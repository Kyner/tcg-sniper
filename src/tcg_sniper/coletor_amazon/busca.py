"""Uma busca na Amazon para um produto da Liga: grava os resultados, confirma os candidatos na
página do produto (e o perfil do vendedor, se preciso), roda o motor e avisa o grupo de
oportunidades. Não conhece fila, ciclo nem janela (ver varredura.py)."""

import dataclasses
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote_plus

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon
from tcg_sniper.coletor_amazon.modelos import OfertaProduto
from tcg_sniper.coletor_amazon.parsers import parse_busca, parse_produto_amazon, parse_vendedor, url_vendedor
from tcg_sniper.coletor_amazon.termo import termo_busca
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio_amazon as repo
from tcg_sniper.db.models import ConfigAmazon, Envio, OrigemPreco, ProdutoLiga, VendedorAmazon
from tcg_sniper.navegador.base import Navegador
from tcg_sniper.navegador.modelos import Pagina
from tcg_sniper.navegador.ritmo import Dormir, com_um_retry, pausa_aleatoria, salvar_html_falha
from tcg_sniper.notificador.base import Destino, Notificador
from tcg_sniper.oportunidades import motor
from tcg_sniper.oportunidades.mensagens import mensagem_oportunidade
from tcg_sniper.parsing import ErroParser

log = logging.getLogger(__name__)


class DesafioAmazon(Exception):
    def __init__(self, url: str):
        super().__init__(url)
        self.url = url


@dataclass
class ContextoBusca:
    sessoes: sessionmaker[Session]
    navegador: Navegador
    notificador: Notificador
    config: Config
    cfg: ConfigAmazon
    relogio: Callable[[], datetime]
    dormir: Dormir
    rng: random.Random
    nome_falha: str  # prefixo do HTML salvo em <DIR_DADOS>/falhas quando um parser falha


def url_busca(cfg: ConfigAmazon, nome: str) -> str:
    return cfg.url_busca.replace("{termo}", quote_plus(termo_busca(nome)))


def _abrir(ctx: ContextoBusca, url: str) -> Pagina:
    """Pausa humana, abre (uma nova tentativa em erro de rede) e para no CAPTCHA."""
    pausa_aleatoria(ctx.cfg.pausa_min_s, ctx.cfg.pausa_max_s, ctx.dormir, ctx.rng)
    pagina = com_um_retry(lambda: ctx.navegador.abrir(url), url, ctx.dormir)
    if eh_desafio_amazon(pagina):
        raise DesafioAmazon(url)
    return pagina


def _ler[T](ctx: ContextoBusca, pagina: Pagina, sufixo: str, parser: Callable[[str], T]) -> T:
    try:
        return parser(pagina.html)
    except ErroParser:
        caminho = salvar_html_falha(ctx.config.dir_dados, f"{ctx.nome_falha}-{sufixo}", pagina.html)
        log.warning("parser da Amazon falhou em %s; HTML em %s", pagina.url, caminho)
        raise


def processar_produto(ctx: ContextoBusca, produto: ProdutoLiga) -> int:
    """Busca o produto e confirma os candidatos. Devolve quantos candidatos houve.
    Lança DesafioAmazon (CAPTCHA), ErroParser (layout) ou ErroRede (depois de uma nova tentativa)."""
    pagina = _abrir(ctx, url_busca(ctx.cfg, produto.nome))
    itens = _ler(ctx, pagina, "busca", lambda html: parse_busca(html, ctx.cfg.resultados_por_busca))
    with ctx.sessoes() as s, s.begin():
        anuncios = repo.gravar_busca(s, itens, produto.id, ctx.relogio(), ctx.config.zona)
        candidatos = [
            (linha.anuncio.id, linha.anuncio.asin, linha.anuncio.url)
            for linha in repo.confirmados_com_referencia(s, [a.id for a in anuncios])
            if motor.atinge_desconto(
                linha.atual.preco, linha.liga.preco_a_partir if linha.liga else None, ctx.cfg.desconto_min_pct
            )
        ]
    for anuncio_id, asin, url in candidatos:
        _confirmar(ctx, anuncio_id, asin, url)
    return len(candidatos)


def _vendedor(ctx: ContextoBusca, oferta: OfertaProduto) -> VendedorAmazon | None:
    """Vendedor da oferta. Só abre o perfil de lojista FBA sem avaliação recente."""
    with ctx.sessoes() as s, s.begin():
        if oferta.envio is Envio.AMAZON:
            return repo.vendedor_da_amazon(s)
        if oferta.seller_id is None:
            return None
        conhecido = repo.obter_vendedor(s, oferta.seller_id)
    recente = conhecido is not None and conhecido.avaliado_em is not None and (
        ctx.relogio() - conhecido.avaliado_em < timedelta(days=ctx.cfg.vendedor_reavaliar_dias)
    )
    if oferta.envio is not Envio.FBA or recente:
        return conhecido
    seller_id = oferta.seller_id
    pagina = _abrir(ctx, url_vendedor(seller_id))
    avaliacao = _ler(ctx, pagina, f"vendedor-{seller_id}", lambda html: parse_vendedor(html, seller_id))
    if avaliacao.nome is None:
        avaliacao = dataclasses.replace(avaliacao, nome=oferta.vendido_por)
    with ctx.sessoes() as s, s.begin():
        return repo.gravar_vendedor(s, avaliacao, ctx.relogio())


def _confirmar(ctx: ContextoBusca, anuncio_id: int, asin: str, url: str) -> None:
    pagina = _abrir(ctx, url)
    oferta = _ler(ctx, pagina, f"produto-{asin}", lambda html: parse_produto_amazon(html, asin))
    vendedor = _vendedor(ctx, oferta)
    agora = ctx.relogio()
    mensagem = None
    with ctx.sessoes() as s, s.begin():
        vendedor_id = vendedor.id if vendedor else None
        repo.registrar_preco(
            s, anuncio_id, oferta.preco, OrigemPreco.PRODUTO, vendedor_id, oferta.envio, agora, ctx.config.zona
        )
        linhas = repo.confirmados_com_referencia(s, [anuncio_id])
        if not linhas:  # o casamento foi desfeito no admin enquanto a página abria
            return
        linha = linhas[0]
        liga = linha.liga
        ref = motor.RefLiga(
            preco_a_partir=liga.preco_a_partir if liga else None,
            listagem_em=liga.listagem_em if liga else None,
            num_lojas=liga.num_lojas if liga else None,
            preco_medio=liga.preco_medio if liga else None,
        )
        leitura = motor.Leitura(
            oferta.preco,
            oferta.envio,
            motor.Vendedor(vendedor.nome, vendedor.pct_positivas, vendedor.num_avaliacoes) if vendedor else None,
        )
        aberta = repo.oportunidade_aberta(s, anuncio_id)
        acao = motor.decidir(
            leitura, ref, motor.Regras.de(ctx.cfg), agora, aberta.preco_alertado if aberta else None
        )
        if acao is motor.Acao.ABRIR:
            repo.abrir_oportunidade(
                s,
                anuncio_id=anuncio_id,
                produto_id=linha.produto.id,
                preco_amazon=oferta.preco,
                preco_liga=ref.preco_a_partir,
                desconto_pct=motor.desconto_pct(oferta.preco, ref.preco_a_partir),
                vendedor_id=vendedor_id,
                envio=oferta.envio,
                agora=agora,
            )
        elif acao in (motor.Acao.REALERTAR, motor.Acao.ATUALIZAR):
            repo.atualizar_oportunidade(
                s,
                aberta,
                preco_amazon=oferta.preco,
                preco_liga=ref.preco_a_partir,
                desconto_pct=motor.desconto_pct(oferta.preco, ref.preco_a_partir),
                vendedor_id=vendedor_id,
                envio=oferta.envio,
                alertou=acao is motor.Acao.REALERTAR,
                agora=agora,
            )
        elif acao is motor.Acao.FECHAR:
            repo.fechar_oportunidade(s, aberta, agora)
        if acao in (motor.Acao.ABRIR, motor.Acao.REALERTAR):
            mensagem = mensagem_oportunidade(
                nome_produto=linha.produto.nome,
                leitura=leitura,
                ref=ref,
                url_amazon=linha.anuncio.url,
                host=ctx.config.host_publico,
                produto_id=linha.produto.id,
            )
    if mensagem is not None:
        ctx.notificador.enviar(Destino.OPORTUNIDADES, mensagem)
