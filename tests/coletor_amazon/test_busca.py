import random
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fakes import (
    NavegadorFake,
    NotificadorFake,
    cartao_busca,
    criar_anuncio,
    criar_preco_liga,
    criar_produto,
    fixture_amazon,
    html_busca,
    html_produto_amazon,
    html_vendedor,
    pagina_html,
)
from sqlalchemy import func, select

from tcg_sniper.coletor_amazon.busca import (
    MAX_CONFIRMADOS_AUSENTES,
    Conferencia,
    ContextoBusca,
    DesafioAmazon,
    processar_produto,
    url_busca,
)
from tcg_sniper.coletor_amazon.parsers import url_produto, url_vendedor
from tcg_sniper.db import repositorio_amazon as repo
from tcg_sniper.db.models import (
    AnuncioAmazon,
    Envio,
    Oportunidade,
    OrigemPreco,
    ProdutoLiga,
    StatusCasamento,
    VendedorAmazon,
)
from tcg_sniper.notificador.base import Destino
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


def test_asin_novo_fica_pendente_e_nao_abre_o_produto(sessoes, config, produto):
    with sessoes() as s:
        url = url_busca(repo.obter_config(s), NOME)
    ctx, navegador, notificador = contexto(sessoes, config, {url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 100,00"))})
    assert processar_produto(ctx, produto) == Conferencia(0, 0)
    assert navegador.visitadas == [url]
    with sessoes() as s:
        anuncio = s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.asin == "B01"))
    assert (anuncio.status_casamento, anuncio.produto_id) == (StatusCasamento.PENDENTE, produto.id)
    assert notificador.mensagens == []


def test_confirmado_barato_vendido_pela_amazon_abre_oportunidade_e_alerta(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    paginas = {
        url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 700,00")),
        url_produto("B01"): pagina_html(html_produto_amazon("Caixa FF", "R$ 699,90", "Amazon.com.br", "Amazon.com.br")),
    }
    dormidas = []
    ctx, navegador, notificador = contexto(sessoes, config, paginas, dormidas)
    assert processar_produto(ctx, produto) == Conferencia(1, 1)
    assert navegador.visitadas == [url, url_produto("B01")]
    assert len(dormidas) == 2  # uma pausa humana antes de cada página
    [(destino, texto)] = notificador.mensagens
    assert destino is Destino.OPORTUNIDADES
    assert texto.startswith(f"Oportunidade: {NOME}\nAmazon: R$ 699,90 (vendido pela Amazon), 30% abaixo da Liga")
    with sessoes() as s:
        op = s.scalar(select(Oportunidade))
    assert (op.preco_amazon, op.preco_liga, op.desconto_pct) == (Decimal("699.90"), Decimal("1000.00"), Decimal("30.01"))


def test_oportunidade_ja_alertada_no_mesmo_preco_nao_alerta_de_novo(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)

    def paginas():
        return {
            url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 700,00")),
            url_produto("B01"): pagina_html(html_produto_amazon("Caixa FF", "R$ 700,00", "Amazon.com.br", None)),
        }

    ctx, _, notificador = contexto(sessoes, config, paginas())
    processar_produto(ctx, produto)
    ctx2, _, notificador2 = contexto(sessoes, config, paginas())
    processar_produto(ctx2, produto)
    assert len(notificador.mensagens) == 1 and notificador2.mensagens == []


def test_confirmado_acima_do_limite_nao_abre_o_produto(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    ctx, navegador, _ = contexto(sessoes, config, {url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 750,01"))})
    assert processar_produto(ctx, produto) == Conferencia(0, 0)
    assert navegador.visitadas == [url]


def test_asin_casado_com_outro_produto_compara_com_o_preco_dele(sessoes, config, produto):
    with sessoes() as s, s.begin():
        outro = criar_produto(s, "outro", nome="Outro produto")
        criar_preco_liga(s, outro, "100.00", listagem_em=AGORA)
        criar_anuncio(s, "B09", produto=outro, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    # R$ 700 é 30% abaixo do produto buscado (R$ 1.000), mas acima do produto casado (R$ 100).
    ctx, navegador, _ = contexto(sessoes, config, {url: busca(url, cartao_busca("B09", "Outro", "R$ 700,00"))})
    assert processar_produto(ctx, produto) == Conferencia(0, 0)
    assert navegador.visitadas == [url]


def test_lojista_fba_desconhecido_abre_o_perfil_e_usa_o_cache_depois(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)

    def paginas():
        return {
            url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 700,00")),
            url_produto("B01"): pagina_html(html_produto_amazon("Caixa FF", "R$ 700,00", "Loja X", "Amazon", "A1")),
            url_vendedor("A1"): pagina_html(html_vendedor("Loja X", 97, "2.340")),
        }

    ctx, navegador, notificador = contexto(sessoes, config, paginas())
    processar_produto(ctx, produto)
    assert navegador.visitadas == [url, url_produto("B01"), url_vendedor("A1")]
    assert "vendido por Loja X (97% de 2.340 avaliações), enviado pela Amazon" in notificador.mensagens[0][1]

    ctx2, navegador2, _ = contexto(sessoes, config, paginas())
    processar_produto(ctx2, produto)
    assert url_vendedor("A1") not in navegador2.visitadas  # avaliado há menos de 7 dias
    with sessoes() as s:
        assert s.scalar(select(func.count()).select_from(VendedorAmazon).where(VendedorAmazon.seller_id == "A1")) == 1


def test_lojista_com_envio_proprio_nao_alerta_nem_abre_o_perfil(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    paginas = {
        url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 700,00")),
        url_produto("B01"): pagina_html(html_produto_amazon("Caixa FF", "R$ 700,00", "Loja X", "Loja X", "A1")),
    }
    ctx, navegador, notificador = contexto(sessoes, config, paginas)
    processar_produto(ctx, produto)
    assert navegador.visitadas == [url, url_produto("B01")]
    assert notificador.mensagens == []


@pytest.mark.parametrize("onde", ["busca", "produto"])
def test_captcha_levanta_desafio(sessoes, config, produto, onde):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    paginas = {
        url: pagina_html(CAPTCHA) if onde == "busca" else busca(url, cartao_busca("B01", "Caixa FF", "R$ 700,00")),
        url_produto("B01"): pagina_html(CAPTCHA),
    }
    ctx, _, _ = contexto(sessoes, config, paginas)
    with pytest.raises(DesafioAmazon) as erro:
        processar_produto(ctx, produto)
    assert erro.value.url == (url if onde == "busca" else url_produto("B01"))


def test_pagina_que_nao_le_salva_o_html_e_levanta(sessoes, config, produto):
    with sessoes() as s:
        url = url_busca(repo.obter_config(s), NOME)
    ctx, _, _ = contexto(sessoes, config, {url: pagina_html("<html><body>layout novo</body></html>")})
    with pytest.raises(ErroParser):
        processar_produto(ctx, produto)
    assert (config.dir_dados / "falhas" / "amazon-1-1-busca.html").exists()


def _paginas_preco(url, preco):
    return {
        url: busca(url, cartao_busca("B01", "Caixa FF", preco)),
        url_produto("B01"): pagina_html(html_produto_amazon("Caixa FF", preco, "Amazon.com.br", None)),
    }


def test_oportunidade_aberta_e_rechecada_fecha_e_reabre(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    ctx, _, notificador = contexto(sessoes, config, _paginas_preco(url, "R$ 700,00"))
    processar_produto(ctx, produto)
    assert len(notificador.mensagens) == 1

    ctx2, navegador2, notificador2 = contexto(sessoes, config, _paginas_preco(url, "R$ 800,00"))
    assert processar_produto(ctx2, produto) == Conferencia(1, 1)
    assert url_produto("B01") in navegador2.visitadas
    assert notificador2.mensagens == []
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)).fechada_em is not None

    ctx3, _, notificador3 = contexto(sessoes, config, _paginas_preco(url, "R$ 700,00"))
    processar_produto(ctx3, produto)
    assert len(notificador3.mensagens) == 1
    with sessoes() as s:
        assert s.scalar(select(func.count()).select_from(Oportunidade)) == 2


def test_oportunidade_aberta_realerta_quando_o_preco_cai_mais(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    ctx, _, notificador = contexto(sessoes, config, _paginas_preco(url, "R$ 700,00"))
    processar_produto(ctx, produto)
    ctx2, _, notificador2 = contexto(sessoes, config, _paginas_preco(url, "R$ 665,00"))
    processar_produto(ctx2, produto)
    assert len(notificador.mensagens) == 1 and len(notificador2.mensagens) == 1
    with sessoes() as s:
        op = s.scalar(select(Oportunidade).where(Oportunidade.fechada_em.is_(None)))
    assert op.preco_alertado == Decimal("665.00")


def test_confirmado_ausente_da_busca_tem_a_pagina_lida_e_o_titulo_atualizado(sessoes, config, produto):
    with sessoes() as s, s.begin():
        manual = repo.casar_link_manual(s, produto.id, "B0MANUAL01", AGORA - timedelta(hours=1))
        url = url_busca(repo.obter_config(s), NOME)
    paginas = {
        url: busca(url, cartao_busca("B01", "Outra coisa", "R$ 100,00")),
        url_produto("B0MANUAL01"): pagina_html(
            html_produto_amazon("Caixa FF lida na página", "R$ 699,90", "Amazon.com.br", "Amazon.com.br")
        ),
    }
    ctx, navegador, notificador = contexto(sessoes, config, paginas)
    assert processar_produto(ctx, produto) == Conferencia(1, 0)
    assert navegador.visitadas == [url, url_produto("B0MANUAL01")]
    with sessoes() as s:
        lido = s.get(AnuncioAmazon, manual.id)
    assert (lido.titulo, lido.visto_ultimo_em) == ("Caixa FF lida na página", AGORA)
    [(destino, texto)] = notificador.mensagens
    assert destino is Destino.OPORTUNIDADES and "R$ 699,90" in texto


def test_no_maximo_5_ausentes_por_busca_os_mais_antigos_primeiro(sessoes, config, produto):
    asins = [f"B0AUSENT{i:02d}" for i in range(7)]
    with sessoes() as s, s.begin():
        url = url_busca(repo.obter_config(s), NOME)
        for i, asin in enumerate(asins):
            anuncio = criar_anuncio(s, asin, produto=produto, status=StatusCasamento.CONFIRMADO)
            if i > 0:  # o 0 nunca foi lido; os demais, do mais antigo (1) ao mais novo (6)
                repo.registrar_preco(
                    s, anuncio.id, Decimal("900.00"), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO,
                    AGORA - timedelta(hours=10 - i), config.zona,
                )
    paginas = {url: busca(url)}
    for asin in asins:
        paginas[url_produto(asin)] = pagina_html(html_produto_amazon(f"Item {asin}", "R$ 900,00", "Loja", "Loja"))
    ctx, navegador, _ = contexto(sessoes, config, paginas)
    assert processar_produto(ctx, produto) == Conferencia(MAX_CONFIRMADOS_AUSENTES, 0)
    assert navegador.visitadas == [url] + [url_produto(a) for a in asins[:5]]


def test_ausente_que_ja_e_candidato_nao_e_lido_duas_vezes(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    paginas = {
        url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 700,00")),
        url_produto("B01"): pagina_html(html_produto_amazon("Caixa FF", "R$ 700,00", "Amazon.com.br", None)),
    }
    ctx, navegador, _ = contexto(sessoes, config, paginas)
    assert processar_produto(ctx, produto) == Conferencia(1, 1)
    assert navegador.visitadas == [url, url_produto("B01")]


def test_ausente_ilegivel_nao_impede_a_leitura_dos_outros_ausentes(sessoes, config, produto):
    with sessoes() as s, s.begin():
        url = url_busca(repo.obter_config(s), NOME)
        criar_anuncio(s, "B0RUIM0001", produto=produto, status=StatusCasamento.CONFIRMADO)  # nunca lido: vem antes
        bom = criar_anuncio(s, "B0BOM00001", produto=produto, status=StatusCasamento.CONFIRMADO)
        repo.registrar_preco(
            s, bom.id, Decimal("900.00"), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO,
            AGORA - timedelta(hours=3), config.zona,
        )
        bom_id = bom.id
    paginas = {
        url: busca(url),
        url_produto("B0RUIM0001"): pagina_html("<html><body>página não encontrada</body></html>"),
        url_produto("B0BOM00001"): pagina_html(html_produto_amazon("Item bom", "R$ 850,00", "Loja", "Loja")),
    }
    ctx, navegador, _ = contexto(sessoes, config, paginas)
    with pytest.raises(ErroParser):
        processar_produto(ctx, produto)
    assert navegador.visitadas == [url, url_produto("B0RUIM0001"), url_produto("B0BOM00001")]
    with sessoes() as s:
        assert s.get(AnuncioAmazon, bom_id).visto_ultimo_em == AGORA


def test_ausente_cuja_pagina_nao_le_segue_o_fluxo_de_erro(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B0SUMIU001", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    paginas = {
        url: busca(url, cartao_busca("B0NOVO0001", "Novo pendente", "R$ 10,00")),
        url_produto("B0SUMIU001"): pagina_html("<html><body>página não encontrada</body></html>"),
    }
    ctx, _, _ = contexto(sessoes, config, paginas)
    with pytest.raises(ErroParser):
        processar_produto(ctx, produto)
    with sessoes() as s:  # a busca já tinha sido gravada antes da leitura que falhou
        assert s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.asin == "B0NOVO0001")) is not None


def test_leitura_grava_a_opcao_da_variacao(sessoes, config, produto):
    with sessoes() as s, s.begin():
        manual = repo.casar_link_manual(s, produto.id, "B0DTS76B5L", AGORA - timedelta(hours=1))
        url = url_busca(repo.obter_config(s), NOME)
    paginas = {
        url: busca(url),
        url_produto("B0DTS76B5L"): pagina_html(fixture_amazon("produto_variacao")),
        url_vendedor("ANP69P8PNCJ0B"): pagina_html(fixture_amazon("vendedor")),
    }
    ctx, _, _ = contexto(sessoes, config, paginas)
    processar_produto(ctx, produto)
    with sessoes() as s:
        lido = s.get(AnuncioAmazon, manual.id)
    assert lido.variacao == "Collector Booster Box"
    assert lido.titulo_exibicao.endswith(" — Collector Booster Box")


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
