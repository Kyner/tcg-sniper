"""config_geral e config_liga: o que saiu do .env para a tela de Configurações

Revision ID: b7c1e5f0a2d4
Revises: a4e2c7d91b30
Create Date: 2026-10-15 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c1e5f0a2d4"
down_revision: Union[str, Sequence[str], None] = "a4e2c7d91b30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DATA = sa.DateTime(timezone=True)
LIMITES_LIGA = {
    "coleta_jitter_min": (0, 180),
    "pausa_min_s": (0, 120),
    "pausa_max_s": (0, 120),
    "limite_falha_pct": (0, 100),
    "max_cliques": (1, 500),
}


def upgrade() -> None:
    # Sem INSERT: a linha é criada na primeira leitura com os valores do .env do serviço.
    op.create_table(
        "config_geral",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("host_publico", sa.Text(), nullable=False),
        sa.Column("fuso", sa.Text(), nullable=False),
        sa.Column("evolution_instancia", sa.Text(), nullable=True),
        sa.Column("whatsapp_grupo_admin", sa.Text(), nullable=True),
        sa.Column("whatsapp_grupo_oportunidades", sa.Text(), nullable=True),
        sa.Column("atualizado_em", DATA, nullable=False),
        sa.CheckConstraint("id = 1", name="ck_config_geral_linha_unica"),
        sa.CheckConstraint("host_publico <> ''", name="ck_config_geral_host"),
        sa.CheckConstraint("fuso <> ''", name="ck_config_geral_fuso"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "config_liga",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("coleta_hora", sa.Time(), nullable=False),
        sa.Column("coleta_jitter_min", sa.Integer(), nullable=False),
        sa.Column("pausa_min_s", sa.Float(), nullable=False),
        sa.Column("pausa_max_s", sa.Float(), nullable=False),
        sa.Column("limite_falha_pct", sa.Integer(), nullable=False),
        sa.Column("categorias", sa.Text(), nullable=False),
        sa.Column("url_listagem", sa.Text(), nullable=False),
        sa.Column("max_cliques", sa.Integer(), nullable=False),
        sa.Column("atualizado_em", DATA, nullable=False),
        sa.CheckConstraint("id = 1", name="ck_config_liga_linha_unica"),
        sa.CheckConstraint("position('{categ}' in url_listagem) > 0", name="ck_config_liga_url"),
        sa.CheckConstraint("categorias ~ '^[0-9]+(,[0-9]+)*$'", name="ck_config_liga_categorias"),
        sa.CheckConstraint("pausa_min_s <= pausa_max_s", name="ck_config_liga_pausas"),
        *(
            sa.CheckConstraint(f"{campo} BETWEEN {minimo} AND {maximo}", name=f"ck_config_liga_{campo}")
            for campo, (minimo, maximo) in LIMITES_LIGA.items()
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("config_liga")
    op.drop_table("config_geral")
