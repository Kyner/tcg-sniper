from decimal import Decimal

import pytest
from fakes import fixture_liga, pagina_html

from tcg_sniper.coletor_liga.desafio import eh_desafio
from tcg_sniper.coletor_liga.modelos import ErroParser, Resumo
from tcg_sniper.coletor_liga.parsers import parse_preco_brl, parse_produto

# <title> real de cada fixture, registrado na captura (scripts/capturar_fixture.py).
TITULOS = {
    "produto_varios_vendedores": "Booster Avulso - Reality Fracture - Booster de Jogo"
    " | Busca de Produtos e Acessórios | LigaMagic",
    "produto_sem_estoque": "From the Vault: Relics Box Set | Busca de Produtos e Acessórios | LigaMagic",
    "produto_um_vendedor": "From the Vault: Exiled Box Set | Busca de Produtos e Acessórios | LigaMagic",
    "catalogo_pagina_1": "Busca: categ=10 searchprod=1"
    " | Busca de cards, produtos e preços de Magic: The Gathering | LigaMagic",
}


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("R$ 1.234,56", Decimal("1234.56")),
        ("R$\xa089,90", Decimal("89.90")),
        ("1234,56", Decimal("1234.56")),
        ("R$ 0,99", Decimal("0.99")),
        ("  R$ 12.345.678,00 ", Decimal("12345678.00")),
    ],
)
def test_parse_preco_brl(texto, esperado):
    assert parse_preco_brl(texto) == esperado


@pytest.mark.parametrize("texto", ["", "Esgotado", "R$ --", "R$ 12"])
def test_parse_preco_brl_invalido(texto):
    with pytest.raises(ErroParser):
        parse_preco_brl(texto)


@pytest.mark.parametrize(("nome", "titulo"), TITULOS.items())
def test_paginas_reais_nao_sao_desafio(nome, titulo):
    assert not eh_desafio(pagina_html(fixture_liga(nome), titulo=titulo))


def test_produto_varios_vendedores():
    assert parse_produto(fixture_liga("produto_varios_vendedores")) == Resumo(
        preco_min=Decimal("29.89"),
        preco_medio=Decimal("37.32"),
        preco_max=Decimal("49.90"),
        num_lojas=94,
    )


def test_produto_um_vendedor():
    assert parse_produto(fixture_liga("produto_um_vendedor")) == Resumo(
        preco_min=Decimal("2499.90"),
        preco_medio=Decimal("2499.90"),
        preco_max=Decimal("2499.90"),
        num_lojas=1,
    )


def test_produto_sem_estoque():
    # A página real sem lojas ainda mostra o quadro "Preço Médio de Venda no Marketplace"
    # (histórico, não depende de estoque atual); o parser devolve o que a página mostra.
    assert parse_produto(fixture_liga("produto_sem_estoque")) == Resumo(
        preco_min=Decimal("5450.00"),
        preco_medio=Decimal("5450.00"),
        preco_max=Decimal("5450.00"),
        num_lojas=0,
    )


def test_produto_sem_quadro_de_precos():
    html = '<html><body><div id="marketplace-stores"><div class="alertaErro">Nenhum item</div></div></body></html>'
    assert parse_produto(html) == Resumo(None, None, None, 0)


@pytest.mark.parametrize(
    "html",
    [
        "<html><body><p>layout novo</p></body></html>",
        # tem lojas na página, mas o contador "Lojas" sumiu
        '<html><body><div id="marketplace-stores"><div class="store"></div></div></body></html>',
        # quadro de preços sem um dos valores
        (
            '<html><body><div id="marketplace-stores"><div class="alertaErro">x</div></div>'
            '<div class="price-mkp"><div class="min"><div class="price">R$ 1,00</div></div></div></body></html>'
        ),
    ],
)
def test_produto_html_sem_estrutura(html):
    with pytest.raises(ErroParser):
        parse_produto(html)
