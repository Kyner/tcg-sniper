"""amazon: anúncios, preços, vendedores, fila, oportunidades, config e estado por coletor

Revision ID: 7d3f1a2b9c4e
Revises: 5c815103a38f
Create Date: 2026-10-14 18:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7d3f1a2b9c4e"
down_revision: Union[str, Sequence[str], None] = "5c815103a38f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DATA = sa.DateTime(timezone=True)
DINHEIRO = sa.Numeric(10, 2)


def _enum(nome: str, *valores: str) -> sa.Enum:
    return sa.Enum(*valores, name=nome, native_enum=False, create_constraint=True, length=20)


ENVIO = ("amazon", "fba", "proprio", "desconhecido")
ORIGEM = ("busca", "produto")
LIMITES = {
    "pausa_min_s": (0, 120),
    "pausa_max_s": (0, 120),
    "resultados_por_busca": (1, 48),
    "intervalo_busca_min": (10, 1440),
    "max_buscas_hora": (1, 400),
    "limite_falha_pct": (0, 100),
    "desconto_min_pct": (1, 90),
    "realerta_queda_pct": (1, 50),
    "liga_preco_max_idade_h": (1, 168),
    "vendedor_min_positivas_pct": (0, 100),
    "vendedor_min_avaliacoes": (0, 100000),
    "vendedor_reavaliar_dias": (1, 90),
}


def upgrade() -> None:
    op.drop_constraint("tipo_coleta", "coleta", type_="check")
    op.create_check_constraint("tipo_coleta", "coleta", "tipo IN ('listagem', 'produtos', 'amazon')")
    op.drop_constraint("estado_coletor_tipo", "estado_coletor", type_="check")
    op.create_check_constraint(
        "estado_coletor_tipo", "estado_coletor", "estado IN ('ativo', 'pausado_desafio', 'pausado')"
    )

    op.drop_constraint("ck_estado_coletor_linha_unica", "estado_coletor", type_="check")
    op.create_check_constraint("ck_estado_coletor_linhas", "estado_coletor", "id IN (1, 2)")
    op.add_column("estado_coletor", sa.Column("coletor", sa.Text(), nullable=True))
    op.execute("UPDATE estado_coletor SET coletor = 'liga' WHERE id = 1")
    op.execute(
        "INSERT INTO estado_coletor (id, coletor, estado, execucao_solicitada, atualizado_em) "
        "VALUES (2, 'amazon', 'ativo', false, now())"
    )
    op.alter_column("estado_coletor", "coletor", nullable=False)
    op.create_unique_constraint("uq_estado_coletor_coletor", "estado_coletor", ["coletor"])

    op.create_table(
        "anuncio_amazon",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asin", sa.Text(), nullable=False),
        sa.Column("titulo", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("produto_id", sa.Integer(), nullable=True),
        sa.Column("status_casamento", _enum("status_casamento", "pendente", "confirmado", "ignorado"), nullable=False),
        sa.Column("revisado_em", DATA, nullable=True),
        sa.Column("visto_primeiro_em", DATA, nullable=False),
        sa.Column("visto_ultimo_em", DATA, nullable=False),
        sa.ForeignKeyConstraint(["produto_id"], ["produto_liga.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asin"),
    )
    op.create_table(
        "vendedor_amazon",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("seller_id", sa.Text(), nullable=False),
        sa.Column("nome", sa.Text(), nullable=True),
        sa.Column("pct_positivas", sa.Numeric(5, 2), nullable=True),
        sa.Column("num_avaliacoes", sa.Integer(), nullable=True),
        sa.Column("avaliado_em", DATA, nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seller_id"),
    )
    op.create_table(
        "preco_amazon",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("anuncio_id", sa.Integer(), nullable=False),
        sa.Column("coletado_em", DATA, nullable=False),
        sa.Column("preco", DINHEIRO, nullable=True),
        sa.Column("origem", _enum("origem_preco", *ORIGEM), nullable=False),
        sa.Column("vendedor_id", sa.Integer(), nullable=True),
        sa.Column("envio", _enum("envio_amazon", *ENVIO), nullable=False),
        sa.ForeignKeyConstraint(["anuncio_id"], ["anuncio_amazon.id"]),
        sa.ForeignKeyConstraint(["vendedor_id"], ["vendedor_amazon.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "preco_atual_amazon",
        sa.Column("anuncio_id", sa.Integer(), nullable=False),
        sa.Column("preco", DINHEIRO, nullable=True),
        sa.Column("origem", _enum("origem_preco", *ORIGEM), nullable=False),
        sa.Column("vendedor_id", sa.Integer(), nullable=True),
        sa.Column("envio", _enum("envio_amazon", *ENVIO), nullable=False),
        sa.Column("coletado_em", DATA, nullable=False),
        sa.ForeignKeyConstraint(["anuncio_id"], ["anuncio_amazon.id"]),
        sa.ForeignKeyConstraint(["vendedor_id"], ["vendedor_amazon.id"]),
        sa.PrimaryKeyConstraint("anuncio_id"),
    )
    op.create_table(
        "fila_amazon",
        sa.Column("produto_id", sa.Integer(), nullable=False),
        sa.Column("entrou_em", DATA, nullable=False),
        sa.Column("proxima_busca_em", DATA, nullable=False),
        sa.Column("ultima_busca_em", DATA, nullable=True),
        sa.Column("ultimo_candidato_em", DATA, nullable=True),
        sa.ForeignKeyConstraint(["produto_id"], ["produto_liga.id"]),
        sa.PrimaryKeyConstraint("produto_id"),
    )
    op.create_table(
        "oportunidade",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("anuncio_id", sa.Integer(), nullable=False),
        sa.Column("produto_id", sa.Integer(), nullable=False),
        sa.Column("preco_amazon", DINHEIRO, nullable=False),
        sa.Column("preco_liga", DINHEIRO, nullable=False),
        sa.Column("desconto_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("vendedor_id", sa.Integer(), nullable=True),
        sa.Column("envio", _enum("envio_amazon", *ENVIO), nullable=False),
        sa.Column("aberta_em", DATA, nullable=False),
        sa.Column("alertada_em", DATA, nullable=False),
        sa.Column("preco_alertado", DINHEIRO, nullable=False),
        sa.Column("fechada_em", DATA, nullable=True),
        sa.ForeignKeyConstraint(["anuncio_id"], ["anuncio_amazon.id"]),
        sa.ForeignKeyConstraint(["produto_id"], ["produto_liga.id"]),
        sa.ForeignKeyConstraint(["vendedor_id"], ["vendedor_amazon.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_oportunidade_aberta", "oportunidade", ["anuncio_id"], unique=True,
        postgresql_where=sa.text("fechada_em IS NULL"),
    )
    op.create_table(
        "config_amazon",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("url_busca", sa.Text(), nullable=False),
        sa.Column("janela_inicio", sa.Time(), nullable=False),
        sa.Column("janela_fim", sa.Time(), nullable=False),
        *(sa.Column(campo, sa.Integer(), nullable=False) for campo in LIMITES),
        sa.Column("atualizado_em", DATA, nullable=False),
        sa.CheckConstraint("id = 1", name="ck_config_amazon_linha_unica"),
        sa.CheckConstraint("position('{termo}' in url_busca) > 0", name="ck_config_amazon_url"),
        sa.CheckConstraint("janela_inicio < janela_fim", name="ck_config_amazon_janela"),
        sa.CheckConstraint("pausa_min_s <= pausa_max_s", name="ck_config_amazon_pausas"),
        *(
            sa.CheckConstraint(f"{campo} BETWEEN {minimo} AND {maximo}", name=f"ck_config_amazon_{campo}")
            for campo, (minimo, maximo) in LIMITES.items()
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO config_amazon (id, url_busca, janela_inicio, janela_fim, pausa_min_s, pausa_max_s, "
        "resultados_por_busca, intervalo_busca_min, max_buscas_hora, limite_falha_pct, desconto_min_pct, "
        "realerta_queda_pct, liga_preco_max_idade_h, vendedor_min_positivas_pct, vendedor_min_avaliacoes, "
        "vendedor_reavaliar_dias, atualizado_em) VALUES (1, 'https://www.amazon.com.br/s?k={termo}', "
        "'08:00', '22:00', 8, 20, 10, 60, 200, 50, 25, 5, 48, 90, 100, 7, now())"
    )
    op.execute("INSERT INTO vendedor_amazon (seller_id, nome) VALUES ('amazon', 'Amazon.com.br')")


def downgrade() -> None:
    op.drop_table("config_amazon")
    op.drop_index("uq_oportunidade_aberta", table_name="oportunidade")
    op.drop_table("oportunidade")
    op.drop_table("fila_amazon")
    op.drop_table("preco_atual_amazon")
    op.drop_table("preco_amazon")
    op.drop_table("vendedor_amazon")
    op.drop_table("anuncio_amazon")
    op.drop_constraint("uq_estado_coletor_coletor", "estado_coletor", type_="unique")
    op.execute("DELETE FROM estado_coletor WHERE id <> 1")
    op.drop_column("estado_coletor", "coletor")
    op.drop_constraint("ck_estado_coletor_linhas", "estado_coletor", type_="check")
    op.create_check_constraint("ck_estado_coletor_linha_unica", "estado_coletor", "id = 1")
    op.execute("UPDATE estado_coletor SET estado = 'ativo' WHERE estado = 'pausado'")
    op.drop_constraint("estado_coletor_tipo", "estado_coletor", type_="check")
    op.create_check_constraint("estado_coletor_tipo", "estado_coletor", "estado IN ('ativo', 'pausado_desafio')")
    op.execute("DELETE FROM coleta WHERE tipo = 'amazon'")
    op.drop_constraint("tipo_coleta", "coleta", type_="check")
    op.create_check_constraint("tipo_coleta", "coleta", "tipo IN ('listagem', 'produtos')")
