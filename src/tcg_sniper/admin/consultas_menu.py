"""Contadores do menu lateral, lidos uma vez por requisição."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from tcg_sniper.db.models import (
    AnuncioAmazon,
    MensagemSaida,
    Oportunidade,
    ProdutoLiga,
    StatusCasamento,
    StatusMensagem,
)

PENDENTE_PARADA = timedelta(minutes=30)


@dataclass(frozen=True)
class ContadoresMenu:
    casamentos: int  # produtos ativos com anúncio pendente
    ofertas: int  # oportunidades abertas
    mensagens: int  # falhas + pendentes paradas há mais de 30 min


def contadores_menu(s: Session, agora: datetime) -> ContadoresMenu:
    casamentos = s.scalar(
        select(func.count(func.distinct(AnuncioAmazon.produto_id)))
        .join(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .where(AnuncioAmazon.status_casamento == StatusCasamento.PENDENTE, ProdutoLiga.ativo.is_(True))
    )
    ofertas = s.scalar(select(func.count()).select_from(Oportunidade).where(Oportunidade.fechada_em.is_(None)))
    mensagens = s.scalar(
        select(func.count())
        .select_from(MensagemSaida)
        .where(
            or_(
                MensagemSaida.status == StatusMensagem.FALHA,
                and_(MensagemSaida.status == StatusMensagem.PENDENTE, MensagemSaida.criada_em < agora - PENDENTE_PARADA),
            )
        )
    )
    return ContadoresMenu(casamentos or 0, ofertas or 0, mensagens or 0)
