from enum import StrEnum
from typing import Protocol


class Destino(StrEnum):
    ADMIN = "admin"
    OPORTUNIDADES = "oportunidades"


class Notificador(Protocol):
    def enviar(self, destino: Destino, texto: str) -> None:
        """Envia a mensagem. Nunca lança exceção: falhas são registradas em log."""
