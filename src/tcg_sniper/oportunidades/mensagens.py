from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from zoneinfo import ZoneInfo

from tcg_sniper.avisos.catalogo import Dados, Negrito, TipoAviso, Trecho
from tcg_sniper.db.models import Envio, MotivoEncerramento
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


def _linha_amazon(leitura: Leitura, detalhes: Detalhes | None, variacao: str | None) -> tuple[Trecho, ...]:
    rotulo = f"Amazon ({variacao}): " if variacao else "Amazon: "
    if detalhes is None:
        return (rotulo, Negrito(formatar_brl(leitura.preco)))
    if detalhes.preco_conferido is not None:
        base = f"conferido, com impostos de {formatar_brl(detalhes.impostos)}" if detalhes.impostos is not None else "conferido"
        if detalhes.frete is None:
            frete = "frete à parte"
        elif detalhes.frete == 0:
            frete = "frete grátis"
        else:
            frete = f"frete {formatar_brl(detalhes.frete)} à parte"
        return (rotulo, Negrito(formatar_brl(detalhes.preco_conferido)), f" ({base}; {frete})")
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


ROTULOS_MOTIVO = {
    MotivoEncerramento.PRECO_SUBIU: "preço subiu",
    MotivoEncerramento.OFERTA_SUMIU: "oferta sumiu",
    MotivoEncerramento.LIGA_CAIU: "Liga baixou",
    MotivoEncerramento.VENDEDOR: "vendedor mudou",
    MotivoEncerramento.LIGA_DESATUALIZADA: "preço da Liga desatualizado",
    MotivoEncerramento.SEM_LEITURA: "anúncio sem leitura",
    MotivoEncerramento.CASAMENTO_DESFEITO: "casamento desfeito",
    MotivoEncerramento.PRODUTO_DESATIVADO: "produto desativado",  # só rótulo: este motivo nunca gera aviso
}
TECNICOS = frozenset({MotivoEncerramento.LIGA_DESATUALIZADA, MotivoEncerramento.SEM_LEITURA})


def tipo_do_encerramento(motivo: MotivoEncerramento) -> TipoAviso:
    if motivo == MotivoEncerramento.CASAMENTO_DESFEITO:
        return TipoAviso.OPORTUNIDADE_CORRIGIDA
    if motivo in TECNICOS:
        return TipoAviso.OPORTUNIDADE_ENCERRADA_TECNICO
    return TipoAviso.OPORTUNIDADE_ENCERRADA


def _duracao(inicio: datetime, fim: datetime) -> str:
    minutos = max(0, int((fim - inicio).total_seconds() // 60))
    horas, resto = divmod(minutos, 60)
    if not horas:
        return f"{resto} min"
    return f"{horas} h {resto} min" if resto else f"{horas} h"


def dados_encerramento(
    *,
    motivo: MotivoEncerramento,
    nome_produto: str,
    aberta_em: datetime,
    fechada_em: datetime,
    preco_alertado: Decimal,
    preco_atual: Decimal | None,
    preco_liga: Decimal | None,
    url_amazon: str | None,
    zona: ZoneInfo,
) -> Dados:
    """Dados dos avisos de fim da oportunidade (tipo em `tipo_do_encerramento`)."""
    desde = aberta_em.astimezone(zona).strftime("%d/%m %H:%M")
    if motivo == MotivoEncerramento.CASAMENTO_DESFEITO:
        return Dados(destaque=nome_produto, linhas=(f"O alerta de {desde} era de outro produto: desconsidere.",))
    linhas: list = [f"Durou {_duracao(aberta_em, fechada_em)} (desde {desde})"]
    if motivo not in TECNICOS:
        agora = Negrito(formatar_brl(preco_atual)) if preco_atual is not None else Negrito("indisponível")
        linhas.append(("Alerta: ", Negrito(formatar_brl(preco_alertado)), " → agora: ", agora))
        if preco_liga is not None:
            linhas.append(f"Liga: a partir de {formatar_brl(preco_liga)}")
    return Dados(
        titulo_extra=ROTULOS_MOTIVO[motivo], destaque=nome_produto, linhas=tuple(linhas),
        link_produto=url_amazon if motivo not in TECNICOS else None,
    )
