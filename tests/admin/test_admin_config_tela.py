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
    "validade_oportunidade_h": "6",
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
    "produtos_novos_dia": "100",
    "esfriar_desafio_min": "30",
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


FORMULARIO_AMAZON = {
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
    "monitor_intervalo_min": "15",
    "monitor_janela_inicio": "08:00",
    "monitor_janela_fim": "22:00",
    "monitor_max_paginas_hora": "150",
    "margem_candidata_pp": "5",
    "checkout_validade_h": "6",
    "descoberta_casados_dias": "7",
}


def test_salvar_amazon_na_rota_nova(cliente, sessoes):
    r = cliente.post("/configuracoes/amazon", data=FORMULARIO_AMAZON, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/configuracoes?msg=amazon"
    with sessoes() as s:
        assert repo_amz.obter_config(s).desconto_min_pct == 30
    assert cliente.post("/configuracoes", data=FORMULARIO_AMAZON).status_code in (404, 405)


def test_dashboard_usa_o_horario_e_o_fuso_salvos(cliente, sessoes, config, monkeypatch):
    monkeypatch.setattr(repo, "agora_utc", lambda: datetime(2026, 10, 20, 12, 0, tzinfo=UTC))
    cliente.post("/configuracoes/liga", data=LIGA)
    cliente.post("/configuracoes/geral", data={**GERAL, "fuso": "Asia/Tokyo"})
    with sessoes() as s, s.begin():
        repo.iniciar_coleta(s, TipoColeta.LISTAGEM, datetime(2026, 10, 15, 3, 0, tzinfo=UTC))
    texto = cliente.get("/").text
    assert "07:30" in texto
    assert "15/10/2026 12:00" in texto  # 03:00 UTC em Tóquio


def aba_marcada(texto, rotulo):
    inicio = texto.index(f'aria-label="{rotulo}"')
    return "checked" in texto[texto.rindex("<input", 0, inicio):inicio + 40]


def test_configuracoes_em_abas_abrindo_em_geral(cliente):
    texto = cliente.get("/configuracoes").text
    assert aba_marcada(texto, "Geral") and not aba_marcada(texto, "LigaMagic")


def test_aba_com_erro_abre_selecionada(cliente):
    r = cliente.post("/configuracoes/liga", data={**LIGA, "categorias": "abc"})
    assert r.status_code == 400 and aba_marcada(r.text, "LigaMagic") and not aba_marcada(r.text, "Geral")
    assert "input-error" in r.text


def test_aba_salva_abre_selecionada(cliente):
    r = cliente.post("/configuracoes/amazon", data=FORMULARIO_AMAZON, follow_redirects=True)
    assert aba_marcada(r.text, "Amazon")


def test_aba_amazon_explica_os_dois_navegadores_e_a_soma_dos_tetos(cliente):
    texto = cliente.get("/configuracoes").text
    trecho = texto[texto.index('id="amazon"') : texto.index('id="ia"')]
    assert "Dois navegadores" in trecho
    assert "porta 6082" in trecho and "porta 6081" in trecho
    assert "soma dos dois tetos" in trecho
    assert "Máximo de buscas por hora (busca)" in trecho
    assert "Máximo de páginas por hora (monitor e checkout)" in trecho


def test_salvar_esfriar_e_novos_por_dia(cliente, sessoes, config):
    dados = {**LIGA, "esfriar_desafio_min": "45", "produtos_novos_dia": "250"}
    assert cliente.post("/configuracoes/liga", data=dados, follow_redirects=False).status_code == 303
    with sessoes() as s:
        liga = repo.obter_config_liga(s, config)
    assert (liga.esfriar_desafio_min, liga.produtos_novos_dia) == (45, 250)


def test_esfriar_fora_do_limite_nao_grava(cliente):
    r = cliente.post("/configuracoes/liga", data={**LIGA, "esfriar_desafio_min": "241"})
    assert r.status_code == 400 and "O valor deve ficar entre 0 e 240." in r.text


def test_aba_ligamagic_explica_a_leitura_por_interesse(cliente):
    texto = cliente.get("/configuracoes").text
    trecho = texto[texto.index('id="liga"') : texto.index('id="amazon"')]
    assert "só abrem os casados e os com candidato" in trecho and "rodízio do dia" in trecho
    assert "Esfriar após desafio (min)" in trecho and "Produtos novos por dia" in trecho
    assert 'name="esfriar_desafio_min" value="30"' in trecho and 'name="produtos_novos_dia" value="100"' in trecho
