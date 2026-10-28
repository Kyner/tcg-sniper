import enum
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.dialects.postgresql import JSONB
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
    OFERTAS = "ofertas"  # melhor oferta elegível da lista de ofertas (monitor)


class OrigemCasamento(enum.StrEnum):
    MANUAL = "manual"  # o usuário decidiu sem avaliação da IA para o par, ou colou o link
    SUGERIDO_IA = "sugerido_ia"  # o usuário decidiu um par que a IA tinha avaliado
    AUTOMATICO_IA = "automatico_ia"  # o automático do casador decidiu
    OUTRO_CONFIRMADO = "outro_confirmado"  # o anúncio foi confirmado para outro produto (decisão do sistema)


class SituacaoCheckout(enum.StrEnum):
    OK = "ok"
    FALHA = "falha"
    CARRINHO_OCUPADO = "carrinho_ocupado"  # havia item no carrinho ativo: nada foi clicado
    SEM_LOGIN = "sem_login"  # a Amazon pediu login: a conferência fica desligada até "Retomar"


class Envio(enum.StrEnum):
    AMAZON = "amazon"  # vendido pela Amazon
    FBA = "fba"  # vendido por lojista, enviado pela Amazon
    PROPRIO = "proprio"  # vendido e enviado por lojista
    DESCONHECIDO = "desconhecido"


class MotivoEncerramento(enum.StrEnum):
    """Por que uma oportunidade fechou, na ordem de prioridade (spec 2026-10-20-fim-da-oportunidade)."""

    CASAMENTO_DESFEITO = "casamento_desfeito"
    SEM_LEITURA = "sem_leitura"
    LIGA_DESATUALIZADA = "liga_desatualizada"
    OFERTA_SUMIU = "oferta_sumiu"
    VENDEDOR = "vendedor"
    LIGA_CAIU = "liga_caiu"
    PRECO_SUBIU = "preco_subiu"
    PRODUTO_DESATIVADO = "produto_desativado"


MOTIVOS_SQL = ", ".join(f"'{m.value}'" for m in MotivoEncerramento)


class StatusMensagem(enum.StrEnum):
    PENDENTE = "pendente"
    ENVIADA = "enviada"
    FALHA = "falha"  # 4xx cinco vezes: precisa de alguém olhar (instância, grupo)
    EXPIRADA = "expirada"  # oportunidade que passou da validade sem sair
    DESCARTADA = "descartada"  # descartada no admin


class StatusManutencao(enum.StrEnum):
    RODANDO = "rodando"
    OK = "ok"  # backup local e cópia no R2
    SO_LOCAL = "so_local"  # backup local; R2 não configurado (variáveis R2_* vazias)
    ERRO = "erro"  # dump, validação, envio ao R2 ou limpeza falhou (o arquivo local fica se o dump deu certo)
    INTERROMPIDA = "interrompida"  # o serviço reiniciou no meio; não conta como a execução do dia


class Papel(enum.StrEnum):
    GRUPO = "grupo"  # área de negócio
    OPERADOR = "operador"  # área de negócio e de gestão (o que mais, a grade de Acessos diz)
    ADMIN = "admin"  # tudo, sempre (não editável na grade)


class TipoAcaoGestao(enum.StrEnum):
    CATALOGO_LOTE = "catalogo_lote"  # ação em lote no catálogo
    CATALOGO_PRODUTO = "catalogo_produto"  # edição de um produto
    SERVICO = "servico"  # ligar, desligar ou rodar um serviço (fase 3B)
    CONFIGURACOES = "configuracoes"  # mudança de configurações (fase 3C)


COLETOR_LIGA = "liga"
COLETOR_AMAZON = "amazon"
COLETOR_CASADOR = "casador"
COLETOR_NOTIFICADOR = "notificador"
COLETOR_MANUTENCAO = "manutencao"
COLETOR_AMAZON_BUSCA = "amazon_busca"  # busca de anúncios novos (serviço coletor-amazon-busca, navegador sem login)


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
    imagem_chave: Mapped[str | None] = mapped_column(Text)  # cópia no bucket de imagens (manutencao/imagens.py)
    imagem_origem: Mapped[str | None] = mapped_column(Text)  # a imagem_url que foi copiada
    url: Mapped[str] = mapped_column(Text)
    edicao: Mapped[str | None] = mapped_column(Text)
    tipo: Mapped[str | None] = mapped_column(Text)
    idioma: Mapped[str | None] = mapped_column(Text)
    ean: Mapped[str | None] = mapped_column(Text)
    ativo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    visto_primeiro_em: Mapped[datetime] = mapped_column(DATA)
    visto_ultimo_em: Mapped[datetime] = mapped_column(DATA)
    # Páginas seguidas que falharam na leitura; uma leitura boa zera (depois de 3 vai para o rodízio).
    falhas_pagina: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Coleta(Base):
    __tablename__ = "coleta"
    __table_args__ = (Index("ix_coleta_iniciada_em", "iniciada_em"),)  # Atividade e último registro

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
    __table_args__ = (
        Index("ix_resumo_preco_coleta", "coleta_id"),  # limpeza das coletas sem preço
        Index("ix_resumo_preco_coletado_em", "coletado_em"),  # último registro da Liga
    )

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
    __table_args__ = (Index("ix_preco_listagem_coleta", "coleta_id"),)  # limpeza das coletas sem preço

    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"), primary_key=True)
    coleta_id: Mapped[int] = mapped_column(ForeignKey("coleta.id"), primary_key=True)
    preco_a_partir: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    coletado_em: Mapped[datetime] = mapped_column(DATA)


class PrecoAtualLiga(Base):
    """Dado corrente por produto. Dois grupos de colunas, cada um gravado só pela sua coleta:
    listagem (`preco_a_partir`, `listagem_*`) e página de produto (resumo, `num_lojas`, `resumo_*`)."""

    __tablename__ = "preco_atual_liga"
    __table_args__ = (
        Index("ix_preco_atual_liga_listagem_coleta", "listagem_coleta_id"),
        Index("ix_preco_atual_liga_resumo_coleta", "resumo_coleta_id"),
    )

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
    """Uma linha por serviço: id 1 = Liga, id 2 = Amazon (monitor, checkout e retirada), id 3 = casador,
    id 4 = notificador, id 5 = manutenção, id 6 = Amazon (busca) (ver `repositorio.ID_COLETOR`)."""

    __tablename__ = "estado_coletor"
    __table_args__ = (
        CheckConstraint("id IN (1, 2, 3, 4, 5, 6)", name="ck_estado_coletor_linhas"),
        UniqueConstraint("coletor", name="uq_estado_coletor_coletor"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    # server_default: o código anterior à Amazon insere a linha 1 sem `coletor` (ver migração 7d3f1a2b9c4e).
    coletor: Mapped[str] = mapped_column(Text, server_default="liga")
    estado: Mapped[EstadoColetorTipo] = mapped_column(_enum(EstadoColetorTipo, "estado_coletor_tipo"))
    motivo: Mapped[str | None] = mapped_column(Text)
    execucao_solicitada: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    atualizado_em: Mapped[datetime] = mapped_column(DATA)
    # Quando o coletor voltou depois de um desafio (captcha) resolvido; a contagem de pausas parte daqui.
    retomado_desafio_em: Mapped[datetime | None] = mapped_column(DATA)


class AnuncioAmazon(Base):
    """Um anúncio (ASIN) da amazon.com.br. O casamento com os produtos da Liga fica em `Casamento` (por par)."""

    __tablename__ = "anuncio_amazon"
    __table_args__ = (
        CheckConstraint("idioma IN ('pt', 'en', 'ja', 'outro', 'indefinido')", name="ck_anuncio_amazon_idioma"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asin: Mapped[str] = mapped_column(Text, unique=True)
    titulo: Mapped[str] = mapped_column(Text)
    # Opção do seletor de variações lida na página do produto ("Collector Booster Box"); a busca não a mostra.
    variacao: Mapped[str | None] = mapped_column(Text)
    # Imagem principal: a busca só preenche quando vazia; a página do produto pode trocar.
    imagem_url: Mapped[str | None] = mapped_column(Text)
    imagem_chave: Mapped[str | None] = mapped_column(Text)  # cópia no bucket de imagens (manutencao/imagens.py)
    imagem_origem: Mapped[str | None] = mapped_column(Text)  # a imagem_url que foi copiada
    url: Mapped[str] = mapped_column(Text)
    visto_primeiro_em: Mapped[datetime] = mapped_column(DATA)
    visto_ultimo_em: Mapped[datetime] = mapped_column(DATA)
    # Última leitura das ofertas pelo monitor (NULL se nunca leu). A busca pode trocar o preço atual
    # (`PrecoAtualAmazon`) sem ser leitura do monitor: o prazo e a ordem do monitor vêm daqui.
    monitor_lido_em: Mapped[datetime | None] = mapped_column(DATA)
    # Idioma definido à mão ou por comando (`IDIOMAS_ANUNCIO`); vazio: vale o da avaliação da IA.
    idioma: Mapped[str | None] = mapped_column(Text)

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
    __table_args__ = (Index("ix_preco_amazon_anuncio_coletado", "anuncio_id", "coletado_em"),)  # curva do produto

    id: Mapped[int] = mapped_column(primary_key=True)
    anuncio_id: Mapped[int] = mapped_column(ForeignKey("anuncio_amazon.id"))
    coletado_em: Mapped[datetime] = mapped_column(DATA)
    preco: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    origem: Mapped[OrigemPreco] = mapped_column(_enum(OrigemPreco, "origem_preco"))
    vendedor_id: Mapped[int | None] = mapped_column(ForeignKey("vendedor_amazon.id"))
    envio: Mapped[Envio] = mapped_column(_enum(Envio, "envio_amazon"))


class PrecoAtualAmazon(Base):
    """Última leitura de cada anúncio. Vendedor e envio só mudam numa leitura de origem `produto` ou `ofertas`."""

    __tablename__ = "preco_atual_amazon"

    anuncio_id: Mapped[int] = mapped_column(ForeignKey("anuncio_amazon.id"), primary_key=True)
    preco: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    origem: Mapped[OrigemPreco] = mapped_column(_enum(OrigemPreco, "origem_preco"))
    vendedor_id: Mapped[int | None] = mapped_column(ForeignKey("vendedor_amazon.id"))
    envio: Mapped[Envio] = mapped_column(_enum(Envio, "envio_amazon"))
    coletado_em: Mapped[datetime] = mapped_column(DATA)


class FilaAmazon(Base):
    """Uma linha por produto ativo da Liga: quando buscar de novo na Amazon e com que termo."""

    __tablename__ = "fila_amazon"
    __table_args__ = (CheckConstraint("indice_termo >= 0", name="ck_fila_amazon_indice_termo"),)

    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"), primary_key=True)
    entrou_em: Mapped[datetime] = mapped_column(DATA)
    proxima_busca_em: Mapped[datetime] = mapped_column(DATA)
    ultima_busca_em: Mapped[datetime | None] = mapped_column(DATA)
    ultimo_candidato_em: Mapped[datetime | None] = mapped_column(DATA)
    # Próximo termo da sequência (nome, nome em inglês, termos alternativos na seca), usado módulo o tamanho.
    indice_termo: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Última vez que a busca deste produto criou um par pendente novo (a seca conta daqui; nulo: desde entrou_em).
    ultimo_par_novo_em: Mapped[datetime | None] = mapped_column(DATA)
    # Última tentativa da IA de gerar termos (sem termo válido: espera 7 dias) e pedido do admin.
    termos_tentados_em: Mapped[datetime | None] = mapped_column(DATA)
    termos_pedidos_em: Mapped[datetime | None] = mapped_column(DATA)
    # Falhas seguidas da geração de termos e até quando esperar para tentar de novo.
    termos_falhas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    termos_espera_ate: Mapped[datetime | None] = mapped_column(DATA)


class Casamento(Base):
    """Par (anúncio da Amazon, produto da Liga): a fonte única do casamento. Um anúncio pode estar pendente
    ou ignorado para vários produtos e confirmado para no máximo um (índice único parcial). `visto_*`: quando
    a busca deste produto viu o anúncio (par criado por link, troca ou migração: a criação). `reavaliar`:
    Desfazer ou "Reavaliar com a IA" pediram nova avaliação mesmo com os dados iguais."""

    __tablename__ = "casamento"
    __table_args__ = (
        Index("uq_casamento_confirmado", "anuncio_id", unique=True, postgresql_where=text("status = 'confirmado'")),
        Index("ix_casamento_produto_status", "produto_id", "status"),
        Index("ix_casamento_status", "status"),
    )

    anuncio_id: Mapped[int] = mapped_column(ForeignKey("anuncio_amazon.id"), primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"), primary_key=True)
    status: Mapped[StatusCasamento] = mapped_column(_enum(StatusCasamento, "status_casamento"))
    origem: Mapped[OrigemCasamento | None] = mapped_column(_enum(OrigemCasamento, "origem_casamento"))
    revisado_em: Mapped[datetime | None] = mapped_column(DATA)
    visto_primeiro_em: Mapped[datetime] = mapped_column(DATA)
    visto_ultimo_em: Mapped[datetime] = mapped_column(DATA)
    reavaliar: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Falhas seguidas da IA neste par, até quando esperar e a assinatura dos dados que falharam.
    ia_falhas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    ia_espera_ate: Mapped[datetime | None] = mapped_column(DATA)
    ia_falha_assinatura: Mapped[str | None] = mapped_column(Text)


class TermoBusca(Base):
    """Termos de busca alternativos de um produto (busca alternativa): gerados pela IA, no máximo 3."""

    __tablename__ = "termo_busca"
    __table_args__ = (
        UniqueConstraint("produto_id", "termo", name="uq_termo_busca_produto_termo"),
        UniqueConstraint("produto_id", "ordem", name="uq_termo_busca_produto_ordem"),
        CheckConstraint("char_length(termo) BETWEEN 1 AND 80", name="ck_termo_busca_termo"),
        CheckConstraint("idioma IN ('pt', 'en')", name="ck_termo_busca_idioma"),
        CheckConstraint("ordem BETWEEN 1 AND 3", name="ck_termo_busca_ordem"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"))
    termo: Mapped[str] = mapped_column(Text)
    idioma: Mapped[str] = mapped_column(Text)
    ordem: Mapped[int] = mapped_column(Integer)
    criado_em: Mapped[datetime] = mapped_column(DATA)


class Oportunidade(Base):
    """Oferta elegível da Amazon. Aberta enquanto `fechada_em` é NULL; no máximo uma aberta por anúncio.
    Em risco (`em_risco_desde`) quando a leitura deixou de ser elegível e a carência ainda não venceu.
    Só `oportunidades.encerramento.encerrar` fecha."""

    __tablename__ = "oportunidade"
    __table_args__ = (
        Index("uq_oportunidade_aberta", "anuncio_id", unique=True, postgresql_where=text("fechada_em IS NULL")),
        CheckConstraint(f"motivo_encerramento IN ({MOTIVOS_SQL})", name="ck_oportunidade_motivo_encerramento"),
        CheckConstraint(f"motivo_risco IN ({MOTIVOS_SQL})", name="ck_oportunidade_motivo_risco"),
        Index("ix_oportunidade_mensagem_alerta_id", "mensagem_alerta_id"),
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
    # O último aviso saiu com o preço conferido no checkout: o anunciado (sem os impostos) não realerta.
    alerta_conferido: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    fechada_em: Mapped[datetime | None] = mapped_column(DATA)
    motivo_encerramento: Mapped[MotivoEncerramento | None] = mapped_column(Text)
    em_risco_desde: Mapped[datetime | None] = mapped_column(DATA)
    motivo_risco: Mapped[MotivoEncerramento | None] = mapped_column(Text)
    menor_preco: Mapped[Decimal] = mapped_column(DINHEIRO)
    alertas: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # Mensagem do último alerta (abertura ou realerta); a limpeza de 30 dias apaga a mensagem e zera aqui.
    mensagem_alerta_id: Mapped[int | None] = mapped_column(ForeignKey("mensagem_saida.id", ondelete="SET NULL"))
    encerramento_avisado_em: Mapped[datetime | None] = mapped_column(DATA)
    # Quando deixou de valer: a primeira leitura ruim (início do risco) ou, sem risco, o encerramento.
    deixou_de_valer_em: Mapped[datetime | None] = mapped_column(DATA)
    # Aberta antes desta versão (o id da mensagem não era guardado): ao encerrar, conta como alerta enviado.
    alerta_sem_registro: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # O alerta desta oportunidade chegou a ser enviado (ao grupo).
    alerta_enviado: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class OfertaAmazon(Base):
    """Todas as ofertas de cada leitura do monitor (lista de ofertas do ASIN). `melhor` marca a que
    virou o preço atual do anúncio. Leituras com mais de 30 dias são apagadas pelo coletor."""

    __tablename__ = "oferta_amazon"
    __table_args__ = (
        Index("ix_oferta_amazon_leitura", "anuncio_id", "lida_em"),
        Index("ix_oferta_amazon_lida_em", "lida_em", "anuncio_id"),  # leituras do monitor na Atividade
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    anuncio_id: Mapped[int] = mapped_column(ForeignKey("anuncio_amazon.id"))
    lida_em: Mapped[datetime] = mapped_column(DATA)
    vendedor_id: Mapped[int | None] = mapped_column(ForeignKey("vendedor_amazon.id"))
    vendedor_nome: Mapped[str | None] = mapped_column(Text)
    preco: Mapped[Decimal] = mapped_column(DINHEIRO)
    preco_de: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    condicao: Mapped[str] = mapped_column(Text)  # "novo" | "usado" | o texto do painel
    envio: Mapped[Envio] = mapped_column(_enum(Envio, "envio_amazon"))
    origem_envio: Mapped[str | None] = mapped_column(Text)  # "Estados Unidos"
    importada: Mapped[bool] = mapped_column(Boolean)
    prime: Mapped[bool] = mapped_column(Boolean)
    elegivel: Mapped[bool] = mapped_column(Boolean)
    melhor: Mapped[bool] = mapped_column(Boolean)


class ConferenciaCheckout(Base):
    """Cada conferência de checkout de uma oferta candidata. `item_removido` False: o item pode ter
    ficado no carrinho e o coletor tenta tirar de novo (no máximo 3 vezes, só com o carrinho exatamente
    como a conferência o deixou). `conferir_a_mao_em` preenchida: o coletor desistiu de tirar sozinho
    (avisou o grupo admin uma vez); o usuário confere o carrinho e clica em "Já conferi" no admin."""

    __tablename__ = "conferencia_checkout"
    __table_args__ = (
        Index("ix_conferencia_checkout_anuncio", "anuncio_id", "em"),
        Index("ix_conferencia_checkout_em", "em"),  # Atividade e último registro
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    em: Mapped[datetime] = mapped_column(DATA)
    anuncio_id: Mapped[int] = mapped_column(ForeignKey("anuncio_amazon.id"))
    vendedor_nome: Mapped[str | None] = mapped_column(Text)
    preco_anunciado: Mapped[Decimal] = mapped_column(DINHEIRO)
    itens: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    frete: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    impostos: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    total: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    situacao: Mapped[SituacaoCheckout] = mapped_column(_enum(SituacaoCheckout, "situacao_checkout"))
    motivo: Mapped[str | None] = mapped_column(Text)
    item_removido: Mapped[bool] = mapped_column(Boolean)
    retiradas_tentadas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    retirada_tentada_em: Mapped[datetime | None] = mapped_column(DATA)
    conferir_a_mao_em: Mapped[datetime | None] = mapped_column(DATA)


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
    "monitor_intervalo_min": (5, 1440),
    "monitor_max_paginas_hora": (1, 1000),
    "monitor_esgotado_dias": (1, 30),
    "margem_candidata_pp": (0, 50),
    "checkout_validade_h": (1, 72),
    "descoberta_casados_dias": (1, 60),
    "carencia_encerramento_min": (0, 240),
    "quase_oportunidade_min_pct": (0, 100),
}

PADROES_CONFIG_AMAZON: dict[str, object] = {
    "url_busca": "https://www.amazon.com.br/s?k={termo}",
    "janela_inicio": time(8, 0),
    "janela_fim": time(22, 0),
    "pausa_min_s": 8,
    "pausa_max_s": 20,
    "resultados_por_busca": 10,
    "intervalo_busca_min": 60,
    "max_buscas_hora": 90,
    "limite_falha_pct": 50,
    "desconto_min_pct": 25,
    "realerta_queda_pct": 5,
    "liga_preco_max_idade_h": 48,
    "vendedor_min_positivas_pct": 90,
    "vendedor_min_avaliacoes": 100,
    "vendedor_reavaliar_dias": 7,
    "monitor_intervalo_min": 15,
    "monitor_janela_inicio": time(8, 0),
    "monitor_janela_fim": time(22, 0),
    "monitor_max_paginas_hora": 150,
    "monitor_esgotado_dias": 7,
    "margem_candidata_pp": 5,
    "checkout_validade_h": 6,
    "descoberta_casados_dias": 7,
    "carencia_encerramento_min": 30,
    "quase_oportunidade_min_pct": 10,
}


class ConfigAmazon(Base):
    """Configuração da Amazon e do motor de oportunidades: uma linha, editável no admin."""

    __tablename__ = "config_amazon"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_config_amazon_linha_unica"),
        CheckConstraint("position('{termo}' in url_busca) > 0", name="ck_config_amazon_url"),
        CheckConstraint("janela_inicio < janela_fim", name="ck_config_amazon_janela"),
        CheckConstraint("monitor_janela_inicio < monitor_janela_fim", name="ck_config_amazon_monitor_janela"),
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
    monitor_janela_inicio: Mapped[time] = mapped_column(Time)
    monitor_janela_fim: Mapped[time] = mapped_column(Time)
    monitor_intervalo_min: Mapped[int] = mapped_column(Integer)
    monitor_max_paginas_hora: Mapped[int] = mapped_column(Integer)
    monitor_esgotado_dias: Mapped[int] = mapped_column(Integer)
    margem_candidata_pp: Mapped[int] = mapped_column(Integer)
    checkout_validade_h: Mapped[int] = mapped_column(Integer)
    descoberta_casados_dias: Mapped[int] = mapped_column(Integer)
    carencia_encerramento_min: Mapped[int] = mapped_column(Integer)
    quase_oportunidade_min_pct: Mapped[int] = mapped_column(Integer)
    # Ligados e desligados em Serviços (fora do formulário de Configurações).
    monitor_ligado: Mapped[bool] = mapped_column(Boolean, server_default="true")
    checkout_ligado: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # Preenchida quando o checkout pediu login: a conferência não roda até "Retomar conferência".
    checkout_sem_login_em: Mapped[datetime | None] = mapped_column(DATA)
    atualizado_em: Mapped[datetime] = mapped_column(DATA)


LIMITES_CONFIG_LIGA: dict[str, tuple[int, int]] = {
    "coleta_jitter_min": (0, 180),
    "pausa_min_s": (0, 120),
    "pausa_max_s": (0, 120),
    "limite_falha_pct": (0, 100),
    "max_cliques": (1, 500),
    "esfriar_desafio_min": (0, 240),
    "produtos_novos_dia": (0, 2000),
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
    # Minutos de espera depois de retomar um desafio do Cloudflare (coletor_liga.esfriamento).
    esfriar_desafio_min: Mapped[int] = mapped_column(Integer, server_default="30")
    # Teto de produtos ainda sem resumo abertos por dia (coletor_liga.lista_do_dia).
    produtos_novos_dia: Mapped[int] = mapped_column(Integer, server_default="100")
    atualizado_em: Mapped[datetime] = mapped_column(DATA)


class MensagemSaida(Base):
    """Tabela de saída do WhatsApp: os serviços gravam aqui (`avisos.servico`) e o serviço
    `notificador` envia, com tentativas, validade e registro do resultado."""

    __tablename__ = "mensagem_saida"
    __table_args__ = (
        CheckConstraint("destino IN ('admin', 'oportunidades', 'individual')", name="ck_mensagem_saida_destino"),
        CheckConstraint("(destino = 'individual') = (numero IS NOT NULL)", name="ck_mensagem_saida_numero"),
        CheckConstraint("texto <> ''", name="ck_mensagem_saida_texto"),
        CheckConstraint("tentativas >= 0", name="ck_mensagem_saida_tentativas"),
        Index("ix_mensagem_saida_fila", "status", "proxima_tentativa_em"),
        Index("ix_mensagem_saida_criada_em", "criada_em"),  # Atividade
        Index("ix_mensagem_saida_enviada_em", "enviada_em"),  # último registro do WhatsApp
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
    numero: Mapped[str | None] = mapped_column(Text)  # E.164, só destino "individual"; nunca em log
    expira_em: Mapped[datetime | None] = mapped_column(DATA)  # validade própria (código de acesso: 5 min)


class EstadoNotificador(Base):
    """Uma linha (id 1): quando o serviço notificador terminou o último ciclo (Serviços mostra se está vivo)."""

    __tablename__ = "estado_notificador"
    __table_args__ = (CheckConstraint("id = 1", name="ck_estado_notificador_linha_unica"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    ultimo_ciclo_em: Mapped[datetime | None] = mapped_column(DATA)


class EstadoManutencao(Base):
    """Uma linha (id 1): quando o serviço de manutenção passou pelo último ciclo (Serviços mostra se está vivo)."""

    __tablename__ = "estado_manutencao"
    __table_args__ = (CheckConstraint("id = 1", name="ck_estado_manutencao_linha_unica"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    ultimo_ciclo_em: Mapped[datetime | None] = mapped_column(DATA)


class ExecucaoManutencao(Base):
    """Uma execução diária do serviço de manutenção: backup do banco e limpeza do histórico."""

    __tablename__ = "execucao_manutencao"
    __table_args__ = (Index("ix_execucao_manutencao_inicio", "inicio"),)  # Atividade

    id: Mapped[int] = mapped_column(primary_key=True)
    inicio: Mapped[datetime] = mapped_column(DATA)
    fim: Mapped[datetime | None] = mapped_column(DATA)
    status: Mapped[StatusManutencao] = mapped_column(_enum(StatusManutencao, "status_manutencao"))
    arquivo: Mapped[str | None] = mapped_column(Text)  # nome do backup diário (sem a pasta)
    tamanho_bytes: Mapped[int | None] = mapped_column(BigInteger)
    enviado_r2: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    apagados: Mapped[dict[str, int] | None] = mapped_column(JSONB)  # linhas apagadas por tabela
    erro: Mapped[str | None] = mapped_column(Text)


class EstadoAviso(Base):
    """Um problema por (tipo, chave) dos avisos do WhatsApp que agrupam: aberto até `resolver`.
    `ultimo_envio_em` nulo: nada saiu ainda (tipo desligado)."""

    __tablename__ = "estado_aviso"
    __table_args__ = (
        CheckConstraint("ocorrencias >= 0", name="ck_estado_aviso_ocorrencias"),
        Index("ix_estado_aviso_ultimo_em", "ultimo_em"),  # Atividade
    )

    tipo: Mapped[str] = mapped_column(Text, primary_key=True)
    chave: Mapped[str] = mapped_column(Text, primary_key=True)
    aberto: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    primeiro_em: Mapped[datetime] = mapped_column(DATA)
    ultimo_em: Mapped[datetime] = mapped_column(DATA)
    ultimo_envio_em: Mapped[datetime | None] = mapped_column(DATA)
    ocorrencias: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class ConfigAviso(Base):
    """Liga/desliga de cada tipo de aviso (Configurações → Avisos). Linha ausente = ligado_padrao do catálogo."""

    __tablename__ = "config_aviso"

    tipo: Mapped[str] = mapped_column(Text, primary_key=True)
    ligado: Mapped[bool] = mapped_column(Boolean)


class SinalServico(Base):
    """Último sinal de vida de cada serviço sem tabela de estado própria (coletores e casador); o vigia lê."""

    __tablename__ = "sinal_servico"

    servico: Mapped[str] = mapped_column(Text, primary_key=True)
    ultimo_em: Mapped[datetime] = mapped_column(DATA)
    # Preenchido num desligamento limpo (SIGTERM); o vigia não avisa de serviço parado de propósito.
    encerrado_em: Mapped[datetime | None] = mapped_column(DATA)


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
    finalidade: Mapped[str] = mapped_column(Text)  # "casamento" | "avaliacao" | "termos" | "idioma"
    modelo: Mapped[str] = mapped_column(Text)
    tokens_entrada: Mapped[int] = mapped_column(Integer)
    tokens_saida: Mapped[int] = mapped_column(Integer)
    custo_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    ok: Mapped[bool] = mapped_column(Boolean)
    erro: Mapped[str | None] = mapped_column(Text)


# Edição de idioma do anúncio que a IA devolve no veredito (`indefinido`: o anúncio não deixa claro).
IDIOMAS_ANUNCIO = ("pt", "en", "ja", "outro", "indefinido")


class AvaliacaoIA(Base):
    """Veredito da IA para um par (anúncio, produto da Liga). `assinatura` = hash dos dados enviados:
    mudou, reavalia. `aplicada_em` preenchida quando o automático confirmou ou ignorou o anúncio
    (fica mesmo se o usuário desfizer, para o automático não reaplicar). `idioma_anuncio`: a edição de
    idioma do anúncio lida pela IA (`IDIOMAS_ANUNCIO`); vazia nas avaliações de antes da regra de idioma."""

    __tablename__ = "avaliacao_ia"
    __table_args__ = (
        UniqueConstraint("anuncio_id", "produto_id", name="uq_avaliacao_ia_par"),
        CheckConstraint("confianca BETWEEN 0 AND 100", name="ck_avaliacao_ia_confianca"),
        CheckConstraint(
            "idioma_anuncio IN ('pt', 'en', 'ja', 'outro', 'indefinido')", name="ck_avaliacao_ia_idioma_anuncio"
        ),
        Index("ix_avaliacao_ia_chamada", "chamada_id"),  # limpeza das chamadas antigas
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
    idioma_anuncio: Mapped[str | None] = mapped_column(Text)


class Usuario(Base):
    """Pessoa que entra no front. `numero` em E.164 fica só no banco: nunca em log, tela (só mascarado) ou grupo.
    `superadmin`: o dono do sistema (um só, sempre admin e ativo; a API nunca o rebaixa, desativa ou encerra)."""

    __tablename__ = "usuario"
    __table_args__ = (
        UniqueConstraint("numero", name="uq_usuario_numero"),
        CheckConstraint("nome <> ''", name="ck_usuario_nome"),
        CheckConstraint("numero ~ '^[+][1-9][0-9]{9,14}$'", name="ck_usuario_numero"),
        CheckConstraint("NOT superadmin OR (papel = 'admin' AND ativo)", name="ck_usuario_superadmin"),
        # no máximo um superadmin (o dono do sistema): criado e trocado só pelos comandos locais
        Index("uq_usuario_superadmin", "superadmin", unique=True, postgresql_where=text("superadmin")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(Text)
    numero: Mapped[str] = mapped_column(Text)
    papel: Mapped[Papel] = mapped_column(_enum(Papel, "papel"))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    superadmin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    criado_em: Mapped[datetime] = mapped_column(DATA)


class AcaoGestao(Base):
    """Registro das ações de gestão feitas no site. Nunca é apagado; `usuario_id` nulo = usuário apagado
    (ON DELETE SET NULL)."""

    __tablename__ = "acao_gestao"
    __table_args__ = (Index("ix_acao_gestao_em", "em"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id", ondelete="SET NULL"))
    em: Mapped[datetime] = mapped_column(DATA)
    tipo: Mapped[TipoAcaoGestao] = mapped_column(_enum(TipoAcaoGestao, "tipo_acao_gestao"))
    detalhe: Mapped[dict] = mapped_column(JSONB)


class CodigoAcesso(Base):
    """Código de 6 dígitos pedido no login (só o hash). Só o último do usuário vale; 5 tentativas erradas o invalidam."""

    __tablename__ = "codigo_acesso"
    __table_args__ = (
        CheckConstraint("tentativas >= 0", name="ck_codigo_acesso_tentativas"),
        Index("ix_codigo_acesso_usuario", "usuario_id", "criado_em"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    hash_codigo: Mapped[str] = mapped_column(Text)
    criado_em: Mapped[datetime] = mapped_column(DATA)
    expira_em: Mapped[datetime] = mapped_column(DATA)
    tentativas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    usado_em: Mapped[datetime | None] = mapped_column(DATA)


class Sessao(Base):
    """Sessão do front (cookie `sessao`; no banco só o hash do token). Vence em 30 dias, renovada a cada uso."""

    __tablename__ = "sessao"
    __table_args__ = (
        UniqueConstraint("hash_token", name="uq_sessao_hash_token"),
        Index("ix_sessao_usuario", "usuario_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    hash_token: Mapped[str] = mapped_column(Text)
    aparelho: Mapped[str] = mapped_column(Text)  # "Chrome · Windows"
    criada_em: Mapped[datetime] = mapped_column(DATA)
    ultimo_uso_em: Mapped[datetime] = mapped_column(DATA)
    expira_em: Mapped[datetime] = mapped_column(DATA)
    encerrada_em: Mapped[datetime | None] = mapped_column(DATA)


class PermissaoPapel(Base):
    """Grade papel × permissão (Gestão → Acessos). Linha ausente = padrão do código (`api/permissoes.py`);
    `permissao` é texto livre de propósito: cada fase acrescenta as suas sem migração. Linhas do admin são ignoradas."""

    __tablename__ = "permissao_papel"

    papel: Mapped[Papel] = mapped_column(_enum(Papel, "papel"), primary_key=True)
    permissao: Mapped[str] = mapped_column(Text, primary_key=True)
    permitido: Mapped[bool] = mapped_column(Boolean)


class PedidoCodigo(Base):
    """Cada pedido de código, para o limite por número (3 em 15 min; o resultado antigo 'limite_total' só existe em
    linhas de antes de 2026-10-24, quando havia um limite total), e cada tentativa de
    entrar (`resultado = 'entrada'`, até 10 por número em 15 min). Sem o número: só o hash, também de números sem
    cadastro (o limite vale para eles, senão o 429 revelaria quem tem cadastro)."""

    __tablename__ = "pedido_codigo"
    __table_args__ = (
        CheckConstraint(
            "resultado IN ('aceito', 'limite_numero', 'limite_total', 'entrada')", name="ck_pedido_codigo_resultado"
        ),
        Index("ix_pedido_codigo_em", "em"),
        Index("ix_pedido_codigo_numero", "numero_hash", "em"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    em: Mapped[datetime] = mapped_column(DATA)
    numero_hash: Mapped[str] = mapped_column(Text)
    resultado: Mapped[str] = mapped_column(Text)
