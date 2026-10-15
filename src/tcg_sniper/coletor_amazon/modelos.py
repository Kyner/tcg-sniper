from dataclasses import dataclass
from decimal import Decimal

from tcg_sniper.db.models import Envio

SELLER_AMAZON = "amazon"  # seller_id da própria Amazon (linha fixa em vendedor_amazon)


@dataclass(frozen=True)
class ResultadoBusca:
    """Cartão do resultado de busca. `preco` None quando o cartão não mostra preço (nunca zero)."""

    asin: str
    titulo: str
    url: str
    preco: Decimal | None
    patrocinado: bool


@dataclass(frozen=True)
class OfertaProduto:
    """Oferta principal da página do produto. `seller_id` é "amazon" quando vendido pela Amazon."""

    asin: str
    titulo: str
    preco: Decimal | None
    vendido_por: str | None
    seller_id: str | None
    envio: Envio
    # Opção escolhida no seletor de variações ("Collector Booster Box"); None sem seletor.
    variacao: str | None = None


@dataclass(frozen=True)
class AvaliacaoVendedor:
    seller_id: str
    nome: str | None
    pct_positivas: Decimal | None
    num_avaliacoes: int | None
