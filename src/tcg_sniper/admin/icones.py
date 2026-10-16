"""Ícones do Heroicons (outline, 24 px) embutidos no HTML, para herdar a cor do texto."""

from functools import cache
from pathlib import Path

from markupsafe import Markup, escape

PASTA = Path(__file__).parent / "static" / "icones"


@cache
def _svg(nome: str) -> str:
    return (PASTA / f"{nome}.svg").read_text(encoding="utf-8").strip()


def icone(nome: str, classes: str = "size-5") -> Markup:
    """`<svg>` do ícone `nome` com as classes dadas (as classes ficam nos templates; "shrink-0" sempre)."""
    return Markup(_svg(nome).replace("<svg ", f'<svg class="{escape(classes)} shrink-0" ', 1))
