"""Motor de oportunidades: decide, para uma leitura da Amazon (melhor oferta da lista de ofertas, com o
preço conferido no checkout quando há conferência: itens + impostos, sem o frete), se há uma oferta
elegível e o que fazer com a oportunidade do anúncio. Funções puras."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from tcg_sniper.db.models import ConfigAmazon, Envio, MotivoEncerramento

CEM = Decimal(100)


@dataclass(frozen=True)
class Regras:
    desconto_min_pct: int
    realerta_queda_pct: int
    liga_preco_max_idade_h: int
    vendedor_min_positivas_pct: int
    vendedor_min_avaliacoes: int
    carencia_encerramento_min: int = 30

    @classmethod
    def de(cls, config: ConfigAmazon) -> "Regras":
        return cls(
            desconto_min_pct=config.desconto_min_pct,
            realerta_queda_pct=config.realerta_queda_pct,
            liga_preco_max_idade_h=config.liga_preco_max_idade_h,
            vendedor_min_positivas_pct=config.vendedor_min_positivas_pct,
            vendedor_min_avaliacoes=config.vendedor_min_avaliacoes,
            carencia_encerramento_min=config.carencia_encerramento_min,
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
    RECUPERAR = "recuperar"  # estava em risco e voltou a ser elegível
    EM_RISCO = "em_risco"  # deixou de ser elegível; a carência ainda não venceu
    FECHAR = "fechar"
    NADA = "nada"


def preco_conferido(
    itens: Decimal | None, impostos: Decimal | None, total: Decimal | None = None, frete: Decimal | None = None
) -> Decimal | None:
    """O preço que vale para a oportunidade quando há conferência de checkout (regra do usuário,
    2026-10-17): itens + impostos, SEM o frete (o frete só aparece à parte). Sem impostos, só os itens;
    sem itens lidos, total menos frete; sem nada, None. Única definição: monitor, conferência e admin
    usam esta."""
    if itens is not None:
        return itens + (impostos or Decimal(0))
    if total is None:
        return None
    return total - (frete or Decimal(0))


def atinge_desconto(preco_amazon: Decimal | None, preco_liga: Decimal | None, desconto_min_pct: int) -> bool:
    """`1 − amazon/liga ≥ desconto/100`, em aritmética exata (sem arredondar): 25% conta.
    Preço da Amazon zero ou negativo é leitura errada, não desconto de 100%."""
    if preco_amazon is None or preco_liga is None or preco_amazon <= 0 or preco_liga <= 0:
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


def vendedor_elegivel(envio: Envio, vendedor: Vendedor | None, regras: Regras) -> bool:
    """Vendido pela Amazon sempre; lojista com envio pela Amazon (FBA) só se confiável; o resto nunca."""
    if envio is Envio.AMAZON:
        return True
    if envio is Envio.FBA:
        return vendedor_confiavel(vendedor, regras)
    return False


def _referencia_valida(ref: RefLiga, regras: Regras, agora: datetime) -> bool:
    return (
        ref.preco_a_partir is not None
        and ref.listagem_em is not None
        and agora - ref.listagem_em <= timedelta(hours=regras.liga_preco_max_idade_h)
    )


@dataclass(frozen=True)
class Aberta:
    """O que o motor precisa da oportunidade aberta do anúncio."""

    preco_alertado: Decimal
    preco_liga: Decimal  # o "À partir de" gravado na última leitura que a manteve aberta
    em_risco_desde: datetime | None = None


@dataclass(frozen=True)
class Decisao:
    acao: Acao
    motivo: MotivoEncerramento | None = None  # EM_RISCO e FECHAR


def motivo_inelegivel(
    leitura: Leitura, ref: RefLiga, regras: Regras, agora: datetime, preco_liga_anterior: Decimal | None = None
) -> MotivoEncerramento | None:
    """Por que a leitura não é elegível, na ordem da spec; None quando é. `preco_liga_anterior` separa
    "a Liga caiu" (a Amazon ainda daria o desconto contra a Liga de antes) de "a Amazon subiu"."""
    if not _referencia_valida(ref, regras, agora):
        return MotivoEncerramento.LIGA_DESATUALIZADA
    if leitura.preco is None or leitura.preco <= 0:
        return MotivoEncerramento.OFERTA_SUMIU
    if not vendedor_elegivel(leitura.envio, leitura.vendedor, regras):
        return MotivoEncerramento.VENDEDOR
    if atinge_desconto(leitura.preco, ref.preco_a_partir, regras.desconto_min_pct):
        return None
    if atinge_desconto(leitura.preco, preco_liga_anterior, regras.desconto_min_pct):
        return MotivoEncerramento.LIGA_CAIU
    return MotivoEncerramento.PRECO_SUBIU


def elegivel(leitura: Leitura, ref: RefLiga, regras: Regras, agora: datetime) -> bool:
    return motivo_inelegivel(leitura, ref, regras, agora) is None


def decidir(leitura: Leitura, ref: RefLiga, regras: Regras, agora: datetime, aberta: Aberta | None) -> Decisao:
    """`aberta`: a oportunidade aberta do anúncio (None se não há). Leitura ruim com aberta: EM_RISCO até
    a carência vencer (contada de `em_risco_desde`), depois FECHAR; carência 0 fecha na hora."""
    motivo = motivo_inelegivel(leitura, ref, regras, agora, aberta.preco_liga if aberta else None)
    if motivo is not None:
        if aberta is None:
            return Decisao(Acao.NADA)
        carencia = timedelta(minutes=regras.carencia_encerramento_min)
        desde = aberta.em_risco_desde or agora
        if agora - desde >= carencia:
            return Decisao(Acao.FECHAR, motivo)
        return Decisao(Acao.EM_RISCO, motivo)
    if aberta is None:
        return Decisao(Acao.ABRIR)
    if leitura.preco * CEM <= aberta.preco_alertado * (CEM - regras.realerta_queda_pct):
        return Decisao(Acao.REALERTAR)
    if aberta.em_risco_desde is not None:
        return Decisao(Acao.RECUPERAR)
    return Decisao(Acao.ATUALIZAR)
