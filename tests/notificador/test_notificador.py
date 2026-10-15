import json
import logging
from datetime import UTC, datetime

import httpx
import pytest
import respx
from sqlalchemy import select

from tcg_sniper.db.models import MensagemSaida, StatusMensagem
from tcg_sniper.notificador import criar_notificador
from tcg_sniper.notificador.base import Destino
from tcg_sniper.notificador.evolution import Resultado, enviar_uma_vez
from tcg_sniper.notificador.fila import NotificadorFila

URL = "http://evo.test"
AGORA = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def test_fila_grava_pendente(sessoes):
    NotificadorFila(sessoes, relogio=lambda: AGORA).enviar(Destino.OPORTUNIDADES, "oferta")
    with sessoes() as s:
        [m] = s.scalars(select(MensagemSaida))
    assert (m.destino, m.texto, m.status, m.criada_em) == ("oportunidades", "oferta", StatusMensagem.PENDENTE, AGORA)


def test_fila_com_banco_fora_nao_lanca_e_registra_o_texto(caplog):
    def quebrado():
        raise RuntimeError("banco fora")

    with caplog.at_level(logging.ERROR):
        NotificadorFila(quebrado).enviar(Destino.ADMIN, "aviso importante")
    assert "aviso importante" in caplog.text and "banco fora" in caplog.text


def test_criar_notificador_devolve_a_fila(config, sessoes):
    assert isinstance(criar_notificador(config, sessoes), NotificadorFila)


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
