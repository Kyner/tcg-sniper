# Monitor da Amazon com prioridade por grupo — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O monitor lê primeiro os nunca lidos, depois a fila rápida (oportunidades abertas + desconto ≥ piso do "quase lá") a cada `monitor_intervalo_min`, depois os esgotados na Liga a cada `monitor_esgotado_dias`, e o resto com a sobra; painel e avisos contam por grupo; o Catálogo da gestão ganha a lista "Esgotado na Liga · analisar".

**Architecture:** Uma expressão SQL de grupo em `repositorio_amazon.py` (sobre `_confirmados_ativos` + `PrecoAtualLiga` + oportunidade aberta) alimenta `proximo_do_monitor`, os ids da volta e `situacao_monitor`. A varredura passa a fazer a volta só com nunca lidos + rápidos. O painel do admin antigo usa as contagens novas. O filtro "preço na Liga" do Catálogo (consulta neutra, API e front) vira uma escolha de três valores.

**Tech Stack:** Python 3 + SQLAlchemy 2 + Alembic + Postgres; FastAPI; React + DaisyUI 5 + Vitest.

**Spec:** `docs/superpowers/specs/2026-10-22-monitor-prioridade-design.md`

## Global Constraints

- Textos em português; assunto dos commits em inglês `tipo: descrição`; **sem** `Co-Authored-By`, `Claude-Session` ou "Generated with".
- Grupo do anúncio = **só preço**: `preco_atual_amazon.preco` contra `preco_atual_liga.preco_a_partir`, regra de `motor.atinge_desconto` (`amazon*100 <= liga*(100-piso)`, ambos > 0), sem filtro de vendedor nem idade da Liga.
- Oportunidade aberta (`oportunidade.fechada_em IS NULL` no anúncio) é **sempre** grupo rápido.
- Esgotado = preço na Amazon e `preco_a_partir` nulo (ou sem linha em `preco_atual_liga`).
- Lento não é relido antes de `monitor_intervalo_min` (piso).
- `monitor_esgotado_dias`: padrão 7, de 1 a 30; `config_amazon` tem um registro só.
- Só componentes do DaisyUI 5 com classes literais; mobile first.
- Testes só no Postgres de teste (127.0.0.1:5433, bancos `tcg_test*`).
- Histórico de preço nunca é apagado.

## Review Focus

1. **Anúncio que cruza a linha entre leituras** (990 → 850 contra Liga 1000) muda do lento para o rápido na leitura seguinte, e volta ao lento quando sobe. Teste na Task 2.
2. **Oportunidade aberta com a Liga zerando o preço** (vira "esgotado" pelo preço) continua no rápido até fechar. Teste na Task 2.
3. **Sem nenhum rápido nem nunca lido** a varredura não abre volta e não manda "rodada concluída" em laço. Teste na Task 3.
4. **Capacidade sobrando à noite/com poucos anúncios:** lento não é relido antes do intervalo (sem martelar a Amazon). Teste na Task 2.
5. **Lote do Catálogo com o filtro "esgotado"** aplica exatamente aos produtos que a lista mostra (mesma consulta). Teste na Task 5.

---

### Task 1: Campo `monitor_esgotado_dias`

**Files:**
- Create: `src/tcg_sniper/db/migrations/versions/c5e1a8d3f7b2_monitor_esgotado_dias.py` (revises `a1c4e7b9d2f6`)
- Modify: `src/tcg_sniper/db/models.py` (`LIMITES_CONFIG_AMAZON` :469-489 `(1, 30)`, `PADROES_CONFIG_AMAZON` :491-516 `7`, coluna em `ConfigAmazon` antes de `monitor_ligado` :561)
- Modify: `src/tcg_sniper/coletor_amazon/config.py` (`CAMPOS` depois de `monitor_max_paginas_hora`; `ROTULOS["monitor_esgotado_dias"] = "Esgotado na Liga: ler a cada (dias)"`; `ROTULOS["monitor_intervalo_min"] = "Fila rápida: ler a cada (min)"`; `EXPLICACOES` dos três campos abaixo)
- Test: `tests/db/test_migracao_monitor_esgotado.py`; ajustar `tests/admin/test_admin_amazon.py:73-101` e `tests/admin/test_admin_config_tela.py:84-109` (formulários completos)

**Interfaces:**
- Produces: `ConfigAmazon.monitor_esgotado_dias: int`.

Textos (`EXPLICACOES`):
- `monitor_intervalo_min`: "Fila rápida: oportunidades abertas e anúncios com desconto a partir do \"quase lá\" são relidos a cada tantos minutos. Os demais usam a sobra do teto e nunca antes deste intervalo."
- `monitor_esgotado_dias`: "Anúncio com preço na Amazon de produto sem vendedor na Liga (\"a partir de\" vazio): relido uma vez a cada tantos dias. Aparece em Catálogo → esgotado na Liga."
- `quase_oportunidade_min_pct` (acrescentar ao texto atual): "Também decide a fila rápida do monitor."

- [ ] **Step 1: Teste da migração** (molde `tests/db/test_migracao_quase_oportunidade.py`): depois do upgrade a coluna existe com 7 e o CHECK `ck_config_amazon_monitor_esgotado_dias` (`BETWEEN 1 AND 30`); downgrade remove os dois; `upgrade head` no `finally`.
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/db/test_migracao_monitor_esgotado.py tests/coletor_amazon/test_config_amazon.py -q`.
- [ ] **Step 3: Implementar** (migração com `server_default="7"`, `nullable=False`, `create_check_constraint`; modelo; config; formulários dos testes).
- [ ] **Step 4: Rodar** `uv run pytest tests/db tests/coletor_amazon tests/admin -q` → PASS.
- [ ] **Step 5: Commit** `feat: setting for how often to reread listings sold out on Liga`.

### Task 2: Grupos no repositório do monitor

**Files:**
- Modify: `src/tcg_sniper/db/repositorio_amazon.py:494-547`
- Test: `tests/db/test_repositorio_monitor.py` (ajustar `test_situacao_do_monitor` :87-95 e chamadas de `proximo_do_monitor`/`situacao_monitor`), `tests/db/test_regressao_casamento_por_par.py:158`

**Interfaces:**
- Produces:
  - `class GrupoMonitor(StrEnum)`: `NUNCA_LIDO = "nunca_lido"`, `RAPIDO = "rapido"`, `ESGOTADO = "esgotado"`, `LENTO = "lento"`.
  - `_grupo_do_monitor(piso_pct: int) -> ColumnElement[str]`: `case` sobre a consulta de `_confirmados_ativos` + `outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)`: leitura nula ⇒ NUNCA_LIDO; existe oportunidade aberta do anúncio ⇒ RAPIDO; preço Amazon > 0 e Liga > 0 e `amazon*100 <= liga*(100-piso)` ⇒ RAPIDO; Liga nula ⇒ ESGOTADO; senão LENTO.
  - `@dataclass(frozen=True) class ProximoMonitor: anuncio_id: int; asin: str; grupo: GrupoMonitor`.
  - `proximo_do_monitor(s, agora, cfg: ConfigAmazon, excluir: Collection[int] = ()) -> ProximoMonitor | None` — **troca** o parâmetro `intervalo_min` por `cfg` (usa `monitor_intervalo_min`, `monitor_esgotado_dias`, `quase_oportunidade_min_pct`). Ordem: NUNCA_LIDO, RAPIDO vencido, ESGOTADO vencido, LENTO vencido; dentro de cada grupo a leitura mais antiga primeiro, depois `AnuncioAmazon.id`.
  - `ids_da_volta(s, piso_pct: int) -> set[int]` — **substitui** `ids_do_monitor`: só NUNCA_LIDO + RAPIDO.
  - `SituacaoMonitor` passa a: `confirmados, nunca_lidos, rapidos, lentos, esgotados, vencidos` (nunca lidos + rápidos vencidos), `mais_antiga_rapida: datetime | None` (leitura mais antiga entre os rápidos), `mais_antiga_lenta: datetime | None`, `ultima: datetime | None`.
  - `situacao_monitor(s, agora, cfg: ConfigAmazon) -> SituacaoMonitor` — **troca** `intervalo_min` por `cfg`.

- [ ] **Step 1: Testes** (Liga 1000 nos helpers `confirmado`):
  - `test_grupos_do_monitor`: nunca lido; lido a 850 (15%) ⇒ rápido; lido a 990 ⇒ lento; lido a 1200 ⇒ lento; Liga sem preço ⇒ esgotado.
  - `test_oportunidade_aberta_fica_no_rapido_mesmo_esgotado` (com `fakes_oportunidades.criar_oportunidade` e Liga `None`).
  - `test_piso_do_quase_la_muda_o_grupo` (piso 20 ⇒ o de 15% vira lento).
  - `test_ordem_nunca_lido_rapido_esgotado_lento` (todos vencidos).
  - `test_lento_nao_e_relido_antes_do_intervalo` (lido há 10 min com intervalo 15 ⇒ `None`).
  - `test_esgotado_so_vence_depois_dos_dias` (lido há 6 dias ⇒ não; 7 dias ⇒ sim).
  - `test_cruzar_a_linha_muda_de_grupo` (990 ⇒ lento; nova leitura 850 ⇒ rápido; 990 de novo ⇒ lento).
  - `test_situacao_do_monitor_por_grupo` (contagens e `mais_antiga_rapida`).
  - `test_ids_da_volta_so_nunca_lidos_e_rapidos`.
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/db/test_repositorio_monitor.py -q`.
- [ ] **Step 3: Implementar**; atualizar os chamadores de `proximo_do_monitor`/`ids_do_monitor`/`situacao_monitor` só o necessário para compilar (`varredura_monitor.py:226-227` passa `cfg` e usa `.anuncio_id/.asin`; `consultas_painel.py:195,488` e `app.py:365` passam `cfg_amazon`) — a lógica nova deles vem nas Tasks 3 e 4.
- [ ] **Step 4: Rodar** `uv run pytest tests/db -q` → PASS. Rodar `uv run pytest -q`: só podem falhar testes de `tests/coletor_amazon/test_varredura_monitor.py` e de `tests/admin/` ligados à rodada, ao card e aos avisos do monitor (consertados nas Tasks 3 e 4); listar os que falharam no relatório. Qualquer outra falha bloqueia o commit.
- [ ] **Step 5: Commit** `feat: monitor reading groups by price proximity`.

### Task 3: Volta do monitor com a fila rápida

**Files:**
- Modify: `src/tcg_sniper/coletor_amazon/varredura_monitor.py:19-24, 79-88, 183-235, 414-417`
- Test: `tests/coletor_amazon/test_varredura_monitor.py` (:589-860), `tests/fakes_varredura.py:72-85`

**Interfaces:**
- Consumes: Task 2 (`ProximoMonitor`, `GrupoMonitor`, `ids_da_volta`).
- Produces: `_Rodada` ganha `lentos: int = 0` e `esgotados: int = 0`; `_monitorar(proximo: ProximoMonitor, cfg)` conta `lidos` só para NUNCA_LIDO/RAPIDO e `lentos`/`esgotados` para os outros; `faltam` = `ids_da_volta`. Sem membros na foto (`ids_da_volta` vazio) não abre volta. O aviso `AMAZON_MONITOR_CONCLUIDO` ganha a linha "Fora da fila rápida: N lentos · M esgotados lidos" quando algum > 0.

- [ ] **Step 1: Ajustar os testes da rodada** que liam a "R$ 990,00" contra Liga 1000 para ler a 850 (15%, fila rápida), mantendo o que cada um prova; acrescentar:
  - `test_volta_so_com_a_fila_rapida` (um rápido e um lento: a volta fecha depois do rápido; o aviso traz "1 lentos").
  - `test_sem_fila_rapida_nao_abre_volta_nem_avisa` (só lentos lidos: nenhum `AMAZON_MONITOR_CONCLUIDO`, mesmo com várias passadas).
  - `test_monitor_le_rapido_antes_do_lento`.
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/coletor_amazon/test_varredura_monitor.py -q`.
- [ ] **Step 3: Implementar**; docstring do módulo (:19-24) explica os grupos e a volta.
- [ ] **Step 4: Rodar** `uv run pytest tests/coletor_amazon -q` → PASS.
- [ ] **Step 5: Commit** `feat: monitor round covers the fast queue only`.

### Task 4: Painel, avisos e card do monitor

**Files:**
- Modify: `src/tcg_sniper/admin/consultas_painel.py:190-208, 263-284, 458-520`, `src/tcg_sniper/admin/app.py:339-380`, `src/tcg_sniper/admin/templates/servicos.html:115`
- Test: `tests/admin/test_admin_monitor_painel.py` (:149-194), `tests/admin/test_consultas_painel.py`

**Interfaces:**
- Consumes: Task 2 (`situacao_monitor(s, agora, cfg)`).
- Produces: `capacidade_por_hora(cfg: ConfigAmazon) -> int` em `consultas_painel.py` = `math.floor(3600 / ((pausa_min_s + pausa_max_s) / 2 + SEGUNDOS_POR_PAGINA))` com `SEGUNDOS_POR_PAGINA = 3` (estimativa do tempo de abrir a página; constante nomeada).

Comportamento:
- `_resumo_monitor`: "monitor: última leitura hoje 16:35 · rápida 32 · lenta 449 · esgotado 119" (+ ", N na fila" quando `vencidos`; "nunca lidos N" quando > 0).
- Aviso "precisa de X páginas por hora": `exigido = ceil(rapidos * 60 / intervalo)`; avisa se `exigido > min(teto, capacidade_por_hora(cfg))`, com o texto "O monitor precisa de {exigido} páginas por hora para ler os {rapidos} anúncios da fila rápida a cada {intervalo} min, acima do que cabe ({limite} por hora: teto {teto}, pausas de {min}–{max} s): as leituras da fila rápida vão atrasar."
- Aviso "atrasado": usa `mais_antiga_rapida` no lugar de `mais_antiga` e `vencidos` (rápidos + nunca lidos).
- `servicos.html:115`: "Fila rápida a cada {intervalo} min, das … às … · última leitura … · rápida N · lenta N (lida há ~X h) · esgotado N" (lenta "lida há" pela `mais_antiga_lenta`).

- [ ] **Step 1: Testes:** card com as contagens (ajustar `test_card_da_amazon_mostra_monitor_e_conferencia`); aviso de capacidade conta só os rápidos e usa o menor entre teto e capacidade (`capacidade_por_hora` com pausas 8–20 ⇒ 211); lentos atrasados **não** geram o aviso de atraso; rápido atrasado gera.
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/admin/test_admin_monitor_painel.py tests/admin/test_consultas_painel.py -q`.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar** `uv run pytest -q` e `uv run ruff check` → PASS (suíte toda verde a partir daqui).
- [ ] **Step 5: Commit** `feat: monitor panel and warnings count the fast queue`.

### Task 5: Catálogo "Esgotado na Liga · analisar"

**Files:**
- Modify: `src/tcg_sniper/consultas/catalogo_gestao.py:115-257`, `src/tcg_sniper/api/rotas_gestao_catalogo.py:35-105, 150-181, 232-269`, `web/src/paginas/gestao/Catalogo.tsx`, `web/src/paginas/gestao/ProdutoGestao.tsx`, `web/src/tipos.ts:232-269`
- Test: `tests/consultas/test_catalogo_gestao.py`, `tests/api/test_gestao_catalogo.py`, `web/src/paginas/gestao/Catalogo.test.tsx`, `ProdutoGestao.test.tsx`; `tests/fakes_oportunidades.py` (variante de `criar_listagem_liga` que aceita `None`)

**Interfaces:**
- Produces:
  - `FiltroCatalogo.preco_liga: Literal["todos", "com", "esgotado"] = "todos"` **substitui** `com_preco: bool` (consulta neutra, `FiltroEntrada`, `Filtros` da API e o corpo do lote). `"com"` = como o `com_preco=True` de hoje. `"esgotado"` = produto com `preco_a_partir` nulo (ou sem `preco_atual_liga`) **e** com anúncio confirmado com `preco_atual_amazon.preco` não nulo.
  - `LinhaCatalogo` ganha `medio_liga: Decimal | None`, `diferenca_media_pct: Decimal | None` (`motor.desconto_pct(melhor_amazon, medio)` quando os dois existem e médio > 0) e `sem_vendedor_desde: datetime | None` (maior `PrecoListagem.coletado_em` com `preco_a_partir` não nulo do produto; `None` = sem registro). Com `preco_liga="esgotado"` a ordem é `diferenca_media_pct` desc, nulos no fim, depois nome; senão a de hoje.
  - API: `LinhaCatalogoSaida` com os três campos; query `preco_liga` (`todos|com|esgotado`); `ProdutoGestaoSaida` ganha `esgotado_liga: bool`.
  - Front: o checkbox "Só com preço" vira `select` "Preço na Liga" (todos / com preço / esgotado na Liga) no `montarQueryCatalogo` (chave `preco_liga`, padrão `todos` omitido); com "esgotado" a lista mostra Amazon, média da Liga, diferença (`badge`) e "sem vendedor desde" (data ou "sem registro"); `ProdutoGestao` mostra `badge badge-warning` "Esgotado na Liga".
- O admin antigo (`condicoes_catalogo` com `com_preco: bool`) **não** muda.

- [ ] **Step 1: Testes:** consulta (`test_filtro_esgotado_so_com_anuncio_com_preco`, `test_ordem_esgotado_por_diferenca_media_nulos_no_fim`, `test_sem_vendedor_desde_pela_ultima_listagem_com_preco`, `test_contar_filtro_esgotado_igual_a_lista`); API (filtro, campos, lote com `preco_liga: "esgotado"` aplica aos mesmos produtos da lista, 422 para valor inválido); front (select grava `preco_liga=esgotado` na URL; colunas aparecem; badge no produto).
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar** `uv run pytest -q`, `uv run ruff check`, `(cd web && npm test && npm run build)` → PASS.
- [ ] **Step 5: Commit** `feat: catalog list of products sold out on Liga to analyze`.

### Task 6: Documentação e implantação

**Files:**
- Modify: `docs/IMPLANTACOES.md` (seção nova no topo: backup — migração `c5e1a8d3f7b2` —, `docker compose up -d --build`, **voltar o intervalo para 15** em Configurações → Amazon → Fila rápida, conferir o card com as contagens e Catálogo → esgotado), `docs/PENDENCIAS.md` (item do monitor atrasado sai da seção 0 para "Concluídas" quando o merge acontecer; acompanhar na seção 3 a primeira semana: ritmo do lento e lista de esgotados), `README.md` (seção do monitor: os grupos).

- [ ] **Step 1: Escrever** as três atualizações.
- [ ] **Step 2: Commit** `docs: monitor priority groups deploy notes`.
