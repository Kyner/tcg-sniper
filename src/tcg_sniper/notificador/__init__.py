from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.config import Config
from tcg_sniper.notificador.base import Notificador
from tcg_sniper.notificador.fila import NotificadorFila

CHAVE_PADRAO = "trocar-esta-chave"


def criar_notificador(config: Config, sessoes: sessionmaker[Session]) -> Notificador:
    """Os serviços só gravam na tabela de saída; o serviço `notificador` envia (`servico.py`).
    `config` fica na assinatura para os chamadores não mudarem."""
    del config
    return NotificadorFila(sessoes)
