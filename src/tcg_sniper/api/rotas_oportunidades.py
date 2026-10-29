"""Área de negócio: oportunidades e histórico de produto (só dado de mercado). Toda rota exige `ver_oportunidades`."""

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from tcg_sniper.api.dependencias import Contexto, exige
from tcg_sniper.api.erros import ErroApi
from tcg_sniper.api.imagens import base_imagens, com_imagens
from tcg_sniper.api.permissoes import Permissao
from tcg_sniper.avisos.servico import zona_e_host
from tcg_sniper.consultas import oportunidades as q
from tcg_sniper.consultas.historico_produto import historico_produto
from tcg_sniper.consultas.quase_la import quase_la
from tcg_sniper.db.models import MotivoEncerramento
from tcg_sniper.db.repositorio_amazon import obter_config
from tcg_sniper.oportunidades.motor import Regras

roteador = APIRouter(prefix="/api", tags=["oportunidades"])
VerOportunidades = Annotated[Contexto, Depends(exige(Permissao.VER_OPORTUNIDADES))]
LIMITE_QUASE_PADRAO = 200


class ProdutoSaida(BaseModel):
    id: int
    nome: str
    imagem: str | None
    ativo: bool


class AnuncioSaida(BaseModel):
    titulo: str
    url: str
    imagem: str | None


class NumerosSaida(BaseModel):
    diferenca_bruta: Decimal
    oportunidades: int
    desconto_medio: Decimal | None
    duracao_media_min: int | None
    produtos: int


class DiaSaida(BaseModel):
    dia: date
    oportunidades: int


class ResumoSaida(BaseModel):
    periodo: str
    numeros: NumerosSaida
    por_dia: list[DiaSaida]


class AtivaSaida(BaseModel):
    id: int
    produto: ProdutoSaida
    anuncio: AnuncioSaida
    preco_amazon: Decimal
    preco_liga: Decimal
    desconto_pct: Decimal
    aberta_em: datetime
    em_risco_desde: datetime | None
    motivo_risco: str | None


class AtivasSaida(BaseModel):
    ativas: list[AtivaSaida]
    ultima_aberta_em: datetime | None


class OportunidadeSaida(BaseModel):
    id: int
    produto: ProdutoSaida
    aberta_em: datetime
    fechada_em: datetime | None
    aberta: bool
    duracao_min: int
    alertas: int
    preco_alertado: Decimal
    menor_preco: Decimal
    preco_liga: Decimal
    desconto_pct: Decimal
    motivo: str | None
    anuncio: AnuncioSaida


class EncerradasSaida(BaseModel):
    itens: list[OportunidadeSaida]
    total: int
    pagina: int
    por_pagina: int


class QuaseSaida(BaseModel):
    produto: ProdutoSaida
    anuncio: AnuncioSaida
    preco_amazon: Decimal
    preco_liga: Decimal
    desconto_pct: Decimal
    falta_reais: Decimal
    falta_pp: Decimal


class QuaseListaSaida(BaseModel):
    itens: list[QuaseSaida]
    desconto_min_pct: int
    piso_pct: int


class CabecalhoSaida(BaseModel):
    id: int
    nome: str
    edicao: str | None
    imagem: str | None
    url_liga: str


class PontoAmazonSaida(BaseModel):
    t: datetime
    preco: Decimal
    anuncio: str


class PontoLigaSaida(BaseModel):
    t: datetime
    preco: Decimal


class FaixaSaida(BaseModel):
    id: int
    inicio: datetime
    fim: datetime
    aberta: bool
    motivo: str | None


class HistoricoSaida(BaseModel):
    produto: CabecalhoSaida
    anuncio: AnuncioSaida | None
    sem_preco: bool
    anuncios_casados: int
    periodo: str
    escala: str
    amazon: list[PontoAmazonSaida]
    liga: list[PontoLigaSaida]
    liga_medio: list[PontoLigaSaida]
    desconto_min_pct: int
    faixas: list[FaixaSaida]
    oportunidades: list[OportunidadeSaida]
    recorrencia_30d: int
    quase_la: bool


def _desde(periodo: str, agora: datetime) -> datetime | None:
    try:
        return q.desde_do_periodo(periodo, agora)
    except ValueError:
        raise ErroApi(400, "periodo_invalido", "Período inválido.") from None


@roteador.get("/oportunidades/resumo")
def resumo(request: Request, _c: VerOportunidades, periodo: str = "7d") -> ResumoSaida:
    estado = request.app.state
    agora = estado.relogio()
    desde = _desde(periodo, agora)
    with estado.sessoes() as s:
        zona, _ = zona_e_host(s)
        numeros = q.numeros_periodo(s, desde, agora)
        dias = q.por_dia(s, desde, agora, zona)
    return ResumoSaida(periodo=periodo, numeros=NumerosSaida(**asdict(numeros)),
                       por_dia=[DiaSaida(**asdict(d)) for d in dias])


@roteador.get("/oportunidades/ativas")
def ativas(request: Request, _c: VerOportunidades) -> AtivasSaida:
    with request.app.state.sessoes() as s:
        return AtivasSaida(ativas=[AtivaSaida.model_validate(com_imagens(asdict(a), base_imagens(request))) for a in q.ativas(s)],
                           ultima_aberta_em=q.ultima_aberta_em(s))


@roteador.get("/oportunidades/encerradas")
def encerradas(
    request: Request, _c: VerOportunidades, periodo: str = "7d", motivo: MotivoEncerramento | None = None,
    pagina: Annotated[int, Query(ge=1, le=10_000)] = 1,
) -> EncerradasSaida:
    estado = request.app.state
    agora = estado.relogio()
    desde = _desde(periodo, agora)
    with estado.sessoes() as s:
        resultado = q.encerradas(s, desde, motivo, pagina, agora)
    return EncerradasSaida.model_validate(com_imagens(asdict(resultado), base_imagens(request)))


def _regras_e_piso(s) -> tuple[Regras, int]:
    config = obter_config(s)
    return Regras.de(config), config.quase_oportunidade_min_pct


@roteador.get("/oportunidades/quase")
def quase(
    request: Request, _c: VerOportunidades, limite: Annotated[int, Query(ge=1, le=500)] = LIMITE_QUASE_PADRAO
) -> QuaseListaSaida:
    estado = request.app.state
    with estado.sessoes() as s:
        regras, piso = _regras_e_piso(s)
        itens = quase_la(s, regras, piso, estado.relogio(), limite=limite)
    return QuaseListaSaida(itens=[QuaseSaida.model_validate(com_imagens(asdict(i), base_imagens(request))) for i in itens],
                           desconto_min_pct=regras.desconto_min_pct, piso_pct=piso)


@roteador.get("/produtos/{produto_id}/historico")
def historico(request: Request, produto_id: int, _c: VerOportunidades, periodo: str = "30d") -> HistoricoSaida:
    estado = request.app.state
    agora = estado.relogio()
    desde = _desde(periodo, agora)
    with estado.sessoes() as s:
        zona, _ = zona_e_host(s)
        regras, piso = _regras_e_piso(s)
        h = historico_produto(s, produto_id, desde, agora, regras, piso, zona)
    if h is None:
        raise ErroApi(404, "nao_encontrado", "Produto não encontrado.")
    return HistoricoSaida.model_validate({**com_imagens(asdict(h), base_imagens(request)), "periodo": periodo})
