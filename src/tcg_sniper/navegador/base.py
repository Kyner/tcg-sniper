from typing import Protocol

from tcg_sniper.navegador.modelos import Pagina


class Navegador(Protocol):
    def vivo(self) -> bool:
        """True se a instância ainda responde (a janela não foi fechada, o processo não morreu)."""

    def abrir(self, url: str) -> Pagina:
        """Abre a URL e devolve a página renderizada. Lança ErroRede em falha de navegação,
        exceto se a tela mostrar um desafio: aí devolve a página do desafio."""
