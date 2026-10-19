import base64
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fakes import T0, criar_anuncio, criar_par, criar_produto
from fastapi.testclient import TestClient

from tcg_sniper.admin import consultas_amazon
from tcg_sniper.admin.app import MENSAGENS_CASAMENTO, criar_app
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db import repositorio_termos as repo_termos
from tcg_sniper.db.models import (
    COLETOR_CASADOR,
    AnuncioAmazon,
    Casamento,
    FilaAmazon,
    OrigemCasamento,
    ProdutoLiga,
    StatusCasamento,
)

PENDENTE, CONFIRMADO, IGNORADO = StatusCasamento.PENDENTE, StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO
MANUAL, OUTRO = OrigemCasamento.MANUAL, OrigemCasamento.OUTRO_CONFIRMADO


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


def _cliente(sessoes, config, **extra):
    c = config.model_copy(update={"admin_senha": "segredo", **extra})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


@pytest.fixture
def cliente(sessoes, config):
    return _cliente(sessoes, config)


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


def acao(cliente, ids, nome_acao, produto):
    voltar = f"/casamentos/produto/{ids[produto]}"
    dados = {"acao": nome_acao, "produto_id": str(ids[produto]), "voltar": voltar}
    return cliente.post(f"/casamentos/{ids['anuncio']}", data=dados, follow_redirects=False)


def msg(resposta):
    return parse_qs(urlsplit(resposta.headers["location"]).query).get("msg")


def test_confirmar_ignora_o_par_do_outro_produto(cliente, sessoes, dois):
    r = acao(cliente, dois, "confirmar", "colec")
    assert (r.status_code, r.headers["location"]) == (303, f"/casamentos/produto/{dois['colec']}")
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (CONFIRMADO, MANUAL)
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (IGNORADO, OUTRO)


def test_ignorar_vale_so_para_o_par(cliente, sessoes, dois):
    acao(cliente, dois, "ignorar", "jogo")
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (IGNORADO, MANUAL)
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (PENDENTE, None)


def test_confirmar_anuncio_ja_confirmado_mostra_erro_e_nao_muda(cliente, sessoes, dois):
    with sessoes() as s, s.begin():
        repo_casamento.confirmar(s, dois["anuncio"], dois["colec"], T0)
        par = s.get(Casamento, (dois["anuncio"], dois["jogo"]))  # a tela do Jogo ainda mostrava o pendente
        par.status, par.origem, par.revisado_em = PENDENTE, None, None
    r = acao(cliente, dois, "confirmar", "jogo")
    assert msg(r) == ["ja_confirmado"]
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (PENDENTE, None)
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (CONFIRMADO, MANUAL)
    assert "já está confirmado para outro produto" in cliente.get(r.headers["location"]).text


def test_desfazer_reabre_o_par_do_outro_produto(cliente, sessoes, dois):
    acao(cliente, dois, "confirmar", "colec")
    acao(cliente, dois, "desfazer", "colec")
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (PENDENTE, None)
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (PENDENTE, None)
    with sessoes() as s:
        assert s.get(Casamento, (dois["anuncio"], dois["colec"])).reavaliar is True


def test_trocar_confirma_o_novo_e_ignora_o_anterior_como_manual(cliente, sessoes, dois):
    with sessoes() as s, s.begin():
        terceiro = criar_produto(s, "terceiro", nome="Caixa Terceira").id
    acao(cliente, dois, "confirmar", "colec")
    dados = {"acao": "trocar", "produto_id": str(terceiro), "voltar": f"/casamentos/produto/{terceiro}"}
    r = cliente.post(f"/casamentos/{dois['anuncio']}", data=dados, follow_redirects=False)
    assert r.status_code == 303
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (IGNORADO, MANUAL)
    assert situacao(sessoes, dois["anuncio"], terceiro) == (CONFIRMADO, MANUAL)


def test_acao_sem_produto_id_400_e_par_inexistente_404(cliente, sessoes, dois):
    assert cliente.post(f"/casamentos/{dois['anuncio']}", data={"acao": "ignorar"}).status_code == 400
    with sessoes() as s, s.begin():
        sem_par = criar_produto(s, "sem-par").id
    r = cliente.post(f"/casamentos/{dois['anuncio']}", data={"acao": "ignorar", "produto_id": str(sem_par)})
    assert r.status_code == 404


def test_tela_mostra_casado_com_o_outro_produto_sem_desfazer(cliente, sessoes, dois):
    with sessoes() as s, s.begin():
        repo_casamento.confirmar(s, dois["anuncio"], dois["colec"], T0)
    texto = cliente.get(f"/casamentos/produto/{dois['jogo']}").text
    assert "casado com" in texto and "Caixa Colecionador" in texto
    assert f'href="/casamentos/produto/{dois["colec"]}"' in texto
    assert 'value="desfazer"' not in texto


def test_tela_tem_os_tres_botoes_e_os_termos(cliente, sessoes, dois):
    with sessoes() as s, s.begin():
        repo_termos.guardar_termos(s, dois["jogo"], [("caixa jogo alfa", "pt"), ("alpha play box", "en")], T0)
    texto = cliente.get(f"/casamentos/produto/{dois['jogo']}").text
    for trecho in ("Rebuscar agora", "Reavaliar com a IA", "Gerar termos de busca", "caixa jogo alfa", "alpha play box"):
        assert trecho in texto


def test_rebuscar_poe_o_produto_na_frente_da_fila(cliente, sessoes, dois):
    with sessoes() as s, s.begin():
        s.get(FilaAmazon, dois["jogo"]).proxima_busca_em = T0 + timedelta(days=3)
    r = cliente.post(f"/casamentos/produto/{dois['jogo']}/rebuscar", data={"voltar": "/casamentos"}, follow_redirects=False)
    assert msg(r) == ["rebuscar"]
    with sessoes() as s:
        assert s.get(FilaAmazon, dois["jogo"]).proxima_busca_em < T0 + timedelta(days=3)


def test_reavaliar_mexe_so_nos_pares_do_produto_e_pede_o_casador(sessoes, config, dois):
    cliente = _cliente(sessoes, config, openai_api_key="sk-teste")
    with sessoes() as s, s.begin():
        repo_ia.salvar_config_ia(s, {"ligado": True}, T0)
        repo_casamento.ignorar(s, dois["anuncio"], dois["jogo"], T0, OrigemCasamento.AUTOMATICO_IA)
        repo_casamento.ignorar(s, dois["anuncio"], dois["colec"], T0, OrigemCasamento.AUTOMATICO_IA)
        manual = criar_anuncio(s, "B0ACAO0002", produto=s.get(ProdutoLiga, dois["jogo"]), status=IGNORADO, origem=MANUAL)
        manual_id = manual.id
    r = cliente.post(f"/casamentos/produto/{dois['jogo']}/reavaliar", data={"voltar": "/casamentos"}, follow_redirects=False)
    assert msg(r) == ["reavaliar"]
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (PENDENTE, None)
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (IGNORADO, OrigemCasamento.AUTOMATICO_IA)
    assert situacao(sessoes, manual_id, dois["jogo"]) == (IGNORADO, MANUAL)
    with sessoes() as s, s.begin():
        assert repo.consumir_solicitacao(s, T0, COLETOR_CASADOR) is True


def test_gerar_termos_registra_o_pedido_e_avisa_o_estado_da_ia(sessoes, config, dois):
    desligada = _cliente(sessoes, config)
    r = desligada.post(f"/casamentos/produto/{dois['jogo']}/termos", data={"voltar": "/casamentos"}, follow_redirects=False)
    assert msg(r) == ["termos_ia_desligada"]
    with sessoes() as s:
        assert s.get(FilaAmazon, dois["jogo"]).termos_pedidos_em is not None
    with sessoes() as s, s.begin():
        repo_ia.salvar_config_ia(s, {"ligado": True}, T0)
    ligada = _cliente(sessoes, config, openai_api_key="sk-teste")
    r = ligada.post(f"/casamentos/produto/{dois['colec']}/termos", data={"voltar": "/casamentos"}, follow_redirects=False)
    assert msg(r) == ["termos_pedidos"]
    with sessoes() as s, s.begin():
        assert repo.consumir_solicitacao(s, T0, COLETOR_CASADOR) is True
        fora = criar_produto(s, "fora-da-fila").id
    r = ligada.post(f"/casamentos/produto/{fora}/termos", data={"voltar": "/casamentos"}, follow_redirects=False)
    assert msg(r) == ["termos_fora_da_fila"]


def test_gerar_termos_em_produto_ja_casado_nao_pede_nada_a_ia(cliente, sessoes, dois):
    """Busca alternativa só vale para produto sem casamento: o botão some e a rota não gasta chamada."""
    with sessoes() as s, s.begin():
        repo_casamento.confirmar(s, dois["anuncio"], dois["jogo"], T0)
    texto = cliente.get(f"/casamentos/produto/{dois['jogo']}").text
    assert "Gerar termos de busca" not in texto and f"/casamentos/produto/{dois['jogo']}/termos" not in texto
    r = cliente.post(f"/casamentos/produto/{dois['jogo']}/termos", data={"voltar": "/casamentos"}, follow_redirects=False)
    assert msg(r) == ["termos_ja_casado"]
    assert "termos_ja_casado" in MENSAGENS_CASAMENTO
    with sessoes() as s, s.begin():
        assert s.get(FilaAmazon, dois["jogo"]).termos_pedidos_em is None
        assert repo.consumir_solicitacao(s, T0, COLETOR_CASADOR) is False


def test_trocar_nao_sugere_o_produto_de_onde_veio(sessoes, dois):
    with sessoes() as s, s.begin():
        anuncio = s.get(AnuncioAmazon, dois["anuncio"])
        anuncio.titulo = "Caixa de Jogo Colecionador"
        s.flush()
        ids = {p.id for p, _ in consultas_amazon.sugestoes_para(s, anuncio, excluir={dois["jogo"]})}
    assert dois["jogo"] not in ids


def test_e_de_outro_produto_troca_e_ignora_o_par_de_onde_veio(cliente, sessoes, dois):
    with sessoes() as s, s.begin():
        terceiro = criar_produto(s, "terceiro", nome="Caixa Terceira").id
    tela = cliente.get(f"/casamentos/produto/{dois['jogo']}").text
    assert f'href="/casamentos/{dois["anuncio"]}/trocar?de={dois["jogo"]}"' in tela
    trocar = cliente.get(f"/casamentos/{dois['anuncio']}/trocar", params={"de": dois["jogo"], "busca": "Terceira"}).text
    assert f'name="de" value="{dois["jogo"]}"' in trocar  # a busca e o "Escolher" levam o produto de onde veio
    dados = {"acao": "trocar", "produto_id": str(terceiro), "de": str(dois["jogo"]), "voltar": f"/casamentos/produto/{terceiro}"}
    r = cliente.post(f"/casamentos/{dois['anuncio']}", data=dados, follow_redirects=False)
    assert r.status_code == 303
    assert situacao(sessoes, dois["anuncio"], terceiro) == (CONFIRMADO, MANUAL)
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (IGNORADO, MANUAL)
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (IGNORADO, OUTRO)
    # desfazer o novo reabre só o `outro_confirmado`; o "não é este" que você deu fica
    acao(cliente, {**dois, "terceiro": terceiro}, "desfazer", "terceiro")
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (IGNORADO, MANUAL)
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (PENDENTE, None)


def test_trocar_com_de_invalido_400(cliente, dois):
    dados = {"acao": "trocar", "produto_id": str(dois["colec"]), "de": "x"}
    assert cliente.post(f"/casamentos/{dois['anuncio']}", data=dados).status_code == 400


def test_reavaliar_nao_mexe_em_decisao_sua_nem_no_casado_em_outro_produto(cliente, sessoes, dois):
    with sessoes() as s, s.begin():
        repo_casamento.confirmar(s, dois["anuncio"], dois["colec"], T0)  # Jogo vira outro_confirmado
        outro = criar_anuncio(s, "B0ACAO0003", produto=s.get(ProdutoLiga, dois["jogo"]), status=IGNORADO,
                              origem=OrigemCasamento.SUGERIDO_IA)
        outro_id = outro.id
    r = cliente.post(f"/casamentos/produto/{dois['jogo']}/reavaliar", data={"voltar": "/casamentos"}, follow_redirects=False)
    assert msg(r) == ["reavaliar_nada"]
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (IGNORADO, OUTRO)
    assert situacao(sessoes, outro_id, dois["jogo"]) == (IGNORADO, OrigemCasamento.SUGERIDO_IA)
    with sessoes() as s, s.begin():
        assert repo.consumir_solicitacao(s, T0, COLETOR_CASADOR) is False
    texto = cliente.get(r.headers["location"]).text
    _, aviso = MENSAGENS_CASAMENTO["reavaliar_nada"]
    assert aviso in texto and "sugerido" not in aviso  # não promete reabrir decisão sua


def test_tela_explica_o_que_reavaliar_reabre(cliente, dois):
    texto = cliente.get(f"/casamentos/produto/{dois['jogo']}").text
    assert "pendentes, os ignorados pelo automático" in texto


def test_rebuscar_produto_fora_da_fila_avisa_em_vez_de_prometer_a_busca(cliente, sessoes):
    with sessoes() as s, s.begin():
        fora = criar_produto(s, "fora-da-fila").id
    r = cliente.post(f"/casamentos/produto/{fora}/rebuscar", data={"voltar": "/casamentos"}, follow_redirects=False)
    assert msg(r) == ["rebuscar_fora_da_fila"]
    _, texto = MENSAGENS_CASAMENTO["rebuscar_fora_da_fila"]
    assert "alguns minutos" in texto and "na frente da fila" not in texto


def test_reavaliar_e_termos_nao_prometem_em_instantes_com_o_casador_parado(sessoes, config, dois):
    with sessoes() as s, s.begin():
        repo_casamento.ignorar(s, dois["anuncio"], dois["jogo"], T0, OrigemCasamento.AUTOMATICO_IA)
        repo_casamento.ignorar(s, dois["anuncio"], dois["colec"], T0, OrigemCasamento.AUTOMATICO_IA)
    desligada = _cliente(sessoes, config, openai_api_key="sk-teste")  # IA desligada em Configurações
    r = desligada.post(f"/casamentos/produto/{dois['jogo']}/reavaliar", data={"voltar": "/casamentos"}, follow_redirects=False)
    assert msg(r) == ["reavaliar_ia_desligada"]
    with sessoes() as s, s.begin():
        repo_ia.salvar_config_ia(s, {"ligado": True}, T0)
        repo.pausar(s, "pausado no admin", T0, COLETOR_CASADOR)
    pausado = _cliente(sessoes, config, openai_api_key="sk-teste")
    r = pausado.post(f"/casamentos/produto/{dois['colec']}/reavaliar", data={"voltar": "/casamentos"}, follow_redirects=False)
    assert msg(r) == ["reavaliar_casador_pausado"]
    r = pausado.post(f"/casamentos/produto/{dois['jogo']}/termos", data={"voltar": "/casamentos"}, follow_redirects=False)
    assert msg(r) == ["termos_casador_pausado"]
    with sessoes() as s:
        assert s.get(FilaAmazon, dois["jogo"]).termos_pedidos_em is not None  # o pedido fica guardado
    for chave in ("reavaliar_ia_desligada", "reavaliar_casador_pausado", "termos_casador_pausado"):
        nivel, texto = MENSAGENS_CASAMENTO[chave]
        assert nivel == "warning" and "em instantes" not in texto


def test_busca_do_trocar_nao_oferece_o_produto_de_onde_veio_nem_o_ja_confirmado(cliente, sessoes, dois):
    with sessoes() as s, s.begin():
        terceiro = criar_produto(s, "terceiro", nome="Caixa Terceira").id
        repo_casamento.confirmar(s, dois["anuncio"], dois["colec"], T0)
    texto = cliente.get(f"/casamentos/{dois['anuncio']}/trocar", params={"de": dois["jogo"], "busca": "Caixa"}).text
    assert f'name="produto_id" value="{terceiro}"' in texto
    assert f'name="produto_id" value="{dois["jogo"]}"' not in texto
    assert f'name="produto_id" value="{dois["colec"]}"' not in texto
