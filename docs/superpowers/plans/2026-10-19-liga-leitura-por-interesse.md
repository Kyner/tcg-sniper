# Coletor da LigaMagic: leitura por interesse e esfriar após desafio — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A etapa 2 do job diário da LigaMagic deixa de abrir os 2165 produtos ativos e passa a abrir só a lista do dia (casados, com candidato, novos até um teto e o rodízio semanal, sem reler o que já foi lido hoje); depois de um desafio do Cloudflare o coletor esfria antes de voltar, segue com pausas em dobro e, no 2º desafio do dia, para até o dia seguinte.

**Architecture:** Dois módulos novos e quase puros em `coletor_liga/`: `lista_do_dia.py` (`montar_lista`: calcula a lista do banco a cada job, com os grupos e as contagens) e `esfriamento.py` (`situacao_desafio`: desafios de hoje e "esfriando até", derivados da tabela `coleta` e da hora da retomada em `estado_coletor`, então um reinício não zera nada). `produtos.py` usa a lista; o `Agendador` consulta a situação a cada tick (esfriando: nada roda; parada: descarta o pedido) e dobra as pausas do job inteiro depois de um desafio no dia. Em volta: duas colunas em `config_liga` (migração), textos do resumo e do aviso de desafio, e o card da LigaMagic em Serviços e no Dashboard.

**Tech Stack:** Python 3.12 (Docker; o venv local do uv pode ser 3.14), uv, SQLAlchemy 2 + Alembic, Postgres 16, pydantic-settings, FastAPI + Jinja2 + DaisyUI 5 (admin), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-19-liga-leitura-por-interesse-design.md`

**Base de código:** este plano roda **depois** do merge do branch `amazon-busca-separada` em `main` (head do Alembic `c6a2f8e4d1b9`, admin com os cards "Amazon (busca)" e "Amazon (monitor e checkout)"). Os números de linha citados vêm desse código integrado (worktrees `tcg-sniper-wt/abs` e, para o admin, `tcg-sniper-wt/admin`); confira o trecho pelo texto antes de editar.

## Global Constraints

- Nomes, comentários, mensagens, avisos e textos de tela em português. Assunto dos commits em inglês, `feat:`/`fix:`/`test:`/`docs:`, **sem** `Co-Authored-By`, `Claude-Session`, "Generated with" nem qualquer trailer de IA.
- Repositório público: nada de dado pessoal (telefone, grupo, IP real, e-mail) em código, teste, fixture ou documento.
- Regras do spec (verbatim): "Um produto aparece uma vez só, no primeiro grupo em que cair"; ordem "Casados" (par `confirmado`) → "Com candidato" (par `pendente`) → "Novos: produto ativo sem nenhum `resumo_preco`, os mais antigos (`visto_primeiro_em`) primeiro, até **"Produtos novos por dia"** (padrão 100)" → "Rodízio: os demais ativos com `id % 7` igual ao dia da semana (segunda = 0)"; "O que já tem `resumo_preco` gravado hoje (desde a meia-noite no fuso) sai da lista"; "Dentro de cada grupo a ordem é embaralhada, como hoje"; "As listagens continuam diárias e completas".
- Esfriar (verbatim): "Desafios hoje" = coletas da Liga que terminaram `pausada_desafio` desde a meia-noite (fuso de Geral); 1º desafio: "o agendador só começa o job depois de **"Esfriar após desafio (min)"** (padrão 30), contado da retomada" e "No resto do dia, as pausas entre páginas usam o dobro de `pausa_min_s`/`pausa_max_s`"; 2º desafio: "o agendador não roda mais nada hoje e segue no horário normal de amanhã"; "Rodar agora respeita as duas regras"; "o reinício não zera a espera".
- Configuração: `esfriar_desafio_min` padrão 30, limites 0–240; `produtos_novos_dia` padrão 100, limites 0–2000; colunas em `config_liga` (migração Alembic, sem tabela nova), com downgrade que as remove.
- Histórico de preço nunca é apagado (`resumo_preco`, `preco_listagem`, `preco_atual_*` etc.): nada aqui apaga linha.
- Admin: só componentes do DaisyUI 5 e utilitários do Tailwind, classes literais (nunca montadas por concatenação). Toda tarefa que mexe em template regenera `src/tcg_sniper/admin/static/admin.css` com `uv run python scripts/gerar_css.py` e commita junto (o teste `test_css_em_dia_com_os_templates` confere).
- Testes só no Postgres de teste (container `postgres-teste`, `127.0.0.1:5433`), um banco por lane (`tcg_test_<lane>`; o fixture `engine` apaga o schema). Criar o banco, de dentro do worktree: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_<lane>` ("already exists" é ok). Ao fim de cada tarefa, verdes: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_<lane> uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`.
- Cada lane trabalha no próprio worktree em `D:/Git/Pessoal/Python/tcg-sniper-wt/<lane>` (`superpowers:using-git-worktrees`), saindo do branch de integração; nada é escrito fora dele (a pasta temporária do pytest à parte; as ferramentas do `gerar_css.py` ficam em `<worktree>/.ferramentas/`). Os nomes de lane deste plano começam com `li-` para não colidir com os worktrees e bancos do plano da Amazon (`abs`, `admin`, ...).
- Nunca mexer na stack de produção: nada de `docker compose up/down/build/restart/run/stop` nem `migrate` contra o Postgres de produção (5432). Tudo que uma lane sobe (servidor, navegador) é parado antes de ela terminar.
- `docs/PENDENCIAS.md` é atualizado na última tarefa (CLAUDE.md: "atualizar no mesmo commit de cada entrega").

## Review Focus

1. **Meia-noite no fuso, não em UTC.** Um desafio às 23:50 de São Paulo é 02:50 UTC do dia seguinte: tem de contar no dia anterior (senão o 1º desafio de amanhã já vira "2º" e para o dia); um resumo gravado às 23:59 local de ontem não pode tirar o casado da lista de hoje. Testes: Task 3 `test_desafio_antes_da_meia_noite_local_conta_no_dia_anterior`; Task 2 `test_lido_hoje_fica_de_fora_e_a_meia_noite_e_a_do_fuso`.
2. **"Rodar agora" no meio do esfriamento.** Hoje `solicitar_execucao` regrava `estado_coletor.atualizado_em`; como o esfriamento conta dessa hora, cada clique empurraria a espera para frente. O pedido fica guardado e roda no fim da espera original. Testes: Task 3 `test_pedir_execucao_nao_muda_a_hora_da_ultima_mudanca_de_estado` e `test_pedir_execucao_nao_estende_o_esfriamento`; Task 5 `test_rodar_agora_no_esfriamento_nao_estende_a_espera`.
3. **Pedido pendente depois do 2º desafio virando job à meia-noite.** O Retomar do 2º desafio pede execução (`solicitar=True`), e um reinício no mesmo dia arma uma execução atrasada; se ficassem guardados, o job sairia às 00:00 em vez de "no horário normal de amanhã". Teste: Task 5 `test_segundo_desafio_nada_roda_ate_amanha_nem_com_rodar_agora`.
4. **Horário do dia que cai durante o esfriamento** (ex.: desafio ontem à noite, "Ligar" às 09:50, horário 10:00): o job do dia é adiado para o fim da espera, não perdido. Teste: Task 5 `test_horario_do_dia_durante_o_esfriamento_espera_o_fim`.
5. **Novos além do teto e grupos que se sobrepõem.** Com ~2000 produtos sem resumo (catálogo recém-ativado), o teto de 100 só vale se os excedentes não entrarem pelo rodízio; e um produto casado que também tem par pendente aparece uma vez só. Testes: Task 2 `test_novo_alem_do_teto_nao_entra_no_rodizio` e `test_grupos_na_ordem_e_cada_produto_uma_vez_so`.

## Decisões tomadas neste plano (o spec não fixava)

- **Módulos e nomes.** `coletor_liga/lista_do_dia.py`: `ListaDoDia`, `montar_lista(s, agora, fuso, novos_por_dia, embaralhar=random.shuffle)`, `inicio_do_dia(agora, fuso)`. `coletor_liga/esfriamento.py`: `TIPOS_LIGA`, `SituacaoDesafio`, `desafios_desde(s, desde)`, `situacao_desafio(s, agora, fuso, esfriar_min)`. O `agendador.py` passa a importar `TIPOS_LIGA` de `esfriamento` (o admin continua importando `agendador.TIPOS_LIGA`).
- **Ordem antes de embaralhar** (vale com `embaralhar` que não mexe, nos testes): casados, candidatos e rodízio por `id`; novos por (`visto_primeiro_em`, `id`). `embaralhar` (o mesmo parâmetro injetável de hoje, padrão `random.shuffle`) é chamado uma vez por grupo, inclusive vazio.
- **Novo além do teto espera** os próximos dias e **não entra no rodízio** (o teto limita as páginas de produtos nunca lidos). Um produto inativo, ou só com par `ignorado`, não é casado nem candidato.
- **"Lido hoje"** = qualquer `resumo_preco.coletado_em >= meia-noite local`, de qualquer grupo. A lista usa o relógio do agendador (`agora`); `coletar_produtos` aceita `agora` (padrão: `repo.agora_utc()`).
- **Referência do esfriamento** = `estado_coletor.atualizado_em` da Liga, e só enquanto (a) ela está `ativo`, (b) houve um desafio da Liga e (c) **nenhuma coleta da Liga começou depois do fim do último desafio**. A regra (c) encerra o esfriamento assim que o job volta (o `consumir_solicitacao` regrava `atualizado_em` no início do job e não pode reabrir a espera). Para o "Rodar agora" não estender a espera, `repo.solicitar_execucao` deixa de mexer em `atualizado_em` (só liga o pedido); nada mais lê essa hora para a Liga, e os outros serviços só usam `execucao_solicitada`.
- **O esfriamento vale para o último desafio mesmo de ontem** (ex.: desafio às 23:00, retomada às 08:00 de hoje: espera até 08:30). Já "desafios hoje" (pausas em dobro e parada) conta só desde a meia-noite: um desafio de ontem não dobra as pausas de hoje.
- **Esfriando, nada roda:** nem o pedido (fica guardado), nem a execução atrasada, nem o horário do dia; os dois últimos são só adiados (rodam no fim da espera, se ainda couberem no dia).
- **Parada (2º desafio do dia):** a cada tick o pedido é descartado (`consumir_solicitacao` e não roda) e a execução atrasada é limpa; o dia seguinte segue o horário normal com pausas normais. No admin, "Rodar agora" some do card e a rota recusa com mensagem (`liga_parada_hoje`); o Retomar diz que volta amanhã (`retomar_parada`) ou que vai esfriar (`retomar_esfriando`).
- **Pausas em dobro** = uma cópia do `Config` com `pausa_min_s` e `pausa_max_s` × 2, decidida no início do job e usada no job inteiro (listagens, cliques em "Exibir mais", pausa entre etapas e produtos).
- **Linha de produtos do resumo:** `Produtos: <status> · <ok> de <ok+falha> · casados N, candidatos N, novos N, rodízio N`. O texto dos grupos vem em `ResultadoColeta.grupos` (novo campo, `None` quando a etapa não veio da lista: aí a linha termina em `<ok> de <total>`). `DESCRICAO` da etapa continua "Coleta dos produtos ativos".
- **Aviso de desafio:** mantém "Página: …" e "A coleta fica pausada até você retomar" e ganha uma 3ª linha: "1º desafio de hoje: volta 30 min depois de você retomar, com pausas em dobro até o fim do dia" (com 0 min: "volta logo depois de você retomar, …") ou "2º desafio de hoje: depois de retomar, a coleta só volta amanhã, no horário de sempre". A contagem inclui o desafio que está sendo registrado.
- **Cards:** no Dashboard, situação `parcial` (selo amarelo, não vira aviso de problema) com selo "esfriando" e texto "Esfriando até HH:MM", ou selo "parada até amanhã" e texto "Parada até amanhã (2º desafio)". Em Serviços, os mesmos textos em negrito no card ativo, com selo `parcial`.
- **Config:** as colunas novas nascem com `server_default` (30, 100) e **não** são semeadas do `.env`; o `Config` ganha os dois campos com os mesmos padrões e limites (para quem lê sem banco) e `config_banco.sobrepor` os copia da tela.
- **Revisão Alembic:** `d4b8e2f6a3c1_liga_leitura_por_interesse.py`, `down_revision = "c6a2f8e4d1b9"`; restrições `ck_config_liga_esfriar_desafio_min` e `ck_config_liga_produtos_novos_dia` (os nomes que o modelo gera a partir de `LIMITES_CONFIG_LIGA`).

---

## Ondas (para execução paralela)

- **Onda 1 (em paralelo, cada uma no próprio worktree a partir do branch de integração):** Task 1 (lane `li-config`: colunas, migração, `Config`) e Tasks 2→3 (lane `li-lista`, sequenciais: `lista_do_dia.py`, depois `esfriamento.py` e `solicitar_execucao`).
- **Onda 2 (em paralelo, a partir do branch integrado da Onda 1):** Tasks 4→5 (lane `li-coletor`, sequenciais: produtos pela lista e resumo; depois esfriar no agendador e aviso de desafio) e Task 6 (lane `li-admin`: Configurações, Serviços, Dashboard).
- **Onda 3:** Task 7 (lane `li-final`: regressão inteira, README, `docs/PENDENCIAS.md`).
- Integração: o controlador cria o branch `liga-leitura-por-interesse` a partir de `main` (já com a Amazon separada), faz merge de cada lane ao fim da onda (`git merge --no-ff`) e as lanes da onda seguinte saem desse branch.
- Conflitos esperados: nenhum arquivo é tocado por duas lanes da mesma onda. Entre ondas: `produtos.py` e `agendador.py` (Tasks 4 e 5, mesma lane); `tests/avisos/test_formato.py` e `avisos/catalogo.py` (Tasks 4 e 5, mesma lane); `admin.css` só na lane `li-admin`.

## Arquivos

| Arquivo | Responsabilidade | Tasks |
|---|---|---|
| `src/tcg_sniper/db/models.py` | `LIMITES_CONFIG_LIGA` e colunas de `ConfigLiga` | 1 |
| `src/tcg_sniper/db/migrations/versions/d4b8e2f6a3c1_liga_leitura_por_interesse.py` (novo) | colunas com padrão, restrições, downgrade | 1 |
| `src/tcg_sniper/config.py`, `src/tcg_sniper/config_banco.py` | campos no `Config` e cópia da tela | 1 |
| `src/tcg_sniper/coletor_liga/lista_do_dia.py` (novo) | lista do dia, grupos, `inicio_do_dia` | 2 |
| `src/tcg_sniper/coletor_liga/esfriamento.py` (novo) | desafios de hoje, esfriando até, parada | 3 |
| `src/tcg_sniper/db/repositorio.py` | `solicitar_execucao` não mexe em `atualizado_em` | 3 |
| `src/tcg_sniper/coletor_liga/produtos.py` | etapa 2 pela lista do dia | 4, 5 |
| `src/tcg_sniper/coletor_liga/execucao.py` | `ResultadoColeta.grupos`, `dados_resumo` (4); `dados_desafio`, `registrar_desafio` (5) | 4, 5 |
| `src/tcg_sniper/coletor_liga/listagens.py` | chamada de `registrar_desafio` com `config` | 5 |
| `src/tcg_sniper/coletor_liga/agendador.py` | `agora` para a lista (4); esfriar, parada, pausas em dobro (5) | 4, 5 |
| `src/tcg_sniper/avisos/catalogo.py` | exemplos do resumo (4) e do desafio (5) | 4, 5 |
| `src/tcg_sniper/admin/formularios_config.py`, `templates/configuracoes.html` | campos e explicação em Configurações → LigaMagic | 6 |
| `src/tcg_sniper/admin/app.py`, `templates/servicos.html` | card da Liga, "Rodar agora" e Retomar com o esfriamento | 6 |
| `src/tcg_sniper/admin/consultas_painel.py` | card da Liga no Dashboard | 6 |
| `README.md`, `docs/PENDENCIAS.md` | documentação e pendências | 7 |

---

### Task 1: Colunas em `config_liga`, migração e `Config` (lane `li-config`)

**Files:**
- Modify: `src/tcg_sniper/db/models.py:519-525` (`LIMITES_CONFIG_LIGA`), `:566-575` (colunas de `ConfigLiga`)
- Create: `src/tcg_sniper/db/migrations/versions/d4b8e2f6a3c1_liga_leitura_por_interesse.py`
- Modify: `src/tcg_sniper/config.py:30-38` (campos), `src/tcg_sniper/config_banco.py:10-27` (`sobrepor`)
- Test: `tests/db/test_migracao_liga_interesse.py` (novo), `tests/db/test_config_banco.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: head do Alembic `c6a2f8e4d1b9`; `repo.obter_config_liga`, `repo.salvar_config_liga`, `carregar_config`.
- Produces:
  - `LIMITES_CONFIG_LIGA["esfriar_desafio_min"] == (0, 240)`, `LIMITES_CONFIG_LIGA["produtos_novos_dia"] == (0, 2000)`.
  - `ConfigLiga.esfriar_desafio_min: int` (padrão 30), `ConfigLiga.produtos_novos_dia: int` (padrão 100).
  - `Config.esfriar_desafio_min: int = 30` (0–240), `Config.produtos_novos_dia: int = 100` (0–2000); `carregar_config(...)` traz os valores salvos na tela.
  - Revisão Alembic `d4b8e2f6a3c1` (nova head).

- [ ] **Step 1: Banco da lane**

Run: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_li_config`
Expected: sem saída (ou "already exists").

- [ ] **Step 2: Escrever os testes (falham)**

Crie `tests/db/test_migracao_liga_interesse.py`:

```python
from alembic import command
from sqlalchemy import create_engine, pool, text

from tcg_sniper.db.session import config_alembic

ANTES = "c6a2f8e4d1b9"
COLUNAS = (
    "SELECT column_name FROM information_schema.columns "
    "WHERE table_name = 'config_liga' AND column_name IN ('esfriar_desafio_min', 'produtos_novos_dia')"
)
LINHA = (
    "INSERT INTO config_liga (id, coleta_hora, coleta_jitter_min, pausa_min_s, pausa_max_s, limite_falha_pct, "
    "categorias, url_listagem, max_cliques, atualizado_em) "
    "VALUES (1, '10:00', 30, 8, 20, 50, '10', 'https://liga.test/?c={categ}', 50, now()) "
    "ON CONFLICT (id) DO NOTHING RETURNING id"
)


def test_migracao_da_leitura_por_interesse_sobe_e_desce(engine):
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    criada = False
    try:
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.execute(text(COLUNAS)).all() == []
            criada = c.execute(text(LINHA)).first() is not None  # linha de antes da migração
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            valores = c.execute(text("SELECT esfriar_desafio_min, produtos_novos_dia FROM config_liga WHERE id = 1"))
            assert tuple(valores.one()) == (30, 100)
            restricoes = {
                r[0]
                for r in c.execute(
                    text("SELECT conname FROM pg_constraint WHERE conrelid = 'config_liga'::regclass AND contype = 'c'")
                )
            }
            assert {"ck_config_liga_esfriar_desafio_min", "ck_config_liga_produtos_novos_dia"} <= restricoes
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.execute(text(COLUNAS)).all() == []
    finally:
        command.upgrade(cfg, "head")
        if criada:
            with proprio.begin() as c:
                c.execute(text("DELETE FROM config_liga WHERE id = 1"))
        proprio.dispose()
```

Em `tests/db/test_config_banco.py`, acrescente à lista do `parametrize` de `test_config_liga_recusa_valores_fora_dos_limites`:

```python
        ("esfriar_desafio_min", 241),
        ("esfriar_desafio_min", -1),
        ("produtos_novos_dia", 2001),
        ("produtos_novos_dia", -1),
```

e, ao fim do arquivo:

```python
def test_esfriar_e_novos_por_dia_nascem_com_o_padrao_e_vao_para_o_config(sessoes, config):
    with sessoes() as s, s.begin():
        liga = repo.obter_config_liga(s, config)
        assert (liga.esfriar_desafio_min, liga.produtos_novos_dia) == (30, 100)
        repo.salvar_config_liga(s, {"esfriar_desafio_min": 45, "produtos_novos_dia": 250}, AGORA)
    efetiva = carregar_config(sessoes, config)
    assert (efetiva.esfriar_desafio_min, efetiva.produtos_novos_dia) == (45, 250)
```

Em `tests/test_config.py`, ao fim do arquivo:

```python
def test_padroes_da_leitura_por_interesse():
    c = Config(_env_file=None)
    assert (c.esfriar_desafio_min, c.produtos_novos_dia) == (30, 100)


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("esfriar_desafio_min", 241), ("esfriar_desafio_min", -1), ("produtos_novos_dia", 2001), ("produtos_novos_dia", -1)],
)
def test_limites_da_leitura_por_interesse(campo, valor):
    with pytest.raises(ValidationError):
        Config(_env_file=None, **{campo: valor})
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_config uv run pytest -q -p no:cacheprovider tests/db/test_migracao_liga_interesse.py tests/db/test_config_banco.py tests/test_config.py`
Expected: FAIL (`AttributeError: 'ConfigLiga' object has no attribute 'esfriar_desafio_min'`, `'Config' object has no attribute 'esfriar_desafio_min'`, colunas inexistentes).

- [ ] **Step 4: Modelo e `Config`**

Em `src/tcg_sniper/db/models.py`, troque `LIMITES_CONFIG_LIGA` por:

```python
LIMITES_CONFIG_LIGA: dict[str, tuple[int, int]] = {
    "coleta_jitter_min": (0, 180),
    "pausa_min_s": (0, 120),
    "pausa_max_s": (0, 120),
    "limite_falha_pct": (0, 100),
    "max_cliques": (1, 500),
    "esfriar_desafio_min": (0, 240),
    "produtos_novos_dia": (0, 2000),
}
```

Em `ConfigLiga`, depois de `max_cliques`:

```python
    # Minutos de espera depois de retomar um desafio do Cloudflare (coletor_liga.esfriamento).
    esfriar_desafio_min: Mapped[int] = mapped_column(Integer, server_default="30")
    # Teto de produtos ainda sem resumo abertos por dia (coletor_liga.lista_do_dia).
    produtos_novos_dia: Mapped[int] = mapped_column(Integer, server_default="100")
```

Em `src/tcg_sniper/config.py`, depois de `limite_falha_pct`:

```python
    # Valem da tela (config_liga); o .env não semeia estes dois.
    esfriar_desafio_min: int = Field(30, ge=0, le=240)
    produtos_novos_dia: int = Field(100, ge=0, le=2000)
```

Em `src/tcg_sniper/config_banco.py`, no `update` de `sobrepor`, depois de `"liga_max_cliques": liga.max_cliques,`:

```python
            "esfriar_desafio_min": liga.esfriar_desafio_min,
            "produtos_novos_dia": liga.produtos_novos_dia,
```

- [ ] **Step 5: Migração**

Crie `src/tcg_sniper/db/migrations/versions/d4b8e2f6a3c1_liga_leitura_por_interesse.py`:

```python
"""LigaMagic: leitura por interesse e esfriar após desafio (esfriar_desafio_min e produtos_novos_dia em config_liga)

Revision ID: d4b8e2f6a3c1
Revises: c6a2f8e4d1b9
Create Date: 2026-10-19 23:00:00

Colunas com padrão (30 min e 100 produtos): a linha que já existe ganha os padrões. O downgrade tira as duas.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4b8e2f6a3c1"
down_revision: Union[str, Sequence[str], None] = "c6a2f8e4d1b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("config_liga", sa.Column("esfriar_desafio_min", sa.Integer(), server_default="30", nullable=False))
    op.add_column("config_liga", sa.Column("produtos_novos_dia", sa.Integer(), server_default="100", nullable=False))
    op.create_check_constraint(
        "ck_config_liga_esfriar_desafio_min", "config_liga", "esfriar_desafio_min BETWEEN 0 AND 240"
    )
    op.create_check_constraint(
        "ck_config_liga_produtos_novos_dia", "config_liga", "produtos_novos_dia BETWEEN 0 AND 2000"
    )


def downgrade() -> None:
    op.drop_constraint("ck_config_liga_produtos_novos_dia", "config_liga", type_="check")
    op.drop_constraint("ck_config_liga_esfriar_desafio_min", "config_liga", type_="check")
    op.drop_column("config_liga", "produtos_novos_dia")
    op.drop_column("config_liga", "esfriar_desafio_min")
```

- [ ] **Step 6: Rodar os testes da tarefa**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_config uv run pytest -q -p no:cacheprovider tests/db tests/test_config.py`
Expected: PASS (inclusive `test_migracao_igual_aos_modelos`).

- [ ] **Step 7: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_config uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde.

- [ ] **Step 8: Commit**

```bash
git add src/tcg_sniper/db/models.py src/tcg_sniper/db/migrations/versions/d4b8e2f6a3c1_liga_leitura_por_interesse.py src/tcg_sniper/config.py src/tcg_sniper/config_banco.py tests/db tests/test_config.py
git commit -m "feat: LigaMagic cooldown and daily new-products settings"
```

---

### Task 2: Lista do dia (lane `li-lista`)

**Files:**
- Create: `src/tcg_sniper/coletor_liga/lista_do_dia.py`
- Test: `tests/coletor_liga/test_lista_do_dia.py` (novo)

**Interfaces:**
- Consumes: modelos `ProdutoLiga`, `ResumoPreco`, `Casamento`, `StatusCasamento`; de teste, `fakes.criar_produto`, `fakes.criar_anuncio`, `repo.iniciar_coleta`, `repo.gravar_precos_produto`, `modelos.Resumo`.
- Produces (módulo `tcg_sniper.coletor_liga.lista_do_dia`):
  - `DIAS_DO_RODIZIO = 7`.
  - `@dataclass(frozen=True) class ListaDoDia(produtos: tuple[tuple[int, str], ...], casados: int, candidatos: int, novos: int, rodizio: int)` com `grupos() -> str` ("casados 52, candidatos 18, novos 100, rodízio 312").
  - `inicio_do_dia(agora: datetime, fuso: ZoneInfo) -> datetime` (meia-noite de hoje no fuso).
  - `montar_lista(s: Session, agora: datetime, fuso: ZoneInfo, novos_por_dia: int, embaralhar: Callable[[list], None] = random.shuffle) -> ListaDoDia`.

- [ ] **Step 1: Banco da lane**

Run: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_li_lista`

- [ ] **Step 2: Escrever os testes (falham)**

Crie `tests/coletor_liga/test_lista_do_dia.py`:

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fakes import criar_anuncio, criar_produto

from tcg_sniper.coletor_liga.lista_do_dia import ListaDoDia, inicio_do_dia, montar_lista
from tcg_sniper.coletor_liga.modelos import Resumo
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import StatusCasamento, TipoColeta

SP = ZoneInfo("America/Sao_Paulo")
SEGUNDA = datetime(2026, 10, 12, 12, 0, tzinfo=SP)
QUARTA = SEGUNDA + timedelta(days=2)
ANTIGO = SEGUNDA - timedelta(days=10)


def fixo(_grupo):
    """Não embaralha: a ordem fica a de antes do sorteio."""


def produto(s, nome, lido_em=None, ativo=True, visto=ANTIGO):
    """Produto com (opcionalmente) um resumo gravado em `lido_em`."""
    p = criar_produto(s, nome, ativo=ativo, agora=visto)
    if lido_em is not None:
        c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, lido_em)
        repo.gravar_precos_produto(s, c.id, p.id, Resumo(None, None, None, 1), lido_em)
    return p


def par(s, p, status, sufixo="00"):
    criar_anuncio(s, f"B{p.id:07d}{sufixo}", produto=p, status=status)


def ids(lista):
    return [produto_id for produto_id, _ in lista.produtos]


def test_grupos_na_ordem_e_cada_produto_uma_vez_so(s):
    casado = produto(s, "casado", lido_em=ANTIGO)
    par(s, casado, StatusCasamento.CONFIRMADO)
    par(s, casado, StatusCasamento.PENDENTE, "01")  # também tem candidato: fica só em casados
    candidato = produto(s, "candidato", lido_em=ANTIGO)
    par(s, candidato, StatusCasamento.PENDENTE)
    novo = produto(s, "novo")
    velhos = [produto(s, f"velho{i}", lido_em=ANTIGO) for i in range(7)]
    [do_dia] = [v for v in velhos if v.id % 7 == QUARTA.weekday()]

    lista = montar_lista(s, QUARTA, SP, 100, fixo)

    assert ids(lista) == [casado.id, candidato.id, novo.id, do_dia.id]
    assert (lista.casados, lista.candidatos, lista.novos, lista.rodizio) == (1, 1, 1, 1)
    assert lista.grupos() == "casados 1, candidatos 1, novos 1, rodízio 1"
    assert dict(lista.produtos)[novo.id] == novo.url


def test_rodizio_cobre_cada_produto_uma_vez_por_semana(s):
    assert SEGUNDA.weekday() == 0
    velhos = [produto(s, f"v{i}", lido_em=ANTIGO) for i in range(14)]
    vistos = []
    for dia in range(7):
        lista = montar_lista(s, SEGUNDA + timedelta(days=dia), SP, 100, fixo)
        assert all(produto_id % 7 == dia for produto_id in ids(lista))
        assert lista.rodizio == 2
        vistos += ids(lista)
    assert sorted(vistos) == sorted(v.id for v in velhos)


def test_novos_ate_o_teto_os_mais_antigos_primeiro(s):
    novos = [produto(s, f"n{i}", visto=ANTIGO + timedelta(days=5 - i)) for i in range(5)]  # n4 é o mais antigo
    lista = montar_lista(s, QUARTA, SP, 3, fixo)
    assert ids(lista) == [novos[4].id, novos[3].id, novos[2].id]
    assert lista.novos == 3
    assert montar_lista(s, QUARTA, SP, 0, fixo).produtos == ()


def test_novo_alem_do_teto_nao_entra_no_rodizio(s):
    novos = [produto(s, f"n{i}") for i in range(7)]  # mesmo visto_primeiro_em: desempate pelo id
    lista = montar_lista(s, QUARTA, SP, 1, fixo)
    assert ids(lista) == [novos[0].id]
    assert (lista.novos, lista.rodizio) == (1, 0)


def test_lido_hoje_fica_de_fora_e_a_meia_noite_e_a_do_fuso(s):
    meia_noite = inicio_do_dia(QUARTA, SP)
    assert meia_noite == datetime(2026, 10, 14, 0, 0, tzinfo=SP)
    hoje = produto(s, "hoje", lido_em=meia_noite + timedelta(minutes=1))
    par(s, hoje, StatusCasamento.CONFIRMADO)
    ontem = produto(s, "ontem", lido_em=meia_noite - timedelta(minutes=1))  # 23:59 local = 02:59 UTC de hoje
    par(s, ontem, StatusCasamento.CONFIRMADO)
    lista = montar_lista(s, QUARTA, SP, 100, fixo)
    assert ids(lista) == [ontem.id]
    assert lista.casados == 1


def test_inativo_fica_de_fora_e_ignorado_nao_e_candidato(s):
    inativo = produto(s, "inativo", lido_em=ANTIGO, ativo=False)
    par(s, inativo, StatusCasamento.CONFIRMADO)
    so_ignorado = produto(s, "ignorado", lido_em=ANTIGO)
    par(s, so_ignorado, StatusCasamento.IGNORADO)
    lista = montar_lista(s, QUARTA, SP, 100, fixo)
    assert inativo.id not in ids(lista)
    assert (lista.casados, lista.candidatos) == (0, 0)


def test_embaralha_cada_grupo_separado(s):
    casados = [produto(s, f"c{i}", lido_em=ANTIGO) for i in range(2)]
    for c in casados:
        par(s, c, StatusCasamento.CONFIRMADO)
    novos = [produto(s, f"n{i}") for i in range(2)]
    chamadas = []

    def inverter(grupo):
        chamadas.append(len(grupo))
        grupo.reverse()

    lista = montar_lista(s, QUARTA, SP, 100, inverter)
    assert chamadas == [2, 0, 2, 0]  # casados, candidatos, novos, rodízio
    assert ids(lista) == [casados[1].id, casados[0].id, novos[1].id, novos[0].id]


def test_sem_produtos_a_lista_e_vazia(s):
    assert montar_lista(s, QUARTA, SP, 100, fixo) == ListaDoDia((), 0, 0, 0, 0)
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_lista uv run pytest -q -p no:cacheprovider tests/coletor_liga/test_lista_do_dia.py`
Expected: FAIL (`ModuleNotFoundError: No module named 'tcg_sniper.coletor_liga.lista_do_dia'`).

- [ ] **Step 4: Implementar**

Crie `src/tcg_sniper/coletor_liga/lista_do_dia.py`:

```python
"""Lista do dia da etapa 2 da LigaMagic: quais produtos ativos abrir hoje.

Um produto entra uma vez só, no primeiro grupo em que cair: casados (par confirmado), com candidato
(par pendente), novos (sem nenhum resumo, os mais antigos primeiro, até o teto do dia) e o rodízio (os
demais com `id % 7` igual ao dia da semana, segunda = 0). O que já tem resumo gravado hoje (desde a
meia-noite no fuso de Configurações → Geral) sai da lista: um Retomar ou Rodar agora continua de onde
parou. Calculada do banco a cada job, sem tabela própria.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcg_sniper.db.models import Casamento, ProdutoLiga, ResumoPreco, StatusCasamento

DIAS_DO_RODIZIO = 7


@dataclass(frozen=True)
class ListaDoDia:
    produtos: tuple[tuple[int, str], ...]  # (id, url), na ordem de leitura
    casados: int
    candidatos: int
    novos: int
    rodizio: int

    def grupos(self) -> str:
        """Texto do resumo do job: "casados 52, candidatos 18, novos 100, rodízio 312"."""
        return f"casados {self.casados}, candidatos {self.candidatos}, novos {self.novos}, rodízio {self.rodizio}"


def inicio_do_dia(agora: datetime, fuso: ZoneInfo) -> datetime:
    """Meia-noite de hoje no fuso dado (não em UTC)."""
    return datetime.combine(agora.astimezone(fuso).date(), time(0), tzinfo=fuso)


def _com_par(s: Session, status: StatusCasamento) -> set[int]:
    return set(s.scalars(select(Casamento.produto_id).where(Casamento.status == status).distinct()))


def montar_lista(
    s: Session,
    agora: datetime,
    fuso: ZoneInfo,
    novos_por_dia: int,
    embaralhar: Callable[[list], None] = random.shuffle,
) -> ListaDoDia:
    """Antes do sorteio, casados, candidatos e rodízio ficam por id e os novos por (visto_primeiro_em, id).
    `embaralhar` é chamado uma vez por grupo. Um novo além do teto espera os próximos dias (não entra no
    rodízio)."""
    inicio = inicio_do_dia(agora, fuso)
    dia_da_semana = agora.astimezone(fuso).weekday()  # segunda = 0
    ativos = s.execute(
        select(ProdutoLiga.id, ProdutoLiga.url, ProdutoLiga.visto_primeiro_em)
        .where(ProdutoLiga.ativo.is_(True))
        .order_by(ProdutoLiga.id)
    ).all()
    lidos_hoje = set(s.scalars(select(ResumoPreco.produto_id).where(ResumoPreco.coletado_em >= inicio).distinct()))
    com_resumo = set(s.scalars(select(ResumoPreco.produto_id).distinct()))
    casados_ids = _com_par(s, StatusCasamento.CONFIRMADO)
    pendentes_ids = _com_par(s, StatusCasamento.PENDENTE)

    casados, candidatos, novos, rodizio = [], [], [], []
    for produto in ativos:
        if produto.id in lidos_hoje:
            continue
        if produto.id in casados_ids:
            casados.append(produto)
        elif produto.id in pendentes_ids:
            candidatos.append(produto)
        elif produto.id not in com_resumo:
            novos.append(produto)
        elif produto.id % DIAS_DO_RODIZIO == dia_da_semana:
            rodizio.append(produto)
    novos.sort(key=lambda p: (p.visto_primeiro_em, p.id))
    novos = novos[:novos_por_dia]

    grupos = [[(p.id, p.url) for p in grupo] for grupo in (casados, candidatos, novos, rodizio)]
    for grupo in grupos:
        embaralhar(grupo)
    return ListaDoDia(
        produtos=tuple(item for grupo in grupos for item in grupo),
        casados=len(grupos[0]),
        candidatos=len(grupos[1]),
        novos=len(grupos[2]),
        rodizio=len(grupos[3]),
    )
```

- [ ] **Step 5: Rodar os testes da tarefa**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_lista uv run pytest -q -p no:cacheprovider tests/coletor_liga/test_lista_do_dia.py`
Expected: PASS.

- [ ] **Step 6: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_lista uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde.

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/coletor_liga/lista_do_dia.py tests/coletor_liga/test_lista_do_dia.py
git commit -m "feat: LigaMagic daily product list by interest"
```

---

### Task 3: Situação de desafio e esfriamento (lane `li-lista`, depois da Task 2)

**Files:**
- Create: `src/tcg_sniper/coletor_liga/esfriamento.py`
- Modify: `src/tcg_sniper/db/repositorio.py:235-239` (`solicitar_execucao`)
- Test: `tests/coletor_liga/test_esfriamento.py` (novo), `tests/db/test_repositorio.py` (acrescentar)

**Interfaces:**
- Consumes: Task 2 (`lista_do_dia.inicio_do_dia`); `repo.obter_estado`, `repo.retomar`, `repo.pausar_por_desafio`, `repo.iniciar_coleta`, `repo.finalizar_coleta`.
- Produces (módulo `tcg_sniper.coletor_liga.esfriamento`):
  - `TIPOS_LIGA = (TipoColeta.LISTAGEM, TipoColeta.PRODUTOS)`.
  - `@dataclass(frozen=True) class SituacaoDesafio(desafios_hoje: int, esfriando_ate: datetime | None)` com as propriedades `parada_hoje -> bool` (`desafios_hoje >= 2`) e `pausas_dobradas -> bool` (`desafios_hoje >= 1`).
  - `desafios_desde(s: Session, desde: datetime) -> int` (coletas da Liga fechadas `pausada_desafio` com `finalizada_em >= desde`).
  - `situacao_desafio(s: Session, agora: datetime, fuso: ZoneInfo, esfriar_min: int) -> SituacaoDesafio` (abre/usa a linha da Liga em `estado_coletor`: chamar dentro de `s.begin()`).
  - `repo.solicitar_execucao(s, agora, coletor)` só liga `execucao_solicitada` (não mexe em `atualizado_em`).

- [ ] **Step 1: Escrever os testes (falham)**

Crie `tests/coletor_liga/test_esfriamento.py`:

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tcg_sniper.coletor_liga.esfriamento import SituacaoDesafio, desafios_desde, situacao_desafio
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import StatusColeta, TipoColeta

SP = ZoneInfo("America/Sao_Paulo")
DIA = datetime(2026, 10, 13, 0, 0, tzinfo=SP)


def local(h, m=0, dias=0):
    return DIA + timedelta(days=dias, hours=h, minutes=m)


def coleta(s, quando, status=StatusColeta.OK, tipo=TipoColeta.PRODUTOS):
    c = repo.iniciar_coleta(s, tipo, quando)
    if status is not StatusColeta.RODANDO:
        repo.finalizar_coleta(s, c.id, status, 1, 0, quando)
    return c


def desafio(s, quando):
    coleta(s, quando, StatusColeta.PAUSADA_DESAFIO)
    repo.pausar_por_desafio(s, "desafio em /x", quando)


def situacao(s, agora, esfriar=30):
    return situacao_desafio(s, agora, SP, esfriar)


def test_sem_desafio_nada_muda(s):
    atual = situacao(s, local(12))
    assert atual == SituacaoDesafio(0, None)
    assert not atual.parada_hoje and not atual.pausas_dobradas


def test_ainda_pausado_conta_o_desafio_mas_nao_esfria(s):
    desafio(s, local(10, 30))
    atual = situacao(s, local(11))
    assert (atual.desafios_hoje, atual.esfriando_ate, atual.pausas_dobradas) == (1, None, True)


def test_esfria_contado_da_retomada(s):
    desafio(s, local(10, 30))
    repo.retomar(s, local(11))
    assert situacao(s, local(11, 10)).esfriando_ate == local(11, 30)
    assert situacao(s, local(11, 30)).esfriando_ate is None


def test_pedir_execucao_nao_estende_o_esfriamento(s):
    desafio(s, local(10, 30))
    repo.retomar(s, local(11))
    repo.solicitar_execucao(s, local(11, 10))  # "Rodar agora" no meio da espera
    assert situacao(s, local(11, 20)).esfriando_ate == local(11, 30)


def test_coleta_que_comecou_depois_do_desafio_encerra_o_esfriamento(s):
    desafio(s, local(10, 30))
    repo.retomar(s, local(11))
    coleta(s, local(11, 30), StatusColeta.RODANDO)
    assert situacao(s, local(11, 45), esfriar=60).esfriando_ate is None  # sem a coleta, iria até 12:00


def test_esfriar_zero_nao_espera(s):
    desafio(s, local(10, 30))
    repo.retomar(s, local(11))
    assert situacao(s, local(11), esfriar=0).esfriando_ate is None


def test_segundo_desafio_do_dia_para_ate_amanha(s):
    desafio(s, local(10, 30))
    repo.retomar(s, local(11))
    coleta(s, local(11, 30))
    desafio(s, local(13))
    atual = situacao(s, local(13, 5))
    assert (atual.desafios_hoje, atual.parada_hoje) == (2, True)
    assert not situacao(s, local(9, dias=1)).parada_hoje


def test_desafio_antes_da_meia_noite_local_conta_no_dia_anterior(s):
    desafio(s, local(23, 50, dias=-1))  # 02:50 UTC de hoje
    assert situacao(s, local(9)).desafios_hoje == 0
    assert desafios_desde(s, DIA) == 0
    assert desafios_desde(s, DIA - timedelta(days=1)) == 1


def test_desafio_de_ontem_ainda_esfria_a_retomada_de_hoje_sem_dobrar_as_pausas(s):
    desafio(s, local(22, dias=-1))
    repo.retomar(s, local(8))
    atual = situacao(s, local(8, 10))
    assert (atual.desafios_hoje, atual.esfriando_ate, atual.pausas_dobradas) == (0, local(8, 30), False)


def test_desafio_da_amazon_nao_conta(s):
    coleta(s, local(10), StatusColeta.PAUSADA_DESAFIO, TipoColeta.AMAZON)
    assert situacao(s, local(10, 5)) == SituacaoDesafio(0, None)
```

Acrescente a `tests/db/test_repositorio.py` (`T0` e `timedelta` já são importados no arquivo):

```python
def test_pedir_execucao_nao_muda_a_hora_da_ultima_mudanca_de_estado(s):
    repo.retomar(s, T0, solicitar=False)
    repo.solicitar_execucao(s, T0 + timedelta(minutes=10))
    estado = repo.obter_estado(s)
    assert estado.execucao_solicitada and estado.atualizado_em == T0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_lista uv run pytest -q -p no:cacheprovider tests/coletor_liga/test_esfriamento.py tests/db/test_repositorio.py`
Expected: FAIL (`ModuleNotFoundError: ... esfriamento`; `atualizado_em` igual a T0 + 10 min).

- [ ] **Step 3: `solicitar_execucao`**

Em `src/tcg_sniper/db/repositorio.py`, troque `solicitar_execucao` por:

```python
def solicitar_execucao(s: Session, agora: datetime, coletor: str = COLETOR_LIGA) -> None:
    """Pede uma execução já. Não mexe em `atualizado_em`: na Liga ela marca a retomada, de onde conta o
    esfriamento depois de um desafio (um "Rodar agora" não pode estender a espera)."""
    estado = obter_estado(s, agora, coletor)
    estado.execucao_solicitada = True
    s.flush()
```

- [ ] **Step 4: Módulo do esfriamento**

Crie `src/tcg_sniper/coletor_liga/esfriamento.py`:

```python
"""Esfriar depois de um desafio do Cloudflare na LigaMagic.

Tudo sai do banco: os desafios são as coletas da Liga fechadas `pausada_desafio` (tabela `coleta`) e a
espera conta da retomada (`estado_coletor.atualizado_em` da Liga). Um reinício do serviço não zera nada.

- 1º desafio do dia: depois de retomar, o job só começa `esfriar_min` minutos depois, e as pausas entre
  páginas dobram até o fim do dia.
- 2º desafio do dia: nada roda até o dia seguinte (nem "Rodar agora").
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tcg_sniper.coletor_liga.lista_do_dia import inicio_do_dia
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import Coleta, EstadoColetorTipo, StatusColeta, TipoColeta

TIPOS_LIGA = (TipoColeta.LISTAGEM, TipoColeta.PRODUTOS)


@dataclass(frozen=True)
class SituacaoDesafio:
    desafios_hoje: int
    esfriando_ate: datetime | None  # fim da espera depois da retomada; None: não está esfriando

    @property
    def parada_hoje(self) -> bool:
        """2º desafio do dia: nada roda até o dia seguinte."""
        return self.desafios_hoje >= 2

    @property
    def pausas_dobradas(self) -> bool:
        return self.desafios_hoje >= 1


def desafios_desde(s: Session, desde: datetime) -> int:
    return (
        s.scalar(
            select(func.count())
            .select_from(Coleta)
            .where(
                Coleta.tipo.in_(TIPOS_LIGA),
                Coleta.status == StatusColeta.PAUSADA_DESAFIO,
                Coleta.finalizada_em >= desde,
            )
        )
        or 0
    )


def _esfriando_ate(s: Session, agora: datetime, esfriar_min: int) -> datetime | None:
    if esfriar_min <= 0:
        return None
    ultimo = s.scalar(
        select(func.max(Coleta.finalizada_em)).where(
            Coleta.tipo.in_(TIPOS_LIGA), Coleta.status == StatusColeta.PAUSADA_DESAFIO
        )
    )
    if ultimo is None:
        return None
    voltou = s.scalar(
        select(func.count()).select_from(Coleta).where(Coleta.tipo.in_(TIPOS_LIGA), Coleta.iniciada_em > ultimo)
    )
    if voltou:
        return None  # o job já voltou depois do desafio
    estado = repo.obter_estado(s, agora)
    if estado.estado is not EstadoColetorTipo.ATIVO:
        return None  # ainda esperando alguém resolver e retomar
    fim = estado.atualizado_em + timedelta(minutes=esfriar_min)
    return fim if agora < fim else None


def situacao_desafio(s: Session, agora: datetime, fuso: ZoneInfo, esfriar_min: int) -> SituacaoDesafio:
    """Desafios desde a meia-noite no fuso e até quando esfriar. O esfriamento vale para o último desafio
    mesmo de ontem (retomado hoje); "desafios hoje" conta só desde a meia-noite."""
    return SituacaoDesafio(desafios_desde(s, inicio_do_dia(agora, fuso)), _esfriando_ate(s, agora, esfriar_min))
```

- [ ] **Step 5: Rodar os testes da tarefa**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_lista uv run pytest -q -p no:cacheprovider tests/coletor_liga tests/db`
Expected: PASS.

- [ ] **Step 6: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_lista uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde.

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/coletor_liga/esfriamento.py src/tcg_sniper/db/repositorio.py tests/coletor_liga/test_esfriamento.py tests/db/test_repositorio.py
git commit -m "feat: LigaMagic challenge cooldown state derived from the database"
```

---

### Task 4: Etapa 2 pela lista do dia e resumo com os grupos (lane `li-coletor`)

**Files:**
- Modify: `src/tcg_sniper/coletor_liga/produtos.py` (arquivo inteiro, ~81 linhas)
- Modify: `src/tcg_sniper/coletor_liga/execucao.py:32-40` (`ResultadoColeta`), `:86-100` (`dados_resumo`)
- Modify: `src/tcg_sniper/coletor_liga/agendador.py:183` (chamada de `coletar_produtos`)
- Modify: `src/tcg_sniper/avisos/catalogo.py:130-152` (exemplos de `LIGA_COLETA_CONCLUIDA` e `LIGA_COLETA_PARCIAL`)
- Test: `tests/coletor_liga/test_produtos.py`, `tests/coletor_liga/test_agendador.py`, `tests/avisos/test_formato.py`

**Interfaces:**
- Consumes: Task 1 (`Config.produtos_novos_dia`), Task 2 (`montar_lista`, `ListaDoDia.grupos()`).
- Produces:
  - `coletar_produtos(sessoes, navegador, avisador, config, dormir=time.sleep, embaralhar=random.shuffle, agora: datetime | None = None) -> ResultadoColeta | None`; o resultado traz `grupos`.
  - `ResultadoColeta.grupos: str | None = None` (último campo).
  - `dados_resumo`: linha `Produtos: <status> · <ok> de <ok+falha>[ · <grupos>]`.

- [ ] **Step 1: Banco da lane**

Run: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_li_coletor`

- [ ] **Step 2: Escrever os testes (falham)**

Em `tests/coletor_liga/test_produtos.py`:

1. Troque os imports do topo por:

```python
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fakes import (
    T0,
    AvisadorFake,
    NavegadorFake,
    criar_anuncio,
    criar_produto,
    fixture_liga,
    pagina_html,
)
from sqlalchemy import func, select

from tcg_sniper.avisos.catalogo import TipoAviso
from tcg_sniper.coletor_liga.modelos import ErroRede, Resumo
from tcg_sniper.coletor_liga.parsers import parse_produto
from tcg_sniper.coletor_liga.produtos import coletar_produtos
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import (
    Coleta,
    EstadoColetorTipo,
    PrecoAtualLiga,
    ProdutoLiga,
    ResumoPreco,
    StatusCasamento,
    StatusColeta,
    TipoColeta,
)
```

(mantenha os imports que o arquivo já usa e o ruff apontar como faltando).

2. Troque o helper `coletar` por:

```python
def coletar(sessoes, config, paginas, pausas=None, agora=None):
    navegador = NavegadorFake(paginas)
    avisador = AvisadorFake()
    resultado = coletar_produtos(
        sessoes,
        navegador,
        avisador,
        config,
        dormir=(pausas if pausas is not None else []).append,
        embaralhar=lambda lista: None,
        agora=agora,
    )
    return resultado, navegador, avisador
```

3. Acrescente ao fim do arquivo:

```python
SP = ZoneInfo("America/Sao_Paulo")
QUARTA = datetime(2026, 10, 14, 12, 0, tzinfo=SP)
ANTIGO = QUARTA - timedelta(days=10)


def lido_em(s, produto, quando):
    c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, quando)
    repo.gravar_precos_produto(s, c.id, produto.id, Resumo(None, None, None, 1), quando)


def test_le_so_a_lista_do_dia_e_resume_os_grupos(sessoes, config):
    with sessoes() as s, s.begin():
        casado = criar_produto(s, "casado")
        lido_em(s, casado, ANTIGO)
        criar_anuncio(s, "B000000001", produto=casado, status=StatusCasamento.CONFIRMADO)
        candidato = criar_produto(s, "candidato")
        lido_em(s, candidato, ANTIGO)
        criar_anuncio(s, "B000000002", produto=candidato, status=StatusCasamento.PENDENTE)
        novo = criar_produto(s, "novo")
        velhos = [criar_produto(s, f"velho{i}") for i in range(7)]
        for v in velhos:
            lido_em(s, v, ANTIGO)
        [do_dia] = [v for v in velhos if v.id % 7 == QUARTA.weekday()]
        urls = [p.url for p in (casado, candidato, novo, do_dia)]
    paginas = {u: pagina_html(HTML_OK, url=u) for u in urls}
    resultado, navegador, _ = coletar(sessoes, config, paginas, agora=QUARTA)
    assert navegador.visitadas == urls  # os outros 6 velhos ficam para outros dias da semana
    assert (resultado.status, resultado.produtos_ok, resultado.produtos_falha) == (StatusColeta.OK, 4, 0)
    assert resultado.grupos == "casados 1, candidatos 1, novos 1, rodízio 1"


def test_retomar_continua_de_onde_parou_sem_reler_os_lidos_hoje(sessoes, config):
    urls = preparar(sessoes, "a", "b", "c")
    navegador = NavegadorFake(
        {urls["a"]: pagina_html(HTML_OK), urls["b"]: [DESAFIO, pagina_html(HTML_OK)], urls["c"]: pagina_html(HTML_OK)}
    )

    def rodar():
        return coletar_produtos(
            sessoes, navegador, AvisadorFake(), config, dormir=[].append, embaralhar=lambda lista: None
        )

    assert rodar().status is StatusColeta.PAUSADA_DESAFIO
    with sessoes() as s, s.begin():
        repo.retomar(s, repo.agora_utc())
    segundo = rodar()
    assert navegador.visitadas == [urls["a"], urls["b"], urls["b"], urls["c"]]  # "a" não é relido
    assert (segundo.status, segundo.produtos_ok) == (StatusColeta.OK, 2)
    assert segundo.grupos == "casados 0, candidatos 0, novos 2, rodízio 0"


def test_lista_vazia_fecha_ok_sem_abrir_pagina(sessoes, config):
    preparar(sessoes, inativos=("z",))
    resultado, navegador, avisador = coletar(sessoes, config, {})
    assert navegador.visitadas == [] and avisador.mensagens == []
    assert (resultado.status, resultado.produtos_ok, resultado.produtos_falha) == (StatusColeta.OK, 0, 0)
    assert resultado.grupos == "casados 0, candidatos 0, novos 0, rodízio 0"


def test_teto_de_novos_vem_da_configuracao(sessoes, config):
    with sessoes() as s, s.begin():
        novos = [criar_produto(s, f"n{i}", agora=T0 - timedelta(days=i)) for i in range(3)]  # n2 é o mais antigo
    paginas = {p.url: pagina_html(HTML_OK, url=p.url) for p in novos}
    c = config.model_copy(update={"produtos_novos_dia": 2})
    _, navegador, _ = coletar(sessoes, c, paginas)
    assert navegador.visitadas == [novos[2].url, novos[1].url]
```

Em `tests/coletor_liga/test_agendador.py`:

1. Em `test_job_completo_envia_resumo` e em `test_job_so_produtos_envia_resumo_sem_listagens`, troque `"Produtos: ok · 0 ok · 0 falhas"` por `"Produtos: ok · 0 de 0 · casados 0, candidatos 0, novos 0, rodízio 0"`.
2. Em `test_job_com_etapa_parcial_avisa_coleta_parcial`, troque `"Produtos: parcial · 3 ok · 1 falhas"` por `"Produtos: parcial · 3 de 4"`.
3. Acrescente ao fim do arquivo:

```python
def test_resumo_mostra_a_lista_do_dia(engine, sessoes, config, monkeypatch):
    from tcg_sniper.coletor_liga import agendador as modulo

    resultado = ResultadoColeta(1, StatusColeta.PARCIAL, 480, 2, grupos="casados 52, candidatos 18, novos 100, rodízio 312")
    monkeypatch.setattr(modulo, "coletar_produtos", lambda *_a, **_k: resultado)
    a, avisador = agendador_resumo(engine, sessoes, config, NavegadorFake({}))
    a.executar_job(incluir_listagens=False)
    [(_, dados)] = resumos(avisador)
    assert dados.linhas[0] == "Produtos: parcial · 480 de 482 · casados 52, candidatos 18, novos 100, rodízio 312"


def test_lista_do_dia_usa_o_relogio_do_agendador(engine, sessoes, config, monkeypatch):
    from tcg_sniper.coletor_liga import agendador as modulo

    vistos = []

    def falso(*_a, **k):
        vistos.append(k["agora"])
        return ResultadoColeta(1, StatusColeta.OK, 0, 0)

    monkeypatch.setattr(modulo, "coletar_produtos", falso)
    a, _ = agendador_resumo(engine, sessoes, config, NavegadorFake({}))
    a.executar_job(incluir_listagens=False)
    assert vistos == [local(TERCA, 10, 40)]
```

Em `tests/avisos/test_formato.py`, no dicionário `ESPERADOS`, troque as entradas `LIGA_COLETA_CONCLUIDA` e `LIGA_COLETA_PARCIAL` por:

```python
    TipoAviso.LIGA_COLETA_CONCLUIDA: (
        "✅ *Liga · coleta concluída · 18/10*\n"
        "• Listagens: ok · 20 de 20 categorias · 3 produtos novos\n"
        "• Produtos: ok · 482 de 482 · casados 52, candidatos 18, novos 100, rodízio 312\n"
        "• Duração: 2 h 41 min\n"
        "_18/10 10:42 · coletor Liga_"
    ),
    TipoAviso.LIGA_COLETA_PARCIAL: (
        "🟡 *Liga · coleta parcial · 18/10*\n"
        "• Listagens: ok · 20 de 20 categorias · 0 produtos novos\n"
        "• Produtos: parcial · 450 de 482 · casados 52, candidatos 18, novos 100, rodízio 312\n"
        "• Duração: 2 h 35 min\n"
        "\n"
        "*O que fazer:* Nada urgente; se repetir, veja Admin → Logs → LigaMagic.\n"
        "_18/10 10:42 · coletor Liga_"
    ),
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_coletor uv run pytest -q -p no:cacheprovider tests/coletor_liga/test_produtos.py tests/coletor_liga/test_agendador.py tests/avisos/test_formato.py`
Expected: FAIL (`unexpected keyword argument 'agora'`, `unexpected keyword argument 'grupos'`, textos diferentes).

- [ ] **Step 4: `ResultadoColeta` e resumo**

Em `src/tcg_sniper/coletor_liga/execucao.py`, acrescente o campo ao fim de `ResultadoColeta`:

```python
    # Grupos da lista do dia ("casados 52, candidatos 18, novos 100, rodízio 312"); só na etapa dos produtos.
    grupos: str | None = None
```

e troque `dados_resumo` por:

```python
def dados_resumo(
    dia: date, listagens: ResultadoColeta | None, produtos: ResultadoColeta, duracao: timedelta
) -> Dados:
    """Resumo de um job concluído. `listagens` é None quando o job rodou só os produtos. Nas listagens,
    ok/falha contam categorias; nos produtos, "<ok> de <lidos>" e os grupos da lista do dia."""
    linhas = []
    if listagens is not None:
        total = listagens.produtos_ok + listagens.produtos_falha
        linhas.append(
            f"Listagens: {listagens.status.value} · {listagens.produtos_ok} de {total} categorias · "
            f"{listagens.novos} produtos novos"
        )
    linha = (
        f"Produtos: {produtos.status.value} · {produtos.produtos_ok} de "
        f"{produtos.produtos_ok + produtos.produtos_falha}"
    )
    if produtos.grupos:
        linha += f" · {produtos.grupos}"
    linhas.append(linha)
    linhas.append(f"Duração: {formatar_duracao(duracao)}")
    return Dados(titulo_extra=f"{dia:%d/%m}", linhas=tuple(linhas))
```

- [ ] **Step 5: Etapa dos produtos**

Troque `src/tcg_sniper/coletor_liga/produtos.py` inteiro por:

```python
"""Etapa 2 do job diário: abre a página dos produtos da lista do dia (`lista_do_dia`).

Grava o resumo histórico ("Preço Médio de Venda no Marketplace": mín, médio, máx) e o
número de lojas atual (`resumo_preco` append-only + grupo "resumo" de `preco_atual_liga`).
"""

import logging
import random
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.avisos.servico import Avisador
from tcg_sniper.coletor_liga.execucao import (
    DesafioDetectado,
    Dormir,
    ResultadoColeta,
    abrir_pagina,
    concluir_coleta,
    encerrar_por_erro,
    iniciar_se_ativo,
    pausa_humana,
    registrar_desafio,
    salvar_html_falha,
)
from tcg_sniper.coletor_liga.lista_do_dia import montar_lista
from tcg_sniper.coletor_liga.modelos import ErroParser, ErroRede
from tcg_sniper.coletor_liga.navegador import Navegador
from tcg_sniper.coletor_liga.parsers import parse_produto
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import StatusColeta, TipoColeta

log = logging.getLogger(__name__)

DESCRICAO = "Coleta dos produtos ativos"


def coletar_produtos(
    sessoes: sessionmaker[Session],
    navegador: Navegador,
    avisador: Avisador,
    config: Config,
    dormir: Dormir = time.sleep,
    embaralhar: Callable[[list], None] = random.shuffle,
    agora: datetime | None = None,
) -> ResultadoColeta | None:
    """`agora` decide o dia da lista (rodízio e "lido hoje"); padrão: a hora atual."""
    coleta_id = iniciar_se_ativo(sessoes, TipoColeta.PRODUTOS)
    if coleta_id is None:
        return None
    with sessoes() as s:
        lista = montar_lista(s, agora or repo.agora_utc(), config.zona, config.produtos_novos_dia, embaralhar)
    grupos = lista.grupos()
    log.info("coleta dos produtos %s: %d na lista do dia (%s)", coleta_id, len(lista.produtos), grupos)

    ok = falha = 0
    try:
        for indice, (produto_id, url) in enumerate(lista.produtos):
            if indice > 0:
                pausa_humana(config, dormir)
            try:
                pagina = abrir_pagina(navegador, url, dormir)
            except DesafioDetectado:
                registrar_desafio(sessoes, avisador, coleta_id, url, ok, falha)
                return ResultadoColeta(coleta_id, StatusColeta.PAUSADA_DESAFIO, ok, falha, grupos=grupos)
            except ErroRede as erro:
                log.warning("produto %s falhou por rede: %s", produto_id, erro)
                falha += 1
                continue
            try:
                resumo = parse_produto(pagina.html)
            except ErroParser as erro:
                caminho = salvar_html_falha(config, f"produto-{coleta_id}-{produto_id}", pagina.html)
                log.warning("parser falhou no produto %s (%s); HTML em %s", produto_id, erro, caminho)
                falha += 1
                continue
            with sessoes() as s, s.begin():
                repo.gravar_precos_produto(s, coleta_id, produto_id, resumo, repo.agora_utc())
            ok += 1
    except Exception as erro:  # noqa: BLE001 - erro inesperado fecha a coleta como falha
        return replace(encerrar_por_erro(sessoes, avisador, coleta_id, DESCRICAO, erro, ok, falha), grupos=grupos)
    resultado = concluir_coleta(sessoes, avisador, config, coleta_id, DESCRICAO, "produtos", ok, falha)
    return replace(resultado, grupos=grupos)
```

- [ ] **Step 6: Agendador passa o relógio**

Em `src/tcg_sniper/coletor_liga/agendador.py`, em `_coletar`, troque a chamada de `coletar_produtos` por:

```python
        produtos = coletar_produtos(
            self._sessoes, navegador, self._avisador, self._config, self._dormir, agora=self._relogio()
        )
```

- [ ] **Step 7: Exemplos do catálogo**

Em `src/tcg_sniper/avisos/catalogo.py`, nos `Dados` de exemplo de `LIGA_COLETA_CONCLUIDA`, troque as linhas de produtos e duração por `"Produtos: ok · 482 de 482 · casados 52, candidatos 18, novos 100, rodízio 312"` e `"Duração: 2 h 41 min"`; nos de `LIGA_COLETA_PARCIAL`, por `"Produtos: parcial · 450 de 482 · casados 52, candidatos 18, novos 100, rodízio 312"` e `"Duração: 2 h 35 min"` (o resto igual).

- [ ] **Step 8: Rodar os testes da tarefa**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_coletor uv run pytest -q -p no:cacheprovider tests/coletor_liga tests/avisos`
Expected: PASS (inclusive `test_coleta_ok_grava_resumos_e_pausa_entre_produtos`: os três produtos sem resumo são "novos" e saem na ordem do id).

- [ ] **Step 9: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_coletor uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde. Um teste do admin que confira o texto de exemplo antigo do resumo ("412 ok · 0 falhas") passa a conferir o novo.

- [ ] **Step 10: Commit**

```bash
git add src/tcg_sniper/coletor_liga src/tcg_sniper/avisos/catalogo.py tests/coletor_liga tests/avisos tests/admin
git commit -m "feat: LigaMagic product step reads only the daily list"
```

---

### Task 5: Esfriar no agendador, pausas em dobro e aviso do 1º/2º desafio (lane `li-coletor`, depois da Task 4)

**Files:**
- Modify: `src/tcg_sniper/coletor_liga/agendador.py:12-27` (imports e `TIPOS_LIGA`), `:101-133` (`tick`), `:168-198` (`_coletar`)
- Modify: `src/tcg_sniper/coletor_liga/execucao.py:79-83` (`dados_desafio`), `:103-118` (`registrar_desafio`)
- Modify: `src/tcg_sniper/coletor_liga/listagens.py:81`, `src/tcg_sniper/coletor_liga/produtos.py` (chamada de `registrar_desafio`)
- Modify: `src/tcg_sniper/avisos/catalogo.py:158-162` (`LIGA_DESAFIO`)
- Test: `tests/coletor_liga/test_agendador.py`, `tests/coletor_liga/test_produtos.py`, `tests/coletor_liga/test_listagens.py`, `tests/avisos/test_formato.py`

**Interfaces:**
- Consumes: Task 1 (`Config.esfriar_desafio_min`), Task 3 (`TIPOS_LIGA`, `situacao_desafio`, `desafios_desde`, `SituacaoDesafio.parada_hoje/pausas_dobradas/esfriando_ate`), Task 2 (`inicio_do_dia`).
- Produces:
  - `Agendador.tick()`: esfriando → `None` sem consumir o pedido; parada → `None`, pedido descartado, atrasada limpa.
  - `Agendador._config_do_job() -> Config` (pausas × 2 depois de um desafio hoje).
  - `registrar_desafio(sessoes, avisador, config, coleta_id, url, ok, falha) -> None` (novo parâmetro `config`, 3º posicional).
  - `dados_desafio(url: str, desafios_hoje: int, esfriar_min: int) -> Dados` (três linhas).
  - `agendador.TIPOS_LIGA` continua existindo (vem de `esfriamento`).

- [ ] **Step 1: Escrever os testes (falham)**

Em `tests/coletor_liga/test_agendador.py`:

1. Acrescente `criar_produto` ao import de `fakes`.
2. Em `test_retomar_roda_no_mesmo_dia_reaproveitando_o_navegador`, troque o trecho que cria o agendador e retoma por:

```python
    relogio = Relogio(datetime.now(UTC))
    a = agendador_com_fabrica(engine, sessoes, c, fabrica, relogio)
    a.executar_job(incluir_listagens=True)
    with sessoes() as s, s.begin():
        assert repo.obter_estado(s).estado.value == "pausado_desafio"
    assert a.tick() is None  # pausado: não roda nada

    with sessoes() as s, s.begin():
        repo.retomar(s, repo.agora_utc())
    assert a.tick() is None  # esfriando: 30 min contados da retomada
    relogio.agora = datetime.now(UTC) + timedelta(minutes=31)
    assert a.tick() == "solicitado"
```

(o resto do teste igual) e acrescente ao docstring: "depois do esfriamento".
3. Em `test_navegador_mantido_morto_e_trocado_uma_vez`, do mesmo jeito: `relogio = Relogio(datetime.now(UTC))`, `a = agendador_com_fabrica(engine, sessoes, c, fabrica, relogio)` e, depois do `repo.retomar`, `relogio.agora = datetime.now(UTC) + timedelta(minutes=31)` antes de `assert a.tick() == "solicitado"`.
4. Acrescente ao fim do arquivo:

```python
def desafio(sessoes, quando):
    coleta(sessoes, TipoColeta.PRODUTOS, quando, status=StatusColeta.PAUSADA_DESAFIO)


def retomar_em(sessoes, quando, solicitar=True):
    with sessoes() as s, s.begin():
        repo.retomar(s, quando, solicitar=solicitar)


def primeiro_desafio_retomado_as_11(sessoes):
    """Job de hoje com listagens ok às 10:05, desafio nos produtos às 10:30 e Retomar às 11:00."""
    job_ok(sessoes, ONTEM, 14)
    coleta(sessoes, TipoColeta.LISTAGEM, local(TERCA, 10, 5))
    desafio(sessoes, local(TERCA, 10, 30))
    retomar_em(sessoes, local(TERCA, 11, 0))


def test_primeiro_desafio_so_roda_depois_de_esfriar_contado_da_retomada(engine, sessoes, config):
    primeiro_desafio_retomado_as_11(sessoes)
    relogio = Relogio(local(TERCA, 11, 0))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    for minuto in (0, 15, 29):
        relogio.agora = local(TERCA, 11, minuto)
        assert a.tick() is None
    relogio.agora = local(TERCA, 11, 30)
    assert a.tick() == "solicitado"
    assert chamadas == [False]  # listagens já ok hoje: só os produtos


def test_rodar_agora_no_esfriamento_nao_estende_a_espera(engine, sessoes, config):
    primeiro_desafio_retomado_as_11(sessoes)
    relogio = Relogio(local(TERCA, 11, 10))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    with sessoes() as s, s.begin():
        repo.solicitar_execucao(s, local(TERCA, 11, 10))
    assert a.tick() is None
    relogio.agora = local(TERCA, 11, 29)
    assert a.tick() is None
    relogio.agora = local(TERCA, 11, 30)
    assert a.tick() == "solicitado"


def test_reinicio_no_meio_do_esfriamento_mantem_a_espera(engine, sessoes, config):
    primeiro_desafio_retomado_as_11(sessoes)
    antes, _ = agendador(engine, sessoes, config, Relogio(local(TERCA, 11, 5)), [])
    assert antes.tick() is None
    relogio = Relogio(local(TERCA, 11, 15))  # o serviço reiniciou
    chamadas = []
    depois, _ = agendador(engine, sessoes, config, relogio, chamadas)
    depois.inicializar()
    assert depois.tick() is None
    relogio.agora = local(TERCA, 11, 30)
    assert depois.tick() == "solicitado"
    assert chamadas == [False]


def test_horario_do_dia_durante_o_esfriamento_espera_o_fim(engine, sessoes, config):
    job_ok(sessoes, ONTEM, 14)
    desafio(sessoes, local(ONTEM, 23, 0))
    retomar_em(sessoes, local(TERCA, 9, 50), solicitar=False)  # "Ligar" sem pedir execução
    salvar_liga(sessoes, config, coleta_hora=time(10, 0), coleta_jitter_min=0)
    relogio = Relogio(local(TERCA, 10, 5))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() is None  # passou das 10:00, mas esfria até 10:20
    relogio.agora = local(TERCA, 10, 20)
    assert a.tick() == "agendado"
    assert chamadas == [True]


def test_segundo_desafio_nada_roda_ate_amanha_nem_com_rodar_agora(engine, sessoes, config):
    job_ok(sessoes, TERCA - timedelta(days=2), 10)  # > 24 h: inicializar arma uma execução atrasada
    coleta(sessoes, TipoColeta.LISTAGEM, local(TERCA, 10, 5))
    desafio(sessoes, local(TERCA, 10, 30))
    desafio(sessoes, local(TERCA, 12, 0))
    retomar_em(sessoes, local(TERCA, 12, 10))  # Retomar pede execução
    relogio = Relogio(local(TERCA, 12, 41))
    chamadas = []
    a, _ = agendador(engine, sessoes, config, relogio, chamadas)
    a.inicializar()
    assert a.tick() is None
    with sessoes() as s, s.begin():
        assert repo.obter_estado(s).execucao_solicitada is False  # o pedido foi descartado
        repo.solicitar_execucao(s, local(TERCA, 13, 0))  # "Rodar agora"
    relogio.agora = local(TERCA, 13, 1)
    assert a.tick() is None
    relogio.agora = local(TERCA + timedelta(days=1), 0, 30)
    assert a.tick() is None  # nem o pedido nem a atrasada rodam à meia-noite
    relogio.agora = local(TERCA + timedelta(days=1), 10, 31)
    assert a.tick() == "agendado"
    assert chamadas == [True]


HTML_PRODUTO = fixture_liga("produto_varios_vendedores")


def pausas_do_job(engine, sessoes, config, agora):
    """Roda um job só de produtos (dois produtos novos) e devolve as pausas entre eles."""
    with sessoes() as s, s.begin():
        urls = [criar_produto(s, nome).url for nome in ("a", "b")]
    navegador = NavegadorFake({u: pagina_html(HTML_PRODUTO, url=u) for u in urls})
    pausas = []
    c = config.model_copy(update={"pausa_min_s": 10, "pausa_max_s": 10})
    a = Agendador(
        engine, sessoes, lambda: nullcontext(navegador), AvisadorFake(), c,
        relogio=Relogio(agora), rng=random.Random(1), dormir=pausas.append,
    )
    a.executar_job(incluir_listagens=False)
    return pausas


def test_pausas_dobradas_no_resto_do_dia_depois_do_primeiro_desafio(engine, sessoes, config):
    desafio(sessoes, local(TERCA, 9, 0))
    retomar_em(sessoes, local(TERCA, 9, 10))
    assert pausas_do_job(engine, sessoes, config, local(TERCA, 10, 40)) == [20.0]


def test_no_dia_seguinte_as_pausas_voltam_ao_normal(engine, sessoes, config):
    desafio(sessoes, local(ONTEM, 9, 0))
    desafio(sessoes, local(ONTEM, 12, 0))
    retomar_em(sessoes, local(ONTEM, 12, 10))
    assert pausas_do_job(engine, sessoes, config, local(TERCA, 10, 40)) == [10.0]
```

Em `tests/coletor_liga/test_produtos.py`, acrescente ao fim:

```python
def test_aviso_do_primeiro_desafio_do_dia_diz_que_volta_depois_de_esfriar(sessoes, config):
    urls = preparar(sessoes, "a")
    _, _, avisador = coletar(sessoes, config, {urls["a"]: DESAFIO})
    [dados] = avisador.dados(TipoAviso.LIGA_DESAFIO)
    assert dados.linhas[1:] == (
        "A coleta fica pausada até você retomar",
        "1º desafio de hoje: volta 30 min depois de você retomar, com pausas em dobro até o fim do dia",
    )


def test_aviso_sem_esfriar_diz_que_volta_logo(sessoes, config):
    urls = preparar(sessoes, "a")
    c = config.model_copy(update={"esfriar_desafio_min": 0})
    _, _, avisador = coletar(sessoes, c, {urls["a"]: DESAFIO})
    [dados] = avisador.dados(TipoAviso.LIGA_DESAFIO)
    assert dados.linhas[2] == "1º desafio de hoje: volta logo depois de você retomar, com pausas em dobro até o fim do dia"


def test_aviso_do_segundo_desafio_do_dia_diz_que_volta_amanha(sessoes, config):
    urls = preparar(sessoes, "a")
    with sessoes() as s, s.begin():
        antes = repo.agora_utc() - timedelta(seconds=1)
        c = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, antes)
        repo.finalizar_coleta(s, c.id, StatusColeta.PAUSADA_DESAFIO, 0, 0, antes, erro="desafio em /x")
    _, _, avisador = coletar(sessoes, config, {urls["a"]: DESAFIO})
    [dados] = avisador.dados(TipoAviso.LIGA_DESAFIO)
    assert dados.linhas[2] == "2º desafio de hoje: depois de retomar, a coleta só volta amanhã, no horário de sempre"
```

Em `tests/coletor_liga/test_listagens.py`, em `test_desafio_na_segunda_categoria_pausa_e_avisa`, troque a asserção de `desafio.linhas` por:

```python
    assert desafio.linhas == (
        "Página: /listagem?categ=11",
        "A coleta fica pausada até você retomar",
        "1º desafio de hoje: volta 30 min depois de você retomar, com pausas em dobro até o fim do dia",
    )
```

Em `tests/avisos/test_formato.py`, troque a entrada `LIGA_DESAFIO` de `ESPERADOS` por:

```python
    TipoAviso.LIGA_DESAFIO: (
        "🔴 *Liga · desafio do Cloudflare*\n"
        "• Página: /?view=cards/search&card=categ%3D10\n"
        "• A coleta fica pausada até você retomar\n"
        "• 1º desafio de hoje: volta 30 min depois de você retomar, com pausas em dobro até o fim do dia\n"
        "\n"
        "*O que fazer:* Resolva no noVNC da Liga (porta 6080) e depois Admin → Serviços → LigaMagic → Retomar.\n"
        "_18/10 10:42 · coletor Liga_"
    ),
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_coletor uv run pytest -q -p no:cacheprovider tests/coletor_liga tests/avisos/test_formato.py`
Expected: FAIL (o agendador roda durante o esfriamento e depois do 2º desafio; pausas `[10.0]` em vez de `[20.0]`; aviso com duas linhas).

- [ ] **Step 3: Aviso do desafio**

Em `src/tcg_sniper/coletor_liga/execucao.py`, acrescente aos imports `from tcg_sniper.coletor_liga.esfriamento import desafios_desde` e `from tcg_sniper.coletor_liga.lista_do_dia import inicio_do_dia`, e troque `dados_desafio` e `registrar_desafio` por:

```python
def dados_desafio(url: str, desafios_hoje: int, esfriar_min: int) -> Dados:
    """Só o caminho da página (sem o domínio): o aviso diz onde parou, a ação diz onde resolver. A 3ª linha
    diz o que acontece depois do Retomar (1º desafio do dia: esfria; 2º: só amanhã)."""
    partes = urlsplit(url)
    pagina = (partes.path or "/") + (f"?{partes.query}" if partes.query else "")
    if desafios_hoje >= 2:
        efeito = "2º desafio de hoje: depois de retomar, a coleta só volta amanhã, no horário de sempre"
    elif esfriar_min > 0:
        efeito = f"1º desafio de hoje: volta {esfriar_min} min depois de você retomar, com pausas em dobro até o fim do dia"
    else:
        efeito = "1º desafio de hoje: volta logo depois de você retomar, com pausas em dobro até o fim do dia"
    return Dados(linhas=(f"Página: {pagina}", "A coleta fica pausada até você retomar", efeito))


def registrar_desafio(
    sessoes: sessionmaker[Session],
    avisador: Avisador,
    config: Config,
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
        desafios_hoje = desafios_desde(s, inicio_do_dia(agora, config.zona))  # já conta este
    log.warning("desafio do Cloudflare em %s (%dº de hoje); coletor pausado", url, desafios_hoje)
    avisador.avisar(TipoAviso.LIGA_DESAFIO, CHAVE_GERAL, dados_desafio(url, desafios_hoje, config.esfriar_desafio_min))
```

Em `src/tcg_sniper/coletor_liga/listagens.py` (linha ~81) e em `src/tcg_sniper/coletor_liga/produtos.py`, troque `registrar_desafio(sessoes, avisador, coleta_id, url, ok, falha)` por `registrar_desafio(sessoes, avisador, config, coleta_id, url, ok, falha)`.

Em `src/tcg_sniper/avisos/catalogo.py`, troque a entrada `LIGA_DESAFIO` por:

```python
    TipoAviso.LIGA_DESAFIO: _problema(
        F, "Liga · desafio do Cloudflare", LIGA,
        "A LigaMagic pediu verificação; a coleta fica pausada. Depois do 1º do dia volta mais devagar, após "
        "esfriar; depois do 2º, só no dia seguinte.",
        "Resolva no noVNC da Liga (porta 6080) e depois Admin → Serviços → LigaMagic → Retomar.",
        Dados(
            linhas=(
                "Página: /?view=cards/search&card=categ%3D10",
                "A coleta fica pausada até você retomar",
                "1º desafio de hoje: volta 30 min depois de você retomar, com pausas em dobro até o fim do dia",
            )
        ),
    ),
```

- [ ] **Step 4: Agendador**

Em `src/tcg_sniper/coletor_liga/agendador.py`:

1. Acrescente o import `from tcg_sniper.coletor_liga.esfriamento import TIPOS_LIGA, situacao_desafio` e apague a linha `TIPOS_LIGA = (TipoColeta.LISTAGEM, TipoColeta.PRODUTOS)` (o admin continua importando `agendador.TIPOS_LIGA`; `TipoColeta` continua importado, o `tick` ainda o usa).
2. Em `tick`, troque o bloco `with self._sessoes() as s, s.begin(): ...` (do `if repo.obter_estado` até `ultima_listagem_ok = ...`) por:

```python
        with self._sessoes() as s, s.begin():
            if repo.obter_estado(s, agora).estado != EstadoColetorTipo.ATIVO:
                return None
            desafio = situacao_desafio(s, agora, self._config.zona, self._config.esfriar_desafio_min)
            if desafio.parada_hoje:
                # 2º desafio do dia: nada roda até amanhã. O pedido (Retomar, Rodar agora) é descartado e a
                # execução atrasada também, para nada sair à meia-noite; amanhã vale o horário normal.
                if repo.consumir_solicitacao(s, agora):
                    log.info("pedido de execução descartado: parada até amanhã (2º desafio do dia)")
                self._atrasada_em = None
                return None
            if desafio.esfriando_ate is not None:
                # Esfriando depois de um desafio: nada roda (nem pedido, nem atrasada, nem o horário do
                # dia). O pedido fica guardado; a atrasada e o horário só são adiados.
                return None
            solicitada = repo.consumir_solicitacao(s, agora)
            rodou_hoje = repo.coleta_iniciada_desde(s, TipoColeta.LISTAGEM, inicio_do_dia)
            ultima_listagem_ok = repo.ultima_coleta_sucesso(s, TipoColeta.LISTAGEM)
```

3. Acrescente o método (antes de `_coletar`):

```python
    def _config_do_job(self) -> Config:
        """Depois de um desafio hoje, o job inteiro usa as pausas em dobro (listagens, cliques e produtos)."""
        with self._sessoes() as s, s.begin():
            desafio = situacao_desafio(s, self._relogio(), self._config.zona, self._config.esfriar_desafio_min)
        if not desafio.pausas_dobradas:
            return self._config
        log.info("desafio hoje: pausas em dobro até o fim do dia")
        return self._config.model_copy(
            update={"pausa_min_s": self._config.pausa_min_s * 2, "pausa_max_s": self._config.pausa_max_s * 2}
        )
```

4. Troque `_coletar` por:

```python
    def _coletar(self, navegador: Navegador, incluir_listagens: bool) -> bool:
        """Roda as etapas do job. Devolve True se parou num desafio do Cloudflare. Se o job vai até o fim
        sem desafio, sem etapa interrompida por erro e sem etapa que falhou, avisa "concluída" (ou
        "parcial") e resolve as falhas e erros abertos. O job só roda com a Liga ativa: um desafio aberto
        foi resolvido (retomada). Depois de um desafio hoje, as pausas são em dobro."""
        inicio = self._relogio()
        config = self._config_do_job()
        self._avisador.resolver(TipoAviso.LIGA_DESAFIO, CHAVE_GERAL)
        listagens = None
        if incluir_listagens:
            listagens = coletar_listagens(self._sessoes, navegador, self._avisador, config, self._dormir)
            if listagens is None:
                return False
            if listagens.status is StatusColeta.PAUSADA_DESAFIO:
                return True
            pausa_humana(config, self._dormir)
        produtos = coletar_produtos(
            self._sessoes, navegador, self._avisador, config, self._dormir, agora=self._relogio()
        )
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

- [ ] **Step 5: Rodar os testes da tarefa**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_coletor uv run pytest -q -p no:cacheprovider tests/coletor_liga tests/avisos`
Expected: PASS.

- [ ] **Step 6: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_coletor uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde. Um teste do admin que confira o exemplo antigo do aviso de desafio passa a conferir as três linhas.

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/coletor_liga src/tcg_sniper/avisos/catalogo.py tests/coletor_liga tests/avisos tests/admin
git commit -m "feat: LigaMagic cools down after a challenge and stops for the day after the second"
```

---

### Task 6: Admin — Configurações, Serviços e Dashboard (lane `li-admin`)

**Files:**
- Modify: `src/tcg_sniper/admin/formularios_config.py:47-76` (`CAMPOS_LIGA`, `ROTULOS_LIGA`, `EXPLICACOES_LIGA`), `:126-134` (laço dos inteiros em `validar_liga`)
- Modify: `src/tcg_sniper/admin/templates/configuracoes.html:13-15` (explicação da seção LigaMagic)
- Modify: `src/tcg_sniper/admin/app.py:34` (import), `:84-110` (`MENSAGENS_SERVICOS`), `:373-408` (contexto de `/servicos`), `:415-427` (`/retomar`, `/rodar-agora`)
- Modify: `src/tcg_sniper/admin/templates/servicos.html:46-60` (card ativo da LigaMagic)
- Modify: `src/tcg_sniper/admin/consultas_painel.py:20` (import), `:166-169` (`_saude_liga`)
- Modify: `src/tcg_sniper/admin/static/admin.css` (regenerado)
- Test: `tests/admin/test_admin_config_tela.py`, `tests/admin/test_admin_servicos.py`, `tests/admin/test_consultas_painel.py`

**Interfaces:**
- Consumes: Task 1 (`LIMITES_CONFIG_LIGA`, colunas, `Config.esfriar_desafio_min`), Task 3 (`situacao_desafio(s, agora, fuso, esfriar_min) -> SituacaoDesafio` com `parada_hoje`, `esfriando_ate`); macros `selo`, `chave`, `aviso`; `request.state.config` (config efetiva).
- Produces: campos `produtos_novos_dia` e `esfriar_desafio_min` em Configurações → LigaMagic; mensagens `liga_esfriando`, `liga_parada_hoje`, `retomar_esfriando`, `retomar_parada`; contexto `liga_parada: bool`, `liga_esfriando_ate: str | None` ("HH:MM") em `/servicos`; card do Dashboard com situação `parcial` e selos "esfriando"/"parada até amanhã".

- [ ] **Step 1: Banco da lane**

Run: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_li_admin`

- [ ] **Step 2: Escrever os testes (falham)**

Em `tests/admin/test_admin_config_tela.py`, acrescente ao dicionário `LIGA`:

```python
    "produtos_novos_dia": "100",
    "esfriar_desafio_min": "30",
```

e, ao fim do arquivo:

```python
def test_salvar_esfriar_e_novos_por_dia(cliente, sessoes, config):
    dados = {**LIGA, "esfriar_desafio_min": "45", "produtos_novos_dia": "250"}
    assert cliente.post("/configuracoes/liga", data=dados, follow_redirects=False).status_code == 303
    with sessoes() as s:
        liga = repo.obter_config_liga(s, config)
    assert (liga.esfriar_desafio_min, liga.produtos_novos_dia) == (45, 250)


def test_esfriar_fora_do_limite_nao_grava(cliente):
    r = cliente.post("/configuracoes/liga", data={**LIGA, "esfriar_desafio_min": "241"})
    assert r.status_code == 400 and "O valor deve ficar entre 0 e 240." in r.text


def test_aba_ligamagic_explica_a_leitura_por_interesse(cliente):
    texto = cliente.get("/configuracoes").text
    trecho = texto[texto.index('id="liga"') : texto.index('id="amazon"')]
    assert "só abrem os casados e os com candidato" in trecho and "rodízio do dia" in trecho
    assert "Esfriar após desafio (min)" in trecho and "Produtos novos por dia" in trecho
    assert 'name="esfriar_desafio_min" value="30"' in trecho and 'name="produtos_novos_dia" value="100"' in trecho
```

Em `tests/admin/test_admin_servicos.py`, acrescente aos imports `from datetime import timedelta`, `from zoneinfo import ZoneInfo` e `StatusColeta, TipoColeta` ao import de `tcg_sniper.db.models`, e ao fim do arquivo:

```python
SP = ZoneInfo("America/Sao_Paulo")


def desafio_da_liga(sessoes, quando):
    with sessoes() as s, s.begin():
        c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, quando)
        repo.finalizar_coleta(s, c.id, StatusColeta.PAUSADA_DESAFIO, 1, 0, quando, erro="desafio em /x")
        repo.pausar_por_desafio(s, "desafio em /x", quando)


def retomada(sessoes, quando, solicitar=False):
    with sessoes() as s, s.begin():
        repo.retomar(s, quando, solicitar=solicitar)


def test_liga_esfriando_mostra_ate_quando(cliente, sessoes):
    agora = repo.agora_utc()
    desafio_da_liga(sessoes, agora - timedelta(seconds=2))
    retomada(sessoes, agora - timedelta(seconds=1))
    ate = (agora - timedelta(seconds=1) + timedelta(minutes=30)).astimezone(SP)
    liga = card(cliente.get("/servicos").text, "liga")
    assert f"Esfriando até {ate:%H:%M}" in liga and "pausas em dobro" in liga
    assert 'action="/rodar-agora"' in liga


def test_liga_parada_ate_amanha_sem_rodar_agora(cliente, sessoes):
    agora = repo.agora_utc()
    desafio_da_liga(sessoes, agora - timedelta(seconds=3))
    desafio_da_liga(sessoes, agora - timedelta(seconds=2))
    retomada(sessoes, agora - timedelta(seconds=1))
    liga = card(cliente.get("/servicos").text, "liga")
    assert "Parada até amanhã (2º desafio)" in liga and 'action="/rodar-agora"' not in liga


def test_rodar_agora_parada_nao_pede_execucao(cliente, sessoes):
    agora = repo.agora_utc()
    desafio_da_liga(sessoes, agora - timedelta(seconds=3))
    desafio_da_liga(sessoes, agora - timedelta(seconds=2))
    retomada(sessoes, agora - timedelta(seconds=1))
    r = cliente.post("/rodar-agora", follow_redirects=False)
    assert r.headers["location"] == "/servicos?msg=liga_parada_hoje"
    with sessoes() as s:
        assert repo.obter_estado(s).execucao_solicitada is False
    assert "fica parada até amanhã" in cliente.get(r.headers["location"]).text


def test_rodar_agora_esfriando_pede_e_diz_que_espera(cliente, sessoes):
    agora = repo.agora_utc()
    desafio_da_liga(sessoes, agora - timedelta(seconds=2))
    retomada(sessoes, agora - timedelta(seconds=1))
    r = cliente.post("/rodar-agora", follow_redirects=False)
    assert r.headers["location"] == "/servicos?msg=liga_esfriando"
    with sessoes() as s:
        assert repo.obter_estado(s).execucao_solicitada is True
    assert "quando o esfriamento terminar" in cliente.get(r.headers["location"]).text


def test_retomar_do_primeiro_desafio_diz_que_esfria(cliente, sessoes):
    desafio_da_liga(sessoes, repo.agora_utc() - timedelta(seconds=1))
    r = cliente.post("/retomar", follow_redirects=False)
    assert r.headers["location"] == "/servicos?msg=retomar_esfriando"


def test_retomar_do_segundo_desafio_diz_que_volta_amanha(cliente, sessoes):
    agora = repo.agora_utc()
    desafio_da_liga(sessoes, agora - timedelta(seconds=2))
    desafio_da_liga(sessoes, agora - timedelta(seconds=1))
    r = cliente.post("/retomar", follow_redirects=False)
    assert r.headers["location"] == "/servicos?msg=retomar_parada"
    assert "só volta amanhã" in cliente.get(r.headers["location"]).text
```

Em `tests/admin/test_consultas_painel.py`, ao fim do arquivo:

```python
def test_liga_esfriando_no_dashboard(s, config):
    coleta(s, TipoColeta.PRODUTOS, AGORA - timedelta(hours=1), StatusColeta.PAUSADA_DESAFIO)  # fecha 18 min depois
    repo.retomar(s, AGORA - timedelta(minutes=10))
    liga = saude(s, config)["LigaMagic"]
    assert (liga.situacao, liga.rotulo, liga.texto) == ("parcial", "esfriando", "Esfriando até 17:00")
    assert "pausas em dobro" in liga.detalhe


def test_liga_parada_ate_amanha_no_dashboard(s, config):
    coleta(s, TipoColeta.PRODUTOS, AGORA - timedelta(hours=3), StatusColeta.PAUSADA_DESAFIO)
    coleta(s, TipoColeta.PRODUTOS, AGORA - timedelta(hours=1), StatusColeta.PAUSADA_DESAFIO)
    repo.retomar(s, AGORA - timedelta(minutes=30))
    liga = saude(s, config)["LigaMagic"]
    assert (liga.situacao, liga.rotulo, liga.texto) == ("parcial", "parada até amanhã", "Parada até amanhã (2º desafio)")
    assert "Próxima amanhã por volta das 10:00" in liga.detalhe
    assert not any("LigaMagic" in a.texto for a in avisos_de(s, config))  # atenção, não problema
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_admin uv run pytest -q -p no:cacheprovider tests/admin/test_admin_config_tela.py tests/admin/test_admin_servicos.py tests/admin/test_consultas_painel.py`
Expected: FAIL (campos ausentes, textos ausentes, `msg=rodar` em vez de `liga_parada_hoje`).

- [ ] **Step 4: Configurações → LigaMagic**

Em `src/tcg_sniper/admin/formularios_config.py`, acrescente ao fim de `CAMPOS_LIGA` `"produtos_novos_dia",` e `"esfriar_desafio_min",`; a `ROTULOS_LIGA`:

```python
    "produtos_novos_dia": "Produtos novos por dia",
    "esfriar_desafio_min": "Esfriar após desafio (min)",
```

a `EXPLICACOES_LIGA`:

```python
    "produtos_novos_dia": "Produtos ativos ainda sem resumo de preço abertos por dia, os mais antigos primeiro. 0: nenhum.",
    "esfriar_desafio_min": (
        "Depois de um desafio resolvido, a coleta espera esses minutos e segue com pausas em dobro até o fim do dia. "
        "Um 2º desafio no mesmo dia para a coleta até o dia seguinte."
    ),
```

e, em `validar_liga`, troque a tupla do laço dos inteiros por:

```python
    for campo in ("coleta_jitter_min", "limite_falha_pct", "max_cliques", "produtos_novos_dia", "esfriar_desafio_min"):
```

Em `src/tcg_sniper/admin/templates/configuracoes.html`, logo antes de `{% if secao.id == "amazon" %}`:

```html
      {% if secao.id == "liga" %}
      {{ aviso("info", "Todo dia as listagens das categorias são lidas por inteiro: elas acham os produtos novos e trazem o preço À partir de de todos. Na etapa dos produtos só abrem os casados e os com candidato (todo dia), os novos ainda sem resumo (até Produtos novos por dia, os mais antigos primeiro) e o rodízio do dia (cada um dos demais uma vez por semana). Depois de um desafio resolvido a coleta espera Esfriar após desafio e segue com pausas em dobro até o fim do dia; um 2º desafio no mesmo dia para a coleta até o dia seguinte.") }}
      {% endif %}
```

- [ ] **Step 5: Serviços**

Em `src/tcg_sniper/admin/app.py`:

1. Acrescente o import `from tcg_sniper.coletor_liga.esfriamento import situacao_desafio`.
2. Em `MENSAGENS_SERVICOS`, acrescente:

```python
    "retomar_esfriando": (
        "Desafio resolvido. A coleta volta sozinha depois do esfriamento (o card mostra até quando), "
        "com pausas em dobro até o fim do dia."
    ),
    "retomar_parada": "Desafio resolvido. Foi o 2º de hoje: a coleta da LigaMagic só volta amanhã, no horário de sempre.",
    "liga_esfriando": "Execução da LigaMagic solicitada; começa quando o esfriamento terminar (o card mostra até quando).",
    "liga_parada_hoje": "A LigaMagic teve o 2º desafio hoje e fica parada até amanhã; nada foi solicitado.",
```

3. Em `servicos`, dentro do `with sessoes() as s, s.begin():`, antes do `return`, acrescente `desafio = situacao_desafio(s, repo.agora_utc(), efetiva.zona, efetiva.esfriar_desafio_min)` e, no contexto, ao lado de `"em_andamento"`:

```python
                    "liga_parada": desafio.parada_hoje,
                    "liga_esfriando_ate": (
                        f"{desafio.esfriando_ate.astimezone(efetiva.zona):%H:%M}" if desafio.esfriando_ate else None
                    ),
```

4. Troque as rotas `/retomar` e `/rodar-agora` por:

```python
    @app.post("/retomar")
    def retomar(request: Request):
        efetiva = request.state.config
        agora = repo.agora_utc()
        with sessoes() as s, s.begin():
            repo.retomar(s, agora)
            _avisar_mudanca(s, COLETOR_LIGA, "ativo", agora)
            desafio = situacao_desafio(s, agora, efetiva.zona, efetiva.esfriar_desafio_min)
        if desafio.parada_hoje:
            msg = "retomar_parada"
        elif desafio.esfriando_ate is not None:
            msg = "retomar_esfriando"
        else:
            msg = "retomar"
        return RedirectResponse(f"/servicos?msg={msg}", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/rodar-agora")
    def rodar_agora(request: Request):
        """Respeita o esfriamento (o pedido espera) e a parada do 2º desafio (nada é pedido)."""
        efetiva = request.state.config
        agora = repo.agora_utc()
        with sessoes() as s, s.begin():
            desafio = situacao_desafio(s, agora, efetiva.zona, efetiva.esfriar_desafio_min)
            if desafio.parada_hoje:
                msg = "liga_parada_hoje"
            else:
                repo.solicitar_execucao(s, agora)
                msg = "liga_esfriando" if desafio.esfriando_ate is not None else "rodar"
        return RedirectResponse(f"/servicos?msg={msg}", status_code=status.HTTP_303_SEE_OTHER)
```

Em `src/tcg_sniper/admin/templates/servicos.html`, troque o card ativo da LigaMagic (o `<div data-servico="liga" class="card bg-base-100 shadow-sm">` do ramo `{% else %}` até o `</div></div>` que o fecha) por:

```html
  <div data-servico="liga" class="card bg-base-100 shadow-sm"><div class="card-body gap-3 p-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h2 class="card-title text-base">LigaMagic {{ selo_ligado(liga == "ativo") }}{% if em_andamento %} {{ selo("rodando", "coleta em andamento") }}{% elif liga == "ativo" and liga_parada %} {{ selo("parcial", "parada até amanhã") }}{% elif liga == "ativo" and liga_esfriando_ate %} {{ selo("parcial", "esfriando") }}{% endif %}</h2>
      {{ chave("/liga/pausar" if liga == "ativo" else "/liga/retomar", liga == "ativo", "LigaMagic") }}
    </div>
    {% if liga == "ativo" %}
    <p class="text-sm">Coleta diária por volta das {{ coleta_hora }} (variação de {{ coleta_jitter }} min).{% if ultima_liga %} Última ok {{ ultima_liga.iniciada_em|data }}.{% endif %}{% if em_andamento %} <strong>Coleta em andamento.</strong>{% elif liga_parada %} <strong>Parada até amanhã (2º desafio).</strong> Volta no horário de amanhã, com as pausas normais.{% elif liga_esfriando_ate %} <strong>Esfriando até {{ liga_esfriando_ate }}.</strong> Depois disso a coleta volta sozinha, com pausas em dobro até o fim do dia.{% elif estado.execucao_solicitada %} Execução solicitada; começa em até 1 minuto.{% endif %}</p>
    {% else %}
    <p class="text-sm">Desligada: {{ estado.motivo or "sem motivo" }}. Não coleta (nem no horário, nem a pedido) até ligar de novo.</p>
    {% endif %}
    <div class="card-actions">
      {% if liga == "ativo" and not em_andamento and not liga_parada %}<form method="post" action="/rodar-agora"><button class="btn btn-sm btn-primary">Rodar agora</button></form>{% endif %}
      <a class="btn btn-sm btn-ghost" href="/logs?aba=liga">Ver histórico</a>
    </div>
  </div></div>
```

- [ ] **Step 6: Dashboard**

Em `src/tcg_sniper/admin/consultas_painel.py`, acrescente o import `from tcg_sniper.coletor_liga.esfriamento import situacao_desafio` e, em `_saude_liga`, logo depois do bloco `rodando = _coleta_rodando(...)` / `if rodando is not None: ... return ...`:

```python
    desafio = situacao_desafio(s, agora, zona, cfg.esfriar_desafio_min)
    precos = f"{com_preco} de {ativos} com preço"
    if desafio.parada_hoje:
        return SaudeServico(
            "LigaMagic", "parcial", "Parada até amanhã (2º desafio)", f"Próxima amanhã {horario} · {precos}",
            link_logs, selo="parada até amanhã",
        )
    if desafio.esfriando_ate is not None:
        texto = f"Esfriando até {desafio.esfriando_ate.astimezone(zona):%H:%M}"
        detalhe_espera = f"Volta sozinha nessa hora, com pausas em dobro até o fim do dia · {precos}"
        return SaudeServico("LigaMagic", "parcial", texto, detalhe_espera, link_logs, selo="esfriando")
```

- [ ] **Step 7: CSS**

Run: `uv run python scripts/gerar_css.py`
Expected: `src/tcg_sniper/admin/static/admin.css` atualizado (ou igual).

- [ ] **Step 8: Rodar os testes, suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_admin uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde (`test_rodar_agora` continua com `msg=rodar`: sem desafio, nada muda).

- [ ] **Step 9: Commit**

```bash
git add src/tcg_sniper/admin tests/admin
git commit -m "feat: admin shows LigaMagic cooldown and settings for the daily list"
```

---

### Task 7: Regressão, README e pendências (lane `li-final`, depois de tudo integrado)

**Files:**
- Modify: `README.md` (fluxo diário ~63-68, passo 7 ~166, "Quando chegar um aviso de desafio" ~405-411, Configurações ~441, nova subseção de implantação depois de "Implantar o casamento por par")
- Modify: `docs/PENDENCIAS.md`

**Interfaces:**
- Consumes: tudo das Tasks 1–6.
- Produces: documentação.

- [ ] **Step 1: Banco da lane e regressão inteira**

Run: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_li_final`, depois `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_final uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde. Também: `git grep -n "produtos_ativos(s)" src/tcg_sniper/coletor_liga` não acha nada (a etapa 2 não lê mais todos os ativos).

- [ ] **Step 2: README**

Edite `README.md` (localize cada trecho pelo texto citado):

1. Fluxo diário, item 2 ("**Produtos ativos.** Depois abre a página de cada produto que você marcou como ativo no admin e guarda o número de lojas e o resumo do histórico de venda (mínimo, médio e máximo).") vira:
   "2. **Produtos do dia.** Depois abre a página só dos produtos ativos que interessam hoje: os casados e os com candidato (todo dia), os novos ainda sem resumo (até 100 por dia, os mais antigos primeiro) e o rodízio do dia (cada um dos demais uma vez por semana). Guarda o número de lojas e o resumo do histórico de venda (mínimo, médio e máximo). O que já foi lido hoje não é relido: um Retomar continua de onde parou."
2. Item 4 ("**Desafio do Cloudflare.** …") acrescenta ao fim: "Depois do 1º desafio do dia a coleta espera 30 min (Configurações → LigaMagic → Esfriar após desafio) e segue com pausas em dobro até o fim do dia; um 2º desafio no mesmo dia encerra o dia, e a coleta volta no horário de amanhã."
3. Passo 7, o parágrafo "Cada produto ativo é uma visita a mais por dia na LigaMagic (cerca de 17 segundos cada): 50 produtos somam uns 15 minutos; 250, pouco mais de uma hora. Comece com poucos." vira: "Cada página de produto leva cerca de 17 segundos. Os casados e os com candidato são lidos todo dia; os demais ativos, uma vez por semana (rodízio), e os novos até 100 por dia. Com uns 2000 produtos ativos são umas 450 a 500 páginas por dia, de 2 a 3 horas."
4. "Quando chegar um aviso de desafio", item 3 ("Clique em **Retomar** em Serviços. Em até 1 minuto a coleta volta, no mesmo navegador.") vira: "Clique em **Retomar** em Serviços. A coleta volta no mesmo navegador depois do esfriamento (30 min por padrão; o card da LigaMagic mostra "Esfriando até HH:MM"), com pausas em dobro até o fim do dia. Se foi o 2º desafio do dia, o card mostra "Parada até amanhã (2º desafio)" e a coleta volta no horário de amanhã ("Rodar agora" some até lá). O aviso do WhatsApp já diz qual dos dois é."
5. Configurações, item "**LigaMagic**: horário da coleta diária e variação, pausas entre páginas, limite de falhas, categorias, URL da listagem e máximo de cliques." vira "**LigaMagic**: horário da coleta diária e variação, pausas entre páginas, limite de falhas, categorias, URL da listagem, máximo de cliques, produtos novos por dia (padrão 100) e esfriar após desafio (padrão 30 min)."
6. Depois da subseção "### Implantar o casamento por par" (antes da subseção ou seção seguinte), acrescente:

```markdown
### Implantar a leitura por interesse da LigaMagic

Faça o backup de sempre antes (ver [Backup do banco](#backup-do-banco)). A migração `d4b8e2f6a3c1` acrescenta a `config_liga` o esfriar após desafio (30 min) e os produtos novos por dia (100). Suba tudo junto (`docker compose up -d --build`) e confira em Configurações → LigaMagic os dois campos novos. Se a LigaMagic estiver parada num desafio, resolva-o no noVNC (`http://<IP deste PC>:6080/vnc.html`) e clique em **Retomar**: o card mostra "Esfriando até HH:MM" (ou "Parada até amanhã (2º desafio)" se já houve dois desafios hoje). No dia seguinte, o resumo no grupo admin traz a linha "Produtos: ok · N de M · casados …, candidatos …, novos …, rodízio …".
```

- [ ] **Step 3: Pendências**

Em `docs/PENDENCIAS.md`:

1. "Última revisão": `2026-10-19 (leitura por interesse da LigaMagic pronta no código, falta implantar; antes: busca da Amazon separada do monitor).`
2. Em "## 0. Crítico", troque o item "**Coletor da LigaMagic provocando o Cloudflare** (2026-10-19): …" por:

```markdown
- [ ] **Implantar a leitura por interesse da LigaMagic** (código pronto, merge `<merge>`): backup, `docker compose up -d --build`, conferir a migração `d4b8e2f6a3c1` aplicada e Configurações → LigaMagic com Esfriar após desafio 30 e Produtos novos por dia 100; depois resolver o desafio pendente no noVNC e Retomar (README → "Implantar a leitura por interesse da LigaMagic").
```

3. Em "## 3. Acompanhar (sem código)":
   - troque o item "Uma semana de coletas da LigaMagic sem desafio do Cloudflare. No fim, revisar o máximo de cliques em "Exibir mais" (Configurações → LigaMagic) com os números reais." por:

```markdown
- [ ] Acompanhar uma semana sem desafio com ~500 páginas/dia (leitura por interesse, desde a implantação): avisos "Liga · desafio do Cloudflare" e a linha "Produtos: … de … · casados, candidatos, novos, rodízio" do resumo diário. Se o desafio voltar, baixar o rodízio (por exemplo para 14 dias) ou subir as pausas em Configurações → LigaMagic. No fim, revisar também o máximo de cliques em "Exibir mais" com os números reais.
```

   - no item "Catálogo com 2165 produtos ativos …", troque "coleta da Liga passa de ~1 h para ~10 h" por "a etapa dos produtos da Liga lê ~450–500 páginas por dia (leitura por interesse; eram ~10 h com todos os ativos)".
4. Em "## Decisões registradas", acrescente: "2026-10-19: LigaMagic lê por interesse (casados e candidatos todo dia, novos até 100/dia, demais em rodízio de 7 dias; listagens completas todo dia) e esfria 30 min após um desafio resolvido, com pausas em dobro no resto do dia; o 2º desafio no dia encerra o dia."
5. Em "## Ordem sugerida", acrescente como primeira linha: "0. Implantar a leitura por interesse da LigaMagic (seção 0)."
6. No topo de "## Concluídas", o bloco:

```markdown
### LigaMagic: leitura por interesse e esfriar após desafio (2026-10-19, merge `<merge>`)

Spec `docs/superpowers/specs/2026-10-19-liga-leitura-por-interesse-design.md`, plano `docs/superpowers/plans/2026-10-19-liga-leitura-por-interesse.md`. Resolve o desafio do Cloudflare provocado pela leitura de todos os 2165 produtos ativos (~10 h seguidas) e o Retomar que recomeçava a lista.

- [x] **Coletor da LigaMagic provocando o Cloudflare**: a etapa dos produtos lê só a lista do dia (casados, candidatos, novos até 100/dia, rodízio de 7 dias), sem reler o que já foi lido hoje; resumo com os grupos.
- [x] Esfriar após desafio (30 min contados da retomada, pausas em dobro no resto do dia; 2º desafio encerra o dia, inclusive "Rodar agora"), derivado do banco (sobrevive a reinício); aviso diz se é o 1º ou o 2º do dia.
- [x] Configurações → LigaMagic com "Produtos novos por dia" e "Esfriar após desafio (min)" (migração `d4b8e2f6a3c1`); cards da LigaMagic em Serviços e no Dashboard com "Esfriando até HH:MM" / "Parada até amanhã (2º desafio)".
```

(O `<merge>` dos dois trechos é preenchido pelo controlador logo depois do merge em `main`, com `git log --merges -1 --format=%h`, num commit `docs: record LigaMagic interest-based reading merge`.)

- [ ] **Step 4: Suíte inteira, ruff e commit**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_li_final uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde.

```bash
git add README.md docs/PENDENCIAS.md
git commit -m "docs: LigaMagic interest-based reading and challenge cooldown; pending list"
```

---

## Implantação (depois do merge, com ok do usuário; o controlador faz, não um subagente)

Segue o CLAUDE.md ("Backup do banco antes de todo deploy com migração"; "Deploy de todos os serviços juntos"):

1. Backup do banco de produção em `dados/backups/` (`tcg-antes-liga-interesse-<data>.dump`) e conferir o arquivo (`pg_restore --list`).
2. `docker compose up -d --build` (todos juntos; o `migrate` aplica `d4b8e2f6a3c1` antes).
3. Conferir: `SELECT esfriar_desafio_min, produtos_novos_dia FROM config_liga` → `30 | 100`; Configurações → LigaMagic com os dois campos; `docker compose logs coletor-liga --tail 20` com `agendador iniciado`.
4. A Liga está pausada por desafio (desde 2026-10-19 16:01): o usuário resolve no noVNC 6080 e clica em Retomar. Conferir o card: "Esfriando até HH:MM" (1º desafio do dia) ou "Parada até amanhã (2º desafio)" (se já houve dois desafios hoje). Na hora marcada, o log mostra `coleta dos produtos N: M na lista do dia (casados …, candidatos …, novos …, rodízio …)` com M perto de 450–500.
5. No dia seguinte: o resumo do grupo admin com a linha "Produtos: … de … · casados …"; abrir o acompanhamento de uma semana (PENDENCIAS, seção 3).
