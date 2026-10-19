"""Termos de busca alternativos (busca alternativa): gerados pela IA uma vez por produto e guardados.

Um produto ativo da fila está "em seca" quando não tem par confirmado e nenhuma busca dele criou par
pendente novo há `SECA` (sem nunca ter criado: desde que entrou na fila)."""

from collections.abc import Collection, Sequence
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session

from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db.models import FilaAmazon, ProdutoLiga, TermoBusca

SECA = timedelta(days=7)
MAX_TERMOS = 3
TERMO_MAX = 80
IDIOMAS = ("pt", "en")


def _condicao_seca(agora: datetime):
    return and_(
        FilaAmazon.produto_id.not_in(repo_casamento.produtos_casados()),
        func.coalesce(FilaAmazon.ultimo_par_novo_em, FilaAmazon.entrou_em) <= agora - SECA,
    )


def termos_do_produto(s: Session, produto_id: int) -> list[TermoBusca]:
    return list(s.scalars(select(TermoBusca).where(TermoBusca.produto_id == produto_id).order_by(TermoBusca.ordem)))


def em_seca(s: Session, produto_id: int, agora: datetime) -> bool:
    consulta = select(FilaAmazon.produto_id).where(FilaAmazon.produto_id == produto_id, _condicao_seca(agora))
    return s.scalar(consulta) is not None


def marcar_tentativa(s: Session, produto_id: int, agora: datetime) -> None:
    """A IA respondeu (com ou sem termo válido): só tenta de novo depois de `SECA`; o pedido do admin sai."""
    s.execute(
        update(FilaAmazon)
        .where(FilaAmazon.produto_id == produto_id)
        .values(termos_tentados_em=agora, termos_pedidos_em=None)
    )
    s.flush()


def _validar(termos: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    if not 1 <= len(termos) <= MAX_TERMOS:
        raise ValueError(f"de 1 a {MAX_TERMOS} termos; recebeu {len(termos)}")
    limpos: list[tuple[str, str]] = []
    vistos: set[str] = set()
    for termo, idioma in termos:
        termo = termo.strip()
        if not 1 <= len(termo) <= TERMO_MAX:
            raise ValueError(f"termo com {len(termo)} caracteres (de 1 a {TERMO_MAX})")
        if idioma not in IDIOMAS:
            raise ValueError(f"idioma {idioma!r} (só {', '.join(IDIOMAS)})")
        if termo.casefold() in vistos:
            raise ValueError(f"termo repetido: {termo!r}")
        vistos.add(termo.casefold())
        limpos.append((termo, idioma))
    return limpos


def guardar_termos(s: Session, produto_id: int, termos: Sequence[tuple[str, str]], agora: datetime) -> list[TermoBusca]:
    """Substitui os termos do produto por `termos` ((termo, idioma), 1 a 3) e marca a tentativa. Confere antes
    de gravar (ValueError, nada muda): cada termo com 1 a 80 caracteres sem os espaços das pontas (guardado
    assim), idioma `pt` ou `en`, sem repetir (sem diferenciar maiúsculas)."""
    termos = _validar(termos)
    s.execute(delete(TermoBusca).where(TermoBusca.produto_id == produto_id))
    novos = [
        TermoBusca(produto_id=produto_id, termo=termo, idioma=idioma, ordem=ordem, criado_em=agora)
        for ordem, (termo, idioma) in enumerate(termos, start=1)
    ]
    s.add_all(novos)
    s.flush()
    marcar_tentativa(s, produto_id, agora)
    return novos


def pedir_termos(s: Session, produto_id: int, agora: datetime) -> bool:
    """Botão "Gerar termos de busca": o casador gera (ou regenera) no próximo ciclo. False sem linha na fila."""
    resultado = s.execute(
        update(FilaAmazon).where(FilaAmazon.produto_id == produto_id).values(termos_pedidos_em=agora)
    )
    s.flush()
    return resultado.rowcount > 0


def produtos_para_gerar_termos(
    s: Session, agora: datetime, limite: int, excluir: Collection[int] = ()
) -> list[ProdutoLiga]:
    """Até `limite` produtos ativos: primeiro os pedidos no admin (mais antigos primeiro, mesmo com termos
    guardados), depois os em seca sem termos e sem tentativa nos últimos 7 dias (os mais secos primeiro).
    `excluir`: produtos que ficam de fora (o casador põe os que esperam depois de uma falha)."""
    base = select(ProdutoLiga).join(FilaAmazon, FilaAmazon.produto_id == ProdutoLiga.id).where(ProdutoLiga.ativo.is_(True))
    if excluir:
        base = base.where(ProdutoLiga.id.not_in(list(excluir)))
    pedidos = list(
        s.scalars(
            base.where(FilaAmazon.termos_pedidos_em.is_not(None))
            .order_by(FilaAmazon.termos_pedidos_em, ProdutoLiga.id)
            .limit(limite)
        )
    )
    if len(pedidos) >= limite:
        return pedidos
    tem_termo = select(TermoBusca.id).where(TermoBusca.produto_id == ProdutoLiga.id).exists()
    secos = s.scalars(
        base.where(
            FilaAmazon.termos_pedidos_em.is_(None),
            _condicao_seca(agora),
            ~tem_termo,
            or_(FilaAmazon.termos_tentados_em.is_(None), FilaAmazon.termos_tentados_em <= agora - SECA),
        )
        .order_by(func.coalesce(FilaAmazon.ultimo_par_novo_em, FilaAmazon.entrou_em), ProdutoLiga.id)
        .limit(limite - len(pedidos))
    )
    return pedidos + list(secos)
