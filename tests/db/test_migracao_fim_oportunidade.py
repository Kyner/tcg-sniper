from alembic import command
from sqlalchemy import create_engine, pool, text

from tcg_sniper.db.session import config_alembic

ANTES = "d4b8e2f6a3c1"
COLUNAS = (
    "SELECT column_name FROM information_schema.columns WHERE table_name = 'oportunidade' AND column_name IN "
    "('motivo_encerramento', 'em_risco_desde', 'motivo_risco', 'menor_preco', 'alertas', 'mensagem_alerta_id', "
    "'encerramento_avisado_em', 'alerta_sem_registro')"
)
PREPARO = """
INSERT INTO produto_liga (id, liga_id, nome, url, ativo, visto_primeiro_em, visto_ultimo_em)
VALUES (990001, 'mig-fim', 'Produto migração', 'https://liga.test/p', true, now(), now());
INSERT INTO anuncio_amazon (id, asin, titulo, url, visto_primeiro_em, visto_ultimo_em)
VALUES (990001, 'BMIGFIM001', 'Anúncio migração', 'https://amazon.test/dp/BMIGFIM001', now(), now());
INSERT INTO oportunidade (id, anuncio_id, produto_id, preco_amazon, preco_liga, desconto_pct, envio, aberta_em,
  alertada_em, preco_alertado, alerta_conferido, fechada_em)
VALUES (990001, 990001, 990001, 700, 1000, 30, 'amazon', now(), now(), 700, false, NULL),
       (990002, 990001, 990001, 650, 1000, 35, 'amazon', now(), now(), 650, false, now());
"""
LIMPEZA = (
    "DELETE FROM oportunidade WHERE id IN (990001, 990002); DELETE FROM anuncio_amazon WHERE id = 990001; "
    "DELETE FROM produto_liga WHERE id = 990001;"
)


def test_migracao_do_fim_da_oportunidade_sobe_preenche_e_desce(engine):
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    try:
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.execute(text(COLUNAS)).all() == []
            c.execute(text(PREPARO))
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            linhas = c.execute(text(
                "SELECT id, menor_preco, alertas, alerta_sem_registro, motivo_encerramento "
                "FROM oportunidade WHERE id IN (990001, 990002) ORDER BY id"
            )).all()
            assert [tuple(l) for l in linhas] == [(990001, 700, 1, True, None), (990002, 650, 1, False, None)]
            carencia = c.execute(text("SELECT carencia_encerramento_min FROM config_amazon WHERE id = 1")).scalar()
            assert carencia in (None, 30)  # sem a linha de config o SELECT volta vazio
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.execute(text(COLUNAS)).all() == []
    finally:
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            c.execute(text(LIMPEZA))
        proprio.dispose()
