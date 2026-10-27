from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tcg_sniper.coletor_liga.esfriamento import SituacaoDesafio, desafios_desde, situacao_desafio
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import StatusColeta, TipoColeta

SP = ZoneInfo("America/Sao_Paulo")
DIA = datetime(2026, 10, 13, 0, 0, tzinfo=SP)


def local(h, m=0, dias=0):
    return DIA + timedelta(days=dias, hours=h, minutes=m)


def coleta(s, quando, status=StatusColeta.OK, tipo=TipoColeta.PRODUTOS):
    c = repo.iniciar_coleta(s, tipo, quando)
    if status is not StatusColeta.RODANDO:
        repo.finalizar_coleta(s, c.id, status, 1, 0, quando)
    return c


def desafio(s, quando):
    coleta(s, quando, StatusColeta.PAUSADA_DESAFIO)
    repo.pausar_por_desafio(s, "desafio em /x", quando)


def situacao(s, agora, esfriar=30):
    return situacao_desafio(s, agora, SP, esfriar)


def test_sem_desafio_nada_muda(s):
    atual = situacao(s, local(12))
    assert atual == SituacaoDesafio(0, 0, None)
    assert not atual.parada_hoje and not atual.pausas_dobradas


def test_ainda_pausado_conta_o_desafio_mas_nao_esfria(s):
    desafio(s, local(10, 30))
    atual = situacao(s, local(11))
    assert (atual.desafios_hoje, atual.esfriando_ate, atual.pausas_dobradas) == (1, None, True)


def test_esfria_contado_da_retomada(s):
    desafio(s, local(10, 30))
    repo.retomar(s, local(11), desafio_resolvido=True)
    assert situacao(s, local(11, 10)).esfriando_ate == local(11, 30)
    assert situacao(s, local(11, 30)).esfriando_ate is None


def test_pedir_execucao_nao_estende_o_esfriamento(s):
    desafio(s, local(10, 30))
    repo.retomar(s, local(11), desafio_resolvido=True)
    repo.solicitar_execucao(s, local(11, 10))  # "Rodar agora" no meio da espera
    assert situacao(s, local(11, 20)).esfriando_ate == local(11, 30)


def test_coleta_que_comecou_depois_do_desafio_encerra_o_esfriamento(s):
    desafio(s, local(10, 30))
    repo.retomar(s, local(11), desafio_resolvido=True)
    coleta(s, local(11, 30), StatusColeta.RODANDO)
    assert situacao(s, local(11, 45), esfriar=60).esfriando_ate is None  # sem a coleta, iria até 12:00


def test_esfriar_zero_nao_espera(s):
    desafio(s, local(10, 30))
    repo.retomar(s, local(11), desafio_resolvido=True)
    assert situacao(s, local(11), esfriar=0).esfriando_ate is None


def test_segundo_desafio_do_dia_para_ate_amanha(s):
    desafio(s, local(10, 30))
    repo.retomar(s, local(11), desafio_resolvido=True)
    coleta(s, local(11, 30))
    desafio(s, local(13))
    atual = situacao(s, local(13, 5))
    assert (atual.desafios_hoje, atual.parada_hoje) == (2, True)
    assert not situacao(s, local(9, dias=1)).parada_hoje


def test_desafio_antes_da_meia_noite_local_conta_no_dia_anterior(s):
    desafio(s, local(23, 50, dias=-1))  # 02:50 UTC de hoje
    assert situacao(s, local(9)).desafios_hoje == 0
    assert desafios_desde(s, DIA) == 0
    assert desafios_desde(s, DIA - timedelta(days=1)) == 1


def test_desafio_de_ontem_ainda_esfria_a_retomada_de_hoje_sem_dobrar_as_pausas(s):
    desafio(s, local(22, dias=-1))
    repo.retomar(s, local(8), desafio_resolvido=True)
    atual = situacao(s, local(8, 10))
    # O desafio de 22h de ontem tem menos de 24 h às 8h: dobra (a parada até amanhã segue no dia do calendário).
    assert (atual.desafios_hoje, atual.esfriando_ate, atual.pausas_dobradas) == (0, local(8, 30), True)
    assert not atual.parada_hoje


def test_desafio_de_mais_de_24h_nao_dobra_as_pausas(s):
    desafio(s, local(7, dias=-1))
    assert not situacao(s, local(8)).pausas_dobradas
    assert situacao(s, local(6, 59)).pausas_dobradas


def test_desafio_as_23h_dobra_as_pausas_da_madrugada(s):
    desafio(s, local(23, dias=-1))
    atual = situacao(s, local(1))  # espera acabando depois da meia-noite
    assert (atual.desafios_hoje, atual.pausas_dobradas) == (0, True)


def test_desligar_e_religar_nao_reinicia_a_espera_do_desafio(s):
    desafio(s, local(10, 30))
    repo.retomar(s, local(11), desafio_resolvido=True)
    repo.pausar(s, "pausado no admin", local(11, 10), repo.COLETOR_LIGA)
    repo.retomar(s, local(11, 20), solicitar=False)
    assert situacao(s, local(11, 25)).esfriando_ate == local(11, 30)
    assert situacao(s, local(11, 30)).esfriando_ate is None


def test_ligar_direto_do_estado_de_desafio_ainda_esfria(s):
    desafio(s, local(10, 30))
    repo.retomar(s, local(11), solicitar=False)  # "Ligar" sem passar pelo Retomar do desafio
    assert situacao(s, local(11, 5)).esfriando_ate == local(11, 30)


def test_sem_marca_da_retomada_a_espera_cai_para_o_atualizado_em(s):
    desafio(s, local(10, 30))
    repo.retomar(s, local(11), desafio_resolvido=True)
    estado = repo.obter_estado(s, local(11))
    estado.retomado_desafio_em = None  # linha resolvida antes da coluna existir
    s.flush()
    assert situacao(s, local(11, 5)).esfriando_ate == local(11, 30)


def test_ligar_na_espera_mantem_o_pedido(s):
    desafio(s, local(10, 30))
    repo.retomar(s, local(11), desafio_resolvido=True)  # Retomar pede a execução
    repo.retomar(s, local(11, 10), solicitar=False)  # Ligar no meio da espera
    assert repo.obter_estado(s, local(11, 10)).execucao_solicitada is True
    assert situacao(s, local(11, 15)).esfriando_ate == local(11, 30)


def test_desafio_da_amazon_nao_conta(s):
    coleta(s, local(10), StatusColeta.PAUSADA_DESAFIO, TipoColeta.AMAZON)
    assert situacao(s, local(10, 5)) == SituacaoDesafio(0, 0, None)
