"""busca da Amazon separada do monitor: linha 6 (amazon_busca) em estado_coletor, tetos 90/180 e ciclo
de busca rodando fechado como interrompido

Revision ID: c6a2f8e4d1b9
Revises: b3e8d1f5c7a2
Create Date: 2026-10-19 21:00:00

Os tetos só descem (least): um valor do usuário menor que 90 (busca) ou 180 (monitor) fica. O downgrade
tira a linha 6 e não mexe nos tetos.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c6a2f8e4d1b9"
down_revision: Union[str, Sequence[str], None] = "b3e8d1f5c7a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_estado_coletor_linhas", "estado_coletor", type_="check")
    op.create_check_constraint("ck_estado_coletor_linhas", "estado_coletor", "id IN (1, 2, 3, 4, 5, 6)")
    op.execute(
        "INSERT INTO estado_coletor (id, coletor, estado, execucao_solicitada, atualizado_em) "
        "VALUES (6, 'amazon_busca', 'ativo', false, now()) ON CONFLICT (id) DO NOTHING"
    )
    op.execute(
        "UPDATE config_amazon SET max_buscas_hora = least(max_buscas_hora, 90), "
        "monitor_max_paginas_hora = least(monitor_max_paginas_hora, 180)"
    )
    # Igual a repositorio.marcar_interrompidas: o ciclo da busca aberto no deploy não volta.
    op.execute(
        "UPDATE coleta SET status = 'falha', erro = 'interrompida', finalizada_em = now() "
        "WHERE tipo = 'amazon' AND status = 'rodando'"
    )


def downgrade() -> None:
    op.execute("DELETE FROM estado_coletor WHERE id = 6")
    op.drop_constraint("ck_estado_coletor_linhas", "estado_coletor", type_="check")
    op.create_check_constraint("ck_estado_coletor_linhas", "estado_coletor", "id IN (1, 2, 3, 4, 5)")
