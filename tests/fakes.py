from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from tcg_sniper.coletor_liga.modelos import Pagina, PaginaExpandida
from tcg_sniper.db.models import AnuncioAmazon, PrecoAtualLiga, ProdutoLiga, StatusCasamento
from tcg_sniper.notificador.base import Destino

T0 = datetime(2026, 10, 13, 13, 0, tzinfo=UTC)
DIR_FIXTURES = Path(__file__).parent / "fixtures" / "liga"


def criar_produto(s, liga_id="p1", ativo=True, agora=T0, nome=None, url=None) -> ProdutoLiga:
    produto = ProdutoLiga(
        liga_id=liga_id,
        nome=nome or f"Produto {liga_id}",
        url=url or f"https://liga.test/produto/{liga_id}",
        ativo=ativo,
        visto_primeiro_em=agora,
        visto_ultimo_em=agora,
    )
    s.add(produto)
    s.flush()
    return produto


class NotificadorFake:
    def __init__(self):
        self.mensagens: list[tuple[Destino, str]] = []

    def enviar(self, destino: Destino, texto: str) -> None:
        self.mensagens.append((destino, texto))


def fixture_liga(nome: str) -> str:
    return (DIR_FIXTURES / f"{nome}.html").read_text(encoding="utf-8")


def pagina_html(html, url="https://liga.test/x", titulo="LigaMagic", status=200, headers=None) -> Pagina:
    return Pagina(url=url, status=status, html=html, titulo=titulo, headers=headers or {})


def cartao_listagem(pcode: str, nome: str, preco: str | None, categoria: str = "Caixas de Boosters") -> str:
    """Cartão no formato real da listagem (copiado de catalogo_pagina_1). `preco=None` = indisponível."""
    if preco is None:
        classe, bloco_preco = "card item-out-of-stock", '<div class="price-out-of-stock">Produto Indisponível</div>'
    else:
        classe = "card"
        bloco_preco = (
            '<div class="price-range-container gap-1 mt-auto"><p class="label-apartir">À partir de</p>'
            f'<p class="smallest-price"> {preco}</p></div>'
        )
    href = f"/?view=prod/view&amp;pcode={pcode}&amp;prod={nome}"
    return (
        f'<div class="{classe}"><div class="p-3 card-lg gap-3">'
        f'<h5 class="card-title text-center"><a href="{href}">\n    {nome}\n</a></h5>'
        f"{bloco_preco}"
        '<div class="card-bottom"><p class="card-section">em '
        f'<a href="/?view=cards%2Fsearch&amp;card=categ%3D10+searchprod%3D1&amp;tipo=1">{categoria}</a>'
        "</p></div></div></div>"
    )


def html_listagem(*cartoes: str) -> str:
    return (
        '<html><body><div class="mt-4 categoria">'
        '<div class="mt-2 grid categoria__card-container mtg-linhas">'
        + "".join(cartoes)
        + '</div></div><div id="exibir_mais_cards"><input type="button" value="Exibir mais" class="exibir-mais"></div>'
        "</body></html>"
    )


class NavegadorFake:
    """Devolve páginas pré-definidas por URL. Uma lista é consumida em ordem (para testar retry).

    Em `abrir_expandindo`, um valor `Pagina` vira `PaginaExpandida(pagina, 0, False)`; um
    `PaginaExpandida` é devolvido como está, depois de chamar `pausar()` uma vez por clique.
    """

    def __init__(self, paginas):
        self.paginas = paginas
        self.visitadas: list[str] = []
        self.expandidas: list[tuple[str, int]] = []
        self.morto = False

    def vivo(self) -> bool:
        return not self.morto

    def _proxima(self, url: str):
        self.visitadas.append(url)
        resposta = self.paginas[url]
        if isinstance(resposta, list):
            resposta = resposta.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    def abrir(self, url: str) -> Pagina:
        return self._proxima(url)

    def abrir_expandindo(self, url, max_cliques, pausar) -> PaginaExpandida:
        self.expandidas.append((url, max_cliques))
        resposta = self._proxima(url)
        if isinstance(resposta, Pagina):
            return PaginaExpandida(resposta, 0, False)
        for _ in range(resposta.cliques):
            pausar()
        return resposta


def criar_anuncio(s, asin="B000000001", produto=None, status=StatusCasamento.PENDENTE, agora=T0) -> AnuncioAmazon:
    anuncio = AnuncioAmazon(
        asin=asin,
        titulo=f"Anúncio {asin}",
        url=f"https://www.amazon.com.br/dp/{asin}",
        produto_id=produto.id if produto is not None else None,
        status_casamento=status,
        visto_primeiro_em=agora,
        visto_ultimo_em=agora,
    )
    s.add(anuncio)
    s.flush()
    return anuncio


def criar_preco_liga(s, produto, preco, listagem_em=T0, num_lojas=None, preco_medio=None) -> PrecoAtualLiga:
    atual = PrecoAtualLiga(
        produto_id=produto.id,
        preco_a_partir=None if preco is None else Decimal(preco),
        listagem_em=listagem_em,
        num_lojas=num_lojas,
        preco_medio=None if preco_medio is None else Decimal(preco_medio),
    )
    s.add(atual)
    s.flush()
    return atual
