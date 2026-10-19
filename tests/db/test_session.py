import traceback
from types import SimpleNamespace

import psycopg
import pytest
from sqlalchemy import String, TypeDecorator, literal, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, StatementError

from tcg_sniper.db.session import _sem_detalhe, criar_engine

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


def test_hint_e_contexto_continuam_so_o_detail_sai(engine):
    """Só o DETAIL (que repete valores) sai; a primeira linha, o HINT e o CONTEXT ficam."""
    levantar = text(
        "DO $$ BEGIN RAISE EXCEPTION 'falha-primaria' USING DETAIL = 'valor-' || 'secreto-1', HINT = 'dica-util'; END $$"
    )
    with engine.connect() as conexao, pytest.raises(DBAPIError) as erro:  # o `engine` já vem de criar_engine
        conexao.execute(levantar)
    texto = str(erro.value) + str(erro.value.orig)
    assert "valor-secreto-1" not in texto
    assert "falha-primaria" in texto and "HINT:  dica-util" in texto and "CONTEXT:" in str(erro.value.orig)
    assert erro.value.orig.diag.message_detail == "valor-secreto-1"  # o diag continua inteiro


class _Explode(TypeDecorator):
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        raise ValueError("não é do banco\nDETAIL: fica como está")


def test_erro_que_nao_e_do_banco_fica_intacto(engine):
    """O handle_error dispara para qualquer exceção na execução; só erro do psycopg é mexido."""
    with engine.connect() as conexao, pytest.raises(StatementError) as erro:
        conexao.execute(select(literal("x", _Explode())))
    assert erro.value.orig.args == ("não é do banco\nDETAIL: fica como está",)
    assert "DETAIL: fica como está" in str(erro.value)


def test_erro_do_psycopg_sem_detail_fica_intacto():
    """Mensagem de várias linhas sem DETAIL no diag (ex.: conexão recusada, deadlock): nada muda."""
    original = psycopg.OperationalError("linha 1\nDETAIL:  parece mas o diag não tem\nlinha 3")
    contexto = SimpleNamespace(original_exception=original, sqlalchemy_exception=None)
    _sem_detalhe(contexto)
    assert original.args == ("linha 1\nDETAIL:  parece mas o diag não tem\nlinha 3",)
