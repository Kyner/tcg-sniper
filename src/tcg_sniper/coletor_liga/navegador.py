from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from tcg_sniper.coletor_liga.desafio import eh_desafio
from tcg_sniper.coletor_liga.modelos import ErroRede, PaginaExpandida
from tcg_sniper.coletor_liga.parsers import SELETOR_CARTAO
from tcg_sniper.navegador.base import Navegador as NavegadorBase
from tcg_sniper.navegador.chromium import NavegadorChromium

# Botão da listagem (fixture catalogo_pagina_1):
# <div id="exibir_mais_cards"><input onclick="mcards.nextPage(40);" type="button"
#  value="Exibir mais" class="exibir-mais"></div>
SELETOR_EXIBIR_MAIS = "#exibir_mais_cards input.exibir-mais"
JS_CONTAGEM_CRESCEU = "([seletor, antes]) => document.querySelectorAll(seletor).length > antes"


class Navegador(NavegadorBase, Protocol):
    def abrir_expandindo(
        self, url: str, max_cliques: int, pausar: Callable[[], None]
    ) -> PaginaExpandida:
        """Abre a listagem e clica em "Exibir mais" até o botão sumir, ficar oculto ou
        desabilitado, ou a quantidade de cartões parar de crescer. Chama `pausar()` antes de
        cada clique. Para em `max_cliques` cliques (`limite_atingido=True`). Se a página virar
        desafio (na carga ou depois de um clique), para de clicar e devolve a página do desafio.
        Lança ErroRede em falha de navegação."""


class NavegadorPlaywright(NavegadorChromium):
    """Chromium da LigaMagic: detector do Cloudflare e o clique em "Exibir mais"."""

    def __init__(self, dir_perfil: Path, timeout_ms: int = 45_000, espera_pos_carga_ms: int = 2_000):
        super().__init__(dir_perfil, eh_desafio, timeout_ms, espera_pos_carga_ms)

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
