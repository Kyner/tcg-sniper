from alembic import command
from sqlalchemy import create_engine, pool, text

from tcg_sniper.db.session import config_alembic

ANTES = "e7b3d9f1a4c6"
INDICES = {
    "ix_coleta_iniciada_em": ("coleta", "(iniciada_em)"),
    "ix_oferta_amazon_lida_em": ("oferta_amazon", "(lida_em, anuncio_id)"),
    "ix_conferencia_checkout_em": ("conferencia_checkout", "(em)"),
    "ix_mensagem_saida_criada_em": ("mensagem_saida", "(criada_em)"),
    "ix_mensagem_saida_enviada_em": ("mensagem_saida", "(enviada_em)"),
    "ix_resumo_preco_coletado_em": ("resumo_preco", "(coletado_em)"),
    "ix_execucao_manutencao_inicio": ("execucao_manutencao", "(inicio)"),
    "ix_estado_aviso_ultimo_em": ("estado_aviso", "(ultimo_em)"),
}
CONSULTA = "SELECT indexname, tablename, indexdef FROM pg_indexes WHERE indexname = ANY(:nomes)"


def _indices(c) -> dict[str, tuple[str, str]]:
    linhas = c.execute(text(CONSULTA), {"nomes": list(INDICES)})
    return {nome: (tabela, definicao[definicao.rindex("("):]) for nome, tabela, definicao in linhas}


def test_migracao_dos_indices_da_atividade_sobe_e_desce(engine):
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    try:
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert _indices(c) == {}
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            assert _indices(c) == INDICES
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert _indices(c) == {}
    finally:
        command.upgrade(cfg, "head")
        proprio.dispose()
