# Casamento por par (anúncio × produto) e busca alternativa Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O casamento deixa de ser coluna do anúncio e passa a ser uma tabela de pares `casamento` (anúncio × produto): ignorado vale só para o par, um anúncio é confirmado para no máximo um produto, "Desfazer" faz a IA reavaliar, produtos 7 dias sem candidato ganham termos de busca alternativos gerados pela IA, e a tela do produto em Casamentos ganha os botões "Rebuscar agora", "Reavaliar com a IA" e "Gerar termos de busca".

**Architecture:** `db/repositorio_casamento.py` (novo) é a única porta de escrita dos pares (confirmar, ignorar, desfazer, trocar, link, reavaliar), com trava da linha do anúncio e índice único parcial como garantia; `db/repositorio_termos.py` (novo) guarda os termos e decide quem está "em seca". A busca (`gravar_busca`) cria/atualiza o par do produto buscado; o casador avalia pares e, numa etapa própria do ciclo, gera os termos; monitor, checkout, oportunidades, fila e telas leem os pares confirmados. As colunas antigas de `anuncio_amazon` convivem (sem uso pelo código novo) enquanto as lanes portam cada área e saem na última tarefa, na mesma revisão do Alembic.

**Tech Stack:** Python 3.12 (Docker; o venv local do uv pode ser 3.14), uv, SQLAlchemy 2 + Alembic, Postgres 16, FastAPI + Jinja2 + DaisyUI 5 (admin antigo), Playwright (coletores), OpenAI Responses API (casador), pytest.

**Spec:** `docs/superpowers/specs/2026-10-19-casamento-por-par-design.md`

## Global Constraints

- Nomes, comentários, mensagens e textos de tela em português, como o resto do código. Mensagens de commit em inglês, no formato `feat:`/`fix:`/`test:`/`docs:`/`chore:`, **sem** linha `Co-Authored-By` nem qualquer trailer de IA.
- Repositório público: nada de dado pessoal (telefone, grupo, IP real, e-mail, ASIN de compra pessoal) em código, teste, fixture ou documento.
- Regras do spec (verbatim): "**Ignorado vale só para aquele par.**"; "**Um anúncio é sempre um produto só:** pode estar pendente/ignorado para vários produtos, mas **confirmado para no máximo um**."; "**Ignorados atuais:** recuperação natural daqui para frente (sem rebusca forçada, sem reavaliação em massa pela IA)."; busca alternativa "entram depois de **7 dias sem candidato**"; termos "no máximo 3 termos, cada um com até 80 caracteres, sem repetir o nome original nem o nome em inglês, sem link, sem vazio".
- Preço conferido = itens + impostos, **sem** frete (regra do usuário; nada nesta mudança mexe nisso).
- Coletor da Amazon: segurança inalterada — nunca confirmar pedido, nunca clicar em "Comprar agora"; esta mudança não toca `checkout.py`, `cliques.py` nem `parsers_checkout.py`.
- Admin: só componentes do DaisyUI 5 e utilitários do Tailwind, classes literais (nunca montadas por concatenação); toda tarefa que mexe em template regenera `src/tcg_sniper/admin/static/admin.css` com `uv run python scripts/gerar_css.py` e commita (o teste `test_css_em_dia_com_os_templates` confere). A regra das ações fica em funções de repositório/serviço, nunca no template (a fase 3 reaproveita).
- O serviço novo `src/tcg_sniper/api/` não usa os campos do casamento e não muda.
- Testes só no Postgres de teste (container `postgres-teste`, `127.0.0.1:5433`), um banco por lane (o fixture `engine` apaga o schema). Criar o banco: no checkout principal (`D:/Git/Pessoal/Python/tcg-sniper`) `docker compose exec -T postgres-teste createdb -U tcg tcg_test_<lane>`; de dentro de um worktree `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_<lane>` ("already exists" é ok). `<lane>` = `t` + número da tarefa (ex.: `tcg_test_t4`). Ao fim de cada tarefa, verdes: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_<lane> uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`.
- Nunca mexer no checkout nem na stack de produção: nada de `docker compose up/down/build/restart/run` nem `migrate` contra o Postgres de produção. Cada lane trabalha no próprio worktree (`superpowers:using-git-worktrees`) e nada é escrito fora dele (pasta temporária do pytest à parte; as ferramentas do `gerar_css.py` ficam em `<worktree>/.ferramentas/`). Tudo que uma lane sobe é parado antes de ela terminar.
- Transição (decisão deste plano, ver abaixo): até a Task 7, `anuncio_amazon.produto_id/status_casamento/origem_casamento/revisado_em` e `fila_amazon.ultimo_termo_en` continuam no banco, mas **nenhum código novo ou portado lê ou grava essas colunas** (únicas exceções, marcadas com comentário e removidas na Task 7: `tests/fakes.py::criar_anuncio` e `repositorio_amazon.casar_link_manual`, que as mantêm iguais ao par confirmado para as áreas ainda não portadas). Se a suíte inteira falhar num teste de **outra** área por causa da sua mudança, porte esse teste para pares (`fakes.criar_par`, `repo_casamento`) no seu commit, sem mexer em código de produção de outra lane.

## Review Focus

1. **Anúncio confirmado num produto e pendente/ignorado em outros, quando a confirmação sai** (Desfazer ou Ignorar o confirmado, no admin ou pelo automático): os pares `outro_confirmado` voltam a pendente e nenhum outro par muda; decisões `manual` ficam. Testes na Task 1 (`test_desfazer_confirmado_volta_a_pendente_reabre_outros_e_pede_reavaliacao`, `test_ignorar_o_confirmado_reabre_os_outro_confirmado`) e na Task 6 (`test_desfazer_reabre_o_par_do_outro_produto`).
2. **Você confirma no admin enquanto o automático da IA confirma o mesmo anúncio para outro produto** (ou duas abas abertas): só uma confirmação vale; a outra vê "já confirmado para outro produto" e nada muda. Testes na Task 1 (`test_confirmacoes_concorrentes_so_uma_vale`, `test_indice_unico_recusa_dois_confirmados_no_mesmo_anuncio`), Task 3 (`test_automatico_nao_confirma_anuncio_que_ficou_confirmado_em_outro_produto`) e Task 6 (`test_confirmar_anuncio_ja_confirmado_mostra_erro_e_nao_muda`).
3. **Termos da IA com lixo** (link, o próprio nome com outra pontuação ou caixa, 81+ caracteres, idioma "es", lista vazia, objeto sem a lista): descartados; sem nenhum válido, a tentativa fica marcada e só repete depois de 7 dias; o produto segue com o nome normal. Testes na Task 3 (`test_descarta_invalidos`, `test_termos_invalidos_sao_descartados_e_so_tenta_de_novo_em_7_dias`).
4. **Produto que sai da seca, ou índice de termo que sobrou de uma seca antiga** (sequência encolheu de 5 para 2 termos): a fila volta ao nome normal e nunca quebra por índice fora da lista. Testes na Task 2 (`test_candidato_novo_na_seca_volta_ao_nome_normal`, `test_indice_maior_que_a_sequencia_nao_quebra`).
5. **"Reavaliar com a IA" ou "Desfazer" num produto que já tem casamento**: os pares antigos (vistos antes do primeiro casamento, que o `so_descoberta` pularia) também são reavaliados, mesmo com a assinatura igual. Testes na Task 3 (`test_reavaliar_produto_casado_reavalia_tambem_os_pares_antigos`, `test_desfazer_faz_a_ia_reavaliar_mesmo_sem_mudar_os_dados`).
6. **Banco de produção com anúncio sem `produto_id`** ou com par antigo `outro_confirmado` sem confirmado no downgrade: a migração não cria par para quem não tem produto; o downgrade escolhe o confirmado ou o par mais antigo e nunca grava `outro_confirmado` na coluna antiga. Testes na Task 1 (`test_migracao_copia_um_par_por_anuncio_e_prepara_a_fila`, `test_downgrade_refaz_as_colunas_pelo_confirmado_ou_pelo_par_mais_antigo`).

## Decisões tomadas neste plano (o spec não fixava)

- **Transição em uma revisão só, editada em duas etapas.** A Task 1 cria a revisão `a9d4f2c6e8b1_casamento_por_par.py` (tabelas novas, cópia, conferência, índice; `anuncio_amazon.status_casamento` passa a aceitar nulo); a Task 7 acrescenta à **mesma** revisão a remoção das colunas antigas (e o downgrade que as refaz). Nada é implantado entre as duas, e o `env.py` roda todas as migrações numa transação só: em produção, criar, copiar, conferir e remover acontecem juntos; um erro desfaz tudo.
- **Coluna `casamento.reavaliar`** (bool, padrão falso): Desfazer e "Reavaliar com a IA" a ligam e zeram `avaliacao_ia.aplicada_em` do par; o casador avalia o par mesmo com a assinatura igual e mesmo que o `so_descoberta` o pulasse, e desliga a marca ao gravar a avaliação. Consequência (spec: "a avaliação antiga do par deixa de valer como já aplicada"): com o automático ligado, um Desfazer pode ser decidido de novo pela IA; para tirar de vez, use Ignorar.
- **Tirar a confirmação reabre `outro_confirmado`.** Desfazer **e** Ignorar um par confirmado devolvem a pendente os pares `outro_confirmado` do anúncio. Trocar não reabre (o anúncio continua confirmado, agora para o novo produto). Os reabertos mantêm a avaliação da IA que já tinham (não ganham `reavaliar`).
- **"Reavaliar com a IA"** volta a pendente os pares do produto `pendente` e os `ignorado` de origem `sugerido_ia`, `automatico_ia` ou `outro_confirmado` — mas pula o `outro_confirmado` cujo anúncio continua confirmado em outro produto (voltaria pendente sem poder ser confirmado). Pede "Rodar agora" ao casador.
- **Concorrência:** toda escrita de par trava antes a linha do anúncio (`SELECT … FOR UPDATE` em `anuncio_amazon`), relê e só então decide; o índice único parcial `uq_casamento_confirmado` é a garantia final (`IntegrityError` num SAVEPOINT vira `JaConfirmado`). `JaConfirmado` = "já confirmado para outro produto"; nada muda.
- **Oportunidades:** confirmar fecha as abertas do anúncio para outros produtos; ignorar, desfazer e trocar um par confirmado fecham as abertas do anúncio (como hoje).
- **Trocar no admin** é a ação `trocar` (a `confirmar` recusa quando o anúncio já é confirmado de outro produto). A origem do novo par é a de `origem_da_decisao` (sugerido_ia se a IA avaliou o par); o confirmado anterior vira `ignorado`/`manual`. "É de outro produto" leva `?de=<produto>` e a lista de parecidos tira esse produto e o já confirmado.
- **Toda ação do admin sobre um anúncio leva `produto_id`** (o par); sem ele, 400; par inexistente em ignorar/desfazer, 404.
- **Fila:** `fila_amazon.indice_termo` (o próximo termo da sequência) substitui `ultimo_termo_en`. A sequência é: nome em português, nome em inglês (se der um termo diferente, sem diferenciar maiúsculas) e, só em seca, os termos guardados. O índice é usado módulo o tamanho da sequência. A migração preserva o próximo termo de hoje (`1` se a última busca foi em português e há busca anterior).
- **Seca** = produto ativo na fila, sem par confirmado, e `coalesce(fila_amazon.ultimo_par_novo_em, entrou_em) <= agora − 7 dias`. `ultimo_par_novo_em` é gravado pela busca quando cria um par **pendente** para o produto buscado (par `outro_confirmado` não conta). A migração inicializa com o par mais recente do produto. O "candidato" do ritmo da fila (`ultimo_candidato_em`: confirmado no desconto) não muda.
- **Geração dos termos:** etapa ao fim de `ServicoCasador.ciclo()` (só com a IA ligada, ativa e com chave), no máximo `TERMOS_POR_CICLO = 5` produtos por ciclo, finalidade `"termos"` em `chamada_ia`, mesmo modelo de Configurações → IA, sem imagem. Ordem: pedidos do admin primeiro (mesmo com termos guardados: regenera), depois os em seca sem termos e sem tentativa nos últimos 7 dias. `SemOrcamento` encerra a etapa sem marcar tentativa (tenta no próximo período) e usa o aviso de teto que já existe; resposta fora do formato ou sem termo válido marca `termos_tentados_em` (7 dias).
- **Botão "Gerar termos de busca":** o admin não chama a OpenAI (não tem transporte): grava `fila_amazon.termos_pedidos_em` e pede "Rodar agora" ao casador; a tela avisa se a IA está desligada/sem chave ou se o produto ainda não entrou na fila.
- **`pares_pendentes`** passa a trazer só produtos ativos (spec: "de produtos ativos"), sem os pares cujo anúncio é confirmado de algum produto, na ordem `visto_ultimo_em` do par (desc) e ids. **`pares_decididos`** deixa de fora `outro_confirmado` (decisão do sistema, não sua).
- **Logs (monitor e checkout)** mostram o produto do par confirmado do anúncio (sem confirmado, "—").
- **Dashboard e menu:** contagens por par; "ignorados" inclui `outro_confirmado`. Nos dados migrados os números são os de hoje (um par por anúncio).
- **Migração:** só anúncios com `produto_id` ganham par. Downgrade: por anúncio, o par confirmado ou, sem confirmado, o mais antigo (`visto_primeiro_em`, depois `produto_id`); `outro_confirmado` vira `manual` na coluna antiga; anúncio sem par fica `pendente`. O teste do aborto chama a função `conferir_um_confirmado_por_anuncio` do módulo da migração numa transação desfeita no fim (com dados reais a cópia nunca gera dois confirmados).
- **`termo_busca`:** `id` serial como PK, únicos `(produto_id, termo)` e `(produto_id, ordem)`, checks `ordem BETWEEN 1 AND 3`, `char_length(termo) BETWEEN 1 AND 80`, `idioma IN ('pt','en')`.

---

## Ondas (para execução paralela)

- **Onda A:** Task 1 (fundação: modelos, migração, `repositorio_casamento`, `repositorio_termos`, fakes).
- **Onda B (em paralelo, cada uma no próprio worktree, todas a partir da Task 1):** Task 2 (busca e fila, lane `busca`), Task 3 (casador e termos, lane `casador`), Task 4 (monitor, checkout e oportunidades, lane `monitor`), Task 5 (admin: listas, menu, dashboard, ofertas e produto, lane `admin`).
- **Onda C:** Task 6 (admin: tela do produto em Casamentos, ações, trocar e botões) — mesma lane `admin`, depois da Task 5; começa do branch integrado da Onda B.
- **Onda D:** Task 7 (remove as colunas antigas, regressão dos números, guarda global, README e `docs/PENDENCIAS.md`) — depende de todas.
- Conflitos esperados e como resolver: `src/tcg_sniper/db/repositorio_amazon.py` (Task 2 mexe em `_descoberta_liberada`, `reagendar`, `gravar_busca` e acrescenta `GravacaoBusca`; Task 4 em `confirmados_com_referencia`, `_confirmados_ativos` e `candidatas_ao_checkout`; as duas acrescentam `Casamento` ao import de modelos e `from tcg_sniper.db import repositorio_casamento as repo_casamento`: manter um de cada); `tests/db/test_repositorio_monitor.py` (Task 2 só em `test_descoberta_pula_casados_ate_a_busca_semanal` se precisar; Task 4 acrescenta testes no fim: manter tudo); `tests/db/test_repositorio_amazon.py` (Task 2 nos testes de fila e `gravar_busca`; ninguém mais até a Task 7); `src/tcg_sniper/admin/static/admin.css` (Tasks 5 e 6 regeneram em sequência; na integração, se houver conflito, rodar `uv run python scripts/gerar_css.py` e commitar).

## Arquivos

| Arquivo | Responsabilidade | Tasks |
|---|---|---|
| `src/tcg_sniper/db/models.py` | `OrigemCasamento.OUTRO_CONFIRMADO`, `Casamento`, `TermoBusca`, colunas novas de `FilaAmazon`; colunas antigas saem | 1, 7 |
| `src/tcg_sniper/db/migrations/versions/a9d4f2c6e8b1_casamento_por_par.py` (novo) | tabelas, cópia, conferência, índice único parcial, fila; remoção das colunas antigas | 1, 7 |
| `src/tcg_sniper/db/repositorio_casamento.py` (novo) | API de pares: registrar visto, confirmar, ignorar, desfazer, trocar, link, reavaliar, condição de confirmado | 1 |
| `src/tcg_sniper/db/repositorio_termos.py` (novo) | termos guardados, seca, pedido, tentativa, quem gera | 1 |
| `tests/fakes.py` | `criar_anuncio` com par, `criar_par` | 1, 7 |
| `src/tcg_sniper/db/repositorio_amazon.py` | `casar_link_manual` (1); fila e `gravar_busca` (2); monitor e checkout (4); limpeza (7) | 1, 2, 4, 7 |
| `src/tcg_sniper/coletor_amazon/termo.py`, `busca.py`, `varredura.py` | sequência de termos, busca por termo, rotação na fila | 2 |
| `src/tcg_sniper/db/repositorio_ia.py`, `casador/servico.py`, `casador/termos.py` (novo) | pares pendentes/decididos, aplicar por par, reavaliar, geração dos termos | 3 |
| `src/tcg_sniper/admin/consultas.py` | Logs do monitor e do checkout pelo par confirmado | 4 |
| `src/tcg_sniper/admin/consultas_amazon.py`, `consultas_menu.py`, `consultas_painel.py`, `templates/produto.html` | listas, menu, dashboard, ofertas e produto por par | 5 |
| `src/tcg_sniper/admin/consultas_amazon.py` (`detalhe_casamento`, `sugestoes_para`), `app.py`, `templates/casamentos_produto.html`, `trocar.html`, `_componentes.html` | tela do produto, ações por par, trocar, três botões, termos | 6 |
| `tests/db/test_regressao_casamento_por_par.py`, `tests/test_sem_casamento_no_anuncio.py` (novos), `README.md`, `docs/PENDENCIAS.md` | regressão dos números, guarda global, documentação | 7 |

---

### Task 1: Fundação — modelos, migração e API de pares

**Files:**
- Modify: `src/tcg_sniper/db/models.py` (`OrigemCasamento`, `AnuncioAmazon` ~222-251, `FilaAmazon` ~294-305; classes novas `Casamento` e `TermoBusca` logo depois de `FilaAmazon`)
- Create: `src/tcg_sniper/db/migrations/versions/a9d4f2c6e8b1_casamento_por_par.py`
- Create: `src/tcg_sniper/db/repositorio_casamento.py`
- Create: `src/tcg_sniper/db/repositorio_termos.py`
- Modify: `src/tcg_sniper/db/repositorio_amazon.py:419-442` (`casar_link_manual` passa a usar os pares)
- Modify: `tests/fakes.py` (`criar_anuncio`, novo `criar_par`)
- Modify: `tests/db/test_migracao.py:238-243` (limpeza do teste antigo apaga os pares antes dos anúncios)
- Test: `tests/db/test_repositorio_casamento.py`, `tests/db/test_repositorio_termos.py`, `tests/db/test_migracao_casamento.py` (novos); `tests/db/test_migracao.py::test_migracao_igual_aos_modelos` confere modelo × migração

**Interfaces:**
- Consumes: modelos existentes (`AnuncioAmazon`, `AvaliacaoIA`, `FilaAmazon`, `Oportunidade`, `ProdutoLiga`, `StatusCasamento`, `_enum`, `DATA`); head atual do Alembic `f8d2a6c4e1b3`; `repositorio_amazon.priorizar_na_fila`, `TITULO_MANUAL`.
- Produces:
  - `models.OrigemCasamento.OUTRO_CONFIRMADO = "outro_confirmado"`.
  - `models.Casamento(anuncio_id: int, produto_id: int, status: StatusCasamento, origem: OrigemCasamento | None, revisado_em: datetime | None, visto_primeiro_em: datetime, visto_ultimo_em: datetime, reavaliar: bool)` — PK `(anuncio_id, produto_id)`; índices `uq_casamento_confirmado` (único parcial, `status = 'confirmado'`), `ix_casamento_produto_status`, `ix_casamento_status`.
  - `models.TermoBusca(id, produto_id: int, termo: str, idioma: str, ordem: int, criado_em: datetime)`.
  - `models.FilaAmazon` ganha `indice_termo: int` (padrão 0), `ultimo_par_novo_em: datetime | None`, `termos_tentados_em: datetime | None`, `termos_pedidos_em: datetime | None`.
  - `repositorio_casamento`: `class JaConfirmado(Exception)` (atributos `anuncio_id`, `produto_id` = produto do confirmado existente; `str()` = `"já confirmado para outro produto"`); `ORIGENS_REAVALIAVEIS: tuple[OrigemCasamento, ...]`; `condicao_confirmado(anuncio_id) -> ColumnElement[bool]`; `produtos_casados() -> Select`; `obter_par(s, anuncio_id: int, produto_id: int, *, travar: bool = False) -> Casamento | None`; `confirmado_do_anuncio(s, anuncio_id: int) -> Casamento | None`; `travar_anuncio(s, anuncio_id: int) -> AnuncioAmazon`; `registrar_visto(s, anuncio_id: int, produto_id: int, agora: datetime) -> tuple[Casamento, bool]`; `confirmar(s, anuncio_id, produto_id, agora, origem=OrigemCasamento.MANUAL) -> Casamento`; `ignorar(s, anuncio_id, produto_id, agora, origem=OrigemCasamento.MANUAL) -> Casamento | None`; `desfazer(s, anuncio_id, produto_id, agora) -> Casamento | None`; `trocar(s, anuncio_id, produto_id, agora, origem=OrigemCasamento.MANUAL) -> Casamento`; `casar_asin(s, produto_id: int, asin: str, agora: datetime, titulo_provisorio: str) -> AnuncioAmazon`; `reavaliar_produto(s, produto_id: int, agora: datetime) -> int`; `marcar_reavaliado(s, anuncio_id: int, produto_id: int) -> None`; `fechar_oportunidades(s, anuncio_id: int, agora: datetime, exceto_produto_id: int | None = None) -> int`.
  - `repositorio_termos`: `SECA = timedelta(days=7)`, `MAX_TERMOS = 3`, `TERMO_MAX = 80`, `IDIOMAS = ("pt", "en")`; `termos_do_produto(s, produto_id) -> list[TermoBusca]`; `em_seca(s, produto_id, agora) -> bool`; `guardar_termos(s, produto_id, termos: Sequence[tuple[str, str]], agora) -> list[TermoBusca]` (ValueError fora de 1..3); `marcar_tentativa(s, produto_id, agora) -> None`; `pedir_termos(s, produto_id, agora) -> bool`; `produtos_para_gerar_termos(s, agora, limite: int) -> list[ProdutoLiga]`.
  - `tests/fakes.py`: `criar_anuncio(s, asin="B000000001", produto=None, status=StatusCasamento.PENDENTE, agora=T0, origem=None) -> AnuncioAmazon` (com `produto`, cria também o par); `criar_par(s, anuncio, produto, status=StatusCasamento.PENDENTE, origem=None, agora=T0, revisado_em=None) -> Casamento`.
  - Migração: módulo com `conferir_um_confirmado_por_anuncio(bind) -> None` (RuntimeError com "mais de um casamento confirmado").

- [ ] **Step 1: Banco da lane**

Run (checkout principal): `docker compose exec -T postgres-teste createdb -U tcg tcg_test_t1`
Expected: sem saída (ou "already exists").

- [ ] **Step 2: Escrever os testes do repositório de pares (falham)**

Crie `tests/db/test_repositorio_casamento.py`:

```python
import threading
from datetime import timedelta
from decimal import Decimal

import pytest
from fakes import T0, criar_anuncio, criar_par, criar_produto
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import Casamento, Envio, OrigemCasamento, StatusCasamento

PENDENTE, CONFIRMADO, IGNORADO = StatusCasamento.PENDENTE, StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO
MANUAL, OUTRO = OrigemCasamento.MANUAL, OrigemCasamento.OUTRO_CONFIRMADO


def situacao(s, anuncio, produto):
    par = repo_casamento.obter_par(s, anuncio.id, produto.id)
    return None if par is None else (par.status, par.origem)


def abrir_op(s, anuncio, produto):
    return repo_amz.abrir_oportunidade(
        s, anuncio_id=anuncio.id, produto_id=produto.id, preco_amazon=Decimal(1), preco_liga=Decimal(2),
        desconto_pct=Decimal(50), vendedor_id=None, envio=Envio.AMAZON, agora=T0, conferido=False,
    )


def avaliacao(s, anuncio, produto):
    return repo_ia.gravar_avaliacao(
        s, anuncio_id=anuncio.id, produto_id=produto.id, mesmo_produto=True, confianca=99, motivo="m",
        modelo="gpt-5", assinatura="x", sem_imagem=False, chamada_id=None, agora=T0,
    )


def test_registrar_visto_cria_pendente_e_depois_so_atualiza_o_visto(s):
    p = criar_produto(s, "p")
    anuncio = criar_anuncio(s, "B0VISTO001")
    par, criado = repo_casamento.registrar_visto(s, anuncio.id, p.id, T0)
    assert criado and (par.status, par.origem, par.visto_primeiro_em, par.visto_ultimo_em) == (PENDENTE, None, T0, T0)
    repo_casamento.ignorar(s, anuncio.id, p.id, T0)
    depois = T0 + timedelta(days=1)
    par, criado = repo_casamento.registrar_visto(s, anuncio.id, p.id, depois)
    assert not criado and (par.status, par.visto_primeiro_em, par.visto_ultimo_em) == (IGNORADO, T0, depois)


def test_ignorado_para_a_vira_pendente_para_b(s):
    a, b = criar_produto(s, "a"), criar_produto(s, "b")
    anuncio = criar_anuncio(s, "B0IGNA0001", produto=a, status=IGNORADO, origem=MANUAL)
    par, criado = repo_casamento.registrar_visto(s, anuncio.id, b.id, T0)
    assert criado and par.status is PENDENTE
    assert situacao(s, anuncio, a) == (IGNORADO, MANUAL)


def test_anuncio_confirmado_para_q_entra_como_outro_confirmado_para_p(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    anuncio = criar_anuncio(s, "B0CONFQ001", produto=q, status=CONFIRMADO, origem=MANUAL)
    par, criado = repo_casamento.registrar_visto(s, anuncio.id, p.id, T0)
    assert criado and (par.status, par.origem, par.revisado_em) == (IGNORADO, OUTRO, T0)


def test_confirmar_ignora_os_outros_pendentes_e_fecha_oportunidades_dos_outros(s):
    p, q, r = criar_produto(s, "p"), criar_produto(s, "q"), criar_produto(s, "r")
    anuncio = criar_anuncio(s, "B0CONF0001", produto=p)
    criar_par(s, anuncio, q)
    criar_par(s, anuncio, r, status=IGNORADO, origem=MANUAL, revisado_em=T0)
    op_q = abrir_op(s, anuncio, q)
    par = repo_casamento.confirmar(s, anuncio.id, p.id, T0, OrigemCasamento.SUGERIDO_IA)
    assert (par.status, par.origem, par.revisado_em, par.reavaliar) == (CONFIRMADO, OrigemCasamento.SUGERIDO_IA, T0, False)
    assert situacao(s, anuncio, q) == (IGNORADO, OUTRO)
    assert situacao(s, anuncio, r) == (IGNORADO, MANUAL)  # decisão sua não muda
    s.refresh(op_q)
    assert op_q.fechada_em == T0


def test_confirmar_cria_o_par_que_nao_existe(s):
    p = criar_produto(s, "p")
    anuncio = criar_anuncio(s, "B0NOVO0001")
    par = repo_casamento.confirmar(s, anuncio.id, p.id, T0)
    assert (par.status, par.origem, par.visto_primeiro_em, par.visto_ultimo_em) == (CONFIRMADO, MANUAL, T0, T0)


def test_confirmar_anuncio_ja_confirmado_em_outro_produto_nao_muda_nada(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    anuncio = criar_anuncio(s, "B0JACONF01", produto=q, status=CONFIRMADO, origem=MANUAL)
    criar_par(s, anuncio, p)
    with pytest.raises(repo_casamento.JaConfirmado) as erro:
        repo_casamento.confirmar(s, anuncio.id, p.id, T0)
    assert erro.value.produto_id == q.id and str(erro.value) == "já confirmado para outro produto"
    assert situacao(s, anuncio, p) == (PENDENTE, None)
    assert situacao(s, anuncio, q) == (CONFIRMADO, MANUAL)
    assert repo_casamento.confirmar(s, anuncio.id, q.id, T0).produto_id == q.id  # o mesmo par: nada a fazer


def test_indice_unico_recusa_dois_confirmados_no_mesmo_anuncio(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    anuncio = criar_anuncio(s, "B0INDICE01", produto=p, status=CONFIRMADO)
    with pytest.raises(IntegrityError), s.begin_nested():
        criar_par(s, anuncio, q, status=CONFIRMADO)


def test_confirmacoes_concorrentes_so_uma_vale(engine):
    """Duas transações confirmam o mesmo anúncio para produtos diferentes ao mesmo tempo: uma vale, a
    outra recebe JaConfirmado. Grava de verdade (fora do `sessoes`) e apaga no fim."""
    fabrica = sessionmaker(bind=engine, expire_on_commit=False)
    with fabrica() as s, s.begin():
        p, q = criar_produto(s, "conc-p", nome="Conc P"), criar_produto(s, "conc-q", nome="Conc Q")
        anuncio_id, produtos = criar_anuncio(s, "B0CONC0001").id, (p.id, q.id)
    barreira = threading.Barrier(2)
    resultados: dict[int, str] = {}

    def confirmar(produto_id: int) -> None:
        with fabrica() as s, s.begin():
            barreira.wait(timeout=10)
            try:
                repo_casamento.confirmar(s, anuncio_id, produto_id, T0)
                resultados[produto_id] = "ok"
            except repo_casamento.JaConfirmado:
                resultados[produto_id] = "já"

    try:
        linhas = [threading.Thread(target=confirmar, args=(produto_id,)) for produto_id in produtos]
        for linha in linhas:
            linha.start()
        for linha in linhas:
            linha.join(timeout=30)
        assert sorted(resultados.values()) == ["já", "ok"]
        with fabrica() as s:
            confirmados = s.scalars(
                select(Casamento).where(Casamento.anuncio_id == anuncio_id, Casamento.status == CONFIRMADO)
            ).all()
        assert len(confirmados) == 1
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM casamento WHERE anuncio_id = :a"), {"a": anuncio_id})
            c.execute(text("DELETE FROM anuncio_amazon WHERE id = :a"), {"a": anuncio_id})
            c.execute(text("DELETE FROM produto_liga WHERE liga_id IN ('conc-p', 'conc-q')"))


def test_desfazer_confirmado_volta_a_pendente_reabre_outros_e_pede_reavaliacao(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    anuncio = criar_anuncio(s, "B0DESF0001", produto=p)
    criar_par(s, anuncio, q)
    av = avaliacao(s, anuncio, p)
    repo_casamento.confirmar(s, anuncio.id, p.id, T0, OrigemCasamento.AUTOMATICO_IA)
    av.aplicada_em = T0
    op = abrir_op(s, anuncio, p)
    depois = T0 + timedelta(hours=1)
    par = repo_casamento.desfazer(s, anuncio.id, p.id, depois)
    assert (par.status, par.origem, par.revisado_em, par.reavaliar) == (PENDENTE, None, None, True)
    assert situacao(s, anuncio, q) == (PENDENTE, None)
    s.refresh(av)
    s.refresh(op)
    assert av.aplicada_em is None and op.fechada_em == depois
    assert repo_casamento.desfazer(s, anuncio.id, criar_produto(s, "sem-par").id, T0) is None


def test_desfazer_par_outro_confirmado_com_o_anuncio_ainda_confirmado_e_recusado(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    anuncio = criar_anuncio(s, "B0DESF0002", produto=q, status=CONFIRMADO, origem=MANUAL)
    criar_par(s, anuncio, p, status=IGNORADO, origem=OUTRO, revisado_em=T0)
    with pytest.raises(repo_casamento.JaConfirmado):
        repo_casamento.desfazer(s, anuncio.id, p.id, T0)
    assert situacao(s, anuncio, p) == (IGNORADO, OUTRO)


def test_ignorar_o_confirmado_reabre_os_outro_confirmado(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    anuncio = criar_anuncio(s, "B0IGNC0001", produto=p)
    criar_par(s, anuncio, q)
    repo_casamento.confirmar(s, anuncio.id, p.id, T0)
    assert situacao(s, anuncio, q) == (IGNORADO, OUTRO)
    par = repo_casamento.ignorar(s, anuncio.id, p.id, T0, MANUAL)
    assert (par.status, par.origem, par.revisado_em, par.reavaliar) == (IGNORADO, MANUAL, T0, False)
    assert situacao(s, anuncio, q) == (PENDENTE, None)
    assert repo_casamento.ignorar(s, anuncio.id, criar_produto(s, "sem-par").id, T0) is None


def test_trocar_ignora_o_confirmado_anterior_como_manual_e_confirma_o_novo(s):
    p, q, r = criar_produto(s, "p"), criar_produto(s, "q"), criar_produto(s, "r")
    anuncio = criar_anuncio(s, "B0TROC0001", produto=p)
    criar_par(s, anuncio, r)
    repo_casamento.confirmar(s, anuncio.id, p.id, T0, OrigemCasamento.AUTOMATICO_IA)
    op = abrir_op(s, anuncio, p)
    depois = T0 + timedelta(hours=1)
    par = repo_casamento.trocar(s, anuncio.id, q.id, depois, OrigemCasamento.SUGERIDO_IA)
    assert (par.status, par.origem, par.revisado_em) == (CONFIRMADO, OrigemCasamento.SUGERIDO_IA, depois)
    assert situacao(s, anuncio, p) == (IGNORADO, MANUAL)
    assert situacao(s, anuncio, r) == (IGNORADO, OUTRO)
    s.refresh(op)
    assert op.fechada_em == depois


def test_casar_asin_cria_o_anuncio_ou_troca_o_confirmado(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    novo = repo_casamento.casar_asin(s, p.id, "B0ASIN0001", T0, "Provisório")
    assert (novo.titulo, novo.url, novo.visto_primeiro_em) == ("Provisório", "https://www.amazon.com.br/dp/B0ASIN0001", T0)
    assert situacao(s, novo, p) == (CONFIRMADO, MANUAL)
    depois = T0 + timedelta(hours=1)
    mesmo = repo_casamento.casar_asin(s, q.id, "B0ASIN0001", depois, "Provisório")
    assert mesmo.id == novo.id and mesmo.visto_ultimo_em == depois
    assert situacao(s, novo, p) == (IGNORADO, MANUAL)
    assert situacao(s, novo, q) == (CONFIRMADO, MANUAL)


def test_reavaliar_produto_so_mexe_nos_pares_dele_e_nao_nas_decisoes_manuais(s):
    p, q, outro = criar_produto(s, "p"), criar_produto(s, "q"), criar_produto(s, "outro")
    pend = criar_anuncio(s, "B0REAV0001", produto=p)
    pela_ia = criar_anuncio(s, "B0REAV0002", produto=p, status=IGNORADO, origem=OrigemCasamento.AUTOMATICO_IA)
    sugerido = criar_anuncio(s, "B0REAV0003", produto=p, status=IGNORADO, origem=OrigemCasamento.SUGERIDO_IA)
    manual = criar_anuncio(s, "B0REAV0004", produto=p, status=IGNORADO, origem=MANUAL)
    confirmado = criar_anuncio(s, "B0REAV0005", produto=p, status=CONFIRMADO, origem=OrigemCasamento.AUTOMATICO_IA)
    casado_em_q = criar_anuncio(s, "B0REAV0006", produto=q, status=CONFIRMADO, origem=MANUAL)
    criar_par(s, casado_em_q, p, status=IGNORADO, origem=OUTRO, revisado_em=T0)
    sobra = criar_anuncio(s, "B0REAV0007", produto=p, status=IGNORADO, origem=OUTRO)  # sem confirmado em lugar nenhum
    de_outro = criar_anuncio(s, "B0REAV0008", produto=outro, status=IGNORADO, origem=OrigemCasamento.AUTOMATICO_IA)
    av = avaliacao(s, pela_ia, p)
    av.aplicada_em = T0
    s.flush()
    assert repo_casamento.reavaliar_produto(s, p.id, T0) == 4
    for anuncio in (pend, pela_ia, sugerido, sobra):
        par = repo_casamento.obter_par(s, anuncio.id, p.id)
        assert (par.status, par.origem, par.revisado_em, par.reavaliar) == (PENDENTE, None, None, True)
    assert situacao(s, manual, p) == (IGNORADO, MANUAL)
    assert situacao(s, confirmado, p) == (CONFIRMADO, OrigemCasamento.AUTOMATICO_IA)
    assert situacao(s, casado_em_q, p) == (IGNORADO, OUTRO)
    assert situacao(s, de_outro, outro) == (IGNORADO, OrigemCasamento.AUTOMATICO_IA)
    s.refresh(av)
    assert av.aplicada_em is None


def test_marcar_reavaliado(s):
    p = criar_produto(s, "p")
    anuncio = criar_anuncio(s, "B0MARC0001", produto=p, status=IGNORADO, origem=OrigemCasamento.AUTOMATICO_IA)
    repo_casamento.reavaliar_produto(s, p.id, T0)
    repo_casamento.marcar_reavaliado(s, anuncio.id, p.id)
    assert repo_casamento.obter_par(s, anuncio.id, p.id).reavaliar is False


def test_condicao_confirmado_e_produtos_casados(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    anuncio = criar_anuncio(s, "B0COND0001", produto=p, status=CONFIRMADO)
    criar_par(s, anuncio, q, status=IGNORADO, origem=OUTRO, revisado_em=T0)
    assert set(s.scalars(repo_casamento.produtos_casados())) == {p.id}
    par = s.scalar(select(Casamento).where(repo_casamento.condicao_confirmado(anuncio.id)))
    assert par.produto_id == p.id
```

- [ ] **Step 3: Escrever os testes dos termos (falham)**

Crie `tests/db/test_repositorio_termos.py`:

```python
from datetime import timedelta

import pytest
from fakes import T0, criar_anuncio, criar_produto

from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_termos as repo_termos
from tcg_sniper.db.models import FilaAmazon, StatusCasamento

DIA = timedelta(days=1)


def test_seca_conta_7_dias_desde_a_entrada_ou_o_ultimo_par_novo(s):
    p = criar_produto(s, "p")
    repo_amz.sincronizar_fila(s, T0)
    assert not repo_termos.em_seca(s, p.id, T0 + 7 * DIA - timedelta(seconds=1))
    assert repo_termos.em_seca(s, p.id, T0 + 7 * DIA)
    s.get(FilaAmazon, p.id).ultimo_par_novo_em = T0 + 3 * DIA
    s.flush()
    assert not repo_termos.em_seca(s, p.id, T0 + 7 * DIA)
    assert repo_termos.em_seca(s, p.id, T0 + 10 * DIA)


def test_produto_casado_ou_fora_da_fila_nunca_esta_em_seca(s):
    casado, fora = criar_produto(s, "casado"), criar_produto(s, "fora", ativo=False)
    repo_amz.sincronizar_fila(s, T0)
    criar_anuncio(s, "B0SECA0001", produto=casado, status=StatusCasamento.CONFIRMADO)
    assert not repo_termos.em_seca(s, casado.id, T0 + 30 * DIA)
    assert not repo_termos.em_seca(s, fora.id, T0 + 30 * DIA)


def test_guardar_termos_substitui_marca_a_tentativa_e_limpa_o_pedido(s):
    p = criar_produto(s, "p")
    repo_amz.sincronizar_fila(s, T0)
    assert repo_termos.pedir_termos(s, p.id, T0) is True
    repo_termos.guardar_termos(s, p.id, [("caixa alfa", "pt"), ("alpha box", "en")], T0)
    repo_termos.guardar_termos(s, p.id, [("alpha booster box", "en")], T0 + DIA)
    assert [(t.termo, t.idioma, t.ordem) for t in repo_termos.termos_do_produto(s, p.id)] == [("alpha booster box", "en", 1)]
    fila = s.get(FilaAmazon, p.id)
    assert (fila.termos_tentados_em, fila.termos_pedidos_em) == (T0 + DIA, None)
    with pytest.raises(ValueError):
        repo_termos.guardar_termos(s, p.id, [("a", "pt"), ("b", "pt"), ("c", "pt"), ("d", "pt")], T0)
    with pytest.raises(ValueError):
        repo_termos.guardar_termos(s, p.id, [], T0)


def test_pedir_termos_sem_linha_na_fila_devolve_falso(s):
    p = criar_produto(s, "p")
    assert repo_termos.pedir_termos(s, p.id, T0) is False


def test_produtos_para_gerar_termos(s):
    pedido = criar_produto(s, "pedido")
    seco = criar_produto(s, "seco")
    seco_com_termos = criar_produto(s, "seco-com-termos")
    tentado = criar_produto(s, "tentado")
    recente = criar_produto(s, "recente")
    repo_amz.sincronizar_fila(s, T0)
    s.get(FilaAmazon, recente.id).entrou_em = T0 + 5 * DIA
    repo_termos.guardar_termos(s, seco_com_termos.id, [("x y", "pt")], T0)
    repo_termos.guardar_termos(s, pedido.id, [("antigo", "pt")], T0)  # o pedido regenera mesmo com termos
    repo_termos.pedir_termos(s, pedido.id, T0 + 8 * DIA)
    repo_termos.marcar_tentativa(s, tentado.id, T0 + 6 * DIA)
    agora = T0 + 8 * DIA
    assert [p.id for p in repo_termos.produtos_para_gerar_termos(s, agora, 10)] == [pedido.id, seco.id]
    assert [p.id for p in repo_termos.produtos_para_gerar_termos(s, agora, 1)] == [pedido.id]
    assert tentado.id in [p.id for p in repo_termos.produtos_para_gerar_termos(s, T0 + 13 * DIA, 10)]
```

- [ ] **Step 4: Escrever os testes da migração (falham)**

Crie `tests/db/test_migracao_casamento.py`:

```python
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, pool, text

import tcg_sniper.db
from tcg_sniper.db.session import config_alembic

ANTES = "f8d2a6c4e1b3"
ARQUIVO = Path(tcg_sniper.db.__file__).parent / "migrations" / "versions" / "a9d4f2c6e8b1_casamento_por_par.py"
T = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
DIA = timedelta(days=1)


def modulo_da_migracao():
    spec = importlib.util.spec_from_file_location("migracao_casamento_por_par", ARQUIVO)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def banco(engine):
    """Fora da transação do `sessoes`: os testes descem e sobem a migração. Sempre deixa o banco em head."""
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    yield cfg, proprio
    command.upgrade(cfg, "head")
    with proprio.begin() as c:
        c.execute(text("DELETE FROM casamento WHERE anuncio_id IN (SELECT id FROM anuncio_amazon WHERE asin LIKE 'BPAR%')"))
        c.execute(text("DELETE FROM anuncio_amazon WHERE asin LIKE 'BPAR%'"))
        c.execute(text("DELETE FROM fila_amazon WHERE produto_id IN (SELECT id FROM produto_liga WHERE liga_id LIKE 'par-%')"))
        c.execute(text("DELETE FROM produto_liga WHERE liga_id LIKE 'par-%'"))
    proprio.dispose()


def _produto(c, liga_id):
    return c.scalar(
        text(
            "INSERT INTO produto_liga (liga_id, nome, url, ativo, visto_primeiro_em, visto_ultimo_em) "
            "VALUES (:l, :l, 'u', true, :t, :t) RETURNING id"
        ),
        {"l": liga_id, "t": T},
    )


def _anuncio_antigo(c, asin, produto_id, status, origem, revisado, primeiro, ultimo):
    """Anúncio no formato de antes (casamento nas colunas do anúncio)."""
    return c.scalar(
        text(
            "INSERT INTO anuncio_amazon (asin, titulo, url, produto_id, status_casamento, origem_casamento, "
            "revisado_em, visto_primeiro_em, visto_ultimo_em) VALUES (:a, 't', 'u', :p, :st, :o, :r, :vp, :vu) RETURNING id"
        ),
        {"a": asin, "p": produto_id, "st": status, "o": origem, "r": revisado, "vp": primeiro, "vu": ultimo},
    )


def test_migracao_copia_um_par_por_anuncio_e_prepara_a_fila(banco):
    cfg, proprio = banco
    command.downgrade(cfg, ANTES)
    with proprio.begin() as c:
        p1, p2 = _produto(c, "par-1"), _produto(c, "par-2")
        conf = _anuncio_antigo(c, "BPAR000001", p1, "confirmado", "automatico_ia", T, T - 10 * DIA, T)
        ign = _anuncio_antigo(c, "BPAR000002", p1, "ignorado", "manual", T, T - 5 * DIA, T - DIA)
        pend = _anuncio_antigo(c, "BPAR000003", p2, "pendente", None, None, T - 2 * DIA, T)
        sem = _anuncio_antigo(c, "BPAR000004", None, "pendente", None, None, T, T)
        c.execute(
            text(
                "INSERT INTO fila_amazon (produto_id, entrou_em, proxima_busca_em, ultima_busca_em, ultimo_termo_en) "
                "VALUES (:p1, :t, :t, :t, false), (:p2, :t, :t, NULL, false)"
            ),
            {"p1": p1, "p2": p2, "t": T},
        )
    command.upgrade(cfg, "head")
    with proprio.connect() as c:
        pares = {
            tuple(linha)
            for linha in c.execute(
                text(
                    "SELECT anuncio_id, produto_id, status, origem, revisado_em, visto_primeiro_em, visto_ultimo_em, "
                    "reavaliar FROM casamento WHERE anuncio_id IN (:a, :b, :c, :d)"
                ),
                {"a": conf, "b": ign, "c": pend, "d": sem},
            )
        }
        fila = {
            linha.produto_id: (linha.indice_termo, linha.ultimo_par_novo_em, linha.termos_tentados_em)
            for linha in c.execute(
                text("SELECT * FROM fila_amazon WHERE produto_id IN (:p1, :p2)"), {"p1": p1, "p2": p2}
            )
        }
    assert pares == {
        (conf, p1, "confirmado", "automatico_ia", T, T - 10 * DIA, T, False),
        (ign, p1, "ignorado", "manual", T, T - 5 * DIA, T - DIA, False),
        (pend, p2, "pendente", None, None, T - 2 * DIA, T, False),
    }
    # p1: última busca em português, há busca anterior -> o próximo é o inglês (1); p2 nunca buscado -> 0
    assert fila == {p1: (1, T - 5 * DIA, None), p2: (0, T - 2 * DIA, None)}


def test_downgrade_refaz_as_colunas_pelo_confirmado_ou_pelo_par_mais_antigo(banco):
    cfg, proprio = banco
    command.downgrade(cfg, ANTES)
    with proprio.begin() as c:
        p1, p2, p3 = _produto(c, "par-1"), _produto(c, "par-2"), _produto(c, "par-3")
        a = _anuncio_antigo(c, "BPAR000011", p1, "pendente", None, None, T, T)
        b = _anuncio_antigo(c, "BPAR000012", p1, "pendente", None, None, T, T)
    command.upgrade(cfg, "head")
    with proprio.begin() as c:
        # a: confirmado para p2 (par mais novo) e outro_confirmado para p1 -> vale o confirmado
        c.execute(
            text(
                "INSERT INTO casamento (anuncio_id, produto_id, status, origem, revisado_em, visto_primeiro_em, "
                "visto_ultimo_em) VALUES (:a, :p, 'confirmado', 'manual', :t, :t2, :t2)"
            ),
            {"a": a, "p": p2, "t": T, "t2": T + DIA},
        )
        c.execute(
            text("UPDATE casamento SET status = 'ignorado', origem = 'outro_confirmado', revisado_em = :t "
                 "WHERE anuncio_id = :a AND produto_id = :p"),
            {"a": a, "p": p1, "t": T},
        )
        # b: ignorado para p1 e pendente para p3 visto antes -> vale o mais antigo (p3)
        c.execute(
            text(
                "INSERT INTO casamento (anuncio_id, produto_id, status, visto_primeiro_em, visto_ultimo_em) "
                "VALUES (:b, :p, 'pendente', :t, :t)"
            ),
            {"b": b, "p": p3, "t": T - DIA},
        )
        c.execute(
            text("UPDATE casamento SET status = 'ignorado', origem = 'sugerido_ia', revisado_em = :t "
                 "WHERE anuncio_id = :b AND produto_id = :p"),
            {"b": b, "p": p1, "t": T},
        )
    command.downgrade(cfg, ANTES)
    with proprio.connect() as c:
        linhas = {
            linha.asin: (linha.produto_id, linha.status_casamento, linha.origem_casamento)
            for linha in c.execute(
                text("SELECT asin, produto_id, status_casamento, origem_casamento FROM anuncio_amazon WHERE asin LIKE 'BPAR%'")
            )
        }
    assert linhas == {"BPAR000011": (p2, "confirmado", "manual"), "BPAR000012": (p3, "pendente", None)}


def test_migracao_aborta_com_dois_confirmados_no_mesmo_anuncio(engine):
    modulo = modulo_da_migracao()
    with engine.connect() as c:
        transacao = c.begin()
        try:
            p1, p2 = _produto(c, "par-dup-1"), _produto(c, "par-dup-2")
            anuncio = c.scalar(
                text(
                    "INSERT INTO anuncio_amazon (asin, titulo, url, visto_primeiro_em, visto_ultimo_em) "
                    "VALUES ('BPARDUP001', 't', 'u', :t, :t) RETURNING id"
                ),
                {"t": T},
            )
            c.execute(text("DROP INDEX uq_casamento_confirmado"))
            c.execute(
                text(
                    "INSERT INTO casamento (anuncio_id, produto_id, status, origem, revisado_em, visto_primeiro_em, "
                    "visto_ultimo_em) VALUES (:a, :p1, 'confirmado', 'manual', :t, :t, :t), "
                    "(:a, :p2, 'confirmado', 'manual', :t, :t, :t)"
                ),
                {"a": anuncio, "p1": p1, "p2": p2, "t": T},
            )
            with pytest.raises(RuntimeError, match="mais de um casamento confirmado"):
                modulo.conferir_um_confirmado_por_anuncio(c)
        finally:
            transacao.rollback()  # o DROP INDEX também volta
```

- [ ] **Step 5: Rodar para ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t1 uv run pytest -q -p no:cacheprovider tests/db/test_repositorio_casamento.py tests/db/test_repositorio_termos.py tests/db/test_migracao_casamento.py`
Expected: FAIL (`ImportError: cannot import name 'criar_par'` / `No module named 'tcg_sniper.db.repositorio_casamento'`).

- [ ] **Step 6: Modelos**

Em `src/tcg_sniper/db/models.py`:

1. Em `OrigemCasamento`, depois de `AUTOMATICO_IA`:

```python
    OUTRO_CONFIRMADO = "outro_confirmado"  # o anúncio foi confirmado para outro produto (decisão do sistema)
```

2. Em `AnuncioAmazon`, troque a docstring e as quatro colunas do casamento por:

```python
class AnuncioAmazon(Base):
    """Um anúncio (ASIN) da amazon.com.br. O casamento com os produtos da Liga fica em `Casamento` (por par).

    `produto_id`, `status_casamento`, `revisado_em` e `origem_casamento` são as colunas antigas do
    casamento: nenhum código novo as lê; saem na Task 7 do plano de casamento por par."""

    __tablename__ = "anuncio_amazon"

    id: Mapped[int] = mapped_column(primary_key=True)
    asin: Mapped[str] = mapped_column(Text, unique=True)
    titulo: Mapped[str] = mapped_column(Text)
    # Opção do seletor de variações lida na página do produto ("Collector Booster Box"); a busca não a mostra.
    variacao: Mapped[str | None] = mapped_column(Text)
    # Imagem principal: a busca só preenche quando vazia; a página do produto pode trocar.
    imagem_url: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    produto_id: Mapped[int | None] = mapped_column(ForeignKey("produto_liga.id"))
    status_casamento: Mapped[StatusCasamento | None] = mapped_column(_enum(StatusCasamento, "status_casamento"))
    revisado_em: Mapped[datetime | None] = mapped_column(DATA)
    origem_casamento: Mapped[OrigemCasamento | None] = mapped_column(_enum(OrigemCasamento, "origem_casamento"))
    visto_primeiro_em: Mapped[datetime] = mapped_column(DATA)
    visto_ultimo_em: Mapped[datetime] = mapped_column(DATA)
```

(mantenha a property `titulo_exibicao` como está).

3. Troque `FilaAmazon` por:

```python
class FilaAmazon(Base):
    """Uma linha por produto ativo da Liga: quando buscar de novo na Amazon e com que termo."""

    __tablename__ = "fila_amazon"
    __table_args__ = (CheckConstraint("indice_termo >= 0", name="ck_fila_amazon_indice_termo"),)

    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"), primary_key=True)
    entrou_em: Mapped[datetime] = mapped_column(DATA)
    proxima_busca_em: Mapped[datetime] = mapped_column(DATA)
    ultima_busca_em: Mapped[datetime | None] = mapped_column(DATA)
    ultimo_candidato_em: Mapped[datetime | None] = mapped_column(DATA)
    # Coluna antiga (sai na Task 7): o termo agora é `indice_termo`.
    ultimo_termo_en: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Próximo termo da sequência (nome, nome em inglês, termos alternativos na seca), usado módulo o tamanho.
    indice_termo: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Última vez que a busca deste produto criou um par pendente novo (a seca conta daqui; nulo: desde entrou_em).
    ultimo_par_novo_em: Mapped[datetime | None] = mapped_column(DATA)
    # Última tentativa da IA de gerar termos (sem termo válido: espera 7 dias) e pedido do admin.
    termos_tentados_em: Mapped[datetime | None] = mapped_column(DATA)
    termos_pedidos_em: Mapped[datetime | None] = mapped_column(DATA)


class Casamento(Base):
    """Par (anúncio da Amazon, produto da Liga): a fonte única do casamento. Um anúncio pode estar pendente
    ou ignorado para vários produtos e confirmado para no máximo um (índice único parcial). `visto_*`: quando
    a busca deste produto viu o anúncio (par criado por link, troca ou migração: a criação). `reavaliar`:
    Desfazer ou "Reavaliar com a IA" pediram nova avaliação mesmo com os dados iguais."""

    __tablename__ = "casamento"
    __table_args__ = (
        Index("uq_casamento_confirmado", "anuncio_id", unique=True, postgresql_where=text("status = 'confirmado'")),
        Index("ix_casamento_produto_status", "produto_id", "status"),
        Index("ix_casamento_status", "status"),
    )

    anuncio_id: Mapped[int] = mapped_column(ForeignKey("anuncio_amazon.id"), primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"), primary_key=True)
    status: Mapped[StatusCasamento] = mapped_column(_enum(StatusCasamento, "status_casamento"))
    origem: Mapped[OrigemCasamento | None] = mapped_column(_enum(OrigemCasamento, "origem_casamento"))
    revisado_em: Mapped[datetime | None] = mapped_column(DATA)
    visto_primeiro_em: Mapped[datetime] = mapped_column(DATA)
    visto_ultimo_em: Mapped[datetime] = mapped_column(DATA)
    reavaliar: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class TermoBusca(Base):
    """Termos de busca alternativos de um produto (busca alternativa): gerados pela IA, no máximo 3."""

    __tablename__ = "termo_busca"
    __table_args__ = (
        UniqueConstraint("produto_id", "termo", name="uq_termo_busca_produto_termo"),
        UniqueConstraint("produto_id", "ordem", name="uq_termo_busca_produto_ordem"),
        CheckConstraint("char_length(termo) BETWEEN 1 AND 80", name="ck_termo_busca_termo"),
        CheckConstraint("idioma IN ('pt', 'en')", name="ck_termo_busca_idioma"),
        CheckConstraint("ordem BETWEEN 1 AND 3", name="ck_termo_busca_ordem"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"))
    termo: Mapped[str] = mapped_column(Text)
    idioma: Mapped[str] = mapped_column(Text)
    ordem: Mapped[int] = mapped_column(Integer)
    criado_em: Mapped[datetime] = mapped_column(DATA)
```

- [ ] **Step 7: Migração**

Crie `src/tcg_sniper/db/migrations/versions/a9d4f2c6e8b1_casamento_por_par.py`:

```python
"""casamento por par: tabela casamento (fonte única), termo_busca e colunas da busca alternativa na fila

Revision ID: a9d4f2c6e8b1
Revises: f8d2a6c4e1b3
Create Date: 2026-10-19 12:00:00

Tudo numa transação (o env.py roda as migrações numa só): cria `casamento`, copia um par por anúncio com
produto, confere que nenhum anúncio ficou com dois confirmados (senão aborta sem mudar nada) e cria o
índice único parcial. As colunas antigas de `anuncio_amazon` saem na Task 7 do plano (nesta mesma revisão).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9d4f2c6e8b1"
down_revision: Union[str, Sequence[str], None] = "f8d2a6c4e1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DATA = sa.DateTime(timezone=True)
STATUS = ("pendente", "confirmado", "ignorado")
ORIGENS = ("manual", "sugerido_ia", "automatico_ia", "outro_confirmado")

COPIAR_PARES = """
INSERT INTO casamento (anuncio_id, produto_id, status, origem, revisado_em, visto_primeiro_em, visto_ultimo_em, reavaliar)
SELECT id, produto_id, status_casamento, origem_casamento, revisado_em, visto_primeiro_em, visto_ultimo_em, false
FROM anuncio_amazon
WHERE produto_id IS NOT NULL
"""

# Downgrade: por anúncio, o par confirmado ou, sem confirmado, o mais antigo; outro_confirmado não existia.
REFAZER_ANUNCIO = """
UPDATE anuncio_amazon a
SET produto_id = p.produto_id,
    status_casamento = p.status,
    origem_casamento = CASE WHEN p.origem = 'outro_confirmado' THEN 'manual' ELSE p.origem END,
    revisado_em = p.revisado_em
FROM (
    SELECT DISTINCT ON (anuncio_id) anuncio_id, produto_id, status, origem, revisado_em
    FROM casamento
    ORDER BY anuncio_id, (status = 'confirmado') DESC, visto_primeiro_em, produto_id
) p
WHERE p.anuncio_id = a.id
"""


def _enum(nome: str, *valores: str) -> sa.Enum:
    return sa.Enum(*valores, name=nome, native_enum=False, create_constraint=True, length=20)


def conferir_um_confirmado_por_anuncio(bind) -> None:
    """Aborta (a transação inteira volta) se algum anúncio ficou com mais de um par confirmado."""
    repetidos = bind.execute(
        sa.text(
            "SELECT anuncio_id FROM casamento WHERE status = 'confirmado' "
            "GROUP BY anuncio_id HAVING count(*) > 1 ORDER BY anuncio_id LIMIT 20"
        )
    ).scalars().all()
    if repetidos:
        raise RuntimeError(
            "migração casamento por par abortada: anúncios com mais de um casamento confirmado "
            f"(ids {', '.join(map(str, repetidos))}); nada foi mudado"
        )


def upgrade() -> None:
    op.create_table(
        "casamento",
        sa.Column("anuncio_id", sa.Integer(), nullable=False),
        sa.Column("produto_id", sa.Integer(), nullable=False),
        sa.Column("status", _enum("status_casamento", *STATUS), nullable=False),
        sa.Column("origem", _enum("origem_casamento", *ORIGENS), nullable=True),
        sa.Column("revisado_em", DATA, nullable=True),
        sa.Column("visto_primeiro_em", DATA, nullable=False),
        sa.Column("visto_ultimo_em", DATA, nullable=False),
        sa.Column("reavaliar", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["anuncio_id"], ["anuncio_amazon.id"]),
        sa.ForeignKeyConstraint(["produto_id"], ["produto_liga.id"]),
        sa.PrimaryKeyConstraint("anuncio_id", "produto_id"),
    )
    op.create_index("ix_casamento_produto_status", "casamento", ["produto_id", "status"])
    op.create_index("ix_casamento_status", "casamento", ["status"])
    op.execute(COPIAR_PARES)
    conferir_um_confirmado_por_anuncio(op.get_bind())
    op.create_index(
        "uq_casamento_confirmado", "casamento", ["anuncio_id"], unique=True,
        postgresql_where=sa.text("status = 'confirmado'"),
    )
    # Transição: o código novo cria anúncios sem as colunas antigas (saem na Task 7).
    op.alter_column("anuncio_amazon", "status_casamento", existing_type=sa.String(20), nullable=True)

    op.create_table(
        "termo_busca",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("produto_id", sa.Integer(), nullable=False),
        sa.Column("termo", sa.Text(), nullable=False),
        sa.Column("idioma", sa.Text(), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False),
        sa.Column("criado_em", DATA, nullable=False),
        sa.CheckConstraint("char_length(termo) BETWEEN 1 AND 80", name="ck_termo_busca_termo"),
        sa.CheckConstraint("idioma IN ('pt', 'en')", name="ck_termo_busca_idioma"),
        sa.CheckConstraint("ordem BETWEEN 1 AND 3", name="ck_termo_busca_ordem"),
        sa.ForeignKeyConstraint(["produto_id"], ["produto_liga.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("produto_id", "termo", name="uq_termo_busca_produto_termo"),
        sa.UniqueConstraint("produto_id", "ordem", name="uq_termo_busca_produto_ordem"),
    )

    op.add_column("fila_amazon", sa.Column("indice_termo", sa.Integer(), server_default="0", nullable=False))
    op.create_check_constraint("ck_fila_amazon_indice_termo", "fila_amazon", "indice_termo >= 0")
    op.add_column("fila_amazon", sa.Column("ultimo_par_novo_em", DATA, nullable=True))
    op.add_column("fila_amazon", sa.Column("termos_tentados_em", DATA, nullable=True))
    op.add_column("fila_amazon", sa.Column("termos_pedidos_em", DATA, nullable=True))
    # Mesmo próximo termo de hoje: depois de uma busca em português vem o inglês.
    op.execute(
        "UPDATE fila_amazon SET indice_termo = "
        "CASE WHEN ultima_busca_em IS NOT NULL AND NOT ultimo_termo_en THEN 1 ELSE 0 END"
    )
    op.execute(
        "UPDATE fila_amazon f SET ultimo_par_novo_em = "
        "(SELECT max(c.visto_primeiro_em) FROM casamento c WHERE c.produto_id = f.produto_id)"
    )


def downgrade() -> None:
    op.execute("UPDATE fila_amazon SET ultimo_termo_en = (ultima_busca_em IS NOT NULL AND indice_termo = 0)")
    op.drop_constraint("ck_fila_amazon_indice_termo", "fila_amazon", type_="check")
    for coluna in ("termos_pedidos_em", "termos_tentados_em", "ultimo_par_novo_em", "indice_termo"):
        op.drop_column("fila_amazon", coluna)
    op.drop_table("termo_busca")
    op.execute(REFAZER_ANUNCIO)
    op.execute("UPDATE anuncio_amazon SET status_casamento = 'pendente' WHERE status_casamento IS NULL")
    op.alter_column("anuncio_amazon", "status_casamento", existing_type=sa.String(20), nullable=False)
    op.drop_table("casamento")
```

- [ ] **Step 8: Repositório de pares**

Crie `src/tcg_sniper/db/repositorio_casamento.py`:

```python
"""Casamento por par (anúncio da Amazon × produto da Liga): a única porta de escrita dos pares.

Regras (spec 2026-10-19-casamento-por-par-design.md):
- ignorado vale só para o par: o mesmo anúncio pode estar pendente ou ignorado para vários produtos;
- confirmado para no máximo um produto (índice único parcial `uq_casamento_confirmado`);
- confirmar um par ignora os outros pendentes do anúncio (origem `outro_confirmado`);
- tirar a confirmação (desfazer ou ignorar o confirmado) reabre esses `outro_confirmado`;
- desfazer e "Reavaliar com a IA" marcam o par para a IA reavaliar mesmo com os dados iguais.

Toda escrita trava antes a linha do anúncio (confirmações do mesmo anúncio viram fila). Este módulo só
depende dos modelos: o repositorio_amazon importa este, nunca o contrário."""

from datetime import datetime

from sqlalchemy import ColumnElement, Select, and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tcg_sniper.db.models import AnuncioAmazon, AvaliacaoIA, Casamento, Oportunidade, OrigemCasamento, StatusCasamento

PENDENTE, CONFIRMADO, IGNORADO = StatusCasamento.PENDENTE, StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO
# Ignorados que "Reavaliar com a IA" devolve a pendente (decisões `manual` e confirmados não mudam).
ORIGENS_REAVALIAVEIS = (OrigemCasamento.SUGERIDO_IA, OrigemCasamento.AUTOMATICO_IA, OrigemCasamento.OUTRO_CONFIRMADO)


class JaConfirmado(Exception):
    """O anúncio já está confirmado para outro produto (`produto_id`): nada mudou."""

    def __init__(self, anuncio_id: int, produto_id: int):
        super().__init__("já confirmado para outro produto")
        self.anuncio_id = anuncio_id
        self.produto_id = produto_id


def condicao_confirmado(anuncio_id) -> ColumnElement[bool]:
    """Para `join(Casamento, condicao_confirmado(AnuncioAmazon.id))`: o par confirmado do anúncio."""
    return and_(Casamento.anuncio_id == anuncio_id, Casamento.status == CONFIRMADO)


def produtos_casados() -> Select:
    """Subconsulta: ids dos produtos com algum par confirmado."""
    return select(Casamento.produto_id).where(Casamento.status == CONFIRMADO)


def obter_par(s: Session, anuncio_id: int, produto_id: int, *, travar: bool = False) -> Casamento | None:
    return s.get(
        Casamento, (anuncio_id, produto_id), with_for_update=True if travar else None, populate_existing=True
    )


def confirmado_do_anuncio(s: Session, anuncio_id: int) -> Casamento | None:
    return s.scalar(select(Casamento).where(condicao_confirmado(anuncio_id)).execution_options(populate_existing=True))


def travar_anuncio(s: Session, anuncio_id: int) -> AnuncioAmazon:
    """`SELECT … FOR UPDATE` na linha do anúncio (NoResultFound se não existe)."""
    return s.get_one(AnuncioAmazon, anuncio_id, with_for_update=True)


def fechar_oportunidades(s: Session, anuncio_id: int, agora: datetime, exceto_produto_id: int | None = None) -> int:
    condicoes = [Oportunidade.anuncio_id == anuncio_id, Oportunidade.fechada_em.is_(None)]
    if exceto_produto_id is not None:
        condicoes.append(Oportunidade.produto_id != exceto_produto_id)
    resultado = s.execute(
        update(Oportunidade).where(*condicoes).values(fechada_em=agora).execution_options(synchronize_session="fetch")
    )
    s.flush()
    return resultado.rowcount


def _zerar_aplicada(s: Session, anuncio_id: int, produto_id: int) -> None:
    """A avaliação antiga do par deixa de valer como "já aplicada" (o automático pode decidir de novo)."""
    s.execute(
        update(AvaliacaoIA)
        .where(AvaliacaoIA.anuncio_id == anuncio_id, AvaliacaoIA.produto_id == produto_id)
        .values(aplicada_em=None)
        .execution_options(synchronize_session="fetch")
    )


def _reabrir_outro_confirmado(s: Session, anuncio_id: int) -> None:
    s.execute(
        update(Casamento)
        .where(
            Casamento.anuncio_id == anuncio_id,
            Casamento.status == IGNORADO,
            Casamento.origem == OrigemCasamento.OUTRO_CONFIRMADO,
        )
        .values(status=PENDENTE, origem=None, revisado_em=None)
        .execution_options(synchronize_session="fetch")
    )


def _inserir_par(s: Session, anuncio_id: int, produto_id: int, agora: datetime, **valores) -> bool:
    """Cria o par se não existe. Devolve se criou."""
    stmt = (
        pg_insert(Casamento)
        .values(anuncio_id=anuncio_id, produto_id=produto_id, visto_primeiro_em=agora, visto_ultimo_em=agora, **valores)
        .on_conflict_do_nothing(index_elements=[Casamento.anuncio_id, Casamento.produto_id])
        .returning(Casamento.anuncio_id)
    )
    return s.execute(stmt).first() is not None


def registrar_visto(s: Session, anuncio_id: int, produto_id: int, agora: datetime) -> tuple[Casamento, bool]:
    """A busca do produto viu o anúncio. Par existente: só `visto_ultimo_em` (status não muda). Par novo:
    pendente; se o anúncio já é confirmado de outro produto, ignorado com origem `outro_confirmado`.
    Devolve (par, criado)."""
    par = obter_par(s, anuncio_id, produto_id)
    if par is not None:
        par.visto_ultimo_em = agora
        s.flush()
        return par, False
    if confirmado_do_anuncio(s, anuncio_id) is None:
        valores = {"status": PENDENTE, "origem": None, "revisado_em": None}
    else:
        valores = {"status": IGNORADO, "origem": OrigemCasamento.OUTRO_CONFIRMADO, "revisado_em": agora}
    criado = _inserir_par(s, anuncio_id, produto_id, agora, **valores)
    return obter_par(s, anuncio_id, produto_id), criado


def confirmar(
    s: Session, anuncio_id: int, produto_id: int, agora: datetime, origem: OrigemCasamento = OrigemCasamento.MANUAL
) -> Casamento:
    """Confirma o par (criando-o se não existe), ignora os outros pendentes do anúncio (`outro_confirmado`) e
    fecha as oportunidades abertas do anúncio para outros produtos. Lança JaConfirmado (nada muda) se o
    anúncio já é confirmado de outro produto; o mesmo par já confirmado volta como está."""
    travar_anuncio(s, anuncio_id)
    atual = confirmado_do_anuncio(s, anuncio_id)
    if atual is not None:
        if atual.produto_id == produto_id:
            return atual
        raise JaConfirmado(anuncio_id, atual.produto_id)
    _inserir_par(s, anuncio_id, produto_id, agora, status=PENDENTE, origem=None, revisado_em=None)
    par = obter_par(s, anuncio_id, produto_id)
    try:
        with s.begin_nested():
            par.status, par.origem, par.revisado_em, par.reavaliar = CONFIRMADO, origem, agora, False
            s.flush()
    except IntegrityError:  # outra transação confirmou sem passar pela trava: o índice único segura
        outro = confirmado_do_anuncio(s, anuncio_id)
        raise JaConfirmado(anuncio_id, outro.produto_id if outro is not None else produto_id) from None
    s.execute(
        update(Casamento)
        .where(Casamento.anuncio_id == anuncio_id, Casamento.produto_id != produto_id, Casamento.status == PENDENTE)
        .values(status=IGNORADO, origem=OrigemCasamento.OUTRO_CONFIRMADO, revisado_em=agora, reavaliar=False)
        .execution_options(synchronize_session="fetch")
    )
    fechar_oportunidades(s, anuncio_id, agora, exceto_produto_id=produto_id)
    s.flush()
    return par


def ignorar(
    s: Session, anuncio_id: int, produto_id: int, agora: datetime, origem: OrigemCasamento = OrigemCasamento.MANUAL
) -> Casamento | None:
    """Ignora o par (só ele). Se era o confirmado: fecha as oportunidades do anúncio e reabre os
    `outro_confirmado`. Sem o par: None."""
    if obter_par(s, anuncio_id, produto_id) is None:
        return None
    travar_anuncio(s, anuncio_id)
    par = obter_par(s, anuncio_id, produto_id)
    era_confirmado = par.status is CONFIRMADO
    par.status, par.origem, par.revisado_em, par.reavaliar = IGNORADO, origem, agora, False
    s.flush()
    if era_confirmado:
        fechar_oportunidades(s, anuncio_id, agora)
        _reabrir_outro_confirmado(s, anuncio_id)
    s.flush()
    return par


def desfazer(s: Session, anuncio_id: int, produto_id: int, agora: datetime) -> Casamento | None:
    """Volta o par a pendente (origem e revisão zeradas) e o marca para a IA reavaliar mesmo com os dados
    iguais. Se era o confirmado: fecha as oportunidades do anúncio e reabre os `outro_confirmado`. Par
    `outro_confirmado` com o anúncio ainda confirmado: JaConfirmado. Sem o par: None."""
    if obter_par(s, anuncio_id, produto_id) is None:
        return None
    travar_anuncio(s, anuncio_id)
    par = obter_par(s, anuncio_id, produto_id)
    if par.origem is OrigemCasamento.OUTRO_CONFIRMADO and (outro := confirmado_do_anuncio(s, anuncio_id)) is not None:
        raise JaConfirmado(anuncio_id, outro.produto_id)
    era_confirmado = par.status is CONFIRMADO
    par.status, par.origem, par.revisado_em, par.reavaliar = PENDENTE, None, None, True
    s.flush()
    _zerar_aplicada(s, anuncio_id, produto_id)
    if era_confirmado:
        fechar_oportunidades(s, anuncio_id, agora)
        _reabrir_outro_confirmado(s, anuncio_id)
    s.flush()
    return par


def trocar(
    s: Session, anuncio_id: int, produto_id: int, agora: datetime, origem: OrigemCasamento = OrigemCasamento.MANUAL
) -> Casamento:
    """Confirma (anúncio, produto) — criando o par se não existe — e o confirmado anterior do anúncio, se
    houver, vira ignorado `manual` (suas oportunidades fecham)."""
    travar_anuncio(s, anuncio_id)
    atual = confirmado_do_anuncio(s, anuncio_id)
    if atual is not None and atual.produto_id == produto_id:
        return atual
    if atual is not None:
        atual.status, atual.origem, atual.revisado_em, atual.reavaliar = IGNORADO, OrigemCasamento.MANUAL, agora, False
        s.flush()
    return confirmar(s, anuncio_id, produto_id, agora, origem)


def casar_asin(s: Session, produto_id: int, asin: str, agora: datetime, titulo_provisorio: str) -> AnuncioAmazon:
    """Link colado: cria o anúncio (título provisório) ou marca o existente como visto, e confirma o par com
    origem `manual`, trocando o confirmado anterior se houver. Quem chama prioriza o produto na fila."""
    anuncio = s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.asin == asin))
    if anuncio is None:
        anuncio = AnuncioAmazon(
            asin=asin, titulo=titulo_provisorio, url=f"https://www.amazon.com.br/dp/{asin}",
            visto_primeiro_em=agora, visto_ultimo_em=agora,
        )
        s.add(anuncio)
    else:
        anuncio.visto_ultimo_em = agora
    s.flush()
    trocar(s, anuncio.id, produto_id, agora, OrigemCasamento.MANUAL)
    return anuncio


def reavaliar_produto(s: Session, produto_id: int, agora: datetime) -> int:
    """"Reavaliar com a IA": volta a pendente (marcados para reavaliar) os pares do produto pendentes ou
    ignorados pela IA (`sugerido_ia`, `automatico_ia`, `outro_confirmado` cujo anúncio não é mais confirmado
    de ninguém). Decisões `manual` e confirmados não mudam. Devolve quantos pares marcou."""
    alvos = s.scalars(
        select(Casamento)
        .where(
            Casamento.produto_id == produto_id,
            or_(
                Casamento.status == PENDENTE,
                and_(Casamento.status == IGNORADO, Casamento.origem.in_(ORIGENS_REAVALIAVEIS)),
            ),
        )
        .order_by(Casamento.anuncio_id)
        .execution_options(populate_existing=True)
    ).all()
    marcados = 0
    for par in alvos:
        if par.origem is OrigemCasamento.OUTRO_CONFIRMADO and confirmado_do_anuncio(s, par.anuncio_id) is not None:
            continue
        par.status, par.origem, par.revisado_em, par.reavaliar = PENDENTE, None, None, True
        _zerar_aplicada(s, par.anuncio_id, produto_id)
        marcados += 1
    s.flush()
    return marcados


def marcar_reavaliado(s: Session, anuncio_id: int, produto_id: int) -> None:
    """O casador gravou uma avaliação nova do par: a marca de reavaliar sai."""
    s.execute(
        update(Casamento)
        .where(Casamento.anuncio_id == anuncio_id, Casamento.produto_id == produto_id)
        .values(reavaliar=False)
        .execution_options(synchronize_session="fetch")
    )
    s.flush()
```

- [ ] **Step 9: Repositório dos termos**

Crie `src/tcg_sniper/db/repositorio_termos.py`:

```python
"""Termos de busca alternativos (busca alternativa): gerados pela IA uma vez por produto e guardados.

Um produto ativo da fila está "em seca" quando não tem par confirmado e nenhuma busca dele criou par
pendente novo há `SECA` (sem nunca ter criado: desde que entrou na fila)."""

from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session

from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db.models import FilaAmazon, ProdutoLiga, TermoBusca

SECA = timedelta(days=7)
MAX_TERMOS = 3
TERMO_MAX = 80
IDIOMAS = ("pt", "en")


def _condicao_seca(agora: datetime):
    return and_(
        FilaAmazon.produto_id.not_in(repo_casamento.produtos_casados()),
        func.coalesce(FilaAmazon.ultimo_par_novo_em, FilaAmazon.entrou_em) <= agora - SECA,
    )


def termos_do_produto(s: Session, produto_id: int) -> list[TermoBusca]:
    return list(s.scalars(select(TermoBusca).where(TermoBusca.produto_id == produto_id).order_by(TermoBusca.ordem)))


def em_seca(s: Session, produto_id: int, agora: datetime) -> bool:
    consulta = select(FilaAmazon.produto_id).where(FilaAmazon.produto_id == produto_id, _condicao_seca(agora))
    return s.scalar(consulta) is not None


def marcar_tentativa(s: Session, produto_id: int, agora: datetime) -> None:
    """A IA respondeu (com ou sem termo válido): só tenta de novo depois de `SECA`; o pedido do admin sai."""
    s.execute(
        update(FilaAmazon)
        .where(FilaAmazon.produto_id == produto_id)
        .values(termos_tentados_em=agora, termos_pedidos_em=None)
    )
    s.flush()


def guardar_termos(s: Session, produto_id: int, termos: Sequence[tuple[str, str]], agora: datetime) -> list[TermoBusca]:
    """Substitui os termos do produto por `termos` ((termo, idioma), já filtrados, 1 a 3) e marca a tentativa."""
    if not 1 <= len(termos) <= MAX_TERMOS:
        raise ValueError(f"de 1 a {MAX_TERMOS} termos; recebeu {len(termos)}")
    s.execute(delete(TermoBusca).where(TermoBusca.produto_id == produto_id))
    novos = [
        TermoBusca(produto_id=produto_id, termo=termo, idioma=idioma, ordem=ordem, criado_em=agora)
        for ordem, (termo, idioma) in enumerate(termos, start=1)
    ]
    s.add_all(novos)
    s.flush()
    marcar_tentativa(s, produto_id, agora)
    return novos


def pedir_termos(s: Session, produto_id: int, agora: datetime) -> bool:
    """Botão "Gerar termos de busca": o casador gera (ou regenera) no próximo ciclo. False sem linha na fila."""
    resultado = s.execute(
        update(FilaAmazon).where(FilaAmazon.produto_id == produto_id).values(termos_pedidos_em=agora)
    )
    s.flush()
    return resultado.rowcount > 0


def produtos_para_gerar_termos(s: Session, agora: datetime, limite: int) -> list[ProdutoLiga]:
    """Até `limite` produtos ativos: primeiro os pedidos no admin (mais antigos primeiro, mesmo com termos
    guardados), depois os em seca sem termos e sem tentativa nos últimos 7 dias (os mais secos primeiro)."""
    base = select(ProdutoLiga).join(FilaAmazon, FilaAmazon.produto_id == ProdutoLiga.id).where(ProdutoLiga.ativo.is_(True))
    pedidos = list(
        s.scalars(
            base.where(FilaAmazon.termos_pedidos_em.is_not(None))
            .order_by(FilaAmazon.termos_pedidos_em, ProdutoLiga.id)
            .limit(limite)
        )
    )
    if len(pedidos) >= limite:
        return pedidos
    tem_termo = select(TermoBusca.id).where(TermoBusca.produto_id == ProdutoLiga.id).exists()
    secos = s.scalars(
        base.where(
            FilaAmazon.termos_pedidos_em.is_(None),
            _condicao_seca(agora),
            ~tem_termo,
            or_(FilaAmazon.termos_tentados_em.is_(None), FilaAmazon.termos_tentados_em <= agora - SECA),
        )
        .order_by(func.coalesce(FilaAmazon.ultimo_par_novo_em, FilaAmazon.entrou_em), ProdutoLiga.id)
        .limit(limite - len(pedidos))
    )
    return pedidos + list(secos)
```

- [ ] **Step 10: Fakes, link colado e limpeza do teste antigo da migração**

Em `tests/fakes.py`, troque o import de modelos por
`from tcg_sniper.db.models import AnuncioAmazon, Casamento, Envio, OrigemCasamento, PrecoAtualLiga, ProdutoLiga, StatusCasamento`
e `criar_anuncio` por:

```python
def criar_anuncio(
    s, asin="B000000001", produto=None, status=StatusCasamento.PENDENTE, agora=T0, origem=None
) -> AnuncioAmazon:
    """Anúncio e, com `produto`, o par (anúncio, produto) com `status` e `origem`.

    Transição (sai na Task 7): também grava as colunas antigas do anúncio, para as áreas ainda não
    portadas. `outro_confirmado` não existe na coluna antiga (vira `manual` lá)."""
    origem_antiga = OrigemCasamento.MANUAL if origem is OrigemCasamento.OUTRO_CONFIRMADO else origem
    anuncio = AnuncioAmazon(
        asin=asin,
        titulo=f"Anúncio {asin}",
        url=f"https://www.amazon.com.br/dp/{asin}",
        produto_id=produto.id if produto is not None else None,
        status_casamento=status,
        origem_casamento=origem_antiga,
        visto_primeiro_em=agora,
        visto_ultimo_em=agora,
    )
    s.add(anuncio)
    s.flush()
    if produto is not None:
        criar_par(s, anuncio, produto, status=status, origem=origem, agora=agora)
    return anuncio


def criar_par(
    s, anuncio, produto, status=StatusCasamento.PENDENTE, origem=None, agora=T0, revisado_em=None
) -> Casamento:
    """Par (anúncio, produto) direto no banco, sem as regras do repositório (para montar cenários)."""
    par = Casamento(
        anuncio_id=anuncio.id, produto_id=produto.id, status=status, origem=origem, revisado_em=revisado_em,
        visto_primeiro_em=agora, visto_ultimo_em=agora,
    )
    s.add(par)
    s.flush()
    return par
```

Em `src/tcg_sniper/db/repositorio_amazon.py`, acrescente `from tcg_sniper.db import repositorio_casamento as repo_casamento` aos imports e troque `casar_link_manual` por:

```python
def casar_link_manual(s: Session, produto_id: int, asin: str, agora: datetime) -> AnuncioAmazon:
    """Casa o ASIN informado à mão com o produto (par confirmado `manual`, trocando o confirmado anterior
    do anúncio se houver) e põe o produto na frente da fila."""
    anuncio = repo_casamento.casar_asin(s, produto_id, asin, agora, TITULO_MANUAL)
    # Transição (sai na Task 7): colunas antigas iguais ao par confirmado, para as telas ainda não portadas.
    anuncio.produto_id, anuncio.status_casamento = produto_id, StatusCasamento.CONFIRMADO
    anuncio.revisado_em, anuncio.origem_casamento = agora, OrigemCasamento.MANUAL
    s.flush()
    priorizar_na_fila(s, produto_id, agora)
    return anuncio
```

Em `tests/db/test_migracao.py::test_migracao_preenche_a_origem_do_casamento`, no `finally`, acrescente como **primeira** linha do bloco `with proprio.begin() as c:`:

```python
            c.execute(text("DELETE FROM casamento WHERE anuncio_id IN (SELECT id FROM anuncio_amazon WHERE asin LIKE 'BMIG%')"))
```

- [ ] **Step 11: Rodar os testes da tarefa**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t1 uv run pytest -q -p no:cacheprovider tests/db/test_repositorio_casamento.py tests/db/test_repositorio_termos.py tests/db/test_migracao_casamento.py tests/db/test_migracao.py tests/db/test_repositorio_amazon.py`
Expected: PASS.

- [ ] **Step 12: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t1 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde (nenhuma área mudou de comportamento: as colunas antigas continuam preenchidas pelos fakes e pelo link colado).

- [ ] **Step 13: Commit**

```bash
git add src/tcg_sniper/db/models.py src/tcg_sniper/db/migrations/versions/a9d4f2c6e8b1_casamento_por_par.py src/tcg_sniper/db/repositorio_casamento.py src/tcg_sniper/db/repositorio_termos.py src/tcg_sniper/db/repositorio_amazon.py tests/fakes.py tests/db/test_migracao.py tests/db/test_repositorio_casamento.py tests/db/test_repositorio_termos.py tests/db/test_migracao_casamento.py
git commit -m "feat: per-pair matching table, search terms table and pair repository"
```

---

### Task 2: Busca e fila sobre pares (lane `busca`)

**Files:**
- Modify: `src/tcg_sniper/db/repositorio_amazon.py` (`_descoberta_liberada` ~70-82, `reagendar` ~106-118, `gravar_busca` ~124-163; nova dataclass `GravacaoBusca`)
- Modify: `src/tcg_sniper/coletor_amazon/termo.py` (nova `sequencia_de_termos`)
- Modify: `src/tcg_sniper/coletor_amazon/busca.py` (`Conferencia`, `processar_produto`)
- Modify: `src/tcg_sniper/coletor_amazon/varredura.py` (`_passo_descoberta` ~592-663)
- Test: `tests/db/test_repositorio_amazon.py` (testes de `gravar_busca` e fila), `tests/coletor_amazon/test_termo.py`, `tests/coletor_amazon/test_busca.py`, `tests/coletor_amazon/test_varredura.py`

**Interfaces:**
- Consumes (Task 1): `repo_casamento.registrar_visto(s, anuncio_id, produto_id, agora) -> tuple[Casamento, bool]`, `repo_casamento.produtos_casados()`, `repo_termos.em_seca(s, produto_id, agora) -> bool`, `repo_termos.termos_do_produto(s, produto_id) -> list[TermoBusca]`, `repo_termos.guardar_termos`, `FilaAmazon.indice_termo`, `FilaAmazon.ultimo_par_novo_em`, `fakes.criar_par`.
- Produces:
  - `repositorio_amazon.GravacaoBusca(anuncios: list[AnuncioAmazon], pares_novos: int)` (frozen); `repositorio_amazon.gravar_busca(s, itens, produto_id, agora, zona) -> GravacaoBusca`.
  - `repositorio_amazon.reagendar(s, produto_id, agora, proxima, teve_candidato, indice_termo: int = 0) -> None` (o 6º parâmetro deixa de ser `termo_en`).
  - `termo.sequencia_de_termos(nome: str, nome_en: str | None, alternativos: Sequence[str] = ()) -> list[str]`.
  - `busca.Conferencia(candidatos: int, pares_novos: int = 0)`; `busca.processar_produto(ctx, produto, termo: str | None = None) -> Conferencia` (sai `usar_nome_en`).

- [ ] **Step 1: Banco da lane**

Run (de dentro do worktree): `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_t2`

- [ ] **Step 2: Testes da sequência de termos (falham)**

Acrescente a `tests/coletor_amazon/test_termo.py` (sem repetir imports que o arquivo já tenha):

```python
import pytest

from tcg_sniper.coletor_amazon.termo import sequencia_de_termos

NOME = "Caixa de Booster - Alfa"


def test_sequencia_so_com_o_nome():
    assert sequencia_de_termos(NOME, None) == [NOME]


def test_sequencia_com_ingles_e_alternativos_sem_repetir():
    alternativos = ["alpha booster box", "caixa de booster: ALFA", "Booster Box: Alpha", "   ", "caixa alfa lacrada"]
    assert sequencia_de_termos(NOME, "Booster Box - Alpha", alternativos) == [
        NOME, "Booster Box - Alpha", "alpha booster box", "caixa alfa lacrada",
    ]


@pytest.mark.parametrize("nome_en", ["Caixa de Booster: Alfa", "CAIXA DE BOOSTER ALFA", "  -  ", "", None])
def test_ingles_igual_ao_portugues_ou_vazio_nao_entra(nome_en):
    assert sequencia_de_termos(NOME, nome_en) == [NOME]
```

- [ ] **Step 3: Testes do repositório (falham)**

Em `tests/db/test_repositorio_amazon.py`: imports `from fakes import T0, criar_anuncio, criar_par, criar_preco_liga, criar_produto` e `from tcg_sniper.db import repositorio_casamento as repo_casamento`; troque `test_gravar_busca_cria_pendente_com_sugestao_e_nao_troca_a_sugestao` pelos testes abaixo; nos testes de imagem (~linhas 324-328) troque cada `[a] = repo.gravar_busca(...)` por `[a] = repo.gravar_busca(...).anuncios`.

```python
PENDENTE, CONFIRMADO, IGNORADO = StatusCasamento.PENDENTE, StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO


def test_gravar_busca_cria_o_par_pendente_do_produto_buscado(s):
    a = criar_produto(s, "a")
    repo.sincronizar_fila(s, T0 - timedelta(days=10))
    gravacao = repo.gravar_busca(s, [resultado("B01"), resultado("B01", "90.00"), resultado("B02")], a.id, T0, SP)
    assert [x.asin for x in gravacao.anuncios] == ["B01", "B02"] and gravacao.pares_novos == 2
    par = repo_casamento.obter_par(s, gravacao.anuncios[0].id, a.id)
    assert (par.status, par.origem, par.visto_primeiro_em, par.visto_ultimo_em) == (PENDENTE, None, T0, T0)
    assert s.get(PrecoAtualAmazon, gravacao.anuncios[0].id).preco == Decimal("100.00")  # vale o primeiro cartão
    assert s.get(FilaAmazon, a.id).ultimo_par_novo_em == T0


def test_anuncio_ignorado_para_a_vira_pendente_na_busca_de_b(s):
    a, b = criar_produto(s, "a"), criar_produto(s, "b")
    anuncio = criar_anuncio(s, "B01", produto=a, status=IGNORADO, origem=OrigemCasamento.MANUAL)
    depois = T0 + timedelta(hours=1)
    gravacao = repo.gravar_busca(s, [resultado("B01", titulo="Novo título")], b.id, depois, SP)
    assert gravacao.pares_novos == 1
    assert repo_casamento.obter_par(s, anuncio.id, b.id).status is PENDENTE
    assert repo_casamento.obter_par(s, anuncio.id, a.id).status is IGNORADO  # ignorado vale só para o par
    s.refresh(anuncio)
    assert (anuncio.titulo, anuncio.visto_ultimo_em) == ("Novo título", depois)


def test_par_existente_so_atualiza_o_visto(s):
    a = criar_produto(s, "a")
    repo.sincronizar_fila(s, T0)
    ignorado = criar_anuncio(s, "B01", produto=a, status=IGNORADO, origem=OrigemCasamento.MANUAL)
    confirmado = criar_anuncio(s, "B02", produto=a, status=CONFIRMADO, origem=OrigemCasamento.MANUAL)
    depois = T0 + timedelta(days=1)
    gravacao = repo.gravar_busca(s, [resultado("B01"), resultado("B02")], a.id, depois, SP)
    assert gravacao.pares_novos == 0
    for anuncio, status in ((ignorado, IGNORADO), (confirmado, CONFIRMADO)):
        par = repo_casamento.obter_par(s, anuncio.id, a.id)
        assert (par.status, par.visto_primeiro_em, par.visto_ultimo_em) == (status, T0, depois)
    assert s.get(FilaAmazon, a.id).ultimo_par_novo_em is None


def test_anuncio_confirmado_para_q_entra_ignorado_para_p_e_nao_tira_da_seca(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    repo.sincronizar_fila(s, T0)
    anuncio = criar_anuncio(s, "B01", produto=q, status=CONFIRMADO, origem=OrigemCasamento.MANUAL)
    gravacao = repo.gravar_busca(s, [resultado("B01")], p.id, T0, SP)
    par = repo_casamento.obter_par(s, anuncio.id, p.id)
    assert (par.status, par.origem) == (IGNORADO, OrigemCasamento.OUTRO_CONFIRMADO)
    assert gravacao.pares_novos == 0 and s.get(FilaAmazon, p.id).ultimo_par_novo_em is None


def test_descoberta_olha_os_pares_confirmados_do_produto(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    repo.sincronizar_fila(s, T0)
    anuncio = criar_anuncio(s, "B01", produto=q, status=CONFIRMADO)
    criar_par(s, anuncio, p, status=IGNORADO, origem=OrigemCasamento.OUTRO_CONFIRMADO, revisado_em=T0)
    repo.reagendar(s, p.id, T0, T0, False)
    repo.reagendar(s, q.id, T0, T0, False)
    assert repo.ids_na_fila(s, T0 + timedelta(hours=1), 7) == {p.id}  # q casado e buscado há menos de 7 dias


def test_reagendar_guarda_o_indice_do_proximo_termo(s):
    p = criar_produto(s, "p")
    repo.sincronizar_fila(s, T0)
    assert s.get(FilaAmazon, p.id).indice_termo == 0
    repo.reagendar(s, p.id, T0, T0 + timedelta(hours=1), False, indice_termo=2)
    assert s.get(FilaAmazon, p.id).indice_termo == 2
```

- [ ] **Step 4: Testes da busca e da varredura (falham)**

Em `tests/coletor_amazon/test_busca.py`:
- Acrescente `from tcg_sniper.db import repositorio_casamento as repo_casamento`.
- Em `test_asin_novo_fica_pendente_e_so_a_busca_e_aberta`, troque `assert processar_produto(ctx, produto) == Conferencia(0)` por `assert processar_produto(ctx, produto) == Conferencia(0, 1)` e a linha do `status_casamento` por `assert repo_casamento.obter_par(s, anuncio.id, produto.id).status is StatusCasamento.PENDENTE` (dentro do `with sessoes() as s:`, depois de ler o anúncio).
- Nos demais `== Conferencia(n)`, use `Conferencia(n, k)`, com `k` = pares pendentes que aquela chamada criou (0 quando o anúncio já tinha par com o produto ou é confirmado de outro).
- Troque os dois testes de `usar_nome_en` por:

```python
def test_busca_pelo_termo_informado(sessoes, config, produto):
    with sessoes() as s, s.begin():
        cfg = repo.obter_config(s)
        url_pt, url_en = url_busca(cfg, NOME), url_busca(cfg, "Booster Box - Final Fantasy")
    assert "Booster+Box+Final+Fantasy" in url_en
    with sessoes() as s:
        p = s.get(ProdutoLiga, produto.id)
        ctx, navegador, _ = contexto(sessoes, config, {url_pt: busca(url_pt), url_en: busca(url_en)})
        processar_produto(ctx, p)
        processar_produto(ctx, p, "Booster Box - Final Fantasy")
        processar_produto(ctx, p, None)
    assert navegador.visitadas == [url_pt, url_en, url_pt]
```

Em `tests/coletor_amazon/test_varredura.py`:
- Acrescente `cartao_busca` e `html_busca` ao import de `fakes` e `from tcg_sniper.db import repositorio_termos as repo_termos`.
- `test_busca_alterna_portugues_e_ingles_quando_ha_nome_en`: troque `ultimo_termo_en` por `indice_termo` e `assert flags == [False, True, False]` por `assert flags == [1, 0, 1]`.
- `test_busca_sem_nome_en_sempre_em_portugues_e_flag_continua_falso`: `assert s.get(FilaAmazon, a.id).indice_termo == 0`.
- `test_nome_en_igual_ao_portugues_ou_vazio_nao_vira_busca_em_ingles`: `assert s.get(FilaAmazon, a.id).indice_termo == 0`.
- `test_flag_do_termo_tambem_alterna_quando_a_busca_falha_no_parser`: `indice_termo` e `assert flags == [1, 0]`.
- No monkeypatch `quebra_so_a(contexto, produto, usar_nome_en=False)`: `quebra_so_a(contexto, produto, termo=None)` e `return real(contexto, produto, termo)`.
- Acrescente:

```python
def _em_seca(sessoes, produto_id, termos, nome_en=None):
    """Produto 8 dias na fila sem par novo, com `termos` guardados. Devolve {termo: url}."""
    with sessoes() as s, s.begin():
        produto = s.get(ProdutoLiga, produto_id)
        produto.nome_en = nome_en
        repo_amz.sincronizar_fila(s, MEIO_DIA - timedelta(days=8))
        if termos:
            repo_termos.guardar_termos(s, produto_id, termos, MEIO_DIA - timedelta(days=1))
        cfg = repo_amz.obter_config(s)
        nomes = [produto.nome, *([nome_en] if nome_en else []), *(termo for termo, _ in termos)]
        return {nome: url_busca(cfg, nome) for nome in nomes}


DUAS_HORAS = timedelta(hours=2, minutes=1)  # sem candidato há 7 dias o intervalo dobra (120 min)


def test_em_seca_a_fila_alterna_nome_ingles_e_termos(engine, sessoes, config):
    (a,), _ = produtos(sessoes, "Caixa de Booster - Alfa")
    urls = _em_seca(sessoes, a.id, [("alfa booster box", "en"), ("caixa alfa lacrada", "pt")], "Booster Box - Alpha")
    relogio = Relogio(MEIO_DIA)
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()}, relogio=relogio)
    for _ in range(5):
        assert v.passo() == 0
        relogio.agora += DUAS_HORAS
    assert navegador.visitadas == [
        urls["Caixa de Booster - Alfa"], urls["Booster Box - Alpha"], urls["alfa booster box"],
        urls["caixa alfa lacrada"], urls["Caixa de Booster - Alfa"],
    ]


def test_em_seca_sem_termos_segue_com_o_nome_normal(engine, sessoes, config):
    (a,), _ = produtos(sessoes, "Caixa de Booster - Alfa")
    urls = _em_seca(sessoes, a.id, [], "Booster Box - Alpha")
    relogio = Relogio(MEIO_DIA)
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()}, relogio=relogio)
    for _ in range(3):
        assert v.passo() == 0
        relogio.agora += DUAS_HORAS
    pt, en = urls["Caixa de Booster - Alfa"], urls["Booster Box - Alpha"]
    assert navegador.visitadas == [pt, en, pt]


def test_candidato_novo_na_seca_volta_ao_nome_normal(engine, sessoes, config):
    (a,), _ = produtos(sessoes, "Caixa de Booster - Alfa")
    urls = _em_seca(sessoes, a.id, [("alfa booster box", "en")], "Booster Box - Alpha")
    pt, en, alternativo = urls["Caixa de Booster - Alfa"], urls["Booster Box - Alpha"], urls["alfa booster box"]
    com_anuncio = pagina_html(html_busca(cartao_busca("B0NOVO0001", "Caixa Alfa", "R$ 900,00")), url=pt)
    relogio = Relogio(MEIO_DIA)
    paginas = {pt: com_anuncio, en: vazia(en), alternativo: vazia(alternativo)}
    v, navegador, _, _ = varredura(engine, sessoes, config, paginas, relogio=relogio)
    for _ in range(3):
        assert v.passo() == 0
        relogio.agora += DUAS_HORAS
    assert navegador.visitadas == [pt, en, pt]  # o termo alternativo não entra mais
    with sessoes() as s:
        assert s.get(FilaAmazon, a.id).ultimo_par_novo_em == MEIO_DIA
        assert [t.termo for t in repo_termos.termos_do_produto(s, a.id)] == ["alfa booster box"]  # guardados


def test_indice_maior_que_a_sequencia_nao_quebra(engine, sessoes, config):
    (a,), urls = produtos(sessoes, "Caixa de Booster - Alfa")
    with sessoes() as s, s.begin():
        repo_amz.sincronizar_fila(s, MEIO_DIA)
        s.get(FilaAmazon, a.id).indice_termo = 4  # sobra de uma seca que acabou
    url = urls[a.id]
    v, navegador, _, _ = varredura(engine, sessoes, config, {url: vazia(url)})
    assert v.passo() == 0 and navegador.visitadas == [url]
    with sessoes() as s:
        assert s.get(FilaAmazon, a.id).indice_termo == 0
```

- [ ] **Step 5: Rodar para ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t2 uv run pytest -q -p no:cacheprovider tests/coletor_amazon/test_termo.py tests/db/test_repositorio_amazon.py tests/coletor_amazon/test_busca.py tests/coletor_amazon/test_varredura.py`
Expected: FAIL (`cannot import name 'sequencia_de_termos'`, `'list' object has no attribute 'anuncios'`, `reagendar() got an unexpected keyword argument 'indice_termo'`).

- [ ] **Step 6: Sequência de termos**

Em `src/tcg_sniper/coletor_amazon/termo.py`, acrescente `from collections.abc import Sequence` no topo e, no fim:

```python
def sequencia_de_termos(nome: str, nome_en: str | None, alternativos: Sequence[str] = ()) -> list[str]:
    """Termos que a fila alterna para o produto, nesta ordem: o nome em português, o nome em inglês (se
    existir e der um termo diferente) e os termos alternativos (a varredura só os passa na seca). Termo
    vazio ou repetido (sem diferenciar maiúsculas nem pontuação) sai."""
    vistos: set[str] = set()
    saida: list[str] = []
    for candidato in (nome, nome_en or "", *alternativos):
        chave = termo_busca(candidato).casefold()
        if chave and chave not in vistos:
            vistos.add(chave)
            saida.append(candidato)
    return saida or [nome]
```

- [ ] **Step 7: Repositório (fila e `gravar_busca`)**

Em `src/tcg_sniper/db/repositorio_amazon.py` (o import `repo_casamento` já veio da Task 1):

```python
def _descoberta_liberada(agora: datetime | None, casados_dias: int | None):
    """Sem par confirmado: sempre (no ritmo da fila). Com par confirmado: só se nunca buscado ou se a
    última busca tem `casados_dias` dias ou mais (busca semanal)."""
    if agora is None or casados_dias is None:
        return literal(True)
    return or_(
        FilaAmazon.produto_id.not_in(repo_casamento.produtos_casados()),
        FilaAmazon.ultima_busca_em.is_(None),
        FilaAmazon.ultima_busca_em <= agora - timedelta(days=casados_dias),
    )
```

```python
def reagendar(
    s: Session, produto_id: int, agora: datetime, proxima: datetime, teve_candidato: bool, indice_termo: int = 0
) -> None:
    """`indice_termo`: o próximo termo da sequência do produto (a varredura calcula; ver `sequencia_de_termos`)."""
    valores: dict[str, datetime | int] = {
        "ultima_busca_em": agora,
        "proxima_busca_em": proxima,
        "indice_termo": indice_termo,
    }
    if teve_candidato:
        valores["ultimo_candidato_em"] = agora
    s.execute(update(FilaAmazon).where(FilaAmazon.produto_id == produto_id).values(**valores))
    s.flush()
```

```python
@dataclass(frozen=True)
class GravacaoBusca:
    anuncios: list[AnuncioAmazon]  # na ordem da busca, sem ASIN repetido
    pares_novos: int  # pares (anúncio, produto buscado) criados pendentes nesta busca: os candidatos


def gravar_busca(
    s: Session, itens: Sequence[ResultadoBusca], produto_id: int, agora: datetime, zona: ZoneInfo
) -> GravacaoBusca:
    """Upsert dos anúncios da busca, do preço de origem `busca` e do par (anúncio, produto buscado): par
    novo fica pendente (ou ignorado `outro_confirmado`, se o anúncio já é confirmado de outro produto);
    par existente só ganha `visto_ultimo_em` (status não muda). Par pendente novo marca
    `fila_amazon.ultimo_par_novo_em` (a seca da busca alternativa conta daí). ASIN repetido na mesma busca
    vale uma vez (o primeiro cartão)."""
    unicos: dict[str, ResultadoBusca] = {}
    for item in itens:
        unicos.setdefault(item.asin, item)
    pares_novos = 0
    for item in unicos.values():
        stmt = pg_insert(AnuncioAmazon).values(
            asin=item.asin,
            titulo=item.titulo,
            url=item.url,
            visto_primeiro_em=agora,
            visto_ultimo_em=agora,
            imagem_url=item.imagem_url,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[AnuncioAmazon.asin],
            set_={
                "titulo": stmt.excluded.titulo,
                "url": stmt.excluded.url,
                "visto_ultimo_em": agora,
                # a busca só preenche a imagem vazia; a página do produto pode trocar
                "imagem_url": func.coalesce(AnuncioAmazon.imagem_url, stmt.excluded.imagem_url),
            },
        ).returning(AnuncioAmazon.id)
        anuncio_id = s.execute(stmt).scalar_one()
        registrar_preco(s, anuncio_id, item.preco, OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, agora, zona)
        par, criado = repo_casamento.registrar_visto(s, anuncio_id, produto_id, agora)
        if criado and par.status is StatusCasamento.PENDENTE:
            pares_novos += 1
    if pares_novos:
        s.execute(update(FilaAmazon).where(FilaAmazon.produto_id == produto_id).values(ultimo_par_novo_em=agora))
    s.flush()
    por_asin = {
        a.asin: a
        for a in s.scalars(
            select(AnuncioAmazon).where(AnuncioAmazon.asin.in_(unicos)).execution_options(populate_existing=True)
        )
    }
    return GravacaoBusca([por_asin[asin] for asin in unicos], pares_novos)
```

- [ ] **Step 8: Busca e varredura**

Em `src/tcg_sniper/coletor_amazon/busca.py`, troque `Conferencia` e `processar_produto` por:

```python
@dataclasses.dataclass(frozen=True)
class Conferencia:
    candidatos: int  # confirmados da busca já no desconto pelo preço atual (só para o ritmo da fila)
    pares_novos: int = 0  # pares pendentes criados por esta busca (candidatos novos ao casamento)


def processar_produto(ctx: ContextoBusca, produto: ProdutoLiga, termo: str | None = None) -> Conferencia:
    """Busca o produto por `termo` (padrão: o nome em português) e grava os resultados. Devolve quantos
    anúncios confirmados da busca estão no desconto pelo preço atual (a fila busca mais vezes o produto
    que teve candidato) e quantos pares novos a busca criou. Lança DesafioAmazon (CAPTCHA), ErroParser
    (layout) ou ErroRede (depois de uma nova tentativa)."""
    pagina = abrir_pagina(ctx, url_busca(ctx.cfg, termo or produto.nome))
    itens = ler_pagina(ctx, pagina, "busca", lambda html: parse_busca(html, ctx.cfg.resultados_por_busca))
    with ctx.sessoes() as s, s.begin():
        gravacao = repo.gravar_busca(s, itens, produto.id, ctx.relogio(), ctx.config.zona)
        candidatos = sum(
            1
            for linha in repo.confirmados_com_referencia(s, [a.id for a in gravacao.anuncios])
            if motor.atinge_desconto(
                linha.atual.preco, linha.liga.preco_a_partir if linha.liga else None, ctx.cfg.desconto_min_pct
            )
        )
    return Conferencia(candidatos, gravacao.pares_novos)
```

e, na docstring do módulo, troque "(ASIN novo fica pendente para o casamento)" por "(cada ASIN ganha o par com o produto buscado; par novo fica pendente)".

Em `src/tcg_sniper/coletor_amazon/varredura.py`: troque `from tcg_sniper.coletor_amazon.termo import termo_busca` por `from tcg_sniper.coletor_amazon.termo import sequencia_de_termos` e acrescente `from tcg_sniper.db import repositorio_termos as repo_termos`. Em `_passo_descoberta`, troque o primeiro `with` (o que calcula `usar_en`) por:

```python
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
```

e, no resto do método, `processar_produto(contexto, produto, usar_en)` vira `processar_produto(contexto, produto, termo)` e os dois `repo_amz.reagendar(..., usar_en)` viram `repo_amz.reagendar(..., proximo_indice)` (no `except Exception` e no fim).

- [ ] **Step 9: Rodar os testes da tarefa**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t2 uv run pytest -q -p no:cacheprovider tests/coletor_amazon tests/db/test_repositorio_amazon.py tests/db/test_repositorio_monitor.py`
Expected: PASS.

- [ ] **Step 10: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t2 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde. Se um teste de outra área falhar porque `gravar_busca` não grava mais as colunas antigas, porte esse teste para pares (regra da transição).

- [ ] **Step 11: Commit**

```bash
git add src/tcg_sniper/db/repositorio_amazon.py src/tcg_sniper/coletor_amazon/termo.py src/tcg_sniper/coletor_amazon/busca.py src/tcg_sniper/coletor_amazon/varredura.py tests/db/test_repositorio_amazon.py tests/coletor_amazon
git commit -m "feat: search records per-pair matches and the queue rotates alternative terms"
```

---

### Task 3: Casador por par e geração dos termos (lane `casador`)

**Files:**
- Modify: `src/tcg_sniper/db/repositorio_ia.py` (`ParPendente`, `pares_pendentes` ~102-127, `pares_decididos` ~171-198)
- Create: `src/tcg_sniper/casador/termos.py`
- Modify: `src/tcg_sniper/casador/servico.py` (`ciclo`, `_gravar`, `_aplicar`; novos `_pausar_por_configuracao` e `_gerar_termos`)
- Modify: `src/tcg_sniper/db/models.py` (só o comentário de `ChamadaIA.finalidade`: `# "casamento" | "avaliacao" | "termos"`)
- Test: `tests/db/test_repositorio_ia.py`, `tests/casador/test_servico.py`, `tests/casador/test_avaliacao.py`, `tests/casador/test_termos.py` (novo), `tests/casador/test_servico_termos.py` (novo)

**Interfaces:**
- Consumes (Task 1): `Casamento`; `repo_casamento.travar_anuncio`, `obter_par`, `confirmar`, `ignorar`, `desfazer`, `trocar`, `reavaliar_produto`, `marcar_reavaliado`, `registrar_visto`, `JaConfirmado`; `repo_termos.produtos_para_gerar_termos`, `guardar_termos`, `marcar_tentativa`, `pedir_termos`, `termos_do_produto`, `MAX_TERMOS`, `TERMO_MAX`, `IDIOMAS`; `fakes.criar_par`. Existentes: `ia.cliente.perguntar`, `coletor_amazon.termo.termo_busca`.
- Produces:
  - `repositorio_ia.ParPendente(anuncio, produto, avaliacao, preco_liga, preco_amazon, reavaliar: bool = False)`; `pares_pendentes(s, so_descoberta=False)` e `pares_decididos(s, limite)` por par (mesmas assinaturas).
  - `casador.termos`: `FINALIDADE = "termos"`, `NOME_FORMATO = "termos_busca"`, `INSTRUCOES: str`, `FORMATO: dict`, `texto_pedido(produto: ProdutoLiga) -> str`, `filtrar_termos(dados: dict, nome: str, nome_en: str | None) -> list[tuple[str, str]]` (RespostaForaDoFormato sem a lista), `gerar_termos(sessoes, transporte, produto, *, zona, relogio=agora_utc) -> list[tuple[str, str]]`.
  - `casador.servico.TERMOS_POR_CICLO = 5`.

- [ ] **Step 1: Banco da lane**

Run (de dentro do worktree): `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_t3`

- [ ] **Step 2: Testes do repositório da IA (falham)**

Em `tests/db/test_repositorio_ia.py`: imports `from fakes import T0, criar_anuncio, criar_par, criar_preco_liga, criar_produto`, `from tcg_sniper.db import repositorio_casamento as repo_casamento` e `Casamento` entre os modelos. Troque estes testes (os demais ficam):

```python
def test_pares_pendentes_com_avaliacao_e_precos(s):
    p = criar_produto(s, "p1", nome="Caixa X")
    inativo = criar_produto(s, "p2", ativo=False, nome="Caixa Y")
    criar_preco_liga(s, p, Decimal(500))
    a1 = criar_anuncio(s, "B1", produto=p, agora=T0 - timedelta(days=1))
    a2 = criar_anuncio(s, "B2", produto=p, agora=T0)
    criar_anuncio(s, "B3", produto=inativo, agora=T0 + timedelta(hours=1))  # produto inativo: fora
    criar_anuncio(s, "B4", produto=p, status=StatusCasamento.CONFIRMADO)
    criar_anuncio(s, "B5", produto=None)
    av = repo_ia.gravar_avaliacao(
        s, anuncio_id=a1.id, produto_id=p.id, mesmo_produto=True, confianca=95, motivo="igual",
        modelo="gpt-5", assinatura="x", sem_imagem=False, chamada_id=None, agora=T0,
    )
    pares = repo_ia.pares_pendentes(s)
    assert [par.anuncio.id for par in pares] == [a2.id, a1.id]  # mais recentes primeiro
    assert pares[1].avaliacao.id == av.id and pares[0].avaliacao is None
    assert pares[0].preco_liga == Decimal(500) and pares[0].preco_amazon is None
    assert pares[0].reavaliar is False


def test_pares_pendentes_um_anuncio_em_dois_produtos_e_fora_se_confirmado(s):
    p, q, r = criar_produto(s, "p"), criar_produto(s, "q"), criar_produto(s, "r")
    anuncio = criar_anuncio(s, "B1", produto=p)
    criar_par(s, anuncio, q)
    casado = criar_anuncio(s, "B2", produto=r, status=StatusCasamento.CONFIRMADO)
    criar_par(s, casado, p)  # pendente de anúncio confirmado em r (corrida): fora da IA
    pares = {(par.anuncio.id, par.produto.id) for par in repo_ia.pares_pendentes(s)}
    assert pares == {(anuncio.id, p.id), (anuncio.id, q.id)}


def test_pares_decididos_sem_os_aplicados_pela_ia_nem_os_do_sistema(s):
    p, q = criar_produto(s, "p1"), criar_produto(s, "p2")
    c = criar_anuncio(s, "B1", produto=p, status=StatusCasamento.CONFIRMADO, origem=OrigemCasamento.MANUAL)
    criar_par(s, c, q, status=StatusCasamento.IGNORADO, origem=OrigemCasamento.OUTRO_CONFIRMADO, revisado_em=T0)
    i = criar_anuncio(s, "B2", produto=p, status=StatusCasamento.IGNORADO, origem=OrigemCasamento.MANUAL)
    pela_ia = criar_anuncio(s, "B3", produto=p, status=StatusCasamento.CONFIRMADO, origem=OrigemCasamento.AUTOMATICO_IA)
    criar_anuncio(s, "B4", produto=p)  # pendente
    av = repo_ia.gravar_avaliacao(
        s, anuncio_id=pela_ia.id, produto_id=p.id, mesmo_produto=True, confianca=99, motivo="m", modelo="gpt-5",
        assinatura="x", sem_imagem=False, chamada_id=None, agora=T0,
    )
    av.aplicada_em = T0
    s.get(Casamento, (pela_ia.id, p.id)).revisado_em = T0  # o automático grava os dois no mesmo instante
    s.flush()
    decididos = repo_ia.pares_decididos(s, None)
    assert {(d.anuncio.id, d.produto.id, d.confirmado) for d in decididos} == {(c.id, p.id, True), (i.id, p.id, False)}
    assert len(repo_ia.pares_decididos(s, 1)) == 1


def test_correcao_do_usuario_depois_do_automatico_conta_na_avaliacao(s):
    p = criar_produto(s, "p1")
    a = criar_anuncio(s, "B1", produto=p, status=StatusCasamento.IGNORADO, origem=OrigemCasamento.MANUAL)
    av = repo_ia.gravar_avaliacao(
        s, anuncio_id=a.id, produto_id=p.id, mesmo_produto=True, confianca=99, motivo="m", modelo="gpt-5",
        assinatura="x", sem_imagem=False, chamada_id=None, agora=T0,
    )
    av.aplicada_em = T0  # a IA confirmou; o usuário desfez e ignorou depois
    s.get(Casamento, (a.id, p.id)).revisado_em = T0 + timedelta(hours=1)
    s.flush()
    assert [(d.anuncio.id, d.confirmado) for d in repo_ia.pares_decididos(s, None)] == [(a.id, False)]


def test_pares_pendentes_so_descoberta_pula_os_antigos_de_produto_casado(s):
    casado = criar_produto(s, "casado")
    livre = criar_produto(s, "livre")
    b0 = criar_anuncio(s, "B0", produto=casado, status=StatusCasamento.CONFIRMADO)
    s.get(Casamento, (b0.id, casado.id)).revisado_em = T0
    antigo = criar_anuncio(s, "B1", produto=casado, agora=T0 - timedelta(days=1))
    da_semanal = criar_anuncio(s, "B2", produto=casado, agora=T0 + timedelta(days=7))
    de_livre = criar_anuncio(s, "B3", produto=livre, agora=T0 - timedelta(days=1))
    s.flush()
    assert {p.anuncio.id for p in repo_ia.pares_pendentes(s, so_descoberta=True)} == {da_semanal.id, de_livre.id}
    assert {p.anuncio.id for p in repo_ia.pares_pendentes(s)} == {antigo.id, da_semanal.id, de_livre.id}
    repo_casamento.reavaliar_produto(s, casado.id, T0)  # pedido de reavaliar vale mesmo no produto casado
    pares = {p.anuncio.id: p for p in repo_ia.pares_pendentes(s, so_descoberta=True)}
    assert antigo.id in pares and pares[antigo.id].reavaliar is True
```

- [ ] **Step 3: Testes do filtro e da geração dos termos (falham)**

Crie `tests/casador/test_termos.py`:

```python
import json
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, TransporteFake, criar_produto
from sqlalchemy import select

from tcg_sniper.casador.termos import FINALIDADE, filtrar_termos, gerar_termos
from tcg_sniper.db.models import ChamadaIA
from tcg_sniper.ia.modelos import Bruta, RespostaForaDoFormato

NOME, NOME_EN = "Caixa de Booster - Alfa", "Booster Box - Alpha"
VALIDO = ("caixa alfa lacrada", "pt")


def dados(*itens):
    return {"termos": [{"termo": termo, "idioma": idioma} for termo, idioma in itens]}


def test_mantem_os_validos_na_ordem():
    itens = (("alfa booster box", "en"), VALIDO)
    assert filtrar_termos(dados(*itens), NOME, NOME_EN) == list(itens)


@pytest.mark.parametrize(
    "termo",
    [
        "",
        "   ",
        "x" * 81,
        "https://www.amazon.com.br/dp/B0ALFA0001",
        "www.amazon.com.br caixa alfa",
        "caixa de booster: ALFA",  # o nome em português com outra pontuação e caixa
        "booster box alpha",  # o nome em inglês
    ],
)
def test_descarta_invalidos(termo):
    assert filtrar_termos(dados((termo, "pt"), VALIDO), NOME, NOME_EN) == [VALIDO]


def test_descarta_idioma_desconhecido_repetido_e_corta_em_3():
    itens = (("alfa caja", "es"), VALIDO, ("Caixa  Alfa  Lacrada", "pt"), ("a1", "pt"), ("a2", "en"), ("a3", "pt"))
    assert filtrar_termos(dados(*itens), NOME, None) == [VALIDO, ("a1", "pt"), ("a2", "en")]


def test_espacos_internos_sao_normalizados():
    assert filtrar_termos(dados(("caixa   alfa \t lacrada", "pt")), NOME, None) == [VALIDO]


def test_item_que_nao_e_objeto_ou_sem_texto_e_ignorado():
    assert filtrar_termos({"termos": ["solto", {"idioma": "pt"}, {"termo": 3, "idioma": "pt"}]}, NOME, None) == []


@pytest.mark.parametrize("resposta", [{}, {"termos": "caixa alfa"}])
def test_resposta_sem_lista_e_fora_do_formato(resposta):
    with pytest.raises(RespostaForaDoFormato):
        filtrar_termos(resposta, NOME, None)


def test_gerar_termos_faz_uma_chamada_sem_imagem_e_registra_a_finalidade(sessoes):
    with sessoes() as s, s.begin():
        produto = criar_produto(s, "p1", nome=NOME)
        produto.nome_en = NOME_EN
        s.flush()
        s.expunge(produto)
    t = TransporteFake([Bruta(json.dumps(dados(("alfa booster box", "en"))), 300, 40)])
    termos = gerar_termos(sessoes, t, produto, zona=ZoneInfo("America/Sao_Paulo"), relogio=lambda: T0)
    assert termos == [("alfa booster box", "en")]
    [pedido] = t.pedidos
    assert pedido.imagens == () and NOME in pedido.texto and NOME_EN in pedido.texto
    with sessoes() as s:
        assert [c.finalidade for c in s.scalars(select(ChamadaIA))] == [FINALIDADE]
```

- [ ] **Step 4: Testes do casador (falham)**

Em `tests/casador/test_servico.py`:
- Imports: `from tcg_sniper.db import repositorio_casamento as repo_casamento` e `Casamento` entre os modelos; tire `repo_amz` se ficar sem uso.
- Troque `status_de` por:

```python
def status_de(sessoes, anuncio_id, produto_id=None):
    with sessoes() as s:
        pares_do_anuncio = list(s.scalars(select(Casamento).where(Casamento.anuncio_id == anuncio_id)))
    if produto_id is not None:
        pares_do_anuncio = [par for par in pares_do_anuncio if par.produto_id == produto_id]
    [par] = pares_do_anuncio
    return par.status
```

- No teste dos limites do automático (~linha 136): `revisado = s.scalar(select(Casamento.revisado_em).where(Casamento.anuncio_id == anuncio_id))`.
- `test_decisao_humana_durante_a_chamada_vence`: no `enviar`, `repo_casamento.trocar(s, a, outro_id, T0)  # usuário troca o produto no meio`; as asserções sobre o anúncio viram `assert status_de(sessoes, a, outro_id) is StatusCasamento.CONFIRMADO and status_de(sessoes, a, p_id) is StatusCasamento.IGNORADO`.
- Troque `test_desfeito_pelo_usuario_nao_e_reaplicado` e `test_avaliacao_antiga_nao_e_aplicada_se_desfeita_ou_decidida_pelo_usuario` (regra antiga; o spec mudou) por:

```python
def test_desfazer_faz_a_ia_reavaliar_mesmo_sem_mudar_os_dados(sessoes, config):
    configurar(sessoes, automatico=True)
    p_id, [a] = pares(sessoes)
    sv, t, _ = servico(sessoes, config, [veredito(True, 99), veredito(True, 70)])
    sv.ciclo()
    assert status_de(sessoes, a) is StatusCasamento.CONFIRMADO
    with sessoes() as s, s.begin():
        repo_casamento.desfazer(s, a, p_id, T0)  # sem mudar título, imagem nem produto
    assert sv.ciclo() == 1 and len(t.pedidos) == 2  # reavaliou com a assinatura igual
    assert status_de(sessoes, a) is StatusCasamento.PENDENTE  # 70 < 90: espera você
    with sessoes() as s:
        assert s.get(Casamento, (a, p_id)).reavaliar is False
    assert sv.ciclo() == 0 and len(t.pedidos) == 2  # não repete


def test_desfeito_volta_para_a_ia_e_o_automatico_decide_de_novo(sessoes, config):
    configurar(sessoes, automatico=True)
    p_id, [a, b] = pares(sessoes, 2)
    respostas = [veredito(True, 99), veredito(False, 99), veredito(True, 99), veredito(False, 99)]
    sv, _, _ = servico(sessoes, config, respostas)
    sv.ciclo()
    with sessoes() as s, s.begin():
        repo_casamento.desfazer(s, a, p_id, T0)
        repo_casamento.desfazer(s, b, p_id, T0)
    assert sv.ciclo() == 2
    assert status_de(sessoes, a) is StatusCasamento.CONFIRMADO and status_de(sessoes, b) is StatusCasamento.IGNORADO
```

- `test_automatico_grava_a_origem_automatico_ia`: `assert s.scalar(select(Casamento.origem).where(Casamento.anuncio_id == a)) is OrigemCasamento.AUTOMATICO_IA`.
- `test_nao_avalia_pendente_antigo_de_produto_ja_casado`: a linha do `B0CASADO` vira `casado = criar_anuncio(s, "B0CASADO", produto=p, status=StatusCasamento.CONFIRMADO)` seguida de `s.get(Casamento, (casado.id, p.id)).revisado_em = T0`.
- Acrescente:

```python
def test_anuncio_ignorado_em_a_e_achado_na_busca_de_b_e_avaliado_para_b(sessoes, config):
    configurar(sessoes)
    with sessoes() as s, s.begin():
        colecionador = criar_produto(s, "a", nome="Caixa Colecionador")
        jogo = criar_produto(s, "b", nome="Caixa de Jogo")
        anuncio = criar_anuncio(
            s, "B0JOGO0001", produto=colecionador, status=StatusCasamento.IGNORADO, origem=OrigemCasamento.AUTOMATICO_IA
        )
        repo_casamento.registrar_visto(s, anuncio.id, jogo.id, T0)
        esperado = (anuncio.id, jogo.id)
    sv, _, _ = servico(sessoes, config, [veredito(True, 95)])
    assert sv.ciclo() == 1
    [av] = avaliacoes(sessoes)
    assert (av.anuncio_id, av.produto_id) == esperado


def test_par_outro_confirmado_fica_fora_da_ia(sessoes, config):
    configurar(sessoes)
    with sessoes() as s, s.begin():
        p, q = criar_produto(s, "p"), criar_produto(s, "q")
        anuncio = criar_anuncio(s, "B0Q0000001", produto=q, status=StatusCasamento.CONFIRMADO)
        repo_casamento.registrar_visto(s, anuncio.id, p.id, T0)
    sv, t, _ = servico(sessoes, config, [])
    assert sv.ciclo() == 0 and t.pedidos == []


def test_automatico_nao_confirma_anuncio_que_ficou_confirmado_em_outro_produto(sessoes, config):
    configurar(sessoes, automatico=True)
    p_id, [a] = pares(sessoes)
    with sessoes() as s, s.begin():
        q_id = criar_produto(s, "q").id

    class TransporteQueConfirmaOutro(TransporteFake):
        def enviar(self, pedido):
            with sessoes() as s, s.begin():
                repo_casamento.confirmar(s, a, q_id, T0)  # você confirma para q enquanto a IA responde
                par = s.get(Casamento, (a, p_id))  # e uma busca atrasada deixou o par de p pendente (corrida)
                par.status, par.origem, par.revisado_em = StatusCasamento.PENDENTE, None, None
            return super().enviar(pedido)

    t = TransporteQueConfirmaOutro([veredito(True, 99)])
    sv = ServicoCasador(sessoes, t, config.model_copy(update={"openai_api_key": "k"}), AvisadorFake(),
                        cliente_http=sem_rede(), relogio=lambda: T0)
    sv.ciclo()
    assert status_de(sessoes, a, q_id) is StatusCasamento.CONFIRMADO
    assert status_de(sessoes, a, p_id) is StatusCasamento.PENDENTE
    [av] = avaliacoes(sessoes)
    assert av.aplicada_em is None


def test_reavaliar_produto_casado_reavalia_tambem_os_pares_antigos(sessoes, config):
    configurar(sessoes)
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Caixa Alfa")
        casado = criar_anuncio(s, "B0CASADO", produto=p, status=StatusCasamento.CONFIRMADO)
        s.get(Casamento, (casado.id, p.id)).revisado_em = T0
        criar_anuncio(s, "B1ANTIGO", produto=p, agora=T0 - timedelta(days=1))
        p_id = p.id
    sv, t, _ = servico(sessoes, config, [veredito(False, 95)])
    assert sv.ciclo() == 0  # so_descoberta: o antigo de produto casado fica de fora
    with sessoes() as s, s.begin():
        assert repo_casamento.reavaliar_produto(s, p_id, T0) == 1
    assert sv.ciclo() == 1 and len(t.pedidos) == 1
```

Em `tests/casador/test_avaliacao.py` (~linha 41), importe `Casamento` e troque a asserção por `assert {c.status for c in s.scalars(select(Casamento))} == {StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO}`.

Crie `tests/casador/test_servico_termos.py`:

```python
import json
from datetime import timedelta
from decimal import Decimal

import httpx
from fakes import T0, AvisadorFake, TransporteFake, criar_anuncio, criar_produto
from sqlalchemy import select

from tcg_sniper.avisos.catalogo import TipoAviso
from tcg_sniper.casador.servico import TERMOS_POR_CICLO, ServicoCasador
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db import repositorio_termos as repo_termos
from tcg_sniper.db.models import ChamadaIA, FilaAmazon, ProdutoLiga, StatusCasamento
from tcg_sniper.ia.modelos import Bruta

DIA = timedelta(days=1)


def termos(*itens):
    return Bruta(json.dumps({"termos": [{"termo": termo, "idioma": idioma} for termo, idioma in itens]}), 300, 40)


def servico(sessoes, config, respostas, agora):
    t = TransporteFake(respostas)
    avisador = AvisadorFake()
    cfg = config.model_copy(update={"openai_api_key": "sk-teste"})
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    return ServicoCasador(sessoes, t, cfg, avisador, cliente_http=http, relogio=lambda: agora), t, avisador


def configurar(sessoes, **valores):
    with sessoes() as s, s.begin():
        repo_ia.salvar_config_ia(s, {"ligado": True, **valores}, T0)


def na_fila(sessoes, *liga_ids, entrou_em=T0):
    with sessoes() as s, s.begin():
        ids = [criar_produto(s, liga_id, nome=f"Caixa de Booster {liga_id}").id for liga_id in liga_ids]
        repo_amz.sincronizar_fila(s, entrou_em)
        return ids


def guardados(sessoes, produto_id):
    with sessoes() as s:
        return [(t.termo, t.idioma) for t in repo_termos.termos_do_produto(s, produto_id)]


def test_gera_termos_so_depois_de_7_dias_sem_candidato(sessoes, config):
    configurar(sessoes)
    [p] = na_fila(sessoes, "alfa")
    sv, t, _ = servico(sessoes, config, [], T0 + 6 * DIA)
    sv.ciclo()
    assert t.pedidos == []
    respostas = [termos(("alfa booster box", "en"), ("caixa alfa lacrada", "pt"))]
    sv, t, _ = servico(sessoes, config, respostas, T0 + 7 * DIA)
    sv.ciclo()
    [pedido] = t.pedidos
    assert pedido.imagens == ()
    assert guardados(sessoes, p) == [("alfa booster box", "en"), ("caixa alfa lacrada", "pt")]
    with sessoes() as s:
        assert [c.finalidade for c in s.scalars(select(ChamadaIA))] == ["termos"]
    sv, t, _ = servico(sessoes, config, [], T0 + 8 * DIA)
    sv.ciclo()
    assert t.pedidos == []  # uma vez por produto: já tem termos guardados


def test_termos_invalidos_sao_descartados_e_so_tenta_de_novo_em_7_dias(sessoes, config):
    configurar(sessoes)
    [p] = na_fila(sessoes, "alfa")
    invalidos = [termos(("https://amazon.com.br/x", "pt"), ("Caixa de Booster alfa", "pt"))]
    sv, t, _ = servico(sessoes, config, invalidos, T0 + 7 * DIA)
    sv.ciclo()
    assert len(t.pedidos) == 1 and guardados(sessoes, p) == []
    with sessoes() as s:
        assert s.get(FilaAmazon, p).termos_tentados_em == T0 + 7 * DIA
    sv, t, _ = servico(sessoes, config, [], T0 + 13 * DIA)
    sv.ciclo()
    assert t.pedidos == []
    sv, t, _ = servico(sessoes, config, [termos(("alfa booster box", "en"))], T0 + 14 * DIA)
    sv.ciclo()
    assert guardados(sessoes, p) == [("alfa booster box", "en")]


def test_sem_orcamento_nao_gera_e_mantem_o_pedido(sessoes, config):
    configurar(sessoes, teto_dia_usd=Decimal("0"))
    [p] = na_fila(sessoes, "alfa")
    with sessoes() as s, s.begin():
        repo_termos.pedir_termos(s, p, T0)
    sv, t, avisador = servico(sessoes, config, [], T0)
    sv.ciclo()
    assert t.pedidos == [] and guardados(sessoes, p) == []
    assert TipoAviso.IA_SEM_ORCAMENTO in avisador.tipos()
    with sessoes() as s:
        fila = s.get(FilaAmazon, p)
        assert (fila.termos_pedidos_em, fila.termos_tentados_em) == (T0, None)


def test_pedido_do_admin_regenera_mesmo_com_termos_guardados(sessoes, config):
    configurar(sessoes)
    [p] = na_fila(sessoes, "alfa")
    with sessoes() as s, s.begin():
        repo_termos.guardar_termos(s, p, [("antigo alfa", "pt")], T0)
        repo_termos.pedir_termos(s, p, T0)
    sv, _, _ = servico(sessoes, config, [termos(("alfa booster box", "en"))], T0)  # fora da seca: vale o pedido
    sv.ciclo()
    assert guardados(sessoes, p) == [("alfa booster box", "en")]
    with sessoes() as s:
        assert s.get(FilaAmazon, p).termos_pedidos_em is None


def test_limite_de_produtos_por_ciclo(sessoes, config):
    configurar(sessoes)
    na_fila(sessoes, *(f"p{i}" for i in range(TERMOS_POR_CICLO + 1)))
    respostas = [termos((f"termo {i}", "pt")) for i in range(TERMOS_POR_CICLO + 1)]
    sv, t, _ = servico(sessoes, config, respostas, T0 + 7 * DIA)
    sv.ciclo()
    assert len(t.pedidos) == TERMOS_POR_CICLO


def test_produto_casado_nao_gera_termos(sessoes, config):
    configurar(sessoes)
    [p] = na_fila(sessoes, "alfa")
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B0CASADO01", produto=s.get(ProdutoLiga, p), status=StatusCasamento.CONFIRMADO)
    sv, t, _ = servico(sessoes, config, [], T0 + 30 * DIA)
    sv.ciclo()
    assert t.pedidos == []
```

- [ ] **Step 5: Rodar para ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t3 uv run pytest -q -p no:cacheprovider tests/db/test_repositorio_ia.py tests/casador`
Expected: FAIL (`No module named 'tcg_sniper.casador.termos'`, `cannot import name 'TERMOS_POR_CICLO'`, pares pendentes ainda pela coluna antiga).

- [ ] **Step 6: Repositório da IA**

Em `src/tcg_sniper/db/repositorio_ia.py`, acrescente `Casamento` aos modelos importados e troque `ParPendente`, `pares_pendentes` e `pares_decididos` por:

```python
@dataclass(frozen=True)
class ParPendente:
    anuncio: AnuncioAmazon
    produto: ProdutoLiga
    avaliacao: AvaliacaoIA | None
    preco_liga: Decimal | None
    preco_amazon: Decimal | None
    reavaliar: bool = False  # Desfazer ou "Reavaliar com a IA": avalia de novo mesmo com a assinatura igual


def pares_pendentes(s: Session, so_descoberta: bool = False) -> list[ParPendente]:
    """Pares pendentes de produtos ativos cujo anúncio não é confirmado de nenhum produto, com a avaliação
    do par (se houver) e os preços atuais; os vistos mais recentemente primeiro. Com `so_descoberta` (o
    casador), pula os pares de produto já casado, exceto os que a busca do produto viu pela primeira vez
    depois do primeiro casamento dele (a busca semanal) e os marcados para reavaliar."""
    confirmado = aliased(Casamento)
    anuncio_confirmado = (
        select(confirmado.anuncio_id)
        .where(confirmado.anuncio_id == Casamento.anuncio_id, confirmado.status == StatusCasamento.CONFIRMADO)
        .exists()
    )
    consulta = (
        select(Casamento, AnuncioAmazon, ProdutoLiga, AvaliacaoIA, PrecoAtualLiga.preco_a_partir, PrecoAtualAmazon.preco)
        .join(AnuncioAmazon, AnuncioAmazon.id == Casamento.anuncio_id)
        .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
        .outerjoin(
            AvaliacaoIA,
            and_(AvaliacaoIA.anuncio_id == Casamento.anuncio_id, AvaliacaoIA.produto_id == Casamento.produto_id),
        )
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .where(Casamento.status == StatusCasamento.PENDENTE, ProdutoLiga.ativo.is_(True), ~anuncio_confirmado)
        .order_by(Casamento.visto_ultimo_em.desc(), Casamento.anuncio_id, Casamento.produto_id)
    )
    if so_descoberta:
        casado = aliased(Casamento)
        casado_desde = (
            select(func.min(casado.revisado_em))
            .where(casado.produto_id == Casamento.produto_id, casado.status == StatusCasamento.CONFIRMADO)
            .scalar_subquery()
        )
        consulta = consulta.where(
            or_(casado_desde.is_(None), Casamento.visto_primeiro_em > casado_desde, Casamento.reavaliar.is_(True))
        )
    return [
        ParPendente(anuncio, produto, avaliacao, liga, amazon, par.reavaliar)
        for par, anuncio, produto, avaliacao, liga, amazon in s.execute(consulta)
    ]
```

```python
def pares_decididos(s: Session, limite: int | None) -> list[ParDecidido]:
    """Pares confirmados ou ignorados por você (não pelo automático nem pelo sistema: `outro_confirmado` fica
    de fora), para a avaliação. A decisão é do automático só se ainda for a dele (`aplicada_em ==
    revisado_em` do par): corrigida por você, conta."""
    aplicada = (
        select(AvaliacaoIA.id)
        .where(
            AvaliacaoIA.anuncio_id == Casamento.anuncio_id,
            AvaliacaoIA.produto_id == Casamento.produto_id,
            AvaliacaoIA.aplicada_em == Casamento.revisado_em,
        )
        .exists()
    )
    consulta = (
        select(Casamento, AnuncioAmazon, ProdutoLiga, PrecoAtualLiga.preco_a_partir, PrecoAtualAmazon.preco)
        .join(AnuncioAmazon, AnuncioAmazon.id == Casamento.anuncio_id)
        .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .where(
            Casamento.status.in_([StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO]),
            Casamento.origem.is_distinct_from(OrigemCasamento.OUTRO_CONFIRMADO),
            ~aplicada,
        )
        .order_by(Casamento.anuncio_id, Casamento.produto_id)
        .limit(limite)
    )
    return [
        ParDecidido(anuncio, produto, par.status is StatusCasamento.CONFIRMADO, liga, amazon)
        for par, anuncio, produto, liga, amazon in s.execute(consulta)
    ]
```

`origem_da_decisao`, `gravar_avaliacao` e `avaliacoes_dos_pares` não mudam (já são por par).

- [ ] **Step 7: Geração dos termos**

Crie `src/tcg_sniper/casador/termos.py`:

```python
"""Busca alternativa: a IA sugere de 2 a 3 termos de busca na Amazon Brasil para um produto da Liga (uma
chamada barata, sem imagem, dentro do teto de gasto) e o filtro descarta os inválidos."""

import re
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.coletor_amazon.termo import termo_busca
from tcg_sniper.db.models import ProdutoLiga
from tcg_sniper.db.repositorio import agora_utc
from tcg_sniper.db.repositorio_termos import IDIOMAS, MAX_TERMOS, TERMO_MAX
from tcg_sniper.ia.cliente import perguntar
from tcg_sniper.ia.modelos import RespostaForaDoFormato, Transporte

FINALIDADE = "termos"
NOME_FORMATO = "termos_busca"
_LINK = re.compile(r"https?://|www\.|\.com\b|\.br\b", re.IGNORECASE)

INSTRUCOES = """Você ajuda a achar na Amazon Brasil (amazon.com.br) um produto selado de Magic: The Gathering vendido na LigaMagic.
A busca pelo nome da LigaMagic não achou nada parecido há uma semana. Sugira de 2 a 3 termos de busca curtos, do jeito que um vendedor da Amazon escreveria o título: em português ou em inglês, com a coleção e o tipo do produto (booster avulso, caixa de boosters, bundle, deck, kit, colecionador etc.).
Não repita o nome da LigaMagic nem o nome em inglês exatamente como foram dados. Sem links, sem aspas, até 80 caracteres cada. Informe o idioma de cada termo: "pt" ou "en"."""

FORMATO = {
    "type": "object",
    "properties": {
        "termos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"termo": {"type": "string"}, "idioma": {"type": "string", "enum": list(IDIOMAS)}},
                "required": ["termo", "idioma"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["termos"],
    "additionalProperties": False,
}


def texto_pedido(produto: ProdutoLiga) -> str:
    return "\n".join(
        [
            "Produto da LigaMagic:",
            f"- nome: {produto.nome}",
            f"- nome em inglês: {produto.nome_en or '(não informado)'}",
            f"- edição: {produto.edicao or '(não informada)'}",
            f"- tipo: {produto.tipo or '(não informado)'}",
            f"- idioma: {produto.idioma or '(não informado)'}",
        ]
    )


def filtrar_termos(dados: dict, nome: str, nome_en: str | None) -> list[tuple[str, str]]:
    """Os termos válidos, na ordem da resposta, no máximo 3: sem vazio, até 80 caracteres, sem link, sem
    repetir o nome nem o nome em inglês (nem entre si; sem diferenciar maiúsculas e pontuação) e com idioma
    "pt" ou "en". Resposta sem a lista: RespostaForaDoFormato."""
    brutos = dados.get("termos")
    if not isinstance(brutos, list):
        raise RespostaForaDoFormato("resposta sem a lista de termos")
    vistos = {termo_busca(n).casefold() for n in (nome, nome_en) if n}
    saida: list[tuple[str, str]] = []
    for item in brutos:
        if not isinstance(item, dict):
            continue
        termo, idioma = item.get("termo"), item.get("idioma")
        if not isinstance(termo, str) or idioma not in IDIOMAS:
            continue
        termo = " ".join(termo.split())
        chave = termo_busca(termo).casefold()
        if not chave or len(termo) > TERMO_MAX or _LINK.search(termo) or chave in vistos:
            continue
        vistos.add(chave)
        saida.append((termo, idioma))
    return saida[:MAX_TERMOS]


def gerar_termos(
    sessoes: sessionmaker[Session],
    transporte: Transporte,
    produto: ProdutoLiga,
    *,
    zona: ZoneInfo,
    relogio: Callable[[], datetime] = agora_utc,
) -> list[tuple[str, str]]:
    """Uma chamada (registrada em `chamada_ia` com a finalidade "termos"). Lança SemOrcamento (sem chamar),
    ChaveInvalida, ConfiguracaoInvalida, RespostaForaDoFormato ou ErroIA, como `perguntar`."""
    resposta = perguntar(
        sessoes, transporte, finalidade=FINALIDADE, instrucoes=INSTRUCOES, texto=texto_pedido(produto), imagens=[],
        nome_formato=NOME_FORMATO, formato=FORMATO, zona=zona, relogio=relogio,
    )
    return filtrar_termos(resposta.dados, produto.nome, produto.nome_en)
```

- [ ] **Step 8: Serviço do casador**

Em `src/tcg_sniper/casador/servico.py`:
- Imports: `from tcg_sniper.casador.termos import gerar_termos`, `from tcg_sniper.db import repositorio_casamento as repo_casamento`, `from tcg_sniper.db import repositorio_termos as repo_termos`; dos modelos fica `COLETOR_CASADOR, EstadoColetorTipo, OrigemCasamento, StatusCasamento` (sai `AnuncioAmazon`); tire `repo_amz` se ficar sem uso.
- Constante: `TERMOS_POR_CICLO = 5  # produtos por ciclo na busca alternativa (uma chamada barata cada, sem imagem)`.
- No laço que separa os candidatos em `ciclo()`: `if p.avaliacao is not None and p.avaliacao.assinatura == atual and not p.reavaliar:`.
- Novo método (e use-o no `except (ChaveInvalida, ConfiguracaoInvalida)` de `ciclo()` no lugar das três linhas de pausa):

```python
    def _pausar_por_configuracao(self, erro: Exception) -> None:
        with self._sessoes() as s, s.begin():
            repo.pausar(s, str(erro), self._relogio(), COLETOR_CASADOR)
        self._avisador.avisar(TipoAviso.IA_PAUSADA, CHAVE_GERAL, Dados(linhas=(f"Motivo: {erro}",)))
        log.error("casador pausado: %s", erro)
```

- Em `ciclo()`: declare `interrompido = False` junto de `avaliados = falhas = ...`; nos `except SemOrcamento` e `except (ChaveInvalida, ConfiguracaoInvalida)` faça `interrompido = True` antes do `break`. Logo antes do `return avaliados`:

```python
        if not interrompido and not self._parar.is_set():
            self._gerar_termos(zona)
```

- Em `_gravar`, logo depois de `av = repo_ia.gravar_avaliacao(...)`:

```python
            repo_casamento.marcar_reavaliado(s, par.anuncio.id, par.produto.id)
```

- Troque `_aplicar` por:

```python
    @staticmethod
    def _aplicar(s: Session, av, limites: tuple[int, int], agora: datetime) -> StatusCasamento | None:
        """Automático: confirma ou ignora o par se a confiança passa do limite. Só age se o par ainda está
        pendente (decisão sua vale) e o anúncio não foi confirmado para outro produto nesse meio-tempo."""
        confirmar, ignorar = limites
        repo_casamento.travar_anuncio(s, av.anuncio_id)
        par = repo_casamento.obter_par(s, av.anuncio_id, av.produto_id)
        if par is None or par.status is not StatusCasamento.PENDENTE:
            return None  # você decidiu enquanto a IA respondia
        try:
            if av.mesmo_produto and av.confianca >= confirmar:
                repo_casamento.confirmar(s, av.anuncio_id, av.produto_id, agora, OrigemCasamento.AUTOMATICO_IA)
                decisao = StatusCasamento.CONFIRMADO
            elif not av.mesmo_produto and av.confianca >= ignorar:
                repo_casamento.ignorar(s, av.anuncio_id, av.produto_id, agora, OrigemCasamento.AUTOMATICO_IA)
                decisao = StatusCasamento.IGNORADO
            else:
                return None
        except repo_casamento.JaConfirmado as erro:
            log.info("anúncio %s já confirmado para o produto %s: o automático não age", av.anuncio_id, erro.produto_id)
            return None
        av.aplicada_em = agora
        return decisao
```

- Acrescente a etapa:

```python
    def _gerar_termos(self, zona: ZoneInfo) -> int:
        """Busca alternativa: gera os termos dos produtos pedidos no admin e dos em seca sem termos, no máximo
        `TERMOS_POR_CICLO`. Para no primeiro SemOrcamento (o pedido fica para o próximo período, com o aviso de
        teto de sempre). Sem termo válido ou resposta fora do formato: marca a tentativa (7 dias)."""
        with self._sessoes() as s, s.begin():
            produtos = repo_termos.produtos_para_gerar_termos(s, self._relogio(), TERMOS_POR_CICLO)
            for produto in produtos:
                s.expunge(produto)
        gerados = 0
        for produto in produtos:
            if self._parar.is_set():
                break
            try:
                termos = gerar_termos(self._sessoes, self._transporte, produto, zona=zona, relogio=self._relogio)
            except SemOrcamento as erro:
                self._avisar_orcamento(str(erro), zona)
                break
            except (ChaveInvalida, ConfiguracaoInvalida) as erro:
                self._pausar_por_configuracao(erro)
                break
            except RespostaForaDoFormato as erro:
                log.warning("termos do produto %s fora do formato: %s", produto.id, erro)
                termos = []
            except ErroIA as erro:
                log.warning("IA falhou ao gerar termos do produto %s: %s", produto.id, erro)
                continue
            except Exception:
                log.exception("erro inesperado ao gerar termos do produto %s; segue para o próximo", produto.id)
                continue
            with self._sessoes() as s, s.begin():
                if termos:
                    repo_termos.guardar_termos(s, produto.id, termos, self._relogio())
                    gerados += 1
                else:
                    repo_termos.marcar_tentativa(s, produto.id, self._relogio())
        if gerados:
            log.info("busca alternativa: termos gerados para %d produto(s)", gerados)
        return gerados
```

- [ ] **Step 9: Rodar os testes da tarefa**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t3 uv run pytest -q -p no:cacheprovider tests/db/test_repositorio_ia.py tests/casador`
Expected: PASS.

- [ ] **Step 10: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t3 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde.

- [ ] **Step 11: Commit**

```bash
git add src/tcg_sniper/db/repositorio_ia.py src/tcg_sniper/db/models.py src/tcg_sniper/casador tests/db/test_repositorio_ia.py tests/casador
git commit -m "feat: matcher works on pairs, re-evaluates undone pairs and generates alternative search terms"
```

---

### Task 4: Monitor, checkout e oportunidades sobre o par confirmado (lane `monitor`)

**Files:**
- Modify: `src/tcg_sniper/db/repositorio_amazon.py` (`confirmados_com_referencia` ~232-245, `_confirmados_ativos` ~531-536, `candidatas_ao_checkout` ~798-843)
- Modify: `src/tcg_sniper/admin/consultas.py` (`historico_conferencias` ~250-266, `historico_monitor` ~279-308)
- Test: `tests/db/test_repositorio_monitor.py`, `tests/coletor_amazon/test_monitor.py`, `tests/admin/test_consultas_logs_par.py` (novo)

**Interfaces:**
- Consumes (Task 1): `Casamento`, `repo_casamento.condicao_confirmado(anuncio_id)`, `repo_casamento.confirmado_do_anuncio`, `repo_casamento.confirmar`, `repo_casamento.desfazer`, `fakes.criar_par`.
- Produces: as mesmas assinaturas de hoje — `confirmados_com_referencia(s, anuncio_ids) -> list[LinhaConfirmada]` (o `produto` é o do par confirmado), `proximo_do_monitor`, `situacao_monitor`, `candidatas_ao_checkout`, `historico_conferencias`, `historico_monitor` — agora lendo o par confirmado. `monitor.py` e `checkout.py` não mudam (consomem essas funções).

- [ ] **Step 1: Banco da lane**

Run (de dentro do worktree): `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_t4`

- [ ] **Step 2: Testes (falham)**

Em `tests/db/test_repositorio_monitor.py`, imports `from fakes import T0, criar_anuncio, criar_par, criar_preco_liga, criar_produto, oferta_lista` e `OrigemCasamento` entre os modelos; acrescente no fim:

```python
def test_monitor_e_checkout_usam_so_o_par_confirmado(s):
    cfg = repo.obter_config(s)
    anuncio = confirmado(s, "B0PAR00001")  # confirmado para p-B0PAR00001 (Liga R$ 1.000)
    barato = criar_produto(s, "barato-par")
    criar_preco_liga(s, barato, "100.00", listagem_em=T0)
    criar_par(s, anuncio, barato, status=StatusCasamento.IGNORADO, origem=OrigemCasamento.OUTRO_CONFIRMADO, revisado_em=T0)
    so_pendente = criar_anuncio(s, "B0PAR00002", produto=barato)  # só pendente: fora do monitor e do checkout
    ler(s, anuncio, T0, oferta_lista("700.00"))
    ler(s, so_pendente, T0, oferta_lista("50.00"))
    assert repo.situacao_monitor(s, T0, 15).confirmados == 1
    assert repo.proximo_do_monitor(s, T0, 15) is None  # o único confirmado acabou de ser lido
    [linha] = repo.confirmados_com_referencia(s, [anuncio.id, so_pendente.id])
    assert linha.produto.liga_id == "p-B0PAR00001" and linha.liga.preco_a_partir == Decimal("1000.00")
    assert [c.asin for c in repo.candidatas_ao_checkout(s, T0, cfg)] == ["B0PAR00001"]  # 30% abaixo de 1.000


def test_confirmado_de_produto_inativo_sai_do_monitor_mesmo_com_par_pendente_ativo(s):
    anuncio = confirmado(s, "B0PAR00003", ativo=False)
    criar_par(s, anuncio, criar_produto(s, "ativo-par"))  # corrida: pendente para um produto ativo
    assert repo.situacao_monitor(s, T0, 15).confirmados == 0
    assert repo.proximo_do_monitor(s, T0, 15) is None
```

Em `tests/coletor_amazon/test_monitor.py`, imports `criar_par` (de `fakes`), `from tcg_sniper.db import repositorio_casamento as repo_casamento` e `OrigemCasamento` entre os modelos; acrescente:

```python
def test_oportunidade_usa_o_produto_do_par_confirmado(sessoes, config, anuncio):
    with sessoes() as s, s.begin():
        outro = criar_produto(s, "outro", nome="Outro produto")
        criar_preco_liga(s, outro, "100.00", listagem_em=AGORA - timedelta(hours=2))
        criar_par(
            s, s.get(AnuncioAmazon, anuncio.id), outro, status=StatusCasamento.IGNORADO,
            origem=OrigemCasamento.OUTRO_CONFIRMADO, revisado_em=AGORA,
        )
        certo = repo_casamento.confirmado_do_anuncio(s, anuncio.id).produto_id
    ctx, _, _ = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))}, checkout=False)
    ler_anuncio(ctx, anuncio.id, ASIN)
    with sessoes() as s:
        op = s.scalar(select(Oportunidade))
    assert (op.produto_id, op.preco_liga) == (certo, Decimal("1000.00"))


def test_par_desfeito_nao_abre_oportunidade(sessoes, config, anuncio):
    with sessoes() as s, s.begin():
        par = repo_casamento.confirmado_do_anuncio(s, anuncio.id)
        repo_casamento.desfazer(s, anuncio.id, par.produto_id, AGORA)
    ctx, _, avisador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))}, checkout=False)
    ler_anuncio(ctx, anuncio.id, ASIN)
    assert avisador.mensagens == []
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)) is None
```

Crie `tests/admin/test_consultas_logs_par.py`:

```python
from decimal import Decimal

from fakes import T0, criar_anuncio, criar_produto, oferta_lista

from tcg_sniper.admin import consultas
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db.models import SituacaoCheckout


def test_logs_do_checkout_e_do_monitor_mostram_o_produto_confirmado(s):
    pendente = criar_produto(s, "pendente-log", nome="Produto Sugerido")
    certo = criar_produto(s, "certo-log", nome="Produto Certo")
    anuncio = criar_anuncio(s, "B0LOG00001", produto=pendente)
    repo_casamento.confirmar(s, anuncio.id, certo.id, T0)
    repo_amz.registrar_conferencia(
        s, em=T0, anuncio_id=anuncio.id, vendedor_nome="Loja", preco_anunciado=Decimal("1.00"), itens=None,
        frete=None, impostos=None, total=None, situacao=SituacaoCheckout.FALHA, motivo="m", item_removido=True,
    )
    repo_amz.gravar_ofertas(s, anuncio.id, T0, [repo_amz.OfertaAvaliada(oferta_lista(), None, True, True)])
    conferencias, _, _ = consultas.historico_conferencias(s, "todas", 1)
    leituras, _, _ = consultas.historico_monitor(s, 1)
    assert [linha.produto for linha in conferencias] == ["Produto Certo"]
    assert [linha.produto for linha in leituras] == ["Produto Certo"]
```

- [ ] **Step 3: Rodar para ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t4 uv run pytest -q -p no:cacheprovider tests/db/test_repositorio_monitor.py tests/coletor_amazon/test_monitor.py tests/admin/test_consultas_logs_par.py`
Expected: FAIL (o monitor ainda lê a coluna antiga: conta o par errado, abre oportunidade no par desfeito, mostra "Produto Sugerido").

- [ ] **Step 4: Implementação**

Em `src/tcg_sniper/db/repositorio_amazon.py` (acrescente `Casamento` ao import de modelos; `repo_casamento` já está importado):

```python
def confirmados_com_referencia(s: Session, anuncio_ids: Sequence[int]) -> list[LinhaConfirmada]:
    """Dos anúncios dados, os que têm par confirmado, com o produto do par, o preço atual e o da Liga."""
    if not anuncio_ids:
        return []
    consulta = (
        select(AnuncioAmazon, ProdutoLiga, PrecoAtualAmazon, PrecoAtualLiga)
        .join(Casamento, repo_casamento.condicao_confirmado(AnuncioAmazon.id))
        .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
        .join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(AnuncioAmazon.id.in_(anuncio_ids))
        .order_by(AnuncioAmazon.id)
        .execution_options(populate_existing=True)
    )
    return [LinhaConfirmada(*linha) for linha in s.execute(consulta)]
```

```python
def _confirmados_ativos(consulta):
    """Anúncios com par confirmado de produto ativo (o par confirmado é um só por anúncio)."""
    return (
        consulta.join(Casamento, repo_casamento.condicao_confirmado(AnuncioAmazon.id))
        .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .where(ProdutoLiga.ativo.is_(True))
    )
```

Em `candidatas_ao_checkout`, troque `.join(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)` por

```python
        .join(Casamento, repo_casamento.condicao_confirmado(AnuncioAmazon.id))
        .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
```

e tire `AnuncioAmazon.status_casamento == StatusCasamento.CONFIRMADO,` do `.where(...)`; na docstring, "de cada confirmado" vira "de cada anúncio com par confirmado".

Em `src/tcg_sniper/admin/consultas.py` (imports `Casamento` e `from tcg_sniper.db import repositorio_casamento as repo_casamento`), nos dois históricos troque `.outerjoin(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)` por

```python
        .outerjoin(Casamento, repo_casamento.condicao_confirmado(AnuncioAmazon.id))
        .outerjoin(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
```

- [ ] **Step 5: Rodar os testes da tarefa**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t4 uv run pytest -q -p no:cacheprovider tests/db/test_repositorio_monitor.py tests/coletor_amazon tests/admin/test_consultas_logs_par.py tests/admin/test_admin_logs.py`
Expected: PASS.

- [ ] **Step 6: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t4 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde. (Testes que confirmam pelas funções antigas `repo_amz.confirmar_casamento`/`desfazer_casamento` e depois esperam efeito no monitor: porte para `repo_casamento`.)

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/db/repositorio_amazon.py src/tcg_sniper/admin/consultas.py tests/db/test_repositorio_monitor.py tests/coletor_amazon/test_monitor.py tests/admin/test_consultas_logs_par.py
git commit -m "feat: monitor, checkout, opportunities and logs read the confirmed pair"
```

---

### Task 5: Admin — listas, menu, dashboard, ofertas e produto por par (lane `admin`)

**Files:**
- Modify: `src/tcg_sniper/admin/consultas_amazon.py` (`LinhaAnuncio`, `produtos_para_casar`, `ofertas`, `amazon_do_produto`, `historico_amazon`)
- Modify: `src/tcg_sniper/admin/consultas_menu.py` (`contadores_menu`)
- Modify: `src/tcg_sniper/admin/consultas_painel.py` (`numeros` ~474-498)
- Modify: `src/tcg_sniper/admin/templates/produto.html:27`
- Modify: `src/tcg_sniper/admin/static/admin.css` (regenerado)
- Test: `tests/admin/test_admin_casamentos_pares.py` (novo), `tests/admin/test_consultas_painel.py`, `tests/admin/test_admin_monitor_ofertas.py`

**Interfaces:**
- Consumes (Task 1): `Casamento`, `repo_casamento.condicao_confirmado`, `repo_casamento.confirmar`, `fakes.criar_anuncio(..., origem=)`, `fakes.criar_par`.
- Produces: `consultas_amazon.LinhaAnuncio` ganha `casamento: Casamento | None = None` e `casado_com: ProdutoLiga | None = None` (no fim, com padrão; a Task 6 usa os dois). Assinaturas de `produtos_para_casar`, `ofertas`, `amazon_do_produto`, `historico_amazon`, `contadores_menu` e `numeros` não mudam.

- [ ] **Step 1: Banco da lane**

Run (de dentro do worktree): `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_t5`

- [ ] **Step 2: Testes (falham)**

Crie `tests/admin/test_admin_casamentos_pares.py`:

```python
import base64
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, criar_anuncio, criar_par, criar_preco_liga, criar_produto
from fastapi.testclient import TestClient

from tcg_sniper.admin import consultas_amazon, consultas_menu
from tcg_sniper.admin import consultas_painel as painel
from tcg_sniper.admin.app import criar_app
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db.models import Envio, OrigemCasamento, OrigemPreco, StatusCasamento

SP = ZoneInfo("America/Sao_Paulo")
PENDENTE, CONFIRMADO, IGNORADO = StatusCasamento.PENDENTE, StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def preco(s, anuncio, valor, origem=OrigemPreco.BUSCA):
    repo_amz.registrar_preco(s, anuncio.id, Decimal(valor), origem, None, Envio.AMAZON, T0, SP)


def test_lista_conta_por_par_um_anuncio_em_dois_produtos(s):
    jogo, colec = criar_produto(s, "jogo", nome="Caixa de Jogo"), criar_produto(s, "colec", nome="Caixa Colecionador")
    for p in (jogo, colec):
        criar_preco_liga(s, p, "1000.00")
    anuncio = criar_anuncio(s, "B0LISTA001", produto=colec, status=IGNORADO, origem=OrigemCasamento.MANUAL)
    criar_par(s, anuncio, jogo)  # o mesmo anúncio pendente para o Jogo
    preco(s, anuncio, "700.00")
    linhas = {
        l.produto.liga_id: (l.pendentes, l.confirmados, l.ignorados, l.oportunidade)
        for l in consultas_amazon.produtos_para_casar(
            s, busca="", categoria=None, situacao="todos", com_preco=False, desconto_min_pct=25
        )
    }
    assert linhas == {"jogo": (1, 0, 0, True), "colec": (0, 0, 1, False)}
    assert consultas_menu.contadores_menu(s, T0).casamentos == 1


def test_dashboard_conta_pares(s, config):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    anuncio = criar_anuncio(s, "B0PAINEL01", produto=p, status=CONFIRMADO, origem=OrigemCasamento.MANUAL)
    criar_par(s, anuncio, q, status=IGNORADO, origem=OrigemCasamento.OUTRO_CONFIRMADO, revisado_em=T0)
    criar_anuncio(s, "B0PAINEL02", produto=q)
    n = painel.numeros(s, T0, config)
    assert (n.confirmados, n.pendentes, n.ignorados, n.produtos_com_par) == (1, 1, 1, 1)


def test_ofertas_e_produto_usam_o_par_confirmado_e_a_origem_dele(s):
    sugerido, certo = criar_produto(s, "sugerido", nome="Produto Sugerido"), criar_produto(s, "certo", nome="Produto Certo")
    for p in (sugerido, certo):
        criar_preco_liga(s, p, "1000.00", listagem_em=T0)
    anuncio = criar_anuncio(s, "B0OFERTA01", produto=sugerido)
    repo_casamento.confirmar(s, anuncio.id, certo.id, T0, OrigemCasamento.AUTOMATICO_IA)
    preco(s, anuncio, "700.00", OrigemPreco.PRODUTO)
    [linha] = consultas_amazon.ofertas(s, consultas_amazon.FiltroOfertas(), repo_amz.obter_config(s))
    assert (linha.produto.liga_id, linha.origem_casamento) == ("certo", OrigemCasamento.AUTOMATICO_IA)
    [no_produto] = consultas_amazon.amazon_do_produto(s, certo.id, repo_amz.obter_config(s), T0)
    assert no_produto.casamento.origem is OrigemCasamento.AUTOMATICO_IA
    assert consultas_amazon.amazon_do_produto(s, sugerido.id, repo_amz.obter_config(s), T0) == []
    assert [a for _, a in consultas_amazon.historico_amazon(s, certo.id)] == ["B0OFERTA01"]
    assert consultas_amazon.historico_amazon(s, sugerido.id) == []


def test_tela_do_produto_mostra_a_origem_do_par(sessoes, cliente):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "tela", nome="Produto Tela")
        criar_anuncio(s, "B0TELA0001", produto=p, status=CONFIRMADO, origem=OrigemCasamento.AUTOMATICO_IA)
        produto_id = p.id
    resposta = cliente.get(f"/produto/{produto_id}")
    assert resposta.status_code == 200 and "automático pela IA" in resposta.text
```

Em `tests/admin/test_consultas_painel.py::test_numeros_de_casamentos_e_ia`, troque o laço das avaliações para não ler `anuncio.produto_id`:

```python
    for anuncio, produto, mesmo, aplicada in (
        (confirmado, ativo, True, AGORA), (pendente, ativo, True, None), (pendente2, inativo, False, None)
    ):
        s.add(AvaliacaoIA(
            anuncio_id=anuncio.id, produto_id=produto.id, mesmo_produto=mesmo, confianca=80, motivo="m",
            modelo="gpt-5", assinatura="a", sem_imagem=False, avaliado_em=AGORA, aplicada_em=aplicada,
        ))
```

Em `tests/admin/test_admin_monitor_ofertas.py`: troque `a = criar_anuncio(s, "B0DNV55QBS", produto=p, status=StatusCasamento.CONFIRMADO)` + `a.origem_casamento = OrigemCasamento.AUTOMATICO_IA` por `a = criar_anuncio(s, "B0DNV55QBS", produto=p, status=StatusCasamento.CONFIRMADO, origem=OrigemCasamento.AUTOMATICO_IA)`; o mesmo para o `OrigemCasamento.MANUAL` (~linha 99).

- [ ] **Step 3: Rodar para ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t5 uv run pytest -q -p no:cacheprovider tests/admin/test_admin_casamentos_pares.py`
Expected: FAIL (contagens pela coluna antiga; `LinhaAnuncio` sem `casamento`).

- [ ] **Step 4: Consultas**

Em `src/tcg_sniper/admin/consultas_amazon.py`, imports: `Casamento` nos modelos e `from tcg_sniper.db import repositorio_casamento as repo_casamento`.

`LinhaAnuncio` ganha, no fim:

```python
    casamento: Casamento | None = None  # o par (anúncio, produto da tela)
    casado_com: ProdutoLiga | None = None  # par `outro_confirmado`: o produto para o qual o anúncio é confirmado
```

Em `produtos_para_casar`, troque as três consultas do bloco `if precos_liga:` por:

```python
        consulta_contagens = (
            select(Casamento.produto_id, Casamento.status, func.count())
            .where(Casamento.produto_id.in_(precos_liga))
            .group_by(Casamento.produto_id, Casamento.status)
        )
        for produto_id, situacao_par, quantidade in s.execute(consulta_contagens):
            contagens[(produto_id, situacao_par)] = quantidade
        consulta_precos = (
            select(Casamento.produto_id, PrecoAtualAmazon.preco)
            .join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == Casamento.anuncio_id)
            .where(Casamento.produto_id.in_(precos_liga), Casamento.status == StatusCasamento.PENDENTE)
        )
        for produto_id, preco in s.execute(consulta_precos):
            if atinge_desconto(preco, precos_liga[produto_id], desconto_min_pct):
                oportunidade.add(produto_id)
        consulta_ia = (
            select(Casamento.produto_id, func.count())
            .join(
                AvaliacaoIA,
                and_(AvaliacaoIA.anuncio_id == Casamento.anuncio_id, AvaliacaoIA.produto_id == Casamento.produto_id),
            )
            .where(
                Casamento.produto_id.in_(precos_liga),
                Casamento.status == StatusCasamento.PENDENTE,
                AvaliacaoIA.mesmo_produto.is_(True),
            )
            .group_by(Casamento.produto_id)
        )
        ia_sugere = dict(s.execute(consulta_ia).all())
```

e na docstring "com as contagens de anúncios da Amazon" vira "com as contagens de pares (anúncio da Amazon × produto)".

Em `ofertas`: `condicoes = [PrecoAtualAmazon.preco.is_not(None)]` e a consulta:

```python
    consulta = (
        select(AnuncioAmazon, ProdutoLiga, PrecoAtualAmazon, VendedorAmazon, PrecoAtualLiga.preco_a_partir, Casamento.origem)
        .join(Casamento, repo_casamento.condicao_confirmado(AnuncioAmazon.id))
        .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
        .join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAtualAmazon.vendedor_id)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(*condicoes)
    )
```

o laço `for anuncio, produto, atual, vendedor, preco_liga in s.execute(consulta):` passa a desempacotar `..., preco_liga, origem` e guarda `origem` na tupla de `aceitas` (último elemento); os laços seguintes desempacotam o elemento a mais e `LinhaOferta(... origem_casamento=origem, ...)` (no lugar de `anuncio.origem_casamento`).

`amazon_do_produto`:

```python
    consulta = (
        select(AnuncioAmazon, PrecoAtualAmazon, VendedorAmazon, Casamento)
        .join(
            Casamento,
            and_(
                Casamento.anuncio_id == AnuncioAmazon.id,
                Casamento.produto_id == produto_id,
                Casamento.status == StatusCasamento.CONFIRMADO,
            ),
        )
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAtualAmazon.vendedor_id)
        .order_by(PrecoAtualAmazon.preco.nulls_last(), AnuncioAmazon.id)
    )
    regras = Regras.de(config)
    linhas = [
        LinhaAnuncio(anuncio, atual, vendedor, False, *_selo_do_vendedor(atual, vendedor, regras), casamento=par)
        for anuncio, atual, vendedor, par in s.execute(consulta)
    ]
    return _com_ofertas(s, linhas, config, agora)
```

`historico_amazon`:

```python
    consulta = (
        select(PrecoAmazon, AnuncioAmazon.asin)
        .join(AnuncioAmazon, AnuncioAmazon.id == PrecoAmazon.anuncio_id)
        .join(
            Casamento,
            and_(
                Casamento.anuncio_id == AnuncioAmazon.id,
                Casamento.produto_id == produto_id,
                Casamento.status == StatusCasamento.CONFIRMADO,
            ),
        )
        .order_by(PrecoAmazon.coletado_em.desc(), PrecoAmazon.id.desc())
        .limit(limite)
    )
```

Em `src/tcg_sniper/admin/consultas_menu.py` (troque `AnuncioAmazon` por `Casamento` no import):

```python
    casamentos = s.scalar(
        select(func.count(func.distinct(Casamento.produto_id)))
        .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
        .where(Casamento.status == StatusCasamento.PENDENTE, ProdutoLiga.ativo.is_(True))
    )
```

e o comentário do campo: `casamentos: int  # produtos ativos com par pendente`.

Em `src/tcg_sniper/admin/consultas_painel.py::numeros` (acrescente `Casamento` ao import):

```python
    por_status = dict(s.execute(select(Casamento.status, func.count()).group_by(Casamento.status)).all())
    produtos_com_par = s.scalar(
        select(func.count(func.distinct(Casamento.produto_id)))
        .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
        .where(Casamento.status == StatusCasamento.CONFIRMADO, ProdutoLiga.ativo.is_(True))
    ) or 0
    esperando = s.scalar(
        select(func.count())
        .select_from(AvaliacaoIA)
        .join(
            Casamento,
            and_(Casamento.anuncio_id == AvaliacaoIA.anuncio_id, Casamento.produto_id == AvaliacaoIA.produto_id),
        )
        .where(
            Casamento.status == StatusCasamento.PENDENTE,
            AvaliacaoIA.mesmo_produto.is_(True),
            AvaliacaoIA.aplicada_em.is_(None),
        )
    ) or 0
```

(tire `AnuncioAmazon` do import se ficar sem uso.)

Em `src/tcg_sniper/admin/templates/produto.html` (linha do ASIN), troque `{{ selo_origem(anuncio.origem_casamento) }}` por `{{ selo_origem(l.casamento.origem if l.casamento else None) }}`.

- [ ] **Step 5: CSS**

Run: `uv run python scripts/gerar_css.py`
Expected: `src/tcg_sniper/admin/static/admin.css` regravado (hash dos templates na 1ª linha).

- [ ] **Step 6: Rodar os testes da tarefa**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t5 uv run pytest -q -p no:cacheprovider tests/admin`
Expected: PASS (se um teste da tela de Casamentos posta uma ação pela rota antiga e depois confere a contagem nova, porte-o para `repo_casamento`; a rota muda na Task 6).

- [ ] **Step 7: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t5 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde.

- [ ] **Step 8: Commit**

```bash
git add src/tcg_sniper/admin/consultas_amazon.py src/tcg_sniper/admin/consultas_menu.py src/tcg_sniper/admin/consultas_painel.py src/tcg_sniper/admin/templates/produto.html src/tcg_sniper/admin/static/admin.css tests/admin
git commit -m "feat: admin lists, menu, dashboard, offers and product page count pairs"
```

---

### Task 6: Admin — tela do produto em Casamentos, ações por par, trocar e botões (lane `admin`, depois da Task 5)

**Files:**
- Modify: `src/tcg_sniper/admin/consultas_amazon.py` (`DetalheCasamento`, `detalhe_casamento`, `sugestoes_para`)
- Modify: `src/tcg_sniper/admin/app.py` (`MENSAGENS_CASAMENTO` ~106, `_tela_produto_casamento` ~926, `link_manual` ~957, `revisar_casamento` ~976, `trocar_casamento` ~1003; rotas novas `rebuscar`, `reavaliar`, `termos`)
- Modify: `src/tcg_sniper/admin/templates/casamentos_produto.html`, `trocar.html`, `_componentes.html` (`selo_origem`)
- Modify: `src/tcg_sniper/admin/static/admin.css` (regenerado)
- Test: `tests/admin/test_admin_casamento_acoes.py` (novo), `tests/admin/test_admin_casamentos.py`, `tests/admin/test_admin_casamentos_ia.py`

**Interfaces:**
- Consumes (Task 1): `repo_casamento.confirmar`, `ignorar`, `desfazer`, `trocar`, `obter_par`, `confirmado_do_anuncio`, `reavaliar_produto`, `JaConfirmado`; `repo_termos.termos_do_produto`, `pedir_termos`, `guardar_termos`; `repo_amz.priorizar_na_fila`, `repo_amz.casar_link_manual` (Task 1); `repo.solicitar_execucao`, `repo.consumir_solicitacao`. (Task 5): `LinhaAnuncio.casamento`, `LinhaAnuncio.casado_com`.
- Produces:
  - `consultas_amazon.DetalheCasamento(produto, preco_liga, pendentes, confirmados, ignorados, termos: tuple[TermoBusca, ...] = (), termos_pedidos_em: datetime | None = None)`.
  - `consultas_amazon.sugestoes_para(s, anuncio, limite: int = 3, excluir: Collection[int] = ()) -> list[tuple[ProdutoLiga, Decimal | None]]`.
  - `app.MENSAGENS_CASAMENTO: dict[str, tuple[str, str]]` (chave → (tipo do alerta, texto)); `app.com_mensagem(destino: str, chave: str) -> str`.
  - Rotas: `POST /casamentos/{anuncio_id}` com `acao` ∈ {confirmar, ignorar, desfazer, trocar} e `produto_id` obrigatório; `GET /casamentos/{anuncio_id}/trocar?de=<produto_id>&busca=`; `POST /casamentos/produto/{produto_id}/rebuscar`, `/reavaliar`, `/termos` (formulário com `voltar`; redirecionam para a tela do produto com `msg`).

- [ ] **Step 1: Banco da lane**

Run (de dentro do worktree): `docker exec tcg-sniper-postgres-teste-1 createdb -U tcg tcg_test_t6`

- [ ] **Step 2: Testes (falham)**

Crie `tests/admin/test_admin_casamento_acoes.py`:

```python
import base64
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fakes import T0, criar_anuncio, criar_par, criar_produto
from fastapi.testclient import TestClient

from tcg_sniper.admin import consultas_amazon
from tcg_sniper.admin.app import criar_app
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db import repositorio_termos as repo_termos
from tcg_sniper.db.models import COLETOR_CASADOR, AnuncioAmazon, Casamento, FilaAmazon, OrigemCasamento, ProdutoLiga, StatusCasamento

PENDENTE, CONFIRMADO, IGNORADO = StatusCasamento.PENDENTE, StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO
MANUAL, OUTRO = OrigemCasamento.MANUAL, OrigemCasamento.OUTRO_CONFIRMADO


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


def _cliente(sessoes, config, **extra):
    c = config.model_copy(update={"admin_senha": "segredo", **extra})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


@pytest.fixture
def cliente(sessoes, config):
    return _cliente(sessoes, config)


@pytest.fixture
def dois(sessoes):
    """Um anúncio pendente para "Caixa de Jogo" e para "Caixa Colecionador"; os dois na fila."""
    with sessoes() as s, s.begin():
        jogo = criar_produto(s, "jogo", nome="Caixa de Jogo")
        colec = criar_produto(s, "colec", nome="Caixa Colecionador")
        anuncio = criar_anuncio(s, "B0ACAO0001", produto=jogo)
        criar_par(s, anuncio, colec)
        repo_amz.sincronizar_fila(s, T0)
        return {"jogo": jogo.id, "colec": colec.id, "anuncio": anuncio.id}


def situacao(sessoes, anuncio_id, produto_id):
    with sessoes() as s:
        par = s.get(Casamento, (anuncio_id, produto_id))
        return par.status, par.origem


def acao(cliente, ids, nome_acao, produto):
    voltar = f"/casamentos/produto/{ids[produto]}"
    dados = {"acao": nome_acao, "produto_id": str(ids[produto]), "voltar": voltar}
    return cliente.post(f"/casamentos/{ids['anuncio']}", data=dados, follow_redirects=False)


def msg(resposta):
    return parse_qs(urlsplit(resposta.headers["location"]).query).get("msg")


def test_confirmar_ignora_o_par_do_outro_produto(cliente, sessoes, dois):
    r = acao(cliente, dois, "confirmar", "colec")
    assert (r.status_code, r.headers["location"]) == (303, f"/casamentos/produto/{dois['colec']}")
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (CONFIRMADO, MANUAL)
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (IGNORADO, OUTRO)


def test_ignorar_vale_so_para_o_par(cliente, sessoes, dois):
    acao(cliente, dois, "ignorar", "jogo")
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (IGNORADO, MANUAL)
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (PENDENTE, None)


def test_confirmar_anuncio_ja_confirmado_mostra_erro_e_nao_muda(cliente, sessoes, dois):
    with sessoes() as s, s.begin():
        repo_casamento.confirmar(s, dois["anuncio"], dois["colec"], T0)
        par = s.get(Casamento, (dois["anuncio"], dois["jogo"]))  # a tela do Jogo ainda mostrava o pendente
        par.status, par.origem, par.revisado_em = PENDENTE, None, None
    r = acao(cliente, dois, "confirmar", "jogo")
    assert msg(r) == ["ja_confirmado"]
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (PENDENTE, None)
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (CONFIRMADO, MANUAL)
    assert "já está confirmado para outro produto" in cliente.get(r.headers["location"]).text


def test_desfazer_reabre_o_par_do_outro_produto(cliente, sessoes, dois):
    acao(cliente, dois, "confirmar", "colec")
    acao(cliente, dois, "desfazer", "colec")
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (PENDENTE, None)
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (PENDENTE, None)
    with sessoes() as s:
        assert s.get(Casamento, (dois["anuncio"], dois["colec"])).reavaliar is True


def test_trocar_confirma_o_novo_e_ignora_o_anterior_como_manual(cliente, sessoes, dois):
    with sessoes() as s, s.begin():
        terceiro = criar_produto(s, "terceiro", nome="Caixa Terceira").id
    acao(cliente, dois, "confirmar", "colec")
    dados = {"acao": "trocar", "produto_id": str(terceiro), "voltar": f"/casamentos/produto/{terceiro}"}
    r = cliente.post(f"/casamentos/{dois['anuncio']}", data=dados, follow_redirects=False)
    assert r.status_code == 303
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (IGNORADO, MANUAL)
    assert situacao(sessoes, dois["anuncio"], terceiro) == (CONFIRMADO, MANUAL)


def test_acao_sem_produto_id_400_e_par_inexistente_404(cliente, sessoes, dois):
    assert cliente.post(f"/casamentos/{dois['anuncio']}", data={"acao": "ignorar"}).status_code == 400
    with sessoes() as s, s.begin():
        sem_par = criar_produto(s, "sem-par").id
    r = cliente.post(f"/casamentos/{dois['anuncio']}", data={"acao": "ignorar", "produto_id": str(sem_par)})
    assert r.status_code == 404


def test_tela_mostra_casado_com_o_outro_produto_sem_desfazer(cliente, sessoes, dois):
    with sessoes() as s, s.begin():
        repo_casamento.confirmar(s, dois["anuncio"], dois["colec"], T0)
    texto = cliente.get(f"/casamentos/produto/{dois['jogo']}").text
    assert "casado com" in texto and "Caixa Colecionador" in texto
    assert f'href="/casamentos/produto/{dois["colec"]}"' in texto
    assert 'value="desfazer"' not in texto


def test_tela_tem_os_tres_botoes_e_os_termos(cliente, sessoes, dois):
    with sessoes() as s, s.begin():
        repo_termos.guardar_termos(s, dois["jogo"], [("caixa jogo alfa", "pt"), ("alpha play box", "en")], T0)
    texto = cliente.get(f"/casamentos/produto/{dois['jogo']}").text
    for trecho in ("Rebuscar agora", "Reavaliar com a IA", "Gerar termos de busca", "caixa jogo alfa", "alpha play box"):
        assert trecho in texto


def test_rebuscar_poe_o_produto_na_frente_da_fila(cliente, sessoes, dois):
    with sessoes() as s, s.begin():
        s.get(FilaAmazon, dois["jogo"]).proxima_busca_em = T0 + timedelta(days=3)
    r = cliente.post(f"/casamentos/produto/{dois['jogo']}/rebuscar", data={"voltar": "/casamentos"}, follow_redirects=False)
    assert msg(r) == ["rebuscar"]
    with sessoes() as s:
        assert s.get(FilaAmazon, dois["jogo"]).proxima_busca_em < T0 + timedelta(days=3)


def test_reavaliar_mexe_so_nos_pares_do_produto_e_pede_o_casador(cliente, sessoes, dois):
    with sessoes() as s, s.begin():
        repo_casamento.ignorar(s, dois["anuncio"], dois["jogo"], T0, OrigemCasamento.AUTOMATICO_IA)
        repo_casamento.ignorar(s, dois["anuncio"], dois["colec"], T0, OrigemCasamento.AUTOMATICO_IA)
        manual = criar_anuncio(s, "B0ACAO0002", produto=s.get(ProdutoLiga, dois["jogo"]), status=IGNORADO, origem=MANUAL)
        manual_id = manual.id
    r = cliente.post(f"/casamentos/produto/{dois['jogo']}/reavaliar", data={"voltar": "/casamentos"}, follow_redirects=False)
    assert msg(r) == ["reavaliar"]
    assert situacao(sessoes, dois["anuncio"], dois["jogo"]) == (PENDENTE, None)
    assert situacao(sessoes, dois["anuncio"], dois["colec"]) == (IGNORADO, OrigemCasamento.AUTOMATICO_IA)
    assert situacao(sessoes, manual_id, dois["jogo"]) == (IGNORADO, MANUAL)
    with sessoes() as s, s.begin():
        assert repo.consumir_solicitacao(s, T0, COLETOR_CASADOR) is True


def test_gerar_termos_registra_o_pedido_e_avisa_o_estado_da_ia(sessoes, config, dois):
    desligada = _cliente(sessoes, config)
    r = desligada.post(f"/casamentos/produto/{dois['jogo']}/termos", data={"voltar": "/casamentos"}, follow_redirects=False)
    assert msg(r) == ["termos_ia_desligada"]
    with sessoes() as s:
        assert s.get(FilaAmazon, dois["jogo"]).termos_pedidos_em is not None
    with sessoes() as s, s.begin():
        repo_ia.salvar_config_ia(s, {"ligado": True}, T0)
    ligada = _cliente(sessoes, config, openai_api_key="sk-teste")
    r = ligada.post(f"/casamentos/produto/{dois['colec']}/termos", data={"voltar": "/casamentos"}, follow_redirects=False)
    assert msg(r) == ["termos_pedidos"]
    with sessoes() as s, s.begin():
        assert repo.consumir_solicitacao(s, T0, COLETOR_CASADOR) is True
        fora = criar_produto(s, "fora-da-fila").id
    r = ligada.post(f"/casamentos/produto/{fora}/termos", data={"voltar": "/casamentos"}, follow_redirects=False)
    assert msg(r) == ["termos_fora_da_fila"]


def test_trocar_nao_sugere_o_produto_de_onde_veio(sessoes, dois):
    with sessoes() as s, s.begin():
        anuncio = s.get(AnuncioAmazon, dois["anuncio"])
        anuncio.titulo = "Caixa de Jogo Colecionador"
        s.flush()
        ids = {p.id for p, _ in consultas_amazon.sugestoes_para(s, anuncio, excluir={dois["jogo"]})}
    assert dois["jogo"] not in ids
```

Porte `tests/admin/test_admin_casamentos.py` (todas as ações passam a mandar `produto_id`; leituras pelo par):
- imports: `Casamento` nos modelos e `from tcg_sniper.db import repositorio_casamento as repo_casamento`;
- `test_link_manual...` (~139): `assert s.get(Casamento, (anuncio.id, c.id)).status is StatusCasamento.CONFIRMADO`;
- `test_link_manual_invalido_nao_grava` (~155): `assert s.scalar(select(Casamento).where(Casamento.produto_id == cenario["c"].id)) is None`;
- `test_acoes_voltam_para_o_destino` (~165-170): `data={"acao": "ignorar", "produto_id": str(cenario["a"].id), "voltar": voltar}` e `assert s.get(Casamento, (alfa.id, cenario["a"].id)).status is StatusCasamento.IGNORADO`;
- os testes parametrizados de `voltar` que postam ações: acrescente `"produto_id": str(<produto do par>)` ao `data`;
- testes de trocar que chamam `consultas_amazon.sugestoes_para(s, anuncio)` continuam (o `excluir` tem padrão);
- `test_confirmar_para_produto_inativo_404_e_nao_grava` (~245): `assert s.get(Casamento, (alfa.id, cenario["a"].id)).status is StatusCasamento.PENDENTE` e `assert s.get(Casamento, (alfa.id, cenario["e"].id)) is None`;
- origens (~330): `assert s.get(Casamento, (avaliado_id, <produto>)).origem is OrigemCasamento.SUGERIDO_IA` e o mesmo para `MANUAL` (o produto é o do cenário daquele teste).

Em `tests/admin/test_admin_casamentos_ia.py::avaliar`, troque as duas linhas que mexem no anúncio por:

```python
        par = s.get(Casamento, (anuncio.id, produto.id))
        par.revisado_em = revisado  # o automático grava os dois no mesmo instante
        par.origem = OrigemCasamento.AUTOMATICO_IA if revisado == T0 else OrigemCasamento.MANUAL
```

(e importe `Casamento`); qualquer `POST /casamentos/{id}` desse arquivo ganha `produto_id`.

- [ ] **Step 3: Rodar para ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t6 uv run pytest -q -p no:cacheprovider tests/admin/test_admin_casamento_acoes.py tests/admin/test_admin_casamentos.py tests/admin/test_admin_casamentos_ia.py`
Expected: FAIL (rotas novas 404/405; ações pela coluna antiga).

- [ ] **Step 4: Consultas da tela**

Em `src/tcg_sniper/admin/consultas_amazon.py` (imports: `from collections.abc import Collection, Sequence`, `FilaAmazon`, `OrigemCasamento`, `TermoBusca` nos modelos, `from tcg_sniper.db import repositorio_termos as repo_termos`):

```python
@dataclass(frozen=True)
class DetalheCasamento:
    produto: ProdutoLiga
    preco_liga: Decimal | None
    pendentes: list[LinhaAnuncio]
    confirmados: list[LinhaAnuncio]
    ignorados: list[LinhaAnuncio]
    termos: tuple[TermoBusca, ...] = ()  # termos de busca alternativos guardados
    termos_pedidos_em: datetime | None = None  # "Gerar termos de busca" esperando o casador


def detalhe_casamento(
    s: Session, produto_id: int, config: ConfigAmazon, agora: datetime | None = None
) -> DetalheCasamento | None:
    """Os pares do produto, por status. Par `outro_confirmado` traz o produto para o qual o anúncio é
    confirmado (`casado_com`)."""
    agora = agora or repo.agora_utc()
    produto = s.get(ProdutoLiga, produto_id)
    if produto is None or not produto.ativo:
        return None
    liga = s.get(PrecoAtualLiga, produto_id)
    preco_liga = liga.preco_a_partir if liga else None
    consulta = (
        select(Casamento, AnuncioAmazon, PrecoAtualAmazon, VendedorAmazon)
        .join(AnuncioAmazon, AnuncioAmazon.id == Casamento.anuncio_id)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAtualAmazon.vendedor_id)
        .where(Casamento.produto_id == produto_id)
        .order_by(PrecoAtualAmazon.preco.nulls_last(), AnuncioAmazon.id)
    )
    regras = Regras.de(config)
    grupos: dict[StatusCasamento, list[LinhaAnuncio]] = {situacao: [] for situacao in StatusCasamento}
    for par, anuncio, atual, vendedor in s.execute(consulta):
        oportunidade = atinge_desconto(atual.preco if atual else None, preco_liga, config.desconto_min_pct)
        confiavel, verificado = _selo_do_vendedor(atual, vendedor, regras)
        grupos[par.status].append(
            LinhaAnuncio(anuncio, atual, vendedor, oportunidade, confiavel, verificado, casamento=par)
        )
    todas = [linha for linhas in grupos.values() for linha in linhas]
    avaliacoes = repo_ia.avaliacoes_dos_pares(s, [(linha.anuncio.id, produto_id) for linha in todas])
    for situacao, linhas in grupos.items():
        grupos[situacao] = [replace(linha, ia=avaliacoes.get((linha.anuncio.id, produto_id))) for linha in linhas]
    outros = [l.anuncio.id for l in grupos[StatusCasamento.IGNORADO] if l.casamento.origem is OrigemCasamento.OUTRO_CONFIRMADO]
    casados: dict[int, ProdutoLiga] = {}
    if outros:
        casados = dict(
            s.execute(
                select(Casamento.anuncio_id, ProdutoLiga)
                .join(ProdutoLiga, ProdutoLiga.id == Casamento.produto_id)
                .where(Casamento.anuncio_id.in_(outros), Casamento.status == StatusCasamento.CONFIRMADO)
            ).all()
        )
    ignorados = [replace(l, casado_com=casados.get(l.anuncio.id)) for l in grupos[StatusCasamento.IGNORADO]]
    pendentes = grupos[StatusCasamento.PENDENTE]
    pendentes.sort(key=lambda linha: -(linha.ia.confianca if linha.ia and linha.ia.mesmo_produto else -1))
    confirmados = _com_ofertas(s, grupos[StatusCasamento.CONFIRMADO], config, agora)
    fila = s.get(FilaAmazon, produto_id)
    return DetalheCasamento(
        produto, preco_liga, pendentes, confirmados, ignorados,
        termos=tuple(repo_termos.termos_do_produto(s, produto_id)),
        termos_pedidos_em=fila.termos_pedidos_em if fila else None,
    )
```

Em `sugestoes_para`, mude a assinatura e a exclusão:

```python
def sugestoes_para(
    s: Session, anuncio: AnuncioAmazon, limite: int = 3, excluir: Collection[int] = ()
) -> list[tuple[ProdutoLiga, Decimal | None]]:
    """Até `limite` produtos do catálogo com nome parecido com o título do anúncio (difflib), sem os de
    `excluir` (o produto de onde você veio e o já confirmado). Cada produto concorre com o nome em
    português e com o nome em inglês (quando há); vale o que parecer mais com o título."""
```

e, no fim, `ids = list(dict.fromkeys(por_nome[nome] for nome in parecidos if por_nome[nome] not in excluir))[:limite]`.

- [ ] **Step 5: Rotas**

Em `src/tcg_sniper/admin/app.py` (imports: `from tcg_sniper.db import repositorio_casamento as repo_casamento`, `from tcg_sniper.db import repositorio_termos as repo_termos`):

```python
MENSAGENS_CASAMENTO: dict[str, tuple[str, str]] = {
    "link_salvo": ("success", "Link salvo; o anúncio será lido em alguns minutos."),
    "ja_confirmado": ("error", "Este anúncio já está confirmado para outro produto; nada mudou."),
    "rebuscar": ("success", "Produto na frente da fila da Amazon; a busca roda em alguns minutos."),
    "reavaliar": ("success", "Pares marcados para a IA reavaliar; o casador roda em instantes."),
    "reavaliar_nada": ("info", "Nada para reavaliar: só pendentes e ignorados pela IA voltam para ela."),
    "termos_pedidos": ("success", "Pedido enviado: a IA gera os termos de busca em instantes, dentro do teto de gasto."),
    "termos_ia_desligada": (
        "warning",
        "Pedido guardado, mas a IA está desligada (Configurações → IA) ou sem chave: os termos saem quando ela for ligada.",
    ),
    "termos_fora_da_fila": ("warning", "O produto ainda não entrou na fila da Amazon; tente de novo em alguns minutos."),
}


def com_mensagem(destino: str, chave: str) -> str:
    """Acrescenta `msg=<chave>` ao destino (que pode já ter parâmetros)."""
    return destino + ("&" if "?" in destino else "?") + urlencode({"msg": chave})
```

Em `_tela_produto_casamento`, o parâmetro `mensagem` passa a ser `tuple[str, str] | None` (sem mudar o resto). Em `link_manual`, nada muda além do `MENSAGENS_CASAMENTO.get(msg)` na rota GET (já devolve a tupla).

Troque `revisar_casamento` por:

```python
    @app.post("/casamentos/{anuncio_id}")
    async def revisar_casamento(request: Request, anuncio_id: int):
        """Ação sobre o par (anúncio, produto_id). A regra fica em `repositorio_casamento`."""
        formulario = await ler_formulario(request)
        acao = formulario.get("acao", "")
        if acao not in ("confirmar", "ignorar", "desfazer", "trocar"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"ação inválida: {acao}")
        texto = formulario.get("produto_id", "").strip()
        if not (texto.isdecimal() and len(texto) <= 9):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "produto_id inválido")
        produto_id = int(texto)
        destino = destino_seguro(formulario.get("voltar", "/casamentos"))
        agora = repo.agora_utc()
        with sessoes() as s, s.begin():
            if s.get(AnuncioAmazon, anuncio_id) is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            if acao in ("confirmar", "trocar"):
                alvo = s.get(ProdutoLiga, produto_id)
                if alvo is None or not alvo.ativo:
                    raise HTTPException(status.HTTP_404_NOT_FOUND)
            elif repo_casamento.obter_par(s, anuncio_id, produto_id) is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            origem = repo_ia.origem_da_decisao(s, anuncio_id, produto_id)
            try:
                if acao == "confirmar":
                    repo_casamento.confirmar(s, anuncio_id, produto_id, agora, origem)
                elif acao == "trocar":
                    repo_casamento.trocar(s, anuncio_id, produto_id, agora, origem)
                elif acao == "ignorar":
                    repo_casamento.ignorar(s, anuncio_id, produto_id, agora, origem)
                else:
                    repo_casamento.desfazer(s, anuncio_id, produto_id, agora)
            except repo_casamento.JaConfirmado:
                destino = com_mensagem(destino, "ja_confirmado")
        return RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)
```

Troque `trocar_casamento` por:

```python
    @app.get("/casamentos/{anuncio_id}/trocar", response_class=HTMLResponse)
    def trocar_casamento(request: Request, anuncio_id: int, busca: str = "", de: int | None = None):
        with sessoes() as s, s.begin():
            anuncio = s.get(AnuncioAmazon, anuncio_id)
            if anuncio is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            confirmado = repo_casamento.confirmado_do_anuncio(s, anuncio_id)
            excluir = {i for i in (de, confirmado.produto_id if confirmado else None) if i is not None}
            return templates.TemplateResponse(
                request,
                "trocar.html",
                {
                    "anuncio": anuncio,
                    "busca": busca,
                    "de": de,
                    "confirmado_em": s.get(ProdutoLiga, confirmado.produto_id) if confirmado else None,
                    "sugestoes": consultas_amazon.sugestoes_para(s, anuncio, excluir=excluir),
                    "produtos": consultas_amazon.buscar_produtos(s, busca) if busca.strip() else [],
                },
            )
```

Acrescente os três botões (antes do `return app`):

```python
    def _produto_ativo_ou_404(s: Session, produto_id: int) -> ProdutoLiga:
        produto = s.get(ProdutoLiga, produto_id)
        if produto is None or not produto.ativo:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        return produto

    def _volta_ao_produto(produto_id: int, voltar: str, chave: str) -> RedirectResponse:
        destino = f"/casamentos/produto/{produto_id}?" + urlencode({"voltar": destino_seguro(voltar), "msg": chave})
        return RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/casamentos/produto/{produto_id}/rebuscar")
    async def rebuscar_produto(request: Request, produto_id: int):
        formulario = await ler_formulario(request)
        with sessoes() as s, s.begin():
            _produto_ativo_ou_404(s, produto_id)
            repo_amz.priorizar_na_fila(s, produto_id, repo.agora_utc())
        return _volta_ao_produto(produto_id, formulario.get("voltar", "/casamentos"), "rebuscar")

    @app.post("/casamentos/produto/{produto_id}/reavaliar")
    async def reavaliar_produto(request: Request, produto_id: int):
        formulario = await ler_formulario(request)
        agora = repo.agora_utc()
        with sessoes() as s, s.begin():
            _produto_ativo_ou_404(s, produto_id)
            marcados = repo_casamento.reavaliar_produto(s, produto_id, agora)
            if marcados:
                repo.solicitar_execucao(s, agora, COLETOR_CASADOR)
        chave = "reavaliar" if marcados else "reavaliar_nada"
        return _volta_ao_produto(produto_id, formulario.get("voltar", "/casamentos"), chave)

    @app.post("/casamentos/produto/{produto_id}/termos")
    async def gerar_termos_produto(request: Request, produto_id: int):
        formulario = await ler_formulario(request)
        agora = repo.agora_utc()
        with sessoes() as s, s.begin():
            _produto_ativo_ou_404(s, produto_id)
            pedido = repo_termos.pedir_termos(s, produto_id, agora)
            if pedido:
                repo.solicitar_execucao(s, agora, COLETOR_CASADOR)
            ligada = repo_ia.obter_config_ia(s).ligado and bool((config.openai_api_key or "").strip())
        if not pedido:
            chave = "termos_fora_da_fila"
        else:
            chave = "termos_pedidos" if ligada else "termos_ia_desligada"
        return _volta_ao_produto(produto_id, formulario.get("voltar", "/casamentos"), chave)
```

(`config` é o parâmetro de `criar_app` já usado em `chave_ia`; se no seu código o nome for outro, use o mesmo objeto de configuração que a linha `chave_ia = bool((config.openai_api_key or "").strip())` usa.)

- [ ] **Step 6: Templates**

Em `src/tcg_sniper/admin/templates/_componentes.html`, troque `selo_origem` por:

```html
{% macro selo_origem(origem) -%}
{%- if origem -%}
{%- set rotulos = {"manual": "manual", "sugerido_ia": "sugerido pela IA", "automatico_ia": "automático pela IA", "outro_confirmado": "outro produto"} -%}
{%- set cores = {"manual": "badge-ghost", "sugerido_ia": "badge-info badge-outline", "automatico_ia": "badge-primary badge-outline", "outro_confirmado": "badge-warning badge-outline"} -%}
<span class="badge badge-sm whitespace-nowrap {{ cores[origem.value] }}">{{ rotulos[origem.value] }}</span>
{%- endif -%}
{%- endmacro %}
```

Em `src/tcg_sniper/admin/templates/casamentos_produto.html`:
- troque `{% if mensagem %}{{ aviso("success", mensagem) }}{% endif %}` por `{% if mensagem %}{{ aviso(mensagem[0], mensagem[1]) }}{% endif %}`;
- logo depois do card do cabeçalho (antes de `{% macro botao ... %}`), acrescente o card dos botões e termos:

```html
<div class="card bg-base-100 shadow-sm"><div class="card-body gap-3">
  <h2 class="card-title text-base">Busca e IA</h2>
  <div class="flex flex-wrap gap-2">
    <form method="post" action="/casamentos/produto/{{ d.produto.id }}/rebuscar"><input type="hidden" name="voltar" value="{{ voltar }}"><button class="btn btn-sm btn-outline">Rebuscar agora</button></form>
    <form method="post" action="/casamentos/produto/{{ d.produto.id }}/reavaliar"><input type="hidden" name="voltar" value="{{ voltar }}"><button class="btn btn-sm btn-outline">Reavaliar com a IA</button></form>
    <form method="post" action="/casamentos/produto/{{ d.produto.id }}/termos"><input type="hidden" name="voltar" value="{{ voltar }}"><button class="btn btn-sm btn-outline">Gerar termos de busca</button></form>
  </div>
  <div class="text-sm">
    <span class="font-medium">Termos de busca alternativos:</span>
    {% if d.termos %}
    <ul class="list-disc pl-5">{% for t in d.termos %}<li>{{ t.termo }} <span class="badge badge-ghost badge-sm">{{ t.idioma }}</span></li>{% endfor %}</ul>
    {% else %}
    <span class="text-base-content/60">nenhum (a IA gera depois de 7 dias sem anúncio novo, ou pelo botão acima)</span>
    {% endif %}
    {% if d.termos_pedidos_em %}<p class="text-xs text-base-content/60">Pedido em {{ d.termos_pedidos_em|data }}; a IA gera no próximo ciclo do casador.</p>{% endif %}
  </div>
</div></div>
```

- troque o macro `botao` por (o par vai sempre junto):

```html
{% macro botao(anuncio, acao, rotulo, classe="btn-sm") %}
<form method="post" action="/casamentos/{{ anuncio.id }}">
  <input type="hidden" name="acao" value="{{ acao }}"><input type="hidden" name="voltar" value="{{ aqui }}">
  <input type="hidden" name="produto_id" value="{{ d.produto.id }}">
  <button class="btn {{ classe }}">{{ rotulo }}</button>
</form>
{% endmacro %}
```

- nos pendentes: `{{ botao(l.anuncio, "confirmar", "Confirmar", "btn-sm btn-success") }}` (sem `produto_id=`) e o link `href="/casamentos/{{ l.anuncio.id }}/trocar?de={{ d.produto.id }}"`;
- nos confirmados e ignorados, troque `l.anuncio.origem_casamento` por `l.casamento.origem` (as duas ocorrências em cada bloco);
- no bloco dos ignorados, troque a linha do selo e a do `card-actions` por:

```html
      {% if l.casado_com %}
      <div class="flex flex-wrap items-center gap-2 text-sm">{{ selo_origem(l.casamento.origem) }}<span>casado com <a class="link" href="/casamentos/produto/{{ l.casado_com.id }}">{{ l.casado_com.nome }}</a></span></div>
      {% else %}
      <div class="flex flex-wrap items-center gap-2">{{ selo_origem(l.casamento.origem) }}{% if l.casamento.origem and l.casamento.origem.value == "automatico_ia" and l.ia %}<span class="text-xs text-base-content/70 break-words">{{ l.ia.motivo }}</span>{% endif %}</div>
      <div class="card-actions">{{ botao(l.anuncio, "desfazer", "Desfazer", "btn-sm btn-outline") }}</div>
      {% endif %}
```

Em `src/tcg_sniper/admin/templates/trocar.html`: no formulário de `linha(p, preco)`, `value="confirmar"` vira `value="trocar"`; logo depois do card do anúncio, acrescente:

```html
{% if confirmado_em %}{{ aviso("info", "Hoje este anúncio está confirmado para " ~ confirmado_em.nome ~ "; escolher outro produto troca o casamento.") }}{% endif %}
```

(e acrescente `aviso` ao `{% from "_componentes.html" import ... %}` do topo).

- [ ] **Step 7: CSS**

Run: `uv run python scripts/gerar_css.py`
Expected: `admin.css` regravado.

- [ ] **Step 8: Rodar os testes da tarefa**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t6 uv run pytest -q -p no:cacheprovider tests/admin`
Expected: PASS.

- [ ] **Step 9: Suíte inteira e ruff**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t6 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde.

- [ ] **Step 10: Commit**

```bash
git add src/tcg_sniper/admin tests/admin
git commit -m "feat: per-pair actions, swap, rerun search, re-evaluate and search terms buttons in the matching screen"
```

---

### Task 7: Remove as colunas antigas, regressão dos números, guarda global e documentação

**Files:**
- Modify: `src/tcg_sniper/db/migrations/versions/a9d4f2c6e8b1_casamento_por_par.py` (remoção e volta das colunas antigas)
- Modify: `src/tcg_sniper/db/models.py` (saem `AnuncioAmazon.produto_id/status_casamento/revisado_em/origem_casamento` e `FilaAmazon.ultimo_termo_en`)
- Modify: `src/tcg_sniper/db/repositorio_amazon.py` (saem `confirmar_casamento`, `ignorar_anuncio`, `desfazer_casamento` e, se sem uso, `fechar_oportunidades_do_anuncio`; `casar_link_manual` sem as linhas de transição)
- Modify: `tests/fakes.py` (`criar_anuncio` sem as colunas antigas), `tests/db/test_migracao.py`, `tests/db/test_repositorio_amazon.py`, `tests/db/test_migracao_casamento.py`
- Create: `tests/db/test_regressao_casamento_por_par.py`, `tests/test_sem_casamento_no_anuncio.py`
- Modify: `README.md`, `docs/PENDENCIAS.md`

**Interfaces:**
- Consumes: tudo das Tasks 1–6.
- Produces: nenhum código novo de produção; o banco fica só com os pares.

- [ ] **Step 1: Banco da lane**

Run: `docker compose exec -T postgres-teste createdb -U tcg tcg_test_t7` (ou `docker exec tcg-sniper-postgres-teste-1 ...` de dentro de um worktree)

- [ ] **Step 2: Testes de regressão e guarda (falham enquanto as colunas existem)**

Crie `tests/test_sem_casamento_no_anuncio.py`:

```python
import re
from pathlib import Path

from tcg_sniper.db.models import AnuncioAmazon, FilaAmazon

RAIZ = Path(__file__).resolve().parents[1] / "src" / "tcg_sniper"
PROIBIDO = re.compile(
    r"(?:AnuncioAmazon|anuncio|l\.anuncio)\.(?:produto_id|status_casamento|origem_casamento|revisado_em)\b"
    r"|ultimo_termo_en|confirmar_casamento|ignorar_anuncio|desfazer_casamento"
)


def test_colunas_antigas_do_casamento_sairam():
    for coluna in ("produto_id", "status_casamento", "origem_casamento", "revisado_em"):
        assert coluna not in AnuncioAmazon.__table__.c
    assert "ultimo_termo_en" not in FilaAmazon.__table__.c


def test_codigo_nao_le_o_casamento_pelo_anuncio():
    achados = []
    for caminho in [*RAIZ.rglob("*.py"), *RAIZ.rglob("*.html")]:
        relativo = caminho.relative_to(RAIZ).as_posix()
        if relativo.startswith("db/migrations/"):
            continue
        for numero, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), start=1):
            if PROIBIDO.search(linha):
                achados.append(f"{relativo}:{numero}: {linha.strip()}")
    assert achados == []
```

Crie `tests/db/test_regressao_casamento_por_par.py`:

```python
"""Regressão: nos dados migrados, telas e motor têm os mesmos números de antes (um par por anúncio)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import create_engine, pool, text
from sqlalchemy.orm import sessionmaker

from tcg_sniper.admin import consultas_amazon, consultas_menu
from tcg_sniper.admin import consultas_painel as painel
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.session import config_alembic

ANTES = "f8d2a6c4e1b3"
AGORA = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)


def _semear(c) -> dict[str, int]:
    """Dados no formato antigo (casamento nas colunas do anúncio), com os números conhecidos:
    p1: confirmado (automático, R$ 600 lido agora), ignorado (manual), pendente R$ 700 (oportunidade na lista);
    p2: confirmado (manual, R$ 950), pendente R$ 990; p3: ignorado (sugerido pela IA); p4: sem par;
    p5 (inativo): confirmado (manual, R$ 500). Uma oportunidade aberta (p1)."""

    def produto(liga_id, ativo=True):
        produto_id = c.scalar(
            text(
                "INSERT INTO produto_liga (liga_id, nome, url, ativo, visto_primeiro_em, visto_ultimo_em) "
                "VALUES (:l, :n, 'u', :a, :t, :t) RETURNING id"
            ),
            {"l": liga_id, "n": f"Regressão {liga_id}", "a": ativo, "t": AGORA},
        )
        c.execute(
            text("INSERT INTO preco_atual_liga (produto_id, preco_a_partir, listagem_em) VALUES (:p, 1000, :t)"),
            {"p": produto_id, "t": AGORA - timedelta(hours=1)},
        )
        return produto_id

    def anuncio(asin, produto_id, status, origem=None, preco=None, lido=False):
        anuncio_id = c.scalar(
            text(
                "INSERT INTO anuncio_amazon (asin, titulo, url, produto_id, status_casamento, origem_casamento, "
                "revisado_em, visto_primeiro_em, visto_ultimo_em) VALUES (:a, :a, 'u', :p, :s, :o, :r, :t, :t) RETURNING id"
            ),
            {
                "a": asin, "p": produto_id, "s": status, "o": origem,
                "r": None if status == "pendente" else AGORA - timedelta(days=1), "t": AGORA - timedelta(days=2),
            },
        )
        if preco is not None:  # lido = leitura do monitor agora (preço atual "ofertas" + a melhor oferta elegível)
            c.execute(
                text(
                    "INSERT INTO preco_atual_amazon (anuncio_id, preco, origem, envio, coletado_em) "
                    "VALUES (:a, :v, :o, 'amazon', :t)"
                ),
                {"a": anuncio_id, "v": preco, "o": "ofertas" if lido else "busca", "t": AGORA},
            )
            if lido:
                c.execute(
                    text(
                        "INSERT INTO oferta_amazon (anuncio_id, lida_em, vendedor_nome, preco, condicao, envio, importada, "
                        "prime, elegivel, melhor) VALUES (:a, :t, 'Amazon.com.br', :v, 'novo', 'amazon', false, false, true, true)"
                    ),
                    {"a": anuncio_id, "v": preco, "t": AGORA},
                )
        return anuncio_id

    p1, p2, p3, p4 = (produto(f"reg-{i}") for i in range(1, 5))
    p5 = produto("reg-5", ativo=False)
    a1 = anuncio("BREG000001", p1, "confirmado", "automatico_ia", Decimal("600.00"), lido=True)
    anuncio("BREG000002", p1, "ignorado", "manual")
    anuncio("BREG000003", p1, "pendente", preco=Decimal("700.00"))
    anuncio("BREG000004", p2, "confirmado", "manual", Decimal("950.00"), lido=True)
    anuncio("BREG000005", p2, "pendente", preco=Decimal("990.00"))
    anuncio("BREG000006", p3, "ignorado", "sugerido_ia")
    anuncio("BREG000007", p5, "confirmado", "manual", Decimal("500.00"), lido=True)
    c.execute(
        text(
            "INSERT INTO oportunidade (anuncio_id, produto_id, preco_amazon, preco_liga, desconto_pct, envio, aberta_em, "
            "alertada_em, preco_alertado) VALUES (:a, :p, 600, 1000, 40, 'amazon', :t, :t, 600)"
        ),
        {"a": a1, "p": p1, "t": AGORA},
    )
    return {"p1": p1, "p2": p2, "p3": p3, "p4": p4, "p5": p5}


def _limpar(c) -> None:
    anuncios = "(SELECT id FROM anuncio_amazon WHERE asin LIKE 'BREG%')"
    produtos = "(SELECT id FROM produto_liga WHERE liga_id LIKE 'reg-%')"
    for tabela in ("oportunidade", "oferta_amazon", "preco_atual_amazon", "preco_amazon", "casamento"):
        c.execute(text(f"DELETE FROM {tabela} WHERE anuncio_id IN {anuncios}"))
    c.execute(text("DELETE FROM anuncio_amazon WHERE asin LIKE 'BREG%'"))
    for tabela in ("preco_atual_liga", "fila_amazon", "termo_busca"):
        c.execute(text(f"DELETE FROM {tabela} WHERE produto_id IN {produtos}"))
    c.execute(text("DELETE FROM produto_liga WHERE liga_id LIKE 'reg-%'"))


@pytest.fixture
def migrado(engine):
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    command.downgrade(cfg, ANTES)
    try:
        with proprio.begin() as c:
            ids = _semear(c)
        command.upgrade(cfg, "head")
        yield sessionmaker(bind=proprio, expire_on_commit=False), ids
    finally:
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            _limpar(c)
        proprio.dispose()


def test_numeros_iguais_aos_de_antes_nos_dados_migrados(migrado, config):
    fabrica, ids = migrado
    with fabrica() as s:
        cfg = repo_amz.obter_config(s)
        n = painel.numeros(s, AGORA, config)
        assert (n.confirmados, n.pendentes, n.ignorados, n.produtos_com_par) == (3, 2, 2, 2)
        menu = consultas_menu.contadores_menu(s, AGORA)
        assert (menu.casamentos, menu.ofertas) == (2, 1)
        linhas = {
            l.produto.liga_id: (l.pendentes, l.confirmados, l.ignorados, l.oportunidade)
            for l in consultas_amazon.produtos_para_casar(
                s, busca="", categoria=None, situacao="todos", com_preco=False, desconto_min_pct=25
            )
            if l.produto.liga_id.startswith("reg-")
        }
        assert linhas == {
            "reg-1": (1, 1, 1, True), "reg-2": (1, 1, 0, False), "reg-3": (0, 0, 1, False), "reg-4": (0, 0, 0, False),
        }
        detalhe = consultas_amazon.detalhe_casamento(s, ids["p1"], cfg, AGORA)
        assert (len(detalhe.pendentes), len(detalhe.confirmados), len(detalhe.ignorados)) == (1, 1, 1)
        situacao = repo_amz.situacao_monitor(s, AGORA, cfg.monitor_intervalo_min)
        assert (situacao.confirmados, situacao.nunca_lidos, situacao.vencidos) == (2, 0, 0)
        assert [c.asin for c in repo_amz.candidatas_ao_checkout(s, AGORA, cfg)] == ["BREG000001"]
        ofertas = {l.anuncio.asin: l.origem_casamento.value for l in consultas_amazon.ofertas(s, consultas_amazon.FiltroOfertas(), cfg)}
        assert ofertas == {"BREG000001": "automatico_ia", "BREG000004": "manual", "BREG000007": "manual"}
```

Em `tests/db/test_migracao_casamento.py`, acrescente:

```python
def test_colunas_antigas_saem_e_voltam_no_downgrade(banco):
    cfg, proprio = banco
    with proprio.connect() as c:
        colunas = set(c.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name IN ('anuncio_amazon', 'fila_amazon')"
        )).scalars())
    assert not colunas & {"produto_id", "status_casamento", "origem_casamento", "revisado_em", "ultimo_termo_en"}
    command.downgrade(cfg, ANTES)
    with proprio.connect() as c:
        colunas = set(c.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name IN ('anuncio_amazon', 'fila_amazon')"
        )).scalars())
    assert {"produto_id", "status_casamento", "origem_casamento", "revisado_em", "ultimo_termo_en"} <= colunas
```

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t7 uv run pytest -q -p no:cacheprovider tests/test_sem_casamento_no_anuncio.py tests/db/test_migracao_casamento.py tests/db/test_regressao_casamento_por_par.py`
Expected: FAIL nos dois testes de colunas (as colunas ainda existem) e no de código (as funções antigas ainda existem); o de regressão já passa (as telas já leem os pares).

- [ ] **Step 3: Migração: remover e refazer as colunas antigas**

Em `a9d4f2c6e8b1_casamento_por_par.py`:
- no `upgrade()`, **apague** a linha `op.alter_column("anuncio_amazon", "status_casamento", ..., nullable=True)` e o comentário "Transição" acima dela; no fim do `upgrade()`, acrescente:

```python
    # A fonte do casamento é a tabela `casamento`: saem as colunas antigas (CHECKs e FK saem junto).
    for coluna in ("origem_casamento", "revisado_em", "status_casamento", "produto_id"):
        op.drop_column("anuncio_amazon", coluna)
    op.drop_column("fila_amazon", "ultimo_termo_en")
```

- troque o `downgrade()` inteiro por:

```python
def downgrade() -> None:
    op.add_column("anuncio_amazon", sa.Column("produto_id", sa.Integer(), nullable=True))
    op.create_foreign_key("anuncio_amazon_produto_id_fkey", "anuncio_amazon", "produto_liga", ["produto_id"], ["id"])
    op.add_column("anuncio_amazon", sa.Column("status_casamento", sa.String(20), nullable=True))
    op.create_check_constraint(
        "status_casamento", "anuncio_amazon", "status_casamento IN ('pendente', 'confirmado', 'ignorado')"
    )
    op.add_column("anuncio_amazon", sa.Column("revisado_em", DATA, nullable=True))
    op.add_column("anuncio_amazon", sa.Column("origem_casamento", sa.String(20), nullable=True))
    op.create_check_constraint(
        "origem_casamento", "anuncio_amazon", "origem_casamento IN ('manual', 'sugerido_ia', 'automatico_ia')"
    )
    op.add_column("fila_amazon", sa.Column("ultimo_termo_en", sa.Boolean(), server_default="false", nullable=False))
    op.execute("UPDATE fila_amazon SET ultimo_termo_en = (ultima_busca_em IS NOT NULL AND indice_termo = 0)")
    op.drop_constraint("ck_fila_amazon_indice_termo", "fila_amazon", type_="check")
    for coluna in ("termos_pedidos_em", "termos_tentados_em", "ultimo_par_novo_em", "indice_termo"):
        op.drop_column("fila_amazon", coluna)
    op.drop_table("termo_busca")
    op.execute(REFAZER_ANUNCIO)
    op.execute("UPDATE anuncio_amazon SET status_casamento = 'pendente' WHERE status_casamento IS NULL")
    op.alter_column("anuncio_amazon", "status_casamento", existing_type=sa.String(20), nullable=False)
    op.drop_table("casamento")
```

e, na docstring do módulo, troque "As colunas antigas de `anuncio_amazon` saem na Task 7 do plano (nesta mesma revisão)." por "Depois remove as colunas antigas do casamento em `anuncio_amazon` e `fila_amazon.ultimo_termo_en`; o downgrade as refaz a partir dos pares.".

- [ ] **Step 4: Modelos, repositório e fakes sem as colunas antigas**

- `models.AnuncioAmazon`: apague `produto_id`, `status_casamento`, `revisado_em`, `origem_casamento` e a segunda frase da docstring (fica "Um anúncio (ASIN) da amazon.com.br. O casamento com os produtos da Liga fica em `Casamento` (por par).").
- `models.FilaAmazon`: apague `ultimo_termo_en` e o comentário dele.
- `repositorio_amazon.py`: apague `confirmar_casamento`, `ignorar_anuncio`, `desfazer_casamento`; em `casar_link_manual`, apague o comentário "Transição" e as duas linhas de atribuição às colunas antigas (e o `s.flush()` que vinha logo depois delas); rode `git grep -n fechar_oportunidades_do_anuncio -- src tests` — se só aparecer a definição, apague `fechar_oportunidades_do_anuncio` também. Tire do import os nomes que ficarem sem uso (o `ruff` aponta).
- `tests/fakes.py::criar_anuncio`: tire `produto_id=...`, `status_casamento=...`, `origem_casamento=...` e a linha `origem_antiga = ...`; a docstring vira "Anúncio e, com `produto`, o par (anúncio, produto) com `status` e `origem`.".
- `tests/db/test_repositorio_amazon.py`: apague `test_casamento_confirmar_trocar_ignorar_desfazer` e o teste das origens que usa as funções antigas (~linhas 335-358; o comportamento está em `tests/db/test_repositorio_casamento.py`); nos testes de `casar_link_manual`, troque cada leitura de `anuncio.produto_id`/`status_casamento`/`revisado_em` por `repo_casamento.obter_par(s, anuncio.id, <produto>.id)` (status `CONFIRMADO`, `revisado_em == agora`).
- `tests/db/test_migracao.py::test_migracao_preenche_a_origem_do_casamento`: troque o `command.upgrade(cfg, "head")` que vem **antes** da leitura das origens por `command.upgrade(cfg, "f8d2a6c4e1b3")` (as colunas antigas só existem até ali; o `finally` continua subindo para `head`).

- [ ] **Step 5: Varredura do resto**

Run: `git grep -nE "status_casamento|origem_casamento|ultimo_termo_en|\.produto_id ==|anuncio\.produto_id|anuncio\.revisado_em" -- src tests ':!src/tcg_sniper/db/migrations'`
Expected: só ocorrências legítimas (o nome do CHECK `_enum(..., "status_casamento")`/`"origem_casamento"` em `Casamento`, o campo `LinhaOferta.origem_casamento` e o `ofertas.html` que o usa, e `.produto_id ==` de outras tabelas). Porte qualquer outra para os pares.

- [ ] **Step 6: README**

Em `README.md`:
- no parágrafo **Amazon.** de "Como funciona", troque "Quando a LigaMagic mostra o nome do produto em inglês, a busca alterna entre o nome em português e o nome em inglês a cada passada. Anúncios novos vão para a fila de revisão em **Casamentos**; só anúncios confirmados geram oportunidade." por:

```markdown
Quando a LigaMagic mostra o nome do produto em inglês, a busca alterna entre o nome em português e o nome em inglês a cada passada; um produto sem casamento que passa 7 dias sem achar anúncio novo ganha de 2 a 3 termos de busca alternativos sugeridos pela IA (uma vez, dentro do teto de gasto), que entram no rodízio até aparecer anúncio novo. Cada anúncio achado vira um par (anúncio × produto) pendente em **Casamentos**; ignorar vale só para aquele par (o mesmo anúncio achado na busca de outro produto volta a ser pendente para ele), e um anúncio é confirmado para no máximo um produto. Só pares confirmados geram oportunidade.
```

- no passo 9 (Casamento com IA), acrescente depois do primeiro parágrafo:

```markdown
A IA avalia cada par (anúncio × produto) pendente. **Desfazer** devolve o par para a IA, que o reavalia mesmo sem mudança no anúncio (com o automático ligado, ela pode decidir de novo; para tirar de vez, use **Ignorar**). Na tela de um produto em **Casamentos** ficam três botões: **Rebuscar agora** (põe o produto na frente da fila da Amazon), **Reavaliar com a IA** (volta para a IA os pares pendentes e os ignorados por ela; suas decisões manuais e os confirmados não mudam) e **Gerar termos de busca** (pede os termos alternativos agora; o casador gera em instantes, dentro do teto). Um anúncio confirmado em outro produto aparece como "casado com <produto>".
```

- na tabela de telas, a linha de **Casamentos** vira: `| **Casamentos** | Produtos ativos da Liga com os pares (anúncio × produto) da Amazon; confirmar, ignorar, desfazer, trocar ou colar o link à mão; rebuscar, reavaliar com a IA e gerar termos de busca; filtros por situação, categoria e nome. |`
- em "Atualizar uma instalação existente", acrescente uma subseção:

```markdown
### Implantar o casamento por par

Faça o backup de sempre antes (ver [Backup do banco](#backup-do-banco)). A migração `a9d4f2c6e8b1` cria a tabela `casamento` (um par por anúncio, com o mesmo status, origem e datas de antes), confere que nenhum anúncio ficou com dois confirmados (se ficar, aborta sem mudar nada) e remove as colunas antigas do anúncio. Depois: `docker compose run --rm migrate` e rebuild/restart de `coletor-amazon`, `casador` e `admin`.
```

- [ ] **Step 7: Pendências**

Em `docs/PENDENCIAS.md`: atualize "Última revisão" para a data do merge; tire o item do casamento da seção "## 0. Crítico (em andamento)" (se a seção ficar vazia, escreva "Nada no momento."); em "## Ordem sugerida", troque a linha "0. Seção 0 (anúncio ignorado preso ao primeiro produto) — em desenho." por "0. —"; no item **Site novo, fase 3**, acrescente ao fim: "; e os botões da tela de Casamentos (Rebuscar agora, Reavaliar com a IA, Gerar termos de busca), cuja regra já está em `repositorio_casamento`/`repositorio_termos`"; em "## 2. Acompanhar (sem código)", acrescente:

```markdown
- [ ] Primeira semana do casamento por par: quantos ignorados foram recuperados (anúncios confirmados para um produto que antes estavam ignorados para outro: `SELECT count(*) FROM casamento c WHERE c.status = 'confirmado' AND EXISTS (SELECT 1 FROM casamento o WHERE o.anuncio_id = c.anuncio_id AND o.produto_id <> c.produto_id AND o.status = 'ignorado' AND o.origem <> 'outro_confirmado')`) e quantos produtos entraram na busca alternativa (`SELECT count(DISTINCT produto_id) FROM termo_busca`).
```

e, no topo de "## Concluídas", um bloco novo (preencha os hashes com `git log --oneline` depois do merge):

```markdown
### Casamento por par e busca alternativa (2026-10-19)

- [x] Tabela `casamento` (anúncio × produto) como fonte única: ignorado vale só para o par; confirmado para no máximo um produto (índice único parcial, trava do anúncio); confirmar ignora os outros pendentes do anúncio (`outro_confirmado`) e desfazer/ignorar o confirmado os reabre (`<hash>`).
- [x] Busca cria o par com o produto buscado; casador avalia pares, Desfazer e "Reavaliar com a IA" fazem a IA reavaliar mesmo com o anúncio igual (`<hash>`).
- [x] Busca alternativa: 7 dias sem anúncio novo → a IA sugere 2–3 termos (uma vez, no teto de gasto), que entram no rodízio da fila; volta ao nome normal com anúncio novo (`<hash>`).
- [x] Monitor, checkout, oportunidades, Logs, Dashboard, Ofertas e telas de Casamentos sobre os pares; botões Rebuscar agora, Reavaliar com a IA e Gerar termos de busca (`<hash>`).
- [x] Migração com conferência e downgrade; regressão: mesmos números nos dados migrados; colunas antigas removidas (`<hash>`).
```

- [ ] **Step 8: Suíte inteira, ruff e commit**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5433/tcg_test_t7 uv run pytest -q -p no:cacheprovider` e `uv run ruff check .`
Expected: verde.

```bash
git add -A src tests README.md docs/PENDENCIAS.md
git commit -m "chore: drop the old listing match columns; regression of numbers; docs"
```

---

## Implantação (depois do merge, com ok do usuário; o controlador faz, não um subagente)

Revisado na Task 7 (ruling F2): segue o CLAUDE.md e o README → "Implantar o casamento por par".

1. Backup do banco de produção em `dados/backups/` (`tcg-antes-casamento-por-par-<data>.dump`) e conferir o arquivo.
2. Antes de migrar: `SELECT count(*) FROM anuncio_amazon WHERE produto_id IS NULL` tem de dar 0; anotar `SELECT status_casamento, count(*) FROM anuncio_amazon WHERE produto_id IS NOT NULL GROUP BY 1` (os números de referência; em 2026-10-19 eram 50 confirmados, 6 pendentes e 1269 ignorados, mas vale a contagem tirada na hora).
3. `docker compose up -d --build` (todos os serviços juntos; o `migrate` aplica `a9d4f2c6e8b1` numa transação antes). Se abortar com "mais de um casamento confirmado", nada mudou no banco: anote os ids e pare (volte o código e suba de novo).
4. Conferir: `SELECT status, count(*) FROM casamento GROUP BY status` bate com as contagens do passo 2; o Dashboard e Casamentos mostram os mesmos números; uma tela de produto mostra os três botões.
