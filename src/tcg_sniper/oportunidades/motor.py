"""Motor de oportunidades: decide, para uma leitura da página do produto na Amazon, se há uma
oferta elegível e o que fazer com a oportunidade do anúncio. Funções puras."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from tcg_sniper.db.models import ConfigAmazon, Envio

CEM = Decimal(100)


@dataclass(frozen=True)
class Regras:
    desconto_min_pct: int
    realerta_queda_pct: int
    liga_preco_max_idade_h: int
    vendedor_min_positivas_pct: int
    vendedor_min_avaliacoes: int

    @classmethod
    def de(cls, config: ConfigAmazon) -> "Regras":
        return cls(
            desconto_min_pct=config.desconto_min_pct,
            realerta_queda_pct=config.realerta_queda_pct,
            liga_preco_max_idade_h=config.liga_preco_max_idade_h,
            vendedor_min_positivas_pct=config.vendedor_min_positivas_pct,
            vendedor_min_avaliacoes=config.vendedor_min_avaliacoes,
        )


@dataclass(frozen=True)
class Vendedor:
    nome: str | None
    pct_positivas: Decimal | None
    num_avaliacoes: int | None


@dataclass(frozen=True)
class RefLiga:
    preco_a_partir: Decimal | None
    listagem_em: datetime | None
    num_lojas: int | None = None
    preco_medio: Decimal | None = None


@dataclass(frozen=True)
class Leitura:
    preco: Decimal | None
    envio: Envio
    vendedor: Vendedor | None


class Acao(StrEnum):
    ABRIR = "abrir"
    REALERTAR = "realertar"
    ATUALIZAR = "atualizar"
    FECHAR = "fechar"
    NADA = "nada"


def atinge_desconto(preco_amazon: Decimal | None, preco_liga: Decimal | None, desconto_min_pct: int) -> bool:
    """`1 − amazon/liga ≥ desconto/100`, em aritmética exata (sem arredondar): 25% conta."""
    if preco_amazon is None or preco_liga is None or preco_liga <= 0:
        return False
    return preco_amazon * CEM <= preco_liga * (CEM - desconto_min_pct)


def desconto_pct(preco_amazon: Decimal, preco_liga: Decimal) -> Decimal:
    return ((1 - preco_amazon / preco_liga) * CEM).quantize(Decimal("0.01"), ROUND_HALF_UP)


def vendedor_confiavel(vendedor: Vendedor | None, regras: Regras) -> bool:
    return (
        vendedor is not None
        and vendedor.pct_positivas is not None
        and vendedor.num_avaliacoes is not None
        and vendedor.pct_positivas >= regras.vendedor_min_positivas_pct
        and vendedor.num_avaliacoes >= regras.vendedor_min_avaliacoes
    )


def _vendedor_elegivel(leitura: Leitura, regras: Regras) -> bool:
    if leitura.envio is Envio.AMAZON:
        return True
    if leitura.envio is Envio.FBA:
        return vendedor_confiavel(leitura.vendedor, regras)
    return False


def _referencia_valida(ref: RefLiga, regras: Regras, agora: datetime) -> bool:
    return (
        ref.preco_a_partir is not None
        and ref.listagem_em is not None
        and agora - ref.listagem_em <= timedelta(hours=regras.liga_preco_max_idade_h)
    )


def elegivel(leitura: Leitura, ref: RefLiga, regras: Regras, agora: datetime) -> bool:
    return (
        _vendedor_elegivel(leitura, regras)
        and _referencia_valida(ref, regras, agora)
        and atinge_desconto(leitura.preco, ref.preco_a_partir, regras.desconto_min_pct)
    )


def decidir(
    leitura: Leitura, ref: RefLiga, regras: Regras, agora: datetime, preco_alertado: Decimal | None
) -> Acao:
    """`preco_alertado` é o da oportunidade aberta do anúncio (None se não há aberta)."""
    aberta = preco_alertado is not None
    if not elegivel(leitura, ref, regras, agora):
        return Acao.FECHAR if aberta else Acao.NADA
    if not aberta:
        return Acao.ABRIR
    if leitura.preco * CEM <= preco_alertado * (CEM - regras.realerta_queda_pct):
        return Acao.REALERTAR
    return Acao.ATUALIZAR
