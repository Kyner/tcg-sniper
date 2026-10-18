"""Serviço `notificador`: envia a tabela de saída pela Evolution, com tentativas, validade e limpeza."""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.avisos import formato
from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import COLETOR_NOTIFICADOR, EstadoColetorTipo, MensagemSaida, StatusMensagem
from tcg_sniper.notificador import CHAVE_PADRAO
from tcg_sniper.notificador.evolution import Resultado, enviar_uma_vez

log = logging.getLogger(__name__)

INTERVALO_S = 5
LOTE = 20
MAX_TENTATIVAS_DEFINITIVAS = 5
ESPERA_SEM_DESTINO = timedelta(minutes=1)
ESPERA_MAX_MIN = 30
INTERVALO_LIMPEZA = timedelta(hours=24)
TIMEOUT_S = 15
JANELA_FALHAS = timedelta(hours=1)


@dataclass(frozen=True)
class _Destinos:
    """Cópia dos valores de Configurações → Geral que o ciclo usa (nada de ORM entre sessões)."""

    evolution_instancia: str | None
    whatsapp_grupo_admin: str | None
    whatsapp_grupo_oportunidades: str | None
    validade_oportunidade_h: int


class ServicoNotificador:
    def __init__(
        self,
        sessoes: sessionmaker[Session],
        config_env: Config,
        cliente: httpx.Client | None = None,
        relogio: Callable[[], datetime] | None = None,
        dormir: Callable[[float], None] | None = None,
    ):
        self._sessoes = sessoes
        self._config_env = config_env
        self._cliente = cliente or httpx.Client(timeout=TIMEOUT_S)
        self._relogio = relogio or repo.agora_utc
        self._dormir = dormir
        self._parar = threading.Event()
        self._ultima_limpeza: datetime | None = None
        chave = (config_env.evolution_api_key or "").strip()
        self._chave = chave if config_env.evolution_url and chave not in ("", CHAVE_PADRAO) else None

    def parar(self) -> None:
        """Pede o encerramento: o ciclo em andamento termina a mensagem atual e `rodar` volta."""
        self._parar.set()

    def ciclo(self) -> int:
        """Um ciclo: registra que está vivo, limpa (1x/dia) e processa até `LOTE` mensagens, cada uma
        na sua transação (o que já saiu não volta a `pendente` se algo falhar depois).
        Pausado no admin, só registra que está vivo: as mensagens ficam pendentes até retomar.
        Devolve quantas mensagens processou."""
        agora = inicio = self._relogio()
        with self._sessoes() as s, s.begin():
            if repo.obter_estado(s, agora, COLETOR_NOTIFICADOR).estado != EstadoColetorTipo.ATIVO:
                repo_msg.registrar_ciclo(s, agora)
                return 0
            geral = repo.obter_config_geral(s, self._config_env)
            cfg = _Destinos(
                geral.evolution_instancia,
                geral.whatsapp_grupo_admin,
                geral.whatsapp_grupo_oportunidades,
                geral.validade_oportunidade_h,
            )
            repo_msg.registrar_ciclo(s, agora)
            limpou = self._ultima_limpeza is None or agora - self._ultima_limpeza >= INTERVALO_LIMPEZA
            if limpou:
                apagadas = repo_msg.limpar_antigas(s, agora)
                if apagadas:
                    log.info("%d mensagem(ns) antigas apagadas", apagadas)
        if limpou:
            self._ultima_limpeza = agora
        processadas = 0
        enviou = False
        for _ in range(LOTE):
            if self._parar.is_set():
                break
            agora = self._relogio()
            with self._sessoes() as s, s.begin():
                lote = repo_msg.lote_pendente(s, agora, 1)
                if not lote:
                    break
                resultado = self._processar(s, lote[0], cfg, agora)
            processadas += 1
            if resultado is Resultado.OK:
                enviou = True
            elif resultado is Resultado.TRANSITORIO:
                break  # a Evolution está fora ou lenta: o resto espera o próximo ciclo
        if enviou:
            # a Evolution voltou: o que esperava um backoff de falha transitória tenta já
            with self._sessoes() as s, s.begin():
                acordadas = repo_msg.acordar_pendentes(s, self._relogio(), antes_de=inicio)
            if acordadas:
                log.info("%d mensagem(ns) em espera voltam à fila", acordadas)
        return processadas

    def _processar(self, s: Session, m: MensagemSaida, geral: _Destinos, agora: datetime) -> Resultado | None:
        """Devolve o resultado do envio, ou `None` se a mensagem nem chegou a ser enviada."""
        m.atualizado_em = agora
        validade = timedelta(hours=geral.validade_oportunidade_h)
        if m.destino == "oportunidades" and not m.ignorar_validade and agora - m.criada_em > validade:
            m.status = StatusMensagem.EXPIRADA
            return None
        grupo = geral.whatsapp_grupo_admin if m.destino == "admin" else geral.whatsapp_grupo_oportunidades
        falta = None
        if self._chave is None:
            falta = "EVOLUTION_URL ou EVOLUTION_API_KEY ausente (ou com o valor padrão) no .env"
        elif not geral.evolution_instancia:
            falta = "sem instância da Evolution em Configurações → Geral"
        elif not grupo:
            falta = f"sem grupo de {m.destino} em Configurações → Geral"
        if falta is not None:
            m.ultimo_erro = falta
            m.proxima_tentativa_em = agora + ESPERA_SEM_DESTINO
            return None
        # linhas antigas da fila e "reenviar" saem como estão gravadas: a guarda de URL vale aqui também
        texto = formato.conferir_urls(m.texto, avisos.zona_e_host(s)[1], estrito=False)
        resultado, erro = enviar_uma_vez(
            self._cliente, self._config_env.evolution_url, self._chave, geral.evolution_instancia, grupo, texto
        )
        if resultado is Resultado.OK:
            m.status = StatusMensagem.ENVIADA
            m.enviada_em = agora
            m.ultimo_erro = None
            return resultado
        m.tentativas += 1
        m.ultimo_erro = erro
        if resultado is Resultado.DEFINITIVO and m.tentativas >= MAX_TENTATIVAS_DEFINITIVAS:
            m.status = StatusMensagem.FALHA
            log.error("mensagem %d para %s falhou de vez: %s", m.id, m.destino, erro)
            if not formato.eh_do_tipo(m.texto, TipoAviso.MENSAGEM_NAO_ENVIADA):  # nunca em laço
                self._avisar_falha(s, agora)
            return resultado
        m.proxima_tentativa_em = agora + timedelta(minutes=min(2 ** min(m.tentativas - 1, 5), ESPERA_MAX_MIN))
        log.warning("mensagem %d para %s não saiu (tentativa %d): %s", m.id, m.destino, m.tentativas, erro)
        return resultado

    @staticmethod
    def _avisar_falha(s: Session, agora: datetime) -> None:
        """Lista as falhas definitivas da última hora (menos os próprios avisos) para o grupo admin."""
        s.flush()
        falhas = [
            f for f in repo_msg.falhas_recentes(s, agora - JANELA_FALHAS)
            if not formato.eh_do_tipo(f.texto, TipoAviso.MENSAGEM_NAO_ENVIADA)
        ]
        linhas = tuple(f"#{f.id} para {f.destino}: {f.ultimo_erro or 'sem detalhe'}" for f in falhas)
        avisos.avisar(s, TipoAviso.MENSAGEM_NAO_ENVIADA, CHAVE_GERAL, Dados(linhas=linhas), agora)

    def rodar(self) -> None:
        log.info("notificador iniciado")
        if self._chave is None:
            log.warning("EVOLUTION_URL ou EVOLUTION_API_KEY ausente (ou com o valor padrão) no .env: as mensagens ficam pendentes")
        while True:
            try:
                self.ciclo()
            except Exception:
                log.exception("erro no ciclo do notificador; tenta de novo em %d s", INTERVALO_S)
            if self._parar.is_set():
                break
            if self._dormir is not None:
                self._dormir(INTERVALO_S)
            else:
                self._parar.wait(INTERVALO_S)
        log.info("notificador encerrado")
