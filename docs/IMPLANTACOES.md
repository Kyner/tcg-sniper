# Notas de implantação

Passos extras de cada versão que muda o banco ou o jeito de subir os serviços, para quem já tem uma instalação rodando. A regra geral (backup, `git pull`, `docker compose up -d --build` com todos os serviços juntos) está no [README](../README.md#atualizar-uma-instalação-existente). Instalação nova não precisa de nada daqui: o `migrate` aplica todas as migrações na primeira subida.

Da mais nova para a mais antiga.


## Site novo, fase 3B: Serviços, Atividade e Dashboard (em construção)

Uma migração, só de índices (`d6a2f8c4b1e9`: instante de `coleta`, `oferta_amazon`, `conferencia_checkout`, `mensagem_saida` (criada e enviada), `resumo_preco`, `execucao_manutencao` e `estado_aviso`), para a Atividade e o estado dos serviços não lerem as tabelas grandes inteiras. Nada é apagado nem reescrito, mas a criação dos índices em `oferta_amazon` e `resumo_preco` pode levar alguns segundos.

1. Backup do banco antes do deploy:

   ```bash
   mkdir -p dados/backups
   docker compose exec -T postgres pg_dump -U tcg -Fc tcg > dados/backups/tcg-antes-3b-<data>.dump
   ```

2. `docker compose up -d --build`, como sempre (o `migrate` cria os índices).


## Segurança, etapa 1 (2026-10-24, implantada às 22:10)

Sem migração. Mudam as portas do admin antigo e do noVNC (agora só neste PC por padrão), o login (sem o limite total de 20 pedidos por hora; ficam os limites por número) e a limpeza diária (sessões encerradas ou vencidas há mais de 30 dias).

1. `docker compose up -d --build`, como sempre. No `.env`, `ADMIN_ESCUTA` e `VNC_ESCUTA` podem ficar de fora ou vazias (só neste PC); `0.0.0.0` reabre para a rede de casa.
2. Em Configurações → Geral, se "IP ou nome deste PC na rede" estiver com o IP da rede, troque para `127.0.0.1`: senão os links do noVNC no admin antigo não abrem.
3. Confira neste PC: `http://localhost:8000`, `http://localhost:6080/vnc.html`, `:6081` e `:6082` abrem; de outro aparelho da rede, não abrem mais.
4. Entre no site (`http://localhost:8090`) pelo código do WhatsApp normalmente.

## Monitor da Amazon com prioridade por grupo (2026-10-23, implantado às 13:28)

Sai no mesmo deploy das atualizações de segurança (seção abaixo), numa subida só; a produção ficou parada de propósito até este deploy.

1. Backup do banco antes de tudo (há duas migrações novas: `c5e1a8d3f7b2`, que acrescenta `monitor_esgotado_dias` a `config_amazon`, padrão 7 dias, e `e7b3d9f1a4c6`, que acrescenta `monitor_lido_em` a `anuncio_amazon` e a preenche com a última leitura das ofertas de cada anúncio):

   ```bash
   mkdir -p dados/backups
   docker compose exec -T postgres pg_dump -U tcg -Fc tcg > dados/backups/tcg-antes-monitor-prioridade-<data>.dump
   ```

2. Atualize o código e recrie **todos** os serviços de uma vez:

   ```bash
   git pull
   docker compose up -d --build
   ```

3. Em Configurações → Amazon, volte "Fila rápida: ler a cada (min)" para **15** (foi subido para 30 provisoriamente em 2026-10-22, enquanto o monitor estava atrasado).
4. Confira:
   - o card do monitor em Serviços mostra as contagens "rápida · lenta · esgotado" (e "nunca lidos" quando houver);
   - o aviso "atrasado" vale só para a fila rápida: anúncios do grupo lento ou esgotados com leitura antiga não o acendem;
   - no site novo, Gestão → Catálogo → filtro "Preço na Liga" → "Esgotado (com anúncio casado)" lista só produtos monitorados, para decidir o que fazer com eles;
   - o aviso "Amazon · rodada do monitor" sai no máximo uma vez por hora (somando as voltas da fila rápida, que fecham a cada ~15 min), começando por "Voltas da fila rápida: N".

## Atualizações de segurança (2026-10-23, implantadas às 13:28)

Vão no mesmo deploy do monitor por grupo (a produção ficou parada de propósito até aqui). Sem migração própria (as do monitor pedem o backup).

1. `docker compose up -d --build`, como sempre. O `uv.lock` mudou, então o Docker refaz a instalação das dependências e a do Chromium do Playwright 1.64.1 (o `playwright install` vem depois do `uv sync` no `Dockerfile`); a primeira construção demora mais.
2. Confira: os três noVNC abrem (`:6080`, `:6081`, `:6082`) e a Amazon segue logada no monitor; Logs → Manutenção sem erro de imagem na primeira rodada de cópia das fotos (Pillow 13; formato fora de JPEG/PNG/WEBP/GIF agora é recusado e só aparece como falha daquele item); o site (`:8090`) abre normalmente (build com Node 24.22.1).

## Site novo, fase 3A: Casamentos e Catálogo na gestão (2026-10-22, implantada às 11:37)

1. Backup do banco antes de tudo (há migração nova: `a1c4e7b9d2f6`, tabela `acao_gestao`, o registro das ações da gestão):

   ```bash
   mkdir -p dados/backups
   docker compose exec -T postgres pg_dump -U tcg -Fc tcg > dados/backups/tcg-antes-fase3a-<data>.dump
   ```

2. Atualize o código e recrie **todos** os serviços de uma vez (o `migrate` aplica a migração antes):

   ```bash
   git pull
   docker compose up -d --build
   ```

3. Confira no site novo (`http://localhost:8090`), entrando como operador ou admin:
   - o menu Gestão aparece com Casamentos (com o selo da quantidade esperando decisão) e Catálogo;
   - Gestão → Casamentos lista os produtos esperando decisão; "Revisar em sequência" abre o primeiro, confirmar um anúncio move o cartão para Confirmados sem recarregar, "Próximo" segue e "Voltar à lista" mantém os filtros;
   - Gestão → Catálogo: ligar e desligar um produto pela chave. O lote (marcar, Desligar, ver o número exato no modal) pode ser conferido com um filtro que traga poucos produtos, e desfeito com Ligar.
4. Layout: o `verificar_layout.py` agora inclui `/gestao/casamentos` e `/gestao/catalogo` (veja o README, seção de testes, para rodar contra o site novo). As telas por produto (`/gestao/casamentos/<id>` e `/gestao/produtos/<id>`) o script não alcança, porque dependem de um id: confira à mão, no tamanho de celular (390 px), um produto de nome longo e outro sem foto, sem barra de rolagem horizontal. O teste ponta a ponta (`tests/e2e`) já cobre essas telas com dados de teste.

## Oportunidades na área de negócio (2026-10-21)

Faça o backup de sempre antes (ver [Backup do banco](../README.md#backup-do-banco)). A migração `f3b8d1c7a9e2` acrescenta a `config_amazon` o piso da quase oportunidade (padrão 10%), cria um índice no `preco_amazon` (leva alguns segundos com o histórico atual) e acrescenta as colunas da cópia das imagens.

**Bucket de imagens**, no painel da Cloudflare:

1. R2 → criar o bucket `tcg-sniper-imagens`. É um bucket **novo**: o dos backups nunca fica público.
2. Settings → Public access → habilitar o endereço `r2.dev` (com domínio próprio: Custom Domains → `img.<domínio>`).
3. Token do R2 com "Object Read & Write" só nesse bucket (ou incluir o bucket no token atual).
4. No `.env`: `R2_BUCKET_IMAGENS`, `URL_PUBLICA_IMAGENS` (o endereço do passo 2, sem barra no fim) e, se o token for outro, `R2_IMAGENS_ACCESS_KEY_ID` e `R2_IMAGENS_SECRET_ACCESS_KEY`.

Suba tudo junto (`docker compose up -d --build`). A primeira passada copia as imagens em lotes (100 por hora, as das oportunidades primeiro). Confira em Configurações → Amazon o campo "Quase oportunidade a partir de (%)" e a tela `/` do site novo (Oportunidades).

## Fim da oportunidade (2026-10-20)

Faça o backup de sempre antes (ver [Backup do banco](../README.md#backup-do-banco)). A migração `e7c3a9d5b2f4` acrescenta à `oportunidade` o motivo de encerramento, o risco (carência), o menor preço, a contagem de alertas, a mensagem do alerta e quando a oportunidade deixou de valer (`deixou_de_valer_em`: a primeira leitura ruim ou, sem carência, o encerramento), e a `config_amazon` a carência (30 min). As oportunidades abertas na hora da migração ficam marcadas como "alerta sem registro": quando encerrarem, o grupo recebe o aviso. Suba tudo junto (`docker compose up -d --build`) e confira em Configurações → Amazon → Monitor de preço o campo "Carência para encerrar uma oportunidade (min)" e em Configurações → Avisos os três avisos novos (oferta encerrada, alerta corrigido, oportunidade encerrada técnico), ligados.

## Leitura por interesse da LigaMagic (2026-10-19)

Faça o backup de sempre antes (ver [Backup do banco](../README.md#backup-do-banco)). A migração `d4b8e2f6a3c1` acrescenta a `config_liga` o esfriar após desafio (30 min) e os produtos novos por dia (100). Suba tudo junto (`docker compose up -d --build`) e confira em Configurações → LigaMagic os dois campos novos. Se a LigaMagic estiver parada num desafio, resolva-o no noVNC (`http://<IP deste PC>:6080/vnc.html`) se a verificação ainda estiver na tela e clique em **Retomar**: o coletor espera 30 min (`esfriar_desafio_min`) antes da primeira página, e o card mostra "Esfriando até HH:MM" (ou "Parada até amanhã (2º desafio)" se já houve dois desafios hoje). No dia seguinte, o resumo no grupo admin traz a linha "Produtos: ok · N de M · casados …, candidatos …, novos …, rodízio …".

## Casamento por par (2026-10-19)

A migração `a9d4f2c6e8b1` cria a tabela `casamento` (um par por anúncio, com o mesmo status, origem e datas de antes) e a `termo_busca`, confere que nenhum anúncio ficou com dois confirmados (se ficar, aborta sem mudar nada) e remove as colunas antigas do casamento em `anuncio_amazon` (e `fila_amazon.ultimo_termo_en`). Tudo numa transação: um erro desfaz tudo. Voltar esta migração (downgrade) refaz as colunas antigas com um produto por anúncio (o confirmado ou, sem confirmado, o par mais antigo) e apaga `casamento`, `termo_busca` e os termos gerados; para voltar ao estado exato de antes, restaure o backup do passo 2.

1. Pare os serviços do app (o banco e o WhatsApp continuam no ar), para nenhum container antigo gravar nas tabelas enquanto você faz o backup e a migração as muda:

   ```bash
   docker compose stop coletor-liga coletor-amazon coletor-amazon-busca casador notificador manutencao admin api web
   ```

   Se desistir da implantação antes do passo 4, volte com `docker compose up -d` (sem `--build`, o código de antes).

2. Backup do banco:

   ```bash
   mkdir -p dados/backups
   docker compose exec -T postgres pg_dump -U tcg -Fc tcg > dados/backups/tcg-antes-casamento-por-par-<data>.dump
   ```

3. Conferência antes de migrar. Anote as contagens por situação (são o número de referência do passo 6) e confira que nenhum anúncio está sem produto (anúncio sem produto não vira par; o resultado tem de ser 0; se não for, pare e investigue antes de seguir):

   ```bash
   docker compose exec -T postgres psql -U tcg -d tcg -c "SELECT status_casamento, count(*) FROM anuncio_amazon WHERE produto_id IS NOT NULL GROUP BY 1 ORDER BY 1"
   docker compose exec -T postgres psql -U tcg -d tcg -c "SELECT count(*) FROM anuncio_amazon WHERE produto_id IS NULL"
   ```

4. Atualize e recrie todos os serviços de uma vez (o `migrate` atualiza o banco antes; os serviços parados no passo 1 voltam já com o código novo):

   ```bash
   git pull
   docker compose up -d --build
   ```

   Se o `migrate` falhar com "mais de um casamento confirmado", nada mudou no banco: anote os ids da mensagem e pare (os serviços com código novo não funcionam com o banco antigo; volte para o commit anterior e rode `docker compose up -d --build` de novo).

5. Confira que a migração rodou: `docker compose logs migrate` termina sem erro.
6. Compare com as contagens do passo 3 (têm de bater, situação por situação):

   ```bash
   docker compose exec -T postgres psql -U tcg -d tcg -c "SELECT status, count(*) FROM casamento GROUP BY 1 ORDER BY 1"
   ```

7. No admin: Dashboard e Casamentos com os mesmos números de antes; a tela de um produto em Casamentos mostra os botões Rebuscar agora, Reavaliar com a IA e, em produto ainda sem casamento, Gerar termos de busca. A contagem dos 7 dias sem anúncio novo da busca alternativa começa na implantação: a IA só gera termos sozinha uma semana depois.
8. Regra de idioma revista: devolva à IA os pares que o automático ignorou por serem em inglês. Primeiro a simulação (só mostra as contagens), depois aplique:

   ```bash
   docker compose exec casador tcg-sniper casamento reabrir-ingles
   docker compose exec casador tcg-sniper casamento reabrir-ingles --aplicar
   ```

   Só pares ignorados pelo automático (com o motivo da IA falando de inglês ou idioma, e não de japonês) voltam a pendente; suas decisões não mudam. Anúncio já confirmado em outro produto fica ignorado.

## Busca da Amazon separada do monitor (2026-10-19)

Faça o backup de sempre antes (ver [Backup do banco](../README.md#backup-do-banco)). A migração `c6a2f8e4d1b9` cria o estado do serviço `amazon_busca` (ativo), baixa os tetos para no máximo 90 buscas por hora (busca) e 180 páginas por hora (monitor) — um valor seu menor fica — e fecha como interrompido um ciclo de busca que estiver rodando. Suba tudo junto (`docker compose up -d --build`) e confira: `docker compose ps` com `coletor-amazon` e `coletor-amazon-busca` de pé, os dois cards da Amazon em Serviços, e `http://<IP deste PC>:6082/vnc.html` abrindo (informe o CEP também nesse navegador). O primeiro CAPTCHA do navegador novo é provável: o grupo admin recebe "Amazon (busca) · CAPTCHA"; resolva no noVNC 6082 e clique em Retomar no card Amazon (busca). O monitor não para.

Depois do deploy, confira Serviços → Amazon (monitor e checkout): se aparecer pausado (um CAPTCHA de antes da separação), resolva pelo noVNC 6081 e clique em Retomar.

## Site novo (front) e login pelo WhatsApp

1. Backup do banco antes de tudo:

   ```bash
   mkdir -p dados/backups
   docker compose exec -T postgres pg_dump -U tcg -Fc tcg > dados/backups/tcg-antes-front-<data>.dump
   ```

2. Atualize o código: `git pull`.
3. Ponha uma `SEGREDO_API` de 32 caracteres ou mais no `.env` (como no [passo 2 do README](../README.md#2-crie-o-env)). Sem ela (ou com o valor de exemplo `trocar-este-segredo`) a `api` não sobe e diz o que fazer.
4. Recrie **todos** os serviços de uma vez (o `migrate` atualiza o banco antes). Nunca só `api` e `web`: o `notificador` antigo não conhece o destino novo das mensagens individuais e mandaria o código de acesso para o grupo de oportunidades.

   ```bash
   docker compose up -d --build
   ```

5. Siga o [passo 11 do README](../README.md#11-site-novo-e-login-pelo-whatsapp) a partir da criação do superadmin.

## Monitor de preço e conferência de checkout

1. Backup do banco antes de tudo:

   ```bash
   mkdir -p dados/backups
   docker compose exec -T postgres pg_dump -U tcg -Fc tcg > dados/backups/tcg-antes-monitor-<data>.dump
   ```

2. Atualize e recrie todos os serviços de uma vez (o `migrate` atualiza o banco antes):

   ```bash
   git pull
   docker compose up -d --build
   ```

3. Confira: em Configurações → Amazon, a seção "Monitor de preço" com os padrões (15 min, 08:00–22:00, 150 páginas por hora, margem 5, validade 6 h, descoberta dos casados a cada 7 dias); em Serviços, os interruptores do monitor e da conferência ligados e os cards Amazon (busca) e Amazon (monitor e checkout) ligados.
4. Faça login na conta Amazon pelo noVNC (`http://<IP deste PC>:6081/vnc.html`). Sem login, a primeira conferência fica `sem_login`, o grupo admin é avisado e o monitor segue.
5. Na primeira hora: Logs → Monitor com leituras chegando; Dashboard sem o aviso de "monitor não cabe no intervalo"; Logs → Checkout com as primeiras conferências e nenhuma marcada "item no carrinho".
