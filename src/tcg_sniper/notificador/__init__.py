import logging

from tcg_sniper.config import Config
from tcg_sniper.notificador.base import Destino, Notificador
from tcg_sniper.notificador.evolution import EvolutionNotificador
from tcg_sniper.notificador.log import LogNotificador

log = logging.getLogger(__name__)

CHAVE_PADRAO = "trocar-esta-chave"


def criar_notificador(config: Config) -> Notificador:
    chave = (config.evolution_api_key or "").strip()
    if config.evolution_url and config.evolution_instancia and chave in ("", CHAVE_PADRAO):
        log.warning(
            "EVOLUTION_API_KEY vazia ou com o valor padrão %r: alertas vão só para o log", CHAVE_PADRAO
        )
        return LogNotificador()
    if not (config.evolution_url and chave and config.evolution_instancia):
        return LogNotificador()
    if not config.whatsapp_grupo_admin:
        log.warning("WHATSAPP_GRUPO_ADMIN vazio: alertas do admin (desafio, falhas) vão só para o log")
    grupos = {
        destino: grupo
        for destino, grupo in (
            (Destino.ADMIN, config.whatsapp_grupo_admin),
            (Destino.OPORTUNIDADES, config.whatsapp_grupo_oportunidades),
        )
        if grupo
    }
    return EvolutionNotificador(
        config.evolution_url, chave, config.evolution_instancia, grupos
    )
