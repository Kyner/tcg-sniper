from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tcg_sniper.db.models import Envio
from tcg_sniper.oportunidades.motor import (
    Acao,
    Leitura,
    RefLiga,
    Regras,
    Vendedor,
    atinge_desconto,
    decidir,
    desconto_pct,
    elegivel,
)

AGORA = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)
REGRAS = Regras(
    desconto_min_pct=25,
    realerta_queda_pct=5,
    liga_preco_max_idade_h=48,
    vendedor_min_positivas_pct=90,
    vendedor_min_avaliacoes=100,
)
LIGA = RefLiga(preco_a_partir=Decimal("1000.00"), listagem_em=AGORA - timedelta(hours=2))
CONFIAVEL = Vendedor("Loja", Decimal(97), 2340)


def leitura(preco="700.00", envio=Envio.AMAZON, vendedor=None):
    return Leitura(None if preco is None else Decimal(preco), envio, vendedor)


@pytest.mark.parametrize(
    ("leit", "ref", "esperado"),
    [
        (leitura(), LIGA, True),
        (leitura(envio=Envio.FBA, vendedor=CONFIAVEL), LIGA, True),
        (leitura(envio=Envio.FBA, vendedor=Vendedor("Loja", Decimal(89), 2340)), LIGA, False),
        (leitura(envio=Envio.FBA, vendedor=Vendedor("Loja", Decimal(97), 99)), LIGA, False),
        (leitura(envio=Envio.FBA, vendedor=Vendedor("Loja", None, None)), LIGA, False),
        (leitura(envio=Envio.FBA, vendedor=None), LIGA, False),
        (leitura(envio=Envio.PROPRIO, vendedor=CONFIAVEL), LIGA, False),
        (leitura(envio=Envio.DESCONHECIDO), LIGA, False),
        (leitura(), RefLiga(None, AGORA), False),
        (leitura(), RefLiga(Decimal("1000.00"), None), False),
        (leitura(), RefLiga(Decimal("1000.00"), AGORA - timedelta(hours=48)), True),
        (leitura(), RefLiga(Decimal("1000.00"), AGORA - timedelta(hours=49)), False),
        (leitura("750.00"), LIGA, True),  # exatamente 25%: o limite é inclusivo
        (leitura("750.10"), LIGA, False),  # 24,99%
        (leitura(None), LIGA, False),
        (leitura("0.00"), LIGA, False),  # preço zerado é leitura errada, não 100% de desconto
    ],
)
def test_elegivel(leit, ref, esperado):
    assert elegivel(leit, ref, REGRAS, AGORA) is esperado


def test_atinge_desconto_sem_arredondamento():
    assert atinge_desconto(Decimal("750.00"), Decimal("1000.00"), 25)
    assert not atinge_desconto(Decimal("750.01"), Decimal("1000.00"), 25)
    assert not atinge_desconto(None, Decimal("1000.00"), 25)
    assert not atinge_desconto(Decimal("1.00"), None, 25)
    assert not atinge_desconto(Decimal("1.00"), Decimal(0), 25)
    assert atinge_desconto(Decimal("0.00"), Decimal("1000.00"), 25) is False
    assert atinge_desconto(Decimal("-1.00"), Decimal("1000.00"), 25) is False


def test_desconto_pct():
    assert desconto_pct(Decimal("599.90"), Decimal("889.00")) == Decimal("32.52")


@pytest.mark.parametrize(
    ("preco", "preco_alertado", "acao"),
    [
        ("700.00", None, Acao.ABRIR),
        ("700.00", Decimal("700.00"), Acao.ATUALIZAR),
        ("665.00", Decimal("700.00"), Acao.REALERTAR),  # queda de exatamente 5%
        ("665.70", Decimal("700.00"), Acao.ATUALIZAR),  # queda de 4,9%
        ("760.00", Decimal("700.00"), Acao.FECHAR),  # deixou de ter 25%
        ("760.00", None, Acao.NADA),
    ],
)
def test_decidir(preco, preco_alertado, acao):
    assert decidir(leitura(preco), LIGA, REGRAS, AGORA, preco_alertado) is acao


def test_decidir_fecha_quando_o_vendedor_deixa_de_ser_elegivel():
    assert decidir(leitura(envio=Envio.PROPRIO), LIGA, REGRAS, AGORA, Decimal("700.00")) is Acao.FECHAR
