"""Situação do catálogo ativo da LigaMagic contada por produto (não por par nem por chamada da IA).

Cada produto ativo cai em exatamente uma situação, nesta ordem de prioridade:
`casado` (≥ 1 par confirmado), `esperando_decisao` (nenhum confirmado, ≥ 1 pendente), `so_ignorados`
(só pares ignorados) e `sem_candidato` (nenhum par). Sem Jinja nem HTTP: o Dashboard do admin e a API
(fase 2) usam a mesma função."""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from tcg_sniper.db.models import AvaliacaoIA, Casamento, ProdutoLiga, StatusCasamento

SITUACOES_PRODUTO = ("casado", "esperando_decisao", "so_ignorados", "sem_candidato")


def inicio_do_dia(agora: datetime, zona: ZoneInfo) -> datetime:
    """Meia-noite de hoje no fuso configurado."""
    return agora.astimezone(zona).replace(hour=0, minute=0, second=0, microsecond=0)


def classificar(confirmados: int, pendentes: int, total: int) -> str:
    """A situação de um produto a partir das contagens dos pares dele (a mesma regra da consulta)."""
    if confirmados:
        return "casado"
    if pendentes:
        return "esperando_decisao"
    return "so_ignorados" if total else "sem_candidato"


@dataclass(frozen=True)
class SituacaoCatalogo:
    produtos_ativos: int
    casado: int
    esperando_decisao: int
    so_ignorados: int
    sem_candidato: int
    com_mais_de_uma_sugestao: int  # produtos com mais de um par (qualquer situação do par)
    com_mais_de_um_confirmado: int
    pares_pendentes: int  # anúncios pendentes dos produtos ativos
    produtos_com_pendentes: int  # produtos distintos desses pendentes
    produtos_avaliados: int  # produtos com pelo menos uma avaliação da IA
    avaliados_hoje: int  # produtos com avaliação feita hoje (no fuso configurado)
    esperando_ia: int  # sem confirmado, com pendente sem avaliação ou marcado para reavaliar
    avaliacoes_total: int
    media_por_produto: float  # avaliações por produto avaliado (1 casa; 0 sem avaliação)

    def por_situacao(self) -> dict[str, int]:
        return {situacao: getattr(self, situacao) for situacao in SITUACOES_PRODUTO}

    def pct(self, situacao: str) -> int:
        """Percentual (inteiro) dos produtos ativos nesta situação."""
        return round(100 * getattr(self, situacao) / self.produtos_ativos) if self.produtos_ativos else 0


def situacao_catalogo(s: Session, agora: datetime, zona: ZoneInfo) -> SituacaoCatalogo:
    ativo = ProdutoLiga.ativo.is_(True)
    pares = (
        select(
            Casamento.produto_id,
            func.count().filter(Casamento.status == StatusCasamento.CONFIRMADO).label("confirmados"),
            func.count().filter(Casamento.status == StatusCasamento.PENDENTE).label("pendentes"),
            func.count().label("total"),
        )
        .group_by(Casamento.produto_id)
        .subquery()
    )
    conf = func.coalesce(pares.c.confirmados, 0)
    pend = func.coalesce(pares.c.pendentes, 0)
    total = func.coalesce(pares.c.total, 0)
    linha = s.execute(
        select(
            func.count(),
            func.count().filter(conf > 0),
            func.count().filter(conf == 0, pend > 0),
            func.count().filter(conf == 0, pend == 0, total > 0),
            func.count().filter(total == 0),
            func.count().filter(total > 1),
            func.count().filter(conf > 1),
            func.coalesce(func.sum(pend), 0),
            func.count().filter(pend > 0),
        )
        .select_from(ProdutoLiga)
        .outerjoin(pares, pares.c.produto_id == ProdutoLiga.id)
        .where(ativo)
    ).one()
    ativos, casado, esperando, so_ignorados, sem, mais_de_uma, mais_de_um_conf, pend_total, prod_pend = linha

    avaliacoes_ativas = select(AvaliacaoIA).join(ProdutoLiga, ProdutoLiga.id == AvaliacaoIA.produto_id).where(ativo)
    produtos_avaliados, avaliacoes_total = s.execute(
        avaliacoes_ativas.with_only_columns(func.count(func.distinct(AvaliacaoIA.produto_id)), func.count())
    ).one()
    avaliados_hoje = s.scalar(
        avaliacoes_ativas.with_only_columns(func.count(func.distinct(AvaliacaoIA.produto_id))).where(
            AvaliacaoIA.avaliado_em >= inicio_do_dia(agora, zona)
        )
    ) or 0

    # O que o casador ainda vai avaliar: pendente sem avaliação (ou marcado para reavaliar) de produto sem
    # confirmado, cujo anúncio não é confirmado de outro produto (esses o casador pula).
    confirmado = aliased(Casamento)
    produto_casado = (
        select(confirmado.produto_id)
        .where(confirmado.produto_id == Casamento.produto_id, confirmado.status == StatusCasamento.CONFIRMADO)
        .exists()
    )
    anuncio_confirmado = (
        select(confirmado.anuncio_id)
        .where(confirmado.anuncio_id == Casamento.anuncio_id, confirmado.status == StatusCasamento.CONFIRMADO)
        .exists()
    )
    esperando_ia = s.scalar(
        select(func.count(func.distinct(Casamento.produto_id)))
        .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
        .outerjoin(
            AvaliacaoIA,
            and_(AvaliacaoIA.anuncio_id == Casamento.anuncio_id, AvaliacaoIA.produto_id == Casamento.produto_id),
        )
        .where(
            ativo,
            Casamento.status == StatusCasamento.PENDENTE,
            ~produto_casado,
            ~anuncio_confirmado,
            or_(AvaliacaoIA.id.is_(None), Casamento.reavaliar.is_(True)),
        )
    ) or 0

    media = round(avaliacoes_total / produtos_avaliados, 1) if produtos_avaliados else 0
    return SituacaoCatalogo(
        produtos_ativos=ativos,
        casado=casado,
        esperando_decisao=esperando,
        so_ignorados=so_ignorados,
        sem_candidato=sem,
        com_mais_de_uma_sugestao=mais_de_uma,
        com_mais_de_um_confirmado=mais_de_um_conf,
        pares_pendentes=int(pend_total),
        produtos_com_pendentes=prod_pend,
        produtos_avaliados=produtos_avaliados,
        avaliados_hoje=avaliados_hoje,
        esperando_ia=esperando_ia,
        avaliacoes_total=avaliacoes_total,
        media_por_produto=media,
    )
