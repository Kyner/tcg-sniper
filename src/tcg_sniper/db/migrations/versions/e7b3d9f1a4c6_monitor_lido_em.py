"""monitor da Amazon: instante da última leitura das ofertas pelo monitor (anuncio_amazon.monitor_lido_em)

Revision ID: e7b3d9f1a4c6
Revises: c5e1a8d3f7b2
Create Date: 2026-10-23 15:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7b3d9f1a4c6"
down_revision: Union[str, Sequence[str], None] = "c5e1a8d3f7b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("anuncio_amazon", sa.Column("monitor_lido_em", sa.DateTime(timezone=True), nullable=True))
    # A leitura mais recente do monitor que ainda dá para ver: as ofertas guardadas (30 dias) e o preço
    # atual quando ainda é das ofertas (cobre leitura sem nenhuma oferta, que não grava `oferta_amazon`).
    op.execute(
        """
        UPDATE anuncio_amazon a SET monitor_lido_em = x.lida_em
        FROM (
            SELECT anuncio_id, max(lida_em) AS lida_em FROM (
                SELECT anuncio_id, lida_em FROM oferta_amazon
                UNION ALL
                SELECT anuncio_id, coletado_em FROM preco_atual_amazon WHERE origem = 'ofertas'
            ) leituras GROUP BY anuncio_id
        ) x
        WHERE x.anuncio_id = a.id
        """
    )


def downgrade() -> None:
    op.drop_column("anuncio_amazon", "monitor_lido_em")
