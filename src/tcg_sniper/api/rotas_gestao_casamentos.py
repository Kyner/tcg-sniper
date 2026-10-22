"""Gestão: revisão dos casamentos (anúncio da Amazon × produto da Liga): leitura e ações. Exige `ver_area_gestao`
e `revisar_casamentos`."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, model_validator

from tcg_sniper.api.dependencias import Contexto, exige, exige_todas
from tcg_sniper.api.erros import ErroApi
from tcg_sniper.api.imagens import base_imagens, com_imagens
from tcg_sniper.api.permissoes import Permissao
from tcg_sniper.coletor_amazon.asin import LinkInvalido, extrair_asin
from tcg_sniper.consultas import casamentos as q
from tcg_sniper.consultas.variacao import pistas_variacao, termos_variacao
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db import repositorio_termos as repo_termos
from tcg_sniper.db.models import COLETOR_CASADOR, AnuncioAmazon, OrigemCasamento, PrecoAtualLiga, ProdutoLiga
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


class MenuSaida(BaseModel):
    casamentos_esperando: int


@roteador.get("/menu")
def menu(request: Request, contexto: Annotated[Contexto, Depends(exige(Permissao.VER_AREA_GESTAO))]) -> MenuSaida:
    """O selo do menu da gestão: produtos esperando decisão (0 para quem não revisa casamentos)."""
    if Permissao.REVISAR_CASAMENTOS not in contexto.permissoes:
        return MenuSaida(casamentos_esperando=0)
    with request.app.state.sessoes() as s:
        return MenuSaida(casamentos_esperando=len(_linhas(s, Filtros())))


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


class DecisaoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acao: Literal["confirmar", "ignorar", "desfazer", "trocar"]
    para_produto_id: int | None = None

    @model_validator(mode="after")
    def _trocar_pede_o_destino(self):
        if self.acao == "trocar" and self.para_produto_id is None:
            raise ValueError("para_produto_id é obrigatório em trocar")
        return self


class DecisaoSaida(BaseModel):
    anuncio: AnuncioRevisaoSaida
    grupo: Literal["para_decidir", "confirmados", "ignorados"]
    mensagem: str | None = None


class LinkEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    link: str


class MensagemSaida(BaseModel):
    tipo: Literal["success", "info", "warning"]
    mensagem: str


# Os tipos de MENSAGENS_CASAMENTO (herdados do admin antigo) para os da API.
_TIPO_DA_MENSAGEM = {"success": "success", "info": "info", "warning": "warning", "error": "warning"}


def _produto_ativo_ou_404(s, produto_id: int) -> ProdutoLiga:
    produto = s.get(ProdutoLiga, produto_id)
    if produto is None or not produto.ativo:
        raise ErroApi(404, "nao_encontrado", "Produto não está mais monitorado.")
    return produto


def _mensagem(chave: str) -> MensagemSaida:
    tipo, texto = q.MENSAGENS_CASAMENTO[chave]
    return MensagemSaida(tipo=_TIPO_DA_MENSAGEM[tipo], mensagem=texto)


def _anuncio_agora(request: Request, s, produto_id: int, anuncio_id: int) -> tuple[AnuncioRevisaoSaida, str]:
    """O anúncio como está agora na tela do produto, e em que grupo."""
    estado = request.app.state
    detalhe = q.detalhe_casamento(s, produto_id, obter_config(s), estado.relogio())
    if detalhe is not None:
        grupos = (
            ("para_decidir", detalhe.pendentes), ("confirmados", detalhe.confirmados), ("ignorados", detalhe.ignorados)
        )
        for grupo, linhas in grupos:
            for linha in linhas:
                if linha.anuncio.id == anuncio_id:
                    saida = AnuncioRevisaoSaida.model_validate(com_imagens(_anuncio(linha), base_imagens(request)))
                    return saida, grupo
    raise ErroApi(404, "nao_encontrado", "Anúncio não está mais nesta revisão.")


@roteador.post("/casamentos/{produto_id}/anuncios/{anuncio_id}")
def decidir(
    request: Request, produto_id: int, anuncio_id: int, entrada: DecisaoEntrada, _c: RevisarCasamentos
) -> DecisaoSaida:
    estado = request.app.state
    acao, para = entrada.acao, entrada.para_produto_id
    with estado.sessoes() as s, s.begin():
        agora = estado.relogio()
        if s.get(AnuncioAmazon, anuncio_id) is None:
            raise ErroApi(404, "nao_encontrado", "Anúncio não encontrado.")
        _produto_ativo_ou_404(s, produto_id)
        if acao == "trocar":
            _produto_ativo_ou_404(s, para)
        if acao != "confirmar" and repo_casamento.obter_par(s, anuncio_id, produto_id) is None:
            raise ErroApi(404, "nao_encontrado", "Este anúncio não está na revisão deste produto.")
        origem = repo_ia.origem_da_decisao(s, anuncio_id, para if acao == "trocar" else produto_id)
        try:
            if acao == "confirmar":
                repo_casamento.confirmar(s, anuncio_id, produto_id, agora, origem)
            elif acao == "trocar":
                repo_casamento.trocar(s, anuncio_id, para, agora, origem)
                if para != produto_id:
                    # "É de outro produto": não é o produto de onde você veio (decisão sua sobre o par).
                    repo_casamento.ignorar(s, anuncio_id, produto_id, agora, OrigemCasamento.MANUAL)
            elif acao == "ignorar":
                repo_casamento.ignorar(s, anuncio_id, produto_id, agora, origem)
            else:
                repo_casamento.desfazer(s, anuncio_id, produto_id, agora)
        except repo_casamento.JaConfirmado as erro:
            confirmado = s.get(ProdutoLiga, erro.produto_id)
            nome = confirmado.nome if confirmado is not None else "outro produto"
            raise ErroApi(409, "ja_confirmado", f"Este anúncio já está confirmado em {nome}.") from None
        anuncio, grupo = _anuncio_agora(request, s, produto_id, anuncio_id)
    return DecisaoSaida(anuncio=anuncio, grupo=grupo)


@roteador.get("/casamentos/anuncios/{anuncio_id}/produtos")
def produtos_para_trocar(
    request: Request, anuncio_id: int, _c: RevisarCasamentos, busca: str = "", de: int | None = None
) -> list[ParecidoSaida]:
    with request.app.state.sessoes() as s:
        anuncio = s.get(AnuncioAmazon, anuncio_id)
        if anuncio is None:
            raise ErroApi(404, "nao_encontrado", "Anúncio não encontrado.")
        confirmado = repo_casamento.confirmado_do_anuncio(s, anuncio_id)
        excluir = {i for i in (de, confirmado.produto_id if confirmado else None) if i is not None}
        if busca.strip():
            achados = q.buscar_produtos(s, busca, excluir=excluir)
        else:
            achados = q.sugestoes_para(s, anuncio, excluir=excluir)
        itens = [_produto_saida(p, preco) for p, preco in achados]
    return [ParecidoSaida.model_validate(i) for i in com_imagens(itens, base_imagens(request))]


@roteador.post("/casamentos/{produto_id}/link")
def casar_link(request: Request, produto_id: int, entrada: LinkEntrada, _c: RevisarCasamentos) -> AnuncioRevisaoSaida:
    estado = request.app.state
    with estado.sessoes() as s, s.begin():
        _produto_ativo_ou_404(s, produto_id)
        try:
            asin = extrair_asin(entrada.link)
        except LinkInvalido as erro:
            raise ErroApi(400, "link_invalido", str(erro)) from None
        anuncio = repo_amz.casar_link_manual(s, produto_id, asin, estado.relogio())
        saida, _grupo = _anuncio_agora(request, s, produto_id, anuncio.id)
    return saida


@roteador.post("/casamentos/{produto_id}/rebuscar")
def rebuscar(request: Request, produto_id: int, _c: RevisarCasamentos) -> MensagemSaida:
    estado = request.app.state
    with estado.sessoes() as s, s.begin():
        _produto_ativo_ou_404(s, produto_id)
        na_fila = repo_amz.priorizar_na_fila(s, produto_id, estado.relogio())
    return _mensagem("rebuscar" if na_fila else "rebuscar_fora_da_fila")


@roteador.post("/casamentos/{produto_id}/reavaliar")
def reavaliar(request: Request, produto_id: int, _c: RevisarCasamentos) -> MensagemSaida:
    estado = request.app.state
    with estado.sessoes() as s, s.begin():
        agora = estado.relogio()
        _produto_ativo_ou_404(s, produto_id)
        marcados = repo_casamento.reavaliar_produto(s, produto_id, agora)
        if marcados:
            repo.solicitar_execucao(s, agora, COLETOR_CASADOR)
        parado = q.casador_parado(s, agora, estado.config)
    if not marcados:
        return _mensagem("reavaliar_nada")
    return _mensagem(f"reavaliar_{parado}" if parado else "reavaliar")


@roteador.post("/casamentos/{produto_id}/termos")
def gerar_termos(request: Request, produto_id: int, _c: RevisarCasamentos) -> MensagemSaida:
    estado = request.app.state
    with estado.sessoes() as s, s.begin():
        agora = estado.relogio()
        _produto_ativo_ou_404(s, produto_id)
        casado = repo_casamento.produto_casado(s, produto_id)
        pedido = not casado and repo_termos.pedir_termos(s, produto_id, agora)
        if pedido:
            repo.solicitar_execucao(s, agora, COLETOR_CASADOR)
        parado = q.casador_parado(s, agora, estado.config)
    if casado:
        return _mensagem("termos_ja_casado")
    if not pedido:
        return _mensagem("termos_fora_da_fila")
    return _mensagem(f"termos_{parado}" if parado else "termos_pedidos")
