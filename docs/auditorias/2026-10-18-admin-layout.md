# Auditoria de UI/UX do admin do tcg-sniper (18/10/2026)

**Escopo:** admin em produção (http://127.0.0.1:8000, Docker), FastAPI + Jinja2 + DaisyUI 5 + htmx.
**Método:** Playwright dentro do container (Chromium + `ADMIN_SENHA` do ambiente). Toda requisição que não fosse GET era abortada (`ctx.route`), e **nenhuma foi tentada** (lista de bloqueadas vazia nas 3 rodadas). Ao todo foram 318 visitas automáticas (66 URLs × 390/1440 × winter/night, mais 768 px, menu recolhido, abas de Configurações, menu móvel aberto e filtros abertos) e 150 prints de janela para olhar os detalhes.

**Prints:** `prints/` tem as páginas inteiras, com o nome `<rota>-<largura>-<tema>[-recolhido].png`. `prints/vista/` tem as janelas, com o nome `<tela>-<1440|390><w|n>[-b].png` (w = winter, n = night, -b = depois de rolar). Os dados brutos estão em `prints/dados.json`.

**Medições automáticas:**
- **Velocidade:** todas as telas abriram em menos de 1,2 s (carga em no máximo 0,89 s). Nenhuma tela lenta.
- **Console e rede:** sem erros e sem requisições com falha. As exceções são os 404/400 provocados de propósito. O htmx da CDN carregou bem.
- **Campos sem rótulo:** nenhum. Também não há imagens sem `alt`, `style=` inline nem `onclick` em elemento que não recebe foco.
- **Regra de design:** cumprida. `estilo.css` só importa Tailwind e DaisyUI, não há CSS próprio nem estilo inline, e todos os componentes são do DaisyUI (card, stats, tabs, badge, alert, collapse, join, table, list, toggle, fieldset).
- **Contraste:** o tema night não teve nenhum texto abaixo de AA. O tema winter teve vários (detalhes em G1 a G3).

---

## Global (vale para todas as telas)

| # | Sev. | O quê / onde | Print | Correção sugerida |
|---|---|---|---|---|
| G1 | **Quebrado** | **Winter: textos quase invisíveis.** Os avisos amarelos do Dashboard (`alert-warning alert-soft`) têm contraste de 1,36:1 e o aviso "Salvo" (`alert-success alert-soft`) tem 1,70:1. Os selos `badge-outline` info/warning ("importado (EUA)", "Prime", "sugerido pela IA") ficam em 1,3:1. O desconto negativo (`badge-error badge-outline`) fica em 2,3:1. Os números `text-success`/`text-warning`/`text-info` dos stats ("51", "5", "0") ficam em 1,8:1. No night, tudo isso está legível. | dashboard-1440-winter.png, vista/ofertas-1440w.png, vista/cas-prod-396-1440w.png | Trocar `alert-soft` por `alert` sólido (o `*-content` tem contraste) ou por `alert-soft` + `text-base-content`. Trocar `badge-outline` por `badge-soft`. Nos stats, usar `text-base-content` e pôr a cor num `badge`/`status` ao lado. Outra saída é ajustar `--color-warning`/`--color-info` do winter no plugin do DaisyUI. |
| G2 | Inconsistente | Winter: o texto de `btn-primary` (Filtrar, Salvar, Rodar agora, Abrir, Casar) fica em 3,62:1, abaixo de 4,5 para texto pequeno. | servicos-1440-winter.png | Usar `btn-primary` sem `btn-sm` nas ações principais ou ajustar `--color-primary-content`. |
| G3 | Melhoria | Winter: o texto secundário `text-base-content/60` (cabeçalhos de tabela, `stat-title`, ajudas de campo, ASIN, datas) fica entre 2,9 e 3,05:1. | vista/catalogo-1440w.png | Subir para `/70` ou `/80` no winter, ou só nos `th`. |
| G4 | **Quebrado** | **As páginas de erro saem como JSON cru:** `{"detail":"Not Found"}` em inglês, sem layout e sem menu (404 de `/produto/999999999`, `/naoexiste`; 400 de `/logs?aba=xyz`). | vista/erro404-1440n.png, vista/erro400-1440w.png | Criar um `exception_handler` para `HTTPException` que renderize `base.html` com `alert alert-error` em português e um botão `btn` "Voltar ao Dashboard". |
| G5 | Inconsistente | **Menu recolhido sem nome acessível:** os 8 links e o botão de tema ficam só com o ícone. O rótulo recebe `hidden` (display:none) e o `data-tip` não é lido por leitor de tela. | dashboard-1440-winter-recolhido.png, vista/recolhido-tooltip.png | Pôr `aria-label="{{ rotulo }}"` no `<a>` ou trocar `is-drawer-close:hidden` por `is-drawer-close:sr-only` no `<span>` do rótulo. |
| G6 | Inconsistente | **Crase errada em "À partir de"**, que deve ser "A partir de". Aparece no Catálogo (coluna e rodapé), em Casamentos, em Ofertas ("Liga (à partir de)"), no produto (aba "Preço à partir de") e em Casamentos › produto. | vista/catalogo-1440w.png, vista/produto-1804-1440w-b.png | Corrigir o texto nos templates. |
| G7 | Inconsistente | **Números com formatos diferentes.** "2262 produto(s)" no Catálogo e "2165 produto(s)" em Casamentos, contra "2.262"/"2.165" no Dashboard. Também "1305 de 2165 com preço", "3 de 10000" e "10000" no campo. O desconto aparece como 20,83% no Dashboard, 20,82% em Ofertas e "20%" no WhatsApp. | dashboard-1440-winter.png, vista/ofertas-1440w.png, vista/mensagens-1440w.png | Usar o filtro `milhar` em todas as contagens. Calcular e arredondar a % num lugar só (mesma função e mesmas casas). |
| G8 | Inconsistente | **Estados vazios diferentes e às vezes errados.** "Nenhum produto encontrado." / "Nenhum produto neste filtro." / "Nenhuma oferta neste filtro." / "Nenhuma mensagem." / "Nenhuma coleta ainda.". Com filtro ativo, Logs diz "ainda", o que é falso (ex.: checkout `sem_login`, IA `com_erro`, Liga `pausada_desafio`). É texto solto, e Casamentos ainda mostra "Página 1 de 1" no vazio. | vista/logs-vazio-390n.png, vista/casamentos-390w.png | Criar um macro `vazio(texto, limpar_url)` com o mesmo visual (linha de tabela centralizada `text-base-content/70` ou `alert alert-info alert-soft`) e um link "Limpar filtros". Dizer "neste filtro" quando houver filtro. Esconder a paginação quando total = 0. |
| G9 | Inconsistente | **Barras de filtro diferentes entre telas.** Catálogo, Casamentos e Ofertas ficam num card sem rótulos (só a 1ª opção, "todos"/"todas") e o "Filtrar" cai sozinho numa 2ª linha. Mensagens tem `fieldset-legend` visível. Logs usa um select minúsculo, fora de card. | vista/catalogo-1440w.png, vista/mensagens-1440w.png, vista/logs-liga-1440w.png | Usar um padrão só: card + `fieldset` com `fieldset-legend` em cada filtro, mesmo tamanho (`select-sm`/`input-sm`) e botão alinhado na mesma linha (`join` ou grid com `items-end`). |
| G10 | Inconsistente | **Vocabulário e cor de estado misturados.** "rodando" aparece como `badge-info` (Dashboard › LigaMagic, Logs) e como `badge-success` (Serviços › WhatsApp e Backup). "ligado", "funcionando", "rodando", "Ativo", "Monitorado" e "Monitorar" disputam o mesmo sentido. | servicos-1440-winter.png, dashboard-1440-winter.png | Definir um glossário (ex.: ligado/desligado para a chave, ativo/parado para o processo) e um mapa de cor único em `selo()`. |
| G11 | Melhoria | A coluna de data tem um nome por tela: "Início", "Quando", "Criada em", "Lido em", "Visto desde". | — | Padronizar ("Quando" ou "Data") e deixar o nome específico só onde muda o sentido. |
| G12 | Inconsistente | **Identificadores internos na tela:** "chamada_ia", "conferencia_checkout" (Logs › Manutenção), "pausada desafio", "carrinho ocupado", "low" (esforço da IA), "lojista FBA". | vista/logs-manut-1440w.png, vista/config-aba3-1440w.png | Mapear para rótulos em português ("chamadas da IA", "conferências de checkout", "pausada (desafio)", "baixo"). |

## Dashboard

| # | Sev. | O quê / onde | Print | Correção |
|---|---|---|---|---|
| D1 | Inconsistente | **"Pendentes 5"** (card Casamentos e "de 5 pendentes" no card IA), mas Casamentos (filtro padrão "pendentes") diz "Nenhum produto neste filtro." e o menu não mostra contador. O Dashboard conta anúncios de produtos inativos; Casamentos e o menu contam só produtos ativos. Todas as larguras e temas. | dashboard-1440-winter.png, vista/casamentos-390w.png | Usar a mesma regra (só produtos ativos) no `consultas_painel` ou explicar ("5, todos de produtos inativos") com link. |
| D2 | Inconsistente | O card Amazon mostra o selo verde "funcionando" e, logo abaixo, "Último ciclo hoje 16:27 (falha)", com o alerta amarelo no topo. | dashboard-1440-winter.png | Usar o selo `badge-warning` "atenção" quando o último ciclo falhou. |
| D3 | Melhoria | O alerta diz "terminou com falha. interrompida": a observação crua vem colada e em minúscula. | dashboard-1440-night.png | Reescrever: "terminou com falha (interrompida: o coletor reiniciou)". |
| D4 | **Quebrado** | 390 px, "Atividade de hoje": o rótulo "Coleta da LigaMagic" quebra no meio da palavra ("LigaMag / ic"), espremido pelo valor à direita. | dashboard-390-winter.png, menu-aberto-390-night.png | Na linha: `flex-col sm:flex-row` (valor embaixo no celular) ou `shrink-0` no rótulo e `text-right min-w-0` no valor. |
| D5 | Melhoria | 390 px: os `stats-vertical` fazem o Dashboard ter cerca de 2.600 px de altura. | dashboard-390-winter.png | `stats stats-horizontal` com `grid grid-cols-3` (3 números pequenos cabem) ou `stat` compacto. |
| D6 | Melhoria | "Avaliados 1.120 / de 5 pendentes" é confuso (1.120 de 5?). | dashboard-1440-winter.png | Trocar a descrição para "5 ainda pendentes". |

## Serviços

| # | Sev. | O quê / onde | Print | Correção |
|---|---|---|---|---|
| S1 | Inconsistente | O estado aparece duas vezes: o selo "ligado" no título e a chave com "Ligado" ao lado, em todos os cards. | servicos-1440-winter.png | Manter só a chave (`toggle` + rótulo) e usar o selo para o estado do processo (rodando, parado, desafio). |
| S2 | Inconsistente | O card Amazon não menciona a falha do último ciclo, que o Dashboard alerta. | servicos-1440-winter.png | Mostrar "Último ciclo: falha (interrompida)" com link para Logs › Amazon. |
| S3 | Melhoria | As chaves enviam o formulário ao mudar (`onchange submit`), sem confirmação. Desligar a "Conferência de checkout" ou o "WhatsApp" fica a um clique acidental. | servicos-390-winter.png | Usar um `modal` DaisyUI de confirmação só para desligar. |
| S4 | Melhoria | O texto difere do Dashboard: "variação de 30 min" contra "± 30 min". | — | Usar a mesma frase. |

## Catálogo

| # | Sev. | O quê / onde | Print | Correção |
|---|---|---|---|---|
| C1 | Melhoria | "Ativar/Desativar todos os 2262 deste filtro" age em lote sem confirmação. O "Ativar" está em destaque e cada ativo gera 1 visita/dia à Liga. | vista/catalogo-1440w.png | `modal` de confirmação com a contagem e o tempo estimado. Botões `btn-outline` e `btn-sm`. |
| C2 | Inconsistente | 390 px: o nome em inglês (`nome_en`, `text-sm`) fica maior que o nome principal em português, que fica pequeno. A hierarquia se inverte. | vista/catalogo-390n.png | `nome_en` com `text-xs`, ou o nome principal com o mesmo `text-sm`. |
| C3 | Inconsistente | Coluna "Monitorar" com rótulos "Ativo/Inativo", filtro "ativos/inativos" e produto "Monitorado". | vista/catalogo-1440w.png, vista/produto-1804-1440w.png | Escolher um termo ("Monitorado"). |
| C4 | Melhoria | 768 px: a tabela rola dentro (831 px em 736) e o select de categoria fica cortado. | catalogo-768-winter.png | Esconder "Visto desde" abaixo de `lg` (`hidden lg:table-cell`). |

## Casamentos (lista, produto e trocar)

| # | Sev. | O quê / onde | Print | Correção |
|---|---|---|---|---|
| K1 | Inconsistente | Igual a D1: o filtro padrão "pendentes" abre vazio enquanto o Dashboard diz 5. | vista/casamentos-390w.png | Ver D1. |
| K2 | Melhoria | A coluna "IA sugere" está vazia em todas as linhas e ocupa espaço. | vista/casamentos-todos-1440w.png | Esconder a coluna quando nenhuma linha tiver valor. |
| K3 | Inconsistente | Produto: no winter, os selos "importado (EUA)" e "Prime" ficam ilegíveis (G1). A tabela de ofertas usa `table-xs` (11 px), destoando do resto. | vista/cas-prod-396-1440w.png | `badge-soft` e `table-sm`. |
| K4 | Melhoria | Produto, 390 px: o campo "Colar link da Amazon (ou o ASIN)" tem só placeholder, e ele aparece cortado. | vista/cas-prod-396-390n-b.png | Pôr `fieldset-legend` "Link da Amazon" e um placeholder curto ("link ou ASIN"). |
| K5 | Melhoria | Produto, 390 px: a tabela de ofertas corta "Selos" e "Elegível", e a rolagem lateral não fica evidente. | vista/cas-prod-396-390n-b.png | `list`/cards no celular ou `hidden sm:table-cell` nessas colunas. |
| K6 | Melhoria | "Desfazer" (casamento confirmado) age sem confirmação. | vista/cas-prod-396-1440w.png | `modal` de confirmação. |
| K7 | **Quebrado** | **Trocar, 390 px:** os botões "Escolher" são espremidos para uma letra por linha (E/s/c/o/l/h/e/r). | vista/trocar-vazio-390n.png | No item: `flex-col sm:flex-row` ou `shrink-0 whitespace-nowrap` no botão (ou `list-row` com o botão em coluna própria). |
| K8 | Inconsistente | Trocar: não tem "← Voltar" (Casamentos › produto tem). O ASIN vem entre parênteses, e em outras telas não. Em 1440, os botões "Escolher" ficam colados ao fim de cada nome, desalinhados. A tela só foi alcançada pela URL (`/casamentos/1/trocar`), porque não há pendentes agora. | vista/trocar-busca-1440w.png | Pôr o link "Voltar" e o botão alinhado à direita (`list-row` + `list-col-grow`). |

## Ofertas

| # | Sev. | O quê / onde | Print | Correção |
|---|---|---|---|---|
| O1 | **Quebrado** | **Em 1440 e 768, a tabela é mais larga que o card** (1.516 px em 1.121). "Diferença (R$)", "Vendedor" e as colunas seguintes ficam fora da tela. A coluna Produto é espremida (nomes em 6 linhas) porque a linha "conferido no checkout: … (impostos …; frete …)" não quebra e alarga a coluna Amazon. Com o menu recolhido continua cortando. Em 768 só se veem Produto e Liga. | vista/ofertas-1440w.png, vista/recolhido-tooltip.png, ofertas-768-winter.png | `whitespace-normal max-w-56` no `preco_conferido`, `min-w-56` no Produto, `hidden 2xl:table-cell` nas colunas secundárias, e os cards do celular até `lg` (hoje vão só até `md`). |
| O2 | Inconsistente | A mesma grandeza tem 3 nomes: "Diferença (%)" na coluna, "Desconto mínimo (%)" e "maior desconto %" nos filtros. O valor negativo sai como "R$ -42…", e não "-R$ 42,00". | vista/ofertas-1440w.png | Usar "Desconto" em todo lugar e formatar o sinal antes do símbolo. |
| O3 | Inconsistente | 20,82% aqui, 20,83% no Dashboard e 20% no WhatsApp (G7). | — | Ver G7. |
| O4 | Melhoria | O botão "≥ desconto configurado (20%)" no cabeçalho parece uma ação, mas é um atalho de filtro. Fica longe dos filtros. | vista/ofertas-390w.png | Movê-lo para a barra de filtros como chip (`btn btn-sm btn-soft`, ativo quando aplicado). |
| O5 | Melhoria | O ASIN fica embaixo do nome aqui e em cima do nome em Logs › Monitor. Até 4 selos empilhados por linha. | vista/ofertas-1440n-b.png, vista/logs-monitor-1440n.png | Padronizar a posição. Juntar os selos numa linha (`flex flex-wrap gap-1`). |

## Mensagens

| # | Sev. | O quê / onde | Print | Correção |
|---|---|---|---|---|
| M1 | Melhoria | O markdown do WhatsApp aparece cru ("*Liga · coleta interrompida*", "_coletor_"). | vista/mensagens-1440w.png | Converter `*x*` para `<strong>` e `_x_` para `<em>` na exibição. |
| M2 | Inconsistente | Mensagens enviadas mostram "Tentativas 0" (e "0 tentativa(s)" no celular). | vista/mensagens-390n.png | Contar a tentativa que deu certo ou mostrar "1ª tentativa". |
| M3 | Melhoria | As colunas "Criada em" e "Enviada em" quase sempre são iguais. O subtítulo "Tabela de saída do notificador" é jargão. | vista/mensagens-1440w.png | Juntar em "Quando" com o atraso só se > 1 min. Subtítulo: "Tudo o que o sistema mandou ou vai mandar no WhatsApp". |
| M4 | Melhoria | O "mais" (`details`) ocupa a largura toda com fundo e chama mais atenção que o texto. | vista/mensagens-detalhe-1440w.png | `collapse` sem fundo ou `link link-hover text-xs`. |

## Logs

| # | Sev. | O quê / onde | Print | Correção |
|---|---|---|---|---|
| L1 | **Quebrado** | **Checkout em 1440: a coluna "Situação" (a mais importante) sai da tela**, e o selo "carrinho ocupado" aparece cortado. Anúncio e Vendedor quebram em 3 linhas. No celular também é tabela (a aba Liga usa cards). | vista/logs-checkout-1440w.png, logs-aba-checkout-390-winter.png | Pôr Situação logo depois de "Quando", esconder Itens e Impostos abaixo de `2xl` e usar cards no celular, como em Liga e Amazon. |
| L2 | Inconsistente | Com filtro, o vazio diz "ainda" (G8). | vista/logs-vazio-390n.png | Ver G8. |
| L3 | Melhoria | 390 px: as 6 abas quebram em 2 linhas. | vista/logs-liga-390w.png | `tabs tabs-border flex-nowrap overflow-x-auto`, ou um `select` no celular. |
| L4 | Inconsistente | Manutenção mostra "Apagados: coleta 0 · chamada_ia 0 · conferencia_checkout 0" (G12). Amazon mostra a falha como "0 buscas · 0 falhas · 219 min / interrompida", que soa contraditório. | vista/logs-manut-1440w.png, vista/logs-amazon-390w.png | Rótulos em português. "Interrompida (o coletor reiniciou)" no lugar das contagens zeradas. |
| L5 | Melhoria | IA: "Tokens 721 / 167" sem legenda. | vista/logs-ia-1440w.png | Cabeçalho "Tokens (entrada / saída)". |

## Configurações

| # | Sev. | O quê / onde | Print | Correção |
|---|---|---|---|---|
| F1 | **Quebrado** | **A aba LigaMagic em 390 px estoura a largura** (documento com 530 px). Campos e ajudas ficam cortados à direita, com rolagem horizontal na página. Provável causa: a linha "Padrão: {{ categorias_padrao }}", longa e sem espaços, alarga o item do grid. | config-aba-ligamagic-390-winter.png, vista/config-liga-390w.png | `min-w-0` nos `fieldset` do grid e `break-words` (ou `break-all`) na linha "Padrão: …". |
| F2 | Inconsistente | Liga/desliga aparece como `select` "Sim/Não" (IA ligada, Automático), enquanto Serviços usa `toggle`. "Esforço de raciocínio" mostra o valor em inglês ("low"). | vista/config-aba3-1440w.png | Usar `toggle` com rótulo e opções em português (baixo/médio/alto). |
| F3 | Inconsistente | O stat "Chamadas hoje 3" repete na descrição "3 de 10000", sem separador de milhar. | vista/config-aba3-1440w.png | Descrição "de 10.000 por dia". |
| F4 | Melhoria | A aba Avisos tem cerca de 6.600 px em 1440 (35 tipos em lista única), sem agrupamento nem busca. Os toggles salvam ao mudar. | vista/config-aba4-1440n.png | Agrupar por serviço (LigaMagic, Amazon, IA, Backup, WhatsApp) em `collapse` ou sub-`tabs` e mostrar o exemplo só ao expandir. |
| F5 | Melhoria | As abas são radios: recarregar volta para "Geral" (só Avisos tem `?msg=`), então não dá para criar link direto para a aba IA. Mesmo assim, o Dashboard tem o link "Configurações → IA". | config-aba-ia-1440-winter.png | Ler `#ia` ou `?aba=ia` para marcar a aba. |

## Detalhe do produto (/produto/{id})

| # | Sev. | O quê / onde | Print | Correção |
|---|---|---|---|---|
| P1 | Inconsistente | Não tem "← Voltar" (Casamentos › produto tem). | vista/produto-1804-1440w.png | Pôr o mesmo link "Voltar". |
| P2 | Melhoria | Selos ilegíveis no winter (G1). Na tabela de vendedores (`table-xs`), "Elegível" sim/não vem em texto, e na lista de Ofertas a mesma informação é um selo. | vista/produto-1804-1440w-b.png | `badge-soft`, `table-sm`, e um `badge` para "não elegível". |

---

## Top 10 (por prioridade)

1. **G1, contraste do winter:** os alertas amarelo e verde, os selos `badge-outline` e os números coloridos ficam praticamente invisíveis no tema claro. É o que mais atrapalha o uso diário.
2. **O1, tabela de Ofertas cortada em 1440 e 768:** "Diferença (R$)" e "Vendedor" ficam fora da tela, e o Produto em 6 linhas.
3. **L1, Logs › Checkout em 1440 esconde a coluna "Situação".**
4. **F1, Configurações › LigaMagic estoura em 390 px** (530 px, campos cortados).
5. **D1/K1, "Pendentes 5" no Dashboard contra 0 em Casamentos e no menu:** dois números diferentes para a mesma coisa.
6. **K7, botões "Escolher" em Trocar, no celular,** espremidos em uma letra por linha.
7. **G4, erros 404/400 em JSON cru** e em inglês, sem layout.
8. **D2/S2, card Amazon "funcionando" com o último ciclo em falha**, e Serviços não mostra a falha.
9. **G5, menu recolhido sem nome acessível** (ícones sem `aria-label`).
10. **G8 e G9, estados vazios e barras de filtro despadronizados** (inclui "ainda" errado com filtro e "Página 1 de 1" no vazio).

## Contagem por severidade

- **Quebrado: 7** (G1, G4, D4, K7, O1, L1, F1)
- **Inconsistente: 22**: G2, G5, G6, G7, G8, G9, G10, G12, D1, D2, S1, S2, C2, C3, K3, K8, O2, M2, L4, F2, F3, P1. K1, O3 e L2 não entram na conta porque repetem D1, G7 e G8.
- **Melhoria: 23**: G3, G11, D3, D5, D6, S3, S4, C1, C4, K2, K4, K5, K6, O4, O5, M1, M3, M4, L3, L5, F4, F5, P2.

## Limitações

- **Trocar:** não havia anúncio pendente, então a tela foi vista pela URL direta `/casamentos/1/trocar` (GET).
- **Telas que só aparecem após POST:** o erro de validação em Configurações e o "link salvo" não foram vistos.
- **Contraste:** foi calculado por canvas sobre a pilha de fundos. Os valores de alertas e selos foram conferidos nos prints.
