# Coletor LigaMagic (sub-projeto 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coletar diariamente o resumo de preços de selados de Magic na LigaMagic, guardar histórico no Postgres, administrar a lista ativa por uma página web e avisar o grupo admin do WhatsApp quando a coleta precisar de intervenção.

**Architecture:** Um pacote Python (`tcg_sniper`) e uma imagem Docker; cada serviço (`coletor-liga`, `admin`, `migrate`) roda em seu próprio container com um comando diferente, e todos se comunicam só pelo Postgres. Parsers e regras de negócio são funções puras testadas com fixtures; navegador (Playwright) e WhatsApp (Evolution API) ficam atrás de interfaces com fakes nos testes.

**Tech Stack:** Python 3.12, uv, SQLAlchemy 2 + psycopg 3, Alembic, Playwright (sync API), selectolax, FastAPI + Jinja2 + HTMX, httpx, pydantic-settings, pytest + respx, Postgres 16, Docker Compose, Evolution API.

**Spec:** `docs/superpowers/specs/2026-10-13-coletor-liga-design.md`

## Global Constraints

- Nada de solucionador de CAPTCHA, spoofing de fingerprint ou retry automático diante de desafio do Cloudflare. Desafio detectado: pausa, avisa o grupo admin, espera intervenção humana.
- Chromium com `headless=False` e perfil persistente em `<DIR_DADOS>/perfil`.
- Pausa aleatória de 8 a 20 segundos entre páginas da LigaMagic (`PAUSA_MIN_S`, `PAUSA_MAX_S`).
- Coleta diária às 10:00 ± 30 min (`COLETA_HORA`, `COLETA_JITTER_MIN`), fuso `America/Sao_Paulo`. Domingo: varredura do catálogo e depois preços, no mesmo job.
- Nunca duas coletas simultâneas (advisory lock do Postgres).
- Dinheiro em `NUMERIC(10,2)`; datas `timestamptz` em UTC no banco, exibidas no fuso local.
- `resumo_preco` é append-only; `preco_atual_liga` é upsert; `produto_liga` nunca é apagado e a varredura nunca altera `ativo`.
- Status de coleta: `ok` sem falhas; `parcial` com falhas até `LIMITE_FALHA_PCT` (50%) inclusive; `falha` acima disso ou erro geral.
- Falha de envio do notificador nunca interrompe a coleta (3 tentativas com backoff, depois log).
- Nenhum teste acessa a LigaMagic ou o WhatsApp reais.
- Identificadores e mensagens em português; commits em inglês no formato `feat:`/`test:`/`chore:`.

## Review Focus

1. Página normal da LigaMagic com Turnstile em outro lugar (ex.: modal de login) sendo classificada como desafio pausaria tudo. Esperado: nenhuma fixture real é desafio. Teste na Task 6.
2. Formatos de preço `R$ 1.234,56`, `R$\xa089,90`, `1234,56` precisam virar `Decimal` exato; texto sem preço gera `ErroParser`, nunca zero. Teste na Task 6.
3. O mesmo produto aparecendo duas vezes na varredura (na mesma página ou em páginas diferentes) não pode gerar erro de chave duplicada nem contar como novo duas vezes. Teste na Task 3.
4. Restart do container no mesmo dia: se a coleta de hoje já rodou, não roda de novo; se ainda não rodou e o horário passou, roda. Teste na Task 9.
5. Busca no admin com `%` ou `_` precisa casar literalmente, não como curinga. Teste na Task 10.

---

## Estrutura de arquivos

```
pyproject.toml, uv.lock, alembic.ini, .gitignore, .gitattributes, .env.example
docker-compose.yml, Dockerfile, docker/postgres-init.sql, docker/coletor-entrypoint.sh
README.md
scripts/capturar_fixture.py          # captura HTML real da Liga para fixtures
src/tcg_sniper/
  __init__.py
  config.py                          # Config (pydantic-settings)
  cli.py                             # tcg-sniper migrate | coletor-liga | admin
  db/
    __init__.py
    models.py                        # tabelas e enums
    session.py                       # criar_engine, criar_sessoes, migrar
    repositorio.py                   # operações de banco do coletor
    migrations/                      # Alembic (env.py, versions/)
  coletor_liga/
    __init__.py
    modelos.py                       # Resumo, ItemCatalogo, PaginaCatalogo, Pagina, ErroParser, ErroRede
    desafio.py                       # eh_desafio (puro)
    parsers.py                       # parse_produto, parse_catalogo, parse_preco_brl (puros)
    navegador.py                     # Navegador (Protocol), NavegadorPlaywright
    execucao.py                      # abrir_pagina, pausa_humana, registrar_desafio, salvar_html_falha
    precos.py                        # coletar_precos
    catalogo.py                      # varrer_catalogo
    agendador.py                     # alvo_do_dia, lock_coleta, Agendador
  notificador/
    __init__.py                      # criar_notificador
    base.py                          # Destino, Notificador
    log.py                           # LogNotificador
    evolution.py                     # EvolutionNotificador
  admin/
    __init__.py
    consultas.py                     # consultas do admin
    app.py                           # criar_app, formatar_brl, formatar_data
    templates/                       # base, index, catalogo, _linha_produto, produto
tests/
  conftest.py                        # config, engine, sessoes, s
  fakes.py                           # criar_produto, NotificadorFake, NavegadorFake, pagina_html, fixture_liga
  fixtures/liga/*.html               # HTMLs reais capturados na Task 6
  test_config.py
  db/test_migracao.py, db/test_repositorio.py
  coletor_liga/test_desafio.py, test_parsers.py, test_precos.py, test_catalogo.py, test_agendador.py
  notificador/test_notificador.py
  admin/test_admin.py
```

Desenvolvimento e testes rodam no Windows com Python nativo (`uv run pytest`) contra o Postgres do compose. Docker completo só na Task 11.

---

### Task 1: Esqueleto do projeto, configuração e Postgres local

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.gitattributes`, `.env.example`, `docker-compose.yml`, `docker/postgres-init.sql`
- Create: `src/tcg_sniper/__init__.py`, `src/tcg_sniper/config.py`
- Create: `tests/conftest.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `tcg_sniper.config.Config` com campos `database_url`, `admin_senha`, `coleta_hora: time`, `coleta_jitter_min: int`, `catalogo_dia_semana: str`, `pausa_min_s: float`, `pausa_max_s: float`, `limite_falha_pct: int`, `fuso: str`, `liga_url_catalogo: str`, `dir_dados: Path`, `host_publico: str`, `evolution_url`, `evolution_api_key`, `evolution_instancia`, `whatsapp_grupo_admin`, `whatsapp_grupo_oportunidades` (todos `str | None`), e propriedades `catalogo_weekday: int` (segunda=0, domingo=6) e `zona: ZoneInfo`. Fixture pytest `config` (com `dir_dados=tmp_path`).

- [ ] **Step 1: Criar `pyproject.toml`**

```toml
[project]
name = "tcg-sniper"
version = "0.1.0"
description = "Monitor de arbitragem de selados de Magic"
requires-python = ">=3.12"
dependencies = [
    "alembic>=1.13",
    "fastapi>=0.115",
    "httpx>=0.27",
    "jinja2>=3.1",
    "playwright>=1.47",
    "psycopg[binary]>=3.2",
    "pydantic-settings>=2.4",
    "selectolax>=0.3.21",
    "sqlalchemy>=2.0.30",
    "tzdata>=2024.1",
    "uvicorn>=0.30",
]

[project.scripts]
tcg-sniper = "tcg_sniper.cli:main"

[dependency-groups]
dev = ["pytest>=8.3", "respx>=0.21"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tcg_sniper"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["tests"]
addopts = "--import-mode=importlib"
```

- [ ] **Step 2: Criar `.gitignore`, `.gitattributes`, `.env.example`**

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.env
.perfil-dev/
dados/
```

`.gitattributes` (scripts shell precisam de LF para rodar no container):
```
* text=auto
*.sh text eol=lf
```

`.env.example`:
```
DATABASE_URL=postgresql+psycopg://tcg:tcg@localhost:5432/tcg
ADMIN_SENHA=trocar-esta-senha
VNC_SENHA=trocar-esta-senha
COLETA_HORA=10:00
COLETA_JITTER_MIN=30
CATALOGO_DIA_SEMANA=domingo
PAUSA_MIN_S=8
PAUSA_MAX_S=20
LIMITE_FALHA_PCT=50
FUSO=America/Sao_Paulo
LIGA_URL_CATALOGO=
DIR_DADOS=./dados
HOST_PUBLICO=192.168.0.10
EVOLUTION_URL=http://localhost:8080
EVOLUTION_API_KEY=trocar-esta-chave
EVOLUTION_INSTANCIA=tcg-sniper
WHATSAPP_GRUPO_ADMIN=
WHATSAPP_GRUPO_OPORTUNIDADES=
```

- [ ] **Step 3: Criar `docker-compose.yml` (só Postgres por enquanto) e `docker/postgres-init.sql`**

`docker-compose.yml`:
```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: tcg
      POSTGRES_PASSWORD: tcg
      POSTGRES_DB: tcg
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./docker/postgres-init.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
    ports:
      - "127.0.0.1:5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U tcg"]
      interval: 5s
      retries: 10

volumes:
  pgdata:
```

`docker/postgres-init.sql` (roda só na criação do volume):
```sql
CREATE DATABASE tcg_test;
CREATE DATABASE evolution;
```

Run: `docker compose up -d postgres`
Expected: container `postgres` healthy (`docker compose ps`).

- [ ] **Step 4: Instalar dependências**

Run: `uv sync`
Expected: cria `.venv` e `uv.lock` sem erro.

- [ ] **Step 5: Escrever o teste da configuração**

`tests/test_config.py`:
```python
from datetime import time
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from tcg_sniper.config import Config


def test_padroes(monkeypatch):
    for var in ("COLETA_HORA", "CATALOGO_DIA_SEMANA", "COLETA_JITTER_MIN"):
        monkeypatch.delenv(var, raising=False)
    c = Config(_env_file=None)
    assert c.coleta_hora == time(10, 0)
    assert c.coleta_jitter_min == 30
    assert c.catalogo_weekday == 6
    assert c.limite_falha_pct == 50
    assert c.zona == ZoneInfo("America/Sao_Paulo")


def test_le_variaveis_de_ambiente(monkeypatch):
    monkeypatch.setenv("COLETA_HORA", "09:15")
    monkeypatch.setenv("CATALOGO_DIA_SEMANA", "Sábado")
    c = Config(_env_file=None)
    assert c.coleta_hora == time(9, 15)
    assert c.catalogo_weekday == 5


def test_dia_invalido():
    with pytest.raises(ValidationError):
        Config(_env_file=None, catalogo_dia_semana="feriado")


def test_pausa_minima_maior_que_maxima():
    with pytest.raises(ValidationError):
        Config(_env_file=None, pausa_min_s=30, pausa_max_s=10)
```

`tests/conftest.py`:
```python
import pytest

from tcg_sniper.config import Config


@pytest.fixture
def config(tmp_path):
    return Config(
        _env_file=None,
        dir_dados=tmp_path,
        liga_url_catalogo="https://liga.test/selados",
        host_publico="host.test",
        pausa_min_s=8,
        pausa_max_s=20,
        limite_falha_pct=50,
    )
```

- [ ] **Step 6: Rodar e ver falhar**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'tcg_sniper'` (ou `tcg_sniper.config`).

- [ ] **Step 7: Implementar**

`src/tcg_sniper/__init__.py`: arquivo vazio.

`src/tcg_sniper/config.py`:
```python
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

    database_url: str = "postgresql+psycopg://tcg:tcg@localhost:5432/tcg"
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
```

- [ ] **Step 8: Rodar e ver passar**

Run: `uv run pytest tests/test_config.py -v`
Expected: 4 passed.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock .gitignore .gitattributes .env.example docker-compose.yml docker/postgres-init.sql src tests
git commit -m "chore: project skeleton, config and local postgres"
```

---

### Task 2: Modelos do banco e migração inicial

**Files:**
- Create: `src/tcg_sniper/db/__init__.py`, `src/tcg_sniper/db/models.py`, `src/tcg_sniper/db/session.py`
- Create: `alembic.ini`, `src/tcg_sniper/db/migrations/env.py`, `src/tcg_sniper/db/migrations/versions/<gerado>_schema_inicial.py`
- Modify: `tests/conftest.py`
- Test: `tests/db/test_migracao.py`

**Interfaces:**
- Consumes: `Config.database_url`.
- Produces:
  - `tcg_sniper.db.models`: `Base`, enums `TipoColeta` (`CATALOGO`, `PRECOS`), `StatusColeta` (`RODANDO`, `OK`, `PARCIAL`, `FALHA`, `PAUSADA_DESAFIO`), `EstadoColetorTipo` (`ATIVO`, `PAUSADO_DESAFIO`); modelos `ProdutoLiga`, `Coleta`, `ResumoPreco`, `PrecoAtualLiga`, `EstadoColetor` com as colunas da spec.
  - `tcg_sniper.db.session`: `criar_engine(url: str) -> Engine`, `criar_sessoes(engine) -> sessionmaker[Session]` (com `expire_on_commit=False`), `migrar(url: str) -> None`.
  - Fixtures pytest: `engine` (sessão de testes, banco `tcg_test` migrado do zero), `sessoes` (sessionmaker isolado por teste, tudo desfeito no fim), `s` (uma `Session` aberta de `sessoes`).

- [ ] **Step 1: Escrever os modelos**

`src/tcg_sniper/db/__init__.py`: arquivo vazio.

`src/tcg_sniper/db/models.py`:
```python
import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TipoColeta(enum.StrEnum):
    CATALOGO = "catalogo"
    PRECOS = "precos"


class StatusColeta(enum.StrEnum):
    RODANDO = "rodando"
    OK = "ok"
    PARCIAL = "parcial"
    FALHA = "falha"
    PAUSADA_DESAFIO = "pausada_desafio"


class EstadoColetorTipo(enum.StrEnum):
    ATIVO = "ativo"
    PAUSADO_DESAFIO = "pausado_desafio"


def _enum(cls: type[enum.Enum], nome: str) -> Enum:
    return Enum(
        cls,
        name=nome,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda e: [m.value for m in e],
    )


DINHEIRO = Numeric(10, 2)
DATA = DateTime(timezone=True)


class ProdutoLiga(Base):
    __tablename__ = "produto_liga"

    id: Mapped[int] = mapped_column(primary_key=True)
    liga_id: Mapped[str] = mapped_column(Text, unique=True)
    nome: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    edicao: Mapped[str | None] = mapped_column(Text)
    tipo: Mapped[str | None] = mapped_column(Text)
    idioma: Mapped[str | None] = mapped_column(Text)
    ean: Mapped[str | None] = mapped_column(Text)
    ativo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    visto_primeiro_em: Mapped[datetime] = mapped_column(DATA)
    visto_ultimo_em: Mapped[datetime] = mapped_column(DATA)


class Coleta(Base):
    __tablename__ = "coleta"

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[TipoColeta] = mapped_column(_enum(TipoColeta, "tipo_coleta"))
    iniciada_em: Mapped[datetime] = mapped_column(DATA)
    finalizada_em: Mapped[datetime | None] = mapped_column(DATA)
    status: Mapped[StatusColeta] = mapped_column(_enum(StatusColeta, "status_coleta"))
    produtos_ok: Mapped[int] = mapped_column(Integer, default=0)
    produtos_falha: Mapped[int] = mapped_column(Integer, default=0)
    erro: Mapped[str | None] = mapped_column(Text)


class ResumoPreco(Base):
    __tablename__ = "resumo_preco"

    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"), primary_key=True)
    coleta_id: Mapped[int] = mapped_column(ForeignKey("coleta.id"), primary_key=True)
    preco_min: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    preco_medio: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    preco_max: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    num_lojas: Mapped[int] = mapped_column(Integer)
    coletado_em: Mapped[datetime] = mapped_column(DATA)


class PrecoAtualLiga(Base):
    __tablename__ = "preco_atual_liga"

    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"), primary_key=True)
    coleta_id: Mapped[int] = mapped_column(ForeignKey("coleta.id"))
    preco_min: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    preco_medio: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    preco_max: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    num_lojas: Mapped[int] = mapped_column(Integer)
    atualizado_em: Mapped[datetime] = mapped_column(DATA)


class EstadoColetor(Base):
    __tablename__ = "estado_coletor"
    __table_args__ = (CheckConstraint("id = 1", name="ck_estado_coletor_linha_unica"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    estado: Mapped[EstadoColetorTipo] = mapped_column(_enum(EstadoColetorTipo, "estado_coletor_tipo"))
    motivo: Mapped[str | None] = mapped_column(Text)
    execucao_solicitada: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    atualizado_em: Mapped[datetime] = mapped_column(DATA)
```

`src/tcg_sniper/db/session.py`:
```python
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DIR_MIGRACOES = Path(__file__).parent / "migrations"


def criar_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


def criar_sessoes(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def migrar(url: str) -> None:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(DIR_MIGRACOES))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
```

- [ ] **Step 2: Inicializar o Alembic**

Run: `uv run alembic init src/tcg_sniper/db/migrations`
Expected: cria `alembic.ini` na raiz e `src/tcg_sniper/db/migrations/` com `env.py`, `script.py.mako`, `versions/`.

Em `alembic.ini`, troque a linha `sqlalchemy.url = driver://user:pass@localhost/dbname` por:
```ini
sqlalchemy.url =
```

Substitua todo o `src/tcg_sniper/db/migrations/env.py` por:
```python
from alembic import context
from sqlalchemy import create_engine, pool

from tcg_sniper.config import Config
from tcg_sniper.db.models import Base

config = context.config
target_metadata = Base.metadata


def executar() -> None:
    url = config.get_main_option("sqlalchemy.url") or Config().database_url
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as conexao:
        context.configure(connection=conexao, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


executar()
```

Apague o `src/tcg_sniper/db/migrations/README` gerado, se existir.

- [ ] **Step 3: Gerar a migração inicial**

Pré-requisito: `docker compose up -d postgres` e um `.env` com `DATABASE_URL=postgresql+psycopg://tcg:tcg@localhost:5432/tcg` (copie de `.env.example`).

Run: `uv run alembic revision --autogenerate -m "schema inicial"`
Expected: novo arquivo `src/tcg_sniper/db/migrations/versions/<hash>_schema_inicial.py`.

Revise o arquivo gerado: ele precisa criar as 5 tabelas, a unique de `produto_liga.liga_id`, as CHECK constraints dos três enums e a `ck_estado_coletor_linha_unica`. Se faltar alguma CHECK de enum, adicione no `op.create_table` correspondente, por exemplo `sa.CheckConstraint("status IN ('rodando','ok','parcial','falha','pausada_desafio')", name="status_coleta")`.

- [ ] **Step 4: Fixtures de banco nos testes**

Acrescente a `tests/conftest.py`:
```python
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from tcg_sniper.db.session import migrar

URL_TESTE = os.environ.get(
    "DATABASE_URL_TESTE", "postgresql+psycopg://tcg:tcg@localhost:5432/tcg_test"
)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(URL_TESTE)
    with eng.begin() as conexao:
        conexao.execute(text("DROP SCHEMA public CASCADE"))
        conexao.execute(text("CREATE SCHEMA public"))
    migrar(URL_TESTE)
    yield eng
    eng.dispose()


@pytest.fixture
def sessoes(engine):
    """sessionmaker isolado: tudo que o teste gravar é desfeito no fim."""
    conexao = engine.connect()
    transacao = conexao.begin()
    fabrica = sessionmaker(
        bind=conexao, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    yield fabrica
    transacao.rollback()
    conexao.close()


@pytest.fixture
def s(sessoes):
    with sessoes() as sessao:
        yield sessao
```

- [ ] **Step 5: Escrever o teste da migração**

`tests/db/test_migracao.py`:
```python
from datetime import UTC, datetime

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.exc import IntegrityError

from tcg_sniper.db.models import Base, EstadoColetor, EstadoColetorTipo


def test_migracao_igual_aos_modelos(engine):
    with engine.connect() as conexao:
        diferencas = compare_metadata(MigrationContext.configure(conexao), Base.metadata)
    assert diferencas == []


def test_estado_coletor_aceita_so_uma_linha(s):
    agora = datetime.now(UTC)
    s.add(EstadoColetor(id=2, estado=EstadoColetorTipo.ATIVO, atualizado_em=agora))
    with pytest.raises(IntegrityError):
        s.flush()
```

- [ ] **Step 6: Rodar**

Run: `uv run pytest tests/db/test_migracao.py -v`
Expected: 2 passed. Se `test_migracao_igual_aos_modelos` listar diferenças, ajuste a migração gerada (não os modelos) até a lista ficar vazia.

- [ ] **Step 7: Commit**

```bash
git add alembic.ini src/tcg_sniper/db tests/conftest.py tests/db
git commit -m "feat: database models and initial migration"
```

---

### Task 3: Modelos de domínio, resumo de preço e repositório

> **Revisão 2026-10-13 (só resumo):** as ofertas por vendedor da LigaMagic são ofuscadas (sprite CSS) e só 16 aparecem sem JavaScript; por decisão do usuário o coletor guarda só o resumo textual da página (mín, médio, máx, nº de lojas). `Oferta`, `calcular_resumo` e `oferta_liga` foram removidos; os blocos abaixo já refletem o código atual. Ver a spec, "Decisão: só o resumo de preços".


**Files:**
- Create: `src/tcg_sniper/coletor_liga/__init__.py`, `src/tcg_sniper/coletor_liga/modelos.py`, `src/tcg_sniper/db/repositorio.py`
- Create: `tests/fakes.py`
- Test: `tests/db/test_repositorio.py`

**Interfaces:**
- Consumes: modelos e enums da Task 2; fixture `s`.
- Produces:
  - `coletor_liga.modelos`: dataclasses frozen `Resumo(preco_min: Decimal | None, preco_medio: Decimal | None, preco_max: Decimal | None, num_lojas: int)`, `ItemCatalogo(liga_id: str, nome: str, url: str, edicao: str | None = None, tipo: str | None = None, idioma: str | None = None)`, `PaginaCatalogo(itens: list[ItemCatalogo], proxima_url: str | None)`, `Pagina(url: str, status: int, html: str, titulo: str, headers: dict[str, str])`; exceções `ErroParser`, `ErroRede`.
  - `db.repositorio`: `agora_utc()`, `produtos_ativos(s)`, `iniciar_coleta(s, tipo, agora) -> Coleta`, `status_final(ok, falha, limite_falha_pct) -> StatusColeta`, `finalizar_coleta(s, coleta_id, status, ok, falha, agora, erro=None)`, `gravar_precos_produto(s, coleta_id, produto_id, resumo, agora)`, `upsert_catalogo(s, itens, agora) -> int` (quantidade de novos), `obter_estado(s, agora=None) -> EstadoColetor`, `pausar_por_desafio(s, motivo, agora)`, `retomar(s, agora)`, `solicitar_execucao(s, agora)`, `consumir_solicitacao(s, agora) -> bool`, `marcar_interrompidas(s, agora) -> int`, `ultima_coleta_sucesso(s, tipo) -> datetime | None`, `coleta_iniciada_desde(s, tipo, desde) -> bool`.
  - `tests/fakes.py`: `criar_produto(s, liga_id="p1", ativo=True, agora=T0, nome=None, url=None) -> ProdutoLiga`, constante `T0`.

- [ ] **Step 1: Escrever os modelos de domínio**

`src/tcg_sniper/coletor_liga/__init__.py`: arquivo vazio.

`src/tcg_sniper/coletor_liga/modelos.py`:
```python
from dataclasses import dataclass, field
from decimal import Decimal


class ErroParser(Exception):
    """HTML não tem a estrutura esperada (provável mudança de layout)."""


class ErroRede(Exception):
    """Falha de navegação: timeout, conexão, DNS."""


@dataclass(frozen=True)
class Resumo:
    """Quadro de preços da página de produto ("Preço Médio de Venda no Marketplace") + nº de lojas.

    Os preços vêm do resumo textual da LigaMagic (os preços por oferta são ofuscados em
    sprite e não são lidos). `None` quando a página não mostra o quadro.
    """

    preco_min: Decimal | None
    preco_medio: Decimal | None
    preco_max: Decimal | None
    num_lojas: int


@dataclass(frozen=True)
class ItemCatalogo:
    liga_id: str
    nome: str
    url: str
    edicao: str | None = None
    tipo: str | None = None
    idioma: str | None = None


@dataclass(frozen=True)
class PaginaCatalogo:
    itens: list[ItemCatalogo]
    proxima_url: str | None


@dataclass(frozen=True)
class Pagina:
    url: str
    status: int
    html: str
    titulo: str
    headers: dict[str, str] = field(default_factory=dict)
```

- [ ] **Steps 2 e 3: (removidos)** `resumo.py`/`calcular_resumo` deixaram de existir: o resumo vem pronto do parser (Task 6).

- [ ] **Step 4: Criar `tests/fakes.py` e os testes do repositório**

`tests/fakes.py`:
```python
from datetime import UTC, datetime

from tcg_sniper.db.models import ProdutoLiga

T0 = datetime(2026, 10, 13, 13, 0, tzinfo=UTC)


def criar_produto(s, liga_id="p1", ativo=True, agora=T0, nome=None, url=None) -> ProdutoLiga:
    produto = ProdutoLiga(
        liga_id=liga_id,
        nome=nome or f"Produto {liga_id}",
        url=url or f"https://liga.test/produto/{liga_id}",
        ativo=ativo,
        visto_primeiro_em=agora,
        visto_ultimo_em=agora,
    )
    s.add(produto)
    s.flush()
    return produto
```

`tests/db/test_repositorio.py`:
```python
from datetime import timedelta
from decimal import Decimal

from fakes import T0, criar_produto
from sqlalchemy import func, select

from tcg_sniper.coletor_liga.modelos import ItemCatalogo, Resumo
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import (
    Coleta,
    EstadoColetorTipo,
    PrecoAtualLiga,
    ProdutoLiga,
    ResumoPreco,
    StatusColeta,
    TipoColeta,
)


def item(liga_id, nome=None, edicao=None):
    return ItemCatalogo(
        liga_id=liga_id, nome=nome or f"Caixa {liga_id}", url=f"https://liga.test/{liga_id}", edicao=edicao
    )


def test_status_final():
    assert repo.status_final(5, 0, 50) is StatusColeta.OK
    assert repo.status_final(0, 0, 50) is StatusColeta.OK
    assert repo.status_final(3, 2, 50) is StatusColeta.PARCIAL
    assert repo.status_final(2, 2, 50) is StatusColeta.PARCIAL
    assert repo.status_final(1, 2, 50) is StatusColeta.FALHA


def test_upsert_catalogo_conta_novos_e_preserva_ativo(s):
    assert repo.upsert_catalogo(s, [item("a"), item("b")], T0) == 2
    produto_a = s.scalar(select(ProdutoLiga).where(ProdutoLiga.liga_id == "a"))
    produto_a.ativo = True
    s.flush()

    depois = T0 + timedelta(days=7)
    assert repo.upsert_catalogo(s, [item("a", nome="Caixa A nova"), item("c")], depois) == 1

    s.expire_all()
    produto_a = s.scalar(select(ProdutoLiga).where(ProdutoLiga.liga_id == "a"))
    assert produto_a.nome == "Caixa A nova"
    assert produto_a.ativo is True
    assert produto_a.visto_primeiro_em == T0
    assert produto_a.visto_ultimo_em == depois


def test_upsert_catalogo_item_repetido_na_mesma_lista(s):
    assert repo.upsert_catalogo(s, [item("a"), item("a")], T0) == 1
    assert s.scalar(select(func.count()).select_from(ProdutoLiga)) == 1


def test_upsert_catalogo_nao_apaga_edicao_com_none(s):
    repo.upsert_catalogo(s, [item("a", edicao="Duskmourn")], T0)
    repo.upsert_catalogo(s, [item("a", edicao=None)], T0 + timedelta(days=1))
    s.expire_all()
    assert s.scalar(select(ProdutoLiga.edicao).where(ProdutoLiga.liga_id == "a")) == "Duskmourn"


def test_upsert_catalogo_lista_vazia(s):
    assert repo.upsert_catalogo(s, [], T0) == 0


def test_gravar_precos_produto_grava_historico_e_atualiza_atual(s):
    produto = criar_produto(s)
    c1 = repo.iniciar_coleta(s, TipoColeta.PRECOS, T0)
    resumo1 = Resumo(Decimal("850.00"), Decimal("874.95"), Decimal("899.90"), 2)
    repo.gravar_precos_produto(s, c1.id, produto.id, resumo1, T0)

    c2 = repo.iniciar_coleta(s, TipoColeta.PRECOS, T0 + timedelta(days=1))
    resumo2 = Resumo(Decimal("799.00"), Decimal("799.00"), Decimal("799.00"), 1)
    repo.gravar_precos_produto(s, c2.id, produto.id, resumo2, T0 + timedelta(days=1))

    historico = s.scalars(select(ResumoPreco).order_by(ResumoPreco.coletado_em)).all()
    assert [(r.coleta_id, r.preco_min, r.num_lojas) for r in historico] == [
        (c1.id, Decimal("850.00"), 2),
        (c2.id, Decimal("799.00"), 1),
    ]
    atual = s.scalars(select(PrecoAtualLiga)).one()
    assert atual.coleta_id == c2.id
    assert (atual.preco_min, atual.preco_medio, atual.preco_max, atual.num_lojas) == (
        Decimal("799.00"),
        Decimal("799.00"),
        Decimal("799.00"),
        1,
    )
    assert atual.atualizado_em == T0 + timedelta(days=1)


def test_gravar_precos_produto_sem_precos(s):
    produto = criar_produto(s)
    c = repo.iniciar_coleta(s, TipoColeta.PRECOS, T0)
    repo.gravar_precos_produto(s, c.id, produto.id, Resumo(None, None, None, 0), T0)
    atual = s.scalars(select(PrecoAtualLiga)).one()
    assert (atual.preco_min, atual.preco_medio, atual.preco_max, atual.num_lojas) == (None, None, None, 0)


def test_estado_pausa_retoma_e_solicitacao(s):
    assert repo.obter_estado(s, T0).estado is EstadoColetorTipo.ATIVO

    repo.solicitar_execucao(s, T0)
    repo.pausar_por_desafio(s, "desafio em /x", T0)
    estado = repo.obter_estado(s)
    assert estado.estado is EstadoColetorTipo.PAUSADO_DESAFIO
    assert estado.motivo == "desafio em /x"
    assert repo.consumir_solicitacao(s, T0) is False

    repo.retomar(s, T0)
    assert repo.obter_estado(s).estado is EstadoColetorTipo.ATIVO
    assert repo.consumir_solicitacao(s, T0) is True
    assert repo.consumir_solicitacao(s, T0) is False


def test_marcar_interrompidas(s):
    rodando = repo.iniciar_coleta(s, TipoColeta.PRECOS, T0)
    pronta = repo.iniciar_coleta(s, TipoColeta.PRECOS, T0)
    repo.finalizar_coleta(s, pronta.id, StatusColeta.OK, 1, 0, T0)

    assert repo.marcar_interrompidas(s, T0 + timedelta(hours=1)) == 1
    s.expire_all()
    assert s.get(Coleta, rodando.id).status is StatusColeta.FALHA
    assert s.get(Coleta, rodando.id).erro == "interrompida"
    assert s.get(Coleta, pronta.id).status is StatusColeta.OK


def test_ultima_coleta_sucesso_ignora_falha_e_pausada(s):
    assert repo.ultima_coleta_sucesso(s, TipoColeta.PRECOS) is None
    for horas, status in [(0, StatusColeta.OK), (1, StatusColeta.PARCIAL), (2, StatusColeta.FALHA), (3, StatusColeta.PAUSADA_DESAFIO)]:
        c = repo.iniciar_coleta(s, TipoColeta.PRECOS, T0 + timedelta(hours=horas))
        repo.finalizar_coleta(s, c.id, status, 0, 0, T0)
    assert repo.ultima_coleta_sucesso(s, TipoColeta.PRECOS) == T0 + timedelta(hours=1)
    assert repo.ultima_coleta_sucesso(s, TipoColeta.CATALOGO) is None


def test_coleta_iniciada_desde(s):
    repo.iniciar_coleta(s, TipoColeta.PRECOS, T0)
    assert repo.coleta_iniciada_desde(s, TipoColeta.PRECOS, T0 - timedelta(hours=1)) is True
    assert repo.coleta_iniciada_desde(s, TipoColeta.PRECOS, T0 + timedelta(hours=1)) is False
    assert repo.coleta_iniciada_desde(s, TipoColeta.CATALOGO, T0 - timedelta(hours=1)) is False


def test_produtos_ativos(s):
    criar_produto(s, "a", ativo=True)
    criar_produto(s, "b", ativo=False)
    assert [p.liga_id for p in repo.produtos_ativos(s)] == ["a"]
```

Run: `uv run pytest tests/db/test_repositorio.py -v`
Expected: FAIL, `ImportError: cannot import name 'repositorio'`.

- [ ] **Step 5: Implementar o repositório**

`src/tcg_sniper/db/repositorio.py`:
```python
"""Operações de banco usadas pelo coletor e pelo agendador."""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tcg_sniper.coletor_liga.modelos import ItemCatalogo, Resumo
from tcg_sniper.db.models import (
    Coleta,
    EstadoColetor,
    EstadoColetorTipo,
    PrecoAtualLiga,
    ProdutoLiga,
    ResumoPreco,
    StatusColeta,
    TipoColeta,
)


def agora_utc() -> datetime:
    return datetime.now(UTC)


def produtos_ativos(s: Session) -> list[ProdutoLiga]:
    consulta = select(ProdutoLiga).where(ProdutoLiga.ativo.is_(True)).order_by(ProdutoLiga.id)
    return list(s.scalars(consulta))


def iniciar_coleta(s: Session, tipo: TipoColeta, agora: datetime) -> Coleta:
    coleta = Coleta(
        tipo=tipo, iniciada_em=agora, status=StatusColeta.RODANDO, produtos_ok=0, produtos_falha=0
    )
    s.add(coleta)
    s.flush()
    return coleta


def status_final(ok: int, falha: int, limite_falha_pct: int) -> StatusColeta:
    if falha == 0:
        return StatusColeta.OK
    if falha * 100 > limite_falha_pct * (ok + falha):
        return StatusColeta.FALHA
    return StatusColeta.PARCIAL


def finalizar_coleta(
    s: Session,
    coleta_id: int,
    status: StatusColeta,
    ok: int,
    falha: int,
    agora: datetime,
    erro: str | None = None,
) -> None:
    s.execute(
        update(Coleta)
        .where(Coleta.id == coleta_id)
        .values(status=status, produtos_ok=ok, produtos_falha=falha, finalizada_em=agora, erro=erro)
    )


def gravar_precos_produto(
    s: Session,
    coleta_id: int,
    produto_id: int,
    resumo: Resumo,
    agora: datetime,
) -> None:
    """Acrescenta o resumo ao histórico (append-only) e faz upsert do preço atual."""
    valores = {
        "coleta_id": coleta_id,
        "preco_min": resumo.preco_min,
        "preco_medio": resumo.preco_medio,
        "preco_max": resumo.preco_max,
        "num_lojas": resumo.num_lojas,
    }
    s.add(ResumoPreco(produto_id=produto_id, coletado_em=agora, **valores))
    atual = {**valores, "atualizado_em": agora}
    s.execute(
        pg_insert(PrecoAtualLiga)
        .values(produto_id=produto_id, **atual)
        .on_conflict_do_update(index_elements=[PrecoAtualLiga.produto_id], set_=atual)
    )
    s.flush()


def upsert_catalogo(s: Session, itens: Sequence[ItemCatalogo], agora: datetime) -> int:
    """Insere ou atualiza produtos do catálogo. Nunca altera `ativo`. Retorna quantos são novos."""
    unicos = {i.liga_id: i for i in itens}
    if not unicos:
        return 0
    existentes = set(s.scalars(select(ProdutoLiga.liga_id).where(ProdutoLiga.liga_id.in_(unicos))))
    for i in unicos.values():
        stmt = pg_insert(ProdutoLiga).values(
            liga_id=i.liga_id,
            nome=i.nome,
            url=i.url,
            edicao=i.edicao,
            tipo=i.tipo,
            idioma=i.idioma,
            ativo=False,
            visto_primeiro_em=agora,
            visto_ultimo_em=agora,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[ProdutoLiga.liga_id],
            set_={
                "nome": stmt.excluded.nome,
                "url": stmt.excluded.url,
                "visto_ultimo_em": stmt.excluded.visto_ultimo_em,
                "edicao": func.coalesce(stmt.excluded.edicao, ProdutoLiga.edicao),
                "tipo": func.coalesce(stmt.excluded.tipo, ProdutoLiga.tipo),
                "idioma": func.coalesce(stmt.excluded.idioma, ProdutoLiga.idioma),
            },
        )
        s.execute(stmt)
    return len(unicos.keys() - existentes)


def obter_estado(s: Session, agora: datetime | None = None) -> EstadoColetor:
    s.execute(
        pg_insert(EstadoColetor)
        .values(
            id=1,
            estado=EstadoColetorTipo.ATIVO,
            execucao_solicitada=False,
            atualizado_em=agora or agora_utc(),
        )
        .on_conflict_do_nothing(index_elements=[EstadoColetor.id])
    )
    return s.get(EstadoColetor, 1, populate_existing=True)


def pausar_por_desafio(s: Session, motivo: str, agora: datetime) -> None:
    estado = obter_estado(s, agora)
    estado.estado = EstadoColetorTipo.PAUSADO_DESAFIO
    estado.motivo = motivo
    estado.execucao_solicitada = False
    estado.atualizado_em = agora
    s.flush()


def retomar(s: Session, agora: datetime) -> None:
    estado = obter_estado(s, agora)
    estado.estado = EstadoColetorTipo.ATIVO
    estado.motivo = None
    estado.execucao_solicitada = True
    estado.atualizado_em = agora
    s.flush()


def solicitar_execucao(s: Session, agora: datetime) -> None:
    estado = obter_estado(s, agora)
    estado.execucao_solicitada = True
    estado.atualizado_em = agora
    s.flush()


def consumir_solicitacao(s: Session, agora: datetime) -> bool:
    estado = obter_estado(s, agora)
    if estado.estado != EstadoColetorTipo.ATIVO or not estado.execucao_solicitada:
        return False
    estado.execucao_solicitada = False
    estado.atualizado_em = agora
    s.flush()
    return True


def marcar_interrompidas(s: Session, agora: datetime) -> int:
    resultado = s.execute(
        update(Coleta)
        .where(Coleta.status == StatusColeta.RODANDO)
        .values(status=StatusColeta.FALHA, erro="interrompida", finalizada_em=agora)
    )
    return resultado.rowcount


def ultima_coleta_sucesso(s: Session, tipo: TipoColeta) -> datetime | None:
    return s.scalar(
        select(func.max(Coleta.iniciada_em)).where(
            Coleta.tipo == tipo, Coleta.status.in_([StatusColeta.OK, StatusColeta.PARCIAL])
        )
    )


def coleta_iniciada_desde(s: Session, tipo: TipoColeta, desde: datetime) -> bool:
    total = s.scalar(
        select(func.count()).select_from(Coleta).where(Coleta.tipo == tipo, Coleta.iniciada_em >= desde)
    )
    return total > 0
```

- [ ] **Step 6: Rodar**

Run: `uv run pytest tests/db -v`
Expected: todos passam.

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/coletor_liga src/tcg_sniper/db/repositorio.py tests/fakes.py tests/coletor_liga tests/db
git commit -m "feat: domain models, price summary and repository"
```

---

### Task 4: Notificador (log e Evolution API)

**Files:**
- Create: `src/tcg_sniper/notificador/__init__.py`, `base.py`, `log.py`, `evolution.py`
- Modify: `tests/fakes.py`
- Test: `tests/notificador/test_notificador.py`

**Interfaces:**
- Consumes: `Config`.
- Produces:
  - `notificador.base`: `Destino` (StrEnum `ADMIN = "admin"`, `OPORTUNIDADES = "oportunidades"`), `Notificador` (Protocol com `enviar(destino: Destino, texto: str) -> None`).
  - `notificador.log.LogNotificador()`.
  - `notificador.evolution.EvolutionNotificador(url: str, api_key: str, instancia: str, grupos: dict[Destino, str], cliente: httpx.Client | None = None, dormir=time.sleep, tentativas: int = 3)`.
  - `notificador.criar_notificador(config: Config) -> Notificador`.
  - `tests/fakes.NotificadorFake` com atributo `mensagens: list[tuple[Destino, str]]`.

- [ ] **Step 1: Escrever os testes**

Acrescente a `tests/fakes.py`:
```python
from tcg_sniper.notificador.base import Destino


class NotificadorFake:
    def __init__(self):
        self.mensagens: list[tuple[Destino, str]] = []

    def enviar(self, destino: Destino, texto: str) -> None:
        self.mensagens.append((destino, texto))
```

`tests/notificador/test_notificador.py`:
```python
import json

import httpx
import respx

from tcg_sniper.notificador import criar_notificador
from tcg_sniper.notificador.base import Destino
from tcg_sniper.notificador.evolution import EvolutionNotificador
from tcg_sniper.notificador.log import LogNotificador

URL = "http://evo.test"
GRUPOS = {Destino.ADMIN: "120363000000000001@g.us"}


def notificador(pausas):
    return EvolutionNotificador(URL, "chave", "inst", GRUPOS, dormir=pausas.append)


@respx.mock
def test_envia_para_o_grupo_do_destino():
    rota = respx.post(f"{URL}/message/sendText/inst").mock(return_value=httpx.Response(201))
    notificador([]).enviar(Destino.ADMIN, "olá")
    assert rota.call_count == 1
    pedido = rota.calls.last.request
    assert pedido.headers["apikey"] == "chave"
    assert json.loads(pedido.read()) == {"number": "120363000000000001@g.us", "text": "olá"}


@respx.mock
def test_tenta_de_novo_e_desiste_sem_lancar_excecao():
    rota = respx.post(f"{URL}/message/sendText/inst").mock(return_value=httpx.Response(500))
    pausas = []
    notificador(pausas).enviar(Destino.ADMIN, "x")
    assert rota.call_count == 3
    assert pausas == [1, 2]


@respx.mock
def test_sucesso_na_segunda_tentativa():
    rota = respx.post(f"{URL}/message/sendText/inst").mock(
        side_effect=[httpx.ConnectError("caiu"), httpx.Response(201)]
    )
    pausas = []
    notificador(pausas).enviar(Destino.ADMIN, "x")
    assert rota.call_count == 2
    assert pausas == [1]


@respx.mock
def test_destino_sem_grupo_nao_envia():
    rota = respx.post(f"{URL}/message/sendText/inst")
    notificador([]).enviar(Destino.OPORTUNIDADES, "x")
    assert rota.call_count == 0


def test_criar_notificador_sem_evolution_usa_log(config):
    assert isinstance(criar_notificador(config), LogNotificador)


def test_criar_notificador_com_evolution(config):
    c = config.model_copy(
        update={
            "evolution_url": URL,
            "evolution_api_key": "chave",
            "evolution_instancia": "inst",
            "whatsapp_grupo_admin": "g@g.us",
        }
    )
    assert isinstance(criar_notificador(c), EvolutionNotificador)
```

Run: `uv run pytest tests/notificador -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'tcg_sniper.notificador'`.

- [ ] **Step 2: Implementar**

`src/tcg_sniper/notificador/base.py`:
```python
from enum import StrEnum
from typing import Protocol


class Destino(StrEnum):
    ADMIN = "admin"
    OPORTUNIDADES = "oportunidades"


class Notificador(Protocol):
    def enviar(self, destino: Destino, texto: str) -> None:
        """Envia a mensagem. Nunca lança exceção: falhas são registradas em log."""
```

`src/tcg_sniper/notificador/log.py`:
```python
import logging

from tcg_sniper.notificador.base import Destino

log = logging.getLogger(__name__)


class LogNotificador:
    def enviar(self, destino: Destino, texto: str) -> None:
        log.info("[notificação %s] %s", destino.value, texto)
```

`src/tcg_sniper/notificador/evolution.py`:
```python
import logging
import time
from collections.abc import Callable

import httpx

from tcg_sniper.notificador.base import Destino

log = logging.getLogger(__name__)


class EvolutionNotificador:
    def __init__(
        self,
        url: str,
        api_key: str,
        instancia: str,
        grupos: dict[Destino, str],
        cliente: httpx.Client | None = None,
        dormir: Callable[[float], None] = time.sleep,
        tentativas: int = 3,
    ):
        self._endpoint = f"{url.rstrip('/')}/message/sendText/{instancia}"
        self._api_key = api_key
        self._grupos = grupos
        self._cliente = cliente or httpx.Client(timeout=15)
        self._dormir = dormir
        self._tentativas = tentativas

    def enviar(self, destino: Destino, texto: str) -> None:
        grupo = self._grupos.get(destino)
        if not grupo:
            log.warning("sem grupo configurado para %s; mensagem descartada: %s", destino.value, texto)
            return
        for tentativa in range(1, self._tentativas + 1):
            try:
                resposta = self._cliente.post(
                    self._endpoint,
                    headers={"apikey": self._api_key},
                    json={"number": grupo, "text": texto},
                )
                resposta.raise_for_status()
                return
            except httpx.HTTPError as erro:
                log.warning("envio para %s falhou (tentativa %d): %s", destino.value, tentativa, erro)
                if tentativa < self._tentativas:
                    self._dormir(2 ** (tentativa - 1))
        log.error("desisti de enviar para %s: %s", destino.value, texto)
```

`src/tcg_sniper/notificador/__init__.py`:
```python
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
```

- [ ] **Step 3: Rodar**

Run: `uv run pytest tests/notificador -v`
Expected: 6 passed.

- [ ] **Step 4: Commit**

```bash
git add src/tcg_sniper/notificador tests/fakes.py tests/notificador
git commit -m "feat: notifier interface with log and Evolution API implementations"
```

---

### Task 5: Navegador, detecção de desafio e script de captura

**Files:**
- Create: `src/tcg_sniper/coletor_liga/desafio.py`, `src/tcg_sniper/coletor_liga/navegador.py`, `scripts/capturar_fixture.py`
- Modify: `tests/fakes.py`
- Test: `tests/coletor_liga/test_desafio.py`

**Interfaces:**
- Consumes: `Pagina`, `ErroRede` (Task 3).
- Produces:
  - `desafio.eh_desafio(pagina: Pagina) -> bool`.
  - `navegador.Navegador` (Protocol com `abrir(url: str) -> Pagina`, lança `ErroRede`), `navegador.NavegadorPlaywright(dir_perfil: Path, timeout_ms: int = 45_000, espera_pos_carga_ms: int = 2_000)`, usado como context manager.
  - `tests/fakes`: `pagina_html(html, url="https://liga.test/x", titulo="LigaMagic", status=200, headers=None) -> Pagina`, `NavegadorFake(paginas: dict[str, Pagina | Exception | list[Pagina | Exception]])` com atributo `visitadas: list[str]`, `fixture_liga(nome: str) -> str`.

- [ ] **Step 1: Fakes de navegador**

Acrescente a `tests/fakes.py`:
```python
from pathlib import Path

from tcg_sniper.coletor_liga.modelos import Pagina

DIR_FIXTURES = Path(__file__).parent / "fixtures" / "liga"


def fixture_liga(nome: str) -> str:
    return (DIR_FIXTURES / f"{nome}.html").read_text(encoding="utf-8")


def pagina_html(html, url="https://liga.test/x", titulo="LigaMagic", status=200, headers=None) -> Pagina:
    return Pagina(url=url, status=status, html=html, titulo=titulo, headers=headers or {})


class NavegadorFake:
    """Devolve páginas pré-definidas por URL. Uma lista é consumida em ordem (para testar retry)."""

    def __init__(self, paginas):
        self.paginas = paginas
        self.visitadas: list[str] = []

    def abrir(self, url: str) -> Pagina:
        self.visitadas.append(url)
        resposta = self.paginas[url]
        if isinstance(resposta, list):
            resposta = resposta.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta
```

- [ ] **Step 2: Teste da detecção de desafio**

`tests/coletor_liga/test_desafio.py`:
```python
from fakes import pagina_html

from tcg_sniper.coletor_liga.desafio import eh_desafio

PAGINA_CF = """<!DOCTYPE html><html><head><title>Just a moment...</title></head>
<body><div id="challenge-form"></div>
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script></body></html>"""


def test_titulo_just_a_moment():
    assert eh_desafio(pagina_html("<html></html>", titulo="Just a moment..."))


def test_titulo_em_portugues():
    assert eh_desafio(pagina_html("<html></html>", titulo="Um momento…"))


def test_html_com_formulario_de_desafio():
    assert eh_desafio(pagina_html(PAGINA_CF, titulo=""))


def test_header_cf_mitigated_com_403():
    assert eh_desafio(pagina_html("<html></html>", status=403, headers={"cf-mitigated": "challenge"}))


def test_403_sem_header_cloudflare_nao_e_desafio():
    assert not eh_desafio(pagina_html("<html></html>", status=403))


def test_pagina_normal():
    assert not eh_desafio(pagina_html("<html><body><h1>Caixa de booster</h1></body></html>"))
```

Run: `uv run pytest tests/coletor_liga/test_desafio.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'tcg_sniper.coletor_liga.desafio'`.

- [ ] **Step 3: Implementar `desafio.py`**

```python
from tcg_sniper.coletor_liga.modelos import Pagina

TITULOS_DESAFIO = ("just a moment", "um momento")
# Marcadores exclusivos da página interstitial. Não usar "cf-turnstile" nem
# "/cdn-cgi/challenge-platform" sozinhos: o widget pode aparecer em formulários normais
# e o Cloudflare injeta scripts desse caminho em páginas comuns (ver teste com fixtures
# reais na Task 6).
MARCADORES_HTML = ('id="challenge-form"', "_cf_chl_opt", "cf-chl-")


def eh_desafio(pagina: Pagina) -> bool:
    titulo = pagina.titulo.strip().lower()
    if any(titulo.startswith(t) for t in TITULOS_DESAFIO):
        return True
    headers = {k.lower() for k in pagina.headers}
    if pagina.status in (403, 503) and "cf-mitigated" in headers:
        return True
    html = pagina.html.lower()
    return any(m in html for m in MARCADORES_HTML)
```

Run: `uv run pytest tests/coletor_liga/test_desafio.py -v`
Expected: 6 passed.

- [ ] **Step 4: Implementar `navegador.py`**

Sem teste unitário (é a borda com o Playwright); validado no Step 6.

```python
from pathlib import Path
from typing import Protocol

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from tcg_sniper.coletor_liga.modelos import ErroRede, Pagina


class Navegador(Protocol):
    def abrir(self, url: str) -> Pagina:
        """Abre a URL e devolve a página renderizada. Lança ErroRede em falha de navegação."""


class NavegadorPlaywright:
    """Chromium visível com perfil persistente. Use como context manager."""

    def __init__(self, dir_perfil: Path, timeout_ms: int = 45_000, espera_pos_carga_ms: int = 2_000):
        self._dir_perfil = dir_perfil
        self._timeout_ms = timeout_ms
        self._espera_ms = espera_pos_carga_ms

    def __enter__(self) -> "NavegadorPlaywright":
        self._dir_perfil.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._contexto = self._playwright.chromium.launch_persistent_context(
            str(self._dir_perfil),
            headless=False,
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport={"width": 1366, "height": 768},
        )
        paginas = self._contexto.pages
        self._pagina = paginas[0] if paginas else self._contexto.new_page()
        return self

    def __exit__(self, *_exc) -> None:
        self._contexto.close()
        self._playwright.stop()

    def abrir(self, url: str) -> Pagina:
        try:
            resposta = self._pagina.goto(url, wait_until="load", timeout=self._timeout_ms)
            self._pagina.wait_for_timeout(self._espera_ms)
            return Pagina(
                url=self._pagina.url,
                status=resposta.status if resposta else 0,
                html=self._pagina.content(),
                titulo=self._pagina.title(),
                headers=dict(resposta.headers) if resposta else {},
            )
        except PlaywrightError as erro:
            raise ErroRede(f"{url}: {erro}") from erro
```

- [ ] **Step 5: Script de captura de fixtures**

`scripts/capturar_fixture.py`:
```python
"""Captura o HTML renderizado de uma página da LigaMagic para virar fixture de teste.

Uso: uv run python scripts/capturar_fixture.py <url> <nome>
Salva em tests/fixtures/liga/<nome>.html. Usa o perfil .perfil-dev (fora do git).
"""

import sys
from pathlib import Path

from tcg_sniper.coletor_liga.desafio import eh_desafio
from tcg_sniper.coletor_liga.navegador import NavegadorPlaywright

DESTINO = Path("tests/fixtures/liga")


def main(url: str, nome: str) -> None:
    with NavegadorPlaywright(Path(".perfil-dev")) as navegador:
        pagina = navegador.abrir(url)
        if eh_desafio(pagina):
            input("Desafio detectado. Resolva na janela do Chromium e pressione Enter...")
            pagina = navegador.abrir(url)
    DESTINO.mkdir(parents=True, exist_ok=True)
    arquivo = DESTINO / f"{nome}.html"
    arquivo.write_text(pagina.html, encoding="utf-8")
    print(f"{arquivo}: {len(pagina.html)} bytes, status {pagina.status}, título {pagina.titulo!r}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
```

- [ ] **Step 6: Smoke test manual do navegador**

Run: `uv run playwright install chromium` e depois `uv run python scripts/capturar_fixture.py https://www.ligamagic.com.br/ smoke_home`
Expected: abre uma janela do Chromium, imprime `tests/fixtures/liga/smoke_home.html: ... bytes, status 200, ...`. Apague `tests/fixtures/liga/smoke_home.html` depois (não vai para o git).

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/coletor_liga/desafio.py src/tcg_sniper/coletor_liga/navegador.py scripts tests/fakes.py tests/coletor_liga/test_desafio.py
git commit -m "feat: playwright browser wrapper, challenge detection and fixture capture script"
```

---

### Task 6: Parsers da LigaMagic (com fixtures reais)

> **Revisão 2026-10-13 (só resumo).** A primeira captura mostrou que as ofertas por vendedor não são utilizáveis: preço e quantidade de cada oferta são desenhados com sprite CSS (classes aleatórias + `background-position`), a loja é só um logotipo, e a página mostra 16 ofertas com um botão "Ver Mais" (JavaScript) para o resto (16 de 94 na fixture). Decisão do usuário: não decodificar o sprite e não clicar em "Ver Mais"; ler só o quadro textual "Preço Médio de Venda no Marketplace" (mín, médio, máx) e o contador "Lojas". `parse_ofertas`/`parse_quantidade` saíram do contrato.
>
> **Catálogo em aberto.** A listagem de selados não é única (são categorias: `?view=cards/search&card=categ%3D<N>+searchprod%3D1&tipo=1`, ex. 10 = Caixas de Boosters) e carrega mais itens por JavaScript ("Exibir mais", `mcards.nextPage(40)`), sem link de próxima página no HTML. `parse_catalogo` e as fixtures `catalogo_*` ficam pendentes de decisão de design (Task 8 depende disso).

**Files:**
- Create: `tests/fixtures/liga/produto_varios_vendedores.html`, `produto_sem_estoque.html`, `produto_um_vendedor.html`
- Create: `src/tcg_sniper/coletor_liga/parsers.py`
- Test: `tests/coletor_liga/test_parsers.py`
- Pendente (catálogo): `tests/fixtures/liga/catalogo_pagina_1.html`, `catalogo_ultima_pagina.html`, `parse_catalogo`, valor de `LIGA_URL_CATALOGO` no `.env.example`

**Interfaces:**
- Consumes: `Resumo`, `ErroParser` (Task 3); `eh_desafio`, `fixture_liga`, `pagina_html` (Task 5).
- Produces: `parsers.parse_preco_brl(texto: str) -> Decimal`, `parsers.parse_produto(html: str) -> Resumo`. `parse_produto` lança `ErroParser` quando a estrutura da página de produto não existe; página válida sem lojas devolve `num_lojas == 0` (os preços do quadro, se a página mostrar o quadro, vêm mesmo assim: ele é histórico). Pendente: `parsers.parse_catalogo(html: str, url_base: str) -> PaginaCatalogo`.

- [x] **Step 1: Capturar as fixtures de produto** (uma por vez, ≥ 10 s entre elas)

```
uv run python scripts/capturar_fixture.py "https://www.ligamagic.com.br/?view=prod/view&pcode=137175&prod=Booster%20Avulso%20-%20Reality%20Fracture%20-%20Booster%20de%20Jogo" produto_varios_vendedores
uv run python scripts/capturar_fixture.py "https://www.ligamagic.com.br/?view=prod/view&pcode=276&prod=From%20the%20Vault:%20Relics%20Box%20Set" produto_sem_estoque
uv run python scripts/capturar_fixture.py "https://www.ligamagic.com.br/?view=prod/view&pcode=273&prod=From%20the%20Vault:%20Exiled%20Box%20Set" produto_um_vendedor
```

- [x] **Step 2: Estrutura registrada** no docstring de `parsers.py` (abaixo).

- [x] **Step 3: Testes** — `tests/coletor_liga/test_parsers.py`:
```python
from decimal import Decimal

import pytest
from fakes import fixture_liga, pagina_html

from tcg_sniper.coletor_liga.desafio import eh_desafio
from tcg_sniper.coletor_liga.modelos import ErroParser, Resumo
from tcg_sniper.coletor_liga.parsers import parse_preco_brl, parse_produto

# <title> real de cada fixture, registrado na captura (scripts/capturar_fixture.py).
TITULOS = {
    "produto_varios_vendedores": "Booster Avulso - Reality Fracture - Booster de Jogo"
    " | Busca de Produtos e Acessórios | LigaMagic",
    "produto_sem_estoque": "From the Vault: Relics Box Set | Busca de Produtos e Acessórios | LigaMagic",
    "produto_um_vendedor": "From the Vault: Exiled Box Set | Busca de Produtos e Acessórios | LigaMagic",
}


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("R$ 1.234,56", Decimal("1234.56")),
        ("R$\xa089,90", Decimal("89.90")),
        ("1234,56", Decimal("1234.56")),
        ("R$ 0,99", Decimal("0.99")),
        ("  R$ 12.345.678,00 ", Decimal("12345678.00")),
    ],
)
def test_parse_preco_brl(texto, esperado):
    assert parse_preco_brl(texto) == esperado


@pytest.mark.parametrize("texto", ["", "Esgotado", "R$ --", "R$ 12"])
def test_parse_preco_brl_invalido(texto):
    with pytest.raises(ErroParser):
        parse_preco_brl(texto)


@pytest.mark.parametrize(("nome", "titulo"), TITULOS.items())
def test_paginas_reais_nao_sao_desafio(nome, titulo):
    assert not eh_desafio(pagina_html(fixture_liga(nome), titulo=titulo))


def test_produto_varios_vendedores():
    assert parse_produto(fixture_liga("produto_varios_vendedores")) == Resumo(
        preco_min=Decimal("29.89"),
        preco_medio=Decimal("37.32"),
        preco_max=Decimal("49.90"),
        num_lojas=94,
    )


def test_produto_um_vendedor():
    assert parse_produto(fixture_liga("produto_um_vendedor")) == Resumo(
        preco_min=Decimal("2499.90"),
        preco_medio=Decimal("2499.90"),
        preco_max=Decimal("2499.90"),
        num_lojas=1,
    )


def test_produto_sem_estoque():
    # A página real sem lojas ainda mostra o quadro "Preço Médio de Venda no Marketplace"
    # (histórico, não depende de estoque atual); o parser devolve o que a página mostra.
    assert parse_produto(fixture_liga("produto_sem_estoque")) == Resumo(
        preco_min=Decimal("5450.00"),
        preco_medio=Decimal("5450.00"),
        preco_max=Decimal("5450.00"),
        num_lojas=0,
    )


def test_produto_sem_quadro_de_precos():
    html = '<html><body><div id="marketplace-stores"><div class="alertaErro">Nenhum item</div></div></body></html>'
    assert parse_produto(html) == Resumo(None, None, None, 0)


@pytest.mark.parametrize(
    "html",
    [
        "<html><body><p>layout novo</p></body></html>",
        # tem lojas na página, mas o contador "Lojas" sumiu
        '<html><body><div id="marketplace-stores"><div class="store"></div></div></body></html>',
        # quadro de preços sem um dos valores
        (
            '<html><body><div id="marketplace-stores"><div class="alertaErro">x</div></div>'
            '<div class="price-mkp"><div class="min"><div class="price">R$ 1,00</div></div></div></body></html>'
        ),
    ],
)
def test_produto_html_sem_estrutura(html):
    with pytest.raises(ErroParser):
        parse_produto(html)
```

Run: `uv run pytest tests/coletor_liga/test_parsers.py -v`
Expected (antes do parser): FAIL na coleta, `ImportError` (`Resumo`/`parsers` inexistentes).

- [x] **Step 4: Implementar** — `src/tcg_sniper/coletor_liga/parsers.py` (selectolax com backend lexbor; o backend `selectolax.parser` foi removido na 1.0):
```python
"""Parsers puros do HTML da LigaMagic, escritos a partir das fixtures reais em tests/fixtures/liga.

Página de produto (`?view=prod/view&pcode=N`), estrutura observada em 2026-10-13:

- `#marketplace-stores`: lista de ofertas das lojas; existe em toda página de produto e é o
  marcador de estrutura (ausente → `ErroParser`). Sem lojas, contém
  `<div class="alertaErro">… Nenhum item encontrado.</div>`.
- As ofertas individuais NÃO são lidas: preço e quantidade de cada `div.store` são desenhados
  dígito a dígito com sprite CSS (classes aleatórias + background-position), a loja é só um
  logotipo, e a página mostra 16 ofertas com um botão "Ver Mais" (JS) para o resto. Decisão do
  usuário em 2026-10-13: usar só o resumo textual.
- Quadro "Preço Médio de Venda no Marketplace" / "Preços aplicados no Marketplace":
  `.price-mkp .min .price`, `.price-mkp .medium .price`, `.price-mkp .max .price`
  (ex.: "R$ 29,89"). ATENÇÃO: é um indicador histórico do marketplace, não o menor preço
  pedido agora — a página sem nenhuma loja (pcode 276) ainda mostra R$ 5.450,00 nos três.
  Ausente → os três preços ficam `None`.
- Número de lojas: filtro "Vendedores" (`.group-filter` cujo `.filter-header .title` tem
  `data-label="Vendedores"`), opção `.filter-option` com `.filter-infos[title="Lojas"]`,
  contador em `.filter-counter` (ex.: 94 com só 16 linhas no HTML). Sem lojas, a página não
  tem nenhum `.group-filter` e `#marketplace-stores` tem `.alertaErro` → 0. Nenhum dos dois
  → `ErroParser`.
"""

import re
from decimal import Decimal

from selectolax.lexbor import LexborHTMLParser, LexborNode

from tcg_sniper.coletor_liga.modelos import ErroParser, Resumo

_RE_PRECO = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+),(\d{2})")
_RE_INTEIRO = re.compile(r"^\d+$")

SELETOR_ESTRUTURA_PRODUTO = "#marketplace-stores"
SELETOR_SEM_LOJAS = "#marketplace-stores .alertaErro"
SELETOR_QUADRO_PRECOS = ".price-mkp"
SELETORES_PRECO = (".min .price", ".medium .price", ".max .price")
SELETOR_GRUPO_FILTRO = ".group-filter"
SELETOR_TITULO_VENDEDORES = '.filter-header .title[data-label="Vendedores"]'
SELETOR_OPCAO_FILTRO = ".filter-option"
SELETOR_OPCAO_LOJAS = '.filter-infos[title="Lojas"]'
SELETOR_CONTADOR = ".filter-counter"


def parse_preco_brl(texto: str) -> Decimal:
    m = _RE_PRECO.search(texto.replace("\xa0", " "))
    if not m:
        raise ErroParser(f"preço inválido: {texto!r}")
    return Decimal(f"{m.group(1).replace('.', '')}.{m.group(2)}")


def _texto(no: LexborNode, seletor: str) -> str:
    alvo = no.css_first(seletor)
    if alvo is None:
        raise ErroParser(f"elemento {seletor!r} não encontrado")
    return alvo.text(strip=True)


def _num_lojas(arvore: LexborHTMLParser) -> int:
    for grupo in arvore.css(SELETOR_GRUPO_FILTRO):
        if grupo.css_first(SELETOR_TITULO_VENDEDORES) is None:
            continue
        for opcao in grupo.css(SELETOR_OPCAO_FILTRO):
            if opcao.css_first(SELETOR_OPCAO_LOJAS) is not None:
                contador = _texto(opcao, SELETOR_CONTADOR)
                if not _RE_INTEIRO.match(contador):
                    raise ErroParser(f"contador de lojas inválido: {contador!r}")
                return int(contador)
    if arvore.css_first(SELETOR_SEM_LOJAS) is not None:
        return 0
    raise ErroParser("contador de lojas não encontrado")


def parse_produto(html: str) -> Resumo:
    arvore = LexborHTMLParser(html)
    if arvore.css_first(SELETOR_ESTRUTURA_PRODUTO) is None:
        raise ErroParser("estrutura da página de produto não encontrada")
    quadro = arvore.css_first(SELETOR_QUADRO_PRECOS)
    if quadro is None:
        precos = (None, None, None)
    else:
        precos = tuple(
            parse_preco_brl(_texto(quadro, seletor)) for seletor in SELETORES_PRECO
        )
    preco_min, preco_medio, preco_max = precos
    return Resumo(
        preco_min=preco_min,
        preco_medio=preco_medio,
        preco_max=preco_max,
        num_lojas=_num_lojas(arvore),
    )
```

- [x] **Step 5: Rodar**

Run: `uv run pytest -q`
Expected: todos passam, inclusive `test_paginas_reais_nao_sao_desafio` para as fixtures de produto com o `<title>` real.

- [x] **Step 6: Commit** — `feat: summary-only LigaMagic product parser; drop per-offer model`

- [ ] **Step 7 (pendente de decisão): catálogo** — escolher a(s) URL(s) de listagem e como paginar sem clicar em "Exibir mais"; capturar `catalogo_pagina_1`/`catalogo_ultima_pagina`; implementar `parse_catalogo` (os cartões `div.card` trazem link `/?view=prod/view&pcode=<id>`, nome em `h5.card-title a`, preço "À partir de" em `.smallest-price` ou "Produto Indisponível" em `.price-out-of-stock`); gravar `LIGA_URL_CATALOGO`.

---

### Task 7: Coleta diária de preços

**Files:**
- Create: `src/tcg_sniper/coletor_liga/execucao.py`, `src/tcg_sniper/coletor_liga/precos.py`
- Test: `tests/coletor_liga/test_precos.py`

**Interfaces:**
- Consumes: `repositorio` (Task 3), `Notificador`/`Destino` (Task 4), `Navegador`, `eh_desafio` (Task 5), `parse_produto` (Task 6), fixtures `config`, `sessoes`.
- Produces:
  - `execucao`: `DesafioDetectado(Exception)`, `ResultadoColeta(coleta_id: int, status: StatusColeta, produtos_ok: int, produtos_falha: int, novos: int = 0)`, `pausa_humana(config, dormir) -> None`, `abrir_pagina(navegador, url, dormir) -> Pagina` (um retry em `ErroRede` após 30 s; lança `DesafioDetectado`), `mensagem_desafio(config, url) -> str`, `registrar_desafio(sessoes, notificador, config, coleta_id, url, ok, falha) -> None`, `salvar_html_falha(config, nome, html) -> Path`.
  - `precos.coletar_precos(sessoes, navegador, notificador, config, dormir=time.sleep, embaralhar=random.shuffle) -> ResultadoColeta | None` (`None` quando o coletor está pausado).

- [ ] **Step 1: Escrever os testes**

`tests/coletor_liga/test_precos.py`:
```python
from fakes import NavegadorFake, NotificadorFake, criar_produto, fixture_liga, pagina_html
from sqlalchemy import func, select

from tcg_sniper.coletor_liga.modelos import ErroRede
from tcg_sniper.coletor_liga.parsers import parse_produto
from tcg_sniper.coletor_liga.precos import coletar_precos
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import (
    Coleta,
    EstadoColetorTipo,
    PrecoAtualLiga,
    ResumoPreco,
    StatusColeta,
)
from tcg_sniper.notificador.base import Destino

HTML_OK = fixture_liga("produto_varios_vendedores")
HTML_QUEBRADO = "<html><body><p>layout novo</p></body></html>"
DESAFIO = pagina_html("<html></html>", titulo="Just a moment...")


def preparar(sessoes, *liga_ids):
    with sessoes() as s, s.begin():
        return {i: criar_produto(s, i).url for i in liga_ids}


def coletar(sessoes, config, paginas, pausas=None):
    navegador = NavegadorFake(paginas)
    notificador = NotificadorFake()
    resultado = coletar_precos(
        sessoes,
        navegador,
        notificador,
        config,
        dormir=(pausas if pausas is not None else []).append,
        embaralhar=lambda lista: None,
    )
    return resultado, navegador, notificador


def test_coleta_ok_grava_resumos_e_pausa_entre_produtos(sessoes, config):
    urls = preparar(sessoes, "a", "b", "c")
    pausas = []
    resultado, navegador, notificador = coletar(
        sessoes, config, {u: pagina_html(HTML_OK, url=u) for u in urls.values()}, pausas
    )

    assert resultado.status is StatusColeta.OK
    assert (resultado.produtos_ok, resultado.produtos_falha) == (3, 0)
    assert len(pausas) == 2 and all(8 <= p <= 20 for p in pausas)
    assert notificador.mensagens == []
    with sessoes() as s:
        assert s.scalar(select(func.count()).select_from(ResumoPreco)) == 3
        atuais = s.scalars(select(PrecoAtualLiga)).all()
        esperado = parse_produto(HTML_OK)
        assert len(atuais) == 3
        assert all((a.preco_min, a.num_lojas) == (esperado.preco_min, esperado.num_lojas) for a in atuais)
        coleta = s.get(Coleta, resultado.coleta_id)
        assert coleta.status is StatusColeta.OK and coleta.finalizada_em is not None


def test_desafio_pausa_coleta_avisa_admin_e_para(sessoes, config):
    urls = preparar(sessoes, "a", "b", "c")
    paginas = {urls["a"]: pagina_html(HTML_OK), urls["b"]: DESAFIO, urls["c"]: pagina_html(HTML_OK)}
    resultado, navegador, notificador = coletar(sessoes, config, paginas)

    assert resultado.status is StatusColeta.PAUSADA_DESAFIO
    assert navegador.visitadas == [urls["a"], urls["b"]]
    assert len(notificador.mensagens) == 1
    destino, texto = notificador.mensagens[0]
    assert destino is Destino.ADMIN
    assert "http://host.test:6080/vnc.html" in texto and "http://host.test:8000" in texto
    with sessoes() as s:
        assert repo.obter_estado(s).estado is EstadoColetorTipo.PAUSADO_DESAFIO
        assert s.get(Coleta, resultado.coleta_id).status is StatusColeta.PAUSADA_DESAFIO
        assert s.scalar(select(func.count()).select_from(PrecoAtualLiga)) == 1


def test_coletor_pausado_nao_executa(sessoes, config):
    urls = preparar(sessoes, "a")
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "x", repo.agora_utc())
    resultado, navegador, _ = coletar(sessoes, config, {urls["a"]: pagina_html(HTML_OK)})
    assert resultado is None
    assert navegador.visitadas == []
    with sessoes() as s:
        assert s.scalar(select(func.count()).select_from(Coleta)) == 0


def test_falha_de_parser_salva_html_e_status_parcial(sessoes, config):
    urls = preparar(sessoes, "a", "b", "c")
    paginas = {
        urls["a"]: pagina_html(HTML_OK),
        urls["b"]: pagina_html(HTML_QUEBRADO),
        urls["c"]: pagina_html(HTML_OK),
    }
    resultado, _, notificador = coletar(sessoes, config, paginas)
    assert resultado.status is StatusColeta.PARCIAL
    assert (resultado.produtos_ok, resultado.produtos_falha) == (2, 1)
    assert notificador.mensagens == []
    salvos = list((config.dir_dados / "falhas").glob("*.html"))
    assert len(salvos) == 1 and salvos[0].read_text(encoding="utf-8") == HTML_QUEBRADO


def test_mais_da_metade_falhando_avisa_layout(sessoes, config):
    urls = preparar(sessoes, "a", "b", "c")
    paginas = {
        urls["a"]: pagina_html(HTML_OK),
        urls["b"]: pagina_html(HTML_QUEBRADO),
        urls["c"]: pagina_html(HTML_QUEBRADO),
    }
    resultado, _, notificador = coletar(sessoes, config, paginas)
    assert resultado.status is StatusColeta.FALHA
    assert len(notificador.mensagens) == 1
    assert "layout" in notificador.mensagens[0][1]


def test_erro_de_rede_tenta_de_novo_uma_vez(sessoes, config):
    urls = preparar(sessoes, "a", "b")
    paginas = {
        urls["a"]: [ErroRede("timeout"), pagina_html(HTML_OK)],
        urls["b"]: [ErroRede("timeout"), ErroRede("timeout")],
    }
    pausas = []
    resultado, _, _ = coletar(sessoes, config, paginas, pausas)
    assert (resultado.produtos_ok, resultado.produtos_falha) == (1, 1)
    assert pausas.count(30) == 2


def test_erro_inesperado_fecha_coleta_como_falha(sessoes, config):
    urls = preparar(sessoes, "a")
    resultado, _, notificador = coletar(sessoes, config, {urls["a"]: RuntimeError("chromium morreu")})
    assert resultado.status is StatusColeta.FALHA
    assert len(notificador.mensagens) == 1
    with sessoes() as s:
        coleta = s.get(Coleta, resultado.coleta_id)
        assert coleta.status is StatusColeta.FALHA and "chromium morreu" in coleta.erro


def test_sem_produtos_ativos(sessoes, config):
    resultado, _, _ = coletar(sessoes, config, {})
    assert resultado.status is StatusColeta.OK
    assert (resultado.produtos_ok, resultado.produtos_falha) == (0, 0)
```

Run: `uv run pytest tests/coletor_liga/test_precos.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'tcg_sniper.coletor_liga.precos'`.

- [ ] **Step 2: Implementar `execucao.py`**

```python
"""Peças compartilhadas pela coleta de preços e pela varredura do catálogo."""

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.coletor_liga.desafio import eh_desafio
from tcg_sniper.coletor_liga.modelos import ErroRede, Pagina
from tcg_sniper.coletor_liga.navegador import Navegador
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import StatusColeta
from tcg_sniper.notificador.base import Destino, Notificador

log = logging.getLogger(__name__)

Dormir = Callable[[float], None]
ESPERA_RETRY_S = 30


class DesafioDetectado(Exception):
    pass


@dataclass(frozen=True)
class ResultadoColeta:
    coleta_id: int
    status: StatusColeta
    produtos_ok: int
    produtos_falha: int
    novos: int = 0


def pausa_humana(config: Config, dormir: Dormir) -> None:
    dormir(random.uniform(config.pausa_min_s, config.pausa_max_s))


def abrir_pagina(navegador: Navegador, url: str, dormir: Dormir) -> Pagina:
    try:
        pagina = navegador.abrir(url)
    except ErroRede as erro:
        log.warning("erro de rede em %s (%s); nova tentativa em %ss", url, erro, ESPERA_RETRY_S)
        dormir(ESPERA_RETRY_S)
        pagina = navegador.abrir(url)
    if eh_desafio(pagina):
        raise DesafioDetectado(url)
    return pagina


def mensagem_desafio(config: Config, url: str) -> str:
    return (
        f"Desafio Cloudflare na LigaMagic ({url}). "
        f"Resolver em http://{config.host_publico}:6080/vnc.html "
        f"e depois clicar em retomar em http://{config.host_publico}:8000"
    )


def registrar_desafio(
    sessoes: sessionmaker[Session],
    notificador: Notificador,
    config: Config,
    coleta_id: int,
    url: str,
    ok: int,
    falha: int,
) -> None:
    agora = repo.agora_utc()
    with sessoes() as s, s.begin():
        repo.finalizar_coleta(s, coleta_id, StatusColeta.PAUSADA_DESAFIO, ok, falha, agora, erro=f"desafio em {url}")
        repo.pausar_por_desafio(s, f"desafio em {url}", agora)
    log.warning("desafio do Cloudflare em %s; coletor pausado", url)
    notificador.enviar(Destino.ADMIN, mensagem_desafio(config, url))


def salvar_html_falha(config: Config, nome: str, html: str) -> Path:
    pasta = config.dir_dados / "falhas"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{nome}.html"
    caminho.write_text(html, encoding="utf-8")
    return caminho
```

- [ ] **Step 3: Implementar `precos.py`**

```python
import logging
import random
import time
from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.coletor_liga.execucao import (
    DesafioDetectado,
    Dormir,
    ResultadoColeta,
    abrir_pagina,
    pausa_humana,
    registrar_desafio,
    salvar_html_falha,
)
from tcg_sniper.coletor_liga.modelos import ErroParser, ErroRede
from tcg_sniper.coletor_liga.navegador import Navegador
from tcg_sniper.coletor_liga.parsers import parse_produto
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import EstadoColetorTipo, StatusColeta, TipoColeta
from tcg_sniper.notificador.base import Destino, Notificador

log = logging.getLogger(__name__)


def coletar_precos(
    sessoes: sessionmaker[Session],
    navegador: Navegador,
    notificador: Notificador,
    config: Config,
    dormir: Dormir = time.sleep,
    embaralhar: Callable[[list], None] = random.shuffle,
) -> ResultadoColeta | None:
    with sessoes() as s, s.begin():
        if repo.obter_estado(s).estado != EstadoColetorTipo.ATIVO:
            log.info("coletor pausado; coleta de preços não executada")
            return None
        coleta_id = repo.iniciar_coleta(s, TipoColeta.PRECOS, repo.agora_utc()).id
        produtos = [(p.id, p.url) for p in repo.produtos_ativos(s)]
    embaralhar(produtos)
    log.info("coleta de preços %s: %d produtos ativos", coleta_id, len(produtos))

    ok = falha = 0
    try:
        for indice, (produto_id, url) in enumerate(produtos):
            if indice > 0:
                pausa_humana(config, dormir)
            try:
                pagina = abrir_pagina(navegador, url, dormir)
            except DesafioDetectado:
                registrar_desafio(sessoes, notificador, config, coleta_id, url, ok, falha)
                return ResultadoColeta(coleta_id, StatusColeta.PAUSADA_DESAFIO, ok, falha)
            except ErroRede as erro:
                log.warning("produto %s falhou por rede: %s", produto_id, erro)
                falha += 1
                continue
            try:
                resumo = parse_produto(pagina.html)
            except ErroParser as erro:
                caminho = salvar_html_falha(config, f"precos-{coleta_id}-{produto_id}", pagina.html)
                log.warning("parser falhou no produto %s (%s); HTML em %s", produto_id, erro, caminho)
                falha += 1
                continue
            with sessoes() as s, s.begin():
                repo.gravar_precos_produto(s, coleta_id, produto_id, resumo, repo.agora_utc())
            ok += 1
    except Exception as erro:
        log.exception("erro inesperado na coleta de preços %s", coleta_id)
        with sessoes() as s, s.begin():
            repo.finalizar_coleta(s, coleta_id, StatusColeta.FALHA, ok, falha, repo.agora_utc(), erro=repr(erro))
        notificador.enviar(Destino.ADMIN, f"Coleta de preços {coleta_id} interrompida por erro inesperado: {erro!r}")
        return ResultadoColeta(coleta_id, StatusColeta.FALHA, ok, falha)

    status = repo.status_final(ok, falha, config.limite_falha_pct)
    with sessoes() as s, s.begin():
        repo.finalizar_coleta(s, coleta_id, status, ok, falha, repo.agora_utc())
    log.info("coleta de preços %s terminou: %s (%d ok, %d falhas)", coleta_id, status.value, ok, falha)
    if status is StatusColeta.FALHA:
        notificador.enviar(
            Destino.ADMIN,
            f"Coleta de preços {coleta_id} falhou em {falha} de {ok + falha} produtos. "
            f"O layout da LigaMagic pode ter mudado. HTMLs em {config.dir_dados / 'falhas'}.",
        )
    return ResultadoColeta(coleta_id, status, ok, falha)
```

- [ ] **Step 4: Rodar**

Run: `uv run pytest tests/coletor_liga/test_precos.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tcg_sniper/coletor_liga/execucao.py src/tcg_sniper/coletor_liga/precos.py tests/coletor_liga/test_precos.py
git commit -m "feat: daily price collection with challenge pause and failure handling"
```

---

### Task 8: Varredura do catálogo

> **Bloqueada (2026-10-13):** depende do Step 7 da Task 6 (listagem do catálogo sem link de próxima página; itens extras via JavaScript "Exibir mais"). O desenho abaixo (`proxima_url`) pode mudar.

**Files:**
- Create: `src/tcg_sniper/coletor_liga/catalogo.py`
- Test: `tests/coletor_liga/test_catalogo.py`

**Interfaces:**
- Consumes: `execucao` (Task 7), `parse_catalogo` (Task 6), `repo.upsert_catalogo` (Task 3).
- Produces: `catalogo.varrer_catalogo(sessoes, navegador, notificador, config, dormir=time.sleep, max_paginas: int = 100) -> ResultadoColeta | None` (`None` se pausado; `ResultadoColeta.novos` = produtos novos; `produtos_ok` = itens lidos).

- [ ] **Step 1: Escrever os testes**

`tests/coletor_liga/test_catalogo.py`:
```python
from fakes import NavegadorFake, NotificadorFake, fixture_liga, pagina_html
from sqlalchemy import func, select

from tcg_sniper.coletor_liga.catalogo import varrer_catalogo
from tcg_sniper.coletor_liga.parsers import parse_catalogo
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import Coleta, EstadoColetorTipo, ProdutoLiga, StatusColeta

HTML_P1 = fixture_liga("catalogo_pagina_1")
HTML_ULTIMA = fixture_liga("catalogo_ultima_pagina")
URL_INICIAL = "https://liga.test/selados"


def varrer(sessoes, config, paginas, pausas=None):
    navegador = NavegadorFake(paginas)
    notificador = NotificadorFake()
    resultado = varrer_catalogo(
        sessoes, navegador, notificador, config, dormir=(pausas if pausas is not None else []).append
    )
    return resultado, navegador, notificador


def duas_paginas():
    proxima = parse_catalogo(HTML_P1, URL_INICIAL).proxima_url
    return proxima, {
        URL_INICIAL: pagina_html(HTML_P1, url=URL_INICIAL),
        proxima: pagina_html(HTML_ULTIMA, url=proxima),
    }


def test_varre_todas_as_paginas_e_avisa_novos(sessoes, config):
    proxima, paginas = duas_paginas()
    pausas = []
    resultado, navegador, notificador = varrer(sessoes, config, paginas, pausas)

    itens = parse_catalogo(HTML_P1, URL_INICIAL).itens + parse_catalogo(HTML_ULTIMA, proxima).itens
    unicos = {i.liga_id for i in itens}
    assert navegador.visitadas == [URL_INICIAL, proxima]
    assert len(pausas) == 1
    assert resultado.status is StatusColeta.OK
    assert resultado.novos == len(unicos)
    with sessoes() as s:
        assert s.scalar(select(func.count()).select_from(ProdutoLiga)) == len(unicos)
        assert s.scalar(select(func.count()).select_from(ProdutoLiga).where(ProdutoLiga.ativo)) == 0
    assert len(notificador.mensagens) == 1
    assert f"{len(unicos)} produtos novos" in notificador.mensagens[0][1]


def test_segunda_varredura_nao_avisa(sessoes, config):
    _, paginas = duas_paginas()
    varrer(sessoes, config, paginas)
    _, paginas = duas_paginas()
    resultado, _, notificador = varrer(sessoes, config, paginas)
    assert resultado.novos == 0
    assert notificador.mensagens == []


def test_desafio_na_segunda_pagina(sessoes, config):
    proxima, paginas = duas_paginas()
    paginas[proxima] = pagina_html("<html></html>", titulo="Just a moment...")
    resultado, _, notificador = varrer(sessoes, config, paginas)
    assert resultado.status is StatusColeta.PAUSADA_DESAFIO
    assert "6080" in notificador.mensagens[-1][1]
    with sessoes() as s:
        assert repo.obter_estado(s).estado is EstadoColetorTipo.PAUSADO_DESAFIO


def test_layout_quebrado_falha_e_avisa(sessoes, config):
    paginas = {URL_INICIAL: pagina_html("<html><body>novo</body></html>", url=URL_INICIAL)}
    resultado, _, notificador = varrer(sessoes, config, paginas)
    assert resultado.status is StatusColeta.FALHA
    assert "catálogo" in notificador.mensagens[0][1]
    assert list((config.dir_dados / "falhas").glob("catalogo-*.html"))


def test_limite_de_paginas(sessoes, config):
    """Proteção contra paginação em loop: para no limite e marca falha."""
    paginas = {URL_INICIAL: pagina_html(HTML_P1, url=URL_INICIAL)}
    proxima = parse_catalogo(HTML_P1, URL_INICIAL).proxima_url
    paginas[proxima] = pagina_html(HTML_P1, url=proxima)
    navegador = NavegadorFake(paginas)
    resultado = varrer_catalogo(sessoes, navegador, NotificadorFake(), config, dormir=lambda _: None, max_paginas=2)
    assert len(navegador.visitadas) == 2
    assert resultado.status is StatusColeta.FALHA
    with sessoes() as s:
        assert "limite" in s.get(Coleta, resultado.coleta_id).erro
```

Run: `uv run pytest tests/coletor_liga/test_catalogo.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'tcg_sniper.coletor_liga.catalogo'`.

Nota: `test_limite_de_paginas` assume que a `proxima_url` da página 1 aponta para uma URL diferente de `URL_INICIAL`; com o fake, a "página 2" devolve o mesmo HTML e portanto aponta de novo para `proxima`, simulando um loop.

- [ ] **Step 2: Implementar `catalogo.py`**

```python
import logging
import time

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.coletor_liga.execucao import (
    DesafioDetectado,
    Dormir,
    ResultadoColeta,
    abrir_pagina,
    pausa_humana,
    registrar_desafio,
    salvar_html_falha,
)
from tcg_sniper.coletor_liga.modelos import ErroParser, ErroRede
from tcg_sniper.coletor_liga.navegador import Navegador
from tcg_sniper.coletor_liga.parsers import parse_catalogo
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import EstadoColetorTipo, StatusColeta, TipoColeta
from tcg_sniper.notificador.base import Destino, Notificador

log = logging.getLogger(__name__)


def varrer_catalogo(
    sessoes: sessionmaker[Session],
    navegador: Navegador,
    notificador: Notificador,
    config: Config,
    dormir: Dormir = time.sleep,
    max_paginas: int = 100,
) -> ResultadoColeta | None:
    if not config.liga_url_catalogo:
        raise ValueError("LIGA_URL_CATALOGO não configurada")
    with sessoes() as s, s.begin():
        if repo.obter_estado(s).estado != EstadoColetorTipo.ATIVO:
            log.info("coletor pausado; varredura do catálogo não executada")
            return None
        coleta_id = repo.iniciar_coleta(s, TipoColeta.CATALOGO, repo.agora_utc()).id

    url: str | None = config.liga_url_catalogo
    paginas = itens = novos = 0
    erro: str | None = None
    try:
        while url:
            if paginas >= max_paginas:
                erro = f"limite de {max_paginas} páginas atingido em {url}"
                break
            if paginas > 0:
                pausa_humana(config, dormir)
            pagina = abrir_pagina(navegador, url, dormir)
            try:
                resultado = parse_catalogo(pagina.html, pagina.url)
            except ErroParser:
                salvar_html_falha(config, f"catalogo-{coleta_id}-{paginas + 1}", pagina.html)
                raise
            with sessoes() as s, s.begin():
                novos += repo.upsert_catalogo(s, resultado.itens, repo.agora_utc())
            itens += len(resultado.itens)
            paginas += 1
            url = resultado.proxima_url
    except DesafioDetectado:
        registrar_desafio(sessoes, notificador, config, coleta_id, url or "", itens, 0)
        return ResultadoColeta(coleta_id, StatusColeta.PAUSADA_DESAFIO, itens, 0, novos)
    except (ErroParser, ErroRede) as e:
        erro = f"página {paginas + 1} ({url}): {e}"
    except Exception as e:
        log.exception("erro inesperado na varredura %s", coleta_id)
        erro = f"erro inesperado: {e!r}"

    status = StatusColeta.FALHA if erro else StatusColeta.OK
    with sessoes() as s, s.begin():
        repo.finalizar_coleta(s, coleta_id, status, itens, 1 if erro else 0, repo.agora_utc(), erro=erro)
    log.info("varredura %s terminou: %s, %d páginas, %d itens, %d novos", coleta_id, status.value, paginas, itens, novos)
    if erro:
        notificador.enviar(Destino.ADMIN, f"Varredura do catálogo {coleta_id} falhou: {erro}")
    if novos:
        notificador.enviar(
            Destino.ADMIN,
            f"{novos} produtos novos no catálogo. Ativar em http://{config.host_publico}:8000/catalogo?filtro=novos",
        )
    return ResultadoColeta(coleta_id, status, itens, 1 if erro else 0, novos)
```

- [ ] **Step 3: Rodar**

Run: `uv run pytest tests/coletor_liga/test_catalogo.py -v`
Expected: 5 passed.

- [ ] **Step 4: Commit**

```bash
git add src/tcg_sniper/coletor_liga/catalogo.py tests/coletor_liga/test_catalogo.py
git commit -m "feat: weekly catalog sweep with new product alert"
```

---

### Task 9: Agendador

O APScheduler da spec é trocado por um laço simples de 60 s: a API síncrona do Playwright é presa à thread que a criou, e os pools de thread do APScheduler quebrariam isso. O laço roda tudo na thread principal, o que também serializa as coletas dentro do processo; o advisory lock cobre o caso de dois containers.

**Files:**
- Create: `src/tcg_sniper/coletor_liga/agendador.py`
- Test: `tests/coletor_liga/test_agendador.py`

**Interfaces:**
- Consumes: `coletar_precos` (Task 7), `varrer_catalogo` (Task 8), `pausa_humana` (Task 7), repositório (Task 3).
- Produces:
  - `alvo_do_dia(dia: date, hora: time, jitter_min: int, fuso: ZoneInfo, rng: random.Random) -> datetime`.
  - `lock_coleta(engine) -> ContextManager[bool]`.
  - `Agendador(engine, sessoes, fabrica_navegador: Callable[[], ContextManager[Navegador]], notificador, config, relogio=None, rng=None, dormir=time.sleep, executor: Callable[[bool], None] | None = None)` com `inicializar() -> None`, `tick() -> str | None` (devolve `"solicitado"`, `"atrasado"`, `"agendado"` ou `None`), `executar_job(incluir_catalogo: bool) -> None`, `rodar() -> None` (laço infinito).

Regras do `tick`:
1. Estado `pausado_desafio`: não faz nada.
2. Execução solicitada pelo admin: roda só preços (`incluir_catalogo=False`).
3. Execução atrasada (definida no `inicializar` quando a última coleta de preços com sucesso tem mais de 24 h ou não existe) e já chegou a hora: roda.
4. Ainda não houve coleta de preços iniciada hoje (fuso local), não houve tentativa agendada hoje e já passou o alvo do dia: roda.
5. `incluir_catalogo` é verdadeiro no dia configurado (domingo) ou quando a última varredura com sucesso tem mais de 7 dias ou não existe.
6. Exceção no job: registra em log, avisa o admin e não tenta de novo no mesmo dia.

- [ ] **Step 1: Escrever os testes**

`tests/coletor_liga/test_agendador.py`:
```python
import random
from contextlib import nullcontext
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fakes import NavegadorFake, NotificadorFake, fixture_liga, pagina_html
from sqlalchemy import select

from tcg_sniper.coletor_liga.agendador import Agendador, alvo_do_dia, lock_coleta
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import Coleta, StatusColeta, TipoColeta

SP = ZoneInfo("America/Sao_Paulo")
TERCA = date(2026, 10, 13)
DOMINGO = date(2026, 10, 18)


def local(dia, h, m=0):
    return datetime.combine(dia, time(h, m), tzinfo=SP)


class Relogio:
    def __init__(self, agora):
        self.agora = agora

    def __call__(self):
        return self.agora


def coleta(sessoes, tipo, quando, status=StatusColeta.OK):
    with sessoes() as s, s.begin():
        c = repo.iniciar_coleta(s, tipo, quando)
        if status is not StatusColeta.RODANDO:
            repo.finalizar_coleta(s, c.id, status, 1, 0, quando)


def agendador(engine, sessoes, config, relogio, chamadas, falhar=False):
    def executor(incluir_catalogo):
        chamadas.append(incluir_catalogo)
        if falhar:
            raise RuntimeError("chromium não abriu")

    notificador = NotificadorFake()
    a = Agendador(
        engine, sessoes, lambda: nullcontext(NavegadorFake({})), notificador, config,
        relogio=relogio, rng=random.Random(42), dormir=lambda _: None, executor=executor,
    )
    return a, notificador


def test_alvo_do_dia_respeita_jitter():
    rng = random.Random(1)
    for _ in range(200):
        alvo = alvo_do_dia(TERCA, time(10, 0), 30, SP, rng)
        assert local(TERCA, 9, 30) <= alvo <= local(TERCA, 10, 30)


def test_lock_coleta_exclusivo(engine):
    with lock_coleta(engine) as primeiro:
        assert primeiro is True
        with lock_coleta(engine) as segundo:
            assert segundo is False
    with lock_coleta(engine) as de_novo:
        assert de_novo is True


def test_primeira_execucao_roda_atrasada_com_catalogo(engine, sessoes, config):
    relogio = Relogio(local(TERCA, 8, 0))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    relogio.agora += timedelta(minutes=31)
    assert a.tick() == "atrasado"
    assert chamadas == [True]


def test_agendado_roda_uma_vez_no_dia(engine, sessoes, config):
    coleta(sessoes, TipoColeta.PRECOS, local(TERCA - timedelta(days=1), 14))
    coleta(sessoes, TipoColeta.CATALOGO, local(TERCA - timedelta(days=2), 10))
    relogio = Relogio(local(TERCA, 9, 29))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() is None
    relogio.agora = local(TERCA, 10, 31)
    assert a.tick() == "agendado"
    relogio.agora = local(TERCA, 10, 45)
    assert a.tick() is None
    assert chamadas == [False]


def test_restart_depois_de_ja_ter_rodado_hoje_nao_roda_de_novo(engine, sessoes, config):
    coleta(sessoes, TipoColeta.CATALOGO, local(TERCA - timedelta(days=2), 10))
    coleta(sessoes, TipoColeta.PRECOS, local(TERCA, 10, 5))
    relogio = Relogio(local(TERCA, 11, 0))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() is None
    assert chamadas == []


def test_restart_sem_coleta_hoje_e_horario_passado_roda(engine, sessoes, config):
    coleta(sessoes, TipoColeta.CATALOGO, local(TERCA - timedelta(days=2), 10))
    coleta(sessoes, TipoColeta.PRECOS, local(TERCA - timedelta(days=1), 14))
    relogio = Relogio(local(TERCA, 10, 45))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() == "agendado"


def test_domingo_inclui_catalogo(engine, sessoes, config):
    coleta(sessoes, TipoColeta.CATALOGO, local(DOMINGO - timedelta(days=1), 10))
    coleta(sessoes, TipoColeta.PRECOS, local(DOMINGO - timedelta(days=1), 10))
    relogio = Relogio(local(DOMINGO, 10, 31))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() == "agendado"
    assert chamadas == [True]


def test_pausado_nao_roda(engine, sessoes, config):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "x", local(TERCA, 8))
    relogio = Relogio(local(TERCA, 15))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() is None
    assert chamadas == []


def test_solicitacao_do_admin_roda_so_precos(engine, sessoes, config):
    coleta(sessoes, TipoColeta.PRECOS, local(TERCA, 10, 5))
    with sessoes() as s, s.begin():
        repo.retomar(s, local(TERCA, 11))
    relogio = Relogio(local(TERCA, 11, 1))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() == "solicitado"
    assert chamadas == [False]


def test_inicializar_marca_interrompidas(engine, sessoes, config):
    coleta(sessoes, TipoColeta.PRECOS, local(TERCA, 10), status=StatusColeta.RODANDO)
    a, _ = agendador(engine, sessoes, config, Relogio(local(TERCA, 12)), [])
    a.inicializar()
    with sessoes() as s:
        assert s.scalars(select(Coleta.status)).one() is StatusColeta.FALHA


def test_excecao_no_job_avisa_e_nao_repete_no_dia(engine, sessoes, config):
    coleta(sessoes, TipoColeta.CATALOGO, local(TERCA - timedelta(days=2), 10))
    coleta(sessoes, TipoColeta.PRECOS, local(TERCA - timedelta(days=1), 14))
    relogio = Relogio(local(TERCA, 10, 31))
    chamadas = []
    a, notificador = agendador(engine, sessoes, config, relogio, chamadas, falhar=True)
    a.inicializar()
    assert a.tick() == "agendado"
    relogio.agora += timedelta(minutes=1)
    assert a.tick() is None
    assert chamadas == [False]
    assert "chromium não abriu" in notificador.mensagens[0][1]


def test_executar_job_varre_catalogo_e_depois_precos(engine, sessoes, config):
    paginas = {config.liga_url_catalogo: pagina_html(fixture_liga("catalogo_ultima_pagina"), url=config.liga_url_catalogo)}
    navegador = NavegadorFake(paginas)
    a = Agendador(
        engine, sessoes, lambda: nullcontext(navegador), NotificadorFake(), config,
        relogio=Relogio(datetime.now(UTC)), rng=random.Random(1), dormir=lambda _: None,
    )
    a.executar_job(incluir_catalogo=True)
    assert navegador.visitadas == [config.liga_url_catalogo]
    with sessoes() as s:
        tipos = [c.tipo for c in s.scalars(select(Coleta).order_by(Coleta.id))]
    assert tipos == [TipoColeta.CATALOGO, TipoColeta.PRECOS]


def test_executar_job_respeita_lock(engine, sessoes, config):
    navegador = NavegadorFake({})
    a = Agendador(
        engine, sessoes, lambda: nullcontext(navegador), NotificadorFake(), config,
        relogio=Relogio(datetime.now(UTC)), dormir=lambda _: None,
    )
    with lock_coleta(engine):
        a.executar_job(incluir_catalogo=False)
    with sessoes() as s:
        assert s.scalars(select(Coleta)).all() == []
```

Run: `uv run pytest tests/coletor_liga/test_agendador.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'tcg_sniper.coletor_liga.agendador'`.

- [ ] **Step 2: Implementar `agendador.py`**

```python
import logging
import random
import time as relogio_sistema
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.coletor_liga.catalogo import varrer_catalogo
from tcg_sniper.coletor_liga.execucao import pausa_humana
from tcg_sniper.coletor_liga.navegador import Navegador
from tcg_sniper.coletor_liga.precos import coletar_precos
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import EstadoColetorTipo, StatusColeta, TipoColeta
from tcg_sniper.notificador.base import Destino, Notificador

log = logging.getLogger(__name__)

ID_LOCK = 7_202_610
INTERVALO_TICK_S = 60


def alvo_do_dia(dia: date, hora: time, jitter_min: int, fuso: ZoneInfo, rng: random.Random) -> datetime:
    base = datetime.combine(dia, hora, tzinfo=fuso)
    return base + timedelta(minutes=rng.uniform(-jitter_min, jitter_min))


@contextmanager
def lock_coleta(engine: Engine) -> Iterator[bool]:
    with engine.connect() as conexao:
        obtido = bool(conexao.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": ID_LOCK}).scalar_one())
        try:
            yield obtido
        finally:
            if obtido:
                conexao.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": ID_LOCK})


class Agendador:
    def __init__(
        self,
        engine: Engine,
        sessoes: sessionmaker[Session],
        fabrica_navegador: Callable[[], AbstractContextManager[Navegador]],
        notificador: Notificador,
        config: Config,
        relogio: Callable[[], datetime] | None = None,
        rng: random.Random | None = None,
        dormir: Callable[[float], None] = relogio_sistema.sleep,
        executor: Callable[[bool], None] | None = None,
    ):
        self._engine = engine
        self._sessoes = sessoes
        self._fabrica_navegador = fabrica_navegador
        self._notificador = notificador
        self._config = config
        self._relogio = relogio or (lambda: datetime.now(UTC))
        self._rng = rng or random.Random()
        self._dormir = dormir
        self._executor = executor or self.executar_job
        self._alvos: dict[date, datetime] = {}
        self._datas_tentadas: set[date] = set()
        self._atrasada_em: datetime | None = None

    def inicializar(self) -> None:
        agora = self._relogio()
        with self._sessoes() as s, s.begin():
            interrompidas = repo.marcar_interrompidas(s, agora)
            ultima = repo.ultima_coleta_sucesso(s, TipoColeta.PRECOS)
        if interrompidas:
            log.warning("%d coleta(s) interrompida(s) marcadas como falha", interrompidas)
        if ultima is None or agora - ultima > timedelta(hours=24):
            self._atrasada_em = agora + timedelta(minutes=self._rng.uniform(0, self._config.coleta_jitter_min))
            log.info("última coleta de preços com sucesso: %s; execução atrasada em %s", ultima, self._atrasada_em)

    def tick(self) -> str | None:
        agora = self._relogio()
        hoje = agora.astimezone(self._config.zona).date()
        inicio_do_dia = datetime.combine(hoje, time(0), tzinfo=self._config.zona)
        with self._sessoes() as s, s.begin():
            if repo.obter_estado(s, agora).estado != EstadoColetorTipo.ATIVO:
                return None
            solicitada = repo.consumir_solicitacao(s, agora)
            rodou_hoje = repo.coleta_iniciada_desde(s, TipoColeta.PRECOS, inicio_do_dia)
            ultimo_catalogo = repo.ultima_coleta_sucesso(s, TipoColeta.CATALOGO)

        incluir_catalogo = (
            hoje.weekday() == self._config.catalogo_weekday
            or ultimo_catalogo is None
            or agora - ultimo_catalogo > timedelta(days=7)
        )
        if solicitada:
            return self._executar("solicitado", False, hoje)
        if self._atrasada_em is not None and agora >= self._atrasada_em:
            self._atrasada_em = None
            return self._executar("atrasado", incluir_catalogo, hoje)
        alvo = self._alvos.setdefault(
            hoje,
            alvo_do_dia(hoje, self._config.coleta_hora, self._config.coleta_jitter_min, self._config.zona, self._rng),
        )
        if not rodou_hoje and hoje not in self._datas_tentadas and agora >= alvo:
            return self._executar("agendado", incluir_catalogo, hoje)
        return None

    def _executar(self, motivo: str, incluir_catalogo: bool, hoje: date) -> str:
        self._datas_tentadas.add(hoje)
        log.info("iniciando job (%s, catálogo=%s)", motivo, incluir_catalogo)
        try:
            self._executor(incluir_catalogo)
        except Exception as erro:
            log.exception("job %s falhou", motivo)
            self._notificador.enviar(Destino.ADMIN, f"Erro inesperado no coletor ({motivo}): {erro!r}")
        return motivo

    def executar_job(self, incluir_catalogo: bool) -> None:
        with lock_coleta(self._engine) as obtido:
            if not obtido:
                log.warning("outra coleta em andamento; job ignorado")
                return
            with self._fabrica_navegador() as navegador:
                if incluir_catalogo:
                    resultado = varrer_catalogo(
                        self._sessoes, navegador, self._notificador, self._config, self._dormir
                    )
                    if resultado is not None and resultado.status is StatusColeta.PAUSADA_DESAFIO:
                        return
                    pausa_humana(self._config, self._dormir)
                coletar_precos(self._sessoes, navegador, self._notificador, self._config, self._dormir)

    def rodar(self) -> None:
        self.inicializar()
        log.info("agendador iniciado")
        while True:
            self.tick()
            self._dormir(INTERVALO_TICK_S)
```

- [ ] **Step 3: Rodar**

Run: `uv run pytest tests/coletor_liga/test_agendador.py -v`
Expected: 13 passed.

- [ ] **Step 4: Rodar a suíte inteira**

Run: `uv run pytest -v`
Expected: todos passam.

- [ ] **Step 5: Commit**

```bash
git add src/tcg_sniper/coletor_liga/agendador.py tests/coletor_liga/test_agendador.py
git commit -m "feat: scheduler loop with daily jitter, catch-up, admin requests and advisory lock"
```

---

### Task 10: Página de admin

**Files:**
- Create: `src/tcg_sniper/admin/__init__.py`, `src/tcg_sniper/admin/consultas.py`, `src/tcg_sniper/admin/app.py`
- Create: `src/tcg_sniper/admin/templates/base.html`, `index.html`, `catalogo.html`, `_linha_produto.html`, `produto.html`
- Test: `tests/admin/test_admin.py`

**Interfaces:**
- Consumes: modelos (Task 2), `repo.obter_estado`, `repo.retomar`, `repo.solicitar_execucao`, `repo.agora_utc` (Task 3).
- Produces:
  - `consultas`: `FILTROS = ("todos", "ativos", "inativos", "novos")`, `listar_coletas(s, limite=10) -> list[Coleta]`, `buscar_catalogo(s, busca: str | None, filtro: str, agora: datetime, limite=500) -> list[tuple[ProdutoLiga, PrecoAtualLiga | None]]`, `alternar_ativo(s, produto_id) -> tuple[ProdutoLiga, PrecoAtualLiga | None] | None`, `detalhe_produto(s, produto_id) -> tuple[ProdutoLiga, PrecoAtualLiga | None, list[ResumoPreco]] | None`.
  - `app`: `criar_app(sessoes, config) -> FastAPI`, `formatar_brl(valor: Decimal | None) -> str`, `formatar_data(dt: datetime | None, zona: ZoneInfo) -> str`.

- [ ] **Step 1: Escrever os testes**

`tests/admin/test_admin.py`:
```python
import base64
from datetime import timedelta
from decimal import Decimal

import pytest
from fakes import T0, criar_produto
from fastapi.testclient import TestClient

from tcg_sniper.admin.app import criar_app, formatar_brl
from tcg_sniper.coletor_liga.modelos import Resumo
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import EstadoColetorTipo, ProdutoLiga, TipoColeta


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def test_formatar_brl():
    assert formatar_brl(Decimal("1234.5")) == "R$ 1.234,50"
    assert formatar_brl(Decimal("0.99")) == "R$ 0,99"
    assert formatar_brl(None) == "—"


def test_sem_senha_401(sessoes, config):
    assert TestClient(criar_app(sessoes, config)).get("/").status_code == 401


def test_senha_errada_401(sessoes, config):
    c = TestClient(criar_app(sessoes, config), headers={"Authorization": basic("admin", "errada")})
    assert c.get("/").status_code == 401


def test_index_mostra_estado_e_coletas(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.iniciar_coleta(s, TipoColeta.PRECOS, T0)
    r = cliente.get("/")
    assert r.status_code == 200
    assert "Rodar agora" in r.text
    assert "precos" in r.text


def test_index_pausado_mostra_retomar(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em /x", T0)
    r = cliente.get("/")
    assert "Retomar" in r.text and "desafio em /x" in r.text and "host.test:6080" in r.text


def test_retomar(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "x", T0)
    r = cliente.post("/retomar", follow_redirects=False)
    assert r.status_code == 303
    with sessoes() as s:
        estado = repo.obter_estado(s)
        assert estado.estado is EstadoColetorTipo.ATIVO and estado.execucao_solicitada


def test_rodar_agora(cliente, sessoes):
    assert cliente.post("/rodar-agora", follow_redirects=False).status_code == 303
    with sessoes() as s:
        assert repo.obter_estado(s).execucao_solicitada


def test_busca_trata_curingas_literalmente(cliente, sessoes):
    with sessoes() as s, s.begin():
        criar_produto(s, "a", nome="Caixa 100% Foil")
        criar_produto(s, "b", nome="Caixa 1000 boosters")
        criar_produto(s, "c", nome="Bundle_Especial")
        criar_produto(s, "d", nome="Bundle Especial")
    r = cliente.get("/catalogo", params={"busca": "100%"})
    assert "Caixa 100% Foil" in r.text and "Caixa 1000 boosters" not in r.text
    r = cliente.get("/catalogo", params={"busca": "Bundle_"})
    assert "Bundle_Especial" in r.text and "Bundle Especial" not in r.text  # "_" não é curinga


def test_filtros(cliente, sessoes):
    agora = repo.agora_utc()
    with sessoes() as s, s.begin():
        criar_produto(s, "a", nome="Ativo antigo", ativo=True, agora=agora - timedelta(days=30))
        criar_produto(s, "b", nome="Inativo novo", ativo=False, agora=agora - timedelta(days=1))
    assert "Ativo antigo" in cliente.get("/catalogo?filtro=ativos").text
    assert "Inativo novo" not in cliente.get("/catalogo?filtro=ativos").text
    assert "Inativo novo" in cliente.get("/catalogo?filtro=inativos").text
    novos = cliente.get("/catalogo?filtro=novos").text
    assert "Inativo novo" in novos and "Ativo antigo" not in novos


def test_filtro_invalido_400(cliente):
    assert cliente.get("/catalogo?filtro=xyz").status_code == 400


def test_toggle_ativo(cliente, sessoes):
    with sessoes() as s, s.begin():
        produto_id = criar_produto(s, "a", ativo=False).id
    r = cliente.post(f"/produto/{produto_id}/ativo")
    assert r.status_code == 200
    assert f'id="produto-{produto_id}"' in r.text and "Ativo" in r.text
    with sessoes() as s:
        assert s.get(ProdutoLiga, produto_id).ativo is True


def test_toggle_inexistente_404(cliente):
    assert cliente.post("/produto/999999/ativo").status_code == 404


def test_detalhe_produto_mostra_preco_e_historico(cliente, sessoes):
    with sessoes() as s, s.begin():
        produto = criar_produto(s, "a", nome="Caixa Duskmourn")
        resumo = Resumo(Decimal("1234.56"), Decimal("1500.00"), Decimal("1999.90"), 7)
        c = repo.iniciar_coleta(s, TipoColeta.PRECOS, T0)
        repo.gravar_precos_produto(s, c.id, produto.id, resumo, T0)
    r = cliente.get(f"/produto/{produto.id}")
    assert r.status_code == 200
    assert "Caixa Duskmourn" in r.text
    for texto in ("Mín", "Médio", "Máx", "Lojas", "R$ 1.234,56", "R$ 1.500,00", "R$ 1.999,90", "<td>7</td>"):
        assert texto in r.text


def test_detalhe_inexistente_404(cliente):
    assert cliente.get("/produto/999999").status_code == 404


def test_catalogo_mostra_preco_min_e_lojas(cliente, sessoes):
    with sessoes() as s, s.begin():
        produto = criar_produto(s, "a", nome="Caixa Duskmourn")
        c = repo.iniciar_coleta(s, TipoColeta.PRECOS, T0)
        repo.gravar_precos_produto(s, c.id, produto.id, Resumo(Decimal("899.90"), None, None, 12), T0)
    r = cliente.get("/catalogo")
    assert "<th>Mín</th>" in r.text and "<th>Lojas</th>" in r.text
    assert "R$ 899,90" in r.text and "<td>12</td>" in r.text
```

Run: `uv run pytest tests/admin -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'tcg_sniper.admin'`.

- [ ] **Step 2: Implementar `consultas.py`**

`src/tcg_sniper/admin/__init__.py`: arquivo vazio.

`src/tcg_sniper/admin/consultas.py`:
```python
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcg_sniper.db.models import Coleta, PrecoAtualLiga, ProdutoLiga, ResumoPreco

FILTROS = ("todos", "ativos", "inativos", "novos")
JANELA_NOVOS = timedelta(days=7)


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def listar_coletas(s: Session, limite: int = 10) -> list[Coleta]:
    return list(s.scalars(select(Coleta).order_by(Coleta.id.desc()).limit(limite)))


def buscar_catalogo(
    s: Session, busca: str | None, filtro: str, agora: datetime, limite: int = 500
) -> list[tuple[ProdutoLiga, PrecoAtualLiga | None]]:
    consulta = select(ProdutoLiga, PrecoAtualLiga).outerjoin(
        PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id
    )
    if busca and busca.strip():
        consulta = consulta.where(ProdutoLiga.nome.ilike(f"%{_escapar_like(busca.strip())}%", escape="\\"))
    if filtro == "ativos":
        consulta = consulta.where(ProdutoLiga.ativo.is_(True))
    elif filtro == "inativos":
        consulta = consulta.where(ProdutoLiga.ativo.is_(False))
    elif filtro == "novos":
        consulta = consulta.where(ProdutoLiga.visto_primeiro_em >= agora - JANELA_NOVOS)
    consulta = consulta.order_by(ProdutoLiga.ativo.desc(), ProdutoLiga.nome).limit(limite)
    return [(produto, atual) for produto, atual in s.execute(consulta)]


def alternar_ativo(s: Session, produto_id: int) -> tuple[ProdutoLiga, PrecoAtualLiga | None] | None:
    produto = s.get(ProdutoLiga, produto_id)
    if produto is None:
        return None
    produto.ativo = not produto.ativo
    s.flush()
    return produto, s.get(PrecoAtualLiga, produto_id)


def detalhe_produto(
    s: Session, produto_id: int, limite_historico: int = 90
) -> tuple[ProdutoLiga, PrecoAtualLiga | None, list[ResumoPreco]] | None:
    produto = s.get(ProdutoLiga, produto_id)
    if produto is None:
        return None
    historico = list(
        s.scalars(
            select(ResumoPreco)
            .where(ResumoPreco.produto_id == produto_id)
            .order_by(ResumoPreco.coletado_em.desc())
            .limit(limite_historico)
        )
    )
    return produto, s.get(PrecoAtualLiga, produto_id), historico
```

- [ ] **Step 3: Implementar `app.py`**

```python
import secrets
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.admin import consultas
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo


def formatar_brl(valor: Decimal | None) -> str:
    if valor is None:
        return "—"
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def formatar_data(dt: datetime | None, zona: ZoneInfo) -> str:
    return "" if dt is None else dt.astimezone(zona).strftime("%d/%m/%Y %H:%M")


def criar_app(sessoes: sessionmaker[Session], config: Config) -> FastAPI:
    seguranca = HTTPBasic()

    def autenticar(credenciais: Annotated[HTTPBasicCredentials, Depends(seguranca)]) -> None:
        if not secrets.compare_digest(credenciais.password.encode(), config.admin_senha.encode()):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, headers={"WWW-Authenticate": "Basic"})

    app = FastAPI(title="TCG Sniper", dependencies=[Depends(autenticar)])
    templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
    templates.env.filters["brl"] = formatar_brl
    templates.env.filters["data"] = lambda dt: formatar_data(dt, config.zona)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        with sessoes() as s, s.begin():
            return templates.TemplateResponse(
                request,
                "index.html",
                {
                    "estado": repo.obter_estado(s),
                    "coletas": consultas.listar_coletas(s),
                    "host": config.host_publico,
                },
            )

    @app.post("/retomar")
    def retomar():
        with sessoes() as s, s.begin():
            repo.retomar(s, repo.agora_utc())
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/rodar-agora")
    def rodar_agora():
        with sessoes() as s, s.begin():
            repo.solicitar_execucao(s, repo.agora_utc())
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/catalogo", response_class=HTMLResponse)
    def catalogo(request: Request, busca: str = "", filtro: str = "todos"):
        if filtro not in consultas.FILTROS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"filtro inválido: {filtro}")
        with sessoes() as s, s.begin():
            linhas = consultas.buscar_catalogo(s, busca, filtro, repo.agora_utc())
            return templates.TemplateResponse(
                request,
                "catalogo.html",
                {"linhas": linhas, "busca": busca, "filtro": filtro, "filtros": consultas.FILTROS},
            )

    @app.post("/produto/{produto_id}/ativo", response_class=HTMLResponse)
    def alternar_ativo(request: Request, produto_id: int):
        with sessoes() as s, s.begin():
            resultado = consultas.alternar_ativo(s, produto_id)
            if resultado is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            produto, atual = resultado
            return templates.TemplateResponse(request, "_linha_produto.html", {"p": produto, "atual": atual})

    @app.get("/produto/{produto_id}", response_class=HTMLResponse)
    def produto(request: Request, produto_id: int):
        with sessoes() as s, s.begin():
            resultado = consultas.detalhe_produto(s, produto_id)
            if resultado is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            p, atual, historico = resultado
            return templates.TemplateResponse(
                request, "produto.html", {"p": p, "atual": atual, "historico": historico}
            )

    return app
```

- [ ] **Step 4: Templates**

`src/tcg_sniper/admin/templates/base.html`:
```html
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block titulo %}TCG Sniper{% endblock %}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2.0.6/css/pico.min.css">
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <style>
    .pausado { background: #fde2e1; color: #7a1c14; padding: 1rem; border-radius: .5rem; margin-bottom: 1rem; }
    td button { margin: 0; padding: .25rem .75rem; }
  </style>
</head>
<body>
<main class="container">
  <nav>
    <ul><li><strong>TCG Sniper</strong></li></ul>
    <ul><li><a href="/">Status</a></li><li><a href="/catalogo">Catálogo</a></li></ul>
  </nav>
  {% block conteudo %}{% endblock %}
</main>
</body>
</html>
```

`src/tcg_sniper/admin/templates/index.html`:
```html
{% extends "base.html" %}
{% block conteudo %}
<h2>Coletor</h2>
{% if estado.estado.value == "pausado_desafio" %}
<div class="pausado">
  <strong>Coleta pausada: desafio pendente.</strong> {{ estado.motivo or "" }}<br>
  Resolva em <a href="http://{{ host }}:6080/vnc.html">http://{{ host }}:6080/vnc.html</a> e clique em retomar.
  <form method="post" action="/retomar"><button>Retomar</button></form>
</div>
{% else %}
<p>Ativo.{% if estado.execucao_solicitada %} Execução solicitada; começa em até 1 minuto.{% endif %}</p>
<form method="post" action="/rodar-agora"><button>Rodar agora</button></form>
{% endif %}

<h2>Últimas coletas</h2>
<table>
  <thead><tr><th>#</th><th>Tipo</th><th>Início</th><th>Fim</th><th>Status</th><th>OK</th><th>Falhas</th><th>Erro</th></tr></thead>
  <tbody>
  {% for c in coletas %}
    <tr>
      <td>{{ c.id }}</td><td>{{ c.tipo.value }}</td><td>{{ c.iniciada_em|data }}</td><td>{{ c.finalizada_em|data }}</td>
      <td>{{ c.status.value }}</td><td>{{ c.produtos_ok }}</td><td>{{ c.produtos_falha }}</td><td>{{ c.erro or "" }}</td>
    </tr>
  {% else %}
    <tr><td colspan="8">Nenhuma coleta ainda.</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

`src/tcg_sniper/admin/templates/catalogo.html`:
```html
{% extends "base.html" %}
{% block titulo %}Catálogo · TCG Sniper{% endblock %}
{% block conteudo %}
<h2>Catálogo</h2>
<form method="get" action="/catalogo" role="search">
  <input type="search" name="busca" value="{{ busca }}" placeholder="Buscar por nome">
  <select name="filtro">
    {% for f in filtros %}<option value="{{ f }}" {% if f == filtro %}selected{% endif %}>{{ f }}</option>{% endfor %}
  </select>
  <button type="submit">Filtrar</button>
</form>
<p>{{ linhas|length }} produto(s).</p>
<table>
  <thead><tr><th>Nome</th><th>Edição</th><th>Mín</th><th>Lojas</th><th>Visto desde</th><th>Monitorar</th></tr></thead>
  <tbody>
  {% for p, atual in linhas %}
    {% include "_linha_produto.html" %}
  {% else %}
    <tr><td colspan="6">Nenhum produto encontrado.</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

`src/tcg_sniper/admin/templates/_linha_produto.html`:
```html
<tr id="produto-{{ p.id }}">
  <td><a href="/produto/{{ p.id }}">{{ p.nome }}</a></td>
  <td>{{ p.edicao or "" }}</td>
  <td>{{ (atual.preco_min if atual else None)|brl }}</td>
  <td>{{ atual.num_lojas if atual else "—" }}</td>
  <td>{{ p.visto_primeiro_em|data }}</td>
  <td>
    <button hx-post="/produto/{{ p.id }}/ativo" hx-target="#produto-{{ p.id }}" hx-swap="outerHTML"
            class="{{ '' if p.ativo else 'secondary outline' }}">{{ "Ativo" if p.ativo else "Inativo" }}</button>
  </td>
</tr>
```

`src/tcg_sniper/admin/templates/produto.html`:
```html
{% extends "base.html" %}
{% block titulo %}{{ p.nome }} · TCG Sniper{% endblock %}
{% block conteudo %}
<h2>{{ p.nome }}</h2>
<p><a href="{{ p.url }}" target="_blank" rel="noopener">Ver na LigaMagic</a> · {{ "Monitorado" if p.ativo else "Não monitorado" }}</p>
<article>
  <strong>Mín:</strong> {{ (atual.preco_min if atual else None)|brl }} ·
  <strong>Médio:</strong> {{ (atual.preco_medio if atual else None)|brl }} ·
  <strong>Máx:</strong> {{ (atual.preco_max if atual else None)|brl }}<br>
  <strong>Lojas:</strong> {{ atual.num_lojas if atual else "—" }}<br>
  <strong>Atualizado em:</strong> {{ (atual.atualizado_em if atual else None)|data }}
</article>
<h3>Histórico</h3>
<table>
  <thead><tr><th>Data</th><th>Mín</th><th>Médio</th><th>Máx</th><th>Lojas</th></tr></thead>
  <tbody>
  {% for r in historico %}
    <tr><td>{{ r.coletado_em|data }}</td><td>{{ r.preco_min|brl }}</td><td>{{ r.preco_medio|brl }}</td><td>{{ r.preco_max|brl }}</td><td>{{ r.num_lojas }}</td></tr>
  {% else %}
    <tr><td colspan="5">Sem coletas ainda.</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

- [ ] **Step 5: Rodar**

Run: `uv run pytest tests/admin -v`
Expected: 18 passed.

- [ ] **Step 6: Commit**

```bash
git add src/tcg_sniper/admin tests/admin
git commit -m "feat: admin web page with status, catalog toggle and price history"
```

---

### Task 11: CLI, Docker e Evolution API

**Files:**
- Create: `src/tcg_sniper/cli.py`, `Dockerfile`, `.dockerignore`, `docker/coletor-entrypoint.sh`
- Modify: `docker-compose.yml`, `README.md` (hoje em UTF-16; reescrever em UTF-8)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: tudo das tasks anteriores.
- Produces: comando `tcg-sniper` com subcomandos `migrate`, `coletor-liga`, `admin [--porta N]`; `cli.main(argv: list[str] | None = None) -> None`.

- [ ] **Step 1: Teste da CLI**

`tests/test_cli.py`:
```python
import pytest

from tcg_sniper import cli


def test_subcomando_obrigatorio():
    with pytest.raises(SystemExit):
        cli.main([])


def test_migrate_chama_migrar(monkeypatch):
    chamadas = []
    monkeypatch.setattr(cli, "migrar", chamadas.append)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x@y/z")
    cli.main(["migrate"])
    assert chamadas == ["postgresql+psycopg://x@y/z"]
```

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL, `ImportError: cannot import name 'cli'`.

- [ ] **Step 2: Implementar `cli.py`**

```python
import argparse
import logging

from tcg_sniper.config import Config
from tcg_sniper.db.session import criar_engine, criar_sessoes, migrar


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tcg-sniper")
    sub = parser.add_subparsers(dest="comando", required=True)
    sub.add_parser("migrate", help="aplica as migrações do banco")
    sub.add_parser("coletor-liga", help="inicia o agendador de coletas da LigaMagic")
    admin = sub.add_parser("admin", help="inicia a página de admin")
    admin.add_argument("--porta", type=int, default=8000)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = Config()

    if args.comando == "migrate":
        migrar(config.database_url)
        return

    engine = criar_engine(config.database_url)
    sessoes = criar_sessoes(engine)

    if args.comando == "coletor-liga":
        from tcg_sniper.coletor_liga.agendador import Agendador
        from tcg_sniper.coletor_liga.navegador import NavegadorPlaywright
        from tcg_sniper.notificador import criar_notificador

        Agendador(
            engine,
            sessoes,
            lambda: NavegadorPlaywright(config.dir_dados / "perfil"),
            criar_notificador(config),
            config,
        ).rodar()
    elif args.comando == "admin":
        import uvicorn

        from tcg_sniper.admin.app import criar_app

        uvicorn.run(criar_app(sessoes, config), host="0.0.0.0", port=args.porta)
```

Run: `uv run pytest tests/test_cli.py -v`
Expected: 2 passed.

- [ ] **Step 3: Dockerfile e entrypoint**

`.dockerignore`:
```
.venv
.git
.env
.perfil-dev
dados
tests
docs
```

`Dockerfile`:
```dockerfile
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update \
    && apt-get install -y --no-install-recommends xvfb x11vnc novnc websockify fluxbox \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
RUN .venv/bin/playwright install --with-deps chromium

COPY src ./src
COPY docker ./docker
RUN uv sync --frozen --no-dev && chmod +x docker/*.sh

ENV PATH="/app/.venv/bin:$PATH"
```

`docker/coletor-entrypoint.sh`:
```sh
#!/bin/sh
set -e
: "${VNC_SENHA:?defina VNC_SENHA no .env}"

export DISPLAY=:99
rm -f /tmp/.X99-lock

Xvfb :99 -screen 0 1366x768x24 &
sleep 1
fluxbox >/dev/null 2>&1 &
x11vnc -display :99 -forever -shared -passwd "$VNC_SENHA" -rfbport 5900 -quiet &
websockify --web /usr/share/novnc 6080 localhost:5900 >/dev/null 2>&1 &

exec tcg-sniper coletor-liga
```

- [ ] **Step 4: Escolher a imagem da Evolution API**

Confira a imagem e a tag atuais da Evolution API v2 (Docker Hub `evoapicloud/evolution-api` ou o README do repositório `EvolutionAPI/evolution-api`) e as variáveis de ambiente que essa versão exige para Postgres sem Redis. Fixe uma tag exata (nunca `latest`). Ajuste o bloco `evolution` do Step 5 se os nomes das variáveis forem diferentes.

- [ ] **Step 5: `docker-compose.yml` completo**

```yaml
x-app: &app
  build: .
  image: tcg-sniper
  env_file: .env
  environment:
    DATABASE_URL: postgresql+psycopg://tcg:tcg@postgres:5432/tcg
    DIR_DADOS: /data
    EVOLUTION_URL: http://evolution:8080
  volumes:
    - dados:/data
  restart: unless-stopped

services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: tcg
      POSTGRES_PASSWORD: tcg
      POSTGRES_DB: tcg
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./docker/postgres-init.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
    ports:
      - "127.0.0.1:5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U tcg"]
      interval: 5s
      retries: 10
    restart: unless-stopped

  evolution:
    image: evoapicloud/evolution-api:<tag fixada no Step 4>
    environment:
      SERVER_URL: http://localhost:8080
      AUTHENTICATION_API_KEY: ${EVOLUTION_API_KEY}
      DATABASE_ENABLED: "true"
      DATABASE_PROVIDER: postgresql
      DATABASE_CONNECTION_URI: postgresql://tcg:tcg@postgres:5432/evolution?schema=public
      CACHE_REDIS_ENABLED: "false"
      CACHE_LOCAL_ENABLED: "true"
    volumes:
      - evolution:/evolution/instances
    ports:
      - "127.0.0.1:8080:8080"
    depends_on:
      postgres:
        condition: service_healthy
    restart: unless-stopped

  migrate:
    <<: *app
    command: tcg-sniper migrate
    restart: "no"
    depends_on:
      postgres:
        condition: service_healthy

  coletor-liga:
    <<: *app
    entrypoint: ["/app/docker/coletor-entrypoint.sh"]
    shm_size: 1gb
    ports:
      - "6080:6080"
    depends_on:
      migrate:
        condition: service_completed_successfully

  admin:
    <<: *app
    command: tcg-sniper admin
    ports:
      - "8000:8000"
    depends_on:
      migrate:
        condition: service_completed_successfully

volumes:
  pgdata:
  dados:
  evolution:
```

- [ ] **Step 6: README com o runbook**

Reescreva `README.md` em UTF-8:
````markdown
# tcg-sniper

Monitor de arbitragem de selados de Magic. Sub-projeto 1: coleta diária da LigaMagic, admin e alertas no grupo admin do WhatsApp.

Design: `docs/superpowers/specs/2026-10-13-coletor-liga-design.md`.

## Desenvolvimento

```
docker compose up -d postgres
uv sync
uv run playwright install chromium
cp .env.example .env   # ajuste os valores
uv run pytest
```

## Subir tudo

1. Copie `.env.example` para `.env` e defina `ADMIN_SENHA`, `VNC_SENHA`, `EVOLUTION_API_KEY`, `LIGA_URL_CATALOGO` e `HOST_PUBLICO` (IP do PC na rede local).
2. `docker compose up -d --build`
3. Conecte o WhatsApp (chip secundário, nunca um número pessoal ou da loja):
   - `curl -X POST http://localhost:8080/instance/create -H "apikey: $EVOLUTION_API_KEY" -H "Content-Type: application/json" -d '{"instanceName":"tcg-sniper","integration":"WHATSAPP-BAILEYS","qrcode":true}'`
   - Leia o QR code devolvido (ou `GET /instance/connect/tcg-sniper`) com o WhatsApp do chip.
   - Adicione o número ao grupo admin e descubra o ID: `curl "http://localhost:8080/group/fetchAllGroups/tcg-sniper?getParticipants=false" -H "apikey: $EVOLUTION_API_KEY"`.
   - Grave o ID (`...@g.us`) em `WHATSAPP_GRUPO_ADMIN` e rode `docker compose up -d coletor-liga`.
4. Admin: `http://<HOST_PUBLICO>:8000` (usuário qualquer, senha `ADMIN_SENHA`).
5. noVNC (para resolver desafio do Cloudflare): `http://<HOST_PUBLICO>:6080/vnc.html` (senha `VNC_SENHA`).

## Quando chegar um aviso de desafio

Abra o noVNC, resolva a verificação na janela do Chromium e clique em **Retomar** no admin. O coletor não tenta de novo sozinho.
````

- [ ] **Step 7: Smoke test completo**

Run: `docker compose up -d --build` e depois `docker compose ps`
Expected: `postgres`, `evolution`, `coletor-liga`, `admin` em `running`; `migrate` em `exited (0)`.

Run: `docker compose logs coletor-liga --tail 50`
Expected: `agendador iniciado`; sem traceback.

Abra `http://localhost:8000` (status "Ativo") e `http://localhost:6080/vnc.html` (área de trabalho com o Chromium ao iniciar uma coleta). Clique em **Rodar agora** e acompanhe pelos logs e pelo noVNC: dentro de 1 minuto a coleta começa. Na primeira execução, como não há catálogo, ela entra como execução atrasada com varredura em até 30 min.

Run: `uv run pytest -v`
Expected: suíte inteira passa.

- [ ] **Step 8: Commit**

```bash
git add src/tcg_sniper/cli.py tests/test_cli.py Dockerfile .dockerignore docker docker-compose.yml README.md
git commit -m "feat: CLI, Docker image with Xvfb/noVNC and full compose stack"
```
