from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator, model_validator
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
    """Valores do .env. Os campos de operação (host, fuso, WhatsApp e coleta da Liga) só valem como
    valor inicial: depois da primeira leitura vêm das tabelas config_geral e config_liga
    (`config_banco.carregar_config`)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg"
    admin_senha: str = "trocar-esta-senha"
    # Chave do HMAC do login do site novo (código, token de sessão e número do pedido). Obrigatória para o serviço
    # `api` e o `codigo-acesso`; ver .env.example.
    segredo_api: SecretStr | None = None
    coleta_hora: time = time(10, 0)
    coleta_jitter_min: int = Field(30, ge=0, le=180)
    pausa_min_s: float = Field(8.0, ge=0)
    pausa_max_s: float = Field(20.0, ge=0)
    limite_falha_pct: int = Field(50, ge=0, le=100)
    # Valem da tela (config_liga); o .env não semeia estes dois.
    esfriar_desafio_min: int = Field(30, ge=0, le=240)
    produtos_novos_dia: int = Field(100, ge=0, le=2000)
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
    openai_api_key: str | None = None
    # Backup diário (serviço `manutencao`): pasta local e cópia fora do PC no Cloudflare R2.
    dir_backups: Path | None = None  # vazio: <DIR_DADOS>/backups
    r2_account_id: str | None = None
    r2_access_key_id: SecretStr | None = None
    r2_secret_access_key: SecretStr | None = None
    r2_bucket: str | None = None
    # Imagens dos produtos e anúncios (área de negócio): bucket PÚBLICO próprio, nunca o dos backups.
    r2_bucket_imagens: str | None = None
    r2_imagens_access_key_id: SecretStr | None = None  # vazias: usa as chaves dos backups
    r2_imagens_secret_access_key: SecretStr | None = None
    url_publica_imagens: str | None = None  # https://pub-<código>.r2.dev ou https://img.<domínio>, sem barra no fim

    @field_validator("liga_categorias")
    @classmethod
    def _validar_categorias(cls, valor: str) -> str:
        ids = [parte.strip() for parte in valor.split(",") if parte.strip()]
        if not ids or not all(i.isascii() and i.isdigit() for i in ids):
            raise ValueError(f"LIGA_CATEGORIAS inválida: {valor!r}; use IDs numéricos separados por vírgula")
        return ",".join(dict.fromkeys(ids))

    @field_validator("dir_backups", mode="before")
    @classmethod
    def _vazio_e_padrao(cls, valor):
        return None if isinstance(valor, str) and not valor.strip() else valor

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
    def pasta_backups(self) -> Path:
        return self.dir_backups or self.dir_dados / "backups"

    @property
    def r2_configurado(self) -> bool:
        """As quatro variáveis R2_* preenchidas; sem elas o backup fica só no PC."""
        segredos = (self.r2_access_key_id, self.r2_secret_access_key)
        textos = (self.r2_account_id, self.r2_bucket, *(s.get_secret_value() if s else None for s in segredos))
        return all((texto or "").strip() for texto in textos)

    def chaves_r2_imagens(self) -> tuple[str, str] | None:
        proprias = (self.r2_imagens_access_key_id, self.r2_imagens_secret_access_key)
        chaves = proprias if all(proprias) else (self.r2_access_key_id, self.r2_secret_access_key)
        if not all(chaves):
            return None
        valores = tuple(c.get_secret_value().strip() for c in chaves if c is not None)
        return (valores[0], valores[1]) if len(valores) == 2 and all(valores) else None

    @property
    def imagens_configuradas(self) -> bool:
        bucket = (self.r2_bucket_imagens or "").strip()
        if bucket == (self.r2_bucket or "").strip():  # o das imagens é público: nunca o dos backups
            return False
        return bool((self.r2_account_id or "").strip() and bucket and self.chaves_r2_imagens())

    @property
    def bucket_imagens_igual_ao_dos_backups(self) -> bool:
        bucket = (self.r2_bucket_imagens or "").strip()
        return bool(bucket) and bucket == (self.r2_bucket or "").strip()

    @property
    def zona(self) -> ZoneInfo:
        return ZoneInfo(self.fuso)
