"""índices por instante para a Atividade e para o último registro de cada serviço (fase 3B)

A linha do tempo lê cada tabela da mais recente para a mais antiga com keyset (`em <= cursor ...`) e o
estado dos serviços pede `max(...)` dessas colunas. Sem índice, as tabelas grandes (`oferta_amazon`,
`resumo_preco`) seriam lidas inteiras. Em `oferta_amazon` o índice leva também o anúncio: a leitura do
monitor é (instante, anúncio), e assim o agrupamento sai na ordem do índice e o LIMIT para cedo.

Revision ID: d6a2f8c4b1e9
Revises: e7b3d9f1a4c6
Create Date: 2026-10-25 15:00:00
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d6a2f8c4b1e9"
down_revision: Union[str, Sequence[str], None] = "e7b3d9f1a4c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDICES = (
    ("ix_coleta_iniciada_em", "coleta", ["iniciada_em"]),
    ("ix_oferta_amazon_lida_em", "oferta_amazon", ["lida_em", "anuncio_id"]),
    ("ix_conferencia_checkout_em", "conferencia_checkout", ["em"]),
    ("ix_mensagem_saida_criada_em", "mensagem_saida", ["criada_em"]),
    ("ix_mensagem_saida_enviada_em", "mensagem_saida", ["enviada_em"]),
    ("ix_resumo_preco_coletado_em", "resumo_preco", ["coletado_em"]),
    ("ix_execucao_manutencao_inicio", "execucao_manutencao", ["inicio"]),
    ("ix_estado_aviso_ultimo_em", "estado_aviso", ["ultimo_em"]),
)


def upgrade() -> None:
    for nome, tabela, colunas in INDICES:
        op.create_index(nome, tabela, colunas)


def downgrade() -> None:
    for nome, tabela, _ in reversed(INDICES):
        op.drop_index(nome, table_name=tabela)
