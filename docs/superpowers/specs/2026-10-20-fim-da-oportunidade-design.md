# Fim da oportunidade: motivo, carência e aviso de oferta encerrada

Data: 2026-10-20. Aprovado em conversa (brainstorming) com o usuário.

Sub-projeto A de três (A: fim da oportunidade; B: área de negócio, oportunidades; C: área de negócio, mercado). A grava os dados que B vai mostrar em gráficos e acompanhamento.

## Problema

Uma oportunidade fecha sem guardar o motivo e sem avisar ninguém. Quem viu o alerta no grupo de oportunidades não sabe que a oferta acabou e pode perder tempo tentando comprar. Um preço que oscila em volta do desconto mínimo abre e fecha várias vezes no dia. E não há histórico da oportunidade além de abrir e fechar, o que a área de negócio (B) precisa para mostrar duração, evolução e recorrência.

## Decisões do usuário

- Aviso de encerramento: mudanças de mercado vão para o **grupo de oportunidades**; motivos técnicos vão para o **grupo admin**; casamento desfeito ou trocado vai para o grupo de oportunidades como "alerta corrigido".
- **Carência de 30 min** antes de encerrar (configurável), para oscilação curta não gerar nada.
- Abordagem 1: colunas novas na `oportunidade`; a curva de preço durante a oferta sai do `preco_amazon` (histórico só de acréscimo, nunca apagado). Sem tabela de eventos.

## Motivos de encerramento

Gravados em `oportunidade.motivo_encerramento`. Quando muda mais de uma coisa na mesma leitura, vale o primeiro desta lista:

| Motivo | Quando | Carência | Aviso |
| --- | --- | --- | --- |
| `casamento_desfeito` | o par foi desfeito, ignorado ou trocado em Casamentos (todos os caminhos de `repositorio_casamento.fechar_oportunidades`) | não | Alerta corrigido (oportunidades) |
| `sem_leitura` | anúncio sem nenhuma leitura há 24 h (`fechar_oportunidades_sem_leitura`) | não | Encerrada, técnico (admin) |
| `liga_desatualizada` | preço da Liga com mais de `liga_preco_max_idade_h` (48 h) | sim | Encerrada, técnico (admin) |
| `oferta_sumiu` | leitura sem preço (indisponível) | sim | Oferta encerrada (oportunidades) |
| `vendedor` | envio ou vendedor não elegível (`vendedor_elegivel` falso) | sim | Oferta encerrada (oportunidades) |
| `liga_caiu` | não atinge o desconto, mas o preço atual da Amazon atingiria contra o `preco_liga` gravado na oportunidade | sim | Oferta encerrada (oportunidades) |
| `preco_subiu` | não atinge o desconto e não é o caso anterior | sim | Oferta encerrada (oportunidades) |

Oportunidades fechadas antes desta versão ficam com o motivo vazio (NULL, "antes do registro").

## Carência

- Leitura não elegível com oportunidade aberta e sem risco: grava `em_risco_desde = agora` e `motivo_risco`. Não fecha nem avisa.
- Leitura não elegível com risco já marcado: atualiza `motivo_risco` com o motivo desta leitura. Se `agora − em_risco_desde ≥ carencia_encerramento_min`, encerra com esse motivo.
- Leitura elegível com risco marcado: limpa `em_risco_desde` e `motivo_risco`, sem aviso. Se a mesma leitura também realerta (queda de preço), segue o realerta normal.
- Sem leitura não há decisão: fora da janela do monitor (22h–08h) a oportunidade em risco só encerra na primeira leitura ruim depois das 08h, ou por `sem_leitura` em 24 h.
- O estado fica no banco: reiniciar o monitor não zera a contagem. Mudar a carência vale na próxima leitura.

## Banco (migração nova)

`oportunidade`, colunas novas:

- `motivo_encerramento` text NULL;
- `em_risco_desde` timestamptz NULL; `motivo_risco` text NULL;
- `menor_preco` numeric (DINHEIRO) NOT NULL: o menor `preco_amazon` da oportunidade, atualizado a cada leitura que a mantém aberta;
- `alertas` integer NOT NULL default 1: avisos de oportunidade enfileirados (abertura + realertas);
- `mensagem_alerta_id` integer NULL, FK `mensagem_saida.id` `ON DELETE SET NULL` (a limpeza apaga mensagens com mais de 30 dias): a mensagem do último alerta;
- `encerramento_avisado_em` timestamptz NULL;
- `deixou_de_valer_em` timestamptz NULL: gravado no encerramento, `em_risco_desde` (a primeira leitura ruim) ou, sem risco, a hora do encerramento;
- `alerta_sem_registro` boolean NOT NULL default false: a oportunidade foi aberta antes desta versão, quando o id da mensagem não era guardado.

Um `CHECK` limita `motivo_encerramento` e `motivo_risco` aos valores da tabela acima.

`config_amazon`: `carencia_encerramento_min` integer NOT NULL default 30 (faixa 0–240; 0 = sem carência).

Preenchimento: as oportunidades existentes recebem `menor_preco = preco_amazon` e `alertas = 1`; as abertas recebem `alerta_sem_registro = true` (ao encerrar, contam como "alerta enviado", ver Encerramento). O downgrade remove as colunas.

## Componentes

### Motor (`oportunidades/motor.py`, funções puras)

- `motivo_inelegivel(leitura, ref, regras, agora, preco_liga_anterior) -> MotivoEncerramento | None`: None quando elegível; senão o motivo na ordem da tabela (sem os dois que não vêm de leitura).
- `decidir()` recebe também `em_risco_desde`, `carencia` e o `preco_liga` da oportunidade, e ganha `Acao.EM_RISCO` e `Acao.RECUPERAR`. `Acao.FECHAR` só sai com a carência vencida. A decisão devolve também o motivo.

### Monitor (`coletor_amazon/monitor.py`)

- Aplica `EM_RISCO` (grava o risco), `RECUPERAR` (limpa) e `FECHAR` (chama o encerramento).
- `ATUALIZAR`, `REALERTAR` e `RECUPERAR` atualizam `menor_preco`.
- O alerta de abertura e os realertas passam a ser enfileirados **na mesma transação** da oportunidade, e o id da mensagem vai para `mensagem_alerta_id`; o realerta soma 1 em `alertas`. Para isso, `avisos.servico.avisar` passa a devolver o id da mensagem enfileirada (ou None quando o aviso está desligado). A espera pela conferência de checkout continua como está.

### Encerramento (`oportunidades/encerramento.py`, novo)

Ponto único para fechar, chamado pelo monitor, pela busca (`sem_leitura`, linha a linha no lugar do `UPDATE` em massa) e por `repositorio_casamento.fechar_oportunidades` (`casamento_desfeito`). Na transação de quem chama:

1. grava `fechada_em`, `motivo_encerramento` e `deixou_de_valer_em` (`em_risco_desde` ou agora), limpa o risco;
2. olha `mensagem_alerta_id`:
   - mensagem **enviada**, ou `alerta_sem_registro` verdadeiro: enfileira o aviso do motivo e grava `encerramento_avisado_em`;
   - mensagem **pendente** na fila: descarta-a (`repositorio_mensagens.descartar`) e não avisa o encerramento;
   - **expirada**, **descartada** ou sem mensagem (aviso de oportunidade desligado, ou mensagem já apagada pela limpeza): não avisa.
3. O aviso roda em savepoint (como todo aviso): uma falha nele vai para o log e não desfaz o encerramento.

### Avisos (`avisos/catalogo.py`)

Três tipos de evento (não agrupam, sem lembrete), cada um com exemplo e liga/desliga em Configurações → Avisos:

- `OPORTUNIDADE_ENCERRADA` (grupo de oportunidades, severidade nova `ENCERRADA` ⏹️), título "Oferta encerrada · <motivo>" com "preço subiu", "oferta sumiu", "Liga baixou" ou "vendedor mudou";
- `OPORTUNIDADE_CORRIGIDA` (grupo de oportunidades, severidade nova `CORRECAO` ⚠️), título "Alerta corrigido";
- `OPORTUNIDADE_ENCERRADA_TECNICO` (grupo admin, severidade `ATENCAO` 🟡), título "Oportunidade encerrada · <motivo técnico>" com a ação "Confira Admin → Serviços".

Exemplos:

```
⏹️ *Oferta encerrada · preço subiu*
*Final Fantasy - Caixa de Booster de Jogo*
• Durou 3 h 20 min (desde 18/10 10:15)
• Alerta: R$ 1.299,90 → agora: R$ 1.549,90
• Liga: a partir de R$ 1.589,00
_18/10 13:35 · monitor Amazon_
```

```
⚠️ *Alerta corrigido*
*Final Fantasy - Caixa de Booster de Jogo*
• O alerta de 18/10 10:15 era de outro produto: desconsidere.
_18/10 13:35 · admin_
```

O "agora" é o preço que o motor julgou (o monitor o informa: o conferido, itens + impostos sem frete, quando há conferência válida); sem ele (busca, casamento), o preço atual do anúncio. Em "oferta sumiu" a linha de preço fica "Alerta: R$ X → agora: indisponível". A duração é `fechada_em − aberta_em`.

### Admin antigo

- Configurações → Amazon → Monitor de preço: campo "Carência para encerrar uma oportunidade (min)".
- Ofertas: oportunidade em risco mostra o selo "em risco desde HH:MM · <motivo>" (componente `badge` do DaisyUI).

## Erros

- Falha ao enfileirar o aviso de encerramento: log, encerramento mantido (savepoint).
- `mensagem_alerta_id` apontando para mensagem apagada pela limpeza: vira NULL pela FK; a oportunidade aberta nesta versão com mais de 30 dias sem alerta novo cai em "sem mensagem" e não avisa. Aceito (oportunidade aberta 30 dias é rara e o grupo já recebeu dezenas de lembretes de preço).
- Duas transações fechando a mesma oportunidade (monitor e desfazer o casamento ao mesmo tempo): o encerramento trava a linha (`FOR UPDATE`) e ignora a que já tem `fechada_em`.

## Testes

- Motor: `motivo_inelegivel` para cada motivo e a ordem com mais de um; `decidir` com risco, recuperação, encerramento ao vencer a carência, carência 0 e realerta em risco.
- Encerramento: matriz situação da mensagem (enviada, pendente, expirada, descartada, sem mensagem, `alerta_sem_registro`) × tipo de aviso por motivo; mensagem pendente descartada.
- Integração (Postgres de teste): leituras ruins e boas alternadas sem aviso; leituras ruins por 30 min encerram com motivo e um aviso só; desfazer o casamento gera "alerta corrigido"; 24 h sem leitura gera o técnico; `menor_preco` e `alertas` acompanham realertas; a migração preenche as existentes.
- Catálogo: exemplos dos três tipos novos (o teste da tela Avisos já percorre o catálogo).

## Fora do escopo

- Telas da área de negócio com as oportunidades ativas, encerradas, gráficos e acompanhamento: sub-projeto B, que usa estas colunas e o `preco_amazon`.
- Tendências de mercado da Liga: sub-projeto C.
