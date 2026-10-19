"""Permissões do site: lista fechada no código; cada fase acrescenta as suas. O que cada papel pode é configurável
na grade papel × permissão (tabela `permissao_papel`, tela Gestão → Acessos); linha ausente vale o padrão daqui.
O admin tem sempre todas (linhas do admin no banco são ignoradas)."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Papel


class Permissao(StrEnum):
    VER_AREA_NEGOCIO = "ver_area_negocio"
    VER_AREA_GESTAO = "ver_area_gestao"
    GERIR_USUARIOS = "gerir_usuarios"
    GERIR_ACESSOS = "gerir_acessos"
    VER_DOCUMENTACAO_API = "ver_documentacao_api"


@dataclass(frozen=True)
class DefinicaoPermissao:
    rotulo: str
    descricao: str


DEFINICOES: dict[Permissao, DefinicaoPermissao] = {
    Permissao.VER_AREA_NEGOCIO: DefinicaoPermissao(
        "Entrar na área de negócio", "Ver a área de negócio (oportunidades e resultados do grupo)."
    ),
    Permissao.VER_AREA_GESTAO: DefinicaoPermissao(
        "Entrar na área de gestão", "Ver o menu e as telas da área administrativa."
    ),
    Permissao.GERIR_USUARIOS: DefinicaoPermissao(
        "Gerir usuários", "Listar, criar, editar e desativar usuários e encerrar sessões."
    ),
    Permissao.GERIR_ACESSOS: DefinicaoPermissao("Gerir acessos", "Editar esta grade de papel × permissão."),
    Permissao.VER_DOCUMENTACAO_API: DefinicaoPermissao(
        "Ver a documentação da API", "Abrir /api/docs (OpenAPI)."
    ),
}
ROTULOS_PAPEL = {Papel.GRUPO: "Grupo", Papel.OPERADOR: "Operador", Papel.ADMIN: "Admin"}
PAPEIS_EDITAVEIS = (Papel.GRUPO, Papel.OPERADOR)
PADROES: dict[Papel, frozenset[Permissao]] = {
    Papel.GRUPO: frozenset({Permissao.VER_AREA_NEGOCIO}),
    Papel.OPERADOR: frozenset({Permissao.VER_AREA_NEGOCIO, Permissao.VER_AREA_GESTAO}),
    Papel.ADMIN: frozenset(Permissao),
}
TTL_CACHE_S = 5.0


def calcular_grade(salvas: dict[tuple[Papel, str], bool]) -> dict[Papel, frozenset[Permissao]]:
    """Permissões efetivas de cada papel: linha salva ou, sem ela, o padrão. Admin: todas."""
    grade = {Papel.ADMIN: frozenset(Permissao)}
    for papel in PAPEIS_EDITAVEIS:
        grade[papel] = frozenset(p for p in Permissao if salvas.get((papel, p.value), p in PADROES[papel]))
    return grade


class GradePermissoes:
    """A grade lida do banco com cache curto (`ttl_s`); `invalidar()` depois de salvar faz a mudança valer na
    próxima requisição de quem já está logado."""

    def __init__(
        self,
        sessoes: sessionmaker[Session],
        ttl_s: float = TTL_CACHE_S,
        monotonico: Callable[[], float] = time.monotonic,
    ):
        self._sessoes = sessoes
        self._ttl_s = ttl_s
        self._monotonico = monotonico
        self._trava = threading.Lock()
        self._grade: dict[Papel, frozenset[Permissao]] | None = None
        self._lida_em = 0.0

    def grade(self) -> dict[Papel, frozenset[Permissao]]:
        with self._trava:
            agora = self._monotonico()
            if self._grade is None or agora - self._lida_em >= self._ttl_s:
                with self._sessoes() as s:
                    self._grade = calcular_grade(repo_acesso.grade_salva(s))
                self._lida_em = agora
            return self._grade

    def efetivas(self, papel: Papel) -> frozenset[Permissao]:
        return self.grade()[papel]

    def invalidar(self) -> None:
        with self._trava:
            self._grade = None
