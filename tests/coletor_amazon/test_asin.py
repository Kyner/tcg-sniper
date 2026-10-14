import pytest

from tcg_sniper.coletor_amazon.asin import MENSAGEM_ENCURTADO, MENSAGEM_SEM_ASIN, LinkInvalido, extrair_asin


@pytest.mark.parametrize(
    ("texto", "asin"),
    [
        ("https://www.amazon.com.br/dp/B0DTMQBLSY", "B0DTMQBLSY"),
        ("https://www.amazon.com.br/MTG-Final-Fantasy-Play-Booster/dp/B0DTMQBLSY/ref=sr_1_1?k=x", "B0DTMQBLSY"),
        ("https://www.amazon.com.br/gp/product/B0DTMQBLSY?psc=1", "B0DTMQBLSY"),
        ("https://www.amazon.com.br/gp/aw/d/B0DTMQBLSY", "B0DTMQBLSY"),
        ("http://amazon.com.br/dp/B0DTMQBLSY", "B0DTMQBLSY"),
        ("amazon.com.br/dp/b0dtmqblsy", "B0DTMQBLSY"),
        ("  https://www.amazon.com.br/dp/B0DTMQBLSY#detalhes  ", "B0DTMQBLSY"),
        ("B0DTMQBLSY", "B0DTMQBLSY"),
        ("b0dtmqblsy", "B0DTMQBLSY"),
    ],
)
def test_extrai_o_asin(texto, asin):
    assert extrair_asin(texto) == asin


@pytest.mark.parametrize("texto", ["https://amzn.to/3abcDEF", "https://a.co/d/abc123", "amzn.com/dp/B0DTMQBLSY"])
def test_recusa_link_encurtado(texto):
    with pytest.raises(LinkInvalido, match="endereço completo"):
        extrair_asin(texto)
    assert MENSAGEM_ENCURTADO.startswith("Abra o link")


@pytest.mark.parametrize(
    "texto",
    [
        "https://www.amazon.com/dp/B0DTMQBLSY",
        "https://www.mercadolivre.com.br/dp/B0DTMQBLSY",
        "https://www.amazon.com.br/s?k=magic",
        "https://www.amazon.com.br/dp/B0DT",
        "B0DT",
        "",
        "caixa de booster",
    ],
)
def test_recusa_sem_asin_ou_outro_dominio(texto):
    with pytest.raises(LinkInvalido) as erro:
        extrair_asin(texto)
    assert str(erro.value) == MENSAGEM_SEM_ASIN
