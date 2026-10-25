"""Dashboard da gestão: "Precisa de você", funil e oportunidades em destaque. Sem HTTP nem Jinja.

Os avisos do painel antigo (`consultas.painel`) trazem links do admin antigo; `destino_novo` os traduz para as
telas novas. O que ainda não foi migrado (hoje, as Configurações) volta como `antigo:<caminho>` e o front monta o
endereço do admin antigo."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from urllib.parse import parse_qsl, urlencode, urlsplit

from sqlalchemy.orm import Session

from tcg_sniper.config import Config
from tcg_sniper.consultas import oportunidades, painel
from tcg_sniper.consultas.catalogo import SituacaoCatalogo, contar_esperando_decisao
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_ia as repo_ia

PREFIXO_ANTIGO = "antigo:"
DESTINO_ESPERANDO = "/gestao/casamentos?situacao=esperando_decisao"
LIMITE_TETO_IA = Decimal("0.8")  # a partir de 80% do teto (do dia ou do mês) a IA entra em "Precisa de você"

# Aba do histórico antigo (/logs?aba=…) -> filtro "o que" da Atividade.
_O_QUE_DA_ABA = {
    "liga": "coleta_liga",
    "amazon": "busca",
    "monitor": "leitura_monitor",
    "checkout": "checkout",
    "ia": "ia",
    "manutencao": "backup",
}
_SITUACOES_ATIVIDADE = ("ok", "parcial", "falha")
# Situação da lista antiga de casamentos -> situação do produto da lista nova.
_SITUACAO_CASAMENTO = {
    "pendentes": "esperando_decisao",
    # Aproximação com perda: o filtro antigo olhava pares; o novo olha o produto (um casado com pendente sai).
    "oportunidade": "esperando_decisao",
    "sem_par": "sem_candidato",
    "casados": "casado",
    "todos": "todos",
}
_SITUACOES_PRODUTO = ("casado", "esperando_decisao", "so_ignorados", "sem_candidato")
# Permissão da tela de destino (além de `ver_area_gestao`); None = sem outra exigência.
_REQUER_DO_CAMINHO = (
    ("/gestao/servicos", "ver_servicos"),
    ("/gestao/casamentos", "revisar_casamentos"),
    ("antigo:/configuracoes", "ver_configuracoes"),
)


def _com_query(caminho: str, parametros: dict[str, str]) -> str:
    return f"{caminho}?{urlencode(parametros)}" if parametros else caminho


def _destino_logs(p: dict[str, str]) -> str:
    aba = p.get("aba", "liga")
    o_que = _O_QUE_DA_ABA.get(aba)
    if o_que is None:
        return "/gestao/atividade"
    saida = {"o_que": o_que}
    # Cada aba antiga tem o seu parâmetro de situação; só o que tem par na tela nova é levado.
    bruto = p.get(f"{aba}_status") or p.get("status") or ""
    if aba == "ia" and p.get("situacao") == "com_erro":
        bruto = "falha"
    if bruto in _SITUACOES_ATIVIDADE:
        saida["situacao"] = bruto
    return _com_query("/gestao/atividade", saida)


def _destino_casamentos(caminho: str, p: dict[str, str]) -> str:
    if caminho.startswith("/casamentos/produto/"):
        return "/gestao/casamentos/" + caminho.rsplit("/", 1)[1]
    saida: dict[str, str] = {}
    if p.get("busca"):
        saida["busca"] = p["busca"]
    situacao = p.get("situacao_produto") if p.get("situacao_produto") in _SITUACOES_PRODUTO else None
    situacao = situacao or _SITUACAO_CASAMENTO.get(p.get("situacao", ""))
    if situacao:
        saida["situacao"] = situacao
    if p.get("categoria"):
        saida["categoria"] = p["categoria"]
    if p.get("com_preco") == "1":
        saida["com_preco"] = "true"  # o que o front espera (a lista antiga mandava "1")
    return _com_query("/gestao/casamentos", saida)


def destino_novo(link_antigo: str) -> str:
    """Link do admin antigo -> destino da gestão nova. O que não foi migrado vira `antigo:<link>`."""
    partes = urlsplit(link_antigo)
    caminho, p = partes.path, dict(parse_qsl(partes.query))
    if caminho == "/":
        return "/gestao"
    if caminho == "/servicos":
        return "/gestao/servicos"
    if caminho == "/logs":
        return _destino_logs(p)
    if caminho == "/mensagens":
        return _com_query("/gestao/atividade", {"o_que": "mensagem", **({"situacao": "falha"} if p.get("situacao") == "falha" else {})})
    if caminho == "/casamentos" or caminho.startswith("/casamentos/produto/"):
        return _destino_casamentos(caminho, p)
    return PREFIXO_ANTIGO + link_antigo


def permissao_do_destino(destino: str) -> str | None:
    """Permissão que a tela de destino exige além de `ver_area_gestao`."""
    if destino.startswith("/gestao/atividade"):
        return "ver_mensagens" if "o_que=mensagem" in destino else "ver_logs"
    for prefixo, permissao in _REQUER_DO_CAMINHO:
        if destino.startswith(prefixo):
            return permissao
    return None


@dataclass(frozen=True)
class ItemPrecisa:
    texto: str
    rotulo: str
    destino: str
    requer: str | None  # permissão da tela de destino; a rota esconde o item de quem não a tem


DESTINO_MONITOR_ATRASADO = PREFIXO_ANTIGO + "/configuracoes?secao=amazon"  # até a 3C migrar as Configurações
_ROTULO_POR_CHAVE = {"servico_pausado": "Ligar", "servico_problema": "Ver", "monitor_atrasado": "Ver o efeito"}


def rotulo_de(aviso: painel.Aviso) -> str:
    """Serviço pausado -> "Ligar"; com problema -> "Ver"; monitor atrasado -> "Ver o efeito"; o resto, o rótulo do painel."""
    return _ROTULO_POR_CHAVE.get(aviso.chave or "", aviso.rotulo_link)


def destino_de(aviso: painel.Aviso) -> str:
    return DESTINO_MONITOR_ATRASADO if aviso.chave == "monitor_atrasado" else destino_novo(aviso.link)


def _item(texto: str, rotulo: str, destino: str) -> ItemPrecisa:
    return ItemPrecisa(texto, rotulo, destino, permissao_do_destino(destino))


def _esperando(s: Session) -> list[ItemPrecisa]:
    n = contar_esperando_decisao(s)
    if not n:
        return []
    texto = f"{n} produto esperando decisão." if n == 1 else f"{n} produtos esperando decisão."
    return [ItemPrecisa(texto, "Revisar em sequência", DESTINO_ESPERANDO, "revisar_casamentos")]


def _pct(parte: Decimal, teto: Decimal) -> int:
    return int(parte * 100 / teto)


def ia_perto_do_teto(s: Session, agora: datetime, cfg: Config) -> list[ItemPrecisa]:
    """A IA gastou 80% ou mais do teto do dia ou do mês (`teto 0` = sem teto, não avisa)."""
    cfg_ia = repo_ia.obter_config_ia(s, agora)
    gasto = repo_ia.gasto(s, agora, cfg.zona)
    itens = []
    for nome, usado, teto in (("dia", gasto.dia_usd, cfg_ia.teto_dia_usd), ("mês", gasto.mes_usd, cfg_ia.teto_mes_usd)):
        if teto > 0 and usado >= teto * LIMITE_TETO_IA:
            texto = f"A IA já usou {_pct(usado, teto)}% do teto do {nome} ({painel.usd(usado)} de {painel.usd(teto)})."
            itens.append(_item(texto, "Ajustar em Configurações", PREFIXO_ANTIGO + "/configuracoes"))
    return itens


def precisa(s: Session, agora: datetime, cfg: Config, avisos_painel: Sequence[painel.Aviso]) -> list[ItemPrecisa]:
    """Decisões esperando, IA perto do teto e os avisos do painel (serviços com problema ou desligados, monitor
    atrasado, carrinho a conferir, mensagens com falha…) já com o destino novo. Vazio quando não há nada."""
    itens = _esperando(s) + ia_perto_do_teto(s, agora, cfg)
    itens += [_item(a.texto, rotulo_de(a), destino_de(a)) for a in avisos_painel]
    return itens


@dataclass(frozen=True)
class Funil:
    liga: int  # produtos da Liga no banco (ativos e inativos)
    monitorados: int  # produtos ativos
    esperando_decisao: int
    so_ignorados: int
    sem_candidato: int
    casados_produtos: int
    casados_anuncios: int  # anúncios confirmados (o que o monitor lê)
    oportunidades: int  # abertas agora


def funil(s: Session, agora: datetime, cfg: Config, numeros: painel.Numeros | None = None) -> Funil:
    n = numeros or painel.numeros(s, agora, cfg)
    cat: SituacaoCatalogo = n.catalogo
    return Funil(
        liga=n.produtos_total,
        monitorados=n.produtos_ativos,
        esperando_decisao=cat.esperando_decisao,
        so_ignorados=cat.so_ignorados,
        sem_candidato=cat.sem_candidato,
        casados_produtos=cat.casado,
        casados_anuncios=repo_amz.situacao_monitor(s, agora, repo_amz.obter_config(s)).confirmados,
        oportunidades=n.abertas,
    )


def top_oportunidades(s: Session, quantas: int = 3) -> list[oportunidades.Ativa]:
    """As abertas de maior desconto (a consulta das ativas já vem ordenada por desconto)."""
    return oportunidades.ativas(s)[:quantas]

