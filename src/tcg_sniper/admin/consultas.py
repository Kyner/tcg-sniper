from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.orm import Session

from tcg_sniper.db.models import (
    ChamadaIA,
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
FINALIDADES_IA = ("todas", "casamento", "avaliacao")


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
