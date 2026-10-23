from alembic import command
from sqlalchemy import create_engine, pool, text

from tcg_sniper.db.session import config_alembic

ANTES = "a1c4e7b9d2f6"
COLUNA = (
    "SELECT 1 FROM information_schema.columns WHERE table_name = 'config_amazon' "
    "AND column_name = 'monitor_esgotado_dias'"
)
CHECK = "SELECT 1 FROM pg_constraint WHERE conname = 'ck_config_amazon_monitor_esgotado_dias'"


def test_migracao_do_intervalo_de_esgotado_sobe_e_desce(engine):
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    try:
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.execute(text(COLUNA)).all() == []
            assert c.execute(text(CHECK)).all() == []
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            assert len(c.execute(text(COLUNA)).all()) == 1
            assert len(c.execute(text(CHECK)).all()) == 1
            assert c.execute(text("SELECT monitor_esgotado_dias FROM config_amazon WHERE id = 1")).scalar() in (
                None, 7,
            )
    finally:
        command.upgrade(cfg, "head")
        proprio.dispose()
