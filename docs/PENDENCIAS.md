# Pendências do tcg-sniper

Lista única do que falta. Atualizar aqui quando algo entrar, sair ou mudar de prioridade.
Marcar `[x]` ao concluir, anotar o commit e mover para "Concluídas". Sem dados pessoais neste arquivo (o repositório é público).

Última revisão: 2026-10-18.

## 0. Crítico (próximo a fazer)

- [ ] **Anúncio ignorado preso ao primeiro produto**: cada anúncio da Amazon fica ligado ao primeiro produto da Liga para o qual foi sugerido (`gravar_busca` nunca troca `produto_id`/status de um ASIN conhecido). Se foi ignorado para o produto errado (ex.: Colecionador sugerido para Jogo) e depois aparece na busca do produto certo, continua ignorado e nunca vira pendente para o produto certo; a IA só avalia pendentes. Perde oportunidades. Decidido (2026-10-18): **ignorado vale só para aquele par** — o mesmo anúncio achado na busca de outro produto vira pendente para esse outro produto e a IA avalia. Precisa de modelo de pares (anúncio × produto) ou equivalente. Relacionados, depois: busca alternativa (nome encurtado/sem edição) após muitos dias sem candidato; botões "rebuscar agora" e "reavaliar com a IA"; "Desfazer" não faz a IA reavaliar anúncio igual.

## 1. Acompanhar (sem código)

- [ ] Frequência de CAPTCHA da Amazon com o monitor ligado (até 150 páginas/h).
- [ ] Uma semana de coletas da LigaMagic sem desafio do Cloudflare.
- [ ] Primeira semana do backup diário (card Backup no Dashboard; arquivos em `dados/backups/` e no R2). Conferir que o rodízio para em 7 diários + 4 semanais.
- [ ] Testar uma restauração do backup (README, seção do backup) num banco descartável, para saber que o arquivo volta inteiro.
- [ ] Volume de avisos no grupo admin na primeira semana (~60–70/dia com a rodada do monitor); desligar em Configurações → Avisos o que virar ruído.
- [ ] Primeiro "Serviço sem sinal" real: conferir que não houve alarme falso durante coletas longas (a batida é uma thread de 60 s).

## 2. Pequenas (sem pressa, juntar num pacote)

- [ ] Vigia de serviços: a batida de 60 s é uma thread à parte, então prova que o processo está vivo, não que o laço principal ou o navegador andam; um Playwright/Chromium travado não dispara `SERVICO_SEM_SINAL`. Se acontecer, mover a batida para dentro do laço de cada serviço.

## 3. Próximas funcionalidades (decisão do grupo)

- [ ] **Margem líquida real** por oportunidade: comissão de lojista da LigaMagic, frete de envio, imposto, cupons e cartões. Precisa dos valores/regras do grupo.
- [ ] **Coletor do Mercado Livre** pelo navegador (sem API).
- [ ] **Limite de exposição por produto** (quanto o grupo aceita comprar de cada item).
- [ ] **Outros sites** de compra.
- [ ] **Migrar para servidor** (a LigaMagic continua sendo coletada em casa).
- [ ] Imagens no R2 da Cloudflare: só se for preciso mostrar fotos no admin ou guardar histórico de imagem (hoje a IA baixa direto da loja).

## 4. Riscos conhecidos (decisão, não código)

- [ ] O PC é ponto único de falha (ver "Migrar para servidor").
- [ ] O número do WhatsApp pode ser banido: usar chip secundário.

## Ordem sugerida

0. Seção 0 (anúncio ignorado preso ao primeiro produto).
1. Seção 1 (acompanhar) nos próximos dias.
2. Margem líquida (seção 3), quando o grupo tiver os valores.

## Concluídas

### Avisos no WhatsApp (2026-10-18)

- [x] Formato único (emoji, título em negrito, "•", "O que fazer", rodapé com hora e origem), sem endereço do sistema nas mensagens (só links de produto da Amazon e da LigaMagic), com escape e corte em 1500 caracteres.
- [x] Catálogo de 28 tipos, cada um desligável em Configurações → Avisos com exemplo; repetição agrupada (lembrete a cada 2 h, "✅ resolvido"); tabelas `estado_aviso` e `config_aviso`.
- [x] Avisos novos: conclusão de cada tarefa (Liga, busca e rodada do monitor da Amazon, rodada da IA, backup), parciais, falhas seguidas da IA, mensagem não enviada, pausar/retomar no admin.
- [x] Vigia de serviços no `manutencao`: serviço ativo sem sinal há mais de 10 min abre "Serviço sem sinal"; batida de vida dos coletores e do casador em `sinal_servico`.
- [x] Testes globais: nenhum exemplo leva endereço do sistema; fora de `avisos/` nada grava mensagem direto; `host_publico` só no admin, na configuração e nos avisos. Saem `NotificadorFila`, `criar_notificador` e o Protocol `Notificador`.

### Bloco 2: pequenas da Amazon (2026-10-18)

- [x] Retirada do carrinho: o clique de excluir conta no teto por hora também quando falha depois de carregar a página; recusa da trava antes do clique não conta. Vale na conferência de checkout e na retirada da varredura (que antes não contava nem o clique bem-sucedido) (`cdf5cbd`).
- [x] `abrir_oportunidade`/`atualizar_oportunidade`: `conferido` obrigatório, sem padrão; todos os chamadores passam o valor (`3a9febc`).
- [x] Trava de cliques: o rótulo tem de COMEÇAR pela frase da ação ("Excluir", "Adicionar ao carrinho", "Proceed to checkout"/"Fechar pedido", como nas páginas reais), escrita só com letras latinas depois de NFKC + casefold ("Еxcluir" com "Е" cirílico é recusado); o título do produto depois dela pode estar em outro alfabeto (produtos japoneses). Recusa também controle bidirecional (U+202A a U+202E, U+2066 a U+2069) e palavra do rótulo ou do contexto que mistura letra latina com letra de outro alfabeto que sobrou depois de trocar os sósias conhecidos ("aɡora", o armênio, versalete); ideograma, kana e hangul não contam como mistura ("MTG遊戯王" passa). Sósias cirílicos/gregos e letras como "ı" viram ASCII antes da lista proibida. A varredura AST junta somas de texto ("cl" + "ick") e f-strings, pega JS com click/submit/requestSubmit/dispatchEvent em evaluate*/eval_on_selector*/wait_for_function/add_init_script/add_script_tag, JS de fora (path=/url=) ou que não é texto conhecido (valor interpolado em f-string é dado), CDP send("Input.dispatch..."), type()/fill() com Enter, dispatch_event/tap/check/set_checked/press/keyboard/submit() e getattr/methodcaller com nome de método que clica (`b82f263`, `d94e630` e a rodada de revisão).
- [x] Anonimizador: número curto em `proibidos` (até 6 dígitos) só troca solto: não dentro de preço ("R$ 1.742,90", "R$ 742"), ASIN ou outro número; com letra depois troca ("742A"). "final R$ 1299" não vira cartão; "final (crédito) 1234" e "terminado em Visa 1234" continuam sendo cartão. CNPJ (com pontuação ou depois de "CNPJ") e telefone fixo sem parênteses viram fictícios; o CNPJ público da Amazon no rodapé fica. Fixtures atuais passam sem regenerar (`865e5aa` e a rodada de revisão).

### Pacote B (2026-10-18)

- [x] **Backup automático do banco**: serviço `manutencao` (compose), todo dia às 04:00 no fuso de Configurações → Geral, com recuperação ao subir se o último ok tem mais de 24 h. `pg_dump -Fc` validado com `pg_restore --list`, rodízio de 7 diários + 4 semanais em `dados/backups/` (os `tcg-antes-*.dump` manuais nunca são tocados) e cópia no R2 (`diario/`, `semanal/`; o bucket expira sozinho). Card Backup no Dashboard, liga/desliga em Serviços, Logs → Manutenção; falha avisa o grupo admin uma vez (`ef4c008`, `e79560f`, `1011a75`, `7ab2ed4`; correções da revisão `abf5c3f`..`2ff5f7c`; merge `7a64bf3`). Primeiro backup em produção 2026-10-18 15:03: diário + semanal (≈607 KB) no PC e no R2.
- [x] **Limpeza de histórico** (`db/retencao.py`, na mesma execução diária, só depois de um backup local ok) (`c006baa`):
  - preços (`preco_amazon`, `resumo_preco`, `preco_listagem`, `preco_atual_*`), `avaliacao_ia` e `oportunidade`: nunca apagados;
  - `chamada_ia`: 90 dias; antes de apagar, `avaliacao_ia.chamada_id` vira NULL (a avaliação fica; nenhuma tela junta a chamada pela avaliação);
  - `conferencia_checkout`: 180 dias, só com `item_removido` (as que ainda podem ter item no carrinho ficam);
  - `coleta`: 180 dias, só as que nenhum preço referencia (`resumo_preco`, `preco_listagem`, `preco_atual_liga`): rodadas que falharam ou vieram vazias e os ciclos da Amazon. Nunca uma `rodando`;
  - `oferta_amazon` e `mensagem_saida` continuam com a limpeza de 30 dias de antes (coletor-amazon e notificador).
- [x] Bancos de teste no container `postgres-teste` (porta 5433, dados em memória); os testes recusam a porta 5432 (ou sem porta) e bancos fora de `tcg_test*` (`2727316`, `abf5c3f`). Bancos `tcg_test*` apagados do Postgres de produção.
- [x] Ofertas no celular: selo de vendedor com nome longo quebra linha em vez de estourar a largura (`fe822ad`).

### Pacote A (2026-10-18)

- [x] Teste do Dashboard dependia do horário (falhava depois das 22:00): relógio fixo em 12:00 (`b9308b1`).
- [x] Monitor: conferência que falhou com "a oferta não está mais no painel" não manda alerta com o preço anunciado velho; a próxima leitura decide (`599a6f2`).
- [x] Monitor: sem REALERTAR com preço anunciado (sem imposto) depois de alerta com preço conferido; nova coluna `oportunidade.alerta_conferido`, migração `c8f2d6a1e4b9` (`7402c3c`).
- [x] `/logs` e abas no `scripts/verificar_layout.py` (`65a134b`).
- [x] Logs: aba da Amazon reabrindo ao paginar a LigaMagic com filtro não acontece mais; teste fica de guarda (`1f61efd`).
- [x] Ofertas: filtro de desconto compara o valor exato; tela mostra arredondado para baixo (24,99%) (`dd1ca0a`).
- [x] htmx com SRI (`integrity` sha384 + `crossorigin`) (`07ec5a0`).
- [x] Checkout: clique recusado pela trava não conta no teto por hora; mensagem de carrinho ocupado com contagem certa (`0990367`).

### Antes

- [x] Painel da Amazon sem oferta em destaque: leitor pula o bloco sem aviso, não perdia oferta (`619b892`).
- [x] "Monitor rodou antes da janela": não é bug, janelas variam até 15 min de propósito.
- [x] Primeiro dia do monitor e da conferência de checkout (2026-10-18): 49 de 51 anúncios lidos, 1 conferência ok (imposto somado, item removido), 1 alerta com preço conferido, nada preso no carrinho.
- [x] Monitor de preço da Amazon com conferência de checkout, descoberta só para quem não tem par, origem do casamento (`32c80a4`, 2026-10-17).
- [x] Dashboard de visão geral, Serviços liga/desliga, tela de Logs (`9e0e07f`).
- [x] Automático da IA aplica avaliações antigas (`44aec0f`).
- [x] Casamento com IA (OpenAI), nome em inglês da LigaMagic, admin em DaisyUI.
