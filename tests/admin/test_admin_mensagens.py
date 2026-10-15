import base64
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from tcg_sniper.admin.app import criar_app, destino_seguro
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import MensagemSaida, StatusMensagem


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def criar(sessoes, destino="admin", texto="x", status=StatusMensagem.PENDENTE, idade=timedelta(0), erro=None):
    with sessoes() as s, s.begin():
        m = repo_msg.enfileirar(s, destino, texto, repo.agora_utc() - idade)
        m.status, m.ultimo_erro = status, erro
        return m.id


def test_menu_tem_mensagens(cliente):
    assert '<a href="/mensagens">Mensagens</a>' in cliente.get("/").text


def test_lista_com_filtros_e_paginacao(cliente, sessoes):
    for i in range(55):
        criar(sessoes, "oportunidades", f"oferta {i:02d}", StatusMensagem.ENVIADA, timedelta(minutes=60 - i))
    criar(sessoes, "admin", "aviso que falhou", StatusMensagem.FALHA, erro="HTTP 400: grupo inválido")
    texto = cliente.get("/mensagens", params={"situacao": "falha"}).text
    assert "aviso que falhou" in texto and "HTTP 400: grupo inválido" in texto and "oferta 0" not in texto
    pagina1 = cliente.get("/mensagens", params={"destino": "oportunidades"}).text
    assert "oferta 54" in pagina1 and "oferta 04" not in pagina1  # mais recentes primeiro, 50 por página
    assert "destino=oportunidades" in pagina1 and "pagina=2" in pagina1
    pagina2 = cliente.get("/mensagens", params={"destino": "oportunidades", "pagina": "2"}).text
    assert "oferta 04" in pagina2


@pytest.mark.parametrize("params", [{"situacao": "x"}, {"destino": "todos-os-grupos"}])
def test_filtro_invalido_400(cliente, params):
    assert cliente.get("/mensagens", params=params).status_code == 400


def test_botoes_por_situacao(cliente, sessoes):
    falha = criar(sessoes, status=StatusMensagem.FALHA)
    pendente = criar(sessoes, status=StatusMensagem.PENDENTE)
    enviada = criar(sessoes, status=StatusMensagem.ENVIADA)
    texto = cliente.get("/mensagens").text
    assert f'action="/mensagens/{falha}"' in texto and f'action="/mensagens/{pendente}"' in texto
    assert f'action="/mensagens/{enviada}"' not in texto


def test_reenviar_e_descartar(cliente, sessoes):
    falha = criar(sessoes, "oportunidades", status=StatusMensagem.FALHA)
    r = cliente.post(
        f"/mensagens/{falha}", data={"acao": "reenviar", "voltar": "/mensagens?situacao=falha"}, follow_redirects=False
    )
    assert r.status_code == 303 and r.headers["location"] == "/mensagens?situacao=falha"
    with sessoes() as s:
        m = s.get(MensagemSaida, falha)
        assert (m.status, m.ignorar_validade) == (StatusMensagem.PENDENTE, True)
    cliente.post(f"/mensagens/{falha}", data={"acao": "descartar"})
    with sessoes() as s:
        assert s.get(MensagemSaida, falha).status is StatusMensagem.DESCARTADA


def test_acoes_invalidas(cliente, sessoes):
    enviada = criar(sessoes, status=StatusMensagem.ENVIADA)
    assert cliente.post(f"/mensagens/{enviada}", data={"acao": "reenviar"}).status_code == 409
    assert cliente.post(f"/mensagens/{enviada}", data={"acao": "apagar"}).status_code == 400
    assert cliente.post("/mensagens/999999", data={"acao": "descartar"}).status_code == 404


@pytest.mark.parametrize(
    ("voltar", "esperado"),
    [
        ("/mensagens?situacao=falha", "/mensagens?situacao=falha"),
        ("https://evil.test", "/mensagens"),
        ("//evil.test", "/mensagens"),
        ("/casamentos", "/mensagens"),
    ],
)
def test_destino_seguro_de_mensagens(voltar, esperado):
    assert destino_seguro(voltar, "/mensagens") == esperado


def test_dashboard_avisa_falha(cliente, sessoes):
    criar(sessoes, status=StatusMensagem.FALHA, erro="HTTP 400: grupo inválido")
    texto = cliente.get("/").text
    assert "WhatsApp" in texto and "HTTP 400: grupo inválido" in texto and 'href="/mensagens' in texto


def test_dashboard_avisa_pendente_antiga_e_nao_a_recente(cliente, sessoes):
    criar(sessoes, idade=timedelta(minutes=10), erro="sem grupo de admin em Configurações → Geral")
    assert "Mensagens do WhatsApp paradas" not in cliente.get("/").text
    criar(sessoes, idade=timedelta(minutes=31), erro="HTTP 503: fora")
    assert "Mensagens do WhatsApp paradas" in cliente.get("/").text


def test_servicos_mostra_o_estado_do_notificador(cliente, sessoes):
    assert "Notificador" in cliente.get("/servicos").text and "nunca rodou" in cliente.get("/servicos").text
    with sessoes() as s, s.begin():
        repo_msg.registrar_ciclo(s, repo.agora_utc())
    assert "rodando" in cliente.get("/servicos").text
    with sessoes() as s, s.begin():
        repo_msg.registrar_ciclo(s, repo.agora_utc() - timedelta(minutes=5))
    assert "parado desde" in cliente.get("/servicos").text


def test_configuracoes_tem_a_validade(cliente):
    assert 'name="validade_oportunidade_h" value="6"' in cliente.get("/configuracoes").text
