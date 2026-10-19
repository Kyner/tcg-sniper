# Casamento por par (anúncio × produto) e busca alternativa

Data: 2026-10-19. Aprovado em conversa (brainstorming) com o usuário. Item crítico das pendências.

## Problema

Hoje o casamento é uma coluna do anúncio: `anuncio_amazon.produto_id` + `status_casamento` (pendente/confirmado/ignorado) + `origem_casamento` + `revisado_em`. `repositorio_amazon.gravar_busca` grava o produto só na primeira vez que um ASIN aparece e nunca mais troca. Consequência: um anúncio ignorado para o produto errado (ex.: Colecionador sugerido para Jogo) nunca vira candidato para o produto certo, mesmo que a busca do produto certo o encontre; a IA só avalia pendentes. Perde oportunidades.

Produção em 2026-10-19: 1269 ignorados (96%), 51 confirmados, 5 pendentes; 50 produtos com par (um com 2 confirmados); `avaliacao_ia` já é por par (1120 pares, nenhum anúncio avaliado para mais de um produto); nenhuma tabela registra quais buscas encontraram cada ASIN. Catálogo: 2165 produtos ativos.

## Decisões do usuário

- **Ignorado vale só para aquele par.** O mesmo anúncio encontrado na busca de outro produto vira pendente para esse produto e a IA avalia.
- **Um anúncio é sempre um produto só:** pode estar pendente/ignorado para vários produtos, mas **confirmado para no máximo um**.
- **Ignorados atuais:** recuperação natural daqui para frente (sem rebusca forçada, sem reavaliação em massa pela IA).
- **Escopo completo:** par + "Desfazer" faz a IA reavaliar + busca alternativa + botões.
- **Busca alternativa:** termos sugeridos pela IA, uma vez por produto, guardados; entram depois de **7 dias sem candidato**.
- **Botões no admin antigo** (Jinja), com a regra em código comum (repositórios/serviços) para a fase 3 reaproveitar.
- **Modelo:** tabela `casamento` como fonte única.

**Regra de idioma (revista em 2026-10-19).** A edição em português é a preferida para o produto da Liga; um anúncio em inglês também casa quando o produto não tem anúncio em português confirmado (coleções antigas juntam os dois num produto só). Inglês já confirmado continua confirmado se o português aparecer depois (sem desfazer automático). Japonês e outros idiomas nunca casam. A IA devolve o idioma do anúncio (`avaliacao_ia.idioma_anuncio`: pt/en/ja/outro/indefinido, migração `b3e8d1f5c7a2`) e a pergunta diz se o produto já tem português confirmado (sim/não/não se sabe), fora da assinatura (sem reavaliação em massa). O automático nunca confirma ja/outro e só confirma inglês em produto sem português confirmado nem confirmado de idioma não registrado; senão o par fica pendente. Os termos da busca alternativa miram primeiro a edição em português e podem incluir a inglesa. `tcg-sniper casamento reabrir-ingles [--aplicar]` devolve à IA os ignorados pelo automático por inglês.

## Modelo

### Tabela `casamento`

| coluna | tipo | nota |
|---|---|---|
| `anuncio_id` | FK `anuncio_amazon.id` | PK composta com `produto_id` |
| `produto_id` | FK `produto_liga.id` | |
| `status` | `StatusCasamento` (pendente/confirmado/ignorado) | |
| `origem` | `OrigemCasamento` + novo valor `outro_confirmado` | nulo enquanto pendente |
| `revisado_em` | timestamptz nulo | quando a decisão foi tomada |
| `visto_primeiro_em` / `visto_ultimo_em` | timestamptz | quando a busca **deste produto** viu o anúncio (pares criados por link colado ou migração: data de criação) |

- Índice único parcial: no máximo um `confirmado` por `anuncio_id`.
- Índices para as leituras quentes: `(produto_id, status)`, `(status)`.

### Migração

Numa transação: cria `casamento`; insere um par por anúncio com `produto_id`, `status_casamento`, `origem_casamento`, `revisado_em`, `visto_primeiro_em`/`visto_ultimo_em` do anúncio; confere que nenhum anúncio ficou com dois confirmados (falha com mensagem clara se ficar); remove `produto_id`, `status_casamento`, `origem_casamento`, `revisado_em` de `anuncio_amazon`. Downgrade refaz as colunas a partir do par confirmado ou, sem confirmado, do par mais antigo. Backup antes do deploy (procedimento de sempre).

### Tabela `termo_busca`

`produto_id` (FK), `termo` (≤ 80 caracteres), `idioma` (`pt`/`en`), `ordem`, `criado_em`; único `(produto_id, termo)`. No máximo 3 por produto.

## Fluxos

### Busca (`gravar_busca`)

Para cada ASIN que a busca do produto P retorna:

- anúncio novo → cria o anúncio e o par (anúncio, P) `pendente`;
- anúncio conhecido sem par com P → cria (anúncio, P) `pendente`;
- par existente → atualiza `visto_ultimo_em` (status não muda: ignorado continua ignorado para P, confirmado continua confirmado);
- se o anúncio já está confirmado para outro produto Q, o par (anúncio, P) é criado com status `ignorado` e origem `outro_confirmado` (fica fora da fila da IA e aparece na tela de P como "casado com Q").

### IA (casador)

- Avalia pares `pendente` de produtos ativos cujo anúncio não esteja confirmado para outro produto. Regras atuais de assinatura, `so_descoberta` e `ja_avaliados` passam a ser por par.
- Confirmar um par (pela IA ou por você) marca os outros pares `pendente` do mesmo anúncio como `ignorado` com origem `outro_confirmado`.
- Duas confirmações concorrentes do mesmo anúncio: o índice único aceita uma; a outra recebe "já confirmado para outro produto" e o par fica como estava.

### Desfazer

O par volta a `pendente` (origem e `revisado_em` zerados) e a IA reavalia mesmo com o anúncio igual (a avaliação antiga do par deixa de valer como "já aplicada"). Os pares do mesmo anúncio com origem `outro_confirmado` voltam a `pendente`.

### Trocar

Confirma o par (anúncio, produto novo) — criando-o se não existir — e desfaz o confirmado anterior do anúncio (que vira `ignorado` origem `manual`).

### Link colado (`casar_link_manual`)

Cria ou confirma o par (anúncio, produto) com origem `manual`, aplicando a regra de "confirmar ignora os outros pendentes do anúncio"; prioriza o produto na fila como hoje.

### Monitor, checkout e oportunidades

Passam a ler os pares `confirmado` (mesma regra de hoje: produto ativo). `Oportunidade` continua com `anuncio_id` + `produto_id` e no máximo uma aberta por anúncio.

### Fila e descoberta

`_descoberta_liberada` e a regra de candidato passam a olhar pares: produto sem par confirmado é buscado no ritmo normal; com confirmado, a cada `descoberta_casados_dias`.

### Busca alternativa

- Produto ativo sem par confirmado e **sem nenhum candidato há 7 dias** (sem par novo criado pela busca dele nesse período; para produto que nunca teve, 7 dias desde que entrou na fila) e sem termos guardados → a IA gera de 2 a 3 termos de busca prováveis na Amazon Brasil (português e inglês), numa chamada barata, dentro do teto de gasto (Configurações → IA). Quem gera: o casador, numa etapa própria do ciclo, com limite de produtos por ciclo.
- Filtros: no máximo 3 termos, cada um com até 80 caracteres, sem repetir o nome original nem o nome em inglês, sem link, sem vazio.
- A fila alterna para esses produtos: nome em português, nome em inglês (se houver), termo 1, termo 2, termo 3, de novo.
- Se aparecer candidato (par novo pela busca do produto), a fila volta ao nome normal; os termos ficam guardados para uma próxima seca.
- Sem saldo de IA: o produto segue com o nome normal e tenta gerar no próximo período (aviso de teto que já existe).

### Botões (admin antigo, tela do produto em Casamentos)

- **Rebuscar agora**: põe o produto na frente da fila (`priorizar_na_fila`).
- **Reavaliar com a IA**: volta a `pendente` os pares do produto que estão `pendente` ou foram ignorados pela IA (origens `sugerido_ia`/`automatico_ia`/`outro_confirmado`); decisões `manual` e confirmados não mudam; a IA reavalia mesmo com o anúncio igual.
- **Gerar termos de busca**: gera (ou regenera) os termos agora, respeitando o teto de gasto; mostra os termos atuais na tela.
- As ações ficam em funções do repositório/serviço (sem regra no template), para a fase 3 reaproveitar.

## Telas que mudam (admin antigo)

- Casamentos (lista): contagens por par; badge do menu = produtos com par pendente.
- Casamentos (produto): pares do produto com status e origem; anúncio confirmado em outro produto aparece como "casado com <produto>"; os três botões; termos de busca atuais.
- Trocar: sobre o par.
- Dashboard, Ofertas, detalhe do produto, catálogo: leem os pares; números com o mesmo sentido de hoje.

## Erros

- Migração inconsistente: aborta sem mudar nada, mensagem clara.
- Confirmação concorrente: "já confirmado para outro produto"; nada muda.
- IA sem saldo ou fora: termos não são gerados; reavaliações esperam; nada quebra a busca.
- Termos inválidos da IA: descartados; se nenhum válido sobrar, tenta de novo só depois de 7 dias.

## Testes

- Migração com dados de exemplo: N anúncios → N pares com o mesmo status/origem/datas; downgrade refaz as colunas; aborta se houver dois confirmados.
- Regra principal: anúncio ignorado para A e encontrado na busca de B → par (anúncio, B) pendente → IA avalia.
- Confirmar par ignora os outros pendentes do anúncio (`outro_confirmado`); desfazer reabre esses e a IA reavalia mesmo com assinatura igual.
- Anúncio confirmado para Q encontrado na busca de P → par (anúncio, P) `ignorado`/`outro_confirmado`, fora da fila da IA.
- No máximo um confirmado por anúncio, inclusive com duas confirmações concorrentes.
- Trocar e link colado sobre o par.
- Busca alternativa: entra só após 7 dias sem candidato; termos filtrados; alternância na fila; volta ao nome normal com candidato novo; sem saldo de IA mantém o nome normal.
- Botões: rebuscar prioriza; reavaliar mexe só nos pares do produto e não toca decisões manuais; gerar termos respeita o teto.
- Regressão: monitor, checkout, oportunidades, dashboard, ofertas e telas de casamento com os mesmos números nos dados migrados; suíte inteira verde.

## Pendências geradas

- Botões migram para o site novo na fase 3.
- Acompanhar na primeira semana quantos ignorados foram recuperados (pares novos confirmados para outro produto) e quantos produtos entraram na busca alternativa.

## Fora do escopo

Reavaliação em massa dos ignorados atuais pela IA; rebusca forçada do catálogo; casamento de um anúncio com mais de um produto.
