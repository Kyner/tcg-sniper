"""Monitor de preço: lê a lista de ofertas de um anúncio confirmado, grava todas as ofertas da leitura,
escolhe a melhor elegível (vira o preço atual do anúncio, origem `ofertas`), roda o motor com o preço
conferido no checkout (itens + impostos, sem o frete) quando há conferência válida para essa oferta e
avisa o grupo. Também aplica à oportunidade uma conferência de checkout ok recém-feita. Não conhece
fila nem janela (ver varredura_monitor.py).

Sem conferência válida e com uma conferência a caminho (conferência ligada, conta logada, carrinho sem
espera e a oferta é candidata ao checkout, sem falha nem ok da mesma oferta na validade), a leitura não
decide pelo preço anunciado: não abre, não avisa, não fecha nem realerta. Quem decide é
`aplicar_conferencia`, com o preço conferido, logo depois da conferência. O aviso com o preço anunciado
("não conferido (<motivo>)") só sai quando não há conferência possível; se ela falha, `redecidir` avisa
na hora com o anunciado (menos quando a oferta saiu do painel: aí a próxima leitura decide).

Leitura não elegível com oportunidade aberta só marca o risco; o encerramento (`oportunidades.encerramento`)
vem quando a carência vence."""

import dataclasses
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from tcg_sniper.avisos.catalogo import Dados, TipoAviso
from tcg_sniper.coletor_amazon.busca import ContextoBusca, DesafioAmazon, abrir_pagina, ler_pagina
from tcg_sniper.coletor_amazon.checkout import MOTIVO_OFERTA_SUMIU
from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon
from tcg_sniper.coletor_amazon.modelos import AvaliacaoVendedor, OfertaLista
from tcg_sniper.coletor_amazon.parsers import (
    SELETOR_PAINEL_OFERTAS,
    parse_ofertas,
    parse_produto_amazon,
    parse_vendedor,
    url_ofertas,
    url_produto,
    url_vendedor,
)
from tcg_sniper.db import repositorio_amazon as repo
from tcg_sniper.db.models import (
    AnuncioAmazon,
    ConferenciaCheckout,
    ConfigAmazon,
    Envio,
    OfertaAmazon,
    Oportunidade,
    OrigemPreco,
    PrecoAtualAmazon,
    PrecoAtualLiga,
    SituacaoCheckout,
    VendedorAmazon,
)
from tcg_sniper.navegador.modelos import Pagina
from tcg_sniper.navegador.ritmo import com_um_retry, pausa_aleatoria
from tcg_sniper.oportunidades import encerramento, motor
from tcg_sniper.oportunidades.mensagens import Detalhes, dados_oportunidade
from tcg_sniper.parsing import ErroParser

log = logging.getLogger(__name__)

ESPERA_OFERTAS_MS = 15_000


@dataclass(frozen=True)
class ResultadoMonitor:
    paginas: int  # páginas abertas: lista de ofertas, perfis de vendedor, página do produto
    ofertas: int
    melhor: OfertaLista | None  # a que virou o preço atual (None: nenhuma oferta nova)
    caiu: bool = False  # a melhor oferta ficou abaixo do preço atual anterior


@dataclass(frozen=True)
class _Avaliada:
    oferta: OfertaLista | OfertaAmazon  # OfertaAmazon: a melhor da leitura gravada (`redecidir`)
    vendedor: VendedorAmazon | None
    elegivel: bool


def preco_conferido(conferencia: ConferenciaCheckout) -> Decimal | None:
    """O preço que vale para a oportunidade quando há conferência: itens + impostos, SEM o frete
    (`motor.preco_conferido`, a única definição da regra)."""
    return motor.preco_conferido(conferencia.itens, conferencia.impostos, conferencia.total, conferencia.frete)


def _info(vendedor: VendedorAmazon | None) -> motor.Vendedor | None:
    if vendedor is None:
        return None
    return motor.Vendedor(vendedor.nome, vendedor.pct_positivas, vendedor.num_avaliacoes)


def _ref(liga: PrecoAtualLiga | None) -> motor.RefLiga:
    return motor.RefLiga(
        preco_a_partir=liga.preco_a_partir if liga else None,
        listagem_em=liga.listagem_em if liga else None,
        num_lojas=liga.num_lojas if liga else None,
        preco_medio=liga.preco_medio if liga else None,
    )


def abrir_ofertas(ctx: ContextoBusca, asin: str) -> Pagina:
    """Abre a lista de ofertas esperando os blocos do painel (o fragmento já os traz; a página do produto
    com ?aod=1 os carrega depois do load). Pausa humana, uma nova tentativa em erro de rede e para no
    CAPTCHA, como `abrir_pagina`."""
    url = url_ofertas(asin)
    pausa_aleatoria(ctx.cfg.pausa_min_s, ctx.cfg.pausa_max_s, ctx.dormir, ctx.rng)
    pagina = com_um_retry(
        lambda: ctx.navegador.abrir_e_esperar(url, SELETOR_PAINEL_OFERTAS, ESPERA_OFERTAS_MS), url, ctx.dormir
    )
    if eh_desafio_amazon(pagina):
        raise DesafioAmazon(url)
    return pagina


def _vendedor(ctx: ContextoBusca, oferta: OfertaLista) -> tuple[VendedorAmazon | None, int]:
    """Vendedor da oferta e quantas páginas abriu (0 ou 1). A avaliação mostrada no painel vale como a
    do perfil; sem ela, só um lojista FBA sem avaliação recente tem o perfil aberto (como antes). Perfil
    ilegível: o vendedor fica desconhecido (oferta inelegível) e as outras ofertas seguem."""
    with ctx.sessoes() as s, s.begin():
        if oferta.envio is Envio.AMAZON:
            return repo.vendedor_da_amazon(s), 0
        if oferta.seller_id is None:
            return None, 0
        if oferta.pct_positivas is not None and oferta.num_avaliacoes is not None:
            avaliacao = AvaliacaoVendedor(oferta.seller_id, oferta.vendedor_nome, oferta.pct_positivas, oferta.num_avaliacoes)
            return repo.gravar_vendedor(s, avaliacao, ctx.relogio()), 0
        conhecido = repo.obter_vendedor(s, oferta.seller_id)
    recente = (
        conhecido is not None
        and conhecido.avaliado_em is not None
        and ctx.relogio() - conhecido.avaliado_em < timedelta(days=ctx.cfg.vendedor_reavaliar_dias)
    )
    if oferta.envio is not Envio.FBA or recente:
        return conhecido, 0
    seller_id = oferta.seller_id
    pagina = abrir_pagina(ctx, url_vendedor(seller_id))
    try:
        avaliacao = ler_pagina(ctx, pagina, f"vendedor-{seller_id}", lambda html: parse_vendedor(html, seller_id))
    except ErroParser:
        log.warning("perfil do vendedor %s ilegível; a oferta dele fica inelegível nesta leitura", seller_id)
        return None, 1
    if avaliacao.nome is None:
        avaliacao = dataclasses.replace(avaliacao, nome=oferta.vendedor_nome)
    with ctx.sessoes() as s, s.begin():
        return repo.gravar_vendedor(s, avaliacao, ctx.relogio()), 1


def _indice_melhor(avaliadas: list[_Avaliada]) -> int | None:
    """A elegível mais barata (empate: a de menor posição); sem elegível, a nova mais barata (vira a
    referência do preço, sem alerta); sem oferta nova, nenhuma."""
    for aceita in (lambda a: a.elegivel, lambda a: a.oferta.condicao == "novo"):
        indices = [i for i, a in enumerate(avaliadas) if aceita(a)]
        if indices:
            return min(indices, key=lambda i: (avaliadas[i].oferta.preco, avaliadas[i].oferta.posicao))
    return None


def _ler_titulo(ctx: ContextoBusca, anuncio_id: int, asin: str) -> int:
    """Anúncio colado à mão ainda com o título provisório: lê a página do produto (título, variação, imagem)."""
    pagina = abrir_pagina(ctx, url_produto(asin))
    try:
        oferta = ler_pagina(ctx, pagina, f"produto-{asin}", lambda html: parse_produto_amazon(html, asin))
    except ErroParser:
        log.warning("página do produto %s ilegível; o título fica para a próxima leitura", asin)
        return 1
    with ctx.sessoes() as s, s.begin():
        repo.atualizar_leitura(s, anuncio_id, oferta.titulo, oferta.variacao, ctx.relogio(), oferta.imagem_url)
    return 1


def _conferencia_a_caminho(s: Session, cfg: ConfigAmazon, anuncio_id: int, agora: datetime) -> bool:
    """A melhor oferta da leitura atual vai ao checkout: conferência ligada, conta logada, carrinho sem
    a espera de "carrinho ocupado" e a oferta é candidata (sem conferência ok ou falha da mesma oferta
    na validade; `repo.candidatas_ao_checkout`)."""
    if not cfg.checkout_ligado or cfg.checkout_sem_login_em is not None:
        return False
    if repo.carrinho_ocupado_ha_pouco(s, agora):
        return False
    return bool(repo.candidatas_ao_checkout(s, agora, cfg, anuncio_id))


def _motivo_nao_conferido(s: Session, cfg: ConfigAmazon, anuncio_id: int, agora: datetime) -> str:
    if not cfg.checkout_ligado:
        return "conferência desligada"
    if cfg.checkout_sem_login_em is not None:
        return "conta Amazon sem login"
    if repo.carrinho_ocupado_ha_pouco(s, agora):
        return "seu carrinho tem itens"
    ultima = repo.ultima_conferencia(s, anuncio_id)
    if (
        ultima is not None
        and ultima.situacao is SituacaoCheckout.FALHA
        and agora - ultima.em < timedelta(hours=cfg.checkout_validade_h)
    ):
        return f"a conferência falhou: {ultima.motivo or 'sem motivo'}"
    return "aguardando conferência"


def _aberta_motor(aberta: Oportunidade | None) -> motor.Aberta | None:
    if aberta is None:
        return None
    return motor.Aberta(aberta.preco_alertado, aberta.preco_liga, aberta.em_risco_desde)


def _aplicar(
    s, decisao: motor.Decisao, aberta, linha, leitura, ref, vendedor_id, agora, conferido: bool
) -> Oportunidade | None:
    """Grava a decisão do motor. Devolve a oportunidade aberta ou atualizada (None em NADA, EM_RISCO e
    FECHAR). `conferido`: o preço da leitura é o conferido no checkout."""
    acao = decisao.acao
    if acao is motor.Acao.ABRIR:
        return repo.abrir_oportunidade(
            s, anuncio_id=linha.anuncio.id, produto_id=linha.produto.id, preco_amazon=leitura.preco,
            preco_liga=ref.preco_a_partir, desconto_pct=motor.desconto_pct(leitura.preco, ref.preco_a_partir),
            vendedor_id=vendedor_id, envio=leitura.envio, agora=agora, conferido=conferido,
        )
    if acao in (motor.Acao.REALERTAR, motor.Acao.ATUALIZAR, motor.Acao.RECUPERAR):
        repo.atualizar_oportunidade(
            s, aberta, preco_amazon=leitura.preco, preco_liga=ref.preco_a_partir,
            desconto_pct=motor.desconto_pct(leitura.preco, ref.preco_a_partir), vendedor_id=vendedor_id,
            envio=leitura.envio, alertou=acao is motor.Acao.REALERTAR, agora=agora, conferido=conferido,
        )
        return aberta
    if acao is motor.Acao.EM_RISCO:
        repo.marcar_risco(s, aberta, decisao.motivo, agora)
    elif acao is motor.Acao.FECHAR:
        encerramento.encerrar(s, aberta.id, decisao.motivo, agora)
    return None


def _dados(linha, leitura: motor.Leitura, ref: motor.RefLiga, detalhes: Detalhes) -> Dados:
    """`leitura.preco` já é o preço que vale (o conferido, quando há conferência): o "% abaixo da Liga"
    do título e a linha da Amazon falam do mesmo preço."""
    return dados_oportunidade(
        nome_produto=linha.produto.nome, variacao=linha.anuncio.variacao, leitura=leitura, ref=ref,
        url_amazon=linha.anuncio.url, detalhes=detalhes,
    )


def _decidir(ctx: ContextoBusca, anuncio_id: int, melhor: _Avaliada | None) -> None:
    agora = ctx.relogio()
    with ctx.sessoes() as s, s.begin():
        linhas = repo.confirmados_com_referencia(s, [anuncio_id])
        if not linhas:  # o casamento foi desfeito no admin enquanto a página abria
            return
        linha = linhas[0]
        ref = _ref(linha.liga)
        oferta = melhor.oferta if melhor else None
        conferencia = None
        if oferta is not None:
            conferencia = repo.conferencia_valida(
                s, anuncio_id, oferta.vendedor_nome, oferta.preco, agora, ctx.cfg.checkout_validade_h
            )
        conferido = preco_conferido(conferencia) if conferencia is not None else None
        if conferido is None:
            conferencia = None
        if conferencia is None and oferta is not None and _conferencia_a_caminho(s, ctx.cfg, anuncio_id, agora):
            # Nem abre/avisa nem fecha/realerta pelo anunciado: `aplicar_conferencia` decide com o conferido.
            log.info("anúncio %s: conferência de checkout a caminho; a decisão espera por ela", anuncio_id)
            return
        # Com conferência válida vale o preço conferido (itens + impostos, sem o frete).
        preco = conferido if conferido is not None else (oferta.preco if oferta else None)
        leitura = motor.Leitura(preco, oferta.envio if oferta else Envio.DESCONHECIDO, _info(melhor.vendedor) if melhor else None)
        aberta = repo.oportunidade_aberta(s, anuncio_id)
        decisao = motor.decidir(leitura, ref, motor.Regras.de(ctx.cfg), agora, _aberta_motor(aberta))
        if decisao.acao is motor.Acao.REALERTAR and conferido is None and aberta.alerta_conferido:
            # O último aviso foi com o conferido; o anunciado não tem os impostos e parece mais barato:
            # só atualiza, sem aviso, até haver um novo preço conferido.
            decisao = motor.Decisao(motor.Acao.ATUALIZAR)
        vendedor_id = melhor.vendedor.id if melhor and melhor.vendedor else None
        op = _aplicar(s, decisao, aberta, linha, leitura, ref, vendedor_id, agora, conferido is not None)
        if decisao.acao in (motor.Acao.ABRIR, motor.Acao.REALERTAR):
            selos = Detalhes(
                importada=oferta.importada, origem_envio=oferta.origem_envio, prime=oferta.prime,
                cupom=getattr(oferta, "cupom", None),  # a oferta gravada (OfertaAmazon) não guarda o cupom
            )
            if conferencia is not None:
                detalhes = dataclasses.replace(
                    selos, preco_conferido=conferido, impostos=conferencia.impostos, frete=conferencia.frete
                )
            else:
                motivo = _motivo_nao_conferido(s, ctx.cfg, anuncio_id, agora)
                detalhes = dataclasses.replace(selos, motivo_nao_conferido=motivo)
            aviso = _dados(linha, leitura, ref, detalhes)
            op.mensagem_alerta_id = ctx.avisador.avisar_em(s, TipoAviso.OPORTUNIDADE, str(anuncio_id), aviso)
            s.flush()


def ler_anuncio(ctx: ContextoBusca, anuncio_id: int, asin: str) -> ResultadoMonitor:
    """Lê as ofertas do anúncio e decide a oportunidade. Lança DesafioAmazon, ErroParser (painel
    ilegível; HTML salvo) ou ErroRede."""
    pagina = abrir_ofertas(ctx, asin)
    ofertas = ler_pagina(ctx, pagina, f"ofertas-{asin}", parse_ofertas)
    paginas = 1
    regras = motor.Regras.de(ctx.cfg)
    avaliadas = []
    for oferta in ofertas:
        vendedor, abertas = _vendedor(ctx, oferta)
        paginas += abertas
        elegivel = oferta.condicao == "novo" and motor.vendedor_elegivel(oferta.envio, _info(vendedor), regras)
        avaliadas.append(_Avaliada(oferta, vendedor, elegivel))
    indice = _indice_melhor(avaliadas)
    melhor = avaliadas[indice] if indice is not None else None
    agora = ctx.relogio()
    with ctx.sessoes() as s, s.begin():
        anterior = s.get(PrecoAtualAmazon, anuncio_id)
        preco_anterior = anterior.preco if anterior is not None else None
        repo.gravar_ofertas(
            s, anuncio_id, agora,
            [
                repo.OfertaAvaliada(a.oferta, a.vendedor.id if a.vendedor else None, a.elegivel, i == indice)
                for i, a in enumerate(avaliadas)
            ],
        )
        repo.registrar_preco(
            s, anuncio_id, melhor.oferta.preco if melhor else None, OrigemPreco.OFERTAS,
            melhor.vendedor.id if melhor and melhor.vendedor else None,
            melhor.oferta.envio if melhor else Envio.DESCONHECIDO, agora, ctx.config.zona,
        )
        repo.marcar_visto(s, anuncio_id, agora)
        anuncio = s.get(AnuncioAmazon, anuncio_id)
        titulo_provisorio = anuncio is not None and anuncio.titulo == repo.TITULO_MANUAL
    _decidir(ctx, anuncio_id, melhor)  # antes do título: a página do produto falhar não pula a decisão
    if titulo_provisorio:
        paginas += _ler_titulo(ctx, anuncio_id, asin)
    novo = melhor.oferta.preco if melhor else None
    caiu = preco_anterior is not None and novo is not None and novo < preco_anterior
    return ResultadoMonitor(paginas, len(ofertas), melhor.oferta if melhor else None, caiu)


def redecidir(ctx: ContextoBusca, anuncio_id: int) -> None:
    """Conferência que não deu ok (falha, carrinho ocupado, sem login): refaz na hora a decisão da
    leitura atual, que agora não espera mais conferência e usa o preço anunciado ("não conferido
    (<motivo>)"). Sem leitura atual de ofertas, ou quando a conferência falhou porque a oferta não está
    mais no painel (o anunciado da leitura já não vale), não faz nada: a próxima leitura decide."""
    with ctx.sessoes() as s:
        ultima = repo.ultima_conferencia(s, anuncio_id)
        if ultima is not None and ultima.situacao is SituacaoCheckout.FALHA and ultima.motivo == MOTIVO_OFERTA_SUMIU:
            log.info("anúncio %s: a oferta saiu do painel; a próxima leitura decide", anuncio_id)
            return
        cfg = repo.obter_config(s)  # a conferência pode ter acabado de marcar a conta sem login
        lidas = repo.ofertas_da_ultima_leitura(s, [anuncio_id]).get(anuncio_id, [])
        melhor = next((o for o in lidas if o.melhor), None)
        if melhor is None:
            return
        vendedor = s.get(VendedorAmazon, melhor.vendedor_id) if melhor.vendedor_id else None
    _decidir(dataclasses.replace(ctx, cfg=cfg), anuncio_id, _Avaliada(melhor, vendedor, melhor.elegivel))


def aplicar_conferencia(ctx: ContextoBusca, anuncio_id: int, conferencia_id: int) -> None:
    """Conferência ok recém-gravada: refaz a decisão com o preço conferido (itens + impostos, sem o
    frete). Sem oportunidade aberta, abre e avisa (com o preço conferido) se ele ainda dá o desconto;
    com uma aberta, atualiza, realerta (o conferido caiu o bastante; com aviso) ou fecha. Só vale para a
    mesma oferta da leitura atual de ofertas (preço atual de origem `ofertas`; anúncio, vendedor e preço
    da melhor oferta), ok e dentro da validade: é preciso que `repo.conferencia_valida` devolva esta
    conferência. Senão não faz nada (a próxima leitura decide)."""
    agora = ctx.relogio()
    with ctx.sessoes() as s, s.begin():
        conferencia = s.get(ConferenciaCheckout, conferencia_id)
        linhas = repo.confirmados_com_referencia(s, [anuncio_id])
        if (
            conferencia is None
            or conferencia.anuncio_id != anuncio_id
            or conferencia.situacao is not SituacaoCheckout.OK
            or not linhas
        ):
            return
        linha = linhas[0]
        lidas = repo.ofertas_da_ultima_leitura(s, [anuncio_id]).get(anuncio_id, [])
        melhor = next((o for o in lidas if o.melhor), None)
        if melhor is None or linha.atual.preco is None or linha.atual.origem is not OrigemPreco.OFERTAS:
            return
        valida = repo.conferencia_valida(
            s, anuncio_id, melhor.vendedor_nome, linha.atual.preco, agora, ctx.cfg.checkout_validade_h
        )
        conferido = preco_conferido(conferencia)
        if valida is None or valida.id != conferencia.id or conferido is None:
            return
        ref = _ref(linha.liga)
        vendedor = s.get(VendedorAmazon, linha.atual.vendedor_id) if linha.atual.vendedor_id else None
        leitura = motor.Leitura(conferido, linha.atual.envio, _info(vendedor))
        aberta = repo.oportunidade_aberta(s, anuncio_id)
        decisao = motor.decidir(leitura, ref, motor.Regras.de(ctx.cfg), agora, _aberta_motor(aberta))
        op = _aplicar(s, decisao, aberta, linha, leitura, ref, linha.atual.vendedor_id, agora, True)
        if decisao.acao in (motor.Acao.ABRIR, motor.Acao.REALERTAR):
            detalhes = Detalhes(
                preco_conferido=conferido, impostos=conferencia.impostos, frete=conferencia.frete,
                importada=melhor.importada, origem_envio=melhor.origem_envio, prime=melhor.prime,
            )
            aviso = _dados(linha, leitura, ref, detalhes)
            op.mensagem_alerta_id = ctx.avisador.avisar_em(s, TipoAviso.OPORTUNIDADE, str(anuncio_id), aviso)
            s.flush()
