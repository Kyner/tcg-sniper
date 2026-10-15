import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import select

from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import EstadoNotificador, MensagemSaida, StatusMensagem
from tcg_sniper.notificador.servico import ServicoNotificador

URL = "http://evo.test"
ROTA = f"{URL}/message/sendText/inst"
AGORA = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


class Relogio:
    def __init__(self, agora):
        self.agora = agora

    def __call__(self):
        return self.agora


@pytest.fixture
def env(config):
    return config.model_copy(update={"evolution_url": URL, "evolution_api_key": "chave"})


@pytest.fixture
def configurado(sessoes, env):
    with sessoes() as s, s.begin():
        repo.obter_config_geral(s, env)
        repo.salvar_config_geral(
            s,
            {"evolution_instancia": "inst", "whatsapp_grupo_admin": "a@g.us", "whatsapp_grupo_oportunidades": "o@g.us"},
            AGORA,
        )


def servico(sessoes, env, relogio=None):
    return ServicoNotificador(sessoes, env, cliente=httpx.Client(), relogio=relogio or Relogio(AGORA), dormir=lambda _: None)


def nova(sessoes, destino="admin", texto="x", criada=AGORA):
    with sessoes() as s, s.begin():
        return repo_msg.enfileirar(s, destino, texto, criada).id


def ler(sessoes, mid):
    with sessoes() as s:
        return s.get(MensagemSaida, mid)


@respx.mock
def test_sucesso_marca_enviada(sessoes, env, configurado):
    rota = respx.post(ROTA).mock(return_value=httpx.Response(201))
    mid = nova(sessoes, "oportunidades", "oferta")
    assert servico(sessoes, env).ciclo() == 1
    m = ler(sessoes, mid)
    assert (m.status, m.enviada_em, m.ultimo_erro) == (StatusMensagem.ENVIADA, AGORA, None)
    assert '"o@g.us"' in rota.calls.last.request.read().decode()


@respx.mock
def test_5xx_espera_crescente_sem_virar_falha(sessoes, env, configurado):
    respx.post(ROTA).mock(return_value=httpx.Response(503))
    mid = nova(sessoes)
    relogio = Relogio(AGORA)
    svc = servico(sessoes, env, relogio)
    esperas = []
    for _ in range(7):
        svc.ciclo()
        m = ler(sessoes, mid)
        esperas.append(m.proxima_tentativa_em - relogio.agora)
        relogio.agora = m.proxima_tentativa_em
    assert [e.total_seconds() / 60 for e in esperas] == [1, 2, 4, 8, 16, 30, 30]
    m = ler(sessoes, mid)
    assert (m.status, m.tentativas) == (StatusMensagem.PENDENTE, 7)
    assert "503" in m.ultimo_erro


@respx.mock
def test_4xx_vira_falha_na_quinta(sessoes, env, configurado):
    respx.post(ROTA).mock(return_value=httpx.Response(400))
    mid = nova(sessoes)
    relogio = Relogio(AGORA)
    svc = servico(sessoes, env, relogio)
    for tentativa in range(1, 6):
        svc.ciclo()
        m = ler(sessoes, mid)
        assert m.tentativas == tentativa
        relogio.agora = m.proxima_tentativa_em
    assert ler(sessoes, mid).status is StatusMensagem.FALHA


@respx.mock
def test_sem_grupo_fica_pendente_sem_gastar_tentativa_e_sai_quando_preenchido(sessoes, env):
    rota = respx.post(ROTA).mock(return_value=httpx.Response(201))
    with sessoes() as s, s.begin():
        repo.obter_config_geral(s, env)
        repo.salvar_config_geral(s, {"evolution_instancia": "inst", "whatsapp_grupo_admin": None}, AGORA)
    mid = nova(sessoes)
    relogio = Relogio(AGORA)
    svc = servico(sessoes, env, relogio)
    svc.ciclo()
    m = ler(sessoes, mid)
    assert (m.status, m.tentativas, m.proxima_tentativa_em) == (StatusMensagem.PENDENTE, 0, AGORA + timedelta(minutes=1))
    assert "grupo" in m.ultimo_erro and rota.call_count == 0
    with sessoes() as s, s.begin():
        repo.salvar_config_geral(s, {"whatsapp_grupo_admin": "a@g.us"}, AGORA)
    relogio.agora = AGORA + timedelta(minutes=1)
    svc.ciclo()
    assert ler(sessoes, mid).status is StatusMensagem.ENVIADA


@respx.mock
def test_sem_chave_fica_pendente(sessoes, env, configurado):
    rota = respx.post(ROTA)
    mid = nova(sessoes)
    servico(sessoes, env.model_copy(update={"evolution_api_key": "trocar-esta-chave"})).ciclo()
    m = ler(sessoes, mid)
    assert (m.status, m.tentativas) == (StatusMensagem.PENDENTE, 0) and rota.call_count == 0
    assert "EVOLUTION_API_KEY" in m.ultimo_erro


@respx.mock
def test_oportunidade_vencida_expira_e_admin_vencida_sai(sessoes, env, configurado):
    respx.post(ROTA).mock(return_value=httpx.Response(201))
    velha = AGORA - timedelta(hours=6, minutes=1)
    oportunidade = nova(sessoes, "oportunidades", "oferta velha", velha)
    admin = nova(sessoes, "admin", "aviso velho", velha)
    servico(sessoes, env).ciclo()
    assert ler(sessoes, oportunidade).status is StatusMensagem.EXPIRADA
    assert ler(sessoes, admin).status is StatusMensagem.ENVIADA


@respx.mock
def test_oportunidade_reenviada_sai_mesmo_vencida(sessoes, env, configurado):
    respx.post(ROTA).mock(return_value=httpx.Response(201))
    mid = nova(sessoes, "oportunidades", "oferta", AGORA - timedelta(hours=10))
    with sessoes() as s, s.begin():
        s.get(MensagemSaida, mid).status = StatusMensagem.EXPIRADA
        repo_msg.reenviar(s, mid, AGORA)
    servico(sessoes, env).ciclo()
    assert ler(sessoes, mid).status is StatusMensagem.ENVIADA


@respx.mock
def test_validade_salva_na_tela(sessoes, env, configurado):
    respx.post(ROTA).mock(return_value=httpx.Response(201))
    with sessoes() as s, s.begin():
        repo.salvar_config_geral(s, {"validade_oportunidade_h": 1}, AGORA)
    mid = nova(sessoes, "oportunidades", "oferta", AGORA - timedelta(hours=2))
    servico(sessoes, env).ciclo()
    assert ler(sessoes, mid).status is StatusMensagem.EXPIRADA


@respx.mock
def test_ordem_e_limite_de_20_por_ciclo(sessoes, env, configurado):
    rota = respx.post(ROTA).mock(return_value=httpx.Response(201))
    for i in range(25):
        nova(sessoes, "admin", f"m{i:02d}", AGORA - timedelta(minutes=25 - i))
    assert servico(sessoes, env).ciclo() == 20
    textos = [chamada.request.read().decode() for chamada in rota.calls]
    assert '"m00"' in textos[0] and '"m19"' in textos[-1]
    with sessoes() as s:
        assert len(list(s.scalars(select(MensagemSaida).where(MensagemSaida.status == StatusMensagem.PENDENTE)))) == 5


@respx.mock
def test_ciclo_registra_que_esta_vivo(sessoes, env, configurado):
    servico(sessoes, env).ciclo()
    with sessoes() as s:
        assert s.get(EstadoNotificador, 1).ultimo_ciclo_em == AGORA


@respx.mock
def test_limpeza_roda_no_primeiro_ciclo_e_depois_a_cada_24h(sessoes, env, configurado):
    def antiga():
        with sessoes() as s, s.begin():
            m = repo_msg.enfileirar(s, "admin", "antiga", AGORA - timedelta(days=40))
            m.status = StatusMensagem.ENVIADA
            return m.id

    primeira = antiga()
    relogio = Relogio(AGORA)
    svc = servico(sessoes, env, relogio)
    svc.ciclo()
    assert ler(sessoes, primeira) is None
    segunda = antiga()
    relogio.agora = AGORA + timedelta(hours=1)
    svc.ciclo()
    assert ler(sessoes, segunda) is not None
    relogio.agora = AGORA + timedelta(hours=24)
    svc.ciclo()
    assert ler(sessoes, segunda) is None


def test_erro_no_ciclo_nao_derruba_o_laco(sessoes, env, caplog, monkeypatch):
    svc = servico(sessoes, env)
    chamadas = []

    def ciclo_quebrado():
        chamadas.append(1)
        if len(chamadas) == 1:
            raise RuntimeError("banco caiu")
        raise SystemExit

    monkeypatch.setattr(svc, "ciclo", ciclo_quebrado)
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit):
        svc.rodar()
    assert len(chamadas) == 2 and "banco caiu" in caplog.text


def test_erro_no_meio_do_lote_nao_desfaz_as_ja_enviadas(sessoes, env, configurado, monkeypatch):
    from tcg_sniper.notificador import servico as modulo
    from tcg_sniper.notificador.evolution import Resultado

    ids = [nova(sessoes, "admin", f"m{i}", AGORA - timedelta(minutes=3 - i)) for i in range(3)]
    chamadas = []

    def envio(*args):
        chamadas.append(1)
        if len(chamadas) == 2:
            raise RuntimeError("morreu no meio")
        return Resultado.OK, None

    monkeypatch.setattr(modulo, "enviar_uma_vez", envio)
    with pytest.raises(RuntimeError):
        servico(sessoes, env).ciclo()
    primeira, segunda, terceira = (ler(sessoes, i) for i in ids)
    assert primeira.status is StatusMensagem.ENVIADA
    assert (segunda.status, segunda.tentativas) == (StatusMensagem.PENDENTE, 0)
    assert (terceira.status, terceira.tentativas) == (StatusMensagem.PENDENTE, 0)
