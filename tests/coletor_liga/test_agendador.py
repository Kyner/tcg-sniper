import random
from contextlib import nullcontext
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fakes import NavegadorFake, NotificadorFake, fixture_liga, pagina_html
from sqlalchemy import func, select, text

from tcg_sniper.coletor_liga.agendador import (
    ID_LOCK,
    Agendador,
    alvo_do_dia,
    lock_coleta,
)
from tcg_sniper.coletor_liga.execucao import ResultadoColeta
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import COLETOR_LIGA, Coleta, ProdutoLiga, StatusColeta, TipoColeta
from tcg_sniper.notificador.base import Destino

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


def test_pausa_manual_nao_roda_agendado_nem_solicitado(engine, sessoes, config):
    with sessoes() as s, s.begin():
        repo.solicitar_execucao(s, local(TERCA, 8))
        repo.pausar(s, "pausado no admin", local(TERCA, 8), COLETOR_LIGA)
        repo.solicitar_execucao(s, local(TERCA, 8, 1))  # "rodar agora" com a coleta desligada
    relogio = Relogio(local(TERCA, 15))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() is None
    assert chamadas == []
    with sessoes() as s, s.begin():
        repo.retomar(s, local(TERCA, 15, 1), COLETOR_LIGA, solicitar=False)
    relogio.agora = local(TERCA, 15, 2)
    assert a.tick() == "agendado"  # a pausa cobriu o horário do dia: roda sozinho ao religar
    assert chamadas == [True]


def test_religar_num_dia_ja_coletado_nao_roda_de_novo(engine, sessoes, config):
    job_ok(sessoes, TERCA, 10, 5)
    with sessoes() as s, s.begin():
        repo.pausar(s, "pausado no admin", local(TERCA, 12), COLETOR_LIGA)
    relogio = Relogio(local(TERCA, 13))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() is None
    with sessoes() as s, s.begin():
        repo.retomar(s, local(TERCA, 13, 1), COLETOR_LIGA, solicitar=False)
    relogio.agora = local(TERCA, 13, 2)
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


class Parar(Exception):
    pass


def criar(engine, sessoes, config, relogio, executor, rng=None, dormir=lambda _: None):
    return Agendador(
        engine,
        sessoes,
        lambda: nullcontext(NavegadorFake({})),
        NotificadorFake(),
        config,
        relogio=relogio,
        rng=rng or random.Random(42),
        dormir=dormir,
        executor=executor,
    )


def dormir_ate(n):
    """`dormir` que levanta `Parar` na n-ésima chamada, para sair do laço infinito de `rodar`."""
    chamadas = []

    def dormir(segundos):
        chamadas.append(segundos)
        if len(chamadas) >= n:
            raise Parar

    return dormir, chamadas


def test_rodar_sobrevive_a_excecao_no_tick(engine, sessoes, config):
    dormir, dormidas = dormir_ate(3)
    a = criar(engine, sessoes, config, Relogio(local(TERCA, 8)), lambda _: None, dormir=dormir)
    ticks = []

    def tick_quebrado():
        ticks.append(1)
        raise RuntimeError("banco caiu")

    a.tick = tick_quebrado
    try:
        a.rodar()
    except Parar:
        pass
    assert len(ticks) == 3
    assert dormidas == [60, 60, 60]


def test_rodar_repete_inicializar_ate_conseguir(engine, sessoes, config):
    dormir, _ = dormir_ate(3)
    a = criar(engine, sessoes, config, Relogio(local(TERCA, 8)), lambda _: None, dormir=dormir)
    eventos = []
    inicializar_real = a.inicializar

    def inicializar_instavel():
        eventos.append("init")
        if eventos.count("init") == 1:
            raise RuntimeError("banco ainda subindo")
        inicializar_real()

    a.inicializar = inicializar_instavel
    a.tick = lambda: eventos.append("tick")
    try:
        a.rodar()
    except Parar:
        pass
    assert eventos == ["init", "init", "tick", "tick"]


def test_solicitacao_com_lock_ocupado_e_rearmada(engine, sessoes, config):
    job_ok(sessoes, TERCA, 10, 5)
    with sessoes() as s, s.begin():
        repo.solicitar_execucao(s, local(TERCA, 11))
    relogio = Relogio(local(TERCA, 11, 1))
    chamadas = []

    def executor(incluir_listagens):
        chamadas.append(incluir_listagens)
        return len(chamadas) > 1  # 1ª vez: lock ocupado; 2ª: obtido

    a = criar(engine, sessoes, config, relogio, executor)
    a.inicializar()
    assert a.tick() == "solicitado"
    relogio.agora += timedelta(minutes=1)
    assert a.tick() == "solicitado"
    relogio.agora += timedelta(minutes=1)
    assert a.tick() is None
    assert chamadas == [False, False]


def test_agendado_com_lock_ocupado_nao_tenta_de_novo_no_dia(engine, sessoes, config):
    job_ok(sessoes, ONTEM, 14)
    relogio = Relogio(local(TERCA, 10, 31))
    chamadas = []

    def executor(incluir_listagens):
        chamadas.append(incluir_listagens)
        return False

    a = criar(engine, sessoes, config, relogio, executor)
    a.inicializar()
    assert a.tick() == "agendado"
    relogio.agora += timedelta(minutes=1)
    assert a.tick() is None
    assert chamadas == [True]
    with sessoes() as s:
        assert repo.obter_estado(s).execucao_solicitada is False


class RngContador(random.Random):
    def __init__(self, semente):
        super().__init__(semente)
        self.sorteios = 0

    def uniform(self, a, b):
        self.sorteios += 1
        return super().uniform(a, b)


def test_alvo_do_dia_sorteado_uma_vez(engine, sessoes, config):
    job_ok(sessoes, ONTEM, 14)  # < 24 h: sem execução atrasada, inicializar não sorteia
    relogio = Relogio(local(TERCA, 9, 0))
    rng = RngContador(7)
    a = criar(engine, sessoes, config, relogio, lambda _: None, rng=rng)
    a.inicializar()
    assert a.tick() is None
    alvo = a._alvos[TERCA]
    for minuto in (1, 2, 3, 10, 20):
        relogio.agora = local(TERCA, 9, minuto)
        assert a.tick() is None
    assert rng.sorteios == 1
    assert a._alvos[TERCA] == alvo


def test_lock_coleta_nao_fica_ocioso_em_transacao(engine):
    with lock_coleta(engine) as obtido:
        assert obtido is True
        with engine.connect() as outra:
            estados = outra.execute(
                text(
                    "SELECT a.state FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
                    "WHERE l.locktype = 'advisory' AND l.objid = :id "
                    # O Postgres é o mesmo da produção: ignora o lock do coletor de lá.
                    "AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database())"
                ),
                {"id": ID_LOCK},
            ).scalars().all()
    assert estados == ["idle"]


class FabricaFake:
    """Fábrica de navegadores: cada chamada devolve um context manager que entrega o próximo
    NavegadorFake da fila e registra entradas e saídas."""

    def __init__(self, *navegadores):
        self.fila = list(navegadores)
        self.entregues: list[NavegadorFake] = []
        self.fechados: list[NavegadorFake] = []

    def __call__(self):
        fabrica = self

        class Contexto:
            def __enter__(self):
                self.navegador = fabrica.fila.pop(0)
                fabrica.entregues.append(self.navegador)
                return self.navegador

            def __exit__(self, *_exc):
                fabrica.fechados.append(self.navegador)

        return Contexto()


def agendador_com_fabrica(engine, sessoes, config, fabrica, relogio=None):
    return Agendador(
        engine,
        sessoes,
        fabrica,
        NotificadorFake(),
        config,
        relogio=relogio or Relogio(datetime.now(UTC)),
        rng=random.Random(1),
        dormir=lambda _: None,
    )


def config_uma_categoria(config):
    c = config.model_copy(update={"liga_categorias": "10"})
    return c, c.url_listagem("10")


DESAFIO = pagina_html("<html></html>", titulo="Just a moment...")


def test_desafio_mantem_o_navegador_aberto(engine, sessoes, config):
    c, url = config_uma_categoria(config)
    navegador = NavegadorFake({url: DESAFIO})
    fabrica = FabricaFake(navegador)
    agendador_com_fabrica(engine, sessoes, c, fabrica).executar_job(incluir_listagens=True)
    assert fabrica.entregues == [navegador]
    assert fabrica.fechados == []


def test_job_normal_fecha_o_navegador(engine, sessoes, config):
    navegador = NavegadorFake({})
    fabrica = FabricaFake(navegador)
    agendador_com_fabrica(engine, sessoes, config, fabrica).executar_job(incluir_listagens=False)
    assert fabrica.fechados == [navegador]


def test_erro_no_job_fecha_o_navegador(engine, sessoes, config, monkeypatch):
    from tcg_sniper.coletor_liga import agendador as modulo

    def quebrar(*_a, **_k):
        raise RuntimeError("banco caiu")

    monkeypatch.setattr(modulo, "coletar_produtos", quebrar)
    navegador = NavegadorFake({})
    fabrica = FabricaFake(navegador)
    try:
        agendador_com_fabrica(engine, sessoes, config, fabrica).executar_job(incluir_listagens=False)
    except RuntimeError:
        pass
    assert fabrica.fechados == [navegador]


def test_retomar_roda_no_mesmo_dia_reaproveitando_o_navegador(engine, sessoes, config):
    """Desafio na listagem → pausa com o navegador aberto → humano resolve e clica em Retomar →
    o próximo tick roda o job completo (listagens + produtos) no mesmo navegador e o fecha."""
    c, url = config_uma_categoria(config)
    navegador = NavegadorFake({url: [DESAFIO, pagina_html(fixture_liga("catalogo_pagina_1"), url=url)]})
    fabrica = FabricaFake(navegador)
    a = agendador_com_fabrica(engine, sessoes, c, fabrica)
    a.executar_job(incluir_listagens=True)
    with sessoes() as s, s.begin():
        assert repo.obter_estado(s).estado.value == "pausado_desafio"
    assert a.tick() is None  # pausado: não roda nada

    with sessoes() as s, s.begin():
        repo.retomar(s, repo.agora_utc())
    assert a.tick() == "solicitado"
    assert fabrica.entregues == [navegador]  # o mesmo, sem abrir outro
    assert fabrica.fechados == [navegador]
    assert navegador.visitadas == [url, url]
    with sessoes() as s:
        coletas = [(x.tipo, x.status) for x in s.scalars(select(Coleta).order_by(Coleta.id))]
    assert coletas == [
        (TipoColeta.LISTAGEM, StatusColeta.PAUSADA_DESAFIO),
        (TipoColeta.LISTAGEM, StatusColeta.OK),
        (TipoColeta.PRODUTOS, StatusColeta.OK),
    ]


def test_navegador_mantido_morto_e_trocado_uma_vez(engine, sessoes, config):
    c, url = config_uma_categoria(config)
    morto = NavegadorFake({url: DESAFIO})
    novo = NavegadorFake({url: pagina_html(fixture_liga("catalogo_pagina_1"), url=url)})
    fabrica = FabricaFake(morto, novo)
    a = agendador_com_fabrica(engine, sessoes, c, fabrica)
    a.executar_job(incluir_listagens=True)
    assert fabrica.fechados == []
    morto.morto = True  # o usuário fechou a janela do Chromium pelo noVNC
    with sessoes() as s, s.begin():
        repo.retomar(s, repo.agora_utc())
    assert a.tick() == "solicitado"
    assert fabrica.entregues == [morto, novo]
    assert fabrica.fechados == [morto, novo]
    assert morto.visitadas == [url]
    assert novo.visitadas == [url]


def test_rodar_fecha_o_navegador_mantido_ao_sair(engine, sessoes, config):
    c, url = config_uma_categoria(config)
    navegador = NavegadorFake({url: DESAFIO})
    fabrica = FabricaFake(navegador)
    a = agendador_com_fabrica(engine, sessoes, c, fabrica)
    a.executar_job(incluir_listagens=True)
    assert fabrica.fechados == []
    dormir, _ = dormir_ate(1)
    a._dormir = dormir
    a.tick = lambda: None
    try:
        a.rodar()
    except Parar:
        pass
    assert fabrica.fechados == [navegador]


def test_solicitado_limpa_atrasada_pendente(engine, sessoes, config):
    """Restart às 23:50 sem job há > 24 h e "rodar agora" logo depois: a atrasada (até 00:20)
    não roda de novo depois da meia-noite."""
    job_ok(sessoes, TERCA - timedelta(days=2), 10)
    relogio = Relogio(local(TERCA, 23, 50))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    with sessoes() as s, s.begin():
        repo.solicitar_execucao(s, local(TERCA, 23, 50))
    assert a.tick() == "solicitado"
    relogio.agora = local(TERCA + timedelta(days=1), 0, 30)
    assert a.tick() is None
    assert chamadas == [True]


def test_inicializar_avisa_admin_das_interrompidas(engine, sessoes, config):
    coleta(sessoes, TipoColeta.LISTAGEM, local(TERCA, 10), status=StatusColeta.RODANDO)
    coleta(sessoes, TipoColeta.PRODUTOS, local(TERCA, 10, 30), status=StatusColeta.RODANDO)
    a, notificador = agendador(engine, sessoes, config, Relogio(local(TERCA, 12)), [])
    a.inicializar()
    assert len(notificador.mensagens) == 1
    destino, texto = notificador.mensagens[0]
    assert destino is Destino.ADMIN
    assert "2 coleta(s) interrompida(s)" in texto
    assert "http://host.test:8000" in texto
    assert "Rodar agora" in texto


def test_inicializar_sem_interrompidas_nao_avisa(engine, sessoes, config):
    job_ok(sessoes, ONTEM, 14)
    a, notificador = agendador(engine, sessoes, config, Relogio(local(TERCA, 12)), [])
    a.inicializar()
    assert notificador.mensagens == []


def agendador_resumo(engine, sessoes, config, navegador):
    notificador = NotificadorFake()
    a = Agendador(
        engine,
        sessoes,
        lambda: nullcontext(navegador),
        notificador,
        config,
        relogio=Relogio(local(TERCA, 10, 40)),
        rng=random.Random(1),
        dormir=lambda _: None,
    )
    return a, notificador


def resumos(notificador):
    return [(d, t) for d, t in notificador.mensagens if t.startswith("Coleta de ")]


def test_job_completo_envia_resumo(engine, sessoes, config):
    c, url = config_uma_categoria(config)
    navegador = NavegadorFake({url: pagina_html(fixture_liga("catalogo_pagina_1"), url=url)})
    a, notificador = agendador_resumo(engine, sessoes, c, navegador)
    a.executar_job(incluir_listagens=True)
    with sessoes() as s:
        novos = s.scalar(select(func.count()).select_from(ProdutoLiga))
    assert resumos(notificador) == [
        (
            Destino.ADMIN,
            (
                "Coleta de 13/10 concluída.\n"
                f"Listagens: ok (1 de 1 categorias, {novos} produtos novos).\n"
                "Produtos: ok (0 ok, 0 falhas).\n"
                "Admin: http://host.test:8000"
            ),
        )
    ]


def test_job_so_produtos_envia_resumo_sem_listagens(engine, sessoes, config):
    a, notificador = agendador_resumo(engine, sessoes, config, NavegadorFake({}))
    a.executar_job(incluir_listagens=False)
    assert resumos(notificador) == [
        (Destino.ADMIN, "Coleta de 13/10 concluída.\nProdutos: ok (0 ok, 0 falhas).\nAdmin: http://host.test:8000")
    ]


def test_desafio_nao_envia_resumo(engine, sessoes, config):
    c, url = config_uma_categoria(config)
    a, notificador = agendador_resumo(engine, sessoes, c, NavegadorFake({url: DESAFIO}))
    a.executar_job(incluir_listagens=True)
    assert notificador.mensagens  # o aviso do desafio
    assert resumos(notificador) == []


def test_etapa_interrompida_por_erro_nao_envia_resumo(engine, sessoes, config, monkeypatch):
    from tcg_sniper.coletor_liga import agendador as modulo

    monkeypatch.setattr(
        modulo,
        "coletar_produtos",
        lambda *_a, **_k: ResultadoColeta(1, StatusColeta.FALHA, 0, 0, interrompida=True),
    )
    a, notificador = agendador_resumo(engine, sessoes, config, NavegadorFake({}))
    a.executar_job(incluir_listagens=False)
    assert resumos(notificador) == []


def test_excecao_no_job_nao_envia_resumo(engine, sessoes, config, monkeypatch):
    from tcg_sniper.coletor_liga import agendador as modulo

    def quebrar(*_a, **_k):
        raise RuntimeError("banco caiu")

    monkeypatch.setattr(modulo, "coletar_produtos", quebrar)
    a, notificador = agendador_resumo(engine, sessoes, config, NavegadorFake({}))
    try:
        a.executar_job(incluir_listagens=False)
    except RuntimeError:
        pass
    assert resumos(notificador) == []


def salvar_liga(sessoes, config, **valores):
    with sessoes() as s, s.begin():
        repo.obter_config_liga(s, config)
        repo.salvar_config_liga(s, valores, local(TERCA, 0))


def test_horario_salvo_na_tela_vale_no_proximo_tick(engine, sessoes, config):
    job_ok(sessoes, ONTEM, 14)
    relogio = Relogio(local(TERCA, 7, 0))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() is None  # alvo sorteado para ~10:00
    salvar_liga(sessoes, config, coleta_hora=time(7, 30), coleta_jitter_min=0)
    relogio.agora = local(TERCA, 7, 31)
    assert a.tick() == "agendado"
    assert chamadas == [True]


def test_horario_mudado_depois_do_job_do_dia_nao_roda_de_novo(engine, sessoes, config):
    job_ok(sessoes, ONTEM, 14)
    relogio = Relogio(local(TERCA, 10, 31))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() == "agendado"
    job_ok(sessoes, TERCA, 10, 31)
    salvar_liga(sessoes, config, coleta_hora=time(11, 0), coleta_jitter_min=0)
    relogio.agora = local(TERCA, 11, 5)
    assert a.tick() is None
    assert chamadas == [True]


def test_job_usa_as_categorias_salvas_na_tela(engine, sessoes, config):
    job_ok(sessoes, ONTEM, 14)
    relogio = Relogio(local(TERCA, 10, 31))
    vistas = []
    a, _ = agendador(engine, sessoes, config, relogio, [])
    a._executor = lambda _incluir: vistas.append(a._config.categorias)
    salvar_liga(sessoes, config, categorias="21,22")
    a.inicializar()
    a.tick()
    assert vistas == [["21", "22"]]
