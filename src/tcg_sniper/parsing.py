"""Peças de parsing comuns aos sites."""

import re
from decimal import Decimal

_RE_PRECO = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+),(\d{2})")


class ErroParser(Exception):
    """HTML não tem a estrutura esperada (provável mudança de layout)."""


def parse_preco_brl(texto: str) -> Decimal:
    """"R$ 1.234,56" → Decimal("1234.56"). Sem "R$", NBSP e espaços nas pontas, o texto inteiro
    tem de ser um preço: qualquer sobra → `ErroParser` (nunca truncar)."""
    limpo = texto.replace("\xa0", " ").strip().removeprefix("R$").strip()
    m = _RE_PRECO.fullmatch(limpo)
    if not m:
        raise ErroParser(f"preço inválido: {texto!r}")
    return Decimal(f"{m.group(1).replace('.', '')}.{m.group(2)}")
