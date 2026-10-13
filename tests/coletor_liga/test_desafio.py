from fakes import pagina_html

from tcg_sniper.coletor_liga.desafio import eh_desafio

PAGINA_CF = """<!DOCTYPE html><html><head><title>Just a moment...</title></head>
<body><div id="challenge-form"></div>
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script></body></html>"""


def test_titulo_just_a_moment():
    assert eh_desafio(pagina_html("<html></html>", titulo="Just a moment..."))


def test_titulo_em_portugues():
    assert eh_desafio(pagina_html("<html></html>", titulo="Um momento…"))


def test_html_com_formulario_de_desafio():
    assert eh_desafio(pagina_html(PAGINA_CF, titulo=""))


def test_header_cf_mitigated_com_403():
    assert eh_desafio(pagina_html("<html></html>", status=403, headers={"cf-mitigated": "challenge"}))


def test_403_sem_header_cloudflare_nao_e_desafio():
    assert not eh_desafio(pagina_html("<html></html>", status=403))


def test_pagina_normal():
    assert not eh_desafio(pagina_html("<html><body><h1>Caixa de booster</h1></body></html>"))
