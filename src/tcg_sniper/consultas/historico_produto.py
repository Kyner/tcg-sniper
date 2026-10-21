"""Histórico de um produto ativo na área de negócio: curva da Amazon (menor preço elegível por hora, ou por dia acima
de 90 dias, entre os anúncios confirmados), curvas da Liga, faixas das oportunidades e recorrência. O `preco_amazon`
só grava quando o preço muda (ou na 1ª leitura do dia): o valor de um anúncio num intervalo é a última linha até o fim
dele, por até 26 h. Carrega só as linhas dos anúncios deste produto."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcg_sniper.consultas.oportunidades import AnuncioResumo, Encerrada, linha_oportunidade
from tcg_sniper.consultas.quase_la import quase_la
from tcg_sniper.db.models import (
    AnuncioAmazon,
    Casamento,
    MotivoEncerramento,
    Oportunidade,
    PrecoAmazon,
    PrecoAtualAmazon,
    PrecoListagem,
    ProdutoLiga,
    ResumoPreco,
    StatusCasamento,
    VendedorAmazon,
)
from tcg_sniper.oportunidades import motor
from tcg_sniper.oportunidades.montagem import vendedor_do_motor

VALIDADE_LEITURA = timedelta(hours=26)
LIMITE_POR_HORA = timedelta(days=90)


@dataclass(frozen=True)
class PontoAmazon:
    t: datetime
    preco: Decimal
    anuncio: str


@dataclass(frozen=True)
class PontoLiga:
    t: datetime
    preco: Decimal


@dataclass(frozen=True)
class Faixa:
    id: int
    inicio: datetime
    fim: datetime
    aberta: bool
    motivo: str | None


@dataclass(frozen=True)
class CabecalhoProduto:
    id: int
    nome: str
    edicao: str | None
    imagem_chave: str | None
    url_liga: str


@dataclass(frozen=True)
class Historico:
    produto: CabecalhoProduto
    anuncio: AnuncioResumo | None
    escala: str
    amazon: list[PontoAmazon]
    liga: list[PontoLiga]
    liga_medio: list[PontoLiga]
    desconto_min_pct: int
    faixas: list[Faixa]
    oportunidades: list[Encerrada]
    recorrencia_30d: int
    quase_la: bool


def _truncar(t: datetime, escala: str, zona: ZoneInfo) -> datetime:
    local = t.astimezone(zona).replace(minute=0, second=0, microsecond=0)
    return local.replace(hour=0) if escala == "dia" else local


def _curva_amazon(s, anuncios, desde, agora, regras, zona) -> tuple[str, list[PontoAmazon]]:
    if not anuncios:
        return "hora", []
    titulos = {a.id: a.titulo for a in anuncios}
    filtro = [PrecoAmazon.anuncio_id.in_(titulos), PrecoAmazon.coletado_em <= agora]
    if desde is not None:
        filtro.append(PrecoAmazon.coletado_em >= desde - VALIDADE_LEITURA)
    linhas = s.execute(
        select(PrecoAmazon, VendedorAmazon).outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAmazon.vendedor_id)
        .where(*filtro).order_by(PrecoAmazon.coletado_em)
    ).all()
    if not linhas:
        return "hora", []
    inicio = desde or linhas[0][0].coletado_em
    escala = "dia" if agora - inicio > LIMITE_POR_HORA else "hora"
    passo = timedelta(days=1) if escala == "dia" else timedelta(hours=1)
    pontos, ultima, i = [], {}, 0
    balde = _truncar(inicio, escala, zona)
    while balde <= agora:
        fim = balde + passo
        while i < len(linhas) and linhas[i][0].coletado_em < fim:
            leitura, vendedor = linhas[i]
            ultima[leitura.anuncio_id] = (leitura, vendedor)
            i += 1
        validos = [
            leitura for leitura, vendedor in ultima.values()
            if leitura.preco is not None and leitura.coletado_em >= balde - VALIDADE_LEITURA
            and motor.vendedor_elegivel(leitura.envio, vendedor_do_motor(vendedor), regras)
        ]
        if validos:
            menor = min(validos, key=lambda l: l.preco)
            pontos.append(PontoAmazon(balde, menor.preco, titulos[menor.anuncio_id]))
        balde = _truncar(fim, escala, zona) if escala == "hora" else (balde + passo).astimezone(zona).replace(hour=0)
    return escala, pontos


def historico_produto(
    s: Session, produto_id: int, desde: datetime | None, agora: datetime, regras: motor.Regras, piso_pct: int,
    zona: ZoneInfo,
) -> Historico | None:
    produto = s.get(ProdutoLiga, produto_id)
    if produto is None or not produto.ativo:
        return None
    anuncios = list(s.scalars(
        select(AnuncioAmazon).join(Casamento, Casamento.anuncio_id == AnuncioAmazon.id)
        .where(Casamento.produto_id == produto_id, Casamento.status == StatusCasamento.CONFIRMADO)
    ))
    escala, amazon = _curva_amazon(s, anuncios, desde, agora, regras, zona)
    periodo_liga = [] if desde is None else [PrecoListagem.coletado_em >= desde]
    liga = [PontoLiga(l.coletado_em, l.preco_a_partir) for l in s.scalars(
        select(PrecoListagem).where(PrecoListagem.produto_id == produto_id, PrecoListagem.preco_a_partir.is_not(None),
                                    *periodo_liga).order_by(PrecoListagem.coletado_em))]
    periodo_resumo = [] if desde is None else [ResumoPreco.coletado_em >= desde]
    liga_medio = [PontoLiga(r.coletado_em, r.preco_medio) for r in s.scalars(
        select(ResumoPreco).where(ResumoPreco.produto_id == produto_id, ResumoPreco.preco_medio.is_not(None),
                                  *periodo_resumo).order_by(ResumoPreco.coletado_em))]
    ops = list(s.scalars(
        select(Oportunidade).where(Oportunidade.produto_id == produto_id,
                                   *([] if desde is None else [Oportunidade.aberta_em >= desde]))
        .order_by(Oportunidade.aberta_em.desc())
    ))
    faixas = [Faixa(op.id, op.aberta_em, op.deixou_de_valer_em or op.fechada_em or agora, op.fechada_em is None,
                    None if op.motivo_encerramento is None else str(op.motivo_encerramento)) for op in ops]
    recorrencia = len([op for op in s.scalars(select(Oportunidade).where(
        Oportunidade.produto_id == produto_id, Oportunidade.aberta_em >= agora - timedelta(days=30),
    )) if op.motivo_encerramento != MotivoEncerramento.CASAMENTO_DESFEITO])
    atual = s.execute(
        select(AnuncioAmazon).join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .where(AnuncioAmazon.id.in_([a.id for a in anuncios]), PrecoAtualAmazon.preco.is_not(None))
        .order_by(PrecoAtualAmazon.preco).limit(1)
    ).scalar()
    return Historico(
        produto=CabecalhoProduto(produto.id, produto.nome, produto.edicao, produto.imagem_chave, produto.url),
        anuncio=None if atual is None else AnuncioResumo(atual.titulo, atual.url, atual.imagem_chave),
        escala=escala, amazon=amazon, liga=liga, liga_medio=liga_medio, desconto_min_pct=regras.desconto_min_pct,
        faixas=faixas, oportunidades=[linha_oportunidade(op, produto, agora) for op in ops],
        recorrencia_30d=recorrencia, quase_la=bool(quase_la(s, regras, piso_pct, agora, produto_id=produto_id)),
    )
