"""A única função que transforma um aviso em texto de WhatsApp: título com emoji, linhas com "•",
"O que fazer", link de produto e rodapé com hora e origem. Escapa a formatação vinda dos dados, corta
textos longos e garante que nenhum endereço do sistema sai (admin, noVNC, IP de casa)."""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from tcg_sniper.avisos.catalogo import (
    CATALOGO,
    CHAVE_GERAL,
    EMOJI,
    EMOJI_RESOLVIDO,
    Dados,
    Linha,
    Negrito,
    TipoAviso,
)

log = logging.getLogger(__name__)

ESTRITO = False  # tests/conftest.py liga: endereço do sistema vira exceção em vez de ser removido
LIMITE = 1500
MAX_TRECHO = 300
MAX_EXTRA = 120
MAX_DESTAQUE = 200
DOMINIOS_PERMITIDOS = ("amazon.com.br", "ligamagic.com.br")
REMOVIDO = "[endereço removido]"
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_PORTAS = re.compile(r":(?:8000|6080|6081|6082)(?!\d)")
_ESCAPES = str.maketrans({"*": "∗", "_": "ˍ", "~": "˜", "`": "ˋ"})


class UrlProibida(ValueError):
    """Mensagem com endereço do sistema (admin, noVNC, IP de casa) ou link fora da Amazon e da LigaMagic."""


@dataclass(frozen=True)
class Aviso:
    tipo: TipoAviso
    titulo_extra: str | None
    linhas: tuple[Linha, ...]
    acao: str | None
    origem: str
    quando: datetime
    link_produto: str | None = None
    destaque: str | None = None


def aviso_de(tipo: TipoAviso, dados: Dados, quando: datetime) -> Aviso:
    """Junta os dados da ocorrência com a definição do tipo (ação padrão e origem)."""
    definicao = CATALOGO[tipo]
    acao = dados.acao if dados.acao is not None else definicao.acao
    return Aviso(
        tipo, dados.titulo_extra, dados.linhas, acao, definicao.origem, quando, dados.link_produto, dados.destaque
    )


def escapar(texto: str) -> str:
    """Troca os marcadores do WhatsApp por sósias: dado nunca vira negrito, itálico, riscado ou código."""
    return texto.translate(_ESCAPES)


def _cortar(texto: str, maximo: int) -> str:
    return texto if len(texto) <= maximo else texto[: maximo - 1] + "…"


def _dado(texto: str, maximo: int = MAX_TRECHO) -> str:
    return escapar(_cortar(texto, maximo))


def _linha(linha: Linha) -> str:
    trechos = (linha,) if isinstance(linha, str) else linha
    partes = [f"*{_dado(t.texto)}*" if isinstance(t, Negrito) else _dado(t) for t in trechos]
    return "• " + "".join(partes)


def cabecalho(tipo: TipoAviso) -> str:
    """Começo de toda mensagem do tipo (também do lembrete): emoji e título, sem o `*` de fechamento."""
    definicao = CATALOGO[tipo]
    return f"{EMOJI[definicao.severidade]} *{definicao.titulo}"


def eh_do_tipo(texto: str, tipo: TipoAviso) -> bool:
    return texto.startswith(cabecalho(tipo))


def eh_resolvido_do_tipo(texto: str, tipo: TipoAviso) -> bool:
    return texto.startswith(f"{EMOJI_RESOLVIDO} *{CATALOGO[tipo].titulo}")


def eh_do_proprio_aviso(texto: str, tipo: TipoAviso) -> bool:
    """O aviso do tipo ou o "✅ resolvido" dele (a falha de um deles nunca gera outro aviso)."""
    return eh_do_tipo(texto, tipo) or eh_resolvido_do_tipo(texto, tipo)


def _titulo(aviso: Aviso) -> str:
    extra = f" · {_dado(aviso.titulo_extra, MAX_EXTRA)}" if aviso.titulo_extra else ""
    return cabecalho(aviso.tipo) + extra


def _montar(primeira: str, aviso: Aviso, zona: ZoneInfo) -> str:
    topo = [primeira]
    if aviso.destaque:
        topo.append(f"*{_dado(aviso.destaque, MAX_DESTAQUE)}*")
    fim = []
    if aviso.acao:
        fim += ["", f"*O que fazer:* {aviso.acao}"]
    if aviso.link_produto:
        fim.append(aviso.link_produto)
    fim.append(f"_{aviso.quando.astimezone(zona):%d/%m %H:%M} · {aviso.origem}_")
    linhas = [_linha(linha) for linha in aviso.linhas]

    def juntar(meio: list[str]) -> str:
        return "\n".join(topo + meio + fim)

    if len(juntar(linhas)) > LIMITE:
        while linhas and len(juntar([*linhas, "• …"])) > LIMITE:
            linhas.pop()
        linhas.append("• …")
    return juntar(linhas)


def formatar(aviso: Aviso, zona: ZoneInfo, host_publico: str | None = None, *, estrito: bool | None = None) -> str:
    return conferir_urls(_montar(_titulo(aviso) + "*", aviso, zona), host_publico, estrito=estrito)


def formatar_lembrete(
    aviso: Aviso,
    ocorrencias: int,
    desde: datetime,
    zona: ZoneInfo,
    host_publico: str | None = None,
    *,
    estrito: bool | None = None,
) -> str:
    """O problema continua: título com a contagem e a hora da primeira ocorrência, corpo da ocorrência atual."""
    local_desde, local_agora = desde.astimezone(zona), aviso.quando.astimezone(zona)
    hora = f"{local_desde:%H:%M}" if local_desde.date() == local_agora.date() else f"{local_desde:%d/%m %H:%M}"
    primeira = f"{_titulo(aviso)} continua · {ocorrencias} vezes desde {hora}*"
    return conferir_urls(_montar(primeira, aviso, zona), host_publico, estrito=estrito)


def formatar_resolvido(
    tipo: TipoAviso,
    chave: str,
    ocorrencias: int,
    primeiro_em: datetime,
    agora: datetime,
    zona: ZoneInfo,
    host_publico: str | None = None,
    *,
    estrito: bool | None = None,
) -> str:
    definicao = CATALOGO[tipo]
    extra = f" · {_dado(chave, MAX_EXTRA)}" if chave != CHAVE_GERAL else ""
    vezes = "1 vez" if ocorrencias == 1 else f"{ocorrencias} vezes"
    texto = (
        f"{EMOJI_RESOLVIDO} *{definicao.titulo}{extra} resolvido · {vezes} em {formatar_duracao(agora - primeiro_em)}*\n"
        f"_{agora.astimezone(zona):%d/%m %H:%M} · {definicao.origem}_"
    )
    return conferir_urls(texto, host_publico, estrito=estrito)


def formatar_duracao(duracao: timedelta) -> str:
    minutos = int(duracao.total_seconds() // 60)
    if minutos < 1:
        return "menos de 1 min"
    if minutos < 60:
        return f"{minutos} min"
    horas, minutos = divmod(minutos, 60)
    if horas < 24:
        return f"{horas} h {minutos} min" if minutos else f"{horas} h"
    dias, horas = divmod(horas, 24)
    return f"{dias} d {horas} h" if horas else f"{dias} d"


def _permitida(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == dominio or host.endswith("." + dominio) for dominio in DOMINIOS_PERMITIDOS)


def conferir_urls(texto: str, host_publico: str | None = None, *, estrito: bool | None = None) -> str:
    """Regra de URL do spec: só links da Amazon e da LigaMagic; nada de `:8000`, `:6080`, `:6081`, `:6082` nem do
    `host_publico`. Estrito (testes): levanta `UrlProibida`. Senão troca por "[endereço removido]" e loga."""
    estrito = ESTRITO if estrito is None else estrito
    achados: list[str] = []

    def trocar(m: re.Match[str]) -> str:
        achados.append(m.group(0))
        return REMOVIDO

    novo = _URL.sub(lambda m: m.group(0) if _permitida(m.group(0)) else trocar(m), texto)
    novo = _PORTAS.sub(trocar, novo)
    host = (host_publico or "").strip()
    if host:
        novo = re.sub(rf"(?<![\w.-]){re.escape(host)}(?![\w-])", trocar, novo, flags=re.IGNORECASE)
    if not achados:
        return texto
    if estrito:
        raise UrlProibida(f"endereço do sistema na mensagem: {achados}")
    log.warning("endereço do sistema removido da mensagem: %s", achados)
    return novo
