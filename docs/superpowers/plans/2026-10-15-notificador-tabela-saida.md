# Notificador com tabela de saída Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nenhum alerta se perde quando a Evolution ou o WhatsApp ficam fora: os serviços gravam as mensagens em `mensagem_saida` e um serviço `notificador` envia com tentativas, validade e registro, visível no admin.

**Architecture:** `NotificadorFila` (implementa `Notificador`) só grava a linha `pendente`. O serviço `notificador` (container novo) roda um ciclo a cada 5 s: pega até 20 pendentes vencidas com `FOR UPDATE SKIP LOCKED`, decide (expirar, esperar configuração, enviar uma vez) e grava o resultado. O admin ganha a tela Mensagens (reenviar/descartar), o cartão e o aviso no Dashboard e o cartão em Serviços.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, httpx, FastAPI + Jinja2 + Pico CSS, Postgres 16, pytest + respx.

**Spec:** `docs/superpowers/specs/2026-10-15-notificador-tabela-saida-design.md`

## Global Constraints

- Situações (`status`): `pendente`, `enviada`, `falha`, `expirada`, `descartada`. Destinos: `admin`, `oportunidades`.
- Ciclo a cada 5 s; até 20 mensagens por ciclo, por `criada_em`; `FOR UPDATE SKIP LOCKED`.
- Oportunidade mais velha que `validade_oportunidade_h` (1–48, padrão 6, em Configurações → Geral) e sem `ignorar_validade` → `expirada`. Mensagens do admin nunca expiram.
- Sem chave da Evolution (vazia ou `trocar-esta-chave`), sem URL, sem instância ou sem grupo do destino → continua `pendente`, nova tentativa em 1 min, `tentativas` não muda, `ultimo_erro` diz o que falta.
- Envio: uma tentativa por ciclo, timeout 15 s. 2xx → `enviada`. Rede/5xx → `tentativas + 1`, espera `min(2^(tentativas−1), 30)` min, sem limite. 4xx → `tentativas + 1`; na 5ª, `falha`.
- Limpeza diária: apaga `enviada`, `expirada`, `descartada` com `criada_em` de mais de 30 dias. `falha` e `pendente` nunca são apagadas.
- Reenviar (só `falha`/`expirada`): `pendente`, `tentativas = 0`, `proxima_tentativa_em = agora`, `ignorar_validade = true`, `ultimo_erro` nulo. Descartar (só `pendente`/`falha`/`expirada`): `descartada`. Outra situação → 409; inexistente → 404.
- Aviso no Dashboard quando houver `falha` ou `pendente` criada há mais de 30 min. Serviços: "rodando" se `ultimo_ciclo_em` < 1 min; "parado desde <data>"; "nunca rodou".
- `NotificadorFila.enviar` nunca lança exceção (contrato do `Notificador`).
- A instância vai no caminho da Evolution codificada: `quote(instancia, safe="")`.
- Menu: Dashboard · Serviços · Catálogo · Casamentos · Ofertas · Mensagens · Configurações.
- Testes com `DATABASE_URL_TESTE` (Postgres): `uv run pytest -q` e `uv run ruff check .`.
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Banco fora do ar quando um coletor chama `enviar`: o coletor não pode cair (log com o texto). Teste na Task 2.
2. Evolution respondendo lento ou travando: o timeout de 15 s vale e o ciclo segue para a próxima mensagem. Teste na Task 2 (`httpx.TimeoutException` tratado como transitório).
3. Erro inesperado dentro de um ciclo (ex.: banco caiu no meio): o laço do serviço não morre. Teste na Task 2.
4. Grupo preenchido depois que as mensagens acumularam: elas saem no ciclo seguinte ao minuto de espera, sem terem gastado tentativas. Teste na Task 2.
5. Reenviar uma oportunidade expirada: sai mesmo vencida. Testes nas Tasks 1 (repositório) e 2 (ciclo).

---

## Ondas (para execução paralela)

- Onda A: Task 1.
- Onda B (depois da 1, em paralelo, arquivos disjuntos): Task 2 (`notificador/*`, `cli.py`, `docker-compose.yml`, testes do notificador e do CLI) e Task 3 (`admin/*`, `README.md`, testes do admin).

---

### Task 1: Tabelas, repositório de mensagens e validade em Configurações

**Files:**
- Modify: `src/tcg_sniper/db/models.py` (enum `StatusMensagem`, classes `MensagemSaida` e `EstadoNotificador`, coluna `ConfigGeral.validade_oportunidade_h`)
- Create: `src/tcg_sniper/db/migrations/versions/c3d8a1f6e2b5_mensagem_saida.py`
- Create: `src/tcg_sniper/db/repositorio_mensagens.py`
- Modify: `src/tcg_sniper/admin/formularios_config.py` (campo `validade_oportunidade_h` na seção Geral)
- Test: `tests/db/test_repositorio_mensagens.py`, `tests/admin/test_formularios_config.py`, `tests/db/test_migracao.py`

**Interfaces:**
- Produces:
  - `models.StatusMensagem` (StrEnum: `PENDENTE="pendente"`, `ENVIADA="enviada"`, `FALHA="falha"`, `EXPIRADA="expirada"`, `DESCARTADA="descartada"`)
  - `models.MensagemSaida` (colunas da spec), `models.EstadoNotificador` (`id`, `ultimo_ciclo_em`), `ConfigGeral.validade_oportunidade_h: int`
  - `repositorio_mensagens.enfileirar(s, destino: str, texto: str, agora: datetime) -> MensagemSaida`
  - `repositorio_mensagens.lote_pendente(s, agora: datetime, limite: int = 20) -> list[MensagemSaida]`
  - `repositorio_mensagens.registrar_ciclo(s, agora: datetime) -> None`
  - `repositorio_mensagens.limpar_antigas(s, agora: datetime, dias: int = 30) -> int`
  - `repositorio_mensagens.reenviar(s, mensagem_id: int, agora: datetime) -> None`, `descartar(s, mensagem_id: int, agora: datetime) -> None`
  - `repositorio_mensagens.MensagemNaoEncontrada`, `AcaoInvalida` (exceções)

- [ ] **Step 1: Testes do repositório (falham)**

Create `tests/db/test_repositorio_mensagens.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import EstadoNotificador, MensagemSaida, StatusMensagem

AGORA = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def test_enfileirar_cria_pendente_vencida(s):
    m = repo_msg.enfileirar(s, "admin", "olá", AGORA)
    assert (m.status, m.tentativas, m.proxima_tentativa_em, m.criada_em) == (
        StatusMensagem.PENDENTE, 0, AGORA, AGORA
    )
    assert (m.ignorar_validade, m.ultimo_erro, m.enviada_em) == (False, None, None)


def test_lote_pendente_so_vencidas_por_ordem_de_criacao_com_limite(s):
    velha = repo_msg.enfileirar(s, "admin", "1", AGORA - timedelta(minutes=10))
    nova = repo_msg.enfileirar(s, "oportunidades", "2", AGORA - timedelta(minutes=5))
    futura = repo_msg.enfileirar(s, "admin", "3", AGORA - timedelta(minutes=20))
    futura.proxima_tentativa_em = AGORA + timedelta(minutes=1)
    enviada = repo_msg.enfileirar(s, "admin", "4", AGORA - timedelta(minutes=30))
    enviada.status = StatusMensagem.ENVIADA
    s.flush()
    assert [m.id for m in repo_msg.lote_pendente(s, AGORA)] == [velha.id, nova.id]
    assert [m.id for m in repo_msg.lote_pendente(s, AGORA, limite=1)] == [velha.id]


def test_lote_pendente_pula_linhas_travadas_por_outra_sessao(engine):
    with Session(engine) as s, s.begin():
        mid = repo_msg.enfileirar(s, "admin", "concorrente", AGORA).id
    try:
        with Session(engine) as a, a.begin():
            assert mid in [m.id for m in repo_msg.lote_pendente(a, AGORA)]
            with Session(engine) as b, b.begin():
                assert mid not in [m.id for m in repo_msg.lote_pendente(b, AGORA)]
    finally:
        with Session(engine) as s, s.begin():
            s.execute(delete(MensagemSaida).where(MensagemSaida.id == mid))


def test_registrar_ciclo(s):
    assert s.get(EstadoNotificador, 1).ultimo_ciclo_em is None
    repo_msg.registrar_ciclo(s, AGORA)
    assert s.get(EstadoNotificador, 1, populate_existing=True).ultimo_ciclo_em == AGORA


def test_limpar_antigas_apaga_so_as_resolvidas_de_mais_de_30_dias(s):
    velho = AGORA - timedelta(days=31)
    ids = {}
    for status in StatusMensagem:
        m = repo_msg.enfileirar(s, "admin", status.value, velho)
        m.status = status
        ids[status] = m.id
    recente = repo_msg.enfileirar(s, "admin", "recente", AGORA - timedelta(days=29))
    recente.status = StatusMensagem.ENVIADA
    s.flush()
    assert repo_msg.limpar_antigas(s, AGORA) == 3
    restantes = set(s.scalars(select(MensagemSaida.id)))
    assert ids[StatusMensagem.PENDENTE] in restantes and ids[StatusMensagem.FALHA] in restantes
    assert recente.id in restantes
    assert not {ids[StatusMensagem.ENVIADA], ids[StatusMensagem.EXPIRADA], ids[StatusMensagem.DESCARTADA]} & restantes


@pytest.mark.parametrize("status", [StatusMensagem.FALHA, StatusMensagem.EXPIRADA])
def test_reenviar(s, status):
    m = repo_msg.enfileirar(s, "oportunidades", "x", AGORA - timedelta(hours=10))
    m.status, m.tentativas, m.ultimo_erro = status, 5, "HTTP 400"
    s.flush()
    repo_msg.reenviar(s, m.id, AGORA)
    s.refresh(m)
    assert (m.status, m.tentativas, m.proxima_tentativa_em, m.ignorar_validade, m.ultimo_erro) == (
        StatusMensagem.PENDENTE, 0, AGORA, True, None
    )


@pytest.mark.parametrize("status", [StatusMensagem.PENDENTE, StatusMensagem.FALHA, StatusMensagem.EXPIRADA])
def test_descartar(s, status):
    m = repo_msg.enfileirar(s, "admin", "x", AGORA)
    m.status = status
    s.flush()
    repo_msg.descartar(s, m.id, AGORA)
    s.refresh(m)
    assert m.status is StatusMensagem.DESCARTADA


@pytest.mark.parametrize(
    ("acao", "status"),
    [
        (repo_msg.reenviar, StatusMensagem.ENVIADA),
        (repo_msg.reenviar, StatusMensagem.PENDENTE),
        (repo_msg.reenviar, StatusMensagem.DESCARTADA),
        (repo_msg.descartar, StatusMensagem.ENVIADA),
        (repo_msg.descartar, StatusMensagem.DESCARTADA),
    ],
)
def test_acao_que_nao_vale_para_a_situacao(s, acao, status):
    m = repo_msg.enfileirar(s, "admin", "x", AGORA)
    m.status = status
    s.flush()
    with pytest.raises(repo_msg.AcaoInvalida):
        acao(s, m.id, AGORA)


def test_mensagem_inexistente(s):
    with pytest.raises(repo_msg.MensagemNaoEncontrada):
        repo_msg.reenviar(s, 999_999, AGORA)
```

Em `tests/db/test_migracao.py`, acrescentar (e importar `EstadoNotificador`, `ConfigGeral` se ainda não estiver importado):

```python
def test_migracao_cria_estado_do_notificador(s):
    assert s.get(EstadoNotificador, 1).ultimo_ciclo_em is None


def test_validade_padrao_na_config_geral(s, config):
    from tcg_sniper.db import repositorio as repo

    assert repo.obter_config_geral(s, config).validade_oportunidade_h == 6
```

Em `tests/admin/test_formularios_config.py`: acrescentar `"validade_oportunidade_h": "6"` ao dicionário `GERAL`, a chave `"validade_oportunidade_h": 6` ao dicionário esperado de `test_geral_valido`, e os casos `("validade_oportunidade_h", "0")`, `("validade_oportunidade_h", "49")`, `("validade_oportunidade_h", "abc")` à parametrização de `test_geral_invalido`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/db/test_repositorio_mensagens.py tests/db/test_migracao.py tests/admin/test_formularios_config.py`
Expected: FAIL/ERROR (`repositorio_mensagens`, `StatusMensagem`, `EstadoNotificador` não existem).

- [ ] **Step 3: Modelos**

Em `src/tcg_sniper/db/models.py`:

- depois de `class Envio(enum.StrEnum)`:

```python
class StatusMensagem(enum.StrEnum):
    PENDENTE = "pendente"
    ENVIADA = "enviada"
    FALHA = "falha"  # 4xx cinco vezes: precisa de alguém olhar (instância, grupo)
    EXPIRADA = "expirada"  # oportunidade que passou da validade sem sair
    DESCARTADA = "descartada"  # descartada no admin
```

- em `ConfigGeral`, depois de `whatsapp_grupo_oportunidades`:

```python
    validade_oportunidade_h: Mapped[int] = mapped_column(Integer, server_default="6")
```

e acrescentar a `__table_args__` de `ConfigGeral`:

```python
        CheckConstraint("validade_oportunidade_h BETWEEN 1 AND 48", name="ck_config_geral_validade"),
```

- no fim do arquivo:

```python
class MensagemSaida(Base):
    """Tabela de saída do WhatsApp: os serviços gravam aqui (`NotificadorFila`) e o serviço
    `notificador` envia, com tentativas, validade e registro do resultado."""

    __tablename__ = "mensagem_saida"
    __table_args__ = (
        CheckConstraint("destino IN ('admin', 'oportunidades')", name="ck_mensagem_saida_destino"),
        CheckConstraint("texto <> ''", name="ck_mensagem_saida_texto"),
        CheckConstraint("tentativas >= 0", name="ck_mensagem_saida_tentativas"),
        Index("ix_mensagem_saida_fila", "status", "proxima_tentativa_em"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    destino: Mapped[str] = mapped_column(Text)
    texto: Mapped[str] = mapped_column(Text)
    status: Mapped[StatusMensagem] = mapped_column(_enum(StatusMensagem, "status_mensagem"))
    tentativas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    proxima_tentativa_em: Mapped[datetime] = mapped_column(DATA)
    ultimo_erro: Mapped[str | None] = mapped_column(Text)
    ignorar_validade: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    criada_em: Mapped[datetime] = mapped_column(DATA)
    atualizado_em: Mapped[datetime] = mapped_column(DATA)
    enviada_em: Mapped[datetime | None] = mapped_column(DATA)


class EstadoNotificador(Base):
    """Uma linha (id 1): quando o serviço notificador terminou o último ciclo (Serviços mostra se está vivo)."""

    __tablename__ = "estado_notificador"
    __table_args__ = (CheckConstraint("id = 1", name="ck_estado_notificador_linha_unica"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    ultimo_ciclo_em: Mapped[datetime | None] = mapped_column(DATA)
```

(`Boolean`, `Index`, `Integer`, `Text`, `CheckConstraint`, `_enum` e `DATA` já existem no módulo.)

- [ ] **Step 4: Migração**

Create `src/tcg_sniper/db/migrations/versions/c3d8a1f6e2b5_mensagem_saida.py`:

```python
"""mensagem_saida, estado_notificador e validade das oportunidades

Revision ID: c3d8a1f6e2b5
Revises: b7c1e5f0a2d4
Create Date: 2026-10-15 18:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d8a1f6e2b5"
down_revision: Union[str, Sequence[str], None] = "b7c1e5f0a2d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DATA = sa.DateTime(timezone=True)
STATUS = ("pendente", "enviada", "falha", "expirada", "descartada")


def upgrade() -> None:
    op.create_table(
        "mensagem_saida",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("destino", sa.Text(), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*STATUS, name="status_mensagem", native_enum=False, create_constraint=True, length=20),
            nullable=False,
        ),
        sa.Column("tentativas", sa.Integer(), server_default="0", nullable=False),
        sa.Column("proxima_tentativa_em", DATA, nullable=False),
        sa.Column("ultimo_erro", sa.Text(), nullable=True),
        sa.Column("ignorar_validade", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("criada_em", DATA, nullable=False),
        sa.Column("atualizado_em", DATA, nullable=False),
        sa.Column("enviada_em", DATA, nullable=True),
        sa.CheckConstraint("destino IN ('admin', 'oportunidades')", name="ck_mensagem_saida_destino"),
        sa.CheckConstraint("texto <> ''", name="ck_mensagem_saida_texto"),
        sa.CheckConstraint("tentativas >= 0", name="ck_mensagem_saida_tentativas"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mensagem_saida_fila", "mensagem_saida", ["status", "proxima_tentativa_em"])
    op.create_table(
        "estado_notificador",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("ultimo_ciclo_em", DATA, nullable=True),
        sa.CheckConstraint("id = 1", name="ck_estado_notificador_linha_unica"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO estado_notificador (id) VALUES (1)")
    op.add_column(
        "config_geral", sa.Column("validade_oportunidade_h", sa.Integer(), server_default="6", nullable=False)
    )
    op.create_check_constraint("ck_config_geral_validade", "config_geral", "validade_oportunidade_h BETWEEN 1 AND 48")


def downgrade() -> None:
    op.drop_constraint("ck_config_geral_validade", "config_geral", type_="check")
    op.drop_column("config_geral", "validade_oportunidade_h")
    op.drop_table("estado_notificador")
    op.drop_index("ix_mensagem_saida_fila", table_name="mensagem_saida")
    op.drop_table("mensagem_saida")
```

(Confira como a migração `7d3f1a2b9c4e` declara as colunas de enum e use o mesmo jeito se for diferente; o teste `test_migracao_igual_aos_modelos` compara os dois.)

- [ ] **Step 5: Repositório de mensagens**

Create `src/tcg_sniper/db/repositorio_mensagens.py`:

```python
"""Tabela de saída do WhatsApp (`mensagem_saida`) e o estado do serviço notificador."""

from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from tcg_sniper.db.models import EstadoNotificador, MensagemSaida, StatusMensagem

RESOLVIDAS = (StatusMensagem.ENVIADA, StatusMensagem.EXPIRADA, StatusMensagem.DESCARTADA)
REENVIAVEIS = (StatusMensagem.FALHA, StatusMensagem.EXPIRADA)
DESCARTAVEIS = (StatusMensagem.PENDENTE, StatusMensagem.FALHA, StatusMensagem.EXPIRADA)


class MensagemNaoEncontrada(Exception):
    pass


class AcaoInvalida(Exception):
    """A ação não vale para a situação atual da mensagem (ex.: reenviar uma já enviada)."""


def enfileirar(s: Session, destino: str, texto: str, agora: datetime) -> MensagemSaida:
    mensagem = MensagemSaida(
        destino=destino,
        texto=texto,
        status=StatusMensagem.PENDENTE,
        tentativas=0,
        proxima_tentativa_em=agora,
        ignorar_validade=False,
        criada_em=agora,
        atualizado_em=agora,
    )
    s.add(mensagem)
    s.flush()
    return mensagem


def lote_pendente(s: Session, agora: datetime, limite: int = 20) -> list[MensagemSaida]:
    """Pendentes vencidas, das mais antigas, travadas para esta transação. Linhas travadas por
    outra transação são puladas (`SKIP LOCKED`), então dois envios nunca pegam a mesma."""
    consulta = (
        select(MensagemSaida)
        .where(MensagemSaida.status == StatusMensagem.PENDENTE, MensagemSaida.proxima_tentativa_em <= agora)
        .order_by(MensagemSaida.criada_em, MensagemSaida.id)
        .limit(limite)
        .with_for_update(skip_locked=True)
    )
    return list(s.scalars(consulta))


def registrar_ciclo(s: Session, agora: datetime) -> None:
    s.execute(update(EstadoNotificador).where(EstadoNotificador.id == 1).values(ultimo_ciclo_em=agora))
    s.flush()


def limpar_antigas(s: Session, agora: datetime, dias: int = 30) -> int:
    """Apaga enviadas, expiradas e descartadas criadas há mais de `dias`. Falhas e pendentes ficam."""
    resultado = s.execute(
        delete(MensagemSaida).where(
            MensagemSaida.status.in_(RESOLVIDAS), MensagemSaida.criada_em < agora - timedelta(days=dias)
        )
    )
    return resultado.rowcount


def _obter(s: Session, mensagem_id: int) -> MensagemSaida:
    mensagem = s.get(MensagemSaida, mensagem_id, with_for_update=True)
    if mensagem is None:
        raise MensagemNaoEncontrada(mensagem_id)
    return mensagem


def reenviar(s: Session, mensagem_id: int, agora: datetime) -> None:
    """Falha ou expirada volta para a fila agora, sem tentativas e ignorando a validade."""
    mensagem = _obter(s, mensagem_id)
    if mensagem.status not in REENVIAVEIS:
        raise AcaoInvalida(f"não dá para reenviar uma mensagem {mensagem.status.value}")
    mensagem.status = StatusMensagem.PENDENTE
    mensagem.tentativas = 0
    mensagem.proxima_tentativa_em = agora
    mensagem.ignorar_validade = True
    mensagem.ultimo_erro = None
    mensagem.atualizado_em = agora
    s.flush()


def descartar(s: Session, mensagem_id: int, agora: datetime) -> None:
    mensagem = _obter(s, mensagem_id)
    if mensagem.status not in DESCARTAVEIS:
        raise AcaoInvalida(f"não dá para descartar uma mensagem {mensagem.status.value}")
    mensagem.status = StatusMensagem.DESCARTADA
    mensagem.atualizado_em = agora
    s.flush()
```

- [ ] **Step 6: Validade na seção Geral**

Em `src/tcg_sniper/admin/formularios_config.py`:

- `CAMPOS_GERAL`: acrescentar `"validade_oportunidade_h"` no fim.
- `ROTULOS_GERAL["validade_oportunidade_h"] = "Validade das oportunidades (h)"`
- `EXPLICACOES_GERAL["validade_oportunidade_h"] = "Oportunidade que não saiu em até tantas horas, por o WhatsApp estar fora, é descartada como expirada."`
- em `validar_geral`, antes do `return`:

```python
    texto = (campos.get("validade_oportunidade_h") or "").strip()
    if not (texto.isascii() and texto.isdecimal()) or len(texto) > 3 or not 1 <= int(texto) <= 48:
        erros["validade_oportunidade_h"] = "Informe um número inteiro de horas entre 1 e 48."
    else:
        valores["validade_oportunidade_h"] = int(texto)
```

(O `int(texto)` só roda quando `texto` é decimal ASCII de até 3 dígitos, por causa do `or` em curto-circuito.)

A tela de Configurações monta a seção Geral a partir de `CAMPOS_GERAL` e lê os valores da `ConfigGeral`, então o campo aparece sem mexer no admin.

- [ ] **Step 7: Rodar e ver passar**

Run: `uv run pytest -q tests/db tests/admin && uv run pytest -q && uv run ruff check .`
Expected: PASS (inclusive `test_migracao_igual_aos_modelos`). Se algum teste de admin que posta a seção Geral falhar por faltar `validade_oportunidade_h` no formulário, acrescente `"validade_oportunidade_h": "6"` ao dicionário de formulário desse teste.

- [ ] **Step 8: Commit**

```bash
git add src/tcg_sniper/db/models.py src/tcg_sniper/db/migrations/versions/c3d8a1f6e2b5_mensagem_saida.py src/tcg_sniper/db/repositorio_mensagens.py src/tcg_sniper/admin/formularios_config.py tests/db/test_repositorio_mensagens.py tests/db/test_migracao.py tests/admin
git commit -m "feat: WhatsApp outbox table, notifier state and opportunity validity setting

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `NotificadorFila` e o serviço `notificador`

**Files:**
- Create: `src/tcg_sniper/notificador/fila.py`
- Create: `src/tcg_sniper/notificador/servico.py`
- Modify: `src/tcg_sniper/notificador/evolution.py` (vira só `enviar_uma_vez`)
- Modify: `src/tcg_sniper/notificador/__init__.py` (`criar_notificador` devolve `NotificadorFila`)
- Delete: `src/tcg_sniper/notificador/log.py`
- Modify: `src/tcg_sniper/cli.py` (subcomando `notificador`)
- Modify: `docker-compose.yml` (serviço `notificador`)
- Test: `tests/notificador/test_notificador.py` (reescrito), `tests/notificador/test_servico.py` (novo), `tests/test_cli.py`

**Interfaces:**
- Consumes (Task 1): `repositorio_mensagens.enfileirar/lote_pendente/registrar_ciclo/limpar_antigas`, `models.StatusMensagem`, `MensagemSaida`, `ConfigGeral.validade_oportunidade_h`; `repositorio.obter_config_geral(s, padrao)`, `repositorio.salvar_config_geral(s, valores, agora)`.
- Produces:
  - `NotificadorFila(sessoes: sessionmaker[Session], relogio: Callable[[], datetime] | None = None)` com `enviar(destino: Destino, texto: str) -> None`
  - `criar_notificador(config: Config, sessoes: sessionmaker[Session]) -> Notificador` (sempre `NotificadorFila`)
  - `evolution.Resultado` (StrEnum `OK`, `TRANSITORIO`, `DEFINITIVO`), `evolution.enviar_uma_vez(cliente, url, chave, instancia, grupo, texto) -> tuple[Resultado, str | None]`
  - `servico.ServicoNotificador(sessoes, config_env, cliente=None, relogio=None, dormir=time.sleep)` com `ciclo() -> int` e `rodar() -> None`
  - CLI: `tcg-sniper notificador`

- [ ] **Step 1: Testes do `NotificadorFila` e do `enviar_uma_vez` (falham)**

Substituir todo o conteúdo de `tests/notificador/test_notificador.py` por:

```python
import json
import logging
from datetime import UTC, datetime

import httpx
import pytest
import respx
from sqlalchemy import select

from tcg_sniper.db.models import MensagemSaida, StatusMensagem
from tcg_sniper.notificador import criar_notificador
from tcg_sniper.notificador.base import Destino
from tcg_sniper.notificador.evolution import Resultado, enviar_uma_vez
from tcg_sniper.notificador.fila import NotificadorFila

URL = "http://evo.test"
AGORA = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def test_fila_grava_pendente(sessoes):
    NotificadorFila(sessoes, relogio=lambda: AGORA).enviar(Destino.OPORTUNIDADES, "oferta")
    with sessoes() as s:
        [m] = s.scalars(select(MensagemSaida))
    assert (m.destino, m.texto, m.status, m.criada_em) == ("oportunidades", "oferta", StatusMensagem.PENDENTE, AGORA)


def test_fila_com_banco_fora_nao_lanca_e_registra_o_texto(caplog):
    def quebrado():
        raise RuntimeError("banco fora")

    with caplog.at_level(logging.ERROR):
        NotificadorFila(quebrado).enviar(Destino.ADMIN, "aviso importante")
    assert "aviso importante" in caplog.text and "banco fora" in caplog.text


def test_criar_notificador_devolve_a_fila(config, sessoes):
    assert isinstance(criar_notificador(config, sessoes), NotificadorFila)


@respx.mock
@pytest.mark.parametrize(
    ("resposta", "esperado"),
    [
        (httpx.Response(201), Resultado.OK),
        (httpx.Response(500), Resultado.TRANSITORIO),
        (httpx.Response(503), Resultado.TRANSITORIO),
        (httpx.Response(400), Resultado.DEFINITIVO),
        (httpx.Response(404), Resultado.DEFINITIVO),
    ],
)
def test_enviar_uma_vez_classifica_a_resposta(resposta, esperado):
    rota = respx.post(f"{URL}/message/sendText/TCG%20Sniper").mock(return_value=resposta)
    resultado, erro = enviar_uma_vez(httpx.Client(), URL, "chave", "TCG Sniper", "1@g.us", "olá")
    assert resultado is esperado
    assert (erro is None) is (esperado is Resultado.OK)
    pedido = rota.calls.last.request
    assert pedido.headers["apikey"] == "chave"
    assert json.loads(pedido.read()) == {"number": "1@g.us", "text": "olá"}


@respx.mock
@pytest.mark.parametrize("falha", [httpx.ConnectError("caiu"), httpx.ReadTimeout("lento"), RuntimeError("?")])
def test_enviar_uma_vez_erro_de_rede_e_transitorio(falha):
    respx.post(f"{URL}/message/sendText/inst").mock(side_effect=falha)
    resultado, erro = enviar_uma_vez(httpx.Client(), URL, "chave", "inst", "1@g.us", "olá")
    assert resultado is Resultado.TRANSITORIO and erro
```

- [ ] **Step 2: Testes do serviço (falham)**

Create `tests/notificador/test_servico.py`:

```python
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from sqlalchemy import select

from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import EstadoNotificador, MensagemSaida, StatusMensagem
from tcg_sniper.notificador.servico import ServicoNotificador

URL = "http://evo.test"
ROTA = f"{URL}/message/sendText/inst"
AGORA = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


class Relogio:
    def __init__(self, agora):
        self.agora = agora

    def __call__(self):
        return self.agora


@pytest.fixture
def env(config):
    return config.model_copy(update={"evolution_url": URL, "evolution_api_key": "chave"})


@pytest.fixture
def configurado(sessoes, env):
    with sessoes() as s, s.begin():
        repo.obter_config_geral(s, env)
        repo.salvar_config_geral(
            s,
            {"evolution_instancia": "inst", "whatsapp_grupo_admin": "a@g.us", "whatsapp_grupo_oportunidades": "o@g.us"},
            AGORA,
        )


def servico(sessoes, env, relogio=None):
    return ServicoNotificador(sessoes, env, cliente=httpx.Client(), relogio=relogio or Relogio(AGORA), dormir=lambda _: None)


def nova(sessoes, destino="admin", texto="x", criada=AGORA):
    with sessoes() as s, s.begin():
        return repo_msg.enfileirar(s, destino, texto, criada).id


def ler(sessoes, mid):
    with sessoes() as s:
        return s.get(MensagemSaida, mid)


@respx.mock
def test_sucesso_marca_enviada(sessoes, env, configurado):
    rota = respx.post(ROTA).mock(return_value=httpx.Response(201))
    mid = nova(sessoes, "oportunidades", "oferta")
    assert servico(sessoes, env).ciclo() == 1
    m = ler(sessoes, mid)
    assert (m.status, m.enviada_em, m.ultimo_erro) == (StatusMensagem.ENVIADA, AGORA, None)
    assert '"o@g.us"' in rota.calls.last.request.read().decode()


@respx.mock
def test_5xx_espera_crescente_sem_virar_falha(sessoes, env, configurado):
    respx.post(ROTA).mock(return_value=httpx.Response(503))
    mid = nova(sessoes)
    relogio = Relogio(AGORA)
    svc = servico(sessoes, env, relogio)
    esperas = []
    for _ in range(7):
        svc.ciclo()
        m = ler(sessoes, mid)
        esperas.append(m.proxima_tentativa_em - relogio.agora)
        relogio.agora = m.proxima_tentativa_em
    assert [e.total_seconds() / 60 for e in esperas] == [1, 2, 4, 8, 16, 30, 30]
    m = ler(sessoes, mid)
    assert (m.status, m.tentativas) == (StatusMensagem.PENDENTE, 7)
    assert "503" in m.ultimo_erro


@respx.mock
def test_4xx_vira_falha_na_quinta(sessoes, env, configurado):
    respx.post(ROTA).mock(return_value=httpx.Response(400))
    mid = nova(sessoes)
    relogio = Relogio(AGORA)
    svc = servico(sessoes, env, relogio)
    for tentativa in range(1, 6):
        svc.ciclo()
        m = ler(sessoes, mid)
        assert m.tentativas == tentativa
        relogio.agora = m.proxima_tentativa_em
    assert ler(sessoes, mid).status is StatusMensagem.FALHA


@respx.mock
def test_sem_grupo_fica_pendente_sem_gastar_tentativa_e_sai_quando_preenchido(sessoes, env):
    rota = respx.post(ROTA).mock(return_value=httpx.Response(201))
    with sessoes() as s, s.begin():
        repo.obter_config_geral(s, env)
        repo.salvar_config_geral(s, {"evolution_instancia": "inst", "whatsapp_grupo_admin": None}, AGORA)
    mid = nova(sessoes)
    relogio = Relogio(AGORA)
    svc = servico(sessoes, env, relogio)
    svc.ciclo()
    m = ler(sessoes, mid)
    assert (m.status, m.tentativas, m.proxima_tentativa_em) == (StatusMensagem.PENDENTE, 0, AGORA + timedelta(minutes=1))
    assert "grupo" in m.ultimo_erro and rota.call_count == 0
    with sessoes() as s, s.begin():
        repo.salvar_config_geral(s, {"whatsapp_grupo_admin": "a@g.us"}, AGORA)
    relogio.agora = AGORA + timedelta(minutes=1)
    svc.ciclo()
    assert ler(sessoes, mid).status is StatusMensagem.ENVIADA


@respx.mock
def test_sem_chave_fica_pendente(sessoes, env, configurado):
    rota = respx.post(ROTA)
    mid = nova(sessoes)
    servico(sessoes, env.model_copy(update={"evolution_api_key": "trocar-esta-chave"})).ciclo()
    m = ler(sessoes, mid)
    assert (m.status, m.tentativas) == (StatusMensagem.PENDENTE, 0) and rota.call_count == 0
    assert "EVOLUTION_API_KEY" in m.ultimo_erro


@respx.mock
def test_oportunidade_vencida_expira_e_admin_vencida_sai(sessoes, env, configurado):
    respx.post(ROTA).mock(return_value=httpx.Response(201))
    velha = AGORA - timedelta(hours=6, minutes=1)
    oportunidade = nova(sessoes, "oportunidades", "oferta velha", velha)
    admin = nova(sessoes, "admin", "aviso velho", velha)
    servico(sessoes, env).ciclo()
    assert ler(sessoes, oportunidade).status is StatusMensagem.EXPIRADA
    assert ler(sessoes, admin).status is StatusMensagem.ENVIADA


@respx.mock
def test_oportunidade_reenviada_sai_mesmo_vencida(sessoes, env, configurado):
    respx.post(ROTA).mock(return_value=httpx.Response(201))
    mid = nova(sessoes, "oportunidades", "oferta", AGORA - timedelta(hours=10))
    with sessoes() as s, s.begin():
        s.get(MensagemSaida, mid).status = StatusMensagem.EXPIRADA
        repo_msg.reenviar(s, mid, AGORA)
    servico(sessoes, env).ciclo()
    assert ler(sessoes, mid).status is StatusMensagem.ENVIADA


@respx.mock
def test_validade_salva_na_tela(sessoes, env, configurado):
    respx.post(ROTA).mock(return_value=httpx.Response(201))
    with sessoes() as s, s.begin():
        repo.salvar_config_geral(s, {"validade_oportunidade_h": 1}, AGORA)
    mid = nova(sessoes, "oportunidades", "oferta", AGORA - timedelta(hours=2))
    servico(sessoes, env).ciclo()
    assert ler(sessoes, mid).status is StatusMensagem.EXPIRADA


@respx.mock
def test_ordem_e_limite_de_20_por_ciclo(sessoes, env, configurado):
    rota = respx.post(ROTA).mock(return_value=httpx.Response(201))
    for i in range(25):
        nova(sessoes, "admin", f"m{i:02d}", AGORA - timedelta(minutes=25 - i))
    assert servico(sessoes, env).ciclo() == 20
    textos = [chamada.request.read().decode() for chamada in rota.calls]
    assert '"m00"' in textos[0] and '"m19"' in textos[-1]
    with sessoes() as s:
        assert len(list(s.scalars(select(MensagemSaida).where(MensagemSaida.status == StatusMensagem.PENDENTE)))) == 5


@respx.mock
def test_ciclo_registra_que_esta_vivo(sessoes, env, configurado):
    servico(sessoes, env).ciclo()
    with sessoes() as s:
        assert s.get(EstadoNotificador, 1).ultimo_ciclo_em == AGORA


@respx.mock
def test_limpeza_roda_no_primeiro_ciclo_e_depois_a_cada_24h(sessoes, env, configurado):
    def antiga():
        with sessoes() as s, s.begin():
            m = repo_msg.enfileirar(s, "admin", "antiga", AGORA - timedelta(days=40))
            m.status = StatusMensagem.ENVIADA
            return m.id

    primeira = antiga()
    relogio = Relogio(AGORA)
    svc = servico(sessoes, env, relogio)
    svc.ciclo()
    assert ler(sessoes, primeira) is None
    segunda = antiga()
    relogio.agora = AGORA + timedelta(hours=1)
    svc.ciclo()
    assert ler(sessoes, segunda) is not None
    relogio.agora = AGORA + timedelta(hours=24)
    svc.ciclo()
    assert ler(sessoes, segunda) is None


def test_erro_no_ciclo_nao_derruba_o_laco(sessoes, env, caplog, monkeypatch):
    svc = servico(sessoes, env)
    chamadas = []

    def ciclo_quebrado():
        chamadas.append(1)
        if len(chamadas) == 1:
            raise RuntimeError("banco caiu")
        raise SystemExit

    monkeypatch.setattr(svc, "ciclo", ciclo_quebrado)
    with caplog.at_level(logging.ERROR), pytest.raises(SystemExit):
        svc.rodar()
    assert len(chamadas) == 2 and "banco caiu" in caplog.text
```

- [ ] **Step 3: Teste do CLI (falha)**

Acrescentar a `tests/test_cli.py`:

```python
def test_notificador_instala_sigterm_e_roda_o_servico(monkeypatch):
    from tcg_sniper.notificador import servico

    anterior = signal.getsignal(signal.SIGTERM)
    vistos = []

    class ServicoFalso:
        def __init__(self, *args, **kwargs):
            pass

        def rodar(self):
            vistos.append(signal.getsignal(signal.SIGTERM))

    monkeypatch.setattr(servico, "ServicoNotificador", ServicoFalso)
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    try:
        cli.main(["notificador"])
        assert vistos and vistos[0] not in (anterior, signal.SIG_DFL, signal.SIG_IGN)
    finally:
        signal.signal(signal.SIGTERM, anterior)
```

- [ ] **Step 4: Rodar e ver falhar**

Run: `uv run pytest -q tests/notificador tests/test_cli.py`
Expected: FAIL/ERROR (`fila`, `servico`, `Resultado`, `enviar_uma_vez` não existem; subcomando inválido).

- [ ] **Step 5: `evolution.py`**

Substituir todo o conteúdo de `src/tcg_sniper/notificador/evolution.py` por:

```python
"""Um envio de texto pela Evolution API, classificado para o serviço notificador decidir o que fazer."""

import enum
from urllib.parse import quote

import httpx


class Resultado(enum.StrEnum):
    OK = "ok"
    TRANSITORIO = "transitorio"  # rede, timeout ou 5xx: tentar de novo mais tarde
    DEFINITIVO = "definitivo"  # 4xx: instância, grupo ou chave errados


def enviar_uma_vez(
    cliente: httpx.Client, url: str, chave: str, instancia: str, grupo: str, texto: str
) -> tuple[Resultado, str | None]:
    """Uma tentativa, sem retries (quem tenta de novo é o serviço). Nunca lança exceção."""
    endpoint = f"{url.rstrip('/')}/message/sendText/{quote(instancia, safe='')}"
    try:
        resposta = cliente.post(endpoint, headers={"apikey": chave}, json={"number": grupo, "text": texto})
    except Exception as erro:  # noqa: BLE001 - qualquer falha de envio é tratada como transitória
        return Resultado.TRANSITORIO, f"{type(erro).__name__}: {erro}"
    if resposta.is_success:
        return Resultado.OK, None
    corpo = resposta.text[:200]
    if resposta.status_code >= 500:
        return Resultado.TRANSITORIO, f"HTTP {resposta.status_code}: {corpo}"
    return Resultado.DEFINITIVO, f"HTTP {resposta.status_code}: {corpo}"
```

(Se o ruff marcar o `noqa` como desnecessário, tire-o.)

- [ ] **Step 6: `NotificadorFila`**

Create `src/tcg_sniper/notificador/fila.py`:

```python
import logging
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.notificador.base import Destino

log = logging.getLogger(__name__)


class NotificadorFila:
    """Grava a mensagem na tabela de saída; quem envia é o serviço `notificador`."""

    def __init__(self, sessoes: sessionmaker[Session], relogio: Callable[[], datetime] | None = None):
        self._sessoes = sessoes
        self._relogio = relogio or repo.agora_utc

    def enviar(self, destino: Destino, texto: str) -> None:
        try:
            with self._sessoes() as s, s.begin():
                repo_msg.enfileirar(s, destino.value, texto, self._relogio())
        except Exception:  # noqa: BLE001 - notificar nunca pode interromper quem chamou
            log.exception("não consegui gravar a mensagem para %s; ela se perdeu: %s", destino.value, texto)
```

Substituir `src/tcg_sniper/notificador/__init__.py` por:

```python
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.config import Config
from tcg_sniper.notificador.base import Notificador
from tcg_sniper.notificador.fila import NotificadorFila

CHAVE_PADRAO = "trocar-esta-chave"


def criar_notificador(config: Config, sessoes: sessionmaker[Session]) -> Notificador:
    """Os serviços só gravam na tabela de saída; o serviço `notificador` envia (`servico.py`).
    `config` fica na assinatura para os chamadores não mudarem."""
    del config
    return NotificadorFila(sessoes)
```

Apagar `src/tcg_sniper/notificador/log.py` (não é mais usado; confira com `grep -rn "LogNotificador" src tests`).

- [ ] **Step 7: Serviço**

Create `src/tcg_sniper/notificador/servico.py`:

```python
"""Serviço `notificador`: envia a tabela de saída pela Evolution, com tentativas, validade e limpeza."""

import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import ConfigGeral, MensagemSaida, StatusMensagem
from tcg_sniper.notificador import CHAVE_PADRAO
from tcg_sniper.notificador.evolution import Resultado, enviar_uma_vez

log = logging.getLogger(__name__)

INTERVALO_S = 5
LOTE = 20
MAX_TENTATIVAS_DEFINITIVAS = 5
ESPERA_SEM_DESTINO = timedelta(minutes=1)
ESPERA_MAX_MIN = 30
INTERVALO_LIMPEZA = timedelta(hours=24)
TIMEOUT_S = 15


class ServicoNotificador:
    def __init__(
        self,
        sessoes: sessionmaker[Session],
        config_env: Config,
        cliente: httpx.Client | None = None,
        relogio: Callable[[], datetime] | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ):
        self._sessoes = sessoes
        self._config_env = config_env
        self._cliente = cliente or httpx.Client(timeout=TIMEOUT_S)
        self._relogio = relogio or repo.agora_utc
        self._dormir = dormir
        self._ultima_limpeza: datetime | None = None
        chave = (config_env.evolution_api_key or "").strip()
        self._chave = chave if config_env.evolution_url and chave not in ("", CHAVE_PADRAO) else None

    def ciclo(self) -> int:
        """Um ciclo: registra que está vivo, limpa (1x/dia) e processa até `LOTE` mensagens.
        Devolve quantas mensagens pegou."""
        agora = self._relogio()
        with self._sessoes() as s, s.begin():
            geral = repo.obter_config_geral(s, self._config_env)
            repo_msg.registrar_ciclo(s, agora)
            if self._ultima_limpeza is None or agora - self._ultima_limpeza >= INTERVALO_LIMPEZA:
                apagadas = repo_msg.limpar_antigas(s, agora)
                self._ultima_limpeza = agora
                if apagadas:
                    log.info("%d mensagem(ns) antigas apagadas", apagadas)
            lote = repo_msg.lote_pendente(s, agora, LOTE)
            for mensagem in lote:
                self._processar(mensagem, geral, agora)
            return len(lote)

    def _processar(self, m: MensagemSaida, geral: ConfigGeral, agora: datetime) -> None:
        m.atualizado_em = agora
        validade = timedelta(hours=geral.validade_oportunidade_h)
        if m.destino == "oportunidades" and not m.ignorar_validade and agora - m.criada_em > validade:
            m.status = StatusMensagem.EXPIRADA
            return
        grupo = geral.whatsapp_grupo_admin if m.destino == "admin" else geral.whatsapp_grupo_oportunidades
        falta = None
        if self._chave is None:
            falta = "EVOLUTION_URL ou EVOLUTION_API_KEY ausente (ou com o valor padrão) no .env"
        elif not geral.evolution_instancia:
            falta = "sem instância da Evolution em Configurações → Geral"
        elif not grupo:
            falta = f"sem grupo de {m.destino} em Configurações → Geral"
        if falta is not None:
            m.ultimo_erro = falta
            m.proxima_tentativa_em = agora + ESPERA_SEM_DESTINO
            return
        resultado, erro = enviar_uma_vez(
            self._cliente, self._config_env.evolution_url, self._chave, geral.evolution_instancia, grupo, m.texto
        )
        if resultado is Resultado.OK:
            m.status = StatusMensagem.ENVIADA
            m.enviada_em = agora
            m.ultimo_erro = None
            return
        m.tentativas += 1
        m.ultimo_erro = erro
        if resultado is Resultado.DEFINITIVO and m.tentativas >= MAX_TENTATIVAS_DEFINITIVAS:
            m.status = StatusMensagem.FALHA
            log.error("mensagem %d para %s falhou de vez: %s", m.id, m.destino, erro)
            return
        m.proxima_tentativa_em = agora + timedelta(minutes=min(2 ** (m.tentativas - 1), ESPERA_MAX_MIN))
        log.warning("mensagem %d para %s não saiu (tentativa %d): %s", m.id, m.destino, m.tentativas, erro)

    def rodar(self) -> None:
        log.info("notificador iniciado")
        while True:
            try:
                self.ciclo()
            except Exception:
                log.exception("erro no ciclo do notificador; tenta de novo em %d s", INTERVALO_S)
            self._dormir(INTERVALO_S)
```

Atenção ao import circular: `servico.py` importa `CHAVE_PADRAO` de `tcg_sniper.notificador` (o `__init__`), que importa só `fila` e `base`; não importe `servico` no `__init__`.

- [ ] **Step 8: CLI e compose**

Em `src/tcg_sniper/cli.py`:

- `sub.add_parser("notificador", help="envia a tabela de saída do WhatsApp pela Evolution API")` (depois do `coletor-amazon`)
- novo ramo antes do `elif args.comando == "admin":`

```python
    elif args.comando == "notificador":
        from tcg_sniper.notificador import servico

        instalar_sigterm()
        servico.ServicoNotificador(sessoes, config).rodar()
```

Em `docker-compose.yml`, antes de `admin:`:

```yaml
  notificador:
    <<: *app
    command: tcg-sniper notificador
    depends_on:
      migrate:
        condition: service_completed_successfully
```

- [ ] **Step 9: Rodar e ver passar**

Run: `uv run pytest -q tests/notificador tests/test_cli.py && uv run pytest -q && uv run ruff check .`
Expected: PASS. Os testes dos coletores usam `NotificadorFake` e não mudam.

- [ ] **Step 10: Commit**

```bash
git add src/tcg_sniper/notificador src/tcg_sniper/cli.py docker-compose.yml tests/notificador tests/test_cli.py
git rm src/tcg_sniper/notificador/log.py
git commit -m "feat: services write WhatsApp messages to the outbox; notifier service sends them with retries and expiry

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Admin — Mensagens, Dashboard, Serviços e README

**Files:**
- Create: `src/tcg_sniper/admin/consultas_mensagens.py`
- Create: `src/tcg_sniper/admin/templates/mensagens.html`
- Modify: `src/tcg_sniper/admin/app.py` (rotas de Mensagens, `destino_seguro` com prefixo, Dashboard e Serviços)
- Modify: `src/tcg_sniper/admin/templates/base.html`, `index.html`, `servicos.html`
- Modify: `README.md`
- Test: `tests/admin/test_admin_mensagens.py` (novo), `tests/admin/test_admin_casamentos.py` (só se `destino_seguro` for chamado com outro nome)

**Interfaces:**
- Consumes (Task 1): `models.MensagemSaida`, `StatusMensagem`, `EstadoNotificador`; `repositorio_mensagens.enfileirar/reenviar/descartar/MensagemNaoEncontrada/AcaoInvalida`. Já existentes: `numero_pagina`, `destino_seguro`, filtro `data`, `request.state.config`.
- Produces:
  - `consultas_mensagens.SITUACOES`, `DESTINOS`, `POR_PAGINA = 50`
  - `consultas_mensagens.listar(s, situacao: str, destino: str, pagina: int) -> tuple[list[MensagemSaida], int, int]`
  - `consultas_mensagens.resumo(s, agora: datetime) -> ResumoMensagens` (`pendentes`, `falhas`, `ultimo_envio`, `aviso`)
  - `consultas_mensagens.estado_notificador(s, agora: datetime) -> tuple[str, datetime | None]` (`"rodando"`, `"parado"`, `"nunca"`)
  - `destino_seguro(voltar: str, prefixo: str = "/casamentos") -> str`

- [ ] **Step 1: Testes (falham)**

Create `tests/admin/test_admin_mensagens.py`:

```python
import base64
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from tcg_sniper.admin.app import criar_app, destino_seguro
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import MensagemSaida, StatusMensagem


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def criar(sessoes, destino="admin", texto="x", status=StatusMensagem.PENDENTE, idade=timedelta(0), erro=None):
    with sessoes() as s, s.begin():
        m = repo_msg.enfileirar(s, destino, texto, repo.agora_utc() - idade)
        m.status, m.ultimo_erro = status, erro
        return m.id


def test_menu_tem_mensagens(cliente):
    assert '<a href="/mensagens">Mensagens</a>' in cliente.get("/").text


def test_lista_com_filtros_e_paginacao(cliente, sessoes):
    for i in range(55):
        criar(sessoes, "oportunidades", f"oferta {i:02d}", StatusMensagem.ENVIADA, timedelta(minutes=60 - i))
    criar(sessoes, "admin", "aviso que falhou", StatusMensagem.FALHA, erro="HTTP 400: grupo inválido")
    texto = cliente.get("/mensagens", params={"situacao": "falha"}).text
    assert "aviso que falhou" in texto and "HTTP 400: grupo inválido" in texto and "oferta" not in texto
    pagina1 = cliente.get("/mensagens", params={"destino": "oportunidades"}).text
    assert "oferta 54" in pagina1 and "oferta 04" not in pagina1  # mais recentes primeiro, 50 por página
    assert "destino=oportunidades" in pagina1 and "pagina=2" in pagina1
    pagina2 = cliente.get("/mensagens", params={"destino": "oportunidades", "pagina": "2"}).text
    assert "oferta 04" in pagina2


@pytest.mark.parametrize("params", [{"situacao": "x"}, {"destino": "todos-os-grupos"}])
def test_filtro_invalido_400(cliente, params):
    assert cliente.get("/mensagens", params=params).status_code == 400


def test_botoes_por_situacao(cliente, sessoes):
    falha = criar(sessoes, status=StatusMensagem.FALHA)
    pendente = criar(sessoes, status=StatusMensagem.PENDENTE)
    enviada = criar(sessoes, status=StatusMensagem.ENVIADA)
    texto = cliente.get("/mensagens").text
    assert f'action="/mensagens/{falha}"' in texto and f'action="/mensagens/{pendente}"' in texto
    assert f'action="/mensagens/{enviada}"' not in texto


def test_reenviar_e_descartar(cliente, sessoes):
    falha = criar(sessoes, "oportunidades", status=StatusMensagem.FALHA)
    r = cliente.post(
        f"/mensagens/{falha}", data={"acao": "reenviar", "voltar": "/mensagens?situacao=falha"}, follow_redirects=False
    )
    assert r.status_code == 303 and r.headers["location"] == "/mensagens?situacao=falha"
    with sessoes() as s:
        m = s.get(MensagemSaida, falha)
        assert (m.status, m.ignorar_validade) == (StatusMensagem.PENDENTE, True)
    cliente.post(f"/mensagens/{falha}", data={"acao": "descartar"})
    with sessoes() as s:
        assert s.get(MensagemSaida, falha).status is StatusMensagem.DESCARTADA


def test_acoes_invalidas(cliente, sessoes):
    enviada = criar(sessoes, status=StatusMensagem.ENVIADA)
    assert cliente.post(f"/mensagens/{enviada}", data={"acao": "reenviar"}).status_code == 409
    assert cliente.post(f"/mensagens/{enviada}", data={"acao": "apagar"}).status_code == 400
    assert cliente.post("/mensagens/999999", data={"acao": "descartar"}).status_code == 404


@pytest.mark.parametrize(
    ("voltar", "esperado"),
    [
        ("/mensagens?situacao=falha", "/mensagens?situacao=falha"),
        ("https://evil.test", "/mensagens"),
        ("//evil.test", "/mensagens"),
        ("/casamentos", "/mensagens"),
    ],
)
def test_destino_seguro_de_mensagens(voltar, esperado):
    assert destino_seguro(voltar, "/mensagens") == esperado


def test_dashboard_avisa_falha(cliente, sessoes):
    criar(sessoes, status=StatusMensagem.FALHA, erro="HTTP 400: grupo inválido")
    texto = cliente.get("/").text
    assert "WhatsApp" in texto and "HTTP 400: grupo inválido" in texto and 'href="/mensagens' in texto


def test_dashboard_avisa_pendente_antiga_e_nao_a_recente(cliente, sessoes):
    criar(sessoes, idade=timedelta(minutes=10), erro="sem grupo de admin em Configurações → Geral")
    assert "Mensagens do WhatsApp paradas" not in cliente.get("/").text
    criar(sessoes, idade=timedelta(minutes=31), erro="HTTP 503: fora")
    assert "Mensagens do WhatsApp paradas" in cliente.get("/").text


def test_servicos_mostra_o_estado_do_notificador(cliente, sessoes):
    assert "Notificador" in cliente.get("/servicos").text and "nunca rodou" in cliente.get("/servicos").text
    with sessoes() as s, s.begin():
        repo_msg.registrar_ciclo(s, repo.agora_utc())
    assert "rodando" in cliente.get("/servicos").text
    with sessoes() as s, s.begin():
        repo_msg.registrar_ciclo(s, repo.agora_utc() - timedelta(minutes=5))
    assert "parado desde" in cliente.get("/servicos").text


def test_configuracoes_tem_a_validade(cliente):
    assert 'name="validade_oportunidade_h" value="6"' in cliente.get("/configuracoes").text
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/admin/test_admin_mensagens.py`
Expected: FAIL (rota `/mensagens` não existe; `destino_seguro` não aceita prefixo). `test_configuracoes_tem_a_validade` já pode passar (Task 1).

- [ ] **Step 3: Consultas**

Create `src/tcg_sniper/admin/consultas_mensagens.py`:

```python
"""Consultas da tabela de saída do WhatsApp para o admin."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tcg_sniper.db.models import EstadoNotificador, MensagemSaida, StatusMensagem

SITUACOES = ("todas", *(s.value for s in StatusMensagem))
DESTINOS = ("todos", "admin", "oportunidades")
POR_PAGINA = 50
PENDENTE_PARADA = timedelta(minutes=30)
NOTIFICADOR_VIVO = timedelta(minutes=1)


@dataclass(frozen=True)
class ResumoMensagens:
    pendentes: int
    falhas: int
    ultimo_envio: datetime | None
    aviso: str | None


def listar(s: Session, situacao: str, destino: str, pagina: int) -> tuple[list[MensagemSaida], int, int]:
    condicoes = []
    if situacao != "todas":
        condicoes.append(MensagemSaida.status == StatusMensagem(situacao))
    if destino != "todos":
        condicoes.append(MensagemSaida.destino == destino)
    total = s.scalar(select(func.count()).select_from(MensagemSaida).where(*condicoes)) or 0
    paginas = max(1, -(-total // POR_PAGINA))
    pagina = min(max(pagina, 1), paginas)
    consulta = (
        select(MensagemSaida)
        .where(*condicoes)
        .order_by(MensagemSaida.criada_em.desc(), MensagemSaida.id.desc())
        .offset((pagina - 1) * POR_PAGINA)
        .limit(POR_PAGINA)
    )
    return list(s.scalars(consulta)), pagina, paginas


def _contar(s: Session, *condicoes) -> int:
    return s.scalar(select(func.count()).select_from(MensagemSaida).where(*condicoes)) or 0


def resumo(s: Session, agora: datetime) -> ResumoMensagens:
    pendentes = _contar(s, MensagemSaida.status == StatusMensagem.PENDENTE)
    falhas = _contar(s, MensagemSaida.status == StatusMensagem.FALHA)
    ultimo_envio = s.scalar(select(func.max(MensagemSaida.enviada_em)))
    paradas = _contar(
        s, MensagemSaida.status == StatusMensagem.PENDENTE, MensagemSaida.criada_em < agora - PENDENTE_PARADA
    )
    aviso = None
    if falhas or paradas:
        ultimo_erro = s.scalar(
            select(MensagemSaida.ultimo_erro)
            .where(
                MensagemSaida.status.in_([StatusMensagem.FALHA, StatusMensagem.PENDENTE]),
                MensagemSaida.ultimo_erro.is_not(None),
            )
            .order_by(MensagemSaida.atualizado_em.desc())
            .limit(1)
        )
        partes = []
        if falhas:
            partes.append(f"{falhas} com falha")
        if paradas:
            partes.append(f"{paradas} pendente(s) há mais de 30 min")
        aviso = "Mensagens do WhatsApp paradas: " + " e ".join(partes) + "."
        if ultimo_erro:
            aviso += f" Último erro: {ultimo_erro}"
    return ResumoMensagens(pendentes, falhas, ultimo_envio, aviso)


def estado_notificador(s: Session, agora: datetime) -> tuple[str, datetime | None]:
    estado = s.get(EstadoNotificador, 1)
    ultimo = estado.ultimo_ciclo_em if estado else None
    if ultimo is None:
        return "nunca", None
    return ("rodando" if agora - ultimo < NOTIFICADOR_VIVO else "parado"), ultimo
```

- [ ] **Step 4: Rotas e `destino_seguro`**

Em `src/tcg_sniper/admin/app.py`:

- trocar `destino_seguro` por:

```python
def destino_seguro(voltar: str, prefixo: str = "/casamentos") -> str:
    """Só volta para telas do próprio admin que começam com `prefixo` (nunca para fora)."""
    if voltar.startswith(prefixo) and not voltar.startswith("//") and "\\" not in voltar:
        return voltar
    return prefixo
```

- imports: `from tcg_sniper.admin import consultas_mensagens` e `from tcg_sniper.db import repositorio_mensagens as repo_msg`
- Dashboard: dentro do `with sessoes()`, acrescentar ao contexto `"resumo_msgs": consultas_mensagens.resumo(s, agora),`
- Serviços: acrescentar ao contexto `"notificador": consultas_mensagens.estado_notificador(s, repo.agora_utc()),`
- novas rotas (antes de Configurações):

```python
    @app.get("/mensagens", response_class=HTMLResponse)
    def mensagens(request: Request, situacao: str = "todas", destino: str = "todos", pagina: str = "1"):
        if situacao not in consultas_mensagens.SITUACOES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"situação inválida: {situacao}")
        if destino not in consultas_mensagens.DESTINOS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"destino inválido: {destino}")
        with sessoes() as s, s.begin():
            linhas, pagina_atual, paginas = consultas_mensagens.listar(s, situacao, destino, numero_pagina(pagina))
            parametros = {"situacao": situacao, "destino": destino, "pagina": pagina_atual}

            def link(**mudancas) -> str:
                return "/mensagens?" + urlencode({**parametros, **mudancas})

            return templates.TemplateResponse(
                request,
                "mensagens.html",
                {
                    "linhas": linhas,
                    "situacao": situacao,
                    "destino": destino,
                    "situacoes": consultas_mensagens.SITUACOES,
                    "destinos": consultas_mensagens.DESTINOS,
                    "pagina": pagina_atual,
                    "paginas": paginas,
                    "link": link,
                    "aqui": link(),
                },
            )

    @app.post("/mensagens/{mensagem_id}")
    async def acao_mensagem(request: Request, mensagem_id: int):
        formulario = await ler_formulario(request)
        acoes = {"reenviar": repo_msg.reenviar, "descartar": repo_msg.descartar}
        acao = acoes.get(formulario.get("acao", ""))
        if acao is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "ação inválida")
        try:
            with sessoes() as s, s.begin():
                acao(s, mensagem_id, repo.agora_utc())
        except repo_msg.MensagemNaoEncontrada:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "mensagem não encontrada") from None
        except repo_msg.AcaoInvalida as erro:
            raise HTTPException(status.HTTP_409_CONFLICT, str(erro)) from None
        voltar = destino_seguro(formulario.get("voltar", "/mensagens"), "/mensagens")
        return RedirectResponse(voltar, status_code=status.HTTP_303_SEE_OTHER)
```

(`ler_formulario` e `urlencode` já existem em `app.py`.)

- [ ] **Step 5: Templates**

Em `base.html`, trocar `<li><a href="/ofertas">Ofertas</a></li><li><a href="/configuracoes">Configurações</a></li>` por `<li><a href="/ofertas">Ofertas</a></li><li><a href="/mensagens">Mensagens</a></li><li><a href="/configuracoes">Configurações</a></li>`.

Em `index.html`, depois do aviso da Amazon pausada:

```html
{% if resumo_msgs.aviso %}
<div class="pausado"><strong>{{ resumo_msgs.aviso }}</strong> <a href="/mensagens?situacao=falha">Ir para Mensagens</a></div>
{% endif %}
```

e um terceiro `<article>` dentro da `<div class="grid">`, depois do da Amazon:

```html
  <article>
    <header><strong>WhatsApp</strong></header>
    <p>Pendentes: {{ resumo_msgs.pendentes }} · Falhas: {{ resumo_msgs.falhas }}</p>
    <p>Último envio: {{ resumo_msgs.ultimo_envio|data if resumo_msgs.ultimo_envio else "—" }}</p>
    <p><a href="/mensagens">Ver mensagens</a></p>
  </article>
```

(Confira se o filtro `data` já trata `None`; se tratar, use só `{{ resumo_msgs.ultimo_envio|data }}`.)

Em `servicos.html`, um terceiro `<article>` depois do da Amazon:

```html
  <article>
    <header><strong>Notificador</strong></header>
    {% set estado_notif, ultimo_ciclo = notificador %}
    {% if estado_notif == "rodando" %}<p>rodando</p>
    {% elif estado_notif == "parado" %}<p class="pausado">parado desde {{ ultimo_ciclo|data }}</p>
    {% else %}<p class="pausado">nunca rodou</p>{% endif %}
  </article>
```

Create `src/tcg_sniper/admin/templates/mensagens.html`:

```html
{% extends "base.html" %}
{% block titulo %}Mensagens · TCG Sniper{% endblock %}
{% block conteudo %}
<h2>Mensagens do WhatsApp</h2>
<form method="get" action="/mensagens" class="filtros">
  <div class="grid">
    <label>Situação
      <select name="situacao">{% for v in situacoes %}<option value="{{ v }}" {% if v == situacao %}selected{% endif %}>{{ v }}</option>{% endfor %}</select>
    </label>
    <label>Destino
      <select name="destino">{% for v in destinos %}<option value="{{ v }}" {% if v == destino %}selected{% endif %}>{{ v }}</option>{% endfor %}</select>
    </label>
    <button>Filtrar</button>
  </div>
</form>
<table>
  <thead><tr><th>Criada em</th><th>Destino</th><th>Texto</th><th>Situação</th><th>Tentativas</th><th>Último erro</th><th>Enviada em</th><th></th></tr></thead>
  <tbody>
  {% for m in linhas %}
    {% set partes = m.texto.split("\n") %}
    <tr>
      <td>{{ m.criada_em|data }}</td>
      <td>{{ m.destino }}</td>
      <td>{{ partes[:2]|join("\n") }}{% if partes|length > 2 %}<details><summary>mais</summary><pre>{{ m.texto }}</pre></details>{% endif %}</td>
      <td>{{ m.status.value }}</td>
      <td>{{ m.tentativas }}</td>
      <td>{{ m.ultimo_erro or "—" }}</td>
      <td>{{ m.enviada_em|data if m.enviada_em else "—" }}</td>
      <td>
        {% if m.status.value in ("falha", "expirada", "pendente") %}
        <form method="post" action="/mensagens/{{ m.id }}">
          <input type="hidden" name="voltar" value="{{ aqui }}">
          {% if m.status.value in ("falha", "expirada") %}<button name="acao" value="reenviar">Reenviar</button>{% endif %}
          <button name="acao" value="descartar" class="secondary">Descartar</button>
        </form>
        {% endif %}
      </td>
    </tr>
  {% else %}
    <tr><td colspan="8">Nenhuma mensagem.</td></tr>
  {% endfor %}
  </tbody>
</table>
<p>Página {{ pagina }} de {{ paginas }}
  {% if pagina > 1 %} · <a href="{{ link(pagina=pagina - 1) }}">anterior</a>{% endif %}
  {% if pagina < paginas %} · <a href="{{ link(pagina=pagina + 1) }}">próxima</a>{% endif %}
</p>
{% endblock %}
```

- [ ] **Step 6: README**

Em `README.md`:

- na tabela de telas do admin, acrescentar a linha **Mensagens**: "Mensagens do WhatsApp gravadas pelos serviços: pendentes, enviadas, com falha, expiradas e descartadas, com filtros. Reenviar (falha ou expirada) e Descartar."
- onde o README lista os containers/serviços, acrescentar `notificador`: "envia as mensagens da tabela de saída pela Evolution a cada 5 s; se a Evolution ou o WhatsApp estiverem fora, tenta de novo (1, 2, 4… até 30 min). Oportunidades que não saírem em até a validade de Configurações → Geral (padrão 6 h) ficam como expiradas; avisos do admin saem sempre."
- na seção de problemas comuns, um item: "**Aviso 'Mensagens do WhatsApp paradas' no Dashboard:** abra Mensagens e leia o último erro. 'sem instância' ou 'sem grupo': preencha em Configurações → Geral. 'HTTP 4xx': confira se a instância está conectada na Evolution e se o ID do grupo está certo, depois clique em Reenviar. 'HTTP 5xx' ou erro de conexão: a Evolution está fora; as mensagens saem sozinhas quando ela voltar."

- [ ] **Step 7: Rodar e ver passar**

Run: `uv run pytest -q tests/admin && uv run pytest -q && uv run ruff check .`
Expected: PASS. Os testes de `destino_seguro` dos Casamentos continuam iguais (o prefixo padrão é `/casamentos`).

- [ ] **Step 8: Commit**

```bash
git add src/tcg_sniper/admin tests/admin README.md
git commit -m "feat: Messages screen with resend and discard, WhatsApp card and warning on the dashboard, notifier on Services

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
