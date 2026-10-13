# Sub-projeto 1: coletor-liga, banco, admin e alerta admin

Data: 2026-10-13
Contexto: `Monitor de arbitragem de selados de Magic.md` (visão geral do sistema)

## Objetivo

Primeiro sub-projeto do monitor de arbitragem. Coletar diariamente os preços de selados de Magic na LigaMagic, guardar histórico no Postgres, permitir que o grupo escolha quais produtos monitorar por uma página de admin, e avisar um grupo de WhatsApp de administração quando a coleta precisar de intervenção humana.

Critério de sucesso: a coleta diária roda por uma semana sem desafio do Cloudflare (ou, se aparecer, o grupo admin é avisado, resolve pelo noVNC e retoma pelo admin), e o histórico de preços por produto fica consultável.

## Escopo

Dentro:

- Varredura semanal do catálogo de selados da LigaMagic.
- Coleta diária do resumo de preços (mín, médio, máx) e do número de lojas dos produtos ativos.
- Banco Postgres com catálogo, resumos de preço e estado do coletor.
- Página de admin para ativar produtos, ver status e retomar a coleta.
- Notificador com destino "admin" via WhatsApp (Evolution API).

Fora (próximas specs):

- Coletores de marketplaces (Mercado Livre, Amazon, outros).
- Matcher e fila de revisão de de-para.
- Motor de oportunidades, regras de cupom e cashback.
- Mensagens para o grupo de oportunidades.
- Migração para servidor.

## Restrições

- Cloudflare é restrição, não obstáculo: nada de solucionador de CAPTCHA nem spoofing de fingerprint. A estratégia é volume baixo, navegador real com perfil persistente, IP residencial e intervenção humana quando o desafio aparecer. Sem retry automático diante de desafio.
- Roda no PC Windows do grupo com Docker Desktop nesta fase.
- Stack: Python 3.12, `uv`, Playwright (Python), SQLAlchemy 2, Alembic, FastAPI, Jinja2, HTMX, pytest, Postgres 16. O agendamento é um laço simples de 60 segundos, não APScheduler: a API síncrona do Playwright é presa à thread que a criou.

## Arquitetura

Um repositório, um pacote Python (`tcg_sniper`), uma imagem Docker. Cada serviço roda em seu próprio container, com a mesma imagem e um comando diferente. Os serviços se comunicam apenas pelo banco.

| Container | Imagem | Comando | Portas | Função |
| --- | --- | --- | --- | --- |
| `postgres` | `postgres:16` | padrão | 5432 (local) | Banco |
| `evolution` | Evolution API (imagem e versão confirmadas na implementação) | padrão | 8080 (local) | Ponte com o WhatsApp via chip secundário |
| `migrate` | `tcg-sniper` | `tcg-sniper migrate` | — | Aplica as migrações e termina; os demais esperam por ele |
| `coletor-liga` | `tcg-sniper` | `tcg-sniper coletor-liga` | 6080 (noVNC, com senha `VNC_SENHA`) | Chromium com Xvfb; agenda e executa coletas |
| `admin` | `tcg-sniper` | `tcg-sniper admin` | 8000 | Página web de administração |

Volumes: dados do Postgres, perfil do Chromium (`/data/perfil`), HTMLs de falha (`/data/falhas`), dados da Evolution API.

### Estrutura do pacote

```
src/tcg_sniper/
  cli.py              # entrypoint: tcg-sniper coletor-liga | admin | migrate
  config.py           # pydantic-settings, lê .env
  db/
    models.py         # modelos SQLAlchemy
    session.py
    migrations/       # Alembic
  coletor_liga/
    navegador.py      # contexto Playwright persistente
    parsers.py        # HTML -> dataclasses, funções puras, sem I/O
    catalogo.py       # varredura da categoria de selados
    precos.py         # coleta diária do resumo de preços da lista ativa
    desafio.py        # detecção da página de desafio
    agendador.py      # laço de 60 s, lock, polling de solicitações
  admin/
    app.py            # FastAPI
    templates/
  notificador/
    base.py           # Destino, Protocol Notificador
    evolution.py      # implementação WhatsApp
    log.py            # implementação que só registra em log
```

Princípio: os parsers são funções puras testadas com fixtures de HTML salvas da LigaMagic. O navegador só busca HTML. A lógica é testada sem acessar a Liga.

## Banco de dados

Dinheiro em `NUMERIC(10,2)` (BRL). Datas em `timestamptz` (UTC).

### `produto_liga`

Catálogo, alimentado pela varredura semanal. Registros nunca são apagados.

| Coluna | Tipo | Nota |
| --- | --- | --- |
| `id` | serial PK | |
| `liga_id` | text UNIQUE | ID do produto na URL da Liga |
| `nome` | text | Título como aparece na Liga |
| `url` | text | |
| `edicao` | text NULL | Extraído quando disponível |
| `tipo` | text NULL | Booster box, bundle etc., quando disponível |
| `idioma` | text NULL | Quando disponível |
| `ean` | text NULL | Para o matcher da fase 2 |
| `ativo` | bool, default false | Alterado pelo admin |
| `visto_primeiro_em` | timestamptz | |
| `visto_ultimo_em` | timestamptz | Fica antigo quando o produto some da Liga |

Os campos `edicao`, `tipo` e `idioma` são confirmados ao inspecionar o HTML real.

### `coleta`

Uma linha por execução.

| Coluna | Tipo |
| --- | --- |
| `id` | serial PK |
| `tipo` | enum `catalogo`, `precos` |
| `iniciada_em` | timestamptz |
| `finalizada_em` | timestamptz NULL |
| `status` | enum `rodando`, `ok`, `parcial`, `falha`, `pausada_desafio` |
| `produtos_ok` | int |
| `produtos_falha` | int |
| `erro` | text NULL |

Status final: `ok` se nenhum produto falhou; `parcial` se falharam até 50%; `falha` se falharam mais de 50% ou houve erro geral.

### `resumo_preco`

Histórico append-only, uma linha por produto e coleta.

| Coluna | Tipo |
| --- | --- |
| `produto_id` | FK, parte da PK |
| `coleta_id` | FK, parte da PK |
| `preco_min` | numeric(10,2) NULL (NULL se a página não mostra o quadro de preços) |
| `preco_medio` | numeric(10,2) NULL |
| `preco_max` | numeric(10,2) NULL |
| `num_lojas` | int |
| `coletado_em` | timestamptz |

### `preco_atual_liga`

Dado corrente, uma linha por produto, atualizado por upsert. É a tabela que o admin e o futuro motor de oportunidades leem para o presente.

| Coluna | Tipo |
| --- | --- |
| `produto_id` | PK, FK `produto_liga` |
| `coleta_id` | FK `coleta` |
| `preco_min` | numeric(10,2) NULL |
| `preco_medio` | numeric(10,2) NULL |
| `preco_max` | numeric(10,2) NULL |
| `num_lojas` | int |
| `atualizado_em` | timestamptz |

Separação entre dado do dia e histórico: `preco_atual_liga` para o presente, `resumo_preco` para o histórico. Não existe job de virada de dia; as duas são gravadas na mesma transação.

### `estado_coletor`

Linha única.

| Coluna | Tipo |
| --- | --- |
| `estado` | enum `ativo`, `pausado_desafio` |
| `motivo` | text NULL |
| `execucao_solicitada` | bool, default false |
| `atualizado_em` | timestamptz |

## Fluxo da coleta

### Navegador

Playwright com `launch_persistent_context`, `headless=False`, perfil em `/data/perfil`. No container, um script de entrada sobe Xvfb, x11vnc e noVNC (websockify) e depois o processo Python. Uma aba, navegação sequencial.

### Ritmo

- Pausa aleatória de 8 a 20 segundos entre páginas.
- Ordem dos produtos embaralhada a cada execução.
- Coleta diária de preços às 10:00, com jitter aleatório de ±30 minutos.
- Aos domingos, no mesmo horário, roda primeiro a varredura do catálogo e em seguida a coleta de preços, como um único job. A varredura também entra no job quando a última com sucesso tem mais de 7 dias ou não existe (primeira execução).
- Horários e jitter configuráveis via `.env`.
- Um lock garante que nunca há duas coletas simultâneas, incluindo as disparadas pelo admin.

### Coleta diária de preços

1. Lê `estado_coletor`. Se `pausado_desafio`, não executa e registra em log.
2. Cria `coleta` com `status = rodando`.
3. Para cada produto ativo:
   1. Abre a URL do produto.
   2. Verifica se a página é desafio (ver abaixo).
   3. Extrai o resumo com o parser (`parse_produto`).
   4. Em uma transação: insere `resumo_preco` e faz upsert em `preco_atual_liga`.
4. Ao fim, define `status` e `finalizada_em`.

`preco_min`, `preco_medio` e `preco_max` são lidos do quadro textual "Preço Médio de Venda no Marketplace" da página do produto; `num_lojas` é o contador "Lojas" do filtro "Vendedores" (0 quando a página diz "Nenhum item encontrado"). Atenção: o quadro é um indicador histórico do marketplace, não o menor preço pedido agora: um produto sem nenhuma loja ainda mostra valores. Quem consome deve olhar `num_lojas` junto.

### Varredura do catálogo

Mesmo navegador, ritmo e detecção de desafio. Pagina a categoria de selados, faz upsert em `produto_liga` (atualiza `nome`, `url`, `visto_ultimo_em`; preenche `visto_primeiro_em` na criação) e nunca altera `ativo`. Se houver produtos novos, envia ao grupo admin: "N produtos novos no catálogo".

### Detecção de desafio

A página é considerada desafio se qualquer um destes ocorrer:

- Título "Just a moment...".
- Presença de widget Turnstile ou `#challenge-form`.
- Resposta 403 ou 503 com header `cf-mitigated`.

Ao detectar:

1. `coleta.status = pausada_desafio`.
2. `estado_coletor.estado = pausado_desafio`, com motivo.
3. Envia ao grupo admin: "Desafio Cloudflare na LigaMagic. Resolver em http://<host>:6080/vnc.html e depois clicar em retomar em http://<host>:8000".
4. Encerra a execução sem retry.

### Retomar e rodar agora

O admin grava em `estado_coletor`: `estado = ativo` e `execucao_solicitada = true`. O coletor verifica `estado_coletor` a cada minuto; se houver solicitação, zera a flag e executa a coleta de preços respeitando o lock.

### Tratamento de erros

| Situação | Ação |
| --- | --- |
| Parser falha em um produto | Incrementa `produtos_falha`, salva o HTML em `/data/falhas/`, segue para o próximo |
| Mais de 50% dos produtos falham | `status = falha`; alerta admin: "layout da LigaMagic pode ter mudado" |
| Timeout ou erro de rede | Um retry após 30 segundos; depois conta como falha do produto |
| Container encerrado durante a coleta | Na inicialização, coletas `rodando` viram `falha` com erro "interrompida" |
| PC desligado no horário agendado | Na inicialização, se a última coleta de preços `ok` ou `parcial` tem mais de 24 horas, agenda uma execução com jitter. Além disso, se ainda não houve coleta de preços iniciada hoje e o horário do dia já passou, ela roda. |
| Erro inesperado no job (ex.: Chromium não abre) | Log, aviso no grupo admin e nenhuma nova tentativa agendada no mesmo dia |

### Decisão: só o resumo de preços (2026-10-13)

As fixtures reais (Task 6) mostraram que as ofertas por vendedor não são utilizáveis:

- Preço e quantidade de cada oferta são desenhados dígito a dígito com sprite CSS (classes aleatórias por página e `background-position`), e a loja aparece só como logotipo. Ler isso exigiria contornar uma ofuscação anti-scraping.
- A página mostra 16 ofertas e um botão "Ver Mais" (JavaScript) para o resto (ex.: 16 de 94).

Decisão do usuário em 2026-10-13: guardar só o resumo textual (mín, médio, máx) e o número de lojas. Não decodificar o sprite e não clicar em "Ver Mais". A tabela `oferta_liga` foi removida.

Ponto em aberto: a listagem do catálogo (ex.: `?view=cards/search&card=categ%3D10+searchprod%3D1&tipo=1`) também carrega itens por JavaScript ("Exibir mais", `mcards.nextPage(40)`), sem link de próxima página no HTML, e não existe uma listagem única de todos os selados: são várias categorias. Os cartões da listagem trazem em texto o preço "À partir de" (ou "Produto Indisponível"). A varredura do catálogo depende de uma decisão de design.

## Admin

FastAPI com templates Jinja e HTMX, na porta 8000. Autenticação HTTP Basic com uma senha compartilhada definida no `.env`. Acesso apenas local ou na rede local nesta fase.

| Página | Conteúdo |
| --- | --- |
| `/` | Estado do coletor (destaque se pausado), últimas 10 coletas, botões "retomar" e "rodar agora" |
| `/catalogo` | Busca por nome; filtros ativos, inativos e novos na última semana; toggle de ativo via HTMX |
| `/produto/{id}` | Preço atual (mín, médio, máx), número de lojas, tabela do histórico de `resumo_preco` |

## Notificador

```python
class Destino(Enum):
    ADMIN = "admin"
    OPORTUNIDADES = "oportunidades"

class Notificador(Protocol):
    def enviar(self, destino: Destino, texto: str) -> None: ...
```

- `EvolutionNotificador`: `POST /message/sendText/{instancia}` com header `apikey`. O ID do grupo de cada destino vem do `.env` (`WHATSAPP_GRUPO_ADMIN`, `WHATSAPP_GRUPO_OPORTUNIDADES`).
- `LogNotificador`: registra a mensagem em log. Usado em desenvolvimento, testes e quando a Evolution API não está configurada.
- Falha de envio nunca interrompe a coleta: até 3 tentativas com backoff, depois log de erro.
- Nesta fase só o destino `ADMIN` é usado.
- O número da Evolution API é o chip secundário do grupo, nunca um número pessoal ou da loja.

## Configuração (`.env`)

`DATABASE_URL`, `ADMIN_SENHA`, `VNC_SENHA`, `FUSO` (padrão `America/Sao_Paulo`), `LIGA_URL_CATALOGO`, `DIR_DADOS` (padrão `/data`), `COLETA_HORA` (padrão `10:00`), `COLETA_JITTER_MIN` (padrão `30`), `CATALOGO_DIA_SEMANA` (padrão `domingo`), `PAUSA_MIN_S` (padrão `8`), `PAUSA_MAX_S` (padrão `20`), `LIMITE_FALHA_PCT` (padrão `50`), `EVOLUTION_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCIA`, `WHATSAPP_GRUPO_ADMIN`, `WHATSAPP_GRUPO_OPORTUNIDADES`, `HOST_PUBLICO` (usado nos links das mensagens).

## Testes

pytest, desenvolvimento orientado a testes. Nenhum teste acessa a LigaMagic ou o WhatsApp reais.

| Camada | Abordagem |
| --- | --- |
| `parsers.py` | Fixtures de HTML reais: produto com várias lojas, sem estoque, uma única loja, página do catálogo |
| `desafio.py` | Fixtures de páginas de desafio do Cloudflare e de páginas normais |
| Persistência | Postgres real de teste, rollback por teste |
| Fluxo da coleta | `NavegadorFake` que devolve fixtures e `NotificadorFake` que guarda mensagens; cobre desafio no meio da coleta, falha acima de 50%, coleta interrompida, lock e execução solicitada |
| Admin | `TestClient` do FastAPI: autenticação, toggle de ativo, retomar, rodar agora |
| `evolution.py` | Mock HTTP com `respx`: sucesso, retry e falha definitiva |
