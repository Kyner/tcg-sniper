import base64
from decimal import Decimal

import pytest
from fakes import T0
from fastapi.testclient import TestClient

from tcg_sniper.admin.app import criar_app
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import COLETOR_CASADOR, EstadoColetorTipo

VALIDO = {
    "ligado": "sim", "modelo": "gpt-5-mini", "esforco": "minimal",
    "preco_entrada_milhao_usd": "0,25", "preco_saida_milhao_usd": "2", "teto_dia_usd": "1,50",
    "teto_mes_usd": "15", "max_chamadas_dia": "500", "intervalo_min": "10", "lote": "30",
    "automatico": "não", "confianca_confirmar": "95", "confianca_ignorar": "85",
}


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo", "openai_api_key": "sk-segredo-de-teste"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def test_aba_ia_com_padroes_e_sem_a_chave(cliente):
    html = cliente.get("/configuracoes").text
    assert 'aria-label="IA"' in html and 'name="modelo"' in html and "gpt-5" in html
    assert "Chave configurada: sim" in html
    assert "sk-segredo" not in html
    assert "OPENAI_API_KEY" in html  # rodapé com as variáveis do .env


def test_sem_chave_aparece_nao(sessoes, config):
    c = TestClient(criar_app(sessoes, config.model_copy(update={"admin_senha": "s"})), headers={"Authorization": basic("admin", "s")})
    assert "Chave configurada: não" in c.get("/configuracoes").text


def test_salvar_ia(cliente, sessoes):
    r = cliente.post("/configuracoes/ia", data=VALIDO, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/configuracoes?msg=ia"
    with sessoes() as s:
        cfg = repo_ia.obter_config_ia(s)
        assert cfg.modelo == "gpt-5-mini" and cfg.ligado is True and cfg.teto_dia_usd == Decimal("1.50")
    html = cliente.get("/configuracoes?msg=ia").text
    assert "Salvo" in html


def test_erro_na_ia_abre_a_aba_e_nao_grava(cliente, sessoes):
    r = cliente.post("/configuracoes/ia", data={**VALIDO, "lote": "0"})
    assert r.status_code == 400 and "input-error" in r.text
    with sessoes() as s:
        assert repo_ia.obter_config_ia(s).modelo == "gpt-5"


def test_resumo_do_gasto_na_aba(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo_ia.registrar_chamada(
            s, em=repo.agora_utc(), finalidade="casamento", modelo="gpt-5", tokens_entrada=1, tokens_saida=1,
            custo_usd=Decimal("0.123456"), ok=True, erro=None,
        )
    html = cliente.get("/configuracoes").text
    assert "US$ 0,12" in html and "1 de 1000" in html


def test_card_do_casador_e_acoes(cliente, sessoes):
    html = cliente.get("/servicos").text
    assert "Casador (IA)" in html and "/casador/pausar" in html and "/casador/rodar-agora" in html
    assert "desligada" in html  # config_ia.ligado = false
    assert cliente.post("/casador/pausar", follow_redirects=False).headers["location"] == "/servicos?msg=casador_pausar"
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_CASADOR).estado is EstadoColetorTipo.PAUSADO
    assert "/casador/retomar" in cliente.get("/servicos").text
    cliente.post("/casador/retomar")
    cliente.post("/casador/rodar-agora")
    with sessoes() as s:
        estado = repo.obter_estado(s, coletor=COLETOR_CASADOR)
        assert estado.estado is EstadoColetorTipo.ATIVO and estado.execucao_solicitada


def _card_casador(html):
    card = html[html.index("Casador (IA)"):]
    return card[:card.index("</div></div>")]


def test_card_do_casador_sem_chave(sessoes, config):
    with sessoes() as s, s.begin():
        repo_ia.salvar_config_ia(s, {"ligado": True}, T0)
    c = TestClient(criar_app(sessoes, config.model_copy(update={"admin_senha": "s", "openai_api_key": ""})),
                   headers={"Authorization": basic("admin", "s")})
    card = _card_casador(c.get("/servicos").text)
    assert "sem chave" in card and "OPENAI_API_KEY" in card and "Ativo." not in card and ">ativo<" not in card


def test_card_do_casador_ativo_com_chave(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo_ia.salvar_config_ia(s, {"ligado": True}, T0)
    card = _card_casador(cliente.get("/servicos").text)
    assert "Ativo." in card and "sem chave" not in card


def test_dashboard_mostra_gasto_e_aviso_de_pausa(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar(s, "chave recusada pela OpenAI (401)", T0, COLETOR_CASADOR)
    html = cliente.get("/").text
    assert "Gasto do mês" in html and "US$ 0,00" in html
    assert "Casador (IA) — Pausado: chave recusada" in html
