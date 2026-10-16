# Casamento de anúncios com IA

Data: 2026-10-16
Contexto: 758 anúncios da Amazon pendentes, 115 ignorados, 15 confirmados (15 de 224 produtos ativos). Casar à mão não acompanha o volume. O usuário tem acesso à API da OpenAI (GPT-5 ou mais novo).

## Objetivo

Uma IA julga se cada anúncio pendente da Amazon é o mesmo produto da LigaMagic que a busca sugeriu, com confiança e motivo. Começa só sugerindo; o automático (confirmar ou ignorar sozinho com confiança alta) vem pronto e desligado. Gasto controlado por tetos configuráveis.

Critério de sucesso: na avaliação contra os 130 casos já decididos, o relatório mostra o acerto por modelo e por faixa de confiança, e o usuário consegue escolher modelo e limites antes de ligar o automático; com o automático desligado nenhum status de casamento muda sozinho; nenhum teto de gasto é ultrapassado.

## Decisões de 2026-10-16

1. **Começo:** primeiro só sugerir, com avaliação nos 130 casos decididos; automático pronto mas desligado, com interruptor e limites em Configurações.
2. **Isolamento:** pacote `tcg_sniper/ia` como único lugar que chama a OpenAI, e serviço (container) próprio `casador` que só monta a pergunta e chama o pacote.
3. **Entrada:** texto e imagens dos dois lados.
4. **Imagens:** o `casador` baixa as duas imagens, reduz e envia em base64 dentro da chamada. Nada guardado; sem R2.
5. **Modelo:** configurável em tela; padrão `gpt-5`, esforço de raciocínio baixo, imagem com `detail: low`, resposta curta em JSON.
6. **Gasto:** teto em dólar por dia e por mês **e** limite de chamadas por dia.

## Fora do escopo

- Procurar outro produto da Liga para um anúncio que a IA julgou diferente (a IA só julga o par sugerido).
- Usar a IA em outras tarefas (o pacote fica pronto para isso, sem outros usos agora).
- Guardar ou mostrar as imagens no admin.
- Mudar a regra de oportunidades ou de mensagens.

## Pacote `tcg_sniper/ia`

Único módulo do projeto que importa `openai` (SDK oficial, nova dependência; e `Pillow` para imagens).

- **`cliente.py`** — `perguntar(s, finalidade, instrucoes, texto, imagens, formato) -> RespostaIA`:
  - chama a Responses API com structured outputs (o `formato` é um JSON Schema; a resposta tem de seguir o schema);
  - devolve os dados lidos, tokens de entrada e saída e o custo em dólar (tokens × preço por milhão da `config_ia`);
  - grava cada chamada (ok ou erro) em `chamada_ia`;
  - repete em 429 e 5xx com espera crescente (até 3 tentativas dentro da mesma chamada);
  - erros tipados: `SemOrcamento`, `ChaveInvalida` (401/403 e falta de crédito), `ErroIA` (demais falhas, inclusive resposta fora do formato).
  - Os testes usam um cliente falso injetado; a suíte nunca chama a OpenAI.
- **`orcamento.py`** — `pode_chamar(s, agora) -> bool` lê `chamada_ia` e a `config_ia`: soma do custo do dia e do mês e número de chamadas do dia, no fuso America/Sao_Paulo. Chamada só acontece se os três ficarem abaixo dos tetos. Gasto e contagem também alimentam as telas.
- **`imagens.py`** — `preparar(url) -> str | None`: baixa (timeout curto, tamanho máximo), reduz para no máximo 512 px no lado maior, JPEG, base64. Falha devolve `None` (a pergunta segue só com texto).
- A chave vem de `OPENAI_API_KEY` no `.env`. É segredo: nunca vai para o banco, logs ou telas. Sem chave, o pacote recusa com `ChaveInvalida`.

## Dados (uma migração)

- `ProdutoLiga.imagem_url` (Text, nulo) — o coletor da Liga lê `#featuredImage` na página do produto (URL `//…` vira `https://…`; não sobrescreve valor existente com nulo).
- `AnuncioAmazon.imagem_url` (Text, nulo) — o coletor da Amazon lê a imagem do resultado da busca e, quando visita a página do produto, a imagem principal.
- **`chamada_ia`**: id, `em`, `finalidade` ("casamento", "avaliacao"), `modelo`, `tokens_entrada`, `tokens_saida`, `custo_usd` (Numeric), `ok`, `erro` (Text, nulo). Índice em `em`.
- **`avaliacao_ia`**: id, `anuncio_id`, `produto_id`, `mesmo_produto` (bool), `confianca` (0–100), `motivo` (Text), `modelo`, `assinatura` (sha256 dos dados de entrada: título, variação, nome, nome_en, URLs das imagens), `sem_imagem` (bool, alguma imagem falhou), `avaliado_em`, `aplicada_em` (nulo; preenchido quando o automático decidiu), `chamada_id`. Única por (`anuncio_id`, `produto_id`); reavaliar substitui.
- **`config_ia`** (linha única, editada em tela): `ligado` (false), `modelo` ("gpt-5"), `esforco` ("low"), `preco_entrada_milhao_usd`, `preco_saida_milhao_usd`, `teto_dia_usd`, `teto_mes_usd`, `max_chamadas_dia`, `intervalo_min` (5), `lote` (20), `automatico` (false), `confianca_confirmar` (90), `confianca_ignorar` (90). Os preços começam com os valores do `gpt-5` na data do deploy; o usuário confere na página da OpenAI.
- **Estado do serviço:** `estado_coletor` ganha a linha 3 (`casador`) — a check `id IN (1, 2)` vira `id IN (1, 2, 3)` — com o mesmo uso de hoje (ativo, pausado e motivo, execução solicitada).

## Serviço `casador`

Comando `tcg-sniper casador`, container no molde do `notificador` (parada graciosa com SIGTERM, `stop_grace_period`).

- A cada `intervalo_min` (ou na hora, com "Rodar agora"), se `config_ia.ligado`, o estado está ativo e há chave:
  1. pega até `lote` anúncios **pendentes** com `produto_id`, sem avaliação para esse par ou com assinatura diferente; produtos ativos primeiro, depois `visto_ultimo_em` mais recente;
  2. para cada um: confere `pode_chamar`; prepara as imagens; chama `perguntar` com a finalidade "casamento"; grava a `avaliacao_ia` (uma transação por anúncio);
  3. se `automatico` e a confiança passa do limite (`mesmo_produto` com `confianca >= confianca_confirmar`, ou não-mesmo com `confianca >= confianca_ignorar`): no mesmo commit, só se o anúncio **ainda está pendente com o mesmo `produto_id`**, confirma (`confirmar_casamento`) ou ignora (`ignorar_anuncio`) e marca `aplicada_em`. Decisão humana nunca é sobrescrita.
- **Pergunta:** instruções fixas em português (mesmo produto = mesmo item lacrado: jogo, edição, tipo — booster, caixa, bundle, deck — idioma e quantidade; carta avulsa, acessório ou outra edição = diferente); dados da Liga (nome PT, nome EN, edição, tipo, idioma, menor preço "à partir de") e da Amazon (título, variação, preço); as duas imagens. Resposta: `{mesmo_produto: bool, confianca: int 0-100, motivo: str (até 200 caracteres, em português)}`.
- **Erros:**
  - `ErroIA`: o anúncio fica sem avaliação e volta no próximo ciclo; 3 falhas seguidas encerram o ciclo.
  - `ChaveInvalida`: pausa o casador com o motivo, aviso no Dashboard e uma mensagem no WhatsApp (tabela de saída).
  - `SemOrcamento`: encerra o ciclo; volta sozinho na virada do dia/mês. Aviso no Dashboard e uma mensagem no WhatsApp por estouro (não repete no mesmo dia/mês).
- O casamento confirmado pela IA segue o fluxo de oportunidades de hoje na próxima leitura de preço.

## Avaliação

Comando `tcg-sniper ia avaliar --modelo gpt-5 [--modelo outro] [--limite N]`:

- roda nos anúncios já decididos pelo usuário (confirmados e ignorados com `produto_id`), sem mudar status nem gravar `avaliacao_ia`; as chamadas entram em `chamada_ia` com a finalidade "avaliacao" e respeitam o orçamento;
- grava `dados/avaliacao-ia-<data>.md` com, por modelo: acerto; falsos "sim" (IA disse mesmo produto, usuário ignorou) e falsos "não"; acerto por faixa de confiança (90+, 75–89, 50–74, <50); custo total e médio; e a lista de cada erro com título, produto e motivo da IA (ignorado por outro motivo, como vendedor ruim, aparece aqui para o usuário conferir).

## Admin

- **Casamento do produto:** cada pendente com avaliação ganha um selo (macro em `_componentes.html`): verde "IA: mesmo produto N%" (sim com confiança ≥ `confianca_confirmar`), vermelho "IA: outro produto N%" (não com confiança ≥ `confianca_ignorar`), amarelo nos demais; motivo em texto pequeno abaixo; aviso "sem imagem" quando for o caso. Pendentes ordenados com o "sim" da IA primeiro (por confiança). Confirmados e ignorados pela IA (`aplicada_em`) com selo "pela IA" e o motivo; o Desfazer de hoje continua valendo.
- **Casamentos:** contagem "IA sugere" (pendentes com sim) por produto.
- **Serviços:** card do casador com selo de estado, motivo e os botões Pausar, Retomar e Rodar agora.
- **Configurações:** aba "IA" com os campos da `config_ia` e o resumo: gasto de hoje, do mês e chamadas de hoje; a chave não aparece (só "chave configurada: sim/não").
- **Dashboard:** stat de gasto da IA no mês; aviso quando o casador está pausado ou sem orçamento.
- Só componentes e temas do DaisyUI; classes literais; CSS regenerado com `scripts/gerar_css.py`.

## Implantação

- `.env.example` ganha `OPENAI_API_KEY=`; README com a seção da IA (o que faz, avaliação, tetos).
- `docker-compose.yml` ganha o serviço `casador` (`command: tcg-sniper casador`).
- Ordem de uso: deploy com IA desligada → coletas preenchem `imagem_url` → `tcg-sniper ia avaliar` → usuário escolhe modelo e limites → liga a IA (sugestões) → depois, se quiser, o automático.
- Backup com `pg_dump` antes do deploy (migração).

## Testes

- Cliente falso da OpenAI; nenhuma chamada real na suíte.
- Orçamento: exatamente no teto bloqueia; abaixo libera; virada de dia e de mês em America/Sao_Paulo; limite de chamadas.
- Custo calculado a partir de tokens e preços; chamada com erro também registrada.
- Assinatura: igual não chama de novo; mudança de título, variação, nome ou imagem reavalia.
- Automático desligado nunca muda status; ligado respeita os dois limites; anúncio decidido pelo usuário durante a chamada não é alterado; `produto_id` trocado não é alterado.
- Imagem que falha segue só com texto e marca `sem_imagem`.
- `ChaveInvalida` pausa o casador e enfileira uma mensagem; `SemOrcamento` avisa uma vez por período.
- Parsers: `#featuredImage` na fixture real da Liga; imagem na busca e na página do produto da Amazon.
- Avaliação: relatório com contagens certas sobre casos falsos; não altera status.
- Admin: selos e ordenação na tela do produto; aba IA salva e valida (números ≥ 0, confianças 0–100); chave nunca aparece no HTML; card do casador.
- `test_migracao_igual_aos_modelos` e `test_css_em_dia_com_os_templates` continuam passando.
