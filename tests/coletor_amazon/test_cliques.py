import ast
from pathlib import Path

import pytest
from fakes import NavegadorInterativoFake, pagina_html
from fakes_checkout import SAIR_DA_CONTA

import tcg_sniper
from tcg_sniper.coletor_amazon.cliques import (
    ACOES,
    ADICIONAR,
    ENTREGAR,
    EXCLUIR,
    FECHAR_PEDIDO,
    CliqueProibido,
    SeletorAusente,
    asin_no_carrinho_ativo,
    clicar_permitido,
    conferir_clique,
    item_fora_do_carrinho_ativo,
    localizar,
    remover_do_carrinho,
)
from tcg_sniper.coletor_amazon.parsers import URL_CARRINHO

PERMITIDOS = {
    ADICIONAR: '<input name="submit.addToCart" value="Adicionar ao carrinho" type="submit">',
    FECHAR_PEDIDO: '<input name="proceedToRetailCheckout" value="Fechar pedido" type="submit">',
    ENTREGAR: '<input data-testid="Address_selectShipToThisAddress" type="submit" aria-label="Entregar neste endereço">',
    EXCLUIR: '<input data-action="delete" name="submit.delete.C1" value="Excluir" type="submit">',
}
PROIBIDOS_HTML = [
    '<input name="placeYourOrder1" value="Confirmar pedido com cartão 0000" type="submit">',
    '<input id="submitOrderButtonId" type="submit">',
    '<input id="buy-now-button" name="submit.buy-now" type="submit">',
    '<span class="a-button-text">Comprar agora</span>',
    "<button>Finalizar pedido</button>",
    '<input value="Fazer pedido" type="submit">',
    '<input name="submit.addToCart" value="Comprar com 1-Clique" type="submit">',
    '<a id="turbo-checkout-pyo-button">Pagar</a>',
]
# Proibidos disfarçados (separadores, traço Unicode, entidade), cada um com o rótulo de uma ação
# permitida: a lista proibida tem de pegar mesmo com o padrão da ação casando.
PROIBIDOS_DISFARCADOS = [
    (ADICIONAR, '<input name="submit.addToCart" value="Comprar com 1\u2011Clique" type="submit">'),
    (FECHAR_PEDIDO, '<input data-testid="place-order" value="Fechar pedido" type="submit">'),
    (FECHAR_PEDIDO, '<input id="place_order_btn" name="proceedToRetailCheckout" value="Fechar pedido" type="submit">'),
    (
        ENTREGAR,
        (
            '<input formaction="/checkout/spc/place-order" data-testid="Address_selectShipToThisAddress"'
            ' aria-label="Entregar neste endereço" type="submit">'
        ),
    ),
    (EXCLUIR, '<input name="submit.delete.C1" value="Concluir pedido" aria-label="Excluir" type="submit">'),
    (ADICIONAR, '<input name="submit.addToCart" value="Comprar&nbsp;agora" aria-label="Adicionar ao carrinho" type="submit">'),
]
PROIBIDOS_HTML += [html for _, html in PROIBIDOS_DISFARCADOS]


def pagina(corpo, url="https://www.amazon.com.br/x"):
    return pagina_html(f"<html><body>{corpo}</body></html>", url=url)


def item(asin):
    return f'<div data-asin="{asin}"><input data-action="delete" name="submit.delete.{asin}" value="Excluir" type="submit"></div>'


def carrinho(ativos=(), salvos=(), logado=True):
    return pagina(
        (SAIR_DA_CONTA if logado else "") + f'<span id="nav-cart-count">{len(ativos)}</span>'
        f'<div data-name="Active Items">{"".join(map(item, ativos))}</div>'
        f'<div data-name="Saved Items">{"".join(map(item, salvos))}</div>',
        url=URL_CARRINHO,
    )


@pytest.mark.parametrize("acao", ACOES, ids=lambda a: a.nome)
@pytest.mark.parametrize("html", PROIBIDOS_HTML)
def test_elemento_proibido_e_recusado_em_qualquer_acao(acao, html):
    with pytest.raises(CliqueProibido):
        conferir_clique(acao, html, "")


@pytest.mark.parametrize("acao", ACOES, ids=lambda a: a.nome)
def test_botao_de_cada_acao_e_aceito(acao):
    conferir_clique(acao, PERMITIDOS[acao], "")


@pytest.mark.parametrize(("acao", "html"), PROIBIDOS_DISFARCADOS)
def test_proibido_disfarcado_e_recusado_pela_lista_proibida(acao, html):
    with pytest.raises(CliqueProibido, match="elemento proibido"):
        conferir_clique(acao, html, "")


def test_token_do_seletor_sem_rotulo_nao_basta():
    with pytest.raises(CliqueProibido, match="não é o botão esperado"):
        conferir_clique(ENTREGAR, '<input data-testid="Address_selectShipToThisAddress" type="submit">', "")
    with pytest.raises(CliqueProibido, match="não é o botão esperado"):
        conferir_clique(ADICIONAR, '<input name="submit.addToCart" type="submit">', "")


def a_button(input_attrs, rotulo, id_rotulo="X-announce", extra=""):
    """Botão no formato real da Amazon: o texto fica num span irmão do input, citado por aria-labelledby."""
    return (
        '<span class="a-button a-button-primary"><span class="a-button-inner">'
        f'<input class="a-button-input" type="submit" aria-labelledby="{id_rotulo}" {input_attrs}>'
        f'<span id="{id_rotulo}" class="a-button-text" aria-hidden="true">{rotulo}</span>{extra}'
        "</span></span>"
    )


def test_a_button_com_confirmar_pedido_no_span_irmao_e_recusado():
    p = pagina(a_button('data-testid="Address_selectShipToThisAddress"', "Confirmar pedido"))
    nav = NavegadorInterativoFake({p.url: p}, apos_clique=[pagina("<p>pedido feito</p>")])
    nav.abrir(p.url)
    with pytest.raises(CliqueProibido):
        clicar_permitido(nav, ENTREGAR, p)
    assert nav.cliques == []


def test_a_button_com_rotulo_certo_no_span_irmao_e_clicado():
    p = pagina(a_button('data-testid="Address_selectShipToThisAddress"', "Entregar neste endereço"))
    nav = NavegadorInterativoFake({p.url: p}, apos_clique=[pagina("<p>pagamento</p>")])
    nav.abrir(p.url)
    clicar_permitido(nav, ENTREGAR, p)
    assert nav.cliques == [('input[data-testid="Address_selectShipToThisAddress"]', 0)]


@pytest.mark.parametrize(
    "corpo",
    [
        # texto proibido no botão em volta, fora do rótulo do input
        a_button(
            'name="submit.addToCart" aria-label="Adicionar ao carrinho"', "Adicionar ao carrinho", extra="<b>Comprar agora</b>"
        ),
        # title e aria-describedby
        '<input name="submit.addToCart" value="Adicionar ao carrinho" title="Finalizar pedido">',
        '<input name="submit.addToCart" value="Adicionar ao carrinho" aria-describedby="d"><p id="d">Fazer pedido</p>',
        # ação do form
        '<form action="/checkout/spc/placeOrder"><input name="submit.addToCart" value="Adicionar ao carrinho"></form>',
    ],
)
def test_contexto_do_elemento_com_proibido_impede_o_clique(corpo):
    p = pagina(corpo)
    nav = NavegadorInterativoFake({p.url: p}, apos_clique=[pagina("<p>x</p>")])
    nav.abrir(p.url)
    with pytest.raises(CliqueProibido, match="elemento proibido"):
        clicar_permitido(nav, ADICIONAR, p)
    assert nav.cliques == []


def test_botao_de_outra_acao_e_recusado():
    with pytest.raises(CliqueProibido, match="não é o botão esperado"):
        conferir_clique(FECHAR_PEDIDO, PERMITIDOS[EXCLUIR], "Excluir")


def test_texto_em_maiusculas_e_com_acento_tambem_casa():
    with pytest.raises(CliqueProibido):
        conferir_clique(ENTREGAR, '<input data-testid="Address_selectShipToThisAddress">', "CONFIRMAR PEDIDO")
    conferir_clique(ENTREGAR, '<span id="shipToThisAddressButton"><input></span>', "ENTREGAR NESTE ENDEREÇO")


def test_clicar_permitido_usa_o_primeiro_seletor_que_acha():
    p = pagina('<div id="sc-buy-box-ptc-button"><input value="Fechar pedido" type="submit"></div>')
    seguinte = pagina("<p>checkout</p>", url="https://www.amazon.com.br/checkout")
    nav = NavegadorInterativoFake({p.url: p}, apos_clique=[seguinte])
    nav.abrir(p.url)
    assert clicar_permitido(nav, FECHAR_PEDIDO, p) is seguinte
    assert nav.cliques == [("#sc-buy-box-ptc-button input", 0)]


def test_botao_proibido_no_lugar_do_esperado_nao_e_clicado():
    p = pagina('<input name="proceedToRetailCheckout" value="Confirmar pedido" type="submit">')
    nav = NavegadorInterativoFake({p.url: p}, apos_clique=[pagina("<p>pedido feito</p>")])
    nav.abrir(p.url)
    with pytest.raises(CliqueProibido):
        clicar_permitido(nav, FECHAR_PEDIDO, p)
    assert nav.cliques == []


def test_a_guarda_do_navegador_confere_o_elemento_da_tela():
    lida = pagina(PERMITIDOS[FECHAR_PEDIDO])
    na_tela = pagina('<input name="proceedToRetailCheckout" value="Confirmar pedido" type="submit">', url=lida.url + "?2")
    nav = NavegadorInterativoFake({na_tela.url: na_tela}, apos_clique=[pagina("<p>x</p>")])
    nav.abrir(na_tela.url)  # a tela mudou depois que `lida` foi capturada
    with pytest.raises(CliqueProibido):
        clicar_permitido(nav, FECHAR_PEDIDO, lida)
    assert nav.cliques == []


def test_sem_botao_levanta_seletor_ausente_sem_clicar():
    p = pagina("<p>passo inesperado</p>")
    nav = NavegadorInterativoFake({p.url: p})
    nav.abrir(p.url)
    with pytest.raises(SeletorAusente, match="fechar pedido"):
        clicar_permitido(nav, FECHAR_PEDIDO, p)
    assert nav.cliques == []


def test_oferta_da_lista_acha_o_botao_do_bloco_certo():
    p = pagina(
        '<div id="aod-pinned-offer"><input name="submit.addToCart" value="Adicionar ao carrinho"></div>'
        '<div id="aod-offer"><span>sem botão</span></div>'
        '<div id="aod-offer"><input name="submit.addToCart" value="Adicionar ao carrinho"></div>'
    )
    assert localizar(ADICIONAR, p, "#aod-offer", 1) == ('#aod-offer input[name="submit.addToCart"]', 0)
    assert localizar(ADICIONAR, p, "#aod-offer", 0) is None
    assert localizar(ADICIONAR, p, "#aod-offer", 5) is None
    assert localizar(ADICIONAR, p, "#aod-pinned-offer") == ('#aod-pinned-offer input[name="submit.addToCart"]', 0)


def test_remover_tira_so_do_carrinho_ativo():
    antes, depois = carrinho(["B0ALVO0001"], ["B0ALVO0001"]), carrinho([], ["B0ALVO0001"])
    nav = NavegadorInterativoFake({URL_CARRINHO: [antes, depois]}, apos_clique=[depois])
    assert remover_do_carrinho(nav, "B0ALVO0001", nav.abrir, lambda: None) == (True, 3)
    assert nav.cliques == [('[data-name="Active Items"] [data-asin="B0ALVO0001"] input[data-action="delete"]', 0)]


def test_item_so_em_salvo_para_depois_nunca_e_tocado():
    nav = NavegadorInterativoFake({URL_CARRINHO: carrinho([], ["B0ALVO0001"])})
    assert remover_do_carrinho(nav, "B0ALVO0001", nav.abrir, lambda: None) == (True, 1)
    assert nav.cliques == []


def test_remover_sem_botao_de_excluir_devolve_falso():
    sem_botao = pagina(
        '<span id="nav-cart-count">1</span><div data-name="Active Items"><div data-asin="B0ALVO0001">item</div></div>',
        url=URL_CARRINHO,
    )
    nav = NavegadorInterativoFake({URL_CARRINHO: sem_botao})
    assert remover_do_carrinho(nav, "B0ALVO0001", nav.abrir, lambda: None) == (False, 1)
    assert asin_no_carrinho_ativo(sem_botao, "B0ALVO0001")


CAPTCHA = pagina('<form action="/errors/validatecaptcha">Digite os caracteres que você vê</form>', url=URL_CARRINHO)
LOGIN = pagina('<form name="signIn"><input type="email" name="email"></form>', url="https://www.amazon.com.br/ap/signin")


def test_remover_com_captcha_no_lugar_do_carrinho_devolve_falso():
    nav = NavegadorInterativoFake({URL_CARRINHO: CAPTCHA})
    assert remover_do_carrinho(nav, "B0ALVO0001", nav.abrir, lambda: None) == (False, 1)
    assert nav.cliques == []


def test_remover_que_cai_no_login_devolve_falso():
    nav = NavegadorInterativoFake({URL_CARRINHO: [carrinho(["B0ALVO0001"]), LOGIN]}, apos_clique=[LOGIN])
    assert remover_do_carrinho(nav, "B0ALVO0001", nav.abrir, lambda: None) == (False, 3)


RAIZ_REPO = Path(tcg_sniper.__file__).parents[2]
CLIQUES_DO_PLAYWRIGHT = {"click", "dispatch_event", "tap", "press"}
SO_CLIQUES_PY = {"src/tcg_sniper/coletor_amazon/cliques.py"}
SO_NAVEGADORES = {"src/tcg_sniper/navegador/chromium.py", "src/tcg_sniper/coletor_liga/navegador.py"}


def _strings(no, constantes):
    """Strings literais dentro de `no`, com nomes resolvidos pelas constantes do módulo."""
    for filho in ast.walk(no):
        if isinstance(filho, ast.Constant) and isinstance(filho.value, str):
            yield filho.value
        elif isinstance(filho, ast.Name) and filho.id in constantes:
            yield from constantes[filho.id]


def _eh_mouse(dono):
    return (isinstance(dono, ast.Attribute) and dono.attr == "mouse") or (isinstance(dono, ast.Name) and dono.id == "mouse")


def chamadas_de_clique(raiz=RAIZ_REPO):
    """{arquivo: {tipos}} com `.clicar(`, cliques do Playwright (`click`, `dispatch_event`, `tap`,
    `press`, `mouse.*`) e `evaluate` com `.click(` no JS, em src/ e scripts/."""
    achados: dict[str, set[str]] = {}
    for caminho in [*(raiz / "src").rglob("*.py"), *(raiz / "scripts").rglob("*.py")]:
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
        constantes = {
            alvo.id: list(_strings(no.value, {}))
            for no in arvore.body
            if isinstance(no, ast.Assign)
            for alvo in no.targets
            if isinstance(alvo, ast.Name)
        }
        nome = caminho.relative_to(raiz).as_posix()
        for no in ast.walk(arvore):
            if not (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)):
                continue
            metodo = no.func.attr
            if metodo == "clicar":
                achados.setdefault(nome, set()).add("clicar")
            if metodo in CLIQUES_DO_PLAYWRIGHT or _eh_mouse(no.func.value):
                achados.setdefault(nome, set()).add("playwright")
            if metodo == "evaluate" and any(".click(" in t for arg in no.args for t in _strings(arg, constantes)):
                achados.setdefault(nome, set()).add("evaluate_click")
    return achados


def _com(achados, tipo):
    return {arquivo for arquivo, tipos in achados.items() if tipo in tipos}


def test_so_cliques_py_chama_clicar_do_navegador():
    achados = chamadas_de_clique()
    assert _com(achados, "clicar") == SO_CLIQUES_PY
    assert _com(achados, "playwright") <= SO_NAVEGADORES
    assert "src/tcg_sniper/navegador/chromium.py" in _com(achados, "playwright")  # a varredura enxerga o clique
    assert _com(achados, "evaluate_click") == set()


def test_varredura_acha_cliques_escondidos(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "a.py").write_text("nav.clicar('#x', 0, g)\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("pagina.mouse.wheel(1, 2)\nbotao.dispatch_event('click')\n", encoding="utf-8")
    (tmp_path / "scripts" / "c.py").write_text("JS = 'e => e.click()'\npagina.evaluate(JS)\n", encoding="utf-8")
    assert chamadas_de_clique(tmp_path) == {
        "src/a.py": {"clicar"},
        "src/b.py": {"playwright"},
        "scripts/c.py": {"evaluate_click"},
    }


# Botão real do passo de endereço (checkout de 2026-10-17): um "continuar" genérico cujo rótulo
# "Entregar neste endereço" fica só no span irmão `-announce`.
ENTREGAR_REAL = (
    '<span id="checkout-primary-continue-button-id" class="a-button a-button-primary continue-button">'
    '<span class="a-button-inner"><input data-testid="bottom-continue-button" class="a-button-input" type="submit"'
    ' aria-labelledby="checkout-primary-continue-button-id-announce">'
    '<span id="checkout-primary-continue-button-id-announce" class="a-button-text">{rotulo}</span></span></span>'
)


def test_botao_real_de_entregar_e_achado_e_clicado():
    p = pagina(ENTREGAR_REAL.format(rotulo="Entregar neste endereço"))
    nav = NavegadorInterativoFake({p.url: p}, apos_clique=[pagina("<p>resumo</p>")])
    nav.abrir(p.url)
    clicar_permitido(nav, ENTREGAR, p)
    assert nav.cliques == [('#checkout-primary-continue-button-id input[data-testid="bottom-continue-button"]', 0)]


def test_mesmo_botao_real_com_confirmar_pedido_e_recusado():
    p = pagina(ENTREGAR_REAL.format(rotulo="Confirmar pedido com cartão 0000"))
    nav = NavegadorInterativoFake({p.url: p}, apos_clique=[pagina("<p>pedido feito</p>")])
    nav.abrir(p.url)
    with pytest.raises(CliqueProibido):
        clicar_permitido(nav, ENTREGAR, p)
    assert nav.cliques == []


def test_carrinho_de_visitante_nao_prova_que_o_item_saiu():
    # Sessão caída: a Amazon mostra o carrinho (vazio) de visitante, sem pedir login. Não resolve nada.
    visitante = carrinho(logado=False)
    assert not item_fora_do_carrinho_ativo(visitante, "B0ALVO0001")
    assert item_fora_do_carrinho_ativo(carrinho(), "B0ALVO0001")
    nav = NavegadorInterativoFake({URL_CARRINHO: [carrinho(["B0ALVO0001"]), visitante]}, apos_clique=[visitante])
    assert remover_do_carrinho(nav, "B0ALVO0001", nav.abrir, lambda: None) == (False, 3)
    nav = NavegadorInterativoFake({URL_CARRINHO: visitante})
    assert remover_do_carrinho(nav, "B0ALVO0001", nav.abrir, lambda: None) == (False, 1)
