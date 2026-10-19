"""Confere o layout das telas do admin e do front novo em 390 e 1440 px, nos temas winter e night.

Admin (precisa do Chromium do Playwright e da senha do admin), dentro do container do admin:
  docker compose exec -T admin python - < scripts/verificar_layout.py

Front novo (serviço web): passe o número de um usuário e um código válido (vale uma vez, por 5 min):
  docker compose exec api tcg-sniper codigo-acesso "<número>"
  docker compose exec -T -e WEB_NUMERO="<número>" -e WEB_CODIGO=<código> admin python - < scripts/verificar_layout.py
Sem WEB_NUMERO/WEB_CODIGO só o admin é conferido; com SO_WEB=1, só o front. WEB_BASE muda o endereço do front
(padrão http://web:8090, o serviço na rede do compose).

Para apontar para outro admin, defina ADMIN_BASE (padrão http://127.0.0.1:8000), por exemplo:
  docker compose exec -T -e ADMIN_BASE=http://host.docker.internal:8010 admin python - < scripts/verificar_layout.py

No computador, cada tela do admin roda também com o menu recolhido (localStorage "menu" = "recolhido").
Falha (código 1) se alguma tela estourar a largura da janela ou tiver erro de script.
Elementos com rolagem horizontal própria (fora das tabelas em .overflow-x-auto) saem como avisos, sem falhar.
Salva os prints em <pasta temporária>/verificar_layout/ (no container: /tmp/verificar_layout; docker cp para ver).
"""

import os
import re
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ADMIN_BASE", "http://127.0.0.1:8000")
WEB_BASE = os.environ.get("WEB_BASE", "http://web:8090")
FIXAS = [
    "/", "/servicos", "/catalogo", "/casamentos?situacao=todos", "/ofertas", "/mensagens", "/configuracoes", "/configuracoes?msg=avisos",
    "/logs", "/logs?aba=amazon", "/logs?aba=ia", "/logs?aba=checkout", "/logs?aba=monitor", "/logs?aba=manutencao",
]
TELAS_WEB = ["/", "/gestao", "/gestao/usuarios", "/gestao/acessos", "/sem-acesso"]
TELAS_WEB_ANONIMAS = ["/entrar"]
TAMANHOS = {"celular": (390, 844), "computador": (1440, 900)}
SAIDA = Path(tempfile.gettempdir()) / "verificar_layout"
MENUS = {"expandido": None, "recolhido": "recolhido"}  # o menu recolhido só existe no computador

ROLAGEM_INTERNA = r"""() => [...document.querySelectorAll('body *')]
  .filter(e => e.scrollWidth > e.clientWidth + 1 && ['auto', 'scroll'].includes(getComputedStyle(e).overflowX)
    && !e.classList.contains('overflow-x-auto'))
  .map(e => e.tagName.toLowerCase() + (typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/ +/).join('.') : ''))
"""


def descobrir(pagina) -> list[str]:
    """Telas que dependem de um id: o primeiro produto de Casamentos e o primeiro anúncio pendente."""
    extras = []
    pagina.goto(BASE + "/casamentos?situacao=todos")
    abrir = pagina.locator('a:has-text("Abrir")').first
    if abrir.count():
        href = abrir.get_attribute("href")
        extras.append(href)
        pagina.goto(BASE + href)
        trocar = pagina.locator('a[href$="/trocar"]').first
        if trocar.count():
            extras.append(trocar.get_attribute("href"))
    pagina.goto(BASE + "/ofertas")
    produto = pagina.locator('a[href^="/produto/"]').first
    if produto.count():
        extras.append(produto.get_attribute("href"))
    return extras


def conferir(pagina, url: str, caminho: str, largura: int, rotulo: str, png: Path, erros: list[str]) -> list[str]:
    """Abre a tela, salva o print e devolve os problemas (HTTP, largura estourada, erro de script)."""
    erros.clear()
    resposta = pagina.goto(url, wait_until="networkidle")
    largura_doc = pagina.evaluate("document.documentElement.scrollWidth")
    pagina.screenshot(path=str(png), full_page=True)
    problemas = []
    if resposta.status != 200:
        problemas.append(f"{caminho} {rotulo}: HTTP {resposta.status}")
    if largura_doc > largura:
        problemas.append(f"{caminho} {rotulo}: largura {largura_doc} > {largura}")
    if erros:
        problemas.append(f"{caminho} {rotulo}: erro de script {erros}")
    return problemas


def _nome_png(caminho: str, sufixo: str, prefixo: str = "") -> str:
    arquivo = re.sub(r"[^a-z0-9]+", "-", caminho.lower()).strip("-") or "dashboard"
    return f"{prefixo}{arquivo}-{sufixo}.png"


def verificar_admin(navegador, problemas: list[str], avisos: list[str]) -> None:
    credenciais = {"username": "admin", "password": os.environ["ADMIN_SENHA"]}
    for nome_tam, (largura, altura) in TAMANHOS.items():
        for menu, valor_menu in MENUS.items():
            if valor_menu and nome_tam != "computador":
                continue
            for tema in ("winter", "night"):
                contexto = navegador.new_context(viewport={"width": largura, "height": altura}, http_credentials=credenciais)
                contexto.add_init_script(f"try {{ localStorage.setItem('tema', '{tema}'); }} catch (e) {{}}")
                if valor_menu:
                    contexto.add_init_script(f"try {{ localStorage.setItem('menu', '{valor_menu}'); }} catch (e) {{}}")
                pagina = contexto.new_page()
                erros: list[str] = []
                pagina.on("pageerror", lambda e, acumulado=erros: acumulado.append(str(e)))
                rotulo = f"{nome_tam} {tema}" + (f" menu {menu}" if valor_menu else "")
                sufixo = f"{nome_tam}-{tema}" + (f"-{menu}" if valor_menu else "")
                for caminho in FIXAS + descobrir(pagina):
                    png = SAIDA / _nome_png(caminho, sufixo)
                    problemas += conferir(pagina, BASE + caminho, caminho, largura, rotulo, png, erros)
                    if valor_menu:
                        for elemento in pagina.evaluate(ROLAGEM_INTERNA):
                            avisos.append(f"{caminho} {rotulo}: rolagem horizontal interna em {elemento}")
                contexto.close()


def entrar_no_web(navegador, base: str, numero: str, codigo: str) -> dict:
    """Entra uma vez pela API (o código vale uma vez) e devolve o estado do navegador com o cookie da sessão."""
    contexto = navegador.new_context()
    try:
        resposta = contexto.request.post(base + "/api/auth/entrar", data={"numero": numero, "codigo": codigo})
        if not resposta.ok:
            raise SystemExit(f"não consegui entrar no front: HTTP {resposta.status} (o código vale 5 min e uma vez só)")
        return contexto.storage_state()
    finally:
        contexto.close()


def verificar_web(navegador, base: str, estado: dict, saida: Path) -> list[str]:
    """Telas do front novo: /entrar sem sessão e as demais com a sessão de `estado`, nos dois tamanhos e temas."""
    saida.mkdir(parents=True, exist_ok=True)
    problemas: list[str] = []
    for nome_tam, (largura, altura) in TAMANHOS.items():
        for tema in ("winter", "night"):
            for logado, telas in ((False, TELAS_WEB_ANONIMAS), (True, TELAS_WEB)):
                contexto = navegador.new_context(
                    viewport={"width": largura, "height": altura}, storage_state=estado if logado else None
                )
                contexto.add_init_script(f"try {{ localStorage.setItem('tema', '{tema}'); }} catch (e) {{}}")
                pagina = contexto.new_page()
                erros: list[str] = []
                pagina.on("pageerror", lambda e, acumulado=erros: acumulado.append(str(e)))
                rotulo = f"web {nome_tam} {tema}"
                for caminho in telas:
                    png = saida / _nome_png(caminho, f"{nome_tam}-{tema}", "web-")
                    problemas += conferir(pagina, base + caminho, caminho, largura, rotulo, png, erros)
                contexto.close()
    return problemas


def main() -> None:
    SAIDA.mkdir(exist_ok=True)
    problemas: list[str] = []
    avisos: list[str] = []
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        if os.environ.get("SO_WEB") != "1":
            verificar_admin(navegador, problemas, avisos)
        numero, codigo = os.environ.get("WEB_NUMERO"), os.environ.get("WEB_CODIGO")
        if numero and codigo:
            estado = entrar_no_web(navegador, WEB_BASE, numero, codigo)
            problemas += verificar_web(navegador, WEB_BASE, estado, SAIDA)
        navegador.close()
    if avisos:
        print("avisos:\n" + "\n".join(sorted(set(avisos))))
    print("\n".join(problemas) or "layout ok")
    sys.exit(1 if problemas else 0)


if __name__ == "__main__":
    main()
