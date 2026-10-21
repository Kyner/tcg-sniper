from alembic import command
from sqlalchemy import create_engine, pool, text

from tcg_sniper.db.session import config_alembic

ANTES = "e7c3a9d5b2f4"
INDICE = "SELECT 1 FROM pg_indexes WHERE indexname = 'ix_preco_amazon_anuncio_coletado'"
COLUNA = (
    "SELECT 1 FROM information_schema.columns WHERE table_name = 'config_amazon' "
    "AND column_name = 'quase_oportunidade_min_pct'"
)
IMAGENS = (
    "SELECT 1 FROM information_schema.columns WHERE table_name IN ('produto_liga', 'anuncio_amazon') "
    "AND column_name IN ('imagem_chave', 'imagem_origem')"
)


def test_migracao_do_piso_e_do_indice_sobe_e_desce(engine):
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    try:
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.execute(text(INDICE)).all() == []
            assert c.execute(text(COLUNA)).all() == []
            assert c.execute(text(IMAGENS)).all() == []
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            assert len(c.execute(text(INDICE)).all()) == 1
            assert len(c.execute(text(IMAGENS)).all()) == 4
            assert c.execute(text("SELECT quase_oportunidade_min_pct FROM config_amazon WHERE id = 1")).scalar() in (
                None, 10,
            )
    finally:
        command.upgrade(cfg, "head")
        proprio.dispose()
