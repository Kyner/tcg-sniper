import random
from datetime import datetime, timedelta

import pytest
from fakes import (
    NavegadorFake,
    NotificadorFake,
    cartao_busca,
    criar_anuncio,
    criar_preco_liga,
    criar_produto,
    html_busca,
    pagina_html,
)
from sqlalchemy import select

from tcg_sniper.coletor_amazon.busca import Conferencia, ContextoBusca, DesafioAmazon, processar_produto, url_busca
from tcg_sniper.db import repositorio_amazon as repo
from tcg_sniper.db.models import AnuncioAmazon, ProdutoLiga, StatusCasamento
from tcg_sniper.parsing import ErroParser

AGORA = datetime.fromisoformat("2026-10-15T15:00:00+00:00")
NOME = "Caixa de Booster - Final Fantasy - Booster de Jogo"
CAPTCHA = '<html><body><form action="/errors/validateCaptcha"></form></body></html>'


@pytest.fixture
def produto(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "ff", nome=NOME)
        criar_preco_liga(s, p, "1000.00", listagem_em=AGORA - timedelta(hours=2), num_lojas=12)
        return p


def contexto(sessoes, config, paginas, dormidas=None):
    with sessoes() as s:
        cfg = repo.obter_config(s)
    navegador = NavegadorFake(paginas)
    notificador = NotificadorFake()
    ctx = ContextoBusca(
        sessoes=sessoes,
        navegador=navegador,
        notificador=notificador,
        config=config,
        cfg=cfg,
        relogio=lambda: AGORA,
        dormir=(dormidas.append if dormidas is not None else lambda _: None),
        rng=random.Random(1),
        nome_falha="amazon-1-1",
    )
    return ctx, navegador, notificador


def busca(cfg_url, *cartoes):
    return pagina_html(html_busca(*cartoes), url=cfg_url)


def test_url_busca_codifica_o_termo(sessoes):
    with sessoes() as s:
        cfg = repo.obter_config(s)
    assert url_busca(cfg, "Caixa - A & B + C #1 Edição") == (
        "https://www.amazon.com.br/s?k=Caixa+A+%26+B+%2B+C+%231+Edi%C3%A7%C3%A3o"
    )


def test_asin_novo_fica_pendente_e_so_a_busca_e_aberta(sessoes, config, produto):
    with sessoes() as s:
        url = url_busca(repo.obter_config(s), NOME)
    dormidas = []
    ctx, navegador, notificador = contexto(sessoes, config, {url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 100,00"))}, dormidas)
    assert processar_produto(ctx, produto) == Conferencia(0)
    assert navegador.visitadas == [url] and len(dormidas) == 1
    with sessoes() as s:
        anuncio = s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.asin == "B01"))
    assert (anuncio.status_casamento, anuncio.produto_id) == (StatusCasamento.PENDENTE, produto.id)
    assert notificador.mensagens == []


def test_confirmado_barato_conta_candidato_sem_abrir_o_produto_nem_alertar(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    ctx, navegador, notificador = contexto(sessoes, config, {url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 700,00"))})
    assert processar_produto(ctx, produto) == Conferencia(1)
    assert navegador.visitadas == [url] and notificador.mensagens == []  # o preço e o alerta são do monitor


def test_confirmado_acima_do_limite_nao_e_candidato(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    ctx, _, _ = contexto(sessoes, config, {url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 750,01"))})
    assert processar_produto(ctx, produto) == Conferencia(0)


def test_asin_casado_com_outro_produto_compara_com_o_preco_dele(sessoes, config, produto):
    with sessoes() as s, s.begin():
        outro = criar_produto(s, "outro", nome="Outro produto")
        criar_preco_liga(s, outro, "100.00", listagem_em=AGORA)
        criar_anuncio(s, "B09", produto=outro, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    # R$ 700 é 30% abaixo do produto buscado (R$ 1.000), mas acima do produto casado (R$ 100).
    ctx, _, _ = contexto(sessoes, config, {url: busca(url, cartao_busca("B09", "Outro", "R$ 700,00"))})
    assert processar_produto(ctx, produto) == Conferencia(0)


def test_captcha_na_busca_levanta_desafio(sessoes, config, produto):
    with sessoes() as s:
        url = url_busca(repo.obter_config(s), NOME)
    ctx, _, _ = contexto(sessoes, config, {url: pagina_html(CAPTCHA)})
    with pytest.raises(DesafioAmazon) as erro:
        processar_produto(ctx, produto)
    assert erro.value.url == url


def test_pagina_que_nao_le_salva_o_html_e_levanta(sessoes, config, produto):
    with sessoes() as s:
        url = url_busca(repo.obter_config(s), NOME)
    ctx, _, _ = contexto(sessoes, config, {url: pagina_html("<html><body>layout novo</body></html>")})
    with pytest.raises(ErroParser):
        processar_produto(ctx, produto)
    assert (config.dir_dados / "falhas" / "amazon-1-1-busca.html").exists()


def test_usar_nome_en_busca_pelo_termo_em_ingles(sessoes, config, produto):
    with sessoes() as s, s.begin():
        s.get(ProdutoLiga, produto.id).nome_en = "Booster Box - Final Fantasy"
        cfg = repo.obter_config(s)
        url_pt, url_en = url_busca(cfg, NOME), url_busca(cfg, "Booster Box - Final Fantasy")
    assert "Booster+Box+Final+Fantasy" in url_en
    with sessoes() as s:
        p = s.get(ProdutoLiga, produto.id)
        ctx, navegador, _ = contexto(sessoes, config, {url_pt: busca(url_pt), url_en: busca(url_en)})
        processar_produto(ctx, p)
        processar_produto(ctx, p, usar_nome_en=True)
        processar_produto(ctx, p, usar_nome_en=False)
    assert navegador.visitadas == [url_pt, url_en, url_pt]


def test_usar_nome_en_sem_nome_en_busca_em_portugues(sessoes, config, produto):
    with sessoes() as s:
        url_pt = url_busca(repo.obter_config(s), NOME)
    ctx, navegador, _ = contexto(sessoes, config, {url_pt: busca(url_pt)})
    processar_produto(ctx, produto, usar_nome_en=True)
    assert navegador.visitadas == [url_pt]
