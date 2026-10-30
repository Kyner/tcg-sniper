"""Testes do NavegadorPlaywright sem abrir um navegador: objetos do Playwright são falsos."""

import pytest
from patchright.sync_api import Error as PatchrightError
from playwright.sync_api import Error as PlaywrightError

from tcg_sniper.coletor_liga.desafio import eh_desafio
from tcg_sniper.coletor_liga.modelos import ErroRede
from tcg_sniper.coletor_liga.navegador import ESPERA_DESAFIO_MS, HOME, NavegadorPlaywright
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

    monkeypatch.setattr(modulo, "sync_patchright", lambda: Inicio())


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


def navegador_com(pagina, na_home=True):
    n = NavegadorPlaywright.__new__(NavegadorPlaywright)
    n._timeout_ms, n._espera_ms = 1_000, 0
    n._eh_desafio = eh_desafio
    n._pagina = pagina
    n._na_home = na_home
    n._espera_desafio_ms = ESPERA_DESAFIO_MS
    return n


class PaginaComHistorico(PaginaPw):
    """Guarda cada `goto` (URL e Referer); o título muda conforme a URL aberta."""

    def __init__(self, titulos=None, erro_home=None):
        super().__init__()
        self.titulos = titulos or {}
        self.erro_home = erro_home
        self.visitas = []

    def goto(self, url, referer=None, **_):
        self.visitas.append((url, referer))
        self.url = url
        self.titulo = self.titulos.get(url, "LigaMagic")
        if url == HOME and self.erro_home:
            raise self.erro_home


def test_primeira_navegacao_passa_pela_home_e_leva_ela_como_referer():
    pagina = PaginaComHistorico()
    n = navegador_com(pagina, na_home=False)
    n.abrir("https://liga.test/p")
    n.abrir("https://liga.test/q")
    assert pagina.visitas == [(HOME, None), ("https://liga.test/p", HOME), ("https://liga.test/q", None)]


def test_desafio_ja_na_home_volta_sem_abrir_a_listagem():
    pagina = PaginaComHistorico(titulos={HOME: "Just a moment..."})
    resultado = navegador_com(pagina, na_home=False).abrir_expandindo("https://liga.test/l", 3, lambda: None)
    assert resultado.pagina.titulo == "Just a moment..."
    assert resultado.cliques == 0
    assert pagina.visitas == [(HOME, None)]


def test_home_fora_do_ar_nao_impede_a_coleta():
    pagina = PaginaComHistorico(erro_home=PatchrightError("net::ERR_TIMED_OUT"))
    resultado = navegador_com(pagina, na_home=False).abrir("https://liga.test/p")
    assert resultado.titulo == "LigaMagic"
    assert pagina.visitas == [(HOME, None), ("https://liga.test/p", None)]


def test_erro_do_patchright_com_desafio_na_tela_devolve_o_desafio():
    pagina = PaginaPw(titulo="Just a moment...", erro_goto=PatchrightError("net::ERR_ABORTED"))
    assert navegador_com(pagina).abrir("https://liga.test/p").titulo == "Just a moment..."


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


class Resposta:
    def __init__(self, status, headers):
        self.status, self.headers = status, headers


class SemBotao:
    first = None

    def __init__(self):
        self.first = self

    def count(self):
        return 0


class PaginaComDesafioQuePassa(PaginaPw):
    """O desafio do Cloudflare fica na tela por `leituras_com_desafio` leituras e depois some sozinho."""

    def __init__(self, leituras_com_desafio, resposta=None):
        super().__init__()
        self.restantes = leituras_com_desafio
        self.resposta = resposta
        self.esperas = 0

    def goto(self, url, **_):
        return self.resposta

    def wait_for_timeout(self, _ms):
        self.esperas += 1

    def title(self):
        if self.restantes > 0:
            self.restantes -= 1
            return "Just a moment..."
        return "Busca | LigaMagic"

    def locator(self, _seletor):
        return SemBotao()


def test_desafio_que_passa_sozinho_devolve_a_pagina_de_verdade():
    pagina = PaginaComDesafioQuePassa(leituras_com_desafio=3)
    resultado = navegador_com(pagina).abrir("https://liga.test/p")
    assert resultado.titulo == "Busca | LigaMagic"
    assert not eh_desafio(resultado)


def test_desafio_que_nao_passa_no_prazo_e_devolvido():
    pagina = PaginaComDesafioQuePassa(leituras_com_desafio=10_000)
    resultado = navegador_com(pagina).abrir("https://liga.test/p")
    assert eh_desafio(resultado)
    # Uma espera da carga e uma por segundo do prazo: não fica preso no desafio.
    assert pagina.esperas == 1 + ESPERA_DESAFIO_MS // 1_000


def test_listagem_com_desafio_que_passa_esquece_o_403_do_desafio():
    # A resposta da navegação foi o desafio (403 com cf-mitigated); depois que ele passa, a página
    # de verdade não pode continuar marcada como desafio por causa desses cabeçalhos.
    resposta = Resposta(403, {"cf-mitigated": "challenge"})
    pagina = PaginaComDesafioQuePassa(leituras_com_desafio=2, resposta=resposta)
    resultado = navegador_com(pagina).abrir_expandindo("https://liga.test/l", 3, lambda: None)
    assert not eh_desafio(resultado.pagina)
    assert resultado.pagina.titulo == "Busca | LigaMagic"


def test_amazon_sem_espera_devolve_o_desafio_na_hora():
    from tcg_sniper.navegador.chromium import NavegadorChromium

    pagina = PaginaComDesafioQuePassa(leituras_com_desafio=1)
    n = NavegadorChromium.__new__(NavegadorChromium)
    n._timeout_ms, n._espera_ms, n._eh_desafio, n._pagina = 1_000, 0, eh_desafio, pagina
    assert eh_desafio(n.abrir("https://loja.test/p"))
