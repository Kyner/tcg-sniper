"""Painel "Outras opções de compra" da Amazon no formato visto nas fixtures reais (tests/fixtures/amazon)."""


def bloco_oferta(
    preco="R$ 275,91",
    vendedor="Shazaar",
    seller_id="A2SHZ",
    envia="Amazon",
    origem=None,
    condicao="Novo",
    destaque=False,
    avaliacao=None,
    de=None,
    prime=False,
    internacional=False,
    cupom=None,
    botao=True,
) -> str:
    """Um bloco de oferta. `seller_id=None` mostra o vendedor sem link (como a Amazon); `envia=None` omite
    o bloco "Enviado por" (como nas ofertas vendidas e enviadas pela Amazon)."""
    id_bloco = "aod-pinned-offer" if destaque else "aod-offer"
    if seller_id:
        nome = (
            f'<a class="a-size-small a-link-normal" href="/gp/aag/main?ie=UTF8&amp;seller={seller_id}'
            f'&amp;isAmazonFulfilled=1">{vendedor}</a>'
        )
    else:
        nome = f'<span class="a-size-small a-color-base">{vendedor}</span>'
    nota = f'<span class="a-size-small">{avaliacao}</span>' if avaliacao else ""
    preco_de = f'<span class="aok-offscreen">De: {de}</span>' if de else ""
    enviado = ""
    if envia:
        origem_html = f' <span class="a-size-small a-color-secondary">Origem do envio {origem}.</span>' if origem else ""
        enviado = (
            '<div id="aod-offer-shipsFrom"><div class="a-col-left"><span>Enviado por</span></div>'
            f'<div class="a-col-right"><span class="a-size-small a-color-base">{envia}</span>{origem_html}</div></div>'
        )
    extras = []
    if internacional:
        extras.append('<span class="a-color-secondary">Compra Internacional</span><span>Os tributos de importação estão incluídos</span>')
    if prime:
        extras.append('<i class="a-icon a-icon-prime" aria-label="Amazon Prime"></i>')
    if cupom:
        extras.append(f'<span class="a-color-success">{cupom}</span>')
    adicionar = (
        '<span data-action="aod-atc-action"><input name="submit.addToCart" value="Adicionar ao carrinho" '
        'type="submit" class="a-button-input"></span>'
        if botao
        else ""
    )
    return (
        f'<div id="{id_bloco}"><div id="aod-offer-price"><span class="a-price"><span class="a-offscreen"></span></span>'
        f'<span class="aok-offscreen apex-pricetopay-accessibility-label">{preco}</span>{preco_de}</div>'
        f'<div id="aod-offer-heading"><h5>{condicao}</h5></div>{"".join(extras)}'
        '<div id="aod-offer-soldBy"><div class="a-col-left"><span>Vendido por</span></div>'
        f'<div class="a-col-right">{nome}{nota}</div></div>{enviado}{adicionar}</div>'
    )


def html_ofertas(*blocos: str, comprar_agora: bool = False, carrinho: int | None = None) -> str:
    """Painel com a oferta destacada e a lista; `comprar_agora` põe o botão "Comprar agora" da página do
    produto; `carrinho` põe o contador do carrinho da barra da página do produto (`#nav-cart-count`)."""
    destaque = "".join(b for b in blocos if b.startswith('<div id="aod-pinned-offer"'))
    lista = "".join(b for b in blocos if b.startswith('<div id="aod-offer"'))
    comprar = '<input id="buy-now-button" name="submit.buy-now" value="Comprar agora" type="submit">' if comprar_agora else ""
    contador = f'<span id="nav-cart-count">{carrinho}</span>' if carrinho is not None else ""
    return f'<html><body>{contador}{comprar}<div id="aod-container">{destaque}<div id="aod-offer-list">{lista}</div></div></body></html>'
