"""monitor de preço da Amazon: ofertas de cada leitura, conferência de checkout, origem do casamento
e configuração do monitor

Revision ID: b9e4c2a7d3f5
Revises: f2b6d8a4c1e7
Create Date: 2026-10-17 18:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9e4c2a7d3f5"
down_revision: Union[str, Sequence[str], None] = "f2b6d8a4c1e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DATA = sa.DateTime(timezone=True)
DINHEIRO = sa.Numeric(10, 2)
ENVIO = ("amazon", "fba", "proprio", "desconhecido")
LIMITES_NOVOS = {
    "monitor_intervalo_min": (5, 1440, 15),
    "monitor_max_paginas_hora": (1, 1000, 150),
    "margem_candidata_pp": (0, 50, 5),
    "checkout_validade_h": (1, 72, 6),
    "descoberta_casados_dias": (1, 60, 7),
}


def _enum(nome: str, *valores: str) -> sa.Enum:
    return sa.Enum(*valores, name=nome, native_enum=False, create_constraint=True, length=20)


def upgrade() -> None:
    for tabela in ("preco_amazon", "preco_atual_amazon"):
        op.drop_constraint("origem_preco", tabela, type_="check")
        op.create_check_constraint("origem_preco", tabela, "origem IN ('busca', 'produto', 'ofertas')")

    op.add_column("anuncio_amazon", sa.Column("origem_casamento", sa.String(20), nullable=True))
    op.create_check_constraint(
        "origem_casamento", "anuncio_amazon", "origem_casamento IN ('manual', 'sugerido_ia', 'automatico_ia')"
    )
    op.execute(
        """
        UPDATE anuncio_amazon a SET origem_casamento = CASE
            WHEN EXISTS (SELECT 1 FROM avaliacao_ia v WHERE v.anuncio_id = a.id AND v.produto_id = a.produto_id
                         AND v.aplicada_em = a.revisado_em) THEN 'automatico_ia'
            WHEN EXISTS (SELECT 1 FROM avaliacao_ia v WHERE v.anuncio_id = a.id AND v.produto_id = a.produto_id)
                THEN 'sugerido_ia'
            ELSE 'manual' END
        WHERE a.status_casamento IN ('confirmado', 'ignorado')
        """
    )

    op.create_table(
        "oferta_amazon",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("anuncio_id", sa.Integer(), sa.ForeignKey("anuncio_amazon.id"), nullable=False),
        sa.Column("lida_em", DATA, nullable=False),
        sa.Column("vendedor_id", sa.Integer(), sa.ForeignKey("vendedor_amazon.id"), nullable=True),
        sa.Column("vendedor_nome", sa.Text(), nullable=True),
        sa.Column("preco", DINHEIRO, nullable=False),
        sa.Column("preco_de", DINHEIRO, nullable=True),
        sa.Column("condicao", sa.Text(), nullable=False),
        sa.Column("envio", _enum("envio_amazon", *ENVIO), nullable=False),
        sa.Column("origem_envio", sa.Text(), nullable=True),
        sa.Column("importada", sa.Boolean(), nullable=False),
        sa.Column("prime", sa.Boolean(), nullable=False),
        sa.Column("elegivel", sa.Boolean(), nullable=False),
        sa.Column("melhor", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_oferta_amazon_leitura", "oferta_amazon", ["anuncio_id", "lida_em"])
    op.create_table(
        "conferencia_checkout",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("em", DATA, nullable=False),
        sa.Column("anuncio_id", sa.Integer(), sa.ForeignKey("anuncio_amazon.id"), nullable=False),
        sa.Column("vendedor_nome", sa.Text(), nullable=True),
        sa.Column("preco_anunciado", DINHEIRO, nullable=False),
        sa.Column("itens", DINHEIRO, nullable=True),
        sa.Column("frete", DINHEIRO, nullable=True),
        sa.Column("impostos", DINHEIRO, nullable=True),
        sa.Column("total", DINHEIRO, nullable=True),
        sa.Column("situacao", _enum("situacao_checkout", "ok", "falha", "carrinho_ocupado", "sem_login"), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("item_removido", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_conferencia_checkout_anuncio", "conferencia_checkout", ["anuncio_id", "em"])

    for campo, hora in (("monitor_janela_inicio", "08:00"), ("monitor_janela_fim", "22:00")):
        op.add_column("config_amazon", sa.Column(campo, sa.Time(), nullable=False, server_default=hora))
        op.alter_column("config_amazon", campo, server_default=None)
    op.create_check_constraint(
        "ck_config_amazon_monitor_janela", "config_amazon", "monitor_janela_inicio < monitor_janela_fim"
    )
    for campo, (minimo, maximo, padrao) in LIMITES_NOVOS.items():
        op.add_column("config_amazon", sa.Column(campo, sa.Integer(), nullable=False, server_default=str(padrao)))
        op.alter_column("config_amazon", campo, server_default=None)
        op.create_check_constraint(f"ck_config_amazon_{campo}", "config_amazon", f"{campo} BETWEEN {minimo} AND {maximo}")
    for campo in ("monitor_ligado", "checkout_ligado"):
        op.add_column("config_amazon", sa.Column(campo, sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("config_amazon", sa.Column("checkout_sem_login_em", DATA, nullable=True))


def downgrade() -> None:
    for campo in ("checkout_sem_login_em", "checkout_ligado", "monitor_ligado", *LIMITES_NOVOS, "monitor_janela_fim", "monitor_janela_inicio"):
        op.drop_column("config_amazon", campo)
    op.drop_index("ix_conferencia_checkout_anuncio", table_name="conferencia_checkout")
    op.drop_table("conferencia_checkout")
    op.drop_index("ix_oferta_amazon_leitura", table_name="oferta_amazon")
    op.drop_table("oferta_amazon")
    op.drop_constraint("origem_casamento", "anuncio_amazon", type_="check")
    op.drop_column("anuncio_amazon", "origem_casamento")
    op.execute("DELETE FROM preco_amazon WHERE origem = 'ofertas'")
    op.execute("UPDATE preco_atual_amazon SET origem = 'produto' WHERE origem = 'ofertas'")
    for tabela in ("preco_amazon", "preco_atual_amazon"):
        op.drop_constraint("origem_preco", tabela, type_="check")
        op.create_check_constraint("origem_preco", tabela, "origem IN ('busca', 'produto')")
