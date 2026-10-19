# Front e API separados — fase 1 (base)

Data: 2026-10-18. Aprovado em conversa (brainstorming) com o usuário.

## Contexto e objetivo

Hoje o admin é um monolito: o mesmo FastAPI busca os dados, monta o HTML (Jinja2) e responde as ações (htmx), e mistura duas coisas diferentes: **acompanhar oportunidades** (negócio, de interesse do grupo) e **gerir o sistema** (serviços, casamentos, configurações, logs).

Objetivo do projeto inteiro: separar em **back** (serviço só de API, JSON) e **front** (aplicação React com duas áreas: **negócio** e **administrativa**), com login por pessoa e papéis. Tudo roda no PC do usuário, em containers, até ele validar; publicar na internet (Cloudflare Pages/Tunnel, VPS) é decisão posterior e não pode exigir reescrita.

Fases (cada uma com spec, plano e deploy próprios):

1. **Base** (este documento): serviço `api`, login pelo WhatsApp com papéis, front React com as duas áreas vazias, containers. Admin atual intacto.
2. **Área de negócio:** dashboard do grupo (oportunidades, funil, resultados).
3. **Área administrativa:** migrar as telas do admin atual (com as correções da auditoria de layout).
4. **Desligar o admin antigo.**

Fora do escopo agora: publicar na internet, pipelines de deploy por serviço, outros fronts.

## Decisões do usuário

- Separação em back (API) e front (área de negócio + área administrativa); motivo: organização e evolução, com publicação na internet depois de muitos testes locais.
- Tudo no PC, em containers (Docker Compose), até validar.
- Front: **React + Vite + TypeScript + DaisyUI** (mesma regra visual do admin: só componentes DaisyUI/utilitários Tailwind, temas winter e night). O front é mantido pelo Claude; código simples e documentado.
- Monorepo: API como módulo do pacote atual; front na pasta `web/`.
- Papéis fixos: **grupo**, **operador**, **admin**; **o que cada papel pode fazer é configurável** numa grade papel × permissão (Gestão → Acessos). O admin tem sempre todas as permissões (travado). Grupo pequeno (< 20 pessoas). Permissões finas desde já porque o projeto deve crescer para venda; papéis livres e permissão extra por pessoa ficam para depois (o modelo não pode impedir isso).
- Login por **código no WhatsApp** (o número será aquecido aos poucos).

## Arquitetura

### Serviço `api` (`src/tcg_sniper/api/`)

- FastAPI novo, só rotas `/api/...` em JSON; reaproveita `db/repositorio*.py`, `admin/consultas*.py` e demais módulos de regra (nada de regra duplicada; se algo do admin for preciso, é extraído para módulo comum).
- CLI `tcg-sniper api`; serviço `api` no `docker-compose.yml`, porta `127.0.0.1:8100`.
- Rotas da fase 1:
  - `POST /api/auth/pedir-codigo` `{numero}`; `POST /api/auth/entrar` `{numero, codigo}`; `POST /api/auth/sair`; `GET /api/auth/eu` (nome, papel).
  - `GET/POST/PATCH /api/usuarios` (`gerir_usuarios`): listar, criar, editar papel/nome/ativo; `GET /api/usuarios/{id}/sessoes` e `POST /api/sessoes/{id}/encerrar` (`gerir_usuarios`).
  - `GET/PUT /api/acessos` (`gerir_acessos`).
  - `GET /api/saude` (sem login): `{ok: true}` se o banco responde.
  - `/api/docs` (OpenAPI) com `ver_documentacao_api`.
- Cada rota declara a **permissão** que exige (dependência FastAPI `exige("<permissao>")`); o back sempre confere, lendo a grade do banco (cache curto, invalidado ao salvar).

### Permissões

- Lista fechada definida no código (`api/permissoes.py`, enum `Permissao` com rótulo e descrição para a tela); cada fase acrescenta as suas. Fase 1:
  - `ver_area_negocio` — entrar na área de negócio;
  - `ver_area_gestao` — entrar na área administrativa;
  - `gerir_usuarios` — listar/criar/editar/desativar usuários e encerrar sessões;
  - `gerir_acessos` — editar a grade papel × permissão;
  - `ver_documentacao_api` — abrir `/api/docs`.
  - Previstas para as próximas fases (entram com as telas): `ver_oportunidades`, `ver_resultados`, `revisar_casamentos`, `ver_catalogo`, `editar_catalogo`, `ver_servicos`, `pausar_servicos`, `ver_logs`, `ver_mensagens`, `reenviar_mensagens`, `ver_configuracoes`, `editar_configuracoes`.
- Tabela `permissao_papel` (`papel`, `permissao`, `permitido`; PK `papel, permissao`). Linha ausente = padrão do código.
- Padrões: **grupo** = `ver_area_negocio`; **operador** = `ver_area_negocio`, `ver_area_gestao`; **admin** = todas, sempre (não editável; a API ignora linhas do admin).
- `GET /api/acessos` (grade com rótulos) e `PUT /api/acessos` (exige `gerir_acessos`). Toda mudança gera aviso `SEGURANCA_USUARIO` no grupo admin (quem mudou, papel, permissão, novo valor).
- `GET /api/auth/eu` devolve também a lista de permissões efetivas; o front usa para montar menu e rotas.
- Erros em JSON padronizado `{erro: "<código>", mensagem: "<texto em português>"}`; 401 sem sessão, 403 papel insuficiente, 404, 422 validação, 429 limite.

### Login pelo WhatsApp

Tabelas novas (uma migração após a head atual):

- `usuario`: `id`, `nome`, `numero` (E.164, único), `papel` (`grupo`/`operador`/`admin`), `ativo`, `criado_em`.
- `codigo_acesso`: `id`, `usuario_id`, `hash_codigo`, `criado_em`, `expira_em` (5 min), `tentativas`, `usado_em`.
- `sessao`: `id`, `usuario_id`, `hash_token`, `aparelho` (user-agent resumido), `criada_em`, `ultimo_uso_em`, `expira_em` (30 dias, renovada no uso), `encerrada_em`.

Fluxo:

1. `pedir-codigo`: se o número é de um usuário ativo e está dentro dos limites, gera código de 6 dígitos (aleatório criptográfico), grava só o hash e enfileira a mensagem individual pelo módulo `avisos` (formato único, tipo novo `CODIGO_ACESSO`, destino = número da pessoa, nunca o grupo). Resposta sempre igual, exista o número ou não.
2. `entrar`: confere hash, validade e tentativas (5 erradas invalidam); cria sessão com token aleatório (só o hash no banco) e devolve cookie `sessao` `HttpOnly`, `SameSite=Strict`, `Path=/`, `Secure` quando servido em HTTPS.
3. Toda rota protegida lê o cookie, confere sessão ativa e não vencida, atualiza `ultimo_uso_em`.

Envio individual: hoje o notificador só manda para grupos. A fila (`mensagem_saida`) passa a aceitar destino individual (número) e a Evolution envia para o número; o código de acesso tem validade própria de 5 min na fila (vencido não é enviado).

Limites: até 3 códigos por número a cada 15 min; até 20 pedidos por hora no total; acima disso responde 429, registra e gera aviso `SEGURANCA_LIMITE` (grupo admin, agrupado).

Acesso de emergência: `tcg-sniper codigo-acesso <numero>` (só no PC/containers) gera e mostra no terminal um código válido para aquele usuário; `tcg-sniper criar-admin <nome> <numero>` cria o primeiro admin (falha se já houver admin, salvo `--forcar`).

Avisos novos no catálogo (desligáveis na aba Avisos): `CODIGO_ACESSO` (individual, não agrupa), `SEGURANCA_USUARIO` (usuário criado, papel alterado, desativado, permissão alterada; grupo admin), `SEGURANCA_LIMITE` (limite de pedidos atingido; agrupa por número).

Dados pessoais: números ficam só no banco; nunca em log (mascarados: `+55 11 9****-**34`), nunca no repositório, nunca no grupo. Código e token nunca em log, banco (só hash) ou mensagem de grupo.

### Serviço `web` (`web/`)

- React + Vite + TypeScript; Tailwind + DaisyUI 5 (temas winter e night, troca como no admin atual); React Router; chamadas à API com `fetch` e cookie (`credentials: "same-origin"`).
- Rotas:
  - `/entrar`: número → código → entrar.
  - `/`: área de negócio (fase 1: esqueleto com menu e link para o admin antigo).
  - `/gestao/...`: área administrativa (`ver_area_gestao`); fase 1: `/gestao/usuarios` (`gerir_usuarios`), `/gestao/acessos` (`gerir_acessos`: grade papel × permissão com toggles DaisyUI; coluna do admin travada) e links para o admin antigo nas telas ainda não migradas.
  - `/sem-acesso` (403) e tela "sistema indisponível" (API fora).
- O front esconde o que as permissões da pessoa não permitem (lista vinda de `/api/auth/eu`), mas a autorização é sempre da API.
- Container: build do Vite + Caddy servindo os estáticos e repassando `/api` para `api:8100`; porta `127.0.0.1:8090`. Desenvolvimento: `npm run dev` (Vite) com proxy para a API local.
- Mesma origem para front e API (via Caddy): sem CORS na fase 1.

### O que não muda

Coletores, casador, notificador (exceto aceitar destino individual), manutenção e o admin atual (porta 8000).

## Erros e casos de borda

- Número não cadastrado/inativo: mesma resposta de sucesso em `pedir-codigo`.
- WhatsApp fora/notificador pausado: a tela de login avisa que o código pode demorar; acesso de emergência pelo terminal.
- Código vencido na fila: não é enviado.
- Sessão vencida/encerrada: 401; front volta para `/entrar`.
- Sem a permissão: 403; front mostra `/sem-acesso`.
- Mudança na grade vale na próxima requisição de quem já está logado (sem precisar sair e entrar).
- API fora: front mostra "sistema indisponível".
- Usuário desativado: todas as sessões dele são encerradas na hora.

## Testes

- API (pytest, Postgres de teste na porta 5433): fluxo de login completo; limites; código vencido/errado/usado; sessão vencida/encerrada; cada permissão em cada rota (com a grade padrão e com a grade alterada); admin não perde permissão mesmo com linhas no banco; mesma resposta para número inexistente; emergência; desativar encerra sessões; nada de número/código/token em log.
- Front (Vitest + Testing Library): login, proteção de rotas por papel, telas de sem acesso e indisponível.
- Ponta a ponta (Playwright): sobe `api` + `web` contra o banco de teste; usuário pede código, o teste lê o código da fila, entra; papel grupo não acessa `/gestao`; depois de liberar `ver_area_gestao` para grupo na grade, passa a acessar.
- Layout: telas novas no `scripts/verificar_layout.py`.

## Critério de pronto da fase 1

1. `docker compose up -d` sobe `api` e `web`; admin antigo continua em `:8000`.
2. O usuário cria o próprio admin pelo comando, entra pelo código no WhatsApp e cadastra um usuário grupo e um operador.
3. Cada papel vê só o que suas permissões permitem (conferido também direto na API), e mudar a grade em Gestão → Acessos muda isso na hora.
4. Área de negócio: esqueleto com menu e link para o admin antigo.
