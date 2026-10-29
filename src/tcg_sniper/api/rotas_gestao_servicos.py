"""Gestão: os seis serviços (estado, transição, ações) e as ações de ligar, desligar, retomar e rodar agora, mais as
chaves do monitor e do checkout da Amazon e o "Já conferi" do carrinho. Ver exige `ver_area_gestao` e `ver_servicos`;
agir exige `ver_area_gestao` e `pausar_servicos`. Toda ação fica em `acao_gestao` (tipo `servico`), na mesma transação
da ação, e usa as mesmas funções (e os mesmos avisos) do admin antigo."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from tcg_sniper.api.dependencias import Contexto, exige_todas
from tcg_sniper.api.erros import ErroApi
from tcg_sniper.api.permissoes import Permissao
from tcg_sniper.api.rotas_usuarios import MAX_ID  # integer do Postgres; fora de 1..MAX_ID é 404, como no admin antigo
from tcg_sniper.avisos.servico import zona_e_host
from tcg_sniper.coletor_liga.agendador import TIPOS_LIGA
from tcg_sniper.config_banco import carregar_config
from tcg_sniper.consultas import historico
from tcg_sniper.consultas import mensagens as consultas_mensagens
from tcg_sniper.consultas import servicos as q
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_manutencao as repo_man
from tcg_sniper.db.models import (
    COLETOR_NOTIFICADOR,
    AnuncioAmazon,
    EstadoColetorTipo,
    TipoAcaoGestao,
    TipoColeta,
)
from tcg_sniper.db.repositorio_acao_gestao import registrar
from tcg_sniper.gestao import servicos as acoes
from tcg_sniper.gestao.servicos import Servico

roteador = APIRouter(prefix="/api/gestao", tags=["gestão"])
VerServicos = Annotated[Contexto, Depends(exige_todas(Permissao.VER_AREA_GESTAO, Permissao.VER_SERVICOS))]
PausarServicos = Annotated[Contexto, Depends(exige_todas(Permissao.VER_AREA_GESTAO, Permissao.PAUSAR_SERVICOS))]

ORDEM = (
    Servico.LIGA, Servico.AMAZON_BUSCA, Servico.AMAZON_MONITOR, Servico.CASADOR, Servico.WHATSAPP, Servico.BACKUP,
)
NOMES_TELA = {
    Servico.LIGA: "LigaMagic",
    Servico.AMAZON_BUSCA: "Amazon · busca",
    Servico.AMAZON_MONITOR: "Amazon · monitor",
    Servico.CASADOR: "Casador (IA)",
    Servico.WHATSAPP: "WhatsApp",
    Servico.BACKUP: "Backup",
}
# Porta do noVNC de cada navegador (o endereço usa o host público das Configurações). O WhatsApp (Evolution) é fixo.
PORTA_VNC = {Servico.LIGA: 6080, Servico.AMAZON_MONITOR: 6081, Servico.AMAZON_BUSCA: 6082}
URL_WHATSAPP = "http://127.0.0.1:8080/manager"
COM_DESAFIO = (Servico.LIGA, Servico.AMAZON_BUSCA, Servico.AMAZON_MONITOR)
Acao = Literal["ligar", "desligar", "rodar_agora", "retomar"]
ACOES_URL = {"ligar": "ligar", "desligar": "desligar", "rodar-agora": "rodar_agora", "retomar": "retomar"}


class TransicaoSaida(BaseModel):
    tipo: Literal["parando", "parado", "iniciando"]
    desde: datetime | None


class ItemCarrinho(BaseModel):
    conferencia_id: int
    asin: str
    produto: str
    em: datetime | None  # desde quando espera conferência à mão


class SubMonitor(BaseModel):
    monitor_ligado: bool
    checkout_ligado: bool
    checkout_parado: bool  # conta sem login: o checkout espera o "Retomar"
    carrinho: list[ItemCarrinho]


class ServicoSaida(BaseModel):
    id: Servico
    nome: str
    estado: q.Estado
    agora: str  # texto curto da saúde, para a linha
    detalhe: str  # texto completo, para o tooltip
    ultimo_ok: datetime | None
    ligado: bool
    transicao: TransicaoSaida | None
    acoes: list[Acao]
    abrir: str | None
    atividade: str  # query da tela Atividade
    sub: SubMonitor | None


class ListaServicosSaida(BaseModel):
    servicos: list[ServicoSaida]


class ResultadoSaida(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codigo: str
    mensagem: str


def _ultimo_ok(s, servico: Servico) -> datetime | None:
    """Último sucesso do serviço: Liga e busca, a última coleta ok/parcial; backup, o último backup ok. Nos demais
    (monitor, casador, WhatsApp) não há "ok" próprio, então vale o último registro que o serviço deixou."""
    if servico in (Servico.LIGA, Servico.AMAZON_BUSCA):
        tipos = TIPOS_LIGA if servico is Servico.LIGA else (TipoColeta.AMAZON,)
        coleta = historico.ultima_coleta_sucesso(s, tipos)
        return None if coleta is None else coleta.finalizada_em or coleta.iniciada_em
    if servico is Servico.BACKUP:
        execucao = repo_man.ultima_ok(s)
        return None if execucao is None else execucao.fim or execucao.inicio
    return q.ultimo_registro(s, servico)


def _acoes_validas(servico: Servico, estado: EstadoColetorTipo) -> list[Acao]:
    if estado is EstadoColetorTipo.PAUSADO:
        return ["ligar"]
    if estado is EstadoColetorTipo.PAUSADO_DESAFIO:
        return ["retomar"] if servico in COM_DESAFIO else []
    acoes_ = ["desligar"]
    if servico in (Servico.LIGA, Servico.CASADOR):
        acoes_.append("rodar_agora")
    return acoes_


def _abrir(servico: Servico, host: str | None) -> str | None:
    if servico is Servico.WHATSAPP:
        return URL_WHATSAPP
    if servico in PORTA_VNC:
        return f"http://{host or 'localhost'}:{PORTA_VNC[servico]}/vnc.html"
    return None


def _sub(s) -> SubMonitor:
    cfg = repo_amz.obter_config(s)
    carrinho = []
    for conferencia, asin in repo_amz.conferencias_a_conferir_a_mao(s):
        anuncio = s.get(AnuncioAmazon, conferencia.anuncio_id)
        carrinho.append(
            ItemCarrinho(
                conferencia_id=conferencia.id,
                asin=asin,
                produto=anuncio.titulo_exibicao if anuncio is not None else asin,
                em=conferencia.conferir_a_mao_em,
            )
        )
    return SubMonitor(
        monitor_ligado=cfg.monitor_ligado,
        checkout_ligado=cfg.checkout_ligado,
        checkout_parado=cfg.checkout_sem_login_em is not None,
        carrinho=carrinho,
    )


@roteador.get("/servicos")
def listar(request: Request, contexto: VerServicos) -> ListaServicosSaida:
    estado = request.app.state
    efetiva = carregar_config(estado.sessoes, estado.config)
    chave_ia = bool((estado.config.openai_api_key or "").strip())
    pode_agir = Permissao.PAUSAR_SERVICOS in contexto.permissoes
    agora = estado.relogio()
    with estado.sessoes() as s, s.begin():  # obter_estado cria a linha do coletor que ainda não existe
        pausado = repo.obter_estado(s, agora, COLETOR_NOTIFICADOR).estado is not EstadoColetorTipo.ATIVO
        resumo = consultas_mensagens.resumo(s, agora, notificador_pausado=pausado)
        saudes = q.saude_por_servico(s, agora, efetiva, chave_ia, resumo)
        _, host = zona_e_host(s)  # host público das Configurações (regra: só avisos/ e admin/ leem o campo)
        saida = []
        for servico in ORDEM:
            saude = saudes[servico]
            coletor = repo.obter_estado(s, agora, acoes.COLETOR[servico])
            transicao = q.transicao(s, servico, coletor, agora)
            saida.append(
                ServicoSaida(
                    id=servico,
                    nome=NOMES_TELA[servico],
                    estado=q.estado_unico(saude),
                    agora=saude.texto,
                    detalhe=saude.detalhe,
                    ultimo_ok=_ultimo_ok(s, servico),
                    # Desafio pendente não é desligado por quem manda: a chave segue ligada até o Retomar.
                    ligado=coletor.estado is not EstadoColetorTipo.PAUSADO,
                    transicao=None if transicao is None else TransicaoSaida(tipo=transicao.tipo, desde=transicao.desde),
                    acoes=_acoes_validas(servico, coletor.estado) if pode_agir else [],
                    abrir=_abrir(servico, host) if pode_agir else None,
                    atividade=f"servico={servico.value}",
                    sub=_sub(s) if servico is Servico.AMAZON_MONITOR else None,
                )
            )
    return ListaServicosSaida(servicos=saida)


def _concluir(s, contexto: Contexto, servico: str, acao: str, codigo: str, agora: datetime) -> ResultadoSaida:
    registrar(s, contexto.usuario_id, TipoAcaoGestao.SERVICO, {"servico": servico, "acao": acao, "codigo": codigo}, agora)
    return ResultadoSaida(codigo=codigo, mensagem=acoes.MENSAGENS[codigo])


def _nao_encontrado() -> ErroApi:
    return ErroApi(404, "nao_encontrado", "Serviço ou ação não encontrado.")


def _servico_de(id_: str) -> Servico:
    try:
        return Servico(id_)
    except ValueError:
        raise _nao_encontrado() from None


# Rotas de 4 segmentos; nenhuma colide com `/{id_}/{acao}` (3).
@roteador.post("/servicos/amazon_monitor/checkout/retomar")
def retomar_checkout(request: Request, contexto: PausarServicos) -> ResultadoSaida:
    estado = request.app.state
    agora = estado.relogio()
    with estado.sessoes() as s, s.begin():
        codigo = acoes.retomar_checkout(s, agora)
        return _concluir(s, contexto, Servico.AMAZON_MONITOR.value, "checkout_retomar", codigo, agora)


@roteador.post("/servicos/amazon_monitor/{chave}/{acao}")
def ajustar_amazon(request: Request, chave: str, acao: str, contexto: PausarServicos) -> ResultadoSaida:
    campos = {"monitor": "monitor_ligado", "checkout": "checkout_ligado"}
    if chave not in campos or acao not in ("ligar", "desligar"):
        raise _nao_encontrado()
    estado = request.app.state
    agora = estado.relogio()
    with estado.sessoes() as s, s.begin():
        codigo = acoes.ajustar_amazon(s, campos[chave], acao == "ligar", agora)  # type: ignore[arg-type]
        return _concluir(s, contexto, Servico.AMAZON_MONITOR.value, codigo, codigo, agora)


@roteador.post("/servicos/carrinho/{conferencia_id}/conferido")
def carrinho_conferido(request: Request, conferencia_id: int, contexto: PausarServicos) -> ResultadoSaida:
    estado = request.app.state
    agora = estado.relogio()
    if not 1 <= conferencia_id <= MAX_ID:
        raise ErroApi(404, "nao_encontrado", "Esse item não está esperando conferência.")
    with estado.sessoes() as s, s.begin():
        if not acoes.carrinho_conferido(s, conferencia_id, agora):
            raise ErroApi(404, "nao_encontrado", "Esse item não está esperando conferência.")
        return _concluir(
            s, contexto, Servico.AMAZON_MONITOR.value, "carrinho_conferido", "carrinho_conferido", agora
        )


@roteador.post("/servicos/{id_}/{acao}")
def agir(request: Request, id_: str, acao: str, contexto: PausarServicos) -> ResultadoSaida:
    servico = _servico_de(id_)
    if acao not in ACOES_URL:
        raise _nao_encontrado()
    nome = ACOES_URL[acao]
    if (nome == "rodar_agora" and servico not in (Servico.LIGA, Servico.CASADOR)) or (
        nome == "retomar" and servico not in COM_DESAFIO
    ):
        raise _nao_encontrado()
    estado = request.app.state
    efetiva = carregar_config(estado.sessoes, estado.config)
    agora = estado.relogio()
    with estado.sessoes() as s, s.begin():
        if nome == "ligar":
            codigo = acoes.ligar(s, servico, agora)
        elif nome == "desligar":
            codigo = acoes.desligar(s, servico, agora)
        elif nome == "retomar":
            codigo = acoes.retomar_desafio(s, servico, efetiva.zona, efetiva, agora)
        else:
            codigo = acoes.rodar_agora(s, servico, efetiva.zona, efetiva, agora)
        return _concluir(s, contexto, servico.value, nome, codigo, agora)
