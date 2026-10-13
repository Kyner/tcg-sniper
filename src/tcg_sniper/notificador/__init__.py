from tcg_sniper.config import Config
from tcg_sniper.notificador.base import Destino, Notificador
from tcg_sniper.notificador.evolution import EvolutionNotificador
from tcg_sniper.notificador.log import LogNotificador


def criar_notificador(config: Config) -> Notificador:
    if not (config.evolution_url and config.evolution_api_key and config.evolution_instancia):
        return LogNotificador()
    grupos = {
        destino: grupo
        for destino, grupo in (
            (Destino.ADMIN, config.whatsapp_grupo_admin),
            (Destino.OPORTUNIDADES, config.whatsapp_grupo_oportunidades),
        )
        if grupo
    }
    return EvolutionNotificador(
        config.evolution_url, config.evolution_api_key, config.evolution_instancia, grupos
    )
