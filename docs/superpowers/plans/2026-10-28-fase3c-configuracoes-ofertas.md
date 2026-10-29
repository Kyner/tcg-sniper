# Fase 3C — Configurações e Ofertas na gestão do site novo — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Levar Configurações e Ofertas para a gestão do site novo, fechar o que falta da tela Mensagens na Atividade e as pequenas de tela da 3A/3B, para o menu não apontar mais nada para o admin antigo e a fase 4 poder apagá-lo.

**Architecture:** As validações das configurações saem de `admin/formularios_*.py` para um pacote neutro `tcg_sniper/configuracoes/`; a consulta de Ofertas sai de `admin/consultas_amazon.py` para `tcg_sniper/consultas/ofertas.py` (o admin antigo passa a importar dos lugares novos, sem mudar de comportamento). Uma função descreve todos os campos por grupo (do spec) e uma única função calcula a caixa "Efeito" (na API, testada). Rotas novas `/api/gestao/configuracoes`, `/api/gestao/avisos/{tipo}` e `/api/gestao/ofertas`; telas `/gestao/configuracoes` e `/gestao/ofertas`.

**Tech Stack:** Python 3.12 + FastAPI + SQLAlchemy 2 + Postgres; React + Vite + TS + DaisyUI 5 + Vitest; Playwright (Python) no ponta a ponta.

**Spec:** `docs/superpowers/specs/2026-10-21-fase3-area-administrativa-design.md` (seções "Regras que valem para todas as telas", "Configurações", "Ofertas", "Menu da gestão", "Permissões", "API"). Rascunho das Configurações aprovado pelo usuário em 2026-10-21.

## Global Constraints

- Textos, telas, docstrings em português; commits em inglês `tipo: descrição`, **sem** `Co-Authored-By`, `Claude-Session` ou "Generated with".
- Só componentes do DaisyUI 5, classes literais (nada montado por concatenação). Mobile first (390 px), sem rolagem horizontal; tabelas viram cartões abaixo de `md`; status em uma linha com `truncate` e detalhe em `tooltip`.
- Toda rota `/api/gestao/...` declara `exige_todas(Permissao.VER_AREA_GESTAO, Permissao.X)`; toda tela exige `ver_area_gestao` e a própria. Configurações: ver = `ver_configuracoes`, salvar e ligar/desligar aviso = `editar_configuracoes`. Ofertas: `ver_catalogo`.
- **Nunca devolver segredo do `.env`** pela API (`admin_senha`, `segredo_api`, `evolution_api_key`, `evolution_url`, `openai_api_key`, `r2_*`, `database_url`, `VNC_SENHA`); da chave da OpenAI só o booleano "chave configurada". Configurações não mostra nem salva `monitor_ligado`, `checkout_ligado`, `checkout_sem_login_em` (são de Serviços).
- Salvar configurações grava `acao_gestao` tipo `configuracoes` com `{"campos": {"<tabela>.<campo>": [antes, depois]}}`, na mesma transação; ligar/desligar aviso grava o mesmo tipo com `{"aviso": tipo, "ligado": bool}`.
- Os limites e as regras de validação são os de hoje (`LIMITES_CONFIG_*` em `db/models.py`, `coletor_amazon/config.py` `validar_config`, `formularios_config`, `formularios_ia`); a mesma validação vale para o admin antigo e para a API.
- O admin antigo continua igual até a fase 4 (testes de `tests/admin/` só mudam import). Nada em `consultas/`, `gestao/`, `configuracoes/` nem `api/` importa `tcg_sniper.admin` (estender a guarda `tests/consultas/test_sem_admin.py`).
- Sem migração. Testes no Postgres de teste (5433). `uvx ruff check src tests`.

## Decisões deste plano (chamadas do controlador)

1. **Caixa "Efeito" na API**: `POST /api/gestao/configuracoes/efeito` recebe os valores digitados (só os do grupo) e devolve o efeito; o front chama com debounce de 400 ms. Uma conta só, testada (spec "API": a decisão é do construtor). Tempo de página **medido não existe**: usa-se a estimativa `SEGUNDOS_POR_PAGINA` de `consultas/painel.py` e o texto diz "estimativa". Custo médio por avaliação = média de `chamada_ia.custo_usd` com `ok` e `finalidade="casamento"` dos últimos 7 dias (sem chamadas: "sem dado ainda").
2. **Categorias da Liga**: chips com busca, um por ID. Não existe tabela ID→nome: cria-se `NOMES_CATEGORIAS: dict[int, str]` em `tcg_sniper/configuracoes/liga.py` **vazio**; ID sem nome aparece "categoria N" (como a spec manda). Preencher os nomes fica como pendência (exige olhar a Liga).
3. **Grupos do WhatsApp**: a Evolution não tem chamada de listar grupos no projeto; mostra-se o ID com a explicação no tooltip ("termina em @g.us; veja no painel da Evolution"). Nomes dos grupos ficam como pendência.
4. **Avisos**: agrupados por área usando `origem` do catálogo (não existe campo "área"); busca por título/descrição; uma linha por tipo (chave, destino, se agrupa), exemplo ao tocar (renderizado com `TextoWhatsApp`). São 37 tipos (a spec dizia 28).
5. **Grupos e campos**: exatamente os da spec, com estes encaixes que a spec não cita: `monitor_esgotado_dias` em "Acompanhar preço" (Avançado); `validade_oportunidade_h` (Geral) em "Oportunidades"; pausas da Liga (float) em "LigaMagic" e pausas da Amazon em "Cuidado com bloqueio" (são campos diferentes).
6. **Mensagens na Atividade**: para cobrir a tela antiga, a Atividade ganha filtro `destino` (admin, oportunidades, individual) e a situação `pendente` (só mensagens); `destino_novo` passa a traduzir `/mensagens?situacao=pendente`.
7. **Pequenas que entram** (as de tela; as internas seguem na seção 2): Catálogo, Revisão, Lista de Casamentos e Menu da 3A (`PENDENCIAS.md` seção 2, "Gestão do site novo"); Serviços (recarga sobrescreve ação, rótulo da chave no celular, mensagem de sucesso que nunca some), "US$ 0.000000", rótulo "Ligar"/links do Dashboard (seção 2, "Pequenas da revisão da 3B"); foco que não volta ao fechar modal; menu de idioma que não fecha com Esc/clique fora. Os itens internos da API da gestão (lista refeita, `Literal` repetidos) não entram.

## Cobertura do admin antigo (complementa a tabela da 3B, para a fase 4)

| Rota antiga | Onde fica |
|---|---|
| `GET /configuracoes`, `POST /configuracoes/{geral,liga,amazon,ia}` | `GET`/`PUT /api/gestao/configuracoes` + `/gestao/configuracoes` |
| `POST /configuracoes/avisos` | `PATCH /api/gestao/avisos/{tipo}` (grupo "WhatsApp e avisos") |
| `GET /ofertas` | `GET /api/gestao/ofertas` + `/gestao/ofertas` |
| `GET /mensagens` (filtros situação e destino) | Atividade com `destino` e `situacao=pendente` (Task 7) |

## Review Focus

1. **Salvar com dois campos dependentes inválidos juntos** (ex.: "quase lá" ≥ desconto mínimo; janela início ≥ fim; pausa mín > máx) → 422 com o erro junto ao campo, nada gravado (nem os outros grupos). Teste na Task 3.
2. **Dois usuários salvando ao mesmo tempo** → o segundo não sobrescreve sem saber: o PUT recebe a versão (`atualizado_em` de cada tabela) e responde 409 `config_mudou` se mudou. Teste na Task 3.
3. **Resposta da API de configurações nunca contém segredo** (procura no JSON pelos valores falsos de `openai_api_key`, `evolution_api_key`, `segredo_api`, `admin_senha` do `.env` de teste). Teste na Task 3.
4. **Sair da tela com alteração não salva** (navegação interna e fechar aba) → confirma; Descartar volta os valores sem chamar a API. Teste na Task 4.
5. **Ofertas com produto sem preço na Liga e com preço conferido vencido** → linha aparece sem desconto e sem quebrar; "conferido" só quando válido. Teste na Task 5.

---

### Task 1: Validações e Ofertas no pacote neutro

**Files:** Move `src/tcg_sniper/admin/formularios_config.py` → `src/tcg_sniper/configuracoes/geral_liga.py` e `admin/formularios_ia.py` → `configuracoes/ia.py` (com `git mv`; `configuracoes/__init__.py`); move de `admin/consultas_amazon.py` para `src/tcg_sniper/consultas/ofertas.py`: `FiltroOfertas`, `LinhaOferta`, `ofertas`, `_desconto_exibido` (e os auxiliares só deles). Modify imports do admin antigo e dos testes. Test: `tests/consultas/test_sem_admin.py` (guarda cobre também `configuracoes` e `api`).

**Interfaces:** Produces os mesmos nomes de hoje nos lugares novos (`validar_geral`, `validar_liga`, `validar_ia`, `texto_ia`, `CAMPOS_*`, `ROTULOS_*`, `EXPLICACOES_*`, `OPCOES_IA`; `FiltroOfertas`, `LinhaOferta`, `ofertas(s, filtro, config)`), mais `NOMES_CATEGORIAS: dict[int, str] = {}` em `configuracoes/geral_liga.py` (decisão 2).

- [ ] Step 1: guarda falha ao incluir `configuracoes` e `api` se algo importar `tcg_sniper.admin` (ver falhar com o pacote novo importando de admin, se for o caso). Step 2: mover; `amazon_do_produto`/`historico_amazon` ficam no admin (são do `/produto` antigo). Step 3: `uv run pytest tests/admin tests/consultas tests/coletor_amazon -q` → PASS sem mudar expectativas. Step 4: commit `refactor: config validation and offers query in neutral packages`.

### Task 2: Descrição dos grupos e cálculo do Efeito

**Files:** Create `src/tcg_sniper/configuracoes/grupos.py`, `src/tcg_sniper/configuracoes/efeito.py`. Test: `tests/configuracoes/test_grupos.py`, `tests/configuracoes/test_efeito.py`.

**Interfaces:**
- `@dataclass(frozen=True) Campo: chave: str` (`"amazon.desconto_min_pct"`, `"<tabela>.<campo>"` com tabela ∈ geral, liga, amazon, ia)`; rotulo: str; explicacao: str; tipo: Literal["int","decimal","float","hora","texto","bool","escolha","categorias"]; padrao: object; minimo: Decimal|None; maximo: Decimal|None; opcoes: tuple[tuple[str,str],...]` (valor, rótulo em português; ex. esforço "low" → "baixo")`; avancado: bool; vinculo: str|None` (texto do vínculo, ex. "menor que o desconto mínimo").
- `@dataclass(frozen=True) Grupo: id: str; titulo: str; proposito: str; campos: tuple[Campo,...]; tem_efeito: bool`.
- `GRUPOS: tuple[Grupo, ...]` na ordem da spec com ids `oportunidades, vendedores, busca, monitor, checkout, bloqueio, liga, ia-decide, ia-ritmo, ia-gasto, ia-modelo, whatsapp, sistema` (decisão 5; avisos ficam fora de `campos`, vêm à parte).
- `valores_atuais(s, config_env) -> dict[str, object]` (lê as 4 tabelas; sem segredos) e `versoes(s) -> dict[str, str]` (`atualizado_em` ISO por tabela).
- `efeito(s, agora, grupo_id: str, valores: Mapping[str, object]) -> Efeito | None`, `@dataclass Efeito: linhas: tuple[str,...]; nivel: Literal["info","aviso","erro"]`. Regras: oportunidades (faixas "alerta a partir de X%", "quase lá de Y% a X%", contagem atual de abertas e de quase lá); busca (buscas/dia = `max_buscas_hora` × horas da janela; produtos sem par ÷ buscas/dia = "cada produto sem par a cada ~N dias"); monitor (páginas/h necessárias = `ceil(rapidos*60/intervalo)` como `painel._avisos_monitor`; limite = `min(teto, capacidade_por_hora)`; aviso quando necessário > limite com a sugestão de intervalo `ceil(rapidos*60/limite)`); checkout ("confere a partir de (desconto − margem)%"); bloqueio (`capacidade_por_hora` por navegador e a soma dos dois, "estimativa"); ia-decide (quantos pendentes ficam para você com as confianças); ia-ritmo (avaliações/h = lote×60/intervalo; em quanto tempo o teto do dia acaba no custo médio, decisão 1); ia-gasto (gasto do dia e do mês × tetos, barra em %). Grupos sem efeito devolvem `None`.

- [ ] Step 1: testes: `test_grupos_cobrem_todos_os_campos_editaveis` (todo campo de `CAMPOS` Amazon, `CAMPOS_GERAL`, `CAMPOS_LIGA`, `CAMPOS_IA` aparece uma vez; nenhum de Serviços), `test_valores_sem_segredo`, `test_esforco_em_portugues`, e um teste por regra de efeito com números fixos (ex.: monitor com 64 rápidos, intervalo 15, teto 150, pausas 8–20 → necessário 256/h, limite 211/h, aviso, sugere 19 min). Step 2–4: ver falhar, implementar, PASS. Step 5: commit `feat: settings groups and effect calculation`.

### Task 3: API de Configurações e avisos

**Files:** Create `src/tcg_sniper/api/rotas_gestao_configuracoes.py`; Modify `api/app.py`; Test `tests/api/test_gestao_configuracoes.py`.

**Interfaces:**
- `GET /api/gestao/configuracoes` (`ver_configuracoes`) → `{grupos: [...Grupo com valor de cada campo], versoes, avisos: [{tipo, titulo, descricao, area (origem), destino, agrupa, ligado, exemplo (texto WhatsApp)}], ia: {chave_configurada: bool}}`.
- `POST /api/gestao/configuracoes/efeito` (`ver_configuracoes`) corpo `{grupo, valores}` → `Efeito | null`.
- `PUT /api/gestao/configuracoes` (`editar_configuracoes`) corpo `{versoes, valores: {"<tabela>.<campo>": valor}}` (só os alterados) → valida tudo com os validadores neutros (os de cada tabela, mais os cruzados) antes de gravar; erro → 422 `validacao` com `{campo: mensagem}`; versão diferente → 409 `config_mudou`; grava as tabelas tocadas numa transação (Amazon por `aplicar_config`), registra `acao_gestao` (`{"campos": {chave: [antes, depois]}}`) e devolve o mesmo corpo do GET.
- `PATCH /api/gestao/avisos/{tipo}` (`editar_configuracoes`) corpo `{ligado}` → `avisos.definir_ligado` + `acao_gestao`; tipo inválido 404.

- [ ] Step 1: testes: 401/403 por rota (operador vê, não salva); `test_put_salva_so_os_alterados_e_registra_antes_depois`; `test_put_invalido_nao_grava_nada` (Review Focus 1, incluindo campo de outra tabela no mesmo corpo); `test_put_com_versao_velha_409` (Review Focus 2); `test_resposta_nunca_tem_segredo` (Review Focus 3); `test_nao_expoe_campos_de_servicos`; `test_patch_aviso`; `test_efeito_do_monitor`. Step 2–4: ver falhar, implementar, PASS (inclui `test_toda_rota_da_api_declara_permissao_ou_e_publica`). Step 5: commit `feat: settings and alert toggles API`.

### Task 4: Tela Configurações

**Files:** Create `web/src/paginas/gestao/Configuracoes.tsx` (+ `.test.tsx`), e componentes pequenos se o arquivo passar de ~300 linhas (`web/src/componentes/CampoConfig.tsx`, `web/src/componentes/AvisosConfig.tsx`); Modify `App.tsx` (rota `/gestao/configuracoes` com `ver_area_gestao` + `ver_configuracoes`), `tipos.ts`.

- [ ] Step 1: testes (Vitest, `apiFalsa`): grupos em `collapse` com a frase de propósito; no computador, menu lateral de grupos e link profundo `?grupo=monitor` abre o grupo; campo com rótulo, tooltip ⓘ, "Padrão: X" e ↺ que volta ao padrão; vínculo mostrado; "Avançado" fechado dentro do grupo; esforço com rótulos em português; booleanos como `toggle`; números com milhar; Efeito chamado com debounce e mostrado em `alert` (aviso em `alert-warning`); barra fixa "N alterações · Descartar · Salvar"; Salvar manda só os alterados com as versões; 422 mostra o erro junto ao campo; 409 mostra "As configurações mudaram; recarregue"; sair com alteração confirma (Review Focus 4; `useBlocker` do React Router e `beforeunload`); operador sem `editar_configuracoes` vê tudo só leitura e sem barra; categorias como chips com busca ("categoria N" sem nome); avisos agrupados por área, com busca, toggle que liga/desliga no lugar e exemplo ao tocar (`TextoWhatsApp`). Step 2–4: ver falhar, implementar, `npm test` e `npm run build` → PASS. Step 5: commit `feat: management settings screen`.

### Task 5: API e tela de Ofertas

**Files:** Create `src/tcg_sniper/api/rotas_gestao_ofertas.py`, `web/src/paginas/gestao/Ofertas.tsx` (+ `.test.tsx`); Modify `api/app.py`, `App.tsx`, `tipos.ts`; Test `tests/api/test_gestao_ofertas.py`.

**Interfaces:** `GET /api/gestao/ofertas?busca=&categoria=&desconto_min=&vendedor=&situacao=&ordem=&pagina=` (`ver_area_gestao` + `ver_catalogo`; mesmos filtros e valores do admin antigo; 50 por página) → `{itens: [{produto_id, produto, imagem, preco_liga, anuncio: {asin, titulo, url, imagem}, preco, desconto_pct, diferenca, envio, vendedor, confiavel, verificado, aberta, risco: {desde, motivo}|null, origem, prime, importada, conferido: {preco, impostos, frete}|null, coletado_em}], total, pagina, por_pagina}`.

- [ ] Step 1: testes API: permissões; filtros; `test_sem_preco_na_liga_aparece_sem_desconto` e `test_conferido_vencido_nao_aparece_como_conferido` (Review Focus 5); `test_frase_do_conferido` (o "conferido, com impostos de R$ X" da seção 2). Front: cartão por produto no celular e tabela enxuta no computador; produto com foto e nome sem selos empilhados (origem, Prime, importado e vendedor no tooltip); linha "conferido R$ X com impostos" com o detalhe no tooltip; diferença negativa com sinal certo ("−R$ 42,00", auditoria O2); filtro de desconto como chip (O4); filtros na URL; sem rolagem horizontal. Step 2–4: ver falhar, implementar, PASS. Step 5: commit `feat: management offers screen`.

### Task 6: Menu e links sem admin antigo

**Files:** Modify `web/src/componentes/LayoutGestao.tsx` (`TELAS_ANTIGAS` sai; Ofertas e Configurações viram `NavLink`), `src/tcg_sniper/consultas/dashboard.py` (`DESTINO_MONITOR_ATRASADO` → `/gestao/configuracoes?grupo=monitor`; "Ajustar em Configurações" → `/gestao/configuracoes?grupo=ia-gasto`; `destino_novo` traduz `/configuracoes?secao=X` → `/gestao/configuracoes?grupo=<id>` e `/ofertas` → `/gestao/ofertas`; `_REQUER_DO_CAMINHO` com as novas), testes de menu e dashboard.

- [ ] Step 1: testes: menu sem nenhum link para a porta 8000; dashboard sem destino `antigo:`; `destino_novo` cobre cada link antigo de configurações e ofertas. Step 2–4: ver falhar, implementar, PASS. Step 5: commit `feat: management menu without old admin links`.

### Task 7: Atividade cobre a tela Mensagens

**Files:** Modify `src/tcg_sniper/consultas/atividade.py` (`FiltroAtividade.destino: Literal["admin","oportunidades","individual"]|None`; `situacao` aceita `"pendente"` que só traz mensagens pendentes), `api/rotas_gestao_atividade.py`, `web/src/paginas/gestao/Atividade.tsx`, `consultas/dashboard.py` (`destino_novo` traduz `/mensagens?situacao=pendente` → `/gestao/atividade?o_que=mensagem&situacao=pendente`).

- [ ] Step 1: testes: filtro destino; `situacao=pendente` só traz mensagens pendentes; tela mostra o filtro de destino quando `o_que=mensagem`; `destino_novo` da pendente. Step 2–4: ver falhar, implementar, PASS. Step 5: commit `feat: activity covers the old messages screen`.

### Task 8: Pequenas de tela da 3A e da 3B

**Files:** conforme cada item (decisão 7): `web/src/paginas/gestao/Catalogo.tsx`, `RevisaoCasamento.tsx` (e dividir em componentes, ~400 linhas), `Casamentos.tsx`, `LayoutGestao.tsx`, `Servicos.tsx`, `Atividade.tsx`, `Gestao.tsx`, `componentes/Modal.tsx`, `componentes/CartaoAnuncio.tsx`, e a API que cada um pedir (ex.: nome em inglês, lojas e contagens do casamento no Catálogo já vêm da API).

- [ ] Step 1: um teste por item, antes da correção: Catálogo (tooltip do selo; contagem do lote depois de aplicar; resposta antiga não desfaz chave recém-trocada; nome em inglês, lojas e contagens na linha; chave sem mudança não registra ação); Revisão (Enter no menu ⋯ não avança; ↑/↓ rolam até o cartão; "desfazer" não troca o destaque sem avisar; no celular a Liga compacta acima, anúncios logo depois; "Pular" ≠ "Próximo" — Pular vai ao seguinte sem marcar visto, Próximo idem após decidir: se forem iguais por definição, juntar num botão só e anotar); Lista de Casamentos ("Tentar de novo" com cancelamento; a lista antiga some sob o alerta; página além da última oferece ir à 1ª); Menu (`aria-expanded`/`aria-controls`); Serviços (recarga de 60 s não sobrescreve ação em andamento; rótulo visível da chave no cartão; mensagem de sucesso some em 5 s); Atividade sem "US$ 0.000000"; Dashboard ("Ver" para quem não pode pausar; links de oportunidades exigem também `ver_area_negocio`); Modal devolve o foco ao botão que abriu; menu de idioma fecha com Esc e clique fora. Step 2–4: ver falhar, corrigir, `npm test`/`npm run build`/pytest → PASS. Step 5: commit(s) `fix: ...` por área.

### Task 9: Ponta a ponta, layout e documentação

**Files:** `tests/e2e/test_ponta_a_ponta.py`, `scripts/verificar_layout.py` (`TELAS_WEB` com `/gestao/configuracoes`, `/gestao/ofertas`), `README.md`, `docs/IMPLANTACOES.md` (seção 3C: sem migração), `docs/PENDENCIAS.md` (3C em Concluídas; itens da seção 2 resolvidos tirados; tabela de cobertura da fase 4 completada com a desta 3C; pendências novas: nomes das categorias (decisão 2) e nomes dos grupos do WhatsApp (decisão 3)).

- [ ] Step 1: ponta a ponta: admin altera um campo de Oportunidades, vê o Efeito, salva, vê a ação na Atividade; operador vê só leitura; Ofertas carrega e filtra; layout 390/1440 claro e escuro sem rolagem horizontal; operador nas telas da gestão (item da seção 2). Step 2: suíte inteira, ruff, `npm test`, `npm run build`, e2e → PASS. Step 3: commit `docs: phase 3C docs and pending list`.
