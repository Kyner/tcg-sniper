from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto
from fakes_oportunidades import criar_atual_amazon, criar_listagem_liga
from sqlalchemy import select

from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import AcaoGestao, Papel, ProdutoLiga, StatusCasamento, TipoAcaoGestao

LISTA = "/api/gestao/catalogo"
LOTE = "/api/gestao/catalogo/lote"
PRODUTO = "/api/gestao/produtos"


@pytest.fixture
def catalogo(sessoes):
    with sessoes() as s, s.begin():
        ids = {}
        for i in range(3):
            p = criar_produto(s, f"cx{i}", nome=f"Caixa {i}")
            p.tipo = "Caixas"
            criar_preco_liga(s, p, "100.00", num_lojas=3, preco_medio="120.00")
            ids[f"cx{i}"] = p.id
        for i in range(2):
            p = criar_produto(s, f"bd{i}", ativo=False, nome=f"Bundle {i}")
            p.tipo = "Bundles"
            ids[f"bd{i}"] = p.id
        casado = s.get(ProdutoLiga, ids["cx0"])
        anuncio = criar_anuncio(s, "B0CAT00001", casado, StatusCasamento.CONFIRMADO)
        criar_atual_amazon(s, anuncio, "70.00")
        criar_anuncio(s, "B0CAT00002", casado, StatusCasamento.PENDENTE)
        s.flush()
        return ids


def _acoes(sessoes):
    with sessoes() as s:
        return [(a.usuario_id, a.tipo, a.detalhe) for a in s.scalars(select(AcaoGestao).order_by(AcaoGestao.id))]


def _ativos(sessoes):
    with sessoes() as s:
        return set(s.scalars(select(ProdutoLiga.liga_id).where(ProdutoLiga.ativo.is_(True))))


def test_sem_sessao_401_e_sem_permissao_403(cliente, app_api, logar, sessoes, catalogo):
    pid = catalogo["cx0"]
    leituras = [("get", LISTA, None), ("get", f"{PRODUTO}/{pid}", None)]
    escritas = [
        ("patch", f"{PRODUTO}/{pid}", {"ativo": False}),
        ("post", LOTE, {"acao": "ligar", "ids": [pid], "esperado": 1, "confirmar": False}),
    ]
    for metodo, rota, corpo in leituras + escritas:
        assert cliente.request(metodo, rota, json=corpo).status_code == 401
    logar(Papel.GRUPO)
    for metodo, rota, corpo in leituras + escritas:
        r = cliente.request(metodo, rota, json=corpo)
        assert r.status_code == 403 and r.json()["erro"] == "sem_permissao"
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.OPERADOR, "editar_catalogo", False)
    app_api.state.grade.invalidar()
    logar(Papel.OPERADOR)
    for metodo, rota, corpo in leituras:
        assert cliente.request(metodo, rota, json=corpo).status_code == 200
    for metodo, rota, corpo in escritas:
        assert cliente.request(metodo, rota, json=corpo).status_code == 403
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.OPERADOR, "ver_catalogo", False)
    app_api.state.grade.invalidar()
    for metodo, rota, corpo in leituras:
        assert cliente.request(metodo, rota, json=corpo).status_code == 403
    assert _acoes(sessoes) == []


def test_lista_com_filtros_e_categorias(cliente, logar, catalogo):
    logar(Papel.OPERADOR)
    r = cliente.get(LISTA)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["total"] == 5 and corpo["pagina"] == 1 and corpo["por_pagina"] == 25
    assert corpo["categorias"] == ["Bundles", "Caixas"]
    primeiro = corpo["itens"][0]
    assert primeiro["nome"] == "Caixa 0" and primeiro["monitorado"] is True
    assert primeiro["situacao"] == "casado" and primeiro["pendentes"] == 1 and primeiro["confirmados"] == 1
    assert Decimal(primeiro["melhor_amazon"]) == Decimal("70.00") and primeiro["lojas"] == 3
    assert [i["nome"] for i in cliente.get(LISTA, params={"monitorado": "nao"}).json()["itens"]] == [
        "Bundle 0", "Bundle 1"
    ]
    assert cliente.get(LISTA, params={"situacao": "casado"}).json()["total"] == 1
    assert cliente.get(LISTA, params={"categoria": "Caixas", "preco_liga": "com"}).json()["total"] == 3
    assert cliente.get(LISTA, params={"situacao": "x"}).status_code == 422
    assert cliente.get(LISTA, params={"monitorado": "talvez"}).status_code == 422


def test_patch_liga_e_desliga_e_grava_acao(cliente, logar, sessoes, catalogo):
    usuario = logar(Papel.OPERADOR)
    pid = catalogo["bd0"]
    r = cliente.patch(f"{PRODUTO}/{pid}", json={"ativo": True})
    assert r.status_code == 200 and r.json()["id"] == pid and r.json()["monitorado"] is True
    assert "bd0" in _ativos(sessoes)
    r = cliente.patch(f"{PRODUTO}/{pid}", json={"ativo": False})
    assert r.status_code == 200 and r.json()["monitorado"] is False
    assert "bd0" not in _ativos(sessoes)
    assert _acoes(sessoes) == [
        (usuario, TipoAcaoGestao.CATALOGO_PRODUTO, {"produto_id": pid, "ativo": True}),
        (usuario, TipoAcaoGestao.CATALOGO_PRODUTO, {"produto_id": pid, "ativo": False}),
    ]
    assert cliente.patch(f"{PRODUTO}/999999", json={"ativo": True}).status_code == 404
    assert cliente.patch(f"{PRODUTO}/{pid}", json={}).status_code == 422


def test_lote_sem_confirmar_so_conta(cliente, logar, sessoes, catalogo):
    logar(Papel.OPERADOR)
    antes = _ativos(sessoes)
    r = cliente.post(LOTE, json={"acao": "ligar", "filtro": {"monitorado": "nao"}, "esperado": 0, "confirmar": False})
    assert r.status_code == 200 and r.json() == {"alvo": 2, "alterados": 0}
    assert _ativos(sessoes) == antes and _acoes(sessoes) == []


def test_lote_com_esperado_errado_409_e_nada_alterado(cliente, logar, sessoes, catalogo):
    logar(Papel.OPERADOR)
    antes = _ativos(sessoes)
    r = cliente.post(LOTE, json={"acao": "desligar", "filtro": {"categoria": "Caixas"}, "esperado": 2, "confirmar": True})
    assert r.status_code == 409
    assert r.json() == {
        "erro": "contagem_mudou", "mensagem": "A lista mudou: agora são 3 produtos. Confira e confirme de novo."
    }
    assert _ativos(sessoes) == antes and _acoes(sessoes) == []


def test_lote_por_filtro_de_categoria_altera_so_ela_e_grava_acao(cliente, logar, sessoes, catalogo):
    usuario = logar(Papel.OPERADOR)
    filtro = {"categoria": "Bundles"}
    r = cliente.post(LOTE, json={"acao": "ligar", "filtro": filtro, "esperado": 2, "confirmar": True})
    assert r.status_code == 200 and r.json() == {"alvo": 2, "alterados": 2}
    assert _ativos(sessoes) == {"cx0", "cx1", "cx2", "bd0", "bd1"}
    [(quem, tipo, detalhe)] = _acoes(sessoes)
    assert quem == usuario and tipo == TipoAcaoGestao.CATALOGO_LOTE
    assert detalhe == {
        "acao": "ligar",
        "filtro": {"busca": "", "monitorado": "todos", "categoria": "Bundles", "situacao": None, "preco_liga": "todos"},
        "alvo": 2,
        "alterados": 2,
    }


def test_lote_por_ids(cliente, logar, sessoes, catalogo):
    usuario = logar(Papel.OPERADOR)
    ids = [catalogo["cx1"], catalogo["cx2"], catalogo["bd0"]]
    r = cliente.post(LOTE, json={"acao": "desligar", "ids": ids, "esperado": 3, "confirmar": True})
    assert r.status_code == 200 and r.json() == {"alvo": 3, "alterados": 2}
    assert _ativos(sessoes) == {"cx0"}
    assert _acoes(sessoes) == [
        (usuario, TipoAcaoGestao.CATALOGO_LOTE, {"acao": "desligar", "ids": ids, "alvo": 3, "alterados": 2})
    ]


def test_lote_exige_ids_ou_filtro(cliente, logar, catalogo):
    logar(Papel.OPERADOR)
    base = {"acao": "ligar", "esperado": 0, "confirmar": False}
    assert cliente.post(LOTE, json=base).status_code == 422
    assert cliente.post(LOTE, json={**base, "ids": [1], "filtro": {}}).status_code == 422


def test_produto_de_gestao_inclusive_inativo(cliente, logar, catalogo):
    logar(Papel.OPERADOR)
    r = cliente.get(f"{PRODUTO}/{catalogo['cx0']}")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["monitorado"] is True and corpo["produto"]["nome"] == "Caixa 0"
    assert "pistas" in corpo["produto"]
    assert Decimal(corpo["liga"]["preco"]) == Decimal("100.00") and corpo["liga"]["lojas"] == 3
    assert Decimal(corpo["liga"]["medio"]) == Decimal("120.00") and corpo["liga"]["lido_em"] is not None
    assert Decimal(corpo["melhor_amazon"]["preco"]) == Decimal("70.00")
    assert Decimal(corpo["melhor_amazon"]["diferenca_pct"]) == Decimal("30.00")
    assert corpo["casamentos"] == {"pendentes": 1, "confirmados": 1, "ignorados": 0}
    assert corpo["curva"] is not None and corpo["curva"]["periodo"] == "30d"
    inativo = cliente.get(f"{PRODUTO}/{catalogo['bd0']}")
    assert inativo.status_code == 200
    corpo = inativo.json()
    assert corpo["monitorado"] is False and corpo["curva"] is None and corpo["melhor_amazon"] is None
    assert corpo["liga"] == {"preco": None, "lojas": None, "medio": None, "lido_em": None}
    assert cliente.get(f"{PRODUTO}/999999").status_code == 404


@pytest.fixture
def esgotado(sessoes, catalogo):
    """Sem "a partir de" na Liga, média 200 e anúncio confirmado a 100; teve vendedor até T0 - 3 dias."""
    with sessoes() as s, s.begin():
        p = criar_produto(s, "esg", nome="Esgotado X")
        criar_preco_liga(s, p, None, preco_medio="200.00")
        criar_atual_amazon(s, criar_anuncio(s, "B0CATESG01", p, StatusCasamento.CONFIRMADO), "100.00")
        criar_listagem_liga(s, p, "150.00", T0 - timedelta(days=3))
        criar_listagem_liga(s, p, None, T0 - timedelta(days=1))
        inativo = criar_produto(s, "esg-off", ativo=False, nome="Esgotado Inativo")  # fora da lista esgotado
        criar_preco_liga(s, inativo, None, preco_medio="300.00")
        criar_atual_amazon(s, criar_anuncio(s, "B0CATESG02", inativo, StatusCasamento.CONFIRMADO), "100.00")
        return {"ativo": p.id, "inativo": inativo.id}


def test_lista_esgotado_com_media_diferenca_e_sem_vendedor_desde(cliente, logar, esgotado):
    logar(Papel.OPERADOR)
    corpo = cliente.get(LISTA, params={"preco_liga": "esgotado"}).json()
    assert corpo["total"] == 1
    [item] = corpo["itens"]
    assert item["id"] == esgotado["ativo"] and item["preco_liga"] is None  # o inativo fica fora
    assert Decimal(item["melhor_amazon"]) == Decimal("100.00") and Decimal(item["medio_liga"]) == Decimal("200.00")
    assert Decimal(item["diferenca_media_pct"]) == Decimal("50.00")
    assert datetime.fromisoformat(item["sem_vendedor_desde"]) == T0 - timedelta(days=3)
    caixa = cliente.get(LISTA, params={"busca": "Caixa 0"}).json()["itens"][0]
    assert Decimal(caixa["medio_liga"]) == Decimal("120.00") and caixa["sem_vendedor_desde"] is None
    assert Decimal(caixa["diferenca_media_pct"]) == Decimal("41.67")
    assert cliente.get(LISTA, params={"preco_liga": "com"}).json()["total"] == 3
    assert cliente.get(LISTA, params={"preco_liga": "x"}).status_code == 422
    assert cliente.get(LISTA, params={"com_preco": True}).json()["total"] == 7  # parâmetro antigo é ignorado


def test_lote_esgotado_aplica_aos_mesmos_da_lista(cliente, logar, sessoes, esgotado):
    logar(Papel.OPERADOR)
    filtro = {"preco_liga": "esgotado"}
    r = cliente.post(LOTE, json={"acao": "desligar", "filtro": filtro, "esperado": 0, "confirmar": False})
    assert r.json() == {"alvo": 1, "alterados": 0}
    r = cliente.post(LOTE, json={"acao": "ligar", "filtro": filtro, "esperado": 1, "confirmar": True})
    assert r.json() == {"alvo": 1, "alterados": 0}  # o inativo não é ligado
    assert "esg-off" not in _ativos(sessoes)
    r = cliente.post(LOTE, json={"acao": "desligar", "filtro": filtro, "esperado": 1, "confirmar": True})
    assert r.status_code == 200 and r.json() == {"alvo": 1, "alterados": 1}
    assert _ativos(sessoes) == {"cx0", "cx1", "cx2"}
    corpo = {"acao": "ligar", "filtro": {"preco_liga": "x"}, "esperado": 0, "confirmar": False}
    assert cliente.post(LOTE, json=corpo).status_code == 422
    corpo = {"acao": "ligar", "filtro": {"com_preco": True}, "esperado": 0, "confirmar": False}
    assert cliente.post(LOTE, json=corpo).status_code == 422


def test_produto_de_gestao_diz_se_esta_esgotado_na_liga(cliente, logar, catalogo, esgotado):
    logar(Papel.OPERADOR)
    assert cliente.get(f"{PRODUTO}/{esgotado['ativo']}").json()["esgotado_liga"] is True
    assert cliente.get(f"{PRODUTO}/{esgotado['inativo']}").json()["esgotado_liga"] is False
    assert cliente.get(f"{PRODUTO}/{catalogo['cx0']}").json()["esgotado_liga"] is False
    assert cliente.get(f"{PRODUTO}/{catalogo['bd0']}").json()["esgotado_liga"] is False  # sem anúncio com preço

def test_limites_de_tamanho_do_lote_e_da_busca(cliente, logar, catalogo):
    logar(Papel.OPERADOR)
    base = {"acao": "ligar", "esperado": 0, "confirmar": False}
    assert cliente.post(LOTE, json={**base, "ids": list(range(1, 1002))}).status_code == 422
    assert cliente.post(LOTE, json={**base, "ids": list(range(1, 1001))}).status_code == 200
    assert cliente.post(LOTE, json={**base, "filtro": {"busca": "x" * 201}}).status_code == 422
    assert cliente.get(LISTA, params={"busca": "x" * 201}).status_code == 422
    assert cliente.get(LISTA, params={"busca": "x" * 200}).status_code == 200
