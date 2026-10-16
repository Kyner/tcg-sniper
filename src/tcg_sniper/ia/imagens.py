"""Baixa a imagem do produto e a prepara para a chamada: até 512 px, JPEG, base64."""

import base64
import io
import logging

import httpx
from PIL import Image, UnidentifiedImageError

log = logging.getLogger(__name__)

LADO_MAX = 512
MAX_BYTES = 5 * 1024 * 1024
QUALIDADE = 80


def preparar(cliente: httpx.Client, url: str | None) -> str | None:
    """JPEG em base64, ou None se não houver URL ou se baixar/abrir falhar (a pergunta segue só com texto)."""
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        resposta = cliente.get(url, follow_redirects=True)
        resposta.raise_for_status()
        if len(resposta.content) > MAX_BYTES:
            log.warning("imagem grande demais (%d bytes): %s", len(resposta.content), url)
            return None
        imagem = Image.open(io.BytesIO(resposta.content))
        imagem.thumbnail((LADO_MAX, LADO_MAX))
        saida = io.BytesIO()
        imagem.convert("RGB").save(saida, "JPEG", quality=QUALIDADE)
    except (httpx.HTTPError, UnidentifiedImageError, OSError) as erro:
        log.warning("não consegui preparar a imagem %s: %s", url, type(erro).__name__)
        return None
    return base64.b64encode(saida.getvalue()).decode()
