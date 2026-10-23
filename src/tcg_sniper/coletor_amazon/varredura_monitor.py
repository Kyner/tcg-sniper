"""Serviço `coletor-amazon`: retirada do carrinho, conferência de checkout e monitor de preço, no navegador
logado. Por passo, no máximo um trabalho, por prioridade: tirar do carrinho um item que ficou de uma
conferência, conferir no checkout uma candidata, ler as ofertas do anúncio confirmado mais atrasado. A
conferência e o monitor só dentro da janela do monitor e com o teto `monitor_max_paginas_hora` (somado, com
as páginas da retirada). A busca de anúncios novos é do serviço `coletor-amazon-busca` (este laço não a
importa nem a chama).

A retirada não espera janela nem teto (só o intervalo `ESPERA_RETIRADA` entre tentativas de cada
conferência, em rodízio): um item nosso no carrinho do usuário não pode ficar lá. Antes do clique em
adicionar, a conferência grava uma marca "em andamento" com `item_removido` False; se o processo morre no
meio, a primeira volta depois do reinício acha a marca; senão o resultado é gravado nessa linha.

A retirada automática só clica em Excluir com o carrinho exatamente como a conferência o deixou: só o ASIN
no carrinho ativo, contador 1, subtotal igual ao preço anunciado e marca de até `RETIRADA_AUTOMATICA_MAX`.
Em qualquer outro caso (ou depois de `MAX_TENTATIVAS_RETIRADA` falhas) não clica: a conferência fica
"conferir à mão", o grupo admin recebe um aviso (`AMAZON_CARRINHO`, um por ASIN) e o admin mostra o alerta
com "Já conferi". Com o monitor pausado, a retirada também para.

O monitor lê em grupos, nesta ordem: nunca lidos, fila rápida (oportunidade aberta ou desconto no piso do
"quase lá"), esgotados na Liga (relidos a cada `monitor_esgotado_dias`) e lentos (o resto, com a capacidade
que sobra). Rodada do monitor (`AMAZON_MONITOR_CONCLUIDO`) = uma volta da fila rápida: começa no primeiro
trabalho com a foto dos nunca lidos e da fila rápida (de anúncios confirmados, de produto ativo) e termina
quando cada um deles foi lido uma vez desde então (ou posto de lado por falha, ou saiu do monitor:
desconfirmado ou produto desativado), mesmo que outros já tenham vencido de novo; a volta seguinte começa no
próximo trabalho. Sem ninguém nessa foto não há volta (nem aviso). Lentos e esgotados lidos durante a volta
só entram na contagem à parte. Nunca fecha "a cada brecha" (uma volta de só os poucos vencidos naquele
instante). A janela que fecha no meio descarta a volta sem aviso."""

import dataclasses
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.avisos.formato import formatar_duracao
from tcg_sniper.coletor_amazon import checkout, monitor
from tcg_sniper.coletor_amazon.busca import CotaHtmlFalha, DesafioAmazon, abrir_pagina
from tcg_sniper.coletor_amazon.cliques import CliqueProibido, SeletorAusente, conta_logada, remover_do_carrinho
from tcg_sniper.coletor_amazon.config import aplicar_config
from tcg_sniper.coletor_amazon.parsers import URL_CARRINHO
from tcg_sniper.coletor_amazon.parsers_checkout import Carrinho, parse_carrinho
from tcg_sniper.coletor_amazon.varredura_base import (
    ESPERA_OCIOSA_S,
    MAX_FALHAS_SEGUIDAS,
    ORIGEM_MONITOR,
    VarreduraBase,
)
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import ConfigAmazon, EstadoColetorTipo, SituacaoCheckout
from tcg_sniper.navegador.base import NavegadorInterativo
from tcg_sniper.navegador.modelos import ErroRede
from tcg_sniper.parsing import ErroParser

log = logging.getLogger(__name__)

ESPERA_RETIRADA = timedelta(minutes=15)  # item nosso que não saiu do carrinho: nova tentativa
RETIRADA_AUTOMATICA_MAX = timedelta(minutes=30)  # marca mais velha que isso: só à mão (o carrinho pode ter mudado)
MAX_TENTATIVAS_RETIRADA = 3  # falhas da retirada automática antes de passar para "conferir à mão"
ERROS_DE_PAGINA = (ErroParser, ErroRede, CliqueProibido, SeletorAusente)
MOTIVO_EM_ANDAMENTO = "conferência em andamento (interrompida?): o item pode ter ficado no carrinho"


def linha_do_carrinho(asin: str) -> str:
    """Linha extra do aviso de CAPTCHA quando uma conferência pode ter deixado o item no carrinho."""
    minutos = int(RETIRADA_AUTOMATICA_MAX.total_seconds() // 60)
    return (
        f"Uma conferência deixou 1× {asin} no carrinho: sai sozinho se você retomar em até {minutos} min; "
        "senão confira à mão"
    )


def dados_conferir_a_mao(asin: str, razao: str) -> Dados:
    return Dados(
        titulo_extra=asin,
        linhas=(f"Pode haver 1× {asin} de uma conferência automática no carrinho", f"Motivo: {razao}"),
    )


DADOS_SEM_LOGIN = Dados(linhas=("A conferência de checkout parou; o monitor de preço continua",))


@dataclass
class _Rodada:
    """Uma volta do monitor: os anúncios acompanhados quando ela começou (`faltam`) até todos saírem."""

    inicio: datetime
    faltam: set[int] = field(default_factory=set)
    lidos: int = 0
    quedas: int = 0
    conferencias: int = 0
    falhas: int = 0  # leituras postas de lado por falha durante a volta
    lentos: int = 0  # lentos lidos com a capacidade que sobrou (fora da fila rápida)
    esgotados: int = 0  # esgotados na Liga relidos durante a volta


class _NavegadorContado:
    """Conta as páginas que o monitor abre (também as de uma leitura que falha no meio: o teto cobra
    todas). Só navega; o resto (inclusive o clique, que só `cliques.py` usa) vai direto ao navegador."""

    def __init__(self, navegador: NavegadorInterativo):
        self._navegador = navegador
        self.abertas = 0

    def abrir(self, url: str):
        self.abertas += 1
        return self._navegador.abrir(url)

    def abrir_e_esperar(self, url: str, seletor: str, timeout_ms: int = 15_000):
        self.abertas += 1
        return self._navegador.abrir_e_esperar(url, seletor, timeout_ms)

    def __getattr__(self, nome: str):
        return getattr(self._navegador, nome)


class VarreduraMonitor(VarreduraBase):
    origem = ORIGEM_MONITOR

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cota_falhas = CotaHtmlFalha()  # renovada uma vez por dia
        self._espera: dict[int, datetime] = {}  # anúncio que falhou -> não reler antes de
        self._limpeza_em: date | None = None
        self._rodada: _Rodada | None = None

    def inicializar(self) -> None:
        super().inicializar()
        with self._sessoes() as s, s.begin():
            presos = repo_amz.conferencias_com_item_no_carrinho(s)
        if presos:  # item que ficou de antes do reinício: a retirada roda já no primeiro passo
            log.warning("%d conferência(s) com item possivelmente no carrinho; tirando no primeiro passo", len(presos))

    def passo(self) -> float:
        """Faz no máximo um trabalho. Devolve quantos segundos dormir antes do próximo passo."""
        agora = self._relogio()
        cfg, estado = self._inicio_do_passo(agora)
        if estado is EstadoColetorTipo.ATIVO:
            try:
                espera = self._talvez_retirar(cfg)
            except DesafioAmazon as desafio:
                self._desafio(desafio.url)
                return ESPERA_OCIOSA_S
            if espera is not None:
                return espera
        if not self._janela(agora, "monitor", cfg.monitor_janela_inicio, cfg.monitor_janela_fim).contem(agora):
            self._rodada = None  # volta incompleta: sem aviso
            self.fechar_navegador()
            return ESPERA_OCIOSA_S
        if estado is not EstadoColetorTipo.ATIVO:
            self._rodada = None  # pausado: a volta aberta ficaria velha (início e duração errados)
            return ESPERA_OCIOSA_S
        self._limpar_uma_vez_por_dia(agora)
        if self._teto.liberado_em(agora, cfg.monitor_max_paginas_hora) is not None:
            return ESPERA_OCIOSA_S
        try:
            espera = self._passo_monitor(agora, cfg)
        except DesafioAmazon as desafio:
            self._desafio(desafio.url)
            return ESPERA_OCIOSA_S
        return ESPERA_OCIOSA_S if espera is None else espera

    def _desafio(self, url: str, asin_no_carrinho: str | None = None) -> None:
        self._registrar_desafio(url, (linha_do_carrinho(asin_no_carrinho),) if asin_no_carrinho else ())

    def _limpar_uma_vez_por_dia(self, agora: datetime) -> None:
        dia = agora.astimezone(self._config.zona).date()
        if self._limpeza_em == dia:
            return
        with self._sessoes() as s, s.begin():
            apagadas = repo_amz.limpar_ofertas_antigas(s, agora)
        if apagadas:
            log.info("%d ofertas lidas há mais de 30 dias apagadas", apagadas)
        self._limpeza_em = dia
        self._cota_falhas = CotaHtmlFalha()

    def _registrar_paginas(self, quantidade: int) -> None:
        agora = self._relogio()
        for _ in range(quantidade):
            self._teto.registrar(agora)

    # --- rodada ----------------------------------------------------------------------------------

    def _rodada_atual(self) -> _Rodada:
        if self._rodada is None:
            self._rodada = _Rodada(self._relogio())
        return self._rodada

    def _talvez_fechar_rodada(self, acompanhados: set[int]) -> None:
        """Tira da volta o que saiu do monitor sem ser lido; com a volta vazia, fecha (e avisa)."""
        if self._rodada is None:
            return
        self._rodada.faltam &= acompanhados
        if not self._rodada.faltam:
            self._fechar_rodada()

    def _fechar_rodada(self) -> None:
        rodada, self._rodada = self._rodada, None
        if rodada is None or (rodada.lidos == 0 and rodada.falhas == 0):
            return
        linhas = [
            f"Anúncios lidos: {rodada.lidos}",
            f"Preços em queda: {rodada.quedas}",
            f"Conferências de checkout: {rodada.conferencias}",
        ]
        if rodada.falhas:
            linhas.append(f"Falhas: {rodada.falhas}")
        if rodada.lentos or rodada.esgotados:
            linhas.append(f"Fora da fila rápida: {rodada.lentos} lentos · {rodada.esgotados} esgotados lidos")
        linhas.append(f"Duração: {formatar_duracao(self._relogio() - rodada.inicio)}")
        dados = Dados(linhas=tuple(linhas))
        self._avisador.avisar(TipoAviso.AMAZON_MONITOR_CONCLUIDO, CHAVE_GERAL, dados)

    def _por_de_lado(self, anuncio_id: int, cfg: ConfigAmazon) -> None:
        """Um anúncio que falha não prende o monitor: espera um intervalo e sai da volta atual."""
        self._espera[anuncio_id] = self._relogio() + timedelta(minutes=cfg.monitor_intervalo_min)
        if self._rodada is not None:
            self._rodada.faltam.discard(anuncio_id)
            self._rodada.falhas += 1

    # --- monitor, conferência e retirada ---------------------------------------------------------

    def _passo_monitor(self, agora: datetime, cfg: ConfigAmazon) -> float | None:
        """Um trabalho do monitor, por prioridade. None: nada a fazer agora."""
        self._espera = {k: v for k, v in self._espera.items() if v > agora}
        de_lado = set(self._espera)
        with self._sessoes() as s, s.begin():
            candidatas = []
            if cfg.checkout_ligado and cfg.checkout_sem_login_em is None and not repo_amz.carrinho_ocupado_ha_pouco(s, agora):
                candidatas = repo_amz.candidatas_ao_checkout(s, agora, cfg)
            proximo = None
            acompanhados: set[int] = set()
            if cfg.monitor_ligado:
                acompanhados = repo_amz.ids_da_volta(s, cfg.quase_oportunidade_min_pct)
                proximo = repo_amz.proximo_do_monitor(s, agora, cfg, de_lado)
        self._talvez_fechar_rodada(acompanhados)
        if not candidatas and proximo is None:
            return None
        if self._rodada is None and acompanhados:  # foto da volta: toda a fila rápida, não só os vencidos agora
            self._rodada = _Rodada(self._relogio(), faltam=set(acompanhados))
        if candidatas:
            return self._conferir(candidatas[0], cfg)
        return self._monitorar(proximo, cfg)

    def _talvez_retirar(self, cfg: ConfigAmazon) -> float | None:
        """Tenta tirar do carrinho o item de uma conferência que pode ter ficado lá (marca "em andamento" de
        um processo que morreu, ou retirada que falhou), uma conferência por passo, em rodízio e com
        `ESPERA_RETIRADA` entre tentativas da mesma. None: nada a tirar agora."""
        with self._sessoes() as s, s.begin():
            pendentes = repo_amz.conferencias_com_item_no_carrinho(s, self._relogio(), ESPERA_RETIRADA)
        if not pendentes:
            return None
        return self._retirar(pendentes[0], cfg)

    def _sem_clique(self, item: repo_amz.ItemNoCarrinho, estado: Carrinho) -> str | None:
        """Por que a retirada automática NÃO pode clicar (None: pode). Só com o carrinho exatamente como a
        conferência o deixou: um item do usuário com o mesmo ASIN nunca é excluído."""
        if self._relogio() - item.em > RETIRADA_AUTOMATICA_MAX:
            return f"marca com mais de {int(RETIRADA_AUTOMATICA_MAX.total_seconds() // 60)} min"
        if estado.asins_ativos != (item.asin,):
            return f"carrinho com outros itens ({', '.join(estado.asins_ativos)})"
        if estado.contador != 1:
            return f"quantidade no carrinho {estado.contador if estado.contador is not None else 'ilegível'}"
        if estado.subtotal != item.preco_anunciado:
            return f"subtotal {estado.subtotal if estado.subtotal is not None else 'ilegível'} diferente do anunciado {item.preco_anunciado}"
        return None

    def _conferir_a_mao(self, item: repo_amz.ItemNoCarrinho, razao: str) -> None:
        with self._sessoes() as s, s.begin():
            novo = repo_amz.marcar_conferir_a_mao(s, item.conferencia_id, self._relogio(), razao)
        log.warning("item %s da conferência %s fica para conferir à mão: %s", item.asin, item.conferencia_id, razao)
        if novo:
            self._avisador.avisar(TipoAviso.AMAZON_CARRINHO, item.asin, dados_conferir_a_mao(item.asin, razao))

    def _falha_na_retirada(self, item: repo_amz.ItemNoCarrinho, motivo: str) -> None:
        with self._sessoes() as s, s.begin():
            tentativas = repo_amz.registrar_tentativa_retirada(s, item.conferencia_id, self._relogio())
        log.warning("não deu para tirar %s do carrinho (tentativa %d): %s", item.asin, tentativas, motivo)
        if tentativas >= MAX_TENTATIVAS_RETIRADA:
            self._conferir_a_mao(item, f"{tentativas} tentativas de retirada falharam")

    def _retirar(self, item: repo_amz.ItemNoCarrinho, cfg: ConfigAmazon) -> float:
        ctx = self._contexto(cfg, f"amazon-carrinho-{item.asin}", self._cota_falhas)
        abertas = [0]

        def abrir(url: str):
            abertas[0] += 1  # conta também as páginas abertas antes de um erro (o teto cobra todas)
            return abrir_pagina(ctx, url)

        def contar_clique() -> None:
            abertas[0] += 1  # a página do clique em Excluir, também quando ele carrega e dá erro

        try:
            carrinho = abrir(URL_CARRINHO)
            try:
                estado = parse_carrinho(carrinho.html)
            except ErroParser as erro:  # login, erro ou layout novo: não prova nada
                self._falha_na_retirada(item, f"carrinho ilegível ({erro})")
                return 0
            if not conta_logada(carrinho):  # carrinho de visitante (sessão caída): não prova que saiu
                self._falha_na_retirada(item, "carrinho sem a conta logada; não prova que o item saiu")
                return 0
            if item.asin not in estado.asins_ativos:  # já saiu: resolve sem clicar
                with self._sessoes() as s, s.begin():
                    repo_amz.marcar_asin_removido(s, item.asin)
                self._avisador.resolver(TipoAviso.AMAZON_CARRINHO, item.asin)
                return 0
            razao = self._sem_clique(item, estado)
            if razao is not None:
                self._conferir_a_mao(item, razao)
                return 0
            removido, _ = remover_do_carrinho(
                ctx.navegador, item.asin, abrir, self._pausa_humana(cfg), carrinho, contar_clique=contar_clique
            )
        except ERROS_DE_PAGINA as erro:
            self._falha_na_retirada(item, str(erro))
            return 0
        except DesafioAmazon as desafio:
            with self._sessoes() as s, s.begin():  # não conta como falha: tenta de novo depois de retomar
                repo_amz.registrar_tentativa_retirada(s, item.conferencia_id, self._relogio(), contar=False)
            self._desafio(desafio.url, item.asin)  # o aviso diz qual item pode ter ficado
            return ESPERA_OCIOSA_S
        except Exception as erro:
            self._falha_na_retirada(item, repr(erro))
            raise
        finally:
            self._registrar_paginas(max(abertas[0], 1))
        if removido:  # carrinho ativo conferido sem o item: resolve as marcas desse ASIN
            with self._sessoes() as s, s.begin():
                repo_amz.marcar_asin_removido(s, item.asin)
            self._avisador.resolver(TipoAviso.AMAZON_CARRINHO, item.asin)
            return 0
        self._falha_na_retirada(item, "o item continua no carrinho depois de excluir")
        return 0

    def _conferir(self, candidata: repo_amz.CandidataCheckout, cfg: ConfigAmazon) -> float:
        self._rodada_atual().conferencias += 1
        ctx = self._contexto(cfg, f"amazon-checkout-{candidata.asin}", self._cota_falhas)
        alvo = checkout.AlvoCheckout(candidata.asin, candidata.vendedor_nome, candidata.preco_anunciado)
        marca: list[int] = []

        def marcar_em_andamento() -> None:
            # Gravada (e commitada) antes do clique em adicionar: se o processo morrer no meio, a
            # retirada do próximo passo (ou do próximo início) acha o item pela marca.
            with self._sessoes() as s, s.begin():
                marca.append(
                    repo_amz.registrar_conferencia(
                        s, em=self._relogio(), anuncio_id=candidata.anuncio_id, vendedor_nome=candidata.vendedor_nome,
                        preco_anunciado=candidata.preco_anunciado, itens=None, frete=None, impostos=None, total=None,
                        situacao=SituacaoCheckout.FALHA, motivo=MOTIVO_EM_ANDAMENTO, item_removido=False,
                    ).id
                )

        abertas = [0]

        def abrir(url: str):
            abertas[0] += 1
            return abrir_pagina(ctx, url)

        resultado = None
        try:
            resultado = checkout.conferir(ctx.navegador, alvo, abrir, self._pausa_humana(cfg), ao_adicionar=marcar_em_andamento)
        finally:  # um erro inesperado também conta as páginas abertas no teto do monitor
            self._registrar_paginas(resultado.paginas if resultado is not None else max(abertas[0], 1))
        agora = self._relogio()
        avisar_sem_login = False
        campos = {
            "em": agora, "itens": resultado.itens, "frete": resultado.frete, "impostos": resultado.impostos,
            "total": resultado.total, "situacao": resultado.situacao, "motivo": resultado.motivo,
            "item_removido": resultado.item_removido,
        }
        with self._sessoes() as s, s.begin():
            if marca:
                conferencia_id = repo_amz.concluir_conferencia(s, marca[0], **campos).id
            else:
                conferencia_id = repo_amz.registrar_conferencia(
                    s, anuncio_id=candidata.anuncio_id, vendedor_nome=candidata.vendedor_nome,
                    preco_anunciado=candidata.preco_anunciado, **campos,
                ).id
            if resultado.situacao is SituacaoCheckout.SEM_LOGIN and repo_amz.obter_config(s).checkout_sem_login_em is None:
                aplicar_config(s, {"checkout_sem_login_em": agora}, agora)
                avisar_sem_login = True
        log.info("conferência de checkout de %s: %s (%s)", candidata.asin, resultado.situacao.value, resultado.motivo or "ok")
        if avisar_sem_login:
            self._avisador.avisar(TipoAviso.AMAZON_SEM_LOGIN, CHAVE_GERAL, DADOS_SEM_LOGIN)
        elif resultado.situacao is not SituacaoCheckout.SEM_LOGIN:
            self._avisador.resolver(TipoAviso.AMAZON_SEM_LOGIN, CHAVE_GERAL)
        if resultado.situacao is SituacaoCheckout.OK:
            self._falhas_seguidas = 0
            monitor.aplicar_conferencia(ctx, candidata.anuncio_id, conferencia_id)
        else:  # sem conferência possível agora: a leitura atual decide já, com o preço anunciado
            monitor.redecidir(ctx, candidata.anuncio_id)
        if resultado.desafio_url is not None:
            self._desafio(resultado.desafio_url, None if resultado.item_removido else candidata.asin)
            return ESPERA_OCIOSA_S
        self._pagina_ok()
        return 0

    def _monitorar(self, proximo: repo_amz.ProximoMonitor, cfg: ConfigAmazon) -> float:
        anuncio_id, asin = proximo.anuncio_id, proximo.asin
        ctx = self._contexto(cfg, f"amazon-monitor-{asin}", self._cota_falhas)
        contado = _NavegadorContado(ctx.navegador)
        ctx = dataclasses.replace(ctx, navegador=contado)
        try:
            resultado = monitor.ler_anuncio(ctx, anuncio_id, asin)
        except ERROS_DE_PAGINA as erro:
            self._registrar_paginas(max(contado.abertas, 1))  # ofertas, perfis de vendedor e novas tentativas
            self._por_de_lado(anuncio_id, cfg)
            self._falhas_seguidas += 1
            log.warning("leitura das ofertas de %s falhou: %s", asin, erro)
            if self._falhas_seguidas >= MAX_FALHAS_SEGUIDAS:
                return self._pausar_por_falhas()
            return 0
        except DesafioAmazon:
            raise  # o anúncio continua na volta: é lido depois de retomar
        except Exception:
            # Um anúncio que quebra não pode prender o monitor nele: espera um intervalo e o erro sobe.
            self._por_de_lado(anuncio_id, cfg)
            raise
        self._registrar_paginas(resultado.paginas)
        self._falhas_seguidas = 0
        self._erros_seguidos = 0
        rodada = self._rodada  # aberta em `_passo_monitor`; None quando a fila rápida está vazia
        if rodada is not None:
            rodada.faltam.discard(anuncio_id)
            if proximo.grupo is repo_amz.GrupoMonitor.LENTO:
                rodada.lentos += 1
            elif proximo.grupo is repo_amz.GrupoMonitor.ESGOTADO:
                rodada.esgotados += 1
            else:
                rodada.lidos += 1
                rodada.quedas += resultado.caiu
        self._pagina_ok()
        return 0
