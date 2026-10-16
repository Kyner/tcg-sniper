from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fakes import criar_anuncio, criar_preco_liga, criar_produto

from tcg_sniper.admin import consultas_painel as painel
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    COLETOR_CASADOR,
    COLETOR_LIGA,
    COLETOR_NOTIFICADOR,
    AvaliacaoIA,
    Envio,
    OrigemPreco,
    StatusCasamento,
    StatusColeta,
    StatusMensagem,
    TipoColeta,
)

AGORA = datetime(2026, 10, 16, 19, 40, tzinfo=UTC)  # 16:40 em São Paulo


def saude(s, config, agora=AGORA, chave_ia=True):
    return {x.nome: x for x in painel.saude_servicos(s, agora, config, chave_ia)}


def coleta(s, tipo, quando, status=StatusColeta.OK, ok=1, falha=0, erro=None):
    c = repo.iniciar_coleta(s, tipo, quando)
    if status is not StatusColeta.RODANDO:
        repo.finalizar_coleta(s, c.id, status, ok, falha, quando + timedelta(minutes=18), erro)
    return c


def test_quatro_servicos_na_ordem(s, config):
    nomes = [x.nome for x in painel.saude_servicos(s, AGORA, config, True)]
    assert nomes == ["LigaMagic", "Amazon", "Casador (IA)", "WhatsApp"]


def test_liga_funcionando_com_a_ultima_coleta_e_a_proxima(s, config):
    coleta(s, TipoColeta.LISTAGEM, AGORA - timedelta(hours=9))
    produto = criar_produto(s, "p1")
    criar_preco_liga(s, produto, "10.00")
    criar_produto(s, "p2")
    liga = saude(s, config)["LigaMagic"]
    assert (liga.situacao, liga.rotulo) == ("ok", "funcionando")
    assert liga.texto == "Última coleta ok hoje 07:40"
    assert "Próxima amanhã por volta das 10:00 (± 30 min)" in liga.detalhe
    assert "1 de 2 com preço" in liga.detalhe


def test_liga_sem_coleta_hoje_proxima_hoje(s, config):
    liga = saude(s, config, agora=datetime(2026, 10, 16, 11, 0, tzinfo=UTC))["LigaMagic"]  # 08:00 em SP
    assert liga.texto == "Nenhuma coleta ainda" and "Próxima hoje por volta das 10:00" in liga.detalhe


@pytest.mark.parametrize(
    ("preparar", "situacao", "trecho"),
    [
        (lambda s: repo.pausar_por_desafio(s, "desafio em /x", AGORA), "pausado_desafio", "desafio em /x"),
        (lambda s: repo.pausar(s, "pausado no admin", AGORA, COLETOR_LIGA), "pausado", "pausado no admin"),
        (lambda s: coleta(s, TipoColeta.LISTAGEM, AGORA, StatusColeta.RODANDO), "rodando", "Coleta em andamento"),
        (lambda s: coleta(s, TipoColeta.PRODUTOS, AGORA - timedelta(hours=1), StatusColeta.FALHA), "parcial", "falhou"),
    ],
)
def test_liga_por_estado(s, config, preparar, situacao, trecho):
    preparar(s)
    liga = saude(s, config)["LigaMagic"]
    assert liga.situacao == situacao and trecho in liga.texto + " " + liga.detalhe


def test_liga_rotulos(s, config):
    repo.pausar_por_desafio(s, "x", AGORA)
    assert saude(s, config)["LigaMagic"].rotulo == "desafio pendente"
    repo.pausar(s, "pausado no admin", AGORA, COLETOR_LIGA)
    assert saude(s, config)["LigaMagic"].rotulo == "pausado"


def test_amazon(s, config):
    amazon = saude(s, config)["Amazon"]
    assert amazon.situacao == "ok" and amazon.texto == "Nenhum ciclo ainda"
    assert amazon.detalhe == "0 preços lidos nas últimas 24 h"
    noite = saude(s, config, agora=datetime(2026, 10, 17, 2, 0, tzinfo=UTC))["Amazon"]  # 23:00 em SP
    assert noite.situacao == "ok" and "fora do horário (08:00–22:00)" in noite.texto
    coleta(s, TipoColeta.AMAZON, AGORA - timedelta(hours=3))
    coleta(s, TipoColeta.AMAZON, AGORA - timedelta(minutes=30), StatusColeta.RODANDO)
    amazon = saude(s, config)["Amazon"]
    assert amazon.situacao == "rodando" and amazon.texto == "Ciclo desde 16:10 · último ok 13:40"
    repo.pausar(s, "pausado no admin", AGORA, COLETOR_AMAZON)
    assert saude(s, config)["Amazon"].situacao == "pausado"
    repo.pausar_por_desafio(s, "captcha", AGORA, COLETOR_AMAZON)
    assert saude(s, config)["Amazon"].situacao == "pausado_desafio"


def test_amazon_conta_precos_lidos_nas_ultimas_24h(s, config):
    produto = criar_produto(s, "p1")
    for i, asin in enumerate(("B000000001", "B000000002")):
        anuncio = criar_anuncio(s, asin, produto)
        quando = AGORA - timedelta(hours=1 if i == 0 else 30)
        repo_amz.registrar_preco(
            s, anuncio.id, Decimal(10), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, quando, config.zona
        )
    assert saude(s, config)["Amazon"].detalhe == "1 preços lidos nas últimas 24 h"


def test_casador(s, config):
    casador = saude(s, config)["Casador (IA)"]
    assert (casador.situacao, casador.rotulo) == ("inativo", "desligada")
    repo_ia.salvar_config_ia(s, {"ligado": True, "modelo": "gpt-5-mini"}, AGORA)
    sem_chave = saude(s, config, chave_ia=False)["Casador (IA)"]
    assert (sem_chave.situacao, sem_chave.rotulo) == ("pausado", "sem chave")
    repo_ia.registrar_chamada(
        s, em=AGORA - timedelta(minutes=3), finalidade="casamento", modelo="gpt-5-mini", tokens_entrada=1,
        tokens_saida=1, custo_usd=Decimal("0.07"), ok=True, erro=None,
    )
    casador = saude(s, config)["Casador (IA)"]
    assert casador.situacao == "ok"
    assert casador.texto == "Última chamada hoje 16:37 · automático desligado"
    assert casador.detalhe == "gpt-5-mini · US$ 0,07 de US$ 2,00 hoje"
    repo.pausar(s, "chave recusada pela OpenAI (401)", AGORA, COLETOR_CASADOR)
    casador = saude(s, config)["Casador (IA)"]
    assert casador.situacao == "pausado" and "chave recusada" in casador.texto


def test_whatsapp(s, config):
    whatsapp = saude(s, config)["WhatsApp"]
    assert (whatsapp.situacao, whatsapp.rotulo) == ("falha", "parado") and "nunca rodou" in whatsapp.texto
    repo_msg.registrar_ciclo(s, AGORA - timedelta(minutes=5))
    assert "parado desde" in saude(s, config)["WhatsApp"].texto
    repo_msg.registrar_ciclo(s, AGORA - timedelta(seconds=20))
    m = repo_msg.enfileirar(s, "admin", "x", AGORA - timedelta(hours=1))
    m.status, m.enviada_em = StatusMensagem.ENVIADA, AGORA - timedelta(hours=1)
    repo_msg.enfileirar(s, "admin", "parada", AGORA - timedelta(hours=1))
    falha = repo_msg.enfileirar(s, "admin", "y", AGORA)
    falha.status = StatusMensagem.FALHA
    s.flush()
    whatsapp = saude(s, config)["WhatsApp"]
    assert whatsapp.situacao == "ok" and whatsapp.texto.startswith("Notificador vivo")
    assert whatsapp.detalhe == "1 enviadas hoje · 1 com falha · 1 paradas"
    repo.pausar(s, "pausado no admin", AGORA, COLETOR_NOTIFICADOR)
    assert saude(s, config)["WhatsApp"].situacao == "pausado"


def test_avisos(s, config):
    repo_msg.registrar_ciclo(s, AGORA)
    assert painel.avisos(s, AGORA, config, True) == []
    repo.pausar(s, "pausado no admin", AGORA, COLETOR_LIGA)
    coleta(s, TipoColeta.AMAZON, AGORA - timedelta(hours=2), StatusColeta.FALHA, erro="interrompida")
    m = repo_msg.enfileirar(s, "admin", "x", AGORA)
    m.status = StatusMensagem.FALHA
    s.flush()
    avisos = painel.avisos(s, AGORA, config, True)
    links = [a.link for a in avisos]
    assert links == ["/servicos", "/mensagens?situacao=falha", "/logs?aba=amazon"]
    assert "LigaMagic" in avisos[0].texto and "pausado no admin" in avisos[0].texto
    assert "interrompida" in avisos[2].texto


def test_aviso_do_notificador_parado(s, config):
    avisos = painel.avisos(s, AGORA, config, True)
    assert [a.texto for a in avisos] == ["O notificador nunca rodou — veja Serviços."]


def test_numeros_de_casamentos_e_ia(s, config):
    ativo, inativo = criar_produto(s, "p1"), criar_produto(s, "p2", ativo=False)
    confirmado = criar_anuncio(s, "B000000001", ativo, StatusCasamento.CONFIRMADO)
    pendente = criar_anuncio(s, "B000000002", ativo)
    pendente2 = criar_anuncio(s, "B000000003", inativo)
    criar_anuncio(s, "B000000004", ativo, StatusCasamento.IGNORADO)
    criar_anuncio(s, "B000000005", None)  # sem produto: não conta
    for anuncio, mesmo, aplicada in ((confirmado, True, AGORA), (pendente, True, None), (pendente2, False, None)):
        s.add(AvaliacaoIA(
            anuncio_id=anuncio.id, produto_id=anuncio.produto_id, mesmo_produto=mesmo, confianca=80, motivo="m",
            modelo="gpt-5", assinatura="a", sem_imagem=False, avaliado_em=AGORA, aplicada_em=aplicada,
        ))
    s.flush()
    n = painel.numeros(s, AGORA, config)
    assert (n.confirmados, n.pendentes, n.ignorados) == (1, 2, 1)
    assert (n.produtos_com_par, n.produtos_ativos, n.produtos_total) == (1, 1, 2)
    assert (n.avaliados, n.pelo_automatico, n.esperando_voce) == (3, 1, 1)
    assert n.teto_mes == Decimal("20.00")


def test_numeros_de_oportunidades(s, config):
    produto = criar_produto(s, "p1")
    for i, (alertada, fechada, desconto) in enumerate(
        ((AGORA - timedelta(hours=1), None, "30"), (AGORA - timedelta(days=3), AGORA, "40"),
         (AGORA - timedelta(days=10), AGORA, "50"), (AGORA - timedelta(hours=2), None, "27.5"))
    ):
        anuncio = criar_anuncio(s, f"B00000000{i}", produto, StatusCasamento.CONFIRMADO)
        op = repo_amz.abrir_oportunidade(
            s, anuncio_id=anuncio.id, produto_id=produto.id, preco_amazon=Decimal(70), preco_liga=Decimal(100),
            desconto_pct=Decimal(desconto), vendedor_id=None, envio=Envio.AMAZON, agora=alertada,
        )
        op.fechada_em = fechada
    s.flush()
    n = painel.numeros(s, AGORA, config)
    assert (n.abertas, n.alertas_hoje, n.alertas_semana) == (2, 2, 3)
    assert n.maior_desconto == Decimal(30) and n.desconto_min == 25


def test_atividade_de_hoje(s, config):
    ontem = AGORA - timedelta(days=1)
    coleta(s, TipoColeta.LISTAGEM, ontem)
    coleta(s, TipoColeta.LISTAGEM, AGORA - timedelta(hours=6, minutes=26))  # 10:14 em SP
    coleta(s, TipoColeta.PRODUTOS, AGORA - timedelta(hours=6, minutes=8))  # 10:32
    coleta(s, TipoColeta.AMAZON, AGORA - timedelta(hours=2))
    repo_ia.registrar_chamada(
        s, em=AGORA, finalidade="casamento", modelo="m", tokens_entrada=1, tokens_saida=1,
        custo_usd=Decimal(0), ok=False, erro="x",
    )
    itens = {i.rotulo: i for i in painel.atividade_hoje(s, AGORA, config)}
    assert list(itens) == ["Coleta da LigaMagic", "Buscas na Amazon", "Chamadas da IA", "Mensagens do WhatsApp"]
    assert itens["Coleta da LigaMagic"].texto == "listagem 10:14 · produtos 10:32"
    assert itens["Coleta da LigaMagic"].situacao == "ok"
    assert itens["Buscas na Amazon"].texto == "1 ciclos · 0 preços"
    assert (itens["Chamadas da IA"].texto, itens["Chamadas da IA"].situacao) == ("1 · 1 com erro", "falha")
    assert (itens["Mensagens do WhatsApp"].texto, itens["Mensagens do WhatsApp"].situacao) == (
        "0 enviadas · 0 falhas", "nenhum",
    )
