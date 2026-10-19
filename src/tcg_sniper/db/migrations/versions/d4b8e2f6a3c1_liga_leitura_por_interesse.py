"""LigaMagic: leitura por interesse e esfriar após desafio (esfriar_desafio_min e produtos_novos_dia em config_liga)

Revision ID: d4b8e2f6a3c1
Revises: c6a2f8e4d1b9
Create Date: 2026-10-19 23:00:00

Colunas com padrão (30 min e 100 produtos): a linha que já existe ganha os padrões. O downgrade tira as duas.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4b8e2f6a3c1"
down_revision: Union[str, Sequence[str], None] = "c6a2f8e4d1b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("config_liga", sa.Column("esfriar_desafio_min", sa.Integer(), server_default="30", nullable=False))
    op.add_column("config_liga", sa.Column("produtos_novos_dia", sa.Integer(), server_default="100", nullable=False))
    op.create_check_constraint(
        "ck_config_liga_esfriar_desafio_min", "config_liga", "esfriar_desafio_min BETWEEN 0 AND 240"
    )
    op.create_check_constraint(
        "ck_config_liga_produtos_novos_dia", "config_liga", "produtos_novos_dia BETWEEN 0 AND 2000"
    )


def downgrade() -> None:
    op.drop_constraint("ck_config_liga_produtos_novos_dia", "config_liga", type_="check")
    op.drop_constraint("ck_config_liga_esfriar_desafio_min", "config_liga", type_="check")
    op.drop_column("config_liga", "produtos_novos_dia")
    op.drop_column("config_liga", "esfriar_desafio_min")
