"""Ritmo da fila da Amazon: janela do dia, intervalo entre buscas do mesmo produto e teto por hora."""

import random
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

JITTER_JANELA_MIN = 15
UMA_HORA = timedelta(hours=1)


@dataclass(frozen=True)
class Janela:
    inicio: datetime
    fim: datetime

    def contem(self, agora: datetime) -> bool:
        return self.inicio <= agora < self.fim


def janela_do_dia(dia: date, inicio: time, fim: time, zona: ZoneInfo, rng: random.Random) -> Janela:
    """Início e fim do dia no fuso, cada um com variação aleatória de até JITTER_JANELA_MIN minutos."""

    def com_jitter(hora: time) -> datetime:
        return datetime.combine(dia, hora, tzinfo=zona) + timedelta(
            minutes=rng.uniform(-JITTER_JANELA_MIN, JITTER_JANELA_MIN)
        )

    abre, fecha = com_jitter(inicio), com_jitter(fim)
    return Janela(abre, max(fecha, abre + timedelta(minutes=1)))


def intervalo_busca(
    base_min: int, agora: datetime, ultimo_candidato_em: datetime | None, entrou_em: datetime
) -> timedelta:
    """Base; metade se houve candidato nas últimas 24 h; o dobro se não há candidato há 7 dias
    (ou nunca houve, depois de 7 dias na fila)."""
    base = timedelta(minutes=base_min)
    if ultimo_candidato_em is not None and agora - ultimo_candidato_em <= timedelta(hours=24):
        return base / 2
    referencia = ultimo_candidato_em or entrou_em
    if agora - referencia >= timedelta(days=7):
        return base * 2
    return base


class TetoPorHora:
    """Conta as buscas da última hora (em memória; um reinício zera, o que é seguro)."""

    def __init__(self) -> None:
        self._buscas: deque[datetime] = deque()

    def registrar(self, agora: datetime) -> None:
        self._buscas.append(agora)

    def liberado_em(self, agora: datetime, maximo: int) -> datetime | None:
        while self._buscas and self._buscas[0] <= agora - UMA_HORA:
            self._buscas.popleft()
        if len(self._buscas) < maximo:
            return None
        return self._buscas[0] + UMA_HORA
