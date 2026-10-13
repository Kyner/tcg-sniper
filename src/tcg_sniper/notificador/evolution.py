import logging
import time
from collections.abc import Callable

import httpx

from tcg_sniper.notificador.base import Destino

log = logging.getLogger(__name__)


class EvolutionNotificador:
    def __init__(
        self,
        url: str,
        api_key: str,
        instancia: str,
        grupos: dict[Destino, str],
        cliente: httpx.Client | None = None,
        dormir: Callable[[float], None] = time.sleep,
        tentativas: int = 3,
    ):
        self._endpoint = f"{url.rstrip('/')}/message/sendText/{instancia}"
        self._api_key = api_key
        self._grupos = grupos
        self._cliente = cliente or httpx.Client(timeout=15)
        self._dormir = dormir
        self._tentativas = tentativas

    def enviar(self, destino: Destino, texto: str) -> None:
        grupo = self._grupos.get(destino)
        if not grupo:
            log.warning("sem grupo configurado para %s; mensagem descartada: %s", destino.value, texto)
            return
        for tentativa in range(1, self._tentativas + 1):
            try:
                resposta = self._cliente.post(
                    self._endpoint,
                    headers={"apikey": self._api_key},
                    json={"number": grupo, "text": texto},
                )
                resposta.raise_for_status()
                return
            except Exception as erro:  # envio nunca pode interromper a coleta
                log.warning("envio para %s falhou (tentativa %d): %s", destino.value, tentativa, erro)
                if tentativa < self._tentativas:
                    self._dormir(2 ** (tentativa - 1))
        log.error("desisti de enviar para %s: %s", destino.value, texto)
