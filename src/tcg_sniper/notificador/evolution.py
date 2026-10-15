import logging
import time
from collections.abc import Callable
from urllib.parse import quote

import httpx

from tcg_sniper.notificador.base import Destino

log = logging.getLogger(__name__)


class EvolutionNotificador:
    """Envia texto pela Evolution API. A instância e os grupos são lidos a cada envio (`destinos`),
    para que o que for salvo na tela de Configurações valha na mensagem seguinte."""

    def __init__(
        self,
        url: str,
        api_key: str,
        destinos: Callable[[], tuple[str | None, dict[Destino, str]]],
        cliente: httpx.Client | None = None,
        dormir: Callable[[float], None] = time.sleep,
        tentativas: int = 3,
    ):
        self._url = url.rstrip("/")
        self._api_key = api_key
        self._destinos = destinos
        self._cliente = cliente or httpx.Client(timeout=15)
        self._dormir = dormir
        self._tentativas = tentativas

    def enviar(self, destino: Destino, texto: str) -> None:
        try:
            instancia, grupos = self._destinos()
        except Exception:  # envio nunca pode interromper a coleta
            log.exception("não consegui ler a configuração do WhatsApp; mensagem descartada: %s", texto)
            return
        if not instancia:
            log.warning("sem instância da Evolution configurada; mensagem descartada: %s", texto)
            return
        grupo = grupos.get(destino)
        if not grupo:
            log.warning("sem grupo configurado para %s; mensagem descartada: %s", destino.value, texto)
            return
        endpoint = f"{self._url}/message/sendText/{quote(instancia, safe='')}"
        for tentativa in range(1, self._tentativas + 1):
            try:
                resposta = self._cliente.post(
                    endpoint,
                    headers={"apikey": self._api_key},
                    json={"number": grupo, "text": texto},
                )
                resposta.raise_for_status()
                return
            except Exception as erro:  # noqa: BLE001 - envio nunca pode interromper a coleta
                log.warning("envio para %s falhou (tentativa %d): %s", destino.value, tentativa, erro)
                if tentativa < self._tentativas:
                    self._dormir(2 ** (tentativa - 1))
        log.error("desisti de enviar para %s: %s", destino.value, texto)
