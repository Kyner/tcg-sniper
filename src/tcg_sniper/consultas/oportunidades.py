"""Oportunidades para a área de negócio: períodos, números, por dia, ativas e encerradas. Só dado de mercado
(nada de casamento, IA, vendedor ou conferência de checkout). Alerta errado (`casamento_desfeito`) não é resultado:
fica fora dos números, mas aparece nas encerradas com o motivo."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, extract, func, literal, or_, select
from sqlalchemy.orm import Session

from tcg_sniper.db.models import DATA, AnuncioAmazon, MotivoEncerramento, Oportunidade, ProdutoLiga

PERIODOS: dict[str, int | None] = {"7d": 7, "30d": 30, "90d": 90, "tudo": None}
CENTAVO = Decimal("0.01")
O = Oportunidade


@dataclass(frozen=True)
class ProdutoResumo:
    id: int
    nome: str
    imagem_chave: str | None
    ativo: bool


@dataclass(frozen=True)
class AnuncioResumo:
    titulo: str
    url: str
    imagem_chave: str | None


@dataclass(frozen=True)
class Numeros:
    diferenca_bruta: Decimal
    oportunidades: int
    desconto_medio: Decimal | None
    duracao_media_min: int | None
    produtos: int


@dataclass(frozen=True)
class Dia:
    dia: date
    oportunidades: int


@dataclass(frozen=True)
class Ativa:
    id: int
    produto: ProdutoResumo
    anuncio: AnuncioResumo
    preco_amazon: Decimal
    preco_liga: Decimal
    desconto_pct: Decimal
    aberta_em: datetime
    em_risco_desde: datetime | None
    motivo_risco: str | None


@dataclass(frozen=True)
class Encerrada:
    id: int
    produto: ProdutoResumo
    aberta_em: datetime
    fechada_em: datetime | None
    aberta: bool
    duracao_min: int
    alertas: int
    preco_alertado: Decimal
    menor_preco: Decimal
    preco_liga: Decimal
    desconto_pct: Decimal
    motivo: str | None


@dataclass(frozen=True)
class Pagina:
    itens: list[Encerrada]
    total: int
    pagina: int
    por_pagina: int


def desde_do_periodo(periodo: str, agora: datetime) -> datetime | None:
    if periodo not in PERIODOS:
        raise ValueError(periodo)
    dias = PERIODOS[periodo]
    return None if dias is None else agora - timedelta(days=dias)


def duracao_min(
    aberta_em: datetime, deixou_de_valer_em: datetime | None, fechada_em: datetime | None, agora: datetime
) -> int:
    """Quanto a oferta valeu de verdade: até deixar de valer (sem a carência), até fechar ou, aberta, até agora."""
    fim = deixou_de_valer_em or fechada_em or agora
    return max(0, int((fim - aberta_em).total_seconds() // 60))


def _conta_como_resultado():
    return or_(O.motivo_encerramento.is_(None), O.motivo_encerramento != MotivoEncerramento.CASAMENTO_DESFEITO)


def _no_periodo(desde: datetime | None):
    return O.aberta_em >= desde if desde is not None else literal(True)


def produto_resumo(p: ProdutoLiga) -> ProdutoResumo:
    return ProdutoResumo(p.id, p.nome, p.imagem_chave, p.ativo)


def numeros_periodo(s: Session, desde: datetime | None, agora: datetime) -> Numeros:
    fim = func.coalesce(O.deixou_de_valer_em, O.fechada_em, literal(agora, DATA))
    linha = s.execute(
        select(
            func.count(),
            func.coalesce(func.sum(O.preco_liga - O.preco_alertado), 0),
            func.avg(O.desconto_pct),
            func.avg(extract("epoch", fim - O.aberta_em)),
            func.count(func.distinct(O.produto_id)),
        ).where(_conta_como_resultado(), _no_periodo(desde))
    ).one()
    total, diferenca, desconto, segundos, produtos = linha
    return Numeros(
        diferenca_bruta=Decimal(diferenca).quantize(CENTAVO),
        oportunidades=total,
        desconto_medio=None if desconto is None else Decimal(desconto).quantize(CENTAVO),
        duracao_media_min=None if segundos is None else int(Decimal(segundos) // 60),
        produtos=produtos,
    )


def por_dia(s: Session, desde: datetime | None, agora: datetime, zona: ZoneInfo) -> list[Dia]:
    dia = func.date(func.timezone(zona.key, O.aberta_em))
    contagens = dict(
        s.execute(select(dia, func.count()).where(_conta_como_resultado(), _no_periodo(desde)).group_by(dia)).all()
    )
    hoje = agora.astimezone(zona).date()
    if desde is not None:
        inicio = desde.astimezone(zona).date()
    elif contagens:
        inicio = min(contagens)
    else:
        return []
    return [Dia(inicio + timedelta(days=i), contagens.get(inicio + timedelta(days=i), 0))
            for i in range((hoje - inicio).days + 1)]


def ativas(s: Session) -> list[Ativa]:
    linhas = s.execute(
        select(O, ProdutoLiga, AnuncioAmazon)
        .join(ProdutoLiga, ProdutoLiga.id == O.produto_id)
        .join(AnuncioAmazon, AnuncioAmazon.id == O.anuncio_id)
        .where(O.fechada_em.is_(None))
        .order_by(O.desconto_pct.desc(), O.aberta_em)
    ).all()
    return [
        Ativa(
            id=op.id, produto=produto_resumo(p), anuncio=AnuncioResumo(a.titulo, a.url, a.imagem_chave),
            preco_amazon=op.preco_amazon, preco_liga=op.preco_liga, desconto_pct=op.desconto_pct,
            aberta_em=op.aberta_em, em_risco_desde=op.em_risco_desde,
            motivo_risco=None if op.motivo_risco is None else str(op.motivo_risco),
        )
        for op, p, a in linhas
    ]


def ultima_aberta_em(s: Session) -> datetime | None:
    return s.scalar(select(func.max(O.aberta_em)).where(_conta_como_resultado()))


def linha_oportunidade(op: Oportunidade, produto: ProdutoLiga, agora: datetime) -> Encerrada:
    return Encerrada(
        id=op.id, produto=produto_resumo(produto), aberta_em=op.aberta_em, fechada_em=op.fechada_em,
        aberta=op.fechada_em is None,
        duracao_min=duracao_min(op.aberta_em, op.deixou_de_valer_em, op.fechada_em, agora), alertas=op.alertas,
        preco_alertado=op.preco_alertado, menor_preco=op.menor_preco, preco_liga=op.preco_liga,
        desconto_pct=op.desconto_pct,
        motivo=None if op.motivo_encerramento is None else str(op.motivo_encerramento),
    )


def encerradas(
    s: Session, desde: datetime | None, motivo: MotivoEncerramento | None, pagina: int, agora: datetime,
    por_pagina: int = 25,
) -> Pagina:
    filtro = and_(O.fechada_em.is_not(None), _no_periodo(desde),
                  O.motivo_encerramento == motivo if motivo is not None else literal(True))
    total = s.scalar(select(func.count()).select_from(O).where(filtro))
    linhas = s.execute(
        select(O, ProdutoLiga).join(ProdutoLiga, ProdutoLiga.id == O.produto_id).where(filtro)
        .order_by(O.fechada_em.desc(), O.id.desc()).offset((pagina - 1) * por_pagina).limit(por_pagina)
    ).all()
    return Pagina([linha_oportunidade(op, p, agora) for op, p in linhas], total, pagina, por_pagina)
