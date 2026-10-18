from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from tcg_sniper.avisos.catalogo import CATALOGO, Negrito, TipoAviso
from tcg_sniper.avisos.formato import aviso_de, formatar
from tcg_sniper.db.models import Envio
from tcg_sniper.oportunidades.mensagens import Detalhes, dados_oportunidade
from tcg_sniper.oportunidades.motor import Leitura, RefLiga, Vendedor

AGORA = datetime(2026, 10, 18, 13, 42, tzinfo=UTC)
SP = ZoneInfo("America/Sao_Paulo")
URL = "https://www.amazon.com.br/dp/B0TESTE123"
NOME = "Final Fantasy - Caixa de Booster de Jogo"


def texto(dados):
    return formatar(aviso_de(TipoAviso.OPORTUNIDADE, dados, AGORA), SP, "192.168.0.10", estrito=True)


def test_modelo_do_spec():
    dados = dados_oportunidade(
        nome_produto=NOME,
        leitura=Leitura(Decimal("1299.90"), Envio.AMAZON, None),
        ref=RefLiga(Decimal("1589.00"), AGORA, num_lojas=12, preco_medio=Decimal("1640.00")),
        url_amazon=URL,
        detalhes=Detalhes(preco_conferido=Decimal("1299.90"), prime=True),
    )
    assert dados == CATALOGO[TipoAviso.OPORTUNIDADE].exemplo
    assert texto(dados) == (
        "💰 *Oportunidade · 18% abaixo da Liga*\n"
        "*Final Fantasy - Caixa de Booster de Jogo*\n"
        "• Amazon: *R$ 1.299,90* (conferido, com impostos; frete à parte)\n"
        "• Vendido por: Amazon · Prime\n"
        "• Liga: a partir de R$ 1.589,00 · 12 lojas · média R$ 1.640,00\n"
        "https://www.amazon.com.br/dp/B0TESTE123\n"
        "_18/10 10:42 · monitor Amazon_"
    )


def test_fba_nao_conferido_sem_resumo_da_liga():
    dados = dados_oportunidade(
        nome_produto=NOME,
        leitura=Leitura(Decimal("599.90"), Envio.FBA, Vendedor("Loja X", Decimal("97.50"), 2340)),
        ref=RefLiga(Decimal("889.00"), AGORA),
        url_amazon=URL,
        detalhes=Detalhes(motivo_nao_conferido="conferência desligada"),
    )
    assert dados.titulo_extra == "32% abaixo da Liga"
    assert dados.linhas == (
        ("Amazon: ", Negrito("R$ 599,90"), " (anunciado, sem impostos; não conferido: conferência desligada)"),
        "Vendido por: Loja X (97,5% de 2.340 avaliações) · enviado pela Amazon",
        "Liga: a partir de R$ 889,00",
    )


def test_sem_motivo_diz_aguardando_conferencia():
    dados = dados_oportunidade(
        nome_produto=NOME, leitura=Leitura(Decimal("599.90"), Envio.AMAZON, None), ref=RefLiga(Decimal("889.00"), AGORA),
        url_amazon=URL, detalhes=Detalhes(),
    )
    assert dados.linhas[0][2] == " (anunciado, sem impostos; não conferido: aguardando conferência)"


def test_variacao_vai_no_rotulo_da_amazon():
    dados = dados_oportunidade(
        nome_produto=NOME, leitura=Leitura(Decimal("599.90"), Envio.AMAZON, None), ref=RefLiga(Decimal("889.00"), AGORA),
        url_amazon=URL, variacao="Collector Booster Box",
    )
    assert dados.linhas[0] == ("Amazon (Collector Booster Box): ", Negrito("R$ 599,90"))


def test_conferido_com_impostos_frete_importado_prime_e_cupom():
    dados = dados_oportunidade(
        nome_produto="Aetherdrift Commander Deck - Eternal Might",
        leitura=Leitura(Decimal("285.99"), Envio.FBA, Vendedor("Shazaar", Decimal(100), 66)),
        ref=RefLiga(Decimal("400.00"), AGORA),
        url_amazon="https://www.amazon.com.br/dp/B0DNV55QBS",
        detalhes=Detalhes(
            preco_conferido=Decimal("285.99"), impostos=Decimal("48.26"), frete=Decimal("12.50"), importada=True,
            origem_envio="Estados Unidos", prime=True, cupom="15% off na 1ª compra com cartão Amazon",
        ),
    )
    assert dados.titulo_extra == "28% abaixo da Liga"
    assert dados.linhas == (
        ("Amazon: ", Negrito("R$ 285,99"), " (conferido, com impostos de R$ 48,26; frete R$ 12,50 à parte)"),
        "Vendido por: Shazaar (100% de 66 avaliações) · enviado pela Amazon · importado (EUA) · Prime",
        "Liga: a partir de R$ 400,00",
        "Cupom: 15% off na 1ª compra com cartão Amazon (condicional, não descontado)",
    )


def test_frete_zero_e_frete_gratis():
    dados = dados_oportunidade(
        nome_produto=NOME, leitura=Leitura(Decimal("599.90"), Envio.AMAZON, None), ref=RefLiga(Decimal("889.00"), AGORA),
        url_amazon=URL, detalhes=Detalhes(preco_conferido=Decimal("599.90"), frete=Decimal("0.00")),
    )
    assert dados.linhas[0][2] == " (conferido, com impostos; frete grátis)"


def test_nome_com_marcador_e_escapado_no_texto():
    dados = dados_oportunidade(
        nome_produto="Caixa *Edição* _Especial_", leitura=Leitura(Decimal("599.90"), Envio.AMAZON, None),
        ref=RefLiga(Decimal("889.00"), AGORA), url_amazon=URL,
    )
    assert "\n*Caixa ∗Edição∗ ˍEspecialˍ*\n" in texto(dados)
