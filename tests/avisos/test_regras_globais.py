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
