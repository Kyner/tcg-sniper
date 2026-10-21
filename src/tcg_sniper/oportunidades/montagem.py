"""Dados do banco no formato do motor; usados pelo monitor e pelas consultas da área de negócio, para a regra
de elegibilidade ser uma só."""

from tcg_sniper.db.models import PrecoAtualLiga, VendedorAmazon
from tcg_sniper.oportunidades import motor


def vendedor_do_motor(vendedor: VendedorAmazon | None) -> motor.Vendedor | None:
    if vendedor is None:
        return None
    return motor.Vendedor(vendedor.nome, vendedor.pct_positivas, vendedor.num_avaliacoes)


def ref_liga(liga: PrecoAtualLiga | None) -> motor.RefLiga:
    return motor.RefLiga(
        preco_a_partir=liga.preco_a_partir if liga else None,
        listagem_em=liga.listagem_em if liga else None,
        num_lojas=liga.num_lojas if liga else None,
        preco_medio=liga.preco_medio if liga else None,
    )
