import json
from datetime import UTC, datetime

import httpx
import pytest
import respx

from tcg_sniper.notificador.evolution import Resultado, enviar_uma_vez

URL = "http://evo.test"
AGORA = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


@respx.mock
@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [
        (httpx.Response(201), Resultado.OK),
        (httpx.Response(500), Resultado.TRANSITORIO),
        (httpx.Response(503), Resultado.TRANSITORIO),
        (httpx.Response(400), Resultado.DEFINITIVO),
        (httpx.Response(404), Resultado.DEFINITIVO),
    ],
)
def test_enviar_uma_vez_classifica_a_resposta(resposta, esperado):
    rota = respx.post(f"{URL}/message/sendText/TCG%20Sniper").mock(return_value=resposta)
    resultado, erro = enviar_uma_vez(httpx.Client(), URL, "chave", "TCG Sniper", "1@g.us", "olá")
    assert resultado is esperado
    assert (erro is None) is (esperado is Resultado.OK)
    pedido = rota.calls.last.request
    assert pedido.headers["apikey"] == "chave"
    assert json.loads(pedido.read()) == {"number": "1@g.us", "text": "olá"}


@respx.mock
@pytest.mark.parametrize("falha", [httpx.ConnectError("caiu"), httpx.ReadTimeout("lento"), RuntimeError("?")])
def test_enviar_uma_vez_erro_de_rede_e_transitorio(falha):
    respx.post(f"{URL}/message/sendText/inst").mock(side_effect=falha)
    resultado, erro = enviar_uma_vez(httpx.Client(), URL, "chave", "inst", "1@g.us", "olá")
    assert resultado is Resultado.TRANSITORIO and erro
