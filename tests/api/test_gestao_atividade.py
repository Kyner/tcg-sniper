from datetime import timedelta

from fakes import T0
from sqlalchemy import func, select

from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import AcaoGestao, MensagemSaida, Papel, StatusMensagem, TipoAcaoGestao

ROTA = "/api/gestao/atividade"
MSG = "/api/gestao/mensagens"


def _mensagem(sessoes, quando, status=StatusMensagem.FALHA, destino="oportunidades", texto="*Aviso*\nCaixa X"):
    with sessoes() as s, s.begin():
        m = MensagemSaida(
            destino=destino, numero="+5511900000009" if destino == "individual" else None, texto=texto, status=status,
            proxima_tentativa_em=quando, criada_em=quando, atualizado_em=quando,
            ultimo_erro="400 grupo" if status is StatusMensagem.FALHA else None,
        )
        s.add(m)
        s.flush()
        return m.id


def _status(sessoes, id_):
    with sessoes() as s:
        return s.get(MensagemSaida, id_).status


def test_sem_sessao_401_e_sem_permissao_403(cliente, app_api, logar, sessoes):
    escritas = [("post", f"{MSG}/1/reenviar"), ("post", f"{MSG}/1/descartar")]
    for metodo, rota in [("get", ROTA), *escritas]:
        assert cliente.request(metodo, rota).status_code == 401
    logar(Papel.GRUPO)
    for metodo, rota in [("get", ROTA), *escritas]:
        r = cliente.request(metodo, rota)
        assert r.status_code == 403 and r.json()["erro"] == "sem_permissao"
    logar(Papel.OPERADOR)
    assert cliente.get(ROTA).status_code == 200
    for _, rota in escritas:
        assert cliente.post(rota).status_code == 403  # operador não reenvia
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.OPERADOR, "ver_logs", False)
    app_api.state.grade.invalidar()
    assert cliente.get(ROTA).status_code == 403


def test_pagina_com_cursor(cliente, logar, sessoes):
    ids = [_mensagem(sessoes, T0 + timedelta(minutes=i)) for i in range(55)]
    logar(Papel.OPERADOR)
    primeira = cliente.get(ROTA, params={"o_que": "mensagem"})
    assert primeira.status_code == 200
    corpo = primeira.json()
    assert set(corpo) == {"itens", "proximo"}
    assert len(corpo["itens"]) == 50 and corpo["proximo"]
    segunda = cliente.get(ROTA, params={"o_que": "mensagem", "cursor": corpo["proximo"]}).json()
    assert segunda["proximo"] is None
    vistos = [i["detalhe"]["mensagem_id"] for i in corpo["itens"] + segunda["itens"]]
    assert vistos == list(reversed(ids))
    assert set(corpo["itens"][0]) == {
        "chave", "em", "servico", "o_que", "situacao", "resultado", "produto_id", "produto", "asin", "custo_usd",
        "detalhe",
    }
    assert corpo["itens"][0]["o_que"] == "mensagem" and corpo["itens"][0]["servico"] == "whatsapp"


def test_filtros_e_busca(cliente, logar, sessoes):
    _mensagem(sessoes, T0, texto="*Aviso*\nCaixa Azul")
    _mensagem(sessoes, T0 + timedelta(minutes=1), texto="*Aviso*\nCaixa Verde")
    logar(Papel.OPERADOR)
    r = cliente.get(ROTA, params={"servico": "whatsapp", "busca": "Azul", "situacao": "falha"})
    assert len(r.json()["itens"]) == 1
    assert cliente.get(ROTA, params={"busca": "x" * 101}).status_code == 422
    assert cliente.get(ROTA, params={"o_que": "inventado"}).status_code == 422
    de = (T0 + timedelta(seconds=30)).isoformat()
    assert len(cliente.get(ROTA, params={"o_que": "mensagem", "de": de}).json()["itens"]) == 1
    assert cliente.get(ROTA, params={"de": "2026-10-13T10:00:00"}).status_code == 422  # sem fuso


def test_sem_ver_mensagens_esconde_o_texto(cliente, app_api, logar, sessoes):
    _mensagem(sessoes, T0, texto="*Aviso*\nCaixa Azul")
    logar(Papel.OPERADOR)
    detalhe = cliente.get(ROTA, params={"o_que": "mensagem"}).json()["itens"][0]["detalhe"]
    assert detalhe["texto"] == "*Aviso*\nCaixa Azul"
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.OPERADOR, "ver_mensagens", False)
    app_api.state.grade.invalidar()
    r = cliente.get(ROTA, params={"o_que": "mensagem"})
    assert r.status_code == 200
    item = r.json()["itens"][0]
    assert item["detalhe"]["texto"] is None
    assert "Caixa Azul" not in r.text  # nem no resultado da linha


def test_sem_ver_configuracoes_esconde_os_valores(cliente, app_api, logar, sessoes):
    with sessoes() as s, s.begin():
        s.add(AcaoGestao(
            tipo=TipoAcaoGestao.CONFIGURACOES, em=T0,
            detalhe={"campos": {"geral.whatsapp_grupo_admin": [None, "grupo-secreto@g.us"]}},
        ))
    logar(Papel.OPERADOR)
    assert "grupo-secreto@g.us" in cliente.get(ROTA, params={"o_que": "acao_gestao"}).text
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.OPERADOR, "ver_configuracoes", False)
    app_api.state.grade.invalidar()
    r = cliente.get(ROTA, params={"o_que": "acao_gestao"})
    assert r.status_code == 200
    [item] = r.json()["itens"]
    assert "grupo de WhatsApp do admin" in item["resultado"]
    assert "grupo-secreto" not in r.text and "→" not in item["resultado"]
    assert cliente.get(ROTA, params={"busca": "grupo-secreto"}).json()["itens"] == []


def test_texto_individual_nunca_aparece(cliente, logar, sessoes):
    _mensagem(sessoes, T0, destino="individual", texto="Seu código: 123456")
    logar(Papel.ADMIN)
    r = cliente.get(ROTA, params={"o_que": "mensagem"})
    assert "123456" not in r.text and "5511900000009" not in r.text
    assert cliente.get(ROTA, params={"busca": "123456"}).json()["itens"] == []


def test_cursor_invalido_422(cliente, logar):
    logar(Papel.OPERADOR)
    r = cliente.get(ROTA, params={"cursor": "lixo"})
    assert r.status_code == 422 and r.json()["erro"] == "validacao"


def test_reenviar_e_descartar(cliente, logar, sessoes):
    falha = _mensagem(sessoes, T0)
    outra = _mensagem(sessoes, T0)
    enviada = _mensagem(sessoes, T0, status=StatusMensagem.ENVIADA)
    individual = _mensagem(sessoes, T0, destino="individual", texto="Seu código: 1")
    logar(Papel.ADMIN)

    r = cliente.post(f"{MSG}/{falha}/reenviar")
    assert r.status_code == 200 and r.json() == {"status": "pendente"}
    assert _status(sessoes, falha) is StatusMensagem.PENDENTE
    r = cliente.post(f"{MSG}/{outra}/descartar")
    assert r.status_code == 200 and r.json() == {"status": "descartada"}
    assert _status(sessoes, outra) is StatusMensagem.DESCARTADA

    for rota in (f"{MSG}/{enviada}/reenviar", f"{MSG}/{enviada}/descartar", f"{MSG}/{individual}/reenviar"):
        r = cliente.post(rota)
        assert r.status_code == 409 and r.json()["erro"] == "acao_invalida"
    for rota in (f"{MSG}/99999/reenviar", f"{MSG}/99999/descartar", f"{MSG}/0/reenviar", f"{MSG}/2147483648/descartar"):
        r = cliente.post(rota)
        assert r.status_code == 404 and r.json()["erro"] == "nao_encontrado"
    with sessoes() as s:
        assert s.scalar(select(func.count()).select_from(AcaoGestao)) == 0  # ação de mensagem não vai a acao_gestao


def test_sem_ver_mensagens_a_busca_nao_sonda_o_texto(cliente, app_api, logar, sessoes):
    _mensagem(sessoes, T0, texto="*Aviso*\nCaixa Azul")
    logar(Papel.OPERADOR)
    assert len(cliente.get(ROTA, params={"busca": "Azul"}).json()["itens"]) == 1
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.OPERADOR, "ver_mensagens", False)
    app_api.state.grade.invalidar()
    assert cliente.get(ROTA, params={"busca": "Azul"}).json()["itens"] == []


def test_destino_e_situacao_pendente(cliente, logar, sessoes):
    _mensagem(sessoes, T0, status=StatusMensagem.PENDENTE, destino="admin")
    _mensagem(sessoes, T0 + timedelta(minutes=1), status=StatusMensagem.FALHA, destino="oportunidades")
    logar(Papel.OPERADOR)
    pend = cliente.get(ROTA, params={"situacao": "pendente"}).json()["itens"]
    assert [i["detalhe"]["status"] for i in pend] == ["pendente"]
    adm = cliente.get(ROTA, params={"destino": "admin"}).json()["itens"]
    assert [i["detalhe"]["destino"] for i in adm] == ["admin"]
    assert cliente.get(ROTA, params={"destino": "inventado"}).status_code == 422
    assert cliente.get(ROTA, params={"situacao": "inventada"}).status_code == 422
