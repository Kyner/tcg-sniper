# Casamento com IA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um serviço `casador` pede à OpenAI (texto + imagens) se cada anúncio pendente da Amazon é o mesmo produto da Liga sugerido, grava confiança e motivo, mostra a sugestão no admin e, com o automático ligado, confirma ou ignora sozinho; gasto travado por tetos configuráveis; comando de avaliação contra os casos já decididos.

**Architecture:** Pacote `tcg_sniper/ia` é o único que importa `openai`: um `Transporte` (OpenAI real ou falso nos testes) e a função `perguntar()` que confere o orçamento, chama, calcula o custo e registra cada chamada em `chamada_ia`. O pacote `tcg_sniper/casador` monta a pergunta, guarda `avaliacao_ia` e aplica o automático; roda como container próprio no molde do `notificador`. Os coletores passam a guardar a URL da imagem principal; o admin ganha a aba IA em Configurações, o card do casador em Serviços, o gasto no Dashboard e os selos da IA nos casamentos.

**Tech Stack:** Python 3.12, SQLAlchemy 2 + Alembic, Postgres 16, FastAPI + Jinja2 + DaisyUI 5, `openai` (SDK oficial, Responses API com structured outputs), `Pillow`, httpx, pytest + respx.

**Spec:** `docs/superpowers/specs/2026-10-16-casamento-ia-design.md`

## Global Constraints

- Só `src/tcg_sniper/ia/` importa `openai`. Nenhum teste chama a OpenAI de verdade (transporte falso ou respx).
- A chave vem de `OPENAI_API_KEY` no `.env` (`Config.openai_api_key`). Nunca vai para o banco, logs, mensagens de erro gravadas ou HTML; a tela mostra só "Chave configurada: sim/não".
- Padrões da `config_ia`: `ligado=false`, `modelo="gpt-5"`, `esforco="low"`, `preco_entrada_milhao_usd=1.25`, `preco_saida_milhao_usd=10.00`, `teto_dia_usd=2.00`, `teto_mes_usd=20.00`, `max_chamadas_dia=1000`, `intervalo_min=5`, `lote=20`, `automatico=false`, `confianca_confirmar=90`, `confianca_ignorar=90`.
- Imagens: até 512 px no lado maior, JPEG, base64, enviadas com `detail: "low"`. Falha de imagem nunca impede a pergunta (segue só com texto e marca `sem_imagem`).
- Orçamento: chamada só sai se gasto do dia < `teto_dia_usd`, gasto do mês < `teto_mes_usd` e chamadas do dia < `max_chamadas_dia`, com dia e mês no fuso de Configurações → Geral (`America/Sao_Paulo` em produção). Chamada com erro também conta.
- Decisão humana nunca é sobrescrita: o automático só age se o anúncio ainda está `pendente` com o mesmo `produto_id`, e nunca reaplica num par cuja avaliação já tem `aplicada_em` (o usuário desfez).
- Admin: só componentes do DaisyUI 5 e utilitários do Tailwind, classes literais (nunca concatenadas); toda tarefa que mexe em template regenera `src/tcg_sniper/admin/static/admin.css` com `uv run python scripts/gerar_css.py` e commita.
- Nomes, comentários e textos em português, como o resto do código.
- Testes com `DATABASE_URL_TESTE` apontando para o banco da lane: `uv run pytest -q` e `uv run ruff check .` verdes ao fim de cada tarefa.
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Busca da Amazon trazendo outra miniatura do mesmo anúncio a cada ciclo: a URL da imagem não pode mudar a cada busca, senão a assinatura muda e o anúncio é reavaliado (e cobrado) sem fim. Regra: a busca só preenche `imagem_url` vazia; a página do produto pode trocar. Teste na Task 3.
2. Usuário desfaz um casamento que a IA confirmou e depois o título do anúncio muda: a reavaliação não pode reaplicar o automático. Teste na Task 6.
3. Usuário confirma, ignora ou troca o produto do anúncio enquanto a chamada da IA está em andamento: nada muda no anúncio. Teste na Task 6.
4. Resposta da OpenAI com JSON válido mas fora do formato (confiança 150, campo faltando, motivo vazio): vira erro registrado, sem avaliação gravada, e o anúncio volta no próximo ciclo. Teste na Task 6.
5. Teto estourado no meio do lote: o ciclo para no anúncio seguinte, sem chamada extra, e a mensagem de "sem orçamento" sai uma vez só no dia (ou no mês). Teste na Task 6.

---

## Ondas (para execução paralela)

- Onda A: Task 1 (modelos, migração e repositório da IA).
- Onda B (em paralelo): Task 2 (pacote `ia`), Task 3 (imagens nos coletores), Task 4 (admin: Configurações, Serviços e Dashboard), Task 5 (admin: selos da IA nos casamentos).
- Onda C: Task 6 (serviço `casador`, CLI e compose) — depende das Tasks 1 e 2.
- Onda D: Task 7 (comando de avaliação e README) — depende da Task 6.
- Conflitos em `src/tcg_sniper/admin/static/admin.css` entre as Tasks 4 e 5 são esperados: na integração, rodar `uv run python scripts/gerar_css.py` e commitar o resultado. Conflitos em `src/tcg_sniper/admin/app.py` ficam em trechos diferentes (Task 4: Serviços/Configurações/Dashboard; Task 5: casamentos).

---

### Task 1: Modelos, migração e repositório da IA

**Files:**
- Modify: `src/tcg_sniper/db/models.py`
- Create: `src/tcg_sniper/db/migrations/versions/e7a4c1d9b3f2_ia.py`
- Create: `src/tcg_sniper/db/repositorio_ia.py`
- Modify: `src/tcg_sniper/db/repositorio.py` (`ID_COLETOR`, `solicitar_execucao`, `consumir_solicitacao` com `coletor`)
- Test: `tests/db/test_repositorio_ia.py` (novo); `tests/db/test_migracao.py` continua passando

**Interfaces:**
- Produces:
  - `models.COLETOR_CASADOR = "casador"`; `repositorio.ID_COLETOR[COLETOR_CASADOR] == 3`
  - `ProdutoLiga.imagem_url: str | None`, `AnuncioAmazon.imagem_url: str | None`
  - `models.ChamadaIA`, `models.AvaliacaoIA`, `models.ConfigIA`, `models.PADROES_CONFIG_IA`, `models.LIMITES_CONFIG_IA`, `models.ESFORCOS_IA`
  - `repositorio.solicitar_execucao(s, agora, coletor=COLETOR_LIGA)`, `repositorio.consumir_solicitacao(s, agora, coletor=COLETOR_LIGA)`
  - `repositorio_ia.obter_config_ia(s) -> ConfigIA`
  - `repositorio_ia.salvar_config_ia(s, valores: Mapping[str, object], agora) -> None`
  - `repositorio_ia.registrar_chamada(s, *, em, finalidade, modelo, tokens_entrada, tokens_saida, custo_usd, ok, erro) -> ChamadaIA`
  - `repositorio_ia.Gasto(dia_usd: Decimal, mes_usd: Decimal, chamadas_dia: int)`, `repositorio_ia.gasto(s, agora, zona) -> Gasto`
  - `repositorio_ia.ParPendente(anuncio, produto, avaliacao, preco_liga, preco_amazon)`, `repositorio_ia.pares_pendentes(s) -> list[ParPendente]`
  - `repositorio_ia.gravar_avaliacao(s, *, anuncio_id, produto_id, mesmo_produto, confianca, motivo, modelo, assinatura, sem_imagem, chamada_id, agora) -> AvaliacaoIA`
  - `repositorio_ia.avaliacoes_dos_pares(s, pares: Sequence[tuple[int, int]]) -> dict[tuple[int, int], AvaliacaoIA]`
  - `repositorio_ia.ParDecidido(anuncio, produto, confirmado: bool, preco_liga, preco_amazon)`, `repositorio_ia.pares_decididos(s, limite: int | None) -> list[ParDecidido]`

- [ ] **Step 1: Testes (falham)**

Create `tests/db/test_repositorio_ia.py`:

```python
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto

from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import COLETOR_CASADOR, PADROES_CONFIG_IA, EstadoColetorTipo, StatusCasamento

SP = ZoneInfo("America/Sao_Paulo")


def chamada(s, em, custo="0.01", ok=True):
    return repo_ia.registrar_chamada(
        s, em=em, finalidade="casamento", modelo="gpt-5", tokens_entrada=100, tokens_saida=10,
        custo_usd=Decimal(custo), ok=ok, erro=None if ok else "falhou",
    )


def test_config_ia_nasce_com_os_padroes(s):
    cfg = repo_ia.obter_config_ia(s)
    for campo, valor in PADROES_CONFIG_IA.items():
        assert getattr(cfg, campo) == valor
    assert cfg.ligado is False and cfg.automatico is False


def test_salvar_config_ia(s):
    repo_ia.obter_config_ia(s)
    repo_ia.salvar_config_ia(s, {"modelo": "gpt-5-mini", "teto_dia_usd": Decimal("0.50")}, T0)
    cfg = repo_ia.obter_config_ia(s)
    assert cfg.modelo == "gpt-5-mini" and cfg.teto_dia_usd == Decimal("0.50")


def test_gasto_por_dia_e_mes_no_fuso(s):
    # T0 = 2026-10-13 13:00 UTC = 10:00 em São Paulo
    chamada(s, T0, "0.10")
    chamada(s, T0 - timedelta(hours=12), "0.20")  # 2026-10-12 22:00 em SP: outro dia, mesmo mês
    chamada(s, T0 - timedelta(days=20), "1.00")  # setembro
    chamada(s, T0, "0.05", ok=False)
    g = repo_ia.gasto(s, T0, SP)
    assert g.dia_usd == Decimal("0.15")
    assert g.mes_usd == Decimal("0.35")
    assert g.chamadas_dia == 2


def test_gasto_vazio(s):
    assert repo_ia.gasto(s, T0, SP) == repo_ia.Gasto(Decimal("0"), Decimal("0"), 0)


def test_virada_do_dia_em_sao_paulo(s):
    # 02:59 UTC de 13/10 = 23:59 de 12/10 em SP; 03:00 UTC = 00:00 de 13/10
    chamada(s, T0.replace(hour=2, minute=59), "0.30")
    assert repo_ia.gasto(s, T0.replace(hour=3, minute=0), SP).dia_usd == Decimal("0")
    assert repo_ia.gasto(s, T0.replace(hour=2, minute=59, second=30), SP).dia_usd == Decimal("0.30")


def test_pares_pendentes_com_avaliacao_e_precos(s):
    p = criar_produto(s, "p1", nome="Caixa X")
    inativo = criar_produto(s, "p2", ativo=False, nome="Caixa Y")
    criar_preco_liga(s, p, Decimal("500"))
    a1 = criar_anuncio(s, "B1", produto=p, agora=T0 - timedelta(days=1))
    a2 = criar_anuncio(s, "B2", produto=p, agora=T0)
    a3 = criar_anuncio(s, "B3", produto=inativo, agora=T0 + timedelta(hours=1))
    criar_anuncio(s, "B4", produto=p, status=StatusCasamento.CONFIRMADO)
    criar_anuncio(s, "B5", produto=None)
    av = repo_ia.gravar_avaliacao(
        s, anuncio_id=a1.id, produto_id=p.id, mesmo_produto=True, confianca=95, motivo="igual",
        modelo="gpt-5", assinatura="x", sem_imagem=False, chamada_id=None, agora=T0,
    )
    pares = repo_ia.pares_pendentes(s)
    assert [par.anuncio.id for par in pares] == [a2.id, a1.id, a3.id]  # ativos primeiro, mais recentes primeiro
    assert pares[1].avaliacao.id == av.id and pares[0].avaliacao is None
    assert pares[0].preco_liga == Decimal("500") and pares[0].preco_amazon is None


def test_gravar_avaliacao_substitui_e_preserva_aplicada_em(s):
    p = criar_produto(s, "p1")
    a = criar_anuncio(s, "B1", produto=p)
    kw = dict(anuncio_id=a.id, produto_id=p.id, modelo="gpt-5", sem_imagem=False, chamada_id=None)
    av = repo_ia.gravar_avaliacao(s, mesmo_produto=True, confianca=95, motivo="m1", assinatura="a1", agora=T0, **kw)
    av.aplicada_em = T0
    s.flush()
    av2 = repo_ia.gravar_avaliacao(
        s, mesmo_produto=False, confianca=60, motivo="m2", assinatura="a2", agora=T0 + timedelta(hours=1), **kw
    )
    assert av2.id == av.id
    assert (av2.mesmo_produto, av2.confianca, av2.motivo, av2.assinatura) == (False, 60, "m2", "a2")
    assert av2.aplicada_em == T0


def test_avaliacoes_dos_pares(s):
    p, q = criar_produto(s, "p1"), criar_produto(s, "p2")
    a = criar_anuncio(s, "B1", produto=p)
    repo_ia.gravar_avaliacao(
        s, anuncio_id=a.id, produto_id=q.id, mesmo_produto=True, confianca=95, motivo="m", modelo="gpt-5",
        assinatura="x", sem_imagem=False, chamada_id=None, agora=T0,
    )
    assert repo_ia.avaliacoes_dos_pares(s, [(a.id, p.id)]) == {}
    assert set(repo_ia.avaliacoes_dos_pares(s, [(a.id, q.id)])) == {(a.id, q.id)}
    assert repo_ia.avaliacoes_dos_pares(s, []) == {}


def test_pares_decididos_sem_os_aplicados_pela_ia(s):
    p = criar_produto(s, "p1")
    c = criar_anuncio(s, "B1", produto=p, status=StatusCasamento.CONFIRMADO)
    i = criar_anuncio(s, "B2", produto=p, status=StatusCasamento.IGNORADO)
    pela_ia = criar_anuncio(s, "B3", produto=p, status=StatusCasamento.CONFIRMADO)
    criar_anuncio(s, "B4", produto=p)  # pendente
    av = repo_ia.gravar_avaliacao(
        s, anuncio_id=pela_ia.id, produto_id=p.id, mesmo_produto=True, confianca=99, motivo="m", modelo="gpt-5",
        assinatura="x", sem_imagem=False, chamada_id=None, agora=T0,
    )
    av.aplicada_em = T0
    s.flush()
    decididos = repo_ia.pares_decididos(s, None)
    assert {(d.anuncio.id, d.confirmado) for d in decididos} == {(c.id, True), (i.id, False)}
    assert len(repo_ia.pares_decididos(s, 1)) == 1


def test_estado_do_casador_e_solicitacao(s):
    estado = repo.obter_estado(s, T0, COLETOR_CASADOR)
    assert estado.id == 3 and estado.estado is EstadoColetorTipo.ATIVO
    repo.solicitar_execucao(s, T0, COLETOR_CASADOR)
    assert repo.consumir_solicitacao(s, T0) is False  # a da Liga não foi pedida
    assert repo.consumir_solicitacao(s, T0, COLETOR_CASADOR) is True
    assert repo.consumir_solicitacao(s, T0, COLETOR_CASADOR) is False
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/db/test_repositorio_ia.py -q`
Expected: FAIL (ImportError: `repositorio_ia`).

- [ ] **Step 3: Modelos**

Em `src/tcg_sniper/db/models.py`:

- Junto de `COLETOR_LIGA`/`COLETOR_AMAZON`: `COLETOR_CASADOR = "casador"`.
- Garantir `Numeric` e `UniqueConstraint`/`Index`/`ForeignKey` no import de `sqlalchemy` (alguns já existem).
- `ProdutoLiga`: depois de `nome_en`, `imagem_url: Mapped[str | None] = mapped_column(Text)`.
- `AnuncioAmazon`: depois de `variacao`, com comentário: `# Imagem principal: a busca só preenche quando vazia; a página do produto pode trocar.` e `imagem_url: Mapped[str | None] = mapped_column(Text)`.
- `EstadoColetor`: docstring "id 1 = Liga, id 2 = Amazon, id 3 = casador"; a check vira `CheckConstraint("id IN (1, 2, 3)", name="ck_estado_coletor_linhas")`.
- No fim do arquivo:

```python
ESFORCOS_IA = ("minimal", "low", "medium", "high")

LIMITES_CONFIG_IA: dict[str, tuple[int, int]] = {
    "max_chamadas_dia": (0, 100000),
    "intervalo_min": (1, 1440),
    "lote": (1, 500),
    "confianca_confirmar": (0, 100),
    "confianca_ignorar": (0, 100),
}

PADROES_CONFIG_IA: dict[str, object] = {
    "ligado": False,
    "modelo": "gpt-5",
    "esforco": "low",
    "preco_entrada_milhao_usd": Decimal("1.25"),
    "preco_saida_milhao_usd": Decimal("10.00"),
    "teto_dia_usd": Decimal("2.00"),
    "teto_mes_usd": Decimal("20.00"),
    "max_chamadas_dia": 1000,
    "intervalo_min": 5,
    "lote": 20,
    "automatico": False,
    "confianca_confirmar": 90,
    "confianca_ignorar": 90,
}


class ConfigIA(Base):
    """Configuração da IA (casador): uma linha, editável no admin. A chave fica no .env (OPENAI_API_KEY)."""

    __tablename__ = "config_ia"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_config_ia_linha_unica"),
        CheckConstraint("modelo <> ''", name="ck_config_ia_modelo"),
        CheckConstraint("esforco IN ('minimal', 'low', 'medium', 'high')", name="ck_config_ia_esforco"),
        CheckConstraint(
            "preco_entrada_milhao_usd >= 0 AND preco_saida_milhao_usd >= 0 AND teto_dia_usd >= 0 AND teto_mes_usd >= 0",
            name="ck_config_ia_valores",
        ),
        *(
            CheckConstraint(f"{campo} BETWEEN {minimo} AND {maximo}", name=f"ck_config_ia_{campo}")
            for campo, (minimo, maximo) in LIMITES_CONFIG_IA.items()
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    ligado: Mapped[bool] = mapped_column(Boolean)
    modelo: Mapped[str] = mapped_column(Text)
    esforco: Mapped[str] = mapped_column(Text)
    preco_entrada_milhao_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    preco_saida_milhao_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    teto_dia_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    teto_mes_usd: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    max_chamadas_dia: Mapped[int] = mapped_column(Integer)
    intervalo_min: Mapped[int] = mapped_column(Integer)
    lote: Mapped[int] = mapped_column(Integer)
    automatico: Mapped[bool] = mapped_column(Boolean)
    confianca_confirmar: Mapped[int] = mapped_column(Integer)
    confianca_ignorar: Mapped[int] = mapped_column(Integer)
    atualizado_em: Mapped[datetime] = mapped_column(DATA)


class ChamadaIA(Base):
    """Cada chamada à OpenAI (ok ou erro), com tokens e custo: base do orçamento e do gasto no admin."""

    __tablename__ = "chamada_ia"
    __table_args__ = (Index("ix_chamada_ia_em", "em"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    em: Mapped[datetime] = mapped_column(DATA)
    finalidade: Mapped[str] = mapped_column(Text)  # "casamento" | "avaliacao"
    modelo: Mapped[str] = mapped_column(Text)
    tokens_entrada: Mapped[int] = mapped_column(Integer)
    tokens_saida: Mapped[int] = mapped_column(Integer)
    custo_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    ok: Mapped[bool] = mapped_column(Boolean)
    erro: Mapped[str | None] = mapped_column(Text)


class AvaliacaoIA(Base):
    """Veredito da IA para um par (anúncio, produto da Liga). `assinatura` = hash dos dados enviados:
    mudou, reavalia. `aplicada_em` preenchida quando o automático confirmou ou ignorou o anúncio
    (fica mesmo se o usuário desfizer, para o automático não reaplicar)."""

    __tablename__ = "avaliacao_ia"
    __table_args__ = (
        UniqueConstraint("anuncio_id", "produto_id", name="uq_avaliacao_ia_par"),
        CheckConstraint("confianca BETWEEN 0 AND 100", name="ck_avaliacao_ia_confianca"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    anuncio_id: Mapped[int] = mapped_column(ForeignKey("anuncio_amazon.id"))
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"))
    mesmo_produto: Mapped[bool] = mapped_column(Boolean)
    confianca: Mapped[int] = mapped_column(Integer)
    motivo: Mapped[str] = mapped_column(Text)
    modelo: Mapped[str] = mapped_column(Text)
    assinatura: Mapped[str] = mapped_column(Text)
    sem_imagem: Mapped[bool] = mapped_column(Boolean)
    avaliado_em: Mapped[datetime] = mapped_column(DATA)
    aplicada_em: Mapped[datetime | None] = mapped_column(DATA)
    chamada_id: Mapped[int | None] = mapped_column(ForeignKey("chamada_ia.id"))
```

- [ ] **Step 4: Migração**

Create `src/tcg_sniper/db/migrations/versions/e7a4c1d9b3f2_ia.py` (mesmo cabeçalho dos arquivos vizinhos; `down_revision = "d5e9b2c4a7f1"`). Docstring: `casamento com IA: imagens, chamadas, avaliações, configuração e estado do casador`.

```python
def upgrade() -> None:
    op.add_column("produto_liga", sa.Column("imagem_url", sa.Text(), nullable=True))
    op.add_column("anuncio_amazon", sa.Column("imagem_url", sa.Text(), nullable=True))
    op.drop_constraint("ck_estado_coletor_linhas", "estado_coletor", type_="check")
    op.create_check_constraint("ck_estado_coletor_linhas", "estado_coletor", "id IN (1, 2, 3)")
    op.create_table(
        "chamada_ia",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalidade", sa.Text(), nullable=False),
        sa.Column("modelo", sa.Text(), nullable=False),
        sa.Column("tokens_entrada", sa.Integer(), nullable=False),
        sa.Column("tokens_saida", sa.Integer(), nullable=False),
        sa.Column("custo_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("erro", sa.Text(), nullable=True),
    )
    op.create_index("ix_chamada_ia_em", "chamada_ia", ["em"])
    op.create_table(
        "avaliacao_ia",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("anuncio_id", sa.Integer(), sa.ForeignKey("anuncio_amazon.id"), nullable=False),
        sa.Column("produto_id", sa.Integer(), sa.ForeignKey("produto_liga.id"), nullable=False),
        sa.Column("mesmo_produto", sa.Boolean(), nullable=False),
        sa.Column("confianca", sa.Integer(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("modelo", sa.Text(), nullable=False),
        sa.Column("assinatura", sa.Text(), nullable=False),
        sa.Column("sem_imagem", sa.Boolean(), nullable=False),
        sa.Column("avaliado_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("aplicada_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chamada_id", sa.Integer(), sa.ForeignKey("chamada_ia.id"), nullable=True),
        sa.UniqueConstraint("anuncio_id", "produto_id", name="uq_avaliacao_ia_par"),
        sa.CheckConstraint("confianca BETWEEN 0 AND 100", name="ck_avaliacao_ia_confianca"),
    )
    op.create_table(
        "config_ia",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("ligado", sa.Boolean(), nullable=False),
        sa.Column("modelo", sa.Text(), nullable=False),
        sa.Column("esforco", sa.Text(), nullable=False),
        sa.Column("preco_entrada_milhao_usd", sa.Numeric(10, 4), nullable=False),
        sa.Column("preco_saida_milhao_usd", sa.Numeric(10, 4), nullable=False),
        sa.Column("teto_dia_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("teto_mes_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("max_chamadas_dia", sa.Integer(), nullable=False),
        sa.Column("intervalo_min", sa.Integer(), nullable=False),
        sa.Column("lote", sa.Integer(), nullable=False),
        sa.Column("automatico", sa.Boolean(), nullable=False),
        sa.Column("confianca_confirmar", sa.Integer(), nullable=False),
        sa.Column("confianca_ignorar", sa.Integer(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_config_ia_linha_unica"),
        sa.CheckConstraint("modelo <> ''", name="ck_config_ia_modelo"),
        sa.CheckConstraint("esforco IN ('minimal', 'low', 'medium', 'high')", name="ck_config_ia_esforco"),
        sa.CheckConstraint(
            "preco_entrada_milhao_usd >= 0 AND preco_saida_milhao_usd >= 0 AND teto_dia_usd >= 0 AND teto_mes_usd >= 0",
            name="ck_config_ia_valores",
        ),
        sa.CheckConstraint("max_chamadas_dia BETWEEN 0 AND 100000", name="ck_config_ia_max_chamadas_dia"),
        sa.CheckConstraint("intervalo_min BETWEEN 1 AND 1440", name="ck_config_ia_intervalo_min"),
        sa.CheckConstraint("lote BETWEEN 1 AND 500", name="ck_config_ia_lote"),
        sa.CheckConstraint("confianca_confirmar BETWEEN 0 AND 100", name="ck_config_ia_confianca_confirmar"),
        sa.CheckConstraint("confianca_ignorar BETWEEN 0 AND 100", name="ck_config_ia_confianca_ignorar"),
    )


def downgrade() -> None:
    op.drop_table("config_ia")
    op.drop_table("avaliacao_ia")
    op.drop_index("ix_chamada_ia_em", table_name="chamada_ia")
    op.drop_table("chamada_ia")
    op.execute("DELETE FROM estado_coletor WHERE id = 3")
    op.drop_constraint("ck_estado_coletor_linhas", "estado_coletor", type_="check")
    op.create_check_constraint("ck_estado_coletor_linhas", "estado_coletor", "id IN (1, 2)")
    op.drop_column("anuncio_amazon", "imagem_url")
    op.drop_column("produto_liga", "imagem_url")
```

A linha da `config_ia` nasce na primeira leitura (`obter_config_ia`), não na migração.

- [ ] **Step 5: Repositório**

Em `src/tcg_sniper/db/repositorio.py`: importar `COLETOR_CASADOR`; `ID_COLETOR = {COLETOR_LIGA: 1, COLETOR_AMAZON: 2, COLETOR_CASADOR: 3}`; `solicitar_execucao(s, agora, coletor: str = COLETOR_LIGA)` e `consumir_solicitacao(s, agora, coletor: str = COLETOR_LIGA)` passando `coletor` para `obter_estado`.

Create `src/tcg_sniper/db/repositorio_ia.py`:

```python
"""Tabelas da IA: configuração, registro de chamadas (orçamento) e avaliações de casamento."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tcg_sniper.db.models import (
    PADROES_CONFIG_IA,
    AnuncioAmazon,
    AvaliacaoIA,
    ChamadaIA,
    ConfigIA,
    PrecoAtualAmazon,
    PrecoAtualLiga,
    ProdutoLiga,
    StatusCasamento,
)
from tcg_sniper.db.repositorio import agora_utc


def obter_config_ia(s: Session, agora: datetime | None = None) -> ConfigIA:
    s.execute(
        pg_insert(ConfigIA)
        .values(id=1, **PADROES_CONFIG_IA, atualizado_em=agora or agora_utc())
        .on_conflict_do_nothing(index_elements=[ConfigIA.id])
    )
    return s.get(ConfigIA, 1, populate_existing=True)


def salvar_config_ia(s: Session, valores: Mapping[str, object], agora: datetime) -> None:
    obter_config_ia(s, agora)
    s.execute(update(ConfigIA).where(ConfigIA.id == 1).values(**valores, atualizado_em=agora))
    s.flush()


def registrar_chamada(
    s: Session,
    *,
    em: datetime,
    finalidade: str,
    modelo: str,
    tokens_entrada: int,
    tokens_saida: int,
    custo_usd: Decimal,
    ok: bool,
    erro: str | None,
) -> ChamadaIA:
    chamada = ChamadaIA(
        em=em, finalidade=finalidade, modelo=modelo, tokens_entrada=tokens_entrada,
        tokens_saida=tokens_saida, custo_usd=custo_usd, ok=ok, erro=erro,
    )
    s.add(chamada)
    s.flush()
    return chamada


@dataclass(frozen=True)
class Gasto:
    dia_usd: Decimal
    mes_usd: Decimal
    chamadas_dia: int


def gasto(s: Session, agora: datetime, zona: ZoneInfo) -> Gasto:
    """Gasto e chamadas desde o início do dia e do mês, no fuso `zona`."""
    local = agora.astimezone(zona)
    inicio_dia = local.replace(hour=0, minute=0, second=0, microsecond=0)
    inicio_mes = inicio_dia.replace(day=1)
    dia, chamadas = s.execute(
        select(func.coalesce(func.sum(ChamadaIA.custo_usd), 0), func.count()).where(ChamadaIA.em >= inicio_dia)
    ).one()
    mes = s.scalar(select(func.coalesce(func.sum(ChamadaIA.custo_usd), 0)).where(ChamadaIA.em >= inicio_mes))
    return Gasto(Decimal(dia), Decimal(mes), chamadas)


@dataclass(frozen=True)
class ParPendente:
    anuncio: AnuncioAmazon
    produto: ProdutoLiga
    avaliacao: AvaliacaoIA | None
    preco_liga: Decimal | None
    preco_amazon: Decimal | None


def pares_pendentes(s: Session) -> list[ParPendente]:
    """Anúncios pendentes com produto sugerido, com a avaliação desse par (se houver) e os preços atuais.
    Produtos ativos primeiro; depois os vistos mais recentemente."""
    consulta = (
        select(AnuncioAmazon, ProdutoLiga, AvaliacaoIA, PrecoAtualLiga.preco_a_partir, PrecoAtualAmazon.preco)
        .join(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .outerjoin(
            AvaliacaoIA,
            and_(AvaliacaoIA.anuncio_id == AnuncioAmazon.id, AvaliacaoIA.produto_id == AnuncioAmazon.produto_id),
        )
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .where(AnuncioAmazon.status_casamento == StatusCasamento.PENDENTE)
        .order_by(ProdutoLiga.ativo.desc(), AnuncioAmazon.visto_ultimo_em.desc(), AnuncioAmazon.id)
    )
    return [ParPendente(*linha) for linha in s.execute(consulta)]


def gravar_avaliacao(
    s: Session,
    *,
    anuncio_id: int,
    produto_id: int,
    mesmo_produto: bool,
    confianca: int,
    motivo: str,
    modelo: str,
    assinatura: str,
    sem_imagem: bool,
    chamada_id: int | None,
    agora: datetime,
) -> AvaliacaoIA:
    """Cria ou substitui a avaliação do par. `aplicada_em` nunca é apagada aqui."""
    valores = dict(
        mesmo_produto=mesmo_produto, confianca=confianca, motivo=motivo, modelo=modelo,
        assinatura=assinatura, sem_imagem=sem_imagem, chamada_id=chamada_id, avaliado_em=agora,
    )
    stmt = pg_insert(AvaliacaoIA).values(anuncio_id=anuncio_id, produto_id=produto_id, **valores)
    stmt = stmt.on_conflict_do_update(constraint="uq_avaliacao_ia_par", set_=valores).returning(AvaliacaoIA.id)
    avaliacao_id = s.execute(stmt).scalar_one()
    return s.get(AvaliacaoIA, avaliacao_id, populate_existing=True)


def avaliacoes_dos_pares(s: Session, pares: Sequence[tuple[int, int]]) -> dict[tuple[int, int], AvaliacaoIA]:
    if not pares:
        return {}
    consulta = select(AvaliacaoIA).where(tuple_(AvaliacaoIA.anuncio_id, AvaliacaoIA.produto_id).in_(list(pares)))
    return {(a.anuncio_id, a.produto_id): a for a in s.scalars(consulta)}


@dataclass(frozen=True)
class ParDecidido:
    anuncio: AnuncioAmazon
    produto: ProdutoLiga
    confirmado: bool
    preco_liga: Decimal | None
    preco_amazon: Decimal | None


def pares_decididos(s: Session, limite: int | None) -> list[ParDecidido]:
    """Anúncios confirmados ou ignorados pelo usuário (não pelo automático), para a avaliação."""
    aplicada = (
        select(AvaliacaoIA.id)
        .where(
            AvaliacaoIA.anuncio_id == AnuncioAmazon.id,
            AvaliacaoIA.produto_id == AnuncioAmazon.produto_id,
            AvaliacaoIA.aplicada_em.is_not(None),
        )
        .exists()
    )
    consulta = (
        select(AnuncioAmazon, ProdutoLiga, PrecoAtualLiga.preco_a_partir, PrecoAtualAmazon.preco)
        .join(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .where(
            AnuncioAmazon.status_casamento.in_([StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO]),
            ~aplicada,
        )
        .order_by(AnuncioAmazon.id)
        .limit(limite)
    )
    return [
        ParDecidido(anuncio, produto, anuncio.status_casamento is StatusCasamento.CONFIRMADO, liga, amazon)
        for anuncio, produto, liga, amazon in s.execute(consulta)
    ]
```

(`repositorio` não importa `repositorio_ia`; o import de `agora_utc` no topo não cria ciclo.)

- [ ] **Step 6: Rodar**

Run: `uv run pytest tests/db -q && uv run pytest -q && uv run ruff check .`
Expected: PASS (inclui `test_migracao_igual_aos_modelos`).

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/db tests/db/test_repositorio_ia.py
git commit -m "feat: tables and repository for AI matching (config, calls, evaluations, casador state)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Pacote `ia` (transporte OpenAI, orçamento, imagens, `perguntar`)

**Files:**
- Modify: `pyproject.toml` (dependências `openai>=1.99`, `pillow>=11.0`; `uv add openai pillow` atualiza o `uv.lock`)
- Modify: `src/tcg_sniper/config.py` (`openai_api_key: str | None = None`)
- Create: `src/tcg_sniper/ia/__init__.py`, `src/tcg_sniper/ia/modelos.py`, `src/tcg_sniper/ia/transporte_openai.py`, `src/tcg_sniper/ia/orcamento.py`, `src/tcg_sniper/ia/imagens.py`, `src/tcg_sniper/ia/cliente.py`
- Test: `tests/ia/test_orcamento.py`, `tests/ia/test_imagens.py`, `tests/ia/test_cliente.py`, `tests/ia/test_transporte_openai.py`; `tests/fakes.py` (`TransporteFake`)

**Interfaces:**
- Consumes (Task 1): `repositorio_ia.obter_config_ia`, `repositorio_ia.registrar_chamada`, `repositorio_ia.gasto`, `models.ConfigIA`.
- Produces:
  - `ia.modelos.Pedido(modelo: str, esforco: str, instrucoes: str, texto: str, imagens: tuple[str, ...], nome_formato: str, formato: dict)` — `imagens` são JPEG em base64 (sem prefixo `data:`)
  - `ia.modelos.Bruta(texto: str, tokens_entrada: int, tokens_saida: int)`
  - `ia.modelos.Transporte` (Protocol): `enviar(self, pedido: Pedido) -> Bruta`
  - `ia.modelos.RespostaIA(dados: dict, modelo: str, tokens_entrada: int, tokens_saida: int, custo_usd: Decimal, chamada_id: int)`
  - Exceções: `ia.modelos.ErroIA(Exception)`, `ia.modelos.ChaveInvalida(ErroIA)`, `ia.modelos.SemOrcamento(ErroIA)`
  - `ia.transporte_openai.TransporteOpenAI(chave: str, timeout_s: float = 60, max_retries: int = 3, base_url: str | None = None)`
  - `ia.orcamento.motivo_sem_orcamento(cfg: ConfigIA, g: Gasto) -> str | None`
  - `ia.imagens.preparar(cliente: httpx.Client, url: str | None) -> str | None`
  - `ia.cliente.perguntar(sessoes, transporte, *, finalidade: str, instrucoes: str, texto: str, imagens: Sequence[str], nome_formato: str, formato: dict, zona: ZoneInfo, modelo: str | None = None, relogio=agora_utc) -> RespostaIA`
  - `ia.cliente.custo(tokens_entrada, tokens_saida, cfg) -> Decimal`
  - `tests/fakes.TransporteFake(respostas: list[Bruta | Exception])` com `.pedidos: list[Pedido]`

- [ ] **Step 1: Dependências e Config**

Run: `uv add "openai>=1.99" "pillow>=11.0"`. Em `Config` (depois de `whatsapp_grupo_oportunidades`): `openai_api_key: str | None = None`.

- [ ] **Step 2: Testes (falham)**

Em `tests/fakes.py`:

```python
class TransporteFake:
    """Transporte da IA para testes: devolve (ou lança) as respostas na ordem e guarda os pedidos."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.pedidos = []

    def enviar(self, pedido):
        self.pedidos.append(pedido)
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta
```

Create `tests/ia/test_orcamento.py`:

```python
from decimal import Decimal

from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.ia.orcamento import motivo_sem_orcamento


def test_orcamento(s):
    cfg = repo_ia.obter_config_ia(s)  # teto dia 2.00, mês 20.00, 1000 chamadas
    G = repo_ia.Gasto
    assert motivo_sem_orcamento(cfg, G(Decimal("1.99"), Decimal("19.99"), 999)) is None
    assert "diário" in motivo_sem_orcamento(cfg, G(Decimal("2.00"), Decimal("2"), 1))
    assert "mensal" in motivo_sem_orcamento(cfg, G(Decimal("0"), Decimal("20.00"), 1))
    assert "chamadas" in motivo_sem_orcamento(cfg, G(Decimal("0"), Decimal("0"), 1000))


def test_teto_zero_bloqueia_tudo(s):
    cfg = repo_ia.obter_config_ia(s)
    cfg.teto_dia_usd = Decimal("0")
    assert motivo_sem_orcamento(cfg, repo_ia.Gasto(Decimal("0"), Decimal("0"), 0)) is not None
```

Create `tests/ia/test_imagens.py`:

```python
import base64
import io

import httpx
import respx
from PIL import Image

from tcg_sniper.ia.imagens import MAX_BYTES, preparar


def png(largura, altura):
    saida = io.BytesIO()
    Image.new("RGBA", (largura, altura), (255, 0, 0, 128)).save(saida, "PNG")
    return saida.getvalue()


@respx.mock
def test_reduz_e_converte_para_jpeg():
    respx.get("https://img.test/a.png").mock(return_value=httpx.Response(200, content=png(1200, 600)))
    with httpx.Client() as c:
        b64 = preparar(c, "https://img.test/a.png")
    imagem = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert imagem.format == "JPEG" and max(imagem.size) == 512 and imagem.size == (512, 256)


@respx.mock
def test_imagem_pequena_nao_aumenta():
    respx.get("https://img.test/p.png").mock(return_value=httpx.Response(200, content=png(100, 80)))
    with httpx.Client() as c:
        imagem = Image.open(io.BytesIO(base64.b64decode(preparar(c, "https://img.test/p.png"))))
    assert imagem.size == (100, 80)


@respx.mock
def test_falhas_viram_none():
    respx.get("https://img.test/404").mock(return_value=httpx.Response(404))
    respx.get("https://img.test/lixo").mock(return_value=httpx.Response(200, content=b"nao e imagem"))
    respx.get("https://img.test/grande").mock(return_value=httpx.Response(200, content=b"0" * (MAX_BYTES + 1)))
    respx.get("https://img.test/rede").mock(side_effect=httpx.ConnectError("caiu"))
    with httpx.Client() as c:
        for url in ("https://img.test/404", "https://img.test/lixo", "https://img.test/grande", "https://img.test/rede"):
            assert preparar(c, url) is None
        assert preparar(c, None) is None
        assert preparar(c, "data:image/gif;base64,R0lGOD") is None
```

Create `tests/ia/test_cliente.py`:

```python
import json
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, TransporteFake
from sqlalchemy import select

from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import ChamadaIA
from tcg_sniper.ia.cliente import custo, perguntar
from tcg_sniper.ia.modelos import Bruta, ChaveInvalida, ErroIA, SemOrcamento

SP = ZoneInfo("America/Sao_Paulo")
FORMATO = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}


def chamar(sessoes, transporte, **extra):
    return perguntar(
        sessoes, transporte, finalidade="casamento", instrucoes="inst", texto="txt", imagens=["AAA"],
        nome_formato="teste", formato=FORMATO, zona=SP, relogio=lambda: T0, **extra,
    )


def chamadas(sessoes):
    with sessoes() as s:
        return list(s.scalars(select(ChamadaIA).order_by(ChamadaIA.id)))


def test_custo(s):
    cfg = repo_ia.obter_config_ia(s)  # 1.25 / 10.00 por milhão
    assert custo(1000, 100, cfg) == Decimal("0.002250")


def test_sucesso_registra_e_devolve(sessoes):
    t = TransporteFake([Bruta(json.dumps({"ok": True}), 1000, 100)])
    r = chamar(sessoes, t)
    assert r.dados == {"ok": True} and r.custo_usd == Decimal("0.002250") and r.modelo == "gpt-5"
    pedido = t.pedidos[0]
    assert (pedido.modelo, pedido.esforco, pedido.imagens, pedido.formato) == ("gpt-5", "low", ("AAA",), FORMATO)
    [c] = chamadas(sessoes)
    assert c.ok and c.id == r.chamada_id and c.finalidade == "casamento" and c.tokens_entrada == 1000


def test_modelo_sobrescrito(sessoes):
    t = TransporteFake([Bruta('{"ok": true}', 10, 1)])
    assert chamar(sessoes, t, modelo="gpt-5-mini").modelo == "gpt-5-mini"
    assert t.pedidos[0].modelo == "gpt-5-mini"


def test_json_invalido_vira_erro_registrado(sessoes):
    t = TransporteFake([Bruta("não é json", 50, 5)])
    with pytest.raises(ErroIA):
        chamar(sessoes, t)
    [c] = chamadas(sessoes)
    assert not c.ok and c.tokens_entrada == 50 and c.custo_usd > 0 and "JSON" in c.erro


@pytest.mark.parametrize("erro", [ChaveInvalida("chave recusada pela OpenAI (401)"), ErroIA("OpenAI 500")])
def test_erro_do_transporte_registrado_e_relancado(sessoes, erro):
    t = TransporteFake([erro])
    with pytest.raises(type(erro)):
        chamar(sessoes, t)
    [c] = chamadas(sessoes)
    assert not c.ok and c.erro == str(erro) and c.custo_usd == 0


def test_sem_orcamento_nao_chama(sessoes):
    with sessoes() as s, s.begin():
        repo_ia.salvar_config_ia(s, {"max_chamadas_dia": 0}, T0)
    t = TransporteFake([])
    with pytest.raises(SemOrcamento):
        chamar(sessoes, t)
    assert t.pedidos == [] and chamadas(sessoes) == []
```

Create `tests/ia/test_transporte_openai.py`:

```python
import json

import httpx
import pytest
import respx

from tcg_sniper.ia.modelos import ChaveInvalida, ErroIA, Pedido
from tcg_sniper.ia.transporte_openai import TransporteOpenAI

URL = "https://api.openai.test/v1/responses"
PEDIDO = Pedido("gpt-5", "low", "inst", "txt", ("QUFB",), "veredito", {"type": "object"})


def transporte():
    return TransporteOpenAI("sk-teste-segredo", max_retries=0, base_url="https://api.openai.test/v1")


def resposta_ok(texto):
    return {
        "id": "resp_1", "object": "response", "created_at": 0, "model": "gpt-5", "status": "completed",
        "output": [{"type": "message", "id": "m1", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": texto, "annotations": []}]}],
        "usage": {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150,
                  "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 10}},
        "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
    }


@respx.mock
def test_envia_texto_imagem_e_formato():
    rota = respx.post(URL).mock(return_value=httpx.Response(200, json=resposta_ok('{"a": 1}')))
    bruta = transporte().enviar(PEDIDO)
    assert (bruta.texto, bruta.tokens_entrada, bruta.tokens_saida) == ('{"a": 1}', 120, 30)
    corpo = json.loads(rota.calls[0].request.content)
    assert corpo["model"] == "gpt-5" and corpo["reasoning"] == {"effort": "low"} and corpo["instructions"] == "inst"
    conteudo = corpo["input"][0]["content"]
    assert conteudo[0] == {"type": "input_text", "text": "txt"}
    assert conteudo[1] == {"type": "input_image", "image_url": "data:image/jpeg;base64,QUFB", "detail": "low"}
    assert corpo["text"]["format"] == {"type": "json_schema", "name": "veredito", "schema": {"type": "object"}, "strict": True}


@respx.mock
@pytest.mark.parametrize("codigo", [401, 403])
def test_chave_recusada(codigo):
    respx.post(URL).mock(return_value=httpx.Response(codigo, json={"error": {"message": "bad key sk-teste-segredo", "code": "invalid_api_key"}}))
    with pytest.raises(ChaveInvalida) as erro:
        transporte().enviar(PEDIDO)
    assert "sk-teste" not in str(erro.value)


@respx.mock
def test_sem_credito_e_chave_invalida():
    respx.post(URL).mock(return_value=httpx.Response(429, json={"error": {"message": "quota", "code": "insufficient_quota", "type": "insufficient_quota"}}))
    with pytest.raises(ChaveInvalida, match="crédito"):
        transporte().enviar(PEDIDO)


@respx.mock
@pytest.mark.parametrize("codigo", [429, 500])
def test_outros_erros(codigo):
    respx.post(URL).mock(return_value=httpx.Response(codigo, json={"error": {"message": "x sk-teste-segredo", "code": "rate_limit_exceeded"}}))
    with pytest.raises(ErroIA) as erro:
        transporte().enviar(PEDIDO)
    assert not isinstance(erro.value, ChaveInvalida) and "sk-teste" not in str(erro.value)
```

(Crie `tests/ia/__init__.py` só se as outras pastas de teste tiverem um; hoje não têm — use `--import-mode=importlib` como elas.)

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/ia -q`
Expected: FAIL (ImportError: `tcg_sniper.ia`).

- [ ] **Step 4: Implementação**

`src/tcg_sniper/ia/__init__.py`:

```python
"""Único lugar do projeto que chama a OpenAI: transporte, orçamento, imagens e registro das chamadas."""
```

`src/tcg_sniper/ia/modelos.py`:

```python
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


class ErroIA(Exception):
    """Falha da chamada (rede, 5xx, 429 de limite, resposta fora do formato). A mensagem nunca traz a chave."""


class ChaveInvalida(ErroIA):
    """Chave ausente, recusada (401/403) ou sem crédito: só volta com ação do usuário."""


class SemOrcamento(ErroIA):
    """Teto de gasto ou de chamadas atingido: a chamada nem saiu."""


@dataclass(frozen=True)
class Pedido:
    modelo: str
    esforco: str
    instrucoes: str
    texto: str
    imagens: tuple[str, ...]  # JPEG em base64, sem o prefixo data:
    nome_formato: str
    formato: dict  # JSON Schema da resposta (structured outputs, strict)


@dataclass(frozen=True)
class Bruta:
    texto: str
    tokens_entrada: int
    tokens_saida: int


class Transporte(Protocol):
    def enviar(self, pedido: Pedido) -> Bruta: ...


@dataclass(frozen=True)
class RespostaIA:
    dados: dict
    modelo: str
    tokens_entrada: int
    tokens_saida: int
    custo_usd: Decimal
    chamada_id: int
```

`src/tcg_sniper/ia/transporte_openai.py`:

```python
"""Transporte real: Responses API da OpenAI com resposta em JSON Schema (structured outputs)."""

import openai

from tcg_sniper.ia.modelos import Bruta, ChaveInvalida, ErroIA, Pedido


class TransporteOpenAI:
    def __init__(self, chave: str, timeout_s: float = 60, max_retries: int = 3, base_url: str | None = None):
        # max_retries: o SDK repete 408/409/429/5xx e falhas de conexão com espera crescente
        self._cliente = openai.OpenAI(api_key=chave, timeout=timeout_s, max_retries=max_retries, base_url=base_url)

    def enviar(self, pedido: Pedido) -> Bruta:
        conteudo = [{"type": "input_text", "text": pedido.texto}]
        conteudo += [
            {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}", "detail": "low"}
            for b64 in pedido.imagens
        ]
        try:
            resposta = self._cliente.responses.create(
                model=pedido.modelo,
                instructions=pedido.instrucoes,
                input=[{"role": "user", "content": conteudo}],
                reasoning={"effort": pedido.esforco},
                text={"format": {"type": "json_schema", "name": pedido.nome_formato, "schema": pedido.formato, "strict": True}},
            )
        except (openai.AuthenticationError, openai.PermissionDeniedError) as erro:
            raise ChaveInvalida(f"chave recusada pela OpenAI ({erro.status_code})") from None
        except openai.RateLimitError as erro:
            if _codigo(erro) == "insufficient_quota":
                raise ChaveInvalida("conta da OpenAI sem crédito (insufficient_quota)") from None
            raise ErroIA("OpenAI 429: limite de requisições") from None
        except openai.APIStatusError as erro:
            raise ErroIA(f"OpenAI {erro.status_code}") from None
        except openai.APIConnectionError as erro:  # inclui timeout
            raise ErroIA(f"sem conexão com a OpenAI: {type(erro).__name__}") from None
        uso = resposta.usage
        return Bruta(resposta.output_text, uso.input_tokens if uso else 0, uso.output_tokens if uso else 0)


def _codigo(erro: openai.APIStatusError) -> str | None:
    corpo = erro.body if isinstance(erro.body, dict) else {}
    interno = corpo.get("error", corpo) if isinstance(corpo, dict) else {}
    return interno.get("code") if isinstance(interno, dict) else None
```

As mensagens das exceções são montadas aqui (sem `str(erro)` do SDK), então nunca carregam a chave nem o corpo da resposta.

`src/tcg_sniper/ia/orcamento.py`:

```python
"""Tetos de gasto: dólares por dia e por mês e chamadas por dia (dia e mês no fuso da configuração)."""

from tcg_sniper.db.models import ConfigIA
from tcg_sniper.db.repositorio_ia import Gasto


def _usd(valor) -> str:
    return f"US$ {valor:.2f}".replace(".", ",")


def motivo_sem_orcamento(cfg: ConfigIA, g: Gasto) -> str | None:
    """None se a próxima chamada cabe nos três tetos; senão o motivo, para log, aviso e mensagem."""
    if g.dia_usd >= cfg.teto_dia_usd:
        return f"teto diário de {_usd(cfg.teto_dia_usd)} atingido"
    if g.mes_usd >= cfg.teto_mes_usd:
        return f"teto mensal de {_usd(cfg.teto_mes_usd)} atingido"
    if g.chamadas_dia >= cfg.max_chamadas_dia:
        return f"limite de {cfg.max_chamadas_dia} chamadas por dia atingido"
    return None
```

`src/tcg_sniper/ia/imagens.py`:

```python
"""Baixa a imagem do produto e a prepara para a chamada: até 512 px, JPEG, base64."""

import base64
import io
import logging

import httpx
from PIL import Image, UnidentifiedImageError

log = logging.getLogger(__name__)

LADO_MAX = 512
MAX_BYTES = 5 * 1024 * 1024
QUALIDADE = 80


def preparar(cliente: httpx.Client, url: str | None) -> str | None:
    """JPEG em base64, ou None se não houver URL ou se baixar/abrir falhar (a pergunta segue só com texto)."""
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        resposta = cliente.get(url, follow_redirects=True)
        resposta.raise_for_status()
        if len(resposta.content) > MAX_BYTES:
            log.warning("imagem grande demais (%d bytes): %s", len(resposta.content), url)
            return None
        imagem = Image.open(io.BytesIO(resposta.content))
        imagem.thumbnail((LADO_MAX, LADO_MAX))
        saida = io.BytesIO()
        imagem.convert("RGB").save(saida, "JPEG", quality=QUALIDADE)
    except (httpx.HTTPError, UnidentifiedImageError, OSError) as erro:
        log.warning("não consegui preparar a imagem %s: %s", url, type(erro).__name__)
        return None
    return base64.b64encode(saida.getvalue()).decode()
```

`src/tcg_sniper/ia/cliente.py`:

```python
"""`perguntar`: confere o orçamento, chama o transporte, calcula o custo e registra a chamada."""

import json
from collections.abc import Callable, Sequence
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import ConfigIA
from tcg_sniper.db.repositorio import agora_utc
from tcg_sniper.ia.modelos import Bruta, ErroIA, Pedido, RespostaIA, SemOrcamento, Transporte
from tcg_sniper.ia.orcamento import motivo_sem_orcamento

MILHAO = Decimal(1_000_000)
CASAS = Decimal("0.000001")


def custo(tokens_entrada: int, tokens_saida: int, cfg: ConfigIA) -> Decimal:
    total = tokens_entrada * cfg.preco_entrada_milhao_usd + tokens_saida * cfg.preco_saida_milhao_usd
    return (total / MILHAO).quantize(CASAS)


def perguntar(
    sessoes: sessionmaker[Session],
    transporte: Transporte,
    *,
    finalidade: str,
    instrucoes: str,
    texto: str,
    imagens: Sequence[str],
    nome_formato: str,
    formato: dict,
    zona: ZoneInfo,
    modelo: str | None = None,
    relogio: Callable[[], datetime] = agora_utc,
) -> RespostaIA:
    """Uma chamada. Cada chamada (ok ou erro) é gravada na sua própria transação, para contar no
    orçamento mesmo se quem chamou desfizer a dele. Lança SemOrcamento (sem chamar), ChaveInvalida ou ErroIA."""
    with sessoes() as s, s.begin():
        cfg = repo_ia.obter_config_ia(s)
        motivo = motivo_sem_orcamento(cfg, repo_ia.gasto(s, relogio(), zona))
        if motivo is not None:
            raise SemOrcamento(motivo)
        s.expunge(cfg)
    pedido = Pedido(modelo or cfg.modelo, cfg.esforco, instrucoes, texto, tuple(imagens), nome_formato, formato)
    try:
        bruta = transporte.enviar(pedido)
    except ErroIA as erro:
        _registrar(sessoes, relogio(), finalidade, pedido.modelo, Bruta("", 0, 0), Decimal(0), str(erro))
        raise
    valor = custo(bruta.tokens_entrada, bruta.tokens_saida, cfg)
    try:
        dados = json.loads(bruta.texto)
        if not isinstance(dados, dict):
            raise ValueError("não é objeto")
    except ValueError:
        _registrar(sessoes, relogio(), finalidade, pedido.modelo, bruta, valor, "resposta não é um JSON de objeto")
        raise ErroIA("resposta da OpenAI não é um JSON de objeto") from None
    chamada_id = _registrar(sessoes, relogio(), finalidade, pedido.modelo, bruta, valor, None)
    return RespostaIA(dados, pedido.modelo, bruta.tokens_entrada, bruta.tokens_saida, valor, chamada_id)


def _registrar(sessoes, em, finalidade, modelo, bruta: Bruta, valor: Decimal, erro: str | None) -> int:
    with sessoes() as s, s.begin():
        return repo_ia.registrar_chamada(
            s, em=em, finalidade=finalidade, modelo=modelo, tokens_entrada=bruta.tokens_entrada,
            tokens_saida=bruta.tokens_saida, custo_usd=valor, ok=erro is None, erro=erro,
        ).id
```

- [ ] **Step 5: Rodar**

Run: `uv run pytest tests/ia -q && uv run pytest -q && uv run ruff check .`
Expected: PASS. Se a resposta simulada em `test_transporte_openai.py` não for aceita pela versão instalada do SDK (campo obrigatório novo), acrescente o campo ao dicionário `resposta_ok` — não mude o transporte.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/tcg_sniper/config.py src/tcg_sniper/ia tests/ia tests/fakes.py
git commit -m "feat: ia package (OpenAI transport, budget, images, perguntar with call log)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: URL da imagem nos coletores

**Files:**
- Modify: `src/tcg_sniper/coletor_liga/modelos.py` (`Resumo.imagem_url`), `src/tcg_sniper/coletor_liga/parsers.py` (`SELETOR_IMAGEM`), `src/tcg_sniper/db/repositorio.py` (`gravar_precos_produto`)
- Modify: `scripts/recortar_fixture.py` (`_blocos_produto` guarda `#featuredImage`), `tests/fixtures/liga/produto_nome_en.html`
- Modify: `src/tcg_sniper/coletor_amazon/modelos.py`, `src/tcg_sniper/coletor_amazon/parsers.py`, `src/tcg_sniper/db/repositorio_amazon.py` (`gravar_busca`, `atualizar_leitura`), `src/tcg_sniper/coletor_amazon/busca.py` (`_confirmar`)
- Test: `tests/coletor_liga/test_parsers.py`, `tests/coletor_liga/test_produtos.py`, `tests/coletor_amazon/test_parsers_amazon.py`, `tests/coletor_amazon/test_busca.py` (ou `tests/db/test_repositorio.py`, onde `gravar_busca` já é testado); `tests/fakes.py` (`cartao_busca(..., imagem=None)`, `html_produto_amazon(..., imagem=None)`)

**Interfaces:**
- Consumes (Task 1): colunas `ProdutoLiga.imagem_url`, `AnuncioAmazon.imagem_url`.
- Produces:
  - `Resumo.imagem_url: str | None = None`; `parsers.SELETOR_IMAGEM = "#featuredImage"` (Liga)
  - `ResultadoBusca.imagem_url: str | None = None`, `OfertaProduto.imagem_url: str | None = None`; `SELETOR_IMAGEM_RESULTADO = "img.s-image"`, `SELETOR_IMAGEM_PRODUTO = "#landingImage"` (Amazon)
  - `repositorio_amazon.atualizar_leitura(s, anuncio_id, titulo, variacao, agora, imagem_url: str | None = None)`

- [ ] **Step 1: Fixture da Liga com a imagem**

Em `scripts/recortar_fixture.py`, `_blocos_produto`: depois da linha do `SELETOR_NOME_EN`, `blocos += [_limpo(no) for no in arvore.css(SELETOR_IMAGEM)]` (importe `SELETOR_IMAGEM` de `coletor_liga.parsers` junto dos outros; crie a constante no Step 3 antes de rodar o script). Regere a fixture a partir da página completa salva:

Run: `cp "C:/Users/danie/.claude/jobs/61a33dc3/tmp/liga-produto-127219.html" tests/fixtures/liga/produto_nome_en.html && uv run python scripts/recortar_fixture.py tests/fixtures/liga/produto_nome_en.html`

Se a página completa não existir mais, insira à mão, logo depois do bloco `.item-name-en` da fixture, a linha:
`<img src="//repositorio.sbrauble.com/arquivos/up/prod/20230222/1677093808_3868.jpg" width="265" height="370" class="image-responsive " id="featuredImage">`

- [ ] **Step 2: Testes (falham)**

Em `tests/coletor_liga/test_parsers.py`:

```python
def test_parse_produto_le_imagem_principal():
    resumo = parse_produto(fixture_liga("produto_nome_en.html"))
    assert resumo.imagem_url == "https://repositorio.sbrauble.com/arquivos/up/prod/20230222/1677093808_3868.jpg"


def test_parse_produto_sem_imagem_da_none():
    assert parse_produto(fixture_liga("produto_um_vendedor.html")).imagem_url is None
```

Em `tests/coletor_liga/test_produtos.py`, no teste que já confere `nome_en` gravado (procure `nome_en`), acrescente a mesma conferência para `imagem_url`: a coleta da página com imagem grava `produto.imagem_url`; uma coleta depois, de página sem imagem, mantém o valor.

Em `tests/fakes.py`: `cartao_busca(asin, titulo, preco, patrocinado=False, imagem=None)` acrescenta `<img class="s-image" src="{imagem}">` dentro do cartão quando `imagem`; `html_produto_amazon(..., imagem=None)` acrescenta `<img id="landingImage" data-old-hires="{imagem}" src="data:image/gif;base64,R0lGOD">` quando `imagem`.

Em `tests/coletor_amazon/test_parsers_amazon.py`:

```python
def test_busca_le_imagem():
    html = html_busca(cartao_busca("B0A", "Caixa", "R$ 10,00", imagem="https://m.media-amazon.com/images/I/a._AC_UL320_.jpg"),
                      cartao_busca("B0B", "Outra", None))
    a, b = parse_busca(html, 10)
    assert a.imagem_url == "https://m.media-amazon.com/images/I/a._AC_UL320_.jpg" and b.imagem_url is None


def test_produto_le_imagem_grande_e_ignora_data_uri():
    html = html_produto_amazon("Caixa", "R$ 10,00", None, None, imagem="https://m.media-amazon.com/images/I/a._AC_SL1500_.jpg")
    assert parse_produto_amazon(html, "B0A").imagem_url == "https://m.media-amazon.com/images/I/a._AC_SL1500_.jpg"
    so_data = '<html><body><span id="productTitle">X</span><img id="landingImage" src="data:image/gif;base64,R0lGOD"></body></html>'
    assert parse_produto_amazon(so_data, "B0A").imagem_url is None
```

No arquivo onde `gravar_busca` é testado hoje (`grep -rn "gravar_busca" tests`), acrescente:

```python
def test_busca_so_preenche_imagem_vazia_e_produto_troca(s):
    p = criar_produto(s, "p1")
    item = lambda img: ResultadoBusca("B0A", "Caixa", "https://www.amazon.com.br/dp/B0A", None, False, img)  # noqa: E731
    [a] = repo_amz.gravar_busca(s, [item(None)], p.id, T0, SP)
    assert a.imagem_url is None
    [a] = repo_amz.gravar_busca(s, [item("https://img/1.jpg")], p.id, T0, SP)
    assert a.imagem_url == "https://img/1.jpg"
    [a] = repo_amz.gravar_busca(s, [item("https://img/2.jpg")], p.id, T0, SP)
    assert a.imagem_url == "https://img/1.jpg"  # a busca não troca: evita reavaliar o anúncio a cada ciclo
    repo_amz.atualizar_leitura(s, a.id, "Caixa", None, T0, imagem_url="https://img/grande.jpg")
    repo_amz.atualizar_leitura(s, a.id, "Caixa", None, T0)  # sem imagem: mantém
    s.refresh(a)
    assert a.imagem_url == "https://img/grande.jpg"
```

- [ ] **Step 3: Implementação**

Liga — `parsers.py`: `SELETOR_IMAGEM = "#featuredImage"` junto de `SELETOR_NOME_EN`; função

```python
def _imagem(arvore: LexborHTMLParser) -> str | None:
    no = arvore.css_first(SELETOR_IMAGEM)
    src = (no.attributes.get("src") or "").strip() if no is not None else ""
    if src.startswith("//"):
        src = "https:" + src
    return src if src.startswith(("http://", "https://")) else None
```

e `imagem_url=_imagem(arvore)` nos dois `Resumo(...)` de `parse_produto`. `modelos.Resumo`: `imagem_url: str | None = None  # imagem principal (#featuredImage); None quando a página não a mostra`.

`repositorio.gravar_precos_produto`: troque o `update` do `nome_en` por um que junta os dois campos não nulos:

```python
    extras = {k: v for k, v in (("nome_en", resumo.nome_en), ("imagem_url", resumo.imagem_url)) if v is not None}
    if extras:
        s.execute(update(ProdutoLiga).where(ProdutoLiga.id == produto_id).values(**extras))
```

(e a docstring: "Grava também o nome em inglês e a imagem do produto quando a página os trouxe (nunca apaga um já guardado).")

Amazon — `modelos.py`: `ResultadoBusca.imagem_url: str | None = None` (último campo) e `OfertaProduto.imagem_url: str | None = None` (último campo, depois de `variacao`). `parsers.py`:

```python
SELETOR_IMAGEM_RESULTADO = "img.s-image"
SELETOR_IMAGEM_PRODUTO = "#landingImage"


def _url_imagem(no: LexborNode | None, *atributos: str) -> str | None:
    if no is None:
        return None
    for atributo in atributos:
        valor = (no.attributes.get(atributo) or "").strip()
        if valor.startswith(("http://", "https://")):
            return valor
    return None
```

Em `parse_busca`: `imagem_url=_url_imagem(cartao.css_first(SELETOR_IMAGEM_RESULTADO), "src")`. Em `parse_produto_amazon`: `imagem_url=_url_imagem(arvore.css_first(SELETOR_IMAGEM_PRODUTO), "data-old-hires", "src")` passado como argumento nomeado no `OfertaProduto(...)`. Acrescente `SELETOR_IMAGEM_PRODUTO` à tupla de blocos da página de produto (a mesma onde está `SELETOR_VARIACAO`), para recortes futuros manterem a imagem.

`repositorio_amazon.gravar_busca`: `imagem_url=item.imagem_url` no `values(...)`; no `set_` do conflito, `"imagem_url": func.coalesce(AnuncioAmazon.imagem_url, stmt.excluded.imagem_url)` (comentário: `# a busca só preenche a imagem vazia; a página do produto pode trocar`). `atualizar_leitura(..., imagem_url: str | None = None)`: monta `valores = {"titulo": ..., "variacao": ..., "visto_ultimo_em": agora}` e acrescenta `imagem_url` só se não for None. `busca._confirmar`: `repo.atualizar_leitura(s, anuncio_id, oferta.titulo, oferta.variacao, agora, oferta.imagem_url)`.

- [ ] **Step 4: Rodar**

Run: `uv run pytest tests/coletor_liga tests/coletor_amazon tests/db -q && uv run pytest -q && uv run ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/recortar_fixture.py src/tcg_sniper/coletor_liga src/tcg_sniper/coletor_amazon src/tcg_sniper/db tests
git commit -m "feat: store the main product image URL from LigaMagic and Amazon

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Admin — aba IA em Configurações, card do casador em Serviços e gasto no Dashboard

**Files:**
- Create: `src/tcg_sniper/admin/formularios_ia.py`
- Modify: `src/tcg_sniper/admin/app.py` (seção "ia" em `_salvos`/`_tela_configuracoes`, rota `POST /configuracoes/ia`, rotas `/casador/pausar`, `/casador/retomar`, `/casador/rodar-agora`, contexto de Serviços e Dashboard)
- Modify: `src/tcg_sniper/admin/templates/configuracoes.html`, `servicos.html`, `index.html`
- Modify: `src/tcg_sniper/admin/static/admin.css` (regerado)
- Test: `tests/admin/test_admin_ia.py` (novo), `tests/admin/test_formularios_ia.py` (novo)

**Interfaces:**
- Consumes (Task 1): `repositorio_ia.obter_config_ia`, `salvar_config_ia`, `gasto`, `Gasto`; `models.COLETOR_CASADOR`, `ESFORCOS_IA`, `LIMITES_CONFIG_IA`; `repositorio.pausar/retomar/solicitar_execucao/obter_estado` com `coletor`.
- Produces:
  - `formularios_ia.CAMPOS_IA`, `ROTULOS_IA`, `EXPLICACOES_IA`, `OPCOES_IA: dict[str, tuple[tuple[str, str], ...]]`, `validar_ia(campos) -> tuple[dict, dict]`, `texto_ia(cfg, campo) -> str`
  - Mensagens de Serviços: `casador_pausar`, `casador_retomar`, `casador_rodar`

- [ ] **Step 1: Testes (falham)**

Create `tests/admin/test_formularios_ia.py`:

```python
from decimal import Decimal

from tcg_sniper.admin.formularios_ia import CAMPOS_IA, validar_ia

VALIDO = {
    "ligado": "sim", "modelo": "gpt-5-mini", "esforco": "minimal",
    "preco_entrada_milhao_usd": "0,25", "preco_saida_milhao_usd": "2", "teto_dia_usd": "1,50",
    "teto_mes_usd": "15", "max_chamadas_dia": "500", "intervalo_min": "10", "lote": "30",
    "automatico": "não", "confianca_confirmar": "95", "confianca_ignorar": "85",
}


def test_valido():
    valores, erros = validar_ia(VALIDO)
    assert erros == {}
    assert set(valores) == set(CAMPOS_IA)
    assert valores["ligado"] is True and valores["automatico"] is False
    assert valores["preco_entrada_milhao_usd"] == Decimal("0.25") and valores["teto_dia_usd"] == Decimal("1.50")
    assert valores["lote"] == 30 and valores["esforco"] == "minimal"


def test_invalidos():
    ruins = {
        "ligado": "talvez", "modelo": "gpt 5", "esforco": "max", "preco_entrada_milhao_usd": "-1",
        "preco_saida_milhao_usd": "abc", "teto_dia_usd": "1.234", "teto_mes_usd": "", "max_chamadas_dia": "1.5",
        "intervalo_min": "0", "lote": "501", "automatico": "", "confianca_confirmar": "101", "confianca_ignorar": "-5",
    }
    _, erros = validar_ia(ruins)
    assert set(erros) == set(CAMPOS_IA)


def test_modelo_vazio_e_longo():
    assert "modelo" in validar_ia({**VALIDO, "modelo": ""})[1]
    assert "modelo" in validar_ia({**VALIDO, "modelo": "x" * 101})[1]
```

Create `tests/admin/test_admin_ia.py`:

```python
import base64
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from fakes import T0
from test_formularios_ia import VALIDO

from tcg_sniper.admin.app import criar_app
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import COLETOR_CASADOR, EstadoColetorTipo


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo", "openai_api_key": "sk-segredo-de-teste"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def test_aba_ia_com_padroes_e_sem_a_chave(cliente):
    html = cliente.get("/configuracoes").text
    assert 'aria-label="IA"' in html and 'name="modelo"' in html and "gpt-5" in html
    assert "Chave configurada: sim" in html
    assert "sk-segredo" not in html
    assert "OPENAI_API_KEY" in html  # rodapé com as variáveis do .env


def test_sem_chave_aparece_nao(sessoes, config):
    c = TestClient(criar_app(sessoes, config.model_copy(update={"admin_senha": "s"})), headers={"Authorization": basic("admin", "s")})
    assert "Chave configurada: não" in c.get("/configuracoes").text


def test_salvar_ia(cliente, sessoes):
    r = cliente.post("/configuracoes/ia", data=VALIDO, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/configuracoes?msg=ia"
    with sessoes() as s:
        cfg = repo_ia.obter_config_ia(s)
        assert cfg.modelo == "gpt-5-mini" and cfg.ligado is True and cfg.teto_dia_usd == Decimal("1.50")
    html = cliente.get("/configuracoes?msg=ia").text
    assert "Salvo" in html


def test_erro_na_ia_abre_a_aba_e_nao_grava(cliente, sessoes):
    r = cliente.post("/configuracoes/ia", data={**VALIDO, "lote": "0"})
    assert r.status_code == 400 and "input-error" in r.text
    with sessoes() as s:
        assert repo_ia.obter_config_ia(s).modelo == "gpt-5"


def test_resumo_do_gasto_na_aba(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo_ia.registrar_chamada(
            s, em=repo.agora_utc(), finalidade="casamento", modelo="gpt-5", tokens_entrada=1, tokens_saida=1,
            custo_usd=Decimal("0.123456"), ok=True, erro=None,
        )
    html = cliente.get("/configuracoes").text
    assert "US$ 0,12" in html and "1 de 1000" in html


def test_card_do_casador_e_acoes(cliente, sessoes):
    html = cliente.get("/servicos").text
    assert "Casador (IA)" in html and "/casador/pausar" in html and "/casador/rodar-agora" in html
    assert "desligada" in html  # config_ia.ligado = false
    assert cliente.post("/casador/pausar", follow_redirects=False).headers["location"] == "/servicos?msg=casador_pausar"
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_CASADOR).estado is EstadoColetorTipo.PAUSADO
    assert "/casador/retomar" in cliente.get("/servicos").text
    cliente.post("/casador/retomar")
    cliente.post("/casador/rodar-agora")
    with sessoes() as s:
        estado = repo.obter_estado(s, coletor=COLETOR_CASADOR)
        assert estado.estado is EstadoColetorTipo.ATIVO and estado.execucao_solicitada


def test_dashboard_mostra_gasto_e_aviso_de_pausa(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar(s, "chave recusada pela OpenAI (401)", T0, COLETOR_CASADOR)
    html = cliente.get("/").text
    assert "IA no mês" in html and "US$ 0,00" in html
    assert "Casador (IA) pausado" in html and "chave recusada" in html
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/admin/test_formularios_ia.py tests/admin/test_admin_ia.py -q`
Expected: FAIL.

- [ ] **Step 3: Formulário**

Create `src/tcg_sniper/admin/formularios_ia.py`:

```python
"""Validação da aba IA de Configurações, com os limites do banco."""

import re
from collections.abc import Mapping
from decimal import Decimal

from tcg_sniper.db.models import ESFORCOS_IA, LIMITES_CONFIG_IA, ConfigIA

DINHEIRO_RE = re.compile(r"[0-9]{1,6}(\.[0-9]{1,2})?")
PRECO_RE = re.compile(r"[0-9]{1,6}(\.[0-9]{1,4})?")
SIM_NAO = (("sim", "Sim"), ("não", "Não"))

CAMPOS_IA = (
    "ligado",
    "modelo",
    "esforco",
    "preco_entrada_milhao_usd",
    "preco_saida_milhao_usd",
    "teto_dia_usd",
    "teto_mes_usd",
    "max_chamadas_dia",
    "intervalo_min",
    "lote",
    "automatico",
    "confianca_confirmar",
    "confianca_ignorar",
)
ROTULOS_IA = {
    "ligado": "IA ligada",
    "modelo": "Modelo da OpenAI",
    "esforco": "Esforço de raciocínio",
    "preco_entrada_milhao_usd": "Preço de entrada (US$ por milhão de tokens)",
    "preco_saida_milhao_usd": "Preço de saída (US$ por milhão de tokens)",
    "teto_dia_usd": "Teto de gasto por dia (US$)",
    "teto_mes_usd": "Teto de gasto por mês (US$)",
    "max_chamadas_dia": "Máximo de chamadas por dia",
    "intervalo_min": "Intervalo entre rodadas (min)",
    "lote": "Anúncios por rodada",
    "automatico": "Automático",
    "confianca_confirmar": "Confiança mínima para confirmar sozinho (%)",
    "confianca_ignorar": "Confiança mínima para ignorar sozinho (%)",
}
EXPLICACOES_IA = {
    "ligado": "Desligada, o casador não chama a OpenAI. Ligada, avalia os anúncios pendentes e mostra a sugestão em Casamentos.",
    "modelo": "Nome do modelo na API da OpenAI, como gpt-5 ou gpt-5-mini. Confira os preços abaixo ao trocar.",
    "esforco": "Mais esforço tende a acertar mais e custa mais tokens de saída.",
    "preco_entrada_milhao_usd": "Copie da página de preços da OpenAI para o modelo escolhido. Usado para calcular o gasto.",
    "preco_saida_milhao_usd": "Copie da página de preços da OpenAI. Inclui os tokens de raciocínio.",
    "teto_dia_usd": "Atingido, o casador para até o dia seguinte (fuso da seção Geral) e avisa no WhatsApp.",
    "teto_mes_usd": "Atingido, o casador para até o mês seguinte e avisa no WhatsApp.",
    "max_chamadas_dia": "Trava extra contra laço ou erro, independente do preço.",
    "intervalo_min": "De quanto em quanto tempo o casador procura anúncios novos ou mudados.",
    "lote": "Quantos anúncios no máximo por rodada.",
    "automatico": "Ligado, a IA confirma ou ignora sozinha quando a confiança passa dos limites abaixo. Decisões suas nunca são trocadas.",
    "confianca_confirmar": "A IA diz que é o mesmo produto com pelo menos essa confiança: confirma (com o automático ligado).",
    "confianca_ignorar": "A IA diz que é outro produto com pelo menos essa confiança: ignora (com o automático ligado).",
}
OPCOES_IA: dict[str, tuple[tuple[str, str], ...]] = {
    "ligado": SIM_NAO,
    "automatico": SIM_NAO,
    "esforco": tuple((e, e) for e in ESFORCOS_IA),
}


def texto_ia(cfg: ConfigIA, campo: str) -> str:
    """Valor salvo como aparece no formulário."""
    valor = getattr(cfg, campo)
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    if isinstance(valor, Decimal):
        return format(valor.normalize(), "f").replace(".", ",")
    return str(valor)


def validar_ia(campos: Mapping[str, str]) -> tuple[dict[str, object], dict[str, str]]:
    valores: dict[str, object] = {}
    erros: dict[str, str] = {}

    for campo in ("ligado", "automatico"):
        texto = (campos.get(campo) or "").strip()
        if texto in ("sim", "não"):
            valores[campo] = texto == "sim"
        else:
            erros[campo] = "Escolha Sim ou Não."

    modelo = (campos.get("modelo") or "").strip()
    if not modelo or len(modelo) > 100 or any(c.isspace() for c in modelo):
        erros["modelo"] = "Informe o nome do modelo, sem espaços (ex.: gpt-5)."
    else:
        valores["modelo"] = modelo

    esforco = (campos.get("esforco") or "").strip()
    if esforco in ESFORCOS_IA:
        valores["esforco"] = esforco
    else:
        erros["esforco"] = "Escolha um dos valores da lista."

    for campo, padrao, exemplo in (
        ("preco_entrada_milhao_usd", PRECO_RE, "1,25"),
        ("preco_saida_milhao_usd", PRECO_RE, "10"),
        ("teto_dia_usd", DINHEIRO_RE, "2"),
        ("teto_mes_usd", DINHEIRO_RE, "20"),
    ):
        texto = (campos.get(campo) or "").strip().replace(",", ".")
        if padrao.fullmatch(texto):
            valores[campo] = Decimal(texto)
        else:
            erros[campo] = f"Informe um valor em dólar, zero ou mais (ex.: {exemplo})."

    for campo, (minimo, maximo) in LIMITES_CONFIG_IA.items():
        texto = (campos.get(campo) or "").strip()
        if not (texto.isascii() and texto.isdecimal()) or len(texto) > 6:
            erros[campo] = f"Informe um número inteiro entre {minimo} e {maximo}."
        elif not minimo <= int(texto) <= maximo:
            erros[campo] = f"O valor deve ficar entre {minimo} e {maximo}."
        else:
            valores[campo] = int(texto)
    return valores, erros
```

- [ ] **Step 4: Rotas e contexto (`app.py`)**

- Imports: `from tcg_sniper.admin import formularios_ia as form_ia`, `from tcg_sniper.db import repositorio_ia as repo_ia`, `COLETOR_CASADOR`.
- `_salvos()`: `"ia": {c: form_ia.texto_ia(ia, c) for c in form_ia.CAMPOS_IA}` com `ia = repo_ia.obter_config_ia(s)`.
- `_tela_configuracoes`: acrescente `("ia", "IA", form_ia.CAMPOS_IA, form_ia.ROTULOS_IA, form_ia.EXPLICACOES_IA)` ao fim de `secoes`; cada dicionário de seção ganha `"opcoes": form_ia.OPCOES_IA if id_ == "ia" else {}`; troque as tuplas `("geral", "liga", "amazon")` por `("geral", "liga", "amazon", "ia")` (mensagem e aba ativa). No contexto: `"resumo_ia": _resumo_ia(request)` onde

```python
    def _resumo_ia(request: Request) -> dict:
        with sessoes() as s, s.begin():
            cfg = repo_ia.obter_config_ia(s)
            g = repo_ia.gasto(s, repo.agora_utc(), request.state.config.zona)
            return {"gasto": g, "teto_dia": cfg.teto_dia_usd, "teto_mes": cfg.teto_mes_usd,
                    "max_chamadas": cfg.max_chamadas_dia, "chave": bool((config.openai_api_key or "").strip())}
```
- Rota:

```python
    @app.post("/configuracoes/ia", response_class=HTMLResponse)
    async def salvar_ia(request: Request):
        def gravar(s, valores):
            repo_ia.salvar_config_ia(s, valores, repo.agora_utc())

        return await _salvar_secao(request, "ia", form_ia.CAMPOS_IA, form_ia.validar_ia, gravar)
```

- Filtro Jinja `usd`: `templates.env.filters["usd"] = lambda v: f"US$ {v:.2f}".replace(".", ",")`.
- Serviços: contexto `"estado_casador": repo.obter_estado(s, coletor=COLETOR_CASADOR)`, `"ia_ligada": repo_ia.obter_config_ia(s).ligado`. Rotas (copiando o padrão de `/amazon/pausar`):

```python
    @app.post("/casador/pausar")
    def pausar_casador():
        with sessoes() as s, s.begin():
            repo.pausar(s, "pausado no admin", repo.agora_utc(), COLETOR_CASADOR)
        return RedirectResponse("/servicos?msg=casador_pausar", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/casador/retomar")
    def retomar_casador():
        with sessoes() as s, s.begin():
            repo.retomar(s, repo.agora_utc(), COLETOR_CASADOR)
        return RedirectResponse("/servicos?msg=casador_retomar", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/casador/rodar-agora")
    def rodar_casador():
        with sessoes() as s, s.begin():
            repo.solicitar_execucao(s, repo.agora_utc(), COLETOR_CASADOR)
        return RedirectResponse("/servicos?msg=casador_rodar", status_code=status.HTTP_303_SEE_OTHER)
```

  Em `MENSAGENS_SERVICOS`: `"casador_pausar": "Casador pausado."`, `"casador_retomar": "Casador retomado; roda em até 1 minuto."`, `"casador_rodar": "Rodada do casador solicitada; começa em até 1 minuto."`.
- Dashboard: contexto `"estado_casador": repo.obter_estado(s, coletor=COLETOR_CASADOR)` e `"gasto_ia": repo_ia.gasto(s, agora, efetiva.zona)`.

- [ ] **Step 5: Templates**

`configuracoes.html`:
- Dentro do loop, antes do `<form>`, para a aba IA:

```html
      {% if secao.id == "ia" %}
      <div class="stats stats-vertical sm:stats-horizontal bg-base-200">
        <div class="stat"><div class="stat-title">Hoje</div><div class="stat-value text-lg tabular-nums">{{ resumo_ia.gasto.dia_usd|usd }}</div><div class="stat-desc">de {{ resumo_ia.teto_dia|usd }}</div></div>
        <div class="stat"><div class="stat-title">Mês</div><div class="stat-value text-lg tabular-nums">{{ resumo_ia.gasto.mes_usd|usd }}</div><div class="stat-desc">de {{ resumo_ia.teto_mes|usd }}</div></div>
        <div class="stat"><div class="stat-title">Chamadas hoje</div><div class="stat-value text-lg tabular-nums">{{ resumo_ia.gasto.chamadas_dia }}</div><div class="stat-desc">{{ resumo_ia.gasto.chamadas_dia }} de {{ resumo_ia.max_chamadas }}</div></div>
      </div>
      <p class="text-sm">Chave configurada: {{ "sim" if resumo_ia.chave else "não" }} (OPENAI_API_KEY no .env)</p>
      {% endif %}
```

- O campo: se `campo in secao.opcoes`, renderize um `select` em vez do `input`:

```html
          {% if campo in secao.opcoes %}
          <select id="{{ secao.id }}-{{ campo }}" name="{{ campo }}" aria-label="{{ secao.rotulos[campo] }}" aria-describedby="{{ secao.id }}-{{ campo }}-ajuda" class="select w-full{% if campo in secao.erros %} select-error{% endif %}"{% if campo in secao.erros %} aria-invalid="true"{% endif %}>
            {% for valor, rotulo in secao.opcoes[campo] %}<option value="{{ valor }}"{% if secao.valores[campo] == valor %} selected{% endif %}>{{ rotulo }}</option>{% endfor %}
          </select>
          {% else %}
          (o input atual, sem mudança)
          {% endif %}
```

- Rodapé: acrescente `OPENAI_API_KEY` à lista de variáveis do `.env`.

`servicos.html`: grade `md:grid-cols-2 xl:grid-cols-4` e um quarto card:

```html
  <div class="card bg-base-100 shadow-sm"><div class="card-body">
    <h2 class="card-title">Casador (IA)
      {% if estado_casador.estado.value == "pausado" %}{{ selo("pausado") }}
      {% elif not ia_ligada %}{{ selo("inativo", "desligada") }}
      {% else %}{{ selo("ativo") }}{% endif %}</h2>
    {% if estado_casador.estado.value == "pausado" %}
      <p>Pausado. {{ estado_casador.motivo or "" }}</p>
      <div class="card-actions"><form method="post" action="/casador/retomar"><button class="btn btn-primary">Retomar (casador)</button></form></div>
    {% else %}
      <p>{% if ia_ligada %}Ativo.{% else %}IA desligada em <a class="link" href="/configuracoes">Configurações → IA</a>.{% endif %}{% if estado_casador.execucao_solicitada %} Rodada solicitada; começa em até 1 minuto.{% endif %}</p>
      <div class="card-actions">
        <form method="post" action="/casador/rodar-agora"><button class="btn btn-primary">Rodar agora</button></form>
        <form method="post" action="/casador/pausar"><button class="btn btn-outline btn-error">Pausar (casador)</button></form>
      </div>
    {% endif %}
  </div></div>
```

`index.html`: depois do aviso da Amazon pausada:

```html
{% if estado_casador.estado.value == "pausado" %}
  {% call aviso("error", "Casador (IA) pausado. " ~ (estado_casador.motivo or "")) %}<a class="link" href="/servicos">Ir para Serviços</a>{% endcall %}
{% endif %}
```

e, no bloco `stats` do Dashboard, um stat no mesmo formato dos vizinhos com título `IA no mês`, valor `{{ gasto_ia.mes_usd|usd }}` e descrição `hoje {{ gasto_ia.dia_usd|usd }}`.

- [ ] **Step 6: CSS e testes**

Run: `uv run python scripts/gerar_css.py && uv run pytest tests/admin -q && uv run pytest -q && uv run ruff check .`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/admin tests/admin
git commit -m "feat: admin AI settings tab, casador card and AI spend on the dashboard

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Admin — selos da IA nos casamentos

**Files:**
- Modify: `src/tcg_sniper/admin/consultas_amazon.py` (`LinhaAnuncio.ia`, `detalhe_casamento`, `LinhaProdutoCasamento.ia_sugere`, `produtos_para_casar`)
- Modify: `src/tcg_sniper/admin/app.py` (passa `cfg_ia` à tela do produto)
- Modify: `src/tcg_sniper/admin/templates/_componentes.html` (macro `selo_ia`), `casamentos_produto.html`, `casamentos.html`
- Modify: `src/tcg_sniper/admin/static/admin.css` (regerado)
- Test: `tests/admin/test_admin_casamentos_ia.py` (novo)

**Interfaces:**
- Consumes (Task 1): `repositorio_ia.avaliacoes_dos_pares`, `repositorio_ia.gravar_avaliacao`, `repositorio_ia.obter_config_ia`, `models.AvaliacaoIA`.
- Produces: `LinhaAnuncio.ia: AvaliacaoIA | None` (último campo, padrão `None`); `LinhaProdutoCasamento.ia_sugere: int` (último campo, padrão `0`); macro `selo_ia(av, cfg_ia)`.

- [ ] **Step 1: Testes (falham)**

Create `tests/admin/test_admin_casamentos_ia.py`:

```python
import base64

import pytest
from fakes import T0, criar_anuncio, criar_produto
from fastapi.testclient import TestClient

from tcg_sniper.admin.app import criar_app
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import StatusCasamento


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def avaliar(s, anuncio, produto, mesmo, confianca, motivo, aplicada=False):
    av = repo_ia.gravar_avaliacao(
        s, anuncio_id=anuncio.id, produto_id=produto.id, mesmo_produto=mesmo, confianca=confianca, motivo=motivo,
        modelo="gpt-5", assinatura="x", sem_imagem=False, chamada_id=None, agora=T0,
    )
    if aplicada:
        av.aplicada_em = T0
        s.flush()
    return av


@pytest.fixture
def cenario(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Caixa Alfa")
        outro = criar_produto(s, "p2", nome="Caixa Beta")
        nao = criar_anuncio(s, "B1", produto=p)
        media = criar_anuncio(s, "B2", produto=p)
        sim = criar_anuncio(s, "B3", produto=p)
        sem = criar_anuncio(s, "B4", produto=p)
        conf = criar_anuncio(s, "B5", produto=p, status=StatusCasamento.CONFIRMADO)
        par_antigo = criar_anuncio(s, "B6", produto=p)
        avaliar(s, nao, p, False, 92, "é carta avulsa")
        avaliar(s, media, p, True, 70, "edição parecida")
        avaliar(s, sim, p, True, 96, "mesma caixa de draft")
        avaliar(s, conf, p, True, 99, "idêntico", aplicada=True)
        avaliar(s, par_antigo, outro, True, 99, "avaliado contra outro produto")
        return p.id


def test_selos_motivo_e_ordem(cliente, cenario):
    html = cliente.get(f"/casamentos/produto/{cenario}").text
    assert "IA: mesmo produto 96%" in html and "IA: outro produto 92%" in html and "IA: mesmo produto 70%" in html
    assert "mesma caixa de draft" in html and "é carta avulsa" in html
    assert "badge-success" in html and "badge-error" in html and "badge-warning" in html
    # sim primeiro (por confiança), depois os demais na ordem de hoje
    assert html.index("Anúncio B3") < html.index("Anúncio B2") < html.index("Anúncio B1")
    assert "avaliado contra outro produto" not in html  # avaliação de outro par não aparece
    assert "pela IA" in html and "idêntico" in html  # confirmado pelo automático


def test_contagem_ia_sugere_na_lista(cliente, cenario):
    html = cliente.get("/casamentos").text
    assert "IA sugere" in html
    assert "2 pela IA" in html  # B3 (96%) e B2 (70%): pendentes com "sim"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/admin/test_admin_casamentos_ia.py -q`
Expected: FAIL.

- [ ] **Step 3: Consultas**

`consultas_amazon.py`:
- `LinhaAnuncio`: último campo `ia: AvaliacaoIA | None = None`.
- `detalhe_casamento`: depois de montar `grupos`, busque as avaliações dos pares (anúncio, `produto_id`) de todas as linhas com `repo_ia.avaliacoes_dos_pares`, recrie cada linha com `dataclasses.replace(linha, ia=avaliacoes.get((linha.anuncio.id, produto_id)))`, e ordene os pendentes com o "sim" da IA primeiro, mantendo a ordem atual entre os demais (sort estável):

```python
    pendentes.sort(key=lambda l: -(l.ia.confianca if l.ia and l.ia.mesmo_produto else -1))
```

- `LinhaProdutoCasamento`: último campo `ia_sugere: int = 0`. Em `produtos_para_casar`, junto das contagens:

```python
        consulta_ia = (
            select(AnuncioAmazon.produto_id, func.count())
            .join(
                AvaliacaoIA,
                and_(AvaliacaoIA.anuncio_id == AnuncioAmazon.id, AvaliacaoIA.produto_id == AnuncioAmazon.produto_id),
            )
            .where(
                AnuncioAmazon.produto_id.in_(precos_liga),
                AnuncioAmazon.status_casamento == StatusCasamento.PENDENTE,
                AvaliacaoIA.mesmo_produto.is_(True),
            )
            .group_by(AnuncioAmazon.produto_id)
        )
        ia_sugere = dict(s.execute(consulta_ia).all())
```

  e `ia_sugere=ia_sugere.get(produto.id, 0)` na montagem (com `ia_sugere = {}` quando não há produtos).

`app.py`, `_tela_produto_casamento`: contexto `"cfg_ia": repo_ia.obter_config_ia(s)`.

- [ ] **Step 4: Templates**

`_componentes.html`:

```html
{% macro selo_ia(av, cfg_ia) -%}
{%- if av.mesmo_produto and av.confianca >= cfg_ia.confianca_confirmar -%}
<span class="badge badge-sm whitespace-nowrap badge-success">IA: mesmo produto {{ av.confianca }}%</span>
{%- elif not av.mesmo_produto and av.confianca >= cfg_ia.confianca_ignorar -%}
<span class="badge badge-sm whitespace-nowrap badge-error">IA: outro produto {{ av.confianca }}%</span>
{%- else -%}
<span class="badge badge-sm whitespace-nowrap badge-warning">IA: {{ "mesmo produto" if av.mesmo_produto else "outro produto" }} {{ av.confianca }}%</span>
{%- endif -%}
{%- endmacro %}
```

`casamentos_produto.html` (importe `selo_ia`):
- Nos pendentes, depois da linha do preço:

```html
      {% if l.ia %}
      <div class="flex flex-wrap items-center gap-2">{{ selo_ia(l.ia, cfg_ia) }}{% if l.ia.sem_imagem %}<span class="text-xs text-base-content/60">sem imagem</span>{% endif %}</div>
      <p class="text-xs text-base-content/70 break-words">{{ l.ia.motivo }}</p>
      {% endif %}
```

- Nos confirmados e nos ignorados, logo depois de `titulo_anuncio(l)`:

```html
      {% if l.ia and l.ia.aplicada_em %}
      <div class="flex flex-wrap items-center gap-2"><span class="badge badge-sm badge-outline whitespace-nowrap">pela IA</span><span class="text-xs text-base-content/70 break-words">{{ l.ia.motivo }}</span></div>
      {% endif %}
```

`casamentos.html`: onde a linha mostra as contagens de pendentes/confirmados/ignorados (tabela e cartões), acrescente `{% if l.ia_sugere %}<span class="badge badge-sm badge-success badge-outline whitespace-nowrap">{{ l.ia_sugere }} pela IA</span>{% endif %}` (use o nome da variável de laço que o template já usa) e, na tabela, o cabeçalho da coluna onde ele aparece passa a incluir "IA sugere" (ex.: nova coluna `<th>IA sugere</th>` com o selo na célula; nos cartões, o selo ao lado das contagens).

- [ ] **Step 5: CSS e testes**

Run: `uv run python scripts/gerar_css.py && uv run pytest tests/admin -q && uv run pytest -q && uv run ruff check .`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/tcg_sniper/admin tests/admin
git commit -m "feat: AI verdict badges, reasons and ordering on the matching screens

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Serviço `casador`, CLI e compose

**Files:**
- Create: `src/tcg_sniper/casador/__init__.py`, `src/tcg_sniper/casador/pergunta.py`, `src/tcg_sniper/casador/servico.py`
- Modify: `src/tcg_sniper/cli.py` (subcomando `casador`), `docker-compose.yml` (serviço `casador`), `.env.example` (`OPENAI_API_KEY=`)
- Test: `tests/casador/test_pergunta.py`, `tests/casador/test_servico.py`, `tests/test_cli.py` (subcomando existe)

**Interfaces:**
- Consumes: Task 1 (`repositorio_ia.*`, `repositorio.obter_estado/pausar/consumir_solicitacao` com `COLETOR_CASADOR`, `repositorio_amazon.confirmar_casamento/ignorar_anuncio`); Task 2 (`ia.cliente.perguntar`, `ia.imagens.preparar`, `ia.modelos.*`); Task 3 (colunas `imagem_url`).
- Produces:
  - `casador.pergunta.INSTRUCOES: str`, `FORMATO: dict`, `NOME_FORMATO = "veredito_casamento"`
  - `casador.pergunta.Veredito(mesmo_produto: bool, confianca: int, motivo: str)`
  - `casador.pergunta.assinatura(anuncio, produto) -> str`
  - `casador.pergunta.texto_pergunta(anuncio, produto, preco_liga, preco_amazon) -> str`
  - `casador.pergunta.ler_veredito(dados: dict) -> Veredito` (lança `ErroIA`)
  - `casador.pergunta.avaliar_par(sessoes, transporte, cliente_http, anuncio, produto, preco_liga, preco_amazon, *, finalidade, zona, modelo=None, relogio) -> tuple[Veredito, RespostaIA, bool]` (o bool é `sem_imagem`)
  - `casador.servico.ServicoCasador(sessoes, transporte, config_env, notificador, cliente_http=None, relogio=None, dormir=None)` com `ciclo() -> int`, `rodar()`, `parar()`

- [ ] **Step 1: Testes da pergunta (falham)**

Create `tests/casador/test_pergunta.py`:

```python
from decimal import Decimal

import pytest
from fakes import criar_anuncio, criar_produto

from tcg_sniper.casador.pergunta import FORMATO, assinatura, ler_veredito, texto_pergunta
from tcg_sniper.ia.modelos import ErroIA


def test_texto_tem_os_dois_lados(s):
    p = criar_produto(s, "p1", nome="Caixa de Booster - Contos da Terra Média")
    p.nome_en, p.edicao, p.tipo, p.idioma = "Booster Box - Tales of Middle-earth", "LTR", "Caixas de Boosters", "Inglês"
    a = criar_anuncio(s, "B1", produto=p)
    a.titulo, a.variacao = "MTG LOTR Draft Booster Box", "Draft"
    texto = texto_pergunta(a, p, Decimal("899.90"), None)
    for trecho in ("Caixa de Booster - Contos da Terra Média", "Booster Box - Tales of Middle-earth", "LTR",
                   "Caixas de Boosters", "Inglês", "MTG LOTR Draft Booster Box", "Draft", "R$ 899,90", "sem preço"):
        assert trecho in texto


def test_assinatura_muda_com_os_dados(s):
    p = criar_produto(s, "p1")
    a = criar_anuncio(s, "B1", produto=p)
    base = assinatura(a, p)
    assert assinatura(a, p) == base
    for mudar in (lambda: setattr(a, "titulo", "outro"), lambda: setattr(a, "variacao", "Set"),
                  lambda: setattr(a, "imagem_url", "https://i/1.jpg"), lambda: setattr(p, "nome_en", "X"),
                  lambda: setattr(p, "imagem_url", "https://i/2.jpg"), lambda: setattr(p, "nome", "Y")):
        mudar()
        assert assinatura(a, p) != base
        base = assinatura(a, p)


def test_formato_estrito():
    assert FORMATO["required"] == ["mesmo_produto", "confianca", "motivo"] and FORMATO["additionalProperties"] is False


def test_ler_veredito_valido():
    v = ler_veredito({"mesmo_produto": True, "confianca": 93, "motivo": "  mesma caixa  "})
    assert (v.mesmo_produto, v.confianca, v.motivo) == (True, 93, "mesma caixa")


@pytest.mark.parametrize("dados", [
    {"mesmo_produto": True, "confianca": 150, "motivo": "x"},
    {"mesmo_produto": True, "confianca": -1, "motivo": "x"},
    {"mesmo_produto": "sim", "confianca": 90, "motivo": "x"},
    {"mesmo_produto": True, "confianca": 90.5, "motivo": "x"},
    {"mesmo_produto": True, "confianca": True, "motivo": "x"},
    {"mesmo_produto": True, "confianca": 90, "motivo": "   "},
    {"mesmo_produto": True, "motivo": "x"},
])
def test_ler_veredito_fora_do_formato(dados):
    with pytest.raises(ErroIA):
        ler_veredito(dados)


def test_motivo_longo_e_cortado():
    assert len(ler_veredito({"mesmo_produto": False, "confianca": 80, "motivo": "a" * 500}).motivo) == 200
```

- [ ] **Step 2: Testes do serviço (falham)**

Create `tests/casador/test_servico.py`:

```python
import json
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from fakes import T0, NotificadorFake, TransporteFake, criar_anuncio, criar_produto
from sqlalchemy import select

from tcg_sniper.casador.pergunta import assinatura
from tcg_sniper.casador.servico import ServicoCasador
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import (
    COLETOR_CASADOR,
    AnuncioAmazon,
    AvaliacaoIA,
    ChamadaIA,
    EstadoColetorTipo,
    ProdutoLiga,
    StatusCasamento,
)
from tcg_sniper.ia.modelos import Bruta, ChaveInvalida, ErroIA
from tcg_sniper.notificador.base import Destino


def veredito(mesmo=True, confianca=95, motivo="mesma caixa"):
    return Bruta(json.dumps({"mesmo_produto": mesmo, "confianca": confianca, "motivo": motivo}), 1000, 100)


def sem_rede():
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))


def servico(sessoes, config, respostas, **kw):
    t = TransporteFake(respostas)
    n = NotificadorFake()
    cfg = config.model_copy(update={"openai_api_key": "sk-teste"})
    agora = kw.pop("agora", T0)
    sv = ServicoCasador(sessoes, t, cfg, n, cliente_http=kw.pop("cliente_http", sem_rede()), relogio=lambda: agora, **kw)
    return sv, t, n


def configurar(sessoes, **valores):
    with sessoes() as s, s.begin():
        repo_ia.salvar_config_ia(s, {"ligado": True, **valores}, T0)


def pares(sessoes, n=1, status=StatusCasamento.PENDENTE):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Caixa Alfa")
        return p.id, [criar_anuncio(s, f"B{i}", produto=p, status=status).id for i in range(n)]


def avaliacoes(sessoes):
    with sessoes() as s:
        return list(s.scalars(select(AvaliacaoIA).order_by(AvaliacaoIA.id)))


def status_de(sessoes, anuncio_id):
    with sessoes() as s:
        return s.get(AnuncioAmazon, anuncio_id).status_casamento


def test_desligada_nao_chama(sessoes, config):
    pares(sessoes)
    sv, t, _ = servico(sessoes, config, [])
    assert sv.ciclo() == 0 and t.pedidos == []


def test_sem_chave_nao_chama(sessoes, config):
    configurar(sessoes)
    pares(sessoes)
    sv = ServicoCasador(sessoes, None, config, NotificadorFake(), cliente_http=sem_rede(), relogio=lambda: T0)
    assert sv.ciclo() == 0


def test_pausado_nao_chama(sessoes, config):
    configurar(sessoes)
    pares(sessoes)
    with sessoes() as s, s.begin():
        repo.pausar(s, "pausado no admin", T0, COLETOR_CASADOR)
    sv, t, _ = servico(sessoes, config, [])
    assert sv.ciclo() == 0 and t.pedidos == []


def test_sugere_sem_mudar_status_com_automatico_desligado(sessoes, config):
    configurar(sessoes)
    _, [a] = pares(sessoes)
    sv, t, _ = servico(sessoes, config, [veredito(True, 99)])
    assert sv.ciclo() == 1
    [av] = avaliacoes(sessoes)
    assert av.mesmo_produto and av.confianca == 99 and av.aplicada_em is None and av.sem_imagem
    assert status_de(sessoes, a) is StatusCasamento.PENDENTE
    assert t.pedidos[0].imagens == ()


def test_nao_reavalia_com_assinatura_igual_e_reavalia_quando_muda(sessoes, config):
    configurar(sessoes)
    _, [a] = pares(sessoes)
    sv, t, _ = servico(sessoes, config, [veredito(), veredito(False, 80, "outro")])
    sv.ciclo()
    assert sv.ciclo() == 0 and len(t.pedidos) == 1
    with sessoes() as s, s.begin():
        s.get(AnuncioAmazon, a).titulo = "Título novo"
    assert sv.ciclo() == 1
    [av] = avaliacoes(sessoes)
    assert av.mesmo_produto is False and av.motivo == "outro"


def test_automatico_respeita_os_limites(sessoes, config):
    configurar(sessoes, automatico=True, confianca_confirmar=90, confianca_ignorar=85)
    _, ids = pares(sessoes, 4)
    sv, _, _ = servico(sessoes, config, [veredito(True, 90), veredito(True, 89), veredito(False, 85), veredito(False, 84)])
    assert sv.ciclo() == 4
    por_anuncio = {av.anuncio_id: av for av in avaliacoes(sessoes)}
    # ordem do ciclo: mais recentes primeiro; todos têm o mesmo visto_ultimo_em, desempate por id
    esperado = dict(zip(ids, [StatusCasamento.CONFIRMADO, StatusCasamento.PENDENTE, StatusCasamento.IGNORADO, StatusCasamento.PENDENTE]))
    for anuncio_id, situacao in esperado.items():
        assert status_de(sessoes, anuncio_id) is situacao
        assert (por_anuncio[anuncio_id].aplicada_em is not None) == (situacao is not StatusCasamento.PENDENTE)


def test_decisao_humana_durante_a_chamada_vence(sessoes, config):
    configurar(sessoes, automatico=True)
    p_id, [a] = pares(sessoes)
    with sessoes() as s, s.begin():
        outro_id = criar_produto(s, "p2").id

    class TransporteQueDecide(TransporteFake):
        def enviar(self, pedido):
            with sessoes() as s, s.begin():
                repo_amz.confirmar_casamento(s, a, outro_id, T0)  # usuário troca o produto no meio
            return super().enviar(pedido)

    t = TransporteQueDecide([veredito(False, 99)])
    sv = ServicoCasador(sessoes, t, config.model_copy(update={"openai_api_key": "k"}), NotificadorFake(),
                        cliente_http=sem_rede(), relogio=lambda: T0)
    sv.ciclo()
    with sessoes() as s:
        anuncio = s.get(AnuncioAmazon, a)
        assert anuncio.status_casamento is StatusCasamento.CONFIRMADO and anuncio.produto_id == outro_id
    [av] = avaliacoes(sessoes)
    assert av.produto_id == p_id and av.aplicada_em is None


def test_desfeito_pelo_usuario_nao_e_reaplicado(sessoes, config):
    configurar(sessoes, automatico=True)
    _, [a] = pares(sessoes)
    sv, _, _ = servico(sessoes, config, [veredito(True, 99), veredito(True, 99)])
    sv.ciclo()
    assert status_de(sessoes, a) is StatusCasamento.CONFIRMADO
    with sessoes() as s, s.begin():
        repo_amz.desfazer_casamento(s, a, T0)
        s.get(AnuncioAmazon, a).titulo = "Título novo"  # força reavaliação
    assert sv.ciclo() == 1
    assert status_de(sessoes, a) is StatusCasamento.PENDENTE


def test_resposta_fora_do_formato_nao_grava_e_volta(sessoes, config):
    configurar(sessoes)
    pares(sessoes)
    ruim = Bruta(json.dumps({"mesmo_produto": True, "confianca": 150, "motivo": "x"}), 10, 1)
    sv, t, _ = servico(sessoes, config, [ruim, veredito()])
    sv.ciclo()
    assert avaliacoes(sessoes) == []
    with sessoes() as s:
        assert [c.ok for c in s.scalars(select(ChamadaIA))] == [True]  # a chamada saiu; o formato é do casador
    sv.ciclo()
    assert len(avaliacoes(sessoes)) == 1


def test_tres_erros_seguidos_encerram_o_ciclo(sessoes, config):
    configurar(sessoes)
    pares(sessoes, 5)
    sv, t, _ = servico(sessoes, config, [ErroIA("OpenAI 500")] * 3)
    assert sv.ciclo() == 0 and len(t.pedidos) == 3


def test_chave_invalida_pausa_e_avisa(sessoes, config):
    configurar(sessoes)
    pares(sessoes, 2)
    sv, t, n = servico(sessoes, config, [ChaveInvalida("chave recusada pela OpenAI (401)")])
    sv.ciclo()
    with sessoes() as s:
        estado = repo.obter_estado(s, coletor=COLETOR_CASADOR)
    assert estado.estado is EstadoColetorTipo.PAUSADO and "401" in estado.motivo
    assert len(t.pedidos) == 1 and n.mensagens[0][0] is Destino.ADMIN and "401" in n.mensagens[0][1]


def test_sem_orcamento_para_e_avisa_uma_vez_por_dia(sessoes, config):
    configurar(sessoes, max_chamadas_dia=1)
    pares(sessoes, 3)
    sv, t, n = servico(sessoes, config, [veredito()])
    assert sv.ciclo() == 1 and len(t.pedidos) == 1
    sv.ciclo()
    assert len(n.mensagens) == 1 and "chamadas" in n.mensagens[0][1]
    # dia seguinte: libera e avisa de novo só se estourar de novo
    sv2, t2, n2 = servico(sessoes, config, [veredito()], agora=T0 + timedelta(days=1))
    sv2._avisos_orcamento = sv._avisos_orcamento
    assert sv2.ciclo() == 1


def test_imagens_vao_na_pergunta(sessoes, config):
    import base64
    import io

    from PIL import Image

    saida = io.BytesIO()
    Image.new("RGB", (10, 10)).save(saida, "PNG")
    cliente = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=saida.getvalue())))
    configurar(sessoes)
    p_id, [a] = pares(sessoes)
    with sessoes() as s, s.begin():
        s.get(AnuncioAmazon, a).imagem_url = "https://img/a.jpg"
        s.get(ProdutoLiga, p_id).imagem_url = "https://img/p.jpg"
    sv, t, _ = servico(sessoes, config, [veredito()], cliente_http=cliente)
    sv.ciclo()
    assert len(t.pedidos[0].imagens) == 2 and all(base64.b64decode(i) for i in t.pedidos[0].imagens)
    assert avaliacoes(sessoes)[0].sem_imagem is False


def test_lote_limita_o_ciclo(sessoes, config):
    configurar(sessoes, lote=2)
    pares(sessoes, 5)
    sv, t, _ = servico(sessoes, config, [veredito()] * 5)
    assert sv.ciclo() == 2


def test_assinatura_gravada_e_a_do_par(sessoes, config):
    configurar(sessoes)
    p_id, [a] = pares(sessoes)
    sv, _, _ = servico(sessoes, config, [veredito()])
    sv.ciclo()
    with sessoes() as s:
        assert avaliacoes(sessoes)[0].assinatura == assinatura(s.get(AnuncioAmazon, a), s.get(ProdutoLiga, p_id))
```

(`_avisos_orcamento` é o conjunto em memória das chaves de período já avisadas — `"dia:2026-10-13"` ou `"mes:2026-10"`; o teste o reaproveita para simular o mesmo processo no dia seguinte.)

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/casador -q`
Expected: FAIL (ImportError).

- [ ] **Step 4: `pergunta.py`**

```python
"""A pergunta "é o mesmo produto?" para a IA: texto, formato da resposta, assinatura dos dados e leitura."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.db.models import AnuncioAmazon, ProdutoLiga
from tcg_sniper.db.repositorio import agora_utc
from tcg_sniper.formatacao import formatar_brl
from tcg_sniper.ia.cliente import perguntar
from tcg_sniper.ia.imagens import preparar
from tcg_sniper.ia.modelos import ErroIA, RespostaIA, Transporte

NOME_FORMATO = "veredito_casamento"
MOTIVO_MAX = 200

INSTRUCOES = """Você compara um produto selado de Magic: The Gathering vendido na LigaMagic com um anúncio da Amazon Brasil.
Responda se o anúncio é exatamente o mesmo item lacrado do produto da LigaMagic.
É o mesmo produto só se coincidirem: o jogo, a edição/coleção, o tipo (booster avulso, caixa de boosters, bundle, deck, kit, colecionador etc.), a versão do booster (draft, set, play, collector), o idioma quando informado e a quantidade.
É outro produto: carta avulsa, acessório (sleeve, deck box, playmat), outra edição, outro tipo, outra quantidade ou lote com vários itens.
Use as imagens, quando houver, para conferir embalagem, edição e tipo. Preço muito abaixo do esperado é pista de item diferente, não prova.
A confiança é um inteiro de 0 a 100 sobre a sua resposta. O motivo é uma frase curta em português (até 200 caracteres) com o que decidiu."""

FORMATO = {
    "type": "object",
    "properties": {
        "mesmo_produto": {"type": "boolean"},
        "confianca": {"type": "integer"},
        "motivo": {"type": "string"},
    },
    "required": ["mesmo_produto", "confianca", "motivo"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Veredito:
    mesmo_produto: bool
    confianca: int
    motivo: str


def _preco(valor: Decimal | None) -> str:
    return formatar_brl(valor) if valor is not None else "sem preço"


def texto_pergunta(anuncio: AnuncioAmazon, produto: ProdutoLiga, preco_liga: Decimal | None, preco_amazon: Decimal | None) -> str:
    linhas = [
        "Produto da LigaMagic:",
        f"- nome: {produto.nome}",
        f"- nome em inglês: {produto.nome_en or '(não informado)'}",
        f"- edição: {produto.edicao or '(não informada)'}",
        f"- tipo: {produto.tipo or '(não informado)'}",
        f"- idioma: {produto.idioma or '(não informado)'}",
        f"- menor preço na LigaMagic: {_preco(preco_liga)}",
        "",
        "Anúncio da Amazon:",
        f"- título: {anuncio.titulo}",
        f"- opção da variação: {anuncio.variacao or '(nenhuma)'}",
        f"- preço: {_preco(preco_amazon)}",
        "",
        "Imagens, quando houver: primeiro a da LigaMagic, depois a da Amazon.",
    ]
    return "\n".join(linhas)


def assinatura(anuncio: AnuncioAmazon, produto: ProdutoLiga) -> str:
    """Hash dos dados que decidem a resposta: mudou, o par é reavaliado."""
    dados = [anuncio.titulo, anuncio.variacao, anuncio.imagem_url, produto.nome, produto.nome_en,
             produto.edicao, produto.tipo, produto.idioma, produto.imagem_url]
    return hashlib.sha256(json.dumps(dados, ensure_ascii=False).encode()).hexdigest()


def ler_veredito(dados: dict) -> Veredito:
    mesmo, confianca, motivo = dados.get("mesmo_produto"), dados.get("confianca"), dados.get("motivo")
    if not isinstance(mesmo, bool):
        raise ErroIA("resposta sem mesmo_produto booleano")
    if not isinstance(confianca, int) or isinstance(confianca, bool) or not 0 <= confianca <= 100:
        raise ErroIA("confiança fora de 0 a 100")
    if not isinstance(motivo, str) or not motivo.strip():
        raise ErroIA("resposta sem motivo")
    return Veredito(mesmo, confianca, motivo.strip()[:MOTIVO_MAX])


def avaliar_par(
    sessoes: sessionmaker[Session],
    transporte: Transporte,
    cliente_http: httpx.Client,
    anuncio: AnuncioAmazon,
    produto: ProdutoLiga,
    preco_liga: Decimal | None,
    preco_amazon: Decimal | None,
    *,
    finalidade: str,
    zona: ZoneInfo,
    modelo: str | None = None,
    relogio: Callable[[], datetime] = agora_utc,
) -> tuple[Veredito, RespostaIA, bool]:
    """Prepara as imagens, pergunta e lê o veredito. Devolve também se faltou alguma imagem."""
    imagens = [preparar(cliente_http, produto.imagem_url), preparar(cliente_http, anuncio.imagem_url)]
    prontas = [i for i in imagens if i is not None]
    resposta = perguntar(
        sessoes, transporte, finalidade=finalidade, instrucoes=INSTRUCOES,
        texto=texto_pergunta(anuncio, produto, preco_liga, preco_amazon), imagens=prontas,
        nome_formato=NOME_FORMATO, formato=FORMATO, zona=zona, modelo=modelo, relogio=relogio,
    )
    return ler_veredito(resposta.dados), resposta, len(prontas) < 2
```

(`formatar_brl` é a mesma função do filtro `brl` do admin; se a saída dela para `Decimal("899.90")` não for `R$ 899,90`, ajuste o texto esperado no teste para a saída real.)

- [ ] **Step 5: `servico.py`**

```python
"""Serviço `casador`: avalia com a IA os anúncios pendentes e, com o automático ligado, decide os claros."""

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.casador.pergunta import assinatura, avaliar_par
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import COLETOR_CASADOR, AnuncioAmazon, EstadoColetorTipo, StatusCasamento
from tcg_sniper.ia.modelos import ChaveInvalida, ErroIA, SemOrcamento, Transporte
from tcg_sniper.notificador.base import Destino, Notificador

log = logging.getLogger(__name__)

PASSO_S = 30  # de quanto em quanto tempo olha se pediram "Rodar agora"
FALHAS_SEGUIDAS_MAX = 3
TIMEOUT_IMAGEM_S = 15


class ServicoCasador:
    def __init__(
        self,
        sessoes: sessionmaker[Session],
        transporte: Transporte | None,
        config_env: Config,
        notificador: Notificador,
        cliente_http: httpx.Client | None = None,
        relogio: Callable[[], datetime] | None = None,
        dormir: Callable[[float], None] | None = None,
    ):
        self._sessoes = sessoes
        self._transporte = transporte
        self._config_env = config_env
        self._notificador = notificador
        self._http = cliente_http or httpx.Client(timeout=TIMEOUT_IMAGEM_S, headers={"User-Agent": "Mozilla/5.0"})
        self._relogio = relogio or repo.agora_utc
        self._dormir = dormir
        self._parar = threading.Event()
        self._avisos_orcamento: set[str] = set()

    def parar(self) -> None:
        self._parar.set()

    def ciclo(self) -> int:
        """Uma rodada: até `lote` pares sem avaliação ou com dados mudados. Devolve quantos avaliou."""
        if self._transporte is None:
            return 0
        agora = self._relogio()
        with self._sessoes() as s, s.begin():
            estado = repo.obter_estado(s, agora, COLETOR_CASADOR)
            cfg = repo_ia.obter_config_ia(s)
            if estado.estado is not EstadoColetorTipo.ATIVO or not cfg.ligado:
                return 0
            zona = ZoneInfo(repo.obter_config_geral(s, self._config_env).fuso)
            lote, automatico = cfg.lote, cfg.automatico
            limites = (cfg.confianca_confirmar, cfg.confianca_ignorar)
            pares = [
                p for p in repo_ia.pares_pendentes(s)
                if p.avaliacao is None or p.avaliacao.assinatura != assinatura(p.anuncio, p.produto)
            ][:lote]
            for p in pares:
                s.expunge(p.anuncio)
                s.expunge(p.produto)
        avaliados = falhas = 0
        for par in pares:
            if self._parar.is_set():
                break
            try:
                veredito, resposta, sem_imagem = avaliar_par(
                    self._sessoes, self._transporte, self._http, par.anuncio, par.produto, par.preco_liga,
                    par.preco_amazon, finalidade="casamento", zona=zona, relogio=self._relogio,
                )
            except SemOrcamento as erro:
                self._avisar_orcamento(str(erro), zona)
                break
            except ChaveInvalida as erro:
                with self._sessoes() as s, s.begin():
                    repo.pausar(s, str(erro), self._relogio(), COLETOR_CASADOR)
                self._notificador.enviar(Destino.ADMIN, f"⚠️ Casador (IA) pausado: {erro}. Corrija e clique em Retomar em Serviços.")
                log.error("casador pausado: %s", erro)
                break
            except ErroIA as erro:
                falhas += 1
                log.warning("IA falhou no anúncio %s: %s", par.anuncio.asin, erro)
                if falhas >= FALHAS_SEGUIDAS_MAX:
                    break
                continue
            falhas = 0
            self._gravar(par, veredito, resposta, sem_imagem, automatico, limites)
            avaliados += 1
        return avaliados

    def _gravar(self, par, veredito, resposta, sem_imagem, automatico, limites) -> None:
        agora = self._relogio()
        confirmar, ignorar = limites
        with self._sessoes() as s, s.begin():
            anterior = repo_ia.avaliacoes_dos_pares(s, [(par.anuncio.id, par.produto.id)]).get((par.anuncio.id, par.produto.id))
            ja_aplicada = anterior is not None and anterior.aplicada_em is not None
            av = repo_ia.gravar_avaliacao(
                s, anuncio_id=par.anuncio.id, produto_id=par.produto.id, mesmo_produto=veredito.mesmo_produto,
                confianca=veredito.confianca, motivo=veredito.motivo, modelo=resposta.modelo,
                assinatura=assinatura(par.anuncio, par.produto), sem_imagem=sem_imagem,
                chamada_id=resposta.chamada_id, agora=agora,
            )
            if not automatico or ja_aplicada:
                return
            anuncio = s.get(AnuncioAmazon, par.anuncio.id, with_for_update=True, populate_existing=True)
            if anuncio.status_casamento is not StatusCasamento.PENDENTE or anuncio.produto_id != par.produto.id:
                return  # o usuário decidiu enquanto a IA respondia
            if veredito.mesmo_produto and veredito.confianca >= confirmar:
                repo_amz.confirmar_casamento(s, anuncio.id, par.produto.id, agora)
            elif not veredito.mesmo_produto and veredito.confianca >= ignorar:
                repo_amz.ignorar_anuncio(s, anuncio.id, agora)
            else:
                return
            av.aplicada_em = agora

    def _avisar_orcamento(self, motivo: str, zona) -> None:
        local = self._relogio().astimezone(zona)
        chave = f"mes:{local:%Y-%m}" if "mensal" in motivo else f"dia:{local:%Y-%m-%d}"
        log.warning("casador sem orçamento: %s", motivo)
        if chave in self._avisos_orcamento:
            return
        self._avisos_orcamento.add(chave)
        self._notificador.enviar(Destino.ADMIN, f"⚠️ Casador (IA) parado: {motivo}. Volta sozinho no próximo período ou ao subir o teto em Configurações → IA.")

    def rodar(self) -> None:
        log.info("casador iniciado")
        if self._transporte is None:
            log.warning("OPENAI_API_KEY ausente no .env: o casador não chama a IA")
        proxima = self._relogio()
        while not self._parar.is_set():
            agora = self._relogio()
            try:
                with self._sessoes() as s, s.begin():
                    pedida = repo.consumir_solicitacao(s, agora, COLETOR_CASADOR)
                    intervalo = timedelta(minutes=repo_ia.obter_config_ia(s).intervalo_min)
                if pedida or agora >= proxima:
                    self.ciclo()
                    proxima = self._relogio() + intervalo
            except Exception:
                log.exception("erro no ciclo do casador; tenta de novo no próximo passo")
            if self._dormir is not None:
                self._dormir(PASSO_S)
            else:
                self._parar.wait(PASSO_S)
        log.info("casador encerrado")
```

`ConfigGeral.fuso` é o fuso efetivo, o mesmo que os outros serviços usam. `retomar` deixa `execucao_solicitada=True`, então o casador roda logo depois de Retomar (desejado).

O teste `test_sem_orcamento_para_e_avisa_uma_vez_por_dia` exige que o primeiro ciclo avalie 1 anúncio e pare no segundo (sem pedido extra) e que o segundo ciclo não repita a mensagem.

- [ ] **Step 6: CLI, compose e .env.example**

`cli.py`: `sub.add_parser("casador", help="avalia com a IA os anúncios pendentes da Amazon")` e:

```python
    elif args.comando == "casador":
        from tcg_sniper.casador.servico import ServicoCasador
        from tcg_sniper.ia.transporte_openai import TransporteOpenAI
        from tcg_sniper.notificador import criar_notificador

        chave = (config.openai_api_key or "").strip()
        casador = ServicoCasador(sessoes, TransporteOpenAI(chave) if chave else None, config, criar_notificador(config, sessoes))
        signal.signal(signal.SIGTERM, lambda _signum, _frame: casador.parar())
        casador.rodar()
```

`docker-compose.yml`, depois do `notificador`:

```yaml
  casador:
    <<: *app
    command: tcg-sniper casador
    stop_grace_period: 90s
    depends_on:
      migrate:
        condition: service_completed_successfully
```

`.env.example`: `OPENAI_API_KEY=` com o comentário `# chave da API da OpenAI para o casador (IA); vazia, a IA não roda`, no mesmo estilo das outras linhas.

`tests/test_cli.py`: acrescente um teste no padrão dos existentes conferindo que `main(["casador", "--help"])` sai com código 0 (ou o padrão equivalente usado ali).

- [ ] **Step 7: Rodar**

Run: `uv run pytest tests/casador tests/test_cli.py -q && uv run pytest -q && uv run ruff check .`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/tcg_sniper/casador src/tcg_sniper/cli.py docker-compose.yml .env.example tests/casador tests/test_cli.py
git commit -m "feat: casador service that asks the AI about pending listings (suggestions and optional automatic decisions)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Comando de avaliação e README

**Files:**
- Create: `src/tcg_sniper/casador/avaliacao.py`
- Modify: `src/tcg_sniper/cli.py` (subcomando `ia avaliar`)
- Modify: `README.md` (seção da IA)
- Test: `tests/casador/test_avaliacao.py`

**Interfaces:**
- Consumes: `casador.pergunta.avaliar_par`, `repositorio_ia.pares_decididos`, `ia.modelos.*`.
- Produces:
  - `avaliacao.Erro(asin, titulo, produto, esperado_mesmo: bool, veredito: Veredito)`
  - `avaliacao.ResultadoModelo(modelo, total, acertos, falsos_sim, falsos_nao, falhas, custo_usd, faixas: dict[str, tuple[int, int]], erros: list[Erro])` — `faixas` = rótulo → (acertos, total) para `"90+"`, `"75–89"`, `"50–74"`, `"<50"`
  - `avaliacao.avaliar(sessoes, transporte, cliente_http, modelos: Sequence[str], limite: int | None, zona, relogio) -> list[ResultadoModelo]`
  - `avaliacao.relatorio_markdown(resultados, gerado_em: datetime) -> str`

- [ ] **Step 1: Testes (falham)**

Create `tests/casador/test_avaliacao.py`:

```python
import json
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from fakes import T0, TransporteFake, criar_anuncio, criar_produto
from sqlalchemy import select

from tcg_sniper.casador.avaliacao import avaliar, relatorio_markdown
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import AnuncioAmazon, AvaliacaoIA, ChamadaIA, StatusCasamento
from tcg_sniper.ia.modelos import Bruta, ErroIA, SemOrcamento

SP = ZoneInfo("America/Sao_Paulo")


def v(mesmo, confianca):
    return Bruta(json.dumps({"mesmo_produto": mesmo, "confianca": confianca, "motivo": f"m{confianca}"}), 1000, 100)


def test_relatorio_conta_acertos_erros_e_faixas(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Caixa Alfa")
        criar_anuncio(s, "B1", produto=p, status=StatusCasamento.CONFIRMADO)
        criar_anuncio(s, "B2", produto=p, status=StatusCasamento.IGNORADO)
        criar_anuncio(s, "B3", produto=p, status=StatusCasamento.IGNORADO)
        criar_anuncio(s, "B4", produto=p, status=StatusCasamento.CONFIRMADO)
    # B1 sim 95 (acerto), B2 não 80 (acerto), B3 sim 60 (falso sim), B4 erro de chamada
    t = TransporteFake([v(True, 95), v(False, 80), v(True, 60), ErroIA("OpenAI 500")])
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    [r] = avaliar(sessoes, t, http, ["gpt-5"], None, SP, lambda: T0)
    assert (r.total, r.acertos, r.falsos_sim, r.falsos_nao, r.falhas) == (3, 2, 1, 0, 1)
    assert r.faixas["90+"] == (1, 1) and r.faixas["75–89"] == (1, 1) and r.faixas["50–74"] == (0, 1)
    assert r.custo_usd == Decimal("0.006750")
    [erro] = r.erros
    assert erro.asin == "B3" and erro.esperado_mesmo is False and erro.veredito.motivo == "m60"
    md = relatorio_markdown([r], T0)
    assert "gpt-5" in md and "2 de 3" in md and "Falsos \"sim\": 1" in md and "B3" in md and "m60" in md
    with sessoes() as s:
        assert s.scalars(select(AvaliacaoIA)).all() == []
        assert {a.status_casamento for a in s.scalars(select(AnuncioAmazon))} == {StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO}
        assert {c.finalidade for c in s.scalars(select(ChamadaIA))} == {"avaliacao"}


def test_dois_modelos_e_limite(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1")
        for i in range(3):
            criar_anuncio(s, f"B{i}", produto=p, status=StatusCasamento.CONFIRMADO)
    t = TransporteFake([v(True, 99)] * 4)
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    resultados = avaliar(sessoes, t, http, ["gpt-5", "gpt-5-mini"], 2, SP, lambda: T0)
    assert [r.modelo for r in resultados] == ["gpt-5", "gpt-5-mini"]
    assert [p.modelo for p in t.pedidos] == ["gpt-5", "gpt-5", "gpt-5-mini", "gpt-5-mini"]


def test_para_sem_orcamento(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1")
        criar_anuncio(s, "B1", produto=p, status=StatusCasamento.CONFIRMADO)
        repo_ia.salvar_config_ia(s, {"max_chamadas_dia": 0}, T0)
    t = TransporteFake([])
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    [r] = avaliar(sessoes, t, http, ["gpt-5"], None, SP, lambda: T0)
    assert r.total == 0 and r.interrompida is not None and "chamadas" in r.interrompida
```

(Acrescente `interrompida: str | None` ao `ResultadoModelo`: o motivo do `SemOrcamento` quando a avaliação parou antes do fim; o relatório mostra "Interrompida: <motivo>".)

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/casador/test_avaliacao.py -q`
Expected: FAIL.

- [ ] **Step 3: Implementação**

Create `src/tcg_sniper/casador/avaliacao.py`:

```python
"""Avaliação da IA contra os casamentos já decididos pelo usuário: acerto, erros e custo, sem mudar nada."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.casador.pergunta import Veredito, avaliar_par
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.ia.modelos import ChaveInvalida, ErroIA, SemOrcamento, Transporte

FAIXAS = (("90+", 90), ("75–89", 75), ("50–74", 50), ("<50", 0))


def faixa(confianca: int) -> str:
    return next(rotulo for rotulo, minimo in FAIXAS if confianca >= minimo)


@dataclass(frozen=True)
class Erro:
    asin: str
    titulo: str
    produto: str
    esperado_mesmo: bool
    veredito: Veredito


@dataclass
class ResultadoModelo:
    modelo: str
    total: int = 0
    acertos: int = 0
    falsos_sim: int = 0
    falsos_nao: int = 0
    falhas: int = 0
    custo_usd: Decimal = Decimal(0)
    faixas: dict[str, tuple[int, int]] = field(default_factory=lambda: {rotulo: (0, 0) for rotulo, _ in FAIXAS})
    erros: list[Erro] = field(default_factory=list)
    interrompida: str | None = None


def avaliar(
    sessoes: sessionmaker[Session],
    transporte: Transporte,
    cliente_http: httpx.Client,
    modelos: Sequence[str],
    limite: int | None,
    zona: ZoneInfo,
    relogio: Callable[[], datetime],
) -> list[ResultadoModelo]:
    with sessoes() as s:
        decididos = repo_ia.pares_decididos(s, limite)
        for d in decididos:
            s.expunge(d.anuncio)
            s.expunge(d.produto)
    resultados = []
    for modelo in modelos:
        r = ResultadoModelo(modelo)
        for d in decididos:
            try:
                veredito, resposta, _ = avaliar_par(
                    sessoes, transporte, cliente_http, d.anuncio, d.produto, d.preco_liga, d.preco_amazon,
                    finalidade="avaliacao", zona=zona, modelo=modelo, relogio=relogio,
                )
            except (SemOrcamento, ChaveInvalida) as erro:
                r.interrompida = str(erro)
                break
            except ErroIA:
                r.falhas += 1
                continue
            r.total += 1
            r.custo_usd += resposta.custo_usd
            certo = veredito.mesmo_produto == d.confirmado
            acertos, total = r.faixas[faixa(veredito.confianca)]
            r.faixas[faixa(veredito.confianca)] = (acertos + certo, total + 1)
            if certo:
                r.acertos += 1
                continue
            if veredito.mesmo_produto:
                r.falsos_sim += 1
            else:
                r.falsos_nao += 1
            r.erros.append(Erro(d.anuncio.asin, d.anuncio.titulo_exibicao, d.produto.nome, d.confirmado, veredito))
        resultados.append(r)
    return resultados


def relatorio_markdown(resultados: Sequence[ResultadoModelo], gerado_em: datetime) -> str:
    linhas = [f"# Avaliação da IA no casamento ({gerado_em:%Y-%m-%d %H:%M} UTC)", ""]
    for r in resultados:
        linhas += [
            f"## {r.modelo}",
            "",
            f"- Acertos: {r.acertos} de {r.total}" + (f" ({100 * r.acertos / r.total:.0f}%)" if r.total else ""),
            f"- Falsos \"sim\": {r.falsos_sim} (a IA diria mesmo produto num anúncio que você ignorou: risco de oportunidade falsa)",
            f"- Falsos \"não\": {r.falsos_nao}",
            f"- Falhas de chamada: {r.falhas}",
            f"- Custo: US$ {r.custo_usd:.4f}" + (f" (médio US$ {r.custo_usd / r.total:.4f})" if r.total else ""),
        ]
        if r.interrompida:
            linhas.append(f"- Interrompida: {r.interrompida}")
        linhas += ["", "| Confiança | Acertos |", "|---|---|"]
        linhas += [f"| {rotulo} | {a} de {t} |" for rotulo, (a, t) in r.faixas.items()]
        if r.erros:
            linhas += ["", "### Erros", "", "| ASIN | Anúncio | Produto da Liga | Você decidiu | IA | Motivo da IA |", "|---|---|---|---|---|---|"]
            for e in r.erros:
                decidiu = "mesmo produto" if e.esperado_mesmo else "ignorado"
                ia = f"{'mesmo' if e.veredito.mesmo_produto else 'outro'} {e.veredito.confianca}%"
                linhas.append(f"| {e.asin} | {_celula(e.titulo)} | {_celula(e.produto)} | {decidiu} | {ia} | {_celula(e.veredito.motivo)} |")
        linhas.append("")
    return "\n".join(linhas)


def _celula(texto: str) -> str:
    return texto.replace("|", "/").replace("\n", " ")
```

`cli.py`: subparser `ia` com sub-subparser `avaliar`:

```python
    ia = sub.add_parser("ia", help="ferramentas da IA")
    ia_sub = ia.add_subparsers(dest="acao_ia", required=True)
    avaliar_p = ia_sub.add_parser("avaliar", help="mede a IA nos casamentos já decididos (não muda nada)")
    avaliar_p.add_argument("--modelo", action="append", required=True, help="pode repetir para comparar modelos")
    avaliar_p.add_argument("--limite", type=int, default=None, help="no máximo N anúncios")
```

e no despacho:

```python
    elif args.comando == "ia":
        import httpx

        from tcg_sniper.casador.avaliacao import avaliar, relatorio_markdown
        from tcg_sniper.db import repositorio as repo
        from tcg_sniper.ia.transporte_openai import TransporteOpenAI

        chave = (config.openai_api_key or "").strip()
        if not chave:
            raise SystemExit("OPENAI_API_KEY ausente no .env")
        with sessoes() as s:
            zona = ZoneInfo(repo.obter_config_geral(s, config).fuso)
        agora = repo.agora_utc()
        with httpx.Client(timeout=15, headers={"User-Agent": "Mozilla/5.0"}) as http:
            resultados = avaliar(sessoes, TransporteOpenAI(chave), http, args.modelo, args.limite, zona, repo.agora_utc)
        destino = config.dir_dados / f"avaliacao-ia-{agora:%Y-%m-%d-%H%M}.md"
        destino.write_text(relatorio_markdown(resultados, agora), encoding="utf-8")
        print(f"relatório em {destino}")
```

(`ZoneInfo` importado de `zoneinfo` no topo do `cli.py`.)

- [ ] **Step 4: README**

Nova seção "Casamento com IA", depois da seção da Amazon, cobrindo em frases curtas: o que o casador faz (avalia pendentes com texto e imagens, mostra selo e motivo em Casamentos); onde configurar (Configurações → IA: ligar, modelo, preços, tetos por dia/mês e chamadas por dia, automático e confianças); a chave (`OPENAI_API_KEY` no `.env`, reiniciar o `casador` depois de mudar: `docker compose up -d casador`); a avaliação antes de ligar o automático:

```
docker compose exec casador tcg-sniper ia avaliar --modelo gpt-5 --modelo gpt-5-mini
```

(o relatório sai em `dados/avaliacao-ia-<data>.md`); e o que acontece em erro (chave recusada pausa o casador e avisa no WhatsApp; teto atingido para até o próximo dia ou mês). Acrescente `casador` à lista de serviços do compose, onde o README a tiver.

- [ ] **Step 5: Rodar**

Run: `uv run pytest -q && uv run ruff check .`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/tcg_sniper/casador/avaliacao.py src/tcg_sniper/cli.py README.md tests/casador/test_avaliacao.py
git commit -m "feat: ia avaliar command (AI accuracy and cost against decided matches) and README

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Implantação (depois do merge, com ok do usuário)

1. Backup: `docker compose exec -T postgres pg_dump -U tcg -Fc tcg > dados/backups/tcg-antes-ia-<data>.dump`.
2. `docker compose up -d --build migrate admin coletor-liga coletor-amazon casador`.
3. Conferir: `alembic_version = e7a4c1d9b3f2`; `casador` rodando com "IA desligada" (log "casador iniciado"); Configurações → IA abre; depois da próxima coleta da Liga e de alguns ciclos da Amazon, `select count(imagem_url) from produto_liga` e `from anuncio_amazon` acima de zero (confere os seletores reais `#featuredImage`, `img.s-image` e `#landingImage`).
4. O usuário põe `OPENAI_API_KEY` no `.env` e roda `docker compose up -d casador`; depois `docker compose exec casador tcg-sniper ia avaliar --modelo gpt-5`.
