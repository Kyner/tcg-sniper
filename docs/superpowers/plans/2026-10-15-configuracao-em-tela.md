# Configuração em tela Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Levar para a tela Configurações do admin (seções Geral, LigaMagic e Amazon) tudo o que é operação e ainda vem do `.env`, valendo no próximo ciclo sem reiniciar.

**Architecture:** Duas tabelas de uma linha (`config_geral`, `config_liga`) no padrão da `config_amazon`, criadas na primeira leitura com os valores do `.env`. `carregar_config(sessoes, config_env)` devolve um `Config` com os valores do banco por cima; o agendador da Liga e a varredura da Amazon o chamam a cada passo, o admin a cada requisição e o notificador lê instância e grupos do banco a cada envio.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, FastAPI + Jinja2 + Pico CSS, Postgres 16, pytest.

**Spec:** `docs/superpowers/specs/2026-10-15-configuracao-em-tela-design.md`

## Global Constraints

- Ficam no `.env` (não vão para o banco nem para a tela): `DATABASE_URL`, `DIR_DADOS`, `EVOLUTION_URL`, `EVOLUTION_API_KEY`, `VNC_SENHA`, `ADMIN_SENHA`.
- Vão para a tela, com estas colunas: Geral — `host_publico`, `fuso`, `evolution_instancia`, `whatsapp_grupo_admin`, `whatsapp_grupo_oportunidades`; LigaMagic — `coleta_hora`, `coleta_jitter_min`, `pausa_min_s`, `pausa_max_s`, `limite_falha_pct`, `categorias`, `url_listagem`, `max_cliques`.
- Limites: `coleta_jitter_min` 0–180; `pausa_min_s`/`pausa_max_s` 0–120 e mínima ≤ máxima; `limite_falha_pct` 0–100; `max_cliques` 1–500; `url_listagem` contém `{categ}`; `categorias` = IDs numéricos separados por vírgula, ao menos um; `host_publico` não vazio e sem espaços; `fuso` válido em `ZoneInfo`; grupos vazios ou terminados em `@g.us`.
- A mudança vale no próximo ciclo, sem reiniciar. Job da Liga em andamento termina com os valores do início.
- Valores iniciais: na primeira leitura, a linha é criada com os valores do `Config` do `.env`. A migração só cria as tabelas.
- As variáveis migradas que ainda estiverem no `.env` são ignoradas: vale o banco.
- Mensagem de sucesso na tela: `Salvo; vale a partir da próxima coleta ou ciclo.`
- Rodapé da tela: `Senhas, banco e chave da Evolution ficam no .env: ADMIN_SENHA, VNC_SENHA, EVOLUTION_API_KEY, DATABASE_URL, DIR_DADOS, EVOLUTION_URL.`
- Testes com `DATABASE_URL_TESTE` (Postgres). Comandos: `uv run pytest -q` e `uv run ruff check .`.
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. `.env` com valor que hoje o banco recusaria (pausa acima de 120, `HOST_PUBLICO` vazio) na primeira leitura: a linha tem que ser criada mesmo assim (valor ajustado ao limite), sem derrubar o serviço. Teste na Task 1.
2. Dois serviços subindo juntos e lendo pela primeira vez ao mesmo tempo: a criação da linha não pode falhar por chave duplicada (`ON CONFLICT DO NOTHING`). Teste na Task 1 (segunda leitura não recria nem sobrescreve).
3. Erro de banco ao ler a configuração dentro do `enviar` do notificador: nunca lança exceção (contrato do `Notificador`). Teste na Task 2.
4. Horário da coleta mudado depois que o job do dia já rodou: não pode rodar de novo no mesmo dia. Teste na Task 3.
5. POST de uma seção com erro não pode apagar o que as outras seções mostram nem gravar nada. Teste na Task 4.

---

## Ondas (para execução paralela)

- Onda A: Task 1.
- Onda B (depois da 1, em paralelo, arquivos disjuntos): Task 2 (notificador + `cli.py`), Task 3 (agendador + varredura), Task 4 (admin).
- Onda C: Task 5 (documentação).

---

### Task 1: Tabelas, repositório, carga e validação

**Files:**
- Modify: `src/tcg_sniper/db/models.py` (imports; constantes e classes novas depois de `ConfigAmazon`)
- Create: `src/tcg_sniper/db/migrations/versions/b7c1e5f0a2d4_config_geral_liga.py`
- Modify: `src/tcg_sniper/db/repositorio.py` (funções novas no fim)
- Create: `src/tcg_sniper/config_banco.py`
- Modify: `src/tcg_sniper/coletor_amazon/config.py` (`_hora` vira `ler_hora`, público)
- Create: `src/tcg_sniper/admin/formularios_config.py`
- Test: `tests/db/test_config_banco.py`, `tests/admin/test_formularios_config.py`, `tests/db/test_migracao.py`

**Interfaces:**
- Produces:
  - `models.ConfigGeral`, `models.ConfigLiga`, `models.LIMITES_CONFIG_LIGA: dict[str, tuple[int, int]]`
  - `repositorio.obter_config_geral(s: Session, padrao: Config) -> ConfigGeral`
  - `repositorio.obter_config_liga(s: Session, padrao: Config) -> ConfigLiga`
  - `repositorio.salvar_config_geral(s: Session, valores: Mapping[str, object], agora: datetime) -> None`
  - `repositorio.salvar_config_liga(s: Session, valores: Mapping[str, object], agora: datetime) -> None`
  - `config_banco.sobrepor(config: Config, geral: ConfigGeral, liga: ConfigLiga) -> Config`
  - `config_banco.carregar_config(sessoes: sessionmaker[Session], config_env: Config) -> Config`
  - `coletor_amazon.config.ler_hora(texto: str) -> time | None`
  - `admin.formularios_config`: `CAMPOS_GERAL`, `ROTULOS_GERAL`, `EXPLICACOES_GERAL`, `CAMPOS_LIGA`, `ROTULOS_LIGA`, `EXPLICACOES_LIGA` (tuplas/dicts de str), `validar_geral(campos: Mapping[str, str]) -> tuple[dict[str, object], dict[str, str]]`, `validar_liga(campos: Mapping[str, str]) -> tuple[dict[str, object], dict[str, str]]`

- [ ] **Step 1: Testes do banco e da carga (falham)**

Create `tests/db/test_config_banco.py`:

```python
from datetime import UTC, datetime, time

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from tcg_sniper.config_banco import carregar_config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import ConfigGeral, ConfigLiga

AGORA = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def test_primeira_leitura_cria_as_linhas_com_os_valores_do_env(s, config):
    geral = repo.obter_config_geral(s, config)
    liga = repo.obter_config_liga(s, config)
    assert (geral.host_publico, geral.fuso, geral.evolution_instancia) == ("host.test", "America/Sao_Paulo", None)
    assert (liga.categorias, liga.url_listagem, liga.max_cliques) == (
        "10,11,12",
        "https://liga.test/listagem?categ={categ}",
        5,
    )
    assert (liga.coleta_hora, liga.pausa_min_s, liga.pausa_max_s, liga.limite_falha_pct) == (time(10, 0), 8, 20, 50)


def test_segunda_leitura_nao_sobrescreve_o_que_foi_salvo(s, config):
    repo.obter_config_geral(s, config)
    repo.salvar_config_geral(s, {"host_publico": "192.168.0.10"}, AGORA)
    outro_env = config.model_copy(update={"host_publico": "outro.test"})
    assert repo.obter_config_geral(s, outro_env).host_publico == "192.168.0.10"


def test_env_fora_dos_limites_e_ajustado_na_primeira_leitura(s, config):
    estranho = config.model_copy(update={"host_publico": "  ", "pausa_min_s": 200.0, "pausa_max_s": 300.0})
    geral = repo.obter_config_geral(s, estranho)
    liga = repo.obter_config_liga(s, estranho)
    assert geral.host_publico == "localhost"
    assert (liga.pausa_min_s, liga.pausa_max_s) == (120, 120)


def test_grupos_vazios_do_env_viram_none(s, config):
    c = config.model_copy(update={"evolution_instancia": "", "whatsapp_grupo_admin": "  "})
    geral = repo.obter_config_geral(s, c)
    assert (geral.evolution_instancia, geral.whatsapp_grupo_admin) == (None, None)


def test_carregar_config_sobrepoe_o_banco_ao_env(sessoes, config):
    with sessoes() as s, s.begin():
        repo.obter_config_geral(s, config)
        repo.obter_config_liga(s, config)
        repo.salvar_config_geral(s, {"host_publico": "10.0.0.5", "whatsapp_grupo_admin": "1@g.us"}, AGORA)
        repo.salvar_config_liga(s, {"coleta_hora": time(7, 30), "categorias": "21,22"}, AGORA)
    efetiva = carregar_config(sessoes, config)
    assert efetiva.host_publico == "10.0.0.5"
    assert efetiva.whatsapp_grupo_admin == "1@g.us"
    assert efetiva.coleta_hora == time(7, 30)
    assert efetiva.categorias == ["21", "22"]
    assert efetiva.dir_dados == config.dir_dados  # o que é do .env continua do .env
    assert config.host_publico == "host.test"  # o Config do .env não é alterado


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("coleta_jitter_min", 181),
        ("pausa_max_s", 121),
        ("limite_falha_pct", 101),
        ("max_cliques", 0),
        ("url_listagem", "https://liga.test/x"),
        ("categorias", "10,,11"),
        ("categorias", "abc"),
    ],
)
def test_config_liga_recusa_valores_fora_dos_limites(s, config, campo, valor):
    repo.obter_config_liga(s, config)
    with pytest.raises(IntegrityError):
        s.execute(update(ConfigLiga).where(ConfigLiga.id == 1).values({campo: valor}))


def test_config_liga_recusa_pausa_minima_maior_que_a_maxima(s, config):
    repo.obter_config_liga(s, config)
    with pytest.raises(IntegrityError):
        s.execute(update(ConfigLiga).where(ConfigLiga.id == 1).values(pausa_min_s=30, pausa_max_s=20))


def test_config_geral_recusa_host_vazio(s, config):
    repo.obter_config_geral(s, config)
    with pytest.raises(IntegrityError):
        s.execute(update(ConfigGeral).where(ConfigGeral.id == 1).values(host_publico=""))
```

Em `tests/db/test_migracao.py`, acrescentar ao fim:

```python
def test_migracao_cria_config_geral_e_liga_vazias(s):
    assert s.get(ConfigGeral, 1) is None
    assert s.get(ConfigLiga, 1) is None
```

e incluir `ConfigGeral, ConfigLiga` no import de `tcg_sniper.db.models` desse arquivo.

- [ ] **Step 2: Testes da validação do formulário (falham)**

Create `tests/admin/test_formularios_config.py`:

```python
from datetime import time

import pytest

from tcg_sniper.admin.formularios_config import validar_geral, validar_liga

GERAL = {
    "host_publico": "192.168.0.10",
    "fuso": "America/Sao_Paulo",
    "evolution_instancia": "TCG Sniper",
    "whatsapp_grupo_admin": "120363000000000001@g.us",
    "whatsapp_grupo_oportunidades": "",
}
LIGA = {
    "coleta_hora": "10:00",
    "coleta_jitter_min": "30",
    "pausa_min_s": "8",
    "pausa_max_s": "20,5",
    "limite_falha_pct": "50",
    "categorias": " 10, 11,10 ,12 ",
    "url_listagem": "https://www.ligamagic.com.br/?view=cards/search&card=categ%3D{categ}",
    "max_cliques": "50",
}


def test_geral_valido():
    valores, erros = validar_geral(GERAL)
    assert erros == {}
    assert valores == {
        "host_publico": "192.168.0.10",
        "fuso": "America/Sao_Paulo",
        "evolution_instancia": "TCG Sniper",
        "whatsapp_grupo_admin": "120363000000000001@g.us",
        "whatsapp_grupo_oportunidades": None,
    }


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("host_publico", ""),
        ("host_publico", "192.168 .0.10"),
        ("fuso", "America/Atlantida"),
        ("fuso", ""),
        ("fuso", "../etc"),
        ("whatsapp_grupo_admin", "120363000000000001"),
        ("whatsapp_grupo_oportunidades", "@g.us"),
    ],
)
def test_geral_invalido(campo, valor):
    _, erros = validar_geral({**GERAL, campo: valor})
    assert campo in erros


def test_liga_valida_normaliza_categorias_e_pausas():
    valores, erros = validar_liga(LIGA)
    assert erros == {}
    assert valores["coleta_hora"] == time(10, 0)
    assert valores["categorias"] == "10,11,12"
    assert (valores["pausa_min_s"], valores["pausa_max_s"]) == (8.0, 20.5)
    assert valores["max_cliques"] == 50


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("coleta_hora", "25:00"),
        ("coleta_hora", "10h"),
        ("coleta_jitter_min", "181"),
        ("coleta_jitter_min", "-1"),
        ("pausa_min_s", "abc"),
        ("pausa_max_s", "121"),
        ("limite_falha_pct", "101"),
        ("categorias", ""),
        ("categorias", "10,abc"),
        ("url_listagem", "https://liga.test/sem-marcador"),
        ("url_listagem", "ftp://liga.test/{categ}"),
        ("max_cliques", "0"),
        ("max_cliques", "9999999"),
    ],
)
def test_liga_invalida(campo, valor):
    _, erros = validar_liga({**LIGA, campo: valor})
    assert campo in erros


def test_liga_recusa_pausa_minima_maior_que_a_maxima():
    _, erros = validar_liga({**LIGA, "pausa_min_s": "30", "pausa_max_s": "20"})
    assert "pausa_min_s" in erros
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest -q tests/db/test_config_banco.py tests/admin/test_formularios_config.py tests/db/test_migracao.py`
Expected: FAIL/ERROR com `ImportError` (`ConfigGeral`, `carregar_config`, `validar_geral` não existem).

- [ ] **Step 4: Modelos**

Em `src/tcg_sniper/db/models.py`, acrescentar `Float` ao import de `sqlalchemy` (ordem alfabética, depois de `Enum`). Depois da classe `ConfigAmazon`, acrescentar:

```python
LIMITES_CONFIG_LIGA: dict[str, tuple[int, int]] = {
    "coleta_jitter_min": (0, 180),
    "pausa_min_s": (0, 120),
    "pausa_max_s": (0, 120),
    "limite_falha_pct": (0, 100),
    "max_cliques": (1, 500),
}


class ConfigGeral(Base):
    """Configuração geral (links, fuso, WhatsApp): uma linha, editável no admin. Criada na primeira
    leitura com os valores do .env (`repositorio.obter_config_geral`)."""

    __tablename__ = "config_geral"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_config_geral_linha_unica"),
        CheckConstraint("host_publico <> ''", name="ck_config_geral_host"),
        CheckConstraint("fuso <> ''", name="ck_config_geral_fuso"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    host_publico: Mapped[str] = mapped_column(Text)
    fuso: Mapped[str] = mapped_column(Text)
    evolution_instancia: Mapped[str | None] = mapped_column(Text)
    whatsapp_grupo_admin: Mapped[str | None] = mapped_column(Text)
    whatsapp_grupo_oportunidades: Mapped[str | None] = mapped_column(Text)
    atualizado_em: Mapped[datetime] = mapped_column(DATA)


class ConfigLiga(Base):
    """Configuração da coleta da LigaMagic: uma linha, editável no admin. Criada na primeira leitura
    com os valores do .env (`repositorio.obter_config_liga`)."""

    __tablename__ = "config_liga"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_config_liga_linha_unica"),
        CheckConstraint("position('{categ}' in url_listagem) > 0", name="ck_config_liga_url"),
        CheckConstraint("categorias ~ '^[0-9]+(,[0-9]+)*$'", name="ck_config_liga_categorias"),
        CheckConstraint("pausa_min_s <= pausa_max_s", name="ck_config_liga_pausas"),
        *(
            CheckConstraint(f"{campo} BETWEEN {minimo} AND {maximo}", name=f"ck_config_liga_{campo}")
            for campo, (minimo, maximo) in LIMITES_CONFIG_LIGA.items()
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    coleta_hora: Mapped[time] = mapped_column(Time)
    coleta_jitter_min: Mapped[int] = mapped_column(Integer)
    pausa_min_s: Mapped[float] = mapped_column(Float)
    pausa_max_s: Mapped[float] = mapped_column(Float)
    limite_falha_pct: Mapped[int] = mapped_column(Integer)
    categorias: Mapped[str] = mapped_column(Text)
    url_listagem: Mapped[str] = mapped_column(Text)
    max_cliques: Mapped[int] = mapped_column(Integer)
    atualizado_em: Mapped[datetime] = mapped_column(DATA)
```

(`DATA` já existe no módulo; confira o nome usado pela `ConfigAmazon` e use o mesmo.)

- [ ] **Step 5: Migração**

Create `src/tcg_sniper/db/migrations/versions/b7c1e5f0a2d4_config_geral_liga.py`:

```python
"""config_geral e config_liga: o que saiu do .env para a tela de Configurações

Revision ID: b7c1e5f0a2d4
Revises: a4e2c7d91b30
Create Date: 2026-10-15 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c1e5f0a2d4"
down_revision: Union[str, Sequence[str], None] = "a4e2c7d91b30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DATA = sa.DateTime(timezone=True)
LIMITES_LIGA = {
    "coleta_jitter_min": (0, 180),
    "pausa_min_s": (0, 120),
    "pausa_max_s": (0, 120),
    "limite_falha_pct": (0, 100),
    "max_cliques": (1, 500),
}


def upgrade() -> None:
    # Sem INSERT: a linha é criada na primeira leitura com os valores do .env do serviço.
    op.create_table(
        "config_geral",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("host_publico", sa.Text(), nullable=False),
        sa.Column("fuso", sa.Text(), nullable=False),
        sa.Column("evolution_instancia", sa.Text(), nullable=True),
        sa.Column("whatsapp_grupo_admin", sa.Text(), nullable=True),
        sa.Column("whatsapp_grupo_oportunidades", sa.Text(), nullable=True),
        sa.Column("atualizado_em", DATA, nullable=False),
        sa.CheckConstraint("id = 1", name="ck_config_geral_linha_unica"),
        sa.CheckConstraint("host_publico <> ''", name="ck_config_geral_host"),
        sa.CheckConstraint("fuso <> ''", name="ck_config_geral_fuso"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "config_liga",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("coleta_hora", sa.Time(), nullable=False),
        sa.Column("coleta_jitter_min", sa.Integer(), nullable=False),
        sa.Column("pausa_min_s", sa.Float(), nullable=False),
        sa.Column("pausa_max_s", sa.Float(), nullable=False),
        sa.Column("limite_falha_pct", sa.Integer(), nullable=False),
        sa.Column("categorias", sa.Text(), nullable=False),
        sa.Column("url_listagem", sa.Text(), nullable=False),
        sa.Column("max_cliques", sa.Integer(), nullable=False),
        sa.Column("atualizado_em", DATA, nullable=False),
        sa.CheckConstraint("id = 1", name="ck_config_liga_linha_unica"),
        sa.CheckConstraint("position('{categ}' in url_listagem) > 0", name="ck_config_liga_url"),
        sa.CheckConstraint("categorias ~ '^[0-9]+(,[0-9]+)*$'", name="ck_config_liga_categorias"),
        sa.CheckConstraint("pausa_min_s <= pausa_max_s", name="ck_config_liga_pausas"),
        *(
            sa.CheckConstraint(f"{campo} BETWEEN {minimo} AND {maximo}", name=f"ck_config_liga_{campo}")
            for campo, (minimo, maximo) in LIMITES_LIGA.items()
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("config_liga")
    op.drop_table("config_geral")
```

- [ ] **Step 6: Repositório**

Em `src/tcg_sniper/db/repositorio.py`: acrescentar `from collections.abc import Mapping` ao import de `collections.abc`, `from tcg_sniper.config import Config` e `ConfigGeral, ConfigLiga` ao import de `tcg_sniper.db.models`. No fim do arquivo:

```python
# --- configuração em tela (geral e LigaMagic) ------------------------------------------------


def _vazio_para_none(texto: str | None) -> str | None:
    return (texto or "").strip() or None


def _pausa(valor: float) -> float:
    return min(max(valor, 0.0), 120.0)


def obter_config_geral(s: Session, padrao: Config) -> ConfigGeral:
    """A configuração geral. Na primeira leitura cria a linha com os valores do .env (`padrao`),
    ajustados aos limites do banco; depois o .env é ignorado."""
    geral = s.get(ConfigGeral, 1, populate_existing=True)
    if geral is not None:
        return geral
    s.execute(
        pg_insert(ConfigGeral)
        .values(
            id=1,
            host_publico=padrao.host_publico.strip() or "localhost",
            fuso=padrao.fuso.strip() or "America/Sao_Paulo",
            evolution_instancia=_vazio_para_none(padrao.evolution_instancia),
            whatsapp_grupo_admin=_vazio_para_none(padrao.whatsapp_grupo_admin),
            whatsapp_grupo_oportunidades=_vazio_para_none(padrao.whatsapp_grupo_oportunidades),
            atualizado_em=agora_utc(),
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    return s.get(ConfigGeral, 1, populate_existing=True)


def obter_config_liga(s: Session, padrao: Config) -> ConfigLiga:
    """A configuração da coleta da Liga. Na primeira leitura cria a linha com os valores do .env
    (`padrao`), ajustados aos limites do banco; depois o .env é ignorado."""
    liga = s.get(ConfigLiga, 1, populate_existing=True)
    if liga is not None:
        return liga
    pausa_min, pausa_max = _pausa(padrao.pausa_min_s), _pausa(padrao.pausa_max_s)
    s.execute(
        pg_insert(ConfigLiga)
        .values(
            id=1,
            coleta_hora=padrao.coleta_hora,
            coleta_jitter_min=padrao.coleta_jitter_min,
            pausa_min_s=min(pausa_min, pausa_max),
            pausa_max_s=pausa_max,
            limite_falha_pct=padrao.limite_falha_pct,
            categorias=padrao.liga_categorias,
            url_listagem=padrao.liga_url_listagem,
            max_cliques=padrao.liga_max_cliques,
            atualizado_em=agora_utc(),
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    return s.get(ConfigLiga, 1, populate_existing=True)


def salvar_config_geral(s: Session, valores: Mapping[str, object], agora: datetime) -> None:
    s.execute(update(ConfigGeral).where(ConfigGeral.id == 1).values(**valores, atualizado_em=agora))
    s.flush()


def salvar_config_liga(s: Session, valores: Mapping[str, object], agora: datetime) -> None:
    s.execute(update(ConfigLiga).where(ConfigLiga.id == 1).values(**valores, atualizado_em=agora))
    s.flush()
```

(`agora_utc` já existe em `repositorio.py`. Se o import de `Config` criar ciclo, importe dentro de `if TYPE_CHECKING:` e use a anotação como string.)

- [ ] **Step 7: Carga**

Create `src/tcg_sniper/config_banco.py`:

```python
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
```

- [ ] **Step 8: `ler_hora` público na Amazon**

Em `src/tcg_sniper/coletor_amazon/config.py`, renomear `_hora` para `ler_hora` (definição e o uso em `validar_config`). Nenhum outro arquivo usa `_hora` (confira com `grep -rn "_hora(" src tests`).

- [ ] **Step 9: Validação do formulário**

Create `src/tcg_sniper/admin/formularios_config.py`:

```python
"""Validação das seções Geral e LigaMagic da tela de Configurações, com os limites do banco."""

import re
from collections.abc import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tcg_sniper.coletor_amazon.config import ler_hora
from tcg_sniper.db.models import LIMITES_CONFIG_LIGA

PAUSA_RE = re.compile(r"[0-9]{1,3}(\.[0-9]{1,2})?")

CAMPOS_GERAL = (
    "host_publico",
    "fuso",
    "evolution_instancia",
    "whatsapp_grupo_admin",
    "whatsapp_grupo_oportunidades",
)
ROTULOS_GERAL = {
    "host_publico": "IP ou nome deste PC na rede",
    "fuso": "Fuso horário",
    "evolution_instancia": "Instância da Evolution API",
    "whatsapp_grupo_admin": "Grupo de WhatsApp do admin",
    "whatsapp_grupo_oportunidades": "Grupo de WhatsApp de oportunidades",
}
EXPLICACOES_GERAL = {
    "host_publico": "Vai nos links das mensagens (admin e noVNC). No Windows: ipconfig, \"Endereço IPv4\".",
    "fuso": "Usado no horário da coleta e nas datas do admin e das mensagens. Ex.: America/Sao_Paulo.",
    "evolution_instancia": "Nome da instância criada na Evolution. Vazio: as mensagens vão só para o log.",
    "whatsapp_grupo_admin": "ID do grupo (120363...@g.us) que recebe desafios, falhas e resumos. Vazio: só log.",
    "whatsapp_grupo_oportunidades": "ID do grupo (120363...@g.us) que recebe as ofertas com desconto. Vazio: só log.",
}

CAMPOS_LIGA = (
    "coleta_hora",
    "coleta_jitter_min",
    "pausa_min_s",
    "pausa_max_s",
    "limite_falha_pct",
    "categorias",
    "url_listagem",
    "max_cliques",
)
ROTULOS_LIGA = {
    "coleta_hora": "Horário da coleta diária",
    "coleta_jitter_min": "Variação do horário (min)",
    "pausa_min_s": "Pausa mínima (s)",
    "pausa_max_s": "Pausa máxima (s)",
    "limite_falha_pct": "Limite de falhas por coleta (%)",
    "categorias": "Categorias",
    "url_listagem": "URL da listagem",
    "max_cliques": "Máximo de cliques em \"Exibir mais\"",
}
EXPLICACOES_LIGA = {
    "coleta_hora": "Hora (HH:MM), no fuso da seção Geral.",
    "coleta_jitter_min": "Minutos sorteados para mais ou para menos. Com 10:00 e 30, começa entre 09:30 e 10:30.",
    "pausa_min_s": "Pausa mínima, em segundos, entre páginas e antes de cada clique em \"Exibir mais\".",
    "pausa_max_s": "Pausa máxima, em segundos. Pausas menores aumentam a chance de desafio do Cloudflare.",
    "limite_falha_pct": "Percentual de falhas a partir do qual a coleta vira \"falha\" e o grupo admin é avisado.",
    "categorias": "IDs das categorias de selados, separados por vírgula. Tire daqui uma categoria que falha todo dia.",
    "url_listagem": "Modelo da URL de uma categoria; {categ} é trocado pelo ID.",
    "max_cliques": "Cada clique mostra mais 40 produtos. Atingir o limite conta como falha da categoria.",
}


def validar_geral(campos: Mapping[str, str]) -> tuple[dict[str, object], dict[str, str]]:
    valores: dict[str, object] = {}
    erros: dict[str, str] = {}

    host = (campos.get("host_publico") or "").strip()
    if not host or any(c.isspace() for c in host):
        erros["host_publico"] = "Informe o IP ou o nome deste PC, sem espaços."
    else:
        valores["host_publico"] = host

    fuso = (campos.get("fuso") or "").strip()
    try:
        if not fuso:
            raise ValueError(fuso)
        ZoneInfo(fuso)
        valores["fuso"] = fuso
    except (ZoneInfoNotFoundError, ValueError):
        erros["fuso"] = "Fuso desconhecido. Use o formato America/Sao_Paulo."

    valores["evolution_instancia"] = (campos.get("evolution_instancia") or "").strip() or None

    for campo in ("whatsapp_grupo_admin", "whatsapp_grupo_oportunidades"):
        grupo = (campos.get(campo) or "").strip()
        if not grupo:
            valores[campo] = None
        elif not grupo.endswith("@g.us") or len(grupo) <= len("@g.us"):
            erros[campo] = "Use o ID do grupo, terminado em @g.us (passo 5 do README)."
        else:
            valores[campo] = grupo
    return valores, erros


def validar_liga(campos: Mapping[str, str]) -> tuple[dict[str, object], dict[str, str]]:
    valores: dict[str, object] = {}
    erros: dict[str, str] = {}

    hora = ler_hora((campos.get("coleta_hora") or "").strip())
    if hora is None:
        erros["coleta_hora"] = "Use o formato HH:MM, por exemplo 10:00."
    else:
        valores["coleta_hora"] = hora

    for campo in ("coleta_jitter_min", "limite_falha_pct", "max_cliques"):
        minimo, maximo = LIMITES_CONFIG_LIGA[campo]
        texto = (campos.get(campo) or "").strip()
        if not (texto.isascii() and texto.isdecimal()) or len(texto) > 6:
            erros[campo] = f"Informe um número inteiro entre {minimo} e {maximo}."
        elif not minimo <= int(texto) <= maximo:
            erros[campo] = f"O valor deve ficar entre {minimo} e {maximo}."
        else:
            valores[campo] = int(texto)

    for campo in ("pausa_min_s", "pausa_max_s"):
        minimo, maximo = LIMITES_CONFIG_LIGA[campo]
        texto = (campos.get(campo) or "").strip().replace(",", ".")
        if not PAUSA_RE.fullmatch(texto):
            erros[campo] = f"Informe segundos entre {minimo} e {maximo} (ex.: 8 ou 8,5)."
        elif not minimo <= float(texto) <= maximo:
            erros[campo] = f"O valor deve ficar entre {minimo} e {maximo}."
        else:
            valores[campo] = float(texto)
    if "pausa_min_s" in valores and "pausa_max_s" in valores and valores["pausa_min_s"] > valores["pausa_max_s"]:
        erros["pausa_min_s"] = "A pausa mínima não pode ser maior que a máxima."

    ids = [parte.strip() for parte in (campos.get("categorias") or "").split(",") if parte.strip()]
    if not ids or not all(i.isascii() and i.isdecimal() for i in ids):
        erros["categorias"] = "Informe IDs numéricos separados por vírgula, por exemplo 10,11,12."
    else:
        valores["categorias"] = ",".join(dict.fromkeys(ids))

    url = (campos.get("url_listagem") or "").strip()
    if not url.startswith("https://"):
        erros["url_listagem"] = "Use uma URL que comece com https://."
    elif "{categ}" not in url:
        erros["url_listagem"] = "A URL precisa conter {categ}."
    else:
        valores["url_listagem"] = url
    return valores, erros
```

- [ ] **Step 10: Rodar e ver passar**

Run: `uv run pytest -q tests/db/test_config_banco.py tests/admin/test_formularios_config.py tests/db/test_migracao.py tests/admin/test_admin_amazon.py`
Expected: PASS (inclusive `test_migracao_igual_aos_modelos`).

Run: `uv run pytest -q && uv run ruff check .`
Expected: tudo verde.

- [ ] **Step 11: Commit**

```bash
git add src/tcg_sniper/db/models.py src/tcg_sniper/db/migrations/versions/b7c1e5f0a2d4_config_geral_liga.py src/tcg_sniper/db/repositorio.py src/tcg_sniper/config_banco.py src/tcg_sniper/coletor_amazon/config.py src/tcg_sniper/admin/formularios_config.py tests/db/test_config_banco.py tests/admin/test_formularios_config.py tests/db/test_migracao.py
git commit -m "feat: general and LigaMagic settings tables seeded from .env, with loading and form validation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Notificador lê instância e grupos do banco a cada envio

**Files:**
- Modify: `src/tcg_sniper/notificador/evolution.py`
- Modify: `src/tcg_sniper/notificador/__init__.py`
- Modify: `src/tcg_sniper/cli.py` (as duas chamadas de `criar_notificador`)
- Test: `tests/notificador/test_notificador.py`

**Interfaces:**
- Consumes: `repositorio.obter_config_geral(s, padrao) -> ConfigGeral` (Task 1).
- Produces:
  - `EvolutionNotificador(url: str, api_key: str, destinos: Callable[[], tuple[str | None, dict[Destino, str]]], cliente=None, dormir=time.sleep, tentativas=3)`
  - `criar_notificador(config: Config, sessoes: sessionmaker[Session]) -> Notificador`

- [ ] **Step 1: Reescrever os testes (falham)**

Em `tests/notificador/test_notificador.py`:

1. Trocar a fábrica `notificador(pausas)` por:

```python
def notificador(pausas, instancia="inst", grupos=GRUPOS):
    return EvolutionNotificador(URL, "chave", lambda: (instancia, grupos), dormir=pausas.append)
```

2. Substituir os testes de `criar_notificador` (de `test_criar_notificador_sem_evolution_usa_log` até o fim do arquivo) por:

```python
def test_criar_notificador_sem_evolution_usa_log(config, sessoes):
    assert isinstance(criar_notificador(config, sessoes), LogNotificador)


def test_criar_notificador_com_evolution(config, sessoes):
    c = config.model_copy(update={"evolution_url": URL, "evolution_api_key": "chave"})
    assert isinstance(criar_notificador(c, sessoes), EvolutionNotificador)


@pytest.mark.parametrize("chave", ["", "   ", "trocar-esta-chave"])
def test_criar_notificador_chave_padrao_usa_log_e_avisa(config, sessoes, chave, caplog):
    c = config.model_copy(update={"evolution_url": URL, "evolution_api_key": chave})
    with caplog.at_level(logging.WARNING):
        assert isinstance(criar_notificador(c, sessoes), LogNotificador)
    assert "EVOLUTION_API_KEY" in caplog.text


@respx.mock
def test_grupo_e_instancia_salvos_na_tela_valem_na_mensagem_seguinte(config, sessoes):
    c = config.model_copy(update={"evolution_url": URL, "evolution_api_key": "chave"})
    rota_a = respx.post(f"{URL}/message/sendText/inst-a").mock(return_value=httpx.Response(201))
    rota_b = respx.post(f"{URL}/message/sendText/inst-b").mock(return_value=httpx.Response(201))
    notif = criar_notificador(c, sessoes)
    with sessoes() as s, s.begin():
        repo.obter_config_geral(s, c)
        repo.salvar_config_geral(s, {"evolution_instancia": "inst-a", "whatsapp_grupo_admin": "1@g.us"}, AGORA)
    notif.enviar(Destino.ADMIN, "primeira")
    with sessoes() as s, s.begin():
        repo.salvar_config_geral(s, {"evolution_instancia": "inst-b", "whatsapp_grupo_admin": "2@g.us"}, AGORA)
    notif.enviar(Destino.ADMIN, "segunda")
    assert json.loads(rota_a.calls.last.request.read())["number"] == "1@g.us"
    assert json.loads(rota_b.calls.last.request.read())["number"] == "2@g.us"


@respx.mock
def test_sem_instancia_na_tela_nao_envia(config, sessoes, caplog):
    c = config.model_copy(update={"evolution_url": URL, "evolution_api_key": "chave"})
    rota = respx.post(url__startswith=URL)
    with caplog.at_level(logging.WARNING):
        criar_notificador(c, sessoes).enviar(Destino.ADMIN, "x")
    assert rota.call_count == 0
    assert "instância" in caplog.text


def test_erro_ao_ler_a_configuracao_nunca_propaga(caplog):
    def quebrado():
        raise RuntimeError("banco fora")

    with caplog.at_level(logging.ERROR):
        EvolutionNotificador(URL, "chave", quebrado, dormir=lambda _: None).enviar(Destino.ADMIN, "x")
    assert "banco fora" in caplog.text
```

e acrescentar no topo:

```python
from datetime import UTC, datetime

from tcg_sniper.db import repositorio as repo

AGORA = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)
```

Os testes de envio já existentes (`test_envia_para_o_grupo_do_destino`, retries, `test_destino_sem_grupo_nao_envia`) ficam como estão, usando a nova fábrica.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/notificador/test_notificador.py`
Expected: FAIL (`criar_notificador()` recebe 1 argumento; `EvolutionNotificador` espera `instancia`/`grupos`).

- [ ] **Step 3: `EvolutionNotificador` com destinos lidos a cada envio**

Substituir `__init__` e o começo de `enviar` em `src/tcg_sniper/notificador/evolution.py`:

```python
class EvolutionNotificador:
    """Envia texto pela Evolution API. A instância e os grupos são lidos a cada envio (`destinos`),
    para que o que for salvo na tela de Configurações valha na mensagem seguinte."""

    def __init__(
        self,
        url: str,
        api_key: str,
        destinos: Callable[[], tuple[str | None, dict[Destino, str]]],
        cliente: httpx.Client | None = None,
        dormir: Callable[[float], None] = time.sleep,
        tentativas: int = 3,
    ):
        self._url = url.rstrip("/")
        self._api_key = api_key
        self._destinos = destinos
        self._cliente = cliente or httpx.Client(timeout=15)
        self._dormir = dormir
        self._tentativas = tentativas

    def enviar(self, destino: Destino, texto: str) -> None:
        try:
            instancia, grupos = self._destinos()
        except Exception:  # noqa: BLE001 - envio nunca pode interromper a coleta
            log.exception("não consegui ler a configuração do WhatsApp; mensagem descartada: %s", texto)
            return
        if not instancia:
            log.warning("sem instância da Evolution configurada; mensagem descartada: %s", texto)
            return
        grupo = grupos.get(destino)
        if not grupo:
            log.warning("sem grupo configurado para %s; mensagem descartada: %s", destino.value, texto)
            return
        endpoint = f"{self._url}/message/sendText/{instancia}"
        for tentativa in range(1, self._tentativas + 1):
            try:
                resposta = self._cliente.post(
                    endpoint,
                    headers={"apikey": self._api_key},
                    json={"number": grupo, "text": texto},
                )
```

(o resto do laço continua igual.)

- [ ] **Step 4: `criar_notificador(config, sessoes)`**

Substituir `criar_notificador` em `src/tcg_sniper/notificador/__init__.py`:

```python
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
```

com os imports `from sqlalchemy.orm import Session, sessionmaker` e `from tcg_sniper.db import repositorio as repo`.

- [ ] **Step 5: `cli.py`**

Em `src/tcg_sniper/cli.py`, trocar `criar_notificador(config)` por `criar_notificador(config, sessoes)` nos blocos `coletor-liga` e `coletor-amazon`.

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest -q tests/notificador tests/test_cli.py && uv run pytest -q && uv run ruff check .`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/notificador/evolution.py src/tcg_sniper/notificador/__init__.py src/tcg_sniper/cli.py tests/notificador/test_notificador.py
git commit -m "feat: WhatsApp instance and groups are read from the settings screen on every message

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Coletores recarregam a configuração a cada passo

**Files:**
- Modify: `src/tcg_sniper/coletor_liga/agendador.py` (`__init__`, `inicializar`, `tick`)
- Modify: `src/tcg_sniper/coletor_amazon/varredura.py` (`__init__`, `inicializar`, `passo`)
- Test: `tests/coletor_liga/test_agendador.py`, `tests/coletor_amazon/test_varredura.py`

**Interfaces:**
- Consumes: `config_banco.carregar_config(sessoes, config_env) -> Config`, `repositorio.obter_config_liga`, `repositorio.salvar_config_liga`, `repositorio.obter_config_geral`, `repositorio.salvar_config_geral` (Task 1).
- Produces: nada novo; `Agendador` e `VarreduraAmazon` mantêm as assinaturas.

- [ ] **Step 1: Testes do agendador (falham)**

Acrescentar a `tests/coletor_liga/test_agendador.py` (usa `job_ok`, `Relogio`, `local`, `agendador`, `TERCA`, `ONTEM` que já existem no arquivo):

```python
def salvar_liga(sessoes, config, **valores):
    with sessoes() as s, s.begin():
        repo.obter_config_liga(s, config)
        repo.salvar_config_liga(s, valores, local(TERCA, 0))


def test_horario_salvo_na_tela_vale_no_proximo_tick(engine, sessoes, config):
    job_ok(sessoes, ONTEM, 14)
    relogio = Relogio(local(TERCA, 7, 0))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() is None  # alvo sorteado para ~10:00
    salvar_liga(sessoes, config, coleta_hora=time(7, 30), coleta_jitter_min=0)
    relogio.agora = local(TERCA, 7, 31)
    assert a.tick() == "agendado"
    assert chamadas == [True]


def test_horario_mudado_depois_do_job_do_dia_nao_roda_de_novo(engine, sessoes, config):
    job_ok(sessoes, ONTEM, 14)
    relogio = Relogio(local(TERCA, 10, 31))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() == "agendado"
    job_ok(sessoes, TERCA, 10, 31)
    salvar_liga(sessoes, config, coleta_hora=time(11, 0), coleta_jitter_min=0)
    relogio.agora = local(TERCA, 11, 5)
    assert a.tick() is None
    assert chamadas == [True]


def test_job_usa_as_categorias_salvas_na_tela(engine, sessoes, config):
    job_ok(sessoes, ONTEM, 14)
    relogio = Relogio(local(TERCA, 10, 31))
    vistas = []
    a, _ = agendador(engine, sessoes, config, relogio, [])
    a._executor = lambda _incluir: vistas.append(a._config.categorias)
    salvar_liga(sessoes, config, categorias="21,22")
    a.inicializar()
    a.tick()
    assert vistas == [["21", "22"]]
```

`test_alvo_do_dia_sorteado_uma_vez` (já existente) tem que continuar passando sem mudança: com a configuração parada, o alvo do dia é sorteado uma vez só.

- [ ] **Step 2: Teste da varredura (falha)**

Acrescentar a `tests/coletor_amazon/test_varredura.py` (usa `produtos`, `varredura`, `CAPTCHA`, `MEIO_DIA`, `pagina_html` e `repo`, que já existem no arquivo):

```python
def test_host_salvo_na_tela_vale_na_mensagem_do_captcha(engine, sessoes, config):
    _, urls = produtos(sessoes, "a")
    [url] = urls.values()
    with sessoes() as s, s.begin():
        repo.obter_config_geral(s, config)
        repo.salvar_config_geral(s, {"host_publico": "10.9.8.7"}, MEIO_DIA)
    v, _, _, notificador = varredura(engine, sessoes, config, {url: pagina_html(CAPTCHA, url=url)})
    v.passo()
    [(_, texto)] = notificador.mensagens
    assert "http://10.9.8.7:6081/vnc.html" in texto
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest -q tests/coletor_liga/test_agendador.py tests/coletor_amazon`
Expected: os testes novos FAIL (a configuração do banco é ignorada).

- [ ] **Step 4: Agendador**

Em `src/tcg_sniper/coletor_liga/agendador.py`:

- import: `from tcg_sniper.config_banco import carregar_config`
- em `__init__`, trocar `self._config = config` por:

```python
        self._config_env = config
        self._config = config
```

e logo depois de `self._alvos: dict[date, datetime] = {}`:

```python
        # Parâmetros (hora, variação, fuso) com que o alvo de cada dia foi sorteado: se mudarem na
        # tela antes do job do dia, o alvo é sorteado de novo.
        self._parametros_alvo: dict[date, tuple[time, int, str]] = {}
```

- novo método:

```python
    def _recarregar(self) -> None:
        """Valores salvos na tela de Configurações valem a partir do próximo tick (o job em andamento
        termina com os valores com que começou)."""
        self._config = carregar_config(self._sessoes, self._config_env)
```

- primeira linha de `inicializar` e de `tick`: `self._recarregar()`
- em `tick`, trocar o bloco do alvo:

```python
        if hoje not in self._alvos:
            self._alvos[hoje] = alvo_do_dia(
                hoje, self._config.coleta_hora, self._config.coleta_jitter_min, self._config.zona, self._rng
            )
```

por:

```python
        parametros = (self._config.coleta_hora, self._config.coleta_jitter_min, self._config.fuso)
        if self._parametros_alvo.get(hoje) != parametros:
            self._parametros_alvo[hoje] = parametros
            self._alvos[hoje] = alvo_do_dia(
                hoje, self._config.coleta_hora, self._config.coleta_jitter_min, self._config.zona, self._rng
            )
```

(A data `hoje` e `inicio_do_dia` são calculadas depois do `_recarregar`, então usam o fuso salvo. O "não roda duas vezes no dia" continua garantido por `rodou_hoje` e `_datas_tentadas`.)

- [ ] **Step 5: Varredura da Amazon**

Em `src/tcg_sniper/coletor_amazon/varredura.py`:

- import: `from tcg_sniper.config_banco import carregar_config`
- em `__init__`, trocar `self._config = config` por `self._config_env = config` e `self._config = config`
- primeira linha de `inicializar` e de `passo`: `self._config = carregar_config(self._sessoes, self._config_env)`

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest -q tests/coletor_liga tests/coletor_amazon && uv run pytest -q && uv run ruff check .`
Expected: PASS. Se algum teste existente construir dois coletores com `Config` diferentes no mesmo teste, lembre que a primeira leitura grava a linha: ajuste o teste salvando o valor desejado com `repo.salvar_config_*` em vez de trocar o `Config`.

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/coletor_liga/agendador.py src/tcg_sniper/coletor_amazon/varredura.py tests/coletor_liga/test_agendador.py tests/coletor_amazon
git commit -m "feat: collectors reload the settings saved on screen at every step

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Admin com a configuração da tela e Configurações em três seções

**Files:**
- Modify: `src/tcg_sniper/admin/app.py` (dependência por requisição, filtro `data`, Dashboard, Serviços, rotas de Configurações)
- Modify: `src/tcg_sniper/admin/templates/configuracoes.html`
- Test: `tests/admin/test_admin_config_tela.py` (novo), `tests/admin/test_admin_amazon.py` (rotas da Amazon)

**Interfaces:**
- Consumes (Task 1): `carregar_config`, `repositorio.obter_config_geral/obter_config_liga/salvar_config_geral/salvar_config_liga`, `formularios_config.*`, `CATEGORIAS_SELADOS` (de `tcg_sniper.config`). Já existentes: `coletor_amazon.config.CAMPOS/ROTULOS/EXPLICACOES/validar_config/aplicar_config`, `repo_amz.obter_config`.
- Produces: rotas `GET /configuracoes`, `POST /configuracoes/geral`, `POST /configuracoes/liga`, `POST /configuracoes/amazon` (some `POST /configuracoes`).

- [ ] **Step 1: Testes (falham)**

Create `tests/admin/test_admin_config_tela.py`:

```python
import base64
from datetime import UTC, datetime, time

import pytest
from fastapi.testclient import TestClient

from tcg_sniper.admin.app import criar_app
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import TipoColeta

GERAL = {
    "host_publico": "192.168.0.10",
    "fuso": "America/Sao_Paulo",
    "evolution_instancia": "TCG Sniper",
    "whatsapp_grupo_admin": "120363000000000001@g.us",
    "whatsapp_grupo_oportunidades": "",
}
LIGA = {
    "coleta_hora": "07:30",
    "coleta_jitter_min": "15",
    "pausa_min_s": "8",
    "pausa_max_s": "20",
    "limite_falha_pct": "50",
    "categorias": "10,11",
    "url_listagem": "https://liga.test/listagem?categ={categ}",
    "max_cliques": "50",
}


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def test_tela_tem_as_tres_secoes_com_os_valores_salvos(cliente):
    texto = cliente.get("/configuracoes").text
    assert texto.index("Geral") < texto.index("LigaMagic") < texto.index("Amazon")
    assert 'name="host_publico" value="host.test"' in texto
    assert 'name="categorias" value="10,11,12"' in texto
    assert 'name="desconto_min_pct" value="25"' in texto
    assert 'action="/configuracoes/geral"' in texto and 'action="/configuracoes/liga"' in texto
    assert 'action="/configuracoes/amazon"' in texto
    assert "ADMIN_SENHA, VNC_SENHA, EVOLUTION_API_KEY, DATABASE_URL, DIR_DADOS, EVOLUTION_URL" in texto


def test_salvar_geral(cliente, sessoes, config):
    r = cliente.post("/configuracoes/geral", data=GERAL, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/configuracoes?msg=geral"
    with sessoes() as s:
        geral = repo.obter_config_geral(s, config)
    assert (geral.host_publico, geral.whatsapp_grupo_oportunidades) == ("192.168.0.10", None)
    assert "Salvo; vale a partir da próxima coleta ou ciclo." in cliente.get(r.headers["location"]).text


def test_salvar_liga(cliente, sessoes, config):
    r = cliente.post("/configuracoes/liga", data=LIGA, follow_redirects=False)
    assert r.status_code == 303
    with sessoes() as s:
        liga = repo.obter_config_liga(s, config)
    assert (liga.coleta_hora, liga.coleta_jitter_min, liga.categorias) == (time(7, 30), 15, "10,11")


def test_erro_numa_secao_nao_grava_nem_mexe_nas_outras(cliente, sessoes, config):
    cliente.post("/configuracoes/geral", data=GERAL)
    r = cliente.post("/configuracoes/liga", data={**LIGA, "pausa_min_s": "30", "categorias": "abc"})
    assert r.status_code == 400
    assert 'name="categorias" value="abc"' in r.text  # a seção com erro volta com o que foi digitado
    assert 'name="host_publico" value="192.168.0.10"' in r.text  # as outras mostram o que está salvo
    assert "A pausa mínima não pode ser maior que a máxima." in r.text
    with sessoes() as s:
        liga = repo.obter_config_liga(s, config)
    assert (liga.pausa_min_s, liga.categorias) == (8, "10,11,12")


def test_salvar_amazon_na_rota_nova(cliente, sessoes):
    formulario = {
        "url_busca": "https://www.amazon.com.br/s?k={termo}",
        "janela_inicio": "08:00",
        "janela_fim": "22:00",
        "pausa_min_s": "8",
        "pausa_max_s": "20",
        "resultados_por_busca": "10",
        "intervalo_busca_min": "60",
        "max_buscas_hora": "200",
        "limite_falha_pct": "50",
        "desconto_min_pct": "30",
        "realerta_queda_pct": "5",
        "liga_preco_max_idade_h": "48",
        "vendedor_min_positivas_pct": "90",
        "vendedor_min_avaliacoes": "100",
        "vendedor_reavaliar_dias": "7",
    }
    r = cliente.post("/configuracoes/amazon", data=formulario, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/configuracoes?msg=amazon"
    with sessoes() as s:
        assert repo_amz.obter_config(s).desconto_min_pct == 30
    assert cliente.post("/configuracoes", data=formulario).status_code in (404, 405)


def test_dashboard_usa_o_horario_e_o_fuso_salvos(cliente, sessoes, config):
    cliente.post("/configuracoes/liga", data=LIGA)
    cliente.post("/configuracoes/geral", data={**GERAL, "fuso": "Asia/Tokyo"})
    with sessoes() as s, s.begin():
        repo.iniciar_coleta(s, TipoColeta.LISTAGEM, datetime(2026, 10, 15, 3, 0, tzinfo=UTC))
    texto = cliente.get("/").text
    assert "07:30" in texto
    assert "15/10 12:00" in texto  # 03:00 UTC em Tóquio
```

Em `tests/admin/test_admin_amazon.py`: nos três testes de configuração, trocar `cliente.post("/configuracoes", ...)` por `cliente.post("/configuracoes/amazon", ...)` e a asserção `"Configurações salvas"` por `"Salvo; vale a partir da próxima coleta ou ciclo."`.

Confira o formato exato de data do filtro `data` (`formatar_data` em `tcg_sniper/formatacao.py`) e ajuste a string `"15/10 12:00"` do último teste ao formato real, mantendo a hora 12:00 (Tóquio).

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/admin/test_admin_config_tela.py tests/admin/test_admin_amazon.py`
Expected: FAIL (rotas novas não existem; Dashboard usa o `.env`).

- [ ] **Step 3: Configuração por requisição e filtro `data`**

Em `src/tcg_sniper/admin/app.py`:

- imports: `from jinja2 import pass_context`, `from tcg_sniper.config import CATEGORIAS_SELADOS`, `from tcg_sniper.config_banco import carregar_config`, `from tcg_sniper.admin import formularios_config as form_cfg`.
- dentro de `criar_app`, depois de `autenticar`:

```python
    def config_da_requisicao(request: Request) -> None:
        """Configuração efetiva (.env + tela) desta requisição, em `request.state.config`."""
        request.state.config = carregar_config(sessoes, config)
```

- `app = FastAPI(title="TCG Sniper", dependencies=[Depends(autenticar), Depends(config_da_requisicao)])`
- trocar o filtro `data`:

```python
    @pass_context
    def _data(contexto, dt):
        return formatar_data(dt, contexto["request"].state.config.zona)

    templates.env.filters["data"] = _data
```

- Dashboard: no começo do handler, `efetiva = request.state.config`; trocar `config.zona` por `efetiva.zona`, `config.coleta_hora` por `efetiva.coleta_hora` e `config.coleta_jitter_min` por `efetiva.coleta_jitter_min`.
- Serviços: `"host": config.host_publico` vira `"host": request.state.config.host_publico`.
- Depois disso, `grep -n "config\." src/tcg_sniper/admin/app.py` só pode mostrar `config.admin_senha` e a chamada `carregar_config(sessoes, config)`.

- [ ] **Step 4: Rotas de Configurações**

Substituir `_tela_configuracoes`, `configuracoes` e `salvar_configuracoes` por:

```python
    MENSAGEM_CONFIG = "Salvo; vale a partir da próxima coleta ou ciclo."

    def _texto(valor) -> str:
        if valor is None:
            return ""
        if isinstance(valor, time):
            return valor.strftime("%H:%M")
        if isinstance(valor, float):
            return f"{valor:g}"
        return str(valor)

    def _salvos() -> dict[str, dict[str, str]]:
        with sessoes() as s, s.begin():
            geral = repo.obter_config_geral(s, config)
            liga = repo.obter_config_liga(s, config)
            amazon = repo_amz.obter_config(s)
            return {
                "geral": {c: _texto(getattr(geral, c)) for c in form_cfg.CAMPOS_GERAL},
                "liga": {c: _texto(getattr(liga, c)) for c in form_cfg.CAMPOS_LIGA},
                "amazon": {c: _texto(getattr(amazon, c)) for c in CAMPOS},
            }

    def _tela_configuracoes(
        request: Request,
        msg: str = "",
        secao_com_erro: str | None = None,
        digitados: dict[str, str] | None = None,
        erros: dict[str, str] | None = None,
    ):
        valores = _salvos()
        if secao_com_erro is not None:
            valores[secao_com_erro] = digitados or {}
        secoes = [
            ("geral", "Geral", form_cfg.CAMPOS_GERAL, form_cfg.ROTULOS_GERAL, form_cfg.EXPLICACOES_GERAL),
            ("liga", "LigaMagic", form_cfg.CAMPOS_LIGA, form_cfg.ROTULOS_LIGA, form_cfg.EXPLICACOES_LIGA),
            ("amazon", "Amazon", CAMPOS, ROTULOS, EXPLICACOES),
        ]
        return templates.TemplateResponse(
            request,
            "configuracoes.html",
            {
                "secoes": [
                    {
                        "id": id_,
                        "titulo": titulo,
                        "campos": campos,
                        "rotulos": rotulos,
                        "explicacoes": explicacoes,
                        "valores": valores[id_],
                        "erros": (erros or {}) if id_ == secao_com_erro else {},
                    }
                    for id_, titulo, campos, rotulos, explicacoes in secoes
                ],
                "mensagem": MENSAGEM_CONFIG if msg in ("geral", "liga", "amazon") else None,
                "categorias_padrao": ",".join(CATEGORIAS_SELADOS),
            },
            status_code=status.HTTP_400_BAD_REQUEST if secao_com_erro else status.HTTP_200_OK,
        )

    @app.get("/configuracoes", response_class=HTMLResponse)
    def configuracoes(request: Request, msg: str = ""):
        return _tela_configuracoes(request, msg)

    async def _salvar_secao(request: Request, secao: str, campos, validar, gravar):
        formulario = await ler_formulario(request)
        valores, erros = validar(formulario)
        if erros:
            digitados = {campo: formulario.get(campo, "") for campo in campos}
            return _tela_configuracoes(request, secao_com_erro=secao, digitados=digitados, erros=erros)
        with sessoes() as s, s.begin():
            gravar(s, valores)
        return RedirectResponse(f"/configuracoes?msg={secao}", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/configuracoes/geral", response_class=HTMLResponse)
    async def salvar_geral(request: Request):
        def gravar(s, valores):
            repo.obter_config_geral(s, config)
            repo.salvar_config_geral(s, valores, repo.agora_utc())

        return await _salvar_secao(request, "geral", form_cfg.CAMPOS_GERAL, form_cfg.validar_geral, gravar)

    @app.post("/configuracoes/liga", response_class=HTMLResponse)
    async def salvar_liga(request: Request):
        def gravar(s, valores):
            repo.obter_config_liga(s, config)
            repo.salvar_config_liga(s, valores, repo.agora_utc())

        return await _salvar_secao(request, "liga", form_cfg.CAMPOS_LIGA, form_cfg.validar_liga, gravar)

    @app.post("/configuracoes/amazon", response_class=HTMLResponse)
    async def salvar_amazon(request: Request):
        def gravar(s, valores):
            aplicar_config(s, valores, repo.agora_utc())

        return await _salvar_secao(request, "amazon", CAMPOS, validar_config, gravar)
```

(`CAMPOS`, `ROTULOS`, `EXPLICACOES`, `validar_config`, `aplicar_config` já são importados de `tcg_sniper.coletor_amazon.config` em `app.py`; `time` já é importado de `datetime`.)

- [ ] **Step 5: Template**

Substituir `src/tcg_sniper/admin/templates/configuracoes.html` por:

```html
{% extends "base.html" %}
{% block titulo %}Configurações · TCG Sniper{% endblock %}
{% block conteudo %}
<h2>Configurações</h2>
<p>As mudanças valem a partir da próxima coleta ou ciclo, sem reiniciar nada.</p>
{% if mensagem %}<p><mark>{{ mensagem }}</mark></p>{% endif %}
{% for secao in secoes %}
<article id="{{ secao.id }}">
  <header><strong>{{ secao.titulo }}</strong></header>
  {% if secao.erros %}<div class="pausado">Nada foi salvo. Corrija os campos marcados.</div>{% endif %}
  <form method="post" action="/configuracoes/{{ secao.id }}">
    {% for campo in secao.campos %}
    <label>{{ secao.rotulos[campo] }}
      <input id="{{ secao.id }}-{{ campo }}" name="{{ campo }}" value="{{ secao.valores[campo] }}"{% if campo in secao.erros %} aria-invalid="true"{% endif %}>
      <small>{{ secao.erros[campo] if campo in secao.erros else secao.explicacoes[campo] }}</small>
      {% if secao.id == "liga" and campo == "categorias" %}
      <small>Padrão: {{ categorias_padrao }} · <a href="#" onclick="document.getElementById('liga-categorias').value='{{ categorias_padrao }}'; return false;">restaurar padrão</a> (depois clique em Salvar)</small>
      {% endif %}
    </label>
    {% endfor %}
    <button>Salvar {{ secao.titulo }}</button>
  </form>
</article>
{% endfor %}
<footer><small>Senhas, banco e chave da Evolution ficam no .env: ADMIN_SENHA, VNC_SENHA, EVOLUTION_API_KEY, DATABASE_URL, DIR_DADOS, EVOLUTION_URL.</small></footer>
{% endblock %}
```

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest -q tests/admin && uv run pytest -q && uv run ruff check .`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/admin/app.py src/tcg_sniper/admin/templates/configuracoes.html tests/admin/test_admin_config_tela.py tests/admin/test_admin_amazon.py
git commit -m "feat: settings screen with General, LigaMagic and Amazon sections; admin uses the saved settings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Documentação

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `src/tcg_sniper/config.py` (só o comentário da classe)

**Interfaces:** nenhuma.

- [ ] **Step 1: `.env.example`**

Remover as variáveis migradas e os comentários delas: `HOST_PUBLICO`, `EVOLUTION_INSTANCIA`, `WHATSAPP_GRUPO_ADMIN`, `WHATSAPP_GRUPO_OPORTUNIDADES`, `FUSO`, `COLETA_HORA`, `COLETA_JITTER_MIN`, `PAUSA_MIN_S`, `PAUSA_MAX_S`, `LIMITE_FALHA_PCT`, `LIGA_CATEGORIAS`, `LIGA_URL_LISTAGEM`, `LIGA_MAX_CLIQUES` (as seções "Agendamento e ritmo da coleta" e "LigaMagic" somem inteiras). No cabeçalho, a lista "Antes de subir, troque obrigatoriamente" fica `ADMIN_SENHA, VNC_SENHA, EVOLUTION_API_KEY`, e o bloco sobre `WHATSAPP_GRUPO_*` vira:

```
# IP deste PC, instância e grupos do WhatsApp, horário e categorias da coleta e o resto da
# operação ficam em Configurações no admin (http://<IP deste PC>:8000/configuracoes).
# Na primeira vez que o sistema sobe, ele copia para lá os valores que ainda estiverem neste
# arquivo; depois disso, essas variáveis são ignoradas e podem ser apagadas do seu .env.
```

- [ ] **Step 2: README**

`grep -n "HOST_PUBLICO\|EVOLUTION_INSTANCIA\|WHATSAPP_GRUPO\|FUSO\|COLETA_HORA\|COLETA_JITTER\|PAUSA_M\|LIMITE_FALHA\|LIGA_CATEGORIAS\|LIGA_URL\|LIGA_MAX" README.md` e, em cada ocorrência, trocar a instrução de editar o `.env` por "em **Configurações** no admin" (seção Geral ou LigaMagic). Em especial:

- passo de conectar o WhatsApp (grupos): colar o ID do grupo em Configurações → Geral, sem reiniciar nada;
- a frase da Amazon "Tudo isso se ajusta em **Configurações**" passa a valer para Geral, LigaMagic e Amazon;
- a linha **Configurações** da tabela de telas do admin: "Três seções (Geral, LigaMagic, Amazon); cada uma salva sozinha e vale a partir da próxima coleta ou ciclo. Senhas, banco e chave da Evolution continuam no `.env`."

- [ ] **Step 3: Comentário do `Config`**

Em `src/tcg_sniper/config.py`, acrescentar docstring à classe `Config`:

```python
    """Valores do .env. Os campos de operação (host, fuso, WhatsApp e coleta da Liga) só valem como
    valor inicial: depois da primeira leitura vêm das tabelas config_geral e config_liga
    (`config_banco.carregar_config`)."""
```

- [ ] **Step 4: Conferir e commitar**

Run: `uv run pytest -q && uv run ruff check .`
Expected: PASS.

```bash
git add .env.example README.md src/tcg_sniper/config.py
git commit -m "docs: operational settings live on the settings screen; .env keeps only secrets and infrastructure

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
