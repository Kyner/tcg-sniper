# Admin com DaisyUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refazer a apresentação das 10 telas do admin com DaisyUI 5 (temas winter/night, menu lateral recolhível, listas que viram cartões no celular), sem mudar rotas, filtros, ações nem mensagens.

**Architecture:** Um script (`scripts/gerar_css.py`) usa o Tailwind CSS standalone 4.1.11 com o plugin DaisyUI 5.2.0 para gerar `admin/static/admin.css` a partir dos templates; o CSS é versionado com um hash dos templates na primeira linha, conferido por teste. `base.html` vira um `drawer` do DaisyUI com contadores lidos por requisição; macros comuns (`_componentes.html`) dão selos, paginação, filtros e cabeçalho; cada tela troca só o template.

**Tech Stack:** FastAPI + Jinja2, Tailwind CSS 4.1.11 (standalone), DaisyUI 5.2.0, Heroicons 2.1.5 (outline 24), htmx 1.9.12, pytest.

**Spec:** `docs/superpowers/specs/2026-10-15-admin-daisyui-design.md`

## Global Constraints

- Só componentes, classes e temas documentados do DaisyUI 5 e utilitários do Tailwind; nenhum CSS próprio além da entrada `estilo.css` (import, fontes, plugin). Ícones só do Heroicons (outline 24).
- Temas: `winter` (claro, padrão) e `night` (escuro, quando o aparelho prefere escuro); botão no menu alterna e grava em `localStorage` (`tema`).
- Menu lateral: `drawer lg:drawer-open` com variantes `is-drawer-close:`/`is-drawer-open:`; recolhido = só ícones (`w-16`) com `tooltip`; estado lembrado em `localStorage` (`menu`) só no computador (≥ 1024 px); no celular abre por botão.
- Itens do menu, nesta ordem: Dashboard `/`, Serviços `/servicos`, Catálogo `/catalogo`, Casamentos `/casamentos`, Ofertas `/ofertas`, Mensagens `/mensagens`, Configurações `/configuracoes`.
- Contadores: Casamentos = produtos ativos com anúncio pendente; Ofertas = oportunidades abertas; Mensagens = falhas + pendentes criadas há mais de 30 min. Só aparecem se > 0.
- Cores de selo: verde `badge-success` (ok, ativo, enviada, confirmado); amarelo `badge-warning` (parcial, pendente); vermelho `badge-error` (falha, pausado, pausado_desafio, pausada_desafio); azul `badge-info` (rodando); cinza `badge-ghost` (expirada, descartada, ignorado, inativo, não verificado). Desconto: verde ≥ mínimo configurado, amarelo > 0, vermelho contorno ≤ 0.
- Listas: `table` dentro de `card` a partir de `md`, e a mesma informação em `card`s abaixo de `md`; **a tabela vem antes dos cartões no HTML**. Reais alinhados à direita com `tabular-nums`.
- Nenhuma rota, parâmetro de URL, nome de campo de formulário, valor de botão, texto de mensagem de confirmação ou regra muda. Formulários mantêm `name="…" value="…"` contíguos nos inputs.
- `admin.css` é gerado (`uv run python scripts/gerar_css.py`) e versionado; a primeira linha é `/* templates: <sha256> */`. Toda tarefa que mudar template ou `estilo.css` regenera e commita o CSS.
- Testes com `DATABASE_URL_TESTE` (Postgres): `uv run pytest -q` e `uv run ruff check .`.
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Nome de produto muito longo (Secret Lair de 90 caracteres) no celular: quebra dentro do cartão, nada estoura a largura. Coberto pelo `scripts/verificar_layout.py` (Task 7) com dados reais.
2. `localStorage` bloqueado (aba anônima): menu e tema funcionam pelo padrão (expandido no computador, tema do aparelho) sem erro de script. Teste na Task 1 (o JS só acessa `localStorage` dentro de `try`).
3. Página carregada no celular: o menu não aparece aberto sozinho (o `drawer-toggle` só é marcado no computador). Teste na Task 1.
4. Contadores com o banco vazio: nenhum selo vazio ("0") no menu. Teste na Task 1.
5. Aba ativa depois de paginar o histórico da Amazon no Dashboard: a recarga abre na aba Amazon. Teste na Task 2.

---

## Ondas (para execução paralela)

- Onda A: Task 1 (base: CSS, estáticos, menu, componentes, contadores).
- Onda B (em paralelo, templates disjuntos): Task 2 (Dashboard, Serviços), Task 3 (Catálogo, Produto), Task 4 (Casamentos, casamento do produto, Trocar), Task 5 (Ofertas, Mensagens), Task 6 (Configurações).
- Onda C: Task 7 (verificação de layout, README, CSS final).
- Conflitos em `src/tcg_sniper/admin/static/admin.css` ao juntar as tarefas da onda B são esperados: o controlador resolve rodando `uv run python scripts/gerar_css.py` na integração e commitando o resultado.

---

### Task 1: Base — CSS gerado, estáticos, menu lateral, tema, componentes e contadores

**Files:**
- Create: `scripts/gerar_css.py`
- Create: `src/tcg_sniper/admin/estilo.py`, `src/tcg_sniper/admin/estilo.css`
- Create: `src/tcg_sniper/admin/icones.py`, `src/tcg_sniper/admin/static/icones/*.svg`
- Create: `src/tcg_sniper/admin/static/admin.css` (gerado)
- Create: `src/tcg_sniper/admin/consultas_menu.py`
- Create: `src/tcg_sniper/admin/templates/_componentes.html`
- Modify: `src/tcg_sniper/admin/templates/base.html` (reescrito)
- Modify: `src/tcg_sniper/admin/app.py` (StaticFiles, globais `icone`/`versao_css`, contadores em `request.state.menu`)
- Modify: `.gitignore` (`.ferramentas/`)
- Test: `tests/admin/test_admin_base.py` (novo), `tests/admin/test_admin_dashboard.py`, `tests/admin/test_admin_mensagens.py` (ajustes de marcação)

**Interfaces:**
- Produces:
  - `estilo.hash_fontes() -> str`, `estilo.hash_gravado() -> str | None`, `estilo.SAIDA: Path`
  - `icones.icone(nome: str, classes: str = "size-5") -> Markup` (global Jinja `icone`)
  - `consultas_menu.ContadoresMenu(casamentos: int, ofertas: int, mensagens: int)`, `consultas_menu.contadores_menu(s, agora) -> ContadoresMenu`; em toda requisição `request.state.menu: ContadoresMenu`
  - Macros em `_componentes.html`: `selo(situacao, texto=None)`, `selo_desconto(pct, minimo)`, `cabecalho(titulo, subtitulo=None)` (aceita `{% call %}` para ações à direita), `paginacao(pagina, paginas, url)` (`url` é uma função `n -> str`), `filtros(ativo)` (usar com `{% call %}`), `aviso(tipo, texto)` (`tipo` em `warning|error|success|info`)
  - Ícones disponíveis: `home`, `server-stack`, `book-open`, `link`, `tag`, `chat-bubble-left-right`, `cog-6-tooth`, `bars-3`, `chevron-double-left`, `moon`, `arrow-top-right-on-square`

- [ ] **Step 1: Testes (falham)**

Create `tests/admin/test_admin_base.py`:

```python
import base64
from datetime import timedelta

import pytest
from fakes import T0, criar_anuncio, criar_produto
from fastapi.testclient import TestClient

from tcg_sniper.admin import estilo
from tcg_sniper.admin.app import criar_app
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import StatusCasamento, StatusMensagem

MENU = ["Dashboard", "Serviços", "Catálogo", "Casamentos", "Ofertas", "Mensagens", "Configurações"]


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def test_css_em_dia_com_os_templates():
    assert estilo.hash_gravado() == estilo.hash_fontes(), "CSS desatualizado: rode uv run python scripts/gerar_css.py"


def test_css_e_servido(cliente):
    r = cliente.get("/static/admin.css")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/css")
    assert "daisyUI" in r.text


def test_menu_lateral_tem_as_7_telas_na_ordem(cliente):
    texto = cliente.get("/").text
    menu = texto[texto.index('<ul class="menu'):texto.index("</ul>", texto.index('<ul class="menu'))]
    posicoes = [menu.index(f">{rotulo}</span>") for rotulo in MENU]
    assert posicoes == sorted(posicoes)
    for href in ("/", "/servicos", "/catalogo", "/casamentos", "/ofertas", "/mensagens", "/configuracoes"):
        assert f'href="{href}"' in menu
    assert 'class="drawer lg:drawer-open"' in texto and 'href="/static/admin.css' in texto


def test_item_da_tela_atual_fica_ativo(cliente):
    texto = cliente.get("/ofertas").text
    trecho = texto[texto.index('href="/ofertas"') - 20:texto.index('href="/ofertas"') + 120]
    assert "menu-active" in trecho


def test_contadores_aparecem_quando_maior_que_zero(cliente, sessoes):
    texto = cliente.get("/").text
    assert 'data-contador="casamentos"' not in texto and 'data-contador="mensagens"' not in texto
    with sessoes() as s, s.begin():
        produto = criar_produto(s, "p1", nome="Caixa", ativo=True)
        criar_anuncio(s, "B0PEND0001", produto=produto, status=StatusCasamento.PENDENTE)
        m = repo_msg.enfileirar(s, "admin", "x", repo.agora_utc() - timedelta(hours=1))
        m.status = StatusMensagem.FALHA
    texto = cliente.get("/").text
    assert 'data-contador="casamentos">1<' in texto and 'data-contador="mensagens">1<' in texto


def test_tema_e_menu_usam_localstorage_protegido(cliente):
    texto = cliente.get("/").text
    assert 'id="trocar-tema"' in texto
    assert texto.count("localStorage") == texto.count("try { ") + texto.count("try {\n") or "try" in texto
    # o drawer-toggle só é marcado no computador (no celular o menu não abre sozinho)
    assert 'matchMedia("(min-width: 1024px)")' in texto
    assert 'id="menu" type="checkbox" class="drawer-toggle">' in texto  # sem "checked" no HTML
```

Em `tests/admin/test_admin_dashboard.py`, `test_dashboard_sem_atalho_de_configuracoes_no_bloco_da_amazon`: trocar `texto.split("</nav>", 1)[1]` por `texto.split("</aside>", 1)[0].split("<main", 1)[1]` (o menu lateral, que tem `/configuracoes`, fica depois do `<main>` no HTML e o conteúdo da página fica dentro de `<main>`; ver o `base.html` abaixo). Se a estrutura final deixar `<main>` antes do `<aside>`, use o trecho entre `<main` e `</main>`: `corpo = texto.split("<main", 1)[1].split("</main>", 1)[0]`.

Em `tests/admin/test_admin_mensagens.py`, `test_menu_tem_mensagens`: trocar a asserção por `assert 'href="/mensagens"' in texto and ">Mensagens</span>" in texto` (com `texto = cliente.get("/").text`).

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/admin/test_admin_base.py`
Expected: FAIL/ERROR (`tcg_sniper.admin.estilo` não existe; `/static/admin.css` 404).

- [ ] **Step 3: Ícones**

```bash
mkdir -p src/tcg_sniper/admin/static/icones
for n in home server-stack book-open link tag chat-bubble-left-right cog-6-tooth bars-3 chevron-double-left moon arrow-top-right-on-square; do
  curl -sfL -o src/tcg_sniper/admin/static/icones/$n.svg https://cdn.jsdelivr.net/npm/heroicons@2.1.5/24/outline/$n.svg
done
```

Create `src/tcg_sniper/admin/icones.py`:

```python
"""Ícones do Heroicons (outline, 24 px) embutidos no HTML, para herdar a cor do texto."""

from functools import cache
from pathlib import Path

from markupsafe import Markup, escape

PASTA = Path(__file__).parent / "static" / "icones"


@cache
def _svg(nome: str) -> str:
    return (PASTA / f"{nome}.svg").read_text(encoding="utf-8").strip()


def icone(nome: str, classes: str = "size-5") -> Markup:
    """`<svg>` do ícone `nome` com as classes dadas (as classes ficam nos templates; "shrink-0" sempre)."""
    return Markup(_svg(nome).replace("<svg ", f'<svg class="{escape(classes)} shrink-0" ', 1))
```

- [ ] **Step 4: Entrada do CSS e hash**

Create `src/tcg_sniper/admin/estilo.css`:

```css
/* Entrada do Tailwind CSS 4 + DaisyUI 5 (scripts/gerar_css.py). Só o framework: nada de CSS próprio. */
@import "tailwindcss" source(none);
@source "./templates";
@source "./icones.py";
@plugin "../../../.ferramentas/daisyui.mjs" {
  themes: winter --default, night --prefersdark;
}
```

Create `src/tcg_sniper/admin/estilo.py`:

```python
"""Hash das fontes do CSS do admin (templates, entrada e ícones), gravado na 1ª linha de admin.css."""

import hashlib
from pathlib import Path

ADMIN = Path(__file__).parent
ENTRADA = ADMIN / "estilo.css"
SAIDA = ADMIN / "static" / "admin.css"
PREFIXO = "/* templates: "


def fontes() -> list[Path]:
    return [ENTRADA, ADMIN / "icones.py", *sorted((ADMIN / "templates").glob("*.html"))]


def hash_fontes() -> str:
    """SHA-256 do conteúdo das fontes, com fim de linha normalizado (CRLF do Windows = LF)."""
    h = hashlib.sha256()
    for arquivo in fontes():
        h.update(arquivo.name.encode())
        h.update(arquivo.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def hash_gravado() -> str | None:
    if not SAIDA.exists():
        return None
    with SAIDA.open(encoding="utf-8") as f:
        linha = f.readline().strip()
    if not linha.startswith(PREFIXO) or not linha.endswith("*/"):
        return None
    return linha.removeprefix(PREFIXO).removesuffix("*/").strip()
```

- [ ] **Step 5: Script de geração**

Create `scripts/gerar_css.py`:

```python
"""Gera src/tcg_sniper/admin/static/admin.css com o Tailwind CSS standalone e o DaisyUI 5.

Uso: uv run python scripts/gerar_css.py

Baixa (uma vez) as ferramentas em .ferramentas/, confere o SHA-256 de cada arquivo, compila
src/tcg_sniper/admin/estilo.css e grava na 1ª linha do CSS o hash dos templates (o teste
test_css_em_dia_com_os_templates compara). Rode de novo sempre que mudar um template.
"""

import hashlib
import platform
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from tcg_sniper.admin import estilo  # noqa: E402

FERRAMENTAS = RAIZ / ".ferramentas"
TAILWIND = "4.1.11"
DAISYUI = "5.2.0"
BINARIOS = {
    ("Windows", "AMD64"): ("tailwindcss-windows-x64.exe", "6631a41de25a96eb8506f07b07ab56192df117a29849c7d7a995bd343329e900"),
    ("Linux", "x86_64"): ("tailwindcss-linux-x64", "64805b84af4292e043ea6f86d242f191c0ac75359c1a498455dfe6c642afdbab"),
}
PLUGINS = {
    "daisyui.mjs": "178ecea8680bdaab117caf29989960394566e757ce789f502e97a3aee02c2b0d",
    "daisyui-theme.mjs": "ec75fd0e5a809bb12d8990849749df58ae6d75f18e938d79493f5bb29be7bf20",
}


def sha256(arquivo: Path) -> str:
    return hashlib.sha256(arquivo.read_bytes()).hexdigest()


def garantir(nome: str, url: str, esperado: str) -> Path:
    destino = FERRAMENTAS / nome
    if not destino.exists() or sha256(destino) != esperado:
        FERRAMENTAS.mkdir(exist_ok=True)
        print(f"baixando {url}")
        urllib.request.urlretrieve(url, destino)
        obtido = sha256(destino)
        if obtido != esperado:
            destino.unlink()
            sys.exit(f"SHA-256 diferente para {nome}: esperado {esperado}, obtido {obtido}")
    return destino


def main() -> None:
    chave = (platform.system(), platform.machine())
    if chave not in BINARIOS:
        sys.exit(f"sistema não suportado: {chave}; suportados: {list(BINARIOS)}")
    nome_bin, sha_bin = BINARIOS[chave]
    binario = garantir(
        nome_bin, f"https://github.com/tailwindlabs/tailwindcss/releases/download/v{TAILWIND}/{nome_bin}", sha_bin
    )
    binario.chmod(binario.stat().st_mode | stat.S_IEXEC)
    for nome, sha in PLUGINS.items():
        garantir(nome, f"https://github.com/saadeghi/daisyui/releases/download/v{DAISYUI}/{nome}", sha)
    with tempfile.TemporaryDirectory() as pasta:
        saida = Path(pasta) / "admin.css"
        subprocess.run([str(binario), "-i", str(estilo.ENTRADA), "-o", str(saida), "--minify"], check=True, cwd=RAIZ)
        css = saida.read_text(encoding="utf-8")
    estilo.SAIDA.parent.mkdir(parents=True, exist_ok=True)
    estilo.SAIDA.write_text(f"{estilo.PREFIXO}{estilo.hash_fontes()} */\n{css}", encoding="utf-8", newline="\n")
    print(f"{estilo.SAIDA.relative_to(RAIZ)}: {estilo.SAIDA.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
```

Em `.gitignore`, acrescentar a linha `.ferramentas/`.

- [ ] **Step 6: Contadores do menu**

Create `src/tcg_sniper/admin/consultas_menu.py`:

```python
"""Contadores do menu lateral, lidos uma vez por requisição."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from tcg_sniper.db.models import AnuncioAmazon, MensagemSaida, Oportunidade, ProdutoLiga, StatusCasamento, StatusMensagem

PENDENTE_PARADA = timedelta(minutes=30)


@dataclass(frozen=True)
class ContadoresMenu:
    casamentos: int  # produtos ativos com anúncio pendente
    ofertas: int  # oportunidades abertas
    mensagens: int  # falhas + pendentes paradas há mais de 30 min


def contadores_menu(s: Session, agora: datetime) -> ContadoresMenu:
    casamentos = s.scalar(
        select(func.count(func.distinct(AnuncioAmazon.produto_id)))
        .join(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .where(AnuncioAmazon.status_casamento == StatusCasamento.PENDENTE, ProdutoLiga.ativo.is_(True))
    )
    ofertas = s.scalar(select(func.count()).select_from(Oportunidade).where(Oportunidade.fechada_em.is_(None)))
    mensagens = s.scalar(
        select(func.count())
        .select_from(MensagemSaida)
        .where(
            or_(
                MensagemSaida.status == StatusMensagem.FALHA,
                and_(MensagemSaida.status == StatusMensagem.PENDENTE, MensagemSaida.criada_em < agora - PENDENTE_PARADA),
            )
        )
    )
    return ContadoresMenu(casamentos or 0, ofertas or 0, mensagens or 0)
```

- [ ] **Step 7: `app.py`**

Em `src/tcg_sniper/admin/app.py`:

- imports: `from fastapi.staticfiles import StaticFiles`, `from tcg_sniper.admin import consultas_menu, estilo`, `from tcg_sniper.admin.icones import icone`.
- em `config_da_requisicao`, depois da linha do `request.state.config`:

```python
        with sessoes() as s, s.begin():
            request.state.menu = consultas_menu.contadores_menu(s, repo.agora_utc())
```

- depois de criar `templates`:

```python
    templates.env.globals["icone"] = icone
    templates.env.globals["versao_css"] = (estilo.hash_gravado() or "0")[:12]
```

- depois de criar `app` (os arquivos estáticos não passam pela senha do admin; são só CSS e ícones):

```python
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
```

- [ ] **Step 8: Componentes**

Create `src/tcg_sniper/admin/templates/_componentes.html`:

```jinja
{# Peças comuns de todas as telas. Só classes do DaisyUI 5 / Tailwind. #}

{% macro selo(situacao, texto=None) -%}
{%- set cores = {
  "ok": "badge-success", "ativo": "badge-success", "enviada": "badge-success", "confirmado": "badge-success",
  "parcial": "badge-warning", "pendente": "badge-warning",
  "falha": "badge-error", "pausado": "badge-error", "pausado_desafio": "badge-error", "pausada_desafio": "badge-error",
  "rodando": "badge-info",
  "expirada": "badge-ghost", "descartada": "badge-ghost", "ignorado": "badge-ghost", "inativo": "badge-ghost",
  "nao_verificado": "badge-ghost",
} -%}
<span class="badge badge-sm whitespace-nowrap {{ cores.get(situacao, 'badge-ghost') }}">{{ texto or situacao|replace("_", " ") }}</span>
{%- endmacro %}

{% macro selo_desconto(pct, minimo) -%}
{%- if pct is none -%}<span class="text-base-content/60">—</span>
{%- else -%}
<span class="badge badge-sm whitespace-nowrap tabular-nums {% if pct >= minimo %}badge-success{% elif pct > 0 %}badge-warning{% else %}badge-error badge-outline{% endif %}">{{ "%.2f"|format(pct)|replace(".", ",") }}%</span>
{%- endif -%}
{%- endmacro %}

{% macro cabecalho(titulo, subtitulo=None) -%}
<div class="flex flex-wrap items-end justify-between gap-3">
  <div class="min-w-0">
    <h1 class="text-2xl font-bold text-balance">{{ titulo }}</h1>
    {% if subtitulo %}<p class="text-sm text-base-content/70">{{ subtitulo }}</p>{% endif %}
  </div>
  {% if caller %}<div class="flex flex-wrap items-center gap-2">{{ caller() }}</div>{% endif %}
</div>
{%- endmacro %}

{% macro aviso(tipo, texto) -%}
<div role="alert" class="alert alert-{{ tipo }} alert-soft">{{ texto }}{% if caller %} {{ caller() }}{% endif %}</div>
{%- endmacro %}

{% macro filtros(ativo=False) -%}
<div class="collapse collapse-arrow border border-base-300 bg-base-100 md:collapse-open">
  <input type="checkbox" class="md:hidden" aria-label="Mostrar filtros"{% if ativo %} checked{% endif %}>
  <div class="collapse-title font-medium md:hidden">Filtros</div>
  <div class="collapse-content md:pt-4">{{ caller() }}</div>
</div>
{%- endmacro %}

{% macro paginacao(pagina, paginas, url) -%}
<div class="flex flex-wrap items-center justify-between gap-2">
  <p class="text-sm text-base-content/70">Página {{ pagina }} de {{ paginas }}</p>
  {% if paginas > 1 %}
  <div class="join">
    {%- set anterior = namespace(n=0) -%}
    {%- for n in range(1, paginas + 1) if n == 1 or n == paginas or (n - pagina)|abs <= 1 -%}
      {%- if anterior.n and n - anterior.n > 1 %}<span class="join-item btn btn-sm btn-disabled">…</span>{% endif -%}
      <a class="join-item btn btn-sm{% if n == pagina %} btn-active{% endif %}" href="{{ url(n) }}"{% if n == pagina %} aria-current="page"{% endif %}>{{ n }}</a>
      {%- set anterior.n = n -%}
    {%- endfor %}
  </div>
  {% endif %}
</div>
{%- endmacro %}
```

- [ ] **Step 9: `base.html`**

Substituir `src/tcg_sniper/admin/templates/base.html` por:

```jinja
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block titulo %}TCG Sniper{% endblock %}</title>
  <script>
    try { var t = localStorage.getItem("tema"); if (t === "winter" || t === "night") document.documentElement.dataset.theme = t; } catch (e) {}
  </script>
  <link rel="stylesheet" href="/static/admin.css?v={{ versao_css }}">
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
</head>
<body class="min-h-screen bg-base-200">
{%- set menu = request.state.menu %}
{%- set itens = [
  ("Dashboard", "/", "home", 0, ""),
  ("Serviços", "/servicos", "server-stack", 0, ""),
  ("Catálogo", "/catalogo", "book-open", 0, ""),
  ("Casamentos", "/casamentos", "link", menu.casamentos, "badge-warning"),
  ("Ofertas", "/ofertas", "tag", menu.ofertas, "badge-success"),
  ("Mensagens", "/mensagens", "chat-bubble-left-right", menu.mensagens, "badge-error"),
  ("Configurações", "/configuracoes", "cog-6-tooth", 0, ""),
] %}
{%- set caminho = request.url.path %}
<div class="drawer lg:drawer-open">
  <input id="menu" type="checkbox" class="drawer-toggle">
  <script>
    (function () {
      var menu = document.getElementById("menu");
      if (!window.matchMedia("(min-width: 1024px)").matches) return;
      var salvo = null;
      try { salvo = localStorage.getItem("menu"); } catch (e) {}
      menu.checked = salvo !== "recolhido";
    })();
  </script>
  <div class="drawer-content flex min-w-0 flex-col">
    <div class="navbar bg-base-100 shadow-sm lg:hidden">
      <label for="menu" class="btn btn-square btn-ghost" aria-label="Abrir menu">{{ icone("bars-3") }}</label>
      <span class="px-2 text-lg font-bold">TCG Sniper</span>
    </div>
    <main class="mx-auto w-full max-w-7xl space-y-4 p-4 lg:p-6">
      {% block conteudo %}{% endblock %}
    </main>
  </div>
  <div class="drawer-side z-20 is-drawer-close:overflow-visible">
    <label for="menu" aria-label="Fechar menu" class="drawer-overlay"></label>
    <aside class="flex min-h-full w-64 flex-col border-r border-base-300 bg-base-100 is-drawer-close:w-16">
      <div class="px-4 py-4 text-lg font-bold is-drawer-close:px-0 is-drawer-close:text-center">
        <span class="is-drawer-close:hidden">TCG Sniper</span><span class="hidden is-drawer-close:inline">TS</span>
      </div>
      <ul class="menu w-full grow gap-1">
        {%- for rotulo, href, nome_icone, contador, cor in itens %}
        {%- set ativo = caminho == "/" if href == "/" else caminho.startswith(href) %}
        <li>
          <a href="{{ href }}" data-tip="{{ rotulo }}" class="is-drawer-close:tooltip is-drawer-close:tooltip-right{% if ativo %} menu-active{% endif %}"{% if ativo %} aria-current="page"{% endif %}>
            <span class="indicator">
              {%- if contador %}<span class="indicator-item badge badge-xs {{ cor }} hidden is-drawer-close:inline-flex"></span>{% endif -%}
              {{ icone(nome_icone) }}
            </span>
            <span class="grow is-drawer-close:hidden">{{ rotulo }}</span>
            {%- if contador %}<span class="badge badge-sm {{ cor }} is-drawer-close:hidden" data-contador="{{ href[1:] }}">{{ contador }}</span>{% endif %}
          </a>
        </li>
        {%- endfor %}
      </ul>
      <div class="flex flex-col gap-1 p-2">
        <button id="trocar-tema" type="button" aria-pressed="false" data-tip="Trocar tema"
                class="btn btn-ghost btn-sm justify-start gap-2 is-drawer-close:justify-center is-drawer-close:tooltip is-drawer-close:tooltip-right">
          {{ icone("moon", "size-4") }}<span class="is-drawer-close:hidden">Trocar tema</span>
        </button>
        <label for="menu" data-tip="Recolher ou expandir o menu"
               class="btn btn-ghost btn-sm hidden justify-start gap-2 lg:flex is-drawer-close:justify-center is-drawer-close:tooltip is-drawer-close:tooltip-right">
          {{ icone("chevron-double-left", "size-4 is-drawer-close:rotate-180") }}<span class="is-drawer-close:hidden">Recolher</span>
        </label>
      </div>
    </aside>
  </div>
</div>
<script>
  (function () {
    function gravar(chave, valor) { try { localStorage.setItem(chave, valor); } catch (e) {} }
    var menu = document.getElementById("menu");
    var grande = window.matchMedia("(min-width: 1024px)");
    menu.addEventListener("change", function () { if (grande.matches) gravar("menu", menu.checked ? "aberto" : "recolhido"); });
    var botao = document.getElementById("trocar-tema");
    function escuro() {
      var t = document.documentElement.dataset.theme;
      return t ? t === "night" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    }
    function marcar() { botao.setAttribute("aria-pressed", String(escuro())); }
    botao.addEventListener("click", function () {
      var novo = escuro() ? "winter" : "night";
      document.documentElement.dataset.theme = novo;
      gravar("tema", novo);
      marcar();
    });
    marcar();
  })();
</script>
</body>
</html>
```

(Os templates das telas continuam usando `{% block conteudo %}` e `{% block titulo %}`; o conteúdo antigo fica sem o estilo do Pico até as Tasks 2–6.)

- [ ] **Step 10: Gerar o CSS e ver passar**

Run: `uv run python scripts/gerar_css.py`
Expected: baixa as ferramentas na primeira vez e imprime `src/tcg_sniper/admin/static/admin.css: … bytes`.

Simplificar a asserção de `localStorage` em `test_tema_e_menu_usam_localstorage_protegido` para o que ela quer provar: `assert all("try {" in bloco for bloco in texto.split("localStorage")[1:] and [])` não é legível — troque a segunda linha do teste por:

```python
    for trecho in texto.split("localStorage")[1:]:
        anterior = texto[: texto.index(trecho)][-120:]
        assert "try {" in anterior, "localStorage fora de try"
```

Run: `uv run pytest -q tests/admin && uv run pytest -q && uv run ruff check .`
Expected: PASS. Testes de telas que conferem marcação do Pico podem falhar por causa do novo `base.html` (ex.: algo que dependa de `</nav>`); ajuste só a forma de localizar o trecho, nunca o que o teste prova.

- [ ] **Step 11: Commit**

```bash
git add scripts/gerar_css.py .gitignore src/tcg_sniper/admin tests/admin
git commit -m "feat: DaisyUI base for the admin (generated CSS, sidebar menu with counters, theme toggle, shared components)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Dashboard e Serviços

**Files:**
- Modify: `src/tcg_sniper/admin/templates/index.html`, `src/tcg_sniper/admin/templates/servicos.html`
- Modify: `src/tcg_sniper/admin/static/admin.css` (regenerado)
- Test: `tests/admin/test_admin_dashboard.py`, `tests/admin/test_admin_amazon.py` (só onde conferirem marcação), `tests/admin/test_admin_mensagens.py` (aviso do Dashboard)

**Interfaces:**
- Consumes (Task 1): macros `selo`, `cabecalho`, `aviso`, `paginacao` de `_componentes.html`; `request.state.menu` (`casamentos`, `ofertas`); global `icone`.
- Contexto já existente do Dashboard (não muda): `estado`, `em_andamento`, `ultima_liga`, `coleta_hora`, `coleta_jitter`, `estado_amazon`, `ciclo_amazon`, `ultimo_ciclo`, `fora_da_janela`, `janela`, `coletas`, `ciclos`, `pagina_liga`, `paginas_liga`, `pagina_amazon`, `paginas_amazon`, `liga_status`, `amazon_status`, `status_historico`, `link(**mudancas)`, `resumo_msgs` (`pendentes`, `falhas`, `ultimo_envio`, `aviso`, `link_aviso`, `notificador_parado`, `notificador_ultimo_ciclo`). Serviços: `estado`, `em_andamento`, `estado_amazon`, `ciclo_amazon`, `host`, `mensagem`, `notificador` (tupla estado, último ciclo).

- [ ] **Step 1: Testes (falham)**

Acrescentar a `tests/admin/test_admin_dashboard.py` (use o fixture `cliente` e helpers que o arquivo já tem):

```python
def test_dashboard_tem_indicadores_e_abas(cliente):
    texto = cliente.get("/").text
    assert 'class="stats' in texto
    for rotulo in ("LigaMagic", "Amazon", "WhatsApp", "Oportunidades abertas", "Casamentos pendentes"):
        assert rotulo in texto
    assert 'aria-label="Coletas da LigaMagic"' in texto and 'aria-label="Ciclos da Amazon"' in texto


def test_aba_da_amazon_abre_depois_de_paginar_ou_filtrar(cliente):
    def aba_amazon_marcada(texto):
        inicio = texto.index('aria-label="Ciclos da Amazon"')
        return "checked" in texto[texto.rindex("<input", 0, inicio):inicio + 60]

    assert not aba_amazon_marcada(cliente.get("/").text)
    assert aba_amazon_marcada(cliente.get("/", params={"amazon_status": "ok"}).text)
    assert aba_amazon_marcada(cliente.get("/", params={"amazon_pagina": "2"}).text)


def test_situacao_das_coletas_tem_selo(cliente, sessoes):
    coleta(sessoes, TipoColeta.LISTAGEM, T0, StatusColeta.FALHA)  # se o arquivo não tiver esse helper, crie a coleta com repo.iniciar_coleta/finalizar_coleta
    assert 'badge-error">falha</span>' in cliente.get("/").text
```

Em `tests/admin/test_admin_amazon.py`, acrescentar:

```python
def test_servicos_tem_selo_de_estado(cliente):
    texto = cliente.get("/servicos").text
    assert 'badge-success">ativo</span>' in texto
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/admin/test_admin_dashboard.py tests/admin/test_admin_amazon.py`
Expected: FAIL nos testes novos.

- [ ] **Step 3: `index.html`**

Substituir por:

```jinja
{% extends "base.html" %}
{% from "_componentes.html" import selo, cabecalho, aviso, paginacao %}
{% block conteudo %}
{{ cabecalho("Dashboard", "Resumo dos serviços e das últimas execuções") }}

{% if estado.estado.value != "ativo" %}
  {% call aviso("error", "LigaMagic pausada. " ~ (estado.motivo or "")) %}<a class="link" href="/servicos">Ir para Serviços</a>{% endcall %}
{% endif %}
{% if estado_amazon.estado.value != "ativo" %}
  {% call aviso("error", "Amazon pausada" ~ (" (CAPTCHA pendente)" if estado_amazon.estado.value == "pausado_desafio" else "") ~ ". " ~ (estado_amazon.motivo or "")) %}<a class="link" href="/servicos">Ir para Serviços</a>{% endcall %}
{% endif %}
{% if resumo_msgs.aviso %}
  {% set extra = " O notificador nunca rodou — veja Serviços." if resumo_msgs.notificador_parado == "nunca" else "" %}
  {% call aviso("warning", resumo_msgs.aviso ~ extra) %}
    {% if resumo_msgs.notificador_parado and resumo_msgs.notificador_parado != "nunca" %}O notificador está parado desde {{ resumo_msgs.notificador_ultimo_ciclo|data }} — veja Serviços.{% endif %}
    <a class="link" href="{{ resumo_msgs.link_aviso }}">Ir para Mensagens</a>
  {% endcall %}
{% endif %}

{% set menu = request.state.menu %}
<div class="stats stats-vertical w-full bg-base-100 shadow-sm md:stats-horizontal">
  <div class="stat">
    <div class="stat-title">LigaMagic</div>
    <div class="stat-value text-lg">{{ selo("ativo") if estado.estado.value == "ativo" else selo("pausado_desafio", "pausado por desafio") }}{% if em_andamento %} {{ selo("rodando", "coleta em andamento") }}{% endif %}</div>
    <div class="stat-desc">Última com sucesso: {% if ultima_liga %}{{ ultima_liga.iniciada_em|data }}{% else %}—{% endif %} · diária às {{ coleta_hora }} (± {{ coleta_jitter }} min)</div>
  </div>
  <div class="stat">
    <div class="stat-title">Amazon</div>
    <div class="stat-value text-lg">
      {% if estado_amazon.estado.value == "pausado_desafio" %}{{ selo("pausado_desafio", "CAPTCHA pendente") }}
      {% elif estado_amazon.estado.value == "pausado" %}{{ selo("pausado") }}
      {% elif fora_da_janela %}{{ selo("inativo", "Fora da janela (" ~ janela ~ ")") }}
      {% else %}{{ selo("ativo") }}{% endif %}
      {% if ciclo_amazon %}{{ selo("rodando", "ciclo em andamento") }}{% endif %}
    </div>
    <div class="stat-desc">Último ciclo: {% if ultimo_ciclo %}{{ ultimo_ciclo.finalizada_em|data }} · {{ ultimo_ciclo.produtos_ok }} ok, {{ ultimo_ciclo.produtos_falha }} falhas{% else %}—{% endif %}</div>
  </div>
  <div class="stat">
    <div class="stat-title">WhatsApp</div>
    <div class="stat-value text-lg tabular-nums">{{ resumo_msgs.pendentes }} <span class="text-sm font-normal">pendentes</span> · {{ resumo_msgs.falhas }} <span class="text-sm font-normal">falhas</span></div>
    <div class="stat-desc">Último envio: {{ resumo_msgs.ultimo_envio|data if resumo_msgs.ultimo_envio else "—" }} · <a class="link" href="/mensagens">Ver mensagens</a></div>
  </div>
  <div class="stat">
    <div class="stat-title">Oportunidades abertas</div>
    <div class="stat-value tabular-nums"><a class="link link-hover" href="/ofertas?situacao=abertas">{{ menu.ofertas }}</a></div>
  </div>
  <div class="stat">
    <div class="stat-title">Casamentos pendentes</div>
    <div class="stat-value tabular-nums"><a class="link link-hover" href="/casamentos">{{ menu.casamentos }}</a></div>
  </div>
</div>

{% macro historico(titulo, campo_status, campo_pagina, valor_status, linhas, pagina, paginas, vazio) %}
<form method="get" action="/" class="flex flex-wrap items-center gap-2">
  {% for nome, valor in [("liga_status", liga_status), ("amazon_status", amazon_status)] if nome != campo_status %}
  <input type="hidden" name="{{ nome }}" value="{{ valor }}">
  {% endfor %}
  <select name="{{ campo_status }}" class="select select-sm w-auto" aria-label="Status">
    {% for s in status_historico %}<option value="{{ s }}" {% if s == valor_status %}selected{% endif %}>{{ s }}</option>{% endfor %}
  </select>
  <button type="submit" class="btn btn-sm btn-primary">Filtrar</button>
</form>
<div class="card hidden bg-base-100 shadow-sm md:block"><div class="overflow-x-auto">
  <table class="table table-zebra">
    <thead><tr><th>#</th><th>Tipo</th><th>Início</th><th>Fim</th><th>Status</th><th class="text-right">OK</th><th class="text-right">Falhas</th><th>Erro</th></tr></thead>
    <tbody>
    {% for c in linhas %}
      <tr>
        <td class="tabular-nums">{{ c.id }}</td><td>{{ c.tipo.value }}</td><td class="whitespace-nowrap">{{ c.iniciada_em|data }}</td><td class="whitespace-nowrap">{{ c.finalizada_em|data }}</td>
        <td>{{ selo(c.status.value) }}</td><td class="text-right tabular-nums">{{ c.produtos_ok }}</td><td class="text-right tabular-nums">{{ c.produtos_falha }}</td><td>{{ c.erro or "" }}</td>
      </tr>
    {% else %}
      <tr><td colspan="8">{{ vazio }}</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div></div>
<div class="space-y-2 md:hidden">
  {% for c in linhas %}
  <div class="card bg-base-100 shadow-sm"><div class="card-body gap-1 p-4">
    <div class="flex items-center justify-between gap-2"><span class="font-medium">#{{ c.id }} · {{ c.tipo.value }}</span>{{ selo(c.status.value) }}</div>
    <div class="text-sm text-base-content/70">{{ c.iniciada_em|data }} → {{ c.finalizada_em|data }}</div>
    <div class="text-sm tabular-nums">{{ c.produtos_ok }} ok · {{ c.produtos_falha }} falhas{% if c.erro %} · {{ c.erro }}{% endif %}</div>
  </div></div>
  {% else %}
  <p class="text-sm">{{ vazio }}</p>
  {% endfor %}
</div>
{{ paginacao(pagina, paginas, lambda_link(campo_pagina)) }}
{% endmacro %}

{% set aba_amazon = amazon_status != "todos" or pagina_amazon > 1 %}
<div class="tabs tabs-border">
  <input type="radio" name="historico" class="tab" aria-label="Coletas da LigaMagic"{% if not aba_amazon %} checked{% endif %}>
  <div class="tab-content space-y-3 pt-4">
    {{ historico("Coletas da LigaMagic", "liga_status", "liga_pagina", liga_status, coletas, pagina_liga, paginas_liga, "Nenhuma coleta ainda.") }}
  </div>
  <input type="radio" name="historico" class="tab" aria-label="Ciclos da Amazon"{% if aba_amazon %} checked{% endif %}>
  <div class="tab-content space-y-3 pt-4">
    {{ historico("Ciclos da Amazon", "amazon_status", "amazon_pagina", amazon_status, ciclos, pagina_amazon, paginas_amazon, "Nenhum ciclo ainda.") }}
  </div>
</div>
{% endblock %}
```

`paginacao` recebe uma função `n -> url`. O `link` do Dashboard é `link(**mudancas)`; para passar uma função por campo, acrescentar no template, antes do `{% macro historico %}`:

```jinja
{% macro _url_pagina(campo, n) %}{{ link(**{campo: n}) }}{% endmacro %}
```

e trocar `lambda_link(campo_pagina)` por uma chamada que o Jinja aceite. Como o Jinja não tem lambda, adicione ao contexto do Dashboard em `app.py` (único ajuste de Python desta tarefa), dentro de `dashboard`, ao lado de `link`:

```python
            def link_pagina(campo: str):
                return lambda n: link(**{campo: n})
```

e `"link_pagina": link_pagina,` no dicionário do `TemplateResponse`; no template use `{{ paginacao(pagina, paginas, link_pagina(campo_pagina)) }}` e apague a macro `_url_pagina`.

- [ ] **Step 4: `servicos.html`**

Substituir por:

```jinja
{% extends "base.html" %}
{% from "_componentes.html" import selo, cabecalho, aviso %}
{% block titulo %}Serviços · TCG Sniper{% endblock %}
{% block conteudo %}
{{ cabecalho("Serviços", "Comandos dos coletores e estado do notificador") }}
{% if mensagem %}{{ aviso("success", mensagem) }}{% endif %}
<div class="grid gap-4 md:grid-cols-3">
  <div class="card bg-base-100 shadow-sm"><div class="card-body">
    <h2 class="card-title">LigaMagic
      {% if estado.estado.value == "pausado_desafio" %}{{ selo("pausado_desafio", "desafio pendente") }}
      {% elif em_andamento %}{{ selo("rodando", "coleta em andamento") }}
      {% else %}{{ selo("ativo") }}{% endif %}</h2>
    {% if estado.estado.value == "pausado_desafio" %}
      <p>Pausada: desafio pendente. {{ estado.motivo or "" }}</p>
      <p>Resolva em <a class="link" href="http://{{ host }}:6080/vnc.html">http://{{ host }}:6080/vnc.html</a> e clique em Retomar.</p>
      <div class="card-actions"><form method="post" action="/retomar"><button class="btn btn-primary">Retomar</button></form></div>
    {% elif em_andamento %}
      <p>Ativa. <strong>Coleta em andamento.</strong></p>
    {% else %}
      <p>Ativa.{% if estado.execucao_solicitada %} Execução solicitada; começa em até 1 minuto.{% endif %}</p>
      <div class="card-actions"><form method="post" action="/rodar-agora"><button class="btn btn-primary">Rodar agora</button></form></div>
    {% endif %}
  </div></div>
  <div class="card bg-base-100 shadow-sm"><div class="card-body">
    <h2 class="card-title">Amazon
      {% if estado_amazon.estado.value == "pausado_desafio" %}{{ selo("pausado_desafio", "CAPTCHA pendente") }}
      {% elif estado_amazon.estado.value == "pausado" %}{{ selo("pausado") }}
      {% else %}{{ selo("ativo") }}{% endif %}</h2>
    {% if estado_amazon.estado.value == "pausado_desafio" %}
      <p>Pausada: CAPTCHA pendente. {{ estado_amazon.motivo or "" }}</p>
      <p>Resolva em <a class="link" href="http://{{ host }}:6081/vnc.html">http://{{ host }}:6081/vnc.html</a> e clique em Retomar.</p>
      <div class="card-actions"><form method="post" action="/amazon/retomar"><button class="btn btn-primary">Retomar (Amazon)</button></form></div>
    {% elif estado_amazon.estado.value == "pausado" %}
      <p>Pausada. {{ estado_amazon.motivo or "" }}</p>
      <div class="card-actions"><form method="post" action="/amazon/retomar"><button class="btn btn-primary">Retomar (Amazon)</button></form></div>
    {% else %}
      <p>Ativa.{% if ciclo_amazon %} Ciclo em andamento desde {{ ciclo_amazon.iniciada_em|data }}.{% endif %}</p>
      <div class="card-actions"><form method="post" action="/amazon/pausar"><button class="btn btn-outline btn-error">Pausar (Amazon)</button></form></div>
    {% endif %}
  </div></div>
  <div class="card bg-base-100 shadow-sm"><div class="card-body">
    {% set estado_notif, ultimo_ciclo = notificador %}
    <h2 class="card-title">Notificador
      {% if estado_notif == "rodando" %}{{ selo("ativo", "rodando") }}{% else %}{{ selo("falha", "parado") }}{% endif %}</h2>
    {% if estado_notif == "rodando" %}<p>rodando</p>
    {% elif estado_notif == "parado" %}<p>parado desde {{ ultimo_ciclo|data }}</p>
    {% else %}<p>nunca rodou</p>{% endif %}
  </div></div>
</div>
{% endblock %}
```

- [ ] **Step 5: CSS, testes e commit**

Run: `uv run python scripts/gerar_css.py && uv run pytest -q tests/admin && uv run pytest -q && uv run ruff check .`
Expected: PASS. Ajuste nos testes existentes só a forma de localizar marcação (ex.: textos que agora estão dentro de selos), nunca o que provam.

```bash
git add src/tcg_sniper/admin tests/admin
git commit -m "feat: Dashboard and Services in DaisyUI (stats, history tabs, status badges)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Catálogo e página do produto

**Files:**
- Modify: `src/tcg_sniper/admin/templates/catalogo.html`, `src/tcg_sniper/admin/templates/_linha_produto.html`, `src/tcg_sniper/admin/templates/produto.html`
- Modify: `src/tcg_sniper/admin/app.py` (só passar `"link": link` ao contexto do Catálogo)
- Modify: `src/tcg_sniper/admin/static/admin.css` (regenerado)
- Test: `tests/admin/test_admin.py`

**Interfaces:**
- Consumes (Task 1): macros `selo`, `cabecalho`, `aviso`, `filtros`, `paginacao`; global `icone`.
- Contexto do Catálogo (existente): `busca`, `filtro`, `filtros`, `categoria`, `categorias`, `com_preco`, `mensagem`, `total`, `pagina`, `paginas`, `linhas` (pares `p, atual`), `link_anterior`, `link_proxima`; passa a ter também `link` (função `numero -> url` que já existe no handler). Produto: `p`, `atual`, `amazon` (trios `anuncio, atual, vendedor`), `historico_amazon` (pares `preco, asin`), `historico_listagem`, `historico_resumo`.
- `_linha_produto.html` é devolvido sozinho pelo htmx (`hx-swap="outerHTML"` em `#produto-<id>`): continua um `<tr id="produto-{{ p.id }}">`.

- [ ] **Step 1: Testes (falham)**

Acrescentar a `tests/admin/test_admin.py` (use o fixture `cliente` e helpers do arquivo):

```python
def test_catalogo_monitorar_e_um_toggle_htmx(cliente, sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "t1", nome="Caixa Toggle")
    texto = cliente.get("/catalogo").text
    assert f'hx-post="/produto/{p.id}/ativo"' in texto and 'class="toggle' in texto
    parcial = cliente.post(f"/produto/{p.id}/ativo").text
    assert parcial.lstrip().startswith(f'<tr id="produto-{p.id}"') and 'class="toggle' in parcial


def test_catalogo_tem_paginacao_numerada(cliente, sessoes):
    with sessoes() as s, s.begin():
        for i in range(250):
            criar_produto(s, f"pag{i}", nome=f"Produto {i:03d}")
    texto = cliente.get("/catalogo").text
    assert 'class="join"' in texto and ">2</a>" in texto


def test_produto_tem_abas_de_historico(cliente, sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "h1", nome="Caixa Histórico")
    texto = cliente.get(f"/produto/{p.id}").text
    assert 'aria-label="Preço à partir de"' in texto and 'aria-label="Histórico de venda"' in texto
```

(Ajuste nomes de helpers ao que `tests/admin/test_admin.py` já importa; a criação de 250 produtos pode reaproveitar o helper que os testes de paginação existentes usam.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/admin/test_admin.py`
Expected: FAIL nos novos.

- [ ] **Step 3: `app.py`**

No handler do Catálogo, no dicionário do `TemplateResponse` de `catalogo.html`, acrescentar `"link": link,` (a função `link(numero)` já existe ali e gera `link_anterior`/`link_proxima`).

- [ ] **Step 4: `_linha_produto.html`**

Substituir por:

```jinja
<tr id="produto-{{ p.id }}">
  <td class="min-w-0"><a class="link link-hover font-medium" href="/produto/{{ p.id }}">{{ p.nome }}</a><div class="text-xs text-base-content/60 md:hidden">{{ p.tipo or "" }}</div></td>
  <td class="hidden md:table-cell">{{ p.tipo or "" }}</td>
  <td class="text-right tabular-nums whitespace-nowrap">{% if atual and atual.listagem_em %}{{ atual.preco_a_partir|brl if atual.preco_a_partir is not none else "Indisponível" }}{% else %}—{% endif %}</td>
  <td class="hidden text-right tabular-nums whitespace-nowrap md:table-cell">{{ (atual.preco_min if atual else None)|brl }}</td>
  <td class="hidden text-right tabular-nums md:table-cell">{{ atual.num_lojas if atual and atual.num_lojas is not none else "—" }}</td>
  <td class="hidden whitespace-nowrap md:table-cell">{{ p.visto_primeiro_em|data }}</td>
  <td>
    <label class="flex items-center gap-2">
      <input type="checkbox" class="toggle toggle-success toggle-sm" {% if p.ativo %}checked{% endif %}
             hx-post="/produto/{{ p.id }}/ativo" hx-target="#produto-{{ p.id }}" hx-swap="outerHTML"
             aria-label="{{ 'Desativar' if p.ativo else 'Ativar' }} {{ p.nome }}">
      <span class="hidden text-sm md:inline">{{ "Ativo" if p.ativo else "Inativo" }}</span>
    </label>
  </td>
</tr>
```

(A linha é a mesma no computador e no celular: no celular as colunas secundárias ficam ocultas, e a tabela já está dentro de `overflow-x-auto`. Isso mantém o htmx trocando uma única `<tr>`.)

- [ ] **Step 5: `catalogo.html`**

Substituir por:

```jinja
{% extends "base.html" %}
{% from "_componentes.html" import cabecalho, aviso, filtros, paginacao %}
{% block titulo %}Catálogo · TCG Sniper{% endblock %}
{% block conteudo %}
{{ cabecalho("Catálogo", total ~ " produto(s) da LigaMagic") }}
{% call filtros(busca or filtro != filtros[0] or categoria or com_preco) %}
<form method="get" action="/catalogo" class="grid gap-2 md:grid-cols-5">
  <input type="search" name="busca" value="{{ busca }}" placeholder="Buscar por nome" class="input input-sm w-full md:col-span-2" aria-label="Buscar por nome">
  <select name="filtro" class="select select-sm w-full" aria-label="Situação">
    {% for f in filtros %}<option value="{{ f }}" {% if f == filtro %}selected{% endif %}>{{ f }}</option>{% endfor %}
  </select>
  <select name="categoria" class="select select-sm w-full" aria-label="Categoria">
    <option value="">todas as categorias</option>
    {% for c in categorias %}<option value="{{ c }}" {% if c == categoria %}selected{% endif %}>{{ c }}</option>{% endfor %}
  </select>
  <label class="label gap-2 text-sm"><input type="checkbox" name="com_preco" value="1" class="checkbox checkbox-sm" {% if com_preco %}checked{% endif %}> Só com preço</label>
  <button type="submit" class="btn btn-sm btn-primary md:col-start-5">Filtrar</button>
</form>
{% endcall %}
{% if mensagem %}{{ aviso("success", mensagem) }}{% endif %}
{% if total > 0 %}
<form method="post" action="/catalogo/lote" class="card bg-base-100 shadow-sm">
  <div class="card-body gap-2 p-4">
    <input type="hidden" name="busca" value="{{ busca }}">
    <input type="hidden" name="filtro" value="{{ filtro }}">
    <input type="hidden" name="categoria" value="{{ categoria }}">
    {% if com_preco %}<input type="hidden" name="com_preco" value="1">{% endif %}
    <div class="flex flex-wrap gap-2">
      <button type="submit" name="acao" value="ativar" class="btn btn-sm btn-success"
              onclick="return confirm('Ativar {{ total }} produto(s) deste filtro?')">Ativar todos os {{ total }} deste filtro</button>
      <button type="submit" name="acao" value="desativar" class="btn btn-sm btn-outline"
              onclick="return confirm('Desativar {{ total }} produto(s) deste filtro?')">Desativar todos os {{ total }} deste filtro</button>
    </div>
    <p class="text-xs text-base-content/70">Cada produto ativo = 1 visita/dia à LigaMagic (~17 s cada).</p>
  </div>
</form>
{% endif %}
<p class="text-sm text-base-content/70">Página {{ pagina }} de {{ paginas }} · {{ total }} produto(s)</p>
<div class="card bg-base-100 shadow-sm"><div class="overflow-x-auto">
  <table class="table">
    <thead><tr><th>Nome</th><th class="hidden md:table-cell">Categoria</th><th class="text-right">À partir de</th><th class="hidden text-right md:table-cell">Mín</th><th class="hidden text-right md:table-cell">Lojas</th><th class="hidden md:table-cell">Visto desde</th><th>Monitorar</th></tr></thead>
    <tbody>
    {% for p, atual in linhas %}
      {% include "_linha_produto.html" %}
    {% else %}
      <tr><td colspan="7">Nenhum produto encontrado.</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div></div>
{{ paginacao(pagina, paginas, link) }}
<p class="text-xs text-base-content/70">À partir de: menor preço pedido agora (listagem diária). Mín e Lojas: histórico de venda e
nº de lojas da página do produto (só produtos monitorados).</p>
{% endblock %}
```

(O macro `paginacao` repete "Página X de Y"; os testes existentes que procuram `"Página 1 de 3 · 250 produto(s)"` continuam valendo pela linha explícita acima da tabela. Se `link_anterior`/`link_proxima` ficarem sem uso no template, mantenha-os no contexto: os testes de "links anterior/próxima mantêm parâmetros" podem procurá-los; ajuste esses testes para procurar os parâmetros nos links numerados.)

- [ ] **Step 6: `produto.html`**

Substituir por:

```jinja
{% extends "base.html" %}
{% from "_componentes.html" import selo, cabecalho %}
{% block titulo %}{{ p.nome }} · TCG Sniper{% endblock %}
{% block conteudo %}
{% call cabecalho(p.nome, (p.tipo or "") ~ " · " ~ ("Monitorado" if p.ativo else "Não monitorado")) %}
  <a class="btn btn-sm btn-outline" href="{{ p.url }}" target="_blank" rel="noopener">{{ icone("arrow-top-right-on-square", "size-4") }} Ver na LigaMagic</a>
{% endcall %}
<div class="grid gap-4 md:grid-cols-2">
  <div class="card bg-base-100 shadow-sm"><div class="card-body">
    <h2 class="card-title text-base">Preço atual (listagem)</h2>
    <p class="text-2xl font-bold tabular-nums">{% if atual and atual.listagem_em %}{{ atual.preco_a_partir|brl if atual.preco_a_partir is not none else "Indisponível" }}{% else %}—{% endif %}</p>
    <p class="text-sm text-base-content/70">À partir de · lido em {{ (atual.listagem_em if atual else None)|data }}</p>
  </div></div>
  <div class="card bg-base-100 shadow-sm"><div class="card-body">
    <h2 class="card-title text-base">Histórico de venda</h2>
    <p class="tabular-nums">Mín {{ (atual.preco_min if atual else None)|brl }} · Médio {{ (atual.preco_medio if atual else None)|brl }} · Máx {{ (atual.preco_max if atual else None)|brl }}</p>
    <p class="text-sm text-base-content/70">Lojas: {{ atual.num_lojas if atual and atual.num_lojas is not none else "—" }} · atualizado em {{ (atual.resumo_em if atual else None)|data }}. Quadro "Preço Médio de Venda no Marketplace"; não é o preço pedido agora.</p>
  </div></div>
</div>
<div class="card bg-base-100 shadow-sm"><div class="card-body">
  <h2 class="card-title text-base">Amazon <span class="text-sm font-normal">(anúncios confirmados em {% if p.ativo %}<a class="link" href="/casamentos/produto/{{ p.id }}">Casamentos</a>{% else %}Casamentos{% endif %})</span></h2>
  <div class="overflow-x-auto"><table class="table">
    <thead><tr><th>ASIN</th><th class="text-right">Preço</th><th>Vendedor</th><th>Lido em</th></tr></thead>
    <tbody>
    {% for anuncio, atual_amz, vendedor in amazon %}
      <tr>
        <td><a class="link font-mono" href="{{ anuncio.url }}" target="_blank" rel="noopener">{{ anuncio.asin }}</a>{% if anuncio.variacao %}<div class="text-xs text-base-content/70">{{ anuncio.variacao }}</div>{% endif %}</td>
        <td class="text-right tabular-nums whitespace-nowrap">{{ (atual_amz.preco if atual_amz else None)|brl }}</td>
        <td>{{ atual_amz.envio|envio(vendedor) if atual_amz else "—" }}</td>
        <td class="whitespace-nowrap">{{ (atual_amz.coletado_em if atual_amz else None)|data }}</td>
      </tr>
    {% else %}
      <tr><td colspan="4">Nenhum anúncio da Amazon confirmado.</td></tr>
    {% endfor %}
    </tbody>
  </table></div>
</div></div>
<div class="tabs tabs-border">
  <input type="radio" name="historicos" class="tab" aria-label="Preço à partir de" checked>
  <div class="tab-content pt-4"><div class="card bg-base-100 shadow-sm"><div class="overflow-x-auto"><table class="table">
    <thead><tr><th>Data</th><th class="text-right">À partir de</th></tr></thead>
    <tbody>
    {% for r in historico_listagem %}
      <tr><td>{{ r.coletado_em|data }}</td><td class="text-right tabular-nums">{{ r.preco_a_partir|brl if r.preco_a_partir is not none else "Indisponível" }}</td></tr>
    {% else %}
      <tr><td colspan="2">Sem coletas de listagem ainda.</td></tr>
    {% endfor %}
    </tbody>
  </table></div></div></div>
  <input type="radio" name="historicos" class="tab" aria-label="Histórico de venda">
  <div class="tab-content pt-4"><div class="card bg-base-100 shadow-sm"><div class="overflow-x-auto"><table class="table">
    <thead><tr><th>Data</th><th class="text-right">Mín</th><th class="text-right">Médio</th><th class="text-right">Máx</th><th class="text-right">Lojas</th></tr></thead>
    <tbody>
    {% for r in historico_resumo %}
      <tr><td>{{ r.coletado_em|data }}</td><td class="text-right tabular-nums">{{ r.preco_min|brl }}</td><td class="text-right tabular-nums">{{ r.preco_medio|brl }}</td><td class="text-right tabular-nums">{{ r.preco_max|brl }}</td><td class="text-right tabular-nums">{{ r.num_lojas if r.num_lojas is not none else "—" }}</td></tr>
    {% else %}
      <tr><td colspan="5">Sem coletas da página do produto ainda (só produtos monitorados).</td></tr>
    {% endfor %}
    </tbody>
  </table></div></div></div>
  {% if historico_amazon %}
  <input type="radio" name="historicos" class="tab" aria-label="Preço na Amazon">
  <div class="tab-content pt-4"><div class="card bg-base-100 shadow-sm"><div class="overflow-x-auto"><table class="table">
    <thead><tr><th>Data</th><th>ASIN</th><th class="text-right">Preço</th><th>Origem</th></tr></thead>
    <tbody>
    {% for preco, asin in historico_amazon %}
      <tr><td>{{ preco.coletado_em|data }}</td><td class="font-mono">{{ asin }}</td><td class="text-right tabular-nums">{{ preco.preco|brl }}</td><td>{{ preco.origem.value }}</td></tr>
    {% endfor %}
    </tbody>
  </table></div></div></div>
  {% endif %}
</div>
{% endblock %}
```

(No `for` da Amazon a variável do laço muda para `atual_amz` para não esconder o `atual` da Liga usado acima.)

- [ ] **Step 7: CSS, testes e commit**

Run: `uv run python scripts/gerar_css.py && uv run pytest -q tests/admin && uv run pytest -q && uv run ruff check .`
Expected: PASS (ajustar só a localização de marcação em testes existentes do Catálogo/Produto).

```bash
git add src/tcg_sniper/admin tests/admin
git commit -m "feat: Catalog and product page in DaisyUI (toggle, numbered pagination, history tabs)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Casamentos, casamento do produto e Trocar

**Files:**
- Modify: `src/tcg_sniper/admin/templates/casamentos.html`, `casamentos_produto.html`, `trocar.html`
- Modify: `src/tcg_sniper/admin/static/admin.css` (regenerado)
- Test: `tests/admin/test_admin_casamentos.py`

**Interfaces:**
- Consumes (Task 1): macros `selo`, `cabecalho`, `aviso`, `filtros`, `paginacao`; global `icone`.
- Contexto (existente): Casamentos — `busca`, `situacao`, `situacoes`, `categoria`, `categorias`, `com_preco`, `total`, `linhas` (cada uma com `produto`, `preco_liga`, `pendentes`, `confirmados`, `ignorados`, `oportunidade`, `sem_par`), `pagina`, `paginas`, `link(n)`, `voltar_atual`. Casamento do produto — `d` (`produto`, `preco_liga`, `pendentes`, `confirmados`, `ignorados`, cada item com `anuncio`, `atual`, `vendedor`, `oportunidade`), `voltar`, `mensagem`, `erro`, `link_digitado`, `aqui`. Trocar — `anuncio`, `sugestoes` e `produtos` (pares `p, preco`), `busca`.

- [ ] **Step 1: Testes (falham)**

Acrescentar a `tests/admin/test_admin_casamentos.py`:

```python
def test_lista_de_casamentos_tem_selos(cliente, cenario):
    texto = cliente.get("/casamentos", params={"situacao": "todos"}).text
    assert 'badge-warning">oportunidade</span>' in texto
    assert ">sem par</span>" in texto


def test_pagina_do_produto_abre_na_aba_de_pendentes_ou_confirmados(cliente, cenario):
    def aba_marcada(texto, rotulo):
        inicio = texto.index(f'aria-label="{rotulo}')
        return "checked" in texto[texto.rindex("<input", 0, inicio):inicio + 80]

    com_pendente = cliente.get(f"/casamentos/produto/{cenario['a'].id}").text
    assert aba_marcada(com_pendente, "Pendentes")
    so_confirmado = cliente.get(f"/casamentos/produto/{cenario['d'].id}").text
    assert aba_marcada(so_confirmado, "Confirmados") and not aba_marcada(so_confirmado, "Pendentes")
```

(`cenario['d']` já tem um confirmado e um ignorado, sem pendentes; `cenario['a']` tem um pendente.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/admin/test_admin_casamentos.py`
Expected: FAIL nos novos.

- [ ] **Step 3: `casamentos.html`**

Substituir por:

```jinja
{% extends "base.html" %}
{% from "_componentes.html" import selo, cabecalho, filtros, paginacao %}
{% block titulo %}Casamentos · TCG Sniper{% endblock %}
{% block conteudo %}
{% set nomes = {"pendentes": "com pendentes", "oportunidade": "com oportunidade", "sem_par": "sem par", "casados": "casados", "todos": "todos"} %}
{{ cabecalho("Casamentos", "Anúncios da Amazon por produto da Liga · " ~ total ~ " produto(s)") }}
{% call filtros(busca or situacao != "pendentes" or categoria or com_preco) %}
<form method="get" action="/casamentos" class="grid gap-2 md:grid-cols-5">
  <input type="search" name="busca" value="{{ busca }}" placeholder="Buscar produto da Liga" class="input input-sm w-full md:col-span-2" aria-label="Buscar produto da Liga">
  <select name="situacao" class="select select-sm w-full" aria-label="Situação">
    {% for s in situacoes %}<option value="{{ s }}" {% if s == situacao %}selected{% endif %}>{{ nomes[s] }}</option>{% endfor %}
  </select>
  <select name="categoria" class="select select-sm w-full" aria-label="Categoria">
    <option value="">todas as categorias</option>
    {% for c in categorias %}<option value="{{ c }}" {% if c == categoria %}selected{% endif %}>{{ c }}</option>{% endfor %}
  </select>
  <label class="label gap-2 text-sm"><input type="checkbox" name="com_preco" value="1" class="checkbox checkbox-sm" {% if com_preco %}checked{% endif %}> Só com preço na Liga</label>
  <button type="submit" class="btn btn-sm btn-primary md:col-start-5">Filtrar</button>
</form>
{% endcall %}
<p class="text-sm text-base-content/70">{{ total }} produto(s)</p>
<div class="card hidden bg-base-100 shadow-sm md:block"><div class="overflow-x-auto">
  <table class="table table-zebra">
    <thead><tr><th>Produto da Liga</th><th class="text-right">À partir de</th><th class="text-right">Pendentes</th><th class="text-right">Confirmados</th><th class="text-right">Ignorados</th><th></th></tr></thead>
    <tbody>
    {% for l in linhas %}
      <tr>
        <td><a class="link link-hover font-medium" href="{{ l.produto.url }}" target="_blank" rel="noopener">{{ l.produto.nome }}</a>
          <div class="mt-1 flex flex-wrap gap-1">{% if l.oportunidade %}{{ selo("pendente", "oportunidade") }}{% endif %}{% if l.sem_par %}{{ selo("ignorado", "sem par") }}{% endif %}</div></td>
        <td class="text-right tabular-nums whitespace-nowrap">{{ l.preco_liga|brl }}</td>
        <td class="text-right tabular-nums">{{ l.pendentes }}</td><td class="text-right tabular-nums">{{ l.confirmados }}</td><td class="text-right tabular-nums">{{ l.ignorados }}</td>
        <td class="text-right"><a class="btn btn-sm btn-primary" href="/casamentos/produto/{{ l.produto.id }}?voltar={{ voltar_atual|urlencode }}">Abrir</a></td>
      </tr>
    {% else %}
      <tr><td colspan="6">Nenhum produto neste filtro.</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div></div>
<div class="space-y-3 md:hidden">
  {% for l in linhas %}
  <div class="card bg-base-100 shadow-sm"><div class="card-body gap-2 p-4">
    <a class="link link-hover font-medium" href="{{ l.produto.url }}" target="_blank" rel="noopener">{{ l.produto.nome }}</a>
    <div class="flex flex-wrap gap-1">{% if l.oportunidade %}{{ selo("pendente", "oportunidade") }}{% endif %}{% if l.sem_par %}{{ selo("ignorado", "sem par") }}{% endif %}</div>
    <div class="text-sm tabular-nums">{{ l.preco_liga|brl }} · {{ l.pendentes }} pendentes · {{ l.confirmados }} confirmados · {{ l.ignorados }} ignorados</div>
    <div class="card-actions justify-end"><a class="btn btn-sm btn-primary" href="/casamentos/produto/{{ l.produto.id }}?voltar={{ voltar_atual|urlencode }}">Abrir</a></div>
  </div></div>
  {% else %}
  <p class="text-sm">Nenhum produto neste filtro.</p>
  {% endfor %}
</div>
{{ paginacao(pagina, paginas, link) }}
{% endblock %}
```

- [ ] **Step 4: `casamentos_produto.html`**

Substituir por:

```jinja
{% extends "base.html" %}
{% from "_componentes.html" import selo, cabecalho, aviso %}
{% block titulo %}{{ d.produto.nome }} · Casamentos · TCG Sniper{% endblock %}
{% block conteudo %}
<a class="link text-sm" href="{{ voltar }}">← Voltar</a>
<div class="card bg-base-100 shadow-sm"><div class="card-body gap-3">
  {% call cabecalho(d.produto.nome, "À partir de " ~ (d.preco_liga|brl)) %}
    <a class="btn btn-sm btn-outline" href="{{ d.produto.url }}" target="_blank" rel="noopener">{{ icone("arrow-top-right-on-square", "size-4") }} Ver na LigaMagic</a>
  {% endcall %}
  {% if mensagem %}{{ aviso("success", mensagem) }}{% endif %}
  <form method="post" action="/casamentos/produto/{{ d.produto.id }}/link" class="space-y-1">
    <input type="hidden" name="voltar" value="{{ voltar }}">
    <div class="join w-full">
      <input name="link" value="{{ link_digitado }}" placeholder="Colar link da Amazon (ou o ASIN)" class="input join-item w-full{% if erro %} input-error{% endif %}" aria-label="Link da Amazon"{% if erro %} aria-invalid="true"{% endif %}>
      <button type="submit" class="btn btn-primary join-item">Casar</button>
    </div>
    {% if erro %}<p class="text-sm text-error">{{ erro }}</p>{% endif %}
  </form>
</div></div>

{% macro botao(anuncio, acao, rotulo, classe="btn-sm", produto_id=None) %}
<form method="post" action="/casamentos/{{ anuncio.id }}">
  <input type="hidden" name="acao" value="{{ acao }}"><input type="hidden" name="voltar" value="{{ aqui }}">
  {% if produto_id %}<input type="hidden" name="produto_id" value="{{ produto_id }}">{% endif %}
  <button class="btn {{ classe }}">{{ rotulo }}</button>
</form>
{% endmacro %}

{% macro titulo_anuncio(l) %}
<a class="link link-hover font-medium" href="{{ l.anuncio.url }}" target="_blank" rel="noopener">{{ l.anuncio.titulo_exibicao }}</a>
<div class="font-mono text-xs text-base-content/60">{{ l.anuncio.asin }}</div>
{% endmacro %}

{% set aba_confirmados = not d.pendentes and d.confirmados %}
<div class="tabs tabs-border">
  <input type="radio" name="anuncios" class="tab" aria-label="Pendentes ({{ d.pendentes|length }})"{% if not aba_confirmados %} checked{% endif %}>
  <div class="tab-content space-y-2 pt-4">
    {% for l in d.pendentes %}
    <div class="card bg-base-100 shadow-sm"><div class="card-body gap-2 p-4">
      {{ titulo_anuncio(l) }}
      <div class="flex flex-wrap items-center gap-2"><span class="tabular-nums">{{ (l.atual.preco if l.atual else None)|brl }}</span>{% if l.oportunidade %}{{ selo("pendente", "oportunidade") }}{% endif %}</div>
      <div class="card-actions">
        {{ botao(l.anuncio, "confirmar", "Confirmar", "btn-sm btn-success", produto_id=d.produto.id) }}
        {{ botao(l.anuncio, "ignorar", "Ignorar", "btn-sm btn-outline") }}
        <a href="/casamentos/{{ l.anuncio.id }}/trocar" class="btn btn-sm btn-ghost">É de outro produto</a>
      </div>
    </div></div>
    {% else %}
    <p class="text-sm">Nenhum anúncio pendente.</p>
    {% endfor %}
  </div>
  <input type="radio" name="anuncios" class="tab" aria-label="Confirmados ({{ d.confirmados|length }})"{% if aba_confirmados %} checked{% endif %}>
  <div class="tab-content space-y-2 pt-4">
    {% for l in d.confirmados %}
    <div class="card bg-base-100 shadow-sm"><div class="card-body gap-2 p-4">
      {{ titulo_anuncio(l) }}
      <div class="flex flex-wrap items-center gap-2 text-sm">
        <span class="tabular-nums">{{ (l.atual.preco if l.atual else None)|brl }}</span>
        {% if l.atual %}{{ selo("confirmado" if l.atual.envio.value in ("amazon", "fba") else "nao_verificado", l.atual.envio|envio(l.vendedor)) }}{% else %}{{ selo("nao_verificado", "sem leitura") }}{% endif %}
        <span class="text-base-content/60">{{ (l.atual.coletado_em if l.atual else None)|data }}</span>
      </div>
      <div class="card-actions">{{ botao(l.anuncio, "desfazer", "Desfazer", "btn-sm btn-outline") }}</div>
    </div></div>
    {% else %}
    <p class="text-sm">Nenhum anúncio confirmado.</p>
    {% endfor %}
  </div>
  <input type="radio" name="anuncios" class="tab" aria-label="Ignorados ({{ d.ignorados|length }})">
  <div class="tab-content space-y-2 pt-4">
    {% for l in d.ignorados %}
    <div class="card bg-base-100 shadow-sm"><div class="card-body gap-2 p-4">
      {{ titulo_anuncio(l) }}
      <div class="card-actions">{{ botao(l.anuncio, "desfazer", "Desfazer", "btn-sm btn-outline") }}</div>
    </div></div>
    {% else %}
    <p class="text-sm">Nenhum anúncio ignorado.</p>
    {% endfor %}
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: `trocar.html`**

Substituir por:

```jinja
{% extends "base.html" %}
{% from "_componentes.html" import cabecalho %}
{% block titulo %}Trocar casamento · TCG Sniper{% endblock %}
{% block conteudo %}
{{ cabecalho("Escolher o produto da Liga") }}
<div class="card bg-base-100 shadow-sm"><div class="card-body gap-1 p-4">
  <a class="link link-hover font-medium" href="{{ anuncio.url }}" target="_blank" rel="noopener">{{ anuncio.titulo_exibicao }}</a>
  <span class="font-mono text-xs text-base-content/60">({{ anuncio.asin }})</span>
</div></div>

{% macro linha(p, preco) %}
<li class="list-row items-center">
  <div class="min-w-0"><a class="link link-hover font-medium" href="{{ p.url }}" target="_blank" rel="noopener">{{ p.nome }}</a>
    <div class="text-sm tabular-nums text-base-content/70">{{ preco|brl }}</div></div>
  <form method="post" action="/casamentos/{{ anuncio.id }}">
    <input type="hidden" name="acao" value="confirmar"><input type="hidden" name="produto_id" value="{{ p.id }}">
    <input type="hidden" name="voltar" value="/casamentos/produto/{{ p.id }}">
    <button class="btn btn-sm btn-primary">Escolher</button>
  </form>
</li>
{% endmacro %}

{% if sugestoes %}
<h2 class="text-lg font-semibold">Parecidos</h2>
<ul class="list rounded-box bg-base-100 shadow-sm">{% for p, preco in sugestoes %}{{ linha(p, preco) }}{% endfor %}</ul>
{% endif %}

<h2 class="text-lg font-semibold">Buscar no catálogo da Liga</h2>
<form method="get" action="/casamentos/{{ anuncio.id }}/trocar" class="join w-full">
  <input type="search" name="busca" value="{{ busca }}" placeholder="Nome do produto na Liga" class="input join-item w-full" aria-label="Nome do produto na Liga">
  <button type="submit" class="btn btn-primary join-item">Buscar</button>
</form>
{% if produtos %}
<ul class="list rounded-box bg-base-100 shadow-sm">{% for p, preco in produtos %}{{ linha(p, preco) }}{% endfor %}</ul>
{% elif busca %}
<p class="text-sm">Nenhum produto encontrado.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 6: CSS, testes e commit**

Run: `uv run python scripts/gerar_css.py && uv run pytest -q tests/admin && uv run pytest -q && uv run ruff check .`
Expected: PASS. Testes existentes que procuram trechos como `'href="https://liga.test/produto/d" target="_blank" rel="noopener"'` continuam valendo (o `class` vem antes do `href`; se algum teste depender da ordem exata de atributos, ajuste só o trecho procurado).

```bash
git add src/tcg_sniper/admin tests/admin
git commit -m "feat: Matching screens in DaisyUI (badges, listing tabs, swap list)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Ofertas e Mensagens

**Files:**
- Modify: `src/tcg_sniper/admin/templates/ofertas.html`, `src/tcg_sniper/admin/templates/mensagens.html`
- Modify: `src/tcg_sniper/admin/static/admin.css` (regenerado)
- Test: `tests/admin/test_admin_ofertas.py`, `tests/admin/test_admin_mensagens.py`

**Interfaces:**
- Consumes (Task 1): macros `selo`, `selo_desconto`, `cabecalho`, `filtros`, `paginacao`.
- Contexto (existente): Ofertas — `f` (`busca`, `categoria`, `vendedor`, `situacao`, `ordem`), `categorias`, `desconto_texto`, `vendedores`, `ordens`, `desconto_min_pct`, `total`, `linhas` (`produto`, `anuncio`, `preco_liga`, `preco`, `desconto`, `diferenca`, `envio`, `vendedor`, `confiavel`, `verificado`, `aberta`, `coletado_em`), `pagina`, `paginas`, `link(n)`. Mensagens — `linhas` (`MensagemSaida`), `situacao`, `situacoes`, `destino`, `destinos`, `pagina`, `paginas`, `link(**mudancas)`, `aqui`.

- [ ] **Step 1: Testes (falham)**

Acrescentar a `tests/admin/test_admin_ofertas.py`:

```python
def test_desconto_e_vendedor_com_selo(cliente, cenario):
    texto = cliente.get("/ofertas").text
    assert 'badge-success' in texto and ">30,00%</span>" in texto  # caixa Amazon 30% ≥ 25%
    assert ">vendido pela Amazon</span>" in texto
```

Acrescentar a `tests/admin/test_admin_mensagens.py`:

```python
def test_situacao_da_mensagem_tem_selo(cliente, sessoes):
    criar(sessoes, status=StatusMensagem.FALHA, erro="HTTP 400: x")
    assert 'badge-error">falha</span>' in cliente.get("/mensagens").text
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/admin/test_admin_ofertas.py tests/admin/test_admin_mensagens.py`
Expected: FAIL nos novos.

- [ ] **Step 3: `ofertas.html`**

Substituir por:

```jinja
{% extends "base.html" %}
{% from "_componentes.html" import selo, selo_desconto, cabecalho, filtros, paginacao %}
{% block titulo %}Ofertas · TCG Sniper{% endblock %}
{% block conteudo %}
{% macro vendedor(l) -%}
{%- if not l.verificado -%}{{ selo("nao_verificado", "vendedor não verificado") }}<div class="text-xs text-base-content/60">preço lido só na busca</div>
{%- elif l.confiavel -%}{{ selo("confirmado", l.envio|envio(l.vendedor)) }}
{%- else -%}{{ selo("nao_verificado", l.envio|envio(l.vendedor)) }} <span class="text-xs text-base-content/60">(não elegível)</span>
{%- endif -%}
{%- endmacro %}
{% call cabecalho("Ofertas", "Amazon × LigaMagic · " ~ total ~ " produto(s)") %}
  <a class="btn btn-sm btn-outline" href="/ofertas?desconto_min={{ desconto_min_pct }}">≥ desconto configurado ({{ desconto_min_pct }}%)</a>
{% endcall %}
{% call filtros(f.busca or f.categoria or desconto_texto or f.vendedor != "todos" or f.situacao != "todas" or f.ordem != "desconto") %}
<form method="get" action="/ofertas" class="grid gap-2 md:grid-cols-4 lg:grid-cols-7">
  <input type="search" name="busca" value="{{ f.busca }}" placeholder="Buscar produto" class="input input-sm w-full md:col-span-2" aria-label="Buscar produto">
  <select name="categoria" class="select select-sm w-full" aria-label="Categoria">
    <option value="">todas as categorias</option>
    {% for c in categorias %}<option value="{{ c }}" {% if c == f.categoria %}selected{% endif %}>{{ c }}</option>{% endfor %}
  </select>
  <input type="number" name="desconto_min" min="0" max="100" value="{{ desconto_texto }}" placeholder="Desconto mínimo (%)" class="input input-sm w-full" aria-label="Desconto mínimo (%)">
  <select name="vendedor" class="select select-sm w-full" aria-label="Vendedor">
    {% for v in vendedores %}<option value="{{ v }}" {% if v == f.vendedor %}selected{% endif %}>{{ {"todos": "todos os vendedores", "amazon": "vendido pela Amazon", "fba": "lojista FBA", "elegiveis": "só elegíveis"}[v] }}</option>{% endfor %}
  </select>
  <select name="situacao" class="select select-sm w-full" aria-label="Situação">
    <option value="todas" {% if f.situacao == "todas" %}selected{% endif %}>todas</option>
    <option value="abertas" {% if f.situacao == "abertas" %}selected{% endif %}>só oportunidades abertas</option>
  </select>
  <select name="ordem" class="select select-sm w-full" aria-label="Ordem">
    {% for o in ordens %}<option value="{{ o }}" {% if o == f.ordem %}selected{% endif %}>{{ {"desconto": "maior desconto %", "diferenca": "maior diferença R$", "recentes": "leitura mais recente", "nome": "nome"}[o] }}</option>{% endfor %}
  </select>
  <button type="submit" class="btn btn-sm btn-primary">Filtrar</button>
</form>
{% endcall %}
<div class="card hidden bg-base-100 shadow-sm md:block"><div class="overflow-x-auto">
  <table class="table table-zebra">
    <thead><tr><th>Produto</th><th class="text-right">Liga (à partir de)</th><th class="text-right">Amazon</th><th class="text-right">Diferença (%)</th><th class="text-right">Diferença (R$)</th><th>Vendedor</th><th>Lido em</th></tr></thead>
    <tbody>
    {% for l in linhas %}
      <tr>
        <td><a class="link link-hover font-medium" href="/produto/{{ l.produto.id }}">{{ l.produto.nome }}</a>{% if l.aberta %} {{ selo("ok", "oportunidade") }}{% endif %}
          <div class="font-mono text-xs text-base-content/60">{{ l.anuncio.asin }}{% if l.anuncio.variacao %} · {{ l.anuncio.variacao }}{% endif %}</div></td>
        <td class="text-right tabular-nums whitespace-nowrap">{{ l.preco_liga|brl }}</td>
        <td class="text-right tabular-nums whitespace-nowrap"><a class="link" href="{{ l.anuncio.url }}" target="_blank" rel="noopener">{{ l.preco|brl }}</a></td>
        <td class="text-right">{{ selo_desconto(l.desconto, desconto_min_pct) }}</td>
        <td class="text-right tabular-nums whitespace-nowrap">{{ l.diferenca|brl }}</td>
        <td>{{ vendedor(l) }}</td>
        <td class="whitespace-nowrap text-base-content/70">{{ l.coletado_em|data }}</td>
      </tr>
    {% else %}
      <tr><td colspan="7">Nenhuma oferta neste filtro.</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div></div>
<div class="space-y-3 md:hidden">
  {% for l in linhas %}
  <div class="card bg-base-100 shadow-sm"><div class="card-body gap-3 p-4">
    <div><a class="link link-hover font-medium" href="/produto/{{ l.produto.id }}">{{ l.produto.nome }}</a>
      <div class="font-mono text-xs text-base-content/60">{{ l.anuncio.asin }}{% if l.anuncio.variacao %} · {{ l.anuncio.variacao }}{% endif %}</div></div>
    <div class="grid grid-cols-2 gap-2 text-sm tabular-nums">
      <div><div class="text-xs text-base-content/60">Liga</div>{{ l.preco_liga|brl }}</div>
      <div class="text-right"><div class="text-xs text-base-content/60">Amazon</div><a class="link" href="{{ l.anuncio.url }}" target="_blank" rel="noopener">{{ l.preco|brl }}</a></div>
    </div>
    <div class="flex flex-wrap items-center gap-2">{{ selo_desconto(l.desconto, desconto_min_pct) }}{% if l.aberta %}{{ selo("ok", "oportunidade") }}{% endif %}{{ vendedor(l) }}
      <span class="ml-auto text-xs text-base-content/60">{{ l.coletado_em|data }}</span></div>
  </div></div>
  {% else %}
  <p class="text-sm">Nenhuma oferta neste filtro.</p>
  {% endfor %}
</div>
{{ paginacao(pagina, paginas, link) }}
{% endblock %}
```

- [ ] **Step 4: `mensagens.html`**

Substituir por:

```jinja
{% extends "base.html" %}
{% from "_componentes.html" import selo, cabecalho, filtros, paginacao %}
{% block titulo %}Mensagens · TCG Sniper{% endblock %}
{% block conteudo %}
{{ cabecalho("Mensagens do WhatsApp", "Tabela de saída do notificador") }}
{% macro url_pagina(n) %}{{ link(pagina=n) }}{% endmacro %}
{% call filtros(situacao != "todas" or destino != "todos") %}
<form method="get" action="/mensagens" class="grid gap-2 md:grid-cols-4">
  <label class="form-control"><span class="label text-sm">Situação</span>
    <select name="situacao" class="select select-sm w-full">{% for v in situacoes %}<option value="{{ v }}" {% if v == situacao %}selected{% endif %}>{{ v }}</option>{% endfor %}</select></label>
  <label class="form-control"><span class="label text-sm">Destino</span>
    <select name="destino" class="select select-sm w-full">{% for v in destinos %}<option value="{{ v }}" {% if v == destino %}selected{% endif %}>{{ v }}</option>{% endfor %}</select></label>
  <button class="btn btn-sm btn-primary self-end">Filtrar</button>
</form>
{% endcall %}
{% macro acoes(m) %}
{% if m.status.value in ("falha", "expirada", "pendente") %}
<form method="post" action="/mensagens/{{ m.id }}" class="flex flex-wrap gap-1">
  <input type="hidden" name="voltar" value="{{ aqui }}">
  {% if m.status.value in ("falha", "expirada") %}<button name="acao" value="reenviar" class="btn btn-xs btn-primary">Reenviar</button>{% endif %}
  <button name="acao" value="descartar" class="btn btn-xs btn-outline">Descartar</button>
</form>
{% endif %}
{% endmacro %}
{% macro texto(m) %}
{% set partes = m.texto.split("\n") %}
<div style="white-space: pre-line">{{ partes[:2]|join("\n") }}</div>
{% if partes|length > 2 %}<details class="collapse collapse-arrow bg-base-200"><summary class="collapse-title min-h-0 py-1 text-xs">mais</summary><pre class="collapse-content text-xs whitespace-pre-wrap">{{ m.texto }}</pre></details>{% endif %}
{% endmacro %}
<div class="card hidden bg-base-100 shadow-sm md:block"><div class="overflow-x-auto">
  <table class="table">
    <thead><tr><th>Criada em</th><th>Destino</th><th>Texto</th><th>Situação</th><th class="text-right">Tentativas</th><th>Último erro</th><th>Enviada em</th><th></th></tr></thead>
    <tbody>
    {% for m in linhas %}
      <tr>
        <td class="whitespace-nowrap">{{ m.criada_em|data }}</td>
        <td>{{ m.destino }}</td>
        <td class="max-w-md">{{ texto(m) }}</td>
        <td>{{ selo(m.status.value) }}</td>
        <td class="text-right tabular-nums">{{ m.tentativas }}</td>
        <td class="max-w-xs text-sm">{{ m.ultimo_erro or "—" }}</td>
        <td class="whitespace-nowrap">{{ m.enviada_em|data if m.enviada_em else "—" }}</td>
        <td>{{ acoes(m) }}</td>
      </tr>
    {% else %}
      <tr><td colspan="8">Nenhuma mensagem.</td></tr>
    {% endfor %}
    </tbody>
  </table>
</div></div>
<div class="space-y-3 md:hidden">
  {% for m in linhas %}
  <div class="card bg-base-100 shadow-sm"><div class="card-body gap-2 p-4">
    <div class="flex items-center justify-between gap-2"><span class="text-sm">{{ m.criada_em|data }} · {{ m.destino }}</span>{{ selo(m.status.value) }}</div>
    {{ texto(m) }}
    {% if m.ultimo_erro %}<p class="text-xs text-error">{{ m.ultimo_erro }}</p>{% endif %}
    <div class="flex items-center justify-between gap-2"><span class="text-xs text-base-content/60">{{ m.tentativas }} tentativa(s){% if m.enviada_em %} · enviada {{ m.enviada_em|data }}{% endif %}</span>{{ acoes(m) }}</div>
  </div></div>
  {% else %}
  <p class="text-sm">Nenhuma mensagem.</p>
  {% endfor %}
</div>
{{ paginacao(pagina, paginas, url_pagina) }}
{% endblock %}
```

(O macro `url_pagina` funciona como a função `n -> url` que `paginacao` espera.) Os testes de Mensagens que procuram `action="/mensagens/{id}"` continuarão encontrando o formulário; como a tabela e os cartões repetem as ações, testes que contam ocorrências precisam contar só na tabela.

- [ ] **Step 5: CSS, testes e commit**

Run: `uv run python scripts/gerar_css.py && uv run pytest -q tests/admin && uv run pytest -q && uv run ruff check .`
Expected: PASS. O teste de Ofertas `test_vendedor_lido_so_na_busca_aparece_como_nao_verificado` usa o recorte até o primeiro `</tr>` (a tabela vem antes dos cartões); se o texto exato mudou ("vendedor não verificado" continua no selo), ajuste só o trecho procurado.

```bash
git add src/tcg_sniper/admin tests/admin
git commit -m "feat: Offers and Messages in DaisyUI (discount and seller badges, cards on phones)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Configurações em abas

**Files:**
- Modify: `src/tcg_sniper/admin/templates/configuracoes.html`
- Modify: `src/tcg_sniper/admin/app.py` (`_tela_configuracoes` passa `secao_ativa`)
- Modify: `src/tcg_sniper/admin/static/admin.css` (regenerado)
- Test: `tests/admin/test_admin_config_tela.py`

**Interfaces:**
- Consumes (Task 1): macros `cabecalho`, `aviso`.
- Contexto (existente): `secoes` (cada uma com `id`, `titulo`, `campos`, `rotulos`, `explicacoes`, `valores`, `erros`), `mensagem`, `categorias_padrao`; passa a ter `secao_ativa: str` (`"geral"`, `"liga"` ou `"amazon"`).

- [ ] **Step 1: Testes (falham)**

Acrescentar a `tests/admin/test_admin_config_tela.py`:

```python
def aba_marcada(texto, rotulo):
    inicio = texto.index(f'aria-label="{rotulo}"')
    return "checked" in texto[texto.rindex("<input", 0, inicio):inicio + 40]


def test_configuracoes_em_abas_abrindo_em_geral(cliente):
    texto = cliente.get("/configuracoes").text
    assert aba_marcada(texto, "Geral") and not aba_marcada(texto, "LigaMagic")


def test_aba_com_erro_abre_selecionada(cliente):
    r = cliente.post("/configuracoes/liga", data={**LIGA, "categorias": "abc"})
    assert r.status_code == 400 and aba_marcada(r.text, "LigaMagic") and not aba_marcada(r.text, "Geral")
    assert "input-error" in r.text


def test_aba_salva_abre_selecionada(cliente):
    r = cliente.post("/configuracoes/amazon", data=FORMULARIO_AMAZON, follow_redirects=True)
    assert aba_marcada(r.text, "Amazon")
```

(`FORMULARIO_AMAZON`: extraia para constante de módulo o dicionário que `test_salvar_amazon_na_rota_nova` monta inline e use nos dois testes.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q tests/admin/test_admin_config_tela.py`
Expected: FAIL nos novos.

- [ ] **Step 3: `app.py`**

Em `_tela_configuracoes`, no dicionário do `TemplateResponse`, acrescentar:

```python
                "secao_ativa": secao_com_erro or (msg if msg in ("geral", "liga", "amazon") else "geral"),
```

- [ ] **Step 4: `configuracoes.html`**

Substituir por:

```jinja
{% extends "base.html" %}
{% from "_componentes.html" import cabecalho, aviso %}
{% block titulo %}Configurações · TCG Sniper{% endblock %}
{% block conteudo %}
{{ cabecalho("Configurações", "As mudanças valem a partir da próxima coleta ou ciclo, sem reiniciar nada.") }}
{% if mensagem %}{{ aviso("success", mensagem) }}{% endif %}
<div class="tabs tabs-border">
{% for secao in secoes %}
  <input type="radio" name="secao" class="tab" aria-label="{{ secao.titulo }}"{% if secao.id == secao_ativa %} checked{% endif %}>
  <div class="tab-content pt-4" id="{{ secao.id }}">
    <div class="card bg-base-100 shadow-sm"><div class="card-body">
      {% if secao.erros %}{{ aviso("error", "Nada foi salvo. Corrija os campos marcados.") }}{% endif %}
      <form method="post" action="/configuracoes/{{ secao.id }}" class="grid gap-x-6 gap-y-3 md:grid-cols-2">
        {% for campo in secao.campos %}
        <fieldset class="fieldset{% if campo in ('categorias', 'url_listagem', 'url_busca') %} md:col-span-2{% endif %}">
          <legend class="fieldset-legend">{{ secao.rotulos[campo] }}</legend>
          <input id="{{ secao.id }}-{{ campo }}" name="{{ campo }}" value="{{ secao.valores[campo] }}" class="input w-full{% if campo in secao.erros %} input-error{% endif %}"{% if campo in secao.erros %} aria-invalid="true"{% endif %}>
          <p class="label whitespace-normal{% if campo in secao.erros %} text-error{% endif %}">{{ secao.erros[campo] if campo in secao.erros else secao.explicacoes[campo] }}</p>
          {% if secao.id == "liga" and campo == "categorias" %}
          <p class="label whitespace-normal">Padrão: {{ categorias_padrao }} · <a class="link" href="#" onclick="document.getElementById('liga-categorias').value='{{ categorias_padrao }}'; return false;">restaurar padrão</a> (depois clique em Salvar)</p>
          {% endif %}
        </fieldset>
        {% endfor %}
        <div class="md:col-span-2"><button class="btn btn-primary">Salvar {{ secao.titulo }}</button></div>
      </form>
    </div></div>
  </div>
{% endfor %}
</div>
<p class="text-xs text-base-content/70">Senhas, banco e chave da Evolution ficam no .env: ADMIN_SENHA, VNC_SENHA, EVOLUTION_API_KEY, DATABASE_URL, DIR_DADOS, EVOLUTION_URL.</p>
{% endblock %}
```

(As pausas mínima e máxima ficam lado a lado porque são campos consecutivos no grid de 2 colunas. `id="{{ secao.id }}-{{ campo }}" name="{{ campo }}" value="…"` mantém `name` e `value` contíguos, como os testes existentes procuram.)

- [ ] **Step 5: CSS, testes e commit**

Run: `uv run python scripts/gerar_css.py && uv run pytest -q tests/admin && uv run pytest -q && uv run ruff check .`
Expected: PASS. `test_tela_tem_as_tres_secoes_com_os_valores_salvos` confere a ordem `Geral < LigaMagic < Amazon` pelo índice no texto: o menu lateral não contém essas palavras como rótulo, mas "Amazon" aparece no menu? Não (os rótulos do menu são as 7 telas); se a ordem quebrar por outro texto, recorte o trecho a partir de `<main`.

```bash
git add src/tcg_sniper/admin tests/admin
git commit -m "feat: Settings in DaisyUI tabs (two-column fields, error tab opens selected)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Verificação de layout, README e CSS final

**Files:**
- Create: `scripts/verificar_layout.py`
- Modify: `README.md`
- Modify: `src/tcg_sniper/admin/static/admin.css` (regenerado na integração, se preciso)

**Interfaces:**
- Consumes: as telas das Tasks 1–6 rodando no container `admin`.

- [ ] **Step 1: Script**

Create `scripts/verificar_layout.py`:

```python
"""Confere o layout das telas do admin em 390 e 1440 px, nos temas winter e night.

Roda dentro do container do admin (precisa do Chromium do Playwright e da senha do admin):
  docker compose exec -T admin python - < scripts/verificar_layout.py

Falha (código 1) se alguma tela estourar a largura da janela ou tiver erro de script.
Salva os prints em /tmp/verificar_layout/ (docker cp para ver).
"""

import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
FIXAS = ["/", "/servicos", "/catalogo", "/casamentos?situacao=todos", "/ofertas", "/mensagens", "/configuracoes"]
TAMANHOS = {"celular": (390, 844), "computador": (1440, 900)}
SAIDA = Path("/tmp/verificar_layout")


def descobrir(pagina) -> list[str]:
    """Telas que dependem de um id: o primeiro produto de Casamentos e o primeiro anúncio pendente."""
    extras = []
    pagina.goto(BASE + "/casamentos?situacao=todos")
    abrir = pagina.locator('a:has-text("Abrir")').first
    if abrir.count():
        href = abrir.get_attribute("href")
        extras.append(href)
        pagina.goto(BASE + href)
        trocar = pagina.locator('a[href$="/trocar"]').first
        if trocar.count():
            extras.append(trocar.get_attribute("href"))
    pagina.goto(BASE + "/ofertas")
    produto = pagina.locator('a[href^="/produto/"]').first
    if produto.count():
        extras.append(produto.get_attribute("href"))
    return extras


def main() -> None:
    SAIDA.mkdir(exist_ok=True)
    problemas = []
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        credenciais = {"username": "admin", "password": os.environ["ADMIN_SENHA"]}
        for nome_tam, (largura, altura) in TAMANHOS.items():
            for tema in ("winter", "night"):
                contexto = navegador.new_context(viewport={"width": largura, "height": altura}, http_credentials=credenciais)
                contexto.add_init_script(f"try {{ localStorage.setItem('tema', '{tema}'); }} catch (e) {{}}")
                pagina = contexto.new_page()
                erros = []
                pagina.on("pageerror", lambda e: erros.append(str(e)))
                for caminho in FIXAS + descobrir(pagina):
                    erros.clear()
                    resposta = pagina.goto(BASE + caminho, wait_until="networkidle")
                    largura_doc = pagina.evaluate("document.documentElement.scrollWidth")
                    arquivo = re.sub(r"[^a-z0-9]+", "-", caminho.lower()).strip("-") or "dashboard"
                    pagina.screenshot(path=str(SAIDA / f"{arquivo}-{nome_tam}-{tema}.png"), full_page=True)
                    if resposta.status != 200:
                        problemas.append(f"{caminho} {nome_tam} {tema}: HTTP {resposta.status}")
                    if largura_doc > largura:
                        problemas.append(f"{caminho} {nome_tam} {tema}: largura {largura_doc} > {largura}")
                    if erros:
                        problemas.append(f"{caminho} {nome_tam} {tema}: erro de script {erros}")
                contexto.close()
        navegador.close()
    print("\n".join(problemas) or "layout ok")
    sys.exit(1 if problemas else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: README**

Em `README.md`, na seção de desenvolvimento (onde estão os comandos `uv run pytest`/`ruff`), acrescentar:

```markdown
### Visual do admin (DaisyUI)

O admin usa DaisyUI 5 sobre Tailwind CSS 4, com os temas winter (claro) e night (escuro). O CSS é gerado e fica versionado em `src/tcg_sniper/admin/static/admin.css`:

- Depois de mudar qualquer template do admin, rode `uv run python scripts/gerar_css.py` (baixa o Tailwind standalone e o DaisyUI em `.ferramentas/` na primeira vez). O teste `test_css_em_dia_com_os_templates` falha se você esquecer.
- Antes de um deploy que mexe no visual, rode `docker compose exec -T admin python - < scripts/verificar_layout.py`: abre as telas em 390 e 1440 px nos dois temas e falha se algo estourar a largura.
- Só use componentes e classes do DaisyUI/Tailwind; não escreva CSS próprio.
```

e, na tabela de telas do admin, trocar menções a "menu no topo" (se houver) por "menu lateral (recolhe para ícones no computador; botão de menu no celular)".

- [ ] **Step 3: Conferir e commitar**

Run: `uv run python scripts/gerar_css.py && uv run pytest -q && uv run ruff check .`
Expected: PASS.

```bash
git add scripts/verificar_layout.py README.md src/tcg_sniper/admin/static/admin.css
git commit -m "chore: layout check script and README for the DaisyUI admin

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Rodar a verificação no container (com o controlador, depois do deploy de teste)**

Run: `docker compose up -d --build admin && docker compose exec -T admin python - < scripts/verificar_layout.py`
Expected: `layout ok`. Problemas apontados entram na rodada de correção final.
