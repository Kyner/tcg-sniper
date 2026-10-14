"""Captura o HTML renderizado de uma página da LigaMagic ou da Amazon para virar fixture de teste.

Uso:
  uv run python scripts/capturar_fixture.py <url> <nome> [--destino PASTA]
  uv run python scripts/capturar_fixture.py <url> <nome> --expandir [--max-cliques N]   (só LigaMagic)

Salva em <PASTA>/<nome>.html (padrão: tests/fixtures/liga para a LigaMagic e
.fixtures-brutas/amazon para a Amazon, que fica fora do git até ser recortada). Usa um perfil
de desenvolvimento por site (.perfil-dev e .perfil-dev-amazon, fora do git).
Com --expandir, clica em "Exibir mais" (pausa de 8 a 20 s antes de cada clique) até o botão
sumir ou até N cliques (padrão 3).
"""

import argparse
import random
import time
from pathlib import Path
from urllib.parse import urlsplit

from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon
from tcg_sniper.coletor_liga.desafio import eh_desafio
from tcg_sniper.coletor_liga.navegador import NavegadorPlaywright
from tcg_sniper.navegador.chromium import NavegadorChromium

DESTINOS = {"liga": Path("tests/fixtures/liga"), "amazon": Path(".fixtures-brutas/amazon")}


def site_da_url(url: str) -> str:
    return "amazon" if "amazon." in urlsplit(url).netloc else "liga"


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
    parser.add_argument("--destino", type=Path)
    args = parser.parse_args()

    site = site_da_url(args.url)
    if args.expandir and site != "liga":
        parser.error("--expandir só vale para a LigaMagic")
    detector = eh_desafio_amazon if site == "amazon" else eh_desafio
    destino = args.destino or DESTINOS[site]
    contexto = (
        NavegadorChromium(Path(".perfil-dev-amazon"), eh_desafio_amazon)
        if site == "amazon"
        else NavegadorPlaywright(Path(".perfil-dev"))
    )

    with contexto as navegador:
        def capturar():
            if args.expandir:
                return navegador.abrir_expandindo(args.url, args.max_cliques, pausar)
            return navegador.abrir(args.url)

        resultado = capturar()
        pagina = resultado.pagina if args.expandir else resultado
        if detector(pagina):
            input("Desafio detectado. Resolva na janela do Chromium e pressione Enter...")
            resultado = capturar()
            pagina = resultado.pagina if args.expandir else resultado
    destino.mkdir(parents=True, exist_ok=True)
    arquivo = destino / f"{args.nome}.html"
    arquivo.write_text(pagina.html, encoding="utf-8")
    print(f"{arquivo}: {len(pagina.html)} bytes, status {pagina.status}, título {pagina.titulo!r}")
    if args.expandir:
        print(f"cliques: {resultado.cliques}, limite atingido: {resultado.limite_atingido}")


if __name__ == "__main__":
    main()
