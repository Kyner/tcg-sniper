"""Consultas das telas da Amazon no admin."""

from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from tcg_sniper.consultas import casamentos
from tcg_sniper.consultas.casamentos import (
    LinhaAnuncio,
    LinhaProdutoCasamento,
    com_ofertas,
    selo_do_vendedor,
)
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import (
    AnuncioAmazon,
    Casamento,
    ConfigAmazon,
    PrecoAmazon,
    PrecoAtualAmazon,
    StatusCasamento,
    VendedorAmazon,
)
from tcg_sniper.oportunidades.motor import Regras

POR_PAGINA_CASAMENTOS = 20


def produtos_para_casar(
    s: Session,
    *,
    busca: str,
    categoria: str | None,
    situacao: str,
    com_preco: bool,
    desconto_min_pct: int,
    situacao_produto: str | None = None,
) -> list[LinhaProdutoCasamento]:
    """`consultas.casamentos.produtos_para_casar` na ordem de sempre do admin antigo: com pendente que seria
    oportunidade, depois com pendentes, depois os demais; por nome."""
    return casamentos.produtos_para_casar(
        s,
        busca=busca,
        categoria=categoria,
        situacao=situacao,
        com_preco=com_preco,
        desconto_min_pct=desconto_min_pct,
        situacao_produto=situacao_produto,
        ordem="legado",
    )


def amazon_do_produto(
    s: Session, produto_id: int, config: ConfigAmazon, agora: datetime | None = None
) -> list[LinhaAnuncio]:
    agora = agora or repo.agora_utc()
    consulta = (
        select(AnuncioAmazon, PrecoAtualAmazon, VendedorAmazon, Casamento)
        .join(
            Casamento,
            and_(
                Casamento.anuncio_id == AnuncioAmazon.id,
                Casamento.produto_id == produto_id,
                Casamento.status == StatusCasamento.CONFIRMADO,
            ),
        )
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAtualAmazon.vendedor_id)
        .order_by(PrecoAtualAmazon.preco.nulls_last(), AnuncioAmazon.id)
    )
    regras = Regras.de(config)
    linhas = [
        LinhaAnuncio(anuncio, atual, vendedor, False, *selo_do_vendedor(atual, vendedor, regras), casamento=par)
        for anuncio, atual, vendedor, par in s.execute(consulta)
    ]
    return com_ofertas(s, linhas, config, agora)


def historico_amazon(s: Session, produto_id: int, limite: int = 90) -> list[tuple[PrecoAmazon, str]]:
    consulta = (
        select(PrecoAmazon, AnuncioAmazon.asin)
        .join(AnuncioAmazon, AnuncioAmazon.id == PrecoAmazon.anuncio_id)
        .join(
            Casamento,
            and_(
                Casamento.anuncio_id == AnuncioAmazon.id,
                Casamento.produto_id == produto_id,
                Casamento.status == StatusCasamento.CONFIRMADO,
            ),
        )
        .order_by(PrecoAmazon.coletado_em.desc(), PrecoAmazon.id.desc())
        .limit(limite)
    )
    return [(preco, asin) for preco, asin in s.execute(consulta)]
