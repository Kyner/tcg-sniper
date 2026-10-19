# Monitor de preço da Amazon, descoberta só para quem não tem par e checkout nas candidatas

Data: 2026-10-17
Contexto: hoje o coletor da Amazon busca todos os 224 produtos ativos de hora em hora e, na mesma visita, abre a página de cada anúncio confirmado para ler a oferta principal (buy box). O preço dos confirmados é atualizado no máximo de hora em hora, só a buy box é lida, e a IA avalia pendentes de produtos que já têm par.

Investigação em 2026-10-17 (conta do usuário, anúncio B0DNV55QBS, Aetherdrift Commander Deck - Eternal Might):

| Onde | Valor |
|---|---|
| Página do produto (buy box, Amazon Global) | R$ 314,11 |
| Lista de ofertas: Shazaar, a menor (FBA, envio dos EUA, "tributos de importação incluídos") | R$ 275,91 |
| Carrinho com essa oferta | R$ 275,91 |
| Checkout: itens / frete / "Taxas de importação incluindo ICMS" / total | R$ 237,73 / R$ 0,00 / R$ 48,26 / **R$ 285,99** |

O total do checkout bate com o pedido real do usuário no mesmo dia. Conclusões: a buy box nem sempre é a melhor oferta; a lista de ofertas traz todas as ofertas numa página leve; nas importadas o preço anunciado não é o final (o ICMS entra no checkout); o carrinho não muda o preço; descontos de cartão/cupom ("15% na 1ª compra com cartão Amazon", CARTAO15OFF) são condicionais.

## Objetivo

Achar oportunidades rápido e com o preço que o grupo de fato pagaria:
1. **Monitor de preço** dos anúncios confirmados, a cada 15 min (configurável), lendo todas as ofertas.
2. **Conferência de checkout** só das candidatas a oportunidade, para usar o total real.
3. **Descoberta** (busca + IA) só para produtos sem casamento confirmado, e uma busca semanal dos já casados.
4. **Origem do casamento** sempre visível: manual, sugerido pela IA ou automático pela IA.

Critério de sucesso: cada anúncio confirmado é lido no intervalo configurado dentro do horário do monitor; o alerta de oportunidade usa a melhor oferta elegível e, quando conferido, o total do checkout; o coletor nunca confirma um pedido nem mexe em itens do usuário no carrinho; a IA não avalia anúncios de produtos já casados fora da busca semanal; todo casamento mostra a origem.

## Decisões de 2026-10-17

1. Produto já casado volta a ser buscado **uma vez por semana**; os anúncios novos dessa busca passam pela IA normalmente.
2. Monitor **a cada 15 min, dentro do horário do monitor (padrão 08:00–22:00)**, com **configuração própria**, separada da busca.
3. O grupo **tem Amazon Prime** (conta logada): o preço considerado é o que a conta vê; o selo Prime é informativo.
4. **Lista de ofertas no monitor; checkout só nas candidatas.** Nunca checkout em toda leitura.
5. Origem do casamento gravada no anúncio: `manual`, `sugerido_ia`, `automatico_ia`.

## Fora do escopo

- Descontos condicionais (cupom, cartão Amazon, primeira compra): só mostrados como informação, nunca descontados.
- Comprar: o sistema nunca confirma pedido.
- Mercado Livre e outros sites.
- Monitor de madrugada.

## Coletor da Amazon: três trabalhos, um navegador

O serviço `coletor-amazon` continua com um navegador (perfil `perfil-amazon`, mesma conta) e escolhe o próximo trabalho por prioridade, respeitando a janela de cada um e o limite total de páginas por hora:

1. **Conferência de checkout** pendente (candidata nova ou com cache vencido).
2. **Monitor**: o anúncio confirmado com leitura mais antiga cujo intervalo venceu.
3. **Descoberta**: a fila de hoje (`fila_amazon`), restrita a produtos ativos **sem casamento confirmado** (intervalo `intervalo_busca_min`, como hoje) **ou** casados cuja última descoberta tem 7 dias ou mais.

O passo de hoje de abrir a página de cada confirmado durante a busca (`_confirmar` e `confirmados_ausentes` em `coletor_amazon/busca.py`) sai: o monitor é o único que lê preço de confirmado. A busca continua gravando anúncios novos (pendentes) e o preço de origem `busca`.

O casador (`casador/servico.py`) passa a pular pares cujo produto já tem anúncio confirmado, exceto anúncios vistos pela primeira vez depois da última descoberta semanal desse produto (os novos da busca semanal). Os pulados ficam pendentes e visíveis em Casamentos.

## Monitor de preço

- Lê a lista de ofertas do ASIN (endpoint do painel "Outras opções de compra", o mesmo que a página carrega). A URL exata e os seletores saem das páginas reais salvas (ver Fixtures).
- Para cada oferta: vendedor (nome e id), preço, preço "De:" quando houver, condição (novo/usado), quem envia (Amazon/lojista), origem do envio (ex.: Estados Unidos), importada (selo "Compra internacional" ou "Origem do envio" fora do Brasil), Prime, avaliação do vendedor (% positivas e nº) quando o painel mostrar.
- Vendedor sem avaliação no painel é avaliado como hoje (página do vendedor, com o mesmo `vendedor_reavaliar_dias`).
- **Melhor oferta elegível**: a de menor preço entre as ofertas novas cujo vendedor é aceito pelas regras de hoje (Amazon, ou FBA com vendedor confiável). Ela vira a linha de `preco_amazon`/`preco_atual_amazon` da leitura (origem nova `ofertas`), de modo que histórico, Ofertas, casamento e motor de oportunidade continuam funcionando sobre o mesmo dado.
- Anúncio sem nenhuma oferta (indisponível): registra preço nulo como hoje.

## Conferência de checkout

- **Candidata**: melhor oferta elegível com desconto anunciado ≥ (`desconto_min_pct` − `margem_candidata_pp`), padrão margem 5 pontos.
- **Cache**: uma conferência ok vale `checkout_validade_h` (padrão 6 h) para o mesmo ASIN + vendedor + preço anunciado.
- **Passos** (módulo `coletor_amazon/checkout.py`):
  1. Abrir o carrinho. **Se houver qualquer item no carrinho ativo, não conferir** (situação `carrinho_ocupado`). Itens em "salvo para depois" não contam e nunca são tocados.
  2. Adicionar a oferta pelo botão "Adicionar ao carrinho" dela na lista de ofertas.
  3. Ir para o checkout ("Fechar pedido").
  4. Se pedir o endereço, escolher o endereço padrão ("Entregar neste endereço").
  5. Ler do resumo: itens, frete, impostos (linha de "Taxas de importação"/ICMS quando houver), total.
  6. Voltar ao carrinho e excluir o item adicionado.
- **Nunca** usar "Comprar agora" (pode fechar o pedido com 1-Clique).
- **Lista fixa de cliques**: o módulo só clica em seletores de uma lista de permitidos (adicionar ao carrinho da lista de ofertas, fechar pedido, entregar neste endereço, excluir do carrinho). Uma **lista proibida** (botões de confirmar/finalizar pedido: `placeOrder`, `placeYourOrder`, textos "Confirmar pedido", "Finalizar pedido", "Comprar agora", "Fazer pedido") é verificada antes de todo clique; um teste prova que nenhum caminho clica num proibido.
- Página fora do esperado em qualquer passo: parar, registrar `falha` com o motivo e tentar excluir o item.
- Item que ficou no carrinho por falha: a próxima volta do coletor tenta excluir de novo (registrado no `conferencia_checkout`).
- **Sem login** (checkout redireciona para entrar na conta): situação `sem_login`; a conferência fica desligada até alguém retomar em Serviços; aviso no Dashboard e uma mensagem no WhatsApp ("logue a conta Amazon no noVNC, porta 6081"). O monitor continua.

## Oportunidade e mensagens

- O motor de oportunidades usa o **total do checkout** quando há conferência ok válida para a melhor oferta; senão o preço anunciado.
- A mensagem do WhatsApp mostra: preço final conferido (itens + impostos, sem frete; frete mostrado à parte; corrigido em 2026-10-19, regra do usuário) ou "preço anunciado, não conferido (<motivo>)"; vendedor; "importado (EUA)" quando for; Prime; e, se houver, o desconto condicional como informação ("cupom: 15% na 1ª compra com cartão Amazon").
- Uma oportunidade aberta com preço anunciado é atualizada quando a conferência chegar (sem novo alerta, a menos que o desconto confirmado caia abaixo do mínimo, caso em que ela fecha).

## Origem do casamento

- Coluna `AnuncioAmazon.origem_casamento` (`manual` | `sugerido_ia` | `automatico_ia`, nula enquanto pendente), gravada em toda decisão:
  - automático do casador → `automatico_ia`;
  - usuário confirma/ignora um anúncio que tinha avaliação da IA para o par → `sugerido_ia`;
  - usuário decide sem avaliação, ou cola link → `manual`;
  - desfazer limpa a origem.
- Migração preenche os existentes: `automatico_ia` onde a avaliação tem `aplicada_em = revisado_em`; `sugerido_ia` onde há avaliação do par; senão `manual`.
- Selo de origem em Casamentos (tela do produto, confirmados e ignorados), na lista de ofertas do produto e em Ofertas. O selo "pela IA" atual é substituído por ele.

## Dados (uma migração)

- `oferta_amazon`: id, `anuncio_id`, `lida_em`, `vendedor_id` (FK `vendedor_amazon`, nulo se não identificado), `vendedor_nome`, `preco`, `preco_de`, `condicao`, `envio` (`Envio`), `origem_envio`, `importada`, `prime`, `elegivel`, `melhor`. Índice (`anuncio_id`, `lida_em`). Guarda todas as ofertas de cada leitura (limpeza das leituras com mais de 30 dias, como a tabela de mensagens).
- `conferencia_checkout`: id, `em`, `anuncio_id`, `vendedor_nome`, `preco_anunciado`, `itens`, `frete`, `impostos`, `total`, `situacao` (`ok` | `falha` | `carrinho_ocupado` | `sem_login`), `motivo`, `item_removido` (bool).
- `OrigemPreco` ganha `ofertas`.
- Última descoberta: usa `FilaAmazon.ultima_busca_em`, que já existe (sem coluna nova).
- `AnuncioAmazon.origem_casamento` (enum, nulo).
- `config_amazon` ganha: `monitor_ligado` (true), `monitor_intervalo_min` (15), `monitor_janela_inicio` (08:00), `monitor_janela_fim` (22:00), `monitor_max_paginas_hora` (150), `checkout_ligado` (true), `margem_candidata_pp` (5), `checkout_validade_h` (6), `descoberta_casados_dias` (7).
- `config_amazon.checkout_sem_login_em` (data, nula): preenchida quando o checkout pede login; enquanto preenchida a conferência não roda; "Retomar conferência" em Serviços limpa. `estado_coletor` não muda.

## Admin

- **Configurações → Amazon**: seção "Monitor de preço" com os campos novos (validação como as demais).
- **Ofertas**: preço com "conferido no checkout: R$ X (impostos R$ Y)" ou "não conferido"; selos "importado (EUA)", "Prime", origem do casamento.
- **Casamento do produto e página do produto**: cada anúncio confirmado com a tabela de ofertas da última leitura (vendedor, preço, envio, importado, Prime, elegível), a melhor marcada; selo de origem.
- **Logs**: aba "Checkout" (quando, anúncio, vendedor, anunciado, itens, frete, impostos, total, situação, motivo) e aba "Monitor" (leituras recentes com nº de ofertas e melhor preço).
- **Dashboard**: card Amazon mostra monitor (última volta, atraso) e conferência (ligada, sem login); aviso quando o monitor não cabe no intervalo ou a conta está sem login.
- **Serviços**: card Amazon ganha liga/desliga do monitor e da conferência de checkout (e "Retomar conferência" após `sem_login`).

## Fixtures (antes de implementar)

- Salvar pelo navegador do coletor (com login), para 2–3 anúncios (o importado B0DNV55QBS, um vendido pela Amazon Brasil e um FBA nacional): lista de ofertas, carrinho com um item, checkout no resumo (antes de confirmar), carrinho vazio, e a página de login para onde o checkout redireciona sem sessão.
- **Privacidade (repositório público)**: as páginas de carrinho e checkout trazem nome, endereço, CPF e final do cartão. O recorte troca esses dados por fictícios antes de salvar em `tests/fixtures/amazon/`; um teste falha se aparecer CEP, CPF, final de cartão ou nome reais (lista de valores proibidos lida de um arquivo fora do git, ou padrões genéricos de CPF/CEP/cartão).

## Testes

- Parser da lista de ofertas (fixtures reais): preço, vendedor, envio, origem, importada, Prime, condição, "De:".
- Parser do resumo do checkout: itens, frete, impostos, total; página de login detectada.
- Checkout: só cliques permitidos; nunca proibidos (teste que injeta um botão proibido no lugar do esperado e verifica que nada é clicado); carrinho ocupado pula; item removido mesmo com falha no meio; retentativa de remoção.
- Fila: checkout > monitor > descoberta; janela própria do monitor; limite por hora somado; monitor atrasado avisa; descoberta só de não casados e casados com 7+ dias.
- Casador: pula pares de produtos casados, exceto anúncios novos da busca semanal.
- Melhor oferta elegível e gravação em `preco_amazon` com origem `ofertas`; oportunidade com total conferido e com "não conferido".
- Origem do casamento em todos os caminhos e na migração.
- Admin: telas novas e selos; configurações validadas.
- `test_migracao_igual_aos_modelos` e `test_css_em_dia_com_os_templates` continuam passando.

## Implantação

- Backup antes (migração). Deploy de `migrate`, `coletor-amazon`, `casador`, `admin`, `notificador` se as mensagens mudarem.
- O usuário loga a conta Amazon no noVNC (porta 6081) antes de ligar a conferência; sem login ela fica em `sem_login` e o monitor funciona.
