from datetime import timedelta
from decimal import Decimal

from fakes import T0, criar_produto
from sqlalchemy import func, select

from tcg_sniper.coletor_liga.modelos import ItemListagem, Resumo
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    COLETOR_AMAZON_BUSCA,
    Coleta,
    EstadoColetorTipo,
    PrecoAtualLiga,
    PrecoListagem,
    ProdutoLiga,
    ResumoPreco,
    StatusColeta,
    TipoColeta,
)


def item(liga_id, nome=None, preco="10.00", tipo=None):
    return ItemListagem(
        liga_id=liga_id,
        nome=nome or f"Caixa {liga_id}",
        url=f"https://liga.test/{liga_id}",
        preco_a_partir=None if preco is None else Decimal(preco),
        tipo=tipo,
    )


def produto(s, liga_id):
    return s.scalar(select(ProdutoLiga).where(ProdutoLiga.liga_id == liga_id))


def test_status_final():
    assert repo.status_final(5, 0, 50) is StatusColeta.OK
    assert repo.status_final(0, 0, 50) is StatusColeta.OK
    assert repo.status_final(3, 2, 50) is StatusColeta.PARCIAL
    assert repo.status_final(2, 2, 50) is StatusColeta.PARCIAL
    assert repo.status_final(1, 2, 50) is StatusColeta.FALHA


def test_upsert_catalogo_conta_novos_e_preserva_ativo(s):
    assert repo.upsert_catalogo(s, [item("a"), item("b")], T0) == 2
    produto(s, "a").ativo = True
    s.flush()

    depois = T0 + timedelta(days=7)
    assert repo.upsert_catalogo(s, [item("a", nome="Caixa A nova"), item("c")], depois) == 1

    s.expire_all()
    produto_a = produto(s, "a")
    assert produto_a.nome == "Caixa A nova"
    assert produto_a.ativo is True
    assert produto_a.visto_primeiro_em == T0
    assert produto_a.visto_ultimo_em == depois
    assert produto(s, "c").ativo is False


def test_upsert_catalogo_item_repetido_na_mesma_lista(s):
    assert repo.upsert_catalogo(s, [item("a"), item("a")], T0) == 1
    assert s.scalar(select(func.count()).select_from(ProdutoLiga)) == 1


def test_upsert_catalogo_preenche_tipo_uma_vez(s):
    repo.upsert_catalogo(s, [item("a", tipo=None)], T0)
    repo.upsert_catalogo(s, [item("a", tipo="Caixas de Boosters")], T0 + timedelta(days=1))
    repo.upsert_catalogo(s, [item("a", tipo="Bundles")], T0 + timedelta(days=2))
    s.expire_all()
    assert produto(s, "a").tipo == "Caixas de Boosters"


def test_upsert_catalogo_lista_vazia(s):
    assert repo.upsert_catalogo(s, [], T0) == 0


def test_gravar_listagem_grava_catalogo_historico_e_atual(s):
    c1 = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0)
    assert repo.gravar_listagem(s, c1.id, [item("a", preco="525.43"), item("b", preco=None)], T0) == 2

    c2 = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0 + timedelta(days=1))
    assert repo.gravar_listagem(s, c2.id, [item("a", preco="499.90")], T0 + timedelta(days=1)) == 0

    id_a, id_b = produto(s, "a").id, produto(s, "b").id
    historico = s.execute(
        select(PrecoListagem.produto_id, PrecoListagem.coleta_id, PrecoListagem.preco_a_partir).order_by(
            PrecoListagem.coleta_id, PrecoListagem.produto_id
        )
    ).all()
    assert historico == [(id_a, c1.id, Decimal("525.43")), (id_b, c1.id, None), (id_a, c2.id, Decimal("499.90"))]

    atual_a = s.get(PrecoAtualLiga, id_a, populate_existing=True)
    assert (atual_a.preco_a_partir, atual_a.listagem_coleta_id, atual_a.listagem_em) == (
        Decimal("499.90"),
        c2.id,
        T0 + timedelta(days=1),
    )
    assert (atual_a.preco_min, atual_a.num_lojas, atual_a.resumo_coleta_id) == (None, None, None)
    atual_b = s.get(PrecoAtualLiga, id_b, populate_existing=True)
    assert (atual_b.preco_a_partir, atual_b.listagem_coleta_id) == (None, c1.id)


def test_gravar_listagem_mesmo_produto_em_duas_categorias_na_mesma_coleta(s):
    c = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0)
    assert repo.gravar_listagem(s, c.id, [item("a", preco="10.00"), item("b")], T0) == 2
    assert repo.gravar_listagem(s, c.id, [item("a", preco="12.00"), item("c")], T0 + timedelta(minutes=1)) == 1

    id_a = produto(s, "a").id
    assert s.scalar(select(func.count()).select_from(PrecoListagem)) == 3
    assert s.scalar(select(PrecoListagem.preco_a_partir).where(PrecoListagem.produto_id == id_a)) == Decimal("10.00")
    assert s.get(PrecoAtualLiga, id_a, populate_existing=True).preco_a_partir == Decimal("10.00")


def test_gravar_listagem_item_repetido_na_mesma_lista(s):
    c = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0)
    assert repo.gravar_listagem(s, c.id, [item("a", preco="10.00"), item("a", preco="11.00")], T0) == 1
    assert s.scalars(select(PrecoListagem.preco_a_partir)).all() == [Decimal("10.00")]


def test_gravar_listagem_vazia(s):
    c = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0)
    assert repo.gravar_listagem(s, c.id, [], T0) == 0


def test_listagem_e_resumo_nao_se_sobrescrevem(s):
    p = criar_produto(s, "a")
    cp = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0)
    repo.gravar_precos_produto(s, cp.id, p.id, Resumo(Decimal("850.00"), Decimal("874.95"), Decimal("899.90"), 2), T0)
    cl = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0 + timedelta(hours=1))
    repo.gravar_listagem(s, cl.id, [item("a", preco="799.00")], T0 + timedelta(hours=1))
    cp2 = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0 + timedelta(hours=2))
    repo.gravar_precos_produto(s, cp2.id, p.id, Resumo(None, None, None, 0), T0 + timedelta(hours=2))

    atual = s.get(PrecoAtualLiga, p.id, populate_existing=True)
    assert (atual.preco_a_partir, atual.listagem_coleta_id, atual.listagem_em) == (
        Decimal("799.00"),
        cl.id,
        T0 + timedelta(hours=1),
    )
    assert (atual.preco_min, atual.num_lojas, atual.resumo_coleta_id, atual.resumo_em) == (
        None,
        0,
        cp2.id,
        T0 + timedelta(hours=2),
    )


def test_gravar_precos_produto_grava_historico_e_atualiza_atual(s):
    p = criar_produto(s)
    c1 = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0)
    resumo1 = Resumo(Decimal("850.00"), Decimal("874.95"), Decimal("899.90"), 2)
    repo.gravar_precos_produto(s, c1.id, p.id, resumo1, T0)

    c2 = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0 + timedelta(days=1))
    resumo2 = Resumo(Decimal("799.00"), Decimal("799.00"), Decimal("799.00"), 1)
    repo.gravar_precos_produto(s, c2.id, p.id, resumo2, T0 + timedelta(days=1))

    historico = s.scalars(select(ResumoPreco).order_by(ResumoPreco.coletado_em)).all()
    assert [(r.coleta_id, r.preco_min, r.num_lojas) for r in historico] == [
        (c1.id, Decimal("850.00"), 2),
        (c2.id, Decimal("799.00"), 1),
    ]
    atual = s.scalars(select(PrecoAtualLiga)).one()
    assert atual.resumo_coleta_id == c2.id
    assert (atual.preco_min, atual.preco_medio, atual.preco_max, atual.num_lojas) == (
        Decimal("799.00"),
        Decimal("799.00"),
        Decimal("799.00"),
        1,
    )
    assert atual.resumo_em == T0 + timedelta(days=1)
    assert (atual.preco_a_partir, atual.listagem_coleta_id) == (None, None)


def test_gravar_precos_produto_sem_precos(s):
    p = criar_produto(s)
    c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0)
    repo.gravar_precos_produto(s, c.id, p.id, Resumo(None, None, None, 0), T0)
    atual = s.scalars(select(PrecoAtualLiga)).one()
    assert (atual.preco_min, atual.preco_medio, atual.preco_max, atual.num_lojas) == (None, None, None, 0)


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


def test_marcar_interrompidas_so_dos_tipos_pedidos(s):
    rodando = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0)
    pronta = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0)
    repo.finalizar_coleta(s, pronta.id, StatusColeta.OK, 1, 0, T0)
    ciclo_amazon = repo.iniciar_coleta(s, TipoColeta.AMAZON, T0)

    assert repo.marcar_interrompidas(s, T0 + timedelta(hours=1), (TipoColeta.LISTAGEM, TipoColeta.PRODUTOS)) == 1
    s.expire_all()
    assert s.get(Coleta, rodando.id).status is StatusColeta.FALHA
    assert s.get(Coleta, rodando.id).erro == "interrompida"
    assert s.get(Coleta, pronta.id).status is StatusColeta.OK
    assert s.get(Coleta, ciclo_amazon.id).status is StatusColeta.RODANDO


def test_estado_por_coletor_e_independente(s):
    repo.pausar_por_desafio(s, "desafio em /x", T0)
    assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.ATIVO

    repo.pausar(s, "erros seguidos", T0, COLETOR_AMAZON)
    amazon = repo.obter_estado(s, coletor=COLETOR_AMAZON)
    assert (amazon.estado, amazon.motivo) == (EstadoColetorTipo.PAUSADO, "erros seguidos")
    assert repo.obter_estado(s).estado is EstadoColetorTipo.PAUSADO_DESAFIO

    repo.retomar(s, T0, COLETOR_AMAZON)
    assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.ATIVO
    assert repo.obter_estado(s).estado is EstadoColetorTipo.PAUSADO_DESAFIO


def test_ultima_coleta_sucesso_ignora_falha_e_pausada(s):
    assert repo.ultima_coleta_sucesso(s, TipoColeta.PRODUTOS) is None
    for horas, status in [
        (0, StatusColeta.OK),
        (1, StatusColeta.PARCIAL),
        (2, StatusColeta.FALHA),
        (3, StatusColeta.PAUSADA_DESAFIO),
    ]:
        c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0 + timedelta(hours=horas))
        repo.finalizar_coleta(s, c.id, status, 0, 0, T0)
    assert repo.ultima_coleta_sucesso(s, TipoColeta.PRODUTOS) == T0 + timedelta(hours=1)
    assert repo.ultima_coleta_sucesso(s, TipoColeta.LISTAGEM) is None


def test_coleta_iniciada_desde(s):
    repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0)
    assert repo.coleta_iniciada_desde(s, TipoColeta.LISTAGEM, T0 - timedelta(hours=1)) is True
    assert repo.coleta_iniciada_desde(s, TipoColeta.LISTAGEM, T0 + timedelta(hours=1)) is False
    assert repo.coleta_iniciada_desde(s, TipoColeta.PRODUTOS, T0 - timedelta(hours=1)) is False


def test_produtos_ativos(s):
    criar_produto(s, "a", ativo=True)
    criar_produto(s, "b", ativo=False)
    assert [p.liga_id for p in repo.produtos_ativos(s)] == ["a"]


def test_estado_da_busca_da_amazon_e_a_linha_6_e_independente_do_monitor(s):
    busca = repo.obter_estado(s, T0, COLETOR_AMAZON_BUSCA)
    assert (busca.id, busca.coletor, busca.estado) == (6, "amazon_busca", EstadoColetorTipo.ATIVO)
    repo.pausar_por_desafio(s, "desafio em /s?k=x", T0, COLETOR_AMAZON_BUSCA)
    assert repo.obter_estado(s, T0, COLETOR_AMAZON_BUSCA).estado is EstadoColetorTipo.PAUSADO_DESAFIO
    assert repo.obter_estado(s, T0, COLETOR_AMAZON).estado is EstadoColetorTipo.ATIVO
    repo.retomar(s, T0, COLETOR_AMAZON_BUSCA)
    assert repo.obter_estado(s, T0, COLETOR_AMAZON_BUSCA).estado is EstadoColetorTipo.ATIVO
