from alembic import command
from sqlalchemy import create_engine, inspect, pool, text

from tcg_sniper.db.session import config_alembic

ANTES = "d6a2f8c4b1e9"
# tabela -> coluna -> (tipo, anulável, trecho esperado no padrão)
COLUNAS = {
    "casamento": {
        "ia_falhas": ("INTEGER", False, "0"),
        "ia_espera_ate": ("TIMESTAMP", True, None),
        "ia_falha_assinatura": ("TEXT", True, None),
    },
    "fila_amazon": {
        "termos_falhas": ("INTEGER", False, "0"),
        "termos_espera_ate": ("TIMESTAMP", True, None),
    },
    "anuncio_amazon": {"idioma": ("TEXT", True, None)},
    "sinal_servico": {"encerrado_em": ("TIMESTAMP", True, None)},
    "oportunidade": {"alerta_enviado": ("BOOLEAN", False, "false")},
    "estado_coletor": {"retomado_desafio_em": ("TIMESTAMP", True, None)},
    "produto_liga": {"falhas_pagina": ("INTEGER", False, "0")},
}
INDICES = "SELECT indexname FROM pg_indexes WHERE tablename = 'oportunidade'"
MOTIVO = (
    "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_oportunidade_motivo_encerramento'"
)


def _colunas(c, tabela):
    return {col["name"]: col for col in inspect(c).get_columns(tabela)}


def test_migracao_do_pacote_de_pequenas_sobe_e_desce(engine):
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    try:
        command.downgrade(cfg, ANTES)
        for tabela, colunas in COLUNAS.items():
            assert not set(colunas) & set(_colunas(proprio, tabela)), tabela
        command.upgrade(cfg, "head")
        for tabela, colunas in COLUNAS.items():
            reais = _colunas(proprio, tabela)
            for nome, (tipo, anulavel, padrao) in colunas.items():
                assert str(reais[nome]["type"]).startswith(tipo), (tabela, nome)
                assert reais[nome]["nullable"] is anulavel, (tabela, nome)
                if tipo == "TIMESTAMP":
                    assert reais[nome]["type"].timezone is True, (tabela, nome)
                if padrao is not None:
                    assert padrao in str(reais[nome]["default"]), (tabela, nome)
        restricoes = {c["name"] for c in inspect(proprio).get_check_constraints("anuncio_amazon")}
        assert "ck_anuncio_amazon_idioma" in restricoes
        indices_oport = {i["name"]: i["column_names"] for i in inspect(proprio).get_indexes("oportunidade")}
        assert indices_oport["ix_oportunidade_mensagem_alerta_id"] == ["mensagem_alerta_id"]
        with proprio.connect() as c:
            indices = {r[0] for r in c.execute(text(INDICES))}
            definicao = c.execute(text(MOTIVO)).scalar_one()
            idioma = c.execute(
                text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_anuncio_amazon_idioma'")
            ).scalar_one()
        for valor in ("pt", "en", "ja", "outro", "indefinido"):
            assert f"'{valor}'" in idioma
        assert "ix_oportunidade_mensagem_alerta_id" in indices
        assert "produto_desativado" in definicao
        command.downgrade(cfg, ANTES)
        with proprio.connect() as c:
            indices = {r[0] for r in c.execute(text(INDICES))}
            definicao = c.execute(text(MOTIVO)).scalar_one()
        assert "ix_oportunidade_mensagem_alerta_id" not in indices
        assert "produto_desativado" not in definicao
    finally:
        command.upgrade(cfg, "head")
        proprio.dispose()


INSERIR = (
    ("INSERT INTO produto_liga (liga_id, nome, url, visto_primeiro_em, visto_ultimo_em) "
    "VALUES ('pp-1', 'Produto', 'https://liga/pp-1', now(), now())"),
    ("INSERT INTO anuncio_amazon (asin, titulo, url, visto_primeiro_em, visto_ultimo_em) "
    "VALUES ('PPASIN0001', 'Anuncio', 'https://amazon/pp', now(), now())"),
    ("INSERT INTO anuncio_amazon (asin, titulo, url, visto_primeiro_em, visto_ultimo_em) "
    "VALUES ('PPASIN0002', 'Anuncio 2', 'https://amazon/pp2', now(), now())"),
    ("INSERT INTO casamento (anuncio_id, produto_id, status, visto_primeiro_em, visto_ultimo_em) "
    "SELECT a.id, p.id, 'pendente', now(), now() FROM anuncio_amazon a, produto_liga p "
    "WHERE a.asin = 'PPASIN0001' AND p.liga_id = 'pp-1'"),
    ("INSERT INTO oportunidade (anuncio_id, produto_id, preco_amazon, preco_liga, desconto_pct, envio, aberta_em, "
    "alertada_em, preco_alertado, menor_preco) "
    "SELECT a.id, p.id, 10, 20, 50, 'amazon', now(), now(), 10, 10 FROM anuncio_amazon a, produto_liga p "
    "WHERE a.asin = 'PPASIN0001' AND p.liga_id = 'pp-1'"),
)
LIMPAR = (
    "DELETE FROM oportunidade WHERE anuncio_id IN (SELECT id FROM anuncio_amazon WHERE asin LIKE 'PPASIN%')",
    "DELETE FROM casamento WHERE anuncio_id IN (SELECT id FROM anuncio_amazon WHERE asin LIKE 'PPASIN%')",
    "DELETE FROM anuncio_amazon WHERE asin LIKE 'PPASIN%'",
    "DELETE FROM produto_liga WHERE liga_id = 'pp-1'",
)


def test_migracao_do_pacote_preserva_dados_e_remapeia_o_motivo_no_downgrade(engine):
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    try:
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            for sql in INSERIR:
                c.execute(text(sql))
        command.upgrade(cfg, "head")
        with proprio.connect() as c:
            linha = c.execute(
                text(
                    "SELECT p.falhas_pagina, k.ia_falhas, k.ia_espera_ate, o.alerta_enviado, o.preco_amazon "
                    "FROM produto_liga p, casamento k, oportunidade o WHERE p.liga_id = 'pp-1'"
                )
            ).one()
        assert (linha[0], linha[1], linha[2], linha[3], int(linha[4])) == (0, 0, None, False, 10)
        # No head: uma oportunidade em risco e outra encerrada, ambas com o motivo novo.
        with proprio.begin() as c:
            c.execute(text("UPDATE oportunidade SET em_risco_desde = now(), motivo_risco = 'produto_desativado'"))
            c.execute(
                text(
                    "INSERT INTO oportunidade (anuncio_id, produto_id, preco_amazon, preco_liga, desconto_pct, "
                    "envio, aberta_em, alertada_em, preco_alertado, menor_preco, fechada_em, motivo_encerramento) "
                    "SELECT a.id, p.id, 10, 20, 50, 'amazon', now(), now(), 10, 10, now(), 'produto_desativado' "
                    "FROM anuncio_amazon a, produto_liga p WHERE a.asin = 'PPASIN0002' AND p.liga_id = 'pp-1'"
                )
            )
        command.downgrade(cfg, ANTES)
        with proprio.connect() as c:
            linhas = c.execute(
                text(
                    "SELECT motivo_risco, motivo_encerramento FROM oportunidade o "
                    "JOIN anuncio_amazon a ON a.id = o.anuncio_id WHERE a.asin LIKE 'PPASIN%' ORDER BY a.asin"
                )
            ).all()
        assert [tuple(x) for x in linhas] == [("casamento_desfeito", None), (None, "casamento_desfeito")]
    finally:
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            for sql in LIMPAR:
                c.execute(text(sql))
        proprio.dispose()
