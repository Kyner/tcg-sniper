"""serviço de manutenção: execuções (backup + limpeza), estado vivo e linha 5 em estado_coletor

Revision ID: d1a7f3c9e5b2
Revises: c8f2d6a1e4b9
Create Date: 2026-10-18 18:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1a7f3c9e5b2"
down_revision: Union[str, Sequence[str], None] = "c8f2d6a1e4b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATUS = ("rodando", "ok", "so_local", "erro", "interrompida")


def upgrade() -> None:
    op.create_table(
        "execucao_manutencao",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inicio", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fim", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(*STATUS, name="status_manutencao", native_enum=False, create_constraint=True, length=20),
            nullable=False,
        ),
        sa.Column("arquivo", sa.Text(), nullable=True),
        sa.Column("tamanho_bytes", sa.BigInteger(), nullable=True),
        sa.Column("enviado_r2", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("apagados", postgresql.JSONB(), nullable=True),
        sa.Column("erro", sa.Text(), nullable=True),
    )
    op.create_table(
        "estado_manutencao",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("ultimo_ciclo_em", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_estado_manutencao_linha_unica"),
    )
    op.execute("INSERT INTO estado_manutencao (id) VALUES (1)")
    op.drop_constraint("ck_estado_coletor_linhas", "estado_coletor", type_="check")
    op.create_check_constraint("ck_estado_coletor_linhas", "estado_coletor", "id IN (1, 2, 3, 4, 5)")
    op.execute(
        "INSERT INTO estado_coletor (id, coletor, estado, execucao_solicitada, atualizado_em) "
        "VALUES (5, 'manutencao', 'ativo', false, now()) ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM estado_coletor WHERE id = 5")
    op.drop_constraint("ck_estado_coletor_linhas", "estado_coletor", type_="check")
    op.create_check_constraint("ck_estado_coletor_linhas", "estado_coletor", "id IN (1, 2, 3, 4)")
    op.drop_table("estado_manutencao")
    op.drop_table("execucao_manutencao")
