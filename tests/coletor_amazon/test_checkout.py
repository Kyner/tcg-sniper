import json
from decimal import Decimal

import pytest
from fakes import DIR_FIXTURES_AMAZON, NavegadorInterativoFake, fixture_amazon, pagina_html
from fakes_checkout import carrinho, checkout_endereco, checkout_resumo, login
from fakes_ofertas import bloco_oferta, html_ofertas

from tcg_sniper.coletor_amazon.busca import DesafioAmazon
from tcg_sniper.coletor_amazon.checkout import AlvoCheckout, ResultadoCheckout, conferir
from tcg_sniper.coletor_amazon.cliques import PROIBIDOS
from tcg_sniper.coletor_amazon.parsers import URL_CARRINHO, url_painel_ofertas
from tcg_sniper.db.models import SituacaoCheckout
from tcg_sniper.navegador.modelos import ErroRede

ASIN = "B0DNV55QBS"
ALVO = AlvoCheckout(ASIN, "Shazaar", Decimal("275.91"))
ESPERADO = json.loads((DIR_FIXTURES_AMAZON / "esperado.json").read_text(encoding="utf-8"))
EXCLUIR_ATIVO = f'[data-name="Active Items"] [data-asin="{ASIN}"] input[data-action="delete"]'


def painel(*blocos, carrinho=0):
    return pagina_html(html_ofertas(*blocos, comprar_agora=True, carrinho=carrinho), url=url_painel_ofertas(ASIN))


PAINEL = painel(
    bloco_oferta("R$ 314,11", "Amazon Global", seller_id=None, envia=None, destaque=True),
    bloco_oferta("R$ 275,91", "Shazaar", "A2SHZ", origem="Estados Unidos"),
)


def conferir_com(paginas, apos_clique):
    nav = NavegadorInterativoFake(paginas, apos_clique)
    return conferir(nav, ALVO, nav.abrir, lambda: None), nav


def clicados(nav):
    return [seletor for seletor, _ in nav.cliques]


def nenhum_proibido(nav):
    return not any(trecho in seletor.lower() for seletor in clicados(nav) for trecho in ("placeyourorder", "buy-now", "submitorder"))


def test_conferencia_ok_le_o_resumo_e_tira_o_item():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [um_item, checkout_endereco(), checkout_resumo(), carrinho()],
    )
    assert (resultado.situacao, resultado.motivo) == (SituacaoCheckout.OK, None)
    assert (resultado.itens, resultado.frete, resultado.impostos, resultado.total) == (
        Decimal("237.73"), Decimal("0.00"), Decimal("48.26"), Decimal("285.99"),
    )
    assert resultado.item_removido and resultado.paginas == 9
    assert clicados(nav) == [
        '#aod-offer input[name="submit.addToCart"]',
        'input[name="proceedToRetailCheckout"]',
        '#checkout-primary-continue-button-id input[data-testid="bottom-continue-button"]',  # BOTAO_ENTREGAR
        EXCLUIR_ATIVO,
    ]
    assert nav.cliques[0] == ('#aod-offer input[name="submit.addToCart"]', 0)  # o botão da Shazaar, não o da destacada
    assert nenhum_proibido(nav)


def test_checkout_direto_no_resumo_sem_passo_do_endereco():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [um_item, checkout_resumo(), carrinho()],
    )
    assert resultado.situacao is SituacaoCheckout.OK and resultado.total == Decimal("285.99")
    assert len(nav.cliques) == 3


def test_carrinho_ocupado_nao_clica_em_nada():
    resultado, nav = conferir_com({URL_CARRINHO: carrinho("B0OUTRO001", "B0OUTRO002")}, [])
    assert (resultado.situacao, resultado.item_removido, resultado.paginas) == (SituacaoCheckout.CARRINHO_OCUPADO, True, 1)
    assert nav.cliques == [] and nav.visitadas == [URL_CARRINHO]


def test_itens_salvos_para_depois_nao_contam_e_nunca_sao_tocados():
    salvos = ("B0SALVO001", ASIN)
    um_item = carrinho(ASIN, salvos=salvos, subtotal="R$ 275,91")
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(salvos=salvos), um_item, um_item, carrinho(salvos=salvos)], url_painel_ofertas(ASIN): PAINEL},
        [um_item, checkout_resumo(), carrinho(salvos=salvos)],
    )
    assert resultado.situacao is SituacaoCheckout.OK and resultado.item_removido
    assert clicados(nav)[-1] == EXCLUIR_ATIVO
    assert not any("Saved Items" in seletor for seletor in clicados(nav))


def test_login_no_carrinho_e_sem_login_sem_clicar():
    resultado, nav = conferir_com({URL_CARRINHO: login()}, [])
    assert resultado.situacao is SituacaoCheckout.SEM_LOGIN and nav.cliques == []


def test_login_expirado_no_checkout_retira_o_item():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [um_item, login(), carrinho()],
    )
    assert (resultado.situacao, resultado.item_removido, resultado.total) == (SituacaoCheckout.SEM_LOGIN, True, None)
    assert clicados(nav)[-1] == EXCLUIR_ATIVO


def test_botao_proibido_no_lugar_de_entregar_nao_e_clicado_e_o_item_sai():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    armadilha = checkout_endereco(botao='<input data-testid="Address_selectShipToThisAddress" type="submit" value="Confirmar pedido">')
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [um_item, armadilha, carrinho()],
    )
    assert resultado.situacao is SituacaoCheckout.FALHA and "proibido" in resultado.motivo
    assert resultado.item_removido
    assert clicados(nav) == ['#aod-offer input[name="submit.addToCart"]', 'input[name="proceedToRetailCheckout"]', EXCLUIR_ATIVO]


def test_o_botao_de_confirmar_do_resumo_nunca_e_clicado():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [um_item, checkout_endereco(), checkout_resumo(), carrinho()],
    )
    assert resultado.situacao is SituacaoCheckout.OK
    assert nenhum_proibido(nav)
    for seletor in clicados(nav):
        assert not any(trecho in seletor.lower() for trecho in PROIBIDOS)


def test_falha_no_meio_ainda_tira_o_item():
    sem_botao = pagina_html(carrinho(ASIN, subtotal="R$ 275,91").html.replace('name="proceedToRetailCheckout"', 'name="outro"'), url=URL_CARRINHO)
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), sem_botao, sem_botao, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [sem_botao, carrinho()],
    )
    assert resultado.situacao is SituacaoCheckout.FALHA and "fechar pedido" in resultado.motivo
    assert resultado.item_removido and clicados(nav)[-1] == EXCLUIR_ATIVO


def test_item_que_nao_sai_fica_registrado():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    resultado, _ = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item, um_item], url_painel_ofertas(ASIN): PAINEL},
        [um_item, checkout_resumo(), um_item],  # o clique em Excluir não tirou o item
    )
    assert resultado.situacao is SituacaoCheckout.OK and not resultado.item_removido
    assert "pode ter ficado no carrinho" in resultado.motivo


def test_oferta_que_mudou_nao_e_adicionada():
    outro_preco = painel(bloco_oferta("R$ 289,90", "Shazaar", "A2SHZ"))
    resultado, nav = conferir_com({URL_CARRINHO: carrinho(), url_painel_ofertas(ASIN): outro_preco}, [])
    assert resultado.situacao is SituacaoCheckout.FALHA and "não está mais no painel" in resultado.motivo
    assert nav.cliques == [] and resultado.item_removido


def test_subtotal_diferente_do_anunciado_falha_e_tira_o_item():
    caro = carrinho(ASIN, subtotal="R$ 314,11")  # entrou a oferta errada
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), caro, caro, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [caro, carrinho()],
    )
    assert resultado.situacao is SituacaoCheckout.FALHA and "subtotal" in resultado.motivo
    assert resultado.item_removido and clicados(nav)[-1] == EXCLUIR_ATIVO


def test_captcha_no_meio_devolve_o_desafio_sem_tentar_tirar():
    contagem = [0]

    def abrir(url):
        contagem[0] += 1
        if contagem[0] == 2:
            raise DesafioAmazon(URL_CARRINHO)
        return nav.abrir(url)

    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    nav = NavegadorInterativoFake({URL_CARRINHO: [carrinho(), um_item], url_painel_ofertas(ASIN): PAINEL}, [um_item])
    resultado = conferir(nav, ALVO, abrir, lambda: None)
    assert (resultado.situacao, resultado.desafio_url, resultado.item_removido) == (SituacaoCheckout.FALHA, URL_CARRINHO, False)


def test_fluxo_com_as_paginas_reais():
    destaque = ESPERADO["painel_importada"]["destaque"]
    alvo = AlvoCheckout(ESPERADO["painel_importada"]["asin"], destaque["vendedor"], Decimal(destaque["preco"]))
    real = {nome: pagina_html(fixture_amazon(nome), url=URL_CARRINHO) for nome in ("carrinho_vazio", "carrinho_um_item")}
    passos = [real["carrinho_um_item"]]
    if "checkout_endereco" in ESPERADO:
        passos.append(pagina_html(fixture_amazon("checkout_endereco")))
    passos += [pagina_html(fixture_amazon("checkout_resumo")), real["carrinho_vazio"]]
    nav = NavegadorInterativoFake(
        {
            URL_CARRINHO: [real["carrinho_vazio"], real["carrinho_um_item"], real["carrinho_um_item"], real["carrinho_vazio"]],
            url_painel_ofertas(alvo.asin): pagina_html(fixture_amazon("painel_importada"), url=url_painel_ofertas(alvo.asin)),
        },
        passos,
    )
    resultado = conferir(nav, alvo, nav.abrir, lambda: None)
    esperado = ESPERADO["checkout_resumo"]
    assert resultado.situacao is SituacaoCheckout.OK, resultado.motivo
    assert resultado.total == Decimal(esperado["total"]) and resultado.item_removido
    assert nenhum_proibido(nav)


# Regra do usuário (2026-10-17): o preço conferido da oportunidade é itens + impostos, sem o frete.
def test_preco_conferido_e_itens_mais_impostos_sem_frete():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    resultado, _ = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [um_item, checkout_resumo(frete="R$ 30,00", total="R$ 315,99"), carrinho()],
    )
    assert (resultado.itens, resultado.frete, resultado.impostos, resultado.total) == (
        Decimal("237.73"), Decimal("30.00"), Decimal("48.26"), Decimal("315.99"),
    )
    assert resultado.preco_conferido == Decimal("285.99")


@pytest.mark.parametrize(
    ("itens", "impostos", "esperado"),
    [
        (Decimal("237.73"), Decimal("48.26"), Decimal("285.99")),
        (Decimal("237.73"), None, Decimal("237.73")),
        (None, Decimal("48.26"), None),
    ],
)
def test_preco_conferido_sem_impostos_vale_os_itens(itens, impostos, esperado):
    resultado = ResultadoCheckout(SituacaoCheckout.OK, None, itens=itens, frete=Decimal("10.00"), impostos=impostos)
    assert resultado.preco_conferido == esperado


def test_preco_conferido_so_com_situacao_ok():
    resultado = ResultadoCheckout(SituacaoCheckout.FALHA, "x", itens=Decimal("237.73"))
    assert resultado.preco_conferido is None


def test_carrinho_ilegivel_falha_sem_clicar():
    # contador 0, mas sem o bloco do carrinho ativo (login, CAPTCHA, erro): não prova carrinho vazio
    ilegivel = pagina_html('<html><body><span id="nav-cart-count">0</span></body></html>', url=URL_CARRINHO)
    resultado, nav = conferir_com({URL_CARRINHO: ilegivel}, [])
    assert resultado.situacao is SituacaoCheckout.FALHA and nav.cliques == [] and resultado.item_removido
    assert nav.visitadas == [URL_CARRINHO]


def test_quantidade_maior_que_um_falha_e_tira_o_item():
    dois = carrinho(ASIN, contador=2)  # mesmo ASIN com quantidade 2 e subtotal ilegível
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), dois, dois, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [dois, carrinho()],
    )
    assert resultado.situacao is SituacaoCheckout.FALHA and "quantidade" in resultado.motivo
    assert resultado.item_removido and clicados(nav)[-1] == EXCLUIR_ATIVO


def test_erro_inesperado_depois_de_adicionar_falha_e_ainda_tira_o_item():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [um_item, RuntimeError("quebrou"), carrinho()],  # o clique em "Fechar pedido" quebra de um jeito inesperado
    )
    assert resultado.situacao is SituacaoCheckout.FALHA and "RuntimeError('quebrou')" in resultado.motivo
    assert resultado.item_removido and clicados(nav)[-1] == EXCLUIR_ATIVO


def test_erro_inesperado_na_retirada_nao_escapa():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    resultado, _ = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item], url_painel_ofertas(ASIN): PAINEL},
        [um_item, checkout_resumo(), RuntimeError("quebrou")],
    )
    assert resultado.situacao is SituacaoCheckout.OK and not resultado.item_removido


@pytest.mark.parametrize("erro", [RuntimeError("quebrou"), ErroRede("timeout depois do clique")], ids=["inesperado", "rede"])
def test_clique_de_excluir_que_falha_depois_de_carregar_conta_a_pagina(erro):
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item], url_painel_ofertas(ASIN): PAINEL},
        [um_item, checkout_resumo(), erro],  # o clique em Excluir carregou e quebrou
    )
    assert not resultado.item_removido
    # carrinho, painel, adicionar, carrinho, fechar pedido, carrinho da retirada e o clique que falhou
    assert resultado.paginas == len(nav.visitadas) + len(nav.cliques) == 7


def test_excluir_recusado_pela_guarda_na_retirada_nao_conta_o_clique():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    armadilha = pagina_html(um_item.html.replace('aria-label="Excluir Item', 'aria-label="Comprar agora Excluir Item'), url=URL_CARRINHO)
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, armadilha], url_painel_ofertas(ASIN): PAINEL},
        [um_item, checkout_resumo()],
    )
    assert not resultado.item_removido and clicados(nav)[-1] != EXCLUIR_ATIVO
    assert resultado.paginas == len(nav.visitadas) + len(nav.cliques) == 6


def test_erro_inesperado_antes_de_adicionar_sobe_sem_clicar():
    nav = NavegadorInterativoFake({URL_CARRINHO: carrinho(), url_painel_ofertas(ASIN): PAINEL}, [])

    def marcar():
        raise RuntimeError("banco fora")

    with pytest.raises(RuntimeError):
        conferir(nav, ALVO, nav.abrir, lambda: None, ao_adicionar=marcar)
    assert nav.cliques == []


def test_ao_adicionar_e_chamado_logo_antes_do_clique():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    nav = NavegadorInterativoFake(
        {URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [um_item, checkout_resumo(), carrinho()],
    )
    cliques_ao_marcar = []
    resultado = conferir(nav, ALVO, nav.abrir, lambda: None, ao_adicionar=lambda: cliques_ao_marcar.append(len(nav.cliques)))
    assert resultado.situacao is SituacaoCheckout.OK and cliques_ao_marcar == [0]


def test_ao_adicionar_nao_e_chamado_com_carrinho_ocupado():
    chamadas = []
    nav = NavegadorInterativoFake({URL_CARRINHO: carrinho("B0OUTRO001")}, [])
    resultado = conferir(nav, ALVO, nav.abrir, lambda: None, ao_adicionar=lambda: chamadas.append(1))
    assert resultado.situacao is SituacaoCheckout.CARRINHO_OCUPADO and chamadas == []


def test_contador_e_subtotal_ilegiveis_depois_de_adicionar_falha_e_tira_o_item():
    sem_quantidade = pagina_html(carrinho(ASIN).html.replace('<span id="nav-cart-count">1</span>', ""), url=URL_CARRINHO)
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), sem_quantidade, sem_quantidade, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [sem_quantidade, carrinho()],
    )
    assert resultado.situacao is SituacaoCheckout.FALHA and "quantidade" in resultado.motivo
    assert resultado.item_removido and clicados(nav)[-1] == EXCLUIR_ATIVO
    assert 'input[name="proceedToRetailCheckout"]' not in clicados(nav)


def test_itens_do_resumo_muito_acima_do_anunciado_falha():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [um_item, checkout_resumo(itens="R$ 551,82", total="R$ 600,08"), carrinho()],  # duas unidades
    )
    assert resultado.situacao is SituacaoCheckout.FALHA and "quantidade" in resultado.motivo
    assert resultado.total is None and resultado.item_removido and clicados(nav)[-1] == EXCLUIR_ATIVO


def test_login_ao_reabrir_o_carrinho_depois_de_adicionar_e_sem_login():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), login(), um_item, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [um_item, carrinho()],
    )
    assert (resultado.situacao, resultado.item_removido) == (SituacaoCheckout.SEM_LOGIN, True)
    assert clicados(nav)[-1] == EXCLUIR_ATIVO


def _fluxo_real(resumo_html):
    destaque = ESPERADO["painel_importada"]["destaque"]
    alvo = AlvoCheckout(ESPERADO["painel_importada"]["asin"], destaque["vendedor"], Decimal(destaque["preco"]))
    real = {nome: pagina_html(fixture_amazon(nome), url=URL_CARRINHO) for nome in ("carrinho_vazio", "carrinho_um_item")}
    passos = [real["carrinho_um_item"]]
    if "checkout_endereco" in ESPERADO:
        passos.append(pagina_html(fixture_amazon("checkout_endereco")))
    passos += [pagina_html(resumo_html), real["carrinho_vazio"]]
    nav = NavegadorInterativoFake(
        {
            URL_CARRINHO: [real["carrinho_vazio"], real["carrinho_um_item"], real["carrinho_um_item"], real["carrinho_vazio"]],
            url_painel_ofertas(alvo.asin): pagina_html(fixture_amazon("painel_importada"), url=url_painel_ofertas(alvo.asin)),
        },
        passos,
    )
    return conferir(nav, alvo, nav.abrir, lambda: None), nav


def test_resumo_que_nao_fecha_falha_e_tira_o_item():
    # Cópia do resumo real com o rótulo dos impostos trocado: a linha some da leitura e itens + frete
    # deixam de fechar com o total. Não pode virar conferência ok (o preço conferido sairia sem impostos).
    renomeado = fixture_amazon("checkout_resumo").replace("Taxas de importação incluindo ICMS", "Tributos estimados")
    resultado, nav = _fluxo_real(renomeado)
    assert resultado.situacao is SituacaoCheckout.FALHA
    assert resultado.motivo.startswith("resumo não fecha: itens 251.49 + frete 0.00 + impostos 0 ≠ total 302.54")
    assert resultado.preco_conferido is None and resultado.total is None
    assert resultado.item_removido and nenhum_proibido(nav)


def test_resumo_que_nao_fecha_com_as_paginas_falsas():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [um_item, checkout_resumo(total="R$ 290,00"), carrinho()],
    )
    assert (resultado.situacao, resultado.motivo) == (
        SituacaoCheckout.FALHA, "resumo não fecha: itens 237.73 + frete 0.00 + impostos 48.26 ≠ total 290.00",
    )
    assert resultado.item_removido and clicados(nav)[-1] == EXCLUIR_ATIVO


@pytest.mark.parametrize(
    ("contador", "situacao"), [(1, SituacaoCheckout.CARRINHO_OCUPADO), (None, SituacaoCheckout.FALHA)]
)
def test_carrinho_relido_no_painel_logo_antes_de_adicionar(contador, situacao):
    # O usuário pôs um item no carrinho depois da primeira leitura: o contador da página do painel
    # (a que está na tela no clique) precisa estar legível e em zero, senão nada é clicado.
    chamadas = []
    blocos = (
        bloco_oferta("R$ 314,11", "Amazon Global", seller_id=None, envia=None, destaque=True),
        bloco_oferta("R$ 275,91", "Shazaar", "A2SHZ", origem="Estados Unidos"),
    )
    nav = NavegadorInterativoFake({URL_CARRINHO: carrinho(), url_painel_ofertas(ASIN): painel(*blocos, carrinho=contador)}, [])
    resultado = conferir(nav, ALVO, nav.abrir, lambda: None, ao_adicionar=lambda: chamadas.append(1))
    assert resultado.situacao is situacao and "nada foi clicado" in resultado.motivo
    assert nav.cliques == [] and chamadas == [] and resultado.item_removido
    assert (nav.visitadas, resultado.paginas) == ([URL_CARRINHO, url_painel_ofertas(ASIN)], 2)


def test_clique_recusado_pela_guarda_nao_conta_pagina():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    armadilha = checkout_endereco(botao='<input data-testid="Address_selectShipToThisAddress" type="submit" value="Confirmar pedido">')
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [um_item, armadilha, carrinho()],
    )
    assert "proibido" in resultado.motivo
    # só as páginas carregadas: as abertas e os cliques feitos (o recusado não carregou nada)
    assert resultado.paginas == len(nav.visitadas) + len(nav.cliques) == 8


def test_carrinho_ocupado_com_contador_zero_conta_os_itens_ativos():
    resultado, _ = conferir_com({URL_CARRINHO: carrinho("B0OUTRO001", "B0OUTRO002", contador=0)}, [])
    assert resultado.situacao is SituacaoCheckout.CARRINHO_OCUPADO
    assert resultado.motivo == "2 item(ns) no carrinho; nada foi clicado"
