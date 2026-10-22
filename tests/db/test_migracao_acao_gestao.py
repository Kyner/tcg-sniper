from alembic import command
from sqlalchemy import create_engine, pool, text

from tcg_sniper.db.session import config_alembic

ANTES = "f3b8d1c7a9e2"
COLUNAS = (
    "SELECT column_name, is_nullable, data_type FROM information_schema.columns "
    "WHERE table_name = 'acao_gestao' ORDER BY column_name"
)
INDICE = "SELECT 1 FROM pg_indexes WHERE tablename = 'acao_gestao' AND indexdef LIKE '%(em)%'"


def test_migracao_da_acao_gestao_sobe_e_desce(engine):
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    try:
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.execute(text(COLUNAS)).all() == []
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            colunas = {nome: (nulo, tipo) for nome, nulo, tipo in c.execute(text(COLUNAS))}
            assert colunas == {
                "id": ("NO", "integer"),
                "usuario_id": ("YES", "integer"),
                "em": ("NO", "timestamp with time zone"),
                "tipo": ("NO", "character varying"),
                "detalhe": ("NO", "jsonb"),
            }
            assert len(c.execute(text(INDICE)).all()) == 1
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.execute(text(COLUNAS)).all() == []
    finally:
        command.upgrade(cfg, "head")
        proprio.dispose()
