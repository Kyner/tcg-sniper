from alembic import context
from sqlalchemy import create_engine, pool

from tcg_sniper.config import Config
from tcg_sniper.db.models import Base

config = context.config
target_metadata = Base.metadata


def executar() -> None:
    url = config.get_main_option("sqlalchemy.url") or Config().database_url
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as conexao:
        context.configure(connection=conexao, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


executar()
