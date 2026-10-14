"""Peças compartilhadas pela coleta das listagens e pela coleta dos produtos ativos."""

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.coletor_liga.desafio import eh_desafio
from tcg_sniper.coletor_liga.modelos import ErroRede, Pagina, PaginaExpandida
from tcg_sniper.coletor_liga.navegador import Navegador
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import EstadoColetorTipo, StatusColeta, TipoColeta
from tcg_sniper.notificador.base import Destino, Notificador

log = logging.getLogger(__name__)

Dormir = Callable[[float], None]
ESPERA_RETRY_S = 30


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


def pausa_humana(config: Config, dormir: Dormir) -> None:
    dormir(random.uniform(config.pausa_min_s, config.pausa_max_s))


def iniciar_se_ativo(sessoes: sessionmaker[Session], tipo: TipoColeta) -> int | None:
    """Preâmbulo comum: com o coletor pausado não faz nada (devolve None); senão cria a coleta `rodando`."""
    with sessoes() as s, s.begin():
        if repo.obter_estado(s).estado != EstadoColetorTipo.ATIVO:
            log.info("coletor pausado; coleta de %s não executada", tipo.value)
            return None
        return repo.iniciar_coleta(s, tipo, repo.agora_utc()).id


def _com_um_retry[T](abrir: Callable[[], T], url: str, dormir: Dormir) -> T:
    try:
        return abrir()
    except ErroRede as erro:
        log.warning("erro de rede em %s (%s); nova tentativa em %ss", url, erro, ESPERA_RETRY_S)
        dormir(ESPERA_RETRY_S)
        return abrir()


def abrir_pagina(navegador: Navegador, url: str, dormir: Dormir) -> Pagina:
    """Abre uma página. Um retry após 30 s em ErroRede; desafio → DesafioDetectado."""
    pagina = _com_um_retry(lambda: navegador.abrir(url), url, dormir)
    if eh_desafio(pagina):
        raise DesafioDetectado(url)
    return pagina


def abrir_listagem(
    navegador: Navegador, url: str, config: Config, dormir: Dormir
) -> PaginaExpandida:
    """Abre a listagem clicando em "Exibir mais" (pausa humana antes de cada clique, no máximo
    `config.liga_max_cliques`). Um retry após 30 s em ErroRede; desafio → DesafioDetectado."""
    expandida = _com_um_retry(
        lambda: navegador.abrir_expandindo(url, config.liga_max_cliques, lambda: pausa_humana(config, dormir)),
        url,
        dormir,
    )
    if eh_desafio(expandida.pagina):
        raise DesafioDetectado(url)
    return expandida


def mensagem_desafio(config: Config, url: str) -> str:
    return (
        f"Desafio Cloudflare na LigaMagic ({url}). "
        f"Resolver em http://{config.host_publico}:6080/vnc.html "
        f"e depois clicar em retomar em http://{config.host_publico}:8000"
    )


def mensagem_resumo(
    config: Config, dia: date, listagens: ResultadoColeta | None, produtos: ResultadoColeta
) -> str:
    """Resumo enviado ao admin no fim de um job concluído. `listagens` é None quando o job rodou
    só os produtos. Nas listagens, ok/falha contam categorias."""
    linhas = [f"Coleta de {dia:%d/%m} concluída."]
    if listagens is not None:
        total = listagens.produtos_ok + listagens.produtos_falha
        linhas.append(
            f"Listagens: {listagens.status.value} ({listagens.produtos_ok} de {total} categorias, "
            f"{listagens.novos} produtos novos)."
        )
    linhas.append(f"Produtos: {produtos.status.value} ({produtos.produtos_ok} ok, {produtos.produtos_falha} falhas).")
    linhas.append(f"Admin: http://{config.host_publico}:8000")
    return "\n".join(linhas)


def registrar_desafio(
    sessoes: sessionmaker[Session],
    notificador: Notificador,
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
    log.warning("desafio do Cloudflare em %s; coletor pausado", url)
    notificador.enviar(Destino.ADMIN, mensagem_desafio(config, url))


def salvar_html_falha(config: Config, nome: str, html: str) -> Path:
    pasta = config.dir_dados / "falhas"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{nome}.html"
    caminho.write_text(html, encoding="utf-8")
    return caminho


def concluir_coleta(
    sessoes: sessionmaker[Session],
    notificador: Notificador,
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
        notificador.enviar(
            Destino.ADMIN,
            f"{descricao} {coleta_id} falhou em {falha} de {ok + falha} {unidade}. "
            f"O layout da LigaMagic pode ter mudado. HTMLs em {config.dir_dados / 'falhas'}.",
        )
    return ResultadoColeta(coleta_id, status, ok, falha, novos)


def encerrar_por_erro(
    sessoes: sessionmaker[Session],
    notificador: Notificador,
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
    notificador.enviar(Destino.ADMIN, f"{descricao} {coleta_id} interrompida por erro inesperado: {erro!r}")
    return ResultadoColeta(coleta_id, StatusColeta.FALHA, ok, falha, novos, interrompida=True)
