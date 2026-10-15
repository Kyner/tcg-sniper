from datetime import UTC, datetime
from decimal import Decimal

from tcg_sniper.db.models import Envio
from tcg_sniper.oportunidades.mensagens import mensagem_oportunidade
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
