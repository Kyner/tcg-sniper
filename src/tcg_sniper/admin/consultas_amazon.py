"""Consultas das telas da Amazon no admin."""

import difflib
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcg_sniper.admin.consultas import _escapar_like
from tcg_sniper.coletor_amazon.termo import termo_busca
from tcg_sniper.db.models import (
    AnuncioAmazon,
    Coleta,
    PrecoAtualAmazon,
    PrecoAtualLiga,
    ProdutoLiga,
    StatusCasamento,
    StatusColeta,
    TipoColeta,
)
from tcg_sniper.oportunidades.motor import atinge_desconto


def ciclo_atual(s: Session) -> Coleta | None:
    return s.scalar(
        select(Coleta)
        .where(Coleta.tipo == TipoColeta.AMAZON, Coleta.status == StatusColeta.RODANDO)
        .order_by(Coleta.id.desc())
        .limit(1)
    )


@dataclass(frozen=True)
class LinhaCasamento:
    anuncio: AnuncioAmazon
    preco: Decimal | None
    sugestao: ProdutoLiga | None
    preco_sugestao: Decimal | None
    alternativas: list[ProdutoLiga]
    candidato: bool  # o preço já está a pelo menos o desconto mínimo abaixo da sugestão


def _normalizar(texto: str) -> str:
    return termo_busca(texto).lower()


def pendentes(s: Session, desconto_min_pct: int, limite: int = 20) -> tuple[list[LinhaCasamento], int]:
    """Pendentes que seriam oportunidade primeiro; depois os demais, mais recentes primeiro.
    Cada linha traz até 3 outros produtos do catálogo com título parecido (difflib)."""
    consulta = (
        select(AnuncioAmazon, PrecoAtualAmazon.preco, ProdutoLiga, PrecoAtualLiga.preco_a_partir)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == AnuncioAmazon.produto_id)
        .where(AnuncioAmazon.status_casamento == StatusCasamento.PENDENTE)
    )
    linhas = [
        (anuncio, preco, sugestao, preco_liga, atinge_desconto(preco, preco_liga, desconto_min_pct))
        for anuncio, preco, sugestao, preco_liga in s.execute(consulta)
    ]
    linhas.sort(key=lambda linha: (not linha[4], -linha[0].visto_primeiro_em.timestamp(), linha[0].id))
    total = len(linhas)
    catalogo = list(s.scalars(select(ProdutoLiga).order_by(ProdutoLiga.id)))
    por_nome: dict[str, ProdutoLiga] = {}
    for produto in catalogo:
        por_nome.setdefault(_normalizar(produto.nome), produto)
    resultado = []
    for anuncio, preco, sugestao, preco_liga, candidato in linhas[:limite]:
        parecidos = difflib.get_close_matches(_normalizar(anuncio.titulo), list(por_nome), n=4, cutoff=0.3)
        alternativas = [por_nome[nome] for nome in parecidos if sugestao is None or por_nome[nome].id != sugestao.id]
        resultado.append(LinhaCasamento(anuncio, preco, sugestao, preco_liga, alternativas[:3], candidato))
    return resultado, total


def revisados(s: Session, limite: int = 100) -> list[tuple[AnuncioAmazon, ProdutoLiga | None]]:
    consulta = (
        select(AnuncioAmazon, ProdutoLiga)
        .outerjoin(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .where(AnuncioAmazon.status_casamento != StatusCasamento.PENDENTE)
        .order_by(AnuncioAmazon.revisado_em.desc().nulls_last(), AnuncioAmazon.id.desc())
        .limit(limite)
    )
    return [(anuncio, produto) for anuncio, produto in s.execute(consulta)]


def buscar_produtos(s: Session, busca: str, limite: int = 20) -> list[ProdutoLiga]:
    consulta = select(ProdutoLiga).order_by(ProdutoLiga.nome).limit(limite)
    if busca.strip():
        consulta = consulta.where(ProdutoLiga.nome.ilike(f"%{_escapar_like(busca.strip())}%", escape="\\"))
    return list(s.scalars(consulta))
