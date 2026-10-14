"""Consultas das telas da Amazon no admin."""

import difflib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tcg_sniper.admin.consultas import _escapar_like
from tcg_sniper.coletor_amazon.termo import termo_busca
from tcg_sniper.db.models import (
    AnuncioAmazon,
    Coleta,
    ConfigAmazon,
    Envio,
    Oportunidade,
    PrecoAmazon,
    PrecoAtualAmazon,
    PrecoAtualLiga,
    ProdutoLiga,
    StatusCasamento,
    StatusColeta,
    TipoColeta,
    VendedorAmazon,
)
from tcg_sniper.oportunidades.motor import Regras, Vendedor, atinge_desconto, desconto_pct, vendedor_confiavel


def ciclo_atual(s: Session) -> Coleta | None:
    return s.scalar(
        select(Coleta)
        .where(Coleta.tipo == TipoColeta.AMAZON, Coleta.status == StatusColeta.RODANDO)
        .order_by(Coleta.id.desc())
        .limit(1)
    )


@dataclass(frozen=True)
class LinhaCasamento:
    anuncio: AnuncioAmazon
    preco: Decimal | None
    sugestao: ProdutoLiga | None
    preco_sugestao: Decimal | None
    alternativas: list[ProdutoLiga]
    candidato: bool  # o preço já está a pelo menos o desconto mínimo abaixo da sugestão


def _normalizar(texto: str) -> str:
    return termo_busca(texto).lower()


def _tokens(texto_normalizado: str) -> set[str]:
    return {token for token in texto_normalizado.split() if len(token) >= 3}


FREQUENCIA_MAXIMA_TOKEN = 0.10


def candidatos_para(titulo_normalizado: str, nomes: list[str], indice: dict[str, set[str]]) -> list[str]:
    """Nomes do catálogo (na ordem do catálogo) que compartilham ao menos um token raro com o título.
    Tokens em mais de 10% dos nomes são genéricos e ignorados; sem token raro, compara com todos."""
    limite = FREQUENCIA_MAXIMA_TOKEN * len(nomes)
    raros = [t for t in _tokens(titulo_normalizado) if t in indice and len(indice[t]) <= limite]
    if not raros:
        return nomes
    comuns = set().union(*(indice[t] for t in raros))
    return [nome for nome in nomes if nome in comuns]


def contar_pendentes(s: Session) -> int:
    consulta = (
        select(func.count()).select_from(AnuncioAmazon).where(AnuncioAmazon.status_casamento == StatusCasamento.PENDENTE)
    )
    return int(s.scalar(consulta) or 0)


def pendentes(s: Session, desconto_min_pct: int, limite: int = 20) -> tuple[list[LinhaCasamento], int]:
    """Pendentes que seriam oportunidade primeiro; depois os demais, mais recentes primeiro.
    Cada linha traz até 3 outros produtos do catálogo com título parecido (difflib)."""
    consulta = (
        select(AnuncioAmazon, PrecoAtualAmazon.preco, ProdutoLiga, PrecoAtualLiga.preco_a_partir)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == AnuncioAmazon.produto_id)
        .where(AnuncioAmazon.status_casamento == StatusCasamento.PENDENTE)
    )
    linhas = [
        (anuncio, preco, sugestao, preco_liga, atinge_desconto(preco, preco_liga, desconto_min_pct))
        for anuncio, preco, sugestao, preco_liga in s.execute(consulta)
    ]
    linhas.sort(key=lambda linha: (not linha[4], -linha[0].visto_primeiro_em.timestamp(), linha[0].id))
    total = len(linhas)
    por_nome: dict[str, int] = {}
    indice: dict[str, set[str]] = {}
    for produto_id, nome in s.execute(select(ProdutoLiga.id, ProdutoLiga.nome).order_by(ProdutoLiga.id)):
        normalizado = _normalizar(nome)
        if por_nome.setdefault(normalizado, produto_id) != produto_id:
            continue
        for token in _tokens(normalizado):
            indice.setdefault(token, set()).add(normalizado)
    nomes = list(por_nome)
    escolhidos = []
    for anuncio, preco, sugestao, preco_liga, candidato in linhas[:limite]:
        titulo = _normalizar(anuncio.titulo)
        candidatos = candidatos_para(titulo, nomes, indice)
        parecidos = difflib.get_close_matches(titulo, candidatos, n=4, cutoff=0.3)
        ids = [por_nome[nome] for nome in parecidos if sugestao is None or por_nome[nome] != sugestao.id]
        escolhidos.append((anuncio, preco, sugestao, preco_liga, candidato, ids[:3]))
    ids_usados = {i for *_, ids in escolhidos for i in ids}
    produtos = {p.id: p for p in s.scalars(select(ProdutoLiga).where(ProdutoLiga.id.in_(ids_usados)))}
    resultado = [
        LinhaCasamento(anuncio, preco, sugestao, preco_liga, [produtos[i] for i in ids], candidato)
        for anuncio, preco, sugestao, preco_liga, candidato, ids in escolhidos
    ]
    return resultado, total


def revisados(s: Session, limite: int = 100) -> list[tuple[AnuncioAmazon, ProdutoLiga | None]]:
    consulta = (
        select(AnuncioAmazon, ProdutoLiga)
        .outerjoin(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .where(AnuncioAmazon.status_casamento != StatusCasamento.PENDENTE)
        .order_by(AnuncioAmazon.revisado_em.desc().nulls_last(), AnuncioAmazon.id.desc())
        .limit(limite)
    )
    return [(anuncio, produto) for anuncio, produto in s.execute(consulta)]


def buscar_produtos(s: Session, busca: str, limite: int = 20) -> list[ProdutoLiga]:
    consulta = select(ProdutoLiga).order_by(ProdutoLiga.nome).limit(limite)
    if busca.strip():
        consulta = consulta.where(ProdutoLiga.nome.ilike(f"%{_escapar_like(busca.strip())}%", escape="\\"))
    return list(s.scalars(consulta))


FILTROS_OFERTAS = ("todas", "desconto", "abertas")


@dataclass(frozen=True)
class LinhaOferta:
    produto: ProdutoLiga
    preco_liga: Decimal | None
    anuncio: AnuncioAmazon
    preco: Decimal | None
    envio: Envio
    vendedor: VendedorAmazon | None
    confiavel: bool
    coletado_em: datetime
    desconto: Decimal | None
    aberta: bool


def ofertas(s: Session, filtro: str, config: ConfigAmazon) -> list[LinhaOferta]:
    """Uma linha por produto da Liga com ASIN confirmado e preço: a oferta mais barata da Amazon
    contra o "À partir de" da Liga, ordenadas pelo maior desconto."""
    consulta = (
        select(AnuncioAmazon, ProdutoLiga, PrecoAtualAmazon, VendedorAmazon, PrecoAtualLiga.preco_a_partir)
        .join(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAtualAmazon.vendedor_id)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(AnuncioAmazon.status_casamento == StatusCasamento.CONFIRMADO, PrecoAtualAmazon.preco.is_not(None))
    )
    abertas = set(s.scalars(select(Oportunidade.produto_id).where(Oportunidade.fechada_em.is_(None))))
    regras = Regras.de(config)
    melhores: dict[int, LinhaOferta] = {}
    for anuncio, produto, atual, vendedor, preco_liga in s.execute(consulta):
        atual_melhor = melhores.get(produto.id)
        if atual_melhor is not None and atual_melhor.preco <= atual.preco:
            continue
        info = Vendedor(vendedor.nome, vendedor.pct_positivas, vendedor.num_avaliacoes) if vendedor else None
        melhores[produto.id] = LinhaOferta(
            produto=produto,
            preco_liga=preco_liga,
            anuncio=anuncio,
            preco=atual.preco,
            envio=atual.envio,
            vendedor=vendedor,
            confiavel=atual.envio is Envio.AMAZON or (atual.envio is Envio.FBA and vendedor_confiavel(info, regras)),
            coletado_em=atual.coletado_em,
            desconto=desconto_pct(atual.preco, preco_liga) if preco_liga else None,
            aberta=produto.id in abertas,
        )
    linhas = list(melhores.values())
    if filtro == "desconto":
        linhas = [l for l in linhas if atinge_desconto(l.preco, l.preco_liga, config.desconto_min_pct)]
    elif filtro == "abertas":
        linhas = [l for l in linhas if l.aberta]
    linhas.sort(key=lambda l: (l.desconto is None, -(l.desconto or 0), l.produto.nome))
    return linhas


def amazon_do_produto(
    s: Session, produto_id: int
) -> list[tuple[AnuncioAmazon, PrecoAtualAmazon | None, VendedorAmazon | None]]:
    consulta = (
        select(AnuncioAmazon, PrecoAtualAmazon, VendedorAmazon)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAtualAmazon.vendedor_id)
        .where(AnuncioAmazon.produto_id == produto_id, AnuncioAmazon.status_casamento == StatusCasamento.CONFIRMADO)
        .order_by(PrecoAtualAmazon.preco.nulls_last(), AnuncioAmazon.id)
    )
    return [(anuncio, atual, vendedor) for anuncio, atual, vendedor in s.execute(consulta)]


def historico_amazon(s: Session, produto_id: int, limite: int = 90) -> list[tuple[PrecoAmazon, str]]:
    consulta = (
        select(PrecoAmazon, AnuncioAmazon.asin)
        .join(AnuncioAmazon, AnuncioAmazon.id == PrecoAmazon.anuncio_id)
        .where(AnuncioAmazon.produto_id == produto_id, AnuncioAmazon.status_casamento == StatusCasamento.CONFIRMADO)
        .order_by(PrecoAmazon.coletado_em.desc(), PrecoAmazon.id.desc())
        .limit(limite)
    )
    return [(preco, asin) for preco, asin in s.execute(consulta)]
