import json
import logging
from datetime import UTC, datetime

import httpx
import pytest
import respx

from tcg_sniper.db import repositorio as repo
from tcg_sniper.notificador import criar_notificador
from tcg_sniper.notificador.base import Destino
from tcg_sniper.notificador.evolution import EvolutionNotificador
from tcg_sniper.notificador.log import LogNotificador

AGORA = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
URL = "http://evo.test"
GRUPOS = {Destino.ADMIN: "120363000000000001@g.us"}


def notificador(pausas, instancia="inst", grupos=GRUPOS):
    return EvolutionNotificador(URL, "chave", lambda: (instancia, grupos), dormir=pausas.append)


@respx.mock
def test_envia_para_o_grupo_do_destino():
    rota = respx.post(f"{URL}/message/sendText/inst").mock(return_value=httpx.Response(201))
    notificador([]).enviar(Destino.ADMIN, "olá")
    assert rota.call_count == 1
    pedido = rota.calls.last.request
    assert pedido.headers["apikey"] == "chave"
    assert json.loads(pedido.read()) == {"number": "120363000000000001@g.us", "text": "olá"}


@respx.mock
@pytest.mark.parametrize(("instancia", "codificada"), [("TCG Sniper", "TCG%20Sniper"), ("a/b?c", "a%2Fb%3Fc")])
def test_nome_da_instancia_vai_codificado_na_url(instancia, codificada):
    rota = respx.post(f"{URL}/message/sendText/{codificada}").mock(return_value=httpx.Response(201))
    notificador([], instancia=instancia).enviar(Destino.ADMIN, "olá")
    assert rota.call_count == 1


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


def test_criar_notificador_sem_evolution_usa_log(config, sessoes):
    assert isinstance(criar_notificador(config, sessoes), LogNotificador)


def test_criar_notificador_com_evolution(config, sessoes):
    c = config.model_copy(update={"evolution_url": URL, "evolution_api_key": "chave"})
    assert isinstance(criar_notificador(c, sessoes), EvolutionNotificador)


@pytest.mark.parametrize("chave", ["", "   ", "trocar-esta-chave"])
def test_criar_notificador_chave_padrao_usa_log_e_avisa(config, sessoes, chave, caplog):
    c = config.model_copy(update={"evolution_url": URL, "evolution_api_key": chave})
    with caplog.at_level(logging.WARNING):
        assert isinstance(criar_notificador(c, sessoes), LogNotificador)
    assert "EVOLUTION_API_KEY" in caplog.text


@respx.mock
def test_grupo_e_instancia_salvos_na_tela_valem_na_mensagem_seguinte(config, sessoes):
    c = config.model_copy(update={"evolution_url": URL, "evolution_api_key": "chave"})
    rota_a = respx.post(f"{URL}/message/sendText/inst-a").mock(return_value=httpx.Response(201))
    rota_b = respx.post(f"{URL}/message/sendText/inst-b").mock(return_value=httpx.Response(201))
    notif = criar_notificador(c, sessoes)
    with sessoes() as s, s.begin():
        repo.obter_config_geral(s, c)
        repo.salvar_config_geral(s, {"evolution_instancia": "inst-a", "whatsapp_grupo_admin": "1@g.us"}, AGORA)
    notif.enviar(Destino.ADMIN, "primeira")
    with sessoes() as s, s.begin():
        repo.salvar_config_geral(s, {"evolution_instancia": "inst-b", "whatsapp_grupo_admin": "2@g.us"}, AGORA)
    notif.enviar(Destino.ADMIN, "segunda")
    assert json.loads(rota_a.calls.last.request.read())["number"] == "1@g.us"
    assert json.loads(rota_b.calls.last.request.read())["number"] == "2@g.us"


@respx.mock
def test_sem_instancia_na_tela_nao_envia(config, sessoes, caplog):
    c = config.model_copy(update={"evolution_url": URL, "evolution_api_key": "chave"})
    rota = respx.post(url__startswith=URL)
    with caplog.at_level(logging.WARNING):
        criar_notificador(c, sessoes).enviar(Destino.ADMIN, "x")
    assert rota.call_count == 0
    assert "instância" in caplog.text


def test_erro_ao_ler_a_configuracao_nunca_propaga(caplog):
    def quebrado():
        raise RuntimeError("banco fora")

    with caplog.at_level(logging.ERROR):
        EvolutionNotificador(URL, "chave", quebrado, dormir=lambda _: None).enviar(Destino.ADMIN, "x")
    assert "banco fora" in caplog.text
