from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcg_sniper.db.models import Coleta, PrecoAtualLiga, ProdutoLiga, ResumoPreco

FILTROS = ("todos", "ativos", "inativos", "novos")
JANELA_NOVOS = timedelta(days=7)


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def listar_coletas(s: Session, limite: int = 10) -> list[Coleta]:
    return list(s.scalars(select(Coleta).order_by(Coleta.id.desc()).limit(limite)))


def buscar_catalogo(
    s: Session, busca: str | None, filtro: str, agora: datetime, limite: int = 500
) -> list[tuple[ProdutoLiga, PrecoAtualLiga | None]]:
    consulta = select(ProdutoLiga, PrecoAtualLiga).outerjoin(
        PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id
    )
    if busca and busca.strip():
        consulta = consulta.where(ProdutoLiga.nome.ilike(f"%{_escapar_like(busca.strip())}%", escape="\\"))
    if filtro == "ativos":
        consulta = consulta.where(ProdutoLiga.ativo.is_(True))
    elif filtro == "inativos":
        consulta = consulta.where(ProdutoLiga.ativo.is_(False))
    elif filtro == "novos":
        consulta = consulta.where(ProdutoLiga.visto_primeiro_em >= agora - JANELA_NOVOS)
    consulta = consulta.order_by(ProdutoLiga.ativo.desc(), ProdutoLiga.nome).limit(limite)
    return [(produto, atual) for produto, atual in s.execute(consulta)]


def alternar_ativo(s: Session, produto_id: int) -> tuple[ProdutoLiga, PrecoAtualLiga | None] | None:
    produto = s.get(ProdutoLiga, produto_id)
    if produto is None:
        return None
    produto.ativo = not produto.ativo
    s.flush()
    return produto, s.get(PrecoAtualLiga, produto_id)


def detalhe_produto(
    s: Session, produto_id: int, limite_historico: int = 90
) -> tuple[ProdutoLiga, PrecoAtualLiga | None, list[ResumoPreco]] | None:
    produto = s.get(ProdutoLiga, produto_id)
    if produto is None:
        return None
    historico = list(
        s.scalars(
            select(ResumoPreco)
            .where(ResumoPreco.produto_id == produto_id)
            .order_by(ResumoPreco.coletado_em.desc())
            .limit(limite_historico)
        )
    )
    return produto, s.get(PrecoAtualLiga, produto_id), historico
