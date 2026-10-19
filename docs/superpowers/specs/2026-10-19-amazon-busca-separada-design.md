# Coletor da Amazon: busca separada do monitor

Data: 2026-10-19. Aprovado em conversa (brainstorming) com o usuário.

## Problema

O `coletor-amazon` é um serviço com **um navegador** logado na conta da Amazon. O laço `passo()` (`coletor_amazon/varredura.py`) faz uma coisa por vez, por prioridade estrita: retirada do carrinho → conferência de checkout → monitor de preço → busca (descoberta). A busca só roda quando o monitor não tem anúncio vencido.

Desde 2026-10-18 07:52 o monitor passou de ~40 para 49 anúncios confirmados; a ~20 s por leitura, uma volta leva ~16 min, mais que `monitor_intervalo_min` = 15, então sempre há anúncio vencido e a busca quase nunca roda (7 buscas em 2026-10-19; em 2026-10-17 eram ~200/h). Resultado: dos 1969 produtos ativos sem candidato, **1941 nunca foram buscados**. Efeito colateral: o aviso "rodada do monitor" sai a cada brecha, com rodadas sem sentido ("2 h 4 min, 397 lidos").

## Decisões do usuário

- Separar busca e monitor em **dois serviços** (funções distintas).
- A busca roda **sem login** (navegador próprio, perfil próprio); monitor, checkout e retirada continuam no navegador logado.
- Tetos: **busca 90 páginas/h + monitor 180 páginas/h** (~270/h somados no mesmo IP), ajustáveis em Configurações → Amazon.
- Nenhum ajuste provisório em produção até a separação entrar.

## Arquitetura

### Serviços

- **`coletor-amazon-busca`** (novo): comando `tcg-sniper coletor-amazon-busca`; perfil do Chromium `/data/perfil-amazon-busca` (sem login); noVNC na porta host `6082` (mesmo arranjo do `coletor-amazon`: tini, hostname fixo para o SingletonLock, `shm_size`); faz só a busca (fila, termos alternativos, pares, ciclos de busca); trava própria (`lock_coleta` com um ID novo) para nunca rodar duas instâncias.
- **`coletor-amazon`** (atual): perfil `/data/perfil-amazon` (logado), noVNC `6081`; faz retirada do carrinho, conferência de checkout e monitor; não faz mais busca.

### Código

- `varredura.py` vira dois laços pequenos sobre as funções de hoje:
  - `varredura_busca.py`: o passo de descoberta (sincronizar fila, próximo da fila, termos, `processar_produto`, reagendar, ciclos, pausa por falhas).
  - `varredura_monitor.py`: retirada, conferência, monitor, rodada do monitor, limpeza diária de ofertas.
- O comum aos dois (janela com jitter, `TetoPorHora`, pausa entre páginas, abrir/fechar navegador, tratamento de CAPTCHA/erro/pausa por erros seguidos, avisos com origem) vai para um módulo base compartilhado (`varredura_base.py`), sem duplicar lógica.
- O laço da busca **não importa** checkout, carrinho nem monitor; o do monitor não importa a busca (teste de importação garante).

### Configuração (Configurações → Amazon)

- `janela_inicio`/`janela_fim` e `max_buscas_hora`: só da busca. Migração ajusta `max_buscas_hora` para **90** (se o valor atual for maior).
- `monitor_janela_*` e `monitor_max_paginas_hora`: do monitor (inclui checkout e retirada). Migração ajusta para **180** (se maior).
- A tela explica que são dois navegadores e que a Amazon vê a soma dos dois tetos.

### Estado, Serviços, Dashboard, vigia e avisos

- `estado_coletor`: nova linha `amazon_busca` (ativa). A linha `amazon` passa a significar monitor + checkout.
- Serviços: card novo "Amazon (busca)" com liga/desliga e "Retomar" próprios; o atual vira "Amazon (monitor e checkout)".
- Dashboard: dois cards de serviço; o da busca mostra buscas na última hora e produtos ativos nunca buscados.
- Vigia (`avisos/vigia.py`) e batida de vida (`sinal_servico`): serviço `amazon_busca` incluído.
- Avisos: CAPTCHA, pausada e erro inesperado carregam a origem no título ("Amazon (busca) · CAPTCHA" / "Amazon (monitor) · CAPTCHA") e chaves separadas, com "resolvido" próprio; o CAPTCHA da busca indica o noVNC 6082. Aviso de busca concluída/parcial/falhou continua (agora do serviço de busca). Rodada do monitor: só sai quando uma volta inteira termina (todos os anúncios vencidos lidos e nenhum vencido restante), não a cada brecha.

## Migração (uma revisão Alembic, após a head atual)

- Insere `estado_coletor` `amazon_busca` (ativo) se não existir.
- `config_amazon.max_buscas_hora = least(max_buscas_hora, 90)`; `monitor_max_paginas_hora = least(monitor_max_paginas_hora, 180)`.
- Ciclo de busca "rodando" no deploy é fechado como interrompido (como hoje).
- Downgrade remove a linha e não mexe nos tetos.

## Erros

- CAPTCHA/erro/pausa num serviço não para o outro.
- Busca desligada em Serviços: monitor segue; o vigia ignora serviço pausado.
- Tetos independentes; nenhum empresta vaga ao outro.
- Fila de busca persiste no banco; reinício retoma do vencido há mais tempo.
- Primeiro CAPTCHA provável no navegador novo sem login: aviso no grupo admin com o noVNC 6082; o monitor não para.

## Deploy

Seguindo o `CLAUDE.md`: parar os serviços, backup, `docker compose up -d --build` (todos), conferir os dois serviços da Amazon no ar, a migração aplicada e o noVNC 6082 abrindo.

## Testes

- Reprodução do problema: com o monitor sempre com anúncio vencido, a busca roda (serviços separados).
- Cada laço respeita teto e janela próprios.
- Laço da busca não chama checkout/carrinho/monitor; laço do monitor não chama a busca (teste de importação + comportamento).
- Avisos com origem certa e "resolvido" separado; card e liga/desliga de "Amazon (busca)"; vigia inclui `amazon_busca`.
- Rodada do monitor só ao fim de uma volta inteira.
- Migração: cria a linha, ajusta tetos sem subir valor menor do usuário, downgrade.
- Suíte atual verde, reorganizada nos dois laços.

## Pendências geradas

- Acompanhar CAPTCHA com ~270 páginas/h somadas (baixar tetos se aumentar).
- Acompanhar quantos produtos ativos ainda não foram buscados.
