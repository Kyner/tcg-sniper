"""Login do front: usuários, códigos de acesso, sessões, pedidos de código (limites) e a grade papel × permissão.
Números de WhatsApp ficam só aqui (banco); código e token entram só como hash."""

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tcg_sniper.db.models import CodigoAcesso, Papel, PedidoCodigo, PermissaoPapel, Sessao, Usuario

ACEITO = "aceito"
RETENCAO = timedelta(days=1)  # pedidos e códigos mais velhos que isso não servem para nada


class NumeroJaCadastrado(Exception):
    pass


class SuperadminJaExiste(Exception):
    pass


class TrocaInvalida(Exception):
    """`trocar_superadmin` recusada (a mensagem diz o motivo, sem dados pessoais)."""


def _violacao(erro: IntegrityError, restricao: str) -> bool:
    """O erro do banco é a violação desta restrição (e não outra, como o check de nome ou de formato do número)?"""
    return getattr(getattr(erro.orig, "diag", None), "constraint_name", None) == restricao


def criar_usuario(s: Session, nome: str, numero: str, papel: Papel, agora: datetime) -> Usuario:
    """`numero` já normalizado (E.164). Número repetido levanta `NumeroJaCadastrado` (nada é gravado); outras
    violações (nome vazio, formato do número) seguem como `IntegrityError`."""
    return _inserir(s, Usuario(nome=nome, numero=numero, papel=papel, ativo=True, criado_em=agora))


def _inserir(s: Session, usuario: Usuario) -> Usuario:
    try:
        with s.begin_nested():  # o savepoint desfaz tudo (inclusive o objeto na sessão) se falhar
            s.add(usuario)
            s.flush()
    except IntegrityError as erro:
        if _violacao(erro, "uq_usuario_numero"):
            raise NumeroJaCadastrado from None
        if _violacao(erro, "uq_usuario_superadmin"):
            raise SuperadminJaExiste from None
        raise
    return usuario


def usuario_por_numero(s: Session, numero: str) -> Usuario | None:
    return s.scalar(select(Usuario).where(Usuario.numero == numero))


def listar_usuarios(s: Session) -> list[Usuario]:
    return list(s.scalars(select(Usuario).order_by(func.lower(Usuario.nome), Usuario.id)))


def superadmin_atual(s: Session) -> Usuario | None:
    return s.scalar(select(Usuario).where(Usuario.superadmin.is_(True)))


def criar_superadmin(s: Session, nome: str, numero: str, agora: datetime) -> Usuario:
    """Só pelo comando local `criar-superadmin`. Já existe um: `SuperadminJaExiste`; número de outra pessoa:
    `NumeroJaCadastrado` (nada é gravado)."""
    if superadmin_atual(s) is not None:
        raise SuperadminJaExiste
    return _inserir(
        s, Usuario(nome=nome, numero=numero, papel=Papel.ADMIN, ativo=True, superadmin=True, criado_em=agora)
    )


def trocar_superadmin(s: Session, novo: Usuario) -> Usuario | None:
    """Só pelo comando local `trocar-superadmin`: a marca passa para `novo` (que vira admin, se não era); o antigo
    continua admin comum. Devolve o antigo (None se não havia). `TrocaInvalida` (nada muda) se `novo` já é o
    superadmin ou está inativo. Desmarca antes de marcar: o índice único é parcial."""
    if novo.superadmin:
        raise TrocaInvalida("esta pessoa já é o superadmin")
    if not novo.ativo:
        raise TrocaInvalida("esta pessoa está inativa")
    antigo = superadmin_atual(s)
    if antigo is not None:
        antigo.superadmin = False
        s.flush()
    novo.papel = Papel.ADMIN
    novo.superadmin = True
    s.flush()
    return antigo


def criar_codigo(s: Session, usuario_id: int, hash_codigo: str, agora: datetime, validade: timedelta) -> CodigoAcesso:
    codigo = CodigoAcesso(
        usuario_id=usuario_id, hash_codigo=hash_codigo, criado_em=agora, expira_em=agora + validade, tentativas=0
    )
    s.add(codigo)
    s.flush()
    return codigo


def ultimo_codigo(s: Session, usuario_id: int) -> CodigoAcesso | None:
    """O código que vale (o mais novo), travado para esta transação (as tentativas contam certo em paralelo)."""
    return s.scalar(
        select(CodigoAcesso)
        .where(CodigoAcesso.usuario_id == usuario_id)
        .order_by(CodigoAcesso.criado_em.desc(), CodigoAcesso.id.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def criar_sessao(
    s: Session, usuario_id: int, hash_token: str, aparelho: str, agora: datetime, validade: timedelta
) -> Sessao:
    sessao = Sessao(
        usuario_id=usuario_id, hash_token=hash_token, aparelho=aparelho, criada_em=agora, ultimo_uso_em=agora,
        expira_em=agora + validade,
    )
    s.add(sessao)
    s.flush()
    return sessao


def sessao_por_hash(s: Session, hash_token: str) -> Sessao | None:
    return s.scalar(select(Sessao).where(Sessao.hash_token == hash_token))


def _ativa(agora: datetime):
    return (Sessao.encerrada_em.is_(None), Sessao.expira_em > agora)


def sessoes_ativas(s: Session, usuario_id: int, agora: datetime) -> list[Sessao]:
    return list(
        s.scalars(
            select(Sessao)
            .where(Sessao.usuario_id == usuario_id, *_ativa(agora))
            .order_by(Sessao.ultimo_uso_em.desc(), Sessao.id.desc())
        )
    )


def contar_sessoes_ativas(s: Session, agora: datetime) -> dict[int, int]:
    linhas = s.execute(
        select(Sessao.usuario_id, func.count()).where(*_ativa(agora)).group_by(Sessao.usuario_id)
    )
    return {usuario_id: total for usuario_id, total in linhas}


def encerrar_sessao(s: Session, sessao: Sessao, agora: datetime) -> None:
    if sessao.encerrada_em is None:
        sessao.encerrada_em = agora
        s.flush()


def encerrar_sessoes_do_usuario(s: Session, usuario_id: int, agora: datetime) -> int:
    resultado = s.execute(
        update(Sessao)
        .where(Sessao.usuario_id == usuario_id, Sessao.encerrada_em.is_(None))
        .values(encerrada_em=agora)
        .execution_options(synchronize_session="fetch")
    )
    return resultado.rowcount


def registrar_pedido(s: Session, numero_hash: str, resultado: str, agora: datetime) -> None:
    s.add(PedidoCodigo(em=agora, numero_hash=numero_hash, resultado=resultado))
    s.flush()


def contar_pedidos(s: Session, desde: datetime, numero_hash: str | None = None) -> int:
    """Pedidos aceitos depois de `desde` (janela aberta), de um número ou de todos."""
    condicoes = [PedidoCodigo.resultado == ACEITO, PedidoCodigo.em > desde]
    if numero_hash is not None:
        condicoes.append(PedidoCodigo.numero_hash == numero_hash)
    return s.scalar(select(func.count()).select_from(PedidoCodigo).where(*condicoes)) or 0


def limpar_antigos(s: Session, agora: datetime) -> None:
    limite = agora - RETENCAO
    s.execute(delete(PedidoCodigo).where(PedidoCodigo.em < limite))
    s.execute(delete(CodigoAcesso).where(CodigoAcesso.criado_em < limite))


def grade_salva(s: Session) -> dict[tuple[Papel, str], bool]:
    return {(linha.papel, linha.permissao): linha.permitido for linha in s.scalars(select(PermissaoPapel))}


def salvar_permissao(s: Session, papel: Papel, permissao: str, permitido: bool) -> None:
    s.execute(
        pg_insert(PermissaoPapel)
        .values(papel=papel, permissao=permissao, permitido=permitido)
        .on_conflict_do_update(
            index_elements=[PermissaoPapel.papel, PermissaoPapel.permissao], set_={"permitido": permitido}
        )
    )
    s.flush()
