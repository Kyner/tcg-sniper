from collections.abc import Callable
from pathlib import Path
from typing import Protocol, Self

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from tcg_sniper.coletor_liga.desafio import eh_desafio
from tcg_sniper.coletor_liga.modelos import ErroRede, Pagina, PaginaExpandida
from tcg_sniper.coletor_liga.parsers import SELETOR_CARTAO

# Botão da listagem (fixture catalogo_pagina_1):
# <div id="exibir_mais_cards"><input onclick="mcards.nextPage(40);" type="button"
#  value="Exibir mais" class="exibir-mais"></div>
SELETOR_EXIBIR_MAIS = "#exibir_mais_cards input.exibir-mais"
JS_CONTAGEM_CRESCEU = "([seletor, antes]) => document.querySelectorAll(seletor).length > antes"


class Navegador(Protocol):
    def abrir(self, url: str) -> Pagina:
        """Abre a URL e devolve a página renderizada. Lança ErroRede em falha de navegação,
        exceto se a tela mostrar um desafio: aí devolve a página do desafio."""

    def abrir_expandindo(
        self, url: str, max_cliques: int, pausar: Callable[[], None]
    ) -> PaginaExpandida:
        """Abre a listagem e clica em "Exibir mais" até o botão sumir, ficar oculto ou
        desabilitado, ou a quantidade de cartões parar de crescer. Chama `pausar()` antes de
        cada clique. Para em `max_cliques` cliques (`limite_atingido=True`). Se a página virar
        desafio (na carga ou depois de um clique), para de clicar e devolve a página do desafio.
        Lança ErroRede em falha de navegação."""


class NavegadorPlaywright:
    """Chromium visível com perfil persistente. Use como context manager."""

    def __init__(self, dir_perfil: Path, timeout_ms: int = 45_000, espera_pos_carga_ms: int = 2_000):
        self._dir_perfil = dir_perfil
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
                viewport={"width": 1366, "height": 768},
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
            if atual is not None and eh_desafio(atual):
                return atual
            raise ErroRede(f"{url}: {erro}") from erro

    def _capturar_se_possivel(self, status: int, headers: dict[str, str]) -> Pagina | None:
        try:
            return self._capturar(status, headers)
        except PlaywrightError:
            return None

    def abrir_expandindo(
        self, url: str, max_cliques: int, pausar: Callable[[], None]
    ) -> PaginaExpandida:
        status, headers, cliques = 0, {}, 0
        try:
            resposta = self._pagina.goto(url, wait_until="load", timeout=self._timeout_ms)
            self._pagina.wait_for_timeout(self._espera_ms)
            status = resposta.status if resposta else 0
            headers = dict(resposta.headers) if resposta else {}
            while True:
                pagina = self._capturar(status, headers)
                if eh_desafio(pagina):
                    return PaginaExpandida(pagina, cliques, limite_atingido=False)
                botao = self._pagina.locator(SELETOR_EXIBIR_MAIS).first
                if botao.count() == 0 or not botao.is_visible() or not botao.is_enabled():
                    return PaginaExpandida(pagina, cliques, limite_atingido=False)
                if cliques >= max_cliques:
                    return PaginaExpandida(pagina, cliques, limite_atingido=True)
                antes = self._pagina.locator(SELETOR_CARTAO).count()
                pausar()
                botao.click(timeout=self._timeout_ms)
                cliques += 1
                try:
                    self._pagina.wait_for_function(
                        JS_CONTAGEM_CRESCEU, arg=[SELETOR_CARTAO, antes], timeout=self._timeout_ms
                    )
                except PlaywrightTimeoutError:
                    # Clicou e nada novo apareceu: fim da lista (ou a página mudou; quem chamou
                    # verifica desafio na página devolvida).
                    return PaginaExpandida(self._capturar(status, headers), cliques, limite_atingido=False)
                self._pagina.wait_for_timeout(self._espera_ms)
        except PlaywrightError as erro:
            # Um clique pode levar a uma navegação para o desafio: nesse caso devolve o desafio.
            atual = self._capturar_se_possivel(status, headers)
            if atual is not None and eh_desafio(atual):
                return PaginaExpandida(atual, cliques, limite_atingido=False)
            raise ErroRede(f"{url}: {erro}") from erro
