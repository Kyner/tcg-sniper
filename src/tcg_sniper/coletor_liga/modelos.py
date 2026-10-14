from dataclasses import dataclass
from decimal import Decimal

from tcg_sniper.navegador.modelos import ErroRede as ErroRede  # noqa: PLC0414
from tcg_sniper.navegador.modelos import Pagina as Pagina  # noqa: PLC0414
from tcg_sniper.parsing import ErroParser as ErroParser  # noqa: PLC0414


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
