"""Operações de banco do coletor da Amazon, do casamento e das oportunidades."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import delete, literal, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tcg_sniper.coletor_amazon.modelos import SELLER_AMAZON, AvaliacaoVendedor, ResultadoBusca
from tcg_sniper.db.models import (
    DATA,
    AnuncioAmazon,
    ConfigAmazon,
    Envio,
    FilaAmazon,
    Oportunidade,
    OrigemPreco,
    PrecoAmazon,
    PrecoAtualAmazon,
    PrecoAtualLiga,
    ProdutoLiga,
    StatusCasamento,
    VendedorAmazon,
)


@dataclass(frozen=True)
class LinhaConfirmada:
    anuncio: AnuncioAmazon
    produto: ProdutoLiga
    atual: PrecoAtualAmazon
    liga: PrecoAtualLiga | None


def obter_config(s: Session) -> ConfigAmazon:
    return s.get(ConfigAmazon, 1, populate_existing=True)


# --- fila -----------------------------------------------------------------------------------


def sincronizar_fila(s: Session, agora: datetime) -> None:
    """Produto ativado na Liga entra na fila (vencido); desativado sai."""
    ativos = select(ProdutoLiga.id).where(ProdutoLiga.ativo.is_(True))
    s.execute(delete(FilaAmazon).where(FilaAmazon.produto_id.not_in(ativos)))
    agora_sql = literal(agora, DATA)
    s.execute(
        pg_insert(FilaAmazon)
        .from_select(
            ["produto_id", "entrou_em", "proxima_busca_em"],
            select(ProdutoLiga.id, agora_sql, agora_sql).where(ProdutoLiga.ativo.is_(True)),
        )
        .on_conflict_do_nothing(index_elements=[FilaAmazon.produto_id])
    )
    s.flush()


def ids_na_fila(s: Session) -> set[int]:
    return set(s.scalars(select(FilaAmazon.produto_id)))


def proximo_da_fila(s: Session, agora: datetime) -> FilaAmazon | None:
    """O vencido há mais tempo; no empate, o de maior "À partir de" na Liga."""
    consulta = (
        select(FilaAmazon)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == FilaAmazon.produto_id)
        .where(FilaAmazon.proxima_busca_em <= agora)
        .order_by(
            FilaAmazon.proxima_busca_em,
            PrecoAtualLiga.preco_a_partir.desc().nulls_last(),
            FilaAmazon.produto_id,
        )
        .limit(1)
    )
    return s.scalar(consulta)


def reagendar(s: Session, produto_id: int, agora: datetime, proxima: datetime, teve_candidato: bool) -> None:
    valores: dict[str, datetime] = {"ultima_busca_em": agora, "proxima_busca_em": proxima}
    if teve_candidato:
        valores["ultimo_candidato_em"] = agora
    s.execute(update(FilaAmazon).where(FilaAmazon.produto_id == produto_id).values(**valores))
    s.flush()


# --- anúncios e preços ----------------------------------------------------------------------


def gravar_busca(
    s: Session, itens: Sequence[ResultadoBusca], produto_id: int, agora: datetime, zona: ZoneInfo
) -> list[AnuncioAmazon]:
    """Upsert dos anúncios da busca (ASIN novo entra pendente com o produto buscado como sugestão;
    a sugestão de um ASIN já conhecido nunca é trocada) e do preço de origem `busca`. ASIN repetido
    na mesma busca vale uma vez (o primeiro cartão). Devolve os anúncios na ordem da busca."""
    unicos: dict[str, ResultadoBusca] = {}
    for item in itens:
        unicos.setdefault(item.asin, item)
    for item in unicos.values():
        stmt = pg_insert(AnuncioAmazon).values(
            asin=item.asin,
            titulo=item.titulo,
            url=item.url,
            produto_id=produto_id,
            status_casamento=StatusCasamento.PENDENTE,
            visto_primeiro_em=agora,
            visto_ultimo_em=agora,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[AnuncioAmazon.asin],
            set_={"titulo": stmt.excluded.titulo, "url": stmt.excluded.url, "visto_ultimo_em": agora},
        ).returning(AnuncioAmazon.id)
        anuncio_id = s.execute(stmt).scalar_one()
        registrar_preco(s, anuncio_id, item.preco, OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, agora, zona)
    s.flush()
    por_asin = {
        a.asin: a
        for a in s.scalars(
            select(AnuncioAmazon).where(AnuncioAmazon.asin.in_(unicos)).execution_options(populate_existing=True)
        )
    }
    return [por_asin[asin] for asin in unicos]


def registrar_preco(
    s: Session,
    anuncio_id: int,
    preco: Decimal | None,
    origem: OrigemPreco,
    vendedor_id: int | None,
    envio: Envio,
    agora: datetime,
    zona: ZoneInfo,
) -> bool:
    """Atualiza o preço atual e acrescenta ao histórico se o preço (ou, na página do produto,
    vendedor/envio) mudou desde a última leitura do anúncio na mesma origem, ou se é a primeira
    leitura do dia. Devolve True se gravou no histórico."""
    ultimo = s.scalar(
        select(PrecoAmazon)
        .where(PrecoAmazon.anuncio_id == anuncio_id, PrecoAmazon.origem == origem)
        .order_by(PrecoAmazon.coletado_em.desc(), PrecoAmazon.id.desc())
        .limit(1)
    )
    inicio_do_dia = datetime.combine(agora.astimezone(zona).date(), time(0), tzinfo=zona)
    gravar = (
        ultimo is None
        or ultimo.coletado_em < inicio_do_dia
        or ultimo.preco != preco
        or (origem is OrigemPreco.PRODUTO and (ultimo.vendedor_id, ultimo.envio) != (vendedor_id, envio))
    )
    if gravar:
        s.add(
            PrecoAmazon(
                anuncio_id=anuncio_id, coletado_em=agora, preco=preco, origem=origem,
                vendedor_id=vendedor_id, envio=envio,
            )
        )
    atual: dict[str, object] = {"preco": preco, "origem": origem, "coletado_em": agora}
    if origem is OrigemPreco.PRODUTO:
        atual |= {"vendedor_id": vendedor_id, "envio": envio}
    s.execute(
        pg_insert(PrecoAtualAmazon)
        .values(anuncio_id=anuncio_id, preco=preco, origem=origem, vendedor_id=vendedor_id, envio=envio, coletado_em=agora)
        .on_conflict_do_update(index_elements=[PrecoAtualAmazon.anuncio_id], set_=atual)
    )
    s.flush()
    return gravar


def confirmados_com_referencia(s: Session, anuncio_ids: Sequence[int]) -> list[LinhaConfirmada]:
    """Dos anúncios dados, os confirmados, com o produto casado, o preço atual e o preço da Liga."""
    if not anuncio_ids:
        return []
    consulta = (
        select(AnuncioAmazon, ProdutoLiga, PrecoAtualAmazon, PrecoAtualLiga)
        .join(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(AnuncioAmazon.id.in_(anuncio_ids), AnuncioAmazon.status_casamento == StatusCasamento.CONFIRMADO)
        .order_by(AnuncioAmazon.id)
    )
    return [LinhaConfirmada(*linha) for linha in s.execute(consulta)]


# --- vendedores -----------------------------------------------------------------------------


def vendedor_da_amazon(s: Session) -> VendedorAmazon:
    return s.scalar(select(VendedorAmazon).where(VendedorAmazon.seller_id == SELLER_AMAZON))


def obter_vendedor(s: Session, seller_id: str) -> VendedorAmazon | None:
    return s.scalar(select(VendedorAmazon).where(VendedorAmazon.seller_id == seller_id))


def gravar_vendedor(s: Session, avaliacao: AvaliacaoVendedor, agora: datetime) -> VendedorAmazon:
    valores = {
        "nome": avaliacao.nome,
        "pct_positivas": avaliacao.pct_positivas,
        "num_avaliacoes": avaliacao.num_avaliacoes,
        "avaliado_em": agora,
    }
    stmt = pg_insert(VendedorAmazon).values(seller_id=avaliacao.seller_id, **valores)
    stmt = stmt.on_conflict_do_update(index_elements=[VendedorAmazon.seller_id], set_=valores)
    s.execute(stmt)
    s.flush()
    return s.scalar(
        select(VendedorAmazon)
        .where(VendedorAmazon.seller_id == avaliacao.seller_id)
        .execution_options(populate_existing=True)
    )


# --- oportunidades --------------------------------------------------------------------------


def oportunidade_aberta(s: Session, anuncio_id: int) -> Oportunidade | None:
    return s.scalar(
        select(Oportunidade).where(Oportunidade.anuncio_id == anuncio_id, Oportunidade.fechada_em.is_(None))
    )


def abrir_oportunidade(
    s: Session,
    *,
    anuncio_id: int,
    produto_id: int,
    preco_amazon: Decimal,
    preco_liga: Decimal,
    desconto_pct: Decimal,
    vendedor_id: int | None,
    envio: Envio,
    agora: datetime,
) -> Oportunidade:
    op = Oportunidade(
        anuncio_id=anuncio_id, produto_id=produto_id, preco_amazon=preco_amazon, preco_liga=preco_liga,
        desconto_pct=desconto_pct, vendedor_id=vendedor_id, envio=envio, aberta_em=agora,
        alertada_em=agora, preco_alertado=preco_amazon,
    )
    s.add(op)
    s.flush()
    return op


def atualizar_oportunidade(
    s: Session,
    op: Oportunidade,
    *,
    preco_amazon: Decimal,
    preco_liga: Decimal,
    desconto_pct: Decimal,
    vendedor_id: int | None,
    envio: Envio,
    alertou: bool,
    agora: datetime,
) -> None:
    op.preco_amazon, op.preco_liga, op.desconto_pct = preco_amazon, preco_liga, desconto_pct
    op.vendedor_id, op.envio = vendedor_id, envio
    if alertou:
        op.alertada_em, op.preco_alertado = agora, preco_amazon
    s.flush()


def fechar_oportunidade(s: Session, op: Oportunidade, agora: datetime) -> None:
    op.fechada_em = agora
    s.flush()


def fechar_oportunidades_do_anuncio(s: Session, anuncio_id: int, agora: datetime) -> int:
    resultado = s.execute(
        update(Oportunidade)
        .where(Oportunidade.anuncio_id == anuncio_id, Oportunidade.fechada_em.is_(None))
        .values(fechada_em=agora)
    )
    s.flush()
    return resultado.rowcount


def fechar_oportunidades_sem_leitura(s: Session, agora: datetime, horas: int = 24) -> int:
    """Fecha as abertas cujo anúncio não aparece em nenhuma busca há `horas` horas."""
    velhos = select(AnuncioAmazon.id).where(AnuncioAmazon.visto_ultimo_em < agora - timedelta(hours=horas))
    resultado = s.execute(
        update(Oportunidade)
        .where(Oportunidade.fechada_em.is_(None), Oportunidade.anuncio_id.in_(velhos))
        .values(fechada_em=agora)
        .execution_options(synchronize_session=False)
    )
    s.flush()
    return resultado.rowcount


# --- casamento ------------------------------------------------------------------------------


def confirmar_casamento(s: Session, anuncio_id: int, produto_id: int, agora: datetime) -> bool:
    """Confirma (ou troca) o produto da Liga do anúncio. Trocar fecha as oportunidades abertas."""
    anuncio = s.get(AnuncioAmazon, anuncio_id)
    if anuncio is None:
        return False
    if anuncio.produto_id != produto_id:
        fechar_oportunidades_do_anuncio(s, anuncio_id, agora)
    anuncio.produto_id = produto_id
    anuncio.status_casamento = StatusCasamento.CONFIRMADO
    anuncio.revisado_em = agora
    s.flush()
    return True


def ignorar_anuncio(s: Session, anuncio_id: int, agora: datetime) -> bool:
    anuncio = s.get(AnuncioAmazon, anuncio_id)
    if anuncio is None:
        return False
    fechar_oportunidades_do_anuncio(s, anuncio_id, agora)
    anuncio.status_casamento = StatusCasamento.IGNORADO
    anuncio.revisado_em = agora
    s.flush()
    return True


def desfazer_casamento(s: Session, anuncio_id: int, agora: datetime) -> bool:
    anuncio = s.get(AnuncioAmazon, anuncio_id)
    if anuncio is None:
        return False
    fechar_oportunidades_do_anuncio(s, anuncio_id, agora)
    anuncio.status_casamento = StatusCasamento.PENDENTE
    anuncio.revisado_em = None
    s.flush()
    return True
