import base64

import pytest
from fakes import T0
from fastapi.testclient import TestClient

from tcg_sniper.admin.app import criar_app
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import COLETOR_AMAZON, COLETOR_LIGA, COLETOR_NOTIFICADOR, EstadoColetorTipo


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


@pytest.mark.parametrize("coletor", [COLETOR_LIGA, COLETOR_NOTIFICADOR])
def test_pausar_e_retomar(cliente, sessoes, coletor):
    prefixo = "/liga" if coletor == COLETOR_LIGA else "/notificador"
    r = cliente.post(f"{prefixo}/pausar", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, f"/servicos?msg={coletor}_pausar")
    with sessoes() as s:
        estado = repo.obter_estado(s, coletor=coletor)
        assert (estado.estado, estado.motivo) == (EstadoColetorTipo.PAUSADO, "pausado no admin")
    r = cliente.post(f"{prefixo}/retomar", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, f"/servicos?msg={coletor}_retomar")
    with sessoes() as s:
        estado = repo.obter_estado(s, coletor=coletor)
        # religar não pede uma execução imediata: o agendador segue o horário do dia
        assert (estado.estado, estado.execucao_solicitada) == (EstadoColetorTipo.ATIVO, False)


@pytest.mark.parametrize(
    ("rota", "mensagem"),
    [
        ("/liga/pausar", "Coleta da LigaMagic desligada"),
        ("/liga/retomar", "Coleta da LigaMagic ligada"),
        ("/notificador/pausar", "Envio do WhatsApp desligado"),
        ("/notificador/retomar", "Envio do WhatsApp ligado"),
    ],
)
def test_mensagens_das_novas_acoes(cliente, rota, mensagem):
    assert mensagem in cliente.post(rota).text


def test_pausar_a_liga_nao_mexe_nos_outros(cliente, sessoes):
    cliente.post("/liga/pausar")
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_NOTIFICADOR).estado is EstadoColetorTipo.ATIVO


def card(texto, servico):
    inicio = texto.index(f'data-servico="{servico}"')
    fim = texto.find('data-servico="', inicio + 1)
    return texto[inicio:fim if fim > 0 else len(texto)]


def test_quatro_cards_ligados_com_chave_e_historico(cliente):
    texto = cliente.get("/servicos").text
    for servico, acao, historico in (
        ("liga", "/liga/pausar", "/logs?aba=liga"),
        ("amazon", "/amazon/pausar", "/logs?aba=amazon"),
        ("casador", "/casador/pausar", "/logs?aba=ia"),
        ("notificador", "/notificador/pausar", "/mensagens"),
    ):
        c = card(texto, servico)
        assert f'action="{acao}"' in c and 'class="toggle toggle-success" checked' in c, servico
        assert 'onchange="this.form.submit()"' in c and "<noscript>" in c and ">Desligar</button>" in c
        assert f'href="{historico}"' in c
        assert 'badge-success">ligado</span>' in c or servico == "casador"
    assert 'action="/rodar-agora"' in card(texto, "liga") and 'action="/casador/rodar-agora"' in card(texto, "casador")


@pytest.mark.parametrize(
    ("coletor", "servico", "acao"),
    [(COLETOR_LIGA, "liga", "/liga/retomar"), (COLETOR_NOTIFICADOR, "notificador", "/notificador/retomar")],
)
def test_card_desligado(cliente, sessoes, coletor, servico, acao):
    with sessoes() as s, s.begin():
        repo.pausar(s, "pausado no admin", T0, coletor)
    c = card(cliente.get("/servicos").text, servico)
    assert f'action="{acao}"' in c and 'class="toggle toggle-success" aria-label' in c and ">Ligar</button>" in c
    assert 'badge-error">desligado</span>' in c
    assert "Rodar agora" not in c


def test_desafio_mantem_o_card_vermelho_com_novnc_e_retomar(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em /x", T0)
        repo.pausar_por_desafio(s, "desafio em /y", T0, COLETOR_AMAZON)
    texto = cliente.get("/servicos").text
    for servico, porta, acao in (("liga", "6080", "/retomar"), ("amazon", "6081", "/amazon/retomar")):
        c = card(texto, servico)
        assert "border-error" in c and f"host.test:{porta}/vnc.html" in c and f'action="{acao}"' in c
        assert "desafio pendente" in c and "toggle" not in c and "Rodar agora" not in c
