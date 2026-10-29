"""Gestão: as ofertas da Amazon contra o "À partir de" da Liga (a melhor oferta por produto com anúncio confirmado).
Ler exige `ver_area_gestao` e `ver_catalogo`. Mesmos filtros e valores do admin antigo; 50 por página."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from tcg_sniper.api.dependencias import Contexto, exige_todas
from tcg_sniper.api.erros import ErroApi
from tcg_sniper.api.imagens import base_imagens, com_imagens
from tcg_sniper.api.permissoes import Permissao
from tcg_sniper.consultas import ofertas as q
from tcg_sniper.consultas.casamentos import categorias_da_liga
from tcg_sniper.consultas.historico import paginar
from tcg_sniper.db.repositorio_amazon import obter_config
from tcg_sniper.oportunidades.motor import preco_conferido

roteador = APIRouter(prefix="/api/gestao", tags=["gestão"])
VerCatalogo = Annotated[Contexto, Depends(exige_todas(Permissao.VER_AREA_GESTAO, Permissao.VER_CATALOGO))]


class AnuncioOfertaSaida(BaseModel):
    asin: str
    titulo: str
    url: str
    imagem: str | None


class VendedorOfertaSaida(BaseModel):
    nome: str | None
    envio: str  # amazon | fba | proprio | desconhecido


class RiscoSaida(BaseModel):
    desde: datetime
    motivo: str


class ConferidoSaida(BaseModel):
    preco: Decimal  # itens + impostos, sem o frete
    impostos: Decimal | None
    frete: Decimal | None  # à parte


class OfertaSaida(BaseModel):
    produto_id: int
    produto: str
    imagem: str | None
    preco_liga: Decimal | None
    anuncio: AnuncioOfertaSaida
    preco: Decimal | None
    desconto_pct: Decimal | None
    diferenca: Decimal | None
    envio: str
    vendedor: VendedorOfertaSaida
    confiavel: bool
    verificado: bool
    aberta: bool
    risco: RiscoSaida | None
    origem: str | None
    prime: bool
    importada: bool
    origem_envio: str | None
    conferido: ConferidoSaida | None
    coletado_em: datetime


class ListaOfertasSaida(BaseModel):
    itens: list[OfertaSaida]
    total: int
    pagina: int
    por_pagina: int
    categorias: list[str]
    desconto_min_pct: int  # o desconto configurado (atalho "≥ desconto configurado")


def _item(linha: q.LinhaOferta) -> dict:
    conferencia = linha.conferencia
    return {
        "produto_id": linha.produto.id, "produto": linha.produto.nome, "imagem_chave": linha.produto.imagem_chave,
        "preco_liga": linha.preco_liga,
        "anuncio": {
            "asin": linha.anuncio.asin, "titulo": linha.anuncio.titulo, "url": linha.anuncio.url,
            "imagem_chave": linha.anuncio.imagem_chave,
        },
        "preco": linha.preco, "desconto_pct": linha.desconto, "diferenca": linha.diferenca,
        "envio": linha.envio.value,
        "vendedor": {"nome": linha.vendedor.nome if linha.vendedor else None, "envio": linha.envio.value},
        "confiavel": linha.confiavel, "verificado": linha.verificado, "aberta": linha.aberta,
        "risco": None if linha.risco is None else {"desde": linha.risco[0], "motivo": linha.risco[1]},
        "origem": linha.origem_casamento.value if linha.origem_casamento else None,
        "prime": linha.prime, "importada": linha.importada, "origem_envio": linha.origem_envio,
        "conferido": None if conferencia is None else {
            "preco": preco_conferido(conferencia.itens, conferencia.impostos, conferencia.total, conferencia.frete),
            "impostos": conferencia.impostos, "frete": conferencia.frete,
        },
        "coletado_em": linha.coletado_em,
    }


@roteador.get("/ofertas")
def lista(
    request: Request, _c: VerCatalogo,
    busca: Annotated[str, Query(max_length=200)] = "",
    categoria: str = "",
    desconto_min: Annotated[int | None, Query(ge=0, le=100)] = None,
    vendedor: Literal["todos", "amazon", "fba", "elegiveis"] = "todos",
    situacao: Literal["todas", "abertas"] = "todas",
    ordem: Literal["desconto", "diferenca", "recentes", "nome"] = "desconto",
    pagina: Annotated[int, Query(ge=1, le=10_000)] = 1,
) -> ListaOfertasSaida:
    with request.app.state.sessoes() as s:
        categorias = categorias_da_liga(s)
        if categoria and categoria not in categorias:
            raise ErroApi(400, "filtro_invalido", f"Categoria inválida: {categoria}.")
        config = obter_config(s)
        filtro = q.FiltroOfertas(
            busca=busca, categoria=categoria or None, desconto_min=desconto_min, vendedor=vendedor,
            situacao=situacao, ordem=ordem,
        )
        linhas = q.ofertas(s, filtro, config)
        da_pagina, numero, _ = paginar(linhas, pagina, q.POR_PAGINA_OFERTAS)
        itens = [_item(linha) for linha in da_pagina]
        minimo = config.desconto_min_pct
    return ListaOfertasSaida.model_validate({
        **com_imagens({"itens": itens}, base_imagens(request)),
        "total": len(linhas), "pagina": numero, "por_pagina": q.POR_PAGINA_OFERTAS, "categorias": categorias,
        "desconto_min_pct": minimo,
    })
