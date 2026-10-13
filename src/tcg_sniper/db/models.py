import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TipoColeta(enum.StrEnum):
    CATALOGO = "catalogo"
    PRECOS = "precos"


class StatusColeta(enum.StrEnum):
    RODANDO = "rodando"
    OK = "ok"
    PARCIAL = "parcial"
    FALHA = "falha"
    PAUSADA_DESAFIO = "pausada_desafio"


class EstadoColetorTipo(enum.StrEnum):
    ATIVO = "ativo"
    PAUSADO_DESAFIO = "pausado_desafio"


def _enum(cls: type[enum.Enum], nome: str) -> Enum:
    return Enum(
        cls,
        name=nome,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda e: [m.value for m in e],
    )


DINHEIRO = Numeric(10, 2)
DATA = DateTime(timezone=True)


class ProdutoLiga(Base):
    __tablename__ = "produto_liga"

    id: Mapped[int] = mapped_column(primary_key=True)
    liga_id: Mapped[str] = mapped_column(Text, unique=True)
    nome: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    edicao: Mapped[str | None] = mapped_column(Text)
    tipo: Mapped[str | None] = mapped_column(Text)
    idioma: Mapped[str | None] = mapped_column(Text)
    ean: Mapped[str | None] = mapped_column(Text)
    ativo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    visto_primeiro_em: Mapped[datetime] = mapped_column(DATA)
    visto_ultimo_em: Mapped[datetime] = mapped_column(DATA)


class Coleta(Base):
    __tablename__ = "coleta"

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[TipoColeta] = mapped_column(_enum(TipoColeta, "tipo_coleta"))
    iniciada_em: Mapped[datetime] = mapped_column(DATA)
    finalizada_em: Mapped[datetime | None] = mapped_column(DATA)
    status: Mapped[StatusColeta] = mapped_column(_enum(StatusColeta, "status_coleta"))
    produtos_ok: Mapped[int] = mapped_column(Integer, default=0)
    produtos_falha: Mapped[int] = mapped_column(Integer, default=0)
    erro: Mapped[str | None] = mapped_column(Text)


class ResumoPreco(Base):
    __tablename__ = "resumo_preco"

    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"), primary_key=True)
    coleta_id: Mapped[int] = mapped_column(ForeignKey("coleta.id"), primary_key=True)
    preco_min: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    preco_medio: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    preco_max: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    num_lojas: Mapped[int] = mapped_column(Integer)
    coletado_em: Mapped[datetime] = mapped_column(DATA)


class PrecoAtualLiga(Base):
    __tablename__ = "preco_atual_liga"

    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"), primary_key=True)
    coleta_id: Mapped[int] = mapped_column(ForeignKey("coleta.id"))
    preco_min: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    preco_medio: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    preco_max: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    num_lojas: Mapped[int] = mapped_column(Integer)
    atualizado_em: Mapped[datetime] = mapped_column(DATA)


class EstadoColetor(Base):
    __tablename__ = "estado_coletor"
    __table_args__ = (CheckConstraint("id = 1", name="ck_estado_coletor_linha_unica"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    estado: Mapped[EstadoColetorTipo] = mapped_column(_enum(EstadoColetorTipo, "estado_coletor_tipo"))
    motivo: Mapped[str | None] = mapped_column(Text)
    execucao_solicitada: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    atualizado_em: Mapped[datetime] = mapped_column(DATA)
