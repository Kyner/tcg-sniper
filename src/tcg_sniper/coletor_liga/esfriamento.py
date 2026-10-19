"""Esfriar depois de um desafio do Cloudflare na LigaMagic.

Tudo sai do banco: os desafios são as coletas da Liga fechadas `pausada_desafio` (tabela `coleta`) e a
espera conta da retomada (`estado_coletor.atualizado_em` da Liga). Um reinício do serviço não zera nada.

- 1º desafio do dia: depois de retomar, o job só começa `esfriar_min` minutos depois, e as pausas entre
  páginas dobram até o fim do dia.
- 2º desafio do dia: nada roda até o dia seguinte (nem "Rodar agora").
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tcg_sniper.coletor_liga.lista_do_dia import inicio_do_dia
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import Coleta, EstadoColetorTipo, StatusColeta, TipoColeta

TIPOS_LIGA = (TipoColeta.LISTAGEM, TipoColeta.PRODUTOS)


@dataclass(frozen=True)
class SituacaoDesafio:
    desafios_hoje: int
    esfriando_ate: datetime | None  # fim da espera depois da retomada; None: não está esfriando

    @property
    def parada_hoje(self) -> bool:
        """2º desafio do dia: nada roda até o dia seguinte."""
        return self.desafios_hoje >= 2

    @property
    def pausas_dobradas(self) -> bool:
        return self.desafios_hoje >= 1


def desafios_desde(s: Session, desde: datetime) -> int:
    return (
        s.scalar(
            select(func.count())
            .select_from(Coleta)
            .where(
                Coleta.tipo.in_(TIPOS_LIGA),
                Coleta.status == StatusColeta.PAUSADA_DESAFIO,
                Coleta.finalizada_em >= desde,
            )
        )
        or 0
    )


def _esfriando_ate(s: Session, agora: datetime, esfriar_min: int) -> datetime | None:
    if esfriar_min <= 0:
        return None
    ultimo = s.scalar(
        select(func.max(Coleta.finalizada_em)).where(
            Coleta.tipo.in_(TIPOS_LIGA), Coleta.status == StatusColeta.PAUSADA_DESAFIO
        )
    )
    if ultimo is None:
        return None
    voltou = s.scalar(
        select(func.count()).select_from(Coleta).where(Coleta.tipo.in_(TIPOS_LIGA), Coleta.iniciada_em > ultimo)
    )
    if voltou:
        return None  # o job já voltou depois do desafio
    estado = repo.obter_estado(s, agora)
    if estado.estado is not EstadoColetorTipo.ATIVO:
        return None  # ainda esperando alguém resolver e retomar
    fim = estado.atualizado_em + timedelta(minutes=esfriar_min)
    return fim if agora < fim else None


def situacao_desafio(s: Session, agora: datetime, fuso: ZoneInfo, esfriar_min: int) -> SituacaoDesafio:
    """Desafios desde a meia-noite no fuso e até quando esfriar. O esfriamento vale para o último desafio
    mesmo de ontem (retomado hoje); "desafios hoje" conta só desde a meia-noite."""
    return SituacaoDesafio(desafios_desde(s, inicio_do_dia(agora, fuso)), _esfriando_ate(s, agora, esfriar_min))
