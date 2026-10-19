"""Casamento por par (anúncio da Amazon × produto da Liga): a única porta de escrita dos pares.

Regras (spec 2026-10-19-casamento-por-par-design.md):
- ignorado vale só para o par: o mesmo anúncio pode estar pendente ou ignorado para vários produtos;
- confirmado para no máximo um produto (índice único parcial `uq_casamento_confirmado`);
- confirmar um par ignora os outros pendentes do anúncio (origem `outro_confirmado`);
- tirar a confirmação (desfazer ou ignorar o confirmado) reabre esses `outro_confirmado`;
- desfazer e "Reavaliar com a IA" marcam o par para a IA reavaliar mesmo com os dados iguais.

Toda escrita trava antes a linha do anúncio (confirmações do mesmo anúncio viram fila). Este módulo só
depende dos modelos: o repositorio_amazon importa este, nunca o contrário."""

from datetime import datetime

from sqlalchemy import ColumnElement, Select, and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tcg_sniper.db.models import AnuncioAmazon, AvaliacaoIA, Casamento, Oportunidade, OrigemCasamento, StatusCasamento

PENDENTE, CONFIRMADO, IGNORADO = StatusCasamento.PENDENTE, StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO
# Ignorados que "Reavaliar com a IA" devolve a pendente (decisões `manual` e confirmados não mudam).
ORIGENS_REAVALIAVEIS = (OrigemCasamento.SUGERIDO_IA, OrigemCasamento.AUTOMATICO_IA, OrigemCasamento.OUTRO_CONFIRMADO)


class JaConfirmado(Exception):
    """O anúncio já está confirmado para outro produto (`produto_id`): nada mudou."""

    def __init__(self, anuncio_id: int, produto_id: int):
        super().__init__("já confirmado para outro produto")
        self.anuncio_id = anuncio_id
        self.produto_id = produto_id


def condicao_confirmado(anuncio_id) -> ColumnElement[bool]:
    """Para `join(Casamento, condicao_confirmado(AnuncioAmazon.id))`: o par confirmado do anúncio."""
    return and_(Casamento.anuncio_id == anuncio_id, Casamento.status == CONFIRMADO)


def produtos_casados() -> Select:
    """Subconsulta: ids dos produtos com algum par confirmado."""
    return select(Casamento.produto_id).where(Casamento.status == CONFIRMADO)


def obter_par(s: Session, anuncio_id: int, produto_id: int, *, travar: bool = False) -> Casamento | None:
    return s.get(
        Casamento, (anuncio_id, produto_id), with_for_update=True if travar else None, populate_existing=True
    )


def confirmado_do_anuncio(s: Session, anuncio_id: int) -> Casamento | None:
    return s.scalar(select(Casamento).where(condicao_confirmado(anuncio_id)).execution_options(populate_existing=True))


def travar_anuncio(s: Session, anuncio_id: int) -> AnuncioAmazon:
    """`SELECT … FOR UPDATE` na linha do anúncio (NoResultFound se não existe)."""
    return s.get_one(AnuncioAmazon, anuncio_id, with_for_update=True)


def fechar_oportunidades(s: Session, anuncio_id: int, agora: datetime, exceto_produto_id: int | None = None) -> int:
    condicoes = [Oportunidade.anuncio_id == anuncio_id, Oportunidade.fechada_em.is_(None)]
    if exceto_produto_id is not None:
        condicoes.append(Oportunidade.produto_id != exceto_produto_id)
    resultado = s.execute(
        update(Oportunidade).where(*condicoes).values(fechada_em=agora).execution_options(synchronize_session="fetch")
    )
    s.flush()
    return resultado.rowcount


def _zerar_aplicada(s: Session, anuncio_id: int, produto_id: int) -> None:
    """A avaliação antiga do par deixa de valer como "já aplicada" (o automático pode decidir de novo)."""
    s.execute(
        update(AvaliacaoIA)
        .where(AvaliacaoIA.anuncio_id == anuncio_id, AvaliacaoIA.produto_id == produto_id)
        .values(aplicada_em=None)
        .execution_options(synchronize_session="fetch")
    )


def _reabrir_outro_confirmado(s: Session, anuncio_id: int) -> None:
    s.execute(
        update(Casamento)
        .where(
            Casamento.anuncio_id == anuncio_id,
            Casamento.status == IGNORADO,
            Casamento.origem == OrigemCasamento.OUTRO_CONFIRMADO,
        )
        .values(status=PENDENTE, origem=None, revisado_em=None)
        .execution_options(synchronize_session="fetch")
    )


def _inserir_par(s: Session, anuncio_id: int, produto_id: int, agora: datetime, **valores) -> bool:
    """Cria o par se não existe. Devolve se criou."""
    stmt = (
        pg_insert(Casamento)
        .values(anuncio_id=anuncio_id, produto_id=produto_id, visto_primeiro_em=agora, visto_ultimo_em=agora, **valores)
        .on_conflict_do_nothing(index_elements=[Casamento.anuncio_id, Casamento.produto_id])
        .returning(Casamento.anuncio_id)
    )
    return s.execute(stmt).first() is not None


def registrar_visto(s: Session, anuncio_id: int, produto_id: int, agora: datetime) -> tuple[Casamento, bool]:
    """A busca do produto viu o anúncio. Par existente: só `visto_ultimo_em` (status não muda). Par novo:
    pendente; se o anúncio já é confirmado de outro produto, ignorado com origem `outro_confirmado`.
    Devolve (par, criado)."""
    par = obter_par(s, anuncio_id, produto_id)
    if par is not None:
        par.visto_ultimo_em = agora
        s.flush()
        return par, False
    if confirmado_do_anuncio(s, anuncio_id) is None:
        valores = {"status": PENDENTE, "origem": None, "revisado_em": None}
    else:
        valores = {"status": IGNORADO, "origem": OrigemCasamento.OUTRO_CONFIRMADO, "revisado_em": agora}
    criado = _inserir_par(s, anuncio_id, produto_id, agora, **valores)
    return obter_par(s, anuncio_id, produto_id), criado


def confirmar(
    s: Session, anuncio_id: int, produto_id: int, agora: datetime, origem: OrigemCasamento = OrigemCasamento.MANUAL
) -> Casamento:
    """Confirma o par (criando-o se não existe), ignora os outros pendentes do anúncio (`outro_confirmado`) e
    fecha as oportunidades abertas do anúncio para outros produtos. Lança JaConfirmado (nada muda) se o
    anúncio já é confirmado de outro produto; o mesmo par já confirmado volta como está."""
    travar_anuncio(s, anuncio_id)
    atual = confirmado_do_anuncio(s, anuncio_id)
    if atual is not None:
        if atual.produto_id == produto_id:
            return atual
        raise JaConfirmado(anuncio_id, atual.produto_id)
    _inserir_par(s, anuncio_id, produto_id, agora, status=PENDENTE, origem=None, revisado_em=None)
    par = obter_par(s, anuncio_id, produto_id)
    try:
        with s.begin_nested():
            par.status, par.origem, par.revisado_em, par.reavaliar = CONFIRMADO, origem, agora, False
            s.flush()
    except IntegrityError:  # outra transação confirmou sem passar pela trava: o índice único segura
        outro = confirmado_do_anuncio(s, anuncio_id)
        raise JaConfirmado(anuncio_id, outro.produto_id if outro is not None else produto_id) from None
    s.execute(
        update(Casamento)
        .where(Casamento.anuncio_id == anuncio_id, Casamento.produto_id != produto_id, Casamento.status == PENDENTE)
        .values(status=IGNORADO, origem=OrigemCasamento.OUTRO_CONFIRMADO, revisado_em=agora, reavaliar=False)
        .execution_options(synchronize_session="fetch")
    )
    fechar_oportunidades(s, anuncio_id, agora, exceto_produto_id=produto_id)
    s.flush()
    return par


def ignorar(
    s: Session, anuncio_id: int, produto_id: int, agora: datetime, origem: OrigemCasamento = OrigemCasamento.MANUAL
) -> Casamento | None:
    """Ignora o par (só ele). Se era o confirmado: fecha as oportunidades do anúncio e reabre os
    `outro_confirmado`. Sem o par: None."""
    if obter_par(s, anuncio_id, produto_id) is None:
        return None
    travar_anuncio(s, anuncio_id)
    par = obter_par(s, anuncio_id, produto_id)
    era_confirmado = par.status is CONFIRMADO
    par.status, par.origem, par.revisado_em, par.reavaliar = IGNORADO, origem, agora, False
    s.flush()
    if era_confirmado:
        fechar_oportunidades(s, anuncio_id, agora)
        _reabrir_outro_confirmado(s, anuncio_id)
    s.flush()
    return par


def desfazer(s: Session, anuncio_id: int, produto_id: int, agora: datetime) -> Casamento | None:
    """Volta o par a pendente (origem e revisão zeradas) e o marca para a IA reavaliar mesmo com os dados
    iguais. Se era o confirmado: fecha as oportunidades do anúncio e reabre os `outro_confirmado`. Par
    `outro_confirmado` com o anúncio ainda confirmado: JaConfirmado. Sem o par: None."""
    if obter_par(s, anuncio_id, produto_id) is None:
        return None
    travar_anuncio(s, anuncio_id)
    par = obter_par(s, anuncio_id, produto_id)
    if par.origem is OrigemCasamento.OUTRO_CONFIRMADO and (outro := confirmado_do_anuncio(s, anuncio_id)) is not None:
        raise JaConfirmado(anuncio_id, outro.produto_id)
    era_confirmado = par.status is CONFIRMADO
    par.status, par.origem, par.revisado_em, par.reavaliar = PENDENTE, None, None, True
    s.flush()
    _zerar_aplicada(s, anuncio_id, produto_id)
    if era_confirmado:
        fechar_oportunidades(s, anuncio_id, agora)
        _reabrir_outro_confirmado(s, anuncio_id)
    s.flush()
    return par


def trocar(
    s: Session, anuncio_id: int, produto_id: int, agora: datetime, origem: OrigemCasamento = OrigemCasamento.MANUAL
) -> Casamento:
    """Confirma (anúncio, produto) — criando o par se não existe — e o confirmado anterior do anúncio, se
    houver, vira ignorado `manual` (suas oportunidades fecham)."""
    travar_anuncio(s, anuncio_id)
    atual = confirmado_do_anuncio(s, anuncio_id)
    if atual is not None and atual.produto_id == produto_id:
        return atual
    if atual is not None:
        atual.status, atual.origem, atual.revisado_em, atual.reavaliar = IGNORADO, OrigemCasamento.MANUAL, agora, False
        s.flush()
    return confirmar(s, anuncio_id, produto_id, agora, origem)


def casar_asin(s: Session, produto_id: int, asin: str, agora: datetime, titulo_provisorio: str) -> AnuncioAmazon:
    """Link colado: cria o anúncio (título provisório) ou marca o existente como visto, e confirma o par com
    origem `manual`, trocando o confirmado anterior se houver. Quem chama prioriza o produto na fila."""
    anuncio = s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.asin == asin))
    if anuncio is None:
        anuncio = AnuncioAmazon(
            asin=asin, titulo=titulo_provisorio, url=f"https://www.amazon.com.br/dp/{asin}",
            visto_primeiro_em=agora, visto_ultimo_em=agora,
        )
        s.add(anuncio)
    else:
        anuncio.visto_ultimo_em = agora
    s.flush()
    trocar(s, anuncio.id, produto_id, agora, OrigemCasamento.MANUAL)
    return anuncio


def reavaliar_produto(s: Session, produto_id: int, agora: datetime) -> int:
    """"Reavaliar com a IA": volta a pendente (marcados para reavaliar) os pares do produto pendentes ou
    ignorados pela IA (`sugerido_ia`, `automatico_ia`, `outro_confirmado` cujo anúncio não é mais confirmado
    de ninguém). Decisões `manual` e confirmados não mudam. Devolve quantos pares marcou."""
    alvos = s.scalars(
        select(Casamento)
        .where(
            Casamento.produto_id == produto_id,
            or_(
                Casamento.status == PENDENTE,
                and_(Casamento.status == IGNORADO, Casamento.origem.in_(ORIGENS_REAVALIAVEIS)),
            ),
        )
        .order_by(Casamento.anuncio_id)
        .execution_options(populate_existing=True)
    ).all()
    marcados = 0
    for par in alvos:
        if par.origem is OrigemCasamento.OUTRO_CONFIRMADO and confirmado_do_anuncio(s, par.anuncio_id) is not None:
            continue
        par.status, par.origem, par.revisado_em, par.reavaliar = PENDENTE, None, None, True
        _zerar_aplicada(s, par.anuncio_id, produto_id)
        marcados += 1
    s.flush()
    return marcados


def marcar_reavaliado(s: Session, anuncio_id: int, produto_id: int) -> None:
    """O casador gravou uma avaliação nova do par: a marca de reavaliar sai."""
    s.execute(
        update(Casamento)
        .where(Casamento.anuncio_id == anuncio_id, Casamento.produto_id == produto_id)
        .values(reavaliar=False)
        .execution_options(synchronize_session="fetch")
    )
    s.flush()
