# Reorganização do admin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separar acompanhamento (Dashboard) de comandos (Serviços), organizar Casamentos por produto da Liga com link manual da Amazon, mostrar o link da LigaMagic nas opções de troca, dar filtros a Casamentos e Ofertas, e fazer o coletor ler anúncios confirmados que não aparecem na busca.

**Architecture:** Mudanças no admin FastAPI + Jinja2 (rotas, consultas e templates) e uma mudança pequena em `coletor_amazon/busca.py`. Nenhuma tabela nova; o link manual cria um `anuncio_amazon` já confirmado e põe o produto na frente da `fila_amazon`.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, Pico CSS, SQLAlchemy 2, pytest.

**Spec:** `docs/superpowers/specs/2026-10-14-admin-reorganizacao-design.md`.

## Estado e ordem de execução

| Task | Situação |
| --- | --- |
| 1 a 5 | Pendentes |

Ondas (dentro de uma onda as tasks não mexem nos mesmos arquivos e podem rodar em paralelo):

- A: Task 1 (ASIN e repositório) e Task 3 (Dashboard e Serviços)
- B: Task 2 (coletor, depende da 1) e Task 4 (Casamentos, depende da 1 e da 3)
- C: Task 5 (Ofertas, depende da 3 e da 4: mexe nos mesmos arquivos da 4)

Cada task termina com `uv run pytest -q` e `uv run ruff check` limpos (use `uv run ruff check --fix` para a ordem dos imports; reexportação `X as X` leva `# noqa: PLC0414`). As pastas de teste não têm `__init__.py`: todo arquivo de teste novo precisa de nome único em `tests/`.

## Global Constraints

- O Dashboard (`/`) não tem nenhum botão nem formulário `POST`; todos os comandos ficam em Serviços (`/servicos`).
- As rotas de ação continuam `POST /rodar-agora`, `/retomar`, `/amazon/pausar`, `/amazon/retomar` e passam a redirecionar para `/servicos?msg=<código>`, com os códigos `rodar`, `retomar`, `amazon_pausar`, `amazon_retomar`; código desconhecido não mostra mensagem.
- Sai o link "definida em Configurações" do bloco da Amazon; Configurações continua no menu.
- Menu: Dashboard · Serviços · Catálogo · Casamentos · Ofertas · Configurações.
- Casamentos lista os produtos **ativos** da Liga, 20 por página; Ofertas, 50 por página; histórico do Dashboard, 20 por página por tabela.
- Filtros ficam na URL e são mantidos na paginação; busca por nome trata `%` e `_` como texto; valor de filtro inválido → 400.
- Link da LigaMagic sempre com `target="_blank" rel="noopener"`.
- Link manual aceita só `amazon.com.br` (com ou sem `www.`, `http`/`https`) com ASIN em `/dp/`, `/gp/product/` ou `/gp/aw/d/`, ou só o ASIN (10 caracteres `[A-Z0-9]`, aceito em minúsculas); recusa encurtadores (`amzn.to`, `a.co`, `amzn.com`) com "Abra o link e copie o endereço completo da página do produto." e o resto com "Não encontrei o código do produto (ASIN) nesse link."
- Redirecionamento por `voltar` só para caminhos que começam com `/casamentos` (e não com `//`); o resto vira `/casamentos`.
- Coletor: no máximo `MAX_CONFIRMADOS_AUSENTES = 5` anúncios confirmados ausentes da busca por busca, os de leitura mais antiga primeiro (sem leitura primeiro); cada leitura de página de produto atualiza `titulo` e `visto_ultimo_em` do anúncio.
- Identificadores e textos em português; commits em inglês (`feat:`/`fix:`/`test:`/`docs:`), terminando com a linha `Co-Authored-By`.

## Review Focus

1. **Produto ativado agora, ainda sem linha na `fila_amazon`, recebendo link manual.** Esperado: o link é salvo sem erro; a primeira sincronização da fila o põe vencido. Teste na Task 1.
2. **Link manual de um ASIN já ignorado ou já confirmado para outro produto.** Esperado: vira confirmado para este produto; oportunidades abertas do produto antigo fecham. Teste na Task 1.
3. **`voltar` com destino externo (`https://evil.test`, `//evil.test`, `/catalogo`).** Esperado: redireciona para `/casamentos`. Teste na Task 4.
4. **Página de histórico/listagem pedida além da última (`pagina=999`) ou não numérica.** Esperado: mostra a última página (ou a 1ª), nunca 500. Testes nas Tasks 3, 4 e 5.
5. **Anúncio confirmado ausente da busca cuja página não lê mais (ASIN removido).** Esperado: o erro de parser segue o fluxo atual (falha contada, HTML salvo dentro da cota) e não impede os outros anúncios já conferidos de terem sido gravados. Teste na Task 2.

---

### Task 1: ASIN a partir do link e operações de banco do link manual

**Files:**
- Create: `src/tcg_sniper/coletor_amazon/asin.py`
- Modify: `src/tcg_sniper/db/repositorio_amazon.py`
- Test: `tests/coletor_amazon/test_asin.py`, `tests/db/test_repositorio_amazon.py`

**Interfaces:**
- Produces:
  - `tcg_sniper.coletor_amazon.asin`: `LinkInvalido(ValueError)`, `MENSAGEM_ENCURTADO`, `MENSAGEM_SEM_ASIN`, `extrair_asin(texto: str) -> str`
  - `tcg_sniper.db.repositorio_amazon`: `priorizar_na_fila(s, produto_id: int, agora: datetime) -> None`; `casar_link_manual(s, produto_id: int, asin: str, agora: datetime) -> AnuncioAmazon`; `confirmados_ausentes(s, produto_id: int, asins_vistos: set[str], limite: int) -> list[tuple[int, str, str]]` (id, asin, url); `atualizar_leitura(s, anuncio_id: int, titulo: str, agora: datetime) -> None`

- [ ] **Step 1: Testes do ASIN**

`tests/coletor_amazon/test_asin.py`:

```python
import pytest

from tcg_sniper.coletor_amazon.asin import MENSAGEM_ENCURTADO, MENSAGEM_SEM_ASIN, LinkInvalido, extrair_asin


@pytest.mark.parametrize(
    ("texto", "asin"),
    [
        ("https://www.amazon.com.br/dp/B0DTMQBLSY", "B0DTMQBLSY"),
        ("https://www.amazon.com.br/MTG-Final-Fantasy-Play-Booster/dp/B0DTMQBLSY/ref=sr_1_1?k=x", "B0DTMQBLSY"),
        ("https://www.amazon.com.br/gp/product/B0DTMQBLSY?psc=1", "B0DTMQBLSY"),
        ("https://www.amazon.com.br/gp/aw/d/B0DTMQBLSY", "B0DTMQBLSY"),
        ("http://amazon.com.br/dp/B0DTMQBLSY", "B0DTMQBLSY"),
        ("amazon.com.br/dp/b0dtmqblsy", "B0DTMQBLSY"),
        ("  https://www.amazon.com.br/dp/B0DTMQBLSY#detalhes  ", "B0DTMQBLSY"),
        ("B0DTMQBLSY", "B0DTMQBLSY"),
        ("b0dtmqblsy", "B0DTMQBLSY"),
    ],
)
def test_extrai_o_asin(texto, asin):
    assert extrair_asin(texto) == asin


@pytest.mark.parametrize("texto", ["https://amzn.to/3abcDEF", "https://a.co/d/abc123", "amzn.com/dp/B0DTMQBLSY"])
def test_recusa_link_encurtado(texto):
    with pytest.raises(LinkInvalido, match="endereço completo"):
        extrair_asin(texto)
    assert MENSAGEM_ENCURTADO.startswith("Abra o link")


@pytest.mark.parametrize(
    "texto",
    [
        "https://www.amazon.com/dp/B0DTMQBLSY",
        "https://www.mercadolivre.com.br/dp/B0DTMQBLSY",
        "https://www.amazon.com.br/s?k=magic",
        "https://www.amazon.com.br/dp/B0DT",
        "B0DT",
        "",
        "caixa de booster",
    ],
)
def test_recusa_sem_asin_ou_outro_dominio(texto):
    with pytest.raises(LinkInvalido) as erro:
        extrair_asin(texto)
    assert str(erro.value) == MENSAGEM_SEM_ASIN
```

- [ ] **Step 2: Testes do repositório**

Acrescente a `tests/db/test_repositorio_amazon.py` (imports que faltarem: `from tcg_sniper.db.models import FilaAmazon` já existe; `Oportunidade` já existe):

```python
def test_casar_link_manual_cria_confirmado_e_prioriza_na_fila(s):
    produto = criar_produto(s, "ff")
    repo.sincronizar_fila(s, T0)
    s.get(FilaAmazon, produto.id).proxima_busca_em = T0 + timedelta(hours=1)
    s.flush()

    agora = T0 + timedelta(minutes=5)
    anuncio = repo.casar_link_manual(s, produto.id, "B0MANUAL01", agora)
    assert (anuncio.asin, anuncio.titulo, anuncio.url) == (
        "B0MANUAL01",
        "Informado manualmente",
        "https://www.amazon.com.br/dp/B0MANUAL01",
    )
    assert (anuncio.produto_id, anuncio.status_casamento, anuncio.revisado_em) == (
        produto.id,
        StatusCasamento.CONFIRMADO,
        agora,
    )
    assert (anuncio.visto_primeiro_em, anuncio.visto_ultimo_em) == (agora, agora)
    assert s.get(FilaAmazon, produto.id).proxima_busca_em == agora


def test_casar_link_manual_de_asin_conhecido_troca_o_produto_e_fecha_oportunidade(s):
    antigo = criar_produto(s, "antigo")
    novo = criar_produto(s, "novo")
    anuncio = criar_anuncio(s, "B0CONHEC01", produto=antigo, status=StatusCasamento.IGNORADO)
    op = repo.abrir_oportunidade(
        s, anuncio_id=anuncio.id, produto_id=antigo.id, preco_amazon=Decimal("1"), preco_liga=Decimal("2"),
        desconto_pct=Decimal("50"), vendedor_id=None, envio=Envio.AMAZON, agora=T0,
    )
    resultado = repo.casar_link_manual(s, novo.id, "B0CONHEC01", T0 + timedelta(hours=1))
    s.refresh(op)
    assert resultado.id == anuncio.id
    assert (resultado.produto_id, resultado.status_casamento) == (novo.id, StatusCasamento.CONFIRMADO)
    assert op.fechada_em == T0 + timedelta(hours=1)


def test_casar_link_manual_sem_linha_na_fila_nao_quebra(s):
    produto = criar_produto(s, "recem_ativado")
    anuncio = repo.casar_link_manual(s, produto.id, "B0SEMFILA1", T0)
    assert anuncio.status_casamento is StatusCasamento.CONFIRMADO
    repo.sincronizar_fila(s, T0 + timedelta(minutes=1))
    assert s.get(FilaAmazon, produto.id).proxima_busca_em == T0 + timedelta(minutes=1)


def test_confirmados_ausentes_mais_antigos_primeiro_e_com_limite(s):
    produto = criar_produto(s, "ff")
    outro = criar_produto(s, "outro")
    sem_leitura = criar_anuncio(s, "B0SEMLEIT1", produto=produto, status=StatusCasamento.CONFIRMADO)
    velho = criar_anuncio(s, "B0VELHO001", produto=produto, status=StatusCasamento.CONFIRMADO)
    novo = criar_anuncio(s, "B0NOVO0001", produto=produto, status=StatusCasamento.CONFIRMADO)
    visto = criar_anuncio(s, "B0VISTO001", produto=produto, status=StatusCasamento.CONFIRMADO)
    criar_anuncio(s, "B0PENDENT1", produto=produto)
    criar_anuncio(s, "B0OUTRO001", produto=outro, status=StatusCasamento.CONFIRMADO)
    for anuncio, quando in ((velho, T0), (novo, T0 + timedelta(hours=2)), (visto, T0)):
        repo.registrar_preco(s, anuncio.id, Decimal("10"), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, quando, SP)

    ausentes = repo.confirmados_ausentes(s, produto.id, {"B0VISTO001"}, limite=5)
    assert [asin for _, asin, _ in ausentes] == ["B0SEMLEIT1", "B0VELHO001", "B0NOVO0001"]
    assert ausentes[0] == (sem_leitura.id, "B0SEMLEIT1", sem_leitura.url)
    assert [asin for _, asin, _ in repo.confirmados_ausentes(s, produto.id, set(), limite=2)] == [
        "B0SEMLEIT1",
        "B0VELHO001",
    ]


def test_atualizar_leitura(s):
    anuncio = criar_anuncio(s, "B0LEITURA1")
    repo.atualizar_leitura(s, anuncio.id, "Título real da página", T0 + timedelta(days=2))
    s.refresh(anuncio)
    assert (anuncio.titulo, anuncio.visto_ultimo_em) == ("Título real da página", T0 + timedelta(days=2))
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/coletor_amazon/test_asin.py tests/db/test_repositorio_amazon.py -q`
Expected: FAIL (`ModuleNotFoundError: tcg_sniper.coletor_amazon.asin`, `AttributeError: ... casar_link_manual`).

- [ ] **Step 4: Implementar**

`src/tcg_sniper/coletor_amazon/asin.py`:

```python
"""Código do produto (ASIN) a partir de um link da amazon.com.br colado à mão no admin."""

import re
from urllib.parse import urlsplit

MENSAGEM_ENCURTADO = "Abra o link e copie o endereço completo da página do produto."
MENSAGEM_SEM_ASIN = "Não encontrei o código do produto (ASIN) nesse link."

_ASIN = re.compile(r"[A-Z0-9]{10}")
_CAMINHO = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Za-z0-9]{10})(?=[/?#]|$)")
_ENCURTADORES = {"amzn.to", "a.co", "amzn.com", "www.amzn.com"}
_DOMINIOS = {"amazon.com.br", "www.amazon.com.br"}


class LinkInvalido(ValueError):
    """Link que não dá para usar; a mensagem é mostrada ao usuário."""


def extrair_asin(texto: str) -> str:
    bruto = texto.strip()
    if _ASIN.fullmatch(bruto.upper()):
        return bruto.upper()
    partes = urlsplit(bruto if "://" in bruto else f"https://{bruto}")
    dominio = (partes.hostname or "").lower()
    if dominio in _ENCURTADORES:
        raise LinkInvalido(MENSAGEM_ENCURTADO)
    if dominio not in _DOMINIOS:
        raise LinkInvalido(MENSAGEM_SEM_ASIN)
    achado = _CAMINHO.search(partes.path)
    if achado is None:
        raise LinkInvalido(MENSAGEM_SEM_ASIN)
    return achado.group(1).upper()
```

Em `src/tcg_sniper/db/repositorio_amazon.py`, acrescente (imports: `true` de `sqlalchemy` se usar; o código abaixo não precisa):

```python
# --- link manual e anúncios confirmados fora da busca ----------------------------------------


def priorizar_na_fila(s: Session, produto_id: int, agora: datetime) -> None:
    """Põe o produto na frente da fila da Amazon (sem linha na fila, não faz nada: a próxima
    sincronização o insere já vencido)."""
    s.execute(update(FilaAmazon).where(FilaAmazon.produto_id == produto_id).values(proxima_busca_em=agora))
    s.flush()


def casar_link_manual(s: Session, produto_id: int, asin: str, agora: datetime) -> AnuncioAmazon:
    """Casa o ASIN informado à mão com o produto: confirma o anúncio existente (trocando de produto
    se preciso) ou cria um já confirmado; e põe o produto na frente da fila."""
    anuncio = s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.asin == asin))
    if anuncio is None:
        anuncio = AnuncioAmazon(
            asin=asin,
            titulo="Informado manualmente",
            url=f"https://www.amazon.com.br/dp/{asin}",
            produto_id=produto_id,
            status_casamento=StatusCasamento.CONFIRMADO,
            revisado_em=agora,
            visto_primeiro_em=agora,
            visto_ultimo_em=agora,
        )
        s.add(anuncio)
        s.flush()
    else:
        confirmar_casamento(s, anuncio.id, produto_id, agora)
        anuncio.visto_ultimo_em = agora
        s.flush()
    priorizar_na_fila(s, produto_id, agora)
    return anuncio


def confirmados_ausentes(
    s: Session, produto_id: int, asins_vistos: set[str], limite: int
) -> list[tuple[int, str, str]]:
    """Anúncios confirmados do produto que não estão em `asins_vistos`, os de leitura mais antiga
    primeiro (sem leitura primeiro). Devolve (id, asin, url)."""
    condicoes = [
        AnuncioAmazon.produto_id == produto_id,
        AnuncioAmazon.status_casamento == StatusCasamento.CONFIRMADO,
    ]
    if asins_vistos:
        condicoes.append(AnuncioAmazon.asin.not_in(asins_vistos))
    consulta = (
        select(AnuncioAmazon.id, AnuncioAmazon.asin, AnuncioAmazon.url)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .where(*condicoes)
        .order_by(PrecoAtualAmazon.coletado_em.asc().nulls_first(), AnuncioAmazon.id)
        .limit(limite)
    )
    return [(anuncio_id, asin, url) for anuncio_id, asin, url in s.execute(consulta)]


def atualizar_leitura(s: Session, anuncio_id: int, titulo: str, agora: datetime) -> None:
    """Título lido na página do produto e "visto por último" (vale para anúncios fora da busca)."""
    s.execute(
        update(AnuncioAmazon).where(AnuncioAmazon.id == anuncio_id).values(titulo=titulo, visto_ultimo_em=agora)
    )
    s.flush()
```

- [ ] **Step 5: Rodar**

Run: `uv run pytest -q && uv run ruff check`
Expected: tudo passa. Se `test_casar_link_manual_cria_confirmado_e_prioriza_na_fila` ler um `proxima_busca_em` antigo por causa do objeto em memória, troque o `s.get` final por `s.get(FilaAmazon, produto.id, populate_existing=True)`.

- [ ] **Step 6: Commit**

```bash
git add src/tcg_sniper/coletor_amazon/asin.py src/tcg_sniper/db/repositorio_amazon.py tests/coletor_amazon/test_asin.py tests/db/test_repositorio_amazon.py
git commit -m "feat: ASIN from a pasted Amazon link and manual match repository operations"
```

---

### Task 2: Coletor lê anúncios confirmados que não aparecem na busca

**Files:**
- Modify: `src/tcg_sniper/coletor_amazon/busca.py`
- Test: `tests/coletor_amazon/test_busca.py`

**Interfaces:**
- Consumes: `repo.confirmados_ausentes`, `repo.atualizar_leitura` (Task 1).
- Produces: `MAX_CONFIRMADOS_AUSENTES = 5` em `coletor_amazon/busca.py`; `processar_produto` devolve candidatos + ausentes conferidos.

- [ ] **Step 1: Testes**

Acrescente a `tests/coletor_amazon/test_busca.py` (usa os helpers do arquivo: `produto`, `contexto`, `busca`, `AGORA`, `NOME`; imports que faltarem: `from tcg_sniper.coletor_amazon.busca import MAX_CONFIRMADOS_AUSENTES`, `from tcg_sniper.db.models import OrigemPreco, Envio` se ainda não houver):

```python
def test_confirmado_ausente_da_busca_tem_a_pagina_lida_e_o_titulo_atualizado(sessoes, config, produto):
    with sessoes() as s, s.begin():
        manual = repo.casar_link_manual(s, produto.id, "B0MANUAL01", AGORA - timedelta(hours=1))
        url = url_busca(repo.obter_config(s), NOME)
    paginas = {
        url: busca(url, cartao_busca("B01", "Outra coisa", "R$ 100,00")),
        url_produto("B0MANUAL01"): pagina_html(
            html_produto_amazon("Caixa FF lida na página", "R$ 699,90", "Amazon.com.br", "Amazon.com.br")
        ),
    }
    ctx, navegador, notificador = contexto(sessoes, config, paginas)
    assert processar_produto(ctx, produto) == 1
    assert navegador.visitadas == [url, url_produto("B0MANUAL01")]
    with sessoes() as s:
        lido = s.get(AnuncioAmazon, manual.id)
    assert (lido.titulo, lido.visto_ultimo_em) == ("Caixa FF lida na página", AGORA)
    [(destino, texto)] = notificador.mensagens
    assert destino is Destino.OPORTUNIDADES and "R$ 699,90" in texto


def test_no_maximo_5_ausentes_por_busca_os_mais_antigos_primeiro(sessoes, config, produto):
    asins = [f"B0AUSENT{i:02d}" for i in range(7)]
    with sessoes() as s, s.begin():
        url = url_busca(repo.obter_config(s), NOME)
        for i, asin in enumerate(asins):
            anuncio = criar_anuncio(s, asin, produto=produto, status=StatusCasamento.CONFIRMADO)
            if i > 0:  # o 0 nunca foi lido; os demais, do mais antigo (1) ao mais novo (6)
                repo.registrar_preco(
                    s, anuncio.id, Decimal("900.00"), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO,
                    AGORA - timedelta(hours=10 - i), config.zona,
                )
    paginas = {url: busca(url)}
    for asin in asins:
        paginas[url_produto(asin)] = pagina_html(html_produto_amazon(f"Item {asin}", "R$ 900,00", "Loja", "Loja"))
    ctx, navegador, _ = contexto(sessoes, config, paginas)
    assert processar_produto(ctx, produto) == MAX_CONFIRMADOS_AUSENTES == 5
    assert navegador.visitadas == [url] + [url_produto(a) for a in asins[:5]]


def test_ausente_que_ja_e_candidato_nao_e_lido_duas_vezes(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    paginas = {
        url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 700,00")),
        url_produto("B01"): pagina_html(html_produto_amazon("Caixa FF", "R$ 700,00", "Amazon.com.br", None)),
    }
    ctx, navegador, _ = contexto(sessoes, config, paginas)
    assert processar_produto(ctx, produto) == 1
    assert navegador.visitadas == [url, url_produto("B01")]


def test_ausente_cuja_pagina_nao_le_segue_o_fluxo_de_erro(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B0SUMIU001", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    paginas = {
        url: busca(url, cartao_busca("B0NOVO0001", "Novo pendente", "R$ 10,00")),
        url_produto("B0SUMIU001"): pagina_html("<html><body>página não encontrada</body></html>"),
    }
    ctx, _, _ = contexto(sessoes, config, paginas)
    with pytest.raises(ErroParser):
        processar_produto(ctx, produto)
    with sessoes() as s:  # a busca já tinha sido gravada antes da leitura que falhou
        assert s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.asin == "B0NOVO0001")) is not None
```

(imports que faltarem no arquivo: `from datetime import timedelta` já existe; `Decimal` já existe; `StatusCasamento`, `AnuncioAmazon` já existem.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/coletor_amazon/test_busca.py -q`
Expected: FAIL (`ImportError: cannot import name 'MAX_CONFIRMADOS_AUSENTES'`).

- [ ] **Step 3: Implementar**

Em `src/tcg_sniper/coletor_amazon/busca.py`:

1. Logo abaixo de `log = logging.getLogger(__name__)`:

```python
MAX_CONFIRMADOS_AUSENTES = 5  # anúncios confirmados fora da busca conferidos por busca
```

2. Troque o corpo de `processar_produto` (depois do `itens = _ler(...)`) por:

```python
    with ctx.sessoes() as s, s.begin():
        anuncios = repo.gravar_busca(s, itens, produto.id, ctx.relogio(), ctx.config.zona)
        candidatos = [
            (linha.anuncio.id, linha.anuncio.asin, linha.anuncio.url)
            for linha in repo.confirmados_com_referencia(s, [a.id for a in anuncios])
            if motor.atinge_desconto(
                linha.atual.preco, linha.liga.preco_a_partir if linha.liga else None, ctx.cfg.desconto_min_pct
            )
            or repo.oportunidade_aberta(s, linha.anuncio.id) is not None  # reconferir para poder fechar
        ]
        # Confirmados do produto que a busca não trouxe (link manual, anúncio que saiu da 1ª página).
        ausentes = repo.confirmados_ausentes(
            s, produto.id, {a.asin for a in anuncios}, MAX_CONFIRMADOS_AUSENTES
        )
    ja_conferidos = {anuncio_id for anuncio_id, _, _ in candidatos}
    conferir = candidatos + [a for a in ausentes if a[0] not in ja_conferidos]
    for anuncio_id, asin, url in conferir:
        _confirmar(ctx, anuncio_id, asin, url)
    return len(conferir)
```

e ajuste o docstring: "Devolve quantos anúncios foram conferidos na página do produto (candidatos da busca mais confirmados ausentes da busca), não quantos foram confirmados."

3. Em `_confirmar`, logo depois de `repo.registrar_preco(...)`:

```python
        repo.atualizar_leitura(s, anuncio_id, oferta.titulo, agora)
```

- [ ] **Step 4: Rodar**

Run: `uv run pytest -q && uv run ruff check`
Expected: tudo passa, inclusive os testes de busca e de varredura que já existiam.

- [ ] **Step 5: Commit**

```bash
git add src/tcg_sniper/coletor_amazon/busca.py tests/coletor_amazon/test_busca.py
git commit -m "feat: Amazon search also reads confirmed listings missing from the results"
```

---

### Task 3: Dashboard e Serviços

**Files:**
- Modify: `src/tcg_sniper/admin/consultas.py`, `src/tcg_sniper/admin/app.py`
- Modify: `src/tcg_sniper/admin/templates/base.html`, `src/tcg_sniper/admin/templates/index.html` (vira o Dashboard)
- Create: `src/tcg_sniper/admin/templates/servicos.html`
- Modify: `tests/admin/test_admin.py`, `tests/admin/test_admin_amazon.py`
- Test: `tests/admin/test_admin_dashboard.py`

**Interfaces:**
- Produces (em `tcg_sniper.admin.consultas`): `STATUS_HISTORICO = ("todos", "ok", "parcial", "falha", "pausada_desafio")`, `POR_PAGINA_HISTORICO = 20`, `paginar[T](itens: list[T], pagina: int, por_pagina: int) -> tuple[list[T], int, int]` (itens da página, página efetiva, total de páginas ≥ 1), `historico_coletas(s, tipos, status: str, pagina: int, por_pagina=20) -> tuple[list[Coleta], int, int]`, `ultima_coleta_sucesso(s, tipos) -> Coleta | None`, `ultima_coleta_finalizada(s, tipos) -> Coleta | None`
- Produces (em `tcg_sniper.admin.app`): `numero_pagina(texto: str) -> int` (módulo), `MENSAGENS_SERVICOS: dict[str, str]`, rotas `GET /` (dashboard) e `GET /servicos`

- [ ] **Step 1: Testes novos**

`tests/admin/test_admin_dashboard.py`:

```python
import base64
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fakes import T0
from fastapi.testclient import TestClient

from tcg_sniper.admin import app as modulo_app
from tcg_sniper.admin.app import criar_app
from tcg_sniper.admin.consultas import paginar
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import COLETOR_AMAZON, StatusColeta, TipoColeta

SP = ZoneInfo("America/Sao_Paulo")


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def test_paginar():
    assert paginar(list(range(45)), 3, 20) == (list(range(40, 45)), 3, 3)
    assert paginar(list(range(45)), 99, 20) == (list(range(40, 45)), 3, 3)
    assert paginar([], 1, 20) == ([], 1, 1)
    assert paginar(list(range(5)), 0, 20) == (list(range(5)), 1, 1)


def test_dashboard_nao_tem_comandos(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em /x", T0)
        repo.pausar(s, "pausado no admin", T0, COLETOR_AMAZON)
    texto = cliente.get("/").text
    assert 'method="post"' not in texto.lower()
    assert "Rodar agora" not in texto and "Retomar" not in texto and "Pausar" not in texto
    assert "desafio em /x" in texto and "pausado no admin" in texto
    assert 'href="/servicos"' in texto


def test_dashboard_sem_atalho_de_configuracoes_no_bloco_da_amazon(cliente):
    texto = cliente.get("/").text
    corpo = texto.split("</nav>", 1)[1]
    assert "/configuracoes" not in corpo


def test_dashboard_mostra_ultimas_execucoes_e_horario(cliente, sessoes):
    with sessoes() as s, s.begin():
        c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0)
        repo.finalizar_coleta(s, c.id, StatusColeta.OK, 5, 0, T0)
        ciclo = repo.iniciar_coleta(s, TipoColeta.AMAZON, T0)
        repo.finalizar_coleta(s, ciclo.id, StatusColeta.PARCIAL, 9, 1, T0)
    texto = cliente.get("/").text
    assert "Última coleta com sucesso" in texto and "10:00" in texto
    assert "Último ciclo" in texto and "parcial" in texto


def test_dashboard_amazon_fora_da_janela(cliente, monkeypatch):
    monkeypatch.setattr(modulo_app.repo, "agora_utc", lambda: datetime(2026, 10, 15, 23, 30, tzinfo=SP))
    assert "Fora da janela" in cliente.get("/").text
    monkeypatch.setattr(modulo_app.repo, "agora_utc", lambda: datetime(2026, 10, 15, 12, 0, tzinfo=SP))
    assert "Fora da janela" not in cliente.get("/").text


def test_historico_com_filtro_e_paginacao(cliente, sessoes):
    with sessoes() as s, s.begin():
        for i in range(25):
            c = repo.iniciar_coleta(s, TipoColeta.AMAZON, T0 + timedelta(hours=i))
            repo.finalizar_coleta(s, c.id, StatusColeta.FALHA if i % 5 == 0 else StatusColeta.OK, 1, 0, T0)
    pagina1 = cliente.get("/").text.split("Ciclos da Amazon", 1)[1]
    assert pagina1.count("<td>amazon</td>") == 20
    assert "amazon_pagina=2" in pagina1 and "liga_status=todos" in pagina1
    pagina2 = cliente.get("/?amazon_pagina=2").text.split("Ciclos da Amazon", 1)[1]
    assert pagina2.count("<td>amazon</td>") == 5
    alem = cliente.get("/?amazon_pagina=999").text.split("Ciclos da Amazon", 1)[1]
    assert alem.count("<td>amazon</td>") == 5
    falhas = cliente.get("/?amazon_status=falha").text.split("Ciclos da Amazon", 1)[1]
    assert falhas.count("<td>amazon</td>") == 5
    assert 'value="falha" selected' in falhas
    assert cliente.get("/?amazon_status=xyz").status_code == 400
    assert cliente.get("/?liga_pagina=abc").status_code == 200


def test_servicos_mostra_os_botoes_por_estado(cliente, sessoes):
    texto = cliente.get("/servicos").text
    assert "Rodar agora" in texto and "Pausar (Amazon)" in texto and "Retomar (Amazon)" not in texto
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em /x", T0)
        repo.pausar_por_desafio(s, "desafio em /y", T0, COLETOR_AMAZON)
    texto = cliente.get("/servicos").text
    assert "host.test:6080" in texto and "host.test:6081" in texto
    assert "Retomar (Amazon)" in texto and "Pausar (Amazon)" not in texto and "Rodar agora" not in texto


@pytest.mark.parametrize(
    ("rota", "codigo", "mensagem"),
    [
        ("/rodar-agora", "rodar", "Execução da LigaMagic solicitada"),
        ("/retomar", "retomar", "Coleta da LigaMagic retomada"),
        ("/amazon/pausar", "amazon_pausar", "Busca na Amazon pausada"),
        ("/amazon/retomar", "amazon_retomar", "Busca na Amazon retomada"),
    ],
)
def test_acoes_voltam_para_servicos_com_mensagem(cliente, rota, codigo, mensagem):
    r = cliente.post(rota, follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, f"/servicos?msg={codigo}")
    assert mensagem in cliente.get(r.headers["location"]).text


def test_servicos_ignora_mensagem_desconhecida(cliente):
    assert "<script>" not in cliente.get("/servicos?msg=<script>").text


def test_menu(cliente):
    nav = cliente.get("/").text.split("</nav>", 1)[0]
    for rotulo in ("Dashboard", "Serviços", "Catálogo", "Casamentos", "Ofertas", "Configurações"):
        assert rotulo in nav
    assert ">Status<" not in nav
```

- [ ] **Step 2: Ajustar os testes antigos que dependem da tela inicial**

Em `tests/admin/test_admin.py`:

- `test_index_mostra_estado_e_coletas`: troque `assert "Rodar agora" in r.text` por `assert "Rodar agora" in cliente.get("/servicos").text` (mantém `"<td>produtos</td>" in r.text` na `/`).
- `test_index_pausado_mostra_retomar`: troque o assert por
  ```python
  assert "desafio em /x" in r.text and 'href="/servicos"' in r.text
  servicos = cliente.get("/servicos").text
  assert "Retomar" in servicos and "host.test:6080" in servicos
  ```
- `test_retomar`: depois do `assert r.status_code == 303`, acrescente `assert r.headers["location"] == "/servicos?msg=retomar"`.
- `test_rodar_agora`: troque a primeira linha por
  ```python
  r = cliente.post("/rodar-agora", follow_redirects=False)
  assert (r.status_code, r.headers["location"]) == (303, "/servicos?msg=rodar")
  ```
- `test_index_com_coleta_rodando_mostra_andamento_e_esconde_rodar_agora`: mantenha `"Coleta em andamento" in r.text` (na `/`) e troque o segundo assert por `assert "Rodar agora" not in cliente.get("/servicos").text`.
- `test_ciclo_da_amazon_rodando_nao_conta_como_coleta_da_liga_em_andamento`: troque `cliente.get("/")` por `cliente.get("/servicos")`.

Em `tests/admin/test_admin_amazon.py`:

- `test_index_mostra_a_amazon_ativa_com_ciclo`: troque os asserts por
  ```python
  texto = cliente.get("/").text
  assert "Amazon" in texto and "Ciclo em andamento" in texto
  assert "Pausar (Amazon)" in cliente.get("/servicos").text
  ```
- `test_pausar_e_retomar_a_amazon`: troque `assert "Retomar (Amazon)" in cliente.get("/").text` por `assert "Retomar (Amazon)" in cliente.get("/servicos").text`.
- `test_index_mostra_o_captcha_da_amazon_com_o_link_do_novnc`: troque `cliente.get("/")` por `cliente.get("/servicos")`.
- `test_ciclos_da_amazon_nao_empurram_as_coletas_da_liga`: troque o corpo depois do bloco `with` por
  ```python
  texto = cliente.get("/").text
  parte_liga, parte_amazon = texto.split("Ciclos da Amazon")
  assert "Coletas da LigaMagic" in parte_liga
  assert "<td>produtos</td>" in parte_liga and "<td>amazon</td>" not in parte_liga
  assert parte_amazon.count("<td>amazon</td>") == 12
  assert "<td>produtos</td>" not in parte_amazon
  ```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/admin -q`
Expected: FAIL (`ImportError: cannot import name 'paginar'`, rotas antigas redirecionando para `/`).

- [ ] **Step 4: Consultas**

Em `src/tcg_sniper/admin/consultas.py`, acrescente (imports: `from collections.abc import Sequence` já existe; `TipoColeta`, `StatusColeta`, `Coleta` já existem):

```python
STATUS_HISTORICO = ("todos", "ok", "parcial", "falha", "pausada_desafio")
POR_PAGINA_HISTORICO = 20


def paginar[T](itens: list[T], pagina: int, por_pagina: int) -> tuple[list[T], int, int]:
    """Itens da página pedida (limitada entre 1 e a última), a página efetiva e o total de páginas."""
    paginas = max(1, -(-len(itens) // por_pagina))
    pagina = min(max(pagina, 1), paginas)
    inicio = (pagina - 1) * por_pagina
    return itens[inicio : inicio + por_pagina], pagina, paginas


def historico_coletas(
    s: Session, tipos: Sequence[TipoColeta], status: str, pagina: int, por_pagina: int = POR_PAGINA_HISTORICO
) -> tuple[list[Coleta], int, int]:
    condicoes = [Coleta.tipo.in_(tipos)]
    if status != "todos":
        condicoes.append(Coleta.status == StatusColeta(status))
    total = s.scalar(select(func.count()).select_from(Coleta).where(*condicoes)) or 0
    paginas = max(1, -(-total // por_pagina))
    pagina = min(max(pagina, 1), paginas)
    consulta = (
        select(Coleta).where(*condicoes).order_by(Coleta.id.desc()).offset((pagina - 1) * por_pagina).limit(por_pagina)
    )
    return list(s.scalars(consulta)), pagina, paginas


def ultima_coleta_sucesso(s: Session, tipos: Sequence[TipoColeta]) -> Coleta | None:
    return s.scalar(
        select(Coleta)
        .where(Coleta.tipo.in_(tipos), Coleta.status.in_([StatusColeta.OK, StatusColeta.PARCIAL]))
        .order_by(Coleta.id.desc())
        .limit(1)
    )


def ultima_coleta_finalizada(s: Session, tipos: Sequence[TipoColeta]) -> Coleta | None:
    return s.scalar(
        select(Coleta)
        .where(Coleta.tipo.in_(tipos), Coleta.finalizada_em.is_not(None))
        .order_by(Coleta.id.desc())
        .limit(1)
    )
```

Se `listar_coletas` ficar sem uso depois desta task, apague-a.

- [ ] **Step 5: Rotas**

Em `src/tcg_sniper/admin/app.py`:

1. No nível do módulo:

```python
MENSAGENS_SERVICOS = {
    "rodar": "Execução da LigaMagic solicitada; começa em até 1 minuto.",
    "retomar": "Coleta da LigaMagic retomada.",
    "amazon_pausar": "Busca na Amazon pausada.",
    "amazon_retomar": "Busca na Amazon retomada.",
}


def numero_pagina(texto: str) -> int:
    """Número de página vindo da URL; texto inválido ou gigante vale 1 (nunca 500)."""
    texto = texto.strip()
    return int(texto) if texto.isdecimal() and len(texto) <= 9 else 1
```

2. Troque a rota `index` por:

```python
    @app.get("/", response_class=HTMLResponse)
    def dashboard(
        request: Request,
        liga_status: str = "todos",
        liga_pagina: str = "1",
        amazon_status: str = "todos",
        amazon_pagina: str = "1",
    ):
        for valor in (liga_status, amazon_status):
            if valor not in consultas.STATUS_HISTORICO:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"status inválido: {valor}")
        agora = repo.agora_utc()
        tipos_amazon = (TipoColeta.AMAZON,)
        with sessoes() as s, s.begin():
            cfg = repo_amz.obter_config(s)
            hora_local = agora.astimezone(config.zona).time()
            coletas, pagina_liga, paginas_liga = consultas.historico_coletas(
                s, TIPOS_LIGA, liga_status, numero_pagina(liga_pagina)
            )
            ciclos, pagina_amazon, paginas_amazon = consultas.historico_coletas(
                s, tipos_amazon, amazon_status, numero_pagina(amazon_pagina)
            )
            parametros = {
                "liga_status": liga_status,
                "liga_pagina": pagina_liga,
                "amazon_status": amazon_status,
                "amazon_pagina": pagina_amazon,
            }

            def link(**mudancas) -> str:
                return "/?" + urlencode({**parametros, **mudancas})

            return templates.TemplateResponse(
                request,
                "index.html",
                {
                    "estado": repo.obter_estado(s),
                    "em_andamento": consultas.coleta_em_andamento(s, TIPOS_LIGA),
                    "ultima_liga": consultas.ultima_coleta_sucesso(s, TIPOS_LIGA),
                    "coleta_hora": config.coleta_hora.strftime("%H:%M"),
                    "coleta_jitter": config.coleta_jitter_min,
                    "estado_amazon": repo.obter_estado(s, coletor=COLETOR_AMAZON),
                    "ciclo_amazon": consultas_amazon.ciclo_atual(s),
                    "ultimo_ciclo": consultas.ultima_coleta_finalizada(s, tipos_amazon),
                    "fora_da_janela": not (cfg.janela_inicio <= hora_local < cfg.janela_fim),
                    "janela": f"{cfg.janela_inicio:%H:%M}–{cfg.janela_fim:%H:%M}",
                    "coletas": coletas,
                    "ciclos": ciclos,
                    "pagina_liga": pagina_liga,
                    "paginas_liga": paginas_liga,
                    "pagina_amazon": pagina_amazon,
                    "paginas_amazon": paginas_amazon,
                    "liga_status": liga_status,
                    "amazon_status": amazon_status,
                    "status_historico": consultas.STATUS_HISTORICO,
                    "link": link,
                },
            )

    @app.get("/servicos", response_class=HTMLResponse)
    def servicos(request: Request, msg: str = ""):
        with sessoes() as s, s.begin():
            return templates.TemplateResponse(
                request,
                "servicos.html",
                {
                    "estado": repo.obter_estado(s),
                    "em_andamento": consultas.coleta_em_andamento(s, TIPOS_LIGA),
                    "estado_amazon": repo.obter_estado(s, coletor=COLETOR_AMAZON),
                    "ciclo_amazon": consultas_amazon.ciclo_atual(s),
                    "host": config.host_publico,
                    "mensagem": MENSAGENS_SERVICOS.get(msg),
                },
            )
```

3. Nas quatro rotas de ação, troque `RedirectResponse("/", ...)` por `RedirectResponse("/servicos?msg=<código>", ...)`, com os códigos `retomar` (`/retomar`), `rodar` (`/rodar-agora`), `amazon_pausar` e `amazon_retomar`.

- [ ] **Step 6: Templates**

`src/tcg_sniper/admin/templates/base.html`, troque o segundo `<ul>` do `nav` por:

```html
    <ul>
      <li><a href="/">Dashboard</a></li><li><a href="/servicos">Serviços</a></li>
      <li><a href="/catalogo">Catálogo</a></li><li><a href="/casamentos">Casamentos</a></li>
      <li><a href="/ofertas">Ofertas</a></li><li><a href="/configuracoes">Configurações</a></li>
    </ul>
```

Substitua todo o `src/tcg_sniper/admin/templates/index.html` por:

```html
{% extends "base.html" %}
{% block conteudo %}
<h2>Dashboard</h2>
{% if estado.estado.value != "ativo" %}
<div class="pausado"><strong>LigaMagic pausada.</strong> {{ estado.motivo or "" }} <a href="/servicos">Ir para Serviços</a></div>
{% endif %}
{% if estado_amazon.estado.value != "ativo" %}
<div class="pausado"><strong>Amazon pausada{% if estado_amazon.estado.value == "pausado_desafio" %} (CAPTCHA pendente){% endif %}.</strong>
  {{ estado_amazon.motivo or "" }} <a href="/servicos">Ir para Serviços</a></div>
{% endif %}

<div class="grid">
  <article>
    <header><strong>LigaMagic</strong></header>
    <p>Estado: {% if estado.estado.value == "ativo" %}ativo{% else %}pausado por desafio{% endif %}{% if em_andamento %} · <strong>Coleta em andamento</strong>{% endif %}</p>
    <p>Última coleta com sucesso: {% if ultima_liga %}{{ ultima_liga.iniciada_em|data }} ({{ ultima_liga.status.value }}){% else %}—{% endif %}</p>
    <p>Coleta diária às {{ coleta_hora }} (± {{ coleta_jitter }} min)</p>
  </article>
  <article>
    <header><strong>Amazon</strong></header>
    <p>Estado:
      {% if estado_amazon.estado.value == "pausado_desafio" %}pausado (CAPTCHA pendente)
      {% elif estado_amazon.estado.value == "pausado" %}pausado
      {% elif fora_da_janela %}Fora da janela ({{ janela }})
      {% else %}ativo{% endif %}</p>
    <p>{% if ciclo_amazon %}<strong>Ciclo em andamento</strong> desde {{ ciclo_amazon.iniciada_em|data }}{% else %}Nenhum ciclo em andamento{% endif %}</p>
    <p>Último ciclo: {% if ultimo_ciclo %}{{ ultimo_ciclo.finalizada_em|data }} · {{ ultimo_ciclo.status.value }} ({{ ultimo_ciclo.produtos_ok }} ok, {{ ultimo_ciclo.produtos_falha }} falhas){% else %}—{% endif %}</p>
  </article>
</div>

{% macro historico(titulo, campo_status, campo_pagina, valor_status, linhas, pagina, paginas, vazio) %}
<h3>{{ titulo }}</h3>
<form method="get" action="/" class="filtros">
  {% for nome, valor in [("liga_status", liga_status), ("amazon_status", amazon_status)] if nome != campo_status %}
  <input type="hidden" name="{{ nome }}" value="{{ valor }}">
  {% endfor %}
  <fieldset role="group">
    <select name="{{ campo_status }}" aria-label="Status">
      {% for s in status_historico %}<option value="{{ s }}" {% if s == valor_status %}selected{% endif %}>{{ s }}</option>{% endfor %}
    </select>
    <button type="submit">Filtrar</button>
  </fieldset>
</form>
<table>
  <thead><tr><th>#</th><th>Tipo</th><th>Início</th><th>Fim</th><th>Status</th><th>OK</th><th>Falhas</th><th>Erro</th></tr></thead>
  <tbody>
  {% for c in linhas %}
    <tr>
      <td>{{ c.id }}</td><td>{{ c.tipo.value }}</td><td>{{ c.iniciada_em|data }}</td><td>{{ c.finalizada_em|data }}</td>
      <td>{{ c.status.value }}</td><td>{{ c.produtos_ok }}</td><td>{{ c.produtos_falha }}</td><td>{{ c.erro or "" }}</td>
    </tr>
  {% else %}
    <tr><td colspan="8">{{ vazio }}</td></tr>
  {% endfor %}
  </tbody>
</table>
<p>
  {% if pagina > 1 %}<a href="{{ link(**{campo_pagina: pagina - 1}) }}">← anterior</a>{% endif %}
  Página {{ pagina }} de {{ paginas }}
  {% if pagina < paginas %}<a href="{{ link(**{campo_pagina: pagina + 1}) }}">próxima →</a>{% endif %}
</p>
{% endmacro %}

{{ historico("Coletas da LigaMagic", "liga_status", "liga_pagina", liga_status, coletas, pagina_liga, paginas_liga, "Nenhuma coleta ainda.") }}
{{ historico("Ciclos da Amazon", "amazon_status", "amazon_pagina", amazon_status, ciclos, pagina_amazon, paginas_amazon, "Nenhum ciclo ainda.") }}
{% endblock %}
```

O formulário de filtro é `method="get"`; o teste de "sem comandos" procura só `method="post"`. Os links de página vêm de `link()`, que mantém os quatro parâmetros (o teste procura `amazon_pagina=2` e `liga_status=todos`). Jinja aceita `link(**{...})` e as macros enxergam as variáveis do contexto da página.

Crie `src/tcg_sniper/admin/templates/servicos.html`:

```html
{% extends "base.html" %}
{% block titulo %}Serviços · TCG Sniper{% endblock %}
{% block conteudo %}
<h2>Serviços</h2>
{% if mensagem %}<p><mark>{{ mensagem }}</mark></p>{% endif %}
<div class="grid">
  <article>
    <header><strong>LigaMagic</strong></header>
    {% if estado.estado.value == "pausado_desafio" %}
      <p class="pausado">Pausada: desafio pendente. {{ estado.motivo or "" }}<br>
      Resolva em <a href="http://{{ host }}:6080/vnc.html">http://{{ host }}:6080/vnc.html</a> e clique em Retomar.</p>
      <form method="post" action="/retomar"><button>Retomar</button></form>
    {% elif em_andamento %}
      <p>Ativa. <strong>Coleta em andamento.</strong></p>
    {% else %}
      <p>Ativa.{% if estado.execucao_solicitada %} Execução solicitada; começa em até 1 minuto.{% endif %}</p>
      <form method="post" action="/rodar-agora"><button>Rodar agora</button></form>
    {% endif %}
  </article>
  <article>
    <header><strong>Amazon</strong></header>
    {% if estado_amazon.estado.value == "pausado_desafio" %}
      <p class="pausado">Pausada: CAPTCHA pendente. {{ estado_amazon.motivo or "" }}<br>
      Resolva em <a href="http://{{ host }}:6081/vnc.html">http://{{ host }}:6081/vnc.html</a> e clique em Retomar.</p>
      <form method="post" action="/amazon/retomar"><button>Retomar (Amazon)</button></form>
    {% elif estado_amazon.estado.value == "pausado" %}
      <p class="pausado">Pausada. {{ estado_amazon.motivo or "" }}</p>
      <form method="post" action="/amazon/retomar"><button>Retomar (Amazon)</button></form>
    {% else %}
      <p>Ativa.{% if ciclo_amazon %} Ciclo em andamento desde {{ ciclo_amazon.iniciada_em|data }}.{% endif %}</p>
      <form method="post" action="/amazon/pausar"><button class="secondary">Pausar (Amazon)</button></form>
    {% endif %}
  </article>
</div>
{% endblock %}
```

- [ ] **Step 7: Rodar**

Run: `uv run pytest -q && uv run ruff check`
Expected: tudo passa.

- [ ] **Step 8: Commit**

```bash
git add src/tcg_sniper/admin tests/admin
git commit -m "feat: split the admin home into a read-only dashboard and a services page"
```

---

### Task 4: Casamentos por produto da Liga, link manual e Trocar com links

**Files:**
- Modify: `src/tcg_sniper/admin/consultas_amazon.py` (sai `LinhaCasamento`, `pendentes`, `contar_pendentes`, `revisados`; entram as consultas por produto)
- Modify: `src/tcg_sniper/admin/app.py`
- Modify: `src/tcg_sniper/admin/templates/casamentos.html` (lista por produto), `src/tcg_sniper/admin/templates/trocar.html`
- Create: `src/tcg_sniper/admin/templates/casamentos_produto.html`
- Modify: `tests/admin/test_admin_amazon.py` (sai a parte de casamentos)
- Test: `tests/admin/test_admin_casamentos.py`

**Interfaces:**
- Consumes: `extrair_asin`, `LinkInvalido` (Task 1); `repo_amz.casar_link_manual` (Task 1); `consultas.paginar`, `numero_pagina` (Task 3); `consultas.listar_categorias`, `consultas._escapar_like` (já existem); `candidatos_para`, `_normalizar`, `_tokens` (já existem em `consultas_amazon`).
- Produces (em `consultas_amazon`):
  - `SITUACOES_CASAMENTO = ("pendentes", "oportunidade", "sem_par", "casados", "todos")`, `POR_PAGINA_CASAMENTOS = 20`
  - `LinhaProdutoCasamento(produto, preco_liga, pendentes: int, confirmados: int, ignorados: int, oportunidade: bool)` com a propriedade `sem_par`
  - `produtos_para_casar(s, *, busca: str, categoria: str | None, situacao: str, com_preco: bool, desconto_min_pct: int) -> list[LinhaProdutoCasamento]`
  - `LinhaAnuncio(anuncio, atual: PrecoAtualAmazon | None, vendedor: VendedorAmazon | None, oportunidade: bool)`; `DetalheCasamento(produto, preco_liga, pendentes, confirmados, ignorados)`
  - `detalhe_casamento(s, produto_id: int, desconto_min_pct: int) -> DetalheCasamento | None` (None se inexistente ou inativo)
  - `sugestoes_para(s, anuncio: AnuncioAmazon, limite: int = 3) -> list[tuple[ProdutoLiga, Decimal | None]]`
  - `buscar_produtos(s, busca: str, limite: int = 20) -> list[tuple[ProdutoLiga, Decimal | None]]` (antes devolvia só produtos)
- Produces (em `app`): `destino_seguro(voltar: str) -> str`, `MENSAGENS_CASAMENTO`, rotas `GET /casamentos`, `GET /casamentos/produto/{id}`, `POST /casamentos/produto/{id}/link`, `POST /casamentos/{anuncio_id}` (com `voltar`), `GET /casamentos/{anuncio_id}/trocar`

- [ ] **Step 1: Testes**

`tests/admin/test_admin_casamentos.py`:

```python
import base64
from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from tcg_sniper.admin import consultas_amazon
from tcg_sniper.admin.app import criar_app, destino_seguro
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import AnuncioAmazon, Envio, FilaAmazon, OrigemPreco, PrecoAtualLiga, StatusCasamento

SP = ZoneInfo("America/Sao_Paulo")


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def anuncio_com_preco(s, asin, produto, preco, status=StatusCasamento.PENDENTE):
    anuncio = criar_anuncio(s, asin, produto=produto, status=status)
    repo_amz.registrar_preco(s, anuncio.id, Decimal(preco), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, T0, SP)
    return anuncio


@pytest.fixture
def cenario(sessoes):
    """a: pendente que seria oportunidade; b: pendente sem desconto; c: sem par; d: casado; e: inativo."""
    with sessoes() as s, s.begin():
        a = criar_produto(s, "a", nome="Caixa Alfa 100%")
        b = criar_produto(s, "b", nome="Caixa Beta")
        c = criar_produto(s, "c", nome="Caixa Gama")
        d = criar_produto(s, "d", nome="Caixa Delta")
        e = criar_produto(s, "e", nome="Caixa Inativa", ativo=False)
        for p in (a, b, c, d, e):
            criar_preco_liga(s, p, "1000.00")
        a.tipo = c.tipo = "Caixas de Boosters"
        b.tipo = d.tipo = "Bundles"
        anuncio_com_preco(s, "B0ALFA0001", a, "700.00")
        anuncio_com_preco(s, "B0BETA0001", b, "990.00")
        anuncio_com_preco(s, "B0DELTA001", d, "800.00", status=StatusCasamento.CONFIRMADO)
        anuncio_com_preco(s, "B0DELTA002", d, "900.00", status=StatusCasamento.IGNORADO)
        anuncio_com_preco(s, "B0INATIVO1", e, "10.00")
        return {"a": a, "b": b, "c": c, "d": d, "e": e}


def nomes(s, **filtros):
    padrao = {"busca": "", "categoria": None, "situacao": "pendentes", "com_preco": False, "desconto_min_pct": 25}
    return [linha.produto.nome for linha in consultas_amazon.produtos_para_casar(s, **{**padrao, **filtros})]


def test_situacoes_e_ordem(s, cenario):
    assert nomes(s) == ["Caixa Alfa 100%", "Caixa Beta"]
    assert nomes(s, situacao="oportunidade") == ["Caixa Alfa 100%"]
    assert nomes(s, situacao="sem_par") == ["Caixa Gama"]
    assert nomes(s, situacao="casados") == ["Caixa Delta"]
    assert nomes(s, situacao="todos") == ["Caixa Alfa 100%", "Caixa Beta", "Caixa Delta", "Caixa Gama"]


def test_contagens(s, cenario):
    [delta] = consultas_amazon.produtos_para_casar(
        s, busca="Delta", categoria=None, situacao="todos", com_preco=False, desconto_min_pct=25
    )
    assert (delta.pendentes, delta.confirmados, delta.ignorados, delta.oportunidade, delta.sem_par) == (
        0, 1, 1, False, False,
    )


def test_busca_categoria_e_preco(s, cenario):
    assert nomes(s, situacao="todos", busca="100%") == ["Caixa Alfa 100%"]
    assert nomes(s, situacao="todos", busca="_") == []  # _ é texto, não curinga
    assert nomes(s, situacao="todos", categoria="Bundles") == ["Caixa Beta", "Caixa Delta"]
    s.execute(update(PrecoAtualLiga).where(PrecoAtualLiga.produto_id == cenario["c"].id).values(preco_a_partir=None))
    assert "Caixa Gama" not in nomes(s, situacao="todos", com_preco=True)


def test_tela_lista_com_filtros_paginacao_e_link_da_liga(cliente, sessoes, cenario):
    texto = cliente.get("/casamentos").text
    assert "Caixa Alfa 100%" in texto and "oportunidade" in texto and "Caixa Gama" not in texto
    assert 'href="https://liga.test/produto/a" target="_blank" rel="noopener"' in texto
    assert "sem par" in cliente.get("/casamentos?situacao=sem_par").text
    assert cliente.get("/casamentos?situacao=xyz").status_code == 400
    assert cliente.get("/casamentos?categoria=Inexistente").status_code == 400
    with sessoes() as s, s.begin():
        for i in range(25):
            criar_produto(s, f"x{i}", nome=f"Extra {i:02d}")
    pagina2 = cliente.get("/casamentos?situacao=sem_par&pagina=2").text
    assert pagina2.count('href="/casamentos/produto/') == 6  # 26 sem par (Gama + 25) → 20 + 6
    assert "situacao=sem_par" in pagina2
    assert cliente.get("/casamentos?situacao=sem_par&pagina=999").status_code == 200


def test_pagina_do_produto_com_os_tres_blocos_e_voltar(cliente, cenario):
    d = cenario["d"]
    texto = cliente.get(f"/casamentos/produto/{d.id}", params={"voltar": "/casamentos?situacao=casados"}).text
    assert "B0DELTA001" in texto and "B0DELTA002" in texto and "Desfazer" in texto
    assert 'href="/casamentos?situacao=casados"' in texto
    assert 'href="https://liga.test/produto/d" target="_blank" rel="noopener"' in texto
    assert cliente.get(f"/casamentos/produto/{cenario['e'].id}").status_code == 404
    assert cliente.get("/casamentos/produto/999999").status_code == 404


def test_link_manual_valido(cliente, sessoes, cenario):
    c = cenario["c"]
    with sessoes() as s, s.begin():
        repo_amz.sincronizar_fila(s, T0)
        s.get(FilaAmazon, c.id).proxima_busca_em = T0 + timedelta(days=3650)
    r = cliente.post(
        f"/casamentos/produto/{c.id}/link",
        data={"link": "https://www.amazon.com.br/Algo/dp/B0MANUAL01?ref=x", "voltar": "/casamentos?situacao=sem_par"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    destino = urlsplit(r.headers["location"])
    assert destino.path == f"/casamentos/produto/{c.id}"
    assert parse_qs(destino.query) == {"voltar": ["/casamentos?situacao=sem_par"], "msg": ["link_salvo"]}
    assert "Link salvo" in cliente.get(r.headers["location"]).text
    with sessoes() as s:
        anuncio = s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.asin == "B0MANUAL01"))
        assert (anuncio.produto_id, anuncio.status_casamento) == (c.id, StatusCasamento.CONFIRMADO)
        assert s.get(FilaAmazon, c.id).proxima_busca_em < T0 + timedelta(days=3650)


@pytest.mark.parametrize(
    ("link", "trecho"),
    [
        ("https://amzn.to/abc", "endereço completo"),
        ("https://www.mercadolivre.com.br/x", "ASIN"),
        ("", "ASIN"),
    ],
)
def test_link_manual_invalido_nao_grava(cliente, sessoes, cenario, link, trecho):
    r = cliente.post(f"/casamentos/produto/{cenario['c'].id}/link", data={"link": link})
    assert r.status_code == 400 and trecho in r.text
    with sessoes() as s:
        assert s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.produto_id == cenario["c"].id)) is None


def test_link_manual_em_produto_inativo_404(cliente, cenario):
    r = cliente.post(f"/casamentos/produto/{cenario['e'].id}/link", data={"link": "B0MANUAL01"})
    assert r.status_code == 404


def test_acoes_voltam_para_o_destino(cliente, sessoes, cenario):
    with sessoes() as s:
        alfa = s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.asin == "B0ALFA0001"))
    voltar = f"/casamentos/produto/{cenario['a'].id}"
    r = cliente.post(f"/casamentos/{alfa.id}", data={"acao": "ignorar", "voltar": voltar}, follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, voltar)
    with sessoes() as s:
        assert s.get(AnuncioAmazon, alfa.id).status_casamento is StatusCasamento.IGNORADO


@pytest.mark.parametrize(
    ("voltar", "esperado"),
    [
        ("/casamentos?situacao=todos", "/casamentos?situacao=todos"),
        ("/casamentos/produto/3", "/casamentos/produto/3"),
        ("https://evil.test/casamentos", "/casamentos"),
        ("//evil.test/casamentos", "/casamentos"),
        ("/catalogo", "/casamentos"),
        ("/casamentos\\..\\x", "/casamentos"),
        ("", "/casamentos"),
    ],
)
def test_destino_seguro(voltar, esperado):
    assert destino_seguro(voltar) == esperado


@pytest.mark.parametrize(
    ("dados", "codigo"),
    [({"acao": "apagar"}, 400), ({"acao": "confirmar"}, 400), ({"acao": "confirmar", "produto_id": "999999"}, 404)],
)
def test_acoes_invalidas(cliente, sessoes, cenario, dados, codigo):
    with sessoes() as s:
        alfa = s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.asin == "B0ALFA0001"))
    assert cliente.post(f"/casamentos/{alfa.id}", data=dados).status_code == codigo


def test_anuncio_inexistente_404(cliente):
    assert cliente.post("/casamentos/999999", data={"acao": "ignorar"}).status_code == 404


def test_trocar_mostra_links_da_liga_e_escolher_volta_para_o_produto_escolhido(cliente, sessoes, cenario):
    with sessoes() as s:
        alfa = s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.asin == "B0ALFA0001"))
    texto = cliente.get(f"/casamentos/{alfa.id}/trocar", params={"busca": "Gama"}).text
    assert 'href="https://liga.test/produto/c" target="_blank" rel="noopener"' in texto
    assert "R$ 1.000,00" in texto
    assert f'name="voltar" value="/casamentos/produto/{cenario["c"].id}"' in texto
    assert cliente.get("/casamentos/999999/trocar").status_code == 404


def test_sugestoes_para_acha_parecidos_e_exclui_o_atual(s):
    alvo = criar_produto(s, "alvo", nome="Caixa de Booster Magic Zulu Colecionador Plus")
    atual = criar_produto(s, "atual", nome="Caixa de Booster Magic Zulu Colecionador")
    for i in range(300):
        criar_produto(s, f"g{i}", nome=f"Caixa de Booster Magic Generico {i:03d}")
    anuncio = criar_anuncio(s, "B0ZULU0001", produto=atual)
    anuncio.titulo = "Magic Zulu Colecionador Plus Booster Box"
    s.flush()
    sugestoes = consultas_amazon.sugestoes_para(s, anuncio)
    assert sugestoes[0][0].id == alvo.id
    assert all(p.id != atual.id for p, _ in sugestoes) and len(sugestoes) <= 3
```

Remova de `tests/admin/test_admin_amazon.py` os testes da fila antiga: `test_pendentes_com_oportunidade_aparecem_primeiro_e_com_alternativas`, `test_tela_de_casamentos_e_acoes`, `test_trocar_busca_produtos_do_catalogo`, `test_acoes_invalidas`, `test_anuncio_inexistente_404`, `test_pendentes_com_catalogo_grande_acha_as_alternativas_certas` e `test_aba_revisados_mostra_contagem_de_pendentes` (os equivalentes estão no arquivo novo). `test_candidatos_para_ignora_tokens_genericos_e_cai_para_todos` fica. Apague os imports que ficarem sem uso.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/admin/test_admin_casamentos.py -q`
Expected: FAIL (`ImportError: cannot import name 'destino_seguro'`).

- [ ] **Step 3: Consultas**

Em `src/tcg_sniper/admin/consultas_amazon.py`, apague `LinhaCasamento`, `contar_pendentes`, `pendentes`, `revisados` e a `buscar_produtos` atual, e acrescente (mantendo `_normalizar`, `_tokens`, `FREQUENCIA_MAXIMA_TOKEN` e `candidatos_para`):

```python
SITUACOES_CASAMENTO = ("pendentes", "oportunidade", "sem_par", "casados", "todos")
POR_PAGINA_CASAMENTOS = 20


@dataclass(frozen=True)
class LinhaProdutoCasamento:
    produto: ProdutoLiga
    preco_liga: Decimal | None
    pendentes: int
    confirmados: int
    ignorados: int
    oportunidade: bool  # algum pendente já está a pelo menos o desconto mínimo abaixo da Liga

    @property
    def sem_par(self) -> bool:
        return self.pendentes == 0 and self.confirmados == 0


_FILTROS_SITUACAO = {
    "pendentes": lambda linha: linha.pendentes > 0,
    "oportunidade": lambda linha: linha.oportunidade,
    "sem_par": lambda linha: linha.sem_par,
    "casados": lambda linha: linha.confirmados > 0,
    "todos": lambda linha: True,
}


def produtos_para_casar(
    s: Session, *, busca: str, categoria: str | None, situacao: str, com_preco: bool, desconto_min_pct: int
) -> list[LinhaProdutoCasamento]:
    """Produtos ativos da Liga com as contagens de anúncios da Amazon, filtrados e ordenados:
    com pendente que seria oportunidade, depois com pendentes, depois os demais; por nome."""
    condicoes = [ProdutoLiga.ativo.is_(True)]
    if busca.strip():
        condicoes.append(ProdutoLiga.nome.ilike(f"%{_escapar_like(busca.strip())}%", escape="\\"))
    if categoria:
        condicoes.append(ProdutoLiga.tipo == categoria)
    if com_preco:
        condicoes.append(PrecoAtualLiga.preco_a_partir.is_not(None))
    produtos = s.execute(
        select(ProdutoLiga, PrecoAtualLiga.preco_a_partir)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(*condicoes)
    ).all()
    precos_liga = {produto.id: preco for produto, preco in produtos}
    contagens: dict[tuple[int, StatusCasamento], int] = {}
    oportunidade: set[int] = set()
    if precos_liga:
        consulta_contagens = (
            select(AnuncioAmazon.produto_id, AnuncioAmazon.status_casamento, func.count())
            .where(AnuncioAmazon.produto_id.in_(precos_liga))
            .group_by(AnuncioAmazon.produto_id, AnuncioAmazon.status_casamento)
        )
        for produto_id, situacao_anuncio, quantidade in s.execute(consulta_contagens):
            contagens[(produto_id, situacao_anuncio)] = quantidade
        consulta_precos = (
            select(AnuncioAmazon.produto_id, PrecoAtualAmazon.preco)
            .join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
            .where(
                AnuncioAmazon.produto_id.in_(precos_liga),
                AnuncioAmazon.status_casamento == StatusCasamento.PENDENTE,
            )
        )
        for produto_id, preco in s.execute(consulta_precos):
            if atinge_desconto(preco, precos_liga[produto_id], desconto_min_pct):
                oportunidade.add(produto_id)
    linhas = [
        LinhaProdutoCasamento(
            produto=produto,
            preco_liga=preco,
            pendentes=contagens.get((produto.id, StatusCasamento.PENDENTE), 0),
            confirmados=contagens.get((produto.id, StatusCasamento.CONFIRMADO), 0),
            ignorados=contagens.get((produto.id, StatusCasamento.IGNORADO), 0),
            oportunidade=produto.id in oportunidade,
        )
        for produto, preco in produtos
    ]
    linhas = [linha for linha in linhas if _FILTROS_SITUACAO[situacao](linha)]
    linhas.sort(key=lambda linha: (not linha.oportunidade, linha.pendentes == 0, linha.produto.nome, linha.produto.id))
    return linhas


@dataclass(frozen=True)
class LinhaAnuncio:
    anuncio: AnuncioAmazon
    atual: PrecoAtualAmazon | None
    vendedor: VendedorAmazon | None
    oportunidade: bool


@dataclass(frozen=True)
class DetalheCasamento:
    produto: ProdutoLiga
    preco_liga: Decimal | None
    pendentes: list[LinhaAnuncio]
    confirmados: list[LinhaAnuncio]
    ignorados: list[LinhaAnuncio]


def detalhe_casamento(s: Session, produto_id: int, desconto_min_pct: int) -> DetalheCasamento | None:
    produto = s.get(ProdutoLiga, produto_id)
    if produto is None or not produto.ativo:
        return None
    liga = s.get(PrecoAtualLiga, produto_id)
    preco_liga = liga.preco_a_partir if liga else None
    consulta = (
        select(AnuncioAmazon, PrecoAtualAmazon, VendedorAmazon)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAtualAmazon.vendedor_id)
        .where(AnuncioAmazon.produto_id == produto_id)
        .order_by(PrecoAtualAmazon.preco.nulls_last(), AnuncioAmazon.id)
    )
    grupos: dict[StatusCasamento, list[LinhaAnuncio]] = {situacao: [] for situacao in StatusCasamento}
    for anuncio, atual, vendedor in s.execute(consulta):
        oportunidade = atinge_desconto(atual.preco if atual else None, preco_liga, desconto_min_pct)
        grupos[anuncio.status_casamento].append(LinhaAnuncio(anuncio, atual, vendedor, oportunidade))
    return DetalheCasamento(
        produto,
        preco_liga,
        grupos[StatusCasamento.PENDENTE],
        grupos[StatusCasamento.CONFIRMADO],
        grupos[StatusCasamento.IGNORADO],
    )


def _com_preco_liga(s: Session, ids: list[int]) -> list[tuple[ProdutoLiga, Decimal | None]]:
    if not ids:
        return []
    linhas = s.execute(
        select(ProdutoLiga, PrecoAtualLiga.preco_a_partir)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(ProdutoLiga.id.in_(ids))
    ).all()
    por_id = {produto.id: (produto, preco) for produto, preco in linhas}
    return [por_id[i] for i in ids if i in por_id]


def sugestoes_para(s: Session, anuncio: AnuncioAmazon, limite: int = 3) -> list[tuple[ProdutoLiga, Decimal | None]]:
    """Até `limite` produtos do catálogo com nome parecido com o título do anúncio (difflib),
    sem o produto ao qual o anúncio já está ligado."""
    por_nome: dict[str, int] = {}
    indice: dict[str, set[str]] = {}
    for produto_id, nome in s.execute(select(ProdutoLiga.id, ProdutoLiga.nome).order_by(ProdutoLiga.id)):
        normalizado = _normalizar(nome)
        if por_nome.setdefault(normalizado, produto_id) != produto_id:
            continue
        for token in _tokens(normalizado):
            indice.setdefault(token, set()).add(normalizado)
    titulo = _normalizar(anuncio.titulo)
    candidatos = candidatos_para(titulo, list(por_nome), indice)
    parecidos = difflib.get_close_matches(titulo, candidatos, n=limite + 1, cutoff=0.3)
    ids = [por_nome[nome] for nome in parecidos if por_nome[nome] != anuncio.produto_id][:limite]
    return _com_preco_liga(s, ids)


def buscar_produtos(s: Session, busca: str, limite: int = 20) -> list[tuple[ProdutoLiga, Decimal | None]]:
    consulta = select(ProdutoLiga.id).order_by(ProdutoLiga.nome).limit(limite)
    if busca.strip():
        consulta = consulta.where(ProdutoLiga.nome.ilike(f"%{_escapar_like(busca.strip())}%", escape="\\"))
    return _com_preco_liga(s, list(s.scalars(consulta)))
```

- [ ] **Step 4: Rotas**

Em `src/tcg_sniper/admin/app.py`:

1. Imports: `from tcg_sniper.coletor_amazon.asin import LinkInvalido, extrair_asin`.
2. No nível do módulo:

```python
MENSAGENS_CASAMENTO = {"link_salvo": "Link salvo; o anúncio será lido em alguns minutos."}


def destino_seguro(voltar: str) -> str:
    """Só volta para telas de Casamentos (nunca para fora do admin)."""
    if voltar.startswith("/casamentos") and not voltar.startswith("//") and "\\" not in voltar:
        return voltar
    return "/casamentos"
```

3. Apague `ABAS_CASAMENTO` e as rotas `casamentos`, `revisar_casamento` e `trocar_casamento` atuais, e acrescente:

```python
    @app.get("/casamentos", response_class=HTMLResponse)
    def casamentos(
        request: Request,
        busca: str = "",
        categoria: str = "",
        situacao: str = "pendentes",
        com_preco: str = "",
        pagina: str = "1",
    ):
        if situacao not in consultas_amazon.SITUACOES_CASAMENTO:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"situação inválida: {situacao}")
        so_com_preco = com_preco == "1"
        with sessoes() as s, s.begin():
            categorias = consultas.listar_categorias(s)
            if categoria and categoria not in categorias:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"categoria inválida: {categoria}")
            cfg = repo_amz.obter_config(s)
            linhas = consultas_amazon.produtos_para_casar(
                s,
                busca=busca,
                categoria=categoria or None,
                situacao=situacao,
                com_preco=so_com_preco,
                desconto_min_pct=cfg.desconto_min_pct,
            )
            linhas_pagina, numero, paginas = consultas.paginar(
                linhas, numero_pagina(pagina), consultas_amazon.POR_PAGINA_CASAMENTOS
            )
            parametros = {"busca": busca, "categoria": categoria, "situacao": situacao}
            if so_com_preco:
                parametros["com_preco"] = "1"
            parametros = {k: v for k, v in parametros.items() if v}

            def link(destino: int) -> str:
                return "/casamentos?" + urlencode({**parametros, "pagina": destino})

            return templates.TemplateResponse(
                request,
                "casamentos.html",
                {
                    "linhas": linhas_pagina,
                    "total": len(linhas),
                    "pagina": numero,
                    "paginas": paginas,
                    "link": link,
                    "voltar_atual": link(numero),
                    "busca": busca,
                    "categoria": categoria,
                    "categorias": categorias,
                    "situacao": situacao,
                    "situacoes": consultas_amazon.SITUACOES_CASAMENTO,
                    "com_preco": so_com_preco,
                },
            )

    def _tela_produto_casamento(
        request: Request, s: Session, produto_id: int, voltar: str, mensagem: str | None, erro: str | None,
        link_digitado: str, codigo: int,
    ):
        cfg = repo_amz.obter_config(s)
        detalhe = consultas_amazon.detalhe_casamento(s, produto_id, cfg.desconto_min_pct)
        if detalhe is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        voltar = destino_seguro(voltar)
        return templates.TemplateResponse(
            request,
            "casamentos_produto.html",
            {
                "d": detalhe,
                "voltar": voltar,
                "aqui": f"/casamentos/produto/{produto_id}?" + urlencode({"voltar": voltar}),
                "mensagem": mensagem,
                "erro": erro,
                "link_digitado": link_digitado,
            },
            status_code=codigo,
        )

    @app.get("/casamentos/produto/{produto_id}", response_class=HTMLResponse)
    def casamento_produto(request: Request, produto_id: int, voltar: str = "/casamentos", msg: str = ""):
        with sessoes() as s, s.begin():
            return _tela_produto_casamento(
                request, s, produto_id, voltar, MENSAGENS_CASAMENTO.get(msg), None, "", status.HTTP_200_OK
            )

    @app.post("/casamentos/produto/{produto_id}/link", response_class=HTMLResponse)
    async def link_manual(request: Request, produto_id: int):
        formulario = await ler_formulario(request)
        texto = formulario.get("link", "")
        voltar = destino_seguro(formulario.get("voltar", "/casamentos"))
        with sessoes() as s, s.begin():
            produto = s.get(ProdutoLiga, produto_id)
            if produto is None or not produto.ativo:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            try:
                asin = extrair_asin(texto)
            except LinkInvalido as erro:
                return _tela_produto_casamento(
                    request, s, produto_id, voltar, None, str(erro), texto, status.HTTP_400_BAD_REQUEST
                )
            repo_amz.casar_link_manual(s, produto_id, asin, repo.agora_utc())
        destino = f"/casamentos/produto/{produto_id}?" + urlencode({"voltar": voltar, "msg": "link_salvo"})
        return RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/casamentos/{anuncio_id}")
    async def revisar_casamento(request: Request, anuncio_id: int):
        formulario = await ler_formulario(request)
        acao = formulario.get("acao", "")
        if acao not in ("confirmar", "ignorar", "desfazer"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"ação inválida: {acao}")
        agora = repo.agora_utc()
        with sessoes() as s, s.begin():
            if s.get(AnuncioAmazon, anuncio_id) is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            if acao == "confirmar":
                texto = formulario.get("produto_id", "").strip()
                if not (texto.isdecimal() and len(texto) <= 9):
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "produto_id inválido")
                if s.get(ProdutoLiga, int(texto)) is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND)
                repo_amz.confirmar_casamento(s, anuncio_id, int(texto), agora)
            elif acao == "ignorar":
                repo_amz.ignorar_anuncio(s, anuncio_id, agora)
            else:
                repo_amz.desfazer_casamento(s, anuncio_id, agora)
        destino = destino_seguro(formulario.get("voltar", "/casamentos"))
        return RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/casamentos/{anuncio_id}/trocar", response_class=HTMLResponse)
    def trocar_casamento(request: Request, anuncio_id: int, busca: str = ""):
        with sessoes() as s, s.begin():
            anuncio = s.get(AnuncioAmazon, anuncio_id)
            if anuncio is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            return templates.TemplateResponse(
                request,
                "trocar.html",
                {
                    "anuncio": anuncio,
                    "busca": busca,
                    "sugestoes": consultas_amazon.sugestoes_para(s, anuncio),
                    "produtos": consultas_amazon.buscar_produtos(s, busca) if busca.strip() else [],
                },
            )
```

`Session` já é importado em `app.py` (`from sqlalchemy.orm import Session, sessionmaker`).

- [ ] **Step 5: Templates**

Substitua todo o `src/tcg_sniper/admin/templates/casamentos.html` por:

```html
{% extends "base.html" %}
{% block titulo %}Casamentos · TCG Sniper{% endblock %}
{% block conteudo %}
<h2>Casamentos Amazon × Liga</h2>
<form method="get" action="/casamentos" class="filtros">
  <fieldset role="group">
    <input type="search" name="busca" value="{{ busca }}" placeholder="Buscar produto da Liga">
    <button type="submit">Filtrar</button>
  </fieldset>
  <div class="grid">
    <select name="situacao" aria-label="Situação">
      {% for s in situacoes %}<option value="{{ s }}" {% if s == situacao %}selected{% endif %}>{{ {"pendentes": "com pendentes", "oportunidade": "com oportunidade", "sem_par": "sem par", "casados": "casados", "todos": "todos"}[s] }}</option>{% endfor %}
    </select>
    <select name="categoria" aria-label="Categoria">
      <option value="">todas as categorias</option>
      {% for c in categorias %}<option value="{{ c }}" {% if c == categoria %}selected{% endif %}>{{ c }}</option>{% endfor %}
    </select>
    <label><input type="checkbox" name="com_preco" value="1" {% if com_preco %}checked{% endif %}> Só com preço na Liga</label>
  </div>
</form>
<p>{{ total }} produto(s)</p>
<table>
  <thead><tr><th>Produto da Liga</th><th>À partir de</th><th>Pendentes</th><th>Confirmados</th><th>Ignorados</th><th></th></tr></thead>
  <tbody>
  {% for l in linhas %}
    <tr>
      <td><a href="{{ l.produto.url }}" target="_blank" rel="noopener">{{ l.produto.nome }}</a>
        {% if l.oportunidade %}<mark>oportunidade</mark>{% endif %}{% if l.sem_par %}<small> · sem par</small>{% endif %}</td>
      <td>{{ l.preco_liga|brl }}</td>
      <td>{{ l.pendentes }}</td><td>{{ l.confirmados }}</td><td>{{ l.ignorados }}</td>
      <td><a href="/casamentos/produto/{{ l.produto.id }}?voltar={{ voltar_atual|urlencode }}">Abrir</a></td>
    </tr>
  {% else %}
    <tr><td colspan="6">Nenhum produto neste filtro.</td></tr>
  {% endfor %}
  </tbody>
</table>
<p>
  {% if pagina > 1 %}<a href="{{ link(pagina - 1) }}">← anterior</a>{% endif %}
  Página {{ pagina }} de {{ paginas }}
  {% if pagina < paginas %}<a href="{{ link(pagina + 1) }}">próxima →</a>{% endif %}
</p>
{% endblock %}
```

O teste de paginação conta `href="/casamentos/produto/` (um por linha): os links de página apontam para `/casamentos?…`, não entram na contagem.

Crie `src/tcg_sniper/admin/templates/casamentos_produto.html`:

```html
{% extends "base.html" %}
{% block titulo %}{{ d.produto.nome }} · Casamentos · TCG Sniper{% endblock %}
{% block conteudo %}
<p><a href="{{ voltar }}">← Voltar</a></p>
<h2>{{ d.produto.nome }}</h2>
<p><a href="{{ d.produto.url }}" target="_blank" rel="noopener">Ver na LigaMagic</a> · À partir de {{ d.preco_liga|brl }}</p>
{% if mensagem %}<p><mark>{{ mensagem }}</mark></p>{% endif %}
<form method="post" action="/casamentos/produto/{{ d.produto.id }}/link">
  <input type="hidden" name="voltar" value="{{ voltar }}">
  <fieldset role="group">
    <input name="link" value="{{ link_digitado }}" placeholder="Colar link da Amazon (ou o ASIN)"{% if erro %} aria-invalid="true"{% endif %}>
    <button type="submit">Casar</button>
  </fieldset>
  {% if erro %}<small>{{ erro }}</small>{% endif %}
</form>

{% macro botao(anuncio, acao, rotulo, classe="", produto_id=None) %}
<form method="post" action="/casamentos/{{ anuncio.id }}">
  <input type="hidden" name="acao" value="{{ acao }}"><input type="hidden" name="voltar" value="{{ aqui }}">
  {% if produto_id %}<input type="hidden" name="produto_id" value="{{ produto_id }}">{% endif %}
  <button class="{{ classe }}">{{ rotulo }}</button>
</form>
{% endmacro %}

<h3>Pendentes</h3>
<table>
  <tbody>
  {% for l in d.pendentes %}
    <tr>
      <td><a href="{{ l.anuncio.url }}" target="_blank" rel="noopener">{{ l.anuncio.titulo }}</a><br><small>{{ l.anuncio.asin }}</small></td>
      <td>{{ (l.atual.preco if l.atual else None)|brl }}{% if l.oportunidade %}<br><mark>oportunidade</mark>{% endif %}</td>
      <td>
        {{ botao(l.anuncio, "confirmar", "Confirmar", produto_id=d.produto.id) }}
        {{ botao(l.anuncio, "ignorar", "Ignorar", "secondary outline") }}
        <a href="/casamentos/{{ l.anuncio.id }}/trocar" role="button" class="secondary">É de outro produto</a>
      </td>
    </tr>
  {% else %}
    <tr><td>Nenhum anúncio pendente.</td></tr>
  {% endfor %}
  </tbody>
</table>

<h3>Confirmados</h3>
<table>
  <tbody>
  {% for l in d.confirmados %}
    <tr>
      <td><a href="{{ l.anuncio.url }}" target="_blank" rel="noopener">{{ l.anuncio.titulo }}</a><br><small>{{ l.anuncio.asin }}</small></td>
      <td>{{ (l.atual.preco if l.atual else None)|brl }}</td>
      <td>{{ l.atual.envio|envio(l.vendedor) if l.atual else "—" }}</td>
      <td>{{ (l.atual.coletado_em if l.atual else None)|data }}</td>
      <td>{{ botao(l.anuncio, "desfazer", "Desfazer", "secondary outline") }}</td>
    </tr>
  {% else %}
    <tr><td>Nenhum anúncio confirmado.</td></tr>
  {% endfor %}
  </tbody>
</table>

<h3>Ignorados</h3>
<table>
  <tbody>
  {% for l in d.ignorados %}
    <tr>
      <td><a href="{{ l.anuncio.url }}" target="_blank" rel="noopener">{{ l.anuncio.titulo }}</a><br><small>{{ l.anuncio.asin }}</small></td>
      <td>{{ botao(l.anuncio, "desfazer", "Desfazer", "secondary outline") }}</td>
    </tr>
  {% else %}
    <tr><td>Nenhum anúncio ignorado.</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

Substitua todo o `src/tcg_sniper/admin/templates/trocar.html` por:

```html
{% extends "base.html" %}
{% block titulo %}Trocar casamento · TCG Sniper{% endblock %}
{% block conteudo %}
<h2>Escolher o produto da Liga</h2>
<p><a href="{{ anuncio.url }}" target="_blank" rel="noopener">{{ anuncio.titulo }}</a> ({{ anuncio.asin }})</p>

{% macro linha(p, preco) %}
<tr>
  <td><a href="{{ p.url }}" target="_blank" rel="noopener">{{ p.nome }}</a></td>
  <td>{{ preco|brl }}</td>
  <td>
    <form method="post" action="/casamentos/{{ anuncio.id }}">
      <input type="hidden" name="acao" value="confirmar"><input type="hidden" name="produto_id" value="{{ p.id }}">
      <input type="hidden" name="voltar" value="/casamentos/produto/{{ p.id }}">
      <button>Escolher</button>
    </form>
  </td>
</tr>
{% endmacro %}

{% if sugestoes %}
<h3>Parecidos</h3>
<table><tbody>{% for p, preco in sugestoes %}{{ linha(p, preco) }}{% endfor %}</tbody></table>
{% endif %}

<h3>Buscar no catálogo da Liga</h3>
<form method="get" action="/casamentos/{{ anuncio.id }}/trocar">
  <fieldset role="group">
    <input type="search" name="busca" value="{{ busca }}" placeholder="Nome do produto na Liga">
    <button type="submit">Buscar</button>
  </fieldset>
</form>
<table>
  <tbody>
  {% for p, preco in produtos %}{{ linha(p, preco) }}{% else %}
    {% if busca %}<tr><td colspan="3">Nenhum produto encontrado.</td></tr>{% endif %}
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

- [ ] **Step 6: Rodar**

Run: `uv run pytest -q && uv run ruff check`
Expected: tudo passa.

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/admin tests/admin
git commit -m "feat: matching by Liga product with a manual Amazon link and Liga links on swap"
```

---

### Task 5: Filtros e paginação em Ofertas

**Files:**
- Modify: `src/tcg_sniper/admin/consultas_amazon.py` (`ofertas` com `FiltroOfertas`, `LinhaOferta.diferenca`)
- Modify: `src/tcg_sniper/admin/app.py` (rota `/ofertas`), `src/tcg_sniper/admin/templates/ofertas.html`
- Modify: `tests/admin/test_admin_amazon.py` (testes de ofertas antigos), `README.md` (tabela de telas)
- Test: `tests/admin/test_admin_ofertas.py`

**Interfaces:**
- Consumes: `consultas.paginar`, `numero_pagina` (Task 3); `consultas.listar_categorias`, `_escapar_like`.
- Produces (em `consultas_amazon`): `VENDEDORES_OFERTAS = ("todos", "amazon", "fba", "elegiveis")`, `SITUACOES_OFERTAS = ("todas", "abertas")`, `ORDENS_OFERTAS = ("desconto", "diferenca", "recentes", "nome")`, `POR_PAGINA_OFERTAS = 50`, `FiltroOfertas(busca="", categoria=None, desconto_min=None, vendedor="todos", situacao="todas", ordem="desconto")`, `LinhaOferta` com o campo novo `diferenca: Decimal | None`, `ofertas(s, filtro: FiltroOfertas, config: ConfigAmazon) -> list[LinhaOferta]`. Some `FILTROS_OFERTAS`.

- [ ] **Step 1: Testes**

`tests/admin/test_admin_ofertas.py`:

```python
import base64
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto
from fastapi.testclient import TestClient

from tcg_sniper.admin import consultas_amazon
from tcg_sniper.admin.app import criar_app
from tcg_sniper.admin.consultas_amazon import FiltroOfertas
from tcg_sniper.coletor_amazon.modelos import AvaliacaoVendedor
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import Envio, OrigemPreco, StatusCasamento

SP = ZoneInfo("America/Sao_Paulo")


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def oferta(s, asin, produto, preco, envio, vendedor_id=None, quando=T0):
    anuncio = criar_anuncio(s, asin, produto=produto, status=StatusCasamento.CONFIRMADO)
    repo_amz.registrar_preco(s, anuncio.id, Decimal(preco), OrigemPreco.PRODUTO, vendedor_id, envio, quando, SP)
    return anuncio


@pytest.fixture
def cenario(sessoes):
    with sessoes() as s, s.begin():
        amazon = repo_amz.vendedor_da_amazon(s)
        boa = repo_amz.gravar_vendedor(s, AvaliacaoVendedor("A1", "Loja Boa", Decimal("98"), 5000), T0)
        ruim = repo_amz.gravar_vendedor(s, AvaliacaoVendedor("A2", "Loja Nova", Decimal("80"), 3), T0)
        caixa = criar_produto(s, "caixa", nome="Caixa 100% Colecionador")
        bundle = criar_produto(s, "bundle", nome="Bundle Final")
        deck = criar_produto(s, "deck", nome="Deck Commander")
        caixa.tipo, bundle.tipo, deck.tipo = "Caixas", "Bundles", "Decks"
        criar_preco_liga(s, caixa, "1000.00")
        criar_preco_liga(s, bundle, "300.00")
        criar_preco_liga(s, deck, "400.00")
        caixa_amazon = oferta(s, "B0CAIXAAMZ", caixa, "700.00", Envio.AMAZON, amazon.id, T0)  # 30%, R$ 300
        oferta(s, "B0CAIXAFBA", caixa, "650.00", Envio.FBA, ruim.id, T0)  # 35%, lojista não confiável
        oferta(s, "B0BUNDLE01", bundle, "150.00", Envio.FBA, boa.id, T0 + timedelta(hours=2))  # 50%, R$ 150
        oferta(s, "B0DECK0001", deck, "380.00", Envio.AMAZON, amazon.id, T0 + timedelta(hours=1))  # 5%, R$ 20
        repo_amz.abrir_oportunidade(
            s, anuncio_id=caixa_amazon.id,
            produto_id=caixa.id, preco_amazon=Decimal("700.00"), preco_liga=Decimal("1000.00"),
            desconto_pct=Decimal("30.00"), vendedor_id=amazon.id, envio=Envio.AMAZON, agora=T0,
        )


def asins(s, **campos):
    config = repo_amz.obter_config(s)
    return [linha.anuncio.asin for linha in consultas_amazon.ofertas(s, FiltroOfertas(**campos), config)]


def test_ordens(s, cenario):
    assert asins(s) == ["B0BUNDLE01", "B0CAIXAFBA", "B0DECK0001"]  # melhor oferta por produto, maior % primeiro
    assert asins(s, ordem="diferenca") == ["B0CAIXAFBA", "B0BUNDLE01", "B0DECK0001"]
    assert asins(s, ordem="recentes") == ["B0BUNDLE01", "B0DECK0001", "B0CAIXAFBA"]
    assert asins(s, ordem="nome") == ["B0BUNDLE01", "B0CAIXAFBA", "B0DECK0001"]


def test_vendedor_escolhe_a_melhor_oferta_entre_as_aceitas(s, cenario):
    assert asins(s, vendedor="amazon") == ["B0CAIXAAMZ", "B0DECK0001"]
    assert asins(s, vendedor="fba") == ["B0BUNDLE01", "B0CAIXAFBA"]
    assert asins(s, vendedor="elegiveis") == ["B0BUNDLE01", "B0CAIXAAMZ", "B0DECK0001"]


def test_busca_categoria_desconto_e_situacao(s, cenario):
    assert asins(s, busca="100%") == ["B0CAIXAFBA"]
    assert asins(s, busca="_") == []
    assert asins(s, categoria="Bundles") == ["B0BUNDLE01"]
    assert asins(s, desconto_min=30) == ["B0BUNDLE01", "B0CAIXAFBA"]
    assert asins(s, situacao="abertas") == ["B0CAIXAFBA"]


def test_diferenca_em_reais(s, cenario):
    config = repo_amz.obter_config(s)
    [deck] = consultas_amazon.ofertas(s, FiltroOfertas(busca="Deck"), config)
    assert deck.diferenca == Decimal("20.00")


def test_tela_com_filtros_paginacao_e_validacao(cliente, sessoes, cenario):
    texto = cliente.get("/ofertas").text
    assert "Diferença (R$)" in texto and "R$ 150,00" in texto
    assert 'href="/ofertas?desconto_min=25' in texto  # atalho "≥ desconto configurado"
    filtrado = cliente.get("/ofertas?vendedor=amazon&ordem=nome").text
    assert "B0CAIXAAMZ" in filtrado and "B0BUNDLE01" not in filtrado
    for consulta in ("vendedor=xyz", "ordem=xyz", "situacao=xyz", "desconto_min=abc", "desconto_min=101", "categoria=Nada"):
        assert cliente.get(f"/ofertas?{consulta}").status_code == 400
    with sessoes() as s, s.begin():
        amazon = repo_amz.vendedor_da_amazon(s)
        for i in range(55):
            produto = criar_produto(s, f"p{i}", nome=f"Produto {i:02d}")
            criar_preco_liga(s, produto, "100.00")
            oferta(s, f"B0EXTRA{i:03d}", produto, "90.00", Envio.AMAZON, amazon.id)
    pagina2 = cliente.get("/ofertas?vendedor=amazon&pagina=2").text
    assert pagina2.count("<small>B0") == 7  # 57 ofertas da Amazon → 50 + 7
    assert "vendedor=amazon" in pagina2
    assert cliente.get("/ofertas?pagina=999").status_code == 200
```

Em `tests/admin/test_admin_amazon.py`, atualize os testes de ofertas que ficaram lá:

- `consultas_amazon.ofertas(s, "todas", config)` vira `consultas_amazon.ofertas(s, FiltroOfertas(), config)`; `ofertas(s, "desconto", config)` vira `ofertas(s, FiltroOfertas(desconto_min=config.desconto_min_pct), config)`; `ofertas(s, "abertas", config)` vira `ofertas(s, FiltroOfertas(situacao="abertas"), config)` (import `from tcg_sniper.admin.consultas_amazon import FiltroOfertas`).
- Em `test_tela_de_ofertas`: `"/ofertas?filtro=desconto"` vira `"/ofertas?desconto_min=25"`, e `"/ofertas?filtro=xyz"` vira `"/ofertas?vendedor=xyz"`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/admin/test_admin_ofertas.py -q`
Expected: FAIL (`ImportError: cannot import name 'FiltroOfertas'`).

- [ ] **Step 3: Consulta**

Em `src/tcg_sniper/admin/consultas_amazon.py`, troque `FILTROS_OFERTAS`, `LinhaOferta` e `ofertas` por:

```python
VENDEDORES_OFERTAS = ("todos", "amazon", "fba", "elegiveis")
SITUACOES_OFERTAS = ("todas", "abertas")
ORDENS_OFERTAS = ("desconto", "diferenca", "recentes", "nome")
POR_PAGINA_OFERTAS = 50


@dataclass(frozen=True)
class FiltroOfertas:
    busca: str = ""
    categoria: str | None = None
    desconto_min: int | None = None
    vendedor: str = "todos"
    situacao: str = "todas"
    ordem: str = "desconto"


@dataclass(frozen=True)
class LinhaOferta:
    produto: ProdutoLiga
    preco_liga: Decimal | None
    anuncio: AnuncioAmazon
    preco: Decimal | None
    envio: Envio
    vendedor: VendedorAmazon | None
    confiavel: bool
    coletado_em: datetime
    desconto: Decimal | None
    diferenca: Decimal | None  # "À partir de" − preço da Amazon
    aberta: bool


def _vendedor_aceito(vendedor: str, envio: Envio, confiavel: bool) -> bool:
    if vendedor == "amazon":
        return envio is Envio.AMAZON
    if vendedor == "fba":
        return envio is Envio.FBA
    if vendedor == "elegiveis":
        return confiavel
    return True


_ORDENS = {
    "desconto": lambda l: (l.desconto is None, -(l.desconto or 0), l.produto.nome, l.produto.id),
    "diferenca": lambda l: (l.diferenca is None, -(l.diferenca or 0), l.produto.nome, l.produto.id),
    "recentes": lambda l: (-l.coletado_em.timestamp(), l.produto.nome, l.produto.id),
    "nome": lambda l: (l.produto.nome, l.produto.id),
}


def ofertas(s: Session, filtro: FiltroOfertas, config: ConfigAmazon) -> list[LinhaOferta]:
    """Uma linha por produto da Liga com ASIN confirmado e preço: a oferta mais barata da Amazon entre
    as aceitas pelo filtro de vendedor, contra o "À partir de" da Liga."""
    condicoes = [AnuncioAmazon.status_casamento == StatusCasamento.CONFIRMADO, PrecoAtualAmazon.preco.is_not(None)]
    if filtro.busca.strip():
        condicoes.append(ProdutoLiga.nome.ilike(f"%{_escapar_like(filtro.busca.strip())}%", escape="\\"))
    if filtro.categoria:
        condicoes.append(ProdutoLiga.tipo == filtro.categoria)
    consulta = (
        select(AnuncioAmazon, ProdutoLiga, PrecoAtualAmazon, VendedorAmazon, PrecoAtualLiga.preco_a_partir)
        .join(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAtualAmazon.vendedor_id)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(*condicoes)
    )
    abertas = set(s.scalars(select(Oportunidade.produto_id).where(Oportunidade.fechada_em.is_(None))))
    regras = Regras.de(config)
    melhores: dict[int, LinhaOferta] = {}
    for anuncio, produto, atual, vendedor, preco_liga in s.execute(consulta):
        info = Vendedor(vendedor.nome, vendedor.pct_positivas, vendedor.num_avaliacoes) if vendedor else None
        confiavel = atual.envio is Envio.AMAZON or (atual.envio is Envio.FBA and vendedor_confiavel(info, regras))
        if not _vendedor_aceito(filtro.vendedor, atual.envio, confiavel):
            continue
        atual_melhor = melhores.get(produto.id)
        if atual_melhor is not None and atual_melhor.preco <= atual.preco:
            continue
        melhores[produto.id] = LinhaOferta(
            produto=produto,
            preco_liga=preco_liga,
            anuncio=anuncio,
            preco=atual.preco,
            envio=atual.envio,
            vendedor=vendedor,
            confiavel=confiavel,
            coletado_em=atual.coletado_em,
            desconto=desconto_pct(atual.preco, preco_liga) if preco_liga else None,
            diferenca=preco_liga - atual.preco if preco_liga is not None else None,
            aberta=produto.id in abertas,
        )
    linhas = list(melhores.values())
    if filtro.desconto_min is not None:
        linhas = [l for l in linhas if l.desconto is not None and l.desconto >= filtro.desconto_min]
    if filtro.situacao == "abertas":
        linhas = [l for l in linhas if l.aberta]
    linhas.sort(key=_ORDENS[filtro.ordem])
    return linhas
```

Em `test_ordens`, por desconto: Bundle 50%, Caixa (melhor oferta = FBA a 650, 35%), Deck 5%. Por diferença: Caixa R$ 350, Bundle R$ 150, Deck R$ 20. Por leitura recente: Bundle (T0+2h), Deck (T0+1h), Caixa (T0). Por nome: "Bundle Final" < "Caixa 100% Colecionador" < "Deck Commander". O filtro `vendedor=elegiveis` descarta a oferta FBA de lojista não confiável, e a melhor oferta da Caixa passa a ser a da Amazon (700).

- [ ] **Step 4: Rota**

Em `src/tcg_sniper/admin/app.py`, troque a rota `ofertas` por:

```python
    @app.get("/ofertas", response_class=HTMLResponse)
    def ofertas(
        request: Request,
        busca: str = "",
        categoria: str = "",
        desconto_min: str = "",
        vendedor: str = "todos",
        situacao: str = "todas",
        ordem: str = "desconto",
        pagina: str = "1",
    ):
        if (
            vendedor not in consultas_amazon.VENDEDORES_OFERTAS
            or situacao not in consultas_amazon.SITUACOES_OFERTAS
            or ordem not in consultas_amazon.ORDENS_OFERTAS
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "filtro inválido")
        texto_desconto = desconto_min.strip()
        if texto_desconto and not (texto_desconto.isdecimal() and len(texto_desconto) <= 3 and int(texto_desconto) <= 100):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"desconto inválido: {desconto_min}")
        with sessoes() as s, s.begin():
            categorias = consultas.listar_categorias(s)
            if categoria and categoria not in categorias:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"categoria inválida: {categoria}")
            cfg = repo_amz.obter_config(s)
            filtro = consultas_amazon.FiltroOfertas(
                busca=busca,
                categoria=categoria or None,
                desconto_min=int(texto_desconto) if texto_desconto else None,
                vendedor=vendedor,
                situacao=situacao,
                ordem=ordem,
            )
            linhas = consultas_amazon.ofertas(s, filtro, cfg)
            linhas_pagina, numero, paginas = consultas.paginar(
                linhas, numero_pagina(pagina), consultas_amazon.POR_PAGINA_OFERTAS
            )
            parametros = {
                "busca": busca,
                "categoria": categoria,
                "desconto_min": texto_desconto,
                "vendedor": vendedor if vendedor != "todos" else "",
                "situacao": situacao if situacao != "todas" else "",
                "ordem": ordem if ordem != "desconto" else "",
            }
            parametros = {k: v for k, v in parametros.items() if v}

            def link(destino: int) -> str:
                return "/ofertas?" + urlencode({**parametros, "pagina": destino})

            return templates.TemplateResponse(
                request,
                "ofertas.html",
                {
                    "linhas": linhas_pagina,
                    "total": len(linhas),
                    "pagina": numero,
                    "paginas": paginas,
                    "link": link,
                    "f": filtro,
                    "desconto_texto": texto_desconto,
                    "categorias": categorias,
                    "vendedores": consultas_amazon.VENDEDORES_OFERTAS,
                    "ordens": consultas_amazon.ORDENS_OFERTAS,
                    "desconto_min_pct": cfg.desconto_min_pct,
                },
            )
```

- [ ] **Step 5: Template**

Substitua todo o `src/tcg_sniper/admin/templates/ofertas.html` por:

```html
{% extends "base.html" %}
{% block titulo %}Ofertas · TCG Sniper{% endblock %}
{% block conteudo %}
<h2>Ofertas Amazon × Liga</h2>
<form method="get" action="/ofertas" class="filtros">
  <fieldset role="group">
    <input type="search" name="busca" value="{{ f.busca }}" placeholder="Buscar produto">
    <button type="submit">Filtrar</button>
  </fieldset>
  <div class="grid">
    <select name="categoria" aria-label="Categoria">
      <option value="">todas as categorias</option>
      {% for c in categorias %}<option value="{{ c }}" {% if c == f.categoria %}selected{% endif %}>{{ c }}</option>{% endfor %}
    </select>
    <input type="number" name="desconto_min" min="0" max="100" value="{{ desconto_texto }}" placeholder="Desconto mínimo (%)" aria-label="Desconto mínimo (%)">
    <select name="vendedor" aria-label="Vendedor">
      {% for v in vendedores %}<option value="{{ v }}" {% if v == f.vendedor %}selected{% endif %}>{{ {"todos": "todos os vendedores", "amazon": "vendido pela Amazon", "fba": "lojista FBA", "elegiveis": "só elegíveis"}[v] }}</option>{% endfor %}
    </select>
    <select name="situacao" aria-label="Situação">
      <option value="todas" {% if f.situacao == "todas" %}selected{% endif %}>todas</option>
      <option value="abertas" {% if f.situacao == "abertas" %}selected{% endif %}>só oportunidades abertas</option>
    </select>
    <select name="ordem" aria-label="Ordem">
      {% for o in ordens %}<option value="{{ o }}" {% if o == f.ordem %}selected{% endif %}>{{ {"desconto": "maior desconto %", "diferenca": "maior diferença R$", "recentes": "leitura mais recente", "nome": "nome"}[o] }}</option>{% endfor %}
    </select>
  </div>
</form>
<p><a href="/ofertas?desconto_min={{ desconto_min_pct }}">≥ desconto configurado ({{ desconto_min_pct }}%)</a> · {{ total }} produto(s)</p>
<table>
  <thead><tr><th>Produto</th><th>Liga (à partir de)</th><th>Amazon</th><th>Diferença (%)</th><th>Diferença (R$)</th><th>Vendedor</th><th>Lido em</th></tr></thead>
  <tbody>
  {% for l in linhas %}
    <tr>
      <td><a href="/produto/{{ l.produto.id }}">{{ l.produto.nome }}</a>{% if l.aberta %} <mark>oportunidade</mark>{% endif %}<br><small>{{ l.anuncio.asin }}</small></td>
      <td>{{ l.preco_liga|brl }}</td>
      <td><a href="{{ l.anuncio.url }}" target="_blank" rel="noopener">{{ l.preco|brl }}</a></td>
      <td>{{ (l.desconto|string).replace(".", ",") ~ "%" if l.desconto is not none else "—" }}</td>
      <td>{{ l.diferenca|brl }}</td>
      <td>{{ l.envio|envio(l.vendedor) }}{% if not l.confiavel %} <small>(não elegível)</small>{% endif %}</td>
      <td>{{ l.coletado_em|data }}</td>
    </tr>
  {% else %}
    <tr><td colspan="7">Nenhuma oferta neste filtro.</td></tr>
  {% endfor %}
  </tbody>
</table>
<p>
  {% if pagina > 1 %}<a href="{{ link(pagina - 1) }}">← anterior</a>{% endif %}
  Página {{ pagina }} de {{ paginas }}
  {% if pagina < paginas %}<a href="{{ link(pagina + 1) }}">próxima →</a>{% endif %}
</p>
{% endblock %}
```

O ASIN aparece em `<small>` em cada linha (e também na URL do anúncio): o teste de paginação conta `<small>B0` para saber quantas linhas a página tem.

- [ ] **Step 6: README**

Em `README.md`, na tabela de telas de "Uso no dia a dia", troque a linha de **Início** por duas linhas — **Dashboard** (`/`): "Estado e histórico dos serviços (só leitura); avisa quando algum está pausado." e **Serviços** (`/servicos`): "Rodar agora e Retomar (LigaMagic), Pausar e Retomar (Amazon)." —, e atualize as linhas de **Casamentos** ("Produtos ativos da Liga com os anúncios da Amazon encontrados; confirmar, ignorar, trocar ou colar o link da Amazon à mão; filtros por situação, categoria e nome.") e **Ofertas** ("Melhor oferta da Amazon por produto contra a Liga; filtros por nome, categoria, desconto mínimo, vendedor e situação; ordenação por desconto, diferença em R$, leitura ou nome."). Onde o README manda clicar em **Retomar (Amazon)** ou **Rodar agora** "no admin", diga "em Serviços".

- [ ] **Step 7: Rodar**

Run: `uv run pytest -q && uv run ruff check`
Expected: tudo passa.

- [ ] **Step 8: Commit**

```bash
git add src/tcg_sniper/admin tests/admin README.md
git commit -m "feat: filters, sorting and pagination on the offers page"
```

- [ ] **Step 9: Deploy (com o usuário)**

Sem migração nesta entrega. Depois do merge no `main`: `docker compose up -d --build admin coletor-amazon` (o `coletor-liga` não muda, mas `docker compose up -d --build` de tudo também serve). Conferir o Dashboard, Serviços, um link manual em Casamentos e os filtros de Ofertas.
