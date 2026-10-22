"""Catálogo da LigaMagic para a gestão: a lista (ativos e inativos) com filtros, a contagem e a alteração em lote
do monitoramento (`ativo`). Sem Jinja nem HTTP: o admin antigo usa `buscar_catalogo`, `alterar_ativo_em_lote` e
`alternar_ativo`; a API usa `linhas_catalogo`, `contar_filtro` e `aplicar_lote`."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import ColumnElement, case, func, select, update
from sqlalchemy.orm import Session

from tcg_sniper.consultas.catalogo import SITUACOES_PRODUTO, casa_nome, classificar
from tcg_sniper.db.models import Casamento, PrecoAtualAmazon, PrecoAtualLiga, ProdutoLiga, StatusCasamento

# --- admin antigo ---

FILTROS = ("todos", "ativos", "inativos", "novos")
JANELA_NOVOS = timedelta(days=7)
POR_PAGINA_ADMIN = 100


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
    por_pagina: int = POR_PAGINA_ADMIN,
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


# --- gestão (API) ---

Monitorado = Literal["todos", "sim", "nao"]
MONITORADO = ("todos", "sim", "nao")
POR_PAGINA = 25


@dataclass(frozen=True)
class FiltroCatalogo:
    """Os filtros da lista de gestão; a contagem e o lote usam os mesmos (o que se vê é o que se altera)."""

    busca: str = ""
    monitorado: Monitorado = "todos"
    categoria: str | None = None
    situacao: str | None = None  # uma de SITUACOES_PRODUTO; None = todas
    com_preco: bool = False


@dataclass(frozen=True)
class LinhaCatalogo:
    produto: ProdutoLiga
    preco_liga: Decimal | None
    lojas: int | None
    situacao_casamento: str  # SITUACOES_PRODUTO, pela regra de `classificar`
    pendentes: int
    confirmados: int
    ignorados: int
    melhor_amazon: Decimal | None  # menor preço atual entre os anúncios confirmados


@dataclass(frozen=True)
class PaginaCatalogo:
    itens: list[LinhaCatalogo]
    total: int
    pagina: int
    por_pagina: int


def _pares():
    """Contagem dos pares de cada produto, por status."""
    return (
        select(
            Casamento.produto_id,
            func.count().filter(Casamento.status == StatusCasamento.CONFIRMADO).label("confirmados"),
            func.count().filter(Casamento.status == StatusCasamento.PENDENTE).label("pendentes"),
            func.count().filter(Casamento.status == StatusCasamento.IGNORADO).label("ignorados"),
            func.count().label("total"),
        )
        .group_by(Casamento.produto_id)
        .subquery()
    )


def _validar(filtro: FiltroCatalogo) -> None:
    if filtro.monitorado not in MONITORADO:
        raise ValueError(f"monitorado desconhecido: {filtro.monitorado}")
    if filtro.situacao is not None and filtro.situacao not in SITUACOES_PRODUTO:
        raise ValueError(f"situação desconhecida: {filtro.situacao}")


def _consulta(filtro: FiltroCatalogo, *colunas):
    """SELECT das `colunas` sobre produto + preço da Liga + contagem de pares, com os filtros aplicados. A situação
    sai em SQL com a mesma regra de `classificar` (para filtrar e paginar no banco)."""
    _validar(filtro)
    pares = _pares()
    conf = func.coalesce(pares.c.confirmados, 0)
    pend = func.coalesce(pares.c.pendentes, 0)
    ign = func.coalesce(pares.c.ignorados, 0)
    total = func.coalesce(pares.c.total, 0)
    situacao = case(
        (conf > 0, "casado"), (pend > 0, "esperando_decisao"), (total > 0, "so_ignorados"), else_="sem_candidato"
    )
    condicoes: list[ColumnElement[bool]] = []
    if filtro.busca.strip():
        condicoes.append(casa_nome(filtro.busca))
    if filtro.monitorado == "sim":
        condicoes.append(ProdutoLiga.ativo.is_(True))
    elif filtro.monitorado == "nao":
        condicoes.append(ProdutoLiga.ativo.is_(False))
    if filtro.categoria:
        condicoes.append(ProdutoLiga.tipo == filtro.categoria)
    if filtro.com_preco:
        condicoes.append(PrecoAtualLiga.preco_a_partir.is_not(None))
    if filtro.situacao is not None:
        condicoes.append(situacao == filtro.situacao)
    colunas = colunas or (ProdutoLiga, PrecoAtualLiga, conf, pend, ign, total)
    return (
        select(*colunas)
        .select_from(ProdutoLiga)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .outerjoin(pares, pares.c.produto_id == ProdutoLiga.id)
        .where(*condicoes)
    )


def _melhores_amazon(s: Session, ids: list[int]) -> dict[int, Decimal]:
    if not ids:
        return {}
    consulta = (
        select(Casamento.produto_id, func.min(PrecoAtualAmazon.preco))
        .join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == Casamento.anuncio_id)
        .where(
            Casamento.produto_id.in_(ids),
            Casamento.status == StatusCasamento.CONFIRMADO,
            PrecoAtualAmazon.preco.is_not(None),
        )
        .group_by(Casamento.produto_id)
    )
    return dict(s.execute(consulta).all())


def _montar(s: Session, linhas) -> list[LinhaCatalogo]:
    melhores = _melhores_amazon(s, [produto.id for produto, *_ in linhas])
    return [
        LinhaCatalogo(
            produto=produto,
            preco_liga=atual.preco_a_partir if atual else None,
            lojas=atual.num_lojas if atual else None,
            situacao_casamento=classificar(confirmados, pendentes, total),
            pendentes=pendentes,
            confirmados=confirmados,
            ignorados=ignorados,
            melhor_amazon=melhores.get(produto.id),
        )
        for produto, atual, confirmados, pendentes, ignorados, total in linhas
    ]


def linhas_catalogo(
    s: Session,
    *,
    busca: str,
    monitorado: Monitorado,
    categoria: str | None,
    situacao: str | None,
    com_preco: bool,
    pagina: int,
    por_pagina: int = POR_PAGINA,
) -> PaginaCatalogo:
    """Uma página do catálogo inteiro (monitorados primeiro, depois por nome). Página além do fim vem vazia."""
    filtro = FiltroCatalogo(busca, monitorado, categoria, situacao, com_preco)
    total = contar_filtro(s, filtro)
    pagina = max(pagina, 1)
    consulta = (
        _consulta(filtro)
        .order_by(ProdutoLiga.ativo.desc(), ProdutoLiga.nome, ProdutoLiga.id)
        .limit(por_pagina)
        .offset((pagina - 1) * por_pagina)
    )
    return PaginaCatalogo(_montar(s, s.execute(consulta).all()), total, pagina, por_pagina)


def linha_produto(s: Session, produto_id: int) -> LinhaCatalogo | None:
    """A linha de um produto (ativo ou não), como sai na lista."""
    linhas = s.execute(_consulta(FiltroCatalogo()).where(ProdutoLiga.id == produto_id)).all()
    return _montar(s, linhas)[0] if linhas else None


def contar_filtro(s: Session, filtro: FiltroCatalogo) -> int:
    """Quantos produtos o filtro pega (o `total` de `linhas_catalogo` com os mesmos filtros)."""
    return s.scalar(select(func.count()).select_from(_consulta(filtro, ProdutoLiga.id).subquery())) or 0


def contar_ids(s: Session, ids: list[int]) -> int:
    """Quantos dos `ids` existem no catálogo."""
    if not ids:
        return 0
    return s.scalar(select(func.count()).select_from(ProdutoLiga).where(ProdutoLiga.id.in_(ids))) or 0


def aplicar_lote(s: Session, ativo: bool, alvo: FiltroCatalogo | list[int], agora: datetime) -> int:
    """Define `ativo` nos produtos do filtro (todas as páginas) ou da lista de ids; devolve quantos mudaram de fato.
    `agora` fica na assinatura para os filtros que dependerem do tempo."""
    if isinstance(alvo, FiltroCatalogo):
        # sem correlação: a subconsulta lê produto_liga por conta própria (não a linha do UPDATE)
        selecao = ProdutoLiga.id.in_(_consulta(alvo, ProdutoLiga.id).correlate(None))
    elif alvo:
        selecao = ProdutoLiga.id.in_(alvo)
    else:
        return 0
    comando = (
        update(ProdutoLiga)
        .where(selecao, ProdutoLiga.ativo != ativo)
        .values(ativo=ativo)
        .execution_options(synchronize_session=False)
    )
    return s.execute(comando).rowcount
