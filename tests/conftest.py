import os

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from tcg_sniper.avisos import formato
from tcg_sniper.config import Config
from tcg_sniper.db.session import criar_engine, migrar

# Nos testes, endereço do sistema numa mensagem é erro (em produção é removido e vai para o log).
formato.ESTRITO = True

URL_TESTE = os.environ.get(
    "DATABASE_URL_TESTE", "postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test"
)


def _checar_banco_de_teste(url: str) -> None:
    """Recusa rodar contra o Postgres de produção: a fixture apaga o schema inteiro."""
    alvo = make_url(url)
    if not (alvo.database or "").startswith("tcg_test") or (alvo.port or 5432) == 5432:
        pytest.exit(
            f"Recusado: os testes apagam o schema public e só podem rodar num banco "
            f"'tcg_test*' fora da porta 5432 (Postgres de produção). URL recebida: "
            f"{alvo.render_as_string(hide_password=True)}. "
            f"Suba o banco de testes com 'docker compose up -d postgres-teste' (porta 5433).",
            returncode=2,
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
        segredo_api="segredo-de-teste-falso-0123456789abcdefghij",
    )


@pytest.fixture(scope="session")
def engine():
    _checar_banco_de_teste(URL_TESTE)
    eng = criar_engine(URL_TESTE)  # a mesma dos serviços (erros sem valores)
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
