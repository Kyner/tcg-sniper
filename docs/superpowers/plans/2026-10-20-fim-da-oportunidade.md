# Fim da oportunidade — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a oportunidade passa a guardar o motivo de encerramento, só fecha depois de 30 min de carência e avisa o grupo certo quando acaba ("oferta encerrada", "alerta corrigido" ou técnico).

**Architecture:** o motor (funções puras) devolve uma `Decisao` com ação e motivo; o monitor grava o risco, a recuperação e o encerramento e enfileira o alerta na mesma transação para guardar o id da mensagem; um módulo novo `oportunidades/encerramento.py` é o único ponto que fecha uma oportunidade (monitor, busca e casamento) e decide o aviso pela situação da mensagem do alerta.

**Tech Stack:** Python 3.12, SQLAlchemy 2 + Alembic, Postgres 16, pytest, FastAPI + Jinja2 + DaisyUI 5 (admin antigo).

**Spec:** `docs/superpowers/specs/2026-10-20-fim-da-oportunidade-design.md`

## Global Constraints

- Textos, telas, mensagens, docstrings e comentários em português; assunto do commit em inglês (`feat:`, `fix:`, `test:`, `docs:`), **sem** `Co-Authored-By` de IA nem "Generated with".
- Testes só no Postgres de teste (`postgres-teste`, `127.0.0.1:5433`, bancos `tcg_test*`): `uv run pytest -q`. Lint: `uv run ruff check`.
- Histórico de preço nunca é apagado (`preco_amazon`, `oportunidade` etc.): nada aqui apaga linhas.
- Admin antigo: só componentes do DaisyUI 5, classes literais por extenso; depois de mexer em template, `uv run python scripts/gerar_css.py` (o teste `test_css_em_dia_com_os_templates` cobra).
- Preço conferido = itens + impostos, sem frete (regra existente; não mudar).
- Carência padrão 30 min, faixa 0–240 (0 = sem carência).
- Motivos (valores exatos): `casamento_desfeito`, `sem_leitura`, `liga_desatualizada`, `oferta_sumiu`, `vendedor`, `liga_caiu`, `preco_subiu`.
- Commit só por tarefa, na branch de trabalho; merge, push e deploy só quando o usuário pedir.

## Review Focus

- Oportunidade em risco que realerta (preço caiu de novo durante a carência): o risco some e `alertas` soma 1 — teste na Tarefa 6.
- Encerramento disputado: monitor e "Desfazer" no admin fecham a mesma oportunidade; só um encerra e só um aviso sai — teste na Tarefa 5 (segunda chamada devolve False e não enfileira).
- Alerta de abertura ainda pendente na fila (WhatsApp fora) quando a oferta acaba: o alerta é descartado e nenhum aviso de encerramento sai — teste na Tarefa 5.
- Carência 0 em Configurações: fecha na primeira leitura ruim, como antes desta versão — teste na Tarefa 2.
- Oportunidade antiga (`alerta_sem_registro`) encerrada: o grupo recebe o aviso mesmo sem mensagem ligada — teste na Tarefa 5.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
| --- | --- |
| `src/tcg_sniper/db/migrations/versions/e7c3a9d5b2f4_fim_da_oportunidade.py` (novo) | colunas novas, CHECKs, preenchimento |
| `src/tcg_sniper/db/models.py` | `MotivoEncerramento`, colunas da `Oportunidade`, `carencia_encerramento_min` |
| `src/tcg_sniper/oportunidades/motor.py` | `motivo_inelegivel`, `Aberta`, `Decisao`, `decidir` com carência |
| `src/tcg_sniper/avisos/catalogo.py` | severidades `ENCERRADA`/`CORRECAO`, três tipos novos |
| `src/tcg_sniper/oportunidades/mensagens.py` | `ROTULOS_MOTIVO`, `dados_encerramento` |
| `src/tcg_sniper/avisos/servico.py` | `avisar` devolve o id; `Avisador.avisar_em` |
| `tests/fakes.py` | `AvisadorFake.avisar_em` |
| `src/tcg_sniper/oportunidades/encerramento.py` (novo) | `encerrar`: fecha, decide e enfileira o aviso |
| `src/tcg_sniper/db/repositorio_amazon.py` | `abrir/atualizar_oportunidade` com `menor_preco`/`alertas`; risco; `fechar_oportunidades_sem_leitura` via encerramento |
| `src/tcg_sniper/db/repositorio_casamento.py` | `fechar_oportunidades` via encerramento |
| `src/tcg_sniper/coletor_amazon/monitor.py` | ações novas; alerta na mesma transação |
| `src/tcg_sniper/coletor_amazon/config.py`, `admin/consultas_amazon.py`, `admin/templates/ofertas.html` | campo da carência; selo "em risco" |
| `README.md`, `docs/IMPLANTACOES.md`, `docs/PENDENCIAS.md` | documentação |

---

### Task 1: Banco — motivo, risco e carência

**Files:**
- Create: `src/tcg_sniper/db/migrations/versions/e7c3a9d5b2f4_fim_da_oportunidade.py`
- Modify: `src/tcg_sniper/db/models.py` (enum perto de `Envio`, ~linha 75; `Oportunidade` ~351; `LIMITES_CONFIG_AMAZON`/`PADROES_CONFIG_AMAZON` ~426–470; `ConfigAmazon` ~503)
- Test: `tests/db/test_migracao_fim_oportunidade.py`

**Interfaces:**
- Produces: `MotivoEncerramento` (StrEnum em `tcg_sniper.db.models`) com `CASAMENTO_DESFEITO, SEM_LEITURA, LIGA_DESATUALIZADA, OFERTA_SUMIU, VENDEDOR, LIGA_CAIU, PRECO_SUBIU`; colunas `Oportunidade.motivo_encerramento: MotivoEncerramento | None`, `em_risco_desde: datetime | None`, `motivo_risco: MotivoEncerramento | None`, `menor_preco: Decimal`, `alertas: int`, `mensagem_alerta_id: int | None`, `encerramento_avisado_em: datetime | None`, `alerta_sem_registro: bool`; `ConfigAmazon.carencia_encerramento_min: int`.

- [ ] **Step 1: Teste da migração (falha)**

```python
# tests/db/test_migracao_fim_oportunidade.py
from alembic import command
from sqlalchemy import create_engine, pool, text

from tcg_sniper.db.session import config_alembic

ANTES = "d4b8e2f6a3c1"
COLUNAS = (
    "SELECT column_name FROM information_schema.columns WHERE table_name = 'oportunidade' AND column_name IN "
    "('motivo_encerramento', 'em_risco_desde', 'motivo_risco', 'menor_preco', 'alertas', 'mensagem_alerta_id', "
    "'encerramento_avisado_em', 'alerta_sem_registro')"
)
PREPARO = """
INSERT INTO produto_liga (id, liga_id, nome, url, ativo, visto_primeiro_em, visto_ultimo_em)
VALUES (990001, 'mig-fim', 'Produto migração', 'https://liga.test/p', true, now(), now());
INSERT INTO anuncio_amazon (id, asin, titulo, url, visto_primeiro_em, visto_ultimo_em)
VALUES (990001, 'BMIGFIM001', 'Anúncio migração', 'https://amazon.test/dp/BMIGFIM001', now(), now());
INSERT INTO oportunidade (id, anuncio_id, produto_id, preco_amazon, preco_liga, desconto_pct, envio, aberta_em,
  alertada_em, preco_alertado, alerta_conferido, fechada_em)
VALUES (990001, 990001, 990001, 700, 1000, 30, 'amazon', now(), now(), 700, false, NULL),
       (990002, 990001, 990001, 650, 1000, 35, 'amazon', now(), now(), 650, false, now());
"""
LIMPEZA = (
    "DELETE FROM oportunidade WHERE id IN (990001, 990002); DELETE FROM anuncio_amazon WHERE id = 990001; "
    "DELETE FROM produto_liga WHERE id = 990001;"
)


def test_migracao_do_fim_da_oportunidade_sobe_preenche_e_desce(engine):
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    try:
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.execute(text(COLUNAS)).all() == []
            c.execute(text(PREPARO))
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            linhas = c.execute(text(
                "SELECT id, menor_preco, alertas, alerta_sem_registro, motivo_encerramento "
                "FROM oportunidade WHERE id IN (990001, 990002) ORDER BY id"
            )).all()
            assert [tuple(l) for l in linhas] == [(990001, 700, 1, True, None), (990002, 650, 1, False, None)]
            carencia = c.execute(text("SELECT carencia_encerramento_min FROM config_amazon WHERE id = 1")).scalar()
            assert carencia in (None, 30)  # sem a linha de config o SELECT volta vazio
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.execute(text(COLUNAS)).all() == []
    finally:
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            c.execute(text(LIMPEZA))
        proprio.dispose()
```

Antes de rodar, confira em `tests/fakes.py` (`criar_produto`, `criar_anuncio`) e em `models.py` que as colunas NOT NULL de `produto_liga` e `anuncio_amazon` são só as do `INSERT` acima; se houver outra sem padrão, acrescente-a ao `PREPARO`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/db/test_migracao_fim_oportunidade.py -q`
Expected: FAIL (revisão `head` ainda não tem as colunas).

- [ ] **Step 3: Modelos**

Em `models.py`, depois de `class Envio`:

```python
class MotivoEncerramento(enum.StrEnum):
    """Por que uma oportunidade fechou, na ordem de prioridade (spec 2026-10-20-fim-da-oportunidade)."""

    CASAMENTO_DESFEITO = "casamento_desfeito"
    SEM_LEITURA = "sem_leitura"
    LIGA_DESATUALIZADA = "liga_desatualizada"
    OFERTA_SUMIU = "oferta_sumiu"
    VENDEDOR = "vendedor"
    LIGA_CAIU = "liga_caiu"
    PRECO_SUBIU = "preco_subiu"


MOTIVOS_SQL = ", ".join(f"'{m.value}'" for m in MotivoEncerramento)
```

Na `Oportunidade`, troque a docstring e acrescente (mantendo as colunas atuais):

```python
class Oportunidade(Base):
    """Oferta elegível da Amazon. Aberta enquanto `fechada_em` é NULL; no máximo uma aberta por anúncio.
    Em risco (`em_risco_desde`) quando a leitura deixou de ser elegível e a carência ainda não venceu.
    Só `oportunidades.encerramento.encerrar` fecha."""

    __tablename__ = "oportunidade"
    __table_args__ = (
        Index("uq_oportunidade_aberta", "anuncio_id", unique=True, postgresql_where=text("fechada_em IS NULL")),
        CheckConstraint(f"motivo_encerramento IN ({MOTIVOS_SQL})", name="ck_oportunidade_motivo_encerramento"),
        CheckConstraint(f"motivo_risco IN ({MOTIVOS_SQL})", name="ck_oportunidade_motivo_risco"),
    )
    # ... colunas atuais ...
    motivo_encerramento: Mapped[MotivoEncerramento | None] = mapped_column(Text)
    em_risco_desde: Mapped[datetime | None] = mapped_column(DATA)
    motivo_risco: Mapped[MotivoEncerramento | None] = mapped_column(Text)
    menor_preco: Mapped[Decimal] = mapped_column(DINHEIRO)
    alertas: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # Mensagem do último alerta (abertura ou realerta); a limpeza de 30 dias apaga a mensagem e zera aqui.
    mensagem_alerta_id: Mapped[int | None] = mapped_column(ForeignKey("mensagem_saida.id", ondelete="SET NULL"))
    encerramento_avisado_em: Mapped[datetime | None] = mapped_column(DATA)
    # Aberta antes desta versão (o id da mensagem não era guardado): ao encerrar, conta como alerta enviado.
    alerta_sem_registro: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
```

Os campos `Mapped[MotivoEncerramento | None]` com `Text`: o SQLAlchemy grava o valor do StrEnum como texto; ao ler, volta `str`. Para voltar o enum, use `mapped_column(Text)` e compare sempre com `MotivoEncerramento.X` (StrEnum compara igual à string) — não use `is`.

Em `LIMITES_CONFIG_AMAZON` acrescente `"carencia_encerramento_min": (0, 240),`; em `PADROES_CONFIG_AMAZON`, `"carencia_encerramento_min": 30,`; na `ConfigAmazon`, depois de `descoberta_casados_dias`: `carencia_encerramento_min: Mapped[int] = mapped_column(Integer)`.

- [ ] **Step 4: Migração**

```python
"""fim da oportunidade: motivo de encerramento, carência (em risco), menor preço, alertas, mensagem do alerta

Revision ID: e7c3a9d5b2f4
Revises: d4b8e2f6a3c1
Create Date: 2026-10-20 12:00:00

As oportunidades existentes recebem menor_preco = preco_amazon e alertas = 1; as abertas ficam com
alerta_sem_registro (o alerta delas saiu antes de o id da mensagem ser guardado). O downgrade tira tudo.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7c3a9d5b2f4"
down_revision: Union[str, Sequence[str], None] = "d4b8e2f6a3c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MOTIVOS = (
    "'casamento_desfeito', 'sem_leitura', 'liga_desatualizada', 'oferta_sumiu', 'vendedor', 'liga_caiu', "
    "'preco_subiu'"
)
DATA = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("oportunidade", sa.Column("motivo_encerramento", sa.Text(), nullable=True))
    op.add_column("oportunidade", sa.Column("em_risco_desde", DATA, nullable=True))
    op.add_column("oportunidade", sa.Column("motivo_risco", sa.Text(), nullable=True))
    op.add_column("oportunidade", sa.Column("menor_preco", sa.Numeric(12, 2), nullable=True))
    op.add_column("oportunidade", sa.Column("alertas", sa.Integer(), server_default="1", nullable=False))
    op.add_column(
        "oportunidade",
        sa.Column(
            "mensagem_alerta_id", sa.Integer(), sa.ForeignKey("mensagem_saida.id", ondelete="SET NULL"), nullable=True
        ),
    )
    op.add_column("oportunidade", sa.Column("encerramento_avisado_em", DATA, nullable=True))
    op.add_column(
        "oportunidade", sa.Column("alerta_sem_registro", sa.Boolean(), server_default="false", nullable=False)
    )
    op.execute("UPDATE oportunidade SET menor_preco = preco_amazon")
    op.execute("UPDATE oportunidade SET alerta_sem_registro = true WHERE fechada_em IS NULL")
    op.alter_column("oportunidade", "menor_preco", nullable=False)
    op.create_check_constraint(
        "ck_oportunidade_motivo_encerramento", "oportunidade", f"motivo_encerramento IN ({MOTIVOS})"
    )
    op.create_check_constraint("ck_oportunidade_motivo_risco", "oportunidade", f"motivo_risco IN ({MOTIVOS})")
    op.add_column(
        "config_amazon", sa.Column("carencia_encerramento_min", sa.Integer(), server_default="30", nullable=False)
    )
    op.create_check_constraint(
        "ck_config_amazon_carencia_encerramento_min", "config_amazon", "carencia_encerramento_min BETWEEN 0 AND 240"
    )


def downgrade() -> None:
    op.drop_constraint("ck_config_amazon_carencia_encerramento_min", "config_amazon", type_="check")
    op.drop_column("config_amazon", "carencia_encerramento_min")
    op.drop_constraint("ck_oportunidade_motivo_risco", "oportunidade", type_="check")
    op.drop_constraint("ck_oportunidade_motivo_encerramento", "oportunidade", type_="check")
    for coluna in (
        "alerta_sem_registro", "encerramento_avisado_em", "mensagem_alerta_id", "alertas", "menor_preco",
        "motivo_risco", "em_risco_desde", "motivo_encerramento",
    ):
        op.drop_column("oportunidade", coluna)
```

Confira o tipo de `DINHEIRO` em `models.py` (procure `DINHEIRO =`) e use o mesmo `Numeric(p, s)` em `menor_preco`; confira também como a migração `7d3f1a2b9c4e_amazon.py` declara `DATA` e copie.

- [ ] **Step 5: Ajustar quem cria `Oportunidade` e `ConfigAmazon`**

`menor_preco` é NOT NULL: em `repositorio_amazon.abrir_oportunidade` passe `menor_preco=preco_amazon`. Procure outros `Oportunidade(` em `src/` e `tests/` (`rg "Oportunidade\(" src tests`) e acrescente `menor_preco=` com o mesmo valor do `preco_amazon`. A linha de `config_amazon` é criada a partir de `PADROES_CONFIG_AMAZON` (confira com `rg PADROES_CONFIG_AMAZON src`): o padrão novo já entra.

- [ ] **Step 6: Rodar os testes**

Run: `uv run pytest tests/db -q`
Expected: PASS (inclui `tests/db/test_config_banco.py`, que cobre limites e padrões).

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/db tests/db/test_migracao_fim_oportunidade.py
git commit -m "feat: opportunity end reason, risk window and alert message columns"
```

---

### Task 2: Motor — motivo e carência

**Files:**
- Modify: `src/tcg_sniper/oportunidades/motor.py`
- Test: `tests/oportunidades/test_motor.py`

**Interfaces:**
- Consumes: `MotivoEncerramento` (Task 1), `ConfigAmazon.carencia_encerramento_min`.
- Produces:
  - `Regras.carencia_encerramento_min: int` (preenchido por `Regras.de`);
  - `@dataclass(frozen=True) class Aberta: preco_alertado: Decimal; preco_liga: Decimal; em_risco_desde: datetime | None = None`;
  - `@dataclass(frozen=True) class Decisao: acao: Acao; motivo: MotivoEncerramento | None = None`;
  - `Acao.EM_RISCO = "em_risco"`, `Acao.RECUPERAR = "recuperar"`;
  - `motivo_inelegivel(leitura, ref, regras, agora, preco_liga_anterior: Decimal | None = None) -> MotivoEncerramento | None`;
  - `decidir(leitura, ref, regras, agora, aberta: Aberta | None) -> Decisao`.

- [ ] **Step 1: Testes novos (falham)**

Acrescente a `tests/oportunidades/test_motor.py` (reaproveite os construtores de `Leitura`, `RefLiga`, `Regras` e `AGORA` que o arquivo já tem; se os nomes forem outros, ajuste):

```python
from datetime import timedelta
from decimal import Decimal

from tcg_sniper.db.models import Envio, MotivoEncerramento as M
from tcg_sniper.oportunidades.motor import Aberta, Acao, Leitura, RefLiga, Regras, decidir, motivo_inelegivel

AGORA = datetime.fromisoformat("2026-10-20T15:00:00+00:00")
REGRAS = Regras(
    desconto_min_pct=25, realerta_queda_pct=5, liga_preco_max_idade_h=48,
    vendedor_min_positivas_pct=90, vendedor_min_avaliacoes=100, carencia_encerramento_min=30,
)
REF = RefLiga(Decimal("1000"), AGORA - timedelta(hours=1))
BOA = Leitura(Decimal("700"), Envio.AMAZON, None)


def test_motivo_none_quando_elegivel():
    assert motivo_inelegivel(BOA, REF, REGRAS, AGORA) is None


def test_motivos_em_ordem():
    velha = RefLiga(Decimal("1000"), AGORA - timedelta(hours=49))
    sem_preco = Leitura(None, Envio.DESCONHECIDO, None)
    lojista = Leitura(Decimal("700"), Envio.LOJISTA, None)
    cara = Leitura(Decimal("800"), Envio.AMAZON, None)
    assert motivo_inelegivel(sem_preco, velha, REGRAS, AGORA) is M.LIGA_DESATUALIZADA
    assert motivo_inelegivel(sem_preco, REF, REGRAS, AGORA) is M.OFERTA_SUMIU
    assert motivo_inelegivel(lojista, REF, REGRAS, AGORA) is M.VENDEDOR
    assert motivo_inelegivel(cara, REF, REGRAS, AGORA) is M.PRECO_SUBIU
    # 800 dá 25% contra a Liga de antes (1.100), não contra a de agora (1.000): foi a Liga que caiu
    assert motivo_inelegivel(cara, REF, REGRAS, AGORA, preco_liga_anterior=Decimal("1100")) is M.LIGA_CAIU


def test_primeira_leitura_ruim_marca_risco():
    aberta = Aberta(Decimal("700"), Decimal("1000"))
    d = decidir(Leitura(Decimal("800"), Envio.AMAZON, None), REF, REGRAS, AGORA, aberta)
    assert (d.acao, d.motivo) == (Acao.EM_RISCO, M.PRECO_SUBIU)


def test_risco_antes_da_carencia_continua_em_risco():
    aberta = Aberta(Decimal("700"), Decimal("1000"), em_risco_desde=AGORA - timedelta(minutes=29))
    assert decidir(Leitura(None, Envio.DESCONHECIDO, None), REF, REGRAS, AGORA, aberta).acao is Acao.EM_RISCO


def test_carencia_vencida_fecha_com_o_motivo_da_leitura():
    aberta = Aberta(Decimal("700"), Decimal("1000"), em_risco_desde=AGORA - timedelta(minutes=30))
    d = decidir(Leitura(None, Envio.DESCONHECIDO, None), REF, REGRAS, AGORA, aberta)
    assert (d.acao, d.motivo) == (Acao.FECHAR, M.OFERTA_SUMIU)


def test_carencia_zero_fecha_na_primeira_leitura_ruim():
    regras = dataclasses.replace(REGRAS, carencia_encerramento_min=0)
    d = decidir(Leitura(None, Envio.DESCONHECIDO, None), REF, regras, AGORA, Aberta(Decimal("700"), Decimal("1000")))
    assert d.acao is Acao.FECHAR


def test_elegivel_em_risco_recupera():
    aberta = Aberta(Decimal("700"), Decimal("1000"), em_risco_desde=AGORA - timedelta(minutes=10))
    assert decidir(BOA, REF, REGRAS, AGORA, aberta).acao is Acao.RECUPERAR


def test_em_risco_com_queda_realerta():
    aberta = Aberta(Decimal("700"), Decimal("1000"), em_risco_desde=AGORA - timedelta(minutes=10))
    assert decidir(Leitura(Decimal("650"), Envio.AMAZON, None), REF, REGRAS, AGORA, aberta).acao is Acao.REALERTAR


def test_sem_aberta_inelegivel_nada_e_elegivel_abre():
    assert decidir(Leitura(None, Envio.DESCONHECIDO, None), REF, REGRAS, AGORA, None).acao is Acao.NADA
    assert decidir(BOA, REF, REGRAS, AGORA, None).acao is Acao.ABRIR
```

(Ponha `import dataclasses` e `from datetime import datetime` no topo se faltarem. Confira o nome do membro "lojista com envio próprio" em `Envio` e troque `Envio.LOJISTA` pelo nome real.)

Atualize os testes de `decidir` que já existem no arquivo: onde passavam `preco_alertado` (Decimal ou None), passe `Aberta(preco_alertado, <preco_liga do teste>)` ou `None`, e compare `.acao` em vez do retorno direto. Onde um teste antigo esperava `Acao.FECHAR` na primeira leitura ruim, use `dataclasses.replace(regras, carencia_encerramento_min=0)`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/oportunidades/test_motor.py -q`
Expected: FAIL (`ImportError: cannot import name 'Aberta'`).

- [ ] **Step 3: Implementação**

Em `motor.py`:

```python
from tcg_sniper.db.models import ConfigAmazon, Envio, MotivoEncerramento


@dataclass(frozen=True)
class Regras:
    desconto_min_pct: int
    realerta_queda_pct: int
    liga_preco_max_idade_h: int
    vendedor_min_positivas_pct: int
    vendedor_min_avaliacoes: int
    carencia_encerramento_min: int = 30

    @classmethod
    def de(cls, config: ConfigAmazon) -> "Regras":
        return cls(
            desconto_min_pct=config.desconto_min_pct,
            realerta_queda_pct=config.realerta_queda_pct,
            liga_preco_max_idade_h=config.liga_preco_max_idade_h,
            vendedor_min_positivas_pct=config.vendedor_min_positivas_pct,
            vendedor_min_avaliacoes=config.vendedor_min_avaliacoes,
            carencia_encerramento_min=config.carencia_encerramento_min,
        )


class Acao(StrEnum):
    ABRIR = "abrir"
    REALERTAR = "realertar"
    ATUALIZAR = "atualizar"
    RECUPERAR = "recuperar"  # estava em risco e voltou a ser elegível
    EM_RISCO = "em_risco"  # deixou de ser elegível; a carência ainda não venceu
    FECHAR = "fechar"
    NADA = "nada"


@dataclass(frozen=True)
class Aberta:
    """O que o motor precisa da oportunidade aberta do anúncio."""

    preco_alertado: Decimal
    preco_liga: Decimal  # o "À partir de" gravado na última leitura que a manteve aberta
    em_risco_desde: datetime | None = None


@dataclass(frozen=True)
class Decisao:
    acao: Acao
    motivo: MotivoEncerramento | None = None  # EM_RISCO e FECHAR


def motivo_inelegivel(
    leitura: Leitura, ref: RefLiga, regras: Regras, agora: datetime, preco_liga_anterior: Decimal | None = None
) -> MotivoEncerramento | None:
    """Por que a leitura não é elegível, na ordem da spec; None quando é. `preco_liga_anterior` separa
    "a Liga caiu" (a Amazon ainda daria o desconto contra a Liga de antes) de "a Amazon subiu"."""
    if not _referencia_valida(ref, regras, agora):
        return MotivoEncerramento.LIGA_DESATUALIZADA
    if leitura.preco is None or leitura.preco <= 0:
        return MotivoEncerramento.OFERTA_SUMIU
    if not vendedor_elegivel(leitura.envio, leitura.vendedor, regras):
        return MotivoEncerramento.VENDEDOR
    if atinge_desconto(leitura.preco, ref.preco_a_partir, regras.desconto_min_pct):
        return None
    if atinge_desconto(leitura.preco, preco_liga_anterior, regras.desconto_min_pct):
        return MotivoEncerramento.LIGA_CAIU
    return MotivoEncerramento.PRECO_SUBIU


def decidir(leitura: Leitura, ref: RefLiga, regras: Regras, agora: datetime, aberta: Aberta | None) -> Decisao:
    """`aberta`: a oportunidade aberta do anúncio (None se não há). Leitura ruim com aberta: EM_RISCO até
    a carência vencer (contada de `em_risco_desde`), depois FECHAR; carência 0 fecha na hora."""
    motivo = motivo_inelegivel(leitura, ref, regras, agora, aberta.preco_liga if aberta else None)
    if motivo is not None:
        if aberta is None:
            return Decisao(Acao.NADA)
        carencia = timedelta(minutes=regras.carencia_encerramento_min)
        desde = aberta.em_risco_desde or agora
        if agora - desde >= carencia:
            return Decisao(Acao.FECHAR, motivo)
        return Decisao(Acao.EM_RISCO, motivo)
    if aberta is None:
        return Decisao(Acao.ABRIR)
    if leitura.preco * CEM <= aberta.preco_alertado * (CEM - regras.realerta_queda_pct):
        return Decisao(Acao.REALERTAR)
    if aberta.em_risco_desde is not None:
        return Decisao(Acao.RECUPERAR)
    return Decisao(Acao.ATUALIZAR)
```

Mantenha `elegivel()` (usado em outros lugares; confira com `rg "motor.elegivel|elegivel\(" src`) e reescreva-a como `return motivo_inelegivel(leitura, ref, regras, agora) is None`.

O monitor ainda chama a assinatura antiga; ele é ajustado na Tarefa 6. Para a suíte não quebrar entre as tarefas, nesta tarefa ajuste só a chamada mínima em `coletor_amazon/monitor.py` (duas ocorrências de `motor.decidir(...)`):

```python
aberta_motor = (
    motor.Aberta(aberta.preco_alertado, aberta.preco_liga, aberta.em_risco_desde) if aberta else None
)
decisao = motor.decidir(leitura, ref, motor.Regras.de(ctx.cfg), agora, aberta_motor)
acao = decisao.acao
if acao in (motor.Acao.EM_RISCO, motor.Acao.RECUPERAR):  # tratadas na Tarefa 6
    acao = motor.Acao.ATUALIZAR if acao is motor.Acao.RECUPERAR else motor.Acao.NADA
```

(Na `_decidir` o bloco `if acao is motor.Acao.REALERTAR and conferido is None and aberta.alerta_conferido:` continua logo depois, como está.)

- [ ] **Step 4: Rodar**

Run: `uv run pytest tests/oportunidades tests/coletor_amazon -q`
Expected: PASS, menos `test_sem_ofertas_registra_preco_nulo_e_fecha_a_oportunidade` em `tests/coletor_amazon/test_monitor.py`, que agora não fecha (carência). Ajuste esse teste: na fixture do contexto use `cfg` com `carencia_encerramento_min = 0` só nele (procure como o teste monta `cfg`; um `cfg.carencia_encerramento_min = 0` antes de `ler_anuncio` basta se for objeto ORM, ou `dataclasses.replace` se for dataclass).

- [ ] **Step 5: Commit**

```bash
git add src/tcg_sniper/oportunidades/motor.py src/tcg_sniper/coletor_amazon/monitor.py tests/oportunidades/test_motor.py tests/coletor_amazon/test_monitor.py
git commit -m "feat: motor returns the end reason and waits a grace period before closing"
```

---

### Task 3: Avisos novos e texto do encerramento

**Files:**
- Modify: `src/tcg_sniper/avisos/catalogo.py`, `src/tcg_sniper/oportunidades/mensagens.py`
- Test: `tests/oportunidades/test_dados_encerramento.py`

**Interfaces:**
- Consumes: `MotivoEncerramento`.
- Produces:
  - `TipoAviso.OPORTUNIDADE_ENCERRADA = "oportunidade_encerrada"`, `TipoAviso.OPORTUNIDADE_CORRIGIDA = "oportunidade_corrigida"`, `TipoAviso.OPORTUNIDADE_ENCERRADA_TECNICO = "oportunidade_encerrada_tecnico"`;
  - `Severidade.ENCERRADA` (⏹️), `Severidade.CORRECAO` (⚠️);
  - em `oportunidades/mensagens.py`: `ROTULOS_MOTIVO: dict[MotivoEncerramento, str]`, `tipo_do_encerramento(motivo) -> TipoAviso`, `dados_encerramento(*, motivo, nome_produto, aberta_em, fechada_em, preco_alertado, preco_atual, preco_liga, url_amazon, zona) -> Dados`.

- [ ] **Step 1: Testes (falham)**

```python
# tests/oportunidades/test_dados_encerramento.py
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from tcg_sniper.avisos.catalogo import CATALOGO, TipoAviso
from tcg_sniper.avisos.formato import aviso_de, formatar
from tcg_sniper.db.models import MotivoEncerramento as M
from tcg_sniper.notificador.base import Destino
from tcg_sniper.oportunidades.mensagens import dados_encerramento, tipo_do_encerramento

SP = ZoneInfo("America/Sao_Paulo")
ABERTA = datetime.fromisoformat("2026-10-18T13:15:00+00:00")  # 10:15 em São Paulo
FECHADA = ABERTA + timedelta(hours=3, minutes=20)


def texto(motivo, preco_atual=Decimal("1549.90")):
    dados = dados_encerramento(
        motivo=motivo, nome_produto="Final Fantasy - Caixa de Booster de Jogo", aberta_em=ABERTA,
        fechada_em=FECHADA, preco_alertado=Decimal("1299.90"), preco_atual=preco_atual,
        preco_liga=Decimal("1589.00"), url_amazon="https://www.amazon.com.br/dp/B0TESTE123", zona=SP,
    )
    tipo = tipo_do_encerramento(motivo)
    return tipo, formatar(aviso_de(tipo, dados, FECHADA), SP, None, estrito=True)


def test_preco_subiu_vai_para_o_grupo_de_oportunidades():
    tipo, t = texto(M.PRECO_SUBIU)
    assert tipo is TipoAviso.OPORTUNIDADE_ENCERRADA
    assert CATALOGO[tipo].grupo is Destino.OPORTUNIDADES
    assert "Oferta encerrada · preço subiu" in t
    assert "Durou 3 h 20 min (desde 18/10 10:15)" in t
    assert "R$ 1.299,90" in t and "R$ 1.549,90" in t and "R$ 1.589,00" in t


def test_oferta_sumiu_mostra_indisponivel():
    _, t = texto(M.OFERTA_SUMIU, preco_atual=None)
    assert "oferta sumiu" in t and "indisponível" in t


def test_casamento_desfeito_e_alerta_corrigido():
    tipo, t = texto(M.CASAMENTO_DESFEITO)
    assert tipo is TipoAviso.OPORTUNIDADE_CORRIGIDA
    assert "Alerta corrigido" in t
    assert "O alerta de 18/10 10:15 era de outro produto: desconsidere." in t


def test_tecnicos_vao_para_o_admin():
    for motivo in (M.SEM_LEITURA, M.LIGA_DESATUALIZADA):
        tipo, t = texto(motivo)
        assert tipo is TipoAviso.OPORTUNIDADE_ENCERRADA_TECNICO
        assert CATALOGO[tipo].grupo is Destino.ADMIN


def test_duracao_curta():
    dados = dados_encerramento(
        motivo=M.PRECO_SUBIU, nome_produto="X", aberta_em=ABERTA, fechada_em=ABERTA + timedelta(minutes=45),
        preco_alertado=Decimal("10"), preco_atual=Decimal("20"), preco_liga=None, url_amazon=None, zona=SP,
    )
    assert "Durou 45 min (desde 18/10 10:15)" in dados.linhas[0]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/oportunidades/test_dados_encerramento.py -q`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Catálogo**

Em `avisos/catalogo.py`: em `Severidade` acrescente `ENCERRADA = "encerrada"` e `CORRECAO = "correcao"`; em `EMOJI`, `Severidade.ENCERRADA: "⏹️"` e `Severidade.CORRECAO: "⚠️"`; em `TipoAviso`, depois de `OPORTUNIDADE`, os três tipos; no `CATALOGO`, depois de `TipoAviso.OPORTUNIDADE`:

```python
    TipoAviso.OPORTUNIDADE_ENCERRADA: DefinicaoAviso(
        Severidade.ENCERRADA, Destino.OPORTUNIDADES, "Oferta encerrada", MONITOR,
        "Uma oportunidade avisada acabou (preço subiu, oferta sumiu, Liga baixou ou vendedor mudou), depois da "
        "carência de Configurações → Amazon.",
        Dados(
            titulo_extra="preço subiu",
            destaque="Final Fantasy - Caixa de Booster de Jogo",
            linhas=(
                "Durou 3 h 20 min (desde 18/10 10:15)",
                ("Alerta: ", Negrito("R$ 1.299,90"), " → agora: ", Negrito("R$ 1.549,90")),
                "Liga: a partir de R$ 1.589,00",
            ),
            link_produto="https://www.amazon.com.br/dp/B0TESTE123",
        ),
    ),
    TipoAviso.OPORTUNIDADE_CORRIGIDA: DefinicaoAviso(
        Severidade.CORRECAO, Destino.OPORTUNIDADES, "Alerta corrigido", CASAMENTOS,
        "O casamento de uma oportunidade avisada foi desfeito, ignorado ou trocado: o alerta era de outro produto.",
        Dados(
            destaque="Final Fantasy - Caixa de Booster de Jogo",
            linhas=("O alerta de 18/10 10:15 era de outro produto: desconsidere.",),
        ),
    ),
    TipoAviso.OPORTUNIDADE_ENCERRADA_TECNICO: DefinicaoAviso(
        A, Destino.ADMIN, "Oportunidade encerrada", MONITOR,
        "Uma oportunidade avisada fechou por motivo técnico (preço da Liga desatualizado ou anúncio sem leitura); "
        "a oferta pode continuar existindo.",
        Dados(
            titulo_extra="anúncio sem leitura",
            destaque="Final Fantasy - Caixa de Booster de Jogo",
            linhas=("Durou 26 h 5 min (desde 18/10 10:15)",),
        ),
        acao="Confira Admin → Serviços (LigaMagic e Amazon (monitor e checkout)).",
    ),
```

e a constante de origem, junto das outras: `CASAMENTOS = "casamentos"`. (Se `A` ainda não estiver definido antes desse ponto, ele está: `F, A, C = ...` vem antes do `CATALOGO`.)

- [ ] **Step 4: Texto do encerramento**

Em `oportunidades/mensagens.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from tcg_sniper.avisos.catalogo import Dados, Negrito, TipoAviso, Trecho
from tcg_sniper.db.models import Envio, MotivoEncerramento

ROTULOS_MOTIVO = {
    MotivoEncerramento.PRECO_SUBIU: "preço subiu",
    MotivoEncerramento.OFERTA_SUMIU: "oferta sumiu",
    MotivoEncerramento.LIGA_CAIU: "Liga baixou",
    MotivoEncerramento.VENDEDOR: "vendedor mudou",
    MotivoEncerramento.LIGA_DESATUALIZADA: "preço da Liga desatualizado",
    MotivoEncerramento.SEM_LEITURA: "anúncio sem leitura",
    MotivoEncerramento.CASAMENTO_DESFEITO: "casamento desfeito",
}
TECNICOS = frozenset({MotivoEncerramento.LIGA_DESATUALIZADA, MotivoEncerramento.SEM_LEITURA})


def tipo_do_encerramento(motivo: MotivoEncerramento) -> TipoAviso:
    if motivo == MotivoEncerramento.CASAMENTO_DESFEITO:
        return TipoAviso.OPORTUNIDADE_CORRIGIDA
    if motivo in TECNICOS:
        return TipoAviso.OPORTUNIDADE_ENCERRADA_TECNICO
    return TipoAviso.OPORTUNIDADE_ENCERRADA


def _duracao(inicio: datetime, fim: datetime) -> str:
    minutos = max(0, int((fim - inicio).total_seconds() // 60))
    horas, resto = divmod(minutos, 60)
    if not horas:
        return f"{resto} min"
    return f"{horas} h {resto} min" if resto else f"{horas} h"


def dados_encerramento(
    *,
    motivo: MotivoEncerramento,
    nome_produto: str,
    aberta_em: datetime,
    fechada_em: datetime,
    preco_alertado: Decimal,
    preco_atual: Decimal | None,
    preco_liga: Decimal | None,
    url_amazon: str | None,
    zona: ZoneInfo,
) -> Dados:
    """Dados dos avisos de fim da oportunidade (tipo em `tipo_do_encerramento`)."""
    desde = aberta_em.astimezone(zona).strftime("%d/%m %H:%M")
    if motivo == MotivoEncerramento.CASAMENTO_DESFEITO:
        return Dados(destaque=nome_produto, linhas=(f"O alerta de {desde} era de outro produto: desconsidere.",))
    linhas: list = [f"Durou {_duracao(aberta_em, fechada_em)} (desde {desde})"]
    if motivo not in TECNICOS:
        agora = Negrito(formatar_brl(preco_atual)) if preco_atual is not None else Negrito("indisponível")
        linhas.append(("Alerta: ", Negrito(formatar_brl(preco_alertado)), " → agora: ", agora))
        if preco_liga is not None:
            linhas.append(f"Liga: a partir de {formatar_brl(preco_liga)}")
    return Dados(
        titulo_extra=ROTULOS_MOTIVO[motivo], destaque=nome_produto, linhas=tuple(linhas),
        link_produto=url_amazon if motivo not in TECNICOS else None,
    )
```

(O import `TipoAviso` em `mensagens.py` não cria ciclo: `avisos.catalogo` só importa `notificador.base`.)

- [ ] **Step 5: Rodar**

Run: `uv run pytest tests/oportunidades tests/avisos tests/admin -q`
Expected: PASS (os testes de `tests/avisos/test_regras_globais.py` percorrem os exemplos novos; a tela Avisos lista o catálogo).

- [ ] **Step 6: Commit**

```bash
git add src/tcg_sniper/avisos/catalogo.py src/tcg_sniper/oportunidades/mensagens.py tests/oportunidades/test_dados_encerramento.py
git commit -m "feat: closed, corrected and technical opportunity notices"
```

---

### Task 4: `avisar` devolve o id da mensagem

**Files:**
- Modify: `src/tcg_sniper/avisos/servico.py`, `tests/fakes.py`
- Test: `tests/avisos/test_servico.py`

**Interfaces:**
- Produces: `servico.avisar(s, tipo, chave, dados, agora) -> int | None` (id da `mensagem_saida` enfileirada; None se desligado, se só contou a repetição ou se falhou); `Avisador.avisar_em(self, s: Session, tipo, chave, dados) -> int | None` (na sessão de quem chama); `AvisadorBanco.avisar_em`; `AvisadorFake.avisar_em` (grava o aviso como `avisar` e enfileira uma `mensagem_saida` real com o texto, devolvendo o id).

- [ ] **Step 1: Testes (falham)**

Em `tests/avisos/test_servico.py` (use a fixture `sessoes` e o `T0`/`AGORA` que o arquivo já usa):

```python
def test_avisar_devolve_o_id_da_mensagem(sessoes):
    with sessoes() as s, s.begin():
        mensagem_id = servico.avisar(s, TipoAviso.OPORTUNIDADE, "1", CATALOGO[TipoAviso.OPORTUNIDADE].exemplo, AGORA)
        assert s.get(MensagemSaida, mensagem_id).destino == "oportunidades"


def test_avisar_desligado_devolve_none(sessoes):
    with sessoes() as s, s.begin():
        servico.definir_ligado(s, TipoAviso.OPORTUNIDADE, False)
        assert servico.avisar(s, TipoAviso.OPORTUNIDADE, "1", CATALOGO[TipoAviso.OPORTUNIDADE].exemplo, AGORA) is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/avisos/test_servico.py -q`
Expected: FAIL (`avisar` devolve None).

- [ ] **Step 3: Implementação**

Em `servico.py`: `_enfileirar` devolve `repo_msg.enfileirar(...).id`; `_avisar` devolve esse id nos dois caminhos em que enfileira (abertura e lembrete) e None nos outros; `avisar`:

```python
def avisar(s: Session, tipo: TipoAviso, chave: str, dados: Dados, agora: datetime) -> int | None:
    """Registra a ocorrência; devolve o id da mensagem enfileirada (None: desligado, só contou ou falhou)."""
    try:
        with s.begin_nested():
            return _avisar(s, tipo, chave, dados, agora)
    except Exception as erro:
        if _deixar_subir(erro):
            raise
        log.exception("aviso %s (%s) não registrado", tipo.value, chave)
        return None
```

No `Protocol` `Avisador`, acrescente `def avisar_em(self, s: Session, tipo: TipoAviso, chave: str, dados: Dados) -> int | None: ...` com a docstring "Como `avisar`, mas na transação de quem chama (o id da mensagem fica junto do que a gerou)." Em `AvisadorBanco`:

```python
    def avisar_em(self, s: Session, tipo: TipoAviso, chave: str, dados: Dados) -> int | None:
        return avisar(s, tipo, chave, dados, self._relogio())
```

Em `tests/fakes.py`, no `AvisadorFake`:

```python
    def avisar_em(self, s, tipo: TipoAviso, chave: str, dados: Dados) -> int | None:
        """Como `avisar`, e enfileira a mensagem de verdade na sessão (o chamador guarda o id)."""
        self.avisar(tipo, chave, dados)
        return repo_msg.enfileirar(s, CATALOGO[tipo].grupo.value, self.mensagens[-1][1], T0).id
```

com `from tcg_sniper.db import repositorio_mensagens as repo_msg` no topo de `fakes.py`. Procure outros avisadores falsos (`rg "def resolver_todos" tests`) e acrescente `avisar_em` igual neles.

- [ ] **Step 4: Rodar**

Run: `uv run pytest tests/avisos tests/coletor_amazon -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tcg_sniper/avisos/servico.py tests/fakes.py tests/avisos/test_servico.py
git commit -m "feat: notices return the queued message id; avisar_em runs in the caller transaction"
```

---

### Task 5: Encerramento — ponto único de fechar

**Files:**
- Create: `src/tcg_sniper/oportunidades/encerramento.py`
- Test: `tests/oportunidades/test_encerramento.py`

**Interfaces:**
- Consumes: `MotivoEncerramento`, colunas da Task 1, `tipo_do_encerramento`/`dados_encerramento` (Task 3), `servico.avisar` e `zona_e_host` (Task 4), `repositorio_mensagens.descartar`.
- Produces: `encerrar(s: Session, oportunidade_id: int, motivo: MotivoEncerramento, agora: datetime) -> bool` (True se fechou agora; False se não existe ou já estava fechada).

- [ ] **Step 1: Testes (falham)**

```python
# tests/oportunidades/test_encerramento.py
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fakes import criar_anuncio, criar_preco_liga, criar_produto
from sqlalchemy import select

from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import (
    Envio, MensagemSaida, MotivoEncerramento as M, Oportunidade, StatusCasamento, StatusMensagem,
)
from tcg_sniper.oportunidades.encerramento import encerrar

AGORA = datetime.fromisoformat("2026-10-20T15:00:00+00:00")


@pytest.fixture
def oportunidade(sessoes):
    """Oportunidade aberta com alerta pendente na fila; o teste muda a situação da mensagem."""
    with sessoes() as s, s.begin():
        p = criar_produto(s, "ff", nome="Final Fantasy")
        criar_preco_liga(s, p, "1000.00", listagem_em=AGORA)
        a = criar_anuncio(s, "B0ENCERRA1", produto=p, status=StatusCasamento.CONFIRMADO)
        msg = repo_msg.enfileirar(s, "oportunidades", "alerta", AGORA - timedelta(hours=2))
        op = Oportunidade(
            anuncio_id=a.id, produto_id=p.id, preco_amazon=Decimal("700"), preco_liga=Decimal("1000"),
            desconto_pct=Decimal("30"), envio=Envio.AMAZON, aberta_em=AGORA - timedelta(hours=2),
            alertada_em=AGORA - timedelta(hours=2), preco_alertado=Decimal("700"), menor_preco=Decimal("700"),
            mensagem_alerta_id=msg.id,
        )
        s.add(op)
        s.flush()
        return op.id, msg.id


def _situacao(sessoes, msg_id, status):
    with sessoes() as s, s.begin():
        s.get(MensagemSaida, msg_id).status = status


def _avisos(s):
    return list(s.scalars(select(MensagemSaida).where(MensagemSaida.texto != "alerta")))


def test_alerta_enviado_avisa_o_grupo_e_grava_o_motivo(sessoes, oportunidade):
    op_id, msg_id = oportunidade
    _situacao(sessoes, msg_id, StatusMensagem.ENVIADA)
    with sessoes() as s, s.begin():
        assert encerrar(s, op_id, M.PRECO_SUBIU, AGORA) is True
    with sessoes() as s:
        op = s.get(Oportunidade, op_id)
        assert (op.fechada_em, op.motivo_encerramento, op.encerramento_avisado_em) == (AGORA, "preco_subiu", AGORA)
        [aviso] = _avisos(s)
        assert aviso.destino == "oportunidades" and "Oferta encerrada · preço subiu" in aviso.texto


def test_alerta_pendente_e_descartado_sem_aviso(sessoes, oportunidade):
    op_id, msg_id = oportunidade
    with sessoes() as s, s.begin():
        encerrar(s, op_id, M.OFERTA_SUMIU, AGORA)
    with sessoes() as s:
        assert s.get(MensagemSaida, msg_id).status is StatusMensagem.DESCARTADA
        assert _avisos(s) == [] and s.get(Oportunidade, op_id).encerramento_avisado_em is None


@pytest.mark.parametrize("status", [StatusMensagem.EXPIRADA, StatusMensagem.DESCARTADA, StatusMensagem.FALHA])
def test_alerta_que_nao_saiu_nao_avisa(sessoes, oportunidade, status):
    op_id, msg_id = oportunidade
    _situacao(sessoes, msg_id, status)
    with sessoes() as s, s.begin():
        encerrar(s, op_id, M.PRECO_SUBIU, AGORA)
    with sessoes() as s:
        assert _avisos(s) == []


def test_sem_mensagem_nao_avisa_mas_alerta_sem_registro_avisa(sessoes, oportunidade):
    op_id, _ = oportunidade
    with sessoes() as s, s.begin():
        s.get(Oportunidade, op_id).mensagem_alerta_id = None
    with sessoes() as s, s.begin():
        encerrar(s, op_id, M.PRECO_SUBIU, AGORA)
    with sessoes() as s, s.begin():
        assert _avisos(s) == []
        op = s.get(Oportunidade, op_id)
        op.fechada_em, op.alerta_sem_registro = None, True  # reabre como oportunidade de antes da versão
    with sessoes() as s, s.begin():
        encerrar(s, op_id, M.PRECO_SUBIU, AGORA)
    with sessoes() as s:
        assert len(_avisos(s)) == 1


def test_casamento_desfeito_avisa_alerta_corrigido(sessoes, oportunidade):
    op_id, msg_id = oportunidade
    _situacao(sessoes, msg_id, StatusMensagem.ENVIADA)
    with sessoes() as s, s.begin():
        encerrar(s, op_id, M.CASAMENTO_DESFEITO, AGORA)
    with sessoes() as s:
        [aviso] = _avisos(s)
        assert aviso.destino == "oportunidades" and "Alerta corrigido" in aviso.texto


def test_tecnico_vai_para_o_admin(sessoes, oportunidade):
    op_id, msg_id = oportunidade
    _situacao(sessoes, msg_id, StatusMensagem.ENVIADA)
    with sessoes() as s, s.begin():
        encerrar(s, op_id, M.SEM_LEITURA, AGORA)
    with sessoes() as s:
        [aviso] = _avisos(s)
        assert aviso.destino == "admin"


def test_segunda_chamada_nao_fecha_nem_avisa_de_novo(sessoes, oportunidade):
    op_id, msg_id = oportunidade
    _situacao(sessoes, msg_id, StatusMensagem.ENVIADA)
    with sessoes() as s, s.begin():
        assert encerrar(s, op_id, M.PRECO_SUBIU, AGORA) is True
    with sessoes() as s, s.begin():
        assert encerrar(s, op_id, M.CASAMENTO_DESFEITO, AGORA + timedelta(minutes=1)) is False
    with sessoes() as s:
        assert len(_avisos(s)) == 1 and s.get(Oportunidade, op_id).motivo_encerramento == "preco_subiu"


def test_limpa_o_risco(sessoes, oportunidade):
    op_id, _ = oportunidade
    with sessoes() as s, s.begin():
        op = s.get(Oportunidade, op_id)
        op.em_risco_desde, op.motivo_risco = AGORA - timedelta(minutes=40), M.OFERTA_SUMIU
    with sessoes() as s, s.begin():
        encerrar(s, op_id, M.OFERTA_SUMIU, AGORA)
    with sessoes() as s:
        op = s.get(Oportunidade, op_id)
        assert (op.em_risco_desde, op.motivo_risco) == (None, None)
```

Confira a assinatura de `criar_anuncio` em `tests/fakes.py` (linha ~116) e ajuste os argumentos se for diferente.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/oportunidades/test_encerramento.py -q`
Expected: FAIL (`ModuleNotFoundError: tcg_sniper.oportunidades.encerramento`).

- [ ] **Step 3: Implementação**

```python
# src/tcg_sniper/oportunidades/encerramento.py
"""Fim de uma oportunidade: o único lugar que fecha (monitor, busca e casamento), grava o motivo e decide o
aviso pela situação da mensagem do alerta (spec 2026-10-20-fim-da-oportunidade):

- alerta enviado (ou oportunidade de antes desta versão, `alerta_sem_registro`): avisa o grupo do motivo;
- alerta ainda pendente na fila: descarta o alerta (perdeu a validade) e não avisa;
- alerta expirado, descartado, com falha ou sem mensagem: não avisa (ninguém viu o alerta).

Roda na transação de quem chama; o aviso roda em savepoint (`avisos.servico.avisar`): falha nele não desfaz o
encerramento."""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from tcg_sniper.avisos import servico as avisos
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import (
    AnuncioAmazon, MensagemSaida, MotivoEncerramento, Oportunidade, PrecoAtualAmazon, PrecoAtualLiga, ProdutoLiga,
    StatusMensagem,
)
from tcg_sniper.oportunidades.mensagens import dados_encerramento, tipo_do_encerramento

log = logging.getLogger(__name__)


def _alerta_saiu(s: Session, op: Oportunidade, agora: datetime) -> bool:
    mensagem = s.get(MensagemSaida, op.mensagem_alerta_id) if op.mensagem_alerta_id else None
    if mensagem is not None and mensagem.status is StatusMensagem.PENDENTE:
        repo_msg.descartar(s, mensagem.id, agora)
        return False
    if op.alerta_sem_registro:
        return True
    return mensagem is not None and mensagem.status is StatusMensagem.ENVIADA


def encerrar(s: Session, oportunidade_id: int, motivo: MotivoEncerramento, agora: datetime) -> bool:
    op = s.get(Oportunidade, oportunidade_id, with_for_update=True, populate_existing=True)
    if op is None or op.fechada_em is not None:
        return False
    op.fechada_em, op.motivo_encerramento = agora, motivo
    op.em_risco_desde = op.motivo_risco = None
    s.flush()
    if not _alerta_saiu(s, op, agora):
        return True
    produto = s.get(ProdutoLiga, op.produto_id)
    anuncio = s.get(AnuncioAmazon, op.anuncio_id)
    atual = s.get(PrecoAtualAmazon, op.anuncio_id)
    liga = s.get(PrecoAtualLiga, op.produto_id)
    zona, _ = avisos.zona_e_host(s)
    dados = dados_encerramento(
        motivo=motivo, nome_produto=produto.nome, aberta_em=op.aberta_em, fechada_em=agora,
        preco_alertado=op.preco_alertado, preco_atual=atual.preco if atual else None,
        preco_liga=liga.preco_a_partir if liga else None, url_amazon=anuncio.url if anuncio else None, zona=zona,
    )
    if avisos.avisar(s, tipo_do_encerramento(motivo), str(op.id), dados, agora) is not None:
        op.encerramento_avisado_em = agora
        s.flush()
    return True
```

- [ ] **Step 4: Rodar**

Run: `uv run pytest tests/oportunidades -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/tcg_sniper/oportunidades/encerramento.py tests/oportunidades/test_encerramento.py
git commit -m "feat: single opportunity close point with the end notice"
```

---

### Task 6: Monitor — risco, recuperação, menor preço e alerta ligado

**Files:**
- Modify: `src/tcg_sniper/coletor_amazon/monitor.py` (`_aplicar` ~195–215, `_decidir` ~222–270, `aplicar_conferencia` ~345–380), `src/tcg_sniper/db/repositorio_amazon.py` (`abrir_oportunidade`, `atualizar_oportunidade`, `fechar_oportunidade` ~318–368)
- Test: `tests/coletor_amazon/test_monitor.py`

**Interfaces:**
- Consumes: `motor.Aberta`, `motor.Decisao`, `Acao.EM_RISCO/RECUPERAR` (Task 2), `Avisador.avisar_em` (Task 4), `encerramento.encerrar` (Task 5).
- Produces: `repo.atualizar_oportunidade(..., alertou: bool, ...)` passa a atualizar `menor_preco`, somar `alertas` quando `alertou`, e limpar o risco; `repo.marcar_risco(s, op, motivo, agora) -> None`; `repo.fechar_oportunidade` é removida.

- [ ] **Step 1: Testes de integração (falham)**

Em `tests/coletor_amazon/test_monitor.py`, use o padrão dos testes que já existem (`contexto(sessoes, config, paginas, checkout=False)`, `painel(amazon("R$ 700,00"))`, `ler_anuncio(ctx, anuncio, ASIN)` e `Relogio`; confira como o arquivo passa o relógio ao `ContextoBusca` e reaproveite). Acrescente:

```python
def _aberta(sessoes):
    with sessoes() as s:
        return s.scalar(select(Oportunidade).order_by(Oportunidade.id.desc()))


def _ler(sessoes, config, preco, quando, ler_anuncio_id):
    """Uma leitura do monitor em `quando` com a Amazon vendendo a `preco` (None: sem ofertas)."""
    pagina = painel(amazon(preco)) if preco else html_ofertas([])  # confira o helper de painel vazio do arquivo
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): pagina}, checkout=False, agora=quando)
    ler_anuncio(ctx, ler_anuncio_id, ASIN)
    return avisador


def _mensagens(sessoes):
    with sessoes() as s:
        return [m.texto for m in s.scalars(select(MensagemSaida).order_by(MensagemSaida.id))]


def test_oscilacao_curta_nao_fecha_nem_avisa(sessoes, config, anuncio):
    _ler(sessoes, config, "R$ 700,00", AGORA, anuncio)
    _ler(sessoes, config, "R$ 800,00", AGORA + timedelta(minutes=15), anuncio)  # em risco
    op = _aberta(sessoes)
    assert op.fechada_em is None and op.em_risco_desde == AGORA + timedelta(minutes=15)
    _ler(sessoes, config, "R$ 700,00", AGORA + timedelta(minutes=30), anuncio)  # recupera
    op = _aberta(sessoes)
    assert (op.fechada_em, op.em_risco_desde, op.motivo_risco) == (None, None, None)
    assert len(_mensagens(sessoes)) == 1  # só o alerta da abertura


def test_ruim_por_30_min_fecha_com_motivo_e_avisa_uma_vez(sessoes, config, anuncio):
    _ler(sessoes, config, "R$ 700,00", AGORA, anuncio)
    with sessoes() as s, s.begin():  # o alerta saiu
        s.get(MensagemSaida, _aberta(sessoes).mensagem_alerta_id).status = StatusMensagem.ENVIADA
    _ler(sessoes, config, "R$ 800,00", AGORA + timedelta(minutes=15), anuncio)
    _ler(sessoes, config, "R$ 800,00", AGORA + timedelta(minutes=45), anuncio)
    op = _aberta(sessoes)
    assert op.fechada_em == AGORA + timedelta(minutes=45) and op.motivo_encerramento == "preco_subiu"
    textos = _mensagens(sessoes)
    assert len(textos) == 2 and "Oferta encerrada · preço subiu" in textos[1]


def test_abertura_guarda_a_mensagem_e_realerta_soma(sessoes, config, anuncio):
    _ler(sessoes, config, "R$ 700,00", AGORA, anuncio)
    op = _aberta(sessoes)
    assert op.mensagem_alerta_id is not None and op.alertas == 1 and op.menor_preco == Decimal("700.00")
    _ler(sessoes, config, "R$ 800,00", AGORA + timedelta(minutes=15), anuncio)  # em risco
    _ler(sessoes, config, "R$ 650,00", AGORA + timedelta(minutes=30), anuncio)  # queda de 7%: realerta
    op = _aberta(sessoes)
    assert op.alertas == 2 and op.menor_preco == Decimal("650.00") and op.em_risco_desde is None
    assert op.fechada_em is None
```

Se `contexto(...)` não aceitar `agora=`, acrescente esse parâmetro opcional à função `contexto` do arquivo (passando um `Relogio(agora)` ao `ContextoBusca` do mesmo jeito que o teste de relógio existente faz). Se o arquivo não tiver helper de painel sem ofertas, use o HTML que `test_sem_ofertas_registra_preco_nulo_e_fecha_a_oportunidade` usa.

Importe `MensagemSaida`, `StatusMensagem` de `tcg_sniper.db.models` no topo.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/coletor_amazon/test_monitor.py -q`
Expected: FAIL nos três testes novos (risco não gravado; `mensagem_alerta_id` vazio).

- [ ] **Step 3: Repositório**

Em `repositorio_amazon.py`:

```python
def atualizar_oportunidade(
    s: Session,
    op: Oportunidade,
    *,
    preco_amazon: Decimal,
    preco_liga: Decimal,
    desconto_pct: Decimal,
    vendedor_id: int | None,
    envio: Envio,
    alertou: bool,
    agora: datetime,
    conferido: bool,
) -> None:
    """`conferido` (obrigatório, sem padrão; só vale com `alertou`): o novo aviso sai com o preço
    conferido no checkout (True) ou com o anunciado (False). Toda leitura elegível tira o risco e acompanha
    o menor preço; o realerta soma em `alertas`."""
    op.preco_amazon, op.preco_liga, op.desconto_pct = preco_amazon, preco_liga, desconto_pct
    op.vendedor_id, op.envio = vendedor_id, envio
    op.menor_preco = min(op.menor_preco, preco_amazon)
    op.em_risco_desde = op.motivo_risco = None
    if alertou:
        op.alertada_em, op.preco_alertado, op.alerta_conferido = agora, preco_amazon, conferido
        op.alertas += 1
    s.flush()


def marcar_risco(s: Session, op: Oportunidade, motivo: MotivoEncerramento, agora: datetime) -> None:
    """Leitura não elegível dentro da carência: guarda desde quando (a primeira) e o motivo (o da última)."""
    if op.em_risco_desde is None:
        op.em_risco_desde = agora
    op.motivo_risco = motivo
    s.flush()
```

Apague `fechar_oportunidade` (o monitor passa a usar o encerramento). `abrir_oportunidade` já recebeu `menor_preco=preco_amazon` na Tarefa 1. Importe `MotivoEncerramento`.

- [ ] **Step 4: Monitor**

Troque `_aplicar` para receber a `Decisao` e devolver a oportunidade que recebeu o alerta:

```python
def _aplicar(s, decisao, aberta, linha, leitura, ref, vendedor_id, agora, conferido: bool) -> Oportunidade | None:
    """Grava a decisão do motor. Devolve a oportunidade aberta ou atualizada (None em NADA, EM_RISCO e
    FECHAR). `conferido`: o preço da leitura é o conferido no checkout."""
    acao = decisao.acao
    if acao is motor.Acao.ABRIR:
        return repo.abrir_oportunidade(
            s, anuncio_id=linha.anuncio.id, produto_id=linha.produto.id, preco_amazon=leitura.preco,
            preco_liga=ref.preco_a_partir, desconto_pct=motor.desconto_pct(leitura.preco, ref.preco_a_partir),
            vendedor_id=vendedor_id, envio=leitura.envio, agora=agora, conferido=conferido,
        )
    if acao in (motor.Acao.REALERTAR, motor.Acao.ATUALIZAR, motor.Acao.RECUPERAR):
        repo.atualizar_oportunidade(
            s, aberta, preco_amazon=leitura.preco, preco_liga=ref.preco_a_partir,
            desconto_pct=motor.desconto_pct(leitura.preco, ref.preco_a_partir), vendedor_id=vendedor_id,
            envio=leitura.envio, alertou=acao is motor.Acao.REALERTAR, agora=agora, conferido=conferido,
        )
        return aberta
    if acao is motor.Acao.EM_RISCO:
        repo.marcar_risco(s, aberta, decisao.motivo, agora)
    elif acao is motor.Acao.FECHAR:
        encerramento.encerrar(s, aberta.id, decisao.motivo, agora)
    return None
```

(`from tcg_sniper.oportunidades import encerramento` e `from tcg_sniper.db.models import Oportunidade` no topo.)

Em `_decidir`, tire o remendo da Tarefa 2 e use a decisão inteira:

```python
        aberta = repo.oportunidade_aberta(s, anuncio_id)
        decisao = motor.decidir(leitura, ref, motor.Regras.de(ctx.cfg), agora, _aberta_motor(aberta))
        if decisao.acao is motor.Acao.REALERTAR and conferido is None and aberta.alerta_conferido:
            # O último aviso foi com o conferido; o anunciado não tem os impostos e parece mais barato:
            # só atualiza, sem aviso, até haver um novo preço conferido.
            decisao = motor.Decisao(motor.Acao.ATUALIZAR)
        vendedor_id = melhor.vendedor.id if melhor and melhor.vendedor else None
        op = _aplicar(s, decisao, aberta, linha, leitura, ref, vendedor_id, agora, conferido is not None)
        if decisao.acao in (motor.Acao.ABRIR, motor.Acao.REALERTAR):
            # ... monta `detalhes` exatamente como hoje ...
            aviso = _dados(linha, leitura, ref, detalhes)
            op.mensagem_alerta_id = ctx.avisador.avisar_em(s, TipoAviso.OPORTUNIDADE, str(anuncio_id), aviso)
            s.flush()
```

e apague o `if aviso is not None: ctx.avisador.avisar(...)` do fim da função (e a variável `aviso` inicializada no começo). Acrescente o auxiliar:

```python
def _aberta_motor(aberta: Oportunidade | None) -> motor.Aberta | None:
    if aberta is None:
        return None
    return motor.Aberta(aberta.preco_alertado, aberta.preco_liga, aberta.em_risco_desde)
```

Em `aplicar_conferencia`, a mesma troca: `decisao = motor.decidir(..., _aberta_motor(aberta))`, `op = _aplicar(s, decisao, ...)`, e dentro do `if decisao.acao in (ABRIR, REALERTAR):` enfileire com `ctx.avisador.avisar_em(s, ...)` e grave `op.mensagem_alerta_id`; apague o envio depois da transação.

Atualize a docstring do módulo: acrescente uma frase "Leitura não elegível com oportunidade aberta só marca o risco; o encerramento (`oportunidades.encerramento`) vem quando a carência vence."

- [ ] **Step 5: Rodar**

Run: `uv run pytest tests/coletor_amazon tests/oportunidades tests/db -q`
Expected: PASS. Testes antigos que contavam `avisador.mensagens` continuam valendo (o `avisar_em` do falso também grava lá).

- [ ] **Step 6: Commit**

```bash
git add src/tcg_sniper/coletor_amazon/monitor.py src/tcg_sniper/db/repositorio_amazon.py tests/coletor_amazon/test_monitor.py
git commit -m "feat: monitor keeps opportunities at risk during the grace period and links the alert message"
```

---

### Task 7: Busca e casamento fecham pelo encerramento

**Files:**
- Modify: `src/tcg_sniper/db/repositorio_amazon.py` (`fechar_oportunidades_sem_leitura` ~371), `src/tcg_sniper/db/repositorio_casamento.py` (`fechar_oportunidades` ~90 e docstring do módulo)
- Test: `tests/db/test_repositorio_casamento.py`, `tests/db/test_repositorio_amazon.py`

**Interfaces:**
- Consumes: `encerramento.encerrar` (Task 5).
- Produces: as duas funções mantêm nome, parâmetros e retorno (`int`, quantas fecharam).

- [ ] **Step 1: Testes (falham)**

Em `tests/db/test_repositorio_casamento.py`, no padrão do arquivo (procure um teste que confirme um par e crie uma `Oportunidade`; reaproveite o helper dele):

```python
def test_desfazer_o_confirmado_encerra_a_oportunidade_como_casamento_desfeito(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "cas-fim")
        a = criar_anuncio(s, "B0CASFIM01", produto=p, status=StatusCasamento.CONFIRMADO)
        op = Oportunidade(
            anuncio_id=a.id, produto_id=p.id, preco_amazon=Decimal("700"), preco_liga=Decimal("1000"),
            desconto_pct=Decimal("30"), envio=Envio.AMAZON, aberta_em=T0, alertada_em=T0,
            preco_alertado=Decimal("700"), menor_preco=Decimal("700"), alerta_sem_registro=True,
        )
        s.add(op)
        s.flush()
        repo_casamento.desfazer(s, a.id, p.id, T0 + timedelta(hours=1))
    with sessoes() as s:
        op = s.scalar(select(Oportunidade))
        assert op.motivo_encerramento == "casamento_desfeito" and op.fechada_em is not None
        assert any("Alerta corrigido" in m.texto for m in s.scalars(select(MensagemSaida)))
```

Em `tests/db/test_repositorio_amazon.py`:

```python
def test_sem_leitura_ha_24h_encerra_como_sem_leitura(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "sem-lei")
        a = criar_anuncio(s, "B0SEMLEI01", produto=p, status=StatusCasamento.CONFIRMADO)
        a.visto_ultimo_em = T0 - timedelta(hours=25)
        s.add(Oportunidade(
            anuncio_id=a.id, produto_id=p.id, preco_amazon=Decimal("700"), preco_liga=Decimal("1000"),
            desconto_pct=Decimal("30"), envio=Envio.AMAZON, aberta_em=T0 - timedelta(hours=26),
            alertada_em=T0 - timedelta(hours=26), preco_alertado=Decimal("700"), menor_preco=Decimal("700"),
            alerta_sem_registro=True,
        ))
        s.flush()
        assert repo.fechar_oportunidades_sem_leitura(s, T0) == 1
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)).motivo_encerramento == "sem_leitura"
        [aviso] = s.scalars(select(MensagemSaida)).all()
        assert aviso.destino == "admin"
```

(Ajuste imports: `Decimal`, `timedelta`, `select`, `Envio`, `MensagemSaida`, `Oportunidade`, `StatusCasamento`, e os helpers de `fakes`. Se `criar_anuncio` já marcar `visto_ultimo_em`, troque-o depois como acima.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/db/test_repositorio_casamento.py tests/db/test_repositorio_amazon.py -q`
Expected: FAIL (motivo vazio; nenhum aviso).

- [ ] **Step 3: Implementação**

`repositorio_casamento.py`:

```python
def fechar_oportunidades(s: Session, anuncio_id: int, agora: datetime, exceto_produto_id: int | None = None) -> int:
    """Encerra (motivo `casamento_desfeito`) as oportunidades abertas do anúncio, menos as de
    `exceto_produto_id`. Pelo encerramento: grava o motivo e avisa "alerta corrigido" a quem viu o alerta."""
    from tcg_sniper.oportunidades import encerramento  # import tardio: este módulo é base do repositorio_amazon

    condicoes = [Oportunidade.anuncio_id == anuncio_id, Oportunidade.fechada_em.is_(None)]
    if exceto_produto_id is not None:
        condicoes.append(Oportunidade.produto_id != exceto_produto_id)
    ids = list(s.scalars(select(Oportunidade.id).where(*condicoes).order_by(Oportunidade.id)))
    return sum(encerramento.encerrar(s, op_id, MotivoEncerramento.CASAMENTO_DESFEITO, agora) for op_id in ids)
```

e, na docstring do módulo, troque "Este módulo só depende dos modelos: o repositorio_amazon importa este, nunca o contrário." por "Este módulo só depende dos modelos (e, num import tardio, do encerramento das oportunidades): o repositorio_amazon importa este, nunca o contrário." Remova `update` dos imports se ficar sem uso.

`repositorio_amazon.py`:

```python
def fechar_oportunidades_sem_leitura(s: Session, agora: datetime, horas: int = 24) -> int:
    """Encerra (motivo `sem_leitura`) as abertas cujo anúncio não aparece em nenhuma leitura há `horas` horas."""
    from tcg_sniper.oportunidades import encerramento  # import tardio: o encerramento usa os repositórios

    velhos = select(AnuncioAmazon.id).where(AnuncioAmazon.visto_ultimo_em < agora - timedelta(hours=horas))
    ids = list(s.scalars(
        select(Oportunidade.id)
        .where(Oportunidade.fechada_em.is_(None), Oportunidade.anuncio_id.in_(velhos))
        .order_by(Oportunidade.id)
    ))
    return sum(encerramento.encerrar(s, op_id, MotivoEncerramento.SEM_LEITURA, agora) for op_id in ids)
```

- [ ] **Step 4: Rodar a suíte inteira**

Run: `uv run pytest -q` e `uv run ruff check`
Expected: PASS e sem achados.

- [ ] **Step 5: Commit**

```bash
git add src/tcg_sniper/db/repositorio_casamento.py src/tcg_sniper/db/repositorio_amazon.py tests/db/test_repositorio_casamento.py tests/db/test_repositorio_amazon.py
git commit -m "feat: unmatched pair and stale listing close opportunities through the end flow"
```

---

### Task 8: Admin antigo — carência e selo "em risco"

**Files:**
- Modify: `src/tcg_sniper/coletor_amazon/config.py` (`CAMPOS`, `ROTULOS`, `EXPLICACOES`), `src/tcg_sniper/admin/consultas_amazon.py` (`LinhaOferta` ~405, `ofertas` ~464–520), `src/tcg_sniper/admin/templates/ofertas.html` (linhas ~35 e ~60), `src/tcg_sniper/admin/static/admin.css` (gerado)
- Test: `tests/admin/test_admin_amazon.py`, `tests/coletor_amazon/test_config_amazon.py`

**Interfaces:**
- Consumes: colunas `em_risco_desde`, `motivo_risco`; `ROTULOS_MOTIVO` (Task 3).
- Produces: `LinhaOferta.risco: tuple[datetime, str] | None` (desde quando e o rótulo do motivo).

- [ ] **Step 1: Testes (falham)**

Em `tests/coletor_amazon/test_config_amazon.py`, no padrão de validação que o arquivo já usa:

```python
def test_carencia_tem_limites():
    campos = dict(VALIDOS, carencia_encerramento_min="241")  # VALIDOS: o dicionário de campos válidos do arquivo
    _, erros = validar_config(campos)
    assert "carencia_encerramento_min" in erros
    _, erros = validar_config(dict(VALIDOS, carencia_encerramento_min="0"))
    assert "carencia_encerramento_min" not in erros
```

Em `tests/admin/test_admin_amazon.py`, depois de `preparar_ofertas(s)`:

```python
def test_ofertas_mostra_o_risco_da_oportunidade(s):
    ff, *_ = preparar_ofertas(s)
    op = s.scalar(select(Oportunidade).where(Oportunidade.produto_id == ff.id, Oportunidade.fechada_em.is_(None)))
    op.em_risco_desde, op.motivo_risco = T0, MotivoEncerramento.PRECO_SUBIU
    s.flush()
    [linha] = [l for l in consultas_amazon.ofertas(s, FiltroOfertas(), config) if l.produto.id == ff.id]
    assert linha.risco == (T0, "preço subiu")
```

(Se `preparar_ofertas` não abrir oportunidade para `ff`, crie uma `Oportunidade` aberta para ele no teste, como na Tarefa 7. Use os nomes de `config` e `T0` do arquivo.) Acrescente também ao `VALIDOS` do teste de config o campo `carencia_encerramento_min: "30"` se o arquivo montar o formulário completo.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/admin/test_admin_amazon.py tests/coletor_amazon/test_config_amazon.py -q`
Expected: FAIL.

- [ ] **Step 3: Configuração**

Em `coletor_amazon/config.py`, depois de `"checkout_validade_h"` nas três estruturas:

```python
    "carencia_encerramento_min",
```
```python
    "carencia_encerramento_min": "Carência para encerrar uma oportunidade (min)",
```
```python
    "carencia_encerramento_min": (
        "Minutos que uma oportunidade avisada espera, depois de deixar de valer, antes de encerrar e avisar o "
        "grupo. Oscilação mais curta que isso não gera aviso. 0: encerra na primeira leitura ruim."
    ),
```

(Os limites vêm de `LIMITES_CONFIG_AMAZON`, já com o campo novo da Tarefa 1; confira que `validar_config` percorre `LIMITES_CONFIG_AMAZON` para os inteiros. Ele aparece dentro do bloco "Monitor de preço" de `configuracoes.html` porque vem depois de `monitor_intervalo_min` em `CAMPOS`.)

- [ ] **Step 4: Ofertas**

Em `consultas_amazon.py`, na `LinhaOferta`, acrescente `risco: tuple[datetime, str] | None = None`. Troque a leitura das abertas:

```python
    abertas = {
        produto_id: (desde, motivo)
        for produto_id, desde, motivo in s.execute(
            select(Oportunidade.produto_id, Oportunidade.em_risco_desde, Oportunidade.motivo_risco)
            .where(Oportunidade.fechada_em.is_(None))
        )
    }
```

e onde monta a linha: `aberta=produto.id in abertas,` e

```python
                risco=(
                    (abertas[produto.id][0], ROTULOS_MOTIVO[MotivoEncerramento(abertas[produto.id][1])])
                    if produto.id in abertas and abertas[produto.id][0] is not None
                    else None
                ),
```

(imports: `ROTULOS_MOTIVO` de `tcg_sniper.oportunidades.mensagens`, `MotivoEncerramento` de `tcg_sniper.db.models`.)

Em `ofertas.html`, nas duas ocorrências de `{% if l.aberta %}{{ selo("ok", "oportunidade") }}{% endif %}` (tabela ~35 e cartão ~60), logo depois:

```jinja
{% if l.risco %} <span class="badge badge-warning badge-sm">em risco desde {{ l.risco[0]|data }} · {{ l.risco[1] }}</span>{% endif %}
```

Confira que o filtro `data` existe (`templates.env.filters["data"]` em `admin/app.py`); ele formata data e hora no fuso.

- [ ] **Step 5: CSS e testes**

Run: `uv run python scripts/gerar_css.py` e depois `uv run pytest tests/admin tests/coletor_amazon -q`
Expected: PASS (inclui `test_css_em_dia_com_os_templates`).

- [ ] **Step 6: Commit**

```bash
git add src/tcg_sniper/coletor_amazon/config.py src/tcg_sniper/admin tests/admin/test_admin_amazon.py tests/coletor_amazon/test_config_amazon.py
git commit -m "feat: grace period setting and at-risk badge in the old admin"
```

---

### Task 9: Documentação

**Files:**
- Modify: `README.md`, `docs/IMPLANTACOES.md`, `docs/PENDENCIAS.md`

- [ ] **Step 1: README**

Em "Como funciona", no parágrafo **Amazon**, depois da frase sobre o grupo de oportunidades receber um aviso, acrescente:

> Quando a oferta deixa de valer (preço subiu, oferta sumiu, Liga baixou ou vendedor mudou) e continua assim pela carência de Configurações → Amazon (padrão 30 min), a oportunidade encerra e o grupo de oportunidades recebe "⏹️ Oferta encerrada" com o motivo e quanto tempo ela durou; oscilação mais curta não gera aviso. Se o casamento for desfeito ou trocado, o grupo recebe "⚠️ Alerta corrigido". Encerramentos técnicos (preço da Liga desatualizado, anúncio sem leitura) vão para o grupo admin. Alerta que nunca saiu (expirado ou ainda na fila) não gera aviso de encerramento.

Na tabela de avisos ("Mensagens no WhatsApp"), linha **Oportunidades**, acrescente: `· ⏹️ oferta encerrada · ⚠️ alerta corrigido`; linha **Amazon**, acrescente: `· 🟡 oportunidade encerrada (técnico)`. Em "Configuração", item **Amazon**, acrescente "carência para encerrar".

- [ ] **Step 2: Notas de implantação**

No topo de `docs/IMPLANTACOES.md` (antes de "Leitura por interesse da LigaMagic"):

```markdown
## Fim da oportunidade (2026-10-20)

Faça o backup de sempre antes (ver [Backup do banco](../README.md#backup-do-banco)). A migração `e7c3a9d5b2f4` acrescenta à `oportunidade` o motivo de encerramento, o risco (carência), o menor preço, a contagem de alertas e a mensagem do alerta, e a `config_amazon` a carência (30 min). As oportunidades abertas na hora da migração ficam marcadas como "alerta sem registro": quando encerrarem, o grupo recebe o aviso. Suba tudo junto (`docker compose up -d --build`) e confira em Configurações → Amazon → Monitor de preço o campo "Carência para encerrar (min)" e em Configurações → Avisos os três avisos novos (oferta encerrada, alerta corrigido, oportunidade encerrada técnico), ligados.
```

- [ ] **Step 3: Pendências**

Em `docs/PENDENCIAS.md`: marque o sub-projeto A como `[x]` com o merge (preencher na hora), mova o detalhe para "Concluídas" numa seção "Fim da oportunidade (2026-10-20, merge `<hash>`)" com os itens entregues (motivo e carência; avisos; alerta ligado à mensagem; selo em risco); atualize a linha "Última revisão". Acrescente em "2. Pequenas" o item: "Oportunidade aberta há mais de 30 dias sem realerta perde o vínculo com a mensagem (limpeza apaga a mensagem) e não avisa o encerramento; aceito por ora (rara)."

- [ ] **Step 4: Commit**

```bash
git add README.md docs/IMPLANTACOES.md docs/PENDENCIAS.md
git commit -m "docs: opportunity end notices, grace period and deploy notes"
```
