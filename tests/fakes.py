from datetime import UTC, datetime
from pathlib import Path

from tcg_sniper.coletor_liga.modelos import Pagina
from tcg_sniper.db.models import ProdutoLiga
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
