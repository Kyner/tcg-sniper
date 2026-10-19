"""Serviço `casador`: avalia com a IA os pares (anúncio × produto) pendentes, com o automático ligado decide
os claros e, numa etapa própria do ciclo, gera os termos da busca alternativa."""

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.avisos.servico import Avisador
from tcg_sniper.casador.pergunta import assinatura, avaliar_par
from tcg_sniper.casador.termos import gerar_termos
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db import repositorio_termos as repo_termos
from tcg_sniper.db.models import COLETOR_CASADOR, EstadoColetorTipo, OrigemCasamento, StatusCasamento
from tcg_sniper.ia.modelos import (
    ChaveInvalida,
    ConfiguracaoInvalida,
    ErroIA,
    RespostaForaDoFormato,
    SemOrcamento,
    Transporte,
)

log = logging.getLogger(__name__)

PASSO_S = 30  # de quanto em quanto tempo olha se pediram "Rodar agora"
FALHAS_SEGUIDAS_MAX = 3  # falhas seguidas de chamada (rede, 5xx, 429) que encerram a rodada
ESPERAS_FALHA = (timedelta(hours=1), timedelta(hours=6), timedelta(hours=24))  # par que falhou espera; teto 24 h
TIMEOUT_IMAGEM_S = 15
TERMOS_POR_CICLO = 5  # produtos por ciclo na busca alternativa (uma chamada barata cada, sem imagem)


class ServicoCasador:
    def __init__(
        self,
        sessoes: sessionmaker[Session],
        transporte: Transporte | None,
        config_env: Config,
        avisador: Avisador,
        cliente_http: httpx.Client | None = None,
        relogio: Callable[[], datetime] | None = None,
        dormir: Callable[[float], None] | None = None,
    ):
        self._sessoes = sessoes
        self._transporte = transporte
        self._config_env = config_env
        self._avisador = avisador
        self._http = cliente_http or httpx.Client(timeout=TIMEOUT_IMAGEM_S, headers={"User-Agent": "Mozilla/5.0"})
        self._relogio = relogio or repo.agora_utc
        self._dormir = dormir
        self._parar = threading.Event()
        # (anúncio, produto) -> (assinatura, falhas seguidas, espera até): o par que falhou não trava a fila
        self._falhas: dict[tuple[int, int], tuple[str, int, datetime]] = {}

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
            pendentes = repo_ia.pares_pendentes(s, so_descoberta=True)
            self._esquecer_falhas_fora_de({(p.anuncio.id, p.produto.id) for p in pendentes})
            candidatos = []
            ja_avaliados = []  # avaliação em dia que o automático ainda não aplicou (ex.: ligado depois)
            for p in pendentes:
                atual = assinatura(p.anuncio, p.produto)
                if p.avaliacao is not None and p.avaliacao.assinatura == atual and not p.reavaliar:
                    if automatico and p.avaliacao.aplicada_em is None:
                        ja_avaliados.append((p.anuncio.id, p.produto.id))
                    continue
                if self._em_espera((p.anuncio.id, p.produto.id), atual, agora):
                    continue
                candidatos.append((p, atual))
            pares = candidatos[:lote]
            # vários anúncios podem sugerir o mesmo produto: cada objeto sai da sessão uma vez só
            for obj in {*(p.anuncio for p, _ in pares), *(p.produto for p, _ in pares)}:
                s.expunge(obj)
        self._avisador.resolver(TipoAviso.IA_PAUSADA, CHAVE_GERAL)  # ativo e ligado: uma pausa aberta acabou
        for anuncio_id, produto_id in ja_avaliados:
            with self._sessoes() as s, s.begin():
                av = repo_ia.avaliacoes_dos_pares(s, [(anuncio_id, produto_id)]).get((anuncio_id, produto_id))
                if av is not None and av.aplicada_em is None:
                    self._aplicar(s, av, limites, self._relogio())
        avaliados = falhas = confirmados = ignorados = 0
        interrompido = False  # orçamento, chave/configuração ou falhas seguidas: a etapa dos termos não roda
        chamada_ok = False
        for par, atual in pares:
            if self._parar.is_set():
                break
            chave = (par.anuncio.id, par.produto.id)
            try:
                veredito, resposta, sem_imagem = avaliar_par(
                    self._sessoes, self._transporte, self._http, par.anuncio, par.produto, par.preco_liga,
                    par.preco_amazon, finalidade="casamento", zona=zona, relogio=self._relogio,
                )
                decisao = self._gravar(par, veredito, resposta, sem_imagem, automatico, limites)
            except SemOrcamento as erro:
                interrompido = True
                self._avisar_orcamento(str(erro), zona)
                break
            except (ChaveInvalida, ConfiguracaoInvalida) as erro:
                interrompido = True
                self._pausar_por_configuracao(erro)
                break
            except RespostaForaDoFormato as erro:  # a chamada funcionou: só o par espera
                falhas = 0
                self._marcar_falha(chave, atual)
                log.warning("resposta fora do formato no anúncio %s: %s", par.anuncio.asin, erro)
                continue
            except ErroIA as erro:  # falha da chamada: o par espera e, se repetir, a rodada acaba
                falhas += 1
                self._marcar_falha(chave, atual)
                log.warning("IA falhou no anúncio %s: %s", par.anuncio.asin, erro)
                if falhas >= FALHAS_SEGUIDAS_MAX:
                    dados = Dados(
                        linhas=(f"{FALHAS_SEGUIDAS_MAX} chamadas seguidas falharam; a rodada parou", f"Última: {erro}")
                    )
                    self._avisador.avisar(TipoAviso.IA_FALHAS_SEGUIDAS, CHAVE_GERAL, dados)
                    interrompido = True
                    break
                continue
            except Exception:
                self._marcar_falha(chave, atual)
                log.exception("erro inesperado no anúncio %s; segue para o próximo", par.anuncio.asin)
                continue
            if not chamada_ok:  # a primeira chamada ok da rodada fecha falhas seguidas e falta de orçamento
                chamada_ok = True
                self._avisador.resolver(TipoAviso.IA_FALHAS_SEGUIDAS, CHAVE_GERAL)
                self._avisador.resolver_todos(TipoAviso.IA_SEM_ORCAMENTO)
            falhas = 0
            self._falhas.pop(chave, None)
            avaliados += 1
            confirmados += decisao is StatusCasamento.CONFIRMADO
            ignorados += decisao is StatusCasamento.IGNORADO
        if avaliados:
            esperando = avaliados - confirmados - ignorados
            dados = Dados(
                linhas=(
                    f"Avaliados: {avaliados}",
                    f"Confirmados pelo automático: {confirmados}",
                    f"Ignorados pelo automático: {ignorados}",
                    f"Esperando você: {esperando}",
                ),
                acao="Revise os pendentes em Admin → Casamentos." if esperando else None,
            )
            self._avisador.avisar(TipoAviso.IA_RODADA_CONCLUIDA, CHAVE_GERAL, dados)
        if not interrompido and not self._parar.is_set():
            self._gerar_termos(zona)
        return avaliados

    def _pausar_por_configuracao(self, erro: Exception) -> None:
        with self._sessoes() as s, s.begin():
            repo.pausar(s, str(erro), self._relogio(), COLETOR_CASADOR)
        self._avisador.avisar(TipoAviso.IA_PAUSADA, CHAVE_GERAL, Dados(linhas=(f"Motivo: {erro}",)))
        log.error("casador pausado: %s", erro)

    def _em_espera(self, chave: tuple[int, int], atual: str, agora: datetime) -> bool:
        falha = self._falhas.get(chave)
        if falha is None:
            return False
        if falha[0] != atual:  # dados mudaram: tenta de novo já
            del self._falhas[chave]
            return False
        return agora < falha[2]

    def _marcar_falha(self, chave: tuple[int, int], atual: str) -> None:
        anterior = self._falhas.get(chave)
        n = anterior[1] + 1 if anterior is not None and anterior[0] == atual else 1
        espera = ESPERAS_FALHA[min(n, len(ESPERAS_FALHA)) - 1]
        self._falhas[chave] = (atual, n, self._relogio() + espera)

    def _esquecer_falhas_fora_de(self, pendentes: set[tuple[int, int]]) -> None:
        for chave in self._falhas.keys() - pendentes:
            del self._falhas[chave]

    def _gravar(self, par, veredito, resposta, sem_imagem, automatico, limites) -> StatusCasamento | None:
        agora = self._relogio()
        with self._sessoes() as s, s.begin():
            anterior = repo_ia.avaliacoes_dos_pares(s, [(par.anuncio.id, par.produto.id)]).get((par.anuncio.id, par.produto.id))
            ja_aplicada = anterior is not None and anterior.aplicada_em is not None
            av = repo_ia.gravar_avaliacao(
                s, anuncio_id=par.anuncio.id, produto_id=par.produto.id, mesmo_produto=veredito.mesmo_produto,
                confianca=veredito.confianca, motivo=veredito.motivo, modelo=resposta.modelo,
                assinatura=assinatura(par.anuncio, par.produto), sem_imagem=sem_imagem,
                chamada_id=resposta.chamada_id, agora=agora,
            )
            repo_casamento.marcar_reavaliado(s, par.anuncio.id, par.produto.id)
            if automatico and not ja_aplicada:
                return self._aplicar(s, av, limites, agora)
        return None

    @staticmethod
    def _aplicar(s: Session, av, limites: tuple[int, int], agora: datetime) -> StatusCasamento | None:
        """Automático: confirma ou ignora o par se a confiança passa do limite. Só age se o par ainda está
        pendente (decisão sua vale) e o anúncio não foi confirmado para outro produto nesse meio-tempo."""
        confirmar, ignorar = limites
        repo_casamento.travar_anuncio(s, av.anuncio_id)
        par = repo_casamento.obter_par(s, av.anuncio_id, av.produto_id)
        if par is None or par.status is not StatusCasamento.PENDENTE:
            return None  # você decidiu enquanto a IA respondia
        try:
            if av.mesmo_produto and av.confianca >= confirmar:
                repo_casamento.confirmar(s, av.anuncio_id, av.produto_id, agora, OrigemCasamento.AUTOMATICO_IA)
                decisao = StatusCasamento.CONFIRMADO
            elif not av.mesmo_produto and av.confianca >= ignorar:
                repo_casamento.ignorar(s, av.anuncio_id, av.produto_id, agora, OrigemCasamento.AUTOMATICO_IA)
                decisao = StatusCasamento.IGNORADO
            else:
                return None
        except repo_casamento.JaConfirmado as erro:
            log.info("anúncio %s já confirmado para o produto %s: o automático não age", av.anuncio_id, erro.produto_id)
            return None
        av.aplicada_em = agora
        return decisao

    def _gerar_termos(self, zona: ZoneInfo) -> int:
        """Busca alternativa: gera os termos dos produtos pedidos no admin e dos em seca sem termos, no máximo
        `TERMOS_POR_CICLO`. Para no primeiro SemOrcamento (o pedido fica para o próximo período, com o aviso de
        teto de sempre). Sem termo válido ou resposta fora do formato: marca a tentativa (7 dias)."""
        with self._sessoes() as s, s.begin():
            produtos = repo_termos.produtos_para_gerar_termos(s, self._relogio(), TERMOS_POR_CICLO)
            for produto in produtos:
                s.expunge(produto)
        gerados = 0
        for produto in produtos:
            if self._parar.is_set():
                break
            try:
                termos = gerar_termos(self._sessoes, self._transporte, produto, zona=zona, relogio=self._relogio)
            except SemOrcamento as erro:
                self._avisar_orcamento(str(erro), zona)
                break
            except (ChaveInvalida, ConfiguracaoInvalida) as erro:
                self._pausar_por_configuracao(erro)
                break
            except RespostaForaDoFormato as erro:
                log.warning("termos do produto %s fora do formato: %s", produto.id, erro)
                termos = []
            except ErroIA as erro:
                log.warning("IA falhou ao gerar termos do produto %s: %s", produto.id, erro)
                continue
            except Exception:
                log.exception("erro inesperado ao gerar termos do produto %s; segue para o próximo", produto.id)
                continue
            with self._sessoes() as s, s.begin():
                if termos:
                    repo_termos.guardar_termos(s, produto.id, termos, self._relogio())
                    gerados += 1
                else:
                    repo_termos.marcar_tentativa(s, produto.id, self._relogio())
        if gerados:
            log.info("busca alternativa: termos gerados para %d produto(s)", gerados)
        return gerados

    def _avisar_orcamento(self, motivo: str, zona) -> None:
        local = self._relogio().astimezone(zona)
        periodo = f"mês {local:%m/%Y}" if "mensal" in motivo else f"dia {local:%d/%m}"
        log.warning("casador sem orçamento: %s", motivo)
        dados = Dados(titulo_extra=periodo, linhas=(f"Motivo: {motivo}",))
        self._avisador.avisar(TipoAviso.IA_SEM_ORCAMENTO, periodo, dados)

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
                    try:
                        self.ciclo()
                    finally:  # com erro também: não repete (nem paga) a cada passo
                        proxima = self._relogio() + intervalo
            except Exception:
                log.exception("erro no ciclo do casador; tenta de novo no próximo passo")
            if self._dormir is not None:
                self._dormir(PASSO_S)
            else:
                self._parar.wait(PASSO_S)
        log.info("casador encerrado")
