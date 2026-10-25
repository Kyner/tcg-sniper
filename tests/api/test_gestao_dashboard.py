from fakes import criar_anuncio, criar_produto
from fakes_api import T0
from fakes_oportunidades import criar_oportunidade

from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Papel, StatusCasamento

DASHBOARD = "/api/gestao/dashboard"
MENU = "/api/gestao/menu"


def _negar(sessoes, app_api, papel, *permissoes):
    with sessoes() as s, s.begin():
        for permissao in permissoes:
            repo_acesso.salvar_permissao(s, papel, permissao, False)
    app_api.state.grade.invalidar()


def test_sem_sessao_401_e_grupo_403(cliente, logar):
    assert cliente.get(DASHBOARD).status_code == 401
    logar(Papel.GRUPO)
    r = cliente.get(DASHBOARD)
    assert r.status_code == 403 and r.json()["erro"] == "sem_permissao"


def test_forma_da_resposta_do_operador(cliente, logar, sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "d1", nome="Caixa de teste")
        a = criar_anuncio(s, "B000000D10", p)
        criar_oportunidade(s, a, p, aberta_em=T0, preco_alertado="700")
    logar(Papel.OPERADOR)
    dados = cliente.get(DASHBOARD).json()
    assert set(dados) == {"precisa", "saude", "oportunidades", "funil"}
    assert [x["id"] for x in dados["saude"]] == [
        "liga", "amazon_busca", "amazon_monitor", "casador", "whatsapp", "backup"
    ]
    assert set(dados["saude"][0]) == {"id", "nome", "estado", "resumo"}
    assert dados["saude"][0]["nome"] == "LigaMagic"
    assert set(dados["oportunidades"]) == {"top", "abertas", "alertas_hoje", "alertas_semana"}
    assert dados["oportunidades"]["abertas"] == 1
    [topo] = dados["oportunidades"]["top"]
    assert set(topo) == {"produto_id", "nome", "imagem", "desconto_pct"}
    assert topo["nome"] == "Caixa de teste" and topo["imagem"] is None and float(topo["desconto_pct"]) == 30
    assert set(dados["funil"]) == {
        "liga", "monitorados", "esperando_decisao", "so_ignorados", "sem_candidato", "casados_produtos",
        "casados_anuncios", "oportunidades",
    }
    assert dados["funil"]["liga"] == 1 and dados["funil"]["oportunidades"] == 1
    for item in dados["precisa"]:
        assert set(item) == {"texto", "rotulo", "destino"}


def test_precisa_inclui_a_revisao_em_sequencia(cliente, logar, sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "d2")
        criar_anuncio(s, "B000000D20", p)
    logar(Papel.OPERADOR)
    assert {
        "texto": "1 produto esperando decisão.",
        "rotulo": "Revisar em sequência",
        "destino": "/gestao/casamentos?situacao=esperando_decisao",
    } in cliente.get(DASHBOARD).json()["precisa"]


def test_top_3_por_maior_desconto_na_api(cliente, logar, sessoes):
    with sessoes() as s, s.begin():
        for i, preco in enumerate(["900", "600", "800", "500"]):
            p = criar_produto(s, f"o{i}", nome=f"Produto {i}")
            a = criar_anuncio(s, f"B000000O{i}0", p)
            criar_oportunidade(s, a, p, aberta_em=T0, preco_alertado=preco, preco_liga="1000")
    logar(Papel.OPERADOR)
    bloco = cliente.get(DASHBOARD).json()["oportunidades"]
    assert [t["nome"] for t in bloco["top"]] == ["Produto 3", "Produto 1", "Produto 2"]
    assert bloco["abertas"] == 4


def test_operador_sem_ver_servicos_recebe_saude_null(cliente, app_api, logar, sessoes):
    logar(Papel.OPERADOR)
    _negar(sessoes, app_api, Papel.OPERADOR, "ver_servicos")
    dados = cliente.get(DASHBOARD).json()
    assert dados["saude"] is None
    assert dados["oportunidades"] is not None and dados["funil"] is not None
    # Os avisos de serviço (destino em Serviços) também somem de quem não pode abrir a tela.
    assert all(not i["destino"].startswith("/gestao/servicos") for i in dados["precisa"])


def test_sem_ver_oportunidades_e_sem_ver_catalogo_blocos_null(cliente, app_api, logar, sessoes):
    logar(Papel.OPERADOR)
    _negar(sessoes, app_api, Papel.OPERADOR, "ver_oportunidades", "ver_catalogo")
    dados = cliente.get(DASHBOARD).json()
    assert dados["oportunidades"] is None and dados["funil"] is None
    assert dados["saude"] is not None


def test_sem_revisar_casamentos_a_revisao_some_do_precisa(cliente, app_api, logar, sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "d3")
        criar_anuncio(s, "B000000D30", p)
    logar(Papel.OPERADOR)
    _negar(sessoes, app_api, Papel.OPERADOR, "revisar_casamentos")
    assert all("esperando decisão" not in i["texto"] for i in cliente.get(DASHBOARD).json()["precisa"])


def test_menu_conta_igual_a_lista(cliente, logar, sessoes):
    with sessoes() as s, s.begin():
        for i in range(3):
            p = criar_produto(s, f"m{i}")
            criar_anuncio(s, f"B000000M{i}0", p)
        casado = criar_produto(s, "mc")
        criar_anuncio(s, "B000000MC0", casado, StatusCasamento.CONFIRMADO)
        criar_produto(s, "mi", ativo=False)
    logar(Papel.OPERADOR)
    lista = cliente.get("/api/gestao/casamentos").json()
    assert lista["total"] == 3
    assert cliente.get(MENU).json() == {"casamentos_esperando": lista["total"]}
