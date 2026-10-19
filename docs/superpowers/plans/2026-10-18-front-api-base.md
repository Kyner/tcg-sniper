# Front e API separados — fase 1 (base) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um serviço `api` (FastAPI, só JSON, porta `127.0.0.1:8100`) com login por código no WhatsApp e permissões configuráveis por papel, e um front React (`web/`, Caddy em `127.0.0.1:8090`) com a área de negócio vazia, a área de gestão com Usuários e Acessos, e as telas de sem acesso e sistema indisponível — sem mexer no admin atual (`:8000`).

**Architecture:** `src/tcg_sniper/api/` é um FastAPI novo que reaproveita o banco (`db/repositorio_acesso.py`, novo) e o módulo `avisos` (três tipos novos e envio individual, com validade de 5 min, pela mesma tabela `mensagem_saida` que o `notificador` já envia). Toda rota protegida declara `exige(Permissao.X)`; a dependência lê o cookie `sessao`, confere a sessão no banco e as permissões efetivas do papel (grade `permissao_papel` com cache de 5 s, invalidado ao salvar). O front (`web/`, React + Vite + TypeScript + Tailwind + DaisyUI 5) chama `/api` na mesma origem: no container o Caddy serve o build e repassa `/api` para `api:8100`; em desenvolvimento e no teste ponta a ponta o Vite faz o mesmo repasse.

**Tech Stack:** Python 3.12 (Docker; o venv local pode ser 3.14), uv, SQLAlchemy 2 + Alembic, Postgres 16, FastAPI, pytest (+ respx), Evolution API; Node 24 / npm 11, React 19.1.0, React Router 7.6.2, Vite 6.3.5, TypeScript 5.8.3, Tailwind CSS 4.1.11, DaisyUI 5.2.0, Vitest 3.2.4 + Testing Library, Caddy 2.10.0; Playwright (o pacote Python que o projeto já usa) no ponta a ponta; Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-18-front-api-base-design.md`

## Global Constraints

- Nomes, comentários, mensagens de erro e textos de tela em português, como o resto do código (identificadores em português; componentes React com nomes em português, ex.: `Entrar`, `Acessos`). Mensagens de commit em inglês, no formato `feat:`/`fix:`/`test:`/`docs:`/`chore:`, **sem** linha `Co-Authored-By` nem qualquer trailer de IA.
- Repositório público: nada de dado pessoal em código, teste, fixture ou documento. Telefones de teste são obviamente falsos: `+5511900000001` (admin), `+5511900000002` (grupo), `+5511900000003` (operador), `+55119000000NN` para os demais; exemplos de tela usam `(11) 9XXXX-XXXX`.
- Dados pessoais (verbatim do spec): "números ficam só no banco; nunca em log (mascarados: `+55 11 9****-**34`), nunca no repositório, nunca no grupo. Código e token nunca em log, banco (só hash) ou mensagem de grupo." Na resposta da API o número sai só mascarado (`numero_mascarado`).
- Hashes (verbatim do spec): "código, token de sessão e número (para contagem de limites) são guardados como **HMAC-SHA256 com chave secreta** `SEGREDO_API` do `.env` (obrigatória; o serviço `api` não sobe sem ela; documentada no `.env.example`), nunca SHA-256 puro." No código: sempre `api.segredos.hash_segredo(segredo, texto)`; nada de `hashlib.sha256` direto. Testes usam o segredo falso fixo `SEGREDO_TESTE` (`tests/fakes_api.py`, o mesmo valor do fixture `config` de `tests/conftest.py`), nunca um segredo real.
- Superadmin (spec, seção "Superadmin"): um só (`usuario.superadmin`, índice único parcial), criado e trocado só pelos comandos locais `criar-superadmin`/`trocar-superadmin`; sempre `admin`, ativo e com todas as permissões; nunca rebaixado, desativado nem tem sessões encerradas pela API por ninguém (só ele encerra as próprias); só ele cria/edita/rebaixa/desativa admins e encerra sessões de admins (403 `so_superadmin`). Não existe regra de "último admin".
- Cookie (verbatim do spec): `sessao`, `HttpOnly`, `SameSite=Strict`, `Path=/`, `Secure` quando servido em HTTPS. Sessão: 30 dias, renovada no uso. Código: 6 dígitos, aleatório criptográfico, 5 min, 5 tentativas erradas invalidam. Limites: até 3 códigos por número a cada 15 min; até 20 pedidos por hora no total; acima disso 429.
- Erros da API sempre em JSON `{"erro": "<código>", "mensagem": "<texto em português>"}`; 401 sem sessão, 403 sem permissão, 404, 409 conflito, 422 validação, 429 limite. Nenhuma resposta de erro ecoa o valor recebido (número, código).
- Portas: `api` em `127.0.0.1:8100`, `web` em `127.0.0.1:8090`; o admin antigo (`:8000`) não muda. Nenhuma mensagem de WhatsApp leva endereço do sistema (regra dos avisos; `tests/avisos/test_regras_globais.py`). Fora de `avisos/`, nada chama `enfileirar`; `host_publico` só no admin, na configuração, no banco e nos avisos.
- Front: só componentes DaisyUI 5 e utilitários Tailwind, classes literais (nunca montadas por concatenação ou template string); temas `winter` (claro, padrão) e `night` (escuro), chave `tema` no `localStorage` como no admin. Versões exatas no `package.json` (sem `^`/`~`), `.npmrc` com `save-exact=true`. Código simples e comentado: cada arquivo começa com um comentário dizendo para que serve.
- Testes Python só no Postgres de teste (container `postgres-teste`, `127.0.0.1:5433`), um banco por lane (o fixture `engine` apaga o schema). Criar o banco: no checkout principal (`D:/Git/Pessoal/Python/tcg-sniper`) `docker compose exec -T postgres-teste createdb -U tcg tcg_test_<lane>`; de dentro de um worktree `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_<lane>` ("already exists" é ok). `<lane>` = `t` + número da tarefa (ex.: `tcg_test_t4`). Ao fim de cada tarefa, verdes: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_<lane> uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`. Tarefas que mexem em `web/` também: `npm ci` (ou `npm install` na Task 7, que cria o lock), `npm test` e `npm run build`, dentro de `web/`.
- Nunca mexer no checkout nem na stack de produção: nada de `docker compose up/down/build/restart/run` nem `migrate` contra o Postgres de produção. Cada lane trabalha no próprio worktree (`superpowers:using-git-worktrees`) e nada é escrito fora dele (pasta temporária do pytest à parte): `node_modules` dentro de `web/` pode; `npm install -g` nunca; o Chromium do ponta a ponta vai em `<worktree>/.playwright-navegadores` (`PLAYWRIGHT_BROWSERS_PATH`), instalado pelo `uv run playwright install chromium` do pacote Python que o projeto já tem. Imagens Docker de verificação usam nomes próprios (`tcg-sniper-web:verificacao`) e são apagadas no fim.
- Todo servidor que uma lane sobe (uvicorn, `vite preview`, container de verificação) é parado antes de a lane terminar.

## Review Focus

1. **Quem tem `gerir_usuarios` mas não é o superadmin** (admin comum, ou operador que ganhou a permissão na grade) tentando criar um admin, promover alguém a admin, editar/rebaixar/desativar um admin ou encerrar a sessão de um admin: a API recusa com 403 `so_superadmin` (sem isso, a grade vira escada para o admin). Testes na Task 5 (`test_quem_nao_e_superadmin_nao_cria_nem_mexe_em_admin`, `test_superadmin_gere_admins`).
2. **O superadmin sendo rebaixado, desativado ou tendo sessões encerradas** por qualquer um pela API (inclusive ele mesmo, sem querer, na tela de editar): 403 `superadmin_protegido`, nada muda; só ele encerra as próprias sessões; só os comandos locais criam (`criar-superadmin`) ou trocam (`trocar-superadmin`) o superadmin, e o banco garante no máximo um (índice único parcial). Testes na Task 1 (`test_superadmin_unico_e_troca`), Task 5 (`test_superadmin_nunca_rebaixado_desativado_nem_encerrado`) e Task 6 (`test_criar_superadmin_uma_vez_so`, `test_trocar_superadmin`).
3. **`SEGREDO_API` ausente ou fraca:** a API (`criar_app` e `tcg-sniper api`) e o `codigo-acesso` recusam começar com mensagem clara; todo hash (código, token, número do pedido) é HMAC-SHA256 com ela, nunca SHA-256 puro. Testes na Task 3 (`test_hash_e_hmac_com_o_segredo`, `test_app_nao_sobe_sem_segredo`) e Task 6 (`test_api_recusa_subir_sem_segredo`).
4. **Número digitado em formatos diferentes** ("(11) 90000-0002", "+55 11 90000 0002", "11900000002", com ou sem o 55): é sempre o mesmo usuário, no login, no limite por número e na checagem de duplicado. Testes na Task 1 (`test_normalizar_numero_formatos`), Task 4 (`test_fluxo_completo_com_numero_formatado`, `test_quarto_pedido_do_mesmo_numero_em_15_min_e_recusado`) e Task 5 (`test_numero_duplicado_em_outro_formato_409`).
5. **WhatsApp fora ou notificador pausado por mais de 5 min com um código na fila**: quando volta, o código vencido não sai (nem pelo "Reenviar" do admin) e o texto com o código some do banco. Testes na Task 2 (`test_codigo_vencido_na_fila_nao_sai_nem_e_reenviado`, `test_individual_vai_para_o_numero_e_o_texto_some_depois`).
6. **Erro da Evolution que repete o número da pessoa** (ex.: `HTTP 400: {"message":"5511900000001 não está no WhatsApp"}`): o número sai mascarado em `ultimo_erro`, no log e no aviso "mensagem não enviada" do grupo admin. Teste na Task 2 (`test_erro_que_repete_o_numero_e_mascarado`).

## Decisões tomadas neste plano (o spec não fixava)

- **Destino individual na fila:** `mensagem_saida.destino` ganha o valor `"individual"` e duas colunas: `numero` (E.164, obrigatório só para individual — check no banco) e `expira_em` (validade própria; vencida vira `expirada` sem enviar, mesmo com `ignorar_validade`). `Destino.INDIVIDUAL = "individual"` no enum do notificador. O texto com o código fica na fila só enquanto está pendente (o spec manda o teste ponta a ponta ler o código da fila): ao sair (enviada, expirada, falha ou descartada) o texto vira `repo_msg.TEXTO_APAGADO`. "Reenviar" não vale para individual (409 no admin). A tela Mensagens do admin mostra o destino `individual`, nunca o número.
- **Envio individual pelos avisos:** `avisos.servico.avisar_individual(s, tipo, numero, dados, agora, validade)` — o único caminho para mensagem individual; `avisar` recusa (log) tipos individuais. `CODIGO_ACESSO` desligado na aba Avisos = ninguém recebe código (fica só o acesso de emergência); a descrição do tipo diz isso.
- **Severidade nova `ACESSO` (🔑)** para o `CODIGO_ACESSO`; `SEGURANCA_USUARIO` e `SEGURANCA_LIMITE` são `ATENCAO` (🟡). Origem no rodapé: `acesso`. Na aba Avisos o selo de destino passa a dizer "grupo admin", "grupo oportunidades" ou "só para a pessoa", e a severidade nova tem selo "Acesso".
- **Nada de número no grupo:** os avisos de segurança dizem nome de quem mudou e de quem foi mudado; o de limite diz só "Número com final 34". A chave do `SEGURANCA_LIMITE` é `numero:<12 primeiros do hash>` (ou `total`), nunca o número; ele agrupa e não é resolvido (como `MENSAGEM_NAO_ENVIADA`).
- **Limites contam pedidos, não códigos:** tabela nova `pedido_codigo` (`em`, `numero_hash`, `resultado`), na mesma migração. Assim número inexistente também recebe 429 no 4º pedido (sem isso o 429 revelaria quem tem cadastro). Só pedidos `aceito` contam; janela aberta (`em > agora - janela`). Pedidos e códigos com mais de 1 dia são apagados a cada pedido.
- **Só o último código vale.** Pedir outro invalida o anterior (mais simples e as 5 tentativas valem para o código atual).
- **Hash:** `api.segredos.hash_segredo(segredo, texto)` = HMAC-SHA256 em hexadecimal com `SEGREDO_API` (campo `Config.segredo_api: SecretStr | None`, opcional no `Config` porque os outros serviços não usam; quem precisa chama `exigir_segredo(config)`). `exigir_segredo` recusa vazio, o valor de exemplo `trocar-este-segredo` e menos de 32 caracteres (`SegredoAusente`, mensagem com o comando para gerar: `python -c "import secrets; print(secrets.token_urlsafe(32))"`). Exigem: `criar_app` (guarda em `app.state.segredo`), `tcg-sniper api` e `tcg-sniper codigo-acesso`; `criar-superadmin` e `trocar-superadmin` não criam código nem sessão, então não exigem. Trocar a `SEGREDO_API` derruba todas as sessões e códigos abertos (todos entram de novo) e zera a contagem dos limites — documentado no `.env.example`.
- **Superadmin no banco:** `usuario.superadmin` (bool, padrão `false`), índice único parcial `uq_usuario_superadmin` (`WHERE superadmin`) e check `ck_usuario_superadmin` (`NOT superadmin OR (papel = 'admin' AND ativo)`): o banco garante um só, sempre admin e ativo. `trocar-superadmin` passa a marca para outro usuário ativo existente (que vira admin; o antigo continua admin comum) e avisa `SEGURANCA_USUARIO` "superadmin trocado".
- **Erros do superadmin:** 403 `so_superadmin` (quem não é o superadmin mexendo em admin ou dando o papel admin); 403 `superadmin_protegido` (rebaixar, desativar ou encerrar sessão do superadmin, por qualquer um; vem antes do `so_superadmin`). PATCH no superadmin com `papel: "admin"` e `ativo: true` não é rebaixar (a tela manda o formulário inteiro). Qualquer pessoa com `gerir_usuarios` encerra as **próprias** sessões (o spec diz que o superadmin encerra as dele; vale igual para os outros).
- **Cookie renovado no `GET /api/auth/eu`:** a sessão no banco renova a cada uso; o cookie (`Max-Age` 30 dias) é regravado no `eu`, que o front chama ao abrir.
- **Grade:** `permissao_papel.permissao` é texto sem check (cada fase acrescenta permissões sem migração; linha com permissão desconhecida é ignorada). Cache de 5 s por instância do app (`GradePermissoes`), invalidado no `PUT /api/acessos`; cada teste cria o próprio app, então o cache não vaza entre testes. `PUT` com o papel admin responde 422 `papel_travado`; linhas do admin no banco são ignoradas.
- **Regras de gestão de usuários:** as do superadmin acima (sem regra de "último admin"); o número não muda depois de criado (para trocar: desativar e criar outro); reativar também avisa (`SEGURANCA_USUARIO` "usuário reativado").
- **Número:** `formatacao.normalizar_numero` aceita espaços, parênteses, pontos e traços; sem `+`, 10 ou 11 dígitos viram Brasil (`+55`). E.164 no banco (check `^[+][1-9][0-9]{9,14}$`).
- **`aparelho`:** "Navegador · Sistema" (ex.: "Chrome · Windows") tirado do User-Agent, nunca o User-Agent inteiro.
- **`tcg-sniper api`** escuta em `127.0.0.1` por padrão; o compose passa `--host 0.0.0.0` dentro do container e publica só em `127.0.0.1:8100`. `Secure` do cookie: `X-Forwarded-Proto: https` (Caddy/túnel) ou esquema https.
- **`/api/docs`** e **`/api/openapi.json`** exigem `ver_documentacao_api`; o FastAPI não registra os seus `/docs` e `/openapi.json` padrão.
- **Ponta a ponta sem o Caddy:** o teste Playwright (Python, `tests/e2e/`, só com `TCG_E2E=1`) sobe o uvicorn e o `vite preview` (que repassa `/api` como o Caddy); o Caddy é conferido na Task 9 com `docker build` + `caddy validate` + um container de verificação. O mesmo teste roda o `verificar_layout` nas telas novas.
- **`verificar_layout.py`** confere o front quando recebe `WEB_NUMERO` e `WEB_CODIGO` (código do `tcg-sniper codigo-acesso`); `SO_WEB=1` pula o admin. Endereço do front: `WEB_BASE` (padrão `http://web:8090`, a rede do compose vista do container do admin).
- **Link para o admin antigo** no front: `http(s)://<mesmo host>:8000/<tela>` montado no navegador (`web/src/enderecos.ts`); nunca vai para mensagem de WhatsApp.

---

## Ondas (para execução paralela)

- **Onda A (em paralelo):** Task 1 (banco: modelos, migração, repositório e números) e Task 7 (front base) — independentes.
- **Onda B (em paralelo):** Task 2 (avisos novos e envio individual) e Task 3 (API base: erros, sessão, permissões, grade) — ambas dependem só da 1; Task 8 (front: Usuários e Acessos) — depende da 7.
- **Onda C (em paralelo):** Task 4 (login pelo WhatsApp) e Task 5 (usuários, sessões e avisos de segurança) — dependem da 2 e da 3.
- **Onda D (em paralelo):** Task 6 (CLI `api`, `codigo-acesso`, `criar-superadmin`, `trocar-superadmin`) — depende da 4 e da 5; Task 9 (containers `api` e `web`, Caddy) — depende da 8.
- **Onda E:** Task 10 (ponta a ponta, `verificar_layout`, regra global de log, README e `docs/PENDENCIAS.md`) — depende de todas.
- Conflitos esperados e como resolver: `src/tcg_sniper/api/app.py` (Task 4 e Task 5 acrescentam cada uma um `app.include_router(...)` logo abaixo do de acessos: manter os dois); `tests/api/` (arquivos novos diferentes; `tests/fakes_api.py` só a Task 3 cria); `.gitignore` (Task 7 acrescenta `web/`, Task 10 acrescenta `.playwright-navegadores/`: manter tudo); `src/tcg_sniper/admin/static/admin.css` (só a Task 2 regenera; na integração, se houver conflito, rodar `uv run python scripts/gerar_css.py` e commitar).

## Arquivos

| Arquivo | Responsabilidade | Tasks |
|---|---|---|
| `src/tcg_sniper/db/models.py`, migração `f8d2a6c4e1b3_acesso.py` (nova) | `Papel`, `Usuario` (com `superadmin`), `CodigoAcesso`, `Sessao`, `PermissaoPapel`, `PedidoCodigo`; `mensagem_saida.numero/expira_em` e destino `individual` | 1 |
| `src/tcg_sniper/db/repositorio_acesso.py` (novo) | consultas e gravações do login, do superadmin, das sessões, dos pedidos e da grade | 1 |
| `src/tcg_sniper/formatacao.py` | `normalizar_numero`, `mascarar_numero`, `ocultar_numero` | 1 |
| `src/tcg_sniper/notificador/base.py`, `avisos/catalogo.py`, `avisos/servico.py` | `Destino.INDIVIDUAL`, `Severidade.ACESSO`, `CODIGO_ACESSO`, `SEGURANCA_USUARIO`, `SEGURANCA_LIMITE`, `avisar_individual` | 2 |
| `src/tcg_sniper/db/repositorio_mensagens.py`, `notificador/servico.py` | fila individual: número, validade, texto apagado, erro sem número | 2 |
| `src/tcg_sniper/admin/app.py`, `admin/consultas_mensagens.py`, `admin/templates/configuracoes.html`, `admin/static/admin.css` | destino individual em Mensagens e na aba Avisos | 2 |
| `src/tcg_sniper/api/__init__.py`, `app.py`, `erros.py`, `segredos.py`, `permissoes.py`, `dependencias.py`, `rotas_acessos.py` (novos) | app, JSON de erro, sessão, `exige`, grade com cache, `/api/acessos`, `/api/saude`, `/api/docs`, HMAC com `SEGREDO_API` | 3 |
| `src/tcg_sniper/config.py`, `.env.example` | `SEGREDO_API` (campo `segredo_api` e documentação) | 3 |
| `tests/fakes_api.py`, `tests/api/conftest.py` (novos), `tests/conftest.py` | relógio, usuário logado e segredo falso nos testes da API | 3 |
| `src/tcg_sniper/api/acesso.py`, `api/rotas_auth.py` (novos) | pedir código, entrar, sair, eu, limites | 4 |
| `src/tcg_sniper/api/avisos_acesso.py`, `api/rotas_usuarios.py` (novos), `api/rotas_acessos.py` | usuários, sessões, avisos `SEGURANCA_USUARIO` | 5 |
| `src/tcg_sniper/cli.py` | `api`, `codigo-acesso`, `criar-superadmin`, `trocar-superadmin` | 6 |
| `web/` (novo: `package.json`, `vite.config.ts`, `src/...`) | front React | 7, 8 |
| `web/Dockerfile`, `web/Caddyfile`, `web/.dockerignore`, `docker-compose.yml`, `.dockerignore` | containers `api` e `web` | 9 |
| `tests/e2e/test_ponta_a_ponta.py` (novo), `scripts/verificar_layout.py`, `tests/avisos/test_regras_globais.py`, `.gitignore`, `README.md`, `docs/PENDENCIAS.md` | ponta a ponta, layout, regra de log, documentação | 10 |

---

### Task 1: Banco do login (modelos, migração, repositório e números)

**Files:**
- Modify: `src/tcg_sniper/db/models.py` (enum `Papel` junto dos outros enums; classes novas no fim, `Usuario` com `superadmin`; `MensagemSaida` ganha `numero`/`expira_em` e o check novo)
- Create: `src/tcg_sniper/db/migrations/versions/f8d2a6c4e1b3_acesso.py`
- Create: `src/tcg_sniper/db/repositorio_acesso.py`
- Modify: `src/tcg_sniper/formatacao.py`
- Test: `tests/db/test_repositorio_acesso.py` (novo), `tests/test_numeros.py` (novo); `tests/db/test_migracao.py::test_migracao_igual_aos_modelos` (já existe) confere modelo × migração

**Interfaces:**
- Consumes: `db.models._enum`, `DATA`, `Base`, `MensagemSaida`, `StatusMensagem` (existentes); head atual do Alembic `e4b7c2d9a1f6`.
- Produces:
  - `models.Papel` (StrEnum): `GRUPO="grupo"`, `OPERADOR="operador"`, `ADMIN="admin"`.
  - `models.Usuario(id, nome, numero, papel: Papel, ativo: bool, superadmin: bool, criado_em)` (no máximo um `superadmin` — índice único parcial `uq_usuario_superadmin`; check `ck_usuario_superadmin`: superadmin é admin e ativo); `models.CodigoAcesso(id, usuario_id, hash_codigo, criado_em, expira_em, tentativas, usado_em)`; `models.Sessao(id, usuario_id, hash_token, aparelho, criada_em, ultimo_uso_em, expira_em, encerrada_em)`; `models.PermissaoPapel(papel: Papel, permissao: str, permitido: bool)`; `models.PedidoCodigo(id, em, numero_hash, resultado)`; `MensagemSaida.numero: str | None`, `MensagemSaida.expira_em: datetime | None`.
  - `repositorio_acesso`: `ACEITO = "aceito"`, `RETENCAO = timedelta(days=1)`, `class NumeroJaCadastrado(Exception)`, `class SuperadminJaExiste(Exception)`; `criar_usuario(s, nome: str, numero: str, papel: Papel, agora: datetime) -> Usuario`; `usuario_por_numero(s, numero: str) -> Usuario | None`; `listar_usuarios(s) -> list[Usuario]`; `superadmin_atual(s) -> Usuario | None`; `criar_superadmin(s, nome: str, numero: str, agora: datetime) -> Usuario` (`SuperadminJaExiste` se já houver um; `NumeroJaCadastrado` se o número for de alguém); `trocar_superadmin(s, novo: Usuario) -> Usuario | None` (passa a marca para `novo`, que vira admin; devolve o antigo, que continua admin comum, ou None se não havia); `criar_codigo(s, usuario_id: int, hash_codigo: str, agora: datetime, validade: timedelta) -> CodigoAcesso`; `ultimo_codigo(s, usuario_id: int) -> CodigoAcesso | None` (travado `FOR UPDATE`); `criar_sessao(s, usuario_id: int, hash_token: str, aparelho: str, agora: datetime, validade: timedelta) -> Sessao`; `sessao_por_hash(s, hash_token: str) -> Sessao | None`; `sessoes_ativas(s, usuario_id: int, agora: datetime) -> list[Sessao]` (último uso primeiro); `contar_sessoes_ativas(s, agora: datetime) -> dict[int, int]`; `encerrar_sessao(s, sessao: Sessao, agora: datetime) -> None`; `encerrar_sessoes_do_usuario(s, usuario_id: int, agora: datetime) -> int`; `registrar_pedido(s, numero_hash: str, resultado: str, agora: datetime) -> None`; `contar_pedidos(s, desde: datetime, numero_hash: str | None = None) -> int` (só `aceito`, `em > desde`); `limpar_antigos(s, agora: datetime) -> None`; `grade_salva(s) -> dict[tuple[Papel, str], bool]`; `salvar_permissao(s, papel: Papel, permissao: str, permitido: bool) -> None`.
  - `formatacao.normalizar_numero(texto: str) -> str` (ValueError se inválido); `formatacao.mascarar_numero(numero: str) -> str`; `formatacao.ocultar_numero(texto: str, numero: str) -> str`.

- [ ] **Step 1: Banco da lane**

Run (de dentro do worktree): `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_t1`
Expected: sem saída (ou "already exists").

- [ ] **Step 2: Escrever os testes (falham)**

Crie `tests/test_numeros.py`:

```python
import pytest

from tcg_sniper.formatacao import mascarar_numero, normalizar_numero, ocultar_numero


@pytest.mark.parametrize(
    "texto",
    [
        "(11) 90000-0001",
        "11 90000-0001",
        "11900000001",
        "+55 11 90000-0001",
        "+55 (11) 90000.0001",
        "5511900000001",
        " +5511900000001 ",
    ],
)
def test_normalizar_numero_formatos(texto):
    assert normalizar_numero(texto) == "+5511900000001"


def test_normalizar_fixo_e_estrangeiro():
    assert normalizar_numero("(11) 3000-0001") == "+551130000001"
    assert normalizar_numero("+1 202 555 0100") == "+12025550100"


@pytest.mark.parametrize(
    "texto", ["", "abc", "123", "+0 11 90000-0001", "11 90000-00012345678", "１１９０００００００１", "+55 11 9000O-0001"]
)
def test_normalizar_recusa(texto):
    with pytest.raises(ValueError):
        normalizar_numero(texto)


def test_mascarar_numero():
    assert mascarar_numero("+5511900000034") == "+55 11 9****-**34"
    assert mascarar_numero("+551130000034") == "+55 11 3***-**34"
    assert mascarar_numero("+12025550134") == "+12 *******34"


def test_ocultar_numero_com_e_sem_mais():
    texto = 'HTTP 400: {"number":"5511900000034","jid":"5511900000034@s.whatsapp.net","n":"+5511900000034"}'
    oculto = ocultar_numero(texto, "+5511900000034")
    assert "900000034" not in oculto
    assert oculto.count("+55 11 9****-**34") == 3
```

Crie `tests/db/test_repositorio_acesso.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import CodigoAcesso, MensagemSaida, Papel, PedidoCodigo, StatusMensagem, Usuario

T = datetime(2026, 10, 18, 13, 0, tzinfo=UTC)
GRUPO = "+5511900000002"


def novo(s, nome="Pessoa Grupo", numero=GRUPO, papel=Papel.GRUPO) -> Usuario:
    return repo_acesso.criar_usuario(s, nome, numero, papel, T)


def test_criar_e_achar_usuario(s):
    u = novo(s)
    assert (u.nome, u.papel, u.ativo, u.criado_em) == ("Pessoa Grupo", Papel.GRUPO, True, T)
    assert repo_acesso.usuario_por_numero(s, GRUPO).id == u.id
    assert repo_acesso.usuario_por_numero(s, "+5511900000009") is None


def test_numero_repetido_nao_cria_outro(s):
    novo(s)
    with pytest.raises(repo_acesso.NumeroJaCadastrado):
        novo(s, nome="Outra Pessoa", papel=Papel.OPERADOR)
    assert len(repo_acesso.listar_usuarios(s)) == 1


def test_banco_recusa_numero_fora_do_e164(s):
    s.add(Usuario(nome="X", numero="11900000002", papel=Papel.GRUPO, ativo=True, criado_em=T))
    with pytest.raises(IntegrityError):
        s.flush()


def test_listar_por_nome(s):
    novo(s, nome="beta", numero="+5511900000005")
    novo(s, nome="Alfa", numero="+5511900000006")
    assert [u.nome for u in repo_acesso.listar_usuarios(s)] == ["Alfa", "beta"]


def test_superadmin_unico_e_troca(s):
    assert repo_acesso.superadmin_atual(s) is None
    dono = repo_acesso.criar_superadmin(s, "Pessoa Superadmin", "+5511900000001", T)
    assert (dono.papel, dono.ativo, dono.superadmin) == (Papel.ADMIN, True, True)
    assert repo_acesso.superadmin_atual(s).id == dono.id
    with pytest.raises(repo_acesso.SuperadminJaExiste):
        repo_acesso.criar_superadmin(s, "Outra Pessoa", "+5511900000004", T)
    grupo = novo(s)
    assert novo(s, nome="Comum", numero="+5511900000005").superadmin is False
    antigo = repo_acesso.trocar_superadmin(s, grupo)
    assert antigo.id == dono.id
    assert (antigo.papel, antigo.superadmin) == (Papel.ADMIN, False)  # o antigo continua admin comum
    assert (grupo.papel, grupo.superadmin) == (Papel.ADMIN, True)
    assert repo_acesso.superadmin_atual(s).id == grupo.id


def test_banco_garante_um_superadmin_so(s):
    repo_acesso.criar_superadmin(s, "Pessoa Superadmin", "+5511900000001", T)
    s.add(Usuario(nome="X", numero="+5511900000004", papel=Papel.ADMIN, ativo=True, superadmin=True, criado_em=T))
    with pytest.raises(IntegrityError):
        s.flush()


@pytest.mark.parametrize(("papel", "ativo"), [(Papel.OPERADOR, True), (Papel.ADMIN, False)])
def test_banco_recusa_superadmin_que_nao_e_admin_ativo(s, papel, ativo):
    s.add(Usuario(nome="X", numero="+5511900000004", papel=papel, ativo=ativo, superadmin=True, criado_em=T))
    with pytest.raises(IntegrityError):
        s.flush()


def test_ultimo_codigo_e_o_mais_novo(s):
    u = novo(s)
    repo_acesso.criar_codigo(s, u.id, "h1", T, timedelta(minutes=5))
    segundo = repo_acesso.criar_codigo(s, u.id, "h2", T + timedelta(seconds=1), timedelta(minutes=5))
    atual = repo_acesso.ultimo_codigo(s, u.id)
    assert atual.id == segundo.id
    assert (atual.hash_codigo, atual.expira_em, atual.tentativas, atual.usado_em) == (
        "h2", T + timedelta(minutes=5, seconds=1), 0, None
    )
    assert repo_acesso.ultimo_codigo(s, u.id + 1000) is None


def test_sessoes_ativas_encerrar_e_contar(s):
    u = novo(s)
    a = repo_acesso.criar_sessao(s, u.id, "ha", "Chrome · Windows", T, timedelta(days=30))
    b = repo_acesso.criar_sessao(s, u.id, "hb", "Safari · iPhone", T + timedelta(hours=1), timedelta(days=30))
    vencida = repo_acesso.criar_sessao(s, u.id, "hc", "Firefox · Linux", T - timedelta(days=40), timedelta(days=30))
    agora = T + timedelta(hours=2)
    assert repo_acesso.sessao_por_hash(s, "ha").id == a.id
    assert repo_acesso.sessao_por_hash(s, "nada") is None
    assert [x.id for x in repo_acesso.sessoes_ativas(s, u.id, agora)] == [b.id, a.id]
    assert vencida.id not in [x.id for x in repo_acesso.sessoes_ativas(s, u.id, agora)]
    repo_acesso.encerrar_sessao(s, a, agora)
    assert a.encerrada_em == agora
    assert [x.id for x in repo_acesso.sessoes_ativas(s, u.id, agora)] == [b.id]
    assert repo_acesso.contar_sessoes_ativas(s, agora) == {u.id: 1}
    # encerra as que ainda não tinham sido encerradas (b e a vencida; a "a" já estava)
    assert repo_acesso.encerrar_sessoes_do_usuario(s, u.id, agora + timedelta(hours=1)) == 2
    assert repo_acesso.sessoes_ativas(s, u.id, agora + timedelta(hours=1)) == []


def test_pedidos_contam_so_aceitos_dentro_da_janela(s):
    repo_acesso.registrar_pedido(s, "n1", repo_acesso.ACEITO, T)
    repo_acesso.registrar_pedido(s, "n1", "limite_numero", T)
    repo_acesso.registrar_pedido(s, "n2", repo_acesso.ACEITO, T + timedelta(minutes=10))
    assert repo_acesso.contar_pedidos(s, T - timedelta(seconds=1)) == 2
    assert repo_acesso.contar_pedidos(s, T - timedelta(seconds=1), "n1") == 1
    assert repo_acesso.contar_pedidos(s, T) == 1  # janela aberta: o pedido de T não conta mais


def test_limpar_antigos_apaga_pedidos_e_codigos_de_mais_de_um_dia(s):
    u = novo(s)
    repo_acesso.registrar_pedido(s, "n1", repo_acesso.ACEITO, T - timedelta(days=2))
    repo_acesso.registrar_pedido(s, "n1", repo_acesso.ACEITO, T)
    repo_acesso.criar_codigo(s, u.id, "velho", T - timedelta(days=2), timedelta(minutes=5))
    repo_acesso.criar_codigo(s, u.id, "novo", T, timedelta(minutes=5))
    repo_acesso.limpar_antigos(s, T)
    assert [p.em for p in s.query(PedidoCodigo)] == [T]
    assert [c.hash_codigo for c in s.query(CodigoAcesso)] == ["novo"]


def test_grade_salva_e_upsert(s):
    assert repo_acesso.grade_salva(s) == {}
    repo_acesso.salvar_permissao(s, Papel.GRUPO, "ver_area_gestao", True)
    repo_acesso.salvar_permissao(s, Papel.GRUPO, "ver_area_gestao", False)
    repo_acesso.salvar_permissao(s, Papel.OPERADOR, "gerir_usuarios", True)
    assert repo_acesso.grade_salva(s) == {
        (Papel.GRUPO, "ver_area_gestao"): False,
        (Papel.OPERADOR, "gerir_usuarios"): True,
    }


def _mensagem(destino, numero):
    return MensagemSaida(
        destino=destino, texto="x", status=StatusMensagem.PENDENTE, tentativas=0, proxima_tentativa_em=T,
        ignorar_validade=False, criada_em=T, atualizado_em=T, numero=numero,
    )


def test_mensagem_individual_exige_numero(s):
    s.add(_mensagem("individual", None))
    with pytest.raises(IntegrityError):
        s.flush()


def test_mensagem_de_grupo_nao_leva_numero(s):
    s.add(_mensagem("admin", GRUPO))
    with pytest.raises(IntegrityError):
        s.flush()


def test_mensagem_individual_com_numero_e_aceita(s):
    s.add(_mensagem("individual", GRUPO))
    s.flush()
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t1 uv run pytest tests/test_numeros.py tests/db/test_repositorio_acesso.py -q -p no:cacheprovider`
Expected: FAIL (ImportError: `normalizar_numero`, `repositorio_acesso`).

- [ ] **Step 4: Números em `formatacao.py`**

Acrescente no topo `import re` (antes de `from decimal import Decimal`) e, no fim do arquivo:

```python
_NUMERO_E164 = re.compile(r"\+[1-9][0-9]{9,14}")
_SEPARADORES = re.compile(r"[\s().-]")


def normalizar_numero(texto: str) -> str:
    """Número de WhatsApp em E.164 ("+5511900000001"). Aceita espaços, parênteses, pontos e traços; sem "+",
    10 ou 11 dígitos (DDD + número) viram número do Brasil (+55). Levanta ValueError se não for um número válido."""
    bruto = texto.strip()
    com_mais = bruto.startswith("+")
    digitos = _SEPARADORES.sub("", bruto.removeprefix("+"))
    if not (digitos.isascii() and digitos.isdigit()):
        raise ValueError("número inválido")
    if not com_mais and len(digitos) in (10, 11):
        digitos = "55" + digitos
    numero = "+" + digitos
    if not _NUMERO_E164.fullmatch(numero):
        raise ValueError("número inválido")
    return numero


def mascarar_numero(numero: str) -> str:
    """Número para log e tela: "+5511900000034" vira "+55 11 9****-**34" (só DDD, o 1º e os 2 últimos dígitos)."""
    digitos = numero.removeprefix("+")
    if digitos.startswith("55") and len(digitos) in (12, 13):
        ddd, assinante = digitos[2:4], digitos[4:]
        return f"+55 {ddd} {assinante[0]}{'*' * (len(assinante) - 5)}-**{assinante[-2:]}"
    return f"+{digitos[:2]} {'*' * max(len(digitos) - 4, 1)}{digitos[-2:]}"


def ocultar_numero(texto: str, numero: str) -> str:
    """Troca o número (com ou sem "+") pela versão mascarada: texto de terceiros (erro da Evolution) que repete o
    número da pessoa não vai para log, banco de erros nem grupo."""
    mascarado = mascarar_numero(numero)
    return texto.replace(numero, mascarado).replace(numero.removeprefix("+"), mascarado)
```

(Conferência do celular: assinante de 9 dígitos → `9` + 4 `*` + `-**` + 2 dígitos = "9****-**34"; fixo de 8 → "3***-**34".)

- [ ] **Step 5: Modelos**

Em `src/tcg_sniper/db/models.py`, depois de `class StatusManutencao`, acrescente:

```python
class Papel(enum.StrEnum):
    GRUPO = "grupo"  # área de negócio
    OPERADOR = "operador"  # área de negócio e de gestão (o que mais, a grade de Acessos diz)
    ADMIN = "admin"  # tudo, sempre (não editável na grade)
```

Em `class MensagemSaida`, troque o check de destino e acrescente o do número e as duas colunas:

```python
    __table_args__ = (
        CheckConstraint("destino IN ('admin', 'oportunidades', 'individual')", name="ck_mensagem_saida_destino"),
        CheckConstraint("(destino = 'individual') = (numero IS NOT NULL)", name="ck_mensagem_saida_numero"),
        CheckConstraint("texto <> ''", name="ck_mensagem_saida_texto"),
        CheckConstraint("tentativas >= 0", name="ck_mensagem_saida_tentativas"),
        Index("ix_mensagem_saida_fila", "status", "proxima_tentativa_em"),
    )
```

e, depois de `enviada_em`:

```python
    numero: Mapped[str | None] = mapped_column(Text)  # E.164, só destino "individual"; nunca em log
    expira_em: Mapped[datetime | None] = mapped_column(DATA)  # validade própria (código de acesso: 5 min)
```

No fim do arquivo, acrescente:

```python
class Usuario(Base):
    """Pessoa que entra no front. `numero` em E.164 fica só no banco: nunca em log, tela (só mascarado) ou grupo.
    `superadmin`: o dono do sistema (um só, sempre admin e ativo; a API nunca o rebaixa, desativa ou encerra)."""

    __tablename__ = "usuario"
    __table_args__ = (
        UniqueConstraint("numero", name="uq_usuario_numero"),
        CheckConstraint("nome <> ''", name="ck_usuario_nome"),
        CheckConstraint("numero ~ '^[+][1-9][0-9]{9,14}$'", name="ck_usuario_numero"),
        CheckConstraint("NOT superadmin OR (papel = 'admin' AND ativo)", name="ck_usuario_superadmin"),
        # no máximo um superadmin (o dono do sistema): criado e trocado só pelos comandos locais
        Index("uq_usuario_superadmin", "superadmin", unique=True, postgresql_where=text("superadmin")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(Text)
    numero: Mapped[str] = mapped_column(Text)
    papel: Mapped[Papel] = mapped_column(_enum(Papel, "papel"))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    superadmin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    criado_em: Mapped[datetime] = mapped_column(DATA)


class CodigoAcesso(Base):
    """Código de 6 dígitos pedido no login (só o hash). Só o último do usuário vale; 5 tentativas erradas o invalidam."""

    __tablename__ = "codigo_acesso"
    __table_args__ = (
        CheckConstraint("tentativas >= 0", name="ck_codigo_acesso_tentativas"),
        Index("ix_codigo_acesso_usuario", "usuario_id", "criado_em"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    hash_codigo: Mapped[str] = mapped_column(Text)
    criado_em: Mapped[datetime] = mapped_column(DATA)
    expira_em: Mapped[datetime] = mapped_column(DATA)
    tentativas: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    usado_em: Mapped[datetime | None] = mapped_column(DATA)


class Sessao(Base):
    """Sessão do front (cookie `sessao`; no banco só o hash do token). Vence em 30 dias, renovada a cada uso."""

    __tablename__ = "sessao"
    __table_args__ = (
        UniqueConstraint("hash_token", name="uq_sessao_hash_token"),
        Index("ix_sessao_usuario", "usuario_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    hash_token: Mapped[str] = mapped_column(Text)
    aparelho: Mapped[str] = mapped_column(Text)  # "Chrome · Windows"
    criada_em: Mapped[datetime] = mapped_column(DATA)
    ultimo_uso_em: Mapped[datetime] = mapped_column(DATA)
    expira_em: Mapped[datetime] = mapped_column(DATA)
    encerrada_em: Mapped[datetime | None] = mapped_column(DATA)


class PermissaoPapel(Base):
    """Grade papel × permissão (Gestão → Acessos). Linha ausente = padrão do código (`api/permissoes.py`);
    `permissao` é texto livre de propósito: cada fase acrescenta as suas sem migração. Linhas do admin são ignoradas."""

    __tablename__ = "permissao_papel"

    papel: Mapped[Papel] = mapped_column(_enum(Papel, "papel"), primary_key=True)
    permissao: Mapped[str] = mapped_column(Text, primary_key=True)
    permitido: Mapped[bool] = mapped_column(Boolean)


class PedidoCodigo(Base):
    """Cada pedido de código, para os limites (3 por número em 15 min, 20 por hora no total). Sem o número: só o hash,
    também de números sem cadastro (o limite vale para eles, senão o 429 revelaria quem tem cadastro)."""

    __tablename__ = "pedido_codigo"
    __table_args__ = (
        CheckConstraint(
            "resultado IN ('aceito', 'limite_numero', 'limite_total')", name="ck_pedido_codigo_resultado"
        ),
        Index("ix_pedido_codigo_em", "em"),
        Index("ix_pedido_codigo_numero", "numero_hash", "em"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    em: Mapped[datetime] = mapped_column(DATA)
    numero_hash: Mapped[str] = mapped_column(Text)
    resultado: Mapped[str] = mapped_column(Text)
```

- [ ] **Step 6: Migração**

Crie `src/tcg_sniper/db/migrations/versions/f8d2a6c4e1b3_acesso.py`:

```python
"""login do front: usuario, codigo_acesso, sessao, permissao_papel, pedido_codigo; mensagem individual

Revision ID: f8d2a6c4e1b3
Revises: e4b7c2d9a1f6
Create Date: 2026-10-18 23:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8d2a6c4e1b3"
down_revision: Union[str, Sequence[str], None] = "e4b7c2d9a1f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DATA = sa.DateTime(timezone=True)
PAPEIS = ("grupo", "operador", "admin")


def _papel() -> sa.Enum:
    return sa.Enum(*PAPEIS, name="papel", native_enum=False, create_constraint=True, length=20)


def upgrade() -> None:
    op.create_table(
        "usuario",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.Text(), nullable=False),
        sa.Column("numero", sa.Text(), nullable=False),
        sa.Column("papel", _papel(), nullable=False),
        sa.Column("ativo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("superadmin", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("criado_em", DATA, nullable=False),
        sa.CheckConstraint("nome <> ''", name="ck_usuario_nome"),
        sa.CheckConstraint("numero ~ '^[+][1-9][0-9]{9,14}$'", name="ck_usuario_numero"),
        sa.CheckConstraint("NOT superadmin OR (papel = 'admin' AND ativo)", name="ck_usuario_superadmin"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("numero", name="uq_usuario_numero"),
    )
    op.create_index(
        "uq_usuario_superadmin", "usuario", ["superadmin"], unique=True, postgresql_where=sa.text("superadmin")
    )
    op.create_table(
        "codigo_acesso",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("hash_codigo", sa.Text(), nullable=False),
        sa.Column("criado_em", DATA, nullable=False),
        sa.Column("expira_em", DATA, nullable=False),
        sa.Column("tentativas", sa.Integer(), server_default="0", nullable=False),
        sa.Column("usado_em", DATA, nullable=True),
        sa.CheckConstraint("tentativas >= 0", name="ck_codigo_acesso_tentativas"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_codigo_acesso_usuario", "codigo_acesso", ["usuario_id", "criado_em"])
    op.create_table(
        "sessao",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("hash_token", sa.Text(), nullable=False),
        sa.Column("aparelho", sa.Text(), nullable=False),
        sa.Column("criada_em", DATA, nullable=False),
        sa.Column("ultimo_uso_em", DATA, nullable=False),
        sa.Column("expira_em", DATA, nullable=False),
        sa.Column("encerrada_em", DATA, nullable=True),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hash_token", name="uq_sessao_hash_token"),
    )
    op.create_index("ix_sessao_usuario", "sessao", ["usuario_id"])
    op.create_table(
        "permissao_papel",
        sa.Column("papel", _papel(), nullable=False),
        sa.Column("permissao", sa.Text(), nullable=False),
        sa.Column("permitido", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("papel", "permissao"),
    )
    op.create_table(
        "pedido_codigo",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("em", DATA, nullable=False),
        sa.Column("numero_hash", sa.Text(), nullable=False),
        sa.Column("resultado", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "resultado IN ('aceito', 'limite_numero', 'limite_total')", name="ck_pedido_codigo_resultado"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pedido_codigo_em", "pedido_codigo", ["em"])
    op.create_index("ix_pedido_codigo_numero", "pedido_codigo", ["numero_hash", "em"])
    op.add_column("mensagem_saida", sa.Column("numero", sa.Text(), nullable=True))
    op.add_column("mensagem_saida", sa.Column("expira_em", DATA, nullable=True))
    op.drop_constraint("ck_mensagem_saida_destino", "mensagem_saida", type_="check")
    op.create_check_constraint(
        "ck_mensagem_saida_destino", "mensagem_saida", "destino IN ('admin', 'oportunidades', 'individual')"
    )
    op.create_check_constraint(
        "ck_mensagem_saida_numero", "mensagem_saida", "(destino = 'individual') = (numero IS NOT NULL)"
    )


def downgrade() -> None:
    op.execute("DELETE FROM mensagem_saida WHERE destino = 'individual'")
    op.drop_constraint("ck_mensagem_saida_numero", "mensagem_saida", type_="check")
    op.drop_constraint("ck_mensagem_saida_destino", "mensagem_saida", type_="check")
    op.create_check_constraint("ck_mensagem_saida_destino", "mensagem_saida", "destino IN ('admin', 'oportunidades')")
    op.drop_column("mensagem_saida", "expira_em")
    op.drop_column("mensagem_saida", "numero")
    op.drop_index("ix_pedido_codigo_numero", table_name="pedido_codigo")
    op.drop_index("ix_pedido_codigo_em", table_name="pedido_codigo")
    op.drop_table("pedido_codigo")
    op.drop_table("permissao_papel")
    op.drop_index("ix_sessao_usuario", table_name="sessao")
    op.drop_table("sessao")
    op.drop_index("ix_codigo_acesso_usuario", table_name="codigo_acesso")
    op.drop_table("codigo_acesso")
    op.drop_index("uq_usuario_superadmin", table_name="usuario")
    op.drop_table("usuario")
```

- [ ] **Step 7: Repositório**

Crie `src/tcg_sniper/db/repositorio_acesso.py`:

```python
"""Login do front: usuários, códigos de acesso, sessões, pedidos de código (limites) e a grade papel × permissão.
Números de WhatsApp ficam só aqui (banco); código e token entram só como hash."""

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tcg_sniper.db.models import CodigoAcesso, Papel, PedidoCodigo, PermissaoPapel, Sessao, Usuario

ACEITO = "aceito"
RETENCAO = timedelta(days=1)  # pedidos e códigos mais velhos que isso não servem para nada


class NumeroJaCadastrado(Exception):
    pass


class SuperadminJaExiste(Exception):
    pass


def criar_usuario(s: Session, nome: str, numero: str, papel: Papel, agora: datetime) -> Usuario:
    """`numero` já normalizado (E.164). Número repetido levanta `NumeroJaCadastrado` (nada é gravado)."""
    usuario = Usuario(nome=nome, numero=numero, papel=papel, ativo=True, criado_em=agora)
    try:
        with s.begin_nested():
            s.add(usuario)
            s.flush()
    except IntegrityError:
        raise NumeroJaCadastrado from None
    return usuario


def usuario_por_numero(s: Session, numero: str) -> Usuario | None:
    return s.scalar(select(Usuario).where(Usuario.numero == numero))


def listar_usuarios(s: Session) -> list[Usuario]:
    return list(s.scalars(select(Usuario).order_by(func.lower(Usuario.nome), Usuario.id)))


def superadmin_atual(s: Session) -> Usuario | None:
    return s.scalar(select(Usuario).where(Usuario.superadmin.is_(True)))


def criar_superadmin(s: Session, nome: str, numero: str, agora: datetime) -> Usuario:
    """Só pelo comando local `criar-superadmin`. Já existe um: `SuperadminJaExiste` (nada é gravado)."""
    if superadmin_atual(s) is not None:
        raise SuperadminJaExiste
    usuario = criar_usuario(s, nome, numero, Papel.ADMIN, agora)
    usuario.superadmin = True
    s.flush()
    return usuario


def trocar_superadmin(s: Session, novo: Usuario) -> Usuario | None:
    """Só pelo comando local `trocar-superadmin`: a marca passa para `novo` (que vira admin, se não era); o antigo
    continua admin comum. Devolve o antigo (None se não havia). Desmarca antes de marcar: o índice único é parcial."""
    antigo = superadmin_atual(s)
    if antigo is not None:
        antigo.superadmin = False
        s.flush()
    novo.papel = Papel.ADMIN
    novo.superadmin = True
    s.flush()
    return antigo


def criar_codigo(s: Session, usuario_id: int, hash_codigo: str, agora: datetime, validade: timedelta) -> CodigoAcesso:
    codigo = CodigoAcesso(
        usuario_id=usuario_id, hash_codigo=hash_codigo, criado_em=agora, expira_em=agora + validade, tentativas=0
    )
    s.add(codigo)
    s.flush()
    return codigo


def ultimo_codigo(s: Session, usuario_id: int) -> CodigoAcesso | None:
    """O código que vale (o mais novo), travado para esta transação (as tentativas contam certo em paralelo)."""
    return s.scalar(
        select(CodigoAcesso)
        .where(CodigoAcesso.usuario_id == usuario_id)
        .order_by(CodigoAcesso.criado_em.desc(), CodigoAcesso.id.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def criar_sessao(
    s: Session, usuario_id: int, hash_token: str, aparelho: str, agora: datetime, validade: timedelta
) -> Sessao:
    sessao = Sessao(
        usuario_id=usuario_id, hash_token=hash_token, aparelho=aparelho, criada_em=agora, ultimo_uso_em=agora,
        expira_em=agora + validade,
    )
    s.add(sessao)
    s.flush()
    return sessao


def sessao_por_hash(s: Session, hash_token: str) -> Sessao | None:
    return s.scalar(select(Sessao).where(Sessao.hash_token == hash_token))


def _ativa(agora: datetime):
    return (Sessao.encerrada_em.is_(None), Sessao.expira_em > agora)


def sessoes_ativas(s: Session, usuario_id: int, agora: datetime) -> list[Sessao]:
    return list(
        s.scalars(
            select(Sessao)
            .where(Sessao.usuario_id == usuario_id, *_ativa(agora))
            .order_by(Sessao.ultimo_uso_em.desc(), Sessao.id.desc())
        )
    )


def contar_sessoes_ativas(s: Session, agora: datetime) -> dict[int, int]:
    linhas = s.execute(
        select(Sessao.usuario_id, func.count()).where(*_ativa(agora)).group_by(Sessao.usuario_id)
    )
    return {usuario_id: total for usuario_id, total in linhas}


def encerrar_sessao(s: Session, sessao: Sessao, agora: datetime) -> None:
    if sessao.encerrada_em is None:
        sessao.encerrada_em = agora
        s.flush()


def encerrar_sessoes_do_usuario(s: Session, usuario_id: int, agora: datetime) -> int:
    resultado = s.execute(
        update(Sessao)
        .where(Sessao.usuario_id == usuario_id, Sessao.encerrada_em.is_(None))
        .values(encerrada_em=agora)
        .execution_options(synchronize_session="fetch")
    )
    return resultado.rowcount


def registrar_pedido(s: Session, numero_hash: str, resultado: str, agora: datetime) -> None:
    s.add(PedidoCodigo(em=agora, numero_hash=numero_hash, resultado=resultado))
    s.flush()


def contar_pedidos(s: Session, desde: datetime, numero_hash: str | None = None) -> int:
    """Pedidos aceitos depois de `desde` (janela aberta), de um número ou de todos."""
    condicoes = [PedidoCodigo.resultado == ACEITO, PedidoCodigo.em > desde]
    if numero_hash is not None:
        condicoes.append(PedidoCodigo.numero_hash == numero_hash)
    return s.scalar(select(func.count()).select_from(PedidoCodigo).where(*condicoes)) or 0


def limpar_antigos(s: Session, agora: datetime) -> None:
    limite = agora - RETENCAO
    s.execute(delete(PedidoCodigo).where(PedidoCodigo.em < limite))
    s.execute(delete(CodigoAcesso).where(CodigoAcesso.criado_em < limite))


def grade_salva(s: Session) -> dict[tuple[Papel, str], bool]:
    return {(linha.papel, linha.permissao): linha.permitido for linha in s.scalars(select(PermissaoPapel))}


def salvar_permissao(s: Session, papel: Papel, permissao: str, permitido: bool) -> None:
    s.execute(
        pg_insert(PermissaoPapel)
        .values(papel=papel, permissao=permissao, permitido=permitido)
        .on_conflict_do_update(
            index_elements=[PermissaoPapel.papel, PermissaoPapel.permissao], set_={"permitido": permitido}
        )
    )
    s.flush()
```

- [ ] **Step 8: Rodar os testes novos**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t1 uv run pytest tests/test_numeros.py tests/db/test_repositorio_acesso.py tests/db/test_migracao.py -q -p no:cacheprovider`
Expected: PASS (inclui `test_migracao_igual_aos_modelos`; se acusar diferença, alinhe modelo e migração — nomes de índice/unique, tipos — até ficar `[]`).

- [ ] **Step 9: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t1 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: tudo verde.

- [ ] **Step 10: Commit**

```bash
git add src/tcg_sniper/db/models.py src/tcg_sniper/db/migrations/versions/f8d2a6c4e1b3_acesso.py src/tcg_sniper/db/repositorio_acesso.py src/tcg_sniper/formatacao.py tests/test_numeros.py tests/db/test_repositorio_acesso.py
git commit -m "feat: users, access codes, sessions and role grid tables"
```

---
### Task 2: Avisos novos e envio individual (código de acesso)

**Files:**
- Modify: `src/tcg_sniper/notificador/base.py` (`Destino.INDIVIDUAL`)
- Modify: `src/tcg_sniper/avisos/catalogo.py` (`Severidade.ACESSO`, três tipos novos)
- Modify: `src/tcg_sniper/avisos/servico.py` (`avisar_individual`; `avisar` recusa tipo individual)
- Modify: `src/tcg_sniper/db/repositorio_mensagens.py` (`enfileirar` com `numero`/`expira_em`, `TEXTO_APAGADO`, `apagar_texto_individual`, `reenviar`/`descartar`)
- Modify: `src/tcg_sniper/notificador/servico.py` (`_processar`)
- Modify: `src/tcg_sniper/admin/consultas_mensagens.py`, `src/tcg_sniper/admin/app.py` (`_avisos_da_tela`), `src/tcg_sniper/admin/templates/configuracoes.html`, `src/tcg_sniper/admin/static/admin.css` (regenerado)
- Test: `tests/avisos/test_formato.py`, `tests/avisos/test_servico.py`, `tests/notificador/test_servico.py`, `tests/db/test_repositorio_mensagens.py`, `tests/admin/test_admin_mensagens.py`, `tests/admin/test_admin_avisos.py`

**Interfaces:**
- Consumes (Task 1): `MensagemSaida.numero`, `MensagemSaida.expira_em`, check `ck_mensagem_saida_numero`; `formatacao.ocultar_numero(texto, numero)`.
- Produces:
  - `Destino.INDIVIDUAL = "individual"`.
  - `catalogo.Severidade.ACESSO = "acesso"` (emoji `"🔑"`); `catalogo.ACESSO = "acesso"` (origem do rodapé).
  - `TipoAviso.CODIGO_ACESSO = "codigo_acesso"` (grupo `Destino.INDIVIDUAL`, não agrupa), `TipoAviso.SEGURANCA_USUARIO = "seguranca_usuario"` (grupo admin, não agrupa), `TipoAviso.SEGURANCA_LIMITE = "seguranca_limite"` (grupo admin, agrupa, lembrete 2 h).
  - `avisos.servico.VALIDADE_INDIVIDUAL = timedelta(minutes=5)`; `avisos.servico.avisar_individual(s: Session, tipo: TipoAviso, numero: str, dados: Dados, agora: datetime, validade: timedelta = VALIDADE_INDIVIDUAL) -> bool` (True se enfileirou; nunca levanta, menos `UrlProibida` no modo estrito).
  - `repositorio_mensagens.enfileirar(s, destino: str, texto: str, agora: datetime, *, numero: str | None = None, expira_em: datetime | None = None) -> MensagemSaida`; `repositorio_mensagens.TEXTO_APAGADO = "(mensagem individual: texto apagado depois de sair da fila)"`; `repositorio_mensagens.apagar_texto_individual(mensagem: MensagemSaida) -> None`.

- [ ] **Step 1: Banco da lane**

Run: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_t2`

- [ ] **Step 2: Testes do catálogo (falham)**

Em `tests/avisos/test_formato.py`, acrescente ao dicionário `ESPERADOS` (antes do `}` final):

```python
    TipoAviso.CODIGO_ACESSO: (
        "🔑 *Código de acesso*\n"
        "*123456*\n"
        "• Vale por 5 minutos.\n"
        "• Não passe este código para ninguém.\n"
        "_18/10 10:42 · acesso_"
    ),
    TipoAviso.SEGURANCA_USUARIO: (
        "🟡 *Segurança · acesso alterado · papel alterado*\n"
        "• Usuário: Pessoa Exemplo\n"
        "• Papel: Grupo → Operador\n"
        "• Por: Pessoa Admin\n"
        "\n"
        "*O que fazer:* Se não foi alguém do grupo, desative o usuário em Gestão → Usuários.\n"
        "_18/10 10:42 · acesso_"
    ),
    TipoAviso.SEGURANCA_LIMITE: (
        "🟡 *Segurança · limite de códigos*\n"
        "• Limite: 3 códigos por número em 15 min\n"
        "• Número com final 34\n"
        "\n"
        "*O que fazer:* Se ninguém do grupo está tentando entrar, alguém pode estar testando números; "
        "o site recusa novos pedidos até a janela passar.\n"
        "_18/10 10:42 · acesso_"
    ),
```

Troque `assert len(TipoAviso) == 28` por `assert len(TipoAviso) == 31`. Em `test_regras_do_catalogo`, troque a linha do `d.grupo` por:

```python
        destino = {TipoAviso.OPORTUNIDADE: Destino.OPORTUNIDADES, TipoAviso.CODIGO_ACESSO: Destino.INDIVIDUAL}
        assert d.grupo is destino.get(tipo, Destino.ADMIN), tipo
```

acrescente `TipoAviso.SEGURANCA_LIMITE` ao conjunto `agrupam` esperado e, depois de `assert CATALOGO[TipoAviso.OPORTUNIDADE].severidade is Severidade.OPORTUNIDADE`:

```python
    assert CATALOGO[TipoAviso.CODIGO_ACESSO].severidade is Severidade.ACESSO
```

- [ ] **Step 3: Testes do serviço de avisos (falham)**

Em `tests/avisos/test_servico.py`, acrescente no fim:

```python
NUMERO = "+5511900000001"
CODIGO = TipoAviso.CODIGO_ACESSO


def test_avisar_individual_enfileira_so_para_o_numero_com_validade(sessoes):
    with sessoes() as s, s.begin():
        dados = Dados(destaque="123456", linhas=("Vale por 5 minutos.",))
        assert servico.avisar_individual(s, CODIGO, NUMERO, dados, T) is True
    [m] = saidas(sessoes)
    assert (m.destino, m.numero, m.expira_em, m.criada_em) == ("individual", NUMERO, T + timedelta(minutes=5), T)
    assert m.texto.startswith("🔑 *Código de acesso*\n*123456*\n")


def test_avisar_individual_respeita_a_validade_pedida(sessoes):
    with sessoes() as s, s.begin():
        servico.avisar_individual(s, CODIGO, NUMERO, CATALOGO[CODIGO].exemplo, T, timedelta(minutes=1))
    assert saidas(sessoes)[0].expira_em == T + timedelta(minutes=1)


def test_avisar_individual_desligado_nao_enfileira(sessoes):
    desligar(sessoes, CODIGO)
    with sessoes() as s, s.begin():
        assert servico.avisar_individual(s, CODIGO, NUMERO, CATALOGO[CODIGO].exemplo, T) is False
    assert saidas(sessoes) == []


def test_tipo_de_grupo_nao_vai_para_numero_e_individual_nao_vai_para_grupo(sessoes, caplog):
    with sessoes() as s, s.begin():
        assert servico.avisar_individual(s, CAPTCHA, NUMERO, CATALOGO[CAPTCHA].exemplo, T) is False
        servico.avisar(s, CODIGO, CHAVE_GERAL, CATALOGO[CODIGO].exemplo, T)
    assert saidas(sessoes) == []
    assert "900000001" not in caplog.text
```

- [ ] **Step 4: Testes da fila, do notificador e do admin (falham)**

Em `tests/db/test_repositorio_mensagens.py`, acrescente no fim:

```python
NUMERO = "+5511900000001"


def individual(s, criada=AGORA):
    return repo_msg.enfileirar(
        s, "individual", "🔑 *Código de acesso*\n*123456*", criada, numero=NUMERO, expira_em=criada + timedelta(minutes=5)
    )


def test_enfileirar_individual_guarda_numero_e_validade(s):
    m = individual(s)
    assert (m.destino, m.numero, m.expira_em) == ("individual", NUMERO, AGORA + timedelta(minutes=5))


def test_individual_nao_e_reenviado(s):
    m = individual(s)
    m.status = StatusMensagem.EXPIRADA
    s.flush()
    with pytest.raises(repo_msg.AcaoInvalida, match="código novo"):
        repo_msg.reenviar(s, m.id, AGORA)


def test_descartar_individual_apaga_o_texto(s):
    m = individual(s)
    repo_msg.descartar(s, m.id, AGORA)
    assert (m.status, m.texto) == (StatusMensagem.DESCARTADA, repo_msg.TEXTO_APAGADO)


def test_apagar_texto_so_mexe_na_individual(s):
    grupo = repo_msg.enfileirar(s, "admin", "aviso", AGORA)
    repo_msg.apagar_texto_individual(grupo)
    assert grupo.texto == "aviso"
```

Em `tests/notificador/test_servico.py`, acrescente `import json` no topo (se ainda não houver) e, no fim:

```python
NUMERO = "+5511900000001"


def nova_individual(sessoes, criada=AGORA, validade=timedelta(minutes=5)):
    with sessoes() as s, s.begin():
        return repo_msg.enfileirar(
            s, "individual", "🔑 *Código de acesso*\n*123456*", criada, numero=NUMERO, expira_em=criada + validade
        ).id


@respx.mock
def test_individual_vai_para_o_numero_e_o_texto_some_depois(sessoes, env, configurado):
    rota = respx.post(ROTA).mock(return_value=httpx.Response(201))
    mid = nova_individual(sessoes)
    assert servico(sessoes, env).ciclo() == 1
    corpo = json.loads(rota.calls.last.request.read())
    assert corpo["number"] == "5511900000001" and "*123456*" in corpo["text"]
    m = ler(sessoes, mid)
    assert (m.status, m.texto) == (StatusMensagem.ENVIADA, repo_msg.TEXTO_APAGADO)


@respx.mock
def test_codigo_vencido_na_fila_nao_sai_nem_e_reenviado(sessoes, env, configurado):
    rota = respx.post(ROTA).mock(return_value=httpx.Response(201))
    mid = nova_individual(sessoes, criada=AGORA - timedelta(minutes=5))
    servico(sessoes, env).ciclo()
    m = ler(sessoes, mid)
    assert (m.status, m.texto) == (StatusMensagem.EXPIRADA, repo_msg.TEXTO_APAGADO)
    assert not rota.called
    with sessoes() as s, s.begin(), pytest.raises(repo_msg.AcaoInvalida):
        repo_msg.reenviar(s, mid, AGORA)


@respx.mock
def test_validade_individual_vale_mesmo_com_ignorar_validade(sessoes, env, configurado):
    rota = respx.post(ROTA).mock(return_value=httpx.Response(201))
    mid = nova_individual(sessoes, criada=AGORA - timedelta(minutes=6))
    with sessoes() as s, s.begin():
        s.get(MensagemSaida, mid).ignorar_validade = True
    servico(sessoes, env).ciclo()
    assert ler(sessoes, mid).status is StatusMensagem.EXPIRADA and not rota.called


@respx.mock
def test_erro_que_repete_o_numero_e_mascarado(sessoes, env, configurado, caplog):
    respx.post(ROTA).mock(
        return_value=httpx.Response(400, text='{"message":"5511900000001 não está no WhatsApp"}')
    )
    mid = nova_individual(sessoes, validade=timedelta(hours=2))
    relogio = Relogio(AGORA)
    svc = servico(sessoes, env, relogio)
    for _ in range(5):
        svc.ciclo()
        relogio.agora = ler(sessoes, mid).proxima_tentativa_em
    m = ler(sessoes, mid)
    assert m.status is StatusMensagem.FALHA and m.texto == repo_msg.TEXTO_APAGADO
    assert "5511900000001" not in m.ultimo_erro and "+55 11 9****-**01" in m.ultimo_erro
    with sessoes() as s:
        avisos_admin = [x.texto for x in s.scalars(select(MensagemSaida).where(MensagemSaida.destino == "admin"))]
    assert avisos_admin and all("900000001" not in texto for texto in avisos_admin)
    assert "900000001" not in caplog.text
```

Em `tests/admin/test_admin_mensagens.py`, acrescente no fim:

```python
def _individual_pendente(sessoes) -> int:
    agora = repo.agora_utc()
    with sessoes() as s, s.begin():
        return repo_msg.enfileirar(
            s, "individual", "🔑 *Código de acesso*", agora, numero="+5511900000001", expira_em=agora + timedelta(minutes=5)
        ).id


def test_filtro_individual_mostra_o_destino_sem_o_numero(cliente, sessoes):
    _individual_pendente(sessoes)
    texto = cliente.get("/mensagens", params={"destino": "individual"}).text
    assert "individual" in texto and "900000001" not in texto


def test_reenviar_individual_responde_409(cliente, sessoes):
    mid = _individual_pendente(sessoes)
    with sessoes() as s, s.begin():
        s.get(MensagemSaida, mid).status = StatusMensagem.EXPIRADA
    r = cliente.post(f"/mensagens/{mid}", data={"acao": "reenviar"}, follow_redirects=False)
    assert r.status_code == 409
```

Em `tests/admin/test_admin_avisos.py`, acrescente no fim:

```python
def test_aba_avisos_mostra_destino_e_severidade_de_acesso(cliente):
    texto = cliente.get("/configuracoes").text
    assert 'badge-ghost badge-sm">só para a pessoa</span>' in texto
    assert 'badge-ghost badge-sm">grupo admin</span>' in texto
    assert 'badge-neutral badge-sm">Acesso</span>' in texto
```

- [ ] **Step 5: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t2 uv run pytest tests/avisos tests/notificador tests/db/test_repositorio_mensagens.py tests/admin/test_admin_mensagens.py tests/admin/test_admin_avisos.py -q -p no:cacheprovider`
Expected: FAIL (`TipoAviso` sem `CODIGO_ACESSO`, `enfileirar` sem `numero`, `avisar_individual` não existe).

- [ ] **Step 6: Destino e catálogo**

Em `src/tcg_sniper/notificador/base.py`:

```python
class Destino(StrEnum):
    ADMIN = "admin"
    OPORTUNIDADES = "oportunidades"
    INDIVIDUAL = "individual"  # número de uma pessoa (código de acesso); nunca um grupo
```

Em `src/tcg_sniper/avisos/catalogo.py`:
- em `Severidade`, acrescente `ACESSO = "acesso"`; em `EMOJI`, `Severidade.ACESSO: "🔑",`;
- em `TipoAviso`, depois de `OPORTUNIDADE`: `CODIGO_ACESSO = "codigo_acesso"`, `SEGURANCA_USUARIO = "seguranca_usuario"`, `SEGURANCA_LIMITE = "seguranca_limite"`;
- depois da linha `MANUTENCAO, VIGIA, ADMIN, NOTIFICADOR = ...`, acrescente `ACESSO = "acesso"`;
- no fim do dicionário `CATALOGO` (depois de `TipoAviso.OPORTUNIDADE`):

```python
    TipoAviso.CODIGO_ACESSO: DefinicaoAviso(
        Severidade.ACESSO, Destino.INDIVIDUAL, "Código de acesso", ACESSO,
        "Código de 6 dígitos para entrar no site, mandado só para o número da pessoa (vale 5 min). "
        "Desligado, ninguém recebe código: fica só o acesso de emergência pelo terminal.",
        Dados(destaque="123456", linhas=("Vale por 5 minutos.", "Não passe este código para ninguém.")),
    ),
    TipoAviso.SEGURANCA_USUARIO: _evento(
        A, "Segurança · acesso alterado", ACESSO,
        "Usuário criado, papel alterado, usuário desativado ou reativado, ou permissão de um papel alterada.",
        "Se não foi alguém do grupo, desative o usuário em Gestão → Usuários.",
        Dados(
            titulo_extra="papel alterado",
            linhas=("Usuário: Pessoa Exemplo", "Papel: Grupo → Operador", "Por: Pessoa Admin"),
        ),
    ),
    TipoAviso.SEGURANCA_LIMITE: _problema(
        A, "Segurança · limite de códigos", ACESSO,
        "Pedidos de código acima do limite (3 por número em 15 min ou 20 por hora no total); agrupa por número.",
        "Se ninguém do grupo está tentando entrar, alguém pode estar testando números; "
        "o site recusa novos pedidos até a janela passar.",
        Dados(linhas=("Limite: 3 códigos por número em 15 min", "Número com final 34")),
    ),
```

- [ ] **Step 7: `avisar_individual`**

Em `src/tcg_sniper/avisos/servico.py`: troque `from datetime import datetime` por `from datetime import datetime, timedelta`, acrescente `from tcg_sniper.notificador.base import Destino` e, depois de `FUSO_PADRAO`, `VALIDADE_INDIVIDUAL = timedelta(minutes=5)`. No começo de `_avisar` (logo depois de `definicao = CATALOGO[tipo]`):

```python
    if definicao.grupo is Destino.INDIVIDUAL:
        log.error("aviso %s é individual: use avisar_individual", tipo.value)
        return
```

Depois de `resolver_todos`, acrescente:

```python
def avisar_individual(
    s: Session, tipo: TipoAviso, numero: str, dados: Dados, agora: datetime, validade: timedelta = VALIDADE_INDIVIDUAL
) -> bool:
    """Mensagem só para o número da pessoa (tipos com grupo INDIVIDUAL, ex.: CODIGO_ACESSO). Não agrupa; vence em
    `validade` (vencida, o notificador não envia). Devolve True se enfileirou. Nunca propaga exceção (menos
    `UrlProibida` no modo estrito) e nunca loga o número."""
    if CATALOGO[tipo].grupo is not Destino.INDIVIDUAL:
        log.error("aviso %s não é individual: use avisar", tipo.value)
        return False
    try:
        with s.begin_nested():
            if not ligado(s, tipo):
                return False
            zona, host = zona_e_host(s)
            texto = formato.formatar(formato.aviso_de(tipo, dados, agora), zona, host)
            repo_msg.enfileirar(s, Destino.INDIVIDUAL.value, texto, agora, numero=numero, expira_em=agora + validade)
            return True
    except Exception as erro:
        if _deixar_subir(erro):
            raise
        log.exception("aviso individual %s não registrado", tipo.value)
        return False
```

- [ ] **Step 8: Fila individual**

Em `src/tcg_sniper/db/repositorio_mensagens.py`: acrescente `from tcg_sniper.notificador.base import Destino` e, depois de `DESCARTAVEIS`:

```python
TEXTO_APAGADO = "(mensagem individual: texto apagado depois de sair da fila)"
```

Troque `enfileirar` por:

```python
def enfileirar(
    s: Session,
    destino: str,
    texto: str,
    agora: datetime,
    *,
    numero: str | None = None,
    expira_em: datetime | None = None,
) -> MensagemSaida:
    """`numero` só no destino "individual" (o banco confere); `expira_em` é a validade própria da mensagem."""
    mensagem = MensagemSaida(
        destino=destino,
        texto=texto,
        status=StatusMensagem.PENDENTE,
        tentativas=0,
        proxima_tentativa_em=agora,
        ignorar_validade=False,
        criada_em=agora,
        atualizado_em=agora,
        numero=numero,
        expira_em=expira_em,
    )
    s.add(mensagem)
    s.flush()
    return mensagem


def apagar_texto_individual(mensagem: MensagemSaida) -> None:
    """Mensagem individual (código de acesso) não guarda o texto depois de sair da fila: enviada, expirada,
    falha ou descartada."""
    if mensagem.destino == Destino.INDIVIDUAL.value:
        mensagem.texto = TEXTO_APAGADO
```

Em `reenviar`, logo depois de `mensagem = _obter(s, mensagem_id)`:

```python
    if mensagem.destino == Destino.INDIVIDUAL.value:
        raise AcaoInvalida("mensagem individual (código de acesso) não é reenviada: peça um código novo")
```

Em `descartar`, depois de `mensagem.status = StatusMensagem.DESCARTADA`, acrescente `apagar_texto_individual(mensagem)`.

- [ ] **Step 9: Notificador**

Em `src/tcg_sniper/notificador/servico.py`: acrescente `from tcg_sniper.formatacao import ocultar_numero` e `from tcg_sniper.notificador.base import Destino`. Troque `_processar` inteiro por:

```python
    def _processar(self, s: Session, m: MensagemSaida, geral: _Destinos, agora: datetime) -> Resultado | None:
        """Devolve o resultado do envio, ou `None` se a mensagem nem chegou a ser enviada."""
        m.atualizado_em = agora
        if m.expira_em is not None and agora >= m.expira_em:
            # validade própria (código de acesso: 5 min) vale até para "reenviar"
            m.status = StatusMensagem.EXPIRADA
            repo_msg.apagar_texto_individual(m)
            return None
        validade = timedelta(hours=geral.validade_oportunidade_h)
        if m.destino == "oportunidades" and not m.ignorar_validade and agora - m.criada_em > validade:
            m.status = StatusMensagem.EXPIRADA
            return None
        individual = m.destino == Destino.INDIVIDUAL.value
        if individual:
            alvo = (m.numero or "").removeprefix("+")  # a Evolution quer só os dígitos
        else:
            alvo = geral.whatsapp_grupo_admin if m.destino == "admin" else geral.whatsapp_grupo_oportunidades
        falta = None
        if self._chave is None:
            falta = "EVOLUTION_URL ou EVOLUTION_API_KEY ausente (ou com o valor padrão) no .env"
        elif not geral.evolution_instancia:
            falta = "sem instância da Evolution em Configurações → Geral"
        elif not alvo:
            falta = f"sem grupo de {m.destino} em Configurações → Geral"
        if falta is not None:
            m.ultimo_erro = falta
            m.proxima_tentativa_em = agora + ESPERA_SEM_DESTINO
            return None
        # linhas antigas da fila e "reenviar" saem como estão gravadas: a guarda de URL vale aqui também
        texto = formato.conferir_urls(m.texto, avisos.zona_e_host(s)[1], estrito=False)
        resultado, erro = enviar_uma_vez(
            self._cliente, self._config_env.evolution_url, self._chave, geral.evolution_instancia, alvo, texto
        )
        if individual and erro and m.numero:
            erro = ocultar_numero(erro, m.numero)  # a Evolution pode repetir o número no erro
        if resultado is Resultado.OK:
            m.status = StatusMensagem.ENVIADA
            m.enviada_em = agora
            m.ultimo_erro = None
            repo_msg.apagar_texto_individual(m)
            return resultado
        m.tentativas += 1
        m.ultimo_erro = erro
        if resultado is Resultado.DEFINITIVO and m.tentativas >= MAX_TENTATIVAS_DEFINITIVAS:
            m.status = StatusMensagem.FALHA
            repo_msg.apagar_texto_individual(m)
            log.error("mensagem %d para %s falhou de vez: %s", m.id, m.destino, erro)
            if not formato.eh_do_tipo(m.texto, TipoAviso.MENSAGEM_NAO_ENVIADA):  # nunca em laço
                self._avisar_falha(s, agora)
            return resultado
        m.proxima_tentativa_em = agora + timedelta(minutes=min(2 ** min(m.tentativas - 1, 5), ESPERA_MAX_MIN))
        log.warning("mensagem %d para %s não saiu (tentativa %d): %s", m.id, m.destino, m.tentativas, erro)
        return resultado
```

(O log usa `m.destino`, que para individual é a palavra `individual`, nunca o número. O aviso `MENSAGEM_NAO_ENVIADA` lista `#id para individual: <erro já mascarado>`.)

- [ ] **Step 10: Admin (Mensagens e aba Avisos)**

Em `src/tcg_sniper/admin/consultas_mensagens.py`: `DESTINOS = ("todos", "admin", "oportunidades", "individual")`.

Em `src/tcg_sniper/admin/app.py`, depois de `MENSAGEM_AVISOS = ...`:

```python
ROTULOS_DESTINO = {
    Destino.ADMIN: "grupo admin",
    Destino.OPORTUNIDADES: "grupo oportunidades",
    Destino.INDIVIDUAL: "só para a pessoa",
}
```

e em `_avisos_da_tela` troque `"grupo": "oportunidades" if d.grupo is Destino.OPORTUNIDADES else "admin",` por `"grupo": ROTULOS_DESTINO[d.grupo],`.

Em `src/tcg_sniper/admin/templates/configuracoes.html` (bloco da aba Avisos), troque:

```html
              {% else %}<span class="badge badge-info badge-sm">Oportunidade</span>{% endif %}
              <span class="badge badge-ghost badge-sm">grupo {{ a.grupo }}</span>
```

por:

```html
              {% elif a.severidade == "acesso" %}<span class="badge badge-neutral badge-sm">Acesso</span>
              {% else %}<span class="badge badge-info badge-sm">Oportunidade</span>{% endif %}
              <span class="badge badge-ghost badge-sm">{{ a.grupo }}</span>
```

Regere o CSS: `uv run python scripts/gerar_css.py` (baixa as ferramentas em `.ferramentas/` do worktree na primeira vez).

- [ ] **Step 11: Rodar os testes da tarefa**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t2 uv run pytest tests/avisos tests/notificador tests/db/test_repositorio_mensagens.py tests/admin -q -p no:cacheprovider`
Expected: PASS (inclui `test_regras_globais.py` com os 31 tipos e `test_css_em_dia_com_os_templates`).

- [ ] **Step 12: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t2 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde.

- [ ] **Step 13: Commit**

```bash
git add src/tcg_sniper/notificador src/tcg_sniper/avisos src/tcg_sniper/db/repositorio_mensagens.py src/tcg_sniper/admin tests/avisos tests/notificador tests/db/test_repositorio_mensagens.py tests/admin/test_admin_mensagens.py tests/admin/test_admin_avisos.py
git commit -m "feat: individual WhatsApp messages with own validity and access alert types"
```

---

### Task 3: API base (erros, sessão, permissões, grade e `/api/acessos`)

**Files:**
- Create: `src/tcg_sniper/api/__init__.py`, `api/erros.py`, `api/segredos.py`, `api/permissoes.py`, `api/dependencias.py`, `api/rotas_acessos.py`, `api/app.py`
- Create: `tests/fakes_api.py`, `tests/api/conftest.py`
- Modify: `src/tcg_sniper/config.py` (campo `segredo_api`), `.env.example` (`SEGREDO_API`), `tests/conftest.py` (segredo falso no fixture `config`)
- Test: `tests/api/test_base.py`, `tests/api/test_acessos.py` (novos)

**Interfaces:**
- Consumes (Task 1): `models.Papel`, `models.Usuario`, `models.Sessao`; `repo_acesso.sessao_por_hash`, `grade_salva`, `salvar_permissao`, `criar_usuario`, `criar_sessao`; `db.repositorio.agora_utc`.
- Produces:
  - `api.erros`: `class ErroApi(Exception)` com `ErroApi(status: int, erro: str, mensagem: str)` e atributos `.status`, `.erro`, `.mensagem`; `MENSAGEM_NUMERO_INVALIDO = "Número inválido. Use DDD e número, ex.: (11) 9XXXX-XXXX."`; `instalar_tratadores(app: FastAPI) -> None`.
  - `config.Config.segredo_api: SecretStr | None = None` (variável `SEGREDO_API`).
  - `api.segredos`: `gerar_codigo() -> str` (6 dígitos), `gerar_token() -> str`, `hash_segredo(segredo: str, texto: str) -> str` (HMAC-SHA256 hex com o segredo como chave); `TAMANHO_MINIMO_SEGREDO = 32`, `SEGREDO_EXEMPLO = "trocar-este-segredo"`, `class SegredoAusente(Exception)` (a mensagem diz o que fazer e como gerar), `exigir_segredo(config: Config) -> str` (o valor; `SegredoAusente` se vazio, igual ao exemplo ou com menos de 32 caracteres).
  - `api.permissoes`: `class Permissao(StrEnum)` com `VER_AREA_NEGOCIO="ver_area_negocio"`, `VER_AREA_GESTAO="ver_area_gestao"`, `GERIR_USUARIOS="gerir_usuarios"`, `GERIR_ACESSOS="gerir_acessos"`, `VER_DOCUMENTACAO_API="ver_documentacao_api"`; `DefinicaoPermissao(rotulo: str, descricao: str)`; `DEFINICOES: dict[Permissao, DefinicaoPermissao]`; `ROTULOS_PAPEL: dict[Papel, str]` (`Grupo`, `Operador`, `Admin`); `PAPEIS_EDITAVEIS = (Papel.GRUPO, Papel.OPERADOR)`; `PADROES: dict[Papel, frozenset[Permissao]]`; `calcular_grade(salvas: dict[tuple[Papel, str], bool]) -> dict[Papel, frozenset[Permissao]]`; `class GradePermissoes(sessoes, ttl_s: float = 5.0, monotonico: Callable[[], float] = time.monotonic)` com `.grade() -> dict[Papel, frozenset[Permissao]]`, `.efetivas(papel: Papel) -> frozenset[Permissao]`, `.invalidar() -> None`.
  - `api.dependencias`: `COOKIE = "sessao"`, `VALIDADE_SESSAO = timedelta(days=30)`, `MAX_TOKEN = 200`; `Contexto(usuario_id: int, nome: str, papel: Papel, permissoes: frozenset[Permissao], sessao_id: int, superadmin: bool)` (frozen); `usuario_logado(request: Request) -> Contexto` (401 `sem_sessao`); `exige(permissao: Permissao) -> Callable[..., Contexto]` (a função devolvida tem o atributo `.permissao`; 403 `sem_permissao`); `https(request: Request) -> bool`.
  - `api.app.criar_app(sessoes: sessionmaker[Session], config: Config, relogio: Callable[[], datetime] | None = None) -> FastAPI` (`SegredoAusente` sem `SEGREDO_API` válida: não sobe); `app.state.sessoes`, `.config`, `.relogio`, `.grade` (`GradePermissoes`), `.segredo` (str, o valor de `SEGREDO_API`).
  - `api.rotas_acessos`: `roteador` (prefixo `/api/acessos`); `Mudanca(papel: Papel, permissao: Permissao, permitido: bool)`; `aplicar_mudancas(s, atual: dict[Papel, frozenset[Permissao]], mudancas: list[Mudanca]) -> list[Mudanca]` (grava e devolve só as que trocam o valor).
  - JSON de `GET/PUT /api/acessos`:
    ```json
    {"papeis": [{"papel": "grupo", "rotulo": "Grupo", "editavel": true},
                {"papel": "operador", "rotulo": "Operador", "editavel": true},
                {"papel": "admin", "rotulo": "Admin", "editavel": false}],
     "permissoes": [{"permissao": "ver_area_negocio", "rotulo": "Entrar na área de negócio",
                     "descricao": "...", "valores": {"grupo": true, "operador": true, "admin": true}}, ...]}
    ```
    Corpo do `PUT`: `{"mudancas": [{"papel": "grupo", "permissao": "ver_area_gestao", "permitido": true}]}` (1 a 100 itens; papel `admin` → 422 `papel_travado`).
  - `GET /api/saude` → `{"ok": true}` ou 503 `banco_fora`. `GET /api/docs` e `GET /api/openapi.json` exigem `ver_documentacao_api`.
  - Testes: `tests/fakes_api.py` com `T0`, `SEGREDO_TESTE` (segredo falso fixo, o mesmo do fixture `config`), `NUMEROS: dict[Papel, str]`, `Relogio`, `criar_usuario(sessoes, papel, *, nome=None, numero=None, ativo=True, superadmin=False, agora=T0) -> int`, `criar_sessao(sessoes, usuario_id, token, agora=T0) -> int`, `logar(sessoes, cliente, papel, *, nome=None, numero=None, token=None, superadmin=False, agora=T0) -> int`, `mensagens(sessoes, destino) -> list[str]`; fixtures em `tests/api/conftest.py`: `relogio`, `app_api`, `cliente`, `logar` (atalho para o `cliente` padrão).

- [ ] **Step 1: Banco da lane**

Run: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_t3`

- [ ] **Step 2: Ajudantes de teste**

Crie `tests/fakes_api.py`:

```python
"""Ajudantes dos testes da API: relógio controlável e usuário logado com token conhecido (sem passar pelo login)."""

from datetime import UTC, datetime

from sqlalchemy import select

from tcg_sniper.api.dependencias import COOKIE, VALIDADE_SESSAO
from tcg_sniper.api.segredos import hash_segredo
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import MensagemSaida, Papel

T0 = datetime(2026, 10, 18, 13, 0, tzinfo=UTC)
# Segredo falso e fixo dos testes (HMAC); o mesmo valor do fixture `config` de tests/conftest.py. Nunca um real.
SEGREDO_TESTE = "segredo-de-teste-falso-0123456789abcdefghij"
NUMEROS = {Papel.ADMIN: "+5511900000001", Papel.GRUPO: "+5511900000002", Papel.OPERADOR: "+5511900000003"}


class Relogio:
    def __init__(self, agora: datetime = T0):
        self.agora = agora

    def __call__(self) -> datetime:
        return self.agora


def criar_usuario(sessoes, papel: Papel, *, nome=None, numero=None, ativo=True, superadmin=False, agora=T0) -> int:
    """`superadmin=True` só com `Papel.ADMIN` e ativo (o banco recusa o resto) e um por teste (índice único)."""
    with sessoes() as s, s.begin():
        usuario = repo_acesso.criar_usuario(s, nome or f"Pessoa {papel.value}", numero or NUMEROS[papel], papel, agora)
        usuario.ativo = ativo
        usuario.superadmin = superadmin
        return usuario.id


def criar_sessao(sessoes, usuario_id: int, token: str, agora=T0) -> int:
    hash_token = hash_segredo(SEGREDO_TESTE, token)
    with sessoes() as s, s.begin():
        return repo_acesso.criar_sessao(s, usuario_id, hash_token, "Chrome · Windows", agora, VALIDADE_SESSAO).id


def logar(sessoes, cliente, papel: Papel, *, nome=None, numero=None, token=None, superadmin=False, agora=T0) -> int:
    """Cria o usuário e uma sessão e põe o cookie no cliente (troca o de antes). Devolve o id do usuário."""
    usuario_id = criar_usuario(sessoes, papel, nome=nome, numero=numero, superadmin=superadmin, agora=agora)
    token = token or f"token-{papel.value}-{usuario_id}"
    criar_sessao(sessoes, usuario_id, token, agora)
    cliente.cookies.set(COOKIE, token)
    return usuario_id


def mensagens(sessoes, destino: str) -> list[str]:
    with sessoes() as s:
        return list(
            s.scalars(select(MensagemSaida.texto).where(MensagemSaida.destino == destino).order_by(MensagemSaida.id))
        )
```

Em `tests/conftest.py`, no fixture `config`, acrescente o argumento `segredo_api="segredo-de-teste-falso-0123456789abcdefghij",` (o mesmo valor de `fakes_api.SEGREDO_TESTE`; `test_segredo_do_config_e_o_dos_fakes` confere).

Crie `tests/api/conftest.py`:

```python
import pytest
from fastapi.testclient import TestClient

import fakes_api
from tcg_sniper.api.app import criar_app


@pytest.fixture
def relogio():
    return fakes_api.Relogio()


@pytest.fixture
def app_api(sessoes, config, relogio):
    """Um app por teste: o cache da grade de permissões não passa de um teste para outro."""
    return criar_app(sessoes, config, relogio=relogio)


@pytest.fixture
def cliente(app_api):
    return TestClient(app_api)


@pytest.fixture
def logar(sessoes, cliente):
    def _logar(papel, **kwargs):
        return fakes_api.logar(sessoes, cliente, papel, **kwargs)

    return _logar
```

- [ ] **Step 3: Testes (falham)**

Crie `tests/api/test_base.py`:

```python
import hashlib
import hmac
from datetime import timedelta

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from fakes_api import SEGREDO_TESTE, T0
from tcg_sniper.api.app import criar_app
from tcg_sniper.api.segredos import SegredoAusente, exigir_segredo, hash_segredo
from tcg_sniper.db.models import Papel, Sessao, Usuario

PUBLICAS = {
    ("GET", "/api/saude"),
    ("POST", "/api/auth/pedir-codigo"),
    ("POST", "/api/auth/entrar"),
    ("POST", "/api/auth/sair"),
    ("GET", "/api/auth/eu"),  # exige sessão, mas nenhuma permissão
}


def test_saude_sem_login(cliente):
    r = cliente.get("/api/saude")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_segredo_do_config_e_o_dos_fakes(config, app_api):
    assert config.segredo_api.get_secret_value() == SEGREDO_TESTE == app_api.state.segredo


def test_hash_e_hmac_com_o_segredo():
    esperado = hmac.new(SEGREDO_TESTE.encode(), b"123456", hashlib.sha256).hexdigest()
    assert hash_segredo(SEGREDO_TESTE, "123456") == esperado
    assert hash_segredo(SEGREDO_TESTE, "123456") != hashlib.sha256(b"123456").hexdigest()  # nunca SHA-256 puro
    assert hash_segredo("outro-segredo-falso-0123456789abcdefghij", "123456") != esperado


@pytest.mark.parametrize("valor", [None, "", "   ", "trocar-este-segredo", "curto-demais"])
def test_app_nao_sobe_sem_segredo(sessoes, config, valor):
    sem = config.model_copy(update={"segredo_api": None if valor is None else SecretStr(valor)})
    with pytest.raises(SegredoAusente, match="SEGREDO_API") as erro:
        criar_app(sessoes, sem)
    assert "token_urlsafe" in str(erro.value)  # diz como gerar
    with pytest.raises(SegredoAusente):
        exigir_segredo(sem)


def test_saude_com_banco_fora_responde_503(config):
    url = "postgresql+psycopg://tcg:tcg@127.0.0.1:1/tcg_test_fora"
    fora = sessionmaker(bind=create_engine(url, connect_args={"connect_timeout": 2}))
    r = TestClient(criar_app(fora, config)).get("/api/saude")
    assert r.status_code == 503 and r.json()["erro"] == "banco_fora"


def test_rota_inexistente_404_em_json(cliente):
    r = cliente.get("/api/nada")
    assert r.status_code == 404 and r.json() == {"erro": "nao_encontrado", "mensagem": "Não encontrado."}


def test_sem_cookie_401_em_json(cliente):
    r = cliente.get("/api/acessos")
    assert r.status_code == 401 and r.json() == {"erro": "sem_sessao", "mensagem": "Entre de novo para continuar."}


def test_token_desconhecido_ou_gigante_401(cliente):
    for token in ("nao-existe", "x" * 500):
        cliente.cookies.set("sessao", token)
        assert cliente.get("/api/acessos").status_code == 401


def test_sessao_vencida_401(cliente, logar, relogio):
    logar(Papel.ADMIN)
    relogio.agora = T0 + timedelta(days=30)
    assert cliente.get("/api/acessos").status_code == 401


def test_sessao_encerrada_401(cliente, logar, sessoes):
    usuario_id = logar(Papel.ADMIN)
    with sessoes() as s, s.begin():
        s.execute(update(Sessao).where(Sessao.usuario_id == usuario_id).values(encerrada_em=T0))
    assert cliente.get("/api/acessos").status_code == 401


def test_usuario_desativado_401_mesmo_com_sessao_aberta(cliente, logar, sessoes):
    usuario_id = logar(Papel.ADMIN)
    with sessoes() as s, s.begin():
        s.get(Usuario, usuario_id).ativo = False
    assert cliente.get("/api/acessos").status_code == 401


def test_uso_renova_a_validade_e_o_ultimo_uso(cliente, logar, relogio, sessoes):
    usuario_id = logar(Papel.ADMIN)
    relogio.agora = T0 + timedelta(days=20)
    assert cliente.get("/api/acessos").status_code == 200
    with sessoes() as s:
        sessao = s.scalars(select(Sessao).where(Sessao.usuario_id == usuario_id)).one()
        assert (sessao.ultimo_uso_em, sessao.expira_em) == (relogio.agora, relogio.agora + timedelta(days=30))
    relogio.agora = T0 + timedelta(days=45)  # 25 dias depois do último uso: ainda vale
    assert cliente.get("/api/acessos").status_code == 200


def test_documentacao_exige_permissao(cliente, logar):
    logar(Papel.GRUPO)
    assert cliente.get("/api/docs").status_code == 403
    assert cliente.get("/api/openapi.json").status_code == 403
    logar(Papel.ADMIN)
    docs = cliente.get("/api/docs")
    assert docs.status_code == 200 and "swagger" in docs.text.lower()
    assert "/api/acessos" in cliente.get("/api/openapi.json").json()["paths"]
    assert cliente.get("/docs").status_code == 404 and cliente.get("/openapi.json").status_code == 404


def test_toda_rota_da_api_declara_permissao_ou_e_publica(app_api):
    def chamadas(dependente):
        for d in dependente.dependencies:
            yield d.call
            yield from chamadas(d)

    sem_permissao = []
    for rota in app_api.routes:
        if not isinstance(rota, APIRoute):
            continue
        assert rota.path.startswith("/api/"), rota.path
        for metodo in rota.methods:
            if (metodo, rota.path) in PUBLICAS:
                continue
            if not any(getattr(c, "permissao", None) for c in chamadas(rota.dependant)):
                sem_permissao.append(f"{metodo} {rota.path}")
    assert sem_permissao == []
```

Crie `tests/api/test_acessos.py`:

```python
from fastapi.testclient import TestClient

from fakes_api import logar as logar_cliente
from tcg_sniper.api.permissoes import GradePermissoes, Permissao, calcular_grade
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Papel

GESTAO_PARA_GRUPO = {"mudancas": [{"papel": "grupo", "permissao": "ver_area_gestao", "permitido": True}]}


def linhas(resposta):
    return {linha["permissao"]: linha for linha in resposta.json()["permissoes"]}


def test_padroes_e_linhas_salvas():
    padrao = calcular_grade({})
    assert padrao[Papel.GRUPO] == {Permissao.VER_AREA_NEGOCIO}
    assert padrao[Papel.OPERADOR] == {Permissao.VER_AREA_NEGOCIO, Permissao.VER_AREA_GESTAO}
    assert padrao[Papel.ADMIN] == set(Permissao)
    salvas = {
        (Papel.GRUPO, "ver_area_negocio"): False,
        (Papel.ADMIN, "gerir_acessos"): False,  # ignorada: admin tem tudo
        (Papel.OPERADOR, "permissao_de_outra_fase"): True,  # ignorada: não existe no código
        (Papel.OPERADOR, "gerir_usuarios"): True,
    }
    grade = calcular_grade(salvas)
    assert grade[Papel.GRUPO] == frozenset()
    assert grade[Papel.ADMIN] == set(Permissao)
    assert grade[Papel.OPERADOR] == {Permissao.VER_AREA_NEGOCIO, Permissao.VER_AREA_GESTAO, Permissao.GERIR_USUARIOS}


def test_grade_em_cache_ate_vencer_ou_invalidar(sessoes):
    agora = [100.0]
    grade = GradePermissoes(sessoes, ttl_s=5.0, monotonico=lambda: agora[0])
    assert Permissao.VER_AREA_GESTAO not in grade.efetivas(Papel.GRUPO)
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.GRUPO, "ver_area_gestao", True)
    assert Permissao.VER_AREA_GESTAO not in grade.efetivas(Papel.GRUPO)  # ainda o cache
    agora[0] += 5.0
    assert Permissao.VER_AREA_GESTAO in grade.efetivas(Papel.GRUPO)
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.GRUPO, "ver_area_gestao", False)
    grade.invalidar()
    assert Permissao.VER_AREA_GESTAO not in grade.efetivas(Papel.GRUPO)


def test_grade_padrao_com_rotulos(cliente, logar):
    logar(Papel.ADMIN)
    r = cliente.get("/api/acessos")
    assert r.status_code == 200
    assert r.json()["papeis"] == [
        {"papel": "grupo", "rotulo": "Grupo", "editavel": True},
        {"papel": "operador", "rotulo": "Operador", "editavel": True},
        {"papel": "admin", "rotulo": "Admin", "editavel": False},
    ]
    por_permissao = linhas(r)
    assert list(por_permissao) == [p.value for p in Permissao]
    assert por_permissao["ver_area_gestao"]["rotulo"] == "Entrar na área de gestão"
    assert por_permissao["ver_area_gestao"]["descricao"]
    assert por_permissao["ver_area_gestao"]["valores"] == {"grupo": False, "operador": True, "admin": True}
    assert por_permissao["gerir_acessos"]["valores"] == {"grupo": False, "operador": False, "admin": True}


def test_grupo_e_operador_nao_veem_a_grade_por_padrao(app_api, sessoes):
    for papel in (Papel.GRUPO, Papel.OPERADOR):
        cliente = TestClient(app_api)
        logar_cliente(sessoes, cliente, papel)
        r = cliente.get("/api/acessos")
        assert r.status_code == 403 and r.json()["erro"] == "sem_permissao"


def test_mudanca_vale_na_proxima_requisicao(app_api, sessoes):
    admin, operador = TestClient(app_api), TestClient(app_api)
    logar_cliente(sessoes, admin, Papel.ADMIN)
    logar_cliente(sessoes, operador, Papel.OPERADOR)
    assert operador.get("/api/acessos").status_code == 403
    liberar = {"mudancas": [{"papel": "operador", "permissao": "gerir_acessos", "permitido": True}]}
    r = admin.put("/api/acessos", json=liberar)
    assert r.status_code == 200 and linhas(r)["gerir_acessos"]["valores"]["operador"] is True
    assert operador.get("/api/acessos").status_code == 200
    tirar = {"mudancas": [{"papel": "operador", "permissao": "gerir_acessos", "permitido": False}]}
    assert admin.put("/api/acessos", json=tirar).status_code == 200
    assert operador.get("/api/acessos").status_code == 403


def test_admin_e_travado_e_linhas_dele_no_banco_sao_ignoradas(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    r = cliente.put("/api/acessos", json={"mudancas": [{"papel": "admin", "permissao": "gerir_acessos", "permitido": False}]})
    assert r.status_code == 422 and r.json()["erro"] == "papel_travado"
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.ADMIN, "gerir_acessos", False)
    cliente.app.state.grade.invalidar()
    assert cliente.get("/api/acessos").status_code == 200


def test_permissao_desconhecida_ou_lista_vazia_422(cliente, logar):
    logar(Papel.ADMIN)
    for corpo in (
        {"mudancas": [{"papel": "grupo", "permissao": "voar", "permitido": True}]},
        {"mudancas": []},
        {"mudancas": [{"papel": "grupo", "permissao": "ver_area_gestao", "permitido": True, "extra": 1}]},
    ):
        r = cliente.put("/api/acessos", json=corpo)
        assert r.status_code == 422 and r.json()["erro"] == "validacao", corpo
        assert "voar" not in r.text


def test_mudanca_igual_ao_atual_nao_grava(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    assert cliente.put("/api/acessos", json=GESTAO_PARA_GRUPO).status_code == 200
    assert cliente.put("/api/acessos", json=GESTAO_PARA_GRUPO).status_code == 200
    with sessoes() as s:
        assert repo_acesso.grade_salva(s) == {(Papel.GRUPO, "ver_area_gestao"): True}
```

- [ ] **Step 4: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t3 uv run pytest tests/api -q -p no:cacheprovider`
Expected: FAIL (`tcg_sniper.api` não existe).

- [ ] **Step 5: Pacote, erros e segredos**

Crie `src/tcg_sniper/api/__init__.py`:

```python
"""Serviço `api`: FastAPI só com rotas /api em JSON, para o front React (web/). Login por código no WhatsApp,
sessão em cookie e permissões por papel (grade em Gestão → Acessos). O admin antigo (admin/) continua à parte."""
```

Crie `src/tcg_sniper/api/erros.py`:

```python
"""Erros da API em JSON padronizado: {"erro": "<código>", "mensagem": "<texto em português>"}.
Nenhuma resposta de erro ecoa o valor recebido (pode ser número de telefone ou código)."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

MENSAGEM_NUMERO_INVALIDO = "Número inválido. Use DDD e número, ex.: (11) 9XXXX-XXXX."
PADROES = {
    401: ("sem_sessao", "Entre de novo para continuar."),
    403: ("sem_permissao", "Seu acesso não permite isto."),
    404: ("nao_encontrado", "Não encontrado."),
    405: ("metodo_invalido", "Método não permitido."),
    422: ("validacao", "Dados inválidos."),
    429: ("limite", "Muitos pedidos. Espere alguns minutos e tente de novo."),
}


class ErroApi(Exception):
    def __init__(self, status: int, erro: str, mensagem: str):
        super().__init__(erro)
        self.status = status
        self.erro = erro
        self.mensagem = mensagem


def _resposta(status: int, erro: str, mensagem: str) -> JSONResponse:
    return JSONResponse({"erro": erro, "mensagem": mensagem}, status_code=status)


def instalar_tratadores(app: FastAPI) -> None:
    @app.exception_handler(ErroApi)
    async def _erro_api(_request: Request, erro: ErroApi) -> JSONResponse:
        return _resposta(erro.status, erro.erro, erro.mensagem)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, erro: StarletteHTTPException) -> JSONResponse:
        codigo, mensagem = PADROES.get(erro.status_code, ("erro", "Erro inesperado."))
        return _resposta(erro.status_code, codigo, mensagem)

    @app.exception_handler(RequestValidationError)
    async def _validacao(_request: Request, erro: RequestValidationError) -> JSONResponse:
        """Diz quais campos estão errados, nunca o valor recebido."""
        campos = sorted({str(e["loc"][-1]) for e in erro.errors() if e.get("loc")} - {"body"})
        mensagem = "Dados inválidos" + (f": {', '.join(campos)}." if campos else ".")
        return _resposta(422, "validacao", mensagem)

    @app.exception_handler(Exception)
    async def _inesperado(request: Request, _erro: Exception) -> JSONResponse:
        log.exception("erro inesperado em %s %s", request.method, request.url.path)
        return _resposta(500, "interno", "Erro interno. Tente de novo em instantes.")
```

Crie `src/tcg_sniper/api/segredos.py`:

```python
"""Segredos do login: código de 6 dígitos e token de sessão (aleatórios criptográficos) e o hash que vai para o
banco: HMAC-SHA256 com a chave `SEGREDO_API` do .env, nunca SHA-256 puro (sem a chave, quem lê o banco não
consegue testar os 1 milhão de códigos nem descobrir o número de um pedido). Código e token nunca vão para log nem
para o banco em texto."""

import hashlib
import hmac
import secrets

from tcg_sniper.config import Config

TAMANHO_MINIMO_SEGREDO = 32
SEGREDO_EXEMPLO = "trocar-este-segredo"  # o valor do .env.example
COMO_GERAR = 'python -c "import secrets; print(secrets.token_urlsafe(32))"'


class SegredoAusente(Exception):
    """SEGREDO_API vazia, igual à do exemplo ou curta: a API (e o código de emergência) não começam sem ela."""


def exigir_segredo(config: Config) -> str:
    valor = config.segredo_api.get_secret_value().strip() if config.segredo_api else ""
    if not valor or valor == SEGREDO_EXEMPLO or len(valor) < TAMANHO_MINIMO_SEGREDO:
        raise SegredoAusente(
            f"SEGREDO_API ausente ou fraca no .env (mínimo {TAMANHO_MINIMO_SEGREDO} caracteres). "
            f"Gere uma com: {COMO_GERAR}"
        )
    return valor


def gerar_codigo() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def gerar_token() -> str:
    return secrets.token_urlsafe(32)


def hash_segredo(segredo: str, texto: str) -> str:
    """HMAC-SHA256 em hexadecimal, com `segredo` (SEGREDO_API) como chave: código, token e número do pedido."""
    return hmac.new(segredo.encode(), texto.encode(), hashlib.sha256).hexdigest()
```

Em `src/tcg_sniper/config.py`, depois de `admin_senha`, acrescente o campo (opcional aqui porque coletores, casador e admin não usam; quem usa chama `exigir_segredo`):

```python
    # Chave do HMAC do login do site novo (código, token de sessão e número do pedido). Obrigatória para o serviço
    # `api` e o `codigo-acesso`; ver .env.example.
    segredo_api: SecretStr | None = None
```

Em `.env.example`, na seção "Acesso", depois do bloco do `VNC_SENHA`, acrescente:

```bash
# Chave secreta do login do site novo (serviço api, http://<IP deste PC>:8090): o banco guarda o código
# de acesso, o token da sessão e o número dos pedidos só como HMAC com esta chave. Obrigatória: vazia,
# "trocar-este-segredo" ou com menos de 32 caracteres, a api não sobe. Gere uma com:
#   python -c "import secrets; print(secrets.token_urlsafe(32))"
# Trocar a chave derruba todas as sessões e códigos abertos (todos entram de novo pelo WhatsApp).
SEGREDO_API=trocar-este-segredo
```

E no cabeçalho do `.env.example`, em "Antes de subir, troque obrigatoriamente:", acrescente `SEGREDO_API` à lista (`ADMIN_SENHA, VNC_SENHA, EVOLUTION_API_KEY, SEGREDO_API`).

- [ ] **Step 6: Permissões e grade**

Crie `src/tcg_sniper/api/permissoes.py`:

```python
"""Permissões do site: lista fechada no código; cada fase acrescenta as suas. O que cada papel pode é configurável
na grade papel × permissão (tabela `permissao_papel`, tela Gestão → Acessos); linha ausente vale o padrão daqui.
O admin tem sempre todas (linhas do admin no banco são ignoradas)."""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Papel


class Permissao(StrEnum):
    VER_AREA_NEGOCIO = "ver_area_negocio"
    VER_AREA_GESTAO = "ver_area_gestao"
    GERIR_USUARIOS = "gerir_usuarios"
    GERIR_ACESSOS = "gerir_acessos"
    VER_DOCUMENTACAO_API = "ver_documentacao_api"


@dataclass(frozen=True)
class DefinicaoPermissao:
    rotulo: str
    descricao: str


DEFINICOES: dict[Permissao, DefinicaoPermissao] = {
    Permissao.VER_AREA_NEGOCIO: DefinicaoPermissao(
        "Entrar na área de negócio", "Ver a área de negócio (oportunidades e resultados do grupo)."
    ),
    Permissao.VER_AREA_GESTAO: DefinicaoPermissao(
        "Entrar na área de gestão", "Ver o menu e as telas da área administrativa."
    ),
    Permissao.GERIR_USUARIOS: DefinicaoPermissao(
        "Gerir usuários", "Listar, criar, editar e desativar usuários e encerrar sessões."
    ),
    Permissao.GERIR_ACESSOS: DefinicaoPermissao("Gerir acessos", "Editar esta grade de papel × permissão."),
    Permissao.VER_DOCUMENTACAO_API: DefinicaoPermissao(
        "Ver a documentação da API", "Abrir /api/docs (OpenAPI)."
    ),
}
ROTULOS_PAPEL = {Papel.GRUPO: "Grupo", Papel.OPERADOR: "Operador", Papel.ADMIN: "Admin"}
PAPEIS_EDITAVEIS = (Papel.GRUPO, Papel.OPERADOR)
PADROES: dict[Papel, frozenset[Permissao]] = {
    Papel.GRUPO: frozenset({Permissao.VER_AREA_NEGOCIO}),
    Papel.OPERADOR: frozenset({Permissao.VER_AREA_NEGOCIO, Permissao.VER_AREA_GESTAO}),
    Papel.ADMIN: frozenset(Permissao),
}
TTL_CACHE_S = 5.0


def calcular_grade(salvas: dict[tuple[Papel, str], bool]) -> dict[Papel, frozenset[Permissao]]:
    """Permissões efetivas de cada papel: linha salva ou, sem ela, o padrão. Admin: todas."""
    grade = {Papel.ADMIN: frozenset(Permissao)}
    for papel in PAPEIS_EDITAVEIS:
        grade[papel] = frozenset(p for p in Permissao if salvas.get((papel, p.value), p in PADROES[papel]))
    return grade


class GradePermissoes:
    """A grade lida do banco com cache curto (`ttl_s`); `invalidar()` depois de salvar faz a mudança valer na
    próxima requisição de quem já está logado."""

    def __init__(
        self,
        sessoes: sessionmaker[Session],
        ttl_s: float = TTL_CACHE_S,
        monotonico: Callable[[], float] = time.monotonic,
    ):
        self._sessoes = sessoes
        self._ttl_s = ttl_s
        self._monotonico = monotonico
        self._trava = threading.Lock()
        self._grade: dict[Papel, frozenset[Permissao]] | None = None
        self._lida_em = 0.0

    def grade(self) -> dict[Papel, frozenset[Permissao]]:
        with self._trava:
            agora = self._monotonico()
            if self._grade is None or agora - self._lida_em >= self._ttl_s:
                with self._sessoes() as s:
                    self._grade = calcular_grade(repo_acesso.grade_salva(s))
                self._lida_em = agora
            return self._grade

    def efetivas(self, papel: Papel) -> frozenset[Permissao]:
        return self.grade()[papel]

    def invalidar(self) -> None:
        with self._trava:
            self._grade = None
```

- [ ] **Step 7: Sessão e `exige`**

Crie `src/tcg_sniper/api/dependencias.py`:

```python
"""Dependências das rotas: quem está logado (cookie `sessao`) e a permissão que cada rota exige.
O back sempre confere: o front só esconde o que a pessoa não pode."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request

from tcg_sniper.api.erros import ErroApi
from tcg_sniper.api.permissoes import Permissao
from tcg_sniper.api.segredos import hash_segredo
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Papel, Usuario

COOKIE = "sessao"
VALIDADE_SESSAO = timedelta(days=30)
MAX_TOKEN = 200  # token maior que isso nem é procurado
MENSAGEM_SEM_SESSAO = "Entre de novo para continuar."


@dataclass(frozen=True)
class Contexto:
    usuario_id: int
    nome: str
    papel: Papel
    permissoes: frozenset[Permissao]
    sessao_id: int
    superadmin: bool  # o dono do sistema: só ele mexe em admins (rotas_usuarios)


def https(request: Request) -> bool:
    """Servido em HTTPS? Atrás do Caddy ou de um túnel vale o X-Forwarded-Proto."""
    return request.headers.get("x-forwarded-proto", request.url.scheme) == "https"


def usuario_logado(request: Request) -> Contexto:
    """Sessão ativa e não vencida de um usuário ativo; renova a validade e o último uso. Senão, 401."""
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) > MAX_TOKEN:
        raise ErroApi(401, "sem_sessao", MENSAGEM_SEM_SESSAO)
    estado = request.app.state
    agora = estado.relogio()
    with estado.sessoes() as s, s.begin():
        sessao = repo_acesso.sessao_por_hash(s, hash_segredo(estado.segredo, token))
        usuario = s.get(Usuario, sessao.usuario_id) if sessao is not None else None
        if (
            sessao is None
            or usuario is None
            or not usuario.ativo
            or sessao.encerrada_em is not None
            or sessao.expira_em <= agora
        ):
            raise ErroApi(401, "sem_sessao", MENSAGEM_SEM_SESSAO)
        sessao.ultimo_uso_em = agora
        sessao.expira_em = agora + VALIDADE_SESSAO
        usuario_id, nome, papel, sessao_id, superadmin = (
            usuario.id, usuario.nome, usuario.papel, sessao.id, usuario.superadmin
        )
    # fora da transação: a grade abre a própria sessão (o superadmin é admin: todas as permissões)
    return Contexto(usuario_id, nome, papel, estado.grade.efetivas(papel), sessao_id, superadmin)


def exige(permissao: Permissao) -> Callable[..., Contexto]:
    """Dependência de uma rota protegida: `Annotated[Contexto, Depends(exige(Permissao.X))]`."""

    def dependencia(contexto: Annotated[Contexto, Depends(usuario_logado)]) -> Contexto:
        if permissao not in contexto.permissoes:
            raise ErroApi(403, "sem_permissao", "Seu acesso não permite isto.")
        return contexto

    dependencia.permissao = permissao  # o teste das rotas confere que toda rota declara uma
    return dependencia
```

- [ ] **Step 8: `/api/acessos`**

Crie `src/tcg_sniper/api/rotas_acessos.py`:

```python
"""Gestão → Acessos: a grade papel × permissão. GET lê, PUT grava (exige `gerir_acessos`); o admin é travado."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from tcg_sniper.api.dependencias import Contexto, exige
from tcg_sniper.api.erros import ErroApi
from tcg_sniper.api.permissoes import DEFINICOES, ROTULOS_PAPEL, Permissao, calcular_grade
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Papel

roteador = APIRouter(prefix="/api/acessos", tags=["acessos"])
GerirAcessos = Annotated[Contexto, Depends(exige(Permissao.GERIR_ACESSOS))]


class Mudanca(BaseModel):
    model_config = ConfigDict(extra="forbid")
    papel: Papel
    permissao: Permissao
    permitido: bool


class MudancasEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mudancas: list[Mudanca] = Field(min_length=1, max_length=100)


class PapelSaida(BaseModel):
    papel: Papel
    rotulo: str
    editavel: bool


class LinhaPermissao(BaseModel):
    permissao: Permissao
    rotulo: str
    descricao: str
    valores: dict[Papel, bool]


class GradeSaida(BaseModel):
    papeis: list[PapelSaida]
    permissoes: list[LinhaPermissao]


def montar_grade(grade: dict[Papel, frozenset[Permissao]]) -> GradeSaida:
    return GradeSaida(
        papeis=[PapelSaida(papel=p, rotulo=ROTULOS_PAPEL[p], editavel=p is not Papel.ADMIN) for p in Papel],
        permissoes=[
            LinhaPermissao(
                permissao=permissao,
                rotulo=DEFINICOES[permissao].rotulo,
                descricao=DEFINICOES[permissao].descricao,
                valores={papel: permissao in grade[papel] for papel in Papel},
            )
            for permissao in Permissao
        ],
    )


def aplicar_mudancas(s: Session, atual: dict[Papel, frozenset[Permissao]], mudancas: list[Mudanca]) -> list[Mudanca]:
    """Grava as mudanças que trocam o valor efetivo e devolve só essas (as iguais ao atual não gravam nem avisam)."""
    feitas = []
    for mudanca in mudancas:
        if (mudanca.permissao in atual[mudanca.papel]) == mudanca.permitido:
            continue
        repo_acesso.salvar_permissao(s, mudanca.papel, mudanca.permissao.value, mudanca.permitido)
        feitas.append(mudanca)
    return feitas


@roteador.get("")
def ler(request: Request, _contexto: GerirAcessos) -> GradeSaida:
    return montar_grade(request.app.state.grade.grade())


@roteador.put("")
def salvar(request: Request, entrada: MudancasEntrada, contexto: GerirAcessos) -> GradeSaida:
    if any(m.papel is Papel.ADMIN for m in entrada.mudancas):
        raise ErroApi(422, "papel_travado", "O admin tem sempre todas as permissões.")
    estado = request.app.state
    with estado.sessoes() as s, s.begin():
        feitas = aplicar_mudancas(s, calcular_grade(repo_acesso.grade_salva(s)), entrada.mudancas)
        del feitas  # Task 5: aviso SEGURANCA_USUARIO de cada mudança feita, nesta mesma transação
    estado.grade.invalidar()
    return montar_grade(estado.grade.grade())
```

(O `del feitas` com o comentário é só o ponto de encaixe da Task 5; ela troca essas duas linhas pelo laço de avisos. `contexto` fica na assinatura porque a Task 5 usa `contexto.nome`.)

- [ ] **Step 9: App**

Crie `src/tcg_sniper/api/app.py`:

```python
"""App FastAPI do serviço `api` (`tcg-sniper api`). Só rotas /api em JSON; sem CORS (o front vem da mesma origem,
pelo Caddy). A documentação OpenAPI fica em /api/docs e exige `ver_documentacao_api`. Não sobe sem `SEGREDO_API`."""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.api import rotas_acessos
from tcg_sniper.api.dependencias import Contexto, exige
from tcg_sniper.api.erros import ErroApi, instalar_tratadores
from tcg_sniper.api.permissoes import GradePermissoes, Permissao
from tcg_sniper.api.segredos import exigir_segredo
from tcg_sniper.config import Config
from tcg_sniper.db.repositorio import agora_utc

log = logging.getLogger(__name__)


def criar_app(
    sessoes: sessionmaker[Session], config: Config, relogio: Callable[[], datetime] | None = None
) -> FastAPI:
    segredo = exigir_segredo(config)  # sem SEGREDO_API válida a API não sobe (SegredoAusente)
    app = FastAPI(title="TCG Sniper · API", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.segredo = segredo
    app.state.sessoes = sessoes
    app.state.config = config
    app.state.relogio = relogio or agora_utc
    app.state.grade = GradePermissoes(sessoes)
    instalar_tratadores(app)
    app.include_router(rotas_acessos.roteador)

    VerDocumentacao = Annotated[Contexto, Depends(exige(Permissao.VER_DOCUMENTACAO_API))]

    @app.get("/api/saude")
    def saude() -> dict[str, bool]:
        """Sem login: o banco responde?"""
        try:
            with sessoes() as s:
                s.execute(text("SELECT 1"))
        except Exception:
            log.warning("saúde: o banco não respondeu")
            raise ErroApi(503, "banco_fora", "O banco de dados não respondeu.") from None
        return {"ok": True}

    @app.get("/api/openapi.json", include_in_schema=False)
    def openapi(_contexto: VerDocumentacao) -> JSONResponse:
        return JSONResponse(app.openapi())

    @app.get("/api/docs", include_in_schema=False)
    def docs(_contexto: VerDocumentacao) -> HTMLResponse:
        return get_swagger_ui_html(openapi_url="/api/openapi.json", title="TCG Sniper · API")

    return app
```

- [ ] **Step 10: Rodar os testes da tarefa**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t3 uv run pytest tests/api -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 11: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t3 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde (`test_regras_globais.py` passa: `api/` não chama `enfileirar` nem lê `host_publico`).

- [ ] **Step 12: Commit**

```bash
git add src/tcg_sniper/api src/tcg_sniper/config.py .env.example tests/conftest.py tests/fakes_api.py tests/api
git commit -m "feat: api service base with session cookie, role grid, hmac secret and json errors"
```

---

### Task 4: Login pelo WhatsApp (pedir código, entrar, sair, eu, limites)

**Files:**
- Create: `src/tcg_sniper/api/acesso.py`, `src/tcg_sniper/api/rotas_auth.py`
- Modify: `src/tcg_sniper/api/app.py` (um `include_router`)
- Test: `tests/api/test_auth.py` (novo)

**Interfaces:**
- Consumes: Task 1 (`repo_acesso.*`, `formatacao.normalizar_numero`, `mascarar_numero`); Task 2 (`avisos.servico.avisar_individual`, `avisos.servico.avisar`, `TipoAviso.CODIGO_ACESSO`, `TipoAviso.SEGURANCA_LIMITE`, `catalogo.Dados`); Task 3 (`ErroApi`, `MENSAGEM_NUMERO_INVALIDO`, `COOKIE`, `VALIDADE_SESSAO`, `MAX_TOKEN`, `Contexto` (com `superadmin`), `usuario_logado`, `https`, `gerar_codigo`, `gerar_token`, `hash_segredo(segredo, texto)`, `Permissao`, `app.state.*` (inclui `.segredo`); fixtures `cliente`, `logar`, `relogio`; `fakes_api.criar_usuario`, `NUMEROS`, `T0`, `SEGREDO_TESTE`, `mensagens`).
- Produces:
  - `api.acesso`: `VALIDADE_CODIGO = timedelta(minutes=5)`, `MAX_TENTATIVAS = 5`, `LIMITE_POR_NUMERO = 3`, `JANELA_NUMERO = timedelta(minutes=15)`, `LIMITE_TOTAL = 20`, `JANELA_TOTAL = timedelta(hours=1)`; `class ResultadoPedido(StrEnum)` (`ACEITO="aceito"`, `LIMITE_NUMERO="limite_numero"`, `LIMITE_TOTAL="limite_total"`); `emitir_codigo(s, usuario_id: int, agora: datetime, segredo: str) -> str`; `pedir_codigo(s, numero: str, agora: datetime, segredo: str) -> ResultadoPedido` (`numero` já normalizado); `entrar(s, numero: str, codigo: str, aparelho: str, agora: datetime, segredo: str) -> tuple[Usuario, str] | None` (o `str` é o token). `segredo` é o valor de `SEGREDO_API` (`app.state.segredo` ou `exigir_segredo(config)`). `resumir_aparelho(user_agent: str | None) -> str`.
  - `api.rotas_auth`: `roteador` (prefixo `/api/auth`); `MENSAGEM_PEDIDO`, `MENSAGEM_CODIGO_INVALIDO`, `MENSAGEM_LIMITE`; `class EuSaida(BaseModel)`: `{"id": int, "nome": str, "papel": "grupo"|"operador"|"admin", "superadmin": bool, "permissoes": [str, ...]}` (na ordem do enum `Permissao`).
  - Rotas: `POST /api/auth/pedir-codigo` `{"numero": str}` → 200 `{"ok": true, "mensagem": MENSAGEM_PEDIDO}` (sempre igual), 422 `numero_invalido`, 429 `limite`; `POST /api/auth/entrar` `{"numero": str, "codigo": "dddddd"}` → 200 `EuSaida` + `Set-Cookie`, 401 `codigo_invalido`; `POST /api/auth/sair` → 200 `{"ok": true}` (apaga o cookie, encerra a sessão se houver); `GET /api/auth/eu` → 200 `EuSaida` (regrava o cookie) ou 401 `sem_sessao`.

- [ ] **Step 1: Banco da lane**

Run: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_t4`

- [ ] **Step 2: Testes (falham)**

Crie `tests/api/test_auth.py`:

```python
import logging
import re
from datetime import timedelta

import pytest
from sqlalchemy import select

from fakes_api import NUMEROS, SEGREDO_TESTE, T0, criar_usuario, mensagens
from tcg_sniper.api import acesso
from tcg_sniper.api.rotas_auth import MENSAGEM_PEDIDO
from tcg_sniper.api.segredos import hash_segredo
from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import TipoAviso
from tcg_sniper.db.models import CodigoAcesso, MensagemSaida, Papel, PedidoCodigo, Sessao

GRUPO = NUMEROS[Papel.GRUPO]  # +5511900000002
CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def individuais(sessoes) -> list[MensagemSaida]:
    with sessoes() as s:
        consulta = select(MensagemSaida).where(MensagemSaida.destino == "individual").order_by(MensagemSaida.id)
        return list(s.scalars(consulta))


def codigo_da_fila(sessoes) -> str:
    return re.search(r"\*(\d{6})\*", individuais(sessoes)[-1].texto).group(1)


def pedir(cliente, numero="(11) 90000-0002", **kwargs):
    return cliente.post("/api/auth/pedir-codigo", json={"numero": numero}, **kwargs)


def entrar(cliente, codigo, numero="11 90000-0002", **kwargs):
    headers = {"User-Agent": CHROME, **kwargs.pop("headers", {})}
    return cliente.post("/api/auth/entrar", json={"numero": numero, "codigo": codigo}, headers=headers, **kwargs)


@pytest.fixture
def codigos(monkeypatch):
    """Códigos previsíveis, na ordem em que são emitidos."""
    fila = ["111111", "222222", "333333", "444444"]
    monkeypatch.setattr(acesso, "gerar_codigo", lambda: fila.pop(0))
    return fila


def test_fluxo_completo_com_numero_formatado(cliente, sessoes):
    criar_usuario(sessoes, Papel.GRUPO, nome="Pessoa Grupo")
    r = pedir(cliente)
    assert r.status_code == 200 and r.json() == {"ok": True, "mensagem": MENSAGEM_PEDIDO}
    [m] = individuais(sessoes)
    assert (m.numero, m.criada_em, m.expira_em) == (GRUPO, T0, T0 + timedelta(minutes=5))
    assert m.texto.startswith("🔑 *Código de acesso*\n")
    r = entrar(cliente, codigo_da_fila(sessoes), numero="+55 11 90000 0002")
    assert r.status_code == 200
    assert {k: r.json()[k] for k in ("nome", "papel", "superadmin", "permissoes")} == {
        "nome": "Pessoa Grupo", "papel": "grupo", "superadmin": False, "permissoes": ["ver_area_negocio"]
    }
    cookie = r.headers["set-cookie"]
    for parte in ("sessao=", "HttpOnly", "Max-Age=2592000", "Path=/", "SameSite=strict"):
        assert parte in cookie, parte
    assert "Secure" not in cookie
    token = r.cookies["sessao"]
    eu = cliente.get("/api/auth/eu")
    assert eu.status_code == 200 and eu.json()["papel"] == "grupo"
    with sessoes() as s:
        sessao = s.scalars(select(Sessao)).one()
        assert (sessao.aparelho, sessao.expira_em) == ("Chrome · Windows", T0 + timedelta(days=30))
    assert cliente.post("/api/auth/sair").json() == {"ok": True}
    cliente.cookies.set("sessao", token)  # mesmo guardando o token, a sessão acabou
    assert cliente.get("/api/auth/eu").status_code == 401


def test_banco_guarda_so_o_hmac_do_codigo_do_token_e_do_numero(cliente, sessoes, codigos):
    criar_usuario(sessoes, Papel.GRUPO)
    pedir(cliente)
    token = entrar(cliente, "111111").cookies["sessao"]
    with sessoes() as s:
        assert s.scalars(select(CodigoAcesso.hash_codigo)).one() == hash_segredo(SEGREDO_TESTE, "111111")
        assert s.scalars(select(PedidoCodigo.numero_hash)).one() == hash_segredo(SEGREDO_TESTE, GRUPO)
        assert s.scalars(select(Sessao.hash_token)).one() == hash_segredo(SEGREDO_TESTE, token)


def test_mesma_resposta_para_numero_inexistente_ou_inativo(cliente, sessoes):
    criar_usuario(sessoes, Papel.GRUPO)
    criar_usuario(sessoes, Papel.OPERADOR, ativo=False)
    respostas = [pedir(cliente, n) for n in ("11 90000-0002", "11 90000-0003", "11 90000-0009")]
    assert {(r.status_code, r.text) for r in respostas} == {(200, respostas[0].text)}
    assert [m.numero for m in individuais(sessoes)] == [GRUPO]


def test_numero_inexistente_nao_entra(cliente, codigos):
    assert entrar(cliente, "111111", numero="11 90000-0009").json()["erro"] == "codigo_invalido"


def test_cinco_codigos_errados_invalidam(cliente, sessoes, codigos):
    criar_usuario(sessoes, Papel.GRUPO)
    pedir(cliente)
    for _ in range(5):
        r = entrar(cliente, "999999")
        assert r.status_code == 401 and r.json()["erro"] == "codigo_invalido"
    assert entrar(cliente, "111111").status_code == 401


def test_codigo_vencido(cliente, sessoes, relogio, codigos):
    criar_usuario(sessoes, Papel.GRUPO)
    pedir(cliente)
    relogio.agora = T0 + timedelta(minutes=5)
    assert entrar(cliente, "111111").status_code == 401


def test_codigo_usado_nao_vale_de_novo(cliente, sessoes, codigos):
    criar_usuario(sessoes, Papel.GRUPO)
    pedir(cliente)
    assert entrar(cliente, "111111").status_code == 200
    assert entrar(cliente, "111111").status_code == 401


def test_so_o_ultimo_codigo_vale(cliente, sessoes, relogio, codigos):
    criar_usuario(sessoes, Papel.GRUPO)
    pedir(cliente)
    relogio.agora = T0 + timedelta(seconds=30)
    pedir(cliente)
    assert entrar(cliente, "111111").status_code == 401
    assert entrar(cliente, "222222").status_code == 200


def test_quarto_pedido_do_mesmo_numero_em_15_min_e_recusado(cliente, sessoes, relogio):
    criar_usuario(sessoes, Papel.GRUPO)
    for minuto in range(3):
        relogio.agora = T0 + timedelta(minutes=minuto)
        assert pedir(cliente).status_code == 200
    r = pedir(cliente, "+55 11 90000-0002")  # outro formato, mesmo número
    assert r.status_code == 429 and r.json()["erro"] == "limite"
    assert len(individuais(sessoes)) == 3
    [aviso] = mensagens(sessoes, "admin")
    assert aviso.startswith("🟡 *Segurança · limite de códigos*")
    assert "final 02" in aviso and "900000002" not in aviso
    relogio.agora = T0 + timedelta(minutes=15)  # o pedido de T0 saiu da janela
    assert pedir(cliente).status_code == 200


def test_limite_vale_tambem_para_numero_sem_usuario(cliente):
    for _ in range(3):
        assert pedir(cliente, "11 90000-0009").status_code == 200
    assert pedir(cliente, "11 90000-0009").status_code == 429


def test_limite_total_por_hora(cliente, relogio):
    for i in range(20):
        assert pedir(cliente, f"11 90000-{i:04d}").status_code == 200
    r = pedir(cliente, "11 90000-0099")
    assert r.status_code == 429 and r.json()["erro"] == "limite"
    relogio.agora = T0 + timedelta(hours=1)
    assert pedir(cliente, "11 90000-0099").status_code == 200


def test_cookie_secure_atras_de_https(cliente, sessoes, codigos):
    criar_usuario(sessoes, Papel.GRUPO)
    pedir(cliente)
    r = entrar(cliente, "111111", headers={"X-Forwarded-Proto": "https"})
    assert r.status_code == 200 and "Secure" in r.headers["set-cookie"]


def test_numero_codigo_e_token_nunca_no_log(cliente, sessoes, caplog, codigos):
    caplog.set_level(logging.DEBUG)
    criar_usuario(sessoes, Papel.GRUPO)
    pedir(cliente)
    entrar(cliente, "999999")
    token = entrar(cliente, "111111").cookies["sessao"]
    for _ in range(3):
        pedir(cliente)  # o último passa do limite
    pedir(cliente, "11 90000-0009")
    for proibido in ("900000002", "900000009", "111111", token):
        assert proibido not in caplog.text, proibido
    assert "+55 11 9****-**02" in caplog.text


def test_numero_ou_codigo_invalido_422_sem_ecoar(cliente):
    r = pedir(cliente, "11 9000O-0002x")
    assert r.status_code == 422 and r.json()["erro"] == "numero_invalido" and "9000O" not in r.text
    r = cliente.post("/api/auth/entrar", json={"numero": "11 90000-0002", "codigo": "12a456"})
    assert r.status_code == 422 and r.json()["erro"] == "validacao" and "12a456" not in r.text


def test_codigo_de_acesso_desligado_nao_enfileira(cliente, sessoes):
    criar_usuario(sessoes, Papel.GRUPO)
    with sessoes() as s, s.begin():
        avisos.definir_ligado(s, TipoAviso.CODIGO_ACESSO, False)
    assert pedir(cliente).status_code == 200
    assert individuais(sessoes) == []


def test_eu_devolve_permissoes_e_renova_o_cookie(cliente, logar):
    logar(Papel.OPERADOR)
    r = cliente.get("/api/auth/eu")
    assert r.json()["permissoes"] == ["ver_area_negocio", "ver_area_gestao"]
    assert "Max-Age=2592000" in r.headers["set-cookie"]


def test_eu_sem_sessao_401(cliente):
    assert cliente.get("/api/auth/eu").json()["erro"] == "sem_sessao"


def test_eu_diz_quem_e_o_superadmin(cliente, logar):
    logar(Papel.ADMIN)
    assert cliente.get("/api/auth/eu").json()["superadmin"] is False
    logar(Papel.ADMIN, numero="+5511900000004", superadmin=True)
    eu = cliente.get("/api/auth/eu").json()
    assert (eu["papel"], eu["superadmin"]) == ("admin", True)
    assert len(eu["permissoes"]) == 5  # todas


@pytest.mark.parametrize(
    ("user_agent", "esperado"),
    [
        (CHROME, "Chrome · Windows"),
        ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36",
         "Chrome · Android"),
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
         "Version/18.0 Mobile/15E148 Safari/604.1", "Safari · iPhone"),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Edg/130.0",
         "Edge · Windows"),
        (None, "navegador desconhecido · sistema desconhecido"),
    ],
)
def test_resumir_aparelho(user_agent, esperado):
    assert acesso.resumir_aparelho(user_agent) == esperado
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t4 uv run pytest tests/api/test_auth.py -q -p no:cacheprovider`
Expected: FAIL (`tcg_sniper.api.acesso` não existe).

- [ ] **Step 4: Regras do login**

Crie `src/tcg_sniper/api/acesso.py`:

```python
"""Login pelo WhatsApp: pedir código (com limites), entrar (código → sessão) e o resumo do aparelho.
Número só aparece em log mascarado; código e token nunca (no banco, só o hash)."""

import logging
import secrets
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy.orm import Session

from tcg_sniper.api.dependencias import VALIDADE_SESSAO
from tcg_sniper.api.segredos import gerar_codigo, gerar_token, hash_segredo
from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import Dados, TipoAviso
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Usuario
from tcg_sniper.formatacao import mascarar_numero

log = logging.getLogger(__name__)

VALIDADE_CODIGO = timedelta(minutes=5)
MAX_TENTATIVAS = 5
LIMITE_POR_NUMERO = 3
JANELA_NUMERO = timedelta(minutes=15)
LIMITE_TOTAL = 20
JANELA_TOTAL = timedelta(hours=1)
LINHAS_CODIGO = ("Vale por 5 minutos.", "Não passe este código para ninguém.")
NAVEGADORES = (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari"))
SISTEMAS = (
    ("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"), ("Windows", "Windows"),
    ("Mac OS X", "macOS"), ("Linux", "Linux"),
)


class ResultadoPedido(StrEnum):
    ACEITO = "aceito"
    LIMITE_NUMERO = "limite_numero"
    LIMITE_TOTAL = "limite_total"


def resumir_aparelho(user_agent: str | None) -> str:
    """"Chrome · Windows": o bastante para a pessoa reconhecer a sessão, sem guardar o User-Agent inteiro."""
    texto = user_agent or ""
    navegador = next((nome for marca, nome in NAVEGADORES if marca in texto), "navegador desconhecido")
    sistema = next((nome for marca, nome in SISTEMAS if marca in texto), "sistema desconhecido")
    return f"{navegador} · {sistema}"


def emitir_codigo(s: Session, usuario_id: int, agora: datetime, segredo: str) -> str:
    """Novo código para o usuário (o anterior deixa de valer: só o último vale). Usado no login e no acesso de
    emergência (`tcg-sniper codigo-acesso`). No banco, só o HMAC com `segredo` (SEGREDO_API)."""
    codigo = gerar_codigo()
    repo_acesso.criar_codigo(s, usuario_id, hash_segredo(segredo, codigo), agora, VALIDADE_CODIGO)
    return codigo


def _recusar(s: Session, numero: str, numero_hash: str, resultado: ResultadoPedido, agora: datetime) -> ResultadoPedido:
    repo_acesso.registrar_pedido(s, numero_hash, resultado.value, agora)
    if resultado is ResultadoPedido.LIMITE_TOTAL:
        chave = "total"
        linhas = (f"Limite: {LIMITE_TOTAL} pedidos por hora no total", "Vários números")
    else:
        chave = f"numero:{numero_hash[:12]}"
        linhas = (f"Limite: {LIMITE_POR_NUMERO} códigos por número em 15 min", f"Número com final {numero[-2:]}")
    log.warning("pedido de código recusado (%s) para %s", resultado.value, mascarar_numero(numero))
    avisos.avisar(s, TipoAviso.SEGURANCA_LIMITE, chave, Dados(linhas=linhas), agora)
    return resultado


def pedir_codigo(s: Session, numero: str, agora: datetime, segredo: str) -> ResultadoPedido:
    """`numero` já normalizado. Dentro dos limites, registra o pedido e, se for de um usuário ativo, emite o código e
    enfileira a mensagem individual. Fora dos limites, registra, avisa o grupo admin e devolve o limite atingido.
    O chamador responde igual para número com ou sem cadastro."""
    repo_acesso.limpar_antigos(s, agora)
    numero_hash = hash_segredo(segredo, numero)
    if repo_acesso.contar_pedidos(s, agora - JANELA_TOTAL) >= LIMITE_TOTAL:
        return _recusar(s, numero, numero_hash, ResultadoPedido.LIMITE_TOTAL, agora)
    if repo_acesso.contar_pedidos(s, agora - JANELA_NUMERO, numero_hash) >= LIMITE_POR_NUMERO:
        return _recusar(s, numero, numero_hash, ResultadoPedido.LIMITE_NUMERO, agora)
    repo_acesso.registrar_pedido(s, numero_hash, ResultadoPedido.ACEITO.value, agora)
    usuario = repo_acesso.usuario_por_numero(s, numero)
    if usuario is None or not usuario.ativo:
        log.info("pedido de código para %s: sem usuário ativo, nada enviado", mascarar_numero(numero))
        return ResultadoPedido.ACEITO
    codigo = emitir_codigo(s, usuario.id, agora, segredo)
    dados = Dados(destaque=codigo, linhas=LINHAS_CODIGO)
    na_fila = avisos.avisar_individual(s, TipoAviso.CODIGO_ACESSO, usuario.numero, dados, agora, VALIDADE_CODIGO)
    situacao = "na fila do WhatsApp" if na_fila else "não enfileirado (aviso desligado ou erro)"
    log.info("código de acesso para %s: %s", mascarar_numero(numero), situacao)
    return ResultadoPedido.ACEITO


def entrar(
    s: Session, numero: str, codigo: str, aparelho: str, agora: datetime, segredo: str
) -> tuple[Usuario, str] | None:
    """Confere o último código do usuário (validade, uso, tentativas). Certo: marca usado, cria a sessão e devolve
    (usuário, token). Errado: conta a tentativa (o chamador grava antes de responder 401) e devolve None."""
    usuario = repo_acesso.usuario_por_numero(s, numero)
    if usuario is None or not usuario.ativo:
        return None
    atual = repo_acesso.ultimo_codigo(s, usuario.id)
    if atual is None or atual.usado_em is not None or atual.expira_em <= agora or atual.tentativas >= MAX_TENTATIVAS:
        log.info("entrada recusada para %s: sem código válido", mascarar_numero(numero))
        return None
    if not secrets.compare_digest(atual.hash_codigo, hash_segredo(segredo, codigo)):
        atual.tentativas += 1
        log.info("código errado para %s (tentativa %d de %d)", mascarar_numero(numero), atual.tentativas, MAX_TENTATIVAS)
        return None
    atual.usado_em = agora
    token = gerar_token()
    repo_acesso.criar_sessao(s, usuario.id, hash_segredo(segredo, token), aparelho, agora, VALIDADE_SESSAO)
    log.info("entrada de %s (usuário %d, %s)", mascarar_numero(numero), usuario.id, aparelho)
    return usuario, token
```

- [ ] **Step 5: Rotas**

Crie `src/tcg_sniper/api/rotas_auth.py`:

```python
"""Login: pedir código no WhatsApp, entrar com o código (cookie `sessao`), sair e quem sou eu."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from tcg_sniper.api import acesso
from tcg_sniper.api.dependencias import COOKIE, MAX_TOKEN, VALIDADE_SESSAO, Contexto, https, usuario_logado
from tcg_sniper.api.erros import MENSAGEM_NUMERO_INVALIDO, ErroApi
from tcg_sniper.api.permissoes import Permissao
from tcg_sniper.api.segredos import hash_segredo
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Papel
from tcg_sniper.formatacao import normalizar_numero

roteador = APIRouter(prefix="/api/auth", tags=["login"])

MENSAGEM_PEDIDO = "Se o número estiver cadastrado, o código chega no WhatsApp em instantes. Vale por 5 minutos."
MENSAGEM_CODIGO_INVALIDO = "Código errado, vencido ou já usado. Peça um novo."
MENSAGEM_LIMITE = "Muitos pedidos de código. Espere alguns minutos e tente de novo."


class PedidoCodigoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numero: str = Field(max_length=30)


class EntrarEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numero: str = Field(max_length=30)
    codigo: str = Field(pattern=r"^[0-9]{6}$")


class PedidoSaida(BaseModel):
    ok: bool
    mensagem: str


class EuSaida(BaseModel):
    id: int
    nome: str
    papel: Papel
    superadmin: bool  # o front mostra/esconde as ações sobre admins (a API confere do mesmo jeito)
    permissoes: list[Permissao]


class Ok(BaseModel):
    ok: bool = True


def _numero(texto: str) -> str:
    try:
        return normalizar_numero(texto)
    except ValueError:
        raise ErroApi(422, "numero_invalido", MENSAGEM_NUMERO_INVALIDO) from None


def _gravar_cookie(resposta: Response, request: Request, token: str) -> None:
    resposta.set_cookie(
        COOKIE, token, max_age=int(VALIDADE_SESSAO.total_seconds()), path="/", httponly=True, samesite="strict",
        secure=https(request),
    )


def _eu(usuario_id: int, nome: str, papel: Papel, superadmin: bool, permissoes: frozenset[Permissao]) -> EuSaida:
    return EuSaida(
        id=usuario_id, nome=nome, papel=papel, superadmin=superadmin,
        permissoes=[p for p in Permissao if p in permissoes],
    )


@roteador.post("/pedir-codigo")
def pedir_codigo(request: Request, entrada: PedidoCodigoEntrada) -> PedidoSaida:
    numero = _numero(entrada.numero)
    estado = request.app.state
    with estado.sessoes() as s, s.begin():
        resultado = acesso.pedir_codigo(s, numero, estado.relogio(), estado.segredo)
    if resultado is not acesso.ResultadoPedido.ACEITO:  # já gravado e avisado; agora responde
        raise ErroApi(429, "limite", MENSAGEM_LIMITE)
    return PedidoSaida(ok=True, mensagem=MENSAGEM_PEDIDO)


@roteador.post("/entrar")
def entrar(request: Request, resposta: Response, entrada: EntrarEntrada) -> EuSaida:
    numero = _numero(entrada.numero)
    estado = request.app.state
    aparelho = acesso.resumir_aparelho(request.headers.get("user-agent"))
    with estado.sessoes() as s, s.begin():
        resultado = acesso.entrar(s, numero, entrada.codigo, aparelho, estado.relogio(), estado.segredo)
        if resultado is not None:
            usuario, token = resultado
            usuario_id, nome, papel, superadmin = usuario.id, usuario.nome, usuario.papel, usuario.superadmin
    if resultado is None:  # a tentativa errada já foi gravada
        raise ErroApi(401, "codigo_invalido", MENSAGEM_CODIGO_INVALIDO)
    _gravar_cookie(resposta, request, token)
    return _eu(usuario_id, nome, papel, superadmin, estado.grade.efetivas(papel))


@roteador.post("/sair")
def sair(request: Request, resposta: Response) -> Ok:
    token = request.cookies.get(COOKIE, "")
    if token and len(token) <= MAX_TOKEN:
        estado = request.app.state
        with estado.sessoes() as s, s.begin():
            sessao = repo_acesso.sessao_por_hash(s, hash_segredo(estado.segredo, token))
            if sessao is not None:
                repo_acesso.encerrar_sessao(s, sessao, estado.relogio())
    resposta.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict", secure=https(request))
    return Ok()


@roteador.get("/eu")
def eu(request: Request, resposta: Response, contexto: Annotated[Contexto, Depends(usuario_logado)]) -> EuSaida:
    """Quem está logado e o que pode (o front monta menu e rotas com isso). Regrava o cookie: a sessão foi renovada."""
    _gravar_cookie(resposta, request, request.cookies[COOKIE])
    return _eu(contexto.usuario_id, contexto.nome, contexto.papel, contexto.superadmin, contexto.permissoes)
```

Em `src/tcg_sniper/api/app.py`: troque `from tcg_sniper.api import rotas_acessos` por `from tcg_sniper.api import rotas_acessos, rotas_auth` e, logo abaixo de `app.include_router(rotas_acessos.roteador)`, acrescente `app.include_router(rotas_auth.roteador)`.

- [ ] **Step 6: Rodar os testes da API**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t4 uv run pytest tests/api -q -p no:cacheprovider`
Expected: PASS (inclui `test_toda_rota_da_api_declara_permissao_ou_e_publica`: as quatro rotas novas estão em `PUBLICAS`).

- [ ] **Step 7: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t4 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde.

- [ ] **Step 8: Commit**

```bash
git add src/tcg_sniper/api/acesso.py src/tcg_sniper/api/rotas_auth.py src/tcg_sniper/api/app.py tests/api/test_auth.py
git commit -m "feat: whatsapp code login with limits and session cookie"
```

---

### Task 5: Usuários, sessões e avisos de segurança

**Files:**
- Create: `src/tcg_sniper/api/avisos_acesso.py`, `src/tcg_sniper/api/rotas_usuarios.py`
- Modify: `src/tcg_sniper/api/rotas_acessos.py` (aviso em cada mudança), `src/tcg_sniper/api/app.py` (um `include_router`)
- Test: `tests/api/test_usuarios.py` (novo)

**Interfaces:**
- Consumes: Task 1 (`repo_acesso.*`, `models.Usuario` (com `superadmin`), `Sessao`, `Papel`, `formatacao.normalizar_numero`, `mascarar_numero`); Task 2 (`avisos.servico.avisar`, `TipoAviso.SEGURANCA_USUARIO`, `CHAVE_GERAL`, `Dados`); Task 3 (`ErroApi`, `MENSAGEM_NUMERO_INVALIDO`, `exige`, `Contexto` (com `superadmin`), `Permissao`, `DEFINICOES`, `ROTULOS_PAPEL`, `rotas_acessos.salvar`/`aplicar_mudancas`; fixtures e `fakes_api`, inclusive `superadmin=True` em `logar`/`criar_usuario`).
- Produces:
  - `api.avisos_acesso`: `usuario_criado(s, usuario: Usuario, por: str, agora: datetime) -> None`; `papel_alterado(s, usuario: Usuario, antes: Papel, por: str, agora: datetime) -> None`; `ativo_alterado(s, usuario: Usuario, por: str, agora: datetime) -> None`; `permissao_alterada(s, papel: Papel, permissao: Permissao, permitido: bool, por: str, agora: datetime) -> None`; `superadmin_trocado(s, novo: Usuario, antigo: Usuario, por: str, agora: datetime) -> None` (usado pelo `trocar-superadmin` da Task 6). Todos mandam `SEGURANCA_USUARIO` (`titulo_extra` "usuário criado" | "papel alterado" | "usuário desativado" | "usuário reativado" | "permissão alterada" | "superadmin trocado"), sem número. No "usuário criado" do superadmin o papel sai "Admin (superadmin)".
  - Rotas (todas `gerir_usuarios`):
    - `GET /api/usuarios` → `{"usuarios": [UsuarioSaida]}`; `UsuarioSaida = {"id": int, "nome": str, "numero_mascarado": str, "papel": str, "superadmin": bool, "ativo": bool, "criado_em": str ISO, "sessoes_ativas": int}`.
    - `POST /api/usuarios` `{"nome": str (1–80), "numero": str, "papel": str}` → 201 `UsuarioSaida`; 409 `numero_ja_cadastrado`; 422 `numero_invalido`; 403 `so_superadmin` (papel admin por quem não é o superadmin). A API nunca cria superadmin.
    - `PATCH /api/usuarios/{id}` `{"nome"?, "papel"?, "ativo"?}` (pelo menos um) → 200 `UsuarioSaida`; 404 `nao_encontrado`; 403 `superadmin_protegido` (rebaixar ou desativar o superadmin, por qualquer um; `papel: "admin"`/`ativo: true` nele não contam); 403 `so_superadmin` (alvo admin, ou papel novo admin, por quem não é o superadmin). Desativar encerra todas as sessões na hora.
    - `GET /api/usuarios/{id}/sessoes` → `{"sessoes": [{"id", "aparelho", "criada_em", "ultimo_uso_em", "expira_em", "atual": bool}]}` (só as ativas).
    - `POST /api/sessoes/{id}/encerrar` → 200 `{"ok": true}` (já encerrada: 200 também); 404; as próprias sessões sempre podem; de outro: 403 `superadmin_protegido` (dono é o superadmin), 403 `so_superadmin` (dono é admin e quem pede não é o superadmin).

- [ ] **Step 1: Banco da lane**

Run: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_t5`

- [ ] **Step 2: Testes (falham)**

Crie `tests/api/test_usuarios.py`:

```python
import pytest
from sqlalchemy import select

from fakes_api import T0, criar_sessao, criar_usuario, mensagens
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Papel, Sessao, Usuario


def test_listar_exige_gerir_usuarios(cliente, logar):
    logar(Papel.GRUPO)
    r = cliente.get("/api/usuarios")
    assert r.status_code == 403 and r.json()["erro"] == "sem_permissao"


def test_operador_por_padrao_nao_gere_usuarios(cliente, logar):
    logar(Papel.OPERADOR)
    assert cliente.get("/api/usuarios").status_code == 403


def test_admin_lista_com_numero_mascarado(cliente, logar, sessoes):
    logar(Papel.ADMIN, superadmin=True)
    criar_usuario(sessoes, Papel.GRUPO)
    r = cliente.get("/api/usuarios")
    assert r.status_code == 200 and "900000002" not in r.text and "900000001" not in r.text
    por_papel = {u["papel"]: u for u in r.json()["usuarios"]}
    assert por_papel["grupo"]["numero_mascarado"] == "+55 11 9****-**02"
    assert (por_papel["grupo"]["ativo"], por_papel["grupo"]["sessoes_ativas"]) == (True, 0)
    assert (por_papel["grupo"]["superadmin"], por_papel["admin"]["superadmin"]) == (False, True)
    assert por_papel["admin"]["sessoes_ativas"] == 1


def test_criar_usuario_avisa_sem_numero(cliente, logar, sessoes):
    logar(Papel.ADMIN, nome="Pessoa Admin")
    r = cliente.post("/api/usuarios", json={"nome": " Pessoa Nova ", "numero": "(11) 90000-0005", "papel": "operador"})
    assert r.status_code == 201
    assert (r.json()["nome"], r.json()["numero_mascarado"], r.json()["papel"]) == (
        "Pessoa Nova", "+55 11 9****-**05", "operador"
    )
    with sessoes() as s:
        assert repo_acesso.usuario_por_numero(s, "+5511900000005").papel is Papel.OPERADOR
    [aviso] = mensagens(sessoes, "admin")
    assert aviso.startswith("🟡 *Segurança · acesso alterado · usuário criado*")
    assert "• Usuário: Pessoa Nova" in aviso and "• Papel: Operador" in aviso and "• Por: Pessoa Admin" in aviso
    assert "900000005" not in aviso


def test_numero_duplicado_em_outro_formato_409(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    criar_usuario(sessoes, Papel.GRUPO)  # +5511900000002
    r = cliente.post("/api/usuarios", json={"nome": "Outra", "numero": "+55 11 90000 0002", "papel": "grupo"})
    assert r.status_code == 409 and r.json()["erro"] == "numero_ja_cadastrado"


def test_numero_ou_nome_invalido_422(cliente, logar):
    logar(Papel.ADMIN)
    r = cliente.post("/api/usuarios", json={"nome": "X", "numero": "123", "papel": "grupo"})
    assert r.status_code == 422 and r.json()["erro"] == "numero_invalido"
    r = cliente.post("/api/usuarios", json={"nome": "   ", "numero": "11 90000-0007", "papel": "grupo"})
    assert r.status_code == 422 and r.json()["erro"] == "validacao"


def _recusado(resposta, erro):
    return resposta.status_code == 403 and resposta.json()["erro"] == erro


@pytest.mark.parametrize("papel", [Papel.ADMIN, Papel.OPERADOR])
def test_quem_nao_e_superadmin_nao_cria_nem_mexe_em_admin(cliente, logar, sessoes, papel):
    """Admin comum e operador que ganhou `gerir_usuarios` na grade: só operador e grupo."""
    logar(papel, numero="+5511900000006")
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.OPERADOR, "gerir_usuarios", True)
    admin_id = criar_usuario(sessoes, Papel.ADMIN, nome="Outro Admin", numero="+5511900000004")
    grupo_id = criar_usuario(sessoes, Papel.GRUPO)
    novo_admin = {"nome": "Intrusa", "numero": "11 90000-0008", "papel": "admin"}
    assert _recusado(cliente.post("/api/usuarios", json=novo_admin), "so_superadmin")
    assert _recusado(cliente.patch(f"/api/usuarios/{grupo_id}", json={"papel": "admin"}), "so_superadmin")
    for mudanca in ({"nome": "Outro nome"}, {"papel": "operador"}, {"ativo": False}):
        assert _recusado(cliente.patch(f"/api/usuarios/{admin_id}", json=mudanca), "so_superadmin")
    sessao_admin = criar_sessao(sessoes, admin_id, "token-do-admin")
    assert _recusado(cliente.post(f"/api/sessoes/{sessao_admin}/encerrar"), "so_superadmin")
    assert cliente.patch(f"/api/usuarios/{grupo_id}", json={"papel": "operador"}).status_code == 200
    assert cliente.patch(f"/api/usuarios/{grupo_id}", json={"ativo": False}).status_code == 200
    with sessoes() as s:
        assert s.get(Usuario, admin_id).papel is Papel.ADMIN and s.get(Usuario, admin_id).ativo


def test_superadmin_gere_admins(cliente, logar, sessoes):
    logar(Papel.ADMIN, nome="Pessoa Superadmin", superadmin=True)
    r = cliente.post("/api/usuarios", json={"nome": "Admin Novo", "numero": "11 90000-0004", "papel": "admin"})
    assert r.status_code == 201 and (r.json()["papel"], r.json()["superadmin"]) == ("admin", False)
    admin_id = r.json()["id"]
    sessao_admin = criar_sessao(sessoes, admin_id, "token-do-admin")
    assert cliente.post(f"/api/sessoes/{sessao_admin}/encerrar").json() == {"ok": True}
    assert cliente.patch(f"/api/usuarios/{admin_id}", json={"nome": "Admin Renomeado"}).status_code == 200
    assert cliente.patch(f"/api/usuarios/{admin_id}", json={"papel": "operador"}).json()["papel"] == "operador"
    assert cliente.patch(f"/api/usuarios/{admin_id}", json={"papel": "admin"}).json()["papel"] == "admin"
    assert cliente.patch(f"/api/usuarios/{admin_id}", json={"ativo": False}).json()["ativo"] is False


def test_superadmin_nunca_rebaixado_desativado_nem_encerrado(cliente, logar, sessoes):
    """Nem por um admin comum nem por ele mesmo; só ele encerra as próprias sessões."""
    super_id = logar(Papel.ADMIN, nome="Pessoa Superadmin", superadmin=True, token="token-super")
    sessao_super = criar_sessao(sessoes, super_id, "token-super-celular")
    logar(Papel.ADMIN, nome="Admin Comum", numero="+5511900000004")
    for mudanca in ({"ativo": False}, {"papel": "operador"}, {"papel": "grupo", "ativo": False}):
        assert _recusado(cliente.patch(f"/api/usuarios/{super_id}", json=mudanca), "superadmin_protegido")
    assert _recusado(cliente.patch(f"/api/usuarios/{super_id}", json={"nome": "X"}), "so_superadmin")
    assert _recusado(cliente.post(f"/api/sessoes/{sessao_super}/encerrar"), "superadmin_protegido")
    cliente.cookies.set("sessao", "token-super")  # agora o próprio superadmin
    for mudanca in ({"ativo": False}, {"papel": "operador"}):
        assert _recusado(cliente.patch(f"/api/usuarios/{super_id}", json=mudanca), "superadmin_protegido")
    r = cliente.patch(f"/api/usuarios/{super_id}", json={"nome": "Dono", "papel": "admin", "ativo": True})
    assert r.status_code == 200 and (r.json()["nome"], r.json()["superadmin"]) == ("Dono", True)
    assert cliente.post(f"/api/sessoes/{sessao_super}/encerrar").json() == {"ok": True}
    with sessoes() as s:
        dono = s.get(Usuario, super_id)
        assert (dono.papel, dono.ativo, dono.superadmin) == (Papel.ADMIN, True, True)


def test_qualquer_um_encerra_as_proprias_sessoes(cliente, logar, sessoes):
    admin_id = logar(Papel.ADMIN)  # admin comum
    outra = criar_sessao(sessoes, admin_id, "token-do-celular")
    assert cliente.post(f"/api/sessoes/{outra}/encerrar").json() == {"ok": True}


def test_papel_alterado_avisa(cliente, logar, sessoes):
    logar(Papel.ADMIN, nome="Pessoa Admin")
    grupo_id = criar_usuario(sessoes, Papel.GRUPO, nome="Pessoa Grupo")
    r = cliente.patch(f"/api/usuarios/{grupo_id}", json={"papel": "operador"})
    assert r.status_code == 200 and r.json()["papel"] == "operador"
    [aviso] = mensagens(sessoes, "admin")
    assert "papel alterado" in aviso and "• Papel: Grupo → Operador" in aviso


def test_mudar_so_o_nome_nao_avisa(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    grupo_id = criar_usuario(sessoes, Papel.GRUPO)
    r = cliente.patch(f"/api/usuarios/{grupo_id}", json={"nome": "Nome Novo", "papel": "grupo", "ativo": True})
    assert r.status_code == 200 and r.json()["nome"] == "Nome Novo"
    assert mensagens(sessoes, "admin") == []


def test_desativar_encerra_as_sessoes_na_hora_e_reativar_avisa(cliente, logar, sessoes):
    logar(Papel.ADMIN)
    grupo_id = criar_usuario(sessoes, Papel.GRUPO)
    criar_sessao(sessoes, grupo_id, "t1")
    criar_sessao(sessoes, grupo_id, "t2")
    r = cliente.patch(f"/api/usuarios/{grupo_id}", json={"ativo": False})
    assert r.status_code == 200 and (r.json()["ativo"], r.json()["sessoes_ativas"]) == (False, 0)
    with sessoes() as s:
        assert [x.encerrada_em for x in s.scalars(select(Sessao).where(Sessao.usuario_id == grupo_id))] == [T0, T0]
    assert cliente.patch(f"/api/usuarios/{grupo_id}", json={"ativo": True}).json()["ativo"] is True
    avisos = mensagens(sessoes, "admin")
    assert "usuário desativado" in avisos[0] and "usuário reativado" in avisos[1]


def test_patch_vazio_ou_usuario_inexistente(cliente, logar):
    admin_id = logar(Papel.ADMIN)
    assert cliente.patch(f"/api/usuarios/{admin_id}", json={}).json()["erro"] == "validacao"
    for usuario_id in (999_999, 2**31):
        r = cliente.patch(f"/api/usuarios/{usuario_id}", json={"nome": "X"})
        assert r.status_code == 404 and r.json()["erro"] == "nao_encontrado"
        assert cliente.get(f"/api/usuarios/{usuario_id}/sessoes").status_code == 404
    assert cliente.post("/api/sessoes/999999/encerrar").status_code == 404


def test_sessoes_lista_e_encerra(cliente, logar, sessoes):
    admin_id = logar(Papel.ADMIN)
    grupo_id = criar_usuario(sessoes, Papel.GRUPO)
    sessao_id = criar_sessao(sessoes, grupo_id, "t-grupo")
    r = cliente.get(f"/api/usuarios/{grupo_id}/sessoes")
    [sessao] = r.json()["sessoes"]
    assert (sessao["id"], sessao["aparelho"], sessao["atual"]) == (sessao_id, "Chrome · Windows", False)
    assert [x["atual"] for x in cliente.get(f"/api/usuarios/{admin_id}/sessoes").json()["sessoes"]] == [True]
    assert cliente.post(f"/api/sessoes/{sessao_id}/encerrar").json() == {"ok": True}
    assert cliente.post(f"/api/sessoes/{sessao_id}/encerrar").json() == {"ok": True}
    assert cliente.get(f"/api/usuarios/{grupo_id}/sessoes").json()["sessoes"] == []


def test_permissao_alterada_avisa_e_valor_igual_nao(cliente, logar, sessoes):
    logar(Papel.ADMIN, nome="Pessoa Admin")
    corpo = {"mudancas": [{"papel": "grupo", "permissao": "ver_area_gestao", "permitido": True}]}
    assert cliente.put("/api/acessos", json=corpo).status_code == 200
    assert cliente.put("/api/acessos", json=corpo).status_code == 200  # igual ao atual: não avisa de novo
    [aviso] = mensagens(sessoes, "admin")
    assert aviso.startswith("🟡 *Segurança · acesso alterado · permissão alterada*")
    for linha in ("• Papel: Grupo", "• Permissão: Entrar na área de gestão", "• Agora: permitido", "• Por: Pessoa Admin"):
        assert linha in aviso, linha
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t5 uv run pytest tests/api/test_usuarios.py -q -p no:cacheprovider`
Expected: FAIL (404 em `/api/usuarios`; sem aviso no `PUT /api/acessos`).

- [ ] **Step 4: Avisos de segurança**

Crie `src/tcg_sniper/api/avisos_acesso.py`:

```python
"""Avisos `SEGURANCA_USUARIO` para o grupo admin: quem mudou o quê. Nunca o número da pessoa."""

from datetime import datetime

from sqlalchemy.orm import Session

from tcg_sniper.api.permissoes import DEFINICOES, ROTULOS_PAPEL, Permissao
from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.db.models import Papel, Usuario


def _avisar(s: Session, titulo_extra: str, linhas: tuple[str, ...], agora: datetime) -> None:
    avisos.avisar(s, TipoAviso.SEGURANCA_USUARIO, CHAVE_GERAL, Dados(titulo_extra=titulo_extra, linhas=linhas), agora)


def usuario_criado(s: Session, usuario: Usuario, por: str, agora: datetime) -> None:
    papel = ROTULOS_PAPEL[usuario.papel] + (" (superadmin)" if usuario.superadmin else "")
    _avisar(s, "usuário criado", (f"Usuário: {usuario.nome}", f"Papel: {papel}", f"Por: {por}"), agora)


def superadmin_trocado(s: Session, novo: Usuario, antigo: Usuario, por: str, agora: datetime) -> None:
    linhas = (f"Superadmin agora: {novo.nome}", f"Antes: {antigo.nome} (continua admin)", f"Por: {por}")
    _avisar(s, "superadmin trocado", linhas, agora)


def papel_alterado(s: Session, usuario: Usuario, antes: Papel, por: str, agora: datetime) -> None:
    papel = f"Papel: {ROTULOS_PAPEL[antes]} → {ROTULOS_PAPEL[usuario.papel]}"
    _avisar(s, "papel alterado", (f"Usuário: {usuario.nome}", papel, f"Por: {por}"), agora)


def ativo_alterado(s: Session, usuario: Usuario, por: str, agora: datetime) -> None:
    if usuario.ativo:
        _avisar(s, "usuário reativado", (f"Usuário: {usuario.nome}", f"Por: {por}"), agora)
    else:
        linhas = (f"Usuário: {usuario.nome}", "Sessões encerradas na hora", f"Por: {por}")
        _avisar(s, "usuário desativado", linhas, agora)


def permissao_alterada(s: Session, papel: Papel, permissao: Permissao, permitido: bool, por: str, agora: datetime) -> None:
    linhas = (
        f"Papel: {ROTULOS_PAPEL[papel]}",
        f"Permissão: {DEFINICOES[permissao].rotulo}",
        f"Agora: {'permitido' if permitido else 'negado'}",
        f"Por: {por}",
    )
    _avisar(s, "permissão alterada", linhas, agora)
```

- [ ] **Step 5: Rotas de usuários e sessões**

Crie `src/tcg_sniper/api/rotas_usuarios.py`:

```python
"""Gestão → Usuários: listar, criar, editar (nome, papel, ativo) e as sessões de cada um. Exige `gerir_usuarios`.
Só o superadmin cria, edita, rebaixa ou desativa admins e encerra sessões de admins (403 `so_superadmin`); o
superadmin nunca é rebaixado, desativado nem tem sessões encerradas por ninguém (403 `superadmin_protegido`; só ele
encerra as dele). Criar e trocar o superadmin: só pelos comandos locais. O número sai sempre mascarado."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from tcg_sniper.api import avisos_acesso
from tcg_sniper.api.dependencias import Contexto, exige
from tcg_sniper.api.erros import MENSAGEM_NUMERO_INVALIDO, ErroApi
from tcg_sniper.api.permissoes import Permissao
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Papel, Sessao, Usuario
from tcg_sniper.formatacao import mascarar_numero, normalizar_numero

roteador = APIRouter(prefix="/api", tags=["usuarios"])
GerirUsuarios = Annotated[Contexto, Depends(exige(Permissao.GERIR_USUARIOS))]
MAX_ID = 2**31 - 1  # fora do integer do Postgres: 404, nunca 500


def _nome_limpo(valor: str | None) -> str | None:
    if valor is None:
        return None
    valor = valor.strip()
    if not valor:
        raise ValueError("nome vazio")
    return valor


class UsuarioSaida(BaseModel):
    id: int
    nome: str
    numero_mascarado: str
    papel: Papel
    superadmin: bool
    ativo: bool
    criado_em: datetime
    sessoes_ativas: int


class UsuariosSaida(BaseModel):
    usuarios: list[UsuarioSaida]


class NovoUsuario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nome: str = Field(min_length=1, max_length=80)
    numero: str = Field(max_length=30)
    papel: Papel

    @field_validator("nome")
    @classmethod
    def _limpar_nome(cls, valor: str | None) -> str | None:
        return _nome_limpo(valor)


class EdicaoUsuario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nome: str | None = Field(default=None, min_length=1, max_length=80)
    papel: Papel | None = None
    ativo: bool | None = None

    @field_validator("nome")
    @classmethod
    def _limpar_nome(cls, valor: str | None) -> str | None:
        return _nome_limpo(valor)

    @model_validator(mode="after")
    def _algo_a_mudar(self) -> "EdicaoUsuario":
        if self.nome is None and self.papel is None and self.ativo is None:
            raise ValueError("nada a mudar")
        return self


class SessaoSaida(BaseModel):
    id: int
    aparelho: str
    criada_em: datetime
    ultimo_uso_em: datetime
    expira_em: datetime
    atual: bool


class SessoesSaida(BaseModel):
    sessoes: list[SessaoSaida]


class Ok(BaseModel):
    ok: bool = True


def _saida(usuario: Usuario, sessoes_ativas: int) -> UsuarioSaida:
    return UsuarioSaida(
        id=usuario.id, nome=usuario.nome, numero_mascarado=mascarar_numero(usuario.numero), papel=usuario.papel,
        superadmin=usuario.superadmin, ativo=usuario.ativo, criado_em=usuario.criado_em, sessoes_ativas=sessoes_ativas,
    )


def _obter(s: Session, usuario_id: int) -> Usuario:
    usuario = s.get(Usuario, usuario_id) if 1 <= usuario_id <= MAX_ID else None
    if usuario is None:
        raise ErroApi(404, "nao_encontrado", "Usuário não encontrado.")
    return usuario


def _so_superadmin(contexto: Contexto, *papeis: Papel | None) -> None:
    """Admin envolvido (alvo admin ou papel novo admin): só o superadmin."""
    if not contexto.superadmin and Papel.ADMIN in papeis:
        raise ErroApi(403, "so_superadmin", "Só o superadmin cria, edita, rebaixa ou desativa admins.")


def _protegido() -> ErroApi:
    return ErroApi(403, "superadmin_protegido", "O superadmin não pode ser rebaixado, desativado nem encerrado.")


@roteador.get("/usuarios")
def listar(request: Request, _contexto: GerirUsuarios) -> UsuariosSaida:
    estado = request.app.state
    with estado.sessoes() as s:
        contagem = repo_acesso.contar_sessoes_ativas(s, estado.relogio())
        return UsuariosSaida(usuarios=[_saida(u, contagem.get(u.id, 0)) for u in repo_acesso.listar_usuarios(s)])


@roteador.post("/usuarios", status_code=201)
def criar(request: Request, entrada: NovoUsuario, contexto: GerirUsuarios) -> UsuarioSaida:
    _so_superadmin(contexto, entrada.papel)
    try:
        numero = normalizar_numero(entrada.numero)
    except ValueError:
        raise ErroApi(422, "numero_invalido", MENSAGEM_NUMERO_INVALIDO) from None
    estado = request.app.state
    agora = estado.relogio()
    with estado.sessoes() as s, s.begin():
        try:
            usuario = repo_acesso.criar_usuario(s, entrada.nome, numero, entrada.papel, agora)
        except repo_acesso.NumeroJaCadastrado:
            raise ErroApi(409, "numero_ja_cadastrado", "Já existe um usuário com este número.") from None
        avisos_acesso.usuario_criado(s, usuario, contexto.nome, agora)
        return _saida(usuario, 0)


@roteador.patch("/usuarios/{usuario_id}")
def editar(request: Request, usuario_id: int, entrada: EdicaoUsuario, contexto: GerirUsuarios) -> UsuarioSaida:
    estado = request.app.state
    agora = estado.relogio()
    with estado.sessoes() as s, s.begin():
        usuario = _obter(s, usuario_id)
        rebaixa = entrada.papel is not None and entrada.papel is not Papel.ADMIN
        if usuario.superadmin and (rebaixa or entrada.ativo is False):
            raise _protegido()  # nem ele mesmo; papel admin e ativo true (formulário inteiro) passam
        _so_superadmin(contexto, usuario.papel, entrada.papel)
        if entrada.nome is not None:
            usuario.nome = entrada.nome
        if entrada.papel is not None and entrada.papel is not usuario.papel:
            antes = usuario.papel
            usuario.papel = entrada.papel
            avisos_acesso.papel_alterado(s, usuario, antes, contexto.nome, agora)
        if entrada.ativo is not None and entrada.ativo != usuario.ativo:
            usuario.ativo = entrada.ativo
            if not usuario.ativo:
                repo_acesso.encerrar_sessoes_do_usuario(s, usuario.id, agora)
            avisos_acesso.ativo_alterado(s, usuario, contexto.nome, agora)
        s.flush()
        return _saida(usuario, repo_acesso.contar_sessoes_ativas(s, agora).get(usuario.id, 0))


@roteador.get("/usuarios/{usuario_id}/sessoes")
def sessoes_do_usuario(request: Request, usuario_id: int, contexto: GerirUsuarios) -> SessoesSaida:
    estado = request.app.state
    with estado.sessoes() as s:
        usuario = _obter(s, usuario_id)
        ativas = repo_acesso.sessoes_ativas(s, usuario.id, estado.relogio())
        return SessoesSaida(
            sessoes=[
                SessaoSaida(
                    id=x.id, aparelho=x.aparelho, criada_em=x.criada_em, ultimo_uso_em=x.ultimo_uso_em,
                    expira_em=x.expira_em, atual=x.id == contexto.sessao_id,
                )
                for x in ativas
            ]
        )


@roteador.post("/sessoes/{sessao_id}/encerrar")
def encerrar(request: Request, sessao_id: int, contexto: GerirUsuarios) -> Ok:
    estado = request.app.state
    with estado.sessoes() as s, s.begin():
        sessao = s.get(Sessao, sessao_id) if 1 <= sessao_id <= MAX_ID else None
        if sessao is None:
            raise ErroApi(404, "nao_encontrado", "Sessão não encontrada.")
        if sessao.usuario_id != contexto.usuario_id:  # as próprias sessões, qualquer um encerra
            dono = s.get(Usuario, sessao.usuario_id)
            if dono.superadmin:
                raise _protegido()
            _so_superadmin(contexto, dono.papel)
        repo_acesso.encerrar_sessao(s, sessao, estado.relogio())
    return Ok()
```

Em `src/tcg_sniper/api/app.py`: `from tcg_sniper.api import rotas_acessos, rotas_auth, rotas_usuarios` e, abaixo dos outros, `app.include_router(rotas_usuarios.roteador)`. (Se a Task 4 ainda não estiver no ramo, o import fica `rotas_acessos, rotas_usuarios`; na integração, manter os três.)

Em `src/tcg_sniper/api/rotas_acessos.py`: acrescente `from tcg_sniper.api import avisos_acesso` e troque as duas linhas

```python
        feitas = aplicar_mudancas(s, calcular_grade(repo_acesso.grade_salva(s)), entrada.mudancas)
        del feitas  # Task 5: aviso SEGURANCA_USUARIO de cada mudança feita, nesta mesma transação
```

por

```python
        agora = estado.relogio()
        for m in aplicar_mudancas(s, calcular_grade(repo_acesso.grade_salva(s)), entrada.mudancas):
            avisos_acesso.permissao_alterada(s, m.papel, m.permissao, m.permitido, contexto.nome, agora)
```

- [ ] **Step 6: Rodar os testes da API**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t5 uv run pytest tests/api -q -p no:cacheprovider`
Expected: PASS (as rotas novas declaram `gerir_usuarios`, então `test_toda_rota_da_api_declara_permissao_ou_e_publica` continua verde).

- [ ] **Step 7: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t5 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde.

- [ ] **Step 8: Commit**

```bash
git add src/tcg_sniper/api tests/api/test_usuarios.py
git commit -m "feat: user and session management with security alerts"
```

---

### Task 6: CLI (`api`, `codigo-acesso`, `criar-superadmin`, `trocar-superadmin`)

**Files:**
- Modify: `src/tcg_sniper/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 3 (`api.app.criar_app(sessoes, config)`, `api.segredos.hash_segredo(segredo, texto)`, `exigir_segredo(config)`, `SegredoAusente`; `fakes_api.SEGREDO_TESTE`); Task 4 (`api.acesso.emitir_codigo(s, usuario_id, agora, segredo) -> str`); Task 5 (`api.avisos_acesso.usuario_criado(s, usuario, por, agora)`, `superadmin_trocado(s, novo, antigo, por, agora)`); Task 1 (`repo_acesso.*` — `criar_superadmin`, `trocar_superadmin`, `superadmin_atual`, `SuperadminJaExiste`, `NumeroJaCadastrado` —, `formatacao.normalizar_numero`, `mascarar_numero`).
- Produces:
  - `tcg-sniper api [--host 127.0.0.1] [--porta 8100]` → confere `exigir_segredo(config)` (`SystemExit` com a mensagem de `SegredoAusente`, antes de qualquer outra coisa) e `uvicorn.run(criar_app(sessoes, config), host=..., port=...)`.
  - `tcg-sniper codigo-acesso <numero>` → exige `SEGREDO_API` como a `api` (o hash do código tem de ser o mesmo que a API confere); imprime `Código para <nome> (<número mascarado>): <6 dígitos>` e `Vale por 5 minutos, uma vez. Digite na tela Entrar.`; `SystemExit` com a mensagem de `SegredoAusente`, "número inválido ..." ou "nenhum usuário ativo com esse número". Não manda WhatsApp.
  - `tcg-sniper criar-superadmin <nome> <numero>` → imprime `Superadmin <nome> criado (<número mascarado>). ...`; `SystemExit` com "já existe um superadmin; para trocar use tcg-sniper trocar-superadmin <número>", "este número já é de um usuário; para torná-lo superadmin use tcg-sniper trocar-superadmin <número>", "nome vazio" ou "número inválido ...". Avisa `SEGURANCA_USUARIO` "usuário criado" (papel "Admin (superadmin)") com "Por: terminal". Não exige `SEGREDO_API` (não cria código nem sessão).
  - `tcg-sniper trocar-superadmin <numero>` → passa a marca para o usuário ativo com esse número (vira admin; o antigo continua admin comum); imprime `Superadmin agora é <nome> (<número mascarado>); <antigo> continua admin.`; `SystemExit` com "número inválido ...", "nenhum usuário ativo com esse número", "ainda não há superadmin; use tcg-sniper criar-superadmin <nome> <número>" ou "este usuário já é o superadmin". Avisa `SEGURANCA_USUARIO` "superadmin trocado" com "Por: terminal". Não exige `SEGREDO_API`.

- [ ] **Step 1: Banco da lane**

Run: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_t6`

- [ ] **Step 2: Testes (falham)**

Em `tests/test_cli.py`, acrescente no topo `import re` e `from sqlalchemy import select`, e no fim:

```python
@pytest.fixture
def segredo(monkeypatch):
    """SEGREDO_API falsa e fixa (sobrepõe a do .env de quem roda o teste)."""
    from fakes_api import SEGREDO_TESTE

    monkeypatch.setenv("SEGREDO_API", SEGREDO_TESTE)
    return SEGREDO_TESTE


@pytest.fixture
def banco(monkeypatch, sessoes, segredo):
    """O CLI usa as sessões do teste (tudo é desfeito no fim)."""
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: sessoes)
    return sessoes


def test_api_sobe_o_uvicorn_so_no_localhost_por_padrao(monkeypatch, segredo):
    import uvicorn

    from tcg_sniper.api import app as modulo_app

    chamadas = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: chamadas.append((app, kw)))
    monkeypatch.setattr(modulo_app, "criar_app", lambda sessoes, config: "app")
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    cli.main(["api"])
    cli.main(["api", "--host", "0.0.0.0", "--porta", "8101"])
    assert chamadas == [("app", {"host": "127.0.0.1", "port": 8100}), ("app", {"host": "0.0.0.0", "port": 8101})]


@pytest.mark.parametrize("valor", ["", "trocar-este-segredo", "curto"])
def test_api_recusa_subir_sem_segredo(monkeypatch, valor):
    import uvicorn

    chamadas = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: chamadas.append(app))
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    monkeypatch.setenv("SEGREDO_API", valor)
    with pytest.raises(SystemExit, match="SEGREDO_API"):
        cli.main(["api"])
    with pytest.raises(SystemExit, match="SEGREDO_API"):
        cli.main(["codigo-acesso", "11 90000-0002"])
    assert chamadas == []


def test_criar_superadmin_uma_vez_so(banco, capsys):
    from tcg_sniper.db import repositorio_acesso as repo_acesso
    from tcg_sniper.db.models import MensagemSaida, Papel

    cli.main(["criar-superadmin", "Pessoa Superadmin", "(11) 90000-0001"])
    saida = capsys.readouterr().out
    assert "Superadmin Pessoa Superadmin criado (+55 11 9****-**01)" in saida and "900000001" not in saida
    with banco() as s:
        dono = repo_acesso.usuario_por_numero(s, "+5511900000001")
        assert (dono.papel, dono.ativo, dono.superadmin) == (Papel.ADMIN, True, True)
        [aviso] = s.scalars(select(MensagemSaida.texto).where(MensagemSaida.destino == "admin")).all()
        assert "usuário criado" in aviso and "• Papel: Admin (superadmin)" in aviso
        assert "• Por: terminal" in aviso and "900000001" not in aviso
    with pytest.raises(SystemExit, match="já existe um superadmin"):
        cli.main(["criar-superadmin", "Outra Pessoa", "11 90000-0004"])
    with pytest.raises(SystemExit, match="número inválido"):
        cli.main(["criar-superadmin", "Mais Uma", "123"])
    with pytest.raises(SystemExit, match="nome vazio"):
        cli.main(["criar-superadmin", "  ", "11 90000-0004"])


def test_criar_superadmin_com_numero_de_outro_usuario(banco):
    from tcg_sniper.db import repositorio_acesso as repo_acesso
    from tcg_sniper.db.models import Papel
    from tcg_sniper.db.repositorio import agora_utc

    with banco() as s, s.begin():
        repo_acesso.criar_usuario(s, "Pessoa Grupo", "+5511900000002", Papel.GRUPO, agora_utc())
    with pytest.raises(SystemExit, match="trocar-superadmin"):
        cli.main(["criar-superadmin", "Pessoa Grupo", "11 90000-0002"])
    with banco() as s:
        assert repo_acesso.superadmin_atual(s) is None


def test_trocar_superadmin(banco, capsys):
    from tcg_sniper.db import repositorio_acesso as repo_acesso
    from tcg_sniper.db.models import MensagemSaida, Papel
    from tcg_sniper.db.repositorio import agora_utc

    with banco() as s, s.begin():
        repo_acesso.criar_usuario(s, "Pessoa Grupo", "+5511900000002", Papel.GRUPO, agora_utc())
        repo_acesso.criar_usuario(s, "Pessoa Inativa", "+5511900000005", Papel.ADMIN, agora_utc()).ativo = False
    with pytest.raises(SystemExit, match="ainda não há superadmin"):
        cli.main(["trocar-superadmin", "11 90000-0002"])
    cli.main(["criar-superadmin", "Pessoa Superadmin", "11 90000-0001"])
    with pytest.raises(SystemExit, match="nenhum usuário ativo"):
        cli.main(["trocar-superadmin", "11 90000-0005"])
    with pytest.raises(SystemExit, match="nenhum usuário ativo"):
        cli.main(["trocar-superadmin", "11 90000-0009"])
    with pytest.raises(SystemExit, match="já é o superadmin"):
        cli.main(["trocar-superadmin", "11 90000-0001"])
    capsys.readouterr()
    cli.main(["trocar-superadmin", "(11) 90000-0002"])
    saida = capsys.readouterr().out
    assert "Superadmin agora é Pessoa Grupo (+55 11 9****-**02); Pessoa Superadmin continua admin." in saida
    assert "900000002" not in saida
    with banco() as s:
        novo = repo_acesso.usuario_por_numero(s, "+5511900000002")
        antigo = repo_acesso.usuario_por_numero(s, "+5511900000001")
        assert (novo.papel, novo.superadmin) == (Papel.ADMIN, True)
        assert (antigo.papel, antigo.ativo, antigo.superadmin) == (Papel.ADMIN, True, False)
        textos = s.scalars(select(MensagemSaida.texto).where(MensagemSaida.destino == "admin")).all()
        assert any("superadmin trocado" in t and "• Por: terminal" in t for t in textos)


def test_codigo_de_emergencia(banco, segredo, capsys):
    from tcg_sniper.api.segredos import hash_segredo
    from tcg_sniper.db import repositorio_acesso as repo_acesso
    from tcg_sniper.db.models import MensagemSaida, Papel
    from tcg_sniper.db.repositorio import agora_utc

    with banco() as s, s.begin():
        repo_acesso.criar_usuario(s, "Pessoa Grupo", "+5511900000002", Papel.GRUPO, agora_utc())
    cli.main(["codigo-acesso", "11 90000-0002"])
    saida = capsys.readouterr().out
    codigo = re.search(r"\): (\d{6})\n", saida).group(1)
    assert "Código para Pessoa Grupo (+55 11 9****-**02)" in saida and "900000002" not in saida
    with banco() as s:
        usuario = repo_acesso.usuario_por_numero(s, "+5511900000002")
        atual = repo_acesso.ultimo_codigo(s, usuario.id)
        assert atual.hash_codigo == hash_segredo(segredo, codigo) and atual.usado_em is None
        assert s.scalars(select(MensagemSaida)).all() == []  # não manda WhatsApp


def test_codigo_de_emergencia_recusa(banco):
    with pytest.raises(SystemExit, match="número inválido"):
        cli.main(["codigo-acesso", "abc"])
    with pytest.raises(SystemExit, match="nenhum usuário ativo"):
        cli.main(["codigo-acesso", "11 90000-0009"])
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t6 uv run pytest tests/test_cli.py -q -p no:cacheprovider`
Expected: FAIL (`invalid choice: 'api'`).

- [ ] **Step 4: Subcomandos**

Em `src/tcg_sniper/cli.py`, logo depois de `admin.add_argument("--porta", type=int, default=8000)`:

```python
    api_p = sub.add_parser("api", help="inicia a API do front novo (JSON, login pelo WhatsApp)")
    api_p.add_argument("--host", default="127.0.0.1", help="no container: 0.0.0.0 (o compose publica só no 127.0.0.1)")
    api_p.add_argument("--porta", type=int, default=8100)
    codigo_p = sub.add_parser(
        "codigo-acesso", help="acesso de emergência: mostra no terminal um código válido (5 min) para o usuário"
    )
    codigo_p.add_argument("numero", help='número de WhatsApp do usuário, ex.: "(11) 9XXXX-XXXX"')
    criar_super_p = sub.add_parser(
        "criar-superadmin", help="cria o superadmin do site novo (o dono do sistema; um só, recusa se já houver)"
    )
    criar_super_p.add_argument("nome")
    criar_super_p.add_argument("numero", help='número de WhatsApp, ex.: "(11) 9XXXX-XXXX"')
    trocar_super_p = sub.add_parser(
        "trocar-superadmin", help="passa o superadmin para outro usuário ativo (o antigo continua admin)"
    )
    trocar_super_p.add_argument("numero", help='número de WhatsApp do usuário, ex.: "(11) 9XXXX-XXXX"')
```

Antes de `def main`, acrescente:

```python
def _numero_ou_sair(texto: str) -> str:
    from tcg_sniper.formatacao import normalizar_numero

    try:
        return normalizar_numero(texto)
    except ValueError:
        raise SystemExit('número inválido: use DDD e número, ex.: "(11) 9XXXX-XXXX"') from None


def _segredo_ou_sair(config: Config) -> str:
    """SEGREDO_API do .env (a API e o código de emergência não começam sem ela)."""
    from tcg_sniper.api.segredos import SegredoAusente, exigir_segredo

    try:
        return exigir_segredo(config)
    except SegredoAusente as erro:
        raise SystemExit(str(erro)) from None
```

No fim do encadeamento de `elif` (depois do ramo `admin`):

```python
    elif args.comando == "api":
        import uvicorn

        from tcg_sniper.api.app import criar_app

        _segredo_ou_sair(config)  # mensagem clara no terminal antes de montar o app
        uvicorn.run(criar_app(sessoes, config), host=args.host, port=args.porta)
    elif args.comando == "codigo-acesso":
        from tcg_sniper.api import acesso
        from tcg_sniper.db import repositorio_acesso as repo_acesso
        from tcg_sniper.db.repositorio import agora_utc
        from tcg_sniper.formatacao import mascarar_numero

        segredo = _segredo_ou_sair(config)
        numero = _numero_ou_sair(args.numero)
        with sessoes() as s, s.begin():
            usuario = repo_acesso.usuario_por_numero(s, numero)
            if usuario is None or not usuario.ativo:
                raise SystemExit("nenhum usuário ativo com esse número")
            nome = usuario.nome
            codigo = acesso.emitir_codigo(s, usuario.id, agora_utc(), segredo)
        # no terminal de propósito (é o acesso de emergência); nunca no log
        print(f"Código para {nome} ({mascarar_numero(numero)}): {codigo}")
        print("Vale por 5 minutos, uma vez. Digite na tela Entrar.")
    elif args.comando == "criar-superadmin":
        from tcg_sniper.api import avisos_acesso
        from tcg_sniper.db import repositorio_acesso as repo_acesso
        from tcg_sniper.db.repositorio import agora_utc
        from tcg_sniper.formatacao import mascarar_numero

        nome = args.nome.strip()
        if not nome:
            raise SystemExit("nome vazio")
        numero = _numero_ou_sair(args.numero)
        agora = agora_utc()
        with sessoes() as s, s.begin():
            try:
                usuario = repo_acesso.criar_superadmin(s, nome, numero, agora)
            except repo_acesso.SuperadminJaExiste:
                raise SystemExit(
                    "já existe um superadmin; para trocar use tcg-sniper trocar-superadmin <número>"
                ) from None
            except repo_acesso.NumeroJaCadastrado:
                raise SystemExit(
                    "este número já é de um usuário; para torná-lo superadmin use tcg-sniper trocar-superadmin <número>"
                ) from None
            avisos_acesso.usuario_criado(s, usuario, "terminal", agora)
        print(
            f"Superadmin {nome} criado ({mascarar_numero(numero)}). Para entrar: peça o código na tela Entrar "
            "ou rode tcg-sniper codigo-acesso com o número."
        )
    elif args.comando == "trocar-superadmin":
        from tcg_sniper.api import avisos_acesso
        from tcg_sniper.db import repositorio_acesso as repo_acesso
        from tcg_sniper.db.repositorio import agora_utc
        from tcg_sniper.formatacao import mascarar_numero

        numero = _numero_ou_sair(args.numero)
        agora = agora_utc()
        with sessoes() as s, s.begin():
            atual = repo_acesso.superadmin_atual(s)
            if atual is None:
                raise SystemExit("ainda não há superadmin; use tcg-sniper criar-superadmin <nome> <número>")
            novo = repo_acesso.usuario_por_numero(s, numero)
            if novo is None or not novo.ativo:
                raise SystemExit("nenhum usuário ativo com esse número")
            if novo.id == atual.id:
                raise SystemExit("este usuário já é o superadmin")
            antigo = repo_acesso.trocar_superadmin(s, novo)
            avisos_acesso.superadmin_trocado(s, novo, antigo, "terminal", agora)
            nome_novo, nome_antigo = novo.nome, antigo.nome
        print(f"Superadmin agora é {nome_novo} ({mascarar_numero(numero)}); {nome_antigo} continua admin.")
```

- [ ] **Step 5: Rodar os testes do CLI**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t6 uv run pytest tests/test_cli.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t6 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde.

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/cli.py tests/test_cli.py
git commit -m "feat: cli commands api, codigo-acesso, criar-superadmin and trocar-superadmin"
```

---

### Task 7: Front base (React + Vite + DaisyUI, login, rotas protegidas, sem acesso, indisponível)

**Files:**
- Create: `web/package.json`, `web/package-lock.json` (gerado), `web/.npmrc`, `web/index.html`, `web/vite.config.ts`, `web/tsconfig.json`
- Create: `web/src/main.tsx`, `App.tsx`, `estilo.css`, `api.ts`, `sessao.tsx`, `tema.ts`, `tipos.ts`, `permissoes.ts`, `enderecos.ts`
- Create: `web/src/componentes/Layout.tsx`, `RotaProtegida.tsx`, `BotaoTema.tsx`, `Carregando.tsx`
- Create: `web/src/paginas/Entrar.tsx`, `AreaNegocio.tsx`, `Gestao.tsx`, `SemAcesso.tsx`, `Indisponivel.tsx`, `NaoEncontrada.tsx`
- Create: `web/src/teste/configuracao.ts`, `web/src/teste/apoio.tsx`
- Modify: `.gitignore` (`web/node_modules/`, `web/dist/`)
- Test: `web/src/api.test.ts`, `web/src/rotas.test.tsx`, `web/src/paginas/Entrar.test.tsx`

**Interfaces:**
- Consumes (contrato da API, Tasks 3–5; nesta tarefa tudo é simulado nos testes): `GET /api/auth/eu` → 200 `{"id", "nome", "papel", "superadmin", "permissoes": [...]}` ou 401 `{"erro": "sem_sessao", ...}`; `POST /api/auth/pedir-codigo` `{"numero"}` → 200 `{"ok": true, "mensagem"}`, 422/429 `{erro, mensagem}`; `POST /api/auth/entrar` `{"numero", "codigo"}` → 200 Eu ou 401 `{"erro": "codigo_invalido", ...}`; `POST /api/auth/sair` → 200 `{"ok": true}`. API fora: erro de rede ou 502/503/504 (Caddy).
- Produces:
  - `api.ts`: `class ErroApi extends Error` (`status: number`, `erro: string`, `message` = mensagem da API); `class ApiIndisponivel extends Error`; `chamarApi<T>(caminho: string, opcoes?: { metodo?: "GET" | "POST" | "PUT" | "PATCH"; corpo?: unknown }): Promise<T>`.
  - `tipos.ts`: `Papel`, `Permissao` (uniões com os valores da API), `Eu`, `Usuario`, `SessaoAparelho`, `GradeAcessos`.
  - `sessao.tsx`: `SessaoProvider`; `useSessao(): { sessao: EstadoSessao; recarregar(): Promise<void>; definirEu(eu: Eu): void; sair(): Promise<void>; pode(p: Permissao): boolean; tratarErro(erro: unknown): string | null }`; `EstadoSessao = {estado: "carregando"} | {estado: "anonimo"} | {estado: "indisponivel"} | {estado: "logado"; eu: Eu}`. `tratarErro`: rede/5xx do proxy → indisponível (devolve null); 401 `sem_sessao` → anônimo (null, a rota volta para /entrar); 403 → recarrega o `eu` (a rota manda para /sem-acesso se a permissão saiu) e devolve a mensagem; outro erro da API → a mensagem.
  - `permissoes.ts`: `ROTULO_PAPEL: Record<Papel, string>`; `paginaInicial(permissoes: Permissao[]): string`.
  - `componentes/RotaProtegida.tsx`: `RotaProtegida` (sem login → `/entrar`; com login → `Layout` + `Outlet`) e `Exige({ permissao, children })` (sem a permissão → `/sem-acesso`).
  - `App.tsx`: `Rotas` (as rotas, usado também nos testes) e `export default App` (`SessaoProvider` + `BrowserRouter` + `Rotas`).
  - Títulos (`h1`) que testes e o ponta a ponta procuram: "Entrar", "Área de negócio", "Gestão", "Sem acesso", "Sistema indisponível", "Página não encontrada". Rótulos dos campos do login: "Número do WhatsApp", "Código"; botões "Receber código", "Entrar", "Usar outro número", "Sair", "Tentar de novo".
  - `teste/apoio.tsx`: `apiFalsa(respostas: Record<string, RespostaFalsa | RespostaFalsa[]>): Chamada[]` (chave `"MÉTODO /caminho"`; lista = uma resposta por chamada, a última se repete; `"rede-fora"` simula a API fora); `ok(corpo)`; `renderizarEm(caminho: string)`; `EU_GRUPO`, `EU_OPERADOR`, `EU_ADMIN` (admin comum), `EU_SUPERADMIN`.

- [ ] **Step 1: Configuração do projeto**

Acrescente ao `.gitignore` da raiz:

```gitignore

# Front (web/): dependências e build locais.
web/node_modules/
web/dist/
```

Crie `web/.npmrc`:

```ini
save-exact=true
fund=false
```

Crie `web/package.json`:

```json
{
  "name": "tcg-sniper-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "19.1.0",
    "react-dom": "19.1.0",
    "react-router": "7.6.2"
  },
  "devDependencies": {
    "@tailwindcss/vite": "4.1.11",
    "@testing-library/dom": "10.4.0",
    "@testing-library/jest-dom": "6.6.3",
    "@testing-library/react": "16.3.0",
    "@testing-library/user-event": "14.6.1",
    "@types/react": "19.1.8",
    "@types/react-dom": "19.1.6",
    "@vitejs/plugin-react": "4.6.0",
    "daisyui": "5.2.0",
    "jsdom": "26.1.0",
    "tailwindcss": "4.1.11",
    "typescript": "5.8.3",
    "vite": "6.3.5",
    "vitest": "3.2.4"
  }
}
```

(Tailwind 4.1.11 e DaisyUI 5.2.0 são as mesmas versões do admin, em `scripts/gerar_css.py`. Se o `npm install` disser que alguma versão não existe, use o patch mais novo da mesma versão menor que exista há pelo menos um mês, anote no commit e mantenha o número exato, sem `^`.)

Crie `web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noEmit": true,
    "isolatedModules": true,
    "skipLibCheck": true,
    "types": ["vite/client"]
  },
  "include": ["src"]
}
```

Crie `web/vite.config.ts`:

```ts
/// <reference types="vitest/config" />
// Vite (build e servidor de desenvolvimento) e Vitest (testes).
// Em `npm run dev` e `vite preview` (teste ponta a ponta), /api vai para a API local (API_ALVO);
// no container quem faz esse repasse é o Caddy (web/Caddyfile). Mesma origem: sem CORS.
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const alvoApi = process.env.API_ALVO ?? "http://127.0.0.1:8100";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": alvoApi } },
  preview: { proxy: { "/api": alvoApi } },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/teste/configuracao.ts"],
    css: false,
  },
});
```

Crie `web/index.html`:

```html
<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>TCG Sniper</title>
    <script>
      // Tema salvo, antes de pintar a página (mesma chave "tema" do admin antigo).
      try { var t = localStorage.getItem("tema"); if (t === "winter" || t === "night") document.documentElement.dataset.theme = t; } catch (e) {}
    </script>
  </head>
  <body>
    <div id="raiz"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Crie `web/src/estilo.css`:

```css
/* Tailwind CSS 4 + DaisyUI 5, temas winter (claro, padrão) e night (escuro).
   Só o framework: nada de CSS próprio (mesma regra do admin antigo). */
@import "tailwindcss";
@plugin "daisyui" {
  themes: winter --default, night --prefersdark;
}
```

Run (em `web/`): `npm install`
Expected: cria `web/node_modules/` e `web/package-lock.json` sem erro.

- [ ] **Step 2: Apoio dos testes**

Crie `web/src/teste/configuracao.ts`:

```ts
// Preparação de todo teste (Vitest): matchers do jest-dom e limpeza entre testes.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});
```

Crie `web/src/teste/apoio.tsx`:

```tsx
// Ajudantes dos testes: API falsa (troca o fetch) e renderização do app numa rota.
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import { Rotas } from "../App";
import { SessaoProvider } from "../sessao";
import type { Eu } from "../tipos";

export type RespostaFalsa = { status: number; corpo?: unknown } | "rede-fora";

export interface Chamada {
  metodo: string;
  caminho: string;
  corpo: unknown;
  credenciais: RequestCredentials | undefined;
}

export const ok = (corpo: unknown): RespostaFalsa => ({ status: 200, corpo });

export const SEM_SESSAO: RespostaFalsa = {
  status: 401,
  corpo: { erro: "sem_sessao", mensagem: "Entre de novo para continuar." },
};

/** Responde cada "MÉTODO /caminho" com a resposta dada (lista: uma por chamada, a última se repete). */
export function apiFalsa(respostas: Record<string, RespostaFalsa | RespostaFalsa[]>): Chamada[] {
  const chamadas: Chamada[] = [];
  const fetchFalso = vi.fn(async (entrada: RequestInfo | URL, init?: RequestInit) => {
    const caminho = String(entrada);
    const metodo = init?.method ?? "GET";
    const corpo = init?.body ? JSON.parse(String(init.body)) : undefined;
    chamadas.push({ metodo, caminho, corpo, credenciais: init?.credentials });
    const registrada = respostas[`${metodo} ${caminho}`];
    if (registrada === undefined) throw new Error(`teste sem resposta falsa para ${metodo} ${caminho}`);
    const resposta = Array.isArray(registrada)
      ? registrada.length > 1
        ? registrada.shift()!
        : registrada[0]
      : registrada;
    if (resposta === "rede-fora") throw new TypeError("Failed to fetch");
    const texto = resposta.corpo === undefined ? null : JSON.stringify(resposta.corpo);
    return new Response(texto, { status: resposta.status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchFalso);
  return chamadas;
}

export function renderizarEm(caminho: string) {
  return render(
    <SessaoProvider>
      <MemoryRouter initialEntries={[caminho]}>
        <Rotas />
      </MemoryRouter>
    </SessaoProvider>,
  );
}

export const EU_GRUPO: Eu = {
  id: 2,
  nome: "Pessoa Grupo",
  papel: "grupo",
  superadmin: false,
  permissoes: ["ver_area_negocio"],
};
export const EU_OPERADOR: Eu = {
  id: 3,
  nome: "Pessoa Operador",
  papel: "operador",
  superadmin: false,
  permissoes: ["ver_area_negocio", "ver_area_gestao"],
};
/** Admin comum: gere operador e grupo, não mexe em admins. */
export const EU_ADMIN: Eu = {
  id: 1,
  nome: "Pessoa Admin",
  papel: "admin",
  superadmin: false,
  permissoes: ["ver_area_negocio", "ver_area_gestao", "gerir_usuarios", "gerir_acessos", "ver_documentacao_api"],
};
/** O dono do sistema: o único que mexe em admins. */
export const EU_SUPERADMIN: Eu = { ...EU_ADMIN, id: 10, nome: "Pessoa Superadmin", superadmin: true };
```

- [ ] **Step 3: Testes (falham)**

Crie `web/src/api.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { ApiIndisponivel, chamarApi, ErroApi } from "./api";
import { apiFalsa, ok } from "./teste/apoio";

describe("chamarApi", () => {
  it("devolve o JSON e manda o cookie da mesma origem", async () => {
    const chamadas = apiFalsa({ "POST /api/x": ok({ a: 1 }) });
    expect(await chamarApi("/api/x", { metodo: "POST", corpo: { b: 2 } })).toEqual({ a: 1 });
    expect(chamadas[0]).toMatchObject({ metodo: "POST", caminho: "/api/x", corpo: { b: 2 }, credenciais: "same-origin" });
  });

  it("erro da API vira ErroApi com o código e a mensagem", async () => {
    apiFalsa({ "GET /api/x": { status: 403, corpo: { erro: "sem_permissao", mensagem: "Seu acesso não permite isto." } } });
    const erro = await chamarApi("/api/x").catch((e: unknown) => e);
    expect(erro).toBeInstanceOf(ErroApi);
    expect(erro).toMatchObject({ status: 403, erro: "sem_permissao", message: "Seu acesso não permite isto." });
  });

  it.each([502, 503, 504])("HTTP %i (proxy sem API) vira ApiIndisponivel", async (status) => {
    apiFalsa({ "GET /api/x": { status } });
    await expect(chamarApi("/api/x")).rejects.toBeInstanceOf(ApiIndisponivel);
  });

  it("rede fora vira ApiIndisponivel", async () => {
    apiFalsa({ "GET /api/x": "rede-fora" });
    await expect(chamarApi("/api/x")).rejects.toBeInstanceOf(ApiIndisponivel);
  });
});
```

Crie `web/src/rotas.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { apiFalsa, EU_GRUPO, EU_OPERADOR, ok, renderizarEm, SEM_SESSAO } from "./teste/apoio";

describe("proteção das rotas", () => {
  it("sem sessão, qualquer tela vai para Entrar", async () => {
    apiFalsa({ "GET /api/auth/eu": SEM_SESSAO });
    renderizarEm("/gestao");
    expect(await screen.findByRole("heading", { name: "Entrar" })).toBeInTheDocument();
  });

  it("grupo vê a área de negócio e não vê o menu Gestão", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO) });
    renderizarEm("/");
    expect(await screen.findByRole("heading", { name: "Área de negócio" })).toBeInTheDocument();
    expect(screen.queryAllByRole("link", { name: "Gestão" })).toHaveLength(0);
    expect(screen.getAllByRole("link", { name: "Negócio" }).length).toBeGreaterThan(0);
  });

  it("grupo em /gestao vai para Sem acesso", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO) });
    renderizarEm("/gestao");
    expect(await screen.findByRole("heading", { name: "Sem acesso" })).toBeInTheDocument();
  });

  it("operador entra na gestão, sem os cartões que não pode", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_OPERADOR) });
    renderizarEm("/gestao");
    expect(await screen.findByRole("heading", { name: "Gestão" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Usuários/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Serviços" })).toHaveAttribute("href", "http://localhost:8000/servicos");
  });

  it("API fora: Sistema indisponível, e Tentar de novo volta quando a API responde", async () => {
    apiFalsa({ "GET /api/auth/eu": ["rede-fora", ok(EU_GRUPO)] });
    renderizarEm("/");
    expect(await screen.findByRole("heading", { name: "Sistema indisponível" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("heading", { name: "Área de negócio" })).toBeInTheDocument();
  });

  it("Sair encerra a sessão e volta para Entrar", async () => {
    const chamadas = apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO), "POST /api/auth/sair": ok({ ok: true }) });
    renderizarEm("/");
    await userEvent.click(await screen.findByRole("button", { name: "Sair" }));
    expect(await screen.findByRole("heading", { name: "Entrar" })).toBeInTheDocument();
    expect(chamadas.some((c) => c.metodo === "POST" && c.caminho === "/api/auth/sair")).toBe(true);
  });

  it("rota desconhecida mostra Página não encontrada", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO) });
    renderizarEm("/nada");
    expect(await screen.findByRole("heading", { name: "Página não encontrada" })).toBeInTheDocument();
  });
});
```

Crie `web/src/paginas/Entrar.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { apiFalsa, EU_GRUPO, EU_OPERADOR, ok, renderizarEm, SEM_SESSAO } from "../teste/apoio";

const PEDIDO_OK = ok({ ok: true, mensagem: "Se o número estiver cadastrado, o código chega no WhatsApp em instantes." });

async function pedirCodigo(numero = "11 90000-0002") {
  const usuario = userEvent.setup();
  await usuario.type(await screen.findByLabelText("Número do WhatsApp"), numero);
  await usuario.click(screen.getByRole("button", { name: "Receber código" }));
  return usuario;
}

describe("Entrar", () => {
  it("número, código e entra na área de negócio", async () => {
    const chamadas = apiFalsa({
      "GET /api/auth/eu": SEM_SESSAO,
      "POST /api/auth/pedir-codigo": PEDIDO_OK,
      "POST /api/auth/entrar": ok(EU_GRUPO),
    });
    renderizarEm("/entrar");
    const usuario = await pedirCodigo();
    expect(await screen.findByText(/o código chega no WhatsApp/)).toBeInTheDocument();
    expect(screen.getByText(/pode demorar/)).toBeInTheDocument();
    await usuario.type(screen.getByLabelText("Código"), "123456");
    await usuario.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("heading", { name: "Área de negócio" })).toBeInTheDocument();
    const entrar = chamadas.find((c) => c.caminho === "/api/auth/entrar");
    expect(entrar?.corpo).toEqual({ numero: "11 90000-0002", codigo: "123456" });
  });

  it("quem só tem a gestão cai na gestão depois de entrar", async () => {
    apiFalsa({
      "GET /api/auth/eu": SEM_SESSAO,
      "POST /api/auth/pedir-codigo": PEDIDO_OK,
      "POST /api/auth/entrar": ok({ ...EU_OPERADOR, permissoes: ["ver_area_gestao"] }),
    });
    renderizarEm("/entrar");
    const usuario = await pedirCodigo();
    await usuario.type(await screen.findByLabelText("Código"), "123456");
    await usuario.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("heading", { name: "Gestão" })).toBeInTheDocument();
  });

  it("código errado mostra a mensagem da API e continua na tela", async () => {
    apiFalsa({
      "GET /api/auth/eu": SEM_SESSAO,
      "POST /api/auth/pedir-codigo": PEDIDO_OK,
      "POST /api/auth/entrar": {
        status: 401,
        corpo: { erro: "codigo_invalido", mensagem: "Código errado, vencido ou já usado. Peça um novo." },
      },
    });
    renderizarEm("/entrar");
    const usuario = await pedirCodigo();
    await usuario.type(await screen.findByLabelText("Código"), "000000");
    await usuario.click(screen.getByRole("button", { name: "Entrar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Código errado, vencido ou já usado.");
    expect(screen.getByRole("heading", { name: "Entrar" })).toBeInTheDocument();
  });

  it("limite de pedidos mostra a mensagem e fica no número", async () => {
    apiFalsa({
      "GET /api/auth/eu": SEM_SESSAO,
      "POST /api/auth/pedir-codigo": {
        status: 429,
        corpo: { erro: "limite", mensagem: "Muitos pedidos de código. Espere alguns minutos e tente de novo." },
      },
    });
    renderizarEm("/entrar");
    await pedirCodigo();
    expect(await screen.findByRole("alert")).toHaveTextContent("Muitos pedidos de código.");
    expect(screen.getByLabelText("Número do WhatsApp")).toBeInTheDocument();
  });

  it("Usar outro número volta para o primeiro passo", async () => {
    apiFalsa({ "GET /api/auth/eu": SEM_SESSAO, "POST /api/auth/pedir-codigo": PEDIDO_OK });
    renderizarEm("/entrar");
    const usuario = await pedirCodigo();
    await usuario.click(await screen.findByRole("button", { name: "Usar outro número" }));
    expect(screen.getByLabelText("Número do WhatsApp")).toHaveValue("11 90000-0002");
  });

  it("já logado, /entrar vai direto para o início", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO) });
    renderizarEm("/entrar");
    expect(await screen.findByRole("heading", { name: "Área de negócio" })).toBeInTheDocument();
  });
});
```

Run (em `web/`): `npm test`
Expected: FAIL (módulos `./api`, `../App`, `../sessao` não existem).

- [ ] **Step 4: Tipos, API, tema e sessão**

Crie `web/src/tipos.ts`:

```ts
// Formatos que a API devolve (src/tcg_sniper/api/). Mantenha igual aos modelos Pydantic de lá.

export type Papel = "grupo" | "operador" | "admin";

export type Permissao =
  | "ver_area_negocio"
  | "ver_area_gestao"
  | "gerir_usuarios"
  | "gerir_acessos"
  | "ver_documentacao_api";

/** GET /api/auth/eu e POST /api/auth/entrar. `superadmin`: o dono do sistema (só ele mexe em admins). */
export interface Eu {
  id: number;
  nome: string;
  papel: Papel;
  superadmin: boolean;
  permissoes: Permissao[];
}

/** GET /api/usuarios (o número vem sempre mascarado). O superadmin é sempre admin e ativo. */
export interface Usuario {
  id: number;
  nome: string;
  numero_mascarado: string;
  papel: Papel;
  superadmin: boolean;
  ativo: boolean;
  criado_em: string;
  sessoes_ativas: number;
}

/** GET /api/usuarios/{id}/sessoes. */
export interface SessaoAparelho {
  id: number;
  aparelho: string;
  criada_em: string;
  ultimo_uso_em: string;
  expira_em: string;
  atual: boolean;
}

/** GET/PUT /api/acessos. */
export interface GradeAcessos {
  papeis: { papel: Papel; rotulo: string; editavel: boolean }[];
  permissoes: { permissao: Permissao; rotulo: string; descricao: string; valores: Record<Papel, boolean> }[];
}
```

Crie `web/src/api.ts`:

```ts
// Chamadas à API. Mesma origem: o Caddy (no container) ou o Vite (em desenvolvimento) repassa /api para o
// serviço api. O cookie de sessão é HttpOnly: o front nunca o lê; o navegador manda sozinho.

/** Erro no formato padrão da API: {erro, mensagem}. `message` é a mensagem em português para mostrar. */
export class ErroApi extends Error {
  readonly status: number;
  readonly erro: string;

  constructor(status: number, erro: string, mensagem: string) {
    super(mensagem);
    this.status = status;
    this.erro = erro;
  }
}

/** A API não respondeu (fora do ar, ou o proxy devolveu 502/503/504). */
export class ApiIndisponivel extends Error {
  constructor() {
    super("Sistema indisponível");
  }
}

interface Opcoes {
  metodo?: "GET" | "POST" | "PUT" | "PATCH";
  corpo?: unknown;
}

export async function chamarApi<T>(caminho: string, { metodo = "GET", corpo }: Opcoes = {}): Promise<T> {
  let resposta: Response;
  try {
    resposta = await fetch(caminho, {
      method: metodo,
      credentials: "same-origin",
      headers: corpo === undefined ? undefined : { "Content-Type": "application/json" },
      body: corpo === undefined ? undefined : JSON.stringify(corpo),
    });
  } catch {
    throw new ApiIndisponivel();
  }
  if (resposta.status === 502 || resposta.status === 503 || resposta.status === 504) {
    throw new ApiIndisponivel();
  }
  const dados: unknown = await resposta.json().catch(() => null);
  if (!resposta.ok) {
    const { erro = "desconhecido", mensagem = "Erro inesperado. Tente de novo." } = (dados ?? {}) as {
      erro?: string;
      mensagem?: string;
    };
    throw new ErroApi(resposta.status, erro, mensagem);
  }
  return dados as T;
}
```

Crie `web/src/tema.ts`:

```ts
// Tema claro (winter) ou escuro (night), guardado no localStorage com a mesma chave do admin antigo.
export type Tema = "winter" | "night";

const CHAVE = "tema";

export function temaEscuroAgora(): boolean {
  const atual = document.documentElement.dataset.theme;
  if (atual) return atual === "night";
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function aplicarTema(tema: Tema): void {
  document.documentElement.dataset.theme = tema;
  try {
    localStorage.setItem(CHAVE, tema);
  } catch {
    // navegador sem localStorage: o tema vale só nesta página
  }
}
```

Crie `web/src/permissoes.ts`:

```ts
// Rótulos dos papéis e a tela inicial de cada pessoa (pelas permissões que a API devolveu).
import type { Papel, Permissao } from "./tipos";

export const ROTULO_PAPEL: Record<Papel, string> = { grupo: "Grupo", operador: "Operador", admin: "Admin" };

export function paginaInicial(permissoes: Permissao[]): string {
  if (permissoes.includes("ver_area_negocio")) return "/";
  if (permissoes.includes("ver_area_gestao")) return "/gestao";
  return "/sem-acesso";
}
```

Crie `web/src/enderecos.ts`:

```ts
// Endereço do admin antigo (porta 8000 no mesmo PC), para as telas que ainda não mudaram para cá.
export function enderecoAdminAntigo(caminho = ""): string {
  return `${window.location.protocol}//${window.location.hostname}:8000/${caminho}`;
}
```

Crie `web/src/sessao.tsx`:

```tsx
// Quem está logado. Ao abrir, pergunta à API (GET /api/auth/eu); as telas usam `pode()` para esconder o que a
// pessoa não pode (a API confere de novo em toda chamada) e `tratarErro()` para reagir a 401/403/API fora.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { ApiIndisponivel, chamarApi, ErroApi } from "./api";
import type { Eu, Permissao } from "./tipos";

export type EstadoSessao =
  | { estado: "carregando" }
  | { estado: "anonimo" }
  | { estado: "indisponivel" }
  | { estado: "logado"; eu: Eu };

interface ValorSessao {
  sessao: EstadoSessao;
  recarregar: () => Promise<void>;
  definirEu: (eu: Eu) => void;
  sair: () => Promise<void>;
  pode: (permissao: Permissao) => boolean;
  tratarErro: (erro: unknown) => string | null;
}

const ContextoSessao = createContext<ValorSessao | null>(null);

export function SessaoProvider({ children }: { children: ReactNode }) {
  const [sessao, setSessao] = useState<EstadoSessao>({ estado: "carregando" });

  const recarregar = useCallback(async () => {
    try {
      setSessao({ estado: "logado", eu: await chamarApi<Eu>("/api/auth/eu") });
    } catch (erro) {
      const semSessao = erro instanceof ErroApi && erro.status === 401;
      setSessao(semSessao ? { estado: "anonimo" } : { estado: "indisponivel" });
    }
  }, []);

  useEffect(() => {
    void recarregar();
  }, [recarregar]);

  const definirEu = useCallback((eu: Eu) => setSessao({ estado: "logado", eu }), []);

  const sair = useCallback(async () => {
    try {
      await chamarApi("/api/auth/sair", { metodo: "POST" });
    } catch {
      // sem API a sessão vence sozinha; a tela volta para Entrar do mesmo jeito
    }
    setSessao({ estado: "anonimo" });
  }, []);

  const tratarErro = useCallback(
    (erro: unknown): string | null => {
      if (erro instanceof ApiIndisponivel) {
        setSessao({ estado: "indisponivel" });
        return null;
      }
      if (erro instanceof ErroApi) {
        if (erro.status === 401 && erro.erro === "sem_sessao") {
          setSessao({ estado: "anonimo" });
          return null;
        }
        if (erro.status === 403) void recarregar(); // a permissão pode ter saído: as rotas reagem
        return erro.message;
      }
      return "Erro inesperado. Tente de novo.";
    },
    [recarregar],
  );

  const pode = (permissao: Permissao) => sessao.estado === "logado" && sessao.eu.permissoes.includes(permissao);

  return (
    <ContextoSessao.Provider value={{ sessao, recarregar, definirEu, sair, pode, tratarErro }}>
      {children}
    </ContextoSessao.Provider>
  );
}

export function useSessao(): ValorSessao {
  const valor = useContext(ContextoSessao);
  if (valor === null) throw new Error("useSessao fora do SessaoProvider");
  return valor;
}
```

- [ ] **Step 5: Componentes**

Crie `web/src/componentes/Carregando.tsx`:

```tsx
// Indicador de carregamento (DaisyUI loading).
export function Carregando() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <span className="loading loading-spinner loading-lg" aria-label="Carregando" />
    </div>
  );
}
```

Crie `web/src/componentes/BotaoTema.tsx`:

```tsx
// Troca entre o tema claro (winter) e o escuro (night).
import { useState } from "react";
import { aplicarTema, temaEscuroAgora } from "../tema";

export function BotaoTema() {
  const [escuro, setEscuro] = useState(temaEscuroAgora);

  function trocar() {
    aplicarTema(escuro ? "winter" : "night");
    setEscuro(!escuro);
  }

  return (
    <button type="button" className="btn btn-ghost btn-sm" aria-label="Trocar tema" aria-pressed={escuro} onClick={trocar}>
      {escuro ? "☀" : "☾"}
    </button>
  );
}
```

Crie `web/src/componentes/Layout.tsx`:

```tsx
// Moldura das telas logadas: barra com o menu (só o que a pessoa pode), nome, papel, tema e Sair.
import type { ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router";
import { ROTULO_PAPEL } from "../permissoes";
import { useSessao } from "../sessao";
import { BotaoTema } from "./BotaoTema";

export function Layout({ children }: { children: ReactNode }) {
  const { sessao, pode, sair } = useSessao();
  const navegar = useNavigate();
  if (sessao.estado !== "logado") return null;
  const { eu } = sessao;

  async function aoSair() {
    await sair();
    navegar("/entrar", { replace: true });
  }

  const links = (
    <>
      {pode("ver_area_negocio") && (
        <li>
          <NavLink to="/" end>
            Negócio
          </NavLink>
        </li>
      )}
      {pode("ver_area_gestao") && (
        <li>
          <NavLink to="/gestao">Gestão</NavLink>
        </li>
      )}
    </>
  );

  return (
    <div className="min-h-screen bg-base-200">
      <nav className="navbar bg-base-100 shadow-sm">
        <div className="navbar-start">
          <div className="dropdown lg:hidden">
            <div tabIndex={0} role="button" className="btn btn-ghost btn-sm" aria-label="Menu">
              ☰
            </div>
            <ul tabIndex={0} className="menu menu-sm dropdown-content z-10 mt-3 w-52 rounded-box bg-base-100 p-2 shadow">
              {links}
            </ul>
          </div>
          <Link to="/" className="btn btn-ghost text-lg">
            TCG Sniper
          </Link>
        </div>
        <div className="navbar-center hidden lg:flex">
          <ul className="menu menu-horizontal px-1">{links}</ul>
        </div>
        <div className="navbar-end gap-1">
          <span className="hidden text-sm sm:inline">{eu.nome}</span>
          <span className="badge badge-ghost badge-sm">{ROTULO_PAPEL[eu.papel]}</span>
          <BotaoTema />
          <button type="button" className="btn btn-ghost btn-sm" onClick={aoSair}>
            Sair
          </button>
        </div>
      </nav>
      <main className="mx-auto max-w-5xl p-4">{children}</main>
    </div>
  );
}
```

Crie `web/src/componentes/RotaProtegida.tsx`:

```tsx
// Guardas das rotas. Só esconde: quem decide é sempre a API.
import type { ReactNode } from "react";
import { Navigate, Outlet } from "react-router";
import { useSessao } from "../sessao";
import type { Permissao } from "../tipos";
import { Carregando } from "./Carregando";
import { Layout } from "./Layout";

/** Exige sessão: sem login vai para /entrar; com login mostra o menu e a página. */
export function RotaProtegida() {
  const { sessao } = useSessao();
  if (sessao.estado === "carregando") return <Carregando />;
  if (sessao.estado !== "logado") return <Navigate to="/entrar" replace />;
  return (
    <Layout>
      <Outlet />
    </Layout>
  );
}

/** Mostra a página só com a permissão; sem ela, /sem-acesso. */
export function Exige({ permissao, children }: { permissao: Permissao; children: ReactNode }) {
  const { pode } = useSessao();
  return pode(permissao) ? <>{children}</> : <Navigate to="/sem-acesso" replace />;
}
```

- [ ] **Step 6: Páginas**

Crie `web/src/paginas/Entrar.tsx`:

```tsx
// Login em dois passos: número → código que chega no WhatsApp → entrar (a API grava o cookie de sessão).
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router";
import { chamarApi } from "../api";
import { BotaoTema } from "../componentes/BotaoTema";
import { Carregando } from "../componentes/Carregando";
import { paginaInicial } from "../permissoes";
import { useSessao } from "../sessao";
import type { Eu } from "../tipos";

export function Entrar() {
  const { sessao, definirEu, tratarErro } = useSessao();
  const navegar = useNavigate();
  const [etapa, setEtapa] = useState<"numero" | "codigo">("numero");
  const [numero, setNumero] = useState("");
  const [codigo, setCodigo] = useState("");
  const [aviso, setAviso] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  if (sessao.estado === "carregando") return <Carregando />;
  if (sessao.estado === "logado") return <Navigate to={paginaInicial(sessao.eu.permissoes)} replace />;

  async function pedirCodigo(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      const resposta = await chamarApi<{ mensagem: string }>("/api/auth/pedir-codigo", {
        metodo: "POST",
        corpo: { numero },
      });
      setAviso(resposta.mensagem);
      setCodigo("");
      setEtapa("codigo");
    } catch (e) {
      setErro(tratarErro(e));
    } finally {
      setEnviando(false);
    }
  }

  async function entrar(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      const eu = await chamarApi<Eu>("/api/auth/entrar", { metodo: "POST", corpo: { numero, codigo } });
      definirEu(eu);
      navegar(paginaInicial(eu.permissoes), { replace: true });
    } catch (e) {
      setErro(tratarErro(e));
      setEnviando(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-base-200 p-4">
      <div className="card w-full max-w-sm bg-base-100 shadow-md">
        <div className="card-body gap-4">
          <div className="flex items-center justify-between">
            <h1 className="card-title text-2xl">Entrar</h1>
            <BotaoTema />
          </div>
          {erro && (
            <div role="alert" className="alert alert-error">
              {erro}
            </div>
          )}
          {etapa === "numero" ? (
            <form onSubmit={pedirCodigo} className="flex flex-col gap-4">
              <fieldset className="fieldset">
                <label className="fieldset-legend" htmlFor="numero">
                  Número do WhatsApp
                </label>
                <input
                  id="numero"
                  className="input w-full"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  placeholder="(11) 9XXXX-XXXX"
                  required
                  maxLength={30}
                  value={numero}
                  onChange={(e) => setNumero(e.target.value)}
                />
              </fieldset>
              <button type="submit" className="btn btn-primary" disabled={enviando}>
                Receber código
              </button>
            </form>
          ) : (
            <form onSubmit={entrar} className="flex flex-col gap-4">
              <div role="status" className="alert alert-info">
                <span>
                  {aviso} Se o WhatsApp estiver fora do ar, o código pode demorar; um admin consegue gerar um código
                  pelo terminal.
                </span>
              </div>
              <fieldset className="fieldset">
                <label className="fieldset-legend" htmlFor="codigo">
                  Código
                </label>
                <input
                  id="codigo"
                  className="input w-full"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="[0-9]{6}"
                  maxLength={6}
                  required
                  value={codigo}
                  onChange={(e) => setCodigo(e.target.value)}
                />
              </fieldset>
              <button type="submit" className="btn btn-primary" disabled={enviando}>
                Entrar
              </button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEtapa("numero")}>
                Usar outro número
              </button>
            </form>
          )}
        </div>
      </div>
    </main>
  );
}
```

Crie `web/src/paginas/AreaNegocio.tsx`:

```tsx
// Área de negócio (fase 1: só o esqueleto). Nunca mostra dado de gestão: um dia será a área dos assinantes.
import { enderecoAdminAntigo } from "../enderecos";

export function AreaNegocio() {
  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold">Área de negócio</h1>
      <div className="card bg-base-100 shadow-sm">
        <div className="card-body">
          <h2 className="card-title">Em construção</h2>
          <p>Aqui vão ficar as oportunidades, o funil e os resultados do grupo (próxima fase).</p>
          <div className="card-actions">
            <a className="btn btn-primary btn-sm" href={enderecoAdminAntigo()} target="_blank" rel="noreferrer">
              Abrir o admin antigo
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
```

Crie `web/src/paginas/Gestao.tsx`:

```tsx
// Área de gestão: atalhos para as telas novas (só as que a pessoa pode) e links para o admin antigo.
import { Link } from "react-router";
import { enderecoAdminAntigo } from "../enderecos";
import { useSessao } from "../sessao";

const TELAS_ANTIGAS = [
  ["Dashboard", ""],
  ["Serviços", "servicos"],
  ["Casamentos", "casamentos"],
  ["Catálogo", "catalogo"],
  ["Ofertas", "ofertas"],
  ["Mensagens", "mensagens"],
  ["Configurações", "configuracoes"],
  ["Logs", "logs"],
] as const;

export function Gestao() {
  const { pode } = useSessao();
  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold">Gestão</h1>
      <div className="grid gap-4 sm:grid-cols-2">
        {pode("gerir_usuarios") && (
          <Link to="/gestao/usuarios" className="card bg-base-100 shadow-sm">
            <div className="card-body">
              <h2 className="card-title">Usuários</h2>
              <p>Quem entra no site, o papel de cada um e as sessões abertas.</p>
            </div>
          </Link>
        )}
        {pode("gerir_acessos") && (
          <Link to="/gestao/acessos" className="card bg-base-100 shadow-sm">
            <div className="card-body">
              <h2 className="card-title">Acessos</h2>
              <p>O que cada papel pode fazer (grade papel × permissão).</p>
            </div>
          </Link>
        )}
        {pode("ver_documentacao_api") && (
          <a href="/api/docs" className="card bg-base-100 shadow-sm">
            <div className="card-body">
              <h2 className="card-title">Documentação da API</h2>
              <p>As rotas da API (OpenAPI).</p>
            </div>
          </a>
        )}
      </div>
      <div className="card bg-base-100 shadow-sm">
        <div className="card-body">
          <h2 className="card-title">Ainda no admin antigo</h2>
          <p className="text-sm">Estas telas mudam para cá nas próximas fases. O admin antigo pede a senha dele.</p>
          <ul className="menu w-full">
            {TELAS_ANTIGAS.map(([nome, caminho]) => (
              <li key={nome}>
                <a href={enderecoAdminAntigo(caminho)} target="_blank" rel="noreferrer">
                  {nome}
                </a>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
```

Crie `web/src/paginas/SemAcesso.tsx`:

```tsx
// 403: o papel da pessoa não permite a tela.
import { Link } from "react-router";
import { paginaInicial } from "../permissoes";
import { useSessao } from "../sessao";

export function SemAcesso() {
  const { sessao } = useSessao();
  const inicio = sessao.estado === "logado" ? paginaInicial(sessao.eu.permissoes) : "/entrar";
  return (
    <section className="hero py-16">
      <div className="hero-content text-center">
        <div className="max-w-md space-y-4">
          <h1 className="text-2xl font-bold">Sem acesso</h1>
          <p>Seu papel não permite abrir esta tela. Se precisar, peça a quem cuida dos acessos.</p>
          {inicio !== "/sem-acesso" && (
            <Link className="btn btn-primary" to={inicio}>
              Voltar ao início
            </Link>
          )}
        </div>
      </div>
    </section>
  );
}
```

Crie `web/src/paginas/Indisponivel.tsx`:

```tsx
// A API não respondeu (container parado, banco fora): explica e deixa tentar de novo.
export function Indisponivel({ aoTentar }: { aoTentar: () => void }) {
  return (
    <main className="hero min-h-screen bg-base-200">
      <div className="hero-content text-center">
        <div className="max-w-md space-y-4">
          <h1 className="text-2xl font-bold">Sistema indisponível</h1>
          <p>Não foi possível falar com o servidor. Confira se os containers estão de pé (docker compose ps) e tente de novo.</p>
          <button type="button" className="btn btn-primary" onClick={aoTentar}>
            Tentar de novo
          </button>
        </div>
      </div>
    </main>
  );
}
```

Crie `web/src/paginas/NaoEncontrada.tsx`:

```tsx
// Rota que não existe.
import { Link } from "react-router";

export function NaoEncontrada() {
  return (
    <main className="hero min-h-screen bg-base-200">
      <div className="hero-content text-center">
        <div className="max-w-md space-y-4">
          <h1 className="text-2xl font-bold">Página não encontrada</h1>
          <Link className="btn btn-primary" to="/">
            Ir para o início
          </Link>
        </div>
      </div>
    </main>
  );
}
```

- [ ] **Step 7: Rotas e entrada**

Crie `web/src/App.tsx`:

```tsx
// Rotas do site. /entrar é aberta; o resto exige sessão e, cada tela, a sua permissão.
import { BrowserRouter, Outlet, Route, Routes } from "react-router";
import { Exige, RotaProtegida } from "./componentes/RotaProtegida";
import { AreaNegocio } from "./paginas/AreaNegocio";
import { Entrar } from "./paginas/Entrar";
import { Gestao } from "./paginas/Gestao";
import { Indisponivel } from "./paginas/Indisponivel";
import { NaoEncontrada } from "./paginas/NaoEncontrada";
import { SemAcesso } from "./paginas/SemAcesso";
import { SessaoProvider, useSessao } from "./sessao";

export function Rotas() {
  const { sessao, recarregar } = useSessao();
  if (sessao.estado === "indisponivel") return <Indisponivel aoTentar={() => void recarregar()} />;
  return (
    <Routes>
      <Route path="/entrar" element={<Entrar />} />
      <Route element={<RotaProtegida />}>
        <Route
          path="/"
          element={
            <Exige permissao="ver_area_negocio">
              <AreaNegocio />
            </Exige>
          }
        />
        <Route
          path="/gestao"
          element={
            <Exige permissao="ver_area_gestao">
              <Outlet />
            </Exige>
          }
        >
          <Route index element={<Gestao />} />
        </Route>
        <Route path="/sem-acesso" element={<SemAcesso />} />
      </Route>
      <Route path="*" element={<NaoEncontrada />} />
    </Routes>
  );
}

export default function App() {
  return (
    <SessaoProvider>
      <BrowserRouter>
        <Rotas />
      </BrowserRouter>
    </SessaoProvider>
  );
}
```

Crie `web/src/main.tsx`:

```tsx
// Ponto de entrada do Vite: monta o app em <div id="raiz"> e carrega o CSS (Tailwind + DaisyUI).
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./estilo.css";

createRoot(document.getElementById("raiz")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

- [ ] **Step 8: Testes e build**

Run (em `web/`): `npm test` e `npm run build`
Expected: todos os testes passam; o build (`tsc` + `vite build`) termina sem erro e gera `web/dist/`. (O teste do link "Serviços" espera `http://localhost:8000/servicos` porque o jsdom roda em `http://localhost`.)

- [ ] **Step 9: Conferir à mão (opcional, sem API)**

Run (em `web/`): `npm run dev`, abrir `http://127.0.0.1:5173/` — sem API local, deve aparecer "Sistema indisponível" (o proxy do Vite responde 502/erro). Parar o `npm run dev` (Ctrl+C) antes de seguir.

- [ ] **Step 10: Commit**

```bash
git add .gitignore web
git commit -m "feat: react front base with whatsapp login and protected routes"
```

(`web/node_modules/` e `web/dist/` ficam fora pelo `.gitignore`; confira com `git status` que só entram os arquivos de `web/` listados acima e o `package-lock.json`.)

---

### Task 8: Front — Gestão → Usuários e Gestão → Acessos

**Files:**
- Create: `web/src/paginas/Usuarios.tsx`, `web/src/paginas/Acessos.tsx`
- Modify: `web/src/App.tsx` (duas rotas filhas de `/gestao`)
- Test: `web/src/paginas/Usuarios.test.tsx`, `web/src/paginas/Acessos.test.tsx`

**Interfaces:**
- Consumes (Task 7): `chamarApi`, `useSessao` (`sessao`, `tratarErro`, `recarregar`), `ROTULO_PAPEL`, tipos `Usuario`, `SessaoAparelho`, `GradeAcessos`, `Papel`, `Permissao`; `Exige`; apoio dos testes (`apiFalsa`, `ok`, `renderizarEm`, `EU_ADMIN`, `EU_SUPERADMIN`, `EU_OPERADOR`); `Eu.superadmin`. Contrato da API (Tasks 3 e 5): `GET /api/usuarios` → `{"usuarios": Usuario[]}` (com `superadmin`); `POST /api/usuarios` `{nome, numero, papel}` → 201 `Usuario`; `PATCH /api/usuarios/{id}` `{nome, papel, ativo}` → `Usuario`; `GET /api/usuarios/{id}/sessoes` → `{"sessoes": SessaoAparelho[]}`; `POST /api/sessoes/{id}/encerrar` → `{"ok": true}`; `GET /api/acessos` e `PUT /api/acessos` `{"mudancas": [{papel, permissao, permitido}]}` → `GradeAcessos`.
- Produces: `Usuarios` (rota `/gestao/usuarios`, exige `gerir_usuarios`) e `Acessos` (rota `/gestao/acessos`, exige `gerir_acessos`). Na tela Usuários (a API confere do mesmo jeito): a opção "Admin" e os botões das linhas de admin só para o superadmin; a linha do superadmin tem o selo "superadmin" e, para os outros, nenhum botão; para ele mesmo, "Editar" com Papel e Ativo travados (só o nome muda) e "Sessões"; qualquer um vê "Sessões" na própria linha. Rótulos e textos que testes e o ponta a ponta usam: título "Usuários", campos "Nome", "Número do WhatsApp", "Papel", botão "Cadastrar", mensagem "<nome> cadastrado."; botões "Editar", "Sessões", "Salvar", "Encerrar"; selo "superadmin"; título "Acessos", toggles com `aria-label` "<Papel>: <rótulo da permissão>" (ex.: "Grupo: Entrar na área de gestão"), mensagem "Salvo. Vale na próxima ação de quem já está logado."

- [ ] **Step 1: Testes (falham)**

Crie `web/src/paginas/Usuarios.test.tsx`:

```tsx
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { apiFalsa, EU_ADMIN, EU_OPERADOR, EU_SUPERADMIN, ok, renderizarEm } from "../teste/apoio";
import type { Usuario } from "../tipos";

// ids iguais aos de EU_ADMIN (1) e EU_SUPERADMIN (10): a linha de cada um é a "própria"
const ADMIN: Usuario = {
  id: 1, nome: "Pessoa Admin", numero_mascarado: "+55 11 9****-**01", papel: "admin", superadmin: false,
  ativo: true, criado_em: "2026-10-18T13:00:00Z", sessoes_ativas: 1,
};
const SUPER: Usuario = {
  ...ADMIN, id: 10, nome: "Pessoa Superadmin", numero_mascarado: "+55 11 9****-**10", superadmin: true,
};
const GRUPO: Usuario = {
  id: 2, nome: "Pessoa Grupo", numero_mascarado: "+55 11 9****-**02", papel: "grupo", superadmin: false,
  ativo: true, criado_em: "2026-10-18T13:00:00Z", sessoes_ativas: 0,
};
const NOVA: Usuario = { ...GRUPO, id: 9, nome: "Pessoa Nova", numero_mascarado: "+55 11 9****-**09", papel: "operador" };
const OPERADOR_GERE_USUARIOS = { ...EU_OPERADOR, permissoes: [...EU_OPERADOR.permissoes, "gerir_usuarios" as const] };

describe("Gestão → Usuários", () => {
  it("lista com número mascarado e cadastra", async () => {
    const chamadas = apiFalsa({
      "GET /api/auth/eu": ok(EU_ADMIN),
      "GET /api/usuarios": [ok({ usuarios: [ADMIN, GRUPO] }), ok({ usuarios: [ADMIN, GRUPO, NOVA] })],
      "POST /api/usuarios": { status: 201, corpo: NOVA },
    });
    const usuario = userEvent.setup();
    renderizarEm("/gestao/usuarios");
    expect(await screen.findByText("+55 11 9****-**02")).toBeInTheDocument();
    await usuario.type(screen.getByLabelText("Nome"), "Pessoa Nova");
    await usuario.type(screen.getByLabelText("Número do WhatsApp"), "(11) 90000-0009");
    await usuario.selectOptions(screen.getByLabelText("Papel"), "operador");
    await usuario.click(screen.getByRole("button", { name: "Cadastrar" }));
    expect(await screen.findByText("Pessoa Nova cadastrado.")).toBeInTheDocument();
    expect(chamadas.find((c) => c.metodo === "POST")?.corpo).toEqual({
      nome: "Pessoa Nova", numero: "(11) 90000-0009", papel: "operador",
    });
    expect(await screen.findByText("+55 11 9****-**09")).toBeInTheDocument();
  });

  it("erro da API aparece (ex.: número já cadastrado)", async () => {
    apiFalsa({
      "GET /api/auth/eu": ok(EU_ADMIN),
      "GET /api/usuarios": ok({ usuarios: [ADMIN] }),
      "POST /api/usuarios": {
        status: 409, corpo: { erro: "numero_ja_cadastrado", mensagem: "Já existe um usuário com este número." },
      },
    });
    const usuario = userEvent.setup();
    renderizarEm("/gestao/usuarios");
    await usuario.type(await screen.findByLabelText("Nome"), "Outra");
    await usuario.type(screen.getByLabelText("Número do WhatsApp"), "11 90000-0001");
    await usuario.click(screen.getByRole("button", { name: "Cadastrar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Já existe um usuário com este número.");
  });

  it.each([
    ["operador com gerir_usuarios", OPERADOR_GERE_USUARIOS],
    ["admin comum", EU_ADMIN],
  ])("%s não vê a opção Admin nem os botões das linhas de admin e do superadmin", async (_nome, eu) => {
    apiFalsa({ "GET /api/auth/eu": ok(eu), "GET /api/usuarios": ok({ usuarios: [SUPER, ADMIN, GRUPO] }) });
    renderizarEm("/gestao/usuarios");
    const linhaSuper = (await screen.findByText("Pessoa Superadmin")).closest("tr")!;
    expect(within(linhaSuper).getByText("superadmin")).toBeInTheDocument();
    expect(within(linhaSuper).queryByRole("button")).not.toBeInTheDocument();
    const linhaAdmin = screen.getByText("Pessoa Admin").closest("tr")!;
    expect(within(linhaAdmin).queryByRole("button", { name: "Editar" })).not.toBeInTheDocument();
    const linhaGrupo = screen.getByText("Pessoa Grupo").closest("tr")!;
    expect(within(linhaGrupo).getByRole("button", { name: "Editar" })).toBeInTheDocument();
    const opcoes = within(screen.getByLabelText("Papel")).getAllByRole("option").map((o) => o.textContent);
    expect(opcoes).toEqual(["Grupo", "Operador"]);
  });

  it("admin comum vê Sessões na própria linha (encerra as próprias sessões)", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_ADMIN), "GET /api/usuarios": ok({ usuarios: [SUPER, ADMIN, GRUPO] }) });
    renderizarEm("/gestao/usuarios");
    const linhaAdmin = (await screen.findByText("Pessoa Admin")).closest("tr")!;
    expect(within(linhaAdmin).getByRole("button", { name: "Sessões" })).toBeInTheDocument();
  });

  it("superadmin gere admins e, na própria linha, só muda o nome", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_SUPERADMIN), "GET /api/usuarios": ok({ usuarios: [SUPER, ADMIN, GRUPO] }) });
    const usuario = userEvent.setup();
    renderizarEm("/gestao/usuarios");
    const linhaAdmin = (await screen.findByText("Pessoa Admin")).closest("tr")!;
    expect(within(linhaAdmin).getByRole("button", { name: "Editar" })).toBeInTheDocument();
    const opcoes = within(screen.getByLabelText("Papel")).getAllByRole("option").map((o) => o.textContent);
    expect(opcoes).toEqual(["Grupo", "Operador", "Admin"]);
    const linhaSuper = screen.getByText("Pessoa Superadmin").closest("tr")!;
    await usuario.click(within(linhaSuper).getByRole("button", { name: "Editar" }));
    const dialogo = screen.getByRole("dialog");
    expect(within(dialogo).getByLabelText("Papel")).toBeDisabled();
    expect(within(dialogo).getByLabelText(/Ativo/)).toBeDisabled();
    expect(within(dialogo).getByLabelText("Nome")).toBeEnabled();
  });

  it("desativar manda PATCH com ativo false", async () => {
    const chamadas = apiFalsa({
      "GET /api/auth/eu": ok(EU_ADMIN),
      "GET /api/usuarios": ok({ usuarios: [ADMIN, GRUPO] }),
      "PATCH /api/usuarios/2": ok({ ...GRUPO, ativo: false }),
    });
    const usuario = userEvent.setup();
    renderizarEm("/gestao/usuarios");
    const linha = (await screen.findByText("Pessoa Grupo")).closest("tr")!;
    await usuario.click(within(linha).getByRole("button", { name: "Editar" }));
    const dialogo = screen.getByRole("dialog");
    await usuario.click(within(dialogo).getByLabelText(/Ativo/));
    await usuario.click(within(dialogo).getByRole("button", { name: "Salvar" }));
    expect(await screen.findByText("Alterações salvas.")).toBeInTheDocument();
    expect(chamadas.find((c) => c.metodo === "PATCH")?.corpo).toEqual({ nome: "Pessoa Grupo", papel: "grupo", ativo: false });
  });

  it("sessões: lista e encerra", async () => {
    const sessao = {
      id: 7, aparelho: "Chrome · Windows", criada_em: "2026-10-18T13:00:00Z", ultimo_uso_em: "2026-10-18T14:00:00Z",
      expira_em: "2026-11-17T14:00:00Z", atual: false,
    };
    const chamadas = apiFalsa({
      "GET /api/auth/eu": ok(EU_ADMIN),
      "GET /api/usuarios": ok({ usuarios: [ADMIN, GRUPO] }),
      "GET /api/usuarios/2/sessoes": [ok({ sessoes: [sessao] }), ok({ sessoes: [] })],
      "POST /api/sessoes/7/encerrar": ok({ ok: true }),
    });
    const usuario = userEvent.setup();
    renderizarEm("/gestao/usuarios");
    const linha = (await screen.findByText("Pessoa Grupo")).closest("tr")!;
    await usuario.click(within(linha).getByRole("button", { name: "Sessões" }));
    expect(await screen.findByText("Chrome · Windows")).toBeInTheDocument();
    await usuario.click(screen.getByRole("button", { name: "Encerrar" }));
    expect(await screen.findByText("Nenhuma sessão aberta.")).toBeInTheDocument();
    expect(chamadas.some((c) => c.caminho === "/api/sessoes/7/encerrar")).toBe(true);
  });

  it("operador sem gerir_usuarios vai para Sem acesso", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_OPERADOR) });
    renderizarEm("/gestao/usuarios");
    expect(await screen.findByRole("heading", { name: "Sem acesso" })).toBeInTheDocument();
  });
});
```

Crie `web/src/paginas/Acessos.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { apiFalsa, EU_ADMIN, EU_OPERADOR, ok, renderizarEm } from "../teste/apoio";
import type { GradeAcessos } from "../tipos";

function grade(gestaoParaGrupo: boolean): GradeAcessos {
  return {
    papeis: [
      { papel: "grupo", rotulo: "Grupo", editavel: true },
      { papel: "operador", rotulo: "Operador", editavel: true },
      { papel: "admin", rotulo: "Admin", editavel: false },
    ],
    permissoes: [
      {
        permissao: "ver_area_gestao",
        rotulo: "Entrar na área de gestão",
        descricao: "Ver o menu e as telas da área administrativa.",
        valores: { grupo: gestaoParaGrupo, operador: true, admin: true },
      },
    ],
  };
}

describe("Gestão → Acessos", () => {
  it("coluna do admin travada; toggle manda PUT e mostra o novo valor", async () => {
    const chamadas = apiFalsa({
      "GET /api/auth/eu": ok(EU_ADMIN),
      "GET /api/acessos": ok(grade(false)),
      "PUT /api/acessos": ok(grade(true)),
    });
    const usuario = userEvent.setup();
    renderizarEm("/gestao/acessos");
    const admin = await screen.findByLabelText("Admin: Entrar na área de gestão");
    expect(admin).toBeChecked();
    expect(admin).toBeDisabled();
    const grupo = screen.getByLabelText("Grupo: Entrar na área de gestão");
    expect(grupo).not.toBeChecked();
    await usuario.click(grupo);
    expect(await screen.findByText("Salvo. Vale na próxima ação de quem já está logado.")).toBeInTheDocument();
    expect(screen.getByLabelText("Grupo: Entrar na área de gestão")).toBeChecked();
    expect(chamadas.find((c) => c.metodo === "PUT")?.corpo).toEqual({
      mudancas: [{ papel: "grupo", permissao: "ver_area_gestao", permitido: true }],
    });
  });

  it("operador sem gerir_acessos vai para Sem acesso", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_OPERADOR) });
    renderizarEm("/gestao/acessos");
    expect(await screen.findByRole("heading", { name: "Sem acesso" })).toBeInTheDocument();
  });
});
```

Run (em `web/`): `npm ci` (se `node_modules` não existir no worktree) e `npm test`
Expected: FAIL (rotas `/gestao/usuarios` e `/gestao/acessos` não existem: "Página não encontrada").

- [ ] **Step 2: Usuários**

Crie `web/src/paginas/Usuarios.tsx`:

```tsx
// Gestão → Usuários: lista (número sempre mascarado), cadastro, edição (nome, papel, ativo) e sessões.
// Só o superadmin vê a opção Admin e os botões das linhas de admin; ninguém rebaixa, desativa ou encerra o
// superadmin (na linha dele, só ele mesmo edita o nome e vê as sessões). A API recusa do mesmo jeito.
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { chamarApi } from "../api";
import { ROTULO_PAPEL } from "../permissoes";
import { useSessao } from "../sessao";
import type { Papel, SessaoAparelho, Usuario } from "../tipos";

function dataHora(iso: string): string {
  return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

export function Usuarios() {
  const { sessao, tratarErro } = useSessao();
  const eu = sessao.estado === "logado" ? sessao.eu : null;
  const souSuperadmin = eu?.superadmin === true;
  const papeis: Papel[] = souSuperadmin ? ["grupo", "operador", "admin"] : ["grupo", "operador"];
  // Editar: operador e grupo para quem tem gerir_usuarios; admins (e a própria linha do superadmin) só o superadmin.
  const podeEditar = (u: Usuario) => (u.superadmin ? u.id === eu?.id : souSuperadmin || u.papel !== "admin");
  // Sessões: as de quem pode editar e as próprias (cada um encerra as suas).
  const podeVerSessoes = (u: Usuario) => podeEditar(u) || u.id === eu?.id;
  const [usuarios, setUsuarios] = useState<Usuario[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [mensagem, setMensagem] = useState<string | null>(null);
  const [editando, setEditando] = useState<Usuario | null>(null);
  const [sessoesDe, setSessoesDe] = useState<Usuario | null>(null);

  const carregar = useCallback(async () => {
    try {
      const resposta = await chamarApi<{ usuarios: Usuario[] }>("/api/usuarios");
      setUsuarios(resposta.usuarios);
    } catch (e) {
      setErro(tratarErro(e));
    }
  }, [tratarErro]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  async function aposSalvar(texto: string) {
    setMensagem(texto);
    setErro(null);
    setEditando(null);
    await carregar();
  }

  function mostrarErro(texto: string | null) {
    setMensagem(null);
    setErro(texto);
  }

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold">Usuários</h1>
      {mensagem && (
        <div role="status" className="alert alert-success">
          {mensagem}
        </div>
      )}
      {erro && (
        <div role="alert" className="alert alert-error">
          {erro}
        </div>
      )}
      <NovoUsuario papeis={papeis} aoCriar={(u) => void aposSalvar(`${u.nome} cadastrado.`)} aoErro={mostrarErro} />
      {usuarios === null ? (
        <span className="loading loading-spinner" aria-label="Carregando" />
      ) : (
        <div className="overflow-x-auto rounded-box bg-base-100 shadow-sm">
          <table className="table">
            <thead>
              <tr>
                <th>Nome</th>
                <th>Número</th>
                <th>Papel</th>
                <th>Situação</th>
                <th>Sessões</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {usuarios.map((u) => (
                <tr key={u.id}>
                  <td>{u.nome}</td>
                  <td className="whitespace-nowrap">{u.numero_mascarado}</td>
                  <td className="whitespace-nowrap">
                    <span className="badge badge-ghost">{ROTULO_PAPEL[u.papel]}</span>
                    {u.superadmin && <span className="badge badge-primary badge-sm ml-1">superadmin</span>}
                  </td>
                  <td>
                    {u.ativo ? (
                      <span className="badge badge-success">Ativo</span>
                    ) : (
                      <span className="badge badge-neutral">Desativado</span>
                    )}
                  </td>
                  <td>{u.sessoes_ativas}</td>
                  <td className="whitespace-nowrap">
                    {podeEditar(u) && (
                      <button type="button" className="btn btn-ghost btn-xs" onClick={() => setEditando(u)}>
                        Editar
                      </button>
                    )}
                    {podeVerSessoes(u) && (
                      <button type="button" className="btn btn-ghost btn-xs" onClick={() => setSessoesDe(u)}>
                        Sessões
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editando && (
        <EditarUsuario
          usuario={editando}
          papeis={papeis}
          aoFechar={() => setEditando(null)}
          aoSalvar={() => void aposSalvar("Alterações salvas.")}
        />
      )}
      {sessoesDe && (
        <SessoesDoUsuario
          usuario={sessoesDe}
          aoFechar={() => {
            setSessoesDe(null);
            void carregar();
          }}
        />
      )}
    </section>
  );
}

function NovoUsuario({
  papeis,
  aoCriar,
  aoErro,
}: {
  papeis: Papel[];
  aoCriar: (usuario: Usuario) => void;
  aoErro: (texto: string | null) => void;
}) {
  const { tratarErro } = useSessao();
  const [nome, setNome] = useState("");
  const [numero, setNumero] = useState("");
  const [papel, setPapel] = useState<Papel>("grupo");
  const [enviando, setEnviando] = useState(false);

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    setEnviando(true);
    try {
      const criado = await chamarApi<Usuario>("/api/usuarios", { metodo: "POST", corpo: { nome, numero, papel } });
      setNome("");
      setNumero("");
      setPapel("grupo");
      aoCriar(criado);
    } catch (e) {
      aoErro(tratarErro(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={enviar} className="card bg-base-100 shadow-sm">
      <div className="card-body">
        <h2 className="card-title">Novo usuário</h2>
        <div className="grid gap-2 sm:grid-cols-3">
          <fieldset className="fieldset">
            <label className="fieldset-legend" htmlFor="novo-nome">
              Nome
            </label>
            <input
              id="novo-nome"
              className="input w-full"
              required
              maxLength={80}
              value={nome}
              onChange={(e) => setNome(e.target.value)}
            />
          </fieldset>
          <fieldset className="fieldset">
            <label className="fieldset-legend" htmlFor="novo-numero">
              Número do WhatsApp
            </label>
            <input
              id="novo-numero"
              className="input w-full"
              type="tel"
              inputMode="tel"
              placeholder="(11) 9XXXX-XXXX"
              required
              maxLength={30}
              value={numero}
              onChange={(e) => setNumero(e.target.value)}
            />
          </fieldset>
          <fieldset className="fieldset">
            <label className="fieldset-legend" htmlFor="novo-papel">
              Papel
            </label>
            <select
              id="novo-papel"
              className="select w-full"
              value={papel}
              onChange={(e) => setPapel(e.target.value as Papel)}
            >
              {papeis.map((p) => (
                <option key={p} value={p}>
                  {ROTULO_PAPEL[p]}
                </option>
              ))}
            </select>
          </fieldset>
        </div>
        <div className="card-actions justify-end">
          <button type="submit" className="btn btn-primary" disabled={enviando}>
            Cadastrar
          </button>
        </div>
      </div>
    </form>
  );
}

function EditarUsuario({
  usuario,
  papeis,
  aoFechar,
  aoSalvar,
}: {
  usuario: Usuario;
  papeis: Papel[];
  aoFechar: () => void;
  aoSalvar: () => void;
}) {
  const { tratarErro } = useSessao();
  const [nome, setNome] = useState(usuario.nome);
  const [papel, setPapel] = useState<Papel>(usuario.papel);
  const [ativo, setAtivo] = useState(usuario.ativo);
  const [erro, setErro] = useState<string | null>(null);
  const travado = usuario.superadmin; // sempre admin e ativo: só o nome muda (só ele mesmo abre esta tela)

  async function salvar(evento: FormEvent) {
    evento.preventDefault();
    try {
      await chamarApi<Usuario>(`/api/usuarios/${usuario.id}`, { metodo: "PATCH", corpo: { nome, papel, ativo } });
      aoSalvar();
    } catch (e) {
      setErro(tratarErro(e));
    }
  }

  return (
    <div className="modal modal-open" role="dialog" aria-modal="true" aria-labelledby="titulo-editar">
      <form className="modal-box space-y-2" onSubmit={salvar}>
        <h2 id="titulo-editar" className="text-lg font-bold">
          Editar {usuario.nome}
        </h2>
        {erro && (
          <div role="alert" className="alert alert-error">
            {erro}
          </div>
        )}
        <fieldset className="fieldset">
          <label className="fieldset-legend" htmlFor="editar-nome">
            Nome
          </label>
          <input
            id="editar-nome"
            className="input w-full"
            required
            maxLength={80}
            value={nome}
            onChange={(e) => setNome(e.target.value)}
          />
        </fieldset>
        <fieldset className="fieldset">
          <label className="fieldset-legend" htmlFor="editar-papel">
            Papel
          </label>
          <select
            id="editar-papel"
            className="select w-full"
            value={papel}
            disabled={travado}
            onChange={(e) => setPapel(e.target.value as Papel)}
          >
            {papeis.map((p) => (
              <option key={p} value={p}>
                {ROTULO_PAPEL[p]}
              </option>
            ))}
          </select>
        </fieldset>
        <label className="label gap-2" htmlFor="editar-ativo">
          <input
            id="editar-ativo"
            type="checkbox"
            className="toggle toggle-success"
            checked={ativo}
            disabled={travado}
            onChange={(e) => setAtivo(e.target.checked)}
          />
          Ativo (desativar encerra as sessões na hora)
        </label>
        {travado && <p className="text-sm opacity-70">O superadmin é sempre admin e ativo.</p>}
        <div className="modal-action">
          <button type="button" className="btn" onClick={aoFechar}>
            Cancelar
          </button>
          <button type="submit" className="btn btn-primary">
            Salvar
          </button>
        </div>
      </form>
    </div>
  );
}

function SessoesDoUsuario({ usuario, aoFechar }: { usuario: Usuario; aoFechar: () => void }) {
  const { tratarErro } = useSessao();
  const [sessoes, setSessoes] = useState<SessaoAparelho[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    try {
      const resposta = await chamarApi<{ sessoes: SessaoAparelho[] }>(`/api/usuarios/${usuario.id}/sessoes`);
      setSessoes(resposta.sessoes);
    } catch (e) {
      setErro(tratarErro(e));
    }
  }, [usuario.id, tratarErro]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  async function encerrar(id: number) {
    try {
      await chamarApi(`/api/sessoes/${id}/encerrar`, { metodo: "POST" });
      await carregar();
    } catch (e) {
      setErro(tratarErro(e));
    }
  }

  return (
    <div className="modal modal-open" role="dialog" aria-modal="true" aria-labelledby="titulo-sessoes">
      <div className="modal-box space-y-2">
        <h2 id="titulo-sessoes" className="text-lg font-bold">
          Sessões de {usuario.nome}
        </h2>
        {erro && (
          <div role="alert" className="alert alert-error">
            {erro}
          </div>
        )}
        {sessoes === null ? (
          <span className="loading loading-spinner" aria-label="Carregando" />
        ) : sessoes.length === 0 ? (
          <p>Nenhuma sessão aberta.</p>
        ) : (
          <ul className="list">
            {sessoes.map((s) => (
              <li key={s.id} className="list-row items-center">
                <div className="list-col-grow">
                  <div>
                    {s.aparelho}
                    {s.atual && <span className="badge badge-info badge-sm ml-2">esta sessão</span>}
                  </div>
                  <div className="text-xs opacity-70">Último uso: {dataHora(s.ultimo_uso_em)}</div>
                </div>
                <button type="button" className="btn btn-error btn-xs" onClick={() => void encerrar(s.id)}>
                  Encerrar
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="modal-action">
          <button type="button" className="btn" onClick={aoFechar}>
            Fechar
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Acessos**

Crie `web/src/paginas/Acessos.tsx`:

```tsx
// Gestão → Acessos: grade papel × permissão. Cada toggle salva na hora (PUT /api/acessos); a coluna do admin é
// travada (o admin tem sempre tudo). A API avisa o grupo admin no WhatsApp a cada mudança.
import { useCallback, useEffect, useState } from "react";
import { chamarApi } from "../api";
import { useSessao } from "../sessao";
import type { GradeAcessos, Papel, Permissao } from "../tipos";

export function Acessos() {
  const { tratarErro, recarregar } = useSessao();
  const [grade, setGrade] = useState<GradeAcessos | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [mensagem, setMensagem] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    try {
      setGrade(await chamarApi<GradeAcessos>("/api/acessos"));
    } catch (e) {
      setErro(tratarErro(e));
    }
  }, [tratarErro]);

  useEffect(() => {
    void carregar();
  }, [carregar]);

  async function trocar(papel: Papel, permissao: Permissao, permitido: boolean) {
    setSalvando(true);
    setMensagem(null);
    setErro(null);
    try {
      const corpo = { mudancas: [{ papel, permissao, permitido }] };
      setGrade(await chamarApi<GradeAcessos>("/api/acessos", { metodo: "PUT", corpo }));
      setMensagem("Salvo. Vale na próxima ação de quem já está logado.");
      await recarregar(); // se a mudança foi no seu papel, o menu muda já
    } catch (e) {
      setErro(tratarErro(e));
    } finally {
      setSalvando(false);
    }
  }

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold">Acessos</h1>
      <p className="text-sm opacity-70">
        O que cada papel pode fazer. O admin tem sempre tudo. Cada mudança vale na hora e avisa o grupo admin no WhatsApp.
      </p>
      {mensagem && (
        <div role="status" className="alert alert-success">
          {mensagem}
        </div>
      )}
      {erro && (
        <div role="alert" className="alert alert-error">
          {erro}
        </div>
      )}
      {grade === null ? (
        <span className="loading loading-spinner" aria-label="Carregando" />
      ) : (
        <div className="overflow-x-auto rounded-box bg-base-100 shadow-sm">
          <table className="table">
            <thead>
              <tr>
                <th>Permissão</th>
                {grade.papeis.map((p) => (
                  <th key={p.papel} className="text-center">
                    {p.rotulo}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {grade.permissoes.map((linha) => (
                <tr key={linha.permissao}>
                  <td>
                    <div className="font-medium">{linha.rotulo}</div>
                    <div className="text-xs opacity-70">{linha.descricao}</div>
                  </td>
                  {grade.papeis.map((p) => (
                    <td key={p.papel} className="text-center">
                      <input
                        type="checkbox"
                        className="toggle toggle-success"
                        aria-label={`${p.rotulo}: ${linha.rotulo}`}
                        checked={linha.valores[p.papel]}
                        disabled={!p.editavel || salvando}
                        onChange={(e) => void trocar(p.papel, linha.permissao, e.target.checked)}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
```

(`aria-label` é texto, não classe: a regra das classes literais continua valendo.)

- [ ] **Step 4: Rotas**

Em `web/src/App.tsx`, acrescente os imports `import { Acessos } from "./paginas/Acessos";` e `import { Usuarios } from "./paginas/Usuarios";` e, dentro de `<Route path="/gestao" ...>`, depois de `<Route index element={<Gestao />} />`:

```tsx
          <Route
            path="usuarios"
            element={
              <Exige permissao="gerir_usuarios">
                <Usuarios />
              </Exige>
            }
          />
          <Route
            path="acessos"
            element={
              <Exige permissao="gerir_acessos">
                <Acessos />
              </Exige>
            }
          />
```

- [ ] **Step 5: Testes e build**

Run (em `web/`): `npm test` e `npm run build`
Expected: tudo verde (os testes da Task 7 continuam passando).

- [ ] **Step 6: Commit**

```bash
git add web/src
git commit -m "feat: users and role grid screens in the management area"
```

---

### Task 9: Containers `api` e `web` (Caddy)

**Files:**
- Create: `web/Dockerfile`, `web/Caddyfile`, `web/.dockerignore`
- Modify: `docker-compose.yml` (serviços `api` e `web`), `.dockerignore` (raiz: tira `web` do contexto da imagem Python)

**Interfaces:**
- Consumes: `tcg-sniper api --host --porta` (Task 6; aqui só o texto do comando); o build do front (`npm run build` → `web/dist/`, Tasks 7–8).
- Produces: serviço `api` (imagem `tcg-sniper`, `tcg-sniper api --host 0.0.0.0 --porta 8100`, `127.0.0.1:8100:8100`, depois do `migrate`; a `SEGREDO_API` chega pelo `env_file: .env` do `x-app`, nada a acrescentar no compose — sem ela o container sai com a mensagem de `SegredoAusente`); serviço `web` (imagem `tcg-sniper-web`, Caddy em `:8090`, `127.0.0.1:8090:8090`; `/api/*` → `{$API_ALVO:api:8100}`; o resto: arquivos do build com volta para `index.html`).

- [ ] **Step 1: Caddy e imagem do front**

Crie `web/Caddyfile`:

```caddyfile
# Serviço `web`: serve o build do front (Vite) e repassa /api para o serviço api (mesma origem: sem CORS).
# API_ALVO muda o destino (padrão: api:8100, o nome do serviço na rede do compose).
{
	admin off
	auto_https off
}

:8090 {
	encode gzip

	handle /api/* {
		reverse_proxy {$API_ALVO:api:8100}
	}

	handle {
		root * /srv
		try_files {path} /index.html
		file_server
	}

	header {
		X-Content-Type-Options nosniff
		X-Frame-Options DENY
		Referrer-Policy same-origin
	}
}
```

Crie `web/Dockerfile`:

```dockerfile
# Build do front (Vite) numa etapa com Node; a imagem final é só o Caddy com os arquivos prontos.
FROM node:24.4.1-alpine AS build
WORKDIR /web
COPY package.json package-lock.json .npmrc ./
RUN npm ci
COPY . .
RUN npm run build

FROM caddy:2.10.0-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv
EXPOSE 8090
```

Crie `web/.dockerignore`:

```
node_modules
dist
*.test.ts
*.test.tsx
```

(Os testes ficam de fora da imagem, mas o `tsc` do build não precisa deles: o `include` é `src` e o que faltar só deixa de ser conferido. Se o `tsc` reclamar de `src/teste/`, acrescente `src/teste` também ao `.dockerignore`.)

Na raiz, acrescente ao `.dockerignore` uma linha `web` (a imagem Python não precisa do front nem do `node_modules`).

- [ ] **Step 2: Compose**

Em `docker-compose.yml`, depois do serviço `admin`, acrescente:

```yaml
  # API do front novo (JSON, login pelo WhatsApp). Só no 127.0.0.1: quem fala com ela de fora é o Caddy (web).
  api:
    <<: *app
    command: tcg-sniper api --host 0.0.0.0 --porta 8100
    ports:
      - "127.0.0.1:8100:8100"
    depends_on:
      migrate:
        condition: service_completed_successfully

  # Front novo (React): Caddy serve o build e repassa /api para o serviço api.
  web:
    build: ./web
    image: tcg-sniper-web
    ports:
      - "127.0.0.1:8090:8090"
    depends_on:
      - api
    restart: unless-stopped
```

- [ ] **Step 3: Conferir sem tocar na produção**

Tudo daqui roda no worktree, com nomes próprios; nada de `docker compose up/build`.

Run:
```bash
cp .env.example .env   # só no worktree (o .env é ignorado pelo git); apague no Step 4
docker compose -p tcg-verificacao config --quiet && echo compose-ok
docker build -t tcg-sniper-web:verificacao web
docker run --rm tcg-sniper-web:verificacao caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker run -d --name tcg-web-verificacao -p 127.0.0.1:18090:8090 -e API_ALVO=127.0.0.1:1 tcg-sniper-web:verificacao
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18090/
curl -s http://127.0.0.1:18090/gestao/usuarios | grep -c 'id="raiz"'
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18090/api/saude
```
Expected: `compose-ok`; o build termina; `Valid configuration`; `200`; `1` (a rota do React volta para o `index.html`); `502` (sem API atrás: o front mostraria "Sistema indisponível").

- [ ] **Step 4: Limpar o que a verificação criou**

Run:
```bash
docker rm -f tcg-web-verificacao
docker image rm tcg-sniper-web:verificacao
rm .env
```
Expected: o container e a imagem de verificação somem; `git status` não mostra `.env`.

- [ ] **Step 5: Commit**

```bash
git add web/Dockerfile web/Caddyfile web/.dockerignore docker-compose.yml .dockerignore
git commit -m "feat: api and web compose services with caddy serving the front"
```

---

### Task 10: Ponta a ponta, layout, regra de log, README e pendências

**Files:**
- Create: `tests/e2e/test_ponta_a_ponta.py`
- Modify: `scripts/verificar_layout.py` (telas do front novo)
- Modify: `tests/avisos/test_regras_globais.py` (log nunca leva número, código ou token cru)
- Modify: `.gitignore` (`.playwright-navegadores/`), `README.md`, `docs/PENDENCIAS.md`

**Interfaces:**
- Consumes: tudo das Tasks 1–9. Em especial: `tcg-sniper api --porta` (Task 6), o build do front e o proxy do `vite preview` com `API_ALVO` (Task 7), os rótulos "Número do WhatsApp", "Receber código", "Código", "Entrar", títulos "Área de negócio", "Sem acesso", "Gestão", toggle "Grupo: Entrar na área de gestão", mensagem "Salvo. ..." (Tasks 7–8), `repo_acesso.criar_usuario` e `criar_superadmin` (Task 1), `fakes_api.SEGREDO_TESTE` (Task 3), o texto do código `*dddddd*` na fila individual (Tasks 2 e 4).
- Produces: `scripts/verificar_layout.py` com `TELAS_WEB = ["/", "/gestao", "/gestao/usuarios", "/gestao/acessos", "/sem-acesso"]`, `entrar_no_web(navegador, base: str, numero: str, codigo: str) -> dict` (estado do navegador com o cookie) e `verificar_web(navegador, base: str, estado: dict, saida: Path) -> list[str]` (problemas); variáveis `WEB_BASE`, `WEB_NUMERO`, `WEB_CODIGO`, `SO_WEB`.

- [ ] **Step 1: Banco da lane e Chromium local**

Run (no worktree, Git Bash):
```bash
docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_t10
export PLAYWRIGHT_BROWSERS_PATH="$(pwd -W)/.playwright-navegadores"
uv run playwright install chromium
(cd web && npm ci && npm run build)
```
Expected: o Chromium baixa em `.playwright-navegadores/` dentro do worktree; `web/dist/index.html` existe.

Acrescente ao `.gitignore`:

```gitignore

# Chromium do Playwright para o teste ponta a ponta (PLAYWRIGHT_BROWSERS_PATH).
.playwright-navegadores/
```

- [ ] **Step 2: `verificar_layout.py` com o front novo**

Troque `scripts/verificar_layout.py` inteiro por:

```python
"""Confere o layout das telas do admin e do front novo em 390 e 1440 px, nos temas winter e night.

Admin (precisa do Chromium do Playwright e da senha do admin), dentro do container do admin:
  docker compose exec -T admin python - < scripts/verificar_layout.py

Front novo (serviço web): passe o número de um usuário e um código válido (vale uma vez, por 5 min):
  docker compose exec api tcg-sniper codigo-acesso "<número>"
  docker compose exec -T -e WEB_NUMERO="<número>" -e WEB_CODIGO=<código> admin python - < scripts/verificar_layout.py
Sem WEB_NUMERO/WEB_CODIGO só o admin é conferido; com SO_WEB=1, só o front. WEB_BASE muda o endereço do front
(padrão http://web:8090, o serviço na rede do compose).

Para apontar para outro admin, defina ADMIN_BASE (padrão http://127.0.0.1:8000), por exemplo:
  docker compose exec -T -e ADMIN_BASE=http://host.docker.internal:8010 admin python - < scripts/verificar_layout.py

No computador, cada tela do admin roda também com o menu recolhido (localStorage "menu" = "recolhido").
Falha (código 1) se alguma tela estourar a largura da janela ou tiver erro de script.
Elementos com rolagem horizontal própria (fora das tabelas em .overflow-x-auto) saem como avisos, sem falhar.
Salva os prints em <pasta temporária>/verificar_layout/ (no container: /tmp/verificar_layout; docker cp para ver).
"""

import os
import re
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ADMIN_BASE", "http://127.0.0.1:8000")
WEB_BASE = os.environ.get("WEB_BASE", "http://web:8090")
FIXAS = [
    "/", "/servicos", "/catalogo", "/casamentos?situacao=todos", "/ofertas", "/mensagens", "/configuracoes", "/configuracoes?msg=avisos",
    "/logs", "/logs?aba=amazon", "/logs?aba=ia", "/logs?aba=checkout", "/logs?aba=monitor", "/logs?aba=manutencao",
]
TELAS_WEB = ["/", "/gestao", "/gestao/usuarios", "/gestao/acessos", "/sem-acesso"]
TELAS_WEB_ANONIMAS = ["/entrar"]
TAMANHOS = {"celular": (390, 844), "computador": (1440, 900)}
SAIDA = Path(tempfile.gettempdir()) / "verificar_layout"
MENUS = {"expandido": None, "recolhido": "recolhido"}  # o menu recolhido só existe no computador

ROLAGEM_INTERNA = r"""() => [...document.querySelectorAll('body *')]
  .filter(e => e.scrollWidth > e.clientWidth + 1 && ['auto', 'scroll'].includes(getComputedStyle(e).overflowX)
    && !e.classList.contains('overflow-x-auto'))
  .map(e => e.tagName.toLowerCase() + (typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/ +/).join('.') : ''))
"""


def descobrir(pagina) -> list[str]:
    """Telas que dependem de um id: o primeiro produto de Casamentos e o primeiro anúncio pendente."""
    extras = []
    pagina.goto(BASE + "/casamentos?situacao=todos")
    abrir = pagina.locator('a:has-text("Abrir")').first
    if abrir.count():
        href = abrir.get_attribute("href")
        extras.append(href)
        pagina.goto(BASE + href)
        trocar = pagina.locator('a[href$="/trocar"]').first
        if trocar.count():
            extras.append(trocar.get_attribute("href"))
    pagina.goto(BASE + "/ofertas")
    produto = pagina.locator('a[href^="/produto/"]').first
    if produto.count():
        extras.append(produto.get_attribute("href"))
    return extras


def conferir(pagina, url: str, caminho: str, largura: int, rotulo: str, png: Path, erros: list[str]) -> list[str]:
    """Abre a tela, salva o print e devolve os problemas (HTTP, largura estourada, erro de script)."""
    erros.clear()
    resposta = pagina.goto(url, wait_until="networkidle")
    largura_doc = pagina.evaluate("document.documentElement.scrollWidth")
    pagina.screenshot(path=str(png), full_page=True)
    problemas = []
    if resposta.status != 200:
        problemas.append(f"{caminho} {rotulo}: HTTP {resposta.status}")
    if largura_doc > largura:
        problemas.append(f"{caminho} {rotulo}: largura {largura_doc} > {largura}")
    if erros:
        problemas.append(f"{caminho} {rotulo}: erro de script {erros}")
    return problemas


def _nome_png(caminho: str, sufixo: str, prefixo: str = "") -> str:
    arquivo = re.sub(r"[^a-z0-9]+", "-", caminho.lower()).strip("-") or "dashboard"
    return f"{prefixo}{arquivo}-{sufixo}.png"


def verificar_admin(navegador, problemas: list[str], avisos: list[str]) -> None:
    credenciais = {"username": "admin", "password": os.environ["ADMIN_SENHA"]}
    for nome_tam, (largura, altura) in TAMANHOS.items():
        for menu, valor_menu in MENUS.items():
            if valor_menu and nome_tam != "computador":
                continue
            for tema in ("winter", "night"):
                contexto = navegador.new_context(viewport={"width": largura, "height": altura}, http_credentials=credenciais)
                contexto.add_init_script(f"try {{ localStorage.setItem('tema', '{tema}'); }} catch (e) {{}}")
                if valor_menu:
                    contexto.add_init_script(f"try {{ localStorage.setItem('menu', '{valor_menu}'); }} catch (e) {{}}")
                pagina = contexto.new_page()
                erros: list[str] = []
                pagina.on("pageerror", lambda e, acumulado=erros: acumulado.append(str(e)))
                rotulo = f"{nome_tam} {tema}" + (f" menu {menu}" if valor_menu else "")
                sufixo = f"{nome_tam}-{tema}" + (f"-{menu}" if valor_menu else "")
                for caminho in FIXAS + descobrir(pagina):
                    png = SAIDA / _nome_png(caminho, sufixo)
                    problemas += conferir(pagina, BASE + caminho, caminho, largura, rotulo, png, erros)
                    if valor_menu:
                        for elemento in pagina.evaluate(ROLAGEM_INTERNA):
                            avisos.append(f"{caminho} {rotulo}: rolagem horizontal interna em {elemento}")
                contexto.close()


def entrar_no_web(navegador, base: str, numero: str, codigo: str) -> dict:
    """Entra uma vez pela API (o código vale uma vez) e devolve o estado do navegador com o cookie da sessão."""
    contexto = navegador.new_context()
    try:
        resposta = contexto.request.post(base + "/api/auth/entrar", data={"numero": numero, "codigo": codigo})
        if not resposta.ok:
            raise SystemExit(f"não consegui entrar no front: HTTP {resposta.status} (o código vale 5 min e uma vez só)")
        return contexto.storage_state()
    finally:
        contexto.close()


def verificar_web(navegador, base: str, estado: dict, saida: Path) -> list[str]:
    """Telas do front novo: /entrar sem sessão e as demais com a sessão de `estado`, nos dois tamanhos e temas."""
    saida.mkdir(parents=True, exist_ok=True)
    problemas: list[str] = []
    for nome_tam, (largura, altura) in TAMANHOS.items():
        for tema in ("winter", "night"):
            for logado, telas in ((False, TELAS_WEB_ANONIMAS), (True, TELAS_WEB)):
                contexto = navegador.new_context(
                    viewport={"width": largura, "height": altura}, storage_state=estado if logado else None
                )
                contexto.add_init_script(f"try {{ localStorage.setItem('tema', '{tema}'); }} catch (e) {{}}")
                pagina = contexto.new_page()
                erros: list[str] = []
                pagina.on("pageerror", lambda e, acumulado=erros: acumulado.append(str(e)))
                rotulo = f"web {nome_tam} {tema}"
                for caminho in telas:
                    png = saida / _nome_png(caminho, f"{nome_tam}-{tema}", "web-")
                    problemas += conferir(pagina, base + caminho, caminho, largura, rotulo, png, erros)
                contexto.close()
    return problemas


def main() -> None:
    SAIDA.mkdir(exist_ok=True)
    problemas: list[str] = []
    avisos: list[str] = []
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        if os.environ.get("SO_WEB") != "1":
            verificar_admin(navegador, problemas, avisos)
        numero, codigo = os.environ.get("WEB_NUMERO"), os.environ.get("WEB_CODIGO")
        if numero and codigo:
            estado = entrar_no_web(navegador, WEB_BASE, numero, codigo)
            problemas += verificar_web(navegador, WEB_BASE, estado, SAIDA)
        navegador.close()
    if avisos:
        print("avisos:\n" + "\n".join(sorted(set(avisos))))
    print("\n".join(problemas) or "layout ok")
    sys.exit(1 if problemas else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Teste ponta a ponta**

Crie `tests/e2e/test_ponta_a_ponta.py`:

```python
"""Ponta a ponta: a API (uvicorn) e o build do front (servido pelo `vite preview`, que repassa /api como o Caddy)
contra o banco de teste. O usuário pede o código, o teste lê o código na fila e entra; o papel grupo não entra na
gestão até a grade liberar `ver_area_gestao`. Também confere o layout das telas novas.

Só roda com TCG_E2E=1; antes: `cd web && npm ci && npm run build` e `uv run playwright install chromium`
(com PLAYWRIGHT_BROWSERS_PATH apontando para .playwright-navegadores/ do checkout). Os dois servidores são
parados no fim, passe ou falhe."""

import importlib.util
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from fakes_api import SEGREDO_TESTE
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Papel
from tcg_sniper.db.repositorio import agora_utc

pytestmark = pytest.mark.skipif(os.environ.get("TCG_E2E") != "1", reason="ponta a ponta: rode com TCG_E2E=1")

RAIZ = Path(__file__).resolve().parents[2]
PORTA_API, PORTA_WEB = 8101, 4174
BASE = f"http://127.0.0.1:{PORTA_WEB}"
ADMIN, GRUPO = "+5511900000001", "+5511900000002"
TABELAS = "sessao, codigo_acesso, pedido_codigo, permissao_papel, mensagem_saida, estado_aviso, usuario"


def esperar(url: str, limite_s: float = 40) -> None:
    fim = time.monotonic() + limite_s
    while time.monotonic() < fim:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"{url} não respondeu em {limite_s:.0f} s")


def parar(processo: subprocess.Popen) -> None:
    processo.terminate()
    try:
        processo.wait(timeout=10)
    except subprocess.TimeoutExpired:
        processo.kill()
        processo.wait(timeout=10)


@pytest.fixture(scope="module")
def servidores(engine):
    if not (RAIZ / "web" / "dist" / "index.html").exists():
        pytest.fail("falta o build do front: cd web && npm ci && npm run build")
    ambiente = {
        **os.environ,
        "DATABASE_URL": engine.url.render_as_string(hide_password=False),
        "SEGREDO_API": SEGREDO_TESTE,  # segredo falso; nunca o do .env
        "API_ALVO": f"http://127.0.0.1:{PORTA_API}",
    }
    codigo_api = f"from tcg_sniper.cli import main; main(['api', '--porta', '{PORTA_API}'])"
    api = subprocess.Popen([sys.executable, "-c", codigo_api], cwd=RAIZ, env=ambiente)
    vite = RAIZ / "web" / "node_modules" / "vite" / "bin" / "vite.js"
    web = subprocess.Popen(
        ["node", str(vite), "preview", "--host", "127.0.0.1", "--port", str(PORTA_WEB), "--strictPort"],
        cwd=RAIZ / "web", env=ambiente,
    )
    try:
        esperar(f"http://127.0.0.1:{PORTA_API}/api/saude")
        esperar(f"{BASE}/api/saude")
        yield BASE
    finally:
        parar(web)
        parar(api)


@pytest.fixture
def usuarios(engine):
    """Superadmin e grupo gravados de verdade (a API roda em outro processo); tudo apagado no fim."""
    with sessionmaker(bind=engine)() as s, s.begin():
        repo_acesso.criar_superadmin(s, "Pessoa Admin", ADMIN, agora_utc())
        repo_acesso.criar_usuario(s, "Pessoa Grupo", GRUPO, Papel.GRUPO, agora_utc())
    yield
    with engine.begin() as conexao:
        conexao.execute(text(f"TRUNCATE {TABELAS} RESTART IDENTITY CASCADE"))


def ler_codigo(engine, numero: str) -> str:
    with engine.connect() as conexao:
        texto = conexao.execute(
            text(
                "SELECT texto FROM mensagem_saida WHERE destino = 'individual' AND numero = :numero "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"numero": numero},
        ).scalar_one()
    return re.search(r"\*(\d{6})\*", texto).group(1)


def entrar(pagina, expect, engine, numero: str, digitado: str) -> None:
    pagina.goto(BASE + "/entrar")
    pagina.get_by_label("Número do WhatsApp").fill(digitado)
    pagina.get_by_role("button", name="Receber código").click()
    campo = pagina.get_by_label("Código", exact=True)
    expect(campo).to_be_visible()  # o pedido terminou: o código já está na fila
    campo.fill(ler_codigo(engine, numero))
    pagina.get_by_role("button", name="Entrar", exact=True).click()


def test_grupo_so_entra_na_gestao_depois_de_liberado(servidores, usuarios, engine):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        try:
            grupo = navegador.new_context().new_page()
            entrar(grupo, expect, engine, GRUPO, "(11) 90000-0002")
            expect(grupo.get_by_role("heading", name="Área de negócio")).to_be_visible()
            grupo.goto(BASE + "/gestao")
            expect(grupo.get_by_role("heading", name="Sem acesso")).to_be_visible()
            assert grupo.request.get(BASE + "/api/usuarios").status == 403  # direto na API também

            admin = navegador.new_context().new_page()
            entrar(admin, expect, engine, ADMIN, "11 90000-0001")
            admin.goto(BASE + "/gestao/acessos")
            toggle = admin.get_by_label("Grupo: Entrar na área de gestão")
            expect(toggle).not_to_be_checked()
            toggle.click()
            expect(admin.get_by_text("Salvo. Vale na próxima ação de quem já está logado.")).to_be_visible()
            expect(toggle).to_be_checked()

            grupo.goto(BASE + "/gestao")
            expect(grupo.get_by_role("heading", name="Gestão", exact=True)).to_be_visible()
        finally:
            navegador.close()


def _verificar_layout():
    spec = importlib.util.spec_from_file_location("verificar_layout", RAIZ / "scripts" / "verificar_layout.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_telas_novas_cabem_na_tela_nos_dois_temas(servidores, usuarios, engine, tmp_path):
    from playwright.sync_api import sync_playwright

    httpx.post(BASE + "/api/auth/pedir-codigo", json={"numero": ADMIN}, timeout=10).raise_for_status()
    layout = _verificar_layout()
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        try:
            estado = layout.entrar_no_web(navegador, BASE, ADMIN, ler_codigo(engine, ADMIN))
            problemas = layout.verificar_web(navegador, BASE, estado, tmp_path)
        finally:
            navegador.close()
    assert problemas == []
```

Run:
```bash
export PLAYWRIGHT_BROWSERS_PATH="$(pwd -W)/.playwright-navegadores"
TCG_E2E=1 DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t10 uv run pytest tests/e2e -q -p no:cacheprovider
```
Expected: 2 passed. Depois, confira que não sobrou servidor: `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8101/api/saude` deve falhar (`000`). Se sobrou (teste interrompido à força), encerre o processo pela porta (`netstat -ano | grep 8101` e `taskkill //F //PID <pid>`; o mesmo para a 4174).

Sem `TCG_E2E=1` os dois testes aparecem como `skipped` na suíte normal.

- [ ] **Step 4: Regra global — log sem número, código ou token cru**

Em `tests/avisos/test_regras_globais.py`, acrescente no fim:

```python
SENSIVEIS = {"numero", "codigo", "token", "hash_codigo", "hash_token"}
MASCARAS = {"mascarar_numero", "ocultar_numero"}
NIVEIS = {"debug", "info", "warning", "error", "exception", "critical"}


def _nome_chamado(no: ast.AST) -> str:
    if isinstance(no, ast.Name):
        return no.id
    if isinstance(no, ast.Attribute):
        return no.attr
    return ""


def _cru(argumento: ast.AST) -> bool:
    if isinstance(argumento, ast.Call) and _nome_chamado(argumento.func) in MASCARAS:
        return False
    nomes = {n.id for n in ast.walk(argumento) if isinstance(n, ast.Name)}
    nomes |= {n.attr for n in ast.walk(argumento) if isinstance(n, ast.Attribute)}
    return bool(nomes & SENSIVEIS)


def test_log_nunca_leva_numero_codigo_ou_token_cru():
    """Número só vai para log mascarado (`mascarar_numero`/`ocultar_numero`); código e token, nunca."""
    problemas = []
    for caminho in arquivos():
        for no in ast.walk(ast.parse(caminho.read_text(encoding="utf-8"))):
            if not (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) and no.func.attr in NIVEIS):
                continue
            alvo = no.func.value
            if not (isinstance(alvo, ast.Name) and alvo.id in {"log", "logging", "logger"}):
                continue
            argumentos = [*no.args[1:], *(k.value for k in no.keywords)]
            if any(_cru(a) for a in argumentos):
                problemas.append(f"{caminho.name}:{no.lineno}")
    assert problemas == []
```

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t10 uv run pytest tests/avisos/test_regras_globais.py -q -p no:cacheprovider`
Expected: PASS. (Se acusar um log antigo fora do login que use uma variável com um desses nomes sem dado pessoal, renomeie a variável no código, não afrouxe a regra.)

- [ ] **Step 5: README**

Em `README.md`:

1. No passo a passo da instalação, depois da seção "### 10. Monitor de preço e conferência de checkout", acrescente:

````markdown
### 11. Site novo (front) e login pelo WhatsApp

O site novo roda em dois containers: `api` (JSON, em `127.0.0.1:8100`) e `web` (o site, em `http://localhost:8090`). O admin antigo continua em `:8000` até as telas mudarem para cá.

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # cole o resultado em SEGREDO_API no .env
docker compose up -d --build api web
docker compose exec api tcg-sniper criar-superadmin "Seu nome" "(DDD) seu número"
```

Sem `SEGREDO_API` no `.env` (ou com o valor de exemplo) a `api` não sobe e diz o que fazer. Trocar essa chave derruba todas as sessões: todos entram de novo pelo código.

Abra `http://localhost:8090`, digite o seu número e o código que chega no WhatsApp (vale 5 minutos). Você é o superadmin: o único que cria, edita, rebaixa ou desativa admins, e ninguém (nem você) o rebaixa ou desativa pelo site. Em Gestão → Usuários cadastre as outras pessoas com o papel de cada uma (grupo, operador ou admin); admins comuns gerenciam só operadores e grupo. Em Gestão → Acessos escolha o que cada papel pode fazer (o admin pode tudo, sempre). Toda mudança de usuário ou de acesso avisa o grupo admin. Para passar o superadmin a outra pessoa já cadastrada (ex.: número novo): `docker compose exec api tcg-sniper trocar-superadmin "(DDD) número"` (o antigo continua admin).

Sem WhatsApp (notificador pausado, Evolution fora), gere um código no terminal: `docker compose exec api tcg-sniper codigo-acesso "(DDD) número"`.
````

2. Em "### Segurança", acrescente um parágrafo: "No site novo cada pessoa entra com o próprio número: o código de acesso vai só para o WhatsApp dela, vale 5 minutos e uma vez; 5 tentativas erradas o invalidam; no máximo 3 códigos por número a cada 15 minutos e 20 pedidos por hora no total (acima disso a tela pede para esperar e o grupo admin é avisado). O banco guarda só o HMAC (com a chave `SEGREDO_API` do `.env`) do código, do token da sessão e do número dos pedidos; o número nunca vai para log nem para o grupo (aparece mascarado, `+55 11 9****-**34`). A sessão dura 30 dias, renovada a cada uso; desativar um usuário encerra as sessões dele na hora."

3. Em "## Desenvolvimento", acrescente depois do bloco de comandos:

````markdown
Front (`web/`, React + Vite + TypeScript + Tailwind + DaisyUI 5):

```bash
uv run tcg-sniper api          # API local em 127.0.0.1:8100 (usa o DATABASE_URL e a SEGREDO_API do .env)
cd web
npm ci
npm run dev                     # http://127.0.0.1:5173, com /api repassado para a API local
npm test                        # Vitest + Testing Library
npm run build                   # tsc + build em web/dist
```

Teste ponta a ponta (sobe a API e o `vite preview` contra o banco de teste e para os dois no fim):

```bash
(cd web && npm ci && npm run build)
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-navegadores"   # no Git Bash do Windows: "$(pwd -W)/.playwright-navegadores"
uv run playwright install chromium
TCG_E2E=1 DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test uv run pytest tests/e2e -q
```

Layout do site novo: `docker compose exec api tcg-sniper codigo-acesso "<número>"` e depois `docker compose exec -T -e WEB_NUMERO="<número>" -e WEB_CODIGO=<código> admin python - < scripts/verificar_layout.py` (`SO_WEB=1` pula as telas do admin).
````

4. Em "### Estrutura", acrescente as linhas `  api/                API do site novo (FastAPI, JSON): login pelo WhatsApp, sessões, permissões por papel` (dentro de `src/tcg_sniper/`) e, fora dela, `web/                  site novo (React + Vite + DaisyUI), servido pelo Caddy no container web`; e em `cli.py` acrescente `api, codigo-acesso, criar-superadmin, trocar-superadmin` à lista de comandos.

- [ ] **Step 6: Pendências**

Em `docs/PENDENCIAS.md`:

1. Atualize a linha `Última revisão:` para a data do merge.
2. Em "## 1. Pequenas", acrescente:
   - `- [ ] Sessões encerradas ou vencidas nunca são apagadas (pedidos e códigos são, depois de 1 dia). Pouco volume com < 20 pessoas; limpar na manutenção quando crescer.`
   - `- [ ] O texto do código de acesso fica na fila (mensagem_saida) enquanto está pendente (até 5 min), visível em Admin → Mensagens. Some ao sair da fila; some de vez quando o admin antigo for desligado (fase 4).`
3. Em "## 3. Próximas funcionalidades", acrescente no topo:
   - `- [ ] **Site novo, fase 2 — área de negócio**: dashboard do grupo (oportunidades, funil, resultados), com as permissões ver_oportunidades e ver_resultados.`
   - `- [ ] **Site novo, fase 3 — área administrativa**: migrar as telas do admin antigo (com as correções da auditoria de layout) e as permissões revisar_casamentos, ver_catalogo, editar_catalogo, ver_servicos, pausar_servicos, ver_logs, ver_mensagens, reenviar_mensagens, ver_configuracoes, editar_configuracoes.`
   - `- [ ] **Site novo, fase 4 — desligar o admin antigo.**`
4. Em "## Concluídas", acrescente no topo:

```markdown
### Site novo, fase 1 — base (2026-10-18)

- [x] Serviço `api` (FastAPI, JSON, `127.0.0.1:8100`): erros padronizados, `/api/saude`, `/api/docs` com permissão, toda rota declara a permissão que exige (`exige(...)`), grade papel × permissão com cache de 5 s.
- [x] Login pelo WhatsApp: código de 6 dígitos só para o número da pessoa (validade própria de 5 min na fila; vencido não sai), 5 tentativas, limites de 3 por número/15 min e 20/hora, mesma resposta para número sem cadastro; cookie `sessao` HttpOnly/SameSite=Strict; código, token e número só como HMAC-SHA256 com `SEGREDO_API` (a api não sobe sem ela); acesso de emergência `tcg-sniper codigo-acesso`.
- [x] Superadmin único (`tcg-sniper criar-superadmin` e `trocar-superadmin`, só no terminal): o único que mexe em admins; nunca rebaixado, desativado nem encerrado pelo site.
- [x] Avisos novos: `CODIGO_ACESSO` (individual), `SEGURANCA_USUARIO` e `SEGURANCA_LIMITE` (grupo admin), desligáveis na aba Avisos.
- [x] Site novo (`web/`, React + Vite + DaisyUI, Caddy em `127.0.0.1:8090`): Entrar, área de negócio (esqueleto), Gestão → Usuários e Gestão → Acessos, sem acesso e sistema indisponível; testes Vitest, ponta a ponta com Playwright e layout no `verificar_layout.py`.
```

(Anote os commits do merge quando ele acontecer, como nas outras entradas.)

- [ ] **Step 7: Suíte inteira, ruff e front**

Run:
```bash
DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t10 uv run pytest -q -p no:cacheprovider
uv run ruff check .
(cd web && npm test && npm run build)
```
Expected: tudo verde (os dois testes de `tests/e2e` como `skipped`, porque já rodaram no Step 3 com `TCG_E2E=1`).

- [ ] **Step 8: Commit**

```bash
git add tests/e2e scripts/verificar_layout.py tests/avisos/test_regras_globais.py .gitignore README.md docs/PENDENCIAS.md
git commit -m "test: end-to-end login and role grid with playwright; docs for the new front"
```

---

## Implantação (depois do merge, com ok do usuário; o controlador faz, não um subagente)

1. Backup manual antes: `docker compose exec -T postgres pg_dump -U tcg -Fc tcg > dados/backups/tcg-antes-front-api.dump`. Gerar a `SEGREDO_API` (`python -c "import secrets; print(secrets.token_urlsafe(32))"`) e pôr no `.env` de produção (sem ela a `api` não sobe).
2. `docker compose build` (imagem Python e a nova `tcg-sniper-web`) e `docker compose run --rm migrate` (aplica `f8d2a6c4e1b3`: tabelas do login com `usuario.superadmin`, `pedido_codigo` e as colunas `numero`/`expira_em` de `mensagem_saida`).
3. Restart de `notificador` e `admin` (destino individual, aba Avisos com 31 tipos) e `docker compose up -d api web`.
4. `docker compose exec api tcg-sniper criar-superadmin "<nome>" "<número>"` (o usuário roda, com o número dele); abrir `http://localhost:8090`, pedir o código, entrar; cadastrar um usuário grupo e um operador; conferir que o grupo não vê Gestão e que liberar `ver_area_gestao` em Gestão → Acessos muda isso na hora (critério de pronto do spec); conferir o aviso "Segurança · acesso alterado" no grupo admin.
5. Layout em produção: `docker compose exec api tcg-sniper codigo-acesso "<número>"` e `docker compose exec -T -e WEB_NUMERO=... -e WEB_CODIGO=... -e SO_WEB=1 admin python - < scripts/verificar_layout.py`.
6. Atualizar `docs/PENDENCIAS.md` com o commit do merge.

