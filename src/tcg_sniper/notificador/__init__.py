import logging

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.notificador.base import Destino, Notificador
from tcg_sniper.notificador.evolution import EvolutionNotificador
from tcg_sniper.notificador.log import LogNotificador

log = logging.getLogger(__name__)

CHAVE_PADRAO = "trocar-esta-chave"


def criar_notificador(config: Config, sessoes: sessionmaker[Session]) -> Notificador:
    """Evolution se a URL e a chave (do .env) estão definidas; instância e grupos vêm da tela de
    Configurações (banco), lidos a cada envio. Sem URL ou chave, as mensagens vão só para o log."""
    chave = (config.evolution_api_key or "").strip()
    if config.evolution_url and chave in ("", CHAVE_PADRAO):
        log.warning(
            "EVOLUTION_API_KEY vazia ou com o valor padrão %r: alertas vão só para o log", CHAVE_PADRAO
        )
        return LogNotificador()
    if not config.evolution_url:
        return LogNotificador()

    def destinos() -> tuple[str | None, dict[Destino, str]]:
        with sessoes() as s, s.begin():
            geral = repo.obter_config_geral(s, config)
            grupos = {
                destino: grupo
                for destino, grupo in (
                    (Destino.ADMIN, geral.whatsapp_grupo_admin),
                    (Destino.OPORTUNIDADES, geral.whatsapp_grupo_oportunidades),
                )
                if grupo
            }
            return geral.evolution_instancia, grupos

    return EvolutionNotificador(config.evolution_url, chave, destinos)
