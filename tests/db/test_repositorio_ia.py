from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto

from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import COLETOR_CASADOR, PADROES_CONFIG_IA, EstadoColetorTipo, StatusCasamento

SP = ZoneInfo("America/Sao_Paulo")


def chamada(s, em, custo="0.01", ok=True):
    return repo_ia.registrar_chamada(
        s, em=em, finalidade="casamento", modelo="gpt-5", tokens_entrada=100, tokens_saida=10,
        custo_usd=Decimal(custo), ok=ok, erro=None if ok else "falhou",
    )


def test_config_ia_nasce_com_os_padroes(s):
    cfg = repo_ia.obter_config_ia(s)
    for campo, valor in PADROES_CONFIG_IA.items():
        assert getattr(cfg, campo) == valor
    assert cfg.ligado is False and cfg.automatico is False


def test_salvar_config_ia(s):
    repo_ia.obter_config_ia(s)
    repo_ia.salvar_config_ia(s, {"modelo": "gpt-5-mini", "teto_dia_usd": Decimal("0.50")}, T0)
    cfg = repo_ia.obter_config_ia(s)
    assert cfg.modelo == "gpt-5-mini" and cfg.teto_dia_usd == Decimal("0.50")


def test_gasto_por_dia_e_mes_no_fuso(s):
    # T0 = 2026-10-13 13:00 UTC = 10:00 em São Paulo
    chamada(s, T0, "0.10")
    chamada(s, T0 - timedelta(hours=12), "0.20")  # 2026-10-12 22:00 em SP: outro dia, mesmo mês
    chamada(s, T0 - timedelta(days=20), "1.00")  # setembro
    chamada(s, T0, "0.05", ok=False)
    g = repo_ia.gasto(s, T0, SP)
    assert g.dia_usd == Decimal("0.15")
    assert g.mes_usd == Decimal("0.35")
    assert g.chamadas_dia == 2


def test_gasto_vazio(s):
    assert repo_ia.gasto(s, T0, SP) == repo_ia.Gasto(Decimal(0), Decimal(0), 0)


def test_virada_do_dia_em_sao_paulo(s):
    # 02:59 UTC de 13/10 = 23:59 de 12/10 em SP; 03:00 UTC = 00:00 de 13/10
    chamada(s, T0.replace(hour=2, minute=59), "0.30")
    assert repo_ia.gasto(s, T0.replace(hour=3, minute=0), SP).dia_usd == Decimal(0)
    assert repo_ia.gasto(s, T0.replace(hour=2, minute=59, second=30), SP).dia_usd == Decimal("0.30")


def test_pares_pendentes_com_avaliacao_e_precos(s):
    p = criar_produto(s, "p1", nome="Caixa X")
    inativo = criar_produto(s, "p2", ativo=False, nome="Caixa Y")
    criar_preco_liga(s, p, Decimal(500))
    a1 = criar_anuncio(s, "B1", produto=p, agora=T0 - timedelta(days=1))
    a2 = criar_anuncio(s, "B2", produto=p, agora=T0)
    a3 = criar_anuncio(s, "B3", produto=inativo, agora=T0 + timedelta(hours=1))
    criar_anuncio(s, "B4", produto=p, status=StatusCasamento.CONFIRMADO)
    criar_anuncio(s, "B5", produto=None)
    av = repo_ia.gravar_avaliacao(
        s, anuncio_id=a1.id, produto_id=p.id, mesmo_produto=True, confianca=95, motivo="igual",
        modelo="gpt-5", assinatura="x", sem_imagem=False, chamada_id=None, agora=T0,
    )
    pares = repo_ia.pares_pendentes(s)
    assert [par.anuncio.id for par in pares] == [a2.id, a1.id, a3.id]  # ativos primeiro, mais recentes primeiro
    assert pares[1].avaliacao.id == av.id and pares[0].avaliacao is None
    assert pares[0].preco_liga == Decimal(500) and pares[0].preco_amazon is None


def test_gravar_avaliacao_substitui_e_preserva_aplicada_em(s):
    p = criar_produto(s, "p1")
    a = criar_anuncio(s, "B1", produto=p)
    kw = {"anuncio_id": a.id, "produto_id": p.id, "modelo": "gpt-5", "sem_imagem": False, "chamada_id": None}
    av = repo_ia.gravar_avaliacao(s, mesmo_produto=True, confianca=95, motivo="m1", assinatura="a1", agora=T0, **kw)
    av.aplicada_em = T0
    s.flush()
    av2 = repo_ia.gravar_avaliacao(
        s, mesmo_produto=False, confianca=60, motivo="m2", assinatura="a2", agora=T0 + timedelta(hours=1), **kw
    )
    assert av2.id == av.id
    assert (av2.mesmo_produto, av2.confianca, av2.motivo, av2.assinatura) == (False, 60, "m2", "a2")
    assert av2.aplicada_em == T0


def test_avaliacoes_dos_pares(s):
    p, q = criar_produto(s, "p1"), criar_produto(s, "p2")
    a = criar_anuncio(s, "B1", produto=p)
    repo_ia.gravar_avaliacao(
        s, anuncio_id=a.id, produto_id=q.id, mesmo_produto=True, confianca=95, motivo="m", modelo="gpt-5",
        assinatura="x", sem_imagem=False, chamada_id=None, agora=T0,
    )
    assert repo_ia.avaliacoes_dos_pares(s, [(a.id, p.id)]) == {}
    assert set(repo_ia.avaliacoes_dos_pares(s, [(a.id, q.id)])) == {(a.id, q.id)}
    assert repo_ia.avaliacoes_dos_pares(s, []) == {}


def test_pares_decididos_sem_os_aplicados_pela_ia(s):
    p = criar_produto(s, "p1")
    c = criar_anuncio(s, "B1", produto=p, status=StatusCasamento.CONFIRMADO)
    i = criar_anuncio(s, "B2", produto=p, status=StatusCasamento.IGNORADO)
    pela_ia = criar_anuncio(s, "B3", produto=p, status=StatusCasamento.CONFIRMADO)
    criar_anuncio(s, "B4", produto=p)  # pendente
    av = repo_ia.gravar_avaliacao(
        s, anuncio_id=pela_ia.id, produto_id=p.id, mesmo_produto=True, confianca=99, motivo="m", modelo="gpt-5",
        assinatura="x", sem_imagem=False, chamada_id=None, agora=T0,
    )
    av.aplicada_em = T0
    s.flush()
    decididos = repo_ia.pares_decididos(s, None)
    assert {(d.anuncio.id, d.confirmado) for d in decididos} == {(c.id, True), (i.id, False)}
    assert len(repo_ia.pares_decididos(s, 1)) == 1


def test_estado_do_casador_e_solicitacao(s):
    estado = repo.obter_estado(s, T0, COLETOR_CASADOR)
    assert estado.id == 3 and estado.estado is EstadoColetorTipo.ATIVO
    repo.solicitar_execucao(s, T0, COLETOR_CASADOR)
    assert repo.consumir_solicitacao(s, T0) is False  # a da Liga não foi pedida
    assert repo.consumir_solicitacao(s, T0, COLETOR_CASADOR) is True
    assert repo.consumir_solicitacao(s, T0, COLETOR_CASADOR) is False
