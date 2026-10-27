"""Peças compartilhadas pela coleta das listagens e pela coleta dos produtos ativos."""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.avisos.formato import formatar_duracao
from tcg_sniper.avisos.servico import Avisador
from tcg_sniper.coletor_liga.desafio import eh_desafio
from tcg_sniper.coletor_liga.esfriamento import desafios_desde
from tcg_sniper.coletor_liga.lista_do_dia import inicio_do_dia
from tcg_sniper.coletor_liga.modelos import Pagina, PaginaExpandida
from tcg_sniper.coletor_liga.navegador import Navegador
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import EstadoColetorTipo, StatusColeta, TipoColeta
from tcg_sniper.navegador import ritmo
from tcg_sniper.navegador.ritmo import ESPERA_RETRY_S as ESPERA_RETRY_S  # noqa: PLC0414
from tcg_sniper.navegador.ritmo import Dormir as Dormir  # noqa: PLC0414
from tcg_sniper.navegador.ritmo import com_um_retry, pausa_aleatoria

log = logging.getLogger(__name__)


class DesafioDetectado(Exception):
    pass


@dataclass(frozen=True)
class ResultadoColeta:
    coleta_id: int
    status: StatusColeta
    produtos_ok: int
    produtos_falha: int
    novos: int = 0
    # Fechada por erro inesperado (o admin já foi avisado por `encerrar_por_erro`).
    interrompida: bool = False
    # Grupos da lista do dia ("casados 52, candidatos 18, novos 100, rodízio 312"); só na etapa dos produtos.
    grupos: str | None = None


def pausa_humana(config: Config, dormir: Dormir) -> None:
    pausa_aleatoria(config.pausa_min_s, config.pausa_max_s, dormir)


def iniciar_se_ativo(sessoes: sessionmaker[Session], tipo: TipoColeta) -> int | None:
    """Preâmbulo comum: com o coletor pausado não faz nada (devolve None); senão cria a coleta `rodando`."""
    with sessoes() as s, s.begin():
        if repo.obter_estado(s).estado != EstadoColetorTipo.ATIVO:
            log.info("coletor pausado; coleta de %s não executada", tipo.value)
            return None
        return repo.iniciar_coleta(s, tipo, repo.agora_utc()).id


def abrir_pagina(navegador: Navegador, url: str, dormir: Dormir) -> Pagina:
    """Abre uma página. Um retry após 30 s em ErroRede; desafio → DesafioDetectado."""
    pagina = com_um_retry(lambda: navegador.abrir(url), url, dormir)
    if eh_desafio(pagina):
        raise DesafioDetectado(url)
    return pagina


def abrir_listagem(
    navegador: Navegador, url: str, config: Config, dormir: Dormir
) -> PaginaExpandida:
    """Abre a listagem clicando em "Exibir mais" (pausa humana antes de cada clique, no máximo
    `config.liga_max_cliques`). Um retry após 30 s em ErroRede; desafio → DesafioDetectado."""
    expandida = com_um_retry(
        lambda: navegador.abrir_expandindo(url, config.liga_max_cliques, lambda: pausa_humana(config, dormir)),
        url,
        dormir,
    )
    if eh_desafio(expandida.pagina):
        raise DesafioDetectado(url)
    return expandida


def dados_desafio(url: str, desafios_hoje: int, esfriar_min: int) -> Dados:
    """Só o caminho da página (sem o domínio): o aviso diz onde parou, a ação diz onde resolver. A 3ª linha
    diz o que acontece depois do Retomar (1º desafio do dia: esfria; 2º: só amanhã)."""
    partes = urlsplit(url)
    pagina = (partes.path or "/") + (f"?{partes.query}" if partes.query else "")
    if desafios_hoje >= 2:
        efeito = "2º desafio de hoje: depois de retomar, a coleta só volta amanhã, no horário de sempre"
    elif esfriar_min > 0:
        efeito = (
            f"1º desafio de hoje: volta {esfriar_min} min depois de você retomar, "
            "com pausas em dobro por 24 h depois do desafio"
        )
    else:
        efeito = "1º desafio de hoje: volta logo depois de você retomar, com pausas em dobro por 24 h depois do desafio"
    return Dados(linhas=(f"Página: {pagina}", "A coleta fica pausada até você retomar", efeito))


def dados_resumo(
    dia: date, listagens: ResultadoColeta | None, produtos: ResultadoColeta, duracao: timedelta
) -> Dados:
    """Resumo de um job concluído. `listagens` é None quando o job rodou só os produtos. Nas listagens,
    ok/falha contam categorias; nos produtos, "<ok> de <lidos>" e os grupos da lista do dia."""
    linhas = []
    if listagens is not None:
        total = listagens.produtos_ok + listagens.produtos_falha
        linhas.append(
            f"Listagens: {listagens.status.value} · {listagens.produtos_ok} de {total} categorias · "
            f"{listagens.novos} produtos novos"
        )
    linha = (
        f"Produtos: {produtos.status.value} · {produtos.produtos_ok} de "
        f"{produtos.produtos_ok + produtos.produtos_falha}"
    )
    if produtos.grupos:
        linha += f" · {produtos.grupos}"
    linhas.append(linha)
    linhas.append(f"Duração: {formatar_duracao(duracao)}")
    return Dados(titulo_extra=f"{dia:%d/%m}", linhas=tuple(linhas))


def registrar_desafio(
    sessoes: sessionmaker[Session],
    avisador: Avisador,
    config: Config,
    coleta_id: int,
    url: str,
    ok: int,
    falha: int,
) -> None:
    agora = repo.agora_utc()
    with sessoes() as s, s.begin():
        repo.finalizar_coleta(
            s, coleta_id, StatusColeta.PAUSADA_DESAFIO, ok, falha, agora, erro=f"desafio em {url}"
        )
        repo.pausar_por_desafio(s, f"desafio em {url}", agora)
        desafios_hoje = desafios_desde(s, inicio_do_dia(agora, config.zona))  # já conta este
    log.warning("desafio do Cloudflare em %s (%dº de hoje); coletor pausado", url, desafios_hoje)
    avisador.avisar(TipoAviso.LIGA_DESAFIO, CHAVE_GERAL, dados_desafio(url, desafios_hoje, config.esfriar_desafio_min))


def salvar_html_falha(config: Config, nome: str, html: str) -> Path:
    return ritmo.salvar_html_falha(config.dir_dados, nome, html)


def concluir_coleta(
    sessoes: sessionmaker[Session],
    avisador: Avisador,
    config: Config,
    coleta_id: int,
    descricao: str,
    unidade: str,
    ok: int,
    falha: int,
    novos: int = 0,
) -> ResultadoColeta:
    """Fecha a coleta com ok/parcial/falha (LIMITE_FALHA_PCT) e avisa o admin se for falha."""
    status = repo.status_final(ok, falha, config.limite_falha_pct)
    with sessoes() as s, s.begin():
        repo.finalizar_coleta(s, coleta_id, status, ok, falha, repo.agora_utc())
    log.info("%s %s terminou: %s (%d ok, %d falhas)", descricao, coleta_id, status.value, ok, falha)
    if status is StatusColeta.FALHA:
        dados = Dados(linhas=(f"Etapa: {descricao}", f"Falhas: {falha} de {ok + falha} {unidade}"))
        avisador.avisar(TipoAviso.LIGA_COLETA_FALHOU, CHAVE_GERAL, dados)
    return ResultadoColeta(coleta_id, status, ok, falha, novos)


def encerrar_por_erro(
    sessoes: sessionmaker[Session],
    avisador: Avisador,
    coleta_id: int,
    descricao: str,
    erro: Exception,
    ok: int,
    falha: int,
    novos: int = 0,
) -> ResultadoColeta:
    """Erro inesperado no meio da coleta (chamar de dentro do `except`): fecha como falha,
    guarda o erro e avisa o admin."""
    log.exception("erro inesperado em %s %s", descricao, coleta_id)
    with sessoes() as s, s.begin():
        repo.finalizar_coleta(s, coleta_id, StatusColeta.FALHA, ok, falha, repo.agora_utc(), erro=repr(erro))
    dados = Dados(linhas=(f"Onde: {descricao} {coleta_id}", f"Erro: {erro!r}"))
    avisador.avisar(TipoAviso.LIGA_ERRO, CHAVE_GERAL, dados)
    return ResultadoColeta(coleta_id, StatusColeta.FALHA, ok, falha, novos, interrompida=True)
