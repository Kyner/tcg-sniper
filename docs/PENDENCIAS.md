# Pendências do tcg-sniper

Lista única do que falta. Atualizar aqui quando algo entrar, sair ou mudar de prioridade.
Marcar `[x]` ao concluir, anotar o commit e mover para "Concluídas". Sem dados pessoais neste arquivo (o repositório é público).

Última revisão: 2026-10-22 (fase 3, entrega 3A em produção desde 11:37; próxima: 3B).

## Ordem sugerida

1. Seção 0: a decisão sobre o atraso do monitor da Amazon.
2. Conferir a 3A em produção (seção 3, "Fase 3A").
3. Site novo, fase 3, entrega 3B (Serviços, Atividade e Dashboard), depois 3C (Configurações, Ofertas e Mensagens) e a fase 4 (desligar o admin antigo). Spec: `docs/superpowers/specs/2026-10-21-fase3-area-administrativa-design.md`.
4. Seção 1 (segurança do login), **obrigatória antes de publicar na internet ou vender acesso**.
5. Sub-projeto C (Mercado), a partir de ~2026-11-03 (3 semanas de histórico da Liga).
6. Acompanhar ao longo dos dias (seção 3), sem prazo.
7. Seção 2 (pequenas), junto com a próxima mexida no código de cada área (as da gestão entram na 3B/3C).
8. Margem líquida (seção 4), quando o grupo tiver os valores.

## 0. Crítico

Nenhum no momento.

### Para resolver logo (achados da auditoria de UX de 2026-10-21)

- [ ] **Atualizações de segurança de 2026-10-23** (pesquisa de alertas recentes de Node, Python e PHP; PHP não é usado): certifi ≥ 2026.10.19 (CAs comprometidas, GHSA-6q48-6c7w-9gw2), Playwright 1.64.1 (Chromium com o zero-day do V8 CVE-2026-87491 corrigido), Pillow 13.0.0 (estouro no decodificador JPEG e outros; imagens agora só JPEG/PNG/WEBP/GIF) e a imagem do build do site em Node 24.22.1. Prontas para o merge; o deploy vai junto com o monitor por grupo. A produção ficou parada de propósito em 2026-10-23 até este deploy.

- [ ] **Monitor da Amazon atrasado (473 anúncios com leitura vencida em 2026-10-21)**: 521 confirmados a cada 15 min pedem ~2.084 páginas/h; o teto é 1.000, mas com pausa de 8–20 s um navegador faz ~257 páginas/h (conta aproximada, não medida). Decidir: intervalo maior (ex.: 30–35 min), pausas menores (mais risco de CAPTCHA) ou ler com prioridade os anúncios perto do desconto.
- [ ] Gasto da IA em 2026-10-21: US$ 21,36 de US$ 30 no dia (4.047 chamadas), provavelmente a fila andando depois do religamento. Conferir se repete.

## 1. Segurança antes da internet (prioridade alta)

Tratar como projeto de verdade, antes de abrir a API para a internet. Hoje são menos de 20 pessoas, mas o acesso vai ser vendido: limites e sessões precisam ser pensados para crescer.

- [ ] **Login sem bloqueio de quem é legítimo e resistente a ataque.** O limite geral de 20 pedidos de código por hora permite que qualquer um bloqueie o login de todos por 1 h. Trocar por limites **por IP e por número**, sem bloqueio global; considerar atraso progressivo por origem, aviso no grupo admin quando o padrão parecer ataque (muitos números, muitos IPs, muitas tentativas erradas) e manter a mesma resposta para número sem cadastro. Requisito: usuário legítimo nunca fica trancado fora (o acesso de emergência `tcg-sniper codigo-acesso` continua como último recurso, não como caminho normal).
- [ ] Login (`POST /api/auth/pedir-codigo` e `POST /api/auth/entrar`): a resposta é sempre igual, mas o tempo ainda difere um pouco entre número com e sem cadastro (no pedido, só o cadastrado gera código e enfileira a mensagem; no entrar, só o cadastrado busca o último código, confere o HMAC e grava a tentativa errada). Fazer o mesmo trabalho nos dois casos ou responder depois de um tempo fixo.
- [ ] Sessões encerradas ou vencidas nunca são apagadas (pedidos e códigos são, depois de 1 dia). Com a venda de acesso o volume cresce: limpar na manutenção diária.
- [ ] O texto do código de acesso fica legível na fila (`mensagem_saida`) enquanto está pendente (até 5 min; Admin → Mensagens já mostra "texto oculto"). Decidir se fica cifrado na fila.
- [ ] Cloudflare Access na frente do noVNC e da gestão quando publicar (ver "Publicar na internet", seção 4).
- [ ] **Restringir o admin antigo (8000) e o noVNC (6080–6082) — plano (decidido em 2026-10-23: não mexer no que está rodando agora; o acesso fica só nesta máquina por enquanto).** Hoje os quatro escutam em `0.0.0.0` (qualquer máquina da rede de casa alcança) e o noVNC do monitor é o navegador logado na Amazon; o VNC usa só os 8 primeiros caracteres de `VNC_SENHA`. Passos, cada um sem derrubar o que roda:
  1. Endereço de escuta configurável no `docker-compose.yml`: `"${ADMIN_ESCUTA:-0.0.0.0}:8000:8000"` e `"${VNC_ESCUTA:-0.0.0.0}:6080:6080"` (idem 6081/6082). O padrão continua o de hoje; ninguém perde acesso no deploy.
  2. Quando quiser fechar: `ADMIN_ESCUTA=127.0.0.1` e `VNC_ESCUTA=127.0.0.1` no `.env` e `docker compose up -d` (só recria os containers que mudaram). De outra máquina, o acesso passa a ser por túnel SSH ou pela VPN (Tailscale), não pela rede aberta.
  3. Senha do noVNC: trocar o `x11vnc -passwdfile` (8 caracteres) por autenticação na frente do websockify (ex.: o próprio Caddy com `basic_auth` e senha longa, ou só pela VPN). Manter `VNC_SENHA` como segunda barreira.
  4. Os links "Abrir" da gestão (3B) já são só para quem pode pausar serviços e só funcionam na rede de casa; com o passo 2 passam a funcionar só no próprio PC (o tooltip avisa).
  5. Antes de publicar na internet: Cloudflare Access (item acima) na frente do que for exposto; admin antigo e noVNC **nunca** publicados.

## 2. Pequenas (sem pressa, juntar num pacote)

### Testes

- [ ] Teste instável: `tests/coletor_amazon/test_varredura_monitor.py::test_janela_que_fecha_no_meio_da_volta_nao_avisa_a_rodada` falhou uma vez numa rodada completa e passa sozinho (suspeita de dependência do relógio ou da ordem). Investigar antes de confiar nele no CI.

- [ ] Ponta a ponta da gestão entra como superadmin; acrescentar um operador para exercitar as permissões das telas novas.
- [ ] Teste da migração `acao_gestao` não confere o `ON DELETE SET NULL` no schema; a lista de permissões do operador está fixa em `tests/api/test_auth.py` (derivar de `PADROES`).

### Gestão do site novo (adiadas da revisão da 3A, 2026-10-22; entram na 3B/3C)

- [ ] Catálogo: selo de situação sem tooltip; depois do lote não aparece quantos produtos mudaram; uma resposta antiga da lista pode desfazer na tela uma chave recém-trocada (só visual); a linha não mostra o nome em inglês, as lojas nem as contagens do casamento ("1 esperando você", "casado · 4 anúncios"), que a spec pede e a API já devolve; a chave registra a ação mesmo quando não muda nada.
- [ ] Revisão de casamentos: Enter com o foco no menu ⋯ avança para o próximo produto; ↑/↓ não rolam até o cartão escolhido; "desfazer" muda o cartão destacado sem avisar; no celular a foto grande e os parecidos ficam acima dos anúncios (a spec pede a Liga compacta); `RevisaoCasamento.tsx` tem ~400 linhas (dividir); "Pular" e "Próximo" levam ao mesmo produto.
- [ ] Lista de Casamentos: "Tentar de novo" sem cancelamento; depois de um erro, a lista antiga fica sob o alerta; página além da última sem link para a 1ª.
- [ ] Menu da gestão: o botão do menu no celular não recebe foco pelo teclado; `GET /api/gestao/menu` monta a lista inteira de casamentos a cada 60 s só para contar (trocar por uma contagem); Mensagens e Logs ainda são itens separados até a Atividade (3B).
- [ ] API da gestão: a navegação da revisão refaz a lista filtrada a cada pedido; `DecisaoSaida.mensagem` nunca é preenchida; os tipos `Literal` e a classe de filtros repetem à mão as listas de situação e de filtros; o lote conta e aplica sem trava (dois usuários ao mesmo tempo podem mudar 1–2 produtos a mais; fica registrado em `acao_gestao`).
- [ ] Código: lambdas com parâmetro `l` e nomes parecidos `ORDENS_CASAMENTO`/`_ORDENS_CASAMENTO` (`consultas/casamentos.py`); `parecidos_na_liga` corta sufixos de forma agressiva e ordena por nome, não por proximidade.

### Oportunidades e monitor da Amazon

- [ ] Oportunidade aberta há mais de 30 dias sem realerta perde o vínculo com a mensagem (limpeza apaga a mensagem) e não avisa o encerramento; aceito por ora (rara).
- [ ] Fim da oportunidade: se um realerta ainda está na fila quando a oportunidade encerra, o vínculo aponta para ele, que é descartado, e o aviso de encerramento não sai mesmo que o grupo tenha visto o alerta anterior (exige o WhatsApp fora por mais que a carência). Avaliar guardar se algum alerta da oportunidade saiu.
- [ ] Fim da oportunidade: `alertas` começa em 1 ao abrir mesmo com o aviso de oportunidade desligado (padrão do banco); o sub-projeto B deve contar pelas mensagens se precisar do número exato.
- [ ] `docs/IMPLANTACOES.md`, fim da oportunidade: "sem carência" onde o certo é "sem risco marcado" (só redação).
- [ ] Teste para a frase "conferido, com impostos de R$ X" da oportunidade (hoje, se o texto quebrar, nenhum teste avisa).
- [ ] Teste de Ofertas com produto sem preço na Liga.

### Casamento e idioma

- [ ] Idioma: produtos com casamento confirmado antes da regra de idioma (todos os ~50 de 2026-10-19) ficam como "não se sabe se tem português confirmado", então anúncios novos em inglês deles ficam pendentes para você em vez de o automático confirmar. Seguro para produtos em português; para quem tem a edição em inglês confirmada à mão, os irmãos em inglês nunca confirmam sozinhos. Corrigir com um preenchimento único do idioma dos anúncios confirmados (IA ou à mão, botão "definir idioma").
- [ ] Idioma: anúncio com idioma "indefinido" ainda pode ser confirmado pelo automático mesmo com português confirmado no produto (pequena brecha na regra "inglês só sem português").
- [ ] Casamento por par: um anúncio confirmado para um produto que foi **desativado** continua confirmado nele (como antes): sai do monitor, mas não aparece como pendente para outros produtos e não pode ser confirmado em outro até você reativar o produto ou desfazer o par. Decidir se desativar um produto deve soltar os confirmados dele.
- [ ] Casamento por par: `marcar_reavaliado` pode tirar a marca de reavaliar com uma resposta da IA que já estava a caminho, mais antiga que o pedido de reavaliar (inofensivo: a avaliação gravada vale para os mesmos dados; para reavaliar de novo, é só clicar outra vez).
- [ ] Casamento por par: a guarda global contra as colunas antigas (`tests/test_sem_casamento_no_anuncio.py`) só pega os prefixos `anuncio.` e `AnuncioAmazon.`; uma variável com outro nome (`a.produto_id`, `item.status_casamento`) passaria. As colunas já saíram do banco, então o erro apareceria em execução.
- [ ] Casador: a espera de 1 h, 6 h e 24 h dos anúncios que sempre falham fica só em memória; cada reinício do container gera uma chamada paga a mais por anúncio. Vale também para a espera dos termos de busca cuja chamada falhou.

### LigaMagic

- [ ] Produto novo cuja página sempre falha ocupa uma das vagas de novos do dia (o mais antigo primeiro); pular depois de N falhas.
- [ ] Desligar e religar pelo liga/desliga de Serviços reinicia a espera de 30 min após um desafio; o card diz "volta sozinha", mas nenhum job roda se o do dia já rodou. Nunca fica mais agressivo, só o texto engana. Contar a espera só do "Retomar" após desafio.
- [ ] 1º desafio tarde da noite com a espera terminando depois da meia-noite roda o job da madrugada com pausas normais ("desafios hoje" zera à meia-noite). Avaliar contar as pausas em dobro pelas últimas 24 h.
- [ ] Índice em `resumo_preco.coletado_em` para a lista do dia (hoje varre a tabela inteira; ela cresce ~800 mil linhas/ano).

### Login, usuários e site novo

- [ ] Celular digitado sem o 9 extra (10 dígitos) é normalizado diferente do cadastrado com 11 dígitos e não entra. **Decidido (2026-10-19):** aceitar a variante sem o 9 no login, normalizando para o número cadastrado.
- [ ] `limpar_antigos` apaga linhas antes de pegar a trava consultiva; dois pedidos simultâneos podem raramente dar deadlock (500). Pegar a trava antes ou usar `SKIP LOCKED`.
- [ ] `GET /api/usuarios` ainda mostra a contagem de sessões ativas de admins para quem não é superadmin.
- [ ] Front: ao fechar um modal, o foco não volta para o botão que o abriu.

### Avisos, vigia e notificador

- [ ] Vigia de serviços: a batida de 60 s é uma thread à parte, então prova que o processo está vivo, não que o laço principal ou o navegador andam; um Playwright/Chromium travado não dispara `SERVICO_SEM_SINAL`. Se acontecer, mover a batida para dentro do laço de cada serviço.
- [ ] Vigia de serviços: container parado de propósito no compose recebe `SERVICO_SEM_SINAL` com lembrete a cada 2 h até ser pausado em Serviços. O vigia deveria ignorar serviço parado de propósito (hoje o jeito é pausá-lo no admin).
- [ ] Problema que bloqueia e só espera (CAPTCHA, Amazon pausada, sem login, IA pausada, carrinho) não recebe o lembrete de 2 h: o lembrete é decidido quando o evento se repete, e esses não se repetem enquanto esperam.
- [ ] Aviso "mensagem não enviada" nunca é resolvido, então o lembrete de 2 h mostra uma contagem que só cresce.
- [ ] Notificador, casos raros aceitos: (a) uma mensagem cujo registro sempre falha pode travar a fila; (b) se o banco cair entre gravar a oportunidade e gravar a mensagem, o alerta fica só no log.

### Admin antigo (juntar com a fase 3)

- [ ] Card da LigaMagic diz "Próxima começa em instantes" até a meia-noite quando a coleta do dia foi pulada (pausa no horário) (`consultas_painel.py`).
- [ ] Admin antigo lê a configuração duas vezes por página (sobra da configuração em tela).
- [ ] Casamentos: o selo/opção "sem par" cobre tanto "só ignorados" quanto "sem candidato" (as situações do produto no Dashboard). Alinhar os nomes.

### Oportunidades na área de negócio

- [ ] Tooltip da curva de preço sem o nome do anúncio e sem as cores do tema (pequena, a fazer).
- [ ] "Quase lá" sem limite padrão na API (pequena): hoje o limite vem do front.

### Código e dependências

- [ ] `openai` fixada em `<3` no `pyproject.toml`: a 3.x troca a biblioteca de rede e exige refazer os testes do pacote `ia`.
- [ ] Limpar as 6 reexportações `# noqa: PLC0414` em `src/` (sobra da extração do pacote `navegador`).
- [ ] `TZ` fixo em America/Sao_Paulo no compose: mudar o fuso em Configurações → Geral não muda os logs nem o relógio do noVNC.
- [ ] Seis itens menores da revisão final do coletor da Amazon (2026-10-14) ficaram "para depois" e não foram registrados. Dar como perdidos ou reabrir por uma revisão do código atual.

## 3. Acompanhar (sem código)

### Fase 3A (em produção desde 2026-10-22 11:37)

- [ ] Abrir a gestão (`localhost:8090/gestao`): menu lateral, selo de Casamentos, lista com filtros, "Revisar em sequência", confirmar e ignorar um par, "Voltar à lista" na mesma página.
- [ ] Catálogo: desligar e religar um produto pela chave e conferir o registro (`SELECT * FROM acao_gestao ORDER BY em DESC LIMIT 5`).
- [ ] Layout depois do deploy: rodar `scripts/verificar_layout.py` (agora com `/gestao/casamentos` e `/gestao/catalogo`) e olhar à mão, no celular e nos temas claro e escuro, a revisão de um produto e a página do produto (roteiro em `docs/IMPLANTACOES.md`).
- [ ] LigaMagic está desligada em Serviços desde 2026-10-21; religar quando quiser a coleta de volta.

### Oportunidades na área de negócio (depois do deploy)

- [ ] Trocar o `r2.dev` por domínio próprio (Custom Domains → `img.<domínio>`) antes de publicar na internet; o `r2.dev` é limitado e não serve para produção.

### Fim da oportunidade (desde 2026-10-20 21:50)

- [ ] Primeira semana: oportunidades que abrem e encerram várias vezes no mesmo dia mesmo com a carência de 30 min (ruído no grupo). Se acontecer, subir a carência em Configurações → Amazon → Monitor de preço.

### Coleta e casamento

- [ ] Catálogo com 2165 produtos ativos (eram 224) — **intencional** (monitorar todos, decidido em 2026-10-19). Acompanhar a carga: a etapa dos produtos da Liga lê ~450–500 páginas por dia (leitura por interesse; eram ~10 h com todos os ativos); a busca da Amazon (90/h na janela 08–22h) alcança cada produto sem par ~1 vez a cada 2 dias; mais anúncios novos e a busca alternativa = mais gasto com a IA.
- [ ] Acompanhar uma semana sem desafio com ~500 páginas/dia (leitura por interesse, desde a implantação): avisos "Liga · desafio do Cloudflare" e a linha "Produtos: … de … · casados, candidatos, novos, rodízio" do resumo diário. Se o desafio voltar, baixar o rodízio (por exemplo para 14 dias) ou subir as pausas em Configurações → LigaMagic. No fim, revisar também o máximo de cliques em "Exibir mais" com os números reais.
- [ ] CAPTCHA da Amazon com os dois navegadores somando ~270 páginas/h no mesmo endereço (busca 90/h + monitor 180/h, desde a separação). Se os CAPTCHAs aumentarem (avisos "Amazon (busca) · CAPTCHA" ou "Amazon (monitor) · CAPTCHA"), baixar os tetos em Configurações → Amazon.
- [ ] Quantos produtos ativos ainda não foram buscados (card Amazon (busca) no Dashboard; eram 1941 de 1969 sem candidato em 2026-10-19). Com 90 buscas/h e a janela de 14 h, a primeira passada nos ~2000 produtos leva cerca de 2 dias.
- [ ] Primeira semana do casamento por par: quantos ignorados foram recuperados (anúncios confirmados para um produto que antes estavam ignorados para outro: `SELECT count(*) FROM casamento c WHERE c.status = 'confirmado' AND EXISTS (SELECT 1 FROM casamento o WHERE o.anuncio_id = c.anuncio_id AND o.produto_id <> c.produto_id AND o.status = 'ignorado' AND o.origem <> 'outro_confirmado')`) e quantos produtos entraram na busca alternativa (`SELECT count(DISTINCT produto_id) FROM termo_busca`; com tentativa sem termo válido: `SELECT count(*) FROM fila_amazon WHERE termos_tentados_em IS NOT NULL`). Se a recuperação estiver lenta, plano B: a IA reavalia os ignorados contra os produtos de nome parecido (com o teto de gasto valendo).
- [ ] Resultado dos 19 pares em inglês reabertos em 2026-10-19 (`reabrir-ingles --aplicar`): quantos a IA confirmou e quantos voltaram a ignorado.
- [ ] Fila e gasto da IA nos primeiros dias depois de implantar o casamento por par (volume aceito; o teto de gasto protege): pares pendentes esperando a IA (Dashboard → "esperando você" e Casamentos), gasto do dia e do mês em Logs → IA (filtro "termos de busca" para a busca alternativa, 5 produtos por ciclo) e se o teto do dia está sendo atingido cedo. Se a fila não baixar, ajustar o lote ou os tetos em Configurações → IA.

### Operação

- [ ] Evolution API (WhatsApp): o Node dentro da imagem (24.11.1) tem a falha de Brotli do lançamento de 2026-10-21 (corrigida no Node 24.22.1) e a versão 2.3.7 expõe `/metrics` sem senha (CVE-2026-91997). Risco baixo (só escuta em 127.0.0.1); atualizar a imagem quando sair uma versão com o Node corrigido.
- [ ] Playwright: conferir na próxima versão se o Chromium empacotado traz todas as correções do Chrome estável (o 1.64.1 vem com um build anterior ao 156 estável).
- [ ] Atualizar o Python do PC de desenvolvimento (3.12.10; CVE-2026-12003 é escalada local no Windows). Não afeta os containers (3.12.15).
- [ ] Primeira semana do site novo (`localhost:8090`): login pelo código no WhatsApp, cadastro do grupo e de operadores, grade de acessos.
- [ ] Testar uma restauração do backup (README, seção do backup) num banco descartável, para saber que o arquivo volta inteiro.
- [ ] Primeiro "Serviço sem sinal" real: conferir que não houve alarme falso durante coletas longas (a batida é uma thread de 60 s).

## 4. Próximas funcionalidades (decisão do grupo)

- [ ] **Site novo, fase 2 — área de negócio**, em três sub-projetos (decidido em 2026-10-20: a informação estratégica é o produto; telas com gráficos e acompanhamento), na ordem A → B → C:
  - [x] **A. Fim da oportunidade** (merge `000fa6d`, em produção desde 2026-10-20 21:50): detalhe em "Concluídas".
  - [x] **B. Oportunidades** (merge `27e6364`, em produção desde 2026-10-21 08:44; detalhe em "Concluídas"): ativas e encerradas, linha do tempo e curva de preço (do `preco_amazon`), duração (`aberta_em` até `deixou_de_valer_em`), motivo do encerramento, recorrência por produto, quase oportunidades (casados com desconto entre 10% e o mínimo) e números do período; permissão `ver_oportunidades`. Os números de casamentos e IA por produto vêm de `consultas_catalogo.situacao_catalogo`.
  - [ ] **C. Mercado (LigaMagic)**: preço subindo ou caindo (7 e 30 dias), nº de lojas caindo (escassez), esgotou na Liga, preço fora da média de venda, lançamentos, volatilidade; talvez avisos de tendência. Permissão `ver_resultados` (ou `ver_mercado`). Começar com ~3 semanas de histórico (coleta desde 2026-10-13, ou seja, a partir de ~2026-11-03).
- [ ] **Site novo, fase 3 — área administrativa**, organizada por tarefa (spec de 2026-10-21: `docs/superpowers/specs/2026-10-21-fase3-area-administrativa-design.md`, a partir da auditoria de UX do mesmo dia), em três entregas:
  - [x] **3A. Casamentos e Catálogo** (merge `43fdd04`, em produção desde 2026-10-22 11:37; detalhe em "Concluídas").
  - [ ] **3B. Serviços, Atividade e Dashboard**: Serviços com estado único, "parado de verdade" e "Abrir" só para quem pode pausar e só na rede de casa; Atividade no lugar das 6 abas de Logs (busca por produto e ASIN, mensagens e ações de gestão); Dashboard com "precisa de você", saúde em uma linha, oportunidades agora e funil.
  - [ ] **3C. Configurações, Ofertas e Mensagens**: Configurações por objetivo com a caixa "Efeito"; Ofertas no padrão novo; o que sobrar dos 52 achados da auditoria de layout de 2026-10-18 (`docs/auditorias/2026-10-18-admin-layout.md`) e das pequenas do admin antigo (seção 2).
- [ ] **Site novo, fase 4 — desligar o admin antigo.**
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
