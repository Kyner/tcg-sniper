"""Limpeza do histórico antigo (serviço `manutencao`, depois do backup do dia).

Regras aprovadas pelo usuário em 2026-10-18:
- preços nunca são apagados (`preco_amazon`, `resumo_preco`, `preco_listagem`, `preco_atual_*`),
  nem `avaliacao_ia` e `oportunidade`;
- `chamada_ia`: mais de 90 dias. A avaliação que aponta para a chamada fica, com `chamada_id` NULL;
- `conferencia_checkout`: mais de 180 dias, menos as que ainda podem ter deixado item no carrinho
  (`item_removido` falso: a retirada automática ou o "conferir à mão" ainda dependem delas);
- `coleta`: mais de 180 dias e só as que nenhum preço referencia (rodadas que falharam ou vieram
  vazias, e os ciclos da Amazon, que não gravam `coleta_id` nos preços). Nunca uma `rodando`.

As limpezas que já existiam continuam onde estão: `oferta_amazon` (30 dias, coletor-amazon) e
`mensagem_saida` (30 dias, notificador).
"""

from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import Select, delete, exists, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.db.models import (
    AvaliacaoIA,
    ChamadaIA,
    Coleta,
    ConferenciaCheckout,
    PrecoAtualLiga,
    PrecoListagem,
    ResumoPreco,
    StatusColeta,
)

DIAS_CHAMADA_IA = 90
DIAS_CONFERENCIA_CHECKOUT = 180
DIAS_COLETA = 180
LOTE = 1000  # linhas por lote; cada lote é uma transação curta (não segura o casador nem o coletor)

Apagar = Callable[[Session, list[int]], None]


def _em_lotes(sessoes: sessionmaker[Session], ids: Callable[[], Select], apagar: Apagar) -> int:
    total = 0
    while True:
        with sessoes() as s, s.begin():
            lote = list(s.scalars(ids().limit(LOTE)))
            if lote:
                apagar(s, lote)
        total += len(lote)
        if len(lote) < LOTE:
            return total


def _limpar_chamadas(sessoes: sessionmaker[Session], agora: datetime) -> int:
    corte = agora - timedelta(days=DIAS_CHAMADA_IA)

    def apagar(s: Session, ids: list[int]) -> None:
        s.execute(update(AvaliacaoIA).where(AvaliacaoIA.chamada_id.in_(ids)).values(chamada_id=None))
        s.execute(delete(ChamadaIA).where(ChamadaIA.id.in_(ids)))

    return _em_lotes(sessoes, lambda: select(ChamadaIA.id).where(ChamadaIA.em < corte).order_by(ChamadaIA.id), apagar)


def _limpar_conferencias(sessoes: sessionmaker[Session], agora: datetime) -> int:
    corte = agora - timedelta(days=DIAS_CONFERENCIA_CHECKOUT)
    return _em_lotes(
        sessoes,
        lambda: select(ConferenciaCheckout.id)
        .where(ConferenciaCheckout.em < corte, ConferenciaCheckout.item_removido.is_(True))
        .order_by(ConferenciaCheckout.id),
        lambda s, ids: s.execute(delete(ConferenciaCheckout).where(ConferenciaCheckout.id.in_(ids))),
    )


def _limpar_coletas(sessoes: sessionmaker[Session], agora: datetime) -> int:
    corte = agora - timedelta(days=DIAS_COLETA)
    com_preco = or_(
        exists().where(ResumoPreco.coleta_id == Coleta.id),
        exists().where(PrecoListagem.coleta_id == Coleta.id),
        exists().where(PrecoAtualLiga.listagem_coleta_id == Coleta.id),
        exists().where(PrecoAtualLiga.resumo_coleta_id == Coleta.id),
    )
    return _em_lotes(
        sessoes,
        lambda: select(Coleta.id)
        .where(Coleta.iniciada_em < corte, Coleta.status != StatusColeta.RODANDO, ~com_preco)
        .order_by(Coleta.id),
        lambda s, ids: s.execute(delete(Coleta).where(Coleta.id.in_(ids))),
    )


def limpar_historico(sessoes: sessionmaker[Session], agora: datetime) -> dict[str, int]:
    """Apaga o histórico vencido, um lote por transação, e devolve quantas linhas saíram de cada tabela."""
    return {
        "chamada_ia": _limpar_chamadas(sessoes, agora),
        "conferencia_checkout": _limpar_conferencias(sessoes, agora),
        "coleta": _limpar_coletas(sessoes, agora),
    }
