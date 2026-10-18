from datetime import UTC, datetime
from decimal import Decimal

from tcg_sniper.db.models import Envio
from tcg_sniper.oportunidades.mensagens import Detalhes, mensagem_oportunidade
from tcg_sniper.oportunidades.motor import Leitura, RefLiga, Vendedor

AGORA = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)
NOME = "Caixa de Booster - Final Fantasy - Booster de Jogo"


def test_mensagem_vendido_pela_amazon_com_resumo_da_liga():
    texto = mensagem_oportunidade(
        nome_produto=NOME,
        leitura=Leitura(Decimal("599.90"), Envio.AMAZON, None),
        ref=RefLiga(Decimal("889.00"), AGORA, num_lojas=12, preco_medio=Decimal("910.00")),
        url_amazon="https://www.amazon.com.br/dp/B0TESTE123",
        host="host.test",
        produto_id=123,
    )
    assert texto == (
        "Oportunidade: Caixa de Booster - Final Fantasy - Booster de Jogo\n"
        "Amazon: R$ 599,90 (vendido pela Amazon), 32% abaixo da Liga\n"
        "Liga: a partir de R$ 889,00, 12 lojas, média de venda R$ 910,00\n"
        "https://www.amazon.com.br/dp/B0TESTE123\n"
        "Admin: http://host.test:8000/produto/123"
    )


def test_mensagem_fba_sem_resumo_da_liga():
    texto = mensagem_oportunidade(
        nome_produto=NOME,
        leitura=Leitura(Decimal("599.90"), Envio.FBA, Vendedor("Loja X", Decimal("97.50"), 2340)),
        ref=RefLiga(Decimal("889.00"), AGORA),
        url_amazon="https://www.amazon.com.br/dp/B0TESTE123",
        host="host.test",
        produto_id=123,
    )
    linhas = texto.split("\n")
    assert linhas[1] == (
        "Amazon: R$ 599,90 (vendido por Loja X (97,5% de 2.340 avaliações), enviado pela Amazon), 32% abaixo da Liga"
    )
    assert linhas[2] == "Liga: a partir de R$ 889,00"


def test_mensagem_mostra_a_opcao_da_variacao():
    texto = mensagem_oportunidade(
        nome_produto=NOME,
        leitura=Leitura(Decimal("599.90"), Envio.AMAZON, None),
        ref=RefLiga(Decimal("889.00"), AGORA),
        url_amazon="https://www.amazon.com.br/dp/B0TESTE123",
        host="host.test",
        produto_id=123,
        variacao="Collector Booster Box",
    )
    linhas = texto.split("\n")
    assert linhas[1] == "Amazon (Collector Booster Box): R$ 599,90 (vendido pela Amazon), 32% abaixo da Liga"


def test_mensagem_com_preco_conferido_sem_frete_importado_prime_e_cupom():
    texto = mensagem_oportunidade(
        nome_produto="Aetherdrift Commander Deck - Eternal Might",
        leitura=Leitura(Decimal("285.99"), Envio.FBA, Vendedor("Shazaar", Decimal(100), 66)),
        ref=RefLiga(Decimal("400.00"), AGORA),
        url_amazon="https://www.amazon.com.br/dp/B0DNV55QBS",
        host="host.test",
        produto_id=7,
        detalhes=Detalhes(
            preco_conferido=Decimal("285.99"), impostos=Decimal("48.26"), frete=Decimal("12.50"), importada=True,
            origem_envio="Estados Unidos", prime=True, cupom="15% off na 1ª compra com cartão Amazon",
        ),
    )
    linhas = texto.split("\n")
    assert linhas[1] == (
        "Amazon: R$ 285,99, preço conferido (sem frete), impostos R$ 48,26 inclusos, frete R$ 12,50 à parte "
        "(vendido por Shazaar (100% de 66 avaliações), enviado pela Amazon · importado (EUA) · Prime), "
        "28% abaixo da Liga"
    )
    assert linhas[2] == "Cupom: 15% off na 1ª compra com cartão Amazon (condicional, não descontado)"
    assert linhas[3].startswith("Liga: a partir de R$ 400,00")


def test_mensagem_com_preco_anunciado_nao_conferido():
    texto = mensagem_oportunidade(
        nome_produto=NOME,
        leitura=Leitura(Decimal("275.91"), Envio.AMAZON, None),
        ref=RefLiga(Decimal("400.00"), AGORA),
        url_amazon="https://www.amazon.com.br/dp/B0TESTE123",
        host="host.test",
        produto_id=1,
        detalhes=Detalhes(motivo_nao_conferido="conferência desligada"),
    )
    assert texto.split("\n")[1] == (
        "Amazon: R$ 275,91, preço anunciado, não conferido (conferência desligada) (vendido pela Amazon), 31% abaixo da Liga"
    )


def test_mensagem_nao_conferida_sem_motivo_diz_aguardando_e_importado_sem_origem():
    texto = mensagem_oportunidade(
        nome_produto=NOME,
        leitura=Leitura(Decimal("275.91"), Envio.AMAZON, None),
        ref=RefLiga(Decimal("400.00"), AGORA),
        url_amazon="https://www.amazon.com.br/dp/B0TESTE123",
        host="host.test",
        produto_id=1,
        detalhes=Detalhes(importada=True),
    )
    assert "não conferido (aguardando conferência) (vendido pela Amazon · importado)" in texto


def test_mensagem_conferida_sem_impostos_nem_frete_so_diz_sem_frete():
    texto = mensagem_oportunidade(
        nome_produto=NOME,
        leitura=Leitura(Decimal("275.91"), Envio.AMAZON, None),
        ref=RefLiga(Decimal("400.00"), AGORA),
        url_amazon="https://www.amazon.com.br/dp/B0TESTE123",
        host="host.test",
        produto_id=1,
        detalhes=Detalhes(preco_conferido=Decimal("275.91")),
    )
    assert texto.split("\n")[1] == (
        "Amazon: R$ 275,91, preço conferido (sem frete) (vendido pela Amazon), 31% abaixo da Liga"
    )
