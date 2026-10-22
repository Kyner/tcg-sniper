from datetime import timedelta

import pytest
from fakes import criar_anuncio, criar_par, criar_produto
from fakes_api import T0

from tcg_sniper.consultas.casamentos import MENSAGENS_CASAMENTO
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import (
    COLETOR_CASADOR,
    AvaliacaoIA,
    Casamento,
    FilaAmazon,
    OrigemCasamento,
    Papel,
    StatusCasamento,
)

BASE = "/api/gestao/casamentos"
PENDENTE, CONFIRMADO, IGNORADO = StatusCasamento.PENDENTE, StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO
MANUAL, OUTRO = OrigemCasamento.MANUAL, OrigemCasamento.OUTRO_CONFIRMADO


@pytest.fixture
def dois(sessoes):
    """Um anúncio pendente para "Caixa de Jogo" e para "Caixa Colecionador"; os dois na fila."""
    with sessoes() as s, s.begin():
        jogo = criar_produto(s, "jogo", nome="Caixa de Jogo")
        colec = criar_produto(s, "colec", nome="Caixa Colecionador")
        anuncio = criar_anuncio(s, "B0ACAO0001", produto=jogo)
        criar_par(s, anuncio, colec)
        repo_amz.sincronizar_fila(s, T0)
        return {"jogo": jogo.id, "colec": colec.id, "anuncio": anuncio.id}


def situacao(sessoes, anuncio_id, produto_id):
    with sessoes() as s:
        par = s.get(Casamento, (anuncio_id, produto_id))
        return par.status, par.origem


def decidir(cliente, ids, acao, produto, **extra):
    return cliente.post(f"{BASE}/{ids[produto]}/anuncios/{ids['anuncio']}", json={"acao": acao, **extra})


def test_permissoes_401_e_403_em_todas_as_rotas(cliente, logar, dois):
    p, a = dois["jogo"], dois["anuncio"]
    rotas = [
        ("post", f"{BASE}/{p}/anuncios/{a}", {"acao": "ignorar"}),
        ("get", f"{BASE}/anuncios/{a}/produtos", None),
        ("post", f"{BASE}/{p}/link", {"link": "x"}),
        ("post", f"{BASE}/{p}/rebuscar", None),
        ("post", f"{BASE}/{p}/reavaliar", None),
        ("post", f"{BASE}/{p}/termos", None),
    ]
    for metodo, rota, corpo in rotas:
        assert cliente.request(metodo, rota, json=corpo).status_code == 401
    logar(Papel.GRUPO)
    for metodo, rota, corpo in rotas:
        r = cliente.request(metodo, rota, json=corpo)
        assert r.status_code == 403 and r.json()["erro"] == "sem_permissao"


def test_confirmar_ignora_o_par_do_outro_produto_e_devolve_o_anuncio(cliente, logar, sessoes, dois):
    logar(Papel.OPERADOR)
    r = decidir(cliente, dois, "confirmar", "colec")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["grupo"] == "confirmados" and corpo["anuncio"]["anuncio_id"] == dois["anuncio"]
    assert corpo["anuncio"]["origem"] == "manual"
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (CONFIRMADO, MANUAL)
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (IGNORADO, OUTRO)


def test_confirmar_com_avaliacao_da_ia_grava_origem_sugerido_ia(cliente, logar, sessoes, dois):
    with sessoes() as s, s.begin():
        s.add(AvaliacaoIA(
            anuncio_id=dois["anuncio"], produto_id=dois["colec"], mesmo_produto=True, confianca=90, motivo="m",
            modelo="m", assinatura="a", sem_imagem=False, avaliado_em=T0, idioma_anuncio="pt",
        ))
    logar(Papel.OPERADOR)
    r = decidir(cliente, dois, "confirmar", "colec")
    assert r.json()["anuncio"]["origem"] == "sugerido_ia"
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (CONFIRMADO, OrigemCasamento.SUGERIDO_IA)


def test_ignorar_vale_so_para_o_par(cliente, logar, sessoes, dois):
    logar(Papel.OPERADOR)
    r = decidir(cliente, dois, "ignorar", "jogo")
    assert r.status_code == 200 and r.json()["grupo"] == "ignorados"
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (IGNORADO, MANUAL)
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (PENDENTE, None)


def test_confirmar_em_outro_produto_409_e_nao_muda(cliente, logar, sessoes, dois):
    logar(Papel.OPERADOR)
    assert decidir(cliente, dois, "confirmar", "colec").status_code == 200
    with sessoes() as s, s.begin():  # a tela do Jogo ainda mostrava o pendente
        par = s.get(Casamento, (dois["anuncio"], dois["jogo"]))
        par.status, par.origem, par.revisado_em = PENDENTE, None, None
    r = decidir(cliente, dois, "confirmar", "jogo")
    assert r.status_code == 409 and r.json()["erro"] == "ja_confirmado"
    assert r.json()["mensagem"] == "Este anúncio já está confirmado em Caixa Colecionador."
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (PENDENTE, None)
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (CONFIRMADO, MANUAL)


def test_confirmar_o_mesmo_par_duas_vezes_e_idempotente(cliente, logar, dois):
    logar(Papel.OPERADOR)
    assert decidir(cliente, dois, "confirmar", "colec").status_code == 200
    r = decidir(cliente, dois, "confirmar", "colec")
    assert r.status_code == 200 and r.json()["grupo"] == "confirmados"


def test_desfazer_reabre_o_par_do_outro_produto(cliente, logar, sessoes, dois):
    logar(Papel.OPERADOR)
    decidir(cliente, dois, "confirmar", "colec")
    r = decidir(cliente, dois, "desfazer", "colec")
    assert r.status_code == 200 and r.json()["grupo"] == "para_decidir"
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (PENDENTE, None)
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (PENDENTE, None)
    with sessoes() as s:
        assert s.get(Casamento, (dois["anuncio"], dois["colec"])).reavaliar is True


def test_trocar_vai_para_o_outro_produto_e_ignora_o_de_onde_veio(cliente, logar, sessoes, dois):
    with sessoes() as s, s.begin():
        terceiro = criar_produto(s, "terceiro", nome="Caixa Terceira").id
    logar(Papel.OPERADOR)
    decidir(cliente, dois, "confirmar", "colec")
    r = decidir(cliente, dois, "trocar", "jogo", para_produto_id=terceiro)
    assert r.status_code == 200 and r.json()["grupo"] == "ignorados"
    assert situacao(sessoes, dois["anuncio"], terceiro) == (CONFIRMADO, MANUAL)
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (IGNORADO, MANUAL)
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (IGNORADO, MANUAL)
    assert r.json()["anuncio"]["casado_com"]["id"] == terceiro
    # desfazer o novo reabre só o `outro_confirmado`; o "não é este" que você deu fica
    r = cliente.post(f"{BASE}/{terceiro}/anuncios/{dois['anuncio']}", json={"acao": "desfazer"})
    assert r.status_code == 200
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (IGNORADO, MANUAL)


def test_trocar_exige_o_produto_de_destino_e_valida_o_corpo(cliente, logar, dois):
    logar(Papel.OPERADOR)
    assert decidir(cliente, dois, "trocar", "jogo").status_code == 422
    assert decidir(cliente, dois, "xyz", "jogo").status_code == 422
    assert decidir(cliente, dois, "ignorar", "jogo", outro=1).status_code == 422


def test_inexistentes_404(cliente, logar, sessoes, dois):
    logar(Papel.OPERADOR)
    with sessoes() as s, s.begin():
        sem_par = criar_produto(s, "sem-par").id
        inativo = criar_produto(s, "inativo", ativo=False).id
    assert cliente.post(f"{BASE}/{sem_par}/anuncios/{dois['anuncio']}", json={"acao": "ignorar"}).status_code == 404
    assert cliente.post(f"{BASE}/{dois['jogo']}/anuncios/999999", json={"acao": "ignorar"}).status_code == 404
    alvo_inativo = {"acao": "trocar", "para_produto_id": inativo}
    assert cliente.post(f"{BASE}/{dois['jogo']}/anuncios/{dois['anuncio']}", json=alvo_inativo).status_code == 404
    assert decidir(cliente, dois, "trocar", "jogo", para_produto_id=999999).status_code == 404


def test_produtos_para_trocar_sugere_busca_e_exclui(cliente, logar, sessoes, dois):
    with sessoes() as s, s.begin():
        criar_produto(s, "terceiro", nome="Caixa Terceira")
        repo_casamento.confirmar(s, dois["anuncio"], dois["colec"], T0)
    logar(Papel.OPERADOR)
    r = cliente.get(f"{BASE}/anuncios/{dois['anuncio']}/produtos", params={"de": dois["jogo"], "busca": "Caixa"})
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()}
    assert ids and dois["jogo"] not in ids and dois["colec"] not in ids
    assert set(r.json()[0]) == {"id", "nome", "imagem", "preco_liga"}
    assert cliente.get(f"{BASE}/anuncios/{dois['anuncio']}/produtos").status_code == 200
    assert cliente.get(f"{BASE}/anuncios/999999/produtos").status_code == 404


def test_link_casa_o_asin_e_link_invalido_400(cliente, logar, dois):
    logar(Papel.OPERADOR)
    r = cliente.post(f"{BASE}/{dois['jogo']}/link", json={"link": "https://www.amazon.com.br/dp/B0LINK0001"})
    assert r.status_code == 200 and r.json()["asin"] == "B0LINK0001" and r.json()["origem"] == "manual"
    ruim = cliente.post(f"{BASE}/{dois['jogo']}/link", json={"link": "isto não é link"})
    assert ruim.status_code == 400 and ruim.json()["erro"] == "link_invalido"
    assert cliente.post(f"{BASE}/999999/link", json={"link": "B0LINK0001"}).status_code == 404


def test_rebuscar_poe_na_frente_e_fora_da_fila_avisa(cliente, logar, sessoes, dois):
    with sessoes() as s, s.begin():
        s.get(FilaAmazon, dois["jogo"]).proxima_busca_em = T0 + timedelta(days=3)
        fora = criar_produto(s, "fora-da-fila").id
    logar(Papel.OPERADOR)
    r = cliente.post(f"{BASE}/{dois['jogo']}/rebuscar")
    assert r.json() == {"tipo": "success", "mensagem": MENSAGENS_CASAMENTO["rebuscar"][1]}
    with sessoes() as s:
        assert s.get(FilaAmazon, dois["jogo"]).proxima_busca_em < T0 + timedelta(days=3)
    r = cliente.post(f"{BASE}/{fora}/rebuscar")
    assert r.json() == {"tipo": "warning", "mensagem": MENSAGENS_CASAMENTO["rebuscar_fora_da_fila"][1]}
    assert cliente.post(f"{BASE}/999999/rebuscar").status_code == 404


def test_reavaliar_marca_pares_e_avisa_o_estado_do_casador(cliente, logar, sessoes, config, dois, app_api):
    with sessoes() as s, s.begin():
        repo_casamento.ignorar(s, dois["anuncio"], dois["jogo"], T0, OrigemCasamento.AUTOMATICO_IA)
        repo_casamento.ignorar(s, dois["anuncio"], dois["colec"], T0, OrigemCasamento.AUTOMATICO_IA)
    logar(Papel.OPERADOR)
    r = cliente.post(f"{BASE}/{dois['jogo']}/reavaliar")  # IA desligada
    assert r.json() == {"tipo": "warning", "mensagem": MENSAGENS_CASAMENTO["reavaliar_ia_desligada"][1]}
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (PENDENTE, None)
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (IGNORADO, OrigemCasamento.AUTOMATICO_IA)
    app_api.state.config = config.model_copy(update={"openai_api_key": "sk-teste"})
    with sessoes() as s, s.begin():
        repo_ia.salvar_config_ia(s, {"ligado": True}, T0)
        repo.pausar(s, "pausado", T0, COLETOR_CASADOR)
    r = cliente.post(f"{BASE}/{dois['colec']}/reavaliar")
    assert r.json() == {"tipo": "warning", "mensagem": MENSAGENS_CASAMENTO["reavaliar_casador_pausado"][1]}


def test_reavaliar_com_tudo_ligado_e_sem_nada_para_reavaliar(cliente, logar, sessoes, config, dois, app_api):
    with sessoes() as s, s.begin():
        repo_casamento.ignorar(s, dois["anuncio"], dois["jogo"], T0, OrigemCasamento.AUTOMATICO_IA)
        repo_ia.salvar_config_ia(s, {"ligado": True}, T0)
    app_api.state.config = config.model_copy(update={"openai_api_key": "sk-teste"})
    logar(Papel.OPERADOR)
    r = cliente.post(f"{BASE}/{dois['jogo']}/reavaliar")
    assert r.json() == {"tipo": "success", "mensagem": MENSAGENS_CASAMENTO["reavaliar"][1]}
    with sessoes() as s, s.begin():
        assert repo.consumir_solicitacao(s, T0, COLETOR_CASADOR) is True
    with sessoes() as s, s.begin():
        repo_casamento.confirmar(s, dois["anuncio"], dois["colec"], T0)  # o par do Jogo vira outro_confirmado
    r = cliente.post(f"{BASE}/{dois['jogo']}/reavaliar")
    assert r.json() == {"tipo": "info", "mensagem": MENSAGENS_CASAMENTO["reavaliar_nada"][1]}


def test_termos_pedido_fora_da_fila_e_produto_casado(cliente, logar, sessoes, config, dois, app_api):
    logar(Papel.OPERADOR)
    r = cliente.post(f"{BASE}/{dois['jogo']}/termos")
    assert r.json() == {"tipo": "warning", "mensagem": MENSAGENS_CASAMENTO["termos_ia_desligada"][1]}
    with sessoes() as s:
        assert s.get(FilaAmazon, dois["jogo"]).termos_pedidos_em is not None
    app_api.state.config = config.model_copy(update={"openai_api_key": "sk-teste"})
    with sessoes() as s, s.begin():
        repo_ia.salvar_config_ia(s, {"ligado": True}, T0)
        fora = criar_produto(s, "fora-da-fila").id
    r = cliente.post(f"{BASE}/{dois['colec']}/termos")
    assert r.json() == {"tipo": "success", "mensagem": MENSAGENS_CASAMENTO["termos_pedidos"][1]}
    assert cliente.post(f"{BASE}/{fora}/termos").json()["mensagem"] == MENSAGENS_CASAMENTO["termos_fora_da_fila"][1]
    with sessoes() as s, s.begin():
        repo_casamento.confirmar(s, dois["anuncio"], dois["jogo"], T0)
    r = cliente.post(f"{BASE}/{dois['jogo']}/termos")
    assert r.json() == {"tipo": "info", "mensagem": MENSAGENS_CASAMENTO["termos_ja_casado"][1]}


def test_produto_inativo_404_nas_acoes_de_produto(cliente, logar, sessoes):
    with sessoes() as s, s.begin():
        inativo = criar_produto(s, "inativo", ativo=False).id
    logar(Papel.OPERADOR)
    for rota in ("rebuscar", "reavaliar", "termos"):
        assert cliente.post(f"{BASE}/{inativo}/{rota}").status_code == 404

def test_busca_e_link_com_tamanho_maximo(cliente, logar, dois):
    logar(Papel.OPERADOR)
    assert cliente.get(BASE, params={"busca": "x" * 201}).status_code == 422
    r = cliente.get(f"{BASE}/anuncios/{dois['anuncio']}/produtos", params={"busca": "x" * 201})
    assert r.status_code == 422
    r = cliente.post(f"{BASE}/{dois['jogo']}/link", json={"link": "https://www.amazon.com.br/dp/" + "x" * 500})
    assert r.status_code == 422
