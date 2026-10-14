"""Recorta uma página salva da LigaMagic só nos trechos que os parsers leem.

Uso:
  uv run python scripts/recortar_fixture.py <arquivo.html> [<arquivo.html> ...]

Sobrescreve cada arquivo com um HTML mínimo: o <title> e só os blocos usados pelos parsers
(ver o docstring de src/tcg_sniper/coletor_liga/parsers.py), sem imagens, scripts e estilos.
Antes de gravar, roda os parsers e a detecção de desafio no original e no recorte; se algum
resultado mudar, não grava e sai com erro.

- Listagem (tem `.categoria__card-container`): a grade de cartões, o carrossel `.best-sellers`
  (que o parser ignora) e o botão "Exibir mais".
- Página de produto: `#marketplace-stores` sem as ofertas das lojas (só o aviso "Nenhum item
  encontrado", quando houver), o aviso oculto `#marketplace-stores-noregisters`, o quadro
  `.price-mkp` e o filtro "Vendedores".
"""

import re
import sys
from html import escape
from pathlib import Path

from selectolax.lexbor import LexborHTMLParser, LexborNode

from tcg_sniper.coletor_liga.desafio import eh_desafio
from tcg_sniper.coletor_liga.modelos import Pagina
from tcg_sniper.coletor_liga.parsers import (
    SELETOR_ESTRUTURA_PRODUTO,
    SELETOR_GRADE_LISTAGEM,
    SELETOR_GRUPO_FILTRO,
    SELETOR_QUADRO_PRECOS,
    SELETOR_SEM_LOJAS,
    SELETOR_TITULO_VENDEDORES,
    parse_listagem,
    parse_produto,
)

URL_BASE = "https://www.ligamagic.com.br/?view=cards/search&card=categ%3D10+searchprod%3D1&tipo=1"
TAGS_REMOVIDAS = ["script", "style", "link", "noscript", "img", "svg", "iframe"]


def _limpo(no: LexborNode) -> str:
    copia = LexborHTMLParser(no.html)
    copia.strip_tags(TAGS_REMOVIDAS)
    corpo = copia.body
    if corpo is None:
        return ""
    html = corpo.html.removeprefix("<body>").removesuffix("</body>")
    # Espaços em sequência viram um só, e cada tag começa numa linha.
    return re.sub(r"\s+", " ", html).replace("> <", ">\n<")


def _blocos_listagem(arvore: LexborHTMLParser) -> list[str]:
    seletores = (SELETOR_GRADE_LISTAGEM, ".best-sellers", "#exibir_mais_cards")
    return [_limpo(no) for seletor in seletores for no in arvore.css(seletor)]


def _blocos_produto(arvore: LexborHTMLParser) -> list[str]:
    blocos = []
    lojas = arvore.css_first(SELETOR_ESTRUTURA_PRODUTO)
    if lojas is not None:
        aviso = arvore.css_first(SELETOR_SEM_LOJAS)
        atributos = "".join(f' {k}="{escape(v or "")}"' for k, v in lojas.attributes.items())
        interno = _limpo(aviso) if aviso is not None else ""
        blocos.append(f"<div{atributos}>{interno}</div>")
    blocos += [_limpo(no) for no in arvore.css("#marketplace-stores-noregisters")]
    blocos += [_limpo(no) for no in arvore.css(SELETOR_QUADRO_PRECOS)]
    for grupo in arvore.css(SELETOR_GRUPO_FILTRO):
        if grupo.css_first(SELETOR_TITULO_VENDEDORES) is not None:
            blocos.append(_limpo(grupo))
    return blocos


def recortar(html: str) -> str:
    arvore = LexborHTMLParser(html)
    titulo = arvore.css_first("title")
    texto_titulo = titulo.text() if titulo is not None else ""
    if arvore.css_first(SELETOR_GRADE_LISTAGEM) is not None:
        blocos = _blocos_listagem(arvore)
    else:
        blocos = _blocos_produto(arvore)
    corpo = "\n".join(blocos)
    return (
        "<!DOCTYPE html>\n<html><head><meta charset=\"utf-8\">"
        f"<title>{escape(texto_titulo)}</title></head>\n"
        "<!-- Recorte de uma página real da LigaMagic: só os trechos lidos pelos parsers "
        "(scripts/recortar_fixture.py). -->\n"
        f"<body>\n{corpo}\n</body></html>\n"
    )


def _resultado(funcao, *args):
    try:
        return ("ok", funcao(*args))
    except Exception as erro:  # noqa: BLE001 - compara qualquer resultado, inclusive o erro
        return ("erro", type(erro).__name__, str(erro))


def _resultados(html: str) -> dict:
    titulo = LexborHTMLParser(html).css_first("title")
    texto_titulo = titulo.text() if titulo is not None else ""
    return {
        "titulo": texto_titulo,
        "listagem": _resultado(parse_listagem, html, URL_BASE),
        "produto": _resultado(parse_produto, html),
        "desafio": eh_desafio(Pagina(url=URL_BASE, status=200, titulo=texto_titulo, html=html, headers={})),
    }


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    falhou = False
    for caminho in map(Path, sys.argv[1:]):
        original = caminho.read_text(encoding="utf-8")
        recorte = recortar(original)
        antes, depois = _resultados(original), _resultados(recorte)
        if antes != depois:
            falhou = True
            print(f"{caminho}: o recorte muda o resultado; arquivo mantido")
            for chave in antes:
                if antes[chave] != depois[chave]:
                    print(f"  {chave}: {antes[chave]!r:.200} != {depois[chave]!r:.200}")
            continue
        caminho.write_text(recorte, encoding="utf-8")
        print(f"{caminho}: {len(original):,} -> {len(recorte):,} bytes")
    sys.exit(1 if falhou else 0)


if __name__ == "__main__":
    main()
