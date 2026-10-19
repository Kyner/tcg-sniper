"""Ajudantes dos testes da API: relógio controlável e usuário logado com token conhecido (sem passar pelo login)."""

from datetime import UTC, datetime

from sqlalchemy import select

from tcg_sniper.api.dependencias import COOKIE, VALIDADE_SESSAO
from tcg_sniper.api.segredos import hash_segredo
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import MensagemSaida, Papel

T0 = datetime(2026, 10, 18, 13, 0, tzinfo=UTC)
# Segredo falso e fixo dos testes (HMAC); o mesmo valor do fixture `config` de tests/conftest.py. Nunca um real.
SEGREDO_TESTE = "segredo-de-teste-falso-0123456789abcdefghij"
NUMEROS = {Papel.ADMIN: "+5511900000001", Papel.GRUPO: "+5511900000002", Papel.OPERADOR: "+5511900000003"}


class Relogio:
    def __init__(self, agora: datetime = T0):
        self.agora = agora

    def __call__(self) -> datetime:
        return self.agora


def criar_usuario(sessoes, papel: Papel, *, nome=None, numero=None, ativo=True, superadmin=False, agora=T0) -> int:
    """`superadmin=True` só com `Papel.ADMIN` e ativo (o banco recusa o resto) e um por teste (índice único)."""
    with sessoes() as s, s.begin():
        usuario = repo_acesso.criar_usuario(s, nome or f"Pessoa {papel.value}", numero or NUMEROS[papel], papel, agora)
        usuario.ativo = ativo
        usuario.superadmin = superadmin
        return usuario.id


def criar_sessao(sessoes, usuario_id: int, token: str, agora=T0) -> int:
    hash_token = hash_segredo(SEGREDO_TESTE, token)
    with sessoes() as s, s.begin():
        return repo_acesso.criar_sessao(s, usuario_id, hash_token, "Chrome · Windows", agora, VALIDADE_SESSAO).id


def logar(sessoes, cliente, papel: Papel, *, nome=None, numero=None, token=None, superadmin=False, agora=T0) -> int:
    """Cria o usuário e uma sessão e põe o cookie no cliente (troca o de antes). Devolve o id do usuário."""
    usuario_id = criar_usuario(sessoes, papel, nome=nome, numero=numero, superadmin=superadmin, agora=agora)
    token = token or f"token-{papel.value}-{usuario_id}"
    criar_sessao(sessoes, usuario_id, token, agora)
    # Limpa antes: um cookie gravado pela API (Set-Cookie, com domínio) ficaria ao lado deste e ganharia dele.
    cliente.cookies.clear()
    cliente.cookies.set(COOKIE, token)
    return usuario_id


def mensagens(sessoes, destino: str) -> list[str]:
    with sessoes() as s:
        return list(
            s.scalars(select(MensagemSaida.texto).where(MensagemSaida.destino == destino).order_by(MensagemSaida.id))
        )
