import enum
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TipoColeta(enum.StrEnum):
    LISTAGEM = "listagem"  # varredura das listagens de categoria (catálogo + preço "à partir de")
    PRODUTOS = "produtos"  # páginas de produto da lista ativa (resumo histórico + nº de lojas)
    AMAZON = "amazon"  # ciclo da fila de buscas na Amazon


class StatusColeta(enum.StrEnum):
    RODANDO = "rodando"
    OK = "ok"
    PARCIAL = "parcial"
    FALHA = "falha"
    PAUSADA_DESAFIO = "pausada_desafio"


class EstadoColetorTipo(enum.StrEnum):
    ATIVO = "ativo"
    PAUSADO_DESAFIO = "pausado_desafio"
    PAUSADO = "pausado"  # pausa manual pelo admin ou por erros seguidos


class StatusCasamento(enum.StrEnum):
    PENDENTE = "pendente"
    CONFIRMADO = "confirmado"
    IGNORADO = "ignorado"


class OrigemPreco(enum.StrEnum):
    BUSCA = "busca"  # cartão do resultado de busca
    PRODUTO = "produto"  # oferta principal da página do produto


class Envio(enum.StrEnum):
    AMAZON = "amazon"  # vendido pela Amazon
    FBA = "fba"  # vendido por lojista, enviado pela Amazon
    PROPRIO = "proprio"  # vendido e enviado por lojista
    DESCONHECIDO = "desconhecido"


COLETOR_LIGA = "liga"
COLETOR_AMAZON = "amazon"


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


class PrecoListagem(Base):
    """Histórico append-only do preço "à partir de" da listagem: uma linha por produto e coleta."""

    __tablename__ = "preco_listagem"

    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"), primary_key=True)
    coleta_id: Mapped[int] = mapped_column(ForeignKey("coleta.id"), primary_key=True)
    preco_a_partir: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    coletado_em: Mapped[datetime] = mapped_column(DATA)


class PrecoAtualLiga(Base):
    """Dado corrente por produto. Dois grupos de colunas, cada um gravado só pela sua coleta:
    listagem (`preco_a_partir`, `listagem_*`) e página de produto (resumo, `num_lojas`, `resumo_*`)."""

    __tablename__ = "preco_atual_liga"

    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"), primary_key=True)
    preco_a_partir: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    listagem_coleta_id: Mapped[int | None] = mapped_column(ForeignKey("coleta.id"))
    listagem_em: Mapped[datetime | None] = mapped_column(DATA)
    preco_min: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    preco_medio: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    preco_max: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    num_lojas: Mapped[int | None] = mapped_column(Integer)
    resumo_coleta_id: Mapped[int | None] = mapped_column(ForeignKey("coleta.id"))
    resumo_em: Mapped[datetime | None] = mapped_column(DATA)


class EstadoColetor(Base):
    """Uma linha por coletor: id 1 = Liga, id 2 = Amazon (ver `repositorio.ID_COLETOR`)."""

    __tablename__ = "estado_coletor"
    __table_args__ = (
        CheckConstraint("id IN (1, 2)", name="ck_estado_coletor_linhas"),
        UniqueConstraint("coletor", name="uq_estado_coletor_coletor"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    # server_default: o código anterior à Amazon insere a linha 1 sem `coletor` (ver migração 7d3f1a2b9c4e).
    coletor: Mapped[str] = mapped_column(Text, server_default="liga")
    estado: Mapped[EstadoColetorTipo] = mapped_column(_enum(EstadoColetorTipo, "estado_coletor_tipo"))
    motivo: Mapped[str | None] = mapped_column(Text)
    execucao_solicitada: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    atualizado_em: Mapped[datetime] = mapped_column(DATA)


class AnuncioAmazon(Base):
    """Um anúncio (ASIN) da amazon.com.br e o casamento com um produto da Liga.

    Enquanto `pendente`, `produto_id` é a sugestão (o produto cuja busca achou o ASIN); quando
    `confirmado`, é o casamento. Um ASIN casa com no máximo um produto da Liga."""

    __tablename__ = "anuncio_amazon"

    id: Mapped[int] = mapped_column(primary_key=True)
    asin: Mapped[str] = mapped_column(Text, unique=True)
    titulo: Mapped[str] = mapped_column(Text)
    # Opção do seletor de variações lida na página do produto ("Collector Booster Box"); a busca não a mostra.
    variacao: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    produto_id: Mapped[int | None] = mapped_column(ForeignKey("produto_liga.id"))
    status_casamento: Mapped[StatusCasamento] = mapped_column(_enum(StatusCasamento, "status_casamento"))
    revisado_em: Mapped[datetime | None] = mapped_column(DATA)
    visto_primeiro_em: Mapped[datetime] = mapped_column(DATA)
    visto_ultimo_em: Mapped[datetime] = mapped_column(DATA)

    @property
    def titulo_exibicao(self) -> str:
        """Título com a opção da variação, quando o título ainda não a menciona."""
        if self.variacao and self.variacao.casefold() not in self.titulo.casefold():
            return f"{self.titulo} — {self.variacao}"
        return self.titulo


class VendedorAmazon(Base):
    """Vendedor da Amazon. A própria Amazon é a linha fixa `seller_id = 'amazon'` (migração)."""

    __tablename__ = "vendedor_amazon"

    id: Mapped[int] = mapped_column(primary_key=True)
    seller_id: Mapped[str] = mapped_column(Text, unique=True)
    nome: Mapped[str | None] = mapped_column(Text)
    pct_positivas: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    num_avaliacoes: Mapped[int | None] = mapped_column(Integer)
    avaliado_em: Mapped[datetime | None] = mapped_column(DATA)


class PrecoAmazon(Base):
    """Histórico append-only: uma linha quando o preço (ou vendedor/envio) muda, ou na 1ª leitura do dia."""

    __tablename__ = "preco_amazon"

    id: Mapped[int] = mapped_column(primary_key=True)
    anuncio_id: Mapped[int] = mapped_column(ForeignKey("anuncio_amazon.id"))
    coletado_em: Mapped[datetime] = mapped_column(DATA)
    preco: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    origem: Mapped[OrigemPreco] = mapped_column(_enum(OrigemPreco, "origem_preco"))
    vendedor_id: Mapped[int | None] = mapped_column(ForeignKey("vendedor_amazon.id"))
    envio: Mapped[Envio] = mapped_column(_enum(Envio, "envio_amazon"))


class PrecoAtualAmazon(Base):
    """Última leitura de cada anúncio. Vendedor e envio só mudam numa leitura de origem `produto`."""

    __tablename__ = "preco_atual_amazon"

    anuncio_id: Mapped[int] = mapped_column(ForeignKey("anuncio_amazon.id"), primary_key=True)
    preco: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    origem: Mapped[OrigemPreco] = mapped_column(_enum(OrigemPreco, "origem_preco"))
    vendedor_id: Mapped[int | None] = mapped_column(ForeignKey("vendedor_amazon.id"))
    envio: Mapped[Envio] = mapped_column(_enum(Envio, "envio_amazon"))
    coletado_em: Mapped[datetime] = mapped_column(DATA)


class FilaAmazon(Base):
    """Uma linha por produto ativo da Liga: quando buscar de novo na Amazon."""

    __tablename__ = "fila_amazon"

    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"), primary_key=True)
    entrou_em: Mapped[datetime] = mapped_column(DATA)
    proxima_busca_em: Mapped[datetime] = mapped_column(DATA)
    ultima_busca_em: Mapped[datetime | None] = mapped_column(DATA)
    ultimo_candidato_em: Mapped[datetime | None] = mapped_column(DATA)


class Oportunidade(Base):
    """Oferta elegível da Amazon. Aberta enquanto `fechada_em` é NULL; no máximo uma aberta por anúncio."""

    __tablename__ = "oportunidade"
    __table_args__ = (
        Index("uq_oportunidade_aberta", "anuncio_id", unique=True, postgresql_where=text("fechada_em IS NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    anuncio_id: Mapped[int] = mapped_column(ForeignKey("anuncio_amazon.id"))
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"))
    preco_amazon: Mapped[Decimal] = mapped_column(DINHEIRO)
    preco_liga: Mapped[Decimal] = mapped_column(DINHEIRO)
    desconto_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    vendedor_id: Mapped[int | None] = mapped_column(ForeignKey("vendedor_amazon.id"))
    envio: Mapped[Envio] = mapped_column(_enum(Envio, "envio_amazon"))
    aberta_em: Mapped[datetime] = mapped_column(DATA)
    alertada_em: Mapped[datetime] = mapped_column(DATA)
    preco_alertado: Mapped[Decimal] = mapped_column(DINHEIRO)
    fechada_em: Mapped[datetime | None] = mapped_column(DATA)


# Limites (inclusivos) dos campos inteiros de config_amazon: os CHECKs do banco, a migração e a
# validação do formulário do admin (coletor_amazon/config.py) usam os mesmos valores.
LIMITES_CONFIG_AMAZON: dict[str, tuple[int, int]] = {
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
    "vendedor_min_avaliacoes": (0, 100_000),
    "vendedor_reavaliar_dias": (1, 90),
}

PADROES_CONFIG_AMAZON: dict[str, object] = {
    "url_busca": "https://www.amazon.com.br/s?k={termo}",
    "janela_inicio": time(8, 0),
    "janela_fim": time(22, 0),
    "pausa_min_s": 8,
    "pausa_max_s": 20,
    "resultados_por_busca": 10,
    "intervalo_busca_min": 60,
    "max_buscas_hora": 200,
    "limite_falha_pct": 50,
    "desconto_min_pct": 25,
    "realerta_queda_pct": 5,
    "liga_preco_max_idade_h": 48,
    "vendedor_min_positivas_pct": 90,
    "vendedor_min_avaliacoes": 100,
    "vendedor_reavaliar_dias": 7,
}


class ConfigAmazon(Base):
    """Configuração da Amazon e do motor de oportunidades: uma linha, editável no admin."""

    __tablename__ = "config_amazon"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_config_amazon_linha_unica"),
        CheckConstraint("position('{termo}' in url_busca) > 0", name="ck_config_amazon_url"),
        CheckConstraint("janela_inicio < janela_fim", name="ck_config_amazon_janela"),
        CheckConstraint("pausa_min_s <= pausa_max_s", name="ck_config_amazon_pausas"),
        *(
            CheckConstraint(f"{campo} BETWEEN {minimo} AND {maximo}", name=f"ck_config_amazon_{campo}")
            for campo, (minimo, maximo) in LIMITES_CONFIG_AMAZON.items()
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    url_busca: Mapped[str] = mapped_column(Text)
    janela_inicio: Mapped[time] = mapped_column(Time)
    janela_fim: Mapped[time] = mapped_column(Time)
    pausa_min_s: Mapped[int] = mapped_column(Integer)
    pausa_max_s: Mapped[int] = mapped_column(Integer)
    resultados_por_busca: Mapped[int] = mapped_column(Integer)
    intervalo_busca_min: Mapped[int] = mapped_column(Integer)
    max_buscas_hora: Mapped[int] = mapped_column(Integer)
    limite_falha_pct: Mapped[int] = mapped_column(Integer)
    desconto_min_pct: Mapped[int] = mapped_column(Integer)
    realerta_queda_pct: Mapped[int] = mapped_column(Integer)
    liga_preco_max_idade_h: Mapped[int] = mapped_column(Integer)
    vendedor_min_positivas_pct: Mapped[int] = mapped_column(Integer)
    vendedor_min_avaliacoes: Mapped[int] = mapped_column(Integer)
    vendedor_reavaliar_dias: Mapped[int] = mapped_column(Integer)
    atualizado_em: Mapped[datetime] = mapped_column(DATA)
