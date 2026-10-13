import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from tcg_sniper.config import Config
from tcg_sniper.db.session import migrar

URL_TESTE = os.environ.get(
    "DATABASE_URL_TESTE", "postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test"
)


@pytest.fixture
def config(tmp_path):
    return Config(
        _env_file=None,
        dir_dados=tmp_path,
        liga_categorias="10,11,12",
        liga_url_listagem="https://liga.test/listagem?categ={categ}",
        liga_max_cliques=5,
        host_publico="host.test",
        pausa_min_s=8,
        pausa_max_s=20,
        limite_falha_pct=50,
    )


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(URL_TESTE)
    with eng.begin() as conexao:
        conexao.execute(text("DROP SCHEMA public CASCADE"))
        conexao.execute(text("CREATE SCHEMA public"))
    migrar(URL_TESTE)
    yield eng
    eng.dispose()


@pytest.fixture
def sessoes(engine):
    """sessionmaker isolado: tudo que o teste gravar é desfeito no fim."""
    conexao = engine.connect()
    transacao = conexao.begin()
    fabrica = sessionmaker(
        bind=conexao, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    yield fabrica
    transacao.rollback()
    conexao.close()


@pytest.fixture
def s(sessoes):
    with sessoes() as sessao:
        yield sessao
