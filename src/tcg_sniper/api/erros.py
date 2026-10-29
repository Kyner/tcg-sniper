"""Erros da API em JSON padronizado: {"erro": "<código>", "mensagem": "<texto em português>"}.
Nenhuma resposta de erro ecoa o valor recebido (pode ser número de telefone ou código)."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

MENSAGEM_NUMERO_INVALIDO = "Número inválido. Use DDD e número, ex.: (11) 9XXXX-XXXX."
PADROES = {
    401: ("sem_sessao", "Entre de novo para continuar."),
    403: ("sem_permissao", "Seu acesso não permite isto."),
    404: ("nao_encontrado", "Não encontrado."),
    405: ("metodo_invalido", "Método não permitido."),
    422: ("validacao", "Dados inválidos."),
    429: ("limite", "Muitos pedidos. Espere alguns minutos e tente de novo."),
}


class ErroApi(Exception):
    """`campos` (opcional): mensagem por campo, para a tela mostrar cada erro junto ao seu campo."""

    def __init__(self, status: int, erro: str, mensagem: str, campos: dict[str, str] | None = None):
        super().__init__(erro)
        self.status = status
        self.erro = erro
        self.mensagem = mensagem
        self.campos = campos


def _resposta(status: int, erro: str, mensagem: str, campos: dict[str, str] | None = None) -> JSONResponse:
    corpo: dict[str, object] = {"erro": erro, "mensagem": mensagem}
    if campos is not None:
        corpo["campos"] = campos
    return JSONResponse(corpo, status_code=status)


def instalar_tratadores(app: FastAPI) -> None:
    @app.exception_handler(ErroApi)
    async def _erro_api(_request: Request, erro: ErroApi) -> JSONResponse:
        return _resposta(erro.status, erro.erro, erro.mensagem, erro.campos)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, erro: StarletteHTTPException) -> JSONResponse:
        codigo, mensagem = PADROES.get(erro.status_code, ("erro", "Erro inesperado."))
        return _resposta(erro.status_code, codigo, mensagem)

    @app.exception_handler(RequestValidationError)
    async def _validacao(_request: Request, erro: RequestValidationError) -> JSONResponse:
        """Diz quais campos estão errados, nunca o valor recebido."""
        campos = sorted({str(e["loc"][-1]) for e in erro.errors() if e.get("loc")} - {"body"})
        mensagem = "Dados inválidos" + (f": {', '.join(campos)}." if campos else ".")
        return _resposta(422, "validacao", mensagem)

    @app.exception_handler(Exception)
    async def _inesperado(request: Request, _erro: Exception) -> JSONResponse:
        log.exception("erro inesperado em %s %s", request.method, request.url.path)
        return _resposta(500, "interno", "Erro interno. Tente de novo em instantes.")
