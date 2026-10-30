"""Teste opcional do NavegadorPlaywright contra uma página local (abre o Google Chrome visível).

Não acessa a LigaMagic. Roda só com TESTAR_NAVEGADOR=1.
"""

import os

import pytest
from selectolax.lexbor import LexborHTMLParser

from tcg_sniper.coletor_liga.navegador import NavegadorPlaywright
from tcg_sniper.coletor_liga.parsers import SELETOR_CARTAO

pytestmark = pytest.mark.skipif(
    os.environ.get("TESTAR_NAVEGADOR") != "1", reason="defina TESTAR_NAVEGADOR=1"
)

PAGINA = """<!doctype html><html><head><title>Listagem</title></head><body>
<div class="categoria__card-container"></div>
<div id="exibir_mais_cards"><input type="button" value="Exibir mais" class="exibir-mais" onclick="mais()"></div>
<script>
  var cargas = 0;
  function cartoes(n) {
    var grade = document.querySelector(".categoria__card-container");
    for (var i = 0; i < n; i++) grade.appendChild(document.createElement("div")).className = "card";
  }
  function mais() {
    cargas += 1;
    cartoes(POR_CLIQUE);
    if (cargas >= LIMITE) document.getElementById("exibir_mais_cards").style.display = "none";
  }
  cartoes(2);
</script></body></html>"""


def url_pagina(tmp_path, por_clique, limite):
    arquivo = tmp_path / "listagem.html"
    html = PAGINA.replace("POR_CLIQUE", str(por_clique)).replace("LIMITE", str(limite))
    arquivo.write_text(html, encoding="utf-8")
    return arquivo.as_uri()


def cartoes(expandida):
    return len(LexborHTMLParser(expandida.pagina.html).css(SELETOR_CARTAO))


def test_expande_ate_o_botao_sumir(tmp_path):
    pausas = []
    with NavegadorPlaywright(tmp_path / "perfil", home=None, espera_pos_carga_ms=100) as navegador:
        expandida = navegador.abrir_expandindo(
            url_pagina(tmp_path, por_clique=2, limite=3), max_cliques=10, pausar=lambda: pausas.append(1)
        )
    assert (expandida.cliques, expandida.limite_atingido, cartoes(expandida)) == (3, False, 8)
    assert len(pausas) == 3


def test_para_no_limite_de_cliques(tmp_path):
    with NavegadorPlaywright(tmp_path / "perfil", home=None, espera_pos_carga_ms=100) as navegador:
        expandida = navegador.abrir_expandindo(
            url_pagina(tmp_path, por_clique=2, limite=99), max_cliques=2, pausar=lambda: None
        )
    assert (expandida.cliques, expandida.limite_atingido, cartoes(expandida)) == (2, True, 6)


def test_para_quando_o_clique_nao_traz_cartoes(tmp_path):
    with NavegadorPlaywright(tmp_path / "perfil", home=None, timeout_ms=3_000, espera_pos_carga_ms=100) as navegador:
        expandida = navegador.abrir_expandindo(
            url_pagina(tmp_path, por_clique=0, limite=99), max_cliques=10, pausar=lambda: None
        )
    assert (expandida.cliques, expandida.limite_atingido, cartoes(expandida)) == (1, False, 2)
