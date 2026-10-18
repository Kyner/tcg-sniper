"""avisos do WhatsApp: estado_aviso (repetição), config_aviso (liga/desliga) e sinal_servico (vigia)

Revision ID: e4b7c2d9a1f6
Revises: d1a7f3c9e5b2
Create Date: 2026-10-18 20:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4b7c2d9a1f6"
down_revision: Union[str, Sequence[str], None] = "d1a7f3c9e5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "estado_aviso",
        sa.Column("tipo", sa.Text(), primary_key=True),
        sa.Column("chave", sa.Text(), primary_key=True),
        sa.Column("aberto", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("primeiro_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ultimo_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ultimo_envio_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ocorrencias", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("ocorrencias >= 0", name="ck_estado_aviso_ocorrencias"),
    )
    op.create_table(
        "config_aviso",
        sa.Column("tipo", sa.Text(), primary_key=True),
        sa.Column("ligado", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "sinal_servico",
        sa.Column("servico", sa.Text(), primary_key=True),
        sa.Column("ultimo_em", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sinal_servico")
    op.drop_table("config_aviso")
    op.drop_table("estado_aviso")
