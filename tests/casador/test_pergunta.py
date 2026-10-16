from decimal import Decimal

import pytest
from fakes import criar_anuncio, criar_produto

from tcg_sniper.casador.pergunta import FORMATO, assinatura, ler_veredito, texto_pergunta
from tcg_sniper.ia.modelos import ErroIA


def test_texto_tem_os_dois_lados(s):
    p = criar_produto(s, "p1", nome="Caixa de Booster - Contos da Terra Média")
    p.nome_en, p.edicao, p.tipo, p.idioma = "Booster Box - Tales of Middle-earth", "LTR", "Caixas de Boosters", "Inglês"
    a = criar_anuncio(s, "B1", produto=p)
    a.titulo, a.variacao = "MTG LOTR Draft Booster Box", "Draft"
    texto = texto_pergunta(a, p, Decimal("899.90"), None)
    for trecho in ("Caixa de Booster - Contos da Terra Média", "Booster Box - Tales of Middle-earth", "LTR",
                   "Caixas de Boosters", "Inglês", "MTG LOTR Draft Booster Box", "Draft", "R$ 899,90", "sem preço"):
        assert trecho in texto


def test_assinatura_muda_com_os_dados(s):
    p = criar_produto(s, "p1")
    a = criar_anuncio(s, "B1", produto=p)
    base = assinatura(a, p)
    assert assinatura(a, p) == base
    for mudar in (lambda: setattr(a, "titulo", "outro"), lambda: setattr(a, "variacao", "Set"),
                  lambda: setattr(a, "imagem_url", "https://i/1.jpg"), lambda: setattr(p, "nome_en", "X"),
                  lambda: setattr(p, "imagem_url", "https://i/2.jpg"), lambda: setattr(p, "nome", "Y")):
        mudar()
        assert assinatura(a, p) != base
        base = assinatura(a, p)


def test_formato_estrito():
    assert FORMATO["required"] == ["mesmo_produto", "confianca", "motivo"] and FORMATO["additionalProperties"] is False


def test_ler_veredito_valido():
    v = ler_veredito({"mesmo_produto": True, "confianca": 93, "motivo": "  mesma caixa  "})
    assert (v.mesmo_produto, v.confianca, v.motivo) == (True, 93, "mesma caixa")


@pytest.mark.parametrize("dados", [
    {"mesmo_produto": True, "confianca": 150, "motivo": "x"},
    {"mesmo_produto": True, "confianca": -1, "motivo": "x"},
    {"mesmo_produto": "sim", "confianca": 90, "motivo": "x"},
    {"mesmo_produto": True, "confianca": 90.5, "motivo": "x"},
    {"mesmo_produto": True, "confianca": True, "motivo": "x"},
    {"mesmo_produto": True, "confianca": 90, "motivo": "   "},
    {"mesmo_produto": True, "motivo": "x"},
])
def test_ler_veredito_fora_do_formato(dados):
    with pytest.raises(ErroIA):
        ler_veredito(dados)


def test_motivo_longo_e_cortado():
    assert len(ler_veredito({"mesmo_produto": False, "confianca": 80, "motivo": "a" * 500}).motivo) == 200
