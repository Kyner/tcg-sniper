from datetime import time
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from tcg_sniper.config import CATEGORIAS_SELADOS, Config

VARIAVEIS = (
    "COLETA_HORA",
    "COLETA_JITTER_MIN",
    "LIGA_CATEGORIAS",
    "LIGA_URL_LISTAGEM",
    "LIGA_MAX_CLIQUES",
)


def test_padroes(monkeypatch):
    for var in VARIAVEIS:
        monkeypatch.delenv(var, raising=False)
    c = Config(_env_file=None)
    assert c.coleta_hora == time(10, 0)
    assert c.coleta_jitter_min == 30
    assert c.limite_falha_pct == 50
    assert c.liga_max_cliques == 50
    assert c.zona == ZoneInfo("America/Sao_Paulo")
    assert c.categorias == list(CATEGORIAS_SELADOS)
    assert len(c.categorias) == 20
    assert c.url_listagem("10") == (
        "https://www.ligamagic.com.br/?view=cards/search&card=categ%3D10+searchprod%3D1&tipo=1"
    )


def test_le_variaveis_de_ambiente(monkeypatch):
    monkeypatch.setenv("COLETA_HORA", "09:15")
    monkeypatch.setenv("LIGA_CATEGORIAS", " 10, 31 ,10,")
    monkeypatch.setenv("LIGA_URL_LISTAGEM", "https://liga.test/l?c={categ}")
    c = Config(_env_file=None)
    assert c.coleta_hora == time(9, 15)
    assert c.categorias == ["10", "31"]
    assert c.url_listagem("31") == "https://liga.test/l?c=31"


@pytest.mark.parametrize("categorias", ["", " , ", "10,abc", "10;11"])
def test_categorias_invalidas(categorias):
    with pytest.raises(ValidationError):
        Config(_env_file=None, liga_categorias=categorias)


def test_url_listagem_sem_marcador():
    with pytest.raises(ValidationError):
        Config(_env_file=None, liga_url_listagem="https://liga.test/selados")


def test_pausa_minima_maior_que_maxima():
    with pytest.raises(ValidationError):
        Config(_env_file=None, pausa_min_s=30, pausa_max_s=10)
