"""monitor da Amazon: intervalo de leitura dos anúncios de produto esgotado na Liga (config_amazon)

Revision ID: c5e1a8d3f7b2
Revises: a1c4e7b9d2f6
Create Date: 2026-10-23 09:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5e1a8d3f7b2"
down_revision: Union[str, Sequence[str], None] = "a1c4e7b9d2f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("config_amazon", sa.Column("monitor_esgotado_dias", sa.Integer(), server_default="7", nullable=False))
    op.create_check_constraint(
        "ck_config_amazon_monitor_esgotado_dias", "config_amazon", "monitor_esgotado_dias BETWEEN 1 AND 30"
    )


def downgrade() -> None:
    op.drop_constraint("ck_config_amazon_monitor_esgotado_dias", "config_amazon", type_="check")
    op.drop_column("config_amazon", "monitor_esgotado_dias")
