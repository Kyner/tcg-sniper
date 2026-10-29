import base64
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, criar_anuncio, criar_par, criar_preco_liga, criar_produto
from fastapi.testclient import TestClient

from tcg_sniper.admin import consultas_amazon
from tcg_sniper.admin.app import criar_app
from tcg_sniper.consultas import menu as consultas_menu
from tcg_sniper.consultas import ofertas as consultas_ofertas
from tcg_sniper.consultas import painel
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db.models import Envio, OrigemCasamento, OrigemPreco, StatusCasamento

SP = ZoneInfo("America/Sao_Paulo")
PENDENTE, CONFIRMADO, IGNORADO = StatusCasamento.PENDENTE, StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def preco(s, anuncio, valor, origem=OrigemPreco.BUSCA):
    repo_amz.registrar_preco(s, anuncio.id, Decimal(valor), origem, None, Envio.AMAZON, T0, SP)


def test_lista_conta_por_par_um_anuncio_em_dois_produtos(s):
    jogo, colec = criar_produto(s, "jogo", nome="Caixa de Jogo"), criar_produto(s, "colec", nome="Caixa Colecionador")
    for p in (jogo, colec):
        criar_preco_liga(s, p, "1000.00")
    anuncio = criar_anuncio(s, "B0LISTA001", produto=colec, status=IGNORADO, origem=OrigemCasamento.MANUAL)
    criar_par(s, anuncio, jogo)  # o mesmo anúncio pendente para o Jogo
    preco(s, anuncio, "700.00")
    linhas = {
        l.produto.liga_id: (l.pendentes, l.confirmados, l.ignorados, l.oportunidade)
        for l in consultas_amazon.produtos_para_casar(
            s, busca="", categoria=None, situacao="todos", com_preco=False, desconto_min_pct=25
        )
    }
    assert linhas == {"jogo": (1, 0, 0, True), "colec": (0, 0, 1, False)}
    assert consultas_menu.contadores_menu(s, T0).casamentos == 1


def test_dashboard_conta_produtos(s, config):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    anuncio = criar_anuncio(s, "B0PAINEL01", produto=p, status=CONFIRMADO, origem=OrigemCasamento.MANUAL)
    criar_par(s, anuncio, q, status=IGNORADO, origem=OrigemCasamento.OUTRO_CONFIRMADO, revisado_em=T0)
    criar_anuncio(s, "B0PAINEL02", produto=q)
    c = painel.numeros(s, T0, config).catalogo
    # p casado; q (ignorado por estar casado em outro produto + um pendente) espera sua decisão
    assert (c.casado, c.esperando_decisao, c.so_ignorados, c.sem_candidato) == (1, 1, 0, 0)
    assert (c.com_mais_de_uma_sugestao, c.pares_pendentes, c.produtos_com_pendentes, c.casados_com_pendentes) == (1, 1, 1, 0)


def test_ofertas_e_produto_usam_o_par_confirmado_e_a_origem_dele(s):
    sugerido, certo = criar_produto(s, "sugerido", nome="Produto Sugerido"), criar_produto(s, "certo", nome="Produto Certo")
    for p in (sugerido, certo):
        criar_preco_liga(s, p, "1000.00", listagem_em=T0)
    anuncio = criar_anuncio(s, "B0OFERTA01", produto=sugerido)
    repo_casamento.confirmar(s, anuncio.id, certo.id, T0, OrigemCasamento.AUTOMATICO_IA)
    preco(s, anuncio, "700.00", OrigemPreco.PRODUTO)
    [linha] = consultas_ofertas.ofertas(s, consultas_ofertas.FiltroOfertas(), repo_amz.obter_config(s))
    assert (linha.produto.liga_id, linha.origem_casamento) == ("certo", OrigemCasamento.AUTOMATICO_IA)
    [no_produto] = consultas_amazon.amazon_do_produto(s, certo.id, repo_amz.obter_config(s), T0)
    assert no_produto.casamento.origem is OrigemCasamento.AUTOMATICO_IA
    assert consultas_amazon.amazon_do_produto(s, sugerido.id, repo_amz.obter_config(s), T0) == []
    assert [a for _, a in consultas_amazon.historico_amazon(s, certo.id)] == ["B0OFERTA01"]
    assert consultas_amazon.historico_amazon(s, sugerido.id) == []


def test_tela_do_produto_mostra_a_origem_do_par(sessoes, cliente):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "tela", nome="Produto Tela")
        criar_anuncio(s, "B0TELA0001", produto=p, status=CONFIRMADO, origem=OrigemCasamento.AUTOMATICO_IA)
        produto_id = p.id
    resposta = cliente.get(f"/produto/{produto_id}")
    assert resposta.status_code == 200 and "automático pela IA" in resposta.text
    assert "sugerido pela IA" not in resposta.text


def test_lista_e_dashboard_mostram_casado_em_outro_produto_a_parte(sessoes, cliente):
    with sessoes() as s, s.begin():
        jogo, colec = criar_produto(s, "jogo", nome="Caixa de Jogo"), criar_produto(s, "colec", nome="Caixa Colecionador")
        anuncio = criar_anuncio(s, "B0OUTRO001", produto=colec, status=CONFIRMADO, origem=OrigemCasamento.MANUAL)
        criar_par(s, anuncio, jogo, status=IGNORADO, origem=OrigemCasamento.OUTRO_CONFIRMADO, revisado_em=T0)
        criar_anuncio(s, "B0OUTRO002", produto=jogo, status=IGNORADO, origem=OrigemCasamento.MANUAL)
        [linha] = consultas_amazon.produtos_para_casar(
            s, busca="Jogo", categoria=None, situacao="todos", com_preco=False, desconto_min_pct=25
        )
        assert (linha.pendentes, linha.confirmados, linha.ignorados, linha.em_outro, linha.sem_par) == (0, 0, 1, 1, True)
    lista = cliente.get("/casamentos", params={"situacao": "todos"}).text
    assert "1 casado em outro produto" in lista
    assert "casado em outro produto" not in cliente.get("/").text  # o Dashboard conta por produto
