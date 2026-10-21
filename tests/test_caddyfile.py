from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def test_csp_libera_so_o_nosso_host_de_imagens():
    texto = (RAIZ / "web" / "Caddyfile").read_text(encoding="utf-8")
    assert "img-src 'self' data: {$URL_PUBLICA_IMAGENS};" in texto
    assert "sbrauble" not in texto and "media-amazon" not in texto
    assert "style-src 'self';" in texto and "script-src 'self';" in texto
    assert "URL_PUBLICA_IMAGENS" in (RAIZ / "docker-compose.yml").read_text(encoding="utf-8")
