import hashlib
import hmac
from datetime import timedelta

import fakes_api
import pytest
from fakes_api import SEGREDO_TESTE, T0
from fastapi import Response
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from tcg_sniper.api.app import criar_app
from tcg_sniper.api.segredos import SegredoAusente, exigir_segredo, hash_segredo
from tcg_sniper.db.models import Papel, Sessao, Usuario

PUBLICAS = {
    ("GET", "/api/saude"),
    ("POST", "/api/auth/pedir-codigo"),
    ("POST", "/api/auth/entrar"),
    ("POST", "/api/auth/sair"),
    ("GET", "/api/auth/eu"),  # exige sessão, mas nenhuma permissão
}


def test_saude_sem_login(cliente):
    r = cliente.get("/api/saude")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_segredo_do_config_e_o_dos_fakes(config, app_api):
    assert config.segredo_api.get_secret_value() == SEGREDO_TESTE == app_api.state.segredo


def test_hash_e_hmac_com_o_segredo():
    esperado = hmac.new(SEGREDO_TESTE.encode(), b"123456", hashlib.sha256).hexdigest()
    assert hash_segredo(SEGREDO_TESTE, "123456") == esperado
    assert hash_segredo(SEGREDO_TESTE, "123456") != hashlib.sha256(b"123456").hexdigest()  # nunca SHA-256 puro
    assert hash_segredo("outro-segredo-falso-0123456789abcdefghij", "123456") != esperado


@pytest.mark.parametrize("valor", [None, "", "   ", "trocar-este-segredo", "curto-demais"])
def test_app_nao_sobe_sem_segredo(sessoes, config, valor):
    sem = config.model_copy(update={"segredo_api": None if valor is None else SecretStr(valor)})
    with pytest.raises(SegredoAusente, match="SEGREDO_API") as erro:
        criar_app(sessoes, sem)
    assert "token_urlsafe" in str(erro.value)  # diz como gerar
    with pytest.raises(SegredoAusente):
        exigir_segredo(sem)


def test_saude_com_banco_fora_responde_503(config):
    url = "postgresql+psycopg://tcg:tcg@127.0.0.1:1/tcg_test_fora"
    fora = sessionmaker(bind=create_engine(url, connect_args={"connect_timeout": 2}))
    r = TestClient(criar_app(fora, config)).get("/api/saude")
    assert r.status_code == 503 and r.json()["erro"] == "banco_fora"


def test_rota_inexistente_404_em_json(cliente):
    r = cliente.get("/api/nada")
    assert r.status_code == 404 and r.json() == {"erro": "nao_encontrado", "mensagem": "Não encontrado."}


def test_sem_cookie_401_em_json(cliente):
    r = cliente.get("/api/acessos")
    assert r.status_code == 401 and r.json() == {"erro": "sem_sessao", "mensagem": "Entre de novo para continuar."}


def test_token_desconhecido_ou_gigante_401(cliente):
    for token in ("nao-existe", "x" * 500):
        cliente.cookies.set("sessao", token)
        assert cliente.get("/api/acessos").status_code == 401


def test_sessao_vencida_401(cliente, logar, relogio):
    logar(Papel.ADMIN)
    relogio.agora = T0 + timedelta(days=30)
    assert cliente.get("/api/acessos").status_code == 401


def test_sessao_encerrada_401(cliente, logar, sessoes):
    usuario_id = logar(Papel.ADMIN)
    with sessoes() as s, s.begin():
        s.execute(update(Sessao).where(Sessao.usuario_id == usuario_id).values(encerrada_em=T0))
    assert cliente.get("/api/acessos").status_code == 401


def test_usuario_desativado_401_mesmo_com_sessao_aberta(cliente, logar, sessoes):
    usuario_id = logar(Papel.ADMIN)
    with sessoes() as s, s.begin():
        s.get(Usuario, usuario_id).ativo = False
    assert cliente.get("/api/acessos").status_code == 401


def test_uso_renova_a_validade_e_o_ultimo_uso(cliente, logar, relogio, sessoes):
    usuario_id = logar(Papel.ADMIN)
    relogio.agora = T0 + timedelta(days=20)
    assert cliente.get("/api/acessos").status_code == 200
    with sessoes() as s:
        sessao = s.scalars(select(Sessao).where(Sessao.usuario_id == usuario_id)).one()
        assert (sessao.ultimo_uso_em, sessao.expira_em) == (relogio.agora, relogio.agora + timedelta(days=30))
    relogio.agora = T0 + timedelta(days=45)  # 25 dias depois do último uso: ainda vale
    assert cliente.get("/api/acessos").status_code == 200


def test_documentacao_exige_permissao(cliente, logar):
    logar(Papel.GRUPO)
    assert cliente.get("/api/docs").status_code == 403
    assert cliente.get("/api/openapi.json").status_code == 403
    logar(Papel.ADMIN)
    docs = cliente.get("/api/docs")
    assert docs.status_code == 200 and "swagger" in docs.text.lower()
    assert "/api/acessos" in cliente.get("/api/openapi.json").json()["paths"]
    assert cliente.get("/docs").status_code == 404 and cliente.get("/openapi.json").status_code == 404


def test_logar_troca_o_cookie_gravado_pela_api(sessoes, config, relogio):
    """Um cookie que a API gravou (Set-Cookie, com domínio, como o /api/auth/eu faz) não pode ganhar do novo
    `logar`: sem limpar, o cliente teria dois `sessao` e mandaria o antigo."""
    app = criar_app(sessoes, config, relogio=relogio)

    @app.get("/api/teste-regrava-cookie")
    def regrava(response: Response) -> dict[str, bool]:
        response.set_cookie("sessao", "token-antigo-gravado-pela-api", httponly=True, samesite="strict", path="/")
        return {"ok": True}

    cliente = TestClient(app)
    fakes_api.logar(sessoes, cliente, Papel.GRUPO)
    cliente.get("/api/teste-regrava-cookie")
    assert cliente.get("/api/acessos").status_code == 401  # vale o cookie que a API gravou (token desconhecido)
    admin_id = fakes_api.logar(sessoes, cliente, Papel.ADMIN)
    assert cliente.get("/api/acessos").status_code == 200  # o novo ganhou: logado como admin
    assert [c.value for c in cliente.cookies.jar if c.name == "sessao"] == [f"token-admin-{admin_id}"]


def test_toda_rota_da_api_declara_permissao_ou_e_publica(app_api):
    def chamadas(dependente):
        for d in dependente.dependencies:
            yield d.call
            yield from chamadas(d)

    sem_permissao = []
    for rota in app_api.routes:
        if not isinstance(rota, APIRoute):
            continue
        assert rota.path.startswith("/api/"), rota.path
        for metodo in rota.methods:
            if (metodo, rota.path) in PUBLICAS:
                continue
            if not any(getattr(c, "permissao", None) for c in chamadas(rota.dependant)):
                sem_permissao.append(f"{metodo} {rota.path}")
    assert sem_permissao == []
