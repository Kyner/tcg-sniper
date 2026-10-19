"""Serviço `coletor-amazon-busca`: a descoberta (fila de buscas) num navegador próprio, sem login. Por
passo, no máximo uma busca: sincroniza a fila, pega o produto vencido há mais tempo, escolhe o termo
(português, inglês e, na seca, os termos guardados da IA), busca, reagenda e fecha o ciclo quando não sobra
busca pendente. Só dentro de `janela_inicio`–`janela_fim` e com o teto `max_buscas_hora`.

Não importa checkout, carrinho nem monitor (teste `test_lacos_separados.py`): este navegador nunca abre o
carrinho nem a conta.

Avisos de fim: `AMAZON_BUSCA_CONCLUIDA`/`PARCIAL`/`FALHOU` só quando o ciclo termina de verdade (sem busca
pendente; uma pausa no meio só avisa a pausa, e a janela que fecha no meio não avisa)."""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.avisos.formato import formatar_duracao
from tcg_sniper.coletor_amazon.busca import CotaHtmlFalha, DesafioAmazon, processar_produto
from tcg_sniper.coletor_amazon.fila import intervalo_busca
from tcg_sniper.coletor_amazon.termo import sequencia_de_termos
from tcg_sniper.coletor_amazon.varredura_base import (
    ESPERA_OCIOSA_S,
    MAX_FALHAS_SEGUIDAS,
    ORIGEM_BUSCA,
    VarreduraBase,
)
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_termos as repo_termos
from tcg_sniper.db.models import ConfigAmazon, EstadoColetorTipo, ProdutoLiga, StatusColeta, TipoColeta
from tcg_sniper.navegador.modelos import ErroRede
from tcg_sniper.parsing import ErroParser

log = logging.getLogger(__name__)

TIPOS_AMAZON = (TipoColeta.AMAZON,)


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


class VarreduraBusca(VarreduraBase):
    origem = ORIGEM_BUSCA

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ciclo: int | None = None
        self._pendentes: set[int] = set()
        self._ok = 0
        self._falha = 0
        self._ciclo_inicio: datetime | None = None
        self._cota_falhas = CotaHtmlFalha()

    def inicializar(self) -> None:
        super().inicializar()
        with self._sessoes() as s, s.begin():
            interrompidos = repo.marcar_interrompidas(s, self._relogio(), TIPOS_AMAZON)
        if interrompidos:
            log.warning("%d ciclo(s) da busca na Amazon interrompido(s) marcados como falha", interrompidos)
            dados = Dados(linhas=(f"{interrompidos} ciclo(s) marcado(s) como falha: o serviço de busca reiniciou",))
            self._avisador.avisar(TipoAviso.AMAZON_INTERROMPIDA, CHAVE_GERAL, dados)

    def passo(self) -> float:
        """No máximo uma busca. Devolve quantos segundos dormir antes do próximo passo."""
        agora = self._relogio()
        cfg, estado = self._inicio_do_passo(agora)
        if not self._janela(agora, "busca", cfg.janela_inicio, cfg.janela_fim).contem(agora):
            self._encerrar_ciclo(cfg)
            self.fechar_navegador()
            return ESPERA_OCIOSA_S
        if estado is not EstadoColetorTipo.ATIVO:
            return ESPERA_OCIOSA_S  # pausada (o navegador fica aberto num CAPTCHA, para resolver no noVNC)
        return self._passo_descoberta(agora, cfg)

    # --- ciclo -----------------------------------------------------------------------------------

    def _iniciar_ciclo(self, agora: datetime, na_fila: set[int]) -> None:
        with self._sessoes() as s, s.begin():
            self._ciclo = repo.iniciar_coleta(s, TipoColeta.AMAZON, agora).id
        self._pendentes = set(na_fila)
        self._ok = self._falha = 0
        self._ciclo_inicio = agora
        self._cota_falhas = CotaHtmlFalha()

    def _encerrar_ciclo(self, cfg: ConfigAmazon, por_pausa: bool = False) -> None:
        """Fecha o ciclo. Só avisa o fim (concluída, parcial ou falhou) quando o ciclo terminou de verdade:
        sem busca pendente e sem ser por uma pausa (que já tem o próprio aviso). A janela que fecha no meio
        do ciclo fecha a coleta sem aviso."""
        if self._ciclo is None:
            return
        status = repo.status_final(self._ok, self._falha, cfg.limite_falha_pct)
        with self._sessoes() as s, s.begin():
            repo.finalizar_coleta(s, self._ciclo, status, self._ok, self._falha, self._relogio())
        log.info("ciclo %s da busca terminou: %s (%d ok, %d falhas)", self._ciclo, status.value, self._ok, self._falha)
        if not por_pausa and not self._pendentes and self._ok + self._falha:
            inicio = self._ciclo_inicio or self._relogio()
            dados = Dados(
                titulo_extra=f"ciclo {self._ciclo}",
                linhas=(
                    f"Buscas: {self._ok} ok · {_plural(self._falha, 'falha', 'falhas')}",
                    f"Duração: {formatar_duracao(self._relogio() - inicio)}",
                ),
            )
            if status is StatusColeta.FALHA:
                self._avisador.avisar(TipoAviso.AMAZON_BUSCA_FALHOU, CHAVE_GERAL, dados)
            else:
                tipo = TipoAviso.AMAZON_BUSCA_CONCLUIDA if status is StatusColeta.OK else TipoAviso.AMAZON_BUSCA_PARCIAL
                self._avisador.avisar(tipo, CHAVE_GERAL, dados)
                self._avisador.resolver(TipoAviso.AMAZON_BUSCA_FALHOU, CHAVE_GERAL)
        self._ciclo = None
        self._ciclo_inicio = None
        self._pendentes = set()

    def _fechar_por_desafio(self, s: Session, url: str, agora: datetime) -> None:
        if self._ciclo is not None:
            repo.finalizar_coleta(
                s, self._ciclo, StatusColeta.PAUSADA_DESAFIO, self._ok, self._falha, agora, erro=f"desafio em {url}"
            )

    def _registrar_desafio(self, url: str, extras: tuple[str, ...] = ()) -> None:
        super()._registrar_desafio(url, extras)
        # Só depois do commit da pausa: se a gravação falhar, o ciclo em memória continua valendo.
        self._ciclo = None
        self._pendentes = set()

    # --- descoberta ------------------------------------------------------------------------------

    def _passo_descoberta(self, agora: datetime, cfg: ConfigAmazon) -> float:
        if self._teto.liberado_em(agora, cfg.max_buscas_hora) is not None:
            return ESPERA_OCIOSA_S
        with self._sessoes() as s, s.begin():
            repo_amz.sincronizar_fila(s, agora)
            na_fila = repo_amz.ids_na_fila(s, agora, cfg.descoberta_casados_dias)
            item = repo_amz.proximo_da_fila(s, agora, cfg.descoberta_casados_dias)
            produto = s.get(ProdutoLiga, item.produto_id) if item else None
            entrou_em = item.entrou_em if item else None
            termo, proximo_indice = None, 0
            if item and produto:
                # Português, inglês (se houver) e, na seca (7 dias sem par novo), os termos guardados da IA.
                alternativos = (
                    [t.termo for t in repo_termos.termos_do_produto(s, produto.id)]
                    if repo_termos.em_seca(s, produto.id, agora)
                    else []
                )
                sequencia = sequencia_de_termos(produto.nome, produto.nome_en, alternativos)
                indice = item.indice_termo % len(sequencia)
                termo, proximo_indice = sequencia[indice], (indice + 1) % len(sequencia)
            ultimo_candidato_em = item.ultimo_candidato_em if item else None
        self._pendentes &= na_fila  # produto desativado na Liga (ou casado) sai do ciclo
        if self._ciclo is not None and not self._pendentes:
            self._encerrar_ciclo(cfg)
        if produto is None:
            return ESPERA_OCIOSA_S
        if self._ciclo is None:
            self._iniciar_ciclo(agora, na_fila)

        contexto = self._contexto(cfg, f"amazon-{self._ciclo}-{produto.id}", self._cota_falhas)
        teve_candidato = False
        try:
            teve_candidato = processar_produto(contexto, produto, termo).candidatos > 0
            self._ok += 1
            self._falhas_seguidas = 0
            self._pagina_ok()
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
                        s, produto.id, depois, depois + timedelta(minutes=cfg.intervalo_busca_min), False, proximo_indice
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
            repo_amz.reagendar(s, produto.id, depois, proxima, teve_candidato, proximo_indice)
            repo_amz.fechar_oportunidades_sem_leitura(s, depois)
        self._pendentes.discard(produto.id)
        if self._falhas_seguidas >= MAX_FALHAS_SEGUIDAS:  # antes do fim do ciclo: a pausa leva o aviso
            return self._pausar_por_falhas(lambda: self._encerrar_ciclo(cfg, por_pausa=True))
        if not self._pendentes:
            self._encerrar_ciclo(cfg)
        return 0
