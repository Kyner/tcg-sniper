from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto
from fakes_oportunidades import (
    criar_atual_amazon,
    criar_leitura,
    criar_listagem_liga,
    criar_oportunidade,
    criar_resumo_liga,
)

from tcg_sniper.consultas.historico_produto import historico_produto
from tcg_sniper.db.models import Envio, MotivoEncerramento, StatusCasamento
from tcg_sniper.oportunidades.motor import Regras

AGORA = T0 + timedelta(hours=5)
SP = ZoneInfo("America/Sao_Paulo")
REGRAS = Regras(desconto_min_pct=20, realerta_queda_pct=5, liga_preco_max_idade_h=48,
                vendedor_min_positivas_pct=90, vendedor_min_avaliacoes=100)


def hora(t):  # a curva vem na hora local
    return t.astimezone(SP).hour


def _hist(s, produto, desde=T0 - timedelta(hours=1)):
    return historico_produto(s, produto.id, desde, AGORA, REGRAS, 10, SP)


def test_curva_carrega_o_preco_e_usa_o_menor_elegivel_por_hora(s):
    p = criar_produto(s, "curva")
    a1 = criar_anuncio(s, "B0CURVA001", p, StatusCasamento.CONFIRMADO)
    a2 = criar_anuncio(s, "B0CURVA002", p, StatusCasamento.CONFIRMADO)
    criar_leitura(s, a1, T0 - timedelta(hours=3), "900.00")  # antes do período: vale até mudar
    criar_leitura(s, a1, T0 + timedelta(hours=2, minutes=10), "950.00")
    criar_leitura(s, a2, T0 + timedelta(minutes=30), "700.00", envio=Envio.PROPRIO)  # não elegível: ignorado
    criar_leitura(s, a2, T0 + timedelta(hours=3, minutes=5), "880.00")
    h = _hist(s, p)
    assert h.escala == "hora"
    precos = [(pt.t.hour, pt.preco) for pt in h.amazon]
    assert precos[:2] == [(hora(T0 - timedelta(hours=1)), Decimal("900.00")), (hora(T0), Decimal("900.00"))]
    assert (hora(T0 + timedelta(hours=2)), Decimal("900.00")) in precos  # 950 chega dentro da hora; vale o menor
    assert (hora(T0 + timedelta(hours=3)), Decimal("880.00")) in precos
    assert all(pt.preco != Decimal("700.00") for pt in h.amazon)


def test_liga_faixas_oportunidades_e_recorrencia(s):
    p = criar_produto(s, "faixas")
    criar_preco_liga(s, p, "1000.00", listagem_em=T0)
    a = criar_anuncio(s, "B0FAIXA001", p, StatusCasamento.CONFIRMADO)
    criar_atual_amazon(s, a, "900.00")
    criar_listagem_liga(s, p, "1000.00", T0)
    criar_resumo_liga(s, p, "1100.00", T0)
    fechada = criar_oportunidade(s, a, p, aberta_em=T0 + timedelta(minutes=10),
                                 deixou_de_valer_em=T0 + timedelta(hours=1),
                                 fechada_em=T0 + timedelta(hours=1, minutes=30), motivo=MotivoEncerramento.PRECO_SUBIU)
    criar_oportunidade(s, a, p, aberta_em=T0 - timedelta(days=40), fechada_em=T0 - timedelta(days=40) +
                       timedelta(hours=1), motivo=MotivoEncerramento.OFERTA_SUMIU)
    h = _hist(s, p)
    assert [pt.preco for pt in h.liga] == [Decimal("1000.00")]
    assert [pt.preco for pt in h.liga_medio] == [Decimal("1100.00")]
    assert [(f.id, f.fim, f.aberta) for f in h.faixas] == [(fechada.id, T0 + timedelta(hours=1), False)]
    assert [o.id for o in h.oportunidades] == [fechada.id]
    assert h.recorrencia_30d == 1
    assert h.desconto_min_pct == 20
    assert h.anuncio.titulo == "Anúncio B0FAIXA001"
    assert h.quase_la is True  # 900 contra 1000: 10%, no piso


def test_produto_inexistente_ou_inativo(s):
    assert historico_produto(s, 999_999, None, AGORA, REGRAS, 10, SP) is None
    inativo = criar_produto(s, "fora", ativo=False)
    assert historico_produto(s, inativo.id, None, AGORA, REGRAS, 10, SP) is None


def test_tudo_acima_de_90_dias_agrega_por_dia(s):
    p = criar_produto(s, "longo")
    a = criar_anuncio(s, "B0LONGO001", p, StatusCasamento.CONFIRMADO)
    criar_leitura(s, a, AGORA - timedelta(days=120), "900.00")
    h = historico_produto(s, p.id, None, AGORA, REGRAS, 10, SP)
    assert h.escala == "dia"
    assert len(h.amazon) == 2  # a leitura vale 26 h: dois dias com ponto, depois some


def test_queda_curta_dentro_do_dia_aparece_na_escala_por_dia(s):
    p = criar_produto(s, "queda")
    a = criar_anuncio(s, "B0QUEDA001", p, StatusCasamento.CONFIRMADO)
    base = AGORA - timedelta(days=100)
    criar_leitura(s, a, base, "900.00")
    criar_leitura(s, a, base + timedelta(hours=1), "700.00")
    criar_leitura(s, a, base + timedelta(hours=3), "900.00")
    h = historico_produto(s, p.id, None, AGORA, REGRAS, 10, SP)
    assert h.escala == "dia"
    assert h.amazon[0].preco == Decimal("700.00")
    assert h.amazon[1].preco == Decimal("900.00")


def test_oportunidade_aberta_ha_31_dias_aparece_no_periodo_de_30(s):
    p = criar_produto(s, "antiga")
    a = criar_anuncio(s, "B0ANTIG001", p, StatusCasamento.CONFIRMADO)
    aberta = criar_oportunidade(s, a, p, aberta_em=AGORA - timedelta(days=31))
    h = _hist(s, p, desde=AGORA - timedelta(days=30))
    assert [(f.id, f.fim, f.aberta) for f in h.faixas] == [(aberta.id, AGORA, True)]
    assert [o.id for o in h.oportunidades] == [aberta.id]


def test_recorrencia_exclui_casamento_desfeito(s):
    p = criar_produto(s, "desfeito")
    a = criar_anuncio(s, "B0DESFE001", p, StatusCasamento.CONFIRMADO)
    criar_oportunidade(s, a, p, aberta_em=AGORA - timedelta(days=2), fechada_em=AGORA - timedelta(days=2, hours=-1),
                       motivo=MotivoEncerramento.CASAMENTO_DESFEITO)
    criar_oportunidade(s, a, p, aberta_em=AGORA - timedelta(days=1), fechada_em=AGORA - timedelta(hours=20),
                       motivo=MotivoEncerramento.OFERTA_SUMIU)
    h = _hist(s, p, desde=None)
    assert h.recorrencia_30d == 1
    assert len(h.oportunidades) == 2
