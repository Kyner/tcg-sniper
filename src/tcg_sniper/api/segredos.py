"""Segredos do login: código de 6 dígitos e token de sessão (aleatórios criptográficos) e o hash que vai para o
banco: HMAC-SHA256 com a chave `SEGREDO_API` do .env, nunca SHA-256 puro (sem a chave, quem lê o banco não
consegue testar os 1 milhão de códigos nem descobrir o número de um pedido). Código e token nunca vão para log nem
para o banco em texto."""

import hashlib
import hmac
import secrets

from tcg_sniper.config import Config

TAMANHO_MINIMO_SEGREDO = 32
SEGREDO_EXEMPLO = "trocar-este-segredo"  # o valor do .env.example
COMO_GERAR = 'python -c "import secrets; print(secrets.token_urlsafe(32))"'


class SegredoAusente(Exception):
    """SEGREDO_API vazia, igual à do exemplo ou curta: a API (e o código de emergência) não começam sem ela."""


def exigir_segredo(config: Config) -> str:
    valor = config.segredo_api.get_secret_value().strip() if config.segredo_api else ""
    if not valor or valor == SEGREDO_EXEMPLO or len(valor) < TAMANHO_MINIMO_SEGREDO:
        raise SegredoAusente(
            f"SEGREDO_API ausente ou fraca no .env (mínimo {TAMANHO_MINIMO_SEGREDO} caracteres). "
            f"Gere uma com: {COMO_GERAR}"
        )
    return valor


def gerar_codigo() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def gerar_token() -> str:
    return secrets.token_urlsafe(32)


def hash_segredo(segredo: str, texto: str) -> str:
    """HMAC-SHA256 em hexadecimal, com `segredo` (SEGREDO_API) como chave: código, token e número do pedido."""
    return hmac.new(segredo.encode(), texto.encode(), hashlib.sha256).hexdigest()
