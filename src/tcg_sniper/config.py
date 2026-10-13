from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DIAS_SEMANA = {
    "segunda": 0,
    "terca": 1,
    "terça": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "sabado": 5,
    "sábado": 5,
    "domingo": 6,
}


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg"
    admin_senha: str = "trocar-esta-senha"
    coleta_hora: time = time(10, 0)
    coleta_jitter_min: int = Field(30, ge=0, le=180)
    catalogo_dia_semana: str = "domingo"
    pausa_min_s: float = Field(8.0, ge=0)
    pausa_max_s: float = Field(20.0, ge=0)
    limite_falha_pct: int = Field(50, ge=0, le=100)
    fuso: str = "America/Sao_Paulo"
    liga_url_catalogo: str = ""
    dir_dados: Path = Path("/data")
    host_publico: str = "localhost"
    evolution_url: str | None = None
    evolution_api_key: str | None = None
    evolution_instancia: str | None = None
    whatsapp_grupo_admin: str | None = None
    whatsapp_grupo_oportunidades: str | None = None

    @field_validator("catalogo_dia_semana")
    @classmethod
    def _validar_dia(cls, valor: str) -> str:
        normalizado = valor.strip().lower()
        if normalizado not in DIAS_SEMANA:
            raise ValueError(f"dia inválido: {valor!r}; use um de {sorted(DIAS_SEMANA)}")
        return normalizado

    @model_validator(mode="after")
    def _validar_pausas(self) -> "Config":
        if self.pausa_min_s > self.pausa_max_s:
            raise ValueError("PAUSA_MIN_S maior que PAUSA_MAX_S")
        return self

    @property
    def catalogo_weekday(self) -> int:
        return DIAS_SEMANA[self.catalogo_dia_semana]

    @property
    def zona(self) -> ZoneInfo:
        return ZoneInfo(self.fuso)
