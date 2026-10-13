from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Categorias de selados de Magic na LigaMagic (levantamento de 2026-10-13).
CATEGORIAS_SELADOS = (
    "10", "11", "12", "13", "14", "15", "16", "17", "19", "21",
    "22", "31", "36", "37", "47", "50", "51", "52", "55", "56",
)  # fmt: skip
URL_LISTAGEM_PADRAO = (
    "https://www.ligamagic.com.br/?view=cards/search&card=categ%3D{categ}+searchprod%3D1&tipo=1"
)


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg"
    admin_senha: str = "trocar-esta-senha"
    coleta_hora: time = time(10, 0)
    coleta_jitter_min: int = Field(30, ge=0, le=180)
    pausa_min_s: float = Field(8.0, ge=0)
    pausa_max_s: float = Field(20.0, ge=0)
    limite_falha_pct: int = Field(50, ge=0, le=100)
    fuso: str = "America/Sao_Paulo"
    liga_categorias: str = ",".join(CATEGORIAS_SELADOS)
    liga_url_listagem: str = URL_LISTAGEM_PADRAO
    liga_max_cliques: int = Field(50, ge=1, le=500)
    dir_dados: Path = Path("/data")
    host_publico: str = "localhost"
    evolution_url: str | None = None
    evolution_api_key: str | None = None
    evolution_instancia: str | None = None
    whatsapp_grupo_admin: str | None = None
    whatsapp_grupo_oportunidades: str | None = None

    @field_validator("liga_categorias")
    @classmethod
    def _validar_categorias(cls, valor: str) -> str:
        ids = [parte.strip() for parte in valor.split(",") if parte.strip()]
        if not ids or not all(i.isascii() and i.isdigit() for i in ids):
            raise ValueError(f"LIGA_CATEGORIAS inválida: {valor!r}; use IDs numéricos separados por vírgula")
        return ",".join(dict.fromkeys(ids))

    @field_validator("liga_url_listagem")
    @classmethod
    def _validar_url_listagem(cls, valor: str) -> str:
        if "{categ}" not in valor:
            raise ValueError("LIGA_URL_LISTAGEM precisa conter {categ}")
        return valor

    @model_validator(mode="after")
    def _validar_pausas(self) -> "Config":
        if self.pausa_min_s > self.pausa_max_s:
            raise ValueError("PAUSA_MIN_S maior que PAUSA_MAX_S")
        return self

    @property
    def categorias(self) -> list[str]:
        return self.liga_categorias.split(",")

    def url_listagem(self, categ: str) -> str:
        return self.liga_url_listagem.replace("{categ}", categ)

    @property
    def zona(self) -> ZoneInfo:
        return ZoneInfo(self.fuso)
