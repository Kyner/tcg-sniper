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
IDIOMAS_NUNCA_CONFIRMAR = ("ja", "outro")  # sempre outro produto: o automático nunca os confirma
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
            candidatos = []
            ja_avaliados = []  # avaliação em dia que o automático ainda não aplicou (ex.: ligado depois)
            for p in pendentes:
                atual = assinatura(p.anuncio, p.produto)
                if p.avaliacao is not None and p.avaliacao.assinatura == atual and not p.reavaliar:
                    if automatico and p.avaliacao.aplicada_em is None:
                        ja_avaliados.append((p.anuncio.id, p.produto.id))
                    continue
                if self._em_espera(p, atual, agora):
                    continue
                candidatos.append((p, atual))
            pares = candidatos[:lote]
            # o que a pergunta diz do português confirmado (fora da assinatura: muda sem reavaliar)
            portugues = {p.produto.id: repo_ia.portugues_confirmado(s, p.produto.id) for p, _ in pares}
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
        produtos_avaliados: set[int] = set()  # a rodada conta anúncios; o aviso diz em quantos produtos
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
                    portugues_confirmado=portugues[par.produto.id],
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
            with self._sessoes() as s, s.begin():
                repo_ia.limpar_falha_par(s, *chave)
            avaliados += 1
            produtos_avaliados.add(par.produto.id)
            confirmados += decisao is StatusCasamento.CONFIRMADO
            ignorados += decisao is StatusCasamento.IGNORADO
        if avaliados:
            esperando = avaliados - confirmados - ignorados
            anuncios = f"{avaliados} {'anúncio' if avaliados == 1 else 'anúncios'}"
            produtos = f"{len(produtos_avaliados)} {'produto' if len(produtos_avaliados) == 1 else 'produtos'}"
            dados = Dados(
                linhas=(
                    f"Avaliados: {anuncios} em {produtos}",
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

    @staticmethod
    def _em_espera(par: repo_ia.ParPendente, atual: str, agora: datetime) -> bool:
        """O par que falhou espera (gravado no banco, sobrevive a reinício); dados mudados: tenta já."""
        if par.ia_espera_ate is None or par.ia_falha_assinatura != atual:
            return False
        return agora < par.ia_espera_ate

    def _marcar_falha(self, chave: tuple[int, int], atual: str) -> None:
        with self._sessoes() as s, s.begin():
            repo_ia.registrar_falha_par(s, *chave, atual, self._relogio(), ESPERAS_FALHA)

    def _gravar(self, par, veredito, resposta, sem_imagem, automatico, limites) -> StatusCasamento | None:
        agora = self._relogio()
        with self._sessoes() as s, s.begin():
            anterior = repo_ia.avaliacoes_dos_pares(s, [(par.anuncio.id, par.produto.id)]).get((par.anuncio.id, par.produto.id))
            ja_aplicada = anterior is not None and anterior.aplicada_em is not None
            av = repo_ia.gravar_avaliacao(
                s, anuncio_id=par.anuncio.id, produto_id=par.produto.id, mesmo_produto=veredito.mesmo_produto,
                confianca=veredito.confianca, motivo=veredito.motivo, modelo=resposta.modelo,
                assinatura=assinatura(par.anuncio, par.produto), sem_imagem=sem_imagem,
                chamada_id=resposta.chamada_id, agora=agora, idioma_anuncio=veredito.idioma_anuncio,
            )
            repo_casamento.marcar_reavaliado(s, par.anuncio.id, par.produto.id)
            if automatico and not ja_aplicada:
                return self._aplicar(s, av, limites, agora)
        return None

    @staticmethod
    def _aplicar(s: Session, av, limites: tuple[int, int], agora: datetime) -> StatusCasamento | None:
        """Automático: confirma ou ignora o par se a confiança passa do limite. Só age se o par ainda está
        pendente (decisão sua vale) e o anúncio não foi confirmado para outro produto nesse meio-tempo.
        Regra de idioma: nunca confirma anúncio japonês ou de outro idioma, e confirma o inglês só se o
        produto não tem anúncio em português confirmado (nem confirmado de idioma não registrado); senão o
        par fica pendente para você. Avaliação sem idioma (de antes da regra) segue como antes."""
        confirmar, ignorar = limites
        repo_casamento.travar_anuncio(s, av.anuncio_id)
        par = repo_casamento.obter_par(s, av.anuncio_id, av.produto_id)
        if par is None or par.status is not StatusCasamento.PENDENTE:
            return None  # você decidiu enquanto a IA respondia
        try:
            if av.mesmo_produto and av.confianca >= confirmar:
                if not ServicoCasador._idioma_permite_confirmar(s, av):
                    return None
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

    @staticmethod
    def _idioma_permite_confirmar(s: Session, av) -> bool:
        if av.idioma_anuncio in IDIOMAS_NUNCA_CONFIRMAR:
            return False
        if av.idioma_anuncio in ("en", "indefinido"):  # idioma que não se leu com certeza: segue a regra do inglês
            return repo_ia.portugues_confirmado(s, av.produto_id) is False
        return True

    def _gerar_termos(self, zona: ZoneInfo) -> int:
        """Busca alternativa: gera os termos dos produtos pedidos no admin e dos em seca sem termos, no máximo
        `TERMOS_POR_CICLO`. Para no primeiro SemOrcamento (o pedido fica para o próximo período, com o aviso de
        teto de sempre). Sem termo válido ou resposta fora do formato: marca a tentativa (7 dias). Falha da
        chamada ou erro inesperado (também ao gravar): o produto espera (1 h, 6 h, 24 h, gravado no banco) sem
        marcar a tentativa; `FALHAS_SEGUIDAS_MAX` falhas seguidas da chamada encerram a etapa com o aviso."""
        agora = self._relogio()
        with self._sessoes() as s, s.begin():
            produtos = repo_termos.produtos_para_gerar_termos(s, agora, TERMOS_POR_CICLO)
            for produto in produtos:
                s.expunge(produto)
        gerados = falhas = 0
        for produto in produtos:
            if self._parar.is_set():
                break
            try:
                try:
                    termos = gerar_termos(self._sessoes, self._transporte, produto, zona=zona, relogio=self._relogio)
                except RespostaForaDoFormato as erro:  # a chamada funcionou: conta como tentativa sem termo
                    log.warning("termos do produto %s fora do formato: %s", produto.id, erro)
                    termos = []
                with self._sessoes() as s, s.begin():
                    if termos:
                        repo_termos.guardar_termos(s, produto.id, termos, self._relogio())
                    else:
                        repo_termos.marcar_tentativa(s, produto.id, self._relogio())
            except SemOrcamento as erro:
                self._avisar_orcamento(str(erro), zona)
                break
            except (ChaveInvalida, ConfiguracaoInvalida) as erro:
                self._pausar_por_configuracao(erro)
                break
            except ErroIA as erro:
                falhas += 1
                self._marcar_falha_termos(produto.id)
                log.warning("IA falhou ao gerar termos do produto %s: %s", produto.id, erro)
                if falhas >= FALHAS_SEGUIDAS_MAX:
                    dados = Dados(
                        linhas=(
                            f"{FALHAS_SEGUIDAS_MAX} chamadas seguidas falharam; a geração de termos parou",
                            f"Última: {erro}",
                        )
                    )
                    self._avisador.avisar(TipoAviso.IA_FALHAS_SEGUIDAS, CHAVE_GERAL, dados)
                    break
                continue
            except Exception:
                self._marcar_falha_termos(produto.id)
                log.exception("erro inesperado ao gerar termos do produto %s; segue para o próximo", produto.id)
                continue
            falhas = 0
            with self._sessoes() as s, s.begin():
                repo_termos.limpar_falha_termos(s, produto.id)
            gerados += bool(termos)
        if gerados:
            log.info("busca alternativa: termos gerados para %d produto(s)", gerados)
        return gerados

    def _marcar_falha_termos(self, produto_id: int) -> None:
        with self._sessoes() as s, s.begin():
            repo_termos.registrar_falha_termos(s, produto_id, self._relogio(), ESPERAS_FALHA)

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
