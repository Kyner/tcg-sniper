"""Os dois serviços da Amazon são funções distintas: a busca não alcança checkout, carrinho nem monitor;
o monitor não alcança a busca."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
PACOTE = SRC / "tcg_sniper" / "coletor_amazon"
CA = "tcg_sniper.coletor_amazon"
CHECKOUT_E_MONITOR = {f"{CA}.checkout", f"{CA}.cliques", f"{CA}.parsers_checkout", f"{CA}.monitor", f"{CA}.captura"}


def _arquivo(modulo: str) -> Path | None:
    base = SRC / Path(*modulo.split("."))
    if base.with_suffix(".py").exists():
        return base.with_suffix(".py")
    if (base / "__init__.py").exists():
        return base / "__init__.py"
    return None


def importados(modulo: str) -> set[str]:
    """Módulos do tcg_sniper que `modulo` alcança, direta ou indiretamente (também imports dentro de funções)."""
    vistos: set[str] = set()
    fila = [modulo]
    while fila:
        atual = fila.pop()
        if atual in vistos:
            continue
        vistos.add(atual)
        arquivo = _arquivo(atual)
        if arquivo is None:
            continue
        for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
            if isinstance(no, ast.ImportFrom) and no.module and no.module.startswith("tcg_sniper"):
                fila.append(no.module)
                fila.extend(f"{no.module}.{a.name}" for a in no.names)
            elif isinstance(no, ast.Import):
                fila.extend(a.name for a in no.names if a.name.startswith("tcg_sniper"))
    return {m for m in vistos if _arquivo(m) is not None} - {modulo}


def test_laco_da_busca_nao_alcanca_checkout_carrinho_nem_monitor():
    alcancados = importados(f"{CA}.varredura_busca")
    assert alcancados & (CHECKOUT_E_MONITOR | {f"{CA}.varredura_monitor"}) == set()


def test_laco_do_monitor_nao_alcanca_o_da_busca():
    assert f"{CA}.varredura_busca" not in importados(f"{CA}.varredura_monitor")


def test_base_nao_alcanca_nenhum_dos_lacos_nem_o_checkout():
    alcancados = importados(f"{CA}.varredura_base")
    assert alcancados & (CHECKOUT_E_MONITOR | {f"{CA}.varredura_busca", f"{CA}.varredura_monitor"}) == set()


def test_monitor_nao_chama_nada_da_fila_de_buscas():
    codigo = (PACOTE / "varredura_monitor.py").read_text(encoding="utf-8")
    for nome in ("processar_produto", "sincronizar_fila", "proximo_da_fila", "reagendar", "sequencia_de_termos",
                 "iniciar_coleta", "marcar_interrompidas"):
        assert nome not in codigo, nome


def _nomes_usados(arquivo: Path) -> set[str]:
    nomes = set()
    for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Name):
            nomes.add(no.id)
        elif isinstance(no, ast.Attribute):
            nomes.add(no.attr)
        elif isinstance(no, ast.alias):
            nomes.add(no.name)
    return nomes


def test_busca_nao_clica_nem_mexe_no_carrinho():
    proibidos = {"clicar", "clicar_permitido", "clicar_contando", "remover_do_carrinho", "URL_CARRINHO",
                 "parse_carrinho", "conferencias_com_item_no_carrinho", "candidatas_ao_checkout"}
    for arquivo in ("varredura_busca.py", "busca.py", "varredura_base.py"):
        assert _nomes_usados(PACOTE / arquivo) & proibidos == set(), arquivo


def test_varredura_unica_saiu():
    assert not (PACOTE / "varredura.py").exists()
