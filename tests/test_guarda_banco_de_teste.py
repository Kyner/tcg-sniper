"""A guarda do conftest recusa o Postgres de produção sem tocar em banco nenhum."""

import pytest
from conftest import _checar_banco_de_teste


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://tcg:tcg@127.0.0.1/tcg_test",  # sem porta = 5432
        "postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_b",
        "postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg",
    ],
)
def test_recusa_producao_ou_banco_errado(url):
    with pytest.raises(pytest.exit.Exception):
        _checar_banco_de_teste(url)


def test_aceita_banco_de_teste_fora_da_5432():
    _checar_banco_de_teste("postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_b")
