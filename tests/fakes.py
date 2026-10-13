from datetime import UTC, datetime

from tcg_sniper.db.models import ProdutoLiga

T0 = datetime(2026, 10, 13, 13, 0, tzinfo=UTC)


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


from pathlib import Path

from tcg_sniper.coletor_liga.modelos import Pagina

DIR_FIXTURES = Path(__file__).parent / "fixtures" / "liga"


def fixture_liga(nome: str) -> str:
    return (DIR_FIXTURES / f"{nome}.html").read_text(encoding="utf-8")


def pagina_html(html, url="https://liga.test/x", titulo="LigaMagic", status=200, headers=None) -> Pagina:
    return Pagina(url=url, status=status, html=html, titulo=titulo, headers=headers or {})


class NavegadorFake:
    """Devolve páginas pré-definidas por URL. Uma lista é consumida em ordem (para testar retry)."""

    def __init__(self, paginas):
        self.paginas = paginas
        self.visitadas: list[str] = []

    def abrir(self, url: str) -> Pagina:
        self.visitadas.append(url)
        resposta = self.paginas[url]
        if isinstance(resposta, list):
            resposta = resposta.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta
