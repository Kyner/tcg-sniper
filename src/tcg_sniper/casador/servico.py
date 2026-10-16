"""Serviço `casador`: avalia com a IA os anúncios pendentes e, com o automático ligado, decide os claros."""

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.casador.pergunta import assinatura, avaliar_par
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import COLETOR_CASADOR, AnuncioAmazon, EstadoColetorTipo, StatusCasamento
from tcg_sniper.ia.modelos import ChaveInvalida, ErroIA, SemOrcamento, Transporte
from tcg_sniper.notificador.base import Destino, Notificador

log = logging.getLogger(__name__)

PASSO_S = 30  # de quanto em quanto tempo olha se pediram "Rodar agora"
FALHAS_SEGUIDAS_MAX = 3
TIMEOUT_IMAGEM_S = 15


class ServicoCasador:
    def __init__(
        self,
        sessoes: sessionmaker[Session],
        transporte: Transporte | None,
        config_env: Config,
        notificador: Notificador,
        cliente_http: httpx.Client | None = None,
        relogio: Callable[[], datetime] | None = None,
        dormir: Callable[[float], None] | None = None,
    ):
        self._sessoes = sessoes
        self._transporte = transporte
        self._config_env = config_env
        self._notificador = notificador
        self._http = cliente_http or httpx.Client(timeout=TIMEOUT_IMAGEM_S, headers={"User-Agent": "Mozilla/5.0"})
        self._relogio = relogio or repo.agora_utc
        self._dormir = dormir
        self._parar = threading.Event()
        self._avisos_orcamento: set[str] = set()

    def parar(self) -> None:
        self._parar.set()

    def ciclo(self) -> int:
        """Uma rodada: até `lote` pares sem avaliação ou com dados mudados. Devolve quantos avaliou."""
        if self._transporte is None:
            return 0
        agora = self._relogio()
        with self._sessoes() as s, s.begin():
            estado = repo.obter_estado(s, agora, COLETOR_CASADOR)
            cfg = repo_ia.obter_config_ia(s)
            if estado.estado is not EstadoColetorTipo.ATIVO or not cfg.ligado:
                return 0
            zona = ZoneInfo(repo.obter_config_geral(s, self._config_env).fuso)
            lote, automatico = cfg.lote, cfg.automatico
            limites = (cfg.confianca_confirmar, cfg.confianca_ignorar)
            pares = [
                p for p in repo_ia.pares_pendentes(s)
                if p.avaliacao is None or p.avaliacao.assinatura != assinatura(p.anuncio, p.produto)
            ][:lote]
            # vários anúncios podem sugerir o mesmo produto: cada objeto sai da sessão uma vez só
            for obj in {*(p.anuncio for p in pares), *(p.produto for p in pares)}:
                s.expunge(obj)
        avaliados = falhas = 0
        for par in pares:
            if self._parar.is_set():
                break
            try:
                veredito, resposta, sem_imagem = avaliar_par(
                    self._sessoes, self._transporte, self._http, par.anuncio, par.produto, par.preco_liga,
                    par.preco_amazon, finalidade="casamento", zona=zona, relogio=self._relogio,
                )
            except SemOrcamento as erro:
                self._avisar_orcamento(str(erro), zona)
                break
            except ChaveInvalida as erro:
                with self._sessoes() as s, s.begin():
                    repo.pausar(s, str(erro), self._relogio(), COLETOR_CASADOR)
                self._notificador.enviar(Destino.ADMIN, f"⚠️ Casador (IA) pausado: {erro}. Corrija e clique em Retomar em Serviços.")
                log.error("casador pausado: %s", erro)
                break
            except ErroIA as erro:
                falhas += 1
                log.warning("IA falhou no anúncio %s: %s", par.anuncio.asin, erro)
                if falhas >= FALHAS_SEGUIDAS_MAX:
                    break
                continue
            falhas = 0
            self._gravar(par, veredito, resposta, sem_imagem, automatico, limites)
            avaliados += 1
        return avaliados

    def _gravar(self, par, veredito, resposta, sem_imagem, automatico, limites) -> None:
        agora = self._relogio()
        confirmar, ignorar = limites
        with self._sessoes() as s, s.begin():
            anterior = repo_ia.avaliacoes_dos_pares(s, [(par.anuncio.id, par.produto.id)]).get((par.anuncio.id, par.produto.id))
            ja_aplicada = anterior is not None and anterior.aplicada_em is not None
            av = repo_ia.gravar_avaliacao(
                s, anuncio_id=par.anuncio.id, produto_id=par.produto.id, mesmo_produto=veredito.mesmo_produto,
                confianca=veredito.confianca, motivo=veredito.motivo, modelo=resposta.modelo,
                assinatura=assinatura(par.anuncio, par.produto), sem_imagem=sem_imagem,
                chamada_id=resposta.chamada_id, agora=agora,
            )
            if not automatico or ja_aplicada:
                return
            anuncio = s.get(AnuncioAmazon, par.anuncio.id, with_for_update=True, populate_existing=True)
            if anuncio.status_casamento is not StatusCasamento.PENDENTE or anuncio.produto_id != par.produto.id:
                return  # o usuário decidiu enquanto a IA respondia
            if veredito.mesmo_produto and veredito.confianca >= confirmar:
                repo_amz.confirmar_casamento(s, anuncio.id, par.produto.id, agora)
            elif not veredito.mesmo_produto and veredito.confianca >= ignorar:
                repo_amz.ignorar_anuncio(s, anuncio.id, agora)
            else:
                return
            av.aplicada_em = agora

    def _avisar_orcamento(self, motivo: str, zona) -> None:
        local = self._relogio().astimezone(zona)
        chave = f"mes:{local:%Y-%m}" if "mensal" in motivo else f"dia:{local:%Y-%m-%d}"
        log.warning("casador sem orçamento: %s", motivo)
        if chave in self._avisos_orcamento:
            return
        self._avisos_orcamento.add(chave)
        self._notificador.enviar(Destino.ADMIN, f"⚠️ Casador (IA) parado: {motivo}. Volta sozinho no próximo período ou ao subir o teto em Configurações → IA.")

    def rodar(self) -> None:
        log.info("casador iniciado")
        if self._transporte is None:
            log.warning("OPENAI_API_KEY ausente no .env: o casador não chama a IA")
        proxima = self._relogio()
        while not self._parar.is_set():
            agora = self._relogio()
            try:
                with self._sessoes() as s, s.begin():
                    pedida = repo.consumir_solicitacao(s, agora, COLETOR_CASADOR)
                    intervalo = timedelta(minutes=repo_ia.obter_config_ia(s).intervalo_min)
                if pedida or agora >= proxima:
                    self.ciclo()
                    proxima = self._relogio() + intervalo
            except Exception:
                log.exception("erro no ciclo do casador; tenta de novo no próximo passo")
            if self._dormir is not None:
                self._dormir(PASSO_S)
            else:
                self._parar.wait(PASSO_S)
        log.info("casador encerrado")
