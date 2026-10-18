import signal

import pytest

from tcg_sniper import cli


def test_subcomando_obrigatorio():
    with pytest.raises(SystemExit):
        cli.main([])


def test_migrate_chama_migrar(monkeypatch):
    chamadas = []
    monkeypatch.setattr(cli, "migrar", chamadas.append)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x@y/z")
    cli.main(["migrate"])
    assert chamadas == ["postgresql+psycopg://x@y/z"]


def test_sigterm_vira_systemexit():
    anterior = signal.getsignal(signal.SIGTERM)
    try:
        cli.instalar_sigterm()
        manipulador = signal.getsignal(signal.SIGTERM)
        with pytest.raises(SystemExit):
            manipulador(signal.SIGTERM, None)
    finally:
        signal.signal(signal.SIGTERM, anterior)


def test_coletor_liga_instala_sigterm_antes_de_rodar(monkeypatch):
    from tcg_sniper.coletor_liga import agendador

    anterior = signal.getsignal(signal.SIGTERM)
    vistos = []

    class AgendadorFalso:
        def __init__(self, *args):
            pass

        def rodar(self):
            vistos.append(signal.getsignal(signal.SIGTERM))

    monkeypatch.setattr(agendador, "Agendador", AgendadorFalso)
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    try:
        cli.main(["coletor-liga"])
        assert vistos and vistos[0] not in (anterior, signal.SIG_DFL, signal.SIG_IGN)
    finally:
        signal.signal(signal.SIGTERM, anterior)


def test_coletor_amazon_instala_sigterm_e_usa_o_perfil_da_amazon(monkeypatch, tmp_path):
    from tcg_sniper.coletor_amazon import varredura

    anterior = signal.getsignal(signal.SIGTERM)
    vistos = []

    class VarreduraFalsa:
        def __init__(self, engine, sessoes, fabrica, avisador, config):
            vistos.append(fabrica()._dir_perfil)

        def rodar(self):
            vistos.append(signal.getsignal(signal.SIGTERM))

    monkeypatch.setattr(varredura, "VarreduraAmazon", VarreduraFalsa)
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    monkeypatch.setenv("DIR_DADOS", str(tmp_path))
    try:
        cli.main(["coletor-amazon"])
        assert vistos[0] == tmp_path / "perfil-amazon"
        assert vistos[1] not in (anterior, signal.SIG_DFL, signal.SIG_IGN)
    finally:
        signal.signal(signal.SIGTERM, anterior)


def test_notificador_instala_sigterm_e_roda_o_servico(monkeypatch):
    from tcg_sniper.notificador import servico

    anterior = signal.getsignal(signal.SIGTERM)
    vistos = []

    class ServicoFalso:
        def __init__(self, *args, **kwargs):
            pass

        def parar(self):
            paradas.append(True)

        def rodar(self):
            vistos.append(signal.getsignal(signal.SIGTERM))
            vistos[-1](signal.SIGTERM, None)

    paradas = []
    monkeypatch.setattr(servico, "ServicoNotificador", ServicoFalso)
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    try:
        cli.main(["notificador"])
        assert vistos and vistos[0] not in (anterior, signal.SIG_DFL, signal.SIG_IGN)
        assert paradas == [True]  # SIGTERM pede parada limpa, sem SystemExit
    finally:
        signal.signal(signal.SIGTERM, anterior)


def test_casador_existe():
    with pytest.raises(SystemExit) as saida:
        cli.main(["casador", "--help"])
    assert saida.value.code == 0


@pytest.mark.parametrize("chave", ["", "sk-teste"])
def test_casador_so_cria_transporte_com_chave(monkeypatch, chave):
    from tcg_sniper.casador import servico
    from tcg_sniper.ia import transporte_openai

    anterior = signal.getsignal(signal.SIGTERM)
    vistos = []

    class ServicoFalso:
        def __init__(self, sessoes, transporte, config, notificador):
            vistos.append(transporte)

        def parar(self):
            pass

        def rodar(self):
            vistos.append(signal.getsignal(signal.SIGTERM))

    monkeypatch.setattr(servico, "ServicoCasador", ServicoFalso)
    monkeypatch.setattr(transporte_openai, "TransporteOpenAI", lambda c, **kw: ("transporte", c, kw))
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    monkeypatch.setenv("OPENAI_API_KEY", chave)
    try:
        cli.main(["casador"])
        assert vistos[0] == (("transporte", chave, {"timeout_s": 30, "max_retries": 2}) if chave else None)
        assert vistos[1] not in (anterior, signal.SIG_DFL, signal.SIG_IGN)
    finally:
        signal.signal(signal.SIGTERM, anterior)


def test_ia_avaliar_sem_chave_aborta_sem_montar_o_transporte(monkeypatch):
    from tcg_sniper.ia import transporte_openai

    montados = []
    monkeypatch.setattr(transporte_openai, "TransporteOpenAI", lambda chave: montados.append(chave))
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with pytest.raises(SystemExit) as erro:
        cli.main(["ia", "avaliar", "--modelo", "gpt-5"])
    assert "OPENAI_API_KEY ausente" in str(erro.value)
    assert montados == []


def test_ia_avaliar_repassa_os_precos(monkeypatch, tmp_path):
    from decimal import Decimal

    from tcg_sniper.casador import avaliacao
    from tcg_sniper.db import repositorio
    from tcg_sniper.ia import transporte_openai

    vistos = {}

    class Sessao:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def avaliar(sessoes, transporte, http, modelos, limite, zona, relogio, **kw):
        vistos["avaliar"] = kw
        return []

    def relatorio(resultados, gerado_em, **kw):
        vistos["relatorio"] = kw
        return "relatório"

    monkeypatch.setattr(transporte_openai, "TransporteOpenAI", lambda c, **kw: object())
    monkeypatch.setattr(avaliacao, "avaliar", avaliar)
    monkeypatch.setattr(avaliacao, "relatorio_markdown", relatorio)
    monkeypatch.setattr(repositorio, "obter_config_geral", lambda s, c: type("G", (), {"fuso": "America/Sao_Paulo"})())
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: Sessao)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-teste")
    monkeypatch.setenv("DIR_DADOS", str(tmp_path))
    cli.main(["ia", "avaliar", "--modelo", "gpt-5-mini", "--preco-entrada", "0.25", "--preco-saida", "2"])
    esperado = {"preco_entrada": Decimal("0.25"), "preco_saida": Decimal(2)}
    assert vistos["avaliar"] == esperado and vistos["relatorio"] == esperado


def test_amazon_capturar_recusa_com_o_coletor_rodando(monkeypatch):
    from contextlib import contextmanager

    from tcg_sniper.coletor_liga import agendador

    @contextmanager
    def lock_ocupado(_engine, _id):
        yield False

    monkeypatch.setattr(agendador, "lock_coleta", lock_ocupado)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x@y/z")
    with pytest.raises(SystemExit, match="docker compose stop coletor-amazon"):
        cli.main(["amazon", "capturar", "--asin", "B0DNV55QBS"])


def test_amazon_capturar_exige_asin():
    with pytest.raises(SystemExit):
        cli.main(["amazon", "capturar"])


def test_amazon_capturar_mostra_o_que_salvou_e_os_avisos_mesmo_com_erro(monkeypatch, tmp_path, capsys):
    from contextlib import contextmanager

    from tcg_sniper.coletor_amazon import captura
    from tcg_sniper.coletor_liga import agendador
    from tcg_sniper.navegador import chromium

    @contextmanager
    def lock_livre(_engine, _id):
        yield True

    class ChromiumFalso:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def capturar_que_quebra(_nav, _asins, destino, *, checkout, pausar, cap):
        cap.salvas.append(destino / "carrinho_inicial.html")
        cap.avisos.append("o item B0DNV55QBS pode ter ficado no carrinho")
        raise RuntimeError("quebrou")

    monkeypatch.setattr(agendador, "lock_coleta", lock_livre)
    monkeypatch.setattr(chromium, "NavegadorChromium", ChromiumFalso)
    monkeypatch.setattr(captura, "capturar", capturar_que_quebra)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x@y/z")
    monkeypatch.setenv("DIR_DADOS", str(tmp_path))
    with pytest.raises(RuntimeError, match="quebrou"):
        cli.main(["amazon", "capturar", "--asin", "B0DNV55QBS", "--checkout"])
    saida = capsys.readouterr().out
    assert f"capturas em {tmp_path}" in saida
    assert "carrinho_inicial.html" in saida
    assert "AVISO: o item B0DNV55QBS pode ter ficado no carrinho" in saida


def test_manutencao_instala_sigterm_e_roda_o_servico_sem_r2(monkeypatch):
    from tcg_sniper.manutencao import servico

    for var in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.setenv(var, "")
    anterior = signal.getsignal(signal.SIGTERM)
    criados, paradas = [], []

    class ServicoFalso:
        def __init__(self, sessoes, config, notificador, enviador):
            criados.append(enviador)

        def parar(self):
            paradas.append(True)

        def rodar(self):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

    monkeypatch.setattr(servico, "ServicoManutencao", ServicoFalso)
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    try:
        cli.main(["manutencao"])
        assert criados == [None] and paradas == [True]
    finally:
        signal.signal(signal.SIGTERM, anterior)
