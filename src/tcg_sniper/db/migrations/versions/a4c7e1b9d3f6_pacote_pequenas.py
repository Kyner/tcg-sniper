"""colunas do pacote de pequenas correções

Espera da IA e da geração de termos após falhas, idioma do anúncio da Amazon, desligamento limpo dos
serviços, alerta enviado da oportunidade (e índice da mensagem do alerta), retomada após desafio do coletor,
falhas de página dos produtos da Liga e o motivo de encerramento `produto_desativado`.
Tudo anulável ou com padrão: nenhum dado existente é reescrito.

Revision ID: a4c7e1b9d3f6
Revises: d6a2f8c4b1e9
Create Date: 2026-10-27 10:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4c7e1b9d3f6"
down_revision: Union[str, Sequence[str], None] = "d6a2f8c4b1e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DATA = sa.DateTime(timezone=True)
MOTIVOS_ANTES = (
    "'casamento_desfeito', 'sem_leitura', 'liga_desatualizada', 'oferta_sumiu', 'vendedor', 'liga_caiu', "
    "'preco_subiu'"
)
MOTIVOS = MOTIVOS_ANTES + ", 'produto_desativado'"


def _motivos(lista: str) -> None:
    op.drop_constraint("ck_oportunidade_motivo_risco", "oportunidade", type_="check")
    op.drop_constraint("ck_oportunidade_motivo_encerramento", "oportunidade", type_="check")
    op.create_check_constraint(
        "ck_oportunidade_motivo_encerramento", "oportunidade", f"motivo_encerramento IN ({lista})"
    )
    op.create_check_constraint("ck_oportunidade_motivo_risco", "oportunidade", f"motivo_risco IN ({lista})")


def upgrade() -> None:
    op.add_column("casamento", sa.Column("ia_falhas", sa.Integer(), server_default="0", nullable=False))
    op.add_column("casamento", sa.Column("ia_espera_ate", DATA, nullable=True))
    op.add_column("casamento", sa.Column("ia_falha_assinatura", sa.Text(), nullable=True))
    op.add_column("fila_amazon", sa.Column("termos_falhas", sa.Integer(), server_default="0", nullable=False))
    op.add_column("fila_amazon", sa.Column("termos_espera_ate", DATA, nullable=True))
    op.add_column("anuncio_amazon", sa.Column("idioma", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_anuncio_amazon_idioma", "anuncio_amazon", "idioma IN ('pt', 'en', 'ja', 'outro', 'indefinido')"
    )
    op.add_column("sinal_servico", sa.Column("encerrado_em", DATA, nullable=True))
    op.add_column("oportunidade", sa.Column("alerta_enviado", sa.Boolean(), server_default="false", nullable=False))
    op.create_index("ix_oportunidade_mensagem_alerta_id", "oportunidade", ["mensagem_alerta_id"])
    op.add_column("estado_coletor", sa.Column("retomado_desafio_em", DATA, nullable=True))
    op.add_column("produto_liga", sa.Column("falhas_pagina", sa.Integer(), server_default="0", nullable=False))
    _motivos(MOTIVOS)


def downgrade() -> None:
    # O motivo novo não existe na versão anterior: as linhas que o usam voltam ao motivo mais próximo.
    for coluna in ("motivo_encerramento", "motivo_risco"):
        op.execute(f"UPDATE oportunidade SET {coluna} = 'casamento_desfeito' WHERE {coluna} = 'produto_desativado'")
    _motivos(MOTIVOS_ANTES)
    op.drop_column("produto_liga", "falhas_pagina")
    op.drop_column("estado_coletor", "retomado_desafio_em")
    op.drop_index("ix_oportunidade_mensagem_alerta_id", table_name="oportunidade")
    op.drop_column("oportunidade", "alerta_enviado")
    op.drop_column("sinal_servico", "encerrado_em")
    op.drop_constraint("ck_anuncio_amazon_idioma", "anuncio_amazon", type_="check")
    op.drop_column("anuncio_amazon", "idioma")
    op.drop_column("fila_amazon", "termos_espera_ate")
    op.drop_column("fila_amazon", "termos_falhas")
    op.drop_column("casamento", "ia_falha_assinatura")
    op.drop_column("casamento", "ia_espera_ate")
    op.drop_column("casamento", "ia_falhas")
