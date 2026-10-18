"""Conferência de checkout: põe uma oferta no carrinho, vai até o resumo do pedido (sem confirmar), lê
itens, frete, impostos e total, e tira o item do carrinho. Todo clique passa por
`cliques.clicar_permitido`; nada aqui confirma pedido nem usa "Comprar agora". Com qualquer item no
carrinho ativo, não clica em nada. Não grava no banco: a varredura registra a `conferencia_checkout`
(itens, frete, impostos e total separados) e aplica o resultado à oportunidade.

Preço conferido da oportunidade (regra do usuário, 2026-10-17): itens + impostos, SEM o frete
(`ResultadoCheckout.preco_conferido`, que usa `motor.preco_conferido`, a única definição).

Depois que o item pode ter entrado no carrinho, nenhum erro (nem um inesperado) pula a retirada: vira
`falha` com o motivo e o item sai. `ao_adicionar` é chamado logo antes do clique em adicionar (a
varredura grava ali a marca de "conferência em andamento" que garante a retirada mesmo se o processo
morrer no meio)."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from tcg_sniper.coletor_amazon.busca import DesafioAmazon
from tcg_sniper.coletor_amazon.cliques import (
    ADICIONAR,
    ENTREGAR,
    ESCOPO_OFERTA_DESTAQUE,
    ESCOPO_OFERTA_LISTA,
    FECHAR_PEDIDO,
    Acao,
    CliqueProibido,
    SeletorAusente,
    clicar_permitido,
    localizar,
    remover_do_carrinho,
)
from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon
from tcg_sniper.coletor_amazon.modelos import OfertaLista
from tcg_sniper.coletor_amazon.parsers import SELETOR_PAINEL_OFERTAS, URL_CARRINHO, parse_ofertas, url_painel_ofertas
from tcg_sniper.coletor_amazon.parsers_checkout import (
    Etapa,
    ResumoCheckout,
    contador_do_carrinho,
    eh_login,
    parse_carrinho,
    parse_resumo_checkout,
)
from tcg_sniper.db.models import SituacaoCheckout
from tcg_sniper.navegador.base import NavegadorInterativo
from tcg_sniper.navegador.modelos import ErroRede, Pagina
from tcg_sniper.oportunidades import motor
from tcg_sniper.parsing import ErroParser

log = logging.getLogger(__name__)

ERROS_DO_PASSO = (CliqueProibido, SeletorAusente, ErroParser, ErroRede)
MAX_ITENS_SOBRE_ANUNCIADO = Decimal("1.5")  # itens do resumo acima disso × o anunciado: mais de uma unidade
# A oferta da leitura não está mais no painel: o preço anunciado dela já não vale (o monitor não avisa por ele).
MOTIVO_OFERTA_SUMIU = "a oferta não está mais no painel (preço ou vendedor mudou)"


@dataclass(frozen=True)
class AlvoCheckout:
    asin: str
    vendedor_nome: str | None
    preco_anunciado: Decimal


@dataclass(frozen=True)
class ResultadoCheckout:
    situacao: SituacaoCheckout
    motivo: str | None
    itens: Decimal | None = None
    frete: Decimal | None = None  # None: frete não lido, nunca zero
    impostos: Decimal | None = None
    total: Decimal | None = None
    item_removido: bool = True  # False: o item pode ter ficado no carrinho (a varredura tenta de novo)
    paginas: int = 0
    desafio_url: str | None = None  # CAPTCHA no meio: a varredura pausa a Amazon

    @property
    def preco_conferido(self) -> Decimal | None:
        """Preço que vale para a oportunidade: itens + impostos, sem o frete (`motor.preco_conferido`).
        None fora de uma conferência ok ou sem valores lidos."""
        if self.situacao is not SituacaoCheckout.OK:
            return None
        return motor.preco_conferido(self.itens, self.impostos, self.total, self.frete)


class _Parada(Exception):
    def __init__(self, situacao: SituacaoCheckout, motivo: str):
        super().__init__(motivo)
        self.situacao, self.motivo = situacao, motivo


def _achar(ofertas: list[OfertaLista], alvo: AlvoCheckout) -> OfertaLista | None:
    return next(
        (
            o for o in ofertas
            if o.condicao == "novo" and o.preco == alvo.preco_anunciado and o.vendedor_nome == alvo.vendedor_nome
        ),
        None,
    )


def _escopo(oferta: OfertaLista) -> tuple[str, int]:
    """Bloco do painel onde está o botão da oferta: a destacada ou o n-ésimo #aod-offer."""
    if oferta.posicao == 0:
        return ESCOPO_OFERTA_DESTAQUE, 0
    return ESCOPO_OFERTA_LISTA, oferta.posicao - 1


def _conferir_fechamento(resumo: ResumoCheckout) -> None:
    """O resumo precisa fechar no centavo: itens + frete + impostos == total (frete ou impostos não
    lidos contam zero). Uma linha que a leitura perdeu (rótulo novo dos impostos, por exemplo) não pode
    virar preço conferido: vira falha."""
    frete = resumo.frete if resumo.frete is not None else Decimal(0)
    impostos = resumo.impostos if resumo.impostos is not None else Decimal(0)
    if resumo.itens + frete + impostos != resumo.total:
        raise _Parada(
            SituacaoCheckout.FALHA,
            f"resumo não fecha: itens {resumo.itens} + frete {frete} + impostos {impostos} ≠ total {resumo.total}",
        )


def conferir(
    nav: NavegadorInterativo,
    alvo: AlvoCheckout,
    abrir: Callable[[str], Pagina],
    pausar: Callable[[], None],
    ao_adicionar: Callable[[], None] | None = None,
) -> ResultadoCheckout:
    paginas = 0
    adicionou = False
    resumo: ResumoCheckout | None = None
    situacao, motivo, desafio = SituacaoCheckout.OK, None, None

    def abrir_contando(url: str) -> Pagina:
        nonlocal paginas
        paginas += 1
        return abrir(url)

    def clicar(acao: Acao, pagina: Pagina, escopo: str = "", bloco: int = 0) -> Pagina:
        nonlocal paginas
        pausar()
        try:
            resultado = clicar_permitido(nav, acao, pagina, escopo, bloco)
        except (CliqueProibido, SeletorAusente):
            raise  # recusado antes do clique: nenhuma página carregou, não conta no teto
        except Exception:
            paginas += 1  # o clique pode ter carregado uma página antes do erro
            raise
        paginas += 1
        return resultado

    try:
        carrinho = abrir_contando(URL_CARRINHO)
        if eh_login(carrinho):
            raise _Parada(SituacaoCheckout.SEM_LOGIN, "a Amazon pediu login no carrinho")
        try:
            estado = parse_carrinho(carrinho.html)
        except ErroParser as erro:  # sem o bloco do carrinho ativo: não prova carrinho vazio
            raise _Parada(SituacaoCheckout.FALHA, f"carrinho ilegível; nada foi clicado ({erro})") from erro
        if estado.contador is None:
            raise _Parada(SituacaoCheckout.FALHA, "contador do carrinho ilegível; nada foi clicado")
        if estado.contador or estado.asins_ativos:
            itens = estado.contador or len(estado.asins_ativos)  # contador zerado com itens ativos: conta os itens
            raise _Parada(SituacaoCheckout.CARRINHO_OCUPADO, f"{itens} item(ns) no carrinho; nada foi clicado")
        url = url_painel_ofertas(alvo.asin)
        pausar()
        paginas += 1
        painel = nav.abrir_e_esperar(url, SELETOR_PAINEL_OFERTAS)
        if eh_desafio_amazon(painel):
            raise DesafioAmazon(url)
        oferta = _achar(parse_ofertas(painel.html), alvo)
        if oferta is None:
            raise _Parada(SituacaoCheckout.FALHA, MOTIVO_OFERTA_SUMIU)
        # Relê o carrinho logo antes do clique, na própria página do painel (a que precisa estar na tela
        # para o clique): o usuário pode ter posto algo no carrinho depois da primeira leitura.
        contador = contador_do_carrinho(painel.html)
        if contador is None:
            raise _Parada(SituacaoCheckout.FALHA, "contador do carrinho ilegível no painel; nada foi clicado")
        if contador:
            raise _Parada(
                SituacaoCheckout.CARRINHO_OCUPADO, f"{contador} item(ns) no carrinho ao abrir o painel; nada foi clicado"
            )
        if ao_adicionar is not None:
            ao_adicionar()  # se falhar (banco fora), sobe sem clicar: nada foi adicionado
        adicionou = True  # daqui em diante pode haver item nosso no carrinho, mesmo se o clique der erro
        clicar(ADICIONAR, painel, *_escopo(oferta))
        carrinho = abrir_contando(URL_CARRINHO)
        if eh_login(carrinho):
            raise _Parada(SituacaoCheckout.SEM_LOGIN, "a Amazon pediu login ao reabrir o carrinho")
        estado = parse_carrinho(carrinho.html)
        if estado.asins_ativos != (alvo.asin,):
            raise _Parada(
                SituacaoCheckout.FALHA,
                f"carrinho inesperado depois de adicionar: {', '.join(estado.asins_ativos) or 'vazio'}",
            )
        if estado.contador not in (1, None):
            raise _Parada(SituacaoCheckout.FALHA, f"quantidade inesperada no carrinho depois de adicionar: {estado.contador}")
        if estado.contador is None and estado.subtotal is None:
            # Sem contador e sem subtotal nada prova que entrou uma unidade só: não segue ao checkout.
            raise _Parada(SituacaoCheckout.FALHA, "quantidade ilegível no carrinho depois de adicionar (sem contador e sem subtotal)")
        if estado.subtotal is not None and estado.subtotal != alvo.preco_anunciado:
            raise _Parada(
                SituacaoCheckout.FALHA, f"subtotal do carrinho R$ {estado.subtotal} diferente do anunciado R$ {alvo.preco_anunciado}"
            )
        pagina = clicar(FECHAR_PEDIDO, carrinho)
        resumo = parse_resumo_checkout(pagina)
        # Passo do endereço, ou um passo desconhecido com o botão de entregar no lugar: a guarda do
        # clique confere o rótulo e a lista proibida (um "Confirmar pedido" ali vira CliqueProibido).
        if resumo.etapa is Etapa.ENDERECO or (resumo.etapa is Etapa.DESCONHECIDA and localizar(ENTREGAR, pagina) is not None):
            pagina = clicar(ENTREGAR, pagina)
            resumo = parse_resumo_checkout(pagina)
        if resumo.etapa is Etapa.LOGIN:
            raise _Parada(SituacaoCheckout.SEM_LOGIN, "o checkout pediu login")
        if resumo.etapa is not Etapa.RESUMO:
            raise _Parada(SituacaoCheckout.FALHA, f"passo inesperado no checkout ({pagina.url})")
        if resumo.itens is not None and resumo.itens > alvo.preco_anunciado * MAX_ITENS_SOBRE_ANUNCIADO:
            raise _Parada(
                SituacaoCheckout.FALHA,
                f"quantidade suspeita: itens R$ {resumo.itens} no resumo para o anunciado R$ {alvo.preco_anunciado}",
            )
        _conferir_fechamento(resumo)
    except _Parada as parada:
        situacao, motivo = parada.situacao, parada.motivo
    except DesafioAmazon as erro:
        situacao, motivo, desafio = SituacaoCheckout.FALHA, f"CAPTCHA em {erro.url}", erro.url
    except ERROS_DO_PASSO as erro:
        situacao, motivo = SituacaoCheckout.FALHA, str(erro)
    except Exception as erro:
        if not adicionou:
            raise  # nada no carrinho: o erro inesperado sobe (a varredura trata)
        log.exception("erro inesperado na conferência de %s; tirando o item do carrinho", alvo.asin)
        situacao, motivo = SituacaoCheckout.FALHA, repr(erro)

    removido = not adicionou
    if adicionou and desafio is None:
        try:
            removido, abertas = remover_do_carrinho(nav, alvo.asin, abrir, pausar)
            paginas += abertas
        except DesafioAmazon as erro:
            desafio = erro.url
        except ERROS_DO_PASSO as erro:
            log.warning("não deu para tirar %s do carrinho: %s", alvo.asin, erro)
        except Exception:  # a varredura tenta de novo pela marca de item no carrinho
            log.exception("erro inesperado ao tirar %s do carrinho", alvo.asin)
    if not removido:
        motivo = f"{motivo}; o item pode ter ficado no carrinho" if motivo else "o item pode ter ficado no carrinho"
    if situacao is not SituacaoCheckout.OK or resumo is None:
        return ResultadoCheckout(situacao, motivo, item_removido=removido, paginas=paginas, desafio_url=desafio)
    return ResultadoCheckout(
        situacao, motivo, resumo.itens, resumo.frete, resumo.impostos, resumo.total, removido, paginas, desafio
    )
