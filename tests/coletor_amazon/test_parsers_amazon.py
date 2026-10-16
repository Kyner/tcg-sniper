from decimal import Decimal

import pytest
from fakes import cartao_busca, fixture_amazon, html_busca, html_produto_amazon

from tcg_sniper.coletor_amazon.modelos import SELLER_AMAZON, AvaliacaoVendedor, OfertaProduto
from tcg_sniper.coletor_amazon.parsers import (
    classificar_envio,
    eh_vendido_pela_amazon,
    parse_busca,
    parse_produto_amazon,
    parse_vendedor,
    url_produto,
)
from tcg_sniper.db.models import Envio
from tcg_sniper.parsing import ErroParser

# Valores lidos à mão nas páginas reais capturadas na Task 6.
TOTAL_RESULTADOS = 13
PRIMEIRO = ("B0HDFVTD4X", "Blissful Eternity Booster Box - Blissful Eternity", Decimal("554.00"))
PATROCINADOS = 0  # a captura não tem nenhum cartão com a marca inline de patrocinado
TOTAL_SEM_RESULTADOS = 0
# Ruling 8: produto_vendido_amazon e produto_indisponivel são derivadas da produto_fba real (mesma
# estrutura de página): nenhuma página real "vendido pela Amazon.com.br" ou "indisponível" foi capturada.
# Seus valores esperados vêm do que foi posto nelas (vendedor e enviador "Amazon.com.br"; sem preço,
# sem vendedor, disponibilidade "Não disponível.").
PRODUTOS = {
    "produto_vendido_amazon": OfertaProduto(
        "B0DTMQBLSY",
        "MTG Final Fantasy - Play Booster - Inglês",
        Decimal("1804.99"),
        "Amazon.com.br",
        SELLER_AMAZON,
        Envio.AMAZON,
    ),
    "produto_fba": OfertaProduto(
        "B0DTMQBLSY",
        "MTG Final Fantasy - Play Booster - Inglês",
        Decimal("1804.99"),
        "PuguBR",
        "ANP69P8PNCJ0B",
        Envio.FBA,
    ),
    "produto_envio_proprio": OfertaProduto(
        "B01CNSPDNA",
        "Thames & Kosmos Magic: Silver Edition Playset with 100 Tricks",
        Decimal("599.47"),
        "Bixemy",
        "A3P8U6BAN7HQM8",
        # A página real só traz o rótulo "Enviado / Vendido" e nenhum bloco "Enviado por": o
        # classificador (vendido_por, enviado_por) não distingue envio próprio disso (Envio.PROPRIO
        # só sai com enviado_por presente, coberto em test_classificar_envio).
        Envio.DESCONHECIDO,
    ),
    "produto_amazon_global": OfertaProduto(
        "B0DTN1MH2J",
        "Magic: The Gathering FINAL FANTASY VI Commander Deck - Revival Trance",
        Decimal("358.78"),
        "Amazon Global",
        SELLER_AMAZON,
        Envio.AMAZON,
    ),
    # Página real com seletor de variações: o título não diz que é a caixa; a opção selecionada diz.
    "produto_variacao": OfertaProduto(
        "B0DTS76B5L",
        "Magic The Gathering - Final Fantasy, multicolorido (Wizards Of The Coast D3868000)",
        Decimal("10999.99"),
        "PuguBR",
        "ANP69P8PNCJ0B",
        Envio.FBA,
        "Collector Booster Box",
    ),
    "produto_indisponivel": OfertaProduto(
        "B0DTMQBLSY", "MTG Final Fantasy - Play Booster - Inglês", None, None, None, Envio.DESCONHECIDO
    ),
}
VENDEDOR = AvaliacaoVendedor("ANP69P8PNCJ0B", "PuguBR", Decimal(100), 2)


def test_busca_real():
    itens = parse_busca(fixture_amazon("busca_resultados"), limite=48)
    assert len(itens) == TOTAL_RESULTADOS
    assert (itens[0].asin, itens[0].titulo, itens[0].preco) == PRIMEIRO
    assert itens[0].url == url_produto(PRIMEIRO[0])
    assert sum(i.patrocinado for i in itens) == PATROCINADOS
    assert all(i.preco is None or i.preco > 0 for i in itens)


def test_busca_respeita_o_limite():
    assert len(parse_busca(fixture_amazon("busca_resultados"), limite=3)) == min(3, TOTAL_RESULTADOS)


def test_busca_sem_resultados():
    assert len(parse_busca(fixture_amazon("busca_sem_resultados"), limite=48)) == TOTAL_SEM_RESULTADOS


def test_cartao_sem_preco_vira_none():
    sem_preco = fixture_amazon("busca_resultados").replace("a-offscreen", "a-sem-preco")
    assert all(i.preco is None for i in parse_busca(sem_preco, limite=48))


@pytest.mark.parametrize("nome", ["vendedor", "produto_fba"])
def test_busca_sem_grade_e_erro(nome):
    with pytest.raises(ErroParser):
        parse_busca(fixture_amazon(nome), limite=10)


@pytest.mark.parametrize("nome", list(PRODUTOS))
def test_produto_real(nome):
    esperado = PRODUTOS[nome]
    assert parse_produto_amazon(fixture_amazon(nome), esperado.asin) == esperado


def test_produto_sem_titulo_e_erro():
    with pytest.raises(ErroParser):
        parse_produto_amazon(fixture_amazon("busca_resultados"), "B000000000")


def test_vendedor_real():
    assert parse_vendedor(fixture_amazon("vendedor"), VENDEDOR.seller_id) == VENDEDOR


def test_vendedor_com_resumo_ilegivel_avisa_no_log_e_devolve_vazio(caplog):
    html = '<html><body><div id="seller-info-feedback-summary">texto novo</div></body></html>'
    avaliacao = parse_vendedor(html, "A1")
    assert (avaliacao.pct_positivas, avaliacao.num_avaliacoes) == (None, None)
    assert "A1" in caplog.text


def test_vendedor_sem_resumo_e_erro():
    with pytest.raises(ErroParser):
        parse_vendedor("<html><body></body></html>", "A1")


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Amazon.com.br", True),
        ("  amazon  ", True),
        ("AMAZON", True),
        ("Amazonas Games", False),
        ("Amazon Global", True),
        ("Loja X", False),
    ],
)
def test_eh_vendido_pela_amazon(texto, esperado):
    assert eh_vendido_pela_amazon(texto) is esperado


@pytest.mark.parametrize(
    ("vendido", "enviado", "envio"),
    [
        ("Amazon.com.br", "Amazon.com.br", Envio.AMAZON),
        ("Amazon.com.br", None, Envio.AMAZON),
        ("Loja X", "Amazon", Envio.FBA),
        ("Loja X", "Amazon.com.br", Envio.FBA),
        ("Amazonas Games", "Amazonas Games", Envio.PROPRIO),
        ("Loja X", "Loja X", Envio.PROPRIO),
        ("Loja X", None, Envio.DESCONHECIDO),
        ("Amazon Global", None, Envio.AMAZON),
        (None, "Amazon", Envio.DESCONHECIDO),
        (None, None, Envio.DESCONHECIDO),
    ],
)
def test_classificar_envio(vendido, enviado, envio):
    assert classificar_envio(vendido, enviado) is envio


def test_variacao_com_duas_dimensoes():
    html = fixture_amazon("produto_variacao").replace(
        "</body>",
        '<span id="inline-twister-expanded-dimension-text-size_name"> 12 unidades </span></body>',
    )
    assert parse_produto_amazon(html, "B0DTS76B5L").variacao == "Collector Booster Box · 12 unidades"


def test_busca_le_imagem():
    html = html_busca(cartao_busca("B0A", "Caixa", "R$ 10,00", imagem="https://m.media-amazon.com/images/I/a._AC_UL320_.jpg"),
                      cartao_busca("B0B", "Outra", None))
    a, b = parse_busca(html, 10)
    assert a.imagem_url == "https://m.media-amazon.com/images/I/a._AC_UL320_.jpg" and b.imagem_url is None


def test_produto_le_imagem_grande_e_ignora_data_uri():
    html = html_produto_amazon("Caixa", "R$ 10,00", None, None, imagem="https://m.media-amazon.com/images/I/a._AC_SL1500_.jpg")
    assert parse_produto_amazon(html, "B0A").imagem_url == "https://m.media-amazon.com/images/I/a._AC_SL1500_.jpg"
    so_data = '<html><body><span id="productTitle">X</span><img id="landingImage" src="data:image/gif;base64,R0lGOD"></body></html>'
    assert parse_produto_amazon(so_data, "B0A").imagem_url is None
