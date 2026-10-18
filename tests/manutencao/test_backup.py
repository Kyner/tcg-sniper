import shutil
import subprocess
from datetime import date

import pytest

from tcg_sniper.manutencao import backup
from tcg_sniper.manutencao.backup import Conexao, ErroBackup, SaidaComando

CONEXAO = Conexao(host="postgres", porta=5432, usuario="tcg", senha="senha-do-banco", banco="tcg")
DOMINGO = date(2026, 10, 18)  # ISO 2026-W42
QUARTA = date(2026, 10, 14)


class ExecutorFake:
    """pg_dump grava `conteudo` no -f; pg_restore --list devolve `lista`. Guarda as chamadas."""

    def __init__(self, dump_codigo=0, conteudo=b"PGDMP-fake", lista="; Archive\n1; 2615 2200 SCHEMA - public\n", lista_codigo=0):
        self.dump_codigo, self.conteudo = dump_codigo, conteudo
        self.lista, self.lista_codigo = lista, lista_codigo
        self.chamadas: list[tuple[list[str], dict[str, str]]] = []

    def __call__(self, args, env, timeout=None):
        self.chamadas.append((list(args), dict(env)))
        if args[0] == "pg_dump":
            destino = args[args.index("-f") + 1]
            with open(destino, "wb") as arquivo:
                arquivo.write(self.conteudo)
            return SaidaComando(self.dump_codigo, "", "" if self.dump_codigo == 0 else "pg_dump: error: connection failed\nmais")
        assert args[:2] == ["pg_restore", "--list"]
        return SaidaComando(self.lista_codigo, self.lista, "" if self.lista_codigo == 0 else "pg_restore: error: bad")


def test_nomes_e_chaves_do_dia():
    assert backup.nome_diario(QUARTA) == "tcg-diario-2026-10-14.dump"
    assert backup.nome_semanal(QUARTA) is None
    assert backup.nome_semanal(DOMINGO) == "tcg-semanal-2026-W42.dump"
    assert backup.chave_r2_diario(DOMINGO) == "diario/tcg-2026-10-18.dump"
    assert backup.chave_r2_semanal(DOMINGO) == "semanal/tcg-2026-W42.dump"
    # semana ISO: 3 de janeiro de 2027 é domingo da semana 53 de 2026
    assert backup.nome_semanal(date(2027, 1, 3)) == "tcg-semanal-2026-W53.dump"


def test_conexao_do_banco_tira_o_driver():
    c = backup.conexao_do_banco("postgresql+psycopg://tcg:segredo@postgres:5432/tcg")
    assert c == Conexao(host="postgres", porta=5432, usuario="tcg", senha="segredo", banco="tcg")
    assert backup.conexao_do_banco("postgresql://u@h/b") == Conexao(host="h", porta=5432, usuario="u", senha=None, banco="b")


def test_backup_de_dia_de_semana_grava_so_o_diario_com_a_senha_fora_dos_argumentos(tmp_path):
    executor = ExecutorFake()
    arquivos = backup.fazer_backup(tmp_path / "backups", QUARTA, CONEXAO, executor)
    assert arquivos.diario == tmp_path / "backups" / "tcg-diario-2026-10-14.dump"
    assert arquivos.semanal is None
    assert arquivos.tamanho == len(b"PGDMP-fake")
    assert sorted(p.name for p in (tmp_path / "backups").iterdir()) == ["tcg-diario-2026-10-14.dump"]
    args, env = executor.chamadas[0]
    assert args[:2] == ["pg_dump", "-Fc"] and "senha-do-banco" not in " ".join(args)
    assert env["PGPASSWORD"] == "senha-do-banco"
    assert executor.chamadas[1][0][:2] == ["pg_restore", "--list"]


def test_domingo_tambem_grava_o_semanal(tmp_path):
    arquivos = backup.fazer_backup(tmp_path, DOMINGO, CONEXAO, ExecutorFake())
    assert arquivos.semanal == tmp_path / "tcg-semanal-2026-W42.dump"
    assert arquivos.semanal.read_bytes() == arquivos.diario.read_bytes() == b"PGDMP-fake"


def test_falha_do_pg_dump_nao_deixa_arquivo(tmp_path):
    with pytest.raises(ErroBackup, match="pg_dump falhou.*connection failed"):
        backup.fazer_backup(tmp_path, QUARTA, CONEXAO, ExecutorFake(dump_codigo=1))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(("lista", "codigo"), [("", 0), ("  \n", 0), ("; ok\n1; x\n", 1)])
def test_validacao_que_falha_nao_deixa_arquivo(tmp_path, lista, codigo):
    with pytest.raises(ErroBackup, match="validação"):
        backup.fazer_backup(tmp_path, QUARTA, CONEXAO, ExecutorFake(lista=lista, lista_codigo=codigo))
    assert list(tmp_path.iterdir()) == []


def test_pg_dump_ausente_vira_erro_legivel(tmp_path):
    def sem_binario(args, env, timeout=None):
        raise FileNotFoundError(2, "No such file or directory", args[0])

    with pytest.raises(ErroBackup, match="pg_dump não encontrado"):
        backup.fazer_backup(tmp_path, QUARTA, CONEXAO, sem_binario)


def test_disco_cheio_vira_erro_legivel(tmp_path):
    def disco_cheio(args, env, timeout=None):
        raise OSError(28, "No space left on device")

    with pytest.raises(ErroBackup, match="No space left on device"):
        backup.fazer_backup(tmp_path, QUARTA, CONEXAO, disco_cheio)


def test_tempo_esgotado_vira_erro_legivel(tmp_path):
    def demorado(args, env, timeout=None):
        raise subprocess.TimeoutExpired(args, 10)

    with pytest.raises(ErroBackup, match="demorou demais"):
        backup.fazer_backup(tmp_path, QUARTA, CONEXAO, demorado)


def test_temporario_esquecido_de_uma_execucao_anterior_e_apagado(tmp_path):
    (tmp_path / ".tcg-diario-2026-10-13.dump.tmp").write_bytes(b"meio")
    (tmp_path / ".outro.tmp").write_bytes(b"de outra pessoa")
    backup.fazer_backup(tmp_path, QUARTA, CONEXAO, ExecutorFake())
    assert sorted(p.name for p in tmp_path.iterdir()) == [".outro.tmp", "tcg-diario-2026-10-14.dump"]


def test_rodizio_mantem_7_diarios_e_4_semanais_e_nao_toca_nos_outros(tmp_path):
    diarios = [f"tcg-diario-2026-10-{dia:02d}.dump" for dia in range(1, 11)]
    semanais = [f"tcg-semanal-2026-W{semana:02d}.dump" for semana in range(36, 42)]
    outros = [
        "tcg-antes-monitor-2026-10-01.dump", "tcg-antes-ia.dump", "notas.txt", "tcg-diario-2026-10-01.dump.bak",
        "tcg-diario-velho.dump", "tcg-semanal-2026-42.dump",
    ]
    for nome in diarios + semanais + outros:
        (tmp_path / nome).write_bytes(b"x")
    (tmp_path / "subpasta").mkdir()

    removidos = backup.rodiziar(tmp_path)

    assert sorted(removidos) == sorted(diarios[:3] + semanais[:2])
    restantes = {p.name for p in tmp_path.iterdir()}
    assert restantes == set(diarios[3:]) | set(semanais[2:]) | set(outros) | {"subpasta"}


def test_executar_comando_de_verdade_devolve_codigo_e_saidas():
    python = shutil.which("python") or shutil.which("python3")
    if python is None:
        pytest.skip("sem python no PATH")
    saida = backup.executar_comando([python, "-c", "import os,sys; print(os.environ['X']); sys.exit(3)"], {"X": "ok"})
    assert (saida.codigo, saida.stdout.strip()) == (3, "ok")


@pytest.mark.skipif(
    shutil.which("pg_dump") is None or shutil.which("pg_restore") is None,
    reason="pg_dump/pg_restore ausentes; rode na imagem Docker (teste de integração real)",
)
def test_integracao_pg_dump_e_pg_restore_de_verdade(tmp_path, engine):
    url = engine.url.render_as_string(hide_password=False)
    arquivos = backup.fazer_backup(tmp_path, DOMINGO, backup.conexao_do_banco(url), backup.executar_comando)
    assert arquivos.tamanho > 0 and arquivos.semanal is not None
