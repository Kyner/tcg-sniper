import base64
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tcg_sniper.admin import consultas_painel as painel
from tcg_sniper.admin.app import criar_app
from tcg_sniper.admin.consultas import POR_PAGINA_HISTORICO
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_manutencao as repo_man
from tcg_sniper.db.models import COLETOR_MANUTENCAO, EstadoColetorTipo, StatusManutencao
from tcg_sniper.formatacao import formatar_bytes

AGORA = datetime(2026, 10, 16, 19, 40, tzinfo=UTC)  # 16:40 em São Paulo


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def execucao(s, inicio, status=StatusManutencao.OK, **campos):
    e = repo_man.iniciar(s, inicio)
    if status is not StatusManutencao.RODANDO:
        valores = {
            "arquivo": f"tcg-diario-{inicio:%Y-%m-%d}.dump", "tamanho_bytes": 12_345_678, "enviado_r2": True,
            "apagados": {"chamada_ia": 3, "conferencia_checkout": 0, "coleta": 1}, "erro": None, **campos,
        }
        repo_man.finalizar(s, e.id, inicio + timedelta(minutes=2), status, **valores)
    return e


def backup(s, config, agora=AGORA):
    return painel.saude_backup(s, agora, config)


def test_formatar_bytes():
    assert [formatar_bytes(n) for n in (None, 0, 900, 2048, 12_345_678, 5 * 1024**3)] == [
        "—", "0 B", "900 B", "2,0 KB", "11,8 MB", "5,0 GB"
    ]


# --- card do Dashboard ---------------------------------------------------------------------------


def test_servico_nunca_rodou(s, config):
    b = backup(s, config)
    assert (b.nome, b.situacao) == ("Backup", "falha")
    assert [a.texto for a in painel.avisos_backup(b)] == ["O serviço de manutenção (backup) nunca rodou — veja Serviços."]


def test_servico_parado(s, config):
    repo_man.registrar_ciclo(s, AGORA - timedelta(minutes=30))
    b = backup(s, config)
    assert b.situacao == "falha" and "parado desde hoje 16:10" in b.texto


def test_ok_com_tamanho_e_r2(s, config):
    repo_man.registrar_ciclo(s, AGORA)
    execucao(s, AGORA - timedelta(hours=12, minutes=40))  # hoje 04:00
    b = backup(s, config)
    assert (b.situacao, b.texto) == ("ok", "Último backup hoje 04:00 · 11,8 MB")
    assert "cópia no R2: sim" in b.detalhe and "04:00" in b.detalhe
    assert painel.avisos_backup(b) == []


def test_so_local(s, config):
    repo_man.registrar_ciclo(s, AGORA)
    execucao(s, AGORA - timedelta(hours=12), StatusManutencao.SO_LOCAL, enviado_r2=False)
    b = backup(s, config)
    assert b.situacao == "ok" and "cópia no R2: não (só local)" in b.detalhe


def test_ultimo_ok_velho_vira_atencao_com_aviso(s, config):
    repo_man.registrar_ciclo(s, AGORA)
    execucao(s, AGORA - timedelta(hours=27))
    b = backup(s, config)
    assert b.situacao == "parcial" and "mais de 26 h" in b.texto
    (aviso,) = painel.avisos_backup(b)
    assert (aviso.tipo, aviso.link) == ("warning", "/logs?aba=manutencao")


def test_nenhum_backup_ainda(s, config):
    repo_man.registrar_ciclo(s, AGORA)
    b = backup(s, config)
    assert (b.situacao, b.texto) == ("parcial", "Nenhum backup ainda")


def test_ultima_execucao_com_erro(s, config):
    repo_man.registrar_ciclo(s, AGORA)
    execucao(s, AGORA - timedelta(hours=30))
    execucao(s, AGORA - timedelta(hours=6), StatusManutencao.ERRO, enviado_r2=False, erro="envio ao R2 falhou: X")
    b = backup(s, config)
    assert b.situacao == "parcial" and "erro" in b.texto and "envio ao R2 falhou" in b.detalhe
    assert painel.avisos_backup(b)[0].tipo == "warning"


def test_rodando_e_desligado(s, config):
    repo_man.registrar_ciclo(s, AGORA)
    execucao(s, AGORA - timedelta(minutes=1), StatusManutencao.RODANDO)
    assert backup(s, config).situacao == "rodando"
    repo.pausar(s, "pausado no admin", AGORA, COLETOR_MANUTENCAO)
    b = backup(s, config)
    assert b.situacao == "pausado" and painel.avisos_backup(b)[0].tipo == "error"


def test_dashboard_mostra_o_card_backup(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo_man.registrar_ciclo(s, repo.agora_utc())
        execucao(s, repo.agora_utc() - timedelta(hours=1))
    texto = cliente.get("/").text
    assert 'data-servico="Backup"' in texto and "11,8 MB" in texto


# --- Serviços ------------------------------------------------------------------------------------


def card(texto, servico):
    inicio = texto.index(f'data-servico="{servico}"')
    fim = texto.find('data-servico="', inicio + 1)
    return texto[inicio:fim if fim > 0 else len(texto)]


def test_card_de_servicos_liga_e_desliga(cliente, sessoes):
    c = card(cliente.get("/servicos").text, "manutencao")
    assert 'action="/manutencao/pausar"' in c and 'class="toggle toggle-success" checked' in c
    assert 'href="/logs?aba=manutencao"' in c and "04:00" in c and "só local" in c
    r = cliente.post("/manutencao/pausar", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/servicos?msg=manutencao_pausar")
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_MANUTENCAO).estado is EstadoColetorTipo.PAUSADO
    c = card(cliente.get(r.headers["location"]).text, "manutencao")
    assert 'action="/manutencao/retomar"' in c and 'badge-error">desligado</span>' in c
    r = cliente.post("/manutencao/retomar", follow_redirects=False)
    assert r.headers["location"] == "/servicos?msg=manutencao_retomar"
    with sessoes() as s:
        estado = repo.obter_estado(s, coletor=COLETOR_MANUTENCAO)
        assert (estado.estado, estado.execucao_solicitada) == (EstadoColetorTipo.ATIVO, False)


def test_card_de_servicos_com_r2(sessoes, config):
    c = config.model_copy(update={
        "admin_senha": "segredo", "r2_account_id": "conta", "r2_bucket": "balde",
        "r2_access_key_id": SecretStr("id"), "r2_secret_access_key": SecretStr("segredo-r2"),
    })
    cliente = TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})
    texto = cliente.get("/servicos").text
    assert "cópia no R2" in card(texto, "manutencao") and "segredo-r2" not in texto


# --- Logs ----------------------------------------------------------------------------------------


def test_aba_manutencao_lista_e_pagina(cliente, sessoes):
    with sessoes() as s, s.begin():
        for i in range(POR_PAGINA_HISTORICO + 1):
            execucao(s, AGORA - timedelta(days=i))
        execucao(s, AGORA + timedelta(hours=1), StatusManutencao.ERRO, arquivo=None, tamanho_bytes=None,
                 enviado_r2=False, apagados=None, erro="pg_dump falhou (código 1): sem conexão")
    texto = cliente.get("/logs?aba=manutencao").text
    inicio = texto.index('aria-label="Manutenção"')
    trecho = texto[inicio:]
    assert "checked" in texto[texto.rindex("<input", 0, inicio):inicio + 60]
    assert trecho.count("data-execucao=") == POR_PAGINA_HISTORICO
    assert "pg_dump falhou (código 1): sem conexão" in trecho and "11,8 MB" in trecho
    assert "chamada_ia 3" in trecho and "só local" not in trecho
    assert "manutencao_pagina=2" in trecho and "aba=manutencao" in trecho
    pagina2 = cliente.get("/logs?aba=manutencao&manutencao_pagina=2").text
    assert pagina2[pagina2.index('aria-label="Manutenção"'):].count("data-execucao=") == 2


def test_aba_manutencao_vazia(cliente):
    texto = cliente.get("/logs?aba=manutencao").text
    assert "Nenhuma execução da manutenção ainda." in texto
