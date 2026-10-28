"""`casamento definir-idioma --ia`: a IA decide o idioma dos anúncios confirmados que o título não decide."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.casador.pergunta import avaliar_par
from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import (
    AnuncioAmazon,
    Casamento,
    PrecoAtualAmazon,
    PrecoAtualLiga,
    ProdutoLiga,
    StatusCasamento,
)
from tcg_sniper.db.repositorio_ia import IDIOMAS_CONHECIDOS
from tcg_sniper.ia.modelos import ChaveInvalida, ConfiguracaoInvalida, ErroIA, SemOrcamento, Transporte

FINALIDADE = "idioma"


@dataclass(frozen=True)
class DecisaoIdioma:
    anuncio_id: int
    idioma: str
    titulo: str
    motivo: str


@dataclass
class ResultadoIdiomaIA:
    definidos: dict[str, int] = field(default_factory=dict)  # idioma -> quantos (título + IA)
    sem_decisao: list[tuple[int, str]] = field(default_factory=list)
    suspeitos: list[tuple[int, str]] = field(default_factory=list)  # ja/outro: possível casamento errado
    decisoes: list[DecisaoIdioma] = field(default_factory=list)  # só as da IA, com o motivo
    falhas: int = 0
    interrompida: str | None = None


def _par_confirmado(s: Session, anuncio_id: int):
    """(anúncio, produto, preço Liga, preço Amazon, português confirmado) do casamento confirmado, ou None."""
    linha = s.execute(
        select(AnuncioAmazon, ProdutoLiga, PrecoAtualLiga.preco_a_partir, PrecoAtualAmazon.preco)
        .join(Casamento, Casamento.anuncio_id == AnuncioAmazon.id)
        .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .where(AnuncioAmazon.id == anuncio_id, Casamento.status == StatusCasamento.CONFIRMADO)
        .order_by(Casamento.produto_id)
        .limit(1)
    ).first()
    if linha is None:
        return None
    anuncio, produto, preco_liga, preco_amazon = linha
    portugues = repo_ia.portugues_confirmado(s, produto.id)
    for objeto in (anuncio, produto):
        s.expunge(objeto)
    return anuncio, produto, preco_liga, preco_amazon, portugues


def _gravar(sessoes: sessionmaker[Session], anuncio_id: int, idioma: str) -> None:
    with sessoes() as s, s.begin():
        anuncio = s.get(AnuncioAmazon, anuncio_id, with_for_update=True)
        if anuncio is not None and anuncio.idioma not in IDIOMAS_CONHECIDOS:  # nunca sobrescreve
            anuncio.idioma = idioma


def definir_idioma_com_ia(
    sessoes: sessionmaker[Session],
    transporte: Transporte,
    cliente_http: httpx.Client,
    zona: ZoneInfo,
    relogio: Callable[[], datetime],
    *,
    aplicar: bool,
    modelo: str | None = None,
    preco_entrada: Decimal | None = None,
    preco_saida: Decimal | None = None,
) -> ResultadoIdiomaIA:
    """Primeiro a heurística do título (grava só com `aplicar`); a IA só para os que sobram. Sem `aplicar` a
    IA é chamada (e registrada em `chamada_ia`), mas nada é gravado em `anuncio_amazon`."""
    with sessoes() as s, s.begin():
        base = repo_casamento.definir_idioma_confirmados(s, relogio(), aplicar=aplicar)
    r = ResultadoIdiomaIA(dict(base.definidos), [], list(base.suspeitos))
    pendentes = list(base.sem_decisao)
    for posicao, (anuncio_id, titulo) in enumerate(pendentes):
        with sessoes() as s, s.begin():
            par = _par_confirmado(s, anuncio_id)
        if par is None:
            r.sem_decisao.append((anuncio_id, titulo))
            continue
        anuncio, produto, preco_liga, preco_amazon, portugues = par
        try:
            veredito, _resposta, _ = avaliar_par(
                sessoes, transporte, cliente_http, anuncio, produto, preco_liga, preco_amazon,
                finalidade=FINALIDADE, zona=zona, modelo=modelo, preco_entrada=preco_entrada,
                preco_saida=preco_saida, relogio=relogio, portugues_confirmado=portugues,
            )
        except (SemOrcamento, ChaveInvalida, ConfiguracaoInvalida) as erro:
            r.interrompida = str(erro)
            r.sem_decisao.extend(pendentes[posicao:])
            break
        except ErroIA:
            r.falhas += 1
            r.sem_decisao.append((anuncio_id, titulo))
            continue
        idioma = veredito.idioma_anuncio
        if idioma not in IDIOMAS_CONHECIDOS:
            r.sem_decisao.append((anuncio_id, titulo))
            continue
        if aplicar:
            _gravar(sessoes, anuncio_id, idioma)
        r.definidos[idioma] = r.definidos.get(idioma, 0) + 1
        r.decisoes.append(DecisaoIdioma(anuncio_id, idioma, titulo, veredito.motivo))
        if idioma in ("ja", "outro"):
            r.suspeitos.append((anuncio_id, titulo))
    return r
