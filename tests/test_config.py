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


VARIAVEIS_BACKUP = ("DIR_BACKUPS", "R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")


def test_pasta_de_backups_padrao_e_dentro_dos_dados(monkeypatch, tmp_path):
    for var in VARIAVEIS_BACKUP:
        monkeypatch.delenv(var, raising=False)
    c = Config(_env_file=None, dir_dados=tmp_path)
    assert c.pasta_backups == tmp_path / "backups"
    assert Config(_env_file=None, dir_dados=tmp_path, dir_backups=tmp_path / "outra").pasta_backups == tmp_path / "outra"
    assert not c.r2_configurado
    monkeypatch.setenv("DIR_BACKUPS", "")
    assert Config(_env_file=None, dir_dados=tmp_path).pasta_backups == tmp_path / "backups"


def test_r2_configurado_so_com_as_quatro_variaveis_e_segredos_nao_aparecem(monkeypatch):
    monkeypatch.setenv("R2_ACCOUNT_ID", "conta123")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "CHAVE-ID-FALSA")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "segredo-falso-xyz")
    monkeypatch.setenv("R2_BUCKET", "balde")
    c = Config(_env_file=None)
    assert c.r2_configurado
    assert c.r2_secret_access_key.get_secret_value() == "segredo-falso-xyz"
    assert "segredo-falso-xyz" not in repr(c) and "segredo-falso-xyz" not in str(c)
    assert "CHAVE-ID-FALSA" not in repr(c)
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "  ")
    assert not Config(_env_file=None).r2_configurado


def test_padroes_da_leitura_por_interesse():
    c = Config(_env_file=None)
    assert (c.esfriar_desafio_min, c.produtos_novos_dia) == (30, 100)


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("esfriar_desafio_min", 241), ("esfriar_desafio_min", -1), ("produtos_novos_dia", 2001), ("produtos_novos_dia", -1)],
)
def test_limites_da_leitura_por_interesse(campo, valor):
    with pytest.raises(ValidationError):
        Config(_env_file=None, **{campo: valor})
