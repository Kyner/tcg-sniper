import pytest
from playwright.sync_api import Error as PlaywrightError

from tcg_sniper.navegador.chromium import JS_DESCREVER, TIMEOUT_CLIQUE_MS, NavegadorChromium
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


class ElementoPw:
    def __init__(self, html, texto, erro_ensaio=None):
        self.html, self.texto, self.erro_ensaio = html, texto, erro_ensaio
        self.eventos: list[tuple[str, int | None]] = []

    @property
    def cliques(self):
        return sum(1 for evento, _ in self.eventos if evento == "clique")

    def evaluate(self, _js):
        self.eventos.append(("descrever", None))
        return [self.html, self.texto]

    def click(self, trial=False, timeout=None, **_):
        if trial:
            self.eventos.append(("ensaio", timeout))
            if self.erro_ensaio:
                raise self.erro_ensaio
        else:
            self.eventos.append(("clique", timeout))


class LocalizadoPw:
    def __init__(self, elementos, indice):
        self.elementos, self.indice = elementos, indice

    def element_handle(self, **_):
        if self.indice >= len(self.elementos):
            raise PlaywrightError("Timeout 1000ms exceeded")
        return self.elementos[self.indice]


class LocatorPw:
    def __init__(self, elementos):
        self.elementos = elementos

    def nth(self, indice):
        return LocalizadoPw(self.elementos, indice)


class PaginaClicavel(PaginaPw):
    def __init__(self, elementos, **kw):
        super().__init__(**kw)
        self.elementos = elementos

    def locator(self, seletor):
        assert seletor.startswith("css:light="), seletor  # só DOM light, como o selectolax
        return LocatorPw(self.elementos.get(seletor.removeprefix("css:light="), []))

    def wait_for_load_state(self, *_a, **_k):
        pass


def test_clicar_confere_o_proprio_elemento_e_clica_nele():
    botao = ElementoPw('<input name="submit.addToCart">', "Adicionar ao carrinho")
    vistos = []
    n = navegador_com(PaginaClicavel({"#b": [botao]}), lambda p: False)
    n.clicar("#b", 0, lambda html, texto: vistos.append((html, texto)))
    assert vistos == [('<input name="submit.addToCart">', "Adicionar ao carrinho")]
    assert botao.cliques == 1


def test_guarda_que_levanta_impede_o_clique():
    botao = ElementoPw('<input name="placeYourOrder1">', "Confirmar pedido")
    n = navegador_com(PaginaClicavel({"#b": [botao]}), lambda p: False)

    def recusar(_html, _texto):
        raise RuntimeError("proibido")

    with pytest.raises(RuntimeError):
        n.clicar("#b", 0, recusar)
    assert botao.cliques == 0


def test_elemento_ausente_vira_erro_rede():
    n = navegador_com(PaginaClicavel({}), lambda p: False)
    with pytest.raises(ErroRede, match="não encontrado"):
        n.clicar("#nada", 0, lambda h, t: None)


def test_ensaio_antes_da_guarda_e_clique_com_prazo_curto():
    botao = ElementoPw('<input name="submit.addToCart">', "Adicionar ao carrinho")
    n = navegador_com(PaginaClicavel({"#b": [botao]}), lambda p: False)
    n.clicar("#b", 0, lambda html, texto: botao.eventos.append(("guarda", None)))
    assert botao.eventos == [("ensaio", 1_000), ("descrever", None), ("guarda", None), ("clique", TIMEOUT_CLIQUE_MS)]


def test_guarda_que_recusa_depois_do_ensaio_nao_clica():
    botao = ElementoPw('<input name="placeYourOrder1">', "Confirmar pedido")
    n = navegador_com(PaginaClicavel({"#b": [botao]}), lambda p: False)

    def recusar(_html, _texto):
        raise RuntimeError("proibido")

    with pytest.raises(RuntimeError):
        n.clicar("#b", 0, recusar)
    assert [e for e, _ in botao.eventos] == ["ensaio", "descrever"]


def test_ensaio_que_falha_vira_erro_rede_sem_guarda_nem_clique():
    botao = ElementoPw("<input>", "", erro_ensaio=PlaywrightError("element is not visible"))
    n = navegador_com(PaginaClicavel({"#b": [botao]}), lambda p: False)
    with pytest.raises(ErroRede, match="não encontrado"):
        n.clicar("#b", 0, lambda h, t: pytest.fail("a guarda não devia rodar"))
    assert [e for e, _ in botao.eventos] == ["ensaio"]


def test_js_descrever_inclui_rotulo_e_contexto():
    for trecho in ("aria-labelledby", "aria-describedby", "closest(", "formAction", "e.form", "e.title", "innerText"):
        assert trecho in JS_DESCREVER


class PaginaQueSomeNaEspera(PaginaPw):
    def __init__(self):
        super().__init__()
        self.leituras = 0

    def wait_for_selector(self, *_a, **_k):
        pass

    def content(self):
        self.leituras += 1
        if self.leituras > 1:
            raise PlaywrightError("Target page, context or browser has been closed")
        return self.html


def test_abrir_e_esperar_com_pagina_ilegivel_vira_erro_rede():
    n = navegador_com(PaginaQueSomeNaEspera(), lambda p: False)
    with pytest.raises(ErroRede, match="ilegível"):
        n.abrir_e_esperar("https://loja.test/p", "#aod-offer")


def test_chromium_abre_sem_se_anunciar_como_automatizado(monkeypatch, tmp_path):
    from tcg_sniper.navegador import chromium as modulo

    recebido = {}

    class Contexto:
        def __init__(self):
            self.pages = [PaginaPw()]

        def close(self):
            pass

    class Playwright:
        def __init__(self):
            self.chromium = self

        def launch_persistent_context(self, *_a, **kwargs):
            recebido.update(kwargs)
            return Contexto()

        def stop(self):
            pass

    class Inicio:
        def start(self):
            return Playwright()

    monkeypatch.setattr(modulo, "sync_playwright", lambda: Inicio())
    with NavegadorChromium(tmp_path / "perfil", lambda p: False):
        pass
    # Sem isso o navigator.webdriver fica true e o desafio do Cloudflare entra em loop mesmo
    # resolvido à mão no noVNC.
    assert "--enable-automation" in recebido["ignore_default_args"]
    assert "--disable-blink-features=AutomationControlled" in recebido["args"]
