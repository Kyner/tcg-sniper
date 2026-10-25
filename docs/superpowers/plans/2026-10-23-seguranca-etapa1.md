# Segurança, etapa 1 — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin antigo e noVNC escutando só neste PC por padrão, login sem o limite global que deixava qualquer um trancar todos, e faxina das sessões velhas.

**Architecture:** Portas do `docker-compose.yml` com endereço de escuta configurável (`${VAR:-127.0.0.1}`); remoção do limite total em `api/acesso.py` (ficam os limites por número); limpeza de `sessao` em `db/retencao.py`, junto com a limpeza diária.

**Tech Stack:** Docker Compose; Python 3 + FastAPI + SQLAlchemy 2; pytest.

**Spec:** `docs/superpowers/specs/2026-10-23-seguranca-etapa1-design.md`

## Global Constraints

- Textos em português; commits em inglês `tipo: descrição`; **sem** `Co-Authored-By`, `Claude-Session` ou "Generated with".
- Testes só no Postgres de teste (`127.0.0.1:5433`, bancos `tcg_test*`).
- Sem migração nesta entrega (a restrição `ck_pedido_codigo_resultado` continua aceitando `'limite_total'` por causa das linhas antigas; o código só não grava mais esse valor).
- Padrão de escuta: `127.0.0.1`; `ADMIN_ESCUTA`/`VNC_ESCUTA` no `.env` reabrem.
- Sessão encerrada ou vencida há mais de 30 dias é apagada; sessão ativa nunca.
- Sem dados pessoais nos docs (repositório público).

## Review Focus

1. **`.env` antigo sem as variáveis novas** → o compose sobe com `127.0.0.1` (padrão) sem erro. Teste na Task 1 (a leitura do compose confere o padrão).
2. **Pedido para 21 números diferentes na mesma hora** → todos aceitos (não existe mais limite global). Teste na Task 2.
3. **Aviso `SEGURANCA_LIMITE` aberto antes do deploy com a chave `total`** → fica sem quem o resolva; a Task 2 resolve esse aviso uma vez no primeiro pedido aceito depois do deploy (mesma chamada de hoje) para não deixar lembrete eterno. Teste na Task 2.
4. **Sessão vencida mas nunca encerrada** (`encerrada_em` nulo, `expira_em` antiga) → também é apagada depois de 30 dias. Teste na Task 3.
5. **`host_publico` com o IP da rede depois do deploy** → os links do noVNC no admin deixam de abrir; a explicação do campo e as notas de implantação dizem para usar `127.0.0.1`. Conferido na revisão da Task 1/4 (texto).

---

### Task 1: Admin antigo e noVNC só neste PC

**Files:**
- Modify: `docker-compose.yml:89-90, 111-112, 134-135, 178-179`
- Modify: `.env.example` (comentários das linhas 8-27 e as duas variáveis novas)
- Modify: `src/tcg_sniper/admin/formularios_config.py` (`EXPLICACOES_GERAL["host_publico"]`)
- Modify: `README.md` (instalação/noVNC: "por padrão só neste PC")
- Create: `tests/test_compose_portas.py`

**Interfaces:** nenhuma para outras tarefas.

- [ ] **Step 1: Teste** `tests/test_compose_portas.py` (lê `docker-compose.yml` com `yaml.safe_load` — `pyyaml` já vem com as dependências? se não vier, ler o arquivo como texto e usar regex):
  - `test_admin_e_novnc_escutam_so_neste_pc_por_padrao`: as portas de `admin` são `["${ADMIN_ESCUTA:-127.0.0.1}:8000:8000"]`; de `coletor-liga`, `coletor-amazon`, `coletor-amazon-busca`, respectivamente `"${VNC_ESCUTA:-127.0.0.1}:6080:6080"`, `"${VNC_ESCUTA:-127.0.0.1}:6081:6080"`, `"${VNC_ESCUTA:-127.0.0.1}:6082:6080"`.
  - `test_nenhuma_porta_publicada_aberta_sem_variavel`: toda porta publicada de todos os serviços começa por `127.0.0.1:` ou por `${…:-127.0.0.1}:`.
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/test_compose_portas.py -q`.
- [ ] **Step 3: Implementar:** portas no compose; `.env.example` com
  ```
  # Onde o admin antigo (8000) e o noVNC (6080-6082) escutam. Vazio = só neste PC (127.0.0.1).
  # 0.0.0.0 abre para qualquer aparelho da rede de casa: o noVNC do monitor é o navegador logado na Amazon.
  ADMIN_ESCUTA=
  VNC_ESCUTA=
  ```
  (atenção: `${VAR:-padrão}` usa o padrão também com a variável vazia), trocando `<IP deste PC>` por `localhost` nos comentários; explicação do `host_publico`: "Usado nos links do admin para o noVNC. Com o noVNC só neste PC (padrão), use 127.0.0.1. As mensagens do WhatsApp nunca levam este endereço."; README.
- [ ] **Step 4: Rodar** `uv run pytest -q` e `uv run ruff check` → PASS (ajustar testes do admin que fixam o texto antigo do `host_publico`, se houver).
- [ ] **Step 5: Commit** `feat: old admin and noVNC listen only on this PC by default`.

### Task 2: Login sem limite global

**Files:**
- Modify: `src/tcg_sniper/api/acesso.py:24-93` (sai `LIMITE_TOTAL`, `JANELA_TOTAL`, `ResultadoPedido.LIMITE_TOTAL` e o ramo do limite total em `_recusar`/`pedir_codigo`)
- Modify: `src/tcg_sniper/db/repositorio_acesso.py:17` (sai `TRAVA_PEDIDOS_TOTAL`; as outras travas mantêm os valores)
- Modify: `src/tcg_sniper/avisos/catalogo.py:434-440` (descrição do `SEGURANCA_LIMITE` sem o limite total) e o exemplo do tipo
- Test: `tests/api/test_auth.py` (:151, :340), `tests/api/test_limites_concorrencia.py` (:69-75), testes do catálogo de avisos que fixam o texto

**Interfaces:** nenhuma para outras tarefas.

Comportamento:
- `pedir_codigo` trava e conta só por número. A chave `CHAVE_TOTAL = "total"` continua existindo só para uma chamada: `avisos.resolver(s, TipoAviso.SEGURANCA_LIMITE, CHAVE_TOTAL, agora)` quando um pedido é aceito, para fechar um aviso antigo de "limite total" que esteja aberto (comentário dizendo isso).
- Descrição nova do `SEGURANCA_LIMITE`: "Pedidos de código acima do limite (3 por número em 15 min) ou 5 códigos errados seguidos (o código é invalidado); agrupa por número. Resolve quando o número entra no site." (o resto do texto como está).

- [ ] **Step 1: Testes:**
  - Trocar `test_limite_total_por_hora` por `test_sem_limite_global_numeros_diferentes_sao_aceitos`: 21 pedidos, um por número diferente, na mesma hora → todos 200 e nenhum `SEGURANCA_LIMITE` aberto.
  - Trocar `test_limite_total_resolve_no_proximo_pedido_aceito_depois_da_janela` por `test_aviso_antigo_de_limite_total_fecha_no_proximo_pedido_aceito` (abrir o aviso com chave `"total"` direto pelo serviço de avisos; um pedido aceito o resolve).
  - Remover/ajustar o caso de `LIMITE_TOTAL` em `test_limites_concorrencia.py`, mantendo o de número.
  - Manter os testes por número (4º código do mesmo número em 15 min → 429; 11ª entrada → 429).
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/api -q`.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar** `uv run pytest -q`, `uv run ruff check` → PASS.
- [ ] **Step 5: Commit** `feat: drop the global login limit, keep per-number limits`.

### Task 3: Faxina de sessões

**Files:**
- Modify: `src/tcg_sniper/db/retencao.py` (constante `DIAS_SESSAO = 30`, função `_limpar_sessoes(sessoes, agora) -> int` com `_em_lotes`, chave `"sessao"` em `limpar_historico`; docstring do módulo cita a regra)
- Test: `tests/db/test_retencao.py`

**Interfaces:** nenhuma.

Regra: apagar `Sessao` com `encerrada_em < agora − 30 dias` **ou** (`encerrada_em IS NULL` e `expira_em < agora − 30 dias`). Logs → Manutenção já mostra as chaves de `apagados` de forma genérica (`logs.html:212`).

- [ ] **Step 1: Testes** (`tests/db/test_retencao.py`): `test_limpa_sessao_encerrada_ha_mais_de_30_dias` (31 dias some, 29 fica); `test_limpa_sessao_vencida_ha_mais_de_30_dias_mesmo_sem_encerrar`; `test_sessao_ativa_nunca_some`; `limpar_historico` devolve a chave `"sessao"` com a contagem.
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/db/test_retencao.py -q`.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar** `uv run pytest -q`, `uv run ruff check` → PASS.
- [ ] **Step 5: Commit** `feat: daily cleanup of old login sessions`.

### Task 4: Documentação

**Files:**
- Modify: `docs/IMPLANTACOES.md` (seção nova no topo: sem migração; `docker compose up -d --build`; em Configurações → Geral, "IP ou nome deste PC na rede" = `127.0.0.1` se estiver com o IP da rede; conferir que `:8000` e `:6080`–`:6082` abrem neste PC; entrar no site pelo código normalmente)
- Modify: `docs/PENDENCIAS.md` (Seção 1: a etapa 1 pronta para o merge — itens "login sem bloqueio", "sessões nunca apagadas" e o plano de restringir admin/noVNC substituídos por uma linha "Etapa 1 pronta (spec …)"; a **etapa 2** listada como itens abertos: limite por origem via `CF-Connecting-IP`, Cloudflare Access, senha de verdade no noVNC, código cifrado na fila, tempo igual no login, domínio próprio das imagens, revisar números dos limites; Ordem sugerida e Última revisão)

- [ ] **Step 1: Escrever.**
- [ ] **Step 2: Commit** `docs: security stage 1 deploy notes and pending list`.
