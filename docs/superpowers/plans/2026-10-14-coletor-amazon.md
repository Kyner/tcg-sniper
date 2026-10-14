# Coletor da Amazon, casamento e oportunidades (sub-projeto 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Procurar cada produto ativo da Liga na amazon.com.br pelo navegador, numa fila contínua de 08:00 às 22:00, casar os anúncios (ASIN) com o produto da Liga com revisão humana no admin, e avisar o grupo de oportunidades do WhatsApp quando uma oferta confiável estiver pelo menos 25% abaixo do "À partir de" da Liga.

**Architecture:** Um serviço novo, `coletor-amazon`, com a mesma imagem e comunicação só pelo Postgres. O navegador do sub-projeto 1 vira o pacote compartilhado `tcg_sniper/navegador`. A Amazon ganha parsers puros testados com fixtures reais recortadas, uma fila no banco, um laço contínuo (`VarreduraAmazon`) e um motor de oportunidades de funções puras. A configuração da Amazon e do motor fica na tabela `config_amazon`, editável no admin e relida a cada busca.

**Tech Stack:** Python 3.12, uv, SQLAlchemy 2 + psycopg 3, Alembic, Playwright (sync API), selectolax (lexbor), FastAPI + Jinja2 + HTMX, difflib, pytest, Postgres 16, Docker Compose, Evolution API.

**Spec:** `docs/superpowers/specs/2026-10-14-coletor-amazon-design.md`.

## Estado e ordem de execução

| Task | Situação |
| --- | --- |
| 1 a 14 | Pendentes |

Ordem: 1 → 14. Cada task termina com a suíte inteira passando (`uv run pytest -q`) e `uv run ruff check` limpo (use `uv run ruff check --fix` para a ordem dos imports, que o ruff organiza com constantes antes de classes). Os 3 testes de `tests/coletor_liga/test_navegador.py` continuam pulados sem `TESTAR_NAVEGADOR=1`.

## Global Constraints

- Nada de solucionador de CAPTCHA, disfarce de navegador ou nova tentativa automática diante de desafio. CAPTCHA ou bloqueio: o ciclo fecha como `pausada_desafio`, a linha `amazon` de `estado_coletor` vira `pausado_desafio`, o grupo admin recebe o link do noVNC na porta 6081, o Chromium fica aberto com a verificação, e só **Retomar (Amazon)** no admin continua.
- Tudo pelo navegador, sem API da Amazon.
- Chromium com `headless=False` e perfil persistente em `<DIR_DADOS>/perfil-amazon`, separado do perfil da Liga.
- Pausa humana aleatória entre `config_amazon.pausa_min_s` e `pausa_max_s` (padrão 8 e 20 s) antes de cada página da Amazon (busca, produto e vendedor).
- Fila contínua só dentro de `janela_inicio`–`janela_fim` (padrão 08:00–22:00, no fuso `FUSO` do `.env`), com variação aleatória de até 15 minutos na entrada e na saída, sorteada uma vez por dia. Teto de `max_buscas_hora` buscas por hora (padrão 200).
- Oportunidade só com ASIN `confirmado`, vendedor elegível (vendido pela Amazon, ou FBA com pelo menos `vendedor_min_positivas_pct`% de positivas e pelo menos `vendedor_min_avaliacoes` avaliações), "À partir de" da Liga não nulo e com no máximo `liga_preco_max_idade_h` horas, e `1 − preço_amazon / preço_liga ≥ desconto_min_pct / 100` (limite inclusivo). Envio `proprio` ou `desconhecido` nunca alerta.
- Alerta no grupo de oportunidades (`Destino.OPORTUNIDADES`) uma vez por oportunidade; de novo só se o preço cair a `preço ≤ preco_alertado × (1 − realerta_queda_pct / 100)` ou se a oportunidade fechar e reabrir. No máximo uma oportunidade aberta por anúncio.
- Preço ausente nunca vira zero: cartão ou página sem preço → `None`; texto de preço inválido → `ErroParser`.
- `preco_amazon` é append-only e só ganha linha quando o preço (ou, na origem `produto`, o vendedor ou o envio) muda em relação à última leitura do mesmo anúncio e origem, ou na primeira leitura do dia no fuso `FUSO`.
- Toda configuração de comportamento da Amazon e do motor fica em `config_amazon`, nunca no `.env`. O `.env` só ganha uso para `WHATSAPP_GRUPO_OPORTUNIDADES`, que já existe.
- O coletor relê `config_amazon` a cada passo do laço; mudanças no admin valem sem reiniciar.
- Nunca dois `coletor-amazon` ao mesmo tempo (advisory lock `7_202_611`, diferente do da Liga, `7_202_610`). Liga e Amazon podem rodar juntas.
- O reinício de um coletor só marca como interrompidas as coletas dos próprios tipos: Liga = `listagem` e `produtos`; Amazon = `amazon`.
- Dinheiro em `NUMERIC(10,2)`; datas `timestamptz` em UTC no banco, exibidas no fuso local.
- Falha de envio do notificador nunca interrompe a coleta.
- Nenhum teste acessa a Amazon, a LigaMagic ou o WhatsApp reais. Só HTML recortado vai para o repositório (`scripts/recortar_fixture.py`); páginas inteiras ficam em `.fixtures-brutas/` (fora do git).
- As pastas de teste não têm `__init__.py`: todo arquivo de teste novo precisa de um nome único em toda a pasta `tests/` (por isso `test_config_amazon.py`, `test_desafio_amazon.py`, `test_parsers_amazon.py`).
- Identificadores e mensagens em português; commits em inglês no formato `feat:`/`test:`/`chore:`/`fix:`/`docs:`.

## Review Focus

1. **Vendedor que se chama "Amazon…" sem ser a Amazon** (ex.: "Amazonas Games"). Esperado: só "Amazon" ou "Amazon.com.br" (sem diferença de maiúsculas e espaços) contam como vendido pela Amazon; o resto é lojista. Teste na Task 7 (`classificar_envio`).
2. **Configuração mudada no admin no meio da fila** (desconto de 25 para 30, pausa, teto). Esperado: vale na busca seguinte, sem reiniciar. Teste na Task 10.
3. **Produto desativado na Liga com oportunidade aberta ou no meio do ciclo.** Esperado: sai da fila no passo seguinte, o ciclo não fica esperando por ele para fechar, e nenhuma busca nova é feita para ele. Teste na Task 10.
4. **O mesmo ASIN em duas buscas de produtos diferentes da Liga.** Esperado: um anúncio só; a sugestão de casamento é a da primeira busca e não é trocada pela segunda; um ASIN confirmado para o produto A nunca vira candidato comparado com o preço do produto B. Testes nas Tasks 3 e 9.
5. **Termo de busca com caracteres especiais** (`&`, `+`, `#`, acentos). Esperado: codificados na URL (`quote_plus`), sem quebrar a busca. Teste na Task 9.

---

## Estrutura de arquivos

```
src/tcg_sniper/
  parsing.py                       ErroParser e parse_preco_brl (movidos da Liga, Task 7)
  navegador/                       (Task 1)
    __init__.py
    modelos.py                     Pagina, ErroRede
    base.py                        Navegador (Protocol: vivo, abrir)
    chromium.py                    NavegadorChromium (detector de desafio injetado)
    ritmo.py                       Dormir, pausa_aleatoria, com_um_retry, salvar_html_falha
  coletor_liga/
    modelos.py                     reexporta Pagina, ErroRede (Task 1) e ErroParser (Task 7)
    navegador.py                   Navegador (+abrir_expandindo), NavegadorPlaywright(NavegadorChromium)
    execucao.py                    usa navegador/ritmo.py
    parsers.py                     reexporta parse_preco_brl (Task 7)
    agendador.py                   lock_coleta(engine, id_lock), TIPOS_LIGA
  coletor_amazon/
    __init__.py
    modelos.py                     ResultadoBusca, OfertaProduto, AvaliacaoVendedor (Task 7)
    desafio.py                     eh_desafio_amazon (Task 7)
    parsers.py                     parse_busca, parse_produto_amazon, parse_vendedor, classificar_envio (Task 7)
    termo.py                       termo_busca (Task 5)
    fila.py                        Janela, janela_do_dia, intervalo_busca, TetoPorHora (Task 5)
    config.py                      validar_config, EXPLICACOES (Task 4)
    busca.py                       DesafioAmazon, processar_produto (Task 9)
    varredura.py                   VarreduraAmazon (Task 10)
  oportunidades/
    __init__.py
    motor.py                       Regras, RefLiga, Leitura, Acao, decidir... (Task 8)
    mensagens.py                   mensagem_oportunidade (Task 8)
  db/
    models.py                      tabelas novas, enums novos, LIMITES_CONFIG_AMAZON (Task 2)
    repositorio.py                 estado por coletor, marcar_interrompidas por tipo (Task 2)
    repositorio_amazon.py          fila, anúncios, preços, vendedores, oportunidades, casamento (Task 3)
    migrations/versions/7d3f1a2b9c4e_amazon.py (Task 2)
  admin/
    app.py, consultas.py           rotas e consultas novas (Tasks 12 a 14)
    consultas_amazon.py            consultas das telas da Amazon (Tasks 12 a 14)
    templates/                     configuracoes.html, casamentos.html, trocar.html, ofertas.html (Tasks 12 a 14)
  cli.py                           comando coletor-amazon (Task 11)
docker/coletor-entrypoint.sh       DIR_PERFIL (Task 11)
docker-compose.yml                 serviço coletor-amazon (Task 11)
scripts/capturar_fixture.py        detector pelo domínio, destino configurável (Task 6)
scripts/recortar_fixture.py        blocos da Amazon (Task 7)
tests/
  navegador/test_ritmo.py, test_chromium.py              (Task 1)
  db/test_repositorio_amazon.py, test_migracao.py        (Tasks 2, 3)
  coletor_amazon/test_config_amazon.py, test_termo.py, test_fila.py, test_desafio_amazon.py,
    test_parsers_amazon.py, test_busca.py, test_varredura.py    (Tasks 4 a 10)
  oportunidades/test_motor.py, test_mensagens.py         (Task 8)
  admin/test_admin_amazon.py                             (Tasks 12 a 14)
  fixtures/amazon/*.html                                 (Task 7, recortadas)
```

`tests/fakes.py` ganha `fixture_amazon`, `criar_anuncio` e `criar_preco_liga` (Tasks 3 e 7).

---

### Task 1: Pacote `navegador` compartilhado

Extrai o que não é da Liga: `Pagina`, `ErroRede`, o protocolo `Navegador` (`vivo`, `abrir`), o Chromium com perfil persistente (`NavegadorChromium`, com o detector de desafio injetado) e o ritmo (pausa aleatória, uma nova tentativa em erro de rede, salvar HTML com falha). A Liga continua com os mesmos nomes (`NavegadorPlaywright`, `Navegador` com `abrir_expandindo`, `pausa_humana`, `salvar_html_falha(config, ...)`), agora apoiados no pacote novo. Nenhum comportamento muda.

**Files:**
- Create: `src/tcg_sniper/navegador/__init__.py`, `src/tcg_sniper/navegador/modelos.py`, `src/tcg_sniper/navegador/base.py`, `src/tcg_sniper/navegador/chromium.py`, `src/tcg_sniper/navegador/ritmo.py`
- Modify: `src/tcg_sniper/coletor_liga/modelos.py`, `src/tcg_sniper/coletor_liga/navegador.py`, `src/tcg_sniper/coletor_liga/execucao.py`
- Modify: `tests/coletor_liga/test_navegador_limpeza.py` (alvo do monkeypatch)
- Test: `tests/navegador/test_ritmo.py`, `tests/navegador/test_chromium.py`

**Interfaces:**
- Produces:
  - `tcg_sniper.navegador.modelos.Pagina(url: str, status: int, html: str, titulo: str, headers: dict[str, str] = {})`, `ErroRede(Exception)`
  - `tcg_sniper.navegador.base.Navegador` (Protocol): `vivo() -> bool`, `abrir(url: str) -> Pagina`
  - `tcg_sniper.navegador.chromium.NavegadorChromium(dir_perfil: Path, eh_desafio: Callable[[Pagina], bool], timeout_ms: int = 45_000, espera_pos_carga_ms: int = 2_000)`, context manager; atributos `_pagina`, `_timeout_ms`, `_espera_ms`; métodos `_capturar(status, headers) -> Pagina`, `_capturar_se_possivel(status, headers) -> Pagina | None`
  - `tcg_sniper.navegador.ritmo`: `Dormir = Callable[[float], None]`, `ESPERA_RETRY_S = 30`, `pausa_aleatoria(min_s: float, max_s: float, dormir: Dormir, rng: random.Random | None = None) -> None`, `com_um_retry[T](abrir: Callable[[], T], url: str, dormir: Dormir) -> T`, `salvar_html_falha(dir_dados: Path, nome: str, html: str) -> Path`

- [ ] **Step 1: Escrever os testes do pacote novo**

Não crie `__init__.py` em `tests/navegador/`: as pastas de teste não são pacotes (o `pyproject.toml` põe `tests/` no `pythonpath`).

`tests/navegador/test_ritmo.py`:

```python
import random

import pytest

from tcg_sniper.navegador.modelos import ErroRede
from tcg_sniper.navegador.ritmo import ESPERA_RETRY_S, com_um_retry, pausa_aleatoria, salvar_html_falha


def test_pausa_aleatoria_dorme_dentro_do_intervalo():
    dormidas = []
    rng = random.Random(1)
    for _ in range(50):
        pausa_aleatoria(8, 20, dormidas.append, rng)
    assert all(8 <= d <= 20 for d in dormidas)


def test_com_um_retry_tenta_de_novo_uma_vez_depois_de_esperar():
    tentativas, dormidas = [], []

    def abrir():
        tentativas.append(1)
        if len(tentativas) == 1:
            raise ErroRede("timeout")
        return "ok"

    assert com_um_retry(abrir, "https://x.test", dormidas.append) == "ok"
    assert len(tentativas) == 2
    assert dormidas == [ESPERA_RETRY_S]


def test_com_um_retry_desiste_na_segunda_falha():
    def abrir():
        raise ErroRede("fora do ar")

    with pytest.raises(ErroRede):
        com_um_retry(abrir, "https://x.test", lambda _: None)


def test_salvar_html_falha(tmp_path):
    caminho = salvar_html_falha(tmp_path, "amazon-1-2", "<html>x</html>")
    assert caminho == tmp_path / "falhas" / "amazon-1-2.html"
    assert caminho.read_text(encoding="utf-8") == "<html>x</html>"
```

`tests/navegador/test_chromium.py` (mesmos falsos do Playwright de `tests/coletor_liga/test_navegador_limpeza.py`, reduzidos ao que `abrir` usa):

```python
import pytest
from playwright.sync_api import Error as PlaywrightError

from tcg_sniper.navegador.chromium import NavegadorChromium
from tcg_sniper.navegador.modelos import ErroRede


class PaginaPw:
    def __init__(self, titulo="Loja", html="<html></html>", erro_goto=None):
        self.titulo, self.html, self.url = titulo, html, "https://loja.test/x"
        self.erro_goto = erro_goto

    def goto(self, url, **_):
        if self.erro_goto:
            raise self.erro_goto

    def wait_for_timeout(self, _ms):
        pass

    def content(self):
        return self.html

    def title(self):
        return self.titulo


def navegador_com(pagina, detector):
    n = NavegadorChromium.__new__(NavegadorChromium)
    n._timeout_ms, n._espera_ms, n._eh_desafio = 1_000, 0, detector
    n._pagina = pagina
    return n


def test_erro_de_navegacao_com_desafio_do_detector_injetado_devolve_a_pagina():
    pagina = PaginaPw(titulo="Verificação", erro_goto=PlaywrightError("net::ERR_ABORTED"))
    resultado = navegador_com(pagina, lambda p: p.titulo == "Verificação").abrir("https://loja.test/p")
    assert resultado.titulo == "Verificação"


def test_erro_de_navegacao_sem_desafio_levanta_erro_rede():
    pagina = PaginaPw(erro_goto=PlaywrightError("net::ERR_TIMED_OUT"))
    with pytest.raises(ErroRede, match="ERR_TIMED_OUT"):
        navegador_com(pagina, lambda p: False).abrir("https://loja.test/p")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/navegador -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'tcg_sniper.navegador'`.

- [ ] **Step 3: Criar o pacote `navegador`**

`src/tcg_sniper/navegador/__init__.py`: arquivo vazio.

`src/tcg_sniper/navegador/modelos.py`:

```python
from dataclasses import dataclass, field


class ErroRede(Exception):
    """Falha de navegação: timeout, conexão, DNS."""


@dataclass(frozen=True)
class Pagina:
    url: str
    status: int
    html: str
    titulo: str
    headers: dict[str, str] = field(default_factory=dict)
```

`src/tcg_sniper/navegador/base.py`:

```python
from typing import Protocol

from tcg_sniper.navegador.modelos import Pagina


class Navegador(Protocol):
    def vivo(self) -> bool:
        """True se a instância ainda responde (a janela não foi fechada, o processo não morreu)."""

    def abrir(self, url: str) -> Pagina:
        """Abre a URL e devolve a página renderizada. Lança ErroRede em falha de navegação,
        exceto se a tela mostrar um desafio: aí devolve a página do desafio."""
```

`src/tcg_sniper/navegador/chromium.py` (o corpo de `__enter__`, `__exit__`, `vivo`, `_capturar`, `abrir` e `_capturar_se_possivel` é o de hoje em `coletor_liga/navegador.py`; muda só o detector, que agora é injetado):

```python
from collections.abc import Callable
from pathlib import Path
from typing import Self

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from tcg_sniper.navegador.modelos import ErroRede, Pagina


class NavegadorChromium:
    """Chromium visível com perfil persistente. Use como context manager.

    `eh_desafio` decide se a página na tela é um desafio do site (Cloudflare na Liga, CAPTCHA na
    Amazon): num erro de navegação com o desafio na tela, `abrir` devolve o desafio em vez de
    lançar ErroRede, para quem chamou pausar em vez de tentar de novo."""

    def __init__(
        self,
        dir_perfil: Path,
        eh_desafio: Callable[[Pagina], bool],
        timeout_ms: int = 45_000,
        espera_pos_carga_ms: int = 2_000,
    ):
        self._dir_perfil = dir_perfil
        self._eh_desafio = eh_desafio
        self._timeout_ms = timeout_ms
        self._espera_ms = espera_pos_carga_ms

    def __enter__(self) -> Self:
        self._dir_perfil.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        try:
            self._contexto = self._playwright.chromium.launch_persistent_context(
                str(self._dir_perfil),
                headless=False,
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                viewport={"width": 1366, "height": 768},
            )
            paginas = self._contexto.pages
            self._pagina = paginas[0] if paginas else self._contexto.new_page()
        except BaseException as erro:
            # Sem isso o driver do Playwright (processo node) fica órfão a cada falha de launch.
            self._playwright.stop()
            if isinstance(erro, PlaywrightError):
                raise ErroRede(f"Chromium não abriu: {erro}") from erro
            raise
        return self

    def __exit__(self, *_exc) -> None:
        try:
            self._contexto.close()
        finally:
            self._playwright.stop()

    def vivo(self) -> bool:
        try:
            return not self._pagina.is_closed() and self._pagina.evaluate("1") == 1
        except PlaywrightError:
            return False

    def _capturar(self, status: int, headers: dict[str, str]) -> Pagina:
        return Pagina(
            url=self._pagina.url,
            status=status,
            html=self._pagina.content(),
            titulo=self._pagina.title(),
            headers=headers,
        )

    def abrir(self, url: str) -> Pagina:
        try:
            resposta = self._pagina.goto(url, wait_until="load", timeout=self._timeout_ms)
            self._pagina.wait_for_timeout(self._espera_ms)
            return self._capturar(
                resposta.status if resposta else 0, dict(resposta.headers) if resposta else {}
            )
        except PlaywrightError as erro:
            # Erro de navegação com o desafio na tela: devolve o desafio (quem chamou pausa) em vez
            # de ErroRede, que levaria a um retry em cima do desafio.
            atual = self._capturar_se_possivel(0, {})
            if atual is not None and self._eh_desafio(atual):
                return atual
            raise ErroRede(f"{url}: {erro}") from erro

    def _capturar_se_possivel(self, status: int, headers: dict[str, str]) -> Pagina | None:
        try:
            return self._capturar(status, headers)
        except PlaywrightError:
            return None
```

`src/tcg_sniper/navegador/ritmo.py`:

```python
"""Ritmo humano e tolerância a falhas de rede, compartilhados pelos coletores."""

import logging
import random
from collections.abc import Callable
from pathlib import Path

from tcg_sniper.navegador.modelos import ErroRede

log = logging.getLogger(__name__)

Dormir = Callable[[float], None]
ESPERA_RETRY_S = 30


def pausa_aleatoria(min_s: float, max_s: float, dormir: Dormir, rng: random.Random | None = None) -> None:
    dormir((rng or random).uniform(min_s, max_s))


def com_um_retry[T](abrir: Callable[[], T], url: str, dormir: Dormir) -> T:
    try:
        return abrir()
    except ErroRede as erro:
        log.warning("erro de rede em %s (%s); nova tentativa em %ss", url, erro, ESPERA_RETRY_S)
        dormir(ESPERA_RETRY_S)
        return abrir()


def salvar_html_falha(dir_dados: Path, nome: str, html: str) -> Path:
    pasta = dir_dados / "falhas"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{nome}.html"
    caminho.write_text(html, encoding="utf-8")
    return caminho
```

- [ ] **Step 4: Apoiar a Liga no pacote novo**

Em `src/tcg_sniper/coletor_liga/modelos.py`: apague as classes `ErroRede` e `Pagina`, troque `from dataclasses import dataclass, field` por `from dataclasses import dataclass` e acrescente, logo abaixo dos imports, a reexportação (a forma `X as X` é a reexportação explícita que o ruff aceita):

```python
from tcg_sniper.navegador.modelos import ErroRede as ErroRede
from tcg_sniper.navegador.modelos import Pagina as Pagina
```

Substitua todo o `src/tcg_sniper/coletor_liga/navegador.py` por (o corpo de `abrir_expandindo` é o de hoje, sem mudança):

```python
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from tcg_sniper.coletor_liga.desafio import eh_desafio
from tcg_sniper.coletor_liga.modelos import ErroRede, PaginaExpandida
from tcg_sniper.coletor_liga.parsers import SELETOR_CARTAO
from tcg_sniper.navegador.base import Navegador as NavegadorBase
from tcg_sniper.navegador.chromium import NavegadorChromium

# Botão da listagem (fixture catalogo_pagina_1):
# <div id="exibir_mais_cards"><input onclick="mcards.nextPage(40);" type="button"
#  value="Exibir mais" class="exibir-mais"></div>
SELETOR_EXIBIR_MAIS = "#exibir_mais_cards input.exibir-mais"
JS_CONTAGEM_CRESCEU = "([seletor, antes]) => document.querySelectorAll(seletor).length > antes"


class Navegador(NavegadorBase, Protocol):
    def abrir_expandindo(
        self, url: str, max_cliques: int, pausar: Callable[[], None]
    ) -> PaginaExpandida:
        """Abre a listagem e clica em "Exibir mais" até o botão sumir, ficar oculto ou
        desabilitado, ou a quantidade de cartões parar de crescer. Chama `pausar()` antes de
        cada clique. Para em `max_cliques` cliques (`limite_atingido=True`). Se a página virar
        desafio (na carga ou depois de um clique), para de clicar e devolve a página do desafio.
        Lança ErroRede em falha de navegação."""


class NavegadorPlaywright(NavegadorChromium):
    """Chromium da LigaMagic: detector do Cloudflare e o clique em "Exibir mais"."""

    def __init__(self, dir_perfil: Path, timeout_ms: int = 45_000, espera_pos_carga_ms: int = 2_000):
        super().__init__(dir_perfil, eh_desafio, timeout_ms, espera_pos_carga_ms)

    def abrir_expandindo(
        self, url: str, max_cliques: int, pausar: Callable[[], None]
    ) -> PaginaExpandida:
        status, headers, cliques = 0, {}, 0
        try:
            resposta = self._pagina.goto(url, wait_until="load", timeout=self._timeout_ms)
            self._pagina.wait_for_timeout(self._espera_ms)
            status = resposta.status if resposta else 0
            headers = dict(resposta.headers) if resposta else {}
            while True:
                pagina = self._capturar(status, headers)
                if eh_desafio(pagina):
                    return PaginaExpandida(pagina, cliques, limite_atingido=False)
                botao = self._pagina.locator(SELETOR_EXIBIR_MAIS).first
                if botao.count() == 0 or not botao.is_visible() or not botao.is_enabled():
                    return PaginaExpandida(pagina, cliques, limite_atingido=False)
                if cliques >= max_cliques:
                    return PaginaExpandida(pagina, cliques, limite_atingido=True)
                antes = self._pagina.locator(SELETOR_CARTAO).count()
                pausar()
                botao.click(timeout=self._timeout_ms)
                cliques += 1
                try:
                    self._pagina.wait_for_function(
                        JS_CONTAGEM_CRESCEU, arg=[SELETOR_CARTAO, antes], timeout=self._timeout_ms
                    )
                except PlaywrightTimeoutError:
                    # Clicou e nada novo apareceu: fim da lista (ou a página mudou; quem chamou
                    # verifica desafio na página devolvida).
                    return PaginaExpandida(self._capturar(status, headers), cliques, limite_atingido=False)
                self._pagina.wait_for_timeout(self._espera_ms)
        except PlaywrightError as erro:
            # Um clique pode levar a uma navegação para o desafio: nesse caso devolve o desafio.
            atual = self._capturar_se_possivel(status, headers)
            if atual is not None and eh_desafio(atual):
                return PaginaExpandida(atual, cliques, limite_atingido=False)
            raise ErroRede(f"{url}: {erro}") from erro
```

Em `src/tcg_sniper/coletor_liga/execucao.py`:

1. Apague `import random`, `Dormir = Callable[[float], None]` e `ESPERA_RETRY_S = 30`, e acrescente aos imports:

```python
from tcg_sniper.navegador import ritmo
from tcg_sniper.navegador.ritmo import ESPERA_RETRY_S as ESPERA_RETRY_S
from tcg_sniper.navegador.ritmo import Dormir as Dormir
from tcg_sniper.navegador.ritmo import com_um_retry, pausa_aleatoria
```

(`Dormir` e `ESPERA_RETRY_S` continuam importáveis de `execucao`, como `listagens.py`, `produtos.py` e os testes fazem hoje.) Se `Callable` deixar de ser usado no arquivo, tire-o do import; o ruff avisa.

2. Troque o corpo de `pausa_humana` por `pausa_aleatoria(config.pausa_min_s, config.pausa_max_s, dormir)`.
3. Apague a função `_com_um_retry` e troque as duas chamadas `_com_um_retry(` por `com_um_retry(`.
4. Troque o corpo de `salvar_html_falha(config, nome, html)` por `return ritmo.salvar_html_falha(config.dir_dados, nome, html)`.

Em `tests/coletor_liga/test_navegador_limpeza.py`, troque a linha `from tcg_sniper.coletor_liga import navegador as modulo` por `from tcg_sniper.navegador import chromium as modulo` (o `sync_playwright` agora é importado em `chromium.py`). A função `navegador_com` do arquivo monta um `NavegadorPlaywright` com `__new__`: acrescente `n._eh_desafio = eh_desafio` e o import `from tcg_sniper.coletor_liga.desafio import eh_desafio`.

- [ ] **Step 5: Rodar a suíte inteira**

Run: `uv run pytest -q && uv run ruff check`
Expected: tudo passa (os testes novos e todos os da Liga, sem mudança de resultado); ruff limpo.

- [ ] **Step 6: Commit**

```bash
git add src/tcg_sniper/navegador src/tcg_sniper/coletor_liga/modelos.py src/tcg_sniper/coletor_liga/navegador.py src/tcg_sniper/coletor_liga/execucao.py tests/navegador tests/coletor_liga/test_navegador_limpeza.py
git commit -m "refactor: extract the shared navegador package from the Liga collector"
```

---

### Task 2: Banco: tabelas da Amazon, estado por coletor e interrupção por tipo

**Files:**
- Modify: `src/tcg_sniper/db/models.py`
- Create: `src/tcg_sniper/db/migrations/versions/7d3f1a2b9c4e_amazon.py`
- Modify: `src/tcg_sniper/db/repositorio.py` (`obter_estado`, `pausar_por_desafio`, `retomar`, `pausar`, `marcar_interrompidas`)
- Modify: `src/tcg_sniper/coletor_liga/agendador.py` (`TIPOS_LIGA`, `lock_coleta(engine, id_lock)`)
- Modify: `src/tcg_sniper/admin/consultas.py` (`coleta_em_andamento(s, tipos)`), `src/tcg_sniper/admin/app.py` (chamada)
- Test: `tests/db/test_migracao.py`, `tests/db/test_repositorio.py`

**Interfaces:**
- Produces (em `tcg_sniper.db.models`):
  - `TipoColeta.AMAZON = "amazon"`; `EstadoColetorTipo.PAUSADO = "pausado"`
  - `StatusCasamento` (`PENDENTE`, `CONFIRMADO`, `IGNORADO`), `OrigemPreco` (`BUSCA`, `PRODUTO`), `Envio` (`AMAZON`, `FBA`, `PROPRIO`, `DESCONHECIDO`)
  - `COLETOR_LIGA = "liga"`, `COLETOR_AMAZON = "amazon"`
  - `EstadoColetor.coletor: str`
  - `AnuncioAmazon`, `VendedorAmazon`, `PrecoAmazon`, `PrecoAtualAmazon`, `FilaAmazon`, `Oportunidade`, `ConfigAmazon` (colunas como abaixo)
  - `LIMITES_CONFIG_AMAZON: dict[str, tuple[int, int]]`, `PADROES_CONFIG_AMAZON: dict[str, object]`
- Produces (em `tcg_sniper.db.repositorio`):
  - `ID_COLETOR = {"liga": 1, "amazon": 2}`
  - `obter_estado(s, agora=None, coletor=COLETOR_LIGA) -> EstadoColetor`
  - `pausar_por_desafio(s, motivo, agora, coletor=COLETOR_LIGA)`, `retomar(s, agora, coletor=COLETOR_LIGA)`
  - `pausar(s, motivo: str, agora: datetime, coletor: str) -> None` (estado `pausado`)
  - `marcar_interrompidas(s, agora, tipos: Sequence[TipoColeta]) -> int`
- Produces (em `tcg_sniper.coletor_liga.agendador`): `TIPOS_LIGA = (TipoColeta.LISTAGEM, TipoColeta.PRODUTOS)`, `lock_coleta(engine, id_lock: int = ID_LOCK)`
- Produces (em `tcg_sniper.admin.consultas`): `coleta_em_andamento(s, tipos: Sequence[TipoColeta]) -> bool`

- [ ] **Step 1: Escrever os testes**

Em `tests/db/test_migracao.py`, troque `test_estado_coletor_aceita_so_uma_linha` por estes (e acrescente os imports `from decimal import Decimal`, `from sqlalchemy import select`, `from sqlalchemy import update` e os modelos usados):

```python
from tcg_sniper.db.models import (
    Base,
    ConfigAmazon,
    EstadoColetor,
    EstadoColetorTipo,
    PADROES_CONFIG_AMAZON,
    VendedorAmazon,
)


def test_estado_coletor_aceita_so_as_linhas_dos_coletores(s):
    agora = datetime.now(UTC)
    s.add(EstadoColetor(id=3, coletor="outro", estado=EstadoColetorTipo.ATIVO, atualizado_em=agora))
    with pytest.raises(IntegrityError):
        s.flush()


def test_migracao_cria_estado_da_amazon_ativo(s):
    estado = s.get(EstadoColetor, 2)
    assert (estado.coletor, estado.estado) == ("amazon", EstadoColetorTipo.ATIVO)


def test_migracao_cria_config_amazon_com_os_padroes(s):
    config = s.get(ConfigAmazon, 1)
    for campo, valor in PADROES_CONFIG_AMAZON.items():
        assert getattr(config, campo) == valor, campo


def test_migracao_cria_o_vendedor_amazon(s):
    vendedor = s.scalar(select(VendedorAmazon).where(VendedorAmazon.seller_id == "amazon"))
    assert vendedor.nome == "Amazon.com.br"


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("resultados_por_busca", 0),
        ("resultados_por_busca", 49),
        ("max_buscas_hora", 401),
        ("desconto_min_pct", 0),
        ("intervalo_busca_min", 9),
        ("pausa_max_s", 121),
        ("url_busca", "https://www.amazon.com.br/s?k=x"),
    ],
)
def test_config_amazon_recusa_valores_fora_dos_limites(s, campo, valor):
    s.execute(update(ConfigAmazon).where(ConfigAmazon.id == 1).values({campo: valor}))
    with pytest.raises(IntegrityError):
        s.flush()


def test_config_amazon_recusa_pausa_minima_maior_que_a_maxima(s):
    s.execute(update(ConfigAmazon).where(ConfigAmazon.id == 1).values(pausa_min_s=30, pausa_max_s=20))
    with pytest.raises(IntegrityError):
        s.flush()
```

Em `tests/db/test_repositorio.py`, troque `test_marcar_interrompidas` e acrescente os testes de estado por coletor (imports: `COLETOR_AMAZON` de `tcg_sniper.db.models`):

```python
def test_marcar_interrompidas_so_dos_tipos_pedidos(s):
    rodando = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0)
    pronta = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0)
    repo.finalizar_coleta(s, pronta.id, StatusColeta.OK, 1, 0, T0)
    ciclo_amazon = repo.iniciar_coleta(s, TipoColeta.AMAZON, T0)

    assert repo.marcar_interrompidas(s, T0 + timedelta(hours=1), (TipoColeta.LISTAGEM, TipoColeta.PRODUTOS)) == 1
    s.expire_all()
    assert s.get(Coleta, rodando.id).status is StatusColeta.FALHA
    assert s.get(Coleta, rodando.id).erro == "interrompida"
    assert s.get(Coleta, pronta.id).status is StatusColeta.OK
    assert s.get(Coleta, ciclo_amazon.id).status is StatusColeta.RODANDO


def test_estado_por_coletor_e_independente(s):
    repo.pausar_por_desafio(s, "desafio em /x", T0)
    assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.ATIVO

    repo.pausar(s, "erros seguidos", T0, COLETOR_AMAZON)
    amazon = repo.obter_estado(s, coletor=COLETOR_AMAZON)
    assert (amazon.estado, amazon.motivo) == (EstadoColetorTipo.PAUSADO, "erros seguidos")
    assert repo.obter_estado(s).estado is EstadoColetorTipo.PAUSADO_DESAFIO

    repo.retomar(s, T0, COLETOR_AMAZON)
    assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.ATIVO
    assert repo.obter_estado(s).estado is EstadoColetorTipo.PAUSADO_DESAFIO
```

Em `tests/admin/test_admin.py`, acrescente:

```python
def test_ciclo_da_amazon_rodando_nao_conta_como_coleta_da_liga_em_andamento(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.iniciar_coleta(s, TipoColeta.AMAZON, T0)
    assert "Rodar agora" in cliente.get("/").text
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/db tests/admin -q`
Expected: FAIL (`ImportError: cannot import name 'ConfigAmazon'`).

- [ ] **Step 3: Modelos**

Em `src/tcg_sniper/db/models.py`:

1. Imports: acrescente `time` em `from datetime import datetime, time`; acrescente `Index`, `Time`, `UniqueConstraint` e `text` ao `from sqlalchemy import (...)`.
2. Enums: acrescente `AMAZON = "amazon"  # ciclo da fila de buscas na Amazon` em `TipoColeta` e `PAUSADO = "pausado"  # pausa manual pelo admin ou por erros seguidos` em `EstadoColetorTipo`. Logo abaixo de `EstadoColetorTipo`, acrescente:

```python
class StatusCasamento(enum.StrEnum):
    PENDENTE = "pendente"
    CONFIRMADO = "confirmado"
    IGNORADO = "ignorado"


class OrigemPreco(enum.StrEnum):
    BUSCA = "busca"  # cartão do resultado de busca
    PRODUTO = "produto"  # oferta principal da página do produto


class Envio(enum.StrEnum):
    AMAZON = "amazon"  # vendido pela Amazon
    FBA = "fba"  # vendido por lojista, enviado pela Amazon
    PROPRIO = "proprio"  # vendido e enviado por lojista
    DESCONHECIDO = "desconhecido"


COLETOR_LIGA = "liga"
COLETOR_AMAZON = "amazon"
```

3. Troque a classe `EstadoColetor` por:

```python
class EstadoColetor(Base):
    """Uma linha por coletor: id 1 = Liga, id 2 = Amazon (ver `repositorio.ID_COLETOR`)."""

    __tablename__ = "estado_coletor"
    __table_args__ = (
        CheckConstraint("id IN (1, 2)", name="ck_estado_coletor_linhas"),
        UniqueConstraint("coletor", name="uq_estado_coletor_coletor"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    coletor: Mapped[str] = mapped_column(Text)
    estado: Mapped[EstadoColetorTipo] = mapped_column(_enum(EstadoColetorTipo, "estado_coletor_tipo"))
    motivo: Mapped[str | None] = mapped_column(Text)
    execucao_solicitada: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    atualizado_em: Mapped[datetime] = mapped_column(DATA)
```

4. No fim do arquivo:

```python
class AnuncioAmazon(Base):
    """Um anúncio (ASIN) da amazon.com.br e o casamento com um produto da Liga.

    Enquanto `pendente`, `produto_id` é a sugestão (o produto cuja busca achou o ASIN); quando
    `confirmado`, é o casamento. Um ASIN casa com no máximo um produto da Liga."""

    __tablename__ = "anuncio_amazon"

    id: Mapped[int] = mapped_column(primary_key=True)
    asin: Mapped[str] = mapped_column(Text, unique=True)
    titulo: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    produto_id: Mapped[int | None] = mapped_column(ForeignKey("produto_liga.id"))
    status_casamento: Mapped[StatusCasamento] = mapped_column(_enum(StatusCasamento, "status_casamento"))
    revisado_em: Mapped[datetime | None] = mapped_column(DATA)
    visto_primeiro_em: Mapped[datetime] = mapped_column(DATA)
    visto_ultimo_em: Mapped[datetime] = mapped_column(DATA)


class VendedorAmazon(Base):
    """Vendedor da Amazon. A própria Amazon é a linha fixa `seller_id = 'amazon'` (migração)."""

    __tablename__ = "vendedor_amazon"

    id: Mapped[int] = mapped_column(primary_key=True)
    seller_id: Mapped[str] = mapped_column(Text, unique=True)
    nome: Mapped[str | None] = mapped_column(Text)
    pct_positivas: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    num_avaliacoes: Mapped[int | None] = mapped_column(Integer)
    avaliado_em: Mapped[datetime | None] = mapped_column(DATA)


class PrecoAmazon(Base):
    """Histórico append-only: uma linha quando o preço (ou vendedor/envio) muda, ou na 1ª leitura do dia."""

    __tablename__ = "preco_amazon"

    id: Mapped[int] = mapped_column(primary_key=True)
    anuncio_id: Mapped[int] = mapped_column(ForeignKey("anuncio_amazon.id"))
    coletado_em: Mapped[datetime] = mapped_column(DATA)
    preco: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    origem: Mapped[OrigemPreco] = mapped_column(_enum(OrigemPreco, "origem_preco"))
    vendedor_id: Mapped[int | None] = mapped_column(ForeignKey("vendedor_amazon.id"))
    envio: Mapped[Envio] = mapped_column(_enum(Envio, "envio_amazon"))


class PrecoAtualAmazon(Base):
    """Última leitura de cada anúncio. Vendedor e envio só mudam numa leitura de origem `produto`."""

    __tablename__ = "preco_atual_amazon"

    anuncio_id: Mapped[int] = mapped_column(ForeignKey("anuncio_amazon.id"), primary_key=True)
    preco: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    origem: Mapped[OrigemPreco] = mapped_column(_enum(OrigemPreco, "origem_preco"))
    vendedor_id: Mapped[int | None] = mapped_column(ForeignKey("vendedor_amazon.id"))
    envio: Mapped[Envio] = mapped_column(_enum(Envio, "envio_amazon"))
    coletado_em: Mapped[datetime] = mapped_column(DATA)


class FilaAmazon(Base):
    """Uma linha por produto ativo da Liga: quando buscar de novo na Amazon."""

    __tablename__ = "fila_amazon"

    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"), primary_key=True)
    entrou_em: Mapped[datetime] = mapped_column(DATA)
    proxima_busca_em: Mapped[datetime] = mapped_column(DATA)
    ultima_busca_em: Mapped[datetime | None] = mapped_column(DATA)
    ultimo_candidato_em: Mapped[datetime | None] = mapped_column(DATA)


class Oportunidade(Base):
    """Oferta elegível da Amazon. Aberta enquanto `fechada_em` é NULL; no máximo uma aberta por anúncio."""

    __tablename__ = "oportunidade"
    __table_args__ = (
        Index("uq_oportunidade_aberta", "anuncio_id", unique=True, postgresql_where=text("fechada_em IS NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    anuncio_id: Mapped[int] = mapped_column(ForeignKey("anuncio_amazon.id"))
    produto_id: Mapped[int] = mapped_column(ForeignKey("produto_liga.id"))
    preco_amazon: Mapped[Decimal] = mapped_column(DINHEIRO)
    preco_liga: Mapped[Decimal] = mapped_column(DINHEIRO)
    desconto_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    vendedor_id: Mapped[int | None] = mapped_column(ForeignKey("vendedor_amazon.id"))
    envio: Mapped[Envio] = mapped_column(_enum(Envio, "envio_amazon"))
    aberta_em: Mapped[datetime] = mapped_column(DATA)
    alertada_em: Mapped[datetime] = mapped_column(DATA)
    preco_alertado: Mapped[Decimal] = mapped_column(DINHEIRO)
    fechada_em: Mapped[datetime | None] = mapped_column(DATA)


# Limites (inclusivos) dos campos inteiros de config_amazon: os CHECKs do banco, a migração e a
# validação do formulário do admin (coletor_amazon/config.py) usam os mesmos valores.
LIMITES_CONFIG_AMAZON: dict[str, tuple[int, int]] = {
    "pausa_min_s": (0, 120),
    "pausa_max_s": (0, 120),
    "resultados_por_busca": (1, 48),
    "intervalo_busca_min": (10, 1440),
    "max_buscas_hora": (1, 400),
    "limite_falha_pct": (0, 100),
    "desconto_min_pct": (1, 90),
    "realerta_queda_pct": (1, 50),
    "liga_preco_max_idade_h": (1, 168),
    "vendedor_min_positivas_pct": (0, 100),
    "vendedor_min_avaliacoes": (0, 100_000),
    "vendedor_reavaliar_dias": (1, 90),
}

PADROES_CONFIG_AMAZON: dict[str, object] = {
    "url_busca": "https://www.amazon.com.br/s?k={termo}",
    "janela_inicio": time(8, 0),
    "janela_fim": time(22, 0),
    "pausa_min_s": 8,
    "pausa_max_s": 20,
    "resultados_por_busca": 10,
    "intervalo_busca_min": 60,
    "max_buscas_hora": 200,
    "limite_falha_pct": 50,
    "desconto_min_pct": 25,
    "realerta_queda_pct": 5,
    "liga_preco_max_idade_h": 48,
    "vendedor_min_positivas_pct": 90,
    "vendedor_min_avaliacoes": 100,
    "vendedor_reavaliar_dias": 7,
}


class ConfigAmazon(Base):
    """Configuração da Amazon e do motor de oportunidades: uma linha, editável no admin."""

    __tablename__ = "config_amazon"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_config_amazon_linha_unica"),
        CheckConstraint("position('{termo}' in url_busca) > 0", name="ck_config_amazon_url"),
        CheckConstraint("janela_inicio < janela_fim", name="ck_config_amazon_janela"),
        CheckConstraint("pausa_min_s <= pausa_max_s", name="ck_config_amazon_pausas"),
        *(
            CheckConstraint(f"{campo} BETWEEN {minimo} AND {maximo}", name=f"ck_config_amazon_{campo}")
            for campo, (minimo, maximo) in LIMITES_CONFIG_AMAZON.items()
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    url_busca: Mapped[str] = mapped_column(Text)
    janela_inicio: Mapped[time] = mapped_column(Time)
    janela_fim: Mapped[time] = mapped_column(Time)
    pausa_min_s: Mapped[int] = mapped_column(Integer)
    pausa_max_s: Mapped[int] = mapped_column(Integer)
    resultados_por_busca: Mapped[int] = mapped_column(Integer)
    intervalo_busca_min: Mapped[int] = mapped_column(Integer)
    max_buscas_hora: Mapped[int] = mapped_column(Integer)
    limite_falha_pct: Mapped[int] = mapped_column(Integer)
    desconto_min_pct: Mapped[int] = mapped_column(Integer)
    realerta_queda_pct: Mapped[int] = mapped_column(Integer)
    liga_preco_max_idade_h: Mapped[int] = mapped_column(Integer)
    vendedor_min_positivas_pct: Mapped[int] = mapped_column(Integer)
    vendedor_min_avaliacoes: Mapped[int] = mapped_column(Integer)
    vendedor_reavaliar_dias: Mapped[int] = mapped_column(Integer)
    atualizado_em: Mapped[datetime] = mapped_column(DATA)
```

- [ ] **Step 4: Migração**

Os CHECKs dos enums (`native_enum=False`) têm o nome do enum (`tipo_coleta`, `estado_coletor_tipo`; confirmado no banco em 2026-10-14). Crie `src/tcg_sniper/db/migrations/versions/7d3f1a2b9c4e_amazon.py` (valores literais de propósito: uma migração não importa os modelos, que mudam depois):

```python
"""amazon: anúncios, preços, vendedores, fila, oportunidades, config e estado por coletor

Revision ID: 7d3f1a2b9c4e
Revises: 5c815103a38f
Create Date: 2026-10-14 18:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7d3f1a2b9c4e"
down_revision: Union[str, Sequence[str], None] = "5c815103a38f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DATA = sa.DateTime(timezone=True)
DINHEIRO = sa.Numeric(10, 2)


def _enum(nome: str, *valores: str) -> sa.Enum:
    return sa.Enum(*valores, name=nome, native_enum=False, create_constraint=True, length=20)


ENVIO = ("amazon", "fba", "proprio", "desconhecido")
ORIGEM = ("busca", "produto")
LIMITES = {
    "pausa_min_s": (0, 120),
    "pausa_max_s": (0, 120),
    "resultados_por_busca": (1, 48),
    "intervalo_busca_min": (10, 1440),
    "max_buscas_hora": (1, 400),
    "limite_falha_pct": (0, 100),
    "desconto_min_pct": (1, 90),
    "realerta_queda_pct": (1, 50),
    "liga_preco_max_idade_h": (1, 168),
    "vendedor_min_positivas_pct": (0, 100),
    "vendedor_min_avaliacoes": (0, 100000),
    "vendedor_reavaliar_dias": (1, 90),
}


def upgrade() -> None:
    op.drop_constraint("tipo_coleta", "coleta", type_="check")
    op.create_check_constraint("tipo_coleta", "coleta", "tipo IN ('listagem', 'produtos', 'amazon')")
    op.drop_constraint("estado_coletor_tipo", "estado_coletor", type_="check")
    op.create_check_constraint(
        "estado_coletor_tipo", "estado_coletor", "estado IN ('ativo', 'pausado_desafio', 'pausado')"
    )

    op.drop_constraint("ck_estado_coletor_linha_unica", "estado_coletor", type_="check")
    op.create_check_constraint("ck_estado_coletor_linhas", "estado_coletor", "id IN (1, 2)")
    op.add_column("estado_coletor", sa.Column("coletor", sa.Text(), nullable=True))
    op.execute("UPDATE estado_coletor SET coletor = 'liga' WHERE id = 1")
    op.execute(
        "INSERT INTO estado_coletor (id, coletor, estado, execucao_solicitada, atualizado_em) "
        "VALUES (2, 'amazon', 'ativo', false, now())"
    )
    op.alter_column("estado_coletor", "coletor", nullable=False)
    op.create_unique_constraint("uq_estado_coletor_coletor", "estado_coletor", ["coletor"])

    op.create_table(
        "anuncio_amazon",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("asin", sa.Text(), nullable=False),
        sa.Column("titulo", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("produto_id", sa.Integer(), nullable=True),
        sa.Column("status_casamento", _enum("status_casamento", "pendente", "confirmado", "ignorado"), nullable=False),
        sa.Column("revisado_em", DATA, nullable=True),
        sa.Column("visto_primeiro_em", DATA, nullable=False),
        sa.Column("visto_ultimo_em", DATA, nullable=False),
        sa.ForeignKeyConstraint(["produto_id"], ["produto_liga.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asin"),
    )
    op.create_table(
        "vendedor_amazon",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("seller_id", sa.Text(), nullable=False),
        sa.Column("nome", sa.Text(), nullable=True),
        sa.Column("pct_positivas", sa.Numeric(5, 2), nullable=True),
        sa.Column("num_avaliacoes", sa.Integer(), nullable=True),
        sa.Column("avaliado_em", DATA, nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seller_id"),
    )
    op.create_table(
        "preco_amazon",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("anuncio_id", sa.Integer(), nullable=False),
        sa.Column("coletado_em", DATA, nullable=False),
        sa.Column("preco", DINHEIRO, nullable=True),
        sa.Column("origem", _enum("origem_preco", *ORIGEM), nullable=False),
        sa.Column("vendedor_id", sa.Integer(), nullable=True),
        sa.Column("envio", _enum("envio_amazon", *ENVIO), nullable=False),
        sa.ForeignKeyConstraint(["anuncio_id"], ["anuncio_amazon.id"]),
        sa.ForeignKeyConstraint(["vendedor_id"], ["vendedor_amazon.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "preco_atual_amazon",
        sa.Column("anuncio_id", sa.Integer(), nullable=False),
        sa.Column("preco", DINHEIRO, nullable=True),
        sa.Column("origem", _enum("origem_preco", *ORIGEM), nullable=False),
        sa.Column("vendedor_id", sa.Integer(), nullable=True),
        sa.Column("envio", _enum("envio_amazon", *ENVIO), nullable=False),
        sa.Column("coletado_em", DATA, nullable=False),
        sa.ForeignKeyConstraint(["anuncio_id"], ["anuncio_amazon.id"]),
        sa.ForeignKeyConstraint(["vendedor_id"], ["vendedor_amazon.id"]),
        sa.PrimaryKeyConstraint("anuncio_id"),
    )
    op.create_table(
        "fila_amazon",
        sa.Column("produto_id", sa.Integer(), nullable=False),
        sa.Column("entrou_em", DATA, nullable=False),
        sa.Column("proxima_busca_em", DATA, nullable=False),
        sa.Column("ultima_busca_em", DATA, nullable=True),
        sa.Column("ultimo_candidato_em", DATA, nullable=True),
        sa.ForeignKeyConstraint(["produto_id"], ["produto_liga.id"]),
        sa.PrimaryKeyConstraint("produto_id"),
    )
    op.create_table(
        "oportunidade",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("anuncio_id", sa.Integer(), nullable=False),
        sa.Column("produto_id", sa.Integer(), nullable=False),
        sa.Column("preco_amazon", DINHEIRO, nullable=False),
        sa.Column("preco_liga", DINHEIRO, nullable=False),
        sa.Column("desconto_pct", sa.Numeric(5, 2), nullable=False),
        sa.Column("vendedor_id", sa.Integer(), nullable=True),
        sa.Column("envio", _enum("envio_amazon", *ENVIO), nullable=False),
        sa.Column("aberta_em", DATA, nullable=False),
        sa.Column("alertada_em", DATA, nullable=False),
        sa.Column("preco_alertado", DINHEIRO, nullable=False),
        sa.Column("fechada_em", DATA, nullable=True),
        sa.ForeignKeyConstraint(["anuncio_id"], ["anuncio_amazon.id"]),
        sa.ForeignKeyConstraint(["produto_id"], ["produto_liga.id"]),
        sa.ForeignKeyConstraint(["vendedor_id"], ["vendedor_amazon.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_oportunidade_aberta", "oportunidade", ["anuncio_id"], unique=True,
        postgresql_where=sa.text("fechada_em IS NULL"),
    )
    op.create_table(
        "config_amazon",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("url_busca", sa.Text(), nullable=False),
        sa.Column("janela_inicio", sa.Time(), nullable=False),
        sa.Column("janela_fim", sa.Time(), nullable=False),
        *(sa.Column(campo, sa.Integer(), nullable=False) for campo in LIMITES),
        sa.Column("atualizado_em", DATA, nullable=False),
        sa.CheckConstraint("id = 1", name="ck_config_amazon_linha_unica"),
        sa.CheckConstraint("position('{termo}' in url_busca) > 0", name="ck_config_amazon_url"),
        sa.CheckConstraint("janela_inicio < janela_fim", name="ck_config_amazon_janela"),
        sa.CheckConstraint("pausa_min_s <= pausa_max_s", name="ck_config_amazon_pausas"),
        *(
            sa.CheckConstraint(f"{campo} BETWEEN {minimo} AND {maximo}", name=f"ck_config_amazon_{campo}")
            for campo, (minimo, maximo) in LIMITES.items()
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO config_amazon (id, url_busca, janela_inicio, janela_fim, pausa_min_s, pausa_max_s, "
        "resultados_por_busca, intervalo_busca_min, max_buscas_hora, limite_falha_pct, desconto_min_pct, "
        "realerta_queda_pct, liga_preco_max_idade_h, vendedor_min_positivas_pct, vendedor_min_avaliacoes, "
        "vendedor_reavaliar_dias, atualizado_em) VALUES (1, 'https://www.amazon.com.br/s?k={termo}', "
        "'08:00', '22:00', 8, 20, 10, 60, 200, 50, 25, 5, 48, 90, 100, 7, now())"
    )
    op.execute("INSERT INTO vendedor_amazon (seller_id, nome) VALUES ('amazon', 'Amazon.com.br')")


def downgrade() -> None:
    op.drop_table("config_amazon")
    op.drop_index("uq_oportunidade_aberta", table_name="oportunidade")
    op.drop_table("oportunidade")
    op.drop_table("fila_amazon")
    op.drop_table("preco_atual_amazon")
    op.drop_table("preco_amazon")
    op.drop_table("vendedor_amazon")
    op.drop_table("anuncio_amazon")
    op.drop_constraint("uq_estado_coletor_coletor", "estado_coletor", type_="unique")
    op.execute("DELETE FROM estado_coletor WHERE id <> 1")
    op.drop_column("estado_coletor", "coletor")
    op.drop_constraint("ck_estado_coletor_linhas", "estado_coletor", type_="check")
    op.create_check_constraint("ck_estado_coletor_linha_unica", "estado_coletor", "id = 1")
    op.execute("UPDATE estado_coletor SET estado = 'ativo' WHERE estado = 'pausado'")
    op.drop_constraint("estado_coletor_tipo", "estado_coletor", type_="check")
    op.create_check_constraint("estado_coletor_tipo", "estado_coletor", "estado IN ('ativo', 'pausado_desafio')")
    op.execute("DELETE FROM coleta WHERE tipo = 'amazon'")
    op.drop_constraint("tipo_coleta", "coleta", type_="check")
    op.create_check_constraint("tipo_coleta", "coleta", "tipo IN ('listagem', 'produtos')")
```

- [ ] **Step 5: Repositório, agendador da Liga e admin**

Em `src/tcg_sniper/db/repositorio.py`: acrescente `COLETOR_AMAZON`, `COLETOR_LIGA` aos imports de `tcg_sniper.db.models` e troque `obter_estado`, `pausar_por_desafio`, `retomar` e `marcar_interrompidas` por (o resto do arquivo fica igual):

```python
ID_COLETOR = {COLETOR_LIGA: 1, COLETOR_AMAZON: 2}


def obter_estado(s: Session, agora: datetime | None = None, coletor: str = COLETOR_LIGA) -> EstadoColetor:
    id_estado = ID_COLETOR[coletor]
    s.execute(
        pg_insert(EstadoColetor)
        .values(
            id=id_estado,
            coletor=coletor,
            estado=EstadoColetorTipo.ATIVO,
            execucao_solicitada=False,
            atualizado_em=agora or agora_utc(),
        )
        .on_conflict_do_nothing(index_elements=[EstadoColetor.id])
    )
    return s.get(EstadoColetor, id_estado, populate_existing=True)


def pausar_por_desafio(s: Session, motivo: str, agora: datetime, coletor: str = COLETOR_LIGA) -> None:
    _mudar_estado(s, EstadoColetorTipo.PAUSADO_DESAFIO, motivo, agora, coletor)


def pausar(s: Session, motivo: str, agora: datetime, coletor: str) -> None:
    """Pausa manual (admin) ou por erros seguidos; só volta com retomar."""
    _mudar_estado(s, EstadoColetorTipo.PAUSADO, motivo, agora, coletor)


def _mudar_estado(s: Session, novo: EstadoColetorTipo, motivo: str, agora: datetime, coletor: str) -> None:
    estado = obter_estado(s, agora, coletor)
    estado.estado = novo
    estado.motivo = motivo
    estado.execucao_solicitada = False
    estado.atualizado_em = agora
    s.flush()


def retomar(s: Session, agora: datetime, coletor: str = COLETOR_LIGA) -> None:
    estado = obter_estado(s, agora, coletor)
    estado.estado = EstadoColetorTipo.ATIVO
    estado.motivo = None
    estado.execucao_solicitada = True
    estado.atualizado_em = agora
    s.flush()


def marcar_interrompidas(s: Session, agora: datetime, tipos: Sequence[TipoColeta]) -> int:
    """Fecha como falha as coletas `rodando` dos tipos do coletor que está subindo."""
    resultado = s.execute(
        update(Coleta)
        .where(Coleta.status == StatusColeta.RODANDO, Coleta.tipo.in_(tipos))
        .values(status=StatusColeta.FALHA, erro="interrompida", finalizada_em=agora)
    )
    return resultado.rowcount
```

Em `src/tcg_sniper/coletor_liga/agendador.py`:

```python
TIPOS_LIGA = (TipoColeta.LISTAGEM, TipoColeta.PRODUTOS)
```

logo abaixo de `INTERVALO_TICK_S`; troque `def lock_coleta(engine: Engine) -> Iterator[bool]:` por `def lock_coleta(engine: Engine, id_lock: int = ID_LOCK) -> Iterator[bool]:` e, dentro, os dois `{"id": ID_LOCK}` por `{"id": id_lock}`; em `inicializar`, troque `repo.marcar_interrompidas(s, agora)` por `repo.marcar_interrompidas(s, agora, TIPOS_LIGA)`.

Em `src/tcg_sniper/admin/consultas.py`, troque `coleta_em_andamento` por:

```python
def coleta_em_andamento(s: Session, tipos: Sequence[TipoColeta]) -> bool:
    consulta = select(Coleta.id).where(Coleta.status == StatusColeta.RODANDO, Coleta.tipo.in_(tipos)).limit(1)
    return s.scalar(consulta) is not None
```

(imports: `from collections.abc import Sequence` e `TipoColeta` de `tcg_sniper.db.models`). Em `src/tcg_sniper/admin/app.py`, troque `consultas.coleta_em_andamento(s)` por `consultas.coleta_em_andamento(s, TIPOS_LIGA)`, com `from tcg_sniper.coletor_liga.agendador import TIPOS_LIGA`.

- [ ] **Step 6: Rodar a suíte inteira e recriar o banco de testes**

Run: `uv run pytest -q && uv run ruff check`
Expected: tudo passa. O fixture `engine` recria o schema `tcg_test` do zero, então `test_migracao_igual_aos_modelos` confere a migração nova contra os modelos. Se ele acusar diferença, ajuste a migração (não os modelos) até zerar.

Aplique também no banco de desenvolvimento, que tem dados do sub-projeto 1, para conferir que a migração sobe em cima deles: `docker compose run --rm migrate` e depois `docker compose exec -T postgres psql -U tcg -d tcg -c "select id, coletor, estado from estado_coletor;"`.
Expected: `1 | liga | ativo` e `2 | amazon | ativo`.

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/db src/tcg_sniper/coletor_liga/agendador.py src/tcg_sniper/admin/consultas.py src/tcg_sniper/admin/app.py tests/db tests/admin/test_admin.py
git commit -m "feat: Amazon tables, per-collector state and interrupted marking by type"
```

---

### Task 3: Repositório da Amazon

Funções de banco da fila, dos anúncios, dos preços, dos vendedores, das oportunidades e do casamento. Tudo recebe a sessão; quem chama abre a transação.

**Files:**
- Create: `src/tcg_sniper/db/repositorio_amazon.py`
- Create: `src/tcg_sniper/coletor_amazon/__init__.py` (vazio), `src/tcg_sniper/coletor_amazon/modelos.py`
- Modify: `tests/fakes.py` (`criar_anuncio`, `criar_preco_liga`)
- Test: `tests/db/test_repositorio_amazon.py`

**Interfaces:**
- Consumes: modelos da Task 2.
- Produces (em `tcg_sniper.coletor_amazon.modelos`):
  - `ResultadoBusca(asin: str, titulo: str, url: str, preco: Decimal | None, patrocinado: bool)`
  - `OfertaProduto(asin: str, titulo: str, preco: Decimal | None, vendido_por: str | None, seller_id: str | None, envio: Envio)`
  - `AvaliacaoVendedor(seller_id: str, nome: str | None, pct_positivas: Decimal | None, num_avaliacoes: int | None)`
- Produces (em `tcg_sniper.coletor_amazon.modelos`): `SELLER_AMAZON = "amazon"`
- Produces (em `tcg_sniper.db.repositorio_amazon`):
  - `obter_config(s) -> ConfigAmazon`
  - `sincronizar_fila(s, agora) -> None`; `ids_na_fila(s) -> set[int]`; `proximo_da_fila(s, agora) -> FilaAmazon | None`; `reagendar(s, produto_id, agora, proxima, teve_candidato) -> None`
  - `gravar_busca(s, itens: Sequence[ResultadoBusca], produto_id: int, agora, zona: ZoneInfo) -> list[AnuncioAmazon]` (um por ASIN, na ordem da busca)
  - `registrar_preco(s, anuncio_id, preco, origem, vendedor_id, envio, agora, zona) -> bool` (True se gravou histórico)
  - `confirmados_com_referencia(s, anuncio_ids) -> list[LinhaConfirmada]`, com `LinhaConfirmada(anuncio: AnuncioAmazon, produto: ProdutoLiga, atual: PrecoAtualAmazon, liga: PrecoAtualLiga | None)`
  - `vendedor_da_amazon(s) -> VendedorAmazon`; `obter_vendedor(s, seller_id) -> VendedorAmazon | None`; `gravar_vendedor(s, avaliacao: AvaliacaoVendedor, agora) -> VendedorAmazon`
  - `oportunidade_aberta(s, anuncio_id) -> Oportunidade | None`; `abrir_oportunidade(s, *, anuncio_id, produto_id, preco_amazon, preco_liga, desconto_pct, vendedor_id, envio, agora) -> Oportunidade`; `atualizar_oportunidade(s, op, *, preco_amazon, preco_liga, desconto_pct, vendedor_id, envio, alertou: bool, agora) -> None`; `fechar_oportunidade(s, op, agora) -> None`; `fechar_oportunidades_do_anuncio(s, anuncio_id, agora) -> int`; `fechar_oportunidades_sem_leitura(s, agora, horas: int = 24) -> int`
  - `confirmar_casamento(s, anuncio_id, produto_id, agora) -> bool`; `ignorar_anuncio(s, anuncio_id, agora) -> bool`; `desfazer_casamento(s, anuncio_id, agora) -> bool` (False = anúncio inexistente)
- Produces (em `tests/fakes.py`): `criar_anuncio(s, asin="B000000001", produto=None, status=StatusCasamento.PENDENTE, agora=T0) -> AnuncioAmazon`; `criar_preco_liga(s, produto, preco: str | None, listagem_em=T0, num_lojas=None, preco_medio=None) -> PrecoAtualLiga`

- [ ] **Step 1: Modelos de domínio da Amazon**

`src/tcg_sniper/coletor_amazon/__init__.py`: vazio.

`src/tcg_sniper/coletor_amazon/modelos.py`:

```python
from dataclasses import dataclass
from decimal import Decimal

from tcg_sniper.db.models import Envio

SELLER_AMAZON = "amazon"  # seller_id da própria Amazon (linha fixa em vendedor_amazon)


@dataclass(frozen=True)
class ResultadoBusca:
    """Cartão do resultado de busca. `preco` None quando o cartão não mostra preço (nunca zero)."""

    asin: str
    titulo: str
    url: str
    preco: Decimal | None
    patrocinado: bool


@dataclass(frozen=True)
class OfertaProduto:
    """Oferta principal da página do produto. `seller_id` é "amazon" quando vendido pela Amazon."""

    asin: str
    titulo: str
    preco: Decimal | None
    vendido_por: str | None
    seller_id: str | None
    envio: Envio


@dataclass(frozen=True)
class AvaliacaoVendedor:
    seller_id: str
    nome: str | None
    pct_positivas: Decimal | None
    num_avaliacoes: int | None
```

- [ ] **Step 2: Fakes de teste**

Acrescente a `tests/fakes.py` (imports: `from decimal import Decimal`; `AnuncioAmazon`, `PrecoAtualLiga`, `StatusCasamento` de `tcg_sniper.db.models`):

```python
def criar_anuncio(s, asin="B000000001", produto=None, status=StatusCasamento.PENDENTE, agora=T0) -> AnuncioAmazon:
    anuncio = AnuncioAmazon(
        asin=asin,
        titulo=f"Anúncio {asin}",
        url=f"https://www.amazon.com.br/dp/{asin}",
        produto_id=produto.id if produto is not None else None,
        status_casamento=status,
        visto_primeiro_em=agora,
        visto_ultimo_em=agora,
    )
    s.add(anuncio)
    s.flush()
    return anuncio


def criar_preco_liga(s, produto, preco, listagem_em=T0, num_lojas=None, preco_medio=None) -> PrecoAtualLiga:
    atual = PrecoAtualLiga(
        produto_id=produto.id,
        preco_a_partir=None if preco is None else Decimal(preco),
        listagem_em=listagem_em,
        num_lojas=num_lojas,
        preco_medio=None if preco_medio is None else Decimal(preco_medio),
    )
    s.add(atual)
    s.flush()
    return atual
```

- [ ] **Step 3: Escrever os testes do repositório**

`tests/db/test_repositorio_amazon.py`:

```python
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto
from sqlalchemy import func, select

from tcg_sniper.coletor_amazon.modelos import AvaliacaoVendedor, ResultadoBusca
from tcg_sniper.db import repositorio_amazon as repo
from tcg_sniper.db.models import (
    AnuncioAmazon,
    Envio,
    FilaAmazon,
    Oportunidade,
    OrigemPreco,
    PrecoAmazon,
    PrecoAtualAmazon,
    StatusCasamento,
)

SP = ZoneInfo("America/Sao_Paulo")


def resultado(asin, preco="100.00", titulo=None):
    return ResultadoBusca(
        asin=asin,
        titulo=titulo or f"Título {asin}",
        url=f"https://www.amazon.com.br/dp/{asin}",
        preco=None if preco is None else Decimal(preco),
        patrocinado=False,
    )


def test_obter_config_devolve_a_linha_da_migracao(s):
    assert repo.obter_config(s).desconto_min_pct == 25


def test_sincronizar_fila_acompanha_os_ativos(s):
    a = criar_produto(s, "a", ativo=True)
    b = criar_produto(s, "b", ativo=True)
    criar_produto(s, "c", ativo=False)
    repo.sincronizar_fila(s, T0)
    assert repo.ids_na_fila(s) == {a.id, b.id}
    assert s.get(FilaAmazon, a.id).proxima_busca_em == T0

    b.ativo = False
    s.flush()
    repo.sincronizar_fila(s, T0 + timedelta(hours=1))
    assert repo.ids_na_fila(s) == {a.id}
    assert s.get(FilaAmazon, a.id).entrou_em == T0  # quem já estava não é reinserido


def test_proximo_da_fila_mais_antigo_vencido_e_empate_pelo_preco_da_liga(s):
    barato = criar_produto(s, "barato")
    caro = criar_produto(s, "caro")
    futuro = criar_produto(s, "futuro")
    criar_preco_liga(s, barato, "100.00")
    criar_preco_liga(s, caro, "900.00")
    repo.sincronizar_fila(s, T0)
    s.get(FilaAmazon, futuro.id).proxima_busca_em = T0 + timedelta(hours=2)
    s.flush()

    assert repo.proximo_da_fila(s, T0).produto_id == caro.id
    repo.reagendar(s, caro.id, T0, T0 + timedelta(hours=1), teve_candidato=False)
    assert repo.proximo_da_fila(s, T0).produto_id == barato.id
    repo.reagendar(s, barato.id, T0, T0 + timedelta(hours=1), teve_candidato=True)
    assert repo.proximo_da_fila(s, T0) is None
    fila = s.get(FilaAmazon, barato.id)
    assert (fila.ultima_busca_em, fila.ultimo_candidato_em) == (T0, T0)
    assert s.get(FilaAmazon, caro.id).ultimo_candidato_em is None


def test_gravar_busca_cria_pendente_com_sugestao_e_nao_troca_a_sugestao(s):
    a = criar_produto(s, "a")
    b = criar_produto(s, "b")
    anuncios = repo.gravar_busca(s, [resultado("B01"), resultado("B01", "90.00"), resultado("B02")], a.id, T0, SP)
    assert [x.asin for x in anuncios] == ["B01", "B02"]
    assert anuncios[0].status_casamento is StatusCasamento.PENDENTE
    assert anuncios[0].produto_id == a.id
    assert s.get(PrecoAtualAmazon, anuncios[0].id).preco == Decimal("100.00")  # vale o primeiro cartão

    depois = T0 + timedelta(hours=1)
    repo.gravar_busca(s, [resultado("B01", titulo="Novo título")], b.id, depois, SP)
    anuncio = s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.asin == "B01"))
    assert (anuncio.produto_id, anuncio.titulo, anuncio.visto_ultimo_em) == (a.id, "Novo título", depois)


def test_registrar_preco_so_grava_historico_quando_muda_ou_no_primeiro_do_dia(s):
    anuncio = criar_anuncio(s)

    def gravar(preco, quando):
        valor = None if preco is None else Decimal(preco)
        return repo.registrar_preco(s, anuncio.id, valor, OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, quando, SP)

    assert gravar("100.00", T0) is True
    assert gravar("100.00", T0 + timedelta(hours=1)) is False
    assert gravar("95.00", T0 + timedelta(hours=2)) is True
    assert gravar(None, T0 + timedelta(hours=3)) is True
    assert gravar(None, T0 + timedelta(days=1)) is True  # primeira leitura do dia seguinte
    total = s.scalar(select(func.count()).select_from(PrecoAmazon).where(PrecoAmazon.anuncio_id == anuncio.id))
    assert total == 4
    assert s.get(PrecoAtualAmazon, anuncio.id).preco is None


def test_leitura_da_busca_nao_apaga_vendedor_e_envio_da_pagina_do_produto(s):
    anuncio = criar_anuncio(s)
    amazon = repo.vendedor_da_amazon(s)
    repo.registrar_preco(s, anuncio.id, Decimal("80.00"), OrigemPreco.PRODUTO, amazon.id, Envio.AMAZON, T0, SP)
    repo.registrar_preco(
        s, anuncio.id, Decimal("85.00"), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, T0 + timedelta(hours=1), SP
    )
    atual = s.get(PrecoAtualAmazon, anuncio.id)
    assert (atual.preco, atual.origem, atual.vendedor_id, atual.envio) == (
        Decimal("85.00"), OrigemPreco.BUSCA, amazon.id, Envio.AMAZON
    )


def test_confirmados_com_referencia_so_traz_confirmados_e_o_preco_do_produto_casado(s):
    a = criar_produto(s, "a")
    b = criar_produto(s, "b")
    criar_preco_liga(s, a, "1000.00")
    criar_preco_liga(s, b, "50.00")
    confirmado = criar_anuncio(s, "B01", produto=a, status=StatusCasamento.CONFIRMADO)
    pendente = criar_anuncio(s, "B02", produto=b)
    for anuncio in (confirmado, pendente):
        repo.registrar_preco(s, anuncio.id, Decimal("700.00"), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, T0, SP)

    linhas = repo.confirmados_com_referencia(s, [confirmado.id, pendente.id])
    assert [(linha.anuncio.asin, linha.produto.id, linha.liga.preco_a_partir) for linha in linhas] == [
        ("B01", a.id, Decimal("1000.00"))
    ]


def test_vendedores(s):
    assert repo.vendedor_da_amazon(s).seller_id == "amazon"
    assert repo.obter_vendedor(s, "A1") is None
    v = repo.gravar_vendedor(s, AvaliacaoVendedor("A1", "Loja", Decimal("97"), 2340), T0)
    assert (v.nome, v.pct_positivas, v.num_avaliacoes, v.avaliado_em) == ("Loja", Decimal("97"), 2340, T0)
    v2 = repo.gravar_vendedor(s, AvaliacaoVendedor("A1", "Loja", Decimal("96"), 2400), T0 + timedelta(days=8))
    assert v2.id == v.id and v2.num_avaliacoes == 2400


def test_oportunidade_abrir_atualizar_fechar(s):
    produto = criar_produto(s)
    anuncio = criar_anuncio(s, produto=produto, status=StatusCasamento.CONFIRMADO)
    amazon = repo.vendedor_da_amazon(s)
    op = repo.abrir_oportunidade(
        s, anuncio_id=anuncio.id, produto_id=produto.id, preco_amazon=Decimal("700.00"),
        preco_liga=Decimal("1000.00"), desconto_pct=Decimal("30.00"), vendedor_id=amazon.id,
        envio=Envio.AMAZON, agora=T0,
    )
    assert repo.oportunidade_aberta(s, anuncio.id).id == op.id
    assert (op.alertada_em, op.preco_alertado) == (T0, Decimal("700.00"))

    depois = T0 + timedelta(hours=1)
    repo.atualizar_oportunidade(
        s, op, preco_amazon=Decimal("650.00"), preco_liga=Decimal("1000.00"), desconto_pct=Decimal("35.00"),
        vendedor_id=amazon.id, envio=Envio.AMAZON, alertou=True, agora=depois,
    )
    assert (op.preco_amazon, op.alertada_em, op.preco_alertado) == (Decimal("650.00"), depois, Decimal("650.00"))

    repo.fechar_oportunidade(s, op, depois)
    assert repo.oportunidade_aberta(s, anuncio.id) is None


def test_fechar_oportunidades_sem_leitura_ha_24h(s):
    produto = criar_produto(s)
    velho = criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO, agora=T0)
    novo = criar_anuncio(s, "B02", produto=produto, status=StatusCasamento.CONFIRMADO, agora=T0 + timedelta(hours=20))
    for anuncio in (velho, novo):
        repo.abrir_oportunidade(
            s, anuncio_id=anuncio.id, produto_id=produto.id, preco_amazon=Decimal("1"), preco_liga=Decimal("2"),
            desconto_pct=Decimal("50"), vendedor_id=None, envio=Envio.AMAZON, agora=T0,
        )
    assert repo.fechar_oportunidades_sem_leitura(s, T0 + timedelta(hours=25)) == 1
    assert repo.oportunidade_aberta(s, velho.id) is None
    assert repo.oportunidade_aberta(s, novo.id) is not None


def test_casamento_confirmar_trocar_ignorar_desfazer(s):
    a = criar_produto(s, "a")
    b = criar_produto(s, "b")
    anuncio = criar_anuncio(s, produto=a)
    assert repo.confirmar_casamento(s, anuncio.id, a.id, T0) is True
    assert (anuncio.status_casamento, anuncio.produto_id, anuncio.revisado_em) == (StatusCasamento.CONFIRMADO, a.id, T0)

    op = repo.abrir_oportunidade(
        s, anuncio_id=anuncio.id, produto_id=a.id, preco_amazon=Decimal("1"), preco_liga=Decimal("2"),
        desconto_pct=Decimal("50"), vendedor_id=None, envio=Envio.AMAZON, agora=T0,
    )
    assert repo.confirmar_casamento(s, anuncio.id, b.id, T0) is True  # trocar fecha a oportunidade do produto antigo
    assert op.fechada_em == T0 and anuncio.produto_id == b.id

    assert repo.ignorar_anuncio(s, anuncio.id, T0) is True
    assert anuncio.status_casamento is StatusCasamento.IGNORADO
    assert repo.desfazer_casamento(s, anuncio.id, T0) is True
    assert (anuncio.status_casamento, anuncio.revisado_em) == (StatusCasamento.PENDENTE, None)
    assert repo.confirmar_casamento(s, 999_999, a.id, T0) is False
    assert s.scalar(select(func.count()).select_from(Oportunidade).where(Oportunidade.fechada_em.is_(None))) == 0
```

- [ ] **Step 4: Rodar e ver falhar**

Run: `uv run pytest tests/db/test_repositorio_amazon.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'tcg_sniper.db.repositorio_amazon'`).

- [ ] **Step 5: Implementar `repositorio_amazon.py`**

```python
"""Operações de banco do coletor da Amazon, do casamento e das oportunidades."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import delete, literal, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tcg_sniper.coletor_amazon.modelos import SELLER_AMAZON, AvaliacaoVendedor, ResultadoBusca
from tcg_sniper.db.models import (
    DATA,
    AnuncioAmazon,
    ConfigAmazon,
    Envio,
    FilaAmazon,
    Oportunidade,
    OrigemPreco,
    PrecoAmazon,
    PrecoAtualAmazon,
    PrecoAtualLiga,
    ProdutoLiga,
    StatusCasamento,
    VendedorAmazon,
)


@dataclass(frozen=True)
class LinhaConfirmada:
    anuncio: AnuncioAmazon
    produto: ProdutoLiga
    atual: PrecoAtualAmazon
    liga: PrecoAtualLiga | None


def obter_config(s: Session) -> ConfigAmazon:
    return s.get(ConfigAmazon, 1, populate_existing=True)


# --- fila -----------------------------------------------------------------------------------


def sincronizar_fila(s: Session, agora: datetime) -> None:
    """Produto ativado na Liga entra na fila (vencido); desativado sai."""
    ativos = select(ProdutoLiga.id).where(ProdutoLiga.ativo.is_(True))
    s.execute(delete(FilaAmazon).where(FilaAmazon.produto_id.not_in(ativos)))
    agora_sql = literal(agora, DATA)
    s.execute(
        pg_insert(FilaAmazon)
        .from_select(
            ["produto_id", "entrou_em", "proxima_busca_em"],
            select(ProdutoLiga.id, agora_sql, agora_sql).where(ProdutoLiga.ativo.is_(True)),
        )
        .on_conflict_do_nothing(index_elements=[FilaAmazon.produto_id])
    )
    s.flush()


def ids_na_fila(s: Session) -> set[int]:
    return set(s.scalars(select(FilaAmazon.produto_id)))


def proximo_da_fila(s: Session, agora: datetime) -> FilaAmazon | None:
    """O vencido há mais tempo; no empate, o de maior "À partir de" na Liga."""
    consulta = (
        select(FilaAmazon)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == FilaAmazon.produto_id)
        .where(FilaAmazon.proxima_busca_em <= agora)
        .order_by(
            FilaAmazon.proxima_busca_em,
            PrecoAtualLiga.preco_a_partir.desc().nulls_last(),
            FilaAmazon.produto_id,
        )
        .limit(1)
    )
    return s.scalar(consulta)


def reagendar(s: Session, produto_id: int, agora: datetime, proxima: datetime, teve_candidato: bool) -> None:
    valores: dict[str, datetime] = {"ultima_busca_em": agora, "proxima_busca_em": proxima}
    if teve_candidato:
        valores["ultimo_candidato_em"] = agora
    s.execute(update(FilaAmazon).where(FilaAmazon.produto_id == produto_id).values(**valores))
    s.flush()


# --- anúncios e preços ----------------------------------------------------------------------


def gravar_busca(
    s: Session, itens: Sequence[ResultadoBusca], produto_id: int, agora: datetime, zona: ZoneInfo
) -> list[AnuncioAmazon]:
    """Upsert dos anúncios da busca (ASIN novo entra pendente com o produto buscado como sugestão;
    a sugestão de um ASIN já conhecido nunca é trocada) e do preço de origem `busca`. ASIN repetido
    na mesma busca vale uma vez (o primeiro cartão). Devolve os anúncios na ordem da busca."""
    unicos: dict[str, ResultadoBusca] = {}
    for item in itens:
        unicos.setdefault(item.asin, item)
    for item in unicos.values():
        stmt = pg_insert(AnuncioAmazon).values(
            asin=item.asin,
            titulo=item.titulo,
            url=item.url,
            produto_id=produto_id,
            status_casamento=StatusCasamento.PENDENTE,
            visto_primeiro_em=agora,
            visto_ultimo_em=agora,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[AnuncioAmazon.asin],
            set_={"titulo": stmt.excluded.titulo, "url": stmt.excluded.url, "visto_ultimo_em": agora},
        ).returning(AnuncioAmazon.id)
        anuncio_id = s.execute(stmt).scalar_one()
        registrar_preco(s, anuncio_id, item.preco, OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, agora, zona)
    s.flush()
    por_asin = {
        a.asin: a
        for a in s.scalars(
            select(AnuncioAmazon).where(AnuncioAmazon.asin.in_(unicos)).execution_options(populate_existing=True)
        )
    }
    return [por_asin[asin] for asin in unicos]


def registrar_preco(
    s: Session,
    anuncio_id: int,
    preco: Decimal | None,
    origem: OrigemPreco,
    vendedor_id: int | None,
    envio: Envio,
    agora: datetime,
    zona: ZoneInfo,
) -> bool:
    """Atualiza o preço atual e acrescenta ao histórico se o preço (ou, na página do produto,
    vendedor/envio) mudou desde a última leitura do anúncio na mesma origem, ou se é a primeira
    leitura do dia. Devolve True se gravou no histórico."""
    ultimo = s.scalar(
        select(PrecoAmazon)
        .where(PrecoAmazon.anuncio_id == anuncio_id, PrecoAmazon.origem == origem)
        .order_by(PrecoAmazon.coletado_em.desc(), PrecoAmazon.id.desc())
        .limit(1)
    )
    inicio_do_dia = datetime.combine(agora.astimezone(zona).date(), time(0), tzinfo=zona)
    gravar = (
        ultimo is None
        or ultimo.coletado_em < inicio_do_dia
        or ultimo.preco != preco
        or (origem is OrigemPreco.PRODUTO and (ultimo.vendedor_id, ultimo.envio) != (vendedor_id, envio))
    )
    if gravar:
        s.add(
            PrecoAmazon(
                anuncio_id=anuncio_id, coletado_em=agora, preco=preco, origem=origem,
                vendedor_id=vendedor_id, envio=envio,
            )
        )
    atual: dict[str, object] = {"preco": preco, "origem": origem, "coletado_em": agora}
    if origem is OrigemPreco.PRODUTO:
        atual |= {"vendedor_id": vendedor_id, "envio": envio}
    s.execute(
        pg_insert(PrecoAtualAmazon)
        .values(anuncio_id=anuncio_id, preco=preco, origem=origem, vendedor_id=vendedor_id, envio=envio, coletado_em=agora)
        .on_conflict_do_update(index_elements=[PrecoAtualAmazon.anuncio_id], set_=atual)
    )
    s.flush()
    return gravar


def confirmados_com_referencia(s: Session, anuncio_ids: Sequence[int]) -> list[LinhaConfirmada]:
    """Dos anúncios dados, os confirmados, com o produto casado, o preço atual e o preço da Liga."""
    if not anuncio_ids:
        return []
    consulta = (
        select(AnuncioAmazon, ProdutoLiga, PrecoAtualAmazon, PrecoAtualLiga)
        .join(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(AnuncioAmazon.id.in_(anuncio_ids), AnuncioAmazon.status_casamento == StatusCasamento.CONFIRMADO)
        .order_by(AnuncioAmazon.id)
    )
    return [LinhaConfirmada(*linha) for linha in s.execute(consulta)]


# --- vendedores -----------------------------------------------------------------------------


def vendedor_da_amazon(s: Session) -> VendedorAmazon:
    return s.scalar(select(VendedorAmazon).where(VendedorAmazon.seller_id == SELLER_AMAZON))


def obter_vendedor(s: Session, seller_id: str) -> VendedorAmazon | None:
    return s.scalar(select(VendedorAmazon).where(VendedorAmazon.seller_id == seller_id))


def gravar_vendedor(s: Session, avaliacao: AvaliacaoVendedor, agora: datetime) -> VendedorAmazon:
    valores = {
        "nome": avaliacao.nome,
        "pct_positivas": avaliacao.pct_positivas,
        "num_avaliacoes": avaliacao.num_avaliacoes,
        "avaliado_em": agora,
    }
    stmt = pg_insert(VendedorAmazon).values(seller_id=avaliacao.seller_id, **valores)
    stmt = stmt.on_conflict_do_update(index_elements=[VendedorAmazon.seller_id], set_=valores)
    s.execute(stmt)
    s.flush()
    return s.scalar(
        select(VendedorAmazon)
        .where(VendedorAmazon.seller_id == avaliacao.seller_id)
        .execution_options(populate_existing=True)
    )


# --- oportunidades --------------------------------------------------------------------------


def oportunidade_aberta(s: Session, anuncio_id: int) -> Oportunidade | None:
    return s.scalar(
        select(Oportunidade).where(Oportunidade.anuncio_id == anuncio_id, Oportunidade.fechada_em.is_(None))
    )


def abrir_oportunidade(
    s: Session,
    *,
    anuncio_id: int,
    produto_id: int,
    preco_amazon: Decimal,
    preco_liga: Decimal,
    desconto_pct: Decimal,
    vendedor_id: int | None,
    envio: Envio,
    agora: datetime,
) -> Oportunidade:
    op = Oportunidade(
        anuncio_id=anuncio_id, produto_id=produto_id, preco_amazon=preco_amazon, preco_liga=preco_liga,
        desconto_pct=desconto_pct, vendedor_id=vendedor_id, envio=envio, aberta_em=agora,
        alertada_em=agora, preco_alertado=preco_amazon,
    )
    s.add(op)
    s.flush()
    return op


def atualizar_oportunidade(
    s: Session,
    op: Oportunidade,
    *,
    preco_amazon: Decimal,
    preco_liga: Decimal,
    desconto_pct: Decimal,
    vendedor_id: int | None,
    envio: Envio,
    alertou: bool,
    agora: datetime,
) -> None:
    op.preco_amazon, op.preco_liga, op.desconto_pct = preco_amazon, preco_liga, desconto_pct
    op.vendedor_id, op.envio = vendedor_id, envio
    if alertou:
        op.alertada_em, op.preco_alertado = agora, preco_amazon
    s.flush()


def fechar_oportunidade(s: Session, op: Oportunidade, agora: datetime) -> None:
    op.fechada_em = agora
    s.flush()


def fechar_oportunidades_do_anuncio(s: Session, anuncio_id: int, agora: datetime) -> int:
    resultado = s.execute(
        update(Oportunidade)
        .where(Oportunidade.anuncio_id == anuncio_id, Oportunidade.fechada_em.is_(None))
        .values(fechada_em=agora)
    )
    s.flush()
    return resultado.rowcount


def fechar_oportunidades_sem_leitura(s: Session, agora: datetime, horas: int = 24) -> int:
    """Fecha as abertas cujo anúncio não aparece em nenhuma busca há `horas` horas."""
    velhos = select(AnuncioAmazon.id).where(AnuncioAmazon.visto_ultimo_em < agora - timedelta(hours=horas))
    resultado = s.execute(
        update(Oportunidade)
        .where(Oportunidade.fechada_em.is_(None), Oportunidade.anuncio_id.in_(velhos))
        .values(fechada_em=agora)
        .execution_options(synchronize_session=False)
    )
    s.flush()
    return resultado.rowcount


# --- casamento ------------------------------------------------------------------------------


def confirmar_casamento(s: Session, anuncio_id: int, produto_id: int, agora: datetime) -> bool:
    """Confirma (ou troca) o produto da Liga do anúncio. Trocar fecha as oportunidades abertas."""
    anuncio = s.get(AnuncioAmazon, anuncio_id)
    if anuncio is None:
        return False
    if anuncio.produto_id != produto_id:
        fechar_oportunidades_do_anuncio(s, anuncio_id, agora)
    anuncio.produto_id = produto_id
    anuncio.status_casamento = StatusCasamento.CONFIRMADO
    anuncio.revisado_em = agora
    s.flush()
    return True


def ignorar_anuncio(s: Session, anuncio_id: int, agora: datetime) -> bool:
    anuncio = s.get(AnuncioAmazon, anuncio_id)
    if anuncio is None:
        return False
    fechar_oportunidades_do_anuncio(s, anuncio_id, agora)
    anuncio.status_casamento = StatusCasamento.IGNORADO
    anuncio.revisado_em = agora
    s.flush()
    return True


def desfazer_casamento(s: Session, anuncio_id: int, agora: datetime) -> bool:
    anuncio = s.get(AnuncioAmazon, anuncio_id)
    if anuncio is None:
        return False
    fechar_oportunidades_do_anuncio(s, anuncio_id, agora)
    anuncio.status_casamento = StatusCasamento.PENDENTE
    anuncio.revisado_em = None
    s.flush()
    return True
```

Se o ruff reclamar de linha longa (limite 120), quebre os argumentos uma por linha, no estilo do resto do arquivo.

- [ ] **Step 6: Rodar**

Run: `uv run pytest -q && uv run ruff check`
Expected: tudo passa. Se `test_casamento_confirmar_trocar_ignorar_desfazer` falhar em `op.fechada_em == T0` porque o `update` em massa não atualizou o objeto da sessão, faça `s.refresh(op)` no teste antes do assert (o comportamento do banco é o que importa).

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/coletor_amazon src/tcg_sniper/db/repositorio_amazon.py tests/fakes.py tests/db/test_repositorio_amazon.py
git commit -m "feat: Amazon repository for queue, listings, prices, sellers, opportunities and matching"
```

---

### Task 4: Validação da configuração da Amazon

Função pura que valida os campos do formulário do admin com os mesmos limites do banco, e as explicações de cada campo (o texto que estaria no `.env.example`).

**Files:**
- Create: `src/tcg_sniper/coletor_amazon/config.py`
- Test: `tests/coletor_amazon/test_config_amazon.py`

**Interfaces:**
- Consumes: `LIMITES_CONFIG_AMAZON`, `PADROES_CONFIG_AMAZON` (Task 2).
- Produces: `CAMPOS: tuple[str, ...]` (ordem do formulário), `EXPLICACOES: dict[str, str]`, `validar_config(campos: Mapping[str, str]) -> tuple[dict[str, object], dict[str, str]]` (valores convertidos, erros por campo; com erro, os valores não devem ser gravados), `aplicar_config(s, valores: Mapping[str, object], agora: datetime) -> None`

- [ ] **Step 1: Escrever os testes**

`tests/coletor_amazon/test_config_amazon.py`:

```python
from datetime import time

import pytest

from tcg_sniper.coletor_amazon.config import CAMPOS, EXPLICACOES, aplicar_config, validar_config
from tcg_sniper.db import repositorio_amazon as repo
from tcg_sniper.db.models import PADROES_CONFIG_AMAZON


def formulario(**mudancas):
    campos = {
        campo: valor.strftime("%H:%M") if isinstance(valor, time) else str(valor)
        for campo, valor in PADROES_CONFIG_AMAZON.items()
    }
    campos.update({k: str(v) for k, v in mudancas.items()})
    return campos


def test_padroes_sao_validos_e_convertidos():
    valores, erros = validar_config(formulario())
    assert erros == {}
    assert valores == PADROES_CONFIG_AMAZON


def test_todo_campo_tem_explicacao():
    assert set(CAMPOS) == set(PADROES_CONFIG_AMAZON) == set(EXPLICACOES)


@pytest.mark.parametrize(
    ("campo", "valor", "trecho"),
    [
        ("desconto_min_pct", "0", "entre 1 e 90"),
        ("desconto_min_pct", "abc", "número inteiro"),
        ("resultados_por_busca", "49", "entre 1 e 48"),
        ("url_busca", "https://www.amazon.com.br/s?k=x", "{termo}"),
        ("url_busca", "http://www.amazon.com.br/s?k={termo}", "https://"),
        ("janela_inicio", "25:00", "HH:MM"),
    ],
)
def test_campo_invalido(campo, valor, trecho):
    _, erros = validar_config(formulario(**{campo: valor}))
    assert trecho in erros[campo]


def test_pausa_minima_maior_que_a_maxima():
    _, erros = validar_config(formulario(pausa_min_s=30, pausa_max_s=20))
    assert "pausa_min_s" in erros


def test_janela_invertida():
    _, erros = validar_config(formulario(janela_inicio="22:00", janela_fim="08:00"))
    assert "janela_fim" in erros


def test_campo_ausente():
    campos = formulario()
    del campos["max_buscas_hora"]
    _, erros = validar_config(campos)
    assert "max_buscas_hora" in erros


def test_aplicar_config_grava(s):
    from fakes import T0

    valores, erros = validar_config(formulario(desconto_min_pct=30))
    assert erros == {}
    aplicar_config(s, valores, T0)
    config = repo.obter_config(s)
    assert (config.desconto_min_pct, config.atualizado_em) == (30, T0)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/coletor_amazon/test_config_amazon.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementar**

`src/tcg_sniper/coletor_amazon/config.py`:

```python
"""Validação do formulário de configuração da Amazon (admin), com os limites do banco."""

from collections.abc import Mapping
from datetime import datetime, time

from sqlalchemy import update
from sqlalchemy.orm import Session

from tcg_sniper.db.models import LIMITES_CONFIG_AMAZON, ConfigAmazon

CAMPOS = (
    "url_busca",
    "janela_inicio",
    "janela_fim",
    "pausa_min_s",
    "pausa_max_s",
    "resultados_por_busca",
    "intervalo_busca_min",
    "max_buscas_hora",
    "limite_falha_pct",
    "desconto_min_pct",
    "realerta_queda_pct",
    "liga_preco_max_idade_h",
    "vendedor_min_positivas_pct",
    "vendedor_min_avaliacoes",
    "vendedor_reavaliar_dias",
)

EXPLICACOES = {
    "url_busca": "Modelo da busca na Amazon; {termo} é trocado pelo nome do produto da Liga.",
    "janela_inicio": "Hora (HH:MM) em que a fila de buscas começa, com variação de até 15 minutos.",
    "janela_fim": "Hora (HH:MM) em que a fila para, com variação de até 15 minutos.",
    "pausa_min_s": "Pausa mínima, em segundos, antes de cada página da Amazon.",
    "pausa_max_s": "Pausa máxima, em segundos. Pausas menores aumentam a chance de CAPTCHA.",
    "resultados_por_busca": "Quantos resultados ler em cada busca (os primeiros da página).",
    "intervalo_busca_min": (
        "Minutos entre duas buscas do mesmo produto. Metade disso se ele teve oferta boa nas "
        "últimas 24 h; o dobro se não tem há 7 dias."
    ),
    "max_buscas_hora": "Teto de buscas por hora, para segurar o ritmo.",
    "limite_falha_pct": "Percentual de buscas com falha num ciclo a partir do qual o grupo admin é avisado.",
    "desconto_min_pct": "Desconto mínimo sobre o \"À partir de\" da Liga para avisar o grupo de oportunidades.",
    "realerta_queda_pct": "Queda extra de preço, em %, que gera um novo aviso da mesma oferta.",
    "liga_preco_max_idade_h": "Idade máxima, em horas, do preço da Liga usado como referência.",
    "vendedor_min_positivas_pct": "Percentual mínimo de avaliações positivas de um lojista com envio pela Amazon.",
    "vendedor_min_avaliacoes": "Número mínimo de avaliações de um lojista com envio pela Amazon.",
    "vendedor_reavaliar_dias": "De quantos em quantos dias reler o perfil de um lojista.",
}


def _hora(texto: str) -> time | None:
    try:
        hora = time.fromisoformat(texto)
    except ValueError:
        return None
    return hora if len(texto) == 5 else None


def validar_config(campos: Mapping[str, str]) -> tuple[dict[str, object], dict[str, str]]:
    valores: dict[str, object] = {}
    erros: dict[str, str] = {}

    url = (campos.get("url_busca") or "").strip()
    if not url.startswith("https://"):
        erros["url_busca"] = "Use uma URL que comece com https://."
    elif "{termo}" not in url:
        erros["url_busca"] = "A URL precisa conter {termo}."
    else:
        valores["url_busca"] = url

    for campo in ("janela_inicio", "janela_fim"):
        hora = _hora((campos.get(campo) or "").strip())
        if hora is None:
            erros[campo] = "Use o formato HH:MM, por exemplo 08:00."
        else:
            valores[campo] = hora

    for campo, (minimo, maximo) in LIMITES_CONFIG_AMAZON.items():
        texto = (campos.get(campo) or "").strip()
        if not (texto.isascii() and texto.isdecimal()) or len(texto) > 6:
            erros[campo] = f"Informe um número inteiro entre {minimo} e {maximo}."
            continue
        numero = int(texto)
        if not minimo <= numero <= maximo:
            erros[campo] = f"O valor deve ficar entre {minimo} e {maximo}."
            continue
        valores[campo] = numero

    if "pausa_min_s" in valores and "pausa_max_s" in valores and valores["pausa_min_s"] > valores["pausa_max_s"]:
        erros["pausa_min_s"] = "A pausa mínima não pode ser maior que a máxima."
    if "janela_inicio" in valores and "janela_fim" in valores and valores["janela_inicio"] >= valores["janela_fim"]:
        erros["janela_fim"] = "O fim da janela precisa ser depois do início."
    return valores, erros


def aplicar_config(s: Session, valores: Mapping[str, object], agora: datetime) -> None:
    s.execute(update(ConfigAmazon).where(ConfigAmazon.id == 1).values(**valores, atualizado_em=agora))
    s.flush()
```

O teste de número inválido espera "número inteiro" e o de fora do intervalo espera "entre 1 e 90": as duas mensagens acima contêm o trecho certo ("Informe um número inteiro entre 1 e 90." e "O valor deve ficar entre 1 e 90.").

- [ ] **Step 4: Rodar**

Run: `uv run pytest -q && uv run ruff check`
Expected: tudo passa.

- [ ] **Step 5: Commit**

```bash
git add src/tcg_sniper/coletor_amazon/config.py tests/coletor_amazon/test_config_amazon.py
git commit -m "feat: validate the Amazon settings form with the database limits"
```

---

### Task 5: Termo de busca, janela, intervalo e teto por hora

Funções puras do ritmo da fila.

**Files:**
- Create: `src/tcg_sniper/coletor_amazon/termo.py`, `src/tcg_sniper/coletor_amazon/fila.py`
- Test: `tests/coletor_amazon/test_termo.py`, `tests/coletor_amazon/test_fila.py`

**Interfaces:**
- Produces:
  - `termo_busca(nome: str) -> str`
  - `JITTER_JANELA_MIN = 15`; `Janela(inicio: datetime, fim: datetime)` com `contem(agora) -> bool`; `janela_do_dia(dia: date, inicio: time, fim: time, zona: ZoneInfo, rng: random.Random) -> Janela`
  - `intervalo_busca(base_min: int, agora: datetime, ultimo_candidato_em: datetime | None, entrou_em: datetime) -> timedelta`
  - `TetoPorHora()` com `registrar(agora: datetime) -> None` e `liberado_em(agora: datetime, maximo: int) -> datetime | None` (None = pode buscar agora)

- [ ] **Step 1: Escrever os testes**

`tests/coletor_amazon/test_termo.py`:

```python
import pytest

from tcg_sniper.coletor_amazon.termo import termo_busca


@pytest.mark.parametrize(
    ("nome", "termo"),
    [
        ("Caixa de Booster - Final Fantasy - Booster de Jogo", "Caixa de Booster Final Fantasy Booster de Jogo"),
        ("Kit de Pré Lançamento - Khans de Tarkir - Jeskai", "Kit de Pré Lançamento Khans de Tarkir Jeskai"),
        ("Booster Avulso - Final Fantasy - Value Booster", "Booster Avulso Final Fantasy Value Booster"),
        (
            "Kit Pré Lançamento - Dragões de Tarkir - Atarka (Battle With)",
            "Kit Pré Lançamento Dragões de Tarkir Atarka Battle With",
        ),
        ("Secret Lair: Deadpool / Marvel, Bundle", "Secret Lair Deadpool Marvel Bundle"),
        ("  Caixa –  Edição  ", "Caixa Edição"),
    ],
)
def test_termo_busca_mantem_o_nome_e_tira_so_a_pontuacao(nome, termo):
    assert termo_busca(nome) == termo
```

`tests/coletor_amazon/test_fila.py`:

```python
import random
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from tcg_sniper.coletor_amazon.fila import JITTER_JANELA_MIN, TetoPorHora, intervalo_busca, janela_do_dia

SP = ZoneInfo("America/Sao_Paulo")
DIA = date(2026, 10, 15)
AGORA = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)


def test_janela_respeita_o_jitter_no_fuso_certo():
    rng = random.Random(1)
    for _ in range(100):
        janela = janela_do_dia(DIA, time(8, 0), time(22, 0), SP, rng)
        base_inicio = datetime(2026, 10, 15, 8, 0, tzinfo=SP)
        base_fim = datetime(2026, 10, 15, 22, 0, tzinfo=SP)
        assert abs(janela.inicio - base_inicio) <= timedelta(minutes=JITTER_JANELA_MIN)
        assert abs(janela.fim - base_fim) <= timedelta(minutes=JITTER_JANELA_MIN)


def test_janela_contem():
    janela = janela_do_dia(DIA, time(8, 0), time(22, 0), SP, random.Random(1))
    assert janela.contem(datetime(2026, 10, 15, 12, 0, tzinfo=SP))
    assert not janela.contem(datetime(2026, 10, 15, 7, 0, tzinfo=SP))
    assert not janela.contem(datetime(2026, 10, 15, 23, 0, tzinfo=SP))


def test_janela_curta_nunca_inverte():
    for semente in range(50):
        janela = janela_do_dia(DIA, time(10, 0), time(10, 10), SP, random.Random(semente))
        assert janela.inicio < janela.fim


def test_intervalo_base():
    assert intervalo_busca(60, AGORA, None, AGORA - timedelta(days=1)) == timedelta(minutes=60)


def test_intervalo_metade_com_candidato_nas_ultimas_24h():
    assert intervalo_busca(60, AGORA, AGORA - timedelta(hours=24), AGORA - timedelta(days=30)) == timedelta(minutes=30)


def test_intervalo_dobro_sem_candidato_ha_7_dias():
    assert intervalo_busca(60, AGORA, AGORA - timedelta(days=7), AGORA - timedelta(days=30)) == timedelta(minutes=120)
    assert intervalo_busca(60, AGORA, None, AGORA - timedelta(days=7)) == timedelta(minutes=120)
    assert intervalo_busca(60, AGORA, None, AGORA - timedelta(days=6)) == timedelta(minutes=60)


def test_teto_por_hora():
    teto = TetoPorHora()
    for minuto in range(3):
        teto.registrar(AGORA + timedelta(minutes=minuto))
    assert teto.liberado_em(AGORA + timedelta(minutes=3), 4) is None
    assert teto.liberado_em(AGORA + timedelta(minutes=3), 3) == AGORA + timedelta(hours=1)
    assert teto.liberado_em(AGORA + timedelta(hours=1), 3) is None  # a primeira saiu da janela de 1 h
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/coletor_amazon/test_termo.py tests/coletor_amazon/test_fila.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementar**

`src/tcg_sniper/coletor_amazon/termo.py`:

```python
import re

_SEPARADORES = re.compile(r"[-–:()/,]")
_ESPACOS = re.compile(r"\s+")


def termo_busca(nome: str) -> str:
    """Nome do produto da Liga como termo de busca na Amazon: mantém o nome inteiro (inclusive o
    tipo, "Caixa de Booster", "Kit de Pré Lançamento"...) e só troca a pontuação por espaço."""
    return _ESPACOS.sub(" ", _SEPARADORES.sub(" ", nome)).strip()
```

`src/tcg_sniper/coletor_amazon/fila.py`:

```python
"""Ritmo da fila da Amazon: janela do dia, intervalo entre buscas do mesmo produto e teto por hora."""

import random
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

JITTER_JANELA_MIN = 15
UMA_HORA = timedelta(hours=1)


@dataclass(frozen=True)
class Janela:
    inicio: datetime
    fim: datetime

    def contem(self, agora: datetime) -> bool:
        return self.inicio <= agora < self.fim


def janela_do_dia(dia: date, inicio: time, fim: time, zona: ZoneInfo, rng: random.Random) -> Janela:
    """Início e fim do dia no fuso, cada um com variação aleatória de até JITTER_JANELA_MIN minutos."""

    def com_jitter(hora: time) -> datetime:
        return datetime.combine(dia, hora, tzinfo=zona) + timedelta(
            minutes=rng.uniform(-JITTER_JANELA_MIN, JITTER_JANELA_MIN)
        )

    abre, fecha = com_jitter(inicio), com_jitter(fim)
    return Janela(abre, max(fecha, abre + timedelta(minutes=1)))


def intervalo_busca(
    base_min: int, agora: datetime, ultimo_candidato_em: datetime | None, entrou_em: datetime
) -> timedelta:
    """Base; metade se houve candidato nas últimas 24 h; o dobro se não há candidato há 7 dias
    (ou nunca houve, depois de 7 dias na fila)."""
    base = timedelta(minutes=base_min)
    if ultimo_candidato_em is not None and agora - ultimo_candidato_em <= timedelta(hours=24):
        return base / 2
    referencia = ultimo_candidato_em or entrou_em
    if agora - referencia >= timedelta(days=7):
        return base * 2
    return base


class TetoPorHora:
    """Conta as buscas da última hora (em memória; um reinício zera, o que é seguro)."""

    def __init__(self) -> None:
        self._buscas: deque[datetime] = deque()

    def registrar(self, agora: datetime) -> None:
        self._buscas.append(agora)

    def liberado_em(self, agora: datetime, maximo: int) -> datetime | None:
        while self._buscas and self._buscas[0] <= agora - UMA_HORA:
            self._buscas.popleft()
        if len(self._buscas) < maximo:
            return None
        return self._buscas[0] + UMA_HORA
```

- [ ] **Step 4: Rodar**

Run: `uv run pytest -q && uv run ruff check`
Expected: tudo passa.

- [ ] **Step 5: Commit**

```bash
git add src/tcg_sniper/coletor_amazon/termo.py src/tcg_sniper/coletor_amazon/fila.py tests/coletor_amazon/test_termo.py tests/coletor_amazon/test_fila.py
git commit -m "feat: Amazon search term, daily window, search interval and hourly cap"
```

---

### Task 6: Detecção de CAPTCHA e captura das páginas reais da Amazon

A detecção de desafio vem antes da captura, porque o script de captura precisa saber quando parar e esperar uma pessoa. As páginas inteiras ficam em `.fixtures-brutas/amazon/`, **fora do git**; só o recorte (Task 7) vai para o repositório.

**Files:**
- Create: `src/tcg_sniper/coletor_amazon/desafio.py`
- Modify: `scripts/capturar_fixture.py`, `.gitignore`
- Test: `tests/coletor_amazon/test_desafio_amazon.py`

**Interfaces:**
- Produces: `MARCADORES_HTML: tuple[str, ...]`, `eh_desafio_amazon(pagina: Pagina) -> bool`

- [ ] **Step 1: Escrever os testes (HTML mínimo; os de fixtures reais entram na Task 7)**

`tests/coletor_amazon/test_desafio_amazon.py`:

```python
import pytest
from fakes import pagina_html

from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon

CAPTCHA = (
    "<html><body><h4>Digite os caracteres que você vê abaixo</h4>"
    '<form method="get" action="/errors/validateCaptcha" name=""><input name="field-keywords"></form>'
    "</body></html>"
)


def test_formulario_de_captcha_e_desafio():
    assert eh_desafio_amazon(pagina_html(CAPTCHA, titulo="Amazon.com.br"))


@pytest.mark.parametrize(
    "html",
    [
        '<form action="/errors/validateCaptcha"></form>',
        "<p>Digite os caracteres que você vê abaixo</p>",
        "<!-- To discuss automated access to Amazon data please contact api-services-support@amazon.com. -->",
    ],
)
def test_cada_marcador_sozinho_e_desafio(html):
    assert eh_desafio_amazon(pagina_html(html))


def test_pagina_comum_nao_e_desafio():
    html = '<html><body><div class="s-main-slot"><form action="/s"><input name="k"></form></div></body></html>'
    assert not eh_desafio_amazon(pagina_html(html, titulo="Amazon.com.br : magic"))
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/coletor_amazon/test_desafio_amazon.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementar**

`src/tcg_sniper/coletor_amazon/desafio.py`:

```python
from tcg_sniper.navegador.modelos import Pagina

# Marcadores exclusivos da página de verificação ("robot check") da Amazon. Conferidos contra
# páginas normais reais na Task 7 (nenhuma fixture normal pode casar).
MARCADORES_HTML = (
    'action="/errors/validatecaptcha"',
    "digite os caracteres que você vê",
    "api-services-support@amazon.com",
)


def eh_desafio_amazon(pagina: Pagina) -> bool:
    html = pagina.html.lower()
    return any(marcador in html for marcador in MARCADORES_HTML)
```

- [ ] **Step 4: Rodar**

Run: `uv run pytest tests/coletor_amazon/test_desafio_amazon.py -q`
Expected: PASS.

- [ ] **Step 5: Script de captura para qualquer site**

Em `.gitignore`, acrescente:

```
# Páginas inteiras capturadas para estudo; só o recorte vai para tests/fixtures.
.fixtures-brutas/
.perfil-dev-amazon/
```

Em `scripts/capturar_fixture.py`:

1. No docstring do topo, troque as linhas de uso por:

```
Uso:
  uv run python scripts/capturar_fixture.py <url> <nome> [--destino PASTA]
  uv run python scripts/capturar_fixture.py <url> <nome> --expandir [--max-cliques N]   (só LigaMagic)

Salva em <PASTA>/<nome>.html (padrão: tests/fixtures/liga para a LigaMagic e
.fixtures-brutas/amazon para a Amazon, que fica fora do git até ser recortada). Usa um perfil
de desenvolvimento por site (.perfil-dev e .perfil-dev-amazon, fora do git).
```

2. Imports: acrescente `from urllib.parse import urlsplit`, `from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon` e `from tcg_sniper.navegador.chromium import NavegadorChromium`.
3. Troque `DESTINO = Path("tests/fixtures/liga")` por:

```python
DESTINOS = {"liga": Path("tests/fixtures/liga"), "amazon": Path(".fixtures-brutas/amazon")}


def site_da_url(url: str) -> str:
    return "amazon" if "amazon." in urlsplit(url).netloc else "liga"
```

4. Em `main`, acrescente `parser.add_argument("--destino", type=Path)` e, logo depois de `args = parser.parse_args()`:

```python
    site = site_da_url(args.url)
    if args.expandir and site != "liga":
        parser.error("--expandir só vale para a LigaMagic")
    detector = eh_desafio_amazon if site == "amazon" else eh_desafio
    destino = args.destino or DESTINOS[site]
    contexto = (
        NavegadorChromium(Path(".perfil-dev-amazon"), eh_desafio_amazon)
        if site == "amazon"
        else NavegadorPlaywright(Path(".perfil-dev"))
    )
```

Troque `with NavegadorPlaywright(Path(".perfil-dev")) as navegador:` por `with contexto as navegador:`, `if eh_desafio(pagina):` por `if detector(pagina):`, `DESTINO.mkdir(parents=True, exist_ok=True)` por `destino.mkdir(parents=True, exist_ok=True)` e `arquivo = DESTINO / f"{args.nome}.html"` por `arquivo = destino / f"{args.nome}.html"`.

- [ ] **Step 6: Capturar as páginas reais (uma por vez, pelo menos 10 s entre elas)**

Respeite o ritmo: no máximo umas 20 páginas no total, uma de cada vez, esperando pelo menos 10 segundos entre um comando e o seguinte. Se aparecer o CAPTCHA durante as capturas normais, o script pede para resolver na janela do Chromium.

```bash
uv run python scripts/capturar_fixture.py "https://www.amazon.com.br/s?k=Caixa+de+Booster+Final+Fantasy+Booster+de+Jogo" busca_resultados
uv run python scripts/capturar_fixture.py "https://www.amazon.com.br/s?k=xqzvwplk+inexistente+magic+918273" busca_sem_resultados
```

Liste os ASINs da busca para escolher os produtos:

```bash
uv run python -I -c "
import re, sys
html = open(sys.argv[1], encoding='utf-8').read()
for asin in dict.fromkeys(re.findall(r'data-asin=\"([A-Z0-9]{10})\"', html)):
    print(asin)
" .fixtures-brutas/amazon/busca_resultados.html
```

Abra alguns `https://www.amazon.com.br/dp/<ASIN>` e capture até ter os quatro tipos de oferta. O tipo se vê no quadro de compra da página ("Vendido por" e "Enviado por"):

```bash
uv run python scripts/capturar_fixture.py "https://www.amazon.com.br/dp/<ASIN>" produto_vendido_amazon   # Vendido por Amazon.com.br
uv run python scripts/capturar_fixture.py "https://www.amazon.com.br/dp/<ASIN>" produto_fba             # Vendido por lojista, enviado pela Amazon
uv run python scripts/capturar_fixture.py "https://www.amazon.com.br/dp/<ASIN>" produto_envio_proprio   # Vendido e enviado por lojista
uv run python scripts/capturar_fixture.py "https://www.amazon.com.br/dp/<ASIN>" produto_indisponivel    # "Não disponível", sem preço
```

Se a busca de Magic não tiver algum dos tipos, procure numa busca vizinha (`k=booster+pokemon`, `k=deck+commander+magic`): o parser é o mesmo para qualquer produto. Depois, o perfil do lojista FBA; o `seller_id` está no link do vendedor na página (`seller=...`):

```bash
uv run python -I -c "
import re, sys
print(set(re.findall(r'seller=([A-Z0-9]+)', open(sys.argv[1], encoding='utf-8').read())))
" .fixtures-brutas/amazon/produto_fba.html
uv run python scripts/capturar_fixture.py "https://www.amazon.com.br/sp?seller=<SELLER_ID>" vendedor
```

Por fim, a página de CAPTCHA. Não dá para provocá-la de propósito sem forçar o ritmo, o que está fora das regras. Se ela apareceu em alguma captura acima, salve-a pelo Chromium (Ctrl+S, "Página da Web, somente HTML") como `.fixtures-brutas/amazon/captcha.html` antes de resolver. Se não apareceu, crie `.fixtures-brutas/amazon/captcha.html` com o conteúdo de `CAPTCHA` do Step 1 e registre no Step 7 que essa fixture é sintética.

- [ ] **Step 7: Registrar a estrutura observada**

Confira nas páginas brutas as hipóteses de estrutura que a Task 7 usa (são as da Amazon em 2026; ela muda o layout de tempos em tempos):

```bash
uv run python -I -c "
import sys
from selectolax.lexbor import LexborHTMLParser
SELETORES = [
    'div.s-main-slot',
    'div.s-main-slot div[data-component-type=\"s-search-result\"]',
    'div[data-component-type=\"s-search-result\"] h2',
    '.a-price:not(.a-text-price) .a-offscreen',
    '.puis-sponsored-label-text',
    '.s-sponsored-label-text',
    '#productTitle',
    '#corePrice_feature_div .a-price .a-offscreen',
    '#corePriceDisplay_desktop_feature_div .a-price .a-offscreen',
    '#apex_desktop .a-price .a-offscreen',
    '[offer-display-feature-name=\"desktop-merchant-info\"] .offer-display-feature-text-message',
    '[offer-display-feature-name=\"desktop-fulfiller-info\"] .offer-display-feature-text-message',
    '#sellerProfileTriggerId',
    '#seller-name',
    '#seller-info-feedback-summary',
]
for arquivo in sys.argv[1:]:
    arvore = LexborHTMLParser(open(arquivo, encoding='utf-8').read())
    print('==', arquivo)
    for seletor in SELETORES:
        nos = arvore.css(seletor)
        if nos:
            print(f'  {len(nos):3} {seletor}: {nos[0].text(strip=True)[:90]!r}')
" .fixtures-brutas/amazon/*.html
```

Para cada seletor que não aparecer onde deveria (por exemplo, o preço da página de produto num contêiner com outro id, o "Vendido por" no bloco antigo `#merchant-info`, o resumo do vendedor com outro id), procure no HTML bruto o elemento equivalente e anote o seletor real. As anotações viram o docstring e as constantes `SELETOR_*` de `coletor_amazon/parsers.py` na Task 7. Guarde-as em `.fixtures-brutas/amazon/NOTAS.md` (fora do git) até lá.

- [ ] **Step 8: Rodar a suíte e commitar (sem nenhuma página bruta)**

Run: `uv run pytest -q && uv run ruff check && git status --short`
Expected: tudo passa; `git status` não lista nada de `.fixtures-brutas/`.

```bash
git add src/tcg_sniper/coletor_amazon/desafio.py tests/coletor_amazon/test_desafio_amazon.py scripts/capturar_fixture.py .gitignore
git commit -m "feat: Amazon CAPTCHA detection and per-site fixture capture"
```

---

### Task 7: Parsers da Amazon com fixtures recortadas

Os parsers são funções puras sobre o HTML. As constantes `SELETOR_*` abaixo são as hipóteses da Task 6; onde a Task 6 anotou outro seletor, use o anotado (os testes, escritos com valores lidos das páginas reais, dizem se o seletor está certo). `ErroParser` e `parse_preco_brl` saem da Liga para `tcg_sniper/parsing.py`, porque os dois sites usam.

**Files:**
- Create: `src/tcg_sniper/parsing.py`, `src/tcg_sniper/coletor_amazon/parsers.py`
- Modify: `src/tcg_sniper/coletor_liga/modelos.py` (reexporta `ErroParser`), `src/tcg_sniper/coletor_liga/parsers.py` (reexporta `parse_preco_brl`)
- Modify: `scripts/recortar_fixture.py` (blocos da Amazon), `tests/fakes.py` (`fixture_amazon`)
- Create: `tests/fixtures/amazon/*.html` (recortadas)
- Test: `tests/coletor_amazon/test_parsers_amazon.py`, `tests/coletor_amazon/test_desafio_amazon.py`

**Interfaces:**
- Consumes: `ResultadoBusca`, `OfertaProduto`, `AvaliacaoVendedor`, `SELLER_AMAZON` (Task 3); `eh_desafio_amazon` (Task 6); `Envio` (Task 2).
- Produces:
  - `tcg_sniper.parsing`: `ErroParser(Exception)`, `parse_preco_brl(texto: str) -> Decimal`
  - `tcg_sniper.coletor_amazon.parsers`: `BASE_AMAZON = "https://www.amazon.com.br"`, `url_produto(asin) -> str`, `url_vendedor(seller_id) -> str`, `eh_vendido_pela_amazon(texto: str) -> bool`, `classificar_envio(vendido_por: str | None, enviado_por: str | None) -> Envio`, `parse_busca(html: str, limite: int) -> list[ResultadoBusca]`, `parse_produto_amazon(html: str, asin: str) -> OfertaProduto`, `parse_vendedor(html: str, seller_id: str) -> AvaliacaoVendedor`, `SELETOR_GRADE_BUSCA`, `BLOCOS_BUSCA`, `BLOCOS_PRODUTO`, `BLOCOS_VENDEDOR`
  - `tests/fakes.py`: `fixture_amazon(nome: str) -> str`

- [ ] **Step 1: Mover `ErroParser` e `parse_preco_brl`**

`src/tcg_sniper/parsing.py` (o corpo de `parse_preco_brl` e `_RE_PRECO` é o de hoje em `coletor_liga/parsers.py`):

```python
"""Peças de parsing comuns aos sites."""

import re
from decimal import Decimal

_RE_PRECO = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+),(\d{2})")


class ErroParser(Exception):
    """HTML não tem a estrutura esperada (provável mudança de layout)."""


def parse_preco_brl(texto: str) -> Decimal:
    """"R$ 1.234,56" → Decimal("1234.56"). Sem "R$", NBSP e espaços nas pontas, o texto inteiro
    tem de ser um preço: qualquer sobra → `ErroParser` (nunca truncar)."""
    limpo = texto.replace("\xa0", " ").strip().removeprefix("R$").strip()
    m = _RE_PRECO.fullmatch(limpo)
    if not m:
        raise ErroParser(f"preço inválido: {texto!r}")
    return Decimal(f"{m.group(1).replace('.', '')}.{m.group(2)}")
```

Em `src/tcg_sniper/coletor_liga/modelos.py`, apague a classe `ErroParser` e acrescente `from tcg_sniper.parsing import ErroParser as ErroParser` junto das outras reexportações. Em `src/tcg_sniper/coletor_liga/parsers.py`, apague `_RE_PRECO` e a função `parse_preco_brl` e acrescente `from tcg_sniper.parsing import parse_preco_brl as parse_preco_brl` (os testes da Liga importam `parse_preco_brl` de lá).

Run: `uv run pytest -q`
Expected: tudo passa (nada mudou de comportamento).

- [ ] **Step 2: Copiar as páginas brutas para o lugar das fixtures (sem `git add`)**

```bash
mkdir -p tests/fixtures/amazon
cp .fixtures-brutas/amazon/*.html tests/fixtures/amazon/
```

Até o Step 9 essas cópias são páginas inteiras: não as adicione ao git. O Step 9 as recorta no lugar.

Acrescente a `tests/fakes.py`:

```python
DIR_FIXTURES_AMAZON = Path(__file__).parent / "fixtures" / "amazon"


def fixture_amazon(nome: str) -> str:
    return (DIR_FIXTURES_AMAZON / f"{nome}.html").read_text(encoding="utf-8")
```

- [ ] **Step 3: Ler nas páginas os valores esperados**

Os testes do Step 4 comparam com valores lidos à mão nas páginas reais, não com o que o parser devolve. Leia cada valor no HTML (busque pelo ASIN ou pelo texto, ou abra a página no navegador):

- `busca_resultados`: quantos cartões `data-component-type="s-search-result"` com `data-asin` não vazio há dentro de `div.s-main-slot` (`TOTAL_RESULTADOS`); ASIN, título e preço do primeiro (`PRIMEIRO`); quantos têm a marca de patrocinado (`PATROCINADOS`).
- `busca_sem_resultados`: quantos cartões de resultado há (`TOTAL_SEM_RESULTADOS`; 0, ou o número de "resultados relacionados" se a Amazon os mostrar como cartões normais).
- Cada `produto_*`: ASIN (da URL capturada), título (`#productTitle`), preço da oferta principal, texto de "Vendido por", `seller_id` do link do vendedor e o tipo de envio.
- `vendedor`: nome, % de positivas e número de avaliações dos últimos 12 meses.

- [ ] **Step 4: Escrever os testes**

`tests/coletor_amazon/test_parsers_amazon.py` (troque cada valor entre `<` e `>` pelo valor lido no Step 3; nenhum pode ficar sem troca):

```python
from decimal import Decimal

import pytest
from fakes import fixture_amazon

from tcg_sniper.coletor_amazon.modelos import SELLER_AMAZON, AvaliacaoVendedor, OfertaProduto
from tcg_sniper.coletor_amazon.parsers import (
    classificar_envio,
    eh_vendido_pela_amazon,
    parse_busca,
    parse_produto_amazon,
    parse_vendedor,
    url_produto,
)
from tcg_sniper.db.models import Envio
from tcg_sniper.parsing import ErroParser

# Valores lidos à mão nas páginas reais capturadas na Task 6.
TOTAL_RESULTADOS = <inteiro>
PRIMEIRO = ("<ASIN>", "<título do primeiro cartão>", Decimal("<preço>"))
PATROCINADOS = <inteiro>
TOTAL_SEM_RESULTADOS = <inteiro>
PRODUTOS = {
    "produto_vendido_amazon": OfertaProduto(
        "<ASIN>", "<título>", Decimal("<preço>"), "<Vendido por>", SELLER_AMAZON, Envio.AMAZON
    ),
    "produto_fba": OfertaProduto("<ASIN>", "<título>", Decimal("<preço>"), "<Vendido por>", "<SELLER_ID>", Envio.FBA),
    "produto_envio_proprio": OfertaProduto(
        "<ASIN>", "<título>", Decimal("<preço>"), "<Vendido por>", "<SELLER_ID>", Envio.PROPRIO
    ),
    "produto_indisponivel": OfertaProduto("<ASIN>", "<título>", None, None, None, Envio.DESCONHECIDO),
}
VENDEDOR = AvaliacaoVendedor("<SELLER_ID>", "<nome>", Decimal("<pct>"), <num_avaliacoes>)


def test_busca_real():
    itens = parse_busca(fixture_amazon("busca_resultados"), limite=48)
    assert len(itens) == TOTAL_RESULTADOS
    assert (itens[0].asin, itens[0].titulo, itens[0].preco) == PRIMEIRO
    assert itens[0].url == url_produto(PRIMEIRO[0])
    assert sum(i.patrocinado for i in itens) == PATROCINADOS
    assert all(i.preco is None or i.preco > 0 for i in itens)


def test_busca_respeita_o_limite():
    assert len(parse_busca(fixture_amazon("busca_resultados"), limite=3)) == min(3, TOTAL_RESULTADOS)


def test_busca_sem_resultados():
    assert len(parse_busca(fixture_amazon("busca_sem_resultados"), limite=48)) == TOTAL_SEM_RESULTADOS


def test_cartao_sem_preco_vira_none():
    sem_preco = fixture_amazon("busca_resultados").replace("a-offscreen", "a-sem-preco")
    assert all(i.preco is None for i in parse_busca(sem_preco, limite=48))


@pytest.mark.parametrize("nome", ["vendedor", "produto_fba"])
def test_busca_sem_grade_e_erro(nome):
    with pytest.raises(ErroParser):
        parse_busca(fixture_amazon(nome), limite=10)


@pytest.mark.parametrize("nome", list(PRODUTOS))
def test_produto_real(nome):
    esperado = PRODUTOS[nome]
    assert parse_produto_amazon(fixture_amazon(nome), esperado.asin) == esperado


def test_produto_sem_titulo_e_erro():
    with pytest.raises(ErroParser):
        parse_produto_amazon(fixture_amazon("busca_resultados"), "B000000000")


def test_vendedor_real():
    assert parse_vendedor(fixture_amazon("vendedor"), VENDEDOR.seller_id) == VENDEDOR


def test_vendedor_sem_resumo_e_erro():
    with pytest.raises(ErroParser):
        parse_vendedor("<html><body></body></html>", "A1")


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [("Amazon.com.br", True), ("  amazon  ", True), ("AMAZON", True), ("Amazonas Games", False), ("Loja X", False)],
)
def test_eh_vendido_pela_amazon(texto, esperado):
    assert eh_vendido_pela_amazon(texto) is esperado


@pytest.mark.parametrize(
    ("vendido", "enviado", "envio"),
    [
        ("Amazon.com.br", "Amazon.com.br", Envio.AMAZON),
        ("Amazon.com.br", None, Envio.AMAZON),
        ("Loja X", "Amazon", Envio.FBA),
        ("Loja X", "Amazon.com.br", Envio.FBA),
        ("Amazonas Games", "Amazonas Games", Envio.PROPRIO),
        ("Loja X", "Loja X", Envio.PROPRIO),
        ("Loja X", None, Envio.DESCONHECIDO),
        (None, "Amazon", Envio.DESCONHECIDO),
        (None, None, Envio.DESCONHECIDO),
    ],
)
def test_classificar_envio(vendido, enviado, envio):
    assert classificar_envio(vendido, enviado) is envio
```

Acrescente a `tests/coletor_amazon/test_desafio_amazon.py` (import `fixture_amazon` de `fakes`):

```python
NORMAIS = [
    "busca_resultados",
    "busca_sem_resultados",
    "produto_vendido_amazon",
    "produto_fba",
    "produto_envio_proprio",
    "produto_indisponivel",
    "vendedor",
]


@pytest.mark.parametrize("nome", NORMAIS)
def test_paginas_reais_normais_nao_sao_desafio(nome):
    assert not eh_desafio_amazon(pagina_html(fixture_amazon(nome), titulo="Amazon.com.br"))


def test_pagina_de_captcha_e_desafio():
    assert eh_desafio_amazon(pagina_html(fixture_amazon("captcha"), titulo="Amazon.com.br"))
```

- [ ] **Step 5: Rodar e ver falhar**

Run: `uv run pytest tests/coletor_amazon -q`
Expected: FAIL em `test_parsers_amazon.py` (`ModuleNotFoundError: tcg_sniper.coletor_amazon.parsers`); os de desafio passam. Se algum `test_paginas_reais_normais_nao_sao_desafio` falhar, um marcador de `MARCADORES_HTML` aparece em página normal: troque-o por um mais exclusivo, lido na página de CAPTCHA.

- [ ] **Step 6: Implementar os parsers**

`src/tcg_sniper/coletor_amazon/parsers.py` (ajuste as constantes `SELETOR_*` e o docstring com o que a Task 6 anotou):

```python
"""Parsers puros do HTML da amazon.com.br, escritos a partir de páginas reais (recortadas em
tests/fixtures/amazon). Estrutura observada na captura da Task 6:

Busca (`/s?k=<termo>`):
- Grade: `div.s-main-slot` (marcador de estrutura; ausente → `ErroParser`).
- Cada resultado: `div[data-component-type="s-search-result"]` com o ASIN em `data-asin`
  (cartões sem ASIN, como faixas e anúncios de marca, são ignorados).
- Título: texto do `h2` do cartão (ausente num cartão com ASIN → `ErroParser`).
- Preço: `.a-price:not(.a-text-price) .a-offscreen` ("R$ 599,90"); o `.a-text-price` é o
  preço riscado "De:". Sem preço → `None`.
- Patrocinado: `.puis-sponsored-label-text` ou `.s-sponsored-label-text` dentro do cartão.

Produto (`/dp/<ASIN>`):
- Título: `#productTitle` (ausente → `ErroParser`).
- Preço da oferta principal: o primeiro `.a-price .a-offscreen` em `#corePrice_feature_div`,
  `#corePriceDisplay_desktop_feature_div` ou `#apex_desktop`. Indisponível → `None`.
- "Vendido por" e "Enviado por": `[offer-display-feature-name="desktop-merchant-info"]` e
  `[offer-display-feature-name="desktop-fulfiller-info"]`, texto em
  `.offer-display-feature-text-message`.
- Vendedor: link `#sellerProfileTriggerId`, com `seller=<ID>` no href.

Perfil do vendedor (`/sp?seller=<ID>`):
- Nome: `#seller-name`.
- Resumo: `#seller-info-feedback-summary` (ausente → `ErroParser`), com "97% positivas nos
  últimos 12 meses (2.340 avaliações)".
"""

import re
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

from tcg_sniper.coletor_amazon.modelos import SELLER_AMAZON, AvaliacaoVendedor, OfertaProduto, ResultadoBusca
from tcg_sniper.db.models import Envio
from tcg_sniper.parsing import ErroParser, parse_preco_brl

BASE_AMAZON = "https://www.amazon.com.br"

SELETOR_GRADE_BUSCA = "div.s-main-slot"
SELETOR_RESULTADO = 'div[data-component-type="s-search-result"]'
SELETOR_TITULO_RESULTADO = "h2"
SELETOR_PRECO_RESULTADO = ".a-price:not(.a-text-price) .a-offscreen"
SELETORES_PATROCINADO = (".puis-sponsored-label-text", ".s-sponsored-label-text")

SELETOR_TITULO_PRODUTO = "#productTitle"
SELETORES_PRECO_PRODUTO = (
    "#corePrice_feature_div .a-price .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
    "#apex_desktop .a-price .a-offscreen",
)
SELETOR_VENDIDO_POR = '[offer-display-feature-name="desktop-merchant-info"] .offer-display-feature-text-message'
SELETOR_ENVIADO_POR = '[offer-display-feature-name="desktop-fulfiller-info"] .offer-display-feature-text-message'
SELETOR_LINK_VENDEDOR = "#sellerProfileTriggerId"

SELETOR_NOME_VENDEDOR = "#seller-name"
SELETOR_RESUMO_VENDEDOR = "#seller-info-feedback-summary"
_RE_PCT_POSITIVAS = re.compile(r"(\d{1,3})\s*%\s*(?:de\s+)?(?:avaliações\s+)?positiv", re.IGNORECASE)
_RE_NUM_AVALIACOES = re.compile(r"\(\s*([\d.]+)\s+avalia", re.IGNORECASE)

# Trechos que o recorte das fixtures mantém (scripts/recortar_fixture.py): tudo o que os parsers leem.
BLOCOS_BUSCA = (SELETOR_RESULTADO,)
BLOCOS_PRODUTO = (
    SELETOR_TITULO_PRODUTO,
    "#corePrice_feature_div",
    "#corePriceDisplay_desktop_feature_div",
    "#apex_desktop",
    '[offer-display-feature-name="desktop-merchant-info"]',
    '[offer-display-feature-name="desktop-fulfiller-info"]',
    SELETOR_LINK_VENDEDOR,
)
BLOCOS_VENDEDOR = (SELETOR_NOME_VENDEDOR, SELETOR_RESUMO_VENDEDOR)

_NOMES_AMAZON = {"amazon", "amazon.com.br"}


def url_produto(asin: str) -> str:
    return f"{BASE_AMAZON}/dp/{asin}"


def url_vendedor(seller_id: str) -> str:
    return f"{BASE_AMAZON}/sp?seller={seller_id}"


def eh_vendido_pela_amazon(texto: str) -> bool:
    """Só "Amazon" ou "Amazon.com.br": um lojista chamado "Amazonas Games" não é a Amazon."""
    return texto.strip().lower() in _NOMES_AMAZON


def classificar_envio(vendido_por: str | None, enviado_por: str | None) -> Envio:
    if vendido_por is None:
        return Envio.DESCONHECIDO
    if eh_vendido_pela_amazon(vendido_por):
        return Envio.AMAZON
    if enviado_por is None:
        return Envio.DESCONHECIDO
    return Envio.FBA if eh_vendido_pela_amazon(enviado_por) else Envio.PROPRIO


def _texto(no: LexborNode | LexborHTMLParser, seletor: str) -> str | None:
    alvo = no.css_first(seletor)
    if alvo is None:
        return None
    return alvo.text(separator=" ", strip=True) or None


def parse_busca(html: str, limite: int) -> list[ResultadoBusca]:
    """Os primeiros `limite` resultados da busca, na ordem da página (pode repetir ASIN)."""
    arvore = LexborHTMLParser(html)
    if arvore.css_first(SELETOR_GRADE_BUSCA) is None:
        raise ErroParser("grade de resultados da busca não encontrada")
    itens: list[ResultadoBusca] = []
    for cartao in arvore.css(f"{SELETOR_GRADE_BUSCA} {SELETOR_RESULTADO}"):
        if len(itens) >= limite:
            break
        asin = (cartao.attributes.get("data-asin") or "").strip()
        if not asin:
            continue
        titulo = _texto(cartao, SELETOR_TITULO_RESULTADO)
        if titulo is None:
            raise ErroParser(f"resultado {asin} sem título")
        preco = _texto(cartao, SELETOR_PRECO_RESULTADO)
        itens.append(
            ResultadoBusca(
                asin=asin,
                titulo=titulo,
                url=url_produto(asin),
                preco=parse_preco_brl(preco) if preco else None,
                patrocinado=any(cartao.css_first(s) is not None for s in SELETORES_PATROCINADO),
            )
        )
    return itens


def _seller_id(arvore: LexborHTMLParser) -> str | None:
    link = arvore.css_first(SELETOR_LINK_VENDEDOR)
    if link is None:
        return None
    valores = parse_qs(urlsplit(link.attributes.get("href") or "").query).get("seller")
    return valores[0] if valores else None


def parse_produto_amazon(html: str, asin: str) -> OfertaProduto:
    arvore = LexborHTMLParser(html)
    titulo = _texto(arvore, SELETOR_TITULO_PRODUTO)
    if titulo is None:
        raise ErroParser("título do produto não encontrado")
    preco = None
    for seletor in SELETORES_PRECO_PRODUTO:
        texto = _texto(arvore, seletor)
        if texto:
            preco = parse_preco_brl(texto)
            break
    vendido_por = _texto(arvore, SELETOR_VENDIDO_POR)
    envio = classificar_envio(vendido_por, _texto(arvore, SELETOR_ENVIADO_POR))
    seller_id = SELLER_AMAZON if envio is Envio.AMAZON else _seller_id(arvore)
    return OfertaProduto(asin, titulo, preco, vendido_por, seller_id, envio)


def parse_vendedor(html: str, seller_id: str) -> AvaliacaoVendedor:
    arvore = LexborHTMLParser(html)
    resumo = arvore.css_first(SELETOR_RESUMO_VENDEDOR)
    if resumo is None:
        raise ErroParser("resumo de avaliações do vendedor não encontrado")
    texto = resumo.text(separator=" ", strip=True)
    pct = _RE_PCT_POSITIVAS.search(texto)
    num = _RE_NUM_AVALIACOES.search(texto)
    return AvaliacaoVendedor(
        seller_id=seller_id,
        nome=_texto(arvore, SELETOR_NOME_VENDEDOR),
        pct_positivas=Decimal(pct.group(1)) if pct else None,
        num_avaliacoes=int(num.group(1).replace(".", "")) if num else None,
    )
```

- [ ] **Step 7: Rodar até passar**

Run: `uv run pytest tests/coletor_amazon -q`
Expected: PASS. Quando um teste falhar porque o parser não achou um elemento que está na página, corrija a constante `SELETOR_*` (e o docstring) com o seletor real. Nunca troque o valor esperado do teste pelo que o parser devolveu sem conferir na página.

- [ ] **Step 8: Recorte para a Amazon**

Em `scripts/recortar_fixture.py`:

1. No docstring, acrescente o item: "- Amazon: busca (só os cartões de resultado, dentro da grade), produto (título, preço, vendido/enviado por, link do vendedor), perfil do vendedor (nome e resumo) e CAPTCHA (o formulário e o texto da verificação)."
2. Imports:

```python
from tcg_sniper.coletor_amazon import parsers as amazon
from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon
```

3. Antes de `def recortar`:

```python
SELETOR_FORM_CAPTCHA = 'form[action="/errors/validateCaptcha"]'


def _eh_amazon(arvore: LexborHTMLParser, titulo: str) -> bool:
    return "amazon" in titulo.lower() or arvore.css_first(SELETOR_FORM_CAPTCHA) is not None


def _blocos_amazon(arvore: LexborHTMLParser) -> list[str]:
    grade = arvore.css_first(amazon.SELETOR_GRADE_BUSCA)
    if grade is not None:
        atributos = "".join(f' {k}="{escape(v or "")}"' for k, v in grade.attributes.items())
        cartoes = "".join(_limpo(no) for s in amazon.BLOCOS_BUSCA for no in grade.css(s))
        return [f"<div{atributos}>{cartoes}</div>"]
    captcha = arvore.css_first(SELETOR_FORM_CAPTCHA)
    if captcha is not None:
        return ["<h4>Digite os caracteres que você vê abaixo</h4>", _limpo(captcha)]
    return [_limpo(no) for s in (*amazon.BLOCOS_PRODUTO, *amazon.BLOCOS_VENDEDOR) for no in arvore.css(s)]
```

4. Em `recortar`, troque o `if/else` que escolhe os blocos por:

```python
    if _eh_amazon(arvore, texto_titulo):
        blocos = _blocos_amazon(arvore)
    elif arvore.css_first(SELETOR_GRADE_LISTAGEM) is not None:
        blocos = _blocos_listagem(arvore)
    else:
        blocos = _blocos_produto(arvore)
```

e a linha do comentário fixo `"<!-- Recorte de uma página real da LigaMagic: só os trechos lidos pelos parsers "` (com a continuação na linha seguinte) por `"<!-- Recorte de uma página real: só os trechos lidos pelos parsers (scripts/recortar_fixture.py). -->\n"`.

5. Em `_resultados`, acrescente as chaves da Amazon ao dicionário devolvido:

```python
        "busca_amazon": _resultado(amazon.parse_busca, html, 48),
        "produto_amazon": _resultado(amazon.parse_produto_amazon, html, "X"),
        "vendedor_amazon": _resultado(amazon.parse_vendedor, html, "X"),
        "desafio_amazon": eh_desafio_amazon(
            Pagina(url=URL_BASE, status=200, titulo=texto_titulo, html=html, headers={})
        ),
```

As fixtures da Liga continuam com os mesmos resultados: os parsers da Amazon falham do mesmo jeito no original e no recorte. O recorte do CAPTCHA mantém o `form` (que basta para o detector) e acrescenta o texto da verificação; o script só grava quando todos os resultados batem.

- [ ] **Step 9: Recortar as fixtures e conferir**

```bash
uv run python scripts/recortar_fixture.py tests/fixtures/amazon/*.html
uv run python scripts/recortar_fixture.py tests/fixtures/liga/*.html
uv run pytest -q && uv run ruff check
ls -la tests/fixtures/amazon
```

Expected: cada fixture da Amazon cai de centenas de KB para poucos KB; as da Liga não mudam (o script é idempotente; `git status` não as lista); tudo passa. Se o script recusar alguma página ("o recorte muda o resultado"), acrescente aos `BLOCOS_*` o trecho que falta e rode de novo.

- [ ] **Step 10: Commit**

Confira que nenhuma página inteira vai junto: `git status --short` não pode listar `.fixtures-brutas/`, e os arquivos de `tests/fixtures/amazon/` devem ter poucos KB.

```bash
git add src/tcg_sniper/parsing.py src/tcg_sniper/coletor_amazon/parsers.py src/tcg_sniper/coletor_liga/modelos.py src/tcg_sniper/coletor_liga/parsers.py scripts/recortar_fixture.py tests/fakes.py tests/fixtures/amazon tests/coletor_amazon/test_parsers_amazon.py tests/coletor_amazon/test_desafio_amazon.py
git commit -m "feat: Amazon search, product and seller parsers with trimmed real fixtures"
```

---

### Task 8: Motor de oportunidades e mensagem do alerta

Funções puras: elegibilidade, decisão e texto. `formatar_brl` sai do admin para `tcg_sniper/formatacao.py`, porque a mensagem também usa.

**Files:**
- Create: `src/tcg_sniper/formatacao.py`, `src/tcg_sniper/oportunidades/__init__.py` (vazio), `src/tcg_sniper/oportunidades/motor.py`, `src/tcg_sniper/oportunidades/mensagens.py`
- Modify: `src/tcg_sniper/admin/app.py` (importa `formatar_brl`)
- Test: `tests/oportunidades/test_motor.py`, `tests/oportunidades/test_mensagens.py`

**Interfaces:**
- Consumes: `ConfigAmazon`, `Envio` (Task 2).
- Produces:
  - `tcg_sniper.formatacao.formatar_brl(valor: Decimal | None) -> str`
  - `tcg_sniper.oportunidades.motor`: `Regras(desconto_min_pct, realerta_queda_pct, liga_preco_max_idade_h, vendedor_min_positivas_pct, vendedor_min_avaliacoes)` com `Regras.de(config: ConfigAmazon)`; `Vendedor(nome: str | None, pct_positivas: Decimal | None, num_avaliacoes: int | None)`; `RefLiga(preco_a_partir: Decimal | None, listagem_em: datetime | None, num_lojas: int | None = None, preco_medio: Decimal | None = None)`; `Leitura(preco: Decimal | None, envio: Envio, vendedor: Vendedor | None)`; `Acao` (`ABRIR`, `REALERTAR`, `ATUALIZAR`, `FECHAR`, `NADA`); `atinge_desconto(preco_amazon, preco_liga, desconto_min_pct) -> bool`; `desconto_pct(preco_amazon, preco_liga) -> Decimal`; `vendedor_confiavel(vendedor, regras) -> bool`; `elegivel(leitura, ref, regras, agora) -> bool`; `decidir(leitura, ref, regras, agora, preco_alertado: Decimal | None) -> Acao`
  - `tcg_sniper.oportunidades.mensagens.mensagem_oportunidade(*, nome_produto: str, leitura: Leitura, ref: RefLiga, url_amazon: str, host: str, produto_id: int) -> str`

- [ ] **Step 1: Escrever os testes**

`tests/oportunidades/test_motor.py`:

```python
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tcg_sniper.db.models import Envio
from tcg_sniper.oportunidades.motor import (
    Acao,
    Leitura,
    RefLiga,
    Regras,
    Vendedor,
    atinge_desconto,
    decidir,
    desconto_pct,
    elegivel,
)

AGORA = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)
REGRAS = Regras(
    desconto_min_pct=25,
    realerta_queda_pct=5,
    liga_preco_max_idade_h=48,
    vendedor_min_positivas_pct=90,
    vendedor_min_avaliacoes=100,
)
LIGA = RefLiga(preco_a_partir=Decimal("1000.00"), listagem_em=AGORA - timedelta(hours=2))
CONFIAVEL = Vendedor("Loja", Decimal("97"), 2340)


def leitura(preco="700.00", envio=Envio.AMAZON, vendedor=None):
    return Leitura(None if preco is None else Decimal(preco), envio, vendedor)


@pytest.mark.parametrize(
    ("leit", "ref", "esperado"),
    [
        (leitura(), LIGA, True),
        (leitura(envio=Envio.FBA, vendedor=CONFIAVEL), LIGA, True),
        (leitura(envio=Envio.FBA, vendedor=Vendedor("Loja", Decimal("89"), 2340)), LIGA, False),
        (leitura(envio=Envio.FBA, vendedor=Vendedor("Loja", Decimal("97"), 99)), LIGA, False),
        (leitura(envio=Envio.FBA, vendedor=Vendedor("Loja", None, None)), LIGA, False),
        (leitura(envio=Envio.FBA, vendedor=None), LIGA, False),
        (leitura(envio=Envio.PROPRIO, vendedor=CONFIAVEL), LIGA, False),
        (leitura(envio=Envio.DESCONHECIDO), LIGA, False),
        (leitura(), RefLiga(None, AGORA), False),
        (leitura(), RefLiga(Decimal("1000.00"), None), False),
        (leitura(), RefLiga(Decimal("1000.00"), AGORA - timedelta(hours=48)), True),
        (leitura(), RefLiga(Decimal("1000.00"), AGORA - timedelta(hours=49)), False),
        (leitura("750.00"), LIGA, True),  # exatamente 25%: o limite é inclusivo
        (leitura("750.10"), LIGA, False),  # 24,99%
        (leitura(None), LIGA, False),
    ],
)
def test_elegivel(leit, ref, esperado):
    assert elegivel(leit, ref, REGRAS, AGORA) is esperado


def test_atinge_desconto_sem_arredondamento():
    assert atinge_desconto(Decimal("750.00"), Decimal("1000.00"), 25)
    assert not atinge_desconto(Decimal("750.01"), Decimal("1000.00"), 25)
    assert not atinge_desconto(None, Decimal("1000.00"), 25)
    assert not atinge_desconto(Decimal("1.00"), None, 25)
    assert not atinge_desconto(Decimal("1.00"), Decimal("0"), 25)


def test_desconto_pct():
    assert desconto_pct(Decimal("599.90"), Decimal("889.00")) == Decimal("32.52")


@pytest.mark.parametrize(
    ("preco", "preco_alertado", "acao"),
    [
        ("700.00", None, Acao.ABRIR),
        ("700.00", Decimal("700.00"), Acao.ATUALIZAR),
        ("665.00", Decimal("700.00"), Acao.REALERTAR),  # queda de exatamente 5%
        ("665.70", Decimal("700.00"), Acao.ATUALIZAR),  # queda de 4,9%
        ("760.00", Decimal("700.00"), Acao.FECHAR),  # deixou de ter 25%
        ("760.00", None, Acao.NADA),
    ],
)
def test_decidir(preco, preco_alertado, acao):
    assert decidir(leitura(preco), LIGA, REGRAS, AGORA, preco_alertado) is acao


def test_decidir_fecha_quando_o_vendedor_deixa_de_ser_elegivel():
    assert decidir(leitura(envio=Envio.PROPRIO), LIGA, REGRAS, AGORA, Decimal("700.00")) is Acao.FECHAR
```

`tests/oportunidades/test_mensagens.py`:

```python
from datetime import UTC, datetime
from decimal import Decimal

from tcg_sniper.db.models import Envio
from tcg_sniper.oportunidades.mensagens import mensagem_oportunidade
from tcg_sniper.oportunidades.motor import Leitura, RefLiga, Vendedor

AGORA = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)
NOME = "Caixa de Booster - Final Fantasy - Booster de Jogo"


def test_mensagem_vendido_pela_amazon_com_resumo_da_liga():
    texto = mensagem_oportunidade(
        nome_produto=NOME,
        leitura=Leitura(Decimal("599.90"), Envio.AMAZON, None),
        ref=RefLiga(Decimal("889.00"), AGORA, num_lojas=12, preco_medio=Decimal("910.00")),
        url_amazon="https://www.amazon.com.br/dp/B0TESTE123",
        host="host.test",
        produto_id=123,
    )
    assert texto == (
        "Oportunidade: Caixa de Booster - Final Fantasy - Booster de Jogo\n"
        "Amazon: R$ 599,90 (vendido pela Amazon), 32% abaixo da Liga\n"
        "Liga: a partir de R$ 889,00, 12 lojas, média de venda R$ 910,00\n"
        "https://www.amazon.com.br/dp/B0TESTE123\n"
        "Admin: http://host.test:8000/produto/123"
    )


def test_mensagem_fba_sem_resumo_da_liga():
    texto = mensagem_oportunidade(
        nome_produto=NOME,
        leitura=Leitura(Decimal("599.90"), Envio.FBA, Vendedor("Loja X", Decimal("97.50"), 2340)),
        ref=RefLiga(Decimal("889.00"), AGORA),
        url_amazon="https://www.amazon.com.br/dp/B0TESTE123",
        host="host.test",
        produto_id=123,
    )
    linhas = texto.split("\n")
    assert linhas[1] == (
        "Amazon: R$ 599,90 (vendido por Loja X (97,5% de 2.340 avaliações), enviado pela Amazon), 32% abaixo da Liga"
    )
    assert linhas[2] == "Liga: a partir de R$ 889,00"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/oportunidades -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementar**

`src/tcg_sniper/formatacao.py`:

```python
from decimal import Decimal


def formatar_brl(valor: Decimal | None) -> str:
    if valor is None:
        return "—"
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"
```

Em `src/tcg_sniper/admin/app.py`, apague a função `formatar_brl` e importe `from tcg_sniper.formatacao import formatar_brl` (os testes do admin importam `formatar_brl` de `admin.app`, e o import continua servindo; se o ruff acusar import não usado, use `from tcg_sniper.formatacao import formatar_brl as formatar_brl`).

`src/tcg_sniper/oportunidades/__init__.py`: vazio.

`src/tcg_sniper/oportunidades/motor.py`:

```python
"""Motor de oportunidades: decide, para uma leitura da página do produto na Amazon, se há uma
oferta elegível e o que fazer com a oportunidade do anúncio. Funções puras."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from tcg_sniper.db.models import ConfigAmazon, Envio

CEM = Decimal(100)


@dataclass(frozen=True)
class Regras:
    desconto_min_pct: int
    realerta_queda_pct: int
    liga_preco_max_idade_h: int
    vendedor_min_positivas_pct: int
    vendedor_min_avaliacoes: int

    @classmethod
    def de(cls, config: ConfigAmazon) -> "Regras":
        return cls(
            desconto_min_pct=config.desconto_min_pct,
            realerta_queda_pct=config.realerta_queda_pct,
            liga_preco_max_idade_h=config.liga_preco_max_idade_h,
            vendedor_min_positivas_pct=config.vendedor_min_positivas_pct,
            vendedor_min_avaliacoes=config.vendedor_min_avaliacoes,
        )


@dataclass(frozen=True)
class Vendedor:
    nome: str | None
    pct_positivas: Decimal | None
    num_avaliacoes: int | None


@dataclass(frozen=True)
class RefLiga:
    preco_a_partir: Decimal | None
    listagem_em: datetime | None
    num_lojas: int | None = None
    preco_medio: Decimal | None = None


@dataclass(frozen=True)
class Leitura:
    preco: Decimal | None
    envio: Envio
    vendedor: Vendedor | None


class Acao(StrEnum):
    ABRIR = "abrir"
    REALERTAR = "realertar"
    ATUALIZAR = "atualizar"
    FECHAR = "fechar"
    NADA = "nada"


def atinge_desconto(preco_amazon: Decimal | None, preco_liga: Decimal | None, desconto_min_pct: int) -> bool:
    """`1 − amazon/liga ≥ desconto/100`, em aritmética exata (sem arredondar): 25% conta."""
    if preco_amazon is None or preco_liga is None or preco_liga <= 0:
        return False
    return preco_amazon * CEM <= preco_liga * (CEM - desconto_min_pct)


def desconto_pct(preco_amazon: Decimal, preco_liga: Decimal) -> Decimal:
    return ((1 - preco_amazon / preco_liga) * CEM).quantize(Decimal("0.01"), ROUND_HALF_UP)


def vendedor_confiavel(vendedor: Vendedor | None, regras: Regras) -> bool:
    return (
        vendedor is not None
        and vendedor.pct_positivas is not None
        and vendedor.num_avaliacoes is not None
        and vendedor.pct_positivas >= regras.vendedor_min_positivas_pct
        and vendedor.num_avaliacoes >= regras.vendedor_min_avaliacoes
    )


def _vendedor_elegivel(leitura: Leitura, regras: Regras) -> bool:
    if leitura.envio is Envio.AMAZON:
        return True
    if leitura.envio is Envio.FBA:
        return vendedor_confiavel(leitura.vendedor, regras)
    return False


def _referencia_valida(ref: RefLiga, regras: Regras, agora: datetime) -> bool:
    return (
        ref.preco_a_partir is not None
        and ref.listagem_em is not None
        and agora - ref.listagem_em <= timedelta(hours=regras.liga_preco_max_idade_h)
    )


def elegivel(leitura: Leitura, ref: RefLiga, regras: Regras, agora: datetime) -> bool:
    return (
        _vendedor_elegivel(leitura, regras)
        and _referencia_valida(ref, regras, agora)
        and atinge_desconto(leitura.preco, ref.preco_a_partir, regras.desconto_min_pct)
    )


def decidir(
    leitura: Leitura, ref: RefLiga, regras: Regras, agora: datetime, preco_alertado: Decimal | None
) -> Acao:
    """`preco_alertado` é o da oportunidade aberta do anúncio (None se não há aberta)."""
    aberta = preco_alertado is not None
    if not elegivel(leitura, ref, regras, agora):
        return Acao.FECHAR if aberta else Acao.NADA
    if not aberta:
        return Acao.ABRIR
    if leitura.preco * CEM <= preco_alertado * (CEM - regras.realerta_queda_pct):
        return Acao.REALERTAR
    return Acao.ATUALIZAR
```

`src/tcg_sniper/oportunidades/mensagens.py`:

```python
from decimal import ROUND_DOWN, Decimal

from tcg_sniper.db.models import Envio
from tcg_sniper.formatacao import formatar_brl
from tcg_sniper.oportunidades.motor import Leitura, RefLiga, desconto_pct


def _pct(valor: Decimal) -> str:
    return f"{valor.normalize():f}".replace(".", ",")


def _quem_vende(leitura: Leitura) -> str:
    if leitura.envio is Envio.AMAZON:
        return "vendido pela Amazon"
    v = leitura.vendedor
    nome = (v.nome if v else None) or "lojista"
    if v and v.pct_positivas is not None and v.num_avaliacoes is not None:
        avaliacoes = f"{v.num_avaliacoes:,}".replace(",", ".")
        nome = f"{nome} ({_pct(v.pct_positivas)}% de {avaliacoes} avaliações)"
    return f"vendido por {nome}, enviado pela Amazon"


def mensagem_oportunidade(
    *, nome_produto: str, leitura: Leitura, ref: RefLiga, url_amazon: str, host: str, produto_id: int
) -> str:
    desconto = desconto_pct(leitura.preco, ref.preco_a_partir).quantize(Decimal("1"), ROUND_DOWN)
    liga = f"Liga: a partir de {formatar_brl(ref.preco_a_partir)}"
    if ref.num_lojas is not None:
        liga += f", {ref.num_lojas} lojas"
    if ref.preco_medio is not None:
        liga += f", média de venda {formatar_brl(ref.preco_medio)}"
    return "\n".join(
        [
            f"Oportunidade: {nome_produto}",
            f"Amazon: {formatar_brl(leitura.preco)} ({_quem_vende(leitura)}), {desconto}% abaixo da Liga",
            liga,
            url_amazon,
            f"Admin: http://{host}:8000/produto/{produto_id}",
        ]
    )
```

- [ ] **Step 4: Rodar**

Run: `uv run pytest -q && uv run ruff check`
Expected: tudo passa.

- [ ] **Step 5: Commit**

```bash
git add src/tcg_sniper/formatacao.py src/tcg_sniper/oportunidades src/tcg_sniper/admin/app.py tests/oportunidades
git commit -m "feat: opportunity engine and alert message"
```

---

### Task 9: Busca de um produto (gravação, confirmação, vendedor e motor)

`processar_produto` faz tudo o que uma entrada da fila exige: busca, grava, confirma os candidatos na página do produto (e o vendedor, se preciso), roda o motor e manda o alerta. Não conhece fila, ciclo nem janela (Task 10).

**Files:**
- Create: `src/tcg_sniper/coletor_amazon/busca.py`
- Modify: `tests/fakes.py` (`cartao_busca`, `html_busca`, `html_produto_amazon`, `html_vendedor`)
- Test: `tests/coletor_amazon/test_busca.py`

**Interfaces:**
- Consumes: Tasks 1 (`Navegador`, `ritmo`), 3 (`repositorio_amazon`), 5 (`termo_busca`), 6 (`eh_desafio_amazon`), 7 (parsers), 8 (`motor`, `mensagem_oportunidade`).
- Produces:
  - `DesafioAmazon(Exception)` com atributo `url: str`
  - `ContextoBusca(sessoes, navegador, notificador, config: Config, cfg: ConfigAmazon, relogio: Callable[[], datetime], dormir: Dormir, rng: random.Random, nome_falha: str)` (dataclass)
  - `url_busca(cfg: ConfigAmazon, nome: str) -> str`
  - `processar_produto(ctx: ContextoBusca, produto: ProdutoLiga) -> int` (quantos candidatos; lança `DesafioAmazon`, `ErroParser`, `ErroRede`)

- [ ] **Step 1: Fakes de HTML da Amazon**

Acrescente a `tests/fakes.py`. A estrutura é a mesma dos seletores de `coletor_amazon/parsers.py`; se a Task 7 trocou algum seletor, monte o HTML com o seletor novo.

```python
def cartao_busca(asin: str, titulo: str, preco: str | None, patrocinado: bool = False) -> str:
    """Cartão de resultado da busca da Amazon. `preco` no formato da página ("R$ 599,90") ou None."""
    preco_html = f'<span class="a-price"><span class="a-offscreen">{preco}</span></span>' if preco else ""
    marca = '<span class="puis-sponsored-label-text">Patrocinado</span>' if patrocinado else ""
    return (
        f'<div data-component-type="s-search-result" data-asin="{asin}">'
        f"<h2><span>{titulo}</span></h2>{marca}{preco_html}</div>"
    )


def html_busca(*cartoes: str) -> str:
    return f'<html><body><div class="s-main-slot">{"".join(cartoes)}</div></body></html>'


def html_produto_amazon(
    titulo: str, preco: str | None, vendido: str | None, enviado: str | None, seller_id: str | None = None
) -> str:
    partes = [f'<span id="productTitle">{titulo}</span>']
    if preco:
        partes.append(f'<div id="corePrice_feature_div"><span class="a-price"><span class="a-offscreen">{preco}</span></span></div>')
    if vendido:
        link = f'<a id="sellerProfileTriggerId" href="/gp/help/seller/at-a-glance.html?seller={seller_id}">{vendido}</a>' if seller_id else vendido
        partes.append(
            '<div offer-display-feature-name="desktop-merchant-info">'
            f'<span class="offer-display-feature-text-message">{link}</span></div>'
        )
    if enviado:
        partes.append(
            '<div offer-display-feature-name="desktop-fulfiller-info">'
            f'<span class="offer-display-feature-text-message">{enviado}</span></div>'
        )
    return f"<html><body>{''.join(partes)}</body></html>"


def html_vendedor(nome: str, pct: int, avaliacoes: str) -> str:
    return (
        f'<html><body><h1 id="seller-name">{nome}</h1><div id="seller-info-feedback-summary">'
        f"{pct}% positivas nos últimos 12 meses ({avaliacoes} avaliações)</div></body></html>"
    )
```

O `#sellerProfileTriggerId` dentro do texto de "Vendido por" faz o `.text()` do bloco continuar sendo o nome do vendedor.

- [ ] **Step 2: Escrever os testes**

`tests/coletor_amazon/test_busca.py`:

```python
import random
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fakes import (
    NavegadorFake,
    NotificadorFake,
    cartao_busca,
    criar_anuncio,
    criar_preco_liga,
    criar_produto,
    html_busca,
    html_produto_amazon,
    html_vendedor,
    pagina_html,
)
from sqlalchemy import func, select

from tcg_sniper.coletor_amazon.busca import ContextoBusca, DesafioAmazon, processar_produto, url_busca
from tcg_sniper.coletor_amazon.parsers import url_produto, url_vendedor
from tcg_sniper.db import repositorio_amazon as repo
from tcg_sniper.db.models import AnuncioAmazon, Oportunidade, StatusCasamento, VendedorAmazon
from tcg_sniper.notificador.base import Destino
from tcg_sniper.parsing import ErroParser

AGORA = datetime.fromisoformat("2026-10-15T15:00:00+00:00")
NOME = "Caixa de Booster - Final Fantasy - Booster de Jogo"
CAPTCHA = '<html><body><form action="/errors/validateCaptcha"></form></body></html>'


@pytest.fixture
def produto(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "ff", nome=NOME)
        criar_preco_liga(s, p, "1000.00", listagem_em=AGORA - timedelta(hours=2), num_lojas=12)
        return p


def contexto(sessoes, config, paginas, dormidas=None):
    with sessoes() as s:
        cfg = repo.obter_config(s)
    navegador = NavegadorFake(paginas)
    notificador = NotificadorFake()
    ctx = ContextoBusca(
        sessoes=sessoes,
        navegador=navegador,
        notificador=notificador,
        config=config,
        cfg=cfg,
        relogio=lambda: AGORA,
        dormir=(dormidas.append if dormidas is not None else lambda _: None),
        rng=random.Random(1),
        nome_falha="amazon-1-1",
    )
    return ctx, navegador, notificador


def busca(cfg_url, *cartoes):
    return pagina_html(html_busca(*cartoes), url=cfg_url)


def test_url_busca_codifica_o_termo(sessoes):
    with sessoes() as s:
        cfg = repo.obter_config(s)
    assert url_busca(cfg, "Caixa - A & B + C #1 Edição") == (
        "https://www.amazon.com.br/s?k=Caixa+A+%26+B+%2B+C+%231+Edi%C3%A7%C3%A3o"
    )


def test_asin_novo_fica_pendente_e_nao_abre_o_produto(sessoes, config, produto):
    with sessoes() as s:
        url = url_busca(repo.obter_config(s), NOME)
    ctx, navegador, notificador = contexto(sessoes, config, {url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 100,00"))})
    assert processar_produto(ctx, produto) == 0
    assert navegador.visitadas == [url]
    with sessoes() as s:
        anuncio = s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.asin == "B01"))
    assert (anuncio.status_casamento, anuncio.produto_id) == (StatusCasamento.PENDENTE, produto.id)
    assert notificador.mensagens == []


def test_confirmado_barato_vendido_pela_amazon_abre_oportunidade_e_alerta(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    paginas = {
        url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 700,00")),
        url_produto("B01"): pagina_html(html_produto_amazon("Caixa FF", "R$ 699,90", "Amazon.com.br", "Amazon.com.br")),
    }
    dormidas = []
    ctx, navegador, notificador = contexto(sessoes, config, paginas, dormidas)
    assert processar_produto(ctx, produto) == 1
    assert navegador.visitadas == [url, url_produto("B01")]
    assert len(dormidas) == 2  # uma pausa humana antes de cada página
    [(destino, texto)] = notificador.mensagens
    assert destino is Destino.OPORTUNIDADES
    assert texto.startswith(f"Oportunidade: {NOME}\nAmazon: R$ 699,90 (vendido pela Amazon), 30% abaixo da Liga")
    with sessoes() as s:
        op = s.scalar(select(Oportunidade))
    assert (op.preco_amazon, op.preco_liga, op.desconto_pct) == (Decimal("699.90"), Decimal("1000.00"), Decimal("30.01"))


def test_oportunidade_ja_alertada_no_mesmo_preco_nao_alerta_de_novo(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)

    def paginas():
        return {
            url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 700,00")),
            url_produto("B01"): pagina_html(html_produto_amazon("Caixa FF", "R$ 700,00", "Amazon.com.br", None)),
        }

    ctx, _, notificador = contexto(sessoes, config, paginas())
    processar_produto(ctx, produto)
    ctx2, _, notificador2 = contexto(sessoes, config, paginas())
    processar_produto(ctx2, produto)
    assert len(notificador.mensagens) == 1 and notificador2.mensagens == []


def test_confirmado_acima_do_limite_nao_abre_o_produto(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    ctx, navegador, _ = contexto(sessoes, config, {url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 750,01"))})
    assert processar_produto(ctx, produto) == 0
    assert navegador.visitadas == [url]


def test_asin_casado_com_outro_produto_compara_com_o_preco_dele(sessoes, config, produto):
    with sessoes() as s, s.begin():
        outro = criar_produto(s, "outro", nome="Outro produto")
        criar_preco_liga(s, outro, "100.00", listagem_em=AGORA)
        criar_anuncio(s, "B09", produto=outro, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    # R$ 700 é 30% abaixo do produto buscado (R$ 1.000), mas acima do produto casado (R$ 100).
    ctx, navegador, _ = contexto(sessoes, config, {url: busca(url, cartao_busca("B09", "Outro", "R$ 700,00"))})
    assert processar_produto(ctx, produto) == 0
    assert navegador.visitadas == [url]


def test_lojista_fba_desconhecido_abre_o_perfil_e_usa_o_cache_depois(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)

    def paginas():
        return {
            url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 700,00")),
            url_produto("B01"): pagina_html(html_produto_amazon("Caixa FF", "R$ 700,00", "Loja X", "Amazon", "A1")),
            url_vendedor("A1"): pagina_html(html_vendedor("Loja X", 97, "2.340")),
        }

    ctx, navegador, notificador = contexto(sessoes, config, paginas())
    processar_produto(ctx, produto)
    assert navegador.visitadas == [url, url_produto("B01"), url_vendedor("A1")]
    assert "vendido por Loja X (97% de 2.340 avaliações), enviado pela Amazon" in notificador.mensagens[0][1]

    ctx2, navegador2, _ = contexto(sessoes, config, paginas())
    processar_produto(ctx2, produto)
    assert url_vendedor("A1") not in navegador2.visitadas  # avaliado há menos de 7 dias
    with sessoes() as s:
        assert s.scalar(select(func.count()).select_from(VendedorAmazon).where(VendedorAmazon.seller_id == "A1")) == 1


def test_lojista_com_envio_proprio_nao_alerta_nem_abre_o_perfil(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    paginas = {
        url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 700,00")),
        url_produto("B01"): pagina_html(html_produto_amazon("Caixa FF", "R$ 700,00", "Loja X", "Loja X", "A1")),
    }
    ctx, navegador, notificador = contexto(sessoes, config, paginas)
    processar_produto(ctx, produto)
    assert navegador.visitadas == [url, url_produto("B01")]
    assert notificador.mensagens == []


@pytest.mark.parametrize("onde", ["busca", "produto"])
def test_captcha_levanta_desafio(sessoes, config, produto, onde):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    paginas = {
        url: pagina_html(CAPTCHA) if onde == "busca" else busca(url, cartao_busca("B01", "Caixa FF", "R$ 700,00")),
        url_produto("B01"): pagina_html(CAPTCHA),
    }
    ctx, _, _ = contexto(sessoes, config, paginas)
    with pytest.raises(DesafioAmazon) as erro:
        processar_produto(ctx, produto)
    assert erro.value.url == (url if onde == "busca" else url_produto("B01"))


def test_pagina_que_nao_le_salva_o_html_e_levanta(sessoes, config, produto):
    with sessoes() as s:
        url = url_busca(repo.obter_config(s), NOME)
    ctx, _, _ = contexto(sessoes, config, {url: pagina_html("<html><body>layout novo</body></html>")})
    with pytest.raises(ErroParser):
        processar_produto(ctx, produto)
    assert (config.dir_dados / "falhas" / "amazon-1-1-busca.html").exists()
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/coletor_amazon/test_busca.py -q`
Expected: FAIL (`ModuleNotFoundError: tcg_sniper.coletor_amazon.busca`).

- [ ] **Step 4: Implementar**

`src/tcg_sniper/coletor_amazon/busca.py`:

```python
"""Uma busca na Amazon para um produto da Liga: grava os resultados, confirma os candidatos na
página do produto (e o perfil do vendedor, se preciso), roda o motor e avisa o grupo de
oportunidades. Não conhece fila, ciclo nem janela (ver varredura.py)."""

import dataclasses
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import quote_plus

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon
from tcg_sniper.coletor_amazon.modelos import OfertaProduto
from tcg_sniper.coletor_amazon.parsers import parse_busca, parse_produto_amazon, parse_vendedor, url_vendedor
from tcg_sniper.coletor_amazon.termo import termo_busca
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio_amazon as repo
from tcg_sniper.db.models import ConfigAmazon, Envio, OrigemPreco, ProdutoLiga, VendedorAmazon
from tcg_sniper.navegador.base import Navegador
from tcg_sniper.navegador.modelos import Pagina
from tcg_sniper.navegador.ritmo import Dormir, com_um_retry, pausa_aleatoria, salvar_html_falha
from tcg_sniper.notificador.base import Destino, Notificador
from tcg_sniper.oportunidades import motor
from tcg_sniper.oportunidades.mensagens import mensagem_oportunidade
from tcg_sniper.parsing import ErroParser

log = logging.getLogger(__name__)


class DesafioAmazon(Exception):
    def __init__(self, url: str):
        super().__init__(url)
        self.url = url


@dataclass
class ContextoBusca:
    sessoes: sessionmaker[Session]
    navegador: Navegador
    notificador: Notificador
    config: Config
    cfg: ConfigAmazon
    relogio: Callable[[], datetime]
    dormir: Dormir
    rng: random.Random
    nome_falha: str  # prefixo do HTML salvo em <DIR_DADOS>/falhas quando um parser falha


def url_busca(cfg: ConfigAmazon, nome: str) -> str:
    return cfg.url_busca.replace("{termo}", quote_plus(termo_busca(nome)))


def _abrir(ctx: ContextoBusca, url: str) -> Pagina:
    """Pausa humana, abre (uma nova tentativa em erro de rede) e para no CAPTCHA."""
    pausa_aleatoria(ctx.cfg.pausa_min_s, ctx.cfg.pausa_max_s, ctx.dormir, ctx.rng)
    pagina = com_um_retry(lambda: ctx.navegador.abrir(url), url, ctx.dormir)
    if eh_desafio_amazon(pagina):
        raise DesafioAmazon(url)
    return pagina


def _ler[T](ctx: ContextoBusca, pagina: Pagina, sufixo: str, parser: Callable[[str], T]) -> T:
    try:
        return parser(pagina.html)
    except ErroParser:
        caminho = salvar_html_falha(ctx.config.dir_dados, f"{ctx.nome_falha}-{sufixo}", pagina.html)
        log.warning("parser da Amazon falhou em %s; HTML em %s", pagina.url, caminho)
        raise


def processar_produto(ctx: ContextoBusca, produto: ProdutoLiga) -> int:
    """Busca o produto e confirma os candidatos. Devolve quantos candidatos houve.
    Lança DesafioAmazon (CAPTCHA), ErroParser (layout) ou ErroRede (depois de uma nova tentativa)."""
    pagina = _abrir(ctx, url_busca(ctx.cfg, produto.nome))
    itens = _ler(ctx, pagina, "busca", lambda html: parse_busca(html, ctx.cfg.resultados_por_busca))
    with ctx.sessoes() as s, s.begin():
        anuncios = repo.gravar_busca(s, itens, produto.id, ctx.relogio(), ctx.config.zona)
        candidatos = [
            (linha.anuncio.id, linha.anuncio.asin, linha.anuncio.url)
            for linha in repo.confirmados_com_referencia(s, [a.id for a in anuncios])
            if motor.atinge_desconto(
                linha.atual.preco, linha.liga.preco_a_partir if linha.liga else None, ctx.cfg.desconto_min_pct
            )
        ]
    for anuncio_id, asin, url in candidatos:
        _confirmar(ctx, anuncio_id, asin, url)
    return len(candidatos)


def _vendedor(ctx: ContextoBusca, oferta: OfertaProduto) -> VendedorAmazon | None:
    """Vendedor da oferta. Só abre o perfil de lojista FBA sem avaliação recente."""
    with ctx.sessoes() as s, s.begin():
        if oferta.envio is Envio.AMAZON:
            return repo.vendedor_da_amazon(s)
        if oferta.seller_id is None:
            return None
        conhecido = repo.obter_vendedor(s, oferta.seller_id)
    recente = conhecido is not None and conhecido.avaliado_em is not None and (
        ctx.relogio() - conhecido.avaliado_em < timedelta(days=ctx.cfg.vendedor_reavaliar_dias)
    )
    if oferta.envio is not Envio.FBA or recente:
        return conhecido
    seller_id = oferta.seller_id
    pagina = _abrir(ctx, url_vendedor(seller_id))
    avaliacao = _ler(ctx, pagina, f"vendedor-{seller_id}", lambda html: parse_vendedor(html, seller_id))
    if avaliacao.nome is None:
        avaliacao = dataclasses.replace(avaliacao, nome=oferta.vendido_por)
    with ctx.sessoes() as s, s.begin():
        return repo.gravar_vendedor(s, avaliacao, ctx.relogio())


def _confirmar(ctx: ContextoBusca, anuncio_id: int, asin: str, url: str) -> None:
    pagina = _abrir(ctx, url)
    oferta = _ler(ctx, pagina, f"produto-{asin}", lambda html: parse_produto_amazon(html, asin))
    vendedor = _vendedor(ctx, oferta)
    agora = ctx.relogio()
    mensagem = None
    with ctx.sessoes() as s, s.begin():
        vendedor_id = vendedor.id if vendedor else None
        repo.registrar_preco(
            s, anuncio_id, oferta.preco, OrigemPreco.PRODUTO, vendedor_id, oferta.envio, agora, ctx.config.zona
        )
        linhas = repo.confirmados_com_referencia(s, [anuncio_id])
        if not linhas:  # o casamento foi desfeito no admin enquanto a página abria
            return
        linha = linhas[0]
        liga = linha.liga
        ref = motor.RefLiga(
            preco_a_partir=liga.preco_a_partir if liga else None,
            listagem_em=liga.listagem_em if liga else None,
            num_lojas=liga.num_lojas if liga else None,
            preco_medio=liga.preco_medio if liga else None,
        )
        leitura = motor.Leitura(
            oferta.preco,
            oferta.envio,
            motor.Vendedor(vendedor.nome, vendedor.pct_positivas, vendedor.num_avaliacoes) if vendedor else None,
        )
        aberta = repo.oportunidade_aberta(s, anuncio_id)
        acao = motor.decidir(
            leitura, ref, motor.Regras.de(ctx.cfg), agora, aberta.preco_alertado if aberta else None
        )
        if acao is motor.Acao.ABRIR:
            repo.abrir_oportunidade(
                s,
                anuncio_id=anuncio_id,
                produto_id=linha.produto.id,
                preco_amazon=oferta.preco,
                preco_liga=ref.preco_a_partir,
                desconto_pct=motor.desconto_pct(oferta.preco, ref.preco_a_partir),
                vendedor_id=vendedor_id,
                envio=oferta.envio,
                agora=agora,
            )
        elif acao in (motor.Acao.REALERTAR, motor.Acao.ATUALIZAR):
            repo.atualizar_oportunidade(
                s,
                aberta,
                preco_amazon=oferta.preco,
                preco_liga=ref.preco_a_partir,
                desconto_pct=motor.desconto_pct(oferta.preco, ref.preco_a_partir),
                vendedor_id=vendedor_id,
                envio=oferta.envio,
                alertou=acao is motor.Acao.REALERTAR,
                agora=agora,
            )
        elif acao is motor.Acao.FECHAR:
            repo.fechar_oportunidade(s, aberta, agora)
        if acao in (motor.Acao.ABRIR, motor.Acao.REALERTAR):
            mensagem = mensagem_oportunidade(
                nome_produto=linha.produto.nome,
                leitura=leitura,
                ref=ref,
                url_amazon=linha.anuncio.url,
                host=ctx.config.host_publico,
                produto_id=linha.produto.id,
            )
    if mensagem is not None:
        ctx.notificador.enviar(Destino.OPORTUNIDADES, mensagem)
```

- [ ] **Step 5: Rodar**

Run: `uv run pytest -q && uv run ruff check`
Expected: tudo passa. Em `test_confirmado_barato_vendido_pela_amazon_abre_oportunidade_e_alerta`, 699,90 sobre 1.000,00 dá 30,01% (`desconto_pct`) e "30%" na mensagem (arredondado para baixo).

- [ ] **Step 6: Commit**

```bash
git add src/tcg_sniper/coletor_amazon/busca.py tests/fakes.py tests/coletor_amazon/test_busca.py
git commit -m "feat: Amazon search per product with candidate confirmation and alerts"
```

---

### Task 10: Laço contínuo da Amazon (`VarreduraAmazon`)

Janela, estado, teto por hora, fila, ciclos, CAPTCHA e erros. Um `passo()` faz no máximo uma busca e devolve quantos segundos dormir; `rodar()` segura o advisory lock e repete.

**Files:**
- Create: `src/tcg_sniper/coletor_amazon/varredura.py`
- Test: `tests/coletor_amazon/test_varredura.py`

**Interfaces:**
- Consumes: Task 2 (`repositorio`: `obter_estado`, `pausar_por_desafio`, `pausar`, `marcar_interrompidas`, `iniciar_coleta`, `finalizar_coleta`, `status_final`; `lock_coleta` da Liga), Task 3, Task 4 (nada), Task 5 (`janela_do_dia`, `intervalo_busca`, `TetoPorHora`), Task 9 (`ContextoBusca`, `processar_produto`, `DesafioAmazon`).
- Produces: `ID_LOCK_AMAZON = 7_202_611`, `TIPOS_AMAZON = (TipoColeta.AMAZON,)`, `ESPERA_OCIOSA_S = 60`, `ESPERA_ERRO_S = 900`, `MAX_ERROS_SEGUIDOS = 3`, `mensagem_captcha(config, url) -> str`, `VarreduraAmazon(engine, sessoes, fabrica_navegador, notificador, config, relogio=None, rng=None, dormir=time.sleep)` com `inicializar()`, `passo() -> float`, `rodar()`, `fechar_navegador()`

- [ ] **Step 1: Escrever os testes**

`tests/coletor_amazon/test_varredura.py`:

```python
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fakes import (
    NavegadorFake,
    NotificadorFake,
    cartao_busca,
    criar_preco_liga,
    criar_produto,
    html_busca,
    pagina_html,
)
from sqlalchemy import select

from tcg_sniper.coletor_amazon.busca import url_busca
from tcg_sniper.coletor_amazon.config import aplicar_config
from tcg_sniper.coletor_amazon.varredura import ESPERA_ERRO_S, ESPERA_OCIOSA_S, VarreduraAmazon
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    AnuncioAmazon,
    Coleta,
    EstadoColetorTipo,
    FilaAmazon,
    StatusColeta,
    TipoColeta,
)
from tcg_sniper.notificador.base import Destino

SP = ZoneInfo("America/Sao_Paulo")
MEIO_DIA = datetime(2026, 10, 15, 12, 0, tzinfo=SP)
CAPTCHA = '<html><body><form action="/errors/validateCaptcha"></form></body></html>'


class Relogio:
    def __init__(self, agora):
        self.agora = agora

    def __call__(self):
        return self.agora


class FabricaFake:
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
    navegador = NavegadorFake(paginas)
    fabrica = FabricaFake(navegador)
    notificador = NotificadorFake()
    v = VarreduraAmazon(
        engine,
        sessoes,
        fabrica,
        notificador,
        config,
        relogio=relogio or Relogio(MEIO_DIA),
        rng=random.Random(1),
        dormir=lambda _: None,
    )
    return v, navegador, fabrica, notificador


def ciclos(sessoes):
    with sessoes() as s:
        return list(s.scalars(select(Coleta).where(Coleta.tipo == TipoColeta.AMAZON).order_by(Coleta.id)))


def vazia(url):
    return pagina_html(html_busca(), url=url)


def test_passo_busca_reagenda_e_fecha_o_ciclo(engine, sessoes, config):
    (a, b), urls = produtos(sessoes, "a", "b")
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()})
    assert v.passo() == 0
    assert v.passo() == 0
    assert sorted(navegador.visitadas) == sorted(urls.values())
    [ciclo] = ciclos(sessoes)
    assert (ciclo.status, ciclo.produtos_ok, ciclo.produtos_falha) == (StatusColeta.OK, 2, 0)
    with sessoes() as s:
        fila = s.get(FilaAmazon, a.id)
    assert fila.ultima_busca_em == MEIO_DIA
    assert fila.proxima_busca_em == MEIO_DIA + timedelta(minutes=60)
    assert v.passo() == ESPERA_OCIOSA_S  # nada vencido


def test_fora_da_janela_nao_busca_e_fecha_o_navegador(engine, sessoes, config):
    _, urls = produtos(sessoes, "a")
    noite = Relogio(datetime(2026, 10, 15, 23, 0, tzinfo=SP))
    v, navegador, fabrica, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()}, noite)
    assert v.passo() == ESPERA_OCIOSA_S
    assert navegador.visitadas == []


def test_pausado_nao_busca(engine, sessoes, config):
    _, urls = produtos(sessoes, "a")
    with sessoes() as s, s.begin():
        repo.pausar(s, "manual", MEIO_DIA, COLETOR_AMAZON)
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()})
    assert v.passo() == ESPERA_OCIOSA_S
    assert navegador.visitadas == []


def test_captcha_pausa_avisa_e_mantem_o_navegador(engine, sessoes, config):
    _, urls = produtos(sessoes, "a")
    [url] = urls.values()
    v, _, fabrica, notificador = varredura(engine, sessoes, config, {url: pagina_html(CAPTCHA, url=url)})
    assert v.passo() == ESPERA_OCIOSA_S
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.PAUSADO_DESAFIO
    [ciclo] = ciclos(sessoes)
    assert ciclo.status is StatusColeta.PAUSADA_DESAFIO
    [(destino, texto)] = notificador.mensagens
    assert destino is Destino.ADMIN and ":6081/vnc.html" in texto
    assert fabrica.fechados == 0


def test_retomar_continua_no_mesmo_navegador(engine, sessoes, config):
    _, urls = produtos(sessoes, "a")
    [url] = urls.values()
    v, navegador, fabrica, _ = varredura(engine, sessoes, config, {url: [pagina_html(CAPTCHA, url=url), vazia(url)]})
    v.passo()
    with sessoes() as s, s.begin():
        repo.retomar(s, MEIO_DIA, COLETOR_AMAZON)
    assert v.passo() == 0
    assert navegador.visitadas == [url, url]
    assert fabrica.abertos == 1


def test_falha_de_layout_conta_falha_e_ciclo_falho_avisa(engine, sessoes, config):
    _, urls = produtos(sessoes, "a")
    [url] = urls.values()
    v, _, _, notificador = varredura(engine, sessoes, config, {url: pagina_html("<html>novo</html>", url=url)})
    v.passo()
    [ciclo] = ciclos(sessoes)
    assert (ciclo.status, ciclo.produtos_falha) == (StatusColeta.FALHA, 1)
    assert any(d is Destino.ADMIN and "falhou" in t for d, t in notificador.mensagens)


def test_teto_por_hora(engine, sessoes, config):
    _, urls = produtos(sessoes, "a", "b")
    with sessoes() as s, s.begin():
        valores = {"max_buscas_hora": 1}
        aplicar_config(s, valores, MEIO_DIA)
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()})
    v.passo()
    assert v.passo() == ESPERA_OCIOSA_S
    assert len(navegador.visitadas) == 1


def test_mudanca_na_config_vale_no_passo_seguinte(engine, sessoes, config):
    (a, b), urls = produtos(sessoes, "a", "b")  # mesmo preço e mesmo vencimento: "a" (menor id) vai primeiro
    paginas = {
        urls[a.id]: pagina_html(html_busca(*(cartao_busca(f"A0000000{i}", "Item", "R$ 10,00") for i in range(3)))),
        urls[b.id]: pagina_html(html_busca(*(cartao_busca(f"B0000000{i}", "Item", "R$ 10,00") for i in range(3)))),
    }
    v, _, _, _ = varredura(engine, sessoes, config, paginas)
    v.passo()
    with sessoes() as s:
        assert len(s.scalars(select(AnuncioAmazon)).all()) == 3
    with sessoes() as s, s.begin():
        aplicar_config(s, {"resultados_por_busca": 1}, MEIO_DIA)
    v.passo()
    with sessoes() as s:
        assert len(s.scalars(select(AnuncioAmazon)).all()) == 4


def test_produto_desativado_no_meio_do_ciclo_sai_e_o_ciclo_fecha(engine, sessoes, config):
    (a, b), urls = produtos(sessoes, "a", "b")
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()})
    v.passo()
    buscado = navegador.visitadas[0]
    restante = b if buscado == urls[a.id] else a
    with sessoes() as s, s.begin():
        s.get(type(restante), restante.id).ativo = False
    assert v.passo() == ESPERA_OCIOSA_S
    assert len(navegador.visitadas) == 1
    [ciclo] = ciclos(sessoes)
    assert (ciclo.status, ciclo.produtos_ok) == (StatusColeta.OK, 1)


def test_erros_inesperados_seguidos_pausam(engine, sessoes, config, monkeypatch):
    from tcg_sniper.coletor_amazon import varredura as modulo

    def quebrar(*_a, **_k):
        raise RuntimeError("banco caiu")

    monkeypatch.setattr(modulo, "processar_produto", quebrar)
    _, urls = produtos(sessoes, "a")
    v, _, fabrica, notificador = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()})
    esperas = []
    for _ in range(3):
        try:
            v.passo()
        except RuntimeError as erro:
            esperas.append(v.tratar_erro(erro))
    assert esperas == [ESPERA_ERRO_S, ESPERA_ERRO_S, ESPERA_OCIOSA_S]
    with sessoes() as s:
        estado = repo.obter_estado(s, coletor=COLETOR_AMAZON)
    assert (estado.estado, estado.motivo) == (EstadoColetorTipo.PAUSADO, "erros seguidos")
    assert len(notificador.mensagens) == 3
    assert fabrica.fechados == 3


def test_inicializar_so_marca_os_ciclos_da_amazon(engine, sessoes, config):
    with sessoes() as s, s.begin():
        liga = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, MEIO_DIA)
        amazon = repo.iniciar_coleta(s, TipoColeta.AMAZON, MEIO_DIA)
    v, _, _, notificador = varredura(engine, sessoes, config, {})
    v.inicializar()
    with sessoes() as s:
        assert s.get(Coleta, liga.id).status is StatusColeta.RODANDO
        assert s.get(Coleta, amazon.id).status is StatusColeta.FALHA
    assert len(notificador.mensagens) == 1


@pytest.mark.parametrize("hora", [7, 22])
def test_janela_nas_bordas(engine, sessoes, config, hora):
    _, urls = produtos(sessoes, "a")
    relogio = Relogio(datetime(2026, 10, 15, hora, 0, tzinfo=SP) + timedelta(minutes=-20 if hora == 7 else 20))
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()}, relogio)
    assert v.passo() == ESPERA_OCIOSA_S
    assert navegador.visitadas == []
```

(`test_janela_nas_bordas` usa 06:40 e 22:20, que ficam fora da janela qualquer que seja a variação de até 15 minutos.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/coletor_amazon/test_varredura.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementar**

`src/tcg_sniper/coletor_amazon/varredura.py`:

```python
"""Fila contínua de buscas na Amazon, dentro da janela do dia, com teto por hora e ciclos."""

import logging
import random
import time as relogio_sistema
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, time

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.coletor_amazon.busca import ContextoBusca, DesafioAmazon, processar_produto
from tcg_sniper.coletor_amazon.fila import Janela, TetoPorHora, intervalo_busca, janela_do_dia
from tcg_sniper.coletor_liga.agendador import lock_coleta
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import COLETOR_AMAZON, ConfigAmazon, EstadoColetorTipo, ProdutoLiga, StatusColeta, TipoColeta
from tcg_sniper.navegador.base import Navegador
from tcg_sniper.navegador.modelos import ErroRede
from tcg_sniper.notificador.base import Destino, Notificador
from tcg_sniper.parsing import ErroParser

log = logging.getLogger(__name__)

ID_LOCK_AMAZON = 7_202_611
TIPOS_AMAZON = (TipoColeta.AMAZON,)
ESPERA_OCIOSA_S = 60
ESPERA_ERRO_S = 15 * 60
MAX_ERROS_SEGUIDOS = 3


def mensagem_captcha(config: Config, url: str) -> str:
    return (
        f"CAPTCHA na Amazon ({url}). Resolver em http://{config.host_publico}:6081/vnc.html "
        f"e depois clicar em Retomar (Amazon) em http://{config.host_publico}:8000"
    )


class VarreduraAmazon:
    def __init__(
        self,
        engine: Engine,
        sessoes: sessionmaker[Session],
        fabrica_navegador: Callable[[], AbstractContextManager[Navegador]],
        notificador: Notificador,
        config: Config,
        relogio: Callable[[], datetime] | None = None,
        rng: random.Random | None = None,
        dormir: Callable[[float], None] = relogio_sistema.sleep,
    ):
        self._engine = engine
        self._sessoes = sessoes
        self._fabrica_navegador = fabrica_navegador
        self._notificador = notificador
        self._config = config
        self._relogio = relogio or (lambda: datetime.now(UTC))
        self._rng = rng or random.Random()
        self._dormir = dormir
        self._janelas: dict[tuple[date, time, time], Janela] = {}
        self._teto = TetoPorHora()
        self._ciclo: int | None = None
        self._pendentes: set[int] = set()
        self._ok = 0
        self._falha = 0
        self._erros_seguidos = 0
        self._contexto_navegador: AbstractContextManager[Navegador] | None = None
        self._navegador: Navegador | None = None

    # --- navegador ---------------------------------------------------------------------------

    def _obter_navegador(self) -> Navegador:
        if self._navegador is not None:
            if self._navegador.vivo():
                return self._navegador
            log.warning("navegador da Amazon não responde; abrindo outro")
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
            log.warning("erro ao fechar o navegador da Amazon", exc_info=True)

    # --- ciclo -------------------------------------------------------------------------------

    def _iniciar_ciclo(self, agora: datetime, na_fila: set[int]) -> None:
        with self._sessoes() as s, s.begin():
            self._ciclo = repo.iniciar_coleta(s, TipoColeta.AMAZON, agora).id
        self._pendentes = set(na_fila)
        self._ok = self._falha = 0

    def _encerrar_ciclo(self, cfg: ConfigAmazon) -> None:
        if self._ciclo is None:
            return
        status = repo.status_final(self._ok, self._falha, cfg.limite_falha_pct)
        with self._sessoes() as s, s.begin():
            repo.finalizar_coleta(s, self._ciclo, status, self._ok, self._falha, self._relogio())
        log.info("ciclo %s da Amazon terminou: %s (%d ok, %d falhas)", self._ciclo, status.value, self._ok, self._falha)
        if status is StatusColeta.FALHA:
            self._notificador.enviar(
                Destino.ADMIN,
                f"Ciclo {self._ciclo} da Amazon falhou em {self._falha} de {self._ok + self._falha} buscas. "
                f"O layout da Amazon pode ter mudado. HTMLs em {self._config.dir_dados / 'falhas'}.",
            )
        self._ciclo = None
        self._pendentes = set()

    def _registrar_desafio(self, url: str) -> None:
        agora = self._relogio()
        with self._sessoes() as s, s.begin():
            if self._ciclo is not None:
                repo.finalizar_coleta(
                    s, self._ciclo, StatusColeta.PAUSADA_DESAFIO, self._ok, self._falha, agora, erro=f"desafio em {url}"
                )
            repo.pausar_por_desafio(s, f"desafio em {url}", agora, COLETOR_AMAZON)
        log.warning("CAPTCHA na Amazon em %s; varredura pausada", url)
        self._ciclo = None
        self._pendentes = set()
        self._notificador.enviar(Destino.ADMIN, mensagem_captcha(self._config, url))

    # --- laço --------------------------------------------------------------------------------

    def inicializar(self) -> None:
        with self._sessoes() as s, s.begin():
            interrompidos = repo.marcar_interrompidas(s, self._relogio(), TIPOS_AMAZON)
        if interrompidos:
            log.warning("%d ciclo(s) da Amazon interrompido(s) marcados como falha", interrompidos)
            self._notificador.enviar(
                Destino.ADMIN,
                f"{interrompidos} ciclo(s) da Amazon interrompido(s) (o coletor reiniciou) e marcado(s) como "
                "falha. A fila continua sozinha.",
            )

    def _janela(self, agora: datetime, cfg: ConfigAmazon) -> Janela:
        dia = agora.astimezone(self._config.zona).date()
        chave = (dia, cfg.janela_inicio, cfg.janela_fim)
        if chave not in self._janelas:
            self._janelas[chave] = janela_do_dia(dia, cfg.janela_inicio, cfg.janela_fim, self._config.zona, self._rng)
        return self._janelas[chave]

    def passo(self) -> float:
        """Faz no máximo uma busca. Devolve quantos segundos dormir antes do próximo passo."""
        agora = self._relogio()
        with self._sessoes() as s, s.begin():
            cfg = repo_amz.obter_config(s)
            estado = repo.obter_estado(s, agora, COLETOR_AMAZON).estado
        if not self._janela(agora, cfg).contem(agora):
            self._encerrar_ciclo(cfg)
            self.fechar_navegador()
            return ESPERA_OCIOSA_S
        if estado is not EstadoColetorTipo.ATIVO:
            return ESPERA_OCIOSA_S
        if self._teto.liberado_em(agora, cfg.max_buscas_hora) is not None:
            return ESPERA_OCIOSA_S

        with self._sessoes() as s, s.begin():
            repo_amz.sincronizar_fila(s, agora)
            na_fila = repo_amz.ids_na_fila(s)
            item = repo_amz.proximo_da_fila(s, agora)
            produto = s.get(ProdutoLiga, item.produto_id) if item else None
            entrou_em = item.entrou_em if item else None
            ultimo_candidato_em = item.ultimo_candidato_em if item else None
        self._pendentes &= na_fila  # produto desativado na Liga sai do ciclo
        if self._ciclo is not None and not self._pendentes:
            self._encerrar_ciclo(cfg)
        if produto is None:
            return ESPERA_OCIOSA_S
        if self._ciclo is None:
            self._iniciar_ciclo(agora, na_fila)

        contexto = ContextoBusca(
            sessoes=self._sessoes,
            navegador=self._obter_navegador(),
            notificador=self._notificador,
            config=self._config,
            cfg=cfg,
            relogio=self._relogio,
            dormir=self._dormir,
            rng=self._rng,
            nome_falha=f"amazon-{self._ciclo}-{produto.id}",
        )
        teve_candidato = False
        try:
            teve_candidato = processar_produto(contexto, produto) > 0
            self._ok += 1
        except DesafioAmazon as desafio:
            self._registrar_desafio(desafio.url)
            return ESPERA_OCIOSA_S
        except (ErroParser, ErroRede) as erro:
            self._falha += 1
            log.warning("busca do produto %s na Amazon falhou: %s", produto.id, erro)
        self._erros_seguidos = 0
        self._teto.registrar(agora)

        depois = self._relogio()
        candidato_em = depois if teve_candidato else ultimo_candidato_em
        proxima = depois + intervalo_busca(cfg.intervalo_busca_min, depois, candidato_em, entrou_em)
        with self._sessoes() as s, s.begin():
            repo_amz.reagendar(s, produto.id, depois, proxima, teve_candidato)
            repo_amz.fechar_oportunidades_sem_leitura(s, depois)
        self._pendentes.discard(produto.id)
        if not self._pendentes:
            self._encerrar_ciclo(cfg)
        return 0

    def tratar_erro(self, erro: Exception) -> float:
        """Erro inesperado num passo: avisa e espera; três seguidos pausam a varredura."""
        log.error("erro inesperado na varredura da Amazon", exc_info=erro)
        self.fechar_navegador()
        self._erros_seguidos += 1
        if self._erros_seguidos >= MAX_ERROS_SEGUIDOS:
            self._erros_seguidos = 0
            with self._sessoes() as s, s.begin():
                repo.pausar(s, "erros seguidos", self._relogio(), COLETOR_AMAZON)
            self._notificador.enviar(
                Destino.ADMIN,
                f"Varredura da Amazon pausada depois de {MAX_ERROS_SEGUIDOS} erros inesperados seguidos "
                f"(último: {erro!r}). Veja `docker compose logs coletor-amazon` e clique em Retomar (Amazon) "
                f"em http://{self._config.host_publico}:8000",
            )
            return ESPERA_OCIOSA_S
        self._notificador.enviar(
            Destino.ADMIN, f"Erro inesperado na varredura da Amazon: {erro!r}. Nova tentativa em 15 minutos."
        )
        return ESPERA_ERRO_S

    def rodar(self) -> None:
        try:
            with lock_coleta(self._engine, ID_LOCK_AMAZON) as obtido:
                if not obtido:
                    log.error("outro coletor-amazon já está rodando; saindo")
                    return
                self.inicializar()
                log.info("varredura da Amazon iniciada")
                while True:
                    try:
                        espera = self.passo()
                    except Exception as erro:
                        espera = self.tratar_erro(erro)
                    if espera > 0:
                        self._dormir(espera)
        finally:
            # SIGTERM vira SystemExit: fecha o navegador que tenha ficado aberto por um CAPTCHA.
            self.fechar_navegador()
```

- [ ] **Step 4: Rodar**

Run: `uv run pytest -q && uv run ruff check`
Expected: tudo passa. Em `test_passo_busca_reagenda_e_fecha_o_ciclo`, o produto entrou na fila no mesmo instante, nunca teve candidato e está há menos de 7 dias na fila, então o intervalo é a base (60 min).

- [ ] **Step 5: Commit**

```bash
git add src/tcg_sniper/coletor_amazon/varredura.py tests/coletor_amazon/test_varredura.py
git commit -m "feat: continuous Amazon search loop with window, hourly cap, cycles and pauses"
```

---

### Task 11: Comando `coletor-amazon`, Docker e documentação

**Files:**
- Modify: `src/tcg_sniper/cli.py`, `tests/test_cli.py`
- Modify: `docker/coletor-entrypoint.sh`, `docker-compose.yml`
- Modify: `README.md`, `.env.example`

**Interfaces:**
- Consumes: `VarreduraAmazon` (Task 10), `NavegadorChromium` (Task 1), `eh_desafio_amazon` (Task 6).
- Produces: subcomando `tcg-sniper coletor-amazon`; serviço `coletor-amazon` no compose (noVNC na porta 6081).

- [ ] **Step 1: Teste da CLI**

Acrescente a `tests/test_cli.py`:

```python
def test_coletor_amazon_instala_sigterm_e_usa_o_perfil_da_amazon(monkeypatch, tmp_path):
    from tcg_sniper.coletor_amazon import varredura

    anterior = signal.getsignal(signal.SIGTERM)
    vistos = []

    class VarreduraFalsa:
        def __init__(self, engine, sessoes, fabrica, notificador, config):
            vistos.append(fabrica()._dir_perfil)

        def rodar(self):
            vistos.append(signal.getsignal(signal.SIGTERM))

    monkeypatch.setattr(varredura, "VarreduraAmazon", VarreduraFalsa)
    monkeypatch.setattr(cli, "criar_engine", lambda url: object())
    monkeypatch.setattr(cli, "criar_sessoes", lambda engine: object())
    monkeypatch.setenv("DIR_DADOS", str(tmp_path))
    try:
        cli.main(["coletor-amazon"])
        assert vistos[0] == tmp_path / "perfil-amazon"
        assert vistos[1] not in (anterior, signal.SIG_DFL, signal.SIG_IGN)
    finally:
        signal.signal(signal.SIGTERM, anterior)
```

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL (`invalid choice: 'coletor-amazon'`).

- [ ] **Step 2: CLI**

Em `src/tcg_sniper/cli.py`, acrescente o subcomando depois do `coletor-liga`:

```python
    sub.add_parser("coletor-amazon", help="inicia a fila contínua de buscas na Amazon")
```

e o ramo, depois do de `coletor-liga`:

```python
    elif args.comando == "coletor-amazon":
        from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon
        from tcg_sniper.coletor_amazon.varredura import VarreduraAmazon
        from tcg_sniper.navegador.chromium import NavegadorChromium
        from tcg_sniper.notificador import criar_notificador

        instalar_sigterm()
        VarreduraAmazon(
            engine,
            sessoes,
            lambda: NavegadorChromium(config.dir_dados / "perfil-amazon", eh_desafio_amazon),
            criar_notificador(config),
            config,
        ).rodar()
```

Run: `uv run pytest tests/test_cli.py -q`
Expected: PASS.

- [ ] **Step 3: Docker**

Em `docker/coletor-entrypoint.sh`, troque `PERFIL="${DIR_DADOS:-/data}/perfil"` por:

```sh
# DIR_PERFIL separa o perfil de cada coletor (Liga: <DIR_DADOS>/perfil; Amazon: <DIR_DADOS>/perfil-amazon).
PERFIL="${DIR_PERFIL:-${DIR_DADOS:-/data}/perfil}"
```

Em `docker-compose.yml`, acrescente o serviço depois de `coletor-liga` (o `environment` repete os três valores do `x-app` porque o merge do YAML troca o mapa inteiro):

```yaml
  coletor-amazon:
    <<: *app
    entrypoint: ["/app/docker/coletor-entrypoint.sh"]
    command: ["tcg-sniper", "coletor-amazon"]
    environment:
      DATABASE_URL: postgresql+psycopg://tcg:tcg@postgres:5432/tcg
      DIR_DADOS: /data
      EVOLUTION_URL: http://evolution:8080
      DIR_PERFIL: /data/perfil-amazon
    # Mesmo arranjo do coletor-liga: tini, hostname fixo para o SingletonLock do perfil e o noVNC
    # da Amazon na porta 6081 do host (a 6080 é da Liga).
    init: true
    hostname: coletor-amazon
    stop_grace_period: 30s
    shm_size: 1gb
    ports:
      - "6081:6080"
    depends_on:
      migrate:
        condition: service_completed_successfully
```

Run: `docker compose config -q && echo ok`
Expected: `ok`.

- [ ] **Step 4: Documentação**

`.env.example`: troque o comentário e a linha de `WHATSAPP_GRUPO_OPORTUNIDADES` por:

```
# ID do grupo de oportunidades (120363...@g.us), que recebe as ofertas da Amazon com desconto
# sobre a Liga. Vazio: os alertas de oportunidade vão só para o log.
WHATSAPP_GRUPO_OPORTUNIDADES=
```

e, no cabeçalho do arquivo, acrescente `WHATSAPP_GRUPO_OPORTUNIDADES` à lista do "depois de conectar o WhatsApp".

`README.md`:

1. No parágrafo do topo e em "Estado", diga que o sub-projeto 2 (Amazon, casamento e oportunidades) está pronto.
2. Em "Como funciona", acrescente ao diagrama `coletor-amazon` (com `-- uma busca por vez --> amazon.com.br` e `--> db` e `--> evo`) e `noVNC :6081`, e um parágrafo: "**Amazon.** De 08:00 às 22:00 o `coletor-amazon` procura cada produto ativo na amazon.com.br, um por vez, com pausa humana. Anúncios novos vão para a fila de revisão em **Casamentos**; só anúncios confirmados geram oportunidade. Quando uma oferta vendida pela Amazon (ou por lojista confiável com envio pela Amazon) fica pelo menos 25% abaixo do "À partir de" da Liga, o grupo de oportunidades recebe um aviso. Tudo isso se ajusta em **Configurações** no admin."
3. Em "Uso responsável", acrescente: "Na Amazon, a fila tem teto de buscas por hora (200 por padrão) e só roda de 08:00 às 22:00; CAPTCHA pausa a fila até uma pessoa resolver."
4. Na instalação, um passo novo depois do 7, "**8. Ligue a Amazon**":
   - grave o ID do grupo de oportunidades em `WHATSAPP_GRUPO_OPORTUNIDADES` (mesmo jeito do passo 5);
   - `docker compose up -d --build coletor-amazon`;
   - abra `http://<HOST_PUBLICO>:6081/vnc.html`, clique no endereço de entrega da Amazon e informe o CEP de onde as compras serão entregues (o preço e o "Enviado por" dependem dele; fica salvo no perfil);
   - "Deu certo se" `docker compose logs coletor-amazon --tail 20` mostrar `varredura da Amazon iniciada` e, na janela, aparecerem buscas a cada 8 a 20 s.
5. Em "Uso no dia a dia": linhas novas na tabela de telas (**Casamentos**, **Ofertas**, **Configurações**) e na de mensagens (**Oportunidade:** no grupo de oportunidades; **CAPTCHA na Amazon** e **Varredura da Amazon pausada** no grupo admin, com o que fazer: resolver pelo noVNC na 6081 e clicar em **Retomar (Amazon)**, ou ver os logs).
6. Em "Roadmap", marque o item 2 como em andamento com a Amazon pronta e mantenha Mercado Livre e outros como próximos; os itens 3 a 5 viram: "Cupons, cashback, frete e comissão no cálculo" e "Migração para servidor".

- [ ] **Step 5: Rodar e commitar**

Run: `uv run pytest -q && uv run ruff check`
Expected: tudo passa.

```bash
git add src/tcg_sniper/cli.py tests/test_cli.py docker/coletor-entrypoint.sh docker-compose.yml README.md .env.example
git commit -m "feat: coletor-amazon command, compose service with its own noVNC, and docs"
```

---

### Task 12: Admin: estado da Amazon, pausar/retomar e configurações

**Files:**
- Create: `src/tcg_sniper/admin/consultas_amazon.py`, `src/tcg_sniper/admin/templates/configuracoes.html`
- Modify: `src/tcg_sniper/admin/app.py`, `src/tcg_sniper/admin/templates/index.html`, `src/tcg_sniper/admin/templates/base.html`
- Modify: `src/tcg_sniper/coletor_amazon/config.py` (`ROTULOS`)
- Test: `tests/admin/test_admin_amazon.py`, `tests/coletor_amazon/test_config_amazon.py`

**Interfaces:**
- Consumes: Tasks 2 a 4.
- Produces:
  - `tcg_sniper.coletor_amazon.config.ROTULOS: dict[str, str]`
  - `tcg_sniper.admin.consultas_amazon.ciclo_atual(s) -> Coleta | None`
  - rotas `POST /amazon/pausar`, `POST /amazon/retomar`, `GET /configuracoes`, `POST /configuracoes`

- [ ] **Step 1: Escrever os testes**

Acrescente a `tests/coletor_amazon/test_config_amazon.py`:

```python
def test_todo_campo_tem_rotulo():
    from tcg_sniper.coletor_amazon.config import ROTULOS

    assert set(ROTULOS) == set(CAMPOS)
```

`tests/admin/test_admin_amazon.py`:

```python
import base64

import pytest
from fakes import T0
from fastapi.testclient import TestClient

from tcg_sniper.admin.app import criar_app
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import COLETOR_AMAZON, EstadoColetorTipo, TipoColeta


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def test_index_mostra_a_amazon_ativa_com_ciclo(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.iniciar_coleta(s, TipoColeta.AMAZON, T0)
    texto = cliente.get("/").text
    assert "Amazon" in texto and "Pausar (Amazon)" in texto and "Ciclo em andamento" in texto


def test_pausar_e_retomar_a_amazon(cliente, sessoes):
    assert cliente.post("/amazon/pausar", follow_redirects=False).status_code == 303
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.PAUSADO
        assert repo.obter_estado(s).estado is EstadoColetorTipo.ATIVO  # a Liga não muda
    assert "Retomar (Amazon)" in cliente.get("/").text
    cliente.post("/amazon/retomar")
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.ATIVO


def test_index_mostra_o_captcha_da_amazon_com_o_link_do_novnc(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em https://www.amazon.com.br/s?k=x", T0, COLETOR_AMAZON)
    texto = cliente.get("/").text
    assert ":6081/vnc.html" in texto and "Retomar (Amazon)" in texto


def test_configuracoes_mostra_os_valores_atuais(cliente):
    texto = cliente.get("/configuracoes").text
    assert 'name="desconto_min_pct" value="25"' in texto
    assert 'name="janela_inicio" value="08:00"' in texto


def formulario_padrao(**mudancas):
    campos = {
        "url_busca": "https://www.amazon.com.br/s?k={termo}",
        "janela_inicio": "08:00",
        "janela_fim": "22:00",
        "pausa_min_s": "8",
        "pausa_max_s": "20",
        "resultados_por_busca": "10",
        "intervalo_busca_min": "60",
        "max_buscas_hora": "200",
        "limite_falha_pct": "50",
        "desconto_min_pct": "25",
        "realerta_queda_pct": "5",
        "liga_preco_max_idade_h": "48",
        "vendedor_min_positivas_pct": "90",
        "vendedor_min_avaliacoes": "100",
        "vendedor_reavaliar_dias": "7",
    }
    campos.update({k: str(v) for k, v in mudancas.items()})
    return campos


def test_configuracoes_grava_valores_validos(cliente, sessoes):
    r = cliente.post("/configuracoes", data=formulario_padrao(desconto_min_pct=30), follow_redirects=False)
    assert r.status_code == 303
    with sessoes() as s:
        assert repo_amz.obter_config(s).desconto_min_pct == 30
    assert "Configurações salvas" in cliente.get(r.headers["location"]).text


def test_configuracoes_recusa_valor_invalido_e_nao_grava_nada(cliente, sessoes):
    r = cliente.post("/configuracoes", data=formulario_padrao(desconto_min_pct=0, max_buscas_hora=150))
    assert r.status_code == 400
    assert "entre 1 e 90" in r.text
    assert 'name="max_buscas_hora" value="150"' in r.text  # o formulário volta com o que foi digitado
    with sessoes() as s:
        config = repo_amz.obter_config(s)
    assert (config.desconto_min_pct, config.max_buscas_hora) == (25, 200)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/admin/test_admin_amazon.py tests/coletor_amazon/test_config_amazon.py -q`
Expected: FAIL (rotas inexistentes, 404; `ROTULOS` inexistente).

- [ ] **Step 3: Implementar**

Em `src/tcg_sniper/coletor_amazon/config.py`, acrescente depois de `CAMPOS`:

```python
ROTULOS = {
    "url_busca": "URL da busca",
    "janela_inicio": "Início da janela",
    "janela_fim": "Fim da janela",
    "pausa_min_s": "Pausa mínima (s)",
    "pausa_max_s": "Pausa máxima (s)",
    "resultados_por_busca": "Resultados por busca",
    "intervalo_busca_min": "Intervalo entre buscas do mesmo produto (min)",
    "max_buscas_hora": "Máximo de buscas por hora",
    "limite_falha_pct": "Limite de falhas por ciclo (%)",
    "desconto_min_pct": "Desconto mínimo sobre a Liga (%)",
    "realerta_queda_pct": "Queda para novo aviso (%)",
    "liga_preco_max_idade_h": "Idade máxima do preço da Liga (h)",
    "vendedor_min_positivas_pct": "Lojista FBA: mínimo de positivas (%)",
    "vendedor_min_avaliacoes": "Lojista FBA: mínimo de avaliações",
    "vendedor_reavaliar_dias": "Reavaliar lojista a cada (dias)",
}
```

`src/tcg_sniper/admin/consultas_amazon.py`:

```python
"""Consultas das telas da Amazon no admin."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from tcg_sniper.db.models import Coleta, StatusColeta, TipoColeta


def ciclo_atual(s: Session) -> Coleta | None:
    return s.scalar(
        select(Coleta)
        .where(Coleta.tipo == TipoColeta.AMAZON, Coleta.status == StatusColeta.RODANDO)
        .order_by(Coleta.id.desc())
        .limit(1)
    )
```

Em `src/tcg_sniper/admin/app.py`:

1. Imports: `from datetime import time`; `from tcg_sniper.admin import consultas_amazon`; `from tcg_sniper.coletor_amazon.config import CAMPOS, EXPLICACOES, ROTULOS, aplicar_config, validar_config`; `from tcg_sniper.db import repositorio_amazon as repo_amz`; `from tcg_sniper.db.models import COLETOR_AMAZON`.
2. Uma função de módulo para ler o corpo urlencoded (a rota `/catalogo/lote` já faz isso à mão, sem `python-multipart`); troque o trecho equivalente dentro de `alterar_lote` por uma chamada a ela:

```python
async def ler_formulario(request: Request) -> dict[str, str]:
    """Corpo urlencoded lido à mão: evita a dependência python-multipart só para os formulários."""
    campos = parse_qs((await request.body()).decode("utf-8", "replace"), keep_blank_values=True)
    return {nome: valores[0] for nome, valores in campos.items()}
```

(em `alterar_lote`, `campo(nome, padrao)` vira `formulario.get(nome, padrao)`, com `formulario = await ler_formulario(request)`).

3. No `index`, acrescente ao contexto `"estado_amazon": repo.obter_estado(s, coletor=COLETOR_AMAZON)` e `"ciclo_amazon": consultas_amazon.ciclo_atual(s)`.
4. Rotas novas (dentro de `criar_app`):

```python
    @app.post("/amazon/pausar")
    def pausar_amazon():
        with sessoes() as s, s.begin():
            repo.pausar(s, "pausado no admin", repo.agora_utc(), COLETOR_AMAZON)
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/amazon/retomar")
    def retomar_amazon():
        with sessoes() as s, s.begin():
            repo.retomar(s, repo.agora_utc(), COLETOR_AMAZON)
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    def _tela_configuracoes(request: Request, valores: dict[str, str], erros: dict[str, str], salvo: bool, codigo: int):
        return templates.TemplateResponse(
            request,
            "configuracoes.html",
            {
                "campos": CAMPOS,
                "rotulos": ROTULOS,
                "explicacoes": EXPLICACOES,
                "valores": valores,
                "erros": erros,
                "salvo": salvo,
            },
            status_code=codigo,
        )

    @app.get("/configuracoes", response_class=HTMLResponse)
    def configuracoes(request: Request, msg: str = ""):
        with sessoes() as s, s.begin():
            config = repo_amz.obter_config(s)
            valores = {
                campo: getattr(config, campo).strftime("%H:%M")
                if isinstance(getattr(config, campo), time)
                else str(getattr(config, campo))
                for campo in CAMPOS
            }
        return _tela_configuracoes(request, valores, {}, msg == "salvo", status.HTTP_200_OK)

    @app.post("/configuracoes", response_class=HTMLResponse)
    async def salvar_configuracoes(request: Request):
        formulario = await ler_formulario(request)
        valores, erros = validar_config(formulario)
        if erros:
            digitados = {campo: formulario.get(campo, "") for campo in CAMPOS}
            return _tela_configuracoes(request, digitados, erros, False, status.HTTP_400_BAD_REQUEST)
        with sessoes() as s, s.begin():
            aplicar_config(s, valores, repo.agora_utc())
        return RedirectResponse("/configuracoes?msg=salvo", status_code=status.HTTP_303_SEE_OTHER)
```

`src/tcg_sniper/admin/templates/configuracoes.html`:

```html
{% extends "base.html" %}
{% block titulo %}Configurações · TCG Sniper{% endblock %}
{% block conteudo %}
<h2>Configurações da Amazon</h2>
<p>Valem a partir da próxima busca, sem reiniciar o coletor.</p>
{% if salvo %}<p><mark>Configurações salvas.</mark></p>{% endif %}
{% if erros %}<div class="pausado">Nada foi salvo. Corrija os campos marcados.</div>{% endif %}
<form method="post" action="/configuracoes">
  {% for campo in campos %}
  <label>{{ rotulos[campo] }}
    <input name="{{ campo }}" value="{{ valores[campo] }}"{% if campo in erros %} aria-invalid="true"{% endif %}>
    <small>{{ erros[campo] if campo in erros else explicacoes[campo] }}</small>
  </label>
  {% endfor %}
  <button>Salvar</button>
</form>
{% endblock %}
```

Em `src/tcg_sniper/admin/templates/base.html`, troque o segundo `<ul>` do `nav` por:

```html
    <ul>
      <li><a href="/">Status</a></li><li><a href="/catalogo">Catálogo</a></li>
      <li><a href="/casamentos">Casamentos</a></li><li><a href="/ofertas">Ofertas</a></li>
      <li><a href="/configuracoes">Configurações</a></li>
    </ul>
```

(as páginas Casamentos e Ofertas chegam nas Tasks 13 e 14; até lá os links dão 404).

Em `src/tcg_sniper/admin/templates/index.html`, troque `<h2>Coletor</h2>` por `<h2>LigaMagic</h2>` e acrescente, antes de `<h2>Últimas coletas</h2>`:

```html
<h2>Amazon</h2>
{% if estado_amazon.estado.value == "pausado_desafio" %}
<div class="pausado">
  <strong>Busca na Amazon pausada: CAPTCHA pendente.</strong> {{ estado_amazon.motivo or "" }}<br>
  Resolva em <a href="http://{{ host }}:6081/vnc.html">http://{{ host }}:6081/vnc.html</a> e clique em retomar.
  <form method="post" action="/amazon/retomar"><button>Retomar (Amazon)</button></form>
</div>
{% elif estado_amazon.estado.value == "pausado" %}
<div class="pausado">
  <strong>Busca na Amazon pausada.</strong> {{ estado_amazon.motivo or "" }}
  <form method="post" action="/amazon/retomar"><button>Retomar (Amazon)</button></form>
</div>
{% else %}
<p>Ativo (busca só dentro da janela definida em <a href="/configuracoes">Configurações</a>).
{% if ciclo_amazon %}<strong>Ciclo em andamento</strong> desde {{ ciclo_amazon.iniciada_em|data }}.{% endif %}</p>
<form method="post" action="/amazon/pausar"><button class="secondary">Pausar (Amazon)</button></form>
{% endif %}
```

- [ ] **Step 4: Rodar**

Run: `uv run pytest -q && uv run ruff check`
Expected: tudo passa (inclusive os testes antigos do admin, que procuram "Rodar agora" e as coletas na tabela).

- [ ] **Step 5: Commit**

```bash
git add src/tcg_sniper/admin src/tcg_sniper/coletor_amazon/config.py tests/admin/test_admin_amazon.py tests/coletor_amazon/test_config_amazon.py
git commit -m "feat: admin shows the Amazon collector, pauses and resumes it, and edits its settings"
```

---

### Task 13: Admin: fila de revisão de casamentos

**Files:**
- Modify: `src/tcg_sniper/admin/consultas_amazon.py`, `src/tcg_sniper/admin/app.py`
- Create: `src/tcg_sniper/admin/templates/casamentos.html`, `src/tcg_sniper/admin/templates/trocar.html`
- Test: `tests/admin/test_admin_amazon.py`

**Interfaces:**
- Consumes: `repositorio_amazon.confirmar_casamento`, `ignorar_anuncio`, `desfazer_casamento` (Task 3); `motor.atinge_desconto` (Task 8); `termo_busca` (Task 5); `consultas._escapar_like` (sub-projeto 1).
- Produces (em `consultas_amazon`):
  - `LinhaCasamento(anuncio: AnuncioAmazon, preco: Decimal | None, sugestao: ProdutoLiga | None, preco_sugestao: Decimal | None, alternativas: list[ProdutoLiga], candidato: bool)`
  - `pendentes(s, desconto_min_pct: int, limite: int = 20) -> tuple[list[LinhaCasamento], int]` (linhas e total de pendentes)
  - `revisados(s, limite: int = 100) -> list[tuple[AnuncioAmazon, ProdutoLiga | None]]`
  - `buscar_produtos(s, busca: str, limite: int = 20) -> list[ProdutoLiga]`
- rotas `GET /casamentos?aba=pendentes|revisados`, `POST /casamentos/{anuncio_id}` (campos `acao` = `confirmar`/`ignorar`/`desfazer`, `produto_id`, `aba`), `GET /casamentos/{anuncio_id}/trocar?busca=`

- [ ] **Step 1: Escrever os testes**

Acrescente a `tests/admin/test_admin_amazon.py` (imports: `from decimal import Decimal`, `from datetime import timedelta`, `from fakes import criar_anuncio, criar_preco_liga, criar_produto`, `from tcg_sniper.admin import consultas_amazon`, `from tcg_sniper.db.models import AnuncioAmazon, Envio, OrigemPreco, StatusCasamento`, `from zoneinfo import ZoneInfo`):

```python
SP = ZoneInfo("America/Sao_Paulo")


def anuncio_com_preco(s, asin, produto, preco, status=StatusCasamento.PENDENTE, agora=T0, titulo=None):
    anuncio = criar_anuncio(s, asin, produto=produto, status=status, agora=agora)
    if titulo:
        anuncio.titulo = titulo
    repo_amz.registrar_preco(s, anuncio.id, Decimal(preco), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, agora, SP)
    return anuncio


def test_pendentes_com_oportunidade_aparecem_primeiro_e_com_alternativas(s):
    ff = criar_produto(s, "ff", nome="Caixa de Booster - Final Fantasy - Booster de Jogo")
    criar_produto(s, "ff2", nome="Caixa de Booster - Final Fantasy - Collector Booster")
    criar_preco_liga(s, ff, "1000.00")
    anuncio_com_preco(s, "B01", ff, "900.00", agora=T0 + timedelta(hours=1))  # mais recente, mas sem desconto
    barato = anuncio_com_preco(
        s, "B02", ff, "700.00", titulo="Magic Final Fantasy Collector Booster Box", agora=T0
    )
    linhas, total = consultas_amazon.pendentes(s, desconto_min_pct=25)
    assert total == 2
    assert [linha.anuncio.asin for linha in linhas] == ["B02", "B01"]
    assert linhas[0].candidato and not linhas[1].candidato
    assert linhas[0].sugestao.id == ff.id and linhas[0].preco_sugestao == Decimal("1000.00")
    assert "Caixa de Booster - Final Fantasy - Collector Booster" in [p.nome for p in linhas[0].alternativas]
    assert all(p.id != ff.id for p in linhas[0].alternativas)
    assert barato.id == linhas[0].anuncio.id


def test_tela_de_casamentos_e_acoes(cliente, sessoes):
    with sessoes() as s, s.begin():
        ff = criar_produto(s, "ff", nome="Caixa FF")
        outro = criar_produto(s, "outro", nome="Caixa Outra")
        a1 = anuncio_com_preco(s, "B01", ff, "700.00")
        a2 = anuncio_com_preco(s, "B02", ff, "700.00")
        a3 = anuncio_com_preco(s, "B03", ff, "700.00")
    texto = cliente.get("/casamentos").text
    assert "B01" in texto and "Caixa FF" in texto and "3 pendentes" in texto

    r = cliente.post(f"/casamentos/{a1.id}", data={"acao": "confirmar", "produto_id": str(ff.id)}, follow_redirects=False)
    assert r.status_code == 303
    cliente.post(f"/casamentos/{a2.id}", data={"acao": "ignorar"})
    cliente.post(f"/casamentos/{a3.id}", data={"acao": "confirmar", "produto_id": str(outro.id)})
    with sessoes() as s:
        estados = {a.asin: (a.status_casamento, a.produto_id) for a in s.scalars(select(AnuncioAmazon))}
    assert estados == {
        "B01": (StatusCasamento.CONFIRMADO, ff.id),
        "B02": (StatusCasamento.IGNORADO, ff.id),
        "B03": (StatusCasamento.CONFIRMADO, outro.id),
    }
    revisados = cliente.get("/casamentos?aba=revisados").text
    assert "Desfazer" in revisados and "Caixa Outra" in revisados

    cliente.post(f"/casamentos/{a1.id}", data={"acao": "desfazer", "aba": "revisados"})
    with sessoes() as s:
        assert s.get(AnuncioAmazon, a1.id).status_casamento is StatusCasamento.PENDENTE


def test_trocar_busca_produtos_do_catalogo(cliente, sessoes):
    with sessoes() as s, s.begin():
        ff = criar_produto(s, "ff", nome="Caixa FF")
        criar_produto(s, "x", nome="Bundle 100% Final")
        anuncio = anuncio_com_preco(s, "B01", ff, "700.00")
    texto = cliente.get(f"/casamentos/{anuncio.id}/trocar", params={"busca": "100%"}).text
    assert "Bundle 100% Final" in texto and "Caixa FF" not in texto.split("<table>")[-1]


@pytest.mark.parametrize(
    ("dados", "codigo"),
    [
        ({"acao": "apagar"}, 400),
        ({"acao": "confirmar"}, 400),  # sem produto_id
        ({"acao": "confirmar", "produto_id": "999999"}, 404),
    ],
)
def test_acoes_invalidas(cliente, sessoes, dados, codigo):
    with sessoes() as s, s.begin():
        anuncio = anuncio_com_preco(s, "B01", criar_produto(s, "ff"), "700.00")
    assert cliente.post(f"/casamentos/{anuncio.id}", data=dados).status_code == codigo


def test_anuncio_inexistente_404(cliente):
    assert cliente.post("/casamentos/999999", data={"acao": "ignorar"}).status_code == 404
```

(acrescente também `from sqlalchemy import select` aos imports do arquivo.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/admin/test_admin_amazon.py -q`
Expected: FAIL (`AttributeError: module 'consultas_amazon' has no attribute 'pendentes'`, rotas 404).

- [ ] **Step 3: Consultas**

Acrescente a `src/tcg_sniper/admin/consultas_amazon.py` (imports: `import difflib`, `from dataclasses import dataclass`, `from decimal import Decimal`; `from tcg_sniper.admin.consultas import _escapar_like`; `from tcg_sniper.coletor_amazon.termo import termo_busca`; `from tcg_sniper.oportunidades.motor import atinge_desconto`; modelos `AnuncioAmazon`, `PrecoAtualAmazon`, `PrecoAtualLiga`, `ProdutoLiga`, `StatusCasamento`):

```python
@dataclass(frozen=True)
class LinhaCasamento:
    anuncio: AnuncioAmazon
    preco: Decimal | None
    sugestao: ProdutoLiga | None
    preco_sugestao: Decimal | None
    alternativas: list[ProdutoLiga]
    candidato: bool  # o preço já está a pelo menos o desconto mínimo abaixo da sugestão


def _normalizar(texto: str) -> str:
    return termo_busca(texto).lower()


def pendentes(s: Session, desconto_min_pct: int, limite: int = 20) -> tuple[list[LinhaCasamento], int]:
    """Pendentes que seriam oportunidade primeiro; depois os demais, mais recentes primeiro.
    Cada linha traz até 3 outros produtos do catálogo com título parecido (difflib)."""
    consulta = (
        select(AnuncioAmazon, PrecoAtualAmazon.preco, ProdutoLiga, PrecoAtualLiga.preco_a_partir)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == AnuncioAmazon.produto_id)
        .where(AnuncioAmazon.status_casamento == StatusCasamento.PENDENTE)
    )
    linhas = [
        (anuncio, preco, sugestao, preco_liga, atinge_desconto(preco, preco_liga, desconto_min_pct))
        for anuncio, preco, sugestao, preco_liga in s.execute(consulta)
    ]
    linhas.sort(key=lambda linha: (not linha[4], -linha[0].visto_primeiro_em.timestamp(), linha[0].id))
    total = len(linhas)
    catalogo = list(s.scalars(select(ProdutoLiga).order_by(ProdutoLiga.id)))
    por_nome: dict[str, ProdutoLiga] = {}
    for produto in catalogo:
        por_nome.setdefault(_normalizar(produto.nome), produto)
    resultado = []
    for anuncio, preco, sugestao, preco_liga, candidato in linhas[:limite]:
        parecidos = difflib.get_close_matches(_normalizar(anuncio.titulo), list(por_nome), n=4, cutoff=0.3)
        alternativas = [por_nome[nome] for nome in parecidos if sugestao is None or por_nome[nome].id != sugestao.id]
        resultado.append(LinhaCasamento(anuncio, preco, sugestao, preco_liga, alternativas[:3], candidato))
    return resultado, total


def revisados(s: Session, limite: int = 100) -> list[tuple[AnuncioAmazon, ProdutoLiga | None]]:
    consulta = (
        select(AnuncioAmazon, ProdutoLiga)
        .outerjoin(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .where(AnuncioAmazon.status_casamento != StatusCasamento.PENDENTE)
        .order_by(AnuncioAmazon.revisado_em.desc().nulls_last(), AnuncioAmazon.id.desc())
        .limit(limite)
    )
    return [(anuncio, produto) for anuncio, produto in s.execute(consulta)]


def buscar_produtos(s: Session, busca: str, limite: int = 20) -> list[ProdutoLiga]:
    consulta = select(ProdutoLiga).order_by(ProdutoLiga.nome).limit(limite)
    if busca.strip():
        consulta = consulta.where(ProdutoLiga.nome.ilike(f"%{_escapar_like(busca.strip())}%", escape="\\"))
    return list(s.scalars(consulta))
```

- [ ] **Step 4: Rotas**

Em `src/tcg_sniper/admin/app.py` (imports: `from tcg_sniper.db.models import AnuncioAmazon, ProdutoLiga`):

```python
    ABAS_CASAMENTO = ("pendentes", "revisados")

    @app.get("/casamentos", response_class=HTMLResponse)
    def casamentos(request: Request, aba: str = "pendentes"):
        if aba not in ABAS_CASAMENTO:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"aba inválida: {aba}")
        with sessoes() as s, s.begin():
            config = repo_amz.obter_config(s)
            linhas, total = consultas_amazon.pendentes(s, config.desconto_min_pct)
            return templates.TemplateResponse(
                request,
                "casamentos.html",
                {
                    "aba": aba,
                    "linhas": linhas,
                    "total": total,
                    "revisados": consultas_amazon.revisados(s) if aba == "revisados" else [],
                    "desconto_min_pct": config.desconto_min_pct,
                },
            )

    @app.post("/casamentos/{anuncio_id}")
    async def revisar_casamento(request: Request, anuncio_id: int):
        formulario = await ler_formulario(request)
        acao, aba = formulario.get("acao", ""), formulario.get("aba", "pendentes")
        if acao not in ("confirmar", "ignorar", "desfazer") or aba not in ABAS_CASAMENTO:
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
        return RedirectResponse(f"/casamentos?aba={aba}", status_code=status.HTTP_303_SEE_OTHER)

    @app.get("/casamentos/{anuncio_id}/trocar", response_class=HTMLResponse)
    def trocar_casamento(request: Request, anuncio_id: int, busca: str = ""):
        with sessoes() as s, s.begin():
            anuncio = s.get(AnuncioAmazon, anuncio_id)
            if anuncio is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            return templates.TemplateResponse(
                request,
                "trocar.html",
                {"anuncio": anuncio, "busca": busca, "produtos": consultas_amazon.buscar_produtos(s, busca)},
            )
```

- [ ] **Step 5: Templates**

`src/tcg_sniper/admin/templates/casamentos.html`:

```html
{% extends "base.html" %}
{% block titulo %}Casamentos · TCG Sniper{% endblock %}
{% block conteudo %}
<h2>Casamentos Amazon × Liga</h2>
<p>
  <a href="/casamentos"{% if aba == "pendentes" %} aria-current="page"{% endif %}>{{ total }} pendentes</a> ·
  <a href="/casamentos?aba=revisados"{% if aba == "revisados" %} aria-current="page"{% endif %}>Revisados</a>
</p>
{% if aba == "pendentes" %}
<p><small>Primeiro os que já estão pelo menos {{ desconto_min_pct }}% abaixo da sugestão. Só anúncios confirmados geram oportunidade.</small></p>
<table>
  <thead><tr><th>Amazon</th><th>Preço</th><th>Produto da Liga</th><th></th></tr></thead>
  <tbody>
  {% for l in linhas %}
    <tr>
      <td><a href="{{ l.anuncio.url }}" target="_blank" rel="noopener">{{ l.anuncio.titulo }}</a><br><small>{{ l.anuncio.asin }}</small></td>
      <td>{{ l.preco|brl }}{% if l.candidato %}<br><mark>oportunidade</mark>{% endif %}</td>
      <td>
        {% if l.sugestao %}<a href="/produto/{{ l.sugestao.id }}">{{ l.sugestao.nome }}</a> ({{ l.preco_sugestao|brl }}){% else %}—{% endif %}
        {% if l.alternativas %}<details><summary>Outros parecidos</summary>
          {% for p in l.alternativas %}
          <form method="post" action="/casamentos/{{ l.anuncio.id }}">
            <input type="hidden" name="acao" value="confirmar"><input type="hidden" name="produto_id" value="{{ p.id }}">
            <button class="secondary outline">{{ p.nome }}</button>
          </form>
          {% endfor %}
        </details>{% endif %}
      </td>
      <td>
        {% if l.sugestao %}
        <form method="post" action="/casamentos/{{ l.anuncio.id }}">
          <input type="hidden" name="acao" value="confirmar"><input type="hidden" name="produto_id" value="{{ l.sugestao.id }}">
          <button>Confirmar</button>
        </form>
        {% endif %}
        <a href="/casamentos/{{ l.anuncio.id }}/trocar" role="button" class="secondary">Trocar</a>
        <form method="post" action="/casamentos/{{ l.anuncio.id }}">
          <input type="hidden" name="acao" value="ignorar"><button class="secondary outline">Ignorar</button>
        </form>
      </td>
    </tr>
  {% else %}
    <tr><td colspan="4">Nenhum anúncio pendente.</td></tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
<table>
  <thead><tr><th>Amazon</th><th>Situação</th><th>Produto da Liga</th><th>Revisado em</th><th></th></tr></thead>
  <tbody>
  {% for anuncio, produto in revisados %}
    <tr>
      <td><a href="{{ anuncio.url }}" target="_blank" rel="noopener">{{ anuncio.titulo }}</a><br><small>{{ anuncio.asin }}</small></td>
      <td>{{ anuncio.status_casamento.value }}</td>
      <td>{% if produto %}<a href="/produto/{{ produto.id }}">{{ produto.nome }}</a>{% else %}—{% endif %}</td>
      <td>{{ anuncio.revisado_em|data }}</td>
      <td>
        <form method="post" action="/casamentos/{{ anuncio.id }}">
          <input type="hidden" name="acao" value="desfazer"><input type="hidden" name="aba" value="revisados">
          <button class="secondary outline">Desfazer</button>
        </form>
      </td>
    </tr>
  {% else %}
    <tr><td colspan="5">Nenhum anúncio revisado ainda.</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endif %}
{% endblock %}
```

`src/tcg_sniper/admin/templates/trocar.html`:

```html
{% extends "base.html" %}
{% block titulo %}Trocar casamento · TCG Sniper{% endblock %}
{% block conteudo %}
<h2>Escolher o produto da Liga</h2>
<p><a href="{{ anuncio.url }}" target="_blank" rel="noopener">{{ anuncio.titulo }}</a> ({{ anuncio.asin }})</p>
<form method="get" action="/casamentos/{{ anuncio.id }}/trocar">
  <input type="search" name="busca" value="{{ busca }}" placeholder="Buscar no catálogo da Liga">
</form>
<table>
  <tbody>
  {% for p in produtos %}
    <tr>
      <td>{{ p.nome }}</td>
      <td>
        <form method="post" action="/casamentos/{{ anuncio.id }}">
          <input type="hidden" name="acao" value="confirmar"><input type="hidden" name="produto_id" value="{{ p.id }}">
          <button>Escolher</button>
        </form>
      </td>
    </tr>
  {% else %}
    <tr><td colspan="2">Nenhum produto encontrado.</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

- [ ] **Step 6: Rodar**

Run: `uv run pytest -q && uv run ruff check`
Expected: tudo passa. Se `test_trocar_busca_produtos_do_catalogo` acusar "Caixa FF" na página por causa do título da página, o teste já olha só depois do último `<table>`; ajuste o recorte do texto se o template mudar.

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/admin tests/admin/test_admin_amazon.py
git commit -m "feat: admin review queue for Amazon listing matches"
```

---

### Task 14: Admin: ofertas (diferenças Amazon × Liga) e a Amazon na página do produto

**Files:**
- Modify: `src/tcg_sniper/admin/consultas_amazon.py`, `src/tcg_sniper/admin/app.py`, `src/tcg_sniper/admin/templates/produto.html`
- Create: `src/tcg_sniper/admin/templates/ofertas.html`
- Test: `tests/admin/test_admin_amazon.py`

**Interfaces:**
- Consumes: `motor.Regras`, `motor.Vendedor`, `motor.vendedor_confiavel`, `motor.atinge_desconto`, `motor.desconto_pct` (Task 8).
- Produces (em `consultas_amazon`):
  - `FILTROS_OFERTAS = ("todas", "desconto", "abertas")`
  - `LinhaOferta(produto: ProdutoLiga, preco_liga: Decimal | None, anuncio: AnuncioAmazon, preco: Decimal | None, envio: Envio, vendedor: VendedorAmazon | None, confiavel: bool, coletado_em: datetime, desconto: Decimal | None, aberta: bool)`
  - `ofertas(s, filtro: str, config: ConfigAmazon) -> list[LinhaOferta]`
  - `amazon_do_produto(s, produto_id) -> list[tuple[AnuncioAmazon, PrecoAtualAmazon | None, VendedorAmazon | None]]`
  - `historico_amazon(s, produto_id, limite: int = 90) -> list[tuple[PrecoAmazon, str]]` (preço e ASIN)
- rota `GET /ofertas?filtro=todas|desconto|abertas`; `GET /produto/{id}` ganha a seção Amazon

- [ ] **Step 1: Escrever os testes**

Acrescente a `tests/admin/test_admin_amazon.py` (imports: `from tcg_sniper.coletor_amazon.modelos import AvaliacaoVendedor`):

```python
def preparar_ofertas(s):
    ff = criar_produto(s, "ff", nome="Caixa FF")
    sem_desconto = criar_produto(s, "sd", nome="Caixa Sem Desconto")
    criar_produto(s, "sem_amazon", nome="Caixa Sem Amazon")
    criar_preco_liga(s, ff, "1000.00")
    criar_preco_liga(s, sem_desconto, "100.00")
    amazon = repo_amz.vendedor_da_amazon(s)
    caro = anuncio_com_preco(s, "B01", ff, "800.00", status=StatusCasamento.CONFIRMADO)
    barato = anuncio_com_preco(s, "B02", ff, "700.00", status=StatusCasamento.CONFIRMADO)
    repo_amz.registrar_preco(s, barato.id, Decimal("690.00"), OrigemPreco.PRODUTO, amazon.id, Envio.AMAZON, T0, SP)
    anuncio_com_preco(s, "B03", sem_desconto, "95.00", status=StatusCasamento.CONFIRMADO)
    anuncio_com_preco(s, "B04", ff, "10.00")  # pendente: não entra
    repo_amz.abrir_oportunidade(
        s, anuncio_id=barato.id, produto_id=ff.id, preco_amazon=Decimal("690.00"), preco_liga=Decimal("1000.00"),
        desconto_pct=Decimal("31.00"), vendedor_id=amazon.id, envio=Envio.AMAZON, agora=T0,
    )
    return ff, sem_desconto, caro, barato


def test_ofertas_melhor_oferta_por_produto_ordenada_por_desconto(s):
    ff, sem_desconto, _, barato = preparar_ofertas(s)
    config = repo_amz.obter_config(s)
    linhas = consultas_amazon.ofertas(s, "todas", config)
    assert [(l.produto.id, l.anuncio.asin, l.preco, l.desconto) for l in linhas] == [
        (ff.id, "B02", Decimal("690.00"), Decimal("31.00")),
        (sem_desconto.id, "B03", Decimal("95.00"), Decimal("5.00")),
    ]
    assert linhas[0].aberta and linhas[0].confiavel and not linhas[1].aberta
    assert [l.produto.id for l in consultas_amazon.ofertas(s, "desconto", config)] == [ff.id]
    assert [l.produto.id for l in consultas_amazon.ofertas(s, "abertas", config)] == [ff.id]


def test_lojista_fba_confiavel_ou_nao(s):
    ff = criar_produto(s, "ff")
    criar_preco_liga(s, ff, "1000.00")
    anuncio = anuncio_com_preco(s, "B01", ff, "700.00", status=StatusCasamento.CONFIRMADO)
    loja = repo_amz.gravar_vendedor(s, AvaliacaoVendedor("A1", "Loja", Decimal("85"), 50), T0)
    repo_amz.registrar_preco(s, anuncio.id, Decimal("700.00"), OrigemPreco.PRODUTO, loja.id, Envio.FBA, T0, SP)
    [linha] = consultas_amazon.ofertas(s, "todas", repo_amz.obter_config(s))
    assert (linha.envio, linha.vendedor.nome, linha.confiavel) == (Envio.FBA, "Loja", False)


def test_tela_de_ofertas(cliente, sessoes):
    with sessoes() as s, s.begin():
        preparar_ofertas(s)
    texto = cliente.get("/ofertas").text
    assert "Caixa FF" in texto and "R$ 690,00" in texto and "31,00%" in texto and "Caixa Sem Amazon" not in texto
    assert "Caixa Sem Desconto" not in cliente.get("/ofertas?filtro=desconto").text
    assert cliente.get("/ofertas?filtro=xyz").status_code == 400


def test_produto_mostra_a_amazon(cliente, sessoes):
    with sessoes() as s, s.begin():
        ff, _, _, _ = preparar_ofertas(s)
    texto = cliente.get(f"/produto/{ff.id}").text
    assert "Amazon" in texto and "B02" in texto and "R$ 690,00" in texto and "vendido pela Amazon" in texto
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/admin/test_admin_amazon.py -q`
Expected: FAIL (`AttributeError: ... has no attribute 'ofertas'`).

- [ ] **Step 3: Consultas**

Acrescente a `src/tcg_sniper/admin/consultas_amazon.py` (imports: `from datetime import datetime`; modelos `ConfigAmazon`, `Envio`, `Oportunidade`, `PrecoAmazon`, `VendedorAmazon`; `from tcg_sniper.oportunidades.motor import Regras, Vendedor, desconto_pct, vendedor_confiavel`):

```python
FILTROS_OFERTAS = ("todas", "desconto", "abertas")


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
    aberta: bool


def ofertas(s: Session, filtro: str, config: ConfigAmazon) -> list[LinhaOferta]:
    """Uma linha por produto da Liga com ASIN confirmado e preço: a oferta mais barata da Amazon
    contra o "À partir de" da Liga, ordenadas pelo maior desconto."""
    consulta = (
        select(AnuncioAmazon, ProdutoLiga, PrecoAtualAmazon, VendedorAmazon, PrecoAtualLiga.preco_a_partir)
        .join(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .join(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAtualAmazon.vendedor_id)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(AnuncioAmazon.status_casamento == StatusCasamento.CONFIRMADO, PrecoAtualAmazon.preco.is_not(None))
    )
    abertas = set(s.scalars(select(Oportunidade.produto_id).where(Oportunidade.fechada_em.is_(None))))
    regras = Regras.de(config)
    melhores: dict[int, LinhaOferta] = {}
    for anuncio, produto, atual, vendedor, preco_liga in s.execute(consulta):
        atual_melhor = melhores.get(produto.id)
        if atual_melhor is not None and atual_melhor.preco <= atual.preco:
            continue
        info = Vendedor(vendedor.nome, vendedor.pct_positivas, vendedor.num_avaliacoes) if vendedor else None
        melhores[produto.id] = LinhaOferta(
            produto=produto,
            preco_liga=preco_liga,
            anuncio=anuncio,
            preco=atual.preco,
            envio=atual.envio,
            vendedor=vendedor,
            confiavel=atual.envio is Envio.AMAZON or (atual.envio is Envio.FBA and vendedor_confiavel(info, regras)),
            coletado_em=atual.coletado_em,
            desconto=desconto_pct(atual.preco, preco_liga) if preco_liga else None,
            aberta=produto.id in abertas,
        )
    linhas = list(melhores.values())
    if filtro == "desconto":
        linhas = [l for l in linhas if atinge_desconto(l.preco, l.preco_liga, config.desconto_min_pct)]
    elif filtro == "abertas":
        linhas = [l for l in linhas if l.aberta]
    linhas.sort(key=lambda l: (l.desconto is None, -(l.desconto or 0), l.produto.nome))
    return linhas


def amazon_do_produto(
    s: Session, produto_id: int
) -> list[tuple[AnuncioAmazon, PrecoAtualAmazon | None, VendedorAmazon | None]]:
    consulta = (
        select(AnuncioAmazon, PrecoAtualAmazon, VendedorAmazon)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .outerjoin(VendedorAmazon, VendedorAmazon.id == PrecoAtualAmazon.vendedor_id)
        .where(AnuncioAmazon.produto_id == produto_id, AnuncioAmazon.status_casamento == StatusCasamento.CONFIRMADO)
        .order_by(PrecoAtualAmazon.preco.nulls_last(), AnuncioAmazon.id)
    )
    return [(anuncio, atual, vendedor) for anuncio, atual, vendedor in s.execute(consulta)]


def historico_amazon(s: Session, produto_id: int, limite: int = 90) -> list[tuple[PrecoAmazon, str]]:
    consulta = (
        select(PrecoAmazon, AnuncioAmazon.asin)
        .join(AnuncioAmazon, AnuncioAmazon.id == PrecoAmazon.anuncio_id)
        .where(AnuncioAmazon.produto_id == produto_id, AnuncioAmazon.status_casamento == StatusCasamento.CONFIRMADO)
        .order_by(PrecoAmazon.coletado_em.desc(), PrecoAmazon.id.desc())
        .limit(limite)
    )
    return [(preco, asin) for preco, asin in s.execute(consulta)]
```

O desconto de "Caixa Sem Desconto" no teste é 5% (95 sobre 100); o de "Caixa FF" é 31% (690 sobre 1.000), e a linha usa a leitura mais recente do anúncio B02 (a da página do produto, R$ 690,00).

- [ ] **Step 4: Rotas e templates**

Em `src/tcg_sniper/admin/app.py`, acrescente:

```python
    @app.get("/ofertas", response_class=HTMLResponse)
    def ofertas(request: Request, filtro: str = "todas"):
        if filtro not in consultas_amazon.FILTROS_OFERTAS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"filtro inválido: {filtro}")
        with sessoes() as s, s.begin():
            config = repo_amz.obter_config(s)
            return templates.TemplateResponse(
                request,
                "ofertas.html",
                {
                    "linhas": consultas_amazon.ofertas(s, filtro, config),
                    "filtro": filtro,
                    "filtros": consultas_amazon.FILTROS_OFERTAS,
                    "desconto_min_pct": config.desconto_min_pct,
                },
            )
```

e, no contexto de `produto`, `"amazon": consultas_amazon.amazon_do_produto(s, produto_id)` e `"historico_amazon": consultas_amazon.historico_amazon(s, produto_id)`. Registre também um filtro de template para o envio:

```python
    templates.env.filters["envio"] = lambda envio, vendedor=None: {
        "amazon": "vendido pela Amazon",
        "fba": f"vendido por {vendedor.nome if vendedor and vendedor.nome else 'lojista'}, enviado pela Amazon",
        "proprio": f"vendido e enviado por {vendedor.nome if vendedor and vendedor.nome else 'lojista'}",
    }.get(envio.value, "—")
```

`src/tcg_sniper/admin/templates/ofertas.html`:

```html
{% extends "base.html" %}
{% block titulo %}Ofertas · TCG Sniper{% endblock %}
{% block conteudo %}
<h2>Ofertas Amazon × Liga</h2>
<p>
  {% for f in filtros %}<a href="/ofertas?filtro={{ f }}"{% if f == filtro %} aria-current="page"{% endif %}>{{ {"todas": "Todas", "desconto": "Só ≥ " ~ desconto_min_pct ~ "%", "abertas": "Só oportunidades abertas"}[f] }}</a>{% if not loop.last %} · {% endif %}{% endfor %}
</p>
<table>
  <thead><tr><th>Produto</th><th>Liga (à partir de)</th><th>Amazon</th><th>Diferença</th><th>Vendedor</th><th>Lido em</th></tr></thead>
  <tbody>
  {% for l in linhas %}
    <tr>
      <td><a href="/produto/{{ l.produto.id }}">{{ l.produto.nome }}</a>{% if l.aberta %} <mark>oportunidade</mark>{% endif %}</td>
      <td>{{ l.preco_liga|brl }}</td>
      <td><a href="{{ l.anuncio.url }}" target="_blank" rel="noopener">{{ l.preco|brl }}</a></td>
      <td>{{ (l.desconto|string).replace(".", ",") ~ "%" if l.desconto is not none else "—" }}</td>
      <td>{{ l.envio|envio(l.vendedor) }}{% if not l.confiavel %} <small>(não elegível)</small>{% endif %}</td>
      <td>{{ l.coletado_em|data }}</td>
    </tr>
  {% else %}
    <tr><td colspan="6">Nenhum produto com anúncio da Amazon confirmado.</td></tr>
  {% endfor %}
  </tbody>
</table>
{% endblock %}
```

Em `src/tcg_sniper/admin/templates/produto.html`, antes de `<h3>Histórico do preço à partir de</h3>`:

```html
<article>
  <header><strong>Amazon</strong> (anúncios confirmados em <a href="/casamentos?aba=revisados">Casamentos</a>)</header>
  <table>
    <thead><tr><th>ASIN</th><th>Preço</th><th>Vendedor</th><th>Lido em</th></tr></thead>
    <tbody>
    {% for anuncio, atual, vendedor in amazon %}
      <tr>
        <td><a href="{{ anuncio.url }}" target="_blank" rel="noopener">{{ anuncio.asin }}</a></td>
        <td>{{ (atual.preco if atual else None)|brl }}</td>
        <td>{{ atual.envio|envio(vendedor) if atual else "—" }}</td>
        <td>{{ (atual.coletado_em if atual else None)|data }}</td>
      </tr>
    {% else %}
      <tr><td colspan="4">Nenhum anúncio da Amazon confirmado.</td></tr>
    {% endfor %}
    </tbody>
  </table>
  {% if historico_amazon %}
  <details><summary>Histórico de preço na Amazon</summary>
    <table>
      <thead><tr><th>Data</th><th>ASIN</th><th>Preço</th><th>Origem</th></tr></thead>
      <tbody>
      {% for preco, asin in historico_amazon %}
        <tr><td>{{ preco.coletado_em|data }}</td><td>{{ asin }}</td><td>{{ preco.preco|brl }}</td><td>{{ preco.origem.value }}</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </details>
  {% endif %}
</article>
```

- [ ] **Step 5: Rodar**

Run: `uv run pytest -q && uv run ruff check`
Expected: tudo passa. A coluna "Diferença" mostra `31,00%` (o `Decimal` do banco tem duas casas).

- [ ] **Step 6: Commit**

```bash
git add src/tcg_sniper/admin tests/admin/test_admin_amazon.py
git commit -m "feat: admin offers page and Amazon section on the product page"
```

- [ ] **Step 7: Smoke test completo (com alguém acompanhando)**

1. `docker compose up -d --build` e `docker compose ps -a`: `postgres`, `evolution`, `coletor-liga`, `coletor-amazon` e `admin` em `Up`; `migrate` em `Exited (0)`.
2. `docker compose logs coletor-amazon --tail 30`: `varredura da Amazon iniciada`, sem traceback.
3. Abra `http://<HOST_PUBLICO>:6081/vnc.html`, defina o CEP na Amazon (README, passo 8).
4. Em `http://<HOST_PUBLICO>:8000`, a seção Amazon mostra "Ativo" e, dentro da janela, "Ciclo em andamento". Em **Configurações**, os padrões (25%, 08:00–22:00, 200 buscas/h).
5. Depois de alguns minutos, **Casamentos** mostra pendentes. Confirme os que forem o mesmo produto da Liga e ignore os outros.
6. Em **Ofertas**, os produtos confirmados aparecem com a diferença. Quando uma oferta passar dos 25%, o grupo de oportunidades recebe a mensagem.
7. Anote no fim deste plano, em "Estado e ordem de execução", o resultado: duração de um ciclo, buscas por hora, CAPTCHAs, pendentes por busca. Esses números alimentam o critério de sucesso (uma semana de fila) e o ajuste de `max_buscas_hora` e `resultados_por_busca`.
