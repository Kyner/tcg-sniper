import ast
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tcg_sniper.avisos.catalogo import CATALOGO, CHAVE_GERAL, TipoAviso
from tcg_sniper.avisos.formato import aviso_de, formatar, formatar_lembrete, formatar_resolvido

RAIZ = Path(__file__).resolve().parents[2] / "src" / "tcg_sniper"
QUANDO = datetime(2026, 10, 18, 13, 42, tzinfo=UTC)
SP = ZoneInfo("America/Sao_Paulo")
PROIBIDO = re.compile(r":(?:8000|6080|6081)(?!\d)|192\.168\.0\.10")


def arquivos(*, fora_de: tuple[str, ...] = ()) -> list[Path]:
    saida = []
    for caminho in RAIZ.rglob("*.py"):
        relativo = caminho.relative_to(RAIZ).as_posix()
        if "migrations/" in relativo or any(relativo.startswith(p) for p in fora_de):
            continue
        saida.append(caminho)
    return saida


@pytest.mark.parametrize("tipo", list(TipoAviso))
def test_nenhum_exemplo_leva_endereco_do_sistema(tipo):
    exemplo = CATALOGO[tipo].exemplo
    aviso = aviso_de(tipo, exemplo, QUANDO)
    desde = QUANDO - timedelta(hours=2)
    textos = [
        formatar(aviso, SP, "192.168.0.10", estrito=True),
        formatar_lembrete(aviso, 3, desde, SP, "192.168.0.10", estrito=True),
        formatar_resolvido(tipo, CHAVE_GERAL, 3, desde, QUANDO, SP, "192.168.0.10", estrito=True),
    ]
    for texto in textos:
        assert not PROIBIDO.search(texto)
        for url in re.findall(r"https?://\S+", texto):
            assert re.match(r"https://www\.(amazon|ligamagic)\.com\.br/", url), url


def test_fora_de_avisos_nada_envia_mensagem_direto():
    problemas = []
    for caminho in arquivos(fora_de=("avisos/",)):
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if isinstance(no, ast.Call):
                funcao = no.func
                nome = funcao.attr if isinstance(funcao, ast.Attribute) else getattr(funcao, "id", "")
                alvo = ast.unparse(funcao.value) if isinstance(funcao, ast.Attribute) else ""
                if nome == "enfileirar" or (nome == "enviar" and "notificador" in alvo.lower()):
                    problemas.append(f"{caminho.name}:{no.lineno} {ast.unparse(funcao)}")
            if isinstance(no, ast.ImportFrom):
                nomes = {a.name for a in no.names}
                if nomes & {"Notificador", "NotificadorFila", "criar_notificador"} or (no.module or "").endswith(
                    "notificador.fila"
                ):
                    problemas.append(f"{caminho.name}:{no.lineno} import {sorted(nomes)}")
    assert problemas == []


def test_nenhum_texto_de_codigo_fora_do_admin_tem_porta_do_sistema():
    """`avisos/` fica de fora: a guarda de URL tem as portas no próprio regex."""
    problemas = []
    for caminho in arquivos(fora_de=("admin/", "avisos/")):
        for no in ast.walk(ast.parse(caminho.read_text(encoding="utf-8"))):
            if isinstance(no, ast.Constant) and isinstance(no.value, str) and PROIBIDO.search(no.value):
                problemas.append(f"{caminho.name}:{no.lineno}")
    assert problemas == []


def test_host_publico_so_no_admin_na_config_no_banco_e_nos_avisos():
    permitidos = ("admin/", "avisos/", "db/", "config.py", "config_banco.py")
    problemas = []
    for caminho in arquivos(fora_de=permitidos):
        for no in ast.walk(ast.parse(caminho.read_text(encoding="utf-8"))):
            if isinstance(no, ast.Attribute) and no.attr == "host_publico":
                problemas.append(f"{caminho.name}:{no.lineno}")
    assert problemas == []


SENSIVEIS = {"numero", "codigo", "token", "hash_codigo", "hash_token"}
MASCARAS = {"mascarar_numero", "ocultar_numero"}
NIVEIS = {"debug", "info", "warning", "error", "exception", "critical"}


def _nome_chamado(no: ast.AST) -> str:
    if isinstance(no, ast.Name):
        return no.id
    if isinstance(no, ast.Attribute):
        return no.attr
    return ""


def _cru(argumento: ast.AST) -> bool:
    """Se o trecho usa um nome sensível fora de uma máscara (também dentro de f-string)."""
    if isinstance(argumento, ast.Call) and _nome_chamado(argumento.func) in MASCARAS:
        return False
    if isinstance(argumento, ast.Name | ast.Attribute) and _nome_chamado(argumento) in SENSIVEIS:
        return True
    return any(_cru(filho) for filho in ast.iter_child_nodes(argumento))


NOMES_DE_LOGGER = {"log", "logging", "logger"}


def _e_logger(alvo: ast.AST) -> bool:
    """`log`, `logger`, `logging`, `LOG`, `_log`; `self.log`/`self._log`/`self.logger`; `logging.getLogger(...)`."""
    if isinstance(alvo, ast.Call):
        return _nome_chamado(alvo.func) == "getLogger"
    if isinstance(alvo, ast.Name | ast.Attribute):
        return _nome_chamado(alvo).lower().lstrip("_") in NOMES_DE_LOGGER
    return False


def _logs_com_dado_cru(fonte: str) -> list[int]:
    """Linhas das chamadas de log (ver `_e_logger`) que levam número, código ou token sem máscara."""
    linhas = []
    for no in ast.walk(ast.parse(fonte)):
        if not (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) and no.func.attr in NIVEIS):
            continue
        if not _e_logger(no.func.value):
            continue
        # Todos os argumentos, inclusive a mensagem (1º): f"... {numero}" também é log cru.
        argumentos = [*no.args, *(k.value for k in no.keywords)]
        if any(_cru(a) for a in argumentos):
            linhas.append(no.lineno)
    return linhas


def test_regra_de_log_pega_fstring_e_aceita_mascara():
    """A mensagem (1º argumento) também conta: f-string com o número cru é erro; mascarado, não."""
    assert _logs_com_dado_cru('log.info(f"entrada de {numero}")') == [1]
    assert _logs_com_dado_cru('log.info(f"código {s.codigo}")') == [1]
    assert _logs_com_dado_cru('log.info("token %s", token)') == [1]
    assert _logs_com_dado_cru('log.info("de %s", u.numero)') == [1]
    assert _logs_com_dado_cru('log.info(f"entrada de {mascarar_numero(numero)}")') == []
    assert _logs_com_dado_cru('log.info("de %s", mascarar_numero(numero))') == []
    assert _logs_com_dado_cru('log.info("de %s", ocultar_numero(texto))') == []
    assert _logs_com_dado_cru('log.info("pedido aceito")') == []
    assert _logs_com_dado_cru('print(numero)') == []


def test_regra_de_log_pega_logger_em_atributo_e_getlogger():
    """Logger guardado em atributo (`self.log`, `self._log`), criado na hora (`logging.getLogger(...)`) ou em
    maiúsculas (`LOG`) também é log."""
    assert _logs_com_dado_cru('self.log.info("de %s", numero)') == [1]
    assert _logs_com_dado_cru('self._log.warning(f"código {codigo}")') == [1]
    assert _logs_com_dado_cru('logging.getLogger(__name__).info("token %s", token)') == [1]
    assert _logs_com_dado_cru('LOG.error("de %s", u.numero)') == [1]
    assert _logs_com_dado_cru('_log.info("de %s", numero)') == [1]
    assert _logs_com_dado_cru('self.log.info("de %s", mascarar_numero(numero))') == []
    assert _logs_com_dado_cru('self.catalogo.info(numero)') == []


def test_log_nunca_leva_numero_codigo_ou_token_cru():
    """Número só vai para log mascarado (`mascarar_numero`/`ocultar_numero`); código e token, nunca."""
    problemas = []
    for caminho in arquivos():
        for linha in _logs_com_dado_cru(caminho.read_text(encoding="utf-8")):
            problemas.append(f"{caminho.name}:{linha}")
    assert problemas == []
