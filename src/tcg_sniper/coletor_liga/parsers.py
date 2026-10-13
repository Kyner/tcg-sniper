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
  Ausente → os três preços ficam `None`.
- Número de lojas: filtro "Vendedores" (`.group-filter` cujo `.filter-header .title` tem
  `data-label="Vendedores"`), opção `.filter-option` com `.filter-infos[title="Lojas"]`,
  contador em `.filter-counter` (ex.: 94 com só 16 linhas no HTML). Sem lojas, a página não
  tem nenhum `.group-filter` e `#marketplace-stores` tem `.alertaErro` → 0. Nenhum dos dois
  → `ErroParser`.
"""

import re
from decimal import Decimal

from selectolax.lexbor import LexborHTMLParser, LexborNode

from tcg_sniper.coletor_liga.modelos import ErroParser, Resumo

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


def parse_preco_brl(texto: str) -> Decimal:
    m = _RE_PRECO.search(texto.replace("\xa0", " "))
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
        precos = (None, None, None)
    else:
        precos = tuple(
            parse_preco_brl(_texto(quadro, seletor)) for seletor in SELETORES_PRECO
        )
    preco_min, preco_medio, preco_max = precos
    return Resumo(
        preco_min=preco_min,
        preco_medio=preco_medio,
        preco_max=preco_max,
        num_lojas=_num_lojas(arvore),
    )
