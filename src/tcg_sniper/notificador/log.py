import logging

from tcg_sniper.notificador.base import Destino

log = logging.getLogger(__name__)


class LogNotificador:
    def enviar(self, destino: Destino, texto: str) -> None:
        log.info("[notificação %s] %s", destino.value, texto)
