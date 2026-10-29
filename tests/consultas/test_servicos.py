from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fakes import criar_anuncio, criar_produto

from tcg_sniper.consultas import painel, servicos
from tcg_sniper.consultas.painel import SaudeServico
from tcg_sniper.consultas.servicos import Transicao, em_andamento, estado_unico, transicao, ultimo_registro
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import (
    ChamadaIA,
    ConferenciaCheckout,
    Envio,
    EstadoColetorTipo,
    ExecucaoManutencao,
    FilaAmazon,
    MensagemSaida,
    OfertaAmazon,
    ResumoPreco,
    SituacaoCheckout,
    StatusColeta,
    StatusManutencao,
    StatusMensagem,
    TipoColeta,
)
from tcg_sniper.gestao.servicos import COLETOR, Servico

AGORA = datetime(2026, 10, 16, 19, 40, tzinfo=UTC)


def _saude(situacao, nome="LigaMagic", texto="x"):
    return SaudeServico(nome, situacao, texto, "", "/servicos")


@pytest.mark.parametrize(
    ("situacao", "esperado"),
    [
        ("rodando", "rodando"),
        ("ok", "esperando"),
        ("parcial", "atrasado"),
        ("falha", "com_problema"),
        ("pausado_desafio", "com_problema"),
        ("pausado", "desligado"),
        ("inativo", "desligado"),
    ],
)
def test_estado_unico_mapeia_cada_situacao(situacao, esperado):
    assert estado_unico(_saude(situacao)) == esperado


def test_estado_unico_casador_sem_chave_e_com_problema():
    sem_chave = _saude("pausado", "Casador (IA)", "IA ligada, mas sem chave")
    assert estado_unico(sem_chave) == "com_problema"
    assert estado_unico(_saude("pausado", "Casador (IA)", "Pausado: manual")) == "desligado"


def _coleta(s, tipo, quando, status=StatusColeta.OK):
    c = repo.iniciar_coleta(s, tipo, quando)
    if status is not StatusColeta.RODANDO:
        repo.finalizar_coleta(s, c.id, status, 1, 0, quando + timedelta(minutes=1), None)
    return c


def _estado(s, servico, desligado, desde):
    if desligado:
        repo.pausar(s, "pausado no admin", desde, COLETOR[servico])
    else:
        repo.retomar(s, desde, COLETOR[servico], solicitar=False)
    return repo.obter_estado(s, desde, COLETOR[servico])


def test_desligado_com_coleta_rodando_esta_parando(s):
    _coleta(s, TipoColeta.LISTAGEM, AGORA - timedelta(minutes=30), StatusColeta.RODANDO)
    estado = _estado(s, Servico.LIGA, True, AGORA - timedelta(minutes=20))
    assert em_andamento(s, Servico.LIGA, AGORA)
    assert transicao(s, Servico.LIGA, estado, AGORA) == Transicao("parando", AGORA - timedelta(minutes=20))


def test_desligado_com_registro_novo_esta_parando(s):
    estado = _estado(s, Servico.CASADOR, True, AGORA - timedelta(minutes=10))
    s.add(ChamadaIA(em=AGORA - timedelta(seconds=30), finalidade="casamento", modelo="m", tokens_entrada=1,
                    tokens_saida=1, custo_usd=Decimal("0.01"), ok=True))
    s.flush()
    assert transicao(s, Servico.CASADOR, estado, AGORA).tipo == "parando"


def test_desligado_sem_registro_ha_2_min_esta_parado_desde_o_ultimo_registro(s):
    registro = AGORA - timedelta(minutes=5)
    _coleta(s, TipoColeta.LISTAGEM, registro - timedelta(minutes=1))  # finaliza em `registro`
    estado = _estado(s, Servico.LIGA, True, AGORA - timedelta(minutes=10))
    assert ultimo_registro(s, Servico.LIGA) == registro
    assert transicao(s, Servico.LIGA, estado, AGORA) == Transicao("parado", registro)


def test_desligado_sem_registro_depois_da_pausa_parado_desde_a_pausa(s):
    _coleta(s, TipoColeta.LISTAGEM, AGORA - timedelta(hours=3))
    pausa = AGORA - timedelta(minutes=10)
    estado = _estado(s, Servico.LIGA, True, pausa)
    assert transicao(s, Servico.LIGA, estado, AGORA) == Transicao("parado", pausa)


def test_desligado_sem_nenhum_registro_parado_desde_a_pausa(s):
    pausa = AGORA - timedelta(hours=1)
    estado = _estado(s, Servico.WHATSAPP, True, pausa)
    assert transicao(s, Servico.WHATSAPP, estado, AGORA) == Transicao("parado", pausa)


def test_ligado_ha_5_min_sem_registro_esta_iniciando(s):
    ligou = AGORA - timedelta(minutes=5)
    estado = _estado(s, Servico.CASADOR, False, ligou)
    assert transicao(s, Servico.CASADOR, estado, AGORA) == Transicao("iniciando", ligou)


@pytest.mark.parametrize("servico", [Servico.LIGA, Servico.WHATSAPP, Servico.BACKUP])
def test_servico_de_horario_ligado_sem_registro_nao_fica_iniciando(s, servico):
    estado = _estado(s, servico, False, AGORA - timedelta(minutes=5))
    assert transicao(s, servico, estado, AGORA) is None


def test_ligado_ha_11_min_sem_registro_volta_ao_estado_normal(s):
    estado = _estado(s, Servico.CASADOR, False, AGORA - timedelta(minutes=11))
    assert transicao(s, Servico.CASADOR, estado, AGORA) is None


def test_ligado_com_registro_depois_de_ligar_nao_esta_iniciando(s):
    ligou = AGORA - timedelta(minutes=5)
    estado = _estado(s, Servico.CASADOR, False, ligou)
    s.add(ChamadaIA(em=ligou + timedelta(minutes=1), finalidade="casamento", modelo="m", tokens_entrada=1,
                    tokens_saida=1, custo_usd=Decimal("0.01"), ok=True))
    s.flush()
    assert transicao(s, Servico.CASADOR, estado, AGORA) is None


def test_desafio_pendente_nao_tem_transicao(s):
    repo.pausar_por_desafio(s, "captcha", AGORA - timedelta(minutes=10), COLETOR[Servico.LIGA])
    estado = repo.obter_estado(s, AGORA, COLETOR[Servico.LIGA])
    assert estado.estado is EstadoColetorTipo.PAUSADO_DESAFIO
    assert transicao(s, Servico.LIGA, estado, AGORA) is None


def test_sem_registro_nenhum_ultimo_registro_e_nulo(s):
    for servico in Servico:
        assert ultimo_registro(s, servico) is None
        assert em_andamento(s, servico, AGORA) is False


def test_ultimo_registro_liga_vem_da_coleta_e_do_resumo(s):
    _coleta(s, TipoColeta.PRODUTOS, AGORA - timedelta(hours=3))
    _coleta(s, TipoColeta.AMAZON, AGORA - timedelta(minutes=1))  # não é da Liga
    assert ultimo_registro(s, Servico.LIGA) == AGORA - timedelta(hours=3) + timedelta(minutes=1)
    produto = criar_produto(s, "p1")
    c = _coleta(s, TipoColeta.PRODUTOS, AGORA - timedelta(hours=4))
    resumo = AGORA - timedelta(minutes=30)
    s.add(ResumoPreco(produto_id=produto.id, coleta_id=c.id, num_lojas=1, coletado_em=resumo))
    s.flush()
    assert ultimo_registro(s, Servico.LIGA) == resumo


def test_ultimo_registro_busca_vem_da_coleta_amazon_e_da_fila(s):
    _coleta(s, TipoColeta.LISTAGEM, AGORA - timedelta(minutes=1))  # não é da busca
    assert ultimo_registro(s, Servico.AMAZON_BUSCA) is None
    _coleta(s, TipoColeta.AMAZON, AGORA - timedelta(hours=2), StatusColeta.RODANDO)
    assert em_andamento(s, Servico.AMAZON_BUSCA, AGORA)
    assert not em_andamento(s, Servico.LIGA, AGORA)
    assert ultimo_registro(s, Servico.AMAZON_BUSCA) == AGORA - timedelta(hours=2)
    busca = AGORA - timedelta(minutes=3)
    s.add(FilaAmazon(produto_id=criar_produto(s, "p2").id, entrou_em=AGORA, proxima_busca_em=AGORA,
                     ultima_busca_em=busca))
    s.flush()
    assert ultimo_registro(s, Servico.AMAZON_BUSCA) == busca


def test_ultimo_registro_monitor_vem_da_oferta_e_da_conferencia(s):
    anuncio = criar_anuncio(s, "B0MONITOR1")
    leitura = AGORA - timedelta(minutes=9)
    s.add(OfertaAmazon(anuncio_id=anuncio.id, lida_em=leitura, preco=Decimal(10), condicao="novo",
                       envio=Envio.AMAZON, importada=False, prime=False, elegivel=True, melhor=True))
    s.flush()
    assert ultimo_registro(s, Servico.AMAZON_MONITOR) == leitura
    conferencia = AGORA - timedelta(minutes=4)
    s.add(ConferenciaCheckout(em=conferencia, anuncio_id=anuncio.id, preco_anunciado=Decimal(10),
                              situacao=SituacaoCheckout.OK, item_removido=True))
    s.flush()
    assert ultimo_registro(s, Servico.AMAZON_MONITOR) == conferencia
    assert em_andamento(s, Servico.AMAZON_MONITOR, AGORA) is False


def test_ultimo_registro_casador_vem_da_chamada_ia(s):
    quando = AGORA - timedelta(minutes=7)
    s.add(ChamadaIA(em=quando, finalidade="casamento", modelo="m", tokens_entrada=1, tokens_saida=1,
                    custo_usd=Decimal("0.01"), ok=True))
    s.flush()
    assert ultimo_registro(s, Servico.CASADOR) == quando


def test_ultimo_registro_whatsapp_vem_da_mensagem_enviada(s):
    quando = AGORA - timedelta(minutes=6)
    s.add(MensagemSaida(destino="admin", texto="a", status=StatusMensagem.ENVIADA, proxima_tentativa_em=AGORA,
                        criada_em=AGORA - timedelta(hours=1), atualizado_em=quando, enviada_em=quando))
    s.add(MensagemSaida(destino="admin", texto="b", status=StatusMensagem.PENDENTE, proxima_tentativa_em=AGORA,
                        criada_em=AGORA, atualizado_em=AGORA))
    s.flush()
    assert ultimo_registro(s, Servico.WHATSAPP) == quando


def test_ultimo_registro_backup_vem_da_execucao(s):
    inicio = AGORA - timedelta(minutes=8)
    s.add(ExecucaoManutencao(inicio=inicio, status=StatusManutencao.RODANDO))
    s.flush()
    assert ultimo_registro(s, Servico.BACKUP) == inicio
    assert em_andamento(s, Servico.BACKUP, AGORA)
    fim = AGORA - timedelta(minutes=2)
    s.query(ExecucaoManutencao).update({"fim": fim, "status": StatusManutencao.OK})
    s.flush()
    assert ultimo_registro(s, Servico.BACKUP) == fim
    assert not em_andamento(s, Servico.BACKUP, AGORA)


def test_saude_por_servico_tem_as_seis_chaves(s, config):
    por_servico = servicos.saude_por_servico(s, AGORA, config, True)
    assert set(por_servico) == set(Servico)
    assert por_servico[Servico.LIGA].nome == "LigaMagic"
    assert por_servico[Servico.AMAZON_BUSCA].nome == painel.NOME_BUSCA
    assert por_servico[Servico.AMAZON_MONITOR].nome == painel.NOME_MONITOR
    assert por_servico[Servico.CASADOR].nome == "Casador (IA)"
    assert por_servico[Servico.WHATSAPP].nome == "WhatsApp"
    assert por_servico[Servico.BACKUP].nome == "Backup"
