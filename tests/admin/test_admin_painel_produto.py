"""Dashboard e Casamentos contados por produto (situação do catálogo)."""

import base64

import pytest
from fakes import catalogo_exemplo
from fastapi.testclient import TestClient

from tcg_sniper.admin import consultas_amazon
from tcg_sniper.admin.app import criar_app
from tcg_sniper.admin.consultas_catalogo import SITUACOES_PRODUTO


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    token = base64.b64encode(b"admin:segredo").decode()
    return TestClient(criar_app(sessoes, c), headers={"Authorization": f"Basic {token}"})


def test_dashboard_mostra_casamentos_e_ia_por_produto(sessoes, cliente):
    with sessoes() as s, s.begin():
        catalogo_exemplo(s)
    texto = cliente.get("/").text
    for trecho in ("Casados", "Esperando sua decisão", "Só ignorados", "Sem candidato",
                   "2 produtos com mais de uma sugestão", "2 anúncios aguardando em 2 produtos (inclui produtos já casados)",
                   "Produtos avaliados", "Avaliados hoje", "Esperando a IA", "0 anúncios avaliados · média de 0 por produto",
                   "Gasto do mês"):
        assert trecho in texto
    for situacao in SITUACOES_PRODUTO:
        assert f'href="/casamentos?situacao=todos&amp;situacao_produto={situacao}"' in texto
    assert "Confirmados</div>" not in texto and "casado em outro produto" not in texto


def test_casamentos_filtra_pela_situacao_do_produto(s):
    catalogo_exemplo(s)
    por_situacao = {
        situacao: sorted(
            linha.produto.liga_id
            for linha in consultas_amazon.produtos_para_casar(
                s, busca="", categoria=None, situacao="todos", com_preco=False, desconto_min_pct=25,
                situacao_produto=situacao,
            )
        )
        for situacao in SITUACOES_PRODUTO
    }
    assert por_situacao == {
        "casado": ["duplo", "simples"], "esperando_decisao": ["esperando"], "so_ignorados": ["ignorado"],
        "sem_candidato": ["sem"],
    }
    [duplo] = consultas_amazon.produtos_para_casar(
        s, busca="duplo", categoria=None, situacao="todos", com_preco=False, desconto_min_pct=25
    )
    assert (duplo.sugestoes, duplo.situacao_produto) == (3, "casado")


def test_tela_de_casamentos_filtra_e_mostra_sugestoes(sessoes, cliente):
    with sessoes() as s, s.begin():
        catalogo_exemplo(s)
    texto = cliente.get("/casamentos", params={"situacao": "todos", "situacao_produto": "so_ignorados"}).text
    assert "Produto ignorado" in texto and "Produto duplo" not in texto and "Sugestões" in texto
    assert cliente.get("/casamentos", params={"situacao_produto": "x"}).status_code == 400
    # sem o filtro novo, o padrão de antes (com pendentes) continua
    padrao = cliente.get("/casamentos").text
    assert "Produto esperando" in padrao and "Produto sem" not in padrao
