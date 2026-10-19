import re
from collections.abc import Sequence

_SEPARADORES = re.compile(r"[-–:()/,]")
_ESPACOS = re.compile(r"\s+")


def termo_busca(nome: str) -> str:
    """Nome do produto da Liga como termo de busca na Amazon: mantém o nome inteiro (inclusive o
    tipo, "Caixa de Booster", "Kit de Pré Lançamento"...) e só troca a pontuação por espaço."""
    return _ESPACOS.sub(" ", _SEPARADORES.sub(" ", nome)).strip()


def sequencia_de_termos(nome: str, nome_en: str | None, alternativos: Sequence[str] = ()) -> list[str]:
    """Termos que a fila alterna para o produto, nesta ordem: o nome em português, o nome em inglês (se
    existir e der um termo diferente) e os termos alternativos (a varredura só os passa na seca). Termo
    vazio ou repetido (sem diferenciar maiúsculas nem pontuação) sai."""
    vistos: set[str] = set()
    saida: list[str] = []
    for candidato in (nome, nome_en or "", *alternativos):
        chave = termo_busca(candidato).casefold()
        if chave and chave not in vistos:
            vistos.add(chave)
            saida.append(candidato)
    return saida or [nome]
