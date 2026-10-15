# Admin com DaisyUI: visual moderno e responsivo

Data: 2026-10-15
Contexto: auditoria das 10 telas do admin (Pico CSS) em 1440 e 390 px; comparação Tabler × shadcn/ui × DaisyUI publicada em https://claude.ai/artifact/QXFT7X2ndM2gnbkoQcYVN3 (fontes em `.superpowers/estilos-admin/`).

## Objetivo

Todas as telas do admin modernas e usáveis no celular, construídas só com componentes e temas do DaisyUI. Nada de visual inventado.

Critério de sucesso: nas 10 telas, em 390 e 1440 px e nos dois temas, nada estoura a largura; a situação de cada coisa (serviço, coleta, mensagem, desconto, vendedor) se lê pela cor do selo; o menu lateral recolhe para ícones no computador e abre por botão no celular; nenhuma rota, filtro, botão ou mensagem muda de comportamento.

## Achados da auditoria que esta entrega resolve

- Todas as telas estouram no celular (783–880 px numa tela de 390): menu de 7 links numa linha e tabelas de 7–9 colunas.
- Estados em texto puro (ativo, falha, enviada), sem cor nem hierarquia; descontos negativos iguais aos positivos.
- Dashboard dominado pelo histórico; Configurações com 29 campos numa página de 5.000 px.
- Pico CSS sem personalização: links sublinhados em preços, "Pausar" com cara de desabilitado, paginação só com "próxima".

## Decisões de 2026-10-15

1. Framework: **DaisyUI** (sobre Tailwind), só componentes e temas dele; ícones do **Heroicons**.
2. Temas: **winter** (claro) e **night** (escuro), seguindo o aparelho, com botão para trocar.
3. Navegação: **menu lateral** (`drawer`) que recolhe para ícones no computador e abre por botão no celular.
4. Escopo: **todas as telas de uma vez**.
5. CSS: **gerado por script e versionado** no repositório (Tailwind standalone + DaisyUI 5), sem Node e sem mudar o Dockerfile.

## Fora do escopo

- Mudar rotas, filtros, ações, textos de mensagens ou regras de negócio.
- Framework JavaScript; o htmx continua onde já é usado (interruptor de monitorar do Catálogo).
- Logo ou identidade visual própria.

## Base técnica

- **`scripts/gerar_css`** (Python, roda com `uv run python scripts/gerar_css.py`):
  - baixa, numa pasta ignorada pelo git (`.ferramentas/`), versões fixas do executável standalone do Tailwind CSS v4 para o sistema atual e do `daisyui.mjs`/`daisyui-theme.mjs` do DaisyUI 5, conferindo o SHA-256 de cada arquivo contra valores gravados no script;
  - compila `src/tcg_sniper/admin/estilo.css` (entrada: `@import "tailwindcss"`, `@source` dos templates, `@plugin "daisyui"` com os temas `winter --default` e `night --prefersdark`) para `src/tcg_sniper/admin/static/admin.css`, minificado;
  - grava na primeira linha do CSS `/* templates: <sha256> */`, o hash do conteúdo de todos os templates e da entrada `estilo.css`, em ordem de nome.
- **Teste de CSS em dia:** recalcula o hash e falha com "CSS desatualizado: rode uv run python scripts/gerar_css.py" se diferir.
- **Arquivos estáticos:** o admin serve `src/tcg_sniper/admin/static/` em `/static` (`admin.css`, ícones). Sai o Pico CSS (CDN). O htmx continua (CDN, versão fixa como hoje).
- **Ícones:** os SVG do Heroicons (outline, 24 px) usados entram em `static/icones/` e são incluídos inline por uma macro (`icone(nome)`), para herdar a cor do texto.
- **Tema:** atributo `data-theme` no `<html>`: sem escolha salva, o DaisyUI segue o aparelho (winter/night); o botão do menu alterna e grava a escolha em `localStorage` (leitura protegida por try/catch; sem armazenamento, segue o aparelho). Um script mínimo no `<head>` aplica a escolha antes de pintar, para não piscar.
- **Menu lateral:** o padrão de drawer recolhível do DaisyUI 5 (`drawer lg:drawer-open` com a variante de barra só com ícones). Itens com ícone e nome; recolhido, só ícones com `tooltip`; estado recolhido lembrado em `localStorage`.
  - Contadores (selo no item; ponto `indicator` quando recolhido): **Casamentos** = produtos ativos com pendentes; **Ofertas** = oportunidades abertas; **Mensagens** = mensagens em falha + pendentes há mais de 30 min (só aparece se > 0).
  - Os contadores são lidos uma vez por requisição, na mesma dependência que já carrega a configuração (`request.state`), com consultas de contagem.

## Peças comuns (macros Jinja em `templates/_componentes.html`)

- **`selo(situacao)`** — `badge` com cor fixa por significado: verde (`badge-success`): ok, ativo, enviada, confirmado, rodando-ok; amarelo (`badge-warning`): parcial, pendente; vermelho (`badge-error`): falha, pausado, pausado por desafio/CAPTCHA; azul (`badge-info`): rodando, em andamento; cinza (`badge-ghost`): expirada, descartada, ignorado, não verificado, inativo.
- **`selo_desconto(pct, minimo)`** — verde se ≥ mínimo configurado, amarelo se > 0, vermelho (contorno) se ≤ 0.
- **Lista responsiva** — `table` (`table-zebra`) dentro de `card` a partir de `md`; abaixo, a mesma informação em `card`s empilhados. Valores em reais alinhados à direita com `tabular-nums`.
- **Filtros** — em linha (grid) no computador; no celular dentro de um `collapse` "Filtros" fechado por padrão (aberto se algum filtro está ativo).
- **Paginação** — `join` com números (atual, vizinhas, primeira e última) mantendo os filtros.
- **Avisos** — `alert` (`alert-warning`, `alert-error`, `alert-success` para mensagens de confirmação).
- **Cabeçalho de página** — título, subtítulo e ação principal à direita.

## Telas

- **Dashboard:** avisos no topo (serviço pausado, mensagens paradas); `stats` com LigaMagic, Amazon, WhatsApp, oportunidades abertas e casamentos pendentes (os dois últimos números são novos, de dados existentes), cada um com selo; histórico em `tabs` "Coletas da LigaMagic" | "Ciclos da Amazon" (filtro e paginação como hoje, separados por aba).
- **Serviços:** `card` por serviço (LigaMagic, Amazon, Notificador) com selo de estado, texto curto e os mesmos botões (primário: Rodar agora/Retomar; secundário legível: Pausar).
- **Catálogo:** filtros; bloco de ações em lote (mesma confirmação); lista responsiva; "Monitorar" vira `toggle` mantendo o htmx de hoje.
- **Casamentos:** filtros; lista responsiva com selos "oportunidade" e "sem par" e contagens pendentes/confirmados/ignorados.
- **Casamento de um produto:** `card` de topo (nome, link da Liga, "À partir de", campo "Colar link da Amazon"); `tabs` Pendentes | Confirmados | Ignorados com a contagem no rótulo, abrindo em Pendentes (ou em Confirmados se não houver pendentes); confirmados com selo de vendedor/envio.
- **Trocar:** `card` do anúncio (título com a opção da variação, ASIN, link); sugestões e resultado da busca como lista com nome, link da Liga, "À partir de" e botão Escolher.
- **Ofertas:** como na prévia aprovada: filtros, lista responsiva, `selo_desconto`, selo de vendedor (incluindo "não verificado").
- **Produto (catálogo):** `card` com os dados da Liga e o link; anúncios da Amazon confirmados em lista com selo de vendedor; históricos (Liga, Amazon) em `tabs`.
- **Mensagens:** filtros; lista responsiva com selo de situação, texto (duas primeiras linhas, resto expansível com `collapse`), tentativas, último erro, e Reenviar/Descartar.
- **Configurações:** `tabs` Geral | LigaMagic | Amazon, cada uma com o seu formulário e Salvar (como hoje); campos em 2 colunas no computador (pausas mínima e máxima lado a lado); ajuda de cada campo como texto auxiliar; erros com `input-error` e a mensagem abaixo. A aba com erro (400) abre selecionada; a mensagem de sucesso em `alert-success`. Rodapé com as variáveis que ficam no `.env`.

## Testes e verificação

- Todos os testes atuais continuam. Os que conferem textos e comportamento ficam iguais; os que conferem HTML exato do Pico (ex.: `<a href="/mensagens">Mensagens</a>`, `name="x" value="y"` contíguos) são ajustados ao HTML novo preservando o que provam (o item de menu existe; o campo tem o valor salvo).
- Novos: CSS em dia com os templates; `GET /static/admin.css` responde 200 com `text/css`; o menu lateral tem as 7 telas; contadores aparecem quando > 0 e somem em 0; o botão de tema existe; a aba com erro abre selecionada em Configurações.
- **`scripts/verificar_layout.py`** (roda no container do admin, não entra na suíte): abre as 10 telas em 390 e 1440 px, temas winter e night, com o menu recolhido e aberto; falha se `scrollWidth` > largura da janela ou se houver erro de script; salva os prints em `/tmp/verificar_layout/`. Roda antes do deploy.
- Deploy: `docker compose up -d --build admin`. Sem migração; coletores e notificador não mudam.
