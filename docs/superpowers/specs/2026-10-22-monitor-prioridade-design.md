# Monitor da Amazon com prioridade por grupo, e lista "Esgotado na Liga · analisar"

Data: 2026-10-22. Aprovado em conversa (brainstorming) com o usuário.

## Problema

O monitor relê a lista de ofertas de cada anúncio confirmado (de produto ativo) sempre pelo de leitura mais antiga, sem olhar o preço. Em 2026-10-22 eram 615 anúncios confirmados; com pausas de 8–20 s o navegador logado lê ~257 páginas por hora, então cada anúncio era relido a cada ~2 h (o painel acusava 473 anúncios com leitura vencida e "precisa de 2.084 páginas por hora"). O usuário disse que **oferta boa some em ~30 min**: ler tudo no mesmo ritmo faz a queda de preço ser vista tarde demais. Quase todos os anúncios estão longe de virar oportunidade (427 eram mais caros que a Liga), e a leitura é gasta neles.

Retrato de 2026-10-22 (anúncios confirmados de produtos ativos): 18 com 20% ou mais de desconto (oportunidade), 14 entre 10% e 20%, 22 entre 0% e 10%, 427 mais caros que a Liga, 15 nunca lidos pelo monitor, 119 com preço na Amazon e **sem preço "a partir de" na Liga** (ninguém vendendo; em 100 deles a Liga mostra a média de venda).

Medida provisória em produção desde 2026-10-22: intervalo do monitor em 30 min (era 15). Sai com esta entrega (volta para 15, ver "Implantação").

## Decisões do usuário

- Gastar a leitura **onde ainda dá para achar algo novo**.
- **Fila rápida, a cada 15 min:** anúncios **perto do desconto** (desconto entre o piso do "quase lá", 10%, e o desconto mínimo, 20%) **e as oportunidades abertas** (para o fim da oportunidade e o novo aviso de queda saírem a tempo).
- **Resto com preço na Liga** (de 0% a 10% de desconto e os mais caros que a Liga): **com a sobra** da capacidade.
- **Esgotado na Liga** (preço na Amazon, sem "a partir de" na Liga): ler **1 vez por semana**; **não** alerta no WhatsApp; aparece numa **lista para analisar** no **Catálogo** da gestão.
- Nunca lidos: lidos primeiro (como hoje).
- A linha de "perto" é o **piso do "quase lá"** que já existe (Configurações → Amazon, padrão 10%).

## Grupos e ordem de leitura

O desconto de um anúncio, para escolher o grupo, é **só preço**: o preço atual da Amazon (`preco_atual_amazon.preco`) contra o "a partir de" atual da Liga, com a mesma conta de `motor.desconto_pct`, pela última leitura. **Não** passa pelo filtro de elegibilidade do "quase lá" e da oportunidade (vendedor aceito, idade do preço da Liga): a melhor oferta pode trocar de vendedor na leitura seguinte, e o monitor existe justamente para descobrir isso (chamada minha; o retrato de 32 rápidos foi contado assim). Preço da Liga velho (coleta da Liga parada) continua "com preço" e vai para o grupo pelo desconto; problema na coleta da Liga tem aviso próprio (chamada minha).

A "leitura do monitor" (nunca lido, vencimento, ordem, mais antiga) é `anuncio_amazon.monitor_lido_em`, gravado a cada leitura das ofertas; a busca pode trocar o preço atual (quando a leitura do monitor tem mais de 2 intervalos) sem mexer nesse prazo. O grupo continua decidido pelo preço atual, qualquer que seja a origem (revisão final).

Regras de desempate (chamadas minhas, coerentes com o que o usuário pediu):
- **Oportunidade aberta sempre fica no grupo rápido**, mesmo que a Liga fique sem preço ou o desconto caia, até ela fechar (o fim da oportunidade depende de leitura nova).
- O grupo é por anúncio (o par confirmado é um só por anúncio): vários anúncios do mesmo produto esgotado ficam todos no grupo "esgotado".
- `config_amazon` tem um registro só (id 1).

| Grupo | Quem | Vence quando |
|---|---|---|
| 1. Nunca lidos | confirmado sem leitura do monitor | sempre (já está vencido) |
| 2. Rápido | oportunidade aberta no anúncio **ou** desconto ≥ piso do "quase lá" | leitura mais velha que `monitor_intervalo_min` (15) |
| 3. Esgotado na Liga | com preço na Amazon e sem "a partir de" na Liga | leitura mais velha que `monitor_esgotado_dias` (7) |
| 4. Lento | todo o resto com preço na Liga | leitura mais velha que `monitor_intervalo_min` (piso, para não reler à toa quando sobra capacidade) |

`proximo_do_monitor` escolhe, nesta ordem: o grupo 1 (mais antigo primeiro), o grupo 2 vencido (leitura mais antiga primeiro), o grupo 3 vencido, e só então o grupo 4 vencido (leitura mais antiga primeiro). O teto de páginas por hora e a janela de horário continuam valendo para tudo. Um anúncio muda de grupo pela leitura seguinte: se cair para o "quase lá", entra no rápido; se subir, volta ao lento; se a Liga voltar a ter "a partir de" (o coletor da Liga é que descobre), sai do esgotado.

Com os números de 2026-10-22: o rápido (32) pede ~128 páginas/h; o lento (449) fica com a sobra, ~1 leitura a cada ~3h30; o esgotado (119) ~1 página/h.

## Configuração

- `monitor_intervalo_min` continua sendo o ritmo da fila rápida; o rótulo passa a "Fila rápida: ler a cada (min)" e a explicação diz quem entra nela.
- Novo `monitor_esgotado_dias` em `config_amazon` (padrão 7, de 1 a 30), em Configurações → Amazon → Monitor de preço: "Esgotado na Liga: ler a cada (dias)". Migração com o valor padrão.
- O piso do "quase lá" (`quase_oportunidade_min_pct`) já existe e passa a decidir também o grupo rápido; a explicação do campo diz isso.

## Painel, avisos e tela do monitor

- `situacao_monitor` passa a contar por grupo (quantos em cada um e quantos vencidos). O "vencido" do aviso "monitor atrasado" e do "N na fila" passa a ser **só o do grupo rápido** (e o dos nunca lidos): o lento não tem prazo, e o esgotado vence por dias.
- O aviso "o monitor precisa de X páginas por hora…" passa a fazer a conta só com o grupo rápido (`rápidos × 60 / intervalo`) e compara com o teto e com a capacidade estimada pelas pausas (3600 / pausa média).
- A tela de Serviços (card do monitor, admin antigo) e o Dashboard mostram as quatro contagens em uma linha ("rápida 32 · lenta 449 · esgotado 119 · nunca lidos 15"), e de quanto em quanto tempo o lento está sendo relido (leitura mais antiga do grupo lento).
- "Rodada do monitor concluída" (`_Rodada` em `varredura_monitor.py`, aviso no grupo admin): a volta passa a ser **a dos grupos 1 e 2** (todos os rápidos e nunca lidos lidos uma vez); o lento e o esgotado não entram na volta. O texto do aviso diz quantos lentos e esgotados foram lidos durante a volta (contador em memória da própria volta, como `lidos` hoje). Sem nenhum rápido nem nunca lido, não há volta e não sai aviso (evita aviso em laço); chamada minha. Revisão final: com a volta só da fila rápida ela fecha a cada ~15 min, então as voltas se somam em memória e sai **no máximo um aviso por hora** (o primeiro na hora), começando por "Voltas da fila rápida: N"; as quedas de preço contam em qualquer grupo.

## Lista "Esgotado na Liga · analisar" (Catálogo da gestão)

- No Catálogo novo (`/gestao/catalogo`), o filtro "Preço na Liga" ganha a opção **"esgotado (com anúncio casado)"**: produto ativo, sem "a partir de" na Liga e com anúncio confirmado com preço na Amazon.
- Com esse filtro, cada linha mostra também: menor preço da Amazon entre os confirmados, **média de venda da Liga** (`preco_medio`), a diferença em % contra a média (positiva = Amazon mais barata), e **desde quando a Liga está sem vendedor** (a última coleta de listagem em que o produto teve "a partir de", pelo histórico `preco_listagem`, que nunca é apagado; "sem registro de preço" se nunca teve; a data é aproximada, da coleta, não do momento exato). Ordem padrão nesse filtro: maior diferença contra a média primeiro; sem média de venda, no fim.
- Sem alerta no WhatsApp. A página do produto de gestão mostra o selo "Esgotado na Liga" quando for o caso.
- Permissão: `ver_catalogo` (como o Catálogo).

## Fora do escopo

- Mudar a regra da oportunidade, do alerta ou do checkout (continuam iguais; o checkout só confere quem tem leitura recente, e quem entra no rápido é relido a cada 15 min).
- Ler os não casados (a busca cuida deles).
- O item "precisa de você" do Dashboard novo para os esgotados (entra na 3B).

## Implantação

Migrações (`monitor_esgotado_dias` e `anuncio_amazon.monitor_lido_em`, preenchida pela última leitura das ofertas) ⇒ backup antes. Depois do deploy, voltar `monitor_intervalo_min` para 15 (estava em 30 provisoriamente). Conferir no dia: contagens por grupo no card do monitor, aviso de atraso só com o grupo rápido, e a lista de esgotados no Catálogo.

## Testes

- `proximo_do_monitor`: ordem entre os grupos; oportunidade aberta abaixo do piso continua no rápido; anúncio que cruza a linha muda de grupo na leitura seguinte; esgotado só vence depois dos dias; lento não é relido antes do intervalo mesmo com capacidade sobrando; piso do "quase lá" alterado muda o grupo.
- `situacao_monitor` e os dois avisos do painel com as contagens por grupo.
- `_Rodada`: a volta conclui quando os rápidos e nunca lidos foram lidos, sem esperar os lentos.
- Catálogo: filtro "esgotado", colunas e ordem; API e front.

## Deixado ao construtor

Como calcular o grupo em SQL (uma expressão `case` reaproveitando a regra do desconto) ou em Python; como medir "desde quando sem vendedor" (histórico de `preco_listagem`/`resumo_preco`); o texto exato das linhas do card; se o filtro do Catálogo é uma opção do "Preço na Liga" ou um filtro próprio, desde que fique uma escolha só.
