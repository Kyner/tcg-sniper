"""Variações que separam produtos parecidos: Foil ou não, idioma e quantidade de pacotes.

`pistas_variacao` resume o que o nome do produto da Liga diz (ou não diz) dessas variações;
`termos_variacao` destaca os trechos do título do anúncio da Amazon que falam delas. Regex por palavra,
sem diferenciar maiúsculas; "Non-Foil" vence "Foil"."""

import re

_NON_FOIL = re.compile(r"\bnon[- ]?foil\b", re.IGNORECASE)
_FOIL = re.compile(r"\bfoil\b", re.IGNORECASE)
_QUANTIDADE = re.compile(r"\b\d+\s+(?:packs|boosters|pacotes)\b", re.IGNORECASE)
_IDIOMAS = {
    "inglês": re.compile(r"\b(?:inglês|ingles|english)\b", re.IGNORECASE),
    "português": re.compile(r"\b(?:português|portugues|portuguese)\b", re.IGNORECASE),
    "japonês": re.compile(r"\b(?:japonês|japones|japanese)\b", re.IGNORECASE),
}
_IDIOMA = re.compile("|".join(f"(?:{regex.pattern})" for regex in _IDIOMAS.values()), re.IGNORECASE)


def _foil(texto: str) -> re.Match[str] | None:
    return _NON_FOIL.search(texto) or _FOIL.search(texto)


def pistas_variacao(nome: str) -> list[str]:
    """O que o nome do produto da Liga diz de Foil e de idioma (a quem decide o par)."""
    foil = _foil(nome)
    if foil is None:
        pistas = ["sem Foil no nome"]
    else:
        pistas = ["Non-Foil" if _NON_FOIL.fullmatch(foil.group()) else "Foil"]
    idiomas = [idioma for idioma, regex in _IDIOMAS.items() if regex.search(nome)]
    return pistas + (idiomas or ["idioma não informado"])


def termos_variacao(titulo: str) -> list[str]:
    """Trechos do título do anúncio (como aparecem nele) sobre Foil, quantidade de pacotes e idioma."""
    termos = []
    foil = _foil(titulo)
    if foil is not None:
        termos.append(foil.group())
    termos += [achado.group() for achado in _QUANTIDADE.finditer(titulo)]
    termos += [achado.group() for achado in _IDIOMA.finditer(titulo)]
    return list(dict.fromkeys(termos))
