from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto
from sqlalchemy import func, select

from tcg_sniper.coletor_amazon.modelos import AvaliacaoVendedor, ResultadoBusca
from tcg_sniper.db import repositorio_amazon as repo
from tcg_sniper.db.models import (
    AnuncioAmazon,
    Envio,
    FilaAmazon,
    Oportunidade,
    OrigemPreco,
    PrecoAmazon,
    PrecoAtualAmazon,
    StatusCasamento,
)

SP = ZoneInfo("America/Sao_Paulo")


def resultado(asin, preco="100.00", titulo=None):
    return ResultadoBusca(
        asin=asin,
        titulo=titulo or f"Título {asin}",
        url=f"https://www.amazon.com.br/dp/{asin}",
        preco=None if preco is None else Decimal(preco),
        patrocinado=False,
    )


def test_obter_config_devolve_a_linha_da_migracao(s):
    assert repo.obter_config(s).desconto_min_pct == 25


def test_sincronizar_fila_acompanha_os_ativos(s):
    a = criar_produto(s, "a", ativo=True)
    b = criar_produto(s, "b", ativo=True)
    criar_produto(s, "c", ativo=False)
    repo.sincronizar_fila(s, T0)
    assert repo.ids_na_fila(s) == {a.id, b.id}
    assert s.get(FilaAmazon, a.id).proxima_busca_em == T0

    b.ativo = False
    s.flush()
    repo.sincronizar_fila(s, T0 + timedelta(hours=1))
    assert repo.ids_na_fila(s) == {a.id}
    assert s.get(FilaAmazon, a.id).entrou_em == T0  # quem já estava não é reinserido


def test_proximo_da_fila_mais_antigo_vencido_e_empate_pelo_preco_da_liga(s):
    barato = criar_produto(s, "barato")
    caro = criar_produto(s, "caro")
    futuro = criar_produto(s, "futuro")
    criar_preco_liga(s, barato, "100.00")
    criar_preco_liga(s, caro, "900.00")
    repo.sincronizar_fila(s, T0)
    s.get(FilaAmazon, futuro.id).proxima_busca_em = T0 + timedelta(hours=2)
    s.flush()

    assert repo.proximo_da_fila(s, T0).produto_id == caro.id
    repo.reagendar(s, caro.id, T0, T0 + timedelta(hours=1), teve_candidato=False)
    assert repo.proximo_da_fila(s, T0).produto_id == barato.id
    repo.reagendar(s, barato.id, T0, T0 + timedelta(hours=1), teve_candidato=True)
    assert repo.proximo_da_fila(s, T0) is None
    fila = s.get(FilaAmazon, barato.id)
    assert (fila.ultima_busca_em, fila.ultimo_candidato_em) == (T0, T0)
    assert s.get(FilaAmazon, caro.id).ultimo_candidato_em is None


def test_gravar_busca_cria_pendente_com_sugestao_e_nao_troca_a_sugestao(s):
    a = criar_produto(s, "a")
    b = criar_produto(s, "b")
    anuncios = repo.gravar_busca(s, [resultado("B01"), resultado("B01", "90.00"), resultado("B02")], a.id, T0, SP)
    assert [x.asin for x in anuncios] == ["B01", "B02"]
    assert anuncios[0].status_casamento is StatusCasamento.PENDENTE
    assert anuncios[0].produto_id == a.id
    assert s.get(PrecoAtualAmazon, anuncios[0].id).preco == Decimal("100.00")  # vale o primeiro cartão

    depois = T0 + timedelta(hours=1)
    repo.gravar_busca(s, [resultado("B01", titulo="Novo título")], b.id, depois, SP)
    anuncio = s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.asin == "B01"))
    assert (anuncio.produto_id, anuncio.titulo, anuncio.visto_ultimo_em) == (a.id, "Novo título", depois)


def test_registrar_preco_so_grava_historico_quando_muda_ou_no_primeiro_do_dia(s):
    anuncio = criar_anuncio(s)

    def gravar(preco, quando):
        valor = None if preco is None else Decimal(preco)
        return repo.registrar_preco(s, anuncio.id, valor, OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, quando, SP)

    assert gravar("100.00", T0) is True
    assert gravar("100.00", T0 + timedelta(hours=1)) is False
    assert gravar("95.00", T0 + timedelta(hours=2)) is True
    assert gravar(None, T0 + timedelta(hours=3)) is True
    assert gravar(None, T0 + timedelta(days=1)) is True  # primeira leitura do dia seguinte
    total = s.scalar(select(func.count()).select_from(PrecoAmazon).where(PrecoAmazon.anuncio_id == anuncio.id))
    assert total == 4
    assert s.get(PrecoAtualAmazon, anuncio.id).preco is None


def test_leitura_da_busca_nao_apaga_vendedor_e_envio_da_pagina_do_produto(s):
    anuncio = criar_anuncio(s)
    amazon = repo.vendedor_da_amazon(s)
    repo.registrar_preco(s, anuncio.id, Decimal("80.00"), OrigemPreco.PRODUTO, amazon.id, Envio.AMAZON, T0, SP)
    repo.registrar_preco(
        s, anuncio.id, Decimal("85.00"), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, T0 + timedelta(hours=1), SP
    )
    atual = s.get(PrecoAtualAmazon, anuncio.id)
    assert (atual.preco, atual.origem, atual.vendedor_id, atual.envio) == (
        Decimal("85.00"), OrigemPreco.BUSCA, amazon.id, Envio.AMAZON
    )


def test_confirmados_com_referencia_so_traz_confirmados_e_o_preco_do_produto_casado(s):
    a = criar_produto(s, "a")
    b = criar_produto(s, "b")
    criar_preco_liga(s, a, "1000.00")
    criar_preco_liga(s, b, "50.00")
    confirmado = criar_anuncio(s, "B01", produto=a, status=StatusCasamento.CONFIRMADO)
    pendente = criar_anuncio(s, "B02", produto=b)
    for anuncio in (confirmado, pendente):
        repo.registrar_preco(s, anuncio.id, Decimal("700.00"), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, T0, SP)

    linhas = repo.confirmados_com_referencia(s, [confirmado.id, pendente.id])
    assert [(linha.anuncio.asin, linha.produto.id, linha.liga.preco_a_partir) for linha in linhas] == [
        ("B01", a.id, Decimal("1000.00"))
    ]


def test_vendedores(s):
    assert repo.vendedor_da_amazon(s).seller_id == "amazon"
    assert repo.obter_vendedor(s, "A1") is None
    v = repo.gravar_vendedor(s, AvaliacaoVendedor("A1", "Loja", Decimal(97), 2340), T0)
    assert (v.nome, v.pct_positivas, v.num_avaliacoes, v.avaliado_em) == ("Loja", Decimal(97), 2340, T0)
    v2 = repo.gravar_vendedor(s, AvaliacaoVendedor("A1", "Loja", Decimal(96), 2400), T0 + timedelta(days=8))
    assert v2.id == v.id and v2.num_avaliacoes == 2400


def test_oportunidade_abrir_atualizar_fechar(s):
    produto = criar_produto(s)
    anuncio = criar_anuncio(s, produto=produto, status=StatusCasamento.CONFIRMADO)
    amazon = repo.vendedor_da_amazon(s)
    op = repo.abrir_oportunidade(
        s, anuncio_id=anuncio.id, produto_id=produto.id, preco_amazon=Decimal("700.00"),
        preco_liga=Decimal("1000.00"), desconto_pct=Decimal("30.00"), vendedor_id=amazon.id,
        envio=Envio.AMAZON, agora=T0,
    )
    assert repo.oportunidade_aberta(s, anuncio.id).id == op.id
    assert (op.alertada_em, op.preco_alertado) == (T0, Decimal("700.00"))

    depois = T0 + timedelta(hours=1)
    repo.atualizar_oportunidade(
        s, op, preco_amazon=Decimal("650.00"), preco_liga=Decimal("1000.00"), desconto_pct=Decimal("35.00"),
        vendedor_id=amazon.id, envio=Envio.AMAZON, alertou=True, agora=depois,
    )
    assert (op.preco_amazon, op.alertada_em, op.preco_alertado) == (Decimal("650.00"), depois, Decimal("650.00"))

    repo.fechar_oportunidade(s, op, depois)
    assert repo.oportunidade_aberta(s, anuncio.id) is None


def test_fechar_oportunidades_sem_leitura_ha_24h(s):
    produto = criar_produto(s)
    velho = criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO, agora=T0)
    novo = criar_anuncio(s, "B02", produto=produto, status=StatusCasamento.CONFIRMADO, agora=T0 + timedelta(hours=20))
    for anuncio in (velho, novo):
        repo.abrir_oportunidade(
            s, anuncio_id=anuncio.id, produto_id=produto.id, preco_amazon=Decimal(1), preco_liga=Decimal(2),
            desconto_pct=Decimal(50), vendedor_id=None, envio=Envio.AMAZON, agora=T0,
        )
    assert repo.fechar_oportunidades_sem_leitura(s, T0 + timedelta(hours=25)) == 1
    assert repo.oportunidade_aberta(s, velho.id) is None
    assert repo.oportunidade_aberta(s, novo.id) is not None


def test_casamento_confirmar_trocar_ignorar_desfazer(s):
    a = criar_produto(s, "a")
    b = criar_produto(s, "b")
    anuncio = criar_anuncio(s, produto=a)
    assert repo.confirmar_casamento(s, anuncio.id, a.id, T0) is True
    assert (anuncio.status_casamento, anuncio.produto_id, anuncio.revisado_em) == (StatusCasamento.CONFIRMADO, a.id, T0)

    op = repo.abrir_oportunidade(
        s, anuncio_id=anuncio.id, produto_id=a.id, preco_amazon=Decimal(1), preco_liga=Decimal(2),
        desconto_pct=Decimal(50), vendedor_id=None, envio=Envio.AMAZON, agora=T0,
    )
    assert repo.confirmar_casamento(s, anuncio.id, b.id, T0) is True  # trocar fecha a oportunidade do produto antigo
    s.refresh(op)
    assert op.fechada_em == T0 and anuncio.produto_id == b.id

    assert repo.ignorar_anuncio(s, anuncio.id, T0) is True
    assert anuncio.status_casamento is StatusCasamento.IGNORADO
    assert repo.desfazer_casamento(s, anuncio.id, T0) is True
    assert (anuncio.status_casamento, anuncio.revisado_em) == (StatusCasamento.PENDENTE, None)
    assert repo.confirmar_casamento(s, 999_999, a.id, T0) is False
    assert s.scalar(select(func.count()).select_from(Oportunidade).where(Oportunidade.fechada_em.is_(None))) == 0


def test_confirmados_com_referencia_reflete_preco_registrado_na_mesma_sessao(s):
    produto = criar_produto(s)
    criar_preco_liga(s, produto, "1000.00")
    anuncio = criar_anuncio(s, produto=produto, status=StatusCasamento.CONFIRMADO)
    repo.registrar_preco(s, anuncio.id, Decimal("700.00"), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, T0, SP)
    antes = repo.confirmados_com_referencia(s, [anuncio.id])
    assert antes[0].atual.preco == Decimal("700.00")

    amazon = repo.vendedor_da_amazon(s)
    depois_t = T0 + timedelta(hours=1)
    repo.registrar_preco(s, anuncio.id, Decimal("600.00"), OrigemPreco.PRODUTO, amazon.id, Envio.AMAZON, depois_t, SP)
    atual = repo.confirmados_com_referencia(s, [anuncio.id])[0].atual
    assert (atual.preco, atual.vendedor_id, atual.envio) == (Decimal("600.00"), amazon.id, Envio.AMAZON)
