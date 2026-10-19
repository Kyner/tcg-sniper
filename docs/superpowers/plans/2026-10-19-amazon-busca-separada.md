# Coletor da Amazon: busca separada do monitor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separar o `coletor-amazon` em dois serviços — `coletor-amazon-busca` (descoberta, navegador próprio sem login, noVNC 6082) e `coletor-amazon` (retirada do carrinho, conferência de checkout e monitor, navegador logado, noVNC 6081) —, cada um com teto, janela, estado, trava, avisos e card próprios, para a busca nunca mais ficar parada atrás do monitor.

**Architecture:** `coletor_amazon/varredura.py` sai e vira três módulos: `varredura_base.py` (o comum: navegador, janela com variação, `TetoPorHora`, pausa humana, CAPTCHA, erro inesperado, pausa por falhas/erros seguidos, avisos com origem, trava, laço `rodar`), `varredura_busca.py` (só a descoberta: fila, termos, ciclos) e `varredura_monitor.py` (retirada, conferência, monitor, rodada por volta inteira, limpeza diária). A origem de cada laço (`OrigemAmazon`) diz a linha de `estado_coletor`, a trava e os três tipos de aviso (CAPTCHA, pausada, erro); um teste de importação garante que a busca não alcança checkout/carrinho/monitor e que o monitor não alcança a busca. Em volta: linha `amazon_busca` em `estado_coletor` (migração com os tetos `least()` 90/180), CLI e serviço no compose, card e rotas em Serviços, card no Dashboard, vigia e textos de Configurações.

**Tech Stack:** Python 3.12 (Docker; o venv local do uv pode ser 3.14), uv, SQLAlchemy 2 + Alembic, Postgres 16, FastAPI + Jinja2 + DaisyUI 5 (admin), Playwright/Chromium (coletores), Docker Compose, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-19-amazon-busca-separada-design.md`

## Global Constraints

- Nomes, comentários, mensagens, avisos e textos de tela em português. Assunto dos commits em inglês, `feat:`/`fix:`/`test:`/`docs:`/`chore:`, **sem** `Co-Authored-By`, `Claude-Session`, "Generated with" nem qualquer trailer de IA.
- Repositório público: nada de dado pessoal (telefone, grupo, IP real, e-mail, ASIN de compra pessoal) em código, teste, fixture ou documento.
- Regras do spec (verbatim): "Separar busca e monitor em **dois serviços** (funções distintas)."; "A busca roda **sem login** (navegador próprio, perfil próprio); monitor, checkout e retirada continuam no navegador logado."; "Tetos: **busca 90 páginas/h + monitor 180 páginas/h** (~270/h somados no mesmo IP), ajustáveis em Configurações → Amazon."; "O laço da busca **não importa** checkout, carrinho nem monitor; o do monitor não importa a busca (teste de importação garante)."; "CAPTCHA/erro/pausa num serviço não para o outro."; "Tetos independentes; nenhum empresta vaga ao outro."; "Rodada do monitor: só sai quando uma volta inteira termina (...), não a cada brecha."; migração "`least(max_buscas_hora, 90)`; `least(monitor_max_paginas_hora, 180)`", "Downgrade remove a linha e não mexe nos tetos".
- Segurança do coletor (CLAUDE.md, inalterada): nunca confirmar pedido, nunca clicar em "Comprar agora", nunca mexer nos itens que o usuário pôs no carrinho; o coletor só remove o que ele mesmo adicionou. Esta mudança **não altera** `checkout.py`, `cliques.py` nem `parsers_checkout.py`; só os move de lugar de quem chama (agora só `varredura_monitor.py`). O serviço de busca não tem acesso a esse código (teste de importação).
- Preço conferido = itens + impostos, **sem** frete (nada aqui mexe nisso).
- Admin: só componentes do DaisyUI 5 e utilitários do Tailwind, classes literais (nunca montadas por concatenação). Toda tarefa que mexe em template regenera `src/tcg_sniper/admin/static/admin.css` com `uv run python scripts/gerar_css.py` e commita junto (o teste `test_css_em_dia_com_os_templates` confere).
- Testes só no Postgres de teste (container `postgres-teste`, `127.0.0.1:5433`), um banco por lane (o fixture `engine` apaga o schema). Criar o banco, de dentro do worktree: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_<lane>` ("already exists" é ok). Ao fim de cada tarefa, verdes: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_<lane> uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`.
- Nunca mexer na stack de produção: nada de `docker compose up/down/build/restart/run/stop` nem `migrate` contra o Postgres de produção (5432). Cada lane trabalha no próprio worktree (`superpowers:using-git-worktrees`) e nada é escrito fora dele (a pasta temporária do pytest à parte; as ferramentas do `gerar_css.py` ficam em `<worktree>/.ferramentas/`). Tudo que uma lane sobe (servidor, navegador) é parado antes de ela terminar.
- `docs/PENDENCIAS.md` é atualizado na última tarefa (CLAUDE.md: "atualizar no mesmo commit de cada entrega").

## Review Focus

1. **O problema real: monitor sempre com anúncio vencido** (49 anúncios, volta de ~16 min > intervalo de 15 min). A busca tem de rodar no ritmo dela, e a rodada do monitor tem de sair uma vez por volta. Testes: Task 5 `test_busca_roda_com_o_monitor_sempre_atrasado` (dois laços no mesmo banco) e `test_rodada_avisa_ao_fim_de_cada_volta_mesmo_com_o_monitor_sempre_atrasado`.
2. **Primeiro CAPTCHA no navegador novo sem login** (provável no primeiro dia): só a busca pausa, o aviso diz "Amazon (busca) · CAPTCHA" com o noVNC da porta 6082, o monitor continua lendo, e a leitura limpa do monitor **não** fecha o CAPTCHA da busca. Testes: Task 4 `test_captcha_pausa_so_a_busca_avisa_e_mantem_o_navegador`, Task 5 `test_captcha_na_busca_nao_para_o_monitor` e `test_captcha_no_monitor_nao_para_a_busca`.
3. **Monitor que reinicia (deploy, queda) com um ciclo de busca aberto pelo outro serviço**: o `inicializar` do monitor não pode fechar como "interrompido" o ciclo que a busca está rodando, nem avisar "ciclo interrompido". Teste: Task 5 `test_inicializar_do_monitor_nao_fecha_o_ciclo_da_busca`.
4. **Volta do monitor que não termina "limpa"**: janela que fecha no meio, anúncio que sai do monitor (produto desativado, par desfeito) ou que falha no meio da volta. A rodada não pode ficar presa nem somar duas voltas num aviso. Testes: Task 5 `test_janela_que_fecha_no_meio_da_volta_nao_avisa_a_rodada`, `test_anuncio_que_sai_do_monitor_no_meio_da_volta_nao_prende_a_rodada`, `test_anuncio_que_falha_sai_da_volta`.
5. **Deploy em produção com teto do usuário diferente** (produção está com o monitor em 1000 páginas/h; um usuário pode ter baixado a busca para 60) e um ciclo de busca `rodando`: a migração baixa só o que está acima (1000→180, 200→90), nunca sobe 60, fecha o ciclo como interrompido, e o downgrade não mexe nos tetos. Teste: Task 1 `test_migracao_da_busca_separada_sobe_e_desce`.

## Decisões tomadas neste plano (o spec não fixava)

- **Ordem das ondas.** O spec põe migração/estado e avisos junto do CLI/compose e da vigia, mas os dois laços dependem deles: o laço da busca grava na linha 6 de `estado_coletor` (o `CHECK id IN (1..5)` recusa sem a migração) e avisa com os tipos novos. Por isso estado/migração (Task 1) e catálogo de avisos (Task 2) formam a Onda 1, em paralelo; os laços (Tasks 3–5) vêm na Onda 2; CLI/compose, admin e vigia em paralelo na Onda 3.
- **Avisos com origem = tipos separados.** Ficam `AMAZON_CAPTCHA`, `AMAZON_PAUSADA` e `AMAZON_ERRO` (os valores `amazon_captcha`, `amazon_pausada`, `amazon_erro` não mudam: estado aberto e liga/desliga de produção continuam valendo) para o **monitor**, com título "Amazon (monitor) · …"; entram `AMAZON_BUSCA_CAPTCHA`, `AMAZON_BUSCA_PAUSADA`, `AMAZON_BUSCA_ERRO` (valores `amazon_busca_captcha`, `amazon_busca_pausada`, `amazon_busca_erro`), título "Amazon (busca) · …". Como o estado de um problema é por (tipo, chave), cada origem tem o seu "resolvido" (a chave continua `geral`). Em Configurações → Avisos cada origem ganha o próprio liga/desliga.
- **Rodapé (origem) dos avisos:** `busca Amazon` (constante nova `BUSCA`) para os seis da busca (concluída, parcial, falhou, CAPTCHA, pausada, erro) e o "ciclo interrompido" (título "Amazon (busca) · ciclo interrompido"); `monitor Amazon` (`MONITOR`, já existe) para CAPTCHA/pausada/erro do monitor. "Conta sem login" e "conferir o carrinho" ficam como estão (só a ação passa a dizer "Amazon (monitor e checkout)").
- **Rodada do monitor = uma volta.** Ao começar (primeiro trabalho sem rodada aberta), a rodada guarda os anúncios vencidos naquele momento (`faltam`). Cada leitura tira o anúncio de `faltam`; uma falha (anúncio posto de lado por um intervalo) também tira; um anúncio que deixa de estar vencido sem ser lido (produto desativado, par desfeito) sai na próxima conferência (`faltam &= vencidos`). Com `faltam` vazio a rodada fecha e avisa (se leu algum), **mesmo que já haja outros vencidos** — com o monitor sempre atrasado, a volta seguinte começa no mesmo passo. Assim "nenhum vencido restante" do spec é lido como "nenhum vencido da volta restante" (com o teto de 180/h e ~49 anúncios, a fila do monitor raramente zera e o aviso nunca sairia). A janela do monitor que fecha no meio descarta a volta sem aviso.
- **`fechar_oportunidades_sem_leitura` fica na busca** (depende de `visto_ultimo_em`, que a busca atualiza), como hoje.
- **Trava:** o monitor mantém `ID_LOCK_AMAZON = 7_202_611` (o `amazon capturar` usa o mesmo perfil `perfil-amazon` e a mesma trava); a busca usa `ID_LOCK_AMAZON_BUSCA = 7_202_612`.
- **Ciclo interrompido:** só o laço da busca marca ciclos `rodando` como interrompidos no `inicializar` (o monitor não tem ciclo). A migração também fecha o que estiver `rodando` no deploy, com o mesmo resultado de `marcar_interrompidas` (`status='falha'`, `erro='interrompida'`).
- **Padrões de fábrica:** `PADROES_CONFIG_AMAZON["max_buscas_hora"]` passa de 200 para 90 (o banco novo nasce com 200 e a migração o baixa para 90; o teste `test_migracao_cria_config_amazon_com_os_padroes` compara os dois). `monitor_max_paginas_hora` continua 150 de fábrica (`least(150, 180) = 150`; `least` nunca sobe valor).
- **Revisão Alembic:** `c6a2f8e4d1b9_amazon_busca_separada.py`, `down_revision = "b3e8d1f5c7a2"`; `estado_coletor` linha **6** = `amazon_busca` (`CHECK id IN (1, 2, 3, 4, 5, 6)`).
- **Constante e nomes:** `COLETOR_AMAZON_BUSCA = "amazon_busca"`; batida de vida `Batimento(sessoes, COLETOR_AMAZON_BUSCA)` (`sinal_servico.servico = 'amazon_busca'`); vigia mostra `coletor-amazon-busca`. Nomes de tela: "Amazon (busca)" e "Amazon (monitor e checkout)".
- **Rotas novas:** `POST /amazon/busca/pausar` (respeita desafio pendente, como as outras) e `POST /amazon/busca/retomar`; mensagens `amazon_busca_pausar`/`amazon_busca_retomar`. `/amazon/pausar` e `/amazon/retomar` continuam e passam a valer só para monitor e checkout.
- **"Buscas na última hora"** no Dashboard = produtos com `fila_amazon.ultima_busca_em` na última hora (um produto buscado duas vezes na mesma hora conta uma; com o intervalo mínimo de 60/2 = 30 min de padrão isso quase não acontece). **"Produtos ativos nunca buscados"** = produtos ativos sem `ultima_busca_em` (inclui os que ainda não entraram na fila).
- **Helpers dos testes** dos dois laços ficam em `tests/fakes_varredura.py` (novo), usado pelos três arquivos de teste de laço.
- `busca.py` (o módulo de página: `abrir_pagina`, `ContextoBusca`, `DesafioAmazon`, `CotaHtmlFalha`) continua compartilhado: o monitor e o checkout usam essas primitivas de página; o que o monitor não pode importar é o **laço** `varredura_busca` (nem chamar `processar_produto`/fila).

---

## Ondas (para execução paralela)

- **Onda 1 (em paralelo, cada uma no próprio worktree a partir de `main`):** Task 1 (lane `estado`: constante, estado, migração, padrão 90) e Task 2 (lane `avisos`: tipos e textos dos avisos por origem).
- **Onda 2 (lane `lacos`, sequencial, a partir do branch integrado da Onda 1):** Task 3 (`varredura_base.py` + `tests/fakes_varredura.py`), Task 4 (`varredura_busca.py`, testes portados), Task 5 (`varredura_monitor.py`, rodada por volta, testes portados, testes cruzados e de importação; `varredura.py` sai; `cli.py` aponta para o monitor).
- **Onda 3 (em paralelo, a partir do branch integrado da Onda 2):** Task 6 (lane `servico`: CLI `coletor-amazon-busca`, compose, entrypoint), Tasks 7–9 (lane `admin`, sequenciais: Serviços, Dashboard, Configurações) e Task 10 (lane `vigia`).
- **Onda 4:** Task 11 (lane `final`: regressão inteira, README, `docs/PENDENCIAS.md`).
- Integração: o controlador cria o branch `amazon-busca-separada` a partir de `main`, faz merge de cada lane ao fim da onda (`git merge --no-ff`) e as lanes da onda seguinte saem desse branch.
- Conflitos esperados: nenhum arquivo é tocado por duas lanes da mesma onda. Entre ondas: `tests/coletor_amazon/test_varredura.py` (Task 2 pode ajustar um texto; Task 4 o substitui por `test_varredura_busca.py`); `src/tcg_sniper/cli.py` (Task 5 troca a importação do monitor; Task 6 acrescenta o ramo da busca); `admin.css` só na lane `admin`.

## Arquivos

| Arquivo | Responsabilidade | Tasks |
|---|---|---|
| `src/tcg_sniper/db/models.py` | `COLETOR_AMAZON_BUSCA`, `CHECK` da linha 6, padrão `max_buscas_hora = 90` | 1 |
| `src/tcg_sniper/db/repositorio.py` | `ID_COLETOR[COLETOR_AMAZON_BUSCA] = 6` | 1 |
| `src/tcg_sniper/db/migrations/versions/c6a2f8e4d1b9_amazon_busca_separada.py` (novo) | linha 6, tetos `least`, ciclo interrompido, downgrade | 1 |
| `src/tcg_sniper/avisos/catalogo.py`, `avisos/formato.py` | tipos da busca, títulos com origem, rodapés, porta 6082 recusada em URL | 2 |
| `src/tcg_sniper/coletor_amazon/varredura_base.py` (novo) | o comum aos dois laços, `OrigemAmazon`, `ORIGEM_BUSCA`, `ORIGEM_MONITOR` | 3 |
| `tests/fakes_varredura.py` (novo) | relógio, fábrica de navegador, `criar_laco`, `confirmado`, `livre`, `ofertas`, `vazia` | 3 |
| `src/tcg_sniper/coletor_amazon/varredura_busca.py` (novo) | laço da descoberta | 4 |
| `src/tcg_sniper/db/repositorio_amazon.py` | `ids_vencidos_do_monitor` | 5 |
| `src/tcg_sniper/coletor_amazon/varredura_monitor.py` (novo) | laço da retirada, conferência, monitor e rodada | 5 |
| `src/tcg_sniper/coletor_amazon/varredura.py` | sai | 5 |
| `src/tcg_sniper/cli.py`, `tests/test_cli.py` | `coletor-amazon` → monitor (5); `coletor-amazon-busca` (6) | 5, 6 |
| `docker-compose.yml`, `docker/coletor-entrypoint.sh`, `tests/test_compose.py` (novo) | serviço `coletor-amazon-busca` | 6 |
| `src/tcg_sniper/admin/app.py`, `templates/servicos.html` | card e rotas da busca; card do monitor | 7 |
| `src/tcg_sniper/admin/consultas_painel.py`, `templates/index.html` | dois cards no Dashboard | 8 |
| `src/tcg_sniper/coletor_amazon/config.py`, `templates/configuracoes.html` | textos dos dois navegadores e tetos | 9 |
| `src/tcg_sniper/avisos/vigia.py` | `amazon_busca` vigiado | 10 |
| `README.md`, `docs/PENDENCIAS.md` | documentação e pendências | 11 |

---

### Task 1: Estado `amazon_busca`, migração e padrão do teto (lane `estado`)

**Files:**
- Modify: `src/tcg_sniper/db/models.py:104-108` (constante), `:204-212` (`EstadoColetor` docstring e `CheckConstraint`), `:453` (`PADROES_CONFIG_AMAZON["max_buscas_hora"]`)
- Modify: `src/tcg_sniper/db/repositorio.py:10-16` (import) e `:179` (`ID_COLETOR`)
- Create: `src/tcg_sniper/db/migrations/versions/c6a2f8e4d1b9_amazon_busca_separada.py`
- Modify: `tests/db/test_migracao.py:31-35` (o teste do CHECK passa a usar a linha 7)
- Test: `tests/db/test_migracao_amazon_busca.py` (novo), `tests/db/test_repositorio.py` (acrescentar)

**Interfaces:**
- Consumes: head atual do Alembic `b3e8d1f5c7a2`; `repo.obter_estado`, `repo.pausar`.
- Produces:
  - `models.COLETOR_AMAZON_BUSCA: str = "amazon_busca"`.
  - `repositorio.ID_COLETOR[COLETOR_AMAZON_BUSCA] == 6`; `repo.obter_estado(s, agora, COLETOR_AMAZON_BUSCA)`, `repo.pausar(..., COLETOR_AMAZON_BUSCA)`, `repo.pausar_por_desafio(..., COLETOR_AMAZON_BUSCA)`, `repo.retomar(..., COLETOR_AMAZON_BUSCA)` funcionam.
  - `PADROES_CONFIG_AMAZON["max_buscas_hora"] == 90`.
  - Revisão Alembic `c6a2f8e4d1b9` (nova head).

- [ ] **Step 1: Banco da lane**

Run: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_estado`
Expected: sem saída (ou "already exists").

- [ ] **Step 2: Escrever os testes (falham)**

Crie `tests/db/test_migracao_amazon_busca.py`:

```python
from alembic import command
from sqlalchemy import create_engine, pool, text

from tcg_sniper.db.session import config_alembic

TETOS = "SELECT max_buscas_hora, monitor_max_paginas_hora FROM config_amazon WHERE id = 1"
ANTES = "b3e8d1f5c7a2"


def _tetos(c, busca, monitor):
    c.execute(
        text("UPDATE config_amazon SET max_buscas_hora = :b, monitor_max_paginas_hora = :m WHERE id = 1"),
        {"b": busca, "m": monitor},
    )


def test_migracao_da_busca_separada_sobe_e_desce(engine):
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    coletas: list[int] = []
    try:
        with proprio.begin() as c:
            originais = tuple(c.execute(text(TETOS)).one())
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.scalar(text("SELECT count(*) FROM estado_coletor WHERE id = 6")) == 0
            _tetos(c, 200, 1000)  # produção: busca no padrão antigo, monitor em 1000
            coletas.append(
                c.scalar(
                    text(
                        "INSERT INTO coleta (tipo, iniciada_em, status, produtos_ok, produtos_falha) "
                        "VALUES ('amazon', now(), 'rodando', 3, 0) RETURNING id"
                    )
                )
            )
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            linha = c.execute(text("SELECT coletor, estado FROM estado_coletor WHERE id = 6")).one()
            assert tuple(linha) == ("amazon_busca", "ativo")
            assert tuple(c.execute(text(TETOS)).one()) == (90, 180)
            ciclo = c.execute(text("SELECT status, erro FROM coleta WHERE id = :id"), {"id": coletas[0]}).one()
            assert tuple(ciclo) == ("falha", "interrompida")
        command.downgrade(cfg, ANTES)
        with proprio.begin() as c:
            assert c.scalar(text("SELECT count(*) FROM estado_coletor WHERE id = 6")) == 0
            assert tuple(c.execute(text(TETOS)).one()) == (90, 180)  # o downgrade não mexe nos tetos
            _tetos(c, 60, 150)  # valores do usuário abaixo dos novos tetos
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            assert tuple(c.execute(text(TETOS)).one()) == (60, 150)  # least nunca sobe
    finally:
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            _tetos(c, *originais)
            for coleta_id in coletas:
                c.execute(text("DELETE FROM coleta WHERE id = :id"), {"id": coleta_id})
        proprio.dispose()
```

Acrescente a `tests/db/test_migracao.py`, logo depois de `test_migracao_cria_estado_da_manutencao_ativo_e_o_estado_vivo`:

```python
def test_migracao_cria_estado_da_busca_da_amazon_ativo(s):
    estado = s.get(EstadoColetor, 6)
    assert (estado.coletor, estado.estado) == ("amazon_busca", EstadoColetorTipo.ATIVO)
```

e troque, em `test_estado_coletor_aceita_so_as_linhas_dos_coletores`, `EstadoColetor(id=6, ...)` por `EstadoColetor(id=7, ...)` (a 6 agora existe).

Acrescente a `tests/db/test_repositorio.py` (importe `COLETOR_AMAZON`, `COLETOR_AMAZON_BUSCA` e `EstadoColetorTipo` de `tcg_sniper.db.models` se o arquivo ainda não importa; `T0` vem de `fakes`):

```python
def test_estado_da_busca_da_amazon_e_a_linha_6_e_independente_do_monitor(s):
    busca = repo.obter_estado(s, T0, COLETOR_AMAZON_BUSCA)
    assert (busca.id, busca.coletor, busca.estado) == (6, "amazon_busca", EstadoColetorTipo.ATIVO)
    repo.pausar_por_desafio(s, "desafio em /s?k=x", T0, COLETOR_AMAZON_BUSCA)
    assert repo.obter_estado(s, T0, COLETOR_AMAZON_BUSCA).estado is EstadoColetorTipo.PAUSADO_DESAFIO
    assert repo.obter_estado(s, T0, COLETOR_AMAZON).estado is EstadoColetorTipo.ATIVO
    repo.retomar(s, T0, COLETOR_AMAZON_BUSCA)
    assert repo.obter_estado(s, T0, COLETOR_AMAZON_BUSCA).estado is EstadoColetorTipo.ATIVO
```

Acrescente a `tests/coletor_amazon/test_config_amazon.py`:

```python
def test_teto_de_fabrica_da_busca_e_90_e_o_do_monitor_150():
    assert PADROES_CONFIG_AMAZON["max_buscas_hora"] == 90
    assert PADROES_CONFIG_AMAZON["monitor_max_paginas_hora"] == 150
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_estado uv run pytest -q -p no:cacheprovider tests/db/test_migracao_amazon_busca.py tests/db/test_migracao.py tests/db/test_repositorio.py tests/coletor_amazon/test_config_amazon.py`
Expected: FAIL (`ImportError: cannot import name 'COLETOR_AMAZON_BUSCA'`; sem ela, a linha 6 inexistente).

- [ ] **Step 4: Modelos e repositório**

Em `src/tcg_sniper/db/models.py`, depois de `COLETOR_MANUTENCAO = "manutencao"`:

```python
COLETOR_AMAZON_BUSCA = "amazon_busca"  # busca de anúncios novos (serviço coletor-amazon-busca, navegador sem login)
```

Em `EstadoColetor`, troque o docstring e o CHECK:

```python
class EstadoColetor(Base):
    """Uma linha por serviço: id 1 = Liga, id 2 = Amazon (monitor, checkout e retirada), id 3 = casador,
    id 4 = notificador, id 5 = manutenção, id 6 = Amazon (busca) (ver `repositorio.ID_COLETOR`)."""

    __tablename__ = "estado_coletor"
    __table_args__ = (
        CheckConstraint("id IN (1, 2, 3, 4, 5, 6)", name="ck_estado_coletor_linhas"),
        UniqueConstraint("coletor", name="uq_estado_coletor_coletor"),
    )
```

Em `PADROES_CONFIG_AMAZON`: `"max_buscas_hora": 90,`.

Em `src/tcg_sniper/db/repositorio.py`, acrescente `COLETOR_AMAZON_BUSCA` ao import de `tcg_sniper.db.models` e troque `ID_COLETOR` por:

```python
ID_COLETOR = {
    COLETOR_LIGA: 1,
    COLETOR_AMAZON: 2,
    COLETOR_CASADOR: 3,
    COLETOR_NOTIFICADOR: 4,
    COLETOR_MANUTENCAO: 5,
    COLETOR_AMAZON_BUSCA: 6,
}
```

- [ ] **Step 5: Migração**

Crie `src/tcg_sniper/db/migrations/versions/c6a2f8e4d1b9_amazon_busca_separada.py`:

```python
"""busca da Amazon separada do monitor: linha 6 (amazon_busca) em estado_coletor, tetos 90/180 e ciclo
de busca rodando fechado como interrompido

Revision ID: c6a2f8e4d1b9
Revises: b3e8d1f5c7a2
Create Date: 2026-10-19 21:00:00

Os tetos só descem (least): um valor do usuário menor que 90 (busca) ou 180 (monitor) fica. O downgrade
tira a linha 6 e não mexe nos tetos.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c6a2f8e4d1b9"
down_revision: Union[str, Sequence[str], None] = "b3e8d1f5c7a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_estado_coletor_linhas", "estado_coletor", type_="check")
    op.create_check_constraint("ck_estado_coletor_linhas", "estado_coletor", "id IN (1, 2, 3, 4, 5, 6)")
    op.execute(
        "INSERT INTO estado_coletor (id, coletor, estado, execucao_solicitada, atualizado_em) "
        "VALUES (6, 'amazon_busca', 'ativo', false, now()) ON CONFLICT (id) DO NOTHING"
    )
    op.execute(
        "UPDATE config_amazon SET max_buscas_hora = least(max_buscas_hora, 90), "
        "monitor_max_paginas_hora = least(monitor_max_paginas_hora, 180)"
    )
    # Igual a repositorio.marcar_interrompidas: o ciclo da busca aberto no deploy não volta.
    op.execute(
        "UPDATE coleta SET status = 'falha', erro = 'interrompida', finalizada_em = now() "
        "WHERE tipo = 'amazon' AND status = 'rodando'"
    )


def downgrade() -> None:
    op.execute("DELETE FROM estado_coletor WHERE id = 6")
    op.drop_constraint("ck_estado_coletor_linhas", "estado_coletor", type_="check")
    op.create_check_constraint("ck_estado_coletor_linhas", "estado_coletor", "id IN (1, 2, 3, 4, 5)")
```

- [ ] **Step 6: Rodar os testes da tarefa**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_estado uv run pytest -q -p no:cacheprovider tests/db tests/coletor_amazon/test_config_amazon.py`
Expected: PASS (inclusive `test_migracao_igual_aos_modelos` e `test_migracao_cria_config_amazon_com_os_padroes`).

- [ ] **Step 7: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_estado uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde. (Teste de outra área que dependa do padrão 200 — por exemplo um que conte mais de 90 buscas numa hora — ganha `aplicar_config(s, {"max_buscas_hora": 200}, ...)` no próprio teste.)

- [ ] **Step 8: Commit**

```bash
git add src/tcg_sniper/db tests/db tests/coletor_amazon/test_config_amazon.py
git commit -m "feat: add amazon_busca collector state, 90/180 caps migration"
```

---

### Task 2: Avisos com origem (lane `avisos`)

**Files:**
- Modify: `src/tcg_sniper/avisos/catalogo.py` (enum `TipoAviso` ~32-62, constantes de origem ~105-106, entradas da Amazon ~170-250)
- Modify: `src/tcg_sniper/avisos/formato.py:33` (`_PORTAS`) e o docstring de `conferir_urls` (~178)
- Test: `tests/avisos/test_formato.py` (`ESPERADOS`, `test_regras_do_catalogo`), `tests/avisos/test_regras_globais.py:16` (`PROIBIDO`)

**Interfaces:**
- Consumes: nada de outras tarefas.
- Produces:
  - `TipoAviso.AMAZON_BUSCA_CAPTCHA = "amazon_busca_captcha"`, `TipoAviso.AMAZON_BUSCA_PAUSADA = "amazon_busca_pausada"`, `TipoAviso.AMAZON_BUSCA_ERRO = "amazon_busca_erro"` (todos `_problema`, agrupam, lembrete 2 h).
  - Títulos: `AMAZON_CAPTCHA` "Amazon (monitor) · CAPTCHA", `AMAZON_PAUSADA` "Amazon (monitor) · pausada", `AMAZON_ERRO` "Amazon (monitor) · erro inesperado", `AMAZON_BUSCA_CAPTCHA` "Amazon (busca) · CAPTCHA", `AMAZON_BUSCA_PAUSADA` "Amazon (busca) · pausada", `AMAZON_BUSCA_ERRO` "Amazon (busca) · erro inesperado", `AMAZON_INTERROMPIDA` "Amazon (busca) · ciclo interrompido".
  - `catalogo.BUSCA = "busca Amazon"` (rodapé).
  - Textos que os laços (Tasks 3–5) gravam nos `Dados` e os testes deles conferem: busca — CAPTCHA "A busca fica pausada até você retomar; o monitor e a conferência seguem", pausa "Com a busca pausada, o monitor e a conferência seguem", interrompido "<n> ciclo(s) marcado(s) como falha: o serviço de busca reiniciou"; monitor — CAPTCHA "Monitor e conferência pausados até você retomar; a busca segue", pausa "Com o monitor pausado, a retirada automática de item do carrinho também para".
  - `formato._PORTAS` recusa também `:6082`.

- [ ] **Step 1: Banco da lane**

Run: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_avisos`

- [ ] **Step 2: Escrever os testes (falham)**

Em `tests/avisos/test_formato.py`, no dicionário `ESPERADOS`:

1. Nas entradas existentes `TipoAviso.AMAZON_BUSCA_CONCLUIDA`, `TipoAviso.AMAZON_BUSCA_PARCIAL` e `TipoAviso.AMAZON_BUSCA_FALHOU`, troque o rodapé `"_18/10 10:42 · coletor Amazon_"` por `"_18/10 10:42 · busca Amazon_"` (o resto igual).
2. Substitua as entradas `AMAZON_CAPTCHA`, `AMAZON_SEM_LOGIN`, `AMAZON_PAUSADA`, `AMAZON_ERRO` e `AMAZON_INTERROMPIDA` por estas, e acrescente as três da busca logo depois de `AMAZON_BUSCA_FALHOU`:

```python
    TipoAviso.AMAZON_BUSCA_CAPTCHA: (
        "🔴 *Amazon (busca) · CAPTCHA*\n"
        "• Página: /s?k=aetherdrift+commander\n"
        "• A busca fica pausada até você retomar; o monitor e a conferência seguem\n"
        "\n"
        "*O que fazer:* Resolva no noVNC da busca (porta 6082) e depois Admin → Serviços → Amazon (busca) → Retomar.\n"
        "_18/10 10:42 · busca Amazon_"
    ),
    TipoAviso.AMAZON_BUSCA_PAUSADA: (
        "🔴 *Amazon (busca) · pausada*\n"
        "• Motivo: 10 páginas seguidas com falha (bloqueio ou layout novo?)\n"
        "• Com a busca pausada, o monitor e a conferência seguem\n"
        "\n"
        "*O que fazer:* Veja os logs (docker compose logs coletor-amazon-busca) e depois "
        "Admin → Serviços → Amazon (busca) → Retomar.\n"
        "_18/10 10:42 · busca Amazon_"
    ),
    TipoAviso.AMAZON_BUSCA_ERRO: (
        "🟡 *Amazon (busca) · erro inesperado*\n"
        "• Erro: RuntimeError('navegador fechou')\n"
        "\n"
        "*O que fazer:* Nada a fazer se não repetir: nova tentativa em 15 min. Se repetir, veja os logs "
        "(docker compose logs coletor-amazon-busca).\n"
        "_18/10 10:42 · busca Amazon_"
    ),
    TipoAviso.AMAZON_CAPTCHA: (
        "🔴 *Amazon (monitor) · CAPTCHA*\n"
        "• Página: /gp/cart/view.html\n"
        "• Monitor e conferência pausados até você retomar; a busca segue\n"
        "• Uma conferência deixou 1× B0DNV55QBS no carrinho: sai sozinho se você retomar em até 30 min; "
        "senão confira à mão\n"
        "\n"
        "*O que fazer:* Resolva no noVNC do monitor (porta 6081) e depois "
        "Admin → Serviços → Amazon (monitor e checkout) → Retomar.\n"
        "_18/10 10:42 · monitor Amazon_"
    ),
    TipoAviso.AMAZON_SEM_LOGIN: (
        "🔴 *Amazon · conta sem login*\n"
        "• A conferência de checkout parou; o monitor de preço continua\n"
        "\n"
        "*O que fazer:* Faça login na conta Amazon pelo noVNC do monitor (porta 6081) e depois "
        "Admin → Serviços → Amazon (monitor e checkout) → Retomar conferência.\n"
        "_18/10 10:42 · coletor Amazon_"
    ),
    TipoAviso.AMAZON_PAUSADA: (
        "🔴 *Amazon (monitor) · pausada*\n"
        "• Motivo: 10 páginas seguidas com falha (bloqueio ou layout novo?)\n"
        "• Com o monitor pausado, a retirada automática de item do carrinho também para\n"
        "\n"
        "*O que fazer:* Veja os logs (docker compose logs coletor-amazon) e depois "
        "Admin → Serviços → Amazon (monitor e checkout) → Retomar.\n"
        "_18/10 10:42 · monitor Amazon_"
    ),
    TipoAviso.AMAZON_ERRO: (
        "🟡 *Amazon (monitor) · erro inesperado*\n"
        "• Erro: RuntimeError('navegador fechou')\n"
        "\n"
        "*O que fazer:* Nada a fazer se não repetir: nova tentativa em 15 min. Se repetir, veja os logs "
        "(docker compose logs coletor-amazon).\n"
        "_18/10 10:42 · monitor Amazon_"
    ),
    TipoAviso.AMAZON_INTERROMPIDA: (
        "🟡 *Amazon (busca) · ciclo interrompido*\n"
        "• 1 ciclo(s) marcado(s) como falha: o serviço de busca reiniciou\n"
        "\n"
        "*O que fazer:* Nada a fazer: a fila continua sozinha.\n"
        "_18/10 10:42 · busca Amazon_"
    ),
```

3. Em `test_regras_do_catalogo`, acrescente ao conjunto `agrupam` esperado: `TipoAviso.AMAZON_BUSCA_CAPTCHA, TipoAviso.AMAZON_BUSCA_PAUSADA, TipoAviso.AMAZON_BUSCA_ERRO`.

4. Acrescente ao fim do arquivo:

```python
def test_cada_origem_da_amazon_tem_titulo_proprio():
    titulos = {CATALOGO[t].titulo for t in (
        TipoAviso.AMAZON_CAPTCHA, TipoAviso.AMAZON_BUSCA_CAPTCHA, TipoAviso.AMAZON_PAUSADA,
        TipoAviso.AMAZON_BUSCA_PAUSADA, TipoAviso.AMAZON_ERRO, TipoAviso.AMAZON_BUSCA_ERRO,
    )}
    assert len(titulos) == 6
    assert all(t.startswith(("Amazon (busca) · ", "Amazon (monitor) · ")) for t in titulos)


def test_porta_6082_tambem_e_endereco_do_sistema():
    with pytest.raises(UrlProibida):
        conferir_urls("veja http://10.0.0.2:6082/vnc.html", "10.0.0.2", estrito=True)
```

(Se `conferir_urls` tiver outra assinatura no arquivo, use a mesma chamada que `test_endereco_do_sistema_e_recusado_em_modo_estrito` usa, trocando só a porta.)

Em `tests/avisos/test_regras_globais.py`, troque `PROIBIDO`:

```python
PROIBIDO = re.compile(r":(?:8000|6080|6081|6082)(?!\d)|192\.168\.0\.10")
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_avisos uv run pytest -q -p no:cacheprovider tests/avisos`
Expected: FAIL (`AttributeError: AMAZON_BUSCA_CAPTCHA`, textos diferentes).

- [ ] **Step 4: Catálogo e formato**

Em `src/tcg_sniper/avisos/catalogo.py`:

No enum, depois de `AMAZON_BUSCA_FALHOU = "amazon_busca_falhou"`:

```python
    AMAZON_BUSCA_CAPTCHA = "amazon_busca_captcha"
    AMAZON_BUSCA_PAUSADA = "amazon_busca_pausada"
    AMAZON_BUSCA_ERRO = "amazon_busca_erro"
```

Troque a linha das origens por:

```python
LIGA, AMAZON, MONITOR, IA = "coletor Liga", "coletor Amazon", "monitor Amazon", "casador (IA)"
BUSCA = "busca Amazon"
```

Nas entradas `AMAZON_BUSCA_CONCLUIDA`, `AMAZON_BUSCA_PARCIAL` e `AMAZON_BUSCA_FALHOU`, troque a origem `AMAZON` por `BUSCA` (título, descrição, ação e exemplo iguais). Logo depois de `AMAZON_BUSCA_FALHOU`, acrescente:

```python
    TipoAviso.AMAZON_BUSCA_CAPTCHA: _problema(
        F, "Amazon (busca) · CAPTCHA", BUSCA,
        "A Amazon pediu verificação no navegador da busca (sem login); só a busca fica pausada.",
        "Resolva no noVNC da busca (porta 6082) e depois Admin → Serviços → Amazon (busca) → Retomar.",
        Dados(
            linhas=(
                "Página: /s?k=aetherdrift+commander",
                "A busca fica pausada até você retomar; o monitor e a conferência seguem",
            )
        ),
    ),
    TipoAviso.AMAZON_BUSCA_PAUSADA: _problema(
        F, "Amazon (busca) · pausada", BUSCA,
        "A busca foi pausada por páginas com falha ou erros inesperados seguidos; o monitor segue.",
        "Veja os logs (docker compose logs coletor-amazon-busca) e depois Admin → Serviços → Amazon (busca) → Retomar.",
        Dados(
            linhas=(
                "Motivo: 10 páginas seguidas com falha (bloqueio ou layout novo?)",
                "Com a busca pausada, o monitor e a conferência seguem",
            )
        ),
    ),
    TipoAviso.AMAZON_BUSCA_ERRO: _problema(
        A, "Amazon (busca) · erro inesperado", BUSCA, "Erro inesperado num passo da busca; tenta de novo em 15 min.",
        "Nada a fazer se não repetir: nova tentativa em 15 min. Se repetir, veja os logs "
        "(docker compose logs coletor-amazon-busca).",
        Dados(linhas=("Erro: RuntimeError('navegador fechou')",)),
    ),
```

Substitua as entradas `AMAZON_CAPTCHA`, `AMAZON_SEM_LOGIN`, `AMAZON_PAUSADA`, `AMAZON_ERRO` e `AMAZON_INTERROMPIDA` por:

```python
    TipoAviso.AMAZON_CAPTCHA: _problema(
        F, "Amazon (monitor) · CAPTCHA", MONITOR,
        "A Amazon pediu verificação no navegador logado; monitor, conferência e retirada do carrinho ficam "
        "pausados (a busca segue).",
        "Resolva no noVNC do monitor (porta 6081) e depois Admin → Serviços → Amazon (monitor e checkout) → Retomar.",
        Dados(
            linhas=(
                "Página: /gp/cart/view.html",
                "Monitor e conferência pausados até você retomar; a busca segue",
                (
                    "Uma conferência deixou 1× B0DNV55QBS no carrinho: sai sozinho se você retomar em até 30 min; "
                    "senão confira à mão"
                ),
            )
        ),
    ),
    TipoAviso.AMAZON_SEM_LOGIN: _problema(
        F, "Amazon · conta sem login", AMAZON, "A conferência de checkout caiu no login; o monitor continua.",
        "Faça login na conta Amazon pelo noVNC do monitor (porta 6081) e depois "
        "Admin → Serviços → Amazon (monitor e checkout) → Retomar conferência.",
        Dados(linhas=("A conferência de checkout parou; o monitor de preço continua",)),
    ),
```

(a entrada `AMAZON_CARRINHO` fica como está)

```python
    TipoAviso.AMAZON_PAUSADA: _problema(
        F, "Amazon (monitor) · pausada", MONITOR,
        "Monitor e checkout pausados por páginas com falha ou erros inesperados seguidos; a busca segue.",
        "Veja os logs (docker compose logs coletor-amazon) e depois "
        "Admin → Serviços → Amazon (monitor e checkout) → Retomar.",
        Dados(
            linhas=(
                "Motivo: 10 páginas seguidas com falha (bloqueio ou layout novo?)",
                "Com o monitor pausado, a retirada automática de item do carrinho também para",
            )
        ),
    ),
    TipoAviso.AMAZON_ERRO: _problema(
        A, "Amazon (monitor) · erro inesperado", MONITOR,
        "Erro inesperado num passo do monitor ou do checkout; tenta de novo em 15 min.",
        "Nada a fazer se não repetir: nova tentativa em 15 min. Se repetir, veja os logs "
        "(docker compose logs coletor-amazon).",
        Dados(linhas=("Erro: RuntimeError('navegador fechou')",)),
    ),
    TipoAviso.AMAZON_INTERROMPIDA: _evento(
        A, "Amazon (busca) · ciclo interrompido", BUSCA, "O serviço de busca da Amazon reiniciou no meio de um ciclo.",
        "Nada a fazer: a fila continua sozinha.",
        Dados(linhas=("1 ciclo(s) marcado(s) como falha: o serviço de busca reiniciou",)),
    ),
```

Na entrada `AMAZON_MONITOR_CONCLUIDO`, troque só a descrição para `"O monitor terminou uma volta: leu todos os anúncios que estavam vencidos quando ela começou."`.

Em `src/tcg_sniper/avisos/formato.py`:

```python
_PORTAS = re.compile(r":(?:8000|6080|6081|6082)(?!\d)")
```

e, no docstring de `conferir_urls`, "`:6081`" vira "`:6081`, `:6082`".

- [ ] **Step 5: Rodar os testes da tarefa**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_avisos uv run pytest -q -p no:cacheprovider tests/avisos`
Expected: PASS.

- [ ] **Step 6: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_avisos uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde. O `varredura.py` antigo ainda existe nesta onda: em `tests/coletor_amazon/test_varredura.py::test_captcha_pausa_avisa_e_mantem_o_navegador`, troque só `"noVNC da Amazon (porta 6081)"` por `"porta 6081"` (o arquivo é substituído na Task 4). Se outro teste de admin conferir um título antigo ("Amazon · CAPTCHA", "Amazon · pausada", "Amazon · erro inesperado"), troque pelo título novo.

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/avisos tests/avisos tests/coletor_amazon/test_varredura.py
git commit -m "feat: Amazon alerts carry their origin (search or monitor)"
```

---

### Task 3: Base comum dos dois laços (lane `lacos`)

**Files:**
- Create: `src/tcg_sniper/coletor_amazon/varredura_base.py`
- Create: `tests/fakes_varredura.py`
- Test: `tests/coletor_amazon/test_varredura_base.py` (novo)

**Interfaces:**
- Consumes: Task 1 (`COLETOR_AMAZON_BUSCA`, linha 6), Task 2 (`TipoAviso.AMAZON_BUSCA_*`, textos dos efeitos); de hoje: `busca.ContextoBusca`, `busca.CotaHtmlFalha`, `fila.Janela`, `fila.TetoPorHora`, `fila.janela_do_dia`, `agendador.lock_coleta`, `config_banco.carregar_config`, `repo.obter_estado/pausar/pausar_por_desafio`, `repo_amz.obter_config`, `ritmo.pausa_aleatoria`.
- Produces (módulo `tcg_sniper.coletor_amazon.varredura_base`):
  - Constantes: `ESPERA_OCIOSA_S = 60`, `ESPERA_ERRO_S = 900`, `MAX_ERROS_SEGUIDOS = 3`, `MAX_FALHAS_SEGUIDAS = 10`, `ID_LOCK_AMAZON = 7_202_611`, `ID_LOCK_AMAZON_BUSCA = 7_202_612`.
  - `@dataclass(frozen=True) class OrigemAmazon(coletor: str, nome: str, id_lock: int, captcha: TipoAviso, pausada: TipoAviso, erro: TipoAviso, efeito_captcha: str, efeito_pausa: str)`; `ORIGEM_BUSCA`, `ORIGEM_MONITOR`.
  - `pagina_curta(url: str) -> str`; `dados_captcha(origem: OrigemAmazon, url: str, extras: tuple[str, ...] = ()) -> Dados`; `dados_pausa(origem: OrigemAmazon, motivo: str, sem_registro: bool = False) -> Dados`.
  - `class VarreduraBase` com atributo de classe `origem: OrigemAmazon`; `__init__(engine, sessoes, fabrica_navegador, avisador, config, relogio=None, rng=None, dormir=time.sleep)`; atributos `_teto: TetoPorHora`, `_erros_seguidos: int`, `_falhas_seguidas: int`, `_avisador`, `_relogio`, `_sessoes`, `_config`; métodos `_obter_navegador() -> NavegadorInterativo`, `fechar_navegador() -> None`, `_contexto(cfg, nome_falha, cota) -> ContextoBusca`, `_pausa_humana(cfg) -> Callable[[], None]`, `_janela(agora, tipo, inicio, fim) -> Janela`, `_inicio_do_passo(agora) -> tuple[ConfigAmazon, EstadoColetorTipo]`, `_pagina_ok() -> None`, `_fechar_por_desafio(s, url, agora) -> None` (gancho, padrão nada), `_registrar_desafio(url, extras=()) -> None`, `_pausar_servico(motivo_banco, motivo, ao_pausar=None) -> float`, `_pausar_por_falhas(ao_pausar=None) -> float`, `tratar_erro(erro) -> float`, `inicializar() -> None`, `passo() -> float` (abstrato), `executar_passo() -> float`, `rodar() -> None`.
  - `tests/fakes_varredura.py`: `SP`, `MEIO_DIA`, `CAPTCHA`, `Relogio`, `FabricaFake` (`abertos`, `fechados`), `criar_laco(classe, engine, sessoes, config, paginas, apos_clique=None, relogio=None) -> tuple[laco, NavegadorInterativoFake, FabricaFake, AvisadorFake, Relogio]`, `confirmado(sessoes, nome, asin, preco=None, lido_em=MEIO_DIA) -> tuple[int, int]`, `livre(sessoes, nome) -> str`, `ofertas(asin, preco) -> Pagina`, `vazia(url) -> Pagina`.

- [ ] **Step 1: Banco da lane**

Run: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_lacos`

- [ ] **Step 2: Helpers dos testes**

Crie `tests/fakes_varredura.py`:

```python
"""Ajudantes dos testes dos dois laços da Amazon (busca e monitor) e da base comum."""

import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fakes import (
    AvisadorFake,
    NavegadorInterativoFake,
    criar_anuncio,
    criar_preco_liga,
    criar_produto,
    html_busca,
    oferta_lista,
    pagina_html,
)
from fakes_ofertas import bloco_oferta, html_ofertas

from tcg_sniper.coletor_amazon.busca import url_busca
from tcg_sniper.coletor_amazon.parsers import url_ofertas
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import Envio, OrigemPreco, StatusCasamento

SP = ZoneInfo("America/Sao_Paulo")
MEIO_DIA = datetime(2026, 10, 15, 12, 0, tzinfo=SP)
CAPTCHA = '<html><body><form action="/errors/validateCaptcha"></form></body></html>'


class Relogio:
    def __init__(self, agora):
        self.agora = agora

    def __call__(self):
        return self.agora


class FabricaFake:
    """Fábrica de navegador: devolve sempre o mesmo navegador falso e conta aberturas e fechamentos."""

    def __init__(self, navegador):
        self.navegador = navegador
        self.abertos = 0
        self.fechados = 0

    def __call__(self):
        fabrica = self

        class Contexto:
            def __enter__(self):
                fabrica.abertos += 1
                return fabrica.navegador

            def __exit__(self, *_exc):
                fabrica.fechados += 1

        return Contexto()


def criar_laco(classe, engine, sessoes, config, paginas, apos_clique=None, relogio=None):
    """Um laço (`VarreduraBusca`, `VarreduraMonitor` ou uma subclasse de teste da base) com navegador,
    avisador e relógio falsos. Devolve (laço, navegador, fábrica, avisador, relógio)."""
    navegador = NavegadorInterativoFake(paginas, apos_clique or [])
    fabrica = FabricaFake(navegador)
    avisador = AvisadorFake()
    relogio = relogio or Relogio(MEIO_DIA)
    laco = classe(
        engine, sessoes, fabrica, avisador, config, relogio=relogio, rng=random.Random(1), dormir=lambda _: None
    )
    return laco, navegador, fabrica, avisador, relogio


def confirmado(sessoes, nome, asin, preco=None, lido_em=MEIO_DIA):
    """Produto (R$ 1.000 na Liga) casado com o anúncio; com `preco`, já lido pelo monitor em `lido_em` com
    essa oferta da Amazon como a melhor. A descoberta do produto só volta daqui a 7 dias."""
    with sessoes() as s, s.begin():
        p = criar_produto(s, nome, nome=nome)
        criar_preco_liga(s, p, "1000.00", listagem_em=MEIO_DIA)
        a = criar_anuncio(s, asin, produto=p, status=StatusCasamento.CONFIRMADO)
        if preco is not None:
            o = oferta_lista(preco, vendedor="Amazon.com.br", seller_id="amazon", envio=Envio.AMAZON, posicao=0)
            repo_amz.gravar_ofertas(s, a.id, lido_em, [repo_amz.OfertaAvaliada(o, None, True, True)])
            repo_amz.registrar_preco(s, a.id, o.preco, OrigemPreco.OFERTAS, None, Envio.AMAZON, lido_em, SP)
        repo_amz.sincronizar_fila(s, MEIO_DIA)
        repo_amz.reagendar(s, p.id, MEIO_DIA, MEIO_DIA + timedelta(days=7), False)
        return p.id, a.id


def livre(sessoes, nome):
    """Produto sem par, vencido na fila da descoberta. Devolve a URL da busca."""
    with sessoes() as s, s.begin():
        p = criar_produto(s, nome, nome=nome)
        criar_preco_liga(s, p, "1000.00", listagem_em=MEIO_DIA)
        repo_amz.sincronizar_fila(s, MEIO_DIA - timedelta(hours=1))
        return url_busca(repo_amz.obter_config(s), nome)


def ofertas(asin, preco):
    return pagina_html(
        html_ofertas(bloco_oferta(preco, "Amazon.com.br", seller_id=None, envia=None, destaque=True)), url=url_ofertas(asin)
    )


def vazia(url):
    return pagina_html(html_busca(), url=url)
```

- [ ] **Step 3: Escrever os testes da base (falham)**

Crie `tests/coletor_amazon/test_varredura_base.py`:

```python
from datetime import timedelta

import pytest
from fakes_varredura import MEIO_DIA, criar_laco

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, TipoAviso
from tcg_sniper.coletor_amazon.varredura_base import (
    ESPERA_ERRO_S,
    ESPERA_OCIOSA_S,
    ORIGEM_BUSCA,
    ORIGEM_MONITOR,
    VarreduraBase,
    dados_captcha,
)
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import COLETOR_AMAZON, COLETOR_AMAZON_BUSCA, EstadoColetorTipo


class LacoDaBusca(VarreduraBase):
    origem = ORIGEM_BUSCA
    acao = staticmethod(lambda: 0)

    def passo(self):
        return self.acao()


class LacoDoMonitor(LacoDaBusca):
    origem = ORIGEM_MONITOR


def estado(sessoes, coletor):
    with sessoes() as s:
        return repo.obter_estado(s, coletor=coletor)


def quebrar():
    raise RuntimeError("navegador fechou")


def test_tres_erros_seguidos_pausam_so_a_propria_origem(engine, sessoes, config, monkeypatch):
    laco, _, fabrica, avisador, _ = criar_laco(LacoDaBusca, engine, sessoes, config, {})
    monkeypatch.setattr(laco, "passo", quebrar)
    assert [laco.executar_passo() for _ in range(3)] == [ESPERA_ERRO_S, ESPERA_ERRO_S, ESPERA_OCIOSA_S]
    busca = estado(sessoes, COLETOR_AMAZON_BUSCA)
    assert (busca.estado, busca.motivo) == (EstadoColetorTipo.PAUSADO, "erros seguidos")
    assert estado(sessoes, COLETOR_AMAZON).estado is EstadoColetorTipo.ATIVO
    assert avisador.tipos() == [TipoAviso.AMAZON_BUSCA_ERRO, TipoAviso.AMAZON_BUSCA_ERRO, TipoAviso.AMAZON_BUSCA_PAUSADA]
    assert avisador.dados(TipoAviso.AMAZON_BUSCA_PAUSADA)[0].linhas[1] == (
        "Com a busca pausada, o monitor e a conferência seguem"
    )


def test_passo_ok_resolve_so_o_erro_da_propria_origem(engine, sessoes, config):
    laco, _, _, avisador, _ = criar_laco(LacoDoMonitor, engine, sessoes, config, {})
    assert laco.executar_passo() == 0
    assert (TipoAviso.AMAZON_ERRO, CHAVE_GERAL) in avisador.resolvidos
    assert (TipoAviso.AMAZON_BUSCA_ERRO, CHAVE_GERAL) not in avisador.resolvidos


def test_desafio_pausa_a_origem_e_avisa_com_o_efeito_e_os_extras(engine, sessoes, config):
    laco, _, _, avisador, _ = criar_laco(LacoDoMonitor, engine, sessoes, config, {})
    laco._registrar_desafio("https://www.amazon.com.br/gp/cart/view.html", ("linha extra",))
    assert estado(sessoes, COLETOR_AMAZON).estado is EstadoColetorTipo.PAUSADO_DESAFIO
    assert estado(sessoes, COLETOR_AMAZON_BUSCA).estado is EstadoColetorTipo.ATIVO
    [(tipo, chave, dados)] = avisador.avisos
    assert (tipo, chave) == (TipoAviso.AMAZON_CAPTCHA, CHAVE_GERAL)
    assert dados.linhas == (
        "Página: /gp/cart/view.html",
        "Monitor e conferência pausados até você retomar; a busca segue",
        "linha extra",
    )


def test_inicio_do_passo_resolve_a_pausa_so_da_propria_origem(engine, sessoes, config):
    laco, _, _, avisador, _ = criar_laco(LacoDaBusca, engine, sessoes, config, {})
    with sessoes() as s, s.begin():
        repo.pausar(s, "falhas seguidas", MEIO_DIA, COLETOR_AMAZON_BUSCA)
    _, situacao = laco._inicio_do_passo(MEIO_DIA)
    assert situacao is EstadoColetorTipo.PAUSADO and avisador.resolvidos == []
    with sessoes() as s, s.begin():
        repo.retomar(s, MEIO_DIA, COLETOR_AMAZON_BUSCA)
    _, situacao = laco._inicio_do_passo(MEIO_DIA)
    assert situacao is EstadoColetorTipo.ATIVO
    assert avisador.resolvidos == [(TipoAviso.AMAZON_BUSCA_PAUSADA, CHAVE_GERAL)]


def test_pausa_que_o_banco_recusa_avisa_e_espera_15_min(engine, sessoes, config, monkeypatch):
    from tcg_sniper.coletor_amazon import varredura_base as modulo

    def recusar(*_a, **_k):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(modulo.repo, "pausar", recusar)
    laco, _, _, avisador, _ = criar_laco(LacoDaBusca, engine, sessoes, config, {})
    chamadas = []
    assert laco._pausar_servico("falhas seguidas", "motivo x", ao_pausar=lambda: chamadas.append(1)) == ESPERA_ERRO_S
    assert chamadas == []  # sem pausa registrada, o gancho (fechar o ciclo) não roda
    assert avisador.dados(TipoAviso.AMAZON_BUSCA_PAUSADA)[0].linhas == (
        "Motivo: motivo x",
        "Não consegui registrar a pausa no banco: nova tentativa em 15 min",
    )


def test_janela_e_sorteada_uma_vez_por_tipo_e_dia(engine, sessoes, config):
    laco, _, _, _, _ = criar_laco(LacoDaBusca, engine, sessoes, config, {})
    with sessoes() as s:
        from tcg_sniper.db import repositorio_amazon as repo_amz

        cfg = repo_amz.obter_config(s)
    a = laco._janela(MEIO_DIA, "busca", cfg.janela_inicio, cfg.janela_fim)
    assert laco._janela(MEIO_DIA + timedelta(hours=1), "busca", cfg.janela_inicio, cfg.janela_fim) is a
    assert laco._janela(MEIO_DIA + timedelta(days=1), "busca", cfg.janela_inicio, cfg.janela_fim) is not a


def test_navegador_que_morre_e_reaberto(engine, sessoes, config):
    laco, navegador, fabrica, _, _ = criar_laco(LacoDaBusca, engine, sessoes, config, {})
    assert laco._obter_navegador() is navegador
    navegador.morto = True
    laco._obter_navegador()
    assert (fabrica.abertos, fabrica.fechados) == (2, 1)
    laco.fechar_navegador()
    assert fabrica.fechados == 2


@pytest.mark.parametrize("origem", [ORIGEM_BUSCA, ORIGEM_MONITOR])
def test_origens_nao_dividem_estado_trava_nem_avisos(origem):
    outra = ORIGEM_MONITOR if origem is ORIGEM_BUSCA else ORIGEM_BUSCA
    assert origem.coletor != outra.coletor and origem.id_lock != outra.id_lock
    assert {origem.captcha, origem.pausada, origem.erro}.isdisjoint({outra.captcha, outra.pausada, outra.erro})
    assert dados_captcha(origem, "https://www.amazon.com.br/s?k=a").linhas[1] == origem.efeito_captcha
```

- [ ] **Step 4: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_lacos uv run pytest -q -p no:cacheprovider tests/coletor_amazon/test_varredura_base.py`
Expected: FAIL (`ModuleNotFoundError: tcg_sniper.coletor_amazon.varredura_base`).

- [ ] **Step 5: Implementar a base**

Crie `src/tcg_sniper/coletor_amazon/varredura_base.py`:

```python
"""Base dos dois serviços da Amazon (`coletor-amazon-busca` e `coletor-amazon`): navegador próprio, janela
do dia com variação, teto por hora, pausa humana entre páginas, CAPTCHA, erro inesperado, pausa por falhas
ou erros seguidos, avisos com a origem no título e o laço `rodar` com trava. Cada serviço tem a própria
linha em `estado_coletor`, a própria trava e os próprios avisos (`OrigemAmazon`): um CAPTCHA, um erro ou
uma pausa num serviço não para o outro.

Este módulo não conhece fila, ciclo, monitor, checkout nem carrinho (ver `varredura_busca.py` e
`varredura_monitor.py`; o teste `test_lacos_separados.py` confere as importações)."""

import logging
import random
import time as relogio_sistema
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from urllib.parse import urlsplit

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.avisos.servico import Avisador
from tcg_sniper.coletor_amazon.busca import ContextoBusca, CotaHtmlFalha
from tcg_sniper.coletor_amazon.fila import Janela, TetoPorHora, janela_do_dia
from tcg_sniper.coletor_liga.agendador import lock_coleta
from tcg_sniper.config import Config
from tcg_sniper.config_banco import carregar_config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import COLETOR_AMAZON, COLETOR_AMAZON_BUSCA, ConfigAmazon, EstadoColetorTipo
from tcg_sniper.navegador.base import NavegadorInterativo
from tcg_sniper.navegador.ritmo import pausa_aleatoria

log = logging.getLogger(__name__)

ESPERA_OCIOSA_S = 60
ESPERA_ERRO_S = 15 * 60
MAX_ERROS_SEGUIDOS = 3
MAX_FALHAS_SEGUIDAS = 10  # páginas seguidas com ErroParser/ErroRede (bloqueio ou layout novo)
ID_LOCK_AMAZON = 7_202_611  # monitor e checkout (o `amazon capturar` usa o mesmo perfil e a mesma trava)
ID_LOCK_AMAZON_BUSCA = 7_202_612


@dataclass(frozen=True)
class OrigemAmazon:
    """Quem é o laço: a linha de `estado_coletor`, a trava e os avisos que só ele abre e resolve."""

    coletor: str
    nome: str  # "busca" | "monitor" (logs)
    id_lock: int
    captcha: TipoAviso
    pausada: TipoAviso
    erro: TipoAviso
    efeito_captcha: str  # linha do aviso de CAPTCHA: o que parou e o que segue
    efeito_pausa: str  # linha do aviso de pausa


ORIGEM_BUSCA = OrigemAmazon(
    coletor=COLETOR_AMAZON_BUSCA,
    nome="busca",
    id_lock=ID_LOCK_AMAZON_BUSCA,
    captcha=TipoAviso.AMAZON_BUSCA_CAPTCHA,
    pausada=TipoAviso.AMAZON_BUSCA_PAUSADA,
    erro=TipoAviso.AMAZON_BUSCA_ERRO,
    efeito_captcha="A busca fica pausada até você retomar; o monitor e a conferência seguem",
    efeito_pausa="Com a busca pausada, o monitor e a conferência seguem",
)
ORIGEM_MONITOR = OrigemAmazon(
    coletor=COLETOR_AMAZON,
    nome="monitor",
    id_lock=ID_LOCK_AMAZON,
    captcha=TipoAviso.AMAZON_CAPTCHA,
    pausada=TipoAviso.AMAZON_PAUSADA,
    erro=TipoAviso.AMAZON_ERRO,
    efeito_captcha="Monitor e conferência pausados até você retomar; a busca segue",
    efeito_pausa="Com o monitor pausado, a retirada automática de item do carrinho também para",
)


def pagina_curta(url: str) -> str:
    partes = urlsplit(url)
    return (partes.path or "/") + (f"?{partes.query}" if partes.query else "")


def dados_captcha(origem: OrigemAmazon, url: str, extras: tuple[str, ...] = ()) -> Dados:
    return Dados(linhas=(f"Página: {pagina_curta(url)}", origem.efeito_captcha, *extras))


def dados_pausa(origem: OrigemAmazon, motivo: str, sem_registro: bool = False) -> Dados:
    if sem_registro:  # o banco recusou a pausa: o serviço segue e tenta de novo
        return Dados(linhas=(f"Motivo: {motivo}", "Não consegui registrar a pausa no banco: nova tentativa em 15 min"))
    return Dados(linhas=(f"Motivo: {motivo}", origem.efeito_pausa))


class VarreduraBase:
    """Laço de um serviço da Amazon. A subclasse define `origem` e `passo()` (no máximo um trabalho por
    passo; devolve quantos segundos dormir)."""

    origem: OrigemAmazon

    def __init__(
        self,
        engine: Engine,
        sessoes: sessionmaker[Session],
        fabrica_navegador: Callable[[], AbstractContextManager[NavegadorInterativo]],
        avisador: Avisador,
        config: Config,
        relogio: Callable[[], datetime] | None = None,
        rng: random.Random | None = None,
        dormir: Callable[[float], None] = relogio_sistema.sleep,
    ):
        self._engine = engine
        self._sessoes = sessoes
        self._fabrica_navegador = fabrica_navegador
        self._avisador = avisador
        self._config_env = config
        self._config = config
        self._relogio = relogio or (lambda: datetime.now(UTC))
        self._rng = rng or random.Random()
        self._dormir = dormir
        self._janelas: dict[tuple[str, date, time, time, str], Janela] = {}
        self._teto = TetoPorHora()  # páginas (ou buscas) deste serviço; nunca divide vaga com o outro
        self._erros_seguidos = 0
        self._falhas_seguidas = 0
        self._contexto_navegador: AbstractContextManager[NavegadorInterativo] | None = None
        self._navegador: NavegadorInterativo | None = None

    # --- navegador -------------------------------------------------------------------------------

    def _obter_navegador(self) -> NavegadorInterativo:
        if self._navegador is not None:
            if self._navegador.vivo():
                return self._navegador
            log.warning("navegador da Amazon (%s) não responde; abrindo outro", self.origem.nome)
            self.fechar_navegador()
        contexto = self._fabrica_navegador()
        self._navegador = contexto.__enter__()
        self._contexto_navegador = contexto
        return self._navegador

    def fechar_navegador(self) -> None:
        contexto = self._contexto_navegador
        self._contexto_navegador = self._navegador = None
        if contexto is None:
            return
        try:
            contexto.__exit__(None, None, None)
        except Exception:  # instância possivelmente morta: só registra
            log.warning("erro ao fechar o navegador da Amazon (%s)", self.origem.nome, exc_info=True)

    def _contexto(self, cfg: ConfigAmazon, nome_falha: str, cota: CotaHtmlFalha) -> ContextoBusca:
        return ContextoBusca(
            sessoes=self._sessoes,
            navegador=self._obter_navegador(),
            avisador=self._avisador,
            config=self._config,
            cfg=cfg,
            relogio=self._relogio,
            dormir=self._dormir,
            rng=self._rng,
            nome_falha=nome_falha,
            cota_falhas=cota,
        )

    def _pausa_humana(self, cfg: ConfigAmazon) -> Callable[[], None]:
        return lambda: pausa_aleatoria(cfg.pausa_min_s, cfg.pausa_max_s, self._dormir, self._rng)

    def _janela(self, agora: datetime, tipo: str, inicio: time, fim: time) -> Janela:
        dia = agora.astimezone(self._config.zona).date()
        chave = (tipo, dia, inicio, fim, self._config.fuso)
        if chave not in self._janelas:
            self._janelas[chave] = janela_do_dia(dia, inicio, fim, self._config.zona, self._rng)
        return self._janelas[chave]

    # --- estado e avisos -------------------------------------------------------------------------

    def _inicio_do_passo(self, agora: datetime) -> tuple[ConfigAmazon, EstadoColetorTipo]:
        """Relê a configuração (Geral e Amazon) e o estado deste serviço; ativo fecha a pausa aberta dele."""
        self._config = carregar_config(self._sessoes, self._config_env)
        with self._sessoes() as s, s.begin():
            cfg = repo_amz.obter_config(s)
            estado = repo.obter_estado(s, agora, self.origem.coletor).estado
        if estado is EstadoColetorTipo.ATIVO:
            self._avisador.resolver(self.origem.pausada, CHAVE_GERAL)  # retomada: a pausa acabou
        return cfg, estado

    def _pagina_ok(self) -> None:
        """Uma página abriu sem CAPTCHA neste navegador: o CAPTCHA aberto deste serviço está resolvido."""
        self._avisador.resolver(self.origem.captcha, CHAVE_GERAL)

    def _fechar_por_desafio(self, s: Session, url: str, agora: datetime) -> None:
        """Gancho: o que fechar na mesma transação da pausa por CAPTCHA (a busca fecha o ciclo aberto)."""

    def _registrar_desafio(self, url: str, extras: tuple[str, ...] = ()) -> None:
        agora = self._relogio()
        with self._sessoes() as s, s.begin():
            self._fechar_por_desafio(s, url, agora)
            repo.pausar_por_desafio(s, f"desafio em {url}", agora, self.origem.coletor)
        log.warning("CAPTCHA na Amazon (%s) em %s; serviço pausado", self.origem.nome, url)
        self._avisador.avisar(self.origem.captcha, CHAVE_GERAL, dados_captcha(self.origem, url, extras))

    def _pausar_servico(self, motivo_banco: str, motivo: str, ao_pausar: Callable[[], None] | None = None) -> float:
        """Pausa este serviço (só volta com Retomar). `ao_pausar` roda só se a pausa foi gravada."""
        try:
            with self._sessoes() as s, s.begin():
                repo.pausar(s, motivo_banco, self._relogio(), self.origem.coletor)
        except Exception:
            log.exception("não foi possível registrar a pausa da Amazon (%s)", self.origem.nome)
            self._avisador.avisar(self.origem.pausada, CHAVE_GERAL, dados_pausa(self.origem, motivo, sem_registro=True))
            return ESPERA_ERRO_S
        log.warning("Amazon (%s) pausada: %s", self.origem.nome, motivo)
        if ao_pausar is not None:
            ao_pausar()
        self._avisador.avisar(self.origem.pausada, CHAVE_GERAL, dados_pausa(self.origem, motivo))
        return ESPERA_OCIOSA_S

    def _pausar_por_falhas(self, ao_pausar: Callable[[], None] | None = None) -> float:
        """Bloqueio sem CAPTCHA ou layout novo: toda página falha. Pausa em vez de seguir no ritmo normal."""
        self._falhas_seguidas = 0
        motivo = f"{MAX_FALHAS_SEGUIDAS} páginas seguidas com falha (bloqueio ou layout novo?)"
        return self._pausar_servico("falhas seguidas", motivo, ao_pausar)

    def tratar_erro(self, erro: Exception) -> float:
        """Erro inesperado num passo: avisa e espera; três seguidos pausam este serviço."""
        log.error("erro inesperado na Amazon (%s)", self.origem.nome, exc_info=erro)
        self.fechar_navegador()
        self._erros_seguidos += 1
        if self._erros_seguidos >= MAX_ERROS_SEGUIDOS:
            self._erros_seguidos = 0
            motivo = f"{MAX_ERROS_SEGUIDOS} erros inesperados seguidos (último: {erro!r})"
            return self._pausar_servico("erros seguidos", motivo)
        self._avisador.avisar(self.origem.erro, CHAVE_GERAL, Dados(linhas=(f"Erro: {erro!r}",)))
        return ESPERA_ERRO_S

    # --- laço ------------------------------------------------------------------------------------

    def inicializar(self) -> None:
        self._config = carregar_config(self._sessoes, self._config_env)

    def passo(self) -> float:
        raise NotImplementedError

    def executar_passo(self) -> float:
        """Um passo protegido: erro inesperado vira aviso/espera; passo ok fecha o erro aberto deste serviço."""
        try:
            espera = self.passo()
        except Exception as erro:  # noqa: BLE001 - qualquer falha inesperada vira espera/pausa
            return self.tratar_erro(erro)
        self._avisador.resolver(self.origem.erro, CHAVE_GERAL)
        return espera

    def rodar(self) -> None:
        try:
            with lock_coleta(self._engine, self.origem.id_lock) as obtido:
                if not obtido:
                    log.error("outra varredura da Amazon (%s) já está rodando; saindo", self.origem.nome)
                    return
                self.inicializar()
                log.info("varredura da Amazon (%s) iniciada", self.origem.nome)
                while True:
                    espera = self.executar_passo()
                    if espera > 0:
                        self._dormir(espera)
        finally:
            # SIGTERM vira SystemExit: fecha o navegador que tenha ficado aberto por um CAPTCHA.
            self.fechar_navegador()
```

- [ ] **Step 6: Rodar os testes da base**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_lacos uv run pytest -q -p no:cacheprovider tests/coletor_amazon/test_varredura_base.py`
Expected: PASS.

- [ ] **Step 7: Suíte inteira, ruff e commit**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_lacos uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde (o `varredura.py` antigo continua intacto nesta tarefa).

```bash
git add src/tcg_sniper/coletor_amazon/varredura_base.py tests/fakes_varredura.py tests/coletor_amazon/test_varredura_base.py
git commit -m "feat: shared base for the Amazon search and monitor loops"
```

---

### Task 4: Laço da busca (lane `lacos`, depois da Task 3)

**Files:**
- Create: `src/tcg_sniper/coletor_amazon/varredura_busca.py`
- Move+Modify: `tests/coletor_amazon/test_varredura.py` → `tests/coletor_amazon/test_varredura_busca.py`

**Interfaces:**
- Consumes (Task 3): `VarreduraBase`, `ORIGEM_BUSCA`, `ESPERA_OCIOSA_S`, `MAX_FALHAS_SEGUIDAS`, `_inicio_do_passo`, `_janela`, `_contexto`, `_teto`, `_pagina_ok`, `_registrar_desafio`, `_fechar_por_desafio`, `_pausar_por_falhas(ao_pausar)`, `fakes_varredura.*`. De hoje: `busca.processar_produto`, `busca.DesafioAmazon`, `busca.CotaHtmlFalha`, `fila.intervalo_busca`, `termo.sequencia_de_termos`, `repo_amz.sincronizar_fila/ids_na_fila/proximo_da_fila/reagendar/fechar_oportunidades_sem_leitura`, `repo_termos.termos_do_produto/em_seca`, `repo.iniciar_coleta/finalizar_coleta/status_final/marcar_interrompidas`.
- Produces: `tcg_sniper.coletor_amazon.varredura_busca.VarreduraBusca(VarreduraBase)` (mesmo construtor da base; `rodar()`, `inicializar()`, `passo()`), `TIPOS_AMAZON = (TipoColeta.AMAZON,)`. O módulo **não** importa `checkout`, `cliques`, `monitor`, `parsers_checkout` nem `varredura_monitor`.

- [ ] **Step 1: Portar os testes da busca (falham)**

Run: `git mv tests/coletor_amazon/test_varredura.py tests/coletor_amazon/test_varredura_busca.py`

No arquivo movido:

1. Troque o bloco de imports do topo até `ciclos(...)` por:

```python
from datetime import datetime, time, timedelta

import pytest
from fakes import AvisadorFake, cartao_busca, criar_preco_liga, criar_produto, html_busca, pagina_html
from fakes_checkout import carrinho
from fakes_varredura import CAPTCHA, MEIO_DIA, SP, Relogio, confirmado, criar_laco, livre, vazia
from sqlalchemy import select

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, TipoAviso
from tcg_sniper.coletor_amazon.busca import url_busca
from tcg_sniper.coletor_amazon.config import aplicar_config
from tcg_sniper.coletor_amazon.parsers import URL_CARRINHO, url_ofertas
from tcg_sniper.coletor_amazon.varredura_base import ESPERA_ERRO_S, ESPERA_OCIOSA_S, MAX_FALHAS_SEGUIDAS
from tcg_sniper.coletor_amazon.varredura_busca import VarreduraBusca
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_termos as repo_termos
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    COLETOR_AMAZON_BUSCA,
    AnuncioAmazon,
    Coleta,
    ConferenciaCheckout,
    EstadoColetorTipo,
    FilaAmazon,
    ProdutoLiga,
    SituacaoCheckout,
    StatusColeta,
    TipoColeta,
)
from tcg_sniper.notificador.base import Destino


def produtos(sessoes, *nomes):
    with sessoes() as s, s.begin():
        criados = []
        for nome in nomes:
            p = criar_produto(s, nome, nome=nome)
            criar_preco_liga(s, p, "1000.00", listagem_em=MEIO_DIA)
            criados.append(p)
        cfg = repo_amz.obter_config(s)
        return criados, {p.id: url_busca(cfg, p.nome) for p in criados}


def varredura(engine, sessoes, config, paginas, relogio=None):
    v, navegador, fabrica, avisador, _ = criar_laco(VarreduraBusca, engine, sessoes, config, paginas, relogio=relogio)
    return v, navegador, fabrica, avisador


def ciclos(sessoes):
    with sessoes() as s:
        return list(s.scalars(select(Coleta).where(Coleta.tipo == TipoColeta.AMAZON).order_by(Coleta.id)))
```

Apague as definições locais de `SP`, `MEIO_DIA`, `CAPTCHA`, `Relogio`, `FabricaFake` e `vazia` (vêm de `fakes_varredura`). Ao fim, rode `uv run ruff check tests/coletor_amazon/test_varredura_busca.py --fix` só para tirar imports que sobrarem sem uso (não aceite outra correção automática sem ler).

2. Substituições mecânicas no arquivo inteiro: `COLETOR_AMAZON)` → `COLETOR_AMAZON_BUSCA)` (em `repo.pausar`, `repo.retomar` e `repo.obter_estado(..., coletor=...)`); `TipoAviso.AMAZON_CAPTCHA` → `TipoAviso.AMAZON_BUSCA_CAPTCHA`; `TipoAviso.AMAZON_PAUSADA` → `TipoAviso.AMAZON_BUSCA_PAUSADA`; `TipoAviso.AMAZON_ERRO` → `TipoAviso.AMAZON_BUSCA_ERRO`; `from tcg_sniper.coletor_amazon import varredura as modulo` → `from tcg_sniper.coletor_amazon import varredura_busca as modulo` (os `monkeypatch.setattr(modulo, "processar_produto", ...)` e `monkeypatch.setattr(modulo.repo, "pausar", ...)` continuam valendo: `modulo.repo` é o mesmo módulo `repositorio`).

3. Substitua `test_captcha_pausa_avisa_e_mantem_o_navegador` por:

```python
def test_captcha_pausa_so_a_busca_avisa_e_mantem_o_navegador(engine, sessoes, config):
    _, urls = produtos(sessoes, "a")
    [url] = urls.values()
    v, _, fabrica, avisador = varredura(engine, sessoes, config, {url: pagina_html(CAPTCHA, url=url)})
    assert v.passo() == ESPERA_OCIOSA_S
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON_BUSCA).estado is EstadoColetorTipo.PAUSADO_DESAFIO
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.ATIVO
    [ciclo] = ciclos(sessoes)
    assert ciclo.status is StatusColeta.PAUSADA_DESAFIO
    [(destino, texto)] = avisador.mensagens
    assert destino is Destino.ADMIN
    [(tipo, chave, dados)] = avisador.avisos
    assert (tipo, chave) == (TipoAviso.AMAZON_BUSCA_CAPTCHA, CHAVE_GERAL)
    assert dados.linhas[1] == "A busca fica pausada até você retomar; o monitor e a conferência seguem"
    assert "Amazon (busca) · CAPTCHA" in texto and "noVNC da busca (porta 6082)" in texto
    assert fabrica.fechados == 0
```

4. Em `test_mensagem_do_captcha_nunca_leva_o_host_salvo`, troque `"porta 6081" in texto` por `"porta 6082" in texto`.

5. Em `test_inicializar_so_marca_os_ciclos_da_amazon`, acrescente ao fim:

```python
    [dados] = avisador.dados(TipoAviso.AMAZON_INTERROMPIDA)
    assert dados.linhas == ("1 ciclo(s) marcado(s) como falha: o serviço de busca reiniciou",)
```

6. Acrescente ao fim do arquivo:

```python
def test_descoberta_so_de_nao_casados_e_casados_com_7_dias(engine, sessoes, config):
    url_livre = livre(sessoes, "livre")
    confirmado(sessoes, "recente", "B0RECE0001", "990.00")
    velho_id, _ = confirmado(sessoes, "velho", "B0VELH0001", "990.00")
    with sessoes() as s, s.begin():
        repo_amz.reagendar(s, velho_id, MEIO_DIA - timedelta(days=8), MEIO_DIA - timedelta(days=1), False)
        url_velho = url_busca(repo_amz.obter_config(s), "velho")
    paginas = {u: pagina_html(html_busca(), url=u) for u in (url_livre, url_velho)}
    v, navegador, _, _ = varredura(engine, sessoes, config, paginas)
    v.passo()
    v.passo()
    assert v.passo() == ESPERA_OCIOSA_S
    assert sorted(navegador.visitadas) == sorted([url_livre, url_velho])


def test_busca_nunca_le_ofertas_nem_abre_o_carrinho(engine, sessoes, config):
    """Anúncio vencido no monitor, candidata ao checkout e item preso no carrinho: a busca ignora tudo."""
    _, anuncio_id = confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    confirmado(sessoes, "venc", "B0VENC0001")  # nunca lido: vencido
    with sessoes() as s, s.begin():
        repo_amz.registrar_conferencia(
            s, em=MEIO_DIA - timedelta(minutes=5), anuncio_id=anuncio_id, vendedor_nome="Amazon.com.br",
            preco_anunciado=Decimal("700.00"), itens=None, frete=None, impostos=None, total=None,
            situacao=SituacaoCheckout.FALHA, motivo="em andamento", item_removido=False,
        )
    url = livre(sessoes, "livre")
    paginas = {url: vazia(url), URL_CARRINHO: carrinho(), url_ofertas("B0VENC0001"): vazia(url_ofertas("B0VENC0001"))}
    v, navegador, _, _ = varredura(engine, sessoes, config, paginas)
    assert v.passo() == 0
    assert v.passo() == ESPERA_OCIOSA_S
    assert navegador.visitadas == [url] and navegador.cliques == []
    with sessoes() as s:
        assert [c.item_removido for c in s.scalars(select(ConferenciaCheckout))] == [False]


def test_busca_segue_a_propria_janela_e_nao_a_do_monitor(engine, sessoes, config):
    url = livre(sessoes, "livre")
    with sessoes() as s, s.begin():
        aplicar_config(s, {"monitor_janela_inicio": time(14, 0)}, MEIO_DIA)  # monitor fechado ao meio-dia
    v, navegador, _, _ = varredura(engine, sessoes, config, {url: vazia(url)})
    assert v.passo() == 0 and navegador.visitadas == [url]
    url2 = livre(sessoes, "livre2")  # vencido: só a janela da busca o segura
    with sessoes() as s, s.begin():
        aplicar_config(s, {"monitor_janela_inicio": time(8, 0), "janela_inicio": time(14, 0)}, MEIO_DIA)
    v2, navegador2, _, _ = varredura(engine, sessoes, config, {url2: vazia(url2)})
    assert v2.passo() == ESPERA_OCIOSA_S and navegador2.visitadas == []


def test_busca_segue_o_proprio_teto_e_nao_o_do_monitor(engine, sessoes, config):
    _, urls = produtos(sessoes, "a", "b")
    with sessoes() as s, s.begin():
        aplicar_config(s, {"max_buscas_hora": 1, "monitor_max_paginas_hora": 1000}, MEIO_DIA)
    relogio = Relogio(MEIO_DIA)
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()}, relogio)
    assert v.passo() == 0
    assert v.passo() == ESPERA_OCIOSA_S
    relogio.agora += timedelta(minutes=61)
    assert v.passo() == 0
    assert len(navegador.visitadas) == 2
```

(Acrescente `from decimal import Decimal` no topo do arquivo.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_lacos uv run pytest -q -p no:cacheprovider tests/coletor_amazon/test_varredura_busca.py`
Expected: FAIL (`ModuleNotFoundError: tcg_sniper.coletor_amazon.varredura_busca`).

- [ ] **Step 3: Implementar o laço da busca**

Crie `src/tcg_sniper/coletor_amazon/varredura_busca.py`:

```python
"""Serviço `coletor-amazon-busca`: a descoberta (fila de buscas) num navegador próprio, sem login. Por
passo, no máximo uma busca: sincroniza a fila, pega o produto vencido há mais tempo, escolhe o termo
(português, inglês e, na seca, os termos guardados da IA), busca, reagenda e fecha o ciclo quando não sobra
busca pendente. Só dentro de `janela_inicio`–`janela_fim` e com o teto `max_buscas_hora`.

Não importa checkout, carrinho nem monitor (teste `test_lacos_separados.py`): este navegador nunca abre o
carrinho nem a conta.

Avisos de fim: `AMAZON_BUSCA_CONCLUIDA`/`PARCIAL`/`FALHOU` só quando o ciclo termina de verdade (sem busca
pendente; uma pausa no meio só avisa a pausa, e a janela que fecha no meio não avisa)."""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.avisos.formato import formatar_duracao
from tcg_sniper.coletor_amazon.busca import CotaHtmlFalha, DesafioAmazon, processar_produto
from tcg_sniper.coletor_amazon.fila import intervalo_busca
from tcg_sniper.coletor_amazon.termo import sequencia_de_termos
from tcg_sniper.coletor_amazon.varredura_base import (
    ESPERA_OCIOSA_S,
    MAX_FALHAS_SEGUIDAS,
    ORIGEM_BUSCA,
    VarreduraBase,
)
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_termos as repo_termos
from tcg_sniper.db.models import ConfigAmazon, EstadoColetorTipo, ProdutoLiga, StatusColeta, TipoColeta
from tcg_sniper.navegador.modelos import ErroRede
from tcg_sniper.parsing import ErroParser

log = logging.getLogger(__name__)

TIPOS_AMAZON = (TipoColeta.AMAZON,)


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


class VarreduraBusca(VarreduraBase):
    origem = ORIGEM_BUSCA

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ciclo: int | None = None
        self._pendentes: set[int] = set()
        self._ok = 0
        self._falha = 0
        self._ciclo_inicio: datetime | None = None
        self._cota_falhas = CotaHtmlFalha()

    def inicializar(self) -> None:
        super().inicializar()
        with self._sessoes() as s, s.begin():
            interrompidos = repo.marcar_interrompidas(s, self._relogio(), TIPOS_AMAZON)
        if interrompidos:
            log.warning("%d ciclo(s) da busca na Amazon interrompido(s) marcados como falha", interrompidos)
            dados = Dados(linhas=(f"{interrompidos} ciclo(s) marcado(s) como falha: o serviço de busca reiniciou",))
            self._avisador.avisar(TipoAviso.AMAZON_INTERROMPIDA, CHAVE_GERAL, dados)

    def passo(self) -> float:
        """No máximo uma busca. Devolve quantos segundos dormir antes do próximo passo."""
        agora = self._relogio()
        cfg, estado = self._inicio_do_passo(agora)
        if not self._janela(agora, "busca", cfg.janela_inicio, cfg.janela_fim).contem(agora):
            self._encerrar_ciclo(cfg)
            self.fechar_navegador()
            return ESPERA_OCIOSA_S
        if estado is not EstadoColetorTipo.ATIVO:
            return ESPERA_OCIOSA_S  # pausada (o navegador fica aberto num CAPTCHA, para resolver no noVNC)
        return self._passo_descoberta(agora, cfg)

    # --- ciclo -----------------------------------------------------------------------------------

    def _iniciar_ciclo(self, agora: datetime, na_fila: set[int]) -> None:
        with self._sessoes() as s, s.begin():
            self._ciclo = repo.iniciar_coleta(s, TipoColeta.AMAZON, agora).id
        self._pendentes = set(na_fila)
        self._ok = self._falha = 0
        self._ciclo_inicio = agora
        self._cota_falhas = CotaHtmlFalha()

    def _encerrar_ciclo(self, cfg: ConfigAmazon, por_pausa: bool = False) -> None:
        """Fecha o ciclo. Só avisa o fim (concluída, parcial ou falhou) quando o ciclo terminou de verdade:
        sem busca pendente e sem ser por uma pausa (que já tem o próprio aviso). A janela que fecha no meio
        do ciclo fecha a coleta sem aviso."""
        if self._ciclo is None:
            return
        status = repo.status_final(self._ok, self._falha, cfg.limite_falha_pct)
        with self._sessoes() as s, s.begin():
            repo.finalizar_coleta(s, self._ciclo, status, self._ok, self._falha, self._relogio())
        log.info("ciclo %s da busca terminou: %s (%d ok, %d falhas)", self._ciclo, status.value, self._ok, self._falha)
        if not por_pausa and not self._pendentes and self._ok + self._falha:
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
        self._ciclo = None
        self._ciclo_inicio = None
        self._pendentes = set()

    def _fechar_por_desafio(self, s: Session, url: str, agora: datetime) -> None:
        if self._ciclo is not None:
            repo.finalizar_coleta(
                s, self._ciclo, StatusColeta.PAUSADA_DESAFIO, self._ok, self._falha, agora, erro=f"desafio em {url}"
            )
        self._ciclo = None
        self._pendentes = set()

    # --- descoberta ------------------------------------------------------------------------------

    def _passo_descoberta(self, agora: datetime, cfg: ConfigAmazon) -> float:
        if self._teto.liberado_em(agora, cfg.max_buscas_hora) is not None:
            return ESPERA_OCIOSA_S
        with self._sessoes() as s, s.begin():
            repo_amz.sincronizar_fila(s, agora)
            na_fila = repo_amz.ids_na_fila(s, agora, cfg.descoberta_casados_dias)
            item = repo_amz.proximo_da_fila(s, agora, cfg.descoberta_casados_dias)
            produto = s.get(ProdutoLiga, item.produto_id) if item else None
            entrou_em = item.entrou_em if item else None
            termo, proximo_indice = None, 0
            if item and produto:
                # Português, inglês (se houver) e, na seca (7 dias sem par novo), os termos guardados da IA.
                alternativos = (
                    [t.termo for t in repo_termos.termos_do_produto(s, produto.id)]
                    if repo_termos.em_seca(s, produto.id, agora)
                    else []
                )
                sequencia = sequencia_de_termos(produto.nome, produto.nome_en, alternativos)
                indice = item.indice_termo % len(sequencia)
                termo, proximo_indice = sequencia[indice], (indice + 1) % len(sequencia)
            ultimo_candidato_em = item.ultimo_candidato_em if item else None
        self._pendentes &= na_fila  # produto desativado na Liga (ou casado) sai do ciclo
        if self._ciclo is not None and not self._pendentes:
            self._encerrar_ciclo(cfg)
        if produto is None:
            return ESPERA_OCIOSA_S
        if self._ciclo is None:
            self._iniciar_ciclo(agora, na_fila)

        contexto = self._contexto(cfg, f"amazon-{self._ciclo}-{produto.id}", self._cota_falhas)
        teve_candidato = False
        try:
            teve_candidato = processar_produto(contexto, produto, termo).candidatos > 0
            self._ok += 1
            self._falhas_seguidas = 0
            self._pagina_ok()
        except DesafioAmazon as desafio:
            self._registrar_desafio(desafio.url)
            return ESPERA_OCIOSA_S
        except (ErroParser, ErroRede) as erro:
            self._falha += 1
            self._falhas_seguidas += 1
            log.warning("busca do produto %s na Amazon falhou: %s", produto.id, erro)
        except Exception:
            # Um produto que quebra não pode travar a fila: conta falha, reagenda e deixa o erro subir.
            self._falha += 1
            depois = self._relogio()
            try:
                with self._sessoes() as s, s.begin():
                    repo_amz.reagendar(
                        s, produto.id, depois, depois + timedelta(minutes=cfg.intervalo_busca_min), False, proximo_indice
                    )
            except Exception:
                log.exception("não foi possível reagendar o produto %s da Amazon", produto.id)
            self._pendentes.discard(produto.id)
            if not self._pendentes:
                self._encerrar_ciclo(cfg)
            raise
        self._erros_seguidos = 0
        self._teto.registrar(agora)

        depois = self._relogio()
        candidato_em = depois if teve_candidato else ultimo_candidato_em
        proxima = depois + intervalo_busca(cfg.intervalo_busca_min, depois, candidato_em, entrou_em)
        with self._sessoes() as s, s.begin():
            repo_amz.reagendar(s, produto.id, depois, proxima, teve_candidato, proximo_indice)
            repo_amz.fechar_oportunidades_sem_leitura(s, depois)
        self._pendentes.discard(produto.id)
        if self._falhas_seguidas >= MAX_FALHAS_SEGUIDAS:  # antes do fim do ciclo: a pausa leva o aviso
            return self._pausar_por_falhas(lambda: self._encerrar_ciclo(cfg, por_pausa=True))
        if not self._pendentes:
            self._encerrar_ciclo(cfg)
        return 0
```

- [ ] **Step 4: Rodar os testes da busca**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_lacos uv run pytest -q -p no:cacheprovider tests/coletor_amazon/test_varredura_busca.py tests/coletor_amazon/test_varredura_base.py`
Expected: PASS. (Se `test_falhas_seguidas_pausam_a_busca` ou `test_ciclo_que_termina_com_a_pausa_so_avisa_a_pausa` conferirem a linha 2 do aviso de pausa, o texto novo é "Com a busca pausada, o monitor e a conferência seguem".)

- [ ] **Step 5: Suíte inteira, ruff e commit**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_lacos uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde (o `varredura.py` antigo e `test_varredura_monitor.py` continuam até a Task 5).

```bash
git add src/tcg_sniper/coletor_amazon/varredura_busca.py tests/coletor_amazon/test_varredura_busca.py
git commit -m "feat: Amazon search loop as its own service loop"
```

---

### Task 5: Laço do monitor, rodada por volta e separação garantida (lane `lacos`, depois da Task 4)

**Files:**
- Create: `src/tcg_sniper/coletor_amazon/varredura_monitor.py`
- Delete: `src/tcg_sniper/coletor_amazon/varredura.py`
- Modify: `src/tcg_sniper/db/repositorio_amazon.py` (nova `ids_vencidos_do_monitor`, logo depois de `proximo_do_monitor` ~502-514)
- Modify: `src/tcg_sniper/cli.py:130-143` (ramo `coletor-amazon`) e `:213` (import de `ID_LOCK_AMAZON`)
- Modify: `tests/coletor_amazon/test_varredura_monitor.py`, `tests/test_cli.py:68-90`
- Test: `tests/coletor_amazon/test_amazon_servicos_separados.py` (novo), `tests/coletor_amazon/test_lacos_separados.py` (novo), `tests/db/test_repositorio_monitor.py` (acrescentar)

**Interfaces:**
- Consumes (Tasks 3–4): `VarreduraBase`, `ORIGEM_MONITOR`, `ESPERA_OCIOSA_S`, `MAX_FALHAS_SEGUIDAS`, `ID_LOCK_AMAZON`, `VarreduraBusca`, `fakes_varredura.*`. De hoje: `checkout.conferir`, `checkout.AlvoCheckout`, `monitor.ler_anuncio/redecidir/aplicar_conferencia`, `cliques.*`, `parse_carrinho`, `repo_amz.*` do monitor e do checkout.
- Produces:
  - `repositorio_amazon.ids_vencidos_do_monitor(s: Session, agora: datetime, intervalo_min: int) -> set[int]`.
  - `tcg_sniper.coletor_amazon.varredura_monitor.VarreduraMonitor(VarreduraBase)`; constantes `ESPERA_RETIRADA`, `RETIRADA_AUTOMATICA_MAX`, `MAX_TENTATIVAS_RETIRADA`, `ERROS_DE_PAGINA`, `MOTIVO_EM_ANDAMENTO`; `linha_do_carrinho(asin: str) -> str`, `dados_conferir_a_mao(asin, razao) -> Dados`, `DADOS_SEM_LOGIN`.
  - `cli.py`: `coletor-amazon` roda `varredura_monitor.VarreduraMonitor` com o perfil `perfil-amazon` e a batida `"amazon"` (igual a hoje); `amazon capturar` trava `varredura_base.ID_LOCK_AMAZON`. A Task 6 acrescenta o ramo `coletor-amazon-busca`.

- [ ] **Step 1: Teste do repositório (falha)**

Acrescente a `tests/db/test_repositorio_monitor.py`:

```python
def test_ids_vencidos_do_monitor_sao_os_confirmados_ativos_nunca_lidos_ou_vencidos(s):
    nunca = confirmado(s, "B0NUNC0001")
    velho = confirmado(s, "B0VELH0001")
    novo = confirmado(s, "B0NOVO0001")
    inativo = confirmado(s, "B0INAT0001", ativo=False)
    ler(s, velho, T0 - timedelta(minutes=20), oferta_lista("990.00", posicao=0))
    ler(s, novo, T0 - timedelta(minutes=5), oferta_lista("990.00", posicao=0))
    assert repo.ids_vencidos_do_monitor(s, T0, 15) == {nunca.id, velho.id}
    assert inativo.id not in repo.ids_vencidos_do_monitor(s, T0, 15)
```

(Se `ler(...)` do arquivo tiver outra assinatura, use a mesma chamada que `test_proximo_do_monitor_nunca_lido_primeiro_depois_o_mais_antigo` usa.)

- [ ] **Step 2: Testes de importação (falham)**

Crie `tests/coletor_amazon/test_lacos_separados.py`:

```python
"""Os dois serviços da Amazon são funções distintas: a busca não alcança checkout, carrinho nem monitor;
o monitor não alcança a busca."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
PACOTE = SRC / "tcg_sniper" / "coletor_amazon"
CA = "tcg_sniper.coletor_amazon"
CHECKOUT_E_MONITOR = {f"{CA}.checkout", f"{CA}.cliques", f"{CA}.parsers_checkout", f"{CA}.monitor", f"{CA}.captura"}


def _arquivo(modulo: str) -> Path | None:
    base = SRC / Path(*modulo.split("."))
    if base.with_suffix(".py").exists():
        return base.with_suffix(".py")
    if (base / "__init__.py").exists():
        return base / "__init__.py"
    return None


def importados(modulo: str) -> set[str]:
    """Módulos do tcg_sniper que `modulo` alcança, direta ou indiretamente (também imports dentro de funções)."""
    vistos: set[str] = set()
    fila = [modulo]
    while fila:
        atual = fila.pop()
        if atual in vistos:
            continue
        vistos.add(atual)
        arquivo = _arquivo(atual)
        if arquivo is None:
            continue
        for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
            if isinstance(no, ast.ImportFrom) and no.module and no.module.startswith("tcg_sniper"):
                fila.append(no.module)
                fila.extend(f"{no.module}.{a.name}" for a in no.names)
            elif isinstance(no, ast.Import):
                fila.extend(a.name for a in no.names if a.name.startswith("tcg_sniper"))
    return {m for m in vistos if _arquivo(m) is not None} - {modulo}


def test_laco_da_busca_nao_alcanca_checkout_carrinho_nem_monitor():
    alcancados = importados(f"{CA}.varredura_busca")
    assert alcancados & (CHECKOUT_E_MONITOR | {f"{CA}.varredura_monitor"}) == set()


def test_laco_do_monitor_nao_alcanca_o_da_busca():
    assert f"{CA}.varredura_busca" not in importados(f"{CA}.varredura_monitor")


def test_base_nao_alcanca_nenhum_dos_lacos_nem_o_checkout():
    alcancados = importados(f"{CA}.varredura_base")
    assert alcancados & (CHECKOUT_E_MONITOR | {f"{CA}.varredura_busca", f"{CA}.varredura_monitor"}) == set()


def test_monitor_nao_chama_nada_da_fila_de_buscas():
    codigo = (PACOTE / "varredura_monitor.py").read_text(encoding="utf-8")
    for nome in ("processar_produto", "sincronizar_fila", "proximo_da_fila", "reagendar", "sequencia_de_termos",
                 "iniciar_coleta", "marcar_interrompidas"):
        assert nome not in codigo, nome


def _nomes_usados(arquivo: Path) -> set[str]:
    nomes = set()
    for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Name):
            nomes.add(no.id)
        elif isinstance(no, ast.Attribute):
            nomes.add(no.attr)
        elif isinstance(no, ast.alias):
            nomes.add(no.name)
    return nomes


def test_busca_nao_clica_nem_mexe_no_carrinho():
    proibidos = {"clicar", "clicar_permitido", "clicar_contando", "remover_do_carrinho", "URL_CARRINHO",
                 "parse_carrinho", "conferencias_com_item_no_carrinho", "candidatas_ao_checkout"}
    for arquivo in ("varredura_busca.py", "busca.py", "varredura_base.py"):
        assert _nomes_usados(PACOTE / arquivo) & proibidos == set(), arquivo


def test_varredura_unica_saiu():
    assert not (PACOTE / "varredura.py").exists()
```

- [ ] **Step 3: Testes cruzados dos dois serviços (falham)**

Crie `tests/coletor_amazon/test_amazon_servicos_separados.py`:

```python
"""Os dois laços sobre o mesmo banco, cada um com o próprio navegador: um não para nem atrasa o outro."""

from datetime import time, timedelta

from fakes import pagina_html
from fakes_varredura import CAPTCHA, MEIO_DIA, confirmado, criar_laco, livre, ofertas, vazia

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, TipoAviso
from tcg_sniper.coletor_amazon.config import aplicar_config
from tcg_sniper.coletor_amazon.parsers import url_ofertas
from tcg_sniper.coletor_amazon.varredura_base import ESPERA_OCIOSA_S
from tcg_sniper.coletor_amazon.varredura_busca import VarreduraBusca
from tcg_sniper.coletor_amazon.varredura_monitor import VarreduraMonitor
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import COLETOR_AMAZON, COLETOR_AMAZON_BUSCA, Coleta, EstadoColetorTipo, StatusColeta, TipoColeta


def dois_lacos(engine, sessoes, config, paginas):
    busca, nav_busca, _, av_busca, relogio = criar_laco(VarreduraBusca, engine, sessoes, config, paginas)
    monitor, nav_monitor, _, av_monitor, _ = criar_laco(
        VarreduraMonitor, engine, sessoes, config, paginas, relogio=relogio
    )
    return busca, nav_busca, av_busca, monitor, nav_monitor, av_monitor, relogio


def estado(sessoes, coletor):
    with sessoes() as s:
        return repo.obter_estado(s, coletor=coletor).estado


def test_busca_roda_com_o_monitor_sempre_atrasado(engine, sessoes, config):
    """O problema de 2026-10-19: com o monitor sempre com anúncio vencido, a busca quase não rodava."""
    asins = ("B0VENC0001", "B0VENC0002", "B0VENC0003")
    for i, asin in enumerate(asins):
        confirmado(sessoes, f"venc{i}", asin)  # nunca lidos: vencidos
    urls = [livre(sessoes, nome) for nome in ("livre1", "livre2")]
    paginas = {url_ofertas(a): ofertas(a, "R$ 990,00") for a in asins} | {u: vazia(u) for u in urls}
    busca, nav_busca, _, monitor, nav_monitor, _, relogio = dois_lacos(engine, sessoes, config, paginas)
    for _ in range(2):
        assert monitor.passo() == 0  # sempre há anúncio vencido
        assert busca.passo() == 0
        relogio.agora += timedelta(minutes=16)  # intervalo de 15 min: tudo vence de novo
    assert sorted(nav_busca.visitadas) == sorted(urls)
    assert len(nav_monitor.visitadas) == 2 and set(nav_monitor.visitadas) <= {url_ofertas(a) for a in asins}


def test_captcha_na_busca_nao_para_o_monitor(engine, sessoes, config):
    confirmado(sessoes, "venc", "B0VENC0001")
    url = livre(sessoes, "livre")
    paginas = {url: pagina_html(CAPTCHA, url=url), url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00")}
    busca, _, av_busca, monitor, nav_monitor, av_monitor, _ = dois_lacos(engine, sessoes, config, paginas)
    assert busca.passo() == ESPERA_OCIOSA_S
    assert estado(sessoes, COLETOR_AMAZON_BUSCA) is EstadoColetorTipo.PAUSADO_DESAFIO
    assert estado(sessoes, COLETOR_AMAZON) is EstadoColetorTipo.ATIVO
    assert monitor.passo() == 0 and nav_monitor.visitadas == [url_ofertas("B0VENC0001")]
    assert av_busca.tipos() == [TipoAviso.AMAZON_BUSCA_CAPTCHA]
    [(_, texto)] = av_busca.mensagens
    assert "porta 6082" in texto
    # a leitura limpa do monitor fecha só o CAPTCHA dele; o da busca continua aberto
    assert (TipoAviso.AMAZON_CAPTCHA, CHAVE_GERAL) in av_monitor.resolvidos
    assert (TipoAviso.AMAZON_BUSCA_CAPTCHA, CHAVE_GERAL) not in av_monitor.resolvidos + av_busca.resolvidos


def test_captcha_no_monitor_nao_para_a_busca(engine, sessoes, config):
    confirmado(sessoes, "venc", "B0VENC0001")
    url = livre(sessoes, "livre")
    oferta = url_ofertas("B0VENC0001")
    paginas = {url: vazia(url), oferta: pagina_html(CAPTCHA, url=oferta)}
    busca, nav_busca, av_busca, monitor, _, av_monitor, _ = dois_lacos(engine, sessoes, config, paginas)
    assert monitor.passo() == ESPERA_OCIOSA_S
    assert estado(sessoes, COLETOR_AMAZON) is EstadoColetorTipo.PAUSADO_DESAFIO
    assert estado(sessoes, COLETOR_AMAZON_BUSCA) is EstadoColetorTipo.ATIVO
    assert busca.passo() == 0 and nav_busca.visitadas == [url]
    assert av_monitor.tipos() == [TipoAviso.AMAZON_CAPTCHA]
    assert (TipoAviso.AMAZON_BUSCA_CAPTCHA, CHAVE_GERAL) in av_busca.resolvidos
    assert (TipoAviso.AMAZON_CAPTCHA, CHAVE_GERAL) not in av_busca.resolvidos


def test_busca_desligada_em_servicos_o_monitor_segue(engine, sessoes, config):
    confirmado(sessoes, "venc", "B0VENC0001")
    url = livre(sessoes, "livre")
    with sessoes() as s, s.begin():
        repo.pausar(s, "pausado no admin", MEIO_DIA, COLETOR_AMAZON_BUSCA)
    paginas = {url: vazia(url), url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00")}
    busca, nav_busca, _, monitor, nav_monitor, _, _ = dois_lacos(engine, sessoes, config, paginas)
    assert busca.passo() == ESPERA_OCIOSA_S and nav_busca.visitadas == []
    assert monitor.passo() == 0 and nav_monitor.visitadas == [url_ofertas("B0VENC0001")]


def test_tetos_independentes(engine, sessoes, config):
    for asin in ("B0VENC0001", "B0VENC0002"):
        confirmado(sessoes, asin, asin)
    urls = [livre(sessoes, nome) for nome in ("livre1", "livre2")]
    with sessoes() as s, s.begin():
        aplicar_config(s, {"max_buscas_hora": 1, "monitor_max_paginas_hora": 1}, MEIO_DIA)
    paginas = {url_ofertas(a): ofertas(a, "R$ 990,00") for a in ("B0VENC0001", "B0VENC0002")} | {
        u: vazia(u) for u in urls
    }
    busca, nav_busca, _, monitor, nav_monitor, _, relogio = dois_lacos(engine, sessoes, config, paginas)
    assert busca.passo() == 0 and monitor.passo() == 0
    assert busca.passo() == ESPERA_OCIOSA_S and monitor.passo() == ESPERA_OCIOSA_S
    assert (len(nav_busca.visitadas), len(nav_monitor.visitadas)) == (1, 1)
    relogio.agora += timedelta(minutes=61)
    assert busca.passo() == 0 and monitor.passo() == 0


def test_janelas_independentes(engine, sessoes, config):
    confirmado(sessoes, "venc", "B0VENC0001")
    url = livre(sessoes, "livre")
    with sessoes() as s, s.begin():
        aplicar_config(s, {"janela_inicio": time(14, 0)}, MEIO_DIA)  # só a busca fechada ao meio-dia
    paginas = {url: vazia(url), url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00")}
    busca, nav_busca, _, monitor, nav_monitor, _, _ = dois_lacos(engine, sessoes, config, paginas)
    assert busca.passo() == ESPERA_OCIOSA_S and nav_busca.visitadas == []
    assert monitor.passo() == 0 and nav_monitor.visitadas == [url_ofertas("B0VENC0001")]


def test_inicializar_do_monitor_nao_fecha_o_ciclo_da_busca(engine, sessoes, config):
    with sessoes() as s, s.begin():
        ciclo_id = repo.iniciar_coleta(s, TipoColeta.AMAZON, MEIO_DIA).id
    monitor, _, _, avisador, _ = criar_laco(VarreduraMonitor, engine, sessoes, config, {})
    monitor.inicializar()
    with sessoes() as s:
        assert s.get(Coleta, ciclo_id).status is StatusColeta.RODANDO
    assert avisador.avisos == []
```

- [ ] **Step 4: Portar os testes do monitor e escrever os novos (falham)**

Em `tests/coletor_amazon/test_varredura_monitor.py`:

1. Troque o import de `tcg_sniper.coletor_amazon.varredura` por:

```python
from tcg_sniper.coletor_amazon.varredura_base import ESPERA_OCIOSA_S
from tcg_sniper.coletor_amazon.varredura_monitor import MOTIVO_EM_ANDAMENTO, RETIRADA_AUTOMATICA_MAX, VarreduraMonitor
```

acrescente `from fakes_varredura import CAPTCHA, MEIO_DIA, SP, Relogio, confirmado, criar_laco, livre, ofertas` e `COLETOR_AMAZON_BUSCA` ao import de `tcg_sniper.db.models`; apague as definições locais de `SP`, `MEIO_DIA`, `CAPTCHA`, `Relogio`, `FabricaFake`, `confirmado`, `livre` e `ofertas`; troque `varredura(...)` por:

```python
def varredura(engine, sessoes, config, paginas, apos_clique=None, relogio=None):
    v, navegador, _, avisador, relogio = criar_laco(
        VarreduraMonitor, engine, sessoes, config, paginas, apos_clique, relogio
    )
    return v, navegador, avisador, relogio
```

2. Substituições mecânicas: `v._teto_monitor` → `v._teto`; `from tcg_sniper.coletor_amazon import varredura as modulo` → `from tcg_sniper.coletor_amazon import varredura_monitor as modulo`.

3. Apague `test_monitor_fora_da_janela_dele_a_descoberta_segue` e `test_descoberta_so_de_nao_casados_e_casados_com_7_dias` (cobertos por `test_janelas_independentes` e pela Task 4).

4. Substitua estes testes pelas versões abaixo:

```python
def test_conferencia_antes_do_monitor_e_nenhuma_busca(engine, sessoes, config):
    url_livre = livre(sessoes, "livre")
    _, candidata = confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    confirmado(sessoes, "venc", "B0VENC0001", "990.00", lido_em=MEIO_DIA - timedelta(minutes=20))
    um_item = carrinho("B0CAND0001", subtotal="R$ 700,00")
    paginas = {
        URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()],
        url_painel_ofertas("B0CAND0001"): painel("B0CAND0001", "R$ 700,00"),
        url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00"),
    }
    v, navegador, avisador, _ = varredura(
        engine, sessoes, config, paginas, [um_item, checkout_resumo("R$ 700,00", "R$ 0,00", None, "R$ 700,00"), carrinho()]
    )
    assert v.passo() == 0  # conferência
    assert v.passo() == 0  # monitor
    assert v.passo() == ESPERA_OCIOSA_S  # o produto livre é da busca, não daqui
    visitadas = navegador.visitadas
    assert visitadas.index(URL_CARRINHO) < visitadas.index(url_ofertas("B0VENC0001"))
    assert url_livre not in visitadas
    [conf] = conferencias(sessoes)
    assert (conf.anuncio_id, conf.situacao, conf.total, conf.item_removido) == (candidata, SituacaoCheckout.OK, Decimal("700.00"), True)
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)).preco_amazon == Decimal("700.00")
    [(_, texto)] = [m for m in avisador.mensagens if m[0] is Destino.OPORTUNIDADES]
    assert "(conferido; frete" in texto


def test_janela_propria_do_monitor(engine, sessoes, config):
    confirmado(sessoes, "venc", "B0VENC0001")  # nunca lido: vencido
    with sessoes() as s, s.begin():
        aplicar_config(s, {"janela_inicio": time(14, 0)}, MEIO_DIA)  # a janela da busca não importa aqui
    v, navegador, _, _ = varredura(engine, sessoes, config, {url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00")})
    assert v.passo() == 0
    assert v.passo() == ESPERA_OCIOSA_S
    assert navegador.visitadas == [url_ofertas("B0VENC0001")]
    with sessoes() as s, s.begin():
        aplicar_config(s, {"janela_inicio": time(8, 0), "monitor_janela_inicio": time(14, 0)}, MEIO_DIA)
    confirmado(sessoes, "outro", "B0OUTR0001")
    v2, navegador2, _, _ = varredura(engine, sessoes, config, {})
    assert v2.passo() == ESPERA_OCIOSA_S and navegador2.visitadas == []


def test_monitor_e_conferencia_somam_no_mesmo_teto(engine, sessoes, config):
    confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    confirmado(sessoes, "venc", "B0VENC0001", "990.00", lido_em=MEIO_DIA - timedelta(minutes=20))
    with sessoes() as s, s.begin():
        aplicar_config(s, {"monitor_max_paginas_hora": 5, "max_buscas_hora": 1}, MEIO_DIA)
    um_item = carrinho("B0CAND0001", subtotal="R$ 700,00")
    paginas = {
        URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()],
        url_painel_ofertas("B0CAND0001"): painel("B0CAND0001", "R$ 700,00"),
        url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00"),
    }
    v, navegador, _, relogio = varredura(
        engine, sessoes, config, paginas, [um_item, checkout_resumo("R$ 700,00", "R$ 0,00", None, "R$ 700,00"), carrinho()]
    )
    v.passo()  # a conferência abre 8 páginas: estoura o teto de 5
    assert v.passo() == ESPERA_OCIOSA_S  # o monitor espera o teto dele
    assert url_ofertas("B0VENC0001") not in navegador.visitadas
    relogio.agora += timedelta(minutes=61)
    v.passo()
    assert navegador.visitadas[-1] == url_ofertas("B0VENC0001")


def test_captcha_no_monitor_pausa_so_o_monitor(engine, sessoes, config):
    confirmado(sessoes, "a", "B0AAAA0001")
    v, _, avisador, _ = varredura(engine, sessoes, config, {url_ofertas("B0AAAA0001"): pagina_html(CAPTCHA, url=url_ofertas("B0AAAA0001"))})
    assert v.passo() == ESPERA_OCIOSA_S
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.PAUSADO_DESAFIO
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON_BUSCA).estado is EstadoColetorTipo.ATIVO
    [dados] = avisador.dados(TipoAviso.AMAZON_CAPTCHA)
    assert dados.linhas[1] == "Monitor e conferência pausados até você retomar; a busca segue"
```

5. Acrescente ao fim do arquivo:

```python
def test_monitor_nunca_busca(engine, sessoes, config):
    livre(sessoes, "livre")
    v, navegador, _, _ = varredura(engine, sessoes, config, {})
    assert v.passo() == ESPERA_OCIOSA_S and navegador.visitadas == []
    with sessoes() as s:
        assert s.scalar(select(FilaAmazon.ultima_busca_em)) is None
        assert s.scalar(select(Coleta)) is None


def test_rodada_avisa_ao_fim_de_cada_volta_mesmo_com_o_monitor_sempre_atrasado(engine, sessoes, config):
    asins = ("B0AAAA0001", "B0BBBB0001", "B0CCCC0001")
    for i, asin in enumerate(asins):
        confirmado(sessoes, f"p{i}", asin)  # nunca lidos
    v, _, avisador, relogio = varredura(engine, sessoes, config, {url_ofertas(a): ofertas(a, "R$ 990,00") for a in asins})
    for _ in range(3):
        assert v.passo() == 0
        relogio.agora += timedelta(minutes=16)  # intervalo de 15 min: o lido já venceu de novo
    assert TipoAviso.AMAZON_MONITOR_CONCLUIDO not in avisador.tipos()
    assert v.passo() == 0  # fecha a volta e já começa a seguinte
    [dados] = avisador.dados(TipoAviso.AMAZON_MONITOR_CONCLUIDO)
    assert dados.linhas[0] == "Anúncios lidos: 3"
    for _ in range(3):
        relogio.agora += timedelta(minutes=16)
        assert v.passo() == 0
    assert [d.linhas[0] for d in avisador.dados(TipoAviso.AMAZON_MONITOR_CONCLUIDO)] == [
        "Anúncios lidos: 3", "Anúncios lidos: 3",
    ]


def test_janela_que_fecha_no_meio_da_volta_nao_avisa_a_rodada(engine, sessoes, config):
    for asin in ("B0AAAA0001", "B0BBBB0001"):
        confirmado(sessoes, asin, asin)
    paginas = {url_ofertas(a): ofertas(a, "R$ 990,00") for a in ("B0AAAA0001", "B0BBBB0001")}
    v, _, avisador, relogio = varredura(engine, sessoes, config, paginas)
    assert v.passo() == 0  # lê um dos dois
    relogio.agora = MEIO_DIA.replace(hour=23)
    assert v.passo() == ESPERA_OCIOSA_S  # janela fechada: a volta incompleta é descartada
    assert TipoAviso.AMAZON_MONITOR_CONCLUIDO not in avisador.tipos()
    relogio.agora = MEIO_DIA + timedelta(days=1)
    assert v.passo() == 0 and v.passo() == 0
    assert v.passo() == ESPERA_OCIOSA_S
    [dados] = avisador.dados(TipoAviso.AMAZON_MONITOR_CONCLUIDO)
    assert dados.linhas[0] == "Anúncios lidos: 2"  # só a volta do dia seguinte


def test_anuncio_que_sai_do_monitor_no_meio_da_volta_nao_prende_a_rodada(engine, sessoes, config):
    confirmado(sessoes, "a", "B0AAAA0001")
    b_id, _ = confirmado(sessoes, "b", "B0BBBB0001")
    paginas = {url_ofertas(a): ofertas(a, "R$ 990,00") for a in ("B0AAAA0001", "B0BBBB0001")}
    v, navegador, avisador, _ = varredura(engine, sessoes, config, paginas)
    assert v.passo() == 0
    assert navegador.visitadas == [url_ofertas("B0AAAA0001")]  # nunca lidos: pela ordem do id
    with sessoes() as s, s.begin():
        s.get(ProdutoLiga, b_id).ativo = False  # o outro sai do monitor sem ser lido
    assert v.passo() == ESPERA_OCIOSA_S
    [dados] = avisador.dados(TipoAviso.AMAZON_MONITOR_CONCLUIDO)
    assert dados.linhas[0] == "Anúncios lidos: 1"


def test_anuncio_que_falha_sai_da_volta(engine, sessoes, config):
    confirmado(sessoes, "a", "B0AAAA0001")
    confirmado(sessoes, "b", "B0BBBB0001")
    paginas = {
        url_ofertas("B0AAAA0001"): pagina_html("<html><body>layout novo</body></html>", url=url_ofertas("B0AAAA0001")),
        url_ofertas("B0BBBB0001"): ofertas("B0BBBB0001", "R$ 990,00"),
    }
    v, _, avisador, _ = varredura(engine, sessoes, config, paginas)
    assert v.passo() == 0 and v.passo() == 0
    assert v.passo() == ESPERA_OCIOSA_S
    [dados] = avisador.dados(TipoAviso.AMAZON_MONITOR_CONCLUIDO)
    assert dados.linhas[0] == "Anúncios lidos: 1"
```

(Acrescente `Coleta`, `FilaAmazon` e `ProdutoLiga` ao import de `tcg_sniper.db.models` se faltarem; `confirmado(sessoes, asin, asin)` usa o ASIN como nome do produto, o que basta.)

Em `tests/test_cli.py`, no `test_coletor_amazon_instala_sigterm_e_usa_o_perfil_da_amazon`, troque `from tcg_sniper.coletor_amazon import varredura` por `from tcg_sniper.coletor_amazon import varredura_monitor` e `monkeypatch.setattr(varredura, "VarreduraAmazon", VarreduraFalsa)` por `monkeypatch.setattr(varredura_monitor, "VarreduraMonitor", VarreduraFalsa)`.

- [ ] **Step 5: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_lacos uv run pytest -q -p no:cacheprovider tests/coletor_amazon tests/db/test_repositorio_monitor.py tests/test_cli.py`
Expected: FAIL (`ModuleNotFoundError: tcg_sniper.coletor_amazon.varredura_monitor`, `AttributeError: ids_vencidos_do_monitor`).

- [ ] **Step 6: Repositório**

Em `src/tcg_sniper/db/repositorio_amazon.py`, logo depois de `proximo_do_monitor`:

```python
def ids_vencidos_do_monitor(s: Session, agora: datetime, intervalo_min: int) -> set[int]:
    """Os anúncios confirmados (de produto ativo) nunca lidos ou com a leitura de ofertas vencida: a volta
    do monitor que começa agora (ver `varredura_monitor._Rodada`)."""
    leitura = _leitura_do_monitor()
    consulta = _confirmados_ativos(select(AnuncioAmazon.id)).where(
        or_(leitura.is_(None), leitura <= agora - timedelta(minutes=intervalo_min))
    )
    return set(s.scalars(consulta))
```

- [ ] **Step 7: Implementar o laço do monitor**

Crie `src/tcg_sniper/coletor_amazon/varredura_monitor.py`:

```python
"""Serviço `coletor-amazon`: retirada do carrinho, conferência de checkout e monitor de preço, no navegador
logado. Por passo, no máximo um trabalho, por prioridade: tirar do carrinho um item que ficou de uma
conferência, conferir no checkout uma candidata, ler as ofertas do anúncio confirmado mais atrasado. A
conferência e o monitor só dentro da janela do monitor e com o teto `monitor_max_paginas_hora` (somado, com
as páginas da retirada). A busca de anúncios novos é do serviço `coletor-amazon-busca` (este laço não a
importa nem a chama).

A retirada não espera janela nem teto (só o intervalo `ESPERA_RETIRADA` entre tentativas de cada
conferência, em rodízio): um item nosso no carrinho do usuário não pode ficar lá. Antes do clique em
adicionar, a conferência grava uma marca "em andamento" com `item_removido` False; se o processo morre no
meio, a primeira volta depois do reinício acha a marca; senão o resultado é gravado nessa linha.

A retirada automática só clica em Excluir com o carrinho exatamente como a conferência o deixou: só o ASIN
no carrinho ativo, contador 1, subtotal igual ao preço anunciado e marca de até `RETIRADA_AUTOMATICA_MAX`.
Em qualquer outro caso (ou depois de `MAX_TENTATIVAS_RETIRADA` falhas) não clica: a conferência fica
"conferir à mão", o grupo admin recebe um aviso (`AMAZON_CARRINHO`, um por ASIN) e o admin mostra o alerta
com "Já conferi". Com o monitor pausado, a retirada também para.

Rodada do monitor (`AMAZON_MONITOR_CONCLUIDO`) = uma volta: começa no primeiro trabalho com os anúncios
vencidos naquele momento e termina quando todos eles foram lidos (ou postos de lado por falha, ou saíram do
monitor), mesmo que outros já tenham vencido de novo; a volta seguinte começa em seguida. A janela que fecha
no meio descarta a volta sem aviso."""

import dataclasses
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, Dados, TipoAviso
from tcg_sniper.avisos.formato import formatar_duracao
from tcg_sniper.coletor_amazon import checkout, monitor
from tcg_sniper.coletor_amazon.busca import CotaHtmlFalha, DesafioAmazon, abrir_pagina
from tcg_sniper.coletor_amazon.cliques import CliqueProibido, SeletorAusente, conta_logada, remover_do_carrinho
from tcg_sniper.coletor_amazon.config import aplicar_config
from tcg_sniper.coletor_amazon.parsers import URL_CARRINHO
from tcg_sniper.coletor_amazon.parsers_checkout import Carrinho, parse_carrinho
from tcg_sniper.coletor_amazon.varredura_base import (
    ESPERA_OCIOSA_S,
    MAX_FALHAS_SEGUIDAS,
    ORIGEM_MONITOR,
    VarreduraBase,
)
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import ConfigAmazon, EstadoColetorTipo, SituacaoCheckout
from tcg_sniper.navegador.base import NavegadorInterativo
from tcg_sniper.navegador.modelos import ErroRede
from tcg_sniper.parsing import ErroParser

log = logging.getLogger(__name__)

ESPERA_RETIRADA = timedelta(minutes=15)  # item nosso que não saiu do carrinho: nova tentativa
RETIRADA_AUTOMATICA_MAX = timedelta(minutes=30)  # marca mais velha que isso: só à mão (o carrinho pode ter mudado)
MAX_TENTATIVAS_RETIRADA = 3  # falhas da retirada automática antes de passar para "conferir à mão"
ERROS_DE_PAGINA = (ErroParser, ErroRede, CliqueProibido, SeletorAusente)
MOTIVO_EM_ANDAMENTO = "conferência em andamento (interrompida?): o item pode ter ficado no carrinho"


def linha_do_carrinho(asin: str) -> str:
    """Linha extra do aviso de CAPTCHA quando uma conferência pode ter deixado o item no carrinho."""
    minutos = int(RETIRADA_AUTOMATICA_MAX.total_seconds() // 60)
    return (
        f"Uma conferência deixou 1× {asin} no carrinho: sai sozinho se você retomar em até {minutos} min; "
        "senão confira à mão"
    )


def dados_conferir_a_mao(asin: str, razao: str) -> Dados:
    return Dados(
        titulo_extra=asin,
        linhas=(f"Pode haver 1× {asin} de uma conferência automática no carrinho", f"Motivo: {razao}"),
    )


DADOS_SEM_LOGIN = Dados(linhas=("A conferência de checkout parou; o monitor de preço continua",))


@dataclass
class _Rodada:
    """Uma volta do monitor: os anúncios vencidos quando ela começou (`faltam`) até todos saírem."""

    inicio: datetime
    faltam: set[int] = field(default_factory=set)
    lidos: int = 0
    quedas: int = 0
    conferencias: int = 0


class _NavegadorContado:
    """Conta as páginas que o monitor abre (também as de uma leitura que falha no meio: o teto cobra
    todas). Só navega; o resto (inclusive o clique, que só `cliques.py` usa) vai direto ao navegador."""

    def __init__(self, navegador: NavegadorInterativo):
        self._navegador = navegador
        self.abertas = 0

    def abrir(self, url: str):
        self.abertas += 1
        return self._navegador.abrir(url)

    def abrir_e_esperar(self, url: str, seletor: str, timeout_ms: int = 15_000):
        self.abertas += 1
        return self._navegador.abrir_e_esperar(url, seletor, timeout_ms)

    def __getattr__(self, nome: str):
        return getattr(self._navegador, nome)


class VarreduraMonitor(VarreduraBase):
    origem = ORIGEM_MONITOR

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cota_falhas = CotaHtmlFalha()  # renovada uma vez por dia
        self._espera: dict[int, datetime] = {}  # anúncio que falhou -> não reler antes de
        self._limpeza_em: date | None = None
        self._rodada: _Rodada | None = None

    def inicializar(self) -> None:
        super().inicializar()
        with self._sessoes() as s, s.begin():
            presos = repo_amz.conferencias_com_item_no_carrinho(s)
        if presos:  # item que ficou de antes do reinício: a retirada roda já no primeiro passo
            log.warning("%d conferência(s) com item possivelmente no carrinho; tirando no primeiro passo", len(presos))

    def passo(self) -> float:
        """Faz no máximo um trabalho. Devolve quantos segundos dormir antes do próximo passo."""
        agora = self._relogio()
        cfg, estado = self._inicio_do_passo(agora)
        if estado is EstadoColetorTipo.ATIVO:
            try:
                espera = self._talvez_retirar(cfg)
            except DesafioAmazon as desafio:
                self._desafio(desafio.url)
                return ESPERA_OCIOSA_S
            if espera is not None:
                return espera
        if not self._janela(agora, "monitor", cfg.monitor_janela_inicio, cfg.monitor_janela_fim).contem(agora):
            self._rodada = None  # volta incompleta: sem aviso
            self.fechar_navegador()
            return ESPERA_OCIOSA_S
        if estado is not EstadoColetorTipo.ATIVO:
            return ESPERA_OCIOSA_S
        self._limpar_uma_vez_por_dia(agora)
        if self._teto.liberado_em(agora, cfg.monitor_max_paginas_hora) is not None:
            return ESPERA_OCIOSA_S
        try:
            espera = self._passo_monitor(agora, cfg)
        except DesafioAmazon as desafio:
            self._desafio(desafio.url)
            return ESPERA_OCIOSA_S
        return ESPERA_OCIOSA_S if espera is None else espera

    def _desafio(self, url: str, asin_no_carrinho: str | None = None) -> None:
        self._registrar_desafio(url, (linha_do_carrinho(asin_no_carrinho),) if asin_no_carrinho else ())

    def _limpar_uma_vez_por_dia(self, agora: datetime) -> None:
        dia = agora.astimezone(self._config.zona).date()
        if self._limpeza_em == dia:
            return
        with self._sessoes() as s, s.begin():
            apagadas = repo_amz.limpar_ofertas_antigas(s, agora)
        if apagadas:
            log.info("%d ofertas lidas há mais de 30 dias apagadas", apagadas)
        self._limpeza_em = dia
        self._cota_falhas = CotaHtmlFalha()

    def _registrar_paginas(self, quantidade: int) -> None:
        agora = self._relogio()
        for _ in range(quantidade):
            self._teto.registrar(agora)

    # --- rodada ----------------------------------------------------------------------------------

    def _rodada_atual(self) -> _Rodada:
        if self._rodada is None:
            self._rodada = _Rodada(self._relogio())
        return self._rodada

    def _talvez_fechar_rodada(self, vencidos: set[int]) -> None:
        """Tira da volta o que saiu do monitor sem ser lido; com a volta vazia, fecha (e avisa)."""
        if self._rodada is None:
            return
        self._rodada.faltam &= vencidos
        if not self._rodada.faltam:
            self._fechar_rodada()

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

    def _por_de_lado(self, anuncio_id: int, cfg: ConfigAmazon) -> None:
        """Um anúncio que falha não prende o monitor: espera um intervalo e sai da volta atual."""
        self._espera[anuncio_id] = self._relogio() + timedelta(minutes=cfg.monitor_intervalo_min)
        if self._rodada is not None:
            self._rodada.faltam.discard(anuncio_id)

    # --- monitor, conferência e retirada ---------------------------------------------------------

    def _passo_monitor(self, agora: datetime, cfg: ConfigAmazon) -> float | None:
        """Um trabalho do monitor, por prioridade. None: nada a fazer agora."""
        self._espera = {k: v for k, v in self._espera.items() if v > agora}
        de_lado = set(self._espera)
        with self._sessoes() as s, s.begin():
            candidatas = []
            if cfg.checkout_ligado and cfg.checkout_sem_login_em is None and not repo_amz.carrinho_ocupado_ha_pouco(s, agora):
                candidatas = repo_amz.candidatas_ao_checkout(s, agora, cfg)
            proximo = None
            vencidos: set[int] = set()
            if cfg.monitor_ligado:
                vencidos = repo_amz.ids_vencidos_do_monitor(s, agora, cfg.monitor_intervalo_min) - de_lado
                proximo = repo_amz.proximo_do_monitor(s, agora, cfg.monitor_intervalo_min, de_lado)
        self._talvez_fechar_rodada(vencidos)
        if not candidatas and proximo is None:
            return None
        if self._rodada is None:
            self._rodada = _Rodada(self._relogio(), faltam=set(vencidos))
        if candidatas:
            return self._conferir(candidatas[0], cfg)
        return self._monitorar(*proximo, cfg)

    def _talvez_retirar(self, cfg: ConfigAmazon) -> float | None:
        """Tenta tirar do carrinho o item de uma conferência que pode ter ficado lá (marca "em andamento" de
        um processo que morreu, ou retirada que falhou), uma conferência por passo, em rodízio e com
        `ESPERA_RETIRADA` entre tentativas da mesma. None: nada a tirar agora."""
        with self._sessoes() as s, s.begin():
            pendentes = repo_amz.conferencias_com_item_no_carrinho(s, self._relogio(), ESPERA_RETIRADA)
        if not pendentes:
            return None
        return self._retirar(pendentes[0], cfg)
```

Em seguida, ainda na classe, copie **sem mudar a lógica** os métodos `_sem_clique`, `_conferir_a_mao`, `_falha_na_retirada`, `_retirar`, `_conferir` e `_monitorar` de `src/tcg_sniper/coletor_amazon/varredura.py` (linhas ~418-589), com estas trocas exatas:

- em `_retirar`, `_conferir` e `_monitorar`: `self._cota_falhas_monitor` → `self._cota_falhas`; `self._pausar(cfg)` → `self._pausa_humana(cfg)`;
- em `_retirar`, no `except DesafioAmazon`: `self._registrar_desafio(desafio.url, item.asin)` → `self._desafio(desafio.url, item.asin)`;
- em `_conferir`, no fim: `self._registrar_desafio(resultado.desafio_url, None if resultado.item_removido else candidata.asin)` → `self._desafio(resultado.desafio_url, None if resultado.item_removido else candidata.asin)`;
- `_monitorar` inteiro fica assim:

```python
    def _monitorar(self, anuncio_id: int, asin: str, cfg: ConfigAmazon) -> float:
        rodada = self._rodada_atual()
        ctx = self._contexto(cfg, f"amazon-monitor-{asin}", self._cota_falhas)
        contado = _NavegadorContado(ctx.navegador)
        ctx = dataclasses.replace(ctx, navegador=contado)
        try:
            resultado = monitor.ler_anuncio(ctx, anuncio_id, asin)
        except ERROS_DE_PAGINA as erro:
            self._registrar_paginas(max(contado.abertas, 1))  # ofertas, perfis de vendedor e novas tentativas
            self._por_de_lado(anuncio_id, cfg)
            self._falhas_seguidas += 1
            log.warning("leitura das ofertas de %s falhou: %s", asin, erro)
            if self._falhas_seguidas >= MAX_FALHAS_SEGUIDAS:
                return self._pausar_por_falhas()
            return 0
        except DesafioAmazon:
            raise  # o anúncio continua na volta: é lido depois de retomar
        except Exception:
            # Um anúncio que quebra não pode prender o monitor nele: espera um intervalo e o erro sobe.
            self._por_de_lado(anuncio_id, cfg)
            raise
        self._registrar_paginas(resultado.paginas)
        self._falhas_seguidas = 0
        self._erros_seguidos = 0
        rodada.faltam.discard(anuncio_id)
        rodada.lidos += 1
        rodada.quedas += resultado.caiu
        self._pagina_ok()
        return 0
```

Depois apague o arquivo antigo:

Run: `git rm src/tcg_sniper/coletor_amazon/varredura.py`

- [ ] **Step 8: CLI aponta para o monitor**

Em `src/tcg_sniper/cli.py`, no ramo `elif args.comando == "coletor-amazon":`, troque `from tcg_sniper.coletor_amazon.varredura import VarreduraAmazon` por `from tcg_sniper.coletor_amazon.varredura_monitor import VarreduraMonitor` e `VarreduraAmazon(` por `VarreduraMonitor(`; troque o help do subcomando para `"inicia o monitor de preço, a conferência de checkout e a retirada do carrinho da Amazon (navegador logado)"`. No ramo `amazon`, troque `from tcg_sniper.coletor_amazon.varredura import ID_LOCK_AMAZON` por `from tcg_sniper.coletor_amazon.varredura_base import ID_LOCK_AMAZON`.

- [ ] **Step 9: Rodar os testes da tarefa**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_lacos uv run pytest -q -p no:cacheprovider tests/coletor_amazon tests/db/test_repositorio_monitor.py tests/test_cli.py`
Expected: PASS. Se um teste portado conferir a linha 2 do aviso de pausa do monitor, o texto é "Com o monitor pausado, a retirada automática de item do carrinho também para".

- [ ] **Step 10: Suíte inteira, ruff e commit**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_lacos uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde. `grep -rn "coletor_amazon.varredura import\|coletor_amazon import varredura\b" src tests` não acha nada.

```bash
git add -A src/tcg_sniper/coletor_amazon src/tcg_sniper/db/repositorio_amazon.py src/tcg_sniper/cli.py tests/coletor_amazon tests/db/test_repositorio_monitor.py tests/test_cli.py
git commit -m "feat: split Amazon collector into search and monitor loops"
```

---

### Task 6: Comando e serviço `coletor-amazon-busca` (lane `servico`)

**Files:**
- Modify: `src/tcg_sniper/cli.py` (subcomando novo ~63 e ramo novo depois de `coletor-amazon` ~144)
- Modify: `docker-compose.yml` (serviço novo depois de `coletor-amazon`, ~118)
- Modify: `docker/coletor-entrypoint.sh:21-23` (comentário dos perfis)
- Test: `tests/test_cli.py` (acrescentar), `tests/test_compose.py` (novo)

**Interfaces:**
- Consumes: `varredura_busca.VarreduraBusca` (Task 4), `models.COLETOR_AMAZON_BUSCA` (Task 1), `vigia.Batimento`, `NavegadorChromium(dir_perfil, eh_desafio)`, `criar_avisador`.
- Produces: `tcg-sniper coletor-amazon-busca` (perfil `<DIR_DADOS>/perfil-amazon-busca`, batida `amazon_busca`, SIGTERM instalado); serviço compose `coletor-amazon-busca` (noVNC `6082:6080`, `DIR_PERFIL=/data/perfil-amazon-busca`, `init: true`, `hostname: coletor-amazon-busca`, `shm_size: 1gb`).

- [ ] **Step 1: Banco da lane**

Run: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_servico`

- [ ] **Step 2: Escrever os testes (falham)**

Acrescente a `tests/test_cli.py`, depois de `test_coletor_amazon_instala_sigterm_e_usa_o_perfil_da_amazon`:

```python
def test_coletor_amazon_busca_usa_perfil_proprio_e_bate_como_amazon_busca(monkeypatch, tmp_path, batidas):
    from tcg_sniper.coletor_amazon import varredura_busca

    anterior = signal.getsignal(signal.SIGTERM)
    vistos = []

    class VarreduraFalsa:
        def __init__(self, engine, sessoes, fabrica, avisador, config):
            vistos.append(fabrica()._dir_perfil)

        def rodar(self):
            vistos.append(signal.getsignal(signal.SIGTERM))

    monkeypatch.setattr(varredura_busca, "VarreduraBusca", VarreduraFalsa)
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    monkeypatch.setenv("DIR_DADOS", str(tmp_path))
    try:
        cli.main(["coletor-amazon-busca"])
        assert vistos[0] == tmp_path / "perfil-amazon-busca"
        assert vistos[1] not in (anterior, signal.SIG_DFL, signal.SIG_IGN)
        assert batidas == ["amazon_busca"]
    finally:
        signal.signal(signal.SIGTERM, anterior)
```

Crie `tests/test_compose.py`:

```python
"""O docker-compose.yml lido como texto (sem dependência de YAML): o serviço da busca da Amazon tem
perfil, noVNC e arranjo próprios; o monitor continua no perfil logado."""

import re
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def bloco(servico: str) -> str:
    texto = COMPOSE.read_text(encoding="utf-8")
    inicio = texto.index(f"\n  {servico}:\n") + 1
    resto = texto[inicio + 1 :]
    fim = re.search(r"\n(?=  [a-z][a-z0-9-]*:\n|\S)", resto)
    return texto[inicio : inicio + 1 + fim.start()] if fim else texto[inicio:]


def test_servico_da_busca_com_perfil_novnc_e_arranjo_proprios():
    b = bloco("coletor-amazon-busca")
    for trecho in (
        'entrypoint: ["/app/docker/coletor-entrypoint.sh"]',
        'command: ["tcg-sniper", "coletor-amazon-busca"]',
        "DIR_PERFIL: /data/perfil-amazon-busca",
        "init: true",
        "hostname: coletor-amazon-busca",
        "stop_grace_period: 30s",
        "shm_size: 1gb",
        '- "6082:6080"',
        "condition: service_completed_successfully",
    ):
        assert trecho in b, trecho


def test_monitor_continua_no_perfil_logado_e_na_6081():
    b = bloco("coletor-amazon")
    assert "DIR_PERFIL: /data/perfil-amazon\n" in b
    assert '- "6081:6080"' in b and 'command: ["tcg-sniper", "coletor-amazon"]' in b


def test_portas_do_novnc_nao_se_repetem():
    assert sorted(re.findall(r'- "(\d+):6080"', COMPOSE.read_text(encoding="utf-8"))) == ["6080", "6081", "6082"]
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_servico uv run pytest -q -p no:cacheprovider tests/test_cli.py tests/test_compose.py`
Expected: FAIL (`invalid choice: 'coletor-amazon-busca'`; `ValueError: substring not found`).

- [ ] **Step 4: CLI**

Em `src/tcg_sniper/cli.py`, depois de `sub.add_parser("coletor-amazon", ...)`:

```python
    sub.add_parser(
        "coletor-amazon-busca", help="inicia a fila de buscas de anúncios novos na Amazon (navegador próprio, sem login)"
    )
```

e, logo depois do ramo `elif args.comando == "coletor-amazon":`:

```python
    elif args.comando == "coletor-amazon-busca":
        from tcg_sniper.avisos.servico import criar_avisador
        from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon
        from tcg_sniper.coletor_amazon.varredura_busca import VarreduraBusca
        from tcg_sniper.db.models import COLETOR_AMAZON_BUSCA
        from tcg_sniper.navegador.chromium import NavegadorChromium

        Batimento(sessoes, COLETOR_AMAZON_BUSCA).iniciar()
        instalar_sigterm()
        VarreduraBusca(
            engine,
            sessoes,
            lambda: NavegadorChromium(config.dir_dados / "perfil-amazon-busca", eh_desafio_amazon),
            criar_avisador(sessoes),
            config,
        ).rodar()
```

- [ ] **Step 5: Compose e entrypoint**

Em `docker-compose.yml`, logo depois do bloco `coletor-amazon` (antes de `notificador:`):

```yaml
  coletor-amazon-busca:
    <<: *app
    entrypoint: ["/app/docker/coletor-entrypoint.sh"]
    command: ["tcg-sniper", "coletor-amazon-busca"]
    environment:
      DATABASE_URL: postgresql+psycopg://tcg:tcg@postgres:5432/tcg
      DIR_DADOS: /data
      EVOLUTION_URL: http://evolution:8080
      TZ: America/Sao_Paulo
      DIR_PERFIL: /data/perfil-amazon-busca
    # Busca de anúncios novos num navegador próprio, sem login (perfil separado do monitor, que fica
    # logado). Mesmo arranjo dos outros coletores: tini, hostname fixo para o SingletonLock do perfil e o
    # noVNC na porta 6082 do host (6080 é da Liga, 6081 do monitor da Amazon).
    init: true
    hostname: coletor-amazon-busca
    stop_grace_period: 30s
    shm_size: 1gb
    ports:
      - "6082:6080"
    depends_on:
      migrate:
        condition: service_completed_successfully
```

No comentário do `coletor-amazon`, troque "e o noVNC da Amazon na porta 6081 do host (a 6080 é da Liga)." por "e o noVNC do monitor da Amazon (navegador logado) na porta 6081 do host (a 6080 é da Liga, a 6082 da busca)."

Em `docker/coletor-entrypoint.sh`, troque as duas linhas de comentário dos perfis por:

```sh
# Cada coletor tem o próprio perfil do Chromium (DIR_PERFIL), então os locks deste perfil são sempre
# obsoletos aqui. Liga: <DIR_DADOS>/perfil; Amazon (monitor): perfil-amazon; Amazon (busca): perfil-amazon-busca.
```

- [ ] **Step 6: Rodar os testes, suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_servico uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde. (Não rode `docker compose` nesta lane: a conferência do compose é o `tests/test_compose.py`; o `up` é da implantação.)

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/cli.py docker-compose.yml docker/coletor-entrypoint.sh tests/test_cli.py tests/test_compose.py
git commit -m "feat: coletor-amazon-busca command and compose service (noVNC 6082)"
```

---

### Task 7: Admin — Serviços (lane `admin`)

**Files:**
- Modify: `src/tcg_sniper/admin/app.py:45-50` (import), `:65-71` (`NOMES_SERVICOS`), `:83-105` (`MENSAGENS_SERVICOS`), `:369-397` (contexto de `/servicos`), `:471-485` (rotas da Amazon)
- Modify: `src/tcg_sniper/admin/templates/servicos.html:63-98` (cards da Amazon)
- Modify: `src/tcg_sniper/admin/static/admin.css` (regenerado)
- Test: `tests/admin/test_admin_servicos.py`

**Interfaces:**
- Consumes: `COLETOR_AMAZON_BUSCA` (Task 1), `repo.obter_estado/pausar/retomar`, `_desligar`, `_avisar_mudanca`, macros `chave`, `selo`, `selo_ligado` do template.
- Produces: rotas `POST /amazon/busca/pausar` → `303 /servicos?msg=amazon_busca_pausar` (ou `desafio_pendente`), `POST /amazon/busca/retomar` → `303 /servicos?msg=amazon_busca_retomar`; card `data-servico="amazon_busca"` ("Amazon (busca)"); card `data-servico="amazon"` vira "Amazon (monitor e checkout)" com histórico `/logs?aba=monitor`; `NOMES_SERVICOS[COLETOR_AMAZON_BUSCA] == "Amazon (busca)"`, `NOMES_SERVICOS[COLETOR_AMAZON] == "Amazon (monitor e checkout)"`.

- [ ] **Step 1: Banco da lane**

Run: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_admin`

- [ ] **Step 2: Escrever os testes (falham)**

Em `tests/admin/test_admin_servicos.py`: acrescente `COLETOR_AMAZON_BUSCA` ao import de `tcg_sniper.db.models`; em `test_quatro_cards_ligados_com_chave_e_historico`, troque a linha `("amazon", "/amazon/pausar", "/logs?aba=amazon"),` por:

```python
        ("amazon_busca", "/amazon/busca/pausar", "/logs?aba=amazon"),
        ("amazon", "/amazon/pausar", "/logs?aba=monitor"),
```

e acrescente ao fim do arquivo:

```python
def test_card_da_busca_e_o_do_monitor(cliente, sessoes):
    with sessoes() as s, s.begin():
        from tcg_sniper.coletor_amazon.config import aplicar_config

        aplicar_config(s, {"max_buscas_hora": 90, "monitor_max_paginas_hora": 180}, T0)
    texto = cliente.get("/servicos").text
    busca, monitor = card(texto, "amazon_busca"), card(texto, "amazon")
    assert "Amazon (busca)" in busca and "Fila contínua de buscas" in busca and "até 90 por hora" in busca
    assert "host.test:6082/vnc.html" in busca and "6081" not in busca
    assert "Amazon (monitor e checkout)" in monitor and "Fila contínua de buscas" not in monitor
    assert "até 180 páginas por hora" in monitor and "host.test:6081/vnc.html" in monitor


def test_pausar_e_retomar_a_busca_nao_mexe_no_monitor(cliente, sessoes):
    r = cliente.post("/amazon/busca/pausar", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/servicos?msg=amazon_busca_pausar")
    with sessoes() as s:
        busca = repo.obter_estado(s, coletor=COLETOR_AMAZON_BUSCA)
        assert (busca.estado, busca.motivo) == (EstadoColetorTipo.PAUSADO, "pausado no admin")
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.ATIVO
    assert "Busca na Amazon pausada" in cliente.get(r.headers["location"]).text
    r = cliente.post("/amazon/busca/retomar", follow_redirects=False)
    assert r.headers["location"] == "/servicos?msg=amazon_busca_retomar"
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON_BUSCA).estado is EstadoColetorTipo.ATIVO
    assert "Busca na Amazon retomada" in cliente.get(r.headers["location"]).text


def test_pausar_o_monitor_nao_mexe_na_busca(cliente, sessoes):
    r = cliente.post("/amazon/pausar", follow_redirects=False)
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.PAUSADO
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON_BUSCA).estado is EstadoColetorTipo.ATIVO
    assert "Monitor e checkout da Amazon pausados" in cliente.get(r.headers["location"]).text


def test_desafio_da_busca_card_vermelho_com_novnc_6082_e_monitor_normal(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em /s?k=x", T0, COLETOR_AMAZON_BUSCA)
    texto = cliente.get("/servicos").text
    busca = card(texto, "amazon_busca")
    assert "border-error" in busca and "host.test:6082/vnc.html" in busca
    assert 'action="/amazon/busca/retomar"' in busca and "desafio pendente" in busca and "toggle" not in busca
    assert "border-error" not in card(texto, "amazon")


def test_desligar_a_busca_nao_apaga_um_desafio_pendente(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em /x", T0, COLETOR_AMAZON_BUSCA)
    r = cliente.post("/amazon/busca/pausar", follow_redirects=False)
    assert r.headers["location"] == "/servicos?msg=desafio_pendente"
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON_BUSCA).estado is EstadoColetorTipo.PAUSADO_DESAFIO


def test_pausar_a_busca_avisa_com_o_nome_do_servico(cliente, sessoes):
    from sqlalchemy import select

    from tcg_sniper.db.models import MensagemSaida

    cliente.post("/amazon/busca/pausar")
    with sessoes() as s:
        textos = [m.texto for m in s.scalars(select(MensagemSaida))]
    assert any("Amazon (busca)" in t and "pausado" in t for t in textos)
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_admin uv run pytest -q -p no:cacheprovider tests/admin/test_admin_servicos.py`
Expected: FAIL (`data-servico="amazon_busca"` ausente, 404/405 nas rotas novas).

- [ ] **Step 4: Rotas, nomes e mensagens**

Em `src/tcg_sniper/admin/app.py`: acrescente `COLETOR_AMAZON_BUSCA` ao import de `tcg_sniper.db.models`. `NOMES_SERVICOS`:

```python
NOMES_SERVICOS = {
    COLETOR_LIGA: "LigaMagic",
    COLETOR_AMAZON_BUSCA: "Amazon (busca)",
    COLETOR_AMAZON: "Amazon (monitor e checkout)",
    COLETOR_CASADOR: "Casador (IA)",
    COLETOR_NOTIFICADOR: "WhatsApp (notificador)",
    COLETOR_MANUTENCAO: "Backup (manutenção)",
}
```

Em `MENSAGENS_SERVICOS`, troque `"amazon_pausar"` e `"amazon_retomar"` e acrescente as da busca:

```python
    "amazon_pausar": "Monitor e checkout da Amazon pausados. A busca segue.",
    "amazon_retomar": "Monitor e checkout da Amazon retomados.",
    "amazon_busca_pausar": "Busca na Amazon pausada. O monitor e o checkout seguem.",
    "amazon_busca_retomar": "Busca na Amazon retomada.",
```

No contexto de `/servicos`, acrescente `"estado_amazon_busca": repo.obter_estado(s, coletor=COLETOR_AMAZON_BUSCA),` (ao lado de `"estado_amazon"`).

Depois de `retomar_amazon`, acrescente:

```python
    @app.post("/amazon/busca/pausar")
    def pausar_busca_amazon():
        return _desligar(COLETOR_AMAZON_BUSCA, "amazon_busca_pausar")

    @app.post("/amazon/busca/retomar")
    def retomar_busca_amazon():
        agora = repo.agora_utc()
        with sessoes() as s, s.begin():
            repo.retomar(s, agora, COLETOR_AMAZON_BUSCA)
            _avisar_mudanca(s, COLETOR_AMAZON_BUSCA, "ativo", agora)
        return RedirectResponse("/servicos?msg=amazon_busca_retomar", status_code=status.HTTP_303_SEE_OTHER)
```

(Se o projeto exigir permissão declarada nas rotas do admin antigo, siga o mesmo padrão das rotas `/amazon/pausar` vizinhas; hoje elas não declaram.)

- [ ] **Step 5: Template**

Em `src/tcg_sniper/admin/templates/servicos.html`, troque o bloco `{# Amazon #}` inteiro (do `{# Amazon #}` até o `{% endif %}` que fecha o card da Amazon, antes do card do casador) por:

```html
  {# Amazon (busca): navegador próprio, sem login #}
  {% set busca = estado_amazon_busca.estado.value %}
  {% if busca == "pausado_desafio" %}
  <div data-servico="amazon_busca" class="card border border-error bg-base-100 shadow-sm"><div class="card-body gap-3 p-4">
    <h2 class="card-title text-base">Amazon (busca) {{ selo("pausado_desafio", "desafio pendente") }}</h2>
    <p class="text-sm">Pausada: CAPTCHA pendente. {{ estado_amazon_busca.motivo or "" }}</p>
    <p class="text-sm">Resolva em <a class="link" href="http://{{ host }}:6082/vnc.html">http://{{ host }}:6082/vnc.html</a> e clique em Retomar. O monitor e o checkout seguem.</p>
    <div class="card-actions"><form method="post" action="/amazon/busca/retomar"><button class="btn btn-sm btn-primary">Retomar</button></form><a class="btn btn-sm btn-ghost" href="/logs?aba=amazon">Ver histórico</a></div>
  </div></div>
  {% else %}
  <div data-servico="amazon_busca" class="card bg-base-100 shadow-sm"><div class="card-body gap-3 p-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h2 class="card-title text-base">Amazon (busca) {{ selo_ligado(busca == "ativo") }}{% if ciclo_amazon %} {{ selo("rodando", "ciclo em andamento") }}{% endif %}</h2>
      {{ chave("/amazon/busca/pausar" if busca == "ativo" else "/amazon/busca/retomar", busca == "ativo", "busca na Amazon") }}
    </div>
    {% if busca == "ativo" %}
    <p class="text-sm">Fila contínua de buscas, das {{ janela[0] }} às {{ janela[1] }}, até {{ cfg_amazon.max_buscas_hora }} por hora.{% if ciclo_amazon %} Ciclo em andamento desde {{ ciclo_amazon.iniciada_em|data }}.{% endif %}</p>
    {% else %}
    <p class="text-sm">Desligada: {{ estado_amazon_busca.motivo or "sem motivo" }}. Volta quando você ligar de novo; o monitor e o checkout seguem.</p>
    {% endif %}
    <p class="text-sm text-base-content/70">Navegador próprio, sem login: <a class="link" href="http://{{ host }}:6082/vnc.html">http://{{ host }}:6082/vnc.html</a>.</p>
    <div class="card-actions"><a class="btn btn-sm btn-ghost" href="/logs?aba=amazon">Ver histórico</a></div>
  </div></div>
  {% endif %}

  {# Amazon (monitor e checkout): navegador logado #}
  {% set amazon = estado_amazon.estado.value %}
  {% if amazon == "pausado_desafio" %}
  <div data-servico="amazon" class="card border border-error bg-base-100 shadow-sm"><div class="card-body gap-3 p-4">
    <h2 class="card-title text-base">Amazon (monitor e checkout) {{ selo("pausado_desafio", "desafio pendente") }}</h2>
    <p class="text-sm">Pausado: CAPTCHA pendente. {{ estado_amazon.motivo or "" }}</p>
    <p class="text-sm">Resolva em <a class="link" href="http://{{ host }}:6081/vnc.html">http://{{ host }}:6081/vnc.html</a> e clique em Retomar. A busca segue.</p>
    {{ alerta_sem_login() }}
    {{ alerta_carrinho() }}
    <div class="card-actions"><form method="post" action="/amazon/retomar"><button class="btn btn-sm btn-primary">Retomar</button></form><a class="btn btn-sm btn-ghost" href="/logs?aba=monitor">Ver histórico</a></div>
  </div></div>
  {% else %}
  <div data-servico="amazon" class="card bg-base-100 shadow-sm"><div class="card-body gap-3 p-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h2 class="card-title text-base">Amazon (monitor e checkout) {{ selo_ligado(amazon == "ativo") }}</h2>
      {{ chave("/amazon/pausar" if amazon == "ativo" else "/amazon/retomar", amazon == "ativo", "monitor e checkout da Amazon") }}
    </div>
    {% if amazon == "ativo" %}
    <p class="text-sm">Retirada do carrinho, conferência de checkout e monitor de preço no navegador logado (<a class="link" href="http://{{ host }}:6081/vnc.html">http://{{ host }}:6081/vnc.html</a>), até {{ cfg_amazon.monitor_max_paginas_hora }} páginas por hora.</p>
    {% else %}
    <p class="text-sm">Desligado: {{ estado_amazon.motivo or "sem motivo" }}. Volta quando você ligar de novo; a busca segue.</p>
    {% endif %}
    <div class="divider my-0"></div>
    <div class="flex flex-wrap items-center justify-between gap-3">
      <span class="text-sm font-medium">Monitor de preço</span>
      {{ chave("/amazon/monitor/desligar" if cfg_amazon.monitor_ligado else "/amazon/monitor/ligar", cfg_amazon.monitor_ligado, "monitor de preço") }}
    </div>
    <p class="text-sm">A cada {{ cfg_amazon.monitor_intervalo_min }} min, das {{ janela_monitor[0] }} às {{ janela_monitor[1] }}{% if monitor.ultima %} · última leitura {{ monitor.ultima|data }}{% endif %}{% if monitor.vencidos %} · {{ monitor.vencidos }} na fila{% endif %}.</p>
    <div class="flex flex-wrap items-center justify-between gap-3">
      <span class="text-sm font-medium">Conferência de checkout</span>
      {{ chave("/amazon/checkout/desligar" if cfg_amazon.checkout_ligado else "/amazon/checkout/ligar", cfg_amazon.checkout_ligado, "conferência de checkout") }}
    </div>
    {{ alerta_sem_login() }}
    {{ alerta_carrinho() }}
    <div class="card-actions"><a class="btn btn-sm btn-ghost" href="/logs?aba=monitor">Ver histórico</a></div>
  </div></div>
  {% endif %}
```

- [ ] **Step 6: CSS**

Run: `uv run python scripts/gerar_css.py`
Expected: `src/tcg_sniper/admin/static/admin.css` atualizado (ou igual).

- [ ] **Step 7: Rodar os testes, suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_admin uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde. Testes do admin que esperavam "Busca na Amazon pausada." para `/amazon/pausar` (ex.: `tests/admin/test_admin_dashboard.py::test_acoes_voltam_para_servicos_com_mensagem`) passam a esperar "Monitor e checkout da Amazon pausados."; ajuste nesses testes só o texto.

- [ ] **Step 8: Commit**

```bash
git add src/tcg_sniper/admin/app.py src/tcg_sniper/admin/templates/servicos.html src/tcg_sniper/admin/static/admin.css tests/admin
git commit -m "feat: Services page has its own Amazon search card with pause and resume"
```

---

### Task 8: Admin — Dashboard com dois cards da Amazon (lane `admin`, depois da Task 7)

**Files:**
- Modify: `src/tcg_sniper/admin/consultas_painel.py` (imports ~26-43; `_saude_amazon` ~198-224 vira duas funções; `saude_servicos` ~287-302; texto do ciclo em `avisos` ~384-395)
- Modify: `src/tcg_sniper/admin/templates/index.html:13` (grade dos cards)
- Modify: `src/tcg_sniper/admin/static/admin.css` (regenerado)
- Test: `tests/admin/test_consultas_painel.py`, `tests/admin/test_admin_dashboard.py`

**Interfaces:**
- Consumes: `COLETOR_AMAZON_BUSCA` (Task 1), `FilaAmazon`, `ProdutoLiga`, `consultas.ultima_coleta_sucesso/ultima_coleta_finalizada`, `consultas_amazon.ciclo_atual`, `_resumo_monitor`, `_contar`, `_quando`.
- Produces: `consultas_painel.NOME_BUSCA = "Amazon (busca)"`, `NOME_MONITOR = "Amazon (monitor e checkout)"`; `saude_servicos(...)` devolve, na ordem, LigaMagic, Amazon (busca), Amazon (monitor e checkout), Casador (IA), WhatsApp. O card da busca tem `detalhe = "<n> buscas na última hora · <m> produtos ativos nunca buscados"`.

- [ ] **Step 1: Escrever os testes (falham)**

Em `tests/admin/test_consultas_painel.py`: acrescente `COLETOR_AMAZON_BUSCA` e `FilaAmazon` aos imports de `tcg_sniper.db.models`; troque `test_quatro_servicos_na_ordem` por:

```python
def test_cinco_servicos_na_ordem(s, config):
    nomes = [x.nome for x in painel.saude_servicos(s, AGORA, config, True)]
    assert nomes == ["LigaMagic", "Amazon (busca)", "Amazon (monitor e checkout)", "Casador (IA)", "WhatsApp"]
```

e troque `test_amazon` e `test_amazon_conta_precos_lidos_nas_ultimas_24h` por:

```python
def test_amazon_busca(s, config):
    busca = saude(s, config)["Amazon (busca)"]
    assert busca.situacao == "ok" and busca.texto == "Nenhum ciclo ainda"
    noite = saude(s, config, agora=datetime(2026, 10, 17, 2, 0, tzinfo=UTC))["Amazon (busca)"]  # 23:00 em SP
    assert noite.situacao == "ok" and "fora do horário (08:00–22:00)" in noite.texto
    coleta(s, TipoColeta.AMAZON, AGORA - timedelta(hours=3))
    coleta(s, TipoColeta.AMAZON, AGORA - timedelta(minutes=30), StatusColeta.RODANDO)
    busca = saude(s, config)["Amazon (busca)"]
    assert busca.situacao == "rodando" and busca.texto == "Ciclo desde 16:10 · último ok 13:40"
    repo.pausar(s, "pausado no admin", AGORA, COLETOR_AMAZON_BUSCA)
    assert saude(s, config)["Amazon (busca)"].situacao == "pausado"
    assert saude(s, config)["Amazon (monitor e checkout)"].situacao == "ok"
    repo.pausar_por_desafio(s, "captcha", AGORA, COLETOR_AMAZON_BUSCA)
    busca = saude(s, config)["Amazon (busca)"]
    assert busca.situacao == "pausado_desafio" and "6082" in busca.detalhe


def test_amazon_busca_conta_buscas_na_ultima_hora_e_nunca_buscados(s, config):
    feitos = [criar_produto(s, f"p{i}") for i in range(4)]
    criar_produto(s, "inativo", ativo=False)
    repo_amz.sincronizar_fila(s, AGORA - timedelta(hours=3))
    repo_amz.reagendar(s, feitos[0].id, AGORA - timedelta(minutes=10), AGORA + timedelta(hours=1), False)
    repo_amz.reagendar(s, feitos[1].id, AGORA - timedelta(hours=2), AGORA + timedelta(hours=1), False)
    detalhe = saude(s, config)["Amazon (busca)"].detalhe
    assert detalhe == "1 buscas na última hora · 2 produtos ativos nunca buscados"


def test_amazon_monitor(s, config):
    monitor = saude(s, config)["Amazon (monitor e checkout)"]
    assert monitor.situacao == "ok" and monitor.detalhe.startswith("0 preços lidos nas últimas 24 h")
    noite = saude(s, config, agora=datetime(2026, 10, 17, 2, 0, tzinfo=UTC))["Amazon (monitor e checkout)"]
    assert "fora do horário (08:00–22:00)" in noite.texto
    repo.pausar(s, "pausado no admin", AGORA, COLETOR_AMAZON)
    assert saude(s, config)["Amazon (monitor e checkout)"].situacao == "pausado"
    assert saude(s, config)["Amazon (busca)"].situacao == "ok"
    repo.pausar_por_desafio(s, "captcha", AGORA, COLETOR_AMAZON)
    monitor = saude(s, config)["Amazon (monitor e checkout)"]
    assert monitor.situacao == "pausado_desafio" and "6081" in monitor.detalhe


def test_amazon_monitor_conta_precos_lidos_nas_ultimas_24h(s, config):
    produto = criar_produto(s, "p1")
    for i, asin in enumerate(("B000000001", "B000000002")):
        anuncio = criar_anuncio(s, asin, produto)
        quando = AGORA - timedelta(hours=1 if i == 0 else 30)
        repo_amz.registrar_preco(
            s, anuncio.id, Decimal(10), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, quando, config.zona
        )
    assert saude(s, config)["Amazon (monitor e checkout)"].detalhe.startswith("1 preços lidos nas últimas 24 h · ")
```

Em `tests/admin/test_admin_dashboard.py`, acrescente:

```python
def test_dashboard_tem_os_dois_cards_da_amazon(cliente):
    texto = cliente.get("/").text
    assert 'data-servico="Amazon (busca)"' in texto and 'data-servico="Amazon (monitor e checkout)"' in texto
    assert "buscas na última hora" in texto and "produtos ativos nunca buscados" in texto
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_admin uv run pytest -q -p no:cacheprovider tests/admin/test_consultas_painel.py tests/admin/test_admin_dashboard.py`
Expected: FAIL (`KeyError: 'Amazon (busca)'`).

- [ ] **Step 3: Implementar**

Em `src/tcg_sniper/admin/consultas_painel.py`: acrescente `COLETOR_AMAZON_BUSCA` e `FilaAmazon` ao import de `tcg_sniper.db.models`. Troque `_saude_amazon` por:

```python
NOME_BUSCA = "Amazon (busca)"
NOME_MONITOR = "Amazon (monitor e checkout)"


def _buscas_na_ultima_hora(s: Session, agora: datetime) -> int:
    """Produtos buscados na última hora (um produto buscado duas vezes na hora conta uma)."""
    return _contar(s, FilaAmazon, FilaAmazon.ultima_busca_em > agora - timedelta(hours=1))


def _nunca_buscados(s: Session) -> int:
    """Produtos ativos que a busca ainda não visitou (inclusive os que nem entraram na fila)."""
    return s.scalar(
        select(func.count())
        .select_from(ProdutoLiga)
        .outerjoin(FilaAmazon, FilaAmazon.produto_id == ProdutoLiga.id)
        .where(ProdutoLiga.ativo.is_(True), FilaAmazon.ultima_busca_em.is_(None))
    ) or 0


def _saude_amazon_busca(s: Session, agora: datetime, cfg: Config) -> SaudeServico:
    estado = repo.obter_estado(s, agora, COLETOR_AMAZON_BUSCA)
    zona = cfg.zona
    detalhe = (
        f"{_buscas_na_ultima_hora(s, agora)} buscas na última hora · "
        f"{_nunca_buscados(s)} produtos ativos nunca buscados"
    )
    if estado.estado is EstadoColetorTipo.PAUSADO_DESAFIO:
        return SaudeServico(
            NOME_BUSCA, "pausado_desafio", f"CAPTCHA pendente: {estado.motivo or ''}".strip(),
            "Resolva pelo noVNC da busca (porta 6082) em Serviços.", "/servicos",
        )
    if estado.estado is EstadoColetorTipo.PAUSADO:
        return SaudeServico(NOME_BUSCA, "pausado", f"Pausada: {estado.motivo or 'sem motivo'}", detalhe, "/servicos")
    ultimo_ok = consultas.ultima_coleta_sucesso(s, (TipoColeta.AMAZON,))
    ciclo = consultas_amazon.ciclo_atual(s)
    if ciclo is not None:
        texto = f"Ciclo desde {ciclo.iniciada_em.astimezone(zona):%H:%M}"
        if ultimo_ok is not None:
            texto += f" · último ok {ultimo_ok.iniciada_em.astimezone(zona):%H:%M}"
        return SaudeServico(NOME_BUSCA, "rodando", texto, detalhe, "/logs?aba=amazon")
    config_amazon = repo_amz.obter_config(s)
    if not (config_amazon.janela_inicio <= agora.astimezone(zona).time() < config_amazon.janela_fim):
        janela = f"{config_amazon.janela_inicio:%H:%M}–{config_amazon.janela_fim:%H:%M}"
        return SaudeServico(NOME_BUSCA, "ok", f"Parada: fora do horário ({janela})", detalhe, "/logs?aba=amazon")
    ultimo = consultas.ultima_coleta_finalizada(s, (TipoColeta.AMAZON,))
    if ultimo is None:
        texto = "Nenhum ciclo ainda"
    else:
        texto = f"Último ciclo {_quando(ultimo.iniciada_em, agora, zona)} ({ultimo.status.value.replace('_', ' ')})"
    return SaudeServico(NOME_BUSCA, "ok", texto, detalhe, "/logs?aba=amazon")


def _saude_amazon_monitor(s: Session, agora: datetime, cfg: Config) -> SaudeServico:
    estado = repo.obter_estado(s, agora, COLETOR_AMAZON)
    lidos = _contar(s, PrecoAtualAmazon, PrecoAtualAmazon.coletado_em >= agora - timedelta(hours=24))
    detalhe = f"{lidos} preços lidos nas últimas 24 h · {_resumo_monitor(s, agora, cfg)}"
    if estado.estado is EstadoColetorTipo.PAUSADO_DESAFIO:
        return SaudeServico(
            NOME_MONITOR, "pausado_desafio", f"CAPTCHA pendente: {estado.motivo or ''}".strip(),
            "Resolva pelo noVNC do monitor (porta 6081) em Serviços.", "/servicos",
        )
    if estado.estado is EstadoColetorTipo.PAUSADO:
        return SaudeServico(NOME_MONITOR, "pausado", f"Pausado: {estado.motivo or 'sem motivo'}", detalhe, "/servicos")
    config_amazon = repo_amz.obter_config(s)
    local = agora.astimezone(cfg.zona).time()
    if not (config_amazon.monitor_janela_inicio <= local < config_amazon.monitor_janela_fim):
        janela = f"{config_amazon.monitor_janela_inicio:%H:%M}–{config_amazon.monitor_janela_fim:%H:%M}"
        return SaudeServico(NOME_MONITOR, "ok", f"Parado: fora do horário ({janela})", detalhe, "/logs?aba=monitor")
    texto = f"Até {config_amazon.monitor_max_paginas_hora} páginas por hora no navegador logado"
    return SaudeServico(NOME_MONITOR, "ok", texto, detalhe, "/logs?aba=monitor")
```

Em `saude_servicos`, troque a linha `_saude_amazon(s, agora, config_efetiva),` por:

```python
        _saude_amazon_busca(s, agora, config_efetiva),
        _saude_amazon_monitor(s, agora, config_efetiva),
```

e o docstring para "Um item por serviço, na ordem LigaMagic, Amazon (busca), Amazon (monitor e checkout), Casador (IA), WhatsApp. ...". Em `avisos`, troque `texto = f"O último ciclo da Amazon ({quando}) terminou com falha."` por `texto = f"O último ciclo da busca na Amazon ({quando}) terminou com falha."`.

Em `src/tcg_sniper/admin/templates/index.html`, troque `<div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">` (a grade dos cards de serviço) por `<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">` (seis cards: cinco serviços e o backup).

- [ ] **Step 4: CSS, testes, suíte, ruff**

Run: `uv run python scripts/gerar_css.py`, depois `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_admin uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde. Testes do Dashboard que procuravam o card `"Amazon"` (ex.: `test_dashboard_amazon_fora_da_janela`, `test_admin_amazon.py` linha ~41 `"Ciclo desde"`) passam a procurar o card "Amazon (busca)" — ajuste nesses testes só o nome; o texto "Ciclo desde" continua no card da busca. Um teste que confira "O último ciclo da Amazon" passa a "O último ciclo da busca na Amazon".

- [ ] **Step 5: Commit**

```bash
git add src/tcg_sniper/admin/consultas_painel.py src/tcg_sniper/admin/templates/index.html src/tcg_sniper/admin/static/admin.css tests/admin
git commit -m "feat: Dashboard shows Amazon search and monitor as separate services"
```

---

### Task 9: Admin — Configurações → Amazon explica os dois navegadores (lane `admin`, depois da Task 8)

**Files:**
- Modify: `src/tcg_sniper/coletor_amazon/config.py` (`ROTULOS` ~41-58, `EXPLICACOES` ~64-92)
- Modify: `src/tcg_sniper/admin/templates/configuracoes.html:12` (aviso no topo da seção Amazon) e `:23-27` (texto do subtítulo do monitor)
- Modify: `src/tcg_sniper/admin/static/admin.css` (regenerado)
- Test: `tests/admin/test_admin_config_tela.py`, `tests/coletor_amazon/test_config_amazon.py`

**Interfaces:**
- Consumes: macro `aviso(tipo, texto)` de `_componentes.html`.
- Produces: textos da tela (nenhuma API nova).

- [ ] **Step 1: Escrever os testes (falham)**

Acrescente a `tests/admin/test_admin_config_tela.py`:

```python
def test_aba_amazon_explica_os_dois_navegadores_e_a_soma_dos_tetos(cliente):
    texto = cliente.get("/configuracoes").text
    trecho = texto[texto.index('id="amazon"') : texto.index('id="ia"')]
    assert "Dois navegadores" in trecho
    assert "porta 6082" in trecho and "porta 6081" in trecho
    assert "soma dos dois tetos" in trecho
    assert "Máximo de buscas por hora (busca)" in trecho
    assert "Máximo de páginas por hora (monitor e checkout)" in trecho
```

Acrescente a `tests/coletor_amazon/test_config_amazon.py`:

```python
def test_explicacoes_dos_tetos_falam_da_soma_no_mesmo_endereco():
    assert "busca" in EXPLICACOES["max_buscas_hora"] and "soma" in EXPLICACOES["max_buscas_hora"]
    assert "busca" in EXPLICACOES["janela_inicio"] and "busca" in EXPLICACOES["janela_fim"]
    assert "soma" in EXPLICACOES["monitor_max_paginas_hora"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_admin uv run pytest -q -p no:cacheprovider tests/admin/test_admin_config_tela.py tests/coletor_amazon/test_config_amazon.py`
Expected: FAIL.

- [ ] **Step 3: Textos**

Em `src/tcg_sniper/coletor_amazon/config.py`, troque em `ROTULOS`:

```python
    "janela_inicio": "Início da busca",
    "janela_fim": "Fim da busca",
    "max_buscas_hora": "Máximo de buscas por hora (busca)",
    "monitor_max_paginas_hora": "Máximo de páginas por hora (monitor e checkout)",
```

e em `EXPLICACOES`:

```python
    "janela_inicio": "Hora (HH:MM) em que a busca de anúncios novos começa, com variação de até 15 minutos.",
    "janela_fim": "Hora (HH:MM) em que a busca de anúncios novos para, com variação de até 15 minutos.",
    "max_buscas_hora": (
        "Teto de buscas por hora do navegador da busca (sem login). A Amazon vê a soma deste teto com o do "
        "monitor, no mesmo endereço."
    ),
    "monitor_max_paginas_hora": (
        "Teto de páginas por hora do navegador logado, somando monitor, conferência de checkout e retirada de "
        "itens do carrinho. A Amazon vê a soma deste teto com o da busca, no mesmo endereço."
    ),
    "pausa_min_s": "Pausa mínima, em segundos, antes de cada página da Amazon (vale para os dois navegadores).",
```

Em `src/tcg_sniper/admin/templates/configuracoes.html`, logo depois de `{% if secao.erros %}...{% endif %}` (antes de `{% if secao.id == "ia" %}`), acrescente:

```html
      {% if secao.id == "amazon" %}
      {{ aviso("info", "Dois navegadores: a busca de anúncios novos roda sem login (noVNC na porta 6082), com o próprio horário e teto de buscas; o monitor, a conferência de checkout e a retirada do carrinho rodam no navegador logado (noVNC na porta 6081), com o horário e o teto do monitor. A Amazon vê a soma dos dois tetos, no mesmo endereço.") }}
      {% endif %}
```

e troque o texto do subtítulo "Monitor de preço" por: `Lê a lista de ofertas dos anúncios confirmados e confere o checkout das candidatas, no navegador logado. Ligar e desligar fica em Serviços → Amazon (monitor e checkout).`

- [ ] **Step 4: CSS, testes, suíte, ruff**

Run: `uv run python scripts/gerar_css.py`, depois `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_admin uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde (um teste que conferia o rótulo antigo "Início da janela"/"Máximo de buscas por hora" troca para o novo).

- [ ] **Step 5: Commit**

```bash
git add src/tcg_sniper/coletor_amazon/config.py src/tcg_sniper/admin/templates/configuracoes.html src/tcg_sniper/admin/static/admin.css tests/admin tests/coletor_amazon/test_config_amazon.py
git commit -m "feat: Amazon settings explain the two browsers and the combined caps"
```

---

### Task 10: Vigia inclui a busca da Amazon (lane `vigia`)

**Files:**
- Modify: `src/tcg_sniper/avisos/vigia.py:1-4` (docstring), `:19-27` (import), `:31-36` (`SERVICOS`)
- Test: `tests/avisos/test_vigia.py`

**Interfaces:**
- Consumes: `COLETOR_AMAZON_BUSCA` (Task 1); `sinal_servico.servico = 'amazon_busca'` gravado pela batida da Task 6.
- Produces: `vigia.SERVICOS[COLETOR_AMAZON_BUSCA] == "coletor-amazon-busca"`.

- [ ] **Step 1: Banco da lane**

Run: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_vigia`

- [ ] **Step 2: Escrever os testes (falham)**

Em `tests/avisos/test_vigia.py`: acrescente `COLETOR_AMAZON_BUSCA` ao import de `tcg_sniper.db.models`; em `todos_vivos`, troque a tupla `(COLETOR_LIGA, COLETOR_AMAZON, COLETOR_CASADOR)` por `(COLETOR_LIGA, COLETOR_AMAZON, COLETOR_AMAZON_BUSCA, COLETOR_CASADOR)`; acrescente ao fim:

```python
def test_busca_da_amazon_muda_abre_com_o_nome_do_servico(sessoes):
    todos_vivos(sessoes, AGORA - timedelta(minutes=1), menos=(COLETOR_AMAZON_BUSCA,))
    verificar(sessoes, AGORA)
    assert abertos(sessoes) == ["coletor-amazon-busca"]


def test_busca_pausada_e_ignorada_e_o_monitor_continua_vigiado(sessoes):
    with sessoes() as s, s.begin():
        repo.pausar(s, "pausado no admin", AGORA, COLETOR_AMAZON_BUSCA)
    todos_vivos(sessoes, AGORA - timedelta(minutes=1), menos=(COLETOR_AMAZON_BUSCA, COLETOR_AMAZON))
    verificar(sessoes, AGORA)
    assert abertos(sessoes) == ["coletor-amazon"]
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_vigia uv run pytest -q -p no:cacheprovider tests/avisos/test_vigia.py`
Expected: FAIL (`abertos == []` no primeiro teste novo).

- [ ] **Step 4: Implementar**

Em `src/tcg_sniper/avisos/vigia.py`, acrescente `COLETOR_AMAZON_BUSCA` ao import e troque `SERVICOS`:

```python
SERVICOS = {
    COLETOR_LIGA: "coletor-liga",
    COLETOR_AMAZON: "coletor-amazon",
    COLETOR_AMAZON_BUSCA: "coletor-amazon-busca",
    COLETOR_CASADOR: "casador",
    COLETOR_NOTIFICADOR: "notificador",
}
```

No docstring do módulo, "a batida de vida dos coletores e do casador" vira "a batida de vida dos coletores (Liga, Amazon monitor e Amazon busca) e do casador".

- [ ] **Step 5: Suíte inteira, ruff e commit**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_vigia uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde.

```bash
git add src/tcg_sniper/avisos/vigia.py tests/avisos/test_vigia.py
git commit -m "feat: service watchdog covers coletor-amazon-busca"
```

---

### Task 11: Regressão, README e pendências (lane `final`, depois de tudo integrado)

**Files:**
- Modify: `README.md` (linhas ~30, ~43-49, ~70, ~170-186, ~208-224, ~297, ~315, ~326, ~380, ~392, ~399, ~415, ~431, ~442, ~509, ~524-527)
- Modify: `docs/PENDENCIAS.md`

**Interfaces:**
- Consumes: tudo das Tasks 1–10.
- Produces: documentação.

- [ ] **Step 1: Banco da lane e regressão inteira**

Run: `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_final`, depois `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_final uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde. Também: `git grep -n "VarreduraAmazon\|coletor_amazon.varredura import\|_teto_monitor"` não acha nada; `git grep -n "6082"` mostra compose, catálogo, formato, Serviços, Dashboard, Configurações e testes.

- [ ] **Step 2: README**

Edite `README.md`:

1. Princípios (~30): "**Amazon com teto e horário.** Na Amazon, a fila tem teto de buscas por hora (200 por padrão)…" vira: "**Amazon com teto e horário.** Na Amazon, a busca tem teto de 90 buscas por hora e o monitor de 180 páginas por hora (padrões; a Amazon vê a soma, cerca de 270 por hora no mesmo endereço), cada um no próprio horário; um CAPTCHA pausa só o serviço que o recebeu até uma pessoa resolver."
2. Diagrama (~43-49): troque o nó `coletor_amz` por dois e acrescente o noVNC 6082:

```
        coletor_amz[coletor-amazon<br/>Chromium logado: monitor de preço,<br/>conferência de checkout e retirada]
        coletor_busca[coletor-amazon-busca<br/>Chromium sem login: busca de anúncios novos]
        ...
        vnc_amz[noVNC :6081]
        vnc_busca[noVNC :6082]
```

e nas ligações acrescente `coletor_busca -- uma página por vez --> amazon`, `coletor_busca --> db`, `coletor_busca --> evo`, `vnc_busca -. tela do Chromium .- coletor_busca`.
3. Parágrafo **Amazon.** (~70): "De 08:00 às 22:00 o `coletor-amazon` procura cada produto ativo…" vira "De 08:00 às 22:00 o `coletor-amazon-busca` (um navegador próprio, sem login) procura cada produto ativo…"; e "Os anúncios confirmados têm o preço lido pelo **monitor de preço** a cada 15 min" vira "Os anúncios confirmados têm o preço lido pelo **monitor de preço** do `coletor-amazon` (o navegador logado) a cada 15 min".
4. Passo 8 (~174-184): no item 2, "Suba tudo de uma vez, não só o `coletor-amazon`" vira "Suba tudo de uma vez, não só os coletores da Amazon"; no item 3 acrescente ao fim: "Faça o mesmo no noVNC da busca, `http://<IP deste PC>:6082/vnc.html` (o CEP muda o preço da busca também). A busca não precisa de login."; troque o **Deu certo se** por: "**Deu certo se** `docker compose logs coletor-amazon --tail 20` mostrar `varredura da Amazon (monitor) iniciada`, `docker compose logs coletor-amazon-busca --tail 20` mostrar `varredura da Amazon (busca) iniciada` e, no noVNC da porta 6082, aparecerem buscas a cada 8 a 20 segundos (dentro do horário de 08:00 às 22:00)."
5. Seção 10 (~210-218): troque "O `coletor-amazon` tem três trabalhos num navegador só, nesta ordem de prioridade:" por "A Amazon roda em dois serviços, cada um com o próprio navegador. O `coletor-amazon` (navegador logado, noVNC 6081) faz, nesta ordem de prioridade:"; o item 3 (**Descoberta**) sai da lista e vira o parágrafo: "O `coletor-amazon-busca` (navegador próprio, sem login, noVNC 6082) faz só a **descoberta**: a busca de anúncios novos, para produtos sem anúncio confirmado (e uma vez por semana para os casados), dentro da janela da busca e com o teto de buscas por hora (padrão 90). Um CAPTCHA, um erro ou uma pausa num serviço não para o outro: cada um tem o próprio card e o próprio Retomar em Serviços, e os avisos dizem a origem ("Amazon (busca) · CAPTCHA" ou "Amazon (monitor) · CAPTCHA")." O parágrafo do teto vira: "A conferência e o monitor dividem um teto de páginas por hora (padrão 150; a retirada de item do carrinho também conta). Ao chegar no teto, o monitor espera; a busca segue no próprio teto, no outro navegador. A Amazon vê a soma dos dois tetos no mesmo endereço (até 90 + 180 = 270 por hora com os tetos no máximo recomendado). Se o monitor não cabe no intervalo, o Dashboard avisa (aumente o intervalo ou o teto). A **rodada do monitor** (aviso no grupo admin) sai uma vez por volta: quando ele leu todos os anúncios que estavam vencidos no começo da volta."
6. Retirada (~220): "Com a Amazon pausada (CAPTCHA, erros seguidos ou desligada em Serviços), a retirada automática também para" vira "Com o monitor da Amazon pausado (CAPTCHA, erros seguidos ou desligado em Serviços → Amazon (monitor e checkout)), a retirada automática também para".
7. Login (~224): "(o botão aparece também com a Amazon pausada por CAPTCHA)" vira "(o botão aparece também com o monitor pausado por CAPTCHA)".
8. Atualização (~297): "(`docker compose up -d --build coletor-amazon`, por exemplo)" fica; acrescente no fim do item: "Da separação da busca em diante, `coletor-amazon` e `coletor-amazon-busca` sobem juntos."
9. Linha ~315 ("Confira: em Configurações → Amazon, a seção "Monitor de preço" com os padrões (15 min, 08:00–22:00, 150 páginas por hora…"): mantenha e acrescente "; em Serviços, os cards Amazon (busca) e Amazon (monitor e checkout) ligados".
10. Listas de `docker compose stop` (~326 e ~431): acrescente `coletor-amazon-busca` logo depois de `coletor-amazon`.
11. Tabela das telas (~380): "Pausar e Retomar (Amazon)" vira "Pausar e Retomar (Amazon (busca) e Amazon (monitor e checkout))".
12. Avisos (~392 e ~399): em ~392 o exemplo "noVNC da Amazon (porta 6081)" vira "noVNC do monitor (porta 6081)" e "Admin → Serviços → Amazon → Retomar" vira "Admin → Serviços → Amazon (busca) → Retomar"; a linha da tabela da Amazon (~399) vira: "| Amazon | ✅ busca concluída · ✅ rodada do monitor (uma por volta) · 🟡 busca parcial · 🔴 busca falhou · 🔴 CAPTCHA, 🔴 pausada e 🟡 erro inesperado — cada um com a origem no título, (busca) ou (monitor), e resolvido próprio · 🔴 conta sem login · 🔴 conferir o carrinho (um por ASIN) · 🟡 ciclo interrompido (busca) |".
13. Segurança (~415): "Não exponha as portas 8000, 6080 e 6081" vira "Não exponha as portas 8000, 6080, 6081 e 6082".
14. Configurações (~442): "**Amazon**: desconto mínimo, teto de buscas por hora, horário…" vira "**Amazon**: desconto mínimo, horário e teto da busca (navegador sem login), horário e teto do monitor (navegador logado) e demais ajustes do motor de oportunidades".
15. Desenvolvimento (~509): acrescente `uv run tcg-sniper coletor-amazon-busca` à lista; Estrutura (~524-527): "coletor-amazon, notificador…" vira "coletor-amazon, coletor-amazon-busca, notificador…" e a linha de `coletor_amazon/` vira "monitor de preço, conferência de checkout, fila de buscas (dois laços: `varredura_busca`, `varredura_monitor`, sobre `varredura_base`), parsers da Amazon e cliques permitidos".

Depois acrescente, na seção de atualização (perto de "Implantar o casamento por par"), a subseção:

```markdown
### Implantar a busca da Amazon separada

Faça o backup de sempre antes (ver [Backup do banco](#backup-do-banco)). A migração `c6a2f8e4d1b9` cria o estado do serviço `amazon_busca` (ativo), baixa os tetos para no máximo 90 buscas por hora (busca) e 180 páginas por hora (monitor) — um valor seu menor fica — e fecha como interrompido um ciclo de busca que estiver rodando. Suba tudo junto (`docker compose up -d --build`) e confira: `docker compose ps` com `coletor-amazon` e `coletor-amazon-busca` de pé, os dois cards da Amazon em Serviços, e `http://<IP deste PC>:6082/vnc.html` abrindo (informe o CEP também nesse navegador). O primeiro CAPTCHA do navegador novo é provável: o grupo admin recebe "Amazon (busca) · CAPTCHA"; resolva no noVNC 6082 e clique em Retomar no card Amazon (busca). O monitor não para.
```

- [ ] **Step 3: Pendências**

Em `docs/PENDENCIAS.md`:

1. "Última revisão": `2026-10-19 (busca da Amazon separada do monitor pronta no código, falta implantar; antes: casamento por par).`
2. Em "## 0. Crítico", troque o item "**Busca da Amazon parada pelo monitor**" por:

```markdown
- [ ] **Implantar a busca da Amazon separada** (código pronto, `<hash do commit "feat: split Amazon collector into search and monitor loops">`): backup, `docker compose up -d --build`, conferir os dois serviços da Amazon no ar, a migração `c6a2f8e4d1b9` aplicada e o noVNC 6082 abrindo (README → "Implantar a busca da Amazon separada").
```

(Pegue o hash com `git log --format=%h -1 --grep "split Amazon collector into search and monitor loops"`.)
3. Em "## 3. Acompanhar (sem código)": troque o item "Frequência de CAPTCHA da Amazon com o monitor no teto de produção de **1000 páginas/h**…" por:

```markdown
- [ ] CAPTCHA da Amazon com os dois navegadores somando ~270 páginas/h no mesmo endereço (busca 90/h + monitor 180/h, desde a separação). Se os CAPTCHAs aumentarem (avisos "Amazon (busca) · CAPTCHA" ou "Amazon (monitor) · CAPTCHA"), baixar os tetos em Configurações → Amazon.
- [ ] Quantos produtos ativos ainda não foram buscados (card Amazon (busca) no Dashboard; eram 1941 de 1969 sem candidato em 2026-10-19). Com 90 buscas/h e a janela de 14 h, a primeira passada nos ~2000 produtos leva cerca de 2 dias.
```

4. Em "## Decisões registradas", troque "2026-10-19: teto do monitor da Amazon em produção é 1000 páginas/h; baixar para ~220 só se os CAPTCHAs aumentarem." por "2026-10-19: busca e monitor da Amazon em serviços separados (busca sem login, 90 buscas/h; monitor logado, 180 páginas/h; a migração baixou o monitor de 1000 para 180)."
5. No topo de "## Concluídas", o bloco:

```markdown
### Busca da Amazon separada do monitor (2026-10-19)

Spec `docs/superpowers/specs/2026-10-19-amazon-busca-separada-design.md`, plano `docs/superpowers/plans/2026-10-19-amazon-busca-separada.md`. Resolve a busca parada pelo monitor (um navegador só, prioridade estrita; 1941 de 1969 produtos sem candidato nunca buscados).

- [x] Dois serviços: `coletor-amazon-busca` (navegador sem login, perfil `perfil-amazon-busca`, noVNC 6082) e `coletor-amazon` (retirada, checkout e monitor, navegador logado, noVNC 6081), sobre uma base comum; teste de importação garante que a busca não alcança checkout/carrinho/monitor (`<hash>`).
- [x] Estado `amazon_busca`, tetos 90/180 com `least` na migração, ciclo rodando fechado como interrompido (`<hash>`).
- [x] Avisos com a origem no título e resolvido próprio; rodada do monitor uma vez por volta inteira (`<hash>`).
- [x] Serviços, Dashboard (buscas na última hora, produtos nunca buscados), Configurações e vigia com os dois serviços (`<hash>`).
```

(Preencha cada `<hash>` com `git log --oneline` do commit correspondente: Tasks 4–5, Task 1, Tasks 2 e 5, Tasks 7–10.)
6. Em "## Ordem sugerida", se houver linha sobre a busca da Amazon parada, troque por "0. Implantar a busca da Amazon separada."

- [ ] **Step 4: Suíte inteira, ruff e commit**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_final uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde.

```bash
git add README.md docs/PENDENCIAS.md
git commit -m "docs: Amazon search and monitor as separate services; pending list"
```

---

## Implantação (depois do merge, com ok do usuário; o controlador faz, não um subagente)

Segue o CLAUDE.md e o spec ("Deploy"):

1. Parar os serviços (`docker compose stop coletor-liga coletor-amazon casador notificador manutencao admin api web`).
2. Backup do banco de produção em `dados/backups/` (`tcg-antes-amazon-busca-separada-<data>.dump`) e conferir o arquivo.
3. `docker compose up -d --build` (todos juntos; o `migrate` aplica `c6a2f8e4d1b9` antes).
4. Conferir: `docker compose ps` com `coletor-amazon` e `coletor-amazon-busca` de pé; `SELECT id, coletor, estado FROM estado_coletor WHERE id = 6` → `amazon_busca | ativo`; `SELECT max_buscas_hora, monitor_max_paginas_hora FROM config_amazon` → `90 | 180` (ou menores, se já eram); logs dos dois com "varredura da Amazon (monitor) iniciada" e "varredura da Amazon (busca) iniciada"; `http://<IP>:6082/vnc.html` abrindo (pedir ao usuário para informar o CEP nesse navegador).
5. Na primeira hora: o card Amazon (busca) do Dashboard mostrando buscas na última hora > 0 e "produtos ativos nunca buscados" caindo; se vier "Amazon (busca) · CAPTCHA", o usuário resolve no noVNC 6082 e clica em Retomar no card da busca.
