from datetime import time

import pytest

from tcg_sniper.coletor_amazon.config import CAMPOS, EXPLICACOES, aplicar_config, validar_config
from tcg_sniper.db.models import PADROES_CONFIG_AMAZON, ConfigAmazon


def formulario(**mudancas):
    campos = {
        campo: valor.strftime("%H:%M") if isinstance(valor, time) else str(valor)
        for campo, valor in PADROES_CONFIG_AMAZON.items()
    }
    campos.update({k: str(v) for k, v in mudancas.items()})
    return campos


def test_padroes_sao_validos_e_convertidos():
    valores, erros = validar_config(formulario())
    assert erros == {}
    assert valores == PADROES_CONFIG_AMAZON


def test_todo_campo_tem_explicacao():
    assert set(CAMPOS) == set(PADROES_CONFIG_AMAZON) == set(EXPLICACOES)


@pytest.mark.parametrize(
    ("campo", "valor", "trecho"),
    [
        ("desconto_min_pct", "0", "entre 1 e 90"),
        ("desconto_min_pct", "abc", "número inteiro"),
        ("resultados_por_busca", "49", "entre 1 e 48"),
        ("url_busca", "https://www.amazon.com.br/s?k=x", "{termo}"),
        ("url_busca", "http://www.amazon.com.br/s?k={termo}", "https://"),
        ("janela_inicio", "25:00", "HH:MM"),
        ("janela_inicio", "0800Z", "HH:MM"),
    ],
)
def test_campo_invalido(campo, valor, trecho):
    _, erros = validar_config(formulario(**{campo: valor}))
    assert trecho in erros[campo]


def test_pausa_minima_maior_que_a_maxima():
    _, erros = validar_config(formulario(pausa_min_s=30, pausa_max_s=20))
    assert "pausa_min_s" in erros


def test_janela_invertida():
    _, erros = validar_config(formulario(janela_inicio="22:00", janela_fim="08:00"))
    assert "janela_fim" in erros


def test_campo_ausente():
    campos = formulario()
    del campos["max_buscas_hora"]
    _, erros = validar_config(campos)
    assert "max_buscas_hora" in erros


def test_aplicar_config_grava(s):
    from fakes import T0

    valores, erros = validar_config(formulario(desconto_min_pct=30))
    assert erros == {}
    aplicar_config(s, valores, T0)
    config = s.get(ConfigAmazon, 1, populate_existing=True)
    assert (config.desconto_min_pct, config.atualizado_em) == (30, T0)


def test_todo_campo_tem_rotulo():
    from tcg_sniper.coletor_amazon.config import ROTULOS

    assert set(ROTULOS) == set(CAMPOS)
