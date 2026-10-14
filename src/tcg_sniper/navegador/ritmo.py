"""Ritmo humano e tolerância a falhas de rede, compartilhados pelos coletores."""

import logging
import random
from collections.abc import Callable
from pathlib import Path

from tcg_sniper.navegador.modelos import ErroRede

log = logging.getLogger(__name__)

Dormir = Callable[[float], None]
ESPERA_RETRY_S = 30


def pausa_aleatoria(min_s: float, max_s: float, dormir: Dormir, rng: random.Random | None = None) -> None:
    dormir((rng or random).uniform(min_s, max_s))


def com_um_retry[T](abrir: Callable[[], T], url: str, dormir: Dormir) -> T:
    try:
        return abrir()
    except ErroRede as erro:
        log.warning("erro de rede em %s (%s); nova tentativa em %ss", url, erro, ESPERA_RETRY_S)
        dormir(ESPERA_RETRY_S)
        return abrir()


def salvar_html_falha(dir_dados: Path, nome: str, html: str) -> Path:
    pasta = dir_dados / "falhas"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{nome}.html"
    caminho.write_text(html, encoding="utf-8")
    return caminho
