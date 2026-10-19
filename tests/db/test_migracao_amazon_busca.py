from alembic import command
from sqlalchemy import create_engine, pool, text

from tcg_sniper.db.session import config_alembic

TETOS = "SELECT max_buscas_hora, monitor_max_paginas_hora FROM config_amazon WHERE id = 1"
ANTES = "b3e8d1f5c7a2"


def _tetos(c, busca, monitor):
    c.execute(
        text("UPDATE config_amazon SET max_buscas_hora = :b, monitor_max_paginas_hora = :m WHERE id = 1"),
        {"b": busca, "m": monitor},
    )


def test_migracao_da_busca_separada_sobe_e_desce(engine):
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    coletas: list[int] = []
    try:
        with proprio.begin() as c:
            originais = tuple(c.execute(text(TETOS)).one())
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.scalar(text("SELECT count(*) FROM estado_coletor WHERE id = 6")) == 0
            _tetos(c, 200, 1000)  # produção: busca no padrão antigo, monitor em 1000
            coletas.append(
                c.scalar(
                    text(
                        "INSERT INTO coleta (tipo, iniciada_em, status, produtos_ok, produtos_falha) "
                        "VALUES ('amazon', now(), 'rodando', 3, 0) RETURNING id"
                    )
                )
            )
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            linha = c.execute(text("SELECT coletor, estado FROM estado_coletor WHERE id = 6")).one()
            assert tuple(linha) == ("amazon_busca", "ativo")
            assert tuple(c.execute(text(TETOS)).one()) == (90, 180)
            ciclo = c.execute(text("SELECT status, erro FROM coleta WHERE id = :id"), {"id": coletas[0]}).one()
            assert tuple(ciclo) == ("falha", "interrompida")
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.scalar(text("SELECT count(*) FROM estado_coletor WHERE id = 6")) == 0
            assert tuple(c.execute(text(TETOS)).one()) == (90, 180)  # o downgrade não mexe nos tetos
            _tetos(c, 60, 150)  # valores do usuário abaixo dos novos tetos
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            assert tuple(c.execute(text(TETOS)).one()) == (60, 150)  # least nunca sobe
    finally:
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            _tetos(c, *originais)
            for coleta_id in coletas:
                c.execute(text("DELETE FROM coleta WHERE id = :id"), {"id": coleta_id})
        proprio.dispose()
