"""Etapa 1 do job diário: varre as listagens de todas as categorias de selados.

Alimenta o catálogo (`produto_liga`, nunca altera `ativo`) e grava o preço atual
"à partir de" de cada produto listado. Contagem por categoria: `produtos_ok` = categorias
lidas, `produtos_falha` = categorias que falharam.
"""

import logging
import random
import time
from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.avisos.servico import Avisador
from tcg_sniper.coletor_liga.execucao import (
    DesafioDetectado,
    Dormir,
    ResultadoColeta,
    abrir_listagem,
    concluir_coleta,
    encerrar_por_erro,
    iniciar_se_ativo,
    pausa_humana,
    registrar_desafio,
    salvar_html_falha,
)
from tcg_sniper.coletor_liga.modelos import ErroParser, ErroRede
from tcg_sniper.coletor_liga.navegador import Navegador
from tcg_sniper.coletor_liga.parsers import parse_listagem
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import StatusColeta, TipoColeta

log = logging.getLogger(__name__)

DESCRICAO = "Coleta das listagens"


def coletar_listagens(
    sessoes: sessionmaker[Session],
    navegador: Navegador,
    avisador: Avisador,
    config: Config,
    dormir: Dormir = time.sleep,
    embaralhar: Callable[[list], None] = random.shuffle,
) -> ResultadoColeta | None:
    coleta_id = iniciar_se_ativo(sessoes, TipoColeta.LISTAGEM)
    if coleta_id is None:
        return None
    resultado = _varrer(sessoes, navegador, avisador, config, coleta_id, dormir, embaralhar)
    if resultado.novos:
        avisador.avisar(
            TipoAviso.LIGA_PRODUTOS_NOVOS, CHAVE_GERAL, Dados(linhas=(f"{resultado.novos} produtos novos nas listagens",))
        )
    return resultado


def _varrer(
    sessoes: sessionmaker[Session],
    navegador: Navegador,
    avisador: Avisador,
    config: Config,
    coleta_id: int,
    dormir: Dormir,
    embaralhar: Callable[[list], None],
) -> ResultadoColeta:
    categorias = list(config.categorias)
    embaralhar(categorias)
    log.info("coleta das listagens %s: %d categorias", coleta_id, len(categorias))
    ok = falha = novos = 0
    try:
        for indice, categ in enumerate(categorias):
            if indice > 0:
                pausa_humana(config, dormir)
            url = config.url_listagem(categ)
            try:
                expandida = abrir_listagem(navegador, url, config, dormir)
            except DesafioDetectado:
                registrar_desafio(sessoes, avisador, coleta_id, url, ok, falha)
                return ResultadoColeta(coleta_id, StatusColeta.PAUSADA_DESAFIO, ok, falha, novos)
            except ErroRede as erro:
                log.warning("categoria %s falhou por rede: %s", categ, erro)
                falha += 1
                continue
            log.info(
                "categoria %s: %d cliques, limite atingido: %s",
                categ,
                expandida.cliques,
                "sim" if expandida.limite_atingido else "não",
            )
            if expandida.limite_atingido:
                caminho = salvar_html_falha(config, f"listagem-{coleta_id}-{categ}", expandida.pagina.html)
                log.warning(
                    "categoria %s: limite de %d cliques em 'Exibir mais' atingido; HTML em %s",
                    categ,
                    config.liga_max_cliques,
                    caminho,
                )
                falha += 1
                continue
            try:
                itens = parse_listagem(expandida.pagina.html, expandida.pagina.url)
            except ErroParser as erro:
                caminho = salvar_html_falha(config, f"listagem-{coleta_id}-{categ}", expandida.pagina.html)
                log.warning("parser falhou na categoria %s (%s); HTML em %s", categ, erro, caminho)
                falha += 1
                continue
            with sessoes() as s, s.begin():
                novos += repo.gravar_listagem(s, coleta_id, itens, repo.agora_utc())
            log.info("categoria %s: %d cartões lidos", categ, len(itens))
            ok += 1
    except Exception as erro:  # noqa: BLE001 - erro inesperado fecha a coleta como falha
        return encerrar_por_erro(sessoes, avisador, coleta_id, DESCRICAO, erro, ok, falha, novos)
    return concluir_coleta(sessoes, avisador, config, coleta_id, DESCRICAO, "categorias", ok, falha, novos)
