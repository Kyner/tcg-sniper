# Avisos no WhatsApp: padrão único e catálogo de eventos

Data: 2026-10-18. Aprovado em conversa (brainstorming) com o usuário.

## Objetivo

1. Toda mensagem de WhatsApp sai num formato único, pensado para leitura no celular.
2. Nenhuma mensagem leva endereço do sistema (admin `:8000`, noVNC `:6080`/`:6081`, IP de casa): eles só abrem na rede de casa e são inúteis no celular fora dela. Links de produto (Amazon, LigaMagic) continuam.
3. O grupo admin é avisado ao concluir cada tarefa, ao encontrar problemas e quando o problema some.
4. Repetições não inundam o grupo: o mesmo problema sai uma vez, volta como lembrete a cada 2 h enquanto continuar e fecha com "resolvido".

## Decisões do usuário

- Motivo de tirar as URLs: utilidade (só abrem em casa), não segurança.
- Avisar ao concluir **cada** tarefa, inclusive cada rodada do monitor de preço da Amazon (~60–70 mensagens/dia no admin). Cada tipo pode ser desligado numa tela.
- Ações sem link: a mensagem diz onde fazer ("noVNC da Amazon (porta 6081)", "Admin → Serviços → Amazon → Retomar").
- Estilo: emoji de severidade + título em negrito + linhas com "•" + "*O que fazer:*" + rodapé em itálico.
- Repetição: agrupar, lembrete a cada 2 h, "✅ resolvido" ao fechar.

## Arquitetura

### Módulo `src/tcg_sniper/avisos/`

- `catalogo.py`: enum `TipoAviso` e uma `DefinicaoAviso` por tipo:
  - `severidade`: `FALHA` (🔴), `ATENCAO` (🟡), `CONCLUIDO` (✅), `OPORTUNIDADE` (💰). "Resolvido" usa ✅.
  - `grupo`: `Destino.ADMIN` ou `Destino.OPORTUNIDADES`.
  - `titulo`: texto fixo do cabeçalho (ex.: "Amazon · CAPTCHA").
  - `agrupa`: se repetições com a mesma chave são agrupadas (problemas: sim; conclusões e oportunidade: não).
  - `lembrete`: `timedelta(hours=2)` para os que agrupam; `None` para os demais.
  - `ligado_padrao`: todos `True`.
  - `exemplo`: dados fictícios usados na tela Avisos e nos testes.
- `formato.py`: única função que transforma um aviso em texto. Recebe `Aviso(tipo, titulo_extra, linhas, acao, origem, quando, link_produto)` e devolve:
  ```
  <emoji> *<titulo>[ · titulo_extra]*
  [linha de destaque opcional]
  • <linha>
  • <linha>

  *O que fazer:* <acao>
  <link de produto, se houver>
  _dd/mm HH:MM · <origem>_
  ```
  - Escapa `*`, `_`, `~` e crase vindos dos dados (nome de produto, mensagem de erro).
  - Corta em ~1500 caracteres com "…".
  - Hora no fuso de Configurações → Geral.
  - Garante a regra de URL: recusa (exceção em teste, remoção + log em produção) qualquer `http(s)://` que não seja de `amazon.com.br` ou `ligamagic.com.br`, e qualquer menção a `:8000`, `:6080`, `:6081` ou ao `host_publico`.
- `servico.py` (API pública):
  - `avisar(s, tipo, chave, dados, agora)`: registra a ocorrência e, conforme a regra de repetição e o liga/desliga, enfileira a mensagem pelo `Notificador` atual.
  - `resolver(s, tipo, chave, agora)`: fecha um problema aberto; se algum aviso dele foi enviado, manda "✅ <título> resolvido · N vezes em <duração>".
  - Nenhuma das duas propaga exceção para o chamador: falha vira log (como `NotificadorFila.enviar` hoje).
- `chave`: separa ocorrências do mesmo tipo (ex.: ASIN no item do carrinho, nome do serviço no vigia, `"geral"` quando não há distinção).

### Regra de repetição (tipos com `agrupa`)

Estado por `(tipo, chave)` na tabela `estado_aviso`:

| Situação | Ação |
|---|---|
| Não há aberto | abre (primeiro_em, ocorrencias=1) e envia |
| Aberto, último envio < 2 h | só incrementa ocorrencias / ultimo_em |
| Aberto, último envio ≥ 2 h | envia lembrete "🔴 <título> continua · N vezes desde HH:MM" |
| `resolver` com aberto | fecha; envia "✅ resolvido" se algum envio saiu |
| `resolver` sem aberto | nada |

- Tipo desligado: o estado é atualizado, nada é enviado. Ao religar com problema aberto, o próximo lembrete sai normalmente.
- Lembretes não se acumulam com o notificador parado: o lembrete é decidido no momento do `avisar`; no máximo um por problema por janela de 2 h.

### Banco (uma migração)

- `estado_aviso`: `tipo` (texto), `chave` (texto), `aberto` (bool), `primeiro_em`, `ultimo_em`, `ultimo_envio_em` (timestamptz, nulo), `ocorrencias` (int). PK `(tipo, chave)`.
- Liga/desliga por tipo: `config_aviso` (`tipo` PK, `ligado` bool), linha ausente = `ligado_padrao`.
- No deploy nada aberto é herdado.

### Vigia de serviços

O serviço `manutencao` (acorda a cada 60 s) verifica o último sinal de vida de coletor-liga, coletor-amazon, casador e notificador (o admin não registra sinal de vida). Serviço ativo e mudo > 10 min abre `SERVICO_SEM_SINAL` (chave = serviço); quando volta, `resolver`. Serviços pausados por você são ignorados. O próprio `manutencao` sem sinal continua aparecendo no card do Dashboard (já existe).

### Tela

Configurações → aba **Avisos** (DaisyUI, classes literais): para cada tipo, severidade, grupo, mensagem de exemplo renderizada pelo `formato.py` e um toggle liga/desliga. Entra no `scripts/verificar_layout.py`.

### O que não muda

`notificador` (envio, tentativas, validade das oportunidades configurável em Configurações → Geral (padrão 6 h), avisos do admin não vencem), tabela `mensagem_saida` e tela Mensagens.

## Catálogo

Todos no grupo admin, exceto a oportunidade. "Novo" = não existe hoje.

| Tipo | Sev. | Agrupa | Resolve quando | Origem / gatilho |
|---|---|---|---|---|
| `LIGA_COLETA_CONCLUIDA` | ✅ | não | — | coleta ok (listagens, produtos, duração); hoje `execucao.mensagem_resumo` |
| `LIGA_COLETA_PARCIAL` | 🟡 | não | — | novo: coleta PARCIAL |
| `LIGA_COLETA_FALHOU` | 🔴 | sim | próxima coleta ok | `execucao.py` FALHA |
| `LIGA_DESAFIO` | 🔴 | sim | coleta retomada / próxima página ok | `execucao.mensagem_desafio` |
| `LIGA_PRODUTOS_NOVOS` | 🟡 | não | — | `listagens.py` produtos novos |
| `LIGA_INTERROMPIDA` | 🟡 | não | — | `agendador.py` reinício |
| `LIGA_ERRO` | 🔴 | sim | próxima coleta ok | `agendador.py` erro em job, `execucao.encerrar_por_erro` |
| `AMAZON_BUSCA_CONCLUIDA` | ✅ | não | — | novo: ciclo de busca ok |
| `AMAZON_MONITOR_CONCLUIDO` | ✅ | não | — | novo: rodada do monitor (lidos, quedas, conferências) |
| `AMAZON_BUSCA_PARCIAL` | 🟡 | não | — | novo |
| `AMAZON_BUSCA_FALHOU` | 🔴 | sim | próximo ciclo ok | `varredura.py` FALHA |
| `AMAZON_CAPTCHA` | 🔴 | sim | próxima página ok | `varredura.mensagem_captcha` (inclui aviso de item no carrinho) |
| `AMAZON_SEM_LOGIN` | 🔴 | sim | conferência volta a rodar | `varredura.mensagem_sem_login` |
| `AMAZON_CARRINHO` | 🔴 | sim (chave ASIN) | "já conferi" ou item retirado | `varredura.mensagem_conferir_a_mao` |
| `AMAZON_PAUSADA` | 🔴 | sim | retomada | junta as 4 mensagens de pausa por falhas/erros seguidos (com e sem registro no banco) |
| `AMAZON_ERRO` | 🟡 | sim | próxima rodada ok | `varredura.py` erro inesperado (hoje 1 mensagem por erro) |
| `AMAZON_INTERROMPIDA` | 🟡 | não | — | `varredura.py` reinício |
| `IA_RODADA_CONCLUIDA` | ✅ | não | — | novo: rodada do casador que avaliou ≥ 1 (avaliados, confirmados, esperando você) |
| `IA_PAUSADA` | 🔴 | sim | retomado | `casador/servico.py` chave/config inválida |
| `IA_SEM_ORCAMENTO` | 🟡 | sim (chave = período) | próximo período | `casador/servico.py` (substitui o dedup em memória) |
| `IA_FALHAS_SEGUIDAS` | 🟡 | sim | próxima chamada ok | novo |
| `BACKUP_CONCLUIDO` | ✅ | não | — | novo: tamanho, R2 sim/não, linhas limpas |
| `BACKUP_ERRO` | 🔴 | sim | próximo backup ok | `manutencao/servico.py` |
| `BACKUP_INTERROMPIDO` | 🟡 | não | — | `manutencao/servico.py` |
| `SERVICO_SEM_SINAL` | 🔴 | sim (chave = serviço) | sinal voltou | novo: vigia |
| `SERVICO_PAUSADO_MANUAL` | 🟡 | não | — | novo: pausar/retomar no admin (qual serviço e o estado novo) |
| `MENSAGEM_NAO_ENVIADA` | 🔴 | sim, máx. 1/h, lista as falhas | — | novo: falha definitiva no notificador; nunca gerada pela falha dela mesma |
| `OPORTUNIDADE` | 💰 | não (regras atuais do motor) | — | `oportunidades/mensagens.py`, grupo oportunidades, sem linha "Admin" |

Mensagem de oportunidade:
```
💰 *Oportunidade · 18% abaixo da Liga*
*<nome do produto>*
• Amazon: *R$ 1.299,90* (conferido, com impostos; frete à parte)
• Vendido por: Amazon · Prime
• Liga: a partir de R$ 1.589,00 · 12 lojas · média R$ 1.640,00
• Cupom: … (se houver)
<link do anúncio na Amazon>
_dd/mm HH:MM · monitor Amazon_
```
Quando o preço não foi conferido no checkout, a linha da Amazon diz "anunciado, sem impostos" (regra atual mantida).

## Erros

- `avisar`/`resolver` nunca derrubam o serviço chamador.
- WhatsApp fora do ar: mensagens esperam na fila (como hoje); lembretes não se acumulam.
- `MENSAGEM_NAO_ENVIADA` não entra em laço: falha ao enviar esse aviso só vai para o log.

## Testes

- Um teste por tipo: texto montado comparado com o modelo (dados do `exemplo`).
- Teste global de URL: nenhuma mensagem gerada (todos os exemplos e os testes dos serviços) contém endereço do sistema.
- Regra de repetição com relógio fixo: primeira ocorrência, repetição silenciosa, lembrete em 2 h, resolver com e sem envio, tipo desligado e religado.
- Teste AST/grep: fora de `avisos/` nada chama `Notificador.enviar`/`repositorio_mensagens.enfileirar` direto.
- Vigia: serviço mudo > 10 min abre; volta resolve; pausado é ignorado.
- Admin: aba Avisos lista todos os tipos, toggle grava, layout passa no `verificar_layout.py`.

## Fora do escopo

Resumo diário, horário de silêncio, avisos por pessoa, outros canais além do WhatsApp.
