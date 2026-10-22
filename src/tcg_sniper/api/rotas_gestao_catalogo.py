"""Gestão: o catálogo da LigaMagic (ativos e inativos), o produto de gestão e o liga/desliga do monitoramento, um a um
e em lote. Ler exige `ver_area_gestao` e `ver_catalogo`; alterar exige `ver_area_gestao` e `editar_catalogo`. Toda
alteração fica em `acao_gestao`, na mesma transação."""

from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, model_validator

from tcg_sniper.api.dependencias import Contexto, exige_todas
from tcg_sniper.api.erros import ErroApi
from tcg_sniper.api.imagens import base_imagens, com_imagens
from tcg_sniper.api.permissoes import Permissao
from tcg_sniper.api.rotas_oportunidades import HistoricoSaida
from tcg_sniper.avisos.servico import zona_e_host
from tcg_sniper.consultas import catalogo_gestao as q
from tcg_sniper.consultas.casamentos import categorias_da_liga
from tcg_sniper.consultas.historico_produto import historico_produto
from tcg_sniper.consultas.variacao import pistas_variacao
from tcg_sniper.db.models import PrecoAtualLiga, ProdutoLiga, TipoAcaoGestao
from tcg_sniper.db.repositorio_acao_gestao import registrar
from tcg_sniper.db.repositorio_amazon import obter_config
from tcg_sniper.oportunidades.motor import Regras, desconto_pct

roteador = APIRouter(prefix="/api/gestao", tags=["gestão"])
VerCatalogo = Annotated[Contexto, Depends(exige_todas(Permissao.VER_AREA_GESTAO, Permissao.VER_CATALOGO))]
EditarCatalogo = Annotated[Contexto, Depends(exige_todas(Permissao.VER_AREA_GESTAO, Permissao.EDITAR_CATALOGO))]
Situacao = Literal["casado", "esperando_decisao", "so_ignorados", "sem_candidato"]
CURVA_DIAS = 30


class LinhaCatalogoSaida(BaseModel):
    id: int
    nome: str
    nome_en: str | None
    imagem: str | None
    categoria: str | None
    monitorado: bool
    preco_liga: Decimal | None
    lojas: int | None
    situacao: str
    pendentes: int
    confirmados: int
    melhor_amazon: Decimal | None


class ListaCatalogoSaida(BaseModel):
    itens: list[LinhaCatalogoSaida]
    total: int
    pagina: int
    por_pagina: int
    categorias: list[str]


class FiltroEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    busca: str = ""
    monitorado: q.Monitorado = "todos"
    categoria: str | None = None
    situacao: Situacao | None = None
    com_preco: bool = False

    def filtro(self) -> q.FiltroCatalogo:
        return q.FiltroCatalogo(self.busca, self.monitorado, self.categoria or None, self.situacao, self.com_preco)


class Filtros:
    """Os filtros da lista, na query string (os mesmos de `FiltroEntrada`)."""

    def __init__(
        self,
        busca: str = "",
        monitorado: q.Monitorado = "todos",
        categoria: str | None = None,
        situacao: Situacao | None = None,
        com_preco: bool = False,
    ):
        self.busca, self.monitorado, self.categoria = busca, monitorado, categoria or None
        self.situacao, self.com_preco = situacao, com_preco

    def filtro(self) -> q.FiltroCatalogo:
        return q.FiltroCatalogo(self.busca, self.monitorado, self.categoria, self.situacao, self.com_preco)


class AtivoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ativo: bool


class LoteEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acao: Literal["ligar", "desligar"]
    ids: list[int] | None = None
    filtro: FiltroEntrada | None = None
    esperado: int
    confirmar: bool

    @model_validator(mode="after")
    def _ids_ou_filtro(self):
        if (self.ids is None) == (self.filtro is None):
            raise ValueError("informe exatamente um de ids e filtro")
        return self


class LoteSaida(BaseModel):
    alvo: int
    alterados: int


class ProdutoGestao(BaseModel):
    id: int
    nome: str
    nome_en: str | None
    imagem: str | None
    categoria: str | None
    url: str
    pistas: list[str]


class LigaSaida(BaseModel):
    preco: Decimal | None
    lojas: int | None
    medio: Decimal | None
    lido_em: datetime | None


class MelhorAmazonSaida(BaseModel):
    preco: Decimal
    diferenca_pct: Decimal | None  # quanto a Amazon está abaixo da Liga (negativo: acima); None sem preço da Liga


class ContagemCasamentosSaida(BaseModel):
    pendentes: int
    confirmados: int
    ignorados: int


class ProdutoGestaoSaida(BaseModel):
    produto: ProdutoGestao
    monitorado: bool
    liga: LigaSaida
    melhor_amazon: MelhorAmazonSaida | None
    casamentos: ContagemCasamentosSaida
    curva: HistoricoSaida | None


def _linha(linha: q.LinhaCatalogo) -> dict:
    p = linha.produto
    return {
        "id": p.id, "nome": p.nome, "nome_en": p.nome_en, "imagem_chave": p.imagem_chave, "categoria": p.tipo,
        "monitorado": p.ativo, "preco_liga": linha.preco_liga, "lojas": linha.lojas,
        "situacao": linha.situacao_casamento, "pendentes": linha.pendentes, "confirmados": linha.confirmados,
        "melhor_amazon": linha.melhor_amazon,
    }


def _linha_saida(request: Request, linha: q.LinhaCatalogo) -> LinhaCatalogoSaida:
    return LinhaCatalogoSaida.model_validate(com_imagens(_linha(linha), base_imagens(request)))


@roteador.get("/catalogo")
def lista(
    request: Request, _c: VerCatalogo, filtros: Annotated[Filtros, Depends()],
    pagina: Annotated[int, Query(ge=1, le=10_000)] = 1,
) -> ListaCatalogoSaida:
    f = filtros.filtro()
    with request.app.state.sessoes() as s:
        resultado = q.linhas_catalogo(
            s, busca=f.busca, monitorado=f.monitorado, categoria=f.categoria, situacao=f.situacao,
            com_preco=f.com_preco, pagina=pagina,
        )
        categorias = categorias_da_liga(s)
        itens = [_linha(linha) for linha in resultado.itens]
    return ListaCatalogoSaida.model_validate({
        **com_imagens({"itens": itens}, base_imagens(request)),
        "total": resultado.total, "pagina": resultado.pagina, "por_pagina": resultado.por_pagina,
        "categorias": categorias,
    })


@roteador.patch("/produtos/{produto_id}")
def alterar_produto(
    request: Request, produto_id: int, entrada: AtivoEntrada, contexto: EditarCatalogo
) -> LinhaCatalogoSaida:
    estado = request.app.state
    with estado.sessoes() as s, s.begin():
        produto = s.get(ProdutoLiga, produto_id)
        if produto is None:
            raise ErroApi(404, "nao_encontrado", "Produto não encontrado.")
        produto.ativo = entrada.ativo
        s.flush()
        registrar(
            s, contexto.usuario_id, TipoAcaoGestao.CATALOGO_PRODUTO,
            {"produto_id": produto_id, "ativo": entrada.ativo}, estado.relogio(),
        )
        saida = _linha_saida(request, q.linha_produto(s, produto_id))
    return saida


@roteador.post("/catalogo/lote")
def lote(request: Request, entrada: LoteEntrada, contexto: EditarCatalogo) -> LoteSaida:
    estado = request.app.state
    with estado.sessoes() as s, s.begin():
        agora = estado.relogio()
        if entrada.filtro is not None:
            filtro = entrada.filtro.filtro()
            alvo_lote: q.FiltroCatalogo | list[int] = filtro
            alvo = q.contar_filtro(s, filtro)
            descricao = {"filtro": asdict(filtro)}
        else:
            ids = list(dict.fromkeys(entrada.ids))
            alvo_lote = ids
            alvo = q.contar_ids(s, ids)
            descricao = {"ids": ids}
        if not entrada.confirmar:
            return LoteSaida(alvo=alvo, alterados=0)
        if alvo != entrada.esperado:
            raise ErroApi(
                409, "contagem_mudou", f"A lista mudou: agora são {alvo} produtos. Confira e confirme de novo."
            )
        alterados = q.aplicar_lote(s, entrada.acao == "ligar", alvo_lote, agora)
        registrar(
            s, contexto.usuario_id, TipoAcaoGestao.CATALOGO_LOTE,
            {"acao": entrada.acao, **descricao, "alvo": alvo, "alterados": alterados}, agora,
        )
    return LoteSaida(alvo=alvo, alterados=alterados)


@roteador.get("/produtos/{produto_id}")
def produto_gestao(request: Request, produto_id: int, _c: VerCatalogo) -> ProdutoGestaoSaida:
    """O produto de gestão, ativo ou não (a gestão liga de volta); a curva de 30 dias só sai para o monitorado."""
    estado = request.app.state
    agora = estado.relogio()
    with estado.sessoes() as s:
        linha = q.linha_produto(s, produto_id)
        if linha is None:
            raise ErroApi(404, "nao_encontrado", "Produto não encontrado.")
        produto = linha.produto
        atual = s.get(PrecoAtualLiga, produto_id)
        zona, _ = zona_e_host(s)
        config = obter_config(s)
        historico = historico_produto(
            s, produto_id, agora - timedelta(days=CURVA_DIAS), agora, Regras.de(config),
            config.quase_oportunidade_min_pct, zona,
        )
        melhor = linha.melhor_amazon
        preco_liga = linha.preco_liga
        saida = {
            "produto": {
                "id": produto.id, "nome": produto.nome, "nome_en": produto.nome_en,
                "imagem_chave": produto.imagem_chave, "categoria": produto.tipo, "url": produto.url,
                "pistas": pistas_variacao(produto.nome),
            },
            "monitorado": produto.ativo,
            "liga": {
                "preco": preco_liga, "lojas": linha.lojas,
                "medio": atual.preco_medio if atual else None, "lido_em": atual.listagem_em if atual else None,
            },
            "melhor_amazon": None if melhor is None else {
                "preco": melhor,
                "diferenca_pct": desconto_pct(melhor, preco_liga) if preco_liga and preco_liga > 0 else None,
            },
            "casamentos": {"pendentes": linha.pendentes, "confirmados": linha.confirmados, "ignorados": linha.ignorados},
            "curva": None if historico is None else {**asdict(historico), "periodo": f"{CURVA_DIAS}d"},
        }
    return ProdutoGestaoSaida.model_validate(com_imagens(saida, base_imagens(request)))
