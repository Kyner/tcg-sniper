"""Regressão: nos dados migrados, telas e motor têm os mesmos números de antes (um par por anúncio)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import create_engine, pool, text
from sqlalchemy.orm import sessionmaker

from tcg_sniper.admin import consultas_amazon, consultas_menu
from tcg_sniper.admin import consultas_painel as painel
from tcg_sniper.consultas import casamentos
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.session import config_alembic

ANTES = "f8d2a6c4e1b3"
AGORA = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)
# As mesmas contagens da implantação (docs/IMPLANTACOES.md → Casamento por par): antes de migrar, pelas
# colunas do anúncio; depois, pela tabela `casamento`. Têm de bater.
CONTAGEM_ANTES = (
    "SELECT status_casamento, count(*) FROM anuncio_amazon WHERE produto_id IS NOT NULL AND asin LIKE 'BREG%' "
    "GROUP BY status_casamento"
)
CONTAGEM_DEPOIS = (
    "SELECT c.status, count(*) FROM casamento c JOIN anuncio_amazon a ON a.id = c.anuncio_id "
    "WHERE a.asin LIKE 'BREG%' GROUP BY c.status"
)


def _semear(c) -> dict[str, int]:
    """Dados no formato antigo (casamento nas colunas do anúncio), com os números conhecidos:
    p1: confirmado (automático, R$ 600 lido agora), ignorado (manual), pendente R$ 700 (oportunidade na lista);
    p2: confirmado (manual, R$ 950), pendente R$ 990; p3: ignorado (sugerido pela IA); p4: sem par;
    p5 (inativo): confirmado (manual, R$ 500). Uma oportunidade aberta (p1)."""

    def produto(liga_id, ativo=True):
        produto_id = c.scalar(
            text(
                "INSERT INTO produto_liga (liga_id, nome, url, ativo, visto_primeiro_em, visto_ultimo_em) "
                "VALUES (:l, :n, 'u', :a, :t, :t) RETURNING id"
            ),
            {"l": liga_id, "n": f"Regressão {liga_id}", "a": ativo, "t": AGORA},
        )
        c.execute(
            text("INSERT INTO preco_atual_liga (produto_id, preco_a_partir, listagem_em) VALUES (:p, 1000, :t)"),
            {"p": produto_id, "t": AGORA - timedelta(hours=1)},
        )
        return produto_id

    def anuncio(asin, produto_id, status, origem=None, preco=None, lido=False):
        anuncio_id = c.scalar(
            text(
                "INSERT INTO anuncio_amazon (asin, titulo, url, produto_id, status_casamento, origem_casamento, "
                "revisado_em, visto_primeiro_em, visto_ultimo_em) VALUES (:a, :a, 'u', :p, :s, :o, :r, :t, :t) RETURNING id"
            ),
            {
                "a": asin, "p": produto_id, "s": status, "o": origem,
                "r": None if status == "pendente" else AGORA - timedelta(days=1), "t": AGORA - timedelta(days=2),
            },
        )
        if preco is not None:  # lido = leitura do monitor agora (preço atual "ofertas" + a melhor oferta elegível)
            c.execute(
                text(
                    "INSERT INTO preco_atual_amazon (anuncio_id, preco, origem, envio, coletado_em) "
                    "VALUES (:a, :v, :o, 'amazon', :t)"
                ),
                {"a": anuncio_id, "v": preco, "o": "ofertas" if lido else "busca", "t": AGORA},
            )
            if lido:
                c.execute(
                    text(
                        "INSERT INTO oferta_amazon (anuncio_id, lida_em, vendedor_nome, preco, condicao, envio, importada, "
                        "prime, elegivel, melhor) VALUES (:a, :t, 'Amazon.com.br', :v, 'novo', 'amazon', false, false, true, true)"
                    ),
                    {"a": anuncio_id, "v": preco, "t": AGORA},
                )
        return anuncio_id

    p1, p2, p3, p4 = (produto(f"reg-{i}") for i in range(1, 5))
    p5 = produto("reg-5", ativo=False)
    a1 = anuncio("BREG000001", p1, "confirmado", "automatico_ia", Decimal("600.00"), lido=True)
    anuncio("BREG000002", p1, "ignorado", "manual")
    anuncio("BREG000003", p1, "pendente", preco=Decimal("700.00"))
    anuncio("BREG000004", p2, "confirmado", "manual", Decimal("950.00"), lido=True)
    anuncio("BREG000005", p2, "pendente", preco=Decimal("990.00"))
    anuncio("BREG000006", p3, "ignorado", "sugerido_ia")
    anuncio("BREG000007", p5, "confirmado", "manual", Decimal("500.00"), lido=True)
    c.execute(
        text(
            "INSERT INTO oportunidade (anuncio_id, produto_id, preco_amazon, preco_liga, desconto_pct, envio, aberta_em, "
            "alertada_em, preco_alertado) VALUES (:a, :p, 600, 1000, 40, 'amazon', :t, :t, 600)"
        ),
        {"a": a1, "p": p1, "t": AGORA},
    )
    return {"p1": p1, "p2": p2, "p3": p3, "p4": p4, "p5": p5}


def _limpar(c) -> None:
    anuncios = "(SELECT id FROM anuncio_amazon WHERE asin LIKE 'BREG%')"
    produtos = "(SELECT id FROM produto_liga WHERE liga_id LIKE 'reg-%')"
    for tabela in ("oportunidade", "oferta_amazon", "preco_atual_amazon", "preco_amazon", "casamento"):
        c.execute(text(f"DELETE FROM {tabela} WHERE anuncio_id IN {anuncios}"))
    c.execute(text("DELETE FROM anuncio_amazon WHERE asin LIKE 'BREG%'"))
    for tabela in ("preco_atual_liga", "fila_amazon", "termo_busca"):
        c.execute(text(f"DELETE FROM {tabela} WHERE produto_id IN {produtos}"))
    c.execute(text("DELETE FROM produto_liga WHERE liga_id LIKE 'reg-%'"))


@pytest.fixture
def migrado(engine):
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    command.downgrade(cfg, ANTES)
    try:
        with proprio.begin() as c:
            ids = _semear(c)
            antes = dict(c.execute(text(CONTAGEM_ANTES)).all())
        command.upgrade(cfg, "head")
        yield sessionmaker(bind=proprio, expire_on_commit=False), ids, antes
    finally:
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            _limpar(c)
        proprio.dispose()


def test_contagem_por_status_igual_a_de_antes_de_migrar(migrado):
    fabrica, _, antes = migrado
    assert antes == {"confirmado": 3, "pendente": 2, "ignorado": 2}
    with fabrica() as s:
        depois = dict(s.execute(text(CONTAGEM_DEPOIS)).all())
    assert depois == antes


def test_numeros_iguais_aos_de_antes_nos_dados_migrados(migrado, config):
    fabrica, ids, _ = migrado
    with fabrica() as s:
        cfg = repo_amz.obter_config(s)
        # o Dashboard agora conta por produto ativo: reg-1 e reg-2 casados, reg-3 só ignorados, reg-4 sem candidato
        c = painel.numeros(s, AGORA, config).catalogo
        assert (c.casado, c.esperando_decisao, c.so_ignorados, c.sem_candidato) == (2, 0, 1, 1)
        menu = consultas_menu.contadores_menu(s, AGORA)
        assert (menu.casamentos, menu.ofertas) == (2, 1)
        linhas = {
            l.produto.liga_id: (l.pendentes, l.confirmados, l.ignorados, l.oportunidade)
            for l in consultas_amazon.produtos_para_casar(
                s, busca="", categoria=None, situacao="todos", com_preco=False, desconto_min_pct=25
            )
            if l.produto.liga_id.startswith("reg-")
        }
        assert linhas == {
            "reg-1": (1, 1, 1, True), "reg-2": (1, 1, 0, False), "reg-3": (0, 0, 1, False), "reg-4": (0, 0, 0, False),
        }
        detalhe = casamentos.detalhe_casamento(s, ids["p1"], cfg, AGORA)
        assert (len(detalhe.pendentes), len(detalhe.confirmados), len(detalhe.ignorados)) == (1, 1, 1)
        situacao = repo_amz.situacao_monitor(s, AGORA, cfg)
        assert (situacao.confirmados, situacao.nunca_lidos, situacao.vencidos) == (2, 0, 0)
        assert [c.asin for c in repo_amz.candidatas_ao_checkout(s, AGORA, cfg)] == ["BREG000001"]
        ofertas = {
            l.anuncio.asin: l.origem_casamento.value
            for l in consultas_amazon.ofertas(s, consultas_amazon.FiltroOfertas(), cfg)
        }
        assert ofertas == {"BREG000001": "automatico_ia", "BREG000004": "manual", "BREG000007": "manual"}
