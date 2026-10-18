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
    imagem_url: str | None = None


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
    imagem_url: str | None = None


@dataclass(frozen=True)
class AvaliacaoVendedor:
    seller_id: str
    nome: str | None
    pct_positivas: Decimal | None
    num_avaliacoes: int | None


@dataclass(frozen=True)
class OfertaLista:
    """Uma oferta do painel "Outras opções de compra". `posicao` 0 = a oferta em destaque
    (#aod-pinned-offer); 1.. = a ordem dos blocos #aod-offer (é o que o clique usa)."""

    posicao: int
    vendedor_nome: str | None
    seller_id: str | None  # "amazon" quando vendida pela Amazon
    preco: Decimal
    preco_de: Decimal | None
    condicao: str  # "novo" | "usado" | o texto do painel
    envio: Envio
    origem_envio: str | None  # "Estados Unidos"; None quando o painel não diz
    importada: bool
    prime: bool
    pct_positivas: Decimal | None  # avaliação do vendedor mostrada no painel
    num_avaliacoes: int | None
    cupom: str | None  # desconto condicional, só informativo
