"""Gestão → Usuários: listar, criar, editar (nome, papel, ativo) e as sessões de cada um. Exige `gerir_usuarios`.
Só o superadmin cria, edita, rebaixa ou desativa admins e vê ou encerra sessões de admins (403 `so_superadmin`); o
superadmin nunca é rebaixado, desativado nem tem sessões encerradas por ninguém (403 `superadmin_protegido`; só ele
encerra as dele). Quem não é o superadmin não muda o próprio papel nem se desativa (403 `proprio_papel`); o próprio
nome e as próprias sessões, qualquer um. Desativar encerra todas as sessões na hora. Criar e trocar o superadmin: só pelos comandos locais. O número sai sempre mascarado."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from tcg_sniper.api import avisos_acesso
from tcg_sniper.api.dependencias import Contexto, exige
from tcg_sniper.api.erros import MENSAGEM_NUMERO_INVALIDO, ErroApi
from tcg_sniper.api.permissoes import Permissao
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Papel, Sessao, Usuario
from tcg_sniper.formatacao import mascarar_numero, normalizar_numero

roteador = APIRouter(prefix="/api", tags=["usuarios"])
GerirUsuarios = Annotated[Contexto, Depends(exige(Permissao.GERIR_USUARIOS))]
MAX_ID = 2**31 - 1  # fora do integer do Postgres: 404, nunca 500


def _nome_limpo(valor: str | None) -> str | None:
    if valor is None:
        return None
    valor = valor.strip()
    if not valor:
        raise ValueError("nome vazio")
    return valor


class UsuarioSaida(BaseModel):
    id: int
    nome: str
    numero_mascarado: str
    papel: Papel
    superadmin: bool
    ativo: bool
    criado_em: datetime
    sessoes_ativas: int


class UsuariosSaida(BaseModel):
    usuarios: list[UsuarioSaida]


class NovoUsuario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nome: str = Field(min_length=1, max_length=80)
    numero: str = Field(max_length=30)
    papel: Papel

    @field_validator("nome")
    @classmethod
    def _limpar_nome(cls, valor: str | None) -> str | None:
        return _nome_limpo(valor)


class EdicaoUsuario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nome: str | None = Field(default=None, min_length=1, max_length=80)
    papel: Papel | None = None
    ativo: bool | None = None

    @field_validator("nome")
    @classmethod
    def _limpar_nome(cls, valor: str | None) -> str | None:
        return _nome_limpo(valor)

    @model_validator(mode="after")
    def _algo_a_mudar(self) -> "EdicaoUsuario":
        if self.nome is None and self.papel is None and self.ativo is None:
            raise ValueError("nada a mudar")
        return self


class SessaoSaida(BaseModel):
    id: int
    aparelho: str
    criada_em: datetime
    ultimo_uso_em: datetime
    expira_em: datetime
    atual: bool


class SessoesSaida(BaseModel):
    sessoes: list[SessaoSaida]


class Ok(BaseModel):
    ok: bool = True


def _saida(usuario: Usuario, sessoes_ativas: int) -> UsuarioSaida:
    return UsuarioSaida(
        id=usuario.id, nome=usuario.nome, numero_mascarado=mascarar_numero(usuario.numero), papel=usuario.papel,
        superadmin=usuario.superadmin, ativo=usuario.ativo, criado_em=usuario.criado_em, sessoes_ativas=sessoes_ativas,
    )


def _obter(s: Session, usuario_id: int, *, travar: bool = False) -> Usuario:
    """`travar`: SELECT ... FOR UPDATE (lido de novo do banco) para editar sem corrida com outra edição ou com o
    `trocar-superadmin`."""
    if not 1 <= usuario_id <= MAX_ID:
        usuario = None
    else:
        usuario = s.get(Usuario, usuario_id, with_for_update=travar, populate_existing=travar)
    if usuario is None:
        raise ErroApi(404, "nao_encontrado", "Usuário não encontrado.")
    return usuario


def _so_superadmin(contexto: Contexto, *papeis: Papel | None) -> None:
    """Admin envolvido (alvo admin ou papel novo admin): só o superadmin."""
    if not contexto.superadmin and Papel.ADMIN in papeis:
        raise ErroApi(
            403, "so_superadmin", "Só o superadmin cria, edita, rebaixa ou desativa admins e vê ou encerra as sessões deles."
        )


def _protegido() -> ErroApi:
    return ErroApi(403, "superadmin_protegido", "O superadmin não pode ser rebaixado, desativado nem encerrado.")


@roteador.get("/usuarios")
def listar(request: Request, _contexto: GerirUsuarios) -> UsuariosSaida:
    estado = request.app.state
    with estado.sessoes() as s:
        contagem = repo_acesso.contar_sessoes_ativas(s, estado.relogio())
        return UsuariosSaida(usuarios=[_saida(u, contagem.get(u.id, 0)) for u in repo_acesso.listar_usuarios(s)])


@roteador.post("/usuarios", status_code=201)
def criar(request: Request, entrada: NovoUsuario, contexto: GerirUsuarios) -> UsuarioSaida:
    _so_superadmin(contexto, entrada.papel)
    try:
        numero = normalizar_numero(entrada.numero)
    except ValueError:
        raise ErroApi(422, "numero_invalido", MENSAGEM_NUMERO_INVALIDO) from None
    estado = request.app.state
    agora = estado.relogio()
    with estado.sessoes() as s, s.begin():
        try:
            usuario = repo_acesso.criar_usuario(s, entrada.nome, numero, entrada.papel, agora)
        except repo_acesso.NumeroJaCadastrado:
            raise ErroApi(409, "numero_ja_cadastrado", "Já existe um usuário com este número.") from None
        avisos_acesso.usuario_criado(s, usuario, contexto.nome, agora)
        return _saida(usuario, 0)


@roteador.patch("/usuarios/{usuario_id}")
def editar(request: Request, usuario_id: int, entrada: EdicaoUsuario, contexto: GerirUsuarios) -> UsuarioSaida:
    estado = request.app.state
    agora = estado.relogio()
    with estado.sessoes() as s, s.begin():
        usuario = _obter(s, usuario_id, travar=True)  # duas edições ao mesmo tempo: uma espera a outra
        rebaixa = entrada.papel is not None and entrada.papel is not Papel.ADMIN
        if usuario.superadmin and (rebaixa or entrada.ativo is False):
            raise _protegido()  # nem ele mesmo; papel admin e ativo true (formulário inteiro) passam
        if usuario.id == contexto.usuario_id and not contexto.superadmin:
            # Quem não é o superadmin não muda o próprio papel nem se desativa (senão um operador que ganhou
            # `gerir_usuarios` se promovia). O próprio nome pode; papel igual e ativo true (formulário inteiro) passam.
            muda_papel = entrada.papel is not None and entrada.papel is not usuario.papel
            if muda_papel or entrada.ativo is False:
                raise ErroApi(403, "proprio_papel", "Você não pode mudar o próprio papel nem se desativar.")
        else:
            _so_superadmin(contexto, usuario.papel, entrada.papel)
        if entrada.nome is not None:
            usuario.nome = entrada.nome
        if entrada.papel is not None and entrada.papel is not usuario.papel:
            antes = usuario.papel
            usuario.papel = entrada.papel
            avisos_acesso.papel_alterado(s, usuario, antes, contexto.nome, agora)
        if entrada.ativo is not None and entrada.ativo != usuario.ativo:
            usuario.ativo = entrada.ativo
            if not usuario.ativo:
                repo_acesso.encerrar_sessoes_do_usuario(s, usuario.id, agora)
            avisos_acesso.ativo_alterado(s, usuario, contexto.nome, agora)
        s.flush()
        return _saida(usuario, repo_acesso.contar_sessoes_ativas(s, agora).get(usuario.id, 0))


@roteador.get("/usuarios/{usuario_id}/sessoes")
def sessoes_do_usuario(request: Request, usuario_id: int, contexto: GerirUsuarios) -> SessoesSaida:
    estado = request.app.state
    with estado.sessoes() as s:
        usuario = _obter(s, usuario_id)
        if usuario.id != contexto.usuario_id:  # as próprias, qualquer um; de admins (e do superadmin), só o superadmin
            _so_superadmin(contexto, usuario.papel)
        ativas = repo_acesso.sessoes_ativas(s, usuario.id, estado.relogio())
        return SessoesSaida(
            sessoes=[
                SessaoSaida(
                    id=x.id, aparelho=x.aparelho, criada_em=x.criada_em, ultimo_uso_em=x.ultimo_uso_em,
                    expira_em=x.expira_em, atual=x.id == contexto.sessao_id,
                )
                for x in ativas
            ]
        )


@roteador.post("/sessoes/{sessao_id}/encerrar")
def encerrar(request: Request, sessao_id: int, contexto: GerirUsuarios) -> Ok:
    estado = request.app.state
    with estado.sessoes() as s, s.begin():
        sessao = s.get(Sessao, sessao_id) if 1 <= sessao_id <= MAX_ID else None
        if sessao is None:
            raise ErroApi(404, "nao_encontrado", "Sessão não encontrada.")
        if sessao.usuario_id != contexto.usuario_id:  # as próprias sessões, qualquer um encerra
            dono = s.get(Usuario, sessao.usuario_id)
            if dono.superadmin:
                raise _protegido()
            _so_superadmin(contexto, dono.papel)
        repo_acesso.encerrar_sessao(s, sessao, estado.relogio())
    return Ok()
