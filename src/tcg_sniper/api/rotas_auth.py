"""Login: pedir código no WhatsApp, entrar com o código (cookie `sessao`), sair e quem sou eu."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from tcg_sniper.api import acesso
from tcg_sniper.api.dependencias import COOKIE, MAX_TOKEN, VALIDADE_SESSAO, Contexto, https, usuario_logado
from tcg_sniper.api.erros import MENSAGEM_NUMERO_INVALIDO, ErroApi
from tcg_sniper.api.permissoes import Permissao
from tcg_sniper.api.segredos import hash_segredo
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Papel
from tcg_sniper.formatacao import normalizar_numero

roteador = APIRouter(prefix="/api/auth", tags=["login"])

MENSAGEM_PEDIDO = "Se o número estiver cadastrado, o código chega no WhatsApp em instantes. Vale por 5 minutos."
MENSAGEM_CODIGO_INVALIDO = "Código errado, vencido ou já usado. Peça um novo."
MENSAGEM_LIMITE = "Muitos pedidos de código. Espere alguns minutos e tente de novo."
MENSAGEM_LIMITE_ENTRAR = "Muitas tentativas. Espere alguns minutos e tente de novo."


class PedidoCodigoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numero: str = Field(max_length=30)


class EntrarEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numero: str = Field(max_length=30)
    codigo: str = Field(pattern=r"^[0-9]{6}$")


class PedidoSaida(BaseModel):
    ok: bool
    mensagem: str


class EuSaida(BaseModel):
    id: int
    nome: str
    papel: Papel
    superadmin: bool  # o front mostra/esconde as ações sobre admins (a API confere do mesmo jeito)
    permissoes: list[Permissao]


class Ok(BaseModel):
    ok: bool = True


def _numero(texto: str) -> str:
    try:
        return normalizar_numero(texto)
    except ValueError:
        raise ErroApi(422, "numero_invalido", MENSAGEM_NUMERO_INVALIDO) from None


def _gravar_cookie(resposta: Response, request: Request, token: str) -> None:
    resposta.set_cookie(
        COOKIE, token, max_age=int(VALIDADE_SESSAO.total_seconds()), path="/", httponly=True, samesite="strict",
        secure=https(request),
    )


def _eu(usuario_id: int, nome: str, papel: Papel, superadmin: bool, permissoes: frozenset[Permissao]) -> EuSaida:
    return EuSaida(
        id=usuario_id, nome=nome, papel=papel, superadmin=superadmin,
        permissoes=[p for p in Permissao if p in permissoes],
    )


@roteador.post("/pedir-codigo")
def pedir_codigo(request: Request, entrada: PedidoCodigoEntrada) -> PedidoSaida:
    numero = _numero(entrada.numero)
    estado = request.app.state
    with estado.sessoes() as s, s.begin():
        resultado = acesso.pedir_codigo(s, numero, estado.relogio(), estado.segredo)
    if resultado is not acesso.ResultadoPedido.ACEITO:  # já gravado e avisado; agora responde
        raise ErroApi(429, "limite", MENSAGEM_LIMITE)
    return PedidoSaida(ok=True, mensagem=MENSAGEM_PEDIDO)


@roteador.post("/entrar")
def entrar(request: Request, resposta: Response, entrada: EntrarEntrada) -> EuSaida:
    numero = _numero(entrada.numero)
    estado = request.app.state
    aparelho = acesso.resumir_aparelho(request.headers.get("user-agent"))
    agora = estado.relogio()
    with estado.sessoes() as s, s.begin():
        dentro_do_limite = acesso.registrar_entrada(s, numero, agora, estado.segredo)
        resultado = acesso.entrar(s, numero, entrada.codigo, aparelho, agora, estado.segredo) if dentro_do_limite else None
        if resultado is not None:
            usuario, token = resultado
            usuario_id, nome, papel, superadmin = usuario.id, usuario.nome, usuario.papel, usuario.superadmin
    if not dentro_do_limite:  # igual com ou sem cadastro: não revela quem existe
        raise ErroApi(429, "limite", MENSAGEM_LIMITE_ENTRAR)
    if resultado is None:  # a tentativa errada já foi gravada
        raise ErroApi(401, "codigo_invalido", MENSAGEM_CODIGO_INVALIDO)
    _gravar_cookie(resposta, request, token)
    return _eu(usuario_id, nome, papel, superadmin, estado.grade.efetivas(papel))


@roteador.post("/sair")
def sair(request: Request, resposta: Response) -> Ok:
    token = request.cookies.get(COOKIE, "")
    if token and len(token) <= MAX_TOKEN:
        estado = request.app.state
        with estado.sessoes() as s, s.begin():
            sessao = repo_acesso.sessao_por_hash(s, hash_segredo(estado.segredo, token))
            if sessao is not None:
                repo_acesso.encerrar_sessao(s, sessao, estado.relogio())
    resposta.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict", secure=https(request))
    return Ok()


@roteador.get("/eu")
def eu(request: Request, resposta: Response, contexto: Annotated[Contexto, Depends(usuario_logado)]) -> EuSaida:
    """Quem está logado e o que pode (o front monta menu e rotas com isso). Regrava o cookie: a sessão foi renovada."""
    _gravar_cookie(resposta, request, request.cookies[COOKIE])
    return _eu(contexto.usuario_id, contexto.nome, contexto.papel, contexto.superadmin, contexto.permissoes)
