import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, pool, text

import tcg_sniper.db
from tcg_sniper.db.session import config_alembic

ANTES = "f8d2a6c4e1b3"
ARQUIVO = Path(tcg_sniper.db.__file__).parent / "migrations" / "versions" / "a9d4f2c6e8b1_casamento_por_par.py"
T = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
DIA = timedelta(days=1)


def modulo_da_migracao():
    spec = importlib.util.spec_from_file_location("migracao_casamento_por_par", ARQUIVO)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def banco(engine):
    """Fora da transação do `sessoes`: os testes descem e sobem a migração. Sempre deixa o banco em head."""
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    yield cfg, proprio
    command.upgrade(cfg, "head")
    with proprio.begin() as c:
        c.execute(text("DELETE FROM casamento WHERE anuncio_id IN (SELECT id FROM anuncio_amazon WHERE asin LIKE 'BPAR%')"))
        c.execute(text("DELETE FROM anuncio_amazon WHERE asin LIKE 'BPAR%'"))
        c.execute(text("DELETE FROM fila_amazon WHERE produto_id IN (SELECT id FROM produto_liga WHERE liga_id LIKE 'par-%')"))
        c.execute(text("DELETE FROM produto_liga WHERE liga_id LIKE 'par-%'"))
    proprio.dispose()


def _produto(c, liga_id):
    return c.scalar(
        text(
            "INSERT INTO produto_liga (liga_id, nome, url, ativo, visto_primeiro_em, visto_ultimo_em) "
            "VALUES (:l, :l, 'u', true, :t, :t) RETURNING id"
        ),
        {"l": liga_id, "t": T},
    )


def _anuncio_antigo(c, asin, produto_id, status, origem, revisado, primeiro, ultimo):
    """Anúncio no formato de antes (casamento nas colunas do anúncio)."""
    return c.scalar(
        text(
            "INSERT INTO anuncio_amazon (asin, titulo, url, produto_id, status_casamento, origem_casamento, "
            "revisado_em, visto_primeiro_em, visto_ultimo_em) VALUES (:a, 't', 'u', :p, :st, :o, :r, :vp, :vu) RETURNING id"
        ),
        {"a": asin, "p": produto_id, "st": status, "o": origem, "r": revisado, "vp": primeiro, "vu": ultimo},
    )


def test_migracao_copia_um_par_por_anuncio_e_prepara_a_fila(banco):
    cfg, proprio = banco
    command.downgrade(cfg, ANTES)
    with proprio.begin() as c:
        p1, p2 = _produto(c, "par-1"), _produto(c, "par-2")
        conf = _anuncio_antigo(c, "BPAR000001", p1, "confirmado", "automatico_ia", T, T - 10 * DIA, T)
        ign = _anuncio_antigo(c, "BPAR000002", p1, "ignorado", "manual", T, T - 5 * DIA, T - DIA)
        pend = _anuncio_antigo(c, "BPAR000003", p2, "pendente", None, None, T - 2 * DIA, T)
        sem = _anuncio_antigo(c, "BPAR000004", None, "pendente", None, None, T, T)
        c.execute(
            text(
                "INSERT INTO fila_amazon (produto_id, entrou_em, proxima_busca_em, ultima_busca_em, ultimo_termo_en) "
                "VALUES (:p1, :t, :t, :t, false), (:p2, :t, :t, NULL, false)"
            ),
            {"p1": p1, "p2": p2, "t": T},
        )
    command.upgrade(cfg, "head")
    with proprio.connect() as c:
        pares = {
            tuple(linha)
            for linha in c.execute(
                text(
                    "SELECT anuncio_id, produto_id, status, origem, revisado_em, visto_primeiro_em, visto_ultimo_em, "
                    "reavaliar FROM casamento WHERE anuncio_id IN (:a, :b, :c, :d)"
                ),
                {"a": conf, "b": ign, "c": pend, "d": sem},
            )
        }
        fila = {
            linha.produto_id: (linha.indice_termo, linha.ultimo_par_novo_em, linha.termos_tentados_em)
            for linha in c.execute(
                text("SELECT * FROM fila_amazon WHERE produto_id IN (:p1, :p2)"), {"p1": p1, "p2": p2}
            )
        }
    assert pares == {
        (conf, p1, "confirmado", "automatico_ia", T, T - 10 * DIA, T, False),
        (ign, p1, "ignorado", "manual", T, T - 5 * DIA, T - DIA, False),
        (pend, p2, "pendente", None, None, T - 2 * DIA, T, False),
    }
    # p1: última busca em português, há busca anterior -> o próximo é o inglês (1); p2 nunca buscado -> 0
    assert fila == {p1: (1, T - 5 * DIA, None), p2: (0, T - 2 * DIA, None)}


def test_downgrade_refaz_as_colunas_pelo_confirmado_ou_pelo_par_mais_antigo(banco):
    cfg, proprio = banco
    command.downgrade(cfg, ANTES)
    with proprio.begin() as c:
        p1, p2, p3 = _produto(c, "par-1"), _produto(c, "par-2"), _produto(c, "par-3")
        a = _anuncio_antigo(c, "BPAR000011", p1, "pendente", None, None, T, T)
        b = _anuncio_antigo(c, "BPAR000012", p1, "pendente", None, None, T, T)
    command.upgrade(cfg, "head")
    with proprio.begin() as c:
        # a: confirmado para p2 (par mais novo) e outro_confirmado para p1 -> vale o confirmado
        c.execute(
            text(
                "INSERT INTO casamento (anuncio_id, produto_id, status, origem, revisado_em, visto_primeiro_em, "
                "visto_ultimo_em) VALUES (:a, :p, 'confirmado', 'manual', :t, :t2, :t2)"
            ),
            {"a": a, "p": p2, "t": T, "t2": T + DIA},
        )
        c.execute(
            text("UPDATE casamento SET status = 'ignorado', origem = 'outro_confirmado', revisado_em = :t "
                 "WHERE anuncio_id = :a AND produto_id = :p"),
            {"a": a, "p": p1, "t": T},
        )
        # b: ignorado para p1 e pendente para p3 visto antes -> vale o mais antigo (p3)
        c.execute(
            text(
                "INSERT INTO casamento (anuncio_id, produto_id, status, visto_primeiro_em, visto_ultimo_em) "
                "VALUES (:b, :p, 'pendente', :t, :t)"
            ),
            {"b": b, "p": p3, "t": T - DIA},
        )
        c.execute(
            text("UPDATE casamento SET status = 'ignorado', origem = 'sugerido_ia', revisado_em = :t "
                 "WHERE anuncio_id = :b AND produto_id = :p"),
            {"b": b, "p": p1, "t": T},
        )
    command.downgrade(cfg, ANTES)
    with proprio.connect() as c:
        linhas = {
            linha.asin: (linha.produto_id, linha.status_casamento, linha.origem_casamento)
            for linha in c.execute(
                text("SELECT asin, produto_id, status_casamento, origem_casamento FROM anuncio_amazon WHERE asin LIKE 'BPAR%'")
            )
        }
    assert linhas == {"BPAR000011": (p2, "confirmado", "manual"), "BPAR000012": (p3, "pendente", None)}


def test_migracao_aborta_com_dois_confirmados_no_mesmo_anuncio(engine):
    modulo = modulo_da_migracao()
    with engine.connect() as c:
        transacao = c.begin()
        try:
            p1, p2 = _produto(c, "par-dup-1"), _produto(c, "par-dup-2")
            anuncio = c.scalar(
                text(
                    "INSERT INTO anuncio_amazon (asin, titulo, url, visto_primeiro_em, visto_ultimo_em) "
                    "VALUES ('BPARDUP001', 't', 'u', :t, :t) RETURNING id"
                ),
                {"t": T},
            )
            c.execute(text("DROP INDEX uq_casamento_confirmado"))
            c.execute(
                text(
                    "INSERT INTO casamento (anuncio_id, produto_id, status, origem, revisado_em, visto_primeiro_em, "
                    "visto_ultimo_em) VALUES (:a, :p1, 'confirmado', 'manual', :t, :t, :t), "
                    "(:a, :p2, 'confirmado', 'manual', :t, :t, :t)"
                ),
                {"a": anuncio, "p1": p1, "p2": p2, "t": T},
            )
            with pytest.raises(RuntimeError, match="mais de um casamento confirmado"):
                modulo.conferir_um_confirmado_por_anuncio(c)
        finally:
            transacao.rollback()  # o DROP INDEX também volta


ANTIGAS = {"anuncio_amazon": {"produto_id", "status_casamento", "origem_casamento", "revisado_em"},
           "fila_amazon": {"ultimo_termo_en"}}


def _colunas(proprio, tabela):
    with proprio.connect() as c:
        return set(c.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"), {"t": tabela}
        ).scalars())


def test_colunas_antigas_saem_e_voltam_no_downgrade(banco):
    """Por tabela: `fila_amazon` tem o seu próprio `produto_id` (a chave), que fica."""
    cfg, proprio = banco
    for tabela, antigas in ANTIGAS.items():
        assert not _colunas(proprio, tabela) & antigas
    command.downgrade(cfg, ANTES)
    for tabela, antigas in ANTIGAS.items():
        assert antigas <= _colunas(proprio, tabela)
