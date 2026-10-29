"""Caixa "Efeito" de cada grupo de Configurações: a conta feita com os valores digitados (antes de salvar),
sobre os valores salvos dos outros campos. Valor digitado que não passa na validação do campo é trocado
pelo salvo (o erro aparece junto ao campo, não aqui). O tempo de página não é medido: a capacidade usa a
estimativa `SEGUNDOS_POR_PAGINA` do painel e o texto diz "estimativa"."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, inspect, or_, select
from sqlalchemy.orm import Session

from tcg_sniper.coletor_amazon.config import ler_hora
from tcg_sniper.configuracoes.grupos import GRUPOS, Campo, campo, grupo
from tcg_sniper.consultas.catalogo import situacao_catalogo
from tcg_sniper.consultas.painel import SEGUNDOS_POR_PAGINA, capacidade_por_hora, carga_monitor
from tcg_sniper.consultas.quase_la import quase_la
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import (
    AvaliacaoIA,
    Casamento,
    ChamadaIA,
    ConfigAmazon,
    ConfigGeral,
    ConfigIA,
    Oportunidade,
    ProdutoLiga,
    StatusCasamento,
)
from tcg_sniper.formatacao import formatar_milhar
from tcg_sniper.oportunidades.motor import Regras

Nivel = Literal["info", "aviso", "erro"]
DIAS_CUSTO_MEDIO = 7
AVISO_PCT = 80  # gasto a partir deste percentual do teto: aviso
CHAVES = frozenset(c.chave for g in GRUPOS for c in g.campos)


@dataclass(frozen=True)
class Efeito:
    linhas: tuple[str, ...]
    nivel: Nivel
    barras: tuple[tuple[str, int], ...] = ()  # (rótulo, percentual do teto), para a barra de gasto


# --- leitura dos valores digitados ------------------------------------------------------------


def _converter(c: Campo, bruto: object) -> object | None:
    """O valor digitado no tipo do campo, ou None se não passa (formato ou limites)."""
    if bruto is None:
        return None
    if c.tipo == "hora":
        return bruto if isinstance(bruto, time) else ler_hora(str(bruto).strip())
    if c.tipo == "bool":
        if isinstance(bruto, bool):
            return bruto
        texto = str(bruto).strip().lower()
        return {"sim": True, "true": True, "não": False, "false": False}.get(texto)
    if c.tipo in ("int", "decimal", "float"):
        try:
            numero = Decimal(str(bruto).strip().replace(",", "."))
        except InvalidOperation:
            return None
        if not numero.is_finite() or (c.tipo == "int" and numero != numero.to_integral_value()):
            return None
        if (c.minimo is not None and numero < c.minimo) or (c.maximo is not None and numero > c.maximo):
            return None
        return {"int": int, "float": float, "decimal": lambda n: n}[c.tipo](numero)
    return str(bruto).strip() or None


def _sobrepor(salvo, tabela: str, valores: Mapping[str, object]) -> dict[str, object]:
    """Colunas da linha salva com os valores digitados válidos da mesma tabela por cima."""
    atual = {a.key: getattr(salvo, a.key) for a in inspect(salvo).mapper.column_attrs}
    for chave, bruto in valores.items():
        if not chave.startswith(f"{tabela}.") or chave not in CHAVES:
            continue  # outra tabela, ou campo fora dos grupos (ex.: os ligados de Serviços)
        convertido = _converter(campo(chave), bruto)
        if convertido is not None:
            atual[chave.split(".", 1)[1]] = convertido
    return atual


def _amazon(s: Session, valores: Mapping[str, object]) -> ConfigAmazon:
    """Uma ConfigAmazon fora da sessão (nunca gravada) com os valores digitados."""
    dados = _sobrepor(repo_amz.obter_config(s), "amazon", valores)
    dados.pop("id")
    return ConfigAmazon(**dados)


def _ia(s: Session, agora: datetime, valores: Mapping[str, object]) -> ConfigIA:
    dados = _sobrepor(repo_ia.obter_config_ia(s, agora), "ia", valores)
    dados.pop("id")
    return ConfigIA(**dados)


def _zona(s: Session) -> ZoneInfo:
    geral = s.get(ConfigGeral, 1)
    return ZoneInfo(geral.fuso if geral is not None else "America/Sao_Paulo")


# --- formatação -------------------------------------------------------------------------------


def _decimal(valor: float, casas: int = 1) -> str:
    texto = f"{valor:.{casas}f}".replace(".", ",")
    return texto.removesuffix(",0") if casas == 1 else texto


def _usd(valor: Decimal, casas: int = 2) -> str:
    return f"US$ {valor:.{casas}f}".replace(".", ",")


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{formatar_milhar(n)} {singular if n == 1 else plural}"


def _duracao(minutos: float) -> str:
    """Duração aproximada: minutos, horas ou dias."""
    if minutos < 60:
        return f"~{max(round(minutos), 1)} min"
    if minutos < 24 * 60:
        return f"~{_decimal(minutos / 60)} h"
    return f"~{_decimal(minutos / (24 * 60))} dias"


def _pct(valor: Decimal | int, teto: Decimal | int) -> int:
    """Percentual inteiro do teto; teto zero com algo gasto (ou teto zero) conta como cheio."""
    if not teto:
        return 100
    return round(100 * Decimal(valor) / Decimal(teto))


# --- regras por grupo ---------------------------------------------------------------------------


def _oportunidades(s: Session, agora: datetime, valores: Mapping[str, object]) -> Efeito:
    cfg = _amazon(s, valores)
    minimo, piso = cfg.desconto_min_pct, cfg.quase_oportunidade_min_pct
    linhas = [f"Vira alerta a partir de {minimo}% de desconto sobre a Liga."]
    if piso >= minimo:
        linhas.append("O \"quase lá\" precisa começar abaixo do desconto mínimo.")
        return Efeito(tuple(linhas), "erro")
    abertas = s.scalar(select(func.count()).select_from(Oportunidade).where(Oportunidade.fechada_em.is_(None))) or 0
    quase = len(quase_la(s, Regras.de(cfg), piso, agora))
    linhas += [
        f"Aparece como quase lá de {piso}% a {minimo}% (na área de negócio, sem aviso).",
        (f"Agora: {_plural(abertas, 'oportunidade aberta', 'oportunidades abertas')} e "
        f"{_plural(quase, 'produto quase lá', 'produtos quase lá')} com estes valores."),
    ]
    return Efeito(tuple(linhas), "info")


def _horas_janela(inicio: time, fim: time) -> float:
    return (datetime.combine(datetime.min, fim) - datetime.combine(datetime.min, inicio)) / timedelta(hours=1)


def _busca(s: Session, agora: datetime, valores: Mapping[str, object]) -> Efeito:
    cfg = _amazon(s, valores)
    horas = _horas_janela(cfg.janela_inicio, cfg.janela_fim)
    if horas <= 0:
        return Efeito(("O fim da busca precisa ser depois do início: com esta janela, nenhuma busca roda.",), "erro")
    por_dia = round(cfg.max_buscas_hora * horas)
    catalogo = situacao_catalogo(s, agora, _zona(s))
    sem_par = catalogo.produtos_ativos - catalogo.casado
    linhas = [
        f"{formatar_milhar(por_dia)} buscas por dia ({cfg.max_buscas_hora} por hora × {_decimal(horas)} h de janela).",
    ]
    if sem_par:
        minutos = sem_par / por_dia * 24 * 60
        if minutos <= cfg.intervalo_busca_min:
            ciclo = f"a cada ~{cfg.intervalo_busca_min} min (o intervalo entre buscas do mesmo produto)"
        else:
            ciclo = f"a cada {_duracao(minutos)}"
        linhas.append(f"{_plural(sem_par, 'produto sem par', 'produtos sem par')}: cada produto sem par {ciclo}.")
    else:
        linhas.append("Nenhum produto ativo sem par agora.")
    linhas.append(f"Produtos já casados voltam à busca a cada {cfg.descoberta_casados_dias} dias.")
    return Efeito(tuple(linhas), "info")


def _monitor(s: Session, agora: datetime, valores: Mapping[str, object]) -> Efeito:
    cfg = _amazon(s, valores)
    situacao = repo_amz.situacao_monitor(s, agora, cfg)
    carga = carga_monitor(situacao.rapidos, cfg)
    linhas = [
        (f"Fila rápida: {_plural(situacao.rapidos, 'anúncio', 'anúncios')} a cada {carga.intervalo_min} min = "
        f"{formatar_milhar(carga.exigido)} páginas por hora."),
        (f"{'Mas só cabem' if carga.estoura else 'Cabem'} {formatar_milhar(carga.limite)} por hora (teto "
        f"{formatar_milhar(carga.teto)}; capacidade de {formatar_milhar(carga.capacidade)} por hora com pausas de "
        f"{cfg.pausa_min_s}–{cfg.pausa_max_s} s, estimativa)."),
    ]
    if not carga.estoura:
        return Efeito(tuple(linhas), "info")
    sugerido = carga.intervalo_sugerido_min
    linhas.append(
        f"Não cabe: cada anúncio rápido será lido a cada ~{sugerido} min, não {carga.intervalo_min}. "
        f"Para caber, usar {sugerido} min ou mais no intervalo (ou menos anúncios na fila rápida)."
    )
    return Efeito(tuple(linhas), "aviso")


def _checkout(s: Session, agora: datetime, valores: Mapping[str, object]) -> Efeito:
    cfg = _amazon(s, valores)
    a_partir = max(cfg.desconto_min_pct - cfg.margem_candidata_pp, 0)
    return Efeito((
        (f"Confere no checkout as ofertas a partir de {a_partir}% de desconto anunciado "
        f"(desconto mínimo {cfg.desconto_min_pct}% − {cfg.margem_candidata_pp} pontos)."),
        f"A conferência vale por {cfg.checkout_validade_h} h para a mesma oferta.",
    ), "info")


def _bloqueio(s: Session, agora: datetime, valores: Mapping[str, object]) -> Efeito:
    cfg = _amazon(s, valores)
    if cfg.pausa_min_s > cfg.pausa_max_s:
        return Efeito(("A pausa mínima não pode ser maior que a máxima.",), "erro")
    capacidade = capacidade_por_hora(cfg)
    media = _decimal((cfg.pausa_min_s + cfg.pausa_max_s) / 2)
    return Efeito((
        (f"Cada navegador lê até ~{formatar_milhar(capacidade)} páginas por hora (estimativa: pausa média de "
        f"{media} s + {SEGUNDOS_POR_PAGINA} s por página)."),
        f"Os dois navegadores juntos, no mesmo endereço: até ~{formatar_milhar(2 * capacidade)} páginas por hora.",
        (f"Tetos atuais: busca {formatar_milhar(cfg.max_buscas_hora)} por hora, monitor e checkout "
        f"{formatar_milhar(cfg.monitor_max_paginas_hora)} por hora."),
    ), "info")


def _ia_decide(s: Session, agora: datetime, valores: Mapping[str, object]) -> Efeito:
    cfg = _ia(s, agora, valores)
    sozinha = or_(
        and_(AvaliacaoIA.mesmo_produto.is_(True), AvaliacaoIA.confianca >= cfg.confianca_confirmar),
        and_(AvaliacaoIA.mesmo_produto.is_(False), AvaliacaoIA.confianca >= cfg.confianca_ignorar),
    )
    total, decide = s.execute(
        select(func.count(), func.count().filter(AvaliacaoIA.id.is_not(None), AvaliacaoIA.aplicada_em.is_(None), sozinha))
        .select_from(Casamento)
        .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
        .outerjoin(AvaliacaoIA, and_(
            AvaliacaoIA.anuncio_id == Casamento.anuncio_id, AvaliacaoIA.produto_id == Casamento.produto_id,
        ))
        .where(Casamento.status == StatusCasamento.PENDENTE, ProdutoLiga.ativo.is_(True))
    ).one()
    if not cfg.ligado:
        motivo, decide = "Com a IA desligada, nada é avaliado", 0
    elif not cfg.automatico:
        motivo, decide = "Com o automático desligado a IA só sugere", 0
    else:
        motivo = (
            f"A IA confirma com {cfg.confianca_confirmar}% de confiança ou mais e ignora com {cfg.confianca_ignorar}% "
            f"ou mais: pelas avaliações de hoje, decide até {_plural(decide, 'anúncio', 'anúncios')}"
        )
    return Efeito((
        f"{motivo}.",
        (f"{formatar_milhar(total - decide)} de {_plural(total, 'anúncio pendente fica', 'anúncios pendentes ficam')} "
        "para você (contando os ainda sem avaliação)."),
    ), "info")


def custo_medio(s: Session, agora: datetime) -> Decimal | None:
    """Custo médio de uma avaliação: média das chamadas de casamento ok dos últimos 7 dias (nenhuma: None)."""
    media = s.scalar(
        select(func.avg(ChamadaIA.custo_usd)).where(
            ChamadaIA.ok.is_(True), ChamadaIA.finalidade == "casamento",
            ChamadaIA.em >= agora - timedelta(days=DIAS_CUSTO_MEDIO),
        )
    )
    return None if media is None else Decimal(media)


def _ia_ritmo(s: Session, agora: datetime, valores: Mapping[str, object]) -> Efeito:
    cfg = _ia(s, agora, valores)
    por_hora = Decimal(cfg.lote * 60) / Decimal(cfg.intervalo_min)
    linhas = [
        (f"Até {formatar_milhar(round(por_hora))} avaliações por hora ({cfg.lote} a cada {cfg.intervalo_min} min), "
        "enquanto houver anúncios para avaliar."),
    ]
    medio = custo_medio(s, agora)
    if medio is None:
        linhas.append("Custo médio por avaliação: sem dado ainda.")
        return Efeito(tuple(linhas), "info")
    linhas.append(f"Custo médio por avaliação: {_usd(medio, 4)} (últimos {DIAS_CUSTO_MEDIO} dias).")
    por_hora_usd = por_hora * medio
    teto = _usd(cfg.teto_dia_usd)
    if por_hora_usd == 0 or por_hora_usd * 24 < cfg.teto_dia_usd:
        linhas.append(f"No ritmo máximo, o gasto não chega ao teto do dia ({teto}).")
        return Efeito(tuple(linhas), "info")
    minutos = float(cfg.teto_dia_usd / por_hora_usd * 60)
    linhas.append(f"No ritmo máximo, o teto do dia ({teto}) acaba em {_duracao(minutos)}.")
    return Efeito(tuple(linhas), "aviso")


def _ia_gasto(s: Session, agora: datetime, valores: Mapping[str, object]) -> Efeito:
    cfg = _ia(s, agora, valores)
    g = repo_ia.gasto(s, agora, _zona(s))
    barras = (
        ("Hoje", _pct(g.dia_usd, cfg.teto_dia_usd)),
        ("No mês", _pct(g.mes_usd, cfg.teto_mes_usd)),
        ("Chamadas hoje", _pct(g.chamadas_dia, cfg.max_chamadas_dia)),
    )
    linhas = (
        f"Hoje: {_usd(g.dia_usd)} de {_usd(cfg.teto_dia_usd)} ({barras[0][1]}%).",
        f"No mês: {_usd(g.mes_usd)} de {_usd(cfg.teto_mes_usd)} ({barras[1][1]}%).",
        f"Chamadas hoje: {formatar_milhar(g.chamadas_dia)} de {formatar_milhar(cfg.max_chamadas_dia)} ({barras[2][1]}%).",
    )
    maior = max(pct for _, pct in barras)
    nivel: Nivel = "erro" if maior >= 100 else "aviso" if maior >= AVISO_PCT else "info"
    return Efeito(linhas, nivel, barras)


REGRAS: dict[str, Callable[[Session, datetime, Mapping[str, object]], Efeito]] = {
    "oportunidades": _oportunidades,
    "busca": _busca,
    "monitor": _monitor,
    "checkout": _checkout,
    "bloqueio": _bloqueio,
    "ia-decide": _ia_decide,
    "ia-ritmo": _ia_ritmo,
    "ia-gasto": _ia_gasto,
}


def efeito(s: Session, agora: datetime, grupo_id: str, valores: Mapping[str, object]) -> Efeito | None:
    """O Efeito do grupo com os valores digitados (`"<tabela>.<campo>"` → texto ou valor). Grupo sem Efeito:
    None. Grupo desconhecido: KeyError. Só lê o banco; nada é gravado."""
    g = grupo(grupo_id)
    regra = REGRAS.get(g.id)
    return regra(s, agora, valores) if g.tem_efeito and regra is not None else None
