import base64
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from fakes import T0
from fastapi.testclient import TestClient

from tcg_sniper.admin.app import criar_app
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    COLETOR_AMAZON_BUSCA,
    COLETOR_LIGA,
    COLETOR_NOTIFICADOR,
    EstadoColetorTipo,
    StatusColeta,
    TipoColeta,
)


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
        ("amazon_busca", "/amazon/busca/pausar", "/logs?aba=amazon"),
        ("amazon", "/amazon/pausar", "/logs?aba=monitor"),
        ("casador", "/casador/pausar", "/logs?aba=ia"),
        ("notificador", "/notificador/pausar", "/mensagens"),
    ):
        c = card(texto, servico)
        assert f'action="{acao}"' in c and 'class="toggle toggle-success" checked' in c, servico
        assert 'onchange="this.form.submit()"' in c and "<noscript>" in c and ">Desligar</button>" in c
        assert 'aria-label="Desligar ' in c and 'aria-label="Ligar ' not in c
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
    assert 'badge-error">desligado</span>' in c and 'aria-label="Ligar ' in c
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


@pytest.mark.parametrize(("rota", "coletor"), [("/liga/pausar", COLETOR_LIGA), ("/notificador/pausar", COLETOR_NOTIFICADOR)])
def test_desligar_nao_apaga_um_desafio_pendente(cliente, sessoes, rota, coletor):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em /x", T0, coletor)
    r = cliente.post(rota, follow_redirects=False)
    assert r.headers["location"] == "/servicos?msg=desafio_pendente"
    assert "desafio pendente" in cliente.get(r.headers["location"]).text.lower()
    with sessoes() as s:
        estado = repo.obter_estado(s, coletor=coletor)
        assert (estado.estado, estado.motivo) == (EstadoColetorTipo.PAUSADO_DESAFIO, "desafio em /x")


def test_texto_do_notificador_desligado(cliente):
    cliente.post("/notificador/pausar")
    c = card(cliente.get("/servicos").text, "notificador")
    assert "saem quando ligar (ofertas vencidas expiram)" in c


def test_ja_conferi_resolve_o_aviso_do_carrinho(cliente, sessoes):
    from datetime import UTC, datetime
    from decimal import Decimal

    from fakes import criar_anuncio, criar_produto

    from tcg_sniper.avisos import servico as avisos
    from tcg_sniper.avisos.catalogo import CATALOGO, TipoAviso
    from tcg_sniper.db import repositorio_amazon as repo_amz
    from tcg_sniper.db.models import EstadoAviso, SituacaoCheckout, StatusCasamento

    agora = datetime(2026, 10, 18, 13, 0, tzinfo=UTC)
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Caixa")
        a = criar_anuncio(s, "B0CAND0001", produto=p, status=StatusCasamento.CONFIRMADO)
        c = repo_amz.registrar_conferencia(
            s, em=agora, anuncio_id=a.id, vendedor_nome="Amazon.com.br", preco_anunciado=Decimal("700.00"),
            itens=None, frete=None, impostos=None, total=None, situacao=SituacaoCheckout.FALHA, motivo="x",
            item_removido=False,
        )
        repo_amz.marcar_conferir_a_mao(s, c.id, agora, "carrinho com outros itens")
        avisos.avisar(s, TipoAviso.AMAZON_CARRINHO, "B0CAND0001", CATALOGO[TipoAviso.AMAZON_CARRINHO].exemplo, agora)
        conferencia_id = c.id
    r = cliente.post(f"/amazon/carrinho/{conferencia_id}/conferido", follow_redirects=False)
    assert r.status_code == 303
    with sessoes() as s:
        assert s.get(EstadoAviso, ("amazon_carrinho", "B0CAND0001")).aberto is False


def test_card_da_busca_e_o_do_monitor(cliente, sessoes):
    with sessoes() as s, s.begin():
        from tcg_sniper.coletor_amazon.config import aplicar_config

        aplicar_config(s, {"max_buscas_hora": 90, "monitor_max_paginas_hora": 180}, T0)
    texto = cliente.get("/servicos").text
    busca, monitor = card(texto, "amazon_busca"), card(texto, "amazon")
    assert "Amazon (busca)" in busca and "Fila contínua de buscas" in busca and "até 90 por hora" in busca
    assert "host.test:6082/vnc.html" in busca and "6081" not in busca
    assert "Amazon (monitor e checkout)" in monitor and "Fila contínua de buscas" not in monitor
    assert "até 180 páginas por hora" in monitor and "host.test:6081/vnc.html" in monitor


def test_pausar_e_retomar_a_busca_nao_mexe_no_monitor(cliente, sessoes):
    r = cliente.post("/amazon/busca/pausar", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/servicos?msg=amazon_busca_pausar")
    with sessoes() as s:
        busca = repo.obter_estado(s, coletor=COLETOR_AMAZON_BUSCA)
        assert (busca.estado, busca.motivo) == (EstadoColetorTipo.PAUSADO, "pausado no admin")
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.ATIVO
    assert "Busca na Amazon pausada" in cliente.get(r.headers["location"]).text
    r = cliente.post("/amazon/busca/retomar", follow_redirects=False)
    assert r.headers["location"] == "/servicos?msg=amazon_busca_retomar"
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON_BUSCA).estado is EstadoColetorTipo.ATIVO
    assert "Busca na Amazon retomada" in cliente.get(r.headers["location"]).text


def test_pausar_o_monitor_nao_mexe_na_busca(cliente, sessoes):
    r = cliente.post("/amazon/pausar", follow_redirects=False)
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.PAUSADO
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON_BUSCA).estado is EstadoColetorTipo.ATIVO
    assert "Monitor e checkout da Amazon pausados" in cliente.get(r.headers["location"]).text


def test_desafio_da_busca_card_vermelho_com_novnc_6082_e_monitor_normal(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em /s?k=x", T0, COLETOR_AMAZON_BUSCA)
    texto = cliente.get("/servicos").text
    busca = card(texto, "amazon_busca")
    assert "border-error" in busca and "host.test:6082/vnc.html" in busca
    assert 'action="/amazon/busca/retomar"' in busca and "desafio pendente" in busca and "toggle" not in busca
    assert "border-error" not in card(texto, "amazon")


def test_desligar_a_busca_nao_apaga_um_desafio_pendente(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em /x", T0, COLETOR_AMAZON_BUSCA)
    r = cliente.post("/amazon/busca/pausar", follow_redirects=False)
    assert r.headers["location"] == "/servicos?msg=desafio_pendente"
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON_BUSCA).estado is EstadoColetorTipo.PAUSADO_DESAFIO


def test_pausar_o_monitor_nao_apaga_um_desafio_pendente(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em /gp/cart", T0, COLETOR_AMAZON)
    r = cliente.post("/amazon/pausar", follow_redirects=False)
    assert r.headers["location"] == "/servicos?msg=desafio_pendente"
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.PAUSADO_DESAFIO


def test_pausar_a_busca_avisa_com_o_nome_do_servico(cliente, sessoes):
    from sqlalchemy import select

    from tcg_sniper.db.models import MensagemSaida

    cliente.post("/amazon/busca/pausar")
    with sessoes() as s:
        textos = [m.texto for m in s.scalars(select(MensagemSaida))]
    assert any("Amazon (busca)" in t and "pausado" in t for t in textos)


SP = ZoneInfo("America/Sao_Paulo")


def desafio_da_liga(sessoes, quando):
    with sessoes() as s, s.begin():
        c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, quando)
        repo.finalizar_coleta(s, c.id, StatusColeta.PAUSADA_DESAFIO, 1, 0, quando, erro="desafio em /x")
        repo.pausar_por_desafio(s, "desafio em /x", quando)


def retomada(sessoes, quando, solicitar=False):
    with sessoes() as s, s.begin():
        repo.retomar(s, quando, solicitar=solicitar, desafio_resolvido=True)


def test_liga_esfriando_mostra_ate_quando(cliente, sessoes):
    agora = repo.agora_utc()
    desafio_da_liga(sessoes, agora - timedelta(seconds=2))
    retomada(sessoes, agora - timedelta(seconds=1))
    ate = (agora - timedelta(seconds=1) + timedelta(minutes=30)).astimezone(SP)
    liga = card(cliente.get("/servicos").text, "liga")
    assert f"Esfriando até {ate:%H:%M}" in liga and "pausas em dobro" in liga
    assert 'action="/rodar-agora"' in liga


def test_liga_parada_ate_amanha_sem_rodar_agora(cliente, sessoes):
    agora = repo.agora_utc()
    desafio_da_liga(sessoes, agora - timedelta(seconds=3))
    desafio_da_liga(sessoes, agora - timedelta(seconds=2))
    retomada(sessoes, agora - timedelta(seconds=1))
    liga = card(cliente.get("/servicos").text, "liga")
    assert "Parada até amanhã (2º desafio)" in liga and 'action="/rodar-agora"' not in liga


def test_rodar_agora_parada_nao_pede_execucao(cliente, sessoes):
    agora = repo.agora_utc()
    desafio_da_liga(sessoes, agora - timedelta(seconds=3))
    desafio_da_liga(sessoes, agora - timedelta(seconds=2))
    retomada(sessoes, agora - timedelta(seconds=1))
    r = cliente.post("/rodar-agora", follow_redirects=False)
    assert r.headers["location"] == "/servicos?msg=liga_parada_hoje"
    with sessoes() as s:
        assert repo.obter_estado(s).execucao_solicitada is False
    assert "fica parada até amanhã" in cliente.get(r.headers["location"]).text


def test_rodar_agora_esfriando_pede_e_diz_que_espera(cliente, sessoes):
    agora = repo.agora_utc()
    desafio_da_liga(sessoes, agora - timedelta(seconds=2))
    retomada(sessoes, agora - timedelta(seconds=1))
    r = cliente.post("/rodar-agora", follow_redirects=False)
    assert r.headers["location"] == "/servicos?msg=liga_esfriando"
    with sessoes() as s:
        assert repo.obter_estado(s).execucao_solicitada is True
    assert "quando o esfriamento terminar" in cliente.get(r.headers["location"]).text


def test_retomar_do_primeiro_desafio_diz_que_esfria(cliente, sessoes):
    desafio_da_liga(sessoes, repo.agora_utc() - timedelta(seconds=1))
    r = cliente.post("/retomar", follow_redirects=False)
    assert r.headers["location"] == "/servicos?msg=retomar_esfriando"


def test_retomar_do_segundo_desafio_diz_que_volta_amanha(cliente, sessoes):
    agora = repo.agora_utc()
    desafio_da_liga(sessoes, agora - timedelta(seconds=2))
    desafio_da_liga(sessoes, agora - timedelta(seconds=1))
    r = cliente.post("/retomar", follow_redirects=False)
    assert r.headers["location"] == "/servicos?msg=retomar_parada"
    assert "só volta amanhã" in cliente.get(r.headers["location"]).text
