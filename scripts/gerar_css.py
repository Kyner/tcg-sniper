"""Gera src/tcg_sniper/admin/static/admin.css com o Tailwind CSS standalone e o DaisyUI 5.

Uso: uv run python scripts/gerar_css.py

Baixa (uma vez) as ferramentas em .ferramentas/, confere o SHA-256 de cada arquivo, compila
src/tcg_sniper/admin/estilo.css e grava na 1ª linha do CSS o hash dos templates (o teste
test_css_em_dia_com_os_templates compara). Rode de novo sempre que mudar um template.
"""

import hashlib
import platform
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from tcg_sniper.admin import estilo

FERRAMENTAS = RAIZ / ".ferramentas"
TAILWIND = "4.1.11"
DAISYUI = "5.2.0"
BINARIOS = {
    ("Windows", "AMD64"): ("tailwindcss-windows-x64.exe", "6631a41de25a96eb8506f07b07ab56192df117a29849c7d7a995bd343329e900"),
    ("Linux", "x86_64"): ("tailwindcss-linux-x64", "64805b84af4292e043ea6f86d242f191c0ac75359c1a498455dfe6c642afdbab"),
}
PLUGINS = {
    "daisyui.mjs": "178ecea8680bdaab117caf29989960394566e757ce789f502e97a3aee02c2b0d",
    "daisyui-theme.mjs": "ec75fd0e5a809bb12d8990849749df58ae6d75f18e938d79493f5bb29be7bf20",
}


def sha256(arquivo: Path) -> str:
    return hashlib.sha256(arquivo.read_bytes()).hexdigest()


def garantir(nome: str, url: str, esperado: str) -> Path:
    destino = FERRAMENTAS / nome
    if not destino.exists() or sha256(destino) != esperado:
        FERRAMENTAS.mkdir(exist_ok=True)
        print(f"baixando {url}")
        urllib.request.urlretrieve(url, destino)
        obtido = sha256(destino)
        if obtido != esperado:
            destino.unlink()
            sys.exit(f"SHA-256 diferente para {nome}: esperado {esperado}, obtido {obtido}")
    return destino


def main() -> None:
    chave = (platform.system(), platform.machine())
    if chave not in BINARIOS:
        sys.exit(f"sistema não suportado: {chave}; suportados: {list(BINARIOS)}")
    nome_bin, sha_bin = BINARIOS[chave]
    binario = garantir(
        nome_bin, f"https://github.com/tailwindlabs/tailwindcss/releases/download/v{TAILWIND}/{nome_bin}", sha_bin
    )
    binario.chmod(binario.stat().st_mode | stat.S_IEXEC)
    for nome, sha in PLUGINS.items():
        garantir(nome, f"https://github.com/saadeghi/daisyui/releases/download/v{DAISYUI}/{nome}", sha)
    with tempfile.TemporaryDirectory() as pasta:
        saida = Path(pasta) / "admin.css"
        subprocess.run([str(binario), "-i", str(estilo.ENTRADA), "-o", str(saida), "--minify"], check=True, cwd=RAIZ)
        css = saida.read_text(encoding="utf-8")
    estilo.SAIDA.parent.mkdir(parents=True, exist_ok=True)
    cabecalho = (
        f"{estilo.PREFIXO}{estilo.hash_fontes()} */\n/* daisyUI {DAISYUI} + Tailwind CSS {TAILWIND} */\n"
    )
    estilo.SAIDA.write_text(cabecalho + css, encoding="utf-8", newline="\n")
    print(f"{estilo.SAIDA.relative_to(RAIZ)}: {estilo.SAIDA.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
