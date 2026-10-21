"""Cópia das imagens dos produtos (Liga) e anúncios (Amazon) para o bucket PÚBLICO de imagens no R2: a área de
negócio nunca aponta para a Liga ou a Amazon (link quebra, entrega o IP de quem vê). Roda no `manutencao`, um lote
por hora; produto ativo e anúncio casado, os com oportunidade aberta primeiro. Falha de um item não para os outros."""

import hashlib
import io
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from PIL import Image, UnidentifiedImageError
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.db.models import AnuncioAmazon, Casamento, Oportunidade, ProdutoLiga, StatusCasamento

log = logging.getLogger(__name__)

LADO_MAX = 600
QUALIDADE = 80
MAX_BYTES = 5 * 1024 * 1024
CACHE = "public, max-age=31536000, immutable"
CABECALHOS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/129.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
}


class ErroImagem(Exception):
    pass


class EnviadorImagens(Protocol):
    def enviar_bytes(self, dados: bytes, chave: str, tipo: str, cache: str) -> None: ...


@dataclass(frozen=True)
class Alvo:
    tipo: str  # "produtos" ou "anuncios"
    id: int
    ident: str  # liga_id ou asin
    url: str


@dataclass(frozen=True)
class Resultado:
    copiadas: int
    falhas: int


def chave_para(tipo: str, ident: str, origem: str) -> str:
    return f"{tipo}/{ident}-{hashlib.sha1(origem.encode()).hexdigest()[:10]}.webp"


def para_webp(dados: bytes) -> bytes:
    try:
        imagem = Image.open(io.BytesIO(dados))
        imagem.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as erro:
        raise ErroImagem("não é uma imagem") from erro
    imagem = imagem.convert("RGBA" if imagem.mode in ("RGBA", "LA", "P") else "RGB")
    imagem.thumbnail((LADO_MAX, LADO_MAX))
    saida = io.BytesIO()
    imagem.save(saida, "WEBP", quality=QUALIDADE)
    return saida.getvalue()


def baixar(http: httpx.Client, url: str) -> bytes:
    resposta = http.get(url, headers=CABECALHOS, timeout=20, follow_redirects=True)
    if resposta.status_code != 200:
        raise ErroImagem(f"HTTP {resposta.status_code}")
    if not resposta.headers.get("Content-Type", "").startswith("image/"):
        raise ErroImagem("a resposta não é imagem")
    if len(resposta.content) > MAX_BYTES:
        raise ErroImagem("imagem grande demais")
    return resposta.content


def _precisa(coluna_url: Any, coluna_origem: Any) -> tuple[Any, Any]:
    return coluna_url.is_not(None), or_(coluna_origem.is_(None), coluna_origem != coluna_url)


def pendentes(s: Session, limite: int) -> list[Alvo]:
    aberta = select(Oportunidade.produto_id).where(Oportunidade.fechada_em.is_(None))
    casado = select(Casamento.produto_id).where(Casamento.status == StatusCasamento.CONFIRMADO)
    produtos = s.execute(
        select(ProdutoLiga.id, ProdutoLiga.liga_id, ProdutoLiga.imagem_url,
               case((ProdutoLiga.id.in_(aberta), 0), (ProdutoLiga.id.in_(casado), 1), else_=2).label("prioridade"))
        .where(ProdutoLiga.ativo.is_(True), *_precisa(ProdutoLiga.imagem_url, ProdutoLiga.imagem_origem))
    ).all()
    aberta_anuncio = select(Oportunidade.anuncio_id).where(Oportunidade.fechada_em.is_(None))
    anuncios = s.execute(
        select(AnuncioAmazon.id, AnuncioAmazon.asin, AnuncioAmazon.imagem_url,
               case((AnuncioAmazon.id.in_(aberta_anuncio), 0), else_=1).label("prioridade"))
        .join(Casamento, Casamento.anuncio_id == AnuncioAmazon.id)
        .where(Casamento.status == StatusCasamento.CONFIRMADO,
               *_precisa(AnuncioAmazon.imagem_url, AnuncioAmazon.imagem_origem))
        .distinct()
    ).all()
    alvos = [(p.prioridade, 0, p.id, Alvo("produtos", p.id, p.liga_id, p.imagem_url)) for p in produtos]
    alvos += [(a.prioridade, 1, a.id, Alvo("anuncios", a.id, a.asin, a.imagem_url)) for a in anuncios]
    alvos.sort(key=lambda x: x[:3])
    return [alvo for *_, alvo in alvos[:limite]]


def _marcar(s: Session, alvo: Alvo, chave: str) -> None:
    modelo = ProdutoLiga if alvo.tipo == "produtos" else AnuncioAmazon
    linha = s.get(modelo, alvo.id)
    if linha is not None and linha.imagem_url == alvo.url:  # a origem não mudou enquanto copiava
        linha.imagem_chave, linha.imagem_origem = chave, alvo.url


def copiar_lote(
    sessoes: sessionmaker[Session], enviador: EnviadorImagens, http: httpx.Client, limite: int = 100,
    dormir: Callable[[float], None] = time.sleep, limpar: Callable[[str], str] = lambda t: t,
) -> Resultado:
    with sessoes() as s:
        alvos = pendentes(s, limite)
    copiadas = falhas = 0
    for i, alvo in enumerate(alvos):
        if i:
            dormir(1.0)
        try:
            chave = chave_para(alvo.tipo, alvo.ident, alvo.url)
            enviador.enviar_bytes(para_webp(baixar(http, alvo.url)), chave, "image/webp", CACHE)
            with sessoes() as s, s.begin():
                _marcar(s, alvo, chave)
            copiadas += 1
        except Exception as erro:  # noqa: BLE001 - um item com problema não para o lote
            falhas += 1
            log.warning("imagem %s/%s não copiada: %s", alvo.tipo, alvo.ident, limpar(f"{type(erro).__name__}: {erro}"))
    if alvos:
        log.info("imagens: %d copiadas, %d falhas (lote de %d)", copiadas, falhas, len(alvos))
    return Resultado(copiadas, falhas)
