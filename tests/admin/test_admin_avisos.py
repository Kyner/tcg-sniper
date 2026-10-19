import base64
import html

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tcg_sniper.admin.app import criar_app
from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import CATALOGO, TipoAviso
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import COLETOR_LIGA, MensagemSaida


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def textos(sessoes):
    with sessoes() as s:
        return [m.texto for m in s.scalars(select(MensagemSaida).order_by(MensagemSaida.id))]


def test_aba_avisos_lista_todos_os_tipos_com_exemplo_e_toggle(cliente):
    texto = cliente.get("/configuracoes").text
    assert 'aria-label="Avisos"' in texto
    for definicao in CATALOGO.values():
        assert html.escape(definicao.titulo) in texto
    assert texto.count('action="/configuracoes/avisos"') == len(TipoAviso)
    assert texto.count('class="toggle toggle-success"') == len(TipoAviso)
    assert "💰 *Oportunidade · 18% abaixo da Liga*" in texto
    assert "https://www.amazon.com.br/dp/B0TESTE123" in texto


def test_desligar_e_religar_um_tipo(cliente, sessoes):
    r = cliente.post(
        "/configuracoes/avisos", data={"tipo": "amazon_monitor_concluido", "ligado": "0"}, follow_redirects=False
    )
    assert r.status_code == 303 and r.headers["location"] == "/configuracoes?msg=avisos"
    with sessoes() as s:
        assert avisos.ligados(s)[TipoAviso.AMAZON_MONITOR_CONCLUIDO] is False
    pagina = cliente.get(r.headers["location"]).text
    assert "Salvo; vale a partir do próximo aviso." in pagina
    assert 'aria-label="Avisos" checked' in pagina
    cliente.post("/configuracoes/avisos", data={"tipo": "amazon_monitor_concluido", "ligado": "1"})
    with sessoes() as s:
        assert avisos.ligados(s)[TipoAviso.AMAZON_MONITOR_CONCLUIDO] is True


def test_tipo_desconhecido_e_400(cliente):
    r = cliente.post("/configuracoes/avisos", data={"tipo": "nao_existe", "ligado": "0"})
    assert r.status_code == 400


def test_pausar_e_retomar_no_admin_avisam(cliente, sessoes):
    cliente.post("/casador/pausar")
    cliente.post("/casador/retomar")
    pausado, retomado = textos(sessoes)
    assert pausado.startswith("🟡 *Serviço mudou no admin · Casador (IA)*\n• Novo estado: pausado\n")
    assert retomado.startswith("🟡 *Serviço mudou no admin · Casador (IA)*\n• Novo estado: ativo\n")


@pytest.mark.parametrize(
    ("rota", "nome"),
    [
        ("/liga/pausar", "LigaMagic"),
        ("/amazon/pausar", "Amazon"),
        ("/notificador/pausar", "WhatsApp (notificador)"),
        ("/manutencao/pausar", "Backup (manutenção)"),
    ],
)
def test_cada_pausa_diz_o_servico(cliente, sessoes, rota, nome):
    cliente.post(rota)
    [texto] = textos(sessoes)
    assert texto.startswith(f"🟡 *Serviço mudou no admin · {nome}*")


def test_desligar_com_desafio_pendente_nao_avisa(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio", repo.agora_utc(), COLETOR_LIGA)
    cliente.post("/liga/pausar")
    assert textos(sessoes) == []


def test_explicacao_do_host_nao_fala_mais_em_mensagens(cliente):
    texto = cliente.get("/configuracoes").text
    assert "As mensagens do WhatsApp nunca levam este endereço." in texto


def test_aba_avisos_mostra_destino_e_severidade_de_acesso(cliente):
    texto = cliente.get("/configuracoes").text
    assert 'badge-ghost badge-sm">só para a pessoa</span>' in texto
    assert 'badge-ghost badge-sm">grupo admin</span>' in texto
    assert 'badge-neutral badge-sm">Acesso</span>' in texto
