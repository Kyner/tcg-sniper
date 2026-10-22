"""Imagens nas respostas da API: só a cópia nossa (URL pública do bucket); nunca a URL da Liga ou da Amazon."""

from fastapi import Request


def com_imagens(dados, base: str | None):
    """Troca cada `imagem_chave` das consultas por `imagem`: a URL pública da cópia, ou None sem cópia ou sem
    `URL_PUBLICA_IMAGENS` (a tela sai sem foto; nunca aponta para a Liga ou a Amazon)."""
    if isinstance(dados, list):
        return [com_imagens(d, base) for d in dados]
    if not isinstance(dados, dict):
        return dados
    saida = {}
    for chave, valor in dados.items():
        if chave == "imagem_chave":
            saida["imagem"] = f"{base.rstrip('/')}/{valor}" if base and valor else None
        else:
            saida[chave] = com_imagens(valor, base)
    return saida


def base_imagens(request: Request) -> str | None:
    return request.app.state.config.url_publica_imagens
