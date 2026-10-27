import logging
import re
from datetime import timedelta

import pytest
from fakes_api import NUMEROS, SEGREDO_TESTE, T0, criar_usuario, mensagens
from sqlalchemy import select

from tcg_sniper.api import acesso
from tcg_sniper.api.permissoes import Permissao
from tcg_sniper.api.rotas_auth import MENSAGEM_PEDIDO
from tcg_sniper.api.segredos import hash_segredo
from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import TipoAviso
from tcg_sniper.db.models import CodigoAcesso, EstadoAviso, MensagemSaida, Papel, PedidoCodigo, Sessao

GRUPO = NUMEROS[Papel.GRUPO]  # +5511900000002
CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def individuais(sessoes) -> list[MensagemSaida]:
    with sessoes() as s:
        consulta = select(MensagemSaida).where(MensagemSaida.destino == "individual").order_by(MensagemSaida.id)
        return list(s.scalars(consulta))


def codigo_da_fila(sessoes) -> str:
    return re.search(r"\*(\d{6})\*", individuais(sessoes)[-1].texto).group(1)


def pedir(cliente, numero="(11) 90000-0002", **kwargs):
    return cliente.post("/api/auth/pedir-codigo", json={"numero": numero}, **kwargs)


def entrar(cliente, codigo, numero="11 90000-0002", **kwargs):
    headers = {"User-Agent": CHROME, **kwargs.pop("headers", {})}
    return cliente.post("/api/auth/entrar", json={"numero": numero, "codigo": codigo}, headers=headers, **kwargs)


@pytest.fixture
def codigos(monkeypatch):
    """Códigos previsíveis, na ordem em que são emitidos."""
    fila = ["111111", "222222", "333333", "444444"]
    monkeypatch.setattr(acesso, "gerar_codigo", lambda: fila.pop(0))
    return fila


def test_fluxo_completo_com_numero_formatado(cliente, sessoes):
    criar_usuario(sessoes, Papel.GRUPO, nome="Pessoa Grupo")
    r = pedir(cliente)
    assert r.status_code == 200 and r.json() == {"ok": True, "mensagem": MENSAGEM_PEDIDO}
    [m] = individuais(sessoes)
    assert (m.numero, m.criada_em, m.expira_em) == (GRUPO, T0, T0 + timedelta(minutes=5))
    assert m.texto.startswith("🔑 *Código de acesso*\n")
    r = entrar(cliente, codigo_da_fila(sessoes), numero="+55 11 90000 0002")
    assert r.status_code == 200
    assert {k: r.json()[k] for k in ("nome", "papel", "superadmin", "permissoes")} == {
        "nome": "Pessoa Grupo", "papel": "grupo", "superadmin": False, "permissoes": ["ver_area_negocio", "ver_oportunidades"]
    }
    cookie = r.headers["set-cookie"]
    for parte in ("sessao=", "HttpOnly", "Max-Age=2592000", "Path=/", "SameSite=strict"):
        assert parte in cookie, parte
    assert "Secure" not in cookie
    token = r.cookies["sessao"]
    eu = cliente.get("/api/auth/eu")
    assert eu.status_code == 200 and eu.json()["papel"] == "grupo"
    with sessoes() as s:
        sessao = s.scalars(select(Sessao)).one()
        assert (sessao.aparelho, sessao.expira_em) == ("Chrome · Windows", T0 + timedelta(days=30))
    assert cliente.post("/api/auth/sair").json() == {"ok": True}
    cliente.cookies.set("sessao", token)  # mesmo guardando o token, a sessão acabou
    assert cliente.get("/api/auth/eu").status_code == 401


def test_banco_guarda_so_o_hmac_do_codigo_do_token_e_do_numero(cliente, sessoes, codigos):
    criar_usuario(sessoes, Papel.GRUPO)
    pedir(cliente)
    token = entrar(cliente, "111111").cookies["sessao"]
    with sessoes() as s:
        assert s.scalars(select(CodigoAcesso.hash_codigo)).one() == hash_segredo(SEGREDO_TESTE, "111111")
        # o pedido e a tentativa de entrar (limite de entradas): os dois só com o HMAC do número
        assert set(s.scalars(select(PedidoCodigo.numero_hash))) == {hash_segredo(SEGREDO_TESTE, GRUPO)}
        assert s.scalars(select(Sessao.hash_token)).one() == hash_segredo(SEGREDO_TESTE, token)


def test_mesma_resposta_para_numero_inexistente_ou_inativo(cliente, sessoes):
    criar_usuario(sessoes, Papel.GRUPO)
    criar_usuario(sessoes, Papel.OPERADOR, ativo=False)
    respostas = [pedir(cliente, n) for n in ("11 90000-0002", "11 90000-0003", "11 90000-0009")]
    assert {(r.status_code, r.text) for r in respostas} == {(200, respostas[0].text)}
    assert [m.numero for m in individuais(sessoes)] == [GRUPO]


def test_numero_inexistente_nao_entra(cliente, codigos):
    assert entrar(cliente, "111111", numero="11 90000-0009").json()["erro"] == "codigo_invalido"


def test_cinco_codigos_errados_invalidam(cliente, sessoes, codigos):
    criar_usuario(sessoes, Papel.GRUPO)
    pedir(cliente)
    for _ in range(5):
        r = entrar(cliente, "999999")
        assert r.status_code == 401 and r.json()["erro"] == "codigo_invalido"
    assert entrar(cliente, "111111").status_code == 401


def test_codigo_vencido(cliente, sessoes, relogio, codigos):
    criar_usuario(sessoes, Papel.GRUPO)
    pedir(cliente)
    relogio.agora = T0 + timedelta(minutes=5)
    assert entrar(cliente, "111111").status_code == 401


def test_codigo_usado_nao_vale_de_novo(cliente, sessoes, codigos):
    criar_usuario(sessoes, Papel.GRUPO)
    pedir(cliente)
    assert entrar(cliente, "111111").status_code == 200
    assert entrar(cliente, "111111").status_code == 401


def test_so_o_ultimo_codigo_vale(cliente, sessoes, relogio, codigos):
    criar_usuario(sessoes, Papel.GRUPO)
    pedir(cliente)
    relogio.agora = T0 + timedelta(seconds=30)
    pedir(cliente)
    assert entrar(cliente, "111111").status_code == 401
    assert entrar(cliente, "222222").status_code == 200


def test_quarto_pedido_do_mesmo_numero_em_15_min_e_recusado(cliente, sessoes, relogio):
    criar_usuario(sessoes, Papel.GRUPO)
    for minuto in range(3):
        relogio.agora = T0 + timedelta(minutes=minuto)
        assert pedir(cliente).status_code == 200
    r = pedir(cliente, "+55 11 90000-0002")  # outro formato, mesmo número
    assert r.status_code == 429 and r.json()["erro"] == "limite"
    assert len(individuais(sessoes)) == 3
    [aviso] = mensagens(sessoes, "admin")
    assert aviso.startswith("🟡 *Segurança · limite de códigos*")
    assert "final 02" in aviso and "900000002" not in aviso
    relogio.agora = T0 + timedelta(minutes=15)  # o pedido de T0 saiu da janela
    assert pedir(cliente).status_code == 200


def test_limite_vale_tambem_para_numero_sem_usuario(cliente):
    for _ in range(3):
        assert pedir(cliente, "11 90000-0009").status_code == 200
    assert pedir(cliente, "11 90000-0009").status_code == 429


def test_sem_limite_global_numeros_diferentes_sao_aceitos(cliente, sessoes):
    """Não existe mais limite total: pedir códigos para muitos números não tranca o login de ninguém."""
    for i in range(21):
        assert pedir(cliente, f"11 90000-{i:04d}").status_code == 200
    estado = _estado_limite(sessoes, "total")
    assert estado is None or not estado.aberto


def test_cookie_secure_atras_de_https(cliente, sessoes, codigos):
    criar_usuario(sessoes, Papel.GRUPO)
    pedir(cliente)
    r = entrar(cliente, "111111", headers={"X-Forwarded-Proto": "https"})
    assert r.status_code == 200 and "Secure" in r.headers["set-cookie"]


def test_numero_codigo_e_token_nunca_no_log(cliente, sessoes, caplog, codigos):
    caplog.set_level(logging.DEBUG)
    criar_usuario(sessoes, Papel.GRUPO)
    pedir(cliente)
    entrar(cliente, "999999")
    token = entrar(cliente, "111111").cookies["sessao"]
    for _ in range(3):
        pedir(cliente)  # o último passa do limite
    pedir(cliente, "11 90000-0009")
    for proibido in ("900000002", "900000009", "111111", token):
        assert proibido not in caplog.text, proibido
    assert "+55 11 9****-**02" in caplog.text


def test_numero_ou_codigo_invalido_422_sem_ecoar(cliente):
    r = pedir(cliente, "11 9000O-0002x")
    assert r.status_code == 422 and r.json()["erro"] == "numero_invalido" and "9000O" not in r.text
    r = cliente.post("/api/auth/entrar", json={"numero": "11 90000-0002", "codigo": "12a456"})
    assert r.status_code == 422 and r.json()["erro"] == "validacao" and "12a456" not in r.text


def test_codigo_de_acesso_desligado_nao_enfileira(cliente, sessoes):
    criar_usuario(sessoes, Papel.GRUPO)
    with sessoes() as s, s.begin():
        avisos.definir_ligado(s, TipoAviso.CODIGO_ACESSO, False)
    assert pedir(cliente).status_code == 200
    assert individuais(sessoes) == []


def test_eu_devolve_permissoes_e_renova_o_cookie(cliente, logar):
    logar(Papel.OPERADOR)
    r = cliente.get("/api/auth/eu")
    assert r.json()["permissoes"] == [
        "ver_area_negocio", "ver_oportunidades", "ver_area_gestao", "revisar_casamentos", "ver_catalogo",
        "editar_catalogo", "ver_servicos", "ver_logs", "ver_mensagens", "ver_configuracoes",
    ]
    assert "Max-Age=2592000" in r.headers["set-cookie"]


def test_eu_sem_sessao_401(cliente):
    assert cliente.get("/api/auth/eu").json()["erro"] == "sem_sessao"


def test_eu_diz_quem_e_o_superadmin(cliente, logar):
    logar(Papel.ADMIN)
    assert cliente.get("/api/auth/eu").json()["superadmin"] is False
    logar(Papel.ADMIN, numero="+5511900000004", superadmin=True)
    eu = cliente.get("/api/auth/eu").json()
    assert (eu["papel"], eu["superadmin"]) == ("admin", True)
    assert len(eu["permissoes"]) == len(Permissao)  # todas


@pytest.mark.parametrize(
    ("user_agent", "esperado"),
    [
        (CHROME, "Chrome · Windows"),
        ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36",
         "Chrome · Android"),
        (("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
          "Version/18.0 Mobile/15E148 Safari/604.1"), "Safari · iPhone"),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Edg/130.0",
         "Edge · Windows"),
        (None, "navegador desconhecido · sistema desconhecido"),
    ],
)
def test_resumir_aparelho(user_agent, esperado):
    assert acesso.resumir_aparelho(user_agent) == esperado


# --- Decisões do controlador (P4, P5, cookie) ---


def avisos_de_limite(sessoes) -> list[str]:
    return [m for m in mensagens(sessoes, "admin") if m.startswith("🟡 *Segurança · limite de códigos*")]


def test_entrar_limite_de_10_tentativas_por_numero_em_15_min(cliente, sessoes, relogio, codigos):
    criar_usuario(sessoes, Papel.GRUPO)
    pedir(cliente)
    formatos = ("11 90000-0002", "+55 11 90000 0002", "(11) 90000-0002", "11900000002", "5511900000002")
    for i in range(acesso.LIMITE_ENTRADAS):
        r = entrar(cliente, "999999", numero=formatos[i % len(formatos)])  # outro formato, mesmo número
        assert r.status_code == 401, i
    r = entrar(cliente, "111111")
    assert r.status_code == 429 and r.json()["erro"] == "limite" and "set-cookie" not in r.headers
    relogio.agora = T0 + timedelta(minutes=15)  # as tentativas de T0 saíram da janela
    pedir(cliente)
    assert entrar(cliente, "222222").status_code == 200


def test_entrar_limite_vale_tambem_para_numero_sem_usuario(cliente, sessoes, codigos):
    """Mesma resposta, com ou sem cadastro: o 429 não revela quem existe."""
    criar_usuario(sessoes, Papel.GRUPO)
    pedir(cliente)
    respostas = {}
    for numero in ("11 90000-0002", "11 90000-0009"):
        for _ in range(acesso.LIMITE_ENTRADAS):
            assert entrar(cliente, "999999", numero=numero).status_code == 401
        respostas[numero] = entrar(cliente, "999999", numero=numero)
    assert {(r.status_code, r.text) for r in respostas.values()} == {(429, respostas["11 90000-0002"].text)}


def test_entrar_limite_nao_conta_para_os_pedidos_de_codigo(cliente, sessoes, codigos):
    criar_usuario(sessoes, Papel.GRUPO)
    for _ in range(acesso.LIMITE_ENTRADAS):
        entrar(cliente, "999999")
    for _ in range(acesso.LIMITE_POR_NUMERO):
        assert pedir(cliente).status_code == 200
    with sessoes() as s:
        resultados = sorted(s.scalars(select(PedidoCodigo.resultado)))
    assert resultados == ["aceito"] * 3 + ["entrada"] * 10


def test_cinco_codigos_errados_avisam_o_grupo_admin_sem_o_numero(cliente, sessoes, relogio, codigos):
    criar_usuario(sessoes, Papel.GRUPO)
    pedir(cliente)
    for _ in range(acesso.MAX_TENTATIVAS - 1):
        entrar(cliente, "999999")
    assert avisos_de_limite(sessoes) == []
    entrar(cliente, "999999")  # a 5ª invalida o código
    [aviso] = avisos_de_limite(sessoes)
    assert "5 códigos errados" in aviso and "final 02" in aviso
    assert "900000002" not in aviso and "999999" not in aviso and "111111" not in aviso
    entrar(cliente, "999999")  # código já inválido: não conta nem avisa de novo
    assert len(avisos_de_limite(sessoes)) == 1
    with sessoes() as s:
        assert s.scalars(select(CodigoAcesso.tentativas)).one() == acesso.MAX_TENTATIVAS


def test_aviso_de_codigos_errados_agrupa_com_o_de_pedidos_pelo_hash_do_numero(cliente, sessoes, codigos):
    criar_usuario(sessoes, Papel.GRUPO)
    pedir(cliente)
    for _ in range(acesso.MAX_TENTATIVAS):
        entrar(cliente, "999999")
    pedir(cliente)
    pedir(cliente)
    assert pedir(cliente).status_code == 429  # 4º pedido: mesmo problema aberto, sem mensagem nova
    assert len(avisos_de_limite(sessoes)) == 1
    with sessoes() as s:
        estado = s.scalars(select(EstadoAviso).where(EstadoAviso.tipo == TipoAviso.SEGURANCA_LIMITE.value)).one()
    assert (estado.chave, estado.ocorrencias) == (f"numero:{hash_segredo(SEGREDO_TESTE, GRUPO)[:12]}", 2)


def test_cookie_httponly_samesite_strict_path_raiz_no_eu_e_apagado_no_sair(cliente, logar):
    logar(Papel.GRUPO)
    for cabecalhos, secure in (({}, False), ({"X-Forwarded-Proto": "https"}, True)):
        cookie = cliente.get("/api/auth/eu", headers=cabecalhos).headers["set-cookie"]
        for parte in ("sessao=", "HttpOnly", "Path=/", "SameSite=strict"):
            assert parte in cookie, parte
        assert ("Secure" in cookie) is secure
    apagado = cliente.post("/api/auth/sair", headers={"X-Forwarded-Proto": "https"}).headers["set-cookie"]
    for parte in ('sessao=""', "Max-Age=0", "HttpOnly", "Path=/", "SameSite=strict", "Secure"):
        assert parte in apagado, parte


def _estado_limite(sessoes, chave):
    with sessoes() as s:
        return s.get(EstadoAviso, (TipoAviso.SEGURANCA_LIMITE.value, chave))


def test_entrada_certa_resolve_o_aviso_de_limite_do_numero(cliente, sessoes, codigos):
    criar_usuario(sessoes, Papel.GRUPO)
    for _ in range(acesso.LIMITE_POR_NUMERO):
        pedir(cliente)
    assert pedir(cliente).status_code == 429
    chave = f"numero:{hash_segredo(SEGREDO_TESTE, GRUPO)[:12]}"
    assert _estado_limite(sessoes, chave).aberto
    assert entrar(cliente, "333333").status_code == 200
    assert not _estado_limite(sessoes, chave).aberto
    resolvido = mensagens(sessoes, "admin")[-1]
    assert "resolvido" in resolvido and "900000002" not in resolvido


def test_aviso_antigo_de_limite_total_fecha_no_proximo_pedido_aceito(cliente, sessoes):
    """Um aviso de "limite total" aberto antes da mudança não fica com lembrete eterno."""
    from tcg_sniper.avisos import servico as servico_avisos
    from tcg_sniper.avisos.catalogo import Dados, TipoAviso

    with sessoes() as s, s.begin():
        servico_avisos.avisar(s, TipoAviso.SEGURANCA_LIMITE, "total", Dados(linhas=("antigo",)), T0)
    assert _estado_limite(sessoes, "total").aberto
    assert pedir(cliente, "11 90000-0099").status_code == 200
    assert not _estado_limite(sessoes, "total").aberto


def test_entrar_tambem_apaga_pedidos_antigos(cliente, sessoes, relogio):
    with sessoes() as s, s.begin():
        s.add(PedidoCodigo(em=T0 - timedelta(days=2), numero_hash="h" * 64, resultado="aceito"))
    entrar(cliente, "999999")
    with sessoes() as s:
        assert s.scalars(select(PedidoCodigo.numero_hash)).all() == [hash_segredo(SEGREDO_TESTE, GRUPO)]


def test_limite_de_entrar_tem_mensagem_propria_e_neutra(cliente, sessoes, codigos):
    for _ in range(acesso.LIMITE_ENTRADAS):
        entrar(cliente, "999999")
    r = entrar(cliente, "999999")
    assert r.status_code == 429
    assert r.json() == {"erro": "limite", "mensagem": "Muitas tentativas. Espere alguns minutos e tente de novo."}


CELULAR_COM_NOVE = "+5511987654321"
CELULAR_SEM_NOVE = "(11) 8765-4321"


def test_entra_digitando_o_celular_sem_o_nove(cliente, sessoes):
    criar_usuario(sessoes, Papel.GRUPO, numero=CELULAR_COM_NOVE)
    assert pedir(cliente, CELULAR_SEM_NOVE).status_code == 200
    [m] = individuais(sessoes)
    assert m.numero == CELULAR_COM_NOVE
    r = entrar(cliente, codigo_da_fila(sessoes), numero=CELULAR_SEM_NOVE)
    assert r.status_code == 200 and r.json()["papel"] == "grupo"


def test_com_e_sem_o_nove_dividem_os_limites(cliente, sessoes):
    criar_usuario(sessoes, Papel.GRUPO, numero=CELULAR_COM_NOVE)
    assert pedir(cliente, CELULAR_SEM_NOVE).status_code == 200
    assert pedir(cliente, "(11) 98765-4321").status_code == 200
    assert pedir(cliente, CELULAR_SEM_NOVE).status_code == 200
    assert pedir(cliente, "(11) 98765-4321").status_code == 429
    with sessoes() as s:
        assert len(set(s.scalars(select(PedidoCodigo.numero_hash)))) == 1


def test_fixo_de_8_digitos_nao_vira_celular(cliente, sessoes):
    criar_usuario(sessoes, Papel.GRUPO, numero="+5511930000001")  # o fixo com um 9 na frente existiria
    assert pedir(cliente, "(11) 3000-0001").status_code == 200
    assert individuais(sessoes) == []
    with sessoes() as s:
        assert s.scalars(select(PedidoCodigo.numero_hash)).one() == hash_segredo(SEGREDO_TESTE, "+551130000001")


def test_sem_o_nove_sem_cadastro_responde_igual(cliente, sessoes):
    criar_usuario(sessoes, Papel.GRUPO, numero=CELULAR_COM_NOVE)
    com = pedir(cliente, CELULAR_SEM_NOVE)
    sem = pedir(cliente, "(21) 8765-4321")  # a variante com o 9 não existe
    assert (com.status_code, com.json()) == (sem.status_code, sem.json())
    assert len(individuais(sessoes)) == 1
    assert entrar(cliente, "000000", numero="(21) 8765-4321").status_code == 401


def test_cadastro_exato_sem_o_nove_tem_prioridade(cliente, sessoes):
    criar_usuario(sessoes, Papel.GRUPO, nome="Com nove", numero=CELULAR_COM_NOVE)
    criar_usuario(sessoes, Papel.OPERADOR, nome="Oito digitos", numero="+551187654321")
    assert pedir(cliente, CELULAR_SEM_NOVE).status_code == 200
    [m] = individuais(sessoes)
    assert m.numero == "+551187654321"
    r = entrar(cliente, codigo_da_fila(sessoes), numero=CELULAR_SEM_NOVE)
    assert r.status_code == 200 and r.json()["nome"] == "Oito digitos"
    assert pedir(cliente, "(11) 98765-4321").status_code == 200
    assert individuais(sessoes)[-1].numero == CELULAR_COM_NOVE


def test_variante_com_o_nove_inativa_nao_recebe_codigo(cliente, sessoes):
    criar_usuario(sessoes, Papel.GRUPO, numero=CELULAR_COM_NOVE, ativo=False)
    inativo = pedir(cliente, CELULAR_SEM_NOVE)
    inexistente = pedir(cliente, "(21) 8765-4321")
    assert (inativo.status_code, inativo.json()) == (inexistente.status_code, inexistente.json())
    assert individuais(sessoes) == []
    r = entrar(cliente, "123456", numero=CELULAR_SEM_NOVE)
    assert r.status_code == 401 and r.json() == entrar(cliente, "123456", numero="(21) 8765-4321").json()
