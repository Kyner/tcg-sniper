import re

_SEPARADORES = re.compile(r"[-–:()/,]")
_ESPACOS = re.compile(r"\s+")


def termo_busca(nome: str) -> str:
    """Nome do produto da Liga como termo de busca na Amazon: mantém o nome inteiro (inclusive o
    tipo, "Caixa de Booster", "Kit de Pré Lançamento"...) e só troca a pontuação por espaço."""
    return _ESPACOS.sub(" ", _SEPARADORES.sub(" ", nome)).strip()
