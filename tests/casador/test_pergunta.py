import inspect
from decimal import Decimal

import pytest
from fakes import criar_anuncio, criar_produto

from tcg_sniper.casador.pergunta import FORMATO, INSTRUCOES, assinatura, ler_veredito, texto_pergunta
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
    assert FORMATO["required"] == ["mesmo_produto", "confianca", "motivo", "idioma_anuncio"]
    assert FORMATO["additionalProperties"] is False
    assert FORMATO["properties"]["idioma_anuncio"]["enum"] == ["pt", "en", "ja", "outro", "indefinido"]


def test_instrucoes_tem_a_regra_de_idioma_condicional():
    assert "Idioma diferente = outro produto" not in INSTRUCOES
    assert "A edição em português é a preferida" in INSTRUCOES
    assert "Anúncio em inglês também é o mesmo produto quando o produto da LigaMagic não tem anúncio em português confirmado" in INSTRUCOES
    assert "Japonês e qualquer outro idioma são sempre outro produto" in INSTRUCOES
    assert "idioma_anuncio" in INSTRUCOES


def test_idioma_vem_da_embalagem_nao_do_titulo():
    linha = next(l for l in INSTRUCOES.splitlines() if "Em idioma_anuncio" in l)
    assert "embalagem" in linha
    assert "não pela língua em que o título está escrito" in linha
    assert "indicação explícita da edição no título" in linha
    assert "indefinido" in linha


@pytest.mark.parametrize(("valor", "trecho"), [
    (True, "- já tem anúncio em português confirmado: sim"),
    (False, "- já tem anúncio em português confirmado: não"),
    (None, "- já tem anúncio em português confirmado: não se sabe"),
])
def test_texto_diz_se_ja_tem_portugues_confirmado(s, valor, trecho):
    p = criar_produto(s, "p1")
    a = criar_anuncio(s, "B1", produto=p)
    assert trecho in texto_pergunta(a, p, None, None, portugues_confirmado=valor)


def test_assinatura_nao_depende_do_portugues_confirmado():
    """O português confirmado vai na pergunta mas não na assinatura: confirmar um anúncio não reavalia tudo."""
    assert list(inspect.signature(assinatura).parameters) == ["anuncio", "produto"]


@pytest.mark.parametrize("idioma", ["pt", "en", "ja", "outro", "indefinido"])
def test_ler_veredito_com_idioma(idioma):
    v = ler_veredito({"mesmo_produto": True, "confianca": 93, "motivo": "x", "idioma_anuncio": idioma})
    assert v.idioma_anuncio == idioma


def test_ler_veredito_sem_idioma_fica_vazio():
    assert ler_veredito({"mesmo_produto": True, "confianca": 93, "motivo": "x"}).idioma_anuncio is None


def test_ler_veredito_idioma_desconhecido_e_fora_do_formato():
    with pytest.raises(ErroIA):
        ler_veredito({"mesmo_produto": True, "confianca": 93, "motivo": "x", "idioma_anuncio": "fr"})


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
