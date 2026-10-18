"""oportunidade: o último aviso saiu com o preço conferido no checkout

Revision ID: c8f2d6a1e4b9
Revises: a1c7e3f9b2d4
Create Date: 2026-10-18 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8f2d6a1e4b9"
down_revision: Union[str, Sequence[str], None] = "a1c7e3f9b2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "oportunidade", sa.Column("alerta_conferido", sa.Boolean(), nullable=False, server_default=sa.false())
    )


def downgrade() -> None:
    op.drop_column("oportunidade", "alerta_conferido")
