import base64
import importlib.util
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fakes import T0
from fastapi.testclient import TestClient

from tcg_sniper.admin.app import criar_app
from tcg_sniper.admin.consultas import POR_PAGINA_HISTORICO
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import StatusColeta, TipoColeta

ABAS = ("LigaMagic", "Amazon", "Monitor", "Checkout", "IA", "Manutenção")


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def aba(texto, rotulo):
    """Conteúdo da aba `rotulo` (do seu <input> até o <input> da aba seguinte)."""
    inicio = texto.index(f'aria-label="{rotulo}"')
    seguinte = [texto.find(f'aria-label="{r}"', inicio + 1) for r in ABAS if r != rotulo]
    fim = min([p for p in seguinte if p > inicio] or [len(texto)])
    return texto[inicio:fim]


def aba_marcada(texto, rotulo):
    inicio = texto.index(f'aria-label="{rotulo}"')
    return "checked" in texto[texto.rindex("<input", 0, inicio):inicio + 60]


def linhas(trecho, tipo):
    return trecho.count(f'data-tipo="{tipo}"')


def coleta(sessoes, tipo, quando, status=StatusColeta.OK, ok=1, falha=0):
    with sessoes() as s, s.begin():
        c = repo.iniciar_coleta(s, tipo, quando)
        repo.finalizar_coleta(s, c.id, status, ok, falha, quando + timedelta(minutes=18))


def chamada(sessoes, quando=T0, finalidade="casamento", ok=True, erro=None, custo="0.000512"):
    with sessoes() as s, s.begin():
        repo_ia.registrar_chamada(
            s, em=quando, finalidade=finalidade, modelo="gpt-5-mini", tokens_entrada=1412, tokens_saida=96,
            custo_usd=Decimal(custo), ok=ok, erro=erro,
        )


def test_menu_tem_logs_entre_mensagens_e_configuracoes(cliente):
    texto = cliente.get("/logs").text
    menu = texto[texto.index('<ul class="menu'):texto.index("</ul>", texto.index('<ul class="menu'))]
    assert menu.index(">Mensagens</span>") < menu.index(">Logs</span>") < menu.index(">Configurações</span>")
    trecho = menu[menu.index('href="/logs"') - 20:menu.index('href="/logs"') + 120]
    assert "menu-active" in trecho


def test_abas_e_a_liga_abre_por_padrao(cliente):
    texto = cliente.get("/logs").text
    for rotulo in ABAS:
        assert f'aria-label="{rotulo}"' in texto
    assert aba_marcada(texto, "LigaMagic") and not aba_marcada(texto, "IA")
    assert aba_marcada(cliente.get("/logs?aba=ia").text, "IA")
    assert cliente.get("/logs?aba=xyz").status_code == 400


def test_historico_da_liga_e_da_amazon_separados(cliente, sessoes):
    coleta(sessoes, TipoColeta.PRODUTOS, T0)
    for i in range(12):
        coleta(sessoes, TipoColeta.AMAZON, T0 + timedelta(hours=i), ok=3)
    texto = cliente.get("/logs").text
    liga, amazon = aba(texto, "LigaMagic"), aba(texto, "Amazon")
    assert linhas(liga, "produtos") == 1 and linhas(liga, "amazon") == 0
    assert linhas(amazon, "amazon") == 12 and linhas(amazon, "produtos") == 0
    assert "18 min" in liga  # duração


def test_historico_com_filtro_e_paginacao(cliente, sessoes):
    for i in range(25):
        coleta(sessoes, TipoColeta.AMAZON, T0 + timedelta(hours=i), StatusColeta.FALHA if i % 5 == 0 else StatusColeta.OK)
    pagina1 = aba(cliente.get("/logs?aba=amazon").text, "Amazon")
    assert linhas(pagina1, "amazon") == 20
    assert "amazon_pagina=2" in pagina1 and "liga_status=todos" in pagina1 and "aba=amazon" in pagina1
    pagina2 = aba(cliente.get("/logs?aba=amazon&amazon_pagina=2").text, "Amazon")
    assert linhas(pagina2, "amazon") == 5
    alem = aba(cliente.get("/logs?aba=amazon&amazon_pagina=999").text, "Amazon")
    assert linhas(alem, "amazon") == 5
    falhas = aba(cliente.get("/logs?aba=amazon&amazon_status=falha").text, "Amazon")
    assert linhas(falhas, "amazon") == 5
    assert 'value="falha" selected' in falhas
    assert cliente.get("/logs?amazon_status=xyz").status_code == 400
    assert cliente.get("/logs?liga_status=xyz").status_code == 400
    assert cliente.get("/logs?liga_pagina=abc").status_code == 200


def test_aba_continua_aberta_depois_de_paginar_ou_filtrar(cliente, sessoes):
    for i in range(POR_PAGINA_HISTORICO + 1):
        for tipo in (TipoColeta.AMAZON, TipoColeta.LISTAGEM):
            coleta(sessoes, tipo, T0 + timedelta(minutes=i))
    texto = cliente.get("/logs?aba=amazon").text
    amazon = aba(texto, "Amazon")
    assert 'name="aba" value="amazon"' in amazon  # o filtro volta para a mesma aba
    assert "aba=amazon" in amazon[amazon.index("amazon_pagina=2") - 120:amazon.index("amazon_pagina=2") + 120]
    assert aba_marcada(cliente.get("/logs", params={"aba": "amazon", "amazon_status": "ok"}).text, "Amazon")
    liga = cliente.get("/logs", params={"aba": "liga", "liga_pagina": "2"}).text
    assert aba_marcada(liga, "LigaMagic") and not aba_marcada(liga, "Amazon")


def test_situacao_das_coletas_tem_selo(cliente, sessoes):
    with sessoes() as s, s.begin():
        c = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0)
        repo.finalizar_coleta(s, c.id, StatusColeta.FALHA, 0, 1, T0, erro="interrompida")
    liga = aba(cliente.get("/logs").text, "LigaMagic")
    assert 'badge-error">falha</span>' in liga and "interrompida" in liga


def test_aba_ia_lista_as_chamadas(cliente, sessoes):
    chamada(sessoes, T0)
    chamada(sessoes, T0 + timedelta(minutes=5), finalidade="avaliacao", ok=False, erro="OpenAI 500", custo="0")
    ia = aba(cliente.get("/logs?aba=ia").text, "IA")
    assert "gpt-5-mini" in ia and "1.412 / 96" in ia and "US$ 0,0005" in ia and "US$ 0,0000" in ia
    assert 'badge-success">ok</span>' in ia and 'badge-error">erro</span>' in ia and "OpenAI 500" in ia
    assert ia.index("OpenAI 500") < ia.index("US$ 0,0005")  # mais recentes primeiro
    assert "avaliação" in ia


def test_aba_ia_filtros(cliente, sessoes):
    chamada(sessoes, T0)
    chamada(sessoes, T0, finalidade="avaliacao", ok=False, erro="OpenAI 500")
    so_erro = aba(cliente.get("/logs?aba=ia&situacao=com_erro").text, "IA")
    assert "OpenAI 500" in so_erro and 'badge-success">ok</span>' not in so_erro
    assert 'value="com_erro" selected' in so_erro
    casamento = aba(cliente.get("/logs?aba=ia&finalidade=casamento").text, "IA")
    assert "OpenAI 500" not in casamento and 'badge-success">ok</span>' in casamento
    assert cliente.get("/logs?situacao=xyz").status_code == 400
    assert cliente.get("/logs?finalidade=xyz").status_code == 400


def test_aba_ia_paginada(cliente, sessoes):
    for i in range(POR_PAGINA_HISTORICO + 3):
        chamada(sessoes, T0 + timedelta(minutes=i))
    pagina1 = aba(cliente.get("/logs?aba=ia&finalidade=casamento").text, "IA")
    assert pagina1.count("gpt-5-mini") == POR_PAGINA_HISTORICO * 2  # tabela e cartões do celular
    assert "ia_pagina=2" in pagina1 and "finalidade=casamento" in pagina1
    pagina2 = aba(cliente.get("/logs?aba=ia&ia_pagina=2").text, "IA")
    assert pagina2.count("gpt-5-mini") == 3 * 2


def test_vazio(cliente):
    texto = cliente.get("/logs").text
    assert "Nenhuma coleta ainda." in texto and "Nenhum ciclo ainda." in texto and "Nenhuma chamada" in texto


def test_paginar_a_liga_com_filtro_nao_reabre_a_amazon(cliente, sessoes):
    # Guarda do bug antigo: paginar o histórico da LigaMagic com filtro reabria a aba da Amazon.
    for i in range(POR_PAGINA_HISTORICO + 5):
        coleta(sessoes, TipoColeta.LISTAGEM, T0 + timedelta(minutes=i), StatusColeta.FALHA, ok=0, falha=1)
        coleta(sessoes, TipoColeta.AMAZON, T0 + timedelta(minutes=i))
    pagina1 = cliente.get("/logs", params={"aba": "liga", "liga_status": "falha"}).text
    liga = aba(pagina1, "LigaMagic")
    link = liga[liga.index("liga_pagina=2") - 200:liga.index("liga_pagina=2") + 200]
    assert "aba=liga" in link and "liga_status=falha" in link
    pagina2 = cliente.get("/logs", params={"aba": "liga", "liga_status": "falha", "liga_pagina": "2"}).text
    assert aba_marcada(pagina2, "LigaMagic") and not aba_marcada(pagina2, "Amazon")
    assert linhas(aba(pagina2, "LigaMagic"), "listagem") == 5


def test_verificar_layout_confere_as_abas_dos_logs():
    caminho = Path(__file__).parents[2] / "scripts" / "verificar_layout.py"
    spec = importlib.util.spec_from_file_location("verificar_layout", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    for tela in ("/logs", "/logs?aba=amazon", "/logs?aba=ia", "/logs?aba=checkout", "/logs?aba=monitor"):
        assert tela in modulo.FIXAS
