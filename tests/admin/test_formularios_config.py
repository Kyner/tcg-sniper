from datetime import time

import pytest

from tcg_sniper.admin.formularios_config import validar_geral, validar_liga

GERAL = {
    "host_publico": "192.168.0.10",
    "fuso": "America/Sao_Paulo",
    "evolution_instancia": "TCG Sniper",
    "whatsapp_grupo_admin": "120363000000000001@g.us",
    "whatsapp_grupo_oportunidades": "",
}
LIGA = {
    "coleta_hora": "10:00",
    "coleta_jitter_min": "30",
    "pausa_min_s": "8",
    "pausa_max_s": "20,5",
    "limite_falha_pct": "50",
    "categorias": " 10, 11,10 ,12 ",
    "url_listagem": "https://www.ligamagic.com.br/?view=cards/search&card=categ%3D{categ}",
    "max_cliques": "50",
}


def test_geral_valido():
    valores, erros = validar_geral(GERAL)
    assert erros == {}
    assert valores == {
        "host_publico": "192.168.0.10",
        "fuso": "America/Sao_Paulo",
        "evolution_instancia": "TCG Sniper",
        "whatsapp_grupo_admin": "120363000000000001@g.us",
        "whatsapp_grupo_oportunidades": None,
    }


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("host_publico", ""),
        ("host_publico", "192.168 .0.10"),
        ("fuso", "America/Atlantida"),
        ("fuso", ""),
        ("fuso", "../etc"),
        ("whatsapp_grupo_admin", "120363000000000001"),
        ("whatsapp_grupo_oportunidades", "@g.us"),
    ],
)
def test_geral_invalido(campo, valor):
    _, erros = validar_geral({**GERAL, campo: valor})
    assert campo in erros


def test_liga_valida_normaliza_categorias_e_pausas():
    valores, erros = validar_liga(LIGA)
    assert erros == {}
    assert valores["coleta_hora"] == time(10, 0)
    assert valores["categorias"] == "10,11,12"
    assert (valores["pausa_min_s"], valores["pausa_max_s"]) == (8.0, 20.5)
    assert valores["max_cliques"] == 50


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("coleta_hora", "25:00"),
        ("coleta_hora", "10h"),
        ("coleta_jitter_min", "181"),
        ("coleta_jitter_min", "-1"),
        ("pausa_min_s", "abc"),
        ("pausa_max_s", "121"),
        ("limite_falha_pct", "101"),
        ("categorias", ""),
        ("categorias", "10,abc"),
        ("url_listagem", "https://liga.test/sem-marcador"),
        ("url_listagem", "ftp://liga.test/{categ}"),
        ("max_cliques", "0"),
        ("max_cliques", "9999999"),
    ],
)
def test_liga_invalida(campo, valor):
    _, erros = validar_liga({**LIGA, campo: valor})
    assert campo in erros


def test_liga_recusa_pausa_minima_maior_que_a_maxima():
    _, erros = validar_liga({**LIGA, "pausa_min_s": "30", "pausa_max_s": "20"})
    assert "pausa_min_s" in erros
