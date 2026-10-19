from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import CodigoAcesso, MensagemSaida, Papel, PedidoCodigo, StatusMensagem, Usuario

T = datetime(2026, 10, 18, 13, 0, tzinfo=UTC)
GRUPO = "+5511900000002"


def novo(s, nome="Pessoa Grupo", numero=GRUPO, papel=Papel.GRUPO) -> Usuario:
    return repo_acesso.criar_usuario(s, nome, numero, papel, T)


def test_criar_e_achar_usuario(s):
    u = novo(s)
    assert (u.nome, u.papel, u.ativo, u.criado_em) == ("Pessoa Grupo", Papel.GRUPO, True, T)
    assert repo_acesso.usuario_por_numero(s, GRUPO).id == u.id
    assert repo_acesso.usuario_por_numero(s, "+5511900000009") is None


def test_numero_repetido_nao_cria_outro(s):
    novo(s)
    with pytest.raises(repo_acesso.NumeroJaCadastrado):
        novo(s, nome="Outra Pessoa", papel=Papel.OPERADOR)
    assert len(repo_acesso.listar_usuarios(s)) == 1


def test_banco_recusa_numero_fora_do_e164(s):
    s.add(Usuario(nome="X", numero="11900000002", papel=Papel.GRUPO, ativo=True, criado_em=T))
    with pytest.raises(IntegrityError):
        s.flush()


def test_listar_por_nome(s):
    novo(s, nome="beta", numero="+5511900000005")
    novo(s, nome="Alfa", numero="+5511900000006")
    assert [u.nome for u in repo_acesso.listar_usuarios(s)] == ["Alfa", "beta"]


def test_superadmin_unico_e_troca(s):
    assert repo_acesso.superadmin_atual(s) is None
    dono = repo_acesso.criar_superadmin(s, "Pessoa Superadmin", "+5511900000001", T)
    assert (dono.papel, dono.ativo, dono.superadmin) == (Papel.ADMIN, True, True)
    assert repo_acesso.superadmin_atual(s).id == dono.id
    with pytest.raises(repo_acesso.SuperadminJaExiste):
        repo_acesso.criar_superadmin(s, "Outra Pessoa", "+5511900000004", T)
    grupo = novo(s)
    assert novo(s, nome="Comum", numero="+5511900000005").superadmin is False
    antigo = repo_acesso.trocar_superadmin(s, grupo)
    assert antigo.id == dono.id
    assert (antigo.papel, antigo.superadmin) == (Papel.ADMIN, False)  # o antigo continua admin comum
    assert (grupo.papel, grupo.superadmin) == (Papel.ADMIN, True)
    assert repo_acesso.superadmin_atual(s).id == grupo.id


def test_banco_garante_um_superadmin_so(s):
    repo_acesso.criar_superadmin(s, "Pessoa Superadmin", "+5511900000001", T)
    s.add(Usuario(nome="X", numero="+5511900000004", papel=Papel.ADMIN, ativo=True, superadmin=True, criado_em=T))
    with pytest.raises(IntegrityError):
        s.flush()


@pytest.mark.parametrize(("papel", "ativo"), [(Papel.OPERADOR, True), (Papel.ADMIN, False)])
def test_banco_recusa_superadmin_que_nao_e_admin_ativo(s, papel, ativo):
    s.add(Usuario(nome="X", numero="+5511900000004", papel=papel, ativo=ativo, superadmin=True, criado_em=T))
    with pytest.raises(IntegrityError):
        s.flush()


def test_ultimo_codigo_e_o_mais_novo(s):
    u = novo(s)
    repo_acesso.criar_codigo(s, u.id, "h1", T, timedelta(minutes=5))
    segundo = repo_acesso.criar_codigo(s, u.id, "h2", T + timedelta(seconds=1), timedelta(minutes=5))
    atual = repo_acesso.ultimo_codigo(s, u.id)
    assert atual.id == segundo.id
    assert (atual.hash_codigo, atual.expira_em, atual.tentativas, atual.usado_em) == (
        "h2", T + timedelta(minutes=5, seconds=1), 0, None
    )
    assert repo_acesso.ultimo_codigo(s, u.id + 1000) is None


def test_sessoes_ativas_encerrar_e_contar(s):
    u = novo(s)
    a = repo_acesso.criar_sessao(s, u.id, "ha", "Chrome · Windows", T, timedelta(days=30))
    b = repo_acesso.criar_sessao(s, u.id, "hb", "Safari · iPhone", T + timedelta(hours=1), timedelta(days=30))
    vencida = repo_acesso.criar_sessao(s, u.id, "hc", "Firefox · Linux", T - timedelta(days=40), timedelta(days=30))
    agora = T + timedelta(hours=2)
    assert repo_acesso.sessao_por_hash(s, "ha").id == a.id
    assert repo_acesso.sessao_por_hash(s, "nada") is None
    assert [x.id for x in repo_acesso.sessoes_ativas(s, u.id, agora)] == [b.id, a.id]
    assert vencida.id not in [x.id for x in repo_acesso.sessoes_ativas(s, u.id, agora)]
    repo_acesso.encerrar_sessao(s, a, agora)
    assert a.encerrada_em == agora
    assert [x.id for x in repo_acesso.sessoes_ativas(s, u.id, agora)] == [b.id]
    assert repo_acesso.contar_sessoes_ativas(s, agora) == {u.id: 1}
    # encerra as que ainda não tinham sido encerradas (b e a vencida; a "a" já estava)
    assert repo_acesso.encerrar_sessoes_do_usuario(s, u.id, agora + timedelta(hours=1)) == 2
    assert repo_acesso.sessoes_ativas(s, u.id, agora + timedelta(hours=1)) == []


def test_pedidos_contam_so_aceitos_dentro_da_janela(s):
    repo_acesso.registrar_pedido(s, "n1", repo_acesso.ACEITO, T)
    repo_acesso.registrar_pedido(s, "n1", "limite_numero", T)
    repo_acesso.registrar_pedido(s, "n2", repo_acesso.ACEITO, T + timedelta(minutes=10))
    assert repo_acesso.contar_pedidos(s, T - timedelta(seconds=1)) == 2
    assert repo_acesso.contar_pedidos(s, T - timedelta(seconds=1), "n1") == 1
    assert repo_acesso.contar_pedidos(s, T) == 1  # janela aberta: o pedido de T não conta mais


def test_limpar_antigos_apaga_pedidos_e_codigos_de_mais_de_um_dia(s):
    u = novo(s)
    repo_acesso.registrar_pedido(s, "n1", repo_acesso.ACEITO, T - timedelta(days=2))
    repo_acesso.registrar_pedido(s, "n1", repo_acesso.ACEITO, T)
    repo_acesso.criar_codigo(s, u.id, "velho", T - timedelta(days=2), timedelta(minutes=5))
    repo_acesso.criar_codigo(s, u.id, "novo", T, timedelta(minutes=5))
    repo_acesso.limpar_antigos(s, T)
    assert [p.em for p in s.query(PedidoCodigo)] == [T]
    assert [c.hash_codigo for c in s.query(CodigoAcesso)] == ["novo"]


def test_grade_salva_e_upsert(s):
    assert repo_acesso.grade_salva(s) == {}
    repo_acesso.salvar_permissao(s, Papel.GRUPO, "ver_area_gestao", True)
    repo_acesso.salvar_permissao(s, Papel.GRUPO, "ver_area_gestao", False)
    repo_acesso.salvar_permissao(s, Papel.OPERADOR, "gerir_usuarios", True)
    assert repo_acesso.grade_salva(s) == {
        (Papel.GRUPO, "ver_area_gestao"): False,
        (Papel.OPERADOR, "gerir_usuarios"): True,
    }


def _mensagem(destino, numero):
    return MensagemSaida(
        destino=destino, texto="x", status=StatusMensagem.PENDENTE, tentativas=0, proxima_tentativa_em=T,
        ignorar_validade=False, criada_em=T, atualizado_em=T, numero=numero,
    )


def test_mensagem_individual_exige_numero(s):
    s.add(_mensagem("individual", None))
    with pytest.raises(IntegrityError):
        s.flush()


def test_mensagem_de_grupo_nao_leva_numero(s):
    s.add(_mensagem("admin", GRUPO))
    with pytest.raises(IntegrityError):
        s.flush()


def test_mensagem_individual_com_numero_e_aceita(s):
    s.add(_mensagem("individual", GRUPO))
    s.flush()


def test_nome_vazio_nao_vira_numero_repetido(s):
    with pytest.raises(IntegrityError):
        novo(s, nome="")


def test_numero_invalido_nao_vira_numero_repetido(s):
    with pytest.raises(IntegrityError):
        novo(s, numero="11900000002")


def test_criar_superadmin_com_numero_repetido(s):
    novo(s)
    with pytest.raises(repo_acesso.NumeroJaCadastrado):
        repo_acesso.criar_superadmin(s, "Dono", GRUPO, T)
    assert repo_acesso.superadmin_atual(s) is None
    assert len(repo_acesso.listar_usuarios(s)) == 1


def test_criar_superadmin_corrida_no_indice_unico(s, monkeypatch):
    """Outro processo criou o superadmin entre a checagem e o insert: o índice único vira SuperadminJaExiste."""
    repo_acesso.criar_superadmin(s, "Dono", "+5511900000001", T)
    monkeypatch.setattr(repo_acesso, "superadmin_atual", lambda _s: None)
    with pytest.raises(repo_acesso.SuperadminJaExiste):
        repo_acesso.criar_superadmin(s, "Outro", "+5511900000004", T)
    assert [u.nome for u in repo_acesso.listar_usuarios(s)] == ["Dono"]


def test_trocar_superadmin_para_quem_ja_e_recusa(s):
    dono = repo_acesso.criar_superadmin(s, "Dono", "+5511900000001", T)
    with pytest.raises(repo_acesso.TrocaInvalida):
        repo_acesso.trocar_superadmin(s, dono)
    assert repo_acesso.superadmin_atual(s).id == dono.id


def test_trocar_superadmin_para_inativo_recusa_sem_mexer_no_antigo(s):
    dono = repo_acesso.criar_superadmin(s, "Dono", "+5511900000001", T)
    inativo = novo(s)
    inativo.ativo = False
    s.flush()
    with pytest.raises(repo_acesso.TrocaInvalida):
        repo_acesso.trocar_superadmin(s, inativo)
    assert repo_acesso.superadmin_atual(s).id == dono.id
    assert inativo.papel == Papel.GRUPO
