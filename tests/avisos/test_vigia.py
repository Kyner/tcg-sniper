import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos import vigia
from tcg_sniper.avisos.catalogo import TipoAviso
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    COLETOR_AMAZON_BUSCA,
    COLETOR_CASADOR,
    COLETOR_LIGA,
    EstadoColetorTipo,
    MensagemSaida,
)

AGORA = datetime(2026, 10, 18, 13, 0, tzinfo=UTC)  # 10:00 em São Paulo
INICIO = AGORA - timedelta(hours=1)


def todos_vivos(sessoes, quando, menos=()):
    with sessoes() as s, s.begin():
        for servico in (COLETOR_LIGA, COLETOR_AMAZON, COLETOR_AMAZON_BUSCA, COLETOR_CASADOR):
            if servico not in menos:
                vigia.registrar_sinal(s, servico, quando)
        repo_msg.registrar_ciclo(s, quando)


def verificar(sessoes, agora, desde=INICIO):
    with sessoes() as s, s.begin():
        vigia.verificar(s, agora, desde)


def abertos(sessoes):
    with sessoes() as s:
        return avisos.abertos(s, TipoAviso.SERVICO_SEM_SINAL)


def textos(sessoes):
    with sessoes() as s:
        return [m.texto for m in s.scalars(select(MensagemSaida).order_by(MensagemSaida.id))]


def test_servico_mudo_mais_de_10_min_abre(sessoes):
    todos_vivos(sessoes, AGORA, menos=(COLETOR_AMAZON,))
    with sessoes() as s, s.begin():
        vigia.registrar_sinal(s, COLETOR_AMAZON, AGORA - timedelta(minutes=11))
    verificar(sessoes, AGORA)
    assert abertos(sessoes) == ["coletor-amazon"]
    [texto] = textos(sessoes)
    assert texto.startswith("🔴 *Serviço sem sinal · coletor-amazon*\n• Último sinal: 18/10 09:49 (há 11 min)\n")


def test_dez_minutos_exatos_ainda_nao_abre(sessoes):
    todos_vivos(sessoes, AGORA - timedelta(minutes=10))
    verificar(sessoes, AGORA)
    assert abertos(sessoes) == []


def test_sinal_que_volta_resolve(sessoes):
    todos_vivos(sessoes, AGORA, menos=(COLETOR_AMAZON,))
    verificar(sessoes, AGORA)  # amazon nunca bateu e a vigia começou há 1 h
    todos_vivos(sessoes, AGORA + timedelta(minutes=1))
    verificar(sessoes, AGORA + timedelta(minutes=1))
    assert abertos(sessoes) == []
    assert textos(sessoes)[-1].startswith("✅ *Serviço sem sinal · coletor-amazon resolvido · 1 vez em 1 min*")


def test_pausado_e_ignorado(sessoes):
    todos_vivos(sessoes, AGORA, menos=(COLETOR_CASADOR,))
    with sessoes() as s, s.begin():
        repo.pausar(s, "pausado no admin", AGORA, COLETOR_CASADOR)
    verificar(sessoes, AGORA)
    assert abertos(sessoes) == []


def test_pausado_por_desafio_continua_vigiado(sessoes):
    todos_vivos(sessoes, AGORA, menos=(COLETOR_LIGA,))
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio", AGORA)
        assert repo.obter_estado(s, AGORA).estado is EstadoColetorTipo.PAUSADO_DESAFIO
    verificar(sessoes, AGORA)
    assert abertos(sessoes) == ["coletor-liga"]


def test_notificador_usa_o_ultimo_ciclo_dele(sessoes):
    todos_vivos(sessoes, AGORA)
    with sessoes() as s, s.begin():
        repo_msg.registrar_ciclo(s, AGORA - timedelta(minutes=30))
    verificar(sessoes, AGORA)
    assert abertos(sessoes) == ["notificador"]


def test_servico_que_nunca_deu_sinal_conta_desde_o_inicio_da_vigia(sessoes):
    todos_vivos(sessoes, AGORA, menos=(COLETOR_CASADOR,))
    verificar(sessoes, AGORA, desde=AGORA - timedelta(minutes=5))
    assert abertos(sessoes) == []
    todos_vivos(sessoes, AGORA + timedelta(minutes=6), menos=(COLETOR_CASADOR,))
    verificar(sessoes, AGORA + timedelta(minutes=6), desde=AGORA - timedelta(minutes=5))
    assert abertos(sessoes) == ["casador"]
    assert "• Último sinal: nenhum desde que a vigia começou\n" in textos(sessoes)[0]


def test_batimento_registra_o_sinal(sessoes):
    vigia.Batimento(sessoes, COLETOR_LIGA, relogio=lambda: AGORA).bater()
    with sessoes() as s:
        assert vigia.ultimo_sinal(s, COLETOR_LIGA) == AGORA


def test_batimento_com_banco_fora_nao_levanta(caplog):
    def sessoes():
        raise RuntimeError("banco fora")

    vigia.Batimento(sessoes, COLETOR_LIGA, relogio=lambda: AGORA).bater()
    assert "sinal de vida de liga" in caplog.text


def test_batimento_em_thread_bate_e_para(sessoes):
    batidas = []
    b = vigia.Batimento(sessoes, COLETOR_LIGA, relogio=lambda: AGORA, intervalo_s=0.01)
    b.bater = lambda: batidas.append(1)
    t = b.iniciar()
    limite = time.monotonic() + 2
    while not batidas and time.monotonic() < limite:
        time.sleep(0.005)
    b.parar()
    assert batidas, "a thread não bateu em 2 s"
    t.join(timeout=2)
    assert not t.is_alive() and t.daemon


def test_busca_da_amazon_muda_abre_com_o_nome_do_servico(sessoes):
    todos_vivos(sessoes, AGORA - timedelta(minutes=1), menos=(COLETOR_AMAZON_BUSCA,))
    verificar(sessoes, AGORA)
    assert abertos(sessoes) == ["coletor-amazon-busca"]


def test_busca_pausada_e_ignorada_e_o_monitor_continua_vigiado(sessoes):
    with sessoes() as s, s.begin():
        repo.pausar(s, "pausado no admin", AGORA, COLETOR_AMAZON_BUSCA)
    todos_vivos(sessoes, AGORA - timedelta(minutes=1), menos=(COLETOR_AMAZON_BUSCA, COLETOR_AMAZON))
    verificar(sessoes, AGORA)
    assert abertos(sessoes) == ["coletor-amazon"]
