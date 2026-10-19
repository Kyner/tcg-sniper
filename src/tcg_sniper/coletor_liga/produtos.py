"""Etapa 2 do job diário: abre a página dos produtos da lista do dia (`lista_do_dia`).

Grava o resumo histórico ("Preço Médio de Venda no Marketplace": mín, médio, máx) e o
número de lojas atual (`resumo_preco` append-only + grupo "resumo" de `preco_atual_liga`).
"""

import logging
import random
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.avisos.servico import Avisador
from tcg_sniper.coletor_liga.execucao import (
    DesafioDetectado,
    Dormir,
    ResultadoColeta,
    abrir_pagina,
    concluir_coleta,
    encerrar_por_erro,
    iniciar_se_ativo,
    pausa_humana,
    registrar_desafio,
    salvar_html_falha,
)
from tcg_sniper.coletor_liga.lista_do_dia import montar_lista
from tcg_sniper.coletor_liga.modelos import ErroParser, ErroRede
from tcg_sniper.coletor_liga.navegador import Navegador
from tcg_sniper.coletor_liga.parsers import parse_produto
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import StatusColeta, TipoColeta

log = logging.getLogger(__name__)

DESCRICAO = "Coleta dos produtos ativos"


def coletar_produtos(
    sessoes: sessionmaker[Session],
    navegador: Navegador,
    avisador: Avisador,
    config: Config,
    dormir: Dormir = time.sleep,
    embaralhar: Callable[[list], None] = random.shuffle,
    agora: datetime | None = None,
) -> ResultadoColeta | None:
    """`agora` decide o dia da lista (rodízio e "lido hoje"); padrão: a hora atual."""
    coleta_id = iniciar_se_ativo(sessoes, TipoColeta.PRODUTOS)
    if coleta_id is None:
        return None
    with sessoes() as s:
        lista = montar_lista(s, agora or repo.agora_utc(), config.zona, config.produtos_novos_dia, embaralhar)
    grupos = lista.grupos()
    log.info("coleta dos produtos %s: %d na lista do dia (%s)", coleta_id, len(lista.produtos), grupos)

    ok = falha = 0
    try:
        for indice, (produto_id, url) in enumerate(lista.produtos):
            if indice > 0:
                pausa_humana(config, dormir)
            try:
                pagina = abrir_pagina(navegador, url, dormir)
            except DesafioDetectado:
                registrar_desafio(sessoes, avisador, config, coleta_id, url, ok, falha)
                return ResultadoColeta(coleta_id, StatusColeta.PAUSADA_DESAFIO, ok, falha, grupos=grupos)
            except ErroRede as erro:
                log.warning("produto %s falhou por rede: %s", produto_id, erro)
                falha += 1
                continue
            try:
                resumo = parse_produto(pagina.html)
            except ErroParser as erro:
                caminho = salvar_html_falha(config, f"produto-{coleta_id}-{produto_id}", pagina.html)
                log.warning("parser falhou no produto %s (%s); HTML em %s", produto_id, erro, caminho)
                falha += 1
                continue
            with sessoes() as s, s.begin():
                repo.gravar_precos_produto(s, coleta_id, produto_id, resumo, repo.agora_utc())
            ok += 1
    except Exception as erro:  # noqa: BLE001 - erro inesperado fecha a coleta como falha
        return replace(encerrar_por_erro(sessoes, avisador, coleta_id, DESCRICAO, erro, ok, falha), grupos=grupos)
    resultado = concluir_coleta(sessoes, avisador, config, coleta_id, DESCRICAO, "produtos", ok, falha)
    return replace(resultado, grupos=grupos)
