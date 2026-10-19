"""Ponta a ponta: a API (uvicorn) e o build do front (servido pelo `vite preview`, que repassa /api como o Caddy)
contra o banco de teste. O usuário pede o código, o teste lê o código na fila e entra; o papel grupo não entra na
gestão até a grade liberar `ver_area_gestao`. Também confere o layout das telas novas.

Só roda com TCG_E2E=1; antes: `cd web && npm ci && npm run build` e `uv run playwright install chromium`
(com PLAYWRIGHT_BROWSERS_PATH apontando para .playwright-navegadores/ do checkout). Os dois servidores são
parados no fim, passe ou falhe."""

import importlib.util
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fakes_api import SEGREDO_TESTE
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Papel
from tcg_sniper.db.repositorio import agora_utc

pytestmark = pytest.mark.skipif(os.environ.get("TCG_E2E") != "1", reason="ponta a ponta: rode com TCG_E2E=1")

RAIZ = Path(__file__).resolve().parents[2]
PORTA_API, PORTA_WEB = 8101, 4174
BASE = f"http://127.0.0.1:{PORTA_WEB}"
ADMIN, GRUPO = "+5511900000001", "+5511900000002"
TABELAS = "sessao, codigo_acesso, pedido_codigo, permissao_papel, mensagem_saida, estado_aviso, usuario"


def esperar(url: str, limite_s: float = 40) -> None:
    fim = time.monotonic() + limite_s
    while time.monotonic() < fim:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"{url} não respondeu em {limite_s:.0f} s")


def parar(processo: subprocess.Popen) -> None:
    processo.terminate()
    try:
        processo.wait(timeout=10)
    except subprocess.TimeoutExpired:
        processo.kill()
        processo.wait(timeout=10)


@pytest.fixture(scope="module")
def servidores(engine):
    if not (RAIZ / "web" / "dist" / "index.html").exists():
        pytest.fail("falta o build do front: cd web && npm ci && npm run build")
    ambiente = {
        **os.environ,
        "DATABASE_URL": engine.url.render_as_string(hide_password=False),
        "SEGREDO_API": SEGREDO_TESTE,  # segredo falso; nunca o do .env
        "API_ALVO": f"http://127.0.0.1:{PORTA_API}",
    }
    codigo_api = f"from tcg_sniper.cli import main; main(['api', '--porta', '{PORTA_API}'])"
    api = subprocess.Popen([sys.executable, "-c", codigo_api], cwd=RAIZ, env=ambiente)
    vite = RAIZ / "web" / "node_modules" / "vite" / "bin" / "vite.js"
    web = subprocess.Popen(
        ["node", str(vite), "preview", "--host", "127.0.0.1", "--port", str(PORTA_WEB), "--strictPort"],
        cwd=RAIZ / "web", env=ambiente,
    )
    try:
        esperar(f"http://127.0.0.1:{PORTA_API}/api/saude")
        esperar(f"{BASE}/api/saude")
        yield BASE
    finally:
        parar(web)
        parar(api)


@pytest.fixture
def usuarios(engine):
    """Superadmin e grupo gravados de verdade (a API roda em outro processo); tudo apagado no fim."""
    with sessionmaker(bind=engine)() as s, s.begin():
        repo_acesso.criar_superadmin(s, "Pessoa Admin", ADMIN, agora_utc())
        repo_acesso.criar_usuario(s, "Pessoa Grupo", GRUPO, Papel.GRUPO, agora_utc())
    yield
    with engine.begin() as conexao:
        conexao.execute(text(f"TRUNCATE {TABELAS} RESTART IDENTITY CASCADE"))


def ler_codigo(engine, numero: str) -> str:
    with engine.connect() as conexao:
        texto = conexao.execute(
            text(
                "SELECT texto FROM mensagem_saida WHERE destino = 'individual' AND numero = :numero "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"numero": numero},
        ).scalar_one()
    return re.search(r"\*(\d{6})\*", texto).group(1)


def entrar(pagina, expect, engine, numero: str, digitado: str) -> None:
    pagina.goto(BASE + "/entrar")
    pagina.get_by_label("Número do WhatsApp").fill(digitado)
    pagina.get_by_role("button", name="Receber código").click()
    campo = pagina.get_by_label("Código", exact=True)
    expect(campo).to_be_visible()  # o pedido terminou: o código já está na fila
    campo.fill(ler_codigo(engine, numero))
    pagina.get_by_role("button", name="Entrar", exact=True).click()
    # Espera a tela inicial: sem isso o próximo goto pode cortar a resposta do entrar antes de o cookie ser gravado.
    expect(pagina.get_by_role("heading", name="Área de negócio")).to_be_visible()


def test_grupo_so_entra_na_gestao_depois_de_liberado(servidores, usuarios, engine):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        try:
            grupo = navegador.new_context().new_page()
            entrar(grupo, expect, engine, GRUPO, "(11) 90000-0002")
            expect(grupo.get_by_role("heading", name="Área de negócio")).to_be_visible()
            grupo.goto(BASE + "/gestao")
            expect(grupo.get_by_role("heading", name="Sem acesso")).to_be_visible()
            assert grupo.request.get(BASE + "/api/usuarios").status == 403  # direto na API também

            admin = navegador.new_context().new_page()
            entrar(admin, expect, engine, ADMIN, "11 90000-0001")
            admin.goto(BASE + "/gestao/acessos")
            toggle = admin.get_by_label("Grupo: Entrar na área de gestão")
            expect(toggle).not_to_be_checked()
            toggle.click()
            expect(admin.get_by_text("Salvo. Vale na próxima ação de quem já está logado.")).to_be_visible()
            expect(toggle).to_be_checked()

            grupo.goto(BASE + "/gestao")
            expect(grupo.get_by_role("heading", name="Gestão", exact=True)).to_be_visible()
        finally:
            navegador.close()


def _verificar_layout():
    spec = importlib.util.spec_from_file_location("verificar_layout", RAIZ / "scripts" / "verificar_layout.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_telas_novas_cabem_na_tela_nos_dois_temas(servidores, usuarios, engine, tmp_path):
    from playwright.sync_api import sync_playwright

    httpx.post(BASE + "/api/auth/pedir-codigo", json={"numero": ADMIN}, timeout=10).raise_for_status()
    layout = _verificar_layout()
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        try:
            estado = layout.entrar_no_web(navegador, BASE, ADMIN, ler_codigo(engine, ADMIN))
            problemas = layout.verificar_web(navegador, BASE, estado, tmp_path)
        finally:
            navegador.close()
    assert problemas == []
