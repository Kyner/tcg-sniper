"""`perguntar`: confere o orçamento, chama o transporte, calcula o custo e registra a chamada."""

import json
from collections.abc import Callable, Sequence
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import ConfigIA
from tcg_sniper.db.repositorio import agora_utc
from tcg_sniper.ia.modelos import Bruta, ErroIA, Pedido, RespostaIA, SemOrcamento, Transporte
from tcg_sniper.ia.orcamento import motivo_sem_orcamento

MILHAO = Decimal(1_000_000)
CASAS = Decimal("0.000001")


def custo(tokens_entrada: int, tokens_saida: int, cfg: ConfigIA) -> Decimal:
    total = tokens_entrada * cfg.preco_entrada_milhao_usd + tokens_saida * cfg.preco_saida_milhao_usd
    return (total / MILHAO).quantize(CASAS)


def perguntar(
    sessoes: sessionmaker[Session],
    transporte: Transporte,
    *,
    finalidade: str,
    instrucoes: str,
    texto: str,
    imagens: Sequence[str],
    nome_formato: str,
    formato: dict,
    zona: ZoneInfo,
    modelo: str | None = None,
    relogio: Callable[[], datetime] = agora_utc,
) -> RespostaIA:
    """Uma chamada. Cada chamada (ok ou erro) é gravada na sua própria transação, para contar no
    orçamento mesmo se quem chamou desfizer a dele. Lança SemOrcamento (sem chamar), ChaveInvalida ou ErroIA."""
    with sessoes() as s, s.begin():
        cfg = repo_ia.obter_config_ia(s)
        motivo = motivo_sem_orcamento(cfg, repo_ia.gasto(s, relogio(), zona))
        if motivo is not None:
            raise SemOrcamento(motivo)
        s.expunge(cfg)
    pedido = Pedido(modelo or cfg.modelo, cfg.esforco, instrucoes, texto, tuple(imagens), nome_formato, formato)
    try:
        bruta = transporte.enviar(pedido)
    except ErroIA as erro:
        _registrar(sessoes, relogio(), finalidade, pedido.modelo, Bruta("", 0, 0), Decimal(0), str(erro))
        raise
    valor = custo(bruta.tokens_entrada, bruta.tokens_saida, cfg)
    try:
        dados = json.loads(bruta.texto)
        if not isinstance(dados, dict):
            raise ValueError("não é objeto")  # noqa: TRY004
    except ValueError:
        _registrar(sessoes, relogio(), finalidade, pedido.modelo, bruta, valor, "resposta não é um JSON de objeto")
        raise ErroIA("resposta da OpenAI não é um JSON de objeto") from None
    chamada_id = _registrar(sessoes, relogio(), finalidade, pedido.modelo, bruta, valor, None)
    return RespostaIA(dados, pedido.modelo, bruta.tokens_entrada, bruta.tokens_saida, valor, chamada_id)


def _registrar(sessoes, em, finalidade, modelo, bruta: Bruta, valor: Decimal, erro: str | None) -> int:
    with sessoes() as s, s.begin():
        return repo_ia.registrar_chamada(
            s, em=em, finalidade=finalidade, modelo=modelo, tokens_entrada=bruta.tokens_entrada,
            tokens_saida=bruta.tokens_saida, custo_usd=valor, ok=erro is None, erro=erro,
        ).id
