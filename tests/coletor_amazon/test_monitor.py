import random
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fakes import (
    AvisadorFake,
    NavegadorInterativoFake,
    criar_anuncio,
    criar_preco_liga,
    criar_produto,
    fixture_amazon,
    html_produto_amazon,
    html_vendedor,
    pagina_html,
)
from fakes_ofertas import bloco_oferta, html_ofertas
from sqlalchemy import select

from tcg_sniper.avisos.catalogo import TipoAviso
from tcg_sniper.coletor_amazon.busca import ContextoBusca, DesafioAmazon
from tcg_sniper.coletor_amazon.monitor import aplicar_conferencia, ler_anuncio
from tcg_sniper.coletor_amazon.parsers import url_ofertas, url_produto, url_vendedor
from tcg_sniper.db import repositorio_amazon as repo
from tcg_sniper.db.models import (
    AnuncioAmazon,
    Envio,
    OfertaAmazon,
    Oportunidade,
    OrigemPreco,
    PrecoAtualAmazon,
    SituacaoCheckout,
    StatusCasamento,
    VendedorAmazon,
)
from tcg_sniper.notificador.base import Destino
from tcg_sniper.parsing import ErroParser

AGORA = datetime.fromisoformat("2026-10-15T15:00:00+00:00")
ASIN = "B0DNV55QBS"
BOA = "A classificação do vendedor é 5 de 5 estrelas (5.000 avaliações) 98% positivas nos últimos 12 meses"
POUCAS = "A classificação do vendedor é 5 de 5 estrelas (66 avaliações) 100% positivas nos últimos 12 meses"
CAPTCHA = '<html><body><form action="/errors/validateCaptcha"></form></body></html>'


@pytest.fixture
def anuncio(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "aether", nome="Aetherdrift Commander")
        criar_preco_liga(s, p, "1000.00", listagem_em=AGORA - timedelta(hours=2))
        return criar_anuncio(s, ASIN, produto=p, status=StatusCasamento.CONFIRMADO)


class Relogio:
    def __init__(self, agora=AGORA):
        self.agora = agora

    def __call__(self):
        return self.agora


def contexto(sessoes, config, paginas, checkout=True, relogio=None):
    """`checkout` False desliga a conferência: o monitor avisa já com o preço anunciado (com ela
    ligada e a oferta candidata, o aviso espera a conferência)."""
    with sessoes() as s, s.begin():
        repo.obter_config(s).checkout_ligado = checkout
    with sessoes() as s:
        cfg = repo.obter_config(s)
    navegador = NavegadorInterativoFake(paginas)
    avisador = AvisadorFake()
    ctx = ContextoBusca(
        sessoes=sessoes, navegador=navegador, avisador=avisador, config=config, cfg=cfg,
        relogio=relogio or (lambda: AGORA), dormir=lambda _: None, rng=random.Random(1), nome_falha="amazon-monitor",
    )
    return ctx, navegador, avisador


def painel(*blocos, asin=ASIN):
    return pagina_html(html_ofertas(*blocos), url=url_ofertas(asin))


def amazon(preco, **kw):
    return bloco_oferta(preco, "Amazon.com.br", seller_id=None, envia=None, destaque=True, **kw)


def conferencia(
    sessoes, anuncio_id, anunciado, total, impostos=None, vendedor="Amazon.com.br", quando=AGORA, itens=None,
    frete="0.00", situacao=SituacaoCheckout.OK,
):
    """Conferência ok. O preço conferido é itens + impostos (o frete fica de fora, mostrado à parte)."""
    with sessoes() as s, s.begin():
        return repo.registrar_conferencia(
            s, em=quando, anuncio_id=anuncio_id, vendedor_nome=vendedor, preco_anunciado=Decimal(anunciado),
            itens=Decimal(itens or anunciado), frete=Decimal(frete),
            impostos=None if impostos is None else Decimal(impostos),
            total=Decimal(total), situacao=situacao, motivo=None, item_removido=True,
        ).id


def test_grava_todas_as_ofertas_e_a_melhor_elegivel_vira_o_preco(sessoes, config, anuncio):
    pagina = painel(
        amazon("R$ 900,00"),
        bloco_oferta("R$ 800,00", "Loja Boa", "A1BOA", avaliacao=BOA),
        bloco_oferta("R$ 700,00", "Shazaar", "A2SHZ", origem="Estados Unidos", avaliacao=POUCAS),
        bloco_oferta("R$ 600,00", "Loja X", "AX", envia="Loja X"),
    )
    ctx, navegador, avisador = contexto(sessoes, config, {url_ofertas(ASIN): pagina})
    resultado = ler_anuncio(ctx, anuncio.id, ASIN)
    assert (resultado.paginas, resultado.ofertas, resultado.melhor.vendedor_nome) == (1, 4, "Loja Boa")
    assert navegador.esperas == [(url_ofertas(ASIN), "#aod-pinned-offer, #aod-offer")]
    with sessoes() as s:
        atual = s.get(PrecoAtualAmazon, anuncio.id)
        lidas = list(s.scalars(select(OfertaAmazon).order_by(OfertaAmazon.preco)))
        shazaar = s.scalar(select(VendedorAmazon).where(VendedorAmazon.seller_id == "A2SHZ"))
        visto = s.get(AnuncioAmazon, anuncio.id).visto_ultimo_em
    assert (atual.preco, atual.origem, atual.envio) == (Decimal("800.00"), OrigemPreco.OFERTAS, Envio.FBA)
    assert [(o.vendedor_nome, o.elegivel, o.melhor) for o in lidas] == [
        ("Loja X", False, False), ("Shazaar", False, False), ("Loja Boa", True, True), ("Amazon.com.br", True, False),
    ]
    assert (shazaar.pct_positivas, shazaar.num_avaliacoes) == (Decimal(100), 66)  # do painel, sem abrir o perfil
    assert visto == AGORA
    assert avisador.mensagens == []  # 800 é 20% abaixo de 1.000: não chega aos 25%


def test_abre_oportunidade_com_o_preco_anunciado_nao_conferido(sessoes, config, anuncio):
    paginas = {url_ofertas(ASIN): painel(amazon("R$ 700,00", prime=True))}
    ctx, _, avisador = contexto(sessoes, config, paginas, checkout=False)
    ler_anuncio(ctx, anuncio.id, ASIN)
    [(destino, texto)] = avisador.mensagens
    assert destino is Destino.OPORTUNIDADES
    [dados] = avisador.dados(TipoAviso.OPORTUNIDADE)
    assert dados.titulo_extra == "30% abaixo da Liga"
    assert "Amazon: *R$ 700,00* (anunciado, sem impostos; não conferido: conferência desligada)" in texto
    assert "Vendido por: Amazon · Prime" in texto
    with sessoes() as s:  # aviso pelo preço anunciado: a oportunidade não fica marcada como conferida
        assert s.scalar(select(Oportunidade)).alerta_conferido is False


def test_conferencia_valida_troca_o_preco_pelos_itens_com_impostos(sessoes, config, anuncio):
    conferencia(sessoes, anuncio.id, "700.00", "780.00", impostos="80.00", quando=AGORA - timedelta(hours=1))
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))})
    ler_anuncio(ctx, anuncio.id, ASIN)
    assert avisador.mensagens == []  # com os impostos fica 22% abaixo: não é oportunidade


def test_conferencia_valida_abre_com_o_preco_conferido_sem_frete(sessoes, config, anuncio):
    # total 790 = itens 700 + impostos 40 + frete 50; o preço conferido é 740 (o frete fica de fora)
    conferencia(
        sessoes, anuncio.id, "700.00", "790.00", impostos="40.00", frete="50.00", quando=AGORA - timedelta(hours=1)
    )
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))})
    ler_anuncio(ctx, anuncio.id, ASIN)
    [(_, texto)] = avisador.mensagens
    assert "Amazon: *R$ 740,00* (conferido, com impostos de R$ 40,00; frete R$ 50,00 à parte)" in texto
    assert avisador.dados(TipoAviso.OPORTUNIDADE)[0].titulo_extra == "26% abaixo da Liga"
    with sessoes() as s:  # aviso pelo preço conferido no checkout: marcada como conferida
        op = s.scalar(select(Oportunidade))
        assert (op.preco_amazon, op.alerta_conferido) == (Decimal("740.00"), True)


def test_conferencia_desligada_aparece_como_motivo(sessoes, config, anuncio):
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))}, checkout=False)
    ler_anuncio(ctx, anuncio.id, ASIN)
    assert "não conferido: conferência desligada" in avisador.mensagens[0][1]


def test_importada_prime_e_cupom_na_mensagem(sessoes, config, anuncio):
    bloco = bloco_oferta(
        "R$ 700,00", "Loja Boa", "A1BOA", avaliacao=BOA, origem="Estados Unidos", internacional=True, prime=True,
        cupom="15% off na 1ª compra com cartão Amazon",
    )
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(bloco)}, checkout=False)
    ler_anuncio(ctx, anuncio.id, ASIN)
    texto = avisador.mensagens[0][1]
    assert "enviado pela Amazon · importado (EUA) · Prime" in texto
    assert "Cupom: 15% off na 1ª compra com cartão Amazon (condicional, não descontado)" in texto


def test_sem_ofertas_registra_preco_nulo_e_fecha_a_oportunidade(sessoes, config, anuncio):
    ctx, _, avisador = contexto(
        sessoes, config, {url_ofertas(ASIN): [painel(amazon("R$ 700,00")), painel()]}, checkout=False
    )
    ler_anuncio(ctx, anuncio.id, ASIN)  # abre a oportunidade
    resultado = ler_anuncio(ctx, anuncio.id, ASIN)  # anúncio indisponível
    assert (resultado.melhor, resultado.ofertas) == (None, 0)
    with sessoes() as s:
        assert s.get(PrecoAtualAmazon, anuncio.id).preco is None
        assert s.scalar(select(Oportunidade)).fechada_em is not None
    assert len(avisador.mensagens) == 1  # só o alerta da abertura


def test_painel_ilegivel_salva_o_html_e_levanta(sessoes, config, anuncio):
    ctx, _, _ = contexto(sessoes, config, {url_ofertas(ASIN): pagina_html("<html><body>layout novo</body></html>")})
    with pytest.raises(ErroParser):
        ler_anuncio(ctx, anuncio.id, ASIN)
    assert (config.dir_dados / "falhas" / f"amazon-monitor-ofertas-{ASIN}.html").exists()


def test_captcha_levanta_desafio(sessoes, config, anuncio):
    ctx, _, _ = contexto(sessoes, config, {url_ofertas(ASIN): pagina_html(CAPTCHA)})
    with pytest.raises(DesafioAmazon) as erro:
        ler_anuncio(ctx, anuncio.id, ASIN)
    assert erro.value.url == url_ofertas(ASIN)


def test_lojista_fba_sem_avaliacao_no_painel_abre_o_perfil_uma_vez(sessoes, config, anuncio):
    pagina = painel(bloco_oferta("R$ 700,00", "Loja X", "A1"))
    paginas = {url_ofertas(ASIN): [pagina, pagina], url_vendedor("A1"): pagina_html(html_vendedor("Loja X", 97, "2.340"))}
    ctx, navegador, avisador = contexto(sessoes, config, paginas, checkout=False)
    assert ler_anuncio(ctx, anuncio.id, ASIN).paginas == 2
    assert "Vendido por: Loja X (97% de 2.340 avaliações) · enviado pela Amazon" in avisador.mensagens[0][1]
    assert ler_anuncio(ctx, anuncio.id, ASIN).paginas == 1  # avaliado há menos de 7 dias
    assert navegador.visitadas.count(url_vendedor("A1")) == 1 and len(avisador.mensagens) == 1


def test_oferta_usada_nunca_e_elegivel(sessoes, config, anuncio):
    pagina = painel(
        bloco_oferta("R$ 500,00", "Amazon.com.br", seller_id=None, envia=None, condicao="Usado - Como novo", destaque=True),
        bloco_oferta("R$ 950,00", "Amazon.com.br", seller_id=None, envia=None),
    )
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): pagina})
    assert ler_anuncio(ctx, anuncio.id, ASIN).melhor.preco == Decimal("950.00")
    assert avisador.mensagens == []


def test_sem_elegivel_a_nova_mais_barata_vira_referencia_sem_alerta(sessoes, config, anuncio):
    pagina = painel(
        bloco_oferta("R$ 600,00", "Shazaar", "A2SHZ", avaliacao=POUCAS),
        bloco_oferta("R$ 650,00", "Loja X", "AX", envia="Loja X"),
    )
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): pagina})
    assert ler_anuncio(ctx, anuncio.id, ASIN).melhor.vendedor_nome == "Shazaar"
    with sessoes() as s:
        atual = s.get(PrecoAtualAmazon, anuncio.id)
    assert (atual.preco, atual.envio) == (Decimal("600.00"), Envio.FBA)
    assert avisador.mensagens == []


def test_anuncio_colado_a_mao_le_a_pagina_do_produto_uma_vez(sessoes, config):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "pm", nome="Produto M")
        criar_preco_liga(s, p, "1000.00", listagem_em=AGORA)
        manual = repo.casar_link_manual(s, p.id, "B0MANUAL01", AGORA - timedelta(hours=1))
    pagina = painel(amazon("R$ 990,00"), asin="B0MANUAL01")
    paginas = {
        url_ofertas("B0MANUAL01"): [pagina, pagina],
        url_produto("B0MANUAL01"): pagina_html(html_produto_amazon("Caixa Manual", "R$ 990,00", "Amazon.com.br", None)),
    }
    ctx, _, _ = contexto(sessoes, config, paginas)
    assert ler_anuncio(ctx, manual.id, "B0MANUAL01").paginas == 2
    assert ler_anuncio(ctx, manual.id, "B0MANUAL01").paginas == 1
    with sessoes() as s:
        assert s.get(AnuncioAmazon, manual.id).titulo == "Caixa Manual"


def test_conferencia_atualiza_a_aberta_sem_novo_alerta_ou_fecha(sessoes, config, anuncio):
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))}, checkout=False)
    ler_anuncio(ctx, anuncio.id, ASIN)  # conferência desligada: abre e avisa com o preço anunciado
    aplicar_conferencia(ctx, anuncio.id, conferencia(sessoes, anuncio.id, "700.00", "720.00", impostos="20.00"))
    with sessoes() as s:
        op = s.scalar(select(Oportunidade))
    assert (op.preco_amazon, op.preco_alertado, op.fechada_em) == (Decimal("720.00"), Decimal("700.00"), None)
    aplicar_conferencia(ctx, anuncio.id, conferencia(sessoes, anuncio.id, "700.00", "800.00", impostos="100.00"))
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)).fechada_em is not None
    assert len(avisador.mensagens) == 1


def test_conferencia_que_baixa_o_preco_abre_e_avisa_conferido(sessoes, config, anuncio):
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 760,00"))})
    ler_anuncio(ctx, anuncio.id, ASIN)  # 24%: candidata, não oportunidade
    assert avisador.mensagens == []
    aplicar_conferencia(ctx, anuncio.id, conferencia(sessoes, anuncio.id, "760.00", "770.00", itens="740.00", frete="30.00"))
    [(_, texto)] = avisador.mensagens
    assert "Amazon: *R$ 740,00* (conferido, com impostos; frete R$ 30,00 à parte)" in texto
    assert avisador.dados(TipoAviso.OPORTUNIDADE)[0].titulo_extra == "26% abaixo da Liga"
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)).preco_amazon == Decimal("740.00")


def test_conferencia_de_outro_preco_e_ignorada(sessoes, config, anuncio):
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 760,00"))})
    ler_anuncio(ctx, anuncio.id, ASIN)
    aplicar_conferencia(ctx, anuncio.id, conferencia(sessoes, anuncio.id, "690.00", "600.00"))
    assert avisador.mensagens == []
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)) is None


def test_conferencia_de_outro_vendedor_com_o_mesmo_preco_e_ignorada(sessoes, config, anuncio):
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 760,00"))})
    ler_anuncio(ctx, anuncio.id, ASIN)  # a melhor oferta é da Amazon
    outra = conferencia(sessoes, anuncio.id, "760.00", "740.00", itens="740.00", vendedor="Loja X")
    aplicar_conferencia(ctx, anuncio.id, outra)
    assert avisador.mensagens == []
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)) is None


def test_conferencia_vencida_ou_com_falha_e_ignorada(sessoes, config, anuncio):
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 760,00"))})
    ler_anuncio(ctx, anuncio.id, ASIN)
    vencida = conferencia(sessoes, anuncio.id, "760.00", "740.00", itens="740.00", quando=AGORA - timedelta(hours=7))
    aplicar_conferencia(ctx, anuncio.id, vencida)
    falha = conferencia(sessoes, anuncio.id, "760.00", "740.00", itens="740.00", situacao=SituacaoCheckout.FALHA)
    aplicar_conferencia(ctx, anuncio.id, falha)
    assert avisador.mensagens == []
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)) is None


def test_perfil_de_vendedor_ilegivel_deixa_o_lojista_inelegivel_e_segue(sessoes, config, anuncio):
    pagina = painel(amazon("R$ 700,00"), bloco_oferta("R$ 600,00", "Loja X", "A1"))
    paginas = {url_ofertas(ASIN): pagina, url_vendedor("A1"): pagina_html("<html><body>layout novo</body></html>")}
    ctx, _, avisador = contexto(sessoes, config, paginas, checkout=False)
    resultado = ler_anuncio(ctx, anuncio.id, ASIN)
    assert (resultado.paginas, resultado.ofertas, resultado.melhor.vendedor_nome) == (2, 2, "Amazon.com.br")
    with sessoes() as s:
        lidas = {o.vendedor_nome: (o.elegivel, o.melhor) for o in s.scalars(select(OfertaAmazon))}
    assert lidas == {"Loja X": (False, False), "Amazon.com.br": (True, True)}
    assert "Amazon: *R$ 700,00* (anunciado, sem impostos" in avisador.mensagens[0][1]


def test_pagina_do_produto_com_captcha_nao_impede_a_decisao(sessoes, config):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "pm", nome="Produto M")
        criar_preco_liga(s, p, "1000.00", listagem_em=AGORA)
        manual = repo.casar_link_manual(s, p.id, "B0MANUAL01", AGORA - timedelta(hours=1))
    paginas = {
        url_ofertas("B0MANUAL01"): painel(amazon("R$ 700,00"), asin="B0MANUAL01"),
        url_produto("B0MANUAL01"): pagina_html(CAPTCHA),
    }
    ctx, _, avisador = contexto(sessoes, config, paginas, checkout=False)
    with pytest.raises(DesafioAmazon):
        ler_anuncio(ctx, manual.id, "B0MANUAL01")
    assert len(avisador.mensagens) == 1
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)).preco_amazon == Decimal("700.00")


# --- o primeiro aviso espera a conferência; a validade vencida não fecha nem realerta ----------------


def test_com_conferencia_a_caminho_o_aviso_espera_e_sai_com_o_preco_conferido(sessoes, config, anuncio):
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00", prime=True))})
    ler_anuncio(ctx, anuncio.id, ASIN)  # 30% abaixo no anunciado, mas a oferta vai ao checkout
    assert avisador.mensagens == []
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)) is None
    aplicar_conferencia(ctx, anuncio.id, conferencia(sessoes, anuncio.id, "700.00", "720.00", impostos="20.00"))
    [(destino, texto)] = avisador.mensagens
    assert destino is Destino.OPORTUNIDADES
    assert "Amazon: *R$ 720,00* (conferido, com impostos de R$ 20,00" in texto
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)).preco_alertado == Decimal("720.00")


def test_conferencia_vencida_nao_fecha_nem_realerta_a_aberta_ate_a_nova_conferencia(sessoes, config, anuncio):
    relogio = Relogio(AGORA)
    conferencia(sessoes, anuncio.id, "700.00", "740.00", impostos="40.00", quando=AGORA - timedelta(minutes=10))
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))}, relogio=relogio)
    ler_anuncio(ctx, anuncio.id, ASIN)  # abre com o conferido (740)
    assert len(avisador.mensagens) == 1
    relogio.agora = AGORA + timedelta(hours=7)  # a conferência venceu (validade 6 h)
    ler_anuncio(ctx, anuncio.id, ASIN)  # 700 anunciado: não fecha nem realerta, espera a nova conferência
    with sessoes() as s:
        op = s.scalar(select(Oportunidade))
    assert (op.fechada_em, op.preco_alertado, op.preco_amazon) == (None, Decimal("740.00"), Decimal("740.00"))
    assert len(avisador.mensagens) == 1
    nova = conferencia(sessoes, anuncio.id, "700.00", "742.00", impostos="42.00", quando=relogio.agora)
    aplicar_conferencia(ctx, anuncio.id, nova)  # mesma oferta, quase o mesmo conferido: só atualiza
    with sessoes() as s:
        op = s.scalar(select(Oportunidade))
    assert (op.fechada_em, op.preco_alertado, op.preco_amazon, op.alertada_em) == (
        None, Decimal("740.00"), Decimal("742.00"), AGORA,
    )
    assert len(avisador.mensagens) == 1


def _registrar(sessoes, anuncio_id, situacao, motivo, em, vendedor="Amazon.com.br", anunciado="700.00"):
    with sessoes() as s, s.begin():
        repo.registrar_conferencia(
            s, em=em, anuncio_id=anuncio_id, vendedor_nome=vendedor, preco_anunciado=Decimal(anunciado),
            itens=None, frete=None, impostos=None, total=None, situacao=situacao, motivo=motivo, item_removido=True,
        )


@pytest.mark.parametrize(
    ("preparo", "motivo"),
    [
        ("sem_login", "não conferido: conta Amazon sem login"),
        ("carrinho_ocupado", "não conferido: seu carrinho tem itens"),
        ("falhou", "não conferido: a conferência falhou: painel mudou"),
    ],
)
def test_sem_conferencia_possivel_avisa_ja_com_o_preco_anunciado(sessoes, config, anuncio, preparo, motivo):
    if preparo == "sem_login":
        with sessoes() as s, s.begin():
            repo.obter_config(s).checkout_sem_login_em = AGORA - timedelta(hours=1)
    elif preparo == "carrinho_ocupado":  # a última conferência (de outro anúncio) achou item do usuário
        _registrar(
            sessoes, anuncio.id, SituacaoCheckout.CARRINHO_OCUPADO, "1 item(ns) no carrinho; nada foi clicado",
            AGORA - timedelta(minutes=20), vendedor="Outro", anunciado="1.00",
        )
    else:
        _registrar(sessoes, anuncio.id, SituacaoCheckout.FALHA, "painel mudou", AGORA - timedelta(hours=1))
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))})
    ler_anuncio(ctx, anuncio.id, ASIN)
    [(_, texto)] = avisador.mensagens
    assert f"Amazon: *R$ 700,00* (anunciado, sem impostos; {motivo})" in texto


def test_conferencia_que_baixa_o_preco_da_aberta_realerta_com_o_conferido(sessoes, config, anuncio):
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))}, checkout=False)
    ler_anuncio(ctx, anuncio.id, ASIN)  # abre com o anunciado 700
    aplicar_conferencia(ctx, anuncio.id, conferencia(sessoes, anuncio.id, "700.00", "650.00", itens="650.00"))
    assert len(avisador.mensagens) == 2 and "Amazon: *R$ 650,00* (conferido" in avisador.mensagens[1][1]
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)).preco_alertado == Decimal("650.00")


def test_conferencia_nao_vale_com_o_preco_atual_de_outra_origem(sessoes, config, anuncio):
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))})
    ler_anuncio(ctx, anuncio.id, ASIN)
    with sessoes() as s, s.begin():  # outra leitura (página do produto) trocou o preço atual, mesmo valor
        repo.registrar_preco(s, anuncio.id, Decimal("700.00"), OrigemPreco.PRODUTO, None, Envio.AMAZON, AGORA, config.zona)
    aplicar_conferencia(ctx, anuncio.id, conferencia(sessoes, anuncio.id, "700.00", "720.00", impostos="20.00"))
    assert avisador.mensagens == []
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)) is None


@pytest.mark.parametrize("nome", ["ofertas_importada", "ofertas_amazon"])
def test_amazon_global_em_destaque_e_envio_amazon_e_elegivel(sessoes, config, anuncio, nome):
    pagina = pagina_html(fixture_amazon(nome), url=url_ofertas(ASIN))
    ctx, _, _ = contexto(sessoes, config, {url_ofertas(ASIN): pagina})
    ler_anuncio(ctx, anuncio.id, ASIN)
    with sessoes() as s:
        destaque = s.scalar(select(OfertaAmazon).where(OfertaAmazon.vendedor_nome == "Amazon Global"))
    assert (destaque.envio, destaque.elegivel) == (Envio.AMAZON, True)


# --- realerta pelo anunciado depois de um aviso conferido ----------------------------------------


def test_aviso_conferido_nao_realerta_pelo_anunciado(sessoes, config, anuncio):
    # O anunciado não tem os impostos de importação: parece mais barato que o conferido. Sem nova
    # conferência, a queda só atualiza a aberta em silêncio.
    relogio = Relogio(AGORA)
    conferencia(sessoes, anuncio.id, "700.00", "740.00", impostos="40.00", quando=AGORA - timedelta(minutes=10))
    paginas = {url_ofertas(ASIN): [painel(amazon("R$ 700,00")), painel(amazon("R$ 600,00"))]}
    ctx, _, avisador = contexto(sessoes, config, paginas, checkout=False, relogio=relogio)
    ler_anuncio(ctx, anuncio.id, ASIN)  # abre e avisa com o conferido (740)
    assert len(avisador.mensagens) == 1
    relogio.agora = AGORA + timedelta(hours=7)  # a conferência venceu
    ler_anuncio(ctx, anuncio.id, ASIN)  # 600 anunciado: 19% abaixo do alertado, mas não conferido
    assert len(avisador.mensagens) == 1
    with sessoes() as s:
        op = s.scalar(select(Oportunidade))
    assert (op.fechada_em, op.preco_alertado, op.preco_amazon, op.alerta_conferido) == (
        None, Decimal("740.00"), Decimal("600.00"), True,
    )


def test_aviso_anunciado_realerta_pelo_anunciado(sessoes, config, anuncio):
    paginas = {url_ofertas(ASIN): [painel(amazon("R$ 700,00")), painel(amazon("R$ 600,00"))]}
    ctx, _, avisador = contexto(sessoes, config, paginas, checkout=False)
    ler_anuncio(ctx, anuncio.id, ASIN)  # abre e avisa com o anunciado (700)
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)).alerta_conferido is False
    ler_anuncio(ctx, anuncio.id, ASIN)  # 600: caiu 14% sobre o alertado
    assert len(avisador.mensagens) == 2 and "Amazon: *R$ 600,00* (anunciado" in avisador.mensagens[1][1]
    with sessoes() as s:
        op = s.scalar(select(Oportunidade))
    assert (op.preco_alertado, op.alerta_conferido) == (Decimal("600.00"), False)


def test_realerta_conferido_marca_o_aviso_como_conferido(sessoes, config, anuncio):
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))}, checkout=False)
    ler_anuncio(ctx, anuncio.id, ASIN)  # abre com o anunciado 700
    aplicar_conferencia(ctx, anuncio.id, conferencia(sessoes, anuncio.id, "700.00", "650.00", itens="650.00"))
    assert len(avisador.mensagens) == 2
    with sessoes() as s:
        op = s.scalar(select(Oportunidade))
    assert (op.preco_alertado, op.alerta_conferido) == (Decimal("650.00"), True)


def test_leitura_mais_barata_que_a_anterior_conta_como_queda(sessoes, config, anuncio):
    ctx, _, _ = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 900,00"))}, checkout=False)
    assert ler_anuncio(ctx, anuncio.id, ASIN).caiu is False  # primeira leitura: nada a comparar
    ctx, _, _ = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 850,00"))}, checkout=False)
    assert ler_anuncio(ctx, anuncio.id, ASIN).caiu is True
    ctx, _, _ = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 870,00"))}, checkout=False)
    assert ler_anuncio(ctx, anuncio.id, ASIN).caiu is False


def test_oportunidade_vai_com_a_chave_do_anuncio(sessoes, config, anuncio):
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))}, checkout=False)
    ler_anuncio(ctx, anuncio.id, ASIN)
    [(tipo, chave, dados)] = avisador.avisos
    assert (tipo, chave) == (TipoAviso.OPORTUNIDADE, str(anuncio.id))
    assert dados.destaque == "Aetherdrift Commander" and dados.link_produto == f"https://www.amazon.com.br/dp/{ASIN}"
    assert dados.titulo_extra == "30% abaixo da Liga"


def test_titulo_e_linha_da_amazon_usam_o_mesmo_preco_conferido(sessoes, config, anuncio):
    # Anunciado 700 (30% abaixo de 1.000), conferido 740 = itens 700 + impostos 40: o título e a linha da
    # Amazon falam do conferido (26%), nunca do anunciado.
    conferencia(sessoes, anuncio.id, "700.00", "740.00", impostos="40.00", quando=AGORA - timedelta(minutes=10))
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))})
    ler_anuncio(ctx, anuncio.id, ASIN)
    [dados] = avisador.dados(TipoAviso.OPORTUNIDADE)
    assert dados.titulo_extra == "26% abaixo da Liga"
    assert "Amazon: *R$ 740,00* (conferido" in avisador.mensagens[0][1]
    assert "R$ 700,00" not in avisador.mensagens[0][1]


def test_conferencia_aplicada_usa_o_preco_conferido_no_titulo(sessoes, config, anuncio):
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))})
    ler_anuncio(ctx, anuncio.id, ASIN)  # conferência a caminho: espera
    aplicar_conferencia(ctx, anuncio.id, conferencia(sessoes, anuncio.id, "700.00", "740.00", impostos="40.00"))
    [dados] = avisador.dados(TipoAviso.OPORTUNIDADE)
    assert dados.titulo_extra == "26% abaixo da Liga"
    assert "Amazon: *R$ 740,00* (conferido" in avisador.mensagens[0][1]
