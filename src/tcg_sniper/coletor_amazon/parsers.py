"""Parsers puros do HTML da amazon.com.br, escritos a partir de páginas reais (recortadas em
tests/fixtures/amazon). Estrutura observada na captura da Task 6:

Busca (`/s?k=<termo>`):
- Grade: `div.s-main-slot` (marcador de estrutura; ausente → `ErroParser`).
- Cada resultado: `div[data-component-type="s-search-result"]` com o ASIN em `data-asin`
  (cartões sem ASIN, como faixas e anúncios de marca, são ignorados).
- Título: texto do `h2` do cartão (ausente num cartão com ASIN → `ErroParser`).
- Preço: `.a-price:not(.a-text-price) .a-offscreen` ("R$ 554,00", com NBSP); o `.a-text-price`
  é o preço riscado "De:". Sem preço → `None`.
- Patrocinado: `.puis-sponsored-label-text` ou `.s-sponsored-label-text` dentro do cartão. Não
  casaram em nenhum cartão da captura (só há banners de anúncio fora dos cartões); não verificado.

Produto (`/dp/<ASIN>`):
- Título: `#productTitle` (ausente → `ErroParser`).
- Preço da oferta principal: `#corePrice_feature_div .a-price .a-offscreen`. Nunca usar
  `.a-price .a-offscreen` sem escopo: nas páginas de produto ele pega os carrosséis (10-28
  nós). `#corePriceDisplay_desktop_feature_div` e `#apex_desktop` existem mas têm texto vazio
  (e `#apex_desktop` pesa dezenas de KB no recorte): não são lidos. Indisponível (sem preço) → `None`.
- "Vendido por" e "Enviado por": `[offer-display-feature-name="desktop-merchant-info"]` e
  `[offer-display-feature-name="desktop-fulfiller-info"]`, texto em
  `.offer-display-feature-text-message`. O bloco "Enviado por" não existe em envio próprio nem
  em "Amazon Global". O bloco antigo `#merchant-info` não existe mais.
- Vendedor: link `#sellerProfileTriggerId`, com `seller=<ID>` no href.
- Opção do seletor de variações (página com envelope, caixa, deck... cada um com o seu ASIN):
  `#inline-twister-expanded-dimension-text-<dimensão>` (ex.: "Collector Booster Box"); sem seletor → `None`.

Perfil do vendedor (`/sp?seller=<ID>`):
- Nome: `#seller-name`.
- Resumo: `#seller-info-feedback-summary` (ausente → `ErroParser`), com texto como
  "5 de 5 estrelas 100% positivo total (2 avaliações)".

Lista de ofertas (`/gp/product/ajax/aodAjaxMain...` ou `/dp/<ASIN>?aod=1`), conferida nas fixtures
ofertas_importada, ofertas_amazon, ofertas_fba e painel_importada (captura de 2026-10-17):
- Estrutura: `#aod-container` (ausente no `/dp/<ASIN>?aod=1`), `#all-offers-display`,
  `#aod-offer-list`; nenhum deles nem bloco de oferta → `ErroParser`. Painel sem bloco → `[]`.
- Blocos: `#aod-pinned-offer` (a destacada, posição 0) e `#aod-offer` repetido (a lista, posição
  1.. na ordem dos blocos, mesmo quando um bloco é descartado).
- Preço: `.apex-pricetopay-accessibility-label` ("R$ 326,17 com 16 por cento de desconto"), depois
  `.aok-offscreen` sem o "De: R$ ..." (o preço riscado), depois `.a-price .a-offscreen` (vazio nas
  páginas reais). Sem preço legível → a oferta é descartada.
- Condição: `#aod-offer-heading` ("Novo", "Usado - Muito bom").
- Vendedor: `#aod-offer-soldBy .a-col-right`; o primeiro link tem `seller=<ID>` (a Amazon Global
  também tem link; vendida pela Amazon vira seller_id "amazon"). No mesmo bloco: "A classificação do
  vendedor é 4.5 de 5 estrelas (29 avaliações) 86% positivas ao longo da vida".
- Quem envia e origem: `#aod-offer-shipsFrom .a-col-right` ("Amazon Origem do envio Estados Unidos.",
  ou só o nome do lojista no envio próprio).
- Importada: "Compra Internacional" ou "tributos de importação" no bloco, ou origem diferente de Brasil.
- Prime: `i.a-icon-prime`, `.a-icon-prime`, `[aria-label*="Prime"]`.
- Cupom (só informativo): "15%  off na 1ª compra com cartão Amazon" ou "cupom de desconto XXXX".
"""

import logging
import re
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

from tcg_sniper.coletor_amazon.modelos import (
    SELLER_AMAZON,
    AvaliacaoVendedor,
    OfertaLista,
    OfertaProduto,
    ResultadoBusca,
)
from tcg_sniper.db.models import Envio
from tcg_sniper.parsing import ErroParser, parse_preco_brl

log = logging.getLogger(__name__)

BASE_AMAZON = "https://www.amazon.com.br"

SELETOR_GRADE_BUSCA = "div.s-main-slot"
SELETOR_RESULTADO = 'div[data-component-type="s-search-result"]'
SELETOR_TITULO_RESULTADO = "h2"
SELETOR_PRECO_RESULTADO = ".a-price:not(.a-text-price) .a-offscreen"
SELETORES_PATROCINADO = (".puis-sponsored-label-text", ".s-sponsored-label-text")

SELETOR_TITULO_PRODUTO = "#productTitle"
SELETORES_PRECO_PRODUTO = (
    "#corePrice_feature_div .a-price .a-offscreen",
)
SELETOR_VENDIDO_POR = '[offer-display-feature-name="desktop-merchant-info"] .offer-display-feature-text-message'
SELETOR_ENVIADO_POR = '[offer-display-feature-name="desktop-fulfiller-info"] .offer-display-feature-text-message'
SELETOR_LINK_VENDEDOR = "#sellerProfileTriggerId"
# Valor selecionado de cada dimensão do seletor de variações (estilo, tamanho...): o título da
# página muitas vezes não diz qual opção é ("Final Fantasy, multicolorido" para a caixa de boosters).
SELETOR_VARIACAO = '[id^="inline-twister-expanded-dimension-text-"]'

SELETOR_IMAGEM_RESULTADO = "img.s-image"
SELETOR_IMAGEM_PRODUTO = "#landingImage"

SELETOR_NOME_VENDEDOR = "#seller-name"
SELETOR_RESUMO_VENDEDOR = "#seller-info-feedback-summary"
_RE_PCT_POSITIVAS = re.compile(r"(\d{1,3})\s*%\s*(?:de\s+)?(?:avaliações\s+)?positiv", re.IGNORECASE)
_RE_NUM_AVALIACOES = re.compile(r"\(\s*([\d.]+)\s+avalia", re.IGNORECASE)

# Trechos que o recorte das fixtures mantém (scripts/recortar_fixture.py): tudo o que os parsers leem.
BLOCOS_BUSCA = (SELETOR_RESULTADO,)
BLOCOS_PRODUTO = (
    SELETOR_TITULO_PRODUTO,
    "#corePrice_feature_div",
    '[offer-display-feature-name="desktop-merchant-info"]',
    '[offer-display-feature-name="desktop-fulfiller-info"]',
    SELETOR_LINK_VENDEDOR,
    SELETOR_VARIACAO,
    SELETOR_IMAGEM_PRODUTO,
)
BLOCOS_VENDEDOR = (SELETOR_NOME_VENDEDOR, SELETOR_RESUMO_VENDEDOR)

# "Amazon Global" (importação pela própria Amazon) conta como a Amazon: decisão do grupo em 2026-10-15.
_NOMES_AMAZON = {"amazon", "amazon.com.br", "amazon global"}


def url_produto(asin: str) -> str:
    return f"{BASE_AMAZON}/dp/{asin}"


def url_vendedor(seller_id: str) -> str:
    return f"{BASE_AMAZON}/sp?seller={seller_id}"


URL_CARRINHO = f"{BASE_AMAZON}/gp/cart/view.html"
# Blocos do painel "Outras opções de compra": a oferta em destaque e as demais (id repetido).
SELETOR_PAINEL_OFERTAS = "#aod-pinned-offer, #aod-offer"


def url_ofertas(asin: str) -> str:
    """Fragmento com todas as ofertas do ASIN (o painel "Outras opções de compra" carrega daqui)."""
    return f"{BASE_AMAZON}/gp/product/ajax/aodAjaxMain/ref=dp_aod_ALL_mbc?asin={asin}&pc=dp&experienceId=aodAjaxMain"


def url_painel_ofertas(asin: str) -> str:
    """Página do produto com o painel de ofertas aberto (onde fica o "Adicionar ao carrinho" de cada oferta)."""
    return f"{BASE_AMAZON}/dp/{asin}?aod=1"


def eh_vendido_pela_amazon(texto: str) -> bool:
    """Só "Amazon", "Amazon.com.br" ou "Amazon Global": um lojista chamado "Amazonas Games" não é a Amazon."""
    return texto.strip().lower() in _NOMES_AMAZON


def classificar_envio(vendido_por: str | None, enviado_por: str | None) -> Envio:
    if vendido_por is None:
        return Envio.DESCONHECIDO
    if eh_vendido_pela_amazon(vendido_por):
        return Envio.AMAZON
    if enviado_por is None:
        return Envio.DESCONHECIDO
    return Envio.FBA if eh_vendido_pela_amazon(enviado_por) else Envio.PROPRIO


def _texto(no: LexborNode | LexborHTMLParser, seletor: str) -> str | None:
    alvo = no.css_first(seletor)
    if alvo is None:
        return None
    return alvo.text(separator=" ", strip=True) or None


def _url_imagem(no: LexborNode | None, *atributos: str) -> str | None:
    if no is None:
        return None
    for atributo in atributos:
        valor = (no.attributes.get(atributo) or "").strip()
        if valor.startswith(("http://", "https://")):
            return valor
    return None


def parse_busca(html: str, limite: int) -> list[ResultadoBusca]:
    """Os primeiros `limite` resultados da busca, na ordem da página (pode repetir ASIN)."""
    arvore = LexborHTMLParser(html)
    if arvore.css_first(SELETOR_GRADE_BUSCA) is None:
        raise ErroParser("grade de resultados da busca não encontrada")
    itens: list[ResultadoBusca] = []
    for cartao in arvore.css(f"{SELETOR_GRADE_BUSCA} {SELETOR_RESULTADO}"):
        if len(itens) >= limite:
            break
        asin = (cartao.attributes.get("data-asin") or "").strip()
        if not asin:
            continue
        titulo = _texto(cartao, SELETOR_TITULO_RESULTADO)
        if titulo is None:
            raise ErroParser(f"resultado {asin} sem título")
        preco = _texto(cartao, SELETOR_PRECO_RESULTADO)
        itens.append(
            ResultadoBusca(
                asin=asin,
                titulo=titulo,
                url=url_produto(asin),
                preco=parse_preco_brl(preco) if preco else None,
                patrocinado=any(cartao.css_first(s) is not None for s in SELETORES_PATROCINADO),
                imagem_url=_url_imagem(cartao.css_first(SELETOR_IMAGEM_RESULTADO), "src"),
            )
        )
    return itens


def _seller_id(arvore: LexborHTMLParser) -> str | None:
    link = arvore.css_first(SELETOR_LINK_VENDEDOR)
    if link is None:
        return None
    valores = parse_qs(urlsplit(link.attributes.get("href") or "").query).get("seller")
    return valores[0] if valores else None


def parse_produto_amazon(html: str, asin: str) -> OfertaProduto:
    arvore = LexborHTMLParser(html)
    titulo = _texto(arvore, SELETOR_TITULO_PRODUTO)
    if titulo is None:
        raise ErroParser("título do produto não encontrado")
    preco = None
    for seletor in SELETORES_PRECO_PRODUTO:
        texto = _texto(arvore, seletor)
        if texto:
            preco = parse_preco_brl(texto)
            break
    vendido_por = _texto(arvore, SELETOR_VENDIDO_POR)
    envio = classificar_envio(vendido_por, _texto(arvore, SELETOR_ENVIADO_POR))
    seller_id = SELLER_AMAZON if envio is Envio.AMAZON else _seller_id(arvore)
    return OfertaProduto(
        asin,
        titulo,
        preco,
        vendido_por,
        seller_id,
        envio,
        _variacao(arvore),
        imagem_url=_url_imagem(arvore.css_first(SELETOR_IMAGEM_PRODUTO), "data-old-hires", "src"),
    )


def _variacao(arvore: LexborHTMLParser) -> str | None:
    """As opções selecionadas no seletor de variações, unidas por " · " (None sem seletor)."""
    valores = [v for no in arvore.css(SELETOR_VARIACAO) if (v := no.text(separator=" ", strip=True))]
    return " · ".join(valores) or None


def parse_vendedor(html: str, seller_id: str) -> AvaliacaoVendedor:
    arvore = LexborHTMLParser(html)
    resumo = arvore.css_first(SELETOR_RESUMO_VENDEDOR)
    if resumo is None:
        raise ErroParser("resumo de avaliações do vendedor não encontrado")
    texto = resumo.text(separator=" ", strip=True)
    pct = _RE_PCT_POSITIVAS.search(texto)
    num = _RE_NUM_AVALIACOES.search(texto)
    if pct is None and num is None:
        log.warning("resumo de avaliações do vendedor %s ilegível (layout novo?): %r", seller_id, texto[:200])
    return AvaliacaoVendedor(
        seller_id=seller_id,
        nome=_texto(arvore, SELETOR_NOME_VENDEDOR),
        pct_positivas=Decimal(pct.group(1)) if pct else None,
        num_avaliacoes=int(num.group(1).replace(".", "")) if num else None,
    )


SELETOR_OFERTA_DESTAQUE = "#aod-pinned-offer"
SELETOR_OFERTA_LISTA = "#aod-offer"
SELETORES_ESTRUTURA_OFERTAS = ("#aod-container", "#all-offers-display", "#aod-offer-list", "#aod-pinned-offer", "#aod-offer")
SELETOR_CONDICAO = "#aod-offer-heading"
SELETOR_VENDIDO_POR_OFERTA = "#aod-offer-soldBy .a-col-right"
SELETOR_ENVIADO_POR_OFERTA = "#aod-offer-shipsFrom .a-col-right"
SELETORES_PRECO_OFERTA = (".apex-pricetopay-accessibility-label", ".aok-offscreen", ".a-price .a-offscreen")
SELETORES_PRIME = ("i.a-icon-prime", ".a-icon-prime", '[aria-label*="Prime"]')
BLOCOS_OFERTAS = (SELETOR_OFERTA_DESTAQUE, "#aod-offer-list", SELETOR_OFERTA_LISTA)
_RE_VALOR = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2})")
_RE_PRECO_DE = re.compile(r"De:\s*R\$\s*(\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2})")
_RE_ORIGEM = re.compile(r"Origem do envio\s*:?\s*([^.]+)", re.IGNORECASE)
# Sem atravessar quebra de linha: o cupom é procurado no texto do bloco com um nó por linha, para não
# engolir o "Vendido por ..." que vem logo depois dele.
_RE_CUPOM = re.compile(r"(\d{1,2}\s*%\s*off[^.\n]{0,80}|cupom de desconto \S+)", re.IGNORECASE)
_MARCAS_IMPORTADA = ("compra internacional", "tributos de importação")


def _preco_da_oferta(bloco: LexborNode) -> Decimal | None:
    """O preço a pagar: o rótulo de acessibilidade ("R$ 326,17 com 16 por cento de desconto"); o
    `.a-offscreen` visível veio vazio nas páginas reais. Textos "De: R$ ..." são o preço riscado."""
    for seletor in SELETORES_PRECO_OFERTA:
        for no in bloco.css(seletor):
            texto = no.text(separator=" ", strip=True)
            if not texto or texto.lower().startswith("de:"):
                continue
            achado = _RE_VALOR.search(texto)
            if achado:
                return parse_preco_brl(achado.group(1))
    return None


def _vendedor_da_oferta(bloco: LexborNode) -> tuple[str | None, str | None, str]:
    """(nome, seller_id, texto do bloco "Vendido por" com a avaliação)."""
    alvo = bloco.css_first(SELETOR_VENDIDO_POR_OFERTA)
    if alvo is None:
        return None, None, ""
    link = alvo.css_first("a")
    nome = (link.text(separator=" ", strip=True) if link is not None else None) or _texto(alvo, "span")
    seller_id = None
    if link is not None:
        valores = parse_qs(urlsplit(link.attributes.get("href") or "").query).get("seller")
        seller_id = valores[0] if valores else None
    return nome, seller_id, alvo.text(separator=" ", strip=True)


def _envio_da_oferta(bloco: LexborNode) -> tuple[str | None, str | None]:
    """(quem envia, origem do envio) de "Amazon Origem do envio Estados Unidos."."""
    alvo = bloco.css_first(SELETOR_ENVIADO_POR_OFERTA)
    if alvo is None:
        return None, None
    texto = alvo.text(separator=" ", strip=True)
    origem = _RE_ORIGEM.search(texto)
    quem = _RE_ORIGEM.sub("", _texto(alvo, "span") or texto).strip(" .") or None
    return quem, origem.group(1).strip() if origem else None


def _condicao(bloco: LexborNode) -> str:
    texto = (_texto(bloco, SELETOR_CONDICAO) or "").lower()
    # "Usado - Como novo" é usado: confere "usado" antes de "novo".
    if "usado" in texto or "used" in texto:
        return "usado"
    if "novo" in texto or "new" in texto:
        return "novo"
    return texto or "desconhecida"


def parse_ofertas(html: str) -> list[OfertaLista]:
    """Todas as ofertas do painel, a destacada (posição 0) primeiro. Lista vazia: o painel abriu sem
    oferta (indisponível). Sem nenhum bloco do painel → ErroParser (layout novo ou página errada)."""
    arvore = LexborHTMLParser(html)
    if not any(arvore.css_first(seletor) is not None for seletor in SELETORES_ESTRUTURA_OFERTAS):
        raise ErroParser("painel de ofertas não encontrado")
    blocos = [(0, bloco) for bloco in arvore.css(SELETOR_OFERTA_DESTAQUE)[:1]]
    blocos += list(enumerate(arvore.css(SELETOR_OFERTA_LISTA), start=1))
    ofertas: list[OfertaLista] = []
    vistas: set[tuple[str | None, Decimal, str]] = set()
    for posicao, bloco in blocos:
        if posicao == 0 and bloco.css_first(SELETOR_VENDIDO_POR_OFERTA) is None:
            # Anúncio sem oferta em destaque: o bloco fixo só tem foto, título e avaliações
            # ("Nenhuma opção de compra em destaque"); as ofertas estão só na lista.
            log.debug("painel sem oferta em destaque")
            continue
        preco = _preco_da_oferta(bloco)
        if preco is None:
            log.warning("oferta %d do painel sem preço legível; descartada", posicao)
            continue
        condicao = _condicao(bloco)
        nome, seller_id, texto_vendedor = _vendedor_da_oferta(bloco)
        if (nome, preco, condicao) in vistas:
            continue  # a destacada costuma se repetir na lista
        vistas.add((nome, preco, condicao))
        quem_envia, origem = _envio_da_oferta(bloco)
        envio = classificar_envio(nome, quem_envia)
        texto = bloco.text(separator=" ", strip=True)
        baixo = texto.lower()
        pct = _RE_PCT_POSITIVAS.search(texto_vendedor)
        num = _RE_NUM_AVALIACOES.search(texto_vendedor)
        de = _RE_PRECO_DE.search(texto)
        cupom = _RE_CUPOM.search(bloco.text(separator="\n", strip=True))
        ofertas.append(
            OfertaLista(
                posicao=posicao,
                vendedor_nome=nome,
                seller_id=SELLER_AMAZON if envio is Envio.AMAZON else seller_id,
                preco=preco,
                preco_de=parse_preco_brl(de.group(1)) if de else None,
                condicao=condicao,
                envio=envio,
                origem_envio=origem,
                importada=any(marca in baixo for marca in _MARCAS_IMPORTADA)
                or (origem is not None and origem.lower() != "brasil"),
                prime=any(bloco.css_first(seletor) is not None for seletor in SELETORES_PRIME),
                pct_positivas=Decimal(pct.group(1)) if pct else None,
                num_avaliacoes=int(num.group(1).replace(".", "")) if num else None,
                cupom=" ".join(cupom.group(1).split()) if cupom else None,
            )
        )
    return ofertas
