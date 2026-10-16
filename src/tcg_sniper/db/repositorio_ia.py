"""Tabelas da IA: configuração, registro de chamadas (orçamento) e avaliações de casamento."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tcg_sniper.db.models import (
    PADROES_CONFIG_IA,
    AnuncioAmazon,
    AvaliacaoIA,
    ChamadaIA,
    ConfigIA,
    PrecoAtualAmazon,
    PrecoAtualLiga,
    ProdutoLiga,
    StatusCasamento,
)
from tcg_sniper.db.repositorio import agora_utc


def obter_config_ia(s: Session, agora: datetime | None = None) -> ConfigIA:
    s.execute(
        pg_insert(ConfigIA)
        .values(id=1, **PADROES_CONFIG_IA, atualizado_em=agora or agora_utc())
        .on_conflict_do_nothing(index_elements=[ConfigIA.id])
    )
    return s.get(ConfigIA, 1, populate_existing=True)


def salvar_config_ia(s: Session, valores: Mapping[str, object], agora: datetime) -> None:
    obter_config_ia(s, agora)
    s.execute(update(ConfigIA).where(ConfigIA.id == 1).values(**valores, atualizado_em=agora))
    s.flush()


def registrar_chamada(
    s: Session,
    *,
    em: datetime,
    finalidade: str,
    modelo: str,
    tokens_entrada: int,
    tokens_saida: int,
    custo_usd: Decimal,
    ok: bool,
    erro: str | None,
) -> ChamadaIA:
    chamada = ChamadaIA(
        em=em, finalidade=finalidade, modelo=modelo, tokens_entrada=tokens_entrada,
        tokens_saida=tokens_saida, custo_usd=custo_usd, ok=ok, erro=erro,
    )
    s.add(chamada)
    s.flush()
    return chamada


@dataclass(frozen=True)
class Gasto:
    dia_usd: Decimal
    mes_usd: Decimal
    chamadas_dia: int


def gasto(s: Session, agora: datetime, zona: ZoneInfo) -> Gasto:
    """Gasto e chamadas desde o início do dia e do mês, no fuso `zona`."""
    local = agora.astimezone(zona)
    inicio_dia = local.replace(hour=0, minute=0, second=0, microsecond=0)
    inicio_mes = inicio_dia.replace(day=1)
    dia, chamadas = s.execute(
        select(func.coalesce(func.sum(ChamadaIA.custo_usd), 0), func.count()).where(ChamadaIA.em >= inicio_dia)
    ).one()
    mes = s.scalar(select(func.coalesce(func.sum(ChamadaIA.custo_usd), 0)).where(ChamadaIA.em >= inicio_mes))
    return Gasto(Decimal(dia), Decimal(mes), chamadas)


@dataclass(frozen=True)
class ParPendente:
    anuncio: AnuncioAmazon
    produto: ProdutoLiga
    avaliacao: AvaliacaoIA | None
    preco_liga: Decimal | None
    preco_amazon: Decimal | None


def pares_pendentes(s: Session) -> list[ParPendente]:
    """Anúncios pendentes com produto sugerido, com a avaliação desse par (se houver) e os preços atuais.
    Produtos ativos primeiro; depois os vistos mais recentemente."""
    consulta = (
        select(AnuncioAmazon, ProdutoLiga, AvaliacaoIA, PrecoAtualLiga.preco_a_partir, PrecoAtualAmazon.preco)
        .join(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .outerjoin(
            AvaliacaoIA,
            and_(AvaliacaoIA.anuncio_id == AnuncioAmazon.id, AvaliacaoIA.produto_id == AnuncioAmazon.produto_id),
        )
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .where(AnuncioAmazon.status_casamento == StatusCasamento.PENDENTE)
        .order_by(ProdutoLiga.ativo.desc(), AnuncioAmazon.visto_ultimo_em.desc(), AnuncioAmazon.id)
    )
    return [ParPendente(*linha) for linha in s.execute(consulta)]


def gravar_avaliacao(
    s: Session,
    *,
    anuncio_id: int,
    produto_id: int,
    mesmo_produto: bool,
    confianca: int,
    motivo: str,
    modelo: str,
    assinatura: str,
    sem_imagem: bool,
    chamada_id: int | None,
    agora: datetime,
) -> AvaliacaoIA:
    """Cria ou substitui a avaliação do par. `aplicada_em` nunca é apagada aqui."""
    valores = {
        "mesmo_produto": mesmo_produto, "confianca": confianca, "motivo": motivo, "modelo": modelo,
        "assinatura": assinatura, "sem_imagem": sem_imagem, "chamada_id": chamada_id, "avaliado_em": agora,
    }
    stmt = pg_insert(AvaliacaoIA).values(anuncio_id=anuncio_id, produto_id=produto_id, **valores)
    stmt = stmt.on_conflict_do_update(constraint="uq_avaliacao_ia_par", set_=valores).returning(AvaliacaoIA.id)
    avaliacao_id = s.execute(stmt).scalar_one()
    return s.get(AvaliacaoIA, avaliacao_id, populate_existing=True)


def avaliacoes_dos_pares(s: Session, pares: Sequence[tuple[int, int]]) -> dict[tuple[int, int], AvaliacaoIA]:
    if not pares:
        return {}
    consulta = select(AvaliacaoIA).where(tuple_(AvaliacaoIA.anuncio_id, AvaliacaoIA.produto_id).in_(list(pares)))
    return {(a.anuncio_id, a.produto_id): a for a in s.scalars(consulta)}


@dataclass(frozen=True)
class ParDecidido:
    anuncio: AnuncioAmazon
    produto: ProdutoLiga
    confirmado: bool
    preco_liga: Decimal | None
    preco_amazon: Decimal | None


def pares_decididos(s: Session, limite: int | None) -> list[ParDecidido]:
    """Anúncios confirmados ou ignorados pelo usuário (não pelo automático), para a avaliação. A decisão é
    do automático só se ainda for a dele (`aplicada_em == revisado_em`): corrigida pelo usuário, conta."""
    aplicada = (
        select(AvaliacaoIA.id)
        .where(
            AvaliacaoIA.anuncio_id == AnuncioAmazon.id,
            AvaliacaoIA.produto_id == AnuncioAmazon.produto_id,
            AvaliacaoIA.aplicada_em == AnuncioAmazon.revisado_em,
        )
        .exists()
    )
    consulta = (
        select(AnuncioAmazon, ProdutoLiga, PrecoAtualLiga.preco_a_partir, PrecoAtualAmazon.preco)
        .join(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .where(
            AnuncioAmazon.status_casamento.in_([StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO]),
            ~aplicada,
        )
        .order_by(AnuncioAmazon.id)
        .limit(limite)
    )
    return [
        ParDecidido(anuncio, produto, anuncio.status_casamento is StatusCasamento.CONFIRMADO, liga, amazon)
        for anuncio, produto, liga, amazon in s.execute(consulta)
    ]
