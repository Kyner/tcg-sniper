from datetime import timedelta

from fakes import T0, criar_anuncio, criar_produto
from fakes_oportunidades import criar_atual_amazon

from tcg_sniper.consultas.anuncio_do_produto import anuncio_do_produto
from tcg_sniper.db.models import StatusCasamento


def test_sem_casado_confirmado_nao_ha_anuncio(s):
    p = criar_produto(s, "semcasado")
    criar_anuncio(s, "B0SEMCAS01", p, StatusCasamento.PENDENTE)
    criar_anuncio(s, "B0SEMCAS02", p, StatusCasamento.IGNORADO)
    assert anuncio_do_produto(s, p.id) is None


def test_com_preco_escolhe_o_mais_barato_e_conta_os_casados(s):
    p = criar_produto(s, "maisbarato")
    caro = criar_anuncio(s, "B0BARATO01", p, StatusCasamento.CONFIRMADO)
    barato = criar_anuncio(s, "B0BARATO02", p, StatusCasamento.CONFIRMADO)
    sem = criar_anuncio(s, "B0BARATO03", p, StatusCasamento.CONFIRMADO)
    criar_atual_amazon(s, caro, "900.00")
    criar_atual_amazon(s, barato, "700.00")
    criar_atual_amazon(s, sem, None, coletado_em=T0 + timedelta(days=1))
    r = anuncio_do_produto(s, p.id)
    assert r.url == barato.url and r.titulo == barato.titulo
    assert r.sem_preco is False and r.anuncios_casados == 3


def test_sem_preco_escolhe_a_leitura_mais_recente(s):
    p = criar_produto(s, "semprec")
    velho = criar_anuncio(s, "B0SEMPRE01", p, StatusCasamento.CONFIRMADO)
    novo = criar_anuncio(s, "B0SEMPRE02", p, StatusCasamento.CONFIRMADO)
    criar_atual_amazon(s, velho, None, coletado_em=T0)
    criar_atual_amazon(s, novo, None, coletado_em=T0 + timedelta(hours=1))
    r = anuncio_do_produto(s, p.id)
    assert r.url == novo.url and r.sem_preco is True and r.anuncios_casados == 2


def test_sem_leitura_nenhuma_pega_o_id_mais_alto(s):
    p = criar_produto(s, "semleit")
    criar_anuncio(s, "B0SEMLEI01", p, StatusCasamento.CONFIRMADO)
    ultimo = criar_anuncio(s, "B0SEMLEI02", p, StatusCasamento.CONFIRMADO)
    r = anuncio_do_produto(s, p.id)
    assert r.url == ultimo.url and r.sem_preco is True and r.anuncios_casados == 2
