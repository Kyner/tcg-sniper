"""Serviço `casador`: avalia com a IA os anúncios pendentes e, com o automático ligado, decide os claros."""

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
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import COLETOR_CASADOR, AnuncioAmazon, EstadoColetorTipo, OrigemCasamento, StatusCasamento
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
                if p.avaliacao is not None and p.avaliacao.assinatura == atual:
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
                self._avisar_orcamento(str(erro), zona)
                break
            except (ChaveInvalida, ConfiguracaoInvalida) as erro:
                with self._sessoes() as s, s.begin():
                    repo.pausar(s, str(erro), self._relogio(), COLETOR_CASADOR)
                self._avisador.avisar(TipoAviso.IA_PAUSADA, CHAVE_GERAL, Dados(linhas=(f"Motivo: {erro}",)))
                log.error("casador pausado: %s", erro)
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
        return avaliados

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
            if automatico and not ja_aplicada:
                return self._aplicar(s, av, limites, agora)
        return None

    @staticmethod
    def _aplicar(s: Session, av, limites: tuple[int, int], agora: datetime) -> StatusCasamento | None:
        """Automático: confirma ou ignora o anúncio se a confiança passa do limite. Só age se o anúncio
        ainda está pendente com o mesmo produto (decisão do usuário vale)."""
        confirmar, ignorar = limites
        anuncio = s.get(AnuncioAmazon, av.anuncio_id, with_for_update=True, populate_existing=True)
        if anuncio.status_casamento is not StatusCasamento.PENDENTE or anuncio.produto_id != av.produto_id:
            return None  # o usuário decidiu enquanto a IA respondia
        if av.mesmo_produto and av.confianca >= confirmar:
            repo_amz.confirmar_casamento(s, anuncio.id, av.produto_id, agora, OrigemCasamento.AUTOMATICO_IA)
            decisao = StatusCasamento.CONFIRMADO
        elif not av.mesmo_produto and av.confianca >= ignorar:
            repo_amz.ignorar_anuncio(s, anuncio.id, agora, OrigemCasamento.AUTOMATICO_IA)
            decisao = StatusCasamento.IGNORADO
        else:
            return None
        av.aplicada_em = agora
        return decisao

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
