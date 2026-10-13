# Sub-projeto 1: coletor-liga, banco, admin e alerta admin

Data: 2026-10-13 (redesenho da coleta em 2026-10-13, ver "Decisões de 2026-10-13")
Contexto: `Monitor de arbitragem de selados de Magic.md` (visão geral do sistema)

## Objetivo

Primeiro sub-projeto do monitor de arbitragem. Coletar diariamente, na LigaMagic, o catálogo de selados de Magic com o menor preço pedido agora ("à partir de") de cada produto e, para os produtos que o grupo escolher monitorar, o resumo histórico de venda e o número de lojas; guardar histórico no Postgres, permitir que o grupo escolha quais produtos monitorar por uma página de admin, e avisar um grupo de WhatsApp de administração quando a coleta precisar de intervenção humana.

Critério de sucesso: a coleta diária roda por uma semana sem desafio do Cloudflare (ou, se aparecer, o grupo admin é avisado, resolve pelo noVNC e retoma pelo admin), e o histórico de preços por produto fica consultável.

## Escopo

Dentro:

- Coleta diária das listagens de todas as categorias de selados da LigaMagic: alimenta o catálogo e grava o preço atual "à partir de" de cada produto listado.
- Coleta diária, logo em seguida, das páginas dos produtos ativos: resumo histórico de venda (mín, médio, máx) e número de lojas.
- Banco Postgres com catálogo, preços da listagem, resumos de preço e estado do coletor.
- Página de admin para ativar produtos, ver status e preços, e retomar a coleta.
- Notificador com destino "admin" via WhatsApp (Evolution API).

Fora (próximas specs):

- Coletores de marketplaces (Mercado Livre, Amazon, outros).
- Matcher e fila de revisão de de-para.
- Motor de oportunidades, regras de cupom e cashback.
- Mensagens para o grupo de oportunidades.
- Migração para servidor.

## Restrições

- Cloudflare é restrição, não obstáculo: nada de solucionador de CAPTCHA nem spoofing de fingerprint. A estratégia é volume baixo, navegador real com perfil persistente, IP residencial e intervenção humana quando o desafio aparecer. Sem retry automático diante de desafio.
- Nada de contornar ofuscação: os preços por oferta (sprite CSS) nunca são decodificados e as ofertas por vendedor nunca são expandidas. Clicar no botão "Exibir mais" das listagens é interação normal de interface e é permitido, com pausa humana e limite de cliques.
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
    repositorio.py    # operações de banco do coletor
    migrations/       # Alembic
  coletor_liga/
    modelos.py        # Resumo, ItemListagem, Pagina, PaginaExpandida, erros
    navegador.py      # contexto Playwright persistente; abrir e abrir_expandindo ("Exibir mais")
    parsers.py        # HTML -> dataclasses, funções puras, sem I/O
    desafio.py        # detecção da página de desafio
    execucao.py       # peças comuns às duas etapas (pausa, retry, desafio, fechamento da coleta)
    listagens.py      # etapa 1: listagens das categorias (catálogo + preço "à partir de")
    produtos.py       # etapa 2: páginas dos produtos ativos (resumo + nº de lojas)
    agendador.py      # laço de 60 s, lock, polling de solicitações
  admin/
    app.py            # FastAPI
    consultas.py
    templates/
  notificador/
    base.py           # Destino, Protocol Notificador
    evolution.py      # implementação WhatsApp
    log.py            # implementação que só registra em log
```

Princípio: os parsers são funções puras testadas com fixtures de HTML salvas da LigaMagic. O navegador só busca HTML (e clica em "Exibir mais"). A lógica é testada sem acessar a Liga.

## Banco de dados

Dinheiro em `NUMERIC(10,2)` (BRL). Datas em `timestamptz` (UTC). Não há banco de produção nesta fase: a migração inicial é editada no lugar enquanto o esquema muda.

### `produto_liga`

Catálogo, alimentado pela coleta diária das listagens. Registros nunca são apagados.

| Coluna | Tipo | Nota |
| --- | --- | --- |
| `id` | serial PK | |
| `liga_id` | text UNIQUE | `pcode` do produto na URL da Liga |
| `nome` | text | Título como aparece no cartão da listagem |
| `url` | text | Página do produto |
| `edicao` | text NULL | Não aparece na listagem; fica vazio nesta fase |
| `tipo` | text NULL | Nome da categoria no cartão (ex.: "Caixas de Boosters"); preenchido uma vez, não troca se o produto aparecer em outra categoria |
| `idioma` | text NULL | Não aparece na listagem; fica vazio nesta fase |
| `ean` | text NULL | Para o matcher da fase 2 |
| `ativo` | bool, default false | Alterado pelo admin |
| `visto_primeiro_em` | timestamptz | |
| `visto_ultimo_em` | timestamptz | Fica antigo quando o produto some das listagens |

### `coleta`

Uma linha por etapa executada.

| Coluna | Tipo |
| --- | --- |
| `id` | serial PK |
| `tipo` | enum `listagem`, `produtos` |
| `iniciada_em` | timestamptz |
| `finalizada_em` | timestamptz NULL |
| `status` | enum `rodando`, `ok`, `parcial`, `falha`, `pausada_desafio` |
| `produtos_ok` | int |
| `produtos_falha` | int |
| `erro` | text NULL |

Em `listagem`, `produtos_ok` e `produtos_falha` contam categorias; em `produtos`, contam produtos. Status final: `ok` se nada falhou; `parcial` se falharam até 50%; `falha` se falharam mais de 50% ou houve erro geral.

### `preco_listagem`

Histórico append-only do preço "à partir de" da listagem: uma linha por produto e coleta `listagem`.

| Coluna | Tipo |
| --- | --- |
| `produto_id` | FK, parte da PK |
| `coleta_id` | FK, parte da PK |
| `preco_a_partir` | numeric(10,2) NULL (NULL quando o cartão diz "Produto Indisponível") |
| `coletado_em` | timestamptz |

Um produto que aparece em duas categorias no mesmo job grava uma linha só (a primeira vista; a segunda é ignorada pela chave).

### `resumo_preco`

Histórico append-only do resumo da página do produto: uma linha por produto ativo e coleta `produtos`.

| Coluna | Tipo |
| --- | --- |
| `produto_id` | FK, parte da PK |
| `coleta_id` | FK, parte da PK |
| `preco_min` | numeric(10,2) NULL (sem o quadro de preços o parser lança `ErroParser`: o produto conta como falha, o HTML vai para `/data/falhas/` e nada é gravado) |
| `preco_medio` | numeric(10,2) NULL |
| `preco_max` | numeric(10,2) NULL |
| `num_lojas` | int |
| `coletado_em` | timestamptz |

### `preco_atual_liga`

Dado corrente, uma linha por produto, atualizado por upsert. É a tabela que o admin e o futuro motor de oportunidades leem para o presente. Tem dois grupos de colunas, e cada etapa só escreve o seu: a etapa das listagens nunca apaga o resumo, e a etapa dos produtos nunca apaga o preço da listagem.

| Coluna | Tipo | Grupo |
| --- | --- | --- |
| `produto_id` | PK, FK `produto_liga` | |
| `preco_a_partir` | numeric(10,2) NULL | listagem |
| `listagem_coleta_id` | FK `coleta` NULL | listagem |
| `listagem_em` | timestamptz NULL | listagem |
| `preco_min` | numeric(10,2) NULL | resumo |
| `preco_medio` | numeric(10,2) NULL | resumo |
| `preco_max` | numeric(10,2) NULL | resumo |
| `num_lojas` | int NULL | resumo |
| `resumo_coleta_id` | FK `coleta` NULL | resumo |
| `resumo_em` | timestamptz NULL | resumo |

Produto nunca monitorado só tem o grupo listagem. `listagem_em` preenchido com `preco_a_partir` NULL significa "indisponível na última listagem"; os dois NULL significam "nunca visto numa listagem". Separação entre dado do dia e histórico: `preco_atual_liga` para o presente, `preco_listagem` e `resumo_preco` para o histórico. Não existe job de virada de dia; histórico e atual de cada produto são gravados na mesma transação.

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

Duas operações: `abrir(url)` (página de produto) e `abrir_expandindo(url, max_cliques, pausar)` (listagem). A segunda clica no botão "Exibir mais" (`#exibir_mais_cards input.exibir-mais`) até ele sumir, ficar oculto ou desabilitado, ou até a quantidade de cartões parar de crescer depois de um clique; chama a pausa humana antes de cada clique; para em `LIGA_MAX_CLIQUES` cliques e avisa que o limite foi atingido; verifica desafio na carga e depois de cada clique e, se aparecer, para de clicar e devolve a página do desafio.

### Ritmo

- Pausa aleatória de 8 a 20 segundos entre páginas e antes de cada clique em "Exibir mais".
- Ordem das categorias e dos produtos embaralhada a cada execução.
- Um job por dia às 10:00, com jitter aleatório de ±30 minutos: primeiro as listagens, depois os produtos ativos. Não há varredura semanal: o catálogo se atualiza todo dia pelas listagens.
- Horários, jitter, categorias e limite de cliques configuráveis via `.env`.
- Um lock garante que nunca há duas coletas simultâneas, incluindo as disparadas pelo admin.

### Etapa 1: listagens das categorias

1. Lê `estado_coletor`. Se `pausado_desafio`, não executa e registra em log.
2. Cria `coleta` `listagem` com `status = rodando`.
3. Para cada categoria de `LIGA_CATEGORIAS` (21 por padrão: 10, 11, 12, 13, 14, 15, 16, 17, 19, 20, 21, 22, 31, 36, 37, 47, 50, 51, 52, 55, 56):
   1. Abre `LIGA_URL_LISTAGEM` com o ID da categoria e clica em "Exibir mais" até acabar.
   2. Verifica desafio.
   3. Extrai os cartões da grade (`parse_listagem`): `pcode`, nome, URL, preço "à partir de" (ou indisponível) e categoria.
   4. Em uma transação: upsert em `produto_liga` (atualiza `nome`, `url`, `visto_ultimo_em`; preenche `visto_primeiro_em` na criação; nunca altera `ativo`), insere `preco_listagem` e atualiza o grupo listagem de `preco_atual_liga`.
4. Ao fim, define `status` e `finalizada_em`. Se houve produtos novos (mesmo que a etapa tenha parado por desafio ou erro), envia ao grupo admin: "N produtos novos no catálogo. Ativar em http://<host>:8000/catalogo?filtro=novos". Um produto que aparece em duas categorias conta como novo uma vez só.

O preço "à partir de" é o menor preço pedido agora (texto "À partir de R$ X" do cartão). Cartão "Produto Indisponível" grava NULL, nunca zero.

### Etapa 2: produtos ativos

Roda logo depois da etapa 1, no mesmo job, se ela não parou por desafio.

1. Lê `estado_coletor` (pausado: não executa).
2. Cria `coleta` `produtos` com `status = rodando`.
3. Para cada produto ativo:
   1. Abre a URL do produto.
   2. Verifica desafio.
   3. Extrai o resumo com o parser (`parse_produto`).
   4. Em uma transação: insere `resumo_preco` e atualiza o grupo resumo de `preco_atual_liga`.
4. Ao fim, define `status` e `finalizada_em`.

`preco_min`, `preco_medio` e `preco_max` são lidos do quadro textual "Preço Médio de Venda no Marketplace" da página do produto; `num_lojas` é o contador "Lojas" do filtro "Vendedores" (0 quando a página diz "Nenhum item encontrado"). Atenção: o quadro é um indicador histórico de venda do marketplace, não o menor preço pedido agora: um produto sem nenhuma loja ainda mostra valores. O preço atual é o "à partir de" da etapa 1; quem consome o resumo deve olhar `num_lojas` junto.

### Volume estimado

O tamanho de cada categoria ainda não foi medido (só a primeira carga da categoria 10, com 40 cartões, foi capturada). Estimativa para planejamento, com 1.500 selados no total: 21 cargas de listagem + cerca de 38 cliques em "Exibir mais" (40 cartões por clique) ≈ 60 interações × 14 s de pausa média + carregamento ≈ 15 a 20 minutos na etapa 1; mais 14 s por produto ativo na etapa 2 (50 ativos ≈ 12 minutos). Total diário na casa de 30 minutos e 100 a 120 requisições de página ou de "Exibir mais", da mesma ordem do desenho anterior (catálogo semanal + produtos diários). O log de cada categoria registra cartões e cliques; com uma semana de números reais, revisar `LIGA_MAX_CLIQUES` (padrão 50, ou seja, até 2.040 cartões por categoria).

### Detecção de desafio

A página é considerada desafio se qualquer um destes ocorrer:

- Título "Just a moment..." (ou "Um momento...").
- Marcadores exclusivos da página interstitial no HTML: `id="challenge-form"`, `_cf_chl_opt` ou `cf-chl-`. Por decisão de revisão, o widget Turnstile (`cf-turnstile`) e scripts de `/cdn-cgi/challenge-platform` sozinhos **não** contam como desafio: aparecem também em páginas normais.
- Resposta 403 ou 503 com header `cf-mitigated`.

A verificação vale para a carga de cada página e para a página depois de cada clique em "Exibir mais". Ao detectar:

1. `coleta.status = pausada_desafio`.
2. `estado_coletor.estado = pausado_desafio`, com motivo.
3. Envia ao grupo admin: "Desafio Cloudflare na LigaMagic. Resolver em http://<host>:6080/vnc.html e depois clicar em retomar em http://<host>:8000".
4. Encerra o job sem retry (a etapa 2 não roda se o desafio veio na etapa 1).
5. Mantém o Chromium aberto com o desafio na tela, para o humano resolver pelo noVNC. O job seguinte (após "retomar") reaproveita essa mesma instância e a fecha no fim, a menos que pause de novo. Se a instância mantida não responder mais (ex.: a janela foi fechada), é descartada e uma nova é aberta, uma única vez.

### Retomar e rodar agora

O admin grava em `estado_coletor`: `estado = ativo` e `execucao_solicitada = true` ("retomar"), ou só `execucao_solicitada = true` ("rodar agora"). O coletor verifica `estado_coletor` a cada minuto; se houver solicitação, zera a flag e executa o job respeitando o lock. Se já houve hoje uma etapa de listagens com sucesso (`ok` ou `parcial`), roda só a etapa dos produtos; senão roda o job completo.

### Tratamento de erros

| Situação | Ação |
| --- | --- |
| Parser falha numa listagem ou num produto | Conta falha daquela categoria ou produto, salva o HTML em `/data/falhas/`, segue para o próximo |
| Limite de cliques em "Exibir mais" atingido | Conta falha da categoria, salva o HTML, não grava nada daquela listagem, segue |
| Mais de 50% falham numa etapa | `status = falha`; alerta admin: "layout da LigaMagic pode ter mudado" |
| Timeout ou erro de rede | Um retry após 30 segundos; depois conta como falha da categoria ou do produto |
| Container encerrado durante a coleta | Na inicialização, coletas `rodando` viram `falha` com erro "interrompida" |
| PC desligado no horário agendado | Na inicialização, se a última etapa de produtos `ok` ou `parcial` tem mais de 24 horas, agenda uma execução com jitter, que só roda se o job ainda não rodou hoje. Além disso, se ainda não houve job iniciado hoje e o horário do dia já passou, ele roda. O job roda no máximo uma vez por dia pelo agendamento (pedidos do admin à parte) |
| Erro inesperado no job (ex.: Chromium não abre) | Log, aviso no grupo admin e nenhuma nova tentativa agendada no mesmo dia |

### Decisão: só o resumo de preços (2026-10-13)

As fixtures reais (Task 6) mostraram que as ofertas por vendedor não são utilizáveis:

- Preço e quantidade de cada oferta são desenhados dígito a dígito com sprite CSS (classes aleatórias por página e `background-position`), e a loja aparece só como logotipo. Ler isso exigiria contornar uma ofuscação anti-scraping.
- A página mostra 16 ofertas e um botão "Ver Mais" (JavaScript) para o resto (ex.: 16 de 94).

Decisão do usuário em 2026-10-13: guardar só o resumo textual (mín, médio, máx) e o número de lojas. Não decodificar o sprite e não clicar em "Ver Mais". A tabela `oferta_liga` foi removida.

## Decisões de 2026-10-13

Fatos levantados no HTML real (relatório da Task 6):

- O quadro "Preço Médio de Venda no Marketplace" da página de produto é histórico de venda, não o preço pedido agora: a página de um produto sem estoque (pcode 276, 0 lojas) mostra R$ 5.450,00 nos três valores. O contador "Lojas" é atual.
- Não existe listagem única de selados. São 21 listagens de categoria (`?view=cards/search&card=categ%3D<ID>+searchprod%3D1&tipo=1`).
- Cada carga de listagem mostra 40 cartões com link (`pcode`), nome, categoria e o preço atual "À partir de R$ X" em texto (ou "Produto Indisponível"). Mais cartões só pelo botão "Exibir mais" (`mcards.nextPage(40)`), sem link de próxima página.

Decisões do usuário:

1. Só o resumo na página de produto, nunca o sprite nem as ofertas por vendedor (mantém a decisão anterior).
2. O job diário tem duas etapas: (a) todas as categorias, clicando em "Exibir mais" até acabar, com pausa entre cliques; alimenta o catálogo e grava o "à partir de" atual de todos os produtos listados (histórico append-only + valor corrente); (b) depois, a página de produto só da lista ativa, para `num_lojas` e o resumo histórico.
3. A varredura semanal do catálogo some (o catálogo vem da etapa (a) todo dia), junto com a regra de "mais de 7 dias" e a configuração `CATALOGO_DIA_SEMANA`.

Por quê:

- O "à partir de" da listagem é o único preço atual em texto que a Liga oferece; o resumo da página de produto não serve como preço atual. Lendo a listagem todo dia, o futuro motor de oportunidades tem o preço atual de todo o catálogo, não só da lista ativa.
- Clicar em "Exibir mais" é o que uma pessoa faz na página: não contorna nada. Com pausa humana antes de cada clique e limite de cliques, o volume diário fica na mesma ordem do desenho anterior.
- Com o catálogo atualizado todo dia, produtos novos aparecem no admin no mesmo dia, e a regra semanal fica sem função.
- `preco_listagem` separado de `resumo_preco`, e `preco_atual_liga` em dois grupos de colunas, porque as duas fontes têm significados diferentes (pedido agora × histórico de venda), produtos diferentes (todos × ativos) e podem falhar de forma independente: uma etapa nunca apaga o dado da outra.
- `TipoColeta` passou de `catalogo`/`precos` para `listagem`/`produtos`, porque as duas etapas agora gravam preços.

Pontos em aberto:

- O comportamento do botão "Exibir mais" no fim de uma categoria (some, fica oculto ou continua visível sem trazer nada) não foi observado; o navegador cobre os três casos. Confirmar no primeiro job real pelos logs (cartões e cliques por categoria).
- Uma categoria vazia (sem nenhum cartão) é tratada como falha de parser. Se alguma categoria ficar vazia de verdade, ela sai de `LIGA_CATEGORIAS`.
- Tamanho real de cada categoria e duração do job: medir na primeira semana e revisar `LIGA_MAX_CLIQUES` e a estimativa de volume.
- `edicao` e `idioma` não aparecem nas listagens e ficam vazios; se o matcher da fase 2 precisar deles, vêm de outra fonte ou do nome.

## Admin

FastAPI com templates Jinja e HTMX, na porta 8000. Autenticação HTTP Basic com uma senha compartilhada definida no `.env` (vazia ou o valor padrão são recusados na inicialização). Acesso apenas local ou na rede local nesta fase.

| Página | Conteúdo |
| --- | --- |
| `/` | Estado do coletor (destaque se pausado), últimas 10 coletas, botões "retomar" e "rodar agora" |
| `/catalogo` | Busca por nome; filtros ativos, inativos e novos na última semana; categoria, preço atual "à partir de" (ou "Indisponível"), mín do histórico de venda e lojas; toggle de ativo via HTMX |
| `/produto/{id}` | Preço atual "à partir de" e quando foi lido; bloco "Histórico de venda" (mín, médio, máx do quadro "Preço Médio de Venda no Marketplace", lojas), rotulado como histórico e não como preço pedido; tabelas do histórico de `preco_listagem` e de `resumo_preco` |

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

`DATABASE_URL`, `ADMIN_SENHA`, `VNC_SENHA`, `FUSO` (padrão `America/Sao_Paulo`), `LIGA_CATEGORIAS` (IDs separados por vírgula; padrão as 21 categorias de selados), `LIGA_URL_LISTAGEM` (modelo com `{categ}`; padrão `https://www.ligamagic.com.br/?view=cards/search&card=categ%3D{categ}+searchprod%3D1&tipo=1`), `LIGA_MAX_CLIQUES` (padrão `50`), `DIR_DADOS` (padrão `/data`), `COLETA_HORA` (padrão `10:00`), `COLETA_JITTER_MIN` (padrão `30`), `PAUSA_MIN_S` (padrão `8`), `PAUSA_MAX_S` (padrão `20`), `LIMITE_FALHA_PCT` (padrão `50`), `EVOLUTION_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCIA`, `WHATSAPP_GRUPO_ADMIN`, `WHATSAPP_GRUPO_OPORTUNIDADES`, `HOST_PUBLICO` (usado nos links das mensagens).

Saíram em 2026-10-13: `CATALOGO_DIA_SEMANA` e `LIGA_URL_CATALOGO`.

## Testes

pytest, desenvolvimento orientado a testes. Nenhum teste acessa a LigaMagic ou o WhatsApp reais.

| Camada | Abordagem |
| --- | --- |
| `parsers.py` | Fixtures de HTML reais: produto com várias lojas, sem estoque, uma única loja; listagem da categoria 10 (primeira carga e expandida com "Exibir mais"); cartão indisponível com a marcação real |
| `desafio.py` | Fixtures de páginas de desafio do Cloudflare e de páginas normais (todas as fixtures reais não são desafio) |
| `navegador.py` | Teste opcional (`TESTAR_NAVEGADOR=1`) com Chromium e um HTML local que imita o botão "Exibir mais": botão some, limite de cliques, clique sem cartões novos |
| Persistência | Postgres real de teste, rollback por teste; um produto em duas categorias; listagem e resumo não se sobrescrevem |
| Fluxo da coleta | `NavegadorFake` que devolve fixtures (e listagens expandidas) e `NotificadorFake` que guarda mensagens; cobre desafio no meio da coleta, falha acima de 50%, limite de cliques, coleta interrompida, lock, execução solicitada e restart no mesmo dia |
| Admin | `TestClient` do FastAPI: autenticação, toggle de ativo, retomar, rodar agora, preço "à partir de" e históricos |
| `evolution.py` | Mock HTTP com `respx`: sucesso, retry e falha definitiva |
