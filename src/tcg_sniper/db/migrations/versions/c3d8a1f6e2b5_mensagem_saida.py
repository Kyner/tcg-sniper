"""mensagem_saida, estado_notificador e validade das oportunidades

Revision ID: c3d8a1f6e2b5
Revises: b7c1e5f0a2d4
Create Date: 2026-10-15 18:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d8a1f6e2b5"
down_revision: Union[str, Sequence[str], None] = "b7c1e5f0a2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DATA = sa.DateTime(timezone=True)
STATUS = ("pendente", "enviada", "falha", "expirada", "descartada")


def upgrade() -> None:
    op.create_table(
        "mensagem_saida",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("destino", sa.Text(), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*STATUS, name="status_mensagem", native_enum=False, create_constraint=True, length=20),
            nullable=False,
        ),
        sa.Column("tentativas", sa.Integer(), server_default="0", nullable=False),
        sa.Column("proxima_tentativa_em", DATA, nullable=False),
        sa.Column("ultimo_erro", sa.Text(), nullable=True),
        sa.Column("ignorar_validade", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("criada_em", DATA, nullable=False),
        sa.Column("atualizado_em", DATA, nullable=False),
        sa.Column("enviada_em", DATA, nullable=True),
        sa.CheckConstraint("destino IN ('admin', 'oportunidades')", name="ck_mensagem_saida_destino"),
        sa.CheckConstraint("texto <> ''", name="ck_mensagem_saida_texto"),
        sa.CheckConstraint("tentativas >= 0", name="ck_mensagem_saida_tentativas"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mensagem_saida_fila", "mensagem_saida", ["status", "proxima_tentativa_em"])
    op.create_table(
        "estado_notificador",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("ultimo_ciclo_em", DATA, nullable=True),
        sa.CheckConstraint("id = 1", name="ck_estado_notificador_linha_unica"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO estado_notificador (id) VALUES (1)")
    op.add_column(
        "config_geral", sa.Column("validade_oportunidade_h", sa.Integer(), server_default="6", nullable=False)
    )
    op.create_check_constraint("ck_config_geral_validade", "config_geral", "validade_oportunidade_h BETWEEN 1 AND 48")


def downgrade() -> None:
    op.drop_constraint("ck_config_geral_validade", "config_geral", type_="check")
    op.drop_column("config_geral", "validade_oportunidade_h")
    op.drop_table("estado_notificador")
    op.drop_index("ix_mensagem_saida_fila", table_name="mensagem_saida")
    op.drop_table("mensagem_saida")
