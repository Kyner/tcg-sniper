import pytest
from fakes import criar_anuncio, criar_par, criar_preco_liga, criar_produto
from fakes_api import T0
from fakes_api import logar as logar_cliente
from fakes_oportunidades import criar_atual_amazon
from fastapi.testclient import TestClient

from tcg_sniper.api.app import criar_app
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import AvaliacaoIA, Papel, StatusCasamento

LISTA = "/api/gestao/casamentos"


def _ia(s, anuncio, produto, mesmo, confianca=80, idioma="pt"):
    s.add(AvaliacaoIA(
        anuncio_id=anuncio.id, produto_id=produto.id, mesmo_produto=mesmo, confianca=confianca, motivo="porque",
        modelo="m", assinatura="a", sem_imagem=False, avaliado_em=T0, idioma_anuncio=idioma,
    ))
    s.flush()


def test_sem_sessao_401_e_sem_permissao_403(cliente, app_api, logar, sessoes):
    rotas = [LISTA, f"{LISTA}/1"]
    for rota in rotas:
        assert cliente.get(rota).status_code == 401
    logar(Papel.GRUPO)
    for rota in rotas:
        r = cliente.get(rota)
        assert r.status_code == 403 and r.json()["erro"] == "sem_permissao"
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.OPERADOR, "revisar_casamentos", False)
    app_api.state.grade.invalidar()
    logar(Papel.OPERADOR)
    for rota in rotas:
        assert cliente.get(rota).status_code == 403


def test_lista_ordena_com_preco_primeiro_e_pagina_de_20(cliente, logar, sessoes):
    with sessoes() as s, s.begin():
        sem_preco = criar_produto(s, "a0", nome="Aaa sem preco")
        for i in range(24):
            p = criar_produto(s, f"p{i:02d}", nome=f"Produto {i:02d}")
            criar_preco_liga(s, p, "10.00")
        sem_preco_id = sem_preco.id
    logar(Papel.OPERADOR)
    r = cliente.get(f"{LISTA}?situacao=todos").json()
    assert r["total"] == 25 and r["pagina"] == 1 and r["por_pagina"] == 20 and len(r["itens"]) == 20
    assert r["itens"][0]["nome"] == "Produto 00" and r["itens"][0]["preco_liga"] == "10.00"
    r2 = cliente.get(f"{LISTA}?situacao=todos&pagina=2").json()
    assert len(r2["itens"]) == 5 and r2["itens"][-1]["id"] == sem_preco_id and r2["itens"][-1]["preco_liga"] is None
    assert set(r["itens"][0]) == {"id", "nome", "nome_en", "imagem", "categoria", "preco_liga", "pendentes",
                                  "confirmados", "ignorados", "em_outro", "ia_sugere", "situacao"}
    assert "categorias" in r
    assert cliente.get(f"{LISTA}?ordem=legado").status_code == 422
    assert cliente.get(f"{LISTA}?situacao=xyz").status_code == 422


def test_lista_filtro_situacao_todos_e_esperando_decisao(cliente, logar, sessoes):
    with sessoes() as s, s.begin():
        esperando = criar_produto(s, "e", nome="Esperando")
        criar_anuncio(s, "B0000000E1", esperando)
        casado = criar_produto(s, "c", nome="Casado")
        criar_anuncio(s, "B0000000C1", casado, StatusCasamento.CONFIRMADO)
        criar_produto(s, "s", nome="Sem candidato")
        esperando_id = esperando.id
    logar(Papel.OPERADOR)
    padrao = cliente.get(LISTA).json()
    assert [i["id"] for i in padrao["itens"]] == [esperando_id]
    assert padrao["itens"][0]["situacao"] == "esperando_decisao"
    assert cliente.get(f"{LISTA}?situacao=todos").json()["total"] == 3
    assert cliente.get(f"{LISTA}?situacao=casado").json()["total"] == 1
    assert cliente.get(f"{LISTA}?situacao=sem_candidato").json()["itens"][0]["nome"] == "Sem candidato"


@pytest.fixture
def revisao(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "x", nome="Final Fantasy Booster Foil (Inglês)")
        p.imagem_chave = "produtos/x.webp"
        criar_preco_liga(s, p, "1000.00", num_lojas=4)
        pend = criar_anuncio(s, "B0000000P1", p)
        pend.titulo = "Booster Box Foil English"
        criar_atual_amazon(s, pend, "700.00")
        criar_anuncio(s, "B0000000C1", p, StatusCasamento.CONFIRMADO)
        ign = criar_anuncio(s, "B0000000I1", p, StatusCasamento.IGNORADO)
        outro = criar_produto(s, "o", nome="Outro produto")
        criar_par(s, ign, outro, StatusCasamento.CONFIRMADO)
        _ia(s, pend, p, True, 90, "en")
        return p.id


def test_revisao_agrupa_sem_abas_e_monta_imagem(sessoes, config, relogio, revisao):
    for base, esperado in (("https://img.teste", "https://img.teste/produtos/x.webp"), (None, None)):
        cliente = TestClient(criar_app(sessoes, config.model_copy(update={"url_publica_imagens": base}), relogio))
        logar_cliente(sessoes, cliente, Papel.OPERADOR, numero="+5511900000010" if base else "+5511900000011")
        r = cliente.get(f"{LISTA}/{revisao}?situacao=todos")
        assert r.status_code == 200
        d = r.json()
        assert set(d) == {"produto", "navegacao", "para_decidir", "confirmados", "ignorados", "parecidos",
                          "termos", "termos_pedidos"}
        assert d["produto"]["imagem"] == esperado and d["produto"]["lojas"] == 4
        assert d["produto"]["preco_liga"] == "1000.00" and "Foil" in d["produto"]["pistas"]
        assert len(d["para_decidir"]) == 1 and len(d["confirmados"]) == 1 and len(d["ignorados"]) == 1
        a = d["para_decidir"][0]
        assert a["asin"] == "B0000000P1" and a["preco"] == "700.00" and a["oportunidade"] is True
        assert a["imagem"] is None and "Foil" in a["termos_variacao"]
        assert a["ia"] == {"mesmo_produto": True, "confianca": 90, "motivo": "porque", "idioma": "en"}
        assert d["ignorados"][0]["casado_com"]["nome"] == "Outro produto"
        assert d["termos"] == [] and d["termos_pedidos"] is False


def test_revisao_sem_selo_oportunidade_quando_ia_diz_outro_produto(cliente, logar, sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "y", nome="Produto Y")
        criar_preco_liga(s, p, "1000.00")
        a = criar_anuncio(s, "B0000000Y1", p)
        criar_atual_amazon(s, a, "700.00")
        _ia(s, a, p, False, 95)
        pid = p.id
    logar(Papel.OPERADOR)
    item = cliente.get(f"{LISTA}/{pid}").json()["para_decidir"][0]
    assert item["ia"]["mesmo_produto"] is False and item["oportunidade"] is False


def test_navegacao_segue_filtros_da_lista(cliente, logar, sessoes):
    with sessoes() as s, s.begin():
        ids = []
        for i, nome in enumerate(["Alfa", "Beta", "Gama"]):
            p = criar_produto(s, f"n{i}", nome=nome)
            if nome != "Beta":
                criar_anuncio(s, f"B000000N{i}0", p)
            ids.append(p.id)
    logar(Papel.OPERADOR)
    # padrão (esperando decisão): só Alfa e Gama
    n = cliente.get(f"{LISTA}/{ids[0]}?ordem=nome").json()["navegacao"]
    assert n == {"posicao": 1, "total": 2, "anterior": None, "proximo": ids[2]}
    n = cliente.get(f"{LISTA}/{ids[2]}?ordem=nome").json()["navegacao"]
    assert n == {"posicao": 2, "total": 2, "anterior": ids[0], "proximo": None}
    n = cliente.get(f"{LISTA}/{ids[1]}?situacao=todos&ordem=nome").json()["navegacao"]
    assert n == {"posicao": 2, "total": 3, "anterior": ids[0], "proximo": ids[2]}


def test_produto_inativo_404(cliente, logar, sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "z", ativo=False)
        pid = p.id
    logar(Papel.OPERADOR)
    r = cliente.get(f"{LISTA}/{pid}")
    assert r.status_code == 404
    assert r.json() == {"erro": "nao_encontrado", "mensagem": "Produto não está mais monitorado."}
    assert cliente.get(f"{LISTA}/999999").status_code == 404


def test_menu_conta_os_esperando_e_zera_sem_revisar_casamentos(cliente, app_api, logar, sessoes):
    assert cliente.get("/api/gestao/menu").status_code == 401
    logar(Papel.GRUPO)
    assert cliente.get("/api/gestao/menu").status_code == 403
    with sessoes() as s, s.begin():
        for i in range(2):
            p = criar_produto(s, f"m{i}", nome=f"Esperando {i}")
            criar_anuncio(s, f"B000000M{i}0", p)
        casado = criar_produto(s, "mc", nome="Casado")
        criar_anuncio(s, "B000000MC0", casado, StatusCasamento.CONFIRMADO)
        criar_produto(s, "ms", nome="Sem candidato")
    logar(Papel.OPERADOR)
    assert cliente.get("/api/gestao/menu").json() == {"casamentos_esperando": 2}
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.OPERADOR, "revisar_casamentos", False)
    app_api.state.grade.invalidar()
    assert cliente.get("/api/gestao/menu").json() == {"casamentos_esperando": 0}
