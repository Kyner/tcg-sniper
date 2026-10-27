"""Vigia de serviços: a batida de vida dos coletores (Liga, Amazon monitor e Amazon busca) e do casador (`sinal_servico`) e a verificação, feita
pelo serviço `manutencao` a cada minuto, que abre `SERVICO_SEM_SINAL` para serviço ativo mudo há mais de
10 min e resolve quando o sinal volta. O notificador já registra o próprio ciclo (`estado_notificador`).
A batida sai de dentro do laço de trabalho (cada passo, cada página, cada fatia de espera): um laço ou
navegador travado deixa de bater e dispara o aviso. Desligamento limpo (SIGTERM, `docker stop`) grava
`encerrado_em` e o serviço fica fora da vigia até bater de novo; queda sem SIGTERM continua avisando.
Serviço pausado (manual ou por erros seguidos) é ignorado; pausado por desafio continua vigiado."""

import logging
import time
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
FATIA_ESPERA_S = 60  # espera longa bate a cada fatia desta duração (o limite é de 10 min)


def registrar_sinal(s: Session, servico: str, agora: datetime) -> None:
    s.execute(
        pg_insert(SinalServico)
        .values(servico=servico, ultimo_em=agora)
        .on_conflict_do_update(index_elements=[SinalServico.servico], set_={"ultimo_em": agora, "encerrado_em": None})
    )
    s.flush()


def registrar_encerramento(s: Session, servico: str, agora: datetime) -> None:
    """Desligamento limpo: a vigia ignora o serviço até o próximo sinal (a batida seguinte apaga a marca)."""
    s.execute(
        pg_insert(SinalServico)
        .values(servico=servico, ultimo_em=agora, encerrado_em=agora)  # ultimo_em só vale se a linha não existia
        .on_conflict_do_update(index_elements=[SinalServico.servico], set_={"encerrado_em": agora})
    )
    s.flush()


def _encerrado_em(s: Session, servico: str) -> datetime | None:
    return s.scalar(select(SinalServico.encerrado_em).where(SinalServico.servico == servico))


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
                (
                    nome,
                    ultimo_sinal(s, coletor),
                    repo.obter_estado(s, agora, coletor).estado,
                    _encerrado_em(s, coletor),
                )
                for coletor, nome in SERVICOS.items()
            ]
            zona, _ = avisos.zona_e_host(s)
    except Exception:
        log.exception("vigia: não consegui ler o sinal dos serviços")
        return
    for nome, ultimo, estado, encerrado in situacoes:
        if estado is EstadoColetorTipo.PAUSADO:
            continue
        if encerrado is not None and (ultimo is None or encerrado >= ultimo):
            avisos.resolver(s, TipoAviso.SERVICO_SEM_SINAL, nome, agora)  # parado de propósito: nada a avisar
            continue
        if agora - (ultimo or desde) > LIMITE_SEM_SINAL:
            avisos.avisar(s, TipoAviso.SERVICO_SEM_SINAL, nome, _dados(nome, ultimo, agora, zona), agora)
        else:
            avisos.resolver(s, TipoAviso.SERVICO_SEM_SINAL, nome, agora)


class Batimento:
    """Registra o sinal de vida do serviço. Quem chama é o próprio laço de trabalho (`bater`), nunca uma
    thread à parte: assim a batida prova que o laço anda, não só que o processo vive."""

    def __init__(
        self,
        sessoes: sessionmaker[Session],
        servico: str,
        relogio: Callable[[], datetime] | None = None,
    ):
        self._sessoes = sessoes
        self._servico = servico
        self._relogio = relogio or repo.agora_utc

    def bater(self) -> None:
        """Falha ao gravar é logada e nunca derruba o laço."""
        try:
            with self._sessoes() as s, s.begin():
                registrar_sinal(s, self._servico, self._relogio())
        except Exception:
            log.warning("não consegui registrar o sinal de vida de %s", self._servico, exc_info=True)

    def encerrar(self) -> None:
        """Desligamento limpo (SIGTERM): marca para a vigia não avisar. Nunca lança exceção."""
        try:
            with self._sessoes() as s, s.begin():
                registrar_encerramento(s, self._servico, self._relogio())
        except Exception:
            log.warning("não consegui registrar o encerramento de %s", self._servico, exc_info=True)

    def dormir(self, dormir: Callable[[float], None] = time.sleep, fatia_s: float = FATIA_ESPERA_S) -> Callable[[float], None]:
        """Devolve um `dormir` que bate antes e a cada fatia de até `fatia_s`, para esperas longas não calarem o serviço."""

        def dormir_batendo(segundos: float) -> None:
            self.bater()
            restante = segundos
            while restante > 0:
                fatia = min(fatia_s, restante)
                dormir(fatia)
                restante -= fatia
                self.bater()

        return dormir_batendo
