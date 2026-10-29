"""Salvar Configurações a partir dos campos alterados (`"<tabela>.<campo>"` → valor). Cada tabela tocada é
validada com o formulário inteiro dela (os salvos, em texto como no admin antigo, com os alterados por cima),
para as regras cruzadas (quase lá < desconto, janelas, pausas) rodarem como hoje. Tudo é validado antes de
gravar qualquer coisa; a versão (`atualizado_em`) de cada tabela tocada é conferida com a linha travada."""

from collections.abc import Callable, Mapping
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcg_sniper.coletor_amazon.config import CAMPOS as CAMPOS_AMAZON
from tcg_sniper.coletor_amazon.config import aplicar_config, validar_config
from tcg_sniper.config import Config
from tcg_sniper.configuracoes.geral_liga import CAMPOS_GERAL, CAMPOS_LIGA, validar_geral, validar_liga
from tcg_sniper.configuracoes.grupos import GRUPOS
from tcg_sniper.configuracoes.ia import CAMPOS_IA, texto_ia, validar_ia
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import ConfigAmazon, ConfigGeral, ConfigIA, ConfigLiga

Valor = str | int | float | bool | None
Validador = Callable[[Mapping[str, str]], tuple[dict[str, object], dict[str, str]]]

CHAVES = frozenset(c.chave for g in GRUPOS for c in g.campos)
MODELOS = {"geral": ConfigGeral, "liga": ConfigLiga, "amazon": ConfigAmazon, "ia": ConfigIA}
_FORMULARIO: dict[str, tuple[tuple[str, ...], Validador]] = {
    "geral": (CAMPOS_GERAL, validar_geral),
    "liga": (CAMPOS_LIGA, validar_liga),
    "amazon": (CAMPOS_AMAZON, validar_config),
    "ia": (CAMPOS_IA, validar_ia),
}
_GRAVAR: dict[str, Callable[[Session, Mapping[str, object], datetime], None]] = {
    "geral": repo.salvar_config_geral,
    "liga": repo.salvar_config_liga,
    "amazon": aplicar_config,
    "ia": repo_ia.salvar_config_ia,
}


class CamposInvalidos(Exception):
    def __init__(self, erros: dict[str, str]):
        super().__init__("campos inválidos")
        self.erros = erros


class ConfigMudou(Exception):
    """Alguém salvou uma das tabelas tocadas depois da leitura de quem salva agora."""


def serializar(valor: object) -> Valor:
    """Valor nativo para JSON: hora em HH:MM, Decimal em texto (sem zeros à direita)."""
    if isinstance(valor, time):
        return valor.strftime("%H:%M")
    if isinstance(valor, Decimal):
        return format(valor.normalize(), "f")
    return valor  # type: ignore[return-value]


def _texto_salvo(linha, tabela: str, nome: str) -> str:
    """Valor salvo como o admin antigo o põe no formulário."""
    if tabela == "ia":
        return texto_ia(linha, nome)
    valor = getattr(linha, nome)
    if valor is None:
        return ""
    if isinstance(valor, time):
        return valor.strftime("%H:%M")
    if isinstance(valor, float):
        return f"{valor:g}"
    return str(valor)


def _texto_enviado(valor: object) -> str:
    """Valor vindo da API como texto de formulário (booleanos em "sim"/"não", listas por vírgula)."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    if isinstance(valor, float):
        return str(int(valor)) if valor.is_integer() else repr(valor)
    if isinstance(valor, list):
        return ",".join(str(item) for item in valor)
    return str(valor)


def chaves_desconhecidas(valores: Mapping[str, object]) -> dict[str, str]:
    """Erro por chave fora dos grupos (inclui os ligados de Serviços e qualquer coluna não exposta)."""
    return {chave: "Campo desconhecido." for chave in valores if chave not in CHAVES}


def _linhas_travadas(s: Session, config_env: Config, tabelas: set[str], agora: datetime) -> dict[str, object]:
    repo.obter_config_geral(s, config_env)
    repo.obter_config_liga(s, config_env)
    repo_ia.obter_config_ia(s, agora)
    linhas = {}
    for tabela in sorted(tabelas):
        modelo = MODELOS[tabela]
        consulta = select(modelo).where(modelo.id == 1).with_for_update().execution_options(populate_existing=True)
        linhas[tabela] = s.execute(consulta).scalar_one()
    return linhas


def _mesma_versao(enviada: str | None, atual: datetime) -> bool:
    if enviada is None:
        return False
    try:
        return datetime.fromisoformat(enviada) == atual
    except ValueError:
        return False


def salvar(
    s: Session, config_env: Config, versoes: Mapping[str, str], valores: Mapping[str, object], agora: datetime
) -> dict[str, list[Valor]]:
    """Valida e grava os campos alterados na transação de quem chama. Devolve só os que mudaram de fato,
    `{chave: [antes, depois]}` (vazio: nada gravado). Levanta `CamposInvalidos` (chaves completas) ou
    `ConfigMudou`, sempre antes de gravar."""
    desconhecidas = chaves_desconhecidas(valores)
    if desconhecidas:
        raise CamposInvalidos(desconhecidas)
    por_tabela: dict[str, dict[str, object]] = {}
    for chave, valor in valores.items():
        tabela, nome = chave.split(".", 1)
        por_tabela.setdefault(tabela, {})[nome] = valor
    linhas = _linhas_travadas(s, config_env, set(por_tabela), agora)
    if any(not _mesma_versao(versoes.get(tabela), linha.atualizado_em) for tabela, linha in linhas.items()):
        raise ConfigMudou

    erros: dict[str, str] = {}
    validados: dict[str, dict[str, object]] = {}
    for tabela, enviados in por_tabela.items():
        campos, validar = _FORMULARIO[tabela]
        formulario = {nome: _texto_salvo(linhas[tabela], tabela, nome) for nome in campos}
        formulario |= {nome: _texto_enviado(valor) for nome, valor in enviados.items()}
        validados[tabela], erros_tabela = validar(formulario)
        erros |= {f"{tabela}.{nome}": mensagem for nome, mensagem in erros_tabela.items()}
    if erros:
        raise CamposInvalidos(erros)

    mudancas: dict[str, list[Valor]] = {}
    for tabela, enviados in por_tabela.items():
        alterados = {}
        for nome in enviados:
            antes, depois = getattr(linhas[tabela], nome), validados[tabela][nome]
            if antes != depois:
                alterados[nome] = depois
                mudancas[f"{tabela}.{nome}"] = [serializar(antes), serializar(depois)]
        if alterados:
            _GRAVAR[tabela](s, alterados, agora)
    return mudancas
