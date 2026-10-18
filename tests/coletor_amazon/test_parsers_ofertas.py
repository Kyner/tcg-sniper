import json
from decimal import Decimal

import pytest
from fakes import DIR_FIXTURES_AMAZON, fixture_amazon
from fakes_ofertas import bloco_oferta, html_ofertas

from tcg_sniper.coletor_amazon.parsers import parse_ofertas
from tcg_sniper.db.models import Envio
from tcg_sniper.parsing import ErroParser

ESPERADO = json.loads((DIR_FIXTURES_AMAZON / "esperado.json").read_text(encoding="utf-8"))
NOMES_DOS_CAMPOS = {"vendedor": "vendedor_nome"}
AVALIACAO = "A classificação do vendedor é 5 de 5 estrelas (66 avaliações) 100% positivas nos últimos 12 meses"


def _convertido(campo, valor):
    if campo in ("preco", "preco_de", "pct_positivas"):
        return Decimal(valor)
    if campo == "envio":
        return Envio(valor)
    return valor


@pytest.mark.parametrize("nome", ["ofertas_importada", "ofertas_amazon", "ofertas_fba", "painel_importada"])
def test_ofertas_das_paginas_reais(nome):
    esperado = ESPERADO[nome]
    ofertas = parse_ofertas(fixture_amazon(nome))
    assert len(ofertas) == esperado["num_ofertas"]
    destaque = ofertas[0]
    assert destaque.posicao == 0
    assert (destaque.vendedor_nome, destaque.preco) == (esperado["destaque"]["vendedor"], Decimal(esperado["destaque"]["preco"]))
    for e in esperado["ofertas"]:
        achada = next((o for o in ofertas if o.vendedor_nome == e["vendedor"] and o.preco == Decimal(e["preco"])), None)
        assert achada is not None, e
        for campo, valor in e.items():
            assert getattr(achada, NOMES_DOS_CAMPOS.get(campo, campo)) == _convertido(campo, valor), campo
    assert all(o.preco > 0 for o in ofertas)


def test_o_importado_real_tem_oferta_dos_eua():
    assert any(o.importada and o.origem_envio == "Estados Unidos" for o in parse_ofertas(fixture_amazon("ofertas_importada")))


def test_preco_do_rotulo_de_acessibilidade_com_desconto_e_preco_de():
    [oferta] = parse_ofertas(html_ofertas(bloco_oferta("R$ 326,17 com 16 por cento de desconto", de="R$ 388,91")))
    assert (oferta.preco, oferta.preco_de) == (Decimal("326.17"), Decimal("388.91"))


def test_lojista_fba_importado_com_avaliacao_prime_e_cupom():
    [oferta] = parse_ofertas(
        html_ofertas(
            bloco_oferta(origem="Estados Unidos", avaliacao=AVALIACAO, prime=True, internacional=True,
                         cupom="15% off na 1ª compra com cartão Amazon")
        )
    )
    assert (oferta.vendedor_nome, oferta.seller_id, oferta.envio) == ("Shazaar", "A2SHZ", Envio.FBA)
    assert (oferta.origem_envio, oferta.importada, oferta.prime) == ("Estados Unidos", True, True)
    assert (oferta.pct_positivas, oferta.num_avaliacoes) == (Decimal(100), 66)
    assert oferta.cupom == "15% off na 1ª compra com cartão Amazon"  # sem engolir o "Vendido por" seguinte
    assert (oferta.condicao, oferta.posicao) == ("novo", 1)


def test_vendido_pela_amazon_sem_bloco_de_envio():
    [oferta] = parse_ofertas(html_ofertas(bloco_oferta("R$ 314,11", "Amazon.com.br", seller_id=None, envia=None, destaque=True)))
    assert (oferta.envio, oferta.seller_id, oferta.posicao, oferta.importada) == (Envio.AMAZON, "amazon", 0, False)


def test_lojista_com_envio_proprio_e_usado():
    [oferta] = parse_ofertas(html_ofertas(bloco_oferta(vendedor="Loja X", seller_id="AX", envia="Loja X", condicao="Usado - Muito bom")))
    assert (oferta.envio, oferta.condicao) == (Envio.PROPRIO, "usado")


def test_cupom_de_codigo():
    [oferta] = parse_ofertas(html_ofertas(bloco_oferta(cupom="Economize com cupom de desconto CARTAO15OFF")))
    assert oferta.cupom == "cupom de desconto CARTAO15OFF"


def test_destaque_repetido_na_lista_conta_uma_vez_e_a_posicao_segue_o_bloco():
    ofertas = parse_ofertas(
        html_ofertas(
            bloco_oferta("R$ 314,11", "Amazon.com.br", seller_id=None, envia=None, destaque=True),
            bloco_oferta("R$ 314,11", "Amazon.com.br", seller_id=None, envia=None),
            bloco_oferta("R$ 275,91"),
        )
    )
    assert [(o.vendedor_nome, o.posicao) for o in ofertas] == [("Amazon.com.br", 0), ("Shazaar", 2)]


def test_oferta_sem_preco_e_descartada_sem_mudar_a_posicao_das_outras():
    ofertas = parse_ofertas(html_ofertas(bloco_oferta(""), bloco_oferta("R$ 275,91")))
    assert [(o.vendedor_nome, o.posicao) for o in ofertas] == [("Shazaar", 2)]


def test_painel_sem_ofertas_devolve_lista_vazia():
    assert parse_ofertas(html_ofertas()) == []


def test_pagina_sem_painel_levanta_erro_parser():
    with pytest.raises(ErroParser, match="painel de ofertas"):
        parse_ofertas("<html><body><p>Página não encontrada</p></body></html>")


def test_cupom_real_com_espacos_duplos():
    # Nas páginas reais vem "15%  off" (dois espaços) e o texto segue até o ponto.
    ofertas = parse_ofertas(fixture_amazon("ofertas_importada"))
    shazaar = next(o for o in ofertas if o.vendedor_nome == "Shazaar")
    assert shazaar.cupom == "15% off na 1ª compra com cartão Amazon"


def test_usado_como_novo_e_usado():
    [oferta] = parse_ofertas(html_ofertas(bloco_oferta(condicao="Usado - Como novo")))
    assert oferta.condicao == "usado"
