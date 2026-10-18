"""Execuções do serviço de manutenção (backup + limpeza) e o estado vivo do serviço."""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tcg_sniper.db.models import EstadoManutencao, ExecucaoManutencao, StatusManutencao

STATUS_OK = (StatusManutencao.OK, StatusManutencao.SO_LOCAL)
MOTIVO_INTERROMPIDA = "interrompida: o serviço reiniciou no meio da execução"


def iniciar(s: Session, agora: datetime) -> ExecucaoManutencao:
    execucao = ExecucaoManutencao(inicio=agora, status=StatusManutencao.RODANDO, enviado_r2=False)
    s.add(execucao)
    s.flush()
    return execucao


def finalizar(
    s: Session,
    execucao_id: int,
    agora: datetime,
    status: StatusManutencao,
    *,
    arquivo: str | None,
    tamanho_bytes: int | None,
    enviado_r2: bool,
    apagados: dict[str, int] | None,
    erro: str | None,
) -> None:
    s.execute(
        update(ExecucaoManutencao)
        .where(ExecucaoManutencao.id == execucao_id)
        .values(
            fim=agora, status=status, arquivo=arquivo, tamanho_bytes=tamanho_bytes, enviado_r2=enviado_r2,
            apagados=apagados, erro=erro,
        )
    )
    s.flush()


def marcar_interrompidas(s: Session, agora: datetime) -> int:
    """Fecha as execuções `rodando` deixadas por um serviço que caiu no meio."""
    resultado = s.execute(
        update(ExecucaoManutencao)
        .where(ExecucaoManutencao.status == StatusManutencao.RODANDO)
        .values(status=StatusManutencao.INTERROMPIDA, fim=agora, erro=MOTIVO_INTERROMPIDA)
    )
    return resultado.rowcount


def execucoes_desde(s: Session, desde: datetime) -> list[ExecucaoManutencao]:
    """Execuções (com qualquer resultado, menos interrompida) que começaram a partir de `desde`."""
    return list(
        s.scalars(
            select(ExecucaoManutencao)
            .where(ExecucaoManutencao.inicio >= desde, ExecucaoManutencao.status != StatusManutencao.INTERROMPIDA)
            .order_by(ExecucaoManutencao.inicio)
        )
    )


def ultima_ok(s: Session) -> ExecucaoManutencao | None:
    """A execução mais recente com backup local feito e tudo certo (com ou sem cópia no R2)."""
    return s.scalar(
        select(ExecucaoManutencao)
        .where(ExecucaoManutencao.status.in_(STATUS_OK))
        .order_by(ExecucaoManutencao.inicio.desc(), ExecucaoManutencao.id.desc())
        .limit(1)
    )


def ultima(s: Session) -> ExecucaoManutencao | None:
    return s.scalar(
        select(ExecucaoManutencao).order_by(ExecucaoManutencao.inicio.desc(), ExecucaoManutencao.id.desc()).limit(1)
    )


def registrar_ciclo(s: Session, agora: datetime) -> None:
    s.execute(update(EstadoManutencao).where(EstadoManutencao.id == 1).values(ultimo_ciclo_em=agora))
    s.flush()


def ultimo_ciclo(s: Session) -> datetime | None:
    return s.scalar(select(EstadoManutencao.ultimo_ciclo_em).where(EstadoManutencao.id == 1))
