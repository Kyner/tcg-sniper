# Pacote de pequenas que afetam o uso — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar os 13 itens da seção 2 do `docs/PENDENCIAS.md` que o usuário percebe no uso (login, Casador, idioma, produto desativado, avisos, vigia, fim da oportunidade, LigaMagic).

**Architecture:** Uma migração com todas as colunas novas (Task 1); depois uma tarefa por área, cada uma com seus testes. Nada de tela nova além do botão "definir idioma" na revisão de casamentos. Sem mudar regra de negócio fora do decidido abaixo.

**Tech Stack:** Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic + Postgres; React + Vite + TS + DaisyUI 5 + Vitest.

**Spec:** sem spec própria. Decisões do usuário nesta conversa (2026-10-26/27): fazer o pacote "pequenas que afetam o uso" antes da 3C; **desativar um produto solta os anúncios confirmados nele**; login aceita o celular sem o 9 extra (decidido em 2026-10-19, `PENDENCIAS.md`). Itens de origem: `docs/PENDENCIAS.md` seção 2 (linhas citadas em cada tarefa).

## Global Constraints

- Textos, docstrings, comentários e telas em português; commits em inglês `tipo: descrição`, **sem** `Co-Authored-By`, `Claude-Session` ou "Generated with".
- Histórico de preço nunca é apagado (`preco_amazon`, `resumo_preco`, `preco_listagem`, `preco_atual_*`, `avaliacao_ia`, `oportunidade`).
- Testes no Postgres de teste (`127.0.0.1:5433`, bancos `tcg_test*`); nunca a 5432. Ruff com `uvx ruff check src tests`.
- O admin antigo segue funcionando (é produção até a fase 4); os testes de `tests/admin/` só mudam se o comportamento novo decidido aqui exigir.
- Nada em `tcg_sniper/consultas/` nem `tcg_sniper/gestao/` importa `tcg_sniper.admin`.
- DaisyUI 5 só com classes literais.
- Há migração: o deploy pede **backup do banco antes** (`docs/IMPLANTACOES.md`).
- Cada tarefa marca seus itens como feitos no `docs/PENDENCIAS.md` (tira da seção 2 e põe uma linha em "Concluídas › Pacote de pequenas (2026-10-27)" com o commit).

## Decisões deste plano (chamadas do controlador, conferir com o usuário no fim)

1. **Oportunidade de produto desativado**: encerra com motivo novo `PRODUTO_DESATIVADO`, **sem aviso no grupo de oportunidades** ("Alerta corrigido" daria a entender que o casamento estava errado). Custo se errado: um aviso a mais ou a menos.
2. **Idioma dos casamentos antigos**: coluna nova `anuncio_amazon.idioma` (mesmos valores de `IDIOMAS_ANUNCIO`), definida à mão ou por comando; a regra "português confirmado" usa `coalesce(anuncio.idioma, avaliação.idioma_anuncio)`. Comando `tcg-sniper casamento definir-idioma [--aplicar]` preenche os confirmados sem idioma pela heurística do título (`consultas/variacao.py`); o que a heurística não decide fica listado. Botão "definir idioma" (pt, en, ja, outro) no cartão do anúncio confirmado na revisão de casamentos (gestão). Sem chamada paga à IA. Custo se errado: alguns ficam para você definir à mão.
3. **Serviço parado de propósito**: o vigia ignora serviço cujo último sinal foi um desligamento limpo (SIGTERM). Queda continua avisando. Custo se errado: um `docker stop` de verdade problemático fica silencioso (o card de Serviços ainda mostra).
4. **Lembrete de bloqueio que só espera**: um passo no laço da `manutencao` (já roda a cada minuto) manda o lembrete dos avisos abertos dos tipos que esperam, sem mexer em `ocorrencias`, com o texto do catálogo (sem as linhas do evento original). Custo se errado: o lembrete é mais genérico que o aviso original.
5. **"Mensagem não enviada"** fecha quando não há mais falha na janela (`falhas_recentes` vazia, sem contar os próprios avisos) ou quando a falha é reenviada/descartada.
6. **Produto novo da Liga que sempre falha**: depois de **3** falhas seguidas de página sai dos "novos do dia" e vai para o rodízio; uma leitura boa zera a contagem.
7. **Pausas em dobro**: contam os desafios das **últimas 24 h** (não do dia do calendário); "parada até amanhã" segue no dia do calendário.

## Review Focus

1. **Login com e sem o 9** dá o mesmo hash, os mesmos limites e o mesmo usuário; número sem o 9 que não existe com o 9 continua "sem cadastro" com o mesmo tempo de resposta. Teste na Task 2.
2. **Desativar em lote 400 produtos** solta os confirmados de todos numa transação, sem 500 e sem mandar aviso ao grupo; reativar deixa os pares pendentes para a IA reavaliar. Teste na Task 5.
3. **Reinício do Casador no meio da espera** de um par que falhou não gera chamada nova antes do fim da espera. Teste na Task 3.
4. **Lembrete de aviso aberto** não sai para tipo desligado em Configurações → Avisos nem duplica com o lembrete normal de repetição. Teste na Task 6.
5. **Serviço que cai (sem SIGTERM)** continua gerando `SERVICO_SEM_SINAL`; o batimento no laço não derruba o laço se o banco falhar. Teste na Task 7.

---

### Task 1: Migração com as colunas novas

**Files:**
- Create: `src/tcg_sniper/db/migrations/versions/<rev>_pacote_pequenas.py` (down_revision `d6a2f8c4b1e9`)
- Modify: `src/tcg_sniper/db/models.py`
- Test: `tests/db/test_migracao_pacote_pequenas.py`

**Interfaces:**
- Produces (todas anuláveis ou com padrão, sem reescrever dados):
  - `casamento.ia_falhas int not null default 0`, `casamento.ia_espera_ate timestamptz null`, `casamento.ia_falha_assinatura text null` (Task 3).
  - `fila_amazon.termos_falhas int not null default 0`, `fila_amazon.termos_espera_ate timestamptz null` (Task 3).
  - `anuncio_amazon.idioma text null` com o mesmo CHECK de `avaliacao_ia.idioma_anuncio` (`IDIOMAS_ANUNCIO`, `models.py:833`) (Task 4).
  - `sinal_servico.encerrado_em timestamptz null` (Task 7).
  - `oportunidade.alerta_enviado boolean not null default false` e índice em `oportunidade.mensagem_alerta_id` (Task 8; o índice é o item da linha 70 da seção 2).
  - `estado_coletor.retomado_desafio_em timestamptz null` (Task 9).
  - `produto_liga.falhas_pagina int not null default 0` (Task 9).
  - Motivo novo `PRODUTO_DESATIVADO` em `MotivoEncerramento` (se houver CHECK no banco para o motivo, a migração o atualiza) (Task 5).

- [ ] **Step 1:** teste da migração no molde de `tests/db/test_migracao_*.py`: upgrade cria cada coluna (tipo, nulo, padrão), o CHECK de idioma e o índice; downgrade remove tudo; dados existentes intactos.
- [ ] **Step 2:** rodar e ver falhar: `uv run pytest tests/db/test_migracao_pacote_pequenas.py -q`.
- [ ] **Step 3:** migração e modelos.
- [ ] **Step 4:** `uv run pytest tests/db -q` → PASS; `alembic heads` com uma cabeça só.
- [ ] **Step 5:** commit `feat: columns for the small fixes package`.

### Task 2: Login com o celular sem o 9 extra (seção 2, "Login": celular sem o 9)

**Files:** `src/tcg_sniper/api/acesso.py` (`pedir_codigo` :72, `registrar_entrada` :96, `entrar` :117), `src/tcg_sniper/formatacao.py` (`normalizar_numero` :35; variante já existe em `ocultar_numero` :60-69), `tests/api/test_auth.py`, `tests/test_numeros.py`.

**Interfaces:** Produces `numero_de_login(s, numero: str) -> str` em `api/acesso.py`: se `numero` é `+55` + DDD + 8 dígitos começando em 6–9, não está cadastrado e a variante com o 9 (`+55DD9…`) está, devolve a variante; senão devolve `numero`. Chamado antes do hash em `pedir_codigo` e em `entrar`/`registrar_entrada`, para os dois formatos terem o mesmo HMAC e os mesmos limites. A consulta acontece sempre (com e sem cadastro), para não mudar o tempo de resposta.

- [ ] **Step 1:** testes: `test_entra_digitando_o_celular_sem_o_nove` (cadastro `+5511987654321`, pede código e entra com `(11) 8765-4321`), `test_com_e_sem_o_nove_dividem_os_limites`, `test_fixo_de_8_digitos_nao_vira_celular` (`(11) 3000-0001` continua `+551130000001` e sem cadastro), `test_sem_o_nove_sem_cadastro_responde_igual`.
- [ ] **Step 2:** ver falhar. **Step 3:** implementar. **Step 4:** `uv run pytest tests/api tests/test_numeros.py -q` → PASS.
- [ ] **Step 5:** PENDENCIAS; commit `fix: log in with the phone typed without the extra 9`.

### Task 3: Espera do Casador gravada no banco (seção 2, "Casamento e idioma": espera em memória)

**Files:** `src/tcg_sniper/casador/servico.py` (`ESPERAS_FALHA` :36, `_falhas` :62, `_falhas_termos` :65, `_em_espera` :186, `_marcar_falha` :195, `_gerar_termos` :265, `_marcar_falha_termos` :316), `src/tcg_sniper/db/repositorio_ia.py` (`pares_pendentes` :125), `src/tcg_sniper/db/repositorio_termos.py` (`produtos_para_gerar_termos` :90), `tests/casador/test_servico.py`, `tests/casador/test_servico_termos.py`.

**Interfaces:** Consumes as colunas da Task 1. Os dicionários em memória saem; a espera do par vive em `casamento.ia_falhas/ia_espera_ate/ia_falha_assinatura` (assinatura mudou → zera, como hoje) e a dos termos em `fila_amazon.termos_falhas/termos_espera_ate`. `pares_pendentes` e `produtos_para_gerar_termos` filtram `espera_ate is null or espera_ate <= agora`. Sucesso zera. Mesmas esperas 1 h, 6 h, 24 h e mesma regra de 3 falhas seguidas que encerram a etapa de termos.

- [ ] **Step 1:** adaptar os testes existentes (mesmo comportamento) e acrescentar `test_espera_sobrevive_a_reinicio_do_casador` (novo `ServicoCasador` no mesmo banco não chama a IA antes do fim da espera) e o equivalente para termos.
- [ ] **Step 2–4:** ver falhar, implementar, `uv run pytest tests/casador tests/db -q` → PASS.
- [ ] **Step 5:** PENDENCIAS; commit `fix: casador backoff survives restarts`.

### Task 4: Idioma — preencher os antigos e fechar a brecha do "indefinido" (seção 2, "Casamento e idioma": os dois itens de idioma)

**Files:** `src/tcg_sniper/db/repositorio_ia.py` (`portugues_confirmado` :175, `IDIOMAS_CONHECIDOS` :172), `src/tcg_sniper/casador/servico.py` (`_idioma_permite_confirmar` :251), `src/tcg_sniper/db/repositorio_casamento.py` (novo `definir_idioma_confirmados`), `src/tcg_sniper/cli.py` (padrão de `casamento reabrir-ingles` :73-79, :216-226), `src/tcg_sniper/consultas/variacao.py` (`_IDIOMAS`), API da revisão de casamentos (`src/tcg_sniper/api/rotas_gestao_casamentos.py`) e `web/src/paginas/gestao/RevisaoCasamento.tsx` (ou o componente do cartão confirmado), testes em `tests/db/test_repositorio_ia.py`, `tests/casador/test_servico.py`, `tests/db/test_repositorio_casamento.py`, `tests/api/test_gestao_casamentos.py`, `web/src/paginas/gestao/RevisaoCasamento.test.tsx`.

**Interfaces:**
- `portugues_confirmado` usa `coalesce(anuncio_amazon.idioma, avaliacao_ia.idioma_anuncio)`.
- `_idioma_permite_confirmar`: `"indefinido"` passa a seguir a regra do inglês (só confirma com `portugues_confirmado is False`); `None` segue como hoje.
- `definir_idioma_confirmados(s, agora, *, aplicar: bool) -> ResultadoIdioma(definidos: dict[str,int], sem_decisao: list[(anuncio_id, titulo)])`: para confirmados sem idioma conhecido, usa a heurística do título; sem `--aplicar` só conta (SAVEPOINT + rollback, como `reabrir_ignorados_por_ingles` :349).
- CLI `tcg-sniper casamento definir-idioma [--aplicar]` imprime a contagem e a lista do que ficou sem decisão.
- `PATCH /api/gestao/casamentos/anuncios/{anuncio_id}/idioma` corpo `{"idioma": "pt"|"en"|"ja"|"outro"}` (permissão `revisar_casamentos`); botão "definir idioma" (menu pequeno com as 4 opções) no cartão do anúncio confirmado; o selo de idioma mostra o valor definido.

- [ ] **Step 1:** testes: `test_idioma_definido_no_anuncio_vale_para_portugues_confirmado`, `test_indefinido_com_portugues_confirmado_nao_confirma_sozinho`, `test_definir_idioma_sem_aplicar_so_conta`, `test_definir_idioma_aplicando_pela_heuristica_e_lista_o_resto`, API `test_definir_idioma_do_anuncio` (403 sem permissão, 422 valor inválido), front: o botão aparece no confirmado e atualiza o selo no lugar.
- [ ] **Step 2–4:** ver falhar, implementar, `uv run pytest tests/db tests/casador tests/api -q` e `(cd web && npm test && npm run build)` → PASS.
- [ ] **Step 5:** PENDENCIAS; `docs/IMPLANTACOES.md` (rodar `casamento definir-idioma` sem e depois com `--aplicar` após o deploy); commit `fix: language of old matches and the undetermined loophole`.

### Task 5: Desativar um produto solta os anúncios confirmados (seção 2, "Casamento e idioma": produto desativado)

**Files:** `src/tcg_sniper/db/repositorio_casamento.py` (`desfazer` :229, `fechar_oportunidades` :99, `_reabrir_outro_confirmado` :121), `src/tcg_sniper/api/rotas_gestao_catalogo.py` (PATCH :193-209, lote :212-238), `src/tcg_sniper/consultas/catalogo_gestao.py` (`aplicar_lote` :338, `alterar_ativo_em_lote` :53, `alternar_ativo` :107), `src/tcg_sniper/admin/app.py` (:724-757, só para chamar a função nova), `src/tcg_sniper/oportunidades/encerramento.py` e o enum `MotivoEncerramento`, testes em `tests/db/test_repositorio_casamento.py`, `tests/api/test_gestao_catalogo.py`, `tests/consultas/test_catalogo_gestao.py`, `tests/admin/test_admin.py`.

**Interfaces:** `soltar_confirmados_do_produto(s, produto_id, agora) -> int` (quantos soltou): para cada par confirmado do produto (ordem de `anuncio_id`), volta a pendente com `reavaliar=True` como `desfazer`, reabre os `outro_confirmado` do anúncio e encerra as oportunidades abertas do anúncio com o motivo `PRODUTO_DESATIVADO` **sem aviso no grupo** (decisão 1). Os caminhos de desativar (PATCH, lote da gestão, lote e chave do admin antigo) chamam a função para cada produto que passa de ativo para inativo; nos lotes, os ids são lidos antes do UPDATE em massa. O `acao_gestao` do lote/PATCH guarda quantos anúncios foram soltos.

- [ ] **Step 1:** testes: `test_desativar_solta_os_confirmados_e_reabre_os_outros`, `test_desativar_encerra_a_oportunidade_sem_aviso_no_grupo`, `test_reativar_deixa_os_pares_para_a_ia`, `test_lote_de_desligar_solta_os_confirmados_de_todos`, e um teste no admin antigo (chave e lote).
- [ ] **Step 2–4:** ver falhar, implementar, `uv run pytest tests/db tests/api tests/consultas tests/admin tests/oportunidades -q` → PASS.
- [ ] **Step 5:** PENDENCIAS; commit `fix: deactivating a product releases its confirmed listings`.

### Task 6: Lembretes e "mensagem não enviada" (seção 2, "Avisos": os dois itens de lembrete)

**Files:** `src/tcg_sniper/avisos/servico.py` (`_avisar` :95, regra do lembrete :121), `src/tcg_sniper/avisos/catalogo.py` (tipos que esperam: `AMAZON_BUSCA_CAPTCHA` :220, `AMAZON_CAPTCHA` :248, `AMAZON_SEM_LOGIN` :264, `AMAZON_CARRINHO` :270, `AMAZON_PAUSADA` :283, `IA_PAUSADA` :319, desafio da Liga; `MENSAGEM_NAO_ENVIADA` :364-370), `src/tcg_sniper/avisos/formato.py` (`formatar_lembrete` :122), `src/tcg_sniper/manutencao/servico.py` (tick :132-134), `src/tcg_sniper/notificador/servico.py` (:158-186), `src/tcg_sniper/db/repositorio_mensagens.py` (`reenviar` :128, `descartar` :144, `falhas_recentes` :154), testes em `tests/avisos/test_servico.py`, `tests/notificador/test_servico.py`, `tests/manutencao/test_servico.py`.

**Interfaces:**
- `lembrar_abertos(s, agora) -> int` em `avisos/servico.py`: para cada `estado_aviso` aberto de um tipo em `TIPOS_QUE_ESPERAM` (constante no catálogo), ligado em Configurações → Avisos, com `agora - ultimo_envio_em >= definicao.lembrete`, manda o lembrete (`formatar_lembrete`, linhas do catálogo) e atualiza `ultimo_envio_em`; não mexe em `ocorrencias`. Chamado no tick da `manutencao`, junto do vigia.
- "Mensagem não enviada": o notificador resolve o aviso no fim do ciclo quando `falhas_recentes` (sem os próprios avisos) fica vazia; `reenviar` e `descartar` também resolvem quando não sobra falha.

- [ ] **Step 1:** testes: `test_bloqueio_que_espera_recebe_lembrete_a_cada_2h`, `test_lembrete_de_aberto_respeita_aviso_desligado`, `test_lembrete_de_aberto_nao_soma_ocorrencias_nem_duplica`, `test_tipo_que_nao_espera_nao_recebe_lembrete_sozinho`, `test_mensagem_nao_enviada_resolve_sem_falhas_na_janela`, `test_reenviar_a_ultima_falha_resolve_o_aviso`.
- [ ] **Step 2–4:** ver falhar, implementar, `uv run pytest tests/avisos tests/notificador tests/manutencao tests/db -q` → PASS.
- [ ] **Step 5:** PENDENCIAS; commit `fix: reminders for waiting problems and resolve unsent messages`.

### Task 7: Vigia — parado de propósito e batida no laço (seção 2, "Avisos": os dois itens do vigia)

**Files:** `src/tcg_sniper/avisos/vigia.py` (`SERVICOS` :32, `verificar` :66-84, `Batimento` :87-122), `src/tcg_sniper/cli.py` (`instalar_sigterm` :16, Batimento :126/:141/:157/:183, SIGTERM do casador e notificador :171/:182), `src/tcg_sniper/coletor_liga/agendador.py` (`rodar` :257, `tick`), `src/tcg_sniper/coletor_liga/produtos.py` (:62-83), `src/tcg_sniper/coletor_amazon/varredura_base.py` (`rodar` :253-264, `ESPERA_ERRO_S` :38, `dormir`), `src/tcg_sniper/casador/servico.py` (:328-350), testes em `tests/avisos/test_vigia.py` e nos testes de cada laço tocado.

**Interfaces:**
- `sinal_servico.encerrado_em`: gravado no desligamento limpo (SIGTERM → `finally` do comando do serviço), apagado na próxima batida. `verificar` ignora serviço com `encerrado_em` não nulo e posterior ao último sinal.
- A batida sai da thread e vai para o laço: `Batimento.bater()` público, chamado a cada passo (tick do agendador, cada produto/página da Liga, `executar_passo` da Amazon, passo do Casador); `dormir` longos batem em fatias de até 60 s. Falha ao gravar a batida é logada e não derruba o laço. Mantém `LIMITE_SEM_SINAL` = 10 min.

- [ ] **Step 1:** testes: `test_desligamento_limpo_nao_gera_sem_sinal`, `test_queda_sem_sigterm_continua_avisando`, `test_batida_volta_depois_de_religar`, `test_laco_parado_dispara_sem_sinal_mesmo_com_processo_vivo` (sem batida do laço por 10 min), `test_espera_longa_bate_em_fatias`, `test_falha_ao_bater_nao_derruba_o_laco`.
- [ ] **Step 2–4:** ver falhar, implementar, `uv run pytest tests/avisos tests/coletor_liga tests/coletor_amazon tests/casador -q` → PASS.
- [ ] **Step 5:** PENDENCIAS; commit `fix: watchdog ignores clean stops and beats from the work loops`.

### Task 8: Fim da oportunidade com realerta na fila (seção 2, "Oportunidades e monitor": realerta na fila)

**Files:** `src/tcg_sniper/coletor_amazon/monitor.py` (`_alertar` :220-237), `src/tcg_sniper/oportunidades/encerramento.py` (`_alerta_saiu` :31-44, `encerrar` :47-85), `tests/oportunidades/test_encerramento.py`, `tests/coletor_amazon/test_monitor.py`.

**Interfaces:** `_alertar` marca `op.alerta_enviado = True` quando a mensagem anterior substituída já foi ENVIADA; o notificador também marca quando a mensagem de alerta atual é enviada (ou `_alerta_saiu` consulta). `_alerta_saiu`, depois de descartar uma mensagem pendente, devolve `op.alerta_enviado or op.alerta_sem_registro`.

- [ ] **Step 1:** testes: `test_realerta_na_fila_descartado_ainda_avisa_se_o_anterior_saiu`, `test_nenhum_alerta_saiu_continua_sem_aviso` (o existente segue passando).
- [ ] **Step 2–4:** ver falhar, implementar, `uv run pytest tests/oportunidades tests/coletor_amazon tests/notificador -q` → PASS.
- [ ] **Step 5:** PENDENCIAS (inclui o índice em `mensagem_alerta_id`, feito na Task 1); commit `fix: closing notice when a queued realert is discarded`.

### Task 9: LigaMagic — espera do desafio, produto que sempre falha e pausas em 24 h (seção 2, "LigaMagic": os três itens)

**Files:** `src/tcg_sniper/coletor_liga/esfriamento.py` (`SituacaoDesafio` :35-37, `_esfriando_ate` :55-74, `desafios_desde` :40/:80), `src/tcg_sniper/gestao/servicos.py` (`ligar` :113, `_SEM_SOLICITAR` :105, `retomar_desafio` :131-145), `src/tcg_sniper/db/repositorio.py` (`retomar` :210-232), `src/tcg_sniper/coletor_liga/agendador.py` (:118-151, `_config_do_job` :187-196), `src/tcg_sniper/coletor_liga/lista_do_dia.py` (`montar_lista` :46, novos :86-91), `src/tcg_sniper/coletor_liga/produtos.py` (:70-80, `gravar_precos_produto`), `src/tcg_sniper/consultas/painel.py` (:179-182), testes em `tests/coletor_liga/test_esfriamento.py`, `tests/coletor_liga/test_agendador.py`, `tests/coletor_liga/test_lista_do_dia.py`, `tests/coletor_liga/test_produtos.py`, `tests/gestao/test_acoes_servicos.py`.

**Interfaces:**
- `estado_coletor.retomado_desafio_em`: gravado só por `retomar_desafio` quando o estado era `PAUSADO_DESAFIO`; `_esfriando_ate` conta dele (não de `atualizado_em`). Ligar/desligar comum não reinicia a espera; `ligar` durante a espera mantém o pedido de execução.
- `produto_liga.falhas_pagina`: +1 em `ErroRede`/`ErroParser` da página do produto, zera ao gravar preços; `montar_lista` tira dos "novos do dia" quem tem `falhas_pagina >= 3` (decisão 6), que segue no rodízio.
- `SituacaoDesafio` ganha `desafios_24h`; `pausas_dobradas = desafios_24h >= 1`; `parada_hoje` continua no dia do calendário.

- [ ] **Step 1:** testes: `test_desligar_e_religar_nao_reinicia_a_espera_do_desafio`, `test_ligar_na_espera_mantem_o_pedido`, `test_novo_que_falha_3_vezes_sai_dos_novos_do_dia`, `test_leitura_boa_zera_as_falhas`, `test_desafio_as_23h_dobra_as_pausas_da_madrugada`; ajustar `test_desafio_de_ontem_ainda_esfria_a_retomada_de_hoje_sem_dobrar_as_pausas` para a regra nova (desafio há menos de 24 h dobra).
- [ ] **Step 2–4:** ver falhar, implementar, `uv run pytest tests/coletor_liga tests/gestao tests/admin -q` → PASS.
- [ ] **Step 5:** PENDENCIAS; commit `fix: Liga challenge wait, failing new products and 24h doubled pauses`.

### Task 10: Fechamento

- [ ] **Step 1:** `docs/IMPLANTACOES.md`: seção "Pacote de pequenas (2026-10-27)" com backup antes (migração), deploy de todos os serviços e o comando `casamento definir-idioma` (sem e com `--aplicar`).
- [ ] **Step 2:** suíte inteira `uv run pytest -q`, `uvx ruff check src tests`, `(cd web && npm test && npm run build)` → PASS.
- [ ] **Step 3:** `docs/PENDENCIAS.md`: "Última revisão", conferir que os 13 itens saíram da seção 2 e estão em "Concluídas › Pacote de pequenas"; commit `docs: small fixes package`.
