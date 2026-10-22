"""Consultas das telas da Amazon no admin."""

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from tcg_sniper.consultas import casamentos
from tcg_sniper.consultas.casamentos import (
    LinhaAnuncio,
    LinhaProdutoCasamento,
    com_ofertas,
    conferencias_das_melhores,
    selo_do_vendedor,
)
from tcg_sniper.consultas.catalogo import casa_nome
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db.models import (
    AnuncioAmazon,
    Casamento,
    Coleta,
    ConferenciaCheckout,
    ConfigAmazon,
    Envio,
    MotivoEncerramento,
    Oportunidade,
    OrigemCasamento,
    PrecoAmazon,
    PrecoAtualAmazon,
    PrecoAtualLiga,
    ProdutoLiga,
    StatusCasamento,
    StatusColeta,
    TipoColeta,
    VendedorAmazon,
)
from tcg_sniper.oportunidades.mensagens import ROTULOS_MOTIVO
from tcg_sniper.oportunidades.motor import CEM, Regras, atinge_desconto, preco_conferido


def ciclo_atual(s: Session) -> Coleta | None:
    return s.scalar(
        select(Coleta)
        .where(Coleta.tipo == TipoColeta.AMAZON, Coleta.status == StatusColeta.RODANDO)
        .order_by(Coleta.id.desc())
        .limit(1)
    )


POR_PAGINA_CASAMENTOS = 20


def produtos_para_casar(
    s: Session,
    *,
    busca: str,
    categoria: str | None,
    situacao: str,
    com_preco: bool,
    desconto_min_pct: int,
    situacao_produto: str | None = None,
) -> list[LinhaProdutoCasamento]:
    """`consultas.casamentos.produtos_para_casar` na ordem de sempre do admin antigo: com pendente que seria
    oportunidade, depois com pendentes, depois os demais; por nome."""
    return casamentos.produtos_para_casar(
        s,
        busca=busca,
        categoria=categoria,
        situacao=situacao,
        com_preco=com_preco,
        desconto_min_pct=desconto_min_pct,
        situacao_produto=situacao_produto,
        ordem="legado",
    )


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
    risco: tuple[datetime, str] | None = None  # desde quando está em risco e o motivo
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


def _desconto_exibido(preco: Decimal, preco_liga: Decimal) -> Decimal:
    """Desconto da tela de ofertas, arredondado para baixo em 2 casas: nunca mostra mais que o exato
    (24,996% vira 24,99%, não 25,00%), e o selo "≥ mínimo" bate com o filtro, que compara o exato."""
    return ((1 - preco / preco_liga) * CEM).quantize(Decimal("0.01"), ROUND_FLOOR)


_ORDENS = {
    "desconto": lambda l: (l.desconto is None, -(l.desconto or 0), l.produto.nome, l.produto.id),
    "diferenca": lambda l: (l.diferenca is None, -(l.diferenca or 0), l.produto.nome, l.produto.id),
    "recentes": lambda l: (-l.coletado_em.timestamp(), l.produto.nome, l.produto.id),
    "nome": lambda l: (l.produto.nome, l.produto.id),
}


def ofertas(s: Session, filtro: FiltroOfertas, config: ConfigAmazon) -> list[LinhaOferta]:
    """Uma linha por produto da Liga com ASIN confirmado e preço: a oferta mais barata da Amazon entre
    as aceitas pelo filtro de vendedor, contra o "À partir de" da Liga."""
    condicoes = [PrecoAtualAmazon.preco.is_not(None)]
    if filtro.busca.strip():
        condicoes.append(casa_nome(filtro.busca))
    if filtro.categoria:
        condicoes.append(ProdutoLiga.tipo == filtro.categoria)
    consulta = (
        select(AnuncioAmazon, ProdutoLiga, PrecoAtualAmazon, VendedorAmazon, PrecoAtualLiga.preco_a_partir, Casamento.origem)
        .join(Casamento, repo_casamento.condicao_confirmado(AnuncioAmazon.id))
        .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
        .join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAtualAmazon.vendedor_id)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(*condicoes)
    )
    # Oportunidades abertas por anúncio (no máximo uma por anúncio): o selo de risco é o da oportunidade do
    # anúncio da linha; "aberta" continua valendo para o produto (qualquer anúncio dele com oportunidade).
    riscos: dict[int, tuple[datetime | None, str | None]] = {}
    produtos_abertos: set[int] = set()
    for anuncio_id, produto_id, desde, motivo in s.execute(
        select(Oportunidade.anuncio_id, Oportunidade.produto_id, Oportunidade.em_risco_desde, Oportunidade.motivo_risco)
        .where(Oportunidade.fechada_em.is_(None))
    ):
        riscos[anuncio_id] = (desde, motivo)
        produtos_abertos.add(produto_id)
    regras = Regras.de(config)
    aceitas = []
    for anuncio, produto, atual, vendedor, preco_liga, origem in s.execute(consulta):
        confiavel, verificado = selo_do_vendedor(atual, vendedor, regras)
        if _vendedor_aceito(filtro.vendedor, atual.envio, confiavel):
            aceitas.append((anuncio, produto, atual, vendedor, preco_liga, confiavel, verificado, origem))
    agora = repo.agora_utc()
    lidas = repo_amz.ofertas_da_ultima_leitura(s, [anuncio.id for anuncio, *_ in aceitas])
    conferencias = conferencias_das_melhores(
        s, [(anuncio.id, lidas.get(anuncio.id, []), atual.preco) for anuncio, _, atual, *_ in aceitas],
        config.checkout_validade_h, agora,
    )
    melhores: dict[int, tuple[Decimal, LinhaOferta]] = {}
    for anuncio, produto, atual, vendedor, preco_liga, confiavel, verificado, origem in aceitas:
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
        desde, motivo_risco = riscos.get(anuncio.id, (None, None))
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
                desconto=_desconto_exibido(efetivo, preco_liga) if preco_liga else None,
                diferenca=preco_liga - efetivo if preco_liga is not None else None,
                aberta=produto.id in produtos_abertos,
                risco=(desde, ROTULOS_MOTIVO[MotivoEncerramento(motivo_risco)]) if desde is not None else None,
                origem_casamento=origem,
                conferencia=conferencia if conferido is not None else None,
                importada=bool(melhor and melhor.importada),
                origem_envio=melhor.origem_envio if melhor else None,
                prime=bool(melhor and melhor.prime),
            ),
        )
    if filtro.desconto_min is not None:  # o desconto exato do preço efetivo, sem arredondar
        linhas = [l for e, l in melhores.values() if atinge_desconto(e, l.preco_liga, filtro.desconto_min)]
    else:
        linhas = [linha for _, linha in melhores.values()]
    if filtro.situacao == "abertas":
        linhas = [l for l in linhas if l.aberta]
    linhas.sort(key=_ORDENS[filtro.ordem])
    return linhas


def amazon_do_produto(
    s: Session, produto_id: int, config: ConfigAmazon, agora: datetime | None = None
) -> list[LinhaAnuncio]:
    agora = agora or repo.agora_utc()
    consulta = (
        select(AnuncioAmazon, PrecoAtualAmazon, VendedorAmazon, Casamento)
        .join(
            Casamento,
            and_(
                Casamento.anuncio_id == AnuncioAmazon.id,
                Casamento.produto_id == produto_id,
                Casamento.status == StatusCasamento.CONFIRMADO,
            ),
        )
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAtualAmazon.vendedor_id)
        .order_by(PrecoAtualAmazon.preco.nulls_last(), AnuncioAmazon.id)
    )
    regras = Regras.de(config)
    linhas = [
        LinhaAnuncio(anuncio, atual, vendedor, False, *selo_do_vendedor(atual, vendedor, regras), casamento=par)
        for anuncio, atual, vendedor, par in s.execute(consulta)
    ]
    return com_ofertas(s, linhas, config, agora)


def historico_amazon(s: Session, produto_id: int, limite: int = 90) -> list[tuple[PrecoAmazon, str]]:
    consulta = (
        select(PrecoAmazon, AnuncioAmazon.asin)
        .join(AnuncioAmazon, AnuncioAmazon.id == PrecoAmazon.anuncio_id)
        .join(
            Casamento,
            and_(
                Casamento.anuncio_id == AnuncioAmazon.id,
                Casamento.produto_id == produto_id,
                Casamento.status == StatusCasamento.CONFIRMADO,
            ),
        )
        .order_by(PrecoAmazon.coletado_em.desc(), PrecoAmazon.id.desc())
        .limit(limite)
    )
    return [(preco, asin) for preco, asin in s.execute(consulta)]
