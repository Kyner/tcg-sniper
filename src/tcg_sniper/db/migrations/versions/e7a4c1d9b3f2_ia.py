"""casamento com IA: imagens, chamadas, avaliações, configuração e estado do casador

Revision ID: e7a4c1d9b3f2
Revises: d5e9b2c4a7f1
Create Date: 2026-10-16 15:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7a4c1d9b3f2"
down_revision: Union[str, Sequence[str], None] = "d5e9b2c4a7f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("produto_liga", sa.Column("imagem_url", sa.Text(), nullable=True))
    op.add_column("anuncio_amazon", sa.Column("imagem_url", sa.Text(), nullable=True))
    op.drop_constraint("ck_estado_coletor_linhas", "estado_coletor", type_="check")
    op.create_check_constraint("ck_estado_coletor_linhas", "estado_coletor", "id IN (1, 2, 3)")
    op.create_table(
        "chamada_ia",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalidade", sa.Text(), nullable=False),
        sa.Column("modelo", sa.Text(), nullable=False),
        sa.Column("tokens_entrada", sa.Integer(), nullable=False),
        sa.Column("tokens_saida", sa.Integer(), nullable=False),
        sa.Column("custo_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("erro", sa.Text(), nullable=True),
    )
    op.create_index("ix_chamada_ia_em", "chamada_ia", ["em"])
    op.create_table(
        "avaliacao_ia",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("anuncio_id", sa.Integer(), sa.ForeignKey("anuncio_amazon.id"), nullable=False),
        sa.Column("produto_id", sa.Integer(), sa.ForeignKey("produto_liga.id"), nullable=False),
        sa.Column("mesmo_produto", sa.Boolean(), nullable=False),
        sa.Column("confianca", sa.Integer(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("modelo", sa.Text(), nullable=False),
        sa.Column("assinatura", sa.Text(), nullable=False),
        sa.Column("sem_imagem", sa.Boolean(), nullable=False),
        sa.Column("avaliado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("aplicada_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chamada_id", sa.Integer(), sa.ForeignKey("chamada_ia.id"), nullable=True),
        sa.UniqueConstraint("anuncio_id", "produto_id", name="uq_avaliacao_ia_par"),
        sa.CheckConstraint("confianca BETWEEN 0 AND 100", name="ck_avaliacao_ia_confianca"),
    )
    op.create_table(
        "config_ia",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("ligado", sa.Boolean(), nullable=False),
        sa.Column("modelo", sa.Text(), nullable=False),
        sa.Column("esforco", sa.Text(), nullable=False),
        sa.Column("preco_entrada_milhao_usd", sa.Numeric(10, 4), nullable=False),
        sa.Column("preco_saida_milhao_usd", sa.Numeric(10, 4), nullable=False),
        sa.Column("teto_dia_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("teto_mes_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("max_chamadas_dia", sa.Integer(), nullable=False),
        sa.Column("intervalo_min", sa.Integer(), nullable=False),
        sa.Column("lote", sa.Integer(), nullable=False),
        sa.Column("automatico", sa.Boolean(), nullable=False),
        sa.Column("confianca_confirmar", sa.Integer(), nullable=False),
        sa.Column("confianca_ignorar", sa.Integer(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_config_ia_linha_unica"),
        sa.CheckConstraint("modelo <> ''", name="ck_config_ia_modelo"),
        sa.CheckConstraint("esforco IN ('minimal', 'low', 'medium', 'high')", name="ck_config_ia_esforco"),
        sa.CheckConstraint(
            "preco_entrada_milhao_usd >= 0 AND preco_saida_milhao_usd >= 0 AND teto_dia_usd >= 0 AND teto_mes_usd >= 0",
            name="ck_config_ia_valores",
        ),
        sa.CheckConstraint("max_chamadas_dia BETWEEN 0 AND 100000", name="ck_config_ia_max_chamadas_dia"),
        sa.CheckConstraint("intervalo_min BETWEEN 1 AND 1440", name="ck_config_ia_intervalo_min"),
        sa.CheckConstraint("lote BETWEEN 1 AND 500", name="ck_config_ia_lote"),
        sa.CheckConstraint("confianca_confirmar BETWEEN 0 AND 100", name="ck_config_ia_confianca_confirmar"),
        sa.CheckConstraint("confianca_ignorar BETWEEN 0 AND 100", name="ck_config_ia_confianca_ignorar"),
    )


def downgrade() -> None:
    op.drop_table("config_ia")
    op.drop_table("avaliacao_ia")
    op.drop_index("ix_chamada_ia_em", table_name="chamada_ia")
    op.drop_table("chamada_ia")
    op.execute("DELETE FROM estado_coletor WHERE id = 3")
    op.drop_constraint("ck_estado_coletor_linhas", "estado_coletor", type_="check")
    op.create_check_constraint("ck_estado_coletor_linhas", "estado_coletor", "id IN (1, 2)")
    op.drop_column("anuncio_amazon", "imagem_url")
    op.drop_column("produto_liga", "imagem_url")
