"""nome em inglês do produto da Liga e alternância do termo de busca da Amazon

Revision ID: d5e9b2c4a7f1
Revises: c3d8a1f6e2b5
Create Date: 2026-10-16 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e9b2c4a7f1"
down_revision: Union[str, Sequence[str], None] = "c3d8a1f6e2b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("produto_liga", sa.Column("nome_en", sa.Text(), nullable=True))
    op.add_column(
        "fila_amazon",
        sa.Column("ultimo_termo_en", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("fila_amazon", "ultimo_termo_en")
    op.drop_column("produto_liga", "nome_en")
