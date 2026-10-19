import re
import signal

import pytest
from sqlalchemy import select

from tcg_sniper import cli


@pytest.fixture(autouse=True)
def batidas(monkeypatch):
    """Nenhum teste do CLI sobe a thread de verdade; guarda quais serviços iniciaram a batida."""
    from tcg_sniper.avisos import vigia

    iniciadas = []
    monkeypatch.setattr(vigia.Batimento, "iniciar", lambda self: iniciadas.append(self._servico))
    return iniciadas


def test_subcomando_obrigatorio():
    with pytest.raises(SystemExit):
        cli.main([])


def test_migrate_chama_migrar(monkeypatch):
    chamadas = []
    monkeypatch.setattr(cli, "migrar", chamadas.append)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x@y/z")
    cli.main(["migrate"])
    assert chamadas == ["postgresql+psycopg://x@y/z"]


def test_sigterm_vira_systemexit():
    anterior = signal.getsignal(signal.SIGTERM)
    try:
        cli.instalar_sigterm()
        manipulador = signal.getsignal(signal.SIGTERM)
        with pytest.raises(SystemExit):
            manipulador(signal.SIGTERM, None)
    finally:
        signal.signal(signal.SIGTERM, anterior)


def test_coletor_liga_instala_sigterm_antes_de_rodar(monkeypatch, batidas):
    from tcg_sniper.coletor_liga import agendador

    anterior = signal.getsignal(signal.SIGTERM)
    vistos = []

    class AgendadorFalso:
        def __init__(self, *args):
            pass

        def rodar(self):
            vistos.append(signal.getsignal(signal.SIGTERM))

    monkeypatch.setattr(agendador, "Agendador", AgendadorFalso)
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    try:
        cli.main(["coletor-liga"])
        assert vistos and vistos[0] not in (anterior, signal.SIG_DFL, signal.SIG_IGN)
        assert batidas == ["liga"]
    finally:
        signal.signal(signal.SIGTERM, anterior)


def test_coletor_amazon_instala_sigterm_e_usa_o_perfil_da_amazon(monkeypatch, tmp_path, batidas):
    from tcg_sniper.coletor_amazon import varredura

    anterior = signal.getsignal(signal.SIGTERM)
    vistos = []

    class VarreduraFalsa:
        def __init__(self, engine, sessoes, fabrica, avisador, config):
            vistos.append(fabrica()._dir_perfil)

        def rodar(self):
            vistos.append(signal.getsignal(signal.SIGTERM))

    monkeypatch.setattr(varredura, "VarreduraAmazon", VarreduraFalsa)
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    monkeypatch.setenv("DIR_DADOS", str(tmp_path))
    try:
        cli.main(["coletor-amazon"])
        assert vistos[0] == tmp_path / "perfil-amazon"
        assert vistos[1] not in (anterior, signal.SIG_DFL, signal.SIG_IGN)
        assert batidas == ["amazon"]
    finally:
        signal.signal(signal.SIGTERM, anterior)


def test_notificador_instala_sigterm_e_roda_o_servico(monkeypatch):
    from tcg_sniper.notificador import servico

    anterior = signal.getsignal(signal.SIGTERM)
    vistos = []

    class ServicoFalso:
        def __init__(self, *args, **kwargs):
            pass

        def parar(self):
            paradas.append(True)

        def rodar(self):
            vistos.append(signal.getsignal(signal.SIGTERM))
            vistos[-1](signal.SIGTERM, None)

    paradas = []
    monkeypatch.setattr(servico, "ServicoNotificador", ServicoFalso)
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    try:
        cli.main(["notificador"])
        assert vistos and vistos[0] not in (anterior, signal.SIG_DFL, signal.SIG_IGN)
        assert paradas == [True]  # SIGTERM pede parada limpa, sem SystemExit
    finally:
        signal.signal(signal.SIGTERM, anterior)


def test_casador_existe():
    with pytest.raises(SystemExit) as saida:
        cli.main(["casador", "--help"])
    assert saida.value.code == 0


@pytest.mark.parametrize("chave", ["", "sk-teste"])
def test_casador_so_cria_transporte_com_chave(monkeypatch, chave, batidas):
    from tcg_sniper.casador import servico
    from tcg_sniper.ia import transporte_openai

    anterior = signal.getsignal(signal.SIGTERM)
    vistos = []

    class ServicoFalso:
        def __init__(self, sessoes, transporte, config, notificador):
            vistos.append(transporte)

        def parar(self):
            pass

        def rodar(self):
            vistos.append(signal.getsignal(signal.SIGTERM))

    monkeypatch.setattr(servico, "ServicoCasador", ServicoFalso)
    monkeypatch.setattr(transporte_openai, "TransporteOpenAI", lambda c, **kw: ("transporte", c, kw))
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    monkeypatch.setenv("OPENAI_API_KEY", chave)
    try:
        cli.main(["casador"])
        assert vistos[0] == (("transporte", chave, {"timeout_s": 30, "max_retries": 2}) if chave else None)
        assert vistos[1] not in (anterior, signal.SIG_DFL, signal.SIG_IGN)
        assert batidas == ["casador"]
    finally:
        signal.signal(signal.SIGTERM, anterior)


def test_ia_avaliar_sem_chave_aborta_sem_montar_o_transporte(monkeypatch):
    from tcg_sniper.ia import transporte_openai

    montados = []
    monkeypatch.setattr(transporte_openai, "TransporteOpenAI", lambda chave: montados.append(chave))
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    monkeypatch.setenv("OPENAI_API_KEY", "")
    with pytest.raises(SystemExit) as erro:
        cli.main(["ia", "avaliar", "--modelo", "gpt-5"])
    assert "OPENAI_API_KEY ausente" in str(erro.value)
    assert montados == []


def test_ia_avaliar_repassa_os_precos(monkeypatch, tmp_path):
    from decimal import Decimal

    from tcg_sniper.casador import avaliacao
    from tcg_sniper.db import repositorio
    from tcg_sniper.ia import transporte_openai

    vistos = {}

    class Sessao:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def avaliar(sessoes, transporte, http, modelos, limite, zona, relogio, **kw):
        vistos["avaliar"] = kw
        return []

    def relatorio(resultados, gerado_em, **kw):
        vistos["relatorio"] = kw
        return "relatório"

    monkeypatch.setattr(transporte_openai, "TransporteOpenAI", lambda c, **kw: object())
    monkeypatch.setattr(avaliacao, "avaliar", avaliar)
    monkeypatch.setattr(avaliacao, "relatorio_markdown", relatorio)
    monkeypatch.setattr(repositorio, "obter_config_geral", lambda s, c: type("G", (), {"fuso": "America/Sao_Paulo"})())
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: Sessao)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-teste")
    monkeypatch.setenv("DIR_DADOS", str(tmp_path))
    cli.main(["ia", "avaliar", "--modelo", "gpt-5-mini", "--preco-entrada", "0.25", "--preco-saida", "2"])
    esperado = {"preco_entrada": Decimal("0.25"), "preco_saida": Decimal(2)}
    assert vistos["avaliar"] == esperado and vistos["relatorio"] == esperado


def test_amazon_capturar_recusa_com_o_coletor_rodando(monkeypatch):
    from contextlib import contextmanager

    from tcg_sniper.coletor_liga import agendador

    @contextmanager
    def lock_ocupado(_engine, _id):
        yield False

    monkeypatch.setattr(agendador, "lock_coleta", lock_ocupado)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x@y/z")
    with pytest.raises(SystemExit, match="docker compose stop coletor-amazon"):
        cli.main(["amazon", "capturar", "--asin", "B0DNV55QBS"])


def test_amazon_capturar_exige_asin():
    with pytest.raises(SystemExit):
        cli.main(["amazon", "capturar"])


def test_amazon_capturar_mostra_o_que_salvou_e_os_avisos_mesmo_com_erro(monkeypatch, tmp_path, capsys):
    from contextlib import contextmanager

    from tcg_sniper.coletor_amazon import captura
    from tcg_sniper.coletor_liga import agendador
    from tcg_sniper.navegador import chromium

    @contextmanager
    def lock_livre(_engine, _id):
        yield True

    class ChromiumFalso:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def capturar_que_quebra(_nav, _asins, destino, *, checkout, pausar, cap):
        cap.salvas.append(destino / "carrinho_inicial.html")
        cap.avisos.append("o item B0DNV55QBS pode ter ficado no carrinho")
        raise RuntimeError("quebrou")

    monkeypatch.setattr(agendador, "lock_coleta", lock_livre)
    monkeypatch.setattr(chromium, "NavegadorChromium", ChromiumFalso)
    monkeypatch.setattr(captura, "capturar", capturar_que_quebra)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x@y/z")
    monkeypatch.setenv("DIR_DADOS", str(tmp_path))
    with pytest.raises(RuntimeError, match="quebrou"):
        cli.main(["amazon", "capturar", "--asin", "B0DNV55QBS", "--checkout"])
    saida = capsys.readouterr().out
    assert f"capturas em {tmp_path}" in saida
    assert "carrinho_inicial.html" in saida
    assert "AVISO: o item B0DNV55QBS pode ter ficado no carrinho" in saida


def test_manutencao_instala_sigterm_e_roda_o_servico_sem_r2(monkeypatch):
    from tcg_sniper.manutencao import servico

    for var in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.setenv(var, "")
    anterior = signal.getsignal(signal.SIGTERM)
    criados, paradas = [], []

    class ServicoFalso:
        def __init__(self, sessoes, config, notificador, enviador):
            criados.append(enviador)

        def parar(self):
            paradas.append(True)

        def rodar(self):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

    monkeypatch.setattr(servico, "ServicoManutencao", ServicoFalso)
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    try:
        cli.main(["manutencao"])
        assert criados == [None] and paradas == [True]
    finally:
        signal.signal(signal.SIGTERM, anterior)


@pytest.fixture
def segredo(monkeypatch):
    """SEGREDO_API falsa e fixa (sobrepõe a do .env de quem roda o teste)."""
    from fakes_api import SEGREDO_TESTE

    monkeypatch.setenv("SEGREDO_API", SEGREDO_TESTE)
    return SEGREDO_TESTE


@pytest.fixture
def banco(monkeypatch, sessoes, segredo):
    """O CLI usa as sessões do teste (tudo é desfeito no fim)."""
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: sessoes)
    return sessoes


def test_api_sobe_o_uvicorn_so_no_localhost_por_padrao(monkeypatch, segredo):
    import uvicorn

    from tcg_sniper.api import app as modulo_app

    chamadas = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: chamadas.append((app, kw)))
    monkeypatch.setattr(modulo_app, "criar_app", lambda sessoes, config: "app")
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    cli.main(["api"])
    cli.main(["api", "--host", "0.0.0.0", "--porta", "8101"])
    assert chamadas == [("app", {"host": "127.0.0.1", "port": 8100}), ("app", {"host": "0.0.0.0", "port": 8101})]


@pytest.mark.parametrize("valor", ["", "trocar-este-segredo", "curto"])
def test_api_recusa_subir_sem_segredo(monkeypatch, valor):
    import uvicorn

    chamadas = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: chamadas.append(app))
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    monkeypatch.setenv("SEGREDO_API", valor)
    with pytest.raises(SystemExit, match="SEGREDO_API"):
        cli.main(["api"])
    with pytest.raises(SystemExit, match="SEGREDO_API"):
        cli.main(["codigo-acesso", "11 90000-0002"])
    assert chamadas == []


def test_criar_superadmin_uma_vez_so(banco, capsys):
    from tcg_sniper.db import repositorio_acesso as repo_acesso
    from tcg_sniper.db.models import MensagemSaida, Papel

    cli.main(["criar-superadmin", "Pessoa Superadmin", "(11) 90000-0001"])
    saida = capsys.readouterr().out
    assert "Superadmin Pessoa Superadmin criado (+55 11 9****-**01)" in saida and "900000001" not in saida
    with banco() as s:
        dono = repo_acesso.usuario_por_numero(s, "+5511900000001")
        assert (dono.papel, dono.ativo, dono.superadmin) == (Papel.ADMIN, True, True)
        [aviso] = s.scalars(select(MensagemSaida.texto).where(MensagemSaida.destino == "admin")).all()
        assert "usuário criado" in aviso and "• Papel: Admin (superadmin)" in aviso
        assert "• Por: terminal" in aviso and "900000001" not in aviso
    with pytest.raises(SystemExit, match="já existe um superadmin"):
        cli.main(["criar-superadmin", "Outra Pessoa", "11 90000-0004"])
    with pytest.raises(SystemExit, match="número inválido"):
        cli.main(["criar-superadmin", "Mais Uma", "123"])
    with pytest.raises(SystemExit, match="nome vazio"):
        cli.main(["criar-superadmin", "  ", "11 90000-0004"])


def test_criar_superadmin_com_numero_de_outro_usuario(banco):
    from tcg_sniper.db import repositorio_acesso as repo_acesso
    from tcg_sniper.db.models import Papel
    from tcg_sniper.db.repositorio import agora_utc

    with banco() as s, s.begin():
        repo_acesso.criar_usuario(s, "Pessoa Grupo", "+5511900000002", Papel.GRUPO, agora_utc())
    with pytest.raises(SystemExit, match="trocar-superadmin"):
        cli.main(["criar-superadmin", "Pessoa Grupo", "11 90000-0002"])
    with banco() as s:
        assert repo_acesso.superadmin_atual(s) is None


def test_trocar_superadmin(banco, capsys):
    from tcg_sniper.db import repositorio_acesso as repo_acesso
    from tcg_sniper.db.models import MensagemSaida, Papel
    from tcg_sniper.db.repositorio import agora_utc

    with banco() as s, s.begin():
        repo_acesso.criar_usuario(s, "Pessoa Grupo", "+5511900000002", Papel.GRUPO, agora_utc())
        repo_acesso.criar_usuario(s, "Pessoa Inativa", "+5511900000005", Papel.ADMIN, agora_utc()).ativo = False
    with pytest.raises(SystemExit, match="ainda não há superadmin"):
        cli.main(["trocar-superadmin", "11 90000-0002"])
    cli.main(["criar-superadmin", "Pessoa Superadmin", "11 90000-0001"])
    with pytest.raises(SystemExit, match="nenhum usuário ativo"):
        cli.main(["trocar-superadmin", "11 90000-0005"])
    with pytest.raises(SystemExit, match="nenhum usuário ativo"):
        cli.main(["trocar-superadmin", "11 90000-0009"])
    with pytest.raises(SystemExit, match="já é o superadmin"):
        cli.main(["trocar-superadmin", "11 90000-0001"])
    capsys.readouterr()
    cli.main(["trocar-superadmin", "(11) 90000-0002"])
    saida = capsys.readouterr().out
    assert "Superadmin agora é Pessoa Grupo (+55 11 9****-**02); Pessoa Superadmin continua admin." in saida
    assert "900000002" not in saida
    with banco() as s:
        novo = repo_acesso.usuario_por_numero(s, "+5511900000002")
        antigo = repo_acesso.usuario_por_numero(s, "+5511900000001")
        assert (novo.papel, novo.superadmin) == (Papel.ADMIN, True)
        assert (antigo.papel, antigo.ativo, antigo.superadmin) == (Papel.ADMIN, True, False)
        textos = s.scalars(select(MensagemSaida.texto).where(MensagemSaida.destino == "admin")).all()
        assert any("superadmin trocado" in t and "• Por: terminal" in t for t in textos)


def test_codigo_de_emergencia(banco, segredo, capsys):
    from tcg_sniper.api.segredos import hash_segredo
    from tcg_sniper.db import repositorio_acesso as repo_acesso
    from tcg_sniper.db.models import MensagemSaida, Papel
    from tcg_sniper.db.repositorio import agora_utc

    with banco() as s, s.begin():
        repo_acesso.criar_usuario(s, "Pessoa Grupo", "+5511900000002", Papel.GRUPO, agora_utc())
    cli.main(["codigo-acesso", "11 90000-0002"])
    saida = capsys.readouterr().out
    codigo = re.search(r"\): (\d{6})\n", saida).group(1)
    assert "Código para Pessoa Grupo (+55 11 9****-**02)" in saida and "900000002" not in saida
    with banco() as s:
        usuario = repo_acesso.usuario_por_numero(s, "+5511900000002")
        atual = repo_acesso.ultimo_codigo(s, usuario.id)
        assert atual.hash_codigo == hash_segredo(segredo, codigo) and atual.usado_em is None
        assert s.scalars(select(MensagemSaida)).all() == []  # não manda WhatsApp


def test_codigo_de_emergencia_recusa(banco):
    with pytest.raises(SystemExit, match="número inválido"):
        cli.main(["codigo-acesso", "abc"])
    with pytest.raises(SystemExit, match="nenhum usuário ativo"):
        cli.main(["codigo-acesso", "11 90000-0009"])


def _ignorado_ingles(sessoes):
    from fakes import T0, criar_anuncio, criar_produto

    from tcg_sniper.db import repositorio_ia as repo_ia
    from tcg_sniper.db.models import OrigemCasamento, StatusCasamento

    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1")
        a = criar_anuncio(s, "B1", produto=p, status=StatusCasamento.IGNORADO, origem=OrigemCasamento.AUTOMATICO_IA)
        repo_ia.gravar_avaliacao(
            s, anuncio_id=a.id, produto_id=p.id, mesmo_produto=False, confianca=95, motivo="Anúncio em inglês",
            modelo="x", assinatura="x", sem_imagem=True, chamada_id=None, agora=T0,
        )
        return a.id, p.id


def _status(sessoes, anuncio_id, produto_id):
    from tcg_sniper.db import repositorio_casamento as repo_casamento

    with sessoes() as s:
        return repo_casamento.obter_par(s, anuncio_id, produto_id).status.value


def test_casamento_reabrir_ingles_sem_aplicar_so_mostra_as_contagens(banco, capsys):
    ids = _ignorado_ingles(banco)
    cli.main(["casamento", "reabrir-ingles"])
    saida = capsys.readouterr().out
    assert "Encontrados: 1" in saida and "Reabertos: 1" in saida and "Confirmados em outro produto: 0" in saida
    assert "simulação" in saida and "--aplicar" in saida
    assert _status(banco, *ids) == "ignorado"


def test_casamento_reabrir_ingles_aplicando(banco, capsys):
    ids = _ignorado_ingles(banco)
    cli.main(["casamento", "reabrir-ingles", "--aplicar"])
    saida = capsys.readouterr().out
    assert "Reabertos: 1" in saida and "simulação" not in saida
    assert _status(banco, *ids) == "pendente"
