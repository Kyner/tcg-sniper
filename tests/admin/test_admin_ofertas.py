import base64
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto
from fastapi.testclient import TestClient

from tcg_sniper.admin import consultas_amazon
from tcg_sniper.admin.app import criar_app
from tcg_sniper.admin.consultas_amazon import FiltroOfertas
from tcg_sniper.coletor_amazon.modelos import AvaliacaoVendedor
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import Envio, OrigemPreco, StatusCasamento

SP = ZoneInfo("America/Sao_Paulo")


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def oferta(s, asin, produto, preco, envio, vendedor_id=None, quando=T0):
    anuncio = criar_anuncio(s, asin, produto=produto, status=StatusCasamento.CONFIRMADO)
    repo_amz.registrar_preco(s, anuncio.id, Decimal(preco), OrigemPreco.PRODUTO, vendedor_id, envio, quando, SP)
    return anuncio


@pytest.fixture
def cenario(sessoes):
    with sessoes() as s, s.begin():
        amazon = repo_amz.vendedor_da_amazon(s)
        boa = repo_amz.gravar_vendedor(s, AvaliacaoVendedor("A1", "Loja Boa", Decimal(98), 5000), T0)
        ruim = repo_amz.gravar_vendedor(s, AvaliacaoVendedor("A2", "Loja Nova", Decimal(80), 3), T0)
        caixa = criar_produto(s, "caixa", nome="Caixa 100% Colecionador")
        bundle = criar_produto(s, "bundle", nome="Bundle Final")
        deck = criar_produto(s, "deck", nome="Deck Commander")
        caixa.tipo, bundle.tipo, deck.tipo = "Caixas", "Bundles", "Decks"
        criar_preco_liga(s, caixa, "1000.00")
        criar_preco_liga(s, bundle, "300.00")
        criar_preco_liga(s, deck, "400.00")
        caixa_amazon = oferta(s, "B0CAIXAAMZ", caixa, "700.00", Envio.AMAZON, amazon.id, T0)  # 30%, R$ 300
        oferta(s, "B0CAIXAFBA", caixa, "650.00", Envio.FBA, ruim.id, T0)  # 35%, lojista não confiável
        oferta(s, "B0BUNDLE01", bundle, "150.00", Envio.FBA, boa.id, T0 + timedelta(hours=2))  # 50%, R$ 150
        oferta(s, "B0DECK0001", deck, "380.00", Envio.AMAZON, amazon.id, T0 + timedelta(hours=1))  # 5%, R$ 20
        repo_amz.abrir_oportunidade(
            s, anuncio_id=caixa_amazon.id,
            produto_id=caixa.id, preco_amazon=Decimal("700.00"), preco_liga=Decimal("1000.00"),
            desconto_pct=Decimal("30.00"), vendedor_id=amazon.id, envio=Envio.AMAZON, agora=T0,
        )


def asins(s, **campos):
    config = repo_amz.obter_config(s)
    return [linha.anuncio.asin for linha in consultas_amazon.ofertas(s, FiltroOfertas(**campos), config)]


def test_ordens(s, cenario):
    assert asins(s) == ["B0BUNDLE01", "B0CAIXAFBA", "B0DECK0001"]  # melhor oferta por produto, maior % primeiro
    assert asins(s, ordem="diferenca") == ["B0CAIXAFBA", "B0BUNDLE01", "B0DECK0001"]
    assert asins(s, ordem="recentes") == ["B0BUNDLE01", "B0DECK0001", "B0CAIXAFBA"]
    assert asins(s, ordem="nome") == ["B0BUNDLE01", "B0CAIXAFBA", "B0DECK0001"]


def test_vendedor_escolhe_a_melhor_oferta_entre_as_aceitas(s, cenario):
    assert asins(s, vendedor="amazon") == ["B0CAIXAAMZ", "B0DECK0001"]
    assert asins(s, vendedor="fba") == ["B0BUNDLE01", "B0CAIXAFBA"]
    assert asins(s, vendedor="elegiveis") == ["B0BUNDLE01", "B0CAIXAAMZ", "B0DECK0001"]


def test_busca_categoria_desconto_e_situacao(s, cenario):
    assert asins(s, busca="100%") == ["B0CAIXAFBA"]
    assert asins(s, busca="_") == []
    assert asins(s, categoria="Bundles") == ["B0BUNDLE01"]
    assert asins(s, desconto_min=30) == ["B0BUNDLE01", "B0CAIXAFBA"]
    assert asins(s, situacao="abertas") == ["B0CAIXAFBA"]


def test_diferenca_em_reais(s, cenario):
    config = repo_amz.obter_config(s)
    [deck] = consultas_amazon.ofertas(s, FiltroOfertas(busca="Deck"), config)
    assert deck.diferenca == Decimal("20.00")


def test_tela_com_filtros_paginacao_e_validacao(cliente, sessoes, cenario):
    texto = cliente.get("/ofertas").text
    assert "Diferença (R$)" in texto and "R$ 150,00" in texto
    assert 'href="/ofertas?desconto_min=25' in texto  # atalho "≥ desconto configurado"
    filtrado = cliente.get("/ofertas?vendedor=amazon&ordem=nome").text
    assert "B0CAIXAAMZ" in filtrado and "B0BUNDLE01" not in filtrado
    for consulta in ("vendedor=xyz", "ordem=xyz", "situacao=xyz", "desconto_min=abc", "desconto_min=101", "categoria=Nada"):
        assert cliente.get(f"/ofertas?{consulta}").status_code == 400
    with sessoes() as s, s.begin():
        amazon = repo_amz.vendedor_da_amazon(s)
        for i in range(55):
            produto = criar_produto(s, f"p{i}", nome=f"Produto {i:02d}")
            criar_preco_liga(s, produto, "100.00")
            oferta(s, f"B0EXTRA{i:03d}", produto, "90.00", Envio.AMAZON, amazon.id)
    pagina2 = cliente.get("/ofertas?vendedor=amazon&pagina=2").text
    assert pagina2.split("</table>")[0].count('text-base-content/60">B0') == 7  # 57 ofertas da Amazon → 50 + 7
    assert "vendedor=amazon" in pagina2
    assert cliente.get("/ofertas?pagina=999").status_code == 200


def test_vendedor_lido_so_na_busca_aparece_como_nao_verificado(cliente, sessoes):
    with sessoes() as s, s.begin():
        produto = criar_produto(s, "selo", nome="Caixa Selada")
        criar_preco_liga(s, produto, "1000.00")
        anuncio = criar_anuncio(s, "B0BUSCA001", produto=produto, status=StatusCasamento.CONFIRMADO)
        repo_amz.registrar_preco(
            s, anuncio.id, Decimal("960.00"), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, T0, SP
        )
        sem_bloco = criar_produto(s, "pagina", nome="Caixa Lida")
        criar_preco_liga(s, sem_bloco, "1000.00")
        oferta(s, "B0PAGINA01", sem_bloco, "900.00", Envio.DESCONHECIDO)
    texto = cliente.get("/ofertas").text
    linha_busca = texto[texto.index("Caixa Selada"):].split("</tr>")[0]
    linha_pagina = texto[texto.index("Caixa Lida"):].split("</tr>")[0]
    assert "vendedor não verificado" in linha_busca and "não elegível" not in linha_busca
    assert "não elegível" in linha_pagina and "não verificado" not in linha_pagina


def test_desconto_e_vendedor_com_selo(cliente, cenario):
    texto = cliente.get("/ofertas?vendedor=amazon").text  # no filtro padrão a melhor oferta da caixa é a do lojista FBA (35%)
    assert 'badge-success' in texto and ">30,00%</span>" in texto  # caixa Amazon 30% ≥ 25%
    assert ">vendido pela Amazon</span>" in texto
