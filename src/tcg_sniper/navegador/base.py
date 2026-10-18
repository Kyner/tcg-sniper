from collections.abc import Callable
from typing import Protocol

from tcg_sniper.navegador.modelos import Pagina

# Recebe o contexto do elemento (o HTML dele primeiro, depois botão/form em volta, `title`,
# `aria-describedby`, `formaction`) e o rótulo (texto visível, `value`, `aria-label`,
# `aria-labelledby`); levanta exceção para impedir o clique. Ver `coletor_amazon.cliques`.
Guarda = Callable[[str, str], None]


class Navegador(Protocol):
    def vivo(self) -> bool:
        """True se a instância ainda responde (a janela não foi fechada, o processo não morreu)."""

    def abrir(self, url: str) -> Pagina:
        """Abre a URL e devolve a página renderizada. Lança ErroRede em falha de navegação,
        exceto se a tela mostrar um desafio: aí devolve a página do desafio."""


class NavegadorInterativo(Navegador, Protocol):
    def atual(self) -> Pagina:
        """A página que está na tela, sem navegar."""

    def abrir_e_esperar(self, url: str, seletor: str, timeout_ms: int = 15_000) -> Pagina:
        """Abre a URL e espera um elemento de `seletor` aparecer (conteúdo carregado depois do load,
        como o painel de ofertas). Sem o elemento no prazo, devolve a página como estiver."""

    def clicar(self, seletor: str, indice: int, guarda: Guarda) -> Pagina:
        """Clica no `indice`-ésimo elemento de `seletor`. Antes, passa o HTML e o texto do próprio
        elemento a `guarda`, que levanta exceção para impedir o clique. Devolve a página depois do
        clique. Lança ErroRede se o elemento não existe ou o clique falha. Só
        `coletor_amazon.cliques` chama este método."""
