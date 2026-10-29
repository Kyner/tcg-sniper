"""Gestão: o Dashboard (`/gestao`). Exige `ver_area_gestao`; cada bloco só vem com a permissão dele (senão `null`):
saúde dos serviços (`ver_servicos`), oportunidades (`ver_oportunidades`) e funil (`ver_catalogo`). O "Precisa de
você" mostra só os itens cuja tela de destino o usuário pode abrir."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from tcg_sniper.api.dependencias import Contexto, exige
from tcg_sniper.api.imagens import base_imagens, com_imagens
from tcg_sniper.api.permissoes import Permissao
from tcg_sniper.api.rotas_gestao_servicos import NOMES_TELA, ORDEM
from tcg_sniper.config_banco import carregar_config
from tcg_sniper.consultas import dashboard as q
from tcg_sniper.consultas import mensagens as consultas_mensagens
from tcg_sniper.consultas import painel
from tcg_sniper.consultas import servicos as consultas_servicos
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import COLETOR_NOTIFICADOR, EstadoColetorTipo
from tcg_sniper.gestao.servicos import Servico

roteador = APIRouter(prefix="/api/gestao", tags=["gestão"])
VerGestao = Annotated[Contexto, Depends(exige(Permissao.VER_AREA_GESTAO))]


class AcaoSaida(BaseModel):
    rotulo: str
    caminho: str


class PrecisaSaida(BaseModel):
    texto: str
    rotulo: str
    destino: str
    acao: AcaoSaida | None = None


class SaudeSaida(BaseModel):
    id: Servico
    nome: str
    estado: consultas_servicos.Estado
    resumo: str


class TopSaida(BaseModel):
    produto_id: int
    nome: str
    imagem: str | None
    desconto_pct: float


class OportunidadesSaida(BaseModel):
    top: list[TopSaida]
    abertas: int
    alertas_hoje: int
    alertas_semana: int


class FunilSaida(BaseModel):
    liga: int
    monitorados: int
    esperando_decisao: int
    so_ignorados: int
    sem_candidato: int
    casados_produtos: int
    casados_anuncios: int
    oportunidades: int


class DashboardSaida(BaseModel):
    precisa: list[PrecisaSaida]
    saude: list[SaudeSaida] | None
    oportunidades: OportunidadesSaida | None
    funil: FunilSaida | None


@roteador.get("/dashboard")
def dashboard(request: Request, contexto: VerGestao) -> DashboardSaida:
    estado = request.app.state
    efetiva = carregar_config(estado.sessoes, estado.config)
    chave_ia = bool((estado.config.openai_api_key or "").strip())
    agora = estado.relogio()
    pode = contexto.permissoes
    with estado.sessoes() as s, s.begin():  # obter_estado cria a linha do coletor que ainda não existe
        pausado = repo.obter_estado(s, agora, COLETOR_NOTIFICADOR).estado is not EstadoColetorTipo.ATIVO
        resumo = consultas_mensagens.resumo(s, agora, notificador_pausado=pausado)
        saudes = consultas_servicos.saude_por_servico(s, agora, efetiva, chave_ia, resumo)
        avisos = painel.avisos(s, agora, efetiva, [saudes[x] for x in ORDEM if x is not Servico.BACKUP], resumo)
        avisos += painel.avisos_backup(saudes[Servico.BACKUP])
        itens = [i for i in q.precisa(s, agora, efetiva, avisos) if q.pode_abrir(i, pode)]
        saude = None
        if Permissao.VER_SERVICOS in pode:
            saude = [
                SaudeSaida(
                    id=x, nome=NOMES_TELA[x], estado=consultas_servicos.estado_unico(saudes[x]), resumo=saudes[x].texto
                )
                for x in ORDEM
            ]
        oportunidades = funil = None
        if Permissao.VER_OPORTUNIDADES in pode or Permissao.VER_CATALOGO in pode:
            numeros = painel.numeros(s, agora, efetiva)
            if Permissao.VER_OPORTUNIDADES in pode:
                topo = [
                    {"produto_id": a.produto.id, "nome": a.produto.nome, "imagem_chave": a.produto.imagem_chave,
                     "desconto_pct": a.desconto_pct}
                    for a in q.top_oportunidades(s)
                ]
                oportunidades = OportunidadesSaida.model_validate({
                    "top": com_imagens(topo, base_imagens(request)),
                    "abertas": numeros.abertas, "alertas_hoje": numeros.alertas_hoje,
                    "alertas_semana": numeros.alertas_semana,
                })
            if Permissao.VER_CATALOGO in pode:
                funil = FunilSaida.model_validate(q.funil(s, agora, efetiva, numeros), from_attributes=True)
    return DashboardSaida(
        precisa=[
            PrecisaSaida(
                texto=i.texto, rotulo=q.rotulo_para(i, pode), destino=i.destino,
                acao=AcaoSaida(rotulo=i.acao.rotulo, caminho=i.acao.caminho) if i.acao else None,
            )
            for i in itens
        ],
        saude=saude, oportunidades=oportunidades, funil=funil,
    )
