"""login do front: usuario, codigo_acesso, sessao, permissao_papel, pedido_codigo; mensagem individual

Revision ID: f8d2a6c4e1b3
Revises: e4b7c2d9a1f6
Create Date: 2026-10-18 23:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8d2a6c4e1b3"
down_revision: Union[str, Sequence[str], None] = "e4b7c2d9a1f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DATA = sa.DateTime(timezone=True)
PAPEIS = ("grupo", "operador", "admin")


def _papel() -> sa.Enum:
    return sa.Enum(*PAPEIS, name="papel", native_enum=False, create_constraint=True, length=20)


def upgrade() -> None:
    op.create_table(
        "usuario",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.Text(), nullable=False),
        sa.Column("numero", sa.Text(), nullable=False),
        sa.Column("papel", _papel(), nullable=False),
        sa.Column("ativo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("superadmin", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("criado_em", DATA, nullable=False),
        sa.CheckConstraint("nome <> ''", name="ck_usuario_nome"),
        sa.CheckConstraint("numero ~ '^[+][1-9][0-9]{9,14}$'", name="ck_usuario_numero"),
        sa.CheckConstraint("NOT superadmin OR (papel = 'admin' AND ativo)", name="ck_usuario_superadmin"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("numero", name="uq_usuario_numero"),
    )
    op.create_index(
        "uq_usuario_superadmin", "usuario", ["superadmin"], unique=True, postgresql_where=sa.text("superadmin")
    )
    op.create_table(
        "codigo_acesso",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("hash_codigo", sa.Text(), nullable=False),
        sa.Column("criado_em", DATA, nullable=False),
        sa.Column("expira_em", DATA, nullable=False),
        sa.Column("tentativas", sa.Integer(), server_default="0", nullable=False),
        sa.Column("usado_em", DATA, nullable=True),
        sa.CheckConstraint("tentativas >= 0", name="ck_codigo_acesso_tentativas"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_codigo_acesso_usuario", "codigo_acesso", ["usuario_id", "criado_em"])
    op.create_table(
        "sessao",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("hash_token", sa.Text(), nullable=False),
        sa.Column("aparelho", sa.Text(), nullable=False),
        sa.Column("criada_em", DATA, nullable=False),
        sa.Column("ultimo_uso_em", DATA, nullable=False),
        sa.Column("expira_em", DATA, nullable=False),
        sa.Column("encerrada_em", DATA, nullable=True),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hash_token", name="uq_sessao_hash_token"),
    )
    op.create_index("ix_sessao_usuario", "sessao", ["usuario_id"])
    op.create_table(
        "permissao_papel",
        sa.Column("papel", _papel(), nullable=False),
        sa.Column("permissao", sa.Text(), nullable=False),
        sa.Column("permitido", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("papel", "permissao"),
    )
    op.create_table(
        "pedido_codigo",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("em", DATA, nullable=False),
        sa.Column("numero_hash", sa.Text(), nullable=False),
        sa.Column("resultado", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "resultado IN ('aceito', 'limite_numero', 'limite_total')", name="ck_pedido_codigo_resultado"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pedido_codigo_em", "pedido_codigo", ["em"])
    op.create_index("ix_pedido_codigo_numero", "pedido_codigo", ["numero_hash", "em"])
    op.add_column("mensagem_saida", sa.Column("numero", sa.Text(), nullable=True))
    op.add_column("mensagem_saida", sa.Column("expira_em", DATA, nullable=True))
    op.drop_constraint("ck_mensagem_saida_destino", "mensagem_saida", type_="check")
    op.create_check_constraint(
        "ck_mensagem_saida_destino", "mensagem_saida", "destino IN ('admin', 'oportunidades', 'individual')"
    )
    op.create_check_constraint(
        "ck_mensagem_saida_numero", "mensagem_saida", "(destino = 'individual') = (numero IS NOT NULL)"
    )


def downgrade() -> None:
    op.execute("DELETE FROM mensagem_saida WHERE destino = 'individual'")
    op.drop_constraint("ck_mensagem_saida_numero", "mensagem_saida", type_="check")
    op.drop_constraint("ck_mensagem_saida_destino", "mensagem_saida", type_="check")
    op.create_check_constraint("ck_mensagem_saida_destino", "mensagem_saida", "destino IN ('admin', 'oportunidades')")
    op.drop_column("mensagem_saida", "expira_em")
    op.drop_column("mensagem_saida", "numero")
    op.drop_index("ix_pedido_codigo_numero", table_name="pedido_codigo")
    op.drop_index("ix_pedido_codigo_em", table_name="pedido_codigo")
    op.drop_table("pedido_codigo")
    op.drop_table("permissao_papel")
    op.drop_index("ix_sessao_usuario", table_name="sessao")
    op.drop_table("sessao")
    op.drop_index("ix_codigo_acesso_usuario", table_name="codigo_acesso")
    op.drop_table("codigo_acesso")
    op.drop_index("uq_usuario_superadmin", table_name="usuario")
    op.drop_table("usuario")
