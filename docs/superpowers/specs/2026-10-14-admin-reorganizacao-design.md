# Reorganização do admin: dashboard, serviços, casamentos por produto e filtros

Data: 2026-10-14
Contexto: sub-projetos 1 (`2026-10-13-coletor-liga-design.md`) e 2 (`2026-10-14-coletor-amazon-design.md`), já em produção.

## Objetivo

Deixar o admin mais fácil de operar no dia a dia:

1. Separar o que é **acompanhar** (status e histórico) do que é **comandar** (rodar, pausar, retomar).
2. Organizar **Casamentos por produto da Liga**, com a opção de **informar à mão o link da Amazon** quando as sugestões não servem ou quando a busca não achou nada.
3. Mostrar o **link do produto na LigaMagic** nas opções de troca, para conferir antes de escolher.
4. Dar **filtros** a Casamentos e Ofertas.

Critério de sucesso: com o admin, o grupo encontra em poucos cliques os produtos sem par, casa um produto colando o link da Amazon e, minutos depois, vê esse anúncio lido (preço e vendedor) na página do produto e em Ofertas; os comandos dos coletores ficam só em Serviços.

## Escopo

Dentro:

- Menu novo e as telas Dashboard e Serviços.
- Casamentos por produto da Liga, com link manual da Amazon e tela de troca com links.
- Filtros e paginação em Casamentos, Ofertas e no histórico do Dashboard.
- Mudança no coletor da Amazon para ler anúncios confirmados que não aparecem na busca (necessário para o link manual funcionar).

Fora:

- Mudar o visual geral (continua o Pico CSS).
- Login com usuários; casar vários produtos de uma vez.

## Decisões de 2026-10-14

1. A aba "Status" vira duas: **Dashboard** (só leitura) e **Serviços** (só comandos).
2. O link "definida em Configurações" no bloco da Amazon sai; Configurações continua no menu.
3. Casamentos passa a ser **por produto da Liga** (a fila por anúncio da Amazon some).
4. Link manual: o coletor lê, a cada busca do produto, os **anúncios confirmados que não apareceram na busca** (no máximo 5 por busca, os lidos há mais tempo primeiro). Cobre o link manual e o anúncio confirmado que saiu da primeira página da busca.

## Navegação

Menu: **Dashboard** (`/`) · **Serviços** (`/servicos`) · **Catálogo** · **Casamentos** · **Ofertas** · **Configurações**.

## Dashboard (`/`)

Só leitura; nenhum botão de ação.

- **Avisos** no topo, em destaque, quando um serviço está pausado: o motivo e o link "Ir para Serviços".
- **LigaMagic:** estado (ativo / pausado por desafio), "coleta em andamento" quando houver, data da última coleta com sucesso e o horário da coleta diária (`COLETA_HORA` ± `COLETA_JITTER_MIN`, do `.env`).
- **Amazon:** estado (ativo / pausado / pausado por CAPTCHA / fora da janela, calculado com `janela_inicio`–`janela_fim` de `config_amazon`, sem a variação), ciclo atual com início, e o último ciclo terminado (status, buscas ok e com falha).
- **Histórico:** "Coletas da LigaMagic" e "Ciclos da Amazon", cada um com 20 linhas por página e filtro por status (todos, ok, parcial, falha, pausada_desafio). Os parâmetros são separados por tabela (`liga_status`, `liga_pagina`, `amazon_status`, `amazon_pagina`).

## Serviços (`/servicos`)

Um cartão por serviço, com o estado em uma linha e só os botões que cabem no estado:

- **LigaMagic:** "Rodar agora" (quando ativo e sem coleta em andamento; "execução solicitada" quando já pedida); "Retomar" com o link do noVNC 6080 quando pausado por desafio; "coleta em andamento" sem botão quando houver.
- **Amazon:** "Pausar (Amazon)" quando ativo; "Retomar (Amazon)" quando pausado ou pausado por CAPTCHA, com o link do noVNC 6081 no caso de CAPTCHA.

As rotas de ação continuam (`POST /rodar-agora`, `/retomar`, `/amazon/pausar`, `/amazon/retomar`) e passam a redirecionar para `/servicos?msg=<código>`, que mostra uma mensagem de confirmação (`rodar`, `retomar`, `amazon_pausar`, `amazon_retomar`; código desconhecido é ignorado).

## Casamentos por produto (`/casamentos`)

Lista os **produtos ativos da Liga**, 20 por página. Cada linha: nome com link para a página do produto na LigaMagic (`target="_blank"`), "À partir de", contagem de anúncios da Amazon pendentes / confirmados / ignorados, marca **"oportunidade"** (algum pendente com preço atual a pelo menos `desconto_min_pct` abaixo do "À partir de"), marca **"sem par"** (nenhum confirmado nem pendente), e link "Abrir".

Filtros (na URL, mantidos na paginação): busca por nome (`%` e `_` literais), categoria (`ProdutoLiga.tipo`), situação — `pendentes` (padrão: ao menos um pendente), `oportunidade`, `sem_par`, `casados` (ao menos um confirmado), `todos` — e "só com preço na Liga".

Ordem: produtos com pendente que seria oportunidade, depois com pendentes, depois os demais; dentro de cada grupo, por nome.

### Página do produto (`/casamentos/produto/<id>`)

- Topo: nome, link da LigaMagic, "À partir de", e o formulário **"Colar link da Amazon"**.
- **Pendentes:** título com link da Amazon, ASIN, preço atual, marca "oportunidade"; botões **Confirmar**, **Ignorar** e **"É de outro produto"** (abre Trocar).
- **Confirmados:** título com link, preço, vendedor/envio, data da última leitura; botão **Desfazer**.
- **Ignorados:** título com link; botão **Desfazer**.
- Link **Voltar** para `/casamentos` com os filtros de onde veio (passados como `voltar=<querystring>` e validados para começar com `/casamentos`).
- Produto inativo ou inexistente → 404.

As ações por anúncio usam a rota existente `POST /casamentos/<anuncio_id>` (`acao` = confirmar / ignorar / desfazer, `produto_id`), que passa a aceitar `voltar` e redirecionar para ele (só caminhos que começam com `/casamentos`; o resto vira `/casamentos`).

### Link manual (`POST /casamentos/produto/<id>/link`)

`extrair_asin(texto) -> str` (função pura, `admin/asin.py` ou junto das consultas) aceita:

- URL de `amazon.com.br` (com ou sem `www.`, `http`/`https`) com o ASIN em `/dp/<ASIN>`, `/gp/product/<ASIN>` ou `/gp/aw/d/<ASIN>`, com qualquer prefixo (nome do produto) e qualquer sufixo ou parâmetro;
- só o ASIN: 10 caracteres `[A-Z0-9]` (maiúsculas após `strip().upper()`).

Recusa, com mensagem na página do produto: link encurtado (`amzn.to`, `a.co`, `amzn.com`) → "Abra o link e copie o endereço completo da página do produto"; outro domínio ou endereço sem ASIN → "Não encontrei o código do produto (ASIN) nesse link".

Ao salvar:

- **ASIN já conhecido:** `confirmar_casamento(anuncio_id, produto_id)` (se estava casado com outro produto, as oportunidades abertas fecham, como hoje).
- **ASIN novo:** cria `anuncio_amazon` com `asin`, `url = https://www.amazon.com.br/dp/<ASIN>`, título "Informado manualmente", `produto_id`, `status_casamento = confirmado`, `revisado_em`, `visto_primeiro_em` e `visto_ultimo_em` = agora.
- **Nos dois casos:** `fila_amazon.proxima_busca_em` do produto = agora (vai para a frente da fila). Redireciona para a página do produto com mensagem "Link salvo; o anúncio será lido em alguns minutos".

## Trocar (`/casamentos/<anuncio_id>/trocar`)

- Topo: o anúncio da Amazon com link e ASIN.
- Busca no catálogo (como hoje); cada produto da Liga mostra nome com link para a LigaMagic (`target="_blank"`), "À partir de" e o botão **Escolher**.
- As sugestões parecidas (difflib, como hoje) aparecem antes da busca, com o mesmo formato.
- Escolher → `confirmar_casamento` e volta para a página do produto escolhido.

## Ofertas (`/ofertas`)

Mantém o conteúdo atual (uma linha por produto com anúncio confirmado com preço: melhor oferta da Amazon) e acrescenta:

- Coluna **"Diferença (R$)"**: "À partir de" − preço da Amazon ("—" sem preço da Liga).
- Filtros (na URL, mantidos na paginação): busca por nome (`%`/`_` literais), categoria, **desconto mínimo** em % (inteiro 0–100; vazio = todos; o link "≥ desconto configurado" preenche com `desconto_min_pct`), **vendedor** — `todos`, `amazon`, `fba`, `elegiveis` (Amazon ou FBA confiável) —, **situação** — `todas`, `abertas` —, **ordem** — `desconto` (padrão, maior primeiro), `diferenca` (maior R$ primeiro), `recentes` (leitura mais recente), `nome`.
- 50 linhas por página.
- Valores de filtro inválidos → 400, como no Catálogo.

## Coletor da Amazon (busca de um produto)

Em `coletor_amazon/busca.py`, `processar_produto`:

1. Como hoje: busca, grava resultados, candidatos (confirmados da busca com desconto no cartão, ou com oportunidade aberta).
2. **Novo:** anúncios **confirmados do produto buscado** que **não apareceram nesta busca**, ordenados pela leitura mais antiga (`preco_atual_amazon.coletado_em`, sem leitura primeiro), no máximo `MAX_CONFIRMADOS_AUSENTES = 5`. Cada um passa pela mesma confirmação dos candidatos (pausa humana, página do produto, vendedor se preciso, motor, alerta).
3. A confirmação (`_confirmar`) passa a atualizar o anúncio com o título lido na página (`#productTitle`) e `visto_ultimo_em = agora`, para que a regra "sem leitura há 24 h fecha a oportunidade" valha para anúncios que nunca aparecem na busca.
4. O número devolvido continua sendo o total de anúncios conferidos na página do produto (candidatos + ausentes).

Um ASIN informado à mão que não existe mais (página sem título) cai no fluxo de erro de parser de hoje (HTML salvo, falha contada, freio de falhas seguidas).

## Testes

- `extrair_asin` (tabela): `/dp/`, `/gp/product/`, `/gp/aw/d/`, com prefixo de nome e com parâmetros, `http`, sem `www`, só o ASIN em minúsculas; recusa `amzn.to`, `a.co`, outro domínio e texto sem ASIN.
- Link manual pelo admin: ASIN novo vira confirmado com `proxima_busca_em` = agora; ASIN de outro produto troca o casamento e fecha as oportunidades; recusas mostram a mensagem e não gravam nada; produto inativo → 404.
- Coletor: confirmado ausente da busca tem a página lida; no máximo 5, os de leitura mais antiga primeiro; título e `visto_ultimo_em` atualizados; link manual com preço ≥ desconto gera alerta; os testes de busca existentes continuam passando.
- Dashboard sem botões de ação; Serviços com os botões certos por estado; ações redirecionam para `/servicos` com mensagem; sem o link de Configurações no bloco da Amazon; histórico com filtro e paginação.
- Casamentos: cada filtro, ordem, paginação mantendo filtros, `%` literal, "sem par", "oportunidade", página do produto com os três blocos, Voltar preservando filtros e recusando destino fora de `/casamentos`.
- Trocar: link da LigaMagic nas sugestões e na busca.
- Ofertas: cada filtro, cada ordem, coluna Diferença, paginação, valores inválidos → 400.
