import random
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from tcg_sniper.coletor_amazon.fila import JITTER_JANELA_MIN, TetoPorHora, intervalo_busca, janela_do_dia

SP = ZoneInfo("America/Sao_Paulo")
DIA = date(2026, 10, 15)
AGORA = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)


def test_janela_respeita_o_jitter_no_fuso_certo():
    rng = random.Random(1)
    for _ in range(100):
        janela = janela_do_dia(DIA, time(8, 0), time(22, 0), SP, rng)
        base_inicio = datetime(2026, 10, 15, 8, 0, tzinfo=SP)
        base_fim = datetime(2026, 10, 15, 22, 0, tzinfo=SP)
        assert abs(janela.inicio - base_inicio) <= timedelta(minutes=JITTER_JANELA_MIN)
        assert abs(janela.fim - base_fim) <= timedelta(minutes=JITTER_JANELA_MIN)


def test_janela_contem():
    janela = janela_do_dia(DIA, time(8, 0), time(22, 0), SP, random.Random(1))
    assert janela.contem(datetime(2026, 10, 15, 12, 0, tzinfo=SP))
    assert not janela.contem(datetime(2026, 10, 15, 7, 0, tzinfo=SP))
    assert not janela.contem(datetime(2026, 10, 15, 23, 0, tzinfo=SP))


def test_janela_curta_nunca_inverte():
    for semente in range(50):
        janela = janela_do_dia(DIA, time(10, 0), time(10, 10), SP, random.Random(semente))
        assert janela.inicio < janela.fim


def test_intervalo_base():
    assert intervalo_busca(60, AGORA, None, AGORA - timedelta(days=1)) == timedelta(minutes=60)


def test_intervalo_metade_com_candidato_nas_ultimas_24h():
    assert intervalo_busca(60, AGORA, AGORA - timedelta(hours=24), AGORA - timedelta(days=30)) == timedelta(minutes=30)


def test_intervalo_dobro_sem_candidato_ha_7_dias():
    assert intervalo_busca(60, AGORA, AGORA - timedelta(days=7), AGORA - timedelta(days=30)) == timedelta(minutes=120)
    assert intervalo_busca(60, AGORA, None, AGORA - timedelta(days=7)) == timedelta(minutes=120)
    assert intervalo_busca(60, AGORA, None, AGORA - timedelta(days=6)) == timedelta(minutes=60)


def test_teto_por_hora():
    teto = TetoPorHora()
    for minuto in range(3):
        teto.registrar(AGORA + timedelta(minutes=minuto))
    assert teto.liberado_em(AGORA + timedelta(minutes=3), 4) is None
    assert teto.liberado_em(AGORA + timedelta(minutes=3), 3) == AGORA + timedelta(hours=1)
    assert teto.liberado_em(AGORA + timedelta(hours=1), 3) is None  # a primeira saiu da janela de 1 h
