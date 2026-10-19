import json
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from fakes import T0, TransporteFake, criar_anuncio, criar_produto
from sqlalchemy import select

from tcg_sniper.casador.avaliacao import avaliar, relatorio_markdown
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import AvaliacaoIA, Casamento, ChamadaIA, StatusCasamento
from tcg_sniper.ia.modelos import Bruta, ErroIA

SP = ZoneInfo("America/Sao_Paulo")


def v(mesmo, confianca):
    return Bruta(json.dumps({"mesmo_produto": mesmo, "confianca": confianca, "motivo": f"m{confianca}"}), 1000, 100)


def test_relatorio_conta_acertos_erros_e_faixas(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Caixa Alfa")
        criar_anuncio(s, "B1", produto=p, status=StatusCasamento.CONFIRMADO)
        criar_anuncio(s, "B2", produto=p, status=StatusCasamento.IGNORADO)
        criar_anuncio(s, "B3", produto=p, status=StatusCasamento.IGNORADO)
        criar_anuncio(s, "B4", produto=p, status=StatusCasamento.CONFIRMADO)
    # B1 sim 95 (acerto), B2 não 80 (acerto), B3 sim 60 (falso sim), B4 erro de chamada
    t = TransporteFake([v(True, 95), v(False, 80), v(True, 60), ErroIA("OpenAI 500")])
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    [r] = avaliar(sessoes, t, http, ["gpt-5"], None, SP, lambda: T0)
    assert (r.total, r.acertos, r.falsos_sim, r.falsos_nao, r.falhas) == (3, 2, 1, 0, 1)
    assert r.faixas["90+"] == (1, 1) and r.faixas["75–89"] == (1, 1) and r.faixas["50–74"] == (0, 1)
    assert r.custo_usd == Decimal("0.006750")
    [erro] = r.erros
    assert erro.asin == "B3" and erro.esperado_mesmo is False and erro.veredito.motivo == "m60"
    md = relatorio_markdown([r], T0)
    assert "gpt-5" in md and "2 de 3" in md and "Falsos \"sim\": 1" in md and "B3" in md and "m60" in md
    with sessoes() as s:
        assert s.scalars(select(AvaliacaoIA)).all() == []
        assert {c.status for c in s.scalars(select(Casamento))} == {StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO}
        assert {c.finalidade for c in s.scalars(select(ChamadaIA))} == {"avaliacao"}


def test_dois_modelos_e_limite(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1")
        for i in range(3):
            criar_anuncio(s, f"B{i}", produto=p, status=StatusCasamento.CONFIRMADO)
    t = TransporteFake([v(True, 99)] * 4)
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    resultados = avaliar(sessoes, t, http, ["gpt-5", "gpt-5-mini"], 2, SP, lambda: T0)
    assert [r.modelo for r in resultados] == ["gpt-5", "gpt-5-mini"]
    assert [p.modelo for p in t.pedidos] == ["gpt-5", "gpt-5", "gpt-5-mini", "gpt-5-mini"]


def test_para_sem_orcamento(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1")
        criar_anuncio(s, "B1", produto=p, status=StatusCasamento.CONFIRMADO)
        repo_ia.salvar_config_ia(s, {"max_chamadas_dia": 0}, T0)
    t = TransporteFake([])
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    [r] = avaliar(sessoes, t, http, ["gpt-5"], None, SP, lambda: T0)
    assert r.total == 0 and r.interrompida is not None and "chamadas" in r.interrompida


def test_configuracao_invalida_interrompe(sessoes):
    from tcg_sniper.ia.modelos import ConfiguracaoInvalida

    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1")
        criar_anuncio(s, "B1", produto=p, status=StatusCasamento.CONFIRMADO)
        criar_anuncio(s, "B2", produto=p, status=StatusCasamento.CONFIRMADO)
    t = TransporteFake([ConfiguracaoInvalida("modelo ou esforço inválido em Configurações → IA: model_not_found (model)")])
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    [r] = avaliar(sessoes, t, http, ["gpt-9"], None, SP, lambda: T0)
    assert r.total == 0 and r.falhas == 0 and "model_not_found" in r.interrompida and len(t.pedidos) == 1


def test_precos_informados_tokens_e_rotulo(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1")
        criar_anuncio(s, "B1", produto=p, status=StatusCasamento.CONFIRMADO)
        criar_anuncio(s, "B2", produto=p, status=StatusCasamento.CONFIRMADO)
    t = TransporteFake([v(True, 99)] * 2)
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    [r] = avaliar(sessoes, t, http, ["gpt-5-mini"], None, SP, lambda: T0,
                  preco_entrada=Decimal("0.25"), preco_saida=Decimal(2))
    assert (r.tokens_entrada, r.tokens_saida) == (2000, 200)
    assert r.custo_usd == Decimal("0.000900")  # 2 × (1000 × 0,25 + 100 × 2) / 1 milhão
    with sessoes() as s:
        assert sum(c.custo_usd for c in s.scalars(select(ChamadaIA))) == Decimal("0.000900")
    md = relatorio_markdown([r], T0, preco_entrada=Decimal("0.25"), preco_saida=Decimal(2))
    assert "Tokens: 2000 de entrada, 200 de saída" in md
    assert "Configurações → IA" not in md and "US$ 0,25" in md and "US$ 2,00" in md


def test_rotulo_dos_precos_de_configuracoes(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1")
        criar_anuncio(s, "B1", produto=p, status=StatusCasamento.CONFIRMADO)
    t = TransporteFake([v(True, 99)])
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    [r] = avaliar(sessoes, t, http, ["gpt-5"], None, SP, lambda: T0)
    md = relatorio_markdown([r], T0)
    assert "com os preços de Configurações → IA" in md and "Tokens: 1000 de entrada, 100 de saída" in md
