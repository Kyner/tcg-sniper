"""Estado de cada serviço da área de gestão: um vocabulário único e as palavras "parando…" e "iniciando…".

Tudo sai de consulta (a spec não pede sinal novo): o estado do painel vira um dos cinco estados únicos, e
os registros que cada serviço deixa (coletas, leituras, chamadas, mensagens, execuções) dizem se ele ainda
está mexendo depois de desligado ou se já deu sinal depois de ligado.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tcg_sniper.coletor_liga.agendador import TIPOS_LIGA
from tcg_sniper.config import Config
from tcg_sniper.consultas import historico, painel
from tcg_sniper.consultas.painel import SaudeServico
from tcg_sniper.db.models import (
    ChamadaIA,
    Coleta,
    ConferenciaCheckout,
    EstadoColetor,
    EstadoColetorTipo,
    ExecucaoManutencao,
    FilaAmazon,
    MensagemSaida,
    OfertaAmazon,
    ResumoPreco,
    StatusManutencao,
    TipoColeta,
)
from tcg_sniper.gestao.servicos import Servico

Estado = Literal["rodando", "esperando", "atrasado", "com_problema", "desligado"]

QUIETO = timedelta(minutes=2)  # desligado: sem registro novo por este tempo, o serviço parou de verdade
INICIANDO = timedelta(minutes=10)  # ligado: até este tempo sem registro novo depois de ligar é "iniciando…"
# Esperam o próprio horário (agenda, fila de mensagens): ligar não os faz começar em seguida, então não há "iniciando…".
SERVICOS_POR_HORARIO = frozenset({Servico.LIGA, Servico.WHATSAPP, Servico.BACKUP})

_POR_SITUACAO: dict[str, Estado] = {
    "rodando": "rodando",
    "ok": "esperando",
    "parcial": "atrasado",
    "falha": "com_problema",
    "pausado_desafio": "com_problema",
    "pausado": "desligado",
    "inativo": "desligado",
}

_TEXTO_SEM_CHAVE = "IA ligada, mas sem chave"


def estado_unico(saude: SaudeServico) -> Estado:
    """Situação do painel -> um dos cinco estados. Exceção: o casador ligado sem chave da IA é problema."""
    if saude.nome == "Casador (IA)" and saude.texto == _TEXTO_SEM_CHAVE:
        return "com_problema"
    return _POR_SITUACAO[saude.situacao]


def saude_por_servico(
    s: Session, agora: datetime, cfg_efetiva: Config, chave_ia: bool, resumo=None
) -> dict[Servico, SaudeServico]:
    """A saúde dos seis serviços, achada pelo id (o painel devolve lista, identificada pelo nome de tela)."""
    liga, busca, monitor, casador, whatsapp = painel.saude_servicos(s, agora, cfg_efetiva, chave_ia, resumo)
    return {
        Servico.LIGA: liga,
        Servico.AMAZON_BUSCA: busca,
        Servico.AMAZON_MONITOR: monitor,
        Servico.CASADOR: casador,
        Servico.WHATSAPP: whatsapp,
        Servico.BACKUP: painel.saude_backup(s, agora, cfg_efetiva),
    }


@dataclass(frozen=True)
class Transicao:
    tipo: Literal["parando", "parado", "iniciando"]
    desde: datetime | None


def _maior(*datas: datetime | None) -> datetime | None:
    existentes = [d for d in datas if d is not None]
    return max(existentes) if existentes else None


def _ultimo_de_coleta(s: Session, tipos) -> datetime | None:
    inicio, fim = s.execute(
        select(func.max(Coleta.iniciada_em), func.max(Coleta.finalizada_em)).where(Coleta.tipo.in_(tipos))
    ).one()
    return _maior(inicio, fim)


def ultimo_registro(s: Session, servico: Servico) -> datetime | None:
    """O registro mais recente que o serviço deixou (None se nunca deixou)."""
    match servico:
        case Servico.LIGA:
            return _maior(_ultimo_de_coleta(s, TIPOS_LIGA), s.scalar(select(func.max(ResumoPreco.coletado_em))))
        case Servico.AMAZON_BUSCA:
            return _maior(
                _ultimo_de_coleta(s, (TipoColeta.AMAZON,)), s.scalar(select(func.max(FilaAmazon.ultima_busca_em)))
            )
        case Servico.AMAZON_MONITOR:
            return _maior(
                s.scalar(select(func.max(OfertaAmazon.lida_em))), s.scalar(select(func.max(ConferenciaCheckout.em)))
            )
        case Servico.CASADOR:
            return s.scalar(select(func.max(ChamadaIA.em)))
        case Servico.WHATSAPP:
            return s.scalar(select(func.max(MensagemSaida.enviada_em)))
        case Servico.BACKUP:
            inicio, fim = s.execute(select(func.max(ExecucaoManutencao.inicio), func.max(ExecucaoManutencao.fim))).one()
            return _maior(inicio, fim)
    raise ValueError(f"serviço desconhecido: {servico}")


def em_andamento(s: Session, servico: Servico, agora: datetime) -> bool:
    """Há um ciclo aberto? Só Liga, busca e backup têm ciclo; os demais contam só com a regra dos 2 minutos."""
    match servico:
        case Servico.LIGA:
            return historico.coleta_em_andamento(s, TIPOS_LIGA)
        case Servico.AMAZON_BUSCA:
            return historico.coleta_em_andamento(s, (TipoColeta.AMAZON,))
        case Servico.BACKUP:
            return (
                s.scalar(
                    select(func.count()).select_from(ExecucaoManutencao).where(
                        ExecucaoManutencao.status == StatusManutencao.RODANDO
                    )
                )
                or 0
            ) > 0
    return False


def transicao(s: Session, servico: Servico, estado: EstadoColetor, agora: datetime) -> Transicao | None:
    """Palavra de transição. Desligado: "parando" enquanto há ciclo aberto ou registro dos últimos 2 min, depois
    "parado" desde o maior entre o desligamento e o último registro. Ligado: "iniciando" por até 10 min, se
    nada novo apareceu depois de ligar (nunca para os serviços por horário). Nos demais casos (inclusive
    desafio pendente), None."""
    ultimo = ultimo_registro(s, servico)
    if estado.estado is EstadoColetorTipo.PAUSADO:
        if em_andamento(s, servico, agora) or (ultimo is not None and agora - ultimo < QUIETO):
            return Transicao("parando", estado.atualizado_em)
        return Transicao("parado", _maior(estado.atualizado_em, ultimo))
    if estado.estado is EstadoColetorTipo.ATIVO and servico not in SERVICOS_POR_HORARIO:
        sem_sinal = ultimo is None or ultimo <= estado.atualizado_em
        if agora - estado.atualizado_em < INICIANDO and sem_sinal and not em_andamento(s, servico, agora):
            return Transicao("iniciando", estado.atualizado_em)
    return None
