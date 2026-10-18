import random
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fakes import (
    AvisadorFake,
    NavegadorInterativoFake,
    criar_anuncio,
    criar_preco_liga,
    criar_produto,
    html_busca,
    html_vendedor,
    oferta_lista,
    pagina_html,
)
from fakes_checkout import carrinho, checkout_resumo, login
from fakes_ofertas import bloco_oferta, html_ofertas
from sqlalchemy import select

from tcg_sniper.avisos.catalogo import TipoAviso
from tcg_sniper.coletor_amazon.busca import url_busca
from tcg_sniper.coletor_amazon.config import aplicar_config
from tcg_sniper.coletor_amazon.parsers import URL_CARRINHO, url_ofertas, url_painel_ofertas, url_vendedor
from tcg_sniper.coletor_amazon.varredura import (
    ESPERA_OCIOSA_S,
    MOTIVO_EM_ANDAMENTO,
    RETIRADA_AUTOMATICA_MAX,
    VarreduraAmazon,
)
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    ConferenciaCheckout,
    Envio,
    EstadoColetorTipo,
    OfertaAmazon,
    Oportunidade,
    OrigemPreco,
    SituacaoCheckout,
    StatusCasamento,
)
from tcg_sniper.navegador.modelos import ErroRede
from tcg_sniper.notificador.base import Destino

SP = ZoneInfo("America/Sao_Paulo")
MEIO_DIA = datetime(2026, 10, 15, 12, 0, tzinfo=SP)
CAPTCHA = '<html><body><form action="/errors/validateCaptcha"></form></body></html>'


class Relogio:
    def __init__(self, agora):
        self.agora = agora

    def __call__(self):
        return self.agora


class FabricaFake:
    def __init__(self, navegador):
        self.navegador = navegador

    def __call__(self):
        fabrica = self

        class Contexto:
            def __enter__(self):
                return fabrica.navegador

            def __exit__(self, *_exc):
                pass

        return Contexto()


def varredura(engine, sessoes, config, paginas, apos_clique=None, relogio=None):
    navegador = NavegadorInterativoFake(paginas, apos_clique or [])
    avisador = AvisadorFake()
    relogio = relogio or Relogio(MEIO_DIA)
    v = VarreduraAmazon(
        engine, sessoes, FabricaFake(navegador), avisador, config,
        relogio=relogio, rng=random.Random(1), dormir=lambda _: None,
    )
    return v, navegador, avisador, relogio


def confirmado(sessoes, nome, asin, preco=None, lido_em=MEIO_DIA):
    """Produto (R$ 1.000 na Liga) casado com o anúncio; com `preco`, já lido pelo monitor em `lido_em` com
    essa oferta da Amazon como a melhor. A descoberta do produto só volta daqui a 7 dias."""
    with sessoes() as s, s.begin():
        p = criar_produto(s, nome, nome=nome)
        criar_preco_liga(s, p, "1000.00", listagem_em=MEIO_DIA)
        a = criar_anuncio(s, asin, produto=p, status=StatusCasamento.CONFIRMADO)
        if preco is not None:
            o = oferta_lista(preco, vendedor="Amazon.com.br", seller_id="amazon", envio=Envio.AMAZON, posicao=0)
            repo_amz.gravar_ofertas(s, a.id, lido_em, [repo_amz.OfertaAvaliada(o, None, True, True)])
            repo_amz.registrar_preco(s, a.id, o.preco, OrigemPreco.OFERTAS, None, Envio.AMAZON, lido_em, SP)
        repo_amz.sincronizar_fila(s, MEIO_DIA)
        repo_amz.reagendar(s, p.id, MEIO_DIA, MEIO_DIA + timedelta(days=7), False)
        return p.id, a.id


def livre(sessoes, nome):
    """Produto sem par, vencido na fila da descoberta. Devolve a URL da busca."""
    with sessoes() as s, s.begin():
        p = criar_produto(s, nome, nome=nome)
        criar_preco_liga(s, p, "1000.00", listagem_em=MEIO_DIA)
        repo_amz.sincronizar_fila(s, MEIO_DIA - timedelta(hours=1))
        return url_busca(repo_amz.obter_config(s), nome)


def ofertas(asin, preco):
    return pagina_html(
        html_ofertas(bloco_oferta(preco, "Amazon.com.br", seller_id=None, envia=None, destaque=True)), url=url_ofertas(asin)
    )


def painel(asin, preco):
    return pagina_html(
        html_ofertas(bloco_oferta(preco, "Amazon.com.br", seller_id=None, envia=None, destaque=True), comprar_agora=True, carrinho=0),
        url=url_painel_ofertas(asin),
    )


def conferencias(sessoes):
    with sessoes() as s:
        return list(s.scalars(select(ConferenciaCheckout).order_by(ConferenciaCheckout.id)))


def test_conferencia_antes_do_monitor_antes_da_descoberta(engine, sessoes, config):
    url_livre = livre(sessoes, "livre")
    _, candidata = confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    confirmado(sessoes, "venc", "B0VENC0001", "990.00", lido_em=MEIO_DIA - timedelta(minutes=20))
    um_item = carrinho("B0CAND0001", subtotal="R$ 700,00")
    paginas = {
        URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()],
        url_painel_ofertas("B0CAND0001"): painel("B0CAND0001", "R$ 700,00"),
        url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00"),
        url_livre: pagina_html(html_busca(), url=url_livre),
    }
    v, navegador, avisador, _ = varredura(
        engine, sessoes, config, paginas, [um_item, checkout_resumo("R$ 700,00", "R$ 0,00", None, "R$ 700,00"), carrinho()]
    )
    assert v.passo() == 0  # conferência
    assert v.passo() == 0  # monitor
    assert v.passo() == 0  # descoberta
    assert v.passo() == ESPERA_OCIOSA_S
    visitadas = navegador.visitadas
    assert visitadas.index(URL_CARRINHO) < visitadas.index(url_ofertas("B0VENC0001")) < visitadas.index(url_livre)
    [conf] = conferencias(sessoes)
    assert (conf.anuncio_id, conf.situacao, conf.total, conf.item_removido) == (candidata, SituacaoCheckout.OK, Decimal("700.00"), True)
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)).preco_amazon == Decimal("700.00")
    [(_, texto)] = [m for m in avisador.mensagens if m[0] is Destino.OPORTUNIDADES]
    assert "(conferido; frete" in texto


def test_janela_propria_do_monitor(engine, sessoes, config):
    url_livre = livre(sessoes, "livre")
    confirmado(sessoes, "venc", "B0VENC0001")  # nunca lido: vencido
    with sessoes() as s, s.begin():
        aplicar_config(s, {"janela_inicio": time(14, 0)}, MEIO_DIA)  # a busca só começa às 14h
    paginas = {url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00"), url_livre: pagina_html(html_busca(), url=url_livre)}
    v, navegador, _, _ = varredura(engine, sessoes, config, paginas)
    assert v.passo() == 0
    assert v.passo() == ESPERA_OCIOSA_S
    assert navegador.visitadas == [url_ofertas("B0VENC0001")]


def test_monitor_fora_da_janela_dele_a_descoberta_segue(engine, sessoes, config):
    url_livre = livre(sessoes, "livre")
    confirmado(sessoes, "venc", "B0VENC0001")
    with sessoes() as s, s.begin():
        aplicar_config(s, {"monitor_janela_inicio": time(14, 0)}, MEIO_DIA)
    paginas = {url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00"), url_livre: pagina_html(html_busca(), url=url_livre)}
    v, navegador, _, _ = varredura(engine, sessoes, config, paginas)
    v.passo()
    assert navegador.visitadas == [url_livre]


def test_monitor_desligado_nao_le(engine, sessoes, config):
    confirmado(sessoes, "venc", "B0VENC0001")
    with sessoes() as s, s.begin():
        aplicar_config(s, {"monitor_ligado": False}, MEIO_DIA)
    v, navegador, _, _ = varredura(engine, sessoes, config, {})
    assert v.passo() == ESPERA_OCIOSA_S and navegador.visitadas == []


def test_conferencia_desligada_nao_confere(engine, sessoes, config):
    confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    with sessoes() as s, s.begin():
        aplicar_config(s, {"checkout_ligado": False}, MEIO_DIA)
    v, navegador, _, _ = varredura(engine, sessoes, config, {})
    assert v.passo() == ESPERA_OCIOSA_S and navegador.visitadas == []


def test_monitor_e_conferencia_somam_no_mesmo_teto_e_a_descoberta_segue(engine, sessoes, config):
    url_livre = livre(sessoes, "livre")
    confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    confirmado(sessoes, "venc", "B0VENC0001", "990.00", lido_em=MEIO_DIA - timedelta(minutes=20))
    with sessoes() as s, s.begin():
        aplicar_config(s, {"monitor_max_paginas_hora": 5}, MEIO_DIA)
    um_item = carrinho("B0CAND0001", subtotal="R$ 700,00")
    paginas = {
        URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()],
        url_painel_ofertas("B0CAND0001"): painel("B0CAND0001", "R$ 700,00"),
        url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00"),
        url_livre: pagina_html(html_busca(), url=url_livre),
    }
    v, navegador, _, relogio = varredura(
        engine, sessoes, config, paginas, [um_item, checkout_resumo("R$ 700,00", "R$ 0,00", None, "R$ 700,00"), carrinho()]
    )
    v.passo()  # a conferência abre 8 páginas: estoura o teto de 5
    v.passo()  # o monitor espera; a descoberta tem o próprio teto
    assert url_livre in navegador.visitadas and url_ofertas("B0VENC0001") not in navegador.visitadas
    relogio.agora += timedelta(minutes=61)
    v.passo()
    assert navegador.visitadas[-1] == url_ofertas("B0VENC0001")


def test_descoberta_so_de_nao_casados_e_casados_com_7_dias(engine, sessoes, config):
    url_livre = livre(sessoes, "livre")
    confirmado(sessoes, "recente", "B0RECE0001", "990.00")
    velho_id, _ = confirmado(sessoes, "velho", "B0VELH0001", "990.00")
    with sessoes() as s, s.begin():
        repo_amz.reagendar(s, velho_id, MEIO_DIA - timedelta(days=8), MEIO_DIA - timedelta(days=1), False)
        url_velho = url_busca(repo_amz.obter_config(s), "velho")
    paginas = {u: pagina_html(html_busca(), url=u) for u in (url_livre, url_velho)}
    v, navegador, _, _ = varredura(engine, sessoes, config, paginas)
    v.passo()
    v.passo()
    assert v.passo() == ESPERA_OCIOSA_S
    assert sorted(navegador.visitadas) == sorted([url_livre, url_velho])


def test_sem_login_desliga_a_conferencia_avisa_uma_vez_e_o_monitor_continua(engine, sessoes, config):
    confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    confirmado(sessoes, "venc", "B0VENC0001", "990.00", lido_em=MEIO_DIA - timedelta(minutes=20))
    um_item = carrinho("B0CAND0001", subtotal="R$ 700,00")
    paginas = {
        URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()],
        url_painel_ofertas("B0CAND0001"): painel("B0CAND0001", "R$ 700,00"),
        url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00"),
    }
    v, navegador, avisador, _ = varredura(engine, sessoes, config, paginas, [um_item, login(), carrinho()])
    v.passo()
    [conf] = conferencias(sessoes)
    assert (conf.situacao, conf.item_removido) == (SituacaoCheckout.SEM_LOGIN, True)
    with sessoes() as s:
        assert repo_amz.obter_config(s).checkout_sem_login_em == MEIO_DIA
    v.passo()
    assert navegador.visitadas[-1] == url_ofertas("B0VENC0001")  # o monitor segue
    v.passo()
    [sem_login] = avisador.dados(TipoAviso.AMAZON_SEM_LOGIN)
    assert sem_login.linhas == ("A conferência de checkout parou; o monitor de preço continua",)
    [texto] = [t for d, t in avisador.mensagens if "conta sem login" in t]
    assert "porta 6081" in texto and "Retomar conferência" in texto
    assert len(conferencias(sessoes)) == 1


def test_item_que_ficou_no_carrinho_e_retirado_na_proxima_volta(engine, sessoes, config):
    _, anuncio_id = confirmado(sessoes, "cand", "B0CAND0001")
    with sessoes() as s, s.begin():
        presa = repo_amz.registrar_conferencia(
            s, em=MEIO_DIA - timedelta(minutes=5), anuncio_id=anuncio_id, vendedor_nome="Amazon.com.br",
            preco_anunciado=Decimal("700.00"), itens=None, frete=None, impostos=None, total=None,
            situacao=SituacaoCheckout.FALHA, motivo="x", item_removido=False,
        ).id
    um_item = carrinho("B0CAND0001", subtotal="R$ 700,00")  # exatamente como a conferência deixou
    v, navegador, _, _ = varredura(
        engine, sessoes, config,
        {URL_CARRINHO: [um_item, carrinho()], url_ofertas("B0CAND0001"): ofertas("B0CAND0001", "R$ 990,00")},
        [carrinho()],
    )
    v.passo()
    assert navegador.cliques[-1][0].endswith('[data-asin="B0CAND0001"] input[data-action="delete"]')
    with sessoes() as s:
        assert s.get(ConferenciaCheckout, presa).item_removido is True
    v.passo()
    assert navegador.visitadas[-1] == url_ofertas("B0CAND0001")


def test_carrinho_ocupado_espera_uma_hora(engine, sessoes, config):
    confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    ocupado = carrinho("B0DOUSUARIO")
    v, navegador, _, relogio = varredura(engine, sessoes, config, {URL_CARRINHO: [ocupado, ocupado]})
    v.passo()
    assert conferencias(sessoes)[0].situacao is SituacaoCheckout.CARRINHO_OCUPADO and navegador.cliques == []
    assert v.passo() == ESPERA_OCIOSA_S and navegador.visitadas == [URL_CARRINHO]
    relogio.agora += timedelta(minutes=61)
    with sessoes() as s, s.begin():  # nova leitura do monitor agora (ofertas e preço com o mesmo `agora`)
        anuncio_id = conferencias(sessoes)[0].anuncio_id
        o = oferta_lista("700.00", vendedor="Amazon.com.br", seller_id="amazon", envio=Envio.AMAZON, posicao=0)
        repo_amz.gravar_ofertas(s, anuncio_id, relogio.agora, [repo_amz.OfertaAvaliada(o, None, True, True)])
        repo_amz.registrar_preco(s, anuncio_id, Decimal("700.00"), OrigemPreco.OFERTAS, None, Envio.AMAZON, relogio.agora, SP)
    v.passo()
    assert navegador.visitadas == [URL_CARRINHO, URL_CARRINHO]


def test_monitor_que_falha_nao_trava_no_mesmo_anuncio(engine, sessoes, config):
    confirmado(sessoes, "a", "B0AAAA0001")
    confirmado(sessoes, "b", "B0BBBB0001")
    paginas = {
        url_ofertas("B0AAAA0001"): pagina_html("<html><body>layout novo</body></html>", url=url_ofertas("B0AAAA0001")),
        url_ofertas("B0BBBB0001"): ofertas("B0BBBB0001", "R$ 990,00"),
    }
    v, navegador, _, _ = varredura(engine, sessoes, config, paginas)
    v.passo()
    v.passo()
    assert navegador.visitadas == [url_ofertas("B0AAAA0001"), url_ofertas("B0BBBB0001")]
    assert v.passo() == ESPERA_OCIOSA_S


def test_captcha_no_monitor_pausa_a_amazon(engine, sessoes, config):
    confirmado(sessoes, "a", "B0AAAA0001")
    v, _, avisador, _ = varredura(engine, sessoes, config, {url_ofertas("B0AAAA0001"): pagina_html(CAPTCHA, url=url_ofertas("B0AAAA0001"))})
    assert v.passo() == ESPERA_OCIOSA_S
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.PAUSADO_DESAFIO
    assert TipoAviso.AMAZON_CAPTCHA in avisador.tipos()


def test_leituras_com_mais_de_30_dias_sao_apagadas(engine, sessoes, config):
    confirmado(sessoes, "a", "B0AAAA0001", "990.00", lido_em=MEIO_DIA - timedelta(days=31))
    v, _, _, _ = varredura(engine, sessoes, config, {url_ofertas("B0AAAA0001"): ofertas("B0AAAA0001", "R$ 990,00")})
    v.passo()
    with sessoes() as s:
        assert {o.lida_em for o in s.scalars(select(OfertaAmazon))} == {MEIO_DIA}


def test_marca_de_conferencia_em_andamento_garante_a_retirada_depois_de_um_reinicio(engine, sessoes, config):
    confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    um_item = carrinho("B0CAND0001", subtotal="R$ 700,00")
    v, navegador, _, _ = varredura(
        engine, sessoes, config,
        {URL_CARRINHO: [carrinho(), um_item, carrinho()], url_painel_ofertas("B0CAND0001"): painel("B0CAND0001", "R$ 700,00")},
        [carrinho()],
    )

    def morre_no_clique(seletor, indice, guarda):  # SIGTERM no meio: nada de retirada nesta volta
        raise SystemExit(0)

    navegador.clicar = morre_no_clique
    with pytest.raises(SystemExit):
        v.passo()
    [marca] = conferencias(sessoes)
    assert (marca.situacao, marca.item_removido) == (SituacaoCheckout.FALHA, False) and "andamento" in marca.motivo
    del navegador.clicar  # o coletor reinicia (mesmas páginas): a primeira volta tira o item
    v2 = VarreduraAmazon(
        engine, sessoes, FabricaFake(navegador), AvisadorFake(), config,
        relogio=Relogio(MEIO_DIA), rng=random.Random(1), dormir=lambda _: None,
    )
    v2.inicializar()
    navegador.paginas[URL_CARRINHO] = [um_item, carrinho()]
    assert v2.passo() == 0
    assert navegador.cliques[-1][0].endswith('[data-asin="B0CAND0001"] input[data-action="delete"]')
    with sessoes() as s:
        assert s.get(ConferenciaCheckout, marca.id).item_removido is True


def test_conferencia_concluida_atualiza_a_marca_sem_duplicar(engine, sessoes, config):
    confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    um_item = carrinho("B0CAND0001", subtotal="R$ 700,00")
    v, _, _, _ = varredura(
        engine, sessoes, config,
        {URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()], url_painel_ofertas("B0CAND0001"): painel("B0CAND0001", "R$ 700,00")},
        [um_item, checkout_resumo("R$ 700,00", "R$ 25,00", None, "R$ 725,00"), carrinho()],
    )
    v.passo()
    [conf] = conferencias(sessoes)
    assert (conf.situacao, conf.motivo, conf.item_removido, conf.frete) == (SituacaoCheckout.OK, None, True, Decimal("25.00"))


def test_item_preso_sai_mesmo_fora_da_janela_e_acima_do_teto(engine, sessoes, config):
    _, anuncio_id = confirmado(sessoes, "cand", "B0CAND0001")
    noite = datetime(2026, 10, 15, 23, 30, tzinfo=SP)
    with sessoes() as s, s.begin():
        aplicar_config(s, {"monitor_max_paginas_hora": 1}, MEIO_DIA)
        presa = repo_amz.registrar_conferencia(
            s, em=noite - timedelta(minutes=5), anuncio_id=anuncio_id, vendedor_nome="Amazon.com.br",
            preco_anunciado=Decimal("700.00"), itens=None, frete=None, impostos=None, total=None,
            situacao=SituacaoCheckout.FALHA, motivo="x", item_removido=False,
        ).id
    um_item = carrinho("B0CAND0001", subtotal="R$ 700,00")
    v, navegador, _, _ = varredura(engine, sessoes, config, {URL_CARRINHO: [um_item, carrinho()]}, [carrinho()], Relogio(noite))
    v.passo()
    with sessoes() as s:
        assert s.get(ConferenciaCheckout, presa).item_removido is True
    assert v.passo() == ESPERA_OCIOSA_S and navegador.visitadas == [URL_CARRINHO, URL_CARRINHO]


def test_item_que_nao_sai_espera_15_minutos_e_conta_a_tentativa(engine, sessoes, config):
    _, anuncio_id = confirmado(sessoes, "cand", "B0CAND0001", "990.00")
    with sessoes() as s, s.begin():
        presa = repo_amz.registrar_conferencia(
            s, em=MEIO_DIA - timedelta(minutes=5), anuncio_id=anuncio_id, vendedor_nome="Amazon.com.br",
            preco_anunciado=Decimal("700.00"), itens=None, frete=None, impostos=None, total=None,
            situacao=SituacaoCheckout.FALHA, motivo="x", item_removido=False,
        ).id
    um_item = carrinho("B0CAND0001", subtotal="R$ 700,00")
    v, navegador, avisador, relogio = varredura(
        engine, sessoes, config, {URL_CARRINHO: [um_item, um_item, um_item, um_item]}, [um_item, um_item]
    )
    v.passo()
    assert v.passo() == ESPERA_OCIOSA_S and len(navegador.cliques) == 1
    with sessoes() as s:
        conf = s.get(ConferenciaCheckout, presa)
        assert (conf.retiradas_tentadas, conf.retirada_tentada_em, conf.conferir_a_mao_em) == (1, MEIO_DIA, None)
    relogio.agora += timedelta(minutes=16)
    with sessoes() as s, s.begin():  # sem leitura vencida do monitor: só a retirada tem o que fazer
        repo_amz.registrar_preco(s, anuncio_id, Decimal("990.00"), OrigemPreco.OFERTAS, None, Envio.AMAZON, relogio.agora, SP)
    v.passo()
    assert len(navegador.cliques) == 2
    assert TipoAviso.AMAZON_CARRINHO not in avisador.tipos()  # aviso só ao passar para "à mão"


# --- retirada automática só com o carrinho exatamente como a conferência deixou ---------------------


def preso(sessoes, asin="B0CAND0001", em=MEIO_DIA - timedelta(minutes=5), nome="cand"):
    """Anúncio já lido agora (o monitor não tem o que fazer) e uma conferência com o item no carrinho."""
    _, anuncio_id = confirmado(sessoes, nome, asin, "990.00")
    with sessoes() as s, s.begin():
        return repo_amz.registrar_conferencia(
            s, em=em, anuncio_id=anuncio_id, vendedor_nome="Amazon.com.br",
            preco_anunciado=Decimal("700.00"), itens=None, frete=None, impostos=None, total=None,
            situacao=SituacaoCheckout.FALHA, motivo=MOTIVO_EM_ANDAMENTO, item_removido=False,
        ).id


def avisos_a_mao(avisador, asin="B0CAND0001"):
    return [d for tipo, chave, d in avisador.avisos if tipo is TipoAviso.AMAZON_CARRINHO and chave == asin]


def assert_a_mao_sem_clique(sessoes, conferencia_id, navegador, avisador, v):
    assert navegador.cliques == []
    with sessoes() as s:
        conf = s.get(ConferenciaCheckout, conferencia_id)
        assert conf.item_removido is False and conf.conferir_a_mao_em == MEIO_DIA and "conferir à mão" in conf.motivo
    [aviso] = avisos_a_mao(avisador)
    assert aviso.titulo_extra == "B0CAND0001"
    assert aviso.linhas[0] == "Pode haver 1× B0CAND0001 de uma conferência automática no carrinho"
    assert "noVNC da Amazon (porta 6081)" in avisador.mensagens[-1][1]
    visitadas = len(navegador.visitadas)
    assert v.passo() == ESPERA_OCIOSA_S  # estado persistente: não volta ao carrinho, não avisa de novo
    assert len(navegador.visitadas) == visitadas and len(avisos_a_mao(avisador)) == 1


@pytest.mark.parametrize(
    "pagina",
    [
        carrinho("B0CAND0001", contador=2, subtotal="R$ 1.400,00"),  # o mesmo ASIN com quantidade 2
        carrinho("B0CAND0001", "B0OUTRO001", subtotal="R$ 700,00"),  # o ASIN e mais um item
        carrinho("B0CAND0001", subtotal="R$ 650,00"),  # subtotal diferente do anunciado
    ],
    ids=["quantidade-2", "outro-item", "subtotal-diferente"],
)
def test_carrinho_diferente_do_que_a_conferencia_deixou_nao_e_clicado(engine, sessoes, config, pagina):
    conferencia_id = preso(sessoes)
    v, navegador, avisador, _ = varredura(engine, sessoes, config, {URL_CARRINHO: [pagina]})
    assert v.passo() == 0
    assert_a_mao_sem_clique(sessoes, conferencia_id, navegador, avisador, v)


def test_marca_com_mais_de_30_min_nao_e_clicada(engine, sessoes, config):
    conferencia_id = preso(sessoes, em=MEIO_DIA - RETIRADA_AUTOMATICA_MAX - timedelta(minutes=1))
    v, navegador, avisador, _ = varredura(engine, sessoes, config, {URL_CARRINHO: [carrinho("B0CAND0001", subtotal="R$ 700,00")]})
    assert v.passo() == 0
    assert_a_mao_sem_clique(sessoes, conferencia_id, navegador, avisador, v)


def test_marca_velha_com_o_item_ja_fora_resolve_sem_clicar(engine, sessoes, config):
    conferencia_id = preso(sessoes, em=MEIO_DIA - timedelta(hours=2))
    v, navegador, avisador, _ = varredura(engine, sessoes, config, {URL_CARRINHO: [carrinho("B0DOUSUARIO")]})
    v.passo()
    with sessoes() as s:
        conf = s.get(ConferenciaCheckout, conferencia_id)
        assert conf.item_removido is True and conf.conferir_a_mao_em is None
    assert navegador.cliques == [] and TipoAviso.AMAZON_CARRINHO not in avisador.tipos()


def test_tres_falhas_passam_para_conferir_a_mao_e_o_aviso_nao_se_repete_depois_de_reiniciar(engine, sessoes, config):
    conferencia_id = preso(sessoes, em=MEIO_DIA - timedelta(minutes=1))
    relogio = Relogio(MEIO_DIA)
    v, navegador, avisador, _ = varredura(engine, sessoes, config, {URL_CARRINHO: [login(), login(), login()]}, relogio=relogio)
    for tentativa in range(1, 4):
        v.passo()
        with sessoes() as s:
            assert s.get(ConferenciaCheckout, conferencia_id).retiradas_tentadas == tentativa
        relogio.agora += timedelta(minutes=16)
        with sessoes() as s, s.begin():  # leitura do monitor em dia: só a retirada tem o que fazer
            atual = conferencias(sessoes)[0].anuncio_id
            o = oferta_lista("990.00", vendedor="Amazon.com.br", seller_id="amazon", envio=Envio.AMAZON, posicao=0)
            repo_amz.gravar_ofertas(s, atual, relogio.agora, [repo_amz.OfertaAvaliada(o, None, True, True)])
            repo_amz.registrar_preco(s, atual, o.preco, OrigemPreco.OFERTAS, None, Envio.AMAZON, relogio.agora, SP)
    assert navegador.cliques == [] and len(avisos_a_mao(avisador)) == 1
    with sessoes() as s:
        assert s.get(ConferenciaCheckout, conferencia_id).conferir_a_mao_em is not None
    novo = AvisadorFake()  # o coletor reinicia: o aviso está gravado no estado, não se repete
    v2 = VarreduraAmazon(
        engine, sessoes, FabricaFake(navegador), novo, config, relogio=relogio, rng=random.Random(1), dormir=lambda _: None,
    )
    v2.inicializar()
    visitadas = len(navegador.visitadas)
    assert v2.passo() == ESPERA_OCIOSA_S and len(navegador.visitadas) == visitadas and avisos_a_mao(novo) == []


def test_um_asin_preso_nao_impede_a_retirada_dos_outros(engine, sessoes, config):
    primeiro = preso(sessoes, "B0PRIM0001", nome="primeiro", em=MEIO_DIA - timedelta(minutes=6))
    segundo = preso(sessoes, "B0SEGU0001", nome="segundo")
    v, navegador, _, _ = varredura(
        engine, sessoes, config,
        {URL_CARRINHO: [login(), carrinho("B0SEGU0001", subtotal="R$ 700,00"), carrinho()]},
        [carrinho()],
    )
    v.passo()  # o mais antigo falha (carrinho ilegível) ...
    v.passo()  # ... e o próximo passo vai ao outro, sem esperar o primeiro
    with sessoes() as s:
        assert s.get(ConferenciaCheckout, primeiro).retiradas_tentadas == 1
        assert s.get(ConferenciaCheckout, segundo).item_removido is True
    assert navegador.cliques[-1][0].endswith('[data-asin="B0SEGU0001"] input[data-action="delete"]')


def test_captcha_depois_de_adicionar_avisa_que_o_item_ficou_no_carrinho(engine, sessoes, config):
    confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    paginas = {
        URL_CARRINHO: [carrinho(), pagina_html(CAPTCHA, url=URL_CARRINHO)],
        url_painel_ofertas("B0CAND0001"): painel("B0CAND0001", "R$ 700,00"),
    }
    um_item = carrinho("B0CAND0001", subtotal="R$ 700,00")
    v, _, avisador, _ = varredura(engine, sessoes, config, paginas, [um_item])
    assert v.passo() == ESPERA_OCIOSA_S
    [captcha] = avisador.dados(TipoAviso.AMAZON_CAPTCHA)
    assert any("1× B0CAND0001 no carrinho" in linha for linha in captcha.linhas)
    assert captcha.linhas[2] == (
        "Uma conferência deixou 1× B0CAND0001 no carrinho: sai sozinho se você retomar em até 30 min; senão confira à mão"
    )
    [conf] = conferencias(sessoes)
    assert conf.item_removido is False


def test_erro_inesperado_na_conferencia_conta_as_paginas_no_teto(engine, sessoes, config, monkeypatch):
    from tcg_sniper.coletor_amazon import checkout as modulo_checkout

    confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    with sessoes() as s, s.begin():
        aplicar_config(s, {"monitor_max_paginas_hora": 1}, MEIO_DIA)

    def quebra(nav, alvo, abrir, pausar, ao_adicionar=None):
        abrir(URL_CARRINHO)
        raise RuntimeError("bug")

    monkeypatch.setattr(modulo_checkout, "conferir", quebra)
    v, _, _, _ = varredura(engine, sessoes, config, {URL_CARRINHO: [carrinho()]})
    with pytest.raises(RuntimeError):
        v.passo()
    assert v._teto_monitor.liberado_em(MEIO_DIA, 1) is not None  # a página aberta contou


def test_conferencia_ok_zera_as_falhas_seguidas(engine, sessoes, config):
    confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    um_item = carrinho("B0CAND0001", subtotal="R$ 700,00")
    v, _, _, _ = varredura(
        engine, sessoes, config,
        {URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()], url_painel_ofertas("B0CAND0001"): painel("B0CAND0001", "R$ 700,00")},
        [um_item, checkout_resumo("R$ 700,00", "R$ 0,00", None, "R$ 700,00"), carrinho()],
    )
    v._falhas_seguidas = 5
    v.passo()
    assert v._falhas_seguidas == 0



def test_erro_depois_do_clique_na_retirada_conta_as_paginas_abertas(engine, sessoes, config, monkeypatch):
    from tcg_sniper.coletor_amazon import varredura as modulo

    preso(sessoes)
    with sessoes() as s, s.begin():
        aplicar_config(s, {"monitor_max_paginas_hora": 2}, MEIO_DIA)

    def quebra_depois_de_abrir(nav, asin, abrir, pausar, carrinho=None, contar_clique=None):
        abrir(URL_CARRINHO)  # recarrega depois do clique e quebra
        raise RuntimeError("bug")

    monkeypatch.setattr(modulo, "remover_do_carrinho", quebra_depois_de_abrir)
    um_item = carrinho("B0CAND0001", subtotal="R$ 700,00")
    v, _, _, _ = varredura(engine, sessoes, config, {URL_CARRINHO: [um_item, carrinho()]})
    with pytest.raises(RuntimeError):
        v.passo()
    assert v._teto_monitor.liberado_em(MEIO_DIA, 2) is not None  # as 2 páginas abertas contaram


def test_clique_de_excluir_que_falha_depois_de_carregar_conta_no_teto(engine, sessoes, config):
    from tcg_sniper.navegador.modelos import ErroRede

    preso(sessoes)
    with sessoes() as s, s.begin():
        aplicar_config(s, {"monitor_max_paginas_hora": 2}, MEIO_DIA)
    um_item = carrinho("B0CAND0001", subtotal="R$ 700,00")
    v, navegador, _, _ = varredura(engine, sessoes, config, {URL_CARRINHO: [um_item]}, [ErroRede("timeout depois do clique")])
    v.passo()
    assert len(navegador.cliques) == 1
    assert v._teto_monitor.liberado_em(MEIO_DIA, 2) is not None  # o carrinho e a página do clique que falhou


def test_retirada_ok_conta_tambem_a_pagina_do_clique(engine, sessoes, config):
    preso(sessoes)
    with sessoes() as s, s.begin():
        aplicar_config(s, {"monitor_max_paginas_hora": 3}, MEIO_DIA)
    um_item = carrinho("B0CAND0001", subtotal="R$ 700,00")
    v, navegador, _, _ = varredura(engine, sessoes, config, {URL_CARRINHO: [um_item, carrinho()]}, [carrinho()])
    v.passo()
    assert len(navegador.cliques) == 1
    assert v._teto_monitor.liberado_em(MEIO_DIA, 3) is not None  # carrinho, clique em Excluir e a recarga


def test_carrinho_de_visitante_nao_resolve_a_retirada(engine, sessoes, config):
    conferencia_id = preso(sessoes)
    v, navegador, _, _ = varredura(engine, sessoes, config, {URL_CARRINHO: [carrinho(logado=False)]})
    assert v.passo() == 0
    with sessoes() as s:
        conf = s.get(ConferenciaCheckout, conferencia_id)
        assert (conf.item_removido, conf.retiradas_tentadas) == (False, 1)
    assert navegador.cliques == []


def test_conferencia_que_falha_avisa_na_hora_com_o_preco_anunciado(engine, sessoes, config):
    confirmado(sessoes, "cand", "B0CAND0001", "700.00")  # lida agora: 30% abaixo, à espera da conferência
    sem_contador = pagina_html(
        html_ofertas(bloco_oferta("R$ 700,00", "Amazon.com.br", seller_id=None, envia=None, destaque=True)),
        url=url_painel_ofertas("B0CAND0001"),
    )
    paginas = {URL_CARRINHO: [carrinho()], url_painel_ofertas("B0CAND0001"): sem_contador}
    v, navegador, avisador, _ = varredura(engine, sessoes, config, paginas)
    v.passo()  # contador do carrinho ilegível no painel: falha sem clicar
    assert conferencias(sessoes)[0].situacao is SituacaoCheckout.FALHA and navegador.cliques == []
    [texto] = [t for d, t in avisador.mensagens if d is Destino.OPORTUNIDADES]
    assert "não conferido: a conferência falhou: contador do carrinho ilegível" in texto
    assert "Amazon: *R$ 700,00* (anunciado, sem impostos" in texto
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)).preco_alertado == Decimal("700.00")


def test_oferta_que_sumiu_do_painel_nao_avisa_com_o_anunciado(engine, sessoes, config):
    confirmado(sessoes, "cand", "B0CAND0001", "700.00")  # lida agora: 30% abaixo, à espera da conferência
    paginas = {URL_CARRINHO: [carrinho()], url_painel_ofertas("B0CAND0001"): painel("B0CAND0001", "R$ 720,00")}
    v, navegador, avisador, _ = varredura(engine, sessoes, config, paginas)
    v.passo()  # a oferta mudou no painel: falha sem clicar; a próxima leitura decide
    [conf] = conferencias(sessoes)
    assert conf.situacao is SituacaoCheckout.FALHA and conf.motivo.startswith("a oferta não está mais no painel")
    assert navegador.cliques == []
    assert [t for d, t in avisador.mensagens if d is Destino.OPORTUNIDADES] == []
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)) is None


def test_captcha_na_retirada_avisa_qual_item_pode_ter_ficado(engine, sessoes, config):
    preso(sessoes)
    v, navegador, avisador, _ = varredura(engine, sessoes, config, {URL_CARRINHO: [pagina_html(CAPTCHA, url=URL_CARRINHO)]})
    assert v.passo() == ESPERA_OCIOSA_S and navegador.cliques == []
    [captcha] = avisador.dados(TipoAviso.AMAZON_CAPTCHA)
    assert any("1× B0CAND0001 no carrinho" in linha for linha in captcha.linhas)
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.PAUSADO_DESAFIO


def test_leitura_que_falha_conta_no_teto_todas_as_paginas_abertas(engine, sessoes, config):
    confirmado(sessoes, "a", "B0AAAA0001")
    with sessoes() as s, s.begin():
        aplicar_config(s, {"monitor_max_paginas_hora": 4}, MEIO_DIA)
    pagina = pagina_html(
        html_ofertas(bloco_oferta("R$ 700,00", "Loja X", "A1X"), bloco_oferta("R$ 710,00", "Loja Y", "A1Y")),
        url=url_ofertas("B0AAAA0001"),
    )
    paginas = {
        url_ofertas("B0AAAA0001"): pagina,
        url_vendedor("A1X"): pagina_html(html_vendedor("Loja X", 97, "2.340")),
        url_vendedor("A1Y"): [ErroRede("caiu"), ErroRede("caiu")],  # a nova tentativa também falha
    }
    v, navegador, _, _ = varredura(engine, sessoes, config, paginas)
    v.passo()
    assert len(navegador.visitadas) == 4  # ofertas, perfil X, perfil Y duas vezes
    assert v._teto_monitor.liberado_em(MEIO_DIA, 4) is not None  # as 4 contaram (antes: só 1)


def test_rodada_do_monitor_avisa_quando_fica_em_dia(engine, sessoes, config):
    confirmado(sessoes, "a", "B0AAAA0001", "990.00", lido_em=MEIO_DIA - timedelta(minutes=20))
    confirmado(sessoes, "b", "B0BBBB0001")
    paginas = {
        url_ofertas("B0AAAA0001"): ofertas("B0AAAA0001", "R$ 950,00"),
        url_ofertas("B0BBBB0001"): ofertas("B0BBBB0001", "R$ 990,00"),
    }
    v, _, avisador, _ = varredura(engine, sessoes, config, paginas)
    assert v.passo() == 0 and v.passo() == 0
    assert TipoAviso.AMAZON_MONITOR_CONCLUIDO not in avisador.tipos()
    assert v.passo() == ESPERA_OCIOSA_S
    [dados] = avisador.dados(TipoAviso.AMAZON_MONITOR_CONCLUIDO)
    assert dados.linhas == (
        "Anúncios lidos: 2", "Preços em queda: 1", "Conferências de checkout: 0", "Duração: menos de 1 min",
    )
    assert v.passo() == ESPERA_OCIOSA_S
    assert len(avisador.dados(TipoAviso.AMAZON_MONITOR_CONCLUIDO)) == 1


def test_monitor_ocioso_nao_avisa_rodada(engine, sessoes, config):
    confirmado(sessoes, "a", "B0AAAA0001", "990.00")  # lido agora: em dia
    v, _, avisador, _ = varredura(engine, sessoes, config, {})
    for _ in range(3):
        assert v.passo() == ESPERA_OCIOSA_S
    assert avisador.avisos == []


def test_retirada_que_ve_o_carrinho_sem_o_item_resolve_o_aviso_do_carrinho(engine, sessoes, config):
    _, anuncio_id = confirmado(sessoes, "cand", "B0CAND0001")
    with sessoes() as s, s.begin():
        repo_amz.registrar_conferencia(
            s, em=MEIO_DIA - timedelta(minutes=5), anuncio_id=anuncio_id, vendedor_nome="Amazon.com.br",
            preco_anunciado=Decimal("700.00"), itens=None, frete=None, impostos=None, total=None,
            situacao=SituacaoCheckout.FALHA, motivo="em andamento", item_removido=False,
        )
    v, _, avisador, _ = varredura(engine, sessoes, config, {URL_CARRINHO: carrinho()})
    v.passo()
    assert (TipoAviso.AMAZON_CARRINHO, "B0CAND0001") in avisador.resolvidos
