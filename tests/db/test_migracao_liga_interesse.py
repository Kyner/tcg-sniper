from alembic import command
from sqlalchemy import create_engine, pool, text

from tcg_sniper.db.session import config_alembic

ANTES = "c6a2f8e4d1b9"
COLUNAS = (
    "SELECT column_name FROM information_schema.columns "
    "WHERE table_name = 'config_liga' AND column_name IN ('esfriar_desafio_min', 'produtos_novos_dia')"
)
LINHA = (
    "INSERT INTO config_liga (id, coleta_hora, coleta_jitter_min, pausa_min_s, pausa_max_s, limite_falha_pct, "
    "categorias, url_listagem, max_cliques, atualizado_em) "
    "VALUES (1, '10:00', 30, 8, 20, 50, '10', 'https://liga.test/?c={categ}', 50, now()) "
    "ON CONFLICT (id) DO NOTHING RETURNING id"
)


def test_migracao_da_leitura_por_interesse_sobe_e_desce(engine):
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    criada = False
    try:
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.execute(text(COLUNAS)).all() == []
            criada = c.execute(text(LINHA)).first() is not None  # linha de antes da migração
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            valores = c.execute(text("SELECT esfriar_desafio_min, produtos_novos_dia FROM config_liga WHERE id = 1"))
            assert tuple(valores.one()) == (30, 100)
            restricoes = {
                r[0]
                for r in c.execute(
                    text("SELECT conname FROM pg_constraint WHERE conrelid = 'config_liga'::regclass AND contype = 'c'")
                )
            }
            assert {"ck_config_liga_esfriar_desafio_min", "ck_config_liga_produtos_novos_dia"} <= restricoes
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.execute(text(COLUNAS)).all() == []
    finally:
        command.upgrade(cfg, "head")
        if criada:
            with proprio.begin() as c:
                c.execute(text("DELETE FROM config_liga WHERE id = 1"))
        proprio.dispose()
