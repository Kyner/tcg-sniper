import base64
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fakes import T0
from fastapi.testclient import TestClient

from tcg_sniper.admin import app as modulo_app
from tcg_sniper.admin.app import criar_app
from tcg_sniper.admin.consultas import paginar
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_manutencao as repo_man
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import COLETOR_AMAZON, StatusColeta, StatusManutencao, TipoColeta

SP = ZoneInfo("America/Sao_Paulo")


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def test_paginar():
    assert paginar(list(range(45)), 3, 20) == (list(range(40, 45)), 3, 3)
    assert paginar(list(range(45)), 99, 20) == (list(range(40, 45)), 3, 3)
    assert paginar([], 1, 20) == ([], 1, 1)
    assert paginar(list(range(5)), 0, 20) == (list(range(5)), 1, 1)


def test_dashboard_nao_tem_comandos(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em /x", T0)
        repo.pausar(s, "pausado no admin", T0, COLETOR_AMAZON)
    texto = cliente.get("/").text
    assert 'method="post"' not in texto.lower()
    assert "Rodar agora" not in texto and "Retomar" not in texto and "Pausar" not in texto
    assert "desafio em /x" in texto and "pausado no admin" in texto
    assert 'href="/servicos"' in texto


def card(texto, nome):
    inicio = texto.index(f'data-servico="{nome}"')
    return texto[inicio:texto.index("</div></div>", inicio)]


def test_dashboard_sem_atalho_de_configuracoes_no_bloco_da_amazon(cliente):
    texto = cliente.get("/").text
    assert "/configuracoes" not in card(texto, "Amazon (busca)")
    assert "/configuracoes" not in card(texto, "Amazon (monitor e checkout)")


def test_dashboard_mostra_ultimas_execucoes_e_horario(cliente, sessoes, monkeypatch):
    # relógio fixo dentro da janela da Amazon (08:00–22:00): fora dela o card mostra "fora do horário"
    monkeypatch.setattr(modulo_app.repo, "agora_utc", lambda: datetime(2026, 10, 13, 12, 0, tzinfo=SP))
    with sessoes() as s, s.begin():
        c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0)
        repo.finalizar_coleta(s, c.id, StatusColeta.OK, 5, 0, T0)
        ciclo = repo.iniciar_coleta(s, TipoColeta.AMAZON, T0)
        repo.finalizar_coleta(s, ciclo.id, StatusColeta.PARCIAL, 9, 1, T0)
    texto = cliente.get("/").text
    liga = card(texto, "LigaMagic")
    assert "Última coleta ok" in liga and "10:00" in liga and 'badge-success">funcionando' in liga
    assert "Último ciclo" in card(texto, "Amazon (busca)") and "(parcial)" in card(texto, "Amazon (busca)")


def test_dashboard_amazon_fora_da_janela(cliente, monkeypatch):
    monkeypatch.setattr(modulo_app.repo, "agora_utc", lambda: datetime(2026, 10, 15, 23, 30, tzinfo=SP))
    assert "fora do horário (08:00–22:00)" in card(cliente.get("/").text, "Amazon (busca)")
    monkeypatch.setattr(modulo_app.repo, "agora_utc", lambda: datetime(2026, 10, 15, 12, 0, tzinfo=SP))
    assert "fora do horário" not in card(cliente.get("/").text, "Amazon (busca)")


def test_dashboard_nao_tem_mais_o_historico(cliente, sessoes):
    with sessoes() as s, s.begin():
        c = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0)
        repo.finalizar_coleta(s, c.id, StatusColeta.OK, 1, 0, T0)
    texto = cliente.get("/").text
    assert "<table" not in texto and 'aria-label="Coletas da LigaMagic"' not in texto
    assert 'href="/logs"' in texto.split("<main", 1)[1]


def test_dashboard_tem_servicos_numeros_e_atividade(cliente):
    texto = cliente.get("/").text
    for nome in ("LigaMagic", "Amazon (busca)", "Amazon (monitor e checkout)", "Casador (IA)", "WhatsApp", "Backup"):
        assert f'data-servico="{nome}"' in texto
    for rotulo in ("Casamentos", "Casados", "Sem candidato", "Produtos avaliados", "Esperando a IA",
                   "Gasto do mês", "Oportunidades", "Alertas na semana", "Atividade de hoje", "Mensagens do WhatsApp"):
        assert rotulo in texto
    assert 'class="stats' in texto and 'class="progress' in texto and 'class="list"' in texto


def backup_em_dia(s):
    """Serviço de manutenção vivo e com um backup ok recente (sem aviso de backup)."""
    agora = repo.agora_utc()
    repo_man.registrar_ciclo(s, agora)
    e = repo_man.iniciar(s, agora - timedelta(hours=1))
    repo_man.finalizar(
        s, e.id, agora, StatusManutencao.SO_LOCAL, arquivo="tcg-diario.dump", tamanho_bytes=1, enviado_r2=False,
        apagados={}, erro=None,
    )


def test_sem_problemas_sem_aviso(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo_msg.registrar_ciclo(s, repo.agora_utc())
        backup_em_dia(s)
    assert 'role="alert"' not in cliente.get("/").text


def test_um_aviso_por_problema_com_link(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo_msg.registrar_ciclo(s, repo.agora_utc())
        backup_em_dia(s)
        repo.pausar(s, "pausado no admin", T0, COLETOR_AMAZON)
        c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0)
        repo.finalizar_coleta(s, c.id, StatusColeta.FALHA, 0, 9, T0, erro="interrompida")
    texto = cliente.get("/").text
    assert texto.count('role="alert"') == 2
    assert 'href="/servicos">Ir para Serviços' in texto and 'href="/logs?aba=liga">Ver nos logs' in texto
    assert 'badge-warning">atenção' in card(texto, "LigaMagic")


def test_servicos_mostra_os_botoes_por_estado(cliente, sessoes):
    texto = cliente.get("/servicos").text
    assert 'action="/rodar-agora"' in texto and 'action="/amazon/pausar"' in texto
    assert 'action="/amazon/retomar"' not in texto
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em /x", T0)
        repo.pausar_por_desafio(s, "desafio em /y", T0, COLETOR_AMAZON)
    texto = cliente.get("/servicos").text
    assert "host.test:6080" in texto and "host.test:6081" in texto
    assert 'action="/amazon/retomar"' in texto and 'action="/amazon/pausar"' not in texto
    assert 'action="/rodar-agora"' not in texto


@pytest.mark.parametrize(
    ("rota", "codigo", "mensagem"),
    [
        ("/rodar-agora", "rodar", "Execução da LigaMagic solicitada"),
        ("/retomar", "retomar", "Coleta da LigaMagic retomada"),
        ("/amazon/pausar", "amazon_pausar", "Monitor e checkout da Amazon pausados"),
        ("/amazon/retomar", "amazon_retomar", "Monitor e checkout da Amazon retomados"),
    ],
)
def test_acoes_voltam_para_servicos_com_mensagem(cliente, rota, codigo, mensagem):
    r = cliente.post(rota, follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, f"/servicos?msg={codigo}")
    assert mensagem in cliente.get(r.headers["location"]).text


def test_servicos_ignora_mensagem_desconhecida(cliente):
    assert "<script>" not in cliente.get("/servicos?msg=<script>").text.split("<main", 1)[1].split("</main>", 1)[0]


def test_menu(cliente):
    texto = cliente.get("/").text
    nav = texto[texto.index('<ul class="menu'):texto.index("</ul>", texto.index('<ul class="menu'))]
    for rotulo in ("Dashboard", "Serviços", "Catálogo", "Casamentos", "Ofertas", "Configurações"):
        assert rotulo in nav
    assert ">Status<" not in nav


def test_notificador_desligado_nao_avisa_pendentes_paradas(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo_msg.registrar_ciclo(s, repo.agora_utc())
        repo_msg.enfileirar(s, "admin", "x", repo.agora_utc() - timedelta(hours=1))
    assert "Mensagens do WhatsApp paradas" in cliente.get("/").text
    cliente.post("/notificador/pausar")
    texto = cliente.get("/").text
    assert "Mensagens do WhatsApp paradas" not in texto
    assert "WhatsApp — Envio desligado" in texto and "ofertas vencidas expiram" in texto


def test_dashboard_tem_os_dois_cards_da_amazon(cliente):
    texto = cliente.get("/").text
    assert 'data-servico="Amazon (busca)"' in texto and 'data-servico="Amazon (monitor e checkout)"' in texto
    assert "buscas na última hora" in texto and "produtos ativos nunca buscados" in texto
