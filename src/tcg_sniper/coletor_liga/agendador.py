import logging
import random
import time as relogio_sistema
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.coletor_liga.execucao import mensagem_resumo, pausa_humana
from tcg_sniper.coletor_liga.listagens import coletar_listagens
from tcg_sniper.coletor_liga.navegador import Navegador
from tcg_sniper.coletor_liga.produtos import coletar_produtos
from tcg_sniper.config import Config
from tcg_sniper.config_banco import carregar_config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import EstadoColetorTipo, StatusColeta, TipoColeta
from tcg_sniper.notificador.base import Destino, Notificador

log = logging.getLogger(__name__)

ID_LOCK = 7_202_610
INTERVALO_TICK_S = 60
TIPOS_LIGA = (TipoColeta.LISTAGEM, TipoColeta.PRODUTOS)


def alvo_do_dia(dia: date, hora: time, jitter_min: int, fuso: ZoneInfo, rng: random.Random) -> datetime:
    base = datetime.combine(dia, hora, tzinfo=fuso)
    return base + timedelta(minutes=rng.uniform(-jitter_min, jitter_min))


@contextmanager
def lock_coleta(engine: Engine, id_lock: int = ID_LOCK) -> Iterator[bool]:
    # AUTOCOMMIT: o lock é de sessão; sem transação aberta a conexão não fica "idle in transaction"
    # durante o job (e um idle_in_transaction_session_timeout não derruba o lock em silêncio).
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conexao:
        obtido = bool(conexao.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": id_lock}).scalar_one())
        try:
            yield obtido
        finally:
            if obtido:
                conexao.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": id_lock})


class Agendador:
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
        executor: Callable[[bool], bool | None] | None = None,
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
        self._executor = executor or self.executar_job
        self._alvos: dict[date, datetime] = {}
        # Parâmetros (hora, variação, fuso) com que o alvo de cada dia foi sorteado: se mudarem na
        # tela antes do job do dia, o alvo é sorteado de novo.
        self._parametros_alvo: dict[date, tuple[time, int, str]] = {}
        self._datas_tentadas: set[date] = set()
        self._atrasada_em: datetime | None = None
        # Navegador aberto sob demanda. Fica aberto quando um job termina pausado por desafio,
        # para o humano resolver pelo noVNC; o job seguinte (após "retomar") o reaproveita.
        self._contexto_navegador: AbstractContextManager[Navegador] | None = None
        self._navegador: Navegador | None = None

    def _recarregar(self) -> None:
        """Valores salvos na tela de Configurações valem a partir do próximo tick (o job em andamento
        termina com os valores com que começou)."""
        self._config = carregar_config(self._sessoes, self._config_env)

    def inicializar(self) -> None:
        self._recarregar()
        agora = self._relogio()
        with self._sessoes() as s, s.begin():
            interrompidas = repo.marcar_interrompidas(s, agora, TIPOS_LIGA)
            ultima = repo.ultima_coleta_sucesso(s, TipoColeta.PRODUTOS)
        if interrompidas:
            log.warning("%d coleta(s) interrompida(s) marcadas como falha", interrompidas)
            self._notificador.enviar(
                Destino.ADMIN,
                f"{interrompidas} coleta(s) interrompida(s) (o coletor reiniciou no meio do job) e marcadas "
                f"como falha. A coleta de hoje pode não rodar de novo sozinha: clique em \"Rodar agora\" em "
                f"http://{self._config.host_publico}:8000",
            )
        if ultima is None or agora - ultima > timedelta(hours=24):
            self._atrasada_em = agora + timedelta(minutes=self._rng.uniform(0, self._config.coleta_jitter_min))
            log.info("último job com sucesso: %s; execução atrasada em %s", ultima, self._atrasada_em)

    def tick(self) -> str | None:
        self._recarregar()
        agora = self._relogio()
        hoje = agora.astimezone(self._config.zona).date()
        inicio_do_dia = datetime.combine(hoje, time(0), tzinfo=self._config.zona)
        with self._sessoes() as s, s.begin():
            if repo.obter_estado(s, agora).estado != EstadoColetorTipo.ATIVO:
                return None
            solicitada = repo.consumir_solicitacao(s, agora)
            rodou_hoje = repo.coleta_iniciada_desde(s, TipoColeta.LISTAGEM, inicio_do_dia)
            ultima_listagem_ok = repo.ultima_coleta_sucesso(s, TipoColeta.LISTAGEM)

        if solicitada:
            # Uma atrasada pendente não roda depois disto (nem passa da meia-noite como job extra).
            self._atrasada_em = None
            # Retomar/rodar agora: refaz as listagens só se ainda não houve uma com sucesso hoje.
            listagem_ok_hoje = ultima_listagem_ok is not None and ultima_listagem_ok >= inicio_do_dia
            return self._executar("solicitado", not listagem_ok_hoje, hoje)
        pode_rodar_hoje = not rodou_hoje and hoje not in self._datas_tentadas
        if self._atrasada_em is not None and agora >= self._atrasada_em:
            self._atrasada_em = None
            if pode_rodar_hoje:
                return self._executar("atrasado", True, hoje)
        parametros = (self._config.coleta_hora, self._config.coleta_jitter_min, self._config.fuso)
        if self._parametros_alvo.get(hoje) != parametros:
            self._parametros_alvo[hoje] = parametros
            self._alvos[hoje] = alvo_do_dia(
                hoje, self._config.coleta_hora, self._config.coleta_jitter_min, self._config.zona, self._rng
            )
        if pode_rodar_hoje and agora >= self._alvos[hoje]:
            self._atrasada_em = None
            return self._executar("agendado", True, hoje)
        return None

    def _executar(self, motivo: str, incluir_listagens: bool, hoje: date) -> str:
        self._datas_tentadas.add(hoje)
        log.info("iniciando job (%s, listagens=%s)", motivo, incluir_listagens)
        try:
            obtido = self._executor(incluir_listagens)
            if obtido is False and motivo == "solicitado":
                # Lock ocupado (outro container coletando): o pedido do admin não se perde.
                with self._sessoes() as s, s.begin():
                    repo.solicitar_execucao(s, self._relogio())
                log.info("pedido de execução rearmado; tenta de novo no próximo tick")
        except Exception as erro:
            log.exception("job %s falhou", motivo)
            self._notificador.enviar(Destino.ADMIN, f"Erro inesperado no coletor ({motivo}): {erro!r}")
        return motivo

    def executar_job(self, incluir_listagens: bool) -> bool:
        """Devolve False se o advisory lock estava ocupado (nada rodou); True caso contrário."""
        with lock_coleta(self._engine) as obtido:
            if not obtido:
                log.warning("outra coleta em andamento; job ignorado")
                return False
            navegador = self._obter_navegador()
            pausou = False
            try:
                pausou = self._coletar(navegador, incluir_listagens)
            finally:
                if pausou:
                    log.info("navegador mantido aberto com o desafio na tela (resolver pelo noVNC)")
                else:
                    self.fechar_navegador()
        return True

    def _coletar(self, navegador: Navegador, incluir_listagens: bool) -> bool:
        """Roda as etapas do job. Devolve True se parou num desafio do Cloudflare. Se o job vai até
        o fim, sem desafio e sem etapa interrompida por erro, avisa o admin com um resumo."""
        listagens = None
        if incluir_listagens:
            listagens = coletar_listagens(self._sessoes, navegador, self._notificador, self._config, self._dormir)
            if listagens is None:
                return False
            if listagens.status is StatusColeta.PAUSADA_DESAFIO:
                return True
            pausa_humana(self._config, self._dormir)
        produtos = coletar_produtos(self._sessoes, navegador, self._notificador, self._config, self._dormir)
        if produtos is None:
            return False
        if produtos.status is StatusColeta.PAUSADA_DESAFIO:
            return True
        if not produtos.interrompida and not (listagens is not None and listagens.interrompida):
            hoje = self._relogio().astimezone(self._config.zona).date()
            self._notificador.enviar(Destino.ADMIN, mensagem_resumo(self._config, hoje, listagens, produtos))
        return False

    def _obter_navegador(self) -> Navegador:
        """Reaproveita o navegador mantido aberto se ele ainda responde; senão (ex.: a janela foi
        fechada pelo noVNC) descarta e abre um novo, uma única vez."""
        if self._navegador is not None:
            if self._navegador.vivo():
                log.info("reaproveitando o navegador mantido aberto")
                return self._navegador
            log.warning("navegador mantido aberto não responde; abrindo outro")
            self.fechar_navegador()
        contexto = self._fabrica_navegador()
        navegador = contexto.__enter__()
        self._contexto_navegador, self._navegador = contexto, navegador
        return navegador

    def fechar_navegador(self) -> None:
        contexto = self._contexto_navegador
        self._contexto_navegador = self._navegador = None
        if contexto is None:
            return
        try:
            contexto.__exit__(None, None, None)
        except Exception:  # instância possivelmente morta: só registra
            log.warning("erro ao fechar o navegador", exc_info=True)

    def rodar(self) -> None:
        inicializado = False
        try:
            while True:
                try:
                    if not inicializado:
                        self.inicializar()
                        inicializado = True
                        log.info("agendador iniciado")
                    self.tick()
                except Exception:
                    log.exception("erro no laço do agendador; tenta de novo no próximo tick")
                self._dormir(INTERVALO_TICK_S)
        finally:
            # SIGTERM vira SystemExit: fecha o navegador que tenha ficado aberto por um desafio.
            self.fechar_navegador()
