# Fase 3B — Serviços, Atividade e Dashboard na gestão do site novo — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Levar Serviços, Logs (como Atividade, junto com Mensagens) e o Dashboard para a gestão do site novo, cobrindo rota por rota o que o admin antigo faz nessas telas, para a fase 4 poder apagar o pacote `admin`.

**Architecture:** As consultas do painel, dos logs, das mensagens e do menu saem do pacote `admin` para o pacote neutro `tcg_sniper/consultas/` (o admin antigo passa a importar de lá, sem mudar de comportamento). As ações de serviço (ligar, desligar, rodar agora, retomar, monitor/checkout, carrinho conferido) saem das rotas do admin para um módulo neutro `tcg_sniper/gestao/servicos.py`, chamado pelos dois. Três roteadores novos em `/api/gestao/...` (`servicos`, `atividade`, `dashboard`) e três telas novas (`/gestao/servicos`, `/gestao/atividade`, `/gestao` como Dashboard).

**Tech Stack:** Python 3.12 + FastAPI + SQLAlchemy 2 + Postgres; React + Vite + TypeScript + DaisyUI 5 + Vitest; Playwright (Python) no ponta a ponta.

**Spec:** `docs/superpowers/specs/2026-10-21-fase3-area-administrativa-design.md` (seções "Regras que valem para todas as telas", "Serviços", "Atividade", "Dashboard", "Menu da gestão", "Permissões", "API").

## Global Constraints

- Textos, telas e mensagens em português; assunto dos commits em inglês `tipo: descrição`; **sem** `Co-Authored-By`, `Claude-Session` ou "Generated with" (CLAUDE.md).
- Só componentes do DaisyUI 5, classes escritas por extenso (nada montado por concatenação). Sem visual próprio. Tooltip = `<div className="tooltip" data-tip=…>` do DaisyUI.
- Mobile first: desenhado para 390 px; abaixo de `md` tabelas viram listas de cartões; sem rolagem horizontal da página.
- Status em uma linha (`truncate`); texto completo em `tooltip`.
- **Vocabulário único de estado**: chave = ligado/desligado; processo = rodando · esperando · atrasado · com problema · desligado, com `badge-success`, `badge-ghost`, `badge-warning`, `badge-error`, `badge-neutral` (nessa ordem), escritas por extenso num mapa único do front.
- Ação numa linha atualiza no lugar (sem recarregar nem mudar a rolagem); erro volta o estado e mostra mensagem.
- Filtros e cursor na URL; "Voltar" restaura.
- Toda rota `/api/gestao/...` declara `exige(...)`/`exige_todas(...)`; toda tela exige `ver_area_gestao` **e** a permissão própria.
- Ações de serviço gravam `acao_gestao` (tipo `servico`) na mesma transação e disparam o mesmo aviso `SERVICO_PAUSADO_MANUAL` que o admin antigo.
- O admin antigo continua funcionando igual até a fase 4 (todos os testes de `tests/admin/` passam sem mudar as expectativas).
- Nada em `tcg_sniper/consultas/` nem em `tcg_sniper/gestao/` importa `tcg_sniper.admin`.
- Testes no Postgres de teste (`127.0.0.1:5433`, bancos `tcg_test*`); nunca a 5432. Ruff com `uvx ruff check`.
- Sem migração prevista. Se um índice novo for preciso (Task 5), entra como migração e o deploy pede backup antes.

## Decisões deste plano (chamadas minhas, com o custo se estiverem erradas)

1. **Estado único a partir da situação do painel**: `rodando`→rodando; `ok`→esperando; `parcial`→atrasado; `falha` e `pausado_desafio`→com problema; `pausado` e `inativo`→desligado; exceção: Casador "IA ligada, mas sem chave" → com problema. Custo: um rótulo errado num caso raro, corrigido no mapa.
2. **"Parando…" / "parado de verdade" / "iniciando…"** (a spec pede só consulta, sem sinal novo): desligado há T; "parando…" enquanto houver ciclo em andamento **ou** registro novo do serviço nos últimos 2 min; depois, "parado de verdade desde HH:MM" (o maior entre T e o último registro). Ligado há menos de 10 min sem registro novo depois de ligar → "iniciando…"; passado isso, o estado normal (um serviço fora da janela não fica "iniciando" para sempre). Registros por serviço: Liga = `coleta` (tipos da Liga) e `resumo_preco.coletado_em`; busca = `coleta` AMAZON e `fila_amazon.ultima_busca_em`; monitor = `oferta_amazon.lida_em` e `conferencia_checkout.em`; casador = `chamada_ia.em`; WhatsApp = `mensagem_saida.enviada_em`; backup = `execucao_manutencao` (`rodando`, `inicio`). Custo: a palavra muda alguns minutos antes ou depois do real.
3. **Amazon · monitor** tem a chave do serviço (`coletor amazon`, que também leva checkout e retirada) e, na sub-linha, as chaves "monitor de preço" (`monitor_ligado`) e "conferência de checkout" (`checkout_ligado`), mais "Retomar" do checkout e a lista "carrinho a conferir" com "Já conferi". Tudo o que o admin antigo tem fica.
4. **"Abrir"**: noVNC em `http://{host_publico}:6080|6081|6082/vnc.html`; WhatsApp em `http://127.0.0.1:8080/manager` (constante; não há endereço no código). Tooltip: "Só abre neste PC" (desde a segurança etapa 1, o noVNC escuta só em 127.0.0.1; a spec dizia "rede de casa"). Só com `pausar_servicos`.
5. **Atividade**: leituras individuais do monitor (~200/h) só aparecem com o filtro "leitura do monitor" ou com busca por produto/ASIN; o "todos" mostra o resto. O detalhe vem na própria linha (sem segunda rota). Cursor = base64 de `em|fonte|id`, mais recente primeiro, 50 por página.
6. **Dashboard, "Ver o efeito" do monitor atrasado**: até a 3C, abre Configurações do admin antigo. Os links antigos dos avisos do painel são traduzidos por uma tabela única (`/servicos`→`/gestao/servicos`, `/logs?aba=X`→`/gestao/atividade?o_que=…`, `/mensagens…`→`/gestao/atividade?o_que=mensagem`, `/casamentos…`→`/gestao/casamentos…`, `/configuracoes…`→admin antigo).
7. **Pequenas da 3A que entram aqui** (as do menu): o botão do menu no celular recebe foco pelo teclado; `GET /api/gestao/menu` conta em vez de montar a lista; Mensagens e Logs saem do menu. As da revisão e do catálogo ficam para a 3C.

## Cobertura do admin antigo (para a fase 4)

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

## Review Focus

1. **Desligar a Liga com desafio pendente** → não mexe, responde `desafio_pendente` com o texto do admin antigo; a linha continua "com problema". Teste na Task 2.
2. **Dois cliques seguidos em Ligar/Desligar** (ou um operador sem `pausar_servicos` chamando a rota) → idempotente, um `acao_gestao` por clique aceito; 403 sem permissão. Teste na Task 4.
3. **Cursor da Atividade com dois registros no mesmo instante** (mensagem e chamada da IA com `em` igual) → nenhum some nem repete entre as páginas. Teste na Task 5.
4. **Atividade de leitura do monitor e de checkout de anúncios de produtos diferentes** → cada linha com o seu produto (regressão do bug do admin antigo). Teste na Task 5.
5. **Operador com `ver_logs` sem `ver_mensagens`** → linhas de mensagem aparecem sem o texto; sem `reenviar_mensagens`, sem botões. Teste na Task 6 e na Task 9.

---

### Task 1: Consultas do painel, dos logs, das mensagens e do menu no pacote neutro

**Files:**
- Move: `src/tcg_sniper/admin/consultas_painel.py` → `src/tcg_sniper/consultas/painel.py`; `admin/consultas.py` (funções `historico_*`, `paginar`, `ultima_coleta_*`, `coleta_em_andamento`, `_produto_da_linha`, `LinhaConferencia`, `LinhaMonitor` e constantes) → `consultas/historico.py`; `admin/consultas_mensagens.py` → `consultas/mensagens.py`; `admin/consultas_amazon.py::ciclo_atual` → `consultas/historico.py`; `admin/consultas_menu.py` → `consultas/menu.py`
- Modify: imports em `src/tcg_sniper/admin/*.py` e `tests/admin/*.py`
- Test: `tests/consultas/test_sem_admin.py`

**Interfaces:**
- Produces: os mesmos nomes e assinaturas de hoje (ver o mapa: `saude_servicos`, `saude_backup`, `avisos`, `avisos_backup`, `numeros`, `atividade_hoje`, `processo_manutencao`, `capacidade_por_hora`, `SaudeServico`, `Aviso`, `Numeros`; `historico_coletas`, `historico_chamadas_ia`, `historico_conferencias`, `historico_monitor`, `historico_manutencao`, `coleta_em_andamento`, `ultima_coleta_sucesso`, `ciclo_atual`, `produto_da_linha` (sem o `_`); `listar`, `resumo`, `estado_notificador`, `ResumoMensagens`; `contadores_menu`), agora em `tcg_sniper.consultas.{painel,historico,mensagens,menu}`.

- [ ] **Step 1: Teste de guarda** `test_consultas_e_gestao_nao_importam_admin`: percorre `src/tcg_sniper/consultas/**/*.py` e `src/tcg_sniper/gestao/**/*.py` (este último pode ainda não existir) com `ast` e falha em qualquer `import`/`from` de `tcg_sniper.admin`.
- [ ] **Step 2: Mover** os módulos com `git mv` quando o arquivo inteiro muda de lugar; o que sobra de `admin/consultas.py` (se sobrar) continua lá. O que dependia de `admin` (ex.: constantes de rótulo) vem junto. Sem reexportação com `noqa: PLC0414`: os chamadores importam do lugar novo.
- [ ] **Step 3: Rodar** `uv run pytest tests/admin tests/consultas -q` e `uvx ruff check src tests` → PASS (nenhuma expectativa de teste muda).
- [ ] **Step 4: Commit** `refactor: move painel, logs, messages and menu queries to neutral package`.

### Task 2: Ações de serviço num módulo neutro

**Files:**
- Create: `src/tcg_sniper/gestao/__init__.py`, `src/tcg_sniper/gestao/servicos.py`
- Modify: `src/tcg_sniper/admin/app.py:388-555` (rotas passam a chamar o módulo; `MENSAGENS_SERVICOS` e `NOMES_SERVICOS` vêm de lá)
- Test: `tests/gestao/test_acoes_servicos.py`

**Interfaces:**
- Produces, em `tcg_sniper.gestao.servicos`:
  - `class Servico(StrEnum)`: `LIGA="liga"`, `AMAZON_BUSCA="amazon_busca"`, `AMAZON_MONITOR="amazon_monitor"`, `CASADOR="casador"`, `WHATSAPP="whatsapp"`, `BACKUP="backup"`; `COLETOR: dict[Servico, str]` (liga→`COLETOR_LIGA`, amazon_busca→`COLETOR_AMAZON_BUSCA`, amazon_monitor→`COLETOR_AMAZON`, casador→`COLETOR_CASADOR`, whatsapp→`COLETOR_NOTIFICADOR`, backup→`COLETOR_MANUTENCAO`); `NOMES: dict[Servico, str]` (os de `NOMES_SERVICOS`).
  - `MENSAGENS: dict[str, str]` (hoje `MENSAGENS_SERVICOS`, mesmas chaves e textos).
  - `ligar(s, servico: Servico, agora) -> str`, `desligar(s, servico, agora) -> str`, `retomar_desafio(s, servico, zona, cfg_efetiva, agora) -> str`, `rodar_agora(s, servico, zona, cfg_efetiva, agora) -> str`, `ajustar_amazon(s, chave: Literal["monitor_ligado","checkout_ligado"], ligado: bool, agora) -> str`, `retomar_checkout(s, agora) -> str`, `carrinho_conferido(s, conferencia_id: int, agora) -> bool`. O `str` devolvido é a chave de `MENSAGENS`.
  - Regras (iguais às do admin antigo): `desligar` com estado `PAUSADO_DESAFIO` não mexe e devolve `"desafio_pendente"` (não vale para o casador); `ligar` da Liga, WhatsApp e Backup usa `retomar(..., solicitar=False)`, da busca, monitor e casador `solicitar=True`; ligar/desligar/retomar disparam `SERVICO_PAUSADO_MANUAL` como `_avisar_mudanca`; `rodar_agora` só existe para Liga e Casador (`ValueError` para os outros), com `parada_hoje` não pede nada; `ajustar_amazon` chama `aplicar_config` sem aviso; `carrinho_conferido` resolve `AMAZON_CARRINHO` do ASIN.

- [ ] **Step 1: Testes** (no molde de `tests/admin/test_admin_servicos.py`, chamando as funções direto): `test_desligar_e_ligar_cada_servico_muda_o_estado_e_avisa` (parametrizado nos 6), `test_desligar_nao_apaga_um_desafio_pendente`, `test_desligar_a_busca_nao_mexe_no_monitor`, `test_rodar_agora_parada_nao_pede_execucao`, `test_rodar_agora_esfriando_pede_e_diz_que_espera`, `test_retomar_do_segundo_desafio_diz_que_volta_amanha`, `test_ajustar_monitor_e_checkout_nao_avisa`, `test_carrinho_conferido_resolve_o_aviso`, `test_rodar_agora_de_servico_sem_essa_acao_falha`.
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/gestao -q` → FAIL (módulo não existe).
- [ ] **Step 3: Implementar** o módulo e trocar o corpo das rotas antigas por chamadas a ele (a rota continua lendo o formulário, devolvendo o mesmo redirect e a mesma mensagem).
- [ ] **Step 4: Rodar** `uv run pytest tests/gestao tests/admin tests/consultas -q` → PASS.
- [ ] **Step 5: Commit** `refactor: neutral service actions shared by old admin and API`.

### Task 3: Estado de cada serviço (vocabulário único, parando e iniciando)

**Files:**
- Create: `src/tcg_sniper/consultas/servicos.py`
- Test: `tests/consultas/test_servicos.py`

**Interfaces:**
- Consumes: `Servico`, `COLETOR` (Task 2); `saude_servicos`, `saude_backup` (Task 1).
- Produces:
  - `Estado = Literal["rodando","esperando","atrasado","com_problema","desligado"]`; `estado_unico(saude: SaudeServico) -> Estado` (decisão 1).
  - `@dataclass(frozen=True) class Transicao: tipo: Literal["parando","parado","iniciando"]; desde: datetime | None`.
  - `ultimo_registro(s, servico: Servico) -> datetime | None` e `em_andamento(s, servico, agora) -> bool` (registros da decisão 2).
  - `transicao(s, servico, estado: EstadoColetor, agora) -> Transicao | None` (decisão 2: `QUIETO = timedelta(minutes=2)`, `INICIANDO = timedelta(minutes=10)`).

- [ ] **Step 1: Testes:** `test_estado_unico_mapeia_cada_situacao` (as 7 situações + "sem chave"); `test_desligado_com_coleta_rodando_esta_parando`; `test_desligado_sem_registro_ha_2_min_esta_parado_desde_o_ultimo_registro`; `test_desligado_sem_registro_depois_da_pausa_parado_desde_a_pausa`; `test_ligado_ha_5_min_sem_registro_esta_iniciando`; `test_ligado_ha_11_min_sem_registro_volta_ao_estado_normal`; `test_ligado_com_registro_depois_de_ligar_nao_esta_iniciando`; um teste por serviço provando de onde vem `ultimo_registro` (Liga coleta, busca fila, monitor oferta e conferência, casador chamada, WhatsApp enviada, backup execução).
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/consultas/test_servicos.py -q`.
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar** → PASS.
- [ ] **Step 5: Commit** `feat: unified service state with stopping and starting`.

### Task 4: API de Serviços

**Files:**
- Create: `src/tcg_sniper/api/rotas_gestao_servicos.py`
- Modify: `src/tcg_sniper/api/app.py:44-49` (include_router)
- Test: `tests/api/test_gestao_servicos.py`

**Interfaces:**
- Consumes: Tasks 1–3; `repositorio_acao_gestao.registrar`, `TipoAcaoGestao.SERVICO`; `carregar_config(sessoes, config)` para a configuração efetiva (a API não tem outra fonte); `zona_e_host(s)`.
- Produces:
  - `GET /api/gestao/servicos` (`ver_area_gestao` + `ver_servicos`) → `{"servicos": [ServicoSaida]}`, na ordem LigaMagic, Amazon · busca, Amazon · monitor, Casador (IA), WhatsApp, Backup. `ServicoSaida`: `id: Servico`, `nome`, `estado: Estado`, `agora: str` (texto curto da saúde), `detalhe: str` (tooltip), `ultimo_ok: datetime | None`, `ligado: bool`, `transicao: {tipo, desde} | None`, `acoes: list[Literal["ligar","desligar","rodar_agora","retomar"]]` (só as válidas no estado; vazio sem `pausar_servicos`), `abrir: str | None` (decisão 4; `None` sem `pausar_servicos`), `atividade: str` (query da Atividade, ex. `servico=liga`), `sub: SubMonitor | None` (só monitor: `monitor_ligado`, `checkout_ligado`, `checkout_parado: bool`, `carrinho: [{conferencia_id, asin, produto, em}]`).
  - `POST /api/gestao/servicos/{id}/{acao}` com `acao ∈ {ligar, desligar, rodar-agora, retomar}`; `POST /api/gestao/servicos/amazon_monitor/{monitor|checkout}/{ligar|desligar}`; `POST /api/gestao/servicos/amazon_monitor/checkout/retomar`; `POST /api/gestao/servicos/carrinho/{conferencia_id}/conferido` — todas `ver_area_gestao` + `pausar_servicos`, resposta `{"codigo": str, "mensagem": str}` (texto de `MENSAGENS`), grava `acao_gestao` `{"servico", "acao", "codigo"}`; ação que não existe para o serviço → 404 `nao_encontrado`; carrinho inexistente → 404.

- [ ] **Step 1: Testes:** `test_sem_sessao_401_e_sem_permissao_403` (GET sem `ver_servicos`, POST como operador); `test_lista_os_seis_servicos_na_ordem`; `test_operador_ve_sem_acoes_nem_abrir`; `test_admin_ve_abrir_com_host_publico` (`http://127.0.0.1:6081/vnc.html` no monitor, `http://127.0.0.1:8080/manager` no WhatsApp, `None` no backup); `test_desligar_e_ligar_gravam_acao_e_avisam`; `test_clicar_desligar_duas_vezes_e_idempotente` (dois `acao_gestao`, estado igual); `test_desligar_liga_com_desafio_devolve_desafio_pendente`; `test_rodar_agora_do_backup_404`; `test_monitor_e_checkout_sub_chaves`; `test_carrinho_conferido_e_404_sem_conferencia`; `test_desligado_mostra_parado_de_verdade`.
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/api/test_gestao_servicos.py -q`.
- [ ] **Step 3: Implementar** (schemas Pydantic no próprio arquivo, `ConfigDict(extra="forbid")`; leitura `with sessoes() as s`, escrita `with sessoes() as s, s.begin()`).
- [ ] **Step 4: Rodar** `uv run pytest tests/api -q` (inclui `test_toda_rota_da_api_declara_permissao_ou_e_publica`) → PASS.
- [ ] **Step 5: Commit** `feat: management services API`.

### Task 5: Linha do tempo da Atividade

**Files:**
- Create: `src/tcg_sniper/consultas/atividade.py`
- Test: `tests/consultas/test_atividade.py`

**Interfaces:**
- Consumes: `produto_da_linha` (Task 1).
- Produces:
  - `OQue = Literal["coleta_liga","busca","leitura_monitor","checkout","ia","mensagem","backup","aviso","acao_gestao"]`; `Situacao = Literal["ok","parcial","falha"]`.
  - `@dataclass(frozen=True) class FiltroAtividade: servico: Servico | None; o_que: OQue | None; situacao: Literal["ok","parcial","falha","problemas"] | None; de: datetime | None; ate: datetime | None; busca: str | None; mostrar_reinicios: bool = False`.
  - `@dataclass(frozen=True) class LinhaAtividade: chave: str` (`"fonte:id"`)`; em: datetime; servico: Servico | None; o_que: OQue; situacao: Situacao; resultado: str` (português, uma linha: ex. `"mesmo 85% · ficou para você"`, `"R$ 309,83 com impostos"`, `"parcial · 512 de 791"`)`; produto_id: int | None; produto: str | None; asin: str | None; custo_usd: Decimal | None; detalhe: dict[str, str | int | None]` (observação completa, números; `texto` e `mensagem_id`/`status` nas mensagens; `usuario` nas ações de gestão).
  - `linha_do_tempo(s, filtro, cursor: str | None, limite: int = 50) -> tuple[list[LinhaAtividade], str | None]` (próximo cursor). Fontes: `coleta` (Liga e busca), `oferta_amazon` (leitura do monitor; decisão 5), `conferencia_checkout`, `chamada_ia`, `mensagem_saida` (`criada_em`), `execucao_manutencao`, `estado_aviso` (`ultimo_em`), `acao_gestao`. Cada fonte com `ORDER BY em DESC, id DESC` e keyset `(em, fonte, id) < cursor`, `LIMIT limite+1`; junta em Python e corta. Falha com `erro="interrompida"` (coleta) ou `status="interrompida"` (manutenção) fica fora sem `mostrar_reinicios`. Busca: `ilike` no nome do produto (pt e en), ASIN exato ou contém, e no texto/erro da linha.

- [ ] **Step 1: Testes:** `test_mais_recente_primeiro_misturando_fontes`; `test_cursor_com_dois_registros_no_mesmo_instante_nao_perde_nem_repete` (Review Focus 3); `test_leitura_do_monitor_so_aparece_com_filtro_ou_busca`; `test_produto_certo_por_linha_no_monitor_e_no_checkout` (Review Focus 4, dois anúncios de produtos diferentes); `test_reinicios_escondidos_por_padrao`; `test_filtro_problemas_traz_falha_e_parcial`; `test_busca_por_asin_e_por_nome`; `test_filtro_por_servico`; `test_resultado_em_portugues_da_ia_e_do_checkout`; `test_acao_de_gestao_traz_o_nome_do_usuario` (e "admin antigo" quando `usuario_id` é nulo).
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/consultas/test_atividade.py -q`.
- [ ] **Step 3: Implementar.** Conferir com `EXPLAIN` no banco de teste que cada fonte usa índice em `em`/`criada_em`/`lida_em`; se faltar um, migração nova só com o índice (e anotar "backup antes do deploy" no IMPLANTACOES).
- [ ] **Step 4: Rodar** → PASS.
- [ ] **Step 5: Commit** `feat: unified activity timeline query`.

### Task 6: API da Atividade e das mensagens

**Files:**
- Create: `src/tcg_sniper/api/rotas_gestao_atividade.py`
- Modify: `src/tcg_sniper/api/app.py`
- Test: `tests/api/test_gestao_atividade.py`

**Interfaces:**
- Consumes: Task 5; `repositorio_mensagens.reenviar`, `descartar`, `MensagemNaoEncontrada`, `AcaoInvalida`.
- Produces:
  - `GET /api/gestao/atividade?servico=&o_que=&situacao=&de=&ate=&busca=&reinicios=&cursor=` (`ver_area_gestao` + `ver_logs`) → `{"itens": [LinhaAtividadeSaida], "proximo": str | None}`; sem `ver_mensagens`, `detalhe.texto` sai `None`; `podeReenviar` não existe na linha (o front usa a permissão). Cursor inválido → 422 `validacao`; `busca` até 100 caracteres.
  - `POST /api/gestao/mensagens/{id}/reenviar` e `/descartar` (`ver_area_gestao` + `reenviar_mensagens`), id 1..2^31-1; 404 `nao_encontrado`, 409 `acao_invalida`; resposta `{"status": str}`.

- [ ] **Step 1: Testes:** `test_sem_sessao_401_e_sem_permissao_403`; `test_pagina_com_cursor`; `test_sem_ver_mensagens_esconde_o_texto` (Review Focus 5); `test_reenviar_e_descartar` (incl. 404 e 409, e 403 para operador); `test_cursor_invalido_422`.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar** `uv run pytest tests/api -q` → PASS.
- [ ] **Step 5: Commit** `feat: management activity and message actions API`.

### Task 7: API do Dashboard e menu com contagem

**Files:**
- Create: `src/tcg_sniper/consultas/dashboard.py`, `src/tcg_sniper/api/rotas_gestao_dashboard.py`
- Modify: `src/tcg_sniper/api/app.py`; `src/tcg_sniper/api/rotas_gestao_casamentos.py:145-155` (menu)
- Test: `tests/consultas/test_dashboard.py`, `tests/api/test_gestao_dashboard.py`

**Interfaces:**
- Consumes: Tasks 1, 3; `situacao_catalogo`, `situacao_monitor`.
- Produces:
  - `destino_novo(link_antigo: str) -> str` (decisão 6; o que não é migrado devolve `"antigo:/configuracoes…"` e o front monta com `enderecoAdminAntigo`).
  - `GET /api/gestao/dashboard` (`ver_area_gestao`; cada bloco só com a permissão dele, senão `null`) → `{"precisa": [{"texto", "rotulo", "destino"}] , "saude": [{"id","nome","estado","resumo"}] | null` (`ver_servicos`), `"oportunidades": {"top": [{"produto_id","nome","imagem","desconto_pct"}] (3, maior desconto), "abertas", "alertas_hoje", "alertas_semana"} | null` (`ver_oportunidades`), `"funil": {"liga", "monitorados", "so_ignorados", "sem_candidato", "casados_produtos", "casados_anuncios", "oportunidades"} | null` (`ver_catalogo`)`}`. "Precisa de você": esperando decisão (`revisar_casamentos`, rótulo "Revisar em sequência", destino `/gestao/casamentos?situacao=esperando_decisao`, a lista da 3A, que já tem o botão), serviços com problema ou desligados, monitor atrasado, IA a 80% do teto do dia ou do mês, carrinho a conferir, mensagens com falha e os demais `avisos(...)` do painel com `destino_novo`.
  - Menu: `casamentos_esperando` por `count` (sem montar a lista).

- [ ] **Step 1: Testes:** `test_destino_novo_traduz_cada_link_antigo` (tabela da decisão 6, incl. cada aba de logs); `test_precisa_some_quando_nao_ha_nada`; `test_ia_perto_do_teto_entra`; `test_funil_soma_com_o_catalogo`; `test_top_3_por_maior_desconto`; API: `test_grupo_403`, `test_operador_sem_ver_servicos_recebe_saude_null`, `test_menu_conta_igual_a_lista`.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar** `uv run pytest tests/api tests/consultas -q` → PASS.
- [ ] **Step 5: Commit** `feat: management dashboard API`.

### Task 8: Tela Serviços

**Files:**
- Create: `web/src/paginas/gestao/Servicos.tsx` (+ `.test.tsx`), `web/src/componentes/SeloEstado.tsx` (mapa único estado → classe e rótulo)
- Modify: `web/src/App.tsx` (rota `/gestao/servicos` com `ExigeTodas([ver_area_gestao, ver_servicos])`), `web/src/tipos.ts`

**Interfaces:**
- Consumes: Task 4.
- Produces: `SeloEstado({estado}: {estado: Estado})` com `{rodando: "badge badge-success", esperando: "badge badge-ghost", atrasado: "badge badge-warning", com_problema: "badge badge-error", desligado: "badge badge-neutral"}` e rótulos "rodando", "esperando", "atrasado", "com problema", "desligado"; tipos `ServicoGestao`, `Estado`.

- [ ] **Step 1: Testes (Vitest, `apiFalsa`):** carregando, erro com "Tentar de novo"; seis cartões com selo e texto truncado e o detalhe no `data-tip`; operador não vê chave, ações nem "Abrir"; admin desliga → a linha mostra "parando…" sem recarregar a página (uma chamada GET depois do POST, só da lista); erro do POST volta a chave e mostra o `alert`; "Abrir" com `target="_blank"` e tooltip "Só abre neste PC"; "Atividade" leva a `/gestao/atividade?servico=liga`; sub-linha do monitor com as duas chaves e "Já conferi" no carrinho; recarga a cada 60 s.
- [ ] **Step 2: Rodar e ver falhar:** `(cd web && npm test -- Servicos)`.
- [ ] **Step 3: Implementar** (cartão no celular, `table` a partir de `md`; chave = `toggle`; "parado de verdade desde HH:MM" no fuso do navegador como as outras telas).
- [ ] **Step 4: Rodar** `(cd web && npm test && npm run build)` → PASS.
- [ ] **Step 5: Commit** `feat: management services screen`.

### Task 9: Tela Atividade

**Files:**
- Create: `web/src/paginas/gestao/Atividade.tsx` (+ `.test.tsx`), `web/src/componentes/TextoWhatsApp.tsx` (renderiza `*negrito*` e `_itálico_` como `<strong>`/`<em>`, sem HTML cru)
- Modify: `web/src/App.tsx` (rota `/gestao/atividade` com `ver_area_gestao` + `ver_logs`), `web/src/tipos.ts`

**Interfaces:**
- Consumes: Task 6; `useFiltrosUrl` (`filtrosUrl.ts`).

- [ ] **Step 1: Testes:** filtros na URL e aplicados sozinhos (busca com debounce); "Carregar mais" usa `proximo` e acrescenta sem perder as linhas; linha mostra quando, serviço, o quê, produto com link para `/gestao/produtos/:id` e ASIN com link para a Amazon, resultado truncado; tocar abre o detalhe (`collapse` ou `modal`) com a observação completa; mensagem com negrito renderizado; sem `ver_mensagens` mostra "texto oculto"; sem `reenviar_mensagens` sem botões; "Reenviar" atualiza o status no lugar; interruptor "mostrar reinícios"; vazio com "Limpar filtros"; `TextoWhatsApp` não interpreta `<b>` (escapa).
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar** `(cd web && npm test && npm run build)` → PASS.
- [ ] **Step 5: Commit** `feat: management activity screen`.

### Task 10: Dashboard e menu da gestão

**Files:**
- Modify: `web/src/paginas/Gestao.tsx` (vira o Dashboard), `web/src/componentes/LayoutGestao.tsx`, `web/src/rotas.test.tsx:27-38`, `web/src/componentes/LayoutGestao.test.tsx`
- Create: `web/src/paginas/Gestao.test.tsx` (se não existir)

- [ ] **Step 1: Testes:** Dashboard na ordem "Precisa de você" → saúde (bolinhas com `SeloEstado`; no celular só o nome) → oportunidades (3 com foto e %) → funil (cada degrau é link para a lista filtrada); bloco `null` não aparece; "Precisa de você" some quando vazio; destino `antigo:…` vira link do admin antigo em nova aba; recarga a cada 60 s. Menu: ordem Dashboard · Casamentos · Catálogo · Ofertas (antigo) · Serviços · Atividade · Configurações (antigo) · Usuários · Acessos · Documentação da API (`ver_documentacao_api`); Mensagens e Logs não existem mais; o botão do menu no celular é focável pelo teclado (`<label tabIndex={0}>` com Enter/Espaço abrindo, ou `button` que alterna o `drawer-toggle`).
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.** `TELAS_ANTIGAS` fica só com Ofertas e Configurações.
- [ ] **Step 4: Rodar** `(cd web && npm test && npm run build)` → PASS.
- [ ] **Step 5: Commit** `feat: management dashboard and menu`.

### Task 11: Ponta a ponta, layout e documentação

**Files:**
- Modify: `tests/e2e/test_ponta_a_ponta.py`, `scripts/verificar_layout.py` (`TELAS_WEB` com `/gestao/servicos` e `/gestao/atividade`), `README.md` (gestão: Serviços, Atividade, Dashboard), `docs/IMPLANTACOES.md` (seção da 3B: sem migração, conferências depois do deploy), `docs/PENDENCIAS.md` (3B em "Concluídas", itens do menu da seção 2 marcados, item novo: Configurações/Ofertas para a 3C e "fase 4: apagar `admin/`, serviço `admin` do compose e porta 8000" com a tabela de cobertura deste plano)

- [ ] **Step 1: Ponta a ponta:** admin abre Serviços, desliga e liga o Casador (vê "parando…"/"parado de verdade" ou "iniciando…"), abre a Atividade filtrada no Casador e vê a ação de gestão com o nome dele; Dashboard carrega os quatro blocos; operador não vê chave nem "Abrir"; largura 390 e 1440 px nos temas claro e escuro, sem rolagem horizontal.
- [ ] **Step 2: Rodar** `uv run pytest tests/e2e -q` e `uv run python scripts/verificar_layout.py` (com os serviços de teste do ponta a ponta) → PASS.
- [ ] **Step 3: Suíte inteira:** `uv run pytest -q`, `uvx ruff check src tests`, `(cd web && npm test && npm run build)` → PASS.
- [ ] **Step 4: Commit** `docs: phase 3B docs and pending list`.
