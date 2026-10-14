from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.orm import Session

from tcg_sniper.db.models import (
    Coleta,
    PrecoAtualLiga,
    PrecoListagem,
    ProdutoLiga,
    ResumoPreco,
    StatusColeta,
    TipoColeta,
)

FILTROS = ("todos", "ativos", "inativos", "novos")
JANELA_NOVOS = timedelta(days=7)
POR_PAGINA = 100


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def listar_coletas(s: Session, tipos: Sequence[TipoColeta], limite: int = 10) -> list[Coleta]:
    consulta = select(Coleta).where(Coleta.tipo.in_(tipos)).order_by(Coleta.id.desc()).limit(limite)
    return list(s.scalars(consulta))


def coleta_em_andamento(s: Session, tipos: Sequence[TipoColeta]) -> bool:
    consulta = select(Coleta.id).where(Coleta.status == StatusColeta.RODANDO, Coleta.tipo.in_(tipos)).limit(1)
    return s.scalar(consulta) is not None


def listar_categorias(s: Session) -> list[str]:
    return list(
        s.scalars(
            select(ProdutoLiga.tipo).where(ProdutoLiga.tipo.is_not(None)).distinct().order_by(ProdutoLiga.tipo)
        )
    )


def condicoes_catalogo(
    busca: str | None, filtro: str, categoria: str | None, com_preco: bool, agora: datetime
) -> list[ColumnElement[bool]]:
    """Condições WHERE do catálogo; compartilhadas pela listagem, pela contagem e pela alteração em lote.

    `com_preco` referencia `PrecoAtualLiga`, então a consulta que as usar precisa do outer join."""
    condicoes: list[ColumnElement[bool]] = []
    if busca and busca.strip():
        condicoes.append(ProdutoLiga.nome.ilike(f"%{_escapar_like(busca.strip())}%", escape="\\"))
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
