"""idioma do anúncio na avaliação da IA (regra de idioma revista em 2026-10-19)

Revision ID: b3e8d1f5c7a2
Revises: a9d4f2c6e8b1
Create Date: 2026-10-19 18:00:00

Coluna nova e vazia: as avaliações antigas ficam sem idioma (nada é reavaliado por causa dela).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3e8d1f5c7a2"
down_revision: Union[str, Sequence[str], None] = "a9d4f2c6e8b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("avaliacao_ia", sa.Column("idioma_anuncio", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_avaliacao_ia_idioma_anuncio", "avaliacao_ia", "idioma_anuncio IN ('pt', 'en', 'ja', 'outro', 'indefinido')"
    )


def downgrade() -> None:
    op.drop_constraint("ck_avaliacao_ia_idioma_anuncio", "avaliacao_ia", type_="check")
    op.drop_column("avaliacao_ia", "idioma_anuncio")
