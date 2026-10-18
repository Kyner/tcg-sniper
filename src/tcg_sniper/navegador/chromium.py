from collections.abc import Callable
from pathlib import Path
from typing import Self

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from tcg_sniper.navegador.base import Guarda
from tcg_sniper.navegador.modelos import ErroRede, Pagina

# O que a guarda confere, igual a `coletor_amazon.cliques.descrever_elemento`: [contexto, rótulo].
# Contexto: HTML do elemento, HTML e texto do botão/link/form em volta (limitados), `title`, textos de
# `aria-describedby`, `formAction` e a ação do form. Rótulo: texto visível, `value`, `aria-label` e
# textos de `aria-labelledby` (a Amazon põe o texto do botão num span irmão do input).
JS_DESCREVER = r"""e => {
  const limite = 4000;
  const ids = a => (e.getAttribute(a) || '').split(/\s+/).filter(Boolean).map(i => {
    const n = document.getElementById(i);
    return n ? (n.innerText || n.textContent || '') : '';
  }).join(' ');
  const c = e.closest('.a-button, button, a, [role=button], form');
  const contexto = [
    e.outerHTML,
    c ? c.outerHTML.slice(0, limite) : '',
    c ? (c.innerText || c.textContent || '').slice(0, limite) : '',
    e.title || '',
    ids('aria-describedby'),
    e.formAction || '',
    (e.form && e.form.action) || '',
  ].map(String).join('\n');
  const rotulo = [
    e.innerText || '', e.value || '', e.getAttribute('aria-label') || '', ids('aria-labelledby'),
  ].map(String).join(' ');
  return [contexto, rotulo];
}"""
# O clique de verdade, depois do ensaio e da guarda, tem prazo curto: o elemento já estava pronto, e
# quanto menos tempo entre a conferência e o clique, menos chance de a tela trocar o botão.
TIMEOUT_CLIQUE_MS = 2_000


class NavegadorChromium:
    """Chromium visível com perfil persistente. Use como context manager.

    `eh_desafio` decide se a página na tela é um desafio do site (Cloudflare na Liga, CAPTCHA na
    Amazon): num erro de navegação com o desafio na tela, `abrir` devolve o desafio em vez de
    lançar ErroRede, para quem chamou pausar em vez de tentar de novo."""

    def __init__(
        self,
        dir_perfil: Path,
        eh_desafio: Callable[[Pagina], bool],
        timeout_ms: int = 45_000,
        espera_pos_carga_ms: int = 2_000,
    ):
        self._dir_perfil = dir_perfil
        self._eh_desafio = eh_desafio
        self._timeout_ms = timeout_ms
        self._espera_ms = espera_pos_carga_ms

    def __enter__(self) -> Self:
        self._dir_perfil.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        try:
            self._contexto = self._playwright.chromium.launch_persistent_context(
                str(self._dir_perfil),
                headless=False,
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                # A janela ocupa a tela do Xvfb (1366x768) com abas e barra de endereço visíveis no
                # noVNC; a página usa o espaço que sobra, como num navegador maximizado de verdade.
                no_viewport=True,
                args=["--start-maximized", "--window-position=0,0", "--window-size=1366,768"],
            )
            paginas = self._contexto.pages
            self._pagina = paginas[0] if paginas else self._contexto.new_page()
        except BaseException as erro:
            # Sem isso o driver do Playwright (processo node) fica órfão a cada falha de launch.
            self._playwright.stop()
            if isinstance(erro, PlaywrightError):
                raise ErroRede(f"Chromium não abriu: {erro}") from erro
            raise
        return self

    def __exit__(self, *_exc) -> None:
        try:
            self._contexto.close()
        finally:
            self._playwright.stop()

    def vivo(self) -> bool:
        try:
            return not self._pagina.is_closed() and self._pagina.evaluate("1") == 1
        except PlaywrightError:
            return False

    def _capturar(self, status: int, headers: dict[str, str]) -> Pagina:
        return Pagina(
            url=self._pagina.url,
            status=status,
            html=self._pagina.content(),
            titulo=self._pagina.title(),
            headers=headers,
        )

    def abrir(self, url: str) -> Pagina:
        try:
            resposta = self._pagina.goto(url, wait_until="load", timeout=self._timeout_ms)
            self._pagina.wait_for_timeout(self._espera_ms)
            return self._capturar(
                resposta.status if resposta else 0, dict(resposta.headers) if resposta else {}
            )
        except PlaywrightError as erro:
            # Erro de navegação com o desafio na tela: devolve o desafio (quem chamou pausa) em vez
            # de ErroRede, que levaria a um retry em cima do desafio.
            atual = self._capturar_se_possivel(0, {})
            if atual is not None and self._eh_desafio(atual):
                return atual
            raise ErroRede(f"{url}: {erro}") from erro

    def _capturar_se_possivel(self, status: int, headers: dict[str, str]) -> Pagina | None:
        try:
            return self._capturar(status, headers)
        except PlaywrightError:
            return None

    def atual(self) -> Pagina:
        try:
            return self._capturar(0, {})
        except PlaywrightError as erro:
            raise ErroRede(f"página atual ilegível: {erro}") from erro

    def abrir_e_esperar(self, url: str, seletor: str, timeout_ms: int = 15_000) -> Pagina:
        pagina = self.abrir(url)
        try:
            self._pagina.wait_for_selector(seletor, state="attached", timeout=timeout_ms)
        except PlaywrightError:
            return pagina  # sem o elemento no prazo: quem chamou decide (o parser acusa o layout)
        try:
            self._pagina.wait_for_timeout(self._espera_ms)
            return self._capturar(pagina.status, pagina.headers)
        except PlaywrightError as erro:
            raise ErroRede(f"{url}: página ilegível depois da espera: {erro}") from erro

    def clicar(self, seletor: str, indice: int, guarda: Guarda) -> Pagina:
        try:
            # `css:light=`: só o DOM "light", sem shadow DOM, para o índice bater com o do selectolax.
            elemento = self._pagina.locator(f"css:light={seletor}").nth(indice).element_handle(
                timeout=self._timeout_ms
            )
            # Ensaio (trial): espera o elemento ficar visível, estável e clicável, sem clicar. Assim a
            # espera longa acontece antes da guarda, não entre a guarda e o clique.
            elemento.click(trial=True, timeout=self._timeout_ms)
            html, texto = elemento.evaluate(JS_DESCREVER)
        except PlaywrightError as erro:
            raise ErroRede(f"elemento {seletor} [{indice}] não encontrado: {erro}") from erro
        # A guarda vê o mesmo nó (handle) que vai ser clicado, já pronto para o clique: se a página
        # trocou o botão depois da leitura do HTML, é este que conta.
        guarda(html, texto)
        try:
            elemento.click(timeout=TIMEOUT_CLIQUE_MS)
            self._pagina.wait_for_load_state("load", timeout=self._timeout_ms)
            self._pagina.wait_for_timeout(self._espera_ms)
            return self._capturar(0, {})
        except PlaywrightError as erro:
            raise ErroRede(f"clique em {seletor} [{indice}]: {erro}") from erro
