"""fim da oportunidade: motivo de encerramento, carência (em risco), menor preço, alertas, mensagem do alerta,
quando deixou de valer

Revision ID: e7c3a9d5b2f4
Revises: d4b8e2f6a3c1
Create Date: 2026-10-20 12:00:00

As oportunidades existentes recebem menor_preco = preco_amazon e alertas = 1; as abertas ficam com
alerta_sem_registro (o alerta delas saiu antes de o id da mensagem ser guardado). O downgrade tira tudo.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7c3a9d5b2f4"
down_revision: Union[str, Sequence[str], None] = "d4b8e2f6a3c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MOTIVOS = (
    "'casamento_desfeito', 'sem_leitura', 'liga_desatualizada', 'oferta_sumiu', 'vendedor', 'liga_caiu', "
    "'preco_subiu'"
)
DATA = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("oportunidade", sa.Column("motivo_encerramento", sa.Text(), nullable=True))
    op.add_column("oportunidade", sa.Column("em_risco_desde", DATA, nullable=True))
    op.add_column("oportunidade", sa.Column("motivo_risco", sa.Text(), nullable=True))
    op.add_column("oportunidade", sa.Column("menor_preco", sa.Numeric(10, 2), nullable=True))
    op.add_column("oportunidade", sa.Column("alertas", sa.Integer(), server_default="1", nullable=False))
    op.add_column(
        "oportunidade",
        sa.Column(
            "mensagem_alerta_id", sa.Integer(), sa.ForeignKey("mensagem_saida.id", ondelete="SET NULL"), nullable=True
        ),
    )
    op.add_column("oportunidade", sa.Column("encerramento_avisado_em", DATA, nullable=True))
    op.add_column("oportunidade", sa.Column("deixou_de_valer_em", DATA, nullable=True))
    op.add_column(
        "oportunidade", sa.Column("alerta_sem_registro", sa.Boolean(), server_default="false", nullable=False)
    )
    op.execute("UPDATE oportunidade SET menor_preco = preco_amazon")
    op.execute("UPDATE oportunidade SET alerta_sem_registro = true WHERE fechada_em IS NULL")
    op.alter_column("oportunidade", "menor_preco", nullable=False)
    op.create_check_constraint(
        "ck_oportunidade_motivo_encerramento", "oportunidade", f"motivo_encerramento IN ({MOTIVOS})"
    )
    op.create_check_constraint("ck_oportunidade_motivo_risco", "oportunidade", f"motivo_risco IN ({MOTIVOS})")
    op.add_column(
        "config_amazon", sa.Column("carencia_encerramento_min", sa.Integer(), server_default="30", nullable=False)
    )
    op.create_check_constraint(
        "ck_config_amazon_carencia_encerramento_min", "config_amazon", "carencia_encerramento_min BETWEEN 0 AND 240"
    )


def downgrade() -> None:
    op.drop_constraint("ck_config_amazon_carencia_encerramento_min", "config_amazon", type_="check")
    op.drop_column("config_amazon", "carencia_encerramento_min")
    op.drop_constraint("ck_oportunidade_motivo_risco", "oportunidade", type_="check")
    op.drop_constraint("ck_oportunidade_motivo_encerramento", "oportunidade", type_="check")
    for coluna in (
        "deixou_de_valer_em", "alerta_sem_registro", "encerramento_avisado_em", "mensagem_alerta_id", "alertas", "menor_preco",
        "motivo_risco", "em_risco_desde", "motivo_encerramento",
    ):
        op.drop_column("oportunidade", coluna)
