"""Os únicos cliques que o coletor faz no site da Amazon (conferência de checkout e captura de
fixtures). Cada ação tem uma lista fixa de seletores e um padrão que o elemento tem de ter; a lista
proibida (confirmar/finalizar pedido, Comprar agora, 1-Clique) é conferida antes de todo clique, no
HTML lido e de novo no elemento que o navegador vai clicar. Nenhum outro módulo chama
`NavegadorInterativo.clicar` (teste em tests/coletor_amazon/test_cliques.py).

A guarda recebe duas partes do elemento (`descrever_elemento` aqui, `JS_DESCREVER` no Chromium):
- o contexto: HTML do elemento, HTML e texto do botão/link/form em volta, `title`, textos de
  `aria-describedby`, `formaction` e a ação do form. Só a lista proibida olha o contexto;
- o rótulo: texto visível, `value`, `aria-label` e textos de `aria-labelledby`. A lista proibida
  também olha o rótulo, e o padrão da ação tem de casar NELE (não basta um atributo do seletor).

Os seletores são conferidos nas páginas reais salvas (tests/fixtures/amazon, Task 9 do plano
2026-10-17); o primeiro de cada lista é o visto na fixture, os demais cobrem variações de layout.
"""

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from html import unescape

from selectolax.lexbor import LexborHTMLParser, LexborNode

from tcg_sniper.coletor_amazon.parsers import URL_CARRINHO
from tcg_sniper.navegador.base import NavegadorInterativo
from tcg_sniper.navegador.modelos import Pagina

# Trechos (sem acento, minúsculos) que tornam um elemento proibido, no HTML dele ou no texto.
PROIBIDOS = (
    "placeorder",
    "placeyourorder",
    "submitorder",
    "place your order",
    "confirmar pedido",
    "confirmar o pedido",
    "finalizar pedido",
    "finalizar compra",
    "fazer pedido",
    "fazer o pedido",
    "comprar agora",
    "buy-now",
    "buynow",
    "buy now",
    "turbo-checkout",
    "1-clique",
    "1-click",
    "oneclick",
    "one-click",
)
# Os mesmos trechos sem nenhum separador, conferidos no alvo só com [a-z0-9]: "place_order",
# "place-order", "Comprar<espaço de largura zero>agora" e afins.
PROIBIDOS_COMPACTOS = (
    "placeorder",
    "placeyourorder",
    "submitorder",
    "buynow",
    "turbocheckout",
    "1click",
    "1clique",
    "oneclick",
    "compraragora",
    "confirmarpedido",
    "finalizarpedido",
    "finalizarcompra",
    "fazerpedido",
    "concluirpedido",
    "concluircompra",
)
# Hífens e traços Unicode (U+2010 a U+2015, U+2212) viram "-" antes de tudo: o NFKD + ASCII apagaria.
TRACOS = dict.fromkeys([*range(0x2010, 0x2016), 0x2212], "-")
# Sósias (já em minúsculas, depois do casefold) que o NFKD + ASCII apagaria: letras cirílicas e gregas
# parecidas com as latinas e letras latinas sem decomposição. Viram a letra ASCII parecida, para a lista
# proibida achar "Cоmprar agora" (о cirílico) ou "Finalızar pedido" (ı sem ponto).
SOSIAS = str.maketrans(
    {
        # cirílico
        "а": "a", "в": "b", "е": "e", "ё": "e", "з": "3", "і": "i", "ї": "i", "ј": "j", "к": "k", "м": "m",
        "н": "h", "о": "o", "р": "p", "с": "c", "т": "t", "у": "y", "х": "x", "ѕ": "s", "ԁ": "d", "ԛ": "q",
        "ԝ": "w", "һ": "h", "ӏ": "l", "ү": "y",
        # grego
        "α": "a", "β": "b", "ε": "e", "η": "n", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t",
        "υ": "u", "χ": "x", "ω": "w",
        # latinas sem decomposição (Latin-1 e Latin Extended-A)
        "æ": "ae", "œ": "oe", "ø": "o", "đ": "d", "ð": "d", "ħ": "h", "ı": "i", "ĸ": "k", "ł": "l", "ŀ": "l",
        "ŋ": "n", "ŧ": "t", "þ": "th",
    }
)
# O botão/link/form em volta do elemento (a Amazon põe o texto do botão num span irmão do input).
SELETOR_EM_VOLTA = ".a-button, button, a, [role=button], form"
LIMITE_CONTEXTO = 4_000


class CliqueProibido(Exception):
    """O elemento a clicar é (ou parece) um botão de confirmar pedido ou de compra imediata, ou não
    é o botão da ação."""


class SeletorAusente(Exception):
    """Nenhum seletor da ação achou o botão na página (layout novo ou passo inesperado)."""


@dataclass(frozen=True)
class Acao:
    nome: str
    seletores: tuple[str, ...]
    padrao: re.Pattern[str]  # o rótulo do elemento (sem acento, minúsculo) tem de casar


ADICIONAR = Acao(
    "adicionar ao carrinho",
    ('input[name="submit.addToCart"]', '[data-action="aod-atc-action"] input', '.aod-atc-column input[type="submit"]'),
    re.compile(r"adicionar ao carrinho|add to cart"),
)
FECHAR_PEDIDO = Acao(
    "fechar pedido",
    (
        'input[name="proceedToRetailCheckout"]',
        "#sc-buy-box-ptc-button input",
        '[data-feature-id="proceed-to-checkout-action"] input',
    ),
    re.compile(r"fechar pedido|proceed to checkout"),
)
ENTREGAR = Acao(
    "entregar neste endereço",
    (
        # checkout real de 2026-10-17: botão "continuar" genérico; o rótulo fica no span -announce
        '#checkout-primary-continue-button-id input[data-testid="bottom-continue-button"]',
        'input[data-testid="Address_selectShipToThisAddress"]',
        "#shipToThisAddressButton input",
        'input[aria-labelledby="shipToThisAddressButton-announce"]',
    ),
    re.compile(r"entregar neste endereco|ship to this address"),
)
EXCLUIR = Acao(
    "excluir do carrinho",
    (
        'input[data-action="delete"]',
        'input[name^="submit.delete"]',
        '[data-feature-id="delete"] input',
        'input[value="Excluir"]',
    ),
    re.compile(r"excluir"),
)
ACOES = (ADICIONAR, FECHAR_PEDIDO, ENTREGAR, EXCLUIR)

# Onde ficam os itens do carrinho ativo; "Salvo para depois" fica fora destes blocos e nunca é tocado.
ESCOPOS_CARRINHO_ATIVO = ('[data-name="Active Items"]', "#sc-active-cart", "#activeCartViewForm")
# Formulário de login (página /ap/signin ou embutida) e o link "Sair da conta" da barra, que só existe
# com a conta logada: um carrinho de visitante (sessão caída) não prova nada sobre o carrinho da conta.
SELETORES_LOGIN = ('form[name="signIn"]', "#ap_email_login", "#ap_email", "#ap_password")
SELETOR_CONTA_LOGADA = "#nav-item-signout"
# Painel de ofertas: a oferta em destaque (posição 0) e as demais, na ordem (posição 1 = 1º bloco).
ESCOPO_OFERTA_DESTAQUE = "#aod-pinned-offer"
ESCOPO_OFERTA_LISTA = "#aod-offer"


def _dobrar(texto: str) -> str:
    """Entidades resolvidas, traços unificados, NFKC (largura cheia, ligaduras) e casefold."""
    texto = unescape(texto.translate(TRACOS)).translate(TRACOS)  # entidades (&nbsp;, &#8209;) não escondem texto
    return unicodedata.normalize("NFKC", texto).casefold()


def _normalizar(texto: str) -> str:
    """Texto comparável com as listas: sósias cirílicos/gregos e letras latinas sem decomposição viram
    as ASCII parecidas antes de tirar os acentos (senão o encode ASCII apagaria a letra e "Finalızar",
    ou "Cоmprar" com o "о" cirílico, escapariam da lista proibida)."""
    sem_acento = unicodedata.normalize("NFKD", _dobrar(texto).translate(SOSIAS)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sem_acento)


def _caractere_de_rotulo(c: str) -> bool:
    ponto = ord(c)
    return ponto < 0x180 or 0x2000 <= ponto <= 0x206F or c.isspace()


def rotulo_latino(texto: str) -> bool:
    """O rótulo só tem ASCII, Latin-1, Latin Extended-A, espaços e a pontuação comum (U+2000 a U+206F),
    depois de NFKC + casefold. Uma letra de outro alfabeto (o "о" cirílico de "Cоmprar") é um sósia
    possível: o rótulo não vale nem para a lista de permitidos."""
    return all(_caractere_de_rotulo(c) for c in _dobrar(texto))


def _raiz(no: LexborNode) -> LexborNode:
    while no.parent is not None:
        no = no.parent
    return no


def _textos_dos_ids(no: LexborNode, atributo: str) -> str:
    """Textos dos elementos citados (por id) em `aria-labelledby`/`aria-describedby`."""
    raiz = _raiz(no)
    textos = []
    for id_ in (no.attributes.get(atributo) or "").split():
        alvo = raiz.css_first(f'[id="{id_}"]')
        if alvo is not None:
            textos.append(alvo.text(separator=" ", strip=True))
    return " ".join(textos)


def _em_volta(no: LexborNode, seletor: str) -> LexborNode | None:
    """Como `Element.closest` do DOM: o próprio elemento ou o ancestral mais próximo que casa."""
    atual = no
    while atual is not None and atual.tag != "-document":
        if atual.css_matches(seletor):
            return atual
        atual = atual.parent
    return None


def texto_do_elemento(no: LexborNode) -> str:
    """O rótulo do elemento: texto visível, `value`, `aria-label` e textos de `aria-labelledby`."""
    partes = (
        no.text(separator=" ", strip=True),
        no.attributes.get("value"),
        no.attributes.get("aria-label"),
        _textos_dos_ids(no, "aria-labelledby"),
    )
    return " ".join(p for p in partes if p)


def descrever_elemento(no: LexborNode) -> tuple[str, str]:
    """(contexto, rótulo) do elemento, como `JS_DESCREVER` do Chromium devolve na tela."""
    em_volta = _em_volta(no, SELETOR_EM_VOLTA)
    form = _em_volta(no, "form")
    contexto = (
        no.html or "",
        (em_volta.html or "")[:LIMITE_CONTEXTO] if em_volta is not None else "",
        em_volta.text(separator=" ", strip=True)[:LIMITE_CONTEXTO] if em_volta is not None else "",
        no.attributes.get("title") or "",
        _textos_dos_ids(no, "aria-describedby"),
        no.attributes.get("formaction") or "",
        (form.attributes.get("action") or "") if form is not None else "",
    )
    return "\n".join(contexto), texto_do_elemento(no)


def _rotulo_do_html(html_elemento: str) -> str:
    """`value` e `aria-label` do primeiro elemento do HTML (o próprio elemento): rótulo de quem só
    passou o HTML."""
    corpo = LexborHTMLParser(html_elemento).body
    no = next(corpo.iter(), None) if corpo is not None else None
    if no is None:
        return ""
    return " ".join(p for p in (no.attributes.get("value"), no.attributes.get("aria-label")) if p)


def conferir_clique(acao: Acao, html_elemento: str, texto: str) -> None:
    """Levanta CliqueProibido se o elemento (contexto ou rótulo) tem um trecho proibido, ou se o
    rótulo não é o do botão da ação. `html_elemento` é o contexto (começa pelo HTML do elemento);
    `texto` é o rótulo."""
    alvo = _normalizar(f"{html_elemento} {texto}")
    compacto = re.sub(r"[^a-z0-9]", "", alvo)
    for trecho in PROIBIDOS:
        if trecho in alvo:
            raise CliqueProibido(f"{acao.nome}: elemento proibido ({trecho!r}): {html_elemento[:200]}")
    for trecho in PROIBIDOS_COMPACTOS:
        if trecho in compacto:
            raise CliqueProibido(f"{acao.nome}: elemento proibido ({trecho!r}): {html_elemento[:200]}")
    rotulo_bruto = f"{texto} {_rotulo_do_html(html_elemento)}"
    if not rotulo_latino(rotulo_bruto):
        raise CliqueProibido(f"{acao.nome}: rótulo com letra fora do alfabeto latino (sósia?): {rotulo_bruto[:200]!r}")
    rotulo = _normalizar(rotulo_bruto)
    if not acao.padrao.search(rotulo):
        raise CliqueProibido(f"{acao.nome}: o elemento não é o botão esperado: {html_elemento[:200]}")


def localizar(acao: Acao, pagina: Pagina, escopo: str = "", bloco: int = 0) -> tuple[str, int] | None:
    """O primeiro seletor da ação que acha o botão dentro do `bloco`-ésimo elemento de `escopo` (sem
    escopo: o primeiro botão da página). Devolve o seletor completo e o índice do botão entre todos
    os elementos desse seletor na página (o índice que o navegador usa)."""
    arvore = LexborHTMLParser(pagina.html)
    raiz = None
    if escopo:
        blocos = arvore.css(escopo)
        if len(blocos) <= bloco:
            return None
        raiz = blocos[bloco]
    for seletor in acao.seletores:
        completo = f"{escopo} {seletor}".strip()
        todos = arvore.css(completo)
        if raiz is None:
            if todos:
                return completo, 0
            continue
        dentro = {no.mem_id for no in raiz.css(seletor)}
        for indice, no in enumerate(todos):
            if no.mem_id in dentro:
                return completo, indice
    return None


def clicar_permitido(
    nav: NavegadorInterativo, acao: Acao, pagina: Pagina, escopo: str = "", bloco: int = 0
) -> Pagina:
    """Confere o botão no HTML de `pagina` e clica nele pelo navegador, que confere de novo no próprio
    elemento antes do clique. Lança SeletorAusente ou CliqueProibido sem clicar."""
    achado = localizar(acao, pagina, escopo, bloco)
    if achado is None:
        raise SeletorAusente(f"{acao.nome}: botão não encontrado em {pagina.url}")
    seletor, indice = achado
    no = LexborHTMLParser(pagina.html).css(seletor)[indice]
    conferir_clique(acao, *descrever_elemento(no))
    return nav.clicar(seletor, indice, lambda html, texto: conferir_clique(acao, html, texto))


def _escopo_do_item(ativo: str, asin: str) -> str:
    return f'{ativo} [data-asin="{asin}"]'


def asin_no_carrinho_ativo(pagina: Pagina, asin: str) -> bool:
    arvore = LexborHTMLParser(pagina.html)
    return any(arvore.css_first(_escopo_do_item(ativo, asin)) is not None for ativo in ESCOPOS_CARRINHO_ATIVO)


def conta_logada(pagina: Pagina) -> bool:
    """A página é da conta logada: tem o "Sair da conta" da barra e nenhum formulário de login."""
    if "/ap/signin" in pagina.url:
        return False
    arvore = LexborHTMLParser(pagina.html)
    if any(arvore.css_first(seletor) is not None for seletor in SELETORES_LOGIN):
        return False
    return arvore.css_first(SELETOR_CONTA_LOGADA) is not None


def item_fora_do_carrinho_ativo(pagina: Pagina, asin: str) -> bool:
    """True só se a página é o carrinho ativo da conta logada (algum bloco dele existe e há o "Sair da
    conta") e o ASIN não está nele. Desafio (CAPTCHA), login, carrinho de visitante ou página de erro
    não provam nada: False."""
    if not conta_logada(pagina):
        return False
    arvore = LexborHTMLParser(pagina.html)
    if not any(arvore.css_first(ativo) is not None for ativo in ESCOPOS_CARRINHO_ATIVO):
        return False
    return not asin_no_carrinho_ativo(pagina, asin)


def clicar_contando(
    nav: NavegadorInterativo,
    acao: Acao,
    pagina: Pagina,
    contar: Callable[[], None],
    escopo: str = "",
    bloco: int = 0,
) -> Pagina:
    """`clicar_permitido` que chama `contar` para a página que o clique carrega, para o teto de páginas
    por hora. Recusa da guarda antes do clique (SeletorAusente, CliqueProibido) não conta: nada
    carregou. Qualquer outro desfecho (sucesso ou erro depois do clique) conta."""
    try:
        resultado = clicar_permitido(nav, acao, pagina, escopo, bloco)
    except (CliqueProibido, SeletorAusente):
        raise
    except BaseException:
        contar()  # o clique pode ter carregado uma página antes do erro
        raise
    contar()
    return resultado


def remover_do_carrinho(
    nav: NavegadorInterativo,
    asin: str,
    abrir: Callable[[str], Pagina],
    pausar: Callable[[], None],
    carrinho: Pagina | None = None,
    contar_clique: Callable[[], None] | None = None,
) -> tuple[bool, int]:
    """Exclui o ASIN do carrinho ativo (nunca de "Salvo para depois"). Devolve (removido, páginas
    abertas); removido é True só com o carrinho ativo na tela e sem o item (também quando ele já
    não estava lá); num desafio, login ou erro no lugar do carrinho, False.

    As páginas abertas por `abrir` são de quem chama (que conta no próprio `abrir`); a do clique em
    Excluir chama `contar_clique`, também quando o clique carrega e dá erro (o teto cobra a página
    mesmo sem a contagem devolvida, que se perde no erro)."""
    abertas = 0
    if carrinho is None:  # `carrinho`: a página do carrinho que quem chama acabou de abrir e conferir
        carrinho, abertas = abrir(URL_CARRINHO), 1
    for ativo in ESCOPOS_CARRINHO_ATIVO:
        escopo = _escopo_do_item(ativo, asin)
        if localizar(EXCLUIR, carrinho, escopo) is None:
            continue
        pausar()
        clicar_contando(nav, EXCLUIR, carrinho, contar_clique or (lambda: None), escopo)
        conferido = abrir(URL_CARRINHO)  # o clique pode só esconder o item por JS: confere recarregando
        return item_fora_do_carrinho_ativo(conferido, asin), abertas + 2
    return item_fora_do_carrinho_ativo(carrinho, asin), abertas
