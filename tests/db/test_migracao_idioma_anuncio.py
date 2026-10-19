from alembic import command
from sqlalchemy import create_engine, inspect, pool

from tcg_sniper.db.session import config_alembic


def test_migracao_do_idioma_do_anuncio_sobe_e_desce(engine):
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    try:
        command.downgrade(cfg, "a9d4f2c6e8b1")
        assert "idioma_anuncio" not in {c["name"] for c in inspect(proprio).get_columns("avaliacao_ia")}
        command.upgrade(cfg, "head")
        colunas = {c["name"]: c for c in inspect(proprio).get_columns("avaliacao_ia")}
        assert colunas["idioma_anuncio"]["nullable"] is True
        restricoes = {c["name"] for c in inspect(proprio).get_check_constraints("avaliacao_ia")}
        assert "ck_avaliacao_ia_idioma_anuncio" in restricoes
    finally:
        command.upgrade(cfg, "head")
        proprio.dispose()
