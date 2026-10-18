"""Carrinho, checkout e login da Amazon no formato visto nas fixtures reais (tests/fixtures/amazon)."""

from fakes import pagina_html

from tcg_sniper.coletor_amazon.parsers import URL_CARRINHO

URL_ENDERECO = "https://www.amazon.com.br/checkout/p/p-000-0000000-0000000/address?pipelineType=Chewbacca"
URL_RESUMO = "https://www.amazon.com.br/checkout/p/p-000-0000000-0000000/spc?pipelineType=Chewbacca"
URL_LOGIN = "https://www.amazon.com.br/ap/signin?openid.return_to=x"
# checkout_endereco.html real: botão "continuar" genérico com o rótulo no span -announce
BOTAO_ENTREGAR = (
    '<span id="checkout-primary-continue-button-id" class="a-button a-button-primary"><span class="a-button-inner">'
    '<input data-testid="bottom-continue-button" class="a-button-input" type="submit"'
    ' aria-labelledby="checkout-primary-continue-button-id-announce">'
    '<span id="checkout-primary-continue-button-id-announce" class="a-button-text"> Entregar neste endereço </span>'
    "</span></span>"
)


def item_carrinho(asin: str) -> str:
    return (
        f'<div class="sc-list-item" data-asin="{asin}"><span class="sc-product-title">Item {asin}</span>'
        f'<input data-action="delete" name="submit.delete.{asin}" value="Excluir" type="submit" aria-label="Excluir Item {asin}"></div>'
    )


# Link "Sair da conta" da barra (como nas páginas reais da conta logada; um carrinho de visitante não tem).
SAIR_DA_CONTA = '<a id="nav-item-signout" href="/gp/flex/sign-out.html" class="nav-link nav-item"><span class="nav-text">Sair da conta</span></a>'


def carrinho(*ativos, salvos=(), subtotal=None, contador=None, logado=True):
    n = len(ativos) if contador is None else contador
    soma = (
        f'<div data-name="Subtotals">Nenhum produto selecionado Subtotal ({n} produto): {subtotal}</div>'
        if subtotal
        else ""
    )
    botao = '<input name="proceedToRetailCheckout" value="Fechar pedido" type="submit">' if ativos else ""
    return pagina_html(
        f'<html><body>{SAIR_DA_CONTA if logado else ""}<span id="nav-cart-count">{n}</span>'
        f'<div id="sc-active-cart" data-name="Active Cart"><form id="activeCartViewForm">'
        f'<div data-name="Active Items">{"".join(map(item_carrinho, ativos))}</div>{soma}{botao}</form></div>'
        f'<div id="sc-saved-cart" data-name="Saved Cart">{"".join(map(item_carrinho, salvos))}</div></body></html>',
        url=URL_CARRINHO,
    )


def _linha(termo: str, valor: str) -> str:
    return (
        f'<li><div class="order-summary-grid"><div class="order-summary-line-term"><span>{termo}</span></div>'
        f'<div class="order-summary-line-definition"><span>{valor}</span></div></div></li>'
    )


def checkout_endereco(total="R$ 237,73", botao=BOTAO_ENTREGAR):
    return pagina_html(
        f'<html><body>{botao}<ul id="subtotals-marketplace-table">'
        f"{_linha('Itens:', '--')}{_linha('Frete:', '--')}{_linha('Total do pedido:', total)}</ul></body></html>",
        url=URL_ENDERECO,
    )


def checkout_resumo(itens="R$ 237,73", frete="R$ 0,00", impostos="R$ 48,26", total="R$ 285,99"):
    # Como na página real, o termo dos impostos traz um popover com o detalhamento (ICMS, taxas e de
    # novo a linha "Taxas de importação incluindo ICMS:") antes do valor da linha.
    taxa = (
        _linha(
            "Taxas de importação incluindo ICMS:<table><tr><td>ICMS estimado</td><td> "
            f"{impostos} </td></tr><tr><td>Taxas de importação estimadas</td><td> R$ 0,00 </td></tr>"
            f"<tr><td>Taxas de importação incluindo ICMS:</td><td> {impostos} </td></tr></table>",
            impostos,
        )
        if impostos
        else ""
    )
    return pagina_html(
        f'<html><body><ul id="subtotals-marketplace-table">{_linha("Itens:", itens)}{_linha("Frete:", frete)}'
        f"{taxa}{_linha('Total do pedido:', total)}</ul>"
        '<input id="placeOrder" name="placeYourOrder1" type="submit" value="Confirmar pedido com cartão Fulano">'
        "</body></html>",
        url=URL_RESUMO,
    )


def login():
    return pagina_html(
        '<html><body><form name="signIn"><input id="ap_email_login"></form></body></html>', url=URL_LOGIN
    )
