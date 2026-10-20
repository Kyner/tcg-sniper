"""Operações de banco do coletor da Amazon, do casamento e das oportunidades."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, delete, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tcg_sniper.coletor_amazon.modelos import SELLER_AMAZON, AvaliacaoVendedor, OfertaLista, ResultadoBusca
from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db.models import (
    DATA,
    AnuncioAmazon,
    Casamento,
    ConferenciaCheckout,
    ConfigAmazon,
    Envio,
    FilaAmazon,
    MotivoEncerramento,
    OfertaAmazon,
    Oportunidade,
    OrigemPreco,
    PrecoAmazon,
    PrecoAtualAmazon,
    PrecoAtualLiga,
    ProdutoLiga,
    SituacaoCheckout,
    StatusCasamento,
    VendedorAmazon,
)
from tcg_sniper.oportunidades import motor

TITULO_MANUAL = "Informado manualmente"  # título provisório do anúncio colado à mão
ESPERA_CARRINHO_OCUPADO = timedelta(hours=1)  # carrinho com item do usuário: não confere por 1 h


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


def _descoberta_liberada(agora: datetime | None, casados_dias: int | None):
    """Sem par confirmado: sempre (no ritmo da fila). Com par confirmado: só se nunca buscado ou se a
    última busca tem `casados_dias` dias ou mais (busca semanal)."""
    if agora is None or casados_dias is None:
        return literal(True)
    return or_(
        FilaAmazon.produto_id.not_in(repo_casamento.produtos_casados()),
        FilaAmazon.ultima_busca_em.is_(None),
        FilaAmazon.ultima_busca_em <= agora - timedelta(days=casados_dias),
    )


def ids_na_fila(s: Session, agora: datetime | None = None, casados_dias: int | None = None) -> set[int]:
    return set(s.scalars(select(FilaAmazon.produto_id).where(_descoberta_liberada(agora, casados_dias))))


def proximo_da_fila(s: Session, agora: datetime, casados_dias: int | None = None) -> FilaAmazon | None:
    """O vencido há mais tempo; no empate, o de maior "À partir de" na Liga. Com `casados_dias`, os
    produtos já casados só entram na busca semanal."""
    consulta = (
        select(FilaAmazon)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == FilaAmazon.produto_id)
        .where(FilaAmazon.proxima_busca_em <= agora, _descoberta_liberada(agora, casados_dias))
        .order_by(
            FilaAmazon.proxima_busca_em,
            PrecoAtualLiga.preco_a_partir.desc().nulls_last(),
            FilaAmazon.produto_id,
        )
        .limit(1)
    )
    return s.scalar(consulta)


def reagendar(
    s: Session, produto_id: int, agora: datetime, proxima: datetime, teve_candidato: bool, indice_termo: int = 0
) -> None:
    """`indice_termo`: o próximo termo da sequência do produto (a varredura calcula; ver `sequencia_de_termos`)."""
    valores: dict[str, datetime | int] = {
        "ultima_busca_em": agora,
        "proxima_busca_em": proxima,
        "indice_termo": indice_termo,
    }
    if teve_candidato:
        valores["ultimo_candidato_em"] = agora
    s.execute(update(FilaAmazon).where(FilaAmazon.produto_id == produto_id).values(**valores))
    s.flush()


# --- anúncios e preços ----------------------------------------------------------------------


@dataclass(frozen=True)
class GravacaoBusca:
    anuncios: list[AnuncioAmazon]  # na ordem da busca, sem ASIN repetido
    pares_novos: int  # pares (anúncio, produto buscado) criados pendentes nesta busca: os candidatos


def gravar_busca(
    s: Session, itens: Sequence[ResultadoBusca], produto_id: int, agora: datetime, zona: ZoneInfo
) -> GravacaoBusca:
    """Upsert dos anúncios da busca, do preço de origem `busca` e do par (anúncio, produto buscado): par
    novo fica pendente (ou ignorado `outro_confirmado`, se o anúncio já é confirmado de outro produto);
    par existente só ganha `visto_ultimo_em` (status não muda). Par pendente novo marca
    `fila_amazon.ultimo_par_novo_em` (a seca da busca alternativa conta daí). ASIN repetido na mesma busca
    vale uma vez (o primeiro cartão). Devolve os anúncios na ordem da busca.

    Travas (ver repositorio_casamento): os ASINs novos entram em ordem de ASIN sem tocar nos existentes
    (`ON CONFLICT DO NOTHING` não trava a linha); depois todos os anúncios da busca são travados de uma vez
    em ordem crescente de id e só então atualizados, com preço e par. Assim duas buscas, ou uma busca e
    uma ação de casamento, nunca se travam mutuamente. A linha do produto em `fila_amazon` é travada por
    último (o `UPDATE` de `ultimo_par_novo_em`), depois dos anúncios, como em `casar_link_manual`; quem
    travar a fila antes de um anúncio inverte a ordem. Anúncio que sumiu no meio (ninguém apaga anúncios
    hoje) fica fora da lista devolvida."""
    unicos: dict[str, ResultadoBusca] = {}
    for item in itens:
        unicos.setdefault(item.asin, item)
    for asin in sorted(unicos):
        item = unicos[asin]
        s.execute(
            pg_insert(AnuncioAmazon)
            .values(
                asin=item.asin,
                titulo=item.titulo,
                url=item.url,
                visto_primeiro_em=agora,
                visto_ultimo_em=agora,
                imagem_url=item.imagem_url,
            )
            .on_conflict_do_nothing(index_elements=[AnuncioAmazon.asin])
        )
    travados = s.execute(
        select(AnuncioAmazon.id, AnuncioAmazon.asin)
        .where(AnuncioAmazon.asin.in_(unicos))
        .order_by(AnuncioAmazon.id)
        .with_for_update()
    ).all()
    pares_novos = 0
    for anuncio_id, asin in travados:
        item = unicos[asin]
        s.execute(
            update(AnuncioAmazon)
            .where(AnuncioAmazon.id == anuncio_id)
            .values(
                titulo=item.titulo,
                url=item.url,
                visto_ultimo_em=agora,
                # a busca só preenche a imagem vazia; a página do produto pode trocar
                imagem_url=func.coalesce(AnuncioAmazon.imagem_url, item.imagem_url),
            )
        )
        registrar_preco(s, anuncio_id, item.preco, OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, agora, zona)
        par, criado = repo_casamento.registrar_visto(s, anuncio_id, produto_id, agora)
        if criado and par.status is StatusCasamento.PENDENTE:
            pares_novos += 1
    if pares_novos:
        s.execute(update(FilaAmazon).where(FilaAmazon.produto_id == produto_id).values(ultimo_par_novo_em=agora))
    s.flush()
    por_asin = {
        a.asin: a
        for a in s.scalars(
            select(AnuncioAmazon).where(AnuncioAmazon.asin.in_(unicos)).execution_options(populate_existing=True)
        )
    }
    return GravacaoBusca([por_asin[asin] for asin in unicos if asin in por_asin], pares_novos)


def _validade_da_leitura(intervalo_min: int) -> timedelta:
    """Uma leitura do monitor vale por dois intervalos (uma volta perdida não a derruba)."""
    return timedelta(minutes=2 * intervalo_min)


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
    """Atualiza o preço atual e acrescenta ao histórico se o preço (ou, numa leitura completa,
    vendedor/envio) mudou desde a última leitura do anúncio na mesma origem, ou se é a primeira
    leitura do dia. Vendedor/envio só mudam numa leitura de origem `produto` ou `ofertas`; a busca
    não troca o preço atual lido nas ofertas enquanto essa leitura tem até 2 × `monitor_intervalo_min`
    (depois disso troca, para o preço não congelar com o monitor desligado ou fora do anúncio).

    Contrato com o monitor: a leitura das ofertas chama `gravar_ofertas(lida_em=agora)` e esta função
    com o mesmo `agora`; `PrecoAtualAmazon.coletado_em` aponta a leitura atual das ofertas
    (`ofertas_da_ultima_leitura`, `candidatas_ao_checkout`). Devolve True se gravou no histórico."""
    ultimo = s.scalar(
        select(PrecoAmazon)
        .where(PrecoAmazon.anuncio_id == anuncio_id, PrecoAmazon.origem == origem)
        .order_by(PrecoAmazon.coletado_em.desc(), PrecoAmazon.id.desc())
        .limit(1)
    )
    inicio_do_dia = datetime.combine(agora.astimezone(zona).date(), time(0), tzinfo=zona)
    leitura_completa = origem in (OrigemPreco.PRODUTO, OrigemPreco.OFERTAS)
    gravar = (
        ultimo is None
        or ultimo.coletado_em < inicio_do_dia
        or ultimo.preco != preco
        or (leitura_completa and (ultimo.vendedor_id, ultimo.envio) != (vendedor_id, envio))
    )
    if gravar:
        s.add(
            PrecoAmazon(
                anuncio_id=anuncio_id, coletado_em=agora, preco=preco, origem=origem,
                vendedor_id=vendedor_id, envio=envio,
            )
        )
    if origem is OrigemPreco.BUSCA:
        leitura_atual = s.execute(
            select(PrecoAtualAmazon.origem, PrecoAtualAmazon.coletado_em).where(PrecoAtualAmazon.anuncio_id == anuncio_id)
        ).first()
        if leitura_atual is not None and leitura_atual.origem is OrigemPreco.OFERTAS:
            intervalo = s.scalar(select(ConfigAmazon.monitor_intervalo_min).where(ConfigAmazon.id == 1))
            if leitura_atual.coletado_em >= agora - _validade_da_leitura(intervalo):
                s.flush()  # o monitor manda no preço atual: a busca só entra no histórico
                return gravar
    atual: dict[str, object] = {"preco": preco, "origem": origem, "coletado_em": agora}
    if leitura_completa:
        atual |= {"vendedor_id": vendedor_id, "envio": envio}
    s.execute(
        pg_insert(PrecoAtualAmazon)
        .values(anuncio_id=anuncio_id, preco=preco, origem=origem, vendedor_id=vendedor_id, envio=envio, coletado_em=agora)
        .on_conflict_do_update(index_elements=[PrecoAtualAmazon.anuncio_id], set_=atual)
    )
    s.flush()
    return gravar


def confirmados_com_referencia(s: Session, anuncio_ids: Sequence[int]) -> list[LinhaConfirmada]:
    """Dos anúncios dados, os com par confirmado, com o produto do par, o preço atual e o preço da Liga."""
    if not anuncio_ids:
        return []
    consulta = (
        select(AnuncioAmazon, ProdutoLiga, PrecoAtualAmazon, PrecoAtualLiga)
        .join(Casamento, repo_casamento.condicao_confirmado(AnuncioAmazon.id))
        .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
        .join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(AnuncioAmazon.id.in_(anuncio_ids))
        .order_by(AnuncioAmazon.id)
        .execution_options(populate_existing=True)
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
    conferido: bool,
) -> Oportunidade:
    """`conferido` (obrigatório, sem padrão): o aviso sai com o preço conferido no checkout (True) ou
    com o anunciado (False)."""
    op = Oportunidade(
        anuncio_id=anuncio_id, produto_id=produto_id, preco_amazon=preco_amazon, preco_liga=preco_liga,
        desconto_pct=desconto_pct, vendedor_id=vendedor_id, envio=envio, aberta_em=agora,
        alertada_em=agora, preco_alertado=preco_amazon, alerta_conferido=conferido, menor_preco=preco_amazon,
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
    conferido: bool,
) -> None:
    """`conferido` (obrigatório, sem padrão; só vale com `alertou`): o novo aviso sai com o preço
    conferido no checkout (True) ou com o anunciado (False)."""
    op.preco_amazon, op.preco_liga, op.desconto_pct = preco_amazon, preco_liga, desconto_pct
    op.vendedor_id, op.envio = vendedor_id, envio
    if alertou:
        op.alertada_em, op.preco_alertado, op.alerta_conferido = agora, preco_amazon, conferido
    s.flush()


def fechar_oportunidade(s: Session, op: Oportunidade, agora: datetime) -> None:
    op.fechada_em = agora
    s.flush()


def fechar_oportunidades_sem_leitura(s: Session, agora: datetime, horas: int = 24) -> int:
    """Encerra (motivo `sem_leitura`) as abertas cujo anúncio não aparece em nenhuma leitura há `horas` horas."""
    from tcg_sniper.oportunidades import encerramento  # import tardio: o encerramento usa os repositórios

    velhos = select(AnuncioAmazon.id).where(AnuncioAmazon.visto_ultimo_em < agora - timedelta(hours=horas))
    ids = list(s.scalars(
        select(Oportunidade.id)
        .where(Oportunidade.fechada_em.is_(None), Oportunidade.anuncio_id.in_(velhos))
        .order_by(Oportunidade.id)
    ))
    return sum(encerramento.encerrar(s, op_id, MotivoEncerramento.SEM_LEITURA, agora) for op_id in ids)


# --- link manual ----------------------------------------------------------------------------


def priorizar_na_fila(s: Session, produto_id: int, agora: datetime) -> bool:
    """Põe o produto na frente da fila da Amazon. Sem linha na fila, não faz nada e devolve False (a
    próxima sincronização o insere já vencido)."""
    primeiro = s.scalar(select(func.min(FilaAmazon.proxima_busca_em)).where(FilaAmazon.produto_id != produto_id))
    quando = agora if primeiro is None else min(agora, primeiro - timedelta(seconds=1))
    resultado = s.execute(
        update(FilaAmazon).where(FilaAmazon.produto_id == produto_id).values(proxima_busca_em=quando)
    )
    s.flush()
    return resultado.rowcount > 0


def casar_link_manual(s: Session, produto_id: int, asin: str, agora: datetime) -> AnuncioAmazon:
    """Casa o ASIN informado à mão com o produto (par confirmado `manual`, trocando o confirmado anterior
    do anúncio se houver) e põe o produto na frente da fila."""
    anuncio = repo_casamento.casar_asin(s, produto_id, asin, agora, TITULO_MANUAL)
    priorizar_na_fila(s, produto_id, agora)
    return anuncio


def atualizar_leitura(
    s: Session,
    anuncio_id: int,
    titulo: str,
    variacao: str | None,
    agora: datetime,
    imagem_url: str | None = None,
) -> None:
    """Título, opção da variação e imagem lidos na página do produto (a imagem só quando veio), e
    "visto por último" (vale para anúncios fora da busca)."""
    valores: dict[str, object] = {"titulo": titulo, "variacao": variacao, "visto_ultimo_em": agora}
    if imagem_url is not None:
        valores["imagem_url"] = imagem_url
    s.execute(update(AnuncioAmazon).where(AnuncioAmazon.id == anuncio_id).values(**valores))
    s.flush()


# --- monitor de preço -----------------------------------------------------------------------


@dataclass(frozen=True)
class OfertaAvaliada:
    oferta: OfertaLista
    vendedor_id: int | None
    elegivel: bool
    melhor: bool


def gravar_ofertas(s: Session, anuncio_id: int, lida_em: datetime, ofertas: Sequence[OfertaAvaliada]) -> None:
    for avaliada in ofertas:
        o = avaliada.oferta
        s.add(
            OfertaAmazon(
                anuncio_id=anuncio_id, lida_em=lida_em, vendedor_id=avaliada.vendedor_id, vendedor_nome=o.vendedor_nome,
                preco=o.preco, preco_de=o.preco_de, condicao=o.condicao, envio=o.envio, origem_envio=o.origem_envio,
                importada=o.importada, prime=o.prime, elegivel=avaliada.elegivel, melhor=avaliada.melhor,
            )
        )
    s.flush()


def ofertas_da_ultima_leitura(s: Session, anuncio_ids: Sequence[int]) -> dict[int, list[OfertaAmazon]]:
    """As ofertas da leitura atual de cada anúncio, a mais barata primeiro. A leitura atual é a do
    preço atual: `PrecoAtualAmazon` de origem `ofertas` com `coletado_em` igual ao `lida_em` das
    ofertas (o monitor passa o mesmo `agora` a `gravar_ofertas` e `registrar_preco`). Leitura vazia
    (preço nulo, nenhuma oferta) ou preço atual vindo de outra origem: o anúncio fica fora."""
    if not anuncio_ids:
        return {}
    consulta = (
        select(OfertaAmazon)
        .join(PrecoAtualAmazon, _leitura_atual_das_ofertas())
        .where(OfertaAmazon.anuncio_id.in_(anuncio_ids))
        .order_by(OfertaAmazon.anuncio_id, OfertaAmazon.preco, OfertaAmazon.id)
    )
    resultado: dict[int, list[OfertaAmazon]] = {}
    for oferta in s.scalars(consulta):
        resultado.setdefault(oferta.anuncio_id, []).append(oferta)
    return resultado


def _leitura_atual_das_ofertas():
    """Liga `OfertaAmazon` à leitura do preço atual (contrato: mesmo `agora` nas duas gravações)."""
    return and_(
        PrecoAtualAmazon.anuncio_id == OfertaAmazon.anuncio_id,
        PrecoAtualAmazon.origem == OrigemPreco.OFERTAS,
        PrecoAtualAmazon.coletado_em == OfertaAmazon.lida_em,
    )


def limpar_ofertas_antigas(s: Session, agora: datetime, dias: int = 30) -> int:
    resultado = s.execute(delete(OfertaAmazon).where(OfertaAmazon.lida_em < agora - timedelta(days=dias)))
    s.flush()
    return resultado.rowcount


def marcar_visto(s: Session, anuncio_id: int, agora: datetime) -> None:
    """A leitura do monitor conta como "visto" (fechar_oportunidades_sem_leitura usa)."""
    s.execute(update(AnuncioAmazon).where(AnuncioAmazon.id == anuncio_id).values(visto_ultimo_em=agora))
    s.flush()


def _leitura_do_monitor():
    """Quando o monitor leu o anúncio pela última vez (NULL se a última leitura não foi das ofertas)."""
    return case((PrecoAtualAmazon.origem == OrigemPreco.OFERTAS, PrecoAtualAmazon.coletado_em), else_=None)


def _confirmados_ativos(consulta):
    """Anúncios com par confirmado de produto ativo (o par confirmado é um só por anúncio)."""
    return (
        consulta.join(Casamento, repo_casamento.condicao_confirmado(AnuncioAmazon.id))
        .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .where(ProdutoLiga.ativo.is_(True))
    )


def proximo_do_monitor(
    s: Session, agora: datetime, intervalo_min: int, excluir: Collection[int] = ()
) -> tuple[int, str] | None:
    """O anúncio confirmado (de produto ativo) com a leitura de ofertas mais antiga já vencida; os
    nunca lidos primeiro. `excluir`: anúncios que falharam há pouco (a varredura guarda)."""
    leitura = _leitura_do_monitor()
    consulta = _confirmados_ativos(select(AnuncioAmazon.id, AnuncioAmazon.asin)).where(
        or_(leitura.is_(None), leitura <= agora - timedelta(minutes=intervalo_min))
    )
    if excluir:
        consulta = consulta.where(AnuncioAmazon.id.not_in(list(excluir)))
    linha = s.execute(consulta.order_by(leitura.asc().nulls_first(), AnuncioAmazon.id).limit(1)).first()
    return (linha.id, linha.asin) if linha else None


def ids_do_monitor(s: Session) -> set[int]:
    """Todos os anúncios que o monitor acompanha (confirmados, de produto ativo), lidos ou não: a foto da
    volta do monitor que começa agora (ver `varredura_monitor._Rodada`)."""
    return set(s.scalars(_confirmados_ativos(select(AnuncioAmazon.id))))


@dataclass(frozen=True)
class SituacaoMonitor:
    confirmados: int
    nunca_lidos: int
    vencidos: int  # leitura mais velha que o intervalo (ou nunca lidos)
    mais_antiga: datetime | None  # leitura de ofertas mais antiga entre os já lidos
    ultima: datetime | None


def situacao_monitor(s: Session, agora: datetime, intervalo_min: int) -> SituacaoMonitor:
    leitura = _leitura_do_monitor()
    vencido = or_(leitura.is_(None), leitura <= agora - timedelta(minutes=intervalo_min))
    consulta = _confirmados_ativos(
        select(func.count(), func.count(leitura), func.count().filter(vencido), func.min(leitura), func.max(leitura))
        .select_from(AnuncioAmazon)
    )
    total, lidos, vencidos, mais_antiga, ultima = s.execute(consulta).one()
    return SituacaoMonitor(total, total - lidos, vencidos, mais_antiga, ultima)


# --- conferência de checkout ----------------------------------------------------------------


def registrar_conferencia(
    s: Session,
    *,
    em: datetime,
    anuncio_id: int,
    vendedor_nome: str | None,
    preco_anunciado: Decimal,
    itens: Decimal | None,
    frete: Decimal | None,
    impostos: Decimal | None,
    total: Decimal | None,
    situacao: SituacaoCheckout,
    motivo: str | None,
    item_removido: bool,
) -> ConferenciaCheckout:
    conferencia = ConferenciaCheckout(
        em=em, anuncio_id=anuncio_id, vendedor_nome=vendedor_nome, preco_anunciado=preco_anunciado, itens=itens,
        frete=frete, impostos=impostos, total=total, situacao=situacao, motivo=motivo, item_removido=item_removido,
    )
    s.add(conferencia)
    s.flush()
    return conferencia


def concluir_conferencia(
    s: Session,
    conferencia_id: int,
    *,
    em: datetime,
    itens: Decimal | None,
    frete: Decimal | None,
    impostos: Decimal | None,
    total: Decimal | None,
    situacao: SituacaoCheckout,
    motivo: str | None,
    item_removido: bool,
) -> ConferenciaCheckout:
    """Grava o resultado na conferência aberta como "em andamento" antes do clique em adicionar."""
    conferencia = s.get_one(ConferenciaCheckout, conferencia_id)
    conferencia.em, conferencia.itens, conferencia.frete = em, itens, frete
    conferencia.impostos, conferencia.total, conferencia.situacao = impostos, total, situacao
    conferencia.motivo, conferencia.item_removido = motivo, item_removido
    s.flush()
    return conferencia


def _mesma_oferta(anuncio_id: int, vendedor_nome: str | None, preco_anunciado: Decimal):
    return and_(
        ConferenciaCheckout.anuncio_id == anuncio_id,
        ConferenciaCheckout.vendedor_nome.is_not_distinct_from(vendedor_nome),
        ConferenciaCheckout.preco_anunciado == preco_anunciado,
    )


def conferencia_valida(
    s: Session, anuncio_id: int, vendedor_nome: str | None, preco_anunciado: Decimal, agora: datetime, validade_h: int
) -> ConferenciaCheckout | None:
    """A conferência ok mais recente da mesma oferta (ASIN + vendedor + preço) dentro da validade."""
    return s.scalar(
        select(ConferenciaCheckout)
        .where(
            _mesma_oferta(anuncio_id, vendedor_nome, preco_anunciado),
            ConferenciaCheckout.situacao == SituacaoCheckout.OK,
            ConferenciaCheckout.total.is_not(None),
            ConferenciaCheckout.em >= agora - timedelta(hours=validade_h),
        )
        .order_by(ConferenciaCheckout.em.desc(), ConferenciaCheckout.id.desc())
        .limit(1)
    )


def conferencias_validas(
    s: Session, ofertas: Sequence[tuple[int, str | None, Decimal]], agora: datetime, validade_h: int
) -> dict[int, ConferenciaCheckout]:
    """`conferencia_valida` de várias ofertas (anúncio, vendedor, preço) numa consulta só: por anúncio,
    a conferência ok mais recente da mesma oferta dentro da validade (telas com muitas linhas)."""
    chaves = {anuncio_id: (vendedor, preco) for anuncio_id, vendedor, preco in ofertas if preco is not None}
    if not chaves:
        return {}
    consulta = (
        select(ConferenciaCheckout)
        .where(
            ConferenciaCheckout.anuncio_id.in_(list(chaves)),
            ConferenciaCheckout.situacao == SituacaoCheckout.OK,
            ConferenciaCheckout.total.is_not(None),
            ConferenciaCheckout.em >= agora - timedelta(hours=validade_h),
        )
        .order_by(ConferenciaCheckout.em.desc(), ConferenciaCheckout.id.desc())
    )
    resultado: dict[int, ConferenciaCheckout] = {}
    for conferencia in s.scalars(consulta):
        if conferencia.anuncio_id in resultado:
            continue
        if (conferencia.vendedor_nome, conferencia.preco_anunciado) == chaves[conferencia.anuncio_id]:
            resultado[conferencia.anuncio_id] = conferencia
    return resultado


def ultima_conferencia(s: Session, anuncio_id: int | None = None) -> ConferenciaCheckout | None:
    consulta = select(ConferenciaCheckout).order_by(ConferenciaCheckout.em.desc(), ConferenciaCheckout.id.desc()).limit(1)
    if anuncio_id is not None:
        consulta = consulta.where(ConferenciaCheckout.anuncio_id == anuncio_id)
    return s.scalar(consulta)


def carrinho_ocupado_ha_pouco(s: Session, agora: datetime) -> bool:
    """A última conferência (de qualquer anúncio) achou item do usuário no carrinho há menos de
    `ESPERA_CARRINHO_OCUPADO`: nenhuma conferência roda até lá."""
    ultima = ultima_conferencia(s)
    return (
        ultima is not None
        and ultima.situacao is SituacaoCheckout.CARRINHO_OCUPADO
        and agora - ultima.em < ESPERA_CARRINHO_OCUPADO
    )


@dataclass(frozen=True)
class ItemNoCarrinho:
    conferencia_id: int
    asin: str
    preco_anunciado: Decimal
    em: datetime
    tentativas: int


def _item_no_carrinho_pendente():
    """Item que pode ter ficado no carrinho e que o coletor ainda tenta tirar (não está "à mão")."""
    return and_(ConferenciaCheckout.item_removido.is_(False), ConferenciaCheckout.conferir_a_mao_em.is_(None))


def conferencias_com_item_no_carrinho(
    s: Session, agora: datetime | None = None, espera: timedelta | None = None
) -> list[ItemNoCarrinho]:
    """Conferências cujo item pode ter ficado no carrinho e que a retirada automática ainda tenta (as
    "conferir à mão" ficam de fora). Com `agora` e `espera`, só as sem tentativa há menos de `espera`.
    Em rodízio: as nunca tentadas primeiro, depois a tentativa mais antiga (um ASIN não prende os outros)."""
    consulta = (
        select(
            ConferenciaCheckout.id, AnuncioAmazon.asin, ConferenciaCheckout.preco_anunciado, ConferenciaCheckout.em,
            ConferenciaCheckout.retiradas_tentadas,
        )
        .join(AnuncioAmazon, AnuncioAmazon.id == ConferenciaCheckout.anuncio_id)
        .where(_item_no_carrinho_pendente())
        .order_by(
            ConferenciaCheckout.retirada_tentada_em.asc().nulls_first(), ConferenciaCheckout.em, ConferenciaCheckout.id
        )
    )
    if agora is not None and espera is not None:
        consulta = consulta.where(
            or_(ConferenciaCheckout.retirada_tentada_em.is_(None), ConferenciaCheckout.retirada_tentada_em <= agora - espera)
        )
    return [ItemNoCarrinho(*linha) for linha in s.execute(consulta)]


def marcar_item_removido(s: Session, conferencia_id: int) -> bool:
    """"Já conferi" no admin: resolve só uma conferência no estado "conferir à mão" (item ainda não
    removido). Devolve False se nenhuma linha casou (id inexistente, pendente da retirada automática
    ou já resolvida): nada muda."""
    resultado = s.execute(
        update(ConferenciaCheckout)
        .where(
            ConferenciaCheckout.id == conferencia_id,
            ConferenciaCheckout.conferir_a_mao_em.is_not(None),
            ConferenciaCheckout.item_removido.is_(False),
        )
        .values(item_removido=True, conferir_a_mao_em=None)
        .execution_options(synchronize_session="fetch")
    )
    s.flush()
    return resultado.rowcount > 0


def marcar_asin_removido(s: Session, asin: str) -> None:
    """Carrinho ativo conferido sem o ASIN: resolve as conferências pendentes dele (não as "à mão")."""
    ids = select(ConferenciaCheckout.id).join(AnuncioAmazon, AnuncioAmazon.id == ConferenciaCheckout.anuncio_id).where(
        AnuncioAmazon.asin == asin, _item_no_carrinho_pendente()
    )
    s.execute(update(ConferenciaCheckout).where(ConferenciaCheckout.id.in_(ids)).values(item_removido=True))
    s.flush()


def registrar_tentativa_retirada(s: Session, conferencia_id: int, agora: datetime, contar: bool = True) -> int:
    """Grava a hora da tentativa (e soma uma, com `contar`). Devolve quantas tentativas falharam."""
    conferencia = s.get_one(ConferenciaCheckout, conferencia_id)
    conferencia.retirada_tentada_em = agora
    if contar:
        conferencia.retiradas_tentadas += 1
    s.flush()
    return conferencia.retiradas_tentadas


def marcar_conferir_a_mao(s: Session, conferencia_id: int, agora: datetime, razao: str) -> bool:
    """Passa para "conferir à mão" (o coletor não clica mais). Devolve False se já estava (sem novo aviso)."""
    conferencia = s.get_one(ConferenciaCheckout, conferencia_id)
    if conferencia.conferir_a_mao_em is not None or conferencia.item_removido:
        return False
    conferencia.conferir_a_mao_em = agora
    conferencia.motivo = f"{conferencia.motivo}; conferir à mão: {razao}" if conferencia.motivo else f"conferir à mão: {razao}"
    s.flush()
    return True


def conferencias_a_conferir_a_mao(s: Session) -> list[tuple[ConferenciaCheckout, str]]:
    """(conferência, ASIN) que esperam o usuário conferir o carrinho, das mais antigas."""
    consulta = (
        select(ConferenciaCheckout, AnuncioAmazon.asin)
        .join(AnuncioAmazon, AnuncioAmazon.id == ConferenciaCheckout.anuncio_id)
        .where(ConferenciaCheckout.item_removido.is_(False), ConferenciaCheckout.conferir_a_mao_em.is_not(None))
        .order_by(ConferenciaCheckout.conferir_a_mao_em, ConferenciaCheckout.id)
    )
    return [(conferencia, asin) for conferencia, asin in s.execute(consulta)]


@dataclass(frozen=True)
class CandidataCheckout:
    anuncio_id: int
    asin: str
    vendedor_nome: str | None
    preco_anunciado: Decimal


def candidatas_ao_checkout(
    s: Session, agora: datetime, cfg: ConfigAmazon, anuncio_id: int | None = None
) -> list[CandidataCheckout]:
    """A melhor oferta elegível da leitura atual de cada confirmado (produto ativo, preço da Liga em
    dia) com desconto anunciado de pelo menos `desconto_min_pct − margem_candidata_pp`, sem conferência
    ok ou falha da mesma oferta nas últimas `checkout_validade_h` horas. Maior desconto primeiro.

    A leitura atual é a do preço atual (`PrecoAtualAmazon` de origem `ofertas`, `coletado_em` igual
    ao `lida_em` das ofertas: o monitor grava as duas com o mesmo `agora`) e precisa ter até
    2 × `monitor_intervalo_min`; leitura vazia ou velha não vai ao checkout. Com `anuncio_id`, só
    a desse anúncio (o monitor pergunta se a oferta que acabou de ler vai ao checkout)."""
    consulta = (
        select(AnuncioAmazon.id, AnuncioAmazon.asin, OfertaAmazon.vendedor_nome, OfertaAmazon.preco, PrecoAtualLiga.preco_a_partir)
        .join(OfertaAmazon, OfertaAmazon.anuncio_id == AnuncioAmazon.id)
        .join(PrecoAtualAmazon, _leitura_atual_das_ofertas())
        .join(Casamento, repo_casamento.condicao_confirmado(AnuncioAmazon.id))
        .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
        .join(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(
            ProdutoLiga.ativo.is_(True),
            OfertaAmazon.melhor.is_(True),
            OfertaAmazon.elegivel.is_(True),
            PrecoAtualAmazon.coletado_em >= agora - _validade_da_leitura(cfg.monitor_intervalo_min),
            PrecoAtualLiga.listagem_em >= agora - timedelta(hours=cfg.liga_preco_max_idade_h),
        )
    )
    if anuncio_id is not None:
        consulta = consulta.where(AnuncioAmazon.id == anuncio_id)
    minimo = max(0, cfg.desconto_min_pct - cfg.margem_candidata_pp)
    candidatas: list[tuple[Decimal, CandidataCheckout]] = []
    for id_anuncio, asin, vendedor, preco, liga in s.execute(consulta):
        if not motor.atinge_desconto(preco, liga, minimo):
            continue
        conferida = s.scalar(
            select(ConferenciaCheckout.id)
            .where(
                _mesma_oferta(id_anuncio, vendedor, preco),
                ConferenciaCheckout.situacao.in_([SituacaoCheckout.OK, SituacaoCheckout.FALHA]),
                ConferenciaCheckout.em >= agora - timedelta(hours=cfg.checkout_validade_h),
            )
            .limit(1)
        )
        if conferida is None:
            candidatas.append((preco / liga, CandidataCheckout(id_anuncio, asin, vendedor, preco)))
    candidatas.sort(key=lambda par: (par[0], par[1].anuncio_id))
    return [candidata for _, candidata in candidatas]
