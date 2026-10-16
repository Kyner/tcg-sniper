"""Hash das fontes do CSS do admin (templates, entrada e ícones), gravado na 1ª linha de admin.css."""

import hashlib
from pathlib import Path

ADMIN = Path(__file__).parent
ENTRADA = ADMIN / "estilo.css"
SAIDA = ADMIN / "static" / "admin.css"
PREFIXO = "/* templates: "


def fontes() -> list[Path]:
    return [ENTRADA, ADMIN / "icones.py", *sorted((ADMIN / "templates").glob("*.html"))]


def hash_fontes() -> str:
    """SHA-256 do conteúdo das fontes, com fim de linha normalizado (CRLF do Windows = LF)."""
    h = hashlib.sha256()
    for arquivo in fontes():
        h.update(arquivo.name.encode())
        h.update(arquivo.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def hash_gravado() -> str | None:
    if not SAIDA.exists():
        return None
    with SAIDA.open(encoding="utf-8") as f:
        linha = f.readline().strip()
    if not linha.startswith(PREFIXO) or not linha.endswith("*/"):
        return None
    return linha.removeprefix(PREFIXO).removesuffix("*/").strip()
