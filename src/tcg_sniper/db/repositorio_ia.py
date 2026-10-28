"""Tabelas da IA: configuração, registro de chamadas (orçamento) e avaliações de casamento."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, aliased

from tcg_sniper.db.models import (
    PADROES_CONFIG_IA,
    AnuncioAmazon,
    AvaliacaoIA,
    Casamento,
    ChamadaIA,
    ConfigIA,
    OrigemCasamento,
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
    reavaliar: bool = False  # Desfazer ou "Reavaliar com a IA": avalia de novo mesmo com a assinatura igual
    # Espera gravada depois de falhas da IA neste par (sobrevive a reinício): quantas, até quando e a assinatura
    ia_falhas: int = 0
    ia_espera_ate: datetime | None = None
    ia_falha_assinatura: str | None = None


def origem_da_decisao(s: Session, anuncio_id: int, produto_id: int | None) -> OrigemCasamento:
    """Decisão do usuário: `sugerido_ia` se a IA avaliou este par (anúncio, produto), senão `manual`."""
    if produto_id is None:
        return OrigemCasamento.MANUAL
    avaliada = s.scalar(
        select(AvaliacaoIA.id).where(AvaliacaoIA.anuncio_id == anuncio_id, AvaliacaoIA.produto_id == produto_id).limit(1)
    )
    return OrigemCasamento.SUGERIDO_IA if avaliada is not None else OrigemCasamento.MANUAL


def pares_pendentes(s: Session, so_descoberta: bool = False) -> list[ParPendente]:
    """Pares pendentes de produtos ativos cujo anúncio não é confirmado de nenhum produto, com a avaliação
    do par (se houver) e os preços atuais; os vistos mais recentemente primeiro. Com `so_descoberta` (o
    casador), pula os pares de produto já casado, exceto os que a busca do produto viu pela primeira vez
    depois do primeiro casamento dele (a busca semanal) e os marcados para reavaliar."""
    confirmado = aliased(Casamento)
    anuncio_confirmado = (
        select(confirmado.anuncio_id)
        .where(confirmado.anuncio_id == Casamento.anuncio_id, confirmado.status == StatusCasamento.CONFIRMADO)
        .exists()
    )
    consulta = (
        select(Casamento, AnuncioAmazon, ProdutoLiga, AvaliacaoIA, PrecoAtualLiga.preco_a_partir, PrecoAtualAmazon.preco)
        .join(AnuncioAmazon, AnuncioAmazon.id == Casamento.anuncio_id)
        .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
        .outerjoin(
            AvaliacaoIA,
            and_(AvaliacaoIA.anuncio_id == Casamento.anuncio_id, AvaliacaoIA.produto_id == Casamento.produto_id),
        )
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .where(Casamento.status == StatusCasamento.PENDENTE, ProdutoLiga.ativo.is_(True), ~anuncio_confirmado)
        .order_by(Casamento.visto_ultimo_em.desc(), Casamento.anuncio_id, Casamento.produto_id)
    )
    if so_descoberta:
        casado = aliased(Casamento)
        casado_desde = (
            select(func.min(casado.revisado_em))
            .where(casado.produto_id == Casamento.produto_id, casado.status == StatusCasamento.CONFIRMADO)
            .scalar_subquery()
        )
        consulta = consulta.where(
            or_(casado_desde.is_(None), Casamento.visto_primeiro_em > casado_desde, Casamento.reavaliar.is_(True))
        )
    return [
        ParPendente(
            anuncio, produto, avaliacao, liga, amazon, par.reavaliar,
            par.ia_falhas, par.ia_espera_ate, par.ia_falha_assinatura,
        )
        for par, anuncio, produto, avaliacao, liga, amazon in s.execute(consulta)
    ]


def registrar_falha_par(
    s: Session, anuncio_id: int, produto_id: int, assinatura: str, agora: datetime, esperas: Sequence[timedelta]
) -> None:
    """A IA falhou neste par: conta mais uma falha seguida (zera se os dados mudaram desde a última) e grava
    até quando esperar (`esperas[n - 1]`, a última vale daí em diante)."""
    par = s.get(Casamento, (anuncio_id, produto_id))
    if par is None:
        return
    n = par.ia_falhas + 1 if par.ia_falha_assinatura == assinatura else 1
    par.ia_falhas = n
    par.ia_falha_assinatura = assinatura
    par.ia_espera_ate = agora + esperas[min(n, len(esperas)) - 1]


def limpar_falha_par(s: Session, anuncio_id: int, produto_id: int) -> None:
    """A IA avaliou o par: some a espera."""
    s.execute(
        update(Casamento)
        .where(Casamento.anuncio_id == anuncio_id, Casamento.produto_id == produto_id)
        .values(ia_falhas=0, ia_espera_ate=None, ia_falha_assinatura=None)
    )


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
    idioma_anuncio: str | None = None,
) -> AvaliacaoIA:
    """Cria ou substitui a avaliação do par. `aplicada_em` nunca é apagada aqui."""
    valores = {
        "mesmo_produto": mesmo_produto, "confianca": confianca, "motivo": motivo, "modelo": modelo,
        "assinatura": assinatura, "sem_imagem": sem_imagem, "chamada_id": chamada_id, "avaliado_em": agora,
        "idioma_anuncio": idioma_anuncio,
    }
    stmt = pg_insert(AvaliacaoIA).values(anuncio_id=anuncio_id, produto_id=produto_id, **valores)
    stmt = stmt.on_conflict_do_update(constraint="uq_avaliacao_ia_par", set_=valores).returning(AvaliacaoIA.id)
    avaliacao_id = s.execute(stmt).scalar_one()
    return s.get(AvaliacaoIA, avaliacao_id, populate_existing=True)


# Idiomas que a IA lê com certeza no anúncio (`indefinido` e vazio não contam como conhecidos).
IDIOMAS_CONHECIDOS = ("pt", "en", "ja", "outro")


def portugues_confirmado(s: Session, produto_id: int) -> bool | None:
    """O produto tem anúncio em português confirmado? True: algum confirmado é `pt`. None: não se sabe (algum
    confirmado sem idioma conhecido, ex.: decidido antes da regra de idioma). False: nenhum confirmado ou só
    de outros idiomas. O idioma é do anúncio: o definido nele (à mão ou por comando) e, sem esse, o da avaliação
    da IA, que vale contra qualquer produto."""
    confirmados = select(Casamento.anuncio_id).where(
        Casamento.produto_id == produto_id, Casamento.status == StatusCasamento.CONFIRMADO
    )
    definidos = {
        anuncio_id: idioma
        for anuncio_id, idioma in s.execute(
            select(AnuncioAmazon.id, AnuncioAmazon.idioma).where(AnuncioAmazon.id.in_(confirmados))
        )
    }
    das_avaliacoes: dict[int, set[str]] = {}
    avaliadas = select(AvaliacaoIA.anuncio_id, AvaliacaoIA.idioma_anuncio).where(
        AvaliacaoIA.anuncio_id.in_(confirmados), AvaliacaoIA.idioma_anuncio.in_(IDIOMAS_CONHECIDOS)
    )
    for anuncio_id, idioma in s.execute(avaliadas):
        das_avaliacoes.setdefault(anuncio_id, set()).add(idioma)
    sem_idioma = False
    for anuncio_id, idioma in definidos.items():
        idiomas = {idioma} if idioma in IDIOMAS_CONHECIDOS else das_avaliacoes.get(anuncio_id, set())
        if "pt" in idiomas:
            return True
        sem_idioma = sem_idioma or not idiomas
    return None if sem_idioma else False


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
    """Pares confirmados ou ignorados por você (não pelo automático nem pelo sistema: `outro_confirmado` fica
    de fora), para a avaliação. A decisão é do automático só se ainda for a dele (`aplicada_em ==
    revisado_em` do par): corrigida por você, conta."""
    aplicada = (
        select(AvaliacaoIA.id)
        .where(
            AvaliacaoIA.anuncio_id == Casamento.anuncio_id,
            AvaliacaoIA.produto_id == Casamento.produto_id,
            AvaliacaoIA.aplicada_em == Casamento.revisado_em,
        )
        .exists()
    )
    consulta = (
        select(Casamento, AnuncioAmazon, ProdutoLiga, PrecoAtualLiga.preco_a_partir, PrecoAtualAmazon.preco)
        .join(AnuncioAmazon, AnuncioAmazon.id == Casamento.anuncio_id)
        .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .where(
            Casamento.status.in_([StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO]),
            Casamento.origem.is_distinct_from(OrigemCasamento.OUTRO_CONFIRMADO),
            ~aplicada,
        )
        .order_by(Casamento.anuncio_id, Casamento.produto_id)
        .limit(limite)
    )
    return [
        ParDecidido(anuncio, produto, par.status is StatusCasamento.CONFIRMADO, liga, amazon)
        for par, anuncio, produto, liga, amazon in s.execute(consulta)
    ]
