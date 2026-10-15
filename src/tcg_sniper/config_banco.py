"""Configuração efetiva: o .env (infraestrutura e segredos) com o que está salvo na tela por cima."""

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import ConfigGeral, ConfigLiga


def sobrepor(config: Config, geral: ConfigGeral, liga: ConfigLiga) -> Config:
    return config.model_copy(
        update={
            "host_publico": geral.host_publico,
            "fuso": geral.fuso,
            "evolution_instancia": geral.evolution_instancia,
            "whatsapp_grupo_admin": geral.whatsapp_grupo_admin,
            "whatsapp_grupo_oportunidades": geral.whatsapp_grupo_oportunidades,
            "coleta_hora": liga.coleta_hora,
            "coleta_jitter_min": liga.coleta_jitter_min,
            "pausa_min_s": liga.pausa_min_s,
            "pausa_max_s": liga.pausa_max_s,
            "limite_falha_pct": liga.limite_falha_pct,
            "liga_categorias": liga.categorias,
            "liga_url_listagem": liga.url_listagem,
            "liga_max_cliques": liga.max_cliques,
        }
    )


def carregar_config(sessoes: sessionmaker[Session], config_env: Config) -> Config:
    """Lê `config_geral` e `config_liga` (criando-as com o .env na primeira vez) e devolve uma cópia
    de `config_env` com esses valores. `config_env` não é alterado."""
    with sessoes() as s, s.begin():
        return sobrepor(config_env, repo.obter_config_geral(s, config_env), repo.obter_config_liga(s, config_env))
