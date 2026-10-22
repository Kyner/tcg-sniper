"""Ponta a ponta: a API (uvicorn) e o build do front (servido pelo `vite preview`, que repassa /api como o Caddy)
contra o banco de teste. O usuário pede o código, o teste lê o código na fila e entra; o papel grupo não entra na
gestão até a grade liberar `ver_area_gestao`. Também confere o layout das telas novas.

Só roda com TCG_E2E=1; antes: `cd web && npm ci && npm run build` e `uv run playwright install chromium`
(com PLAYWRIGHT_BROWSERS_PATH apontando para .playwright-navegadores/ do checkout; sem a variável, o teste usa
essa pasta). Os dois servidores são parados no fim, passe ou falhe, um sem depender do outro (no Windows, a
árvore de processos inteira)."""

import importlib.util
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import fakes
import fakes_oportunidades
import httpx
import pytest
from fakes_api import SEGREDO_TESTE
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Papel, StatusCasamento
from tcg_sniper.db.repositorio import agora_utc

pytestmark = pytest.mark.skipif(os.environ.get("TCG_E2E") != "1", reason="ponta a ponta: rode com TCG_E2E=1")

RAIZ = Path(__file__).resolve().parents[2]
PORTA_API, PORTA_WEB = 8101, 4174
BASE = f"http://127.0.0.1:{PORTA_WEB}"
ADMIN, GRUPO = "+5511900000001", "+5511900000002"
TABELAS = (
    "sessao, codigo_acesso, pedido_codigo, permissao_papel, mensagem_saida, estado_aviso, usuario, "
    "oportunidade, preco_atual_amazon, preco_amazon, casamento, preco_atual_liga, anuncio_amazon, produto_liga"
)


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


def parar(processo: subprocess.Popen | None) -> None:
    """Para o processo e o que ele abriu. No Windows o terminate() não alcança os filhos: taskkill /T /F na árvore
    (e kill() se o taskkill falhar); fora dele, terminate() e kill() se não sair em 10 s."""
    if processo is None or processo.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(processo.pid), "/T", "/F"], capture_output=True, check=False)
    else:
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
    navegadores_antes = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if navegadores_antes is None:  # o Chromium do teste fica no checkout, nunca na pasta do usuário
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(RAIZ / ".playwright-navegadores")
    codigo_api = f"from tcg_sniper.cli import main; main(['api', '--porta', '{PORTA_API}'])"
    vite = RAIZ / "web" / "node_modules" / "vite" / "bin" / "vite.js"
    api = web = None
    try:
        api = subprocess.Popen([sys.executable, "-c", codigo_api], cwd=RAIZ, env=ambiente)
        web = subprocess.Popen(
            ["node", str(vite), "preview", "--host", "127.0.0.1", "--port", str(PORTA_WEB), "--strictPort"],
            cwd=RAIZ / "web", env=ambiente,
        )
        esperar(f"http://127.0.0.1:{PORTA_API}/api/saude")
        esperar(f"{BASE}/api/saude")
        yield BASE
    finally:
        try:
            parar(web)
        finally:
            parar(api)
            if navegadores_antes is None:
                os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)


@pytest.fixture
def usuarios(engine):
    """Superadmin, grupo e um produto com oportunidade aberta gravados de verdade (a API roda em outro processo); tudo apagado no fim."""
    with sessionmaker(bind=engine)() as s, s.begin():
        repo_acesso.criar_superadmin(s, "Pessoa Admin", ADMIN, agora_utc())
        repo_acesso.criar_usuario(s, "Pessoa Grupo", GRUPO, Papel.GRUPO, agora_utc())
        produto = fakes.criar_produto(s)
        fakes.criar_preco_liga(s, produto, "1000")
        anuncio = fakes.criar_anuncio(s, produto=produto, status=StatusCasamento.CONFIRMADO)
        fakes_oportunidades.criar_oportunidade(s, anuncio, produto, aberta_em=agora_utc())
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
    expect(pagina.get_by_role("heading", name="Oportunidades", exact=True)).to_be_visible()


def test_grupo_so_entra_na_gestao_depois_de_liberado(servidores, usuarios, engine):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        try:
            grupo = navegador.new_context().new_page()
            entrar(grupo, expect, engine, GRUPO, "(11) 90000-0002")
            expect(grupo.get_by_role("heading", name="Oportunidades", exact=True)).to_be_visible()
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


def test_grupo_ve_oportunidade_e_abre_o_produto(servidores, usuarios, engine):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        try:
            pagina = navegador.new_context().new_page()
            erros_csp = []
            pagina.on("console", lambda m: erros_csp.append(m.text) if "Content Security Policy" in m.text else None)
            entrar(pagina, expect, engine, GRUPO, "(11) 90000-0002")
            expect(pagina.get_by_role("region", name="Ativas agora")).to_be_visible()
            pagina.get_by_role("link", name="Histórico do produto").first.click()
            expect(pagina.get_by_role("figure", name=re.compile("Curva de preço"))).to_be_visible()
            assert erros_csp == []
        finally:
            navegador.close()


NOME_LONGO = (
    "Colecao Especial de Aniversario Edicao Limitada Caixa de Boosters de Colecionador Em Portugues Com Brinde Exclusivo "
    "Numerado"
)[:120]
assert len(NOME_LONGO) == 120


@pytest.fixture
def gestao(usuarios, engine):
    """Três produtos para as telas de gestão: dois da categoria "Booster Box" com anúncios pendentes e um de nome com
    120 caracteres, sem foto, da categoria "Deck". O apagão no fim vem da fixture `usuarios`."""
    with sessionmaker(bind=engine)() as s, s.begin():
        alfa = fakes.criar_produto(s, "g-alfa", nome="Caixa Alfa")
        beta = fakes.criar_produto(s, "g-beta", nome="Caixa Beta")
        longo = fakes.criar_produto(s, "g-longo", nome=NOME_LONGO)
        for produto, tipo, preco in ((alfa, "Booster Box", "100"), (beta, "Booster Box", "200"), (longo, "Deck", "300")):
            produto.tipo = tipo
            fakes.criar_preco_liga(s, produto, preco)
        fakes.criar_anuncio(s, "B0ALFA0001", alfa)
        fakes.criar_anuncio(s, "B0ALFA0002", alfa)
        fakes.criar_anuncio(s, "B0BETA0001", beta)
        fakes.criar_anuncio(s, "B0LONGO001", longo)
        ids = {"alfa": alfa.id, "beta": beta.id, "longo": longo.id}
    return ids


def _ativo(engine, liga_id: str, esperado: bool, limite_s: float = 10) -> bool:
    """O valor gravado de `ativo`, esperando até `limite_s` s que chegue ao `esperado` (a tela pinta antes de a API gravar)."""
    fim = time.monotonic() + limite_s
    while True:
        with engine.connect() as conexao:
            valor = conexao.execute(text("SELECT ativo FROM produto_liga WHERE liga_id = :l"), {"l": liga_id}).scalar_one()
        if valor == esperado or time.monotonic() > fim:
            return valor
        time.sleep(0.2)


def test_revisao_de_casamentos_e_catalogo_ponta_a_ponta(servidores, gestao, engine):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        try:
            pagina = navegador.new_context().new_page()
            entrar(pagina, expect, engine, ADMIN, "11 90000-0001")

            # Casamentos: filtra pela busca, revisa em sequência, confirma um anúncio sem recarregar, vai ao próximo
            # produto e volta à lista com o filtro.
            pagina.goto(BASE + "/gestao/casamentos")
            pagina.get_by_label("Buscar").fill("Caixa")
            expect(pagina).to_have_url(re.compile(r"busca=Caixa"))
            pagina.get_by_role("link", name="Revisar em sequência").click()
            expect(pagina.get_by_role("heading", name="Para decidir (", exact=False)).to_be_visible()
            pagina.evaluate("window.__sem_recarga = true")
            para_decidir = pagina.get_by_role("list", name="Para decidir")
            antes = para_decidir.get_by_role("listitem").count()
            assert antes >= 1
            para_decidir.get_by_role("button", name=re.compile("é o mesmo")).first.click()
            expect(pagina.get_by_role("heading", name=re.compile(r"Confirmados \(1\)"))).to_be_visible()
            expect(para_decidir.get_by_role("listitem")).to_have_count(antes - 1)
            assert pagina.evaluate("window.__sem_recarga === true")  # o cartão mudou de grupo sem recarregar a página
            pagina.get_by_role("link", name=re.compile("Próximo")).click()
            expect(pagina.get_by_role("heading", name=re.compile(r"Para decidir \("))).to_be_visible()
            pagina.get_by_role("link", name="Voltar à lista").click()
            expect(pagina).to_have_url(re.compile(r"/gestao/casamentos\?.*busca=Caixa"))
            expect(pagina.get_by_label("Buscar")).to_have_value("Caixa")

            # Catálogo: um produto desligado pela chave e um lote de 2 pelo filtro de categoria.
            pagina.goto(BASE + "/gestao/catalogo")
            chave = pagina.locator(f'input[aria-label="Monitorar {NOME_LONGO}"]:visible')
            expect(chave).to_be_checked()
            chave.click()
            expect(chave).not_to_be_checked()
            assert _ativo(engine, "g-longo", False) is False
            pagina.get_by_label("Categoria").select_option(label="Booster Box")
            expect(pagina.get_by_text("2 produtos", exact=True)).to_be_visible()  # a lista filtrada já chegou
            pagina.get_by_label("Selecionar a página").check()
            expect(pagina.get_by_text("2 selecionados")).to_be_visible()
            pagina.get_by_role("button", name="Desligar", exact=True).click()
            expect(pagina.get_by_text("Desligar 2 produtos?")).to_be_visible()
            pagina.get_by_role("button", name="Confirmar").click()
            expect(pagina.get_by_text("Desligar 2 produtos?")).to_be_hidden()
            expect(pagina.locator('input[aria-label="Monitorar Caixa Alfa"]:visible')).not_to_be_checked()
            assert _ativo(engine, "g-alfa", False) is False and _ativo(engine, "g-beta", False) is False
        finally:
            navegador.close()


def test_telas_de_gestao_cabem_com_nome_de_120_caracteres(servidores, gestao, engine, tmp_path):
    """As quatro telas novas, em 390 e 1440 px nos dois temas, com um produto de nome longo e sem foto."""
    from playwright.sync_api import sync_playwright

    httpx.post(BASE + "/api/auth/pedir-codigo", json={"numero": ADMIN}, timeout=10).raise_for_status()
    layout = _verificar_layout()
    telas = [
        "/gestao/casamentos?situacao=todos", "/gestao/catalogo",
        f"/gestao/casamentos/{gestao['longo']}", f"/gestao/produtos/{gestao['longo']}",
    ]
    problemas: list[str] = []
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        try:
            estado = layout.entrar_no_web(navegador, BASE, ADMIN, ler_codigo(engine, ADMIN))
            for nome, (largura, altura) in layout.TAMANHOS.items():
                for tema in ("winter", "night"):
                    contexto = navegador.new_context(viewport={"width": largura, "height": altura}, storage_state=estado)
                    contexto.add_init_script(f"try {{ localStorage.setItem('tema', '{tema}'); }} catch (e) {{}}")
                    pagina = contexto.new_page()
                    erros: list[str] = []
                    pagina.on("pageerror", lambda e, acumulado=erros: acumulado.append(str(e)))
                    for caminho in telas:
                        png = tmp_path / f"{nome}-{tema}-{abs(hash(caminho))}.png"
                        problemas += layout.conferir(pagina, BASE + caminho, caminho, largura, f"{nome} {tema}", png, erros)
                        if pagina.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
                            problemas.append(f"{caminho} {nome} {tema}: estourou a largura")
                    contexto.close()
        finally:
            navegador.close()
    assert problemas == []


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
