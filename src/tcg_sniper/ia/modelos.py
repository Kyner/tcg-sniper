from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


class ErroIA(Exception):
    """Falha da chamada (rede, 5xx, 429 de limite, resposta fora do formato). A mensagem nunca traz a chave."""


class ChaveInvalida(ErroIA):
    """Chave ausente, recusada (401/403) ou sem crédito: só volta com ação do usuário."""


class SemOrcamento(ErroIA):
    """Teto de gasto ou de chamadas atingido: a chamada nem saiu."""


@dataclass(frozen=True)
class Pedido:
    modelo: str
    esforco: str
    instrucoes: str
    texto: str
    imagens: tuple[str, ...]  # JPEG em base64, sem o prefixo data:
    nome_formato: str
    formato: dict  # JSON Schema da resposta (structured outputs, strict)


@dataclass(frozen=True)
class Bruta:
    texto: str
    tokens_entrada: int
    tokens_saida: int


class Transporte(Protocol):
    def enviar(self, pedido: Pedido) -> Bruta: ...


@dataclass(frozen=True)
class RespostaIA:
    dados: dict
    modelo: str
    tokens_entrada: int
    tokens_saida: int
    custo_usd: Decimal
    chamada_id: int
