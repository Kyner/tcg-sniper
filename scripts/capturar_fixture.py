"""Captura o HTML renderizado de uma página da LigaMagic para virar fixture de teste.

Uso: uv run python scripts/capturar_fixture.py <url> <nome>
Salva em tests/fixtures/liga/<nome>.html. Usa o perfil .perfil-dev (fora do git).
"""

import sys
from pathlib import Path

from tcg_sniper.coletor_liga.desafio import eh_desafio
from tcg_sniper.coletor_liga.navegador import NavegadorPlaywright

DESTINO = Path("tests/fixtures/liga")


def main(url: str, nome: str) -> None:
    with NavegadorPlaywright(Path(".perfil-dev")) as navegador:
        pagina = navegador.abrir(url)
        if eh_desafio(pagina):
            input("Desafio detectado. Resolva na janela do Chromium e pressione Enter...")
            pagina = navegador.abrir(url)
    DESTINO.mkdir(parents=True, exist_ok=True)
    arquivo = DESTINO / f"{nome}.html"
    arquivo.write_text(pagina.html, encoding="utf-8")
    print(f"{arquivo}: {len(pagina.html)} bytes, status {pagina.status}, título {pagina.titulo!r}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
