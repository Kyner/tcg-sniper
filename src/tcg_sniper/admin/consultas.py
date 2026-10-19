from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import ColumnElement, case, func, or_, select, update
from sqlalchemy.orm import Session

from tcg_sniper.db.models import (
    AnuncioAmazon,
    Casamento,
    ChamadaIA,
    Coleta,
    ConferenciaCheckout,
    ExecucaoManutencao,
    OfertaAmazon,
    Oportunidade,
    PrecoAtualLiga,
    PrecoListagem,
    ProdutoLiga,
    ResumoPreco,
    SituacaoCheckout,
    StatusCasamento,
    StatusColeta,
    TipoColeta,
)

FILTROS = ("todos", "ativos", "inativos", "novos")
JANELA_NOVOS = timedelta(days=7)
POR_PAGINA = 100


def _escapar_like(texto: str) -> str:
    return texto.replace("\x00", "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


STATUS_HISTORICO = ("todos", "ok", "parcial", "falha", "pausada_desafio")
POR_PAGINA_HISTORICO = 20


def paginar[T](itens: list[T], pagina: int, por_pagina: int) -> tuple[list[T], int, int]:
    """Itens da página pedida (limitada entre 1 e a última), a página efetiva e o total de páginas."""
    paginas = max(1, -(-len(itens) // por_pagina))
    pagina = min(max(pagina, 1), paginas)
    inicio = (pagina - 1) * por_pagina
    return itens[inicio : inicio + por_pagina], pagina, paginas


def historico_coletas(
    s: Session, tipos: Sequence[TipoColeta], status: str, pagina: int, por_pagina: int = POR_PAGINA_HISTORICO
) -> tuple[list[Coleta], int, int]:
    condicoes = [Coleta.tipo.in_(tipos)]
    if status != "todos":
        condicoes.append(Coleta.status == StatusColeta(status))
    total = s.scalar(select(func.count()).select_from(Coleta).where(*condicoes)) or 0
    paginas = max(1, -(-total // por_pagina))
    pagina = min(max(pagina, 1), paginas)
    consulta = (
        select(Coleta).where(*condicoes).order_by(Coleta.id.desc()).offset((pagina - 1) * por_pagina).limit(por_pagina)
    )
    return list(s.scalars(consulta)), pagina, paginas


SITUACOES_IA = ("todas", "com_erro")
FINALIDADES_IA = ("todas", "casamento", "avaliacao", "termos")


def historico_chamadas_ia(
    s: Session, situacao: str, finalidade: str, pagina: int, por_pagina: int = POR_PAGINA_HISTORICO
) -> tuple[list[ChamadaIA], int, int]:
    """Chamadas à OpenAI, das mais recentes, com os filtros da aba IA de Logs."""
    condicoes = []
    if situacao == "com_erro":
        condicoes.append(ChamadaIA.ok.is_(False))
    if finalidade != "todas":
        condicoes.append(ChamadaIA.finalidade == finalidade)
    total = s.scalar(select(func.count()).select_from(ChamadaIA).where(*condicoes)) or 0
    paginas = max(1, -(-total // por_pagina))
    pagina = min(max(pagina, 1), paginas)
    consulta = (
        select(ChamadaIA)
        .where(*condicoes)
        .order_by(ChamadaIA.em.desc(), ChamadaIA.id.desc())
        .offset((pagina - 1) * por_pagina)
        .limit(por_pagina)
    )
    return list(s.scalars(consulta)), pagina, paginas


def ultima_coleta_sucesso(s: Session, tipos: Sequence[TipoColeta]) -> Coleta | None:
    return s.scalar(
        select(Coleta)
        .where(Coleta.tipo.in_(tipos), Coleta.status.in_([StatusColeta.OK, StatusColeta.PARCIAL]))
        .order_by(Coleta.id.desc())
        .limit(1)
    )


def ultima_coleta_finalizada(s: Session, tipos: Sequence[TipoColeta]) -> Coleta | None:
    return s.scalar(
        select(Coleta)
        .where(Coleta.tipo.in_(tipos), Coleta.finalizada_em.is_not(None))
        .order_by(Coleta.id.desc())
        .limit(1)
    )


def coleta_em_andamento(s: Session, tipos: Sequence[TipoColeta]) -> bool:
    consulta = select(Coleta.id).where(Coleta.status == StatusColeta.RODANDO, Coleta.tipo.in_(tipos)).limit(1)
    return s.scalar(consulta) is not None


def listar_categorias(s: Session) -> list[str]:
    return list(
        s.scalars(
            select(ProdutoLiga.tipo).where(ProdutoLiga.tipo.is_not(None)).distinct().order_by(ProdutoLiga.tipo)
        )
    )


def casa_nome(busca: str) -> ColumnElement[bool]:
    """O texto aparece no nome do produto ou no nome em inglês (`%` e `_` valem como texto)."""
    padrao = f"%{_escapar_like(busca.strip())}%"
    return or_(ProdutoLiga.nome.ilike(padrao, escape="\\"), ProdutoLiga.nome_en.ilike(padrao, escape="\\"))


def condicoes_catalogo(
    busca: str | None, filtro: str, categoria: str | None, com_preco: bool, agora: datetime
) -> list[ColumnElement[bool]]:
    """Condições WHERE do catálogo; compartilhadas pela listagem, pela contagem e pela alteração em lote.

    `com_preco` referencia `PrecoAtualLiga`, então a consulta que as usar precisa do outer join."""
    condicoes: list[ColumnElement[bool]] = []
    if busca and busca.strip():
        condicoes.append(casa_nome(busca))
    if filtro == "ativos":
        condicoes.append(ProdutoLiga.ativo.is_(True))
    elif filtro == "inativos":
        condicoes.append(ProdutoLiga.ativo.is_(False))
    elif filtro == "novos":
        condicoes.append(ProdutoLiga.visto_primeiro_em >= agora - JANELA_NOVOS)
    if categoria:
        condicoes.append(ProdutoLiga.tipo == categoria)
    if com_preco:
        condicoes.append(PrecoAtualLiga.preco_a_partir.is_not(None))
    return condicoes


def alterar_ativo_em_lote(
    s: Session,
    ativo: bool,
    busca: str | None,
    filtro: str,
    categoria: str | None,
    com_preco: bool,
    agora: datetime,
) -> int:
    """Define `ativo` em todos os produtos do filtro (todas as páginas); devolve quantos mudaram de fato."""
    condicoes = condicoes_catalogo(busca, filtro, categoria, com_preco, agora)
    if com_preco:
        juncao = ProdutoLiga.__table__.outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        condicoes_update = [ProdutoLiga.id.in_(select(ProdutoLiga.id).select_from(juncao).where(*condicoes))]
    else:
        condicoes_update = condicoes
    comando = (
        update(ProdutoLiga)
        .where(*condicoes_update, ProdutoLiga.ativo != ativo)
        .values(ativo=ativo)
        .execution_options(synchronize_session=False)
    )
    return s.execute(comando).rowcount


def buscar_catalogo(
    s: Session,
    busca: str | None,
    filtro: str,
    agora: datetime,
    categoria: str | None = None,
    com_preco: bool = False,
    pagina: int = 1,
    por_pagina: int = POR_PAGINA,
) -> tuple[list[tuple[ProdutoLiga, PrecoAtualLiga | None]], int, int, int]:
    """Uma página do catálogo: (linhas, total de produtos com os filtros, página efetiva, total de páginas).

    A página pedida além do fim é reduzida para a última."""
    condicoes = condicoes_catalogo(busca, filtro, categoria, com_preco, agora)
    juncao = ProdutoLiga.__table__.outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
    total = s.scalar(select(func.count()).select_from(juncao).where(*condicoes)) or 0
    paginas = max(1, -(-total // por_pagina))
    pagina = min(max(pagina, 1), paginas)
    consulta = (
        select(ProdutoLiga, PrecoAtualLiga)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(*condicoes)
        .order_by(ProdutoLiga.ativo.desc(), ProdutoLiga.nome, ProdutoLiga.id)
        .limit(por_pagina)
        .offset((pagina - 1) * por_pagina)
    )
    return [(produto, atual) for produto, atual in s.execute(consulta)], total, pagina, paginas


def alternar_ativo(s: Session, produto_id: int) -> tuple[ProdutoLiga, PrecoAtualLiga | None] | None:
    produto = s.get(ProdutoLiga, produto_id)
    if produto is None:
        return None
    produto.ativo = not produto.ativo
    s.flush()
    return produto, s.get(PrecoAtualLiga, produto_id)


def detalhe_produto(
    s: Session, produto_id: int, limite_historico: int = 90
) -> tuple[ProdutoLiga, PrecoAtualLiga | None, list[ResumoPreco], list[PrecoListagem]] | None:
    """Produto, preço atual, histórico de venda (resumo) e histórico do preço "à partir de"."""
    produto = s.get(ProdutoLiga, produto_id)
    if produto is None:
        return None
    historico_resumo = list(
        s.scalars(
            select(ResumoPreco)
            .where(ResumoPreco.produto_id == produto_id)
            .order_by(ResumoPreco.coletado_em.desc())
            .limit(limite_historico)
        )
    )
    historico_listagem = list(
        s.scalars(
            select(PrecoListagem)
            .where(PrecoListagem.produto_id == produto_id)
            .order_by(PrecoListagem.coletado_em.desc())
            .limit(limite_historico)
        )
    )
    return produto, s.get(PrecoAtualLiga, produto_id), historico_resumo, historico_listagem


SITUACOES_CHECKOUT = ("todas", *(situacao.value for situacao in SituacaoCheckout))


def _pagina(total: int, pagina: int, por_pagina: int) -> tuple[int, int]:
    paginas = max(1, -(-total // por_pagina))
    return min(max(pagina, 1), paginas), paginas


def _produto_da_linha(anuncio_id, instante) -> ColumnElement:
    """Nome do produto de uma linha de log do anúncio no `instante`: o da oportunidade aberta naquela hora;
    sem ela, o par do anúncio (o confirmado primeiro, senão o mexido por último). Assim a linha antiga
    continua com produto depois de o par ser desfeito, ignorado ou trocado."""
    da_oportunidade = (
        select(Oportunidade.produto_id)
        .where(
            Oportunidade.anuncio_id == anuncio_id,
            Oportunidade.aberta_em <= instante,
            or_(Oportunidade.fechada_em.is_(None), Oportunidade.fechada_em >= instante),
        )
        .order_by(Oportunidade.aberta_em.desc(), Oportunidade.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    do_par = (
        select(Casamento.produto_id)
        .where(Casamento.anuncio_id == anuncio_id)
        .order_by(
            case((Casamento.status == StatusCasamento.CONFIRMADO, 0), else_=1),
            func.greatest(Casamento.revisado_em, Casamento.visto_ultimo_em).desc(),
            Casamento.produto_id,
        )
        .limit(1)
        .scalar_subquery()
    )
    return (
        select(ProdutoLiga.nome)
        .where(ProdutoLiga.id == func.coalesce(da_oportunidade, do_par))
        .scalar_subquery()
    )


@dataclass(frozen=True)
class LinhaConferencia:
    conferencia: ConferenciaCheckout
    asin: str
    produto: str | None


def historico_conferencias(
    s: Session, situacao: str, pagina: int, por_pagina: int = POR_PAGINA_HISTORICO
) -> tuple[list[LinhaConferencia], int, int]:
    """Conferências de checkout, das mais recentes, com o filtro de situação da aba Checkout."""
    condicoes = [] if situacao == "todas" else [ConferenciaCheckout.situacao == SituacaoCheckout(situacao)]
    total = s.scalar(select(func.count()).select_from(ConferenciaCheckout).where(*condicoes)) or 0
    pagina, paginas = _pagina(total, pagina, por_pagina)
    consulta = (
        select(
            ConferenciaCheckout, AnuncioAmazon.asin,
            _produto_da_linha(ConferenciaCheckout.anuncio_id, ConferenciaCheckout.em),
        )
        .join(AnuncioAmazon, AnuncioAmazon.id == ConferenciaCheckout.anuncio_id)
        .where(*condicoes)
        .order_by(ConferenciaCheckout.em.desc(), ConferenciaCheckout.id.desc())
        .offset((pagina - 1) * por_pagina)
        .limit(por_pagina)
    )
    return [LinhaConferencia(c, asin, nome) for c, asin, nome in s.execute(consulta)], pagina, paginas


@dataclass(frozen=True)
class LinhaMonitor:
    lida_em: datetime
    asin: str
    produto: str | None
    ofertas: int
    melhor_preco: Decimal | None
    melhor_vendedor: str | None


def historico_monitor(
    s: Session, pagina: int, por_pagina: int = POR_PAGINA_HISTORICO
) -> tuple[list[LinhaMonitor], int, int]:
    """Leituras do monitor (uma por anúncio e instante), das mais recentes, com nº de ofertas e a melhor.
    Leituras sem nenhuma oferta (anúncio indisponível) não aparecem."""
    leituras = (
        select(
            OfertaAmazon.anuncio_id,
            OfertaAmazon.lida_em,
            func.count().label("ofertas"),
            func.max(case((OfertaAmazon.melhor, OfertaAmazon.preco))).label("melhor_preco"),
            func.max(case((OfertaAmazon.melhor, OfertaAmazon.vendedor_nome))).label("melhor_vendedor"),
        )
        .group_by(OfertaAmazon.anuncio_id, OfertaAmazon.lida_em)
        .subquery()
    )
    total = s.scalar(select(func.count()).select_from(leituras)) or 0
    pagina, paginas = _pagina(total, pagina, por_pagina)
    consulta = (
        select(
            leituras.c.lida_em, AnuncioAmazon.asin, _produto_da_linha(leituras.c.anuncio_id, leituras.c.lida_em),
            leituras.c.ofertas, leituras.c.melhor_preco, leituras.c.melhor_vendedor,
        )
        .join(AnuncioAmazon, AnuncioAmazon.id == leituras.c.anuncio_id)
        .order_by(leituras.c.lida_em.desc(), AnuncioAmazon.id)
        .offset((pagina - 1) * por_pagina)
        .limit(por_pagina)
    )
    return [LinhaMonitor(*linha) for linha in s.execute(consulta)], pagina, paginas


def historico_manutencao(
    s: Session, pagina: int, por_pagina: int = POR_PAGINA_HISTORICO
) -> tuple[list[ExecucaoManutencao], int, int]:
    """Execuções do serviço de manutenção (backup + limpeza), das mais recentes."""
    total = s.scalar(select(func.count()).select_from(ExecucaoManutencao)) or 0
    pagina, paginas = _pagina(total, pagina, por_pagina)
    consulta = (
        select(ExecucaoManutencao)
        .order_by(ExecucaoManutencao.inicio.desc(), ExecucaoManutencao.id.desc())
        .offset((pagina - 1) * por_pagina)
        .limit(por_pagina)
    )
    return list(s.scalars(consulta)), pagina, paginas
