"""Base dos dois serviços da Amazon (`coletor-amazon-busca` e `coletor-amazon`): navegador próprio, janela
do dia com variação, teto por hora, pausa humana entre páginas, CAPTCHA, erro inesperado, pausa por falhas
ou erros seguidos, avisos com a origem no título e o laço `rodar` com trava. Cada serviço tem a própria
linha em `estado_coletor`, a própria trava e os próprios avisos (`OrigemAmazon`): um CAPTCHA, um erro ou
uma pausa num serviço não para o outro.

Este módulo não conhece fila, ciclo, monitor, checkout nem carrinho (ver `varredura_busca.py` e
`varredura_monitor.py`; o teste `test_lacos_separados.py` confere as importações)."""

import logging
import random
import time as relogio_sistema
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from urllib.parse import urlsplit

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.avisos.servico import Avisador
from tcg_sniper.coletor_amazon.busca import ContextoBusca, CotaHtmlFalha
from tcg_sniper.coletor_amazon.fila import Janela, TetoPorHora, janela_do_dia
from tcg_sniper.coletor_liga.agendador import lock_coleta
from tcg_sniper.config import Config
from tcg_sniper.config_banco import carregar_config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import COLETOR_AMAZON, COLETOR_AMAZON_BUSCA, ConfigAmazon, EstadoColetorTipo
from tcg_sniper.navegador.base import NavegadorInterativo
from tcg_sniper.navegador.ritmo import pausa_aleatoria

log = logging.getLogger(__name__)

ESPERA_OCIOSA_S = 60
ESPERA_ERRO_S = 15 * 60
MAX_ERROS_SEGUIDOS = 3
MAX_FALHAS_SEGUIDAS = 10  # páginas seguidas com ErroParser/ErroRede (bloqueio ou layout novo)
ID_LOCK_AMAZON = 7_202_611  # monitor e checkout (o `amazon capturar` usa o mesmo perfil e a mesma trava)
ID_LOCK_AMAZON_BUSCA = 7_202_612


@dataclass(frozen=True)
class OrigemAmazon:
    """Quem é o laço: a linha de `estado_coletor`, a trava e os avisos que só ele abre e resolve."""

    coletor: str
    nome: str  # "busca" | "monitor" (logs)
    id_lock: int
    captcha: TipoAviso
    pausada: TipoAviso
    erro: TipoAviso
    efeito_captcha: str  # linha do aviso de CAPTCHA: o que parou e o que segue
    efeito_pausa: str  # linha do aviso de pausa


ORIGEM_BUSCA = OrigemAmazon(
    coletor=COLETOR_AMAZON_BUSCA,
    nome="busca",
    id_lock=ID_LOCK_AMAZON_BUSCA,
    captcha=TipoAviso.AMAZON_BUSCA_CAPTCHA,
    pausada=TipoAviso.AMAZON_BUSCA_PAUSADA,
    erro=TipoAviso.AMAZON_BUSCA_ERRO,
    efeito_captcha="A busca fica pausada até você retomar; o monitor e a conferência seguem",
    efeito_pausa="Com a busca pausada, o monitor e a conferência seguem",
)
ORIGEM_MONITOR = OrigemAmazon(
    coletor=COLETOR_AMAZON,
    nome="monitor",
    id_lock=ID_LOCK_AMAZON,
    captcha=TipoAviso.AMAZON_CAPTCHA,
    pausada=TipoAviso.AMAZON_PAUSADA,
    erro=TipoAviso.AMAZON_ERRO,
    efeito_captcha="Monitor e conferência pausados até você retomar; a busca segue",
    efeito_pausa="Com o monitor pausado, a retirada automática de item do carrinho também para",
)


def pagina_curta(url: str) -> str:
    partes = urlsplit(url)
    return (partes.path or "/") + (f"?{partes.query}" if partes.query else "")


def dados_captcha(origem: OrigemAmazon, url: str, extras: tuple[str, ...] = ()) -> Dados:
    return Dados(linhas=(f"Página: {pagina_curta(url)}", origem.efeito_captcha, *extras))


def dados_pausa(origem: OrigemAmazon, motivo: str, sem_registro: bool = False) -> Dados:
    if sem_registro:  # o banco recusou a pausa: o serviço segue e tenta de novo
        return Dados(linhas=(f"Motivo: {motivo}", "Não consegui registrar a pausa no banco: nova tentativa em 15 min"))
    return Dados(linhas=(f"Motivo: {motivo}", origem.efeito_pausa))


class VarreduraBase:
    """Laço de um serviço da Amazon. A subclasse define `origem` e `passo()` (no máximo um trabalho por
    passo; devolve quantos segundos dormir)."""

    origem: OrigemAmazon

    def __init__(
        self,
        engine: Engine,
        sessoes: sessionmaker[Session],
        fabrica_navegador: Callable[[], AbstractContextManager[NavegadorInterativo]],
        avisador: Avisador,
        config: Config,
        relogio: Callable[[], datetime] | None = None,
        rng: random.Random | None = None,
        dormir: Callable[[float], None] = relogio_sistema.sleep,
    ):
        self._engine = engine
        self._sessoes = sessoes
        self._fabrica_navegador = fabrica_navegador
        self._avisador = avisador
        self._config_env = config
        self._config = config
        self._relogio = relogio or (lambda: datetime.now(UTC))
        self._rng = rng or random.Random()
        self._dormir = dormir
        self._janelas: dict[tuple[str, date, time, time, str], Janela] = {}
        self._teto = TetoPorHora()  # páginas (ou buscas) deste serviço; nunca divide vaga com o outro
        self._erros_seguidos = 0
        self._falhas_seguidas = 0
        self._contexto_navegador: AbstractContextManager[NavegadorInterativo] | None = None
        self._navegador: NavegadorInterativo | None = None

    # --- navegador -------------------------------------------------------------------------------

    def _obter_navegador(self) -> NavegadorInterativo:
        if self._navegador is not None:
            if self._navegador.vivo():
                return self._navegador
            log.warning("navegador da Amazon (%s) não responde; abrindo outro", self.origem.nome)
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
            log.warning("erro ao fechar o navegador da Amazon (%s)", self.origem.nome, exc_info=True)

    def _contexto(self, cfg: ConfigAmazon, nome_falha: str, cota: CotaHtmlFalha) -> ContextoBusca:
        return ContextoBusca(
            sessoes=self._sessoes,
            navegador=self._obter_navegador(),
            avisador=self._avisador,
            config=self._config,
            cfg=cfg,
            relogio=self._relogio,
            dormir=self._dormir,
            rng=self._rng,
            nome_falha=nome_falha,
            cota_falhas=cota,
        )

    def _pausa_humana(self, cfg: ConfigAmazon) -> Callable[[], None]:
        return lambda: pausa_aleatoria(cfg.pausa_min_s, cfg.pausa_max_s, self._dormir, self._rng)

    def _janela(self, agora: datetime, tipo: str, inicio: time, fim: time) -> Janela:
        dia = agora.astimezone(self._config.zona).date()
        chave = (tipo, dia, inicio, fim, self._config.fuso)
        if chave not in self._janelas:
            self._janelas[chave] = janela_do_dia(dia, inicio, fim, self._config.zona, self._rng)
        return self._janelas[chave]

    # --- estado e avisos -------------------------------------------------------------------------

    def _inicio_do_passo(self, agora: datetime) -> tuple[ConfigAmazon, EstadoColetorTipo]:
        """Relê a configuração (Geral e Amazon) e o estado deste serviço; ativo fecha a pausa aberta dele."""
        self._config = carregar_config(self._sessoes, self._config_env)
        with self._sessoes() as s, s.begin():
            cfg = repo_amz.obter_config(s)
            estado = repo.obter_estado(s, agora, self.origem.coletor).estado
        if estado is EstadoColetorTipo.ATIVO:
            self._avisador.resolver(self.origem.pausada, CHAVE_GERAL)  # retomada: a pausa acabou
        return cfg, estado

    def _pagina_ok(self) -> None:
        """Uma página abriu sem CAPTCHA neste navegador: o CAPTCHA aberto deste serviço está resolvido."""
        self._avisador.resolver(self.origem.captcha, CHAVE_GERAL)

    def _fechar_por_desafio(self, s: Session, url: str, agora: datetime) -> None:
        """Gancho: o que fechar na mesma transação da pausa por CAPTCHA (a busca fecha o ciclo aberto)."""

    def _registrar_desafio(self, url: str, extras: tuple[str, ...] = ()) -> None:
        agora = self._relogio()
        with self._sessoes() as s, s.begin():
            self._fechar_por_desafio(s, url, agora)
            repo.pausar_por_desafio(s, f"desafio em {url}", agora, self.origem.coletor)
        log.warning("CAPTCHA na Amazon (%s) em %s; serviço pausado", self.origem.nome, url)
        self._avisador.avisar(self.origem.captcha, CHAVE_GERAL, dados_captcha(self.origem, url, extras))

    def _pausar_servico(self, motivo_banco: str, motivo: str, ao_pausar: Callable[[], None] | None = None) -> float:
        """Pausa este serviço (só volta com Retomar). `ao_pausar` roda só se a pausa foi gravada."""
        try:
            with self._sessoes() as s, s.begin():
                repo.pausar(s, motivo_banco, self._relogio(), self.origem.coletor)
        except Exception:
            log.exception("não foi possível registrar a pausa da Amazon (%s)", self.origem.nome)
            self._avisador.avisar(self.origem.pausada, CHAVE_GERAL, dados_pausa(self.origem, motivo, sem_registro=True))
            return ESPERA_ERRO_S
        log.warning("Amazon (%s) pausada: %s", self.origem.nome, motivo)
        if ao_pausar is not None:
            ao_pausar()
        self._avisador.avisar(self.origem.pausada, CHAVE_GERAL, dados_pausa(self.origem, motivo))
        return ESPERA_OCIOSA_S

    def _pausar_por_falhas(self, ao_pausar: Callable[[], None] | None = None) -> float:
        """Bloqueio sem CAPTCHA ou layout novo: toda página falha. Pausa em vez de seguir no ritmo normal."""
        self._falhas_seguidas = 0
        motivo = f"{MAX_FALHAS_SEGUIDAS} páginas seguidas com falha (bloqueio ou layout novo?)"
        return self._pausar_servico("falhas seguidas", motivo, ao_pausar)

    def tratar_erro(self, erro: Exception) -> float:
        """Erro inesperado num passo: avisa e espera; três seguidos pausam este serviço."""
        log.error("erro inesperado na Amazon (%s)", self.origem.nome, exc_info=erro)
        self.fechar_navegador()
        self._erros_seguidos += 1
        if self._erros_seguidos >= MAX_ERROS_SEGUIDOS:
            self._erros_seguidos = 0
            motivo = f"{MAX_ERROS_SEGUIDOS} erros inesperados seguidos (último: {erro!r})"
            return self._pausar_servico("erros seguidos", motivo)
        self._avisador.avisar(self.origem.erro, CHAVE_GERAL, Dados(linhas=(f"Erro: {erro!r}",)))
        return ESPERA_ERRO_S

    # --- laço ------------------------------------------------------------------------------------

    def inicializar(self) -> None:
        self._config = carregar_config(self._sessoes, self._config_env)

    def passo(self) -> float:
        raise NotImplementedError

    def executar_passo(self) -> float:
        """Um passo protegido: erro inesperado vira aviso/espera; passo ok fecha o erro aberto deste serviço."""
        try:
            espera = self.passo()
        except Exception as erro:  # noqa: BLE001 - qualquer falha inesperada vira espera/pausa
            return self.tratar_erro(erro)
        self._avisador.resolver(self.origem.erro, CHAVE_GERAL)
        return espera

    def rodar(self) -> None:
        try:
            with lock_coleta(self._engine, self.origem.id_lock) as obtido:
                if not obtido:
                    log.error("outra varredura da Amazon (%s) já está rodando; saindo", self.origem.nome)
                    return
                self.inicializar()
                log.info("varredura da Amazon (%s) iniciada", self.origem.nome)
                while True:
                    espera = self.executar_passo()
                    if espera > 0:
                        self._dormir(espera)
        finally:
            # SIGTERM vira SystemExit: fecha o navegador que tenha ficado aberto por um CAPTCHA.
            self.fechar_navegador()
