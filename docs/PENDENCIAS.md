# Pendências do tcg-sniper

Lista única do que falta. Atualizar aqui quando algo entrar, sair ou mudar de prioridade.
Marcar `[x]` ao concluir, anotar o commit e mover para "Concluídas". Sem dados pessoais neste arquivo (o repositório é público).

Última revisão: 2026-10-19 (casamento por par pronto no código, falta implantar; antes: auditoria conversa × lista e respostas do usuário do mesmo dia).

## 0. Crítico (em andamento)

- [ ] **Implantar o casamento por par** (com ok do usuário), seguindo o README → "Implantar o casamento por par": backup em `dados/backups/`, conferir antes que `SELECT count(*) FROM anuncio_amazon WHERE produto_id IS NULL` dá 0 e anotar as contagens por situação (`SELECT status_casamento, count(*) FROM anuncio_amazon WHERE produto_id IS NOT NULL GROUP BY 1`), `docker compose up -d --build` (todos os serviços) e comparar com `SELECT status, count(*) FROM casamento GROUP BY 1`: têm de bater com as contagens tiradas logo antes (não com números antigos; em 2026-10-19 eram 50 confirmados, 6 pendentes e 1269 ignorados).

## 1. Segurança antes da internet (prioridade alta)

Tratar como projeto de verdade, antes de abrir a API para a internet. Hoje são menos de 20 pessoas, mas o acesso vai ser vendido: limites e sessões precisam ser pensados para crescer.

- [ ] **Login sem bloqueio de quem é legítimo e resistente a ataque.** O limite geral de 20 pedidos de código por hora permite que qualquer um bloqueie o login de todos por 1 h. Trocar por limites **por IP e por número**, sem bloqueio global; considerar atraso progressivo por origem, aviso no grupo admin quando o padrão parecer ataque (muitos números, muitos IPs, muitas tentativas erradas) e manter a mesma resposta para número sem cadastro. Requisito: usuário legítimo nunca fica trancado fora (o acesso de emergência `tcg-sniper codigo-acesso` continua como último recurso, não como caminho normal).
- [ ] Login (`POST /api/auth/pedir-codigo` e `POST /api/auth/entrar`): a resposta é sempre igual, mas o tempo ainda difere um pouco entre número com e sem cadastro (no pedido, só o cadastrado gera código e enfileira a mensagem; no entrar, só o cadastrado busca o último código, confere o HMAC e grava a tentativa errada). Fazer o mesmo trabalho nos dois casos ou responder depois de um tempo fixo.
- [ ] Sessões encerradas ou vencidas nunca são apagadas (pedidos e códigos são, depois de 1 dia). Com a venda de acesso o volume cresce: limpar na manutenção diária.
- [ ] O texto do código de acesso fica legível na fila (`mensagem_saida`) enquanto está pendente (até 5 min; Admin → Mensagens já mostra "texto oculto"). Decidir se fica cifrado na fila.
- [ ] Cloudflare Access na frente do noVNC e da gestão quando publicar (ver "Publicar na internet", seção 4).

## 2. Pequenas (sem pressa, juntar num pacote)

- [ ] Login: celular digitado sem o 9 extra (10 dígitos) é normalizado diferente do cadastrado com 11 dígitos e não entra. **Decidido (2026-10-19):** aceitar a variante sem o 9 no login, normalizando para o número cadastrado.
- [ ] Login: `limpar_antigos` apaga linhas antes de pegar a trava consultiva; dois pedidos simultâneos podem raramente dar deadlock (500). Pegar a trava antes ou usar `SKIP LOCKED`.
- [ ] Usuários: `GET /api/usuarios` ainda mostra a contagem de sessões ativas de admins para quem não é superadmin.
- [ ] Front: ao fechar um modal, o foco não volta para o botão que o abriu.
- [ ] README: o passo de gerar `SEGREDO_API` usa Python no PC; dar alternativa com `docker compose run --rm api python -c ...`.
- [ ] Vigia de serviços: a batida de 60 s é uma thread à parte, então prova que o processo está vivo, não que o laço principal ou o navegador andam; um Playwright/Chromium travado não dispara `SERVICO_SEM_SINAL`. Se acontecer, mover a batida para dentro do laço de cada serviço.
- [ ] Vigia de serviços: container parado de propósito no compose recebe `SERVICO_SEM_SINAL` com lembrete a cada 2 h até ser pausado em Serviços. O vigia deveria ignorar serviço parado de propósito (hoje o jeito é pausá-lo no admin).
- [ ] Problema que bloqueia e só espera (CAPTCHA, Amazon pausada, sem login, IA pausada, carrinho) não recebe o lembrete de 2 h: o lembrete é decidido quando o evento se repete, e esses não se repetem enquanto esperam.
- [ ] Aviso "mensagem não enviada" nunca é resolvido, então o lembrete de 2 h mostra uma contagem que só cresce.
- [ ] Notificador, casos raros aceitos: (a) uma mensagem cujo registro sempre falha pode travar a fila; (b) se o banco cair entre gravar a oportunidade e gravar a mensagem, o alerta fica só no log.
- [ ] Casador: a espera de 1 h, 6 h e 24 h dos anúncios que sempre falham fica só em memória; cada reinício do container gera uma chamada paga a mais por anúncio. Vale também para a espera dos termos de busca cuja chamada falhou.
- [ ] Casamento por par: um anúncio confirmado para um produto que foi **desativado** continua confirmado nele (como antes): sai do monitor, mas não aparece como pendente para outros produtos e não pode ser confirmado em outro até você reativar o produto ou desfazer o par. Decidir se desativar um produto deve soltar os confirmados dele.
- [ ] Casamento por par: `marcar_reavaliado` pode tirar a marca de reavaliar com uma resposta da IA que já estava a caminho, mais antiga que o pedido de reavaliar (inofensivo: a avaliação gravada vale para os mesmos dados; para reavaliar de novo, é só clicar outra vez).
- [ ] Casamento por par: a guarda global contra as colunas antigas (`tests/test_sem_casamento_no_anuncio.py`) só pega os prefixos `anuncio.` e `AnuncioAmazon.`; uma variável com outro nome (`a.produto_id`, `item.status_casamento`) passaria. As colunas já saíram do banco, então o erro apareceria em execução.
- [ ] Teste para a frase "conferido, com impostos de R$ X" da oportunidade (hoje, se o texto quebrar, nenhum teste avisa).
- [ ] Teste de Ofertas com produto sem preço na Liga.
- [ ] `openai` fixada em `<3` no `pyproject.toml`: a 3.x troca a biblioteca de rede e exige refazer os testes do pacote `ia`.
- [ ] Limpar as 6 reexportações `# noqa: PLC0414` em `src/` (sobra da extração do pacote `navegador`).
- [ ] `TZ` fixo em America/Sao_Paulo no compose: mudar o fuso em Configurações → Geral não muda os logs nem o relógio do noVNC.
- [ ] Card da LigaMagic diz "Próxima começa em instantes" até a meia-noite quando a coleta do dia foi pulada (pausa no horário) (`consultas_painel.py`). Pode ir junto com a fase 3.
- [ ] Admin antigo lê a configuração duas vezes por página (sobra da configuração em tela). Pode ir junto com a fase 3.
- [ ] Seis itens menores da revisão final do coletor da Amazon (2026-10-14) ficaram "para depois" e não foram registrados. Dar como perdidos ou reabrir por uma revisão do código atual.

## 3. Acompanhar (sem código)

- [ ] Catálogo com 2165 produtos ativos (eram 224) — **intencional** (monitorar todos, decidido em 2026-10-19). Acompanhar a carga: coleta da Liga passa de ~1 h para ~10 h; a busca da Amazon (200/h na janela 08–22h) alcança cada produto sem par ~1 vez por dia; mais anúncios novos e a busca alternativa = mais gasto com a IA.
- [ ] Frequência de CAPTCHA da Amazon com o monitor no teto de produção de **1000 páginas/h**. Se os CAPTCHAs aumentarem, baixar para ~220 páginas/h (o suficiente para os anúncios confirmados a cada 15 min).
- [ ] Primeira semana do casamento por par: quantos ignorados foram recuperados (anúncios confirmados para um produto que antes estavam ignorados para outro: `SELECT count(*) FROM casamento c WHERE c.status = 'confirmado' AND EXISTS (SELECT 1 FROM casamento o WHERE o.anuncio_id = c.anuncio_id AND o.produto_id <> c.produto_id AND o.status = 'ignorado' AND o.origem <> 'outro_confirmado')`) e quantos produtos entraram na busca alternativa (`SELECT count(DISTINCT produto_id) FROM termo_busca`; com tentativa sem termo válido: `SELECT count(*) FROM fila_amazon WHERE termos_tentados_em IS NOT NULL`). Se a recuperação estiver lenta, plano B: a IA reavalia os ignorados contra os produtos de nome parecido (com o teto de gasto valendo).
- [ ] Fila e gasto da IA nos primeiros dias depois de implantar o casamento por par (volume aceito; o teto de gasto protege): pares pendentes esperando a IA (Dashboard → "esperando você" e Casamentos), gasto do dia e do mês em Logs → IA (filtro "termos de busca" para a busca alternativa, 5 produtos por ciclo) e se o teto do dia está sendo atingido cedo. Se a fila não baixar, ajustar o lote ou os tetos em Configurações → IA.
- [ ] Primeira semana do site novo (`localhost:8090`): login pelo código no WhatsApp, cadastro do grupo e de operadores, grade de acessos.
- [ ] Uma semana de coletas da LigaMagic sem desafio do Cloudflare. No fim, revisar o máximo de cliques em "Exibir mais" (Configurações → LigaMagic) com os números reais.
- [ ] Primeira semana do backup diário (card Backup no Dashboard; arquivos em `dados/backups/` e no R2). Conferir que o rodízio local para em 7 diários + 4 semanais. No R2, as regras de ciclo de vida foram criadas no painel (`diario/` 7 dias, `semanal/` 35 dias): conferir que os arquivos antigos somem.
- [ ] Testar uma restauração do backup (README, seção do backup) num banco descartável, para saber que o arquivo volta inteiro.
- [ ] Volume de avisos no grupo admin na primeira semana (~60–70/dia com a rodada do monitor); desligar em Configurações → Avisos o que virar ruído.
- [ ] Primeiro "Serviço sem sinal" real: conferir que não houve alarme falso durante coletas longas (a batida é uma thread de 60 s).

## 4. Próximas funcionalidades (decisão do grupo)

- [ ] **Site novo, fase 2 — área de negócio**: dashboard do grupo (oportunidades, funil, resultados), com as permissões ver_oportunidades e ver_resultados.
- [ ] **Site novo, fase 3 — área administrativa**: migrar as telas do admin antigo, já corrigindo os 52 achados da auditoria de layout de 2026-10-18 (`docs/auditorias/2026-10-18-admin-layout.md`: 7 quebrados — contraste do tema claro, tabela de Ofertas cortada, Logs › Checkout, Configurações › LigaMagic no celular, botões de Trocar no celular, erros 404/400 em JSON cru, rótulo do Dashboard no celular —, 22 inconsistências e 23 melhorias), e o Dashboard reorganizado para UX/negócio (oportunidade em destaque, funil, saúde compacta, "precisa de você") e as permissões revisar_casamentos, ver_catalogo, editar_catalogo, ver_servicos, pausar_servicos, ver_logs, ver_mensagens, reenviar_mensagens, ver_configuracoes, editar_configuracoes. Incluir os botões do casamento por par ("Rebuscar agora", "Reavaliar com a IA", "Gerar termos de busca"), que nascem no admin antigo e migram para o site novo: a regra já está em `repositorio_casamento`/`repositorio_termos` (e `priorizar_na_fila`), o admin só chama e mostra a mensagem.
- [ ] **Site novo, fase 4 — desligar o admin antigo.**
- [ ] **Publicar na internet** (depois de muitos testes em casa e da seção 1): front estático no Cloudflare Pages (ou Vercel), API pelo Cloudflare Tunnel, Cloudflare Access na frente do noVNC e da gestão. A Vercel não serve para a API Python com o banco em casa.
- [ ] **Vender acesso às oportunidades**: assinantes na área de negócio, no mesmo sistema (sem multi-cliente). Assinatura, pagamento e planos ficam num projeto próprio; a base de permissões finas já veio na fase 1.
- [ ] **Margem líquida real** por oportunidade: comissão de lojista da LigaMagic, frete de envio, imposto, cupons e cartões. Alertar por um piso de margem configurável (ex.: 15%) no lugar ou ao lado do desconto mínimo, com uma tabela editável de regras (Prime e frete grátis, cashback por cartão, cupons com validade). Precisa dos valores/regras do grupo.
- [ ] **Coletor do Mercado Livre** pelo navegador (sem API).
- [ ] **Limite de exposição por produto** (quanto o grupo aceita comprar de cada item). Pré-requisito: registrar compras e estoque (hoje não existe). Faz sentido depois da margem.
- [ ] **Outros sites** de compra, um por vez. Candidatos: Magalu, Shopee e lojas de TCG.
- [ ] **Migrar para servidor**, modelo híbrido: API, front, banco e serviços num VPS (mínimo 4 GB de RAM); **os dois coletores** (LigaMagic e Amazon) continuam em casa, ligados ao banco do VPS por rede privada (Tailscale ou WireGuard), por causa do IP e da conta da Amazon. Antes, testar a Liga e a Amazon alguns dias com o IP do VPS.
- [ ] Imagens no R2 da Cloudflare: só se for preciso mostrar fotos no admin ou guardar histórico de imagem (hoje a IA baixa direto da loja).
- [ ] Ideia, fora do escopo agora: pipeline de deploy separado por serviço (o monorepo permite).

## 5. Riscos conhecidos (decisão, não código)

- [ ] O PC é ponto único de falha (ver "Migrar para servidor"). Ninguém fica sabendo quando ele cai: o vigia e o notificador caem junto. Vale um aviso externo simples (batida de vida para um serviço de fora, que avisa se parar).
- [ ] O número do WhatsApp pode ser banido: usar chip secundário.
- [ ] Conta da Amazon dedicada ao coletor (com Prime): evita o "carrinho ocupado" que desliga a conferência e protege a conta pessoal numa futura migração para servidor (logar a conta pessoal de IP de datacenter é o risco mais sério).

## Decisões pendentes

- [ ] Alerta que **espera a conferência de checkout** antes de sair (decidido pelo assistente em 2026-10-18 e descrito no README): falta a confirmação do usuário.

## Decisões registradas

- **Idioma (2026-10-19):** inglês, português e japonês (e outros idiomas) são **produtos diferentes**; um anúncio em inglês não casa com o produto em português da Liga.
- 2026-10-19: os 2165 produtos ativos são intencionais (monitorar todos).
- 2026-10-19: teto do monitor da Amazon em produção é 1000 páginas/h; baixar para ~220 só se os CAPTCHAs aumentarem.
- 2026-10-19: busca alternativa entra depois de 7 dias sem candidato.
- 2026-10-19: celular sem o 9 extra é aceito no login (normalizado para o cadastrado).
- 2026-10-19: menos de 20 usuários por enquanto, mas o acesso vai ser vendido; limites e sessões pensados para crescer, sem multi-cliente.
- 2026-10-19: o front (React) fica a cargo do assistente.
- 2026-10-19: os nomes fictícios usados nos testes ficam como estão.
- 2026-10-19: o histórico do GitHub fica como está (sem reescrever commits nem pedir limpeza ao suporte).
- 2026-10-19: regras de ciclo de vida do R2 criadas no painel.
- 2026-10-17: desconto mínimo de produção em 20% (Configurações → Amazon; o padrão de fábrica é 25%).
- 2026-10-17: preço conferido = itens + impostos, sem frete (frete mostrado à parte); a oportunidade usa o preço Prime quando existir (o preço que a conta vê).
- 2026-10-15: Ofertas não lê uma vez por dia os anúncios casados sem desconto; só mostra o rótulo "vendedor não verificado" (por isso vendedor e variação ficam vazios nesses anúncios).
- Avisos e alertas só pelo WhatsApp. Hospedagem: tudo no PC até validar.

## Ordem sugerida

0. Seção 0: implantar o casamento por par (código pronto) e acompanhar a primeira semana (seção 3).
1. Site novo, fase 2 (área de negócio).
2. Site novo, fase 3 (área administrativa + auditoria de layout + botões do par), depois fase 4.
3. Seção 1 (segurança do login), antes de publicar na internet.
4. Seção 2 (pequenas), junto com a próxima mexida no código de cada área.
5. Seção 3 (acompanhar) ao longo dos próximos dias, sem prazo.
6. Margem líquida (seção 4), quando o grupo tiver os valores.

## Concluídas

### Casamento por par e busca alternativa (2026-10-19; hashes a preencher no merge)

Spec `docs/superpowers/specs/2026-10-19-casamento-por-par-design.md`, plano `docs/superpowers/plans/2026-10-19-casamento-por-par.md`. Resolve o anúncio da Amazon preso ao primeiro produto da Liga para o qual foi sugerido (ignorado para o produto errado nunca voltava para o certo).

- [x] Tabela `casamento` (anúncio × produto) como fonte única: ignorado vale só para o par; confirmado para no máximo um produto (índice único parcial, trava do anúncio); confirmar ignora os outros pendentes do anúncio (`outro_confirmado`) e desfazer/ignorar o confirmado os reabre. O automático nunca muda uma decisão sua (`manual` ou `sugerido_ia`).
- [x] Busca cria o par com o produto buscado; casador avalia pares; Desfazer e "Reavaliar com a IA" fazem a IA reavaliar mesmo com o anúncio igual.
- [x] Busca alternativa: 7 dias sem anúncio novo → a IA sugere 2–3 termos (uma vez, no teto de gasto), que entram no rodízio da fila; volta ao nome normal com anúncio novo. Chamada que falha espera 1 h, 6 h, 24 h; 3 falhas seguidas encerram a etapa com aviso.
- [x] Monitor, checkout, oportunidades, Logs, Dashboard, Ofertas e telas de Casamentos sobre os pares; botões Rebuscar agora, Reavaliar com a IA e Gerar termos de busca (com mensagens honestas quando o produto não está na fila, a IA está desligada ou o casador pausado).
- [x] Migração `a9d4f2c6e8b1` com conferência (aborta com dois confirmados no mesmo anúncio) e downgrade; regressão: mesmas contagens antes e depois de migrar; colunas antigas do casamento removidas do anúncio e guarda global que impede ler o casamento pelo anúncio.

### Avaliação da IA (2026-10-19)

- [x] `ia avaliar --modelo gpt-5-mini` nos 266 pares decididos à mão: 260 acertos (98%), 3 falsos "sim" e 3 falsos "não", US$ 0,14. Na faixa em que o automático age (confiança ≥ 90): 217 de 218. O único erro ≥ 90 era um caso de idioma (caixa em inglês confirmada à mão para o produto em português); pela regra de idioma decidida (inglês, português e japonês são produtos diferentes) a IA estava certa e esse casamento foi desfeito. Automático segue ligado com 90/90. Os 24 ignorados pelo automático por idioma estão corretos.

### Site novo, fase 1 — base (merge `ccb2b98`, em produção desde 2026-10-19; superadmin criado e login pelo WhatsApp funcionando)

- [x] Serviço `api` (FastAPI, JSON, `127.0.0.1:8100`): erros padronizados, `/api/saude`, `/api/docs` com permissão, toda rota declara a permissão que exige (`exige(...)`), grade papel × permissão com cache de 5 s.
- [x] Login pelo WhatsApp: código de 6 dígitos só para o número da pessoa (validade própria de 5 min na fila; vencido não sai), 5 tentativas, limites de 3 por número/15 min e 20/hora (e 10 tentativas de entrar por número/15 min), mesma resposta para número sem cadastro; cookie `sessao` HttpOnly/SameSite=Strict; código, token e número só como HMAC-SHA256 com `SEGREDO_API` (a api não sobe sem ela); acesso de emergência `tcg-sniper codigo-acesso`.
- [x] Superadmin único (`tcg-sniper criar-superadmin` e `trocar-superadmin`, só no terminal): o único que mexe em admins; nunca rebaixado, desativado nem encerrado pelo site.
- [x] Avisos novos: `CODIGO_ACESSO` (individual), `SEGURANCA_USUARIO` e `SEGURANCA_LIMITE` (grupo admin), desligáveis na aba Avisos.
- [x] Site novo (`web/`, React + Vite + DaisyUI, Caddy em `127.0.0.1:8090`): Entrar, área de negócio (esqueleto), Gestão → Usuários e Gestão → Acessos, sem acesso e sistema indisponível; testes Vitest, ponta a ponta com Playwright e layout no `verificar_layout.py`.
- [x] Revisão final: limites do login atrás de `pg_advisory_xact_lock` (sem corrida na última vaga); `SEGURANCA_LIMITE` resolve (o do número quando ele entra, o total no próximo pedido aceito); entrar também limpa pedidos antigos e tem 429 com texto próprio; sessões de admins só o superadmin vê ou encerra; `PATCH /api/usuarios/{id}` e `trocar-superadmin` travam as linhas; CSP no Caddy (tema inicial em arquivo, sem script inline); `.dockerignore` do `web/`; nome do menu atualiza ao se renomear; Escape fecha os modais; README com a sequência segura de implantação.

### Avisos no WhatsApp (2026-10-18, merge `75733d2`)

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
