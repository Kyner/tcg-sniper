# Oportunidades na área de negócio: números do período, ativas, quase lá, encerradas e histórico do produto

Data: 2026-10-20. Aprovado em conversa (brainstorming) com o usuário.

Sub-projeto B de três da fase 2 do site novo (A: fim da oportunidade, em produção desde 2026-10-20 21:50; B: oportunidades; C: mercado da LigaMagic). Usa as colunas que o A gravou (`motivo_encerramento`, `menor_preco`, `alertas`, `deixou_de_valer_em`, `em_risco_desde`) e o histórico de preço (nunca apagado).

## Problema

A área de negócio do site novo é um esqueleto ("Em construção"). O grupo só vê as oportunidades pelos alertas do WhatsApp: não há onde ver o que está aberto agora, o que passou, quanto rendeu o período, quais produtos caem de preço com frequência nem o que está perto de virar oportunidade. A informação estratégica é o que vai ser vendido aos assinantes; esta tela é a primeira vitrine dela.

## Decisões do usuário

- A área de negócio mostra **só dado de mercado** (oportunidades, preços, duração, recorrência, quase oportunidades). Números de bastidor (casamentos, IA, produtos monitorados) ficam na gestão (fase 3). Vale para o grupo hoje e para os assinantes amanhã.
- Número de destaque do período: **diferença bruta** (soma de Liga − Amazon), com a nota "antes de taxas e frete", ao lado de contagem, desconto médio, duração média e produtos distintos. Período padrão 7 dias; seletor 7, 30, 90 dias e tudo.
- Detalhe **por produto**: uma página por produto da Liga com a curva Amazon × Liga, as oportunidades como faixas no gráfico e o histórico delas (recorrência).
- **Quase oportunidade**: anúncio casado e elegível (vendedor aceito, Liga em dia) com desconto entre um piso configurável (padrão 10%) e o desconto mínimo, pela última leitura; sem alerta no WhatsApp.
- Abordagem 1: consultas na hora (sem tabelas de resumo), pacote neutro `tcg_sniper/consultas/`, rotas novas na API; gráficos com **Recharts**.

## Telas (`web/`)

### Oportunidades (`/`)

Substitui o "Em construção" (`AreaNegocio.tsx` sai). Exige `ver_oportunidades`; quem tem só `ver_area_negocio` cai em "sem acesso". De cima para baixo:

1. **Números do período** (`stats` do DaisyUI), com o seletor de período (`join` de botões): diferença bruta ("antes de taxas e frete"), oportunidades, desconto médio, duração média, produtos diferentes. Sem oportunidades no período: as médias mostram "—".
2. **Ativas agora** (cartões `card`): foto, produto, preço Amazon × Liga, desconto, "aberta há 2 h 10 min", selo "em risco" (`badge badge-warning`) quando `em_risco_desde` não é nulo, botões "Ver na Amazon" (link do anúncio) e "Histórico do produto". Sem ativas: "Nenhuma oportunidade aberta agora" e a data da última aberta. Recarrega a cada 60 s.
3. **Quase lá** (`table`): produto, desconto atual, "faltam R$ Y (Z%)", link para o produto. As mais próximas do mínimo primeiro, até 20 linhas, com "ver todas" (sem limite).
4. **Encerradas no período** (`table`, paginada, 25 por página): produto, abertura, duração, preço do alerta × menor preço, desconto, motivo (`badge`). Filtro por motivo. A linha leva à página do produto com a faixa da oportunidade em destaque (`?oportunidade=<id>`). Produto inativo: linha sem link.
5. **Oportunidades por dia** (barras, Recharts) no período, dias no fuso de Configurações → Geral.

### Produto (`/produtos/:id`)

Exige `ver_oportunidades`. Produto inexistente ou inativo: tela `NaoEncontrada`.

- Cabeçalho: foto, nome, edição, link da Liga, link do anúncio casado da Amazon (o de menor preço atual quando há mais de um), "Nª oportunidade em 30 dias".
- **Curva de preço** (Recharts, seletor de período, padrão 30 dias): linha da Amazon, linha da Liga ("a partir de") e do médio da Liga, linha tracejada do preço alvo (Liga × (1 − desconto mínimo)), faixas sombreadas (`ReferenceArea`) em cada oportunidade; a faixa vinda de `?oportunidade=` fica mais escura. Toque ou passar o mouse mostra data, preço e anúncio.
- **Histórico de oportunidades do produto** (`table`): abertura, duração, alertas, preço alertado, menor preço, motivo.
- Selo "quase lá" se o produto estiver na faixa agora.

Cores dos gráficos a partir das variáveis do tema do DaisyUI (`--color-primary`, `--color-secondary`, `--color-base-content`), lidas do CSS, para seguir os temas claro e escuro. No celular os cartões empilham, as tabelas viram listas e o gráfico ocupa a largura.

### Estados

Carregando: `Carregando`. Erro de rede: `alert alert-error` com "Tentar de novo". Vazio: textos próprios ("Nenhuma oportunidade nos últimos 7 dias", "Ainda não há leituras suficientes para a curva", "sem preço da Liga no período" na legenda). Oportunidade sem motivo (fechada antes do registro): selo "antes do registro". Ativa: duração até agora, selo "aberta".

## Consultas (`tcg_sniper/consultas/`)

Pacote neutro, importado pela API e pelo admin antigo (a fase 4 apaga o pacote `admin`).

- `catalogo.py`: o `admin/consultas_catalogo.py` movido sem mudança de comportamento; os imports do admin passam a apontar para cá. **Primeira tarefa.**
- `oportunidades.py` (recebem sessão, `agora` e o que precisarem da configuração; devolvem dataclasses):
  - `numeros_periodo(s, desde, agora)`: oportunidades **abertas** em `aberta_em >= desde` (todas, com `desde = None`), exceto `motivo_encerramento = casamento_desfeito` (alerta errado não é resultado). Diferença bruta = soma de `preco_liga − preco_alertado`; desconto médio = média de `desconto_pct`; duração = `coalesce(deixou_de_valer_em, fechada_em, agora) − aberta_em`, média; produtos distintos.
  - `por_dia(s, desde, agora, zona)`: contagem por dia de `aberta_em` no fuso, com os dias sem oportunidade como zero.
  - `ativas(s, agora)`: `fechada_em is null`, com produto, anúncio (título, link, imagem), preço atual (`preco_atual_amazon`), `preco_liga` da oportunidade, desconto, `aberta_em`, `em_risco_desde`, `motivo_risco`.
  - `encerradas(s, desde, motivo, pagina, por_pagina=25)`: `fechada_em is not null`, mais recentes primeiro, com total para a paginação.
  - `quase_la(s, regras, piso_pct, agora, limite)`: anúncios com casamento confirmado em produto ativo e sem oportunidade aberta; junta `preco_atual_amazon`, `preco_atual_liga` e o vendedor, monta `motor.Leitura` e `motor.RefLiga` como o monitor (mesmas funções de montagem, extraídas se preciso para não duplicar) e aplica `motor.motivo_inelegivel`. Entra quem dá `preco_subiu` ou `liga_caiu` e tem desconto ≥ `piso_pct`. Devolve desconto atual e quanto falta (R$ e pontos percentuais) para o desconto mínimo. Ordem: mais perto do mínimo primeiro.
  - `historico_produto(s, produto_id, desde, agora)`: cabeçalho; curva da Amazon = **menor preço por hora** entre os anúncios com casamento confirmado do produto, só leituras com preço e vendedor elegível (`motor.vendedor_elegivel`), com o anúncio do ponto; por dia quando o período passa de 90 dias; curva da Liga = `preco_listagem.preco_a_partir` e `resumo_preco.preco_medio` no período; preço alvo; faixas `[aberta_em, coalesce(deixou_de_valer_em, fechada_em, agora)]` das oportunidades do produto; recorrência = oportunidades abertas nos últimos 30 dias; situação "quase lá" atual.

Agregação no SQL (`date_trunc` no fuso), nunca carregar as leituras brutas na memória.

## Banco (migração nova)

- `config_amazon.quase_oportunidade_min_pct` integer NOT NULL default 10, `CHECK` 0–100. A validação da configuração exige `quase_oportunidade_min_pct < desconto_min_pct`. Campo no admin antigo em Configurações → Amazon → Monitor de preço, rótulo "Quase oportunidade a partir de (%)".
- Índice `ix_preco_amazon_anuncio_coletado` em `preco_amazon (anuncio_id, coletado_em)`.

## API (`api/rotas_oportunidades.py`)

Toda rota com `exige(Permissao.VER_OPORTUNIDADES)`. Dinheiro como texto decimal ("1299.90"), datas ISO 8601 com fuso, `periodo` em `7d | 30d | 90d | tudo` (outro valor: 400 no formato de erro padrão).

- `GET /api/oportunidades/resumo?periodo=`: números do período e a série por dia.
- `GET /api/oportunidades/ativas`
- `GET /api/oportunidades/encerradas?periodo=&motivo=&pagina=`
- `GET /api/oportunidades/quase?limite=` (sem `limite`: todas)
- `GET /api/produtos/{id}/historico?periodo=`: 404 para produto inexistente ou inativo.

**Nunca sai** na API de negócio: contagens de casamentos ou IA, id ou nome de vendedor, mensagens, conferência de checkout (itens, impostos, frete). O preço é o da oportunidade (o conferido quando houve conferência, igual ao do alerta). Os testes conferem a lista fechada de chaves de cada resposta.

## Permissão

`Permissao.VER_OPORTUNIDADES = "ver_oportunidades"`, rótulo "Ver oportunidades", descrição "Ver as oportunidades, o histórico dos produtos e as quase oportunidades na área de negócio." Padrão ligada para grupo, operador e admin; editável em Gestão → Acessos.

## Front: dependência e arquivos

- `recharts` com versão exata no `package.json`.
- Páginas `paginas/Oportunidades.tsx`, `paginas/Produto.tsx`; componentes `NumerosPeriodo`, `CartaoAtiva`, `TabelaQuaseLa`, `TabelaEncerradas`, `GraficoPorDia`, `CurvaPreco`, `SeletorPeriodo`; `formato.ts` (reais pt-BR, duração "3 h 20 min", data); rótulos dos motivos iguais aos dos avisos (`oportunidades/mensagens.ROTULOS_MOTIVO`); tipos do JSON em `tipos.ts`.
- Só componentes do DaisyUI 5 com classes literais; o gráfico é o único elemento fora do DaisyUI.

## Testes

- Consultas (Postgres de teste): números do período (inclui ativas, exclui `casamento_desfeito`, limites de período, duração por `deixou_de_valer_em`); por dia com dias vazios e fuso; quase lá (fica de fora: vendedor não elegível, Liga velha, abaixo do piso, com oportunidade aberta, produto inativo, casamento não confirmado; ordem); curva com dois anúncios (menor elegível por hora; vendedor não elegível ignorado) e agregação por dia acima de 90 dias; recorrência em 30 dias; encerradas com paginação e filtro.
- API: 401 sem sessão, 403 sem `ver_oportunidades`, formato e lista fechada de chaves, 404 do produto, 400 de período inválido.
- Migração: padrão 10, `CHECK`, índice criado; validação piso < mínimo.
- Admin antigo: campo do piso em Configurações.
- Front: Vitest das páginas (carregando, vazio, erro, dados, troca de período) e de `formato.ts`; ponta a ponta com Playwright (entrar, ver Oportunidades, abrir um produto); `scripts/verificar_layout.py` com as duas telas no celular e no computador, nos dois temas.

## Fora do escopo

- Alerta "quase lá" no WhatsApp.
- Tendências da LigaMagic (sub-projeto C).
- Margem líquida (taxas, frete, imposto).
- Assinantes: pagamento, planos e cadastro.
- Números de casamentos e IA (gestão, fase 3).
