from datetime import UTC, datetime

from alembic import command
from sqlalchemy import create_engine, pool, text

from tcg_sniper.db.session import config_alembic

ANTES = "c5e1a8d3f7b2"
COLUNA = (
    "SELECT 1 FROM information_schema.columns WHERE table_name = 'anuncio_amazon' AND column_name = 'monitor_lido_em'"
)
PREPARO = """
INSERT INTO anuncio_amazon (id, asin, titulo, url, visto_primeiro_em, visto_ultimo_em) VALUES
  (990101, 'BMIGLID001', 'Lido pelo monitor e depois pela busca', 'https://amazon.test/dp/BMIGLID001', now(), now()),
  (990102, 'BMIGLID002', 'Leitura do monitor sem ofertas', 'https://amazon.test/dp/BMIGLID002', now(), now()),
  (990103, 'BMIGLID003', 'Só a busca', 'https://amazon.test/dp/BMIGLID003', now(), now());
INSERT INTO oferta_amazon (anuncio_id, lida_em, preco, condicao, envio, importada, prime, elegivel, melhor) VALUES
  (990101, '2026-10-20 10:00:00+00', 700, 'novo', 'amazon', false, false, true, true),
  (990101, '2026-10-21 10:00:00+00', 710, 'novo', 'amazon', false, false, true, true);
INSERT INTO preco_atual_amazon (anuncio_id, preco, origem, envio, coletado_em) VALUES
  (990101, 690, 'busca', 'desconhecido', '2026-10-22 10:00:00+00'),
  (990102, NULL, 'ofertas', 'desconhecido', '2026-10-22 11:00:00+00'),
  (990103, 690, 'busca', 'desconhecido', '2026-10-22 12:00:00+00');
"""
LIMPEZA = (
    "DELETE FROM oferta_amazon WHERE anuncio_id BETWEEN 990101 AND 990103; "
    "DELETE FROM preco_atual_amazon WHERE anuncio_id BETWEEN 990101 AND 990103; "
    "DELETE FROM anuncio_amazon WHERE id BETWEEN 990101 AND 990103;"
)


def test_migracao_da_leitura_do_monitor_sobe_preenche_e_desce(engine):
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    try:
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.execute(text(COLUNA)).all() == []
            c.execute(text(PREPARO))
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            assert len(c.execute(text(COLUNA)).all()) == 1
            linhas = c.execute(text(
                "SELECT id, monitor_lido_em FROM anuncio_amazon WHERE id BETWEEN 990101 AND 990103 ORDER BY id"
            )).all()
            assert [tuple(l) for l in linhas] == [
                (990101, datetime(2026, 10, 21, 10, tzinfo=UTC)),  # a oferta mais recente, não a busca
                (990102, datetime(2026, 10, 22, 11, tzinfo=UTC)),  # preço atual ainda das ofertas
                (990103, None),  # só a busca: o monitor nunca leu
            ]
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.execute(text(COLUNA)).all() == []
    finally:
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            c.execute(text(LIMPEZA))
        proprio.dispose()
