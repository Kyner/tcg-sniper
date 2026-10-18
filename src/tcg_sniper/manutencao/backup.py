"""Backup do banco: `pg_dump -Fc` num nome temporário, validação com `pg_restore --list`, troca
atômica para o nome final e rodízio dos arquivos automáticos (7 diários + 4 semanais).

Só os arquivos com os nomes automáticos (`tcg-diario-AAAA-MM-DD.dump` e `tcg-semanal-AAAA-Wss.dump`)
são apagados; os backups manuais da mesma pasta (`tcg-antes-*.dump`) e qualquer outro arquivo ficam.
"""

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy.engine import make_url

MANTER_DIARIOS = 7
MANTER_SEMANAIS = 4
TIMEOUT_DUMP_S = 30 * 60
TIMEOUT_LISTA_S = 5 * 60
PADRAO_DIARIO = re.compile(r"tcg-diario-\d{4}-\d{2}-\d{2}\.dump")
PADRAO_SEMANAL = re.compile(r"tcg-semanal-\d{4}-W\d{2}\.dump")
PADRAO_TEMPORARIO = re.compile(r"\.tcg-(diario|semanal)-[0-9W-]+\.dump\.tmp")


class ErroBackup(Exception):
    """Falha do backup com uma mensagem curta, em português, sem senha nem stack trace."""


@dataclass(frozen=True)
class SaidaComando:
    codigo: int
    stdout: str
    stderr: str


Executar = Callable[[Sequence[str], Mapping[str, str], float], SaidaComando]  # (args, env extra, timeout em s)


def executar_comando(args: Sequence[str], env: Mapping[str, str], timeout: float | None = None) -> SaidaComando:
    r = subprocess.run(
        list(args), env={**os.environ, **env}, capture_output=True, text=True, timeout=timeout, check=False,
        encoding="utf-8", errors="replace",
    )
    return SaidaComando(r.returncode, r.stdout, r.stderr)


@dataclass(frozen=True)
class Conexao:
    host: str
    porta: int
    usuario: str
    senha: str | None
    banco: str


def conexao_do_banco(database_url: str) -> Conexao:
    """Dados de conexão do DATABASE_URL (`postgresql+psycopg://...`; o driver não importa ao pg_dump)."""
    url = make_url(database_url)
    return Conexao(url.host or "localhost", url.port or 5432, url.username or "", url.password, url.database or "")


@dataclass(frozen=True)
class ArquivosBackup:
    diario: Path
    semanal: Path | None
    tamanho: int
    erro_semanal: str | None = None  # a cópia semanal falhou; o diário ficou


def nome_diario(dia: date) -> str:
    return f"tcg-diario-{dia:%Y-%m-%d}.dump"


def _semana(dia: date) -> str:
    ano, semana, _ = dia.isocalendar()
    return f"{ano}-W{semana:02d}"


def eh_domingo(dia: date) -> bool:
    return dia.isoweekday() == 7


def nome_semanal(dia: date) -> str | None:
    return f"tcg-semanal-{_semana(dia)}.dump" if eh_domingo(dia) else None


def chave_r2_diario(dia: date) -> str:
    return f"diario/tcg-{dia:%Y-%m-%d}.dump"


def chave_r2_semanal(dia: date) -> str:
    return f"semanal/tcg-{_semana(dia)}.dump"


def _primeira_linha(texto: str) -> str:
    linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
    return (linhas[0] if linhas else "sem mensagem")[:200]


def _rodar(executar: Executar, args: list[str], env: Mapping[str, str], timeout: float) -> SaidaComando:
    try:
        return executar(args, env, timeout)
    except FileNotFoundError:
        raise ErroBackup(f"{args[0]} não encontrado no container (falta o postgresql-client-16 na imagem)") from None
    except subprocess.TimeoutExpired:
        raise ErroBackup(f"{args[0]} demorou demais (mais de {int(timeout // 60)} min)") from None


def _apagar_temporarios(pasta: Path) -> None:
    for arquivo in pasta.iterdir():
        if arquivo.is_file() and PADRAO_TEMPORARIO.fullmatch(arquivo.name):
            arquivo.unlink(missing_ok=True)


def _dump(pasta: Path, dia: date, conexao: Conexao, executar: Executar) -> Path:
    final = pasta / nome_diario(dia)
    temporario = pasta / f".{final.name}.tmp"
    env = {"PGCONNECT_TIMEOUT": "15"}
    if conexao.senha:
        env["PGPASSWORD"] = conexao.senha  # fora dos argumentos: não aparece em `ps` nem em erro
    args = [
        "pg_dump", "-Fc", "--no-password", "-h", conexao.host, "-p", str(conexao.porta), "-U", conexao.usuario,
        "-d", conexao.banco, "-f", str(temporario),
    ]
    try:
        saida = _rodar(executar, args, env, TIMEOUT_DUMP_S)
        if saida.codigo != 0:
            raise ErroBackup(f"pg_dump falhou (código {saida.codigo}): {_primeira_linha(saida.stderr)}")
        lista = _rodar(executar, ["pg_restore", "--list", str(temporario)], {}, TIMEOUT_LISTA_S)
        if lista.codigo != 0:
            raise ErroBackup(f"validação do backup falhou: pg_restore --list saiu com código {lista.codigo}: "
                             f"{_primeira_linha(lista.stderr)}")
        if not lista.stdout.strip():
            raise ErroBackup("validação do backup falhou: pg_restore --list não listou nada")
        os.replace(temporario, final)
        return final
    finally:
        temporario.unlink(missing_ok=True)


def _copiar_atomico(origem: Path, destino: Path) -> None:
    temporario = destino.with_name(f".{destino.name}.tmp")
    try:
        shutil.copyfile(origem, temporario)
        os.replace(temporario, destino)
    finally:
        temporario.unlink(missing_ok=True)


def fazer_backup(pasta: Path, dia: date, conexao: Conexao, executar: Executar = executar_comando) -> ArquivosBackup:
    """Grava o backup diário de `dia` (e, no domingo, a cópia semanal). Erro no diário vira `ErroBackup`;
    erro só na cópia semanal não perde o diário: volta em `erro_semanal`."""
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        _apagar_temporarios(pasta)
        diario = _dump(pasta, dia, conexao, executar)
        tamanho = diario.stat().st_size
    except OSError as erro:
        raise ErroBackup(f"erro de disco no backup: {erro.strerror or erro}") from None
    nome = nome_semanal(dia)
    if nome is None:
        return ArquivosBackup(diario, None, tamanho)
    try:
        _copiar_atomico(diario, pasta / nome)
    except OSError as erro:
        return ArquivosBackup(diario, None, tamanho, f"cópia semanal falhou: {erro.strerror or erro}")
    return ArquivosBackup(diario, pasta / nome, tamanho)


def rodiziar(pasta: Path, manter_diarios: int = MANTER_DIARIOS, manter_semanais: int = MANTER_SEMANAIS) -> list[str]:
    """Apaga os automáticos mais antigos (pelo nome, que ordena pela data). Devolve os nomes apagados."""
    removidos = []
    for padrao, manter in ((PADRAO_DIARIO, manter_diarios), (PADRAO_SEMANAL, manter_semanais)):
        nomes = sorted((a.name for a in pasta.iterdir() if a.is_file() and padrao.fullmatch(a.name)), reverse=True)
        for nome in nomes[manter:]:
            (pasta / nome).unlink(missing_ok=True)
            removidos.append(nome)
    return removidos
