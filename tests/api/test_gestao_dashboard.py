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
        assert set(item) == {"texto", "rotulo", "destino", "acao"}


def test_precisa_inclui_a_revisao_em_sequencia(cliente, logar, sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "d2")
        criar_anuncio(s, "B000000D20", p)
    logar(Papel.OPERADOR)
    assert {
        "texto": "1 produto esperando decisão.",
        "rotulo": "Revisar em sequência",
        "destino": "/gestao/casamentos?situacao=esperando_decisao",
        "acao": None,
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


def _rotulos_dos_servicos(cliente):
    itens = cliente.get(DASHBOARD).json()["precisa"]
    por_texto = {i["texto"]: i for i in itens if i["destino"] == "/gestao/servicos"}
    liga = next(i for t, i in por_texto.items() if t.startswith("LigaMagic"))
    busca = next(i for t, i in por_texto.items() if t.startswith("Amazon (busca)"))
    return liga["rotulo"], busca["rotulo"]


def test_servico_pausado_leva_ligar_e_desafio_leva_ver(cliente, logar, sessoes):
    from tcg_sniper.db import repositorio as repo
    from tcg_sniper.db.models import COLETOR_AMAZON_BUSCA, COLETOR_LIGA

    with sessoes() as s, s.begin():
        repo.pausar(s, "teste", T0, COLETOR_LIGA)
        repo.pausar_por_desafio(s, "captcha", T0, COLETOR_AMAZON_BUSCA)
    logar(Papel.ADMIN)
    assert _rotulos_dos_servicos(cliente) == ("Ligar", "Ver")


def test_servico_pausado_leva_ver_para_quem_nao_pode_pausar(cliente, logar, sessoes):
    from tcg_sniper.db import repositorio as repo
    from tcg_sniper.db.models import COLETOR_AMAZON_BUSCA, COLETOR_LIGA

    with sessoes() as s, s.begin():
        repo.pausar(s, "teste", T0, COLETOR_LIGA)
        repo.pausar_por_desafio(s, "captcha", T0, COLETOR_AMAZON_BUSCA)
    logar(Papel.OPERADOR)  # sem pausar_servicos
    assert _rotulos_dos_servicos(cliente) == ("Ver", "Ver")


def test_admin_antigo_abre_a_secao_pedida(sessoes, config):
    import base64

    from fastapi.testclient import TestClient

    from tcg_sniper.admin.app import criar_app

    auth = "Basic " + base64.b64encode(b"admin:segredo").decode()
    c = TestClient(
        criar_app(sessoes, config.model_copy(update={"admin_senha": "segredo"})), headers={"Authorization": auth}
    )
    texto = c.get("/configuracoes?secao=amazon").text
    assert 'aria-label="Amazon" checked' in texto
    assert 'aria-label="Geral" checked' not in texto


def _com_mensagem_com_falha(sessoes):
    from tcg_sniper.db.models import MensagemSaida, StatusMensagem

    with sessoes() as s, s.begin():
        s.add(MensagemSaida(
            destino="oportunidades", texto="x", status=StatusMensagem.FALHA, proxima_tentativa_em=T0,
            criada_em=T0, atualizado_em=T0, ultimo_erro="400",
        ))


def _itens_de_mensagem(cliente):
    return [i for i in cliente.get(DASHBOARD).json()["precisa"] if i["destino"].startswith("/gestao/atividade?o_que=mensagem")]


def test_mensagens_com_falha_pedem_ver_logs_e_nao_ver_mensagens(cliente, app_api, logar, sessoes):
    _com_mensagem_com_falha(sessoes)
    logar(Papel.OPERADOR)
    _negar(sessoes, app_api, Papel.OPERADOR, "ver_mensagens")
    assert _itens_de_mensagem(cliente)  # ver_logs basta (a Atividade inclui mensagens)
    _negar(sessoes, app_api, Papel.OPERADOR, "ver_logs")
    assert _itens_de_mensagem(cliente) == []
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.OPERADOR, "ver_mensagens", True)
    app_api.state.grade.invalidar()
    assert _itens_de_mensagem(cliente) == []  # ver_mensagens sem ver_logs: a tela não abre
