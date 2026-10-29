"""Serviço `notificador`: envia a tabela de saída pela Evolution, com tentativas, validade e limpeza."""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.avisos import formato, vigia
from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import COLETOR_NOTIFICADOR, EstadoColetorTipo, MensagemSaida, StatusMensagem
from tcg_sniper.formatacao import ocultar_numero
from tcg_sniper.notificador import CHAVE_PADRAO
from tcg_sniper.notificador.base import Destino
from tcg_sniper.notificador.evolution import Resultado, enviar_uma_vez

log = logging.getLogger(__name__)

INTERVALO_S = 5
LOTE = 20
MAX_TENTATIVAS_DEFINITIVAS = 5
ESPERA_SEM_DESTINO = timedelta(minutes=1)
ESPERA_MAX_MIN = 30
INTERVALO_LIMPEZA = timedelta(hours=24)
INTERVALO_VIGIA = timedelta(minutes=1)
TIMEOUT_S = 15
JANELA_FALHAS = repo_msg.JANELA_FALHAS


def _espera(tentativas: int) -> timedelta:
    """Backoff de uma mensagem que não saiu: 1, 2, 4... min, até `ESPERA_MAX_MIN`."""
    return timedelta(minutes=min(2 ** min(tentativas - 1, 5), ESPERA_MAX_MIN))


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
        self._ultima_vigia: datetime | None = None
        self._desde = self._relogio()  # início da vigia da manutenção: reinício do notificador não alarma
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
        try:  # antes da pausa: o código vencido não pode ficar no banco com o notificador parado
            with self._sessoes() as s, s.begin():
                repo_msg.expirar_individuais_vencidas(s, agora)
        except Exception:
            log.exception("não consegui expirar os códigos vencidos")
        self._vigiar_manutencao(agora)
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
        pular: set[int] = set()  # só deste ciclo: mensagens que nem o adiamento conseguiu gravar
        for _ in range(LOTE):
            if self._parar.is_set():
                break
            agora = self._relogio()
            mid: int | None = None
            try:
                with self._sessoes() as s, s.begin():
                    lote = repo_msg.lote_pendente(s, agora, 1, excluir=pular)
                    if not lote:
                        break
                    mid = lote[0].id
                    resultado = self._processar(s, lote[0], cfg, agora)
            except Exception as exc:
                if mid is None:  # nem a leitura da fila funcionou: o `rodar` registra e tenta no próximo ciclo
                    raise
                log.exception("erro ao processar a mensagem %d; ela é adiada e a fila segue", mid)
                try:
                    self._adiar(mid, agora, f"erro ao gravar o resultado: {type(exc).__name__}")
                except Exception:
                    log.exception("não consegui nem adiar a mensagem %d; encerro o lote", mid)
                    pular.add(mid)
                    break
                processadas += 1
                continue
            processadas += 1
            if resultado is Resultado.OK:
                enviou = True
            elif resultado is Resultado.TRANSITORIO:
                break  # a Evolution está fora ou lenta: o resto espera o próximo ciclo
        try:  # sem falha na janela (reenviada, descartada ou velha), o aviso de mensagem não enviada fecha
            with self._sessoes() as s, s.begin():
                avisos.resolver_nao_enviada_sem_falhas(s, self._relogio())
        except Exception:
            log.exception("não consegui conferir o aviso de mensagem não enviada")
        if enviou:
            # a Evolution voltou: o que esperava um backoff de falha transitória tenta já
            with self._sessoes() as s, s.begin():
                acordadas = repo_msg.acordar_pendentes(s, self._relogio(), antes_de=inicio)
            if acordadas:
                log.info("%d mensagem(ns) em espera voltam à fila", acordadas)
        return processadas

    def _vigiar_manutencao(self, agora: datetime) -> None:
        """A `manutencao` vigia os outros serviços; quem vigia a `manutencao` é este. No máximo 1x/min; nunca lança."""
        if self._ultima_vigia is not None and agora - self._ultima_vigia < INTERVALO_VIGIA:
            return
        self._ultima_vigia = agora
        try:
            with self._sessoes() as s, s.begin():
                vigia.verificar_manutencao(s, agora, self._desde)
        except Exception:
            log.exception("não consegui vigiar a manutenção")

    def _adiar(self, mid: int, agora: datetime, erro: str) -> None:
        """Em transação nova (a anterior caiu): conta a tentativa e adia pelo mesmo backoff da falha de envio.
        Ao atingir `MAX_TENTATIVAS_DEFINITIVAS` vira falha, para não reenviar para sempre."""
        with self._sessoes() as s, s.begin():
            m = s.get(MensagemSaida, mid)
            if m is None or m.status != StatusMensagem.PENDENTE:
                return
            m.tentativas += 1
            m.atualizado_em = agora
            m.ultimo_erro = erro
            if m.tentativas >= MAX_TENTATIVAS_DEFINITIVAS:
                m.status = StatusMensagem.FALHA
                repo_msg.apagar_texto_individual(m)
                log.error("mensagem %d para %s falhou de vez: %s", m.id, m.destino, erro)
            else:
                m.proxima_tentativa_em = agora + _espera(m.tentativas)

    def _processar(self, s: Session, m: MensagemSaida, geral: _Destinos, agora: datetime) -> Resultado | None:
        """Devolve o resultado do envio, ou `None` se a mensagem nem chegou a ser enviada."""
        m.atualizado_em = agora
        if m.expira_em is not None and agora >= m.expira_em:
            # validade própria (código de acesso: 5 min) vale até para "reenviar"
            m.status = StatusMensagem.EXPIRADA
            repo_msg.apagar_texto_individual(m)
            return None
        validade = timedelta(hours=geral.validade_oportunidade_h)
        if m.destino == "oportunidades" and not m.ignorar_validade and agora - m.criada_em > validade:
            m.status = StatusMensagem.EXPIRADA
            return None
        individual = m.destino == Destino.INDIVIDUAL.value
        if individual:
            alvo = (m.numero or "").removeprefix("+")  # a Evolution quer só os dígitos
        else:
            alvo = geral.whatsapp_grupo_admin if m.destino == "admin" else geral.whatsapp_grupo_oportunidades
        falta = None
        if self._chave is None:
            falta = "EVOLUTION_URL ou EVOLUTION_API_KEY ausente (ou com o valor padrão) no .env"
        elif not geral.evolution_instancia:
            falta = "sem instância da Evolution em Configurações → Geral"
        elif not alvo:
            falta = "sem número na mensagem individual" if individual else f"sem grupo de {m.destino} em Configurações → Geral"
        if falta is not None:
            m.ultimo_erro = falta
            m.proxima_tentativa_em = agora + ESPERA_SEM_DESTINO
            return None
        # linhas antigas da fila e "reenviar" saem como estão gravadas: a guarda de URL vale aqui também
        texto = formato.conferir_urls(m.texto, avisos.zona_e_host(s)[1], estrito=False)
        resultado, erro = enviar_uma_vez(
            self._cliente, self._config_env.evolution_url, self._chave, geral.evolution_instancia, alvo, texto
        )
        if individual and erro and m.numero:
            erro = ocultar_numero(erro, m.numero)  # a Evolution pode repetir o número no erro
        if resultado is Resultado.OK:
            m.status = StatusMensagem.ENVIADA
            m.enviada_em = agora
            m.ultimo_erro = None
            repo_msg.apagar_texto_individual(m)
            return resultado
        m.tentativas += 1
        m.ultimo_erro = erro
        if resultado is Resultado.DEFINITIVO and m.tentativas >= MAX_TENTATIVAS_DEFINITIVAS:
            m.status = StatusMensagem.FALHA
            repo_msg.apagar_texto_individual(m)
            log.error("mensagem %d para %s falhou de vez: %s", m.id, m.destino, erro)
            if not formato.eh_do_proprio_aviso(m.texto, TipoAviso.MENSAGEM_NAO_ENVIADA):  # nunca em laço
                self._avisar_falha(s, agora)
            return resultado
        m.proxima_tentativa_em = agora + _espera(m.tentativas)
        log.warning("mensagem %d para %s não saiu (tentativa %d): %s", m.id, m.destino, m.tentativas, erro)
        return resultado

    @staticmethod
    def _avisar_falha(s: Session, agora: datetime) -> None:
        """Lista as falhas definitivas da última hora (menos os próprios avisos) para o grupo admin."""
        s.flush()
        falhas = [
            f for f in repo_msg.falhas_recentes(s, agora - JANELA_FALHAS)
            if not formato.eh_do_proprio_aviso(f.texto, TipoAviso.MENSAGEM_NAO_ENVIADA)
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
