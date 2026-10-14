"""Consultas das telas da Amazon no admin."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcg_sniper.db.models import Coleta, StatusColeta, TipoColeta


def ciclo_atual(s: Session) -> Coleta | None:
    return s.scalar(
        select(Coleta)
        .where(Coleta.tipo == TipoColeta.AMAZON, Coleta.status == StatusColeta.RODANDO)
        .order_by(Coleta.id.desc())
        .limit(1)
    )
