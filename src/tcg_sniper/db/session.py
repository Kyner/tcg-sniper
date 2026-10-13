from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DIR_MIGRACOES = Path(__file__).parent / "migrations"


def criar_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


def criar_sessoes(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def migrar(url: str) -> None:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(DIR_MIGRACOES))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
