"""Confere o layout das telas do admin em 390 e 1440 px, nos temas winter e night.

Roda dentro do container do admin (precisa do Chromium do Playwright e da senha do admin):
  docker compose exec -T admin python - < scripts/verificar_layout.py

Para apontar para outro admin, defina ADMIN_BASE (padrão http://127.0.0.1:8000), por exemplo:
  docker compose exec -T -e ADMIN_BASE=http://host.docker.internal:8010 admin python - < scripts/verificar_layout.py

Falha (código 1) se alguma tela estourar a largura da janela ou tiver erro de script.
Salva os prints em /tmp/verificar_layout/ (docker cp para ver).
"""

import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ADMIN_BASE", "http://127.0.0.1:8000")
FIXAS = ["/", "/servicos", "/catalogo", "/casamentos?situacao=todos", "/ofertas", "/mensagens", "/configuracoes"]
TAMANHOS = {"celular": (390, 844), "computador": (1440, 900)}
SAIDA = Path("/tmp/verificar_layout")


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


def main() -> None:
    SAIDA.mkdir(exist_ok=True)
    problemas = []
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        credenciais = {"username": "admin", "password": os.environ["ADMIN_SENHA"]}
        for nome_tam, (largura, altura) in TAMANHOS.items():
            for tema in ("winter", "night"):
                contexto = navegador.new_context(viewport={"width": largura, "height": altura}, http_credentials=credenciais)
                contexto.add_init_script(f"try {{ localStorage.setItem('tema', '{tema}'); }} catch (e) {{}}")
                pagina = contexto.new_page()
                erros = []
                pagina.on("pageerror", lambda e, acumulado=erros: acumulado.append(str(e)))
                for caminho in FIXAS + descobrir(pagina):
                    erros.clear()
                    resposta = pagina.goto(BASE + caminho, wait_until="networkidle")
                    largura_doc = pagina.evaluate("document.documentElement.scrollWidth")
                    arquivo = re.sub(r"[^a-z0-9]+", "-", caminho.lower()).strip("-") or "dashboard"
                    pagina.screenshot(path=str(SAIDA / f"{arquivo}-{nome_tam}-{tema}.png"), full_page=True)
                    if resposta.status != 200:
                        problemas.append(f"{caminho} {nome_tam} {tema}: HTTP {resposta.status}")
                    if largura_doc > largura:
                        problemas.append(f"{caminho} {nome_tam} {tema}: largura {largura_doc} > {largura}")
                    if erros:
                        problemas.append(f"{caminho} {nome_tam} {tema}: erro de script {erros}")
                contexto.close()
        navegador.close()
    print("\n".join(problemas) or "layout ok")
    sys.exit(1 if problemas else 0)


if __name__ == "__main__":
    main()
