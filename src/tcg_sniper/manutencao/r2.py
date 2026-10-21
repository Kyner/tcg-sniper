"""Cópia do backup fora do PC: Cloudflare R2 pela API S3 (boto3).

O token só precisa gravar objetos: nada é apagado no bucket (as regras de ciclo de vida do próprio
bucket apagam `diario/` depois de 7 dias e `semanal/` depois de 35)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from tcg_sniper.config import Config


class Enviador(Protocol):
    def enviar(self, caminho: Path, chave: str) -> None:
        """Grava o arquivo no bucket com a chave dada. Erro sobe como exceção."""


def _cliente_boto3(**kwargs: Any):
    import boto3
    from botocore.config import Config as ConfigBotocore

    return boto3.client(
        "s3",
        config=ConfigBotocore(
            # o R2 não aceita os checksums que o boto3 manda por padrão desde a 1.36
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            connect_timeout=15,
            read_timeout=120,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
        **kwargs,
    )


class EnviadorR2:
    def __init__(
        self, config: Config, fabrica_cliente: Callable[..., Any] = _cliente_boto3, *,
        bucket: str | None = None, chaves: tuple[str, str] | None = None,
    ):
        """Sem `bucket` e `chaves`, usa o bucket e as chaves dos backups."""
        self._bucket = (bucket if bucket is not None else config.r2_bucket or "").strip()
        if chaves is None:
            chaves = (config.r2_access_key_id.get_secret_value().strip(),
                      config.r2_secret_access_key.get_secret_value().strip())
        # o account id vai na URL do endpoint, que aparece nas mensagens de erro do boto3
        self._segredos = tuple(v for v in (*chaves, (config.r2_account_id or "").strip()) if v)
        self._cliente = fabrica_cliente(
            endpoint_url=f"https://{(config.r2_account_id or '').strip()}.r2.cloudflarestorage.com",
            region_name="auto",
            aws_access_key_id=chaves[0],
            aws_secret_access_key=chaves[1],
        )

    @property
    def segredos(self) -> tuple[str, ...]:
        """Chaves e account id, para tirar das mensagens de erro (nunca vão para log, banco ou WhatsApp)."""
        return self._segredos

    def __repr__(self) -> str:
        return f"EnviadorR2(bucket={self._bucket!r})"

    def enviar(self, caminho: Path, chave: str) -> None:
        self._cliente.upload_file(str(caminho), self._bucket, chave)

    def enviar_bytes(self, dados: bytes, chave: str, tipo: str, cache: str) -> None:
        self._cliente.put_object(Bucket=self._bucket, Key=chave, Body=dados, ContentType=tipo, CacheControl=cache)


def criar_enviador(config: Config) -> EnviadorR2 | None:
    """`None` quando as variáveis R2_* não estão todas preenchidas (o backup fica só no PC)."""
    return EnviadorR2(config) if config.r2_configurado else None


def criar_enviador_imagens(config: Config) -> EnviadorR2 | None:
    """`None` sem `R2_BUCKET_IMAGENS` ou sem chaves (as telas saem sem foto). Nunca usa o bucket dos backups."""
    chaves = config.chaves_r2_imagens()
    if not config.imagens_configuradas or chaves is None or config.r2_bucket_imagens is None:
        return None
    return EnviadorR2(config, bucket=config.r2_bucket_imagens.strip(), chaves=chaves)
