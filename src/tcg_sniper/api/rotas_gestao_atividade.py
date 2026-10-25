"""Gestão: a Atividade (registros dos serviços e mensagens numa lista só) e as ações de reenviar e descartar uma
mensagem. Ver exige `ver_area_gestao` e `ver_logs`; sem `ver_mensagens` o texto das mensagens sai vazio. Reenviar e
descartar exigem `ver_area_gestao` e `reenviar_mensagens`. Essas ações não vão para `acao_gestao`: a spec lista ali só
o lote do catálogo, ligar/desligar serviço e salvar configurações (o admin antigo também não registrava).

`de` e `ate` são datas e horas ISO **com fuso** (ex.: `2026-10-13T10:00:00-03:00`); sem fuso é 422, para não
adivinhar a zona de quem pergunta."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AfterValidator, BaseModel, ConfigDict

from tcg_sniper.api.dependencias import Contexto, exige_todas
from tcg_sniper.api.erros import ErroApi
from tcg_sniper.api.permissoes import Permissao
from tcg_sniper.consultas import atividade as q
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.gestao.servicos import Servico

roteador = APIRouter(prefix="/api/gestao", tags=["gestão"])
VerAtividade = Annotated[Contexto, Depends(exige_todas(Permissao.VER_AREA_GESTAO, Permissao.VER_LOGS))]
ReenviarMensagens = Annotated[Contexto, Depends(exige_todas(Permissao.VER_AREA_GESTAO, Permissao.REENVIAR_MENSAGENS))]


def _com_fuso(valor: datetime | None) -> datetime | None:
    if valor is not None and valor.tzinfo is None:
        raise ValueError("a data precisa ter fuso")
    return valor


ComFuso = Annotated[datetime | None, AfterValidator(_com_fuso)]


class LinhaAtividadeSaida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chave: str
    em: datetime
    servico: Servico | None
    o_que: q.OQue
    situacao: q.Situacao
    resultado: str
    produto_id: int | None
    produto: str | None
    asin: str | None
    custo_usd: Decimal | None
    detalhe: q.Detalhe


class PaginaAtividadeSaida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    itens: list[LinhaAtividadeSaida]
    proximo: str | None


class StatusMensagemSaida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str


def _sem_texto(linha: q.LinhaAtividade) -> q.LinhaAtividade:
    """Tira o texto da mensagem: do detalhe e do fim do `resultado` ("status · destino · primeira linha")."""
    if linha.o_que != "mensagem":
        return linha
    resultado = " · ".join(linha.resultado.split(" · ")[:2])
    return q.LinhaAtividade(**{**linha.__dict__, "resultado": resultado, "detalhe": {**linha.detalhe, "texto": None}})


@roteador.get("/atividade")
def listar(
    request: Request,
    contexto: VerAtividade,
    servico: Servico | None = None,
    o_que: q.OQue | None = None,
    situacao: q.FiltroSituacao | None = None,
    de: ComFuso = None,
    ate: ComFuso = None,
    busca: Annotated[str | None, Query(max_length=100)] = None,
    reinicios: bool = False,
    cursor: Annotated[str | None, Query(max_length=300)] = None,
) -> PaginaAtividadeSaida:
    filtro = q.FiltroAtividade(servico, o_que, situacao, de, ate, busca, mostrar_reinicios=reinicios)
    try:
        with request.app.state.sessoes() as s:
            linhas, proximo = q.linha_do_tempo(s, filtro, cursor)
    except ValueError:
        raise ErroApi(422, "validacao", "Dados inválidos: cursor.") from None
    if Permissao.VER_MENSAGENS not in contexto.permissoes:
        linhas = [_sem_texto(linha) for linha in linhas]
    return PaginaAtividadeSaida(
        itens=[LinhaAtividadeSaida(**linha.__dict__) for linha in linhas], proximo=proximo
    )


ID_MAXIMO = 2**31 - 1  # o integer do Postgres; fora de 1..ID_MAXIMO é 404, como no admin antigo


def _agir(request: Request, id_: int, acao: Literal["reenviar", "descartar"]) -> StatusMensagemSaida:
    if not 1 <= id_ <= ID_MAXIMO:
        raise ErroApi(404, "nao_encontrado", "Mensagem não encontrada.")
    estado = request.app.state
    funcao = repo_msg.reenviar if acao == "reenviar" else repo_msg.descartar
    try:
        with estado.sessoes() as s, s.begin():
            funcao(s, id_, estado.relogio())
            return StatusMensagemSaida(status=s.get(repo_msg.MensagemSaida, id_).status.value)
    except repo_msg.MensagemNaoEncontrada:
        raise ErroApi(404, "nao_encontrado", "Mensagem não encontrada.") from None
    except repo_msg.AcaoInvalida as erro:
        raise ErroApi(409, "acao_invalida", str(erro)) from None


@roteador.post("/mensagens/{id_}/reenviar")
def reenviar(request: Request, id_: int, contexto: ReenviarMensagens) -> StatusMensagemSaida:
    return _agir(request, id_, "reenviar")


@roteador.post("/mensagens/{id_}/descartar")
def descartar(request: Request, id_: int, contexto: ReenviarMensagens) -> StatusMensagemSaida:
    return _agir(request, id_, "descartar")
