import base64
from datetime import timedelta

import pytest
from fakes import criar_anuncio, criar_produto
from fastapi.testclient import TestClient

from tcg_sniper.admin import estilo
from tcg_sniper.admin.app import criar_app
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import StatusCasamento, StatusMensagem

MENU = ["Dashboard", "Serviços", "Catálogo", "Casamentos", "Ofertas", "Mensagens", "Configurações"]


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def test_css_em_dia_com_os_templates():
    assert estilo.hash_gravado() == estilo.hash_fontes(), "CSS desatualizado: rode uv run python scripts/gerar_css.py"


def test_css_e_servido(cliente):
    r = cliente.get("/static/admin.css")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/css")
    assert "daisyUI" in r.text


def test_menu_lateral_tem_as_7_telas_na_ordem(cliente):
    texto = cliente.get("/").text
    menu = texto[texto.index('<ul class="menu'):texto.index("</ul>", texto.index('<ul class="menu'))]
    posicoes = [menu.index(f">{rotulo}</span>") for rotulo in MENU]
    assert posicoes == sorted(posicoes)
    for href in ("/", "/servicos", "/catalogo", "/casamentos", "/ofertas", "/mensagens", "/configuracoes"):
        assert f'href="{href}"' in menu
    assert 'class="drawer lg:drawer-open"' in texto and 'href="/static/admin.css' in texto


def test_item_da_tela_atual_fica_ativo(cliente):
    texto = cliente.get("/ofertas").text
    trecho = texto[texto.index('href="/ofertas"') - 20:texto.index('href="/ofertas"') + 120]
    assert "menu-active" in trecho


def test_contadores_aparecem_quando_maior_que_zero(cliente, sessoes):
    texto = cliente.get("/").text
    assert 'data-contador="casamentos"' not in texto and 'data-contador="mensagens"' not in texto
    with sessoes() as s, s.begin():
        produto = criar_produto(s, "p1", nome="Caixa", ativo=True)
        criar_anuncio(s, "B0PEND0001", produto=produto, status=StatusCasamento.PENDENTE)
        m = repo_msg.enfileirar(s, "admin", "x", repo.agora_utc() - timedelta(hours=1))
        m.status = StatusMensagem.FALHA
    texto = cliente.get("/").text
    assert 'data-contador="casamentos">1<' in texto and 'data-contador="mensagens">1<' in texto


def test_tema_e_menu_usam_localstorage_protegido(cliente):
    texto = cliente.get("/").text
    assert 'id="trocar-tema"' in texto
    # todo acesso ao localStorage fica dentro de um try (aba anônima ou bloqueio não quebram a página)
    pedacos = texto.split("localStorage")
    for i in range(1, len(pedacos)):
        assert "try {" in pedacos[i - 1][-60:], "localStorage fora de try"
    # o drawer-toggle só é marcado no computador (no celular o menu não abre sozinho)
    assert 'matchMedia("(min-width: 1024px)")' in texto
    assert 'id="menu" type="checkbox" class="drawer-toggle">' in texto  # sem "checked" no HTML
