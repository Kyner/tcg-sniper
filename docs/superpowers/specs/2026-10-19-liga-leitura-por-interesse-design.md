# Coletor da LigaMagic: leitura por interesse e esfriar após desafio

Data: 2026-10-19. Aprovado em conversa (brainstorming) com o usuário.

## Problema

O job diário da LigaMagic tem duas etapas:

1. **Listagens.** São 21 categorias, em ~20 min, e trazem o "a partir de" de todos os produtos e os produtos novos.
2. **Produtos.** Abre a página de **cada produto ativo** (2165, embaralhados) para gravar o resumo (mín/médio/máx, lojas).

Com o catálogo crescendo de 224 para 2165 produtos, a etapa 2 passou de ~1 h para ~10 h de navegação seguida. Em 2026-10-19 ela provocou o desafio do Cloudflare. A cada "Retomar", o job recomeçava a lista inteira e pedia a página seguinte em segundos, então o desafio voltava (`pausado_desafio` desde as 16:01).

## Decisões do usuário

- **Leitura por interesse (A).** A etapa 2 lê por dia só o que importa: casados e com candidato todo dia; o resto em rodízio semanal; produtos novos com limite diário. As listagens continuam diárias e completas, porque são elas que acham produtos novos e mantêm o "a partir de" de todos.
- **Esfriar após desafio (A).** Depois de um desafio resolvido, espera antes de voltar e segue mais devagar. Um segundo desafio no mesmo dia encerra o dia.
- Abordagem 1: sem tabela nova; a lista do dia é calculada a partir do banco.

## Lista do dia (etapa 2)

Calculada no início da etapa, no fuso de Configurações → Geral. Um produto aparece uma vez só, no primeiro grupo em que cair, nesta ordem:

1. **Casados**: produto ativo com par `confirmado` na tabela `casamento`.
2. **Com candidato**: produto ativo com par `pendente`.
3. **Novos**: produto ativo sem nenhum `resumo_preco`, os mais antigos (`visto_primeiro_em`) primeiro, até **"Produtos novos por dia"** (padrão 100).
4. **Rodízio**: os demais ativos com `id % 7` igual ao dia da semana (segunda = 0), ou seja, cada produto uma vez por semana.

O que já tem `resumo_preco` gravado hoje (desde a meia-noite no fuso) sai da lista. Assim um "Retomar" ou "Rodar agora" continua de onde parou e não relê o dia. Dentro de cada grupo a ordem é embaralhada, como hoje.

Volume esperado: ~50 casados + candidatos + até 100 novos + ~310 do rodízio, ou seja ~450–500 páginas/dia (~2–3 h), contra 2165 hoje.

## Esfriar após desafio

- "Desafios hoje" = coletas da Liga que terminaram `pausada_desafio` desde a meia-noite (fuso de Geral). Contado na tabela `coleta`, sem estado novo.
- **Primeiro desafio do dia:**
  - O fluxo atual continua igual: pausa, aviso `LIGA_DESAFIO` e navegador aberto para o noVNC.
  - Ao "Retomar", o agendador só começa o job depois de **"Esfriar após desafio (min)"** (padrão 30), contado da retomada.
  - No resto do dia, as pausas entre páginas usam o dobro de `pausa_min_s`/`pausa_max_s`.
- **Segundo desafio no mesmo dia:**
  - Pausa e aviso como sempre, e o aviso diz que a coleta só volta no dia seguinte.
  - Depois do "Retomar", o agendador não roda mais nada hoje e segue no horário normal de amanhã.
  - O que ficou da lista de hoje não passa para amanhã: casados e candidatos entram de novo; o grupo do rodízio que faltou espera a próxima semana.
- "Rodar agora" respeita as duas regras: espera o esfriamento e não roda após o segundo desafio do dia. A tela de Serviços diz até quando está esperando.

## Configuração (Configurações → LigaMagic)

Duas colunas novas em `config_liga` (migração Alembic, sem tabela nova):

| campo | padrão | limites |
|---|---|---|
| `esfriar_desafio_min` | 30 | 0–240 |
| `produtos_novos_dia` | 100 | 0–2000 |

A tela explica que só casados, candidatos, novos e o rodízio do dia são abertos, e que as listagens seguem completas.

## Avisos e telas

- Resumo do job (`LIGA_COLETA_CONCLUIDA`/`PARCIAL`): a linha de produtos passa a mostrar a lista do dia, por exemplo: "Produtos: ok · 480 de 482 · casados 52, candidatos 18, novos 100, rodízio 312".
- O aviso `LIGA_DESAFIO` diz se é o 1º do dia ("volta 30 min após retomar, mais devagar") ou o 2º ("volta amanhã no horário").
- Card da LigaMagic em Serviços e no Dashboard: "Esfriando até HH:MM" ou "Parada até amanhã (2º desafio)" quando for o caso.

## Erros

- Lista do dia vazia (tudo já lido hoje): a etapa fecha como `ok` com 0 produtos, sem abrir página.
- Esfriamento ou segundo desafio com o serviço reiniciado: o estado sai da tabela `coleta` e da hora da retomada (`estado_coletor.atualizado_em`), então o reinício não zera a espera.
- Produto que vira inativo no meio do dia sai da lista no próximo cálculo; a lista é recalculada a cada job.

## Testes

- Lista do dia: ordem dos grupos; um produto só uma vez; rodízio pelo dia da semana; teto de novos, os mais antigos primeiro; quem já foi lido hoje fica de fora.
- Retomar continua de onde parou, sem reler os lidos hoje.
- Primeiro desafio: o job só começa após `esfriar_desafio_min`, com pausas dobradas no resto do dia.
- Segundo desafio: nada roda até o dia seguinte, nem com "Rodar agora"; no dia seguinte roda no horário normal com as pausas normais.
- Reinício no meio do esfriamento mantém a espera.
- Migração: colunas com padrão e limites; downgrade remove.
- Resumo e avisos com os textos novos; suíte atual verde.

## Pendências geradas

- Acompanhar uma semana sem desafio com ~500 páginas/dia. Se o desafio voltar, baixar o rodízio, por exemplo para 14 dias, ou subir as pausas.
- O item "Uma semana de coletas da LigaMagic sem desafio" (seção 3) passa a medir este desenho.
