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
