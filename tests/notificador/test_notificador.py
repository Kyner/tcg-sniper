import json
import logging

import httpx
import pytest
import respx

from tcg_sniper.notificador import criar_notificador
from tcg_sniper.notificador.base import Destino
from tcg_sniper.notificador.evolution import EvolutionNotificador
from tcg_sniper.notificador.log import LogNotificador

URL = "http://evo.test"
GRUPOS = {Destino.ADMIN: "120363000000000001@g.us"}


def notificador(pausas):
    return EvolutionNotificador(URL, "chave", "inst", GRUPOS, dormir=pausas.append)


@respx.mock
def test_envia_para_o_grupo_do_destino():
    rota = respx.post(f"{URL}/message/sendText/inst").mock(return_value=httpx.Response(201))
    notificador([]).enviar(Destino.ADMIN, "olá")
    assert rota.call_count == 1
    pedido = rota.calls.last.request
    assert pedido.headers["apikey"] == "chave"
    assert json.loads(pedido.read()) == {"number": "120363000000000001@g.us", "text": "olá"}


@respx.mock
def test_tenta_de_novo_e_desiste_sem_lancar_excecao():
    rota = respx.post(f"{URL}/message/sendText/inst").mock(return_value=httpx.Response(500))
    pausas = []
    notificador(pausas).enviar(Destino.ADMIN, "x")
    assert rota.call_count == 3
    assert pausas == [1, 2]


@respx.mock
def test_sucesso_na_segunda_tentativa():
    rota = respx.post(f"{URL}/message/sendText/inst").mock(
        side_effect=[httpx.ConnectError("caiu"), httpx.Response(201)]
    )
    pausas = []
    notificador(pausas).enviar(Destino.ADMIN, "x")
    assert rota.call_count == 2
    assert pausas == [1]


@respx.mock
def test_excecao_nao_http_tambem_nunca_propaga():
    rota = respx.post(f"{URL}/message/sendText/inst").mock(side_effect=RuntimeError("inesperado"))
    pausas = []
    notificador(pausas).enviar(Destino.ADMIN, "x")
    assert rota.call_count == 3
    assert pausas == [1, 2]


@respx.mock
def test_destino_sem_grupo_nao_envia():
    rota = respx.post(f"{URL}/message/sendText/inst")
    notificador([]).enviar(Destino.OPORTUNIDADES, "x")
    assert rota.call_count == 0


def test_criar_notificador_sem_evolution_usa_log(config):
    assert isinstance(criar_notificador(config), LogNotificador)


def test_criar_notificador_com_evolution(config):
    c = config.model_copy(
        update={
            "evolution_url": URL,
            "evolution_api_key": "chave",
            "evolution_instancia": "inst",
            "whatsapp_grupo_admin": "g@g.us",
        }
    )
    assert isinstance(criar_notificador(c), EvolutionNotificador)


@pytest.mark.parametrize("chave", ["", "   ", "trocar-esta-chave"])
def test_criar_notificador_chave_padrao_usa_log_e_avisa(config, chave, caplog):
    c = config.model_copy(
        update={
            "evolution_url": URL,
            "evolution_api_key": chave,
            "evolution_instancia": "inst",
            "whatsapp_grupo_admin": "g@g.us",
        }
    )
    with caplog.at_level(logging.WARNING):
        assert isinstance(criar_notificador(c), LogNotificador)
    assert "EVOLUTION_API_KEY" in caplog.text
