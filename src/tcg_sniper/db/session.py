from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import ExceptionContext
from sqlalchemy.orm import Session, sessionmaker

DIR_MIGRACOES = Path(__file__).parent / "migrations"


def criar_engine(url: str) -> Engine:
    """Engine de todos os serviços. Erros do banco nunca levam valores para o log (números, códigos):
    `hide_parameters` esconde os parâmetros do SQL e `_sem_detalhe` tira o DETAIL do Postgres."""
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
    event.listen(engine, "handle_error", _sem_detalhe)
    return engine


def _so_a_primeira_linha(texto: str) -> str:
    return texto.split("\n", 1)[0]


def _sem_detalhe(contexto: ExceptionContext) -> None:
    """O Postgres repete o valor no DETAIL ("Key (numero)=(...) already exists", "Failing row contains (...)"):
    fica só a primeira linha da mensagem, no erro do driver e no do SQLAlchemy (que já a copiou). O resto do erro
    (restrição em `orig.diag.constraint_name`, SQL sem parâmetros) continua igual."""
    original = contexto.original_exception
    if original.args and isinstance(original.args[0], str):
        original.args = (_so_a_primeira_linha(original.args[0]), *original.args[1:])
    erro = contexto.sqlalchemy_exception
    if erro is not None and erro.args and isinstance(erro.args[0], str) and erro.args[0].startswith("("):
        tipo, _, mensagem = erro.args[0].partition(") ")
        erro.args = (f"{tipo}) {_so_a_primeira_linha(mensagem)}", *erro.args[1:])


def criar_sessoes(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def config_alembic(url: str) -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(DIR_MIGRACOES))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def migrar(url: str) -> None:
    command.upgrade(config_alembic(url), "head")
