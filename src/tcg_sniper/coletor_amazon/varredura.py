"""Coletor da Amazon: um navegador, três trabalhos. Por prioridade, a cada passo: tirar do carrinho um
item que ficou de uma conferência, conferir no checkout uma candidata, ler as ofertas do anúncio
confirmado mais atrasado (monitor) e, por último, a descoberta (fila de buscas). A conferência e o
monitor só dentro da janela do monitor e com o teto `monitor_max_paginas_hora` (somado, com as páginas
da retirada); a descoberta dentro da janela da busca, com o teto `max_buscas_hora`.

A retirada não espera janela nem teto (só o intervalo `ESPERA_RETIRADA` entre tentativas de cada
conferência, em rodízio): um item nosso no carrinho do usuário não pode ficar lá. Antes do clique em
adicionar, a conferência grava uma marca "em andamento" com `item_removido` False; se o processo morre
no meio, a primeira volta depois do reinício acha a marca; senão o resultado é gravado nessa linha.

A retirada automática só clica em Excluir com o carrinho exatamente como a conferência o deixou: só o
ASIN no carrinho ativo, contador 1, subtotal igual ao preço anunciado e marca de até
`RETIRADA_AUTOMATICA_MAX`. Em qualquer outro caso (ou depois de `MAX_TENTATIVAS_RETIRADA` falhas) não
clica: a conferência fica "conferir à mão", o grupo admin recebe um aviso (uma vez por conferência,
gravado no banco) e o admin mostra o alerta com "Já conferi". Com a Amazon pausada, a retirada também
para."""

import dataclasses
import logging
import random
import time as relogio_sistema
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.coletor_amazon import checkout, monitor
from tcg_sniper.coletor_amazon.busca import (
    ContextoBusca,
    CotaHtmlFalha,
    DesafioAmazon,
    abrir_pagina,
    processar_produto,
)
from tcg_sniper.coletor_amazon.cliques import CliqueProibido, SeletorAusente, conta_logada, remover_do_carrinho
from tcg_sniper.coletor_amazon.config import aplicar_config
from tcg_sniper.coletor_amazon.fila import Janela, TetoPorHora, intervalo_busca, janela_do_dia
from tcg_sniper.coletor_amazon.parsers import URL_CARRINHO
from tcg_sniper.coletor_amazon.parsers_checkout import Carrinho, parse_carrinho
from tcg_sniper.coletor_amazon.termo import termo_busca
from tcg_sniper.coletor_liga.agendador import lock_coleta
from tcg_sniper.config import Config
from tcg_sniper.config_banco import carregar_config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    ConfigAmazon,
    EstadoColetorTipo,
    ProdutoLiga,
    SituacaoCheckout,
    StatusColeta,
    TipoColeta,
)
from tcg_sniper.navegador.base import NavegadorInterativo
from tcg_sniper.navegador.modelos import ErroRede
from tcg_sniper.navegador.ritmo import pausa_aleatoria
from tcg_sniper.notificador.base import Destino, Notificador
from tcg_sniper.parsing import ErroParser

log = logging.getLogger(__name__)

ID_LOCK_AMAZON = 7_202_611
TIPOS_AMAZON = (TipoColeta.AMAZON,)
ESPERA_OCIOSA_S = 60
ESPERA_ERRO_S = 15 * 60
MAX_ERROS_SEGUIDOS = 3
MAX_FALHAS_SEGUIDAS = 10  # páginas seguidas com ErroParser/ErroRede (bloqueio ou layout novo)
ESPERA_RETIRADA = timedelta(minutes=15)  # item nosso que não saiu do carrinho: nova tentativa
RETIRADA_AUTOMATICA_MAX = timedelta(minutes=30)  # marca mais velha que isso: só à mão (o carrinho pode ter mudado)
MAX_TENTATIVAS_RETIRADA = 3  # falhas da retirada automática antes de passar para "conferir à mão"
ERROS_DE_PAGINA = (ErroParser, ErroRede, CliqueProibido, SeletorAusente)
MOTIVO_EM_ANDAMENTO = "conferência em andamento (interrompida?): o item pode ter ficado no carrinho"


def mensagem_captcha(config: Config, url: str, asin_no_carrinho: str | None = None) -> str:
    texto = (
        f"CAPTCHA na Amazon ({url}). Resolver em http://{config.host_publico}:6081/vnc.html "
        f"e depois clicar em Retomar (Amazon) em http://{config.host_publico}:8000"
    )
    if asin_no_carrinho is not None:
        texto += (
            f". Uma conferência deixou 1× {asin_no_carrinho} no carrinho; ele sai se você retomar em até "
            f"{int(RETIRADA_AUTOMATICA_MAX.total_seconds() // 60)} min; senão confira à mão"
        )
    return texto


def mensagem_conferir_a_mao(config: Config, asin: str) -> str:
    return (
        f"Confira o carrinho da Amazon: pode haver 1× {asin} de uma conferência automática; tire à mão pelo "
        f"noVNC em http://{config.host_publico}:6081/vnc.html se não for seu."
    )


def mensagem_sem_login(config: Config) -> str:
    return (
        "A conta Amazon do coletor está sem login: a conferência de checkout parou (o monitor de preço continua). "
        f"Logue a conta Amazon no noVNC, porta 6081: http://{config.host_publico}:6081/vnc.html, e depois clique em "
        f"Retomar conferência em http://{config.host_publico}:8000/servicos"
    )


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


class VarreduraAmazon:
    def __init__(
        self,
        engine: Engine,
        sessoes: sessionmaker[Session],
        fabrica_navegador: Callable[[], AbstractContextManager[NavegadorInterativo]],
        notificador: Notificador,
        config: Config,
        relogio: Callable[[], datetime] | None = None,
        rng: random.Random | None = None,
        dormir: Callable[[float], None] = relogio_sistema.sleep,
    ):
        self._engine = engine
        self._sessoes = sessoes
        self._fabrica_navegador = fabrica_navegador
        self._notificador = notificador
        self._config_env = config
        self._config = config
        self._relogio = relogio or (lambda: datetime.now(UTC))
        self._rng = rng or random.Random()
        self._dormir = dormir
        self._janelas: dict[tuple[str, date, time, time, str], Janela] = {}
        self._teto = TetoPorHora()  # buscas da descoberta
        self._teto_monitor = TetoPorHora()  # páginas do monitor, da conferência e da retirada, somadas
        self._ciclo: int | None = None
        self._pendentes: set[int] = set()
        self._ok = 0
        self._falha = 0
        self._erros_seguidos = 0
        self._falhas_seguidas = 0
        self._cota_falhas = CotaHtmlFalha()
        self._cota_falhas_monitor = CotaHtmlFalha()
        self._espera_monitor: dict[int, datetime] = {}  # anúncio que falhou -> não reler antes de
        self._limpeza_em: date | None = None
        self._contexto_navegador: AbstractContextManager[NavegadorInterativo] | None = None
        self._navegador: NavegadorInterativo | None = None

    # --- navegador ---------------------------------------------------------------------------

    def _obter_navegador(self) -> NavegadorInterativo:
        if self._navegador is not None:
            if self._navegador.vivo():
                return self._navegador
            log.warning("navegador da Amazon não responde; abrindo outro")
            self.fechar_navegador()
        contexto = self._fabrica_navegador()
        self._navegador = contexto.__enter__()
        self._contexto_navegador = contexto
        return self._navegador

    def fechar_navegador(self) -> None:
        contexto = self._contexto_navegador
        self._contexto_navegador = self._navegador = None
        if contexto is None:
            return
        try:
            contexto.__exit__(None, None, None)
        except Exception:  # instância possivelmente morta: só registra
            log.warning("erro ao fechar o navegador da Amazon", exc_info=True)

    def _contexto(self, cfg: ConfigAmazon, nome_falha: str, cota: CotaHtmlFalha) -> ContextoBusca:
        return ContextoBusca(
            sessoes=self._sessoes,
            navegador=self._obter_navegador(),
            notificador=self._notificador,
            config=self._config,
            cfg=cfg,
            relogio=self._relogio,
            dormir=self._dormir,
            rng=self._rng,
            nome_falha=nome_falha,
            cota_falhas=cota,
        )

    def _pausar(self, cfg: ConfigAmazon) -> Callable[[], None]:
        return lambda: pausa_aleatoria(cfg.pausa_min_s, cfg.pausa_max_s, self._dormir, self._rng)

    def _registrar_paginas(self, quantidade: int) -> None:
        agora = self._relogio()
        for _ in range(quantidade):
            self._teto_monitor.registrar(agora)

    # --- ciclo da descoberta -------------------------------------------------------------------

    def _iniciar_ciclo(self, agora: datetime, na_fila: set[int]) -> None:
        with self._sessoes() as s, s.begin():
            self._ciclo = repo.iniciar_coleta(s, TipoColeta.AMAZON, agora).id
        self._pendentes = set(na_fila)
        self._ok = self._falha = 0
        self._cota_falhas = CotaHtmlFalha()

    def _encerrar_ciclo(self, cfg: ConfigAmazon) -> None:
        if self._ciclo is None:
            return
        status = repo.status_final(self._ok, self._falha, cfg.limite_falha_pct)
        with self._sessoes() as s, s.begin():
            repo.finalizar_coleta(s, self._ciclo, status, self._ok, self._falha, self._relogio())
        log.info("ciclo %s da Amazon terminou: %s (%d ok, %d falhas)", self._ciclo, status.value, self._ok, self._falha)
        if status is StatusColeta.FALHA:
            self._notificador.enviar(
                Destino.ADMIN,
                f"Ciclo {self._ciclo} da Amazon falhou em {self._falha} de {self._ok + self._falha} buscas. "
                f"O layout da Amazon pode ter mudado. HTMLs em {self._config.dir_dados / 'falhas'}.",
            )
        self._ciclo = None
        self._pendentes = set()

    def _registrar_desafio(self, url: str, asin_no_carrinho: str | None = None) -> None:
        agora = self._relogio()
        with self._sessoes() as s, s.begin():
            if self._ciclo is not None:
                repo.finalizar_coleta(
                    s, self._ciclo, StatusColeta.PAUSADA_DESAFIO, self._ok, self._falha, agora, erro=f"desafio em {url}"
                )
            repo.pausar_por_desafio(s, f"desafio em {url}", agora, COLETOR_AMAZON)
        log.warning("CAPTCHA na Amazon em %s; varredura pausada", url)
        self._ciclo = None
        self._pendentes = set()
        self._notificador.enviar(Destino.ADMIN, mensagem_captcha(self._config, url, asin_no_carrinho))

    # --- laço --------------------------------------------------------------------------------

    def inicializar(self) -> None:
        self._config = carregar_config(self._sessoes, self._config_env)
        with self._sessoes() as s, s.begin():
            interrompidos = repo.marcar_interrompidas(s, self._relogio(), TIPOS_AMAZON)
            presos = repo_amz.conferencias_com_item_no_carrinho(s)
        if presos:  # item que ficou de antes do reinício: a retirada roda já no primeiro passo
            log.warning("%d conferência(s) com item possivelmente no carrinho; tirando no primeiro passo", len(presos))
        if interrompidos:
            log.warning("%d ciclo(s) da Amazon interrompido(s) marcados como falha", interrompidos)
            self._notificador.enviar(
                Destino.ADMIN,
                f"{interrompidos} ciclo(s) da Amazon interrompido(s) (o coletor reiniciou) e marcado(s) como "
                "falha. A fila continua sozinha.",
            )

    def _janela(self, agora: datetime, tipo: str, inicio: time, fim: time) -> Janela:
        dia = agora.astimezone(self._config.zona).date()
        chave = (tipo, dia, inicio, fim, self._config.fuso)
        if chave not in self._janelas:
            self._janelas[chave] = janela_do_dia(dia, inicio, fim, self._config.zona, self._rng)
        return self._janelas[chave]

    def passo(self) -> float:
        """Faz no máximo um trabalho. Devolve quantos segundos dormir antes do próximo passo."""
        self._config = carregar_config(self._sessoes, self._config_env)
        agora = self._relogio()
        with self._sessoes() as s, s.begin():
            cfg = repo_amz.obter_config(s)
            estado = repo.obter_estado(s, agora, COLETOR_AMAZON).estado
        descoberta_aberta = self._janela(agora, "busca", cfg.janela_inicio, cfg.janela_fim).contem(agora)
        monitor_aberto = self._janela(agora, "monitor", cfg.monitor_janela_inicio, cfg.monitor_janela_fim).contem(agora)
        if not descoberta_aberta:
            self._encerrar_ciclo(cfg)
        if estado is EstadoColetorTipo.ATIVO:
            try:
                espera = self._talvez_retirar(cfg)
            except DesafioAmazon as desafio:
                self._registrar_desafio(desafio.url)
                return ESPERA_OCIOSA_S
            if espera is not None:
                return espera
        if not (descoberta_aberta or monitor_aberto):
            self.fechar_navegador()
            return ESPERA_OCIOSA_S
        if estado is not EstadoColetorTipo.ATIVO:
            return ESPERA_OCIOSA_S
        self._limpar_uma_vez_por_dia(agora)
        if monitor_aberto and self._teto_monitor.liberado_em(agora, cfg.monitor_max_paginas_hora) is None:
            try:
                espera = self._passo_monitor(agora, cfg)
            except DesafioAmazon as desafio:
                self._registrar_desafio(desafio.url)
                return ESPERA_OCIOSA_S
            if espera is not None:
                return espera
        if descoberta_aberta:
            return self._passo_descoberta(agora, cfg)
        return ESPERA_OCIOSA_S

    def _limpar_uma_vez_por_dia(self, agora: datetime) -> None:
        dia = agora.astimezone(self._config.zona).date()
        if self._limpeza_em == dia:
            return
        with self._sessoes() as s, s.begin():
            apagadas = repo_amz.limpar_ofertas_antigas(s, agora)
        if apagadas:
            log.info("%d ofertas lidas há mais de 30 dias apagadas", apagadas)
        self._limpeza_em = dia
        self._cota_falhas_monitor = CotaHtmlFalha()

    # --- monitor, conferência e retirada ---------------------------------------------------------

    def _passo_monitor(self, agora: datetime, cfg: ConfigAmazon) -> float | None:
        """Um trabalho do monitor, por prioridade. None: nada a fazer agora (a descoberta pode ir)."""
        self._espera_monitor = {k: v for k, v in self._espera_monitor.items() if v > agora}
        with self._sessoes() as s, s.begin():
            candidatas = []
            if cfg.checkout_ligado and cfg.checkout_sem_login_em is None and not repo_amz.carrinho_ocupado_ha_pouco(s, agora):
                candidatas = repo_amz.candidatas_ao_checkout(s, agora, cfg)
            proximo = None
            if cfg.monitor_ligado:
                proximo = repo_amz.proximo_do_monitor(s, agora, cfg.monitor_intervalo_min, set(self._espera_monitor))
        if candidatas:
            return self._conferir(candidatas[0], cfg)
        if proximo is not None:
            return self._monitorar(*proximo, cfg)
        return None

    def _talvez_retirar(self, cfg: ConfigAmazon) -> float | None:
        """Tenta tirar do carrinho o item de uma conferência que pode ter ficado lá (marca "em
        andamento" de um processo que morreu, ou retirada que falhou), uma conferência por passo, em
        rodízio e com `ESPERA_RETIRADA` entre tentativas da mesma. None: nada a tirar agora."""
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
            self._notificador.enviar(Destino.ADMIN, mensagem_conferir_a_mao(self._config, item.asin))

    def _falha_na_retirada(self, item: repo_amz.ItemNoCarrinho, motivo: str) -> None:
        with self._sessoes() as s, s.begin():
            tentativas = repo_amz.registrar_tentativa_retirada(s, item.conferencia_id, self._relogio())
        log.warning("não deu para tirar %s do carrinho (tentativa %d): %s", item.asin, tentativas, motivo)
        if tentativas >= MAX_TENTATIVAS_RETIRADA:
            self._conferir_a_mao(item, f"{tentativas} tentativas de retirada falharam")

    def _retirar(self, item: repo_amz.ItemNoCarrinho, cfg: ConfigAmazon) -> float:
        ctx = self._contexto(cfg, f"amazon-carrinho-{item.asin}", self._cota_falhas_monitor)
        abertas = [0]

        def abrir(url: str):
            abertas[0] += 1  # conta também as páginas abertas antes de um erro (o teto cobra todas)
            return abrir_pagina(ctx, url)

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
                return 0
            razao = self._sem_clique(item, estado)
            if razao is not None:
                self._conferir_a_mao(item, razao)
                return 0
            removido, _ = remover_do_carrinho(ctx.navegador, item.asin, abrir, self._pausar(cfg), carrinho)
        except ERROS_DE_PAGINA as erro:
            self._falha_na_retirada(item, str(erro))
            return 0
        except DesafioAmazon as desafio:
            with self._sessoes() as s, s.begin():  # não conta como falha: tenta de novo depois de retomar
                repo_amz.registrar_tentativa_retirada(s, item.conferencia_id, self._relogio(), contar=False)
            self._registrar_desafio(desafio.url, item.asin)  # o aviso diz qual item pode ter ficado
            return ESPERA_OCIOSA_S
        except Exception as erro:
            self._falha_na_retirada(item, repr(erro))
            raise
        finally:
            self._registrar_paginas(max(abertas[0], 1))
        if removido:  # carrinho ativo conferido sem o item: resolve as marcas desse ASIN
            with self._sessoes() as s, s.begin():
                repo_amz.marcar_asin_removido(s, item.asin)
            return 0
        self._falha_na_retirada(item, "o item continua no carrinho depois de excluir")
        return 0

    def _conferir(self, candidata: repo_amz.CandidataCheckout, cfg: ConfigAmazon) -> float:
        ctx = self._contexto(cfg, f"amazon-checkout-{candidata.asin}", self._cota_falhas_monitor)
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
            resultado = checkout.conferir(ctx.navegador, alvo, abrir, self._pausar(cfg), ao_adicionar=marcar_em_andamento)
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
            self._notificador.enviar(Destino.ADMIN, mensagem_sem_login(self._config))
        if resultado.situacao is SituacaoCheckout.OK:
            self._falhas_seguidas = 0
            monitor.aplicar_conferencia(ctx, candidata.anuncio_id, conferencia_id)
        else:  # sem conferência possível agora: a leitura atual decide já, com o preço anunciado
            monitor.redecidir(ctx, candidata.anuncio_id)
        if resultado.desafio_url is not None:
            self._registrar_desafio(resultado.desafio_url, None if resultado.item_removido else candidata.asin)
            return ESPERA_OCIOSA_S
        return 0

    def _monitorar(self, anuncio_id: int, asin: str, cfg: ConfigAmazon) -> float:
        ctx = self._contexto(cfg, f"amazon-monitor-{asin}", self._cota_falhas_monitor)
        contado = _NavegadorContado(ctx.navegador)
        ctx = dataclasses.replace(ctx, navegador=contado)
        try:
            resultado = monitor.ler_anuncio(ctx, anuncio_id, asin)
        except ERROS_DE_PAGINA as erro:
            self._registrar_paginas(max(contado.abertas, 1))  # ofertas, perfis de vendedor e novas tentativas
            self._espera_monitor[anuncio_id] = self._relogio() + timedelta(minutes=cfg.monitor_intervalo_min)
            self._falhas_seguidas += 1
            log.warning("leitura das ofertas de %s falhou: %s", asin, erro)
            if self._falhas_seguidas >= MAX_FALHAS_SEGUIDAS:
                return self._pausar_por_falhas(cfg)
            return 0
        except DesafioAmazon:
            raise
        except Exception:
            # Um anúncio que quebra não pode prender o monitor nele: espera um intervalo e o erro sobe.
            self._espera_monitor[anuncio_id] = self._relogio() + timedelta(minutes=cfg.monitor_intervalo_min)
            raise
        self._registrar_paginas(resultado.paginas)
        self._falhas_seguidas = 0
        self._erros_seguidos = 0
        return 0

    # --- descoberta ------------------------------------------------------------------------------

    def _passo_descoberta(self, agora: datetime, cfg: ConfigAmazon) -> float:
        if self._teto.liberado_em(agora, cfg.max_buscas_hora) is not None:
            return ESPERA_OCIOSA_S
        with self._sessoes() as s, s.begin():
            repo_amz.sincronizar_fila(s, agora)
            na_fila = repo_amz.ids_na_fila(s, agora, cfg.descoberta_casados_dias)
            item = repo_amz.proximo_da_fila(s, agora, cfg.descoberta_casados_dias)
            produto = s.get(ProdutoLiga, item.produto_id) if item else None
            entrou_em = item.entrou_em if item else None
            # Português na primeira busca, depois alterna; sem nome em inglês é sempre português.
            # O inglês só vale se o termo existir e for diferente do português.
            usar_en = bool(
                item
                and produto
                and produto.nome_en
                and termo_busca(produto.nome_en) not in ("", termo_busca(produto.nome))
                and item.ultima_busca_em is not None
                and not item.ultimo_termo_en
            )
            ultimo_candidato_em = item.ultimo_candidato_em if item else None
        self._pendentes &= na_fila  # produto desativado na Liga (ou casado) sai do ciclo
        if self._ciclo is not None and not self._pendentes:
            self._encerrar_ciclo(cfg)
        if produto is None:
            return ESPERA_OCIOSA_S
        if self._ciclo is None:
            self._iniciar_ciclo(agora, na_fila)

        contexto = self._contexto(cfg, f"amazon-{self._ciclo}-{produto.id}", self._cota_falhas)
        teve_candidato = False
        try:
            teve_candidato = processar_produto(contexto, produto, usar_en).candidatos > 0
            self._ok += 1
            self._falhas_seguidas = 0
        except DesafioAmazon as desafio:
            self._registrar_desafio(desafio.url)
            return ESPERA_OCIOSA_S
        except (ErroParser, ErroRede) as erro:
            self._falha += 1
            self._falhas_seguidas += 1
            log.warning("busca do produto %s na Amazon falhou: %s", produto.id, erro)
        except Exception:
            # Um produto que quebra não pode travar a fila: conta falha, reagenda e deixa o erro subir.
            self._falha += 1
            depois = self._relogio()
            try:
                with self._sessoes() as s, s.begin():
                    repo_amz.reagendar(
                        s, produto.id, depois, depois + timedelta(minutes=cfg.intervalo_busca_min), False, usar_en
                    )
            except Exception:
                log.exception("não foi possível reagendar o produto %s da Amazon", produto.id)
            self._pendentes.discard(produto.id)
            if not self._pendentes:
                self._encerrar_ciclo(cfg)
            raise
        self._erros_seguidos = 0
        self._teto.registrar(agora)

        depois = self._relogio()
        candidato_em = depois if teve_candidato else ultimo_candidato_em
        proxima = depois + intervalo_busca(cfg.intervalo_busca_min, depois, candidato_em, entrou_em)
        with self._sessoes() as s, s.begin():
            repo_amz.reagendar(s, produto.id, depois, proxima, teve_candidato, usar_en)
            repo_amz.fechar_oportunidades_sem_leitura(s, depois)
        self._pendentes.discard(produto.id)
        if not self._pendentes:
            self._encerrar_ciclo(cfg)
        if self._falhas_seguidas >= MAX_FALHAS_SEGUIDAS:
            return self._pausar_por_falhas(cfg)
        return 0

    def _pausar_por_falhas(self, cfg: ConfigAmazon) -> float:
        """Bloqueio sem CAPTCHA ou layout novo: toda página falha. Pausa em vez de seguir no ritmo normal."""
        self._falhas_seguidas = 0
        pasta = self._config.dir_dados / "falhas"
        try:
            with self._sessoes() as s, s.begin():
                repo.pausar(s, "falhas seguidas", self._relogio(), COLETOR_AMAZON)
        except Exception:
            log.exception("não foi possível registrar a pausa da busca na Amazon")
            self._notificador.enviar(
                Destino.ADMIN,
                f"{MAX_FALHAS_SEGUIDAS} páginas seguidas da Amazon falharam (bloqueio ou mudança de layout?); "
                f"não foi possível registrar a pausa no banco. HTMLs em {pasta}.",
            )
            return ESPERA_ERRO_S
        log.warning("%d páginas seguidas da Amazon falharam; varredura pausada", MAX_FALHAS_SEGUIDAS)
        self._encerrar_ciclo(cfg)
        self._notificador.enviar(
            Destino.ADMIN,
            f"Amazon pausada depois de {MAX_FALHAS_SEGUIDAS} páginas seguidas com falha (bloqueio ou "
            f"mudança de layout?). HTMLs em {pasta}. Com a Amazon pausada, a retirada automática de item do "
            "carrinho também para. Veja `docker compose logs coletor-amazon` e clique em "
            f"Retomar (Amazon) em http://{self._config.host_publico}:8000",
        )
        return ESPERA_OCIOSA_S

    def tratar_erro(self, erro: Exception) -> float:
        """Erro inesperado num passo: avisa e espera; três seguidos pausam a varredura."""
        log.error("erro inesperado na varredura da Amazon", exc_info=erro)
        self.fechar_navegador()
        self._erros_seguidos += 1
        if self._erros_seguidos >= MAX_ERROS_SEGUIDOS:
            self._erros_seguidos = 0
            try:
                with self._sessoes() as s, s.begin():
                    repo.pausar(s, "erros seguidos", self._relogio(), COLETOR_AMAZON)
            except Exception:
                log.exception("não foi possível registrar a pausa da varredura da Amazon")
                self._notificador.enviar(
                    Destino.ADMIN,
                    f"Erros inesperados seguidos na varredura da Amazon (último: {erro!r}); não foi possível "
                    "registrar a pausa no banco. Nova tentativa em 15 minutos.",
                )
                return ESPERA_ERRO_S
            self._notificador.enviar(
                Destino.ADMIN,
                f"Varredura da Amazon pausada depois de {MAX_ERROS_SEGUIDOS} erros inesperados seguidos "
                f"(último: {erro!r}). Com a Amazon pausada, a retirada automática de item do carrinho também para. "
                "Veja `docker compose logs coletor-amazon` e clique em Retomar (Amazon) "
                f"em http://{self._config.host_publico}:8000",
            )
            return ESPERA_OCIOSA_S
        self._notificador.enviar(
            Destino.ADMIN, f"Erro inesperado na varredura da Amazon: {erro!r}. Nova tentativa em 15 minutos."
        )
        return ESPERA_ERRO_S

    def rodar(self) -> None:
        try:
            with lock_coleta(self._engine, ID_LOCK_AMAZON) as obtido:
                if not obtido:
                    log.error("outro coletor-amazon já está rodando; saindo")
                    return
                self.inicializar()
                log.info("varredura da Amazon iniciada")
                while True:
                    try:
                        espera = self.passo()
                    except Exception as erro:  # noqa: BLE001 - qualquer falha inesperada vira espera/pausa
                        espera = self.tratar_erro(erro)
                    if espera > 0:
                        self._dormir(espera)
        finally:
            # SIGTERM vira SystemExit: fecha o navegador que tenha ficado aberto por um CAPTCHA.
            self.fechar_navegador()
