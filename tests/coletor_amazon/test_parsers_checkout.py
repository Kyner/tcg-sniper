import json
from decimal import Decimal

import pytest
from fakes import DIR_FIXTURES_AMAZON, fixture_amazon, pagina_html
from fakes_checkout import carrinho, checkout_endereco, checkout_resumo, login

from tcg_sniper.coletor_amazon.parsers_checkout import (
    Etapa,
    ResumoCheckout,
    eh_login,
    parse_carrinho,
    parse_resumo_checkout,
)
from tcg_sniper.parsing import ErroParser

ESPERADO = json.loads((DIR_FIXTURES_AMAZON / "esperado.json").read_text(encoding="utf-8"))


def _dinheiro(valor):
    return None if valor is None else Decimal(valor)


@pytest.mark.parametrize("nome", ["carrinho_inicial", "carrinho_um_item", "carrinho_vazio"])
def test_carrinhos_reais(nome):
    esperado = ESPERADO[nome]
    c = parse_carrinho(fixture_amazon(nome))
    assert (c.contador, list(c.asins_ativos)) == (esperado["contador"], esperado["asins_ativos"])
    if "subtotal" in esperado:
        assert c.subtotal == _dinheiro(esperado["subtotal"])


@pytest.mark.parametrize("nome", [n for n in ("checkout_endereco", "checkout_resumo", "login") if n in ESPERADO])
def test_checkout_e_login_reais(nome):
    esperado = ESPERADO[nome]
    resumo = parse_resumo_checkout(pagina_html(fixture_amazon(nome)))
    assert resumo.etapa is Etapa(esperado["etapa"])
    for campo in ("itens", "frete", "impostos", "total"):
        if campo in esperado:
            assert getattr(resumo, campo) == _dinheiro(esperado[campo]), campo


def test_carrinho_conta_so_os_ativos():
    c = parse_carrinho(carrinho("B0ALVO0001", salvos=("B0SALVO001",), subtotal="R$ 275,91").html)
    assert (c.contador, c.asins_ativos, c.subtotal) == (1, ("B0ALVO0001",), Decimal("275.91"))


def test_carrinho_so_com_salvos_esta_vazio():
    c = parse_carrinho(carrinho(salvos=("B0SALVO001",)).html)
    assert (c.contador, c.asins_ativos, c.subtotal) == (0, (), None)


def test_contador_ilegivel_vira_none():
    c = parse_carrinho(
        '<html><body><span id="nav-cart-count">?</span><div data-name="Active Items"></div></body></html>'
    )
    assert c.contador is None


def test_pagina_que_nao_e_carrinho_levanta():
    with pytest.raises(ErroParser):
        parse_carrinho("<html><body>outra página</body></html>")


CONTADOR = '<span id="nav-cart-count">0</span>'


@pytest.mark.parametrize("nome", ["login", "captcha", "checkout_resumo"])
def test_so_o_contador_nao_e_carrinho_vazio(nome):
    # login, CAPTCHA e outras páginas mostram o contador do cabeçalho, mas não o carrinho ativo
    html = fixture_amazon(nome).replace("<body>", f"<body>{CONTADOR}", 1)
    with pytest.raises(ErroParser):
        parse_carrinho(html)


def test_resumo_com_impostos_de_importacao():
    assert parse_resumo_checkout(checkout_resumo()) == ResumoCheckout(
        Etapa.RESUMO, Decimal("237.73"), Decimal("0.00"), Decimal("48.26"), Decimal("285.99")
    )


def test_resumo_nacional_sem_impostos_e_frete_gratis():
    resumo = parse_resumo_checkout(checkout_resumo("R$ 1.299,90", "Grátis", None, "R$ 1.299,90"))
    assert resumo == ResumoCheckout(Etapa.RESUMO, Decimal("1299.90"), Decimal("0.00"), None, Decimal("1299.90"))


def test_etapa_do_endereco_nao_expoe_valores_finais():
    resumo = parse_resumo_checkout(checkout_endereco())
    assert resumo == ResumoCheckout(Etapa.ENDERECO, None, None, None, None, total_estimado=Decimal("237.73"))


def test_endereco_real_so_tem_total_estimado():
    resumo = parse_resumo_checkout(pagina_html(fixture_amazon("checkout_endereco")))
    assert (resumo.etapa, resumo.total, resumo.total_estimado) == (Etapa.ENDERECO, None, Decimal("251.49"))


def test_resumo_sem_itens_e_desconhecido():
    pagina = pagina_html(
        '<html><body><ul id="subtotals-marketplace-table">Frete: R$ 0,00 Total do pedido: R$ 285,99</ul></body></html>'
    )
    assert parse_resumo_checkout(pagina) == ResumoCheckout(Etapa.DESCONHECIDA, None, None, None, None)


def test_resumo_sem_total_do_pedido_e_desconhecido():
    pagina = pagina_html(
        '<html><body><ul id="subtotals-marketplace-table">Itens: R$ 237,73 Frete: R$ 0,00</ul></body></html>'
    )
    assert parse_resumo_checkout(pagina) == ResumoCheckout(Etapa.DESCONHECIDA, None, None, None, None)


def test_itens_e_total_vem_do_mesmo_bloco():
    # o bloco do resumo existe sem "Total do pedido": o texto solto em body não completa o resumo
    pagina = pagina_html(
        '<html><body><ul id="subtotals-marketplace-table">Itens: R$ 237,73</ul>'
        "<div>Total do pedido: R$ 285,99</div></body></html>"
    )
    assert parse_resumo_checkout(pagina).etapa is Etapa.DESCONHECIDA


def test_body_so_sem_nenhum_bloco_do_resumo():
    pagina = pagina_html(
        "<html><body><div>Itens: R$ 10,00 Frete: R$ 1,00 Total do pedido: R$ 11,00</div></body></html>"
    )
    assert parse_resumo_checkout(pagina) == ResumoCheckout(
        Etapa.RESUMO, Decimal("10.00"), Decimal("1.00"), None, Decimal("11.00")
    )


def test_frete_ilegivel_fica_none():
    resumo = parse_resumo_checkout(checkout_resumo(frete="A calcular", impostos=None))
    assert (resumo.etapa, resumo.frete, resumo.total) == (Etapa.RESUMO, None, Decimal("285.99"))


def test_botao_continuar_sem_rotulo_de_entregar_nao_e_o_endereco():
    botao = '<span id="checkout-primary-continue-button-id"><input data-testid="bottom-continue-button" type="submit" value="Usar esta forma de pagamento"></span>'
    assert parse_resumo_checkout(checkout_endereco(botao=botao)).etapa is Etapa.DESCONHECIDA


def test_login_pela_url_ou_pelo_formulario():
    assert eh_login(login())
    assert eh_login(pagina_html("<html><body>x</body></html>", url="https://www.amazon.com.br/ap/signin?x=1"))
    assert parse_resumo_checkout(login()).etapa is Etapa.LOGIN
    assert not eh_login(checkout_resumo())


def test_passo_desconhecido():
    pagina = pagina_html(
        "<html><body>Escolha uma forma de pagamento</body></html>", url="https://www.amazon.com.br/checkout/p/x/pay"
    )
    assert parse_resumo_checkout(pagina).etapa is Etapa.DESCONHECIDA


def test_todo_resumo_real_fecha_itens_frete_impostos_e_total():
    resumos = []
    for caminho in sorted(DIR_FIXTURES_AMAZON.glob("*.html")):
        resumo = parse_resumo_checkout(pagina_html(caminho.read_text(encoding="utf-8")))
        if resumo.etapa is Etapa.RESUMO:
            resumos.append(caminho.name)
            assert resumo.itens + (resumo.frete or 0) + (resumo.impostos or 0) == resumo.total, caminho.name
    assert resumos  # há ao menos um resumo real (checkout_resumo.html)
