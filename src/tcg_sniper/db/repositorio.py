"""Operações de banco usadas pelo coletor e pelo agendador."""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tcg_sniper.coletor_liga.modelos import ItemCatalogo, Oferta
from tcg_sniper.coletor_liga.resumo import Resumo
from tcg_sniper.db.models import (
    Coleta,
    EstadoColetor,
    EstadoColetorTipo,
    OfertaLiga,
    PrecoAtualLiga,
    ProdutoLiga,
    ResumoPreco,
    StatusColeta,
    TipoColeta,
)


def agora_utc() -> datetime:
    return datetime.now(UTC)


def produtos_ativos(s: Session) -> list[ProdutoLiga]:
    consulta = select(ProdutoLiga).where(ProdutoLiga.ativo.is_(True)).order_by(ProdutoLiga.id)
    return list(s.scalars(consulta))


def iniciar_coleta(s: Session, tipo: TipoColeta, agora: datetime) -> Coleta:
    coleta = Coleta(
        tipo=tipo, iniciada_em=agora, status=StatusColeta.RODANDO, produtos_ok=0, produtos_falha=0
    )
    s.add(coleta)
    s.flush()
    return coleta


def status_final(ok: int, falha: int, limite_falha_pct: int) -> StatusColeta:
    if falha == 0:
        return StatusColeta.OK
    if falha * 100 > limite_falha_pct * (ok + falha):
        return StatusColeta.FALHA
    return StatusColeta.PARCIAL


def finalizar_coleta(
    s: Session,
    coleta_id: int,
    status: StatusColeta,
    ok: int,
    falha: int,
    agora: datetime,
    erro: str | None = None,
) -> None:
    s.execute(
        update(Coleta)
        .where(Coleta.id == coleta_id)
        .values(status=status, produtos_ok=ok, produtos_falha=falha, finalizada_em=agora, erro=erro)
    )


def gravar_precos_produto(
    s: Session,
    coleta_id: int,
    produto_id: int,
    ofertas: Sequence[Oferta],
    resumo: Resumo,
    agora: datetime,
) -> None:
    s.add_all(
        OfertaLiga(
            coleta_id=coleta_id,
            produto_id=produto_id,
            loja=o.loja,
            preco=o.preco,
            quantidade=o.quantidade,
            idioma=o.idioma,
            condicao=o.condicao,
            coletado_em=agora,
        )
        for o in ofertas
    )
    s.add(
        ResumoPreco(
            produto_id=produto_id,
            coleta_id=coleta_id,
            menor_preco_com_estoque=resumo.menor_preco_com_estoque,
            num_vendedores_com_estoque=resumo.num_vendedores_com_estoque,
            num_ofertas=resumo.num_ofertas,
            coletado_em=agora,
        )
    )
    valores = {
        "coleta_id": coleta_id,
        "menor_preco_com_estoque": resumo.menor_preco_com_estoque,
        "num_vendedores_com_estoque": resumo.num_vendedores_com_estoque,
        "num_ofertas": resumo.num_ofertas,
        "atualizado_em": agora,
    }
    s.execute(
        pg_insert(PrecoAtualLiga)
        .values(produto_id=produto_id, **valores)
        .on_conflict_do_update(index_elements=[PrecoAtualLiga.produto_id], set_=valores)
    )
    s.flush()


def upsert_catalogo(s: Session, itens: Sequence[ItemCatalogo], agora: datetime) -> int:
    """Insere ou atualiza produtos do catálogo. Nunca altera `ativo`. Retorna quantos são novos."""
    unicos = {i.liga_id: i for i in itens}
    if not unicos:
        return 0
    existentes = set(s.scalars(select(ProdutoLiga.liga_id).where(ProdutoLiga.liga_id.in_(unicos))))
    for i in unicos.values():
        stmt = pg_insert(ProdutoLiga).values(
            liga_id=i.liga_id,
            nome=i.nome,
            url=i.url,
            edicao=i.edicao,
            tipo=i.tipo,
            idioma=i.idioma,
            ativo=False,
            visto_primeiro_em=agora,
            visto_ultimo_em=agora,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[ProdutoLiga.liga_id],
            set_={
                "nome": stmt.excluded.nome,
                "url": stmt.excluded.url,
                "visto_ultimo_em": stmt.excluded.visto_ultimo_em,
                "edicao": func.coalesce(stmt.excluded.edicao, ProdutoLiga.edicao),
                "tipo": func.coalesce(stmt.excluded.tipo, ProdutoLiga.tipo),
                "idioma": func.coalesce(stmt.excluded.idioma, ProdutoLiga.idioma),
            },
        )
        s.execute(stmt)
    return len(unicos.keys() - existentes)


def obter_estado(s: Session, agora: datetime | None = None) -> EstadoColetor:
    s.execute(
        pg_insert(EstadoColetor)
        .values(
            id=1,
            estado=EstadoColetorTipo.ATIVO,
            execucao_solicitada=False,
            atualizado_em=agora or agora_utc(),
        )
        .on_conflict_do_nothing(index_elements=[EstadoColetor.id])
    )
    return s.get(EstadoColetor, 1, populate_existing=True)


def pausar_por_desafio(s: Session, motivo: str, agora: datetime) -> None:
    estado = obter_estado(s, agora)
    estado.estado = EstadoColetorTipo.PAUSADO_DESAFIO
    estado.motivo = motivo
    estado.execucao_solicitada = False
    estado.atualizado_em = agora
    s.flush()


def retomar(s: Session, agora: datetime) -> None:
    estado = obter_estado(s, agora)
    estado.estado = EstadoColetorTipo.ATIVO
    estado.motivo = None
    estado.execucao_solicitada = True
    estado.atualizado_em = agora
    s.flush()


def solicitar_execucao(s: Session, agora: datetime) -> None:
    estado = obter_estado(s, agora)
    estado.execucao_solicitada = True
    estado.atualizado_em = agora
    s.flush()


def consumir_solicitacao(s: Session, agora: datetime) -> bool:
    estado = obter_estado(s, agora)
    if estado.estado != EstadoColetorTipo.ATIVO or not estado.execucao_solicitada:
        return False
    estado.execucao_solicitada = False
    estado.atualizado_em = agora
    s.flush()
    return True


def marcar_interrompidas(s: Session, agora: datetime) -> int:
    resultado = s.execute(
        update(Coleta)
        .where(Coleta.status == StatusColeta.RODANDO)
        .values(status=StatusColeta.FALHA, erro="interrompida", finalizada_em=agora)
    )
    return resultado.rowcount


def ultima_coleta_sucesso(s: Session, tipo: TipoColeta) -> datetime | None:
    return s.scalar(
        select(func.max(Coleta.iniciada_em)).where(
            Coleta.tipo == tipo, Coleta.status.in_([StatusColeta.OK, StatusColeta.PARCIAL])
        )
    )


def coleta_iniciada_desde(s: Session, tipo: TipoColeta, desde: datetime) -> bool:
    total = s.scalar(
        select(func.count()).select_from(Coleta).where(Coleta.tipo == tipo, Coleta.iniciada_em >= desde)
    )
    return total > 0
