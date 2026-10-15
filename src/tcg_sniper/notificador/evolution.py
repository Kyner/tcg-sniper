"""Um envio de texto pela Evolution API, classificado para o serviço notificador decidir o que fazer."""

import enum
from urllib.parse import quote

import httpx


class Resultado(enum.StrEnum):
    OK = "ok"
    TRANSITORIO = "transitorio"  # rede, timeout ou 5xx: tentar de novo mais tarde
    DEFINITIVO = "definitivo"  # 4xx: instância, grupo ou chave errados


def enviar_uma_vez(
    cliente: httpx.Client, url: str, chave: str, instancia: str, grupo: str, texto: str
) -> tuple[Resultado, str | None]:
    """Uma tentativa, sem retries (quem tenta de novo é o serviço). Nunca lança exceção."""
    endpoint = f"{url.rstrip('/')}/message/sendText/{quote(instancia, safe='')}"
    try:
        resposta = cliente.post(endpoint, headers={"apikey": chave}, json={"number": grupo, "text": texto})
    except Exception as erro:  # noqa: BLE001 - qualquer falha de envio é tratada como transitória
        return Resultado.TRANSITORIO, f"{type(erro).__name__}: {erro}"
    if resposta.is_success:
        return Resultado.OK, None
    corpo = resposta.text[:200]
    if resposta.status_code >= 500:
        return Resultado.TRANSITORIO, f"HTTP {resposta.status_code}: {corpo}"
    return Resultado.DEFINITIVO, f"HTTP {resposta.status_code}: {corpo}"
