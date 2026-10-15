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


SITUACOES_CASAMENTO = ("pendentes", "oportunidade", "sem_par", "casados", "todos")
POR_PAGINA_CASAMENTOS = 20


@dataclass(frozen=True)
class LinhaProdutoCasamento:
    produto: ProdutoLiga
    preco_liga: Decimal | None
    pendentes: int
    confirmados: int
    ignorados: int
    oportunidade: bool  # algum pendente já está a pelo menos o desconto mínimo abaixo da Liga

    @property
    def sem_par(self) -> bool:
        return self.pendentes == 0 and self.confirmados == 0


_FILTROS_SITUACAO = {
    "pendentes": lambda linha: linha.pendentes > 0,
    "oportunidade": lambda linha: linha.oportunidade,
    "sem_par": lambda linha: linha.sem_par,
    "casados": lambda linha: linha.confirmados > 0,
    "todos": lambda linha: True,
}


def produtos_para_casar(
    s: Session, *, busca: str, categoria: str | None, situacao: str, com_preco: bool, desconto_min_pct: int
) -> list[LinhaProdutoCasamento]:
    """Produtos ativos da Liga com as contagens de anúncios da Amazon, filtrados e ordenados:
    com pendente que seria oportunidade, depois com pendentes, depois os demais; por nome."""
    condicoes = [ProdutoLiga.ativo.is_(True)]
    if busca.strip():
        condicoes.append(ProdutoLiga.nome.ilike(f"%{_escapar_like(busca.strip())}%", escape="\\"))
    if categoria:
        condicoes.append(ProdutoLiga.tipo == categoria)
    if com_preco:
        condicoes.append(PrecoAtualLiga.preco_a_partir.is_not(None))
    produtos = s.execute(
        select(ProdutoLiga, PrecoAtualLiga.preco_a_partir)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(*condicoes)
    ).all()
    precos_liga = {produto.id: preco for produto, preco in produtos}
    contagens: dict[tuple[int, StatusCasamento], int] = {}
    oportunidade: set[int] = set()
    if precos_liga:
        consulta_contagens = (
            select(AnuncioAmazon.produto_id, AnuncioAmazon.status_casamento, func.count())
            .where(AnuncioAmazon.produto_id.in_(precos_liga))
            .group_by(AnuncioAmazon.produto_id, AnuncioAmazon.status_casamento)
        )
        for produto_id, situacao_anuncio, quantidade in s.execute(consulta_contagens):
            contagens[(produto_id, situacao_anuncio)] = quantidade
        consulta_precos = (
            select(AnuncioAmazon.produto_id, PrecoAtualAmazon.preco)
            .join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
            .where(
                AnuncioAmazon.produto_id.in_(precos_liga),
                AnuncioAmazon.status_casamento == StatusCasamento.PENDENTE,
            )
        )
        for produto_id, preco in s.execute(consulta_precos):
            if atinge_desconto(preco, precos_liga[produto_id], desconto_min_pct):
                oportunidade.add(produto_id)
    linhas = [
        LinhaProdutoCasamento(
            produto=produto,
            preco_liga=preco,
            pendentes=contagens.get((produto.id, StatusCasamento.PENDENTE), 0),
            confirmados=contagens.get((produto.id, StatusCasamento.CONFIRMADO), 0),
            ignorados=contagens.get((produto.id, StatusCasamento.IGNORADO), 0),
            oportunidade=produto.id in oportunidade,
        )
        for produto, preco in produtos
    ]
    linhas = [linha for linha in linhas if _FILTROS_SITUACAO[situacao](linha)]
    linhas.sort(key=lambda linha: (not linha.oportunidade, linha.pendentes == 0, linha.produto.nome, linha.produto.id))
    return linhas


@dataclass(frozen=True)
class LinhaAnuncio:
    anuncio: AnuncioAmazon
    atual: PrecoAtualAmazon | None
    vendedor: VendedorAmazon | None
    oportunidade: bool


@dataclass(frozen=True)
class DetalheCasamento:
    produto: ProdutoLiga
    preco_liga: Decimal | None
    pendentes: list[LinhaAnuncio]
    confirmados: list[LinhaAnuncio]
    ignorados: list[LinhaAnuncio]


def detalhe_casamento(s: Session, produto_id: int, desconto_min_pct: int) -> DetalheCasamento | None:
    produto = s.get(ProdutoLiga, produto_id)
    if produto is None or not produto.ativo:
        return None
    liga = s.get(PrecoAtualLiga, produto_id)
    preco_liga = liga.preco_a_partir if liga else None
    consulta = (
        select(AnuncioAmazon, PrecoAtualAmazon, VendedorAmazon)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAtualAmazon.vendedor_id)
        .where(AnuncioAmazon.produto_id == produto_id)
        .order_by(PrecoAtualAmazon.preco.nulls_last(), AnuncioAmazon.id)
    )
    grupos: dict[StatusCasamento, list[LinhaAnuncio]] = {situacao: [] for situacao in StatusCasamento}
    for anuncio, atual, vendedor in s.execute(consulta):
        oportunidade = atinge_desconto(atual.preco if atual else None, preco_liga, desconto_min_pct)
        grupos[anuncio.status_casamento].append(LinhaAnuncio(anuncio, atual, vendedor, oportunidade))
    return DetalheCasamento(
        produto,
        preco_liga,
        grupos[StatusCasamento.PENDENTE],
        grupos[StatusCasamento.CONFIRMADO],
        grupos[StatusCasamento.IGNORADO],
    )


def _com_preco_liga(s: Session, ids: list[int]) -> list[tuple[ProdutoLiga, Decimal | None]]:
    if not ids:
        return []
    linhas = s.execute(
        select(ProdutoLiga, PrecoAtualLiga.preco_a_partir)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(ProdutoLiga.id.in_(ids))
    ).all()
    por_id = {produto.id: (produto, preco) for produto, preco in linhas}
    return [por_id[i] for i in ids if i in por_id]


def sugestoes_para(s: Session, anuncio: AnuncioAmazon, limite: int = 3) -> list[tuple[ProdutoLiga, Decimal | None]]:
    """Até `limite` produtos do catálogo com nome parecido com o título do anúncio (difflib),
    sem o produto ao qual o anúncio já está ligado."""
    por_nome: dict[str, int] = {}
    indice: dict[str, set[str]] = {}
    consulta_nomes = select(ProdutoLiga.id, ProdutoLiga.nome).where(ProdutoLiga.ativo.is_(True)).order_by(ProdutoLiga.id)
    for produto_id, nome in s.execute(consulta_nomes):
        normalizado = _normalizar(nome)
        if por_nome.setdefault(normalizado, produto_id) != produto_id:
            continue
        for token in _tokens(normalizado):
            indice.setdefault(token, set()).add(normalizado)
    titulo = _normalizar(anuncio.titulo_exibicao)
    candidatos = candidatos_para(titulo, list(por_nome), indice)
    parecidos = difflib.get_close_matches(titulo, candidatos, n=limite + 1, cutoff=0.3)
    ids = [por_nome[nome] for nome in parecidos if por_nome[nome] != anuncio.produto_id][:limite]
    return _com_preco_liga(s, ids)


def buscar_produtos(s: Session, busca: str, limite: int = 20) -> list[tuple[ProdutoLiga, Decimal | None]]:
    consulta = select(ProdutoLiga.id).where(ProdutoLiga.ativo.is_(True)).order_by(ProdutoLiga.nome).limit(limite)
    if busca.strip():
        consulta = consulta.where(ProdutoLiga.nome.ilike(f"%{_escapar_like(busca.strip())}%", escape="\\"))
    return _com_preco_liga(s, list(s.scalars(consulta)))


VENDEDORES_OFERTAS = ("todos", "amazon", "fba", "elegiveis")
SITUACOES_OFERTAS = ("todas", "abertas")
ORDENS_OFERTAS = ("desconto", "diferenca", "recentes", "nome")
POR_PAGINA_OFERTAS = 50


@dataclass(frozen=True)
class FiltroOfertas:
    busca: str = ""
    categoria: str | None = None
    desconto_min: int | None = None
    vendedor: str = "todos"
    situacao: str = "todas"
    ordem: str = "desconto"


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
    diferenca: Decimal | None  # "À partir de" − preço da Amazon
    aberta: bool


def _vendedor_aceito(vendedor: str, envio: Envio, confiavel: bool) -> bool:
    if vendedor == "amazon":
        return envio is Envio.AMAZON
    if vendedor == "fba":
        return envio is Envio.FBA
    if vendedor == "elegiveis":
        return confiavel
    return True


_ORDENS = {
    "desconto": lambda l: (l.desconto is None, -(l.desconto or 0), l.produto.nome, l.produto.id),
    "diferenca": lambda l: (l.diferenca is None, -(l.diferenca or 0), l.produto.nome, l.produto.id),
    "recentes": lambda l: (-l.coletado_em.timestamp(), l.produto.nome, l.produto.id),
    "nome": lambda l: (l.produto.nome, l.produto.id),
}


def ofertas(s: Session, filtro: FiltroOfertas, config: ConfigAmazon) -> list[LinhaOferta]:
    """Uma linha por produto da Liga com ASIN confirmado e preço: a oferta mais barata da Amazon entre
    as aceitas pelo filtro de vendedor, contra o "À partir de" da Liga."""
    condicoes = [AnuncioAmazon.status_casamento == StatusCasamento.CONFIRMADO, PrecoAtualAmazon.preco.is_not(None)]
    if filtro.busca.strip():
        condicoes.append(ProdutoLiga.nome.ilike(f"%{_escapar_like(filtro.busca.strip())}%", escape="\\"))
    if filtro.categoria:
        condicoes.append(ProdutoLiga.tipo == filtro.categoria)
    consulta = (
        select(AnuncioAmazon, ProdutoLiga, PrecoAtualAmazon, VendedorAmazon, PrecoAtualLiga.preco_a_partir)
        .join(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAtualAmazon.vendedor_id)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(*condicoes)
    )
    abertas = set(s.scalars(select(Oportunidade.produto_id).where(Oportunidade.fechada_em.is_(None))))
    regras = Regras.de(config)
    melhores: dict[int, LinhaOferta] = {}
    for anuncio, produto, atual, vendedor, preco_liga in s.execute(consulta):
        info = Vendedor(vendedor.nome, vendedor.pct_positivas, vendedor.num_avaliacoes) if vendedor else None
        confiavel = atual.envio is Envio.AMAZON or (atual.envio is Envio.FBA and vendedor_confiavel(info, regras))
        if not _vendedor_aceito(filtro.vendedor, atual.envio, confiavel):
            continue
        atual_melhor = melhores.get(produto.id)
        if atual_melhor is not None and atual_melhor.preco <= atual.preco:
            continue
        melhores[produto.id] = LinhaOferta(
            produto=produto,
            preco_liga=preco_liga,
            anuncio=anuncio,
            preco=atual.preco,
            envio=atual.envio,
            vendedor=vendedor,
            confiavel=confiavel,
            coletado_em=atual.coletado_em,
            desconto=desconto_pct(atual.preco, preco_liga) if preco_liga else None,
            diferenca=preco_liga - atual.preco if preco_liga is not None else None,
            aberta=produto.id in abertas,
        )
    linhas = list(melhores.values())
    if filtro.desconto_min is not None:
        linhas = [l for l in linhas if l.desconto is not None and l.desconto >= filtro.desconto_min]
    if filtro.situacao == "abertas":
        linhas = [l for l in linhas if l.aberta]
    linhas.sort(key=_ORDENS[filtro.ordem])
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
