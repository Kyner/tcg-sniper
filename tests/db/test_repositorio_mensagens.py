from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import EstadoNotificador, MensagemSaida, StatusMensagem

AGORA = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def test_enfileirar_cria_pendente_vencida(s):
    m = repo_msg.enfileirar(s, "admin", "olá", AGORA)
    assert (m.status, m.tentativas, m.proxima_tentativa_em, m.criada_em) == (
        StatusMensagem.PENDENTE, 0, AGORA, AGORA
    )
    assert (m.ignorar_validade, m.ultimo_erro, m.enviada_em) == (False, None, None)


def test_lote_pendente_so_vencidas_por_ordem_de_criacao_com_limite(s):
    velha = repo_msg.enfileirar(s, "admin", "1", AGORA - timedelta(minutes=10))
    nova = repo_msg.enfileirar(s, "oportunidades", "2", AGORA - timedelta(minutes=5))
    futura = repo_msg.enfileirar(s, "admin", "3", AGORA - timedelta(minutes=20))
    futura.proxima_tentativa_em = AGORA + timedelta(minutes=1)
    enviada = repo_msg.enfileirar(s, "admin", "4", AGORA - timedelta(minutes=30))
    enviada.status = StatusMensagem.ENVIADA
    s.flush()
    assert [m.id for m in repo_msg.lote_pendente(s, AGORA)] == [velha.id, nova.id]
    assert [m.id for m in repo_msg.lote_pendente(s, AGORA, limite=1)] == [velha.id]


def test_lote_pendente_pula_linhas_travadas_por_outra_sessao(engine):
    with Session(engine) as s, s.begin():
        mid = repo_msg.enfileirar(s, "admin", "concorrente", AGORA).id
    try:
        with Session(engine) as a, a.begin():
            assert mid in [m.id for m in repo_msg.lote_pendente(a, AGORA)]
            with Session(engine) as b, b.begin():
                assert mid not in [m.id for m in repo_msg.lote_pendente(b, AGORA)]
    finally:
        with Session(engine) as s, s.begin():
            s.execute(delete(MensagemSaida).where(MensagemSaida.id == mid))


def test_registrar_ciclo(s):
    assert s.get(EstadoNotificador, 1).ultimo_ciclo_em is None
    repo_msg.registrar_ciclo(s, AGORA)
    assert s.get(EstadoNotificador, 1, populate_existing=True).ultimo_ciclo_em == AGORA


def test_limpar_antigas_apaga_so_as_resolvidas_de_mais_de_30_dias(s):
    velho = AGORA - timedelta(days=31)
    ids = {}
    for status in StatusMensagem:
        m = repo_msg.enfileirar(s, "admin", status.value, velho)
        m.status = status
        ids[status] = m.id
    recente = repo_msg.enfileirar(s, "admin", "recente", AGORA - timedelta(days=29))
    recente.status = StatusMensagem.ENVIADA
    s.flush()
    assert repo_msg.limpar_antigas(s, AGORA) == 3
    restantes = set(s.scalars(select(MensagemSaida.id)))
    assert ids[StatusMensagem.PENDENTE] in restantes and ids[StatusMensagem.FALHA] in restantes
    assert recente.id in restantes
    assert not {ids[StatusMensagem.ENVIADA], ids[StatusMensagem.EXPIRADA], ids[StatusMensagem.DESCARTADA]} & restantes


@pytest.mark.parametrize("status", [StatusMensagem.FALHA, StatusMensagem.EXPIRADA])
def test_reenviar(s, status):
    m = repo_msg.enfileirar(s, "oportunidades", "x", AGORA - timedelta(hours=10))
    m.status, m.tentativas, m.ultimo_erro = status, 5, "HTTP 400"
    s.flush()
    repo_msg.reenviar(s, m.id, AGORA)
    s.refresh(m)
    assert (m.status, m.tentativas, m.proxima_tentativa_em, m.ignorar_validade, m.ultimo_erro) == (
        StatusMensagem.PENDENTE, 0, AGORA, True, None
    )


@pytest.mark.parametrize("status", [StatusMensagem.PENDENTE, StatusMensagem.FALHA, StatusMensagem.EXPIRADA])
def test_descartar(s, status):
    m = repo_msg.enfileirar(s, "admin", "x", AGORA)
    m.status = status
    s.flush()
    repo_msg.descartar(s, m.id, AGORA)
    s.refresh(m)
    assert m.status is StatusMensagem.DESCARTADA


@pytest.mark.parametrize(
    ("acao", "status"),
    [
        (repo_msg.reenviar, StatusMensagem.ENVIADA),
        (repo_msg.reenviar, StatusMensagem.PENDENTE),
        (repo_msg.reenviar, StatusMensagem.DESCARTADA),
        (repo_msg.descartar, StatusMensagem.ENVIADA),
        (repo_msg.descartar, StatusMensagem.DESCARTADA),
    ],
)
def test_acao_que_nao_vale_para_a_situacao(s, acao, status):
    m = repo_msg.enfileirar(s, "admin", "x", AGORA)
    m.status = status
    s.flush()
    with pytest.raises(repo_msg.AcaoInvalida):
        acao(s, m.id, AGORA)


def test_mensagem_inexistente(s):
    with pytest.raises(repo_msg.MensagemNaoEncontrada):
        repo_msg.reenviar(s, 999_999, AGORA)


def test_acao_confere_a_situacao_atual_e_nao_a_do_cache_da_sessao(engine):
    with Session(engine) as s, s.begin():
        mid = repo_msg.enfileirar(s, "admin", "obsoleta", AGORA).id
    try:
        with Session(engine) as s1, s1.begin():
            assert s1.get(MensagemSaida, mid).status is StatusMensagem.PENDENTE
            with Session(engine) as s2, s2.begin():
                s2.get(MensagemSaida, mid).status = StatusMensagem.ENVIADA
            with pytest.raises(repo_msg.AcaoInvalida):
                repo_msg.descartar(s1, mid, AGORA)
    finally:
        with Session(engine) as s, s.begin():
            s.execute(delete(MensagemSaida).where(MensagemSaida.id == mid))


def test_falhas_recentes_so_as_falhas_da_janela_das_mais_novas(s):
    agora = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    antiga = repo_msg.enfileirar(s, "admin", "a", agora - timedelta(hours=3))
    nova = repo_msg.enfileirar(s, "oportunidades", "b", agora)
    pendente = repo_msg.enfileirar(s, "admin", "c", agora)
    for m, quando in ((antiga, agora - timedelta(hours=2)), (nova, agora - timedelta(minutes=5))):
        m.status, m.atualizado_em = StatusMensagem.FALHA, quando
    s.flush()
    assert repo_msg.falhas_recentes(s, agora - timedelta(hours=1)) == [nova]
    assert pendente.status is StatusMensagem.PENDENTE


NUMERO = "+5511900000001"


def individual(s, criada=AGORA):
    return repo_msg.enfileirar(
        s, "individual", "🔑 *Código de acesso*\n*123456*", criada, numero=NUMERO, expira_em=criada + timedelta(minutes=5)
    )


def test_enfileirar_individual_guarda_numero_e_validade(s):
    m = individual(s)
    assert (m.destino, m.numero, m.expira_em) == ("individual", NUMERO, AGORA + timedelta(minutes=5))


def test_individual_nao_e_reenviado(s):
    m = individual(s)
    m.status = StatusMensagem.EXPIRADA
    s.flush()
    with pytest.raises(repo_msg.AcaoInvalida, match="código novo"):
        repo_msg.reenviar(s, m.id, AGORA)


def test_descartar_individual_apaga_o_texto(s):
    m = individual(s)
    repo_msg.descartar(s, m.id, AGORA)
    assert (m.status, m.texto) == (StatusMensagem.DESCARTADA, repo_msg.TEXTO_APAGADO)


def test_apagar_texto_so_mexe_na_individual(s):
    grupo = repo_msg.enfileirar(s, "admin", "aviso", AGORA)
    repo_msg.apagar_texto_individual(grupo)
    assert grupo.texto == "aviso"
