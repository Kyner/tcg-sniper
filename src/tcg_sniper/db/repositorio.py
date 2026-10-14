"""Operações de banco usadas pelo coletor e pelo agendador."""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tcg_sniper.coletor_liga.modelos import ItemListagem, Resumo
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    COLETOR_LIGA,
    Coleta,
    EstadoColetor,
    EstadoColetorTipo,
    PrecoAtualLiga,
    PrecoListagem,
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
    resumo: Resumo,
    agora: datetime,
) -> None:
    """Acrescenta o resumo ao histórico (append-only) e atualiza só o grupo "resumo" do preço atual."""
    precos = {
        "preco_min": resumo.preco_min,
        "preco_medio": resumo.preco_medio,
        "preco_max": resumo.preco_max,
        "num_lojas": resumo.num_lojas,
    }
    s.add(ResumoPreco(produto_id=produto_id, coleta_id=coleta_id, coletado_em=agora, **precos))
    atual = {**precos, "resumo_coleta_id": coleta_id, "resumo_em": agora}
    s.execute(
        pg_insert(PrecoAtualLiga)
        .values(produto_id=produto_id, **atual)
        .on_conflict_do_update(index_elements=[PrecoAtualLiga.produto_id], set_=atual)
    )
    s.flush()


def _primeiro_de_cada(itens: Sequence[ItemListagem]) -> dict[str, ItemListagem]:
    unicos: dict[str, ItemListagem] = {}
    for item in itens:
        unicos.setdefault(item.liga_id, item)
    return unicos


def upsert_catalogo(s: Session, itens: Sequence[ItemListagem], agora: datetime) -> int:
    """Insere ou atualiza produtos do catálogo. Nunca altera `ativo`. Retorna quantos são novos.

    Atualiza `nome`, `url` e `visto_ultimo_em`; `tipo` só é preenchido se ainda estiver vazio
    (um produto listado em duas categorias não fica trocando de tipo). `liga_id` repetido na
    lista vale uma vez (a primeira ocorrência).
    """
    unicos = _primeiro_de_cada(itens)
    if not unicos:
        return 0
    existentes = set(s.scalars(select(ProdutoLiga.liga_id).where(ProdutoLiga.liga_id.in_(unicos))))
    for i in unicos.values():
        stmt = pg_insert(ProdutoLiga).values(
            liga_id=i.liga_id,
            nome=i.nome,
            url=i.url,
            tipo=i.tipo,
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
                "tipo": func.coalesce(ProdutoLiga.tipo, stmt.excluded.tipo),
            },
        )
        s.execute(stmt)
    return len(unicos.keys() - existentes)


def gravar_listagem(s: Session, coleta_id: int, itens: Sequence[ItemListagem], agora: datetime) -> int:
    """Grava uma listagem de categoria: catálogo (upsert), histórico do preço "à partir de"
    (append-only) e o grupo "listagem" do preço atual. Retorna quantos produtos são novos.

    Um produto que já apareceu nesta coleta (outra categoria) não é contado como novo de novo e
    mantém o primeiro preço visto na coleta, tanto no histórico quanto no preço atual.
    """
    unicos = _primeiro_de_cada(itens)
    novos = upsert_catalogo(s, list(unicos.values()), agora)
    if not unicos:
        return novos
    ids = dict(
        s.execute(select(ProdutoLiga.liga_id, ProdutoLiga.id).where(ProdutoLiga.liga_id.in_(unicos))).all()
    )
    for liga_id, item in unicos.items():
        produto_id = ids[liga_id]
        s.execute(
            pg_insert(PrecoListagem)
            .values(produto_id=produto_id, coleta_id=coleta_id, preco_a_partir=item.preco_a_partir, coletado_em=agora)
            .on_conflict_do_nothing(index_elements=[PrecoListagem.produto_id, PrecoListagem.coleta_id])
        )
        atual = {"preco_a_partir": item.preco_a_partir, "listagem_coleta_id": coleta_id, "listagem_em": agora}
        s.execute(
            pg_insert(PrecoAtualLiga)
            .values(produto_id=produto_id, **atual)
            .on_conflict_do_update(
                index_elements=[PrecoAtualLiga.produto_id],
                set_=atual,
                where=PrecoAtualLiga.listagem_coleta_id.is_distinct_from(coleta_id),
            )
        )
    s.flush()
    return novos


ID_COLETOR = {COLETOR_LIGA: 1, COLETOR_AMAZON: 2}


def obter_estado(s: Session, agora: datetime | None = None, coletor: str = COLETOR_LIGA) -> EstadoColetor:
    id_estado = ID_COLETOR[coletor]
    s.execute(
        pg_insert(EstadoColetor)
        .values(
            id=id_estado,
            coletor=coletor,
            estado=EstadoColetorTipo.ATIVO,
            execucao_solicitada=False,
            atualizado_em=agora or agora_utc(),
        )
        .on_conflict_do_nothing(index_elements=[EstadoColetor.id])
    )
    return s.get(EstadoColetor, id_estado, populate_existing=True)


def pausar_por_desafio(s: Session, motivo: str, agora: datetime, coletor: str = COLETOR_LIGA) -> None:
    _mudar_estado(s, EstadoColetorTipo.PAUSADO_DESAFIO, motivo, agora, coletor)


def pausar(s: Session, motivo: str, agora: datetime, coletor: str) -> None:
    """Pausa manual (admin) ou por erros seguidos; só volta com retomar."""
    _mudar_estado(s, EstadoColetorTipo.PAUSADO, motivo, agora, coletor)


def _mudar_estado(s: Session, novo: EstadoColetorTipo, motivo: str, agora: datetime, coletor: str) -> None:
    estado = obter_estado(s, agora, coletor)
    estado.estado = novo
    estado.motivo = motivo
    estado.execucao_solicitada = False
    estado.atualizado_em = agora
    s.flush()


def retomar(s: Session, agora: datetime, coletor: str = COLETOR_LIGA) -> None:
    estado = obter_estado(s, agora, coletor)
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


def marcar_interrompidas(s: Session, agora: datetime, tipos: Sequence[TipoColeta]) -> int:
    """Fecha como falha as coletas `rodando` dos tipos do coletor que está subindo."""
    resultado = s.execute(
        update(Coleta)
        .where(Coleta.status == StatusColeta.RODANDO, Coleta.tipo.in_(tipos))
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
