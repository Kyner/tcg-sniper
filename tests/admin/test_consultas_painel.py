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
    COLETOR_AMAZON_BUSCA,
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


def avisos_de(s, config, agora=AGORA):
    resumo = painel.consultas_mensagens.resumo(s, agora)
    return painel.avisos(s, agora, config, painel.saude_servicos(s, agora, config, True, resumo), resumo)


def coleta(s, tipo, quando, status=StatusColeta.OK, ok=1, falha=0, erro=None):
    c = repo.iniciar_coleta(s, tipo, quando)
    if status is not StatusColeta.RODANDO:
        repo.finalizar_coleta(s, c.id, status, ok, falha, quando + timedelta(minutes=18), erro)
    return c


def test_cinco_servicos_na_ordem(s, config):
    nomes = [x.nome for x in painel.saude_servicos(s, AGORA, config, True)]
    assert nomes == ["LigaMagic", "Amazon (busca)", "Amazon (monitor e checkout)", "Casador (IA)", "WhatsApp"]


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


def test_amazon_busca(s, config):
    busca = saude(s, config)["Amazon (busca)"]
    assert busca.situacao == "ok" and busca.texto == "Nenhum ciclo ainda"
    noite = saude(s, config, agora=datetime(2026, 10, 17, 2, 0, tzinfo=UTC))["Amazon (busca)"]  # 23:00 em SP
    assert noite.situacao == "ok" and "fora do horário (08:00–22:00)" in noite.texto
    coleta(s, TipoColeta.AMAZON, AGORA - timedelta(hours=3))
    coleta(s, TipoColeta.AMAZON, AGORA - timedelta(minutes=30), StatusColeta.RODANDO)
    busca = saude(s, config)["Amazon (busca)"]
    assert busca.situacao == "rodando" and busca.texto == "Ciclo desde 16:10 · último ok 13:40"
    repo.pausar(s, "pausado no admin", AGORA, COLETOR_AMAZON_BUSCA)
    assert saude(s, config)["Amazon (busca)"].situacao == "pausado"
    assert saude(s, config)["Amazon (monitor e checkout)"].situacao == "ok"
    repo.pausar_por_desafio(s, "captcha", AGORA, COLETOR_AMAZON_BUSCA)
    busca = saude(s, config)["Amazon (busca)"]
    assert busca.situacao == "pausado_desafio" and "6082" in busca.detalhe


def test_amazon_busca_conta_buscas_na_ultima_hora_e_nunca_buscados(s, config):
    feitos = [criar_produto(s, f"p{i}") for i in range(4)]
    criar_produto(s, "inativo", ativo=False)
    repo_amz.sincronizar_fila(s, AGORA - timedelta(hours=3))
    repo_amz.reagendar(s, feitos[0].id, AGORA - timedelta(minutes=10), AGORA + timedelta(hours=1), False)
    repo_amz.reagendar(s, feitos[1].id, AGORA - timedelta(hours=2), AGORA + timedelta(hours=1), False)
    detalhe = saude(s, config)["Amazon (busca)"].detalhe
    assert detalhe == "1 buscas na última hora · 2 produtos ativos nunca buscados"


def test_amazon_monitor(s, config):
    monitor = saude(s, config)["Amazon (monitor e checkout)"]
    assert monitor.situacao == "ok" and monitor.detalhe.startswith("0 preços lidos nas últimas 24 h")
    noite = saude(s, config, agora=datetime(2026, 10, 17, 2, 0, tzinfo=UTC))["Amazon (monitor e checkout)"]
    assert "fora do horário (08:00–22:00)" in noite.texto
    repo.pausar(s, "pausado no admin", AGORA, COLETOR_AMAZON)
    assert saude(s, config)["Amazon (monitor e checkout)"].situacao == "pausado"
    assert saude(s, config)["Amazon (busca)"].situacao == "ok"
    repo.pausar_por_desafio(s, "captcha", AGORA, COLETOR_AMAZON)
    monitor = saude(s, config)["Amazon (monitor e checkout)"]
    assert monitor.situacao == "pausado_desafio" and "6081" in monitor.detalhe


def test_amazon_monitor_conta_precos_lidos_nas_ultimas_24h(s, config):
    produto = criar_produto(s, "p1")
    for i, asin in enumerate(("B000000001", "B000000002")):
        anuncio = criar_anuncio(s, asin, produto)
        quando = AGORA - timedelta(hours=1 if i == 0 else 30)
        repo_amz.registrar_preco(
            s, anuncio.id, Decimal(10), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, quando, config.zona
        )
    assert saude(s, config)["Amazon (monitor e checkout)"].detalhe.startswith("1 preços lidos nas últimas 24 h · ")


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
    assert avisos_de(s, config) == []
    repo.pausar(s, "pausado no admin", AGORA, COLETOR_LIGA)
    coleta(s, TipoColeta.AMAZON, AGORA - timedelta(hours=2), StatusColeta.FALHA, erro="interrompida")
    m = repo_msg.enfileirar(s, "admin", "x", AGORA)
    m.status = StatusMensagem.FALHA
    s.flush()
    avisos = avisos_de(s, config)
    links = [a.link for a in avisos]
    assert links == ["/servicos", "/mensagens?situacao=falha", "/logs?aba=amazon"]
    assert "LigaMagic" in avisos[0].texto and "pausado no admin" in avisos[0].texto
    assert "interrompida" in avisos[2].texto


def test_aviso_do_notificador_parado(s, config):
    avisos = avisos_de(s, config)
    assert [a.texto for a in avisos] == ["O notificador nunca rodou — veja Serviços."]


def test_numeros_de_casamentos_e_ia(s, config):
    ativo, inativo = criar_produto(s, "p1"), criar_produto(s, "p2", ativo=False)
    confirmado = criar_anuncio(s, "B000000001", ativo, StatusCasamento.CONFIRMADO)
    pendente = criar_anuncio(s, "B000000002", ativo)
    pendente2 = criar_anuncio(s, "B000000003", inativo)
    criar_anuncio(s, "B000000004", ativo, StatusCasamento.IGNORADO)
    criar_anuncio(s, "B000000005", None)  # sem produto: não conta
    for anuncio, produto, mesmo, aplicada in (
        (confirmado, ativo, True, AGORA), (pendente, ativo, True, None), (pendente2, inativo, False, None)
    ):
        s.add(AvaliacaoIA(
            anuncio_id=anuncio.id, produto_id=produto.id, mesmo_produto=mesmo, confianca=80, motivo="m",
            modelo="gpt-5", assinatura="a", sem_imagem=False, avaliado_em=AGORA, aplicada_em=aplicada,
        ))
    s.flush()
    n = painel.numeros(s, AGORA, config)
    c = n.catalogo  # por produto ativo: p1 tem confirmado, pendente e ignorado e conta uma vez, como casado
    assert (c.casado, c.esperando_decisao, c.so_ignorados, c.sem_candidato) == (1, 0, 0, 0)
    assert (n.produtos_ativos, n.produtos_total) == (1, 2)
    assert (c.produtos_avaliados, c.avaliacoes_total, c.media_por_produto) == (1, 2, 2.0)
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
            desconto_pct=Decimal(desconto), vendedor_id=None, envio=Envio.AMAZON, agora=alertada, conferido=False,
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
    assert itens["Buscas na Amazon"].texto == "1 ciclo · 0 preços"
    assert (itens["Chamadas da IA"].texto, itens["Chamadas da IA"].situacao) == (
        "1 · 1 com erro · 0 produtos avaliados", "falha",
    )
    assert (itens["Mensagens do WhatsApp"].texto, itens["Mensagens do WhatsApp"].situacao) == (
        "0 enviadas · 0 falhas", "nenhum",
    )


NOITE = datetime(2026, 10, 17, 1, 30, tzinfo=UTC)  # 22:30 em São Paulo, ainda dia 16


def test_alertas_de_hoje_usam_o_dia_do_fuso(s, config):
    produto = criar_produto(s, "p1")
    for i, alertada in enumerate((
        datetime(2026, 10, 16, 13, 0, tzinfo=UTC),  # 10:00 do dia 16 em SP: hoje
        datetime(2026, 10, 16, 2, 0, tzinfo=UTC),  # 23:00 do dia 15 em SP: ontem (dia 16 em UTC)
    )):
        anuncio = criar_anuncio(s, f"B00000000{i}", produto, StatusCasamento.CONFIRMADO)
        repo_amz.abrir_oportunidade(
            s, anuncio_id=anuncio.id, produto_id=produto.id, preco_amazon=Decimal(70), preco_liga=Decimal(100),
            desconto_pct=Decimal(30), vendedor_id=None, envio=Envio.AMAZON, agora=alertada, conferido=False,
        )
    n = painel.numeros(s, NOITE, config)
    assert (n.alertas_hoje, n.alertas_semana) == (1, 2)


def test_atividade_de_hoje_usa_o_dia_do_fuso(s, config):
    coleta(s, TipoColeta.LISTAGEM, datetime(2026, 10, 16, 2, 0, tzinfo=UTC))  # 23:00 do dia 15 em SP
    coleta(s, TipoColeta.PRODUTOS, datetime(2026, 10, 16, 13, 32, tzinfo=UTC))  # 10:32 do dia 16
    coleta(s, TipoColeta.AMAZON, datetime(2026, 10, 17, 0, 0, tzinfo=UTC))  # 21:00 do dia 16
    coleta(s, TipoColeta.AMAZON, datetime(2026, 10, 16, 2, 30, tzinfo=UTC))  # dia 15 em SP
    itens = {i.rotulo: i for i in painel.atividade_hoje(s, NOITE, config)}
    assert itens["Coleta da LigaMagic"].texto == "produtos 10:32"
    assert itens["Buscas na Amazon"].texto == "1 ciclo · 0 preços"


def test_liga_depois_do_horario_sem_coleta_comeca_em_instantes(s, config):
    liga = saude(s, config, agora=datetime(2026, 10, 16, 14, 0, tzinfo=UTC))["LigaMagic"]  # 11:00 em SP
    assert "Próxima começa em instantes" in liga.detalhe and "amanhã" not in liga.detalhe


def test_notificador_desligado_nao_avisa_mensagens_paradas(s, config):
    repo_msg.registrar_ciclo(s, AGORA)
    repo_msg.enfileirar(s, "admin", "x", AGORA - timedelta(hours=1))
    resumo = painel.consultas_mensagens.resumo(s, AGORA)
    assert [a.link for a in painel.avisos(s, AGORA, config, painel.saude_servicos(s, AGORA, config, True), resumo)] == [
        "/mensagens?situacao=pendente"
    ]
    repo.pausar(s, "pausado no admin", AGORA, COLETOR_NOTIFICADOR)
    resumo = painel.consultas_mensagens.resumo(s, AGORA, notificador_pausado=True)
    servicos = painel.saude_servicos(s, AGORA, config, True, resumo)
    whatsapp = servicos[4]
    assert whatsapp.texto == "Envio desligado; as mensagens ficam guardadas e saem quando ligar (ofertas vencidas expiram)"
    assert [a.link for a in painel.avisos(s, AGORA, config, servicos, resumo)] == ["/servicos"]


def test_liga_esfriando_no_dashboard(s, config):
    coleta(s, TipoColeta.PRODUTOS, AGORA - timedelta(hours=1), StatusColeta.PAUSADA_DESAFIO)  # fecha 18 min depois
    repo.retomar(s, AGORA - timedelta(minutes=10))
    liga = saude(s, config)["LigaMagic"]
    assert (liga.situacao, liga.rotulo, liga.texto) == ("parcial", "esfriando", "Esfriando até 17:00")
    assert "pausas em dobro" in liga.detalhe


def test_liga_parada_ate_amanha_no_dashboard(s, config):
    coleta(s, TipoColeta.PRODUTOS, AGORA - timedelta(hours=3), StatusColeta.PAUSADA_DESAFIO)
    coleta(s, TipoColeta.PRODUTOS, AGORA - timedelta(hours=1), StatusColeta.PAUSADA_DESAFIO)
    repo.retomar(s, AGORA - timedelta(minutes=30))
    liga = saude(s, config)["LigaMagic"]
    assert (liga.situacao, liga.rotulo, liga.texto) == ("parcial", "parada até amanhã", "Parada até amanhã (2º desafio)")
    assert "Próxima amanhã por volta das 10:00" in liga.detalhe
    assert not any("LigaMagic" in a.texto for a in avisos_de(s, config))  # atenção, não problema
