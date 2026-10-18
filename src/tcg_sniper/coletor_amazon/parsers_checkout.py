"""Parsers puros do carrinho, do resumo do checkout e da página de login da amazon.com.br, escritos a
partir das páginas reais anonimizadas em tests/fixtures/amazon (Task 9 do plano 2026-10-17).

Carrinho (`/gp/cart/view.html`): contador `#nav-cart-count`; itens do carrinho ativo com `data-asin`
dentro de `ESCOPOS_CARRINHO_ATIVO` ("Salvo para depois", `#sc-saved-cart`/`data-name="Saved Cart"`,
fica fora); subtotal em `[data-name="Subtotals"]` ("Nenhum produto selecionado Subtotal (1 produto):
R$ 314,11").

Checkout (`/checkout/p/p-<id>/address` e `/spc`): resumo em `#subtotals-marketplace-table` com as
linhas "Itens:", "Frete:", "Taxas de importação incluindo ICMS:" (só em importados) e "Total do
pedido:". O termo dos impostos traz um popover com o detalhamento ("ICMS estimado R$ x", "Taxas de
importação estimadas R$ y" e de novo "Taxas de importação incluindo ICMS: R$ z") antes do valor da
linha; vale o primeiro rótulo seguido direto de um valor. No passo do endereço itens e frete aparecem
como "--" e há o botão "Entregar neste endereço" (um "continuar" genérico com o rótulo no span
-announce).

Valores finais (itens, frete, impostos, total) só saem com a etapa RESUMO, lidos todos do mesmo bloco
do resumo; no passo do endereço o total da página vai para `total_estimado`.

Login: URL `/ap/signin` ou o formulário `form[name="signIn"]` ("Fazer login", `#ap_email_login`).
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from selectolax.lexbor import LexborHTMLParser

from tcg_sniper.coletor_amazon.cliques import (
    ENTREGAR,
    ESCOPOS_CARRINHO_ATIVO,
    SELETORES_LOGIN,
    localizar,
    texto_do_elemento,
)
from tcg_sniper.navegador.modelos import Pagina
from tcg_sniper.parsing import ErroParser, parse_preco_brl

SELETOR_CONTADOR = "#nav-cart-count"
SELETORES_SUBTOTAL = ('[data-name="Subtotals"]', "#sc-subtotal-amount-activecart", "#sc-subtotal-amount-buybox")
SELETORES_RESUMO = (
    "#subtotals-marketplace-table",
    "#order-summary-container",
    '[data-testid="order-summary"]',
    "#spc-order-summary",
    "body",
)
_VALOR = r"(R\$\s*(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}|--|Gr[aá]tis)"
_RE_LINHAS = {
    "itens": re.compile(rf"Itens\s*:?\s*{_VALOR}", re.IGNORECASE),
    "frete": re.compile(rf"Frete(?: e manuseio)?\s*:?\s*{_VALOR}", re.IGNORECASE),
    # [^:$]*: o rótulo não atravessa um valor ("... estimadas R$ 0,00 Taxas ...: R$ 51,05")
    "impostos": re.compile(rf"Taxas de importa[cç][aã]o[^:$]*:\s*{_VALOR}", re.IGNORECASE),
    "total": re.compile(rf"Total do pedido\s*:?\s*{_VALOR}", re.IGNORECASE),
}
_RE_SUBTOTAL = re.compile(r"R\$\s*((?:\d{1,3}(?:\.\d{3})+|\d+),\d{2})")


@dataclass(frozen=True)
class Carrinho:
    contador: int | None  # None: contador ilegível (quem chama não pode supor carrinho vazio)
    asins_ativos: tuple[str, ...]
    subtotal: Decimal | None


class Etapa(StrEnum):
    ENDERECO = "endereco"
    RESUMO = "resumo"
    LOGIN = "login"
    DESCONHECIDA = "desconhecida"


@dataclass(frozen=True)
class ResumoCheckout:
    """Valores do pedido, só preenchidos com `etapa is Etapa.RESUMO` (fora dele são todos None).
    `frete` None quer dizer frete não lido (linha ausente ou valor ilegível), NUNCA frete zero: quem
    consome não pode tratar None como 0 ("Grátis" já vira Decimal("0.00")). `total_estimado` é o
    "Total do pedido" do passo do endereço (estimativa antes de escolher a entrega), só em ENDERECO."""

    etapa: Etapa
    itens: Decimal | None
    frete: Decimal | None
    impostos: Decimal | None
    total: Decimal | None
    total_estimado: Decimal | None = None


def _contador(arvore: LexborHTMLParser) -> int | None:
    no = arvore.css_first(SELETOR_CONTADOR)
    texto = no.text(strip=True) if no is not None else ""
    return int(texto) if texto.isdecimal() else None


def contador_do_carrinho(html: str) -> int | None:
    """O contador do carrinho na barra de qualquer página da Amazon (`#nav-cart-count`); None se ilegível."""
    return _contador(LexborHTMLParser(html))


def parse_carrinho(html: str) -> Carrinho:
    """Levanta ErroParser sem nenhum bloco do carrinho ativo (`ESCOPOS_CARRINHO_ATIVO`): login,
    desafio (CAPTCHA) ou página de erro também mostram `#nav-cart-count`, mas não provam carrinho
    vazio."""
    arvore = LexborHTMLParser(html)
    escopos = [no for escopo in ESCOPOS_CARRINHO_ATIVO for no in arvore.css(escopo)]
    if not escopos:
        raise ErroParser("carrinho não encontrado (nenhum bloco do carrinho ativo na página)")
    contador = _contador(arvore)
    asins: list[str] = []
    for escopo in escopos:
        for item in escopo.css("[data-asin]"):
            asin = (item.attributes.get("data-asin") or "").strip()
            if asin and asin not in asins:
                asins.append(asin)
    subtotal = None
    for seletor in SELETORES_SUBTOTAL:
        no = arvore.css_first(seletor)
        achado = _RE_SUBTOTAL.search(no.text(separator=" ", strip=True)) if no is not None else None
        if achado:
            subtotal = parse_preco_brl(achado.group(1))
            break
    return Carrinho(contador, tuple(asins), subtotal)


def eh_login(pagina: Pagina) -> bool:
    if "/ap/signin" in pagina.url:
        return True
    arvore = LexborHTMLParser(pagina.html)
    return any(arvore.css_first(seletor) is not None for seletor in SELETORES_LOGIN)


def _valor(texto: str) -> Decimal | None:
    if texto == "--":
        return None
    if texto.lower().startswith("gr"):
        return Decimal("0.00")
    return parse_preco_brl(texto)


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


def _tem_botao_entregar(pagina: Pagina) -> bool:
    """O botão do passo do endereço, com o rótulo "Entregar neste endereço" (o seletor real é um
    "continuar" genérico, que também aparece em outros passos)."""
    achado = localizar(ENTREGAR, pagina)
    if achado is None:
        return False
    seletor, indice = achado
    no = LexborHTMLParser(pagina.html).css(seletor)[indice]
    return ENTREGAR.padrao.search(_sem_acento(texto_do_elemento(no))) is not None


def _texto_do_resumo(arvore: LexborHTMLParser) -> str:
    """O texto de UM bloco do resumo: o primeiro bloco com "Total do pedido" ou, se nenhum tem, o
    primeiro que existe. `body` só quando nenhum seletor de bloco acha nada na página."""
    blocos = [no for seletor in SELETORES_RESUMO if seletor != "body" for no in arvore.css(seletor)]
    textos = [no.text(separator=" ", strip=True) for no in blocos]
    if textos:
        return next((t for t in textos if _RE_LINHAS["total"].search(t)), textos[0])
    return arvore.body.text(separator=" ", strip=True) if arvore.body is not None else ""


def parse_resumo_checkout(pagina: Pagina) -> ResumoCheckout:
    """RESUMO quando o mesmo bloco do resumo traz "Itens:" e "Total do pedido:" com valor; ENDERECO
    quando não e há o botão "Entregar neste endereço" (total da página em `total_estimado`). Fora do
    RESUMO itens, frete, impostos e total são None."""
    if eh_login(pagina):
        return ResumoCheckout(Etapa.LOGIN, None, None, None, None)
    texto = _texto_do_resumo(LexborHTMLParser(pagina.html))
    valores = {}
    for campo, regex in _RE_LINHAS.items():
        achado = regex.search(texto)
        valores[campo] = _valor(achado.group(1)) if achado else None
    if valores["itens"] is not None and valores["total"] is not None:
        return ResumoCheckout(Etapa.RESUMO, **valores)
    if _tem_botao_entregar(pagina):
        return ResumoCheckout(Etapa.ENDERECO, None, None, None, None, total_estimado=valores["total"])
    return ResumoCheckout(Etapa.DESCONHECIDA, None, None, None, None)
