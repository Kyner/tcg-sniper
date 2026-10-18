import ast
import re
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


# Rótulos com sósias Unicode (cirílico, grego) de letras latinas: não passam na lista de permitidos
# nem escapam da lista proibida.
ROTULOS_SOSIAS = [
    (EXCLUIR, "Exclu\u0456r"),  # i cirílico
    (ADICIONAR, "Adicionar ao carrinh\u043e"),  # o cirílico
    (FECHAR_PEDIDO, "Fechar p\u0435dido"),  # e cirílico
    (ENTREGAR, "Entregar neste endere\u03bfo"),  # ómicron grego
    (ADICIONAR, "Adicionar ao carrinho C\u043emprar agora"),  # "Comprar agora" com o cirílico
    (EXCLUIR, "Excluir Fin\u0430lizar pedido"),  # a cirílico
]


@pytest.mark.parametrize(("acao", "rotulo"), ROTULOS_SOSIAS)
def test_rotulo_com_sosia_unicode_e_recusado(acao, rotulo):
    with pytest.raises(CliqueProibido):
        conferir_clique(acao, '<input type="submit">', rotulo)


@pytest.mark.parametrize(
    "html",
    [
        '<input name="submit.addToCart" value="Adicionar ao carrinho" data-x="pl\u0430ce-order">',  # a cirílico
        '<input name="submit.addToCart" value="Adicionar ao carrinho" title="Finaliz\u0430r pedido">',
        '<input name="submit.addToCart" value="Adicionar ao carrinho" title="Finalızar pedido">',  # i sem ponto
        '<input name="submit.addToCart" value="Adicionar ao carrinho" title="\uff23omprar agora">',  # C de largura cheia
    ],
)
def test_sosia_no_contexto_nao_escapa_da_lista_proibida(html):
    with pytest.raises(CliqueProibido, match="elemento proibido"):
        conferir_clique(ADICIONAR, html, "")


def test_rotulo_latino_com_acento_e_pontuacao_continua_aceito():
    conferir_clique(EXCLUIR, '<input type="submit">', "Excluir Magic: The Gathering Æther \u2014 Booster «50»\u2122")
    conferir_clique(ENTREGAR, '<input type="submit">', "ENTREGAR NESTE ENDEREÇO ")


def test_titulo_em_japones_depois_da_acao_e_aceito():
    # O grupo compra produtos japoneses: só a parte da ação ("Excluir") precisa ser latina.
    conferir_clique(EXCLUIR, '<input type="submit">', "Excluir \u904a\u622f\u738b \u30d6\u30fc\u30b9\u30bf\u30fc")
    conferir_clique(ADICIONAR, '<input type="submit">', "Adicionar ao carrinho \u30de\u30b8\u30c3\u30af")


def test_acao_com_sosia_e_recusada_mesmo_com_titulo_japones():
    with pytest.raises(CliqueProibido, match="não é o botão esperado"):
        conferir_clique(EXCLUIR, '<input type="submit">', "\u0415xcluir \u904a\u622f\u738b")  # E cirílico


def test_frase_proibida_com_sosias_no_titulo_e_recusada():
    with pytest.raises(CliqueProibido, match="elemento proibido"):
        conferir_clique(EXCLUIR, '<input type="submit">', "Excluir \u904a\u622f\u738b C\u043empr\u0430r \u0430gora")


@pytest.mark.parametrize(
    ("rotulo", "html"),
    [
        ("Fechar pedido Comprar a\u0261ora", '<input type="submit">'),  # \u0261 do IPA, fora de SOSIAS
        ("Fechar pedido C\u0585mprar agora", '<input type="submit">'),  # o armênio
        ("Fechar pedido \u1d04omprar agora", '<input type="submit">'),  # c versalete
        ("Fechar pedido", '<input type="submit" title="Comprar a\u0261ora">'),  # no contexto
    ],
)
def test_palavra_que_mistura_latino_com_outro_alfabeto_e_recusada(rotulo, html):
    with pytest.raises(CliqueProibido, match="mistura"):
        conferir_clique(FECHAR_PEDIDO, html, rotulo)


def test_titulo_japones_colado_em_sigla_latina_continua_aceito():
    conferir_clique(EXCLUIR, '<input type="submit">', "Excluir MTG\u904a\u622f\u738b \u3010MTG\u3011\u30de\u30b8\u30c3\u30af")


@pytest.mark.parametrize(
    ("acao", "rotulo"),
    [
        (EXCLUIR, "Remover item Excluir"),
        (ADICIONAR, "Ver carrinho Adicionar ao carrinho"),
        (FECHAR_PEDIDO, "Comprar Fechar pedido"),
    ],
)
def test_acao_tem_de_estar_no_comeco_do_rotulo(acao, rotulo):
    with pytest.raises(CliqueProibido, match="não é o botão esperado"):
        conferir_clique(acao, '<input type="submit">', rotulo)


@pytest.mark.parametrize("rotulo", ["Excluir\u202e", "Excluir \u2066titulo\u2069", "\u202aExcluir"])
def test_controle_bidi_no_rotulo_e_recusado(rotulo):
    with pytest.raises(CliqueProibido):
        conferir_clique(EXCLUIR, '<input type="submit">', rotulo)


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


def test_clique_de_excluir_conta_a_pagina_mesmo_quando_falha_depois_de_carregar():
    from tcg_sniper.navegador.modelos import ErroRede

    antes, depois = carrinho(["B0ALVO0001"]), carrinho()
    cliques_contados = []
    nav = NavegadorInterativoFake({URL_CARRINHO: [antes, depois]}, apos_clique=[depois])
    assert remover_do_carrinho(nav, "B0ALVO0001", nav.abrir, lambda: None, contar_clique=lambda: cliques_contados.append(1)) == (True, 3)
    assert cliques_contados == [1]
    nav = NavegadorInterativoFake({URL_CARRINHO: [antes]}, apos_clique=[ErroRede("timeout depois do clique")])
    with pytest.raises(ErroRede):
        remover_do_carrinho(nav, "B0ALVO0001", nav.abrir, lambda: None, contar_clique=lambda: cliques_contados.append(1))
    assert cliques_contados == [1, 1]  # o clique carregou a página antes do erro: conta


def test_excluir_recusado_pela_guarda_nao_conta_o_clique():
    cliques_contados = []
    armadilha = pagina(
        SAIR_DA_CONTA + '<span id="nav-cart-count">1</span><div data-name="Active Items"><div data-asin="B0ALVO0001">'
        '<input data-action="delete" value="Excluir" aria-label="Comprar agora" type="submit"></div></div>',
        url=URL_CARRINHO,
    )
    nav = NavegadorInterativoFake({URL_CARRINHO: [armadilha]})
    with pytest.raises(CliqueProibido):
        remover_do_carrinho(nav, "B0ALVO0001", nav.abrir, lambda: None, contar_clique=lambda: cliques_contados.append(1))
    assert cliques_contados == [] and nav.cliques == []


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
CLIQUES_DO_PLAYWRIGHT = {
    "click", "dblclick", "dispatch_event", "tap", "press", "press_sequentially", "check", "uncheck", "set_checked",
    "submit", "request_submit",
}
METODOS_QUE_CLICAM = CLIQUES_DO_PLAYWRIGHT | {"clicar", "requestSubmit"}
ACESSO_DINAMICO = {"getattr", "methodcaller", "attrgetter"}
AVALIA_JS = {
    "evaluate", "evaluate_handle", "evaluate_all", "eval_on_selector", "eval_on_selector_all", "wait_for_function",
    "add_init_script", "add_script_tag",
}
# Argumentos que apontam JS de fora (arquivo ou URL): nunca é texto conhecido.
JS_DE_FORA = {"path", "url"}
DIGITA = {"type", "fill", "press_sequentially", "insert_text"}  # com "\n"/"\r" no texto: Enter
JS_QUE_CLICA = re.compile(r"\b(click|submit|requestSubmit)\b|dispatchEvent")
SO_CLIQUES_PY = {"src/tcg_sniper/coletor_amazon/cliques.py"}
SO_NAVEGADORES = {"src/tcg_sniper/navegador/chromium.py", "src/tcg_sniper/coletor_liga/navegador.py"}


def _valores(no, constantes):
    """Valores possíveis do texto de `no`: literal, constante do módulo, soma de textos ("cl" + "ick") e
    f-string (as partes interpoladas viram "")."""
    if isinstance(no, ast.Constant) and isinstance(no.value, str):
        return [no.value]
    if isinstance(no, ast.Name) and no.id in constantes:
        return list(constantes[no.id])
    if isinstance(no, ast.BinOp) and isinstance(no.op, ast.Add):
        esquerda, direita = _valores(no.left, constantes), _valores(no.right, constantes)
        return [a + b for a in esquerda for b in direita][:50]
    if isinstance(no, ast.JoinedStr):
        partes = [v.value if isinstance(v, ast.Constant) else "" for v in no.values]
        return ["".join(str(p) for p in partes)]
    return []


def _strings(no, constantes):
    """Strings dentro de `no` (cada literal e cada soma/f-string inteira), com nomes resolvidos pelas
    constantes do módulo."""
    for filho in ast.walk(no):
        if isinstance(filho, ast.Constant) and isinstance(filho.value, str):
            yield filho.value
        elif isinstance(filho, ast.Name) and filho.id in constantes:
            yield from constantes[filho.id]
        elif isinstance(filho, (ast.BinOp, ast.JoinedStr)):
            yield from _valores(filho, constantes)


def _eh_mouse(dono):
    return (isinstance(dono, ast.Attribute) and dono.attr == "mouse") or (isinstance(dono, ast.Name) and dono.id == "mouse")


def _eh_teclado(dono):
    return (isinstance(dono, ast.Attribute) and dono.attr == "keyboard") or (
        isinstance(dono, ast.Name) and dono.id == "keyboard"
    )


def _resolvivel(no, constantes):
    """O JS é só texto conhecido: literais e constantes do módulo (nada importado, montado ou chamado).
    O que entra interpolado numa f-string é dado (tema, seletor), não código: não conta."""
    pendentes = [no]
    while pendentes:
        filho = pendentes.pop()
        if isinstance(filho, ast.FormattedValue):
            continue
        if isinstance(filho, (ast.Call, ast.Attribute, ast.Subscript)):
            return False
        if isinstance(filho, ast.Name) and filho.id not in constantes:
            return False
        pendentes.extend(ast.iter_child_nodes(filho))
    return True


def _expressao_js(no):
    """O argumento com o JS: o 1º (o 2º em `eval_on_selector*`) ou `expression=`/`script=`/`content=`.
    None quando não há JS no texto (só `path=`/`url=`, ou nada)."""
    for kw in no.keywords:
        if kw.arg in ("expression", "script", "content"):
            return kw.value
    posicao = 1 if no.func.attr.startswith("eval_on_selector") else 0
    return no.args[posicao] if len(no.args) > posicao else None


def chamadas_de_clique(raiz=RAIZ_REPO):
    """{arquivo: {tipos}} em src/ e scripts/:
    - "clicar": `.clicar(` (o clique com guarda do navegador);
    - "playwright": cliques e teclas do Playwright (`click`, `dispatch_event`, `tap`, `check`, `press`,
      `submit`, `mouse.*`, `keyboard.*` e afins; `type`/`fill` com "\\n" ou "\\r");
    - "js_clique": JS avaliado na página (`evaluate*`, `eval_on_selector[_all]`, `wait_for_function`,
      `add_init_script`, `add_script_tag`) com a palavra `click`, `submit`, `requestSubmit` ou
      `dispatchEvent` (somas de texto e constantes resolvidas);
    - "js_opaco": JS avaliado que não é texto conhecido no módulo (importado, montado por função,
      `path=`/`url=`); valores interpolados em f-string são dado, não código;
    - "cdp": `send("Input.dispatch...")` do protocolo do Chromium;
    - "dinamico": `getattr(x, "click")`, `methodcaller("click")` e afins com o nome de um método que clica."""
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
            if not isinstance(no, ast.Call):
                continue
            funcao = no.func.id if isinstance(no.func, ast.Name) else no.func.attr if isinstance(no.func, ast.Attribute) else ""
            argumentos = [*no.args, *(kw.value for kw in no.keywords)]
            if funcao in ACESSO_DINAMICO and any(
                t in METODOS_QUE_CLICAM for arg in argumentos for t in _strings(arg, constantes)
            ):
                achados.setdefault(nome, set()).add("dinamico")
            if not isinstance(no.func, ast.Attribute):
                continue
            if funcao == "clicar":
                achados.setdefault(nome, set()).add("clicar")
            textos = [t for arg in argumentos for t in _strings(arg, constantes)]
            if funcao in CLIQUES_DO_PLAYWRIGHT or _eh_mouse(no.func.value) or _eh_teclado(no.func.value):
                achados.setdefault(nome, set()).add("playwright")
            if funcao in DIGITA and any("\n" in t or "\r" in t for t in textos):
                achados.setdefault(nome, set()).add("playwright")  # digitar com Enter envia o form
            if funcao == "send" and any(t.startswith("Input.dispatch") for t in textos):
                achados.setdefault(nome, set()).add("cdp")  # clique/tecla pelo protocolo do Chromium
            if funcao in AVALIA_JS:
                expressao = _expressao_js(no)
                js = list(_strings(expressao, constantes)) if expressao is not None else []
                if any(JS_QUE_CLICA.search(t) for t in js):
                    achados.setdefault(nome, set()).add("js_clique")
                de_fora = any(kw.arg in JS_DE_FORA for kw in no.keywords)
                if de_fora or expressao is None or not _resolvivel(expressao, constantes):
                    achados.setdefault(nome, set()).add("js_opaco")
    return achados


def _com(achados, tipo):
    return {arquivo for arquivo, tipos in achados.items() if tipo in tipos}


def test_so_cliques_py_chama_clicar_do_navegador():
    achados = chamadas_de_clique()
    assert _com(achados, "clicar") == SO_CLIQUES_PY
    assert _com(achados, "playwright") <= SO_NAVEGADORES
    assert "src/tcg_sniper/navegador/chromium.py" in _com(achados, "playwright")  # a varredura enxerga o clique
    assert _com(achados, "js_clique") == set()
    assert _com(achados, "js_opaco") == set()
    assert _com(achados, "dinamico") == set()
    assert _com(achados, "cdp") == set()


@pytest.mark.parametrize(
    ("codigo", "tipo"),
    [
        ("pagina.eval_on_selector('#b', 'e => e.click()')\n", "js_clique"),
        ("pagina.eval_on_selector_all('form', 'fs => fs[0].submit()')\n", "js_clique"),
        ("pagina.locator('form').evaluate_all('fs => fs[0].requestSubmit()')\n", "js_clique"),
        ("JS = 'e => e . click ()'\nh = pagina.evaluate_handle(JS)\n", "js_clique"),
        ("pagina.evaluate(\"e => e.dispatchEvent(new MouseEvent('click'))\")\n", "js_clique"),
        ("pagina.evaluate(f\"document.querySelector('{s}').click()\")\n", "js_clique"),
        ("pagina.evaluate(\"e => e['click']()\")\n", "js_clique"),
        ("from x import JS\npagina.evaluate(JS)\n", "js_opaco"),
        ("pagina.evaluate(montar_js())\n", "js_opaco"),
        ("botao.dispatch_event('click')\n", "playwright"),
        ("botao.tap()\n", "playwright"),
        ("caixa.check()\n", "playwright"),
        ("caixa.set_checked(True)\n", "playwright"),
        ("botao.dblclick()\n", "playwright"),
        ("pagina.keyboard.press('Enter')\n", "playwright"),
        ("campo.press('Enter')\n", "playwright"),
        ("pagina.keyboard.down('Enter')\n", "playwright"),
        ("form.submit()\n", "playwright"),
        ("getattr(botao, 'click')()\n", "dinamico"),
        ("NOME = 'clicar'\ngetattr(nav, NOME)('#x', 0, g)\n", "dinamico"),
        ("operator.methodcaller('dispatch_event', 'click')(botao)\n", "dinamico"),
    ],
)
def test_varredura_acha_outras_formas_de_clicar(tmp_path, codigo, tipo):
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "a.py").write_text(codigo, encoding="utf-8")
    assert tipo in chamadas_de_clique(tmp_path).get("src/a.py", set())


@pytest.mark.parametrize(
    "codigo",
    [
        "pagina.evaluate('1')\n",
        "pagina.evaluate('document.documentElement.scrollWidth')\n",
        "JS = 'e => [e.outerHTML, e.innerText]'\nelemento.evaluate(JS)\n",
        "pagina.eval_on_selector('#preco', 'e => e.textContent')\n",
        "valor = getattr(cfg, campo)\n",
        "x = getattr(oferta, 'cupom', None)\n",
        "campo.fill('texto')\n",
    ],
)
def test_varredura_nao_acusa_leitura(tmp_path, codigo):
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "a.py").write_text(codigo, encoding="utf-8")
    assert chamadas_de_clique(tmp_path) == {}


@pytest.mark.parametrize(
    ("codigo", "tipo"),
    [
        ("JS = 'e => e.cl' + 'ick()'\npagina.evaluate(JS)\n", "js_clique"),
        ("getattr(botao, 'cli' + 'ck')()\n", "dinamico"),
        ("pagina.evaluate('e => { const m = \"click\"; e[m](); }')\n", "js_clique"),
        ("pagina.wait_for_function('() => (document.querySelector(\"#b\").click(), true)')\n", "js_clique"),
        ("contexto.add_init_script('addEventListener(\"load\", () => document.forms[0].submit())')\n", "js_clique"),
        ("pagina.add_script_tag(content='document.querySelector(\"#b\").click()')\n", "js_clique"),
        ("pagina.add_script_tag(url='https://exemplo.invalid/x.js')\n", "js_opaco"),
        ("contexto.add_init_script(path='x.js')\n", "js_opaco"),
        ("cdp.send('Input.dispatchMouseEvent', {'type': 'mousePressed'})\n", "cdp"),
        ("campo.fill('texto\\n')\n", "playwright"),
        ("campo.type('abc\\r')\n", "playwright"),
    ],
)
def test_varredura_acha_cliques_montados_e_outras_entradas(tmp_path, codigo, tipo):
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "a.py").write_text(codigo, encoding="utf-8")
    assert tipo in chamadas_de_clique(tmp_path).get("src/a.py", set())


@pytest.mark.parametrize(
    "codigo",
    [
        "contexto.add_init_script(f\"localStorage.setItem('tema', '{tema}')\")\n",
        "JS = '([s, n]) => document.querySelectorAll(s).length > n'\npagina.wait_for_function(JS, arg=[1, 2])\n",
        "pagina.eval_on_selector('input[type=submit]', 'e => e.value')\n",
        "cdp.send('Network.enable')\n",
        "campo.type('abc')\n",
    ],
)
def test_varredura_nao_acusa_leitura_nem_dado_interpolado(tmp_path, codigo):
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "a.py").write_text(codigo, encoding="utf-8")
    assert chamadas_de_clique(tmp_path) == {}


def test_varredura_acha_cliques_escondidos(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "a.py").write_text("nav.clicar('#x', 0, g)\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("pagina.mouse.wheel(1, 2)\nbotao.dispatch_event('click')\n", encoding="utf-8")
    (tmp_path / "scripts" / "c.py").write_text("JS = 'e => e.click()'\npagina.evaluate(JS)\n", encoding="utf-8")
    assert chamadas_de_clique(tmp_path) == {
        "src/a.py": {"clicar"},
        "src/b.py": {"playwright"},
        "scripts/c.py": {"js_clique"},
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
