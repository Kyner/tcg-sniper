from decimal import ROUND_DOWN, Decimal

from tcg_sniper.db.models import Envio
from tcg_sniper.formatacao import formatar_brl
from tcg_sniper.oportunidades.motor import Leitura, RefLiga, desconto_pct


def _pct(valor: Decimal) -> str:
    return f"{valor.normalize():f}".replace(".", ",")


def _quem_vende(leitura: Leitura) -> str:
    if leitura.envio is Envio.AMAZON:
        return "vendido pela Amazon"
    v = leitura.vendedor
    nome = (v.nome if v else None) or "lojista"
    if v and v.pct_positivas is not None and v.num_avaliacoes is not None:
        avaliacoes = f"{v.num_avaliacoes:,}".replace(",", ".")
        nome = f"{nome} ({_pct(v.pct_positivas)}% de {avaliacoes} avaliações)"
    return f"vendido por {nome}, enviado pela Amazon"


def mensagem_oportunidade(
    *,
    nome_produto: str,
    leitura: Leitura,
    ref: RefLiga,
    url_amazon: str,
    host: str,
    produto_id: int,
    variacao: str | None = None,
) -> str:
    desconto = desconto_pct(leitura.preco, ref.preco_a_partir).quantize(Decimal(1), ROUND_DOWN)
    liga = f"Liga: a partir de {formatar_brl(ref.preco_a_partir)}"
    if ref.num_lojas is not None:
        liga += f", {ref.num_lojas} lojas"
    if ref.preco_medio is not None:
        liga += f", média de venda {formatar_brl(ref.preco_medio)}"
    amazon = f"Amazon ({variacao})" if variacao else "Amazon"
    return "\n".join(
        [
            f"Oportunidade: {nome_produto}",
            f"{amazon}: {formatar_brl(leitura.preco)} ({_quem_vende(leitura)}), {desconto}% abaixo da Liga",
            liga,
            url_amazon,
            f"Admin: http://{host}:8000/produto/{produto_id}",
        ]
    )
