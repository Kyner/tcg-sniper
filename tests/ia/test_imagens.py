import base64
import io

import httpx
import respx
from PIL import Image

from tcg_sniper.ia.imagens import MAX_BYTES, preparar


def png(largura, altura):
    saida = io.BytesIO()
    Image.new("RGBA", (largura, altura), (255, 0, 0, 128)).save(saida, "PNG")
    return saida.getvalue()


@respx.mock
def test_reduz_e_converte_para_jpeg():
    respx.get("https://img.test/a.png").mock(return_value=httpx.Response(200, content=png(1200, 600)))
    with httpx.Client() as c:
        b64 = preparar(c, "https://img.test/a.png")
    imagem = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert imagem.format == "JPEG" and max(imagem.size) == 512 and imagem.size == (512, 256)


@respx.mock
def test_imagem_pequena_nao_aumenta():
    respx.get("https://img.test/p.png").mock(return_value=httpx.Response(200, content=png(100, 80)))
    with httpx.Client() as c:
        imagem = Image.open(io.BytesIO(base64.b64decode(preparar(c, "https://img.test/p.png"))))
    assert imagem.size == (100, 80)


@respx.mock
def test_falhas_viram_none():
    respx.get("https://img.test/404").mock(return_value=httpx.Response(404))
    respx.get("https://img.test/lixo").mock(return_value=httpx.Response(200, content=b"nao e imagem"))
    respx.get("https://img.test/grande").mock(return_value=httpx.Response(200, content=b"0" * (MAX_BYTES + 1)))
    respx.get("https://img.test/rede").mock(side_effect=httpx.ConnectError("caiu"))
    with httpx.Client() as c:
        for url in ("https://img.test/404", "https://img.test/lixo", "https://img.test/grande", "https://img.test/rede"):
            assert preparar(c, url) is None
        assert preparar(c, None) is None
        assert preparar(c, "data:image/gif;base64,R0lGOD") is None
