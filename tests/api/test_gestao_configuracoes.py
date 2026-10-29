import json
from datetime import timedelta

import fakes_api
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from tcg_sniper.api.app import criar_app
from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import CATALOGO, TipoAviso
from tcg_sniper.coletor_amazon.config import aplicar_config
from tcg_sniper.configuracoes.grupos import GRUPOS
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import AcaoGestao, ConfigGeral, ConfigLiga, Papel, TipoAcaoGestao

ROTA = "/api/gestao/configuracoes"
EFEITO = f"{ROTA}/efeito"
AVISO = "/api/gestao/avisos/liga_desafio"
SEGREDOS = {
    "admin_senha": "senha-admin-falsa-7f3a",
    "segredo_api": fakes_api.SEGREDO_TESTE,  # o mesmo das sessões falsas (o login depende dele)
    "evolution_api_key": "chave-evolution-falsa-91bd",
    "evolution_url": "http://evolution-falsa.test:9911",
    "openai_api_key": "sk-openai-falsa-55c1",
    "r2_account_id": "conta-r2-falsa-0aa1",
    "r2_access_key_id": "acesso-r2-falso-0bb2",
    "r2_secret_access_key": "segredo-r2-falso-0cc3",
    "r2_bucket": "balde-r2-falso-0dd4",
    "r2_bucket_imagens": "balde-imagens-falso-0ee5",
    "r2_imagens_access_key_id": "acesso-imagens-falso-0ff6",
    "r2_imagens_secret_access_key": "segredo-imagens-falso-0007",
    "database_url": "postgresql+psycopg://usuario-falso:senha-banco-falsa@db-falso.test:5432/tcg",
}
NOMES_SEGREDOS = set(SEGREDOS) | {"vnc_senha"}


def _acoes(sessoes):
    with sessoes() as s:
        return [(a.tipo, a.detalhe) for a in s.scalars(select(AcaoGestao).order_by(AcaoGestao.id))]


def _salvar(cliente, valores, versoes=None):
    if versoes is None:
        versoes = cliente.get(ROTA).json()["versoes"]
    return cliente.put(ROTA, json={"versoes": versoes, "valores": valores})


def _valores(corpo):
    return {c["chave"]: c["valor"] for g in corpo["grupos"] for c in g["campos"]}


def _amazon(sessoes):
    with sessoes() as s:
        return repo_amz.obter_config(s)


def _ia(sessoes):
    with sessoes() as s, s.begin():
        return repo_ia.obter_config_ia(s)


def test_sem_sessao_401_e_sem_permissao_403(cliente, app_api, logar, sessoes):
    corpo_put = {"versoes": {}, "valores": {}}
    leituras = [("get", ROTA, None), ("post", EFEITO, {"grupo": "monitor", "valores": {}})]
    escritas = [("put", ROTA, corpo_put), ("patch", AVISO, {"ligado": False})]
    for metodo, rota, corpo in [*leituras, *escritas]:
        assert cliente.request(metodo, rota, json=corpo).status_code == 401
    logar(Papel.GRUPO)
    for metodo, rota, corpo in [*leituras, *escritas]:
        r = cliente.request(metodo, rota, json=corpo)
        assert r.status_code == 403 and r.json()["erro"] == "sem_permissao"
    logar(Papel.OPERADOR)
    for metodo, rota, corpo in leituras:
        assert cliente.request(metodo, rota, json=corpo).status_code == 200
    for metodo, rota, corpo in escritas:
        assert cliente.request(metodo, rota, json=corpo).status_code == 403
    assert _acoes(sessoes) == []
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.OPERADOR, "ver_configuracoes", False)
    app_api.state.grade.invalidar()
    assert cliente.get(ROTA).status_code == 403


def test_get_traz_grupos_valores_versoes_avisos_e_ia(cliente, logar):
    logar(Papel.OPERADOR)
    corpo = cliente.get(ROTA).json()
    assert set(corpo) == {"grupos", "versoes", "avisos", "ia"}
    assert [g["id"] for g in corpo["grupos"]] == [g.id for g in GRUPOS]
    assert set(corpo["versoes"]) == {"geral", "liga", "amazon", "ia"}
    assert corpo["ia"] == {"chave_configurada": False}
    monitor = next(g for g in corpo["grupos"] if g["id"] == "monitor")
    assert monitor["tem_efeito"] is True and monitor["proposito"]
    campo = monitor["campos"][0]
    assert set(campo) == {
        "chave", "rotulo", "explicacao", "tipo", "padrao", "minimo", "maximo", "opcoes", "avancado", "vinculo", "valor"
    }
    valores = _valores(corpo)
    assert valores["amazon.janela_inicio"] == "08:00"
    assert valores["amazon.desconto_min_pct"] == 25
    assert valores["ia.ligado"] is False
    assert isinstance(valores["ia.teto_dia_usd"], str)
    assert valores["liga.categorias"] == "10,11,12"
    esforco = next(c for g in corpo["grupos"] for c in g["campos"] if c["chave"] == "ia.esforco")
    assert {"valor": "medium", "rotulo": "médio"} in esforco["opcoes"]
    desconto = next(c for g in corpo["grupos"] for c in g["campos"] if c["chave"] == "amazon.desconto_min_pct")
    assert (desconto["minimo"], desconto["maximo"], desconto["padrao"]) == (1, 90, 25)
    assert len(corpo["avisos"]) == len(CATALOGO)
    aviso = next(a for a in corpo["avisos"] if a["tipo"] == "liga_desafio")
    assert set(aviso) == {"tipo", "titulo", "descricao", "area", "destino", "agrupa", "ligado", "exemplo"}
    definicao = CATALOGO[TipoAviso.LIGA_DESAFIO]
    assert aviso["titulo"] == definicao.titulo and aviso["area"] == definicao.origem
    assert aviso["destino"] == "grupo admin" and aviso["ligado"] is True
    assert definicao.titulo in aviso["exemplo"]
    assert not any("host.test" in a["exemplo"] for a in corpo["avisos"])  # host_publico nunca sai no WhatsApp


def test_put_salva_so_os_alterados_e_registra_antes_depois(cliente, logar, sessoes, relogio):
    usuario_id = logar(Papel.ADMIN)
    antes = cliente.get(ROTA).json()
    relogio.agora += timedelta(minutes=1)
    r = _salvar(cliente, {
        "amazon.desconto_min_pct": 30,
        "amazon.realerta_queda_pct": 5,  # igual ao salvo: não conta como alteração
        "ia.lote": "35",
        "ia.automatico": True,
        "liga.pausa_min_s": "9,5",
    }, antes["versoes"])
    assert r.status_code == 200, r.text
    corpo = r.json()
    valores = _valores(corpo)
    assert (valores["amazon.desconto_min_pct"], valores["ia.lote"], valores["ia.automatico"]) == (30, 35, True)
    assert valores["liga.pausa_min_s"] == 9.5
    assert _amazon(sessoes).desconto_min_pct == 30
    assert _ia(sessoes).lote == 35
    # Tabela não tocada mantém a versão; as tocadas ganham a nova.
    assert corpo["versoes"]["geral"] == antes["versoes"]["geral"]
    assert corpo["versoes"]["amazon"] != antes["versoes"]["amazon"]
    assert _acoes(sessoes) == [(TipoAcaoGestao.CONFIGURACOES, {"campos": {
        "amazon.desconto_min_pct": [25, 30],
        "ia.lote": [20, 35],
        "ia.automatico": [False, True],
        "liga.pausa_min_s": [8.0, 9.5],
    }})]
    with sessoes() as s:
        assert s.scalars(select(AcaoGestao.usuario_id)).one() == usuario_id


def test_put_sem_mudanca_nao_grava_acao(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    r = _salvar(cliente, {"amazon.desconto_min_pct": 25})
    assert r.status_code == 200
    assert _acoes(sessoes) == []


def test_put_invalido_nao_grava_nada(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    antes = cliente.get(ROTA).json()
    r = _salvar(cliente, {
        "amazon.quase_oportunidade_min_pct": 30,  # >= desconto mínimo (25): regra cruzada
        "amazon.janela_inicio": "23:00",  # depois do fim (22:00)
        "liga.pausa_min_s": "25",  # maior que a máxima (20)
        "geral.whatsapp_grupo_admin": "sem-arroba",
        "ia.lote": 40,  # válido, mas não pode ser gravado
    }, antes["versoes"])
    assert r.status_code == 422
    erro = r.json()
    assert erro["erro"] == "validacao"
    assert set(erro["campos"]) == {
        "amazon.quase_oportunidade_min_pct", "amazon.janela_fim", "liga.pausa_min_s", "geral.whatsapp_grupo_admin"
    }
    assert "abaixo do desconto mínimo" in erro["campos"]["amazon.quase_oportunidade_min_pct"]
    assert _ia(sessoes).lote == 20
    assert _amazon(sessoes).quase_oportunidade_min_pct == 10
    assert cliente.get(ROTA).json()["versoes"] == antes["versoes"]
    assert _acoes(sessoes) == []
    # Formato inválido também volta junto ao campo.
    r = _salvar(cliente, {"ia.teto_dia_usd": "muito", "amazon.janela_fim": "25:00"})
    assert r.status_code == 422
    assert set(r.json()["campos"]) == {"ia.teto_dia_usd", "amazon.janela_fim"}


def test_put_campo_desconhecido_422(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    for chave in ("amazon.inexistente", "amazon.monitor_ligado", "amazon.checkout_ligado", "ia.id", "outra.x", "x"):
        r = _salvar(cliente, {chave: 1, "ia.lote": 30})
        assert r.status_code == 422, chave
        assert set(r.json()["campos"]) == {chave}
    assert _ia(sessoes).lote == 20
    assert cliente.put(ROTA, json={"versoes": {}, "valores": {}, "extra": 1}).status_code == 422


def test_put_com_versao_velha_409(cliente, logar, sessoes, relogio):
    logar(Papel.ADMIN)
    antes = cliente.get(ROTA).json()["versoes"]
    # Outra pessoa salvou a Amazon depois da leitura.
    with sessoes() as s, s.begin():
        aplicar_config(s, {"desconto_min_pct": 40}, relogio.agora + timedelta(seconds=30))
    r = _salvar(cliente, {"amazon.desconto_min_pct": 30, "ia.lote": 30}, antes)
    assert r.status_code == 409 and r.json()["erro"] == "config_mudou"
    assert _amazon(sessoes).desconto_min_pct == 40
    assert _ia(sessoes).lote == 20
    assert _acoes(sessoes) == []
    # Versão ausente ou ilegível da tabela tocada também é conflito.
    assert _salvar(cliente, {"ia.lote": 30}, {}).status_code == 409
    assert _salvar(cliente, {"ia.lote": 30}, {**antes, "ia": "ontem"}).status_code == 409
    # Só as tabelas tocadas contam: salvar a IA com a versão velha da Amazon passa.
    r = _salvar(cliente, {"ia.lote": 30}, antes)
    assert r.status_code == 200
    assert _ia(sessoes).lote == 30


def _configuracao_com_segredos(config):
    tipos_secretos = {"segredo_api", "r2_access_key_id", "r2_secret_access_key", "r2_imagens_access_key_id",
                      "r2_imagens_secret_access_key"}
    return config.model_copy(update={
        nome: SecretStr(valor) if nome in tipos_secretos else valor for nome, valor in SEGREDOS.items()
    })


def _chaves(valor):
    if isinstance(valor, dict):
        for chave, item in valor.items():
            yield chave
            yield from _chaves(item)
    elif isinstance(valor, list):
        for item in valor:
            yield from _chaves(item)


def test_resposta_nunca_tem_segredo(sessoes, config, relogio):
    app = criar_app(sessoes, _configuracao_com_segredos(config), relogio=relogio)
    cliente = TestClient(app)
    fakes_api.logar(sessoes, cliente, Papel.ADMIN)
    respostas = [cliente.get(ROTA)]
    respostas.append(_salvar(cliente, {"ia.lote": 30}))
    respostas.append(_salvar(cliente, {"ia.lote": 0}))  # 422
    respostas.append(cliente.post(EFEITO, json={"grupo": "ia-gasto", "valores": {"ia.teto_dia_usd": "3"}}))
    respostas.append(cliente.patch(AVISO, json={"ligado": False}))
    assert [r.status_code for r in respostas] == [200, 200, 422, 200, 200]
    assert respostas[0].json()["ia"] == {"chave_configurada": True}
    for r in respostas:
        texto = r.text
        for nome, valor in SEGREDOS.items():
            assert valor not in texto, nome
        chaves = {c.split(".")[-1].casefold() for c in _chaves(r.json())}
        chaves |= {c.split(".")[-1].casefold() for c in _valores(r.json())} if "grupos" in r.json() else set()
        assert not chaves & NOMES_SEGREDOS
        assert not any(c.startswith("r2_") for c in chaves)


def test_nao_expoe_campos_de_servicos(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    chaves = set(_valores(cliente.get(ROTA).json()))
    for nome in ("monitor_ligado", "checkout_ligado", "checkout_sem_login_em"):
        assert f"amazon.{nome}" not in chaves
        r = _salvar(cliente, {f"amazon.{nome}": False})
        assert r.status_code == 422
    assert _amazon(sessoes).monitor_ligado is True


def test_patch_aviso(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    r = cliente.patch(AVISO, json={"ligado": False})
    assert r.status_code == 200
    assert r.json()["tipo"] == "liga_desafio" and r.json()["ligado"] is False
    with sessoes() as s:
        assert avisos.ligados(s)[TipoAviso.LIGA_DESAFIO] is False
    assert next(a for a in cliente.get(ROTA).json()["avisos"] if a["tipo"] == "liga_desafio")["ligado"] is False
    assert cliente.patch(AVISO, json={"ligado": True}).json()["ligado"] is True
    assert _acoes(sessoes) == [
        (TipoAcaoGestao.CONFIGURACOES, {"aviso": "liga_desafio", "ligado": False}),
        (TipoAcaoGestao.CONFIGURACOES, {"aviso": "liga_desafio", "ligado": True}),
    ]
    r = cliente.patch("/api/gestao/avisos/nao_existe", json={"ligado": True})
    assert r.status_code == 404 and r.json()["erro"] == "nao_encontrado"
    assert cliente.patch(AVISO, json={"ligado": True, "outro": 1}).status_code == 422
    assert cliente.patch(AVISO, json={}).status_code == 422
    assert len(_acoes(sessoes)) == 2


def test_efeito_do_monitor(cliente, logar, sessoes):
    logar(Papel.OPERADOR)
    r = cliente.post(EFEITO, json={"grupo": "monitor", "valores": {
        "amazon.monitor_intervalo_min": "15", "amazon.monitor_max_paginas_hora": "300",
    }})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert set(corpo) == {"linhas", "nivel", "barras"}
    assert corpo["nivel"] == "info"
    assert "estimativa" in " ".join(corpo["linhas"])
    assert _acoes(sessoes) == []
    gasto = cliente.post(EFEITO, json={"grupo": "ia-gasto", "valores": {}}).json()
    assert all(set(b) == {"rotulo", "pct"} for b in gasto["barras"])
    assert cliente.post(EFEITO, json={"grupo": "vendedores", "valores": {}}).json() is None
    r = cliente.post(EFEITO, json={"grupo": "nao_existe", "valores": {}})
    assert r.status_code == 404
    r = cliente.post(EFEITO, json={"grupo": "monitor", "valores": {"ia.lote": "3"}})  # campo de outro grupo
    assert r.status_code == 422 and set(r.json()["campos"]) == {"ia.lote"}


def test_admin_antigo_e_api_gravam_a_mesma_linha(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    assert _salvar(cliente, {"geral.validade_oportunidade_h": 12, "liga.categorias": "10, 11,10"}).status_code == 200
    with sessoes() as s:
        assert s.get(ConfigGeral, 1).validade_oportunidade_h == 12
        assert s.get(ConfigLiga, 1).categorias == "10,11"
    assert json.loads(json.dumps(_acoes(sessoes)[0][1]))["campos"]["liga.categorias"] == ["10,11,12", "10,11"]
