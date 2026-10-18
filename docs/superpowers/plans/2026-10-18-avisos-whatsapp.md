# Avisos no WhatsApp (padrão único e catálogo) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Toda mensagem de WhatsApp passa a sair de um módulo só (`src/tcg_sniper/avisos/`), num formato único para celular, sem endereço do sistema, com um catálogo de 28 tipos (cada um desligável em Configurações → Avisos), agrupamento de repetições (lembrete a cada 2 h e "✅ resolvido") e um vigia que avisa quando um serviço fica mudo.

**Architecture:** `avisos/catalogo.py` define `TipoAviso`, a `DefinicaoAviso` de cada tipo e os dados (`Dados`, `Negrito`); `avisos/formato.py` é a única função que monta texto (escape, corte em 1500 caracteres, fuso, guarda de URL); `avisos/servico.py` tem `avisar`/`resolver` (regra de repetição em `estado_aviso`, liga/desliga em `config_aviso`) e grava na mesma tabela de saída (`mensagem_saida`) que o serviço `notificador` já envia. Os serviços deixam de receber um `Notificador` e passam a receber um `Avisador` (avisar/resolver/resolver_todos); o admin e o notificador, que já estão numa sessão, chamam `avisar(s, ...)` direto. O vigia roda dentro do serviço `manutencao` e lê `sinal_servico` (batida de 60 s numa thread de cada coletor) e `estado_notificador`.

**Tech Stack:** Python 3.12, uv, SQLAlchemy 2 + Alembic, Postgres 16, FastAPI + Jinja2 + DaisyUI 5, pytest (+ respx), Docker Compose, Evolution API.

**Spec:** `docs/superpowers/specs/2026-10-18-avisos-whatsapp-design.md`

## Global Constraints

- Nomes, comentários, mensagens e textos em português, como o resto do código. Mensagens de commit em inglês, no formato `feat:`/`fix:`/`test:`/`docs:`, **sem** linha `Co-Authored-By` nem qualquer trailer de IA.
- Repositório público: nada de dado pessoal (telefone, grupo, IP real, e-mail) em código, teste, fixture ou documento.
- Nenhuma mensagem de WhatsApp leva endereço do sistema: admin `:8000`, noVNC `:6080`/`:6081`, nem o `host_publico` de Configurações → Geral. Links de produto da Amazon (`amazon.com.br`) e da LigaMagic (`ligamagic.com.br`) são permitidos. Ações sem link dizem onde fazer: "noVNC da Amazon (porta 6081)", "Admin → Serviços → Amazon → Retomar".
- Estilo único (verbatim do spec): emoji de severidade (`FALHA` 🔴, `ATENCAO` 🟡, `CONCLUIDO` ✅, `OPORTUNIDADE` 💰; "resolvido" usa ✅) + título em negrito + linhas com "•" + "*O que fazer:*" + rodapé em itálico `_dd/mm HH:MM · <origem>_`, hora no fuso de Configurações → Geral; escape de `*`, `_`, `~` e crase vindos dos dados; corte em ~1500 caracteres com "…".
- Repetição (verbatim do spec): tipos que agrupam saem uma vez, voltam como lembrete a cada 2 h (`MENSAGEM_NAO_ENVIADA`: no máximo 1/h) enquanto continuarem e fecham com "✅ <título> resolvido · N vezes em <duração>". Tipo desligado: o estado é atualizado e nada é enviado.
- `avisar`/`resolver` nunca propagam exceção para o chamador (falha vira log). Única exceção: com `formato.ESTRITO = True` (só nos testes) um endereço do sistema levanta `UrlProibida`.
- Preço conferido = itens + impostos, **sem** frete (regra do usuário; o frete só aparece à parte).
- O que não muda (spec): o serviço `notificador` (envio, tentativas, validade das oportunidades de Configurações → Geral; avisos do admin não vencem), a tabela `mensagem_saida` e a tela Mensagens.
- Admin: só componentes do DaisyUI 5 e utilitários do Tailwind, classes literais (nunca concatenadas); toda tarefa que mexe em template regenera `src/tcg_sniper/admin/static/admin.css` com `uv run python scripts/gerar_css.py` e commita.
- Testes só no Postgres de teste (container `postgres-teste`, porta 5433). Cada lane usa o próprio banco (o fixture `engine` apaga o schema): `docker compose exec -T postgres-teste createdb -U tcg tcg_test_<lane>` (se ainda não existir) e, ao fim de cada tarefa, `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_<lane> uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`, ambos verdes. `<lane>` é o número da tarefa (ex.: `tcg_test_t4`).
- Nunca mexer no checkout nem na stack de produção: nada de `docker compose up/down/build/restart` nem `migrate` contra o banco de produção. Cada lane trabalha no próprio worktree (`superpowers:using-git-worktrees`).

## Review Focus

1. **Notificador parado ou WhatsApp fora por horas** com o mesmo problema acontecendo a cada passo (CAPTCHA, serviço mudo a cada minuto): ao voltar, sai **um** lembrete, não um por janela perdida nem um por ocorrência. Teste na Task 2 (`test_lembretes_nao_acumulam_depois_de_horas_parado`).
2. **Erro de terceiros com endereço dentro** (ex.: `ConnectError('http://192.168.0.10:8000/x')`, corpo de resposta com URL interna) em produção: o endereço vira "[endereço removido]", o aviso sai e o serviço não cai; nos testes isso é exceção. Testes na Task 1 (`test_fora_do_modo_estrito_remove_o_endereco_e_registra_no_log`) e na Task 2 (`test_fora_do_modo_estrito_avisar_remove_e_enfileira`).
3. **Serviço que nunca deu sinal** (container que não sobe depois do deploy, tabela `sinal_servico` sem a linha dele): o vigia conta a partir de quando ele mesmo começou e avisa depois de 10 min. Teste na Task 7 (`test_servico_que_nunca_deu_sinal_conta_desde_o_inicio_da_vigia`).
4. **Monitor ocioso** (tudo em dia, um passo por minuto): "rodada do monitor" só sai quando uma rodada com pelo menos um anúncio lido termina, nunca a cada passo vazio. Testes na Task 6 (`test_monitor_ocioso_nao_avisa_rodada`, `test_rodada_do_monitor_avisa_quando_fica_em_dia`).
5. **Texto gigante** (traceback de vários KB, nome de produto enorme, muitas linhas): a mensagem fica com no máximo 1500 caracteres, mantém título, "O que fazer" e rodapé, e marca o corte com "…". Testes na Task 1 (`test_corta_mensagem_longa_mantendo_titulo_acao_e_rodape`, `test_trecho_gigante_e_cortado`).

## Decisões tomadas neste plano (o spec não fixava)

- **"Pelo Notificador atual" = pela mesma tabela de saída, na mesma transação.** `avisar(s, …)` grava `estado_aviso` e chama `repositorio_mensagens.enfileirar(s, …)` dentro de um SAVEPOINT da sessão do chamador; falha desfaz só o savepoint e vira log. `NotificadorFila`, `criar_notificador` e o Protocol `Notificador` saem na Task 9 (o `Destino` fica). O serviço `notificador` continua enviando a tabela como hoje.
- **Injeção:** quem hoje recebe `notificador: Notificador` passa a receber `avisador: Avisador` (Protocol com `avisar(tipo, chave, dados)`, `resolver(tipo, chave)`, `resolver_todos(tipo)`); em produção `AvisadorBanco(sessoes)` abre a própria transação. Nos testes, `fakes.AvisadorFake` guarda os avisos e monta o texto pelo `formato` em modo estrito (assim todo teste de serviço também é teste de URL).
- **Dados:** `Dados(linhas, titulo_extra, destaque, acao, link_produto)`; uma linha é texto ou tupla de trechos, e `Negrito("R$ 1.299,90")` é o único jeito de pôr negrito em dado (é escapado e depois envolvido em `*`). `acao` dos dados substitui a ação padrão do tipo (catálogo); a ação é sempre texto nosso, nunca leva dado.
- **Escape:** `*`→`∗` (U+2217), `_`→`ˍ` (U+02CD), `~`→`˜` (U+02DC), crase→`ˋ` (U+02CB). O WhatsApp não tem caractere de escape; sósias mantêm a leitura. Por isso testes que procuram dado com esses caracteres olham `dados.linhas`, não o texto.
- **Corte:** cada trecho de dado ≤ 300 caracteres, `titulo_extra` ≤ 120, `destaque` ≤ 200; se a mensagem passar de 1500, as últimas linhas "•" saem e entra "• …" (título, ação, link e rodapé ficam sempre).
- **Lembrete:** `<emoji> *<título>[ · extra] continua · N vezes desde HH:MM*` + o corpo da ocorrência atual; "desde dd/mm HH:MM" quando o primeiro foi em outro dia. **Resolvido:** `✅ *<título>[ · chave] resolvido · N vezes em <duração>*` + rodapé (a chave entra no título quando não é `"geral"`, porque `resolver` não recebe dados). Duração: "menos de 1 min", "30 min", "2 h", "1 h 12 min", "1 d 2 h".
- **Tipos que não agrupam** não gravam `estado_aviso` (só enviam, se ligados). `resolver` só manda "✅" se algum envio saiu **e** o tipo está ligado agora.
- **Modo estrito:** `formato.ESTRITO` (padrão `False`) é ligado em `tests/conftest.py`. Em produção o endereço é removido e vai para o log.
- **Sinal de vida:** coletor-liga, coletor-amazon e casador não tinham batida. Uma tabela nova `sinal_servico` (na mesma migração) recebe uma batida a cada 60 s de uma thread (`vigia.Batimento`) iniciada no `cli.py`; o notificador continua usando `estado_notificador.ultimo_ciclo_em`. Só `PAUSADO` (manual ou por erros seguidos) é ignorado; pausado por desafio ainda é vigiado. Sem linha nenhuma, conta desde o início do vigia.
- **Quando cada problema resolve:** `LIGA_DESAFIO` no início do próximo job (só roda com a Liga ativa, isto é, retomada); `LIGA_COLETA_FALHOU`/`LIGA_ERRO` e `AMAZON_BUSCA_FALHOU` numa conclusão ok **ou parcial**; `AMAZON_CAPTCHA` na próxima página aberta sem CAPTCHA (monitor, busca ou conferência); `AMAZON_PAUSADA` no primeiro passo com a Amazon ativa; `AMAZON_ERRO` no próximo passo sem exceção; `AMAZON_SEM_LOGIN` na próxima conferência que não cai no login; `AMAZON_CARRINHO` (chave ASIN) quando a retirada vê o carrinho sem o item ou no "Já conferi"; `IA_PAUSADA` no primeiro ciclo ativo; `IA_FALHAS_SEGUIDAS` e `IA_SEM_ORCAMENTO` (todos os períodos abertos, `resolver_todos`) na primeira chamada ok da rodada; `BACKUP_ERRO` no próximo backup ok; `SERVICO_SEM_SINAL` quando o sinal volta. `MENSAGEM_NAO_ENVIADA` nunca resolve (só lembra, no máximo 1/h).
- **Liga com etapa que falhou:** não sai "concluída" nem "parcial" (o `LIGA_COLETA_FALHOU` da etapa já saiu); antes saía o resumo mesmo assim.
- **`IA_SEM_ORCAMENTO`:** chave legível "dia 18/10" ou "mês 10/2026" (vira o `titulo_extra` e o sufixo do "resolvido").
- **`AMAZON_MONITOR_CONCLUIDO`:** uma rodada vai do primeiro anúncio lido até o primeiro passo em que o monitor não tem nada vencido; "Preços em queda" = leituras em que a melhor oferta ficou abaixo do preço atual anterior; conta também as conferências de checkout.
- **`MENSAGEM_NAO_ENVIADA`:** reconhecida pelo começo do texto (`formato.eh_do_tipo`), já que `mensagem_saida` não muda; lista até 5 falhas definitivas da última hora (`#id para <destino>: <erro>`).
- **`SERVICO_PAUSADO_MANUAL`:** chave = coletor; sai nas rotas de pausar/retomar de Serviços (LigaMagic, Amazon, casador, notificador, manutenção e o "Retomar" da Liga), com "Novo estado: pausado/ativo". Pausar com desafio pendente não pausa nem avisa.
- **Oportunidade:** a variação vai no rótulo ("Amazon (Collector Booster Box): …"); frete 0 vira "frete grátis".
- **Configurações → Geral:** a explicação de "IP ou nome deste PC na rede" deixa de dizer que vai nas mensagens.

---

## Ondas (para execução paralela)

- **Onda A:** Task 1 (catálogo e formato).
- **Onda B (em paralelo):** Task 2 (estado, migração e serviço `avisar`/`resolver`) e Task 3 (dados da oportunidade) — ambas dependem só da 1.
- **Onda C (em paralelo):** Task 4 (LigaMagic), Task 5 (casador, manutenção e notificador) e Task 6 (Amazon: varredura, monitor e oportunidade) — dependem da 2; a 6 também da 3.
- **Onda D (em paralelo):** Task 7 (vigia de serviços) — depende da 5; Task 8 (admin: aba Avisos e pausar/retomar) — depende da 6.
- **Onda E:** Task 9 (testes globais, limpeza do `Notificador`, README e `docs/PENDENCIAS.md`) — depende de todas.
- Conflitos esperados e como resolver: `src/tcg_sniper/cli.py` (Tasks 4, 5 e 6 mexem cada uma no próprio `elif`; Task 7 acrescenta o `Batimento` nos três ramos: manter tudo); `tests/fakes.py` (Task 2 acrescenta `AvisadorFake`; Task 9 tira `NotificadorFake`); `src/tcg_sniper/admin/app.py` (Task 6 só em `carrinho_conferido`; Task 8 no resto); `src/tcg_sniper/manutencao/servico.py` (Task 5, depois Task 7 em `__init__`/`tick`); `admin.css` (só a Task 8 regenera; na integração, se houver conflito, rodar `uv run python scripts/gerar_css.py` e commitar).

## Arquivos

| Arquivo | Responsabilidade | Tasks |
|---|---|---|
| `src/tcg_sniper/avisos/__init__.py`, `catalogo.py` (novos) | `TipoAviso`, `Severidade`, `Negrito`, `Dados`, `DefinicaoAviso`, `CATALOGO` | 1 |
| `src/tcg_sniper/avisos/formato.py` (novo) | montar texto, lembrete e resolvido; escape; corte; guarda de URL | 1 |
| `tests/conftest.py` | liga `formato.ESTRITO` | 1 |
| `src/tcg_sniper/db/models.py`, migração `e4b7c2d9a1f6_avisos.py` (nova) | `estado_aviso`, `config_aviso`, `sinal_servico` | 2 |
| `src/tcg_sniper/avisos/servico.py` (novo), `tests/fakes.py` | `avisar`, `resolver`, `resolver_todos`, liga/desliga, `Avisador`, `AvisadorBanco`, `AvisadorFake` | 2 |
| `src/tcg_sniper/oportunidades/mensagens.py` | `dados_oportunidade` (e, na Task 6, sai `mensagem_oportunidade`) | 3, 6 |
| `src/tcg_sniper/coletor_liga/execucao.py`, `agendador.py`, `listagens.py`, `produtos.py` | avisos da LigaMagic | 4 |
| `src/tcg_sniper/casador/servico.py`, `manutencao/servico.py`, `notificador/servico.py`, `db/repositorio_mensagens.py` | avisos da IA, do backup e da mensagem não enviada | 5 |
| `src/tcg_sniper/coletor_amazon/varredura.py`, `busca.py`, `monitor.py`, `admin/app.py` (`carrinho_conferido`) | avisos da Amazon, rodada do monitor, oportunidade | 6 |
| `src/tcg_sniper/avisos/vigia.py` (novo), `manutencao/servico.py`, `cli.py` | sinal de vida e `SERVICO_SEM_SINAL` | 7 |
| `src/tcg_sniper/admin/app.py`, `templates/configuracoes.html`, `formularios_config.py`, `static/admin.css`, `scripts/verificar_layout.py` | aba Avisos, `SERVICO_PAUSADO_MANUAL` | 8 |
| `tests/avisos/test_regras_globais.py` (novo), `notificador/__init__.py`, `notificador/base.py`, `notificador/fila.py` (sai), `README.md`, `docs/PENDENCIAS.md` | regras globais e limpeza | 9 |

---

### Task 1: Catálogo e formato

**Files:**
- Create: `src/tcg_sniper/avisos/__init__.py`
- Create: `src/tcg_sniper/avisos/catalogo.py`
- Create: `src/tcg_sniper/avisos/formato.py`
- Modify: `tests/conftest.py` (liga o modo estrito)
- Test: `tests/avisos/test_formato.py` (novo)

**Interfaces:**
- Consumes: `tcg_sniper.notificador.base.Destino` (`ADMIN`, `OPORTUNIDADES`).
- Produces:
  - `catalogo.CHAVE_GERAL = "geral"`; `catalogo.Severidade` (StrEnum: `FALHA="falha"`, `ATENCAO="atencao"`, `CONCLUIDO="concluido"`, `OPORTUNIDADE="oportunidade"`); `catalogo.EMOJI: dict[Severidade, str]`; `catalogo.EMOJI_RESOLVIDO = "✅"`.
  - `catalogo.TipoAviso` (StrEnum; nome = membro do spec, valor = nome em minúsculas): `LIGA_COLETA_CONCLUIDA`, `LIGA_COLETA_PARCIAL`, `LIGA_COLETA_FALHOU`, `LIGA_DESAFIO`, `LIGA_PRODUTOS_NOVOS`, `LIGA_INTERROMPIDA`, `LIGA_ERRO`, `AMAZON_BUSCA_CONCLUIDA`, `AMAZON_MONITOR_CONCLUIDO`, `AMAZON_BUSCA_PARCIAL`, `AMAZON_BUSCA_FALHOU`, `AMAZON_CAPTCHA`, `AMAZON_SEM_LOGIN`, `AMAZON_CARRINHO`, `AMAZON_PAUSADA`, `AMAZON_ERRO`, `AMAZON_INTERROMPIDA`, `IA_RODADA_CONCLUIDA`, `IA_PAUSADA`, `IA_SEM_ORCAMENTO`, `IA_FALHAS_SEGUIDAS`, `BACKUP_CONCLUIDO`, `BACKUP_ERRO`, `BACKUP_INTERROMPIDO`, `SERVICO_SEM_SINAL`, `SERVICO_PAUSADO_MANUAL`, `MENSAGEM_NAO_ENVIADA`, `OPORTUNIDADE`.
  - `catalogo.Negrito(texto: str)` (frozen); `catalogo.Trecho = str | Negrito`; `catalogo.Linha = str | tuple[Trecho, ...]`.
  - `catalogo.Dados(linhas: tuple[Linha, ...] = (), titulo_extra: str | None = None, destaque: str | None = None, acao: str | None = None, link_produto: str | None = None)` (frozen).
  - `catalogo.DefinicaoAviso(severidade, grupo: Destino, titulo: str, origem: str, descricao: str, exemplo: Dados, agrupa: bool = False, lembrete: timedelta | None = None, acao: str | None = None, ligado_padrao: bool = True)` (frozen); `catalogo.CATALOGO: dict[TipoAviso, DefinicaoAviso]`.
  - `formato.ESTRITO: bool = False`; `formato.LIMITE = 1500`; `formato.REMOVIDO = "[endereço removido]"`; `formato.UrlProibida(ValueError)`.
  - `formato.Aviso(tipo, titulo_extra, linhas, acao, origem, quando, link_produto=None, destaque=None)` (frozen).
  - `formato.aviso_de(tipo: TipoAviso, dados: Dados, quando: datetime) -> Aviso`.
  - `formato.formatar(aviso: Aviso, zona: ZoneInfo, host_publico: str | None = None, *, estrito: bool | None = None) -> str`.
  - `formato.formatar_lembrete(aviso: Aviso, ocorrencias: int, desde: datetime, zona: ZoneInfo, host_publico: str | None = None, *, estrito: bool | None = None) -> str`.
  - `formato.formatar_resolvido(tipo: TipoAviso, chave: str, ocorrencias: int, primeiro_em: datetime, agora: datetime, zona: ZoneInfo, host_publico: str | None = None, *, estrito: bool | None = None) -> str`.
  - `formato.conferir_urls(texto: str, host_publico: str | None = None, *, estrito: bool | None = None) -> str`.
  - `formato.escapar(texto: str) -> str`, `formato.formatar_duracao(duracao: timedelta) -> str`, `formato.cabecalho(tipo: TipoAviso) -> str`, `formato.eh_do_tipo(texto: str, tipo: TipoAviso) -> bool`.

- [ ] **Step 1: Banco da lane**

Run: `docker compose exec -T postgres-teste createdb -U tcg tcg_test_t1`
Expected: sem saída (ou "already exists").

- [ ] **Step 2: Escrever os testes (falham)**

Crie `tests/avisos/test_formato.py`:

```python
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from tcg_sniper.avisos.catalogo import CATALOGO, CHAVE_GERAL, Dados, Negrito, Severidade, TipoAviso
from tcg_sniper.avisos.formato import (
    LIMITE,
    UrlProibida,
    aviso_de,
    cabecalho,
    conferir_urls,
    eh_do_tipo,
    escapar,
    formatar,
    formatar_duracao,
    formatar_lembrete,
    formatar_resolvido,
)
from tcg_sniper.notificador.base import Destino

SP = ZoneInfo("America/Sao_Paulo")
QUANDO = datetime(2026, 10, 18, 13, 42, tzinfo=UTC)  # 10:42 em São Paulo
HOST = "192.168.0.10"

ESPERADOS = {
    TipoAviso.LIGA_COLETA_CONCLUIDA: (
        "✅ *Liga · coleta concluída · 18/10*\n"
        "• Listagens: ok · 20 de 20 categorias · 3 produtos novos\n"
        "• Produtos: ok · 412 ok · 0 falhas\n"
        "• Duração: 1 h 12 min\n"
        "_18/10 10:42 · coletor Liga_"
    ),
    TipoAviso.LIGA_COLETA_PARCIAL: (
        "🟡 *Liga · coleta parcial · 18/10*\n"
        "• Listagens: ok · 20 de 20 categorias · 0 produtos novos\n"
        "• Produtos: parcial · 380 ok · 32 falhas\n"
        "• Duração: 1 h 5 min\n"
        "\n"
        "*O que fazer:* Nada urgente; se repetir, veja Admin → Logs → LigaMagic.\n"
        "_18/10 10:42 · coletor Liga_"
    ),
    TipoAviso.LIGA_COLETA_FALHOU: (
        "🔴 *Liga · coleta falhou*\n"
        "• Etapa: Coleta dos produtos ativos\n"
        "• Falhas: 300 de 412 produtos\n"
        "\n"
        "*O que fazer:* O layout da LigaMagic pode ter mudado: veja Admin → Logs → LigaMagic e os HTMLs na pasta falhas.\n"
        "_18/10 10:42 · coletor Liga_"
    ),
    TipoAviso.LIGA_DESAFIO: (
        "🔴 *Liga · desafio do Cloudflare*\n"
        "• Página: /?view=cards/search&card=categ%3D10\n"
        "• A coleta fica pausada até você retomar\n"
        "\n"
        "*O que fazer:* Resolva no noVNC da Liga (porta 6080) e depois Admin → Serviços → LigaMagic → Retomar.\n"
        "_18/10 10:42 · coletor Liga_"
    ),
    TipoAviso.LIGA_PRODUTOS_NOVOS: (
        "🟡 *Liga · produtos novos no catálogo*\n"
        "• 3 produtos novos nas listagens\n"
        "\n"
        "*O que fazer:* Ative os que quiser acompanhar em Admin → Catálogo → filtro Novos.\n"
        "_18/10 10:42 · coletor Liga_"
    ),
    TipoAviso.LIGA_INTERROMPIDA: (
        "🟡 *Liga · coleta interrompida*\n"
        "• 2 coleta(s) marcada(s) como falha: o coletor reiniciou no meio do job\n"
        "\n"
        "*O que fazer:* A coleta de hoje pode não rodar de novo sozinha: Admin → Serviços → LigaMagic → Rodar agora.\n"
        "_18/10 10:42 · coletor Liga_"
    ),
    TipoAviso.LIGA_ERRO: (
        "🔴 *Liga · erro inesperado*\n"
        "• Onde: Coleta dos produtos ativos 41\n"
        "• Erro: TimeoutError('página não carregou')\n"
        "\n"
        "*O que fazer:* Veja os logs do coletor (docker compose logs coletor-liga); a próxima coleta tenta de novo.\n"
        "_18/10 10:42 · coletor Liga_"
    ),
    TipoAviso.AMAZON_BUSCA_CONCLUIDA: (
        "✅ *Amazon · busca concluída · ciclo 42*\n"
        "• Buscas: 37 ok · 1 falha\n"
        "• Duração: 2 h 5 min\n"
        "_18/10 10:42 · coletor Amazon_"
    ),
    TipoAviso.AMAZON_MONITOR_CONCLUIDO: (
        "✅ *Amazon · rodada do monitor*\n"
        "• Anúncios lidos: 24\n"
        "• Preços em queda: 2\n"
        "• Conferências de checkout: 1\n"
        "• Duração: 14 min\n"
        "_18/10 10:42 · monitor Amazon_"
    ),
    TipoAviso.AMAZON_BUSCA_PARCIAL: (
        "🟡 *Amazon · busca parcial · ciclo 42*\n"
        "• Buscas: 30 ok · 8 falhas\n"
        "• Duração: 2 h 10 min\n"
        "\n"
        "*O que fazer:* Nada urgente; se repetir, veja Admin → Logs → Amazon.\n"
        "_18/10 10:42 · coletor Amazon_"
    ),
    TipoAviso.AMAZON_BUSCA_FALHOU: (
        "🔴 *Amazon · busca falhou · ciclo 42*\n"
        "• Buscas: 12 ok · 26 falhas\n"
        "• Duração: 1 h 40 min\n"
        "\n"
        "*O que fazer:* O layout da Amazon pode ter mudado: veja Admin → Logs → Amazon e os HTMLs na pasta falhas.\n"
        "_18/10 10:42 · coletor Amazon_"
    ),
    TipoAviso.AMAZON_CAPTCHA: (
        "🔴 *Amazon · CAPTCHA*\n"
        "• Página: /s?k=aetherdrift+commander\n"
        "• Busca, monitor e conferência pausados até você retomar\n"
        "• Uma conferência deixou 1× B0DNV55QBS no carrinho: sai sozinho se você retomar em até 30 min; "
        "senão confira à mão\n"
        "\n"
        "*O que fazer:* Resolva no noVNC da Amazon (porta 6081) e depois Admin → Serviços → Amazon → Retomar.\n"
        "_18/10 10:42 · coletor Amazon_"
    ),
    TipoAviso.AMAZON_SEM_LOGIN: (
        "🔴 *Amazon · conta sem login*\n"
        "• A conferência de checkout parou; o monitor de preço continua\n"
        "\n"
        "*O que fazer:* Faça login na conta Amazon pelo noVNC da Amazon (porta 6081) e depois "
        "Admin → Serviços → Amazon → Retomar conferência.\n"
        "_18/10 10:42 · coletor Amazon_"
    ),
    TipoAviso.AMAZON_CARRINHO: (
        "🔴 *Amazon · conferir o carrinho · B0DNV55QBS*\n"
        "• Pode haver 1× B0DNV55QBS de uma conferência automática no carrinho\n"
        "• Motivo: carrinho com outros itens (B0AAAA0001)\n"
        "\n"
        "*O que fazer:* Confira o carrinho pelo noVNC da Amazon (porta 6081), tire o item se não for seu e "
        "clique em Admin → Serviços → Já conferi.\n"
        "_18/10 10:42 · coletor Amazon_"
    ),
    TipoAviso.AMAZON_PAUSADA: (
        "🔴 *Amazon · pausada*\n"
        "• Motivo: 10 páginas seguidas com falha (bloqueio ou layout novo?)\n"
        "• Com a Amazon pausada, a retirada automática de item do carrinho também para\n"
        "\n"
        "*O que fazer:* Veja os logs (docker compose logs coletor-amazon) e depois Admin → Serviços → Amazon → Retomar.\n"
        "_18/10 10:42 · coletor Amazon_"
    ),
    TipoAviso.AMAZON_ERRO: (
        "🟡 *Amazon · erro inesperado*\n"
        "• Erro: RuntimeError('navegador fechou')\n"
        "\n"
        "*O que fazer:* Nada a fazer se não repetir: nova tentativa em 15 min. Se repetir, veja os logs "
        "(docker compose logs coletor-amazon).\n"
        "_18/10 10:42 · coletor Amazon_"
    ),
    TipoAviso.AMAZON_INTERROMPIDA: (
        "🟡 *Amazon · ciclo interrompido*\n"
        "• 1 ciclo(s) marcado(s) como falha: o coletor reiniciou\n"
        "\n"
        "*O que fazer:* Nada a fazer: a fila continua sozinha.\n"
        "_18/10 10:42 · coletor Amazon_"
    ),
    TipoAviso.IA_RODADA_CONCLUIDA: (
        "✅ *IA · rodada concluída*\n"
        "• Avaliados: 12\n"
        "• Confirmados pelo automático: 3\n"
        "• Ignorados pelo automático: 5\n"
        "• Esperando você: 4\n"
        "\n"
        "*O que fazer:* Revise os pendentes em Admin → Casamentos.\n"
        "_18/10 10:42 · casador (IA)_"
    ),
    TipoAviso.IA_PAUSADA: (
        "🔴 *IA · casador pausado*\n"
        "• Motivo: chave recusada pela OpenAI (401)\n"
        "\n"
        "*O que fazer:* Corrija a chave da OpenAI (.env) ou Admin → Configurações → IA e depois "
        "Admin → Serviços → Casador → Retomar.\n"
        "_18/10 10:42 · casador (IA)_"
    ),
    TipoAviso.IA_SEM_ORCAMENTO: (
        "🟡 *IA · sem orçamento · dia 18/10*\n"
        "• Motivo: teto diário de US$ 1,00 atingido\n"
        "\n"
        "*O que fazer:* Volta sozinho no próximo período, ou suba o teto em Admin → Configurações → IA.\n"
        "_18/10 10:42 · casador (IA)_"
    ),
    TipoAviso.IA_FALHAS_SEGUIDAS: (
        "🟡 *IA · falhas seguidas*\n"
        "• 3 chamadas seguidas falharam; a rodada parou\n"
        "• Última: OpenAI 503\n"
        "\n"
        "*O que fazer:* Nada a fazer se for passageiro: a próxima rodada tenta de novo.\n"
        "_18/10 10:42 · casador (IA)_"
    ),
    TipoAviso.BACKUP_CONCLUIDO: (
        "✅ *Backup · concluído · 18/10*\n"
        "• Tamanho: 607,3 KB\n"
        "• Cópia no R2: sim\n"
        "• Linhas antigas apagadas: 1.234\n"
        "_18/10 10:42 · manutenção_"
    ),
    TipoAviso.BACKUP_ERRO: (
        "🔴 *Backup · erro · 18/10*\n"
        "• Erro: envio ao R2 falhou: EndpointConnectionError\n"
        "• O backup local ficou salvo\n"
        "\n"
        "*O que fazer:* Tenta de novo amanhã às 04:00; veja Admin → Logs → Manutenção.\n"
        "_18/10 10:42 · manutenção_"
    ),
    TipoAviso.BACKUP_INTERROMPIDO: (
        "🟡 *Backup · interrompido*\n"
        "• 1 execução(ões) interrompida(s) no meio: o serviço de manutenção reiniciou\n"
        "\n"
        "*O que fazer:* Nada a fazer: o backup do dia roda de novo.\n"
        "_18/10 10:42 · manutenção_"
    ),
    TipoAviso.SERVICO_SEM_SINAL: (
        "🔴 *Serviço sem sinal · coletor-amazon*\n"
        "• Último sinal: 18/10 10:30 (há 12 min)\n"
        "\n"
        "*O que fazer:* Veja se o container está de pé (docker compose ps) e os logs dele.\n"
        "_18/10 10:42 · vigia_"
    ),
    TipoAviso.SERVICO_PAUSADO_MANUAL: (
        "🟡 *Serviço mudou no admin · Amazon*\n"
        "• Novo estado: pausado\n"
        "_18/10 10:42 · admin_"
    ),
    TipoAviso.MENSAGEM_NAO_ENVIADA: (
        "🔴 *WhatsApp · mensagem não enviada*\n"
        "• #123 para oportunidades: HTTP 400: grupo não encontrado\n"
        "\n"
        "*O que fazer:* Confira a instância e os grupos em Admin → Configurações → Geral e reenvie em "
        "Admin → Mensagens.\n"
        "_18/10 10:42 · notificador_"
    ),
    TipoAviso.OPORTUNIDADE: (
        "💰 *Oportunidade · 18% abaixo da Liga*\n"
        "*Final Fantasy - Caixa de Booster de Jogo*\n"
        "• Amazon: *R$ 1.299,90* (conferido, com impostos; frete à parte)\n"
        "• Vendido por: Amazon · Prime\n"
        "• Liga: a partir de R$ 1.589,00 · 12 lojas · média R$ 1.640,00\n"
        "https://www.amazon.com.br/dp/B0TESTE123\n"
        "_18/10 10:42 · monitor Amazon_"
    ),
}


def texto_de(tipo, dados=None, host=HOST, estrito=True):
    return formatar(aviso_de(tipo, dados or CATALOGO[tipo].exemplo, QUANDO), SP, host, estrito=estrito)


def test_catalogo_cobre_todos_os_tipos():
    assert set(CATALOGO) == set(TipoAviso) == set(ESPERADOS)
    assert len(TipoAviso) == 28


@pytest.mark.parametrize("tipo", list(TipoAviso))
def test_exemplo_de_cada_tipo_igual_ao_modelo(tipo):
    assert texto_de(tipo) == ESPERADOS[tipo]


def test_regras_do_catalogo():
    for tipo, d in CATALOGO.items():
        assert d.ligado_padrao is True, tipo
        assert (d.lembrete is not None) == d.agrupa, tipo
        assert d.grupo is (Destino.OPORTUNIDADES if tipo is TipoAviso.OPORTUNIDADE else Destino.ADMIN), tipo
        if d.agrupa and tipo is not TipoAviso.MENSAGEM_NAO_ENVIADA:
            assert d.lembrete == timedelta(hours=2), tipo
        assert d.descricao, tipo
    assert CATALOGO[TipoAviso.MENSAGEM_NAO_ENVIADA].lembrete == timedelta(hours=1)
    assert CATALOGO[TipoAviso.OPORTUNIDADE].severidade is Severidade.OPORTUNIDADE
    agrupam = {t for t, d in CATALOGO.items() if d.agrupa}
    assert agrupam == {
        TipoAviso.LIGA_COLETA_FALHOU, TipoAviso.LIGA_DESAFIO, TipoAviso.LIGA_ERRO, TipoAviso.AMAZON_BUSCA_FALHOU,
        TipoAviso.AMAZON_CAPTCHA, TipoAviso.AMAZON_SEM_LOGIN, TipoAviso.AMAZON_CARRINHO, TipoAviso.AMAZON_PAUSADA,
        TipoAviso.AMAZON_ERRO, TipoAviso.IA_PAUSADA, TipoAviso.IA_SEM_ORCAMENTO, TipoAviso.IA_FALHAS_SEGUIDAS,
        TipoAviso.BACKUP_ERRO, TipoAviso.SERVICO_SEM_SINAL, TipoAviso.MENSAGEM_NAO_ENVIADA,
    }


def test_escapa_formatacao_vinda_dos_dados():
    dados = Dados(titulo_extra="*x*", destaque="_y_", linhas=("Erro: *a* _b_ ~c~ `d`", ("Preço: ", Negrito("R$ *1*"))))
    texto = texto_de(TipoAviso.AMAZON_ERRO, dados)
    assert texto.startswith("🟡 *Amazon · erro inesperado · ∗x∗*\n*ˍyˍ*\n")
    assert "• Erro: ∗a∗ ˍbˍ ˜c˜ ˋdˋ\n" in texto
    assert "• Preço: *R$ ∗1∗*\n" in texto
    assert escapar("sem nada") == "sem nada"


def test_acao_dos_dados_substitui_a_padrao_e_none_some():
    sem = texto_de(TipoAviso.IA_RODADA_CONCLUIDA, Dados(linhas=("Avaliados: 1",)))
    assert "O que fazer" not in sem
    com = texto_de(TipoAviso.IA_RODADA_CONCLUIDA, Dados(linhas=("Avaliados: 1",), acao="Revise."))
    assert "\n\n*O que fazer:* Revise.\n_18/10 10:42 · casador (IA)_" in com


def test_corta_mensagem_longa_mantendo_titulo_acao_e_rodape():
    texto = texto_de(TipoAviso.AMAZON_ERRO, Dados(linhas=tuple("x" * 100 for _ in range(50))))
    assert len(texto) <= LIMITE
    assert texto.startswith("🟡 *Amazon · erro inesperado*\n")
    assert "\n• …\n\n*O que fazer:* " in texto
    assert texto.endswith("_18/10 10:42 · coletor Amazon_")


def test_trecho_gigante_e_cortado():
    texto = texto_de(TipoAviso.AMAZON_ERRO, Dados(linhas=("y" * 5000,), titulo_extra="z" * 500))
    linhas = texto.split("\n")
    assert linhas[1] == "• " + "y" * 299 + "…"
    assert linhas[0] == "🟡 *Amazon · erro inesperado · " + "z" * 119 + "…*"


@pytest.mark.parametrize(
    "linha",
    [
        "Veja http://192.168.0.10:8000/servicos",
        "noVNC em http://pc-de-casa:6081/vnc.html",
        "abra a porta :6080",
        "admin em algum-lugar:8000",
        "https://exemplo.com/caminho",
        "abra 192.168.0.10 no navegador",
    ],
)
def test_endereco_do_sistema_e_recusado_em_modo_estrito(linha):
    with pytest.raises(UrlProibida):
        texto_de(TipoAviso.AMAZON_ERRO, Dados(linhas=(linha,)))


def test_link_de_produto_de_outro_dominio_e_recusado():
    with pytest.raises(UrlProibida):
        texto_de(TipoAviso.OPORTUNIDADE, Dados(link_produto="https://evil.example/dp/B0X"))


def test_links_da_amazon_e_da_ligamagic_passam():
    dados = Dados(
        linhas=("Página: https://www.ligamagic.com.br/?view=cards/search",),
        link_produto="https://www.amazon.com.br/dp/B0TESTE123",
    )
    texto = texto_de(TipoAviso.OPORTUNIDADE, dados)
    assert "https://www.ligamagic.com.br/?view=cards/search" in texto
    assert "\nhttps://www.amazon.com.br/dp/B0TESTE123\n" in texto


def test_porta_sem_dois_pontos_e_preco_nao_sao_endereco():
    texto = texto_de(TipoAviso.AMAZON_ERRO, Dados(linhas=("noVNC da Amazon (porta 6081)", "R$ 6.080,00")))
    assert "porta 6081" in texto and "R$ 6.080,00" in texto


def test_fora_do_modo_estrito_remove_o_endereco_e_registra_no_log(caplog):
    caplog.set_level(logging.WARNING)
    dados = Dados(linhas=("Erro: ConnectError('http://192.168.0.10:8000/x')", "veja 192.168.0.10 e :6081"))
    texto = texto_de(TipoAviso.AMAZON_ERRO, dados, estrito=False)
    assert "• Erro: ConnectError('[endereço removido]')" in texto
    assert "• veja [endereço removido] e [endereço removido]" in texto
    assert "192.168" not in texto and "8000" not in texto
    assert "endereço do sistema removido" in caplog.text


def test_conferir_urls_sem_host_so_olha_portas_e_dominios():
    assert conferir_urls("tudo certo", None, estrito=True) == "tudo certo"


def test_lembrete_no_mesmo_dia_e_em_outro_dia():
    aviso = aviso_de(TipoAviso.AMAZON_CAPTCHA, CATALOGO[TipoAviso.AMAZON_CAPTCHA].exemplo, QUANDO)
    mesmo = formatar_lembrete(aviso, 3, QUANDO - timedelta(hours=2), SP, HOST, estrito=True)
    assert mesmo.startswith("🔴 *Amazon · CAPTCHA continua · 3 vezes desde 08:42*\n• Página: /s?k=")
    assert mesmo.endswith("_18/10 10:42 · coletor Amazon_")
    outro = formatar_lembrete(aviso, 9, QUANDO - timedelta(days=1), SP, HOST, estrito=True)
    assert outro.startswith("🔴 *Amazon · CAPTCHA continua · 9 vezes desde 17/10 10:42*\n")


def test_resolvido_com_e_sem_chave():
    geral = formatar_resolvido(TipoAviso.AMAZON_CAPTCHA, CHAVE_GERAL, 2, QUANDO - timedelta(minutes=30), QUANDO, SP)
    assert geral == "✅ *Amazon · CAPTCHA resolvido · 2 vezes em 30 min*\n_18/10 10:42 · coletor Amazon_"
    carrinho = formatar_resolvido(TipoAviso.AMAZON_CARRINHO, "B0DNV55QBS", 1, QUANDO - timedelta(hours=2), QUANDO, SP)
    assert carrinho == "✅ *Amazon · conferir o carrinho · B0DNV55QBS resolvido · 1 vez em 2 h*\n_18/10 10:42 · coletor Amazon_"


@pytest.mark.parametrize(
    ("duracao", "texto"),
    [
        (timedelta(seconds=30), "menos de 1 min"),
        (timedelta(seconds=-5), "menos de 1 min"),
        (timedelta(minutes=30), "30 min"),
        (timedelta(hours=2), "2 h"),
        (timedelta(hours=1, minutes=12), "1 h 12 min"),
        (timedelta(hours=26), "1 d 2 h"),
        (timedelta(days=2), "2 d"),
    ],
)
def test_duracao(duracao, texto):
    assert formatar_duracao(duracao) == texto


def test_hora_no_fuso_pedido():
    texto = formatar(aviso_de(TipoAviso.SERVICO_PAUSADO_MANUAL, Dados(), QUANDO), ZoneInfo("UTC"), estrito=True)
    assert texto.endswith("_18/10 13:42 · admin_")


def test_cabecalho_reconhece_o_tipo_tambem_no_lembrete():
    assert cabecalho(TipoAviso.MENSAGEM_NAO_ENVIADA) == "🔴 *WhatsApp · mensagem não enviada"
    aviso = aviso_de(TipoAviso.MENSAGEM_NAO_ENVIADA, CATALOGO[TipoAviso.MENSAGEM_NAO_ENVIADA].exemplo, QUANDO)
    assert eh_do_tipo(formatar(aviso, SP, estrito=True), TipoAviso.MENSAGEM_NAO_ENVIADA)
    assert eh_do_tipo(formatar_lembrete(aviso, 2, QUANDO, SP, estrito=True), TipoAviso.MENSAGEM_NAO_ENVIADA)
    assert not eh_do_tipo("🔴 *Amazon · CAPTCHA*", TipoAviso.MENSAGEM_NAO_ENVIADA)
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t1 uv run pytest -q -p no:cacheprovider tests/avisos/test_formato.py`
Expected: FAIL com `ModuleNotFoundError: No module named 'tcg_sniper.avisos'`.

- [ ] **Step 4: Catálogo**

Crie `src/tcg_sniper/avisos/__init__.py`:

```python
"""Avisos do WhatsApp: catálogo de tipos, formato único e a API `avisar`/`resolver` (spec 2026-10-18)."""
```

Crie `src/tcg_sniper/avisos/catalogo.py`:

```python
"""Catálogo dos avisos do WhatsApp: um tipo por evento, com severidade, grupo, título, regra de repetição,
ação padrão e um exemplo com dados fictícios (tela Avisos e testes)."""

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from tcg_sniper.notificador.base import Destino

CHAVE_GERAL = "geral"  # ocorrências sem distinção: um problema só por tipo
DUAS_HORAS = timedelta(hours=2)


class Severidade(StrEnum):
    FALHA = "falha"
    ATENCAO = "atencao"
    CONCLUIDO = "concluido"
    OPORTUNIDADE = "oportunidade"


EMOJI = {
    Severidade.FALHA: "🔴",
    Severidade.ATENCAO: "🟡",
    Severidade.CONCLUIDO: "✅",
    Severidade.OPORTUNIDADE: "💰",
}
EMOJI_RESOLVIDO = "✅"


class TipoAviso(StrEnum):
    LIGA_COLETA_CONCLUIDA = "liga_coleta_concluida"
    LIGA_COLETA_PARCIAL = "liga_coleta_parcial"
    LIGA_COLETA_FALHOU = "liga_coleta_falhou"
    LIGA_DESAFIO = "liga_desafio"
    LIGA_PRODUTOS_NOVOS = "liga_produtos_novos"
    LIGA_INTERROMPIDA = "liga_interrompida"
    LIGA_ERRO = "liga_erro"
    AMAZON_BUSCA_CONCLUIDA = "amazon_busca_concluida"
    AMAZON_MONITOR_CONCLUIDO = "amazon_monitor_concluido"
    AMAZON_BUSCA_PARCIAL = "amazon_busca_parcial"
    AMAZON_BUSCA_FALHOU = "amazon_busca_falhou"
    AMAZON_CAPTCHA = "amazon_captcha"
    AMAZON_SEM_LOGIN = "amazon_sem_login"
    AMAZON_CARRINHO = "amazon_carrinho"
    AMAZON_PAUSADA = "amazon_pausada"
    AMAZON_ERRO = "amazon_erro"
    AMAZON_INTERROMPIDA = "amazon_interrompida"
    IA_RODADA_CONCLUIDA = "ia_rodada_concluida"
    IA_PAUSADA = "ia_pausada"
    IA_SEM_ORCAMENTO = "ia_sem_orcamento"
    IA_FALHAS_SEGUIDAS = "ia_falhas_seguidas"
    BACKUP_CONCLUIDO = "backup_concluido"
    BACKUP_ERRO = "backup_erro"
    BACKUP_INTERROMPIDO = "backup_interrompido"
    SERVICO_SEM_SINAL = "servico_sem_sinal"
    SERVICO_PAUSADO_MANUAL = "servico_pausado_manual"
    MENSAGEM_NAO_ENVIADA = "mensagem_nao_enviada"
    OPORTUNIDADE = "oportunidade"


@dataclass(frozen=True)
class Negrito:
    """Trecho de dado que sai em negrito (é escapado e depois envolvido em `*`)."""

    texto: str


Trecho = str | Negrito
Linha = str | tuple[Trecho, ...]


@dataclass(frozen=True)
class Dados:
    """O que varia em cada ocorrência. Tudo aqui é dado (escapado no formato), menos `acao`, que é texto
    nosso e substitui a ação padrão do tipo (None: fica a padrão)."""

    linhas: tuple[Linha, ...] = ()
    titulo_extra: str | None = None
    destaque: str | None = None  # linha em negrito logo abaixo do título (ex.: nome do produto)
    acao: str | None = None
    link_produto: str | None = None  # só Amazon ou LigaMagic


@dataclass(frozen=True)
class DefinicaoAviso:
    severidade: Severidade
    grupo: Destino
    titulo: str
    origem: str  # rodapé: quem mandou
    descricao: str  # quando sai (tela Avisos)
    exemplo: Dados
    agrupa: bool = False
    lembrete: timedelta | None = None
    acao: str | None = None
    ligado_padrao: bool = True


LIGA, AMAZON, MONITOR, IA = "coletor Liga", "coletor Amazon", "monitor Amazon", "casador (IA)"
MANUTENCAO, VIGIA, ADMIN, NOTIFICADOR = "manutenção", "vigia", "admin", "notificador"


def _problema(
    severidade: Severidade, titulo: str, origem: str, descricao: str, acao: str, exemplo: Dados,
    lembrete: timedelta = DUAS_HORAS,
) -> DefinicaoAviso:
    return DefinicaoAviso(
        severidade, Destino.ADMIN, titulo, origem, descricao, exemplo, agrupa=True, lembrete=lembrete, acao=acao
    )


def _evento(
    severidade: Severidade, titulo: str, origem: str, descricao: str, acao: str | None, exemplo: Dados
) -> DefinicaoAviso:
    return DefinicaoAviso(severidade, Destino.ADMIN, titulo, origem, descricao, exemplo, acao=acao)


F, A, C = Severidade.FALHA, Severidade.ATENCAO, Severidade.CONCLUIDO

CATALOGO: dict[TipoAviso, DefinicaoAviso] = {
    TipoAviso.LIGA_COLETA_CONCLUIDA: _evento(
        C, "Liga · coleta concluída", LIGA, "Fim de uma coleta da LigaMagic sem falha, erro nem desafio.", None,
        Dados(
            titulo_extra="18/10",
            linhas=(
                "Listagens: ok · 20 de 20 categorias · 3 produtos novos",
                "Produtos: ok · 412 ok · 0 falhas",
                "Duração: 1 h 12 min",
            ),
        ),
    ),
    TipoAviso.LIGA_COLETA_PARCIAL: _evento(
        A, "Liga · coleta parcial", LIGA, "Fim de uma coleta da LigaMagic com algumas páginas falhando.",
        "Nada urgente; se repetir, veja Admin → Logs → LigaMagic.",
        Dados(
            titulo_extra="18/10",
            linhas=(
                "Listagens: ok · 20 de 20 categorias · 0 produtos novos",
                "Produtos: parcial · 380 ok · 32 falhas",
                "Duração: 1 h 5 min",
            ),
        ),
    ),
    TipoAviso.LIGA_COLETA_FALHOU: _problema(
        F, "Liga · coleta falhou", LIGA, "Uma etapa da coleta falhou em mais páginas que o limite.",
        "O layout da LigaMagic pode ter mudado: veja Admin → Logs → LigaMagic e os HTMLs na pasta falhas.",
        Dados(linhas=("Etapa: Coleta dos produtos ativos", "Falhas: 300 de 412 produtos")),
    ),
    TipoAviso.LIGA_DESAFIO: _problema(
        F, "Liga · desafio do Cloudflare", LIGA, "A LigaMagic pediu verificação; a coleta fica pausada.",
        "Resolva no noVNC da Liga (porta 6080) e depois Admin → Serviços → LigaMagic → Retomar.",
        Dados(linhas=("Página: /?view=cards/search&card=categ%3D10", "A coleta fica pausada até você retomar")),
    ),
    TipoAviso.LIGA_PRODUTOS_NOVOS: _evento(
        A, "Liga · produtos novos no catálogo", LIGA, "As listagens trouxeram produtos que não estavam no catálogo.",
        "Ative os que quiser acompanhar em Admin → Catálogo → filtro Novos.",
        Dados(linhas=("3 produtos novos nas listagens",)),
    ),
    TipoAviso.LIGA_INTERROMPIDA: _evento(
        A, "Liga · coleta interrompida", LIGA, "O coletor reiniciou no meio de uma coleta.",
        "A coleta de hoje pode não rodar de novo sozinha: Admin → Serviços → LigaMagic → Rodar agora.",
        Dados(linhas=("2 coleta(s) marcada(s) como falha: o coletor reiniciou no meio do job",)),
    ),
    TipoAviso.LIGA_ERRO: _problema(
        F, "Liga · erro inesperado", LIGA, "Erro inesperado no job ou no meio de uma etapa da coleta.",
        "Veja os logs do coletor (docker compose logs coletor-liga); a próxima coleta tenta de novo.",
        Dados(linhas=("Onde: Coleta dos produtos ativos 41", "Erro: TimeoutError('página não carregou')")),
    ),
    TipoAviso.AMAZON_BUSCA_CONCLUIDA: _evento(
        C, "Amazon · busca concluída", AMAZON, "Fim de um ciclo da busca de anúncios novos sem falha.", None,
        Dados(titulo_extra="ciclo 42", linhas=("Buscas: 37 ok · 1 falha", "Duração: 2 h 5 min")),
    ),
    TipoAviso.AMAZON_MONITOR_CONCLUIDO: _evento(
        C, "Amazon · rodada do monitor", MONITOR, "O monitor leu todos os anúncios vencidos (cerca de 4 por hora).",
        None,
        Dados(
            linhas=("Anúncios lidos: 24", "Preços em queda: 2", "Conferências de checkout: 1", "Duração: 14 min")
        ),
    ),
    TipoAviso.AMAZON_BUSCA_PARCIAL: _evento(
        A, "Amazon · busca parcial", AMAZON, "Fim de um ciclo da busca com algumas buscas falhando.",
        "Nada urgente; se repetir, veja Admin → Logs → Amazon.",
        Dados(titulo_extra="ciclo 42", linhas=("Buscas: 30 ok · 8 falhas", "Duração: 2 h 10 min")),
    ),
    TipoAviso.AMAZON_BUSCA_FALHOU: _problema(
        F, "Amazon · busca falhou", AMAZON, "Um ciclo da busca falhou em mais buscas que o limite.",
        "O layout da Amazon pode ter mudado: veja Admin → Logs → Amazon e os HTMLs na pasta falhas.",
        Dados(titulo_extra="ciclo 42", linhas=("Buscas: 12 ok · 26 falhas", "Duração: 1 h 40 min")),
    ),
    TipoAviso.AMAZON_CAPTCHA: _problema(
        F, "Amazon · CAPTCHA", AMAZON, "A Amazon pediu verificação; busca, monitor e conferência ficam pausados.",
        "Resolva no noVNC da Amazon (porta 6081) e depois Admin → Serviços → Amazon → Retomar.",
        Dados(
            linhas=(
                "Página: /s?k=aetherdrift+commander",
                "Busca, monitor e conferência pausados até você retomar",
                "Uma conferência deixou 1× B0DNV55QBS no carrinho: sai sozinho se você retomar em até 30 min; "
                "senão confira à mão",
            )
        ),
    ),
    TipoAviso.AMAZON_SEM_LOGIN: _problema(
        F, "Amazon · conta sem login", AMAZON, "A conferência de checkout caiu no login; o monitor continua.",
        "Faça login na conta Amazon pelo noVNC da Amazon (porta 6081) e depois "
        "Admin → Serviços → Amazon → Retomar conferência.",
        Dados(linhas=("A conferência de checkout parou; o monitor de preço continua",)),
    ),
    TipoAviso.AMAZON_CARRINHO: _problema(
        F, "Amazon · conferir o carrinho", AMAZON,
        "O coletor não pôde tirar sozinho o item de uma conferência do carrinho (um aviso por ASIN).",
        "Confira o carrinho pelo noVNC da Amazon (porta 6081), tire o item se não for seu e "
        "clique em Admin → Serviços → Já conferi.",
        Dados(
            titulo_extra="B0DNV55QBS",
            linhas=(
                "Pode haver 1× B0DNV55QBS de uma conferência automática no carrinho",
                "Motivo: carrinho com outros itens (B0AAAA0001)",
            ),
        ),
    ),
    TipoAviso.AMAZON_PAUSADA: _problema(
        F, "Amazon · pausada", AMAZON, "A Amazon foi pausada por páginas com falha ou erros inesperados seguidos.",
        "Veja os logs (docker compose logs coletor-amazon) e depois Admin → Serviços → Amazon → Retomar.",
        Dados(
            linhas=(
                "Motivo: 10 páginas seguidas com falha (bloqueio ou layout novo?)",
                "Com a Amazon pausada, a retirada automática de item do carrinho também para",
            )
        ),
    ),
    TipoAviso.AMAZON_ERRO: _problema(
        A, "Amazon · erro inesperado", AMAZON, "Erro inesperado num passo da varredura; tenta de novo em 15 min.",
        "Nada a fazer se não repetir: nova tentativa em 15 min. Se repetir, veja os logs "
        "(docker compose logs coletor-amazon).",
        Dados(linhas=("Erro: RuntimeError('navegador fechou')",)),
    ),
    TipoAviso.AMAZON_INTERROMPIDA: _evento(
        A, "Amazon · ciclo interrompido", AMAZON, "O coletor da Amazon reiniciou no meio de um ciclo.",
        "Nada a fazer: a fila continua sozinha.",
        Dados(linhas=("1 ciclo(s) marcado(s) como falha: o coletor reiniciou",)),
    ),
    TipoAviso.IA_RODADA_CONCLUIDA: _evento(
        C, "IA · rodada concluída", IA, "Rodada do casador que avaliou pelo menos um anúncio.", None,
        Dados(
            linhas=(
                "Avaliados: 12",
                "Confirmados pelo automático: 3",
                "Ignorados pelo automático: 5",
                "Esperando você: 4",
            ),
            acao="Revise os pendentes em Admin → Casamentos.",
        ),
    ),
    TipoAviso.IA_PAUSADA: _problema(
        F, "IA · casador pausado", IA, "A OpenAI recusou a chave ou a configuração; o casador fica pausado.",
        "Corrija a chave da OpenAI (.env) ou Admin → Configurações → IA e depois "
        "Admin → Serviços → Casador → Retomar.",
        Dados(linhas=("Motivo: chave recusada pela OpenAI (401)",)),
    ),
    TipoAviso.IA_SEM_ORCAMENTO: _problema(
        A, "IA · sem orçamento", IA, "O teto de gasto ou de chamadas do dia (ou do mês) foi atingido.",
        "Volta sozinho no próximo período, ou suba o teto em Admin → Configurações → IA.",
        Dados(titulo_extra="dia 18/10", linhas=("Motivo: teto diário de US$ 1,00 atingido",)),
    ),
    TipoAviso.IA_FALHAS_SEGUIDAS: _problema(
        A, "IA · falhas seguidas", IA, "Chamadas seguidas à OpenAI falharam e a rodada parou.",
        "Nada a fazer se for passageiro: a próxima rodada tenta de novo.",
        Dados(linhas=("3 chamadas seguidas falharam; a rodada parou", "Última: OpenAI 503")),
    ),
    TipoAviso.BACKUP_CONCLUIDO: _evento(
        C, "Backup · concluído", MANUTENCAO, "Backup diário do banco feito (e limpeza do histórico).", None,
        Dados(
            titulo_extra="18/10",
            linhas=("Tamanho: 607,3 KB", "Cópia no R2: sim", "Linhas antigas apagadas: 1.234"),
        ),
    ),
    TipoAviso.BACKUP_ERRO: _problema(
        F, "Backup · erro", MANUTENCAO, "O backup, a cópia no R2 ou a limpeza falhou.",
        "Tenta de novo amanhã às 04:00; veja Admin → Logs → Manutenção.",
        Dados(
            titulo_extra="18/10",
            linhas=("Erro: envio ao R2 falhou: EndpointConnectionError", "O backup local ficou salvo"),
        ),
    ),
    TipoAviso.BACKUP_INTERROMPIDO: _evento(
        A, "Backup · interrompido", MANUTENCAO, "O serviço de manutenção reiniciou no meio de um backup.",
        "Nada a fazer: o backup do dia roda de novo.",
        Dados(linhas=("1 execução(ões) interrompida(s) no meio: o serviço de manutenção reiniciou",)),
    ),
    TipoAviso.SERVICO_SEM_SINAL: _problema(
        F, "Serviço sem sinal", VIGIA, "Um serviço ativo ficou mais de 10 min sem dar sinal de vida.",
        "Veja se o container está de pé (docker compose ps) e os logs dele.",
        Dados(titulo_extra="coletor-amazon", linhas=("Último sinal: 18/10 10:30 (há 12 min)",)),
    ),
    TipoAviso.SERVICO_PAUSADO_MANUAL: _evento(
        A, "Serviço mudou no admin", ADMIN, "Alguém pausou ou retomou um serviço em Admin → Serviços.", None,
        Dados(titulo_extra="Amazon", linhas=("Novo estado: pausado",)),
    ),
    TipoAviso.MENSAGEM_NAO_ENVIADA: _problema(
        F, "WhatsApp · mensagem não enviada", NOTIFICADOR,
        "Uma mensagem falhou de vez (5 recusas). No máximo um aviso por hora.",
        "Confira a instância e os grupos em Admin → Configurações → Geral e reenvie em Admin → Mensagens.",
        Dados(linhas=("#123 para oportunidades: HTTP 400: grupo não encontrado",)),
        lembrete=timedelta(hours=1),
    ),
    TipoAviso.OPORTUNIDADE: DefinicaoAviso(
        Severidade.OPORTUNIDADE, Destino.OPORTUNIDADES, "Oportunidade", MONITOR,
        "Oferta confirmada da Amazon abaixo da Liga (regras do motor), no grupo de oportunidades.",
        Dados(
            titulo_extra="18% abaixo da Liga",
            destaque="Final Fantasy - Caixa de Booster de Jogo",
            linhas=(
                ("Amazon: ", Negrito("R$ 1.299,90"), " (conferido, com impostos; frete à parte)"),
                "Vendido por: Amazon · Prime",
                "Liga: a partir de R$ 1.589,00 · 12 lojas · média R$ 1.640,00",
            ),
            link_produto="https://www.amazon.com.br/dp/B0TESTE123",
        ),
    ),
}
```

- [ ] **Step 5: Formato**

Crie `src/tcg_sniper/avisos/formato.py`:

```python
"""A única função que transforma um aviso em texto de WhatsApp: título com emoji, linhas com "•",
"O que fazer", link de produto e rodapé com hora e origem. Escapa a formatação vinda dos dados, corta
textos longos e garante que nenhum endereço do sistema sai (admin, noVNC, IP de casa)."""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from tcg_sniper.avisos.catalogo import (
    CATALOGO,
    CHAVE_GERAL,
    EMOJI,
    EMOJI_RESOLVIDO,
    Dados,
    Linha,
    Negrito,
    TipoAviso,
)

log = logging.getLogger(__name__)

ESTRITO = False  # tests/conftest.py liga: endereço do sistema vira exceção em vez de ser removido
LIMITE = 1500
MAX_TRECHO = 300
MAX_EXTRA = 120
MAX_DESTAQUE = 200
DOMINIOS_PERMITIDOS = ("amazon.com.br", "ligamagic.com.br")
REMOVIDO = "[endereço removido]"
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_PORTAS = re.compile(r":(?:8000|6080|6081)(?!\d)")
_ESCAPES = str.maketrans({"*": "∗", "_": "ˍ", "~": "˜", "`": "ˋ"})


class UrlProibida(ValueError):
    """Mensagem com endereço do sistema (admin, noVNC, IP de casa) ou link fora da Amazon e da LigaMagic."""


@dataclass(frozen=True)
class Aviso:
    tipo: TipoAviso
    titulo_extra: str | None
    linhas: tuple[Linha, ...]
    acao: str | None
    origem: str
    quando: datetime
    link_produto: str | None = None
    destaque: str | None = None


def aviso_de(tipo: TipoAviso, dados: Dados, quando: datetime) -> Aviso:
    """Junta os dados da ocorrência com a definição do tipo (ação padrão e origem)."""
    definicao = CATALOGO[tipo]
    acao = dados.acao if dados.acao is not None else definicao.acao
    return Aviso(
        tipo, dados.titulo_extra, dados.linhas, acao, definicao.origem, quando, dados.link_produto, dados.destaque
    )


def escapar(texto: str) -> str:
    """Troca os marcadores do WhatsApp por sósias: dado nunca vira negrito, itálico, riscado ou código."""
    return texto.translate(_ESCAPES)


def _cortar(texto: str, maximo: int) -> str:
    return texto if len(texto) <= maximo else texto[: maximo - 1] + "…"


def _dado(texto: str, maximo: int = MAX_TRECHO) -> str:
    return escapar(_cortar(texto, maximo))


def _linha(linha: Linha) -> str:
    trechos = (linha,) if isinstance(linha, str) else linha
    partes = [f"*{_dado(t.texto)}*" if isinstance(t, Negrito) else _dado(t) for t in trechos]
    return "• " + "".join(partes)


def cabecalho(tipo: TipoAviso) -> str:
    """Começo de toda mensagem do tipo (também do lembrete): emoji e título, sem o `*` de fechamento."""
    definicao = CATALOGO[tipo]
    return f"{EMOJI[definicao.severidade]} *{definicao.titulo}"


def eh_do_tipo(texto: str, tipo: TipoAviso) -> bool:
    return texto.startswith(cabecalho(tipo))


def _titulo(aviso: Aviso) -> str:
    extra = f" · {_dado(aviso.titulo_extra, MAX_EXTRA)}" if aviso.titulo_extra else ""
    return cabecalho(aviso.tipo) + extra


def _montar(primeira: str, aviso: Aviso, zona: ZoneInfo) -> str:
    topo = [primeira]
    if aviso.destaque:
        topo.append(f"*{_dado(aviso.destaque, MAX_DESTAQUE)}*")
    fim = []
    if aviso.acao:
        fim += ["", f"*O que fazer:* {aviso.acao}"]
    if aviso.link_produto:
        fim.append(aviso.link_produto)
    fim.append(f"_{aviso.quando.astimezone(zona):%d/%m %H:%M} · {aviso.origem}_")
    linhas = [_linha(linha) for linha in aviso.linhas]

    def juntar(meio: list[str]) -> str:
        return "\n".join(topo + meio + fim)

    if len(juntar(linhas)) > LIMITE:
        while linhas and len(juntar([*linhas, "• …"])) > LIMITE:
            linhas.pop()
        linhas.append("• …")
    return juntar(linhas)


def formatar(aviso: Aviso, zona: ZoneInfo, host_publico: str | None = None, *, estrito: bool | None = None) -> str:
    return conferir_urls(_montar(_titulo(aviso) + "*", aviso, zona), host_publico, estrito=estrito)


def formatar_lembrete(
    aviso: Aviso,
    ocorrencias: int,
    desde: datetime,
    zona: ZoneInfo,
    host_publico: str | None = None,
    *,
    estrito: bool | None = None,
) -> str:
    """O problema continua: título com a contagem e a hora da primeira ocorrência, corpo da ocorrência atual."""
    local_desde, local_agora = desde.astimezone(zona), aviso.quando.astimezone(zona)
    hora = f"{local_desde:%H:%M}" if local_desde.date() == local_agora.date() else f"{local_desde:%d/%m %H:%M}"
    primeira = f"{_titulo(aviso)} continua · {ocorrencias} vezes desde {hora}*"
    return conferir_urls(_montar(primeira, aviso, zona), host_publico, estrito=estrito)


def formatar_resolvido(
    tipo: TipoAviso,
    chave: str,
    ocorrencias: int,
    primeiro_em: datetime,
    agora: datetime,
    zona: ZoneInfo,
    host_publico: str | None = None,
    *,
    estrito: bool | None = None,
) -> str:
    definicao = CATALOGO[tipo]
    extra = f" · {_dado(chave, MAX_EXTRA)}" if chave != CHAVE_GERAL else ""
    vezes = "1 vez" if ocorrencias == 1 else f"{ocorrencias} vezes"
    texto = (
        f"{EMOJI_RESOLVIDO} *{definicao.titulo}{extra} resolvido · {vezes} em {formatar_duracao(agora - primeiro_em)}*\n"
        f"_{agora.astimezone(zona):%d/%m %H:%M} · {definicao.origem}_"
    )
    return conferir_urls(texto, host_publico, estrito=estrito)


def formatar_duracao(duracao: timedelta) -> str:
    minutos = int(duracao.total_seconds() // 60)
    if minutos < 1:
        return "menos de 1 min"
    if minutos < 60:
        return f"{minutos} min"
    horas, minutos = divmod(minutos, 60)
    if horas < 24:
        return f"{horas} h {minutos} min" if minutos else f"{horas} h"
    dias, horas = divmod(horas, 24)
    return f"{dias} d {horas} h" if horas else f"{dias} d"


def _permitida(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == dominio or host.endswith("." + dominio) for dominio in DOMINIOS_PERMITIDOS)


def conferir_urls(texto: str, host_publico: str | None = None, *, estrito: bool | None = None) -> str:
    """Regra de URL do spec: só links da Amazon e da LigaMagic; nada de `:8000`, `:6080`, `:6081` nem do
    `host_publico`. Estrito (testes): levanta `UrlProibida`. Senão troca por "[endereço removido]" e loga."""
    estrito = ESTRITO if estrito is None else estrito
    achados: list[str] = []

    def trocar(m: re.Match[str]) -> str:
        achados.append(m.group(0))
        return REMOVIDO

    novo = _URL.sub(lambda m: m.group(0) if _permitida(m.group(0)) else trocar(m), texto)
    novo = _PORTAS.sub(trocar, novo)
    host = (host_publico or "").strip()
    if host:
        novo = re.sub(rf"(?<![\w.-]){re.escape(host)}(?![\w-])", trocar, novo, flags=re.IGNORECASE)
    if not achados:
        return texto
    if estrito:
        raise UrlProibida(f"endereço do sistema na mensagem: {achados}")
    log.warning("endereço do sistema removido da mensagem: %s", achados)
    return novo
```

Em `tests/conftest.py`, logo depois dos imports (antes de `URL_TESTE`), acrescente:

```python
from tcg_sniper.avisos import formato

# Nos testes, endereço do sistema numa mensagem é erro (em produção é removido e vai para o log).
formato.ESTRITO = True
```

(mantenha o import junto dos outros `from tcg_sniper…` para o ruff não reclamar de ordem; a atribuição fica logo abaixo do bloco de imports.)

- [ ] **Step 6: Rodar os testes**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t1 uv run pytest -q -p no:cacheprovider tests/avisos/test_formato.py`
Expected: PASS (todos). Se algum `ESPERADOS` divergir, corrija o **catálogo** (o modelo do teste é o contrato), nunca o teste.

- [ ] **Step 7: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t1 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: tudo verde (nenhum serviço usa o módulo ainda).

- [ ] **Step 8: Commit**

```bash
git add src/tcg_sniper/avisos tests/avisos/test_formato.py tests/conftest.py
git commit -m "feat: WhatsApp alert catalog and single message format with URL guard"
```

---

### Task 2: Estado, migração e serviço `avisar`/`resolver`

**Files:**
- Modify: `src/tcg_sniper/db/models.py` (três modelos novos, depois de `ExecucaoManutencao`)
- Create: `src/tcg_sniper/db/migrations/versions/e4b7c2d9a1f6_avisos.py`
- Create: `src/tcg_sniper/avisos/servico.py`
- Modify: `tests/fakes.py` (acrescenta `AvisadorFake` no fim)
- Test: `tests/avisos/test_servico.py` (novo)

**Interfaces:**
- Consumes: Task 1 (`CATALOGO`, `CHAVE_GERAL`, `Dados`, `TipoAviso`, `formato.*`); `repositorio_mensagens.enfileirar(s, destino: str, texto: str, agora) -> MensagemSaida`; `models.ConfigGeral`.
- Produces:
  - `models.EstadoAviso` (`estado_aviso`: `tipo`, `chave` (PK), `aberto`, `primeiro_em`, `ultimo_em`, `ultimo_envio_em`, `ocorrencias`), `models.ConfigAviso` (`config_aviso`: `tipo` PK, `ligado`), `models.SinalServico` (`sinal_servico`: `servico` PK, `ultimo_em`).
  - `servico.FUSO_PADRAO = "America/Sao_Paulo"`.
  - `servico.avisar(s: Session, tipo: TipoAviso, chave: str, dados: Dados, agora: datetime) -> None`.
  - `servico.resolver(s: Session, tipo: TipoAviso, chave: str, agora: datetime) -> None`.
  - `servico.resolver_todos(s: Session, tipo: TipoAviso, agora: datetime) -> None`.
  - `servico.abertos(s: Session, tipo: TipoAviso) -> list[str]` (chaves abertas, em ordem).
  - `servico.ligado(s, tipo) -> bool`, `servico.ligados(s) -> dict[TipoAviso, bool]`, `servico.definir_ligado(s, tipo, ligado: bool) -> None`.
  - `servico.zona_e_host(s) -> tuple[ZoneInfo, str | None]`.
  - `servico.Avisador` (Protocol): `avisar(tipo, chave, dados) -> None`, `resolver(tipo, chave) -> None`, `resolver_todos(tipo) -> None`.
  - `servico.AvisadorBanco(sessoes: sessionmaker[Session], relogio: Callable[[], datetime] | None = None)` (implementa `Avisador`, cada chamada na própria transação); `servico.criar_avisador(sessoes) -> AvisadorBanco`.
  - `fakes.AvisadorFake(host_publico: str = "host.test")`: `.avisos: list[tuple[TipoAviso, str, Dados]]`, `.resolvidos: list[tuple[TipoAviso, str]]` (`resolver_todos` grava a chave `"*"`), `.mensagens: list[tuple[Destino, str]]` (texto montado em modo estrito), `.tipos() -> list[TipoAviso]`, `.dados(tipo) -> list[Dados]`.

- [ ] **Step 1: Banco da lane e head atual**

Run: `docker compose exec -T postgres-teste createdb -U tcg tcg_test_t2` e `uv run alembic heads`
Expected: `d1a7f3c9e5b2 (head)`. Se a head for outra, use-a como `down_revision` abaixo.

- [ ] **Step 2: Testes (falham)**

Crie `tests/avisos/test_servico.py`:

```python
import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tcg_sniper.avisos import formato, servico
from tcg_sniper.avisos.catalogo import CATALOGO, CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.avisos.formato import UrlProibida
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import ConfigAviso, EstadoAviso, MensagemSaida

T = datetime(2026, 10, 18, 13, 0, tzinfo=UTC)  # 10:00 em São Paulo
CAPTCHA = TipoAviso.AMAZON_CAPTCHA


def saidas(sessoes):
    with sessoes() as s:
        return list(s.scalars(select(MensagemSaida).order_by(MensagemSaida.id)))


def avisar_em(sessoes, quando, tipo=CAPTCHA, chave=CHAVE_GERAL, dados=None):
    with sessoes() as s, s.begin():
        servico.avisar(s, tipo, chave, dados or CATALOGO[tipo].exemplo, quando)


def resolver_em(sessoes, quando, tipo=CAPTCHA, chave=CHAVE_GERAL):
    with sessoes() as s, s.begin():
        servico.resolver(s, tipo, chave, quando)


def estado(sessoes, tipo=CAPTCHA, chave=CHAVE_GERAL):
    with sessoes() as s:
        return s.get(EstadoAviso, (tipo.value, chave))


def desligar(sessoes, tipo=CAPTCHA, ligado=False):
    with sessoes() as s, s.begin():
        servico.definir_ligado(s, tipo, ligado)


def test_primeira_ocorrencia_abre_e_envia(sessoes):
    avisar_em(sessoes, T)
    [m] = saidas(sessoes)
    assert m.destino == "admin" and m.texto.startswith("🔴 *Amazon · CAPTCHA*\n") and m.criada_em == T
    e = estado(sessoes)
    assert (e.aberto, e.ocorrencias, e.primeiro_em, e.ultimo_em, e.ultimo_envio_em) == (True, 1, T, T, T)


def test_repeticao_antes_de_2h_so_conta(sessoes):
    avisar_em(sessoes, T)
    avisar_em(sessoes, T + timedelta(minutes=30))
    avisar_em(sessoes, T + timedelta(hours=1, minutes=59))
    assert len(saidas(sessoes)) == 1
    e = estado(sessoes)
    assert (e.ocorrencias, e.ultimo_em, e.ultimo_envio_em) == (3, T + timedelta(hours=1, minutes=59), T)


def test_lembrete_depois_de_2h(sessoes):
    avisar_em(sessoes, T)
    avisar_em(sessoes, T + timedelta(minutes=30))
    avisar_em(sessoes, T + timedelta(hours=2))
    primeira, lembrete = saidas(sessoes)
    assert lembrete.texto.startswith("🔴 *Amazon · CAPTCHA continua · 3 vezes desde 10:00*\n")
    assert lembrete.texto.endswith("_18/10 12:00 · coletor Amazon_")
    assert estado(sessoes).ultimo_envio_em == T + timedelta(hours=2)


def test_lembretes_nao_acumulam_depois_de_horas_parado(sessoes):
    avisar_em(sessoes, T)
    for minuto in range(5):  # o serviço volta 5 h depois e o problema repete a cada minuto
        avisar_em(sessoes, T + timedelta(hours=5, minutes=minuto))
    assert len(saidas(sessoes)) == 2
    assert estado(sessoes).ocorrencias == 6


def test_resolver_com_envio_manda_resolvido(sessoes):
    avisar_em(sessoes, T)
    avisar_em(sessoes, T + timedelta(minutes=10))
    resolver_em(sessoes, T + timedelta(minutes=30))
    *_, resolvido = saidas(sessoes)
    assert resolvido.texto == "✅ *Amazon · CAPTCHA resolvido · 2 vezes em 30 min*\n_18/10 10:30 · coletor Amazon_"
    assert estado(sessoes).aberto is False


def test_resolver_sem_aberto_nao_faz_nada(sessoes):
    resolver_em(sessoes, T)
    assert saidas(sessoes) == [] and estado(sessoes) is None


def test_tipo_desligado_atualiza_o_estado_e_nao_envia_nem_resolvido(sessoes):
    desligar(sessoes)
    avisar_em(sessoes, T)
    avisar_em(sessoes, T + timedelta(hours=3))
    assert saidas(sessoes) == []
    assert (estado(sessoes).aberto, estado(sessoes).ocorrencias) == (True, 2)
    resolver_em(sessoes, T + timedelta(hours=4))
    assert saidas(sessoes) == [] and estado(sessoes).aberto is False


def test_religado_com_problema_aberto_o_proximo_avisar_lembra(sessoes):
    desligar(sessoes)
    avisar_em(sessoes, T)
    desligar(sessoes, ligado=True)
    avisar_em(sessoes, T + timedelta(minutes=5))
    [m] = saidas(sessoes)
    assert m.texto.startswith("🔴 *Amazon · CAPTCHA continua · 2 vezes desde 10:00*")


def test_reabre_depois_de_resolvido(sessoes):
    avisar_em(sessoes, T)
    resolver_em(sessoes, T + timedelta(minutes=1))
    avisar_em(sessoes, T + timedelta(minutes=2))
    assert saidas(sessoes)[-1].texto.startswith("🔴 *Amazon · CAPTCHA*\n")
    e = estado(sessoes)
    assert (e.aberto, e.ocorrencias, e.primeiro_em) == (True, 1, T + timedelta(minutes=2))


def test_chave_separa_ocorrencias(sessoes):
    avisar_em(sessoes, T, TipoAviso.AMAZON_CARRINHO, "B0AAAA0001")
    avisar_em(sessoes, T, TipoAviso.AMAZON_CARRINHO, "B0BBBB0001")
    resolver_em(sessoes, T + timedelta(minutes=5), TipoAviso.AMAZON_CARRINHO, "B0AAAA0001")
    textos = [m.texto for m in saidas(sessoes)]
    assert len(textos) == 3
    assert textos[2].startswith("✅ *Amazon · conferir o carrinho · B0AAAA0001 resolvido · 1 vez em 5 min*")
    with sessoes() as s:
        assert servico.abertos(s, TipoAviso.AMAZON_CARRINHO) == ["B0BBBB0001"]


def test_resolver_todos(sessoes):
    avisar_em(sessoes, T, TipoAviso.IA_SEM_ORCAMENTO, "dia 17/10")
    avisar_em(sessoes, T, TipoAviso.IA_SEM_ORCAMENTO, "dia 18/10")
    with sessoes() as s, s.begin():
        servico.resolver_todos(s, TipoAviso.IA_SEM_ORCAMENTO, T + timedelta(hours=1))
    with sessoes() as s:
        assert servico.abertos(s, TipoAviso.IA_SEM_ORCAMENTO) == []
    assert len(saidas(sessoes)) == 4


def test_tipo_que_nao_agrupa_sempre_envia_e_nao_grava_estado(sessoes):
    avisar_em(sessoes, T, TipoAviso.OPORTUNIDADE, "7")
    avisar_em(sessoes, T, TipoAviso.OPORTUNIDADE, "7")
    assert [m.destino for m in saidas(sessoes)] == ["oportunidades", "oportunidades"]
    assert estado(sessoes, TipoAviso.OPORTUNIDADE, "7") is None


def test_mensagem_nao_enviada_lembra_no_maximo_uma_vez_por_hora(sessoes):
    tipo = TipoAviso.MENSAGEM_NAO_ENVIADA
    for minutos in (0, 30, 59, 60, 90):
        avisar_em(sessoes, T + timedelta(minutes=minutos), tipo)
    assert len(saidas(sessoes)) == 2


def test_usa_o_fuso_e_o_host_de_configuracoes(sessoes, config):
    with sessoes() as s, s.begin():
        repo.obter_config_geral(s, config)
        repo.salvar_config_geral(s, {"fuso": "UTC"}, T)
    avisar_em(sessoes, T, TipoAviso.SERVICO_PAUSADO_MANUAL)
    assert saidas(sessoes)[0].texto.endswith("_18/10 13:00 · admin_")
    with pytest.raises(UrlProibida), sessoes() as s, s.begin():  # config.host_publico == "host.test"
        servico.avisar(s, TipoAviso.AMAZON_ERRO, CHAVE_GERAL, Dados(linhas=("abra host.test",)), T)


def test_endereco_do_sistema_em_modo_estrito_levanta(sessoes):
    dados = Dados(linhas=("veja http://192.168.0.10:8000/servicos",))
    with pytest.raises(UrlProibida), sessoes() as s, s.begin():
        servico.avisar(s, TipoAviso.AMAZON_ERRO, CHAVE_GERAL, dados, T)


def test_fora_do_modo_estrito_avisar_remove_e_enfileira(sessoes, monkeypatch):
    monkeypatch.setattr(formato, "ESTRITO", False)
    avisar_em(sessoes, T, TipoAviso.AMAZON_ERRO, dados=Dados(linhas=("Erro: ConnectError('http://10.0.0.2:8000/x')",)))
    [m] = saidas(sessoes)
    assert "ConnectError('[endereço removido]')" in m.texto and "8000" not in m.texto


def test_erro_ao_enfileirar_nao_propaga_nem_estraga_a_transacao(sessoes, monkeypatch, caplog):
    caplog.set_level(logging.ERROR)

    def quebrar(*_a, **_k):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(repo_msg, "enfileirar", quebrar)
    with sessoes() as s, s.begin():
        servico.avisar(s, CAPTCHA, CHAVE_GERAL, CATALOGO[CAPTCHA].exemplo, T)
        s.add(ConfigAviso(tipo="so_para_o_teste", ligado=True))
        s.flush()
    assert "aviso amazon_captcha (geral) não registrado" in caplog.text
    with sessoes() as s:
        assert s.get(EstadoAviso, ("amazon_captcha", "geral")) is None  # o savepoint foi desfeito
        assert s.get(ConfigAviso, "so_para_o_teste") is not None  # a transação do chamador seguiu


def test_ligados_e_definir_ligado(sessoes):
    with sessoes() as s:
        assert all(servico.ligados(s).values())
    desligar(sessoes, TipoAviso.AMAZON_MONITOR_CONCLUIDO)
    with sessoes() as s:
        assert servico.ligados(s)[TipoAviso.AMAZON_MONITOR_CONCLUIDO] is False
        assert servico.ligado(s, TipoAviso.AMAZON_CAPTCHA) is True


def test_avisador_banco_abre_a_propria_transacao(sessoes):
    avisador = servico.AvisadorBanco(sessoes, relogio=lambda: T)
    avisador.avisar(CAPTCHA, CHAVE_GERAL, CATALOGO[CAPTCHA].exemplo)
    avisador.resolver(CAPTCHA, CHAVE_GERAL)
    avisador.avisar(TipoAviso.IA_SEM_ORCAMENTO, "dia 18/10", CATALOGO[TipoAviso.IA_SEM_ORCAMENTO].exemplo)
    avisador.resolver_todos(TipoAviso.IA_SEM_ORCAMENTO)
    assert len(saidas(sessoes)) == 4


def test_avisador_banco_com_banco_fora_nao_propaga(caplog):
    def sessoes():
        raise RuntimeError("banco fora")

    servico.AvisadorBanco(sessoes, relogio=lambda: T).avisar(CAPTCHA, CHAVE_GERAL, CATALOGO[CAPTCHA].exemplo)
    assert "aviso amazon_captcha não registrado" in caplog.text
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t2 uv run pytest -q -p no:cacheprovider tests/avisos/test_servico.py`
Expected: FAIL com `ImportError` (`servico`, `EstadoAviso`).

- [ ] **Step 4: Modelos**

Em `src/tcg_sniper/db/models.py`, logo depois da classe `ExecucaoManutencao`:

```python
class EstadoAviso(Base):
    """Um problema por (tipo, chave) dos avisos do WhatsApp que agrupam: aberto até `resolver`.
    `ultimo_envio_em` nulo: nada saiu ainda (tipo desligado)."""

    __tablename__ = "estado_aviso"
    __table_args__ = (CheckConstraint("ocorrencias >= 0", name="ck_estado_aviso_ocorrencias"),)

    tipo: Mapped[str] = mapped_column(Text, primary_key=True)
    chave: Mapped[str] = mapped_column(Text, primary_key=True)
    aberto: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    primeiro_em: Mapped[datetime] = mapped_column(DATA)
    ultimo_em: Mapped[datetime] = mapped_column(DATA)
    ultimo_envio_em: Mapped[datetime | None] = mapped_column(DATA)
    ocorrencias: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class ConfigAviso(Base):
    """Liga/desliga de cada tipo de aviso (Configurações → Avisos). Linha ausente = ligado_padrao do catálogo."""

    __tablename__ = "config_aviso"

    tipo: Mapped[str] = mapped_column(Text, primary_key=True)
    ligado: Mapped[bool] = mapped_column(Boolean)


class SinalServico(Base):
    """Último sinal de vida de cada serviço sem tabela de estado própria (coletores e casador); o vigia lê."""

    __tablename__ = "sinal_servico"

    servico: Mapped[str] = mapped_column(Text, primary_key=True)
    ultimo_em: Mapped[datetime] = mapped_column(DATA)
```

- [ ] **Step 5: Migração**

Crie `src/tcg_sniper/db/migrations/versions/e4b7c2d9a1f6_avisos.py`:

```python
"""avisos do WhatsApp: estado_aviso (repetição), config_aviso (liga/desliga) e sinal_servico (vigia)

Revision ID: e4b7c2d9a1f6
Revises: d1a7f3c9e5b2
Create Date: 2026-10-18 20:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4b7c2d9a1f6"
down_revision: Union[str, Sequence[str], None] = "d1a7f3c9e5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "estado_aviso",
        sa.Column("tipo", sa.Text(), primary_key=True),
        sa.Column("chave", sa.Text(), primary_key=True),
        sa.Column("aberto", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("primeiro_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ultimo_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ultimo_envio_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ocorrencias", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("ocorrencias >= 0", name="ck_estado_aviso_ocorrencias"),
    )
    op.create_table(
        "config_aviso",
        sa.Column("tipo", sa.Text(), primary_key=True),
        sa.Column("ligado", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "sinal_servico",
        sa.Column("servico", sa.Text(), primary_key=True),
        sa.Column("ultimo_em", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sinal_servico")
    op.drop_table("config_aviso")
    op.drop_table("estado_aviso")
```

- [ ] **Step 6: Serviço**

Crie `src/tcg_sniper/avisos/servico.py`:

```python
"""API pública dos avisos do WhatsApp: `avisar` registra a ocorrência e, conforme a regra de repetição e o
liga/desliga do tipo, grava a mensagem na tabela de saída (`mensagem_saida`, enviada pelo serviço
`notificador`); `resolver` fecha um problema aberto e manda "✅ resolvido" se algum aviso dele saiu.

Repetição (tipos com `agrupa`), estado por (tipo, chave) em `estado_aviso`:
- sem problema aberto: abre (ocorrências = 1) e envia;
- aberto e último envio há menos que `lembrete`: só conta;
- aberto e último envio há `lembrete` ou mais (ou nunca enviado): manda o lembrete.
O lembrete é decidido no `avisar`: com o serviço parado nada se acumula.

Nada aqui propaga exceção (cada chamada roda num SAVEPOINT; falha vira log), menos `UrlProibida` com
`formato.ESTRITO` ligado (testes)."""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.avisos import formato
from tcg_sniper.avisos.catalogo import CATALOGO, Dados, TipoAviso
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import ConfigAviso, ConfigGeral, EstadoAviso
from tcg_sniper.db.repositorio import agora_utc

log = logging.getLogger(__name__)

FUSO_PADRAO = "America/Sao_Paulo"


def _deixar_subir(erro: Exception) -> bool:
    return formato.ESTRITO and isinstance(erro, formato.UrlProibida)


def zona_e_host(s: Session) -> tuple[ZoneInfo, str | None]:
    """Fuso e host_publico de Configurações → Geral (sem a linha: fuso padrão e nenhum host)."""
    geral = s.get(ConfigGeral, 1)
    if geral is None:
        return ZoneInfo(FUSO_PADRAO), None
    try:
        return ZoneInfo(geral.fuso), geral.host_publico
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(FUSO_PADRAO), geral.host_publico


def ligado(s: Session, tipo: TipoAviso) -> bool:
    linha = s.get(ConfigAviso, tipo.value)
    return CATALOGO[tipo].ligado_padrao if linha is None else linha.ligado


def ligados(s: Session) -> dict[TipoAviso, bool]:
    salvos = {c.tipo: c.ligado for c in s.scalars(select(ConfigAviso))}
    return {tipo: salvos.get(tipo.value, d.ligado_padrao) for tipo, d in CATALOGO.items()}


def definir_ligado(s: Session, tipo: TipoAviso, valor: bool) -> None:
    s.execute(
        pg_insert(ConfigAviso)
        .values(tipo=tipo.value, ligado=valor)
        .on_conflict_do_update(index_elements=[ConfigAviso.tipo], set_={"ligado": valor})
    )
    s.flush()


def abertos(s: Session, tipo: TipoAviso) -> list[str]:
    return list(
        s.scalars(
            select(EstadoAviso.chave)
            .where(EstadoAviso.tipo == tipo.value, EstadoAviso.aberto.is_(True))
            .order_by(EstadoAviso.chave)
        )
    )


def _enfileirar(s: Session, tipo: TipoAviso, texto: str, agora: datetime) -> None:
    repo_msg.enfileirar(s, CATALOGO[tipo].grupo.value, texto, agora)


def _travar(s: Session, tipo: TipoAviso, chave: str, agora: datetime) -> EstadoAviso:
    """A linha do problema, criada fechada se não existe e travada para esta transação."""
    s.execute(
        pg_insert(EstadoAviso)
        .values(tipo=tipo.value, chave=chave, aberto=False, primeiro_em=agora, ultimo_em=agora, ocorrencias=0)
        .on_conflict_do_nothing(index_elements=[EstadoAviso.tipo, EstadoAviso.chave])
    )
    return s.get(EstadoAviso, (tipo.value, chave), with_for_update=True, populate_existing=True)


def _avisar(s: Session, tipo: TipoAviso, chave: str, dados: Dados, agora: datetime) -> None:
    definicao = CATALOGO[tipo]
    zona, host = zona_e_host(s)
    aviso = formato.aviso_de(tipo, dados, agora)
    liga = ligado(s, tipo)
    if not definicao.agrupa:
        if liga:
            _enfileirar(s, tipo, formato.formatar(aviso, zona, host), agora)
        return
    estado = _travar(s, tipo, chave, agora)
    if not estado.aberto:
        estado.aberto, estado.ocorrencias = True, 1
        estado.primeiro_em = estado.ultimo_em = agora
        estado.ultimo_envio_em = None
        if liga:
            _enfileirar(s, tipo, formato.formatar(aviso, zona, host), agora)
            estado.ultimo_envio_em = agora
        s.flush()
        return
    estado.ocorrencias += 1
    estado.ultimo_em = agora
    if liga and (estado.ultimo_envio_em is None or agora - estado.ultimo_envio_em >= definicao.lembrete):
        texto = formato.formatar_lembrete(aviso, estado.ocorrencias, estado.primeiro_em, zona, host)
        _enfileirar(s, tipo, texto, agora)
        estado.ultimo_envio_em = agora
    s.flush()


def _resolver(s: Session, tipo: TipoAviso, chave: str, agora: datetime) -> None:
    if not CATALOGO[tipo].agrupa:
        return
    estado = s.get(EstadoAviso, (tipo.value, chave), with_for_update=True, populate_existing=True)
    if estado is None or not estado.aberto:
        return
    estado.aberto = False
    if estado.ultimo_envio_em is not None and ligado(s, tipo):
        zona, host = zona_e_host(s)
        texto = formato.formatar_resolvido(tipo, chave, estado.ocorrencias, estado.primeiro_em, agora, zona, host)
        _enfileirar(s, tipo, texto, agora)
    s.flush()


def avisar(s: Session, tipo: TipoAviso, chave: str, dados: Dados, agora: datetime) -> None:
    try:
        with s.begin_nested():
            _avisar(s, tipo, chave, dados, agora)
    except Exception as erro:
        if _deixar_subir(erro):
            raise
        log.exception("aviso %s (%s) não registrado", tipo.value, chave)


def resolver(s: Session, tipo: TipoAviso, chave: str, agora: datetime) -> None:
    try:
        with s.begin_nested():
            _resolver(s, tipo, chave, agora)
    except Exception as erro:
        if _deixar_subir(erro):
            raise
        log.exception("resolução do aviso %s (%s) não registrada", tipo.value, chave)


def resolver_todos(s: Session, tipo: TipoAviso, agora: datetime) -> None:
    """Fecha todos os problemas abertos do tipo (ex.: todos os períodos sem orçamento da IA)."""
    try:
        with s.begin_nested():
            chaves = abertos(s, tipo)
    except Exception:
        log.exception("não consegui ler os avisos %s abertos", tipo.value)
        return
    for chave in chaves:
        resolver(s, tipo, chave, agora)


class Avisador(Protocol):
    """O que os serviços recebem no lugar do antigo `Notificador`."""

    def avisar(self, tipo: TipoAviso, chave: str, dados: Dados) -> None: ...

    def resolver(self, tipo: TipoAviso, chave: str) -> None: ...

    def resolver_todos(self, tipo: TipoAviso) -> None: ...


class AvisadorBanco:
    """`Avisador` de produção: cada chamada na própria transação. Nunca lança exceção (menos no modo estrito)."""

    def __init__(self, sessoes: sessionmaker[Session], relogio: Callable[[], datetime] | None = None):
        self._sessoes = sessoes
        self._relogio = relogio or agora_utc

    def _rodar(self, funcao, tipo: TipoAviso, *args) -> None:
        try:
            with self._sessoes() as s, s.begin():
                funcao(s, tipo, *args, self._relogio())
        except Exception as erro:
            if _deixar_subir(erro):
                raise
            log.exception("aviso %s não registrado", tipo.value)

    def avisar(self, tipo: TipoAviso, chave: str, dados: Dados) -> None:
        self._rodar(avisar, tipo, chave, dados)

    def resolver(self, tipo: TipoAviso, chave: str) -> None:
        self._rodar(resolver, tipo, chave)

    def resolver_todos(self, tipo: TipoAviso) -> None:
        self._rodar(resolver_todos, tipo)


def criar_avisador(sessoes: sessionmaker[Session]) -> AvisadorBanco:
    return AvisadorBanco(sessoes)
```

- [ ] **Step 7: `AvisadorFake`**

No topo de `tests/fakes.py`, acrescente aos imports:

```python
from zoneinfo import ZoneInfo

from tcg_sniper.avisos import formato
from tcg_sniper.avisos.catalogo import CATALOGO, Dados, TipoAviso
```

No fim de `tests/fakes.py`:

```python
class AvisadorFake:
    """Guarda os avisos e monta o texto de cada um pelo `formato`, em modo estrito: endereço do sistema
    numa mensagem de qualquer serviço faz o teste falhar. Não agrupa (a regra de repetição é do serviço
    de avisos e tem os próprios testes)."""

    def __init__(self, host_publico: str = "host.test"):
        self._host = host_publico
        self.avisos: list[tuple[TipoAviso, str, Dados]] = []
        self.resolvidos: list[tuple[TipoAviso, str]] = []
        self.mensagens: list[tuple[Destino, str]] = []

    def avisar(self, tipo: TipoAviso, chave: str, dados: Dados) -> None:
        aviso = formato.aviso_de(tipo, dados, T0)
        texto = formato.formatar(aviso, ZoneInfo("America/Sao_Paulo"), self._host, estrito=True)
        self.avisos.append((tipo, chave, dados))
        self.mensagens.append((CATALOGO[tipo].grupo, texto))

    def resolver(self, tipo: TipoAviso, chave: str) -> None:
        self.resolvidos.append((tipo, chave))

    def resolver_todos(self, tipo: TipoAviso) -> None:
        self.resolvidos.append((tipo, "*"))

    def tipos(self) -> list[TipoAviso]:
        return [tipo for tipo, _, _ in self.avisos]

    def dados(self, tipo: TipoAviso) -> list[Dados]:
        return [d for t, _, d in self.avisos if t is tipo]
```

- [ ] **Step 8: Rodar os testes**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t2 uv run pytest -q -p no:cacheprovider tests/avisos tests/db/test_migracao.py`
Expected: PASS (inclui `test_migracao_igual_aos_modelos`).

- [ ] **Step 9: Suíte inteira, ruff e commit**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t2 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde.

```bash
git add src/tcg_sniper/db/models.py src/tcg_sniper/db/migrations/versions/e4b7c2d9a1f6_avisos.py src/tcg_sniper/avisos/servico.py tests/fakes.py tests/avisos/test_servico.py
git commit -m "feat: alert state, on/off per type and avisar/resolver with repetition rule"
```

---

### Task 3: Dados da oportunidade no formato novo

**Files:**
- Modify: `src/tcg_sniper/oportunidades/mensagens.py` (acrescenta `dados_oportunidade`; `mensagem_oportunidade` fica até a Task 6)
- Test: `tests/oportunidades/test_dados_oportunidade.py` (novo)

**Interfaces:**
- Consumes: Task 1 (`Dados`, `Negrito`, `Trecho`, `TipoAviso`, `formato.aviso_de`, `formato.formatar`); `motor.Leitura`, `motor.RefLiga`, `motor.desconto_pct`; `mensagens.Detalhes` (sem mudança).
- Produces: `mensagens.dados_oportunidade(*, nome_produto: str, leitura: Leitura, ref: RefLiga, url_amazon: str, variacao: str | None = None, detalhes: Detalhes | None = None) -> Dados` (o chamador passa `TipoAviso.OPORTUNIDADE` e a chave `str(anuncio_id)`).

- [ ] **Step 1: Banco da lane**

Run: `docker compose exec -T postgres-teste createdb -U tcg tcg_test_t3`

- [ ] **Step 2: Testes (falham)**

Crie `tests/oportunidades/test_dados_oportunidade.py`:

```python
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from tcg_sniper.avisos.catalogo import CATALOGO, Negrito, TipoAviso
from tcg_sniper.avisos.formato import aviso_de, formatar
from tcg_sniper.db.models import Envio
from tcg_sniper.oportunidades.mensagens import Detalhes, dados_oportunidade
from tcg_sniper.oportunidades.motor import Leitura, RefLiga, Vendedor

AGORA = datetime(2026, 10, 18, 13, 42, tzinfo=UTC)
SP = ZoneInfo("America/Sao_Paulo")
URL = "https://www.amazon.com.br/dp/B0TESTE123"
NOME = "Final Fantasy - Caixa de Booster de Jogo"


def texto(dados):
    return formatar(aviso_de(TipoAviso.OPORTUNIDADE, dados, AGORA), SP, "192.168.0.10", estrito=True)


def test_modelo_do_spec():
    dados = dados_oportunidade(
        nome_produto=NOME,
        leitura=Leitura(Decimal("1299.90"), Envio.AMAZON, None),
        ref=RefLiga(Decimal("1589.00"), AGORA, num_lojas=12, preco_medio=Decimal("1640.00")),
        url_amazon=URL,
        detalhes=Detalhes(preco_conferido=Decimal("1299.90"), prime=True),
    )
    assert dados == CATALOGO[TipoAviso.OPORTUNIDADE].exemplo
    assert texto(dados) == (
        "💰 *Oportunidade · 18% abaixo da Liga*\n"
        "*Final Fantasy - Caixa de Booster de Jogo*\n"
        "• Amazon: *R$ 1.299,90* (conferido, com impostos; frete à parte)\n"
        "• Vendido por: Amazon · Prime\n"
        "• Liga: a partir de R$ 1.589,00 · 12 lojas · média R$ 1.640,00\n"
        "https://www.amazon.com.br/dp/B0TESTE123\n"
        "_18/10 10:42 · monitor Amazon_"
    )


def test_fba_nao_conferido_sem_resumo_da_liga():
    dados = dados_oportunidade(
        nome_produto=NOME,
        leitura=Leitura(Decimal("599.90"), Envio.FBA, Vendedor("Loja X", Decimal("97.50"), 2340)),
        ref=RefLiga(Decimal("889.00"), AGORA),
        url_amazon=URL,
        detalhes=Detalhes(motivo_nao_conferido="conferência desligada"),
    )
    assert dados.titulo_extra == "32% abaixo da Liga"
    assert dados.linhas == (
        ("Amazon: ", Negrito("R$ 599,90"), " (anunciado, sem impostos; não conferido: conferência desligada)"),
        "Vendido por: Loja X (97,5% de 2.340 avaliações) · enviado pela Amazon",
        "Liga: a partir de R$ 889,00",
    )


def test_sem_motivo_diz_aguardando_conferencia():
    dados = dados_oportunidade(
        nome_produto=NOME, leitura=Leitura(Decimal("599.90"), Envio.AMAZON, None), ref=RefLiga(Decimal("889.00"), AGORA),
        url_amazon=URL, detalhes=Detalhes(),
    )
    assert dados.linhas[0][2] == " (anunciado, sem impostos; não conferido: aguardando conferência)"


def test_variacao_vai_no_rotulo_da_amazon():
    dados = dados_oportunidade(
        nome_produto=NOME, leitura=Leitura(Decimal("599.90"), Envio.AMAZON, None), ref=RefLiga(Decimal("889.00"), AGORA),
        url_amazon=URL, variacao="Collector Booster Box",
    )
    assert dados.linhas[0] == ("Amazon (Collector Booster Box): ", Negrito("R$ 599,90"))


def test_conferido_com_impostos_frete_importado_prime_e_cupom():
    dados = dados_oportunidade(
        nome_produto="Aetherdrift Commander Deck - Eternal Might",
        leitura=Leitura(Decimal("285.99"), Envio.FBA, Vendedor("Shazaar", Decimal(100), 66)),
        ref=RefLiga(Decimal("400.00"), AGORA),
        url_amazon="https://www.amazon.com.br/dp/B0DNV55QBS",
        detalhes=Detalhes(
            preco_conferido=Decimal("285.99"), impostos=Decimal("48.26"), frete=Decimal("12.50"), importada=True,
            origem_envio="Estados Unidos", prime=True, cupom="15% off na 1ª compra com cartão Amazon",
        ),
    )
    assert dados.titulo_extra == "28% abaixo da Liga"
    assert dados.linhas == (
        ("Amazon: ", Negrito("R$ 285,99"), " (conferido, com impostos de R$ 48,26; frete R$ 12,50 à parte)"),
        "Vendido por: Shazaar (100% de 66 avaliações) · enviado pela Amazon · importado (EUA) · Prime",
        "Liga: a partir de R$ 400,00",
        "Cupom: 15% off na 1ª compra com cartão Amazon (condicional, não descontado)",
    )


def test_frete_zero_e_frete_gratis():
    dados = dados_oportunidade(
        nome_produto=NOME, leitura=Leitura(Decimal("599.90"), Envio.AMAZON, None), ref=RefLiga(Decimal("889.00"), AGORA),
        url_amazon=URL, detalhes=Detalhes(preco_conferido=Decimal("599.90"), frete=Decimal("0.00")),
    )
    assert dados.linhas[0][2] == " (conferido, com impostos; frete grátis)"


def test_nome_com_marcador_e_escapado_no_texto():
    dados = dados_oportunidade(
        nome_produto="Caixa *Edição* _Especial_", leitura=Leitura(Decimal("599.90"), Envio.AMAZON, None),
        ref=RefLiga(Decimal("889.00"), AGORA), url_amazon=URL,
    )
    assert "\n*Caixa ∗Edição∗ ˍEspecialˍ*\n" in texto(dados)
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t3 uv run pytest -q -p no:cacheprovider tests/oportunidades/test_dados_oportunidade.py`
Expected: FAIL com `ImportError: cannot import name 'dados_oportunidade'`.

- [ ] **Step 4: Implementar**

Em `src/tcg_sniper/oportunidades/mensagens.py`, acrescente ao import: `from tcg_sniper.avisos.catalogo import Dados, Negrito, Trecho`. No fim do arquivo:

```python
def _linha_amazon(leitura: Leitura, detalhes: Detalhes | None, variacao: str | None) -> tuple[Trecho, ...]:
    rotulo = f"Amazon ({variacao}): " if variacao else "Amazon: "
    if detalhes is None:
        return (rotulo, Negrito(formatar_brl(leitura.preco)))
    if detalhes.preco_conferido is not None:
        impostos = f" de {formatar_brl(detalhes.impostos)}" if detalhes.impostos is not None else ""
        if detalhes.frete is None:
            frete = "frete à parte"
        elif detalhes.frete == 0:
            frete = "frete grátis"
        else:
            frete = f"frete {formatar_brl(detalhes.frete)} à parte"
        return (rotulo, Negrito(formatar_brl(detalhes.preco_conferido)), f" (conferido, com impostos{impostos}; {frete})")
    motivo = detalhes.motivo_nao_conferido or "aguardando conferência"
    return (rotulo, Negrito(formatar_brl(leitura.preco)), f" (anunciado, sem impostos; não conferido: {motivo})")


def _linha_vendedor(leitura: Leitura, detalhes: Detalhes | None) -> str:
    if leitura.envio is Envio.AMAZON:
        texto = "Vendido por: Amazon"
    else:
        v = leitura.vendedor
        nome = (v.nome if v else None) or "lojista"
        if v and v.pct_positivas is not None and v.num_avaliacoes is not None:
            avaliacoes = f"{v.num_avaliacoes:,}".replace(",", ".")
            nome = f"{nome} ({_pct(v.pct_positivas)}% de {avaliacoes} avaliações)"
        texto = f"Vendido por: {nome} · enviado pela Amazon"
    return texto + _selos(detalhes)


def dados_oportunidade(
    *,
    nome_produto: str,
    leitura: Leitura,
    ref: RefLiga,
    url_amazon: str,
    variacao: str | None = None,
    detalhes: Detalhes | None = None,
) -> Dados:
    """Dados do aviso `OPORTUNIDADE` (grupo de oportunidades). Com conferência vale o preço conferido
    (itens + impostos, sem o frete, que aparece à parte); sem ela, o anunciado, sem impostos."""
    desconto = desconto_pct(leitura.preco, ref.preco_a_partir).quantize(Decimal(1), ROUND_DOWN)
    liga = f"Liga: a partir de {formatar_brl(ref.preco_a_partir)}"
    if ref.num_lojas is not None:
        liga += f" · {ref.num_lojas} lojas"
    if ref.preco_medio is not None:
        liga += f" · média {formatar_brl(ref.preco_medio)}"
    linhas: list = [_linha_amazon(leitura, detalhes, variacao), _linha_vendedor(leitura, detalhes), liga]
    if detalhes is not None and detalhes.cupom:
        linhas.append(f"Cupom: {detalhes.cupom} (condicional, não descontado)")
    return Dados(
        titulo_extra=f"{desconto}% abaixo da Liga", destaque=nome_produto, linhas=tuple(linhas), link_produto=url_amazon
    )
```

- [ ] **Step 5: Rodar, suíte inteira, ruff e commit**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t3 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde.

```bash
git add src/tcg_sniper/oportunidades/mensagens.py tests/oportunidades/test_dados_oportunidade.py
git commit -m "feat: opportunity alert data in the new WhatsApp format"
```

---

### Task 4: LigaMagic

**Files:**
- Modify: `src/tcg_sniper/coletor_liga/execucao.py`
- Modify: `src/tcg_sniper/coletor_liga/agendador.py`
- Modify: `src/tcg_sniper/coletor_liga/listagens.py`
- Modify: `src/tcg_sniper/coletor_liga/produtos.py`
- Modify: `src/tcg_sniper/cli.py` (ramo `coletor-liga`)
- Test: `tests/coletor_liga/test_agendador.py`, `tests/coletor_liga/test_listagens.py`, `tests/coletor_liga/test_produtos.py`

**Interfaces:**
- Consumes: Task 2 (`Avisador`, `criar_avisador`, `fakes.AvisadorFake`); Task 1 (`CHAVE_GERAL`, `Dados`, `TipoAviso`, `formato.formatar_duracao`).
- Produces:
  - `execucao.dados_desafio(url: str) -> Dados`; `execucao.dados_resumo(dia: date, listagens: ResultadoColeta | None, produtos: ResultadoColeta, duracao: timedelta) -> Dados` (saem `mensagem_desafio` e `mensagem_resumo`).
  - `execucao.registrar_desafio(sessoes, avisador: Avisador, coleta_id: int, url: str, ok: int, falha: int) -> None` (sai o parâmetro `config`).
  - `execucao.concluir_coleta(sessoes, avisador: Avisador, config, coleta_id, descricao, unidade, ok, falha, novos=0) -> ResultadoColeta`.
  - `execucao.encerrar_por_erro(sessoes, avisador: Avisador, coleta_id, descricao, erro, ok, falha, novos=0) -> ResultadoColeta`.
  - `coletar_listagens(sessoes, navegador, avisador: Avisador, config, dormir=..., embaralhar=...)`, `coletar_produtos(sessoes, navegador, avisador: Avisador, config, dormir=..., embaralhar=...)`.
  - `Agendador(engine, sessoes, fabrica_navegador, avisador: Avisador, config, relogio=None, rng=None, dormir=..., executor=None)`.

- [ ] **Step 1: Banco da lane**

Run: `docker compose exec -T postgres-teste createdb -U tcg tcg_test_t4`

- [ ] **Step 2: Ajustar os testes da Liga (falham)**

Nos três arquivos de teste, troque `NotificadorFake` por `AvisadorFake` (import e uso) e a variável `notificador` por `avisador`; acrescente `from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso`. Depois troque as asserções abaixo.

`tests/coletor_liga/test_agendador.py`:

```python
def test_excecao_no_job_avisa_e_nao_repete_no_dia(engine, sessoes, config):
    job_ok(sessoes, ONTEM, 14)
    relogio = Relogio(local(TERCA, 10, 31))
    chamadas = []
    a, avisador = agendador(engine, sessoes, config, relogio, chamadas, falhar=True)
    a.inicializar()
    assert a.tick() == "agendado"
    relogio.agora += timedelta(minutes=1)
    assert a.tick() is None
    assert chamadas == [True]
    [(tipo, chave, dados)] = avisador.avisos
    assert (tipo, chave) == (TipoAviso.LIGA_ERRO, CHAVE_GERAL)
    assert dados.linhas[0] == "Onde: job agendado" and "chromium não abriu" in dados.linhas[1]


def test_inicializar_avisa_admin_das_interrompidas(engine, sessoes, config):
    coleta(sessoes, TipoColeta.LISTAGEM, local(TERCA, 10), status=StatusColeta.RODANDO)
    coleta(sessoes, TipoColeta.PRODUTOS, local(TERCA, 10, 30), status=StatusColeta.RODANDO)
    a, avisador = agendador(engine, sessoes, config, Relogio(local(TERCA, 12)), [])
    a.inicializar()
    assert avisador.avisos == [
        (
            TipoAviso.LIGA_INTERROMPIDA,
            CHAVE_GERAL,
            Dados(linhas=("2 coleta(s) marcada(s) como falha: o coletor reiniciou no meio do job",)),
        )
    ]
    [(destino, texto)] = avisador.mensagens
    assert destino is Destino.ADMIN and "Rodar agora" in texto and ":8000" not in texto


def resumos(avisador):
    tipos = (TipoAviso.LIGA_COLETA_CONCLUIDA, TipoAviso.LIGA_COLETA_PARCIAL)
    return [(tipo, dados) for tipo, _, dados in avisador.avisos if tipo in tipos]


def test_job_completo_envia_resumo(engine, sessoes, config):
    c, url = config_uma_categoria(config)
    navegador = NavegadorFake({url: pagina_html(fixture_liga("catalogo_pagina_1"), url=url)})
    a, avisador = agendador_resumo(engine, sessoes, c, navegador)
    a.executar_job(incluir_listagens=True)
    with sessoes() as s:
        novos = s.scalar(select(func.count()).select_from(ProdutoLiga))
    assert resumos(avisador) == [
        (
            TipoAviso.LIGA_COLETA_CONCLUIDA,
            Dados(
                titulo_extra="13/10",
                linhas=(
                    f"Listagens: ok · 1 de 1 categorias · {novos} produtos novos",
                    "Produtos: ok · 0 ok · 0 falhas",
                    "Duração: menos de 1 min",
                ),
            ),
        )
    ]
    for tipo in (TipoAviso.LIGA_DESAFIO, TipoAviso.LIGA_COLETA_FALHOU, TipoAviso.LIGA_ERRO):
        assert (tipo, CHAVE_GERAL) in avisador.resolvidos


def test_job_so_produtos_envia_resumo_sem_listagens(engine, sessoes, config):
    a, avisador = agendador_resumo(engine, sessoes, config, NavegadorFake({}))
    a.executar_job(incluir_listagens=False)
    assert resumos(avisador) == [
        (
            TipoAviso.LIGA_COLETA_CONCLUIDA,
            Dados(titulo_extra="13/10", linhas=("Produtos: ok · 0 ok · 0 falhas", "Duração: menos de 1 min")),
        )
    ]


def test_job_com_etapa_parcial_avisa_coleta_parcial(engine, sessoes, config, monkeypatch):
    from tcg_sniper.coletor_liga import agendador as modulo

    monkeypatch.setattr(modulo, "coletar_produtos", lambda *_a, **_k: ResultadoColeta(1, StatusColeta.PARCIAL, 3, 1))
    a, avisador = agendador_resumo(engine, sessoes, config, NavegadorFake({}))
    a.executar_job(incluir_listagens=False)
    [(tipo, dados)] = resumos(avisador)
    assert tipo is TipoAviso.LIGA_COLETA_PARCIAL and dados.linhas[0] == "Produtos: parcial · 3 ok · 1 falhas"
    assert (TipoAviso.LIGA_COLETA_FALHOU, CHAVE_GERAL) in avisador.resolvidos


def test_job_com_etapa_que_falhou_nao_manda_conclusao_nem_resolve(engine, sessoes, config, monkeypatch):
    from tcg_sniper.coletor_liga import agendador as modulo

    monkeypatch.setattr(modulo, "coletar_produtos", lambda *_a, **_k: ResultadoColeta(1, StatusColeta.FALHA, 0, 3))
    a, avisador = agendador_resumo(engine, sessoes, config, NavegadorFake({}))
    a.executar_job(incluir_listagens=False)
    assert resumos(avisador) == []
    assert (TipoAviso.LIGA_COLETA_FALHOU, CHAVE_GERAL) not in avisador.resolvidos


def test_desafio_nao_envia_resumo(engine, sessoes, config):
    c, url = config_uma_categoria(config)
    a, avisador = agendador_resumo(engine, sessoes, c, NavegadorFake({url: DESAFIO}))
    a.executar_job(incluir_listagens=True)
    assert TipoAviso.LIGA_DESAFIO in avisador.tipos()
    assert resumos(avisador) == []
```

(Os demais testes que só desempacotam `a, notificador = …` ou checam `resumos(...) == []` continuam iguais com a troca de nomes.)

`tests/coletor_liga/test_listagens.py`:

```python
# test_varre_todas_as_categorias_grava_catalogo_e_preco_atual
    assert avisador.avisos == [
        (TipoAviso.LIGA_PRODUTOS_NOVOS, CHAVE_GERAL, Dados(linhas=("42 produtos novos nas listagens",)))
    ]

# test_segunda_coleta_nao_avisa_e_acrescenta_historico
    assert avisador.avisos == []

# test_desafio_na_segunda_categoria_pausa_e_avisa
    assert avisador.tipos() == [TipoAviso.LIGA_DESAFIO, TipoAviso.LIGA_PRODUTOS_NOVOS]
    desafio = avisador.dados(TipoAviso.LIGA_DESAFIO)[0]
    assert desafio.linhas == ("Página: /listagem?categ=11", "A coleta fica pausada até você retomar")
    assert "noVNC da Liga (porta 6080)" in avisador.mensagens[0][1]
    assert avisador.dados(TipoAviso.LIGA_PRODUTOS_NOVOS)[0].linhas == ("40 produtos novos nas listagens",)

# test_falha_de_parser_salva_html_e_status_parcial
    assert TipoAviso.LIGA_COLETA_FALHOU not in avisador.tipos()

# test_mais_da_metade_falhando_avisa_layout
    [falhou] = avisador.dados(TipoAviso.LIGA_COLETA_FALHOU)
    assert falhou.linhas == ("Etapa: Coleta das listagens", "Falhas: 2 de 3 categorias")

# test_erro_inesperado_fecha_coleta_como_falha
    [erro] = avisador.dados(TipoAviso.LIGA_ERRO)
    assert erro.linhas[0].startswith("Onde: Coleta das listagens ") and "chromium morreu" in erro.linhas[1]
    assert avisador.dados(TipoAviso.LIGA_PRODUTOS_NOVOS)[0].linhas == ("40 produtos novos nas listagens",)
```

`tests/coletor_liga/test_produtos.py`:

```python
# teste do desafio (linhas 81-90)
    [(tipo, _, dados)] = avisador.avisos
    assert tipo is TipoAviso.LIGA_DESAFIO and dados.linhas[0] == "Página: /produto/b"
    assert ":6080" not in avisador.mensagens[0][1] and ":8000" not in avisador.mensagens[0][1]

# teste de "falhou em 2 de 3 produtos" (linhas 128-132)
    [falhou] = avisador.dados(TipoAviso.LIGA_COLETA_FALHOU)
    assert falhou.linhas == ("Etapa: Coleta dos produtos ativos", "Falhas: 2 de 3 produtos")

# test_erro_inesperado_fecha_coleta_como_falha (linha 151)
    assert avisador.tipos() == [TipoAviso.LIGA_ERRO]
```

(Se a URL do produto no teste do desafio não for `…/produto/b`, use o caminho da URL que o teste abre: `urlsplit(url).path`.)

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t4 uv run pytest -q -p no:cacheprovider tests/coletor_liga`
Expected: FAIL (`AvisadorFake` não tem `enviar`; asserções de tipo).

- [ ] **Step 4: `execucao.py`**

Troque o import `from tcg_sniper.notificador.base import Destino, Notificador` por:

```python
from datetime import date, timedelta
from urllib.parse import urlsplit

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.avisos.formato import formatar_duracao
from tcg_sniper.avisos.servico import Avisador
```

(junte `date, timedelta` ao `from datetime import date` existente). Substitua `mensagem_desafio`, `mensagem_resumo`, `registrar_desafio`, `concluir_coleta` e `encerrar_por_erro` por:

```python
def dados_desafio(url: str) -> Dados:
    """Só o caminho da página (sem o domínio): o aviso diz onde parou, a ação diz onde resolver."""
    partes = urlsplit(url)
    pagina = (partes.path or "/") + (f"?{partes.query}" if partes.query else "")
    return Dados(linhas=(f"Página: {pagina}", "A coleta fica pausada até você retomar"))


def dados_resumo(
    dia: date, listagens: ResultadoColeta | None, produtos: ResultadoColeta, duracao: timedelta
) -> Dados:
    """Resumo de um job concluído. `listagens` é None quando o job rodou só os produtos. Nas listagens,
    ok/falha contam categorias."""
    linhas = []
    if listagens is not None:
        total = listagens.produtos_ok + listagens.produtos_falha
        linhas.append(
            f"Listagens: {listagens.status.value} · {listagens.produtos_ok} de {total} categorias · "
            f"{listagens.novos} produtos novos"
        )
    linhas.append(f"Produtos: {produtos.status.value} · {produtos.produtos_ok} ok · {produtos.produtos_falha} falhas")
    linhas.append(f"Duração: {formatar_duracao(duracao)}")
    return Dados(titulo_extra=f"{dia:%d/%m}", linhas=tuple(linhas))


def registrar_desafio(
    sessoes: sessionmaker[Session],
    avisador: Avisador,
    coleta_id: int,
    url: str,
    ok: int,
    falha: int,
) -> None:
    agora = repo.agora_utc()
    with sessoes() as s, s.begin():
        repo.finalizar_coleta(
            s, coleta_id, StatusColeta.PAUSADA_DESAFIO, ok, falha, agora, erro=f"desafio em {url}"
        )
        repo.pausar_por_desafio(s, f"desafio em {url}", agora)
    log.warning("desafio do Cloudflare em %s; coletor pausado", url)
    avisador.avisar(TipoAviso.LIGA_DESAFIO, CHAVE_GERAL, dados_desafio(url))


def concluir_coleta(
    sessoes: sessionmaker[Session],
    avisador: Avisador,
    config: Config,
    coleta_id: int,
    descricao: str,
    unidade: str,
    ok: int,
    falha: int,
    novos: int = 0,
) -> ResultadoColeta:
    """Fecha a coleta com ok/parcial/falha (LIMITE_FALHA_PCT) e avisa o admin se for falha."""
    status = repo.status_final(ok, falha, config.limite_falha_pct)
    with sessoes() as s, s.begin():
        repo.finalizar_coleta(s, coleta_id, status, ok, falha, repo.agora_utc())
    log.info("%s %s terminou: %s (%d ok, %d falhas)", descricao, coleta_id, status.value, ok, falha)
    if status is StatusColeta.FALHA:
        dados = Dados(linhas=(f"Etapa: {descricao}", f"Falhas: {falha} de {ok + falha} {unidade}"))
        avisador.avisar(TipoAviso.LIGA_COLETA_FALHOU, CHAVE_GERAL, dados)
    return ResultadoColeta(coleta_id, status, ok, falha, novos)


def encerrar_por_erro(
    sessoes: sessionmaker[Session],
    avisador: Avisador,
    coleta_id: int,
    descricao: str,
    erro: Exception,
    ok: int,
    falha: int,
    novos: int = 0,
) -> ResultadoColeta:
    """Erro inesperado no meio da coleta (chamar de dentro do `except`): fecha como falha,
    guarda o erro e avisa o admin."""
    log.exception("erro inesperado em %s %s", descricao, coleta_id)
    with sessoes() as s, s.begin():
        repo.finalizar_coleta(s, coleta_id, StatusColeta.FALHA, ok, falha, repo.agora_utc(), erro=repr(erro))
    dados = Dados(linhas=(f"Onde: {descricao} {coleta_id}", f"Erro: {erro!r}"))
    avisador.avisar(TipoAviso.LIGA_ERRO, CHAVE_GERAL, dados)
    return ResultadoColeta(coleta_id, StatusColeta.FALHA, ok, falha, novos, interrompida=True)
```

Atualize o comentário de `ResultadoColeta.interrompida` para "(o admin já foi avisado por `encerrar_por_erro`)" — sem mudança de sentido.

- [ ] **Step 5: `listagens.py` e `produtos.py`**

Em ambos, troque `from tcg_sniper.notificador.base import …` por `from tcg_sniper.avisos.servico import Avisador` (e, em `listagens.py`, também `from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso`); renomeie o parâmetro `notificador: Notificador` para `avisador: Avisador` em `coletar_*` e `_varrer`; nas chamadas: `registrar_desafio(sessoes, avisador, coleta_id, url, ok, falha)`, `encerrar_por_erro(sessoes, avisador, …)`, `concluir_coleta(sessoes, avisador, config, …)`. Em `coletar_listagens`, o aviso de novos vira:

```python
    if resultado.novos:
        avisador.avisar(
            TipoAviso.LIGA_PRODUTOS_NOVOS, CHAVE_GERAL, Dados(linhas=(f"{resultado.novos} produtos novos nas listagens",))
        )
```

- [ ] **Step 6: `agendador.py`**

Troque o import do notificador e o de `mensagem_resumo` por:

```python
from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.avisos.servico import Avisador
from tcg_sniper.coletor_liga.execucao import dados_resumo, pausa_humana
```

No `__init__`: parâmetro `avisador: Avisador` no lugar de `notificador` e `self._avisador = avisador`. Em `inicializar`:

```python
        if interrompidas:
            log.warning("%d coleta(s) interrompida(s) marcadas como falha", interrompidas)
            dados = Dados(linhas=(f"{interrompidas} coleta(s) marcada(s) como falha: o coletor reiniciou no meio do job",))
            self._avisador.avisar(TipoAviso.LIGA_INTERROMPIDA, CHAVE_GERAL, dados)
```

Em `_executar`, o `except`:

```python
        except Exception as erro:
            log.exception("job %s falhou", motivo)
            dados = Dados(linhas=(f"Onde: job {motivo}", f"Erro: {erro!r}"))
            self._avisador.avisar(TipoAviso.LIGA_ERRO, CHAVE_GERAL, dados)
```

`_coletar` inteiro:

```python
    def _coletar(self, navegador: Navegador, incluir_listagens: bool) -> bool:
        """Roda as etapas do job. Devolve True se parou num desafio do Cloudflare. Se o job vai até o fim
        sem desafio, sem etapa interrompida por erro e sem etapa que falhou, avisa "concluída" (ou
        "parcial") e resolve as falhas e erros abertos. O job só roda com a Liga ativa: um desafio aberto
        foi resolvido (retomada)."""
        inicio = self._relogio()
        self._avisador.resolver(TipoAviso.LIGA_DESAFIO, CHAVE_GERAL)
        listagens = None
        if incluir_listagens:
            listagens = coletar_listagens(self._sessoes, navegador, self._avisador, self._config, self._dormir)
            if listagens is None:
                return False
            if listagens.status is StatusColeta.PAUSADA_DESAFIO:
                return True
            pausa_humana(self._config, self._dormir)
        produtos = coletar_produtos(self._sessoes, navegador, self._avisador, self._config, self._dormir)
        if produtos is None:
            return False
        if produtos.status is StatusColeta.PAUSADA_DESAFIO:
            return True
        etapas = [r for r in (listagens, produtos) if r is not None]
        if any(r.interrompida or r.status is StatusColeta.FALHA for r in etapas):
            return False  # o LIGA_ERRO ou o LIGA_COLETA_FALHOU da etapa já saiu
        hoje = self._relogio().astimezone(self._config.zona).date()
        dados = dados_resumo(hoje, listagens, produtos, self._relogio() - inicio)
        parcial = any(r.status is StatusColeta.PARCIAL for r in etapas)
        tipo = TipoAviso.LIGA_COLETA_PARCIAL if parcial else TipoAviso.LIGA_COLETA_CONCLUIDA
        self._avisador.avisar(tipo, CHAVE_GERAL, dados)
        self._avisador.resolver(TipoAviso.LIGA_COLETA_FALHOU, CHAVE_GERAL)
        self._avisador.resolver(TipoAviso.LIGA_ERRO, CHAVE_GERAL)
        return False
```

- [ ] **Step 7: `cli.py`**

No ramo `coletor-liga`, troque `from tcg_sniper.notificador import criar_notificador` por `from tcg_sniper.avisos.servico import criar_avisador` e o argumento `criar_notificador(config, sessoes)` por `criar_avisador(sessoes)`.

- [ ] **Step 8: Rodar, suíte inteira, ruff e commit**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t4 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde. Confirme que `grep -rn "host_publico\|:8000\|:6080" src/tcg_sniper/coletor_liga` não acha nada.

```bash
git add src/tcg_sniper/coletor_liga src/tcg_sniper/cli.py tests/coletor_liga
git commit -m "feat: LigaMagic collector sends catalog alerts without system addresses"
```

---

### Task 5: Casador, manutenção e notificador

**Files:**
- Modify: `src/tcg_sniper/casador/servico.py`
- Modify: `src/tcg_sniper/manutencao/servico.py`
- Modify: `src/tcg_sniper/notificador/servico.py`
- Modify: `src/tcg_sniper/db/repositorio_mensagens.py` (acrescenta `falhas_recentes`)
- Modify: `src/tcg_sniper/cli.py` (ramos `casador` e `manutencao`)
- Test: `tests/casador/test_servico.py`, `tests/manutencao/test_servico.py`, `tests/notificador/test_servico.py`, `tests/db/test_repositorio_mensagens.py`

**Interfaces:**
- Consumes: Task 2 (`Avisador`, `criar_avisador`, `avisos.servico.avisar(s, …)`, `fakes.AvisadorFake`); Task 1 (`CHAVE_GERAL`, `Dados`, `TipoAviso`, `formato.eh_do_tipo`); `formatacao.formatar_bytes`.
- Produces:
  - `ServicoCasador(sessoes, transporte, config_env, avisador: Avisador, cliente_http=None, relogio=None, dormir=None)`; `_aplicar(...) -> StatusCasamento | None`; `_gravar(...) -> StatusCasamento | None`.
  - `ServicoManutencao(sessoes, config_env, avisador: Avisador, enviador, executar=..., relogio=None, dormir=None)`.
  - `repositorio_mensagens.falhas_recentes(s: Session, desde: datetime, limite: int = 5) -> list[MensagemSaida]`.
  - `ServicoNotificador._processar(self, s: Session, m: MensagemSaida, geral: _Destinos, agora: datetime) -> Resultado | None`.

- [ ] **Step 1: Banco da lane**

Run: `docker compose exec -T postgres-teste createdb -U tcg tcg_test_t5`

- [ ] **Step 2: Testes do casador (falham)**

Em `tests/casador/test_servico.py`: troque `NotificadorFake` por `AvisadorFake` (import e `servico()`: `n = AvisadorFake()`; `test_sem_chave_nao_chama` usa `AvisadorFake()`), acrescente `from tcg_sniper.avisos.catalogo import CHAVE_GERAL, TipoAviso` e troque/acrescente:

```python
def test_tres_erros_seguidos_encerram_o_ciclo(sessoes, config):
    configurar(sessoes)
    pares(sessoes, 5)
    sv, t, av = servico(sessoes, config, [ErroIA("OpenAI 500")] * 3)
    assert sv.ciclo() == 0 and len(t.pedidos) == 3
    [dados] = av.dados(TipoAviso.IA_FALHAS_SEGUIDAS)
    assert dados.linhas == ("3 chamadas seguidas falharam; a rodada parou", "Última: OpenAI 500")
    assert TipoAviso.IA_RODADA_CONCLUIDA not in av.tipos()


def test_chave_invalida_pausa_e_avisa(sessoes, config):
    configurar(sessoes)
    pares(sessoes, 2)
    sv, t, av = servico(sessoes, config, [ChaveInvalida("chave recusada pela OpenAI (401)")])
    sv.ciclo()
    with sessoes() as s:
        estado = repo.obter_estado(s, coletor=COLETOR_CASADOR)
    assert estado.estado is EstadoColetorTipo.PAUSADO and "401" in estado.motivo
    assert len(t.pedidos) == 1
    assert av.dados(TipoAviso.IA_PAUSADA)[0].linhas == ("Motivo: chave recusada pela OpenAI (401)",)
    assert av.mensagens[0][0] is Destino.ADMIN


def test_sem_orcamento_avisa_com_a_chave_do_periodo(sessoes, config):
    configurar(sessoes, max_chamadas_dia=1)
    pares(sessoes, 3)
    sv, t, av = servico(sessoes, config, [veredito()])
    assert sv.ciclo() == 1 and len(t.pedidos) == 1
    sv.ciclo()
    orcamento = [(c, d) for tipo, c, d in av.avisos if tipo is TipoAviso.IA_SEM_ORCAMENTO]
    assert [c for c, _ in orcamento] == ["dia 13/10", "dia 13/10"]  # o agrupamento é do serviço de avisos
    assert orcamento[0][1].titulo_extra == "dia 13/10" and "chamadas" in orcamento[0][1].linhas[0]
    # dia seguinte: a chamada ok fecha os períodos abertos; estourar de novo abre o dia novo
    sv2, t2, av2 = servico(sessoes, config, [veredito()], agora=T0 + timedelta(days=1))
    assert sv2.ciclo() == 1 and len(t2.pedidos) == 1
    assert (TipoAviso.IA_SEM_ORCAMENTO, "*") in av2.resolvidos
    assert [c for tipo, c, _ in av2.avisos if tipo is TipoAviso.IA_SEM_ORCAMENTO] == ["dia 14/10"]


def test_configuracao_invalida_pausa_e_avisa(sessoes, config):
    configurar(sessoes)
    pares(sessoes, 2)
    motivo = "modelo ou esforço inválido em Configurações → IA: model_not_found (model)"
    sv, t, av = servico(sessoes, config, [ConfiguracaoInvalida(motivo)])
    sv.ciclo()
    with sessoes() as s:
        estado = repo.obter_estado(s, coletor=COLETOR_CASADOR)
    assert estado.estado is EstadoColetorTipo.PAUSADO and "model_not_found" in estado.motivo
    assert len(t.pedidos) == 1 and "model_not_found" in av.dados(TipoAviso.IA_PAUSADA)[0].linhas[0]


def test_rodada_com_avaliacao_avisa_conclusao_com_as_contas(sessoes, config):
    configurar(sessoes, automatico=True, confianca_confirmar=90, confianca_ignorar=85)
    pares(sessoes, 3)
    sv, _, av = servico(sessoes, config, [veredito(True, 95), veredito(False, 90), veredito(True, 50)])
    assert sv.ciclo() == 3
    [dados] = av.dados(TipoAviso.IA_RODADA_CONCLUIDA)
    assert dados.linhas == (
        "Avaliados: 3", "Confirmados pelo automático: 1", "Ignorados pelo automático: 1", "Esperando você: 1",
    )
    assert dados.acao == "Revise os pendentes em Admin → Casamentos."


def test_rodada_sem_ninguem_esperando_nao_tem_acao(sessoes, config):
    configurar(sessoes, automatico=True)
    pares(sessoes, 1)
    sv, _, av = servico(sessoes, config, [veredito(True, 99)])
    sv.ciclo()
    assert av.dados(TipoAviso.IA_RODADA_CONCLUIDA)[0].acao is None


def test_rodada_sem_avaliacao_nao_avisa(sessoes, config):
    configurar(sessoes)
    sv, _, av = servico(sessoes, config, [])
    assert sv.ciclo() == 0 and av.avisos == []


def test_chamada_ok_resolve_falhas_e_orcamento_e_ciclo_ativo_resolve_a_pausa(sessoes, config):
    configurar(sessoes)
    pares(sessoes, 1)
    sv, _, av = servico(sessoes, config, [veredito()])
    sv.ciclo()
    assert av.resolvidos[0] == (TipoAviso.IA_PAUSADA, CHAVE_GERAL)
    assert (TipoAviso.IA_FALHAS_SEGUIDAS, CHAVE_GERAL) in av.resolvidos
    assert (TipoAviso.IA_SEM_ORCAMENTO, "*") in av.resolvidos


def test_pausado_nao_resolve_a_pausa(sessoes, config):
    configurar(sessoes)
    pares(sessoes)
    with sessoes() as s, s.begin():
        repo.pausar(s, "pausado no admin", T0, COLETOR_CASADOR)
    sv, _, av = servico(sessoes, config, [])
    sv.ciclo()
    assert av.resolvidos == []
```

(Apague o antigo `test_sem_orcamento_para_e_avisa_uma_vez_por_dia`: o dedup em memória saiu; a regra "uma vez por período" agora está em `tests/avisos/test_servico.py`.)

- [ ] **Step 3: Testes da manutenção (falham)**

Em `tests/manutencao/test_servico.py`: troque `NotificadorFake` por `AvisadorFake`, o parâmetro `notificador=None` de `servico()` por `avisador=None` (passado na mesma posição para `ServicoManutencao`) e as variáveis `notificador` por `avisador`; acrescente `from tcg_sniper.avisos.catalogo import CHAVE_GERAL, TipoAviso`. Troque:

```python
# test_ok_com_r2_num_dia_de_semana (no lugar de `notificador.mensagens == []`)
    [dados] = avisador.dados(TipoAviso.BACKUP_CONCLUIDO)
    assert dados.titulo_extra == "14/10" and dados.linhas[1] == "Cópia no R2: sim"
    assert dados.linhas[2].startswith("Linhas antigas apagadas: ")
    assert avisador.tipos() == [TipoAviso.BACKUP_CONCLUIDO]
    assert (TipoAviso.BACKUP_ERRO, CHAVE_GERAL) in avisador.resolvidos

# test_sem_r2_fica_so_local_sem_alerta
    assert avisador.tipos() == [TipoAviso.BACKUP_CONCLUIDO]
    assert avisador.dados(TipoAviso.BACKUP_CONCLUIDO)[0].linhas[1] == "Cópia no R2: não (só local)"

# test_falha_do_pg_dump_grava_erro_avisa_uma_vez_e_nao_limpa
    [(tipo, chave, dados)] = avisador.avisos
    assert (tipo, chave) == (TipoAviso.BACKUP_ERRO, CHAVE_GERAL) and dados.titulo_extra == "14/10"
    assert "pg_dump falhou" in dados.linhas[0] and dados.linhas[1] == "Nenhum backup novo foi gravado"
    assert avisador.mensagens[0][0] is Destino.ADMIN and "Traceback" not in avisador.mensagens[0][1]

# test_falha_na_validacao
    assert list(pasta.iterdir()) == [] and avisador.tipos() == [TipoAviso.BACKUP_ERRO]

# test_falha_no_r2_mantem_o_local_avisa_e_nao_vaza_segredo
    assert avisador.tipos() == [TipoAviso.BACKUP_ERRO]
    assert avisador.dados(TipoAviso.BACKUP_ERRO)[0].linhas[1] == "O backup local ficou salvo"
    for texto in (e.erro, avisador.mensagens[0][1], caplog.text):
        ...  # as mesmas asserções de segredo de antes

# test_interrompida_ao_subir_avisa_o_admin_uma_vez
    avisador = AvisadorFake()
    servico(sessoes, config, QUARTA_4H + timedelta(minutes=10), avisador=avisador).inicializar()
    [(tipo, _, dados)] = avisador.avisos
    assert tipo is TipoAviso.BACKUP_INTERROMPIDO
    assert dados.linhas == ("1 execução(ões) interrompida(s) no meio: o serviço de manutenção reiniciou",)
    outro = AvisadorFake()
    servico(sessoes, config, QUARTA_4H + timedelta(minutes=20), avisador=outro).inicializar()
    assert outro.avisos == []
```

(Nas asserções que procuram no texto um dado com `*`, `_`, `~` ou crase — por exemplo o `***` que substitui segredos —, olhe `dados.linhas`: o texto montado troca esses caracteres. QUARTA_4H é 14/10.)

- [ ] **Step 4: Testes do notificador (falham)**

Acrescente em `tests/db/test_repositorio_mensagens.py`:

```python
def test_falhas_recentes_so_as_falhas_da_janela_das_mais_novas(s):
    agora = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    antiga = repo_msg.enfileirar(s, "admin", "a", agora - timedelta(hours=3))
    nova = repo_msg.enfileirar(s, "oportunidades", "b", agora)
    pendente = repo_msg.enfileirar(s, "admin", "c", agora)
    for m, quando in ((antiga, agora - timedelta(hours=2)), (nova, agora - timedelta(minutes=5))):
        m.status, m.atualizado_em = StatusMensagem.FALHA, quando
    s.flush()
    assert repo_msg.falhas_recentes(s, agora - timedelta(hours=1)) == [nova]
    assert pendente.status is StatusMensagem.PENDENTE
```

(use os imports que o arquivo já tem; acrescente `timedelta`, `UTC`, `StatusMensagem` se faltarem.)

Acrescente em `tests/notificador/test_servico.py`:

```python
@respx.mock
def test_falha_definitiva_avisa_o_admin_e_a_falha_do_aviso_nao_gera_outro(sessoes, env, configurado):
    respx.post(ROTA).mock(return_value=httpx.Response(400, text="grupo não encontrado"))
    mid = nova(sessoes, "oportunidades", "oferta")
    relogio = Relogio(AGORA)
    svc = servico(sessoes, env, relogio)
    for _ in range(12):  # a original e o aviso falham de vez (5 recusas cada)
        svc.ciclo()
        relogio.agora += timedelta(minutes=31)
    with sessoes() as s:
        outras = list(s.scalars(select(MensagemSaida).where(MensagemSaida.id != mid)))
    [aviso] = outras
    assert aviso.destino == "admin" and aviso.status is StatusMensagem.FALHA
    assert aviso.texto.startswith("🔴 *WhatsApp · mensagem não enviada*\n")
    assert f"• #{mid} para oportunidades: HTTP 400: grupo não encontrado" in aviso.texto
```

- [ ] **Step 5: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t5 uv run pytest -q -p no:cacheprovider tests/casador tests/manutencao tests/notificador tests/db/test_repositorio_mensagens.py`
Expected: FAIL.

- [ ] **Step 6: Casador**

Em `src/tcg_sniper/casador/servico.py`, troque `from tcg_sniper.notificador.base import Destino, Notificador` por:

```python
from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.avisos.servico import Avisador
```

`__init__`: parâmetro `avisador: Avisador`, `self._avisador = avisador`; apague `self._avisos_orcamento`. Do fim do primeiro `with` em `ciclo()` até `return avaliados`:

```python
        self._avisador.resolver(TipoAviso.IA_PAUSADA, CHAVE_GERAL)  # ativo e ligado: uma pausa aberta acabou
        for anuncio_id, produto_id in ja_avaliados:
            with self._sessoes() as s, s.begin():
                av = repo_ia.avaliacoes_dos_pares(s, [(anuncio_id, produto_id)]).get((anuncio_id, produto_id))
                if av is not None and av.aplicada_em is None:
                    self._aplicar(s, av, limites, self._relogio())
        avaliados = falhas = confirmados = ignorados = 0
        chamada_ok = False
        for par, atual in pares:
            if self._parar.is_set():
                break
            chave = (par.anuncio.id, par.produto.id)
            try:
                veredito, resposta, sem_imagem = avaliar_par(
                    self._sessoes, self._transporte, self._http, par.anuncio, par.produto, par.preco_liga,
                    par.preco_amazon, finalidade="casamento", zona=zona, relogio=self._relogio,
                )
                decisao = self._gravar(par, veredito, resposta, sem_imagem, automatico, limites)
            except SemOrcamento as erro:
                self._avisar_orcamento(str(erro), zona)
                break
            except (ChaveInvalida, ConfiguracaoInvalida) as erro:
                with self._sessoes() as s, s.begin():
                    repo.pausar(s, str(erro), self._relogio(), COLETOR_CASADOR)
                self._avisador.avisar(TipoAviso.IA_PAUSADA, CHAVE_GERAL, Dados(linhas=(f"Motivo: {erro}",)))
                log.error("casador pausado: %s", erro)
                break
            except RespostaForaDoFormato as erro:  # a chamada funcionou: só o par espera
                falhas = 0
                self._marcar_falha(chave, atual)
                log.warning("resposta fora do formato no anúncio %s: %s", par.anuncio.asin, erro)
                continue
            except ErroIA as erro:  # falha da chamada: o par espera e, se repetir, a rodada acaba
                falhas += 1
                self._marcar_falha(chave, atual)
                log.warning("IA falhou no anúncio %s: %s", par.anuncio.asin, erro)
                if falhas >= FALHAS_SEGUIDAS_MAX:
                    dados = Dados(
                        linhas=(f"{FALHAS_SEGUIDAS_MAX} chamadas seguidas falharam; a rodada parou", f"Última: {erro}")
                    )
                    self._avisador.avisar(TipoAviso.IA_FALHAS_SEGUIDAS, CHAVE_GERAL, dados)
                    break
                continue
            except Exception:
                self._marcar_falha(chave, atual)
                log.exception("erro inesperado no anúncio %s; segue para o próximo", par.anuncio.asin)
                continue
            if not chamada_ok:  # a primeira chamada ok da rodada fecha falhas seguidas e falta de orçamento
                chamada_ok = True
                self._avisador.resolver(TipoAviso.IA_FALHAS_SEGUIDAS, CHAVE_GERAL)
                self._avisador.resolver_todos(TipoAviso.IA_SEM_ORCAMENTO)
            falhas = 0
            self._falhas.pop(chave, None)
            avaliados += 1
            confirmados += decisao is StatusCasamento.CONFIRMADO
            ignorados += decisao is StatusCasamento.IGNORADO
        if avaliados:
            esperando = avaliados - confirmados - ignorados
            dados = Dados(
                linhas=(
                    f"Avaliados: {avaliados}",
                    f"Confirmados pelo automático: {confirmados}",
                    f"Ignorados pelo automático: {ignorados}",
                    f"Esperando você: {esperando}",
                ),
                acao="Revise os pendentes em Admin → Casamentos." if esperando else None,
            )
            self._avisador.avisar(TipoAviso.IA_RODADA_CONCLUIDA, CHAVE_GERAL, dados)
        return avaliados
```

`_gravar` devolve a decisão:

```python
    def _gravar(self, par, veredito, resposta, sem_imagem, automatico, limites) -> StatusCasamento | None:
        agora = self._relogio()
        with self._sessoes() as s, s.begin():
            anterior = repo_ia.avaliacoes_dos_pares(s, [(par.anuncio.id, par.produto.id)]).get((par.anuncio.id, par.produto.id))
            ja_aplicada = anterior is not None and anterior.aplicada_em is not None
            av = repo_ia.gravar_avaliacao(
                s, anuncio_id=par.anuncio.id, produto_id=par.produto.id, mesmo_produto=veredito.mesmo_produto,
                confianca=veredito.confianca, motivo=veredito.motivo, modelo=resposta.modelo,
                assinatura=assinatura(par.anuncio, par.produto), sem_imagem=sem_imagem,
                chamada_id=resposta.chamada_id, agora=agora,
            )
            if automatico and not ja_aplicada:
                return self._aplicar(s, av, limites, agora)
        return None
```

`_aplicar` devolve `StatusCasamento.CONFIRMADO`, `StatusCasamento.IGNORADO` ou `None` (troque os dois `return` sem valor por `return None`, e depois de `av.aplicada_em = agora` devolva `StatusCasamento.CONFIRMADO` no ramo de confirmar e `StatusCasamento.IGNORADO` no de ignorar — guarde em uma variável `decisao` antes do `av.aplicada_em = agora`). Assinatura: `def _aplicar(s, av, limites, agora) -> StatusCasamento | None`.

`_avisar_orcamento`:

```python
    def _avisar_orcamento(self, motivo: str, zona) -> None:
        local = self._relogio().astimezone(zona)
        periodo = f"mês {local:%m/%Y}" if "mensal" in motivo else f"dia {local:%d/%m}"
        log.warning("casador sem orçamento: %s", motivo)
        dados = Dados(titulo_extra=periodo, linhas=(f"Motivo: {motivo}",))
        self._avisador.avisar(TipoAviso.IA_SEM_ORCAMENTO, periodo, dados)
```

- [ ] **Step 7: Manutenção**

Em `src/tcg_sniper/manutencao/servico.py`, troque o import do notificador por:

```python
from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.avisos.servico import Avisador
from tcg_sniper.formatacao import formatar_bytes
```

Parâmetro `avisador: Avisador` (mesma posição), `self._avisador = avisador`. Em `inicializar`:

```python
        if interrompidas:
            log.warning("%d execução(ões) da manutenção interrompida(s) no meio; o dia roda de novo", interrompidas)
            dados = Dados(
                linhas=(f"{interrompidas} execução(ões) interrompida(s) no meio: o serviço de manutenção reiniciou",)
            )
            self._avisador.avisar(TipoAviso.BACKUP_INTERROMPIDO, CHAVE_GERAL, dados)
```

No fim de `executar`, a partir de `if erro_texto is None:`:

```python
        if erro_texto is None:
            log.info("manutenção de %s concluída: %s", f"{dia:%d/%m}", status.value)
            apagadas = sum((apagados or {}).values())
            dados = Dados(
                titulo_extra=f"{dia:%d/%m}",
                linhas=(
                    f"Tamanho: {formatar_bytes(arquivos.tamanho)}",
                    f"Cópia no R2: {'sim' if enviado else 'não (só local)'}",
                    f"Linhas antigas apagadas: {apagadas:,}".replace(",", "."),
                ),
            )
            self._avisador.avisar(TipoAviso.BACKUP_CONCLUIDO, CHAVE_GERAL, dados)
            self._avisador.resolver(TipoAviso.BACKUP_ERRO, CHAVE_GERAL)
            return
        log.error("manutenção de %s com erro: %s", f"{dia:%d/%m}", erro_texto)
        local = "O backup local ficou salvo" if arquivos else "Nenhum backup novo foi gravado"
        dados = Dados(titulo_extra=f"{dia:%d/%m}", linhas=(f"Erro: {erro_texto}", local))
        self._avisador.avisar(TipoAviso.BACKUP_ERRO, CHAVE_GERAL, dados)
```

Atualize a docstring do módulo: "Falha (…): grava o erro e avisa o grupo admin (`BACKUP_ERRO`, com lembrete enquanto continuar); ok avisa `BACKUP_CONCLUIDO`."

- [ ] **Step 8: Notificador**

Em `src/tcg_sniper/db/repositorio_mensagens.py`:

```python
def falhas_recentes(s: Session, desde: datetime, limite: int = 5) -> list[MensagemSaida]:
    """Mensagens que falharam de vez a partir de `desde`, das mais novas (aviso MENSAGEM_NAO_ENVIADA)."""
    return list(
        s.scalars(
            select(MensagemSaida)
            .where(MensagemSaida.status == StatusMensagem.FALHA, MensagemSaida.atualizado_em >= desde)
            .order_by(MensagemSaida.atualizado_em.desc(), MensagemSaida.id.desc())
            .limit(limite)
        )
    )
```

Em `src/tcg_sniper/notificador/servico.py`, acrescente:

```python
from tcg_sniper.avisos import formato
from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso

JANELA_FALHAS = timedelta(hours=1)
```

No laço de `ciclo()`, a chamada vira `resultado = self._processar(s, lote[0], cfg, agora)`. `_processar` ganha `s: Session` como primeiro parâmetro e, no ramo da falha definitiva:

```python
        if resultado is Resultado.DEFINITIVO and m.tentativas >= MAX_TENTATIVAS_DEFINITIVAS:
            m.status = StatusMensagem.FALHA
            log.error("mensagem %d para %s falhou de vez: %s", m.id, m.destino, erro)
            if not formato.eh_do_tipo(m.texto, TipoAviso.MENSAGEM_NAO_ENVIADA):  # nunca em laço
                self._avisar_falha(s, agora)
            return resultado
```

E o método novo:

```python
    @staticmethod
    def _avisar_falha(s: Session, agora: datetime) -> None:
        """Lista as falhas definitivas da última hora (menos os próprios avisos) para o grupo admin."""
        s.flush()
        falhas = [
            f for f in repo_msg.falhas_recentes(s, agora - JANELA_FALHAS)
            if not formato.eh_do_tipo(f.texto, TipoAviso.MENSAGEM_NAO_ENVIADA)
        ]
        linhas = tuple(f"#{f.id} para {f.destino}: {f.ultimo_erro or 'sem detalhe'}" for f in falhas)
        avisos.avisar(s, TipoAviso.MENSAGEM_NAO_ENVIADA, CHAVE_GERAL, Dados(linhas=linhas), agora)
```

- [ ] **Step 9: `cli.py`**

Nos ramos `casador` e `manutencao`, troque `from tcg_sniper.notificador import criar_notificador` por `from tcg_sniper.avisos.servico import criar_avisador` e `criar_notificador(config, sessoes)` por `criar_avisador(sessoes)`.

- [ ] **Step 10: Rodar, suíte inteira, ruff e commit**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t5 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde (o antigo `test_4xx_vira_falha_na_quinta` continua passando: o aviso entra na fila depois e só muda as outras linhas).

```bash
git add src/tcg_sniper/casador/servico.py src/tcg_sniper/manutencao/servico.py src/tcg_sniper/notificador/servico.py src/tcg_sniper/db/repositorio_mensagens.py src/tcg_sniper/cli.py tests/casador tests/manutencao tests/notificador tests/db/test_repositorio_mensagens.py
git commit -m "feat: AI matcher, backup and notifier send catalog alerts"
```

---

### Task 6: Amazon (varredura, monitor e oportunidade)

**Files:**
- Modify: `src/tcg_sniper/coletor_amazon/busca.py` (`ContextoBusca.avisador`)
- Modify: `src/tcg_sniper/coletor_amazon/monitor.py`
- Modify: `src/tcg_sniper/coletor_amazon/varredura.py`
- Modify: `src/tcg_sniper/oportunidades/mensagens.py` (sai `mensagem_oportunidade` e o que só ela usava)
- Modify: `src/tcg_sniper/admin/app.py` (só `carrinho_conferido`)
- Modify: `src/tcg_sniper/cli.py` (ramo `coletor-amazon`)
- Delete: `tests/oportunidades/test_mensagens.py` (coberto por `test_dados_oportunidade.py`)
- Test: `tests/coletor_amazon/test_varredura.py`, `test_varredura_monitor.py`, `test_monitor.py`, `test_busca.py`, `tests/admin/test_admin_servicos.py`

**Interfaces:**
- Consumes: Task 2 (`Avisador`, `criar_avisador`, `avisos.servico.resolver(s, …)`, `fakes.AvisadorFake`); Task 3 (`dados_oportunidade`); Task 1 (`CHAVE_GERAL`, `Dados`, `TipoAviso`, `formato.formatar_duracao`).
- Produces:
  - `ContextoBusca(sessoes, navegador, avisador: Avisador, config, cfg, relogio, dormir, rng, nome_falha, cota_falhas=...)`.
  - `monitor.ResultadoMonitor(paginas: int, ofertas: int, melhor: OfertaLista | None, caiu: bool = False)`.
  - `VarreduraAmazon(engine, sessoes, fabrica_navegador, avisador: Avisador, config, relogio=None, rng=None, dormir=...)`; `VarreduraAmazon.executar_passo() -> float`.
  - `varredura.dados_captcha(url: str, asin_no_carrinho: str | None = None) -> Dados`, `varredura.dados_conferir_a_mao(asin: str, razao: str) -> Dados`, `varredura.dados_pausa(motivo: str, sem_registro: bool = False) -> Dados`, `varredura.DADOS_SEM_LOGIN: Dados` (saem `mensagem_captcha`, `mensagem_conferir_a_mao`, `mensagem_sem_login`).

- [ ] **Step 1: Banco da lane**

Run: `docker compose exec -T postgres-teste createdb -U tcg tcg_test_t6`

- [ ] **Step 2: Ajustar os testes existentes (falham)**

Em `test_varredura.py`, `test_varredura_monitor.py`, `test_monitor.py` e `test_busca.py`: troque `NotificadorFake` por `AvisadorFake`, `notificador=` por `avisador=` (inclusive no `ContextoBusca(...)` dos helpers `contexto`) e a variável `notificador` por `avisador`; acrescente `from tcg_sniper.avisos.catalogo import CHAVE_GERAL, TipoAviso`. Troque as asserções de texto pela tabela:

| Antes | Depois |
|---|---|
| `"preço conferido (sem frete)"` | `"(conferido, com impostos"` |
| `"não conferido (conferência desligada)"` | `"não conferido: conferência desligada"` |
| `"Amazon: R$ 700,00, preço anunciado"` | `"Amazon: *R$ 700,00* (anunciado, sem impostos"` |
| `"Amazon: R$ 650,00, preço conferido"` / `"Amazon: R$ 600,00, preço anunciado"` | `"Amazon: *R$ 650,00* (conferido"` / `"Amazon: *R$ 600,00* (anunciado"` |
| `"vendido por Loja X (97% de 2.340 avaliações), enviado pela Amazon"` | `"Vendido por: Loja X (97% de 2.340 avaliações) · enviado pela Amazon"` |
| `"não conferido (a conferência falhou: contador do carrinho ilegível"` | `"não conferido: a conferência falhou: contador do carrinho ilegível"` |

Onde o teste desempacota a lista inteira (`[(destino, texto)] = notificador.mensagens`), filtre pelo grupo, porque agora também saem avisos de conclusão no admin: `[(destino, texto)] = [m for m in avisador.mensagens if m[0] is Destino.OPORTUNIDADES]`.

`tests/coletor_amazon/test_varredura.py`:

```python
# test_captcha_pausa_avisa_e_mantem_o_navegador
    [(tipo, chave, dados)] = avisador.avisos
    assert (tipo, chave) == (TipoAviso.AMAZON_CAPTCHA, CHAVE_GERAL)
    assert dados.linhas[1] == "Busca, monitor e conferência pausados até você retomar"
    assert "noVNC da Amazon (porta 6081)" in avisador.mensagens[0][1]

# test_retomar_continua_no_mesmo_navegador (depois do segundo passo)
    assert (TipoAviso.AMAZON_CAPTCHA, CHAVE_GERAL) in avisador.resolvidos

# test_falha_de_layout_conta_falha_e_ciclo_falho_avisa
    assert TipoAviso.AMAZON_BUSCA_FALHOU in avisador.tipos()

# test_erros_inesperados_seguidos_pausam
    seguidos = [t for t in avisador.tipos() if t in (TipoAviso.AMAZON_ERRO, TipoAviso.AMAZON_PAUSADA)]
    assert seguidos == [TipoAviso.AMAZON_ERRO, TipoAviso.AMAZON_ERRO, TipoAviso.AMAZON_PAUSADA]

# test_inicializar_so_marca_os_ciclos_da_amazon
    assert avisador.tipos() == [TipoAviso.AMAZON_INTERROMPIDA]

# test_tratar_erro_nunca_levanta_se_a_pausa_falhar
    assert avisador.tipos() == [TipoAviso.AMAZON_ERRO, TipoAviso.AMAZON_ERRO, TipoAviso.AMAZON_PAUSADA]
    assert avisador.dados(TipoAviso.AMAZON_PAUSADA)[0].linhas[1] == (
        "Não consegui registrar a pausa no banco: nova tentativa em 15 min"
    )

# test_falhas_seguidas_pausam_a_busca
    [pausa] = avisador.dados(TipoAviso.AMAZON_PAUSADA)
    assert pausa.linhas[0] == f"Motivo: {MAX_FALHAS_SEGUIDAS} páginas seguidas com falha (bloqueio ou layout novo?)"

# test_busca_com_sucesso_zera_as_falhas_seguidas
    assert TipoAviso.AMAZON_PAUSADA not in avisador.tipos()
```

Substitua `test_host_salvo_na_tela_vale_na_mensagem_do_captcha` por:

```python
def test_mensagem_do_captcha_nunca_leva_o_host_salvo(engine, sessoes, config):
    with sessoes() as s, s.begin():
        repo.obter_config_geral(s, config)
        repo.salvar_config_geral(s, {"host_publico": "10.9.8.7"}, MEIO_DIA)
    _, urls = produtos(sessoes, "a")
    [url] = urls.values()
    v, _, _, _ = varredura(engine, sessoes, config, {url: pagina_html(CAPTCHA, url=url)})
    avisador = AvisadorFake(host_publico="10.9.8.7")  # modo estrito: o host no texto faz o avisar levantar
    v._avisador = avisador
    v.passo()
    [(_, texto)] = avisador.mensagens
    assert "porta 6081" in texto and "10.9.8.7" not in texto
```

Acrescente ao fim de `test_varredura.py`:

```python
def test_ciclo_ok_avisa_busca_concluida_e_resolve_a_falha(engine, sessoes, config):
    _, urls = produtos(sessoes, "a")
    [url] = urls.values()
    v, _, _, avisador = varredura(engine, sessoes, config, {url: vazia(url)})
    v.passo()
    [(tipo, chave, dados)] = avisador.avisos
    assert (tipo, chave) == (TipoAviso.AMAZON_BUSCA_CONCLUIDA, CHAVE_GERAL)
    assert dados.titulo_extra.startswith("ciclo ") and dados.linhas == ("Buscas: 1 ok · 0 falhas", "Duração: menos de 1 min")
    assert (TipoAviso.AMAZON_BUSCA_FALHOU, CHAVE_GERAL) in avisador.resolvidos


def test_passo_com_a_amazon_ativa_resolve_a_pausa(engine, sessoes, config):
    v, _, _, avisador = varredura(engine, sessoes, config, {})
    with sessoes() as s, s.begin():
        repo.pausar(s, "erros seguidos", MEIO_DIA, COLETOR_AMAZON)
    v.passo()
    assert (TipoAviso.AMAZON_PAUSADA, CHAVE_GERAL) not in avisador.resolvidos
    with sessoes() as s, s.begin():
        repo.retomar(s, MEIO_DIA, COLETOR_AMAZON)
    v.passo()
    assert (TipoAviso.AMAZON_PAUSADA, CHAVE_GERAL) in avisador.resolvidos


def test_executar_passo_avisa_erro_e_o_passo_ok_seguinte_resolve(engine, sessoes, config, monkeypatch):
    v, _, _, avisador = varredura(engine, sessoes, config, {})

    def quebrar():
        raise RuntimeError("navegador fechou")

    monkeypatch.setattr(v, "passo", quebrar)
    assert v.executar_passo() == ESPERA_ERRO_S
    [(tipo, _, dados)] = avisador.avisos
    assert tipo is TipoAviso.AMAZON_ERRO and dados.linhas == ("Erro: RuntimeError('navegador fechou')", "Nova tentativa em 15 min")
    monkeypatch.setattr(v, "passo", lambda: 0)
    assert v.executar_passo() == 0
    assert (TipoAviso.AMAZON_ERRO, CHAVE_GERAL) in avisador.resolvidos
```

`tests/coletor_amazon/test_varredura_monitor.py`:

```python
# test_conferencia_antes_do_monitor_antes_da_descoberta
    [(destino, texto)] = [m for m in avisador.mensagens if m[0] is Destino.OPORTUNIDADES]
    assert "(conferido, com impostos" in texto

# test_sem_login_desliga_a_conferencia_avisa_uma_vez_e_o_monitor_continua
    [sem_login] = avisador.dados(TipoAviso.AMAZON_SEM_LOGIN)
    assert sem_login.linhas == ("A conferência de checkout parou; o monitor de preço continua",)
    [texto] = [t for d, t in avisador.mensagens if "conta sem login" in t]
    assert "porta 6081" in texto and "Retomar conferência" in texto

# test_captcha_no_monitor_pausa_a_amazon
    assert TipoAviso.AMAZON_CAPTCHA in avisador.tipos()

# teste da linha 413 ("aviso só ao passar para à mão")
    assert TipoAviso.AMAZON_CARRINHO not in avisador.tipos()

# helper avisos_a_mao
def avisos_a_mao(avisador, asin="B0CAND0001"):
    return [d for tipo, chave, d in avisador.avisos if tipo is TipoAviso.AMAZON_CARRINHO and chave == asin]

# teste da linha 479
    assert navegador.cliques == [] and TipoAviso.AMAZON_CARRINHO not in avisador.tipos()

# testes das linhas 533 e 659 (CAPTCHA com item no carrinho)
    [captcha] = avisador.dados(TipoAviso.AMAZON_CAPTCHA)
    assert any("1× B0CAND0001 no carrinho" in linha for linha in captcha.linhas)

# testes das linhas 636 e 650: filtrar `Destino.OPORTUNIDADES` como na tabela acima
```

(onde o helper `avisos_a_mao` era usado com `len(...) == 1`, continua igual; se o teste conferia a frase "Confira o carrinho da Amazon: pode haver 1× …", confira `d.linhas[0] == f"Pode haver 1× {asin} de uma conferência automática no carrinho"`. No construtor direto da linha 349, `NotificadorFake()` vira `AvisadorFake()`.)

Acrescente ao fim de `test_varredura_monitor.py`:

```python
def test_rodada_do_monitor_avisa_quando_fica_em_dia(engine, sessoes, config):
    confirmado(sessoes, "a", "B0AAAA0001", "990.00", lido_em=MEIO_DIA - timedelta(minutes=20))
    confirmado(sessoes, "b", "B0BBBB0001")
    paginas = {
        url_ofertas("B0AAAA0001"): ofertas("B0AAAA0001", "R$ 950,00"),
        url_ofertas("B0BBBB0001"): ofertas("B0BBBB0001", "R$ 990,00"),
    }
    v, _, avisador, _ = varredura(engine, sessoes, config, paginas)
    assert v.passo() == 0 and v.passo() == 0
    assert TipoAviso.AMAZON_MONITOR_CONCLUIDO not in avisador.tipos()
    assert v.passo() == ESPERA_OCIOSA_S
    [dados] = avisador.dados(TipoAviso.AMAZON_MONITOR_CONCLUIDO)
    assert dados.linhas == (
        "Anúncios lidos: 2", "Preços em queda: 1", "Conferências de checkout: 0", "Duração: menos de 1 min",
    )
    assert v.passo() == ESPERA_OCIOSA_S
    assert len(avisador.dados(TipoAviso.AMAZON_MONITOR_CONCLUIDO)) == 1


def test_monitor_ocioso_nao_avisa_rodada(engine, sessoes, config):
    confirmado(sessoes, "a", "B0AAAA0001", "990.00")  # lido agora: em dia
    v, _, avisador, _ = varredura(engine, sessoes, config, {})
    for _ in range(3):
        assert v.passo() == ESPERA_OCIOSA_S
    assert avisador.avisos == []


def test_retirada_que_ve_o_carrinho_sem_o_item_resolve_o_aviso_do_carrinho(engine, sessoes, config):
    _, anuncio_id = confirmado(sessoes, "cand", "B0CAND0001")
    with sessoes() as s, s.begin():
        repo_amz.registrar_conferencia(
            s, em=MEIO_DIA - timedelta(minutes=5), anuncio_id=anuncio_id, vendedor_nome="Amazon.com.br",
            preco_anunciado=Decimal("700.00"), itens=None, frete=None, impostos=None, total=None,
            situacao=SituacaoCheckout.FALHA, motivo="em andamento", item_removido=False,
        )
    v, _, avisador, _ = varredura(engine, sessoes, config, {URL_CARRINHO: carrinho()})
    v.passo()
    assert (TipoAviso.AMAZON_CARRINHO, "B0CAND0001") in avisador.resolvidos
```

(`carrinho()`, `URL_CARRINHO`, `Decimal`, `SituacaoCheckout`, `repo_amz` já estão importados no arquivo; `carrinho()` sem argumentos é o carrinho vazio da conta logada, como em `test_item_que_ficou_no_carrinho_e_retirado_na_proxima_volta`.)

`tests/coletor_amazon/test_monitor.py` — acrescente:

```python
def test_leitura_mais_barata_que_a_anterior_conta_como_queda(sessoes, config, anuncio):
    ctx, _, _ = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 900,00"))}, checkout=False)
    assert ler_anuncio(ctx, anuncio.id, ASIN).caiu is False  # primeira leitura: nada a comparar
    ctx, _, _ = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 850,00"))}, checkout=False)
    assert ler_anuncio(ctx, anuncio.id, ASIN).caiu is True
    ctx, _, _ = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 870,00"))}, checkout=False)
    assert ler_anuncio(ctx, anuncio.id, ASIN).caiu is False


def test_oportunidade_vai_com_a_chave_do_anuncio(sessoes, config, anuncio):
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))}, checkout=False)
    ler_anuncio(ctx, anuncio.id, ASIN)
    [(tipo, chave, dados)] = avisador.avisos
    assert (tipo, chave) == (TipoAviso.OPORTUNIDADE, str(anuncio.id))
    assert dados.destaque == "Aetherdrift Commander" and dados.link_produto == f"https://www.amazon.com.br/dp/{ASIN}"
    assert dados.titulo_extra == "30% abaixo da Liga"
```

`tests/admin/test_admin_servicos.py` — acrescente:

```python
def test_ja_conferi_resolve_o_aviso_do_carrinho(cliente, sessoes):
    from datetime import UTC, datetime
    from decimal import Decimal

    from fakes import criar_anuncio, criar_produto

    from tcg_sniper.avisos import servico as avisos
    from tcg_sniper.avisos.catalogo import CATALOGO, TipoAviso
    from tcg_sniper.db import repositorio_amazon as repo_amz
    from tcg_sniper.db.models import EstadoAviso, SituacaoCheckout, StatusCasamento

    agora = datetime(2026, 10, 18, 13, 0, tzinfo=UTC)
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Caixa")
        a = criar_anuncio(s, "B0CAND0001", produto=p, status=StatusCasamento.CONFIRMADO)
        c = repo_amz.registrar_conferencia(
            s, em=agora, anuncio_id=a.id, vendedor_nome="Amazon.com.br", preco_anunciado=Decimal("700.00"),
            itens=None, frete=None, impostos=None, total=None, situacao=SituacaoCheckout.FALHA, motivo="x",
            item_removido=False,
        )
        repo_amz.marcar_conferir_a_mao(s, c.id, agora, "carrinho com outros itens")
        avisos.avisar(s, TipoAviso.AMAZON_CARRINHO, "B0CAND0001", CATALOGO[TipoAviso.AMAZON_CARRINHO].exemplo, agora)
        conferencia_id = c.id
    r = cliente.post(f"/amazon/carrinho/{conferencia_id}/conferido", follow_redirects=False)
    assert r.status_code == 303
    with sessoes() as s:
        assert s.get(EstadoAviso, ("amazon_carrinho", "B0CAND0001")).aberto is False
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t6 uv run pytest -q -p no:cacheprovider tests/coletor_amazon tests/admin/test_admin_servicos.py`
Expected: FAIL.

- [ ] **Step 4: `busca.py`**

Troque `from tcg_sniper.notificador.base import Notificador` por `from tcg_sniper.avisos.servico import Avisador` e o campo `notificador: Notificador` de `ContextoBusca` por `avisador: Avisador`.

- [ ] **Step 5: `monitor.py`**

Imports: saem `from tcg_sniper.notificador.base import Destino` e `mensagem_oportunidade`; entram:

```python
from tcg_sniper.avisos.catalogo import Dados, TipoAviso
from tcg_sniper.oportunidades.mensagens import Detalhes, dados_oportunidade
```

e `PrecoAtualAmazon` no import de `tcg_sniper.db.models`.

`ResultadoMonitor` ganha `caiu: bool = False  # a melhor oferta ficou abaixo do preço atual anterior`.

`_mensagem` vira:

```python
def _dados(linha, leitura: motor.Leitura, ref: motor.RefLiga, detalhes: Detalhes) -> Dados:
    return dados_oportunidade(
        nome_produto=linha.produto.nome, variacao=linha.anuncio.variacao, leitura=leitura, ref=ref,
        url_amazon=linha.anuncio.url, detalhes=detalhes,
    )
```

Em `_decidir` e `aplicar_conferencia`: a variável `mensagem = None` vira `aviso: Dados | None = None`; `mensagem = _mensagem(ctx, linha, leitura, ref, detalhes)` vira `aviso = _dados(linha, leitura, ref, detalhes)`; e o fim de cada função:

```python
    if aviso is not None:
        ctx.avisador.avisar(TipoAviso.OPORTUNIDADE, str(anuncio_id), aviso)
```

Em `ler_anuncio`, dentro do `with` que grava, antes de `repo.gravar_ofertas`:

```python
        anterior = s.get(PrecoAtualAmazon, anuncio_id)
        preco_anterior = anterior.preco if anterior is not None else None
```

e o `return`:

```python
    novo = melhor.oferta.preco if melhor else None
    caiu = preco_anterior is not None and novo is not None and novo < preco_anterior
    return ResultadoMonitor(paginas, len(ofertas), melhor.oferta if melhor else None, caiu)
```

- [ ] **Step 6: `mensagens.py`**

Apague `_preco`, `_quem_vende` e `mensagem_oportunidade` (ficam `PAISES_CURTOS`, `Detalhes`, `_selos`, `_pct` e o que a Task 3 acrescentou); apague `tests/oportunidades/test_mensagens.py` (`git rm`).

- [ ] **Step 7: `varredura.py`**

Imports: sai `from tcg_sniper.notificador.base import Destino, Notificador`; entram:

```python
from dataclasses import dataclass
from urllib.parse import urlsplit

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.avisos.formato import formatar_duracao
from tcg_sniper.avisos.servico import Avisador
```

Troque `mensagem_captcha`, `mensagem_conferir_a_mao` e `mensagem_sem_login` por:

```python
def _pagina(url: str) -> str:
    partes = urlsplit(url)
    return (partes.path or "/") + (f"?{partes.query}" if partes.query else "")


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def dados_captcha(url: str, asin_no_carrinho: str | None = None) -> Dados:
    linhas = [f"Página: {_pagina(url)}", "Busca, monitor e conferência pausados até você retomar"]
    if asin_no_carrinho is not None:
        minutos = int(RETIRADA_AUTOMATICA_MAX.total_seconds() // 60)
        linhas.append(
            f"Uma conferência deixou 1× {asin_no_carrinho} no carrinho: sai sozinho se você retomar em até "
            f"{minutos} min; senão confira à mão"
        )
    return Dados(linhas=tuple(linhas))


def dados_conferir_a_mao(asin: str, razao: str) -> Dados:
    return Dados(
        titulo_extra=asin,
        linhas=(f"Pode haver 1× {asin} de uma conferência automática no carrinho", f"Motivo: {razao}"),
    )


def dados_pausa(motivo: str, sem_registro: bool = False) -> Dados:
    if sem_registro:  # o banco recusou a pausa: a Amazon segue e tenta de novo
        return Dados(linhas=(f"Motivo: {motivo}", "Não consegui registrar a pausa no banco: nova tentativa em 15 min"))
    return Dados(
        linhas=(f"Motivo: {motivo}", "Com a Amazon pausada, a retirada automática de item do carrinho também para")
    )


DADOS_SEM_LOGIN = Dados(linhas=("A conferência de checkout parou; o monitor de preço continua",))


@dataclass
class _Rodada:
    """Uma rodada do monitor: do primeiro anúncio lido até o monitor ficar sem nada vencido."""

    inicio: datetime
    lidos: int = 0
    quedas: int = 0
    conferencias: int = 0
```

`__init__`: parâmetro `avisador: Avisador` (4ª posição), `self._avisador = avisador`, e acrescente `self._ciclo_inicio: datetime | None = None` e `self._rodada: _Rodada | None = None`. Em `_contexto`, `avisador=self._avisador`.

Métodos novos:

```python
    def _rodada_atual(self) -> _Rodada:
        if self._rodada is None:
            self._rodada = _Rodada(self._relogio())
        return self._rodada

    def _fechar_rodada(self) -> None:
        rodada, self._rodada = self._rodada, None
        if rodada is None or rodada.lidos == 0:
            return
        dados = Dados(
            linhas=(
                f"Anúncios lidos: {rodada.lidos}",
                f"Preços em queda: {rodada.quedas}",
                f"Conferências de checkout: {rodada.conferencias}",
                f"Duração: {formatar_duracao(self._relogio() - rodada.inicio)}",
            )
        )
        self._avisador.avisar(TipoAviso.AMAZON_MONITOR_CONCLUIDO, CHAVE_GERAL, dados)

    def _pagina_ok(self) -> None:
        """Uma página abriu sem CAPTCHA: um CAPTCHA aberto está resolvido."""
        self._avisador.resolver(TipoAviso.AMAZON_CAPTCHA, CHAVE_GERAL)

    def executar_passo(self) -> float:
        """Um passo protegido: erro inesperado vira aviso/espera; passo ok fecha o erro aberto."""
        try:
            espera = self.passo()
        except Exception as erro:  # noqa: BLE001 - qualquer falha inesperada vira espera/pausa
            return self.tratar_erro(erro)
        self._avisador.resolver(TipoAviso.AMAZON_ERRO, CHAVE_GERAL)
        return espera
```

Mudanças nos métodos existentes:

- `_iniciar_ciclo`: acrescente `self._ciclo_inicio = agora`.
- `_encerrar_ciclo`: troque o bloco `if status is StatusColeta.FALHA: self._notificador.enviar(...)` por:

```python
        if self._ok + self._falha:
            inicio = self._ciclo_inicio or self._relogio()
            dados = Dados(
                titulo_extra=f"ciclo {self._ciclo}",
                linhas=(
                    f"Buscas: {self._ok} ok · {_plural(self._falha, 'falha', 'falhas')}",
                    f"Duração: {formatar_duracao(self._relogio() - inicio)}",
                ),
            )
            if status is StatusColeta.FALHA:
                self._avisador.avisar(TipoAviso.AMAZON_BUSCA_FALHOU, CHAVE_GERAL, dados)
            else:
                tipo = TipoAviso.AMAZON_BUSCA_CONCLUIDA if status is StatusColeta.OK else TipoAviso.AMAZON_BUSCA_PARCIAL
                self._avisador.avisar(tipo, CHAVE_GERAL, dados)
                self._avisador.resolver(TipoAviso.AMAZON_BUSCA_FALHOU, CHAVE_GERAL)
```

- `_registrar_desafio`: a última linha vira `self._avisador.avisar(TipoAviso.AMAZON_CAPTCHA, CHAVE_GERAL, dados_captcha(url, asin_no_carrinho))`.
- `inicializar`: o aviso vira `self._avisador.avisar(TipoAviso.AMAZON_INTERROMPIDA, CHAVE_GERAL, Dados(linhas=(f"{interrompidos} ciclo(s) marcado(s) como falha: o coletor reiniciou",)))`.
- `passo`: logo depois do `with` que lê `cfg` e `estado`, acrescente:

```python
        if estado is EstadoColetorTipo.ATIVO:
            self._avisador.resolver(TipoAviso.AMAZON_PAUSADA, CHAVE_GERAL)  # retomada: a pausa acabou
```

- `_passo_monitor`: no fim, antes do `return None`, chame `self._fechar_rodada()`.
- `_conferir_a_mao`: `if novo: self._avisador.avisar(TipoAviso.AMAZON_CARRINHO, item.asin, dados_conferir_a_mao(item.asin, razao))`.
- `_retirar`: depois de cada um dos dois `with … repo_amz.marcar_asin_removido(s, item.asin)`, acrescente `self._avisador.resolver(TipoAviso.AMAZON_CARRINHO, item.asin)` (antes do `return 0`).
- `_conferir`: primeira linha `self._rodada_atual().conferencias += 1`; o aviso de login vira:

```python
        if avisar_sem_login:
            self._avisador.avisar(TipoAviso.AMAZON_SEM_LOGIN, CHAVE_GERAL, DADOS_SEM_LOGIN)
        elif resultado.situacao is not SituacaoCheckout.SEM_LOGIN:
            self._avisador.resolver(TipoAviso.AMAZON_SEM_LOGIN, CHAVE_GERAL)
```

  e, no fim, `if resultado.desafio_url is not None: …` fica igual; antes do último `return 0` chame `self._pagina_ok()`.
- `_monitorar`: depois de `self._erros_seguidos = 0`, acrescente:

```python
        rodada = self._rodada_atual()
        rodada.lidos += 1
        rodada.quedas += resultado.caiu
        self._pagina_ok()
```

- `_passo_descoberta`: no `try`, depois de `self._falhas_seguidas = 0`, chame `self._pagina_ok()`.
- `_pausar_por_falhas`:

```python
        motivo = f"{MAX_FALHAS_SEGUIDAS} páginas seguidas com falha (bloqueio ou layout novo?)"
        try:
            with self._sessoes() as s, s.begin():
                repo.pausar(s, "falhas seguidas", self._relogio(), COLETOR_AMAZON)
        except Exception:
            log.exception("não foi possível registrar a pausa da busca na Amazon")
            self._avisador.avisar(TipoAviso.AMAZON_PAUSADA, CHAVE_GERAL, dados_pausa(motivo, sem_registro=True))
            return ESPERA_ERRO_S
        log.warning("%d páginas seguidas da Amazon falharam; varredura pausada", MAX_FALHAS_SEGUIDAS)
        self._encerrar_ciclo(cfg)
        self._avisador.avisar(TipoAviso.AMAZON_PAUSADA, CHAVE_GERAL, dados_pausa(motivo))
        return ESPERA_OCIOSA_S
```

  (a variável `pasta` sai).
- `tratar_erro`:

```python
    def tratar_erro(self, erro: Exception) -> float:
        """Erro inesperado num passo: avisa e espera; três seguidos pausam a varredura."""
        log.error("erro inesperado na varredura da Amazon", exc_info=erro)
        self.fechar_navegador()
        self._erros_seguidos += 1
        if self._erros_seguidos >= MAX_ERROS_SEGUIDOS:
            self._erros_seguidos = 0
            motivo = f"{MAX_ERROS_SEGUIDOS} erros inesperados seguidos (último: {erro!r})"
            try:
                with self._sessoes() as s, s.begin():
                    repo.pausar(s, "erros seguidos", self._relogio(), COLETOR_AMAZON)
            except Exception:
                log.exception("não foi possível registrar a pausa da varredura da Amazon")
                self._avisador.avisar(TipoAviso.AMAZON_PAUSADA, CHAVE_GERAL, dados_pausa(motivo, sem_registro=True))
                return ESPERA_ERRO_S
            self._avisador.avisar(TipoAviso.AMAZON_PAUSADA, CHAVE_GERAL, dados_pausa(motivo))
            return ESPERA_OCIOSA_S
        dados = Dados(linhas=(f"Erro: {erro!r}", "Nova tentativa em 15 min"))
        self._avisador.avisar(TipoAviso.AMAZON_ERRO, CHAVE_GERAL, dados)
        return ESPERA_ERRO_S
```

- `rodar`: o corpo do laço vira `espera = self.executar_passo()` (sai o `try/except` dali).
- Atualize a docstring do módulo: "o grupo admin recebe um aviso (`AMAZON_CARRINHO`, um por ASIN, com lembrete)…".

- [ ] **Step 8: Admin e CLI**

Em `src/tcg_sniper/admin/app.py`, acrescente `from tcg_sniper.avisos import servico as avisos` e `from tcg_sniper.avisos.catalogo import TipoAviso`, e `ConferenciaCheckout` ao import de `tcg_sniper.db.models`. `carrinho_conferido`:

```python
    @app.post("/amazon/carrinho/{conferencia_id}/conferido")
    def carrinho_conferido(conferencia_id: int):
        """"Já conferi": o usuário viu o carrinho pelo noVNC; a conferência sai do "conferir à mão" e o
        aviso do carrinho daquele ASIN fecha."""
        agora = repo.agora_utc()
        with sessoes() as s, s.begin():
            conferencia = s.get(ConferenciaCheckout, conferencia_id)
            anuncio = s.get(AnuncioAmazon, conferencia.anuncio_id) if conferencia is not None else None
            resolvida = repo_amz.marcar_item_removido(s, conferencia_id)
            if resolvida and anuncio is not None:
                avisos.resolver(s, TipoAviso.AMAZON_CARRINHO, anuncio.asin, agora)
        if not resolvida:  # inexistente ou fora do "conferir à mão": não marca nada
            raise HTTPException(status.HTTP_404_NOT_FOUND, "conferência não está aguardando conferência à mão")
        return RedirectResponse("/servicos?msg=carrinho_conferido", status_code=status.HTTP_303_SEE_OTHER)
```

Em `src/tcg_sniper/cli.py`, ramo `coletor-amazon`: `from tcg_sniper.avisos.servico import criar_avisador` e `criar_avisador(sessoes)` no lugar de `criar_notificador(config, sessoes)`. Em `tests/test_cli.py`, o `VarreduraFalsa.__init__` pode renomear o parâmetro `notificador` para `avisador` (é posicional; opcional).

- [ ] **Step 9: Rodar, suíte inteira, ruff e commit**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t6 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde. Confirme que `grep -rn "host_publico\|:8000\|:6081" src/tcg_sniper/coletor_amazon src/tcg_sniper/oportunidades` não acha nada.

```bash
git add src/tcg_sniper/coletor_amazon src/tcg_sniper/oportunidades src/tcg_sniper/admin/app.py src/tcg_sniper/cli.py tests/coletor_amazon tests/admin/test_admin_servicos.py tests/test_cli.py
git rm tests/oportunidades/test_mensagens.py
git commit -m "feat: Amazon collector and price monitor send catalog alerts"
```

---

### Task 7: Vigia de serviços

**Files:**
- Create: `src/tcg_sniper/avisos/vigia.py`
- Modify: `src/tcg_sniper/manutencao/servico.py` (`__init__`, `tick`)
- Modify: `src/tcg_sniper/cli.py` (batida nos ramos `coletor-liga`, `coletor-amazon` e `casador`)
- Test: `tests/avisos/test_vigia.py` (novo), `tests/manutencao/test_servico.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 2 (`models.SinalServico`, `avisos.servico.avisar/resolver/zona_e_host`); Task 1 (`Dados`, `TipoAviso`, `formatar_duracao`); `models.EstadoNotificador`, `COLETOR_*`, `repositorio.obter_estado`.
- Produces:
  - `vigia.SERVICOS: dict[str, str]` (`{COLETOR_LIGA: "coletor-liga", COLETOR_AMAZON: "coletor-amazon", COLETOR_CASADOR: "casador", COLETOR_NOTIFICADOR: "notificador"}`); `vigia.LIMITE_SEM_SINAL = timedelta(minutes=10)`; `vigia.INTERVALO_BATIMENTO_S = 60`.
  - `vigia.registrar_sinal(s, servico: str, agora: datetime) -> None`; `vigia.ultimo_sinal(s, servico: str) -> datetime | None`; `vigia.verificar(s, agora: datetime, desde: datetime) -> None`.
  - `vigia.Batimento(sessoes, servico: str, relogio=None, intervalo_s: float = INTERVALO_BATIMENTO_S)`: `.bater() -> None`, `.iniciar() -> threading.Thread`, `.parar() -> None`.

- [ ] **Step 1: Banco da lane**

Run: `docker compose exec -T postgres-teste createdb -U tcg tcg_test_t7`

- [ ] **Step 2: Testes (falham)**

Crie `tests/avisos/test_vigia.py`:

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos import vigia
from tcg_sniper.avisos.catalogo import TipoAviso
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import COLETOR_AMAZON, COLETOR_CASADOR, COLETOR_LIGA, EstadoColetorTipo, MensagemSaida

AGORA = datetime(2026, 10, 18, 13, 0, tzinfo=UTC)  # 10:00 em São Paulo
INICIO = AGORA - timedelta(hours=1)


def todos_vivos(sessoes, quando, menos=()):
    with sessoes() as s, s.begin():
        for servico in (COLETOR_LIGA, COLETOR_AMAZON, COLETOR_CASADOR):
            if servico not in menos:
                vigia.registrar_sinal(s, servico, quando)
        repo_msg.registrar_ciclo(s, quando)


def verificar(sessoes, agora, desde=INICIO):
    with sessoes() as s, s.begin():
        vigia.verificar(s, agora, desde)


def abertos(sessoes):
    with sessoes() as s:
        return avisos.abertos(s, TipoAviso.SERVICO_SEM_SINAL)


def textos(sessoes):
    with sessoes() as s:
        return [m.texto for m in s.scalars(select(MensagemSaida).order_by(MensagemSaida.id))]


def test_servico_mudo_mais_de_10_min_abre(sessoes):
    todos_vivos(sessoes, AGORA, menos=(COLETOR_AMAZON,))
    with sessoes() as s, s.begin():
        vigia.registrar_sinal(s, COLETOR_AMAZON, AGORA - timedelta(minutes=11))
    verificar(sessoes, AGORA)
    assert abertos(sessoes) == ["coletor-amazon"]
    [texto] = textos(sessoes)
    assert texto.startswith("🔴 *Serviço sem sinal · coletor-amazon*\n• Último sinal: 18/10 09:49 (há 11 min)\n")


def test_dez_minutos_exatos_ainda_nao_abre(sessoes):
    todos_vivos(sessoes, AGORA - timedelta(minutes=10))
    verificar(sessoes, AGORA)
    assert abertos(sessoes) == []


def test_sinal_que_volta_resolve(sessoes):
    todos_vivos(sessoes, AGORA, menos=(COLETOR_AMAZON,))
    verificar(sessoes, AGORA)  # amazon nunca bateu e a vigia começou há 1 h
    todos_vivos(sessoes, AGORA + timedelta(minutes=1))
    verificar(sessoes, AGORA + timedelta(minutes=1))
    assert abertos(sessoes) == []
    assert textos(sessoes)[-1].startswith("✅ *Serviço sem sinal · coletor-amazon resolvido · 1 vez em 1 min*")


def test_pausado_e_ignorado(sessoes):
    todos_vivos(sessoes, AGORA, menos=(COLETOR_CASADOR,))
    with sessoes() as s, s.begin():
        repo.pausar(s, "pausado no admin", AGORA, COLETOR_CASADOR)
    verificar(sessoes, AGORA)
    assert abertos(sessoes) == []


def test_pausado_por_desafio_continua_vigiado(sessoes):
    todos_vivos(sessoes, AGORA, menos=(COLETOR_LIGA,))
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio", AGORA)
        assert repo.obter_estado(s, AGORA).estado is EstadoColetorTipo.PAUSADO_DESAFIO
    verificar(sessoes, AGORA)
    assert abertos(sessoes) == ["coletor-liga"]


def test_notificador_usa_o_ultimo_ciclo_dele(sessoes):
    todos_vivos(sessoes, AGORA)
    with sessoes() as s, s.begin():
        repo_msg.registrar_ciclo(s, AGORA - timedelta(minutes=30))
    verificar(sessoes, AGORA)
    assert abertos(sessoes) == ["notificador"]


def test_servico_que_nunca_deu_sinal_conta_desde_o_inicio_da_vigia(sessoes):
    todos_vivos(sessoes, AGORA, menos=(COLETOR_CASADOR,))
    verificar(sessoes, AGORA, desde=AGORA - timedelta(minutes=5))
    assert abertos(sessoes) == []
    todos_vivos(sessoes, AGORA + timedelta(minutes=6), menos=(COLETOR_CASADOR,))
    verificar(sessoes, AGORA + timedelta(minutes=6), desde=AGORA - timedelta(minutes=5))
    assert abertos(sessoes) == ["casador"]
    assert "• Último sinal: nenhum desde que a vigia começou\n" in textos(sessoes)[0]


def test_batimento_registra_o_sinal(sessoes):
    vigia.Batimento(sessoes, COLETOR_LIGA, relogio=lambda: AGORA).bater()
    with sessoes() as s:
        assert vigia.ultimo_sinal(s, COLETOR_LIGA) == AGORA


def test_batimento_com_banco_fora_nao_levanta(caplog):
    def sessoes():
        raise RuntimeError("banco fora")

    vigia.Batimento(sessoes, COLETOR_LIGA, relogio=lambda: AGORA).bater()
    assert "sinal de vida de liga" in caplog.text


def test_batimento_em_thread_bate_e_para(sessoes):
    batidas = []
    b = vigia.Batimento(sessoes, COLETOR_LIGA, relogio=lambda: AGORA, intervalo_s=0.01)
    b.bater = lambda: batidas.append(1)
    t = b.iniciar()
    while not batidas:
        pass
    b.parar()
    t.join(timeout=2)
    assert not t.is_alive() and t.daemon
```

Acrescente em `tests/manutencao/test_servico.py`:

```python
def test_tick_roda_a_vigia_mesmo_com_o_backup_desligado(sessoes, config):
    from tcg_sniper.avisos import servico as avisos
    from tcg_sniper.avisos.catalogo import TipoAviso

    relogio = Relogio(QUARTA_4H - timedelta(hours=3))
    srv = ServicoManutencao(
        sessoes, config, AvisadorFake(), None, ExecutorFake(), relogio=relogio, dormir=lambda _: None
    )
    with sessoes() as s, s.begin():
        repo.pausar(s, "pausado no admin", relogio.agora, COLETOR_MANUTENCAO)
    relogio.agora += timedelta(minutes=11)
    srv.tick()
    with sessoes() as s:
        assert "casador" in avisos.abertos(s, TipoAviso.SERVICO_SEM_SINAL)
```

Em `tests/test_cli.py`, acrescente no topo:

```python
@pytest.fixture(autouse=True)
def batidas(monkeypatch):
    """Nenhum teste do CLI sobe a thread de verdade; guarda quais serviços iniciaram a batida."""
    from tcg_sniper.avisos import vigia

    iniciadas = []
    monkeypatch.setattr(vigia.Batimento, "iniciar", lambda self: iniciadas.append(self._servico))
    return iniciadas
```

e, em `test_coletor_liga_instala_sigterm_antes_de_rodar` e `test_coletor_amazon_instala_sigterm_e_usa_o_perfil_da_amazon`, receba o fixture `batidas` e acrescente `assert batidas == ["liga"]` / `assert batidas == ["amazon"]` no fim; no teste do casador com chave (`test_casador_so_cria_transporte_com_chave`), `assert batidas == ["casador"]`.

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t7 uv run pytest -q -p no:cacheprovider tests/avisos/test_vigia.py tests/manutencao tests/test_cli.py`
Expected: FAIL com `ImportError: cannot import name 'vigia'`.

- [ ] **Step 4: Implementar o vigia**

Crie `src/tcg_sniper/avisos/vigia.py`:

```python
"""Vigia de serviços: a batida de vida dos coletores e do casador (`sinal_servico`) e a verificação, feita
pelo serviço `manutencao` a cada minuto, que abre `SERVICO_SEM_SINAL` para serviço ativo mudo há mais de
10 min e resolve quando o sinal volta. O notificador já registra o próprio ciclo (`estado_notificador`).
Serviço pausado (manual ou por erros seguidos) é ignorado; pausado por desafio continua vigiado."""

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import Dados, TipoAviso
from tcg_sniper.avisos.formato import formatar_duracao
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    COLETOR_CASADOR,
    COLETOR_LIGA,
    COLETOR_NOTIFICADOR,
    EstadoColetorTipo,
    EstadoNotificador,
    SinalServico,
)

log = logging.getLogger(__name__)

SERVICOS = {
    COLETOR_LIGA: "coletor-liga",
    COLETOR_AMAZON: "coletor-amazon",
    COLETOR_CASADOR: "casador",
    COLETOR_NOTIFICADOR: "notificador",
}
LIMITE_SEM_SINAL = timedelta(minutes=10)
INTERVALO_BATIMENTO_S = 60


def registrar_sinal(s: Session, servico: str, agora: datetime) -> None:
    s.execute(
        pg_insert(SinalServico)
        .values(servico=servico, ultimo_em=agora)
        .on_conflict_do_update(index_elements=[SinalServico.servico], set_={"ultimo_em": agora})
    )
    s.flush()


def ultimo_sinal(s: Session, servico: str) -> datetime | None:
    if servico == COLETOR_NOTIFICADOR:
        return s.scalar(select(EstadoNotificador.ultimo_ciclo_em).where(EstadoNotificador.id == 1))
    return s.scalar(select(SinalServico.ultimo_em).where(SinalServico.servico == servico))


def _dados(nome: str, ultimo: datetime | None, agora: datetime, zona) -> Dados:
    if ultimo is None:
        quando = "nenhum desde que a vigia começou"
    else:
        quando = f"{ultimo.astimezone(zona):%d/%m %H:%M} (há {formatar_duracao(agora - ultimo)})"
    return Dados(titulo_extra=nome, linhas=(f"Último sinal: {quando}",))


def verificar(s: Session, agora: datetime, desde: datetime) -> None:
    """`desde`: quando a vigia começou (serviço sem sinal nenhum conta a partir daí). Nunca lança exceção."""
    try:
        with s.begin_nested():
            situacoes = [
                (nome, ultimo_sinal(s, coletor), repo.obter_estado(s, agora, coletor).estado)
                for coletor, nome in SERVICOS.items()
            ]
            zona, _ = avisos.zona_e_host(s)
    except Exception:
        log.exception("vigia: não consegui ler o sinal dos serviços")
        return
    for nome, ultimo, estado in situacoes:
        if estado is EstadoColetorTipo.PAUSADO:
            continue
        if agora - (ultimo or desde) > LIMITE_SEM_SINAL:
            avisos.avisar(s, TipoAviso.SERVICO_SEM_SINAL, nome, _dados(nome, ultimo, agora, zona), agora)
        else:
            avisos.resolver(s, TipoAviso.SERVICO_SEM_SINAL, nome, agora)


class Batimento:
    """Thread que registra o sinal de vida do serviço a cada `intervalo_s` enquanto o processo vive."""

    def __init__(
        self,
        sessoes: sessionmaker[Session],
        servico: str,
        relogio: Callable[[], datetime] | None = None,
        intervalo_s: float = INTERVALO_BATIMENTO_S,
    ):
        self._sessoes = sessoes
        self._servico = servico
        self._relogio = relogio or repo.agora_utc
        self._intervalo_s = intervalo_s
        self._parar = threading.Event()

    def bater(self) -> None:
        try:
            with self._sessoes() as s, s.begin():
                registrar_sinal(s, self._servico, self._relogio())
        except Exception:
            log.warning("não consegui registrar o sinal de vida de %s", self._servico, exc_info=True)

    def _laco(self) -> None:
        while True:
            self.bater()
            if self._parar.wait(self._intervalo_s):
                return

    def iniciar(self) -> threading.Thread:
        thread = threading.Thread(target=self._laco, name=f"batimento-{self._servico}", daemon=True)
        thread.start()
        return thread

    def parar(self) -> None:
        self._parar.set()
```

- [ ] **Step 5: Manutenção e CLI**

Em `src/tcg_sniper/manutencao/servico.py`: `from tcg_sniper.avisos import vigia`; no fim do `__init__`, `self._vigia_desde = self._relogio()`; em `tick`, logo depois de `repo_man.registrar_ciclo(s, agora)`:

```python
            vigia.verificar(s, agora, self._vigia_desde)  # roda também com o backup desligado
```

Atualize a docstring do módulo com uma linha: "- A cada passo, o vigia confere o sinal de vida dos outros serviços (`avisos/vigia.py`)."

Em `src/tcg_sniper/cli.py`, nos ramos `coletor-liga`, `coletor-amazon` e `casador`, logo antes de construir o serviço:

```python
        from tcg_sniper.avisos.vigia import Batimento
        from tcg_sniper.db.models import COLETOR_LIGA  # COLETOR_AMAZON / COLETOR_CASADOR no ramo respectivo

        Batimento(sessoes, COLETOR_LIGA).iniciar()
```

(no `casador`, depois de `signal.signal(...)` não importa: só antes de `casador.rodar()`.)

- [ ] **Step 6: Rodar, suíte inteira, ruff e commit**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t7 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde.

```bash
git add src/tcg_sniper/avisos/vigia.py src/tcg_sniper/manutencao/servico.py src/tcg_sniper/cli.py tests/avisos/test_vigia.py tests/manutencao/test_servico.py tests/test_cli.py
git commit -m "feat: service watchdog alerts when a service stops reporting"
```

---

### Task 8: Admin — aba Avisos e pausar/retomar

**Files:**
- Modify: `src/tcg_sniper/admin/app.py`
- Modify: `src/tcg_sniper/admin/templates/configuracoes.html`
- Modify: `src/tcg_sniper/admin/formularios_config.py` (explicação do host)
- Modify: `src/tcg_sniper/admin/static/admin.css` (regenerado)
- Modify: `scripts/verificar_layout.py`
- Test: `tests/admin/test_admin_avisos.py` (novo)

**Interfaces:**
- Consumes: Task 1 (`CATALOGO`, `EMOJI`, `Dados`, `TipoAviso`, `formato.aviso_de`, `formato.formatar`); Task 2 (`avisos.servico.ligados`, `definir_ligado`, `avisar(s, …)`).
- Produces: rota `POST /configuracoes/avisos` (campos `tipo`, `ligado` = `"1"`/`"0"`; 303 para `/configuracoes?msg=avisos`; 400 com tipo desconhecido); `app.NOMES_SERVICOS: dict[str, str]`; aba "Avisos" em Configurações.

- [ ] **Step 1: Banco da lane**

Run: `docker compose exec -T postgres-teste createdb -U tcg tcg_test_t8`

- [ ] **Step 2: Testes (falham)**

Crie `tests/admin/test_admin_avisos.py`:

```python
import base64
import html

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tcg_sniper.admin.app import criar_app
from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import CATALOGO, TipoAviso
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import COLETOR_LIGA, MensagemSaida


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def textos(sessoes):
    with sessoes() as s:
        return [m.texto for m in s.scalars(select(MensagemSaida).order_by(MensagemSaida.id))]


def test_aba_avisos_lista_todos_os_tipos_com_exemplo_e_toggle(cliente):
    texto = cliente.get("/configuracoes").text
    assert 'aria-label="Avisos"' in texto
    for definicao in CATALOGO.values():
        assert html.escape(definicao.titulo) in texto
    assert texto.count('action="/configuracoes/avisos"') == len(TipoAviso)
    assert texto.count('class="toggle toggle-success"') == len(TipoAviso)
    assert "💰 *Oportunidade · 18% abaixo da Liga*" in texto
    assert "https://www.amazon.com.br/dp/B0TESTE123" in texto


def test_desligar_e_religar_um_tipo(cliente, sessoes):
    r = cliente.post(
        "/configuracoes/avisos", data={"tipo": "amazon_monitor_concluido", "ligado": "0"}, follow_redirects=False
    )
    assert r.status_code == 303 and r.headers["location"] == "/configuracoes?msg=avisos"
    with sessoes() as s:
        assert avisos.ligados(s)[TipoAviso.AMAZON_MONITOR_CONCLUIDO] is False
    pagina = cliente.get(r.headers["location"]).text
    assert "Salvo; vale a partir do próximo aviso." in pagina
    assert 'aria-label="Avisos" checked' in pagina
    cliente.post("/configuracoes/avisos", data={"tipo": "amazon_monitor_concluido", "ligado": "1"})
    with sessoes() as s:
        assert avisos.ligados(s)[TipoAviso.AMAZON_MONITOR_CONCLUIDO] is True


def test_tipo_desconhecido_e_400(cliente):
    r = cliente.post("/configuracoes/avisos", data={"tipo": "nao_existe", "ligado": "0"})
    assert r.status_code == 400


def test_pausar_e_retomar_no_admin_avisam(cliente, sessoes):
    cliente.post("/casador/pausar")
    cliente.post("/casador/retomar")
    pausado, retomado = textos(sessoes)
    assert pausado.startswith("🟡 *Serviço mudou no admin · Casador (IA)*\n• Novo estado: pausado\n")
    assert retomado.startswith("🟡 *Serviço mudou no admin · Casador (IA)*\n• Novo estado: ativo\n")


@pytest.mark.parametrize(
    ("rota", "nome"),
    [
        ("/liga/pausar", "LigaMagic"),
        ("/amazon/pausar", "Amazon"),
        ("/notificador/pausar", "WhatsApp (notificador)"),
        ("/manutencao/pausar", "Backup (manutenção)"),
    ],
)
def test_cada_pausa_diz_o_servico(cliente, sessoes, rota, nome):
    cliente.post(rota)
    [texto] = textos(sessoes)
    assert texto.startswith(f"🟡 *Serviço mudou no admin · {nome}*")


def test_desligar_com_desafio_pendente_nao_avisa(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio", repo.agora_utc(), COLETOR_LIGA)
    cliente.post("/liga/pausar")
    assert textos(sessoes) == []


def test_explicacao_do_host_nao_fala_mais_em_mensagens(cliente):
    texto = cliente.get("/configuracoes").text
    assert "As mensagens do WhatsApp nunca levam este endereço." in texto
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t8 uv run pytest -q -p no:cacheprovider tests/admin/test_admin_avisos.py`
Expected: FAIL.

- [ ] **Step 4: Rotas e dados da aba**

Em `src/tcg_sniper/admin/app.py`, acrescente aos imports (se a Task 6 ainda não acrescentou):

```python
from tcg_sniper.avisos import formato
from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import CATALOGO, EMOJI, Dados, TipoAviso
from tcg_sniper.notificador.base import Destino
```

Constantes de módulo (perto de `MENSAGENS_SERVICOS`):

```python
NOMES_SERVICOS = {
    COLETOR_LIGA: "LigaMagic",
    COLETOR_AMAZON: "Amazon",
    COLETOR_CASADOR: "Casador (IA)",
    COLETOR_NOTIFICADOR: "WhatsApp (notificador)",
    COLETOR_MANUTENCAO: "Backup (manutenção)",
}
MENSAGEM_AVISOS = "Salvo; vale a partir do próximo aviso."
```

Dentro de `criar_app`, um helper e as rotas de Serviços avisando:

```python
    def _avisar_mudanca(s: Session, coletor: str, novo: str, agora: datetime) -> None:
        dados = Dados(titulo_extra=NOMES_SERVICOS[coletor], linhas=(f"Novo estado: {novo}",))
        avisos.avisar(s, TipoAviso.SERVICO_PAUSADO_MANUAL, coletor, dados, agora)
```

- `retomar` (`/retomar`): dentro do `with`, depois de `repo.retomar(...)`, `_avisar_mudanca(s, COLETOR_LIGA, "ativo", agora)` (crie `agora = repo.agora_utc()` antes e use nos dois).
- `_desligar`: no `else`, depois de `repo.pausar(...)`, `_avisar_mudanca(s, coletor, "pausado", agora)`.
- `retomar_liga`, `retomar_notificador`, `retomar_manutencao`, `retomar_amazon`, `retomar_casador`: dentro do `with`, depois de `repo.retomar(...)`, `_avisar_mudanca(s, <COLETOR_…>, "ativo", agora)`.
- `pausar_amazon`, `pausar_casador`: dentro do `with`, depois de `repo.pausar(...)`, `_avisar_mudanca(s, <COLETOR_…>, "pausado", agora)`.

A aba:

```python
    def _avisos_da_tela(request: Request) -> list[dict]:
        zona = request.state.config.zona
        agora = repo.agora_utc()
        with sessoes() as s:
            estados = avisos.ligados(s)
        return [
            {
                "tipo": tipo.value,
                "titulo": d.titulo,
                "emoji": EMOJI[d.severidade],
                "severidade": d.severidade.value,
                "grupo": "oportunidades" if d.grupo is Destino.OPORTUNIDADES else "admin",
                "descricao": d.descricao,
                "agrupa": d.agrupa,
                "exemplo": formato.formatar(formato.aviso_de(tipo, d.exemplo, agora), zona, estrito=False),
                "ligado": estados[tipo],
            }
            for tipo, d in CATALOGO.items()
        ]
```

Em `_tela_configuracoes`, acrescente ao contexto `"avisos": _avisos_da_tela(request)`, troque `"mensagem"` e `"secao_ativa"` por:

```python
                "mensagem": (
                    MENSAGEM_AVISOS if msg == "avisos"
                    else MENSAGEM_CONFIG if msg in ("geral", "liga", "amazon", "ia") else None
                ),
                "secao_ativa": secao_com_erro or (msg if msg in ("geral", "liga", "amazon", "ia", "avisos") else "geral"),
```

Rota:

```python
    @app.post("/configuracoes/avisos")
    async def salvar_aviso(request: Request):
        formulario = await ler_formulario(request)
        try:
            tipo = TipoAviso(formulario.get("tipo", ""))
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "tipo de aviso desconhecido") from None
        with sessoes() as s, s.begin():
            avisos.definir_ligado(s, tipo, formulario.get("ligado") == "1")
        return RedirectResponse("/configuracoes?msg=avisos", status_code=status.HTTP_303_SEE_OTHER)
```

- [ ] **Step 5: Template**

Em `src/tcg_sniper/admin/templates/configuracoes.html`, logo depois de `{% endfor %}` que fecha as seções (antes do `</div>` dos tabs):

```jinja
  <input type="radio" name="secao" class="tab" aria-label="Avisos"{% if secao_ativa == "avisos" %} checked{% endif %}>
  <div class="tab-content pt-4" id="avisos">
    <div class="card bg-base-100 shadow-sm"><div class="card-body">
      <p class="text-sm text-base-content/70">Cada tipo de mensagem do WhatsApp, com um exemplo. Desligado, o tipo não manda nada (os problemas continuam sendo contados e, ao religar, o próximo lembrete sai). Problemas repetidos saem uma vez, lembram a cada 2 h e fecham com "resolvido".</p>
      <ul class="list">
        {% for a in avisos %}
        <li class="list-row items-start" id="aviso-{{ a.tipo }}">
          <div class="text-xl" aria-hidden="true">{{ a.emoji }}</div>
          <div class="list-col-grow min-w-0 flex flex-col gap-2">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-semibold">{{ a.titulo }}</span>
              {% if a.severidade == "falha" %}<span class="badge badge-error badge-sm">Falha</span>
              {% elif a.severidade == "atencao" %}<span class="badge badge-warning badge-sm">Atenção</span>
              {% elif a.severidade == "concluido" %}<span class="badge badge-success badge-sm">Concluído</span>
              {% else %}<span class="badge badge-info badge-sm">Oportunidade</span>{% endif %}
              <span class="badge badge-ghost badge-sm">grupo {{ a.grupo }}</span>
              {% if a.agrupa %}<span class="badge badge-outline badge-sm">agrupa</span>{% endif %}
            </div>
            <p class="text-sm text-base-content/70">{{ a.descricao }}</p>
            <div class="chat chat-start">
              <div class="chat-bubble text-sm whitespace-pre-line break-words max-w-full">{{ a.exemplo }}</div>
            </div>
          </div>
          <form method="post" action="/configuracoes/avisos" class="flex items-center gap-2">
            <input type="hidden" name="tipo" value="{{ a.tipo }}">
            <input type="hidden" name="ligado" value="{{ '0' if a.ligado else '1' }}">
            <input type="checkbox" class="toggle toggle-success" aria-label="{{ a.titulo }}: {{ 'ligado' if a.ligado else 'desligado' }}"{% if a.ligado %} checked{% endif %} onchange="this.form.requestSubmit()">
            <noscript><button class="btn btn-xs">{{ "Desligar" if a.ligado else "Ligar" }}</button></noscript>
          </form>
        </li>
        {% endfor %}
      </ul>
    </div></div>
  </div>
```

Em `src/tcg_sniper/admin/formularios_config.py`, a explicação de `host_publico` vira: `"Usado nos links do admin para o noVNC. As mensagens do WhatsApp nunca levam este endereço. No Windows: ipconfig, \"Endereço IPv4\"."`

Em `scripts/verificar_layout.py`, acrescente `"/configuracoes?msg=avisos"` em `FIXAS`, logo depois de `"/configuracoes"`.

- [ ] **Step 6: CSS e testes**

Run: `uv run python scripts/gerar_css.py` e depois `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t8 uv run pytest -q -p no:cacheprovider tests/admin`
Expected: PASS (inclui `test_css_em_dia_com_os_templates`). Se algum teste antigo de Serviços contar linhas de `mensagem_saida` depois de pausar/retomar, filtre pelos que não começam com "🟡 *Serviço mudou no admin".

- [ ] **Step 7: Layout em 390 e 1440 px (admin local, banco descartável)**

Run (no worktree; nada na stack de produção):

```bash
docker compose exec -T postgres-teste createdb -U tcg tcg_test_t8_layout
DATABASE_URL=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t8_layout uv run tcg-sniper migrate
DATABASE_URL=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t8_layout ADMIN_SENHA=layout-teste uv run tcg-sniper admin --porta 8010
# em outro terminal:
ADMIN_BASE=http://127.0.0.1:8010 ADMIN_SENHA=layout-teste uv run python scripts/verificar_layout.py
```

Expected: "layout ok" (se o Chromium do Playwright faltar: `uv run playwright install chromium`). Pare o admin local depois.

- [ ] **Step 8: Suíte inteira, ruff e commit**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t8 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`

```bash
git add src/tcg_sniper/admin scripts/verificar_layout.py tests/admin/test_admin_avisos.py
git commit -m "feat: alerts tab in settings and manual pause/resume alerts"
```

---

### Task 9: Regras globais, limpeza, README e pendências

**Files:**
- Create: `tests/avisos/test_regras_globais.py`
- Delete: `src/tcg_sniper/notificador/fila.py`
- Modify: `src/tcg_sniper/notificador/__init__.py` (sai `criar_notificador`), `src/tcg_sniper/notificador/base.py` (sai o Protocol `Notificador`)
- Modify: `tests/fakes.py` (sai `NotificadorFake`), `tests/notificador/test_notificador.py` (saem os testes da fila e do `criar_notificador`)
- Modify: `README.md`, `docs/PENDENCIAS.md`
- Test: `tests/avisos/test_regras_globais.py`

**Interfaces:**
- Consumes: tudo das Tasks 1–8.
- Produces: nenhum código novo de produção; os testes globais travam as regras para o futuro.

- [ ] **Step 1: Banco da lane**

Run: `docker compose exec -T postgres-teste createdb -U tcg tcg_test_t9`

- [ ] **Step 2: Testes globais (falham enquanto houver resto do notificador antigo)**

Crie `tests/avisos/test_regras_globais.py`:

```python
import ast
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tcg_sniper.avisos.catalogo import CATALOGO, CHAVE_GERAL, TipoAviso
from tcg_sniper.avisos.formato import aviso_de, formatar, formatar_lembrete, formatar_resolvido

RAIZ = Path(__file__).resolve().parents[2] / "src" / "tcg_sniper"
QUANDO = datetime(2026, 10, 18, 13, 42, tzinfo=UTC)
SP = ZoneInfo("America/Sao_Paulo")
PROIBIDO = re.compile(r":(?:8000|6080|6081)(?!\d)|192\.168\.0\.10")


def arquivos(*, fora_de: tuple[str, ...] = ()) -> list[Path]:
    saida = []
    for caminho in RAIZ.rglob("*.py"):
        relativo = caminho.relative_to(RAIZ).as_posix()
        if "migrations/" in relativo or any(relativo.startswith(p) for p in fora_de):
            continue
        saida.append(caminho)
    return saida


@pytest.mark.parametrize("tipo", list(TipoAviso))
def test_nenhum_exemplo_leva_endereco_do_sistema(tipo):
    exemplo = CATALOGO[tipo].exemplo
    aviso = aviso_de(tipo, exemplo, QUANDO)
    textos = [
        formatar(aviso, SP, "192.168.0.10", estrito=True),
        formatar_lembrete(aviso, 3, QUANDO - timedelta(hours=2), SP, "192.168.0.10", estrito=True),
        formatar_resolvido(tipo, CHAVE_GERAL, 3, QUANDO - timedelta(hours=2), QUANDO, SP, "192.168.0.10", estrito=True),
    ]
    for texto in textos:
        assert not PROIBIDO.search(texto)
        for url in re.findall(r"https?://\S+", texto):
            assert re.match(r"https://www\.(amazon|ligamagic)\.com\.br/", url), url


def test_fora_de_avisos_nada_envia_mensagem_direto():
    problemas = []
    for caminho in arquivos(fora_de=("avisos/",)):
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if isinstance(no, ast.Call):
                funcao = no.func
                nome = funcao.attr if isinstance(funcao, ast.Attribute) else getattr(funcao, "id", "")
                alvo = ast.unparse(funcao.value) if isinstance(funcao, ast.Attribute) else ""
                if nome == "enfileirar" or (nome == "enviar" and "notificador" in alvo.lower()):
                    problemas.append(f"{caminho.name}:{no.lineno} {ast.unparse(funcao)}")
            if isinstance(no, ast.ImportFrom):
                nomes = {a.name for a in no.names}
                if nomes & {"Notificador", "NotificadorFila", "criar_notificador"} or (no.module or "").endswith(
                    "notificador.fila"
                ):
                    problemas.append(f"{caminho.name}:{no.lineno} import {sorted(nomes)}")
    assert problemas == []


def test_nenhum_texto_de_codigo_fora_do_admin_tem_porta_do_sistema():
    """`avisos/` fica de fora: a guarda de URL tem as portas no próprio regex."""
    problemas = []
    for caminho in arquivos(fora_de=("admin/", "avisos/")):
        for no in ast.walk(ast.parse(caminho.read_text(encoding="utf-8"))):
            if isinstance(no, ast.Constant) and isinstance(no.value, str) and PROIBIDO.search(no.value):
                problemas.append(f"{caminho.name}:{no.lineno}")
    assert problemas == []


def test_host_publico_so_no_admin_na_config_no_banco_e_nos_avisos():
    permitidos = ("admin/", "avisos/", "db/", "config.py", "config_banco.py")
    problemas = []
    for caminho in arquivos(fora_de=permitidos):
        for no in ast.walk(ast.parse(caminho.read_text(encoding="utf-8"))):
            if isinstance(no, ast.Attribute) and no.attr == "host_publico":
                problemas.append(f"{caminho.name}:{no.lineno}")
    assert problemas == []
```

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t9 uv run pytest -q -p no:cacheprovider tests/avisos/test_regras_globais.py`
Expected: FAIL em `test_fora_de_avisos_nada_envia_mensagem_direto` (`notificador/fila.py` ainda chama `enfileirar`; `notificador/__init__.py` importa `NotificadorFila`).

- [ ] **Step 3: Limpar o notificador antigo**

- `git rm src/tcg_sniper/notificador/fila.py`.
- `src/tcg_sniper/notificador/__init__.py` fica só com:

```python
"""Serviço `notificador` (servico.py): envia a tabela de saída pela Evolution. Quem grava as mensagens é
`tcg_sniper.avisos` (catálogo, formato e repetição)."""

CHAVE_PADRAO = "trocar-esta-chave"
```

- `src/tcg_sniper/notificador/base.py` fica só com o `Destino`:

```python
from enum import StrEnum


class Destino(StrEnum):
    ADMIN = "admin"
    OPORTUNIDADES = "oportunidades"
```

- `tests/fakes.py`: apague `NotificadorFake`.
- `tests/notificador/test_notificador.py`: apague os testes de `NotificadorFila` e de `criar_notificador` e os imports deles (`criar_notificador`, `NotificadorFila`, `Destino` se não for mais usado); ficam os de `enviar_uma_vez`.

Run: `grep -rn "NotificadorFake\|criar_notificador\|NotificadorFila\|notificador.base import.*Notificador" src tests`
Expected: nada.

- [ ] **Step 4: README**

Em `README.md`, substitua a seção "### Mensagens no WhatsApp" (tabela inteira) por:

```markdown
### Mensagens no WhatsApp

Todas as mensagens seguem o mesmo formato: emoji de severidade (🔴 falha, 🟡 atenção, ✅ concluído, 💰 oportunidade), título em negrito, linhas com "•", "*O que fazer:*" e, em itálico, a hora e quem mandou. Nenhuma leva endereço do admin ou do noVNC (só abrem na rede de casa); a ação diz onde fazer, por exemplo "noVNC da Amazon (porta 6081)" ou "Admin → Serviços → Amazon → Retomar". Links de produto (Amazon, LigaMagic) continuam.

Um problema que se repete sai uma vez, volta como lembrete a cada 2 h enquanto continuar ("continua · N vezes desde HH:MM") e fecha com "✅ … resolvido". Cada tipo pode ser desligado em **Configurações → Avisos**, que mostra um exemplo de cada um.

| Grupo | Avisos |
| --- | --- |
| LigaMagic | ✅ coleta concluída · 🟡 coleta parcial · 🔴 coleta falhou · 🔴 desafio do Cloudflare · 🟡 produtos novos no catálogo · 🟡 coleta interrompida · 🔴 erro inesperado |
| Amazon | ✅ busca concluída · ✅ rodada do monitor · 🟡 busca parcial · 🔴 busca falhou · 🔴 CAPTCHA · 🔴 conta sem login · 🔴 conferir o carrinho (um por ASIN) · 🔴 pausada · 🟡 erro inesperado · 🟡 ciclo interrompido |
| IA | ✅ rodada concluída · 🔴 casador pausado · 🟡 sem orçamento · 🟡 falhas seguidas |
| Backup | ✅ concluído · 🔴 erro · 🟡 interrompido |
| Serviços | 🔴 serviço sem sinal (ativo e mudo há mais de 10 min) · 🟡 serviço mudou no admin (pausar/retomar) · 🔴 mensagem não enviada (no máximo uma por hora) |
| Oportunidades | 💰 oportunidade, no grupo de oportunidades: preço da Amazon (conferido com impostos, frete à parte; ou anunciado, sem impostos), quem vende, referência da Liga e o link do anúncio |
```

E, no texto do passo da primeira coleta, troque `Ao final, o grupo admin recebe "N produtos novos no catálogo" e o resumo da coleta.` por `Ao final, o grupo admin recebe "🟡 Liga · produtos novos no catálogo" e "✅ Liga · coleta concluída".`; na seção da conferência de checkout, troque `o grupo admin recebe uma vez "Confira o carrinho da Amazon: pode haver 1× <ASIN>…"` por `o grupo admin recebe "🔴 Amazon · conferir o carrinho · <ASIN>" (com lembrete a cada 2 h até resolver)`.

- [ ] **Step 5: Pendências**

Em `docs/PENDENCIAS.md`: atualize "Última revisão" para a data do merge; em "## 1. Acompanhar (sem código)" acrescente:

```markdown
- [ ] Volume de avisos no grupo admin na primeira semana (~60–70/dia com a rodada do monitor); desligar em Configurações → Avisos o que virar ruído.
- [ ] Primeiro "Serviço sem sinal" real: conferir que não houve alarme falso durante coletas longas (a batida é uma thread de 60 s).
```

e, no topo de "## Concluídas", um bloco novo (preencha os hashes com `git log --oneline` depois do merge):

```markdown
### Avisos no WhatsApp (2026-10-18)

- [x] Formato único (emoji, título em negrito, "•", "O que fazer", rodapé com hora e origem), sem endereço do sistema nas mensagens (só links de produto da Amazon e da LigaMagic), com escape e corte em 1500 caracteres (`<hash>`).
- [x] Catálogo de 28 tipos, cada um desligável em Configurações → Avisos com exemplo; repetição agrupada (lembrete a cada 2 h, "✅ resolvido"); tabelas `estado_aviso` e `config_aviso` (`<hash>`).
- [x] Avisos novos: conclusão de cada tarefa (Liga, busca e rodada do monitor da Amazon, rodada da IA, backup), parciais, falhas seguidas da IA, mensagem não enviada, pausar/retomar no admin (`<hash>`).
- [x] Vigia de serviços no `manutencao`: serviço ativo sem sinal há mais de 10 min abre "Serviço sem sinal"; batida de vida dos coletores e do casador em `sinal_servico` (`<hash>`).
- [x] Testes globais: nenhum exemplo leva endereço do sistema; fora de `avisos/` nada grava mensagem direto; `host_publico` só no admin, na configuração e nos avisos (`<hash>`).
```

- [ ] **Step 6: Suíte inteira, ruff e commit**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t9 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde.

```bash
git add -A src/tcg_sniper/notificador tests README.md docs/PENDENCIAS.md
git commit -m "test: global alert rules; remove the direct notifier; docs"
```

---

## Implantação (depois do merge, com ok do usuário; o controlador faz, não um subagente)

1. `docker compose run --rm migrate` aplica `e4b7c2d9a1f6` (três tabelas novas; nada aberto é herdado).
2. Rebuild e restart de `coletor-liga`, `coletor-amazon`, `casador`, `notificador`, `manutencao` e `admin` (todos importam o módulo novo).
3. Conferir: em até 2 min, `sinal_servico` tem linhas de liga, amazon e casador; Configurações → Avisos mostra os 28 tipos; pausar e retomar um serviço em Serviços manda "🟡 Serviço mudou no admin" no grupo admin.
