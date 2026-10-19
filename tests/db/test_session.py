import traceback

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tcg_sniper.db.session import criar_engine

NUMERO = "+5511900000077"
INSERIR = (
    "INSERT INTO usuario (nome, numero, papel, ativo, superadmin, criado_em)"
    " VALUES (:nome, :numero, 'grupo', true, false, now())"
)


def _erro(conexao, nome: str, numero: str) -> IntegrityError:
    with pytest.raises(IntegrityError) as erro, conexao.begin_nested():
        conexao.execute(text(INSERIR), {"nome": nome, "numero": numero})
    return erro.value


def test_erro_do_banco_nao_mostra_os_valores(engine):
    """Erro do SQLAlchemy/Postgres nunca leva para o log o valor gravado (número, código): nem nos parâmetros
    (`hide_parameters`) nem no DETAIL do Postgres ("Key (numero)=(...)", "Failing row contains (...)")."""
    proprio = criar_engine(engine.url.render_as_string(hide_password=False))  # o banco de teste
    try:
        with proprio.connect() as conexao, conexao.begin() as transacao:
            conexao.execute(text(INSERIR), {"nome": "Nome-Unico-A", "numero": NUMERO})
            repetido = _erro(conexao, "Nome-Unico-B", NUMERO)  # uq_usuario_numero
            formato = _erro(conexao, "Nome-Unico-C", "+55119000000770000000")  # ck_usuario_numero
            transacao.rollback()
    finally:
        proprio.dispose()
    for erro, restricao, valor in (
        (repetido, "uq_usuario_numero", NUMERO),
        (formato, "ck_usuario_numero", "+55119000000770000000"),
    ):
        texto = str(erro) + str(erro.orig) + "".join(traceback.format_exception(erro))
        assert valor not in texto and "Nome-Unico" not in texto
        assert restricao in texto  # o resto do erro continua útil
        assert erro.orig.diag.constraint_name == restricao  # o repositório ainda reconhece a restrição
