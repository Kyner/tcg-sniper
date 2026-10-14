import pytest
from playwright.sync_api import Error as PlaywrightError

from tcg_sniper.navegador.chromium import NavegadorChromium
from tcg_sniper.navegador.modelos import ErroRede


class PaginaPw:
    def __init__(self, titulo="Loja", html="<html></html>", erro_goto=None):
        self.titulo, self.html, self.url = titulo, html, "https://loja.test/x"
        self.erro_goto = erro_goto

    def goto(self, url, **_):
        if self.erro_goto:
            raise self.erro_goto

    def wait_for_timeout(self, _ms):
        pass

    def content(self):
        return self.html

    def title(self):
        return self.titulo


def navegador_com(pagina, detector):
    n = NavegadorChromium.__new__(NavegadorChromium)
    n._timeout_ms, n._espera_ms, n._eh_desafio = 1_000, 0, detector
    n._pagina = pagina
    return n


def test_erro_de_navegacao_com_desafio_do_detector_injetado_devolve_a_pagina():
    pagina = PaginaPw(titulo="Verificação", erro_goto=PlaywrightError("net::ERR_ABORTED"))
    resultado = navegador_com(pagina, lambda p: p.titulo == "Verificação").abrir("https://loja.test/p")
    assert resultado.titulo == "Verificação"


def test_erro_de_navegacao_sem_desafio_levanta_erro_rede():
    pagina = PaginaPw(erro_goto=PlaywrightError("net::ERR_TIMED_OUT"))
    with pytest.raises(ErroRede, match="ERR_TIMED_OUT"):
        navegador_com(pagina, lambda p: False).abrir("https://loja.test/p")
