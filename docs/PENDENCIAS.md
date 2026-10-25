# Pendências do tcg-sniper

Lista única do que falta. Atualizar aqui quando algo entrar, sair ou mudar de prioridade.
Marcar `[x]` ao concluir, anotar o commit e mover para "Concluídas". Sem dados pessoais neste arquivo (o repositório é público).

Última revisão: 2026-10-25 (3B com merge na `main` (`266cc9d`), deploy pendente; coleta retomada pelo usuário e Amazon conferida logada; segurança etapa 1 em produção desde 2026-10-24 22:10; próxima entrega: 3C).

## Ordem sugerida

1. Acompanhar a primeira semana do monitor por grupo e a primeira coleta da Liga depois da retomada (seção 3).
2. Conferir a 3A em produção (seção 3, "Fase 3A") e, depois do deploy, a 3B (seção 3, "Fase 3B").
3. Site novo, fase 3, entrega 3C (Configurações, Ofertas e Mensagens) e depois a fase 4 (desligar o admin antigo, com a tabela de cobertura da seção 4). A 3B (Serviços, Atividade e Dashboard) tem merge (`266cc9d`); falta o deploy, com backup antes por causa da migração de índices. Spec: `docs/superpowers/specs/2026-10-21-fase3-area-administrativa-design.md`.
4. Seção 1, etapa 2: **obrigatória antes de publicar na internet ou vender acesso** (a etapa 1 está em produção desde 2026-10-24).
5. Sub-projeto C (Mercado), a partir de ~2026-11-03 (3 semanas de histórico da Liga).
6. Acompanhar ao longo dos dias (seção 3), sem prazo.
7. Seção 2 (pequenas), junto com a próxima mexida no código de cada área (as da gestão entram na 3C).
8. Margem líquida (seção 4), quando o grupo tiver os valores.

## 0. Crítico

Nenhum no momento.

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

## 2. Pequenas (sem pressa, juntar num pacote)

### Testes

- [ ] Teste instável: `tests/coletor_amazon/test_varredura_monitor.py::test_janela_que_fecha_no_meio_da_volta_nao_avisa_a_rodada` falhou uma vez numa rodada completa e passa sozinho (suspeita de dependência do relógio ou da ordem). Investigar antes de confiar nele no CI.
- [x] Ponta a ponta da gestão entra como superadmin; acrescentar um operador para exercitar as permissões das telas novas (feito para Serviços na 3B, commit `e255b2e`; falta o operador nas outras telas).
- [ ] `tests/test_compose_portas.py` só lê portas no formato curto (`"ip:porta:porta"`); uma porta no formato longo (`published:`) ou só `"8000"` passaria sem ser conferida.
- [ ] Teste da migração `acao_gestao` não confere o `ON DELETE SET NULL` no schema; a lista de permissões do operador está fixa em `tests/api/test_auth.py` (derivar de `PADROES`).

### Gestão do site novo (adiadas da revisão da 3A, 2026-10-22; entram na 3C)

- [ ] Catálogo: selo de situação sem tooltip; depois do lote não aparece quantos produtos mudaram; uma resposta antiga da lista pode desfazer na tela uma chave recém-trocada (só visual); a linha não mostra o nome em inglês, as lojas nem as contagens do casamento ("1 esperando você", "casado · 4 anúncios"), que a spec pede e a API já devolve; a chave registra a ação mesmo quando não muda nada.
- [ ] Revisão de casamentos: Enter com o foco no menu ⋯ avança para o próximo produto; ↑/↓ não rolam até o cartão escolhido; "desfazer" muda o cartão destacado sem avisar; no celular a foto grande e os parecidos ficam acima dos anúncios (a spec pede a Liga compacta); `RevisaoCasamento.tsx` tem ~400 linhas (dividir); "Pular" e "Próximo" levam ao mesmo produto.
- [ ] Lista de Casamentos: "Tentar de novo" sem cancelamento; depois de um erro, a lista antiga fica sob o alerta; página além da última sem link para a 1ª.
- [ ] Menu da gestão: o botão do menu no celular não recebe foco pelo teclado nem tem `aria-expanded`/`aria-controls` (aberto). Feitos na 3B (commit `7e02a55`): `GET /api/gestao/menu` conta sem montar a lista, e Mensagens e Logs viraram a Atividade no menu.
- [ ] API da gestão: a navegação da revisão refaz a lista filtrada a cada pedido; `DecisaoSaida.mensagem` nunca é preenchida; os tipos `Literal` e a classe de filtros repetem à mão as listas de situação e de filtros; o lote conta e aplica sem trava (dois usuários ao mesmo tempo podem mudar 1–2 produtos a mais; fica registrado em `acao_gestao`).
- [ ] Código: lambdas com parâmetro `l` e nomes parecidos `ORDENS_CASAMENTO`/`_ORDENS_CASAMENTO` (`consultas/casamentos.py`); `parecidos_na_liga` corta sufixos de forma agressiva e ordena por nome, não por proximidade.

### Pequenas da revisão da 3B (2026-10-25; adiadas, sem pressa)

- [ ] Histórico: `historico._pagina` repete a limitação de página escrita à mão (herdado do admin antigo).
- [ ] `admin/consultas.py`: `listar_categorias` e `detalhe_produto` seguem no admin antigo; mover na fase 4.
- [ ] Serviços (back): os testes de `retomar_desafio` não conferem o aviso `SERVICO_PAUSADO_MANUAL`; `cfg_efetiva` sem tipo e redundante com `zona`; um teste usa `servicos.aplicar_config` pelo módulo testado; a docstring de `rodar_agora` não diz que o Casador ignora zona e config.
- [ ] Estado dos serviços: sem testes nos limites exatos de 2 e 10 min, com ciclo aberto bloqueando "iniciando" e nas transições do monitor e do backup; `em_andamento` recebe `agora` sem usar; `saude_por_servico` com `resumo` sem tipo; linhas travadas em RODANDO mostrariam "parando" para sempre (a marcação de interrompidas ao reiniciar atenua).
- [ ] API de Serviços: `ajustar_amazon` grava `acao=codigo` (redundante) em `acao_gestao`; `extra="forbid"` só em `ResultadoSaida`; id de carrinho que não é inteiro dá 422 em vez de 404; `rodar-agora` e `retomar` são aceitos mesmo com a ação escondida na lista (igual ao admin antigo); o "último ok" do monitor, do Casador e do WhatsApp é o último registro (rótulo "Último registro"), não um ok de verdade.
- [ ] "Abrir" usa `host_publico`, e o noVNC só escuta em 127.0.0.1: com `host_publico` diferente de localhost/127.0.0.1 o link morre (em produção está 127.0.0.1 desde 2026-10-24).
- [ ] Atividade (back): `atividade.py` tem 730 linhas (virar pacote se crescer); `_SERVICO_DA_ORIGEM` repete as origens de `avisos/catalogo.py`; os índices da migração não usam `CONCURRENTLY` (trava curta de escrita no deploy); `estado_aviso.ultimo_em` muda e um aviso reaberto pode repetir entre páginas; o índice de `oferta_amazon` é `(lida_em, anuncio_id)`, não de coluna única (aceito).
- [ ] Atividade (API e tela): `de`/`ate` com `+HH:MM` precisam de URL-encode (o 422 confunde); `FiltroAtividade.mostrar_texto_mensagem` começa em `True` (falha aberta para chamadores futuros; trocar para `False`) e há uma linha em branco sobrando; `de` maior que `ate` não é validado (lista vazia); o teste "exige `ver_logs`" só confere a ausência do título; "Descartar" aparece para mensagem individual (o back decide); trocar o filtro A→B→A ou clicar duas vezes na mesma busca pode repetir uma página (um contador de geração resolveria).
- [ ] Dashboard: `rotas_gestao_dashboard` importa `NOMES_TELA`/`ORDEM` de outro módulo de rotas; `top_oportunidades` carrega todas as abertas para fatiar 3.
- [ ] Tela de Serviços: a recarga de 60 s pode sobrescrever o estado de uma ação recém-feita; ação que deu certo seguida de GET que falha mostra erro; nos cartões do celular a chave não tem rótulo visível, a dica só aparece com o mouse e a mensagem de sucesso nunca some; os testes usam `querySelector` por `href` em vez de papel e nome (o menu agora também tem "Atividade").
- [ ] Teste "Entrar" do front estourou o tempo uma vez sob carga (acompanhar se é instável).
- [ ] Índice em `oportunidade.mensagem_alerta_id` (a Atividade faz duas subconsultas correlacionadas por linha de mensagem) — na próxima migração.
- [ ] Atividade mostra "US$ 0.000000" em chamada da IA de custo zero (esconder quando 0).
- [ ] `POST /api/gestao/servicos/carrinho/{id}/conferido` sem limite do id (id acima de 2³¹ dá 500; reusar `MAX_ID`).
- [ ] Dashboard: rótulo "Ligar" para quem não pode pausar serviços (usar "Ver"); links das oportunidades exigem também `ver_area_negocio`.
- [ ] `destino_novo` perde o filtro de mensagens pendentes (`/mensagens?situacao=pendente`).
- [ ] "iniciando…" por 10 min em Liga/WhatsApp/Backup, que esperam o próprio horário (não mostrar para esses).
- [ ] `listar` dos serviços repete `ultimo_registro` para monitor, casador e WhatsApp.
- [ ] Guarda "não importa admin" não cobre o pacote `api`.

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
- [ ] `repositorio_acesso.travar_limite` ainda cita o "limite total" na docstring, e o caminho sem número (chave fixa) e `contar_pedidos` sem número ficaram sem uso desde a segurança etapa 1.
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

### Fase 3B (depois do deploy)

- [ ] Backup do banco, deploy e conferências em `docs/IMPLANTACOES.md` ("Site novo, fase 3B"); a migração `d6a2f8c4b1e9` só cria índices.
- [ ] Layout depois do deploy: rodar `scripts/verificar_layout.py` (agora com `/gestao/servicos` e `/gestao/atividade`).
- [ ] Olhar a Atividade e o Dashboard com dados reais: tempo de resposta com a tabela de ofertas cheia, e se "Precisa de você" bate com o que o grupo espera.

### Monitor por grupo e atualizações de segurança (em produção desde 2026-10-23 13:28)

- [ ] Na primeira coleta da Liga depois da retomada (Chromium novo, Playwright 1.64.1), conferir que o Cloudflare não pede desafio.
- [ ] Primeira rodada de cópia de fotos com a Pillow 13 (Logs → Manutenção): falha só nos itens fora de JPEG/PNG/WEBP/GIF.
- [ ] Primeira semana: conferir o ritmo da fila rápida (card em Serviços), quão velhas ficam as leituras do grupo lento e o tamanho da lista "esgotado na Liga" (Catálogo), vendo se algum desses produtos merece ação.
- [ ] Se a fila rápida crescer demais, ajustar `quase_oportunidade_min_pct` ou o intervalo da fila rápida.

### Antes de publicar na internet

- [ ] Trocar o `r2.dev` por domínio próprio (Custom Domains → `img.<domínio>`) antes de publicar na internet; o `r2.dev` é limitado e não serve para produção.

### Fim da oportunidade (desde 2026-10-20 21:50)

- [ ] Primeira semana: oportunidades que abrem e encerram várias vezes no mesmo dia mesmo com a carência de 30 min (ruído no grupo). Se acontecer, subir a carência em Configurações → Amazon → Monitor de preço.

### Coleta e casamento

- [ ] Catálogo com 2165 produtos ativos (eram 224) — **intencional** (monitorar todos, decidido em 2026-10-19). Acompanhar a carga: a etapa dos produtos da Liga lê ~450–500 páginas por dia (leitura por interesse; eram ~10 h com todos os ativos); a busca da Amazon (90/h na janela 08–22h) alcança cada produto sem par ~1 vez a cada 2 dias; mais anúncios novos e a busca alternativa = mais gasto com a IA.
- [ ] Acompanhar uma semana sem desafio com ~500 páginas/dia (leitura por interesse, desde a implantação): avisos "Liga · desafio do Cloudflare" e a linha "Produtos: … de … · casados, candidatos, novos, rodízio" do resumo diário. Se o desafio voltar, baixar o rodízio (por exemplo para 14 dias) ou subir as pausas em Configurações → LigaMagic. No fim, revisar também o máximo de cliques em "Exibir mais" com os números reais.
- [ ] CAPTCHA da Amazon com os dois navegadores no mesmo endereço: busca até 90/h e monitor limitado na prática pelas pausas (~211 páginas/h com 8–20 s; o teto configurado é 1.000). Se os CAPTCHAs aumentarem (avisos "Amazon (busca) · CAPTCHA" ou "Amazon (monitor) · CAPTCHA"), baixar os tetos em Configurações → Amazon.
- [ ] Quantos produtos ativos ainda não foram buscados (card Amazon (busca) no Dashboard; eram 1941 de 1969 sem candidato em 2026-10-19). Com 90 buscas/h e a janela de 14 h, a primeira passada nos ~2000 produtos leva cerca de 2 dias.
- [ ] Primeira semana do casamento por par: quantos ignorados foram recuperados (anúncios confirmados para um produto que antes estavam ignorados para outro: `SELECT count(*) FROM casamento c WHERE c.status = 'confirmado' AND EXISTS (SELECT 1 FROM casamento o WHERE o.anuncio_id = c.anuncio_id AND o.produto_id <> c.produto_id AND o.status = 'ignorado' AND o.origem <> 'outro_confirmado')`) e quantos produtos entraram na busca alternativa (`SELECT count(DISTINCT produto_id) FROM termo_busca`; com tentativa sem termo válido: `SELECT count(*) FROM fila_amazon WHERE termos_tentados_em IS NOT NULL`). Se a recuperação estiver lenta, plano B: a IA reavalia os ignorados contra os produtos de nome parecido (com o teto de gasto valendo).
- [ ] Gasto da IA em 2026-10-21: US$ 21,36 de US$ 30 no dia (4.047 chamadas), provavelmente a fila andando depois do religamento. Conferir se repete depois de retomar o casador.
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
  - [x] **3B. Serviços, Atividade e Dashboard** (merge `266cc9d`, deploy pendente; detalhe em "Concluídas").
  - [ ] **3C. Configurações, Ofertas e Mensagens**: Configurações por objetivo com a caixa "Efeito"; Ofertas no padrão novo; o que sobrar dos 52 achados da auditoria de layout de 2026-10-18 (`docs/auditorias/2026-10-18-admin-layout.md`) e das pequenas do admin antigo (seção 2).
- [ ] **Site novo, fase 4 — desligar o admin antigo:** apagar `admin/`, o serviço `admin` do compose e a porta 8000, depois de a 3C cobrir o resto. Cobertura do admin antigo (rota antiga → onde fica no site novo):

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
| `GET /mensagens`, `POST /mensagens/{id}` (reenviar, descartar) | Atividade (o quê = mensagem) + `POST /api/gestao/mensagens/{id}/{reenviar|descartar}` |
| Restantes (`/ofertas`, `/configuracoes*`, `/catalogo*`, `/produto*`, `/casamentos*`) | 3A (feito) ou 3C |

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

### Fase 3B — Serviços, Atividade e Dashboard na gestão (merge `266cc9d`, deploy pendente)

Plano `docs/superpowers/plans/2026-10-25-fase3b-servicos-atividade-dashboard.md`; migração `d6a2f8c4b1e9` (só índices; backup antes do deploy em `dados/backups/tcg-antes-fase3b-<data>.dump`). Commits `a372602`..`1e6a3c5` mais o ponta a ponta `e255b2e`.

- [x] Consultas de painel, logs, mensagens e menu movidas para o pacote neutro `tcg_sniper/consultas/`; ações de serviço neutras, compartilhadas pelo admin antigo e pela API (`4dd64d5`, `a372602`).
- [x] Estado único dos serviços, com "parando…", "parado de verdade" e "iniciando…" (`3e83bdd`); API `/api/gestao/servicos` (ligar, desligar, rodar agora, retomar, monitor e checkout da Amazon, carrinho conferido), com `acao_gestao` por ação (`5fe67ba`).
- [x] Linha do tempo única da Atividade (`7046809`, `d24ee0e`) e API `/api/gestao/atividade` com as ações de mensagens (reenviar, descartar), texto de mensagem escondido sem `ver_mensagens` na camada da consulta (`1d198b9`, `3b53f1e`).
- [x] API do Dashboard (`1da0220`, `2d6ca17`) e telas Serviços, Atividade e Dashboard com o menu novo (`5c72ef2`, `bf165c4`, `dc74b06`, `7e02a55`, `1e6a3c5`).
- [x] Ponta a ponta: Casador desligado e ligado, Atividade filtrada com a ação de gestão, Dashboard com os quatro blocos, operador sem chave nem "Abrir", layout em 390 e 1440 px nos dois temas (`e255b2e`).
- [x] Decisões: a Atividade não leva o cursor na URL (os filtros sim; "Carregar mais" acumula em memória) e usa uma lista de cartões em todas as larguras; "Precisa de você" lista só problemas reais (serviço desligado por configuração fica de fora).

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
