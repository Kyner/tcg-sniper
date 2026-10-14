"""Código do produto (ASIN) a partir de um link da amazon.com.br colado à mão no admin."""

import re
from urllib.parse import urlsplit

MENSAGEM_ENCURTADO = "Abra o link e copie o endereço completo da página do produto."
MENSAGEM_SEM_ASIN = "Não encontrei o código do produto (ASIN) nesse link."

_ASIN = re.compile(r"[A-Z0-9]{10}")
_CAMINHO = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Za-z0-9]{10})(?=[/?#]|$)")
_ENCURTADORES = {"amzn.to", "a.co", "amzn.com", "www.amzn.com"}
_DOMINIOS = {"amazon.com.br", "www.amazon.com.br"}


class LinkInvalido(ValueError):
    """Link que não dá para usar; a mensagem é mostrada ao usuário."""


def extrair_asin(texto: str) -> str:
    bruto = texto.strip()
    if _ASIN.fullmatch(bruto.upper()):
        return bruto.upper()
    try:
        partes = urlsplit(bruto if "://" in bruto else f"https://{bruto}")
    except ValueError:
        raise LinkInvalido(MENSAGEM_SEM_ASIN) from None
    dominio = (partes.hostname or "").lower()
    if dominio in _ENCURTADORES:
        raise LinkInvalido(MENSAGEM_ENCURTADO)
    if dominio not in _DOMINIOS:
        raise LinkInvalido(MENSAGEM_SEM_ASIN)
    achado = _CAMINHO.search(partes.path)
    if achado is None:
        raise LinkInvalido(MENSAGEM_SEM_ASIN)
    return achado.group(1).upper()
