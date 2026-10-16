"""estado do notificador em estado_coletor (id 4): pausar e retomar o envio pelo admin

Revision ID: f2b6d8a4c1e7
Revises: e7a4c1d9b3f2
Create Date: 2026-10-16 18:00:00

"""
from typing import Sequence, Union

from alembic import op

revision: str = "f2b6d8a4c1e7"
down_revision: Union[str, Sequence[str], None] = "e7a4c1d9b3f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_estado_coletor_linhas", "estado_coletor", type_="check")
    op.create_check_constraint("ck_estado_coletor_linhas", "estado_coletor", "id IN (1, 2, 3, 4)")
    op.execute(
        "INSERT INTO estado_coletor (id, coletor, estado, execucao_solicitada, atualizado_em) "
        "VALUES (4, 'notificador', 'ativo', false, now()) ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM estado_coletor WHERE id = 4")
    op.drop_constraint("ck_estado_coletor_linhas", "estado_coletor", type_="check")
    op.create_check_constraint("ck_estado_coletor_linhas", "estado_coletor", "id IN (1, 2, 3)")
