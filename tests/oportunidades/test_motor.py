import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tcg_sniper.db.models import Envio
from tcg_sniper.db.models import MotivoEncerramento as M
from tcg_sniper.oportunidades.motor import (
    Aberta,
    Acao,
    Leitura,
    RefLiga,
    Regras,
    Vendedor,
    atinge_desconto,
    decidir,
    desconto_pct,
    elegivel,
    motivo_inelegivel,
    vendedor_elegivel,
)

AGORA = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)
REGRAS = Regras(
    desconto_min_pct=25,
    realerta_queda_pct=5,
    liga_preco_max_idade_h=48,
    vendedor_min_positivas_pct=90,
    vendedor_min_avaliacoes=100,
    carencia_encerramento_min=30,
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
    regras = dataclasses.replace(REGRAS, carencia_encerramento_min=0)
    aberta = None if preco_alertado is None else Aberta(preco_alertado, LIGA.preco_a_partir)
    assert decidir(leitura(preco), LIGA, regras, AGORA, aberta).acao is acao


def test_decidir_fecha_quando_o_vendedor_deixa_de_ser_elegivel():
    regras = dataclasses.replace(REGRAS, carencia_encerramento_min=0)
    aberta = Aberta(Decimal("700.00"), LIGA.preco_a_partir)
    d = decidir(leitura(envio=Envio.PROPRIO), LIGA, regras, AGORA, aberta)
    assert (d.acao, d.motivo) == (Acao.FECHAR, M.VENDEDOR)


BOA = leitura()
REF = LIGA


def test_motivo_none_quando_elegivel():
    assert motivo_inelegivel(BOA, REF, REGRAS, AGORA) is None


def test_motivos_em_ordem():
    velha = RefLiga(Decimal(1000), AGORA - timedelta(hours=49))
    sem_preco = leitura(None, Envio.DESCONHECIDO)
    proprio = leitura("700", Envio.PROPRIO)
    cara = leitura("800")
    assert motivo_inelegivel(sem_preco, velha, REGRAS, AGORA) is M.LIGA_DESATUALIZADA
    assert motivo_inelegivel(sem_preco, REF, REGRAS, AGORA) is M.OFERTA_SUMIU
    assert motivo_inelegivel(proprio, REF, REGRAS, AGORA) is M.VENDEDOR
    assert motivo_inelegivel(cara, REF, REGRAS, AGORA) is M.PRECO_SUBIU
    # 800 dá 27% contra a Liga de antes (1.100), não contra a de agora (1.000): foi a Liga que caiu
    assert motivo_inelegivel(cara, REF, REGRAS, AGORA, preco_liga_anterior=Decimal(1100)) is M.LIGA_CAIU


def test_primeira_leitura_ruim_marca_risco():
    aberta = Aberta(Decimal(700), Decimal(1000))
    d = decidir(leitura("800"), REF, REGRAS, AGORA, aberta)
    assert (d.acao, d.motivo) == (Acao.EM_RISCO, M.PRECO_SUBIU)


def test_risco_antes_da_carencia_continua_em_risco():
    aberta = Aberta(Decimal(700), Decimal(1000), em_risco_desde=AGORA - timedelta(minutes=29))
    assert decidir(leitura(None, Envio.DESCONHECIDO), REF, REGRAS, AGORA, aberta).acao is Acao.EM_RISCO


def test_carencia_vencida_fecha_com_o_motivo_da_leitura():
    aberta = Aberta(Decimal(700), Decimal(1000), em_risco_desde=AGORA - timedelta(minutes=30))
    d = decidir(leitura(None, Envio.DESCONHECIDO), REF, REGRAS, AGORA, aberta)
    assert (d.acao, d.motivo) == (Acao.FECHAR, M.OFERTA_SUMIU)


def test_carencia_zero_fecha_na_primeira_leitura_ruim():
    regras = dataclasses.replace(REGRAS, carencia_encerramento_min=0)
    d = decidir(leitura(None, Envio.DESCONHECIDO), REF, regras, AGORA, Aberta(Decimal(700), Decimal(1000)))
    assert d.acao is Acao.FECHAR


def test_elegivel_em_risco_recupera():
    aberta = Aberta(Decimal(700), Decimal(1000), em_risco_desde=AGORA - timedelta(minutes=10))
    assert decidir(BOA, REF, REGRAS, AGORA, aberta).acao is Acao.RECUPERAR


def test_em_risco_com_queda_realerta():
    aberta = Aberta(Decimal(700), Decimal(1000), em_risco_desde=AGORA - timedelta(minutes=10))
    assert decidir(leitura("650"), REF, REGRAS, AGORA, aberta).acao is Acao.REALERTAR


def test_sem_aberta_inelegivel_nada_e_elegivel_abre():
    assert decidir(leitura(None, Envio.DESCONHECIDO), REF, REGRAS, AGORA, None).acao is Acao.NADA
    assert decidir(BOA, REF, REGRAS, AGORA, None).acao is Acao.ABRIR


REGRAS_ELEGIVEL = Regras(
    desconto_min_pct=25, realerta_queda_pct=5, liga_preco_max_idade_h=48,
    vendedor_min_positivas_pct=90, vendedor_min_avaliacoes=100, carencia_encerramento_min=30,
)


def test_vendedor_elegivel():
    confiavel = Vendedor("Loja Boa", Decimal(98), 5000)
    poucas = Vendedor("Shazaar", Decimal(100), 66)
    assert vendedor_elegivel(Envio.AMAZON, None, REGRAS_ELEGIVEL)
    assert vendedor_elegivel(Envio.FBA, confiavel, REGRAS_ELEGIVEL)
    assert not vendedor_elegivel(Envio.FBA, poucas, REGRAS_ELEGIVEL)
    assert not vendedor_elegivel(Envio.FBA, None, REGRAS_ELEGIVEL)
    assert not vendedor_elegivel(Envio.PROPRIO, confiavel, REGRAS_ELEGIVEL)
    assert not vendedor_elegivel(Envio.DESCONHECIDO, confiavel, REGRAS_ELEGIVEL)
