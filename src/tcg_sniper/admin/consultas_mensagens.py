"""Consultas da tabela de saída do WhatsApp para o admin."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tcg_sniper.db.models import EstadoNotificador, MensagemSaida, StatusMensagem

SITUACOES = ("todas", *(s.value for s in StatusMensagem))
DESTINOS = ("todos", "admin", "oportunidades")
POR_PAGINA = 50
PENDENTE_PARADA = timedelta(minutes=30)
NOTIFICADOR_VIVO = timedelta(minutes=1)


@dataclass(frozen=True)
class ResumoMensagens:
    pendentes: int
    falhas: int
    ultimo_envio: datetime | None
    aviso: str | None
    link_aviso: str = "/mensagens?situacao=falha"
    notificador_parado: str | None = None  # "nunca" ou "parado", só com pendentes presas
    notificador_ultimo_ciclo: datetime | None = None
    paradas: int = 0  # pendentes há mais de 30 min


def listar(s: Session, situacao: str, destino: str, pagina: int) -> tuple[list[MensagemSaida], int, int]:
    condicoes = []
    if situacao != "todas":
        condicoes.append(MensagemSaida.status == StatusMensagem(situacao))
    if destino != "todos":
        condicoes.append(MensagemSaida.destino == destino)
    total = s.scalar(select(func.count()).select_from(MensagemSaida).where(*condicoes)) or 0
    paginas = max(1, -(-total // POR_PAGINA))
    pagina = min(max(pagina, 1), paginas)
    consulta = (
        select(MensagemSaida)
        .where(*condicoes)
        .order_by(MensagemSaida.criada_em.desc(), MensagemSaida.id.desc())
        .offset((pagina - 1) * POR_PAGINA)
        .limit(POR_PAGINA)
    )
    return list(s.scalars(consulta)), pagina, paginas


def _contar(s: Session, *condicoes) -> int:
    return s.scalar(select(func.count()).select_from(MensagemSaida).where(*condicoes)) or 0


def resumo(s: Session, agora: datetime, notificador_pausado: bool = False) -> ResumoMensagens:
    """Com o notificador desligado no admin, as pendentes paradas não geram aviso (o desligamento explica)."""
    pendentes = _contar(s, MensagemSaida.status == StatusMensagem.PENDENTE)
    falhas = _contar(s, MensagemSaida.status == StatusMensagem.FALHA)
    ultimo_envio = s.scalar(select(func.max(MensagemSaida.enviada_em)))
    paradas = _contar(
        s, MensagemSaida.status == StatusMensagem.PENDENTE, MensagemSaida.criada_em < agora - PENDENTE_PARADA
    )
    avisar_paradas = paradas if not notificador_pausado else 0
    aviso = None
    link_aviso = "/mensagens?situacao=falha" if falhas else "/mensagens?situacao=pendente"
    notificador_parado = None
    ultimo_ciclo = None
    if falhas or avisar_paradas:
        ultimo_erro = s.scalar(
            select(MensagemSaida.ultimo_erro)
            .where(
                MensagemSaida.status.in_([StatusMensagem.FALHA, StatusMensagem.PENDENTE]),
                MensagemSaida.ultimo_erro.is_not(None),
            )
            .order_by(MensagemSaida.atualizado_em.desc())
            .limit(1)
        )
        partes = []
        if falhas:
            partes.append(f"{falhas} com falha")
        if avisar_paradas:
            partes.append(f"{paradas} pendente(s) há mais de 30 min")
        aviso = "Mensagens do WhatsApp paradas: " + " e ".join(partes) + "."
        if ultimo_erro:
            aviso += f" Último erro: {ultimo_erro}"
        if avisar_paradas:
            situacao, ultimo_ciclo = estado_notificador(s, agora)
            if situacao != "rodando":
                notificador_parado = situacao
    return ResumoMensagens(
        pendentes, falhas, ultimo_envio, aviso, link_aviso, notificador_parado, ultimo_ciclo, paradas
    )


def estado_notificador(s: Session, agora: datetime) -> tuple[str, datetime | None]:
    estado = s.get(EstadoNotificador, 1)
    ultimo = estado.ultimo_ciclo_em if estado else None
    if ultimo is None:
        return "nunca", None
    return ("rodando" if agora - ultimo < NOTIFICADOR_VIVO else "parado"), ultimo
