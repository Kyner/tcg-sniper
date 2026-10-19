"""casamento por par: tabela casamento (fonte única), termo_busca e colunas da busca alternativa na fila

Revision ID: a9d4f2c6e8b1
Revises: f8d2a6c4e1b3
Create Date: 2026-10-19 12:00:00

Tudo numa transação (o env.py roda as migrações numa só): cria `casamento`, copia um par por anúncio com
produto, confere que nenhum anúncio ficou com dois confirmados (senão aborta sem mudar nada) e cria o
índice único parcial. Depois remove as colunas antigas do casamento em `anuncio_amazon` e
`fila_amazon.ultimo_termo_en`; o downgrade as refaz a partir dos pares.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9d4f2c6e8b1"
down_revision: Union[str, Sequence[str], None] = "f8d2a6c4e1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DATA = sa.DateTime(timezone=True)
STATUS = ("pendente", "confirmado", "ignorado")
ORIGENS = ("manual", "sugerido_ia", "automatico_ia", "outro_confirmado")

COPIAR_PARES = """
INSERT INTO casamento (anuncio_id, produto_id, status, origem, revisado_em, visto_primeiro_em, visto_ultimo_em, reavaliar)
SELECT id, produto_id, status_casamento, origem_casamento, revisado_em, visto_primeiro_em, visto_ultimo_em, false
FROM anuncio_amazon
WHERE produto_id IS NOT NULL
"""

# Downgrade: por anúncio, o par confirmado ou, sem confirmado, o mais antigo; outro_confirmado não existia.
REFAZER_ANUNCIO = """
UPDATE anuncio_amazon a
SET produto_id = p.produto_id,
    status_casamento = p.status,
    origem_casamento = CASE WHEN p.origem = 'outro_confirmado' THEN 'manual' ELSE p.origem END,
    revisado_em = p.revisado_em
FROM (
    SELECT DISTINCT ON (anuncio_id) anuncio_id, produto_id, status, origem, revisado_em
    FROM casamento
    ORDER BY anuncio_id, (status = 'confirmado') DESC, visto_primeiro_em, produto_id
) p
WHERE p.anuncio_id = a.id
"""


def _enum(nome: str, *valores: str) -> sa.Enum:
    return sa.Enum(*valores, name=nome, native_enum=False, create_constraint=True, length=20)


def conferir_um_confirmado_por_anuncio(bind) -> None:
    """Aborta (a transação inteira volta) se algum anúncio ficou com mais de um par confirmado."""
    repetidos = bind.execute(
        sa.text(
            "SELECT anuncio_id FROM casamento WHERE status = 'confirmado' "
            "GROUP BY anuncio_id HAVING count(*) > 1 ORDER BY anuncio_id LIMIT 20"
        )
    ).scalars().all()
    if repetidos:
        raise RuntimeError(
            "migração casamento por par abortada: anúncios com mais de um casamento confirmado "
            f"(ids {', '.join(map(str, repetidos))}); nada foi mudado"
        )


def upgrade() -> None:
    op.create_table(
        "casamento",
        sa.Column("anuncio_id", sa.Integer(), nullable=False),
        sa.Column("produto_id", sa.Integer(), nullable=False),
        sa.Column("status", _enum("status_casamento", *STATUS), nullable=False),
        sa.Column("origem", _enum("origem_casamento", *ORIGENS), nullable=True),
        sa.Column("revisado_em", DATA, nullable=True),
        sa.Column("visto_primeiro_em", DATA, nullable=False),
        sa.Column("visto_ultimo_em", DATA, nullable=False),
        sa.Column("reavaliar", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["anuncio_id"], ["anuncio_amazon.id"]),
        sa.ForeignKeyConstraint(["produto_id"], ["produto_liga.id"]),
        sa.PrimaryKeyConstraint("anuncio_id", "produto_id"),
    )
    op.create_index("ix_casamento_produto_status", "casamento", ["produto_id", "status"])
    op.create_index("ix_casamento_status", "casamento", ["status"])
    op.execute(COPIAR_PARES)
    conferir_um_confirmado_por_anuncio(op.get_bind())
    op.create_index(
        "uq_casamento_confirmado", "casamento", ["anuncio_id"], unique=True,
        postgresql_where=sa.text("status = 'confirmado'"),
    )

    op.create_table(
        "termo_busca",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("produto_id", sa.Integer(), nullable=False),
        sa.Column("termo", sa.Text(), nullable=False),
        sa.Column("idioma", sa.Text(), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False),
        sa.Column("criado_em", DATA, nullable=False),
        sa.CheckConstraint("char_length(termo) BETWEEN 1 AND 80", name="ck_termo_busca_termo"),
        sa.CheckConstraint("idioma IN ('pt', 'en')", name="ck_termo_busca_idioma"),
        sa.CheckConstraint("ordem BETWEEN 1 AND 3", name="ck_termo_busca_ordem"),
        sa.ForeignKeyConstraint(["produto_id"], ["produto_liga.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("produto_id", "termo", name="uq_termo_busca_produto_termo"),
        sa.UniqueConstraint("produto_id", "ordem", name="uq_termo_busca_produto_ordem"),
    )

    op.add_column("fila_amazon", sa.Column("indice_termo", sa.Integer(), server_default="0", nullable=False))
    op.create_check_constraint("ck_fila_amazon_indice_termo", "fila_amazon", "indice_termo >= 0")
    op.add_column("fila_amazon", sa.Column("ultimo_par_novo_em", DATA, nullable=True))
    op.add_column("fila_amazon", sa.Column("termos_tentados_em", DATA, nullable=True))
    op.add_column("fila_amazon", sa.Column("termos_pedidos_em", DATA, nullable=True))
    # Mesmo próximo termo de hoje: depois de uma busca em português vem o inglês.
    op.execute(
        "UPDATE fila_amazon SET indice_termo = "
        "CASE WHEN ultima_busca_em IS NOT NULL AND NOT ultimo_termo_en THEN 1 ELSE 0 END"
    )
    op.execute(
        "UPDATE fila_amazon f SET ultimo_par_novo_em = "
        "(SELECT max(c.visto_primeiro_em) FROM casamento c WHERE c.produto_id = f.produto_id)"
    )

    # A fonte do casamento é a tabela `casamento`: saem as colunas antigas (CHECKs e FK saem junto).
    for coluna in ("origem_casamento", "revisado_em", "status_casamento", "produto_id"):
        op.drop_column("anuncio_amazon", coluna)
    op.drop_column("fila_amazon", "ultimo_termo_en")


def downgrade() -> None:
    op.add_column("anuncio_amazon", sa.Column("produto_id", sa.Integer(), nullable=True))
    op.create_foreign_key("anuncio_amazon_produto_id_fkey", "anuncio_amazon", "produto_liga", ["produto_id"], ["id"])
    op.add_column("anuncio_amazon", sa.Column("status_casamento", sa.String(20), nullable=True))
    op.create_check_constraint(
        "status_casamento", "anuncio_amazon", "status_casamento IN ('pendente', 'confirmado', 'ignorado')"
    )
    op.add_column("anuncio_amazon", sa.Column("revisado_em", DATA, nullable=True))
    op.add_column("anuncio_amazon", sa.Column("origem_casamento", sa.String(20), nullable=True))
    op.create_check_constraint(
        "origem_casamento", "anuncio_amazon", "origem_casamento IN ('manual', 'sugerido_ia', 'automatico_ia')"
    )
    op.add_column("fila_amazon", sa.Column("ultimo_termo_en", sa.Boolean(), server_default="false", nullable=False))
    op.execute("UPDATE fila_amazon SET ultimo_termo_en = (ultima_busca_em IS NOT NULL AND indice_termo = 0)")
    op.drop_constraint("ck_fila_amazon_indice_termo", "fila_amazon", type_="check")
    for coluna in ("termos_pedidos_em", "termos_tentados_em", "ultimo_par_novo_em", "indice_termo"):
        op.drop_column("fila_amazon", coluna)
    op.drop_table("termo_busca")
    op.execute(REFAZER_ANUNCIO)
    op.execute("UPDATE anuncio_amazon SET status_casamento = 'pendente' WHERE status_casamento IS NULL")
    op.alter_column("anuncio_amazon", "status_casamento", existing_type=sa.String(20), nullable=False)
    op.drop_table("casamento")
