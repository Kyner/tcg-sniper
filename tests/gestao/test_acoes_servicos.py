"""Ações de serviço do módulo neutro, chamadas direto (as rotas do admin antigo têm testes próprios)."""

from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, criar_anuncio, criar_produto
from sqlalchemy import select

from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import CATALOGO, TipoAviso
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import (
    EstadoColetorTipo,
    MensagemSaida,
    SituacaoCheckout,
    StatusCasamento,
    StatusColeta,
    TipoColeta,
)
from tcg_sniper.gestao import servicos
from tcg_sniper.gestao.servicos import COLETOR, MENSAGENS, NOMES, Servico

SP = ZoneInfo("America/Sao_Paulo")
SEM_SOLICITAR = {Servico.LIGA, Servico.WHATSAPP, Servico.BACKUP}


def textos(sessoes):
    with sessoes() as s:
        return [m.texto for m in s.scalars(select(MensagemSaida).order_by(MensagemSaida.id))]


def estado(sessoes, servico):
    with sessoes() as s:
        return repo.obter_estado(s, coletor=COLETOR[servico])


def desafio_da_liga(sessoes, quando):
    with sessoes() as s, s.begin():
        c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, quando)
        repo.finalizar_coleta(s, c.id, StatusColeta.PAUSADA_DESAFIO, 1, 0, quando, erro="desafio em /x")
        repo.pausar_por_desafio(s, "desafio em /x", quando)


def retomada(sessoes, quando):
    with sessoes() as s, s.begin():
        repo.retomar(s, quando, solicitar=False)


def test_servicos_e_mensagens_cobrem_tudo():
    assert set(COLETOR) == set(NOMES) == set(Servico)
    for servico in Servico:
        assert servicos._PREFIXO[servico] + "_pausar" in MENSAGENS
        assert servicos._PREFIXO[servico] + "_retomar" in MENSAGENS


@pytest.mark.parametrize("servico", list(Servico))
def test_desligar_e_ligar_cada_servico_muda_o_estado_e_avisa(sessoes, servico):
    with sessoes() as s, s.begin():
        chave = servicos.desligar(s, servico, T0)
    assert chave in MENSAGENS
    pausado = estado(sessoes, servico)
    assert (pausado.estado, pausado.motivo) == (EstadoColetorTipo.PAUSADO, "pausado no admin")

    with sessoes() as s, s.begin():
        chave = servicos.ligar(s, servico, T0 + timedelta(minutes=1))
    assert chave in MENSAGENS
    ativo = estado(sessoes, servico)
    # religar Liga, WhatsApp e Backup segue o horário; os demais pedem uma execução já
    assert (ativo.estado, ativo.execucao_solicitada) == (EstadoColetorTipo.ATIVO, servico not in SEM_SOLICITAR)

    pausou, voltou = textos(sessoes)
    assert pausou.startswith(f"🟡 *Serviço mudou no admin · {NOMES[servico]}*\n• Novo estado: pausado\n")
    assert voltou.startswith(f"🟡 *Serviço mudou no admin · {NOMES[servico]}*\n• Novo estado: ativo\n")


def test_desligar_nao_apaga_um_desafio_pendente(sessoes):
    desafio_da_liga(sessoes, T0)
    with sessoes() as s, s.begin():
        assert servicos.desligar(s, Servico.LIGA, T0 + timedelta(minutes=1)) == "desafio_pendente"
    pendente = estado(sessoes, Servico.LIGA)
    assert (pendente.estado, pendente.motivo) == (EstadoColetorTipo.PAUSADO_DESAFIO, "desafio em /x")
    assert textos(sessoes) == []


def test_desligar_a_busca_nao_mexe_no_monitor(sessoes):
    with sessoes() as s, s.begin():
        assert servicos.desligar(s, Servico.AMAZON_BUSCA, T0) == "amazon_busca_pausar"
    assert estado(sessoes, Servico.AMAZON_BUSCA).estado is EstadoColetorTipo.PAUSADO
    assert estado(sessoes, Servico.AMAZON_MONITOR).estado is EstadoColetorTipo.ATIVO


def test_rodar_agora_parada_nao_pede_execucao(sessoes, config):
    agora = repo.agora_utc()
    desafio_da_liga(sessoes, agora - timedelta(seconds=3))
    desafio_da_liga(sessoes, agora - timedelta(seconds=2))
    retomada(sessoes, agora - timedelta(seconds=1))
    with sessoes() as s, s.begin():
        assert servicos.rodar_agora(s, Servico.LIGA, SP, config, agora) == "liga_parada_hoje"
    assert estado(sessoes, Servico.LIGA).execucao_solicitada is False


def test_rodar_agora_esfriando_pede_e_diz_que_espera(sessoes, config):
    agora = repo.agora_utc()
    desafio_da_liga(sessoes, agora - timedelta(seconds=2))
    retomada(sessoes, agora - timedelta(seconds=1))
    with sessoes() as s, s.begin():
        assert servicos.rodar_agora(s, Servico.LIGA, SP, config, agora) == "liga_esfriando"
    assert estado(sessoes, Servico.LIGA).execucao_solicitada is True


def test_rodar_agora_liga_e_casador_sem_esfriamento(sessoes, config):
    with sessoes() as s, s.begin():
        assert servicos.rodar_agora(s, Servico.LIGA, SP, config, T0) == "rodar"
        assert servicos.rodar_agora(s, Servico.CASADOR, SP, config, T0) == "casador_rodar"
    assert estado(sessoes, Servico.LIGA).execucao_solicitada is True
    assert estado(sessoes, Servico.CASADOR).execucao_solicitada is True
    assert textos(sessoes) == []  # rodar agora não avisa


@pytest.mark.parametrize("servico", [Servico.AMAZON_BUSCA, Servico.AMAZON_MONITOR, Servico.WHATSAPP, Servico.BACKUP])
def test_rodar_agora_de_servico_sem_essa_acao_falha(sessoes, config, servico):
    with pytest.raises(ValueError), sessoes() as s, s.begin():
        servicos.rodar_agora(s, servico, SP, config, T0)


def test_retomar_do_primeiro_desafio_diz_que_esfria(sessoes, config):
    agora = repo.agora_utc()
    desafio_da_liga(sessoes, agora - timedelta(seconds=1))
    with sessoes() as s, s.begin():
        assert servicos.retomar_desafio(s, Servico.LIGA, SP, config, agora) == "retomar_esfriando"
    assert estado(sessoes, Servico.LIGA).execucao_solicitada is True


def test_retomar_do_segundo_desafio_diz_que_volta_amanha(sessoes, config):
    agora = repo.agora_utc()
    desafio_da_liga(sessoes, agora - timedelta(seconds=2))
    desafio_da_liga(sessoes, agora - timedelta(seconds=1))
    with sessoes() as s, s.begin():
        assert servicos.retomar_desafio(s, Servico.LIGA, SP, config, agora) == "retomar_parada"


def test_retomar_desafio_da_amazon_usa_a_mensagem_de_retomar(sessoes, config):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "captcha", T0, COLETOR[Servico.AMAZON_BUSCA])
        assert servicos.retomar_desafio(s, Servico.AMAZON_BUSCA, SP, config, T0) == "amazon_busca_retomar"
        repo.pausar_por_desafio(s, "captcha", T0, COLETOR[Servico.AMAZON_MONITOR])
        assert servicos.retomar_desafio(s, Servico.AMAZON_MONITOR, SP, config, T0) == "amazon_retomar"
    assert estado(sessoes, Servico.AMAZON_BUSCA).estado is EstadoColetorTipo.ATIVO
    assert estado(sessoes, Servico.AMAZON_MONITOR).execucao_solicitada is True


def test_retomar_desafio_de_servico_sem_desafio_falha(sessoes, config):
    with pytest.raises(ValueError), sessoes() as s, s.begin():
        servicos.retomar_desafio(s, Servico.CASADOR, SP, config, T0)


@pytest.mark.parametrize(
    ("chave", "ligado", "esperada"),
    [
        ("monitor_ligado", True, "monitor_ligar"),
        ("monitor_ligado", False, "monitor_desligar"),
        ("checkout_ligado", True, "checkout_ligar"),
        ("checkout_ligado", False, "checkout_desligar"),
    ],
)
def test_ajustar_monitor_e_checkout_nao_avisa(sessoes, chave, ligado, esperada):
    with sessoes() as s, s.begin():
        assert servicos.ajustar_amazon(s, chave, ligado, T0) == esperada
    with sessoes() as s:
        assert getattr(repo_amz.obter_config(s), chave) is ligado
    assert textos(sessoes) == []


def test_retomar_checkout_limpa_a_marca_de_sem_login(sessoes):
    with sessoes() as s, s.begin():
        servicos.aplicar_config(s, {"checkout_sem_login_em": T0}, T0)
        assert servicos.retomar_checkout(s, T0) == "checkout_retomar"
    with sessoes() as s:
        assert repo_amz.obter_config(s).checkout_sem_login_em is None


def _a_conferir(sessoes):
    with sessoes() as s, s.begin():
        produto = criar_produto(s, "p-B0MAO00001", nome="Produto")
        anuncio = criar_anuncio(s, "B0MAO00001", produto=produto, status=StatusCasamento.CONFIRMADO)
        conf = repo_amz.registrar_conferencia(
            s, em=T0, anuncio_id=anuncio.id, vendedor_nome="Shazaar", preco_anunciado=Decimal("275.91"), itens=None,
            frete=None, impostos=None, total=None, situacao=SituacaoCheckout.FALHA, motivo="x", item_removido=False,
        )
        repo_amz.marcar_conferir_a_mao(s, conf.id, T0, "teste")
        avisos.avisar(s, TipoAviso.AMAZON_CARRINHO, "B0MAO00001", CATALOGO[TipoAviso.AMAZON_CARRINHO].exemplo, T0)
        return conf.id


def test_carrinho_conferido_resolve_o_aviso(sessoes):
    conferencia_id = _a_conferir(sessoes)
    with sessoes() as s:
        assert avisos.abertos(s, TipoAviso.AMAZON_CARRINHO) == ["B0MAO00001"]
    with sessoes() as s, s.begin():
        assert servicos.carrinho_conferido(s, conferencia_id, T0) is True
    with sessoes() as s:
        assert avisos.abertos(s, TipoAviso.AMAZON_CARRINHO) == []
        assert repo_amz.conferencias_com_item_no_carrinho(s) == []


def test_carrinho_conferido_inexistente_devolve_falso(sessoes):
    with sessoes() as s, s.begin():
        assert servicos.carrinho_conferido(s, 999_999, T0) is False
