from datetime import time
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from tcg_sniper.config import Config


def test_padroes(monkeypatch):
    for var in ("COLETA_HORA", "CATALOGO_DIA_SEMANA", "COLETA_JITTER_MIN"):
        monkeypatch.delenv(var, raising=False)
    c = Config(_env_file=None)
    assert c.coleta_hora == time(10, 0)
    assert c.coleta_jitter_min == 30
    assert c.catalogo_weekday == 6
    assert c.limite_falha_pct == 50
    assert c.zona == ZoneInfo("America/Sao_Paulo")


def test_le_variaveis_de_ambiente(monkeypatch):
    monkeypatch.setenv("COLETA_HORA", "09:15")
    monkeypatch.setenv("CATALOGO_DIA_SEMANA", "Sábado")
    c = Config(_env_file=None)
    assert c.coleta_hora == time(9, 15)
    assert c.catalogo_weekday == 5


def test_dia_invalido():
    with pytest.raises(ValidationError):
        Config(_env_file=None, catalogo_dia_semana="feriado")


def test_pausa_minima_maior_que_maxima():
    with pytest.raises(ValidationError):
        Config(_env_file=None, pausa_min_s=30, pausa_max_s=10)
