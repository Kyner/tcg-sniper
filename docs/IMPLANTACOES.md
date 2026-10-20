# Notas de implantação

Passos extras de cada versão que muda o banco ou o jeito de subir os serviços, para quem já tem uma instalação rodando. A regra geral (backup, `git pull`, `docker compose up -d --build` com todos os serviços juntos) está no [README](../README.md#atualizar-uma-instalação-existente). Instalação nova não precisa de nada daqui: o `migrate` aplica todas as migrações na primeira subida.

Da mais nova para a mais antiga.

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
