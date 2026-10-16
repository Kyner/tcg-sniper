import base64
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fakes import T0
from fastapi.testclient import TestClient

from tcg_sniper.admin import app as modulo_app
from tcg_sniper.admin.app import criar_app
from tcg_sniper.admin.consultas import POR_PAGINA_HISTORICO, paginar
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import COLETOR_AMAZON, StatusColeta, TipoColeta

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


def test_dashboard_sem_atalho_de_configuracoes_no_bloco_da_amazon(cliente):
    texto = cliente.get("/").text
    corpo = texto.split("<main", 1)[1].split("</main>", 1)[0]
    assert "/configuracoes" not in corpo


def test_dashboard_mostra_ultimas_execucoes_e_horario(cliente, sessoes):
    with sessoes() as s, s.begin():
        c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0)
        repo.finalizar_coleta(s, c.id, StatusColeta.OK, 5, 0, T0)
        ciclo = repo.iniciar_coleta(s, TipoColeta.AMAZON, T0)
        repo.finalizar_coleta(s, ciclo.id, StatusColeta.PARCIAL, 9, 1, T0)
    texto = cliente.get("/").text
    assert "Última com sucesso" in texto and "10:00" in texto
    assert "Último ciclo" in texto and "parcial" in texto


def test_dashboard_amazon_fora_da_janela(cliente, monkeypatch):
    monkeypatch.setattr(modulo_app.repo, "agora_utc", lambda: datetime(2026, 10, 15, 23, 30, tzinfo=SP))
    assert "Fora da janela" in cliente.get("/").text
    monkeypatch.setattr(modulo_app.repo, "agora_utc", lambda: datetime(2026, 10, 15, 12, 0, tzinfo=SP))
    assert "Fora da janela" not in cliente.get("/").text


def test_historico_com_filtro_e_paginacao(cliente, sessoes):
    with sessoes() as s, s.begin():
        for i in range(25):
            c = repo.iniciar_coleta(s, TipoColeta.AMAZON, T0 + timedelta(hours=i))
            repo.finalizar_coleta(s, c.id, StatusColeta.FALHA if i % 5 == 0 else StatusColeta.OK, 1, 0, T0)
    pagina1 = cliente.get("/").text.split("Ciclos da Amazon", 1)[1]
    assert pagina1.count("<td>amazon</td>") == 20
    assert "amazon_pagina=2" in pagina1 and "liga_status=todos" in pagina1
    pagina2 = cliente.get("/?amazon_pagina=2").text.split("Ciclos da Amazon", 1)[1]
    assert pagina2.count("<td>amazon</td>") == 5
    alem = cliente.get("/?amazon_pagina=999").text.split("Ciclos da Amazon", 1)[1]
    assert alem.count("<td>amazon</td>") == 5
    falhas = cliente.get("/?amazon_status=falha").text.split("Ciclos da Amazon", 1)[1]
    assert falhas.count("<td>amazon</td>") == 5
    assert 'value="falha" selected' in falhas
    assert cliente.get("/?amazon_status=xyz").status_code == 400
    assert cliente.get("/?liga_pagina=abc").status_code == 200


def test_servicos_mostra_os_botoes_por_estado(cliente, sessoes):
    texto = cliente.get("/servicos").text
    assert "Rodar agora" in texto and "Pausar (Amazon)" in texto and "Retomar (Amazon)" not in texto
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em /x", T0)
        repo.pausar_por_desafio(s, "desafio em /y", T0, COLETOR_AMAZON)
    texto = cliente.get("/servicos").text
    assert "host.test:6080" in texto and "host.test:6081" in texto
    assert "Retomar (Amazon)" in texto and "Pausar (Amazon)" not in texto and "Rodar agora" not in texto


@pytest.mark.parametrize(
    ("rota", "codigo", "mensagem"),
    [
        ("/rodar-agora", "rodar", "Execução da LigaMagic solicitada"),
        ("/retomar", "retomar", "Coleta da LigaMagic retomada"),
        ("/amazon/pausar", "amazon_pausar", "Busca na Amazon pausada"),
        ("/amazon/retomar", "amazon_retomar", "Busca na Amazon retomada"),
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


def test_dashboard_tem_indicadores_e_abas(cliente):
    texto = cliente.get("/").text
    assert 'class="stats' in texto
    for rotulo in ("LigaMagic", "Amazon", "WhatsApp", "Oportunidades abertas", "Casamentos pendentes"):
        assert rotulo in texto
    assert 'aria-label="Coletas da LigaMagic"' in texto and 'aria-label="Ciclos da Amazon"' in texto


def test_aba_da_amazon_abre_depois_de_paginar_ou_filtrar(cliente, sessoes):
    def aba_marcada(texto, rotulo):
        inicio = texto.index(f'aria-label="{rotulo}"')
        return "checked" in texto[texto.rindex("<input", 0, inicio):inicio + 60]

    with sessoes() as s, s.begin():
        for i in range(POR_PAGINA_HISTORICO + 1):
            for tipo in (TipoColeta.AMAZON, TipoColeta.LISTAGEM):
                c = repo.iniciar_coleta(s, tipo, T0 + timedelta(minutes=i))
                repo.finalizar_coleta(s, c.id, StatusColeta.OK, 1, 0, T0 + timedelta(minutes=i))

    assert not aba_marcada(cliente.get("/").text, "Ciclos da Amazon")
    assert aba_marcada(cliente.get("/", params={"amazon_status": "ok"}).text, "Ciclos da Amazon")
    assert aba_marcada(cliente.get("/", params={"amazon_pagina": "2"}).text, "Ciclos da Amazon")
    liga = cliente.get("/", params={"liga_pagina": "2", "amazon_pagina": "1"}).text
    assert aba_marcada(liga, "Coletas da LigaMagic")
    assert not aba_marcada(liga, "Ciclos da Amazon")


def test_situacao_das_coletas_tem_selo(cliente, sessoes):
    with sessoes() as s, s.begin():
        c = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0)
        repo.finalizar_coleta(s, c.id, StatusColeta.FALHA, 0, 1, T0)
    assert 'badge-error">falha</span>' in cliente.get("/").text
