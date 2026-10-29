"""Gestão: Configurações (grupos com o valor de cada campo, Efeito de cada grupo, salvar só os alterados) e
os avisos do WhatsApp (ligar/desligar). Ver exige `ver_area_gestao` e `ver_configuracoes`; salvar e
ligar/desligar aviso exigem `ver_area_gestao` e `editar_configuracoes`. Nenhum segredo do .env sai daqui:
da chave da OpenAI só o booleano "chave configurada". Toda gravação fica em `acao_gestao` (tipo
`configuracoes`), na mesma transação."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.orm import Session

from tcg_sniper.api.dependencias import Contexto, exige_todas
from tcg_sniper.api.erros import ErroApi
from tcg_sniper.api.permissoes import Permissao
from tcg_sniper.avisos import formato
from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import CATALOGO, TipoAviso
from tcg_sniper.config import Config
from tcg_sniper.configuracoes import grupos as cfg_grupos
from tcg_sniper.configuracoes import salvar as cfg_salvar
from tcg_sniper.configuracoes.efeito import efeito as calcular_efeito
from tcg_sniper.configuracoes.salvar import Valor, serializar
from tcg_sniper.db.models import TipoAcaoGestao
from tcg_sniper.db.repositorio_acao_gestao import registrar
from tcg_sniper.notificador.base import Destino

roteador = APIRouter(prefix="/api/gestao", tags=["gestão"])
VerConfiguracoes = Annotated[
    Contexto, Depends(exige_todas(Permissao.VER_AREA_GESTAO, Permissao.VER_CONFIGURACOES))
]
EditarConfiguracoes = Annotated[
    Contexto, Depends(exige_todas(Permissao.VER_AREA_GESTAO, Permissao.EDITAR_CONFIGURACOES))
]

ROTULOS_DESTINO = {
    Destino.ADMIN: "grupo admin",
    Destino.OPORTUNIDADES: "grupo oportunidades",
    Destino.INDIVIDUAL: "só para a pessoa",
}
ValorEntrada = str | int | float | bool | None | list[str | int]


class OpcaoSaida(BaseModel):
    valor: str
    rotulo: str


class CampoSaida(BaseModel):
    chave: str
    rotulo: str
    explicacao: str
    tipo: str
    padrao: Valor
    minimo: int | None
    maximo: int | None
    opcoes: list[OpcaoSaida]
    avancado: bool
    vinculo: str | None
    valor: Valor


class GrupoSaida(BaseModel):
    id: str
    titulo: str
    proposito: str
    tem_efeito: bool
    campos: list[CampoSaida]


class AvisoSaida(BaseModel):
    tipo: str
    titulo: str
    descricao: str
    area: str  # `origem` do catálogo (quem manda o aviso)
    destino: str
    agrupa: bool
    ligado: bool
    exemplo: str  # texto do WhatsApp, com a marcação dele


class IASaida(BaseModel):
    chave_configurada: bool


class ConfiguracoesSaida(BaseModel):
    grupos: list[GrupoSaida]
    versoes: dict[str, str]
    avisos: list[AvisoSaida]
    ia: IASaida


class BarraSaida(BaseModel):
    rotulo: str
    pct: int


class EfeitoSaida(BaseModel):
    linhas: list[str]
    nivel: str
    barras: list[BarraSaida]


class EfeitoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grupo: str
    valores: dict[str, ValorEntrada] = Field(default_factory=dict)


class SalvarEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    versoes: dict[str, str]
    valores: dict[str, ValorEntrada]


class AvisoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ligado: StrictBool


def _inteiro(valor) -> int | None:
    return None if valor is None else int(valor)


def _grupos(s: Session, config_env: Config) -> list[GrupoSaida]:
    atuais = cfg_grupos.valores_atuais(s, config_env)
    return [
        GrupoSaida(
            id=g.id,
            titulo=g.titulo,
            proposito=g.proposito,
            tem_efeito=g.tem_efeito,
            campos=[
                CampoSaida(
                    chave=c.chave,
                    rotulo=c.rotulo,
                    explicacao=c.explicacao,
                    tipo=c.tipo,
                    padrao=serializar(c.padrao),
                    minimo=_inteiro(c.minimo),
                    maximo=_inteiro(c.maximo),
                    opcoes=[OpcaoSaida(valor=v, rotulo=r) for v, r in c.opcoes],
                    avancado=c.avancado,
                    vinculo=c.vinculo,
                    valor=serializar(atuais[c.chave]),
                )
                for c in g.campos
            ],
        )
        for g in cfg_grupos.GRUPOS
    ]


def _aviso(tipo: TipoAviso, ligado: bool, agora: datetime, zona, host: str | None) -> AvisoSaida:
    """`host` vai para `formatar`, que recusa o endereço do sistema no texto (o exemplo nunca o leva)."""
    d = CATALOGO[tipo]
    return AvisoSaida(
        tipo=tipo.value,
        titulo=d.titulo,
        descricao=d.descricao,
        area=d.origem,
        destino=ROTULOS_DESTINO[d.grupo],
        agrupa=d.agrupa,
        ligado=ligado,
        exemplo=formato.formatar(formato.aviso_de(tipo, d.exemplo, agora), zona, host, estrito=False),
    )


def _corpo(s: Session, config_env: Config, agora: datetime) -> ConfiguracoesSaida:
    grupos = _grupos(s, config_env)  # cria as linhas que faltam antes de ler as versões
    zona, host = avisos.zona_e_host(s)
    estados = avisos.ligados(s)
    return ConfiguracoesSaida(
        grupos=grupos,
        versoes=cfg_grupos.versoes(s),
        avisos=[_aviso(tipo, estados[tipo], agora, zona, host) for tipo in CATALOGO],
        ia=IASaida(chave_configurada=bool((config_env.openai_api_key or "").strip())),
    )


@roteador.get("/configuracoes")
def ler(request: Request, contexto: VerConfiguracoes) -> ConfiguracoesSaida:
    estado = request.app.state
    with estado.sessoes() as s, s.begin():  # a primeira leitura cria as linhas de geral, liga e IA
        return _corpo(s, estado.config, estado.relogio())


@roteador.post("/configuracoes/efeito")
def efeito(request: Request, corpo: EfeitoEntrada, contexto: VerConfiguracoes) -> EfeitoSaida | None:
    try:
        grupo = cfg_grupos.grupo(corpo.grupo)
    except KeyError:
        raise ErroApi(404, "nao_encontrado", "Grupo de configurações não encontrado.") from None
    do_grupo = {c.chave for c in grupo.campos}
    fora = {chave: "Campo fora deste grupo." for chave in corpo.valores if chave not in do_grupo}
    if fora:
        raise ErroApi(422, "validacao", "Dados inválidos.", fora)
    estado = request.app.state
    with estado.sessoes() as s:  # só leitura
        resultado = calcular_efeito(s, estado.relogio(), grupo.id, corpo.valores)
    if resultado is None:
        return None
    return EfeitoSaida(
        linhas=list(resultado.linhas),
        nivel=resultado.nivel,
        barras=[BarraSaida(rotulo=r, pct=p) for r, p in resultado.barras],
    )


@roteador.put("/configuracoes")
def salvar(request: Request, corpo: SalvarEntrada, contexto: EditarConfiguracoes) -> ConfiguracoesSaida:
    estado = request.app.state
    agora = estado.relogio()
    with estado.sessoes() as s, s.begin():
        try:
            mudancas = cfg_salvar.salvar(s, estado.config, corpo.versoes, corpo.valores, agora)
        except cfg_salvar.CamposInvalidos as erro:
            raise ErroApi(422, "validacao", "Confira os campos marcados.", erro.erros) from None
        except cfg_salvar.ConfigMudou:
            raise ErroApi(
                409, "config_mudou", "As configurações mudaram desde que você abriu a tela; recarregue."
            ) from None
        if mudancas:
            registrar(s, contexto.usuario_id, TipoAcaoGestao.CONFIGURACOES, {"campos": mudancas}, agora)
        return _corpo(s, estado.config, agora)


@roteador.patch("/avisos/{tipo}")
def ligar_aviso(request: Request, tipo: str, corpo: AvisoEntrada, contexto: EditarConfiguracoes) -> AvisoSaida:
    try:
        tipo_aviso = TipoAviso(tipo)
    except ValueError:
        raise ErroApi(404, "nao_encontrado", "Aviso não encontrado.") from None
    estado = request.app.state
    agora = estado.relogio()
    with estado.sessoes() as s, s.begin():
        avisos.definir_ligado(s, tipo_aviso, corpo.ligado)
        registrar(
            s, contexto.usuario_id, TipoAcaoGestao.CONFIGURACOES, {"aviso": tipo_aviso.value, "ligado": corpo.ligado},
            agora,
        )
        zona, host = avisos.zona_e_host(s)
        return _aviso(tipo_aviso, corpo.ligado, agora, zona, host)
