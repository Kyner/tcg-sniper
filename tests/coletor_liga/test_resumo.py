from decimal import Decimal

from tcg_sniper.coletor_liga.modelos import Oferta
from tcg_sniper.coletor_liga.resumo import Resumo, calcular_resumo


def o(loja, preco, quantidade):
    return Oferta(loja=loja, preco=Decimal(preco), quantidade=quantidade)


def test_menor_preco_ignora_ofertas_sem_estoque():
    r = calcular_resumo([o("A", "100.00", 0), o("B", "120.00", 2), o("C", "110.00", 1)])
    assert r == Resumo(Decimal("110.00"), 2, 3)


def test_sem_estoque_nenhum():
    assert calcular_resumo([o("A", "100.00", 0)]) == Resumo(None, 0, 1)


def test_lista_vazia():
    assert calcular_resumo([]) == Resumo(None, 0, 0)


def test_mesma_loja_conta_uma_vez():
    r = calcular_resumo([o("A", "100.00", 1), o("A", "90.00", 1)])
    assert r == Resumo(Decimal("90.00"), 1, 2)
