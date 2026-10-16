import enum
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
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


class StatusMensagem(enum.StrEnum):
    PENDENTE = "pendente"
    ENVIADA = "enviada"
    FALHA = "falha"  # 4xx cinco vezes: precisa de alguém olhar (instância, grupo)
    EXPIRADA = "expirada"  # oportunidade que passou da validade sem sair
    DESCARTADA = "descartada"  # descartada no admin


COLETOR_LIGA = "liga"
COLETOR_AMAZON = "amazon"
COLETOR_CASADOR = "casador"
COLETOR_NOTIFICADOR = "notificador"


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
    nome_en: Mapped[str | None] = mapped_column(Text)
    imagem_url: Mapped[str | None] = mapped_column(Text)
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
    """Uma linha por serviço: id 1 = Liga, id 2 = Amazon, id 3 = casador, id 4 = notificador
    (ver `repositorio.ID_COLETOR`)."""

    __tablename__ = "estado_coletor"
    __table_args__ = (
        CheckConstraint("id IN (1, 2, 3, 4)", name="ck_estado_coletor_linhas"),
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
    # Imagem principal: a busca só preenche quando vazia; a página do produto pode trocar.
    imagem_url: Mapped[str | None] = mapped_column(Text)
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
    # A última busca usou o nome em inglês; a próxima volta ao português (só alterna se o produto tem `nome_en`).
    ultimo_termo_en: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


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


LIMITES_CONFIG_LIGA: dict[str, tuple[int, int]] = {
    "coleta_jitter_min": (0, 180),
    "pausa_min_s": (0, 120),
    "pausa_max_s": (0, 120),
    "limite_falha_pct": (0, 100),
    "max_cliques": (1, 500),
}


class ConfigGeral(Base):
    """Configuração geral (links, fuso, WhatsApp): uma linha, editável no admin. Criada na primeira
    leitura com os valores do .env (`repositorio.obter_config_geral`)."""

    __tablename__ = "config_geral"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_config_geral_linha_unica"),
        CheckConstraint("host_publico <> ''", name="ck_config_geral_host"),
        CheckConstraint("fuso <> ''", name="ck_config_geral_fuso"),
        CheckConstraint("validade_oportunidade_h BETWEEN 1 AND 48", name="ck_config_geral_validade"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    host_publico: Mapped[str] = mapped_column(Text)
    fuso: Mapped[str] = mapped_column(Text)
    evolution_instancia: Mapped[str | None] = mapped_column(Text)
    whatsapp_grupo_admin: Mapped[str | None] = mapped_column(Text)
    whatsapp_grupo_oportunidades: Mapped[str | None] = mapped_column(Text)
    validade_oportunidade_h: Mapped[int] = mapped_column(Integer, server_default="6")
    atualizado_em: Mapped[datetime] = mapped_column(DATA)


class ConfigLiga(Base):
    """Configuração da coleta da LigaMagic: uma linha, editável no admin. Criada na primeira leitura
    com os valores do .env (`repositorio.obter_config_liga`)."""

    __tablename__ = "config_liga"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_config_liga_linha_unica"),
        CheckConstraint("position('{categ}' in url_listagem) > 0", name="ck_config_liga_url"),
        CheckConstraint("categorias ~ '^[0-9]+(,[0-9]+)*$'", name="ck_config_liga_categorias"),
        CheckConstraint("pausa_min_s <= pausa_max_s", name="ck_config_liga_pausas"),
        *(
            CheckConstraint(f"{campo} BETWEEN {minimo} AND {maximo}", name=f"ck_config_liga_{campo}")
            for campo, (minimo, maximo) in LIMITES_CONFIG_LIGA.items()
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    coleta_hora: Mapped[time] = mapped_column(Time)
    coleta_jitter_min: Mapped[int] = mapped_column(Integer)
    pausa_min_s: Mapped[float] = mapped_column(Float)
    pausa_max_s: Mapped[float] = mapped_column(Float)
    limite_falha_pct: Mapped[int] = mapped_column(Integer)
    categorias: Mapped[str] = mapped_column(Text)
    url_listagem: Mapped[str] = mapped_column(Text)
    max_cliques: Mapped[int] = mapped_column(Integer)
    atualizado_em: Mapped[datetime] = mapped_column(DATA)


class MensagemSaida(Base):
    """Tabela de saída do WhatsApp: os serviços gravam aqui (`NotificadorFila`) e o serviço
    `notificador` envia, com tentativas, validade e registro do resultado."""

    __tablename__ = "mensagem_saida"
    __table_args__ = (
        CheckConstraint("destino IN ('admin', 'oportunidades')", name="ck_mensagem_saida_destino"),
        CheckConstraint("texto <> ''", name="ck_mensagem_saida_texto"),
        CheckConstraint("tentativas >= 0", name="ck_mensagem_saida_tentativas"),
        Index("ix_mensagem_saida_fila", "status", "proxima_tentativa_em"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    destino: Mapped[str] = mapped_column(Text)
    texto: Mapped[str] = mapped_column(Text)
    status: Mapped[StatusMensagem] = mapped_column(_enum(StatusMensagem, "status_mensagem"))
    tentativas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    proxima_tentativa_em: Mapped[datetime] = mapped_column(DATA)
    ultimo_erro: Mapped[str | None] = mapped_column(Text)
    ignorar_validade: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    criada_em: Mapped[datetime] = mapped_column(DATA)
    atualizado_em: Mapped[datetime] = mapped_column(DATA)
    enviada_em: Mapped[datetime | None] = mapped_column(DATA)


class EstadoNotificador(Base):
    """Uma linha (id 1): quando o serviço notificador terminou o último ciclo (Serviços mostra se está vivo)."""

    __tablename__ = "estado_notificador"
    __table_args__ = (CheckConstraint("id = 1", name="ck_estado_notificador_linha_unica"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    ultimo_ciclo_em: Mapped[datetime | None] = mapped_column(DATA)


ESFORCOS_IA = ("minimal", "low", "medium", "high")

LIMITES_CONFIG_IA: dict[str, tuple[int, int]] = {
    "max_chamadas_dia": (0, 100000),
    "intervalo_min": (1, 1440),
    "lote": (1, 500),
    "confianca_confirmar": (0, 100),
    "confianca_ignorar": (0, 100),
}

PADROES_CONFIG_IA: dict[str, object] = {
    "ligado": False,
    "modelo": "gpt-5",
    "esforco": "low",
    "preco_entrada_milhao_usd": Decimal("1.25"),
    "preco_saida_milhao_usd": Decimal("10.00"),
    "teto_dia_usd": Decimal("2.00"),
    "teto_mes_usd": Decimal("20.00"),
    "max_chamadas_dia": 1000,
    "intervalo_min": 5,
    "lote": 20,
    "automatico": False,
    "confianca_confirmar": 90,
    "confianca_ignorar": 90,
}


class ConfigIA(Base):
    """Configuração da IA (casador): uma linha, editável no admin. A chave fica no .env (OPENAI_API_KEY)."""

    __tablename__ = "config_ia"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_config_ia_linha_unica"),
        CheckConstraint("modelo <> ''", name="ck_config_ia_modelo"),
        CheckConstraint("esforco IN ('minimal', 'low', 'medium', 'high')", name="ck_config_ia_esforco"),
        CheckConstraint(
            "preco_entrada_milhao_usd >= 0 AND preco_saida_milhao_usd >= 0 AND teto_dia_usd >= 0 AND teto_mes_usd >= 0",
            name="ck_config_ia_valores",
        ),
        *(
            CheckConstraint(f"{campo} BETWEEN {minimo} AND {maximo}", name=f"ck_config_ia_{campo}")
            for campo, (minimo, maximo) in LIMITES_CONFIG_IA.items()
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    ligado: Mapped[bool] = mapped_column(Boolean)
    modelo: Mapped[str] = mapped_column(Text)
    esforco: Mapped[str] = mapped_column(Text)
    preco_entrada_milhao_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    preco_saida_milhao_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    teto_dia_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    teto_mes_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    max_chamadas_dia: Mapped[int] = mapped_column(Integer)
    intervalo_min: Mapped[int] = mapped_column(Integer)
    lote: Mapped[int] = mapped_column(Integer)
    automatico: Mapped[bool] = mapped_column(Boolean)
    confianca_confirmar: Mapped[int] = mapped_column(Integer)
    confianca_ignorar: Mapped[int] = mapped_column(Integer)
    atualizado_em: Mapped[datetime] = mapped_column(DATA)


class ChamadaIA(Base):
    """Cada chamada à OpenAI (ok ou erro), com tokens e custo: base do orçamento e do gasto no admin."""

    __tablename__ = "chamada_ia"
    __table_args__ = (Index("ix_chamada_ia_em", "em"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    em: Mapped[datetime] = mapped_column(DATA)
    finalidade: Mapped[str] = mapped_column(Text)  # "casamento" | "avaliacao"
    modelo: Mapped[str] = mapped_column(Text)
    tokens_entrada: Mapped[int] = mapped_column(Integer)
    tokens_saida: Mapped[int] = mapped_column(Integer)
    custo_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    ok: Mapped[bool] = mapped_column(Boolean)
    erro: Mapped[str | None] = mapped_column(Text)


class AvaliacaoIA(Base):
    """Veredito da IA para um par (anúncio, produto da Liga). `assinatura` = hash dos dados enviados:
    mudou, reavalia. `aplicada_em` preenchida quando o automático confirmou ou ignorou o anúncio
    (fica mesmo se o usuário desfizer, para o automático não reaplicar)."""

    __tablename__ = "avaliacao_ia"
    __table_args__ = (
        UniqueConstraint("anuncio_id", "produto_id", name="uq_avaliacao_ia_par"),
        CheckConstraint("confianca BETWEEN 0 AND 100", name="ck_avaliacao_ia_confianca"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    anuncio_id: Mapped[int] = mapped_column(ForeignKey("anuncio_amazon.id"))
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"))
    mesmo_produto: Mapped[bool] = mapped_column(Boolean)
    confianca: Mapped[int] = mapped_column(Integer)
    motivo: Mapped[str] = mapped_column(Text)
    modelo: Mapped[str] = mapped_column(Text)
    assinatura: Mapped[str] = mapped_column(Text)
    sem_imagem: Mapped[bool] = mapped_column(Boolean)
    avaliado_em: Mapped[datetime] = mapped_column(DATA)
    aplicada_em: Mapped[datetime | None] = mapped_column(DATA)
    chamada_id: Mapped[int | None] = mapped_column(ForeignKey("chamada_ia.id"))
