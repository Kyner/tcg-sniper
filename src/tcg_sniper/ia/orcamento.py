"""Tetos de gasto: dólares por dia e por mês e chamadas por dia (dia e mês no fuso da configuração)."""

from tcg_sniper.db.models import ConfigIA
from tcg_sniper.db.repositorio_ia import Gasto


def _usd(valor) -> str:
    return f"US$ {valor:.2f}".replace(".", ",")


def motivo_sem_orcamento(cfg: ConfigIA, g: Gasto) -> str | None:
    """None se a próxima chamada cabe nos três tetos; senão o motivo, para log, aviso e mensagem."""
    if g.dia_usd >= cfg.teto_dia_usd:
        return f"teto diário de {_usd(cfg.teto_dia_usd)} atingido"
    if g.mes_usd >= cfg.teto_mes_usd:
        return f"teto mensal de {_usd(cfg.teto_mes_usd)} atingido"
    if g.chamadas_dia >= cfg.max_chamadas_dia:
        return f"limite de {cfg.max_chamadas_dia} chamadas por dia atingido"
    return None
