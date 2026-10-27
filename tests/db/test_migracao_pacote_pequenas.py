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
                if padrao is not None:
                    assert padrao in str(reais[nome]["default"]), (tabela, nome)
        restricoes = {c["name"] for c in inspect(proprio).get_check_constraints("anuncio_amazon")}
        assert "ck_anuncio_amazon_idioma" in restricoes
        with proprio.connect() as c:
            indices = {r[0] for r in c.execute(text(INDICES))}
            definicao = c.execute(text(MOTIVO)).scalar_one()
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
