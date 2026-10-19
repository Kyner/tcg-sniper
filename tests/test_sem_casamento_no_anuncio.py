import re
from pathlib import Path

from tcg_sniper.db.models import AnuncioAmazon, FilaAmazon

RAIZ = Path(__file__).resolve().parents[1] / "src" / "tcg_sniper"
PROIBIDO = re.compile(
    r"(?:AnuncioAmazon|anuncio|l\.anuncio)\.(?:produto_id|status_casamento|origem_casamento|revisado_em)\b"
    r"|ultimo_termo_en|confirmar_casamento|ignorar_anuncio|desfazer_casamento"
)


def test_colunas_antigas_do_casamento_sairam():
    for coluna in ("produto_id", "status_casamento", "origem_casamento", "revisado_em"):
        assert coluna not in AnuncioAmazon.__table__.c
    assert "ultimo_termo_en" not in FilaAmazon.__table__.c


def test_codigo_nao_le_o_casamento_pelo_anuncio():
    achados = []
    for caminho in [*RAIZ.rglob("*.py"), *RAIZ.rglob("*.html")]:
        relativo = caminho.relative_to(RAIZ).as_posix()
        if relativo.startswith("db/migrations/"):
            continue
        for numero, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), start=1):
            if PROIBIDO.search(linha):
                achados.append(f"{relativo}:{numero}: {linha.strip()}")
    assert achados == []
