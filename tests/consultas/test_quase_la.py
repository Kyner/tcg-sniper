from datetime import timedelta
from decimal import Decimal

from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto
from fakes_oportunidades import criar_atual_amazon, criar_oportunidade, criar_vendedor

from tcg_sniper.consultas.quase_la import quase_la
from tcg_sniper.db.models import Envio, StatusCasamento
from tcg_sniper.oportunidades.motor import Regras

AGORA = T0 + timedelta(hours=2)
REGRAS = Regras(desconto_min_pct=20, realerta_queda_pct=5, liga_preco_max_idade_h=48,
                vendedor_min_positivas_pct=90, vendedor_min_avaliacoes=100)


def _produto(s, nome, liga="1000.00", listagem_em=T0, ativo=True):
    p = criar_produto(s, nome, ativo=ativo)
    criar_preco_liga(s, p, liga, listagem_em=listagem_em)
    return p


def test_quase_la_so_elegiveis_entre_o_piso_e_o_minimo(s):
    perto = _produto(s, "perto")
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE001", perto, StatusCasamento.CONFIRMADO), "850.00")  # 15%
    longe = _produto(s, "longe")
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE002", longe, StatusCasamento.CONFIRMADO), "880.00")  # 12%
    abaixo = _produto(s, "abaixo")
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE003", abaixo, StatusCasamento.CONFIRMADO), "950.00")  # 5%
    loja = _produto(s, "loja")
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE004", loja, StatusCasamento.CONFIRMADO), "850.00",
                       envio=Envio.PROPRIO)
    velha = _produto(s, "velha", listagem_em=T0 - timedelta(hours=72))
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE005", velha, StatusCasamento.CONFIRMADO), "850.00")
    inativo = _produto(s, "inativo", ativo=False)
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE006", inativo, StatusCasamento.CONFIRMADO), "850.00")
    pendente = _produto(s, "pendente")
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE007", pendente, StatusCasamento.PENDENTE), "850.00")
    aberta = _produto(s, "aberta")
    a = criar_anuncio(s, "B0QUASE008", aberta, StatusCasamento.CONFIRMADO)
    criar_atual_amazon(s, a, "850.00")
    criar_oportunidade(s, a, aberta, aberta_em=T0)
    ja_e = _produto(s, "ja")
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE009", ja_e, StatusCasamento.CONFIRMADO), "790.00")  # 21%
    fba = _produto(s, "fba")
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE010", fba, StatusCasamento.CONFIRMADO), "860.00",
                       envio=Envio.FBA, vendedor=criar_vendedor(s))  # FBA confiável: entra

    itens = quase_la(s, REGRAS, 10, AGORA)
    assert [i.produto.nome for i in itens] == ["Produto perto", "Produto fba", "Produto longe"]
    assert itens[0].desconto_pct == Decimal("15.00")
    assert itens[0].falta_reais == Decimal("50.00")  # alvo = 1000 × 0,80 = 800
    assert itens[0].falta_pp == Decimal("5.00")
    assert [i.produto.nome for i in quase_la(s, REGRAS, 10, AGORA, limite=1)] == ["Produto perto"]
    assert [i.produto.nome for i in quase_la(s, REGRAS, 10, AGORA, produto_id=longe.id)] == ["Produto longe"]


def test_quase_la_um_item_por_produto_o_mais_perto(s):
    p = _produto(s, "dois")
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE011", p, StatusCasamento.CONFIRMADO), "880.00")  # 12%
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE012", p, StatusCasamento.CONFIRMADO), "850.00")  # 15%

    itens = quase_la(s, REGRAS, 10, AGORA)
    assert [i.produto.nome for i in itens] == ["Produto dois"]
    assert itens[0].desconto_pct == Decimal("15.00")


def test_quase_la_ignora_produto_com_ativa_em_outro_anuncio(s):
    p = _produto(s, "ativa")
    a = criar_anuncio(s, "B0QUASE013", p, StatusCasamento.CONFIRMADO)
    criar_atual_amazon(s, a, "790.00")
    criar_oportunidade(s, a, p, aberta_em=T0)
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE014", p, StatusCasamento.CONFIRMADO), "850.00")  # na faixa

    assert quase_la(s, REGRAS, 10, AGORA) == []
    assert quase_la(s, REGRAS, 10, AGORA, produto_id=p.id) == []
