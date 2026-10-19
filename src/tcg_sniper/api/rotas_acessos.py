"""Gestão → Acessos: a grade papel × permissão. GET lê, PUT grava (exige `gerir_acessos`); o admin é travado."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from tcg_sniper.api import avisos_acesso
from tcg_sniper.api.dependencias import Contexto, exige
from tcg_sniper.api.erros import ErroApi
from tcg_sniper.api.permissoes import DEFINICOES, ROTULOS_PAPEL, Permissao, calcular_grade
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Papel

roteador = APIRouter(prefix="/api/acessos", tags=["acessos"])
GerirAcessos = Annotated[Contexto, Depends(exige(Permissao.GERIR_ACESSOS))]


class Mudanca(BaseModel):
    model_config = ConfigDict(extra="forbid")
    papel: Papel
    permissao: Permissao
    permitido: bool


class MudancasEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mudancas: list[Mudanca] = Field(min_length=1, max_length=100)


class PapelSaida(BaseModel):
    papel: Papel
    rotulo: str
    editavel: bool


class LinhaPermissao(BaseModel):
    permissao: Permissao
    rotulo: str
    descricao: str
    valores: dict[Papel, bool]


class GradeSaida(BaseModel):
    papeis: list[PapelSaida]
    permissoes: list[LinhaPermissao]


def montar_grade(grade: dict[Papel, frozenset[Permissao]]) -> GradeSaida:
    return GradeSaida(
        papeis=[PapelSaida(papel=p, rotulo=ROTULOS_PAPEL[p], editavel=p is not Papel.ADMIN) for p in Papel],
        permissoes=[
            LinhaPermissao(
                permissao=permissao,
                rotulo=DEFINICOES[permissao].rotulo,
                descricao=DEFINICOES[permissao].descricao,
                valores={papel: permissao in grade[papel] for papel in Papel},
            )
            for permissao in Permissao
        ],
    )


def aplicar_mudancas(s: Session, atual: dict[Papel, frozenset[Permissao]], mudancas: list[Mudanca]) -> list[Mudanca]:
    """Grava as mudanças que trocam o valor efetivo e devolve só essas (as iguais ao atual não gravam nem avisam)."""
    feitas = []
    for mudanca in mudancas:
        if (mudanca.permissao in atual[mudanca.papel]) == mudanca.permitido:
            continue
        repo_acesso.salvar_permissao(s, mudanca.papel, mudanca.permissao.value, mudanca.permitido)
        feitas.append(mudanca)
    return feitas


@roteador.get("")
def ler(request: Request, _contexto: GerirAcessos) -> GradeSaida:
    return montar_grade(request.app.state.grade.grade())


@roteador.put("")
def salvar(request: Request, entrada: MudancasEntrada, contexto: GerirAcessos) -> GradeSaida:
    if any(m.papel is Papel.ADMIN for m in entrada.mudancas):
        raise ErroApi(422, "papel_travado", "O admin tem sempre todas as permissões.")
    estado = request.app.state
    with estado.sessoes() as s, s.begin():
        agora = estado.relogio()
        for m in aplicar_mudancas(s, calcular_grade(repo_acesso.grade_salva(s)), entrada.mudancas):
            avisos_acesso.permissao_alterada(s, m.papel, m.permissao, m.permitido, contexto.nome, agora)
    estado.grade.invalidar()
    return montar_grade(estado.grade.grade())
