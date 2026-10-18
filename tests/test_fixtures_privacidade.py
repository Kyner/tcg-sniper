"""Nenhuma fixture da Amazon pode ter dado pessoal (o repositório é público). Os padrões genéricos
valem sempre; os textos reais (nome, rua, telefone...) vêm de .fixtures-brutas/proibidos.txt, e os
itens do "Salvo para depois" das capturas brutas em .fixtures-brutas/amazon/capturas, que só existem
na máquina que fez a captura."""

import re
from html import unescape
from pathlib import Path

import pytest

from tcg_sniper.coletor_amazon.anonimizar import achados, itens_salvos, ler_proibidos

RAIZ = Path(__file__).parent.parent
FIXTURES = sorted((RAIZ / "tests" / "fixtures" / "amazon").glob("*.html"))
PROIBIDOS = ler_proibidos(RAIZ / ".fixtures-brutas" / "proibidos.txt")
CAPTURAS_CARRINHO = sorted((RAIZ / ".fixtures-brutas" / "amazon" / "capturas").glob("*/carrinho*.html"))

UUID = re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])")
UUID_FICTICIO = "00000000-0000-0000-0000-"
# 16+ caracteres de base64/base64url com dígito ou padding (ids legíveis como "proceedToRetailCheckout" não têm)
TOKEN = re.compile(r"(?<![A-Za-z0-9+/=_])[A-Za-z0-9+/_]{16,}={0,2}(?![A-Za-z0-9+/=_])")
PEDIDO = re.compile(r"(?<!\d)\d{3}-\d{7}-\d{7}(?!\d)")
PEDIDO_FICTICIO = "000-0000000-0000000"


def _desescapar(texto: str) -> str:
    """Desfaz entidades até estabilizar: `&amp;eacute;` (codificado duas vezes) também é conferido."""
    while (novo := unescape(texto)) != texto:
        texto = novo
    return texto


def _sem_espacos(texto: str) -> str:
    return " ".join(_desescapar(texto).lower().split())


@pytest.mark.parametrize("caminho", FIXTURES, ids=lambda p: p.name)
def test_fixture_sem_dado_pessoal(caminho):
    assert achados(caminho.read_text(encoding="utf-8"), PROIBIDOS) == []


@pytest.mark.parametrize("caminho", FIXTURES, ids=lambda p: p.name)
def test_fixture_sem_ids_de_pedido_item_ou_sessao(caminho):
    html = _desescapar(caminho.read_text(encoding="utf-8"))
    problemas = []
    if any(not u.lower().startswith(UUID_FICTICIO) for u in UUID.findall(html)):
        problemas.append("UUID")
    if any(re.search(r"[\d+=]", t) for t in TOKEN.findall(html)):
        problemas.append("token base64 de 16+ caracteres")
    if "miq://" in html:
        problemas.append("miq://")
    if any(p != PEDIDO_FICTICIO for p in PEDIDO.findall(html)):
        problemas.append("número de pedido")
    if re.search(r"p[fd]_rd_", html):
        problemas.append("pf_rd_/pd_rd_")
    assert problemas == []  # só o tipo: o valor iria parar no log do teste


@pytest.mark.skipif(not CAPTURAS_CARRINHO, reason="capturas brutas só existem na máquina que capturou")
@pytest.mark.parametrize("caminho", FIXTURES, ids=lambda p: p.name)
def test_fixture_sem_itens_salvos_reais(caminho):
    asins: set[str] = set()
    titulos: set[str] = set()
    for bruto in CAPTURAS_CARRINHO:
        a, t = itens_salvos(bruto.read_text(encoding="utf-8"))
        asins |= a
        titulos |= t
    texto = _sem_espacos(caminho.read_text(encoding="utf-8"))
    assert sum(asin.lower() in texto for asin in asins) == 0  # contagem, nunca o valor
    assert sum(_sem_espacos(t) in texto for t in titulos) == 0


@pytest.mark.skipif(not PROIBIDOS, reason="proibidos.txt só existe na máquina que capturou")
@pytest.mark.parametrize("caminho", FIXTURES, ids=lambda p: p.name)
def test_fixture_sem_proibidos_nem_codificados(caminho):
    texto = _sem_espacos(caminho.read_text(encoding="utf-8"))
    assert sum(_sem_espacos(p) in texto for p in PROIBIDOS) == 0
