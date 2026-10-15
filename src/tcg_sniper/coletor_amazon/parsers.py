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
"""

import logging
import re
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

from tcg_sniper.coletor_amazon.modelos import SELLER_AMAZON, AvaliacaoVendedor, OfertaProduto, ResultadoBusca
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
)
BLOCOS_VENDEDOR = (SELETOR_NOME_VENDEDOR, SELETOR_RESUMO_VENDEDOR)

# "Amazon Global" (importação pela própria Amazon) conta como a Amazon: decisão do grupo em 2026-10-15.
_NOMES_AMAZON = {"amazon", "amazon.com.br", "amazon global"}


def url_produto(asin: str) -> str:
    return f"{BASE_AMAZON}/dp/{asin}"


def url_vendedor(seller_id: str) -> str:
    return f"{BASE_AMAZON}/sp?seller={seller_id}"


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
    return OfertaProduto(asin, titulo, preco, vendido_por, seller_id, envio, _variacao(arvore))


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
