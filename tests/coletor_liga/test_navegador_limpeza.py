"""Testes do NavegadorPlaywright sem abrir um navegador: objetos do Playwright são falsos."""

import pytest
from playwright.sync_api import Error as PlaywrightError

from tcg_sniper.coletor_liga.desafio import eh_desafio
from tcg_sniper.coletor_liga.modelos import ErroRede
from tcg_sniper.coletor_liga.navegador import NavegadorPlaywright
from tcg_sniper.navegador import chromium as modulo


class PaginaPw:
    def __init__(self, titulo="LigaMagic", html="<html></html>", url="https://liga.test/x", erro_goto=None):
        self.titulo, self.html, self.url = titulo, html, url
        self.erro_goto = erro_goto
        self.erro_captura = None
        self.fechada = False

    def goto(self, url, **_):
        if self.erro_goto:
            raise self.erro_goto

    def wait_for_timeout(self, _ms):
        pass

    def content(self):
        if self.erro_captura:
            raise self.erro_captura
        return self.html

    def title(self):
        if self.erro_captura:
            raise self.erro_captura
        return self.titulo

    def is_closed(self):
        return self.fechada

    def evaluate(self, _js):
        if self.erro_captura:
            raise self.erro_captura
        return 1


class ContextoPw:
    def __init__(self, pagina, erro_close=None):
        self.pages = [pagina]
        self.erro_close = erro_close

    def close(self):
        if self.erro_close:
            raise self.erro_close


class PlaywrightFalso:
    def __init__(self, contexto=None, erro_launch=None):
        self.parado = False
        self._contexto, self._erro = contexto, erro_launch
        self.chromium = self

    def launch_persistent_context(self, *_a, **_k):
        if self._erro:
            raise self._erro
        return self._contexto

    def stop(self):
        self.parado = True


def instalar(monkeypatch, pw):
    class Inicio:
        def start(self):
            return pw

    monkeypatch.setattr(modulo, "sync_playwright", lambda: Inicio())


def test_falha_no_launch_para_o_playwright_e_vira_erro_rede(monkeypatch, tmp_path):
    pw = PlaywrightFalso(erro_launch=PlaywrightError("perfil travado"))
    instalar(monkeypatch, pw)
    with pytest.raises(ErroRede, match="perfil travado"), NavegadorPlaywright(tmp_path / "perfil"):
        pass
    assert pw.parado


def test_falha_inesperada_no_launch_tambem_para_o_playwright(monkeypatch, tmp_path):
    pw = PlaywrightFalso(erro_launch=RuntimeError("boom"))
    instalar(monkeypatch, pw)
    with pytest.raises(RuntimeError):
        NavegadorPlaywright(tmp_path / "perfil").__enter__()
    assert pw.parado


def test_falha_ao_fechar_o_contexto_ainda_para_o_playwright(monkeypatch, tmp_path):
    pw = PlaywrightFalso(contexto=ContextoPw(PaginaPw(), erro_close=PlaywrightError("já fechado")))
    instalar(monkeypatch, pw)
    with pytest.raises(PlaywrightError), NavegadorPlaywright(tmp_path / "perfil"):
        pass
    assert pw.parado


def navegador_com(pagina):
    n = NavegadorPlaywright.__new__(NavegadorPlaywright)
    n._timeout_ms, n._espera_ms = 1_000, 0
    n._eh_desafio = eh_desafio
    n._pagina = pagina
    return n


def test_abrir_com_erro_mas_tela_de_desafio_devolve_o_desafio():
    pagina = PaginaPw(titulo="Just a moment...", erro_goto=PlaywrightError("net::ERR_ABORTED"))
    resultado = navegador_com(pagina).abrir("https://liga.test/p")
    assert resultado.titulo == "Just a moment..."


def test_abrir_com_erro_sem_desafio_levanta_erro_rede():
    pagina = PaginaPw(erro_goto=PlaywrightError("net::ERR_TIMED_OUT"))
    with pytest.raises(ErroRede, match="ERR_TIMED_OUT"):
        navegador_com(pagina).abrir("https://liga.test/p")


def test_abrir_com_erro_e_captura_impossivel_levanta_erro_rede():
    pagina = PaginaPw(erro_goto=PlaywrightError("Target closed"))
    pagina.erro_captura = PlaywrightError("Target closed")
    with pytest.raises(ErroRede, match="Target closed"):
        navegador_com(pagina).abrir("https://liga.test/p")


def test_vivo_com_pagina_respondendo():
    assert navegador_com(PaginaPw()).vivo() is True


def test_vivo_falso_com_pagina_fechada():
    pagina = PaginaPw()
    pagina.fechada = True
    assert navegador_com(pagina).vivo() is False


def test_vivo_falso_quando_o_navegador_morreu():
    pagina = PaginaPw()
    pagina.erro_captura = PlaywrightError("Target page, context or browser has been closed")
    assert navegador_com(pagina).vivo() is False
