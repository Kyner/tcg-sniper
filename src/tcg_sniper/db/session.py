import re
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import ExceptionContext
from sqlalchemy.orm import Session, sessionmaker

DIR_MIGRACOES = Path(__file__).parent / "migrations"


def criar_engine(url: str) -> Engine:
    """Engine de todos os serviços. Erros do banco nunca levam valores para o log (números, códigos):
    `hide_parameters` esconde os parâmetros do SQL e `_sem_detalhe` tira o DETAIL do Postgres (que repete o valor)."""
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
    event.listen(engine, "handle_error", _sem_detalhe)
    return engine


# A linha "DETAIL:  ..." e as que a continuam, até o próximo campo do Postgres (HINT:, CONTEXT:, LINE 1: ...),
# a parte do SQLAlchemy ("[SQL: ...]", "(Background ...") ou o fim.
_DETAIL = re.compile(r"^DETAIL:  .*(?:\n(?![A-Z]+:  |LINE \d|\[|\(Background).*)*\n?", re.MULTILINE)


def _tirar_detail(args: tuple) -> tuple:
    if args and isinstance(args[0], str):
        return (_DETAIL.sub("", args[0]), *args[1:])
    return args


def _sem_detalhe(contexto: ExceptionContext) -> None:
    """O Postgres repete o valor no DETAIL ("Key (numero)=(...) already exists", "Failing row contains (...)"):
    tira só o DETAIL, do erro do driver e do do SQLAlchemy (que já copiou o texto). A primeira linha, o HINT, o
    CONTEXT e `orig.diag` (inclusive `constraint_name`) ficam. Só mexe em erro do psycopg que tem DETAIL no diag:
    o `handle_error` dispara para qualquer exceção durante a execução, e essas ficam como estão."""
    original = contexto.original_exception
    if not isinstance(original, psycopg.Error) or not original.diag.message_detail:
        return
    original.args = _tirar_detail(original.args)
    if contexto.sqlalchemy_exception is not None:
        contexto.sqlalchemy_exception.args = _tirar_detail(contexto.sqlalchemy_exception.args)


def criar_sessoes(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def config_alembic(url: str) -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(DIR_MIGRACOES))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def migrar(url: str) -> None:
    command.upgrade(config_alembic(url), "head")
