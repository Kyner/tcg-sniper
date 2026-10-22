import base64
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto, oferta_lista
from fastapi.testclient import TestClient

from tcg_sniper.admin import consultas
from tcg_sniper.admin import consultas_painel as painel
from tcg_sniper.admin.app import criar_app
from tcg_sniper.coletor_amazon.config import aplicar_config
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import Envio, OrigemPreco, SituacaoCheckout, StatusCasamento

AGORA = datetime(2026, 10, 16, 19, 40, tzinfo=UTC)  # 16:40 em São Paulo
SP = ZoneInfo("America/Sao_Paulo")


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def confirmado(s, asin, lido_em=None):
    produto = criar_produto(s, f"p-{asin}", nome=f"Produto {asin}")
    criar_preco_liga(s, produto, "1000.00", listagem_em=AGORA)
    anuncio = criar_anuncio(s, asin, produto=produto, status=StatusCasamento.CONFIRMADO)
    if lido_em is not None:
        o = oferta_lista("700.00", vendedor="Amazon.com.br", seller_id="amazon", envio=Envio.AMAZON, posicao=0)
        repo_amz.gravar_ofertas(s, anuncio.id, lido_em, [repo_amz.OfertaAvaliada(o, None, True, True)])
        repo_amz.registrar_preco(s, anuncio.id, o.preco, OrigemPreco.OFERTAS, None, Envio.AMAZON, lido_em, SP)
    return anuncio


def avisos_de(s, config, agora=AGORA):
    repo_msg.registrar_ciclo(s, agora)  # notificador vivo: só os avisos do monitor interessam aqui
    resumo = painel.consultas_mensagens.resumo(s, agora)
    return painel.avisos(s, agora, config, painel.saude_servicos(s, agora, config, True, resumo), resumo)


def test_configuracoes_tem_a_secao_monitor_de_preco(cliente):
    texto = cliente.get("/configuracoes").text
    assert "Monitor de preço" in texto
    assert 'name="monitor_intervalo_min" value="15"' in texto and 'name="monitor_janela_inicio" value="08:00"' in texto


@pytest.mark.parametrize(
    ("rota", "campo", "valor", "mensagem"),
    [
        ("/amazon/monitor/desligar", "monitor_ligado", False, "Monitor de preço desligado"),
        ("/amazon/monitor/ligar", "monitor_ligado", True, "Monitor de preço ligado"),
        ("/amazon/checkout/desligar", "checkout_ligado", False, "Conferência de checkout desligada"),
        ("/amazon/checkout/ligar", "checkout_ligado", True, "Conferência de checkout ligada"),
    ],
)
def test_liga_e_desliga_monitor_e_conferencia(cliente, sessoes, rota, campo, valor, mensagem):
    r = cliente.post(rota, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/servicos?msg=")
    with sessoes() as s:
        assert getattr(repo_amz.obter_config(s), campo) is valor
    assert mensagem in cliente.get(r.headers["location"]).text


def test_retomar_conferencia_limpa_o_sem_login(cliente, sessoes):
    with sessoes() as s, s.begin():
        aplicar_config(s, {"checkout_sem_login_em": T0}, T0)
    texto = cliente.get("/servicos").text
    assert "Retomar conferência" in texto and ":6081/vnc.html" in texto
    cliente.post("/amazon/checkout/retomar")
    with sessoes() as s:
        assert repo_amz.obter_config(s).checkout_sem_login_em is None
    assert "Retomar conferência" not in cliente.get("/servicos").text


def test_servicos_mostra_os_dois_interruptores(cliente):
    texto = cliente.get("/servicos").text
    assert 'action="/amazon/monitor/desligar"' in texto and 'action="/amazon/checkout/desligar"' in texto


def test_historico_das_conferencias(s):
    a = confirmado(s, "B0LOG00001")
    repo_amz.registrar_conferencia(
        s, em=T0, anuncio_id=a.id, vendedor_nome="Shazaar", preco_anunciado=Decimal("275.91"), itens=None,
        frete=None, impostos=None, total=None, situacao=SituacaoCheckout.CARRINHO_OCUPADO, motivo="2 item(ns)",
        item_removido=True,
    )
    repo_amz.registrar_conferencia(
        s, em=T0 + timedelta(minutes=5), anuncio_id=a.id, vendedor_nome="Shazaar", preco_anunciado=Decimal("275.91"),
        itens=Decimal("237.73"), frete=Decimal("0.00"), impostos=Decimal("48.26"), total=Decimal("285.99"),
        situacao=SituacaoCheckout.OK, motivo=None, item_removido=True,
    )
    linhas, pagina, paginas = consultas.historico_conferencias(s, "todas", 1)
    assert [l.conferencia.situacao for l in linhas] == [SituacaoCheckout.OK, SituacaoCheckout.CARRINHO_OCUPADO]
    assert (linhas[0].asin, linhas[0].produto, pagina, paginas) == ("B0LOG00001", "Produto B0LOG00001", 1, 1)
    assert len(consultas.historico_conferencias(s, "carrinho_ocupado", 1)[0]) == 1


def test_historico_do_monitor(s):
    a = confirmado(s, "B0LOG00001", lido_em=T0)
    repo_amz.gravar_ofertas(
        s, a.id, T0 + timedelta(minutes=15),
        [repo_amz.OfertaAvaliada(oferta_lista("690.00"), None, True, True), repo_amz.OfertaAvaliada(oferta_lista("720.00", vendedor="Outra"), None, False, False)],
    )
    linhas, _, _ = consultas.historico_monitor(s, 1)
    assert [(l.ofertas, l.melhor_preco, l.melhor_vendedor) for l in linhas] == [
        (2, Decimal("690.00"), "Shazaar"), (1, Decimal("700.00"), "Amazon.com.br"),
    ]


def test_historico_das_conferencias_mostra_o_produto_de_cada_linha(s):
    """Regressão: as subconsultas do nome perdiam a correlação e todas as linhas saíam com o mesmo produto."""
    for i, asin in enumerate(("B0LOG00001", "B0LOG00002")):
        a = confirmado(s, asin)
        repo_amz.registrar_conferencia(
            s, em=T0 + timedelta(minutes=i), anuncio_id=a.id, vendedor_nome="Shazaar",
            preco_anunciado=Decimal("275.91"), itens=None, frete=None, impostos=None, total=None,
            situacao=SituacaoCheckout.CARRINHO_OCUPADO, motivo=None, item_removido=True,
        )
    linhas, _, _ = consultas.historico_conferencias(s, "todas", 1)
    assert [(l.asin, l.produto) for l in linhas] == [
        ("B0LOG00002", "Produto B0LOG00002"), ("B0LOG00001", "Produto B0LOG00001"),
    ]


def test_historico_do_monitor_mostra_o_produto_de_cada_linha(s):
    confirmado(s, "B0LOG00001", lido_em=T0)
    confirmado(s, "B0LOG00002", lido_em=T0 + timedelta(minutes=1))
    linhas, _, _ = consultas.historico_monitor(s, 1)
    assert [(l.asin, l.produto) for l in linhas] == [
        ("B0LOG00002", "Produto B0LOG00002"), ("B0LOG00001", "Produto B0LOG00001"),
    ]


def test_logs_tem_as_abas_monitor_e_checkout(cliente):
    texto = cliente.get("/logs?aba=checkout").text
    assert 'aria-label="Monitor"' in texto and 'aria-label="Checkout"' in texto
    assert "Nenhuma conferência de checkout ainda." in texto
    assert cliente.get("/logs?checkout_situacao=xyz").status_code == 400


def test_card_da_amazon_mostra_monitor_e_conferencia(s, config):
    confirmado(s, "B0LOG00001", lido_em=AGORA - timedelta(minutes=5))
    detalhe = {x.nome: x for x in painel.saude_servicos(s, AGORA, config, True)}["Amazon (monitor e checkout)"].detalhe
    assert detalhe.endswith("monitor: última leitura hoje 16:35 · conferência ligada")
    aplicar_config(s, {"checkout_sem_login_em": AGORA}, AGORA)
    detalhe = {x.nome: x for x in painel.saude_servicos(s, AGORA, config, True)}["Amazon (monitor e checkout)"].detalhe
    assert detalhe.endswith("conferência parada: conta sem login")


def test_card_da_amazon_com_o_monitor_desligado_diz_desligado(s, config):
    def card():
        return {x.nome: x for x in painel.saude_servicos(s, AGORA, config, True)}["Amazon (monitor e checkout)"]

    assert "Até" in card().texto
    aplicar_config(s, {"monitor_ligado": False, "checkout_ligado": False}, AGORA)
    assert card().texto == "Monitor desligado" and card().situacao == "inativo" and "Até" not in card().texto


def test_card_da_amazon_com_o_monitor_desligado_e_checkout_ligado_segue_ok(s, config):
    aplicar_config(s, {"monitor_ligado": False, "checkout_ligado": True}, AGORA)
    card = {x.nome: x for x in painel.saude_servicos(s, AGORA, config, True)}["Amazon (monitor e checkout)"]
    assert card.texto == "Monitor desligado · checkout ligado" and card.situacao == "ok"


def test_dashboard_avisa_conta_sem_login(s, config):
    aplicar_config(s, {"checkout_sem_login_em": AGORA - timedelta(hours=1)}, AGORA)
    [aviso] = avisos_de(s, config)
    assert aviso.tipo == "error" and "sem login" in aviso.texto and "6081" in aviso.texto and aviso.link == "/servicos"


def test_dashboard_avisa_monitor_que_nao_cabe_no_intervalo(s, config):
    for i in range(3):
        confirmado(s, f"B0LOG0000{i}", lido_em=AGORA - timedelta(minutes=1))
    aplicar_config(s, {"monitor_max_paginas_hora": 10}, AGORA)  # 3 anúncios a cada 15 min = 12 páginas/h
    [aviso] = avisos_de(s, config)
    assert aviso.tipo == "warning" and "12 páginas por hora" in aviso.texto and aviso.link == "/configuracoes"


def test_dashboard_avisa_monitor_atrasado_so_dentro_da_janela(s, config):
    confirmado(s, "B0LOG00001", lido_em=AGORA - timedelta(minutes=40))
    [aviso] = avisos_de(s, config)
    assert "atrasado" in aviso.texto and aviso.link == "/logs?aba=monitor"
    noite = datetime(2026, 10, 17, 2, 0, tzinfo=UTC)  # 23:00 em SP, monitor fora do horário
    assert avisos_de(s, config, noite) == []
    manha = datetime(2026, 10, 17, 11, 10, tzinfo=UTC)  # 08:10: a janela abriu há menos de 2 intervalos
    assert avisos_de(s, config, manha) == []


def test_retomar_conferencia_aparece_mesmo_com_a_amazon_pausada_por_desafio(cliente, sessoes):
    from tcg_sniper.db import repositorio as repo
    from tcg_sniper.db.models import COLETOR_AMAZON

    with sessoes() as s, s.begin():
        aplicar_config(s, {"checkout_sem_login_em": T0}, T0)
        repo.pausar_por_desafio(s, "desafio em /x", T0, COLETOR_AMAZON)
    texto = cliente.get("/servicos").text
    assert "desafio pendente" in texto
    assert 'action="/amazon/checkout/retomar"' in texto and "Retomar conferência" in texto


def test_logs_so_consulta_o_monitor_na_aba_monitor(cliente, sessoes, monkeypatch):
    chamadas = []
    real = consultas.historico_monitor

    def contando(*args, **kwargs):
        chamadas.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(consultas, "historico_monitor", contando)
    texto = cliente.get("/logs?aba=checkout").text
    assert chamadas == [] and "/logs?aba=monitor" in texto
    texto = cliente.get("/logs?aba=monitor").text
    assert chamadas == [1] and "Nenhuma leitura do monitor ainda." in texto



def _a_conferir(sessoes):
    with sessoes() as s, s.begin():
        a = confirmado(s, "B0MAO00001")
        conf = repo_amz.registrar_conferencia(
            s, em=T0, anuncio_id=a.id, vendedor_nome="Shazaar", preco_anunciado=Decimal("275.91"), itens=None,
            frete=None, impostos=None, total=None, situacao=SituacaoCheckout.FALHA, motivo="x", item_removido=False,
        )
        repo_amz.marcar_conferir_a_mao(s, conf.id, T0, "teste")
        return conf.id


def test_item_para_conferir_a_mao_aparece_no_dashboard_e_em_servicos_ate_ja_conferi(cliente, sessoes):
    conferencia_id = _a_conferir(sessoes)
    acao = f'action="/amazon/carrinho/{conferencia_id}/conferido"'
    for tela in ("/", "/servicos"):
        texto = cliente.get(tela).text
        assert "Confira o carrinho da Amazon: pode haver 1×" in texto and "B0MAO00001" in texto
        assert acao in texto and "Já conferi" in texto
    r = cliente.post(f"/amazon/carrinho/{conferencia_id}/conferido", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/servicos?msg=carrinho_conferido")
    with sessoes() as s:
        assert repo_amz.conferencias_a_conferir_a_mao(s) == []
        assert repo_amz.conferencias_com_item_no_carrinho(s) == []
    assert "Confira o carrinho da Amazon" not in cliente.get("/").text
    assert "Confira o carrinho da Amazon" not in cliente.get("/servicos").text


def test_ja_conferi_aparece_com_a_amazon_pausada_por_desafio(cliente, sessoes):
    from tcg_sniper.db import repositorio as repo
    from tcg_sniper.db.models import COLETOR_AMAZON

    conferencia_id = _a_conferir(sessoes)
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em /x", T0, COLETOR_AMAZON)
    assert f'action="/amazon/carrinho/{conferencia_id}/conferido"' in cliente.get("/servicos").text



def test_ja_conferi_so_vale_para_conferencia_a_conferir_a_mao(cliente, sessoes):
    from tcg_sniper.db.models import ConferenciaCheckout

    with sessoes() as s, s.begin():
        a = confirmado(s, "B0AUTO0001")
        pendente = repo_amz.registrar_conferencia(
            s, em=T0, anuncio_id=a.id, vendedor_nome="Shazaar", preco_anunciado=Decimal("275.91"), itens=None,
            frete=None, impostos=None, total=None, situacao=SituacaoCheckout.FALHA, motivo="x", item_removido=False,
        ).id
    a_mao = _a_conferir(sessoes)
    assert cliente.post(f"/amazon/carrinho/{pendente}/conferido", follow_redirects=False).status_code == 404
    assert cliente.post("/amazon/carrinho/999999/conferido", follow_redirects=False).status_code == 404
    with sessoes() as s:
        conf = s.get(ConferenciaCheckout, pendente)
        assert (conf.item_removido, conf.conferir_a_mao_em) == (False, None)  # a retirada automática continua
        assert [i.conferencia_id for i in repo_amz.conferencias_com_item_no_carrinho(s)] == [pendente]
    r = cliente.post(f"/amazon/carrinho/{a_mao}/conferido", follow_redirects=False)
    assert r.status_code == 303
    with sessoes() as s:
        conf = s.get(ConferenciaCheckout, a_mao)
        assert (conf.item_removido, conf.conferir_a_mao_em) == (True, None)
    assert cliente.post(f"/amazon/carrinho/{a_mao}/conferido", follow_redirects=False).status_code == 404
