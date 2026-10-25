# tcg-sniper

[![Licença MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-blue.svg)](LICENSE)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)
![Docker Compose](https://img.shields.io/badge/roda%20com-Docker%20Compose-2496ED.svg)

**Monitor de arbitragem de produtos selados de Magic: The Gathering no Brasil.** O tcg-sniper compara o preço da Amazon com o da [LigaMagic](https://www.ligamagic.com.br) e avisa no WhatsApp quando um booster, uma caixa ou um kit aparece bem abaixo do preço de mercado, já com o preço conferido no checkout.

Feito para quem compra e revende selados: lojistas da LigaMagic, revendedores e grupos de compra. Roda num PC seu, com Docker, e é administrado por uma página web.

## O que ele faz

- **Preço de referência da LigaMagic, todo dia.** Lê o catálogo de selados com o menor preço anunciado ("À partir de") de cada produto e, para os produtos acompanhados, o número de lojas e o resumo do histórico de venda (mínimo, médio e máximo).
- **Busca e monitor na Amazon.** Procura cada produto na amazon.com.br e lê o preço dos anúncios casados a cada 15 minutos, com o vendedor e a opção (envelope, caixa, deck…) de cada anúncio.
- **Casamento de produtos com IA (opcional).** A IA compara texto e imagens do anúncio da Amazon com o produto da LigaMagic, inclusive o idioma da edição; você confirma, ou liga o modo automático com confiança mínima e teto de gasto.
- **Preço conferido no checkout.** Antes do alerta, a oferta vai ao resumo do pedido para ler itens e impostos (o frete aparece à parte). O coletor nunca confirma pedido.
- **Alertas no WhatsApp.** Oportunidades num grupo, avisos de operação em outro, com lembrete enquanto um problema continua e aviso de resolvido.
- **Site com login pelo WhatsApp.** Cada pessoa entra com o próprio número e um código; papéis (grupo, operador, admin) com permissões configuráveis.
- **Operação de casa.** Backup diário do banco (com cópia opcional no Cloudflare R2), vigia dos serviços e tela remota (noVNC) para resolver verificações à mão.

## Estado do projeto

Versão 0.1, em uso diário por um grupo de compra desde outubro de 2026. Coleta da LigaMagic, Amazon (busca, monitor e conferência de checkout), casamento com IA, avisos no WhatsApp e backup estão prontos. O site novo (React) tem login, usuários e acessos, a área de oportunidades e, da administração, Casamentos e Catálogo (fase 3A); o restante da administração ainda está no admin antigo e migra nas próximas entregas. Ainda não está pronto para ficar exposto na internet (ver [Segurança](#segurança)). O que falta está no [Roadmap](#roadmap) e em [`docs/PENDENCIAS.md`](docs/PENDENCIAS.md).

## Formas de usar

- **Instalar por conta própria.** O código é aberto sob a [licença MIT](LICENSE): você pode instalar, modificar e usar, inclusive comercialmente, seguindo este README. Não há suporte garantido; dúvidas e problemas vão para as [issues](https://github.com/Kyner/tcg-sniper/issues).
- **Assinar as oportunidades (em preparação).** O plano é vender o acesso aos alertas e à área de negócio para assinantes, no mesmo sistema, sem você precisar instalar nada. Ainda não está aberto.

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
- [Contribuir](#contribuir)
- [Licença e avisos](#licença-e-avisos)

## Uso responsável

O tcg-sniper foi feito para acessar a LigaMagic como uma pessoa acessaria, em volume baixo:

- **Um acesso por vez, com pausa humana.** Entre uma página e outra há uma pausa aleatória de 8 a 20 segundos. A coleta roda uma vez por dia e nunca há duas ao mesmo tempo.
- **Navegador de verdade.** Usa o Chromium com janela (não headless), com perfil persistente, no seu próprio PC e na sua conexão.
- **Sem burlar proteções.** Não há solucionador de CAPTCHA, nem troca de identidade do navegador, nem rodízio de IP. O Chromium sobe sem a marca de "navegador automatizado" (sem ela, a verificação do Cloudflare entra em loop mesmo resolvida à mão), mas com o próprio user agent e o IP da sua casa. Se aparecer uma verificação, a coleta pausa, avisa você e espera que uma pessoa a resolva pela tela remota; depois de um desafio, a coleta fica mais lenta, e um segundo desafio no mesmo dia encerra o dia.
- **Amazon com teto e horário.** Na Amazon, a busca tem teto de 90 buscas por hora e o monitor de 150 páginas por hora (padrões; recomendado no máximo 90 e 180, e a Amazon vê a soma no mesmo endereço), cada um no próprio horário; um CAPTCHA pausa só o serviço que o recebeu até uma pessoa resolver.
- **Só o que a página mostra em texto.** Lê o preço "À partir de" das listagens e o quadro de resumo da página do produto. Os preços de cada loja são desenhados como imagem na página e nunca são decodificados.

Respeite os termos de uso da LigaMagic e da Amazon e não aumente o ritmo da coleta. Quem instala é responsável pelo uso que faz (ver [Licença e avisos](#licença-e-avisos)).

## Como funciona

```mermaid
flowchart LR
    liga[(LigaMagic)]
    amazon[(amazon.com.br)]
    subgraph pc[Seu PC - Docker Compose]
        coletor[coletor-liga<br/>Chromium + agendador]
        coletor_amz[coletor-amazon<br/>Chromium logado: monitor de preço,<br/>conferência de checkout e retirada]
        coletor_busca[coletor-amazon-busca<br/>Chromium sem login: busca de anúncios novos]
        casador[casador<br/>casamento com IA]
        admin[admin<br/>página web :8000]
        web[web + api<br/>site novo :8090]
        db[(Postgres)]
        notif[notificador]
        manut[manutencao<br/>backup e limpeza]
        evo[Evolution API]
        vnc[noVNC :6080]
        vnc_amz[noVNC :6081]
        vnc_busca[noVNC :6082]
    end
    whats[Grupos admin e<br/>oportunidades no WhatsApp]
    openai[(OpenAI)]
    r2[(Cloudflare R2<br/>opcional)]

    coletor -- uma visita por vez --> liga
    coletor_amz -- uma página por vez --> amazon
    coletor_busca -- uma página por vez --> amazon
    coletor --> db
    coletor_amz --> db
    coletor_busca --> db
    casador --> db
    casador --> openai
    admin --> db
    web --> db
    manut --> db
    manut -.-> r2
    db --> notif --> evo --> whats
    vnc -. tela do Chromium .- coletor
    vnc_amz -. tela do Chromium .- coletor_amz
    vnc_busca -. tela do Chromium .- coletor_busca
```

Todo dia, por volta das 10:00:

1. **Listagens.** O coletor abre a listagem de cada categoria de selados (20 por padrão) e clica em "Exibir mais" até mostrar tudo. Daí saem o catálogo e o preço "À partir de" atual de cada produto.
2. **Produtos do dia.** Depois abre a página só dos produtos ativos que interessam hoje: os casados e os com candidato (todo dia), os novos ainda sem resumo (até 100 por dia, os mais antigos primeiro) e o rodízio do dia (cada um dos demais uma vez por semana). Guarda o número de lojas e o resumo do histórico de venda (mínimo, médio e máximo). O que já foi lido hoje não é relido: um Retomar continua de onde parou.
3. **Aviso.** No fim, manda um resumo para o grupo admin do WhatsApp.
4. **Desafio do Cloudflare.** Se aparecer uma verificação no meio do caminho, a coleta pausa e avisa o grupo. Você resolve a verificação pela tela remota (noVNC) e clica em **Retomar** em Serviços. Depois do 1º desafio do dia a coleta espera 30 min (Configurações → LigaMagic → Esfriar após desafio) e segue com pausas em dobro até o fim do dia; um 2º desafio no mesmo dia encerra o dia, e a coleta volta no horário de amanhã.

**Amazon.** De 08:00 às 22:00 o `coletor-amazon-busca` (um navegador próprio, sem login) procura cada produto ativo na amazon.com.br, um por vez, com pausa humana. Quando a LigaMagic mostra o nome do produto em inglês, a busca alterna entre o nome em português e o nome em inglês a cada passada; um produto sem casamento que passa 7 dias sem achar anúncio novo ganha de 2 a 3 termos de busca alternativos sugeridos pela IA (uma vez, dentro do teto de gasto), que entram no rodízio até aparecer anúncio novo. Cada anúncio achado vira um par (anúncio × produto) pendente em **Casamentos**; ignorar vale só para aquele par (o mesmo anúncio achado na busca de outro produto volta a ser pendente para ele), e um anúncio é confirmado para no máximo um produto. Só pares confirmados geram oportunidade. Quando uma oferta vendida pela Amazon (ou por lojista confiável com envio pela Amazon) fica abaixo do "À partir de" da Liga pelo menos o desconto mínimo de Configurações → Amazon (padrão 25%), o grupo de oportunidades recebe um aviso. Quando a oferta deixa de valer (preço subiu, oferta sumiu, Liga baixou ou vendedor mudou) e continua assim pela carência de Configurações → Amazon (padrão 30 min), a oportunidade encerra e o grupo de oportunidades recebe "⏹️ Oferta encerrada" com o motivo e quanto tempo ela durou; oscilação mais curta não gera aviso. Se o casamento for desfeito ou trocado, o grupo recebe "⚠️ Alerta corrigido". Encerramentos técnicos (preço da Liga desatualizado, anúncio sem leitura) vão para o grupo admin. Alerta que nunca saiu (expirado ou ainda na fila) não gera aviso de encerramento. Ofertas vendidas pela "Amazon Global" (importadas pela própria Amazon) contam como vendidas pela Amazon e também geram aviso; o prazo é mais longo e o imposto de importação pode ser cobrado à parte do preço mostrado. Os anúncios confirmados têm o preço lido pelo **monitor de preço** do `coletor-amazon` (o navegador logado) a cada 15 min, e as melhores ofertas passam pela **conferência de checkout** (ver [Monitor de preço e conferência de checkout](#10-monitor-de-preço-e-conferência-de-checkout)). Tudo isso se ajusta em **Configurações** no admin (seções Geral, LigaMagic e Amazon; os valores ficam no banco, não no `.env`).

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
| `SEGREDO_API` | Chave do site novo, com 32 caracteres ou mais (gere com o comando abaixo). Trocá-la depois derruba todas as sessões: todos entram de novo pelo código. |

Para gerar a `SEGREDO_API` (ou qualquer outra chave aleatória), use o `openssl` que vem com o Git Bash ou, sem ele, o Python do próprio container:

```bash
openssl rand -base64 32
# ou
docker compose run --rm --no-deps api python -c "import secrets; print(secrets.token_urlsafe(32))"
```

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

Procure o grupo pelo nome (`subject`) e copie o `id`, que termina em `@g.us`. Abra o admin em `http://localhost:8000/configuracoes` e, em **Configurações** → Geral, cole-o em **Grupo de WhatsApp do admin**. Aproveite para preencher **IP ou nome deste PC na rede** (no Windows: `ipconfig`, "Endereço IPv4") e **Instância da Evolution API**. Salve: não precisa reiniciar nada.

### 6. Suba o coletor

Faça isso quando puder acompanhar a primeira coleta:

```bash
docker compose up -d --build coletor-liga
```

**Deu certo se** `docker compose logs coletor-liga --tail 20` mostrar `agendador iniciado`, sem erro.

Na primeira vez, como ainda não há nenhuma coleta, ela começa sozinha em até 30 minutos (não espera as 10:00). Para começar já, use **Rodar agora** em Serviços (passo 7). As listagens de todas as categorias levam cerca de 20 minutos. Dá para acompanhar o Chromium trabalhando pelo noVNC: `http://localhost:6080/vnc.html`, com a `VNC_SENHA`.

Ao final, o grupo admin recebe "🟡 Liga · produtos novos no catálogo" e "✅ Liga · coleta concluída".

### 7. Escolha os produtos que quer acompanhar

Abra o admin em `http://localhost:8000` (usuário qualquer, senha `ADMIN_SENHA`) e vá em **Catálogo**. Todo produto novo entra inativo. Ative um por um ou use os filtros e **Ativar todos deste filtro**.

Cada página de produto leva cerca de 17 segundos. Os casados e os com candidato são lidos todo dia; os demais ativos, uma vez por semana (rodízio), e os novos até 100 por dia. Com uns 2000 produtos ativos são umas 450 a 500 páginas por dia, de 2 a 3 horas.

A partir da próxima coleta, os produtos ativos ganham histórico de venda e número de lojas. Para não esperar o dia seguinte, clique em **Rodar agora** em Serviços: como as listagens do dia já foram feitas, só os produtos rodam.

### 8. Ligue a Amazon

1. Crie no WhatsApp o grupo de oportunidades (com o número secundário dentro), descubra o ID dele como no passo 5 e cole em **Configurações** → Geral, no campo **Grupo de WhatsApp de oportunidades**.

2. Suba o coletor da Amazon junto com todo o resto:

   ```bash
   docker compose up -d --build
   ```

   Suba tudo de uma vez, não só os coletores da Amazon: a nova versão muda o banco (o `migrate` roda antes) e o `coletor-liga` e o `admin` precisam ser recriados com o código novo junto. Ver [Atualizar uma instalação existente](#atualizar-uma-instalação-existente).

3. Abra `http://localhost:6081/vnc.html` (senha `VNC_SENHA`), clique no endereço de entrega da Amazon e informe o CEP de onde as compras serão entregues. O preço e o "Enviado por" dependem dele; o CEP fica salvo no perfil do Chromium.

   Faça o mesmo no noVNC da busca, `http://localhost:6082/vnc.html` (o CEP muda o preço da busca também). A busca não precisa de login.

**Deu certo se** `docker compose logs coletor-amazon --tail 20` mostrar `varredura da Amazon (monitor) iniciada`, `docker compose logs coletor-amazon-busca --tail 20` mostrar `varredura da Amazon (busca) iniciada` e, no noVNC da porta 6082, aparecerem buscas a cada 8 a 20 segundos (dentro do horário de 08:00 às 22:00).

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

A Amazon roda em dois serviços, cada um com o próprio navegador. O `coletor-amazon` (navegador logado, noVNC 6081) faz, nesta ordem de prioridade:

1. **Conferência de checkout** das candidatas (melhor oferta com desconto anunciado a até 5 pontos do mínimo): põe a oferta no carrinho, vai até o resumo do pedido, lê itens, frete, impostos de importação e total, e tira o item do carrinho. **Nunca confirma pedido** e nunca usa "Comprar agora". Só roda com o carrinho ativo **vazio**: com qualquer item seu no carrinho, não clica em nada e espera 1 hora para tentar de novo (itens em "Salvo para depois" não contam e nunca são tocados).
2. **Monitor de preço**: lê a lista de ofertas de cada anúncio confirmado a cada 15 min, só dentro da janela do monitor (08:00–22:00), e usa a melhor oferta elegível.

O `coletor-amazon-busca` (navegador próprio, sem login, noVNC 6082) faz só a **descoberta**: a busca de anúncios novos, para produtos sem anúncio confirmado (e uma vez por semana para os casados), dentro da janela da busca e com o teto de buscas por hora (padrão 90). Um CAPTCHA, um erro ou uma pausa num serviço não para o outro: cada um tem o próprio card e o próprio Retomar em Serviços, e os avisos dizem a origem ("Amazon (busca) · CAPTCHA" ou "Amazon (monitor) · CAPTCHA").

A conferência e o monitor dividem um teto de páginas por hora (padrão 150; a retirada de item do carrinho também conta). Ao chegar no teto, o monitor espera; a busca segue no próprio teto, no outro navegador. A Amazon vê a soma dos dois tetos no mesmo endereço (até 90 + 180 = 270 por hora com os tetos no máximo recomendado). Se o monitor não cabe no intervalo, o Dashboard avisa (aumente o intervalo ou o teto). A **rodada do monitor** (aviso no grupo admin) sai uma vez por volta: quando ele leu todos os anúncios acompanhados no começo da volta.

**Preço conferido = itens + impostos, sem o frete.** O alerta e o admin mostram esse valor, com os impostos inclusos e o frete à parte ("frete R$ X à parte"). Com a conferência ligada, o aviso de uma oferta que vai ao checkout espera a conferência e sai com o preço conferido; uma conferência vencida também não fecha nem realerta a oportunidade aberta antes da nova conferência. Só quando não há conferência possível (desligada, conta sem login, seu carrinho com itens ou a conferência dessa oferta falhou) o alerta sai com "preço anunciado, não conferido" e o motivo. O resumo do checkout precisa fechar no centavo (itens + frete + impostos = total); se não fechar, a conferência falha. Cupons e descontos de cartão aparecem só como informação.

O item adicionado sai do carrinho na própria conferência, também depois de um erro no meio. Antes de adicionar, o coletor grava a conferência como "em andamento"; se ele cair no meio (ou a exclusão falhar), tenta tirar o item nas voltas seguintes, mesmo fora da janela, com 15 min entre tentativas. Essa retirada automática **só clica em Excluir com o carrinho exatamente como a conferência o deixou**: só aquele item no carrinho ativo, quantidade 1, subtotal igual ao preço anunciado e conferência de até 30 min. Em qualquer outro caso (por exemplo, você pôs o mesmo produto no carrinho) ou depois de 3 tentativas que falharam, o coletor não clica: o grupo admin recebe "🔴 Amazon · conferir o carrinho · <ASIN>" (com lembrete a cada 2 h até resolver), e o Dashboard e Serviços mostram o alerta até você conferir o carrinho pelo noVNC (porta 6081), tirar o item se não for seu e clicar em **Já conferi**. Com o monitor da Amazon pausado (CAPTCHA, erros seguidos ou desligado em Serviços → Amazon (monitor e checkout)), a retirada automática também para; ela volta quando você retomar. Em Logs → Checkout, "item no carrinho" mostra esses casos.

Tudo em Configurações → Amazon → Monitor de preço; liga e desliga em Serviços.

O monitor divide os anúncios confirmados em quatro grupos, nesta ordem de prioridade: (1) **nunca lidos**, lidos primeiro; (2) **fila rápida**, com as oportunidades abertas e os anúncios com desconto a partir do "quase lá", lidos a cada "Fila rápida: ler a cada (min)" (padrão 15; a rodada e o aviso de atraso contam só esta fila); (3) **esgotado na Liga**, produtos sem preço na Liga, lidos uma vez por semana (Configurações → Amazon → "Esgotado na Liga: ler a cada (dias)", padrão 7); (4) **lento**, o resto, lido com a capacidade que sobrar. O card em Serviços mostra as contagens "rápida · lenta · esgotado".

**Login da conta Amazon.** A conferência precisa da conta Amazon logada no Chromium do coletor: entre no noVNC em `http://localhost:6081/vnc.html` e faça login. Se a Amazon pedir login (situação `sem_login`), a conferência para (o monitor continua), o item é retirado, o grupo admin recebe um aviso uma vez e, depois de logar de novo pelo noVNC na porta 6081, clique em **Retomar conferência** em Serviços (o botão aparece também com o monitor pausado por CAPTCHA).

Para capturar páginas reais para os testes (só quando o layout da Amazon mudar):

```
docker compose stop coletor-amazon
docker compose run --rm --service-ports coletor-amazon tcg-sniper amazon capturar --asin <ASIN> --checkout --login
docker compose start coletor-amazon
```

As páginas ficam em `dados/capturas/` (fora do git) e só entram em `tests/fixtures/amazon` depois de `scripts/anonimizar_fixture.py`.

### 11. Site novo e login pelo WhatsApp

O site novo roda em dois containers: `api` (JSON, em `127.0.0.1:8100`) e `web` (o site, em `http://localhost:8090`). Eles já subiram no `docker compose up -d --build` do passo 8; sem uma `SEGREDO_API` válida no `.env` (passo 2), a `api` não sobe e o log diz o que fazer. O admin antigo continua em `:8000` até as telas mudarem para cá. Quem já tinha uma instalação de antes do site novo segue as [notas de implantação](docs/IMPLANTACOES.md#site-novo-front-e-login-pelo-whatsapp).

1. Crie o superadmin (você):

   ```bash
   docker compose exec api tcg-sniper criar-superadmin "<Nome>" "<número>"
   ```

2. Confira no admin antigo (`:8000`): em Configurações → Avisos, o aviso "Código de acesso" ligado (desligado, ninguém recebe código); em Serviços, o `notificador` rodando (ou `docker compose ps notificador`).
3. Abra `http://localhost:8090` neste PC.

Para entrar, digite o seu número e o código que chega no WhatsApp (vale 5 minutos). Você é o superadmin: o único que cria, edita, rebaixa ou desativa admins, e ninguém (nem você) o rebaixa ou desativa pelo site. Em Gestão → Usuários cadastre as outras pessoas com o papel de cada uma (grupo, operador ou admin); admins comuns gerenciam só operadores e grupo. Em Gestão → Acessos escolha o que cada papel pode fazer (o admin pode tudo, sempre). Toda mudança de usuário ou de acesso avisa o grupo admin. Para passar o superadmin a outra pessoa já cadastrada (ex.: número novo): `docker compose exec api tcg-sniper trocar-superadmin "(DDD) número"` (o antigo continua admin).

A área de negócio do site novo tem duas telas, ambas atrás de `ver_oportunidades`:

- **Oportunidades** (`/`): números do período (7, 30 ou 90 dias), as oportunidades ativas agora (com o selo de risco), as quase lá (casados com desconto entre o piso e o mínimo), um gráfico por dia e a lista das encerradas, com duração e motivo.
- **Produto** (`/produtos/<id>`): a curva de preço do produto (menor preço elegível da Amazon, "a partir de" e média da Liga, preço alvo), com as faixas em que houve oportunidade, a recorrência e as oportunidades do produto.

A área de gestão (Gestão no menu, para quem tem `ver_area_gestao`) já tem duas telas do admin antigo:

- **Casamentos** (`/gestao/casamentos`): os produtos da LigaMagic com busca, filtros e ordem; "Revisar em sequência" abre um produto por vez, com os anúncios da Amazon para decidir, confirmados e ignorados (confirmar, ignorar, passar para outro produto, casar por link, rebuscar, reavaliar com a IA e gerar termos de busca), e "Próximo" mantém os filtros da lista. Atalhos no computador: C confirma, I ignora, setas escolhem o anúncio e Enter vai ao próximo produto.
- **Catálogo** (`/gestao/catalogo`): todos os produtos, com a chave para monitorar ou parar de monitorar, ações em lote com confirmação do número exato de produtos, e a página do produto (`/gestao/produtos/<id>`) com preços, casamentos e curva. Desligar um produto nunca apaga o histórico de preços.

As imagens de produto são copiadas para um bucket público do R2 (`R2_BUCKET_IMAGENS`, `URL_PUBLICA_IMAGENS`); sem essas variáveis o site funciona sem fotos.

Permissões de cada papel (padrão; Gestão → Acessos muda as de grupo e operador, e vale na próxima ação de quem já está logado):

| Permissão | Grupo | Operador | Admin |
| --- | --- | --- | --- |
| Entrar na área de negócio (`ver_area_negocio`) | sim | sim | sempre |
| Ver oportunidades (`ver_oportunidades`) | sim | sim | sempre |
| Entrar na área de gestão (`ver_area_gestao`) | não | sim | sempre |
| Gerir usuários (`gerir_usuarios`) | não | não | sempre |
| Gerir acessos (`gerir_acessos`) | não | não | sempre |
| Ver a documentação da API (`ver_documentacao_api`, `/api/docs`) | não | não | sempre |
| Revisar casamentos (`revisar_casamentos`) | não | sim | sempre |
| Ver o catálogo (`ver_catalogo`) | não | sim | sempre |
| Editar o catálogo (`editar_catalogo`) | não | sim | sempre |
| Ver serviços (`ver_servicos`) | não | sim | sempre |
| Pausar serviços (`pausar_servicos`) | não | não | sempre |
| Ver a atividade (`ver_logs`) | não | sim | sempre |
| Ver mensagens (`ver_mensagens`) | não | sim | sempre |
| Reenviar mensagens (`reenviar_mensagens`) | não | não | sempre |
| Ver configurações (`ver_configuracoes`) | não | sim | sempre |
| Editar configurações (`editar_configuracoes`) | não | não | sempre |

Quem ganhar `gerir_usuarios` sem ser o superadmin não cria nem mexe em admins, nem muda o próprio papel ou a própria situação (ativo/inativo).

Sem WhatsApp (notificador pausado, Evolution fora), gere um código no terminal: `docker compose exec api tcg-sniper codigo-acesso "(DDD) número"` (acesso de emergência: vale 5 minutos e uma vez, como o do WhatsApp).

## Atualizar uma instalação existente

```bash
mkdir -p dados/backups
docker compose exec -T postgres pg_dump -U tcg -Fc tcg > dados/backups/tcg-antes-<data>.dump
git pull
docker compose up -d --build
```

- Faça o backup antes de toda atualização que muda o banco (na dúvida, sempre). Os arquivos `tcg-antes-*.dump` nunca são apagados pelo rodízio do backup diário.
- Leia antes as [notas de implantação](docs/IMPLANTACOES.md): algumas versões pedem passos a mais (parar serviços, conferir contagens, rodar um comando depois).
- Atualize fora do horário da coleta da LigaMagic (por volta das 10:00), para não interromper uma coleta no meio.
- Recrie todos os serviços de uma vez, como acima. O `migrate` atualiza o banco antes e todos os containers sobem com o código novo.
- Voltar a migração (downgrade) apaga a tabela `mensagem_saida`, com as mensagens pendentes e o histórico. Faça backup do banco antes de qualquer rollback.
- Nunca reconstrua um serviço só (`docker compose up -d --build coletor-amazon`, por exemplo) depois de uma atualização que muda o banco: os outros continuam com o código antigo contra o banco novo e podem parar de funcionar. Da separação da busca em diante, `coletor-amazon` e `coletor-amazon-busca` sobem juntos.

## Uso no dia a dia

### Página de admin

O menu fica na lateral (recolhe para ícones no computador; botão de menu no celular).

| Tela | Para que serve |
| --- | --- |
| **Dashboard** (`/`) | Estado e histórico dos serviços (só leitura), incluindo o último backup; avisa quando algum está pausado ou o backup está atrasado. |
| **Serviços** (`/servicos`) | Rodar agora e Retomar (LigaMagic), Pausar e Retomar (Amazon (busca) e Amazon (monitor e checkout)), ligar e desligar o monitor de preço e a conferência de checkout, Retomar conferência, ligar e desligar o backup e a limpeza. |
| **Catálogo** (`/catalogo`) | Todos os produtos, 100 por página. Busca por nome; filtros por situação (todos, ativos, inativos, novos nos últimos 7 dias), por categoria e "só com preço". Ativa ou desativa um produto ou todos os do filtro. |
| **Produto** (`/produto/<id>`) | Preço "À partir de" atual, resumo de venda (mínimo, médio, máximo), número de lojas e o histórico de cada coleta. |
| **Casamentos** | Produtos ativos da Liga com os pares (anúncio × produto) da Amazon; confirmar, ignorar, desfazer, trocar ou colar o link à mão; rebuscar, reavaliar com a IA e gerar termos de busca; filtros por situação, categoria e nome. |
| **Ofertas** | Melhor oferta da Amazon por produto contra a Liga; filtros por nome, categoria, desconto mínimo, vendedor e situação; ordenação por desconto, diferença em R$, leitura ou nome. |
| **Mensagens** (`/mensagens`) | Mensagens do WhatsApp gravadas pelos serviços: pendentes, enviadas, com falha, expiradas e descartadas, com filtros. Reenviar (falha ou expirada) e Descartar. |
| **Configurações** | Três seções (Geral, LigaMagic, Amazon); cada uma salva sozinha e vale a partir da próxima coleta ou ciclo. Senhas, banco e chave da Evolution continuam no `.env`. |

Preço que a página não mostra aparece como "—", nunca como zero.

### Mensagens no WhatsApp

Todas as mensagens seguem o mesmo formato: emoji de severidade (🔴 falha, 🟡 atenção, ✅ concluído, 💰 oportunidade, ⏹️ encerrada, ⚠️ correção), título em negrito, linhas com "•", "*O que fazer:*" e, em itálico, a hora e quem mandou. Nenhuma leva endereço do admin ou do noVNC (só abrem na rede de casa); a ação diz onde fazer, por exemplo "noVNC do monitor (porta 6081)" ou "Admin → Serviços → Amazon (busca) → Retomar". Links de produto (Amazon, LigaMagic) continuam.

Um problema que se repete sai uma vez, volta como lembrete a cada 2 h enquanto continuar ("continua · N vezes desde HH:MM") e fecha com "✅ … resolvido". Cada tipo pode ser desligado em **Configurações → Avisos**, que mostra um exemplo de cada um.

| Grupo | Avisos |
| --- | --- |
| LigaMagic | ✅ coleta concluída · 🟡 coleta parcial · 🔴 coleta falhou · 🔴 desafio do Cloudflare · 🟡 produtos novos no catálogo · 🟡 coleta interrompida · 🔴 erro inesperado |
| Amazon | ✅ busca concluída · ✅ rodada do monitor (uma por volta) · 🟡 busca parcial · 🔴 busca falhou · 🔴 CAPTCHA, 🔴 pausada e 🟡 erro inesperado — cada um com a origem no título, (busca) ou (monitor), e resolvido próprio · 🔴 conta sem login · 🔴 conferir o carrinho (um por ASIN) · 🟡 ciclo interrompido (busca) · 🟡 oportunidade encerrada (técnico) |
| IA | ✅ rodada concluída · 🔴 casador pausado · 🟡 sem orçamento · 🟡 falhas seguidas |
| Backup | ✅ concluído · 🔴 erro · 🟡 interrompido |
| Serviços | 🔴 serviço sem sinal (ativo e mudo há mais de 10 min) · 🟡 serviço mudou no admin (pausar/retomar) · 🔴 mensagem não enviada (no máximo uma por hora) |
| Oportunidades | 💰 oportunidade, no grupo de oportunidades: preço da Amazon (conferido com impostos, frete à parte; ou anunciado, sem impostos), quem vende, referência da Liga e o link do anúncio · ⏹️ oferta encerrada · ⚠️ alerta corrigido |

### Quando chegar um aviso de desafio

1. Abra o noVNC: `http://localhost:6080/vnc.html` (senha `VNC_SENHA`). Por padrão só abre neste PC (veja abaixo como abrir para a rede de casa).
2. O Chromium está aberto com a verificação na tela. Resolva-a nessa janela.
3. Clique em **Retomar** em Serviços. A coleta volta no mesmo navegador depois do esfriamento (30 min por padrão; o card da LigaMagic mostra "Esfriando até HH:MM"), com pausas em dobro até o fim do dia. Se foi o 2º desafio do dia, o card mostra "Parada até amanhã (2º desafio)" e a coleta volta no horário de amanhã ("Rodar agora" some até lá). O aviso do WhatsApp já diz qual dos dois é.

O coletor nunca tenta de novo sozinho. Se a janela do Chromium for fechada, a próxima coleta abre outra.

### Segurança

O admin e o noVNC usam HTTP sem TLS e, por padrão, escutam só neste PC (`127.0.0.1`): nenhum outro aparelho da rede de casa chega neles. O noVNC do monitor (6081) é o navegador logado na sua conta da Amazon. Para abrir para a rede de casa (por sua conta e risco), ponha `ADMIN_ESCUTA=0.0.0.0` e/ou `VNC_ESCUTA=0.0.0.0` no `.env`, rode `docker compose up -d` e, em Configurações → Geral, use o IP deste PC na rede. Nunca exponha as portas 8000, 6080, 6081 e 6082 para a internet. A Evolution API (8080) e o Postgres (5432) só escutam em `127.0.0.1`.

No site novo cada pessoa entra com o próprio número: o código de acesso vai só para o WhatsApp dela, vale 5 minutos e uma vez; 5 tentativas erradas o invalidam; no máximo 3 códigos por número a cada 15 minutos e 20 pedidos por hora no total (acima disso a tela pede para esperar e o grupo admin é avisado). O banco guarda só o HMAC (com a chave `SEGREDO_API` do `.env`) do código, do token da sessão e do número dos pedidos; o número nunca vai para log nem para o grupo (aparece mascarado, `+55 11 9****-**34`). A sessão dura 30 dias, renovada a cada uso; desativar um usuário encerra as sessões dele na hora. A `api` (8100) e o `web` (8090) só escutam em `127.0.0.1`.

Antes de publicar na internet ainda faltam os itens da seção "Segurança antes da internet" de [`docs/PENDENCIAS.md`](docs/PENDENCIAS.md) (limites de login por IP e por número, entre outros). Para avisar de uma falha de segurança, veja [`SECURITY.md`](SECURITY.md).

### Backup do banco

O serviço `manutencao` faz, todo dia às 04:00 (fuso de Configurações → Geral), um `pg_dump` do banco e depois apaga o histórico antigo. Se o PC estava desligado às 04:00, ao subir ele roda na hora quando o último backup ok tem mais de 24 h. Reiniciar não repete o backup do dia.

- **Onde ficam:** em `dados/backups/` neste PC. Diários `tcg-diario-AAAA-MM-DD.dump` (os 7 mais novos) e, aos domingos, semanais `tcg-semanal-AAAA-Wss.dump` (os 4 mais novos). Cada arquivo é conferido com `pg_restore --list` antes de entrar no lugar. Os backups manuais (`tcg-antes-*.dump`) e qualquer outro arquivo da pasta nunca são apagados.
- **Cópia fora do PC:** com as variáveis `R2_*` preenchidas no `.env` (passo a passo no [`.env.example`](.env.example)), cada backup vai também para o bucket do Cloudflare R2: `diario/tcg-AAAA-MM-DD.dump` e `semanal/tcg-AAAA-Wss.dump`. O serviço nunca apaga nada no bucket; as regras de ciclo de vida do bucket apagam `diario/` depois de 7 dias e `semanal/` depois de 35. Sem as variáveis, o backup fica só no PC ("só local") e não há alerta.
- **Acompanhar:** card **Backup** no Dashboard (último ok, tamanho, cópia no R2), **Serviços** para ligar e desligar e **Logs → Manutenção** com cada execução. Falha avisa o grupo admin uma vez e tenta de novo no dia seguinte.
- **Limpeza do histórico** (só depois de um backup local ok): chamadas da IA com mais de 90 dias (a avaliação da IA fica, sem o vínculo com a chamada), conferências de checkout com mais de 180 dias (menos as que podem ter deixado item no carrinho) e coletas com mais de 180 dias que nenhum preço usa. Preços, avaliações da IA e oportunidades nunca são apagados.

Para restaurar um backup (apaga e recria o conteúdo do banco `tcg`): primeiro pare os serviços do app, que escrevem no banco; depois restaure; por fim suba tudo de novo:

```bash
docker compose stop coletor-liga coletor-amazon coletor-amazon-busca casador notificador manutencao admin api web
docker compose exec -T postgres pg_restore -U tcg -d tcg --clean --if-exists < dados/backups/tcg-diario-AAAA-MM-DD.dump
docker compose up -d
```

## Configuração

Os ajustes de operação ficam na página **Configurações** do admin, em quatro seções que salvam separadamente e valem a partir da próxima coleta ou ciclo, sem reiniciar:

- **Geral**: IP ou nome deste PC na rede, fuso horário, instância da Evolution e os grupos de WhatsApp (admin e oportunidades).
- **LigaMagic**: horário da coleta diária e variação, pausas entre páginas, limite de falhas, categorias, URL da listagem, máximo de cliques, produtos novos por dia (padrão 100) e esfriar após desafio (padrão 30 min). Tire de **Categorias** uma que falhe todo dia; pausas menores aumentam a chance de desafio do Cloudflare.
- **Amazon**: desconto mínimo, horário e teto da busca (navegador sem login), horário e teto do monitor (navegador logado), carência para encerrar e demais ajustes do motor de oportunidades.
- **IA**: liga a IA do casamento, modelo, preços, tetos de gasto e de chamadas e o modo automático (ver [passo 9](#9-casamento-com-ia-opcional)).

No `.env` ficam só as senhas e a infraestrutura: `ADMIN_SENHA`, `VNC_SENHA`, `EVOLUTION_API_KEY`, `SEGREDO_API`, `OPENAI_API_KEY`, as `R2_*` do backup, `DATABASE_URL`, `DIR_DADOS` e `EVOLUTION_URL`, explicadas no [`.env.example`](.env.example). Depois de mudar o `.env`, recrie os containers: `docker compose up -d`.

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

As regras para contribuir (idioma, commits, dados pessoais, ritmo de coleta) estão em [`CONTRIBUTING.md`](CONTRIBUTING.md).

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

Para rodar um serviço fora do Docker: `uv run tcg-sniper migrate`, `uv run tcg-sniper admin`, `uv run tcg-sniper coletor-liga`, `uv run tcg-sniper coletor-amazon`, `uv run tcg-sniper coletor-amazon-busca` ou `uv run tcg-sniper notificador`.

### Visual do admin (DaisyUI)

O admin usa DaisyUI 5 sobre Tailwind CSS 4, com os temas winter (claro) e night (escuro). O CSS é gerado e fica versionado em `src/tcg_sniper/admin/static/admin.css`:

- Depois de mudar qualquer template do admin, rode `uv run python scripts/gerar_css.py` (baixa o Tailwind standalone e o DaisyUI em `.ferramentas/` na primeira vez). O teste `test_css_em_dia_com_os_templates` falha se você esquecer.
- Antes de um deploy que mexe no visual, rode `docker compose exec -T admin python - < scripts/verificar_layout.py`: abre as telas em 390 e 1440 px nos dois temas e falha se algo estourar a largura.
- Só use componentes e classes do DaisyUI/Tailwind; não escreva CSS próprio.

### Estrutura

```
src/tcg_sniper/
  cli.py              comandos migrate, admin, api, codigo-acesso, criar-superadmin, trocar-superadmin, coletor-liga,
                      coletor-amazon, coletor-amazon-busca, notificador, casador, manutencao e ia
  config.py           leitura do .env
  coletor_liga/       agendador, navegador (Playwright), parsers e as duas etapas da coleta
  coletor_amazon/     monitor de preço, conferência de checkout, fila de buscas (dois laços: `varredura_busca`, `varredura_monitor`, sobre `varredura_base`), parsers da Amazon e cliques permitidos
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
docs/PENDENCIAS.md    lista única do que falta e das decisões tomadas
docs/IMPLANTACOES.md  passos extras de atualização de cada versão
docs/superpowers/     especificações e planos de implementação
```

### Quando a LigaMagic muda o layout

1. Pegue o HTML que falhou em `/data/falhas` (`docker compose cp coletor-liga:/data/falhas/<arquivo> .`).
2. Ou capture uma página nova: `uv run python scripts/capturar_fixture.py <url> <nome>` (com `--expandir` para uma listagem).
3. Adicione a página em `tests/fixtures/liga`, escreva o teste que falha e ajuste `src/tcg_sniper/coletor_liga/parsers.py`. O docstring do arquivo descreve a estrutura esperada de cada página.
4. Antes de commitar, recorte a página: `uv run python scripts/recortar_fixture.py tests/fixtures/liga/<nome>.html`. O repositório guarda só os trechos que os parsers leem, nunca a página inteira. O script confere que os parsers dão o mesmo resultado no original e no recorte; se ele recusar, inclua os blocos novos que o parser passou a ler na lista do script.

O desenho completo está em [`docs/superpowers/specs/2026-10-13-coletor-liga-design.md`](docs/superpowers/specs/2026-10-13-coletor-liga-design.md).

## Roadmap

Pronto:

- Coleta da LigaMagic, admin e avisos no WhatsApp.
- Amazon: busca, monitor de preço, conferência de checkout e oportunidades.
- Casamento de produtos por par, com IA opcional e regra de idioma.
- Backup diário, vigia dos serviços e site novo fase 1 (login pelo WhatsApp, usuários, papéis e acessos).

Próximos, nesta ordem:

1. **Site novo, fase 2:** área de negócio (oportunidades, funil, resultados).
2. **Site novo, fases 3 e 4:** telas de administração no site novo e desligamento do admin antigo.
3. **Segurança antes da internet** e **publicação**: front estático, API por túnel, controle de acesso na frente da gestão e do noVNC.
4. **Assinatura das oportunidades** para quem não quer instalar.
5. **Margem líquida real:** comissão da LigaMagic, frete, imposto, cupons e cashback no cálculo, com alerta por margem mínima.
6. **Mais lojas:** Mercado Livre (pelo navegador) e depois Magalu, Shopee e lojas de TCG.
7. **Servidor:** API, site e banco num VPS, com os coletores em casa.

O detalhe de cada item está em [`docs/PENDENCIAS.md`](docs/PENDENCIAS.md).

## Contribuir

Issues e pull requests são bem-vindos; veja [`CONTRIBUTING.md`](CONTRIBUTING.md). Falhas de segurança vão pelo aviso privado descrito em [`SECURITY.md`](SECURITY.md), nunca por issue pública.

## Licença e avisos

Código sob a licença [MIT](LICENSE): pode ser usado, copiado, modificado e distribuído, inclusive comercialmente, mantendo o aviso de copyright e a licença. O software vem sem garantia de nenhum tipo.

- **Sem afiliação.** O tcg-sniper não é afiliado, patrocinado nem aprovado pela LigaMagic, pela Amazon, pela Wizards of the Coast, pela Meta (WhatsApp) nem pela OpenAI. Magic: The Gathering é marca da Wizards of the Coast; os demais nomes são marcas dos seus donos e aparecem só para dizer com o que o projeto conversa. A licença do código não dá direito sobre essas marcas.
- **Termos dos sites.** Quem instala e roda o tcg-sniper é responsável por seguir os termos de uso dos sites acessados e as leis aplicáveis, e por manter o ritmo de coleta descrito em [Uso responsável](#uso-responsável).
- **Não é recomendação de compra.** As oportunidades são cálculos a partir de preços públicos, que mudam a qualquer momento. Confira preço, vendedor e produto antes de comprar; o projeto nunca compra por você.
