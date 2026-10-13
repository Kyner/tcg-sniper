"""Parsers puros do HTML da LigaMagic, escritos a partir das fixtures reais em tests/fixtures/liga.

Página de produto (`?view=prod/view&pcode=N`), estrutura observada em 2026-10-13:

- `#marketplace-stores`: lista de ofertas das lojas; existe em toda página de produto e é o
  marcador de estrutura (ausente → `ErroParser`). Sem lojas, contém
  `<div class="alertaErro">… Nenhum item encontrado.</div>`.
- As ofertas individuais NÃO são lidas: preço e quantidade de cada `div.store` são desenhados
  dígito a dígito com sprite CSS (classes aleatórias + background-position), a loja é só um
  logotipo, e a página mostra 16 ofertas com um botão "Ver Mais" (JS) para o resto. Decisão do
  usuário em 2026-10-13: usar só o resumo textual.
- Quadro "Preço Médio de Venda no Marketplace" / "Preços aplicados no Marketplace":
  `.price-mkp .min .price`, `.price-mkp .medium .price`, `.price-mkp .max .price`
  (ex.: "R$ 29,89"). ATENÇÃO: é um indicador histórico do marketplace, não o menor preço
  pedido agora — a página sem nenhuma loja (pcode 276) ainda mostra R$ 5.450,00 nos três.
  As três páginas reais o têm, inclusive a sem lojas; ausente → `ErroParser`.
- Número de lojas: filtro "Vendedores" (`.group-filter` cujo `.filter-header .title` tem
  `data-label="Vendedores"`), opção `.filter-option` com `.filter-infos[title="Lojas"]`,
  contador em `.filter-counter` (ex.: 94 com só 16 linhas no HTML). Sem lojas, a página não
  tem nenhum `.group-filter` e `#marketplace-stores` tem `.alertaErro` → 0. Nenhum dos dois
  → `ErroParser`.

Listagem de categoria (`?view=cards/search&card=categ%3D<ID>+searchprod%3D1&tipo=1`),
estrutura observada em 2026-10-13 (fixture `catalogo_pagina_1`, categ 10):

- Grade da categoria: `.categoria__card-container` (marcador de estrutura; ausente →
  `ErroParser`). Cada produto é um `.card` dentro dela: 40 por carga; mais cartões só via o
  botão `#exibir_mais_cards input.exibir-mais` (`mcards.nextPage(40)`), sem link de próxima
  página. O carrossel "mais vendidos" (`.best-sellers`, 15 cartões) fica fora da grade e é
  ignorado.
- Link e nome: `h5.card-title a` (`href="/?view=prod/view&pcode=<ID>&prod=<nome>"`); o
  `pcode` é o `liga_id`.
- Preço atual: `.smallest-price` ("R$ 8.888,85"), precedido de "À partir de". Sem estoque, o
  cartão traz `.price-out-of-stock` ("Produto Indisponível") → `None`, nunca zero. Nenhum dos
  dois → `ErroParser`.
- Categoria: `.card-section a` ("Caixas de Boosters") → `tipo`.
- Grade sem nenhum cartão → `ErroParser` (layout mudou ou categoria vazia; categoria vazia
  deve sair de `LIGA_CATEGORIAS`).
"""

import re
from decimal import Decimal
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser, LexborNode

from tcg_sniper.coletor_liga.modelos import ErroParser, ItemListagem, Resumo

_RE_PRECO = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+),(\d{2})")
_RE_INTEIRO = re.compile(r"^\d+$")

SELETOR_ESTRUTURA_PRODUTO = "#marketplace-stores"
SELETOR_SEM_LOJAS = "#marketplace-stores .alertaErro"
SELETOR_QUADRO_PRECOS = ".price-mkp"
SELETORES_PRECO = (".min .price", ".medium .price", ".max .price")
SELETOR_GRUPO_FILTRO = ".group-filter"
SELETOR_TITULO_VENDEDORES = '.filter-header .title[data-label="Vendedores"]'
SELETOR_OPCAO_FILTRO = ".filter-option"
SELETOR_OPCAO_LOJAS = '.filter-infos[title="Lojas"]'
SELETOR_CONTADOR = ".filter-counter"

SELETOR_GRADE_LISTAGEM = ".categoria__card-container"
SELETOR_CARTAO = ".categoria__card-container .card"
SELETOR_LINK_CARTAO = "h5.card-title a"
SELETOR_PRECO_A_PARTIR = ".smallest-price"
SELETOR_SEM_ESTOQUE = ".price-out-of-stock"
SELETOR_CATEGORIA_CARTAO = ".card-section a"
_RE_PCODE = re.compile(r"[?&]pcode=(\d+)")


def parse_preco_brl(texto: str) -> Decimal:
    """"R$ 1.234,56" → Decimal("1234.56"). Sem "R$", NBSP e espaços nas pontas, o texto inteiro
    tem de ser um preço: qualquer sobra → `ErroParser` (nunca truncar)."""
    limpo = texto.replace("\xa0", " ").strip().removeprefix("R$").strip()
    m = _RE_PRECO.fullmatch(limpo)
    if not m:
        raise ErroParser(f"preço inválido: {texto!r}")
    return Decimal(f"{m.group(1).replace('.', '')}.{m.group(2)}")


def _texto(no: LexborNode, seletor: str) -> str:
    alvo = no.css_first(seletor)
    if alvo is None:
        raise ErroParser(f"elemento {seletor!r} não encontrado")
    return alvo.text(strip=True)


def _num_lojas(arvore: LexborHTMLParser) -> int:
    for grupo in arvore.css(SELETOR_GRUPO_FILTRO):
        if grupo.css_first(SELETOR_TITULO_VENDEDORES) is None:
            continue
        for opcao in grupo.css(SELETOR_OPCAO_FILTRO):
            if opcao.css_first(SELETOR_OPCAO_LOJAS) is not None:
                contador = _texto(opcao, SELETOR_CONTADOR)
                if not _RE_INTEIRO.match(contador):
                    raise ErroParser(f"contador de lojas inválido: {contador!r}")
                return int(contador)
    if arvore.css_first(SELETOR_SEM_LOJAS) is not None:
        return 0
    raise ErroParser("contador de lojas não encontrado")


def parse_produto(html: str) -> Resumo:
    arvore = LexborHTMLParser(html)
    if arvore.css_first(SELETOR_ESTRUTURA_PRODUTO) is None:
        raise ErroParser("estrutura da página de produto não encontrada")
    quadro = arvore.css_first(SELETOR_QUADRO_PRECOS)
    if quadro is None:
        raise ErroParser("quadro de preços do marketplace não encontrado")
    preco_min, preco_medio, preco_max = (
        parse_preco_brl(_texto(quadro, seletor)) for seletor in SELETORES_PRECO
    )
    return Resumo(
        preco_min=preco_min,
        preco_medio=preco_medio,
        preco_max=preco_max,
        num_lojas=_num_lojas(arvore),
    )


def _preco_a_partir(cartao: LexborNode) -> Decimal | None:
    preco = cartao.css_first(SELETOR_PRECO_A_PARTIR)
    if preco is not None:
        return parse_preco_brl(preco.text(strip=True))
    if cartao.css_first(SELETOR_SEM_ESTOQUE) is not None:
        return None
    raise ErroParser("cartão sem preço e sem aviso de indisponível")


def _item_listagem(cartao: LexborNode, url_base: str) -> ItemListagem:
    link = cartao.css_first(SELETOR_LINK_CARTAO)
    if link is None:
        raise ErroParser("cartão sem link do produto")
    href = link.attributes.get("href") or ""
    pcode = _RE_PCODE.search(href)
    if pcode is None:
        raise ErroParser(f"link sem pcode: {href!r}")
    nome = link.text(strip=True)
    if not nome:
        raise ErroParser(f"cartão sem nome: {href!r}")
    categoria = cartao.css_first(SELETOR_CATEGORIA_CARTAO)
    return ItemListagem(
        liga_id=pcode.group(1),
        nome=nome,
        url=urljoin(url_base, href),
        preco_a_partir=_preco_a_partir(cartao),
        tipo=(categoria.text(strip=True) or None) if categoria is not None else None,
    )


def parse_listagem(html: str, url_base: str) -> list[ItemListagem]:
    """Cartões da grade de uma listagem de categoria, na ordem da página (pode repetir `liga_id`)."""
    arvore = LexborHTMLParser(html)
    if arvore.css_first(SELETOR_GRADE_LISTAGEM) is None:
        raise ErroParser("grade da listagem não encontrada")
    cartoes = arvore.css(SELETOR_CARTAO)
    if not cartoes:
        raise ErroParser("listagem sem cartões")
    return [_item_listagem(cartao, url_base) for cartao in cartoes]
