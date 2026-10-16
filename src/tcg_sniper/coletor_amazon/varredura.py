"""Fila contínua de buscas na Amazon, dentro da janela do dia, com teto por hora e ciclos."""

import logging
import random
import time as relogio_sistema
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.coletor_amazon.busca import ContextoBusca, CotaHtmlFalha, DesafioAmazon, processar_produto
from tcg_sniper.coletor_amazon.fila import Janela, TetoPorHora, intervalo_busca, janela_do_dia
from tcg_sniper.coletor_amazon.termo import termo_busca
from tcg_sniper.coletor_liga.agendador import lock_coleta
from tcg_sniper.config import Config
from tcg_sniper.config_banco import carregar_config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import COLETOR_AMAZON, ConfigAmazon, EstadoColetorTipo, ProdutoLiga, StatusColeta, TipoColeta
from tcg_sniper.navegador.base import Navegador
from tcg_sniper.navegador.modelos import ErroRede
from tcg_sniper.notificador.base import Destino, Notificador
from tcg_sniper.parsing import ErroParser

log = logging.getLogger(__name__)

ID_LOCK_AMAZON = 7_202_611
TIPOS_AMAZON = (TipoColeta.AMAZON,)
ESPERA_OCIOSA_S = 60
ESPERA_ERRO_S = 15 * 60
MAX_ERROS_SEGUIDOS = 3
MAX_FALHAS_SEGUIDAS = 10  # buscas seguidas com ErroParser/ErroRede (bloqueio ou layout novo)


def mensagem_captcha(config: Config, url: str) -> str:
    return (
        f"CAPTCHA na Amazon ({url}). Resolver em http://{config.host_publico}:6081/vnc.html "
        f"e depois clicar em Retomar (Amazon) em http://{config.host_publico}:8000"
    )


class VarreduraAmazon:
    def __init__(
        self,
        engine: Engine,
        sessoes: sessionmaker[Session],
        fabrica_navegador: Callable[[], AbstractContextManager[Navegador]],
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
        self._janelas: dict[tuple[date, time, time, str], Janela] = {}
        self._teto = TetoPorHora()
        self._ciclo: int | None = None
        self._pendentes: set[int] = set()
        self._ok = 0
        self._falha = 0
        self._erros_seguidos = 0
        self._falhas_seguidas = 0
        self._cota_falhas = CotaHtmlFalha()
        self._contexto_navegador: AbstractContextManager[Navegador] | None = None
        self._navegador: Navegador | None = None

    # --- navegador ---------------------------------------------------------------------------

    def _obter_navegador(self) -> Navegador:
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

    # --- ciclo -------------------------------------------------------------------------------

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

    def _registrar_desafio(self, url: str) -> None:
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
        self._notificador.enviar(Destino.ADMIN, mensagem_captcha(self._config, url))

    # --- laço --------------------------------------------------------------------------------

    def inicializar(self) -> None:
        self._config = carregar_config(self._sessoes, self._config_env)
        with self._sessoes() as s, s.begin():
            interrompidos = repo.marcar_interrompidas(s, self._relogio(), TIPOS_AMAZON)
        if interrompidos:
            log.warning("%d ciclo(s) da Amazon interrompido(s) marcados como falha", interrompidos)
            self._notificador.enviar(
                Destino.ADMIN,
                f"{interrompidos} ciclo(s) da Amazon interrompido(s) (o coletor reiniciou) e marcado(s) como "
                "falha. A fila continua sozinha.",
            )

    def _janela(self, agora: datetime, cfg: ConfigAmazon) -> Janela:
        dia = agora.astimezone(self._config.zona).date()
        chave = (dia, cfg.janela_inicio, cfg.janela_fim, self._config.fuso)
        if chave not in self._janelas:
            self._janelas[chave] = janela_do_dia(dia, cfg.janela_inicio, cfg.janela_fim, self._config.zona, self._rng)
        return self._janelas[chave]

    def passo(self) -> float:
        """Faz no máximo uma busca. Devolve quantos segundos dormir antes do próximo passo."""
        self._config = carregar_config(self._sessoes, self._config_env)
        agora = self._relogio()
        with self._sessoes() as s, s.begin():
            cfg = repo_amz.obter_config(s)
            estado = repo.obter_estado(s, agora, COLETOR_AMAZON).estado
        if not self._janela(agora, cfg).contem(agora):
            self._encerrar_ciclo(cfg)
            self.fechar_navegador()
            return ESPERA_OCIOSA_S
        if estado is not EstadoColetorTipo.ATIVO:
            return ESPERA_OCIOSA_S
        if self._teto.liberado_em(agora, cfg.max_buscas_hora) is not None:
            return ESPERA_OCIOSA_S

        with self._sessoes() as s, s.begin():
            repo_amz.sincronizar_fila(s, agora)
            na_fila = repo_amz.ids_na_fila(s)
            item = repo_amz.proximo_da_fila(s, agora)
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
        self._pendentes &= na_fila  # produto desativado na Liga sai do ciclo
        if self._ciclo is not None and not self._pendentes:
            self._encerrar_ciclo(cfg)
        if produto is None:
            return ESPERA_OCIOSA_S
        if self._ciclo is None:
            self._iniciar_ciclo(agora, na_fila)

        contexto = ContextoBusca(
            sessoes=self._sessoes,
            navegador=self._obter_navegador(),
            notificador=self._notificador,
            config=self._config,
            cfg=cfg,
            relogio=self._relogio,
            dormir=self._dormir,
            rng=self._rng,
            nome_falha=f"amazon-{self._ciclo}-{produto.id}",
            cota_falhas=self._cota_falhas,
        )
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
        """Bloqueio sem CAPTCHA ou layout novo: toda busca falha. Pausa em vez de seguir no ritmo normal."""
        self._falhas_seguidas = 0
        pasta = self._config.dir_dados / "falhas"
        try:
            with self._sessoes() as s, s.begin():
                repo.pausar(s, "falhas seguidas", self._relogio(), COLETOR_AMAZON)
        except Exception:
            log.exception("não foi possível registrar a pausa da busca na Amazon")
            self._notificador.enviar(
                Destino.ADMIN,
                f"{MAX_FALHAS_SEGUIDAS} buscas seguidas na Amazon falharam (bloqueio ou mudança de layout?); "
                f"não foi possível registrar a pausa no banco. HTMLs em {pasta}.",
            )
            return ESPERA_ERRO_S
        log.warning("%d buscas seguidas na Amazon falharam; varredura pausada", MAX_FALHAS_SEGUIDAS)
        self._encerrar_ciclo(cfg)
        self._notificador.enviar(
            Destino.ADMIN,
            f"Busca na Amazon pausada depois de {MAX_FALHAS_SEGUIDAS} buscas seguidas com falha (bloqueio ou "
            f"mudança de layout?). HTMLs em {pasta}. Veja `docker compose logs coletor-amazon` e clique em "
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
                f"(último: {erro!r}). Veja `docker compose logs coletor-amazon` e clique em Retomar (Amazon) "
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
