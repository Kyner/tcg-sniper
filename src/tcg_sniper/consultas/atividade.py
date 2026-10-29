"""Linha do tempo da Atividade (gestão): as 6 abas de Logs e a tela Mensagens numa lista só.

Cada fonte (uma tabela) é lida já filtrada, da mais recente para a mais antiga, com keyset
`(em, fonte, id) < cursor` e `LIMIT limite + 1`; as listas se juntam aqui e o corte sai daqui. Empate no
mesmo instante: o nome da fonte desempata, depois o id. O cursor é o base64 de `em|fonte|id` da última
linha mostrada. As leituras do monitor (~200/h) só entram com o filtro "leitura do monitor" ou com busca
(decisão 5 do plano da fase 3B). O detalhe vem na própria linha (sem segunda rota).
"""

import base64
import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import ColumnElement, Text, and_, case, cast, exists, func, not_, or_, select, tuple_, union
from sqlalchemy.orm import Session

from tcg_sniper.avisos.catalogo import CATALOGO, TipoAviso
from tcg_sniper.coletor_liga.esfriamento import TIPOS_LIGA
from tcg_sniper.configuracoes.grupos import campo as campo_config
from tcg_sniper.consultas.catalogo import casa_nome, escapar_like
from tcg_sniper.consultas.historico import produto_id_da_linha
from tcg_sniper.db.models import (
    AcaoGestao,
    AnuncioAmazon,
    AvaliacaoIA,
    Casamento,
    ChamadaIA,
    Coleta,
    ConferenciaCheckout,
    EstadoAviso,
    ExecucaoManutencao,
    MensagemSaida,
    OfertaAmazon,
    Oportunidade,
    ProdutoLiga,
    SituacaoCheckout,
    StatusColeta,
    StatusManutencao,
    StatusMensagem,
    TipoAcaoGestao,
    TipoColeta,
    Usuario,
)
from tcg_sniper.formatacao import formatar_brl, formatar_bytes, formatar_milhar
from tcg_sniper.gestao.servicos import COLETOR, MENSAGENS, Servico
from tcg_sniper.oportunidades import motor

OQue = Literal[
    "coleta_liga", "busca", "leitura_monitor", "checkout", "ia", "mensagem", "backup", "aviso", "acao_gestao"
]
Situacao = Literal["ok", "parcial", "falha"]
FiltroSituacao = Literal["ok", "parcial", "falha", "problemas", "pendente"]  # "pendente": só mensagens na fila
Destino = Literal["admin", "oportunidades", "individual"]
Detalhe = dict[str, str | int | None]

POR_PAGINA = 50
INTERROMPIDA = "interrompida"  # erro das coletas fechadas por `marcar_interrompidas` (reinício do serviço)
SEM_USUARIO = "admin antigo"  # ação gravada sem usuário (admin antigo, senha única) ou usuário apagado

# Fontes: o nome da tabela, que também desempata linhas do mesmo instante (ordem alfabética, decrescente).
COLETA, OFERTA, CHECKOUT, IA = "coleta", "oferta_amazon", "conferencia_checkout", "chamada_ia"
MENSAGEM, MANUTENCAO, AVISO, ACAO = "mensagem_saida", "execucao_manutencao", "estado_aviso", "acao_gestao"
FONTES = (COLETA, OFERTA, CHECKOUT, IA, MENSAGEM, MANUTENCAO, AVISO, ACAO)


@dataclass(frozen=True)
class FiltroAtividade:
    servico: Servico | None
    o_que: OQue | None
    situacao: FiltroSituacao | None
    de: datetime | None  # inclusive
    ate: datetime | None  # inclusive
    busca: str | None  # nome do produto (pt ou en), ASIN ou texto/erro da linha
    mostrar_reinicios: bool = False
    mostrar_texto_mensagem: bool = True  # False: sem `ver_mensagens`; o texto não sai nem entra na busca
    mostrar_valores_configuracao: bool = False  # False: sem `ver_configuracoes`; só os rótulos dos campos salvos
    destino: Destino | None = None  # só mensagens: com destino, as outras fontes não entram na lista


@dataclass(frozen=True)
class LinhaAtividade:
    chave: str  # "fonte:id"
    em: datetime
    servico: Servico | None
    o_que: OQue
    situacao: Situacao
    resultado: str  # português, uma linha
    produto_id: int | None
    produto: str | None
    asin: str | None
    custo_usd: Decimal | None
    detalhe: Detalhe  # observação completa e números


@dataclass(frozen=True)
class _Cursor:
    em: datetime
    fonte: str
    id: tuple  # (int,) ou (tipo, chave) nos avisos


@dataclass(frozen=True)
class _Bruta:
    """Linha de uma fonte antes de juntar: `ordem` é o id do keyset, `id_texto` o que vai no cursor."""

    em: datetime
    fonte: str
    ordem: tuple
    chave: str
    servico: Servico | None
    o_que: OQue
    situacao: Situacao
    resultado: str
    produto_id: int | None = None
    anuncio_id: int | None = None
    custo_usd: Decimal | None = None
    detalhe: Detalhe = field(default_factory=dict)

    @property
    def id_texto(self) -> str:
        return ":".join(str(parte) for parte in self.ordem)


# --- cursor -----------------------------------------------------------------------------------------------


def _escrever_cursor(linha: _Bruta) -> str:
    texto = f"{linha.em.isoformat()}|{linha.fonte}|{linha.id_texto}"
    return base64.urlsafe_b64encode(texto.encode()).decode().rstrip("=")


def _ler_cursor(cursor: str) -> _Cursor:
    """Levanta ValueError para cursor que não saiu daqui."""
    try:
        texto = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        em_texto, fonte, id_texto = texto.split("|", 2)
        em = datetime.fromisoformat(em_texto)
    except (ValueError, UnicodeDecodeError) as erro:
        raise ValueError("cursor inválido") from erro
    if fonte not in FONTES or em.tzinfo is None:
        raise ValueError("cursor inválido")
    if fonte == AVISO:
        tipo, sep, chave = id_texto.partition(":")
        if not sep:
            raise ValueError("cursor inválido")
        return _Cursor(em, fonte, (tipo, chave))
    if not id_texto.isdigit():
        raise ValueError("cursor inválido")
    return _Cursor(em, fonte, (int(id_texto),))


def _keyset(fonte: str, em, ids: tuple, cursor: _Cursor | None) -> list[ColumnElement[bool]]:
    """`(em, fonte, id) < cursor` com a fonte fixa da consulta; `em <= ...` sempre na frente (usa o índice)."""
    if cursor is None:
        return []
    if fonte < cursor.fonte:
        return [em <= cursor.em]
    if fonte > cursor.fonte:
        return [em < cursor.em]
    menor_id = ids[0] < cursor.id[0] if len(ids) == 1 else tuple_(*ids) < tuple_(*cursor.id)
    return [em <= cursor.em, or_(em < cursor.em, menor_id)]


# --- ajudas ----------------------------------------------------------------------------------------------


def _periodo(em, filtro: FiltroAtividade) -> list[ColumnElement[bool]]:
    condicoes = []
    if filtro.de is not None:
        condicoes.append(em >= filtro.de)
    if filtro.ate is not None:
        condicoes.append(em <= filtro.ate)
    return condicoes


def _quer(filtro: FiltroAtividade) -> set[Situacao] | None:
    match filtro.situacao:
        case None:
            return None
        case "problemas":
            return {"parcial", "falha"}
        case "pendente":
            return set()  # nenhuma fonte tem "pendente" na tabela de situações; só a de mensagens trata à parte
        case situacao:
            return {situacao}


def _por_situacao(coluna, mapa: dict, quer: set[Situacao] | None) -> list[ColumnElement[bool]] | None:
    """Condição da situação pedida sobre a coluna de status; None: a fonte não tem linha nessa situação."""
    if quer is None:
        return []
    valores = [valor for valor, situacao in mapa.items() if situacao in quer]
    return [coluna.in_(valores)] if valores else None


def _like(coluna, busca: str) -> ColumnElement[bool]:
    return coluna.ilike(f"%{escapar_like(busca)}%", escape="\\")


def _produto_casa(produto_id, busca: str) -> ColumnElement[bool]:
    return exists(select(ProdutoLiga.id).where(ProdutoLiga.id == produto_id, casa_nome(busca)))


def _anuncios_da_busca(busca: str):
    """Anúncios que podem casar com a busca: ASIN, ou par/oportunidade com produto de nome parecido. Só um
    pré-filtro (usa o índice `anuncio_id, lida_em`); o produto certo da linha é conferido à parte."""
    return union(
        select(AnuncioAmazon.id).where(_like(AnuncioAmazon.asin, busca)),
        select(Casamento.anuncio_id).join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id).where(casa_nome(busca)),
        select(Oportunidade.anuncio_id)
        .join(ProdutoLiga, ProdutoLiga.id == Oportunidade.produto_id)
        .where(casa_nome(busca)),
    )


def _uma_linha(texto: str | None) -> str:
    linhas = (texto or "").strip().splitlines()
    return linhas[0].strip() if linhas else ""


def _com(prefixo: str, texto: str | None) -> str:
    linha = _uma_linha(texto)
    return f"{prefixo} · {linha}" if linha else prefixo


def _iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.isoformat()


def _dinheiro(valor: Decimal | None) -> str | None:
    return None if valor is None else formatar_brl(valor)


def _sim(valor: bool | None) -> str | None:
    return None if valor is None else ("sim" if valor else "não")


def _pode(filtro: FiltroAtividade, servico: Servico | None, o_que: OQue) -> bool:
    return filtro.servico in (None, servico) and filtro.o_que in (None, o_que)


# --- fontes ----------------------------------------------------------------------------------------------

_SITUACAO_COLETA: dict[StatusColeta, Situacao] = {
    StatusColeta.RODANDO: "ok",
    StatusColeta.OK: "ok",
    StatusColeta.PARCIAL: "parcial",
    StatusColeta.PAUSADA_DESAFIO: "parcial",
    StatusColeta.FALHA: "falha",
}


def _resultado_coleta(c: Coleta) -> str:
    unidade = "buscas" if c.tipo is TipoColeta.AMAZON else "produtos"
    feitos, total = formatar_milhar(c.produtos_ok), formatar_milhar(c.produtos_ok + c.produtos_falha)
    match c.status:
        case StatusColeta.RODANDO:
            return f"rodando · {feitos} {unidade} até agora"
        case StatusColeta.OK:
            return f"ok · {feitos} {unidade}"
        case StatusColeta.PARCIAL:
            return f"parcial · {feitos} de {total}"
        case StatusColeta.PAUSADA_DESAFIO:
            return f"parada por desafio · {feitos} de {total}"
    if c.erro == INTERROMPIDA:
        return "interrompida (reinício)"
    return _com("falha", c.erro)


def _coletas(s: Session, f: FiltroAtividade, quer, cursor, n: int) -> list[_Bruta]:
    tipos = [
        *(TIPOS_LIGA if _pode(f, Servico.LIGA, "coleta_liga") else ()),
        *((TipoColeta.AMAZON,) if _pode(f, Servico.AMAZON_BUSCA, "busca") else ()),
    ]
    situacao = _por_situacao(Coleta.status, _SITUACAO_COLETA, quer)
    if not tipos or situacao is None:
        return []
    condicoes = [
        Coleta.tipo.in_(tipos), *situacao, *_periodo(Coleta.iniciada_em, f),
        *_keyset(COLETA, Coleta.iniciada_em, (Coleta.id,), cursor),
    ]
    if not f.mostrar_reinicios:
        condicoes.append(or_(Coleta.status != StatusColeta.FALHA, Coleta.erro.is_(None), Coleta.erro != INTERROMPIDA))
    if f.busca:
        condicoes.append(_like(Coleta.erro, f.busca))
    consulta = select(Coleta).where(*condicoes).order_by(Coleta.iniciada_em.desc(), Coleta.id.desc()).limit(n + 1)
    linhas = []
    for c in s.scalars(consulta):
        busca = c.tipo is TipoColeta.AMAZON
        linhas.append(_Bruta(
            c.iniciada_em, COLETA, (c.id,), f"{COLETA}:{c.id}", Servico.AMAZON_BUSCA if busca else Servico.LIGA,
            "busca" if busca else "coleta_liga", _SITUACAO_COLETA[c.status], _resultado_coleta(c),
            detalhe={
                "tipo": c.tipo.value, "status": c.status.value, "produtos_ok": c.produtos_ok,
                "produtos_falha": c.produtos_falha, "iniciada_em": _iso(c.iniciada_em),
                "finalizada_em": _iso(c.finalizada_em), "erro": c.erro,
            },
        ))
    return linhas


def _leituras(s: Session, f: FiltroAtividade, quer, cursor, n: int) -> list[_Bruta]:
    """Uma linha por leitura (anúncio, instante), como a aba Monitor; o id do keyset é o do anúncio."""
    if not _pode(f, Servico.AMAZON_MONITOR, "leitura_monitor") or (f.o_que is None and not f.busca):
        return []
    if quer is not None and not quer & {"ok", "parcial"}:
        return []
    condicoes = [
        *_periodo(OfertaAmazon.lida_em, f),
        *_keyset(OFERTA, OfertaAmazon.lida_em, (OfertaAmazon.anuncio_id,), cursor),
    ]
    if f.busca:
        condicoes += [
            OfertaAmazon.anuncio_id.in_(_anuncios_da_busca(f.busca)),
            or_(
                OfertaAmazon.anuncio_id.in_(select(AnuncioAmazon.id).where(_like(AnuncioAmazon.asin, f.busca))),
                _produto_casa(produto_id_da_linha(OfertaAmazon.anuncio_id, OfertaAmazon.lida_em), f.busca),
            ),
        ]
    tem_melhor = func.bool_or(OfertaAmazon.melhor)
    consulta = (
        select(
            OfertaAmazon.anuncio_id, OfertaAmazon.lida_em, func.min(OfertaAmazon.id).label("id"),
            func.count().label("ofertas"),
            func.max(case((OfertaAmazon.melhor, OfertaAmazon.preco))).label("melhor_preco"),
            func.max(case((OfertaAmazon.melhor, OfertaAmazon.vendedor_nome))).label("melhor_vendedor"),
            tem_melhor.label("tem_melhor"),
        )
        .where(*condicoes)
        .group_by(OfertaAmazon.lida_em, OfertaAmazon.anuncio_id)
        .order_by(OfertaAmazon.lida_em.desc(), OfertaAmazon.anuncio_id.desc())
        .limit(n + 1)
    )
    if quer == {"ok"}:
        consulta = consulta.having(tem_melhor)
    elif quer is not None and "ok" not in quer:  # "parcial" ou "problemas" (leitura nunca é falha)
        consulta = consulta.having(not_(tem_melhor))
    leituras = consulta.subquery()
    com_produto = select(
        leituras, produto_id_da_linha(leituras.c.anuncio_id, leituras.c.lida_em).label("produto_id")
    ).order_by(leituras.c.lida_em.desc(), leituras.c.anuncio_id.desc())
    linhas = []
    for l in s.execute(com_produto):
        ofertas = f"{l.ofertas} oferta" if l.ofertas == 1 else f"{formatar_milhar(l.ofertas)} ofertas"
        if l.melhor_preco is None:
            resultado = f"{ofertas} · nenhuma elegível"
        else:
            vendedor = f" ({l.melhor_vendedor})" if l.melhor_vendedor else ""
            resultado = f"{ofertas} · melhor {formatar_brl(l.melhor_preco)}{vendedor}"
        linhas.append(_Bruta(
            l.lida_em, OFERTA, (l.anuncio_id,), f"{OFERTA}:{l.id}", Servico.AMAZON_MONITOR, "leitura_monitor",
            "ok" if l.tem_melhor else "parcial", resultado, l.produto_id, l.anuncio_id,
            detalhe={
                "anuncio_id": l.anuncio_id, "ofertas": l.ofertas, "melhor_preco": _dinheiro(l.melhor_preco),
                "melhor_vendedor": l.melhor_vendedor,
            },
        ))
    return linhas


_SITUACAO_CHECKOUT: dict[SituacaoCheckout, Situacao] = {
    SituacaoCheckout.OK: "ok",
    SituacaoCheckout.CARRINHO_OCUPADO: "parcial",
    SituacaoCheckout.FALHA: "falha",
    SituacaoCheckout.SEM_LOGIN: "falha",
}


def _resultado_checkout(c: ConferenciaCheckout, conferido: Decimal | None) -> str:
    match c.situacao:
        case SituacaoCheckout.OK if conferido is None:
            texto = "ok · sem valores lidos"
        case SituacaoCheckout.OK:
            # Preço conferido = itens + impostos, sem frete (o frete à parte).
            texto = f"{formatar_brl(conferido)} com impostos"
            if c.frete:
                texto += f" · frete {formatar_brl(c.frete)} à parte"
        case SituacaoCheckout.CARRINHO_OCUPADO:
            texto = "carrinho ocupado · nada foi clicado"
        case SituacaoCheckout.SEM_LOGIN:
            texto = "sem login na Amazon"
        case _:
            texto = _com("falha", c.motivo)
    return texto if c.item_removido else f"{texto} · item ficou no carrinho"


def _conferencias(s: Session, f: FiltroAtividade, quer, cursor, n: int) -> list[_Bruta]:
    situacao = _por_situacao(ConferenciaCheckout.situacao, _SITUACAO_CHECKOUT, quer)
    if not _pode(f, Servico.AMAZON_MONITOR, "checkout") or situacao is None:
        return []
    c = ConferenciaCheckout
    condicoes = [*situacao, *_periodo(c.em, f), *_keyset(CHECKOUT, c.em, (c.id,), cursor)]
    if f.busca:
        condicoes.append(or_(
            _like(AnuncioAmazon.asin, f.busca), _like(c.motivo, f.busca), _like(c.vendedor_nome, f.busca),
            and_(  # o pré-filtro barato antes do produto certo da linha
                c.anuncio_id.in_(_anuncios_da_busca(f.busca)),
                _produto_casa(produto_id_da_linha(c.anuncio_id, c.em), f.busca),
            ),
        ))
    consulta = (
        select(c, produto_id_da_linha(c.anuncio_id, c.em).label("produto_id"))
        .join(AnuncioAmazon, AnuncioAmazon.id == c.anuncio_id)
        .where(*condicoes)
        .order_by(c.em.desc(), c.id.desc())
        .limit(n + 1)
    )
    linhas = []
    for conf, produto_id in s.execute(consulta):
        conferido = motor.preco_conferido(conf.itens, conf.impostos, conf.total, conf.frete)
        linhas.append(_Bruta(
            conf.em, CHECKOUT, (conf.id,), f"{CHECKOUT}:{conf.id}", Servico.AMAZON_MONITOR, "checkout",
            _SITUACAO_CHECKOUT[conf.situacao], _resultado_checkout(conf, conferido), produto_id, conf.anuncio_id,
            detalhe={
                "situacao": conf.situacao.value, "vendedor": conf.vendedor_nome,
                "preco_anunciado": _dinheiro(conf.preco_anunciado), "itens": _dinheiro(conf.itens),
                "impostos": _dinheiro(conf.impostos), "frete": _dinheiro(conf.frete), "total": _dinheiro(conf.total),
                "conferido": _dinheiro(conferido) if conf.situacao is SituacaoCheckout.OK else None,
                "motivo": conf.motivo, "item_removido": _sim(conf.item_removido),
            },
        ))
    return linhas


def _resultado_ia(c: ChamadaIA, av: AvaliacaoIA | None) -> str:
    if not c.ok:
        return _com("erro", c.erro)
    if av is None:
        # a avaliação do par aponta para a chamada mais recente dele; a antiga fica sem veredito
        if c.finalidade == "termos":
            return "termos de busca gerados"
        return "idioma consultado" if c.finalidade == "idioma" else "avaliação feita"
    palavra = "mesmo" if av.mesmo_produto else "outro"
    if av.aplicada_em is not None and av.aplicada_em >= c.em:
        desfecho = "confirmado sozinho" if av.mesmo_produto else "ignorado sozinho"
    else:
        desfecho = "ficou para você"
    return f"{palavra} {av.confianca}% · {desfecho}"


def _chamadas(s: Session, f: FiltroAtividade, quer, cursor, n: int) -> list[_Bruta]:
    if not _pode(f, Servico.CASADOR, "ia") or (quer is not None and not quer & {"ok", "falha"}):
        return []
    condicoes = [*_periodo(ChamadaIA.em, f), *_keyset(IA, ChamadaIA.em, (ChamadaIA.id,), cursor)]
    if quer == {"ok"}:
        condicoes.append(ChamadaIA.ok.is_(True))
    elif quer is not None and "ok" not in quer:
        condicoes.append(ChamadaIA.ok.is_(False))
    if f.busca:
        condicoes.append(or_(_like(ChamadaIA.erro, f.busca), _like(AnuncioAmazon.asin, f.busca), casa_nome(f.busca)))
    consulta = (
        select(ChamadaIA, AvaliacaoIA)
        .outerjoin(AvaliacaoIA, AvaliacaoIA.chamada_id == ChamadaIA.id)
        .outerjoin(ProdutoLiga, ProdutoLiga.id == AvaliacaoIA.produto_id)
        .outerjoin(AnuncioAmazon, AnuncioAmazon.id == AvaliacaoIA.anuncio_id)
        .where(*condicoes)
        .order_by(ChamadaIA.em.desc(), ChamadaIA.id.desc())
        .limit(n + 1)
    )
    linhas = []
    for c, av in s.execute(consulta):
        linhas.append(_Bruta(
            c.em, IA, (c.id,), f"{IA}:{c.id}", Servico.CASADOR, "ia", "ok" if c.ok else "falha",
            _resultado_ia(c, av), av.produto_id if av else None, av.anuncio_id if av else None, c.custo_usd,
            detalhe={
                "finalidade": c.finalidade, "modelo": c.modelo, "tokens_entrada": c.tokens_entrada,
                "tokens_saida": c.tokens_saida, "custo_usd": str(c.custo_usd), "erro": c.erro,
                "mesmo_produto": _sim(av.mesmo_produto) if av else None, "confianca": av.confianca if av else None,
                "motivo": av.motivo if av else None, "idioma_anuncio": av.idioma_anuncio if av else None,
            },
        ))
    return linhas


_SITUACAO_MENSAGEM: dict[StatusMensagem, Situacao] = {
    StatusMensagem.ENVIADA: "ok",
    StatusMensagem.DESCARTADA: "ok",  # quem descartou foi você: não é problema
    StatusMensagem.PENDENTE: "parcial",
    StatusMensagem.EXPIRADA: "parcial",
    StatusMensagem.FALHA: "falha",
}
_ROTULO_MENSAGEM = {
    StatusMensagem.ENVIADA: "enviada",
    StatusMensagem.DESCARTADA: "descartada",
    StatusMensagem.PENDENTE: "na fila",
    StatusMensagem.EXPIRADA: "expirou sem sair",
    StatusMensagem.FALHA: "falha",
}
INDIVIDUAL = "individual"
_ROTULO_DESTINO = {"admin": "grupo do admin", "oportunidades": "grupo de oportunidades", "individual": "individual"}


def _mensagens(s: Session, f: FiltroAtividade, quer, cursor, n: int) -> list[_Bruta]:
    if f.situacao == "pendente":  # `_quer` devolve conjunto vazio para ela: as outras fontes ficam de fora
        situacao = [MensagemSaida.status == StatusMensagem.PENDENTE]
    else:
        situacao = _por_situacao(MensagemSaida.status, _SITUACAO_MENSAGEM, quer)
    if not _pode(f, Servico.WHATSAPP, "mensagem") or situacao is None:
        return []
    m = MensagemSaida
    condicoes = [*situacao, *_periodo(m.criada_em, f), *_keyset(MENSAGEM, m.criada_em, (m.id,), cursor)]
    if f.destino:
        condicoes.append(m.destino == f.destino)
    if f.busca:
        # o texto individual (código de acesso) nunca aparece nem entra na busca, como no admin antigo
        no_texto = and_(m.destino != INDIVIDUAL, _like(m.texto, f.busca)) if f.mostrar_texto_mensagem else None
        condicoes.append(or_(*[c for c in (no_texto, _like(m.ultimo_erro, f.busca)) if c is not None]))

    def da_oportunidade(coluna):  # o alerta de oportunidade aponta para a mensagem
        return (
            select(coluna).where(Oportunidade.mensagem_alerta_id == m.id).order_by(Oportunidade.id).limit(1)
            .scalar_subquery()
        )

    consulta = (
        select(m, da_oportunidade(Oportunidade.produto_id), da_oportunidade(Oportunidade.anuncio_id))
        .where(*condicoes)
        .order_by(m.criada_em.desc(), m.id.desc())
        .limit(n + 1)
    )
    linhas = []
    for msg, produto_id, anuncio_id in s.execute(consulta):
        oculto = msg.destino == INDIVIDUAL or not f.mostrar_texto_mensagem
        titulo = ("texto oculto" if msg.destino == INDIVIDUAL else "") if oculto else _uma_linha(msg.texto).strip("*_~ ")
        resultado = f"{_ROTULO_MENSAGEM[msg.status]} · {_ROTULO_DESTINO.get(msg.destino, msg.destino)}"
        linhas.append(_Bruta(
            msg.criada_em, MENSAGEM, (msg.id,), f"{MENSAGEM}:{msg.id}", Servico.WHATSAPP, "mensagem",
            _SITUACAO_MENSAGEM[msg.status], f"{resultado} · {titulo}" if titulo else resultado, produto_id, anuncio_id,
            detalhe={  # nunca o número nem o texto do destino individual
                "mensagem_id": msg.id, "status": msg.status.value, "destino": msg.destino,
                "texto": None if oculto else msg.texto,
                "tentativas": msg.tentativas, "ultimo_erro": msg.ultimo_erro, "enviada_em": _iso(msg.enviada_em),
            },
        ))
    return linhas


_SITUACAO_MANUTENCAO: dict[StatusManutencao, Situacao] = {
    StatusManutencao.RODANDO: "ok",
    StatusManutencao.OK: "ok",
    StatusManutencao.SO_LOCAL: "ok",
    StatusManutencao.ERRO: "falha",
    StatusManutencao.INTERROMPIDA: "falha",
}


def _resultado_manutencao(e: ExecucaoManutencao) -> str:
    match e.status:
        case StatusManutencao.RODANDO:
            return "rodando"
        case StatusManutencao.OK:
            return f"backup ok · {formatar_bytes(e.tamanho_bytes)} · cópia no R2"
        case StatusManutencao.SO_LOCAL:
            return f"backup só local · {formatar_bytes(e.tamanho_bytes)}"
        case StatusManutencao.INTERROMPIDA:
            return "interrompida (reinício)"
    return _com("erro", e.erro)


def _execucoes(s: Session, f: FiltroAtividade, quer, cursor, n: int) -> list[_Bruta]:
    situacao = _por_situacao(ExecucaoManutencao.status, _SITUACAO_MANUTENCAO, quer)
    if not _pode(f, Servico.BACKUP, "backup") or situacao is None:
        return []
    e = ExecucaoManutencao
    condicoes = [*situacao, *_periodo(e.inicio, f), *_keyset(MANUTENCAO, e.inicio, (e.id,), cursor)]
    if not f.mostrar_reinicios:
        condicoes.append(e.status != StatusManutencao.INTERROMPIDA)
    if f.busca:
        condicoes.append(or_(_like(e.erro, f.busca), _like(e.arquivo, f.busca)))
    consulta = select(e).where(*condicoes).order_by(e.inicio.desc(), e.id.desc()).limit(n + 1)
    linhas = []
    for ex in s.scalars(consulta):
        apagados = " · ".join(f"{t} {formatar_milhar(q)}" for t, q in (ex.apagados or {}).items()) or None
        linhas.append(_Bruta(
            ex.inicio, MANUTENCAO, (ex.id,), f"{MANUTENCAO}:{ex.id}", Servico.BACKUP, "backup",
            _SITUACAO_MANUTENCAO[ex.status], _resultado_manutencao(ex),
            detalhe={
                "status": ex.status.value, "arquivo": ex.arquivo, "tamanho_bytes": ex.tamanho_bytes,
                "tamanho": formatar_bytes(ex.tamanho_bytes) if ex.tamanho_bytes is not None else None,
                "enviado_r2": _sim(ex.enviado_r2), "apagados": apagados, "fim": _iso(ex.fim), "erro": ex.erro,
            },
        ))
    return linhas


# Quem manda cada aviso (rodapé do catálogo) → serviço. Vigia e admin: a chave é o nome do coletor.
_SERVICO_DA_ORIGEM = {
    "coletor Liga": Servico.LIGA,
    "busca Amazon": Servico.AMAZON_BUSCA,
    "coletor Amazon": Servico.AMAZON_MONITOR,
    "monitor Amazon": Servico.AMAZON_MONITOR,
    "casador (IA)": Servico.CASADOR,
    "notificador": Servico.WHATSAPP,
    "manutenção": Servico.BACKUP,
}
_AVISOS_DE_SERVICO = (TipoAviso.SERVICO_SEM_SINAL.value, TipoAviso.SERVICO_PAUSADO_MANUAL.value)
_SERVICO_DO_COLETOR = {coletor: servico for servico, coletor in COLETOR.items()}


def _servico_do_aviso(tipo: str, chave: str) -> Servico | None:
    if tipo in _AVISOS_DE_SERVICO:
        return _SERVICO_DO_COLETOR.get(chave)
    definicao = CATALOGO.get(tipo)  # StrEnum: a string do banco acha o tipo
    return None if definicao is None else _SERVICO_DA_ORIGEM.get(definicao.origem)


def _titulo_aviso(tipo: str) -> str:
    definicao = CATALOGO.get(tipo)
    return tipo if definicao is None else definicao.titulo


def _avisos(s: Session, f: FiltroAtividade, quer, cursor, n: int) -> list[_Bruta]:
    if f.o_que not in (None, "aviso") or (quer is not None and not quer & {"ok", "falha"}):
        return []
    a = EstadoAviso
    tipo_c, chave_c = a.tipo.collate("C"), a.chave.collate("C")  # mesma ordem do Python (por código)
    condicoes = [*_periodo(a.ultimo_em, f), *_keyset(AVISO, a.ultimo_em, (tipo_c, chave_c), cursor)]
    if f.servico is not None:
        tipos = [t.value for t, d in CATALOGO.items() if _SERVICO_DA_ORIGEM.get(d.origem) is f.servico]
        condicoes.append(or_(a.tipo.in_(tipos), and_(a.tipo.in_(_AVISOS_DE_SERVICO), a.chave == COLETOR[f.servico])))
    if quer == {"ok"}:
        condicoes.append(a.aberto.is_(False))
    elif quer is not None and "ok" not in quer:
        condicoes.append(a.aberto.is_(True))
    if f.busca:
        pelo_titulo = [t.value for t, d in CATALOGO.items() if f.busca.casefold() in d.titulo.casefold()]
        condicoes.append(or_(_like(a.tipo, f.busca), _like(a.chave, f.busca), a.tipo.in_(pelo_titulo)))
    consulta = select(a).where(*condicoes).order_by(a.ultimo_em.desc(), tipo_c.desc(), chave_c.desc()).limit(n + 1)
    linhas = []
    for av in s.scalars(consulta):
        vezes = "1 ocorrência" if av.ocorrencias == 1 else f"{formatar_milhar(av.ocorrencias)} ocorrências"
        titulo = _titulo_aviso(av.tipo)
        linhas.append(_Bruta(
            av.ultimo_em, AVISO, (av.tipo, av.chave), f"{AVISO}:{av.tipo}:{av.chave}",
            _servico_do_aviso(av.tipo, av.chave), "aviso", "falha" if av.aberto else "ok",
            f"{titulo} · {'aberto' if av.aberto else 'resolvido'} · {vezes}",
            detalhe={
                "tipo": av.tipo, "chave": av.chave, "titulo": titulo, "aberto": _sim(av.aberto),
                "ocorrencias": av.ocorrencias, "primeiro_em": _iso(av.primeiro_em),
                "ultimo_envio_em": _iso(av.ultimo_envio_em),
            },
        ))
    return linhas


def _descricao_acao(acao: AcaoGestao, mostrar_valores: bool) -> str:
    d = acao.detalhe or {}
    match acao.tipo:
        case TipoAcaoGestao.SERVICO:
            mensagem = MENSAGENS.get(d.get("codigo", ""))
            if mensagem:
                return mensagem.split(". ")[0].rstrip(".")
            return f"{d.get('acao', 'ação')} · {d.get('servico', 'serviço')}"
        case TipoAcaoGestao.CATALOGO_LOTE:
            verbo = "ligou" if d.get("acao") == "ligar" else "desligou"
            alterados = d.get("alterados")
            quantos = formatar_milhar(alterados) if isinstance(alterados, int) else "?"
            return f"{verbo} o monitoramento de {quantos} produtos (lote)"
        case TipoAcaoGestao.CATALOGO_PRODUTO:
            return f"{'ligou' if d.get('ativo') else 'desligou'} o monitoramento de um produto"
        case TipoAcaoGestao.CONFIGURACOES:
            return _descricao_configuracoes(d, mostrar_valores)
    return "salvou as configurações"


CAMPOS_NA_DESCRICAO = 3  # campos listados na linha; o resto vira "e mais N"


def _valor_config(valor) -> str:
    if valor is None or valor == "":
        return "vazio"
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    if isinstance(valor, float):
        return f"{valor:g}"
    return str(valor)


def _rotulo_config(chave: str) -> str:
    try:
        rotulo = campo_config(chave).rotulo
    except KeyError:
        return chave
    if rotulo[1:2].isupper():  # sigla no começo (URL, IA, IP): fica como está
        return rotulo
    return rotulo[:1].lower() + rotulo[1:]


def _descricao_configuracoes(d: dict, mostrar_valores: bool = True) -> str:
    """"salvou 3 campos: desconto mínimo 20→22, …" (sem `mostrar_valores`: só os rótulos)
    ou "ligou/desligou o aviso X"."""
    if "aviso" in d:
        tipo = d.get("aviso")
        try:
            titulo = CATALOGO[TipoAviso(tipo)].titulo
        except ValueError:
            titulo = str(tipo)
        return f"{'ligou' if d.get('ligado') else 'desligou'} o aviso {titulo}"
    campos = d.get("campos")
    if not isinstance(campos, dict) or not campos:
        return "salvou as configurações"
    partes = []
    for chave, par in list(campos.items())[:CAMPOS_NA_DESCRICAO]:
        if not mostrar_valores:
            partes.append(_rotulo_config(chave))
            continue
        antes, depois = par if isinstance(par, list) and len(par) == 2 else (None, par)
        partes.append(f"{_rotulo_config(chave)} {_valor_config(antes)}→{_valor_config(depois)}")
    texto = ", ".join(partes)
    if len(campos) > CAMPOS_NA_DESCRICAO:
        texto += f" e mais {formatar_milhar(len(campos) - CAMPOS_NA_DESCRICAO)}"
    quantos = "1 campo" if len(campos) == 1 else f"{formatar_milhar(len(campos))} campos"
    return f"salvou {quantos}: {texto}"


def _servico_da_acao(acao: AcaoGestao) -> Servico | None:
    if acao.tipo is not TipoAcaoGestao.SERVICO:
        return None
    try:
        return Servico((acao.detalhe or {}).get("servico"))
    except ValueError:
        return None


def _plano(valor) -> str | int | None:
    if valor is None or isinstance(valor, (str, int)):
        return valor
    return json.dumps(valor, ensure_ascii=False)


def _acoes(s: Session, f: FiltroAtividade, quer, cursor, n: int) -> list[_Bruta]:
    if f.o_que not in (None, "acao_gestao") or (quer is not None and "ok" not in quer):
        return []
    a = AcaoGestao
    condicoes = [*_periodo(a.em, f), *_keyset(ACAO, a.em, (a.id,), cursor)]
    if f.servico is not None:
        condicoes += [a.tipo == TipoAcaoGestao.SERVICO, a.detalhe["servico"].astext == f.servico.value]
    if f.busca:
        no_detalhe = _like(cast(a.detalhe, Text), f.busca)
        if not f.mostrar_valores_configuracao:  # os valores salvos não entram na busca de quem não os vê
            no_detalhe = and_(a.tipo != TipoAcaoGestao.CONFIGURACOES, no_detalhe)
        condicoes.append(or_(no_detalhe, _like(Usuario.nome, f.busca)))
    consulta = (
        select(a, Usuario.nome)
        .outerjoin(Usuario, Usuario.id == a.usuario_id)
        .where(*condicoes)
        .order_by(a.em.desc(), a.id.desc())
        .limit(n + 1)
    )
    linhas = []
    for acao, nome in s.execute(consulta):
        usuario = nome or SEM_USUARIO
        produto_id = acao.detalhe.get("produto_id") if acao.tipo is TipoAcaoGestao.CATALOGO_PRODUTO else None
        plano = {chave: _plano(valor) for chave, valor in (acao.detalhe or {}).items()}
        if not f.mostrar_valores_configuracao and isinstance(campos := (acao.detalhe or {}).get("campos"), dict):
            plano["campos"] = _plano(list(campos))
        linhas.append(_Bruta(
            acao.em, ACAO, (acao.id,), f"{ACAO}:{acao.id}", _servico_da_acao(acao), "acao_gestao", "ok",
            f"{usuario} · {_descricao_acao(acao, f.mostrar_valores_configuracao)}", produto_id if isinstance(produto_id, int) else None,
            detalhe={
                **plano, "tipo": acao.tipo.value, "usuario": usuario,
            },
        ))
    return linhas


_FONTES = (_coletas, _leituras, _conferencias, _chamadas, _mensagens, _execucoes, _avisos, _acoes)


def linha_do_tempo(
    s: Session, filtro: FiltroAtividade, cursor: str | None, limite: int = POR_PAGINA
) -> tuple[list[LinhaAtividade], str | None]:
    """Uma página da Atividade, mais recente primeiro, e o cursor da próxima (None: acabou).
    Levanta ValueError para cursor inválido ou limite menor que 1."""
    if limite < 1:
        raise ValueError("limite precisa ser pelo menos 1")
    depois_de = _ler_cursor(cursor) if cursor else None
    filtro = replace(filtro, busca=(filtro.busca or "").strip() or None)
    quer = _quer(filtro)
    fontes = (_mensagens,) if filtro.destino else _FONTES  # destino só existe nas mensagens
    brutas = [linha for fonte in fontes for linha in fonte(s, filtro, quer, depois_de, limite)]
    brutas.sort(key=lambda b: (b.em, b.fonte, b.ordem), reverse=True)
    pagina = brutas[:limite]
    proximo = _escrever_cursor(pagina[-1]) if len(brutas) > limite else None

    produtos = {b.produto_id for b in pagina if b.produto_id is not None}
    anuncios = {b.anuncio_id for b in pagina if b.anuncio_id is not None}
    nomes = dict(s.execute(select(ProdutoLiga.id, ProdutoLiga.nome).where(ProdutoLiga.id.in_(produtos))).all()) if produtos else {}
    asins = (
        dict(s.execute(select(AnuncioAmazon.id, AnuncioAmazon.asin).where(AnuncioAmazon.id.in_(anuncios))).all())
        if anuncios else {}
    )
    return [
        LinhaAtividade(
            chave=b.chave, em=b.em, servico=b.servico, o_que=b.o_que, situacao=b.situacao, resultado=b.resultado,
            produto_id=b.produto_id if b.produto_id in nomes else None, produto=nomes.get(b.produto_id),
            asin=asins.get(b.anuncio_id), custo_usd=b.custo_usd, detalhe=b.detalhe,
        )
        for b in pagina
    ], proximo
