"""Tabela de saída do WhatsApp (`mensagem_saida`) e o estado do serviço notificador."""

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from tcg_sniper.db.models import EstadoNotificador, MensagemSaida, StatusMensagem

RESOLVIDAS = (StatusMensagem.ENVIADA, StatusMensagem.EXPIRADA, StatusMensagem.DESCARTADA)
REENVIAVEIS = (StatusMensagem.FALHA, StatusMensagem.EXPIRADA)
DESCARTAVEIS = (StatusMensagem.PENDENTE, StatusMensagem.FALHA, StatusMensagem.EXPIRADA)


class MensagemNaoEncontrada(Exception):
    pass


class AcaoInvalida(Exception):
    """A ação não vale para a situação atual da mensagem (ex.: reenviar uma já enviada)."""


def enfileirar(s: Session, destino: str, texto: str, agora: datetime) -> MensagemSaida:
    mensagem = MensagemSaida(
        destino=destino,
        texto=texto,
        status=StatusMensagem.PENDENTE,
        tentativas=0,
        proxima_tentativa_em=agora,
        ignorar_validade=False,
        criada_em=agora,
        atualizado_em=agora,
    )
    s.add(mensagem)
    s.flush()
    return mensagem


def lote_pendente(s: Session, agora: datetime, limite: int = 20) -> list[MensagemSaida]:
    """Pendentes vencidas, das mais antigas, travadas para esta transação. Linhas travadas por
    outra transação são puladas (`SKIP LOCKED`), então dois envios nunca pegam a mesma."""
    consulta = (
        select(MensagemSaida)
        .where(MensagemSaida.status == StatusMensagem.PENDENTE, MensagemSaida.proxima_tentativa_em <= agora)
        .order_by(MensagemSaida.criada_em, MensagemSaida.id)
        .limit(limite)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    return list(s.scalars(consulta))


def acordar_pendentes(s: Session, agora: datetime, antes_de: datetime) -> int:
    """Pendentes que esperam o backoff de uma falha transitória voltam para agora (a Evolution
    respondeu). Ficam como estão: as sem tentativas (esperando configuração), as recusadas com 4xx
    (o problema é a instância ou o grupo) e as que falharam a partir de `antes_de` (neste ciclo)."""
    resultado = s.execute(
        update(MensagemSaida)
        .where(
            MensagemSaida.status == StatusMensagem.PENDENTE,
            MensagemSaida.tentativas > 0,
            MensagemSaida.proxima_tentativa_em > agora,
            MensagemSaida.atualizado_em < antes_de,
            ~func.coalesce(MensagemSaida.ultimo_erro, "").startswith("HTTP 4"),
        )
        .values(proxima_tentativa_em=agora, atualizado_em=agora)
    )
    return resultado.rowcount


def registrar_ciclo(s: Session, agora: datetime) -> None:
    s.execute(update(EstadoNotificador).where(EstadoNotificador.id == 1).values(ultimo_ciclo_em=agora))
    s.flush()


def limpar_antigas(s: Session, agora: datetime, dias: int = 30) -> int:
    """Apaga enviadas, expiradas e descartadas criadas há mais de `dias`. Falhas e pendentes ficam."""
    resultado = s.execute(
        delete(MensagemSaida).where(
            MensagemSaida.status.in_(RESOLVIDAS), MensagemSaida.criada_em < agora - timedelta(days=dias)
        )
    )
    return resultado.rowcount


def _obter(s: Session, mensagem_id: int) -> MensagemSaida:
    mensagem = s.get(MensagemSaida, mensagem_id, with_for_update=True, populate_existing=True)
    if mensagem is None:
        raise MensagemNaoEncontrada(mensagem_id)
    return mensagem


def reenviar(s: Session, mensagem_id: int, agora: datetime) -> None:
    """Falha ou expirada volta para a fila agora, sem tentativas e ignorando a validade."""
    mensagem = _obter(s, mensagem_id)
    if mensagem.status not in REENVIAVEIS:
        raise AcaoInvalida(f"não dá para reenviar uma mensagem {mensagem.status.value}")
    mensagem.status = StatusMensagem.PENDENTE
    mensagem.tentativas = 0
    mensagem.proxima_tentativa_em = agora
    mensagem.ignorar_validade = True
    mensagem.ultimo_erro = None
    mensagem.atualizado_em = agora
    s.flush()


def descartar(s: Session, mensagem_id: int, agora: datetime) -> None:
    mensagem = _obter(s, mensagem_id)
    if mensagem.status not in DESCARTAVEIS:
        raise AcaoInvalida(f"não dá para descartar uma mensagem {mensagem.status.value}")
    mensagem.status = StatusMensagem.DESCARTADA
    mensagem.atualizado_em = agora
    s.flush()
