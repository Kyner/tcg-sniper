import base64
from datetime import UTC, datetime, time

import pytest
from fastapi.testclient import TestClient

from tcg_sniper.admin.app import criar_app
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import TipoColeta

GERAL = {
    "host_publico": "192.168.0.10",
    "fuso": "America/Sao_Paulo",
    "evolution_instancia": "TCG Sniper",
    "whatsapp_grupo_admin": "120363000000000001@g.us",
    "whatsapp_grupo_oportunidades": "",
}
LIGA = {
    "coleta_hora": "07:30",
    "coleta_jitter_min": "15",
    "pausa_min_s": "8",
    "pausa_max_s": "20",
    "limite_falha_pct": "50",
    "categorias": "10,11",
    "url_listagem": "https://liga.test/listagem?categ={categ}",
    "max_cliques": "50",
}


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def test_tela_tem_as_tres_secoes_com_os_valores_salvos(cliente):
    texto = cliente.get("/configuracoes").text
    assert texto.index("Geral") < texto.index("LigaMagic") < texto.index("Amazon")
    assert 'name="host_publico" value="host.test"' in texto
    assert 'name="categorias" value="10,11,12"' in texto
    assert 'name="desconto_min_pct" value="25"' in texto
    assert 'action="/configuracoes/geral"' in texto and 'action="/configuracoes/liga"' in texto
    assert 'action="/configuracoes/amazon"' in texto
    assert "ADMIN_SENHA, VNC_SENHA, EVOLUTION_API_KEY, DATABASE_URL, DIR_DADOS, EVOLUTION_URL" in texto


def test_salvar_geral(cliente, sessoes, config):
    r = cliente.post("/configuracoes/geral", data=GERAL, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/configuracoes?msg=geral"
    with sessoes() as s:
        geral = repo.obter_config_geral(s, config)
    assert (geral.host_publico, geral.whatsapp_grupo_oportunidades) == ("192.168.0.10", None)
    assert "Salvo; vale a partir da próxima coleta ou ciclo." in cliente.get(r.headers["location"]).text


def test_salvar_liga(cliente, sessoes, config):
    r = cliente.post("/configuracoes/liga", data=LIGA, follow_redirects=False)
    assert r.status_code == 303
    with sessoes() as s:
        liga = repo.obter_config_liga(s, config)
    assert (liga.coleta_hora, liga.coleta_jitter_min, liga.categorias) == (time(7, 30), 15, "10,11")


def test_erro_numa_secao_nao_grava_nem_mexe_nas_outras(cliente, sessoes, config):
    cliente.post("/configuracoes/geral", data=GERAL)
    r = cliente.post("/configuracoes/liga", data={**LIGA, "pausa_min_s": "30", "categorias": "abc"})
    assert r.status_code == 400
    assert 'name="categorias" value="abc"' in r.text  # a seção com erro volta com o que foi digitado
    assert 'name="host_publico" value="192.168.0.10"' in r.text  # as outras mostram o que está salvo
    assert "A pausa mínima não pode ser maior que a máxima." in r.text
    with sessoes() as s:
        liga = repo.obter_config_liga(s, config)
    assert (liga.pausa_min_s, liga.categorias) == (8, "10,11,12")


def test_salvar_amazon_na_rota_nova(cliente, sessoes):
    formulario = {
        "url_busca": "https://www.amazon.com.br/s?k={termo}",
        "janela_inicio": "08:00",
        "janela_fim": "22:00",
        "pausa_min_s": "8",
        "pausa_max_s": "20",
        "resultados_por_busca": "10",
        "intervalo_busca_min": "60",
        "max_buscas_hora": "200",
        "limite_falha_pct": "50",
        "desconto_min_pct": "30",
        "realerta_queda_pct": "5",
        "liga_preco_max_idade_h": "48",
        "vendedor_min_positivas_pct": "90",
        "vendedor_min_avaliacoes": "100",
        "vendedor_reavaliar_dias": "7",
    }
    r = cliente.post("/configuracoes/amazon", data=formulario, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/configuracoes?msg=amazon"
    with sessoes() as s:
        assert repo_amz.obter_config(s).desconto_min_pct == 30
    assert cliente.post("/configuracoes", data=formulario).status_code in (404, 405)


def test_dashboard_usa_o_horario_e_o_fuso_salvos(cliente, sessoes, config):
    cliente.post("/configuracoes/liga", data=LIGA)
    cliente.post("/configuracoes/geral", data={**GERAL, "fuso": "Asia/Tokyo"})
    with sessoes() as s, s.begin():
        repo.iniciar_coleta(s, TipoColeta.LISTAGEM, datetime(2026, 10, 15, 3, 0, tzinfo=UTC))
    texto = cliente.get("/").text
    assert "07:30" in texto
    assert "15/10/2026 12:00" in texto  # 03:00 UTC em Tóquio
