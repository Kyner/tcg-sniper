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
