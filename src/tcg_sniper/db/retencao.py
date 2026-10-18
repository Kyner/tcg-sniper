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
from sqlalchemy.orm import Session

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
LOTE = 5000  # linhas por comando DELETE


def _em_lotes(s: Session, ids: Callable[[], Select], apagar: Callable[[list[int]], None]) -> int:
    total = 0
    while True:
        lote = list(s.scalars(ids().limit(LOTE)))
        if not lote:
            return total
        apagar(lote)
        total += len(lote)
        if len(lote) < LOTE:
            return total


def _limpar_chamadas(s: Session, agora: datetime) -> int:
    corte = agora - timedelta(days=DIAS_CHAMADA_IA)

    def apagar(ids: list[int]) -> None:
        s.execute(update(AvaliacaoIA).where(AvaliacaoIA.chamada_id.in_(ids)).values(chamada_id=None))
        s.execute(delete(ChamadaIA).where(ChamadaIA.id.in_(ids)))

    return _em_lotes(s, lambda: select(ChamadaIA.id).where(ChamadaIA.em < corte).order_by(ChamadaIA.id), apagar)


def _limpar_conferencias(s: Session, agora: datetime) -> int:
    corte = agora - timedelta(days=DIAS_CONFERENCIA_CHECKOUT)
    return _em_lotes(
        s,
        lambda: select(ConferenciaCheckout.id)
        .where(ConferenciaCheckout.em < corte, ConferenciaCheckout.item_removido.is_(True))
        .order_by(ConferenciaCheckout.id),
        lambda ids: s.execute(delete(ConferenciaCheckout).where(ConferenciaCheckout.id.in_(ids))),
    )


def _limpar_coletas(s: Session, agora: datetime) -> int:
    corte = agora - timedelta(days=DIAS_COLETA)
    com_preco = or_(
        exists().where(ResumoPreco.coleta_id == Coleta.id),
        exists().where(PrecoListagem.coleta_id == Coleta.id),
        exists().where(or_(PrecoAtualLiga.listagem_coleta_id == Coleta.id, PrecoAtualLiga.resumo_coleta_id == Coleta.id)),
    )
    return _em_lotes(
        s,
        lambda: select(Coleta.id)
        .where(Coleta.iniciada_em < corte, Coleta.status != StatusColeta.RODANDO, ~com_preco)
        .order_by(Coleta.id),
        lambda ids: s.execute(delete(Coleta).where(Coleta.id.in_(ids))),
    )


def limpar_historico(s: Session, agora: datetime) -> dict[str, int]:
    """Apaga o histórico vencido na transação de `s` e devolve quantas linhas saíram de cada tabela."""
    apagados = {
        "chamada_ia": _limpar_chamadas(s, agora),
        "conferencia_checkout": _limpar_conferencias(s, agora),
        "coleta": _limpar_coletas(s, agora),
    }
    s.flush()
    return apagados
