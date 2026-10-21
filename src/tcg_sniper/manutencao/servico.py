"""Serviço `manutencao`: uma vez por dia (04:00 no fuso de Configurações → Geral) faz o backup do
banco, copia para o R2 (se configurado) e, com o backup local feito, limpa o histórico antigo.

- Uma execução por dia local: reiniciar não repete (a execução que caiu no meio não conta).
- Ao subir, se o último backup ok tem mais de 24 h, roda já (PC desligado às 04:00).
- A cada passo, o vigia confere o sinal de vida dos outros serviços (`avisos/vigia.py`).
- Falha (dump, validação, R2 ou limpeza): grava o erro e avisa o grupo admin (`BACKUP_ERRO`, com lembrete
  enquanto continuar); ok avisa `BACKUP_CONCLUIDO`. Tenta de novo no dia seguinte. Sem as variáveis R2_*,
  o backup fica só no PC ("só local").
"""

import logging
import threading
from collections.abc import Callable, Iterable
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.avisos import vigia
from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.avisos.servico import Avisador
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_manutencao as repo_man
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db import retencao
from tcg_sniper.db.models import COLETOR_MANUTENCAO, EstadoColetorTipo, StatusManutencao
from tcg_sniper.formatacao import formatar_bytes
from tcg_sniper.manutencao import backup, imagens
from tcg_sniper.manutencao.r2 import Enviador, criar_enviador_imagens

log = logging.getLogger(__name__)

HORA_BACKUP = time(4, 0)
ATRASO_RECUPERAR = timedelta(hours=24)
PASSO_S = 60
MAX_ERRO = 300  # caracteres do erro gravado e enviado


def limpar_texto(texto: str, segredos: Iterable[str]) -> str:
    """Tira os segredos (chaves do R2, senha do banco) e quebras de linha; corta em `MAX_ERRO`."""
    for segredo in segredos:
        if segredo and len(segredo) >= 6:
            texto = texto.replace(segredo, "***")
    texto = " ".join(texto.split())
    return texto if len(texto) <= MAX_ERRO else texto[: MAX_ERRO - 1] + "…"


class ServicoManutencao:
    def __init__(
        self,
        sessoes: sessionmaker[Session],
        config_env: Config,
        avisador: Avisador,
        enviador: Enviador | None,
        executar: backup.Executar = backup.executar_comando,
        relogio: Callable[[], datetime] | None = None,
        dormir: Callable[[float], None] | None = None,
        enviador_imagens: imagens.EnviadorImagens | None = None,
        http: httpx.Client | None = None,
    ):
        self._sessoes = sessoes
        self._config_env = config_env
        self._avisador = avisador
        self._enviador = enviador
        self._executar = executar
        self._relogio = relogio or repo.agora_utc
        self._dormir = dormir
        self._parar = threading.Event()
        self._recuperar = True  # a primeira passada (serviço ativo) confere se o backup está atrasado
        self._conexao = backup.conexao_do_banco(config_env.database_url)
        self._segredos = (*getattr(enviador, "segredos", ()), self._conexao.senha or "")
        self._vigia_desde = self._relogio()
        self._enviador_imagens = enviador_imagens or criar_enviador_imagens(config_env)
        self._http = http or httpx.Client()
        self._imagens_em: datetime | None = None

    def parar(self) -> None:
        """Pede o encerramento: a execução em andamento termina e `rodar` volta."""
        self._parar.set()

    def inicializar(self) -> None:
        with self._sessoes() as s, s.begin():
            interrompidas = repo_man.marcar_interrompidas(s, self._relogio())
        if interrompidas:
            log.warning("%d execução(ões) da manutenção interrompida(s) no meio; o dia roda de novo", interrompidas)
            dados = Dados(
                linhas=(f"{interrompidas} execução(ões) interrompida(s) no meio: o serviço de manutenção reiniciou",)
            )
            self._avisador.avisar(TipoAviso.BACKUP_INTERROMPIDO, CHAVE_GERAL, dados)

    def tick(self) -> bool:
        """Registra que está vivo, roda a execução do dia se for a hora (devolve se rodou) e, depois dela,
        o lote de imagens da hora: o backup nunca espera a cópia das imagens."""
        try:
            return self._tick_backup()
        finally:
            self._copiar_imagens()

    def _copiar_imagens(self) -> None:
        enviador = self._enviador_imagens
        if enviador is None:
            return
        agora = self._relogio()
        if self._imagens_em is not None and agora - self._imagens_em < timedelta(hours=1):
            return
        self._imagens_em = agora
        segredos = getattr(enviador, "segredos", ())
        try:
            imagens.copiar_lote(
                self._sessoes, enviador, self._http, limpar=lambda t: limpar_texto(t, segredos)
            )
        except Exception as erro:  # noqa: BLE001 - a cópia das imagens nunca derruba a manutenção
            log.error("erro inesperado na cópia das imagens: %s", limpar_texto(f"{type(erro).__name__}: {erro}", segredos))

    def _tick_backup(self) -> bool:
        agora = self._relogio()
        try:  # apaga o código de acesso vencido mesmo com o notificador parado
            with self._sessoes() as s, s.begin():
                repo_msg.expirar_individuais_vencidas(s, agora)
        except Exception:
            log.exception("não consegui expirar os códigos vencidos")
        with self._sessoes() as s, s.begin():
            repo_man.registrar_ciclo(s, agora)
            vigia.verificar(s, agora, self._vigia_desde)  # roda também com o backup desligado
            if repo.obter_estado(s, agora, COLETOR_MANUTENCAO).estado is not EstadoColetorTipo.ATIVO:
                return False
            zona = ZoneInfo(repo.obter_config_geral(s, self._config_env).fuso)
            local = agora.astimezone(zona)
            inicio_do_dia = local.replace(hour=0, minute=0, second=0, microsecond=0)
            horario = inicio_do_dia.replace(hour=HORA_BACKUP.hour, minute=HORA_BACKUP.minute)
            # (início, deu erro) das execuções de hoje, fora das interrompidas
            hoje = [(e.inicio, e.status is StatusManutencao.ERRO) for e in repo_man.execucoes_desde(s, inicio_do_dia)]
            ultima = repo_man.ultima_ok(s)
        recuperar, self._recuperar = self._recuperar, False
        if hoje:
            # Só um erro da recuperação de madrugada (antes do horário) ganha mais uma tentativa no horário.
            so_erro_de_madrugada = all(erro and inicio < horario for inicio, erro in hoje)
            if not (so_erro_de_madrugada and local >= horario):
                return False
            log.info("a recuperação da madrugada falhou; tenta de novo no horário")
            self.executar(agora)
            return True
        atrasado = recuperar and (ultima is None or agora - ultima.inicio > ATRASO_RECUPERAR)
        if local.time() < HORA_BACKUP and not atrasado:
            return False
        if atrasado and local.time() < HORA_BACKUP:
            log.info("último backup ok: %s; roda já (atrasado)", ultima.inicio if ultima else "nenhum")
        self.executar(agora)
        return True

    def executar(self, agora: datetime) -> None:
        """Backup, rodízio, cópia no R2 e limpeza; grava a execução e avisa o admin se algo falhou."""
        with self._sessoes() as s, s.begin():
            execucao_id = repo_man.iniciar(s, agora).id
            dia = agora.astimezone(ZoneInfo(repo.obter_config_geral(s, self._config_env).fuso)).date()
        pasta = self._config_env.pasta_backups
        erros: list[str] = []
        arquivos = None
        enviado = False
        apagados = None
        try:
            arquivos = backup.fazer_backup(pasta, dia, self._conexao, self._executar)
            log.info("backup gravado: %s (%d bytes)", arquivos.diario.name, arquivos.tamanho)
            if arquivos.erro_semanal is not None:
                erros.append(arquivos.erro_semanal)
        except backup.ErroBackup as erro:
            erros.append(str(erro))
        except Exception as erro:
            log.exception("erro inesperado no backup")
            erros.append(f"erro inesperado no backup: {type(erro).__name__}")
        if arquivos is not None:
            try:
                removidos = backup.rodiziar(pasta)
                if removidos:
                    log.info("rodízio apagou %d backup(s) antigo(s): %s", len(removidos), ", ".join(removidos))
            except OSError as erro:
                erros.append(f"rodízio dos backups falhou: {erro.strerror or erro}")
            if self._enviador is not None:
                try:
                    self._enviador.enviar(arquivos.diario, backup.chave_r2_diario(dia))
                    if arquivos.semanal is not None:
                        self._enviador.enviar(arquivos.semanal, backup.chave_r2_semanal(dia))
                    enviado = True
                except Exception as erro:  # noqa: BLE001 - sem log da exceção crua: o texto passa por limpar_texto
                    erros.append(f"envio ao R2 falhou: {type(erro).__name__}: {erro}")
            try:
                apagados = retencao.limpar_historico(self._sessoes, self._relogio())
                log.info("limpeza do histórico: %s", ", ".join(f"{t} {n}" for t, n in apagados.items()))
            except Exception as erro:
                log.exception("limpeza do histórico falhou")
                erros.append(f"limpeza do histórico falhou: {type(erro).__name__}")
        erro_texto = limpar_texto("; ".join(erros), self._segredos) if erros else None
        if erro_texto is not None:
            status = StatusManutencao.ERRO
        else:
            status = StatusManutencao.OK if self._enviador is not None else StatusManutencao.SO_LOCAL
        with self._sessoes() as s, s.begin():
            repo_man.finalizar(
                s, execucao_id, self._relogio(), status,
                arquivo=arquivos.diario.name if arquivos else None,
                tamanho_bytes=arquivos.tamanho if arquivos else None,
                enviado_r2=enviado, apagados=apagados, erro=erro_texto,
            )
        if erro_texto is None:
            log.info("manutenção de %s concluída: %s", f"{dia:%d/%m}", status.value)
            apagadas = sum((apagados or {}).values())
            dados = Dados(
                titulo_extra=f"{dia:%d/%m}",
                linhas=(
                    f"Tamanho: {formatar_bytes(arquivos.tamanho)}",
                    f"Cópia no R2: {'sim' if enviado else 'não (só local)'}",
                    f"Linhas antigas apagadas: {apagadas:,}".replace(",", "."),
                ),
            )
            self._avisador.avisar(TipoAviso.BACKUP_CONCLUIDO, CHAVE_GERAL, dados)
            self._avisador.resolver(TipoAviso.BACKUP_ERRO, CHAVE_GERAL)
            return
        log.error("manutenção de %s com erro: %s", f"{dia:%d/%m}", erro_texto)
        local = "O backup local ficou salvo" if arquivos else "Nenhum backup novo foi gravado"
        dados = Dados(titulo_extra=f"{dia:%d/%m}", linhas=(f"Erro: {erro_texto}", local))
        self._avisador.avisar(TipoAviso.BACKUP_ERRO, CHAVE_GERAL, dados)

    def rodar(self) -> None:
        log.info("manutenção iniciada (backup diário às %s)", f"{HORA_BACKUP:%H:%M}")
        if self._enviador is None:
            log.warning("R2_* vazias no .env: o backup fica só no PC (só local)")
        if self._enviador_imagens is None:
            log.warning("R2_BUCKET_IMAGENS vazia: sem cópia das imagens (as telas saem sem foto)")
        self.inicializar()
        while not self._parar.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("erro no ciclo da manutenção; tenta de novo em %d s", PASSO_S)
            if self._dormir is not None:
                self._dormir(PASSO_S)
            else:
                self._parar.wait(PASSO_S)
        log.info("manutenção encerrada")
