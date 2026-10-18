from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fakes import criar_anuncio, criar_produto
from sqlalchemy import func, select

from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db import retencao
from tcg_sniper.db.models import (
    AvaliacaoIA,
    ChamadaIA,
    Coleta,
    ConferenciaCheckout,
    Envio,
    OrigemPreco,
    PrecoAmazon,
    PrecoAtualLiga,
    PrecoListagem,
    ResumoPreco,
    SituacaoCheckout,
    StatusColeta,
    TipoColeta,
)

AGORA = datetime(2026, 10, 18, 7, 0, tzinfo=UTC)


def _chamada(s, em):
    return repo_ia.registrar_chamada(
        s, em=em, finalidade="casamento", modelo="gpt-5", tokens_entrada=1, tokens_saida=1,
        custo_usd=Decimal("0.001"), ok=True, erro=None,
    )


def _conferencia(s, anuncio, em, item_removido=True):
    return repo_amz.registrar_conferencia(
        s, em=em, anuncio_id=anuncio.id, vendedor_nome="Loja", preco_anunciado=Decimal(100), itens=None,
        frete=None, impostos=None, total=None, situacao=SituacaoCheckout.OK, motivo=None, item_removido=item_removido,
    )


def _coleta(s, tipo, em, status=StatusColeta.OK):
    coleta = repo.iniciar_coleta(s, tipo, em)
    if status is not StatusColeta.RODANDO:
        repo.finalizar_coleta(s, coleta.id, status, 0, 0, em + timedelta(minutes=5))
    return coleta


def _ids(s, modelo):
    return set(s.scalars(select(modelo.id)))


def test_chamada_ia_apaga_mais_de_90_dias_e_solta_a_avaliacao(s):
    produto = criar_produto(s)
    anuncio = criar_anuncio(s, produto=produto)
    velha = _chamada(s, AGORA - timedelta(days=91))
    limite = _chamada(s, AGORA - timedelta(days=89))
    av = repo_ia.gravar_avaliacao(
        s, anuncio_id=anuncio.id, produto_id=produto.id, mesmo_produto=True, confianca=95, motivo="igual",
        modelo="gpt-5", assinatura="x", sem_imagem=False, chamada_id=velha.id, agora=AGORA - timedelta(days=91),
    )

    apagados = retencao.limpar_historico(s, AGORA)

    assert apagados["chamada_ia"] == 1
    assert _ids(s, ChamadaIA) == {limite.id}
    avaliacao = s.get(AvaliacaoIA, av.id, populate_existing=True)
    assert avaliacao is not None and avaliacao.chamada_id is None and avaliacao.motivo == "igual"


def test_chamada_ia_em_lotes(s, monkeypatch):
    monkeypatch.setattr(retencao, "LOTE", 2)
    for _ in range(5):
        _chamada(s, AGORA - timedelta(days=100))
    assert retencao.limpar_historico(s, AGORA)["chamada_ia"] == 5
    assert s.scalar(select(func.count()).select_from(ChamadaIA)) == 0


def test_conferencia_apaga_mais_de_180_dias_menos_item_que_pode_estar_no_carrinho(s):
    anuncio = criar_anuncio(s)
    velha = _conferencia(s, anuncio, AGORA - timedelta(days=181))
    velha_no_carrinho = _conferencia(s, anuncio, AGORA - timedelta(days=181), item_removido=False)
    velha_a_mao = _conferencia(s, anuncio, AGORA - timedelta(days=200), item_removido=False)
    velha_a_mao.conferir_a_mao_em = AGORA - timedelta(days=199)
    recente = _conferencia(s, anuncio, AGORA - timedelta(days=179))
    s.flush()

    apagados = retencao.limpar_historico(s, AGORA)

    assert apagados["conferencia_checkout"] == 1
    assert velha.id not in _ids(s, ConferenciaCheckout)
    assert _ids(s, ConferenciaCheckout) == {velha_no_carrinho.id, velha_a_mao.id, recente.id}


def test_coleta_apaga_so_as_velhas_sem_nenhum_preco(s):
    produto = criar_produto(s)
    outro = criar_produto(s, liga_id="p2")
    velho = AGORA - timedelta(days=181)
    com_resumo = _coleta(s, TipoColeta.PRODUTOS, velho)
    s.add(ResumoPreco(produto_id=produto.id, coleta_id=com_resumo.id, num_lojas=3, coletado_em=velho))
    com_listagem = _coleta(s, TipoColeta.LISTAGEM, velho)
    s.add(PrecoListagem(produto_id=produto.id, coleta_id=com_listagem.id, preco_a_partir=Decimal(10), coletado_em=velho))
    so_no_atual = _coleta(s, TipoColeta.LISTAGEM, velho)
    resumo_no_atual = _coleta(s, TipoColeta.PRODUTOS, velho)
    s.add(PrecoAtualLiga(produto_id=outro.id, listagem_coleta_id=so_no_atual.id, resumo_coleta_id=resumo_no_atual.id))
    vazia = _coleta(s, TipoColeta.LISTAGEM, velho, StatusColeta.FALHA)
    ciclo_amazon = _coleta(s, TipoColeta.AMAZON, velho)
    rodando = _coleta(s, TipoColeta.PRODUTOS, velho, StatusColeta.RODANDO)
    recente = _coleta(s, TipoColeta.LISTAGEM, AGORA - timedelta(days=179), StatusColeta.FALHA)
    s.flush()

    apagados = retencao.limpar_historico(s, AGORA)

    assert apagados["coleta"] == 2
    assert _ids(s, Coleta) == {com_resumo.id, com_listagem.id, so_no_atual.id, resumo_no_atual.id, rodando.id, recente.id}
    assert vazia.id not in _ids(s, Coleta) and ciclo_amazon.id not in _ids(s, Coleta)


def test_precos_nunca_sao_apagados(s):
    produto = criar_produto(s)
    anuncio = criar_anuncio(s, produto=produto)
    muito_velho = AGORA - timedelta(days=3000)
    coleta = _coleta(s, TipoColeta.LISTAGEM, muito_velho)
    s.add(PrecoListagem(produto_id=produto.id, coleta_id=coleta.id, preco_a_partir=Decimal(10), coletado_em=muito_velho))
    s.add(ResumoPreco(produto_id=produto.id, coleta_id=coleta.id, num_lojas=1, coletado_em=muito_velho))
    s.add(PrecoAmazon(anuncio_id=anuncio.id, coletado_em=muito_velho, preco=Decimal(9), origem=OrigemPreco.BUSCA, envio=Envio.AMAZON))
    s.flush()

    retencao.limpar_historico(s, AGORA)

    for modelo in (PrecoListagem, ResumoPreco, PrecoAmazon):
        assert s.scalar(select(func.count()).select_from(modelo)) == 1, modelo.__tablename__
    assert coleta.id in _ids(s, Coleta)


def test_nada_a_apagar_devolve_zeros(s):
    assert retencao.limpar_historico(s, AGORA) == {"chamada_ia": 0, "conferencia_checkout": 0, "coleta": 0}
