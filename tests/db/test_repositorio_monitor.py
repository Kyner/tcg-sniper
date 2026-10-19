from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fakes import T0, criar_anuncio, criar_par, criar_preco_liga, criar_produto, oferta_lista

from tcg_sniper.db import repositorio_amazon as repo
from tcg_sniper.db.models import (
    Envio,
    OfertaAmazon,
    OrigemCasamento,
    OrigemPreco,
    PrecoAtualAmazon,
    SituacaoCheckout,
    StatusCasamento,
)

SP = ZoneInfo("America/Sao_Paulo")


def confirmado(s, asin, liga="1000.00", listagem_em=T0, ativo=True):
    produto = criar_produto(s, f"p-{asin}", ativo=ativo)
    criar_preco_liga(s, produto, liga, listagem_em=listagem_em)
    return criar_anuncio(s, asin, produto=produto, status=StatusCasamento.CONFIRMADO)


def ler(s, anuncio, quando, *ofertas):
    """Uma leitura do monitor: as ofertas (a primeira é a melhor, todas elegíveis) e o preço atual."""
    repo.gravar_ofertas(s, anuncio.id, quando, [repo.OfertaAvaliada(o, None, True, i == 0) for i, o in enumerate(ofertas)])
    melhor = ofertas[0] if ofertas else None
    repo.registrar_preco(
        s, anuncio.id, melhor.preco if melhor else None, OrigemPreco.OFERTAS, None,
        melhor.envio if melhor else Envio.DESCONHECIDO, quando, SP,
    )


def conferencia(s, anuncio, quando, situacao=SituacaoCheckout.OK, vendedor="Shazaar", preco="275.91", total="285.99", removido=True):
    tem_total = total is not None
    return repo.registrar_conferencia(
        s, em=quando, anuncio_id=anuncio.id, vendedor_nome=vendedor, preco_anunciado=Decimal(preco),
        itens=Decimal("237.73") if tem_total else None, frete=Decimal("0.00") if tem_total else None,
        impostos=Decimal("48.26") if tem_total else None, total=Decimal(total) if tem_total else None,
        situacao=situacao, motivo=None if situacao is SituacaoCheckout.OK else "motivo", item_removido=removido,
    )


def test_gravar_ofertas_e_ler_so_a_ultima_leitura(s):
    a = confirmado(s, "B0MON00001")
    ler(s, a, T0 - timedelta(minutes=20), oferta_lista("300.00"))
    ler(
        s, a, T0,
        oferta_lista("275.91"),
        oferta_lista("314.11", vendedor="Amazon.com.br", seller_id="amazon", envio=Envio.AMAZON, posicao=0,
                     importada=True, origem_envio="Estados Unidos", prime=True),
    )
    ultimas = repo.ofertas_da_ultima_leitura(s, [a.id])[a.id]
    assert [(o.vendedor_nome, o.preco, o.melhor) for o in ultimas] == [
        ("Shazaar", Decimal("275.91"), True), ("Amazon.com.br", Decimal("314.11"), False),
    ]
    assert ultimas[1].importada and ultimas[1].prime and ultimas[1].origem_envio == "Estados Unidos"
    assert repo.ofertas_da_ultima_leitura(s, []) == {}


def test_limpar_ofertas_com_mais_de_30_dias(s):
    a = confirmado(s, "B0MON00001")
    ler(s, a, T0 - timedelta(days=31), oferta_lista())
    ler(s, a, T0, oferta_lista())
    assert repo.limpar_ofertas_antigas(s, T0) == 1
    assert s.query(OfertaAmazon).count() == 1


def test_proximo_do_monitor_nunca_lido_primeiro_depois_o_mais_antigo(s):
    nunca = confirmado(s, "B0MON00001")
    velho = confirmado(s, "B0MON00002")
    novo = confirmado(s, "B0MON00003")
    confirmado(s, "B0MON00004", ativo=False)  # produto desativado na Liga: fora do monitor
    criar_anuncio(s, "B0MON00005", produto=criar_produto(s, "pendente"))  # pendente: fora
    repo.registrar_preco(s, nunca.id, Decimal("10.00"), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, T0, SP)
    ler(s, velho, T0 - timedelta(minutes=40), oferta_lista())
    ler(s, novo, T0 - timedelta(minutes=5), oferta_lista())
    assert repo.proximo_do_monitor(s, T0, 15) == (nunca.id, "B0MON00001")
    assert repo.proximo_do_monitor(s, T0, 15, excluir={nunca.id}) == (velho.id, "B0MON00002")
    assert repo.proximo_do_monitor(s, T0, 15, excluir={nunca.id, velho.id}) is None


def test_situacao_do_monitor(s):
    confirmado(s, "B0MON00001")
    velho = confirmado(s, "B0MON00002")
    novo = confirmado(s, "B0MON00003")
    ler(s, velho, T0 - timedelta(minutes=40), oferta_lista())
    ler(s, novo, T0 - timedelta(minutes=5), oferta_lista())
    assert repo.situacao_monitor(s, T0, 15) == repo.SituacaoMonitor(
        confirmados=3, nunca_lidos=1, vencidos=2, mais_antiga=T0 - timedelta(minutes=40), ultima=T0 - timedelta(minutes=5)
    )


def test_busca_nao_sobrescreve_o_preco_lido_nas_ofertas(s):
    a = confirmado(s, "B0MON00001")
    ler(s, a, T0, oferta_lista("700.00", vendedor="Amazon.com.br", seller_id="amazon", envio=Envio.AMAZON, posicao=0))
    gravou = repo.registrar_preco(
        s, a.id, Decimal("650.00"), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, T0 + timedelta(minutes=1), SP
    )
    atual = s.get(PrecoAtualAmazon, a.id, populate_existing=True)
    assert gravou  # vai para o histórico
    assert (atual.preco, atual.origem, atual.envio) == (Decimal("700.00"), OrigemPreco.OFERTAS, Envio.AMAZON)


def test_ofertas_gravam_vendedor_e_envio_no_preco_atual(s):
    a = confirmado(s, "B0MON00001")
    amazon = repo.vendedor_da_amazon(s)
    repo.registrar_preco(s, a.id, Decimal("700.00"), OrigemPreco.OFERTAS, amazon.id, Envio.AMAZON, T0, SP)
    assert repo.registrar_preco(s, a.id, Decimal("700.00"), OrigemPreco.OFERTAS, None, Envio.FBA, T0 + timedelta(minutes=15), SP)
    atual = s.get(PrecoAtualAmazon, a.id, populate_existing=True)
    assert (atual.vendedor_id, atual.envio, atual.origem) == (None, Envio.FBA, OrigemPreco.OFERTAS)


def test_marcar_visto(s):
    a = confirmado(s, "B0MON00001")
    repo.marcar_visto(s, a.id, T0 + timedelta(hours=3))
    s.refresh(a)
    assert a.visto_ultimo_em == T0 + timedelta(hours=3)


def test_descoberta_pula_casados_ate_a_busca_semanal(s):
    livre = criar_produto(s, "livre")
    casado = criar_produto(s, "casado")
    velho = criar_produto(s, "velho")
    nunca_buscado = criar_produto(s, "nunca")
    for produto, asin in ((casado, "B0CAS00001"), (velho, "B0CAS00002"), (nunca_buscado, "B0CAS00003")):
        criar_anuncio(s, asin, produto=produto, status=StatusCasamento.CONFIRMADO)
    repo.sincronizar_fila(s, T0 - timedelta(days=10))
    repo.reagendar(s, livre.id, T0 - timedelta(hours=2), T0 - timedelta(hours=1), False)
    repo.reagendar(s, casado.id, T0 - timedelta(days=2), T0 - timedelta(days=1), False)
    repo.reagendar(s, velho.id, T0 - timedelta(days=7), T0 - timedelta(days=6), False)
    assert repo.ids_na_fila(s, T0, 7) == {livre.id, velho.id, nunca_buscado.id}
    assert repo.ids_na_fila(s) == {livre.id, casado.id, velho.id, nunca_buscado.id}
    assert repo.proximo_da_fila(s, T0, 7).produto_id == nunca_buscado.id  # vencido desde a entrada na fila
    repo.reagendar(s, nunca_buscado.id, T0, T0 + timedelta(days=7), False)
    assert repo.proximo_da_fila(s, T0, 7).produto_id == velho.id
    repo.reagendar(s, velho.id, T0, T0 + timedelta(days=7), False)
    assert repo.proximo_da_fila(s, T0, 7).produto_id == livre.id
    assert repo.proximo_da_fila(s, T0).produto_id == casado.id  # sem o filtro, como antes


def test_conferencia_valida_pela_mesma_oferta_dentro_da_validade(s):
    a = confirmado(s, "B0MON00001")
    ok = conferencia(s, a, T0 - timedelta(hours=5))
    assert repo.conferencia_valida(s, a.id, "Shazaar", Decimal("275.91"), T0, 6).id == ok.id
    assert repo.conferencia_valida(s, a.id, "Outra loja", Decimal("275.91"), T0, 6) is None
    assert repo.conferencia_valida(s, a.id, "Shazaar", Decimal("270.00"), T0, 6) is None
    assert repo.conferencia_valida(s, a.id, "Shazaar", Decimal("275.91"), T0 + timedelta(hours=2), 6) is None
    conferencia(s, a, T0, SituacaoCheckout.FALHA, total=None)
    assert repo.conferencia_valida(s, a.id, "Shazaar", Decimal("275.91"), T0, 6).id == ok.id
    assert repo.ultima_conferencia(s, a.id).situacao is SituacaoCheckout.FALHA
    assert repo.ultima_conferencia(s).situacao is SituacaoCheckout.FALHA


def test_candidatas_ao_checkout(s):
    cfg = repo.obter_config(s)  # desconto mínimo 25%, margem 5 pontos: candidata a partir de 20%
    boa = confirmado(s, "B0CAN00001")
    no_limite = confirmado(s, "B0CAN00002")
    cara = confirmado(s, "B0CAN00003")
    inelegivel = confirmado(s, "B0CAN00004")
    ja_conferida = confirmado(s, "B0CAN00005")
    liga_velha = confirmado(s, "B0CAN00006", listagem_em=T0 - timedelta(hours=49))
    ler(s, boa, T0, oferta_lista("700.00"))
    ler(s, no_limite, T0, oferta_lista("800.00"))
    ler(s, cara, T0, oferta_lista("800.01"))
    repo.gravar_ofertas(s, inelegivel.id, T0, [repo.OfertaAvaliada(oferta_lista("500.00"), None, False, True)])
    ler(s, ja_conferida, T0, oferta_lista("700.00"))
    conferencia(s, ja_conferida, T0 - timedelta(hours=1), preco="700.00", total="720.00")
    ler(s, liga_velha, T0, oferta_lista("500.00"))
    candidatas = repo.candidatas_ao_checkout(s, T0, cfg)
    assert [c.asin for c in candidatas] == ["B0CAN00001", "B0CAN00002"]
    assert candidatas[0] == repo.CandidataCheckout(boa.id, "B0CAN00001", "Shazaar", Decimal("700.00"))


def test_item_que_ficou_no_carrinho(s):
    a = confirmado(s, "B0MON00001")
    presa = conferencia(s, a, T0, SituacaoCheckout.FALHA, total=None, removido=False)
    conferencia(s, a, T0 + timedelta(minutes=1))
    assert [(i.conferencia_id, i.asin, i.tentativas) for i in repo.conferencias_com_item_no_carrinho(s)] == [
        (presa.id, "B0MON00001", 0)
    ]
    assert repo.marcar_item_removido(s, presa.id) is False  # pendente da retirada automática: não muda
    repo.marcar_asin_removido(s, "B0MON00001")  # carrinho conferido sem o item
    assert repo.conferencias_com_item_no_carrinho(s) == []


def test_retirada_em_rodizio_com_espera_e_sem_as_de_conferir_a_mao(s):
    a, b, c = (confirmado(s, asin) for asin in ("B0ROD00001", "B0ROD00002", "B0ROD00003"))
    primeira = conferencia(s, a, T0, SituacaoCheckout.FALHA, total=None, removido=False)
    segunda = conferencia(s, b, T0 + timedelta(minutes=1), SituacaoCheckout.FALHA, total=None, removido=False)
    a_mao = conferencia(s, c, T0 - timedelta(minutes=1), SituacaoCheckout.FALHA, total=None, removido=False)
    assert repo.marcar_conferir_a_mao(s, a_mao.id, T0, "teste") is True
    assert repo.marcar_conferir_a_mao(s, a_mao.id, T0, "teste") is False  # já estava: sem novo aviso
    assert repo.registrar_tentativa_retirada(s, primeira.id, T0) == 1
    ids = lambda agora: [i.conferencia_id for i in repo.conferencias_com_item_no_carrinho(s, agora, timedelta(minutes=15))]
    assert ids(T0 + timedelta(minutes=5)) == [segunda.id]  # a tentada há pouco espera; a nunca tentada vem
    assert ids(T0 + timedelta(minutes=15)) == [segunda.id, primeira.id]
    assert [(cf.id, asin) for cf, asin in repo.conferencias_a_conferir_a_mao(s)] == [(a_mao.id, "B0ROD00003")]
    assert "conferir à mão: teste" in a_mao.motivo
    assert repo.marcar_item_removido(s, a_mao.id) is True  # "Já conferi" no admin
    assert repo.marcar_item_removido(s, a_mao.id) is False  # já resolvida
    assert repo.conferencias_a_conferir_a_mao(s) == [] and a_mao.conferir_a_mao_em is None


def test_link_manual_usa_o_titulo_provisorio(s):
    produto = criar_produto(s, "p1")
    assert repo.casar_link_manual(s, produto.id, "B0MANUAL01", T0).titulo == repo.TITULO_MANUAL


def test_leitura_vazia_depois_de_uma_com_ofertas_nao_deixa_ofertas_velhas(s):
    a = confirmado(s, "B0MON00001")
    ler(s, a, T0 - timedelta(minutes=15), oferta_lista("500.00"))
    ler(s, a, T0)  # painel sem ofertas: preço nulo, nenhuma oferta
    assert repo.ofertas_da_ultima_leitura(s, [a.id]) == {}
    assert repo.candidatas_ao_checkout(s, T0, repo.obter_config(s)) == []


def test_leitura_velha_do_monitor_nao_vai_ao_checkout(s):
    cfg = repo.obter_config(s)  # intervalo 15 min: leitura vale até 30 min
    velha = confirmado(s, "B0CAN00001")
    recente = confirmado(s, "B0CAN00002")
    ler(s, velha, T0 - timedelta(minutes=31), oferta_lista("500.00"))
    ler(s, recente, T0 - timedelta(minutes=30), oferta_lista("500.00"))
    assert [c.asin for c in repo.candidatas_ao_checkout(s, T0, cfg)] == ["B0CAN00002"]


def test_busca_troca_o_preco_quando_a_leitura_do_monitor_ficou_velha(s):
    a = confirmado(s, "B0MON00001")
    ler(s, a, T0, oferta_lista("700.00", vendedor="Amazon.com.br", seller_id="amazon", envio=Envio.AMAZON, posicao=0))
    repo.registrar_preco(s, a.id, Decimal("650.00"), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, T0 + timedelta(minutes=30), SP)
    atual = s.get(PrecoAtualAmazon, a.id, populate_existing=True)
    assert (atual.preco, atual.origem) == (Decimal("700.00"), OrigemPreco.OFERTAS)  # 2 intervalos: ainda vale
    repo.registrar_preco(s, a.id, Decimal("650.00"), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, T0 + timedelta(minutes=31), SP)
    atual = s.get(PrecoAtualAmazon, a.id, populate_existing=True)
    assert (atual.preco, atual.origem, atual.coletado_em) == (
        Decimal("650.00"), OrigemPreco.BUSCA, T0 + timedelta(minutes=31)
    )


def test_falha_na_validade_tira_a_oferta_das_candidatas(s):
    cfg = repo.obter_config(s)
    a = confirmado(s, "B0CAN00001")
    ler(s, a, T0, oferta_lista("700.00"))
    conferencia(s, a, T0 - timedelta(hours=1), SituacaoCheckout.FALHA, preco="700.00", total=None)
    assert repo.candidatas_ao_checkout(s, T0, cfg) == []
    assert [c.asin for c in repo.candidatas_ao_checkout(s, T0 + timedelta(hours=6), cfg)] == []  # leitura velha
    ler(s, a, T0 + timedelta(hours=6), oferta_lista("700.00"))
    assert [c.asin for c in repo.candidatas_ao_checkout(s, T0 + timedelta(hours=6), cfg)] == ["B0CAN00001"]


def test_carrinho_ocupado_e_sem_login_nao_tiram_a_oferta_das_candidatas(s):
    cfg = repo.obter_config(s)
    a = confirmado(s, "B0CAN00001")
    ler(s, a, T0, oferta_lista("700.00"))
    conferencia(s, a, T0 - timedelta(minutes=10), SituacaoCheckout.CARRINHO_OCUPADO, preco="700.00", total=None)
    conferencia(s, a, T0 - timedelta(minutes=5), SituacaoCheckout.SEM_LOGIN, preco="700.00", total=None)
    assert [c.asin for c in repo.candidatas_ao_checkout(s, T0, cfg)] == ["B0CAN00001"]


def test_monitor_e_checkout_usam_so_o_par_confirmado(s):
    cfg = repo.obter_config(s)
    anuncio = confirmado(s, "B0PAR00001")  # confirmado para p-B0PAR00001 (Liga R$ 1.000)
    barato = criar_produto(s, "barato-par")
    criar_preco_liga(s, barato, "100.00", listagem_em=T0)
    criar_par(s, anuncio, barato, status=StatusCasamento.IGNORADO, origem=OrigemCasamento.OUTRO_CONFIRMADO, revisado_em=T0)
    so_pendente = criar_anuncio(s, "B0PAR00002", produto=barato)  # só pendente: fora do monitor e do checkout
    ler(s, anuncio, T0, oferta_lista("700.00"))
    ler(s, so_pendente, T0, oferta_lista("50.00"))
    assert repo.situacao_monitor(s, T0, 15).confirmados == 1
    assert repo.proximo_do_monitor(s, T0, 15) is None  # o único confirmado acabou de ser lido
    [linha] = repo.confirmados_com_referencia(s, [anuncio.id, so_pendente.id])
    assert linha.produto.liga_id == "p-B0PAR00001" and linha.liga.preco_a_partir == Decimal("1000.00")
    assert [c.asin for c in repo.candidatas_ao_checkout(s, T0, cfg)] == ["B0PAR00001"]  # 30% abaixo de 1.000


def test_confirmado_de_produto_inativo_sai_do_monitor_mesmo_com_par_pendente_ativo(s):
    anuncio = confirmado(s, "B0PAR00003", ativo=False)
    criar_par(s, anuncio, criar_produto(s, "ativo-par"))  # corrida: pendente para um produto ativo
    assert repo.situacao_monitor(s, T0, 15).confirmados == 0
    assert repo.proximo_do_monitor(s, T0, 15) is None
