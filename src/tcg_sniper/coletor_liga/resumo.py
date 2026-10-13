from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from tcg_sniper.coletor_liga.modelos import Oferta


@dataclass(frozen=True)
class Resumo:
    menor_preco_com_estoque: Decimal | None
    num_vendedores_com_estoque: int
    num_ofertas: int


def calcular_resumo(ofertas: Sequence[Oferta]) -> Resumo:
    com_estoque = [o for o in ofertas if o.quantidade > 0]
    return Resumo(
        menor_preco_com_estoque=min((o.preco for o in com_estoque), default=None),
        num_vendedores_com_estoque=len({o.loja for o in com_estoque}),
        num_ofertas=len(ofertas),
    )
