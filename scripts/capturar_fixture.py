"""Captura o HTML renderizado de uma página da LigaMagic para virar fixture de teste.

Uso:
  uv run python scripts/capturar_fixture.py <url> <nome>
  uv run python scripts/capturar_fixture.py <url> <nome> --expandir [--max-cliques N]

Salva em tests/fixtures/liga/<nome>.html. Usa o perfil .perfil-dev (fora do git).
Com --expandir, clica em "Exibir mais" (pausa de 8 a 20 s antes de cada clique) até o botão
sumir ou até N cliques (padrão 3).
"""

import argparse
import random
import time
from pathlib import Path

from tcg_sniper.coletor_liga.desafio import eh_desafio
from tcg_sniper.coletor_liga.navegador import NavegadorPlaywright

DESTINO = Path("tests/fixtures/liga")


def pausar() -> None:
    segundos = random.uniform(8, 20)
    print(f"pausa de {segundos:.1f} s antes de clicar em 'Exibir mais'")
    time.sleep(segundos)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("nome")
    parser.add_argument("--expandir", action="store_true")
    parser.add_argument("--max-cliques", type=int, default=3)
    args = parser.parse_args()

    with NavegadorPlaywright(Path(".perfil-dev")) as navegador:
        def capturar():
            if args.expandir:
                return navegador.abrir_expandindo(args.url, args.max_cliques, pausar)
            return navegador.abrir(args.url)

        resultado = capturar()
        pagina = resultado.pagina if args.expandir else resultado
        if eh_desafio(pagina):
            input("Desafio detectado. Resolva na janela do Chromium e pressione Enter...")
            resultado = capturar()
            pagina = resultado.pagina if args.expandir else resultado
    DESTINO.mkdir(parents=True, exist_ok=True)
    arquivo = DESTINO / f"{args.nome}.html"
    arquivo.write_text(pagina.html, encoding="utf-8")
    print(f"{arquivo}: {len(pagina.html)} bytes, status {pagina.status}, título {pagina.titulo!r}")
    if args.expandir:
        print(f"cliques: {resultado.cliques}, limite atingido: {resultado.limite_atingido}")


if __name__ == "__main__":
    main()
