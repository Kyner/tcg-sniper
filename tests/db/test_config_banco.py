from datetime import UTC, datetime, time

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from tcg_sniper.config_banco import carregar_config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import ConfigGeral, ConfigLiga

AGORA = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def test_primeira_leitura_cria_as_linhas_com_os_valores_do_env(s, config):
    geral = repo.obter_config_geral(s, config)
    liga = repo.obter_config_liga(s, config)
    assert (geral.host_publico, geral.fuso, geral.evolution_instancia) == ("host.test", "America/Sao_Paulo", None)
    assert (liga.categorias, liga.url_listagem, liga.max_cliques) == (
        "10,11,12",
        "https://liga.test/listagem?categ={categ}",
        5,
    )
    assert (liga.coleta_hora, liga.pausa_min_s, liga.pausa_max_s, liga.limite_falha_pct) == (time(10, 0), 8, 20, 50)


def test_segunda_leitura_nao_sobrescreve_o_que_foi_salvo(s, config):
    repo.obter_config_geral(s, config)
    repo.salvar_config_geral(s, {"host_publico": "192.168.0.10"}, AGORA)
    outro_env = config.model_copy(update={"host_publico": "outro.test"})
    assert repo.obter_config_geral(s, outro_env).host_publico == "192.168.0.10"


def test_env_fora_dos_limites_e_ajustado_na_primeira_leitura(s, config):
    estranho = config.model_copy(update={"host_publico": "  ", "pausa_min_s": 200.0, "pausa_max_s": 300.0})
    geral = repo.obter_config_geral(s, estranho)
    liga = repo.obter_config_liga(s, estranho)
    assert geral.host_publico == "localhost"
    assert (liga.pausa_min_s, liga.pausa_max_s) == (120, 120)


def test_grupos_vazios_do_env_viram_none(s, config):
    c = config.model_copy(update={"evolution_instancia": "", "whatsapp_grupo_admin": "  "})
    geral = repo.obter_config_geral(s, c)
    assert (geral.evolution_instancia, geral.whatsapp_grupo_admin) == (None, None)


def test_carregar_config_sobrepoe_o_banco_ao_env(sessoes, config):
    with sessoes() as s, s.begin():
        repo.obter_config_geral(s, config)
        repo.obter_config_liga(s, config)
        repo.salvar_config_geral(s, {"host_publico": "10.0.0.5", "whatsapp_grupo_admin": "1@g.us"}, AGORA)
        repo.salvar_config_liga(s, {"coleta_hora": time(7, 30), "categorias": "21,22"}, AGORA)
    efetiva = carregar_config(sessoes, config)
    assert efetiva.host_publico == "10.0.0.5"
    assert efetiva.whatsapp_grupo_admin == "1@g.us"
    assert efetiva.coleta_hora == time(7, 30)
    assert efetiva.categorias == ["21", "22"]
    assert efetiva.dir_dados == config.dir_dados  # o que é do .env continua do .env
    assert config.host_publico == "host.test"  # o Config do .env não é alterado


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("coleta_jitter_min", 181),
        ("pausa_max_s", 121),
        ("limite_falha_pct", 101),
        ("max_cliques", 0),
        ("url_listagem", "https://liga.test/x"),
        ("categorias", "10,,11"),
        ("categorias", "abc"),
        ("esfriar_desafio_min", 241),
        ("esfriar_desafio_min", -1),
        ("produtos_novos_dia", 2001),
        ("produtos_novos_dia", -1),
    ],
)
def test_config_liga_recusa_valores_fora_dos_limites(s, config, campo, valor):
    repo.obter_config_liga(s, config)
    with pytest.raises(IntegrityError):
        s.execute(update(ConfigLiga).where(ConfigLiga.id == 1).values({campo: valor}))


def test_config_liga_recusa_pausa_minima_maior_que_a_maxima(s, config):
    repo.obter_config_liga(s, config)
    with pytest.raises(IntegrityError):
        s.execute(update(ConfigLiga).where(ConfigLiga.id == 1).values(pausa_min_s=30, pausa_max_s=20))


def test_config_geral_recusa_host_vazio(s, config):
    repo.obter_config_geral(s, config)
    with pytest.raises(IntegrityError):
        s.execute(update(ConfigGeral).where(ConfigGeral.id == 1).values(host_publico=""))


def test_esfriar_e_novos_por_dia_nascem_com_o_padrao_e_vao_para_o_config(sessoes, config):
    with sessoes() as s, s.begin():
        liga = repo.obter_config_liga(s, config)
        assert (liga.esfriar_desafio_min, liga.produtos_novos_dia) == (30, 100)
        repo.salvar_config_liga(s, {"esfriar_desafio_min": 45, "produtos_novos_dia": 250}, AGORA)
    efetiva = carregar_config(sessoes, config)
    assert (efetiva.esfriar_desafio_min, efetiva.produtos_novos_dia) == (45, 250)
