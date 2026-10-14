# Sub-projeto 2: coletor da Amazon, casamento de produtos e oportunidades

Data: 2026-10-14
Contexto: visão geral do monitor de arbitragem (documento de planejamento fora deste repositório) e o sub-projeto 1, em `2026-10-13-coletor-liga-design.md`.

## Objetivo

Comprar barato nos marketplaces e revender na LigaMagic. Este sub-projeto começa pela Amazon (amazon.com.br): procura cada produto ativo da Liga na Amazon, liga os anúncios ao produto certo da Liga com revisão humana, mostra as diferenças de preço entre a Amazon e a Liga e avisa o grupo de oportunidades do WhatsApp quando uma oferta confiável está pelo menos 25% abaixo do preço da Liga.

Critério de sucesso: uma semana de fila contínua na janela das 08:00 às 22:00 com a taxa de CAPTCHA medida e cada desafio avisado, resolvido pelo noVNC e retomado pelo admin; todo alerta enviado corresponde a um casamento confirmado, com vendedor elegível e desconto de pelo menos 25% sobre a Liga; nenhum alerta de anúncio não casado.

## Escopo

Dentro:

- Serviço `coletor-amazon`: fila contínua de buscas na Amazon, uma por produto ativo da Liga, pelo navegador.
- Casamento anúncio da Amazon (ASIN) ↔ produto da Liga, com fila de revisão no admin.
- Avaliação do vendedor pelo perfil público na Amazon.
- Motor de oportunidades: desconto sobre o "À partir de" da Liga, elegibilidade do vendedor, alerta sem repetição.
- Admin: casamentos, ofertas (diferenças Amazon × Liga), configurações da Amazon, estado do coletor da Amazon e seção Amazon na página do produto.
- Configuração da Amazon e do motor no banco, editável no admin.
- Extração do navegador compartilhado para um pacote próprio.

Fora (próximas specs):

- Cupons, cashback, frete, comissão da Liga e impostos no cálculo da margem.
- Mercado Livre e outros marketplaces (a estrutura deste sub-projeto serve para eles).
- Migrar para o banco a configuração da Liga, que continua no `.env`.
- Migração para servidor.

## Restrições

- As mesmas da Liga: navegador real (Chromium com janela, perfil persistente), pausa humana entre páginas, nada de solucionador de CAPTCHA, de disfarce de navegador ou de nova tentativa automática diante de desafio. CAPTCHA ou bloqueio pausam o coletor e avisam o grupo admin; uma pessoa resolve pelo noVNC.
- Sem API: tudo pelo navegador (decisão do grupo, já estudada).
- Volume: com 241 produtos ativos, cerca de 2.900 buscas por dia na janela das 08:00 às 22:00 (detalhes em "Volume estimado"). É bem acima da Liga; o ritmo tem teto configurável e é medido na primeira semana.
- Roda no mesmo PC Windows com Docker Desktop, no mesmo IP residencial da Liga.

## Decisões de 2026-10-14

1. Amazon primeiro (o documento de visão geral previa o Mercado Livre).
2. Tudo pelo navegador, sem API.
3. Desconto mínimo de 25% em relação ao "À partir de" atual da Liga: alerta quando `preço_amazon ≤ 0,75 × preço_liga`.
4. Uma busca na Amazon por produto ativo da Liga, numa fila contínua com ritmo limitado. A frequência é consequência do tamanho da lista: com 241 ativos, cada produto volta a cada ~70 minutos.
5. Janela de funcionamento: 08:00 às 22:00.
6. Ofertas válidas: vendido pela Amazon, ou lojista com envio pela Amazon (FBA) que seja confiável (pelo menos 90% de avaliações positivas e pelo menos 100 avaliações). Lojista com envio próprio não gera alerta.
7. Alerta no grupo de oportunidades, uma vez por oferta; repete só se o preço cair mais 5% ou se a oferta fechar e reabrir.
8. O termo de busca é o nome completo do produto na Liga, incluindo o tipo ("Caixa de Booster", "Booster Avulso", "Kit de Pré Lançamento"), só sem pontuação.
9. Configuração da Amazon e do motor no banco, editável no admin, valendo sem reiniciar. O `.env` fica só com segredos e infraestrutura.
10. Uma spec só para coletor, casamento e oportunidades.

## Arquitetura

Um serviço novo no `docker-compose.yml`, `coletor-amazon`, com a mesma imagem e o comando `tcg-sniper coletor-amazon`. Ele não depende do `coletor-liga`: os dois se comunicam só pelo Postgres, como o admin.

```
produto_liga (ativos) ──► fila_amazon ──► busca na Amazon ──► anuncio_amazon / preco_amazon
                                                │
                                   ASIN confirmado e barato
                                                ▼
                                 página do produto + perfil do vendedor
                                                ▼
                       motor de oportunidades ──► oportunidade ──► grupo de oportunidades
```

- Chromium próprio, com perfil em `<DIR_DADOS>/perfil-amazon`, separado do perfil da Liga.
- Área de trabalho virtual e noVNC próprios: o container expõe o noVNC na porta 6081 do host (a 6080 continua da Liga). A senha é a mesma `VNC_SENHA`.
- Advisory lock próprio no Postgres (ID diferente do da Liga): nunca dois `coletor-amazon` ao mesmo tempo; Liga e Amazon podem rodar juntos.
- Agendamento: o mesmo laço simples de 60 segundos da Liga, não APScheduler (a API síncrona do Playwright é presa à thread que a criou).

### Estrutura do pacote

```
src/tcg_sniper/
  navegador/            extraído de coletor_liga, sem mudança de comportamento
    navegador.py        Navegador (Protocol), NavegadorPlaywright
    modelos.py          Pagina, ErroRede
    ritmo.py            pausa humana, uma nova tentativa em erro de rede, salvar HTML com falha
  coletor_liga/         passa a importar de navegador/
  coletor_amazon/
    parsers.py          busca, página de produto, perfil do vendedor (funções puras)
    desafio.py          detecção de CAPTCHA e bloqueio da Amazon
    termo.py            nome da Liga → termo de busca
    fila.py             escolha do próximo produto, reagendamento, janela, teto por hora
    varredura.py        laço contínuo: busca, confirmação, vendedor, ciclo
    config.py           leitura e validação de config_amazon
  oportunidades/
    motor.py            elegibilidade, decisão abrir/atualizar/fechar/alertar (funções puras)
    mensagens.py        texto do alerta
  admin/                páginas novas (ver "Admin")
  db/                   modelos, repositório e migração novos
```

O `docker/coletor-entrypoint.sh` passa a receber o diretório do perfil por variável (`DIR_PERFIL`, padrão `<DIR_DADOS>/perfil`), para limpar os locks do Chromium do perfil certo. O serviço `coletor-amazon` define `DIR_PERFIL=/data/perfil-amazon`.

## Banco de dados

Migração nova do Alembic. Dinheiro em `NUMERIC(10,2)`, datas `timestamptz` em UTC, como no sub-projeto 1.

### `anuncio_amazon`

| Coluna | Tipo | Notas |
| --- | --- | --- |
| `id` | serial PK | |
| `asin` | text, único | |
| `titulo` | text | atualizado a cada leitura |
| `url` | text | `https://www.amazon.com.br/dp/<ASIN>` |
| `produto_id` | FK `produto_liga`, nulo | sugestão enquanto pendente; casamento quando confirmado |
| `status_casamento` | enum `pendente`, `confirmado`, `ignorado` | ASIN novo entra `pendente` |
| `revisado_em` | timestamptz, nulo | |
| `visto_primeiro_em`, `visto_ultimo_em` | timestamptz | |

Um ASIN casa com no máximo um produto da Liga; um produto da Liga pode ter vários ASINs.

### `vendedor_amazon`

| Coluna | Tipo | Notas |
| --- | --- | --- |
| `id` | serial PK | |
| `seller_id` | text, único | a Amazon como vendedora é a linha fixa `seller_id = 'amazon'` |
| `nome` | text | |
| `pct_positivas` | numeric(5,2), nulo | dos últimos 12 meses |
| `num_avaliacoes` | integer, nulo | |
| `avaliado_em` | timestamptz, nulo | |

"Confiável" é calculado na hora com os limites de `config_amazon`; não é guardado.

### `preco_amazon` (append-only)

| Coluna | Tipo | Notas |
| --- | --- | --- |
| `id` | serial PK | |
| `anuncio_id` | FK | |
| `coletado_em` | timestamptz | |
| `preco` | numeric(10,2), nulo | `NULL` quando o cartão ou a página não mostram preço |
| `origem` | enum `busca`, `produto` | |
| `vendedor_id` | FK, nulo | só com origem `produto` |
| `envio` | enum `amazon`, `fba`, `proprio`, `desconhecido` | `desconhecido` com origem `busca` |

Grava uma linha só quando o preço é diferente da última leitura do mesmo ASIN e da mesma origem, ou quando é a primeira leitura do dia (no fuso do `.env`). O mesmo ASIN repetido numa busca conta uma vez (vale o primeiro cartão).

### `preco_atual_amazon` (upsert)

Uma linha por anúncio: último `preco`, `origem`, `vendedor_id`, `envio` e `coletado_em`. Os campos de vendedor e envio só mudam numa leitura de origem `produto`. É a tabela que o admin e o motor leem.

### `fila_amazon`

| Coluna | Tipo | Notas |
| --- | --- | --- |
| `produto_id` | FK `produto_liga`, PK | |
| `proxima_busca_em` | timestamptz | produto novo na fila entra vencido |
| `ultima_busca_em` | timestamptz, nulo | |
| `ultimo_candidato_em` | timestamptz, nulo | última busca em que algum ASIN confirmado do produto ficou abaixo do limite de desconto |

A fila é sincronizada com os produtos ativos da Liga a cada passo do laço: ativado entra, desativado sai. Os anúncios e o histórico não são apagados.

### `oportunidade`

| Coluna | Tipo | Notas |
| --- | --- | --- |
| `id` | serial PK | |
| `anuncio_id`, `produto_id` | FK | |
| `preco_amazon`, `preco_liga` | numeric(10,2) | da última atualização |
| `desconto_pct` | numeric(5,2) | |
| `vendedor_id` | FK | |
| `envio` | enum | |
| `aberta_em` | timestamptz | |
| `alertada_em`, `preco_alertado` | timestamptz, numeric(10,2) | do último alerta enviado |
| `fechada_em` | timestamptz, nulo | aberta enquanto `NULL` |

No máximo uma oportunidade aberta por anúncio (índice único parcial em `anuncio_id` onde `fechada_em IS NULL`).

### `config_amazon`

Uma linha só (`CHECK id = 1`), criada pela migração com os padrões. Cada coluna tem `CHECK` com o limite aceito.

| Coluna | Padrão | Limite | Para quê |
| --- | --- | --- | --- |
| `url_busca` | `https://www.amazon.com.br/s?k={termo}` | contém `{termo}` | modelo da busca |
| `janela_inicio`, `janela_fim` | 08:00, 22:00 | início < fim | janela da fila contínua |
| `pausa_min_s`, `pausa_max_s` | 8, 20 | 0 ≤ mín ≤ máx ≤ 120 | pausa humana entre páginas |
| `resultados_por_busca` | 10 | 1 a 48 | cartões lidos por busca |
| `intervalo_busca_min` | 60 | 10 a 1440 | intervalo base entre buscas do mesmo produto |
| `max_buscas_hora` | 200 | 1 a 400 | teto de segurança do ritmo |
| `limite_falha_pct` | 50 | 0 a 100 | falhas num ciclo a partir das quais ele vira `falha` |
| `desconto_min_pct` | 25 | 1 a 90 | desconto mínimo sobre a Liga para alertar |
| `realerta_queda_pct` | 5 | 1 a 50 | queda extra que gera novo alerta |
| `liga_preco_max_idade_h` | 48 | 1 a 168 | idade máxima do "À partir de" usado como referência |
| `vendedor_min_positivas_pct` | 90 | 0 a 100 | critério de lojista FBA confiável |
| `vendedor_min_avaliacoes` | 100 | 0 a 100000 | idem |
| `vendedor_reavaliar_dias` | 7 | 1 a 90 | quando reler o perfil do vendedor |
| `atualizado_em` | | | |

O coletor relê a linha a cada busca e o motor a cada decisão: mudanças feitas no admin valem sem reiniciar.

### Mudanças em tabelas do sub-projeto 1

- `estado_coletor`: sai o `CHECK id = 1`; entra a coluna `coletor` (text, único, `liga` ou `amazon`). A migração marca a linha existente como `liga` e cria a linha `amazon` com estado `ativo`. Os coletores leem e gravam só a própria linha. O enum `estado_coletor_tipo` ganha `pausado` (pausa manual pelo admin ou por erros seguidos), além de `ativo` e `pausado_desafio`; o coletor da Liga já trata qualquer estado diferente de `ativo` como parado.
- `coleta`: o enum `tipo_coleta` ganha `amazon`. Cada ciclo da fila (uma passada por todos os produtos que estavam na fila quando ele começou) vira uma linha; `produtos_ok` e `produtos_falha` contam buscas.
- `marcar_interrompidas` passa a receber os tipos de coleta do coletor que está subindo: o reinício da Liga não fecha um ciclo da Amazon em andamento, nem o contrário.

## Fluxo da coleta

### Laço

A cada passo:

1. **Janela.** Fora de `janela_inicio`–`janela_fim` (no fuso do `.env`, com variação aleatória de até 15 minutos na entrada e na saída, sorteada uma vez por dia), fecha o navegador e dorme até a próxima abertura.
2. **Estado.** Com a linha `amazon` de `estado_coletor` diferente de `ativo`, verifica de novo em 1 minuto.
3. **Teto.** Se a última hora já teve `max_buscas_hora` buscas, dorme até liberar.
4. **Fila.** Sincroniza `fila_amazon` com os produtos ativos. Pega o produto com o `proxima_busca_em` mais antigo já vencido; no empate, o de maior "À partir de" na Liga primeiro. Sem nenhum vencido, dorme até o próximo vencer.
5. **Busca** (abaixo).
6. **Reagendamento.** `proxima_busca_em = agora + intervalo`, onde o intervalo é `intervalo_busca_min`, metade disso se `ultimo_candidato_em` for das últimas 24 h, ou o dobro se o produto não tiver candidato há 7 dias (ou nunca tiver tido, depois de 7 dias na fila).
7. **Ciclo.** Quando todos os produtos do ciclo atual foram buscados, o ciclo fecha (status pela regra de `limite_falha_pct`, como na Liga) e outro começa. Ciclo `falha` avisa o grupo admin.
8. **Oportunidades velhas.** Fecha as oportunidades abertas cujo anúncio não aparece em nenhuma leitura há 24 h.

### Busca de um produto

1. Monta o termo: o nome do produto na Liga com `-`, `–`, `:`, `(`, `)`, `/` e `,` trocados por espaço e os espaços repetidos juntados; o resto (tipo do produto, acentos, maiúsculas) fica como está. Ex.: "Caixa de Booster - Final Fantasy - Booster de Jogo" → "Caixa de Booster Final Fantasy Booster de Jogo".
2. Pausa humana e abre `url_busca` com o termo codificado.
3. Detecta CAPTCHA ou bloqueio (ver "Desafio").
4. Lê os primeiros `resultados_por_busca` cartões: ASIN, título, preço (ou `None`) e se é patrocinado. Página sem a grade de resultados → `ErroParser`; busca com zero resultados é sucesso com lista vazia.
5. Em uma transação: upsert em `anuncio_amazon` (ASIN novo entra `pendente`, com o produto buscado como sugestão), `preco_amazon` (regra de gravação acima) e `preco_atual_amazon`.
6. **Candidatos:** ASINs `confirmado` (para qualquer produto da Liga) cujo preço na busca está a pelo menos `desconto_min_pct` abaixo do "À partir de" do produto casado. ASIN `pendente` ou `ignorado` nunca abre outra página.
7. Para cada candidato: pausa, abre a página do produto e lê o preço da oferta principal, "Vendido por", "Enviado por" e o `seller_id`. Se for lojista sem avaliação ou com `avaliado_em` mais velho que `vendedor_reavaliar_dias`, pausa e abre o perfil dele. Grava preço (origem `produto`) e vendedor, e chama o motor.
8. Atualiza `ultima_busca_em` e, se houve candidato, `ultimo_candidato_em`.

Envio, pela página do produto: vendido pela Amazon → `amazon`; enviado pela Amazon e vendido por um lojista → `fba`; vendido e enviado por um lojista → `proprio`; sem a informação → `desconhecido`.

### Volume estimado

Com 241 produtos ativos e pausa média de 14 s mais o carregamento, cerca de 17 s por busca: ~210 buscas por hora, ~2.900 nas 14 horas da janela, e cada produto revisitado a cada ~70 minutos. Somam-se uma página por candidato e uma por vendedor a avaliar, que devem ser poucas. Com 500 ativos, cada produto volta a cada ~2h30. O teto `max_buscas_hora` (200) fica abaixo do ritmo natural de propósito e pode ser ajustado no admin depois da primeira semana.

### Desafio

`eh_desafio_amazon(pagina)` usa marcadores exclusivos da página de verificação da Amazon (o formulário de `validateCaptcha`, o texto "Digite os caracteres que você vê", a página de erro de bloqueio), definidos a partir de fixtures reais, como na Liga. Ao detectar:

1. Fecha o ciclo como `pausada_desafio`, com a URL no `erro`.
2. Marca a linha `amazon` de `estado_coletor` como `pausado_desafio`.
3. Avisa o grupo admin: "CAPTCHA na Amazon (<url>). Resolver em http://<HOST_PUBLICO>:6081/vnc.html e depois clicar em Retomar (Amazon) em http://<HOST_PUBLICO>:8000".
4. Mantém o Chromium aberto com a verificação na tela.

Sem nova tentativa automática. **Retomar (Amazon)** no admin volta a linha para `ativo`, e a fila continua de onde parou, no mesmo navegador.

### Tratamento de erros

| Situação | Ação |
| --- | --- |
| Página que não lê (`ErroParser`) | Salva o HTML em `<DIR_DADOS>/falhas/amazon-<ciclo>-<produto>.html`, conta falha da busca, segue. |
| Erro de rede | Uma nova tentativa depois de 30 s; depois conta falha. |
| Erro inesperado | Log, aviso no grupo admin, espera 15 minutos e continua. Três erros inesperados seguidos marcam a linha `amazon` como `pausado` (motivo "erros seguidos") e avisam; só volta com **Retomar (Amazon)**. |
| Reinício do container | A fila está no banco e continua de onde parou; o ciclo aberto é marcado como interrompido. |
| Falha de envio do WhatsApp | Como no sub-projeto 1: três tentativas, depois log; nunca interrompe a coleta. |

## Motor de oportunidades

Função pura chamada para cada candidato confirmado na página do produto, com: a leitura (preço, envio, vendedor), o preço da Liga do produto casado (`preco_a_partir` e `listagem_em`), o vendedor, a oportunidade aberta do anúncio (se houver) e `config_amazon`.

Elegível quando tudo vale:

1. **Vendedor:** envio `amazon`; ou envio `fba` com vendedor confiável (`pct_positivas ≥ vendedor_min_positivas_pct` e `num_avaliacoes ≥ vendedor_min_avaliacoes`). Envio `proprio` ou `desconhecido` nunca é elegível.
2. **Referência da Liga:** `preco_a_partir` não nulo e `listagem_em` com no máximo `liga_preco_max_idade_h` horas.
3. **Desconto:** `desconto = 1 − preço_amazon / preço_liga ≥ desconto_min_pct / 100` (o limite é inclusivo). Preço da Amazon nulo nunca é elegível.

| Situação | Ação |
| --- | --- |
| Elegível, sem oportunidade aberta | Abre e alerta. |
| Elegível, aberta, `preço ≤ preco_alertado × (1 − realerta_queda_pct / 100)` | Atualiza e alerta de novo. |
| Elegível, aberta, sem essa queda | Só atualiza. |
| Não elegível, aberta | Fecha. |

Alerta, no grupo de oportunidades (`WHATSAPP_GRUPO_OPORTUNIDADES`):

```
Oportunidade: Caixa de Booster - Final Fantasy - Booster de Jogo
Amazon: R$ 599,90 (vendido pela Amazon), 32% abaixo da Liga
Liga: a partir de R$ 889,00, 12 lojas, média de venda R$ 910,00
https://www.amazon.com.br/dp/B0XXXXXXXX
Admin: http://<HOST_PUBLICO>:8000/produto/123
```

Para lojista FBA a segunda linha diz "vendido por <nome> (97% de 2.340 avaliações), enviado pela Amazon". Número de lojas e média de venda vêm do resumo da Liga e são omitidos quando o produto não tem resumo. Sem `WHATSAPP_GRUPO_OPORTUNIDADES`, o alerta vai só para o log.

## Admin

- **Casamentos** (`/casamentos`): ASINs pendentes, cada um com título, preço atual, link da Amazon, a sugestão (o produto cuja busca o encontrou, com o "À partir de") e até 3 outros produtos do catálogo da Liga por semelhança de título (`difflib`, sem dependência nova). Primeiro os pendentes cujo preço está a pelo menos `desconto_min_pct` abaixo da sugestão; depois os demais, mais recentes primeiro. Ações: **Confirmar**, **Trocar** (escolher outro produto, com busca no catálogo) e **Ignorar**. Uma aba lista os confirmados e ignorados, com **Desfazer** (volta para pendente e fecha as oportunidades abertas do anúncio).
- **Ofertas** (`/ofertas`): uma linha por produto da Liga com pelo menos um ASIN confirmado: "À partir de" da Liga, melhor oferta atual da Amazon (preço, envio, vendedor e se é confiável, data da leitura) e a diferença em %. Ordenada pelo maior desconto; filtros "só ≥ desconto mínimo" e "só oportunidades abertas".
- **Configurações** (`/configuracoes`): formulário com os valores de `config_amazon`, uma explicação curta por campo e validação com os mesmos limites do banco. Valor inválido volta com a mensagem e não grava nada.
- **Produto** (`/produto/<id>`): seção Amazon com os ASINs casados, preço atual, vendedor, envio e histórico de `preco_amazon`.
- **Início** (`/`): estado do coletor da Amazon (ativo, pausado, fora da janela, motivo), ciclo atual (buscas feitas e falhas), botões **Pausar (Amazon)** e **Retomar (Amazon)** e o link do noVNC da Amazon.

## Configuração (`.env`)

Nenhuma variável nova de comportamento: o que controla a Amazon e o motor está em `config_amazon`. O `.env` continua só com segredos e infraestrutura; `WHATSAPP_GRUPO_OPORTUNIDADES` passa a ser usado. O `docker-compose.yml` ganha o serviço `coletor-amazon` (porta `6081:6080`, `DIR_PERFIL=/data/perfil-amazon`, `shm_size: 1gb`, `init: true`, `hostname: coletor-amazon`).

## Testes

Nenhum teste acessa a Amazon nem o WhatsApp reais.

- **Fixtures reais**, capturadas à mão, uma por vez e com pausa, e recortadas com `scripts/recortar_fixture.py` (que ganha os blocos da Amazon) antes do commit: busca com resultados (com patrocinado e com cartão sem preço), busca sem resultados, produto vendido pela Amazon, produto de lojista FBA, produto de lojista com envio próprio, produto indisponível, perfil de vendedor e página de CAPTCHA. `scripts/capturar_fixture.py` passa a escolher a detecção de desafio pelo domínio da URL.
- **Parsers:** preço com inteiro e centavos em elementos separados vira `Decimal` exato; cartão ou página sem preço → `None`, nunca zero; layout novo → `ErroParser`; ASIN, vendido por, enviado por, `seller_id`, % de positivas e número de avaliações.
- **Desafio:** nenhuma fixture normal é desafio; a de CAPTCHA é.
- **Termo de busca:** tabela de nomes reais da Liga e o termo esperado.
- **Fila e janela:** escolha pelo vencido mais antigo e desempate pelo preço da Liga; metade e dobro do intervalo; janela com variação no fuso certo; teto por hora; sincronização com ativação e desativação na Liga. Relógio falso.
- **Motor** (tabela de casos): Amazon; FBA confiável; FBA com 89% ou com 99 avaliações; envio próprio e desconhecido; preço da Liga nulo e com 49 h; desconto de exatamente 25% (elegível) e de 24,99%; preço da Amazon nulo; novo alerta com queda de exatamente 5% e sem alerta com 4,9%; fechamento.
- **Banco:** preço gravado só quando muda ou na primeira leitura do dia; ASIN repetido na mesma busca; uma oportunidade aberta por anúncio; migração preserva a linha `liga` de `estado_coletor` e cria a `amazon`; `config_amazon` recusa valores fora dos limites; `marcar_interrompidas` respeita o tipo.
- **Varredura com navegador falso:** CAPTCHA pausa, mantém o navegador aberto e avisa o admin; parser que falha salva o HTML e segue; candidato abre produto e, se preciso, vendedor; pendente e ignorado não abrem nada; ciclo fecha e ciclo `falha` avisa; três erros seguidos pausam; mudança em `config_amazon` vale na busca seguinte.
- **Admin:** casamentos (confirmar, trocar, ignorar, desfazer fecha oportunidade), ofertas (ordem e filtros), configurações (valida e grava), início e produto com a parte da Amazon.
- **Extração do navegador:** a suíte da Liga continua passando, mudando só os imports.

## Pontos em aberto

- **CEP na Amazon:** preço, disponibilidade e "Enviado por" podem depender do CEP. Antes da primeira varredura, alguém abre o noVNC da Amazon e define o CEP no perfil `perfil-amazon` (fica salvo nos cookies). Confirmar nas fixtures se a página mostra o CEP, para o coletor avisar quando ele não estiver definido.
- **Busca com resultados irrelevantes:** a Amazon mistura acessórios, sleeves e cartas avulsas nos resultados. Eles entram como pendentes e são ignorados na revisão; medir na primeira semana quantos pendentes por busca aparecem e, se a fila de revisão ficar grande demais, reduzir `resultados_por_busca`.
- **Taxa de CAPTCHA:** desconhecida até rodar. Se virar rotina, diminuir a lista de ativos, o teto por hora ou aumentar as pausas.
- **Preço do resultado × preço da página:** o cartão da busca pode mostrar o preço de outra oferta. Por isso o alerta sempre usa o preço lido na página do produto.
