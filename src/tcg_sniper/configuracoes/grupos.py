"""Grupos da tela de Configurações (spec da fase 3, "Configurações"): cada grupo junta os campos de um
objetivo, com a frase de propósito e, por campo, rótulo, explicação, tipo, padrão, limites e vínculo.
Os campos vêm das quatro tabelas de uma linha só (`config_geral`, `config_liga`, `config_amazon`,
`config_ia`); a chave de cada um é `"<tabela>.<campo>"`. Nada do .env entra aqui."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from tcg_sniper.coletor_amazon.config import EXPLICACOES, ROTULOS
from tcg_sniper.config import Config
from tcg_sniper.configuracoes.geral_liga import (
    EXPLICACOES_GERAL,
    EXPLICACOES_LIGA,
    ROTULOS_GERAL,
    ROTULOS_LIGA,
)
from tcg_sniper.configuracoes.ia import EXPLICACOES_IA, ROTULOS_IA
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import (
    LIMITES_CONFIG_AMAZON,
    LIMITES_CONFIG_IA,
    LIMITES_CONFIG_LIGA,
    PADROES_CONFIG_AMAZON,
    PADROES_CONFIG_IA,
    ConfigAmazon,
    ConfigGeral,
    ConfigIA,
    ConfigLiga,
)

Tipo = Literal["int", "decimal", "float", "hora", "texto", "bool", "escolha", "categorias"]
TABELAS = ("geral", "liga", "amazon", "ia")
OPCOES_ESFORCO = (("minimal", "mínimo"), ("low", "baixo"), ("medium", "médio"), ("high", "alto"))


@dataclass(frozen=True)
class Campo:
    chave: str  # "<tabela>.<campo>", tabela em geral, liga, amazon, ia
    rotulo: str
    explicacao: str
    tipo: Tipo
    padrao: object
    minimo: Decimal | None = None
    maximo: Decimal | None = None
    opcoes: tuple[tuple[str, str], ...] = ()  # (valor, rótulo em português)
    avancado: bool = False
    vinculo: str | None = None

    @property
    def tabela(self) -> str:
        return self.chave.split(".", 1)[0]

    @property
    def nome(self) -> str:
        return self.chave.split(".", 1)[1]


@dataclass(frozen=True)
class Grupo:
    id: str
    titulo: str
    proposito: str
    campos: tuple[Campo, ...]
    tem_efeito: bool


def _limites(limites: dict[str, tuple[int, int]], nome: str) -> tuple[Decimal | None, Decimal | None]:
    if nome not in limites:
        return None, None
    minimo, maximo = limites[nome]
    return Decimal(minimo), Decimal(maximo)


def _padrao_env(nome: str) -> object:
    return Config.model_fields[nome].default


# Padrões de geral e liga: os do .env sem nada preenchido (a linha nasce deles; `obter_config_*`).
PADROES_GERAL: dict[str, object] = {
    "host_publico": _padrao_env("host_publico"),
    "fuso": _padrao_env("fuso"),
    "evolution_instancia": None,
    "whatsapp_grupo_admin": None,
    "whatsapp_grupo_oportunidades": None,
    "validade_oportunidade_h": 6,
}
PADROES_LIGA: dict[str, object] = {
    "coleta_hora": _padrao_env("coleta_hora"),
    "coleta_jitter_min": _padrao_env("coleta_jitter_min"),
    "pausa_min_s": _padrao_env("pausa_min_s"),
    "pausa_max_s": _padrao_env("pausa_max_s"),
    "limite_falha_pct": _padrao_env("limite_falha_pct"),
    "categorias": _padrao_env("liga_categorias"),
    "url_listagem": _padrao_env("liga_url_listagem"),
    "max_cliques": _padrao_env("liga_max_cliques"),
    "produtos_novos_dia": _padrao_env("produtos_novos_dia"),
    "esfriar_desafio_min": _padrao_env("esfriar_desafio_min"),
}

VINCULOS: dict[str, str] = {
    "amazon.quase_oportunidade_min_pct": "menor que o desconto mínimo",
    "amazon.margem_candidata_pp": "conferir a partir de (desconto mínimo − este valor)",
    "amazon.pausa_min_s": "não maior que a pausa máxima",
    "liga.pausa_min_s": "não maior que a pausa máxima",
    "amazon.janela_fim": "depois do início da busca",
    "amazon.monitor_janela_fim": "depois do início do monitor",
}


def _amazon(nome: str, tipo: Tipo = "int", avancado: bool = False) -> Campo:
    minimo, maximo = _limites(LIMITES_CONFIG_AMAZON, nome)
    chave = f"amazon.{nome}"
    return Campo(chave, ROTULOS[nome], EXPLICACOES[nome], tipo, PADROES_CONFIG_AMAZON[nome], minimo, maximo,
                 avancado=avancado, vinculo=VINCULOS.get(chave))


def _liga(nome: str, tipo: Tipo = "int", avancado: bool = False) -> Campo:
    minimo, maximo = _limites(LIMITES_CONFIG_LIGA, nome)
    chave = f"liga.{nome}"
    return Campo(chave, ROTULOS_LIGA[nome], EXPLICACOES_LIGA[nome], tipo, PADROES_LIGA[nome], minimo, maximo,
                 avancado=avancado, vinculo=VINCULOS.get(chave))


def _geral(nome: str, tipo: Tipo = "texto") -> Campo:
    minimo, maximo = (Decimal(1), Decimal(48)) if nome == "validade_oportunidade_h" else (None, None)  # CHECK do banco
    return Campo(f"geral.{nome}", ROTULOS_GERAL[nome], EXPLICACOES_GERAL[nome], tipo, PADROES_GERAL[nome], minimo, maximo)


def _ia(nome: str, tipo: Tipo = "int", avancado: bool = False, opcoes: tuple[tuple[str, str], ...] = ()) -> Campo:
    minimo, maximo = _limites(LIMITES_CONFIG_IA, nome)
    if tipo == "decimal":
        minimo = Decimal(0)  # CHECK do banco: valores em dólar, zero ou mais
    return Campo(f"ia.{nome}", ROTULOS_IA[nome], EXPLICACOES_IA[nome], tipo, PADROES_CONFIG_IA[nome], minimo, maximo,
                 opcoes, avancado)


GRUPOS: tuple[Grupo, ...] = (
    Grupo("oportunidades", "Oportunidades",
          "O que vira alerta no grupo de oportunidades e o que aparece como \"quase lá\".",
          (_amazon("desconto_min_pct"), _amazon("quase_oportunidade_min_pct"), _amazon("realerta_queda_pct"),
           _amazon("carencia_encerramento_min"), _amazon("liga_preco_max_idade_h"),
           _geral("validade_oportunidade_h", "int")),
          True),
    Grupo("vendedores", "Vendedores",
          "Em quem confiar: lojista com envio pela Amazon abaixo destes números não vira oportunidade.",
          (_amazon("vendedor_min_positivas_pct"), _amazon("vendedor_min_avaliacoes"), _amazon("vendedor_reavaliar_dias")),
          False),
    Grupo("busca", "Achar anúncios novos (Amazon · busca)",
          "Quando e em que ritmo o navegador da busca procura anúncios dos produtos da Liga.",
          (_amazon("janela_inicio", "hora"), _amazon("janela_fim", "hora"), _amazon("max_buscas_hora"),
           _amazon("intervalo_busca_min"), _amazon("descoberta_casados_dias"),
           _amazon("url_busca", "texto", avancado=True), _amazon("resultados_por_busca", avancado=True),
           _amazon("limite_falha_pct", avancado=True)),
          True),
    Grupo("monitor", "Acompanhar preço (Amazon · monitor)",
          "De quanto em quanto tempo o navegador logado relê o preço dos anúncios confirmados.",
          (_amazon("monitor_janela_inicio", "hora"), _amazon("monitor_janela_fim", "hora"),
           _amazon("monitor_intervalo_min"), _amazon("monitor_max_paginas_hora"),
           _amazon("monitor_esgotado_dias", avancado=True)),
          True),
    Grupo("checkout", "Conferir no checkout",
          "Quais ofertas vão ao carrinho para conferir o preço com impostos antes do aviso.",
          (_amazon("margem_candidata_pp"), _amazon("checkout_validade_h")),
          True),
    Grupo("bloqueio", "Cuidado com bloqueio (vale para os dois navegadores da Amazon)",
          "Pausas entre páginas: menores leem mais por hora e aumentam a chance de CAPTCHA.",
          (_amazon("pausa_min_s"), _amazon("pausa_max_s")),
          True),
    Grupo("liga", "LigaMagic",
          "Quando e como a coleta diária lê os preços da LigaMagic.",
          (_liga("coleta_hora", "hora"), _liga("coleta_jitter_min"), _liga("produtos_novos_dia"),
           _liga("esfriar_desafio_min"), _liga("max_cliques"), _liga("pausa_min_s", "float"),
           _liga("pausa_max_s", "float"), _liga("categorias", "categorias"),
           _liga("url_listagem", "texto", avancado=True), _liga("limite_falha_pct", avancado=True)),
          False),
    Grupo("ia-decide", "IA · o que decide sozinha",
          "Se a IA avalia os anúncios e quando ela confirma ou ignora sem esperar você.",
          (_ia("ligado", "bool"), _ia("automatico", "bool"), _ia("confianca_confirmar"), _ia("confianca_ignorar")),
          True),
    Grupo("ia-ritmo", "IA · ritmo",
          "De quanto em quanto tempo a IA procura anúncios para avaliar e quantos por vez.",
          (_ia("intervalo_min"), _ia("lote")),
          True),
    Grupo("ia-gasto", "IA · quanto pode gastar",
          "Tetos de gasto: atingido um deles, a IA para até o dia ou o mês seguinte e avisa no WhatsApp.",
          (_ia("teto_dia_usd", "decimal"), _ia("teto_mes_usd", "decimal"), _ia("max_chamadas_dia")),
          True),
    Grupo("ia-modelo", "IA · modelo",
          "Qual modelo da OpenAI avalia os anúncios e quanto ele custa.",
          (_ia("modelo", "texto", avancado=True), _ia("esforco", "escolha", avancado=True, opcoes=OPCOES_ESFORCO),
           _ia("preco_entrada_milhao_usd", "decimal", avancado=True),
           _ia("preco_saida_milhao_usd", "decimal", avancado=True)),
          False),
    Grupo("whatsapp", "WhatsApp e avisos",
          "Para onde vão as mensagens do WhatsApp e quais avisos saem.",
          (_geral("evolution_instancia"), _geral("whatsapp_grupo_admin"), _geral("whatsapp_grupo_oportunidades")),
          False),
    Grupo("sistema", "Sistema",
          "Endereço deste PC na rede (links do noVNC) e fuso das datas.",
          (_geral("host_publico"), _geral("fuso")),
          False),
)

_POR_CHAVE: dict[str, Campo] = {c.chave: c for g in GRUPOS for c in g.campos}
_POR_ID: dict[str, Grupo] = {g.id: g for g in GRUPOS}


def campo(chave: str) -> Campo:
    return _POR_CHAVE[chave]


def grupo(grupo_id: str) -> Grupo:
    return _POR_ID[grupo_id]


def _linhas(s: Session, config_env: Config) -> dict[str, ConfigGeral | ConfigLiga | ConfigAmazon | ConfigIA]:
    return {
        "geral": repo.obter_config_geral(s, config_env),
        "liga": repo.obter_config_liga(s, config_env),
        "amazon": repo_amz.obter_config(s),
        "ia": repo_ia.obter_config_ia(s),
    }


def valores_atuais(s: Session, config_env: Config) -> dict[str, object]:
    """Valor salvo de cada campo dos grupos, por chave. Só as tabelas de configuração: nenhum segredo do
    .env (o `config_env` só semeia geral e liga na primeira leitura) nem os ligados de Serviços."""
    linhas = _linhas(s, config_env)
    return {c.chave: getattr(linhas[c.tabela], c.nome) for c in _POR_CHAVE.values()}


def versoes(s: Session) -> dict[str, str]:
    """`atualizado_em` (ISO) de cada tabela que já existe: o front manda de volta para detectar edição concorrente."""
    modelos = {"geral": ConfigGeral, "liga": ConfigLiga, "amazon": ConfigAmazon, "ia": ConfigIA}
    saida = {}
    for tabela, modelo in modelos.items():
        linha = s.get(modelo, 1, populate_existing=True)
        if linha is not None:
            saida[tabela] = linha.atualizado_em.isoformat()
    return saida
