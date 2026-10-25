"""Guarda: o pacote neutro de consultas e a gestão nova não dependem do admin antigo (que será apagado)."""

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2] / "src" / "tcg_sniper"
PACOTES = ("consultas", "gestao")  # `gestao` pode ainda não existir


def _importa_admin(arquivo: Path) -> list[str]:
    achados = []
    for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Import):
            achados += [a.name for a in no.names if a.name.split(".")[:2] == ["tcg_sniper", "admin"]]
        elif isinstance(no, ast.ImportFrom) and no.module and no.module.split(".")[:2] == ["tcg_sniper", "admin"]:
            achados.append(no.module)
    return achados


def test_consultas_e_gestao_nao_importam_admin():
    infratores = {
        str(arquivo.relative_to(RAIZ)): achados
        for pacote in PACOTES
        for arquivo in sorted((RAIZ / pacote).glob("**/*.py"))
        if (achados := _importa_admin(arquivo))
    }
    assert infratores == {}
