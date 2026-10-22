"""Consultas de casamento (anúncio da Amazon × produto da Liga) no pacote neutro."""

from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, criar_anuncio, criar_par, criar_preco_liga, criar_produto

from tcg_sniper.consultas.casamentos import ORDENS_CASAMENTO, parecidos_na_liga, produtos_para_casar
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import Envio, OrigemPreco, StatusCasamento

SP = ZoneInfo("America/Sao_Paulo")
FILTROS = {"busca": "", "categoria": None, "situacao": "todos", "com_preco": False, "desconto_min_pct": 25}


def nomes(s, **filtros):
    return [linha.produto.nome for linha in produtos_para_casar(s, **{**FILTROS, **filtros})]


def pendentes(s, produto, quantidade):
    for i in range(quantidade):
        criar_anuncio(s, f"B0{produto.liga_id.upper():>4}{i:04d}".replace(" ", "Z"), produto=produto)


def test_ordens_casamento():
    assert ORDENS_CASAMENTO == ("preco_liga", "pendentes", "nome")


def test_ordem_preco_liga_poe_quem_tem_preco_primeiro(s):
    a = criar_produto(s, "a", nome="A sem preço")
    b = criar_produto(s, "b", nome="B com preço")
    criar_preco_liga(s, b, "100.00")
    pendentes(s, a, 5)
    pendentes(s, b, 1)
    assert nomes(s) == ["B com preço", "A sem preço"]
    assert nomes(s, ordem="preco_liga") == ["B com preço", "A sem preço"]


def test_ordem_preco_liga_desempata_por_pendentes_e_nome(s):
    for liga_id, quantidade in (("x", 1), ("y", 3), ("w", 1)):
        produto = criar_produto(s, liga_id, nome=liga_id.upper())
        criar_preco_liga(s, produto, "100.00")
        pendentes(s, produto, quantidade)
    assert nomes(s) == ["Y", "W", "X"]


def test_ordem_pendentes_e_nome(s):
    a = criar_produto(s, "a", nome="Alfa")
    b = criar_produto(s, "b", nome="Beta")
    criar_produto(s, "c", nome="Gama")
    criar_preco_liga(s, a, "100.00")
    pendentes(s, a, 1)
    pendentes(s, b, 2)
    assert nomes(s, ordem="pendentes") == ["Beta", "Alfa", "Gama"]
    assert nomes(s, ordem="nome") == ["Alfa", "Beta", "Gama"]


def test_ordem_desconhecida_recusa(s):
    with pytest.raises(ValueError):
        nomes(s, ordem="xyz")


def test_ordem_legado_igual_a_de_hoje(s):
    """O mesmo cenário de `tests/admin/test_admin_casamentos.py::test_situacoes_e_ordem`."""
    a = criar_produto(s, "a", nome="Caixa Alfa 100%")
    b = criar_produto(s, "b", nome="Caixa Beta")
    c = criar_produto(s, "c", nome="Caixa Gama")
    d = criar_produto(s, "d", nome="Caixa Delta")
    e = criar_produto(s, "e", nome="Caixa Inativa", ativo=False)
    for p in (a, b, c, d, e):
        criar_preco_liga(s, p, "1000.00")
    for asin, produto, preco, status in (
        ("B0ALFA0001", a, "700.00", StatusCasamento.PENDENTE),
        ("B0BETA0001", b, "990.00", StatusCasamento.PENDENTE),
        ("B0DELTA001", d, "800.00", StatusCasamento.CONFIRMADO),
        ("B0DELTA002", d, "900.00", StatusCasamento.IGNORADO),
        ("B0INATIVO1", e, "10.00", StatusCasamento.PENDENTE),
    ):
        anuncio = criar_anuncio(s, asin, produto=produto, status=status)
        repo_amz.registrar_preco(s, anuncio.id, Decimal(preco), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, T0, SP)
    assert nomes(s, ordem="legado", situacao="pendentes") == ["Caixa Alfa 100%", "Caixa Beta"]
    assert nomes(s, ordem="legado") == ["Caixa Alfa 100%", "Caixa Beta", "Caixa Delta", "Caixa Gama"]
    # Com um pendente, Gama passa à frente de Delta (sem pendente), mas fica atrás de Beta (por nome).
    criar_par(s, criar_anuncio(s, "B0GAMA0001"), c, agora=T0 + timedelta(hours=1))
    assert nomes(s, ordem="legado") == ["Caixa Alfa 100%", "Caixa Beta", "Caixa Gama", "Caixa Delta"]


def test_parecidos_exclui_o_proprio_e_inativos(s):
    base = criar_produto(s, "base", nome="Secret Lair - Goblingram")
    foil = criar_produto(s, "foil", nome="Secret Lair - Goblingram Foil Edition")
    ingles = criar_produto(s, "ingles", nome="Secret Lair - Goblingram (Inglês)")
    criar_produto(s, "inativo", nome="Secret Lair - Goblingram Non-Foil", ativo=False)
    criar_produto(s, "outro", nome="Secret Lair - Outra Coisa")
    criar_preco_liga(s, base, "300.00")
    parecidos = parecidos_na_liga(s, foil)
    assert [(p.id, preco) for p, preco in parecidos] == [(base.id, Decimal("300.00")), (ingles.id, None)]
    assert [p.id for p, _ in parecidos_na_liga(s, ingles)] == [base.id, foil.id]
    [unico] = parecidos_na_liga(s, base, limite=1)
    assert unico[0].id in {foil.id, ingles.id}


def test_parecidos_de_nome_so_com_sufixo_nao_traz_nada(s):
    produto = criar_produto(s, "foil", nome="Foil Edition")
    criar_produto(s, "outro", nome="Outra Foil Edition")
    assert parecidos_na_liga(s, produto) == []
