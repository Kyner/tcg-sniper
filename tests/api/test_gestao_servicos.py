from datetime import timedelta

from fakes import T0, criar_anuncio, criar_produto
from sqlalchemy import func, select

from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    COLETOR_CASADOR,
    COLETOR_LIGA,
    COLETOR_NOTIFICADOR,
    AcaoGestao,
    ConferenciaCheckout,
    EstadoColetorTipo,
    MensagemSaida,
    Papel,
    SituacaoCheckout,
    StatusCasamento,
    TipoAcaoGestao,
)

LISTA = "/api/gestao/servicos"
ORDEM = ["liga", "amazon_busca", "amazon_monitor", "casador", "whatsapp", "backup"]


def _acoes(sessoes):
    with sessoes() as s:
        return [(a.tipo, a.detalhe) for a in s.scalars(select(AcaoGestao).order_by(AcaoGestao.id))]


def _servico(cliente, id_):
    return next(x for x in cliente.get(LISTA).json()["servicos"] if x["id"] == id_)


def _estado(sessoes, coletor):
    with sessoes() as s, s.begin():
        return repo.obter_estado(s, T0, coletor).estado


def _pausar(sessoes, coletor, desafio=False, agora=T0):
    with sessoes() as s, s.begin():
        (repo.pausar_por_desafio if desafio else repo.pausar)(s, "teste", agora, coletor)


def test_sem_sessao_401_e_sem_permissao_403(cliente, app_api, logar, sessoes):
    escritas = [
        ("post", f"{LISTA}/liga/desligar"),
        ("post", f"{LISTA}/amazon_monitor/monitor/ligar"),
        ("post", f"{LISTA}/amazon_monitor/checkout/retomar"),
        ("post", f"{LISTA}/carrinho/1/conferido"),
    ]
    for metodo, rota in [("get", LISTA), *escritas]:
        assert cliente.request(metodo, rota).status_code == 401
    logar(Papel.GRUPO)
    for metodo, rota in [("get", LISTA), *escritas]:
        r = cliente.request(metodo, rota)
        assert r.status_code == 403 and r.json()["erro"] == "sem_permissao"
    logar(Papel.OPERADOR)
    assert cliente.get(LISTA).status_code == 200
    for metodo, rota in escritas:
        assert cliente.request(metodo, rota).status_code == 403
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.OPERADOR, "ver_servicos", False)
    app_api.state.grade.invalidar()
    assert cliente.get(LISTA).status_code == 403


def test_lista_os_seis_servicos_na_ordem(cliente, logar):
    logar(Papel.OPERADOR)
    servicos = cliente.get(LISTA).json()["servicos"]
    assert [x["id"] for x in servicos] == ORDEM
    assert [x["nome"] for x in servicos] == [
        "LigaMagic", "Amazon · busca", "Amazon · monitor", "Casador (IA)", "WhatsApp", "Backup"
    ]
    assert [x["atividade"] for x in servicos] == [f"servico={i}" for i in ORDEM]
    for x in servicos:
        assert set(x) == {
            "id", "nome", "estado", "agora", "detalhe", "ultimo_ok", "ligado", "transicao", "acoes", "abrir",
            "atividade", "sub",
        }
        assert x["estado"] in {"rodando", "esperando", "atrasado", "com_problema", "desligado"}
    assert [x["sub"] is not None for x in servicos] == [False, False, True, False, False, False]


def test_operador_ve_sem_acoes_nem_abrir(cliente, logar):
    logar(Papel.OPERADOR)
    for x in cliente.get(LISTA).json()["servicos"]:
        assert x["acoes"] == [] and x["abrir"] is None


def test_admin_ve_abrir_com_host_publico(cliente, logar):
    logar(Papel.ADMIN)
    por_id = {x["id"]: x for x in cliente.get(LISTA).json()["servicos"]}
    # host_publico da configuração dos testes: host.test
    assert por_id["liga"]["abrir"] == "http://host.test:6080/vnc.html"
    assert por_id["amazon_monitor"]["abrir"] == "http://host.test:6081/vnc.html"
    assert por_id["amazon_busca"]["abrir"] == "http://host.test:6082/vnc.html"
    assert por_id["whatsapp"]["abrir"] == "http://127.0.0.1:8080/manager"
    assert por_id["backup"]["abrir"] is None and por_id["casador"]["abrir"] is None


def test_acoes_so_as_validas_no_estado(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    assert _servico(cliente, "liga")["acoes"] == ["desligar", "rodar_agora"]
    assert _servico(cliente, "casador")["acoes"] == ["desligar", "rodar_agora"]
    assert _servico(cliente, "whatsapp")["acoes"] == ["desligar"]
    _pausar(sessoes, COLETOR_LIGA)
    assert _servico(cliente, "liga")["acoes"] == ["ligar"]
    assert _servico(cliente, "liga")["ligado"] is False
    _pausar(sessoes, COLETOR_AMAZON, desafio=True)
    assert _servico(cliente, "amazon_monitor")["acoes"] == ["retomar"]


def test_desligar_e_ligar_gravam_acao_e_avisam(cliente, logar, sessoes):
    uid = logar(Papel.ADMIN)
    r = cliente.post(f"{LISTA}/whatsapp/desligar")
    assert r.status_code == 200
    assert r.json()["codigo"] == "notificador_pausar"
    assert "WhatsApp" in r.json()["mensagem"]
    assert _estado(sessoes, COLETOR_NOTIFICADOR) is EstadoColetorTipo.PAUSADO
    with sessoes() as s:
        assert s.scalar(select(func.count()).select_from(MensagemSaida)) == 1
        assert s.scalar(select(AcaoGestao.usuario_id)) == uid
    assert _servico(cliente, "whatsapp")["ligado"] is False
    r = cliente.post(f"{LISTA}/whatsapp/ligar")
    assert r.json()["codigo"] == "notificador_retomar"
    assert _estado(sessoes, COLETOR_NOTIFICADOR) is EstadoColetorTipo.ATIVO
    assert _acoes(sessoes) == [
        (TipoAcaoGestao.SERVICO, {"servico": "whatsapp", "acao": "desligar", "codigo": "notificador_pausar"}),
        (TipoAcaoGestao.SERVICO, {"servico": "whatsapp", "acao": "ligar", "codigo": "notificador_retomar"}),
    ]


def test_clicar_desligar_duas_vezes_e_idempotente(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    assert cliente.post(f"{LISTA}/liga/desligar").status_code == 200
    antes = _servico(cliente, "liga")["estado"]
    assert cliente.post(f"{LISTA}/liga/desligar").status_code == 200
    assert _servico(cliente, "liga")["estado"] == antes == "desligado"
    assert len(_acoes(sessoes)) == 2


def test_desligar_liga_com_desafio_devolve_desafio_pendente(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    _pausar(sessoes, COLETOR_LIGA, desafio=True)
    r = cliente.post(f"{LISTA}/liga/desligar")
    assert r.status_code == 200 and r.json()["codigo"] == "desafio_pendente"
    assert _estado(sessoes, COLETOR_LIGA) is EstadoColetorTipo.PAUSADO_DESAFIO
    assert _acoes(sessoes)[0][1]["codigo"] == "desafio_pendente"
    assert _servico(cliente, "liga")["acoes"] == ["retomar"]
    r = cliente.post(f"{LISTA}/liga/retomar")
    assert r.status_code == 200
    assert _estado(sessoes, COLETOR_LIGA) is EstadoColetorTipo.ATIVO


def test_rodar_agora(cliente, logar):
    logar(Papel.ADMIN)
    assert cliente.post(f"{LISTA}/liga/rodar-agora").json()["codigo"] in {"rodar", "liga_esfriando", "liga_parada_hoje"}
    assert cliente.post(f"{LISTA}/casador/rodar-agora").json()["codigo"] == "casador_rodar"


def test_rodar_agora_do_backup_404(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    for rota in ("backup/rodar-agora", "whatsapp/retomar", "casador/retomar", "inexistente/ligar", "liga/explodir"):
        r = cliente.post(f"{LISTA}/{rota}")
        assert r.status_code == 404 and r.json()["erro"] == "nao_encontrado", rota
    assert _acoes(sessoes) == []


def test_monitor_e_checkout_sub_chaves(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    sub = _servico(cliente, "amazon_monitor")["sub"]
    assert sub["monitor_ligado"] is True and sub["checkout_ligado"] is True and sub["checkout_parado"] is False
    assert cliente.post(f"{LISTA}/amazon_monitor/monitor/desligar").json()["codigo"] == "monitor_desligar"
    assert cliente.post(f"{LISTA}/amazon_monitor/checkout/desligar").json()["codigo"] == "checkout_desligar"
    sub = _servico(cliente, "amazon_monitor")["sub"]
    assert sub["monitor_ligado"] is False and sub["checkout_ligado"] is False
    assert cliente.post(f"{LISTA}/amazon_monitor/monitor/ligar").json()["codigo"] == "monitor_ligar"
    with sessoes() as s, s.begin():
        repo_amz.obter_config(s).checkout_sem_login_em = T0
    assert _servico(cliente, "amazon_monitor")["sub"]["checkout_parado"] is True
    assert cliente.post(f"{LISTA}/amazon_monitor/checkout/retomar").json()["codigo"] == "checkout_retomar"
    assert _servico(cliente, "amazon_monitor")["sub"]["checkout_parado"] is False
    assert _acoes(sessoes)[0][1] == {
        "servico": "amazon_monitor", "acao": "monitor_desligar", "codigo": "monitor_desligar"
    }
    for rota in ("explodir/ligar", "monitor/retomar", "checkout/explodir"):
        assert cliente.post(f"{LISTA}/amazon_monitor/{rota}").status_code == 404


def test_carrinho_conferido_e_404_sem_conferencia(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    with sessoes() as s, s.begin():
        anuncio = criar_anuncio(s, "B0CARRINH1", criar_produto(s, "p1"), StatusCasamento.CONFIRMADO)
        c = ConferenciaCheckout(
            em=T0, anuncio_id=anuncio.id, preco_anunciado=10, situacao=SituacaoCheckout.OK,
            item_removido=False, conferir_a_mao_em=T0,
        )
        s.add(c)
        s.flush()
        cid = c.id
    carrinho = _servico(cliente, "amazon_monitor")["sub"]["carrinho"]
    assert [(x["conferencia_id"], x["asin"]) for x in carrinho] == [(cid, "B0CARRINH1")]
    assert carrinho[0]["produto"] and carrinho[0]["em"]
    r = cliente.post(f"{LISTA}/carrinho/{cid}/conferido")
    assert r.status_code == 200 and r.json()["codigo"] == "carrinho_conferido"
    assert _servico(cliente, "amazon_monitor")["sub"]["carrinho"] == []
    r = cliente.post(f"{LISTA}/carrinho/{cid}/conferido")
    assert r.status_code == 404 and r.json()["erro"] == "nao_encontrado"
    assert cliente.post(f"{LISTA}/carrinho/999999/conferido").status_code == 404
    assert len(_acoes(sessoes)) == 1


def test_carrinho_conferido_com_id_gigante_e_404(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    for cid in (2**31, 0):
        r = cliente.post(f"{LISTA}/carrinho/{cid}/conferido")
        assert r.status_code == 404
        assert r.json()["erro"] == "nao_encontrado"
        assert r.json()["mensagem"] == "Esse item não está esperando conferência."
    assert _acoes(sessoes) == []


def test_desligado_mostra_parado_de_verdade(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    _pausar(sessoes, COLETOR_CASADOR, agora=T0 - timedelta(hours=1))
    x = _servico(cliente, "casador")
    assert x["estado"] == "desligado" and x["transicao"]["tipo"] == "parado"
    assert x["transicao"]["desde"]
    _pausar(sessoes, COLETOR_CASADOR, agora=T0)
    assert _servico(cliente, "casador")["transicao"]["tipo"] == "parado"
