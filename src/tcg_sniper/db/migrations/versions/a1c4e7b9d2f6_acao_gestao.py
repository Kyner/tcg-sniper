"""registro das ações de gestão (acao_gestao)

Revision ID: a1c4e7b9d2f6
Revises: f3b8d1c7a9e2
Create Date: 2026-10-22 09:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1c4e7b9d2f6"
down_revision: Union[str, Sequence[str], None] = "f3b8d1c7a9e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TIPOS = ("catalogo_lote", "catalogo_produto", "servico", "configuracoes")


def upgrade() -> None:
    op.create_table(
        "acao_gestao",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True),
        sa.Column("em", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "tipo", sa.Enum(*TIPOS, name="tipo_acao_gestao", native_enum=False, create_constraint=True, length=20),
            nullable=False,
        ),
        sa.Column("detalhe", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_acao_gestao_em", "acao_gestao", ["em"])


def downgrade() -> None:
    op.drop_index("ix_acao_gestao_em", table_name="acao_gestao")
    op.drop_table("acao_gestao")
