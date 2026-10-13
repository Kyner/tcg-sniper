from pathlib import Path
from typing import Protocol, Self

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from tcg_sniper.coletor_liga.modelos import ErroRede, Pagina


class Navegador(Protocol):
    def abrir(self, url: str) -> Pagina:
        """Abre a URL e devolve a página renderizada. Lança ErroRede em falha de navegação."""


class NavegadorPlaywright:
    """Chromium visível com perfil persistente. Use como context manager."""

    def __init__(self, dir_perfil: Path, timeout_ms: int = 45_000, espera_pos_carga_ms: int = 2_000):
        self._dir_perfil = dir_perfil
        self._timeout_ms = timeout_ms
        self._espera_ms = espera_pos_carga_ms

    def __enter__(self) -> Self:
        self._dir_perfil.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._contexto = self._playwright.chromium.launch_persistent_context(
            str(self._dir_perfil),
            headless=False,
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport={"width": 1366, "height": 768},
        )
        paginas = self._contexto.pages
        self._pagina = paginas[0] if paginas else self._contexto.new_page()
        return self

    def __exit__(self, *_exc) -> None:
        self._contexto.close()
        self._playwright.stop()

    def abrir(self, url: str) -> Pagina:
        try:
            resposta = self._pagina.goto(url, wait_until="load", timeout=self._timeout_ms)
            self._pagina.wait_for_timeout(self._espera_ms)
            return Pagina(
                url=self._pagina.url,
                status=resposta.status if resposta else 0,
                html=self._pagina.content(),
                titulo=self._pagina.title(),
                headers=dict(resposta.headers) if resposta else {},
            )
        except PlaywrightError as erro:
            raise ErroRede(f"{url}: {erro}") from erro
