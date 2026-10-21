"""Montagem de oportunidades, leituras da Amazon e preços da Liga direto no banco (cenários das consultas)."""

from datetime import timedelta
from decimal import Decimal

from fakes import T0

from tcg_sniper.db.models import (
    Coleta,
    Envio,
    Oportunidade,
    OrigemPreco,
    PrecoAmazon,
    PrecoAtualAmazon,
    PrecoListagem,
    ResumoPreco,
    StatusColeta,
    TipoColeta,
    VendedorAmazon,
)
from tcg_sniper.oportunidades.motor import desconto_pct


def criar_oportunidade(
    s, anuncio, produto, *, aberta_em, preco_alertado="700", preco_liga="1000", fechada_em=None, motivo=None,
    deixou_de_valer_em=None, em_risco_desde=None, motivo_risco=None, alertas=1,
) -> Oportunidade:
    preco, liga = Decimal(preco_alertado), Decimal(preco_liga)
    op = Oportunidade(
        anuncio_id=anuncio.id, produto_id=produto.id, preco_amazon=preco, preco_liga=liga,
        desconto_pct=desconto_pct(preco, liga), envio=Envio.AMAZON, aberta_em=aberta_em, alertada_em=aberta_em,
        preco_alertado=preco, menor_preco=preco, fechada_em=fechada_em, motivo_encerramento=motivo,
        deixou_de_valer_em=deixou_de_valer_em, em_risco_desde=em_risco_desde, motivo_risco=motivo_risco,
        alertas=alertas,
    )
    s.add(op)
    s.flush()
    return op


def criar_vendedor(s, seller_id="A1LOJA", pct="98", avaliacoes=500) -> VendedorAmazon:
    vendedor = VendedorAmazon(seller_id=seller_id, nome=f"Loja {seller_id}", pct_positivas=Decimal(pct),
                              num_avaliacoes=avaliacoes, avaliado_em=T0)
    s.add(vendedor)
    s.flush()
    return vendedor


def criar_leitura(s, anuncio, coletado_em, preco, envio=Envio.AMAZON, vendedor=None) -> PrecoAmazon:
    linha = PrecoAmazon(
        anuncio_id=anuncio.id, coletado_em=coletado_em, preco=None if preco is None else Decimal(preco),
        origem=OrigemPreco.OFERTAS, vendedor_id=vendedor.id if vendedor else None, envio=envio,
    )
    s.add(linha)
    s.flush()
    return linha


def criar_atual_amazon(s, anuncio, preco, envio=Envio.AMAZON, vendedor=None, coletado_em=T0) -> PrecoAtualAmazon:
    atual = PrecoAtualAmazon(
        anuncio_id=anuncio.id, preco=None if preco is None else Decimal(preco), origem=OrigemPreco.OFERTAS,
        vendedor_id=vendedor.id if vendedor else None, envio=envio, coletado_em=coletado_em,
    )
    s.add(atual)
    s.flush()
    return atual


def _coleta(s, tipo, quando) -> Coleta:
    coleta = Coleta(tipo=tipo, iniciada_em=quando, finalizada_em=quando + timedelta(minutes=5), status=StatusColeta.OK)
    s.add(coleta)
    s.flush()
    return coleta


def criar_listagem_liga(s, produto, preco, coletado_em) -> PrecoListagem:
    linha = PrecoListagem(produto_id=produto.id, coleta_id=_coleta(s, TipoColeta.LISTAGEM, coletado_em).id,
                          preco_a_partir=Decimal(preco), coletado_em=coletado_em)
    s.add(linha)
    s.flush()
    return linha


def criar_resumo_liga(s, produto, preco_medio, coletado_em, num_lojas=5) -> ResumoPreco:
    linha = ResumoPreco(produto_id=produto.id, coleta_id=_coleta(s, TipoColeta.PRODUTOS, coletado_em).id,
                        preco_medio=Decimal(preco_medio), num_lojas=num_lojas, coletado_em=coletado_em)
    s.add(linha)
    s.flush()
    return linha
