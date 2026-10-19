"""Vigia de serviços: a batida de vida dos coletores (Liga, Amazon monitor e Amazon busca) e do casador (`sinal_servico`) e a verificação, feita
pelo serviço `manutencao` a cada minuto, que abre `SERVICO_SEM_SINAL` para serviço ativo mudo há mais de
10 min e resolve quando o sinal volta. O notificador já registra o próprio ciclo (`estado_notificador`).
Serviço pausado (manual ou por erros seguidos) é ignorado; pausado por desafio continua vigiado."""

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import Dados, TipoAviso
from tcg_sniper.avisos.formato import formatar_duracao
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    COLETOR_AMAZON_BUSCA,
    COLETOR_CASADOR,
    COLETOR_LIGA,
    COLETOR_NOTIFICADOR,
    EstadoColetorTipo,
    EstadoNotificador,
    SinalServico,
)

log = logging.getLogger(__name__)

SERVICOS = {
    COLETOR_LIGA: "coletor-liga",
    COLETOR_AMAZON: "coletor-amazon",
    COLETOR_AMAZON_BUSCA: "coletor-amazon-busca",
    COLETOR_CASADOR: "casador",
    COLETOR_NOTIFICADOR: "notificador",
}
LIMITE_SEM_SINAL = timedelta(minutes=10)
INTERVALO_BATIMENTO_S = 60


def registrar_sinal(s: Session, servico: str, agora: datetime) -> None:
    s.execute(
        pg_insert(SinalServico)
        .values(servico=servico, ultimo_em=agora)
        .on_conflict_do_update(index_elements=[SinalServico.servico], set_={"ultimo_em": agora})
    )
    s.flush()


def ultimo_sinal(s: Session, servico: str) -> datetime | None:
    if servico == COLETOR_NOTIFICADOR:
        return s.scalar(select(EstadoNotificador.ultimo_ciclo_em).where(EstadoNotificador.id == 1))
    return s.scalar(select(SinalServico.ultimo_em).where(SinalServico.servico == servico))


def _dados(nome: str, ultimo: datetime | None, agora: datetime, zona) -> Dados:
    if ultimo is None:
        quando = "nenhum desde que a vigia começou"
    else:
        quando = f"{ultimo.astimezone(zona):%d/%m %H:%M} (há {formatar_duracao(agora - ultimo)})"
    return Dados(titulo_extra=nome, linhas=(f"Último sinal: {quando}",))


def verificar(s: Session, agora: datetime, desde: datetime) -> None:
    """`desde`: quando a vigia começou (serviço sem sinal nenhum conta a partir daí). Nunca lança exceção."""
    try:
        with s.begin_nested():
            situacoes = [
                (nome, ultimo_sinal(s, coletor), repo.obter_estado(s, agora, coletor).estado)
                for coletor, nome in SERVICOS.items()
            ]
            zona, _ = avisos.zona_e_host(s)
    except Exception:
        log.exception("vigia: não consegui ler o sinal dos serviços")
        return
    for nome, ultimo, estado in situacoes:
        if estado is EstadoColetorTipo.PAUSADO:
            continue
        if agora - (ultimo or desde) > LIMITE_SEM_SINAL:
            avisos.avisar(s, TipoAviso.SERVICO_SEM_SINAL, nome, _dados(nome, ultimo, agora, zona), agora)
        else:
            avisos.resolver(s, TipoAviso.SERVICO_SEM_SINAL, nome, agora)


class Batimento:
    """Thread que registra o sinal de vida do serviço a cada `intervalo_s` enquanto o processo vive."""

    def __init__(
        self,
        sessoes: sessionmaker[Session],
        servico: str,
        relogio: Callable[[], datetime] | None = None,
        intervalo_s: float = INTERVALO_BATIMENTO_S,
    ):
        self._sessoes = sessoes
        self._servico = servico
        self._relogio = relogio or repo.agora_utc
        self._intervalo_s = intervalo_s
        self._parar = threading.Event()

    def bater(self) -> None:
        try:
            with self._sessoes() as s, s.begin():
                registrar_sinal(s, self._servico, self._relogio())
        except Exception:
            log.warning("não consegui registrar o sinal de vida de %s", self._servico, exc_info=True)

    def _laco(self) -> None:
        while True:
            self.bater()
            if self._parar.wait(self._intervalo_s):
                return

    def iniciar(self) -> threading.Thread:
        thread = threading.Thread(target=self._laco, name=f"batimento-{self._servico}", daemon=True)
        thread.start()
        return thread

    def parar(self) -> None:
        self._parar.set()
