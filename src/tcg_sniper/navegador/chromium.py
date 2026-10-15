from collections.abc import Callable
from pathlib import Path
from typing import Self

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from tcg_sniper.navegador.modelos import ErroRede, Pagina


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
