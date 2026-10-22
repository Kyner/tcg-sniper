"""Gestão: revisão dos casamentos (anúncio da Amazon × produto da Liga). Só leitura; exige `ver_area_gestao` e
`revisar_casamentos`."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from tcg_sniper.api.dependencias import Contexto, exige_todas
from tcg_sniper.api.erros import ErroApi
from tcg_sniper.api.imagens import base_imagens, com_imagens
from tcg_sniper.api.permissoes import Permissao
from tcg_sniper.consultas import casamentos as q
from tcg_sniper.consultas.variacao import pistas_variacao, termos_variacao
from tcg_sniper.db.models import PrecoAtualLiga, ProdutoLiga
from tcg_sniper.db.repositorio_amazon import obter_config

roteador = APIRouter(prefix="/api/gestao", tags=["gestão"])
RevisarCasamentos = Annotated[
    Contexto, Depends(exige_todas(Permissao.VER_AREA_GESTAO, Permissao.REVISAR_CASAMENTOS))
]
POR_PAGINA = 20
Situacao = Literal["casado", "esperando_decisao", "so_ignorados", "sem_candidato", "todos"]
Ordem = Literal["preco_liga", "pendentes", "nome"]


class ProdutoCasamentoSaida(BaseModel):
    id: int
    nome: str
    nome_en: str | None
    imagem: str | None
    categoria: str | None
    preco_liga: Decimal | None
    pendentes: int
    confirmados: int
    ignorados: int
    em_outro: int
    ia_sugere: int
    situacao: str


class ListaCasamentosSaida(BaseModel):
    itens: list[ProdutoCasamentoSaida]
    total: int
    pagina: int
    por_pagina: int
    categorias: list[str]


class ProdutoLigaSaida(BaseModel):
    id: int
    nome: str
    nome_en: str | None
    imagem: str | None
    categoria: str | None
    url: str
    preco_liga: Decimal | None
    lojas: int | None
    pistas: list[str]


class ParecidoSaida(BaseModel):
    id: int
    nome: str
    imagem: str | None
    preco_liga: Decimal | None


class IaSaida(BaseModel):
    mesmo_produto: bool
    confianca: int
    motivo: str
    idioma: str | None


class AnuncioRevisaoSaida(BaseModel):
    anuncio_id: int
    asin: str
    titulo: str
    url: str
    imagem: str | None
    preco: Decimal | None
    vendedor: str | None
    termos_variacao: list[str]
    ia: IaSaida | None
    origem: str | None
    revisado_em: datetime | None
    oportunidade: bool
    casado_com: ParecidoSaida | None


class NavegacaoSaida(BaseModel):
    posicao: int
    total: int
    anterior: int | None
    proximo: int | None


class RevisaoSaida(BaseModel):
    produto: ProdutoLigaSaida
    navegacao: NavegacaoSaida
    para_decidir: list[AnuncioRevisaoSaida]
    confirmados: list[AnuncioRevisaoSaida]
    ignorados: list[AnuncioRevisaoSaida]
    parecidos: list[ParecidoSaida]
    termos: list[str]
    termos_pedidos: bool


class Filtros:
    """Os filtros da lista; a revisão de um produto recebe os mesmos para navegar entre os produtos filtrados."""

    def __init__(
        self,
        busca: str = "",
        situacao: Situacao = "esperando_decisao",
        categoria: str | None = None,
        com_preco: bool = False,
        ordem: Ordem = "preco_liga",
    ):
        self.busca, self.situacao, self.categoria = busca, situacao, categoria or None
        self.com_preco, self.ordem = com_preco, ordem


def _linhas(s, filtros: Filtros) -> list[q.LinhaProdutoCasamento]:
    return q.produtos_para_casar(
        s, busca=filtros.busca, categoria=filtros.categoria, situacao="todos", com_preco=filtros.com_preco,
        desconto_min_pct=obter_config(s).desconto_min_pct,
        situacao_produto=None if filtros.situacao == "todos" else filtros.situacao, ordem=filtros.ordem,
    )


def _produto_saida(produto: ProdutoLiga, preco: Decimal | None) -> dict:
    return {"id": produto.id, "nome": produto.nome, "imagem_chave": produto.imagem_chave, "preco_liga": preco}


@roteador.get("/casamentos")
def lista(
    request: Request, _c: RevisarCasamentos, filtros: Annotated[Filtros, Depends()],
    pagina: Annotated[int, Query(ge=1, le=10_000)] = 1,
) -> ListaCasamentosSaida:
    with request.app.state.sessoes() as s:
        linhas = _linhas(s, filtros)
        categorias = q.categorias_da_liga(s)
    pedaco = linhas[(pagina - 1) * POR_PAGINA : pagina * POR_PAGINA]
    itens = [
        {
            "id": l.produto.id, "nome": l.produto.nome, "nome_en": l.produto.nome_en,
            "imagem_chave": l.produto.imagem_chave, "categoria": l.produto.tipo, "preco_liga": l.preco_liga,
            "pendentes": l.pendentes, "confirmados": l.confirmados, "ignorados": l.ignorados,
            "em_outro": l.em_outro, "ia_sugere": l.ia_sugere, "situacao": l.situacao_produto,
        }
        for l in pedaco
    ]
    return ListaCasamentosSaida.model_validate({
        **com_imagens({"itens": itens}, base_imagens(request)),
        "total": len(linhas), "pagina": pagina, "por_pagina": POR_PAGINA, "categorias": categorias,
    })


def _anuncio(linha: q.LinhaAnuncio) -> dict:
    ia = linha.ia
    casado = linha.casado_com
    par = linha.casamento
    return {
        "anuncio_id": linha.anuncio.id, "asin": linha.anuncio.asin, "titulo": linha.anuncio.titulo_exibicao,
        "url": linha.anuncio.url, "imagem_chave": linha.anuncio.imagem_chave,
        "preco": linha.atual.preco if linha.atual else None,
        "vendedor": linha.vendedor.nome if linha.vendedor else None,
        "termos_variacao": termos_variacao(linha.anuncio.titulo_exibicao),
        "ia": None if ia is None else {
            "mesmo_produto": ia.mesmo_produto, "confianca": ia.confianca, "motivo": ia.motivo,
            "idioma": ia.idioma_anuncio or None,
        },
        "origem": par.origem.value if par is not None and par.origem is not None else None,
        "revisado_em": par.revisado_em if par is not None else None,
        "oportunidade": linha.oportunidade and (ia is None or ia.mesmo_produto),
        "casado_com": None if casado is None else _produto_saida(casado, None),
    }


@roteador.get("/casamentos/{produto_id}")
def revisao(
    request: Request, produto_id: int, _c: RevisarCasamentos, filtros: Annotated[Filtros, Depends()]
) -> RevisaoSaida:
    estado = request.app.state
    with estado.sessoes() as s:
        config = obter_config(s)
        detalhe = q.detalhe_casamento(s, produto_id, config, estado.relogio())
        if detalhe is None:
            raise ErroApi(404, "nao_encontrado", "Produto não está mais monitorado.")
        ids = [l.produto.id for l in _linhas(s, filtros)]
        parecidos = q.parecidos_na_liga(s, detalhe.produto)
        produto = detalhe.produto
        atual = s.get(PrecoAtualLiga, produto.id)
        lojas = atual.num_lojas if atual else None
        posicao = ids.index(produto_id) + 1 if produto_id in ids else 0
        saida = {
            "produto": {
                "id": produto.id, "nome": produto.nome, "nome_en": produto.nome_en,
                "imagem_chave": produto.imagem_chave, "categoria": produto.tipo, "url": produto.url,
                "preco_liga": detalhe.preco_liga, "lojas": lojas, "pistas": pistas_variacao(produto.nome),
            },
            "navegacao": {
                "posicao": posicao, "total": len(ids),
                "anterior": ids[posicao - 2] if posicao > 1 else None,
                "proximo": ids[posicao] if 0 < posicao < len(ids) else None,
            },
            "para_decidir": [_anuncio(l) for l in detalhe.pendentes],
            "confirmados": [_anuncio(l) for l in detalhe.confirmados],
            "ignorados": [_anuncio(l) for l in detalhe.ignorados],
            "parecidos": [_produto_saida(p, preco) for p, preco in parecidos],
            "termos": [t.termo for t in detalhe.termos],
            "termos_pedidos": detalhe.termos_pedidos_em is not None,
        }
    return RevisaoSaida.model_validate(com_imagens(saida, base_imagens(request)))
