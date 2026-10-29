from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import fakes_api
import pytest
from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto, oferta_lista
from fakes_oportunidades import criar_oportunidade
from fastapi.testclient import TestClient
from sqlalchemy import select

from tcg_sniper.api.app import criar_app
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import (
    Envio,
    MotivoEncerramento,
    Oportunidade,
    OrigemCasamento,
    OrigemPreco,
    Papel,
    SituacaoCheckout,
    StatusCasamento,
)

SP = ZoneInfo("America/Sao_Paulo")
ROTA = "/api/gestao/ofertas"


@pytest.fixture
def agora_fixo(monkeypatch):
    monkeypatch.setattr("tcg_sniper.db.repositorio.agora_utc", lambda: T0)


def _preco(s, asin, produto, preco, envio=Envio.AMAZON, quando=T0, origem=OrigemCasamento.MANUAL):
    anuncio = criar_anuncio(s, asin, produto=produto, status=StatusCasamento.CONFIRMADO, origem=origem)
    repo_amz.registrar_preco(s, anuncio.id, Decimal(preco), OrigemPreco.PRODUTO, None, envio, quando, SP)
    return anuncio


@pytest.fixture
def cenario(sessoes):
    with sessoes() as s, s.begin():
        caixa = criar_produto(s, "caixa", nome="Caixa Colecionador")
        bundle = criar_produto(s, "bundle", nome="Bundle Final")
        deck = criar_produto(s, "deck", nome="Deck Commander")
        caixa.tipo, bundle.tipo, deck.tipo = "Caixas", "Bundles", "Decks"
        caixa.imagem_chave = "p/caixa.jpg"
        criar_preco_liga(s, caixa, "1000.00")
        criar_preco_liga(s, bundle, "300.00")
        criar_preco_liga(s, deck, "400.00")
        a_caixa = _preco(s, "B0CAIXA001", caixa, "700.00")  # 30%, R$ 300
        _preco(s, "B0BUNDLE01", bundle, "150.00", Envio.FBA, T0 + timedelta(hours=2))  # 50%
        _preco(s, "B0DECK0001", deck, "380.00", quando=T0 + timedelta(hours=1))  # 5%
        criar_oportunidade(s, a_caixa, caixa, aberta_em=T0)
        return {"caixa": caixa.id}


def _asins(cliente, **params):
    r = cliente.get(ROTA, params=params)
    assert r.status_code == 200, r.text
    return [i["anuncio"]["asin"] for i in r.json()["itens"]]


def test_permissoes(cliente, app_api, logar, sessoes, cenario):
    assert cliente.get(ROTA).status_code == 401
    logar(Papel.GRUPO)
    r = cliente.get(ROTA)
    assert r.status_code == 403 and r.json()["erro"] == "sem_permissao"
    logar(Papel.OPERADOR)
    assert cliente.get(ROTA).status_code == 200
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.OPERADOR, "ver_catalogo", False)
    app_api.state.grade.invalidar()
    assert cliente.get(ROTA).status_code == 403


def test_lista_campos_e_ordem_padrao(cliente, logar, cenario, agora_fixo):
    logar(Papel.OPERADOR)
    corpo = cliente.get(ROTA).json()
    assert (corpo["total"], corpo["pagina"], corpo["por_pagina"]) == (3, 1, 50)
    assert [i["anuncio"]["asin"] for i in corpo["itens"]] == ["B0BUNDLE01", "B0CAIXA001", "B0DECK0001"]
    caixa = corpo["itens"][1]
    assert caixa["produto"] == "Caixa Colecionador" and caixa["produto_id"] == cenario["caixa"]
    assert Decimal(caixa["preco_liga"]) == 1000 and Decimal(caixa["preco"]) == 700
    assert Decimal(caixa["desconto_pct"]) == 30 and Decimal(caixa["diferenca"]) == 300
    assert caixa["aberta"] is True and caixa["risco"] is None and caixa["conferido"] is None
    assert caixa["origem"] == "manual" and caixa["prime"] is False and caixa["importada"] is False
    assert caixa["anuncio"]["url"].endswith("B0CAIXA001") and caixa["vendedor"]["envio"] == "amazon"


def test_imagem_so_a_copia_do_bucket(sessoes, config, relogio, cenario):
    nova = config.model_copy(update={"url_publica_imagens": "https://img.test"})
    cliente = TestClient(criar_app(sessoes, nova, relogio))
    fakes_api.logar(sessoes, cliente, Papel.OPERADOR)
    caixa = next(i for i in cliente.get(ROTA).json()["itens"] if i["anuncio"]["asin"] == "B0CAIXA001")
    assert caixa["imagem"] == "https://img.test/p/caixa.jpg"
    assert "imagem_chave" not in caixa and caixa["anuncio"]["imagem"] is None


def test_filtros_e_ordens(cliente, logar, cenario):
    logar(Papel.OPERADOR)
    assert _asins(cliente, vendedor="amazon") == ["B0CAIXA001", "B0DECK0001"]
    assert _asins(cliente, vendedor="fba") == ["B0BUNDLE01"]
    assert _asins(cliente, categoria="Bundles") == ["B0BUNDLE01"]
    assert _asins(cliente, busca="deck") == ["B0DECK0001"]
    assert _asins(cliente, desconto_min=30) == ["B0BUNDLE01", "B0CAIXA001"]
    assert _asins(cliente, situacao="abertas") == ["B0CAIXA001"]
    assert _asins(cliente, ordem="diferenca") == ["B0CAIXA001", "B0BUNDLE01", "B0DECK0001"]
    assert _asins(cliente, ordem="recentes") == ["B0BUNDLE01", "B0DECK0001", "B0CAIXA001"]
    assert _asins(cliente, ordem="nome") == ["B0BUNDLE01", "B0CAIXA001", "B0DECK0001"]


def test_filtros_invalidos(cliente, logar, cenario):
    logar(Papel.OPERADOR)
    for params in (
        {"vendedor": "x"}, {"ordem": "x"}, {"situacao": "x"}, {"desconto_min": "101"}, {"desconto_min": "abc"},
        {"pagina": "0"},
    ):
        assert cliente.get(ROTA, params=params).status_code == 422, params
    r = cliente.get(ROTA, params={"categoria": "Nada"})
    assert r.status_code == 400 and r.json()["erro"] == "filtro_invalido"


def test_paginacao(cliente, sessoes, logar):
    with sessoes() as s, s.begin():
        for i in range(55):
            p = criar_produto(s, f"p{i}", nome=f"Produto {i:02d}")
            criar_preco_liga(s, p, "100.00")
            _preco(s, f"B0EXTRA{i:03d}", p, "90.00")
    logar(Papel.OPERADOR)
    p1 = cliente.get(ROTA, params={"ordem": "nome"}).json()
    p2 = cliente.get(ROTA, params={"ordem": "nome", "pagina": 2}).json()
    assert p1["total"] == 55 and len(p1["itens"]) == 50 and len(p2["itens"]) == 5 and p2["pagina"] == 2
    assert cliente.get(ROTA, params={"pagina": 999}).json()["pagina"] == 2


def test_sem_preco_na_liga_aparece_sem_desconto(cliente, sessoes, logar):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "esgotado", nome="Caixa Esgotada")
        _preco(s, "B0SEMLIGA1", p, "500.00")
    logar(Papel.OPERADOR)
    [item] = cliente.get(ROTA).json()["itens"]
    assert item["preco_liga"] is None and item["desconto_pct"] is None and item["diferenca"] is None
    assert Decimal(item["preco"]) == 500


@pytest.fixture
def com_conferencia(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Aetherdrift Commander")
        criar_preco_liga(s, p, "400.00", listagem_em=T0)
        a = criar_anuncio(
            s, "B0DNV55QBS", produto=p, status=StatusCasamento.CONFIRMADO, origem=OrigemCasamento.AUTOMATICO_IA
        )
        shazaar = oferta_lista("275.91", importada=True, origem_envio="Estados Unidos", prime=True)
        repo_amz.gravar_ofertas(s, a.id, T0, [repo_amz.OfertaAvaliada(shazaar, None, True, True)])
        repo_amz.registrar_preco(s, a.id, Decimal("275.91"), OrigemPreco.OFERTAS, None, Envio.FBA, T0, SP)
        repo_amz.registrar_conferencia(
            s, em=T0, anuncio_id=a.id, vendedor_nome="Shazaar", preco_anunciado=Decimal("275.91"),
            itens=Decimal("237.73"), frete=Decimal("30.00"), impostos=Decimal("48.26"), total=Decimal("315.99"),
            situacao=SituacaoCheckout.OK, motivo=None, item_removido=True,
        )


def test_frase_do_conferido(cliente, logar, com_conferencia, agora_fixo):
    logar(Papel.OPERADOR)
    [item] = cliente.get(ROTA).json()["itens"]
    c = item["conferido"]
    # itens + impostos, sem o frete; o frete vai à parte
    assert (Decimal(c["preco"]), Decimal(c["impostos"]), Decimal(c["frete"])) == (Decimal("285.99"), Decimal("48.26"), 30)
    assert Decimal(item["preco"]) == Decimal("275.91")
    assert Decimal(item["desconto_pct"]) == Decimal("28.50")  # do conferido: 1 - 285,99/400
    assert (item["importada"], item["prime"], item["origem"]) == (True, True, "automatico_ia")


def test_conferido_vencido_nao_aparece_como_conferido(cliente, logar, com_conferencia, monkeypatch):
    monkeypatch.setattr("tcg_sniper.db.repositorio.agora_utc", lambda: T0 + timedelta(hours=7))
    logar(Papel.OPERADOR)
    [item] = cliente.get(ROTA).json()["itens"]
    assert item["conferido"] is None
    assert Decimal(item["desconto_pct"]) == Decimal("31.02")  # do anunciado: 1 - 275,91/400


def test_risco(cliente, sessoes, logar, cenario):
    with sessoes() as s, s.begin():
        op = s.scalars(select(Oportunidade)).one()
        op.em_risco_desde, op.motivo_risco = T0, MotivoEncerramento.PRECO_SUBIU.value
    logar(Papel.OPERADOR)
    caixa = next(i for i in cliente.get(ROTA).json()["itens"] if i["anuncio"]["asin"] == "B0CAIXA001")
    assert caixa["risco"]["motivo"] == "preço subiu" and caixa["risco"]["desde"].startswith("2026")
