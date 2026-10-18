"""Consultas das telas da Amazon no admin."""

import difflib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from tcg_sniper.admin.consultas import casa_nome
from tcg_sniper.coletor_amazon.termo import termo_busca
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import (
    AnuncioAmazon,
    AvaliacaoIA,
    Coleta,
    ConferenciaCheckout,
    ConfigAmazon,
    Envio,
    OfertaAmazon,
    Oportunidade,
    OrigemCasamento,
    OrigemPreco,
    PrecoAmazon,
    PrecoAtualAmazon,
    PrecoAtualLiga,
    ProdutoLiga,
    StatusCasamento,
    StatusColeta,
    TipoColeta,
    VendedorAmazon,
)
from tcg_sniper.oportunidades.motor import (
    Regras,
    Vendedor,
    atinge_desconto,
    desconto_pct,
    preco_conferido,
    vendedor_confiavel,
)


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
    ia_sugere: int = 0  # pendentes que a IA avaliou como o mesmo produto

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
        condicoes.append(casa_nome(busca))
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
    ia_sugere: dict[int, int] = {}
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
        consulta_ia = (
            select(AnuncioAmazon.produto_id, func.count())
            .join(
                AvaliacaoIA,
                and_(AvaliacaoIA.anuncio_id == AnuncioAmazon.id, AvaliacaoIA.produto_id == AnuncioAmazon.produto_id),
            )
            .where(
                AnuncioAmazon.produto_id.in_(precos_liga),
                AnuncioAmazon.status_casamento == StatusCasamento.PENDENTE,
                AvaliacaoIA.mesmo_produto.is_(True),
            )
            .group_by(AnuncioAmazon.produto_id)
        )
        ia_sugere = dict(s.execute(consulta_ia).all())
    linhas = [
        LinhaProdutoCasamento(
            produto=produto,
            preco_liga=preco,
            pendentes=contagens.get((produto.id, StatusCasamento.PENDENTE), 0),
            confirmados=contagens.get((produto.id, StatusCasamento.CONFIRMADO), 0),
            ignorados=contagens.get((produto.id, StatusCasamento.IGNORADO), 0),
            oportunidade=produto.id in oportunidade,
            ia_sugere=ia_sugere.get(produto.id, 0),
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
    # Mesmas regras da tela de Ofertas: confiavel = vendedor aceito pelos alertas; verificado = preço lido na página do produto.
    confiavel: bool
    verificado: bool
    ia: AvaliacaoIA | None = None  # avaliação da IA para este anúncio contra este produto
    ofertas: tuple[OfertaAmazon, ...] = ()  # da última leitura do monitor, a mais barata primeiro
    conferencia: ConferenciaCheckout | None = None  # conferência ok válida para a melhor oferta


@dataclass(frozen=True)
class DetalheCasamento:
    produto: ProdutoLiga
    preco_liga: Decimal | None
    pendentes: list[LinhaAnuncio]
    confirmados: list[LinhaAnuncio]
    ignorados: list[LinhaAnuncio]


def _selo_do_vendedor(atual: PrecoAtualAmazon | None, vendedor: VendedorAmazon | None, regras: Regras) -> tuple[bool, bool]:
    """(confiavel, verificado) de uma leitura de preço: o mesmo critério dos alertas e da tela de Ofertas."""
    if atual is None:
        return False, False
    info = Vendedor(vendedor.nome, vendedor.pct_positivas, vendedor.num_avaliacoes) if vendedor else None
    confiavel = atual.envio is Envio.AMAZON or (atual.envio is Envio.FBA and vendedor_confiavel(info, regras))
    return confiavel, atual.origem in (OrigemPreco.PRODUTO, OrigemPreco.OFERTAS)


def _conferencias_das_melhores(
    s: Session,
    precos: Sequence[tuple[int, Sequence[OfertaAmazon], Decimal | None]],
    validade_h: int,
    agora: datetime,
) -> dict[int, ConferenciaCheckout]:
    """Conferência válida da melhor oferta de cada anúncio (anúncio, ofertas lidas, preço atual), numa
    consulta só (sem uma consulta por linha)."""
    chaves = []
    for anuncio_id, ofertas, preco in precos:
        melhor = next((o for o in ofertas if o.melhor), None)
        if melhor is not None and preco is not None:
            chaves.append((anuncio_id, melhor.vendedor_nome, preco))
    return repo_amz.conferencias_validas(s, chaves, agora, validade_h)


def _com_ofertas(s: Session, linhas: list[LinhaAnuncio], config: ConfigAmazon, agora: datetime) -> list[LinhaAnuncio]:
    por_anuncio = repo_amz.ofertas_da_ultima_leitura(s, [linha.anuncio.id for linha in linhas])
    precos = [
        (
            linha.anuncio.id,
            por_anuncio.get(linha.anuncio.id, ()),
            linha.atual.preco if linha.atual is not None and linha.atual.origem is OrigemPreco.OFERTAS else None,
        )
        for linha in linhas
    ]
    conferencias = _conferencias_das_melhores(s, precos, config.checkout_validade_h, agora)
    return [
        replace(
            linha,
            ofertas=tuple(por_anuncio.get(linha.anuncio.id, ())),
            conferencia=conferencias.get(linha.anuncio.id),
        )
        for linha in linhas
    ]


def detalhe_casamento(
    s: Session, produto_id: int, config: ConfigAmazon, agora: datetime | None = None
) -> DetalheCasamento | None:
    agora = agora or repo.agora_utc()
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
    regras = Regras.de(config)
    grupos: dict[StatusCasamento, list[LinhaAnuncio]] = {situacao: [] for situacao in StatusCasamento}
    for anuncio, atual, vendedor in s.execute(consulta):
        oportunidade = atinge_desconto(atual.preco if atual else None, preco_liga, config.desconto_min_pct)
        confiavel, verificado = _selo_do_vendedor(atual, vendedor, regras)
        grupos[anuncio.status_casamento].append(LinhaAnuncio(anuncio, atual, vendedor, oportunidade, confiavel, verificado))
    todas = [linha for linhas in grupos.values() for linha in linhas]
    avaliacoes = repo_ia.avaliacoes_dos_pares(s, [(linha.anuncio.id, produto_id) for linha in todas])
    for situacao, linhas in grupos.items():
        grupos[situacao] = [replace(linha, ia=avaliacoes.get((linha.anuncio.id, produto_id))) for linha in linhas]
    pendentes = grupos[StatusCasamento.PENDENTE]
    pendentes.sort(key=lambda linha: -(linha.ia.confianca if linha.ia and linha.ia.mesmo_produto else -1))
    confirmados = _com_ofertas(s, grupos[StatusCasamento.CONFIRMADO], config, agora)
    return DetalheCasamento(produto, preco_liga, pendentes, confirmados, grupos[StatusCasamento.IGNORADO])


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
    sem o produto ao qual o anúncio já está ligado. Cada produto concorre com o nome em português
    e com o nome em inglês (quando há); vale o que parecer mais com o título."""
    por_nome: dict[str, int] = {}
    indice: dict[str, set[str]] = {}
    consulta_nomes = (
        select(ProdutoLiga.id, ProdutoLiga.nome, ProdutoLiga.nome_en)
        .where(ProdutoLiga.ativo.is_(True))
        .order_by(ProdutoLiga.id)
    )
    for produto_id, nome, nome_en in s.execute(consulta_nomes):
        for nome_do_produto in (nome, nome_en):
            if not nome_do_produto:
                continue
            normalizado = _normalizar(nome_do_produto)
            if por_nome.setdefault(normalizado, produto_id) != produto_id:
                continue
            for token in _tokens(normalizado):
                indice.setdefault(token, set()).add(normalizado)
    titulo = _normalizar(anuncio.titulo_exibicao)
    candidatos = candidatos_para(titulo, list(por_nome), indice)
    # Até 2 nomes por produto: pede o dobro e fica com a primeira (melhor) ocorrência de cada um.
    parecidos = difflib.get_close_matches(titulo, candidatos, n=2 * limite + 2, cutoff=0.3)
    ids = list(dict.fromkeys(por_nome[nome] for nome in parecidos if por_nome[nome] != anuncio.produto_id))[:limite]
    return _com_preco_liga(s, ids)


def buscar_produtos(s: Session, busca: str, limite: int = 20) -> list[tuple[ProdutoLiga, Decimal | None]]:
    consulta = select(ProdutoLiga.id).where(ProdutoLiga.ativo.is_(True)).order_by(ProdutoLiga.nome).limit(limite)
    if busca.strip():
        consulta = consulta.where(casa_nome(busca))
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
    # False: o preço veio só do cartão da busca e a página do produto (vendedor, envio) não foi lida.
    verificado: bool
    coletado_em: datetime
    desconto: Decimal | None
    diferenca: Decimal | None  # "À partir de" − preço da Amazon
    aberta: bool
    origem_casamento: OrigemCasamento | None = None
    conferencia: ConferenciaCheckout | None = None
    importada: bool = False
    origem_envio: str | None = None
    prime: bool = False


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
        condicoes.append(casa_nome(filtro.busca))
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
    aceitas = []
    for anuncio, produto, atual, vendedor, preco_liga in s.execute(consulta):
        confiavel, verificado = _selo_do_vendedor(atual, vendedor, regras)
        if _vendedor_aceito(filtro.vendedor, atual.envio, confiavel):
            aceitas.append((anuncio, produto, atual, vendedor, preco_liga, confiavel, verificado))
    agora = repo.agora_utc()
    lidas = repo_amz.ofertas_da_ultima_leitura(s, [anuncio.id for anuncio, *_ in aceitas])
    conferencias = _conferencias_das_melhores(
        s, [(anuncio.id, lidas.get(anuncio.id, []), atual.preco) for anuncio, _, atual, *_ in aceitas],
        config.checkout_validade_h, agora,
    )
    melhores: dict[int, tuple[Decimal, LinhaOferta]] = {}
    for anuncio, produto, atual, vendedor, preco_liga, confiavel, verificado in aceitas:
        conferencia = conferencias.get(anuncio.id)
        conferido = (
            preco_conferido(conferencia.itens, conferencia.impostos, conferencia.total, conferencia.frete)
            if conferencia is not None
            else None
        )
        # Desconto, diferença e a escolha da melhor oferta usam o preço que vale para o aviso: o
        # conferido (itens + impostos, sem o frete) com conferência válida, senão o anunciado.
        efetivo = conferido if conferido is not None else atual.preco
        atual_melhor = melhores.get(produto.id)
        if atual_melhor is not None and atual_melhor[0] <= efetivo:
            continue
        ofertas_lidas = lidas.get(anuncio.id, [])
        melhor = next((o for o in ofertas_lidas if o.melhor), None)
        melhores[produto.id] = (
            efetivo,
            LinhaOferta(
                produto=produto,
                preco_liga=preco_liga,
                anuncio=anuncio,
                preco=atual.preco,
                envio=atual.envio,
                vendedor=vendedor,
                confiavel=confiavel,
                verificado=verificado,
                coletado_em=atual.coletado_em,
                desconto=desconto_pct(efetivo, preco_liga) if preco_liga else None,
                diferenca=preco_liga - efetivo if preco_liga is not None else None,
                aberta=produto.id in abertas,
                origem_casamento=anuncio.origem_casamento,
                conferencia=conferencia if conferido is not None else None,
                importada=bool(melhor and melhor.importada),
                origem_envio=melhor.origem_envio if melhor else None,
                prime=bool(melhor and melhor.prime),
            ),
        )
    linhas = [linha for _, linha in melhores.values()]
    if filtro.desconto_min is not None:
        linhas = [l for l in linhas if l.desconto is not None and l.desconto >= filtro.desconto_min]
    if filtro.situacao == "abertas":
        linhas = [l for l in linhas if l.aberta]
    linhas.sort(key=_ORDENS[filtro.ordem])
    return linhas


def amazon_do_produto(
    s: Session, produto_id: int, config: ConfigAmazon, agora: datetime | None = None
) -> list[LinhaAnuncio]:
    agora = agora or repo.agora_utc()
    consulta = (
        select(AnuncioAmazon, PrecoAtualAmazon, VendedorAmazon)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAtualAmazon.vendedor_id)
        .where(AnuncioAmazon.produto_id == produto_id, AnuncioAmazon.status_casamento == StatusCasamento.CONFIRMADO)
        .order_by(PrecoAtualAmazon.preco.nulls_last(), AnuncioAmazon.id)
    )
    regras = Regras.de(config)
    linhas = [
        LinhaAnuncio(anuncio, atual, vendedor, False, *_selo_do_vendedor(atual, vendedor, regras))
        for anuncio, atual, vendedor in s.execute(consulta)
    ]
    return _com_ofertas(s, linhas, config, agora)


def historico_amazon(s: Session, produto_id: int, limite: int = 90) -> list[tuple[PrecoAmazon, str]]:
    consulta = (
        select(PrecoAmazon, AnuncioAmazon.asin)
        .join(AnuncioAmazon, AnuncioAmazon.id == PrecoAmazon.anuncio_id)
        .where(AnuncioAmazon.produto_id == produto_id, AnuncioAmazon.status_casamento == StatusCasamento.CONFIRMADO)
        .order_by(PrecoAmazon.coletado_em.desc(), PrecoAmazon.id.desc())
        .limit(limite)
    )
    return [(preco, asin) for preco, asin in s.execute(consulta)]
