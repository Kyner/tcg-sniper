import base64

import pytest
from fakes import T0
from fastapi.testclient import TestClient

from tcg_sniper.admin.app import criar_app
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import COLETOR_AMAZON, EstadoColetorTipo, TipoColeta


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def test_index_mostra_a_amazon_ativa_com_ciclo(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.iniciar_coleta(s, TipoColeta.AMAZON, T0)
    texto = cliente.get("/").text
    assert "Amazon" in texto and "Pausar (Amazon)" in texto and "Ciclo em andamento" in texto


def test_pausar_e_retomar_a_amazon(cliente, sessoes):
    assert cliente.post("/amazon/pausar", follow_redirects=False).status_code == 303
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.PAUSADO
        assert repo.obter_estado(s).estado is EstadoColetorTipo.ATIVO  # a Liga não muda
    assert "Retomar (Amazon)" in cliente.get("/").text
    cliente.post("/amazon/retomar")
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.ATIVO


def test_index_mostra_o_captcha_da_amazon_com_o_link_do_novnc(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em https://www.amazon.com.br/s?k=x", T0, COLETOR_AMAZON)
    texto = cliente.get("/").text
    assert ":6081/vnc.html" in texto and "Retomar (Amazon)" in texto


def test_configuracoes_mostra_os_valores_atuais(cliente):
    texto = cliente.get("/configuracoes").text
    assert 'name="desconto_min_pct" value="25"' in texto
    assert 'name="janela_inicio" value="08:00"' in texto


def formulario_padrao(**mudancas):
    campos = {
        "url_busca": "https://www.amazon.com.br/s?k={termo}",
        "janela_inicio": "08:00",
        "janela_fim": "22:00",
        "pausa_min_s": "8",
        "pausa_max_s": "20",
        "resultados_por_busca": "10",
        "intervalo_busca_min": "60",
        "max_buscas_hora": "200",
        "limite_falha_pct": "50",
        "desconto_min_pct": "25",
        "realerta_queda_pct": "5",
        "liga_preco_max_idade_h": "48",
        "vendedor_min_positivas_pct": "90",
        "vendedor_min_avaliacoes": "100",
        "vendedor_reavaliar_dias": "7",
    }
    campos.update({k: str(v) for k, v in mudancas.items()})
    return campos


def test_configuracoes_grava_valores_validos(cliente, sessoes):
    r = cliente.post("/configuracoes", data=formulario_padrao(desconto_min_pct=30), follow_redirects=False)
    assert r.status_code == 303
    with sessoes() as s:
        assert repo_amz.obter_config(s).desconto_min_pct == 30
    assert "Configurações salvas" in cliente.get(r.headers["location"]).text


def test_configuracoes_recusa_valor_invalido_e_nao_grava_nada(cliente, sessoes):
    r = cliente.post("/configuracoes", data=formulario_padrao(desconto_min_pct=0, max_buscas_hora=150))
    assert r.status_code == 400
    assert "entre 1 e 90" in r.text
    assert 'name="max_buscas_hora" value="150"' in r.text  # o formulário volta com o que foi digitado
    with sessoes() as s:
        config = repo_amz.obter_config(s)
    assert (config.desconto_min_pct, config.max_buscas_hora) == (25, 200)
