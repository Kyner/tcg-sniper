import logging
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.notificador.base import Destino

log = logging.getLogger(__name__)


class NotificadorFila:
    """Grava a mensagem na tabela de saída; quem envia é o serviço `notificador`."""

    def __init__(self, sessoes: sessionmaker[Session], relogio: Callable[[], datetime] | None = None):
        self._sessoes = sessoes
        self._relogio = relogio or repo.agora_utc

    def enviar(self, destino: Destino, texto: str) -> None:
        try:
            with self._sessoes() as s, s.begin():
                repo_msg.enfileirar(s, destino.value, texto, self._relogio())
        except Exception:  # notificar nunca pode interromper quem chamou
            log.exception("não consegui gravar a mensagem para %s; ela se perdeu: %s", destino.value, texto)
