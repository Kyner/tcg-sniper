"""amazon: opção do seletor de variações do anúncio

Revision ID: a4e2c7d91b30
Revises: 7d3f1a2b9c4e
Create Date: 2026-10-15 08:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4e2c7d91b30"
down_revision: Union[str, Sequence[str], None] = "7d3f1a2b9c4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("anuncio_amazon", sa.Column("variacao", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("anuncio_amazon", "variacao")
