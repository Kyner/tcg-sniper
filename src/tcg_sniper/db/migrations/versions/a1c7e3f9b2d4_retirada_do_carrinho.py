"""retirada do item de uma conferência: tentativas, última tentativa e "conferir à mão"

Revision ID: a1c7e3f9b2d4
Revises: b9e4c2a7d3f5
Create Date: 2026-10-17 23:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1c7e3f9b2d4"
down_revision: Union[str, Sequence[str], None] = "b9e4c2a7d3f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DATA = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column(
        "conferencia_checkout", sa.Column("retiradas_tentadas", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("conferencia_checkout", sa.Column("retirada_tentada_em", DATA, nullable=True))
    op.add_column("conferencia_checkout", sa.Column("conferir_a_mao_em", DATA, nullable=True))


def downgrade() -> None:
    for coluna in ("conferir_a_mao_em", "retirada_tentada_em", "retiradas_tentadas"):
        op.drop_column("conferencia_checkout", coluna)
