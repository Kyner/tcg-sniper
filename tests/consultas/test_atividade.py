from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fakes import criar_anuncio, criar_produto

from tcg_sniper.consultas.atividade import FiltroAtividade, linha_do_tempo
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import (
    AcaoGestao,
    AvaliacaoIA,
    ChamadaIA,
    Coleta,
    ConferenciaCheckout,
    Envio,
    EstadoAviso,
    ExecucaoManutencao,
    MensagemSaida,
    OfertaAmazon,
    Papel,
    SituacaoCheckout,
    StatusCasamento,
    StatusColeta,
    StatusManutencao,
    StatusMensagem,
    TipoAcaoGestao,
    TipoColeta,
)
from tcg_sniper.gestao.servicos import Servico

T = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def _filtro(**campos) -> FiltroAtividade:
    base = {"servico": None, "o_que": None, "situacao": None, "de": None, "ate": None, "busca": None}
    return FiltroAtividade(**(base | campos))


def _coleta(s, quando, tipo=TipoColeta.PRODUTOS, status=StatusColeta.OK, ok=10, falha=0, erro=None):
    c = Coleta(
        tipo=tipo, iniciada_em=quando, finalizada_em=quando + timedelta(minutes=5), status=status,
        produtos_ok=ok, produtos_falha=falha, erro=erro,
    )
    s.add(c)
    s.flush()
    return c


def _leitura(s, anuncio, quando, preco="300.00", vendedor="Loja X"):
    for melhor, valor in ((True, preco), (False, "350.00")):
        s.add(OfertaAmazon(
            anuncio_id=anuncio.id, lida_em=quando, vendedor_nome=vendedor if melhor else "Outra", preco=Decimal(valor),
            condicao="novo", envio=Envio.FBA, importada=False, prime=True, elegivel=True, melhor=melhor,
        ))
    s.flush()


def _conferencia(s, anuncio, quando, situacao=SituacaoCheckout.OK, itens="280.00", impostos="29.83", frete=None,
                 motivo=None):
    c = ConferenciaCheckout(
        em=quando, anuncio_id=anuncio.id, vendedor_nome="Loja X", preco_anunciado=Decimal("300.00"),
        itens=Decimal(itens) if itens else None, impostos=Decimal(impostos) if impostos else None,
        frete=Decimal(frete) if frete else None, total=None, situacao=situacao, motivo=motivo, item_removido=True,
    )
    s.add(c)
    s.flush()
    return c


def _chamada(s, quando, ok=True, custo="0.012345", finalidade="casamento", erro=None):
    c = ChamadaIA(
        em=quando, finalidade=finalidade, modelo="gpt-teste", tokens_entrada=1000, tokens_saida=200,
        custo_usd=Decimal(custo), ok=ok, erro=erro,
    )
    s.add(c)
    s.flush()
    return c


def _mensagem(s, quando, status=StatusMensagem.ENVIADA, texto="*Oportunidade*\nCaixa X", erro=None, destino="oportunidades"):
    m = MensagemSaida(
        destino=destino, numero="+5511900000009" if destino == "individual" else None, texto=texto, status=status, proxima_tentativa_em=quando, criada_em=quando,
        atualizado_em=quando, enviada_em=quando if status is StatusMensagem.ENVIADA else None, ultimo_erro=erro,
    )
    s.add(m)
    s.flush()
    return m


def _execucao(s, quando, status=StatusManutencao.OK, erro=None):
    e = ExecucaoManutencao(inicio=quando, fim=quando + timedelta(minutes=2), status=status, erro=erro,
                           arquivo="tcg-2026-10-25.dump", tamanho_bytes=2048)
    s.add(e)
    s.flush()
    return e


def _aviso(s, quando, tipo="liga_desafio", chave="geral", aberto=True):
    a = EstadoAviso(tipo=tipo, chave=chave, aberto=aberto, primeiro_em=quando, ultimo_em=quando, ocorrencias=2)
    s.add(a)
    s.flush()
    return a


def _acao(s, quando, usuario_id=None, tipo=TipoAcaoGestao.SERVICO, detalhe=None):
    a = AcaoGestao(
        usuario_id=usuario_id, em=quando, tipo=tipo,
        detalhe=detalhe or {"servico": "liga", "acao": "pausar", "codigo": "liga_pausar"},
    )
    s.add(a)
    s.flush()
    return a


def _todas(s, filtro, limite=50):
    linhas, cursor, paginas = [], None, 0
    while True:
        pagina, cursor = linha_do_tempo(s, filtro, cursor, limite)
        linhas += pagina
        paginas += 1
        assert paginas < 100
        if cursor is None:
            return linhas


def test_mais_recente_primeiro_misturando_fontes(s):
    coleta = _coleta(s, T - timedelta(minutes=5))
    execucao = _execucao(s, T - timedelta(minutes=4))
    chamada = _chamada(s, T - timedelta(minutes=3))
    _aviso(s, T - timedelta(minutes=2))
    mensagem = _mensagem(s, T - timedelta(minutes=1))
    acao = _acao(s, T)
    linhas, proximo = linha_do_tempo(s, _filtro(), None)
    assert proximo is None
    assert [l.chave for l in linhas] == [
        f"acao_gestao:{acao.id}",
        f"mensagem_saida:{mensagem.id}",
        "estado_aviso:liga_desafio:geral",
        f"chamada_ia:{chamada.id}",
        f"execucao_manutencao:{execucao.id}",
        f"coleta:{coleta.id}",
    ]
    assert [l.o_que for l in linhas] == ["acao_gestao", "mensagem", "aviso", "ia", "backup", "coleta_liga"]
    assert [l.em for l in linhas] == sorted((l.em for l in linhas), reverse=True)


@pytest.mark.parametrize("limite", [1, 2, 3])
def test_cursor_com_dois_registros_no_mesmo_instante_nao_perde_nem_repete(s, limite):
    """Review Focus 3: empates no mesmo instante entre fontes e dentro da mesma fonte, cortados entre páginas."""
    chamadas = [_chamada(s, T), _chamada(s, T)]
    coletas = [_coleta(s, T), _coleta(s, T, tipo=TipoColeta.AMAZON)]
    mensagem = _mensagem(s, T)
    _aviso(s, T, chave="a")
    _aviso(s, T, chave="b")
    antiga = _chamada(s, T - timedelta(seconds=1))
    linhas = _todas(s, _filtro(), limite)
    chaves = [l.chave for l in linhas]
    esperadas = {
        *(f"chamada_ia:{c.id}" for c in [*chamadas, antiga]),
        *(f"coleta:{c.id}" for c in coletas),
        f"mensagem_saida:{mensagem.id}",
        "estado_aviso:liga_desafio:a",
        "estado_aviso:liga_desafio:b",
    }
    assert len(chaves) == len(set(chaves)) == len(esperadas)
    assert set(chaves) == esperadas
    assert chaves[-1] == f"chamada_ia:{antiga.id}"
    # a ordem é a mesma com qualquer tamanho de página
    assert chaves == [l.chave for l in linha_do_tempo(s, _filtro(), None, 50)[0]]


def test_cursor_invalido_levanta_valueerror(s):
    with pytest.raises(ValueError):
        linha_do_tempo(s, _filtro(), "isto-nao-e-cursor", 50)


def test_leitura_do_monitor_so_aparece_com_filtro_ou_busca(s):
    produto = criar_produto(s, "p1", nome="Caixa de Booster Fundações")
    anuncio = criar_anuncio(s, "B0LEITURA1", produto, status=StatusCasamento.CONFIRMADO)
    _leitura(s, anuncio, T)
    _coleta(s, T - timedelta(minutes=1))
    assert [l.o_que for l in linha_do_tempo(s, _filtro(), None)[0]] == ["coleta_liga"]
    assert [l.o_que for l in linha_do_tempo(s, _filtro(servico=Servico.AMAZON_MONITOR), None)[0]] == []
    so_leituras, _ = linha_do_tempo(s, _filtro(o_que="leitura_monitor"), None)
    assert [(l.o_que, l.asin, l.produto, l.situacao) for l in so_leituras] == [
        ("leitura_monitor", "B0LEITURA1", "Caixa de Booster Fundações", "ok")
    ]
    assert so_leituras[0].resultado == "2 ofertas · melhor R$ 300,00 (Loja X)"
    assert so_leituras[0].servico is Servico.AMAZON_MONITOR
    por_asin, _ = linha_do_tempo(s, _filtro(busca="leitura1"), None)
    assert [l.o_que for l in por_asin] == ["leitura_monitor"]
    por_nome, _ = linha_do_tempo(s, _filtro(busca="fundações"), None)
    assert [l.o_que for l in por_nome] == ["leitura_monitor"]


def test_produto_certo_por_linha_no_monitor_e_no_checkout(s):
    """Review Focus 4: dois anúncios de produtos diferentes; cada linha mostra o produto do seu anúncio."""
    p1 = criar_produto(s, "p1", nome="Produto Um")
    p2 = criar_produto(s, "p2", nome="Produto Dois")
    a1 = criar_anuncio(s, "B0PRODUM01", p1, status=StatusCasamento.CONFIRMADO)
    a2 = criar_anuncio(s, "B0PRODDOI2", p2, status=StatusCasamento.CONFIRMADO)
    _leitura(s, a1, T - timedelta(minutes=4))
    _leitura(s, a2, T - timedelta(minutes=3))
    _conferencia(s, a1, T - timedelta(minutes=2))
    _conferencia(s, a2, T - timedelta(minutes=1))
    leituras, _ = linha_do_tempo(s, _filtro(o_que="leitura_monitor"), None)
    conferencias, _ = linha_do_tempo(s, _filtro(o_que="checkout"), None)
    assert [(l.asin, l.produto, l.produto_id) for l in leituras] == [
        ("B0PRODDOI2", "Produto Dois", p2.id), ("B0PRODUM01", "Produto Um", p1.id)
    ]
    assert [(l.asin, l.produto, l.produto_id) for l in conferencias] == [
        ("B0PRODDOI2", "Produto Dois", p2.id), ("B0PRODUM01", "Produto Um", p1.id)
    ]


def test_reinicios_escondidos_por_padrao(s):
    interrompida = _coleta(s, T - timedelta(minutes=3), status=StatusColeta.FALHA, erro="interrompida")
    falha = _coleta(s, T - timedelta(minutes=2), status=StatusColeta.FALHA, erro="layout mudou")
    backup = _execucao(s, T - timedelta(minutes=1), status=StatusManutencao.INTERROMPIDA)
    padrao, _ = linha_do_tempo(s, _filtro(), None)
    assert [l.chave for l in padrao] == [f"coleta:{falha.id}"]
    com_reinicios, _ = linha_do_tempo(s, _filtro(mostrar_reinicios=True), None)
    assert [l.chave for l in com_reinicios] == [
        f"execucao_manutencao:{backup.id}", f"coleta:{falha.id}", f"coleta:{interrompida.id}"
    ]
    assert {l.situacao for l in com_reinicios} == {"falha"}


def test_filtro_problemas_traz_falha_e_parcial(s):
    _coleta(s, T - timedelta(minutes=4))
    parcial = _coleta(s, T - timedelta(minutes=3), status=StatusColeta.PARCIAL, ok=512, falha=279)
    falha = _chamada(s, T - timedelta(minutes=2), ok=False, erro="timeout")
    _chamada(s, T - timedelta(minutes=1))
    _acao(s, T)
    problemas, _ = linha_do_tempo(s, _filtro(situacao="problemas"), None)
    assert [(l.chave, l.situacao) for l in problemas] == [
        (f"chamada_ia:{falha.id}", "falha"), (f"coleta:{parcial.id}", "parcial")
    ]
    assert [l.chave for l in linha_do_tempo(s, _filtro(situacao="parcial"), None)[0]] == [f"coleta:{parcial.id}"]
    assert len(linha_do_tempo(s, _filtro(situacao="ok"), None)[0]) == 3


def test_problemas_nao_traz_leitura_ok_do_monitor(s):
    anuncio = criar_anuncio(s, "B0PROBLEM1")
    _leitura(s, anuncio, T - timedelta(minutes=1))  # com melhor oferta: ok
    s.add(OfertaAmazon(
        anuncio_id=anuncio.id, lida_em=T, preco=Decimal("400.00"), condicao="usado", envio=Envio.FBA,
        importada=False, prime=False, elegivel=False, melhor=False,
    ))  # nenhuma elegível: parcial
    s.flush()
    for filtro in (_filtro(o_que="leitura_monitor", situacao="problemas"), _filtro(busca="problem1", situacao="problemas")):
        assert [(l.em, l.situacao) for l in linha_do_tempo(s, filtro, None)[0]] == [(T, "parcial")]


def test_cursor_em_duas_leituras_no_mesmo_instante(s):
    a1, a2 = criar_anuncio(s, "B0MESMO001"), criar_anuncio(s, "B0MESMO002")
    _leitura(s, a1, T)
    _leitura(s, a2, T)
    linhas = _todas(s, _filtro(o_que="leitura_monitor"), 1)
    assert [l.asin for l in linhas] == ["B0MESMO002", "B0MESMO001"]


def test_busca_por_asin_e_por_nome(s):
    p1 = criar_produto(s, "p1", nome="Caixa de Booster Fundações")
    p1.nome_en = "Foundations Booster Box"
    p2 = criar_produto(s, "p2", nome="Deck Comandante")
    a1 = criar_anuncio(s, "B0BUSCA001", p1, status=StatusCasamento.CONFIRMADO)
    a2 = criar_anuncio(s, "B0OUTRO002", p2, status=StatusCasamento.CONFIRMADO)
    c1 = _conferencia(s, a1, T - timedelta(minutes=3))
    _conferencia(s, a2, T - timedelta(minutes=2))
    _leitura(s, a2, T - timedelta(minutes=2))
    msg = _mensagem(s, T - timedelta(minutes=1), texto="*Oportunidade*\nDeck Comandante 50%")
    erro = _coleta(s, T, status=StatusColeta.FALHA, erro="Timeout na página B0BUSCA001")
    assert [l.chave for l in linha_do_tempo(s, _filtro(busca="B0BUSCA001"), None)[0]] == [
        f"coleta:{erro.id}", f"conferencia_checkout:{c1.id}"
    ]
    assert [l.chave for l in linha_do_tempo(s, _filtro(busca="busca0"), None)[0]] == [
        f"coleta:{erro.id}", f"conferencia_checkout:{c1.id}"
    ]
    assert [l.chave for l in linha_do_tempo(s, _filtro(busca="FUNDAÇÕES"), None)[0]] == [f"conferencia_checkout:{c1.id}"]
    assert [l.chave for l in linha_do_tempo(s, _filtro(busca="foundations"), None)[0]] == [
        f"conferencia_checkout:{c1.id}"
    ]
    comandante = [l.o_que for l in linha_do_tempo(s, _filtro(busca="comandante"), None)[0]]
    assert comandante == ["mensagem", "leitura_monitor", "checkout"]  # empate: a fonte desempata
    # `%` e `_` valem como texto, não como curinga: só a mensagem tem "%"
    assert [l.chave for l in linha_do_tempo(s, _filtro(busca="%"), None)[0]] == [f"mensagem_saida:{msg.id}"]
    assert linha_do_tempo(s, _filtro(busca="_"), None)[0] == []


def test_filtro_por_servico(s):
    liga = _coleta(s, T - timedelta(minutes=5))
    busca = _coleta(s, T - timedelta(minutes=4), tipo=TipoColeta.AMAZON)
    chamada = _chamada(s, T - timedelta(minutes=3))
    _aviso(s, T - timedelta(minutes=2), tipo="liga_desafio")
    _aviso(s, T - timedelta(minutes=2), tipo="servico_sem_sinal", chave="casador")
    acao_liga = _acao(s, T - timedelta(minutes=1))
    _acao(s, T, tipo=TipoAcaoGestao.CATALOGO_LOTE, detalhe={"acao": "ligar", "ids": [1], "alvo": 1, "alterados": 1})

    def chaves(servico):
        return [l.chave for l in linha_do_tempo(s, _filtro(servico=servico), None)[0]]

    assert chaves(Servico.LIGA) == [f"acao_gestao:{acao_liga.id}", "estado_aviso:liga_desafio:geral", f"coleta:{liga.id}"]
    assert chaves(Servico.AMAZON_BUSCA) == [f"coleta:{busca.id}"]
    assert chaves(Servico.CASADOR) == ["estado_aviso:servico_sem_sinal:casador", f"chamada_ia:{chamada.id}"]
    todas = linha_do_tempo(s, _filtro(), None)[0]
    assert {l.chave: l.servico for l in todas}[f"coleta:{busca.id}"] is Servico.AMAZON_BUSCA
    assert [l.servico for l in todas if l.o_que == "acao_gestao"] == [None, Servico.LIGA]
    assert [l.o_que for l in linha_do_tempo(s, _filtro(o_que="busca"), None)[0]] == ["busca"]


def test_resultado_em_portugues_da_ia_e_do_checkout(s):
    produto = criar_produto(s, "p1", nome="Produto Um")
    anuncio = criar_anuncio(s, "B0RESULT01", produto)
    chamada = _chamada(s, T - timedelta(minutes=3))
    s.add(AvaliacaoIA(
        anuncio_id=anuncio.id, produto_id=produto.id, mesmo_produto=True, confianca=85, motivo="mesma caixa",
        modelo="gpt-teste", assinatura="x", sem_imagem=False, avaliado_em=chamada.em, chamada_id=chamada.id,
    ))
    falhou = _chamada(s, T - timedelta(minutes=2), ok=False, erro="Timeout\nlinha 2 do erro")
    sem_frete = _conferencia(s, anuncio, T - timedelta(minutes=1))
    com_frete = _conferencia(s, anuncio, T, frete="15.00")
    parcial = _coleta(s, T - timedelta(minutes=4), status=StatusColeta.PARCIAL, ok=512, falha=279)
    s.flush()
    linhas = {l.chave: l for l in linha_do_tempo(s, _filtro(), None)[0]}
    ia = linhas[f"chamada_ia:{chamada.id}"]
    assert ia.resultado == "mesmo 85% · ficou para você"
    assert (ia.produto, ia.asin, ia.custo_usd) == ("Produto Um", "B0RESULT01", Decimal("0.012345"))
    assert ia.detalhe["motivo"] == "mesma caixa"
    assert linhas[f"chamada_ia:{falhou.id}"].resultado == "erro · Timeout"
    assert linhas[f"chamada_ia:{falhou.id}"].detalhe["erro"] == "Timeout\nlinha 2 do erro"
    assert linhas[f"conferencia_checkout:{sem_frete.id}"].resultado == "R$ 309,83 com impostos"
    assert linhas[f"conferencia_checkout:{com_frete.id}"].resultado == "R$ 309,83 com impostos · frete R$ 15,00 à parte"
    assert linhas[f"coleta:{parcial.id}"].resultado == "parcial · 512 de 791"


def test_chamada_sem_avaliacao_diz_o_que_era(s):
    termos = _chamada(s, T - timedelta(minutes=2), finalidade="termos")
    idioma = _chamada(s, T - timedelta(minutes=1), finalidade="idioma")
    casamento = _chamada(s, T)
    s.flush()
    linhas = {l.chave: l for l in linha_do_tempo(s, _filtro(), None)[0]}
    assert linhas[f"chamada_ia:{termos.id}"].resultado == "termos de busca gerados"
    assert linhas[f"chamada_ia:{idioma.id}"].resultado == "idioma consultado"
    assert linhas[f"chamada_ia:{casamento.id}"].resultado == "avaliação feita"


def test_ia_que_o_automatico_aplicou_diz_o_que_fez(s):
    produto = criar_produto(s, "p1")
    anuncio = criar_anuncio(s, "B0AUTOMAT1", produto)
    chamada = _chamada(s, T)
    s.add(AvaliacaoIA(
        anuncio_id=anuncio.id, produto_id=produto.id, mesmo_produto=False, confianca=95, motivo="outra edição",
        modelo="gpt-teste", assinatura="x", sem_imagem=False, avaliado_em=T, chamada_id=chamada.id,
        aplicada_em=T + timedelta(seconds=1),
    ))
    s.flush()
    assert linha_do_tempo(s, _filtro(), None)[0][0].resultado == "outro 95% · ignorado sozinho"


def test_acao_de_gestao_traz_o_nome_do_usuario(s):
    ana = repo_acesso.criar_usuario(s, "Ana", "+5511900000009", Papel.ADMIN, T)
    com_usuario = _acao(s, T, usuario_id=ana.id)
    sem_usuario = _acao(s, T - timedelta(minutes=1))
    linhas = {l.chave: l for l in linha_do_tempo(s, _filtro(o_que="acao_gestao"), None)[0]}
    assert linhas[f"acao_gestao:{com_usuario.id}"].detalhe["usuario"] == "Ana"
    assert linhas[f"acao_gestao:{sem_usuario.id}"].detalhe["usuario"] == "admin antigo"
    assert linhas[f"acao_gestao:{com_usuario.id}"].resultado.startswith("Ana · ")
    assert linha_do_tempo(s, _filtro(busca="ana"), None)[0][0].chave == f"acao_gestao:{com_usuario.id}"


def test_mensagem_traz_texto_e_situacao_no_detalhe(s):
    m = _mensagem(s, T, status=StatusMensagem.FALHA, texto="*Aviso*\nTexto completo", erro="400 grupo")
    [linha], _ = linha_do_tempo(s, _filtro(o_que="mensagem"), None)
    assert linha.situacao == "falha" and linha.servico is Servico.WHATSAPP
    assert linha.detalhe["texto"] == "*Aviso*\nTexto completo"
    assert (linha.detalhe["mensagem_id"], linha.detalhe["status"]) == (m.id, "falha")


def test_periodo(s):
    _coleta(s, T - timedelta(days=2))
    dentro = _coleta(s, T - timedelta(days=1))
    _coleta(s, T)
    filtro = _filtro(de=T - timedelta(days=1, hours=1), ate=T - timedelta(hours=1))
    assert [l.chave for l in linha_do_tempo(s, filtro, None)[0]] == [f"coleta:{dentro.id}"]


def test_mensagem_individual_nao_mostra_nem_busca_o_texto(s):
    m = MensagemSaida(
        destino="individual", numero="+5511900000009", texto="Seu código: 123456", status=StatusMensagem.ENVIADA,
        proxima_tentativa_em=T, criada_em=T, atualizado_em=T, enviada_em=T,
    )
    s.add(m)
    s.flush()
    [linha], _ = linha_do_tempo(s, _filtro(o_que="mensagem"), None)
    assert linha.detalhe["texto"] is None and "123456" not in linha.resultado
    assert "+5511900000009" not in str(linha)
    assert linha_do_tempo(s, _filtro(busca="123456"), None)[0] == []


def test_sem_mostrar_texto_da_mensagem_nao_traz_nem_busca_o_texto(s):
    _mensagem(s, T, status=StatusMensagem.FALHA, texto="*Aviso*\nCaixa Azul", erro="400 grupo")
    filtro = _filtro(o_que="mensagem", mostrar_texto_mensagem=False)
    [linha], _ = linha_do_tempo(s, filtro, None)
    assert linha.detalhe["texto"] is None
    assert "Azul" not in linha.resultado and "Aviso" not in linha.resultado
    assert linha.resultado == "falha · grupo de oportunidades"
    assert linha_do_tempo(s, _filtro(mostrar_texto_mensagem=False, busca="Azul"), None)[0] == []
    # o erro continua pesquisável, e com a permissão o texto volta
    assert len(linha_do_tempo(s, _filtro(mostrar_texto_mensagem=False, busca="400 grupo"), None)[0]) == 1
    assert len(linha_do_tempo(s, _filtro(busca="Azul"), None)[0]) == 1


def test_acao_de_configuracoes_diz_o_que_mudou(s):
    um = _acao(s, T - timedelta(minutes=3), tipo=TipoAcaoGestao.CONFIGURACOES,
               detalhe={"campos": {"amazon.desconto_min_pct": [20, 22]}})
    varios = _acao(s, T - timedelta(minutes=2), tipo=TipoAcaoGestao.CONFIGURACOES, detalhe={"campos": {
        "amazon.desconto_min_pct": [20, 22], "ia.automatico": [False, True],
        "geral.whatsapp_grupo_admin": [None, "1@g.us"], "ia.lote": [20, 30], "sumiu.campo": [1, 2],
    }})
    desligou = _acao(s, T - timedelta(minutes=1), tipo=TipoAcaoGestao.CONFIGURACOES,
                     detalhe={"aviso": "liga_desafio", "ligado": False})
    ligou = _acao(s, T, tipo=TipoAcaoGestao.CONFIGURACOES, detalhe={"aviso": "sumiu", "ligado": True})
    siglas = _acao(s, T - timedelta(minutes=4), tipo=TipoAcaoGestao.CONFIGURACOES, detalhe={"campos": {
        "amazon.url_busca": ["a", "b"], "ia.ligado": [False, True], "geral.host_publico": ["x", "y"],
    }})
    linhas = {l.chave: l.resultado for l in linha_do_tempo(s, _filtro(o_que="acao_gestao"), None)[0]}
    assert linhas[f"acao_gestao:{um.id}"] == "admin antigo · salvou 1 campo: desconto mínimo sobre a Liga (%) 20→22"
    assert linhas[f"acao_gestao:{varios.id}"] == (
        "admin antigo · salvou 5 campos: desconto mínimo sobre a Liga (%) 20→22, automático não→sim, "
        "grupo de WhatsApp do admin vazio→1@g.us e mais 2"
    )
    assert linhas[f"acao_gestao:{desligou.id}"] == "admin antigo · desligou o aviso Liga · desafio do Cloudflare"
    assert linhas[f"acao_gestao:{ligou.id}"] == "admin antigo · ligou o aviso sumiu"
    assert linhas[f"acao_gestao:{siglas.id}"] == (
        "admin antigo · salvou 3 campos: URL da busca a→b, IA ligada não→sim, IP ou nome deste PC na rede x→y"
    )


def test_situacao_pendente_traz_so_mensagens_pendentes(s):
    _coleta(s, T, status=StatusColeta.PARCIAL)
    pendente = _mensagem(s, T - timedelta(minutes=1), status=StatusMensagem.PENDENTE)
    _mensagem(s, T - timedelta(minutes=2), status=StatusMensagem.EXPIRADA)
    _mensagem(s, T - timedelta(minutes=3), status=StatusMensagem.FALHA)
    linhas, _ = linha_do_tempo(s, _filtro(situacao="pendente"), None)
    assert [l.chave for l in linhas] == [f"mensagem_saida:{pendente.id}"]
    assert linha_do_tempo(s, _filtro(situacao="pendente", o_que="coleta_liga"), None)[0] == []


def test_filtro_destino_traz_so_mensagens_do_destino(s):
    _coleta(s, T)
    admin = _mensagem(s, T - timedelta(minutes=1), destino="admin")
    _mensagem(s, T - timedelta(minutes=2), destino="oportunidades")
    individual = _mensagem(s, T - timedelta(minutes=3), destino="individual")
    assert [l.chave for l in linha_do_tempo(s, _filtro(destino="admin"), None)[0]] == [f"mensagem_saida:{admin.id}"]
    assert [l.chave for l in linha_do_tempo(s, _filtro(destino="individual"), None)[0]] == [
        f"mensagem_saida:{individual.id}"
    ]
    assert linha_do_tempo(s, _filtro(destino="admin", situacao="falha"), None)[0] == []


def test_destino_individual_nao_mostra_nem_busca_o_texto(s):
    _mensagem(s, T, texto="*Código*\nPalavraSecreta", destino="individual")
    for mostrar in (True, False):
        [linha], _ = linha_do_tempo(s, _filtro(destino="individual", mostrar_texto_mensagem=mostrar), None)
        assert linha.detalhe["texto"] is None
        assert "texto oculto" in linha.resultado
        assert "PalavraSecreta" not in linha.resultado
        assert linha_do_tempo(s, _filtro(destino="individual", busca="PalavraSecreta", mostrar_texto_mensagem=mostrar), None)[0] == []
