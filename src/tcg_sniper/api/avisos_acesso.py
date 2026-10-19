"""Avisos `SEGURANCA_USUARIO` para o grupo admin: quem mudou o quê. Nunca o número da pessoa."""

from datetime import datetime

from sqlalchemy.orm import Session

from tcg_sniper.api.permissoes import DEFINICOES, ROTULOS_PAPEL, Permissao
from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.db.models import Papel, Usuario


def _avisar(s: Session, titulo_extra: str, linhas: tuple[str, ...], agora: datetime) -> None:
    avisos.avisar(s, TipoAviso.SEGURANCA_USUARIO, CHAVE_GERAL, Dados(titulo_extra=titulo_extra, linhas=linhas), agora)


def usuario_criado(s: Session, usuario: Usuario, por: str, agora: datetime) -> None:
    papel = ROTULOS_PAPEL[usuario.papel] + (" (superadmin)" if usuario.superadmin else "")
    _avisar(s, "usuário criado", (f"Usuário: {usuario.nome}", f"Papel: {papel}", f"Por: {por}"), agora)


def superadmin_trocado(s: Session, novo: Usuario, antigo: Usuario, por: str, agora: datetime) -> None:
    linhas = (f"Superadmin agora: {novo.nome}", f"Antes: {antigo.nome} (continua admin)", f"Por: {por}")
    _avisar(s, "superadmin trocado", linhas, agora)


def papel_alterado(s: Session, usuario: Usuario, antes: Papel, por: str, agora: datetime) -> None:
    papel = f"Papel: {ROTULOS_PAPEL[antes]} → {ROTULOS_PAPEL[usuario.papel]}"
    _avisar(s, "papel alterado", (f"Usuário: {usuario.nome}", papel, f"Por: {por}"), agora)


def ativo_alterado(s: Session, usuario: Usuario, por: str, agora: datetime) -> None:
    if usuario.ativo:
        _avisar(s, "usuário reativado", (f"Usuário: {usuario.nome}", f"Por: {por}"), agora)
    else:
        linhas = (f"Usuário: {usuario.nome}", "Sessões encerradas na hora", f"Por: {por}")
        _avisar(s, "usuário desativado", linhas, agora)


def permissao_alterada(s: Session, papel: Papel, permissao: Permissao, permitido: bool, por: str, agora: datetime) -> None:
    linhas = (
        f"Papel: {ROTULOS_PAPEL[papel]}",
        f"Permissão: {DEFINICOES[permissao].rotulo}",
        f"Agora: {'permitido' if permitido else 'negado'}",
        f"Por: {por}",
    )
    _avisar(s, "permissão alterada", linhas, agora)
