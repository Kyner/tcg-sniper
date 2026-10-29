# Pendências do tcg-sniper

Lista única do que falta. Atualizar aqui quando algo entrar, sair ou mudar de prioridade.
Marcar `[x]` ao concluir, anotar o commit e mover para "Concluídas". Sem dados pessoais neste arquivo (o repositório é público).

Última revisão: 2026-10-29 (pacote de bugs em produção desde 2026-10-29 20:51 (merge `6dee6d4`); fase 3C em produção desde 2026-10-29 11:35 (merge `f3f7c72`), conferência pelo usuário pendente; coletor da Liga no Google Chrome em produção desde 2026-10-29 11:23 (`7232f8b`); Liga com desafio na 1ª página em toda tentativa desde 27/10 16:54; 3A e 3B conferidas pelo usuário; pacote de pequenas em produção desde 2026-10-27 17:08, merge `9a765b6`; 3B em produção desde 2026-10-25 20:37 (merge `266cc9d`); segurança etapa 1 em produção desde 2026-10-24 22:10; próximas entregas: fase 4, segurança etapa 2).

## Ordem sugerida

0. **Liga com desafio do Cloudflare em toda tentativa** (seção 0): ver se o Google Chrome resolve.
1. Casamento e idioma (seção 3, "Coleta e casamento"): conferir os casamentos #322, #382 e #462 e o idioma de 4 anúncios.
2. Acompanhar a primeira semana do monitor por grupo (seção 3).
3. Conferir a 3C e o Voltar de Configurações em produção (roteiro da 3C em `docs/IMPLANTACOES.md`; o Voltar na seção 2, "Sobras do pacote de bugs"), depois a fase 4 (desligar o admin antigo, com a tabela de cobertura da seção 4) e a segurança etapa 2 (seção 1). Spec: `docs/superpowers/specs/2026-10-21-fase3-area-administrativa-design.md`.
4. Seção 1, etapa 2 (segurança): **obrigatória antes de publicar na internet ou vender acesso** (a etapa 1 está em produção desde 2026-10-24).
5. Sub-projeto C (Mercado), a partir de ~2026-11-03 (3 semanas de histórico da Liga).
6. Acompanhar ao longo dos dias (seção 3), sem prazo.
7. Seção 2, "Sobras do pacote de bugs" (3 itens pequenos).
8. Margem líquida (seção 4), quando o grupo tiver os valores.

## 0. Crítico

- [ ] **LigaMagic sem coletar desde 2026-10-26** (último job ok: produtos, 26/10 14:42): toda tentativa cai no desafio do Cloudflare já na 1ª página das listagens (27/10 16:54, 28/10 23:12, 29/10 08:46 e 11:09), mesmo depois de resolvido e retomado. Em 2026-10-29 11:23 o coletor passou para o Google Chrome estável (`7232f8b`) e retomado às 11:25, mas o 2º desafio do dia (11:09) já tinha encerrado o dia: a primeira tentativa no Chrome é a coleta de 2026-10-30, no horário normal. Se o desafio continuar, pensar em perfil novo (o atual veio do Chromium) ou em pausas maiores antes da 1ª página.

## 1. Segurança antes da internet (prioridade alta)

Tratar como projeto de verdade, antes de abrir a API para a internet. Hoje são 2 pessoas em beta (2026-10-23), mas o acesso vai ser vendido: limites e sessões precisam ser pensados para crescer.

A etapa 1 está em produção desde 2026-10-24 22:10 (detalhe em "Concluídas").

**Etapa 2, antes de publicar na internet** (decidido em 2026-10-23: hoje só este PC usa o sistema, com 2 pessoas em beta):

- [ ] Limite de login **por origem** (pedidos de código e tentativas de entrar por IP; requisito: usuário legítimo nunca fica trancado fora, com o acesso de emergência `tcg-sniper codigo-acesso` só como último recurso), lendo o IP real de `CF-Connecting-IP` só quando o pedido vem do túnel do Cloudflare, guardado só como HMAC; aviso de ataque por origem no grupo admin. Não serve antes: no Docker Desktop todo pedido local chega com o mesmo endereço, e o limite viraria um limite global disfarçado.
- [ ] Cloudflare Access na frente do que for exposto (ver "Publicar na internet", seção 4); admin antigo e noVNC **nunca** publicados.
- [ ] Autenticação de verdade no noVNC (senha longa na frente do websockify, ex.: Caddy com `basic_auth`, ou só pela VPN), mantendo `VNC_SENHA` (o VNC só usa os 8 primeiros caracteres) como segunda barreira.
- [ ] O texto do código de acesso fica legível na fila (`mensagem_saida`) enquanto está pendente (até 5 min; Admin → Mensagens já mostra "texto oculto"). Decidir se fica cifrado na fila.
- [ ] Login (`POST /api/auth/pedir-codigo` e `POST /api/auth/entrar`): a resposta é sempre igual, mas o tempo ainda difere um pouco entre número com e sem cadastro. Fazer o mesmo trabalho nos dois casos ou responder depois de um tempo fixo.
- [ ] Revisar os números dos limites por número com o volume real de assinantes.
- [ ] Avisos de limite de login com teto: sem o limite total, quem inventa muitos números faz sair um `SEGURANCA_LIMITE` por número no grupo admin, e o de número sem cadastro nunca fecha. Agrupar (um aviso "muitos números" por hora) e avisar por número só quando ele tem usuário ativo. Hoje não é alcançável (a API só escuta neste PC).
- [ ] `tests/test_compose_portas.py` só lê portas no formato curto (`"ip:porta:porta"`); uma porta no formato longo (`published:`) ou só `"8000"` passaria sem ser conferida.
- [ ] "Abrir" (Serviços) usa `host_publico`, e o noVNC só escuta em 127.0.0.1: com `host_publico` diferente de localhost/127.0.0.1 o link morre.

## 2. Pequenas

Faxina de 2026-10-29: das 58 linhas, 31 foram descartadas (código, teste fraco ou visual sem efeito no uso; ficam no histórico do git), 2 foram para a segurança etapa 2 e 3 para a fase 4. Regra daqui em diante: revisão só registra aqui bug que afeta uso ou dados; o resto é corrigido na hora ou descartado.

### Sobras do pacote de bugs (2026-10-29)

- [ ] Configurações → Voltar do navegador: conferir à mão no navegador depois do deploy (os testes usam `MemoryRouter`): Voltar com alteração pergunta; cancelar fica na tela com o rascunho; confirmar sai; link do menu confirmado sai com um Voltar só.
- [ ] Vigia, sinal antigo no boot: com o PC desligado mais de 10 min, se o vigia rodar antes da primeira batida do serviço, abre "sem sinal" e logo resolve (vale para todos os serviços). Medir a partir de `max(ultimo, desde)` quando `ultimo < desde`.
- [ ] Ids acima de 2³¹ ainda dão 500 em rotas com `produto_id` (casamentos, catálogo, `/produtos/{id}/historico`); `MAX_ID` mora em `rotas_usuarios` e é importado por outras rotas. Mover para um módulo comum e conferir as rotas com id.

### Mantidas (funcionalidade ou decisão)

- [ ] **Nomes das categorias da Liga:** `NOMES_CATEGORIAS` (`src/tcg_sniper/configuracoes/geral_liga.py`) está vazio; os chips de Configurações → LigaMagic mostram "categoria N". Preencher olhando a Liga.
- [ ] **Nomes dos grupos do WhatsApp:** Configurações mostra só o ID (`…@g.us`); o projeto não tem chamada da Evolution para listar grupos.
- [ ] Login: número cadastrado sem o 9 e digitado com o 9 (`+55DD9…` para um cadastro `+55DD8…`) não é reconhecido.
- [ ] Tooltip da curva de preço (área de negócio) sem o nome do anúncio e sem as cores do tema.
- [ ] `openai` fixada em `<3` no `pyproject.toml`: a 3.x troca a biblioteca de rede e exige refazer os testes do pacote `ia`. Só ao atualizar.
- [ ] `TZ` fixo em America/Sao_Paulo no compose: mudar o fuso em Configurações → Geral não muda os logs nem o relógio do noVNC. Documentar no README.

## 3. Acompanhar (sem código)

### Monitor por grupo e atualizações de segurança (em produção desde 2026-10-23 13:28)

- [ ] Primeira rodada de cópia de fotos com a Pillow 13 (Atividade, filtro "backup"): falha só nos itens fora de JPEG/PNG/WEBP/GIF.
- [ ] Primeira semana: conferir o ritmo da fila rápida (card em Serviços), quão velhas ficam as leituras do grupo lento e o tamanho da lista "esgotado na Liga" (Catálogo), vendo se algum desses produtos merece ação.
- [ ] Se a fila rápida crescer demais, ajustar `quase_oportunidade_min_pct` ou o intervalo da fila rápida.

### Antes de publicar na internet

- [ ] Trocar o `r2.dev` por domínio próprio (Custom Domains → `img.<domínio>`) antes de publicar na internet; o `r2.dev` é limitado e não serve para produção.

### Fim da oportunidade (desde 2026-10-20 21:50)

- [ ] Primeira semana: oportunidades que abrem e encerram várias vezes no mesmo dia mesmo com a carência de 30 min (ruído no grupo). Se acontecer, subir a carência em Configurações → Amazon → Monitor de preço.

### Coleta e casamento

- [ ] **Coletor da Liga no Google Chrome** (em produção desde 2026-10-29 11:23, `7232f8b`; Chrome 156 estável na imagem, a Amazon continua no Chromium): conferir no noVNC (porta 6080) que o Chrome abre com o perfil antigo e acompanhar se os desafios do Cloudflare mudam (seção 0). O Chrome só se atualiza ao refazer a imagem.
- [ ] **Casamentos possivelmente errados** (pendente com o usuário; conferir e desfazer na revisão se for o caso): #322 "Secret Lair x Final Fantasy: Grimoire – Rainbow Foil Edition (Japanese)" (japonês confirmado; pela regra é sempre produto diferente); #382 "Iron Man, Titan of Innovation – Rainbow Foil" (a IA diz que parece carta avulsa, não o Secret Lair completo); #462 "MTG Decks & More Compatible with Spider-Man…" (a IA diz que é acessório não oficial, não o Secret Lair lacrado).
- [ ] **Idioma de 4 anúncios confirmados** (pendente com o usuário; definir pela foto no botão "definir idioma" da revisão): #25 Final Fantasy Chocobo, #394 Secret Lair Storm e #5424 Foundations Starter Collection (a IA respondeu português pelo título, mas no #5424 diz que a embalagem está em inglês: não gravado para não bloquear os anúncios em inglês do produto); #102935 Dominária Unida (sem decisão). Os outros 30 foram gravados como inglês em 2026-10-28 pela IA (`definir-idioma --ia`).
- [ ] Catálogo com 2165 produtos ativos (eram 224) — **intencional** (monitorar todos, decidido em 2026-10-19). Acompanhar a carga: a etapa dos produtos da Liga lê ~450–500 páginas por dia (leitura por interesse; eram ~10 h com todos os ativos); a busca da Amazon (90/h na janela 08–22h) alcança cada produto sem par ~1 vez a cada 2 dias; mais anúncios novos e a busca alternativa = mais gasto com a IA.
- [ ] Acompanhar uma semana sem desafio com ~500 páginas/dia (leitura por interesse, desde a implantação): avisos "Liga · desafio do Cloudflare" e a linha "Produtos: … de … · casados, candidatos, novos, rodízio" do resumo diário. Se o desafio voltar, baixar o rodízio (por exemplo para 14 dias) ou subir as pausas em Configurações → LigaMagic. No fim, revisar também o máximo de cliques em "Exibir mais" com os números reais.
- [ ] CAPTCHA da Amazon com os dois navegadores no mesmo endereço: busca até 90/h e monitor limitado na prática pelas pausas (~211 páginas/h com 8–20 s; o teto configurado é 1.000). Se os CAPTCHAs aumentarem (avisos "Amazon (busca) · CAPTCHA" ou "Amazon (monitor) · CAPTCHA"), baixar os tetos em Configurações → Amazon.
- [ ] Quantos produtos ativos ainda não foram buscados (card Amazon (busca) no Dashboard; eram 1941 de 1969 sem candidato em 2026-10-19). Com 90 buscas/h e a janela de 14 h, a primeira passada nos ~2000 produtos leva cerca de 2 dias.
- [ ] Primeira semana do casamento por par: quantos ignorados foram recuperados (anúncios confirmados para um produto que antes estavam ignorados para outro: `SELECT count(*) FROM casamento c WHERE c.status = 'confirmado' AND EXISTS (SELECT 1 FROM casamento o WHERE o.anuncio_id = c.anuncio_id AND o.produto_id <> c.produto_id AND o.status = 'ignorado' AND o.origem <> 'outro_confirmado')`) e quantos produtos entraram na busca alternativa (`SELECT count(DISTINCT produto_id) FROM termo_busca`; com tentativa sem termo válido: `SELECT count(*) FROM fila_amazon WHERE termos_tentados_em IS NOT NULL`). Se a recuperação estiver lenta, plano B: a IA reavalia os ignorados contra os produtos de nome parecido (com o teto de gasto valendo).
- [ ] Resultado dos 19 pares em inglês reabertos em 2026-10-19 (`reabrir-ingles --aplicar`): quantos a IA confirmou e quantos voltaram a ignorado.
- [ ] Fila e gasto da IA nos primeiros dias depois de implantar o casamento por par (volume aceito; o teto de gasto protege): pares pendentes esperando a IA (Dashboard → "esperando você" e Casamentos), gasto do dia e do mês em Logs → IA (filtro "termos de busca" para a busca alternativa, 5 produtos por ciclo) e se o teto do dia está sendo atingido cedo. Se a fila não baixar, ajustar o lote ou os tetos em Configurações → IA.

### Operação

- [ ] Teste `test_janela_que_fecha_no_meio_da_volta_nao_avisa_a_rodada` (monitor da Amazon): reforçado em `af03916`, causa da falha única de 2026-10-22 não provada. Se falhar de novo, a mensagem agora mostra cada passo e os avisos: investigar a partir dela.
- [ ] Evolution API (WhatsApp): o Node dentro da imagem (24.11.1) tem a falha de Brotli do lançamento de 2026-10-21 (corrigida no Node 24.22.1) e a versão 2.3.7 expõe `/metrics` sem senha (CVE-2026-91997). Risco baixo (só escuta em 127.0.0.1); atualizar a imagem quando sair uma versão com o Node corrigido.
- [ ] Playwright: conferir na próxima versão se o Chromium empacotado traz todas as correções do Chrome estável (o 1.64.1 vem com um build anterior ao 156 estável).
- [ ] Atualizar o Python do PC de desenvolvimento (3.12.10; CVE-2026-12003 é escalada local no Windows). Não afeta os containers (3.12.15).
- [ ] Primeira semana do site novo (`localhost:8090`): login pelo código no WhatsApp, cadastro do grupo e de operadores, grade de acessos.
- [ ] Testar uma restauração do backup (README, seção do backup) num banco descartável, para saber que o arquivo volta inteiro.
- [ ] Primeiro "Serviço sem sinal" real: conferir que não houve alarme falso durante coletas longas (a batida agora vem do laço de cada serviço, em fatias de até 60 s).

## 4. Próximas funcionalidades (decisão do grupo)

- [ ] **Site novo, fase 2 — área de negócio**, em três sub-projetos (decidido em 2026-10-20: a informação estratégica é o produto; telas com gráficos e acompanhamento), na ordem A → B → C:
  - [x] **A. Fim da oportunidade** (merge `000fa6d`, em produção desde 2026-10-20 21:50): detalhe em "Concluídas".
  - [x] **B. Oportunidades** (merge `27e6364`, em produção desde 2026-10-21 08:44; detalhe em "Concluídas"): ativas e encerradas, linha do tempo e curva de preço (do `preco_amazon`), duração (`aberta_em` até `deixou_de_valer_em`), motivo do encerramento, recorrência por produto, quase oportunidades (casados com desconto entre 10% e o mínimo) e números do período; permissão `ver_oportunidades`. Os números de casamentos e IA por produto vêm de `consultas_catalogo.situacao_catalogo`.
  - [ ] **C. Mercado (LigaMagic)**: preço subindo ou caindo (7 e 30 dias), nº de lojas caindo (escassez), esgotou na Liga, preço fora da média de venda, lançamentos, volatilidade; talvez avisos de tendência. Permissão `ver_resultados` (ou `ver_mercado`). Começar com ~3 semanas de histórico (coleta desde 2026-10-13, ou seja, a partir de ~2026-11-03).
- [ ] **Site novo, fase 3 — área administrativa**, organizada por tarefa (spec de 2026-10-21: `docs/superpowers/specs/2026-10-21-fase3-area-administrativa-design.md`, a partir da auditoria de UX do mesmo dia), em três entregas:
  - [x] **3A. Casamentos e Catálogo** (merge `43fdd04`, em produção desde 2026-10-22 11:37; detalhe em "Concluídas").
  - [x] **3B. Serviços, Atividade e Dashboard** (merge `266cc9d`, em produção desde 2026-10-25 20:37; detalhe em "Concluídas").
  - [x] **3C. Configurações, Ofertas e Mensagens** (merge `f3f7c72`, em produção desde 2026-10-29 11:35; detalhe em "Concluídas"). Do que sobrou da auditoria de layout de 2026-10-18 (`docs/auditorias/2026-10-18-admin-layout.md`) e das pequenas do admin antigo, o que não entrou fica na seção 2.
- [ ] **Site novo, fase 4 — desligar o admin antigo:** apagar `admin/`, o serviço `admin` do compose e a porta 8000, depois do deploy e da conferência da 3C. Junto: mover `listar_categorias` e `detalhe_produto` de `admin/consultas.py`; somem com o admin antigo o card da Liga que diz "Próxima começa em instantes" com a coleta pulada e a leitura dupla da configuração. Cobertura do admin antigo (rota antiga → onde fica no site novo):

| Rota antiga | Onde fica |
|---|---|
| `GET /` (painel) | `GET /api/gestao/dashboard` + `/gestao` |
| `GET /servicos` | `GET /api/gestao/servicos` + `/gestao/servicos` |
| `POST /liga/pausar`, `/liga/retomar`, `/amazon/pausar`, `/amazon/retomar`, `/amazon/busca/pausar`, `/amazon/busca/retomar`, `/casador/pausar`, `/casador/retomar`, `/notificador/pausar`, `/notificador/retomar`, `/manutencao/pausar`, `/manutencao/retomar` | `POST /api/gestao/servicos/{id}/desligar` e `/ligar` |
| `POST /retomar` (Liga após desafio) | `POST /api/gestao/servicos/liga/retomar` (CAPTCHA da busca e do monitor também) |
| `POST /rodar-agora`, `/casador/rodar-agora` | `POST /api/gestao/servicos/{liga|casador}/rodar-agora` |
| `POST /amazon/monitor/ligar|desligar`, `/amazon/checkout/ligar|desligar`, `/amazon/checkout/retomar` | `POST /api/gestao/servicos/amazon_monitor/{monitor|checkout}/{ligar|desligar}`, `…/checkout/retomar` |
| `POST /amazon/carrinho/{id}/conferido` | `POST /api/gestao/servicos/carrinho/{id}/conferido` |
| `GET /logs` (6 abas) | `GET /api/gestao/atividade` + `/gestao/atividade` |
| `GET /mensagens` (filtros situação e destino), `POST /mensagens/{id}` (reenviar, descartar) | Atividade (o quê = mensagem, com `destino` e `situacao=pendente`) + `POST /api/gestao/mensagens/{id}/{reenviar|descartar}` |
| `GET /configuracoes`, `POST /configuracoes/{geral,liga,amazon,ia}` | `GET`/`PUT /api/gestao/configuracoes` + `/gestao/configuracoes` (e `POST /api/gestao/configuracoes/efeito` para a caixa "Efeito") |
| `POST /configuracoes/avisos` | `PATCH /api/gestao/avisos/{tipo}` (grupo "WhatsApp e avisos") |
| `GET /ofertas` | `GET /api/gestao/ofertas` + `/gestao/ofertas` |
| Restantes (`/catalogo*`, `/produto*`, `/casamentos*`) | 3A (feito) |

- [ ] **Publicar na internet** (depois de muitos testes em casa e da seção 1): front estático no Cloudflare Pages (ou Vercel), API pelo Cloudflare Tunnel, Cloudflare Access na frente do noVNC e da gestão. A Vercel não serve para a API Python com o banco em casa.
- [ ] **Vender acesso às oportunidades**: assinantes na área de negócio, no mesmo sistema (sem multi-cliente). Assinatura, pagamento e planos ficam num projeto próprio; a base de permissões finas já veio na fase 1. Depende da seção 1 e de publicar na internet.
- [ ] **Margem líquida real** por oportunidade: comissão de lojista da LigaMagic, frete de envio, imposto, cupons e cartões. Alertar por um piso de margem configurável (ex.: 15%) no lugar ou ao lado do desconto mínimo, com uma tabela editável de regras (Prime e frete grátis, cashback por cartão, cupons com validade). Precisa dos valores/regras do grupo.
- [ ] **Coletor do Mercado Livre** pelo navegador (sem API).
- [ ] **Limite de exposição por produto** (quanto o grupo aceita comprar de cada item). Pré-requisito: registrar compras e estoque (hoje não existe). Faz sentido depois da margem.
- [ ] **Outros sites** de compra, um por vez. Candidatos: Magalu, Shopee e lojas de TCG.
- [ ] **Migrar para servidor**, modelo híbrido: API, front, banco e serviços num VPS (mínimo 4 GB de RAM); **os dois coletores** (LigaMagic e Amazon) continuam em casa, ligados ao banco do VPS por rede privada (Tailscale ou WireGuard), por causa do IP e da conta da Amazon. Antes, testar a Liga e a Amazon alguns dias com o IP do VPS.
- [ ] Ideia, fora do escopo agora: pipeline de deploy separado por serviço (o monorepo permite).

## 5. Riscos conhecidos (decisão, não código)

- [ ] As imagens copiadas para o R2 são da LigaMagic e da Amazon (uso de imagem de terceiros): rever antes de vender acesso.
- [ ] O PC é ponto único de falha (ver "Migrar para servidor"). Ninguém fica sabendo quando ele cai: o vigia e o notificador caem junto. Vale um aviso externo simples (batida de vida para um serviço de fora, que avisa se parar).
- [ ] O número do WhatsApp pode ser banido: usar chip secundário.
- [ ] Conta da Amazon dedicada ao coletor (com Prime): evita o "carrinho ocupado" que desliga a conferência e protege a conta pessoal numa futura migração para servidor (logar a conta pessoal de IP de datacenter é o risco mais sério).

## Decisões pendentes

Nenhuma no momento.

## Decisões registradas

- 2026-10-29: coletor da LigaMagic passa a usar o Google Chrome estável (canal `chrome` do Playwright); os da Amazon ficam no Chromium empacotado.
- 2026-10-23: produção parada por segurança das ~11h às 13:28 para aplicar certifi, Playwright, Pillow e a imagem do build em Node 24.22.1 (PHP não é usado); os serviços de coleta só voltam quando o usuário liberar (retomados por ele em 2026-10-25). Admin antigo e noVNC passaram a escutar só neste PC na segurança etapa 1 (2026-10-24).
- 2026-10-22: monitor da Amazon por prioridade: fila rápida a cada 15 min com as oportunidades abertas e os anúncios a partir do "quase lá" (10%); esgotado na Liga lido 1 vez por semana e só listado no Catálogo para analisar (sem alerta no WhatsApp, só produtos ativos); o resto com a sobra. Tendência de mercado (lojas e preço subindo ou caindo) fica no sub-projeto C, não no Catálogo.
- 2026-10-22: fase 3 da área administrativa organizada por tarefa, em três entregas (3A Casamentos e Catálogo, 3B Serviços, Atividade e Dashboard, 3C Configurações, Ofertas e Mensagens); mobile first; status curto com detalhe no tooltip; revisão de casamentos um produto por vez (Liga à esquerda, Amazon à direita, C/I, sem abas). Os links "Abrir" de Serviços só para quem pode pausar serviços e só na rede de casa; ações de gestão (lote do catálogo, ligar/desligar serviço, salvar configurações) registradas com quem e quando.
- 2026-10-20: fase 2 do site novo dividida em A (fim da oportunidade), B (oportunidades) e C (mercado da Liga); a informação estratégica (tendências, histórico, gráficos) é o que se vende.
- 2026-10-20: fim da oportunidade com carência de 30 min (configurável, 0 a 240); motivos de mercado avisam o grupo de oportunidades ("Oferta encerrada"), motivos técnicos o grupo admin, casamento desfeito ou trocado avisa "Alerta corrigido" no grupo de oportunidades; o aviso de fim só sai se o alerta de abertura chegou ao grupo.
- 2026-10-20: README pronto para publicar o repositório e preparar a venda, licença MIT mantida; aviso de vulnerabilidade privado pelo GitHub ativado; assinatura descrita só como "em preparação".
- **Alerta espera a conferência de checkout (confirmado pelo usuário em 2026-10-19):** o primeiro alerta de uma oportunidade só sai depois da conferência no checkout (preço = itens + impostos, sem frete); se a conferência não puder rodar, vale o comportamento descrito no README.
- **Idioma (revista em 2026-10-19):** a edição em **português é a preferida** para o produto da Liga; um anúncio em **inglês também casa quando o produto não tem anúncio em português confirmado** (coleções antigas juntam português e inglês num produto só da Liga). Inglês já confirmado **continua confirmado** se um português for confirmado depois (sem desfazer automático; quem decide é o usuário). **Japonês e qualquer outro idioma são sempre produtos diferentes.** O automático só confirma inglês em produto sem português confirmado (nem confirmado de idioma não registrado); senão o par fica pendente para o usuário.
- 2026-10-19: LigaMagic lê por interesse (casados e candidatos todo dia, novos até 100/dia, demais em rodízio de 7 dias; listagens completas todo dia) e esfria 30 min após um desafio resolvido, com pausas em dobro no resto do dia; o 2º desafio no dia encerra o dia.
- 2026-10-19: os 2165 produtos ativos são intencionais (monitorar todos).
- 2026-10-19: busca e monitor da Amazon em serviços separados (busca sem login, 90 buscas/h; monitor logado, 180 páginas/h; a migração baixou o monitor de 1000 para 180).
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

## Concluídas

### Pacote de bugs (merge `6dee6d4`, em produção desde 2026-10-29 20:51; sem migração)

Plano `docs/superpowers/plans/2026-10-29-pacote-de-bugs.md`. Um agente por bug, cada um com revisão própria, e revisão final do pacote inteiro.

- [x] IA do idioma olha a embalagem e as cartas, não a língua do título (`427af31`, ajuste em `faa6b91`).
- [x] Notificador: mensagem que falha ao gravar é adiada e a fila segue; depois de 5 tentativas vira falha definitiva e avisa o grupo admin (`0ecfe8f`, `0ef1101`, `faa6b91`).
- [x] Casador: gravar falha, limpeza, pausa ou aviso de orçamento não derruba mais o ciclo se o banco cair (`0549ba4`, `edf251d`).
- [x] Notificador vigia a manutenção (backup) com o mesmo "sem sinal" de 10 min (`9d1cd1c`).
- [x] Atividade sem `ver_configuracoes`: só os nomes dos campos, sem valores, e a busca não acha pelo valor (`d4c1aa9`).
- [x] Lista de usuários sem a contagem de sessões de admins para quem não é superadmin (`3b5f2c8`).
- [x] Login: trava por número antes da limpeza, e a limpeza com trava global que não espera (sem deadlock) (`1bd3d23`, `b6e6175`).
- [x] Carrinho com id fora do limite dá 404 (`6e7e1ed`).
- [x] Configurações: Voltar do navegador avisa sobre alterações não salvas, sem perder o estado do roteador (`7aabc10`, `82cf594`, `faa6b91`).
- [x] Configurações: categoria inválida ou repetida mostra o motivo; botões maiores para toque (`b2f5560`).
- [x] Serviços: Liga, WhatsApp e Backup não ficam "iniciando…" por 10 min (`fef9ab9`, `e0f5f12`).
- [x] Dashboard: botão "Já conferi" do carrinho (com `pausar_servicos`) e log de link do painel sem destino novo (`02dae85`, `e68af1f`).
- [x] "Quase lá" com limite padrão de 200 na API ("Ver todas" mostra no máximo 200) (`277beec`).
- [x] Frase "conferido, com impostos de R$ X": já coberta por `test_conferido_com_impostos_frete_importado_prime_e_cupom` (sem código).
- [x] Testes instáveis: teste do monitor reforçado (janela fixa e mensagens de falha legíveis; causa não reproduzida em 30 rodadas, o código que falhou foi reescrito em 23/10) e `testTimeout` de 15 s no front (`af03916`).
- [x] Liga: reinício com o dia encerrado pelo 2º desafio não promete mais execução atrasada (`7a7b596`).

### Fase 3C — Configurações, Ofertas e Mensagens na gestão (merge `f3f7c72`, em produção desde 2026-10-29 11:35; sem migração)

Plano `docs/superpowers/plans/2026-10-28-fase3c-configuracoes-ofertas.md`. Decisões do plano: Efeito calculado na API, categorias da Liga por ID, grupos do WhatsApp por ID, avisos agrupados por origem (37 tipos), Mensagens como filtro da Atividade.

- [x] Base neutra: validação de configuração e consulta de ofertas fora do admin antigo (`b74f07b`).
- [x] Configurações, API e Efeito: grupos por objetivo, caixa "Efeito" (com barras do gasto da IA), salvar com versões e avisos do WhatsApp (`8a3629f`, `59d5997`, `83c9852`, `5d9000d`).
- [x] Configurações, tela: grupos que abrem e fecham, barra Descartar/Salvar, aviso ao sair com alteração, avisos com exemplo (`378d210`, `4951f9c`).
- [x] Ofertas na gestão (`c23110f`, `29bc823`).
- [x] Menu da gestão sem links para o admin antigo; Dashboard aponta para as telas novas (`df2ed87`).
- [x] Mensagens dentro da Atividade: filtro de destino e situação pendente; texto de mensagem individual continua oculto sob o filtro (`6169321`, `bfad526`).
- [x] Pequenas de tela da 3A/3B: Catálogo (selos, contagens, lote, lista velha), Revisão de casamentos (Enter, setas, destaque, celular, menu de idioma), lista de Casamentos (retry, erro, página fora), Serviços (corrida da recarga, rótulo da chave, mensagem), Atividade sem "US$ 0.000000", Dashboard ("Ver" sem `pausar_servicos`, links por permissão), foco do modal, classes do DaisyUI sempre literais com teste-guarda (`3aea766`, `3b67ba8`, `4a54026`, `4098a8f`, `0f89f61`, `853b111`, `494685f`, `2c37dd5`, `68f746b`).
- [x] Ponta a ponta (admin edita Oportunidades e vê a ação na Atividade; operador em leitura e nas telas da gestão; Ofertas filtra) e layout de Configurações e Ofertas a 390/1440 px nos dois temas (`673c50d`).
- [x] `destino_novo` leva o filtro de mensagens pendentes (`/mensagens?situacao=pendente`) à Atividade (`6169321`).
- [x] Teste de Ofertas com produto sem preço na Liga, `test_sem_preco_na_liga_aparece_sem_desconto` (`c23110f`).
- [x] Guarda "não importa admin" cobre também o pacote `api` (`b74f07b`).
- [x] Revisão final: ligar/desligar serviços e a marca de "sem login" não mudam mais a versão das Configurações (fim do falso "As configurações mudaram"); avisos "IA desligada" e "monitor não cabe" abrem a seção certa de Configurações.
- [x] Spec: "Pular" e "Próximo" viraram um botão só, "Próximo →" (eram o mesmo link).
- [x] Depois do deploy: Configurações → LigaMagic mostrava "Nenhuma categoria." (a API mandava `liga.categorias` como o texto do banco, `"10,11,12"`, e a tela espera a lista de IDs); a API passa a mandar a lista em `valor` e `padrao`.

### Conferido em produção (2026-10-26 a 2026-10-28)

- [x] 3A e 3B conferidas pelo usuário em 2026-10-26 ("está tudo certo"): gestão, Casamentos, Catálogo, Serviços, Atividade e Dashboard. Os problemas achados nessa conferência (botão Voltar e link da Amazon) foram corrigidos em `9314e27`, `ce2af1c`. O layout das telas novas foi conferido pelo ponta a ponta em 390 e 1440 px, temas claro e escuro.
- [x] Primeira coleta da Liga depois da retomada de 2026-10-25 (Chromium novo, Playwright 1.64.1): rodou sem desafio em 25/10 e 26/10. O 1º desafio veio em 2026-10-27 16:54, logo depois de religar a produção (seção 3, "Coleta e casamento").
- [x] Gasto da IA depois de retomar o casador: US$ 2,69 a 6,69 por dia de 24/10 a 27/10 (520 a 950 chamadas), longe dos US$ 21,36 de 2026-10-21.
- [x] Sem `SERVICO_SEM_SINAL` nem CAPTCHA da Amazon de 25/10 a 28/10.

### Pacote de pequenas (merge `9a765b6`, em produção desde 2026-10-27 17:08)

- [x] Deploy em 2026-10-27 17:08 (backup `dados/backups/tcg-antes-pacote-pequenas-2026-10-27.dump`, migração `a4c7e1b9d3f6`); `casamento definir-idioma --aplicar` gravou 21 anúncios em inglês e 1 em japonês (#322, possível casamento errado, a conferir), 34 ficaram sem decisão; `casamento soltar-inativos` não tinha nada a soltar.
- [x] Login com o celular digitado sem o 9 extra: `numero_de_login` (`api/acesso.py`) usa a variante cadastrada com o 9 antes do HMAC, dividindo os limites; fixo nunca vira celular; consulta feita sempre, sem mudar o tempo. Commits `916f165` e `bf147ba` (correção da revisão).
- [x] Espera do Casador gravada no banco: a espera de 1 h, 6 h e 24 h dos pares cuja chamada da IA falha (`casamento.ia_falhas/ia_espera_ate/ia_falha_assinatura`; dados mudados zeram) e dos termos de busca (`fila_amazon.termos_falhas/termos_espera_ate`) sobrevive a reinício do container, sem chamada paga a mais. Commit `488c92c`.
- [x] Idioma dos casamentos antigos e brecha do "indefinido": `anuncio_amazon.idioma` (definido à mão ou por comando) passa a valer antes do idioma da avaliação na regra "português confirmado" (`coalesce`); `tcg-sniper casamento definir-idioma [--aplicar]` preenche os confirmados sem idioma pelo título (sem chamada à IA) e lista o que o título não decide; botão "definir idioma" (português, inglês, japonês, outro) no cartão do confirmado na revisão de casamentos (`PATCH /api/gestao/casamentos/anuncios/{id}/idioma`); o automático trata "indefinido" como inglês (só confirma sem português confirmado). Depois do deploy: rodar `casamento definir-idioma` sem e depois com `--aplicar` (ver `docs/IMPLANTACOES.md`). Commits `ca59caa` e `74fa1d7` (correção da revisão).
- [x] Desativar um produto solta os anúncios confirmados: `soltar_confirmados_do_produto` (`db/repositorio_casamento.py`) volta cada confirmado a pendente (marcado para a IA reavaliar, avaliação antiga sem "aplicada"), reabre os `outro_confirmado` e encerra as oportunidades abertas do anúncio com o motivo novo `produto_desativado`, **sem aviso** (nem no grupo, nem no admin: a decisão foi sua; descarta só o alerta ainda na fila). Vale no PATCH e no lote da gestão (`acao_gestao` guarda `anuncios_soltos`) e na chave e no lote do admin antigo; os ids vêm do próprio UPDATE (`RETURNING`), tudo na mesma transação. Reativar não mexe: os pares ficam pendentes para a IA. O casador não confirma par de produto desativado durante a chamada da IA. `tcg-sniper casamento soltar-inativos [--aplicar]` solta os confirmados de produtos já inativos (passo do deploy em `docs/IMPLANTACOES.md`). O motivo conta como resultado e na recorrência de 30 dias. Commits `3691e4f` e `7f47094` (correção da revisão).
- [x] Lembretes e "mensagem não enviada": os bloqueios que só esperam (`TIPOS_QUE_ESPERAM`: CAPTCHA da busca e do monitor, sem login, carrinho, Amazon pausada (monitor e busca), IA pausada, desafio da Liga) recebem o lembrete de 2 h de `lembrar_abertos`, chamado a cada minuto pela manutenção; respeita o liga/desliga de Configurações → Avisos, usa o texto do catálogo (sem as linhas do evento original) e não mexe em `ocorrencias`. "Mensagem não enviada" fecha (com o "✅ resolvido") quando não sobra falha definitiva na última hora, sem contar o próprio aviso e o resolvido dele (conferido a cada ciclo do notificador), ou quando reenviar/descartar tira a última falha; uma mensagem que saiu não basta. Commit `9d3cef8`.
- [x] Vigia: serviço parado de propósito (SIGTERM, `docker stop`) grava `sinal_servico.encerrado_em` e sai da vigia até bater de novo (a batida apaga a marca; o notificador compara com o último ciclo); queda sem SIGTERM continua avisando. A batida deixou de ser thread: `Batimento.bater()` sai do laço de cada serviço (`Batimento.dormir()` bate antes e a cada fatia de até 60 s de qualquer espera, o que cobre tick do agendador, páginas da Liga, passos e esperas de erro de 15 min da Amazon; o Casador bate a cada passo e a cada par), então laço ou navegador travado dispara `SERVICO_SEM_SINAL`. Falha ao gravar a batida é logada. O notificador também bate uma vez na subida (apaga a marca do desligamento limpo anterior). Commits `d5f6124` e `61fd878` (correção da revisão).
- [x] Fim da oportunidade com realerta na fila: `oportunidade.alerta_enviado` (marcado pelo monitor quando a troca de mensagem substitui um alerta já ENVIADO; o notificador não precisa marcar) faz o encerramento avisar o grupo mesmo que o realerta atual seja descartado ainda na fila; sem nenhum alerta enviado segue sem aviso. Inclui o índice em `oportunidade.mensagem_alerta_id` (item da 3B, feito na Task 1, commit `b41b970`). Linhas abertas antes disso não têm `alerta_enviado` preenchido (sem backfill). Commits `e5fa1f3` e `33b7de6` (correção da revisão).
- [x] LigaMagic: (a) a espera de 30 min depois de um desafio conta só da retomada do desafio (`estado_coletor.retomado_desafio_em`, gravado por `repo.retomar` em qualquer saída de `pausado_desafio`; se a marca faltar, a espera cai para a hora da última mudança de estado); desligar e ligar comum não a reinicia, e ligar no meio da espera mantém o pedido de execução feito pelo Retomar (o texto do card e da mensagem deixou de prometer "volta sozinha"); (b) produto novo cuja página falha 3 vezes seguidas (`produto_liga.falhas_pagina`, rede ou parser; uma leitura boa zera) sai dos "novos do dia" e segue só no rodízio; (c) as pausas em dobro contam os desafios das últimas 24 h (`SituacaoDesafio.desafios_24h`), não do dia do calendário; "parada até amanhã" segue no dia do calendário; os textos do aviso, do painel e das configurações dizem "pausas em dobro por 24 h depois do desafio". Commits `442c51c` e `2cbdd1d` (correção da revisão).

### Fase 3B — Serviços, Atividade e Dashboard na gestão (merge `266cc9d`, em produção desde 2026-10-25 20:37)

Plano `docs/superpowers/plans/2026-10-25-fase3b-servicos-atividade-dashboard.md`; migração `d6a2f8c4b1e9` (só índices, entre eles o de `resumo_preco.coletado_em` que estava pendente para a lista do dia da Liga; backup antes do deploy em `dados/backups/tcg-antes-fase3b-2026-10-25.dump`). Commits `a372602`..`1e6a3c5` mais o ponta a ponta `e255b2e`.

- [x] Consultas de painel, logs, mensagens e menu movidas para o pacote neutro `tcg_sniper/consultas/`; ações de serviço neutras, compartilhadas pelo admin antigo e pela API (`4dd64d5`, `a372602`).
- [x] Estado único dos serviços, com "parando…", "parado de verdade" e "iniciando…" (`3e83bdd`); API `/api/gestao/servicos` (ligar, desligar, rodar agora, retomar, monitor e checkout da Amazon, carrinho conferido), com `acao_gestao` por ação (`5fe67ba`).
- [x] Linha do tempo única da Atividade (`7046809`, `d24ee0e`) e API `/api/gestao/atividade` com as ações de mensagens (reenviar, descartar), texto de mensagem escondido sem `ver_mensagens` na camada da consulta (`1d198b9`, `3b53f1e`).
- [x] API do Dashboard (`1da0220`, `2d6ca17`) e telas Serviços, Atividade e Dashboard com o menu novo (`5c72ef2`, `bf165c4`, `dc74b06`, `7e02a55`, `1e6a3c5`).
- [x] Depois do deploy, o menu seguia abrindo Serviços e Logs no admin antigo: o navegador reaproveitava o `index.html` velho (o Caddy não mandava `Cache-Control`). Agora a página sempre confere com o servidor (`no-cache`) e os arquivos com hash ficam em cache longo.
- [x] Ponta a ponta: Casador desligado e ligado, Atividade filtrada com a ação de gestão, Dashboard com os quatro blocos, operador sem chave nem "Abrir", layout em 390 e 1440 px nos dois temas (`e255b2e`).
- [x] Decisões: a Atividade não leva o cursor na URL (os filtros sim; "Carregar mais" acumula em memória) e usa uma lista de cartões em todas as larguras; "Precisa de você" lista só problemas reais (serviço desligado por configuração fica de fora).

- [x] Link da Amazon e Voltar (2026-10-26): o histórico e o produto da gestão mostram "Ver na Amazon" sempre que há anúncio casado (o mais barato com preço; sem preço, o de leitura mais recente, com "sem preço agora" e "+N anúncios"); encerradas, tabela do histórico e "Quase lá" levam ao anúncio; `BotaoVoltar` volta na página anterior do site ou vai ao padrão (`9314e27`, `ce2af1c`).

### Segurança, etapa 1 (merge `e56364e`, em produção desde 2026-10-24 22:10)

Spec `docs/superpowers/specs/2026-10-23-seguranca-etapa1-design.md`, plano `docs/superpowers/plans/2026-10-23-seguranca-etapa1.md`. Sem migração. Suíte no merge: 2193 testes passando.

- [x] Admin antigo (8000) e noVNC (6080–6082) escutam só neste PC por padrão (`${ADMIN_ESCUTA:-127.0.0.1}`, `${VNC_ESCUTA:-127.0.0.1}`); teste garante que nenhuma porta publicada fica aberta sem variável. No deploy, "IP ou nome deste PC na rede" trocado de IP da rede para `127.0.0.1`.
- [x] Login sem o limite total de 20 pedidos por hora (qualquer um trancava todos); ficam os limites por número; aviso antigo de "limite total" fecha no próximo pedido aceito.
- [x] Limpeza diária apaga sessões encerradas ou vencidas há mais de 30 dias (ativas nunca); total em Logs → Manutenção.

### Monitor da Amazon com prioridade por grupo (merge `f98b44d`, em produção desde 2026-10-23 13:28)

Spec `docs/superpowers/specs/2026-10-22-monitor-prioridade-design.md`, plano `docs/superpowers/plans/2026-10-22-monitor-prioridade.md`; migrações `c5e1a8d3f7b2` (`monitor_esgotado_dias`) e `e7b3d9f1a4c6` (`anuncio_amazon.monitor_lido_em`, preenchida com a última leitura das ofertas); backup em `dados/backups/tcg-antes-monitor-e-seguranca-2026-10-23.dump`. No deploy: 657 confirmados — 32 na fila rápida, 486 lentos, 135 esgotados na Liga, 4 nunca lidos; intervalo da fila rápida de volta a 15 min.

- [x] Grupos de leitura: nunca lidos primeiro; fila rápida (oportunidade aberta ou desconto ≥ piso do "quase lá") a cada `monitor_intervalo_min`; esgotado na Liga a cada `monitor_esgotado_dias` (7); lento com a sobra, nunca antes do intervalo. Grupo pelo preço atual; "lido" pela hora própria do monitor (a busca não embaralha mais a fila).
- [x] Volta do monitor só com a fila rápida; aviso "rodada do monitor" no máximo uma vez por hora (resumo das voltas).
- [x] Painel: card com "rápida · lenta · esgotado"; aviso de capacidade conta só a fila rápida e compara com o teto e com a capacidade pelas pausas; aviso de atraso só para a fila rápida.
- [x] Catálogo da gestão: filtro "Esgotado (com anúncio casado)" (só produtos ativos) com preço da Amazon, média de venda da Liga, diferença e desde quando sem vendedor; selo no produto.

### Atualizações de segurança (merge `39235f0`, em produção desde 2026-10-23 13:28)

- [x] certifi 2026.10.23 (≥ 2026.10.19, CAs comprometidas, GHSA-6q48-6c7w-9gw2, travado por `constraint-dependencies`), Playwright 1.64.1 (Chromium com o zero-day do V8 corrigido), Pillow 13.0.0 (imagens só JPEG/PNG/WEBP/GIF; `ValueError` tratado) e a imagem do build do site em Node 24.22.1. PHP não é usado. A produção ficou parada de propósito das ~11h às 13:28 de 2026-10-23.
- [x] Vitest 4.1.12 (2026-10-26): fecha os 2 alertas médios do Dependabot no `@vitest/mocker` (injeção de código pelo registro de mocks e desvio da lista permitida com barra invertida no Windows). Só afeta os testes do front; o build de produção não muda, sem deploy. `npm audit` sem vulnerabilidades.

### Logs › Monitor e Checkout com o produto certo (2026-10-22)

- [x] Todas as linhas de Logs › Monitor e Logs › Checkout mostravam o mesmo produto (só exibição; os casamentos estavam certos). `_produto_da_linha` (`admin/consultas.py`) aninhava duas subconsultas num terceiro SELECT e elas perdiam a ligação com a linha (o SQL saía com `FROM oportunidade, conferencia_checkout`). Corrigido com `correlate_except` nas duas; testes com dois anúncios de produtos diferentes nas duas abas.

### Fase 3A — Casamentos e Catálogo na gestão (merge `43fdd04`, em produção desde 2026-10-22 11:37)

Spec `docs/superpowers/specs/2026-10-21-fase3-area-administrativa-design.md`, plano `docs/superpowers/plans/2026-10-21-fase3a-casamentos-catalogo.md`; migração `a1c4e7b9d2f6`; backup antes do deploy em `dados/backups/tcg-antes-fase3a-2026-10-22.dump`. Suíte no merge: 2153 testes passando no back, 100 no front, ponta a ponta com 5.

- [x] 10 permissões novas da fase 3 (revisar_casamentos, ver_catalogo, editar_catalogo, ver_servicos, pausar_servicos, ver_logs, ver_mensagens, reenviar_mensagens, ver_configuracoes, editar_configuracoes), com os padrões do operador; toda tela da gestão exige `ver_area_gestao` e a própria.
- [x] Tabela `acao_gestao` (quem, quando, o quê), nunca apagada pela limpeza; registra a chave e o lote do Catálogo.
- [x] Consultas de casamento e de catálogo movidas para o pacote neutro `tcg_sniper/consultas/` (o admin antigo continua igual); ordem "com preço na Liga primeiro", pistas de variação e parecidos na Liga.
- [x] API `/api/gestao/casamentos` (lista, revisão, decisões C/I/desfazer/outro produto, link, rebuscar, reavaliar, termos), `/api/gestao/catalogo` (lista, lote que conta e depois aplica, 409 se a contagem mudou), `/api/gestao/produtos/{id}` e `/api/gestao/menu`.
- [x] Telas: menu lateral da gestão com o selo de Casamentos; lista de Casamentos com filtros na URL e "Revisar em sequência"; revisão de um produto (Liga fixa, três grupos sem abas, C/I no lugar, teclado, "é de outro produto"); Catálogo com chave por linha e lote com confirmação do número exato; página do produto.
- [x] Revisão final: resposta de C/I que chega depois de trocar de produto é descartada; seleção e lote do Catálogo nunca usam a lista antiga; limites de tamanho nas entradas da API; ponta a ponta com largura conferida em 390 e 1440 px, nos temas claro e escuro.
- [x] O bug de seleção do Catálogo achado pelo ponta a ponta (lista antiga logo depois de trocar o filtro) foi corrigido antes do merge.

### Retomada da coleta (2026-10-25, pelo usuário)

- [x] LigaMagic, Amazon (busca e monitor) e casador retomados em Serviços depois da parada de segurança de 2026-10-23; Amazon conferida logada no noVNC do monitor com o Chromium novo.
- [x] `main` publicada no GitHub (até `3038904`), sem segredos nos commits enviados.

### Conferido em produção (2026-10-21, pelo usuário)

- [x] Avisos de encerramento da oportunidade (sub-projeto A): funcionando no grupo de oportunidades.
- [x] Fotos copiadas para o bucket público do R2 (sub-projeto B): aparecem em Oportunidades e na página de produto.
- [x] Backup diário: funcionando (rodízio local e cópia no R2).
- [x] Volume de avisos no grupo admin: sem ruído, nada a desligar.

### Oportunidades na área de negócio (merge `27e6364`, em produção desde 2026-10-21 08:44)

Spec `docs/superpowers/specs/2026-10-20-oportunidades-area-negocio-design.md`, plano `docs/superpowers/plans/2026-10-20-oportunidades-area-negocio.md`; migração `f3b8d1c7a9e2`. Sub-projeto B da fase 2 do site novo.

- [x] Telas Oportunidades (`/`: números do período, ativas, quase lá, por dia, encerradas) e Produto (`/produtos/<id>`: curva de preço, faixas de oportunidade, recorrência), carregadas sob demanda.
- [x] API `/api/oportunidades/*` e `/api/produtos/{id}/historico`; permissão `ver_oportunidades` (grupo e operador sim, admin sempre).
- [x] Piso da quase oportunidade configurável (Configurações → Amazon, padrão 10%) e índice no `preco_amazon`.
- [x] Imagens de produto copiadas para um bucket público do R2 (lotes de 100 por hora, as das oportunidades primeiro); `consultas_catalogo` movido para `tcg_sniper/consultas/`.
- [x] Ponta a ponta (login do grupo, oportunidade ativa, abrir o produto) e layout das telas novas, inclusive a página de produto.
- [x] Revisão final: "Quase lá" com um item por produto (o anúncio mais perto do mínimo) e sem produto que já tem oportunidade aberta, também no selo do produto; link das encerradas leva o período (`?periodo=`) e a página do produto abre nele, para a oportunidade destacada estar na curva; sem spinner eterno nas encerradas quando a primeira carga falha; "nenhuma oportunidade em 30 dias" no lugar de "0ª"; "Histórico do produto" das ativas só com o produto ativo; cópia das imagens pula por 24 h (em memória) o item que não baixou ou não converteu, sem segurar a fila; imagem acima de 40 megapixels recusada antes de decodificar; aviso no log quando só uma das chaves `R2_IMAGENS_*` está preenchida.

### Fim da oportunidade (merge `000fa6d`, em produção desde 2026-10-20 21:50; 13 abertas marcadas "alerta sem registro")

Spec `docs/superpowers/specs/2026-10-20-fim-da-oportunidade-design.md`, plano `docs/superpowers/plans/2026-10-20-fim-da-oportunidade.md`; migração `e7c3a9d5b2f4`. Suíte no merge: 2047 testes passando.

- [x] Motivo de encerramento e carência (Configurações → Amazon → Monitor de preço, padrão 30 min, 0 a 240): a oportunidade só encerra depois de ficar fora das condições pela carência; oscilação mais curta não gera aviso.
- [x] Avisos: "⏹️ Oferta encerrada · <motivo>" e "⚠️ Alerta corrigido" no grupo de oportunidades; "🟡 Oportunidade encerrada · <motivo técnico>" no grupo admin. Num realerta, o alerta anterior ainda pendente é descartado (vale o preço mais novo).
- [x] Alerta ligado à mensagem: o encerramento só avisa se o alerta saiu de fato (expirado ou ainda na fila não gera aviso).
- [x] Selo "em risco desde HH:MM · <motivo>" em Ofertas.
- [x] Dados para o sub-projeto B na `oportunidade`: menor preço, número de alertas, mensagem do último alerta e `deixou_de_valer_em` (a primeira leitura ruim).

### Reabrir os ignorados por inglês (2026-10-19)

- [x] `reabrir-ingles --aplicar` reabriu 19 pares ignorados pelo automático por idioma inglês (o dry-run esperava perto de 24; o filtro por motivo é aproximado e ficou de fora o que não era sobre idioma); voltaram a pendente para a IA reavaliar com a regra condicional (português preferido; inglês casa se o produto não tiver português confirmado). Acompanhar o resultado na seção 3.

### README para publicação e comercialização (2026-10-20)

- [x] README com apresentação para quem chega (o que faz, para quem, estado, formas de usar: instalar sob a MIT ou, em preparação, assinar as oportunidades), diagrama com todos os serviços, roadmap atualizado e seção "Licença e avisos" (sem afiliação, marcas, termos dos sites, não é recomendação de compra). Licença continua MIT.
- [x] "Uso responsável" descreve o Chromium sem a marca de automação (correção do loop do Cloudflare) e os tetos padrão certos da Amazon (90 buscas/h, 150 páginas/h do monitor).
- [x] `SEGREDO_API` no passo 2 da instalação, com `openssl rand` ou o Python do container (sem Python no PC); passo 11 para instalação nova.
- [x] Passos de implantação de cada versão movidos para `docs/IMPLANTACOES.md`; `SECURITY.md` (aviso privado pelo GitHub) e `CONTRIBUTING.md` (regras do projeto) novos.

### LigaMagic: leitura por interesse e esfriar após desafio (2026-10-19, merge `64b3e69`)

Em produção desde 2026-10-20 08:30. Loop do desafio no noVNC: o Chromium se anunciava como automatizado (`navigator.webdriver = true`); corrigido sem `--enable-automation` e com `--disable-blink-features=AutomationControlled` (merge `6492c55`, vale também para os navegadores da Amazon).

Spec `docs/superpowers/specs/2026-10-19-liga-leitura-por-interesse-design.md`, plano `docs/superpowers/plans/2026-10-19-liga-leitura-por-interesse.md`. Resolve o desafio do Cloudflare provocado pela leitura de todos os 2165 produtos ativos (~10 h seguidas) e o Retomar que recomeçava a lista.

- [x] **Coletor da LigaMagic provocando o Cloudflare**: a etapa dos produtos lê só a lista do dia (casados, candidatos, novos até 100/dia, rodízio de 7 dias), sem reler o que já foi lido hoje; resumo com os grupos.
- [x] Esfriar após desafio (30 min contados da retomada, pausas em dobro no resto do dia; 2º desafio encerra o dia, inclusive "Rodar agora"), derivado do banco (sobrevive a reinício); aviso diz se é o 1º ou o 2º do dia.
- [x] Configurações → LigaMagic com "Produtos novos por dia" e "Esfriar após desafio (min)" (migração `d4b8e2f6a3c1`); cards da LigaMagic em Serviços e no Dashboard com "Esfriando até HH:MM" / "Parada até amanhã (2º desafio)".

### Busca da Amazon separada do monitor (merge `ee69f72`, em produção desde 2026-10-19 18:49)

Spec `docs/superpowers/specs/2026-10-19-amazon-busca-separada-design.md`, plano `docs/superpowers/plans/2026-10-19-amazon-busca-separada.md`. Resolve a busca parada pelo monitor (um navegador só, prioridade estrita; 1941 de 1969 produtos sem candidato nunca buscados).

- [x] Dois serviços: `coletor-amazon-busca` (navegador sem login, perfil `perfil-amazon-busca`, noVNC 6082) e `coletor-amazon` (retirada, checkout e monitor, navegador logado, noVNC 6081), sobre uma base comum; teste de importação garante que a busca não alcança checkout/carrinho/monitor (`feca3fd`, `a3683e0`, `e45702e`, `3f4bfc8`; serviço e compose `1078c8e`).
- [x] Estado `amazon_busca`, tetos 90/180 com `least` na migração, ciclo rodando fechado como interrompido (`edd1fcc`).
- [x] Avisos com a origem no título e resolvido próprio (`ecd382b`); rodada do monitor uma vez por volta inteira (`e45702e`, `3f4bfc8`).
- [x] Serviços, Dashboard (buscas na última hora, produtos nunca buscados), Configurações e vigia com os dois serviços (`5e27293`, `108f0f8`, `886dc76`, `ed2da3c`).

### Dashboard e Casamentos por produto (merge `1a834b5`, em produção desde 2026-10-19 15:37)

- [x] Casamentos e IA contados por produto ativo da LigaMagic, não por par nem por chamada: cada produto cai em uma situação só (casado, esperando sua decisão, só ignorados, sem candidato; somam o catálogo ativo), com % e barra no Dashboard e link para Casamentos filtrado. Linha com produtos com mais de uma sugestão e anúncios aguardando em quantos produtos. IA: produtos avaliados, avaliados hoje (fuso configurado), esperando a IA, avaliações e média por produto; gasto do mês igual.
- [x] Casamentos: filtro "situação do produto" (`situacao_produto`) e coluna Sugestões (pares do produto). Atividade de hoje e aviso de rodada da IA dizem em quantos produtos ("12 anúncios em 5 produtos").

### Casamento por par e busca alternativa (merge `cb16fbb`, em produção desde 2026-10-19 11:51; contagens antes = depois: 51 confirmados, 1269 ignorados, 5 pendentes, 1325 pares)

Spec `docs/superpowers/specs/2026-10-19-casamento-por-par-design.md`, plano `docs/superpowers/plans/2026-10-19-casamento-por-par.md`. Resolve o anúncio da Amazon preso ao primeiro produto da Liga para o qual foi sugerido (ignorado para o produto errado nunca voltava para o certo).

- [x] Tabela `casamento` (anúncio × produto) como fonte única: ignorado vale só para o par; confirmado para no máximo um produto (índice único parcial, trava do anúncio); confirmar ignora os outros pendentes do anúncio (`outro_confirmado`) e desfazer/ignorar o confirmado os reabre. O automático nunca muda uma decisão sua (`manual` ou `sugerido_ia`).
- [x] Busca cria o par com o produto buscado; casador avalia pares; Desfazer e "Reavaliar com a IA" fazem a IA reavaliar mesmo com o anúncio igual.
- [x] Busca alternativa: 7 dias sem anúncio novo → a IA sugere 2–3 termos (uma vez, no teto de gasto), que entram no rodízio da fila; volta ao nome normal com anúncio novo. Chamada que falha espera 1 h, 6 h, 24 h; 3 falhas seguidas encerram a etapa com aviso.
- [x] Monitor, checkout, oportunidades, Logs, Dashboard, Ofertas e telas de Casamentos sobre os pares; botões Rebuscar agora, Reavaliar com a IA e Gerar termos de busca (com mensagens honestas quando o produto não está na fila, a IA está desligada ou o casador pausado).
- [x] Migração `a9d4f2c6e8b1` com conferência (aborta com dois confirmados no mesmo anúncio) e downgrade; regressão: mesmas contagens antes e depois de migrar; colunas antigas do casamento removidas do anúncio e guarda global que impede ler o casamento pelo anúncio.

### Avaliação da IA (2026-10-19)

- [x] `ia avaliar --modelo gpt-5-mini` nos 266 pares decididos à mão: 260 acertos (98%), 3 falsos "sim" e 3 falsos "não", US$ 0,14. Na faixa em que o automático age (confiança ≥ 90): 217 de 218. O único erro ≥ 90 era um caso de idioma (caixa em inglês do Senhor dos Anéis confirmada à mão para o produto em português); o usuário a reconfirmou em 2026-10-19 10:24 e, pela regra de idioma revista (português preferido, inglês casa quando o produto não tem português confirmado), ela está certa e continua confirmada. Automático segue ligado com 90/90. Os 24 ignorados pelo automático por idioma voltam para a IA com `tcg-sniper casamento reabrir-ingles --aplicar` depois do deploy.

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
