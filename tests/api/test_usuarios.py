import pytest
from fakes_api import T0, criar_sessao, criar_usuario, mensagens
from fastapi.testclient import TestClient
from sqlalchemy import select

from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Papel, Sessao, Usuario


def test_listar_exige_gerir_usuarios(cliente, logar):
    logar(Papel.GRUPO)
    r = cliente.get("/api/usuarios")
    assert r.status_code == 403 and r.json()["erro"] == "sem_permissao"


def test_operador_por_padrao_nao_gere_usuarios(cliente, logar):
    logar(Papel.OPERADOR)
    assert cliente.get("/api/usuarios").status_code == 403


def test_admin_lista_com_numero_mascarado(cliente, logar, sessoes):
    logar(Papel.ADMIN, superadmin=True)
    criar_usuario(sessoes, Papel.GRUPO)
    r = cliente.get("/api/usuarios")
    assert r.status_code == 200 and "900000002" not in r.text and "900000001" not in r.text
    por_papel = {u["papel"]: u for u in r.json()["usuarios"]}
    assert por_papel["grupo"]["numero_mascarado"] == "+55 11 9****-**02"
    assert (por_papel["grupo"]["ativo"], por_papel["grupo"]["sessoes_ativas"]) == (True, 0)
    assert (por_papel["grupo"]["superadmin"], por_papel["admin"]["superadmin"]) == (False, True)
    assert por_papel["admin"]["sessoes_ativas"] == 1


def test_criar_usuario_avisa_sem_numero(cliente, logar, sessoes):
    logar(Papel.ADMIN, nome="Pessoa Admin")
    r = cliente.post("/api/usuarios", json={"nome": " Pessoa Nova ", "numero": "(11) 90000-0005", "papel": "operador"})
    assert r.status_code == 201
    assert (r.json()["nome"], r.json()["numero_mascarado"], r.json()["papel"]) == (
        "Pessoa Nova", "+55 11 9****-**05", "operador"
    )
    with sessoes() as s:
        assert repo_acesso.usuario_por_numero(s, "+5511900000005").papel is Papel.OPERADOR
    [aviso] = mensagens(sessoes, "admin")
    assert aviso.startswith("🟡 *Segurança · acesso alterado · usuário criado*")
    assert "• Usuário: Pessoa Nova" in aviso and "• Papel: Operador" in aviso and "• Por: Pessoa Admin" in aviso
    assert "900000005" not in aviso


def test_numero_duplicado_em_outro_formato_409(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    criar_usuario(sessoes, Papel.GRUPO)  # +5511900000002
    r = cliente.post("/api/usuarios", json={"nome": "Outra", "numero": "+55 11 90000 0002", "papel": "grupo"})
    assert r.status_code == 409 and r.json()["erro"] == "numero_ja_cadastrado"


def test_numero_ou_nome_invalido_422(cliente, logar):
    logar(Papel.ADMIN)
    r = cliente.post("/api/usuarios", json={"nome": "X", "numero": "123", "papel": "grupo"})
    assert r.status_code == 422 and r.json()["erro"] == "numero_invalido"
    r = cliente.post("/api/usuarios", json={"nome": "   ", "numero": "11 90000-0007", "papel": "grupo"})
    assert r.status_code == 422 and r.json()["erro"] == "validacao"


def _recusado(resposta, erro):
    return resposta.status_code == 403 and resposta.json()["erro"] == erro


@pytest.mark.parametrize("papel", [Papel.ADMIN, Papel.OPERADOR])
def test_quem_nao_e_superadmin_nao_cria_nem_mexe_em_admin(cliente, logar, sessoes, papel):
    """Admin comum e operador que ganhou `gerir_usuarios` na grade: só operador e grupo."""
    logar(papel, numero="+5511900000006")
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.OPERADOR, "gerir_usuarios", True)
    admin_id = criar_usuario(sessoes, Papel.ADMIN, nome="Outro Admin", numero="+5511900000004")
    grupo_id = criar_usuario(sessoes, Papel.GRUPO)
    novo_admin = {"nome": "Intrusa", "numero": "11 90000-0008", "papel": "admin"}
    assert _recusado(cliente.post("/api/usuarios", json=novo_admin), "so_superadmin")
    assert _recusado(cliente.patch(f"/api/usuarios/{grupo_id}", json={"papel": "admin"}), "so_superadmin")
    for mudanca in ({"nome": "Outro nome"}, {"papel": "operador"}, {"ativo": False}):
        assert _recusado(cliente.patch(f"/api/usuarios/{admin_id}", json=mudanca), "so_superadmin")
    sessao_admin = criar_sessao(sessoes, admin_id, "token-do-admin")
    assert _recusado(cliente.post(f"/api/sessoes/{sessao_admin}/encerrar"), "so_superadmin")
    assert cliente.patch(f"/api/usuarios/{grupo_id}", json={"papel": "operador"}).status_code == 200
    assert cliente.patch(f"/api/usuarios/{grupo_id}", json={"ativo": False}).status_code == 200
    with sessoes() as s:
        assert s.get(Usuario, admin_id).papel is Papel.ADMIN and s.get(Usuario, admin_id).ativo


def test_superadmin_gere_admins(cliente, logar, sessoes):
    logar(Papel.ADMIN, nome="Pessoa Superadmin", superadmin=True)
    r = cliente.post("/api/usuarios", json={"nome": "Admin Novo", "numero": "11 90000-0004", "papel": "admin"})
    assert r.status_code == 201 and (r.json()["papel"], r.json()["superadmin"]) == ("admin", False)
    admin_id = r.json()["id"]
    sessao_admin = criar_sessao(sessoes, admin_id, "token-do-admin")
    assert cliente.post(f"/api/sessoes/{sessao_admin}/encerrar").json() == {"ok": True}
    assert cliente.patch(f"/api/usuarios/{admin_id}", json={"nome": "Admin Renomeado"}).status_code == 200
    assert cliente.patch(f"/api/usuarios/{admin_id}", json={"papel": "operador"}).json()["papel"] == "operador"
    assert cliente.patch(f"/api/usuarios/{admin_id}", json={"papel": "admin"}).json()["papel"] == "admin"
    assert cliente.patch(f"/api/usuarios/{admin_id}", json={"ativo": False}).json()["ativo"] is False


def test_superadmin_nunca_rebaixado_desativado_nem_encerrado(cliente, logar, sessoes):
    """Nem por um admin comum nem por ele mesmo; só ele encerra as próprias sessões."""
    super_id = logar(Papel.ADMIN, nome="Pessoa Superadmin", superadmin=True, token="token-super")
    sessao_super = criar_sessao(sessoes, super_id, "token-super-celular")
    logar(Papel.ADMIN, nome="Admin Comum", numero="+5511900000004")
    for mudanca in ({"ativo": False}, {"papel": "operador"}, {"papel": "grupo", "ativo": False}):
        assert _recusado(cliente.patch(f"/api/usuarios/{super_id}", json=mudanca), "superadmin_protegido")
    assert _recusado(cliente.patch(f"/api/usuarios/{super_id}", json={"nome": "X"}), "so_superadmin")
    assert _recusado(cliente.post(f"/api/sessoes/{sessao_super}/encerrar"), "superadmin_protegido")
    cliente.cookies.set("sessao", "token-super")  # agora o próprio superadmin
    for mudanca in ({"ativo": False}, {"papel": "operador"}):
        assert _recusado(cliente.patch(f"/api/usuarios/{super_id}", json=mudanca), "superadmin_protegido")
    r = cliente.patch(f"/api/usuarios/{super_id}", json={"nome": "Dono", "papel": "admin", "ativo": True})
    assert r.status_code == 200 and (r.json()["nome"], r.json()["superadmin"]) == ("Dono", True)
    assert cliente.post(f"/api/sessoes/{sessao_super}/encerrar").json() == {"ok": True}
    with sessoes() as s:
        dono = s.get(Usuario, super_id)
        assert (dono.papel, dono.ativo, dono.superadmin) == (Papel.ADMIN, True, True)


def test_qualquer_um_encerra_as_proprias_sessoes(cliente, logar, sessoes):
    admin_id = logar(Papel.ADMIN)  # admin comum
    outra = criar_sessao(sessoes, admin_id, "token-do-celular")
    assert cliente.post(f"/api/sessoes/{outra}/encerrar").json() == {"ok": True}


def test_papel_alterado_avisa(cliente, logar, sessoes):
    logar(Papel.ADMIN, nome="Pessoa Admin")
    grupo_id = criar_usuario(sessoes, Papel.GRUPO, nome="Pessoa Grupo")
    r = cliente.patch(f"/api/usuarios/{grupo_id}", json={"papel": "operador"})
    assert r.status_code == 200 and r.json()["papel"] == "operador"
    [aviso] = mensagens(sessoes, "admin")
    assert "papel alterado" in aviso and "• Papel: Grupo → Operador" in aviso


def test_mudar_so_o_nome_nao_avisa(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    grupo_id = criar_usuario(sessoes, Papel.GRUPO)
    r = cliente.patch(f"/api/usuarios/{grupo_id}", json={"nome": "Nome Novo", "papel": "grupo", "ativo": True})
    assert r.status_code == 200 and r.json()["nome"] == "Nome Novo"
    assert mensagens(sessoes, "admin") == []


def test_desativar_encerra_as_sessoes_na_hora_e_reativar_avisa(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    grupo_id = criar_usuario(sessoes, Papel.GRUPO)
    criar_sessao(sessoes, grupo_id, "t1")
    criar_sessao(sessoes, grupo_id, "t2")
    r = cliente.patch(f"/api/usuarios/{grupo_id}", json={"ativo": False})
    assert r.status_code == 200 and (r.json()["ativo"], r.json()["sessoes_ativas"]) == (False, 0)
    with sessoes() as s:
        assert [x.encerrada_em for x in s.scalars(select(Sessao).where(Sessao.usuario_id == grupo_id))] == [T0, T0]
    assert cliente.patch(f"/api/usuarios/{grupo_id}", json={"ativo": True}).json()["ativo"] is True
    avisos = mensagens(sessoes, "admin")
    assert "usuário desativado" in avisos[0] and "usuário reativado" in avisos[1]


def test_patch_vazio_ou_usuario_inexistente(cliente, logar):
    admin_id = logar(Papel.ADMIN)
    assert cliente.patch(f"/api/usuarios/{admin_id}", json={}).json()["erro"] == "validacao"
    for usuario_id in (999_999, 2**31):
        r = cliente.patch(f"/api/usuarios/{usuario_id}", json={"nome": "X"})
        assert r.status_code == 404 and r.json()["erro"] == "nao_encontrado"
        assert cliente.get(f"/api/usuarios/{usuario_id}/sessoes").status_code == 404
    assert cliente.post("/api/sessoes/999999/encerrar").status_code == 404


def test_sessoes_lista_e_encerra(cliente, logar, sessoes):
    admin_id = logar(Papel.ADMIN)
    grupo_id = criar_usuario(sessoes, Papel.GRUPO)
    sessao_id = criar_sessao(sessoes, grupo_id, "t-grupo")
    r = cliente.get(f"/api/usuarios/{grupo_id}/sessoes")
    [sessao] = r.json()["sessoes"]
    assert (sessao["id"], sessao["aparelho"], sessao["atual"]) == (sessao_id, "Chrome · Windows", False)
    assert [x["atual"] for x in cliente.get(f"/api/usuarios/{admin_id}/sessoes").json()["sessoes"]] == [True]
    assert cliente.post(f"/api/sessoes/{sessao_id}/encerrar").json() == {"ok": True}
    assert cliente.post(f"/api/sessoes/{sessao_id}/encerrar").json() == {"ok": True}
    assert cliente.get(f"/api/usuarios/{grupo_id}/sessoes").json()["sessoes"] == []


def test_permissao_alterada_avisa_e_valor_igual_nao(cliente, logar, sessoes):
    logar(Papel.ADMIN, nome="Pessoa Admin")
    corpo = {"mudancas": [{"papel": "grupo", "permissao": "ver_area_gestao", "permitido": True}]}
    assert cliente.put("/api/acessos", json=corpo).status_code == 200
    assert cliente.put("/api/acessos", json=corpo).status_code == 200  # igual ao atual: não avisa de novo
    [aviso] = mensagens(sessoes, "admin")
    assert aviso.startswith("🟡 *Segurança · acesso alterado · permissão alterada*")
    for linha in ("• Papel: Grupo", "• Permissão: Entrar na área de gestão", "• Agora: permitido", "• Por: Pessoa Admin"):
        assert linha in aviso, linha


@pytest.mark.parametrize("papel", [Papel.ADMIN, Papel.OPERADOR])
def test_quem_nao_e_superadmin_nao_muda_o_proprio_papel_nem_se_desativa(cliente, logar, sessoes, papel):
    """Quem ganhou `gerir_usuarios` não se promove nem se desativa; o próprio nome e as próprias sessões, pode."""
    eu = logar(papel, nome="Pessoa Gestora", numero="+5511900000006")
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.OPERADOR, "gerir_usuarios", True)
    outros = [p for p in Papel if p is not papel]
    for mudanca in ({"papel": outros[0].value}, {"papel": outros[1].value}, {"ativo": False}):
        assert _recusado(cliente.patch(f"/api/usuarios/{eu}", json=mudanca), "proprio_papel"), mudanca
    r = cliente.patch(f"/api/usuarios/{eu}", json={"nome": "Nome Novo", "papel": papel.value, "ativo": True})
    assert r.status_code == 200 and r.json()["nome"] == "Nome Novo"
    outra = criar_sessao(sessoes, eu, "token-do-celular")
    assert cliente.post(f"/api/sessoes/{outra}/encerrar").json() == {"ok": True}
    with sessoes() as s:
        assert (s.get(Usuario, eu).papel, s.get(Usuario, eu).ativo) == (papel, True)
    assert mensagens(sessoes, "admin") == []


def test_avisos_de_seguranca_nunca_levam_o_numero(cliente, logar, sessoes):
    logar(Papel.ADMIN, nome="Pessoa Superadmin", superadmin=True)
    r = cliente.post("/api/usuarios", json={"nome": "Pessoa Nova", "numero": "11 90000-0009", "papel": "grupo"})
    novo = r.json()["id"]
    cliente.patch(f"/api/usuarios/{novo}", json={"papel": "operador"})
    cliente.patch(f"/api/usuarios/{novo}", json={"ativo": False})
    cliente.patch(f"/api/usuarios/{novo}", json={"ativo": True})
    avisos = mensagens(sessoes, "admin")
    assert len(avisos) == 4
    for aviso in avisos:
        assert "900000009" not in aviso and "90000-0009" not in aviso and "0009" not in aviso


def test_desativar_derruba_a_sessao_em_uso(cliente, logar, sessoes):
    """Desativado, o cookie dele para de valer na hora (401)."""
    logar(Papel.ADMIN, superadmin=True)
    grupo_id = criar_usuario(sessoes, Papel.GRUPO)
    criar_sessao(sessoes, grupo_id, "token-grupo")
    outro = TestClient(cliente.app)
    outro.cookies.set("sessao", "token-grupo")
    assert outro.get("/api/usuarios").status_code == 403  # logado, mas sem permissão
    assert cliente.patch(f"/api/usuarios/{grupo_id}", json={"ativo": False}).status_code == 200
    assert outro.get("/api/usuarios").status_code == 401


@pytest.mark.parametrize("papel", [Papel.ADMIN, Papel.OPERADOR])
def test_so_o_superadmin_ve_sessoes_de_admins(cliente, logar, sessoes, papel):
    """Quem não é o superadmin (com `gerir_usuarios`) não lista sessões de admins nem do superadmin; as próprias sim."""
    super_id = criar_usuario(sessoes, Papel.ADMIN, nome="Pessoa Superadmin", superadmin=True)
    admin_id = criar_usuario(sessoes, Papel.ADMIN, nome="Outro Admin", numero="+5511900000004")
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.OPERADOR, "gerir_usuarios", True)
    eu_id = logar(papel, numero="+5511900000006")
    for alvo in (super_id, admin_id):
        assert _recusado(cliente.get(f"/api/usuarios/{alvo}/sessoes"), "so_superadmin")
    assert cliente.get(f"/api/usuarios/{eu_id}/sessoes").status_code == 200
    cliente.cookies.clear()
    criar_sessao(sessoes, super_id, "token-super")
    cliente.cookies.set("sessao", "token-super")
    assert cliente.get(f"/api/usuarios/{admin_id}/sessoes").status_code == 200
