import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tcg_sniper.avisos import formato, servico
from tcg_sniper.avisos.catalogo import CATALOGO, CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.avisos.formato import UrlProibida
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import ConfigAviso, EstadoAviso, MensagemSaida, StatusMensagem

T = datetime(2026, 10, 18, 13, 0, tzinfo=UTC)  # 10:00 em São Paulo
CAPTCHA = TipoAviso.AMAZON_CAPTCHA


def saidas(sessoes):
    with sessoes() as s:
        return list(s.scalars(select(MensagemSaida).order_by(MensagemSaida.id)))


def avisar_em(sessoes, quando, tipo=CAPTCHA, chave=CHAVE_GERAL, dados=None):
    with sessoes() as s, s.begin():
        servico.avisar(s, tipo, chave, dados or CATALOGO[tipo].exemplo, quando)


def resolver_em(sessoes, quando, tipo=CAPTCHA, chave=CHAVE_GERAL):
    with sessoes() as s, s.begin():
        servico.resolver(s, tipo, chave, quando)


def estado(sessoes, tipo=CAPTCHA, chave=CHAVE_GERAL):
    with sessoes() as s:
        return s.get(EstadoAviso, (tipo.value, chave))


def desligar(sessoes, tipo=CAPTCHA, ligado=False):
    with sessoes() as s, s.begin():
        servico.definir_ligado(s, tipo, ligado)


def test_primeira_ocorrencia_abre_e_envia(sessoes):
    avisar_em(sessoes, T)
    [m] = saidas(sessoes)
    assert m.destino == "admin" and m.texto.startswith("🔴 *Amazon (monitor) · CAPTCHA*\n") and m.criada_em == T
    e = estado(sessoes)
    assert (e.aberto, e.ocorrencias, e.primeiro_em, e.ultimo_em, e.ultimo_envio_em) == (True, 1, T, T, T)


def test_repeticao_antes_de_2h_so_conta(sessoes):
    avisar_em(sessoes, T)
    avisar_em(sessoes, T + timedelta(minutes=30))
    avisar_em(sessoes, T + timedelta(hours=1, minutes=59))
    assert len(saidas(sessoes)) == 1
    e = estado(sessoes)
    assert (e.ocorrencias, e.ultimo_em, e.ultimo_envio_em) == (3, T + timedelta(hours=1, minutes=59), T)


def test_lembrete_depois_de_2h(sessoes):
    avisar_em(sessoes, T)
    avisar_em(sessoes, T + timedelta(minutes=30))
    avisar_em(sessoes, T + timedelta(hours=2))
    _, lembrete = saidas(sessoes)
    assert lembrete.texto.startswith("🔴 *Amazon (monitor) · CAPTCHA continua · 3 vezes desde 10:00*\n")
    assert lembrete.texto.endswith("_18/10 12:00 · monitor Amazon_")
    assert estado(sessoes).ultimo_envio_em == T + timedelta(hours=2)


def test_lembretes_nao_acumulam_depois_de_horas_parado(sessoes):
    avisar_em(sessoes, T)
    for minuto in range(5):  # o serviço volta 5 h depois e o problema repete a cada minuto
        avisar_em(sessoes, T + timedelta(hours=5, minutes=minuto))
    assert len(saidas(sessoes)) == 2
    assert estado(sessoes).ocorrencias == 6


def test_resolver_com_envio_manda_resolvido(sessoes):
    avisar_em(sessoes, T)
    avisar_em(sessoes, T + timedelta(minutes=10))
    resolver_em(sessoes, T + timedelta(minutes=30))
    *_, resolvido = saidas(sessoes)
    assert resolvido.texto == "✅ *Amazon (monitor) · CAPTCHA resolvido · 2 vezes em 30 min*\n_18/10 10:30 · monitor Amazon_"
    assert estado(sessoes).aberto is False


def test_resolver_sem_aberto_nao_faz_nada(sessoes):
    resolver_em(sessoes, T)
    assert saidas(sessoes) == [] and estado(sessoes) is None


def test_tipo_desligado_atualiza_o_estado_e_nao_envia_nem_resolvido(sessoes):
    desligar(sessoes)
    avisar_em(sessoes, T)
    avisar_em(sessoes, T + timedelta(hours=3))
    assert saidas(sessoes) == []
    assert (estado(sessoes).aberto, estado(sessoes).ocorrencias) == (True, 2)
    resolver_em(sessoes, T + timedelta(hours=4))
    assert saidas(sessoes) == [] and estado(sessoes).aberto is False


def test_religado_com_problema_aberto_o_proximo_avisar_lembra(sessoes):
    desligar(sessoes)
    avisar_em(sessoes, T)
    desligar(sessoes, ligado=True)
    avisar_em(sessoes, T + timedelta(minutes=5))
    [m] = saidas(sessoes)
    assert m.texto.startswith("🔴 *Amazon (monitor) · CAPTCHA continua · 2 vezes desde 10:00*")


def test_reabre_depois_de_resolvido(sessoes):
    avisar_em(sessoes, T)
    resolver_em(sessoes, T + timedelta(minutes=1))
    avisar_em(sessoes, T + timedelta(minutes=2))
    assert saidas(sessoes)[-1].texto.startswith("🔴 *Amazon (monitor) · CAPTCHA*\n")
    e = estado(sessoes)
    assert (e.aberto, e.ocorrencias, e.primeiro_em) == (True, 1, T + timedelta(minutes=2))


def test_chave_separa_ocorrencias(sessoes):
    avisar_em(sessoes, T, TipoAviso.AMAZON_CARRINHO, "B0AAAA0001")
    avisar_em(sessoes, T, TipoAviso.AMAZON_CARRINHO, "B0BBBB0001")
    resolver_em(sessoes, T + timedelta(minutes=5), TipoAviso.AMAZON_CARRINHO, "B0AAAA0001")
    textos = [m.texto for m in saidas(sessoes)]
    assert len(textos) == 3
    assert textos[2].startswith("✅ *Amazon · conferir o carrinho · B0AAAA0001 resolvido · 1 vez em 5 min*")
    with sessoes() as s:
        assert servico.abertos(s, TipoAviso.AMAZON_CARRINHO) == ["B0BBBB0001"]


def test_resolver_todos(sessoes):
    avisar_em(sessoes, T, TipoAviso.IA_SEM_ORCAMENTO, "dia 17/10")
    avisar_em(sessoes, T, TipoAviso.IA_SEM_ORCAMENTO, "dia 18/10")
    with sessoes() as s, s.begin():
        servico.resolver_todos(s, TipoAviso.IA_SEM_ORCAMENTO, T + timedelta(hours=1))
    with sessoes() as s:
        assert servico.abertos(s, TipoAviso.IA_SEM_ORCAMENTO) == []
    assert len(saidas(sessoes)) == 4


def test_tipo_que_nao_agrupa_sempre_envia_e_nao_grava_estado(sessoes):
    avisar_em(sessoes, T, TipoAviso.OPORTUNIDADE, "7")
    avisar_em(sessoes, T, TipoAviso.OPORTUNIDADE, "7")
    assert [m.destino for m in saidas(sessoes)] == ["oportunidades", "oportunidades"]
    assert estado(sessoes, TipoAviso.OPORTUNIDADE, "7") is None


def test_mensagem_nao_enviada_lembra_no_maximo_uma_vez_por_hora(sessoes):
    tipo = TipoAviso.MENSAGEM_NAO_ENVIADA
    for minutos in (0, 30, 59, 60, 90):
        avisar_em(sessoes, T + timedelta(minutes=minutos), tipo)
    assert len(saidas(sessoes)) == 2


def test_usa_o_fuso_e_o_host_de_configuracoes(sessoes, config):
    with sessoes() as s, s.begin():
        repo.obter_config_geral(s, config)
        repo.salvar_config_geral(s, {"fuso": "UTC"}, T)
    avisar_em(sessoes, T, TipoAviso.SERVICO_PAUSADO_MANUAL)
    assert saidas(sessoes)[0].texto.endswith("_18/10 13:00 · admin_")
    with pytest.raises(UrlProibida), sessoes() as s, s.begin():  # config.host_publico == "host.test"
        servico.avisar(s, TipoAviso.AMAZON_ERRO, CHAVE_GERAL, Dados(linhas=("abra host.test",)), T)


def test_endereco_do_sistema_em_modo_estrito_levanta(sessoes):
    dados = Dados(linhas=("veja http://192.168.0.10:8000/servicos",))
    with pytest.raises(UrlProibida), sessoes() as s, s.begin():
        servico.avisar(s, TipoAviso.AMAZON_ERRO, CHAVE_GERAL, dados, T)


def test_fora_do_modo_estrito_avisar_remove_e_enfileira(sessoes, monkeypatch):
    monkeypatch.setattr(formato, "ESTRITO", False)
    avisar_em(sessoes, T, TipoAviso.AMAZON_ERRO, dados=Dados(linhas=("Erro: ConnectError('http://10.0.0.2:8000/x')",)))
    [m] = saidas(sessoes)
    assert "ConnectError('[endereço removido]')" in m.texto and "8000" not in m.texto


def test_erro_ao_enfileirar_nao_propaga_nem_estraga_a_transacao(sessoes, monkeypatch, caplog):
    caplog.set_level(logging.ERROR)

    def quebrar(*_a, **_k):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(repo_msg, "enfileirar", quebrar)
    with sessoes() as s, s.begin():
        servico.avisar(s, CAPTCHA, CHAVE_GERAL, CATALOGO[CAPTCHA].exemplo, T)
        s.add(ConfigAviso(tipo="so_para_o_teste", ligado=True))
        s.flush()
    assert "aviso amazon_captcha (geral) não registrado" in caplog.text
    with sessoes() as s:
        assert s.get(EstadoAviso, ("amazon_captcha", "geral")) is None  # o savepoint foi desfeito
        assert s.get(ConfigAviso, "so_para_o_teste") is not None  # a transação do chamador seguiu


def test_ligados_e_definir_ligado(sessoes):
    with sessoes() as s:
        assert all(servico.ligados(s).values())
    desligar(sessoes, TipoAviso.AMAZON_MONITOR_CONCLUIDO)
    with sessoes() as s:
        assert servico.ligados(s)[TipoAviso.AMAZON_MONITOR_CONCLUIDO] is False
        assert servico.ligado(s, TipoAviso.AMAZON_CAPTCHA) is True


def test_avisador_banco_abre_a_propria_transacao(sessoes):
    avisador = servico.AvisadorBanco(sessoes, relogio=lambda: T)
    avisador.avisar(CAPTCHA, CHAVE_GERAL, CATALOGO[CAPTCHA].exemplo)
    avisador.resolver(CAPTCHA, CHAVE_GERAL)
    avisador.avisar(TipoAviso.IA_SEM_ORCAMENTO, "dia 18/10", CATALOGO[TipoAviso.IA_SEM_ORCAMENTO].exemplo)
    avisador.resolver_todos(TipoAviso.IA_SEM_ORCAMENTO)
    assert len(saidas(sessoes)) == 4


def test_avisador_banco_com_banco_fora_nao_propaga(caplog):
    def sessoes():
        raise RuntimeError("banco fora")

    servico.AvisadorBanco(sessoes, relogio=lambda: T).avisar(CAPTCHA, CHAVE_GERAL, CATALOGO[CAPTCHA].exemplo)
    assert "aviso amazon_captcha não registrado" in caplog.text


NUMERO = "+5511900000001"
CODIGO = TipoAviso.CODIGO_ACESSO


def test_avisar_individual_enfileira_so_para_o_numero_com_validade(sessoes):
    with sessoes() as s, s.begin():
        dados = Dados(destaque="123456", linhas=("Vale por 5 minutos.",))
        assert servico.avisar_individual(s, CODIGO, NUMERO, dados, T) is True
    [m] = saidas(sessoes)
    assert (m.destino, m.numero, m.expira_em, m.criada_em) == ("individual", NUMERO, T + timedelta(minutes=5), T)
    assert m.texto.startswith("🔑 *Código de acesso*\n*123456*\n")


def test_avisar_individual_respeita_a_validade_pedida(sessoes):
    with sessoes() as s, s.begin():
        servico.avisar_individual(s, CODIGO, NUMERO, CATALOGO[CODIGO].exemplo, T, timedelta(minutes=1))
    assert saidas(sessoes)[0].expira_em == T + timedelta(minutes=1)


def test_avisar_individual_desligado_nao_enfileira(sessoes):
    desligar(sessoes, CODIGO)
    with sessoes() as s, s.begin():
        assert servico.avisar_individual(s, CODIGO, NUMERO, CATALOGO[CODIGO].exemplo, T) is False
    assert saidas(sessoes) == []


def test_tipo_de_grupo_nao_vai_para_numero_e_individual_nao_vai_para_grupo(sessoes, caplog):
    with sessoes() as s, s.begin():
        assert servico.avisar_individual(s, CAPTCHA, NUMERO, CATALOGO[CAPTCHA].exemplo, T) is False
        servico.avisar(s, CODIGO, CHAVE_GERAL, CATALOGO[CODIGO].exemplo, T)
    assert saidas(sessoes) == []
    assert "900000001" not in caplog.text


def test_avisar_devolve_o_id_da_mensagem(sessoes):
    with sessoes() as s, s.begin():
        mensagem_id = servico.avisar(s, TipoAviso.OPORTUNIDADE, "1", CATALOGO[TipoAviso.OPORTUNIDADE].exemplo, T)
        assert s.get(MensagemSaida, mensagem_id).destino == "oportunidades"


def test_avisar_desligado_devolve_none(sessoes):
    with sessoes() as s, s.begin():
        servico.definir_ligado(s, TipoAviso.OPORTUNIDADE, False)
        assert servico.avisar(s, TipoAviso.OPORTUNIDADE, "1", CATALOGO[TipoAviso.OPORTUNIDADE].exemplo, T) is None


def lembrar_em(sessoes, quando):
    with sessoes() as s, s.begin():
        return servico.lembrar_abertos(s, quando)


def test_bloqueio_que_espera_recebe_lembrete_a_cada_2h(sessoes):
    avisar_em(sessoes, T)
    assert lembrar_em(sessoes, T + timedelta(hours=1, minutes=59)) == 0
    assert lembrar_em(sessoes, T + timedelta(hours=2)) == 1
    assert lembrar_em(sessoes, T + timedelta(hours=3)) == 0
    assert lembrar_em(sessoes, T + timedelta(hours=4)) == 1
    _, primeiro, segundo = saidas(sessoes)
    assert primeiro.texto.startswith("🔴 *Amazon (monitor) · CAPTCHA continua · 1 vezes desde 10:00*\n")
    assert "*O que fazer:*" in primeiro.texto and primeiro.texto.endswith("_18/10 12:00 · monitor Amazon_")
    assert "Página:" not in primeiro.texto
    assert estado(sessoes).ultimo_envio_em == T + timedelta(hours=4) and segundo.criada_em == T + timedelta(hours=4)


def test_lembrete_de_aberto_respeita_aviso_desligado(sessoes):
    avisar_em(sessoes, T)
    desligar(sessoes)
    assert lembrar_em(sessoes, T + timedelta(hours=3)) == 0
    assert len(saidas(sessoes)) == 1


def test_lembrete_de_aberto_nao_soma_ocorrencias_nem_duplica(sessoes):
    avisar_em(sessoes, T)
    lembrar_em(sessoes, T + timedelta(hours=2))
    avisar_em(sessoes, T + timedelta(hours=2, minutes=1))  # a repetição não reenvia: o lembrete acabou de sair
    lembrar_em(sessoes, T + timedelta(hours=2, minutes=2))
    assert len(saidas(sessoes)) == 2
    e = estado(sessoes)
    assert (e.ocorrencias, e.ultimo_em) == (2, T + timedelta(hours=2, minutes=1))


def test_tipo_que_nao_espera_nao_recebe_lembrete_sozinho(sessoes):
    avisar_em(sessoes, T, TipoAviso.AMAZON_ERRO)
    assert lembrar_em(sessoes, T + timedelta(hours=5)) == 0
    assert len(saidas(sessoes)) == 1


def test_lembrete_de_aberto_fechado_nao_sai(sessoes):
    avisar_em(sessoes, T)
    resolver_em(sessoes, T + timedelta(minutes=5))
    assert lembrar_em(sessoes, T + timedelta(hours=5)) == 0


def test_mensagem_nao_enviada_resolve_sem_falhas_na_janela(sessoes):
    tipo = TipoAviso.MENSAGEM_NAO_ENVIADA
    with sessoes() as s, s.begin():
        falha = repo_msg.enfileirar(s, "oportunidades", "oferta", T)
        falha.status = StatusMensagem.FALHA
        outra = repo_msg.enfileirar(s, "admin", "outra", T)
        outra.status = StatusMensagem.FALHA
        ids = (falha.id, outra.id)
    avisar_em(sessoes, T, tipo)
    with sessoes() as s, s.begin():
        s.get(MensagemSaida, ids[0]).status = StatusMensagem.ENVIADA
        servico.resolver_nao_enviada_sem_falhas(s, T + timedelta(minutes=5))
    assert estado(sessoes, tipo).aberto is True  # outra falha segue
    with sessoes() as s, s.begin():
        s.get(MensagemSaida, ids[1]).status = StatusMensagem.DESCARTADA
        servico.resolver_nao_enviada_sem_falhas(s, T + timedelta(minutes=10))
    assert estado(sessoes, tipo).aberto is False
    assert saidas(sessoes)[-1].texto.startswith("✅ *WhatsApp · mensagem não enviada resolvido")


def test_reenviar_a_ultima_falha_resolve_o_aviso(sessoes):
    tipo = TipoAviso.MENSAGEM_NAO_ENVIADA
    with sessoes() as s, s.begin():
        falha = repo_msg.enfileirar(s, "oportunidades", "oferta", T)
        falha.status = StatusMensagem.FALHA
        falha.atualizado_em = T
        mid = falha.id
    avisar_em(sessoes, T, tipo)
    with sessoes() as s, s.begin():
        repo_msg.reenviar(s, mid, T + timedelta(minutes=5))
    assert estado(sessoes, tipo).aberto is False


def test_descartar_a_ultima_falha_resolve_o_aviso(sessoes):
    tipo = TipoAviso.MENSAGEM_NAO_ENVIADA
    with sessoes() as s, s.begin():
        falha = repo_msg.enfileirar(s, "oportunidades", "oferta", T)
        falha.status = StatusMensagem.FALHA
        falha.atualizado_em = T
        mid = falha.id
    avisar_em(sessoes, T, tipo)
    with sessoes() as s, s.begin():
        repo_msg.descartar(s, mid, T + timedelta(minutes=5))
    assert estado(sessoes, tipo).aberto is False


def test_busca_pausada_tambem_recebe_lembrete(sessoes):
    """É o gêmeo de AMAZON_PAUSADA (os dois vêm de `OrigemAmazon.pausada`): também só espera alguém agir."""
    from tcg_sniper.avisos.catalogo import TIPOS_QUE_ESPERAM

    assert TipoAviso.AMAZON_BUSCA_PAUSADA in TIPOS_QUE_ESPERAM
    assert len(TIPOS_QUE_ESPERAM) == 8
    avisar_em(sessoes, T, tipo=TipoAviso.AMAZON_BUSCA_PAUSADA)
    assert lembrar_em(sessoes, T + timedelta(hours=2)) == 1
