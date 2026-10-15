# Notificador com tabela de saída

Data: 2026-10-15
Contexto: hoje cada serviço (coletor da Liga, coletor da Amazon) chama a Evolution API na hora, com 3 tentativas; se a Evolution ou o WhatsApp estiverem fora, a mensagem é descartada. A instância e os grupos vêm de Configurações → Geral (`2026-10-15-configuracao-em-tela-design.md`).

## Objetivo

Nenhum alerta se perde quando a Evolution ou o WhatsApp ficam fora do ar. Os serviços gravam as mensagens numa tabela de saída; um serviço próprio, `notificador`, envia, tenta de novo até conseguir e registra o resultado. O admin mostra o que saiu, o que está pendente e o que falhou.

Critério de sucesso: com a Evolution parada por uma hora, nenhuma mensagem do admin se perde e as oportunidades com menos de 6 h saem quando ela volta; o Dashboard avisa que há mensagens paradas; pela tela Mensagens dá para reenviar ou descartar.

## Escopo

Dentro:

- Tabela `mensagem_saida` e o `NotificadorFila` (grava em vez de enviar).
- Serviço `notificador` (container novo) com tentativas, validade e limpeza.
- Tela **Mensagens**, cartão e aviso no Dashboard, cartão em Serviços.
- Campo "Validade das oportunidades (h)" em Configurações → Geral.

Fora:

- Aviso instantâneo via `LISTEN/NOTIFY` (pode entrar depois sem mudar a tabela).
- Outros canais (Telegram) e receber mensagens.

## Decisões de 2026-10-15

1. Mensagens acumuladas: as do admin saem sempre, mesmo atrasadas; as de oportunidade só saem se tiverem menos que a validade (padrão 6 h, editável); as vencidas ficam `expirada`.
2. Tela de mensagens com **Reenviar** e **Descartar**.
3. Container próprio que lê a tabela a cada 5 s (não `LISTEN/NOTIFY`, não thread no admin).

## Dados

`mensagem_saida`:

| Coluna | Tipo | Observação |
|---|---|---|
| `id` | inteiro | chave |
| `destino` | texto | `admin` ou `oportunidades` (`Destino`) |
| `texto` | texto | não vazio |
| `status` | texto | `pendente`, `enviada`, `falha`, `expirada`, `descartada` |
| `tentativas` | inteiro | ≥ 0, começa em 0 |
| `proxima_tentativa_em` | data/hora | quando pode ser tentada de novo |
| `ultimo_erro` | texto | nulo se nunca falhou |
| `ignorar_validade` | booleano | marcado pelo Reenviar |
| `criada_em`, `atualizado_em` | data/hora | |
| `enviada_em` | data/hora | nulo até enviar |

Índice em (`status`, `proxima_tentativa_em`).

`estado_notificador` (uma linha, `id = 1`): `ultimo_ciclo_em` (data/hora, nulo até o primeiro ciclo). Tabela própria, e não uma linha em `estado_coletor`, porque o notificador não tem pausa nem desafio.

`config_geral` ganha `validade_oportunidade_h` (inteiro, 1 a 48, padrão 6), editável em Configurações → Geral ("Validade das oportunidades (h)": "Oportunidade que não saiu em até tantas horas, por o WhatsApp estar fora, é descartada como expirada.").

## Gravação (`NotificadorFila`)

- `criar_notificador(config, sessoes)` passa a devolver `NotificadorFila(sessoes)`, que implementa `Notificador`: `enviar(destino, texto)` insere uma linha `pendente` com `proxima_tentativa_em = criada_em = agora`, numa transação curta e própria.
- Nunca lança exceção (contrato do `Notificador`): erro ao gravar vira log com o texto da mensagem.
- Os coletores não falam mais com a Evolution; o código que chama `notificador.enviar` não muda.

## Serviço `notificador`

Comando `tcg-sniper notificador`. Laço: a cada 5 s, um ciclo; erro inesperado num ciclo vira log e o laço segue.

Ciclo:

1. Lê a configuração geral (instância, grupos, validade) do banco e grava `estado_notificador.ultimo_ciclo_em = agora`.
2. Pega até 20 mensagens `pendente` com `proxima_tentativa_em <= agora`, por `criada_em`, com `FOR UPDATE SKIP LOCKED`.
3. Para cada uma:
   - Oportunidade com `criada_em` mais velha que a validade e sem `ignorar_validade` → `expirada`.
   - Sem chave da Evolution (vazia ou padrão), sem instância ou sem grupo para o destino → continua `pendente`, `proxima_tentativa_em = agora + 1 min`, `ultimo_erro` explica o que falta; `tentativas` não muda.
   - Senão, um envio (sem tentativas internas; timeout de 15 s):
     - sucesso (2xx) → `enviada`, `enviada_em = agora`;
     - erro de rede ou 5xx → `tentativas + 1`, `proxima_tentativa_em = agora + min(2^(tentativas−1), 30) min`, `ultimo_erro`; sem limite de tentativas;
     - 4xx → `tentativas + 1`; na 5ª, `falha`; antes disso, a mesma espera do caso anterior.
4. Uma vez por dia (primeiro ciclo depois de 24 h da última limpeza, guardada em memória), apaga `enviada`, `expirada` e `descartada` com `criada_em` de mais de 30 dias. `falha` e `pendente` nunca são apagadas.

A URL e a chave da Evolution continuam no `.env` (`EVOLUTION_URL`, `EVOLUTION_API_KEY`); a instância vai no caminho codificada (`quote(instancia, safe="")`), como hoje.

## Admin

- **Menu:** Dashboard · Serviços · Catálogo · Casamentos · Ofertas · Mensagens · Configurações.
- **Mensagens (`/mensagens`):** filtros na URL — situação (`todas`, `pendente`, `enviada`, `falha`, `expirada`, `descartada`) e destino (`todos`, `admin`, `oportunidades`); valores inválidos → 400; 50 por página, mais recentes primeiro. Cada linha: criada em, destino, texto (as duas primeiras linhas, o resto num `<details>`), situação, tentativas, último erro, enviada em.
  - Botões: `falha` e `expirada` → **Reenviar** e **Descartar**; `pendente` → **Descartar**.
  - `POST /mensagens/<id>` com `acao` = `reenviar` ou `descartar` e `voltar` (só caminhos que começam com `/mensagens`). Reenviar: `status = pendente`, `tentativas = 0`, `proxima_tentativa_em = agora`, `ignorar_validade = true`, `ultimo_erro` limpo. Descartar: `status = descartada`. Ação que não vale para a situação atual (ex.: reenviar uma `enviada`) → 409; mensagem inexistente → 404.
- **Dashboard:** cartão **WhatsApp** com pendentes, falhas e o último envio com sucesso. Aviso no topo (como o de serviço pausado) quando houver `falha` ou `pendente` criada há mais de 30 min, com o último erro e o link "Ir para Mensagens".
- **Serviços:** cartão **Notificador** só com o estado: "rodando" se `ultimo_ciclo_em` tem menos de 1 min; "parado desde <data>" se mais; "nunca rodou" se nulo. Sem botões.

## Deploy e transição

- Migração: `mensagem_saida`, `estado_notificador` (com a linha 1) e `config_geral.validade_oportunidade_h` (padrão 6 nas linhas existentes).
- Compose: serviço `notificador` com a mesma imagem, comando `tcg-sniper notificador`, `depends_on: migrate` concluído; sem navegador, sem noVNC.
- Deploy: backup do banco; `docker compose up -d --build` (migrate, notificador, admin e coletores). Durante a troca, um coletor antigo ainda envia direto e o novo só grava: cada mensagem tem um caminho só, então nada se perde nem duplica.
- README: a página Mensagens, o serviço novo e o que fazer com o aviso no Dashboard (conferir a instância na Evolution e os grupos em Configurações → Geral).

## Testes

- `NotificadorFila`: grava `pendente`; com o banco indisponível, não lança e registra no log.
- Ciclo do serviço (Evolution simulada): sucesso → `enviada`; 5xx → espera 1, 2, 4… até 30 min, sem virar `falha`; 4xx → `falha` na 5ª; sem instância/grupo/chave → continua `pendente` sem contar tentativa; oportunidade vencida → `expirada`; com `ignorar_validade` sai mesmo vencida; admin vencida sai; ordem por `criada_em`; até 20 por ciclo.
- Dois ciclos concorrentes (duas sessões) não pegam a mesma mensagem.
- Limpeza: apaga só `enviada`/`expirada`/`descartada` de mais de 30 dias.
- `ultimo_ciclo_em` atualizado a cada ciclo; cartão de Serviços com os três estados.
- Mensagens: cada filtro, paginação mantendo filtros, valor inválido → 400, Reenviar/Descartar, 409 e 404, `voltar` fora de `/mensagens` vira `/mensagens`.
- Dashboard: aviso com falha e com pendente antiga; sem aviso com pendente recente.
- Configurações → Geral: validade 1–48, inválida → 400.
- O teste que compara os modelos com as migrações continua passando.
