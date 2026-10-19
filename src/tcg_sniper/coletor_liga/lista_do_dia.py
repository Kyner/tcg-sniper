"""Lista do dia da etapa 2 da LigaMagic: quais produtos ativos abrir hoje.

Um produto entra uma vez só, no primeiro grupo em que cair: casados (par confirmado), com candidato
(par pendente), novos (sem nenhum resumo, os mais antigos primeiro, até o teto do dia) e o rodízio (os
demais com `id % 7` igual ao dia da semana, segunda = 0). O que já tem resumo gravado hoje (desde a
meia-noite no fuso de Configurações → Geral) sai da lista: um Retomar ou Rodar agora continua de onde
parou. Calculada do banco a cada job, sem tabela própria.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcg_sniper.db.models import Casamento, ProdutoLiga, ResumoPreco, StatusCasamento

DIAS_DO_RODIZIO = 7


@dataclass(frozen=True)
class ListaDoDia:
    produtos: tuple[tuple[int, str], ...]  # (id, url), na ordem de leitura
    casados: int
    candidatos: int
    novos: int
    rodizio: int

    def grupos(self) -> str:
        """Texto do resumo do job: "casados 52, candidatos 18, novos 100, rodízio 312"."""
        return f"casados {self.casados}, candidatos {self.candidatos}, novos {self.novos}, rodízio {self.rodizio}"


def inicio_do_dia(agora: datetime, fuso: ZoneInfo) -> datetime:
    """Meia-noite de hoje no fuso dado (não em UTC)."""
    return datetime.combine(agora.astimezone(fuso).date(), time(0), tzinfo=fuso)


def _com_par(s: Session, status: StatusCasamento) -> set[int]:
    return set(s.scalars(select(Casamento.produto_id).where(Casamento.status == status).distinct()))


def montar_lista(
    s: Session,
    agora: datetime,
    fuso: ZoneInfo,
    novos_por_dia: int,
    embaralhar: Callable[[list], None] = random.shuffle,
) -> ListaDoDia:
    """Antes do sorteio, casados, candidatos e rodízio ficam por id e os novos por (visto_primeiro_em, id).
    `embaralhar` é chamado uma vez por grupo. Um novo além do teto espera os próximos dias (não entra no
    rodízio)."""
    inicio = inicio_do_dia(agora, fuso)
    dia_da_semana = agora.astimezone(fuso).weekday()  # segunda = 0
    ativos = s.execute(
        select(ProdutoLiga.id, ProdutoLiga.url, ProdutoLiga.visto_primeiro_em)
        .where(ProdutoLiga.ativo.is_(True))
        .order_by(ProdutoLiga.id)
    ).all()
    lidos_hoje = set(s.scalars(select(ResumoPreco.produto_id).where(ResumoPreco.coletado_em >= inicio).distinct()))
    com_resumo = set(s.scalars(select(ResumoPreco.produto_id).distinct()))
    casados_ids = _com_par(s, StatusCasamento.CONFIRMADO)
    pendentes_ids = _com_par(s, StatusCasamento.PENDENTE)

    casados, candidatos, novos, rodizio = [], [], [], []
    for produto in ativos:
        if produto.id in lidos_hoje:
            continue
        if produto.id in casados_ids:
            casados.append(produto)
        elif produto.id in pendentes_ids:
            candidatos.append(produto)
        elif produto.id not in com_resumo:
            novos.append(produto)
        elif produto.id % DIAS_DO_RODIZIO == dia_da_semana:
            rodizio.append(produto)
    novos.sort(key=lambda p: (p.visto_primeiro_em, p.id))
    novos = novos[:novos_por_dia]

    grupos = [[(p.id, p.url) for p in grupo] for grupo in (casados, candidatos, novos, rodizio)]
    for grupo in grupos:
        embaralhar(grupo)
    return ListaDoDia(
        produtos=tuple(item for grupo in grupos for item in grupo),
        casados=len(grupos[0]),
        candidatos=len(grupos[1]),
        novos=len(grupos[2]),
        rodizio=len(grupos[3]),
    )
