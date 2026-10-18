"""Uma busca na Amazon para um produto da Liga (descoberta): grava os resultados (ASIN novo fica
pendente para o casamento) e o preço de origem `busca`. Não abre página de produto nem de vendedor:
o preço dos anúncios confirmados é do monitor (monitor.py). Não conhece fila, ciclo nem janela (ver
varredura.py). `abrir_pagina` e `ler_pagina` são usadas também pelo monitor e pela conferência."""

import dataclasses
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import quote_plus

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.avisos.servico import Avisador
from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon
from tcg_sniper.coletor_amazon.parsers import parse_busca
from tcg_sniper.coletor_amazon.termo import termo_busca
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio_amazon as repo
from tcg_sniper.db.models import ConfigAmazon, ProdutoLiga
from tcg_sniper.navegador.base import NavegadorInterativo
from tcg_sniper.navegador.modelos import Pagina
from tcg_sniper.navegador.ritmo import Dormir, com_um_retry, pausa_aleatoria, salvar_html_falha
from tcg_sniper.oportunidades import motor
from tcg_sniper.parsing import ErroParser

log = logging.getLogger(__name__)


class DesafioAmazon(Exception):
    def __init__(self, url: str):
        super().__init__(url)
        self.url = url


MAX_HTMLS_FALHA = 3  # por ciclo: sob bloqueio ou layout novo toda página falha e cada uma tem 1-2 MB


@dataclass
class CotaHtmlFalha:
    """Quantos HTMLs de falha ainda podem ser salvos; a varredura cria uma por ciclo (e uma por dia no monitor)."""

    restante: int = MAX_HTMLS_FALHA

    def consumir(self) -> bool:
        if self.restante <= 0:
            return False
        self.restante -= 1
        return True


@dataclass
class ContextoBusca:
    sessoes: sessionmaker[Session]
    navegador: NavegadorInterativo
    avisador: Avisador
    config: Config
    cfg: ConfigAmazon
    relogio: Callable[[], datetime]
    dormir: Dormir
    rng: random.Random
    nome_falha: str  # prefixo do HTML salvo em <DIR_DADOS>/falhas quando um parser falha
    cota_falhas: CotaHtmlFalha = field(default_factory=CotaHtmlFalha)


def url_busca(cfg: ConfigAmazon, nome: str) -> str:
    return cfg.url_busca.replace("{termo}", quote_plus(termo_busca(nome)))


def abrir_pagina(ctx: ContextoBusca, url: str) -> Pagina:
    """Pausa humana, abre (uma nova tentativa em erro de rede) e para no CAPTCHA."""
    pausa_aleatoria(ctx.cfg.pausa_min_s, ctx.cfg.pausa_max_s, ctx.dormir, ctx.rng)
    pagina = com_um_retry(lambda: ctx.navegador.abrir(url), url, ctx.dormir)
    if eh_desafio_amazon(pagina):
        raise DesafioAmazon(url)
    return pagina


def ler_pagina[T](ctx: ContextoBusca, pagina: Pagina, sufixo: str, parser: Callable[[str], T]) -> T:
    try:
        return parser(pagina.html)
    except ErroParser:
        if ctx.cota_falhas.consumir():
            caminho = salvar_html_falha(ctx.config.dir_dados, f"{ctx.nome_falha}-{sufixo}", pagina.html)
            log.warning("parser da Amazon falhou em %s; HTML em %s", pagina.url, caminho)
        else:
            log.warning("parser da Amazon falhou em %s; HTML não salvo (limite atingido)", pagina.url)
        raise


@dataclasses.dataclass(frozen=True)
class Conferencia:
    candidatos: int  # confirmados da busca já no desconto pelo preço atual (só para o ritmo da fila)


def processar_produto(ctx: ContextoBusca, produto: ProdutoLiga, usar_nome_en: bool = False) -> Conferencia:
    """Busca o produto e grava os resultados. Devolve quantos anúncios confirmados da busca estão no
    desconto pelo preço atual (a fila busca mais vezes o produto que teve candidato). Lança
    DesafioAmazon (CAPTCHA), ErroParser (layout) ou ErroRede (depois de uma nova tentativa).
    `usar_nome_en` busca pelo nome em inglês (se o produto tiver um)."""
    nome = produto.nome_en if usar_nome_en and produto.nome_en else produto.nome
    pagina = abrir_pagina(ctx, url_busca(ctx.cfg, nome))
    itens = ler_pagina(ctx, pagina, "busca", lambda html: parse_busca(html, ctx.cfg.resultados_por_busca))
    with ctx.sessoes() as s, s.begin():
        anuncios = repo.gravar_busca(s, itens, produto.id, ctx.relogio(), ctx.config.zona)
        candidatos = sum(
            1
            for linha in repo.confirmados_com_referencia(s, [a.id for a in anuncios])
            if motor.atinge_desconto(
                linha.atual.preco, linha.liga.preco_a_partir if linha.liga else None, ctx.cfg.desconto_min_pct
            )
        )
    return Conferencia(candidatos)
