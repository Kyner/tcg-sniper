from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, criar_anuncio, criar_produto
from fakes_oportunidades import criar_oportunidade

from tcg_sniper.consultas import oportunidades as q
from tcg_sniper.db.models import MotivoEncerramento, StatusCasamento

AGORA = T0 + timedelta(days=10)
SP = ZoneInfo("America/Sao_Paulo")


def _cenario(s):
    p1 = criar_produto(s, "p1", nome="Final Fantasy")
    p2 = criar_produto(s, "p2", nome="Duskmourn")
    a1 = criar_anuncio(s, "B0OPQ00001", p1, StatusCasamento.CONFIRMADO)
    a2 = criar_anuncio(s, "B0OPQ00002", p2, StatusCasamento.CONFIRMADO)
    # encerrada há 2 dias, valeu 3 h (deixou de valer antes de fechar pela carência)
    criar_oportunidade(s, a1, p1, aberta_em=AGORA - timedelta(days=2), preco_alertado="700", preco_liga="1000",
                       deixou_de_valer_em=AGORA - timedelta(days=2) + timedelta(hours=3),
                       fechada_em=AGORA - timedelta(days=2) + timedelta(hours=3, minutes=30),
                       motivo=MotivoEncerramento.PRECO_SUBIU)
    # ativa há 1 h
    criar_oportunidade(s, a2, p2, aberta_em=AGORA - timedelta(hours=1), preco_alertado="800", preco_liga="1000")
    # alerta errado: não conta
    criar_oportunidade(s, a1, p1, aberta_em=AGORA - timedelta(days=1), fechada_em=AGORA - timedelta(hours=20),
                       motivo=MotivoEncerramento.CASAMENTO_DESFEITO)
    # fora dos 7 dias
    criar_oportunidade(s, a1, p1, aberta_em=AGORA - timedelta(days=9), fechada_em=AGORA - timedelta(days=9) +
                       timedelta(hours=1), motivo=MotivoEncerramento.OFERTA_SUMIU)
    return p1, p2


def test_desde_do_periodo():
    assert q.desde_do_periodo("7d", AGORA) == AGORA - timedelta(days=7)
    assert q.desde_do_periodo("tudo", AGORA) is None
    with pytest.raises(ValueError):
        q.desde_do_periodo("1a", AGORA)


def test_numeros_do_periodo_contam_ativas_e_ignoram_casamento_desfeito(s):
    _cenario(s)
    n = q.numeros_periodo(s, AGORA - timedelta(days=7), AGORA)
    assert n.oportunidades == 2
    assert n.diferenca_bruta == Decimal("500.00")  # (1000−700) + (1000−800)
    assert n.desconto_medio == Decimal("25.00")
    assert n.duracao_media_min == 120  # (180 + 60) / 2: a ativa conta até agora
    assert n.produtos == 2
    assert q.numeros_periodo(s, None, AGORA).oportunidades == 3


def test_numeros_sem_oportunidades_tem_medias_vazias(s):
    n = q.numeros_periodo(s, AGORA - timedelta(days=7), AGORA)
    assert (n.oportunidades, n.diferenca_bruta, n.desconto_medio, n.duracao_media_min, n.produtos) == (
        0, Decimal("0.00"), None, None, 0,
    )


def test_por_dia_preenche_os_dias_vazios_no_fuso(s):
    _cenario(s)
    dias = q.por_dia(s, AGORA - timedelta(days=3), AGORA, SP)
    assert [d.dia for d in dias] == [date(2026, 10, 23) - timedelta(days=i) for i in (3, 2, 1, 0)]
    assert [d.oportunidades for d in dias] == [0, 1, 0, 1]


def test_ativas_e_ultima_aberta(s):
    _, p2 = _cenario(s)
    ativas = q.ativas(s)
    assert [a.produto.id for a in ativas] == [p2.id]
    assert ativas[0].preco_amazon == Decimal("800.00") and ativas[0].desconto_pct == Decimal("20.00")
    assert q.ultima_aberta_em(s) == AGORA - timedelta(hours=1)


def test_encerradas_paginadas_e_filtradas(s):
    _cenario(s)
    pagina = q.encerradas(s, None, None, 1, AGORA, por_pagina=2)
    assert pagina.total == 3 and len(pagina.itens) == 2
    assert pagina.itens[0].fechada_em > pagina.itens[1].fechada_em  # mais recentes primeiro
    assert pagina.itens[0].aberta is False
    so_sumiu = q.encerradas(s, None, MotivoEncerramento.OFERTA_SUMIU, 1, AGORA)
    assert [e.motivo for e in so_sumiu.itens] == ["oferta_sumiu"]
    assert q.encerradas(s, AGORA - timedelta(days=7), None, 1, AGORA).total == 2
