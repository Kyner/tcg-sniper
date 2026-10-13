from datetime import timedelta
from decimal import Decimal

from fakes import T0, criar_produto
from sqlalchemy import func, select

from tcg_sniper.coletor_liga.modelos import ItemCatalogo, Oferta
from tcg_sniper.coletor_liga.resumo import calcular_resumo
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import (
    Coleta,
    EstadoColetorTipo,
    OfertaLiga,
    PrecoAtualLiga,
    ProdutoLiga,
    ResumoPreco,
    StatusColeta,
    TipoColeta,
)


def item(liga_id, nome=None, edicao=None):
    return ItemCatalogo(
        liga_id=liga_id, nome=nome or f"Caixa {liga_id}", url=f"https://liga.test/{liga_id}", edicao=edicao
    )


def test_status_final():
    assert repo.status_final(5, 0, 50) is StatusColeta.OK
    assert repo.status_final(0, 0, 50) is StatusColeta.OK
    assert repo.status_final(3, 2, 50) is StatusColeta.PARCIAL
    assert repo.status_final(2, 2, 50) is StatusColeta.PARCIAL
    assert repo.status_final(1, 2, 50) is StatusColeta.FALHA


def test_upsert_catalogo_conta_novos_e_preserva_ativo(s):
    assert repo.upsert_catalogo(s, [item("a"), item("b")], T0) == 2
    produto_a = s.scalar(select(ProdutoLiga).where(ProdutoLiga.liga_id == "a"))
    produto_a.ativo = True
    s.flush()

    depois = T0 + timedelta(days=7)
    assert repo.upsert_catalogo(s, [item("a", nome="Caixa A nova"), item("c")], depois) == 1

    s.expire_all()
    produto_a = s.scalar(select(ProdutoLiga).where(ProdutoLiga.liga_id == "a"))
    assert produto_a.nome == "Caixa A nova"
    assert produto_a.ativo is True
    assert produto_a.visto_primeiro_em == T0
    assert produto_a.visto_ultimo_em == depois


def test_upsert_catalogo_item_repetido_na_mesma_lista(s):
    assert repo.upsert_catalogo(s, [item("a"), item("a")], T0) == 1
    assert s.scalar(select(func.count()).select_from(ProdutoLiga)) == 1


def test_upsert_catalogo_nao_apaga_edicao_com_none(s):
    repo.upsert_catalogo(s, [item("a", edicao="Duskmourn")], T0)
    repo.upsert_catalogo(s, [item("a", edicao=None)], T0 + timedelta(days=1))
    s.expire_all()
    assert s.scalar(select(ProdutoLiga.edicao).where(ProdutoLiga.liga_id == "a")) == "Duskmourn"


def test_upsert_catalogo_lista_vazia(s):
    assert repo.upsert_catalogo(s, [], T0) == 0


def test_gravar_precos_produto_grava_historico_e_atualiza_atual(s):
    produto = criar_produto(s)
    ofertas = [
        Oferta("Loja A", Decimal("899.90"), 2),
        Oferta("Loja B", Decimal("850.00"), 0),
    ]
    c1 = repo.iniciar_coleta(s, TipoColeta.PRECOS, T0)
    repo.gravar_precos_produto(s, c1.id, produto.id, ofertas, calcular_resumo(ofertas), T0)

    novas = [Oferta("Loja C", Decimal("799.00"), 1)]
    c2 = repo.iniciar_coleta(s, TipoColeta.PRECOS, T0 + timedelta(days=1))
    repo.gravar_precos_produto(s, c2.id, produto.id, novas, calcular_resumo(novas), T0 + timedelta(days=1))

    assert s.scalar(select(func.count()).select_from(OfertaLiga)) == 3
    assert s.scalar(select(func.count()).select_from(ResumoPreco)) == 2
    atual = s.scalars(select(PrecoAtualLiga)).one()
    assert atual.coleta_id == c2.id
    assert atual.menor_preco_com_estoque == Decimal("799.00")
    assert atual.num_vendedores_com_estoque == 1


def test_estado_pausa_retoma_e_solicitacao(s):
    assert repo.obter_estado(s, T0).estado is EstadoColetorTipo.ATIVO

    repo.solicitar_execucao(s, T0)
    repo.pausar_por_desafio(s, "desafio em /x", T0)
    estado = repo.obter_estado(s)
    assert estado.estado is EstadoColetorTipo.PAUSADO_DESAFIO
    assert estado.motivo == "desafio em /x"
    assert repo.consumir_solicitacao(s, T0) is False

    repo.retomar(s, T0)
    assert repo.obter_estado(s).estado is EstadoColetorTipo.ATIVO
    assert repo.consumir_solicitacao(s, T0) is True
    assert repo.consumir_solicitacao(s, T0) is False


def test_marcar_interrompidas(s):
    rodando = repo.iniciar_coleta(s, TipoColeta.PRECOS, T0)
    pronta = repo.iniciar_coleta(s, TipoColeta.PRECOS, T0)
    repo.finalizar_coleta(s, pronta.id, StatusColeta.OK, 1, 0, T0)

    assert repo.marcar_interrompidas(s, T0 + timedelta(hours=1)) == 1
    s.expire_all()
    assert s.get(Coleta, rodando.id).status is StatusColeta.FALHA
    assert s.get(Coleta, rodando.id).erro == "interrompida"
    assert s.get(Coleta, pronta.id).status is StatusColeta.OK


def test_ultima_coleta_sucesso_ignora_falha_e_pausada(s):
    assert repo.ultima_coleta_sucesso(s, TipoColeta.PRECOS) is None
    for horas, status in [(0, StatusColeta.OK), (1, StatusColeta.PARCIAL), (2, StatusColeta.FALHA), (3, StatusColeta.PAUSADA_DESAFIO)]:
        c = repo.iniciar_coleta(s, TipoColeta.PRECOS, T0 + timedelta(hours=horas))
        repo.finalizar_coleta(s, c.id, status, 0, 0, T0)
    assert repo.ultima_coleta_sucesso(s, TipoColeta.PRECOS) == T0 + timedelta(hours=1)
    assert repo.ultima_coleta_sucesso(s, TipoColeta.CATALOGO) is None


def test_coleta_iniciada_desde(s):
    repo.iniciar_coleta(s, TipoColeta.PRECOS, T0)
    assert repo.coleta_iniciada_desde(s, TipoColeta.PRECOS, T0 - timedelta(hours=1)) is True
    assert repo.coleta_iniciada_desde(s, TipoColeta.PRECOS, T0 + timedelta(hours=1)) is False
    assert repo.coleta_iniciada_desde(s, TipoColeta.CATALOGO, T0 - timedelta(hours=1)) is False


def test_produtos_ativos(s):
    criar_produto(s, "a", ativo=True)
    criar_produto(s, "b", ativo=False)
    assert [p.liga_id for p in repo.produtos_ativos(s)] == ["a"]
