# Segurança, etapa 1: fechar o caminho até a Amazon e um login que ninguém derruba

Data: 2026-10-23. Aprovado em conversa (brainstorming) com o usuário.

Primeira parte da Seção 1 de `docs/PENDENCIAS.md` ("Segurança antes da internet"). A Seção 1 foi dividida em duas etapas; esta é a etapa 1. A etapa 2 fica registrada no fim, para antes de publicar na internet.

## Problema

O que mais preocupa o usuário: **alguém derrubar o login** ou **acessar a conta da Amazon**.

- **Login:** `POST /api/auth/pedir-codigo` tem um limite **global** de 20 pedidos por hora (`LIMITE_TOTAL` em `src/tcg_sniper/api/acesso.py`). Qualquer um que peça 20 códigos (para números quaisquer) tranca o login de todos por até 1 h. Os outros limites (3 códigos por número em 15 min, 10 tentativas de entrar por número em 15 min, 5 códigos errados seguidos) são por número e continuam bons.
- **Amazon:** o noVNC do monitor (`:6081`) é o navegador logado na conta da Amazon; os três noVNC (`6080`–`6082`) e o admin antigo (`8000`) escutam em `0.0.0.0`, então qualquer aparelho da rede de casa chega neles. O VNC usa só os 8 primeiros caracteres de `VNC_SENHA`.
- **Sessões:** `sessao` encerradas ou vencidas nunca são apagadas (pedidos e códigos são, depois de 1 dia, em `repositorio_acesso.limpar_antigos`).

## Contexto do usuário

- Hoje são **2 pessoas**, em beta; abrir para assinantes vai levar tempo.
- Todo o uso é **só deste PC**: o noVNC só é aberto daqui, e o site novo (`127.0.0.1:8090`) e a API (`127.0.0.1:8100`) já escutam só aqui.
- A etapa 1 não pode mudar a rotina do usuário.

## Decisões do usuário

- Dividir a Seção 1: etapa 1 agora (pequena, sem mudar a rotina), etapa 2 antes de publicar na internet.
- Etapa 1 = fechar o admin antigo e o noVNC neste PC + login sem bloqueio global + faxina de sessões.

## Etapa 1

### 1. Admin antigo e noVNC só neste PC

- `docker-compose.yml`: as portas passam a usar um endereço de escuta configurável, com padrão **`127.0.0.1`**:
  - admin: `"${ADMIN_ESCUTA:-127.0.0.1}:8000:8000"`;
  - noVNC: `"${VNC_ESCUTA:-127.0.0.1}:6080:6080"`, `"${VNC_ESCUTA:-127.0.0.1}:6081:6080"`, `"${VNC_ESCUTA:-127.0.0.1}:6082:6080"`.
- `.env.example` documenta `ADMIN_ESCUTA` e `VNC_ESCUTA` (vazias = só este PC; `0.0.0.0` reabre para a rede de casa, por conta e risco).
- Os links do noVNC no admin antigo (montados com o "IP ou nome deste PC na rede" de Configurações → Geral, `host_publico`) continuam funcionando neste PC quando `host_publico` for `localhost`/`127.0.0.1`; com outro valor, o link deixa de abrir. A explicação do campo `host_publico` passa a dizer isso, e as notas de implantação mandam trocar o valor para `127.0.0.1` se ele estiver com o IP da rede.
- README (seção do noVNC e da instalação) atualizado: por padrão só no próprio PC.
- Chamada minha: o padrão vira `127.0.0.1` (e não `0.0.0.0` como o plano antigo dizia), porque o usuário só usa deste PC; quem precisar de outro aparelho reabre pelo `.env`.

### 2. Login sem bloqueio global

- **Sai** o limite global (`LIMITE_TOTAL` de 20 pedidos por hora para todos, com a trava `TRAVA_PEDIDOS_TOTAL` e o aviso de "limite total"). Era ele que deixava qualquer um trancar o login de todos.
- **Ficam** os limites **por número**, como estão: 3 códigos por número em 15 min; 10 tentativas de entrar por número em 15 min; 5 códigos errados invalidam o código. Com eles, quem pede códigos para números cadastrados manda no máximo 3 mensagens por número a cada 15 min, e um número sem cadastro nunca gera mensagem.
- A resposta continua igual para número com e sem cadastro; o aviso `SEGURANCA_LIMITE` por número continua; o aviso do limite total sai do catálogo (texto, exemplo e testes ajustados).
- O acesso de emergência (`tcg-sniper codigo-acesso`) não muda.
- **Sem limite por origem (IP) na etapa 1** (chamada minha, depois da revisão da spec): no Docker Desktop do Windows todo pedido feito neste PC chega à API com o mesmo endereço (o gateway do Docker, repassado pelo Caddy), então um limite "por origem" seria um limite global disfarçado e voltaria a deixar alguém trancar o login dos dois usuários. Como hoje só este PC alcança o site e a API, o limite por origem vai para a etapa 2, lendo o IP real que o Cloudflare repassa (`CF-Connecting-IP`).

### 3. Faxina de sessões

- A manutenção diária apaga `sessao` encerradas há mais de **30 dias** ou vencidas (`expira_em`) há mais de **30 dias** (chamada minha: dá tempo de ver "quem entrou de onde" na tela de Usuários sem acumular para sempre). Roda junto com a limpeza de histórico (`db/retencao.py`, depois do backup ok) e entra na contagem "apagados" de Logs → Manutenção.
- Sessão ativa nunca é apagada.

## Etapa 2 — antes de publicar na internet (não faz parte desta entrega)

Registrada na Seção 1 de `docs/PENDENCIAS.md`:

- Cloudflare Access na frente do que for exposto; admin antigo e noVNC **nunca** publicados.
- Limite de login **por origem** (pedidos de código e tentativas de entrar por IP), com o IP real lido de `CF-Connecting-IP` só quando o pedido vem do túnel do Cloudflare, guardado só como HMAC; aviso de ataque por origem no grupo admin.
- Autenticação de verdade no noVNC (senha longa na frente do websockify, ou só pela VPN), mantendo `VNC_SENHA` como segunda barreira.
- Código de acesso cifrado na fila do WhatsApp (`mensagem_saida`).
- Mesmo tempo de resposta para número com e sem cadastro no login.
- Domínio próprio para as imagens no lugar do `r2.dev`.
- Revisar os números dos limites da etapa 1 com o volume real de assinantes.

## Fora do escopo

- Mudar o jeito de entrar (continua o código pelo WhatsApp).
- Rate limit fora do login (outras rotas da API exigem sessão).
- Mexer na Evolution API (já escuta só em `127.0.0.1`).

## Testes

- Sem limite global: 21 pedidos para 21 números diferentes na mesma hora são aceitos; os limites por número continuam (4º código do mesmo número em 15 min → 429; 11ª tentativa de entrar → 429).
- O aviso do limite total não existe mais no catálogo; o aviso por número continua abrindo e resolvendo.
- Faxina: sessão encerrada há 31 dias some, há 29 fica; ativa nunca some.
- Compose: teste que lê `docker-compose.yml` e garante que admin e noVNC usam `${ADMIN_ESCUTA:-127.0.0.1}`/`${VNC_ESCUTA:-127.0.0.1}`, e que nenhuma porta publicada fica em `0.0.0.0` sem variável.

## Implantação

Sem migração. `docker compose up -d --build`. Depois: conferir que `:8000` e `:6080`–`:6082` abrem neste PC e não de outro aparelho da rede; em Configurações → Geral, trocar "IP ou nome deste PC na rede" para `127.0.0.1` se estiver com o IP da rede (senão os links do noVNC do admin antigo não abrem); entrar no site pelo código do WhatsApp normalmente.

## Deixado ao construtor

O nome exato das constantes; a forma do teste do compose; se a faxina de sessões entra na contagem "apagados" de Logs → Manutenção com uma chave própria (`sessao`) — conferir se as telas leem as chaves por nome.
