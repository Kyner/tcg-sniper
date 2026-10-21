"""quase oportunidade: piso do desconto (config_amazon), índice do histórico da Amazon e colunas da cópia das imagens

Revision ID: f3b8d1c7a9e2
Revises: e7c3a9d5b2f4
Create Date: 2026-10-21 09:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3b8d1c7a9e2"
down_revision: Union[str, Sequence[str], None] = "e7c3a9d5b2f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "config_amazon", sa.Column("quase_oportunidade_min_pct", sa.Integer(), server_default="10", nullable=False)
    )
    op.create_check_constraint(
        "ck_config_amazon_quase_oportunidade_min_pct", "config_amazon", "quase_oportunidade_min_pct BETWEEN 0 AND 100"
    )
    op.create_index("ix_preco_amazon_anuncio_coletado", "preco_amazon", ["anuncio_id", "coletado_em"])
    for tabela in ("produto_liga", "anuncio_amazon"):
        op.add_column(tabela, sa.Column("imagem_chave", sa.Text(), nullable=True))
        op.add_column(tabela, sa.Column("imagem_origem", sa.Text(), nullable=True))


def downgrade() -> None:
    for tabela in ("produto_liga", "anuncio_amazon"):
        op.drop_column(tabela, "imagem_origem")
        op.drop_column(tabela, "imagem_chave")
    op.drop_index("ix_preco_amazon_anuncio_coletado", table_name="preco_amazon")
    op.drop_constraint("ck_config_amazon_quase_oportunidade_min_pct", "config_amazon", type_="check")
    op.drop_column("config_amazon", "quase_oportunidade_min_pct")
