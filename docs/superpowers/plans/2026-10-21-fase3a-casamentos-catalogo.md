# Fase 3A — Casamentos e Catálogo na gestão do site novo — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Levar a revisão de casamentos (lista + um produto por vez) e o catálogo (lista, lote, página do produto) para a área de gestão do site novo, com as permissões novas, o menu da gestão e o registro das ações de gestão.

**Architecture:** As consultas de casamento e de catálogo saem do pacote `admin` para o pacote neutro `tcg_sniper/consultas/` (o admin antigo passa a importar de lá, sem mudar de comportamento). Um roteador novo `rotas_gestao_casamentos.py` e outro `rotas_gestao_catalogo.py` em `/api/gestao/...` chamam os repositórios que já existem. O front ganha um layout de gestão com menu lateral (`drawer`) e as telas `/gestao/casamentos`, `/gestao/casamentos/:produtoId`, `/gestao/catalogo` e `/gestao/produtos/:id`.

**Tech Stack:** Python 3 + FastAPI + SQLAlchemy 2 + Alembic + Postgres; React + Vite + TypeScript + DaisyUI 5 + Vitest; Playwright (Python) no ponta a ponta.

**Spec:** `docs/superpowers/specs/2026-10-21-fase3-area-administrativa-design.md` (seções "Regras que valem para todas as telas", "Casamentos — lista", "Casamentos — revisão de um produto", "Catálogo", "Produto na gestão", "Menu da gestão", "Permissões", "API", "Atividade" → ações de gestão).

## Global Constraints

- Textos, telas e mensagens em português; assunto dos commits em inglês `tipo: descrição`; **sem** `Co-Authored-By`, `Claude-Session` ou "Generated with" (CLAUDE.md).
- Só componentes do DaisyUI 5, classes escritas por extenso (nada montado por concatenação). Sem visual próprio.
- Mobile first: desenhado para 390 px; abaixo de `md` tabelas viram listas de cartões; sem rolagem horizontal da página.
- Ação numa linha atualiza **no lugar** (estado otimista, volta e mensagem se a API falhar); a página não recarrega nem muda a rolagem.
- Filtros, busca, ordem e página ficam na URL; "Voltar" restaura a lista com eles.
- Status em uma linha (`truncate`); texto completo em `tooltip`.
- Fotos só do bucket público (`imagem` montada de `imagem_chave` + `URL_PUBLICA_IMAGENS`); sem foto, placeholder neutro. Nunca URL da Liga/Amazon como imagem.
- Ação em lote pede confirmação com o número exato em `modal`.
- Toda rota `/api/gestao/...` declara `exige(...)`; toda tela exige `ver_area_gestao` **e** a permissão própria.
- Testes no Postgres de teste (`127.0.0.1:5433`, bancos `tcg_test*`); nunca a 5432.
- Regra de casamento não muda: só chamar `repositorio_casamento`, `repositorio_termos`, `repositorio_amazon.priorizar_na_fila`, `casar_link_manual`.
- `acao_gestao` nunca é apagada pela limpeza diária.
- Backup do banco antes do deploy (há migração); deploy de todos os serviços juntos `docker compose up -d --build`.

## Review Focus

1. **Duplo clique ou C em anúncio já confirmado em outro produto** → a API responde 409 `ja_confirmado` com o nome do outro produto; a tela volta o cartão e mostra a mensagem, sem quebrar o resto. Teste na Task 5 e na Task 9.
2. **Lote com o filtro mudando entre a contagem e o aplicar** (produto novo entrou) → a API recebe a contagem esperada; se diferente, 409 `contagem_mudou` com o número novo e nada é alterado. Teste na Task 6.
3. **Produto desativado (no Catálogo ou no admin antigo) enquanto está aberto na revisão** → ações e "Próximo" respondem 404; a tela mostra "Produto não está mais monitorado" e oferece "Próximo". Teste na Task 4 e Task 9.
4. **Nome muito longo (Secret Lair de 120 caracteres) e produto sem foto em 390 px** → nada estoura a largura; placeholder no lugar da foto. Teste de layout na Task 11.
5. **Voltar do produto para a lista** com busca, filtros e página 3 → a lista volta igual (URL). Teste na Task 8.

---

### Task 1: Permissões novas da fase 3

**Files:**
- Modify: `src/tcg_sniper/api/permissoes.py:17-59`
- Modify: `web/src/tipos.ts:5-11`, `web/src/teste/apoio.tsx:78-81`
- Modify: `tests/api/test_acessos.py:15-34`
- Modify: `README.md:310-317`

**Interfaces:**
- Produces: `Permissao.REVISAR_CASAMENTOS`, `VER_CATALOGO`, `EDITAR_CATALOGO`, `VER_SERVICOS`, `PAUSAR_SERVICOS`, `VER_LOGS`, `VER_MENSAGENS`, `REENVIAR_MENSAGENS`, `VER_CONFIGURACOES`, `EDITAR_CONFIGURACOES` (valores em minúsculas, iguais aos nomes); no front, o tipo `Permissao` com os mesmos 10 valores a mais.

- [ ] **Step 1: Atualizar o teste de padrões** em `tests/api/test_acessos.py::test_padroes_e_linhas_salvas`: o conjunto do OPERADOR passa a ser `{ver_area_negocio, ver_oportunidades, ver_area_gestao, revisar_casamentos, ver_catalogo, editar_catalogo, ver_servicos, ver_logs, ver_mensagens, ver_configuracoes}`; GRUPO continua `{ver_area_negocio, ver_oportunidades}`.
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/api/test_acessos.py -q` → FAIL no conjunto do operador.
- [ ] **Step 3: Acrescentar ao enum, nesta ordem, depois de `VER_DOCUMENTACAO_API`**, as 10 permissões; `DEFINICOES` com rótulo e descrição da tabela "Permissões" da spec (ex.: `REVISAR_CASAMENTOS: ("Revisar casamentos", "Ver e decidir casamentos, rebuscar, reavaliar com a IA e gerar termos de busca.")`); `PADROES[OPERADOR]` com o conjunto do Step 1.
- [ ] **Step 4: Front:** acrescentar os 10 valores ao tipo `Permissao` (`web/src/tipos.ts`) e a `EU_ADMIN.permissoes` (`web/src/teste/apoio.tsx`); `EU_OPERADOR` ganha os padrões do operador.
- [ ] **Step 5: Rodar:** `uv run pytest tests/api -q` e `(cd web && npm test)` → PASS (o teste de ordem do enum em `test_acessos.py:65` continua passando porque compara com o próprio enum).
- [ ] **Step 6: README:** tabela de permissões com as 10 novas e o padrão por papel.
- [ ] **Step 7: Commit** `feat: phase 3 permissions`.

### Task 2: Registro das ações de gestão (`acao_gestao`)

**Files:**
- Create: `src/tcg_sniper/db/migrations/versions/a1c4e7b9d2f6_acao_gestao.py` (revises `f3b8d1c7a9e2`)
- Modify: `src/tcg_sniper/db/models.py` (classe nova `AcaoGestao`, enum `TipoAcaoGestao`)
- Create: `src/tcg_sniper/db/repositorio_acao_gestao.py`
- Test: `tests/db/test_migracao_acao_gestao.py`, `tests/db/test_repositorio_acao_gestao.py`

**Interfaces:**
- Produces:
  - `class TipoAcaoGestao(StrEnum)`: `CATALOGO_LOTE = "catalogo_lote"`, `CATALOGO_PRODUTO = "catalogo_produto"`, `SERVICO = "servico"`, `CONFIGURACOES = "configuracoes"` (as duas últimas usadas na 3B/3C).
  - `class AcaoGestao`: `id: int`, `usuario_id: int | None` (FK `usuario.id`, `ondelete="SET NULL"`; nulo = "admin antigo"), `em: datetime` (timezone), `tipo: TipoAcaoGestao` (texto), `detalhe: dict` (JSONB, não nulo). Índice em `em`.
  - `registrar(s: Session, usuario_id: int | None, tipo: TipoAcaoGestao, detalhe: dict, agora: datetime) -> AcaoGestao` em `repositorio_acao_gestao.py` (não faz commit; roda na transação de quem chama).

- [ ] **Step 1: Teste da migração** (no molde dos `tests/db/test_migracao_*.py`): `upgrade` cria a tabela `acao_gestao` com as colunas acima e o índice; `downgrade` a remove.
- [ ] **Step 2: Teste do repositório:** `test_registrar_grava_na_transacao_de_quem_chama` (registrar + rollback ⇒ nada gravado) e `test_usuario_apagado_deixa_acao_sem_usuario`.
- [ ] **Step 3: Rodar e ver falhar:** `uv run pytest tests/db/test_migracao_acao_gestao.py tests/db/test_repositorio_acao_gestao.py -q`.
- [ ] **Step 4: Implementar** migração, modelo e `registrar`. Conferir que `db/retencao.py` não toca na tabela (acrescentar `acao_gestao` à lista do teste de "nunca apagado", se existir; senão um teste `test_limpeza_nao_apaga_acao_gestao` em `tests/manutencao/`).
- [ ] **Step 5: Rodar** `uv run pytest tests/db tests/manutencao -q` → PASS.
- [ ] **Step 6: Commit** `feat: management action log table`.

### Task 3: Consultas de casamento no pacote neutro

**Files:**
- Create: `src/tcg_sniper/consultas/casamentos.py`, `src/tcg_sniper/consultas/variacao.py`
- Modify: `src/tcg_sniper/admin/consultas_amazon.py:86-400` (passa a importar e reexportar o que mudou de lugar), `src/tcg_sniper/admin/app.py:123-172` (importa `MENSAGENS_CASAMENTO` e `EXPLICACAO_REAVALIAR` do pacote novo)
- Test: `tests/consultas/test_casamentos.py`, `tests/consultas/test_variacao.py`

**Interfaces:**
- Produces (em `tcg_sniper.consultas.casamentos`):
  - `LinhaProdutoCasamento`, `produtos_para_casar(...)`, `LinhaAnuncio`, `DetalheCasamento`, `detalhe_casamento(...)`, `sugestoes_para(...)`, `buscar_produtos(...)`, `SITUACOES_CASAMENTO`, `MENSAGENS_CASAMENTO`, `EXPLICACAO_REAVALIAR` — **movidos sem mudar assinatura** de `admin/consultas_amazon.py` e `admin/app.py`.
  - Novo: `ORDENS_CASAMENTO = ("preco_liga", "pendentes", "nome")` e o parâmetro `ordem: str = "preco_liga"` em `produtos_para_casar`. `"preco_liga"`: com preço na Liga primeiro, depois mais pendentes, depois nome, id. O admin antigo chama com a ordem de hoje (`ordem="legado"`, que mantém `(not oportunidade, pendentes == 0, nome, id)`).
  - Novo: `parecidos_na_liga(s: Session, produto: ProdutoLiga, limite: int = 3) -> list[tuple[ProdutoLiga, Decimal | None]]` (produtos ativos de nome próximo, excluindo o próprio; o construtor escolhe a regra, ex.: mesmo nome sem "Foil"/"Edition" ou o `buscar_produtos` com o nome sem sufixos).
  - Novo (em `tcg_sniper.consultas.variacao`): `pistas_variacao(nome: str) -> list[str]` e `termos_variacao(titulo: str) -> list[str]`.

- [ ] **Step 1: Testes de variação** (`tests/consultas/test_variacao.py`):
  - `pistas_variacao("Secret Lair - Goblingram") == ["sem Foil no nome", "idioma não informado"]`
  - `pistas_variacao("Secret Lair - Goblingram Foil Edition") == ["Foil", "idioma não informado"]`
  - `pistas_variacao("Booster Box - Core Set 2019 (Inglês)") == ["sem Foil no nome", "inglês"]`
  - `termos_variacao("MTG Secret Lair: Goblingram (Non-Foil Edition)") == ["Non-Foil"]`
  - `termos_variacao("Yu-Gi-Oh! Booster Box 24 Packs English") == ["24 Packs", "English"]`
- [ ] **Step 2: Testes de casamentos** (`tests/consultas/test_casamentos.py`, com `fakes.criar_produto/criar_anuncio/criar_par/criar_preco_liga`):
  - `test_ordem_preco_liga_poe_quem_tem_preco_primeiro`: produto A sem preço com 5 pendentes, B com preço e 1 pendente ⇒ `[B, A]`.
  - `test_ordem_legado_igual_a_de_hoje`: mesma entrada que o teste atual de ordenação do admin antigo dá a mesma lista.
  - `test_parecidos_exclui_o_proprio_e_inativos`.
- [ ] **Step 3: Rodar e ver falhar:** `uv run pytest tests/consultas -q`.
- [ ] **Step 4: Mover** as funções, dataclasses e textos listados para `consultas/casamentos.py`; `admin/consultas_amazon.py` e `admin/app.py` importam de lá (sem `# noqa: PLC0414` novo: importar pelo nome usado). Implementar `ordem`, `parecidos_na_liga`, `pistas_variacao`, `termos_variacao` (regex por palavra, sem diferenciar maiúsculas; idiomas: inglês/english, português/portuguese, japonês/japanese; "Non-Foil" vence "Foil"; quantidade `\d+ (packs|boosters|pacotes)`).
- [ ] **Step 5: Rodar tudo:** `uv run pytest -q` → PASS (os testes do admin antigo provam que nada mudou de comportamento); `uv run ruff check`.
- [ ] **Step 6: Commit** `refactor: move match queries to neutral package`.

### Task 4: API de leitura dos casamentos

**Files:**
- Create: `src/tcg_sniper/api/rotas_gestao_casamentos.py`
- Create: `src/tcg_sniper/api/imagens.py` (move `_imagens` e `_base` de `rotas_oportunidades.py:155-171` como `com_imagens(dados: dict, base: str | None) -> dict` e `base_imagens(request) -> str | None`; `rotas_oportunidades.py` passa a usá-los)
- Modify: `src/tcg_sniper/api/app.py:15,37-40`
- Test: `tests/api/test_gestao_casamentos.py`

**Interfaces:**
- Consumes: Task 1 (`Permissao.REVISAR_CASAMENTOS`), Task 3 (`produtos_para_casar`, `detalhe_casamento`, `parecidos_na_liga`, `pistas_variacao`, `termos_variacao`).
- Produces:
  - Dependência `RevisarCasamentos = Annotated[Contexto, Depends(exige_todas(Permissao.VER_AREA_GESTAO, Permissao.REVISAR_CASAMENTOS))]`. `exige_todas(*permissoes: Permissao) -> Callable[..., Contexto]` nova em `dependencias.py`, com `dependencia.permissao` = a última (o teste `test_toda_rota_da_api_declara_permissao_ou_e_publica` continua valendo).
  - `GET /api/gestao/casamentos?busca=&situacao=&categoria=&com_preco=&ordem=&pagina=` → `ListaCasamentosSaida { itens: list[ProdutoCasamentoSaida], total, pagina, por_pagina (20), categorias: list[str] }`; `ProdutoCasamentoSaida { id, nome, nome_en, imagem, categoria, preco_liga: Decimal|None, pendentes, confirmados, ignorados, em_outro, ia_sugere, situacao }`. `situacao` aceita `SITUACOES_PRODUTO + ("todos",)` (um filtro só; padrão `"esperando_decisao"`).
  - `GET /api/gestao/casamentos/{produto_id}?<mesmos filtros>` → `RevisaoSaida { produto: ProdutoLigaSaida, navegacao: NavegacaoSaida { posicao, total, anterior: int|None, proximo: int|None }, para_decidir, confirmados, ignorados: list[AnuncioRevisaoSaida], parecidos: list[ParecidoSaida], termos: list[str], termos_pedidos: bool }`.
    - `ProdutoLigaSaida { id, nome, nome_en, imagem, categoria, url, preco_liga, lojas, pistas: list[str] }`.
    - `AnuncioRevisaoSaida { anuncio_id, asin, titulo, url, imagem, preco: Decimal|None, vendedor: str|None, termos_variacao: list[str], ia: IaSaida|None { mesmo_produto, confianca, motivo, idioma }, origem: str|None, revisado_em: datetime|None, oportunidade: bool, casado_com: ParecidoSaida|None }`. `oportunidade` é **falso quando `ia` diz outro produto**.
    - `navegacao` segue a mesma consulta/ordem da lista (posição do produto entre os ids filtrados).
  - 404 `nao_encontrado` "Produto não está mais monitorado." quando `detalhe_casamento` devolve None.

- [ ] **Step 1: Testes** (`tests/api/test_gestao_casamentos.py`, fixtures `cliente`, `logar`, `sessoes`):
  - `test_sem_sessao_401_e_sem_permissao_403` (GRUPO ⇒ 403 nas duas rotas; OPERADOR com `revisar_casamentos` salvo como falso ⇒ 403).
  - `test_lista_ordena_com_preco_primeiro_e_pagina_de_20`.
  - `test_lista_filtro_situacao_todos_e_esperando_decisao`.
  - `test_revisao_agrupa_sem_abas_e_monta_imagem` (com `config.url_publica_imagens="https://img.teste"`, `imagem == "https://img.teste/produtos/x.webp"`; sem chave ⇒ `None`).
  - `test_revisao_sem_selo_oportunidade_quando_ia_diz_outro_produto`.
  - `test_navegacao_segue_filtros_da_lista` (3 produtos, filtro que pega 2 ⇒ `total == 2`, `anterior/proximo` certos).
  - `test_produto_inativo_404`.
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/api/test_gestao_casamentos.py -q`.
- [ ] **Step 3: Implementar** `exige_todas`, `imagens.py` (e trocar o uso em `rotas_oportunidades.py`), o roteador e o registro em `app.py`.
- [ ] **Step 4: Rodar** `uv run pytest tests/api -q` → PASS.
- [ ] **Step 5: Commit** `feat: management API to list and review matches`.

### Task 5: API de ações dos casamentos

**Files:**
- Modify: `src/tcg_sniper/api/rotas_gestao_casamentos.py`
- Test: `tests/api/test_gestao_casamentos_acoes.py` (portar os casos de `tests/admin/test_admin_casamento_acoes.py:72-286`)

**Interfaces:**
- Consumes: Task 4 (`RevisarCasamentos`, `AnuncioRevisaoSaida`).
- Produces:
  - `POST /api/gestao/casamentos/{produto_id}/anuncios/{anuncio_id}` corpo `DecisaoEntrada { acao: Literal["confirmar","ignorar","desfazer","trocar"], para_produto_id: int | None }` (`extra="forbid"`; `para_produto_id` obrigatório só em `trocar`) → `DecisaoSaida { anuncio: AnuncioRevisaoSaida, grupo: Literal["para_decidir","confirmados","ignorados"], mensagem: str | None }`. A origem vem de `repo_ia.origem_da_decisao`. `trocar` = `trocar(para)` + `ignorar(produto_id)` quando diferentes (como o admin antigo).
  - Erros: 404 (anúncio, par ou produto alvo inexistente/inativo), 409 `ja_confirmado` "Este anúncio já está confirmado em <nome do produto>." (`JaConfirmado`).
  - `GET /api/gestao/casamentos/anuncios/{anuncio_id}/produtos?busca=&de=` → `list[ParecidoSaida]` (sem busca: `sugestoes_para`; com busca: `buscar_produtos`; exclui `de` e o confirmado).
  - `POST /api/gestao/casamentos/{produto_id}/link` corpo `{ link: str }` → `AnuncioRevisaoSaida`; 400 `link_invalido` com `str(LinkInvalido)`.
  - `POST /api/gestao/casamentos/{produto_id}/rebuscar`, `/reavaliar`, `/termos` → `MensagemSaida { tipo: Literal["success","info","warning"], mensagem: str }` com os textos de `MENSAGENS_CASAMENTO` (mesma lógica de `_casador_parado`, movida para `consultas/casamentos.py` como `casador_parado(s, agora, config) -> str | None`).
  - Todas as escritas em `with estado.sessoes() as s, s.begin():`.

- [ ] **Step 1: Testes:** confirmar (pendente ⇒ confirmado, `grupo == "confirmados"`, origem `sugerido_ia` quando há avaliação), ignorar, desfazer, trocar (anúncio vai para o outro produto e fica ignorado neste), **409 `ja_confirmado` em confirmar duas vezes em produtos diferentes**, confirmar o mesmo par duas vezes é idempotente (200), link inválido 400, rebuscar fora da fila ⇒ mensagem `rebuscar_fora_da_fila`, reavaliar com IA desligada ⇒ `reavaliar_ia_desligada`, termos em produto casado ⇒ `termos_ja_casado`, permissão 403 em todas.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** as rotas.
- [ ] **Step 4: Rodar** `uv run pytest tests/api tests/admin -q` → PASS.
- [ ] **Step 5: Commit** `feat: management API actions for matches`.

### Task 6: Catálogo — consultas neutras e API

**Files:**
- Create: `src/tcg_sniper/consultas/catalogo_gestao.py` (move `condicoes_catalogo`, `buscar_catalogo`, `alterar_ativo_em_lote`, `alternar_ativo`, `FILTROS`, `JANELA_NOVOS`, `casa_nome` de `admin/consultas.py:28-215`; o admin importa de lá)
- Create: `src/tcg_sniper/api/rotas_gestao_catalogo.py`
- Modify: `src/tcg_sniper/api/app.py`
- Test: `tests/consultas/test_catalogo_gestao.py`, `tests/api/test_gestao_catalogo.py`

**Interfaces:**
- Consumes: Task 1, Task 2 (`registrar`, `TipoAcaoGestao.CATALOGO_LOTE/CATALOGO_PRODUTO`), Task 4 (`exige_todas`, `com_imagens`).
- Produces:
  - `linhas_catalogo(s, *, busca, monitorado: Literal["todos","sim","nao"], categoria, situacao: str | None, com_preco: bool, pagina: int, por_pagina: int = 25) -> PaginaCatalogo` com `LinhaCatalogo { produto, preco_liga, lojas, situacao_casamento, pendentes, confirmados, melhor_amazon: Decimal|None }` (situação por `classificar` de `consultas/catalogo.py`).
  - `contar_filtro(s, filtro: FiltroCatalogo) -> int` e `aplicar_lote(s, ativo: bool, alvo: FiltroCatalogo | list[int], agora) -> int`. `FiltroCatalogo` = dataclass com os mesmos campos de filtro.
  - `GET /api/gestao/catalogo?busca=&monitorado=&categoria=&situacao=&com_preco=&pagina=` (`ver_catalogo`) → `{ itens, total, pagina, por_pagina, categorias }`.
  - `PATCH /api/gestao/produtos/{id}` corpo `{ ativo: bool }` (`editar_catalogo`) → linha; registra `CATALOGO_PRODUTO {produto_id, ativo}`.
  - `POST /api/gestao/catalogo/lote` corpo `LoteEntrada { acao: Literal["ligar","desligar"], ids: list[int] | None, filtro: FiltroEntrada | None, esperado: int, confirmar: bool }` (exatamente um de `ids`/`filtro`) → `{ alvo: int, alterados: int }`. `confirmar=false` só conta (`alterados = 0`). `confirmar=true` e alvo ≠ `esperado` ⇒ 409 `contagem_mudou` com `{alvo}` na mensagem e nada alterado. Registra `CATALOGO_LOTE {acao, filtro|ids, alvo, alterados}` na mesma transação.
  - `GET /api/gestao/produtos/{id}` (`ver_catalogo`) → `ProdutoGestaoSaida { produto (com pistas), monitorado, liga: {preco, lojas, medio, lido_em}, melhor_amazon: {preco, diferenca_pct}|None, casamentos: {pendentes, confirmados, ignorados}, curva: dados do `historico_produto` de 30 dias ou None }`. Produto inativo **aparece** aqui (a gestão liga de volta).

- [ ] **Step 1: Testes de consulta:** `test_filtro_monitorado_e_situacao`, `test_contar_filtro_igual_ao_total_da_lista`, `test_aplicar_lote_por_ids_e_por_filtro_devolve_alterados`.
- [ ] **Step 2: Testes de API:** 403 sem `ver_catalogo`/`editar_catalogo`; PATCH liga e desliga e grava `acao_gestao`; **lote `confirmar=false` não altera nada**; **lote com `esperado` errado ⇒ 409 `contagem_mudou` e nada alterado**; lote por filtro de categoria altera só ela e grava `acao_gestao` com `usuario_id` de quem fez; produto inativo abre em `GET /api/gestao/produtos/{id}`.
- [ ] **Step 3: Rodar e ver falhar.**
- [ ] **Step 4: Implementar** (mover, criar as funções e as rotas; admin antigo importa as funções movidas).
- [ ] **Step 5: Rodar** `uv run pytest -q` e `uv run ruff check` → PASS.
- [ ] **Step 6: Commit** `feat: management catalog API with bulk toggle`.

### Task 7: Front — layout da gestão, menu e rotas

**Files:**
- Create: `web/src/componentes/LayoutGestao.tsx`, `web/src/componentes/Foto.tsx`, `web/src/componentes/ExigeTodas.tsx`
- Modify: `web/src/App.tsx:50-75`, `web/src/paginas/Gestao.tsx:6-15`, `web/src/tipos.ts`, `web/src/rotas.test.tsx`
- Create: rota `GET /api/gestao/menu` em `rotas_gestao_casamentos.py` → `{ casamentos_esperando: int }` (`ver_area_gestao`; 0 quando falta `revisar_casamentos`), teste em `tests/api/test_gestao_casamentos.py`
- Test: `web/src/componentes/LayoutGestao.test.tsx`

**Interfaces:**
- Produces:
  - `LayoutGestao` (`drawer lg:drawer-open`): itens Dashboard (página atual de Gestão por enquanto), Casamentos (com `badge` do `casamentos_esperando`, recarrega a cada 60 s), Catálogo, e os itens ainda antigos (Ofertas, Serviços, Mensagens, Configurações, Logs) apontando para `enderecoAdminAntigo`; Usuários e Acessos. Cada item só para quem pode.
  - `Foto({ src, alt, tamanho: "p" | "m" | "g" })`: `img` com `loading="lazy"` ou placeholder (`skeleton` estático) sem `src`; toque em `g` abre `modal` com a foto grande.
  - `ExigeTodas({ permissoes: Permissao[], children })`: redireciona para `/sem-acesso` se faltar alguma.
  - Rotas: `/gestao/casamentos`, `/gestao/casamentos/:produtoId`, `/gestao/catalogo`, `/gestao/produtos/:id` dentro de `LayoutGestao`.
  - `Gestao.tsx` tira Casamentos e Catálogo de `TELAS_ANTIGAS`.

- [ ] **Step 1: Testes:** `LayoutGestao` mostra o selo "96" com `apiFalsa({"GET /api/gestao/menu": ok({casamentos_esperando: 96})})`; operador sem `revisar_casamentos` não vê o item; `rotas.test.tsx` ajustado (Casamentos sai das telas antigas).
- [ ] **Step 2: Rodar e ver falhar:** `(cd web && npm test)`.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar** `(cd web && npm test && npm run build)` e `uv run pytest tests/api -q` → PASS.
- [ ] **Step 5: Commit** `feat: management layout with side menu`.

### Task 8: Front — lista de Casamentos

**Files:**
- Create: `web/src/paginas/gestao/Casamentos.tsx`, `web/src/filtrosUrl.ts`
- Test: `web/src/paginas/gestao/Casamentos.test.tsx`, `web/src/filtrosUrl.test.ts`

**Interfaces:**
- Consumes: Task 4 (`GET /api/gestao/casamentos`), Task 7 (`Foto`, rota).
- Produces: `useFiltrosUrl<T extends Record<string,string>>(padroes: T): [T, (mudancas: Partial<T>) => void]` (lê e grava `useSearchParams`, volta `pagina` para 1 quando outro filtro muda); a lista monta o link da revisão como `/gestao/casamentos/<id>?<mesma query>`.

- [ ] **Step 1: Testes:**
  - `aplica filtro sem botão e grava na URL` (mudar o `select` de situação chama `GET /api/gestao/casamentos?situacao=todos&...`).
  - `busca espera o usuário parar de digitar` (uma chamada só depois de digitar "goblin").
  - `cartão leva à revisão com a mesma query`.
  - `Revisar em sequência abre o primeiro da lista filtrada`.
  - `vazio com filtro mostra Limpar filtros`.
  - **`voltar restaura busca, filtros e página`** (render em `/gestao/casamentos?busca=lair&pagina=3` ⇒ campo com "lair" e chamada com `pagina=3`).
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar:** filtros (busca, situação, categoria, com preço, ordem) num `fieldset` em grade; lista de cartões abaixo de `md` e `table` a partir de `md`; contagens com `badge`; `join` de paginação; estados com `Carregando`, `alert alert-error` + "Tentar de novo", vazio.
- [ ] **Step 4: Rodar** `(cd web && npm test)` → PASS.
- [ ] **Step 5: Commit** `feat: match list in management area`.

### Task 9: Front — revisão de um produto

**Files:**
- Create: `web/src/paginas/gestao/RevisaoCasamento.tsx`, `web/src/componentes/CartaoAnuncio.tsx`, `web/src/componentes/ModalOutroProduto.tsx`
- Test: `web/src/paginas/gestao/RevisaoCasamento.test.tsx`

**Interfaces:**
- Consumes: Task 4 e 5 (rotas e tipos), Task 7 (`Foto`), Task 8 (`useFiltrosUrl` para manter a query na navegação).
- Produces: `CartaoAnuncio({ anuncio, grupo, onDecidir(acao), ocupado })` com o título destacando `termos_variacao` (`span` com `font-semibold text-warning`), parecer da IA em `badge` (mesmo ⇒ `badge-success`/`badge-warning` por confiança ≥ 90; outro ⇒ `badge-error`) e motivo `truncate` com `tooltip`.

- [ ] **Step 1: Testes:**
  - `mostra Liga fixa à esquerda e os três grupos sem abas` (sem `role="tab"` na página).
  - `C move o cartão para Confirmados sem nova busca da página` (um POST; nenhum novo `GET /api/gestao/casamentos/31`).
  - **`409 ja_confirmado devolve o cartão e mostra a mensagem`**.
  - **`404 do produto mostra "Produto não está mais monitorado" e o botão Próximo`**.
  - `atalhos C, I, setas e Enter` (Enter navega para `proximo` com a mesma query).
  - `Ignorados começam fechados` (`collapse` sem `checked`).
  - `É de outro produto abre modal com parecidos e busca; escolher chama trocar`.
  - `menu ⋯ Rebuscar agora mostra a mensagem da API em alert`.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar:** topo com "12 de 96", `join` "← Anterior · Pular · Próximo →" (Pular = próximo sem decidir) e "Voltar à lista"; menu ⋯ (`dropdown`) com Rebuscar agora, Reavaliar com a IA, Gerar termos de busca e o campo "Casar por link ou ASIN" (`POST .../link`, o anúncio entra em Confirmados); grade `lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]` com a Liga `lg:sticky lg:top-4` (no celular a Liga fica em cima, compacta); grupos com `h2` + lista; estado otimista por cartão; atalhos só com foco fora de `input`; `kbd` com a dica no rodapé (`hidden lg:block`).
- [ ] **Step 4: Rodar** `(cd web && npm test && npm run build)` → PASS.
- [ ] **Step 5: Commit** `feat: one-product match review screen`.

### Task 10: Front — Catálogo e Produto na gestão

**Files:**
- Create: `web/src/paginas/gestao/Catalogo.tsx`, `web/src/paginas/gestao/ProdutoGestao.tsx`, `web/src/componentes/ModalConfirmarLote.tsx`
- Test: `web/src/paginas/gestao/Catalogo.test.tsx`, `web/src/paginas/gestao/ProdutoGestao.test.tsx`

**Interfaces:**
- Consumes: Task 6 (rotas), Task 7 (`Foto`), Task 8 (`useFiltrosUrl`), `CurvaPreco` existente.

- [ ] **Step 1: Testes do Catálogo:**
  - `chave da linha liga e desliga no lugar` (PATCH; sem recarregar a lista); erro ⇒ chave volta e `alert`.
  - `marcar linhas mostra a barra de lote com N selecionados`.
  - `Selecionar todos do filtro pede a contagem e o modal mostra "Desligar 412 produtos?"` (POST `confirmar=false` depois `confirmar=true` com `esperado: 412`).
  - **`409 contagem_mudou mostra o número novo e pede confirmar de novo`**.
  - Usuário sem `editar_catalogo` não vê chaves nem caixas de seleção.
- [ ] **Step 2: Testes do Produto:** mostra monitorar, preços, contagens e "Revisar este produto" (link para `/gestao/casamentos/<id>`); "Voltar ao Catálogo" usa a query de onde veio; sem curva ⇒ texto "Ainda não há leituras suficientes".
- [ ] **Step 3: Rodar e ver falhar.**
- [ ] **Step 4: Implementar** (cartões no celular, `table` a partir de `md`; barra de lote `sticky bottom-0` com `alert`; `modal` de confirmação com o número; `CurvaPreco` com 30 dias; "Ver no Mercado" ainda não existe ⇒ link "Histórico do produto" para `/produtos/<id>` quando o usuário tem `ver_oportunidades`).
- [ ] **Step 5: Rodar** `(cd web && npm test && npm run build)` → PASS.
- [ ] **Step 6: Commit** `feat: catalog and product pages in management area`.

### Task 11: Ponta a ponta, layout e documentação

**Files:**
- Modify: `tests/e2e/test_ponta_a_ponta.py`, `scripts/verificar_layout.py`
- Modify: `docs/PENDENCIAS.md`, `docs/IMPLANTACOES.md`, `README.md`

- [ ] **Step 1: Ponta a ponta:** operador entra, abre Casamentos, "Revisar em sequência", confirma um anúncio (cartão vai para Confirmados sem recarregar), "Próximo", volta à lista com o filtro; no Catálogo desliga um produto pela chave e um lote de 2 pelo filtro de categoria (modal com "2").
- [ ] **Step 2: Layout:** `verificar_layout.py` passa pelas 4 telas novas em 390 e 1440 px, temas claro e escuro, com um produto de nome de 120 caracteres e sem foto; falha se `document.documentElement.scrollWidth > innerWidth`.
- [ ] **Step 3: Rodar** `TCG_E2E=1 DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test uv run pytest tests/e2e -q`, `uv run python scripts/verificar_layout.py` (com o site de teste no ar, como hoje) → PASS.
- [ ] **Step 4: Docs:** `IMPLANTACOES.md` com o passo a passo (backup, migração `a1c4e7b9d2f6`, `docker compose up -d --build`, conferir menu e Casamentos); `PENDENCIAS.md` marca a entrega 3A com o commit do merge e move para "Concluídas"; README com as telas novas.
- [ ] **Step 5: Commit** `docs: phase 3A deploy notes and pending list`.
