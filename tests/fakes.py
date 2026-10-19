from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from tcg_sniper.avisos import formato
from tcg_sniper.avisos.catalogo import CATALOGO, Dados, TipoAviso
from tcg_sniper.coletor_amazon.modelos import OfertaLista
from tcg_sniper.coletor_liga.modelos import Pagina, PaginaExpandida
from tcg_sniper.db.models import (
    AnuncioAmazon,
    Casamento,
    Envio,
    PrecoAtualLiga,
    ProdutoLiga,
    StatusCasamento,
)
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


def criar_anuncio(
    s, asin="B000000001", produto=None, status=StatusCasamento.PENDENTE, agora=T0, origem=None
) -> AnuncioAmazon:
    """Anúncio e, com `produto`, o par (anúncio, produto) com `status` e `origem`."""
    anuncio = AnuncioAmazon(
        asin=asin,
        titulo=f"Anúncio {asin}",
        url=f"https://www.amazon.com.br/dp/{asin}",
        visto_primeiro_em=agora,
        visto_ultimo_em=agora,
    )
    s.add(anuncio)
    s.flush()
    if produto is not None:
        criar_par(s, anuncio, produto, status=status, origem=origem, agora=agora)
    return anuncio


def criar_par(
    s, anuncio, produto, status=StatusCasamento.PENDENTE, origem=None, agora=T0, revisado_em=None
) -> Casamento:
    """Par (anúncio, produto) direto no banco, sem as regras do repositório (para montar cenários)."""
    par = Casamento(
        anuncio_id=anuncio.id, produto_id=produto.id, status=status, origem=origem, revisado_em=revisado_em,
        visto_primeiro_em=agora, visto_ultimo_em=agora,
    )
    s.add(par)
    s.flush()
    return par


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


DIR_FIXTURES_AMAZON = Path(__file__).parent / "fixtures" / "amazon"


def fixture_amazon(nome: str) -> str:
    return (DIR_FIXTURES_AMAZON / f"{nome}.html").read_text(encoding="utf-8")


def cartao_busca(asin: str, titulo: str, preco: str | None, patrocinado: bool = False, imagem: str | None = None) -> str:
    """Cartão de resultado da busca da Amazon. `preco` no formato da página ("R$ 599,90") ou None."""
    preco_html = f'<span class="a-price"><span class="a-offscreen">{preco}</span></span>' if preco else ""
    marca = '<span class="puis-sponsored-label-text">Patrocinado</span>' if patrocinado else ""
    img = f'<img class="s-image" src="{imagem}">' if imagem else ""
    return (
        f'<div data-component-type="s-search-result" data-asin="{asin}">'
        f"{img}<h2><span>{titulo}</span></h2>{marca}{preco_html}</div>"
    )


def html_busca(*cartoes: str) -> str:
    return f'<html><body><div class="s-main-slot">{"".join(cartoes)}</div></body></html>'


def html_produto_amazon(
    titulo: str, preco: str | None, vendido: str | None, enviado: str | None, seller_id: str | None = None,
    imagem: str | None = None,
) -> str:
    partes = [f'<span id="productTitle">{titulo}</span>']
    if preco:
        partes.append(f'<div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">{preco}</span></span></div>')
    if vendido:
        link = f'<a id="sellerProfileTriggerId" href="/gp/help/seller/at-a-glance.html?seller={seller_id}">{vendido}</a>' if seller_id else vendido
        partes.append(
            '<div offer-display-feature-name="desktop-merchant-info">'
            f'<span class="offer-display-feature-text-message">{link}</span></div>'
        )
    if enviado:
        partes.append(
            '<div offer-display-feature-name="desktop-fulfiller-info">'
            f'<span class="offer-display-feature-text-message">{enviado}</span></div>'
        )
    if imagem:
        partes.append(f'<img id="landingImage" data-old-hires="{imagem}" src="data:image/gif;base64,R0lGOD">')
    return f"<html><body>{''.join(partes)}</body></html>"


def html_vendedor(nome: str, pct: int, avaliacoes: str) -> str:
    return (
        f'<html><body><h1 id="seller-name">{nome}</h1><div id="seller-info-feedback-summary">'
        f"{pct}% positivas nos últimos 12 meses ({avaliacoes} avaliações)</div></body></html>"
    )


class TransporteFake:
    """Transporte da IA para testes: devolve (ou lança) as respostas na ordem e guarda os pedidos."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.pedidos = []

    def enviar(self, pedido):
        self.pedidos.append(pedido)
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


def oferta_lista(preco="275.91", vendedor="Shazaar", seller_id="A2SHZ", envio=Envio.FBA, posicao=1, **campos) -> OfertaLista:
    valores = {
        "posicao": posicao, "vendedor_nome": vendedor, "seller_id": seller_id, "preco": Decimal(preco),
        "preco_de": None, "condicao": "novo", "envio": envio, "origem_envio": None, "importada": False,
        "prime": False, "pct_positivas": None, "num_avaliacoes": None, "cupom": None,
    }
    valores.update(campos)
    return OfertaLista(**valores)


class NavegadorInterativoFake(NavegadorFake):
    """NavegadorFake que também clica, como o Chromium: acha o elemento no HTML da página atual
    (selectolax) e passa HTML e texto à guarda antes de registrar o clique. `apos_clique` diz a página
    seguinte: uma lista (cada clique consome a próxima) ou um dict {trecho do seletor: Pagina | lista}."""

    def __init__(self, paginas, apos_clique=None):
        super().__init__(paginas)
        self.apos_clique = apos_clique if apos_clique is not None else []
        self.cliques: list[tuple[str, int]] = []
        self.esperas: list[tuple[str, str]] = []
        self._atual = None

    def abrir(self, url):
        self._atual = super().abrir(url)
        return self._atual

    def abrir_e_esperar(self, url, seletor, timeout_ms=15_000):
        self.esperas.append((url, seletor))
        return self.abrir(url)

    def atual(self):
        return self._atual

    def _seguinte(self, seletor):
        if isinstance(self.apos_clique, list):
            resposta = self.apos_clique.pop(0)
        else:
            chave = next((trecho for trecho in self.apos_clique if trecho in seletor), None)
            if chave is None:
                raise AssertionError(f"clique sem página seguinte no teste: {seletor}")
            resposta = self.apos_clique[chave]
            if isinstance(resposta, list):
                resposta = resposta.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    def clicar(self, seletor, indice, guarda):
        # Imports locais: o bloco fica todo aqui no fim (outras tarefas também acrescentam ao arquivo).
        from selectolax.lexbor import LexborHTMLParser

        from tcg_sniper.coletor_amazon.cliques import descrever_elemento
        from tcg_sniper.navegador.modelos import ErroRede

        nos = LexborHTMLParser(self._atual.html).css(seletor) if self._atual is not None else []
        if len(nos) <= indice:
            raise ErroRede(f"elemento {seletor} [{indice}] não encontrado")
        no = nos[indice]
        guarda(*descrever_elemento(no))  # contexto e rótulo, como o JS_DESCREVER do Chromium
        self.cliques.append((seletor, indice))
        self._atual = self._seguinte(seletor)
        return self._atual


class AvisadorFake:
    """Guarda os avisos e monta o texto de cada um pelo `formato`, em modo estrito: endereço do sistema
    numa mensagem de qualquer serviço faz o teste falhar. Não agrupa (a regra de repetição é do serviço
    de avisos e tem os próprios testes)."""

    def __init__(self, host_publico: str = "host.test"):
        self._host = host_publico
        self.avisos: list[tuple[TipoAviso, str, Dados]] = []
        self.resolvidos: list[tuple[TipoAviso, str]] = []
        self.mensagens: list[tuple[Destino, str]] = []

    def avisar(self, tipo: TipoAviso, chave: str, dados: Dados) -> None:
        aviso = formato.aviso_de(tipo, dados, T0)
        texto = formato.formatar(aviso, ZoneInfo("America/Sao_Paulo"), self._host, estrito=True)
        self.avisos.append((tipo, chave, dados))
        self.mensagens.append((CATALOGO[tipo].grupo, texto))

    def resolver(self, tipo: TipoAviso, chave: str) -> None:
        self.resolvidos.append((tipo, chave))

    def resolver_todos(self, tipo: TipoAviso) -> None:
        self.resolvidos.append((tipo, "*"))

    def tipos(self) -> list[TipoAviso]:
        return [tipo for tipo, _, _ in self.avisos]

    def dados(self, tipo: TipoAviso) -> list[Dados]:
        return [d for t, _, d in self.avisos if t is tipo]
