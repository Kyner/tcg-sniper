# Site novo, fase 3: área administrativa (gestão) organizada por tarefa

Data: 2026-10-21. Aprovado em conversa (brainstorming) com o usuário, com rascunhos de tela no navegador.

Migra o admin antigo (FastAPI + Jinja2 + htmx, porta 8000) para a área de gestão do site novo (`web/`, React + DaisyUI 5, API em `tcg_sniper/api`). A fase 4 desliga o admin antigo; até lá os dois convivem e o admin antigo continua funcionando.

## Problema

O admin antigo espelha as tabelas do banco, não as tarefas de quem o usa. Cada tarefa fica espalhada por 3 ou 4 telas e nenhuma tem tudo o que é preciso para terminar o que se veio fazer. Na auditoria de 2026-10-21 (navegação pelas tarefas, além da auditoria de layout de 2026-10-18):

- **Casamentos** (a tarefa que mais pesa): a fila não tem prioridade nem ordenação (produto sem preço na Liga pede decisão igual a um com preço); o detalhe não mostra foto de nenhum dos lados (a IA diz "imagens coincidem", o usuário não vê); abas Pendentes/Confirmados/Ignorados; a tela sobe e desce a cada clique; selo "oportunidade" em candidato de outro jogo; dois filtros que se sobrepõem.
- **Catálogo**: a lista não mostra situação do casamento nem preço da Amazon; a página do produto não mostra os pendentes nem tem a chave de monitorar; categorias configuradas por número; "Ativar/Desativar todos" em destaque.
- **Serviços**: repete o Dashboard com outro vocabulário ("pausado"/"desligado"/"funcionando"/"rodando"); o mesmo estado em 3 lugares; ao desligar, não dá para saber se parou de verdade.
- **Logs**: 6 abas por tabela técnica, sem busca por produto ou ASIN; a aba IA mostra só tokens e custo; falhas "interrompida" de reinício poluem.
- **Configurações**: 24 campos da Amazon e 12 da IA misturando regra de negócio, ritmo e custo, sem dizer para que serve cada um nem como um afeta o outro (ex.: com pausa de 8–20 s um navegador lê ~257 páginas/h, então o teto de 1.000 do monitor nunca é alcançado e 473 anúncios ficam atrasados, sem a tela mostrar isso).
- **Dashboard**: o produto (oportunidades) fica no rodapé; o topo tem alertas técnicos longos e 6 cartões de letra miúda; não diz o que fazer agora.

## Decisões do usuário

- **Organizar por tarefa**, não por tabela: revisar casamentos, gerir o catálogo, controlar os serviços, investigar a atividade (logs), ajustar as configurações, e um Dashboard que diz o que fazer agora.
- **Mobile first sempre** e responsivo: no celular, tabelas viram cartões; nada estoura a largura.
- **Status curto**: uma linha, cortada com "…"; o detalhe vai para o **tooltip** (ⓘ). Nada demorado de ler.
- **Casamentos**: revisar **vários em sequência**, comparando **foto e texto** dos dois lados (há muita variação: foil, idioma, edição, quantidade). Foco em **um produto por vez**: Liga parada à esquerda como referência, anúncios da Amazon à direita, marcando **C** (é o mesmo) ou **I** (não é) em cada um. Um produto pode ter **mais de um confirmado** (normal). **Sem abas** e **sem a tela pular**. A **lista** continua existindo para analisar ou entrar num produto específico.
- **Catálogo**: achar um produto e **ligar/desligar o monitoramento** (desliga produto que não interessa ao grupo), **um a um ou em lote** (selecionando ou aplicando a todos do filtro, inclusive por categoria). A tela atual é "feia e confusa".
- **Tendência de mercado** (produtos perdendo/ganhando lojas, preço subindo/caindo) **não fica no Catálogo**: é o sub-projeto C (Mercado), na área de negócio. O Catálogo só leva a ele por um link.
- **Serviços**: ativar e ver o status precisa ser funcional, detalhes em tooltip; **atalho para abrir cada serviço no seu endereço web**.
- **Logs**: uma tela com mais detalhe, que ajude a filtrar e organizar.
- **Configurações**: grupos que abrem e fecham, com **propósito claro** de cada grupo e **como um campo afeta o outro**.
- **Dashboard**: "precisa de você" → saúde em uma linha → oportunidades agora → funil.

## Escopo e ordem de entrega

Três entregas, cada uma com spec própria de plano e merge separado (chamada minha, no molde da fase 2 A/B/C; o usuário pode reordenar):

1. **3A — Casamentos e Catálogo** (a tarefa que mais pesa): lista e revisão de casamentos, catálogo e página do produto de gestão, e já o **menu da gestão** (`drawer` no celular) com o selo de Casamentos; os itens de telas ainda não migradas apontam para o admin antigo, como hoje.
2. **3B — Serviços, Atividade e Dashboard.**
3. **3C — Configurações, Ofertas e Mensagens**, e o que sobrar dos 52 achados da auditoria de layout de 2026-10-18 (`docs/auditorias/2026-10-18-admin-layout.md`) e das "pequenas" do admin antigo (`docs/PENDENCIAS.md`, seção 2).

Depois: fase 4 (desligar o admin antigo). O sub-projeto C (Mercado) segue a sua data (~2026-11-03) e é independente desta fase.

Fora do escopo: a área de negócio (já feita na fase 2), Usuários e Acessos (fase 1), a regra de casamento em si (`repositorio_casamento`, `repositorio_termos`, `priorizar_na_fila` não mudam; a gestão só chama), novas funções de coleta.

## Regras que valem para todas as telas

- **Só componentes do DaisyUI 5**, classes literais (regra do projeto). Nada de visual próprio.
- **Mobile first**: desenhar para 390 px e crescer. Tabelas viram listas de cartões abaixo de `md`. Sem rolagem horizontal da página.
- **Sem pular**: ação numa linha (confirmar, ignorar, ligar, desligar) atualiza **no lugar** (estado otimista, com volta e mensagem se a API falhar); a página não recarrega nem muda a rolagem.
- **Voltar preserva**: filtros, busca, página e ordenação ficam na URL (`?busca=&categoria=&ordem=&pagina=`); "Voltar" restaura a lista e a rolagem.
- **Status em uma linha** com `truncate`; texto completo em `tooltip` (ou toque no celular).
- **Vocabulário único de estado**: chave = **ligado/desligado**; processo = **rodando · esperando · atrasado · com problema · desligado**. Um mapa de cor único (rodando `badge-success`, esperando `badge-ghost`, atrasado `badge-warning`, com problema `badge-error`, desligado `badge-neutral`).
- **Fotos** sempre do bucket público de imagens (fase 2B); sem foto, um `skeleton`/ícone neutro. Nunca link direto para imagem da Liga ou da Amazon.
- **Números** com milhar e porcentagem calculada num lugar só (achado G7 da auditoria de layout); datas no fuso de Configurações → Geral.
- **Ação em lote ou destrutiva** pede confirmação com o número exato ("Desligar 412 produtos?") em `modal`.
- **Estados**: carregando, erro com "Tentar de novo", vazio com texto próprio e, se houver filtro, "Limpar filtros".
- Permissão checada na API (toda rota declara a sua) e no front (menu e botões só aparecem para quem pode).

## Telas

### Casamentos — lista (`/gestao/casamentos`)

- Busca (português ou inglês), filtros que aplicam sozinhos (sem botão "Filtrar"): **situação** (um filtro só, juntando os dois de hoje: esperando você, casado, só ignorados, sem candidato, todos), categoria, preço na Liga (com/sem).
- **Ordem padrão: produtos com preço na Liga primeiro**, depois mais pendentes (chamada minha: produto indisponível não vira oportunidade). Ordenação por nome, pendentes, preço.
- Linha/cartão: foto pequena do produto da Liga, nome (pt e en), preço "a partir de", contagem **pendentes · confirmados · ignorados**, selo "IA sugere" quando há sugestão. Clicar abre a revisão daquele produto.
- Botão **"Revisar em sequência"**: abre a revisão no primeiro produto **da lista filtrada**.

### Casamentos — revisão de um produto (`/gestao/casamentos/:produtoId`)

- Topo: posição na fila ("12 de 96"), **Anterior · Pular · Próximo produto**, seguindo a ordem e os filtros da lista de onde veio; "Voltar à lista" restaura filtros e rolagem.
- **Esquerda, fixa (sticky)**: produto da Liga — foto grande (toque amplia), nome pt e en, categoria, preço e lojas, **pistas de variação** (ex.: "sem Foil no nome", "idioma não informado"; derivadas do nome, sem IA), "Ver na LigaMagic ↗", **parecidos na Liga** (produtos de nome próximo, ex.: a versão Foil).
- **Direita**: anúncios da Amazon do produto, em três grupos **na mesma página, sem abas**:
  1. **Para decidir** (pendentes, os sugeridos pela IA primeiro): foto (toque amplia), título com a **variação destacada** (Foil/Non-Foil, idioma, quantidade), preço, vendedor, ASIN com link para a Amazon, **parecer da IA** (mesmo/outro, confiança, motivo em uma linha com o resto no tooltip), selo de idioma. Botões **C · é o mesmo**, **I · não é**, "é de outro produto…".
  2. **Confirmados** (podem ser vários): foto, título, preço, origem (você, IA, automático, link) e quando, "desfazer". Sem autor por usuário: `casamento` não guarda usuário e o admin antigo entra com senha única (chamada minha).
  3. **Ignorados**, fechado por padrão (`collapse`): foto, título, motivo, origem (você, IA, automático, outro confirmado), "desfazer".
- Ao clicar C ou I, o cartão muda de cor e vai para o grupo certo **sem recarregar nem mudar a rolagem**.
- **Atalhos de teclado**: C, I, ↓/↑ anúncio, Enter próximo produto (só no computador; mostrados num `kbd` discreto).
- "É de outro produto…": `modal` com os parecidos e a busca no catálogo, cada um com foto; fecha e volta ao mesmo ponto.
- Ações do par já existentes: "Rebuscar agora", "Reavaliar com a IA", "Gerar termos de busca" (menu ⋯ do topo), "Casar por link/ASIN" (campo no menu ⋯).
- **Sem selo "oportunidade"** em anúncio que a IA diz ser outro produto (chamada minha); o desconto aparece só como número.

### Catálogo (`/gestao/catalogo`)

- Busca grande (pt ou en), filtros que aplicam sozinhos: categoria, monitorado (sim/não/todos), situação do casamento, preço na Liga.
- Linha/cartão: caixa de seleção, foto, nome (pt e en), categoria, "a partir de", lojas, **situação do casamento** ("1 esperando você", "casado · 4 anúncios", "só ignorados", "sem candidato"), **chave de monitorar** (liga/desliga na hora, um a um).
- **Lote**: ao marcar uma ou mais linhas aparece a barra "N selecionados · Desligar monitoramento · Ligar monitoramento"; nela, "Selecionar todos os N do filtro". Aplicar pede confirmação com o número exato.
- Paginação de 20 a 50 (a definir pelo construtor), total visível.

### Produto na gestão (`/gestao/produtos/:id`)

- "Voltar ao Catálogo" preserva busca e filtros.
- Foto, nome, categoria, **chave de monitorar**, "Ver na LigaMagic ↗", **"Ver no Mercado"** (quando o sub-projeto C existir; antes disso, "Histórico do produto" da fase 2B).
- Liga (preço, lojas, média de venda, quando foi lido) × melhor Amazon confirmada (preço, diferença).
- **Casamentos deste produto**: contagem pendentes · confirmados · ignorados e "Revisar este produto →".
- Gráfico curto (30 dias) Liga × melhor Amazon, reaproveitando `CurvaPreco`.

### Serviços (`/gestao/servicos`)

- Uma linha por serviço (cartão no celular): LigaMagic, Amazon · busca, Amazon · monitor (com a sub-linha conferência de checkout), Casador (IA), WhatsApp, Backup.
- Colunas: **estado** (vocabulário único), **agora** (uma linha: "buscando 'Goblingram' · 84 na última hora", "473 com leitura vencida", "fila vazia"), **último ok**, **chave ligado/desligado**, ações.
- **Ao desligar**: a linha mostra "parando…" enquanto houver um ciclo em andamento (coleta/ciclo com situação `rodando`, rodada da IA aberta, mensagem sendo enviada) e, quando não houver mais nenhum e nenhuma leitura, coleta ou chamada nova tiver sido gravada depois da pausa, "**parado de verdade desde HH:MM**" (hora do último registro). Ao ligar, "iniciando…" até o primeiro registro novo. Só consulta, sem sinal novo nos coletores (chamada minha: a batida de `sinal_servico` continua com o processo pausado, então não serve para isso; WhatsApp e Backup usam `estado_notificador`/`estado_manutencao`).
- Ações por serviço: **Abrir** (endereço web do serviço, nova aba), **Atividade** (abre a Atividade filtrada no serviço), "Rodar agora" (onde existe), "Retomar" (Liga após desafio, checkout após carrinho ocupado).
- **Endereços**: noVNC da Liga `:6080`, da Amazon monitor `:6081`, da Amazon busca `:6082` (host de Configurações → Geral), painel da Evolution `127.0.0.1:8080/manager` para o WhatsApp; Backup sem endereço.
- **Segurança do "Abrir" (decidido pelo usuário em 2026-10-21)**: o noVNC do monitor é o navegador logado na conta da Amazon. Os links só aparecem para quem tem `pausar_servicos` (por padrão, só admin); as portas do noVNC nunca são publicadas na internet, então os links só funcionam na rede de casa (a tela diz isso no tooltip); o painel da Evolution só abre no próprio PC do servidor (a tela diz isso quando o acesso não vem de lá).
- Detalhe (horários, tetos, explicação) no tooltip ⓘ do nome.

### Atividade (`/gestao/atividade`) — substitui as 6 abas de Logs

- Linha do tempo única, mais recente primeiro, paginada por cursor.
- Filtros: **serviço**, **o quê** (coleta da Liga, busca, leitura do monitor, conferência de checkout, avaliação da IA, mensagem do WhatsApp, backup, aviso), **situação** (ok, parcial, falha, só problemas), **período**, **busca por produto, ASIN ou texto**. Interruptor "mostrar reinícios" (desligado por padrão esconde falhas "interrompida" causadas por reinício).
- Linha: quando, serviço, o quê, **produto/anúncio** (nome real, com link para o produto e para a Amazon), **resultado em português** (ex.: "mesmo 85% · ficou para você", "R$ 309,83 com impostos", "parcial · 512 de 791"). Custo da IA quando houver.
- Toque/clique abre o **detalhe** (observação completa, números, links). URLs longas e observações cruas só no detalhe.
- O nome do produto em cada linha vem da relação certa por linha (corrige o bug do admin antigo em que todas as linhas de Monitor e Checkout mostravam o mesmo produto, ver `PENDENCIAS.md`).
- **Ações de gestão** (decidido pelo usuário em 2026-10-21) entram aqui como "o quê: ação de gestão", com **quem** e **quando**: ação em lote no Catálogo (filtro ou IDs e quantos produtos), ligar/desligar serviço (e rodar agora, retomar), salvar configurações (grupos e campos alterados, valor antes → depois). Tabela nova (ex.: `acao_gestao`: usuário, quando, tipo, detalhe JSON), gravada na mesma transação da ação; nunca apagada pela limpeza diária. Decisões C/I de casamento **não** entram (já guardam data e origem). O admin antigo, que não tem usuário, grava como "admin antigo" se o construtor ligar o registro lá também (opcional).
- **Mensagens do WhatsApp** entram aqui como "o quê: mensagem", com o texto formatado (negrito do WhatsApp renderizado), situação e "Reenviar" no detalhe para quem pode (chamada minha: tira a tela Mensagens do menu).

### Configurações (`/gestao/configuracoes`)

- Grupos por **objetivo**, em `collapse` (abre e fecha); no computador, menu lateral de grupos.
- Cada grupo tem **uma frase de propósito** e, quando faz sentido, uma caixa **Efeito** que faz a conta com os valores digitados (antes de salvar) e mostra o resultado e o risco (`alert` sólido, aviso quando estoura).
- Cada campo: rótulo claro, explicação no tooltip ⓘ, **padrão** visível e ↺ para voltar ao padrão; campos que dependem de outro mostram o vínculo ("a partir de 15%: 20% do desconto mínimo − 5").
- **Barra fixa embaixo** "N alterações · Descartar · Salvar" (um salvar para a tela, só com os grupos alterados); validação junto ao campo; ao sair com alteração não salva, confirma.
- Técnico em "Avançado" dentro do grupo.

Grupos (todos os campos atuais, reorganizados):

- **Oportunidades** — o que vira alerta: desconto mínimo, "quase lá" a partir de, nova queda para avisar de novo, espera antes de encerrar, idade máxima do preço da Liga, validade da oportunidade (h). Efeito: faixas de alerta e de "quase lá", contagem atual.
- **Vendedores** — em quem confiar: mínimo de positivas, mínimo de avaliações, reler lojista a cada (dias).
- **Achar anúncios novos (Amazon · busca)**: horário, buscas por hora, mesmo produto de novo após, produto casado de novo a cada; Avançado: URL da busca, resultados por busca, limite de falhas. Efeito: buscas por dia e de quanto em quanto tempo cada produto sem par é procurado.
- **Acompanhar preço (Amazon · monitor)**: horário, ler cada anúncio a cada, páginas por hora (monitor + checkout). Efeito: páginas/h necessárias (`anúncios confirmados × 60 / intervalo`) × teto × capacidade real (ver "Cuidado com bloqueio"), intervalo efetivo e sugestão ("usar 32 min").
- **Conferir no checkout**: conferir a partir de (pontos abaixo do desconto mínimo), conferência vale por (h). Efeito: "a partir de X% de desconto".
- **Cuidado com bloqueio (vale para os dois navegadores da Amazon)**: pausa mínima e máxima. Efeito: páginas/h máximas de um navegador com a pausa média (3600 / (pausa média + tempo médio de página medido)); soma dos dois navegadores no mesmo IP.
- **LigaMagic**: horário e variação da coleta, produtos novos por dia, esfriar após desafio, máximo de cliques em "Exibir mais", pausas; **categorias com nome** (chips com busca, não mais IDs separados por vírgula); Avançado: URL da listagem, limite de falhas. Os nomes vêm de uma tabela fixa no código (ID → nome da categoria na Liga, levantada à mão a partir de `CATEGORIAS_SELADOS`); ID sem nome aparece como "categoria N". O filtro de categoria do Catálogo e de Casamentos usa o `tipo` do produto, como hoje (chamada minha).
- **IA · o que decide sozinha**: ligada, automático, confiança para confirmar, confiança para ignorar. Efeito: quantos produtos ficam para você.
- **IA · ritmo**: intervalo entre rodadas, anúncios por rodada. Efeito: avaliações por hora e em quanto tempo o teto do dia acaba no custo médio atual.
- **IA · quanto pode gastar**: teto do dia, do mês, chamadas por dia, com **barra do gasto atual**.
- **IA · modelo (Avançado)**: modelo, esforço, preço de entrada e de saída por milhão de tokens.
- **WhatsApp e avisos**: grupos mostrados pelo nome (o ID no tooltip), instância da Evolution; os 28 tipos de aviso **agrupados por área** com busca, uma linha cada (chave, destino, agrupamento), exemplo ao tocar.
- **Sistema**: IP/nome do PC na rede, fuso.

### Ofertas (`/gestao/ofertas`)

Migra a tela de Ofertas (todos os anúncios confirmados com preço atual × Liga, filtros de vendedor, desconto e categoria) com a regra mobile first: cartão por produto no celular, tabela enxuta no computador (produto com foto e nome sem selos empilhados; selos de origem e Prime no tooltip; a frase do checkout em uma linha "conferido R$ X com impostos" com o detalhe no tooltip). Sem rolagem horizontal.

### Dashboard (`/gestao`)

Substitui a página de atalhos atual de Gestão (Usuários, Acessos e API docs passam para o menu). De cima para baixo:

1. **Precisa de você**: lista curta, cada item com o botão que resolve — produtos esperando decisão ("Revisar em sequência"), serviço desligado ou com problema ("Ligar"/"Ver"), monitor atrasado ("Ver o efeito", abre o grupo de Configurações), IA perto do teto. Some quando não há nada.
2. **Saúde em uma linha**: bolinha por serviço (cor do vocabulário único) com 3–4 palavras no computador e só o nome no celular; toque abre Serviços.
3. **Oportunidades agora**: as 3 de maior desconto com foto e %, contagem de abertas, alertas hoje e na semana; link para Oportunidades (área de negócio), sem repetir a tela.
4. **Funil**: Liga → monitorados → só ignorados / sem candidato → casados (produtos e anúncios) → oportunidades; cada degrau abre a lista filtrada.

Recarrega a cada 60 s (como Oportunidades).

## Menu da gestão

Dashboard · Casamentos (selo com quantos esperam você) · Catálogo · Ofertas · Serviços · Atividade · Configurações · Usuários · Acessos. No celular, o menu da gestão vira `drawer`. Selos só para pendências que pedem ação.

## Permissões

Novas (lista prevista em `PENDENCIAS.md`), cada rota declara a sua:

| Permissão | O que libera | Operador por padrão |
|---|---|---|
| `revisar_casamentos` | ver e decidir casamentos, rebuscar, reavaliar, gerar termos | sim |
| `ver_catalogo` | ver catálogo e produto de gestão | sim |
| `editar_catalogo` | ligar/desligar monitoramento (um a um e em lote) | sim |
| `ver_servicos` | ver Serviços e a saúde no Dashboard | sim |
| `pausar_servicos` | ligar/desligar, rodar agora, retomar | não |
| `ver_logs` | ver Atividade (inclui mensagens) | sim |
| `ver_mensagens` | ver o texto das mensagens na Atividade | sim |
| `reenviar_mensagens` | reenviar mensagem | não |
| `ver_configuracoes` | ver Configurações | sim |
| `editar_configuracoes` | salvar Configurações | não |

Os padrões do operador são chamada minha (editáveis na grade Gestão → Acessos). Grupo: nenhuma. Admin: todas. Ofertas usa `ver_catalogo`. Toda tela da gestão exige `ver_area_gestao` **e** a permissão própria (chamada minha: quem perdeu a entrada na gestão não entra por uma permissão de tela esquecida); as novas entram com o padrão da tabela para quem não tem linha salva na grade.

## API

- Rotas novas em `/api/gestao/...` (casamentos, catálogo, produtos, serviços, atividade, configurações, ofertas, dashboard), JSON, com a permissão declarada e os erros padronizados da fase 1.
- A regra continua nos repositórios existentes; consultas novas no pacote neutro `tcg_sniper/consultas/` (como na fase 2B), reaproveitando as do admin antigo onde servirem (`consultas_painel`, `consultas_amazon`, `consultas_menu`).
- Validação de configurações reaproveita os limites de hoje (`formularios_config`, `formularios_ia`, `LIMITES_CONFIG_LIGA`, `coletor_amazon.config`), movida para um lugar neutro para a fase 4 apagar o pacote `admin`.
- A caixa **Efeito** pode ser calculada no front (com os números atuais vindos da API: anúncios confirmados, produtos sem par, custo médio por avaliação, tempo médio de página medido) ou por uma rota que recebe os valores e devolve o efeito; a decisão é do construtor, desde que a conta seja uma só e testada.
- Lotes do catálogo: uma rota que recebe ou a lista de IDs ou o filtro, devolve a contagem para a confirmação e aplica numa transação.

## Testes

- API: cada rota com a permissão certa (com e sem), filtros e paginação, lote com filtro, "parado de verdade", nome do produto por linha na Atividade (regressão do bug do admin antigo), contas da caixa Efeito.
- Front (Vitest): cada tela com os estados (carregando, erro, vazio, filtro), ação no lugar sem recarregar, voltar preservando filtros, atalhos de teclado.
- Ponta a ponta (Playwright) e layout (`scripts/verificar_layout.py`) em 390 e 1440 px, temas claro e escuro, sem rolagem horizontal.

## Riscos

- **Duas telas convivendo** até a fase 4: decisões tomadas numa aparecem na outra (mesmo banco); nada a migrar.
- **Fila de casamentos grande** com fotos: carregar foto sob demanda (`loading="lazy"`) e paginar os ignorados.
- **Lote no catálogo** é a ação mais perigosa: confirmação com número exato e registro em Atividade (`acao_gestao`).
- **Migração**: só a tabela `acao_gestao` (3B, junto com a Atividade; o lote do 3A grava nela, então ela entra no 3A se o 3A for primeiro). Backup do banco antes do deploy (regra do projeto).
- **Contas da caixa Efeito** dependem de medidas (tempo médio de página); sem medida, mostrar a conta com o dado que há e dizer "estimativa".

## Deixado ao construtor

Paginação exata, debounce da busca, formato do cursor da Atividade, quais pistas de variação extrair do nome (foil, idioma, quantidade, edição), forma de calcular os "parecidos na Liga", tamanho das fotos, e se a caixa Efeito é calculada no front ou na API.
