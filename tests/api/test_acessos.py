from fakes_api import logar as logar_cliente
from fastapi.testclient import TestClient

from tcg_sniper.api.permissoes import GradePermissoes, Permissao, calcular_grade
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Papel

GESTAO_PARA_GRUPO = {"mudancas": [{"papel": "grupo", "permissao": "ver_area_gestao", "permitido": True}]}


def linhas(resposta):
    return {linha["permissao"]: linha for linha in resposta.json()["permissoes"]}


def test_padroes_e_linhas_salvas():
    padrao = calcular_grade({})
    assert padrao[Papel.GRUPO] == {Permissao.VER_AREA_NEGOCIO, Permissao.VER_OPORTUNIDADES}
    assert padrao[Papel.OPERADOR] == {
        Permissao.VER_AREA_NEGOCIO, Permissao.VER_OPORTUNIDADES, Permissao.VER_AREA_GESTAO,
    }
    assert padrao[Papel.ADMIN] == set(Permissao)
    salvas = {
        (Papel.GRUPO, "ver_area_negocio"): False,
        (Papel.ADMIN, "gerir_acessos"): False,  # ignorada: admin tem tudo
        (Papel.OPERADOR, "permissao_de_outra_fase"): True,  # ignorada: não existe no código
        (Papel.OPERADOR, "gerir_usuarios"): True,
    }
    grade = calcular_grade(salvas)
    assert grade[Papel.GRUPO] == {Permissao.VER_OPORTUNIDADES}
    assert grade[Papel.ADMIN] == set(Permissao)
    assert grade[Papel.OPERADOR] == {
        Permissao.VER_AREA_NEGOCIO, Permissao.VER_OPORTUNIDADES, Permissao.VER_AREA_GESTAO,
        Permissao.GERIR_USUARIOS,
    }


def test_grade_em_cache_ate_vencer_ou_invalidar(sessoes):
    agora = [100.0]
    grade = GradePermissoes(sessoes, ttl_s=5.0, monotonico=lambda: agora[0])
    assert Permissao.VER_AREA_GESTAO not in grade.efetivas(Papel.GRUPO)
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.GRUPO, "ver_area_gestao", True)
    assert Permissao.VER_AREA_GESTAO not in grade.efetivas(Papel.GRUPO)  # ainda o cache
    agora[0] += 5.0
    assert Permissao.VER_AREA_GESTAO in grade.efetivas(Papel.GRUPO)
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.GRUPO, "ver_area_gestao", False)
    grade.invalidar()
    assert Permissao.VER_AREA_GESTAO not in grade.efetivas(Papel.GRUPO)


def test_grade_padrao_com_rotulos(cliente, logar):
    logar(Papel.ADMIN)
    r = cliente.get("/api/acessos")
    assert r.status_code == 200
    assert r.json()["papeis"] == [
        {"papel": "grupo", "rotulo": "Grupo", "editavel": True},
        {"papel": "operador", "rotulo": "Operador", "editavel": True},
        {"papel": "admin", "rotulo": "Admin", "editavel": False},
    ]
    por_permissao = linhas(r)
    assert list(por_permissao) == [p.value for p in Permissao]
    assert por_permissao["ver_area_gestao"]["rotulo"] == "Entrar na área de gestão"
    assert por_permissao["ver_area_gestao"]["descricao"]
    assert por_permissao["ver_area_gestao"]["valores"] == {"grupo": False, "operador": True, "admin": True}
    assert por_permissao["gerir_acessos"]["valores"] == {"grupo": False, "operador": False, "admin": True}


def test_grupo_e_operador_nao_veem_a_grade_por_padrao(app_api, sessoes):
    for papel in (Papel.GRUPO, Papel.OPERADOR):
        cliente = TestClient(app_api)
        logar_cliente(sessoes, cliente, papel)
        r = cliente.get("/api/acessos")
        assert r.status_code == 403 and r.json()["erro"] == "sem_permissao"


def test_mudanca_vale_na_proxima_requisicao(app_api, sessoes):
    admin, operador = TestClient(app_api), TestClient(app_api)
    logar_cliente(sessoes, admin, Papel.ADMIN)
    logar_cliente(sessoes, operador, Papel.OPERADOR)
    assert operador.get("/api/acessos").status_code == 403
    liberar = {"mudancas": [{"papel": "operador", "permissao": "gerir_acessos", "permitido": True}]}
    r = admin.put("/api/acessos", json=liberar)
    assert r.status_code == 200 and linhas(r)["gerir_acessos"]["valores"]["operador"] is True
    assert operador.get("/api/acessos").status_code == 200
    tirar = {"mudancas": [{"papel": "operador", "permissao": "gerir_acessos", "permitido": False}]}
    assert admin.put("/api/acessos", json=tirar).status_code == 200
    assert operador.get("/api/acessos").status_code == 403


def test_admin_e_travado_e_linhas_dele_no_banco_sao_ignoradas(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    r = cliente.put("/api/acessos", json={"mudancas": [{"papel": "admin", "permissao": "gerir_acessos", "permitido": False}]})
    assert r.status_code == 422 and r.json()["erro"] == "papel_travado"
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.ADMIN, "gerir_acessos", False)
    cliente.app.state.grade.invalidar()
    assert cliente.get("/api/acessos").status_code == 200


def test_permissao_desconhecida_ou_lista_vazia_422(cliente, logar):
    logar(Papel.ADMIN)
    for corpo in (
        {"mudancas": [{"papel": "grupo", "permissao": "voar", "permitido": True}]},
        {"mudancas": []},
        {"mudancas": [{"papel": "grupo", "permissao": "ver_area_gestao", "permitido": True, "extra": 1}]},
    ):
        r = cliente.put("/api/acessos", json=corpo)
        assert r.status_code == 422 and r.json()["erro"] == "validacao", corpo
        assert "voar" not in r.text


def test_mudanca_igual_ao_atual_nao_grava(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    assert cliente.put("/api/acessos", json=GESTAO_PARA_GRUPO).status_code == 200
    assert cliente.put("/api/acessos", json=GESTAO_PARA_GRUPO).status_code == 200
    with sessoes() as s:
        assert repo_acesso.grade_salva(s) == {(Papel.GRUPO, "ver_area_gestao"): True}
