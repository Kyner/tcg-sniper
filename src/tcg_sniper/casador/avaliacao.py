"""Avaliação da IA contra os casamentos já decididos pelo usuário: acerto, erros e custo, sem mudar nada."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.casador.pergunta import Veredito, avaliar_par
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.ia.modelos import ChaveInvalida, ConfiguracaoInvalida, ErroIA, SemOrcamento, Transporte

FAIXAS = (("90+", 90), ("75–89", 75), ("50–74", 50), ("<50", 0))


def faixa(confianca: int) -> str:
    return next(rotulo for rotulo, minimo in FAIXAS if confianca >= minimo)


@dataclass(frozen=True)
class Erro:
    asin: str
    titulo: str
    produto: str
    esperado_mesmo: bool
    veredito: Veredito


@dataclass
class ResultadoModelo:
    modelo: str
    total: int = 0
    acertos: int = 0
    falsos_sim: int = 0
    falsos_nao: int = 0
    falhas: int = 0
    custo_usd: Decimal = Decimal(0)
    tokens_entrada: int = 0
    tokens_saida: int = 0
    faixas: dict[str, tuple[int, int]] = field(default_factory=lambda: {rotulo: (0, 0) for rotulo, _ in FAIXAS})
    erros: list[Erro] = field(default_factory=list)
    interrompida: str | None = None


def avaliar(
    sessoes: sessionmaker[Session],
    transporte: Transporte,
    cliente_http: httpx.Client,
    modelos: Sequence[str],
    limite: int | None,
    zona: ZoneInfo,
    relogio: Callable[[], datetime],
    preco_entrada: Decimal | None = None,
    preco_saida: Decimal | None = None,
) -> list[ResultadoModelo]:
    """Os preços informados (US$ por milhão de tokens) substituem os de Configurações → IA no custo."""
    with sessoes() as s:
        decididos = repo_ia.pares_decididos(s, limite)
        vistos: set[int] = set()
        for d in decididos:
            for objeto in (d.anuncio, d.produto):
                if id(objeto) not in vistos:
                    vistos.add(id(objeto))
                    s.expunge(objeto)
    resultados = []
    for modelo in modelos:
        r = ResultadoModelo(modelo)
        for d in decididos:
            try:
                veredito, resposta, _ = avaliar_par(
                    sessoes, transporte, cliente_http, d.anuncio, d.produto, d.preco_liga, d.preco_amazon,
                    finalidade="avaliacao", zona=zona, modelo=modelo, preco_entrada=preco_entrada,
                    preco_saida=preco_saida, relogio=relogio,
                )
            except (SemOrcamento, ChaveInvalida, ConfiguracaoInvalida) as erro:
                r.interrompida = str(erro)
                break
            except ErroIA:
                r.falhas += 1
                continue
            r.total += 1
            r.custo_usd += resposta.custo_usd
            r.tokens_entrada += resposta.tokens_entrada
            r.tokens_saida += resposta.tokens_saida
            certo = veredito.mesmo_produto == d.confirmado
            acertos, total = r.faixas[faixa(veredito.confianca)]
            r.faixas[faixa(veredito.confianca)] = (acertos + certo, total + 1)
            if certo:
                r.acertos += 1
                continue
            if veredito.mesmo_produto:
                r.falsos_sim += 1
            else:
                r.falsos_nao += 1
            r.erros.append(Erro(d.anuncio.asin, d.anuncio.titulo_exibicao, d.produto.nome, d.confirmado, veredito))
        resultados.append(r)
    return resultados


def _usd_milhao(valor: Decimal) -> str:
    return f"US$ {valor:.2f}".replace(".", ",") + " por milhão"


def rotulo_precos(preco_entrada: Decimal | None, preco_saida: Decimal | None) -> str:
    if preco_entrada is None and preco_saida is None:
        return "com os preços de Configurações → IA"
    entrada = _usd_milhao(preco_entrada) if preco_entrada is not None else "de Configurações → IA"
    saida = _usd_milhao(preco_saida) if preco_saida is not None else "de Configurações → IA"
    return f"com os preços informados: entrada {entrada}, saída {saida}"


def relatorio_markdown(
    resultados: Sequence[ResultadoModelo],
    gerado_em: datetime,
    preco_entrada: Decimal | None = None,
    preco_saida: Decimal | None = None,
) -> str:
    rotulo = rotulo_precos(preco_entrada, preco_saida)
    linhas = [f"# Avaliação da IA no casamento ({gerado_em:%Y-%m-%d %H:%M} UTC)", ""]
    for r in resultados:
        linhas += [
            f"## {r.modelo}",
            "",
            f"- Acertos: {r.acertos} de {r.total}" + (f" ({100 * r.acertos / r.total:.0f}%)" if r.total else ""),
            f"- Falsos \"sim\": {r.falsos_sim} (a IA diria mesmo produto num anúncio que você ignorou: risco de oportunidade falsa)",
            f"- Falsos \"não\": {r.falsos_nao}",
            f"- Falhas de chamada: {r.falhas}",
            f"- Tokens: {r.tokens_entrada} de entrada, {r.tokens_saida} de saída",
            f"- Custo: US$ {r.custo_usd:.4f}" + (f" (médio US$ {r.custo_usd / r.total:.4f})" if r.total else "") + f", {rotulo}",
        ]
        if r.interrompida:
            linhas.append(f"- Interrompida: {r.interrompida}")
        linhas += ["", "| Confiança | Acertos |", "|---|---|"]
        linhas += [f"| {rotulo} | {a} de {t} |" for rotulo, (a, t) in r.faixas.items()]
        if r.erros:
            linhas += ["", "### Erros", "", "| ASIN | Anúncio | Produto da Liga | Você decidiu | IA | Motivo da IA |", "|---|---|---|---|---|---|"]
            for e in r.erros:
                decidiu = "mesmo produto" if e.esperado_mesmo else "ignorado"
                ia = f"{'mesmo' if e.veredito.mesmo_produto else 'outro'} {e.veredito.confianca}%"
                linhas.append(f"| {e.asin} | {_celula(e.titulo)} | {_celula(e.produto)} | {decidiu} | {ia} | {_celula(e.veredito.motivo)} |")
        linhas.append("")
    return "\n".join(linhas)


def _celula(texto: str) -> str:
    return texto.replace("|", "/").replace("\n", " ")
