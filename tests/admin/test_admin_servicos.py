import base64

import pytest
from fastapi.testclient import TestClient

from tcg_sniper.admin.app import criar_app
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import COLETOR_LIGA, COLETOR_NOTIFICADOR, EstadoColetorTipo


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
        assert repo.obter_estado(s, coletor=coletor).estado is EstadoColetorTipo.ATIVO


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
