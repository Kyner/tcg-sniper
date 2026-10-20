"""Casamento por par (anúncio da Amazon × produto da Liga): a única porta de escrita dos pares.

Regras (spec 2026-10-19-casamento-por-par-design.md):
- ignorado vale só para o par: o mesmo anúncio pode estar pendente ou ignorado para vários produtos;
- confirmado para no máximo um produto (índice único parcial `uq_casamento_confirmado`);
- confirmar um par ignora os outros pendentes do anúncio (origem `outro_confirmado`);
- tirar a confirmação (desfazer ou ignorar o confirmado) reabre esses `outro_confirmado`;
- desfazer e "Reavaliar com a IA" marcam o par para a IA reavaliar mesmo com os dados iguais;
- o automático da IA (origem `automatico_ia`) nunca passa por cima de uma decisão sua (`manual` ou
  `sugerido_ia`): confirmar, ignorar e trocar devolvem o par como está, sem mudar nada (`decidido_por_voce`
  diz se foi o caso).

- nunca fica par pendente num anúncio confirmado para outro produto: desfazer e reavaliar o deixam
  ignorado com origem `outro_confirmado`.

Toda escrita trava antes a linha do anúncio (confirmações do mesmo anúncio viram fila). Quem registra
vários anúncios numa transação só (a busca, `registrar_visto` em laço) trava em ordem crescente de
`anuncio_id` — como `reavaliar_produto` — ou faz commit por anúncio; senão duas transações podem se
travar mutuamente (deadlock). Este módulo só depende dos modelos (e, num import tardio, do encerramento das
oportunidades): o repositorio_amazon importa este, nunca o contrário."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, Select, and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tcg_sniper.db.models import (
    AnuncioAmazon,
    AvaliacaoIA,
    Casamento,
    MotivoEncerramento,
    Oportunidade,
    OrigemCasamento,
    StatusCasamento,
)

PENDENTE, CONFIRMADO, IGNORADO = StatusCasamento.PENDENTE, StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO
# Ignorados que "Reavaliar com a IA" devolve a pendente. `manual` e `sugerido_ia` são decisões suas (no
# admin) e não mudam, nem os confirmados; `outro_confirmado` só se o anúncio não é confirmado de ninguém.
ORIGENS_REAVALIAVEIS = (OrigemCasamento.AUTOMATICO_IA, OrigemCasamento.OUTRO_CONFIRMADO)


# Origens de uma decisão sua no admin: `manual` e `sugerido_ia` (você decidiu vendo o selo da IA).
ORIGENS_SUAS = (OrigemCasamento.MANUAL, OrigemCasamento.SUGERIDO_IA)


def decidido_por_voce(par: Casamento | None) -> bool:
    """O par tem uma decisão sua (confirmado ou ignorado com origem `manual` ou `sugerido_ia`): o automático
    não muda."""
    return par is not None and par.status is not PENDENTE and par.origem in ORIGENS_SUAS


def _automatico_barrado(par: Casamento | None, origem: OrigemCasamento) -> bool:
    return origem is OrigemCasamento.AUTOMATICO_IA and decidido_por_voce(par)


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


def produto_casado(s: Session, produto_id: int) -> bool:
    """O produto tem algum par confirmado."""
    return s.scalar(produtos_casados().where(Casamento.produto_id == produto_id).limit(1)) is not None


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
    """Encerra (motivo `casamento_desfeito`) as oportunidades abertas do anúncio, menos as de
    `exceto_produto_id`. Pelo encerramento: grava o motivo e avisa "alerta corrigido" a quem viu o alerta."""
    from tcg_sniper.oportunidades import encerramento  # import tardio: este módulo é base do repositorio_amazon

    condicoes = [Oportunidade.anuncio_id == anuncio_id, Oportunidade.fechada_em.is_(None)]
    if exceto_produto_id is not None:
        condicoes.append(Oportunidade.produto_id != exceto_produto_id)
    ids = list(s.scalars(select(Oportunidade.id).where(*condicoes).order_by(Oportunidade.id)))
    return sum(encerramento.encerrar(s, op_id, MotivoEncerramento.CASAMENTO_DESFEITO, agora) for op_id in ids)


def _zerar_aplicada(s: Session, anuncio_id: int, produto_id: int) -> None:
    """A avaliação antiga do par deixa de valer como "já aplicada" (o automático pode decidir de novo)."""
    s.execute(
        update(AvaliacaoIA)
        .where(AvaliacaoIA.anuncio_id == anuncio_id, AvaliacaoIA.produto_id == produto_id)
        .values(aplicada_em=None)
        .execution_options(synchronize_session="fetch")
    )


def _reabrir_outro_confirmado(s: Session, anuncio_id: int) -> None:
    """O anúncio deixou de ser confirmado: os pares `outro_confirmado` voltam a pendente, marcados para a
    IA reavaliar (sem a marca, a etapa só de descoberta do casador não os veria)."""
    s.execute(
        update(Casamento)
        .where(
            Casamento.anuncio_id == anuncio_id,
            Casamento.status == IGNORADO,
            Casamento.origem == OrigemCasamento.OUTRO_CONFIRMADO,
        )
        .values(status=PENDENTE, origem=None, revisado_em=None, reavaliar=True)
        .execution_options(synchronize_session="fetch")
    )


def _outro_confirmado(par: Casamento, agora: datetime) -> None:
    """O anúncio do par é confirmado para outro produto: o par não pode ficar pendente."""
    par.status, par.origem, par.revisado_em, par.reavaliar = IGNORADO, OrigemCasamento.OUTRO_CONFIRMADO, agora, False


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
    Devolve (par, criado). Trava o anúncio antes (uma confirmação em andamento termina primeiro)."""
    travar_anuncio(s, anuncio_id)
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
    anúncio já é confirmado de outro produto; o mesmo par já confirmado volta como está. Origem
    `automatico_ia` num par que você decidiu (`decidido_por_voce`): devolve o par como está."""
    travar_anuncio(s, anuncio_id)
    atual = confirmado_do_anuncio(s, anuncio_id)
    if atual is not None:
        if atual.produto_id == produto_id:
            return atual
        raise JaConfirmado(anuncio_id, atual.produto_id)
    existente = obter_par(s, anuncio_id, produto_id)
    if _automatico_barrado(existente, origem):
        return existente
    try:
        # Criar e confirmar no mesmo SAVEPOINT: se o índice recusar, o par recém-criado também volta.
        with s.begin_nested():
            _inserir_par(s, anuncio_id, produto_id, agora, status=PENDENTE, origem=None, revisado_em=None)
            par = obter_par(s, anuncio_id, produto_id)
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
    `outro_confirmado`. Sem o par: None. Origem `automatico_ia` num par que você decidiu
    (`decidido_por_voce`): devolve o par como está."""
    if obter_par(s, anuncio_id, produto_id) is None:
        return None
    travar_anuncio(s, anuncio_id)
    par = obter_par(s, anuncio_id, produto_id)
    if _automatico_barrado(par, origem):
        return par
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
    `outro_confirmado` com o anúncio ainda confirmado: JaConfirmado. Outro par com o anúncio confirmado para
    outro produto: vira ignorado `outro_confirmado` (nunca pendente). Sem o par: None."""
    if obter_par(s, anuncio_id, produto_id) is None:
        return None
    travar_anuncio(s, anuncio_id)
    par = obter_par(s, anuncio_id, produto_id)
    outro = confirmado_do_anuncio(s, anuncio_id)
    if outro is not None and outro.produto_id != produto_id:
        if par.origem is OrigemCasamento.OUTRO_CONFIRMADO:
            raise JaConfirmado(anuncio_id, outro.produto_id)
        _outro_confirmado(par, agora)
        s.flush()
        return par
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
    houver, vira ignorado `manual` (suas oportunidades fecham). Origem `automatico_ia` com o confirmado
    atual ou o par novo decididos por você: devolve o confirmado atual (ou o par) como está."""
    travar_anuncio(s, anuncio_id)
    atual = confirmado_do_anuncio(s, anuncio_id)
    if atual is not None and atual.produto_id == produto_id:
        return atual
    if _automatico_barrado(atual, origem):
        return atual
    if _automatico_barrado(novo := obter_par(s, anuncio_id, produto_id), origem):
        return novo
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
    ignorados pelo automático (`automatico_ia`) ou `outro_confirmado` cujo anúncio não é mais confirmado de
    ninguém. Decisões suas (`manual`, `sugerido_ia`) e confirmados não mudam. Par desses cujo anúncio é
    confirmado de outro produto vira ignorado `outro_confirmado` (nunca pendente; não conta). Trava os
    anúncios em ordem crescente de id. Devolve quantos pares marcou para reavaliar."""
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
    marcados = sum(_reabrir(s, alvo.anuncio_id, produto_id, agora, ORIGENS_REAVALIAVEIS) == REABERTO for alvo in alvos)
    s.flush()
    return marcados


REABERTO, CONFIRMADO_EM_OUTRO, PULADO = "reaberto", "confirmado_em_outro", "pulado"


def _reabrir(s: Session, anuncio_id: int, produto_id: int, agora: datetime, origens) -> str:
    """Volta o par a pendente marcado para reavaliar (zera o "já aplicada" da avaliação) se ainda está
    pendente ou ignorado com uma de `origens`. Anúncio confirmado de outro produto: o par vira ignorado
    `outro_confirmado` (nunca pendente). Trava o anúncio e relê o par antes: uma confirmação em andamento
    termina antes da decisão."""
    travar_anuncio(s, anuncio_id)
    par = obter_par(s, anuncio_id, produto_id)
    if par.status is CONFIRMADO or (par.status is IGNORADO and par.origem not in origens):
        return PULADO
    if confirmado_do_anuncio(s, anuncio_id) is not None:  # confirmado de outro produto
        if par.origem is not OrigemCasamento.OUTRO_CONFIRMADO:
            _outro_confirmado(par, agora)
        return CONFIRMADO_EM_OUTRO
    par.status, par.origem, par.revisado_em, par.reavaliar = PENDENTE, None, None, True
    _zerar_aplicada(s, anuncio_id, produto_id)
    return REABERTO


# Motivo de quem o automático ignorou por ser em inglês (regra de idioma antiga), sem os casos de japonês.
_MOTIVO_INGLES = ("%inglês%", "%ingles%", "%english%", "%idioma%")
_MOTIVO_JAPONES = ("%japon%", "%japanese%")


@dataclass(frozen=True)
class Reabertura:
    encontrados: int  # ignorados pelo automático com motivo de inglês/idioma (sem japonês)
    reabertos: int  # voltaram (ou voltariam) a pendente, marcados para a IA reavaliar
    confirmados_em_outro: int  # anúncio confirmado de outro produto: ficam ignorados (`outro_confirmado`)


def reabrir_ignorados_por_ingles(s: Session, agora: datetime, *, aplicar: bool) -> Reabertura:
    """Regra de idioma revista (2026-10-19): reabre para a IA reavaliar os pares ignorados pelo automático
    (só origem `automatico_ia`; decisões suas não mudam) cujo motivo da IA fala de inglês ou idioma e não de
    japonês, com a mesma lógica do "Reavaliar com a IA". Sem `aplicar`, só conta (tudo num SAVEPOINT
    desfeito). Trava os anúncios em ordem crescente de id."""
    motivo = AvaliacaoIA.motivo
    alvos = s.execute(
        select(Casamento.anuncio_id, Casamento.produto_id)
        .join(
            AvaliacaoIA,
            and_(AvaliacaoIA.anuncio_id == Casamento.anuncio_id, AvaliacaoIA.produto_id == Casamento.produto_id),
        )
        .where(
            Casamento.status == IGNORADO,
            Casamento.origem == OrigemCasamento.AUTOMATICO_IA,
            or_(*(motivo.ilike(m) for m in _MOTIVO_INGLES)),
            *(~motivo.ilike(m) for m in _MOTIVO_JAPONES),
        )
        .order_by(Casamento.anuncio_id, Casamento.produto_id)
    ).all()
    savepoint = s.begin_nested()
    resultados = [_reabrir(s, anuncio_id, produto_id, agora, (OrigemCasamento.AUTOMATICO_IA,)) for anuncio_id, produto_id in alvos]
    s.flush()
    if aplicar:
        savepoint.commit()
    else:
        savepoint.rollback()
    return Reabertura(len(alvos), resultados.count(REABERTO), resultados.count(CONFIRMADO_EM_OUTRO))


def marcar_reavaliado(s: Session, anuncio_id: int, produto_id: int) -> None:
    """O casador gravou uma avaliação nova do par: a marca de reavaliar sai."""
    s.execute(
        update(Casamento)
        .where(Casamento.anuncio_id == anuncio_id, Casamento.produto_id == produto_id)
        .values(reavaliar=False)
        .execution_options(synchronize_session="fetch")
    )
    s.flush()
