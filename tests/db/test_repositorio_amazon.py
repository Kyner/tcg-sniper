import threading
import time
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, criar_anuncio, criar_par, criar_preco_liga, criar_produto
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from tcg_sniper.coletor_amazon.modelos import AvaliacaoVendedor, ResultadoBusca
from tcg_sniper.db import repositorio_amazon as repo
from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db.models import (
    AnuncioAmazon,
    Envio,
    FilaAmazon,
    Oportunidade,
    OrigemCasamento,
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


PENDENTE, CONFIRMADO, IGNORADO = StatusCasamento.PENDENTE, StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO


def test_gravar_busca_cria_o_par_pendente_do_produto_buscado(s):
    a = criar_produto(s, "a")
    repo.sincronizar_fila(s, T0 - timedelta(days=10))
    gravacao = repo.gravar_busca(s, [resultado("B01"), resultado("B01", "90.00"), resultado("B02")], a.id, T0, SP)
    assert [x.asin for x in gravacao.anuncios] == ["B01", "B02"] and gravacao.pares_novos == 2
    par = repo_casamento.obter_par(s, gravacao.anuncios[0].id, a.id)
    assert (par.status, par.origem, par.visto_primeiro_em, par.visto_ultimo_em) == (PENDENTE, None, T0, T0)
    assert s.get(PrecoAtualAmazon, gravacao.anuncios[0].id).preco == Decimal("100.00")  # vale o primeiro cartão
    assert s.get(FilaAmazon, a.id).ultimo_par_novo_em == T0


def test_anuncio_ignorado_para_a_vira_pendente_na_busca_de_b(s):
    a, b = criar_produto(s, "a"), criar_produto(s, "b")
    anuncio = criar_anuncio(s, "B01", produto=a, status=IGNORADO, origem=OrigemCasamento.MANUAL)
    depois = T0 + timedelta(hours=1)
    gravacao = repo.gravar_busca(s, [resultado("B01", titulo="Novo título")], b.id, depois, SP)
    assert gravacao.pares_novos == 1
    assert repo_casamento.obter_par(s, anuncio.id, b.id).status is PENDENTE
    assert repo_casamento.obter_par(s, anuncio.id, a.id).status is IGNORADO  # ignorado vale só para o par
    s.refresh(anuncio)
    assert (anuncio.titulo, anuncio.visto_ultimo_em) == ("Novo título", depois)


def test_par_existente_so_atualiza_o_visto(s):
    a = criar_produto(s, "a")
    repo.sincronizar_fila(s, T0)
    ignorado = criar_anuncio(s, "B01", produto=a, status=IGNORADO, origem=OrigemCasamento.MANUAL)
    confirmado = criar_anuncio(s, "B02", produto=a, status=CONFIRMADO, origem=OrigemCasamento.MANUAL)
    depois = T0 + timedelta(days=1)
    gravacao = repo.gravar_busca(s, [resultado("B01"), resultado("B02")], a.id, depois, SP)
    assert gravacao.pares_novos == 0
    for anuncio, status in ((ignorado, IGNORADO), (confirmado, CONFIRMADO)):
        par = repo_casamento.obter_par(s, anuncio.id, a.id)
        assert (par.status, par.visto_primeiro_em, par.visto_ultimo_em) == (status, T0, depois)
    assert s.get(FilaAmazon, a.id).ultimo_par_novo_em is None


def test_anuncio_confirmado_para_q_entra_ignorado_para_p_e_nao_tira_da_seca(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    repo.sincronizar_fila(s, T0)
    anuncio = criar_anuncio(s, "B01", produto=q, status=CONFIRMADO, origem=OrigemCasamento.MANUAL)
    gravacao = repo.gravar_busca(s, [resultado("B01")], p.id, T0, SP)
    par = repo_casamento.obter_par(s, anuncio.id, p.id)
    assert (par.status, par.origem) == (IGNORADO, OrigemCasamento.OUTRO_CONFIRMADO)
    assert gravacao.pares_novos == 0 and s.get(FilaAmazon, p.id).ultimo_par_novo_em is None


def test_descoberta_olha_os_pares_confirmados_do_produto(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    repo.sincronizar_fila(s, T0)
    anuncio = criar_anuncio(s, "B01", produto=q, status=CONFIRMADO)
    criar_par(s, anuncio, p, status=IGNORADO, origem=OrigemCasamento.OUTRO_CONFIRMADO, revisado_em=T0)
    repo.reagendar(s, p.id, T0, T0, False)
    repo.reagendar(s, q.id, T0, T0, False)
    assert repo.ids_na_fila(s, T0 + timedelta(hours=1), 7) == {p.id}  # q casado e buscado há menos de 7 dias


def test_reagendar_guarda_o_indice_do_proximo_termo(s):
    p = criar_produto(s, "p")
    repo.sincronizar_fila(s, T0)
    assert s.get(FilaAmazon, p.id).indice_termo == 0
    repo.reagendar(s, p.id, T0, T0 + timedelta(hours=1), False, indice_termo=2)
    assert s.get(FilaAmazon, p.id).indice_termo == 2


def _esperar_espera_de_trava(engine, tarefa: threading.Thread) -> None:
    """Espera a outra transação parar numa trava (ou terminar)."""
    limite = time.monotonic() + 5
    while tarefa.is_alive() and time.monotonic() < limite:
        with engine.connect() as c:
            if c.scalar(text("SELECT count(*) FROM pg_locks WHERE NOT granted")):
                return
        time.sleep(0.01)


def test_busca_trava_os_anuncios_em_ordem_crescente_de_id_e_nao_causa_deadlock(engine):
    """Outra transação segura o anúncio de menor id e depois pede o de maior id (a ordem de
    `reavaliar_produto`); a busca traz os dois na ordem inversa. Travando em ordem crescente de id, a busca
    espera a outra terminar em vez de travar as duas. Grava de verdade e apaga no fim."""
    fabrica = sessionmaker(bind=engine, expire_on_commit=False)
    with fabrica() as s, s.begin():
        produto_id = criar_produto(s, "ordem-p").id
        menor, maior = criar_anuncio(s, "B0ORDEM001").id, criar_anuncio(s, "B0ORDEM002").id
    erros: list[DBAPIError] = []

    def buscar() -> None:
        try:
            with fabrica() as s, s.begin():
                repo.gravar_busca(s, [resultado("B0ORDEM002"), resultado("B0ORDEM001")], produto_id, T0, SP)
        except DBAPIError as erro:  # deadlock detectado pelo Postgres
            erros.append(erro)

    try:
        with fabrica() as s, s.begin():
            repo_casamento.travar_anuncio(s, menor)
            tarefa = threading.Thread(target=buscar)
            tarefa.start()
            _esperar_espera_de_trava(engine, tarefa)
            repo_casamento.travar_anuncio(s, maior)
        tarefa.join(timeout=30)
        assert erros == [] and not tarefa.is_alive()
        with fabrica() as s:
            assert all(repo_casamento.obter_par(s, a, produto_id).status is PENDENTE for a in (menor, maior))
    finally:
        with engine.begin() as c:
            for tabela in ("casamento", "preco_amazon", "preco_atual_amazon"):
                c.execute(text(f"DELETE FROM {tabela} WHERE anuncio_id IN (:a, :b)"), {"a": menor, "b": maior})
            c.execute(text("DELETE FROM anuncio_amazon WHERE id IN (:a, :b)"), {"a": menor, "b": maior})
            c.execute(text("DELETE FROM produto_liga WHERE id = :p"), {"p": produto_id})


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
        envio=Envio.AMAZON, agora=T0, conferido=False,
    )
    assert repo.oportunidade_aberta(s, anuncio.id).id == op.id
    assert (op.alertada_em, op.preco_alertado) == (T0, Decimal("700.00"))

    depois = T0 + timedelta(hours=1)
    repo.atualizar_oportunidade(
        s, op, preco_amazon=Decimal("650.00"), preco_liga=Decimal("1000.00"), desconto_pct=Decimal("35.00"),
        vendedor_id=amazon.id, envio=Envio.AMAZON, alertou=True, agora=depois, conferido=False,
    )
    assert (op.preco_amazon, op.alertada_em, op.preco_alertado) == (Decimal("650.00"), depois, Decimal("650.00"))

    repo.fechar_oportunidade(s, op, depois)
    assert repo.oportunidade_aberta(s, anuncio.id) is None


def test_conferido_e_obrigatorio_ao_abrir_e_ao_atualizar_oportunidade(s):
    produto = criar_produto(s)
    anuncio = criar_anuncio(s, "B0OBRIG001", produto=produto, status=StatusCasamento.CONFIRMADO, agora=T0)
    campos = {
        "preco_amazon": Decimal(1), "preco_liga": Decimal(2), "desconto_pct": Decimal(50), "vendedor_id": None,
        "envio": Envio.AMAZON,
    }
    with pytest.raises(TypeError, match="conferido"):
        repo.abrir_oportunidade(s, anuncio_id=anuncio.id, produto_id=produto.id, agora=T0, **campos)
    op = repo.abrir_oportunidade(s, anuncio_id=anuncio.id, produto_id=produto.id, agora=T0, conferido=True, **campos)
    assert op.alerta_conferido is True
    with pytest.raises(TypeError, match="conferido"):
        repo.atualizar_oportunidade(s, op, alertou=True, agora=T0, **campos)
    repo.atualizar_oportunidade(s, op, alertou=True, agora=T0, conferido=False, **campos)
    assert op.alerta_conferido is False


def test_fechar_oportunidades_sem_leitura_ha_24h(s):
    produto = criar_produto(s)
    velho = criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO, agora=T0)
    novo = criar_anuncio(s, "B02", produto=produto, status=StatusCasamento.CONFIRMADO, agora=T0 + timedelta(hours=20))
    for anuncio in (velho, novo):
        repo.abrir_oportunidade(
            s, anuncio_id=anuncio.id, produto_id=produto.id, preco_amazon=Decimal(1), preco_liga=Decimal(2),
            desconto_pct=Decimal(50), vendedor_id=None, envio=Envio.AMAZON, agora=T0, conferido=False,
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
        desconto_pct=Decimal(50), vendedor_id=None, envio=Envio.AMAZON, agora=T0, conferido=False,
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


def test_casar_link_manual_cria_confirmado_e_prioriza_na_fila(s):
    produto = criar_produto(s, "ff")
    repo.sincronizar_fila(s, T0)
    s.get(FilaAmazon, produto.id).proxima_busca_em = T0 + timedelta(hours=1)
    s.flush()

    agora = T0 + timedelta(minutes=5)
    anuncio = repo.casar_link_manual(s, produto.id, "B0MANUAL01", agora)
    assert (anuncio.asin, anuncio.titulo, anuncio.url) == (
        "B0MANUAL01",
        "Informado manualmente",
        "https://www.amazon.com.br/dp/B0MANUAL01",
    )
    assert (anuncio.produto_id, anuncio.status_casamento, anuncio.revisado_em) == (
        produto.id,
        StatusCasamento.CONFIRMADO,
        agora,
    )
    assert (anuncio.visto_primeiro_em, anuncio.visto_ultimo_em) == (agora, agora)
    assert s.get(FilaAmazon, produto.id).proxima_busca_em == agora


def test_link_manual_passa_na_frente_mesmo_com_a_fila_atrasada(s):
    atrasado = criar_produto(s, "gg")
    produto = criar_produto(s, "ff")
    repo.sincronizar_fila(s, T0)
    agora = T0 + timedelta(hours=5)
    s.get(FilaAmazon, atrasado.id).proxima_busca_em = agora - timedelta(hours=1)
    s.get(FilaAmazon, produto.id).proxima_busca_em = agora + timedelta(hours=1)
    s.flush()

    repo.casar_link_manual(s, produto.id, "B0MANUAL01", agora)
    assert repo.proximo_da_fila(s, agora).produto_id == produto.id


def test_casar_link_manual_de_asin_conhecido_troca_o_produto_e_fecha_oportunidade(s):
    antigo = criar_produto(s, "antigo")
    novo = criar_produto(s, "novo")
    anuncio = criar_anuncio(s, "B0CONHEC01", produto=antigo, status=StatusCasamento.IGNORADO)
    op = repo.abrir_oportunidade(
        s, anuncio_id=anuncio.id, produto_id=antigo.id, preco_amazon=Decimal(1), preco_liga=Decimal(2),
        desconto_pct=Decimal(50), vendedor_id=None, envio=Envio.AMAZON, agora=T0, conferido=False,
    )
    resultado = repo.casar_link_manual(s, novo.id, "B0CONHEC01", T0 + timedelta(hours=1))
    s.refresh(op)
    assert resultado.id == anuncio.id
    assert (resultado.produto_id, resultado.status_casamento) == (novo.id, StatusCasamento.CONFIRMADO)
    assert op.fechada_em == T0 + timedelta(hours=1)


def test_casar_link_manual_sem_linha_na_fila_nao_quebra(s):
    produto = criar_produto(s, "recem_ativado")
    anuncio = repo.casar_link_manual(s, produto.id, "B0SEMFILA1", T0)
    assert anuncio.status_casamento is StatusCasamento.CONFIRMADO
    repo.sincronizar_fila(s, T0 + timedelta(minutes=1))
    assert s.get(FilaAmazon, produto.id).proxima_busca_em == T0 + timedelta(minutes=1)


def test_atualizar_leitura(s):
    anuncio = criar_anuncio(s, "B0LEITURA1")
    repo.atualizar_leitura(s, anuncio.id, "Título real da página", "Collector Booster Box", T0 + timedelta(days=2))
    s.refresh(anuncio)
    assert (anuncio.titulo, anuncio.variacao, anuncio.visto_ultimo_em) == (
        "Título real da página",
        "Collector Booster Box",
        T0 + timedelta(days=2),
    )
    repo.atualizar_leitura(s, anuncio.id, "Título real da página", None, T0 + timedelta(days=3))
    s.refresh(anuncio)
    assert anuncio.variacao is None  # a página deixou de ter o seletor


@pytest.mark.parametrize(
    ("titulo", "variacao", "esperado"),
    [
        ("Final Fantasy, multicolorido", "Collector Booster Box", "Final Fantasy, multicolorido — Collector Booster Box"),
        ("Final Fantasy - Collector Booster Box", "collector booster box", "Final Fantasy - Collector Booster Box"),
        ("Final Fantasy", None, "Final Fantasy"),
    ],
)
def test_titulo_exibicao(titulo, variacao, esperado):
    assert AnuncioAmazon(titulo=titulo, variacao=variacao).titulo_exibicao == esperado


def test_busca_so_preenche_imagem_vazia_e_produto_troca(s):
    p = criar_produto(s, "p1")
    item = lambda img: ResultadoBusca("B0A", "Caixa", "https://www.amazon.com.br/dp/B0A", None, False, img)
    [a] = repo.gravar_busca(s, [item(None)], p.id, T0, SP).anuncios
    assert a.imagem_url is None
    [a] = repo.gravar_busca(s, [item("https://img/1.jpg")], p.id, T0, SP).anuncios
    assert a.imagem_url == "https://img/1.jpg"
    [a] = repo.gravar_busca(s, [item("https://img/2.jpg")], p.id, T0, SP).anuncios
    assert a.imagem_url == "https://img/1.jpg"  # a busca não troca: evita reavaliar o anúncio a cada ciclo
    repo.atualizar_leitura(s, a.id, "Caixa", None, T0, imagem_url="https://img/grande.jpg")
    repo.atualizar_leitura(s, a.id, "Caixa", None, T0)  # sem imagem: mantém
    s.refresh(a)
    assert a.imagem_url == "https://img/grande.jpg"


def test_origem_do_casamento_em_cada_decisao(s):
    produto = criar_produto(s, "p1")
    a = criar_anuncio(s, "B0ORIG0001", produto=produto)
    b = criar_anuncio(s, "B0ORIG0002", produto=produto)
    assert a.origem_casamento is None
    repo.confirmar_casamento(s, a.id, produto.id, T0)
    assert a.origem_casamento is OrigemCasamento.MANUAL
    repo.ignorar_anuncio(s, b.id, T0, OrigemCasamento.SUGERIDO_IA)
    assert b.origem_casamento is OrigemCasamento.SUGERIDO_IA
    repo.confirmar_casamento(s, b.id, produto.id, T0, OrigemCasamento.AUTOMATICO_IA)
    assert b.origem_casamento is OrigemCasamento.AUTOMATICO_IA
    repo.desfazer_casamento(s, b.id, T0)
    assert b.origem_casamento is None


def test_link_manual_tem_origem_manual(s):
    produto = criar_produto(s, "p1")
    novo = repo.casar_link_manual(s, produto.id, "B0ORIG0003", T0)
    existente = criar_anuncio(s, "B0ORIG0004", produto=produto)
    repo.ignorar_anuncio(s, existente.id, T0, OrigemCasamento.SUGERIDO_IA)
    repo.casar_link_manual(s, produto.id, "B0ORIG0004", T0)
    assert novo.origem_casamento is OrigemCasamento.MANUAL
    assert existente.origem_casamento is OrigemCasamento.MANUAL
