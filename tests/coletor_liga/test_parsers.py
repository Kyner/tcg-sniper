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
    "produto_sem_historico": "Kit de Pré Lançamento - Khans de Tarkir - Jeskai"
    " | Busca de Produtos e Acessórios | LigaMagic",
    "catalogo_pagina_1": "Busca: categ=10 searchprod=1"
    " | Busca de cards, produtos e preços de Magic: The Gathering | LigaMagic",
    "listagem_expandida": "Busca: categ=10 searchprod=1"
    " | Busca de cards, produtos e preços de Magic: The Gathering | LigaMagic",
    "listagem_vazia": "Global Series - Jiang Yanggu e Mu Yanling | Busca de Produtos e Acessórios | LigaMagic",
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


@pytest.mark.parametrize(
    "texto",
    [
        "",
        "Esgotado",
        "R$ --",
        "R$ 12",
        # nada de truncar em silêncio: o texto inteiro tem de ser um preço
        "R$ 1.234,567",
        "R$ 10,001",
        "R$ 1.2345,67",
        "R$ 10,00 7",
        "R$ 10,00abc",
        "x R$ 10,00",
        "R$ R$ 10,00",
    ],
)
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


def test_produto_sem_historico():
    # Sem lojas e sem venda registrada (pcode 1527, coleta de 2026-10-14) a página não mostra o
    # quadro "Preço Médio de Venda no Marketplace": preços None, nunca zero.
    assert parse_produto(fixture_liga("produto_sem_historico")) == Resumo(
        preco_min=None,
        preco_medio=None,
        preco_max=None,
        num_lojas=0,
    )


@pytest.mark.parametrize(
    "html",
    [
        "<html><body><p>layout novo</p></body></html>",
        # tem lojas na página, mas o quadro "Preço Médio de Venda no Marketplace" sumiu
        (
            '<html><body><div id="marketplace-stores"><div class="store"></div></div>'
            '<div class="group-filter"><div class="filter-header"><div class="title" data-label="Vendedores">'
            '</div></div><div class="filter-option"><div class="filter-infos" title="Lojas"></div>'
            '<div class="filter-counter">3</div></div></div></body></html>'
        ),
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


def test_produto_le_o_nome_em_ingles():
    resumo = parse_produto(fixture_liga("produto_nome_en"))
    assert resumo.nome_en == "Booster Box - The Lord of the Rings: Tales of Middle-Earth - Draft Booster"


@pytest.mark.parametrize(
    "nome",
    ["produto_varios_vendedores", "produto_um_vendedor", "produto_sem_estoque", "produto_sem_historico"],
)
def test_produto_sem_nome_em_ingles_devolve_none(nome):
    assert parse_produto(fixture_liga(nome)).nome_en is None


def test_nome_em_ingles_vazio_vira_none():
    html = fixture_liga("produto_sem_historico").replace(
        "<body>", '<body><div class="item-name-en">  </div>', 1
    )
    assert parse_produto(html).nome_en is None


def test_parse_produto_le_imagem_principal():
    resumo = parse_produto(fixture_liga("produto_nome_en"))
    assert resumo.imagem_url == "https://repositorio.sbrauble.com/arquivos/up/prod/20230222/1677093808_3868.jpg"


def test_parse_produto_sem_imagem_da_none():
    assert parse_produto(fixture_liga("produto_um_vendedor")).imagem_url is None
