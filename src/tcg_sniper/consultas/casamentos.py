"""Consultas de casamento (anúncio da Amazon × produto da Liga): a lista de produtos para casar, os pares
de um produto, as sugestões de produto para um anúncio e os textos das ações. Sem Jinja nem HTTP: o admin
antigo e a API usam as mesmas funções."""

import difflib
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from tcg_sniper.coletor_amazon.termo import termo_busca
from tcg_sniper.config import Config
from tcg_sniper.consultas.catalogo import casa_nome, classificar
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db import repositorio_termos as repo_termos
from tcg_sniper.db.models import (
    COLETOR_CASADOR,
    AnuncioAmazon,
    AvaliacaoIA,
    Casamento,
    ConferenciaCheckout,
    ConfigAmazon,
    Envio,
    EstadoColetorTipo,
    FilaAmazon,
    OfertaAmazon,
    OrigemCasamento,
    OrigemPreco,
    PrecoAtualAmazon,
    PrecoAtualLiga,
    ProdutoLiga,
    StatusCasamento,
    TermoBusca,
    VendedorAmazon,
)
from tcg_sniper.oportunidades.motor import Regras, Vendedor, atinge_desconto, vendedor_confiavel

# O que "Reavaliar com a IA" devolve para ela (regra em repositorio_casamento.reavaliar_produto).
EXPLICACAO_REAVALIAR = (
    "Reavaliar com a IA: voltam para ela os pendentes, os ignorados pelo automático e os casados em outro "
    "produto que deixaram de ser; suas decisões (manual ou sugerido pela IA) e os confirmados não mudam."
)

MENSAGENS_CASAMENTO: dict[str, tuple[str, str]] = {
    "link_salvo": ("success", "Link salvo; o anúncio será lido em alguns minutos."),
    "ja_confirmado": ("error", "Este anúncio já está confirmado para outro produto; nada mudou."),
    "rebuscar": ("success", "Produto na frente da fila da Amazon; a busca roda em alguns minutos."),
    "rebuscar_fora_da_fila": (
        "warning",
        "O produto ainda não entrou na fila da Amazon; ele entra sozinho em alguns minutos. Tente de novo depois.",
    ),
    "reavaliar": ("success", "Pares marcados para a IA reavaliar; o casador roda em instantes."),
    "reavaliar_ia_desligada": (
        "warning",
        (
            "Pares marcados para a IA reavaliar, mas a IA está desligada (Configurações → IA) ou sem chave: "
            "a reavaliação sai quando ela for ligada."
        ),
    ),
    "reavaliar_casador_pausado": (
        "warning",
        (
            "Pares marcados para a IA reavaliar, mas o casador está pausado (Serviços): a reavaliação sai "
            "quando ele for retomado."
        ),
    ),
    "reavaliar_nada": (
        "info",
        (
            "Nada para reavaliar: só voltam para a IA os pendentes, os ignorados pelo automático e os casados em "
            "outro produto que deixaram de ser."
        ),
    ),
    "termos_pedidos": ("success", "Pedido enviado: a IA gera os termos de busca em instantes, dentro do teto de gasto."),
    "termos_ia_desligada": (
        "warning",
        "Pedido guardado, mas a IA está desligada (Configurações → IA) ou sem chave: os termos saem quando ela for ligada.",
    ),
    "termos_casador_pausado": (
        "warning",
        "Pedido guardado, mas o casador está pausado (Serviços): os termos saem quando ele for retomado.",
    ),
    "termos_ja_casado": (
        "info",
        "Nada pedido à IA: o produto já tem anúncio confirmado, e a busca alternativa só vale para produto sem casamento.",
    ),
    "termos_fora_da_fila": ("warning", "O produto ainda não entrou na fila da Amazon; tente de novo em alguns minutos."),
}


def casador_parado(s: Session, agora: datetime, config: Config) -> str | None:
    """Por que o casador não vai rodar "em instantes": IA desligada/sem chave ("ia_desligada") ou casador
    pausado ("casador_pausado"); None se vai rodar."""
    if not (repo_ia.obter_config_ia(s).ligado and (config.openai_api_key or "").strip()):
        return "ia_desligada"
    if repo.obter_estado(s, agora, COLETOR_CASADOR).estado is not EstadoColetorTipo.ATIVO:
        return "casador_pausado"
    return None


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
ORDENS_CASAMENTO = ("preco_liga", "pendentes", "nome")


def categorias_da_liga(s: Session) -> list[str]:
    """Categorias (tipos) dos produtos da Liga, em ordem alfabética, para o filtro da lista."""
    return list(
        s.scalars(select(ProdutoLiga.tipo).where(ProdutoLiga.tipo.is_not(None)).distinct().order_by(ProdutoLiga.tipo))
    )


@dataclass(frozen=True)
class LinhaProdutoCasamento:
    produto: ProdutoLiga
    preco_liga: Decimal | None
    pendentes: int
    confirmados: int
    ignorados: int  # decisões sobre o par (sem os `outro_confirmado`, que vêm em `em_outro`)
    oportunidade: bool  # algum pendente já está a pelo menos o desconto mínimo abaixo da Liga
    ia_sugere: int = 0  # pendentes que a IA avaliou como o mesmo produto
    em_outro: int = 0  # ignorados porque o anúncio é confirmado para outro produto (`outro_confirmado`)

    @property
    def sem_par(self) -> bool:
        return self.pendentes == 0 and self.confirmados == 0

    @property
    def sugestoes(self) -> int:
        """Pares deste produto, em qualquer situação (anúncios sugeridos para ele)."""
        return self.pendentes + self.confirmados + self.ignorados + self.em_outro

    @property
    def situacao_produto(self) -> str:
        """Situação do produto no catálogo (`consultas.catalogo.SITUACOES_PRODUTO`)."""
        return classificar(self.confirmados, self.pendentes, self.sugestoes)


_FILTROS_SITUACAO = {
    "pendentes": lambda linha: linha.pendentes > 0,
    "oportunidade": lambda linha: linha.oportunidade,
    "sem_par": lambda linha: linha.sem_par,
    "casados": lambda linha: linha.confirmados > 0,
    "todos": lambda linha: True,
}

# "legado" é a ordem do admin antigo (com pendente que seria oportunidade, depois com pendentes, depois os
# demais; por nome); fica fora de ORDENS_CASAMENTO, que são as que a API aceita.
_ORDENS_CASAMENTO = {
    "preco_liga": lambda l: (l.preco_liga is None, -l.pendentes, l.produto.nome, l.produto.id),
    "pendentes": lambda l: (-l.pendentes, l.produto.nome, l.produto.id),
    "nome": lambda l: (l.produto.nome, l.produto.id),
    "legado": lambda l: (not l.oportunidade, l.pendentes == 0, l.produto.nome, l.produto.id),
}


def produtos_para_casar(
    s: Session,
    *,
    busca: str,
    categoria: str | None,
    situacao: str,
    com_preco: bool,
    desconto_min_pct: int,
    situacao_produto: str | None = None,
    ordem: str = "preco_liga",
) -> list[LinhaProdutoCasamento]:
    """Produtos ativos da Liga com as contagens de pares (anúncio da Amazon × produto), filtrados e ordenados
    por `ordem`: `preco_liga` (com preço na Liga primeiro, depois mais pendentes, depois nome), `pendentes`
    (mais pendentes primeiro, depois nome) ou `nome`. `situacao_produto` filtra também pela situação do
    produto no catálogo (casado, esperando decisão, só ignorados, sem candidato)."""
    if ordem not in _ORDENS_CASAMENTO:
        raise ValueError(f"ordem desconhecida: {ordem}")
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
    contagens: dict[tuple[int, StatusCasamento | OrigemCasamento], int] = {}
    oportunidade: set[int] = set()
    ia_sugere: dict[int, int] = {}
    if precos_liga:
        consulta_contagens = (
            select(Casamento.produto_id, Casamento.status, Casamento.origem, func.count())
            .where(Casamento.produto_id.in_(precos_liga))
            .group_by(Casamento.produto_id, Casamento.status, Casamento.origem)
        )
        for produto_id, situacao_par, origem, quantidade in s.execute(consulta_contagens):
            # `outro_confirmado` conta à parte: "ignorados" segue sendo decisão sobre o par.
            chave = origem if origem is OrigemCasamento.OUTRO_CONFIRMADO else situacao_par
            contagens[(produto_id, chave)] = contagens.get((produto_id, chave), 0) + quantidade
        consulta_precos = (
            select(Casamento.produto_id, PrecoAtualAmazon.preco)
            .join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == Casamento.anuncio_id)
            .where(Casamento.produto_id.in_(precos_liga), Casamento.status == StatusCasamento.PENDENTE)
        )
        for produto_id, preco in s.execute(consulta_precos):
            if atinge_desconto(preco, precos_liga[produto_id], desconto_min_pct):
                oportunidade.add(produto_id)
        consulta_ia = (
            select(Casamento.produto_id, func.count())
            .join(
                AvaliacaoIA,
                and_(AvaliacaoIA.anuncio_id == Casamento.anuncio_id, AvaliacaoIA.produto_id == Casamento.produto_id),
            )
            .where(
                Casamento.produto_id.in_(precos_liga),
                Casamento.status == StatusCasamento.PENDENTE,
                AvaliacaoIA.mesmo_produto.is_(True),
            )
            .group_by(Casamento.produto_id)
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
            em_outro=contagens.get((produto.id, OrigemCasamento.OUTRO_CONFIRMADO), 0),
        )
        for produto, preco in produtos
    ]
    linhas = [linha for linha in linhas if _FILTROS_SITUACAO[situacao](linha)]
    if situacao_produto:
        linhas = [linha for linha in linhas if linha.situacao_produto == situacao_produto]
    linhas.sort(key=_ORDENS_CASAMENTO[ordem])
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
    casamento: Casamento | None = None  # o par (anúncio, produto da tela)
    casado_com: ProdutoLiga | None = None  # par ignorado: o outro produto para o qual o anúncio é confirmado


@dataclass(frozen=True)
class DetalheCasamento:
    produto: ProdutoLiga
    preco_liga: Decimal | None
    pendentes: list[LinhaAnuncio]
    confirmados: list[LinhaAnuncio]
    ignorados: list[LinhaAnuncio]
    termos: tuple[TermoBusca, ...] = ()  # termos de busca alternativos guardados
    termos_pedidos_em: datetime | None = None  # "Gerar termos de busca" esperando o casador


def selo_do_vendedor(atual: PrecoAtualAmazon | None, vendedor: VendedorAmazon | None, regras: Regras) -> tuple[bool, bool]:
    """(confiavel, verificado) de uma leitura de preço: o mesmo critério dos alertas e da tela de Ofertas."""
    if atual is None:
        return False, False
    info = Vendedor(vendedor.nome, vendedor.pct_positivas, vendedor.num_avaliacoes) if vendedor else None
    confiavel = atual.envio is Envio.AMAZON or (atual.envio is Envio.FBA and vendedor_confiavel(info, regras))
    return confiavel, atual.origem in (OrigemPreco.PRODUTO, OrigemPreco.OFERTAS)


def conferencias_das_melhores(
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


def com_ofertas(s: Session, linhas: list[LinhaAnuncio], config: ConfigAmazon, agora: datetime) -> list[LinhaAnuncio]:
    por_anuncio = repo_amz.ofertas_da_ultima_leitura(s, [linha.anuncio.id for linha in linhas])
    precos = [
        (
            linha.anuncio.id,
            por_anuncio.get(linha.anuncio.id, ()),
            linha.atual.preco if linha.atual is not None and linha.atual.origem is OrigemPreco.OFERTAS else None,
        )
        for linha in linhas
    ]
    conferencias = conferencias_das_melhores(s, precos, config.checkout_validade_h, agora)
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
    """Os pares do produto, por status. Par ignorado cujo anúncio é confirmado para outro produto traz esse
    produto em `casado_com`."""
    agora = agora or repo.agora_utc()
    produto = s.get(ProdutoLiga, produto_id)
    if produto is None or not produto.ativo:
        return None
    liga = s.get(PrecoAtualLiga, produto_id)
    preco_liga = liga.preco_a_partir if liga else None
    consulta = (
        select(Casamento, AnuncioAmazon, PrecoAtualAmazon, VendedorAmazon)
        .join(AnuncioAmazon, AnuncioAmazon.id == Casamento.anuncio_id)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAtualAmazon.vendedor_id)
        .where(Casamento.produto_id == produto_id)
        .order_by(PrecoAtualAmazon.preco.nulls_last(), AnuncioAmazon.id)
    )
    regras = Regras.de(config)
    grupos: dict[StatusCasamento, list[LinhaAnuncio]] = {situacao: [] for situacao in StatusCasamento}
    for par, anuncio, atual, vendedor in s.execute(consulta):
        oportunidade = atinge_desconto(atual.preco if atual else None, preco_liga, config.desconto_min_pct)
        confiavel, verificado = selo_do_vendedor(atual, vendedor, regras)
        grupos[par.status].append(
            LinhaAnuncio(anuncio, atual, vendedor, oportunidade, confiavel, verificado, casamento=par)
        )
    todas = [linha for linhas in grupos.values() for linha in linhas]
    avaliacoes = repo_ia.avaliacoes_dos_pares(s, [(linha.anuncio.id, produto_id) for linha in todas])
    for situacao, linhas in grupos.items():
        grupos[situacao] = [replace(linha, ia=avaliacoes.get((linha.anuncio.id, produto_id))) for linha in linhas]
    ignorados_ids = [linha.anuncio.id for linha in grupos[StatusCasamento.IGNORADO]]
    casados: dict[int, ProdutoLiga] = {}
    if ignorados_ids:
        casados = {
            anuncio_id: casado
            for anuncio_id, casado in s.execute(
                select(Casamento.anuncio_id, ProdutoLiga)
                .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
                .where(Casamento.anuncio_id.in_(ignorados_ids), Casamento.status == StatusCasamento.CONFIRMADO)
            )
        }
    ignorados = [replace(linha, casado_com=casados.get(linha.anuncio.id)) for linha in grupos[StatusCasamento.IGNORADO]]
    pendentes = grupos[StatusCasamento.PENDENTE]
    pendentes.sort(key=lambda linha: -(linha.ia.confianca if linha.ia and linha.ia.mesmo_produto else -1))
    confirmados = com_ofertas(s, grupos[StatusCasamento.CONFIRMADO], config, agora)
    fila = s.get(FilaAmazon, produto_id)
    return DetalheCasamento(
        produto, preco_liga, pendentes, confirmados, ignorados,
        termos=tuple(repo_termos.termos_do_produto(s, produto_id)),
        termos_pedidos_em=fila.termos_pedidos_em if fila else None,
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


def sugestoes_para(
    s: Session, anuncio: AnuncioAmazon, limite: int = 3, excluir: Collection[int] = ()
) -> list[tuple[ProdutoLiga, Decimal | None]]:
    """Até `limite` produtos do catálogo com nome parecido com o título do anúncio (difflib), sem os de
    `excluir` (o produto de onde você veio e o já confirmado). Cada produto concorre com o nome em
    português e com o nome em inglês (quando há); vale o que parecer mais com o título."""
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
    ids = list(dict.fromkeys(por_nome[nome] for nome in parecidos if por_nome[nome] not in excluir))[:limite]
    return _com_preco_liga(s, ids)


def buscar_produtos(
    s: Session, busca: str, limite: int = 20, excluir: Collection[int] = ()
) -> list[tuple[ProdutoLiga, Decimal | None]]:
    """Produtos ativos cujo nome casa com `busca`, sem os de `excluir` (como em `sugestoes_para`)."""
    consulta = select(ProdutoLiga.id).where(ProdutoLiga.ativo.is_(True)).order_by(ProdutoLiga.nome).limit(limite)
    if excluir:
        consulta = consulta.where(ProdutoLiga.id.not_in(list(excluir)))
    if busca.strip():
        consulta = consulta.where(casa_nome(busca))
    return _com_preco_liga(s, list(s.scalars(consulta)))


# Sufixos de variação no fim do nome: Foil/Non-Foil, "Edition"/"Edição" e o idioma entre parênteses.
_SUFIXO_VARIACAO = re.compile(
    r"[\s\-–:]*(?:\((?:[^()]*\b(?:foil|edition|edição|inglês|english|português|portuguese|japonês|japanese)\b[^()]*)\)"
    r"|\bnon[- ]?foil\b|\bfoil\b|\bedition\b|\bedição\b)[\s\-–:]*$",
    re.IGNORECASE,
)


def _sem_sufixos_de_variacao(nome: str) -> str:
    anterior = None
    while anterior != nome:
        anterior, nome = nome, _SUFIXO_VARIACAO.sub("", nome)
    return nome.strip()


def parecidos_na_liga(s: Session, produto: ProdutoLiga, limite: int = 3) -> list[tuple[ProdutoLiga, Decimal | None]]:
    """Até `limite` produtos ativos da Liga de nome próximo ao do produto (sem ele): os que contêm o nome dele
    sem os sufixos de variação (Foil, Non-Foil, Edition, idioma entre parênteses), por nome. Servem para
    lembrar quem decide o par de que existe outra edição do mesmo produto."""
    base = _sem_sufixos_de_variacao(produto.nome)
    if not base:
        return []
    return buscar_produtos(s, base, limite=limite, excluir={produto.id})
