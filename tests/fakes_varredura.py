"""Ajudantes dos testes dos dois laços da Amazon (busca e monitor) e da base comum."""

import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fakes import (
    AvisadorFake,
    NavegadorInterativoFake,
    criar_anuncio,
    criar_preco_liga,
    criar_produto,
    html_busca,
    oferta_lista,
    pagina_html,
)
from fakes_ofertas import bloco_oferta, html_ofertas

from tcg_sniper.coletor_amazon.busca import url_busca
from tcg_sniper.coletor_amazon.parsers import url_ofertas
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import Envio, OrigemPreco, StatusCasamento

SP = ZoneInfo("America/Sao_Paulo")
MEIO_DIA = datetime(2026, 10, 15, 12, 0, tzinfo=SP)
CAPTCHA = '<html><body><form action="/errors/validateCaptcha"></form></body></html>'


class Relogio:
    def __init__(self, agora):
        self.agora = agora

    def __call__(self):
        return self.agora


class FabricaFake:
    """Fábrica de navegador: devolve sempre o mesmo navegador falso e conta aberturas e fechamentos."""

    def __init__(self, navegador):
        self.navegador = navegador
        self.abertos = 0
        self.fechados = 0

    def __call__(self):
        fabrica = self

        class Contexto:
            def __enter__(self):
                fabrica.abertos += 1
                return fabrica.navegador

            def __exit__(self, *_exc):
                fabrica.fechados += 1

        return Contexto()


def criar_laco(classe, engine, sessoes, config, paginas, apos_clique=None, relogio=None):
    """Um laço (`VarreduraBusca`, `VarreduraMonitor` ou uma subclasse de teste da base) com navegador,
    avisador e relógio falsos. Devolve (laço, navegador, fábrica, avisador, relógio)."""
    navegador = NavegadorInterativoFake(paginas, apos_clique or [])
    fabrica = FabricaFake(navegador)
    avisador = AvisadorFake()
    relogio = relogio or Relogio(MEIO_DIA)
    laco = classe(
        engine, sessoes, fabrica, avisador, config, relogio=relogio, rng=random.Random(1), dormir=lambda _: None
    )
    return laco, navegador, fabrica, avisador, relogio


def confirmado(sessoes, nome, asin, preco=None, lido_em=MEIO_DIA):
    """Produto (R$ 1.000 na Liga) casado com o anúncio; com `preco`, já lido pelo monitor em `lido_em` com
    essa oferta da Amazon como a melhor. A descoberta do produto só volta daqui a 7 dias."""
    with sessoes() as s, s.begin():
        p = criar_produto(s, nome, nome=nome)
        criar_preco_liga(s, p, "1000.00", listagem_em=MEIO_DIA)
        a = criar_anuncio(s, asin, produto=p, status=StatusCasamento.CONFIRMADO)
        if preco is not None:
            o = oferta_lista(preco, vendedor="Amazon.com.br", seller_id="amazon", envio=Envio.AMAZON, posicao=0)
            repo_amz.gravar_ofertas(s, a.id, lido_em, [repo_amz.OfertaAvaliada(o, None, True, True)])
            repo_amz.registrar_preco(s, a.id, o.preco, OrigemPreco.OFERTAS, None, Envio.AMAZON, lido_em, SP)
        repo_amz.sincronizar_fila(s, MEIO_DIA)
        repo_amz.reagendar(s, p.id, MEIO_DIA, MEIO_DIA + timedelta(days=7), False)
        return p.id, a.id


def livre(sessoes, nome):
    """Produto sem par, vencido na fila da descoberta. Devolve a URL da busca."""
    with sessoes() as s, s.begin():
        p = criar_produto(s, nome, nome=nome)
        criar_preco_liga(s, p, "1000.00", listagem_em=MEIO_DIA)
        repo_amz.sincronizar_fila(s, MEIO_DIA - timedelta(hours=1))
        return url_busca(repo_amz.obter_config(s), nome)


def ofertas(asin, preco):
    return pagina_html(
        html_ofertas(bloco_oferta(preco, "Amazon.com.br", seller_id=None, envia=None, destaque=True)),
        url=url_ofertas(asin),
    )


def vazia(url):
    return pagina_html(html_busca(), url=url)
