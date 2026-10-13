from dataclasses import dataclass, field
from decimal import Decimal


class ErroParser(Exception):
    """HTML não tem a estrutura esperada (provável mudança de layout)."""


class ErroRede(Exception):
    """Falha de navegação: timeout, conexão, DNS."""


@dataclass(frozen=True)
class Resumo:
    """Quadro de preços da página de produto ("Preço Médio de Venda no Marketplace") + nº de lojas.

    Os preços vêm do resumo textual da LigaMagic (os preços por oferta são ofuscados em
    sprite e não são lidos). `None` quando a página não mostra o quadro.
    """

    preco_min: Decimal | None
    preco_medio: Decimal | None
    preco_max: Decimal | None
    num_lojas: int


@dataclass(frozen=True)
class ItemCatalogo:
    liga_id: str
    nome: str
    url: str
    edicao: str | None = None
    tipo: str | None = None
    idioma: str | None = None


@dataclass(frozen=True)
class PaginaCatalogo:
    itens: list[ItemCatalogo]
    proxima_url: str | None


@dataclass(frozen=True)
class Pagina:
    url: str
    status: int
    html: str
    titulo: str
    headers: dict[str, str] = field(default_factory=dict)
