# Oportunidades na área de negócio — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a área de negócio do site novo passa a mostrar números do período, oportunidades ativas, quase oportunidades, encerradas e o histórico de preço de cada produto, com gráficos.

**Architecture:** consultas na hora num pacote neutro `tcg_sniper/consultas/` (funções que recebem sessão e `agora` e devolvem dataclasses), expostas por `api/rotas_oportunidades.py` com a permissão nova `ver_oportunidades`; o front (`web/`) ganha as páginas Oportunidades (`/`) e Produto (`/produtos/:id`) com Recharts. A elegibilidade das quase oportunidades usa as funções do motor (`motor.motivo_inelegivel`, `motor.vendedor_elegivel`), nunca uma cópia da regra.

**Tech Stack:** Python 3.12, SQLAlchemy 2 + Alembic, Postgres 16, FastAPI + Pydantic 2, pytest; React 19 + Vite + DaisyUI 5 + Recharts 3, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-20-oportunidades-area-negocio-design.md`

## Global Constraints

- Textos, telas, docstrings e comentários em português; assunto do commit em inglês (`feat:`, `fix:`, `test:`, `docs:`), **sem** `Co-Authored-By` de IA, `Claude-Session` nem "Generated with".
- Testes Python só no Postgres de teste (`127.0.0.1:5433`, bancos `tcg_test*`): `uv run pytest -q`; lint `uv run ruff check`. Front: `cd web && npm test` e `npm run build`.
- Histórico de preço nunca é apagado; nada aqui apaga nem altera `preco_amazon`, `resumo_preco`, `preco_listagem`, `preco_atual_*`, `oportunidade`.
- Front: só componentes do DaisyUI 5 com classes literais (nada montado por concatenação); o gráfico (Recharts) é o único elemento fora do DaisyUI.
- A área de negócio mostra **só dado de mercado**: nenhuma resposta de `/api/oportunidades*` ou `/api/produtos/*` leva contagem de casamentos/IA, id ou nome de vendedor, mensagens ou conferência de checkout.
- Dinheiro no JSON como texto decimal com 2 casas ("1299.90"); percentuais também ("27.40"); datas ISO 8601 com fuso.
- `periodo` ∈ `7d | 30d | 90d | tudo`; outro valor: 400 `{"erro": "periodo_invalido", "mensagem": "Período inválido."}`.
- Piso da quase oportunidade: `quase_oportunidade_min_pct`, padrão 10, faixa 0–100, e menor que `desconto_min_pct` (validação do formulário).
- Commit por tarefa, na branch de trabalho; merge, push e deploy só quando o usuário pedir.

## Decisões do plano sobre o que a spec deixou aberto

- **Preço das ativas:** a spec cita `preco_atual_amazon` e também "o preço é o da oportunidade (o conferido)". Vale o da oportunidade (`oportunidade.preco_amazon`, `preco_liga`, `desconto_pct`, que o monitor atualiza a cada leitura elegível, com o conferido quando houve conferência). O `preco_atual_amazon` pode ser de vendedor não elegível ou sem imposto.
- **Curva da Amazon:** `preco_amazon` só grava quando o preço muda (ou na 1ª leitura do dia). O valor de um anúncio numa hora é a **última linha até o fim da hora**, valendo por até 26 h. A consulta carrega só as linhas dos anúncios confirmados **daquele produto** no período (poucas centenas) e faz o "carrega para frente" em Python. Assim usa `motor.vendedor_elegivel` sem duplicar a regra em SQL.
- **Arquivos:** a spec pôs tudo em `consultas/oportunidades.py`; o plano divide em `oportunidades.py` (período, ativas, encerradas, por dia), `quase_la.py` e `historico_produto.py`, para tarefas paralelas sem conflito.
- `duracao_media_min` e `duracao_min` em minutos inteiros.

## Review Focus

- Oportunidade ativa (sem `fechada_em`) entra nos números com duração até agora e não quebra a média — teste na Tarefa 4.
- Produto com dois anúncios confirmados, um de lojista sem envio pela Amazon mais barato: a curva ignora o não elegível — teste na Tarefa 5.
- Período sem nenhuma oportunidade: médias `null` no JSON e "—" na tela, sem divisão por zero — testes nas Tarefas 4 e 7.
- Imagens do produto (Liga: `repositorio.sbrauble.com`; Amazon: `m.media-amazon.com`) bloqueadas pela CSP do Caddy: `img-src` precisa liberar os dois hosts — mudança e teste na Tarefa 7.
- Recharts sob a CSP `style-src 'self'`: o gráfico não pode gerar `<style>` inline nem erro de CSP no console — conferido no ponta a ponta da Tarefa 9.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade |
| --- | --- |
| `src/tcg_sniper/consultas/__init__.py`, `catalogo.py` (movido de `admin/consultas_catalogo.py`) | situação do catálogo (gestão) |
| `src/tcg_sniper/consultas/oportunidades.py` (novo) | períodos, números, por dia, ativas, encerradas |
| `src/tcg_sniper/consultas/quase_la.py` (novo) | quase oportunidades |
| `src/tcg_sniper/consultas/historico_produto.py` (novo) | cabeçalho, curvas, faixas, recorrência |
| `src/tcg_sniper/oportunidades/montagem.py` (novo) | `vendedor_do_motor`, `ref_liga` (saem do monitor) |
| `src/tcg_sniper/db/models.py`, migração `f3b8d1c7a9e2` | `quase_oportunidade_min_pct`, índice `ix_preco_amazon_anuncio_coletado` |
| `src/tcg_sniper/coletor_amazon/config.py` | campo do piso e validação piso < mínimo |
| `src/tcg_sniper/api/permissoes.py`, `api/rotas_oportunidades.py` (novo), `api/app.py` | permissão e rotas |
| `tests/fakes_oportunidades.py` (novo) | montar oportunidades, leituras e preços da Liga nos testes |
| `web/src/...` | páginas, componentes, `formato.ts`, tipos |
| `web/Caddyfile` | `img-src` com os hosts das imagens |
| `tests/e2e/test_ponta_a_ponta.py`, `scripts/verificar_layout.py` | ponta a ponta e layout |
| `README.md`, `docs/IMPLANTACOES.md`, `docs/PENDENCIAS.md` | documentação |

Ondas para execução paralela: [T1, T2, T3] → [T4, T7] → [T5, T8] → [T6] → [T9].

---

### Task 1: Mover `consultas_catalogo` para o pacote neutro

**Files:**
- Create: `src/tcg_sniper/consultas/__init__.py`, `src/tcg_sniper/consultas/catalogo.py` (conteúdo de `admin/consultas_catalogo.py`)
- Delete: `src/tcg_sniper/admin/consultas_catalogo.py`
- Modify: `src/tcg_sniper/admin/app.py:27`, `admin/consultas_amazon.py:13,112`, `admin/consultas_painel.py:14,524`
- Move test: `tests/admin/test_consultas_catalogo.py` → `tests/consultas/test_catalogo.py`; modify `tests/admin/test_admin_painel_produto.py:11`

**Interfaces:** Produces `tcg_sniper.consultas.catalogo` com os mesmos nomes de antes (`inicio_do_dia`, `classificar`, `SituacaoCatalogo`, `SITUACOES_PRODUTO`, `produtos_avaliados_desde`, `situacao_catalogo`).

- [ ] **Step 1:** `git mv src/tcg_sniper/admin/consultas_catalogo.py src/tcg_sniper/consultas/catalogo.py`; criar `src/tcg_sniper/consultas/__init__.py` com:

```python
"""Consultas de leitura usadas pela API e pelo admin antigo (o pacote `admin` sai na fase 4)."""
```

- [ ] **Step 2:** trocar todo `tcg_sniper.admin.consultas_catalogo` por `tcg_sniper.consultas.catalogo` (imports e as duas menções em docstrings: "`consultas_catalogo`" vira "`consultas.catalogo`"). Conferir: `uv run python -c "import subprocess,sys; sys.exit(subprocess.call(['git','grep','-n','consultas_catalogo','--','src','tests','scripts']) == 0)"` deve sair 0 (nenhuma ocorrência).
- [ ] **Step 3:** `mkdir tests/consultas` com `__init__.py` vazio só se `tests/admin/` tiver `__init__.py` (seguir o padrão da pasta); `git mv tests/admin/test_consultas_catalogo.py tests/consultas/test_catalogo.py` e trocar o import.
- [ ] **Step 4:** `uv run pytest -q tests/consultas tests/admin` e `uv run ruff check` — PASS.
- [ ] **Step 5:** commit `refactor: move catalog queries to neutral consultas package`.

---

### Task 2: Piso da quase oportunidade e índice do histórico da Amazon

**Files:**
- Create: `src/tcg_sniper/db/migrations/versions/f3b8d1c7a9e2_quase_oportunidade.py`
- Modify: `src/tcg_sniper/db/models.py` (`LIMITES_CONFIG_AMAZON` ~457, `PADROES_CONFIG_AMAZON` ~478, `ConfigAmazon` ~544, `PrecoAmazon` ~276)
- Modify: `src/tcg_sniper/coletor_amazon/config.py` (`CAMPOS`, `ROTULOS`, `EXPLICACOES`, `validar_config`)
- Test: `tests/db/test_migracao_quase_oportunidade.py` (novo), `tests/coletor_amazon/test_config_amazon.py`, e os formulários completos em `tests/admin/test_admin_amazon.py:96` e `tests/admin/test_admin_config_tela.py:107` (acrescentar `"quase_oportunidade_min_pct": "10"`)

**Interfaces:** Produces `ConfigAmazon.quase_oportunidade_min_pct: int` (padrão 10).

- [ ] **Step 1: teste da migração** (`tests/db/test_migracao_quase_oportunidade.py`):

```python
from alembic import command
from sqlalchemy import create_engine, pool, text

from tcg_sniper.db.session import config_alembic

ANTES = "e7c3a9d5b2f4"
INDICE = "SELECT 1 FROM pg_indexes WHERE indexname = 'ix_preco_amazon_anuncio_coletado'"
COLUNA = (
    "SELECT 1 FROM information_schema.columns WHERE table_name = 'config_amazon' "
    "AND column_name = 'quase_oportunidade_min_pct'"
)


def test_migracao_do_piso_e_do_indice_sobe_e_desce(engine):
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    try:
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.execute(text(INDICE)).all() == []
            assert c.execute(text(COLUNA)).all() == []
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            assert len(c.execute(text(INDICE)).all()) == 1
            assert c.execute(text("SELECT quase_oportunidade_min_pct FROM config_amazon WHERE id = 1")).scalar() in (
                None, 10,
            )
    finally:
        command.upgrade(cfg, "head")
        proprio.dispose()
```

E em `tests/db/test_migracao.py`, na lista do `test_config_amazon_recusa_valores_fora_dos_limites`, acrescentar `("quase_oportunidade_min_pct", 101)`. O `test_migracao_cria_config_amazon_com_os_padroes` já cobre o padrão 10 pelo `PADROES_CONFIG_AMAZON`.

- [ ] **Step 2: testes da configuração** (`tests/coletor_amazon/test_config_amazon.py`, usando o `formulario(...)` que o arquivo já tem):

```python
def test_piso_da_quase_oportunidade_fica_abaixo_do_desconto_minimo():
    _, erros = validar_config(formulario(quase_oportunidade_min_pct="20", desconto_min_pct="20"))
    assert erros["quase_oportunidade_min_pct"] == "O piso da quase oportunidade precisa ficar abaixo do desconto mínimo."
    _, erros = validar_config(formulario(quase_oportunidade_min_pct="19", desconto_min_pct="20"))
    assert "quase_oportunidade_min_pct" not in erros
    _, erros = validar_config(formulario(quase_oportunidade_min_pct="101"))
    assert "quase_oportunidade_min_pct" in erros
```

O `formulario()` monta os padrões a partir de `PADROES_CONFIG_AMAZON`; se ele listar os campos à mão, acrescentar `quase_oportunidade_min_pct="10"`.

- [ ] **Step 3:** rodar `uv run pytest -q tests/db/test_migracao_quase_oportunidade.py tests/coletor_amazon/test_config_amazon.py` — FAIL.
- [ ] **Step 4: models.** Em `LIMITES_CONFIG_AMAZON`: `"quase_oportunidade_min_pct": (0, 100),`; em `PADROES_CONFIG_AMAZON`: `"quase_oportunidade_min_pct": 10,`; em `ConfigAmazon`, depois de `carencia_encerramento_min`: `quase_oportunidade_min_pct: Mapped[int] = mapped_column(Integer)`. Em `PrecoAmazon`:

```python
    __table_args__ = (Index("ix_preco_amazon_anuncio_coletado", "anuncio_id", "coletado_em"),)  # curva do produto
```

- [ ] **Step 5: migração** `f3b8d1c7a9e2_quase_oportunidade.py`:

```python
"""quase oportunidade: piso do desconto (config_amazon) e índice do histórico da Amazon por anúncio e data

Revision ID: f3b8d1c7a9e2
Revises: e7c3a9d5b2f4
Create Date: 2026-10-21 09:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3b8d1c7a9e2"
down_revision: Union[str, Sequence[str], None] = "e7c3a9d5b2f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "config_amazon", sa.Column("quase_oportunidade_min_pct", sa.Integer(), server_default="10", nullable=False)
    )
    op.create_check_constraint(
        "ck_config_amazon_quase_oportunidade_min_pct", "config_amazon", "quase_oportunidade_min_pct BETWEEN 0 AND 100"
    )
    op.create_index("ix_preco_amazon_anuncio_coletado", "preco_amazon", ["anuncio_id", "coletado_em"])


def downgrade() -> None:
    op.drop_index("ix_preco_amazon_anuncio_coletado", table_name="preco_amazon")
    op.drop_constraint("ck_config_amazon_quase_oportunidade_min_pct", "config_amazon", type_="check")
    op.drop_column("config_amazon", "quase_oportunidade_min_pct")
```

Se `tests/db/test_migracao.py` comparar o `server_default` dos modelos com o banco e reclamar, seguir o que a coluna `carencia_encerramento_min` faz nos modelos.

- [ ] **Step 6: config.py.** Em `CAMPOS`, depois de `"carencia_encerramento_min"`: `"quase_oportunidade_min_pct",`. `ROTULOS`: `"quase_oportunidade_min_pct": "Quase oportunidade a partir de (%)",`. `EXPLICACOES`:

```python
    "quase_oportunidade_min_pct": (
        "Desconto a partir do qual um anúncio elegível aparece como \"quase lá\" na área de negócio (abaixo do "
        "desconto mínimo). Não gera aviso."
    ),
```

No fim de `validar_config`, antes do `return`:

```python
    if (
        "quase_oportunidade_min_pct" in valores
        and "desconto_min_pct" in valores
        and valores["quase_oportunidade_min_pct"] >= valores["desconto_min_pct"]
    ):
        erros["quase_oportunidade_min_pct"] = "O piso da quase oportunidade precisa ficar abaixo do desconto mínimo."
```

- [ ] **Step 7:** `uv run pytest -q tests/db tests/coletor_amazon tests/admin` e `uv run ruff check` — PASS (o template do admin percorre `CAMPOS`; se `test_css_em_dia_com_os_templates` falhar, `uv run python scripts/gerar_css.py`).
- [ ] **Step 8:** commit `feat: near-opportunity floor setting and price history index`.

---

### Task 3: Permissão `ver_oportunidades`

**Files:**
- Modify: `src/tcg_sniper/api/permissoes.py`, `tests/api/test_acessos.py:12-26`
- Modify: `web/src/tipos.ts`, `web/src/teste/apoio.tsx` (EU_GRUPO, EU_OPERADOR, EU_ADMIN)

**Interfaces:** Produces `Permissao.VER_OPORTUNIDADES = "ver_oportunidades"`; no front, `"ver_oportunidades"` no tipo `Permissao`.

- [ ] **Step 1: teste** — em `test_padroes_e_linhas_salvas`, os padrões passam a ser:

```python
    assert padrao[Papel.GRUPO] == {Permissao.VER_AREA_NEGOCIO, Permissao.VER_OPORTUNIDADES}
    assert padrao[Papel.OPERADOR] == {
        Permissao.VER_AREA_NEGOCIO, Permissao.VER_OPORTUNIDADES, Permissao.VER_AREA_GESTAO,
    }
```

e o último `assert` do teste: `{Permissao.VER_AREA_NEGOCIO, Permissao.VER_OPORTUNIDADES, Permissao.VER_AREA_GESTAO, Permissao.GERIR_USUARIOS}`. A linha `grade[Papel.GRUPO] == frozenset()` vira `== {Permissao.VER_OPORTUNIDADES}` (só `ver_area_negocio` foi desligada).

- [ ] **Step 2:** `uv run pytest -q tests/api/test_acessos.py` — FAIL.
- [ ] **Step 3:** em `permissoes.py`, `VER_OPORTUNIDADES = "ver_oportunidades"` logo depois de `VER_AREA_NEGOCIO`; em `DEFINICOES`:

```python
    Permissao.VER_OPORTUNIDADES: DefinicaoPermissao(
        "Ver oportunidades",
        "Ver as oportunidades, o histórico dos produtos e as quase oportunidades na área de negócio.",
    ),
```

`PADROES`: grupo `{VER_AREA_NEGOCIO, VER_OPORTUNIDADES}`, operador `{VER_AREA_NEGOCIO, VER_OPORTUNIDADES, VER_AREA_GESTAO}`.

- [ ] **Step 4: front.** `tipos.ts`: acrescentar `| "ver_oportunidades"` depois de `"ver_area_negocio"`. `teste/apoio.tsx`: `"ver_oportunidades"` logo depois de `"ver_area_negocio"` em EU_GRUPO, EU_OPERADOR e EU_ADMIN.
- [ ] **Step 5:** `uv run pytest -q tests/api` e `cd web && npm test` — PASS.
- [ ] **Step 6:** commit `feat: ver_oportunidades permission`.

---

### Task 4: Consultas — período, números, por dia, ativas e encerradas

**Files:**
- Create: `src/tcg_sniper/consultas/oportunidades.py`, `tests/fakes_oportunidades.py`, `tests/consultas/test_oportunidades.py`

**Interfaces:**
- Consumes: modelos `Oportunidade`, `ProdutoLiga`, `AnuncioAmazon`, `MotivoEncerramento`; `avisos.servico.zona_e_host`.
- Produces (usados nas Tarefas 5 e 6):

```python
PERIODOS: dict[str, int | None]  # {"7d": 7, "30d": 30, "90d": 90, "tudo": None}
def desde_do_periodo(periodo: str, agora: datetime) -> datetime | None  # ValueError se periodo inválido
def duracao_min(aberta_em: datetime, deixou_de_valer_em: datetime | None, fechada_em: datetime | None, agora: datetime) -> int
@dataclass(frozen=True) class ProdutoResumo: id: int; nome: str; imagem_url: str | None; ativo: bool
@dataclass(frozen=True) class AnuncioResumo: titulo: str; url: str; imagem_url: str | None
@dataclass(frozen=True) class Numeros: diferenca_bruta: Decimal; oportunidades: int; desconto_medio: Decimal | None; duracao_media_min: int | None; produtos: int
@dataclass(frozen=True) class Dia: dia: date; oportunidades: int
@dataclass(frozen=True) class Ativa: id: int; produto: ProdutoResumo; anuncio: AnuncioResumo; preco_amazon: Decimal; preco_liga: Decimal; desconto_pct: Decimal; aberta_em: datetime; em_risco_desde: datetime | None; motivo_risco: str | None
@dataclass(frozen=True) class Encerrada: id: int; produto: ProdutoResumo; aberta_em: datetime; fechada_em: datetime | None; aberta: bool; duracao_min: int; alertas: int; preco_alertado: Decimal; menor_preco: Decimal; preco_liga: Decimal; desconto_pct: Decimal; motivo: str | None
@dataclass(frozen=True) class Pagina: itens: list[Encerrada]; total: int; pagina: int; por_pagina: int
def numeros_periodo(s: Session, desde: datetime | None, agora: datetime) -> Numeros
def por_dia(s: Session, desde: datetime | None, agora: datetime, zona: ZoneInfo) -> list[Dia]
def ativas(s: Session) -> list[Ativa]
def ultima_aberta_em(s: Session) -> datetime | None
def encerradas(s: Session, desde: datetime | None, motivo: MotivoEncerramento | None, pagina: int, agora: datetime, por_pagina: int = 25) -> Pagina
def linha_oportunidade(op: Oportunidade, produto: ProdutoLiga, agora: datetime) -> Encerrada
```

- `tests/fakes_oportunidades.py` (Tarefa 5 usa):

```python
def criar_oportunidade(s, anuncio, produto, *, aberta_em, preco_alertado="700", preco_liga="1000", fechada_em=None,
                       motivo=None, deixou_de_valer_em=None, em_risco_desde=None, motivo_risco=None, alertas=1) -> Oportunidade
def criar_vendedor(s, seller_id="A1LOJA", pct="98", avaliacoes=500) -> VendedorAmazon
def criar_leitura(s, anuncio, coletado_em, preco, envio=Envio.AMAZON, vendedor=None) -> PrecoAmazon
def criar_atual_amazon(s, anuncio, preco, envio=Envio.AMAZON, vendedor=None, coletado_em=T0) -> PrecoAtualAmazon
def criar_listagem_liga(s, produto, preco, coletado_em) -> PrecoListagem
def criar_resumo_liga(s, produto, preco_medio, coletado_em, num_lojas=5) -> ResumoPreco
```

- [ ] **Step 1: `tests/fakes_oportunidades.py`:**

```python
"""Montagem de oportunidades, leituras da Amazon e preços da Liga direto no banco (cenários das consultas)."""

from datetime import timedelta
from decimal import Decimal

from fakes import T0

from tcg_sniper.db.models import (
    Coleta,
    Envio,
    Oportunidade,
    OrigemPreco,
    PrecoAmazon,
    PrecoAtualAmazon,
    PrecoListagem,
    ResumoPreco,
    StatusColeta,
    TipoColeta,
    VendedorAmazon,
)
from tcg_sniper.oportunidades.motor import desconto_pct


def criar_oportunidade(
    s, anuncio, produto, *, aberta_em, preco_alertado="700", preco_liga="1000", fechada_em=None, motivo=None,
    deixou_de_valer_em=None, em_risco_desde=None, motivo_risco=None, alertas=1,
) -> Oportunidade:
    preco, liga = Decimal(preco_alertado), Decimal(preco_liga)
    op = Oportunidade(
        anuncio_id=anuncio.id, produto_id=produto.id, preco_amazon=preco, preco_liga=liga,
        desconto_pct=desconto_pct(preco, liga), envio=Envio.AMAZON, aberta_em=aberta_em, alertada_em=aberta_em,
        preco_alertado=preco, menor_preco=preco, fechada_em=fechada_em, motivo_encerramento=motivo,
        deixou_de_valer_em=deixou_de_valer_em, em_risco_desde=em_risco_desde, motivo_risco=motivo_risco,
        alertas=alertas,
    )
    s.add(op)
    s.flush()
    return op


def criar_vendedor(s, seller_id="A1LOJA", pct="98", avaliacoes=500) -> VendedorAmazon:
    vendedor = VendedorAmazon(seller_id=seller_id, nome=f"Loja {seller_id}", pct_positivas=Decimal(pct),
                              num_avaliacoes=avaliacoes, avaliado_em=T0)
    s.add(vendedor)
    s.flush()
    return vendedor


def criar_leitura(s, anuncio, coletado_em, preco, envio=Envio.AMAZON, vendedor=None) -> PrecoAmazon:
    linha = PrecoAmazon(
        anuncio_id=anuncio.id, coletado_em=coletado_em, preco=None if preco is None else Decimal(preco),
        origem=OrigemPreco.OFERTAS, vendedor_id=vendedor.id if vendedor else None, envio=envio,
    )
    s.add(linha)
    s.flush()
    return linha


def criar_atual_amazon(s, anuncio, preco, envio=Envio.AMAZON, vendedor=None, coletado_em=T0) -> PrecoAtualAmazon:
    atual = PrecoAtualAmazon(
        anuncio_id=anuncio.id, preco=None if preco is None else Decimal(preco), origem=OrigemPreco.OFERTAS,
        vendedor_id=vendedor.id if vendedor else None, envio=envio, coletado_em=coletado_em,
    )
    s.add(atual)
    s.flush()
    return atual


def _coleta(s, tipo, quando) -> Coleta:
    coleta = Coleta(tipo=tipo, iniciada_em=quando, finalizada_em=quando + timedelta(minutes=5), status=StatusColeta.OK)
    s.add(coleta)
    s.flush()
    return coleta


def criar_listagem_liga(s, produto, preco, coletado_em) -> PrecoListagem:
    linha = PrecoListagem(produto_id=produto.id, coleta_id=_coleta(s, TipoColeta.LISTAGEM, coletado_em).id,
                          preco_a_partir=Decimal(preco), coletado_em=coletado_em)
    s.add(linha)
    s.flush()
    return linha


def criar_resumo_liga(s, produto, preco_medio, coletado_em, num_lojas=5) -> ResumoPreco:
    linha = ResumoPreco(produto_id=produto.id, coleta_id=_coleta(s, TipoColeta.PRODUTOS, coletado_em).id,
                        preco_medio=Decimal(preco_medio), num_lojas=num_lojas, coletado_em=coletado_em)
    s.add(linha)
    s.flush()
    return linha
```

(Se `Coleta` exigir mais colunas sem padrão, preencher com os padrões que os testes da Liga já usam.)

- [ ] **Step 2: testes** (`tests/consultas/test_oportunidades.py`):

```python
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, criar_anuncio, criar_produto
from fakes_oportunidades import criar_oportunidade

from tcg_sniper.consultas import oportunidades as q
from tcg_sniper.db.models import MotivoEncerramento, StatusCasamento

AGORA = T0 + timedelta(days=10)
SP = ZoneInfo("America/Sao_Paulo")


def _cenario(s):
    p1 = criar_produto(s, "p1", nome="Final Fantasy")
    p2 = criar_produto(s, "p2", nome="Duskmourn")
    a1 = criar_anuncio(s, "B0OPQ00001", p1, StatusCasamento.CONFIRMADO)
    a2 = criar_anuncio(s, "B0OPQ00002", p2, StatusCasamento.CONFIRMADO)
    # encerrada há 2 dias, valeu 3 h (deixou de valer antes de fechar pela carência)
    criar_oportunidade(s, a1, p1, aberta_em=AGORA - timedelta(days=2), preco_alertado="700", preco_liga="1000",
                       deixou_de_valer_em=AGORA - timedelta(days=2) + timedelta(hours=3),
                       fechada_em=AGORA - timedelta(days=2) + timedelta(hours=3, minutes=30),
                       motivo=MotivoEncerramento.PRECO_SUBIU)
    # ativa há 1 h
    criar_oportunidade(s, a2, p2, aberta_em=AGORA - timedelta(hours=1), preco_alertado="800", preco_liga="1000")
    # alerta errado: não conta
    criar_oportunidade(s, a1, p1, aberta_em=AGORA - timedelta(days=1), fechada_em=AGORA - timedelta(hours=20),
                       motivo=MotivoEncerramento.CASAMENTO_DESFEITO)
    # fora dos 7 dias
    criar_oportunidade(s, a1, p1, aberta_em=AGORA - timedelta(days=9), fechada_em=AGORA - timedelta(days=9) +
                       timedelta(hours=1), motivo=MotivoEncerramento.OFERTA_SUMIU)
    return p1, p2


def test_desde_do_periodo():
    assert q.desde_do_periodo("7d", AGORA) == AGORA - timedelta(days=7)
    assert q.desde_do_periodo("tudo", AGORA) is None
    with pytest.raises(ValueError):
        q.desde_do_periodo("1a", AGORA)


def test_numeros_do_periodo_contam_ativas_e_ignoram_casamento_desfeito(s):
    _cenario(s)
    n = q.numeros_periodo(s, AGORA - timedelta(days=7), AGORA)
    assert n.oportunidades == 2
    assert n.diferenca_bruta == Decimal("500.00")  # (1000−700) + (1000−800)
    assert n.desconto_medio == Decimal("25.00")
    assert n.duracao_media_min == 120  # (180 + 60) / 2: a ativa conta até agora
    assert n.produtos == 2
    assert q.numeros_periodo(s, None, AGORA).oportunidades == 3


def test_numeros_sem_oportunidades_tem_medias_vazias(s):
    n = q.numeros_periodo(s, AGORA - timedelta(days=7), AGORA)
    assert (n.oportunidades, n.diferenca_bruta, n.desconto_medio, n.duracao_media_min, n.produtos) == (
        0, Decimal("0.00"), None, None, 0,
    )


def test_por_dia_preenche_os_dias_vazios_no_fuso(s):
    _cenario(s)
    dias = q.por_dia(s, AGORA - timedelta(days=3), AGORA, SP)
    assert [d.dia for d in dias] == [date(2026, 10, 20) - timedelta(days=i) for i in (3, 2, 1, 0)]
    assert [d.oportunidades for d in dias] == [0, 1, 0, 1]


def test_ativas_e_ultima_aberta(s):
    _, p2 = _cenario(s)
    ativas = q.ativas(s)
    assert [a.produto.id for a in ativas] == [p2.id]
    assert ativas[0].preco_amazon == Decimal("800.00") and ativas[0].desconto_pct == Decimal("20.00")
    assert q.ultima_aberta_em(s) == AGORA - timedelta(hours=1)


def test_encerradas_paginadas_e_filtradas(s):
    _cenario(s)
    pagina = q.encerradas(s, None, None, 1, AGORA, por_pagina=2)
    assert pagina.total == 3 and len(pagina.itens) == 2
    assert pagina.itens[0].fechada_em > pagina.itens[1].fechada_em  # mais recentes primeiro
    assert pagina.itens[0].aberta is False
    so_sumiu = q.encerradas(s, None, MotivoEncerramento.OFERTA_SUMIU, 1, AGORA)
    assert [e.motivo for e in so_sumiu.itens] == ["oferta_sumiu"]
    assert q.encerradas(s, AGORA - timedelta(days=7), None, 1, AGORA).total == 2
```

(`T0 = 2026-10-13 13:00 UTC`; `AGORA = 2026-10-23 13:00 UTC = 10:00 em São Paulo`. Ajustar as datas esperadas de `por_dia` se o cálculo der outro dia local: o teste deve conferir 4 dias, do mais antigo ao de hoje, com 1 no dia da encerrada de 2 dias atrás e 1 hoje.)

- [ ] **Step 3:** `uv run pytest -q tests/consultas/test_oportunidades.py` — FAIL (módulo não existe).
- [ ] **Step 4: `src/tcg_sniper/consultas/oportunidades.py`:**

```python
"""Oportunidades para a área de negócio: períodos, números, por dia, ativas e encerradas. Só dado de mercado
(nada de casamento, IA, vendedor ou conferência de checkout). Alerta errado (`casamento_desfeito`) não é resultado:
fica fora dos números, mas aparece nas encerradas com o motivo."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, extract, func, literal, or_, select
from sqlalchemy.orm import Session

from tcg_sniper.db.models import DATA, AnuncioAmazon, MotivoEncerramento, Oportunidade, ProdutoLiga

PERIODOS: dict[str, int | None] = {"7d": 7, "30d": 30, "90d": 90, "tudo": None}
CENTAVO = Decimal("0.01")
O = Oportunidade


@dataclass(frozen=True)
class ProdutoResumo:
    id: int
    nome: str
    imagem_url: str | None
    ativo: bool


@dataclass(frozen=True)
class AnuncioResumo:
    titulo: str
    url: str
    imagem_url: str | None


@dataclass(frozen=True)
class Numeros:
    diferenca_bruta: Decimal
    oportunidades: int
    desconto_medio: Decimal | None
    duracao_media_min: int | None
    produtos: int


@dataclass(frozen=True)
class Dia:
    dia: date
    oportunidades: int


@dataclass(frozen=True)
class Ativa:
    id: int
    produto: ProdutoResumo
    anuncio: AnuncioResumo
    preco_amazon: Decimal
    preco_liga: Decimal
    desconto_pct: Decimal
    aberta_em: datetime
    em_risco_desde: datetime | None
    motivo_risco: str | None


@dataclass(frozen=True)
class Encerrada:
    id: int
    produto: ProdutoResumo
    aberta_em: datetime
    fechada_em: datetime | None
    aberta: bool
    duracao_min: int
    alertas: int
    preco_alertado: Decimal
    menor_preco: Decimal
    preco_liga: Decimal
    desconto_pct: Decimal
    motivo: str | None


@dataclass(frozen=True)
class Pagina:
    itens: list[Encerrada]
    total: int
    pagina: int
    por_pagina: int


def desde_do_periodo(periodo: str, agora: datetime) -> datetime | None:
    if periodo not in PERIODOS:
        raise ValueError(periodo)
    dias = PERIODOS[periodo]
    return None if dias is None else agora - timedelta(days=dias)


def duracao_min(
    aberta_em: datetime, deixou_de_valer_em: datetime | None, fechada_em: datetime | None, agora: datetime
) -> int:
    """Quanto a oferta valeu de verdade: até deixar de valer (sem a carência), até fechar ou, aberta, até agora."""
    fim = deixou_de_valer_em or fechada_em or agora
    return max(0, int((fim - aberta_em).total_seconds() // 60))


def _conta_como_resultado():
    return or_(O.motivo_encerramento.is_(None), O.motivo_encerramento != MotivoEncerramento.CASAMENTO_DESFEITO)


def _no_periodo(desde: datetime | None):
    return O.aberta_em >= desde if desde is not None else literal(True)


def produto_resumo(p: ProdutoLiga) -> ProdutoResumo:
    return ProdutoResumo(p.id, p.nome, p.imagem_url, p.ativo)


def numeros_periodo(s: Session, desde: datetime | None, agora: datetime) -> Numeros:
    fim = func.coalesce(O.deixou_de_valer_em, O.fechada_em, literal(agora, DATA))
    linha = s.execute(
        select(
            func.count(),
            func.coalesce(func.sum(O.preco_liga - O.preco_alertado), 0),
            func.avg(O.desconto_pct),
            func.avg(extract("epoch", fim - O.aberta_em)),
            func.count(func.distinct(O.produto_id)),
        ).where(_conta_como_resultado(), _no_periodo(desde))
    ).one()
    total, diferenca, desconto, segundos, produtos = linha
    return Numeros(
        diferenca_bruta=Decimal(diferenca).quantize(CENTAVO),
        oportunidades=total,
        desconto_medio=None if desconto is None else Decimal(desconto).quantize(CENTAVO),
        duracao_media_min=None if segundos is None else int(Decimal(segundos) // 60),
        produtos=produtos,
    )


def por_dia(s: Session, desde: datetime | None, agora: datetime, zona: ZoneInfo) -> list[Dia]:
    dia = func.date(func.timezone(zona.key, O.aberta_em))
    contagens = dict(
        s.execute(select(dia, func.count()).where(_conta_como_resultado(), _no_periodo(desde)).group_by(dia)).all()
    )
    hoje = agora.astimezone(zona).date()
    if desde is not None:
        inicio = desde.astimezone(zona).date()
    elif contagens:
        inicio = min(contagens)
    else:
        return []
    return [Dia(inicio + timedelta(days=i), contagens.get(inicio + timedelta(days=i), 0))
            for i in range((hoje - inicio).days + 1)]


def ativas(s: Session) -> list[Ativa]:
    linhas = s.execute(
        select(O, ProdutoLiga, AnuncioAmazon)
        .join(ProdutoLiga, ProdutoLiga.id == O.produto_id)
        .join(AnuncioAmazon, AnuncioAmazon.id == O.anuncio_id)
        .where(O.fechada_em.is_(None))
        .order_by(O.desconto_pct.desc(), O.aberta_em)
    ).all()
    return [
        Ativa(
            id=op.id, produto=produto_resumo(p), anuncio=AnuncioResumo(a.titulo, a.url, a.imagem_url),
            preco_amazon=op.preco_amazon, preco_liga=op.preco_liga, desconto_pct=op.desconto_pct,
            aberta_em=op.aberta_em, em_risco_desde=op.em_risco_desde,
            motivo_risco=None if op.motivo_risco is None else str(op.motivo_risco),
        )
        for op, p, a in linhas
    ]


def ultima_aberta_em(s: Session) -> datetime | None:
    return s.scalar(select(func.max(O.aberta_em)).where(_conta_como_resultado()))


def linha_oportunidade(op: Oportunidade, produto: ProdutoLiga, agora: datetime) -> Encerrada:
    return Encerrada(
        id=op.id, produto=produto_resumo(produto), aberta_em=op.aberta_em, fechada_em=op.fechada_em,
        aberta=op.fechada_em is None,
        duracao_min=duracao_min(op.aberta_em, op.deixou_de_valer_em, op.fechada_em, agora), alertas=op.alertas,
        preco_alertado=op.preco_alertado, menor_preco=op.menor_preco, preco_liga=op.preco_liga,
        desconto_pct=op.desconto_pct,
        motivo=None if op.motivo_encerramento is None else str(op.motivo_encerramento),
    )


def encerradas(
    s: Session, desde: datetime | None, motivo: MotivoEncerramento | None, pagina: int, agora: datetime,
    por_pagina: int = 25,
) -> Pagina:
    filtro = and_(O.fechada_em.is_not(None), _no_periodo(desde),
                  O.motivo_encerramento == motivo if motivo is not None else literal(True))
    total = s.scalar(select(func.count()).select_from(O).where(filtro))
    linhas = s.execute(
        select(O, ProdutoLiga).join(ProdutoLiga, ProdutoLiga.id == O.produto_id).where(filtro)
        .order_by(O.fechada_em.desc(), O.id.desc()).offset((pagina - 1) * por_pagina).limit(por_pagina)
    ).all()
    return Pagina([linha_oportunidade(op, p, agora) for op, p in linhas], total, pagina, por_pagina)
```

`DATA` vem de `tcg_sniper.db.models` (o tipo `DateTime(timezone=True)` usado nas colunas); se não estiver exportado com esse nome, usar `sa.DateTime(timezone=True)`.

- [ ] **Step 5:** `uv run pytest -q tests/consultas/test_oportunidades.py` e `uv run ruff check` — PASS.
- [ ] **Step 6:** commit `feat: opportunity queries for the business area`.

---

### Task 5: Consultas — quase lá e histórico do produto

**Files:**
- Create: `src/tcg_sniper/oportunidades/montagem.py`, `src/tcg_sniper/consultas/quase_la.py`, `src/tcg_sniper/consultas/historico_produto.py`
- Modify: `src/tcg_sniper/coletor_amazon/monitor.py:89-101,274,290,326,406-408` (usar `montagem`)
- Test: `tests/oportunidades/test_montagem.py`, `tests/consultas/test_quase_la.py`, `tests/consultas/test_historico_produto.py`

**Interfaces:**
- Consumes (Tarefa 4): `consultas.oportunidades.{ProdutoResumo, AnuncioResumo, Encerrada, produto_resumo, linha_oportunidade, CENTAVO}`; `tests/fakes_oportunidades.py`.
- Produces (Tarefa 6):

```python
# oportunidades/montagem.py
def vendedor_do_motor(vendedor: VendedorAmazon | None) -> motor.Vendedor | None
def ref_liga(liga: PrecoAtualLiga | None) -> motor.RefLiga
# consultas/quase_la.py
@dataclass(frozen=True) class QuaseLa: produto: ProdutoResumo; anuncio: AnuncioResumo; preco_amazon: Decimal; preco_liga: Decimal; desconto_pct: Decimal; falta_reais: Decimal; falta_pp: Decimal
def quase_la(s: Session, regras: motor.Regras, piso_pct: int, agora: datetime, limite: int | None = None, produto_id: int | None = None) -> list[QuaseLa]
# consultas/historico_produto.py
@dataclass(frozen=True) class PontoAmazon: t: datetime; preco: Decimal; anuncio: str
@dataclass(frozen=True) class PontoLiga: t: datetime; preco: Decimal
@dataclass(frozen=True) class Faixa: id: int; inicio: datetime; fim: datetime; aberta: bool; motivo: str | None
@dataclass(frozen=True) class CabecalhoProduto: id: int; nome: str; edicao: str | None; imagem_url: str | None; url_liga: str
@dataclass(frozen=True) class Historico: produto: CabecalhoProduto; anuncio: AnuncioResumo | None; escala: str; amazon: list[PontoAmazon]; liga: list[PontoLiga]; liga_medio: list[PontoLiga]; desconto_min_pct: int; faixas: list[Faixa]; oportunidades: list[Encerrada]; recorrencia_30d: int; quase_la: bool
def historico_produto(s: Session, produto_id: int, desde: datetime | None, agora: datetime, regras: motor.Regras, piso_pct: int, zona: ZoneInfo) -> Historico | None  # None: produto inexistente ou inativo
```

- [ ] **Step 1: montagem (teste + código).** `tests/oportunidades/test_montagem.py`:

```python
from datetime import UTC, datetime
from decimal import Decimal

from tcg_sniper.db.models import PrecoAtualLiga, VendedorAmazon
from tcg_sniper.oportunidades import montagem, motor


def test_montagem_dos_dados_do_motor():
    assert montagem.vendedor_do_motor(None) is None
    v = VendedorAmazon(seller_id="X", nome="Loja", pct_positivas=Decimal("97"), num_avaliacoes=300)
    assert montagem.vendedor_do_motor(v) == motor.Vendedor("Loja", Decimal("97"), 300)
    assert montagem.ref_liga(None) == motor.RefLiga(None, None, None, None)
    quando = datetime(2026, 10, 20, tzinfo=UTC)
    liga = PrecoAtualLiga(produto_id=1, preco_a_partir=Decimal("1000"), listagem_em=quando, num_lojas=4,
                          preco_medio=Decimal("1100"))
    assert montagem.ref_liga(liga) == motor.RefLiga(Decimal("1000"), quando, 4, Decimal("1100"))
```

`src/tcg_sniper/oportunidades/montagem.py` recebe o corpo de `monitor._info` e `monitor._ref` com os nomes novos (docstring do módulo: "Dados do banco no formato do motor; usados pelo monitor e pelas consultas da área de negócio, para a regra de elegibilidade ser uma só."). Em `monitor.py`: apagar `_info`/`_ref`, `from tcg_sniper.oportunidades.montagem import ref_liga, vendedor_do_motor` e trocar as 5 chamadas. `uv run pytest -q tests/oportunidades tests/coletor_amazon` — PASS.

- [ ] **Step 2: testes do quase lá** (`tests/consultas/test_quase_la.py`):

```python
from datetime import timedelta
from decimal import Decimal

from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto
from fakes_oportunidades import criar_atual_amazon, criar_oportunidade, criar_vendedor

from tcg_sniper.consultas.quase_la import quase_la
from tcg_sniper.db.models import Envio, StatusCasamento
from tcg_sniper.oportunidades.motor import Regras

AGORA = T0 + timedelta(hours=2)
REGRAS = Regras(desconto_min_pct=20, realerta_queda_pct=5, liga_preco_max_idade_h=48,
                vendedor_min_positivas_pct=90, vendedor_min_avaliacoes=100)


def _produto(s, nome, liga="1000.00", listagem_em=T0, ativo=True):
    p = criar_produto(s, nome, ativo=ativo)
    criar_preco_liga(s, p, liga, listagem_em=listagem_em)
    return p


def test_quase_la_so_elegiveis_entre_o_piso_e_o_minimo(s):
    perto = _produto(s, "perto")
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE001", perto, StatusCasamento.CONFIRMADO), "850.00")  # 15%
    longe = _produto(s, "longe")
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE002", longe, StatusCasamento.CONFIRMADO), "880.00")  # 12%
    abaixo = _produto(s, "abaixo")
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE003", abaixo, StatusCasamento.CONFIRMADO), "950.00")  # 5%
    loja = _produto(s, "loja")
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE004", loja, StatusCasamento.CONFIRMADO), "850.00",
                       envio=Envio.PROPRIO)
    velha = _produto(s, "velha", listagem_em=T0 - timedelta(hours=72))
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE005", velha, StatusCasamento.CONFIRMADO), "850.00")
    inativo = _produto(s, "inativo", ativo=False)
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE006", inativo, StatusCasamento.CONFIRMADO), "850.00")
    pendente = _produto(s, "pendente")
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE007", pendente, StatusCasamento.PENDENTE), "850.00")
    aberta = _produto(s, "aberta")
    a = criar_anuncio(s, "B0QUASE008", aberta, StatusCasamento.CONFIRMADO)
    criar_atual_amazon(s, a, "850.00")
    criar_oportunidade(s, a, aberta, aberta_em=T0)
    ja_e = _produto(s, "ja")
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE009", ja_e, StatusCasamento.CONFIRMADO), "790.00")  # 21%
    fba = _produto(s, "fba")
    criar_atual_amazon(s, criar_anuncio(s, "B0QUASE010", fba, StatusCasamento.CONFIRMADO), "860.00",
                       envio=Envio.FBA, vendedor=criar_vendedor(s))  # FBA confiável: entra

    itens = quase_la(s, REGRAS, 10, AGORA)
    assert [i.produto.nome for i in itens] == ["Produto perto", "Produto fba", "Produto longe"]
    assert itens[0].desconto_pct == Decimal("15.00")
    assert itens[0].falta_reais == Decimal("50.00")  # alvo = 1000 × 0,80 = 800
    assert itens[0].falta_pp == Decimal("5.00")
    assert [i.produto.nome for i in quase_la(s, REGRAS, 10, AGORA, limite=1)] == ["Produto perto"]
    assert [i.produto.nome for i in quase_la(s, REGRAS, 10, AGORA, produto_id=longe.id)] == ["Produto longe"]
```

(O nome vem de `criar_produto`: `f"Produto {liga_id}"`.)

- [ ] **Step 3: `src/tcg_sniper/consultas/quase_la.py`:**

```python
"""Quase oportunidades: anúncio casado (confirmado) de produto ativo, sem oportunidade aberta, elegível pelo motor
(vendedor aceito, Liga em dia), com desconto entre o piso e o mínimo, pela última leitura. Foto de agora."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcg_sniper.consultas.oportunidades import CENTAVO, AnuncioResumo, ProdutoResumo, produto_resumo
from tcg_sniper.db.models import (
    AnuncioAmazon, Casamento, MotivoEncerramento, Oportunidade, PrecoAtualAmazon, PrecoAtualLiga, ProdutoLiga,
    StatusCasamento, VendedorAmazon,
)
from tcg_sniper.oportunidades import motor
from tcg_sniper.oportunidades.montagem import ref_liga, vendedor_do_motor

CEM = Decimal(100)


@dataclass(frozen=True)
class QuaseLa:
    produto: ProdutoResumo
    anuncio: AnuncioResumo
    preco_amazon: Decimal
    preco_liga: Decimal
    desconto_pct: Decimal
    falta_reais: Decimal
    falta_pp: Decimal


def quase_la(
    s: Session, regras: motor.Regras, piso_pct: int, agora: datetime, limite: int | None = None,
    produto_id: int | None = None,
) -> list[QuaseLa]:
    aberta = select(Oportunidade.id).where(
        Oportunidade.anuncio_id == AnuncioAmazon.id, Oportunidade.fechada_em.is_(None)
    ).exists()
    consulta = (
        select(ProdutoLiga, AnuncioAmazon, PrecoAtualAmazon, PrecoAtualLiga, VendedorAmazon)
        .join(Casamento, Casamento.produto_id == ProdutoLiga.id)
        .join(AnuncioAmazon, AnuncioAmazon.id == Casamento.anuncio_id)
        .join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .join(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAtualAmazon.vendedor_id)
        .where(Casamento.status == StatusCasamento.CONFIRMADO, ProdutoLiga.ativo.is_(True), ~aberta)
    )
    if produto_id is not None:
        consulta = consulta.where(ProdutoLiga.id == produto_id)
    itens = []
    for produto, anuncio, atual, liga, vendedor in s.execute(consulta):
        leitura = motor.Leitura(atual.preco, atual.envio, vendedor_do_motor(vendedor))
        ref = ref_liga(liga)
        if motor.motivo_inelegivel(leitura, ref, regras, agora) is not MotivoEncerramento.PRECO_SUBIU:
            continue  # elegível de verdade (é oportunidade) ou não elegível (vendedor, Liga, sem preço)
        desconto = motor.desconto_pct(atual.preco, ref.preco_a_partir)
        if desconto < piso_pct:
            continue
        alvo = (ref.preco_a_partir * (CEM - regras.desconto_min_pct) / CEM).quantize(CENTAVO)
        itens.append(QuaseLa(
            produto=produto_resumo(produto), anuncio=AnuncioResumo(anuncio.titulo, anuncio.url, anuncio.imagem_url),
            preco_amazon=atual.preco, preco_liga=ref.preco_a_partir, desconto_pct=desconto,
            falta_reais=(atual.preco - alvo).quantize(CENTAVO),
            falta_pp=(Decimal(regras.desconto_min_pct) - desconto).quantize(CENTAVO),
        ))
    itens.sort(key=lambda i: (i.falta_pp, i.produto.nome))
    return itens if limite is None else itens[:limite]
```

(`motivo_inelegivel` sem `preco_liga_anterior` devolve `PRECO_SUBIU` para "elegível mas sem desconto"; nunca `LIGA_CAIU`.)

- [ ] **Step 4: testes do histórico** (`tests/consultas/test_historico_produto.py`):

```python
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto
from fakes_oportunidades import (
    criar_atual_amazon, criar_leitura, criar_listagem_liga, criar_oportunidade, criar_resumo_liga,
)

from tcg_sniper.consultas.historico_produto import historico_produto
from tcg_sniper.db.models import Envio, MotivoEncerramento, StatusCasamento
from tcg_sniper.oportunidades.motor import Regras

AGORA = T0 + timedelta(hours=5)
SP = ZoneInfo("America/Sao_Paulo")
REGRAS = Regras(desconto_min_pct=20, realerta_queda_pct=5, liga_preco_max_idade_h=48,
                vendedor_min_positivas_pct=90, vendedor_min_avaliacoes=100)


def _hist(s, produto, desde=T0 - timedelta(hours=1)):
    return historico_produto(s, produto.id, desde, AGORA, REGRAS, 10, SP)


def test_curva_carrega_o_preco_e_usa_o_menor_elegivel_por_hora(s):
    p = criar_produto(s, "curva")
    a1 = criar_anuncio(s, "B0CURVA001", p, StatusCasamento.CONFIRMADO)
    a2 = criar_anuncio(s, "B0CURVA002", p, StatusCasamento.CONFIRMADO)
    criar_leitura(s, a1, T0 - timedelta(hours=3), "900.00")  # antes do período: vale até mudar
    criar_leitura(s, a1, T0 + timedelta(hours=2, minutes=10), "950.00")
    criar_leitura(s, a2, T0 + timedelta(minutes=30), "700.00", envio=Envio.PROPRIO)  # não elegível: ignorado
    criar_leitura(s, a2, T0 + timedelta(hours=3, minutes=5), "880.00")
    h = _hist(s, p)
    assert h.escala == "hora"
    precos = [(pt.t.hour, pt.preco) for pt in h.amazon]
    assert precos[:2] == [((T0 - timedelta(hours=1)).hour, Decimal("900.00")), (T0.hour, Decimal("900.00"))]
    assert ((T0 + timedelta(hours=2)).hour, Decimal("950.00")) in precos
    assert ((T0 + timedelta(hours=3)).hour, Decimal("880.00")) in precos
    assert all(pt.preco != Decimal("700.00") for pt in h.amazon)


def test_liga_faixas_oportunidades_e_recorrencia(s):
    p = criar_produto(s, "faixas")
    criar_preco_liga(s, p, "1000.00", listagem_em=T0)
    a = criar_anuncio(s, "B0FAIXA001", p, StatusCasamento.CONFIRMADO)
    criar_atual_amazon(s, a, "900.00")
    criar_listagem_liga(s, p, "1000.00", T0)
    criar_resumo_liga(s, p, "1100.00", T0)
    fechada = criar_oportunidade(s, a, p, aberta_em=T0 + timedelta(minutes=10),
                                 deixou_de_valer_em=T0 + timedelta(hours=1),
                                 fechada_em=T0 + timedelta(hours=1, minutes=30), motivo=MotivoEncerramento.PRECO_SUBIU)
    criar_oportunidade(s, a, p, aberta_em=T0 - timedelta(days=40), fechada_em=T0 - timedelta(days=40) +
                       timedelta(hours=1), motivo=MotivoEncerramento.OFERTA_SUMIU)
    h = _hist(s, p)
    assert [pt.preco for pt in h.liga] == [Decimal("1000.00")]
    assert [pt.preco for pt in h.liga_medio] == [Decimal("1100.00")]
    assert [(f.id, f.fim, f.aberta) for f in h.faixas] == [(fechada.id, T0 + timedelta(hours=1), False)]
    assert [o.id for o in h.oportunidades] == [fechada.id]
    assert h.recorrencia_30d == 1
    assert h.desconto_min_pct == 20
    assert h.anuncio.titulo == "Anúncio B0FAIXA001"
    assert h.quase_la is True  # 900 contra 1000: 10%, no piso


def test_produto_inexistente_ou_inativo(s):
    assert historico_produto(s, 999_999, None, AGORA, REGRAS, 10, SP) is None
    inativo = criar_produto(s, "fora", ativo=False)
    assert historico_produto(s, inativo.id, None, AGORA, REGRAS, 10, SP) is None


def test_tudo_acima_de_90_dias_agrega_por_dia(s):
    p = criar_produto(s, "longo")
    a = criar_anuncio(s, "B0LONGO001", p, StatusCasamento.CONFIRMADO)
    criar_leitura(s, a, AGORA - timedelta(days=120), "900.00")
    h = historico_produto(s, p.id, None, AGORA, REGRAS, 10, SP)
    assert h.escala == "dia"
    assert len(h.amazon) == 2  # a leitura vale 26 h: dois dias com ponto, depois some
```

- [ ] **Step 5: `src/tcg_sniper/consultas/historico_produto.py`:**

```python
"""Histórico de um produto ativo na área de negócio: curva da Amazon (menor preço elegível por hora, ou por dia acima
de 90 dias, entre os anúncios confirmados), curvas da Liga, faixas das oportunidades e recorrência. O `preco_amazon`
só grava quando o preço muda (ou na 1ª leitura do dia): o valor de um anúncio num intervalo é a última linha até o fim
dele, por até 26 h. Carrega só as linhas dos anúncios deste produto."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcg_sniper.consultas.oportunidades import AnuncioResumo, Encerrada, linha_oportunidade
from tcg_sniper.consultas.quase_la import quase_la
from tcg_sniper.db.models import (
    AnuncioAmazon, Casamento, MotivoEncerramento, Oportunidade, PrecoAmazon, PrecoAtualAmazon, PrecoListagem,
    ProdutoLiga, ResumoPreco, StatusCasamento, VendedorAmazon,
)
from tcg_sniper.oportunidades import motor
from tcg_sniper.oportunidades.montagem import vendedor_do_motor

VALIDADE_LEITURA = timedelta(hours=26)
LIMITE_POR_HORA = timedelta(days=90)


@dataclass(frozen=True)
class PontoAmazon:
    t: datetime
    preco: Decimal
    anuncio: str


@dataclass(frozen=True)
class PontoLiga:
    t: datetime
    preco: Decimal


@dataclass(frozen=True)
class Faixa:
    id: int
    inicio: datetime
    fim: datetime
    aberta: bool
    motivo: str | None


@dataclass(frozen=True)
class CabecalhoProduto:
    id: int
    nome: str
    edicao: str | None
    imagem_url: str | None
    url_liga: str


@dataclass(frozen=True)
class Historico:
    produto: CabecalhoProduto
    anuncio: AnuncioResumo | None
    escala: str
    amazon: list[PontoAmazon]
    liga: list[PontoLiga]
    liga_medio: list[PontoLiga]
    desconto_min_pct: int
    faixas: list[Faixa]
    oportunidades: list[Encerrada]
    recorrencia_30d: int
    quase_la: bool


def _truncar(t: datetime, escala: str, zona: ZoneInfo) -> datetime:
    local = t.astimezone(zona).replace(minute=0, second=0, microsecond=0)
    return local.replace(hour=0) if escala == "dia" else local


def _curva_amazon(s, anuncios, desde, agora, regras, zona) -> tuple[str, list[PontoAmazon]]:
    if not anuncios:
        return "hora", []
    titulos = {a.id: a.titulo for a in anuncios}
    filtro = [PrecoAmazon.anuncio_id.in_(titulos), PrecoAmazon.coletado_em <= agora]
    if desde is not None:
        filtro.append(PrecoAmazon.coletado_em >= desde - VALIDADE_LEITURA)
    linhas = s.execute(
        select(PrecoAmazon, VendedorAmazon).outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAmazon.vendedor_id)
        .where(*filtro).order_by(PrecoAmazon.coletado_em)
    ).all()
    if not linhas:
        return "hora", []
    inicio = desde or linhas[0][0].coletado_em
    escala = "dia" if agora - inicio > LIMITE_POR_HORA else "hora"
    passo = timedelta(days=1) if escala == "dia" else timedelta(hours=1)
    pontos, ultima, i = [], {}, 0
    balde = _truncar(inicio, escala, zona)
    while balde <= agora:
        fim = balde + passo
        while i < len(linhas) and linhas[i][0].coletado_em < fim:
            leitura, vendedor = linhas[i]
            ultima[leitura.anuncio_id] = (leitura, vendedor)
            i += 1
        validos = [
            leitura for leitura, vendedor in ultima.values()
            if leitura.preco is not None and leitura.coletado_em >= fim - VALIDADE_LEITURA
            and motor.vendedor_elegivel(leitura.envio, vendedor_do_motor(vendedor), regras)
        ]
        if validos:
            menor = min(validos, key=lambda l: l.preco)
            pontos.append(PontoAmazon(balde, menor.preco, titulos[menor.anuncio_id]))
        balde = _truncar(fim, escala, zona) if escala == "hora" else (balde + passo).astimezone(zona).replace(hour=0)
    return escala, pontos


def historico_produto(
    s: Session, produto_id: int, desde: datetime | None, agora: datetime, regras: motor.Regras, piso_pct: int,
    zona: ZoneInfo,
) -> Historico | None:
    produto = s.get(ProdutoLiga, produto_id)
    if produto is None or not produto.ativo:
        return None
    anuncios = list(s.scalars(
        select(AnuncioAmazon).join(Casamento, Casamento.anuncio_id == AnuncioAmazon.id)
        .where(Casamento.produto_id == produto_id, Casamento.status == StatusCasamento.CONFIRMADO)
    ))
    escala, amazon = _curva_amazon(s, anuncios, desde, agora, regras, zona)
    periodo_liga = [] if desde is None else [PrecoListagem.coletado_em >= desde]
    liga = [PontoLiga(l.coletado_em, l.preco_a_partir) for l in s.scalars(
        select(PrecoListagem).where(PrecoListagem.produto_id == produto_id, PrecoListagem.preco_a_partir.is_not(None),
                                    *periodo_liga).order_by(PrecoListagem.coletado_em))]
    periodo_resumo = [] if desde is None else [ResumoPreco.coletado_em >= desde]
    liga_medio = [PontoLiga(r.coletado_em, r.preco_medio) for r in s.scalars(
        select(ResumoPreco).where(ResumoPreco.produto_id == produto_id, ResumoPreco.preco_medio.is_not(None),
                                  *periodo_resumo).order_by(ResumoPreco.coletado_em))]
    ops = list(s.scalars(
        select(Oportunidade).where(Oportunidade.produto_id == produto_id,
                                   *([] if desde is None else [Oportunidade.aberta_em >= desde]))
        .order_by(Oportunidade.aberta_em.desc())
    ))
    faixas = [Faixa(op.id, op.aberta_em, op.deixou_de_valer_em or op.fechada_em or agora, op.fechada_em is None,
                    None if op.motivo_encerramento is None else str(op.motivo_encerramento)) for op in ops]
    recorrencia = len([op for op in s.scalars(select(Oportunidade).where(
        Oportunidade.produto_id == produto_id, Oportunidade.aberta_em >= agora - timedelta(days=30),
    )) if op.motivo_encerramento != MotivoEncerramento.CASAMENTO_DESFEITO])
    atual = s.execute(
        select(AnuncioAmazon).join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .where(AnuncioAmazon.id.in_([a.id for a in anuncios]), PrecoAtualAmazon.preco.is_not(None))
        .order_by(PrecoAtualAmazon.preco).limit(1)
    ).scalar()
    return Historico(
        produto=CabecalhoProduto(produto.id, produto.nome, produto.edicao, produto.imagem_url, produto.url),
        anuncio=None if atual is None else AnuncioResumo(atual.titulo, atual.url, atual.imagem_url),
        escala=escala, amazon=amazon, liga=liga, liga_medio=liga_medio, desconto_min_pct=regras.desconto_min_pct,
        faixas=faixas, oportunidades=[linha_oportunidade(op, produto, agora) for op in ops],
        recorrencia_30d=recorrencia, quase_la=bool(quase_la(s, regras, piso_pct, agora, produto_id=produto_id)),
    )
```

O passo do balde em "dia" usa a meia-noite local seguinte; se o teste de 120 dias mostrar 3 pontos por causa do horário de verão ou do corte das 26 h, conferir que `VALIDADE_LEITURA` é aplicada ao **fim** do balde, como no código.

- [ ] **Step 6:** `uv run pytest -q tests/consultas tests/oportunidades tests/coletor_amazon` e `uv run ruff check` — PASS.
- [ ] **Step 7:** commit `feat: near-opportunity and product history queries`.

---

### Task 6: API das oportunidades

**Files:**
- Create: `src/tcg_sniper/api/rotas_oportunidades.py`, `tests/api/test_oportunidades.py`
- Modify: `src/tcg_sniper/api/app.py` (`include_router`)

**Interfaces:**
- Consumes: Tarefas 3, 4 e 5; `repositorio_amazon.obter_config`, `motor.Regras.de`, `avisos.servico.zona_e_host`.
- Produces — o contrato JSON que o front (Tarefas 7 e 8) usa:

```text
GET /api/oportunidades/resumo?periodo=7d
  {"periodo":"7d","numeros":{"diferenca_bruta":"500.00","oportunidades":2,"desconto_medio":"25.00"|null,
   "duracao_media_min":120|null,"produtos":2},"por_dia":[{"dia":"2026-10-20","oportunidades":1}]}
GET /api/oportunidades/ativas
  {"ativas":[{"id":1,"produto":{"id":1,"nome":"…","imagem_url":"…"|null,"ativo":true},
   "anuncio":{"titulo":"…","url":"…","imagem_url":"…"|null},"preco_amazon":"800.00","preco_liga":"1000.00",
   "desconto_pct":"20.00","aberta_em":"…","em_risco_desde":"…"|null,"motivo_risco":"preco_subiu"|null}],
   "ultima_aberta_em":"…"|null}
GET /api/oportunidades/encerradas?periodo=7d&motivo=preco_subiu&pagina=1
  {"itens":[{"id":1,"produto":{…},"aberta_em":"…","fechada_em":"…"|null,"aberta":false,"duracao_min":180,
   "alertas":1,"preco_alertado":"700.00","menor_preco":"700.00","preco_liga":"1000.00","desconto_pct":"30.00",
   "motivo":"preco_subiu"|null}],"total":3,"pagina":1,"por_pagina":25}
GET /api/oportunidades/quase?limite=20
  {"itens":[{"produto":{…},"anuncio":{…},"preco_amazon":"850.00","preco_liga":"1000.00","desconto_pct":"15.00",
   "falta_reais":"50.00","falta_pp":"5.00"}],"desconto_min_pct":20,"piso_pct":10}
GET /api/produtos/{id}/historico?periodo=30d
  {"produto":{"id":1,"nome":"…","edicao":"…"|null,"imagem_url":"…"|null,"url_liga":"…"},"anuncio":{…}|null,
   "periodo":"30d","escala":"hora"|"dia","amazon":[{"t":"…","preco":"900.00","anuncio":"…"}],
   "liga":[{"t":"…","preco":"1000.00"}],"liga_medio":[{"t":"…","preco":"1100.00"}],"desconto_min_pct":20,
   "faixas":[{"id":1,"inicio":"…","fim":"…","aberta":false,"motivo":"preco_subiu"|null}],
   "oportunidades":[<mesmo formato dos itens das encerradas>],"recorrencia_30d":1,"quase_la":true}
```

- [ ] **Step 1: testes** (`tests/api/test_oportunidades.py`):

```python
from datetime import timedelta

import pytest
from fakes import criar_anuncio, criar_preco_liga, criar_produto
from fakes_api import T0
from fakes_oportunidades import criar_atual_amazon, criar_oportunidade

from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import MotivoEncerramento, Papel, StatusCasamento

ROTAS = ["/api/oportunidades/resumo", "/api/oportunidades/ativas", "/api/oportunidades/encerradas",
         "/api/oportunidades/quase"]


@pytest.fixture
def dados(sessoes, relogio):
    agora = relogio()
    with sessoes() as s, s.begin():
        p = criar_produto(s, "api", nome="Final Fantasy")
        criar_preco_liga(s, p, "1000.00", listagem_em=agora)
        a = criar_anuncio(s, "B0API00001", p, StatusCasamento.CONFIRMADO)
        criar_atual_amazon(s, a, "800.00")
        criar_oportunidade(s, a, p, aberta_em=agora - timedelta(hours=1), preco_alertado="800")
        criar_oportunidade(s, a, p, aberta_em=agora - timedelta(days=1), fechada_em=agora - timedelta(hours=20),
                           motivo=MotivoEncerramento.PRECO_SUBIU)
        return p.id


def test_sem_sessao_401_e_sem_permissao_403(cliente, logar, sessoes):
    for rota in ROTAS:
        assert cliente.get(rota).status_code == 401
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.GRUPO, "ver_oportunidades", False)
    logar(Papel.GRUPO)
    for rota in [*ROTAS, "/api/produtos/1/historico"]:
        r = cliente.get(rota)
        assert r.status_code == 403 and r.json()["erro"] == "sem_permissao"


def test_periodo_invalido_400(cliente, logar):
    logar(Papel.GRUPO)
    r = cliente.get("/api/oportunidades/resumo?periodo=1a")
    assert r.status_code == 400 and r.json() == {"erro": "periodo_invalido", "mensagem": "Período inválido."}


def test_formatos_e_chaves_fechadas(cliente, logar, dados):
    logar(Papel.GRUPO)
    resumo = cliente.get("/api/oportunidades/resumo?periodo=7d").json()
    assert set(resumo) == {"periodo", "numeros", "por_dia"}
    assert resumo["numeros"]["diferenca_bruta"] == "200.00"
    ativas = cliente.get("/api/oportunidades/ativas").json()
    assert set(ativas) == {"ativas", "ultima_aberta_em"}
    assert set(ativas["ativas"][0]) == {"id", "produto", "anuncio", "preco_amazon", "preco_liga", "desconto_pct",
                                        "aberta_em", "em_risco_desde", "motivo_risco"}
    assert set(ativas["ativas"][0]["produto"]) == {"id", "nome", "imagem_url", "ativo"}
    assert set(ativas["ativas"][0]["anuncio"]) == {"titulo", "url", "imagem_url"}
    enc = cliente.get("/api/oportunidades/encerradas?periodo=tudo&motivo=preco_subiu").json()
    assert enc["total"] == 1 and enc["itens"][0]["motivo"] == "preco_subiu"
    assert set(enc["itens"][0]) == {"id", "produto", "aberta_em", "fechada_em", "aberta", "duracao_min", "alertas",
                                    "preco_alertado", "menor_preco", "preco_liga", "desconto_pct", "motivo"}
    quase = cliente.get("/api/oportunidades/quase").json()
    assert set(quase) == {"itens", "desconto_min_pct", "piso_pct"}
    hist = cliente.get(f"/api/produtos/{dados}/historico?periodo=30d").json()
    assert set(hist) == {"produto", "anuncio", "periodo", "escala", "amazon", "liga", "liga_medio",
                         "desconto_min_pct", "faixas", "oportunidades", "recorrencia_30d", "quase_la"}
    texto = str([resumo, ativas, enc, quase, hist]).lower()
    for proibido in ("vendedor", "casamento", "mensagem", "imposto", "frete", "seller"):
        assert proibido not in texto


def test_produto_inexistente_404(cliente, logar):
    logar(Papel.GRUPO)
    r = cliente.get("/api/produtos/999999/historico")
    assert r.status_code == 404 and r.json()["erro"] == "nao_encontrado"
```

(Confirmar que `fakes_api.Relogio()` devolve um `datetime` com fuso ao ser chamado; se `T0` de `fakes_api` não existir com esse nome, remover o import. O motivo "casamento_desfeito" pode aparecer no texto de `motivo` — por isso o teste não procura "casamento" em dados que tenham esse motivo; o cenário acima não tem.)

- [ ] **Step 2:** `uv run pytest -q tests/api/test_oportunidades.py` — FAIL (404 nas rotas).
- [ ] **Step 3: `src/tcg_sniper/api/rotas_oportunidades.py`:**

```python
"""Área de negócio: oportunidades e histórico de produto (só dado de mercado). Toda rota exige `ver_oportunidades`."""

from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from tcg_sniper.api.dependencias import Contexto, exige
from tcg_sniper.api.erros import ErroApi
from tcg_sniper.api.permissoes import Permissao
from tcg_sniper.avisos.servico import zona_e_host
from tcg_sniper.consultas import oportunidades as q
from tcg_sniper.consultas.historico_produto import historico_produto
from tcg_sniper.consultas.quase_la import quase_la
from tcg_sniper.db.models import MotivoEncerramento
from tcg_sniper.db.repositorio_amazon import obter_config
from tcg_sniper.oportunidades.motor import Regras

roteador = APIRouter(prefix="/api", tags=["oportunidades"])
VerOportunidades = Annotated[Contexto, Depends(exige(Permissao.VER_OPORTUNIDADES))]


class ProdutoSaida(BaseModel):
    id: int
    nome: str
    imagem_url: str | None
    ativo: bool


class AnuncioSaida(BaseModel):
    titulo: str
    url: str
    imagem_url: str | None


class NumerosSaida(BaseModel):
    diferenca_bruta: Decimal
    oportunidades: int
    desconto_medio: Decimal | None
    duracao_media_min: int | None
    produtos: int


class DiaSaida(BaseModel):
    dia: date
    oportunidades: int


class ResumoSaida(BaseModel):
    periodo: str
    numeros: NumerosSaida
    por_dia: list[DiaSaida]


class AtivaSaida(BaseModel):
    id: int
    produto: ProdutoSaida
    anuncio: AnuncioSaida
    preco_amazon: Decimal
    preco_liga: Decimal
    desconto_pct: Decimal
    aberta_em: datetime
    em_risco_desde: datetime | None
    motivo_risco: str | None


class AtivasSaida(BaseModel):
    ativas: list[AtivaSaida]
    ultima_aberta_em: datetime | None


class OportunidadeSaida(BaseModel):
    id: int
    produto: ProdutoSaida
    aberta_em: datetime
    fechada_em: datetime | None
    aberta: bool
    duracao_min: int
    alertas: int
    preco_alertado: Decimal
    menor_preco: Decimal
    preco_liga: Decimal
    desconto_pct: Decimal
    motivo: str | None


class EncerradasSaida(BaseModel):
    itens: list[OportunidadeSaida]
    total: int
    pagina: int
    por_pagina: int


class QuaseSaida(BaseModel):
    produto: ProdutoSaida
    anuncio: AnuncioSaida
    preco_amazon: Decimal
    preco_liga: Decimal
    desconto_pct: Decimal
    falta_reais: Decimal
    falta_pp: Decimal


class QuaseListaSaida(BaseModel):
    itens: list[QuaseSaida]
    desconto_min_pct: int
    piso_pct: int


class CabecalhoSaida(BaseModel):
    id: int
    nome: str
    edicao: str | None
    imagem_url: str | None
    url_liga: str


class PontoAmazonSaida(BaseModel):
    t: datetime
    preco: Decimal
    anuncio: str


class PontoLigaSaida(BaseModel):
    t: datetime
    preco: Decimal


class FaixaSaida(BaseModel):
    id: int
    inicio: datetime
    fim: datetime
    aberta: bool
    motivo: str | None


class HistoricoSaida(BaseModel):
    produto: CabecalhoSaida
    anuncio: AnuncioSaida | None
    periodo: str
    escala: str
    amazon: list[PontoAmazonSaida]
    liga: list[PontoLigaSaida]
    liga_medio: list[PontoLigaSaida]
    desconto_min_pct: int
    faixas: list[FaixaSaida]
    oportunidades: list[OportunidadeSaida]
    recorrencia_30d: int
    quase_la: bool


def _desde(periodo: str, agora: datetime) -> datetime | None:
    try:
        return q.desde_do_periodo(periodo, agora)
    except ValueError:
        raise ErroApi(400, "periodo_invalido", "Período inválido.") from None


@roteador.get("/oportunidades/resumo")
def resumo(request: Request, _c: VerOportunidades, periodo: str = "7d") -> ResumoSaida:
    estado = request.app.state
    agora = estado.relogio()
    desde = _desde(periodo, agora)
    with estado.sessoes() as s:
        zona, _ = zona_e_host(s)
        numeros = q.numeros_periodo(s, desde, agora)
        dias = q.por_dia(s, desde, agora, zona)
    return ResumoSaida(periodo=periodo, numeros=NumerosSaida(**asdict(numeros)),
                       por_dia=[DiaSaida(**asdict(d)) for d in dias])


@roteador.get("/oportunidades/ativas")
def ativas(request: Request, _c: VerOportunidades) -> AtivasSaida:
    with request.app.state.sessoes() as s:
        return AtivasSaida(ativas=[AtivaSaida.model_validate(asdict(a)) for a in q.ativas(s)],
                           ultima_aberta_em=q.ultima_aberta_em(s))


@roteador.get("/oportunidades/encerradas")
def encerradas(
    request: Request, _c: VerOportunidades, periodo: str = "7d", motivo: MotivoEncerramento | None = None,
    pagina: Annotated[int, Query(ge=1, le=10_000)] = 1,
) -> EncerradasSaida:
    estado = request.app.state
    agora = estado.relogio()
    desde = _desde(periodo, agora)
    with estado.sessoes() as s:
        resultado = q.encerradas(s, desde, motivo, pagina, agora)
    return EncerradasSaida.model_validate(asdict(resultado))


def _regras_e_piso(s) -> tuple[Regras, int]:
    config = obter_config(s)
    return Regras.de(config), config.quase_oportunidade_min_pct


@roteador.get("/oportunidades/quase")
def quase(
    request: Request, _c: VerOportunidades, limite: Annotated[int | None, Query(ge=1, le=500)] = None
) -> QuaseListaSaida:
    estado = request.app.state
    with estado.sessoes() as s:
        regras, piso = _regras_e_piso(s)
        itens = quase_la(s, regras, piso, estado.relogio(), limite=limite)
    return QuaseListaSaida(itens=[QuaseSaida.model_validate(asdict(i)) for i in itens],
                           desconto_min_pct=regras.desconto_min_pct, piso_pct=piso)


@roteador.get("/produtos/{produto_id}/historico")
def historico(request: Request, produto_id: int, _c: VerOportunidades, periodo: str = "30d") -> HistoricoSaida:
    estado = request.app.state
    agora = estado.relogio()
    desde = _desde(periodo, agora)
    with estado.sessoes() as s:
        zona, _ = zona_e_host(s)
        regras, piso = _regras_e_piso(s)
        h = historico_produto(s, produto_id, desde, agora, regras, piso, zona)
    if h is None:
        raise ErroApi(404, "nao_encontrado", "Produto não encontrado.")
    return HistoricoSaida.model_validate({**asdict(h), "periodo": periodo})
```

Em `app.py`: `from tcg_sniper.api import rotas_acessos, rotas_auth, rotas_oportunidades, rotas_usuarios` e `app.include_router(rotas_oportunidades.roteador)`.

Dinheiro: o Pydantic 2 serializa `Decimal` como texto no JSON ("200.00") — conferido pelo teste. Se sair número, declarar os campos como `Annotated[Decimal, PlainSerializer(lambda v: f"{v:.2f}", return_type=str)]` num alias `Dinheiro` e usar nos modelos.

- [ ] **Step 4:** `uv run pytest -q tests/api` e `uv run ruff check` — PASS (o teste que confere que toda rota declara permissão também precisa passar).
- [ ] **Step 5:** commit `feat: business area opportunity API`.

---

### Task 7: Front — página Oportunidades

**Files:**
- Modify: `web/package.json`, `web/package-lock.json` (Recharts), `web/Caddyfile:27` (`img-src`), `web/src/App.tsx`, `web/src/tipos.ts`, `web/src/teste/configuracao.ts`, `web/src/rotas.test.tsx`
- Delete: `web/src/paginas/AreaNegocio.tsx`
- Create: `web/src/formato.ts`, `web/src/formato.test.ts`, `web/src/cores.ts`, `web/src/componentes/SeletorPeriodo.tsx`, `web/src/componentes/MotivoSelo.tsx`, `web/src/paginas/Oportunidades.tsx`, `web/src/paginas/Oportunidades.test.tsx`, `tests/test_caddyfile.py`

**Interfaces:**
- Consumes: contrato JSON da Tarefa 6 (bloco "Produces"); permissão da Tarefa 3.
- Produces (Tarefa 8): `formato.ts` (`reais`, `pct`, `duracao`, `dataHora`, `ROTULOS_MOTIVO`), `cores.ts` (`useCoresTema`), `SeletorPeriodo`, `MotivoSelo`, tipos `Periodo`, `ProdutoResumo`, `AnuncioResumo`, `OportunidadeLinha`, `Historico` em `tipos.ts`.

- [ ] **Step 1: dependência.** `cd web && npm view recharts versions --json` e escolher a **3.x mais nova publicada há pelo menos 14 dias** (`npm view recharts time --json`); `npm install --save-exact recharts@<versão>`. `npm run build` tem de passar.
- [ ] **Step 2: CSP.** No `web/Caddyfile`, `img-src 'self' data:` vira `img-src 'self' data: https://repositorio.sbrauble.com https://m.media-amazon.com`. Teste `tests/test_caddyfile.py`:

```python
from pathlib import Path

CADDYFILE = Path(__file__).resolve().parents[1] / "web" / "Caddyfile"


def test_csp_libera_so_as_imagens_da_liga_e_da_amazon():
    texto = CADDYFILE.read_text(encoding="utf-8")
    assert "img-src 'self' data: https://repositorio.sbrauble.com https://m.media-amazon.com;" in texto
    assert "style-src 'self';" in texto and "script-src 'self';" in texto
```

- [ ] **Step 3: tipos** (`web/src/tipos.ts`, no fim):

```ts
export type Periodo = "7d" | "30d" | "90d" | "tudo";
export type Motivo =
  | "casamento_desfeito" | "sem_leitura" | "liga_desatualizada" | "oferta_sumiu" | "vendedor" | "liga_caiu"
  | "preco_subiu";

export interface ProdutoResumo { id: number; nome: string; imagem_url: string | null; ativo: boolean }
export interface AnuncioResumo { titulo: string; url: string; imagem_url: string | null }

/** GET /api/oportunidades/resumo. Dinheiro e % vêm como texto decimal ("1299.90"). */
export interface ResumoOportunidades {
  periodo: Periodo;
  numeros: {
    diferenca_bruta: string; oportunidades: number; desconto_medio: string | null;
    duracao_media_min: number | null; produtos: number;
  };
  por_dia: { dia: string; oportunidades: number }[];
}

/** GET /api/oportunidades/ativas. */
export interface AtivasOportunidades {
  ativas: {
    id: number; produto: ProdutoResumo; anuncio: AnuncioResumo; preco_amazon: string; preco_liga: string;
    desconto_pct: string; aberta_em: string; em_risco_desde: string | null; motivo_risco: Motivo | null;
  }[];
  ultima_aberta_em: string | null;
}

/** Item das encerradas e do histórico do produto. */
export interface OportunidadeLinha {
  id: number; produto: ProdutoResumo; aberta_em: string; fechada_em: string | null; aberta: boolean;
  duracao_min: number; alertas: number; preco_alertado: string; menor_preco: string; preco_liga: string;
  desconto_pct: string; motivo: Motivo | null;
}

/** GET /api/oportunidades/encerradas. */
export interface EncerradasOportunidades { itens: OportunidadeLinha[]; total: number; pagina: number; por_pagina: number }

/** GET /api/oportunidades/quase. */
export interface QuaseOportunidades {
  itens: {
    produto: ProdutoResumo; anuncio: AnuncioResumo; preco_amazon: string; preco_liga: string; desconto_pct: string;
    falta_reais: string; falta_pp: string;
  }[];
  desconto_min_pct: number;
  piso_pct: number;
}

/** GET /api/produtos/{id}/historico. */
export interface Historico {
  produto: { id: number; nome: string; edicao: string | null; imagem_url: string | null; url_liga: string };
  anuncio: AnuncioResumo | null;
  periodo: Periodo;
  escala: "hora" | "dia";
  amazon: { t: string; preco: string; anuncio: string }[];
  liga: { t: string; preco: string }[];
  liga_medio: { t: string; preco: string }[];
  desconto_min_pct: number;
  faixas: { id: number; inicio: string; fim: string; aberta: boolean; motivo: Motivo | null }[];
  oportunidades: OportunidadeLinha[];
  recorrencia_30d: number;
  quase_la: boolean;
}
```

- [ ] **Step 4: formato (teste primeiro)** `web/src/formato.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { duracao, pct, reais } from "./formato";

describe("formato", () => {
  it("reais em pt-BR", () => {
    expect(reais("1299.9")).toBe("R$ 1.299,90");
    expect(reais(null)).toBe("—");
  });
  it("percentual", () => {
    expect(pct("27.4")).toBe("27,4%");
    expect(pct(null)).toBe("—");
  });
  it("duração", () => {
    expect(duracao(45)).toBe("45 min");
    expect(duracao(200)).toBe("3 h 20 min");
    expect(duracao(120)).toBe("2 h");
    expect(duracao(60 * 24 * 2 + 60)).toBe("2 d 1 h");
    expect(duracao(null)).toBe("—");
  });
});
```

(O `Intl` do Node pode usar espaço não separável depois de "R$"; o teste compara com `.replace(/ /g, " ")` aplicado dentro de `reais`.)

`web/src/formato.ts`:

```ts
// Formatos da área de negócio: reais e % em pt-BR, duração curta, data e hora no fuso do navegador.
import type { Motivo } from "./tipos";

const MOEDA = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const PCT = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const DATA_HORA = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const DATA = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit" });

export function reais(valor: string | null): string {
  return valor === null ? "—" : MOEDA.format(Number(valor)).replace(/ /g, " ");
}

export function pct(valor: string | null): string {
  return valor === null ? "—" : `${PCT.format(Number(valor))}%`;
}

export function duracao(minutos: number | null): string {
  if (minutos === null) return "—";
  if (minutos < 60) return `${minutos} min`;
  const dias = Math.floor(minutos / 1440);
  const horas = Math.floor((minutos % 1440) / 60);
  const resto = minutos % 60;
  if (dias > 0) return horas > 0 ? `${dias} d ${horas} h` : `${dias} d`;
  return resto > 0 ? `${horas} h ${resto} min` : `${horas} h`;
}

export const dataHora = (iso: string) => DATA_HORA.format(new Date(iso));
export const dataCurta = (iso: string) => DATA.format(new Date(iso));

/** Iguais aos dos avisos do WhatsApp (oportunidades/mensagens.ROTULOS_MOTIVO). */
export const ROTULOS_MOTIVO: Record<Motivo, string> = {
  preco_subiu: "preço subiu",
  oferta_sumiu: "oferta sumiu",
  liga_caiu: "Liga baixou",
  vendedor: "vendedor mudou",
  liga_desatualizada: "preço da Liga desatualizado",
  sem_leitura: "anúncio sem leitura",
  casamento_desfeito: "casamento desfeito",
};
```

- [ ] **Step 5: componentes pequenos.** `web/src/componentes/SeletorPeriodo.tsx`:

```tsx
// Seletor de período (join de botões do DaisyUI). Classes literais: ativo = btn-primary.
import type { Periodo } from "../tipos";

const OPCOES: { valor: Periodo; rotulo: string }[] = [
  { valor: "7d", rotulo: "7 dias" },
  { valor: "30d", rotulo: "30 dias" },
  { valor: "90d", rotulo: "90 dias" },
  { valor: "tudo", rotulo: "Tudo" },
];

export function SeletorPeriodo({ valor, aoMudar }: { valor: Periodo; aoMudar: (p: Periodo) => void }) {
  return (
    <div className="join" role="group" aria-label="Período">
      {OPCOES.map((o) => (
        <button
          key={o.valor}
          type="button"
          className={o.valor === valor ? "btn btn-sm btn-primary join-item" : "btn btn-sm join-item"}
          aria-pressed={o.valor === valor}
          onClick={() => aoMudar(o.valor)}
        >
          {o.rotulo}
        </button>
      ))}
    </div>
  );
}
```

`web/src/componentes/MotivoSelo.tsx`:

```tsx
// Selo do motivo de encerramento; sem motivo = fechada antes do registro (2026-10-20).
import { ROTULOS_MOTIVO } from "../formato";
import type { Motivo } from "../tipos";

export function MotivoSelo({ motivo, aberta = false }: { motivo: Motivo | null; aberta?: boolean }) {
  if (aberta) return <span className="badge badge-success badge-sm">aberta</span>;
  if (motivo === null) return <span className="badge badge-ghost badge-sm">antes do registro</span>;
  return <span className="badge badge-outline badge-sm">{ROTULOS_MOTIVO[motivo]}</span>;
}
```

`web/src/cores.ts` (cores do tema para o Recharts, que não lê `var()` em atributo):

```ts
// Cores do tema do DaisyUI lidas do CSS, refeitas quando o tema muda (data-theme no <html>).
import { useEffect, useState } from "react";

export interface CoresTema { primaria: string; secundaria: string; texto: string; aviso: string; sucesso: string }

function ler(): CoresTema {
  const css = getComputedStyle(document.documentElement);
  const v = (nome: string, padrao: string) => css.getPropertyValue(nome).trim() || padrao;
  return {
    primaria: v("--color-primary", "#570df8"),
    secundaria: v("--color-secondary", "#f000b8"),
    texto: v("--color-base-content", "#1f2937"),
    aviso: v("--color-warning", "#fbbd23"),
    sucesso: v("--color-success", "#36d399"),
  };
}

export function useCoresTema(): CoresTema {
  const [cores, setCores] = useState(ler);
  useEffect(() => {
    const observador = new MutationObserver(() => setCores(ler()));
    observador.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observador.disconnect();
  }, []);
  return cores;
}
```

Em `web/src/teste/configuracao.ts` (jsdom não tem `ResizeObserver`, que o `ResponsiveContainer` usa):

```ts
class ResizeObserverFalso {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverFalso);
```

Como o `afterEach` chama `vi.unstubAllGlobals()`, colocar o `stubGlobal` num `beforeEach` (importar `beforeEach` do vitest).

- [ ] **Step 6: testes da página** (`web/src/paginas/Oportunidades.test.tsx`):

```tsx
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { apiFalsa, EU_GRUPO, ok, renderizarEm } from "../teste/apoio";

const PRODUTO = { id: 7, nome: "Final Fantasy - Caixa", imagem_url: null, ativo: true };
const ANUNCIO = { titulo: "Caixa FF", url: "https://www.amazon.com.br/dp/B0X", imagem_url: null };
const resumo = (periodo: string, oportunidades: number) => ok({
  periodo,
  numeros: oportunidades
    ? { diferenca_bruta: "4820.00", oportunidades, desconto_medio: "27.40", duracao_media_min: 200, produtos: 9 }
    : { diferenca_bruta: "0.00", oportunidades: 0, desconto_medio: null, duracao_media_min: null, produtos: 0 },
  por_dia: [{ dia: "2026-10-20", oportunidades }],
});
const VAZIO = {
  "GET /api/oportunidades/ativas": ok({ ativas: [], ultima_aberta_em: null }),
  "GET /api/oportunidades/quase?limite=20": ok({ itens: [], desconto_min_pct: 20, piso_pct: 10 }),
  "GET /api/oportunidades/encerradas?periodo=7d&pagina=1": ok({ itens: [], total: 0, pagina: 1, por_pagina: 25 }),
};

describe("Oportunidades", () => {
  it("mostra números, ativa, quase lá e encerrada", async () => {
    apiFalsa({
      "GET /api/auth/eu": ok(EU_GRUPO),
      "GET /api/oportunidades/resumo?periodo=7d": resumo("7d", 12),
      "GET /api/oportunidades/ativas": ok({
        ativas: [{ id: 1, produto: PRODUTO, anuncio: ANUNCIO, preco_amazon: "1299.90", preco_liga: "1589.00",
          desconto_pct: "18.20", aberta_em: new Date().toISOString(), em_risco_desde: new Date().toISOString(),
          motivo_risco: "preco_subiu" }],
        ultima_aberta_em: null,
      }),
      "GET /api/oportunidades/quase?limite=20": ok({
        itens: [{ produto: { ...PRODUTO, id: 8, nome: "Duskmourn" }, anuncio: ANUNCIO, preco_amazon: "850.00",
          preco_liga: "1000.00", desconto_pct: "15.00", falta_reais: "50.00", falta_pp: "5.00" }],
        desconto_min_pct: 20, piso_pct: 10,
      }),
      "GET /api/oportunidades/encerradas?periodo=7d&pagina=1": ok({
        itens: [{ id: 2, produto: PRODUTO, aberta_em: "2026-10-18T10:15:00-03:00",
          fechada_em: "2026-10-18T13:35:00-03:00", aberta: false, duracao_min: 200, alertas: 2,
          preco_alertado: "1299.90", menor_preco: "1249.90", preco_liga: "1589.00", desconto_pct: "18.20",
          motivo: "preco_subiu" }],
        total: 1, pagina: 1, por_pagina: 25,
      }),
    });
    renderizarEm("/");
    expect(await screen.findByRole("heading", { name: "Oportunidades" })).toBeInTheDocument();
    expect(await screen.findByText("R$ 4.820,00")).toBeInTheDocument();
    expect(screen.getByText("antes de taxas e frete")).toBeInTheDocument();
    expect(screen.getByText("3 h 20 min")).toBeInTheDocument();
    const ativas = screen.getByRole("region", { name: "Ativas agora" });
    expect(within(ativas).getByText(/em risco desde/)).toBeInTheDocument();
    expect(within(ativas).getByRole("link", { name: "Ver na Amazon" })).toHaveAttribute("href", ANUNCIO.url);
    expect(within(ativas).getByRole("link", { name: "Histórico do produto" })).toHaveAttribute("href", "/produtos/7");
    const quase = screen.getByRole("region", { name: "Quase lá" });
    expect(within(quase).getByText("faltam R$ 50,00 (5%)")).toBeInTheDocument();
    const encerradas = screen.getByRole("region", { name: "Encerradas no período" });
    expect(within(encerradas).getByText("preço subiu")).toBeInTheDocument();
  });

  it("período vazio: médias com traço e textos de vazio; troca de período busca de novo", async () => {
    const chamadas = apiFalsa({
      "GET /api/auth/eu": ok(EU_GRUPO),
      "GET /api/oportunidades/resumo?periodo=7d": resumo("7d", 0),
      "GET /api/oportunidades/resumo?periodo=30d": resumo("30d", 3),
      "GET /api/oportunidades/encerradas?periodo=30d&pagina=1": ok({ itens: [], total: 0, pagina: 1, por_pagina: 25 }),
      ...VAZIO,
    });
    renderizarEm("/");
    expect(await screen.findByText("Nenhuma oportunidade aberta agora")).toBeInTheDocument();
    expect(screen.getByText("Nenhuma oportunidade nos últimos 7 dias")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
    await userEvent.click(screen.getByRole("button", { name: "30 dias" }));
    expect(await screen.findByText("R$ 4.820,00")).toBeInTheDocument();
    expect(chamadas.some((c) => c.caminho === "/api/oportunidades/resumo?periodo=30d")).toBe(true);
  });

  it("erro de rede mostra alerta com Tentar de novo", async () => {
    apiFalsa({
      "GET /api/auth/eu": ok(EU_GRUPO),
      "GET /api/oportunidades/resumo?periodo=7d": [{ status: 500, corpo: { erro: "interno", mensagem: "Erro interno. Tente de novo em instantes." } }, resumo("7d", 12)],
      ...VAZIO,
    });
    renderizarEm("/");
    expect(await screen.findByRole("alert")).toHaveTextContent("Erro interno");
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByText("R$ 4.820,00")).toBeInTheDocument();
  });

  it("sem ver_oportunidades vai para Sem acesso", async () => {
    apiFalsa({ "GET /api/auth/eu": ok({ ...EU_GRUPO, permissoes: ["ver_area_negocio"] }) });
    renderizarEm("/");
    expect(await screen.findByRole("heading", { name: "Sem acesso" })).toBeInTheDocument();
  });
});
```

Em `web/src/rotas.test.tsx`, os testes que abrem `/` como grupo passam a esperar o heading "Oportunidades" e precisam das respostas da página: registrar `"GET /api/oportunidades/resumo?periodo=7d"`, `ativas`, `quase?limite=20` e `encerradas?periodo=7d&pagina=1` com os mesmos objetos vazios (copiar `resumo("7d", 0)` e `VAZIO` para um ajudante `respostasOportunidadesVazias()` em `teste/apoio.tsx` e usar nos dois arquivos).

- [ ] **Step 7:** `cd web && npm test` — FAIL.
- [ ] **Step 8: página** `web/src/paginas/Oportunidades.tsx`:

```tsx
// Área de negócio: números do período, ativas, quase lá, encerradas e oportunidades por dia. Só dado de mercado.
// As ativas recarregam a cada 60 s; o resto ao abrir e ao trocar o período ou a página.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { chamarApi } from "../api";
import { MotivoSelo } from "../componentes/MotivoSelo";
import { SeletorPeriodo } from "../componentes/SeletorPeriodo";
import { useCoresTema } from "../cores";
import { dataCurta, dataHora, duracao, pct, reais } from "../formato";
import { useSessao } from "../sessao";
import type {
  AtivasOportunidades, EncerradasOportunidades, Periodo, QuaseOportunidades, ResumoOportunidades,
} from "../tipos";

const TEXTO_PERIODO: Record<Periodo, string> = {
  "7d": "nos últimos 7 dias", "30d": "nos últimos 30 dias", "90d": "nos últimos 90 dias", tudo: "até agora",
};

function minutosDesde(iso: string): number {
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
}

export function Oportunidades() {
  const { tratarErro } = useSessao();
  const cores = useCoresTema();
  const [periodo, setPeriodo] = useState<Periodo>("7d");
  const [pagina, setPagina] = useState(1);
  const [resumo, setResumo] = useState<ResumoOportunidades | null>(null);
  const [ativas, setAtivas] = useState<AtivasOportunidades | null>(null);
  const [quase, setQuase] = useState<QuaseOportunidades | null>(null);
  const [todasQuase, setTodasQuase] = useState(false);
  const [encerradas, setEncerradas] = useState<EncerradasOportunidades | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    setErro(null);
    try {
      const [r, e] = await Promise.all([
        chamarApi<ResumoOportunidades>(`/api/oportunidades/resumo?periodo=${periodo}`),
        chamarApi<EncerradasOportunidades>(`/api/oportunidades/encerradas?periodo=${periodo}&pagina=${pagina}`),
      ]);
      setResumo(r);
      setEncerradas(e);
    } catch (e) {
      setErro(tratarErro(e));
    }
  }, [periodo, pagina, tratarErro]);

  const carregarAtivas = useCallback(async () => {
    try {
      const caminhoQuase = todasQuase ? "/api/oportunidades/quase" : "/api/oportunidades/quase?limite=20";
      const [a, q] = await Promise.all([
        chamarApi<AtivasOportunidades>("/api/oportunidades/ativas"),
        chamarApi<QuaseOportunidades>(caminhoQuase),
      ]);
      setAtivas(a);
      setQuase(q);
    } catch (e) {
      setErro(tratarErro(e));
    }
  }, [todasQuase, tratarErro]);

  useEffect(() => { void carregar(); }, [carregar]);
  useEffect(() => {
    void carregarAtivas();
    const id = window.setInterval(() => void carregarAtivas(), 60_000);
    return () => window.clearInterval(id);
  }, [carregarAtivas]);

  function trocarPeriodo(p: Periodo) {
    setPagina(1);
    setPeriodo(p);
  }

  const n = resumo?.numeros;
  const paginas = encerradas ? Math.max(1, Math.ceil(encerradas.total / encerradas.por_pagina)) : 1;

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">Oportunidades</h1>
        <SeletorPeriodo valor={periodo} aoMudar={trocarPeriodo} />
      </div>

      {erro && (
        <div role="alert" className="alert alert-error">
          <span>{erro}</span>
          <button type="button" className="btn btn-sm" onClick={() => { void carregar(); void carregarAtivas(); }}>
            Tentar de novo
          </button>
        </div>
      )}

      {n && (
        <div className="stats stats-vertical lg:stats-horizontal w-full shadow-sm">
          <div className="stat">
            <div className="stat-title">Diferença bruta</div>
            <div className="stat-value text-primary">{reais(n.diferenca_bruta)}</div>
            <div className="stat-desc">antes de taxas e frete</div>
          </div>
          <div className="stat">
            <div className="stat-title">Oportunidades</div>
            <div className="stat-value">{n.oportunidades}</div>
            <div className="stat-desc">{n.produtos} produtos</div>
          </div>
          <div className="stat">
            <div className="stat-title">Desconto médio</div>
            <div className="stat-value">{pct(n.desconto_medio)}</div>
          </div>
          <div className="stat">
            <div className="stat-title">Duração média</div>
            <div className="stat-value">{duracao(n.duracao_media_min)}</div>
          </div>
        </div>
      )}
      {n && n.oportunidades === 0 && <p className="opacity-70">Nenhuma oportunidade {TEXTO_PERIODO[periodo]}</p>}

      <section aria-labelledby="titulo-ativas" className="space-y-3">
        <h2 id="titulo-ativas" className="text-xl font-semibold">Ativas agora</h2>
        {ativas && ativas.ativas.length === 0 && (
          <p className="opacity-70">
            Nenhuma oportunidade aberta agora
            {ativas.ultima_aberta_em && <> · a última abriu em {dataHora(ativas.ultima_aberta_em)}</>}
          </p>
        )}
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {ativas?.ativas.map((a) => (
            <div key={a.id} className="card bg-base-100 shadow-sm">
              {(a.produto.imagem_url ?? a.anuncio.imagem_url) && (
                <figure className="h-40 bg-base-200">
                  <img src={(a.produto.imagem_url ?? a.anuncio.imagem_url)!} alt="" className="h-full object-contain" />
                </figure>
              )}
              <div className="card-body gap-2">
                <h3 className="card-title text-base">{a.produto.nome}</h3>
                <p>
                  <span className="text-lg font-bold">{reais(a.preco_amazon)}</span>
                  <span className="opacity-70"> · Liga {reais(a.preco_liga)}</span>
                </p>
                <div className="flex flex-wrap gap-2">
                  <span className="badge badge-primary">{pct(a.desconto_pct)}</span>
                  <span className="badge badge-ghost">aberta há {duracao(minutosDesde(a.aberta_em))}</span>
                  {a.em_risco_desde && (
                    <span className="badge badge-warning">em risco desde {dataHora(a.em_risco_desde)}</span>
                  )}
                </div>
                <div className="card-actions justify-end">
                  <a className="btn btn-primary btn-sm" href={a.anuncio.url} target="_blank" rel="noreferrer">
                    Ver na Amazon
                  </a>
                  <Link className="btn btn-ghost btn-sm" to={`/produtos/${a.produto.id}`}>Histórico do produto</Link>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="titulo-quase" className="space-y-3">
        <h2 id="titulo-quase" className="text-xl font-semibold">Quase lá</h2>
        {quase && quase.itens.length === 0 && (
          <p className="opacity-70">Nenhum produto entre {quase.piso_pct}% e {quase.desconto_min_pct}% de desconto agora</p>
        )}
        {quase && quase.itens.length > 0 && (
          <div className="overflow-x-auto">
            <table className="table table-sm">
              <thead><tr><th>Produto</th><th>Desconto</th><th>Falta</th></tr></thead>
              <tbody>
                {quase.itens.map((q) => (
                  <tr key={q.produto.id}>
                    <td><Link className="link" to={`/produtos/${q.produto.id}`}>{q.produto.nome}</Link></td>
                    <td>{pct(q.desconto_pct)}</td>
                    <td>faltam {reais(q.falta_reais)} ({pct(q.falta_pp)})</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {quase && !todasQuase && quase.itens.length === 20 && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setTodasQuase(true)}>Ver todas</button>
        )}
      </section>

      <section aria-labelledby="titulo-encerradas" className="space-y-3">
        <h2 id="titulo-encerradas" className="text-xl font-semibold">Encerradas no período</h2>
        {encerradas && encerradas.itens.length === 0 && <p className="opacity-70">Nenhuma encerrada {TEXTO_PERIODO[periodo]}</p>}
        {encerradas && encerradas.itens.length > 0 && (
          <div className="overflow-x-auto">
            <table className="table table-sm">
              <thead>
                <tr><th>Produto</th><th>Abriu</th><th>Durou</th><th>Alerta → menor</th><th>Desconto</th><th>Motivo</th></tr>
              </thead>
              <tbody>
                {encerradas.itens.map((e) => (
                  <tr key={e.id}>
                    <td>
                      {e.produto.ativo
                        ? <Link className="link" to={`/produtos/${e.produto.id}?oportunidade=${e.id}`}>{e.produto.nome}</Link>
                        : e.produto.nome}
                    </td>
                    <td>{dataHora(e.aberta_em)}</td>
                    <td>{duracao(e.duracao_min)}</td>
                    <td>{reais(e.preco_alertado)} → {reais(e.menor_preco)}</td>
                    <td>{pct(e.desconto_pct)}</td>
                    <td><MotivoSelo motivo={e.motivo} aberta={e.aberta} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {paginas > 1 && (
          <div className="join">
            <button type="button" className="btn btn-sm join-item" disabled={pagina <= 1} onClick={() => setPagina(pagina - 1)}>«</button>
            <span className="btn btn-sm join-item">Página {pagina} de {paginas}</span>
            <button type="button" className="btn btn-sm join-item" disabled={pagina >= paginas} onClick={() => setPagina(pagina + 1)}>»</button>
          </div>
        )}
      </section>

      {resumo && resumo.por_dia.length > 0 && (
        <section aria-labelledby="titulo-por-dia" className="space-y-3">
          <h2 id="titulo-por-dia" className="text-xl font-semibold">Oportunidades por dia</h2>
          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={resumo.por_dia.map((d) => ({ ...d, rotulo: dataCurta(`${d.dia}T12:00:00`) }))}>
                <XAxis dataKey="rotulo" stroke={cores.texto} fontSize={12} />
                <YAxis allowDecimals={false} stroke={cores.texto} fontSize={12} width={28} />
                <Tooltip />
                <Bar dataKey="oportunidades" name="Oportunidades" fill={cores.primaria} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}
    </section>
  );
}
```

O filtro por motivo das encerradas: acrescentar um `<select className="select select-sm">` com "Todos os motivos" + `ROTULOS_MOTIVO`, que soma `&motivo=<valor>` ao caminho e volta à página 1 (as chamadas falsas dos testes usam o caminho sem `motivo`). `aria-labelledby` + `<section>` dá o papel `region` com o nome do título, que os testes usam.

- [ ] **Step 9: rotas** (`web/src/App.tsx`): trocar `AreaNegocio` por `Oportunidades`; a rota `/` fica:

```tsx
        <Route
          path="/"
          element={
            <Exige permissao="ver_area_negocio">
              <Exige permissao="ver_oportunidades">
                <Oportunidades />
              </Exige>
            </Exige>
          }
        />
```

Apagar `web/src/paginas/AreaNegocio.tsx` e o `enderecoAdminAntigo` dele se ficar sem uso (o `Gestao.tsx` usa `enderecos.ts`; não apagar o arquivo).

- [ ] **Step 10:** `cd web && npm test && npm run build`, `uv run pytest -q tests/test_caddyfile.py` — PASS.
- [ ] **Step 11:** commit `feat: opportunities page in the business area`.

---

### Task 8: Front — página Produto

**Files:**
- Create: `web/src/paginas/Produto.tsx`, `web/src/componentes/CurvaPreco.tsx`, `web/src/paginas/Produto.test.tsx`
- Modify: `web/src/App.tsx` (rota `/produtos/:id`)

**Interfaces:**
- Consumes: Tarefa 7 (`formato.ts`, `cores.ts`, `SeletorPeriodo`, `MotivoSelo`, tipo `Historico`); `GET /api/produtos/{id}/historico?periodo=` (Tarefa 6).

- [ ] **Step 1: testes** (`web/src/paginas/Produto.test.tsx`):

```tsx
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { apiFalsa, EU_GRUPO, ok, renderizarEm } from "../teste/apoio";
import type { Historico } from "../tipos";

function historico(parcial: Partial<Historico> = {}): Historico {
  return {
    produto: { id: 7, nome: "Final Fantasy - Caixa", edicao: "FIN", imagem_url: null, url_liga: "https://liga.test/p/7" },
    anuncio: { titulo: "Caixa FF", url: "https://www.amazon.com.br/dp/B0X", imagem_url: null },
    periodo: "30d", escala: "hora",
    amazon: [{ t: "2026-10-18T10:00:00-03:00", preco: "1299.90", anuncio: "Caixa FF" }],
    liga: [{ t: "2026-10-18T04:00:00-03:00", preco: "1589.00" }],
    liga_medio: [],
    desconto_min_pct: 20,
    faixas: [{ id: 2, inicio: "2026-10-18T10:15:00-03:00", fim: "2026-10-18T13:15:00-03:00", aberta: false, motivo: "preco_subiu" }],
    oportunidades: [{ id: 2, produto: { id: 7, nome: "Final Fantasy - Caixa", imagem_url: null, ativo: true },
      aberta_em: "2026-10-18T10:15:00-03:00", fechada_em: "2026-10-18T13:35:00-03:00", aberta: false,
      duracao_min: 180, alertas: 2, preco_alertado: "1299.90", menor_preco: "1249.90", preco_liga: "1589.00",
      desconto_pct: "18.20", motivo: "preco_subiu" }],
    recorrencia_30d: 4,
    quase_la: true,
    ...parcial,
  };
}

describe("Produto", () => {
  it("cabeçalho, recorrência, links, quase lá e histórico", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO), "GET /api/produtos/7/historico?periodo=30d": ok(historico()) });
    renderizarEm("/produtos/7?oportunidade=2");
    expect(await screen.findByRole("heading", { name: "Final Fantasy - Caixa" })).toBeInTheDocument();
    expect(screen.getByText("4ª oportunidade em 30 dias")).toBeInTheDocument();
    expect(screen.getByText("quase lá")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ver na Liga" })).toHaveAttribute("href", "https://liga.test/p/7");
    expect(screen.getByRole("link", { name: "Ver na Amazon" })).toHaveAttribute("href", "https://www.amazon.com.br/dp/B0X");
    expect(screen.getByRole("figure", { name: /Curva de preço/ })).toBeInTheDocument();
    const tabela = screen.getByRole("region", { name: "Oportunidades deste produto" });
    expect(within(tabela).getByText("3 h")).toBeInTheDocument();
    expect(within(tabela).getByText("preço subiu")).toBeInTheDocument();
  });

  it("sem leituras e sem Liga: textos de vazio; troca de período", async () => {
    apiFalsa({
      "GET /api/auth/eu": ok(EU_GRUPO),
      "GET /api/produtos/7/historico?periodo=30d": ok(historico({ amazon: [], liga: [], oportunidades: [], faixas: [] })),
      "GET /api/produtos/7/historico?periodo=7d": ok(historico({ periodo: "7d" })),
    });
    renderizarEm("/produtos/7");
    expect(await screen.findByText("Ainda não há leituras suficientes para a curva")).toBeInTheDocument();
    expect(screen.getByText("sem preço da Liga no período")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "7 dias" }));
    expect(await screen.findByRole("figure", { name: /Curva de preço/ })).toBeInTheDocument();
  });

  it("produto inexistente: Não encontrada", async () => {
    apiFalsa({
      "GET /api/auth/eu": ok(EU_GRUPO),
      "GET /api/produtos/9/historico?periodo=30d": { status: 404, corpo: { erro: "nao_encontrado", mensagem: "Produto não encontrado." } },
    });
    renderizarEm("/produtos/9");
    expect(await screen.findByRole("heading", { name: /não encontrada/i })).toBeInTheDocument();
  });
});
```

(Conferir o heading real de `NaoEncontrada.tsx` e ajustar o regex.)

- [ ] **Step 2:** `cd web && npm test` — FAIL.
- [ ] **Step 3: `web/src/componentes/CurvaPreco.tsx`:**

```tsx
// Curva de preço do produto: Amazon (menor elegível), Liga "a partir de", médio da Liga e preço alvo (Liga com o
// desconto mínimo), com as oportunidades como faixas. Linhas em degrau: o preço vale até a próxima leitura.
import {
  CartesianGrid, Legend, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { useCoresTema } from "../cores";
import { dataHora, reais } from "../formato";
import type { Historico } from "../tipos";

const ms = (iso: string) => new Date(iso).getTime();

export function CurvaPreco({ historico, destaque }: { historico: Historico; destaque: number | null }) {
  const cores = useCoresTema();
  const fator = 1 - historico.desconto_min_pct / 100;
  const amazon = historico.amazon.map((p) => ({ t: ms(p.t), amazon: Number(p.preco), anuncio: p.anuncio }));
  const liga = historico.liga.map((p) => ({ t: ms(p.t), liga: Number(p.preco), alvo: Number(p.preco) * fator }));
  const medio = historico.liga_medio.map((p) => ({ t: ms(p.t), medio: Number(p.preco) }));
  const resumo = `Curva de preço: ${amazon.length} leituras da Amazon e ${liga.length} da Liga`;
  return (
    <figure aria-label={resumo} className="space-y-2">
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart margin={{ left: 8, right: 8, top: 8, bottom: 8 }}>
            <CartesianGrid strokeOpacity={0.15} />
            <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]}
              tickFormatter={(t: number) => dataHora(new Date(t).toISOString())} stroke={cores.texto} fontSize={11} />
            <YAxis tickFormatter={(v: number) => reais(String(v))} stroke={cores.texto} fontSize={11} width={84} />
            <Tooltip labelFormatter={(t) => dataHora(new Date(Number(t)).toISOString())}
              formatter={(v) => reais(String(v))} />
            <Legend />
            {historico.faixas.map((f) => (
              <ReferenceArea key={f.id} x1={ms(f.inicio)} x2={ms(f.fim)} fill={cores.sucesso}
                fillOpacity={f.id === destaque ? 0.35 : 0.12} ifOverflow="extendDomain" />
            ))}
            <Line data={amazon} dataKey="amazon" name="Amazon" type="stepAfter" stroke={cores.primaria} dot={false} strokeWidth={2} />
            <Line data={liga} dataKey="liga" name="Liga (a partir de)" type="stepAfter" stroke={cores.secundaria} dot={false} />
            <Line data={medio} dataKey="medio" name="Liga (média)" type="stepAfter" stroke={cores.texto} strokeOpacity={0.5} dot={false} />
            <Line data={liga} dataKey="alvo" name="Preço alvo" type="stepAfter" stroke={cores.aviso} strokeDasharray="5 4" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="text-sm opacity-70">
        {amazon.length === 0 && <span>Ainda não há leituras suficientes para a curva. </span>}
        {liga.length === 0 && <span>sem preço da Liga no período</span>}
      </figcaption>
    </figure>
  );
}
```

(Se o teste de vazio procurar o texto exato "Ainda não há leituras suficientes para a curva", tirar o ponto final do `<span>` ou usar o mesmo texto nos dois lugares.)

- [ ] **Step 4: `web/src/paginas/Produto.tsx`:**

```tsx
// Histórico de um produto: curva Amazon × Liga com as oportunidades em faixas e a lista delas (recorrência).
import { useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { chamarApi, ErroApi } from "../api";
import { CurvaPreco } from "../componentes/CurvaPreco";
import { MotivoSelo } from "../componentes/MotivoSelo";
import { SeletorPeriodo } from "../componentes/SeletorPeriodo";
import { dataHora, duracao, pct, reais } from "../formato";
import { useSessao } from "../sessao";
import type { Historico, Periodo } from "../tipos";
import { NaoEncontrada } from "./NaoEncontrada";

export function Produto() {
  const { id } = useParams();
  const [busca] = useSearchParams();
  const destaque = busca.get("oportunidade") ? Number(busca.get("oportunidade")) : null;
  const { tratarErro } = useSessao();
  const [periodo, setPeriodo] = useState<Periodo>("30d");
  const [historico, setHistorico] = useState<Historico | null>(null);
  const [naoExiste, setNaoExiste] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    setErro(null);
    try {
      setHistorico(await chamarApi<Historico>(`/api/produtos/${id}/historico?periodo=${periodo}`));
    } catch (e) {
      if (e instanceof ErroApi && e.status === 404) setNaoExiste(true);
      else setErro(tratarErro(e));
    }
  }, [id, periodo, tratarErro]);

  useEffect(() => { void carregar(); }, [carregar]);

  if (naoExiste) return <NaoEncontrada />;
  const h = historico;
  return (
    <section className="space-y-6">
      {erro && (
        <div role="alert" className="alert alert-error">
          <span>{erro}</span>
          <button type="button" className="btn btn-sm" onClick={() => void carregar()}>Tentar de novo</button>
        </div>
      )}
      {h && (
        <>
          <div className="flex flex-wrap items-start gap-4">
            {h.produto.imagem_url && <img src={h.produto.imagem_url} alt="" className="h-24 w-24 rounded object-contain" />}
            <div className="flex-1 space-y-2">
              <h1 className="text-2xl font-bold">{h.produto.nome}</h1>
              <div className="flex flex-wrap gap-2">
                {h.produto.edicao && <span className="badge badge-ghost">{h.produto.edicao}</span>}
                <span className="badge badge-primary">{h.recorrencia_30d}ª oportunidade em 30 dias</span>
                {h.quase_la && <span className="badge badge-warning">quase lá</span>}
              </div>
              <div className="flex flex-wrap gap-2">
                <a className="btn btn-sm" href={h.produto.url_liga} target="_blank" rel="noreferrer">Ver na Liga</a>
                {h.anuncio && (
                  <a className="btn btn-primary btn-sm" href={h.anuncio.url} target="_blank" rel="noreferrer">Ver na Amazon</a>
                )}
              </div>
            </div>
            <SeletorPeriodo valor={periodo} aoMudar={setPeriodo} />
          </div>
          <CurvaPreco historico={h} destaque={destaque} />
          <section aria-labelledby="titulo-historico" className="space-y-3">
            <h2 id="titulo-historico" className="text-xl font-semibold">Oportunidades deste produto</h2>
            {h.oportunidades.length === 0 && <p className="opacity-70">Nenhuma oportunidade no período</p>}
            {h.oportunidades.length > 0 && (
              <div className="overflow-x-auto">
                <table className="table table-sm">
                  <thead>
                    <tr><th>Abriu</th><th>Durou</th><th>Alertas</th><th>Alerta</th><th>Menor</th><th>Desconto</th><th>Motivo</th></tr>
                  </thead>
                  <tbody>
                    {h.oportunidades.map((o) => (
                      <tr key={o.id} className={o.id === destaque ? "bg-base-200" : undefined}>
                        <td>{dataHora(o.aberta_em)}</td>
                        <td>{duracao(o.duracao_min)}</td>
                        <td>{o.alertas}</td>
                        <td>{reais(o.preco_alertado)}</td>
                        <td>{reais(o.menor_preco)}</td>
                        <td>{pct(o.desconto_pct)}</td>
                        <td><MotivoSelo motivo={o.motivo} aberta={o.aberta} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </section>
  );
}
```

A recorrência "Nª" com N = `recorrencia_30d` (o número de oportunidades do produto nos últimos 30 dias, contando a mais recente).

- [ ] **Step 5: rota** em `App.tsx`, irmã de `/`:

```tsx
        <Route
          path="/produtos/:id"
          element={
            <Exige permissao="ver_oportunidades">
              <Produto />
            </Exige>
          }
        />
```

- [ ] **Step 6:** `cd web && npm test && npm run build` — PASS.
- [ ] **Step 7:** commit `feat: product history page with price curve`.

---

### Task 9: Ponta a ponta, layout e documentação

**Files:**
- Modify: `tests/e2e/test_ponta_a_ponta.py`, `scripts/verificar_layout.py`
- Modify: `README.md` (seção do site novo), `docs/IMPLANTACOES.md` (seção nova no topo), `docs/PENDENCIAS.md`

- [ ] **Step 1: e2e.** Em `entrar()`, o heading esperado passa de "Área de negócio" para "Oportunidades" (e o mesmo em `test_grupo_so_entra_na_gestao_depois_de_liberado`). Na fixture `usuarios`, gravar um produto ativo com preço da Liga, um anúncio confirmado e uma oportunidade aberta (usar `fakes.criar_produto`, `fakes.criar_preco_liga`, `fakes.criar_anuncio(..., StatusCasamento.CONFIRMADO)` e `fakes_oportunidades.criar_oportunidade`) e acrescentar `oportunidade, preco_atual_amazon, preco_amazon, casamento, preco_atual_liga, anuncio_amazon, produto_liga` à lista `TABELAS` do `TRUNCATE`. Teste novo:

```python
def test_grupo_ve_oportunidade_e_abre_o_produto(servidores, usuarios, engine):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        try:
            pagina = navegador.new_context().new_page()
            erros_csp = []
            pagina.on("console", lambda m: erros_csp.append(m.text) if "Content Security Policy" in m.text else None)
            entrar(pagina, expect, engine, GRUPO, "(11) 90000-0002")
            expect(pagina.get_by_role("region", name="Ativas agora")).to_be_visible()
            pagina.get_by_role("link", name="Histórico do produto").first.click()
            expect(pagina.get_by_role("figure", name=re.compile("Curva de preço"))).to_be_visible()
            assert erros_csp == []
        finally:
            navegador.close()
```

(O `vite preview` não aplica a CSP do Caddy; o teste de CSP de verdade é o layout em produção do Step 2 e a conferência manual após o deploy. Mesmo assim o teste fica: pega erro de CSP se um dia o preview passar a mandá-la.)

- [ ] **Step 2: layout.** Em `scripts/verificar_layout.py`, depois de entrar, descobrir a primeira página de produto: abrir `/`, ler o `href` do primeiro link que começa com `/produtos/` e, se houver, acrescentá-lo a `TELAS_WEB` para esta execução (sem produto, seguir só com as fixas). Rodar o teste de layout do e2e (`TCG_E2E=1 uv run pytest -q tests/e2e`) com o produto da fixture.
- [ ] **Step 3: docs.**
  - `docs/IMPLANTACOES.md`, seção nova no topo "Oportunidades na área de negócio (2026-10-21)": backup de sempre; migração `f3b8d1c7a9e2` (piso da quase oportunidade, padrão 10%, e índice do `preco_amazon`, que leva alguns segundos com o histórico atual); subir tudo junto; conferir Configurações → Amazon → "Quase oportunidade a partir de (%)" e a tela `/` do site novo; a CSP do site passa a liberar imagens de `repositorio.sbrauble.com` e `m.media-amazon.com`.
  - `README.md`: na seção do site novo, a área de negócio passa a ter Oportunidades e Produto (o que cada uma mostra, em 3–4 linhas) e a permissão `ver_oportunidades`.
  - `docs/PENDENCIAS.md`: marcar B `[x]` com "merge `pendente`" e detalhe em "Concluídas" (telas, API, permissão, piso, índice); tirar o pré-requisito `consultas_catalogo` (feito na Tarefa 1); "Última revisão" atualizada.
- [ ] **Step 4:** suíte inteira: `uv run pytest -q`, `uv run ruff check`, `cd web && npm test && npm run build` — PASS.
- [ ] **Step 5:** commit `docs: opportunities in the business area (deploy notes, readme, pending list)`.
