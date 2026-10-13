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
class Pagina:
    url: str
    status: int
    html: str
    titulo: str
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ItemListagem:
    """Cartão de uma listagem de categoria da LigaMagic.

    `preco_a_partir` é o menor preço pedido AGORA ("À partir de R$ X"); `None` quando o cartão
    diz "Produto Indisponível" (sem estoque). `tipo` é o nome da categoria mostrado no cartão.
    """

    liga_id: str
    nome: str
    url: str
    preco_a_partir: Decimal | None
    tipo: str | None = None


@dataclass(frozen=True)
class PaginaExpandida:
    """Listagem depois de clicar em "Exibir mais" até acabar (ou até o limite de cliques)."""

    pagina: Pagina
    cliques: int
    limite_atingido: bool
