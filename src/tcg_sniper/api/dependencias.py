"""Dependências das rotas: quem está logado (cookie `sessao`) e a permissão que cada rota exige.
O back sempre confere: o front só esconde o que a pessoa não pode."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request

from tcg_sniper.api.erros import ErroApi
from tcg_sniper.api.permissoes import Permissao
from tcg_sniper.api.segredos import hash_segredo
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Papel, Usuario

COOKIE = "sessao"
VALIDADE_SESSAO = timedelta(days=30)
MAX_TOKEN = 200  # token maior que isso nem é procurado
MENSAGEM_SEM_SESSAO = "Entre de novo para continuar."


@dataclass(frozen=True)
class Contexto:
    usuario_id: int
    nome: str
    papel: Papel
    permissoes: frozenset[Permissao]
    sessao_id: int
    superadmin: bool  # o dono do sistema: só ele mexe em admins (rotas_usuarios)


def https(request: Request) -> bool:
    """Servido em HTTPS? Atrás do Caddy ou de um túnel vale o X-Forwarded-Proto."""
    return request.headers.get("x-forwarded-proto", request.url.scheme) == "https"


def usuario_logado(request: Request) -> Contexto:
    """Sessão ativa e não vencida de um usuário ativo; renova a validade e o último uso. Senão, 401."""
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) > MAX_TOKEN:
        raise ErroApi(401, "sem_sessao", MENSAGEM_SEM_SESSAO)
    estado = request.app.state
    agora = estado.relogio()
    with estado.sessoes() as s, s.begin():
        sessao = repo_acesso.sessao_por_hash(s, hash_segredo(estado.segredo, token))
        usuario = s.get(Usuario, sessao.usuario_id) if sessao is not None else None
        if (
            sessao is None
            or usuario is None
            or not usuario.ativo
            or sessao.encerrada_em is not None
            or sessao.expira_em <= agora
        ):
            raise ErroApi(401, "sem_sessao", MENSAGEM_SEM_SESSAO)
        sessao.ultimo_uso_em = agora
        sessao.expira_em = agora + VALIDADE_SESSAO
        usuario_id, nome, papel, sessao_id, superadmin = (
            usuario.id, usuario.nome, usuario.papel, sessao.id, usuario.superadmin
        )
    # fora da transação: a grade abre a própria sessão (o superadmin é admin: todas as permissões)
    return Contexto(usuario_id, nome, papel, estado.grade.efetivas(papel), sessao_id, superadmin)


def exige(permissao: Permissao) -> Callable[..., Contexto]:
    """Dependência de uma rota protegida: `Annotated[Contexto, Depends(exige(Permissao.X))]`."""

    def dependencia(contexto: Annotated[Contexto, Depends(usuario_logado)]) -> Contexto:
        if permissao not in contexto.permissoes:
            raise ErroApi(403, "sem_permissao", "Seu acesso não permite isto.")
        return contexto

    dependencia.permissao = permissao  # o teste das rotas confere que toda rota declara uma
    return dependencia


def exige_todas(*permissoes: Permissao) -> Callable[..., Contexto]:
    """Dependência que exige todas as permissões dadas (403 se faltar qualquer uma)."""

    def dependencia(contexto: Annotated[Contexto, Depends(usuario_logado)]) -> Contexto:
        if not all(p in contexto.permissoes for p in permissoes):
            raise ErroApi(403, "sem_permissao", "Seu acesso não permite isto.")
        return contexto

    dependencia.permissao = permissoes[-1]  # o teste das rotas confere que toda rota declara uma
    return dependencia
