import pytest
from fakes import pagina_html

from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon

CAPTCHA = (
    "<html><body><h4>Digite os caracteres que você vê abaixo</h4>"
    '<form method="get" action="/errors/validateCaptcha" name=""><input name="field-keywords"></form>'
    "</body></html>"
)


def test_formulario_de_captcha_e_desafio():
    assert eh_desafio_amazon(pagina_html(CAPTCHA, titulo="Amazon.com.br"))


@pytest.mark.parametrize(
    "html",
    [
        '<form action="/errors/validateCaptcha"></form>',
        "<p>Digite os caracteres que você vê abaixo</p>",
        "<!-- To discuss automated access to Amazon data please contact api-services-support@amazon.com. -->",
    ],
)
def test_cada_marcador_sozinho_e_desafio(html):
    assert eh_desafio_amazon(pagina_html(html))


def test_pagina_comum_nao_e_desafio():
    html = '<html><body><div class="s-main-slot"><form action="/s"><input name="k"></form></div></body></html>'
    assert not eh_desafio_amazon(pagina_html(html, titulo="Amazon.com.br : magic"))
