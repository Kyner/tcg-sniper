"""Quase oportunidades: anúncio casado (confirmado) de produto ativo, sem oportunidade aberta, elegível pelo motor
(vendedor aceito, Liga em dia), com desconto entre o piso e o mínimo, pela última leitura. Foto de agora."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcg_sniper.consultas.oportunidades import CENTAVO, AnuncioResumo, ProdutoResumo, produto_resumo
from tcg_sniper.db.models import (
    AnuncioAmazon,
    Casamento,
    MotivoEncerramento,
    Oportunidade,
    PrecoAtualAmazon,
    PrecoAtualLiga,
    ProdutoLiga,
    StatusCasamento,
    VendedorAmazon,
)
from tcg_sniper.oportunidades import motor
from tcg_sniper.oportunidades.montagem import ref_liga, vendedor_do_motor

CEM = Decimal(100)


@dataclass(frozen=True)
class QuaseLa:
    produto: ProdutoResumo
    anuncio: AnuncioResumo
    preco_amazon: Decimal
    preco_liga: Decimal
    desconto_pct: Decimal
    falta_reais: Decimal
    falta_pp: Decimal


def quase_la(
    s: Session, regras: motor.Regras, piso_pct: int, agora: datetime, limite: int | None = None,
    produto_id: int | None = None,
) -> list[QuaseLa]:
    aberta = select(Oportunidade.id).where(
        Oportunidade.anuncio_id == AnuncioAmazon.id, Oportunidade.fechada_em.is_(None)
    ).exists()
    consulta = (
        select(ProdutoLiga, AnuncioAmazon, PrecoAtualAmazon, PrecoAtualLiga, VendedorAmazon)
        .join(Casamento, Casamento.produto_id == ProdutoLiga.id)
        .join(AnuncioAmazon, AnuncioAmazon.id == Casamento.anuncio_id)
        .join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .join(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAtualAmazon.vendedor_id)
        .where(Casamento.status == StatusCasamento.CONFIRMADO, ProdutoLiga.ativo.is_(True), ~aberta)
    )
    if produto_id is not None:
        consulta = consulta.where(ProdutoLiga.id == produto_id)
    itens = []
    for produto, anuncio, atual, liga, vendedor in s.execute(consulta):
        leitura = motor.Leitura(atual.preco, atual.envio, vendedor_do_motor(vendedor))
        ref = ref_liga(liga)
        if motor.motivo_inelegivel(leitura, ref, regras, agora) is not MotivoEncerramento.PRECO_SUBIU:
            continue  # elegível de verdade (é oportunidade) ou não elegível (vendedor, Liga, sem preço)
        desconto = motor.desconto_pct(atual.preco, ref.preco_a_partir)
        if desconto < piso_pct:
            continue
        alvo = (ref.preco_a_partir * (CEM - regras.desconto_min_pct) / CEM).quantize(CENTAVO)
        itens.append(QuaseLa(
            produto=produto_resumo(produto), anuncio=AnuncioResumo(anuncio.titulo, anuncio.url, anuncio.imagem_chave),
            preco_amazon=atual.preco, preco_liga=ref.preco_a_partir, desconto_pct=desconto,
            falta_reais=(atual.preco - alvo).quantize(CENTAVO),
            falta_pp=(Decimal(regras.desconto_min_pct) - desconto).quantize(CENTAVO),
        ))
    itens.sort(key=lambda i: (i.falta_pp, i.produto.nome))
    return itens if limite is None else itens[:limite]
