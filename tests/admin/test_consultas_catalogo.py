"""Situação do catálogo contada por produto ativo da LigaMagic (não por par nem por chamada da IA)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fakes import catalogo_exemplo, criar_anuncio, criar_produto

from tcg_sniper.admin.consultas_catalogo import situacao_catalogo
from tcg_sniper.db.models import AvaliacaoIA, Casamento, StatusCasamento

SP = ZoneInfo("America/Sao_Paulo")
NOITE = datetime(2026, 10, 17, 1, 30, tzinfo=UTC)  # 22:30 em São Paulo, ainda dia 16
HOJE_SP = datetime(2026, 10, 16, 13, 0, tzinfo=UTC)  # 10:00 do dia 16 em SP
ONTEM_SP = datetime(2026, 10, 16, 2, 0, tzinfo=UTC)  # 23:00 do dia 15 em SP (já dia 16 em UTC)

CONF, PEND, IGN = StatusCasamento.CONFIRMADO, StatusCasamento.PENDENTE, StatusCasamento.IGNORADO


def avaliar(s, anuncio, produto, em=HOJE_SP):
    s.add(AvaliacaoIA(
        anuncio_id=anuncio.id, produto_id=produto.id, mesmo_produto=True, confianca=80, motivo="m",
        modelo="gpt-5", assinatura="a", sem_imagem=False, avaliado_em=em,
    ))
    s.flush()


def test_cada_produto_ativo_cai_em_uma_situacao(s):
    catalogo_exemplo(s)
    c = situacao_catalogo(s, NOITE, SP)
    assert (c.casado, c.esperando_decisao, c.so_ignorados, c.sem_candidato) == (2, 1, 1, 1)
    assert c.casado + c.esperando_decisao + c.so_ignorados + c.sem_candidato == c.produtos_ativos == 5
    assert (c.com_mais_de_uma_sugestao, c.com_mais_de_um_confirmado) == (2, 1)
    assert (c.pares_pendentes, c.produtos_com_pendentes, c.casados_com_pendentes) == (2, 2, 1)
    assert c.por_situacao() == {"casado": 2, "esperando_decisao": 1, "so_ignorados": 1, "sem_candidato": 1}
    assert c.pct("casado") == 40


def test_catalogo_vazio_soma_zero(s):
    c = situacao_catalogo(s, NOITE, SP)
    assert c.produtos_ativos == 0 and sum(c.por_situacao().values()) == 0 and c.pct("casado") == 0
    assert (c.produtos_avaliados, c.avaliacoes_total, c.media_por_produto) == (0, 0, 0)


def test_ia_contada_por_produto(s):
    a = criar_produto(s, "a")  # duas avaliações: uma hoje e uma ontem (no fuso)
    a1, a2 = criar_anuncio(s, "B0A0000001", a), criar_anuncio(s, "B0A0000002", a)
    avaliar(s, a1, a, HOJE_SP)
    avaliar(s, a2, a, ONTEM_SP)
    b = criar_produto(s, "b")  # pendente sem avaliação: esperando a IA
    criar_anuncio(s, "B0B0000001", b)
    c = criar_produto(s, "c")  # avaliado, mas marcado para reavaliar: esperando a IA
    c1 = criar_anuncio(s, "B0C0000001", c)
    avaliar(s, c1, c, HOJE_SP)
    s.get(Casamento, {"anuncio_id": c1.id, "produto_id": c.id}).reavaliar = True
    d = criar_produto(s, "d")  # casado com um pendente sem avaliação: não espera a IA
    criar_anuncio(s, "B0D0000001", d, CONF)
    criar_anuncio(s, "B0D0000002", d)
    e = criar_produto(s, "e")  # só avaliado "ontem" no fuso (já hoje em UTC)
    e1 = criar_anuncio(s, "B0E0000001", e, IGN)
    avaliar(s, e1, e, ONTEM_SP)
    inativo = criar_produto(s, "inativo", ativo=False)
    i1 = criar_anuncio(s, "B0I0000001", inativo)
    avaliar(s, i1, inativo, HOJE_SP)
    s.flush()
    cat = situacao_catalogo(s, NOITE, SP)
    assert cat.produtos_avaliados == 3  # a, c, e (duas avaliações de a = 1 produto; inativo fora)
    assert cat.avaliados_hoje == 2  # a, c
    assert cat.esperando_ia == 2  # b, c
    assert (cat.avaliacoes_total, cat.media_por_produto) == (4, 1.3)
