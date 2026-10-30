"""Lista do dia da etapa 2 da LigaMagic: quais produtos ativos abrir hoje.

Um produto entra uma vez só, no primeiro grupo em que cair: casados (par confirmado), com candidato
(par pendente), novos (sem nenhum resumo, os mais antigos primeiro, até o teto do dia), os atrasados
do rodízio e o rodízio (os demais com `id % 7` igual ao dia da semana, segunda = 0). O que já tem resumo
gravado hoje (desde a meia-noite no fuso de Configurações → Geral) sai da lista: um Retomar ou Rodar
agora continua de onde parou. Calculada do banco a cada job, sem tabela própria.

Atrasado: produto do rodízio de outro dia cujo último resumo é de antes da semana (o dia dele foi
cortado por um desafio): entra nos dias seguintes até ser lido, o mais antigo primeiro, até
`ATRASADOS_POR_DIA` por dia. Sem resumo
nenhum ou com 3 falhas seguidas da página, fica só no dia dele (não é tentado todo dia).
"""

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tcg_sniper.db.models import Casamento, ProdutoLiga, ResumoPreco, StatusCasamento

DIAS_DO_RODIZIO = 7
# Falhas seguidas da página: o produto novo que chega a isto sai dos "novos do dia" e fica só no rodízio.
FALHAS_PARA_SAIR_DOS_NOVOS = 3
# Teto de atrasados por dia (vale entre execuções do mesmo dia, como o de novos): um acúmulo grande (dias
# sem coleta) é lido aos poucos, sem estourar o volume do dia e provocar o Cloudflare.
ATRASADOS_POR_DIA = 100


@dataclass(frozen=True)
class ListaDoDia:
    produtos: tuple[tuple[int, str], ...]  # (id, url), na ordem de leitura
    casados: int
    candidatos: int
    novos: int
    rodizio: int
    atrasados: int = 0

    def grupos(self) -> str:
        """Texto do resumo do job: "casados 52, candidatos 18, novos 100, rodízio 312" (e ", atrasados 9"
        quando houver)."""
        texto = f"casados {self.casados}, candidatos {self.candidatos}, novos {self.novos}, rodízio {self.rodizio}"
        return f"{texto}, atrasados {self.atrasados}" if self.atrasados else texto


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
        select(ProdutoLiga.id, ProdutoLiga.url, ProdutoLiga.visto_primeiro_em, ProdutoLiga.falhas_pagina)
        .where(ProdutoLiga.ativo.is_(True))
        .order_by(ProdutoLiga.id)
    ).all()
    lidos_hoje = set(s.scalars(select(ResumoPreco.produto_id).where(ResumoPreco.coletado_em >= inicio).distinct()))
    ultimo_resumo = dict(
        s.execute(
            select(ResumoPreco.produto_id, func.max(ResumoPreco.coletado_em)).group_by(ResumoPreco.produto_id)
        ).all()
    )
    com_resumo = set(ultimo_resumo)
    # Lido antes disto e fora do dia dele no rodízio: atrasado (a semana do rodízio passou sem leitura).
    limite_atraso = inicio - timedelta(days=DIAS_DO_RODIZIO - 1)
    casados_ids = _com_par(s, StatusCasamento.CONFIRMADO)
    pendentes_ids = _com_par(s, StatusCasamento.PENDENTE)
    # Novos que já tiveram o primeiro resumo hoje contam no teto do dia (vale entre execuções do mesmo dia).
    # Casados e candidatos lidos hoje foram lidos pelos grupos deles, não como novos: ficam de fora.
    primeiros_hoje = set(
        s.scalars(
            select(ResumoPreco.produto_id)
            .group_by(ResumoPreco.produto_id)
            .having(func.min(ResumoPreco.coletado_em) >= inicio)
        )
    )
    novos_de_hoje = len(primeiros_hoje - casados_ids - pendentes_ids)
    # Lidos hoje fora de casados, candidatos, novos e do rodízio do dia: foram atrasados (gastam o teto).
    atrasados_de_hoje = sum(
        1
        for pid in lidos_hoje - casados_ids - pendentes_ids - primeiros_hoje
        if pid % DIAS_DO_RODIZIO != dia_da_semana
    )

    casados, candidatos, novos, atrasados, rodizio = [], [], [], [], []
    for produto in ativos:
        if produto.id in lidos_hoje:
            continue
        if produto.id in casados_ids:
            casados.append(produto)
        elif produto.id in pendentes_ids:
            candidatos.append(produto)
        elif produto.id not in com_resumo and produto.falhas_pagina < FALHAS_PARA_SAIR_DOS_NOVOS:
            novos.append(produto)
        elif produto.id % DIAS_DO_RODIZIO == dia_da_semana:
            rodizio.append(produto)
        elif (
            produto.id in com_resumo
            and ultimo_resumo[produto.id] < limite_atraso
            and produto.falhas_pagina < FALHAS_PARA_SAIR_DOS_NOVOS
        ):
            atrasados.append(produto)
    novos.sort(key=lambda p: (p.visto_primeiro_em, p.id))
    novos = novos[: max(novos_por_dia - novos_de_hoje, 0)]
    atrasados.sort(key=lambda p: (ultimo_resumo[p.id], p.id))
    atrasados = atrasados[: max(ATRASADOS_POR_DIA - atrasados_de_hoje, 0)]

    grupos = [[(p.id, p.url) for p in grupo] for grupo in (casados, candidatos, novos, rodizio)]
    for grupo in grupos:
        embaralhar(grupo)
    em_atraso = [(p.id, p.url) for p in atrasados]  # sem sorteio: o mais antigo primeiro
    return ListaDoDia(
        produtos=tuple(item for grupo in (*grupos[:3], em_atraso, grupos[3]) for item in grupo),
        casados=len(grupos[0]),
        candidatos=len(grupos[1]),
        novos=len(grupos[2]),
        rodizio=len(grupos[3]),
        atrasados=len(em_atraso),
    )
