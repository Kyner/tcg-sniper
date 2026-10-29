"""API pública dos avisos do WhatsApp: `avisar` registra a ocorrência e, conforme a regra de repetição e o
liga/desliga do tipo, grava a mensagem na tabela de saída (`mensagem_saida`, enviada pelo serviço
`notificador`); `resolver` fecha um problema aberto e manda "✅ resolvido" se algum aviso dele saiu.

Repetição (tipos com `agrupa`), estado por (tipo, chave) em `estado_aviso`:
- sem problema aberto: abre (ocorrências = 1) e envia;
- aberto e último envio há menos que `lembrete`: só conta;
- aberto e último envio há `lembrete` ou mais (ou nunca enviado): manda o lembrete.
O lembrete é decidido no `avisar`: com o serviço parado nada se acumula.
Os tipos em `TIPOS_QUE_ESPERAM` (bloqueio que só espera alguém agir, sem nova ocorrência) recebem o lembrete
de `lembrar_abertos`, chamado a cada minuto pela manutenção; ele não mexe nas ocorrências.

Nada aqui propaga exceção (cada chamada roda num SAVEPOINT; falha vira log), menos `UrlProibida` com
`formato.ESTRITO` ligado (testes)."""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.avisos import formato
from tcg_sniper.avisos.catalogo import CATALOGO, CHAVE_GERAL, TIPOS_QUE_ESPERAM, Dados, TipoAviso
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import ConfigAviso, ConfigGeral, EstadoAviso
from tcg_sniper.db.repositorio import agora_utc
from tcg_sniper.notificador.base import Destino

log = logging.getLogger(__name__)

FUSO_PADRAO = "America/Sao_Paulo"
VALIDADE_INDIVIDUAL = timedelta(minutes=5)


def _deixar_subir(erro: Exception) -> bool:
    return formato.ESTRITO and isinstance(erro, formato.UrlProibida)


def deve_subir(erro: Exception) -> bool:
    """No modo estrito (testes), o erro de URL proibida não pode ser engolido por quem protege o laço."""
    return _deixar_subir(erro)


def zona_e_host(s: Session) -> tuple[ZoneInfo, str | None]:
    """Fuso e host_publico de Configurações → Geral (sem a linha: fuso padrão e nenhum host)."""
    geral = s.get(ConfigGeral, 1)
    if geral is None:
        return ZoneInfo(FUSO_PADRAO), None
    try:
        return ZoneInfo(geral.fuso), geral.host_publico
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(FUSO_PADRAO), geral.host_publico


def ligado(s: Session, tipo: TipoAviso) -> bool:
    linha = s.get(ConfigAviso, tipo.value)
    return CATALOGO[tipo].ligado_padrao if linha is None else linha.ligado


def ligados(s: Session) -> dict[TipoAviso, bool]:
    salvos = {c.tipo: c.ligado for c in s.scalars(select(ConfigAviso))}
    return {tipo: salvos.get(tipo.value, d.ligado_padrao) for tipo, d in CATALOGO.items()}


def definir_ligado(s: Session, tipo: TipoAviso, valor: bool) -> None:
    s.execute(
        pg_insert(ConfigAviso)
        .values(tipo=tipo.value, ligado=valor)
        .on_conflict_do_update(index_elements=[ConfigAviso.tipo], set_={"ligado": valor})
    )
    s.flush()


def abertos(s: Session, tipo: TipoAviso) -> list[str]:
    return list(
        s.scalars(
            select(EstadoAviso.chave)
            .where(EstadoAviso.tipo == tipo.value, EstadoAviso.aberto.is_(True))
            .order_by(EstadoAviso.chave)
        )
    )


def _enfileirar(s: Session, tipo: TipoAviso, texto: str, agora: datetime) -> int:
    return repo_msg.enfileirar(s, CATALOGO[tipo].grupo.value, texto, agora).id


def _travar(s: Session, tipo: TipoAviso, chave: str, agora: datetime) -> EstadoAviso:
    """A linha do problema, criada fechada se não existe e travada para esta transação."""
    s.execute(
        pg_insert(EstadoAviso)
        .values(tipo=tipo.value, chave=chave, aberto=False, primeiro_em=agora, ultimo_em=agora, ocorrencias=0)
        .on_conflict_do_nothing(index_elements=[EstadoAviso.tipo, EstadoAviso.chave])
    )
    return s.get(EstadoAviso, (tipo.value, chave), with_for_update=True, populate_existing=True)


def _avisar(s: Session, tipo: TipoAviso, chave: str, dados: Dados, agora: datetime) -> int | None:
    definicao = CATALOGO[tipo]
    if definicao.grupo is Destino.INDIVIDUAL:
        log.error("aviso %s é individual: use avisar_individual", tipo.value)
        return None
    zona, host = zona_e_host(s)
    aviso = formato.aviso_de(tipo, dados, agora)
    liga = ligado(s, tipo)
    if not definicao.agrupa:
        if liga:
            return _enfileirar(s, tipo, formato.formatar(aviso, zona, host), agora)
        return None
    estado = _travar(s, tipo, chave, agora)
    if not estado.aberto:
        estado.aberto, estado.ocorrencias = True, 1
        estado.primeiro_em = estado.ultimo_em = agora
        estado.ultimo_envio_em = None
        mensagem_id = None
        if liga:
            mensagem_id = _enfileirar(s, tipo, formato.formatar(aviso, zona, host), agora)
            estado.ultimo_envio_em = agora
        s.flush()
        return mensagem_id
    estado.ocorrencias += 1
    estado.ultimo_em = agora
    mensagem_id = None
    if liga and (estado.ultimo_envio_em is None or agora - estado.ultimo_envio_em >= definicao.lembrete):
        texto = formato.formatar_lembrete(aviso, estado.ocorrencias, estado.primeiro_em, zona, host)
        mensagem_id = _enfileirar(s, tipo, texto, agora)
        estado.ultimo_envio_em = agora
    s.flush()
    return mensagem_id


def _resolver(s: Session, tipo: TipoAviso, chave: str, agora: datetime) -> None:
    if not CATALOGO[tipo].agrupa:
        return
    estado = s.get(EstadoAviso, (tipo.value, chave), with_for_update=True, populate_existing=True)
    if estado is None or not estado.aberto:
        return
    estado.aberto = False
    if estado.ultimo_envio_em is not None and ligado(s, tipo):
        zona, host = zona_e_host(s)
        texto = formato.formatar_resolvido(tipo, chave, estado.ocorrencias, estado.primeiro_em, agora, zona, host)
        _enfileirar(s, tipo, texto, agora)
    s.flush()


def avisar(s: Session, tipo: TipoAviso, chave: str, dados: Dados, agora: datetime) -> int | None:
    """Registra a ocorrência; devolve o id da mensagem enfileirada (None: desligado, só contou ou falhou)."""
    try:
        with s.begin_nested():
            return _avisar(s, tipo, chave, dados, agora)
    except Exception as erro:
        if _deixar_subir(erro):
            raise
        log.exception("aviso %s (%s) não registrado", tipo.value, chave)
        return None


def resolver(s: Session, tipo: TipoAviso, chave: str, agora: datetime) -> None:
    try:
        with s.begin_nested():
            _resolver(s, tipo, chave, agora)
    except Exception as erro:
        if _deixar_subir(erro):
            raise
        log.exception("resolução do aviso %s (%s) não registrada", tipo.value, chave)


def resolver_todos(s: Session, tipo: TipoAviso, agora: datetime) -> None:
    """Fecha todos os problemas abertos do tipo (ex.: todos os períodos sem orçamento da IA)."""
    try:
        with s.begin_nested():
            chaves = abertos(s, tipo)
    except Exception:
        log.exception("não consegui ler os avisos %s abertos", tipo.value)
        return
    for chave in chaves:
        resolver(s, tipo, chave, agora)


def lembrar_abertos(s: Session, agora: datetime) -> int:
    """Manda o lembrete dos bloqueios abertos que só esperam (`TIPOS_QUE_ESPERAM`), ligados em Configurações →
    Avisos, cujo último envio tem `lembrete` ou mais. Texto do catálogo (sem as linhas do evento original); não
    mexe em `ocorrencias`. Devolve quantos saíram. Nunca propaga exceção (menos `UrlProibida` no modo estrito)."""
    enviados = 0
    try:
        with s.begin_nested():
            chaves = [
                (TipoAviso(e.tipo), e.chave)
                for e in s.scalars(
                    select(EstadoAviso).where(
                        EstadoAviso.aberto.is_(True),
                        EstadoAviso.tipo.in_([t.value for t in TIPOS_QUE_ESPERAM]),
                    )
                )
            ]
    except Exception:
        log.exception("não consegui ler os avisos abertos para lembrar")
        return 0
    for tipo, chave in chaves:
        try:
            with s.begin_nested():
                enviados += _lembrar(s, tipo, chave, agora)
        except Exception as erro:
            if _deixar_subir(erro):
                raise
            log.exception("lembrete do aviso %s (%s) não registrado", tipo.value, chave)
    return enviados


def _lembrar(s: Session, tipo: TipoAviso, chave: str, agora: datetime) -> int:
    definicao = CATALOGO[tipo]
    estado = s.get(EstadoAviso, (tipo.value, chave), with_for_update=True, populate_existing=True)
    if estado is None or not estado.aberto or definicao.lembrete is None or not ligado(s, tipo):
        return 0
    if estado.ultimo_envio_em is not None and agora - estado.ultimo_envio_em < definicao.lembrete:
        return 0
    zona, host = zona_e_host(s)
    dados = Dados(titulo_extra=None if chave == CHAVE_GERAL else chave)
    texto = formato.formatar_lembrete(formato.aviso_de(tipo, dados, agora), estado.ocorrencias, estado.primeiro_em, zona, host)
    _enfileirar(s, tipo, texto, agora)
    estado.ultimo_envio_em = agora
    s.flush()
    return 1


def resolver_nao_enviada_sem_falhas(s: Session, agora: datetime) -> None:
    """Fecha "mensagem não enviada" quando não sobra falha definitiva na janela (sem contar os próprios avisos):
    todas reenviadas, descartadas ou velhas demais. Uma que saiu não basta: outro grupo pode seguir falhando."""
    try:
        with s.begin_nested():
            s.flush()
            estado = s.get(EstadoAviso, (TipoAviso.MENSAGEM_NAO_ENVIADA.value, CHAVE_GERAL))
            if estado is None or not estado.aberto:
                return
            sobra = any(
                not formato.eh_do_proprio_aviso(f.texto, TipoAviso.MENSAGEM_NAO_ENVIADA)
                for f in repo_msg.falhas_recentes(s, agora - repo_msg.JANELA_FALHAS, limite=1000)
            )
            if not sobra:
                _resolver(s, TipoAviso.MENSAGEM_NAO_ENVIADA, CHAVE_GERAL, agora)
    except Exception as erro:
        if _deixar_subir(erro):
            raise
        log.exception("resolução de mensagem não enviada não registrada")


def avisar_individual(
    s: Session, tipo: TipoAviso, numero: str, dados: Dados, agora: datetime, validade: timedelta = VALIDADE_INDIVIDUAL
) -> bool:
    """Mensagem só para o número da pessoa (tipos com grupo INDIVIDUAL, ex.: CODIGO_ACESSO). Não agrupa; vence em
    `validade` (vencida, o notificador não envia). Devolve True se enfileirou. Nunca propaga exceção (menos
    `UrlProibida` no modo estrito) e nunca loga o número."""
    if CATALOGO[tipo].grupo is not Destino.INDIVIDUAL:
        log.error("aviso %s não é individual: use avisar", tipo.value)
        return False
    try:
        with s.begin_nested():
            if not ligado(s, tipo):
                return False
            zona, host = zona_e_host(s)
            texto = formato.formatar(formato.aviso_de(tipo, dados, agora), zona, host)
            repo_msg.enfileirar(s, Destino.INDIVIDUAL.value, texto, agora, numero=numero, expira_em=agora + validade)
            return True
    except Exception as erro:
        if _deixar_subir(erro):
            raise
        log.exception("aviso individual %s não registrado", tipo.value)
        return False


class Avisador(Protocol):
    """O que os serviços recebem no lugar do antigo `Notificador`."""

    def avisar(self, tipo: TipoAviso, chave: str, dados: Dados) -> None: ...

    def avisar_em(self, s: Session, tipo: TipoAviso, chave: str, dados: Dados) -> int | None:
        """Como `avisar`, mas na transação de quem chama (o id da mensagem fica junto do que a gerou)."""
        ...

    def resolver(self, tipo: TipoAviso, chave: str) -> None: ...

    def resolver_todos(self, tipo: TipoAviso) -> None: ...


class AvisadorBanco:
    """`Avisador` de produção: cada chamada na própria transação. Nunca lança exceção (menos no modo estrito)."""

    def __init__(self, sessoes: sessionmaker[Session], relogio: Callable[[], datetime] | None = None):
        self._sessoes = sessoes
        self._relogio = relogio or agora_utc

    def _rodar(self, funcao, tipo: TipoAviso, *args) -> None:
        try:
            with self._sessoes() as s, s.begin():
                funcao(s, tipo, *args, self._relogio())
        except Exception as erro:
            if _deixar_subir(erro):
                raise
            log.exception("aviso %s não registrado", tipo.value)

    def avisar(self, tipo: TipoAviso, chave: str, dados: Dados) -> None:
        self._rodar(avisar, tipo, chave, dados)

    def avisar_em(self, s: Session, tipo: TipoAviso, chave: str, dados: Dados) -> int | None:
        return avisar(s, tipo, chave, dados, self._relogio())

    def resolver(self, tipo: TipoAviso, chave: str) -> None:
        self._rodar(resolver, tipo, chave)

    def resolver_todos(self, tipo: TipoAviso) -> None:
        self._rodar(resolver_todos, tipo)


def criar_avisador(sessoes: sessionmaker[Session]) -> AvisadorBanco:
    return AvisadorBanco(sessoes)
