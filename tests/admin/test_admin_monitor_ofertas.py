import base64
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto, oferta_lista
from fastapi.testclient import TestClient

from tcg_sniper.admin import consultas_amazon
from tcg_sniper.admin.app import criar_app
from tcg_sniper.admin.consultas_amazon import FiltroOfertas
from tcg_sniper.consultas import casamentos
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import Envio, OrigemCasamento, OrigemPreco, SituacaoCheckout, StatusCasamento

SP = ZoneInfo("America/Sao_Paulo")


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


@pytest.fixture
def cenario(sessoes):
    """Um produto com um anúncio confirmado pela IA, lido duas vezes pelo monitor, com conferência ok."""
    agora = T0
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Aetherdrift Commander")
        criar_preco_liga(s, p, "400.00", listagem_em=T0)
        a = criar_anuncio(s, "B0DNV55QBS", produto=p, status=StatusCasamento.CONFIRMADO, origem=OrigemCasamento.AUTOMATICO_IA)
        antiga = oferta_lista("300.00", vendedor="Loja Antiga")
        repo_amz.gravar_ofertas(s, a.id, T0 - timedelta(minutes=30), [repo_amz.OfertaAvaliada(antiga, None, True, True)])
        shazaar = oferta_lista("275.91", importada=True, origem_envio="Estados Unidos", prime=True)
        global_ = oferta_lista("314.11", vendedor="Amazon Global", seller_id="amazon", envio=Envio.AMAZON, posicao=0)
        repo_amz.gravar_ofertas(
            s, a.id, agora,
            [repo_amz.OfertaAvaliada(shazaar, None, True, True), repo_amz.OfertaAvaliada(global_, None, True, False)],
        )
        repo_amz.registrar_preco(s, a.id, Decimal("275.91"), OrigemPreco.OFERTAS, None, Envio.FBA, agora, SP)
        repo_amz.registrar_conferencia(
            s, em=agora, anuncio_id=a.id, vendedor_nome="Shazaar", preco_anunciado=Decimal("275.91"),
            itens=Decimal("237.73"), frete=Decimal("0.00"), impostos=Decimal("48.26"), total=Decimal("285.99"),
            situacao=SituacaoCheckout.OK, motivo=None, item_removido=True,
        )
        return p.id, a.id


def test_detalhe_casamento_traz_as_ofertas_da_ultima_leitura_e_a_conferencia(sessoes, cenario):
    produto_id, _ = cenario
    with sessoes() as s:
        d = casamentos.detalhe_casamento(s, produto_id, repo_amz.obter_config(s), T0)
    [linha] = d.confirmados
    assert [(o.vendedor_nome, o.melhor) for o in linha.ofertas] == [("Shazaar", True), ("Amazon Global", False)]
    assert linha.conferencia.total == Decimal("285.99")
    assert linha.verificado  # leitura de ofertas conta como verificada


def test_conferencia_vencida_ou_de_outra_oferta_nao_vale(sessoes, cenario):
    produto_id, _ = cenario
    with sessoes() as s:
        d = casamentos.detalhe_casamento(s, produto_id, repo_amz.obter_config(s), T0 + timedelta(hours=7))
    assert d.confirmados[0].conferencia is None


def test_tela_do_produto_em_casamentos_mostra_tabela_origem_e_conferido(cliente, cenario, monkeypatch):
    produto_id, _ = cenario
    monkeypatch.setattr("tcg_sniper.db.repositorio.agora_utc", lambda: T0)
    texto = cliente.get(f"/casamentos/produto/{produto_id}").text
    assert "automático pela IA" in texto
    assert 'badge-outline whitespace-nowrap">pela IA<' not in texto  # o selo antigo saiu
    assert "Shazaar" in texto and "Amazon Global" in texto and "melhor" in texto
    assert "conferido no checkout: R$ 285,99 (impostos R$ 48,26 inclusos; frete R$ 0,00 à parte)" in texto
    assert "importado (EUA)" in texto and "Prime" in texto


def test_ofertas_mostra_conferido_selos_e_origem(sessoes, cliente, cenario, monkeypatch):
    monkeypatch.setattr("tcg_sniper.db.repositorio.agora_utc", lambda: T0)
    with sessoes() as s:
        [linha] = consultas_amazon.ofertas(s, FiltroOfertas(), repo_amz.obter_config(s))
    assert linha.conferencia.total == Decimal("285.99")
    assert (linha.importada, linha.origem_envio, linha.prime) == (True, "Estados Unidos", True)
    assert linha.origem_casamento is OrigemCasamento.AUTOMATICO_IA
    texto = cliente.get("/ofertas").text
    assert "conferido no checkout: R$ 285,99 (impostos R$ 48,26 inclusos; frete R$ 0,00 à parte)" in texto and "automático pela IA" in texto


def test_ofertas_sem_conferencia_diz_nao_conferido(sessoes, cliente):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p2", nome="Caixa Beta")
        criar_preco_liga(s, p, "1000.00", listagem_em=T0)
        a = criar_anuncio(s, "B0BETA0001", produto=p, status=StatusCasamento.CONFIRMADO, origem=OrigemCasamento.MANUAL)
        o = oferta_lista("700.00", vendedor="Amazon.com.br", seller_id="amazon", envio=Envio.AMAZON, posicao=0)
        repo_amz.gravar_ofertas(s, a.id, T0, [repo_amz.OfertaAvaliada(o, None, True, True)])
        repo_amz.registrar_preco(s, a.id, Decimal("700.00"), OrigemPreco.OFERTAS, None, Envio.AMAZON, T0, SP)
    texto = cliente.get("/ofertas").text
    assert "não conferido" in texto and ">manual<" in texto


def test_pagina_do_produto_mostra_as_ofertas_lidas(cliente, cenario):
    produto_id, _ = cenario
    texto = cliente.get(f"/produto/{produto_id}").text
    assert "Shazaar" in texto and "Amazon Global" in texto and "automático pela IA" in texto


def _com_frete(sessoes, anuncio_id):
    """Conferência mais nova da mesma oferta com frete: total 315,99 = itens 237,73 + impostos 48,26 + frete 30,00."""
    with sessoes() as s, s.begin():
        repo_amz.registrar_conferencia(
            s, em=T0 + timedelta(minutes=1), anuncio_id=anuncio_id, vendedor_nome="Shazaar", preco_anunciado=Decimal("275.91"),
            itens=Decimal("237.73"), frete=Decimal("30.00"), impostos=Decimal("48.26"), total=Decimal("315.99"),
            situacao=SituacaoCheckout.OK, motivo=None, item_removido=True,
        )


# Regra do usuário (2026-10-17): o conferido é itens + impostos, sem o frete (mostrado à parte).
def test_ofertas_mostra_o_conferido_sem_frete_e_o_frete_a_parte(sessoes, cliente, cenario, monkeypatch):
    _com_frete(sessoes, cenario[1])
    monkeypatch.setattr("tcg_sniper.db.repositorio.agora_utc", lambda: T0 + timedelta(minutes=2))
    texto = cliente.get("/ofertas").text
    assert "conferido no checkout: R$ 285,99 (impostos R$ 48,26 inclusos; frete R$ 30,00 à parte)" in texto
    assert "R$ 315,99" not in texto


def test_aba_checkout_mostra_o_conferido_sem_frete(sessoes, cliente, cenario):
    _com_frete(sessoes, cenario[1])
    texto = cliente.get("/logs?aba=checkout").text
    assert "Conferido (sem frete)" in texto
    assert "R$ 285,99" in texto and "frete R$ 30,00 à parte" in texto and "R$ 48,26" in texto


def test_ofertas_busca_as_conferencias_de_uma_vez(sessoes, cliente, cenario, monkeypatch):
    monkeypatch.setattr("tcg_sniper.db.repositorio.agora_utc", lambda: T0)

    def uma_por_linha(*_args, **_kwargs):
        raise AssertionError("conferencia_valida por linha (N+1)")

    monkeypatch.setattr(repo_amz, "conferencia_valida", uma_por_linha)
    with sessoes() as s:
        [linha] = consultas_amazon.ofertas(s, FiltroOfertas(), repo_amz.obter_config(s))
        assert linha.conferencia.total == Decimal("285.99")
        d = casamentos.detalhe_casamento(s, cenario[0], repo_amz.obter_config(s), T0)
        assert d.confirmados[0].conferencia.total == Decimal("285.99")
    assert "conferido no checkout" in cliente.get("/ofertas").text


def test_desconto_e_filtro_das_ofertas_usam_o_conferido_quando_ha_conferencia(sessoes, cenario, monkeypatch):
    # Liga 400: anunciado 275,91 dá 31%; o conferido (itens + impostos) 285,99 dá 28,5%, a regra do aviso.
    monkeypatch.setattr("tcg_sniper.db.repositorio.agora_utc", lambda: T0)
    with sessoes() as s:
        config = repo_amz.obter_config(s)
        [linha] = consultas_amazon.ofertas(s, FiltroOfertas(), config)
        assert (linha.preco, linha.desconto, linha.diferenca) == (Decimal("275.91"), Decimal("28.50"), Decimal("114.01"))
        assert consultas_amazon.ofertas(s, FiltroOfertas(desconto_min=30), config) == []
    monkeypatch.setattr("tcg_sniper.db.repositorio.agora_utc", lambda: T0 + timedelta(hours=7))  # conferência vencida
    with sessoes() as s:
        [linha] = consultas_amazon.ofertas(s, FiltroOfertas(desconto_min=30), repo_amz.obter_config(s))
        assert (linha.conferencia, linha.desconto) == (None, Decimal("31.02"))
