import random
from contextlib import nullcontext
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fakes import NavegadorFake, NotificadorFake, fixture_liga, pagina_html
from sqlalchemy import select

from tcg_sniper.coletor_liga.agendador import Agendador, alvo_do_dia, lock_coleta
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import Coleta, StatusColeta, TipoColeta

SP = ZoneInfo("America/Sao_Paulo")
TERCA = date(2026, 10, 13)
ONTEM = TERCA - timedelta(days=1)


def local(dia, h, m=0):
    return datetime.combine(dia, time(h, m), tzinfo=SP)


class Relogio:
    def __init__(self, agora):
        self.agora = agora

    def __call__(self):
        return self.agora


def coleta(sessoes, tipo, quando, status=StatusColeta.OK):
    with sessoes() as s, s.begin():
        c = repo.iniciar_coleta(s, tipo, quando)
        if status is not StatusColeta.RODANDO:
            repo.finalizar_coleta(s, c.id, status, 1, 0, quando)


def job_ok(sessoes, dia, h=10, m=5):
    """Job diário completo com sucesso no dia/hora dados."""
    coleta(sessoes, TipoColeta.LISTAGEM, local(dia, h, m))
    coleta(sessoes, TipoColeta.PRODUTOS, local(dia, h, m + 20))


def agendador(engine, sessoes, config, relogio, chamadas, falhar=False):
    def executor(incluir_listagens):
        chamadas.append(incluir_listagens)
        if falhar:
            raise RuntimeError("chromium não abriu")

    notificador = NotificadorFake()
    a = Agendador(
        engine,
        sessoes,
        lambda: nullcontext(NavegadorFake({})),
        notificador,
        config,
        relogio=relogio,
        rng=random.Random(42),
        dormir=lambda _: None,
        executor=executor,
    )
    return a, notificador


def test_alvo_do_dia_respeita_jitter():
    rng = random.Random(1)
    for _ in range(200):
        alvo = alvo_do_dia(TERCA, time(10, 0), 30, SP, rng)
        assert local(TERCA, 9, 30) <= alvo <= local(TERCA, 10, 30)


def test_lock_coleta_exclusivo(engine):
    with lock_coleta(engine) as primeiro:
        assert primeiro is True
        with lock_coleta(engine) as segundo:
            assert segundo is False
    with lock_coleta(engine) as de_novo:
        assert de_novo is True


def test_primeira_execucao_roda_atrasada(engine, sessoes, config):
    relogio = Relogio(local(TERCA, 8, 0))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    relogio.agora += timedelta(minutes=31)
    assert a.tick() == "atrasado"
    assert chamadas == [True]


def test_agendado_roda_uma_vez_no_dia(engine, sessoes, config):
    job_ok(sessoes, ONTEM, 14)
    relogio = Relogio(local(TERCA, 9, 29))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() is None
    relogio.agora = local(TERCA, 10, 31)
    assert a.tick() == "agendado"
    relogio.agora = local(TERCA, 10, 45)
    assert a.tick() is None
    assert chamadas == [True]


def test_restart_depois_de_ja_ter_rodado_hoje_nao_roda_de_novo(engine, sessoes, config):
    job_ok(sessoes, TERCA, 10, 5)
    relogio = Relogio(local(TERCA, 11, 0))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() is None
    assert chamadas == []


def test_restart_sem_coleta_hoje_e_horario_passado_roda(engine, sessoes, config):
    job_ok(sessoes, ONTEM, 14)
    relogio = Relogio(local(TERCA, 10, 45))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() == "agendado"
    assert chamadas == [True]


def test_restart_atrasado_e_agendado_no_mesmo_dia_roda_uma_vez(engine, sessoes, config):
    """Regra do controlador: o ramo "agendado" limpa a execução atrasada pendente."""
    job_ok(sessoes, TERCA - timedelta(days=2), 10)  # > 24 h: inicializar marca execução atrasada
    relogio = Relogio(local(TERCA, 10, 45))  # já passou o alvo do dia (no máximo 10:30)
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() == "agendado"
    relogio.agora = local(TERCA, 11, 30)  # depois de qualquer horário atrasado (até 11:15)
    assert a.tick() is None
    assert chamadas == [True]


def test_agendado_limpa_atrasada_que_cairia_depois_da_meia_noite(engine, sessoes, config):
    """Regra do controlador: restart às 23:50 sem job há > 24 h; a atrasada (até 00:20) não roda de novo."""
    job_ok(sessoes, TERCA - timedelta(days=2), 10)
    relogio = Relogio(local(TERCA, 23, 50))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() == "agendado"
    relogio.agora = local(TERCA + timedelta(days=1), 1, 0)  # primeiro tick depois de um job longo
    assert a.tick() is None
    assert chamadas == [True]


def test_atrasado_respeita_job_ja_iniciado_hoje(engine, sessoes, config):
    """Regra do controlador: o ramo "atrasado" respeita rodou_hoje e não sobra para a madrugada."""
    job_ok(sessoes, TERCA - timedelta(days=2), 10)
    coleta(sessoes, TipoColeta.LISTAGEM, local(TERCA, 10, 5), StatusColeta.PAUSADA_DESAFIO)
    relogio = Relogio(local(TERCA, 11, 0))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    relogio.agora = local(TERCA, 11, 31)
    assert a.tick() is None
    relogio.agora = local(TERCA + timedelta(days=1), 0, 5)
    assert a.tick() is None
    assert chamadas == []


def test_pausado_nao_roda(engine, sessoes, config):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "x", local(TERCA, 8))
    relogio = Relogio(local(TERCA, 15))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() is None
    assert chamadas == []


def test_solicitacao_com_listagem_ok_hoje_roda_so_produtos(engine, sessoes, config):
    job_ok(sessoes, TERCA, 10, 5)
    with sessoes() as s, s.begin():
        repo.retomar(s, local(TERCA, 11))
    relogio = Relogio(local(TERCA, 11, 1))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() == "solicitado"
    assert chamadas == [False]


def test_solicitacao_sem_listagem_ok_hoje_roda_job_completo(engine, sessoes, config):
    job_ok(sessoes, ONTEM, 10)
    coleta(sessoes, TipoColeta.LISTAGEM, local(TERCA, 10, 5), StatusColeta.PAUSADA_DESAFIO)
    with sessoes() as s, s.begin():
        repo.retomar(s, local(TERCA, 14))
    relogio = Relogio(local(TERCA, 14, 1))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() == "solicitado"
    assert chamadas == [True]


def test_inicializar_marca_interrompidas(engine, sessoes, config):
    coleta(sessoes, TipoColeta.PRODUTOS, local(TERCA, 10), status=StatusColeta.RODANDO)
    a, _ = agendador(engine, sessoes, config, Relogio(local(TERCA, 12)), [])
    a.inicializar()
    with sessoes() as s:
        assert s.scalars(select(Coleta.status)).one() is StatusColeta.FALHA


def test_excecao_no_job_avisa_e_nao_repete_no_dia(engine, sessoes, config):
    job_ok(sessoes, ONTEM, 14)
    relogio = Relogio(local(TERCA, 10, 31))
    chamadas = []
    a, notificador = agendador(engine, sessoes, config, relogio, chamadas, falhar=True)
    a.inicializar()
    assert a.tick() == "agendado"
    relogio.agora += timedelta(minutes=1)
    assert a.tick() is None
    assert chamadas == [True]
    assert "chromium não abriu" in notificador.mensagens[0][1]


def agendador_real(engine, sessoes, config, navegador):
    return Agendador(
        engine,
        sessoes,
        lambda: nullcontext(navegador),
        NotificadorFake(),
        config,
        relogio=Relogio(datetime.now(UTC)),
        rng=random.Random(1),
        dormir=lambda _: None,
    )


def tipos_das_coletas(sessoes):
    with sessoes() as s:
        return [c.tipo for c in s.scalars(select(Coleta).order_by(Coleta.id))]


def test_executar_job_varre_listagens_e_depois_produtos(engine, sessoes, config):
    c = config.model_copy(update={"liga_categorias": "10"})
    url = c.url_listagem("10")
    navegador = NavegadorFake({url: pagina_html(fixture_liga("catalogo_pagina_1"), url=url)})
    agendador_real(engine, sessoes, c, navegador).executar_job(incluir_listagens=True)
    assert navegador.visitadas == [url]  # produtos novos entram inativos: nenhuma página de produto
    assert tipos_das_coletas(sessoes) == [TipoColeta.LISTAGEM, TipoColeta.PRODUTOS]


def test_executar_job_para_se_a_listagem_pausar(engine, sessoes, config):
    c = config.model_copy(update={"liga_categorias": "10"})
    navegador = NavegadorFake({c.url_listagem("10"): pagina_html("<html></html>", titulo="Just a moment...")})
    agendador_real(engine, sessoes, c, navegador).executar_job(incluir_listagens=True)
    assert tipos_das_coletas(sessoes) == [TipoColeta.LISTAGEM]


def test_executar_job_so_produtos(engine, sessoes, config):
    navegador = NavegadorFake({})
    agendador_real(engine, sessoes, config, navegador).executar_job(incluir_listagens=False)
    assert navegador.visitadas == []
    assert tipos_das_coletas(sessoes) == [TipoColeta.PRODUTOS]


def test_executar_job_respeita_lock(engine, sessoes, config):
    navegador = NavegadorFake({})
    with lock_coleta(engine):
        agendador_real(engine, sessoes, config, navegador).executar_job(incluir_listagens=True)
    assert tipos_das_coletas(sessoes) == []
