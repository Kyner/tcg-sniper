from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from tcg_sniper.avisos.catalogo import Dados, Negrito, Trecho
from tcg_sniper.db.models import Envio
from tcg_sniper.formatacao import formatar_brl
from tcg_sniper.oportunidades.motor import Leitura, RefLiga, desconto_pct

PAISES_CURTOS = {"Estados Unidos": "EUA", "Estados Unidos da América": "EUA"}


@dataclass(frozen=True)
class Detalhes:
    """O que a lista de ofertas e a conferência de checkout acrescentam à mensagem."""

    # Itens + impostos do checkout, SEM o frete (regra do usuário); None = não conferido.
    preco_conferido: Decimal | None = None
    impostos: Decimal | None = None  # já incluídos em preco_conferido
    frete: Decimal | None = None  # fora do preço: só aparece à parte
    motivo_nao_conferido: str | None = None
    importada: bool = False
    origem_envio: str | None = None
    prime: bool = False
    cupom: str | None = None  # desconto condicional: só informação


def _preco(leitura: Leitura, detalhes: Detalhes | None) -> str:
    if detalhes is None:
        return formatar_brl(leitura.preco)
    if detalhes.preco_conferido is not None:
        partes = [f"{formatar_brl(detalhes.preco_conferido)}, preço conferido (sem frete)"]
        if detalhes.impostos is not None:
            partes.append(f"impostos {formatar_brl(detalhes.impostos)} inclusos")
        if detalhes.frete is not None:
            partes.append(f"frete {formatar_brl(detalhes.frete)} à parte")
        return ", ".join(partes)
    motivo = detalhes.motivo_nao_conferido or "aguardando conferência"
    return f"{formatar_brl(leitura.preco)}, preço anunciado, não conferido ({motivo})"


def _selos(detalhes: Detalhes | None) -> str:
    if detalhes is None:
        return ""
    selos = []
    if detalhes.importada:
        origem = PAISES_CURTOS.get(detalhes.origem_envio or "", detalhes.origem_envio)
        selos.append(f"importado ({origem})" if origem else "importado")
    if detalhes.prime:
        selos.append("Prime")
    return "".join(f" · {selo}" for selo in selos)


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
    detalhes: Detalhes | None = None,
) -> str:
    desconto = desconto_pct(leitura.preco, ref.preco_a_partir).quantize(Decimal(1), ROUND_DOWN)
    liga = f"Liga: a partir de {formatar_brl(ref.preco_a_partir)}"
    if ref.num_lojas is not None:
        liga += f", {ref.num_lojas} lojas"
    if ref.preco_medio is not None:
        liga += f", média de venda {formatar_brl(ref.preco_medio)}"
    amazon = f"Amazon ({variacao})" if variacao else "Amazon"
    linhas = [
        f"Oportunidade: {nome_produto}",
        f"{amazon}: {_preco(leitura, detalhes)} ({_quem_vende(leitura)}{_selos(detalhes)}), {desconto}% abaixo da Liga",
    ]
    if detalhes is not None and detalhes.cupom:
        linhas.append(f"Cupom: {detalhes.cupom} (condicional, não descontado)")
    linhas += [liga, url_amazon, f"Admin: http://{host}:8000/produto/{produto_id}"]
    return "\n".join(linhas)


def _linha_amazon(leitura: Leitura, detalhes: Detalhes | None, variacao: str | None) -> tuple[Trecho, ...]:
    rotulo = f"Amazon ({variacao}): " if variacao else "Amazon: "
    if detalhes is None:
        return (rotulo, Negrito(formatar_brl(leitura.preco)))
    if detalhes.preco_conferido is not None:
        impostos = f" de {formatar_brl(detalhes.impostos)}" if detalhes.impostos is not None else ""
        if detalhes.frete is None:
            frete = "frete à parte"
        elif detalhes.frete == 0:
            frete = "frete grátis"
        else:
            frete = f"frete {formatar_brl(detalhes.frete)} à parte"
        return (rotulo, Negrito(formatar_brl(detalhes.preco_conferido)), f" (conferido, com impostos{impostos}; {frete})")
    motivo = detalhes.motivo_nao_conferido or "aguardando conferência"
    return (rotulo, Negrito(formatar_brl(leitura.preco)), f" (anunciado, sem impostos; não conferido: {motivo})")


def _linha_vendedor(leitura: Leitura, detalhes: Detalhes | None) -> str:
    if leitura.envio is Envio.AMAZON:
        texto = "Vendido por: Amazon"
    else:
        v = leitura.vendedor
        nome = (v.nome if v else None) or "lojista"
        if v and v.pct_positivas is not None and v.num_avaliacoes is not None:
            avaliacoes = f"{v.num_avaliacoes:,}".replace(",", ".")
            nome = f"{nome} ({_pct(v.pct_positivas)}% de {avaliacoes} avaliações)"
        texto = f"Vendido por: {nome} · enviado pela Amazon"
    return texto + _selos(detalhes)


def dados_oportunidade(
    *,
    nome_produto: str,
    leitura: Leitura,
    ref: RefLiga,
    url_amazon: str,
    variacao: str | None = None,
    detalhes: Detalhes | None = None,
) -> Dados:
    """Dados do aviso `OPORTUNIDADE` (grupo de oportunidades). Com conferência vale o preço conferido
    (itens + impostos, sem o frete, que aparece à parte); sem ela, o anunciado, sem impostos."""
    desconto = desconto_pct(leitura.preco, ref.preco_a_partir).quantize(Decimal(1), ROUND_DOWN)
    liga = f"Liga: a partir de {formatar_brl(ref.preco_a_partir)}"
    if ref.num_lojas is not None:
        liga += f" · {ref.num_lojas} lojas"
    if ref.preco_medio is not None:
        liga += f" · média {formatar_brl(ref.preco_medio)}"
    linhas: list = [_linha_amazon(leitura, detalhes, variacao), _linha_vendedor(leitura, detalhes), liga]
    if detalhes is not None and detalhes.cupom:
        linhas.append(f"Cupom: {detalhes.cupom} (condicional, não descontado)")
    return Dados(
        titulo_extra=f"{desconto}% abaixo da Liga", destaque=nome_produto, linhas=tuple(linhas), link_produto=url_amazon
    )
