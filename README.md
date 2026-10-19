# tcg-sniper

Monitor de preços de produtos selados de Magic: The Gathering (boosters, caixas, kits) na [LigaMagic](https://www.ligamagic.com.br). Uma vez por dia ele lê o catálogo de selados com o menor preço anunciado de cada produto e, para os produtos que você escolher acompanhar, guarda o histórico de venda e o número de lojas. Você administra tudo por uma página web e recebe os avisos num grupo de WhatsApp.

É o primeiro pedaço de um monitor de arbitragem: ele já compara o preço da LigaMagic com o da Amazon e avisa quando há uma oferta bem abaixo; outros marketplaces vêm depois (ver [Roadmap](#roadmap)).

**Estado:** a coleta da LigaMagic, o admin e os avisos no WhatsApp estão prontos e rodando no dia a dia. O sub-projeto 2 (coletor da Amazon, casamento de produtos e oportunidades) também está pronto.

## Índice

- [Uso responsável](#uso-responsável)
- [Como funciona](#como-funciona)
- [Pré-requisitos](#pré-requisitos)
- [Instalação passo a passo](#instalação-passo-a-passo)
- [Atualizar uma instalação existente](#atualizar-uma-instalação-existente)
- [Uso no dia a dia](#uso-no-dia-a-dia)
- [Configuração](#configuração)
- [Solução de problemas](#solução-de-problemas)
- [Desenvolvimento](#desenvolvimento)
- [Roadmap](#roadmap)
- [Licença](#licença)

## Uso responsável

O tcg-sniper foi feito para acessar a LigaMagic como uma pessoa acessaria, em volume baixo:

- **Um acesso por vez, com pausa humana.** Entre uma página e outra há uma pausa aleatória de 8 a 20 segundos. A coleta roda uma vez por dia e nunca há duas ao mesmo tempo.
- **Navegador de verdade.** Usa o Chromium com janela (não headless), com perfil persistente, no seu próprio PC e na sua conexão.
- **Sem burlar proteções.** Não há solucionador de CAPTCHA nem disfarce de navegador. Se o Cloudflare mostrar uma verificação, a coleta pausa, avisa você e espera que uma pessoa a resolva.
- **Amazon com teto e horário.** Na Amazon, a fila tem teto de buscas por hora (200 por padrão) e só roda de 08:00 às 22:00; CAPTCHA pausa a fila até uma pessoa resolver.
- **Só o que a página mostra em texto.** Lê o preço "À partir de" das listagens e o quadro de resumo da página do produto. Os preços de cada loja são desenhados como imagem na página e nunca são decodificados.

Respeite os termos de uso da LigaMagic e não aumente o ritmo da coleta. Este projeto não é afiliado à LigaMagic nem à Wizards of the Coast; Magic: The Gathering é marca da Wizards of the Coast.

## Como funciona

```mermaid
flowchart LR
    liga[(LigaMagic)]
    amazon[(amazon.com.br)]
    subgraph pc[Seu PC - Docker Compose]
        coletor[coletor-liga<br/>Chromium + agendador]
        coletor_amz[coletor-amazon<br/>Chromium: monitor de preço,<br/>conferência de checkout e busca]
        admin[admin<br/>página web :8000]
        db[(Postgres)]
        evo[Evolution API]
        vnc[noVNC :6080]
        vnc_amz[noVNC :6081]
    end
    whats[Grupos admin e<br/>oportunidades no WhatsApp]

    coletor -- uma visita por vez --> liga
    coletor --> db
    admin --> db
    coletor --> evo --> whats
    coletor_amz -- uma página por vez --> amazon
    coletor_amz --> db
    coletor_amz --> evo
    vnc -. tela do Chromium .- coletor
    vnc_amz -. tela do Chromium .- coletor_amz
```

Todo dia, por volta das 10:00:

1. **Listagens.** O coletor abre a listagem de cada categoria de selados (20 por padrão) e clica em "Exibir mais" até mostrar tudo. Daí saem o catálogo e o preço "À partir de" atual de cada produto.
2. **Produtos ativos.** Depois abre a página de cada produto que você marcou como ativo no admin e guarda o número de lojas e o resumo do histórico de venda (mínimo, médio e máximo).
3. **Aviso.** No fim, manda um resumo para o grupo admin do WhatsApp.
4. **Desafio do Cloudflare.** Se aparecer uma verificação no meio do caminho, a coleta pausa e avisa o grupo. Você resolve a verificação pela tela remota (noVNC) e clica em **Retomar** em Serviços.

**Amazon.** De 08:00 às 22:00 o `coletor-amazon` procura cada produto ativo na amazon.com.br, um por vez, com pausa humana. Quando a LigaMagic mostra o nome do produto em inglês, a busca alterna entre o nome em português e o nome em inglês a cada passada; um produto sem casamento que passa 7 dias sem achar anúncio novo ganha de 2 a 3 termos de busca alternativos sugeridos pela IA (uma vez, dentro do teto de gasto), que entram no rodízio até aparecer anúncio novo. Cada anúncio achado vira um par (anúncio × produto) pendente em **Casamentos**; ignorar vale só para aquele par (o mesmo anúncio achado na busca de outro produto volta a ser pendente para ele), e um anúncio é confirmado para no máximo um produto. Só pares confirmados geram oportunidade. Quando uma oferta vendida pela Amazon (ou por lojista confiável com envio pela Amazon) fica abaixo do "À partir de" da Liga pelo menos o desconto mínimo de Configurações → Amazon (padrão 25%), o grupo de oportunidades recebe um aviso. Ofertas vendidas pela "Amazon Global" (importadas pela própria Amazon) contam como vendidas pela Amazon e também geram aviso; o prazo é mais longo e o imposto de importação pode ser cobrado à parte do preço mostrado. Os anúncios confirmados têm o preço lido pelo **monitor de preço** a cada 15 min, e as melhores ofertas passam pela **conferência de checkout** (ver [Monitor de preço e conferência de checkout](#10-monitor-de-preço-e-conferência-de-checkout)). Tudo isso se ajusta em **Configurações** no admin (seções Geral, LigaMagic e Amazon; os valores ficam no banco, não no `.env`).

O `notificador` envia as mensagens da tabela de saída pela Evolution a cada 5 s; se a Evolution ou o WhatsApp estiverem fora, tenta de novo (1, 2, 4… até 30 min). Oportunidades que não saírem em até a validade de Configurações → Geral (padrão 6 h) ficam como expiradas; avisos do admin saem sempre.

Os serviços conversam só pelo banco: o admin grava pedidos ("retomar", "rodar agora") e o coletor os lê a cada minuto.

## Pré-requisitos

- **Um PC que fique ligado no horário da coleta.** Foi feito para Windows com Docker Desktop; também funciona em Linux e macOS.
- **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** (ou Docker Engine com o plugin Compose).
- **[Git](https://git-scm.com/downloads).** No Windows, o Git traz o **Git Bash**: use-o para os comandos deste README.
- **Um chip de WhatsApp secundário.** Nunca use um número pessoal ou de loja: o número fica conectado à Evolution API e manda as mensagens do grupo.
- **Um grupo de WhatsApp de administração**, com você e esse número secundário.

Para desenvolver (opcional): Python 3.12 e [uv](https://docs.astral.sh/uv/). Ver [Desenvolvimento](#desenvolvimento).

## Instalação passo a passo

### 1. Baixe o projeto

```bash
git clone https://github.com/Kyner/tcg-sniper.git
cd tcg-sniper
```

### 2. Crie o `.env`

```bash
cp .env.example .env
```

Abra o `.env` num editor e troque pelo menos:

| Variável | O que colocar |
| --- | --- |
| `ADMIN_SENHA` | Senha da página de admin. |
| `VNC_SENHA` | Senha da tela remota do Chromium. Só os 8 primeiros caracteres valem. |
| `EVOLUTION_API_KEY` | Uma chave longa e aleatória, inventada por você. |

O IP deste PC, a instância e os grupos do WhatsApp não ficam no `.env`: você os preenche em **Configurações** no admin (passos 4 e 5). Cada variável do `.env` está explicada no próprio [`.env.example`](.env.example).

### 3. Suba o banco, a Evolution API, o admin e o notificador

O coletor fica para o passo 6: ao subir, ele já acessa a LigaMagic.

```bash
docker compose up -d --build postgres evolution migrate admin notificador manutencao
```

**Deu certo se** `docker compose ps -a` mostrar `postgres`, `evolution`, `admin`, `notificador` e `manutencao` em `Up` e `migrate` em `Exited (0)`, e **Serviços** no admin mostrar o Notificador "rodando". Enquanto o WhatsApp não estiver configurado (passos 4 e 5), as mensagens esperam em **Mensagens**, com o motivo em "Último erro".

### 4. Conecte o WhatsApp

Carregue a chave do `.env` no terminal e crie a instância (use um nome sem espaços, igual ao campo **Instância da Evolution API** em **Configurações** → Geral):

```bash
set -a; . ./.env; set +a

curl -X POST http://localhost:8080/instance/create \
  -H "apikey: $EVOLUTION_API_KEY" -H "Content-Type: application/json" \
  -d '{"instanceName":"tcg-sniper","integration":"WHATSAPP-BAILEYS","qrcode":true}'
```

A resposta traz um QR code (em base64). O jeito mais fácil de lê-lo é pelo painel da Evolution, em http://localhost:8080/manager (entre com a `EVOLUTION_API_KEY`): abra a instância `tcg-sniper`, gere o QR code e leia com o WhatsApp do chip secundário (Aparelhos conectados > Conectar um aparelho).

**Deu certo se** a instância aparecer como conectada no painel.

### 5. Descubra o ID do grupo admin

Com o número secundário já no grupo admin:

```bash
curl "http://localhost:8080/group/fetchAllGroups/tcg-sniper?getParticipants=false" \
  -H "apikey: $EVOLUTION_API_KEY"
```

Procure o grupo pelo nome (`subject`) e copie o `id`, que termina em `@g.us`. Abra o admin em `http://<IP deste PC>:8000/configuracoes` e, em **Configurações** → Geral, cole-o em **Grupo de WhatsApp do admin**. Aproveite para preencher **IP ou nome deste PC na rede** (no Windows: `ipconfig`, "Endereço IPv4") e **Instância da Evolution API**. Salve: não precisa reiniciar nada.

### 6. Suba o coletor

Faça isso quando puder acompanhar a primeira coleta:

```bash
docker compose up -d --build coletor-liga
```

**Deu certo se** `docker compose logs coletor-liga --tail 20` mostrar `agendador iniciado`, sem erro.

Na primeira vez, como ainda não há nenhuma coleta, ela começa sozinha em até 30 minutos (não espera as 10:00). Para começar já, use **Rodar agora** em Serviços (passo 7). As listagens de todas as categorias levam cerca de 20 minutos. Dá para acompanhar o Chromium trabalhando pelo noVNC: `http://<IP deste PC>:6080/vnc.html`, com a `VNC_SENHA`.

Ao final, o grupo admin recebe "🟡 Liga · produtos novos no catálogo" e "✅ Liga · coleta concluída".

### 7. Escolha os produtos que quer acompanhar

Abra o admin em `http://<IP deste PC>:8000` (usuário qualquer, senha `ADMIN_SENHA`) e vá em **Catálogo**. Todo produto novo entra inativo. Ative um por um ou use os filtros e **Ativar todos deste filtro**.

Cada produto ativo é uma visita a mais por dia na LigaMagic (cerca de 17 segundos cada): 50 produtos somam uns 15 minutos; 250, pouco mais de uma hora. Comece com poucos.

A partir da próxima coleta, os produtos ativos ganham histórico de venda e número de lojas. Para não esperar o dia seguinte, clique em **Rodar agora** em Serviços: como as listagens do dia já foram feitas, só os produtos rodam.

### 8. Ligue a Amazon

1. Crie no WhatsApp o grupo de oportunidades (com o número secundário dentro), descubra o ID dele como no passo 5 e cole em **Configurações** → Geral, no campo **Grupo de WhatsApp de oportunidades**.

2. Suba o coletor da Amazon junto com todo o resto:

   ```bash
   docker compose up -d --build
   ```

   Suba tudo de uma vez, não só o `coletor-amazon`: a nova versão muda o banco (o `migrate` roda antes) e o `coletor-liga` e o `admin` precisam ser recriados com o código novo junto. Ver [Atualizar uma instalação existente](#atualizar-uma-instalação-existente).

3. Abra `http://<IP deste PC>:6081/vnc.html` (senha `VNC_SENHA`), clique no endereço de entrega da Amazon e informe o CEP de onde as compras serão entregues. O preço e o "Enviado por" dependem dele; o CEP fica salvo no perfil do Chromium.

**Deu certo se** `docker compose logs coletor-amazon --tail 20` mostrar `varredura da Amazon iniciada` e, na janela do noVNC, aparecerem buscas a cada 8 a 20 segundos (dentro do horário de 08:00 às 22:00).

Os anúncios achados só viram oportunidade depois de confirmados em **Casamentos** no admin. Uma mesma página da Amazon pode ter várias opções (envelope, caixa, deck...), cada uma com o seu ASIN; o título muitas vezes não diz qual é. Ao ler a página de um anúncio casado, o coletor guarda a opção selecionada, que aparece ao lado do título no admin (ex.: "Final Fantasy, multicolorido — Collector Booster Box") e na mensagem de oportunidade. Anúncios ainda pendentes só mostram o título da busca.

### 9. Casamento com IA (opcional)

O `casador` avalia com a IA (OpenAI) os anúncios da Amazon que ainda estão pendentes em **Casamentos**, olhando o texto e as imagens do anúncio e do produto da LigaMagic. Cada anúncio avaliado ganha um selo com a confiança, o motivo da IA e o idioma do anúncio; você continua decidindo, a menos que ligue o modo automático.

Regra de idioma: a edição em português é a preferida para o produto da LigaMagic; um anúncio em inglês também é o mesmo produto quando o produto não tem anúncio em português confirmado (coleções antigas juntam os dois num produto só da Liga). Japonês e qualquer outro idioma são sempre outro produto. O automático nunca confirma anúncio japonês ou de outro idioma, e só confirma o inglês em produto sem anúncio em português confirmado (nem confirmado de idioma não registrado); nos outros casos o par fica pendente para você. Um inglês já confirmado continua confirmado se o português aparecer depois: quem desfaz é você.

A IA avalia cada par (anúncio × produto) pendente. **Desfazer** devolve o par para a IA, que o reavalia mesmo sem mudança no anúncio (com o automático ligado, ela pode decidir de novo; para tirar de vez, use **Ignorar**). O automático nunca muda uma decisão sua (manual ou tomada com o selo da IA). Na tela de um produto em **Casamentos** ficam três botões: **Rebuscar agora** (põe o produto na frente da fila da Amazon), **Reavaliar com a IA** (volta para a IA os pares pendentes e os ignorados pelo automático; suas decisões e os confirmados não mudam) e **Gerar termos de busca** (pede os termos alternativos agora; o casador gera em instantes, dentro do teto, se a IA estiver ligada e o casador ativo). Um anúncio confirmado em outro produto aparece como "casado com <produto>".

1. Ponha a chave no `.env` (`OPENAI_API_KEY=...`) e recrie o serviço: `docker compose up -d casador`. Sempre que mudar a chave, recrie o `casador` de novo.
2. Em **Configurações** → **IA**, ligue a IA e ajuste o modelo, os preços, os tetos por dia e por mês (em dólar), o máximo de chamadas por dia, o modo automático e as confianças mínimas.
3. Antes de ligar o automático, meça a IA contra o que você já decidiu em **Casamentos**. O comando não muda nada nos casamentos, só consulta a IA e gera um relatório:

   ```bash
   docker compose exec casador tcg-sniper ia avaliar --modelo gpt-5 --modelo gpt-5-mini
   ```

   Repita `--modelo` para comparar modelos e use `--limite N` para testar com poucos anúncios. O custo usa os preços de Configurações → IA; para medir um modelo com outro preço, informe `--preco-entrada` e `--preco-saida` (US$ por milhão de tokens). O relatório sai em `dados/avaliacao-ia-<data>.md`, com acertos, falsos "sim" (o erro que mais importa), custo e os casos errados. Estas chamadas contam nos tetos.

Se a OpenAI recusar a chave, o `casador` pausa e avisa no WhatsApp. Ao atingir o teto do dia (ou do mês), a IA para até o próximo dia (ou mês) e os anúncios seguem pendentes para você decidir.

### 10. Monitor de preço e conferência de checkout

O `coletor-amazon` tem três trabalhos num navegador só, nesta ordem de prioridade:

1. **Conferência de checkout** das candidatas (melhor oferta com desconto anunciado a até 5 pontos do mínimo): põe a oferta no carrinho, vai até o resumo do pedido, lê itens, frete, impostos de importação e total, e tira o item do carrinho. **Nunca confirma pedido** e nunca usa "Comprar agora". Só roda com o carrinho ativo **vazio**: com qualquer item seu no carrinho, não clica em nada e espera 1 hora para tentar de novo (itens em "Salvo para depois" não contam e nunca são tocados).
2. **Monitor de preço**: lê a lista de ofertas de cada anúncio confirmado a cada 15 min, só dentro da janela do monitor (08:00–22:00), e usa a melhor oferta elegível.
3. **Descoberta**: a busca de anúncios novos, só para produtos sem anúncio confirmado (e uma vez por semana para os casados), dentro da janela da busca.

A conferência e o monitor dividem um teto de páginas por hora (padrão 150; a retirada de item do carrinho também conta). Ao chegar no teto, o monitor espera e a descoberta segue no próprio teto de buscas por hora; se o monitor não cabe no intervalo, o Dashboard avisa (aumente o intervalo ou o teto).

**Preço conferido = itens + impostos, sem o frete.** O alerta e o admin mostram esse valor, com os impostos inclusos e o frete à parte ("frete R$ X à parte"). Com a conferência ligada, o aviso de uma oferta que vai ao checkout espera a conferência e sai com o preço conferido; uma conferência vencida também não fecha nem realerta a oportunidade aberta antes da nova conferência. Só quando não há conferência possível (desligada, conta sem login, seu carrinho com itens ou a conferência dessa oferta falhou) o alerta sai com "preço anunciado, não conferido" e o motivo. O resumo do checkout precisa fechar no centavo (itens + frete + impostos = total); se não fechar, a conferência falha. Cupons e descontos de cartão aparecem só como informação.

O item adicionado sai do carrinho na própria conferência, também depois de um erro no meio. Antes de adicionar, o coletor grava a conferência como "em andamento"; se ele cair no meio (ou a exclusão falhar), tenta tirar o item nas voltas seguintes, mesmo fora da janela, com 15 min entre tentativas. Essa retirada automática **só clica em Excluir com o carrinho exatamente como a conferência o deixou**: só aquele item no carrinho ativo, quantidade 1, subtotal igual ao preço anunciado e conferência de até 30 min. Em qualquer outro caso (por exemplo, você pôs o mesmo produto no carrinho) ou depois de 3 tentativas que falharam, o coletor não clica: o grupo admin recebe "🔴 Amazon · conferir o carrinho · <ASIN>" (com lembrete a cada 2 h até resolver), e o Dashboard e Serviços mostram o alerta até você conferir o carrinho pelo noVNC (porta 6081), tirar o item se não for seu e clicar em **Já conferi**. Com a Amazon pausada (CAPTCHA, erros seguidos ou desligada em Serviços), a retirada automática também para; ela volta quando você retomar. Em Logs → Checkout, "item no carrinho" mostra esses casos.

Tudo em Configurações → Amazon → Monitor de preço; liga e desliga em Serviços.

**Login da conta Amazon.** A conferência precisa da conta Amazon logada no Chromium do coletor: entre no noVNC em `http://<IP deste PC>:6081/vnc.html` e faça login. Se a Amazon pedir login (situação `sem_login`), a conferência para (o monitor continua), o item é retirado, o grupo admin recebe um aviso uma vez e, depois de logar de novo pelo noVNC na porta 6081, clique em **Retomar conferência** em Serviços (o botão aparece também com a Amazon pausada por CAPTCHA).

Para capturar páginas reais para os testes (só quando o layout da Amazon mudar):

```
docker compose stop coletor-amazon
docker compose run --rm --service-ports coletor-amazon tcg-sniper amazon capturar --asin <ASIN> --checkout --login
docker compose start coletor-amazon
```

As páginas ficam em `dados/capturas/` (fora do git) e só entram em `tests/fixtures/amazon` depois de `scripts/anonimizar_fixture.py`.

### 11. Site novo (front) e login pelo WhatsApp

O site novo roda em dois containers: `api` (JSON, em `127.0.0.1:8100`) e `web` (o site, em `http://localhost:8090`). O admin antigo continua em `:8000` até as telas mudarem para cá.

Para implantar (numa instalação que já roda), nesta ordem:

1. Backup do banco antes de tudo:

   ```bash
   mkdir -p dados/backups
   docker compose exec -T postgres pg_dump -U tcg -Fc tcg > dados/backups/tcg-antes-front-<data>.dump
   ```

2. Atualize o código: `git pull`.
3. Ponha uma `SEGREDO_API` de 32 caracteres ou mais no `.env` (gere com o comando abaixo e cole o resultado em `SEGREDO_API=`). Sem ela (ou com o valor de exemplo `trocar-este-segredo`) a `api` não sobe e diz o que fazer. Trocar essa chave depois derruba todas as sessões: todos entram de novo pelo código.

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

4. Recrie **todos** os serviços de uma vez (o `migrate` atualiza o banco antes), como na regra de [Atualizar uma instalação existente](#atualizar-uma-instalação-existente). Nunca só `api` e `web`: o `notificador` antigo não conhece o destino novo das mensagens individuais e mandaria o código de acesso para o grupo de oportunidades.

   ```bash
   docker compose up -d --build
   ```

5. Crie o superadmin (você):

   ```bash
   docker compose exec api tcg-sniper criar-superadmin "<Nome>" "<número>"
   ```

6. Confira no admin antigo (`:8000`): em Configurações → Avisos, o aviso "Código de acesso" ligado (desligado, ninguém recebe código); em Serviços, o `notificador` rodando (ou `docker compose ps notificador`).
7. Abra `http://localhost:8090` neste PC.

Para entrar, digite o seu número e o código que chega no WhatsApp (vale 5 minutos). Você é o superadmin: o único que cria, edita, rebaixa ou desativa admins, e ninguém (nem você) o rebaixa ou desativa pelo site. Em Gestão → Usuários cadastre as outras pessoas com o papel de cada uma (grupo, operador ou admin); admins comuns gerenciam só operadores e grupo. Em Gestão → Acessos escolha o que cada papel pode fazer (o admin pode tudo, sempre). Toda mudança de usuário ou de acesso avisa o grupo admin. Para passar o superadmin a outra pessoa já cadastrada (ex.: número novo): `docker compose exec api tcg-sniper trocar-superadmin "(DDD) número"` (o antigo continua admin).

Permissões de cada papel (padrão; Gestão → Acessos muda as de grupo e operador, e vale na próxima ação de quem já está logado):

| Permissão | Grupo | Operador | Admin |
| --- | --- | --- | --- |
| Entrar na área de negócio (`ver_area_negocio`) | sim | sim | sempre |
| Entrar na área de gestão (`ver_area_gestao`) | não | sim | sempre |
| Gerir usuários (`gerir_usuarios`) | não | não | sempre |
| Gerir acessos (`gerir_acessos`) | não | não | sempre |
| Ver a documentação da API (`ver_documentacao_api`, `/api/docs`) | não | não | sempre |

Quem ganhar `gerir_usuarios` sem ser o superadmin não cria nem mexe em admins, nem muda o próprio papel ou a própria situação (ativo/inativo).

Sem WhatsApp (notificador pausado, Evolution fora), gere um código no terminal: `docker compose exec api tcg-sniper codigo-acesso "(DDD) número"` (acesso de emergência: vale 5 minutos e uma vez, como o do WhatsApp).

## Atualizar uma instalação existente

```bash
git pull
docker compose up -d --build
```

- Atualize fora do horário da coleta da LigaMagic (por volta das 10:00), para não interromper uma coleta no meio.
- Recrie todos os serviços de uma vez, como acima. O `migrate` atualiza o banco antes e todos os containers sobem com o código novo.
- Voltar a migração (downgrade) apaga a tabela `mensagem_saida`, com as mensagens pendentes e o histórico. Faça backup do banco antes de qualquer rollback.
- Nunca reconstrua um serviço só (`docker compose up -d --build coletor-amazon`, por exemplo) depois de uma atualização que muda o banco: os outros continuam com o código antigo contra o banco novo e podem parar de funcionar.

### Implantar o monitor de preço e a conferência de checkout

1. Backup do banco antes de tudo:

   ```bash
   mkdir -p dados/backups
   docker compose exec -T postgres pg_dump -U tcg -Fc tcg > dados/backups/tcg-antes-monitor-<data>.dump
   ```

2. Atualize e recrie todos os serviços de uma vez (o `migrate` atualiza o banco antes), como na regra acima:

   ```bash
   git pull
   docker compose up -d --build
   ```

3. Confira: em Configurações → Amazon, a seção "Monitor de preço" com os padrões (15 min, 08:00–22:00, 150 páginas por hora, margem 5, validade 6 h, descoberta dos casados a cada 7 dias); em Serviços, os interruptores do monitor e da conferência ligados.
4. Faça login na conta Amazon pelo noVNC (`http://<IP deste PC>:6081/vnc.html`). Sem login, a primeira conferência fica `sem_login`, o grupo admin é avisado e o monitor segue.
5. Na primeira hora: Logs → Monitor com leituras chegando; Dashboard sem o aviso de "monitor não cabe no intervalo"; Logs → Checkout com as primeiras conferências e nenhuma marcada "item no carrinho".

### Implantar o casamento por par

A migração `a9d4f2c6e8b1` cria a tabela `casamento` (um par por anúncio, com o mesmo status, origem e datas de antes) e a `termo_busca`, confere que nenhum anúncio ficou com dois confirmados (se ficar, aborta sem mudar nada) e remove as colunas antigas do casamento em `anuncio_amazon` (e `fila_amazon.ultimo_termo_en`). Tudo numa transação: um erro desfaz tudo. Voltar esta migração (downgrade) refaz as colunas antigas com um produto por anúncio (o confirmado ou, sem confirmado, o par mais antigo) e apaga `casamento`, `termo_busca` e os termos gerados; para voltar ao estado exato de antes, restaure o backup do passo 2.

1. Pare os serviços do app (o banco e o WhatsApp continuam no ar), para nenhum container antigo gravar nas tabelas enquanto você faz o backup e a migração as muda:

   ```bash
   docker compose stop coletor-liga coletor-amazon casador notificador manutencao admin api web
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

4. Atualize e recrie todos os serviços de uma vez (o `migrate` atualiza o banco antes; os serviços parados no passo 1 voltam já com o código novo), como na regra acima:

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

## Uso no dia a dia

### Página de admin

O menu fica na lateral (recolhe para ícones no computador; botão de menu no celular).

| Tela | Para que serve |
| --- | --- |
| **Dashboard** (`/`) | Estado e histórico dos serviços (só leitura), incluindo o último backup; avisa quando algum está pausado ou o backup está atrasado. |
| **Serviços** (`/servicos`) | Rodar agora e Retomar (LigaMagic), Pausar e Retomar (Amazon), ligar e desligar o monitor de preço e a conferência de checkout, Retomar conferência, ligar e desligar o backup e a limpeza. |
| **Catálogo** (`/catalogo`) | Todos os produtos, 100 por página. Busca por nome; filtros por situação (todos, ativos, inativos, novos nos últimos 7 dias), por categoria e "só com preço". Ativa ou desativa um produto ou todos os do filtro. |
| **Produto** (`/produto/<id>`) | Preço "À partir de" atual, resumo de venda (mínimo, médio, máximo), número de lojas e o histórico de cada coleta. |
| **Casamentos** | Produtos ativos da Liga com os pares (anúncio × produto) da Amazon; confirmar, ignorar, desfazer, trocar ou colar o link à mão; rebuscar, reavaliar com a IA e gerar termos de busca; filtros por situação, categoria e nome. |
| **Ofertas** | Melhor oferta da Amazon por produto contra a Liga; filtros por nome, categoria, desconto mínimo, vendedor e situação; ordenação por desconto, diferença em R$, leitura ou nome. |
| **Mensagens** (`/mensagens`) | Mensagens do WhatsApp gravadas pelos serviços: pendentes, enviadas, com falha, expiradas e descartadas, com filtros. Reenviar (falha ou expirada) e Descartar. |
| **Configurações** | Três seções (Geral, LigaMagic, Amazon); cada uma salva sozinha e vale a partir da próxima coleta ou ciclo. Senhas, banco e chave da Evolution continuam no `.env`. |

Preço que a página não mostra aparece como "—", nunca como zero.

### Mensagens no WhatsApp

Todas as mensagens seguem o mesmo formato: emoji de severidade (🔴 falha, 🟡 atenção, ✅ concluído, 💰 oportunidade), título em negrito, linhas com "•", "*O que fazer:*" e, em itálico, a hora e quem mandou. Nenhuma leva endereço do admin ou do noVNC (só abrem na rede de casa); a ação diz onde fazer, por exemplo "noVNC da Amazon (porta 6081)" ou "Admin → Serviços → Amazon → Retomar". Links de produto (Amazon, LigaMagic) continuam.

Um problema que se repete sai uma vez, volta como lembrete a cada 2 h enquanto continuar ("continua · N vezes desde HH:MM") e fecha com "✅ … resolvido". Cada tipo pode ser desligado em **Configurações → Avisos**, que mostra um exemplo de cada um.

| Grupo | Avisos |
| --- | --- |
| LigaMagic | ✅ coleta concluída · 🟡 coleta parcial · 🔴 coleta falhou · 🔴 desafio do Cloudflare · 🟡 produtos novos no catálogo · 🟡 coleta interrompida · 🔴 erro inesperado |
| Amazon | ✅ busca concluída · ✅ rodada do monitor · 🟡 busca parcial · 🔴 busca falhou · 🔴 CAPTCHA · 🔴 conta sem login · 🔴 conferir o carrinho (um por ASIN) · 🔴 pausada · 🟡 erro inesperado · 🟡 ciclo interrompido |
| IA | ✅ rodada concluída · 🔴 casador pausado · 🟡 sem orçamento · 🟡 falhas seguidas |
| Backup | ✅ concluído · 🔴 erro · 🟡 interrompido |
| Serviços | 🔴 serviço sem sinal (ativo e mudo há mais de 10 min) · 🟡 serviço mudou no admin (pausar/retomar) · 🔴 mensagem não enviada (no máximo uma por hora) |
| Oportunidades | 💰 oportunidade, no grupo de oportunidades: preço da Amazon (conferido com impostos, frete à parte; ou anunciado, sem impostos), quem vende, referência da Liga e o link do anúncio |

### Quando chegar um aviso de desafio

1. Abra o noVNC: `http://<IP deste PC>:6080/vnc.html` (senha `VNC_SENHA`). Funciona pelo celular, na mesma rede.
2. O Chromium está aberto com a verificação na tela. Resolva-a nessa janela.
3. Clique em **Retomar** em Serviços. Em até 1 minuto a coleta volta, no mesmo navegador.

O coletor nunca tenta de novo sozinho. Se a janela do Chromium for fechada, a próxima coleta abre outra.

### Segurança

O admin e o noVNC usam HTTP sem TLS e são para a rede local. Não exponha as portas 8000, 6080 e 6081 para a internet. A Evolution API (8080) e o Postgres (5432) só escutam em `127.0.0.1`.

No site novo cada pessoa entra com o próprio número: o código de acesso vai só para o WhatsApp dela, vale 5 minutos e uma vez; 5 tentativas erradas o invalidam; no máximo 3 códigos por número a cada 15 minutos e 20 pedidos por hora no total (acima disso a tela pede para esperar e o grupo admin é avisado). O banco guarda só o HMAC (com a chave `SEGREDO_API` do `.env`) do código, do token da sessão e do número dos pedidos; o número nunca vai para log nem para o grupo (aparece mascarado, `+55 11 9****-**34`). A sessão dura 30 dias, renovada a cada uso; desativar um usuário encerra as sessões dele na hora. A `api` (8100) e o `web` (8090) só escutam em `127.0.0.1`.

### Backup do banco

O serviço `manutencao` faz, todo dia às 04:00 (fuso de Configurações → Geral), um `pg_dump` do banco e depois apaga o histórico antigo. Se o PC estava desligado às 04:00, ao subir ele roda na hora quando o último backup ok tem mais de 24 h. Reiniciar não repete o backup do dia.

- **Onde ficam:** em `dados/backups/` neste PC. Diários `tcg-diario-AAAA-MM-DD.dump` (os 7 mais novos) e, aos domingos, semanais `tcg-semanal-AAAA-Wss.dump` (os 4 mais novos). Cada arquivo é conferido com `pg_restore --list` antes de entrar no lugar. Os backups manuais (`tcg-antes-*.dump`) e qualquer outro arquivo da pasta nunca são apagados.
- **Cópia fora do PC:** com as variáveis `R2_*` preenchidas no `.env` (passo a passo no [`.env.example`](.env.example)), cada backup vai também para o bucket do Cloudflare R2: `diario/tcg-AAAA-MM-DD.dump` e `semanal/tcg-AAAA-Wss.dump`. O serviço nunca apaga nada no bucket; as regras de ciclo de vida do bucket apagam `diario/` depois de 7 dias e `semanal/` depois de 35. Sem as variáveis, o backup fica só no PC ("só local") e não há alerta.
- **Acompanhar:** card **Backup** no Dashboard (último ok, tamanho, cópia no R2), **Serviços** para ligar e desligar e **Logs → Manutenção** com cada execução. Falha avisa o grupo admin uma vez e tenta de novo no dia seguinte.
- **Limpeza do histórico** (só depois de um backup local ok): chamadas da IA com mais de 90 dias (a avaliação da IA fica, sem o vínculo com a chamada), conferências de checkout com mais de 180 dias (menos as que podem ter deixado item no carrinho) e coletas com mais de 180 dias que nenhum preço usa. Preços, avaliações da IA e oportunidades nunca são apagados.

Para restaurar um backup (apaga e recria o conteúdo do banco `tcg`): primeiro pare os serviços do app, que escrevem no banco; depois restaure; por fim suba tudo de novo:

```bash
docker compose stop coletor-liga coletor-amazon casador notificador manutencao admin
docker compose exec -T postgres pg_restore -U tcg -d tcg --clean --if-exists < dados/backups/tcg-diario-AAAA-MM-DD.dump
docker compose up -d
```

## Configuração

Os ajustes de operação ficam na página **Configurações** do admin, em quatro seções que salvam separadamente e valem a partir da próxima coleta ou ciclo, sem reiniciar:

- **Geral**: IP ou nome deste PC na rede, fuso horário, instância da Evolution e os grupos de WhatsApp (admin e oportunidades).
- **LigaMagic**: horário da coleta diária e variação, pausas entre páginas, limite de falhas, categorias, URL da listagem e máximo de cliques. Tire de **Categorias** uma que falhe todo dia; pausas menores aumentam a chance de desafio do Cloudflare.
- **Amazon**: desconto mínimo, teto de buscas por hora, horário e demais ajustes do motor de oportunidades.
- **IA**: liga a IA do casamento, modelo, preços, tetos de gasto e de chamadas e o modo automático (ver [passo 9](#9-casamento-com-ia-opcional)).

No `.env` ficam só as senhas e a infraestrutura: `ADMIN_SENHA`, `VNC_SENHA`, `EVOLUTION_API_KEY`, `OPENAI_API_KEY`, as `R2_*` do backup, `DATABASE_URL`, `DIR_DADOS` e `EVOLUTION_URL`, explicadas no [`.env.example`](.env.example). Depois de mudar o `.env`, recrie os containers: `docker compose up -d`.

Quem já tinha os antigos `HOST_PUBLICO`, `FUSO`, `COLETA_*`, `PAUSA_*`, `LIGA_*` etc. no `.env`: na primeira subida o sistema copia esses valores para a tela; depois disso eles são ignorados e podem ser apagados.

## Solução de problemas

**O coletor não sobe e o log diz "defina VNC_SENHA".** A `VNC_SENHA` está vazia ou com o valor padrão. Troque no `.env` e rode `docker compose up -d coletor-liga`.

**O admin não sobe e o log fala de "ADMIN_SENHA".** Mesmo caso: defina uma senha própria.

**A Evolution não sobe e o log reclama do banco `evolution`.** O script que cria o banco `evolution` só roda num volume novo do Postgres. Crie à mão:
`docker compose exec postgres psql -U tcg -c "CREATE DATABASE evolution;"`

**Nenhuma mensagem chega no WhatsApp.** Confira se a instância está conectada no painel da Evolution e se `EVOLUTION_API_KEY` (no `.env`) e a instância e o grupo admin (em **Configurações** → Geral) estão preenchidos. Sem algum deles, as mensagens ficam pendentes em **Mensagens**, com o motivo em "Último erro" (as oportunidades expiram depois da validade). Quem envia é o `notificador`: veja `docker compose logs notificador` (com a chave padrão ele avisa isso ao subir) e o cartão do Notificador em **Serviços**. Os avisos de oportunidade vão para outro grupo: confira também o grupo de oportunidades em **Configurações** → Geral.

**Aviso 'Mensagens do WhatsApp paradas' no Dashboard:** abra Mensagens e leia o último erro. 'sem instância' ou 'sem grupo': preencha em Configurações → Geral. 'HTTP 4xx': confira se a instância está conectada na Evolution e se o ID do grupo está certo, depois clique em Reenviar. 'HTTP 5xx' ou erro de conexão: a Evolution está fora; as mensagens saem sozinhas quando ela voltar. Pendentes sem "Último erro": confira o Notificador em **Serviços** e `docker compose logs notificador`.

**Por que não chega alerta de um produto que está barato na Amazon?** As causas mais comuns: é de um lojista com envio próprio; é de um lojista FBA com poucas avaliações; o casamento do anúncio com o produto da Liga ainda está pendente em **Casamentos**; ou o preço da Liga tem mais de 48 h.

**Uma categoria falha todo dia.** Ela pode ter ficado vazia, ou ter um produto só (a LigaMagic então abre direto a página do produto). Tire o ID de **Categorias** em **Configurações** → LigaMagic.

**Um produto aparece sem preço e com 0 lojas.** É normal: a LigaMagic não mostra o quadro de preços de produtos sem nenhuma loja e sem venda registrada.

**O painel da Evolution diz "Missing base64 data and mediaUrl" ao abrir uma foto ou áudio.** É esperado e não afeta o projeto. A Evolution não guarda o conteúdo das mídias por padrão, e o tcg-sniper só envia texto, sem ler mensagens. Configurar armazenamento de mídia (S3, Cloudflare R2, MinIO) não é necessário e não está no escopo.

**O logo do painel da Evolution aparece quebrado.** É só visual e não afeta nada.

## Desenvolvimento

```bash
cp .env.example .env
docker compose up -d postgres postgres-teste   # postgres-teste: banco só de testes (porta 5433, em memória)
uv sync
uv run playwright install chromium
uv run pytest -q
uv run ruff check
```

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

Os testes usam `tcg_test` no `postgres-teste` (`127.0.0.1:5433`), nunca o Postgres de produção: a suíte recusa rodar em banco que não comece com `tcg_test` ou na porta 5432. Para outro banco (por exemplo um por trabalho paralelo), crie-o com `docker compose exec -T postgres-teste createdb -U tcg tcg_test_<nome>` e aponte `DATABASE_URL_TESTE` para ele. O `postgres-teste` guarda os dados em memória (tmpfs): ao reiniciar o container ou o Docker, tudo some. O `tcg_test` padrão volta sozinho (o container o cria e as migrações recriam as tabelas no próximo `pytest`), mas os bancos extras (`tcg_test_<nome>`) precisam ser criados de novo com o `createdb` acima.

Nenhum teste acessa a LigaMagic ou o WhatsApp reais: os parsers são testados com páginas salvas em `tests/fixtures/liga`, e o navegador e o WhatsApp têm versões falsas nos testes. Os 3 testes de `tests/coletor_liga/test_navegador.py` abrem um Chromium com uma página local e só rodam com `TESTAR_NAVEGADOR=1`.

Para rodar um serviço fora do Docker: `uv run tcg-sniper migrate`, `uv run tcg-sniper admin`, `uv run tcg-sniper coletor-liga`, `uv run tcg-sniper coletor-amazon` ou `uv run tcg-sniper notificador`.

### Visual do admin (DaisyUI)

O admin usa DaisyUI 5 sobre Tailwind CSS 4, com os temas winter (claro) e night (escuro). O CSS é gerado e fica versionado em `src/tcg_sniper/admin/static/admin.css`:

- Depois de mudar qualquer template do admin, rode `uv run python scripts/gerar_css.py` (baixa o Tailwind standalone e o DaisyUI em `.ferramentas/` na primeira vez). O teste `test_css_em_dia_com_os_templates` falha se você esquecer.
- Antes de um deploy que mexe no visual, rode `docker compose exec -T admin python - < scripts/verificar_layout.py`: abre as telas em 390 e 1440 px nos dois temas e falha se algo estourar a largura.
- Só use componentes e classes do DaisyUI/Tailwind; não escreva CSS próprio.

### Estrutura

```
src/tcg_sniper/
  cli.py              comandos migrate, admin, api, codigo-acesso, criar-superadmin, trocar-superadmin, coletor-liga,
                      coletor-amazon, notificador, casador, manutencao e ia
  config.py           leitura do .env
  coletor_liga/       agendador, navegador (Playwright), parsers e as duas etapas da coleta
  coletor_amazon/     monitor de preço, conferência de checkout, fila de buscas, parsers da Amazon e cliques permitidos
  casador/            casamento com IA: pergunta, serviço e avaliação
  ia/                 transporte OpenAI, modelos e custos
  admin/              página de admin (FastAPI + Jinja2 + HTMX)
  api/                API do site novo (FastAPI, JSON): login pelo WhatsApp, sessões, permissões por papel
  db/                 modelos, repositório e migrações (SQLAlchemy + Alembic)
  notificador/        tabela de saída do WhatsApp e o serviço que envia pela Evolution API
  manutencao/         backup diário do banco (pg_dump, rodízio, cópia no R2) e o serviço que também limpa o histórico
web/                  site novo (React + Vite + DaisyUI), servido pelo Caddy no container web
docker/               entrypoint do coletor (Xvfb, VNC, noVNC) e script inicial do Postgres
scripts/              captura de páginas reais para as fixtures
tests/                testes (pytest)
docs/superpowers/     especificação e plano de implementação
```

### Quando a LigaMagic muda o layout

1. Pegue o HTML que falhou em `/data/falhas` (`docker compose cp coletor-liga:/data/falhas/<arquivo> .`).
2. Ou capture uma página nova: `uv run python scripts/capturar_fixture.py <url> <nome>` (com `--expandir` para uma listagem).
3. Adicione a página em `tests/fixtures/liga`, escreva o teste que falha e ajuste `src/tcg_sniper/coletor_liga/parsers.py`. O docstring do arquivo descreve a estrutura esperada de cada página.
4. Antes de commitar, recorte a página: `uv run python scripts/recortar_fixture.py tests/fixtures/liga/<nome>.html`. O repositório guarda só os trechos que os parsers leem, nunca a página inteira. O script confere que os parsers dão o mesmo resultado no original e no recorte; se ele recusar, inclua os blocos novos que o parser passou a ler na lista do script.

O desenho completo está em [`docs/superpowers/specs/2026-10-13-coletor-liga-design.md`](docs/superpowers/specs/2026-10-13-coletor-liga-design.md).

## Roadmap

1. **Coleta da LigaMagic, admin e avisos no WhatsApp.** Pronto.
2. **Mais marketplaces.** Em andamento: a Amazon, o casamento de produtos e as oportunidades estão prontos; Mercado Livre e outros são os próximos.
3. **Cupons, cashback, frete e comissão no cálculo.**
4. **Migração para servidor.**

## Licença

[MIT](LICENSE).
