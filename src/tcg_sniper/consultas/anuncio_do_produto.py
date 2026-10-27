"""O anúncio da Amazon que representa um produto: entre os confirmados, o mais barato com preço agora; se nenhum tem
preço, o de leitura mais recente (sem leitura, o de id mais alto), marcado `sem_preco`. Serve ao link "Ver na Amazon"."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tcg_sniper.db.models import AnuncioAmazon, Casamento, PrecoAtualAmazon, StatusCasamento


@dataclass(frozen=True)
class AnuncioDoProduto:
    titulo: str
    url: str
    imagem_chave: str | None
    sem_preco: bool
    anuncios_casados: int


def anuncio_do_produto(s: Session, produto_id: int) -> AnuncioDoProduto | None:
    base = (
        select(AnuncioAmazon, PrecoAtualAmazon.preco)
        .join(Casamento, Casamento.anuncio_id == AnuncioAmazon.id)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .where(Casamento.produto_id == produto_id, Casamento.status == StatusCasamento.CONFIRMADO)
    )
    total = s.scalar(select(func.count()).select_from(base.subquery())) or 0
    if total == 0:
        return None
    com_preco = s.execute(
        base.where(PrecoAtualAmazon.preco.is_not(None)).order_by(PrecoAtualAmazon.preco, AnuncioAmazon.id).limit(1)
    ).first()
    if com_preco is not None:
        a = com_preco[0]
        return AnuncioDoProduto(a.titulo, a.url, a.imagem_chave, False, total)
    a = s.execute(
        base.order_by(PrecoAtualAmazon.coletado_em.desc().nulls_last(), AnuncioAmazon.id.desc()).limit(1)
    ).first()[0]
    return AnuncioDoProduto(a.titulo, a.url, a.imagem_chave, True, total)
