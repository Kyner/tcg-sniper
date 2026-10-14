from decimal import Decimal

import pytest
from fakes import cartao_listagem, fixture_liga, html_listagem

from tcg_sniper.coletor_liga.modelos import ErroParser, ItemListagem
from tcg_sniper.coletor_liga.parsers import parse_listagem

URL_CATEG_10 = "https://www.ligamagic.com.br/?view=cards/search&card=categ%3D10+searchprod%3D1&tipo=1"
URL_PRODUTO = "https://www.ligamagic.com.br/?view=prod/view&pcode="


def test_listagem_real_primeira_carga():
    itens = parse_listagem(fixture_liga("catalogo_pagina_1"), URL_CATEG_10)
    assert len(itens) == 40
    assert len({i.liga_id for i in itens}) == 40
    assert itens[0] == ItemListagem(
        liga_id="127987",
        nome="Caixa de Booster - 30th Anniversary Edition",
        url=URL_PRODUTO + "127987&prod=Caixa de Booster - 30th Anniversary Edition",
        preco_a_partir=Decimal("8888.85"),
        tipo="Caixas de Boosters",
    )
    assert (itens[1].liga_id, itens[1].preco_a_partir) == ("107229", Decimal("1299.00"))
    assert (itens[-1].liga_id, itens[-1].nome, itens[-1].preco_a_partir) == (
        "124050",
        "Caixa de Booster - Dominária Unida - Booster de Colecionador",
        Decimal("1770.00"),
    )
    assert all(i.preco_a_partir is not None for i in itens)
    assert all(i.tipo == "Caixas de Boosters" for i in itens)


def test_listagem_ignora_carrossel_de_mais_vendidos():
    # 107547 (Magic 2010, indisponível) só aparece no carrossel `.best-sellers` desta fixture.
    itens = parse_listagem(fixture_liga("catalogo_pagina_1"), URL_CATEG_10)
    assert "107547" not in {i.liga_id for i in itens}


def test_cartao_sem_estoque_vira_none():
    html = html_listagem(
        cartao_listagem("107547", "Caixa de Booster - Magic 2010 Core Set", None),
        cartao_listagem("127987", "Caixa de Booster - 30th Anniversary Edition", "R$ 8.888,85"),
    )
    itens = parse_listagem(html, URL_CATEG_10)
    assert [(i.liga_id, i.preco_a_partir) for i in itens] == [
        ("107547", None),
        ("127987", Decimal("8888.85")),
    ]
    assert itens[0].nome == "Caixa de Booster - Magic 2010 Core Set"


def test_listagem_mantem_repetidos_na_ordem():
    html = html_listagem(cartao_listagem("1", "A", "R$ 10,00"), cartao_listagem("1", "A", "R$ 10,00"))
    assert [i.liga_id for i in parse_listagem(html, URL_CATEG_10)] == ["1", "1"]


@pytest.mark.parametrize(
    "html",
    [
        "<html><body><p>layout novo</p></body></html>",
        html_listagem(),
        html_listagem(cartao_listagem("1", "A", "R$ --")),
        html_listagem('<div class="card"><h5 class="card-title">sem link</h5></div>'),
        html_listagem(
            '<div class="card"><h5 class="card-title"><a href="/?view=prod/view&amp;pcode=9">X</a></h5></div>'
        ),
        html_listagem(
            '<div class="card"><h5 class="card-title"><a href="/?view=outra">X</a></h5>'
            '<p class="smallest-price">R$ 1,00</p></div>'
        ),
    ],
    ids=["sem-grade", "grade-vazia", "preco-invalido", "sem-link", "sem-preco-nem-indisponivel", "sem-pcode"],
)
def test_listagem_sem_estrutura(html):
    with pytest.raises(ErroParser):
        parse_listagem(html, URL_CATEG_10)


# Contagens de tests/fixtures/liga/listagem_expandida.html impressas na captura (Task 6, Step 11);
# o recorte (scripts/recortar_fixture.py) mantém a grade inteira, então valem igual.
CARTOES_EXPANDIDA = 160
UNICOS_EXPANDIDA = 160
SEM_PRECO_EXPANDIDA = 0


def test_listagem_real_expandida():
    itens = parse_listagem(fixture_liga("listagem_expandida"), URL_CATEG_10)
    assert len(itens) == CARTOES_EXPANDIDA
    assert len(itens) > 40  # os cliques em "Exibir mais" trouxeram cartões
    assert len({i.liga_id for i in itens}) == UNICOS_EXPANDIDA
    assert sum(i.preco_a_partir is None for i in itens) == SEM_PRECO_EXPANDIDA
    assert all(f"pcode={i.liga_id}" in i.url for i in itens)
    assert all(i.preco_a_partir is None or i.preco_a_partir > 0 for i in itens)


def test_pagina_de_produto_no_lugar_da_listagem_continua_erro():
    # Categoria 20 devolveu a página do pcode 106224 (busca com um único resultado redireciona
    # para o produto). O aviso "Nenhum produto de lojas encontrado" ali é um `div` oculto que toda
    # página de produto traz; não é sinal de listagem vazia e a categoria deve contar como falha.
    html = fixture_liga("listagem_vazia")
    assert "Nenhum produto de lojas encontrado" in html
    with pytest.raises(ErroParser):
        parse_listagem(html, URL_CATEG_10)
