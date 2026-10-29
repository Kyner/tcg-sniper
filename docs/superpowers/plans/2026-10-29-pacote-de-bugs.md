# Pacote de bugs (seção 2 das pendências) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** corrigir os 16 itens de "Pacote de bugs" em `docs/PENDENCIAS.md` (seção 2), um commit por tarefa.

**Architecture:** correções pontuais, cada uma no módulo que já cuida do assunto; nenhuma migração. TDD: teste que falha, correção mínima, teste passa, commit.

**Tech Stack:** Python 3.12, SQLAlchemy, FastAPI, pytest (Postgres de teste em 127.0.0.1:5433); React 19, react-router 7, Vitest, DaisyUI 5.

**Spec:** `docs/PENDENCIAS.md`, seção 2, "Pacote de bugs (próxima entrega)".

## Global Constraints

- Textos em português; assunto dos commits em inglês (`fix:`, `test:`), sem assinatura de IA.
- `git add` só com os arquivos nomeados (nunca `-A`).
- Front: só componentes do DaisyUI 5, classes literais.
- Testes só no Postgres de teste (`tcg_test*`, porta 5433).
- Sem migração neste pacote.

## Review Focus

- Notificador com o banco fora do ar: o ciclo não pode enviar a mesma mensagem em loop a cada segundo (o adiamento tem de valer mesmo quando a gravação falha) — teste na Tarefa 2.
- Atividade sem `ver_configuracoes`: a busca por um valor de configuração não pode achar a ação (vazamento pela busca) — teste na Tarefa 5.
- Voltar do navegador com alteração e o usuário confirmando sair: tem de sair de fato, sem ficar preso na página — teste na Tarefa 9.
- Categoria repetida ou inválida: o texto digitado fica no campo junto com a mensagem, para o usuário corrigir — teste na Tarefa 10.
- Liga parada pelo 2º desafio e reiniciada: amanhã, no horário, a coleta roda normalmente — teste na Tarefa 16.

---

### Task 1: IA do idioma olha a embalagem, não o título

**Files:** Modify `src/tcg_sniper/casador/pergunta.py:24-31` (`INSTRUCOES`). Test `tests/casador/test_pergunta.py`.

- [ ] Teste `test_idioma_vem_da_embalagem_nao_do_titulo`: `INSTRUCOES` contém `"embalagem"`, `"não pelo título"` e `"indefinido"` na mesma regra de `idioma_anuncio`.
- [ ] Rodar: `uv run pytest tests/casador/test_pergunta.py -q` → FAIL.
- [ ] Trocar a linha de `idioma_anuncio` por: "Em idioma_anuncio informe o idioma do produto vendido, pela embalagem e pelas cartas que aparecem nas imagens, não pelo título (lojas brasileiras escrevem o título em português para produto importado): "pt", "en", "ja", "outro" ou "indefinido" (as imagens não mostram a embalagem com clareza)."
- [ ] Rodar `tests/casador` → PASS. Commit `fix: language question asks for the packaging language, not the title`.

### Task 2: Notificador não trava a fila numa mensagem

**Files:** Modify `src/tcg_sniper/notificador/servico.py:69-126` (`ciclo`, `_processar`). Test `tests/notificador/test_servico.py` (substitui `test_erro_no_meio_do_lote_nao_desfaz_as_ja_enviadas`).

Decisão: erro ao processar uma mensagem (inclusive o commit) não sobe do `ciclo`. Em transação nova, a mensagem ganha `tentativas + 1` e `proxima_tentativa_em` pelo mesmo backoff da falha de envio; o ciclo segue para a próxima. Se até esse adiamento falhar (banco fora), o id entra num conjunto `pular` só deste ciclo, `lote_pendente` ganha `excluir: Collection[int] = ()` e o ciclo encerra o lote (sem repetir a mesma).

- [ ] Teste `test_mensagem_que_sempre_falha_ao_gravar_nao_trava_a_fila`: duas pendentes A (mais velha) e B; `monkeypatch` faz o registro de A lançar; `ciclo()` não lança; B fica ENVIADA; A fica PENDENTE com `tentativas == 1` e `proxima_tentativa_em > agora`.
- [ ] Teste `test_banco_fora_no_adiamento_nao_reenvia_em_loop`: registro e adiamento lançam; `ciclo()` não lança e `enviar_uma_vez` é chamado uma vez só para A no ciclo.
- [ ] FAIL → implementar → `uv run pytest tests/notificador -q` PASS. Commit `fix: one failing message no longer blocks the WhatsApp queue`.

### Task 3: Casador sobrevive ao banco fora dentro dos `except`

**Files:** Modify `src/tcg_sniper/casador/servico.py` (`ciclo` `:127-162`, `_gerar_termos` `:290-316`). Tests `tests/casador/test_servico.py`, `tests/casador/test_servico_termos.py`.

- [ ] Criar `_sem_derrubar(self, descricao: str, acao: Callable[[], None]) -> None`: roda `acao`; em `Exception` faz `log.exception(...)` com a descrição e segue. Envolver `_marcar_falha`, `_pausar_por_configuracao`, `_avisar_orcamento`, `limpar_falha_par`, `_marcar_falha_termos` e `limpar_falha_termos`.
- [ ] Teste `test_falha_ao_gravar_a_falha_nao_derruba_o_ciclo`: dois pares; a IA falha no 1º; `registrar_falha_par` lança `OperationalError`; `ciclo()` não lança e o 2º par é avaliado.
- [ ] Teste igual para termos: `test_falha_ao_gravar_falha_de_termos_nao_derruba`.
- [ ] FAIL → implementar → `tests/casador` PASS. Commit `fix: casador keeps its cycle when recording a failure fails`.

### Task 4: Alguém vigia a manutenção

**Files:** Modify `src/tcg_sniper/avisos/vigia.py`, `src/tcg_sniper/notificador/servico.py`. Tests `tests/avisos/test_vigia.py`, `tests/notificador/test_servico.py`.

Decisão: o notificador vigia a `manutencao` (o único outro serviço que roda sempre e já manda WhatsApp). `vigia.verificar_manutencao(s, agora, desde) -> None` usa o sinal `EstadoManutencao` (último ciclo) com o mesmo limite de 10 min e o mesmo aviso `SERVICO_SEM_SINAL` (abre e fecha) dos outros; o notificador chama uma vez por minuto, protegido como na Tarefa 3.

- [ ] Teste `test_manutencao_muda_mais_de_10_min_abre` e `test_manutencao_volta_fecha` em `test_vigia.py` (helpers `verificar`, `abertos`).
- [ ] Teste no notificador: `ciclo()` chama `verificar_manutencao` e não lança se ela lançar.
- [ ] FAIL → implementar → PASS. Commit `fix: notificador watches the maintenance service`.

### Task 5: Atividade esconde valores de configuração de quem não pode vê-los

**Files:** Modify `src/tcg_sniper/consultas/atividade.py` (`FiltroAtividade` `:69-79`, `_descricao_configuracoes` `:691-711`, `_acoes` `:729-757`), `src/tcg_sniper/api/rotas_gestao_atividade.py:80`. Tests `tests/consultas/test_atividade.py`, `tests/api/test_gestao_atividade.py`.

- [ ] `FiltroAtividade.mostrar_valores_configuracao: bool = False`. Falso: o resultado diz "salvou N campos: rótulo, rótulo" (sem antes→depois), `detalhe["campos"]` vira a lista de chaves, e a busca não olha `detalhe` das ações de configuração. A rota liga com `Permissao.VER_CONFIGURACOES in contexto.permissoes`.
- [ ] Teste `test_sem_ver_configuracoes_esconde_os_valores` (API, operador sem `ver_configuracoes`): a ação aparece com os rótulos, sem os valores; buscar pelo valor salvo não acha a ação.
- [ ] Ajustar `test_acao_de_configuracoes_diz_o_que_mudou` para passar `mostrar_valores_configuracao=True`.
- [ ] FAIL → implementar → PASS. Commit `fix: activity hides setting values without ver_configuracoes`.

### Task 6: Lista de usuários sem sessões de admins para quem não é superadmin

**Files:** Modify `src/tcg_sniper/api/rotas_usuarios.py:44,98-102,129-134`; `web/src/tipos.ts` (campo `sessoes_ativas: number | null`) e a tela de Usuários (mostrar "—" para `null`). Test `tests/api/test_usuarios.py`.

- [ ] Teste `test_admin_comum_nao_ve_sessoes_de_admins_na_lista`: admin não-superadmin lista; linha de admin tem `sessoes_ativas is None`; operador mostra o número.
- [ ] FAIL → implementar (`_saida(usuario, sessoes)` recebe `None` quando `usuario.papel is Papel.ADMIN and not contexto.superadmin`) → PASS, front `npm test` PASS. Commit `fix: user list hides admin session counts from regular admins`.

### Task 7: Login pega a trava antes de apagar

**Files:** Modify `src/tcg_sniper/api/acesso.py:87-91,112-115`. Test `tests/api/test_limites_concorrencia.py`.

- [ ] Teste `test_trava_vem_antes_da_limpeza`: `monkeypatch` em `repo_acesso.travar_limite` e `repo_acesso.limpar_antigos` registra a ordem; em `pedir_codigo` e em `registrar_entrada` a ordem é `["travar", "limpar"]`.
- [ ] FAIL → mover `limpar_antigos` para depois de `travar_limite` nos dois → PASS. Commit `fix: login takes the advisory lock before cleaning old rows`.

### Task 8: Carrinho com id fora do limite dá 404

**Files:** Modify `src/tcg_sniper/api/rotas_gestao_servicos.py:230-239`. Test `tests/api/test_gestao_servicos.py`.

- [ ] Teste `test_carrinho_conferido_com_id_gigante_e_404`: `2**31` e `0` → 404 (mesmo erro de "sem conferência").
- [ ] FAIL → checar `1 <= conferencia_id <= MAX_ID` como em `rotas_gestao_atividade.py:95` → PASS. Commit `fix: cart confirm returns 404 for out-of-range ids`.

### Task 9: Voltar do navegador avisa sobre alterações

**Files:** Modify `web/src/paginas/gestao/Configuracoes.tsx:21-47` (`useAvisarAoSair`). Test `web/src/paginas/gestao/Configuracoes.test.tsx`.

Decisão: sem trocar para data router. Com `sujo`, o hook empilha uma entrada de histórico guarda (`history.pushState`) e escuta `popstate`: pergunta com `window.confirm` (mesma frase dos links); cancelou → empilha a guarda de novo; confirmou → remove o ouvinte e chama `history.back()`. Ao limpar (`sujo` falso ou desmontar), tira o ouvinte.

- [ ] Teste "Voltar com alteração pergunta e fica se cancelar": muda um campo, `confirm` → false, dispara `popstate`; o campo e a barra Salvar continuam.
- [ ] Teste "Voltar com alteração e confirmar sai": `confirm` → true; `history.back` é chamado.
- [ ] FAIL → implementar → `npm test` PASS. Commit `fix: browser Back warns about unsaved settings`.

### Task 10: Categorias avisam o erro; botões maiores no celular

**Files:** Modify `web/src/componentes/CategoriasConfig.tsx`, `web/src/componentes/CampoConfig.tsx:95,102`, `web/src/componentes/AvisosConfig.tsx:79`. Test `web/src/paginas/gestao/Configuracoes.test.tsx`.

- [ ] Teste: digitar `abc{Enter}` mostra "Informe o número da categoria." e o texto fica no campo; `7{Enter}` com 7 já na lista mostra "A categoria 7 já está na lista."; digitar de novo some a mensagem.
- [ ] FAIL → implementar (mensagem em `<p className="text-sm text-error" role="alert">`, só limpa o campo quando adiciona) → PASS.
- [ ] Trocar `btn-xs` por `btn-sm` nos quatro botões citados (classes literais; o teste-guarda de classes continua passando). Commit `fix: category field explains rejected input and settings buttons fit touch`.

### Task 11: "iniciando…" só para quem roda sem esperar horário

**Files:** Modify `src/tcg_sniper/consultas/servicos.py:135-148`. Test `tests/consultas/test_servicos.py`.

- [ ] Teste parametrizado `test_servico_de_horario_ligado_sem_registro_nao_fica_iniciando` para Liga, WhatsApp e Backup: ligado há 5 min, sem registro → `transicao(...) is None`. O teste existente `test_ligado_ha_5_min_sem_registro_esta_iniciando` passa a usar um serviço contínuo (casador).
- [ ] FAIL → constante `SERVICOS_POR_HORARIO` (os três) e retorno `None` para eles → PASS. Commit `fix: scheduled services no longer show starting for 10 minutes`.

### Task 12: Dashboard com "Já conferi" do carrinho e link desconhecido no log

**Files:** Modify `src/tcg_sniper/consultas/dashboard.py` (`destino_novo` `:99-125`, `precisa` `:205-210`), a saída da rota do Dashboard (campo opcional `acao: {rotulo, caminho}` no item), `web/src/paginas/Gestao.tsx:76-90`, `web/src/tipos.ts`. Tests `tests/consultas/test_dashboard.py`, `web/src/paginas/Gestao.test.tsx`.

- [ ] `destino_novo`: caminho desconhecido faz `log.warning("link do painel sem destino novo: %s", link)` e segue em `/gestao`. Teste com `caplog`.
- [ ] `precisa()`: o aviso do carrinho leva `acao = {"rotulo": "Já conferi", "caminho": "/api/gestao/servicos/carrinho/{id}/conferido"}` (de `/amazon/carrinho/{id}/conferido`). Teste no `test_precisa_junta_decisoes_e_avisos_com_destino_novo`.
- [ ] Front: item com `acao` e permissão `pausar_servicos` mostra botão "Já conferi" (`btn btn-sm`) que faz POST e recarrega o Dashboard; sem a permissão, não mostra. Teste em `Gestao.test.tsx`.
- [ ] FAIL → implementar → PASS (pytest e `npm test`). Commit `fix: dashboard offers the cart confirm action and logs unknown links`.

### Task 13: "Quase lá" com limite padrão

**Files:** Modify `src/tcg_sniper/api/rotas_oportunidades.py:204-213`. Test `tests/api/test_oportunidades.py`.

- [ ] Teste `test_quase_la_sem_limite_usa_200`: com 201 quase oportunidades, sem `limite` volta 200. (Se montar 201 for caro, `monkeypatch` do padrão para 2 com 3 itens.)
- [ ] FAIL → `limite: ... = 200` (constante `LIMITE_QUASE_PADRAO = 200`, `le=500` mantido) → PASS. Commit `fix: near opportunities API has a default limit`.

### Task 14: Frase "conferido, com impostos de R$ X"

Já coberta: `tests/oportunidades/test_dados_oportunidade.py::test_conferido_com_impostos_frete_importado_prime_e_cupom` confere `" (conferido, com impostos de R$ 48,26; frete R$ 12,50 à parte)"`.

- [ ] Rodar o teste e confirmar PASS; marcar o item como resolvido nas pendências (Tarefa 17), sem código.

### Task 15: Testes instáveis

**Files:** `tests/coletor_amazon/test_varredura_monitor.py:768-781`, `tests/fakes_varredura.py`, `web/vite.config.ts`.

- [ ] Python: usar superpowers:systematic-debugging. Reproduzir com `uv run pytest tests/coletor_amazon -q -p no:randomly --count` (ou laço de 30 execuções da pasta) e conferir se o teste lê o relógio real (`varredura_base.py:119`) ou depende do sorteio da janela (`fila.janela_do_dia`, `JITTER_JANELA_MIN`). Corrigir a causa no teste ou no fake (relógio fixo injetado em todo caminho, ou horas longe da borda da janela com o jitter).
- [ ] Front: `web/vite.config.ts` → `test.testTimeout: 15000` (o `findBy` espera 5 s e o teste também tinha 5 s; o chunk do Recharts carrega na primeira abertura).
- [ ] 30 execuções seguidas sem falha. Commit `test: stabilize monitor window test and front timeouts`.

### Task 16: Liga não promete execução atrasada no dia encerrado

**Files:** Modify `src/tcg_sniper/coletor_liga/agendador.py:87-99` (`inicializar`). Test `tests/coletor_liga/test_agendador.py`.

- [ ] Em `inicializar`, consultar `situacao_desafio(...)`; com `parada_hoje`, não cria a atrasada e loga "dia encerrado pelo 2º desafio; a próxima coleta é amanhã no horário".
- [ ] Teste `test_reinicio_com_dia_encerrado_nao_agenda_atrasada` (`caplog`): sem "execução atrasada" no log, com a frase nova; no dia seguinte, no horário, o job roda.
- [ ] FAIL → implementar → `tests/coletor_liga` PASS. Commit `fix: Liga restart on a closed day does not announce a late run`.

### Task 17: Fechar o pacote

- [ ] Suíte completa: `uv run pytest -q`, `uvx ruff check src tests`, `cd web && npm test -- --run && npm run build`.
- [ ] `docs/PENDENCIAS.md`: marcar os 16 `[x]` com o commit de cada um e mover para "Concluídas" numa seção "Pacote de bugs (2026-10-29)". Commit `docs: bug package done`.
- [ ] Deploy só quando o usuário pedir (sem migração: `docker compose up -d --build`).
