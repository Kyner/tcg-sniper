"""Limpa e anonimiza uma página real da Amazon e grava como fixture.

Uso:
  uv run python scripts/anonimizar_fixture.py <tipo> <origem.html> <destino.html> [--proibidos ARQ]

<tipo>: ofertas | painel | carrinho | checkout | login (define os blocos mantidos; ver BLOCOS em
src/tcg_sniper/coletor_amazon/anonimizar.py). --proibidos (padrão .fixtures-brutas/proibidos.txt,
fora do git): um texto real por linha (nome, rua, bairro, telefone...). Não grava se, depois de
anonimizar, ainda sobrar algo com cara de dado pessoal. Para checkout, carrinho, login e ofertas
(páginas de quem está logado) o arquivo de proibidos é obrigatório: liste nome completo, primeiro nome
e sobrenome em linhas separadas, rua, número, bairro, cidade, telefone e e-mail reais.
"""

import argparse
import sys
from pathlib import Path

from tcg_sniper.coletor_amazon.anonimizar import (
    BLOCOS,
    TIPOS_COM_DADOS_PESSOAIS,
    achados,
    anonimizar,
    ler_proibidos,
    limpar,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tipo", choices=sorted(BLOCOS))
    parser.add_argument("origem", type=Path)
    parser.add_argument("destino", type=Path)
    parser.add_argument("--proibidos", type=Path, default=Path(".fixtures-brutas/proibidos.txt"))
    args = parser.parse_args()
    proibidos = ler_proibidos(args.proibidos)
    if not proibidos and args.tipo in TIPOS_COM_DADOS_PESSOAIS:
        sys.exit(f"{args.proibidos} vazio ou ausente: página '{args.tipo}' tem dados pessoais; nada gravado")
    if not proibidos:
        print(f"aviso: {args.proibidos} vazio ou ausente; só os padrões genéricos serão trocados")
    original = args.origem.read_text(encoding="utf-8")
    try:
        limpo = limpar(original, BLOCOS[args.tipo])
    except ValueError as erro:
        sys.exit(f"{args.origem}: {erro}")
    final = anonimizar(limpo, proibidos)
    problemas = achados(final, proibidos)
    if problemas:
        sys.exit(f"{args.origem}: ainda há dado pessoal ({'; '.join(problemas)}); nada gravado")
    args.destino.write_text(final, encoding="utf-8")
    print(f"{args.destino}: {len(original):,} -> {len(final):,} bytes")


if __name__ == "__main__":
    main()
