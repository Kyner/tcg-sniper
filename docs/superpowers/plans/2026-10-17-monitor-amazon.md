# Monitor de preço da Amazon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O `coletor-amazon` passa a ter três trabalhos num navegador só — conferência de checkout das candidatas, monitor de preço (lista de ofertas de cada anúncio confirmado a cada 15 min) e descoberta (busca + IA só para quem não tem par, e uma vez por semana para os casados) —, o alerta usa a melhor oferta elegível e, quando conferido, o total do checkout, e todo casamento mostra a origem (manual, sugerido pela IA, automático pela IA).

**Architecture:** Antes de qualquer parser, uma ferramenta de captura (`tcg-sniper amazon capturar`) salva as páginas reais com o perfil logado do coletor, e um anonimizador transforma essas páginas em fixtures sem dado pessoal; os parsers da lista de ofertas, do carrinho e do checkout são escritos TDD contra essas fixtures. Todo clique no site passa por `coletor_amazon/cliques.py` (lista fixa de ações permitidas e lista proibida conferida no HTML lido e de novo no elemento que o Chromium vai clicar). `monitor.py` lê as ofertas e roda o motor; `checkout.py` confere o total sem tocar no banco; a `varredura` escolhe o próximo trabalho por prioridade, com janela e teto de páginas por hora próprios do monitor.

**Tech Stack:** Python 3.12, uv, SQLAlchemy 2 + Alembic, Postgres 16, Playwright/Chromium (perfil persistente), selectolax (lexbor), FastAPI + Jinja2 + DaisyUI 5, pytest.

**Spec:** `docs/superpowers/specs/2026-10-17-monitor-amazon-design.md`

## Global Constraints

- O sistema **nunca confirma pedido** e **nunca usa "Comprar agora"**. Só `src/tcg_sniper/coletor_amazon/cliques.py` chama `NavegadorInterativo.clicar` (há um teste que varre o código). Cliques permitidos: adicionar ao carrinho (da lista de ofertas), fechar pedido, entregar neste endereço, excluir do carrinho. A lista proibida (`placeOrder`, `placeYourOrder`, `submitOrder`, "Confirmar pedido", "Finalizar pedido", "Comprar agora", "Fazer pedido", `buy-now`, `turbo-checkout`, 1-Clique) é conferida antes de todo clique.
- Itens do carrinho do usuário nunca são tocados: com qualquer item no carrinho ativo a conferência não clica em nada (`carrinho_ocupado`); "Salvo para depois" não conta e nunca é tocado (toda exclusão é escopada no bloco do carrinho ativo e no ASIN conferido).
- Padrões da `config_amazon` (verbatim do spec): `monitor_ligado=true`, `monitor_intervalo_min=15`, `monitor_janela_inicio=08:00`, `monitor_janela_fim=22:00`, `monitor_max_paginas_hora=150`, `checkout_ligado=true`, `margem_candidata_pp=5`, `checkout_validade_h=6`, `descoberta_casados_dias=7`, `checkout_sem_login_em=NULL`.
- Valores fixos: `OrigemPreco.OFERTAS="ofertas"`; `OrigemCasamento`: `manual`, `sugerido_ia`, `automatico_ia` (nula enquanto pendente); `SituacaoCheckout`: `ok`, `falha`, `carrinho_ocupado`, `sem_login`.
- Descontos condicionais (cupom, cartão Amazon, primeira compra) só aparecem como informação; nunca entram no preço.
- Fixtures vêm de páginas reais, passam por `scripts/anonimizar_fixture.py` e o teste `tests/test_fixtures_privacidade.py` falha com CPF, CEP, final de cartão, e-mail, telefone, número de pedido ou qualquer texto de `.fixtures-brutas/proibidos.txt` (fora do git). Páginas brutas ficam só em `<DIR_DADOS>/capturas` e `.fixtures-brutas/` (ambos fora do git).
- Nenhum teste abre navegador ou rede de verdade (`NavegadorFake`/`NavegadorInterativoFake`, páginas Playwright falsas).
- Admin: só componentes do DaisyUI 5 e utilitários do Tailwind, classes literais (nunca concatenadas); toda tarefa que mexe em template regenera `src/tcg_sniper/admin/static/admin.css` com `uv run python scripts/gerar_css.py` e commita.
- Nomes, comentários, mensagens e textos em português, como o resto do código. Mensagens de commit em inglês, no formato `feat:`/`fix:`/`test:`, **sem** linha `Co-Authored-By` nem qualquer trailer de IA.
- Cada lane paralela usa o próprio banco de testes (o fixture `engine` apaga o schema): crie com `docker compose exec -T postgres createdb -U tcg tcg_test_<lane>` (se ainda não existir) e rode `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_<lane> uv run pytest -q` e `uv run ruff check .` — ambos verdes ao fim de cada tarefa. Nos comandos abaixo `<lane>` é o número da tarefa (ex.: `tcg_test_t3`).

## Review Focus

1. **Itens do próprio usuário no carrinho** (ativos ou "salvo para depois", inclusive do mesmo ASIN): com item ativo, a conferência não clica em nada e registra `carrinho_ocupado`, sem martelar o carrinho a cada passo (espera 1 h); itens salvos nunca são clicados. Testes na Task 13 (`test_carrinho_ocupado_nao_clica_em_nada`, `test_itens_salvos_para_depois_nao_contam_e_nunca_sao_tocados`) e na Task 14 (`test_carrinho_ocupado_espera_uma_hora`).
2. **Login expirado no meio da conferência** (o carrinho abre, mas "Fechar pedido" cai no login): situação `sem_login`, o item adicionado é retirado, `checkout_sem_login_em` é preenchida, um único aviso no WhatsApp com o noVNC (porta 6081) e o monitor continua lendo. Testes na Task 13 (`test_login_expirado_no_checkout_retira_o_item`) e na Task 14 (`test_sem_login_desliga_a_conferencia_avisa_uma_vez_e_o_monitor_continua`).
3. **Monitor estourando o teto de páginas por hora** (muitos confirmados, intervalo curto, conferências caras): ao chegar em `monitor_max_paginas_hora` (monitor + conferência + retirada, somados) o monitor espera, a descoberta segue no próprio teto e o Dashboard avisa que o monitor não cabe no intervalo. Testes na Task 14 (`test_monitor_e_conferencia_somam_no_mesmo_teto_e_a_descoberta_segue`) e na Task 8 (`test_dashboard_avisa_monitor_que_nao_cabe_no_intervalo`).
4. **Lista de ofertas vazia ou ilegível** (anúncio indisponível, painel sem ofertas, layout novo): vazia grava preço nulo, nenhuma oferta e fecha a oportunidade aberta sem alerta; sem a estrutura do painel vira `ErroParser` com HTML salvo, e o anúncio não trava o monitor. Testes na Task 10 (`test_painel_sem_ofertas_devolve_lista_vazia`, `test_pagina_sem_painel_levanta_erro_parser`), Task 12 (`test_sem_ofertas_registra_preco_nulo_e_fecha_a_oportunidade`) e Task 14 (`test_monitor_que_falha_nao_trava_no_mesmo_anuncio`).
5. **Botão proibido renderizado onde se espera um permitido** (ex.: "Confirmar pedido" com o seletor de "Entregar neste endereço", ou a tela muda entre a leitura e o clique): nada é clicado, a conferência vira `falha` com o motivo e o item é retirado. Testes na Task 1 (`test_botao_proibido_no_lugar_do_esperado_nao_e_clicado`, `test_a_guarda_do_navegador_confere_o_elemento_da_tela`) e na Task 13 (`test_botao_proibido_no_lugar_de_entregar_nao_e_clicado_e_o_item_sai`).

## Decisões tomadas neste plano (o spec não fixava)

- **Teto por hora:** `monitor_max_paginas_hora` limita as páginas do monitor, da conferência de checkout e da retirada de itens, **somadas**; a descoberta continua limitada por `max_buscas_hora` (buscas). Assim o monitor nunca deixa a descoberta sem vez, e a prioridade conferência > monitor > descoberta decide quem vai primeiro quando há orçamento.
- **"Anúncios novos da busca semanal"** (casador): pendente de produto já casado só é avaliado pela IA se foi visto pela primeira vez **depois** do primeiro casamento confirmado do produto (`visto_primeiro_em > min(revisado_em)` dos confirmados). Depois de casado, o produto só é buscado na semanal, então esses são exatamente os anúncios novos da semanal; os pendentes antigos ficam visíveis em Casamentos.
- **Referência sem oferta elegível:** quando nenhuma oferta é elegível, a mais barata nova vira a linha de `preco_amazon` (com vendedor e envio dela, então o motor não alerta), como hoje a buy box era gravada mesmo inelegível. Oferta usada nunca é elegível.
- **Busca não sobrescreve o monitor:** um preço de origem `busca` entra no histórico mas não troca o preço atual de um anúncio cuja última leitura é `ofertas`.
- **Cache da conferência:** uma conferência `ok` ou `falha` da mesma oferta (ASIN + vendedor + preço) bloqueia nova tentativa por `checkout_validade_h`; depois de `carrinho_ocupado` a conferência espera 1 h.
- **Anúncio colado à mão:** o monitor lê a página do produto uma vez enquanto o título for o provisório ("Informado manualmente"), para trazer título, variação e imagem (antes a busca fazia isso ao abrir o produto).
- **Liga/desliga** do monitor e da conferência ficam só em Serviços; Configurações → Amazon ganha a seção "Monitor de preço" com os campos numéricos e de horário.
- **Cupom** só sai na mensagem do monitor (a tabela `oferta_amazon` do spec não tem a coluna).

---

## Ondas (para execução paralela)

- **Onda A (em paralelo):** Task 1 (guarda de cliques e navegador interativo), Task 2 (anonimização e teste de privacidade), Task 3 (modelos, migração, repositório e configuração), Task 4 (motor e mensagens).
- **Onda B (em paralelo):** Task 5 (ferramenta de captura) — depende da 1; Task 6 (origem do casamento e casador) — depende da 3; Task 7 (admin: ofertas, conferência e origem) — depende da 3; Task 8 (admin: Configurações, Serviços, Logs e Dashboard) — depende da 3.
- **Onda C (o controlador, não um subagente, em produção):** Task 9 (captura real e fixtures) — depende das 2 e 5 e do login do usuário no noVNC.
- **Onda D (em paralelo):** Task 10 (parser da lista de ofertas), Task 11 (parsers do carrinho, do checkout e do login) — dependem da 9.
- **Onda E (em paralelo):** Task 12 (monitor de preço e busca sem confirmados) — depende das 3, 4 e 10; Task 13 (conferência de checkout) — depende das 1, 10 e 11.
- **Onda F:** Task 14 (integração na varredura, README e implantação) — depende de todas.
- Conflitos esperados e como resolver: `tests/fakes.py` (Tasks 1 e 3 acrescentam no fim: manter os dois blocos); `src/tcg_sniper/admin/app.py` (Task 6 mexe só em `revisar_casamento`, Task 8 em Serviços/Logs/rotas novas); `src/tcg_sniper/admin/static/admin.css` (Tasks 7 e 8: na integração rodar `uv run python scripts/gerar_css.py` e commitar o resultado).

## Arquivos

| Arquivo | Responsabilidade | Tasks |
|---|---|---|
| `src/tcg_sniper/navegador/base.py` | protocolo `NavegadorInterativo` (`atual`, `abrir_e_esperar`, `clicar` com guarda) | 1 |
| `src/tcg_sniper/navegador/chromium.py` | implementação do clique conferido no próprio elemento | 1 |
| `src/tcg_sniper/coletor_amazon/cliques.py` (novo) | ações permitidas, lista proibida, `clicar_permitido`, `remover_do_carrinho` | 1 |
| `src/tcg_sniper/coletor_amazon/anonimizar.py` (novo) + `scripts/anonimizar_fixture.py` (novo) | limpar e anonimizar páginas reais | 2 |
| `src/tcg_sniper/db/models.py`, migração `b9e4c2a7d3f5_monitor_amazon.py` (nova), `db/repositorio_amazon.py`, `coletor_amazon/modelos.py`, `coletor_amazon/config.py` | dados, consultas e formulário | 3 (e 6 no casamento) |
| `src/tcg_sniper/oportunidades/motor.py`, `mensagens.py` | elegibilidade pública e mensagem com conferência | 4 |
| `src/tcg_sniper/coletor_amazon/captura.py` (novo), `cli.py` | `tcg-sniper amazon capturar` | 5 |
| `src/tcg_sniper/db/repositorio_ia.py`, `casador/servico.py`, `admin/app.py` (`revisar_casamento`) | origem do casamento, casador só para não casados | 6 |
| `src/tcg_sniper/admin/consultas_amazon.py`, templates `_componentes`, `casamentos_produto`, `produto`, `ofertas` | ofertas da leitura, conferência, selos | 7 |
| `src/tcg_sniper/admin/app.py`, `consultas.py`, `consultas_painel.py`, templates `configuracoes`, `servicos`, `logs` | painel | 8 |
| `tests/fixtures/amazon/*.html`, `tests/fixtures/amazon/esperado.json` | páginas reais anonimizadas e valores lidos à mão | 9 |
| `src/tcg_sniper/coletor_amazon/parsers.py` | `parse_ofertas` | 10 |
| `src/tcg_sniper/coletor_amazon/parsers_checkout.py` (novo) | carrinho, resumo do checkout, login | 11 |
| `src/tcg_sniper/coletor_amazon/monitor.py` (novo), `busca.py` | monitor; busca sem página de produto | 12 |
| `src/tcg_sniper/coletor_amazon/checkout.py` (novo) | conferência de checkout | 13 |
| `src/tcg_sniper/coletor_amazon/varredura.py`, `README.md` | escolha do trabalho, teto, janela, avisos | 14 |

---

### Task 1: Guarda de cliques e navegador interativo

**Files:**
- Modify: `src/tcg_sniper/navegador/base.py`
- Modify: `src/tcg_sniper/navegador/chromium.py`
- Modify: `src/tcg_sniper/coletor_amazon/parsers.py` (só URLs novas)
- Create: `src/tcg_sniper/coletor_amazon/cliques.py`
- Modify: `tests/fakes.py` (acrescenta `NavegadorInterativoFake` no fim)
- Test: `tests/coletor_amazon/test_cliques.py` (novo), `tests/navegador/test_chromium.py` (acrescenta)

**Interfaces:**
- Consumes: `navegador.modelos.Pagina`, `ErroRede`; `fakes.NavegadorFake`, `fakes.pagina_html`.
- Produces:
  - `navegador.base.Guarda = Callable[[str, str], None]`; `navegador.base.NavegadorInterativo` (Protocol, estende `Navegador`): `atual() -> Pagina`, `abrir_e_esperar(url: str, seletor: str, timeout_ms: int = 15_000) -> Pagina`, `clicar(seletor: str, indice: int, guarda: Guarda) -> Pagina`.
  - `NavegadorChromium.atual`, `.abrir_e_esperar`, `.clicar` (mesmas assinaturas).
  - `parsers.URL_CARRINHO: str`, `parsers.SELETOR_PAINEL_OFERTAS: str`, `parsers.url_ofertas(asin: str) -> str`, `parsers.url_painel_ofertas(asin: str) -> str`.
  - `cliques.Acao(nome: str, seletores: tuple[str, ...], padrao: re.Pattern[str])`; constantes `ADICIONAR`, `FECHAR_PEDIDO`, `ENTREGAR`, `EXCLUIR`, `ACOES`, `PROIBIDOS`, `ESCOPOS_CARRINHO_ATIVO: tuple[str, ...]`, `ESCOPO_OFERTA_DESTAQUE = "#aod-pinned-offer"`, `ESCOPO_OFERTA_LISTA = "#aod-offer"`.
  - `cliques.CliqueProibido(Exception)`, `cliques.SeletorAusente(Exception)`.
  - `cliques.texto_do_elemento(no: LexborNode) -> str`, `cliques.conferir_clique(acao: Acao, html_elemento: str, texto: str) -> None`.
  - `cliques.localizar(acao: Acao, pagina: Pagina, escopo: str = "", bloco: int = 0) -> tuple[str, int] | None` (seletor completo e índice do botão entre todos os elementos desse seletor na página).
  - `cliques.clicar_permitido(nav: NavegadorInterativo, acao: Acao, pagina: Pagina, escopo: str = "", bloco: int = 0) -> Pagina`.
  - `cliques.asin_no_carrinho_ativo(pagina: Pagina, asin: str) -> bool`.
  - `cliques.remover_do_carrinho(nav: NavegadorInterativo, asin: str, abrir: Callable[[str], Pagina], pausar: Callable[[], None]) -> tuple[bool, int]` (removido — também `True` se o item não estava lá —, páginas abertas).
  - `fakes.NavegadorInterativoFake(paginas, apos_clique=None)`: `.cliques: list[tuple[str, int]]`, `.esperas: list[tuple[str, str]]`; `apos_clique` é uma lista (cada clique consome a próxima página) ou um dict `{trecho_do_seletor: Pagina | list[Pagina]}`.

- [ ] **Step 1: Testes do Chromium (falham)**

Acrescente em `tests/navegador/test_chromium.py` (o arquivo já tem `PaginaPw`, `navegador_com`, `pytest`, `PlaywrightError` e `ErroRede`):

```python
class ElementoPw:
    def __init__(self, html, texto):
        self.html, self.texto, self.cliques = html, texto, 0

    def evaluate(self, _js):
        return [self.html, self.texto]

    def click(self, **_):
        self.cliques += 1


class LocalizadoPw:
    def __init__(self, elementos, indice):
        self.elementos, self.indice = elementos, indice

    def element_handle(self, **_):
        if self.indice >= len(self.elementos):
            raise PlaywrightError("Timeout 1000ms exceeded")
        return self.elementos[self.indice]


class LocatorPw:
    def __init__(self, elementos):
        self.elementos = elementos

    def nth(self, indice):
        return LocalizadoPw(self.elementos, indice)


class PaginaClicavel(PaginaPw):
    def __init__(self, elementos, **kw):
        super().__init__(**kw)
        self.elementos = elementos

    def locator(self, seletor):
        return LocatorPw(self.elementos.get(seletor, []))

    def wait_for_load_state(self, *_a, **_k):
        pass


def test_clicar_confere_o_proprio_elemento_e_clica_nele():
    botao = ElementoPw('<input name="submit.addToCart">', "Adicionar ao carrinho")
    vistos = []
    n = navegador_com(PaginaClicavel({"#b": [botao]}), lambda p: False)
    n.clicar("#b", 0, lambda html, texto: vistos.append((html, texto)))
    assert vistos == [('<input name="submit.addToCart">', "Adicionar ao carrinho")]
    assert botao.cliques == 1


def test_guarda_que_levanta_impede_o_clique():
    botao = ElementoPw('<input name="placeYourOrder1">', "Confirmar pedido")
    n = navegador_com(PaginaClicavel({"#b": [botao]}), lambda p: False)

    def recusar(_html, _texto):
        raise RuntimeError("proibido")

    with pytest.raises(RuntimeError):
        n.clicar("#b", 0, recusar)
    assert botao.cliques == 0


def test_elemento_ausente_vira_erro_rede():
    n = navegador_com(PaginaClicavel({}), lambda p: False)
    with pytest.raises(ErroRede, match="não encontrado"):
        n.clicar("#nada", 0, lambda h, t: None)
```

- [ ] **Step 2: Testes da guarda (falham)**

Create `tests/coletor_amazon/test_cliques.py`:

```python
from pathlib import Path

import pytest
from fakes import NavegadorInterativoFake, pagina_html

import tcg_sniper
from tcg_sniper.coletor_amazon.cliques import (
    ACOES,
    ADICIONAR,
    ENTREGAR,
    EXCLUIR,
    FECHAR_PEDIDO,
    CliqueProibido,
    SeletorAusente,
    asin_no_carrinho_ativo,
    clicar_permitido,
    conferir_clique,
    localizar,
    remover_do_carrinho,
)
from tcg_sniper.coletor_amazon.parsers import URL_CARRINHO

PERMITIDOS = {
    ADICIONAR: '<input name="submit.addToCart" value="Adicionar ao carrinho" type="submit">',
    FECHAR_PEDIDO: '<input name="proceedToRetailCheckout" value="Fechar pedido" type="submit">',
    ENTREGAR: '<input data-testid="Address_selectShipToThisAddress" type="submit" aria-label="Entregar neste endereço">',
    EXCLUIR: '<input data-action="delete" name="submit.delete.C1" value="Excluir" type="submit">',
}
PROIBIDOS_HTML = [
    '<input name="placeYourOrder1" value="Confirmar pedido com cartão 0000" type="submit">',
    '<input id="submitOrderButtonId" type="submit">',
    '<input id="buy-now-button" name="submit.buy-now" type="submit">',
    '<span class="a-button-text">Comprar agora</span>',
    "<button>Finalizar pedido</button>",
    '<input value="Fazer pedido" type="submit">',
    '<input name="submit.addToCart" value="Comprar com 1-Clique" type="submit">',
    '<a id="turbo-checkout-pyo-button">Pagar</a>',
]


def pagina(corpo, url="https://www.amazon.com.br/x"):
    return pagina_html(f"<html><body>{corpo}</body></html>", url=url)


def item(asin):
    return f'<div data-asin="{asin}"><input data-action="delete" name="submit.delete.{asin}" value="Excluir" type="submit"></div>'


def carrinho(ativos=(), salvos=()):
    return pagina(
        f'<span id="nav-cart-count">{len(ativos)}</span>'
        f'<div data-name="Active Items">{"".join(map(item, ativos))}</div>'
        f'<div data-name="Saved Items">{"".join(map(item, salvos))}</div>',
        url=URL_CARRINHO,
    )


@pytest.mark.parametrize("acao", ACOES, ids=lambda a: a.nome)
@pytest.mark.parametrize("html", PROIBIDOS_HTML)
def test_elemento_proibido_e_recusado_em_qualquer_acao(acao, html):
    with pytest.raises(CliqueProibido):
        conferir_clique(acao, html, "")


@pytest.mark.parametrize("acao", ACOES, ids=lambda a: a.nome)
def test_botao_de_cada_acao_e_aceito(acao):
    conferir_clique(acao, PERMITIDOS[acao], "")


def test_botao_de_outra_acao_e_recusado():
    with pytest.raises(CliqueProibido, match="não é o botão esperado"):
        conferir_clique(FECHAR_PEDIDO, PERMITIDOS[EXCLUIR], "Excluir")


def test_texto_em_maiusculas_e_com_acento_tambem_casa():
    with pytest.raises(CliqueProibido):
        conferir_clique(ENTREGAR, '<input data-testid="Address_selectShipToThisAddress">', "CONFIRMAR PEDIDO")
    conferir_clique(ENTREGAR, '<span id="shipToThisAddressButton"><input></span>', "ENTREGAR NESTE ENDEREÇO")


def test_clicar_permitido_usa_o_primeiro_seletor_que_acha():
    p = pagina('<div id="sc-buy-box-ptc-button"><input value="Fechar pedido" type="submit"></div>')
    seguinte = pagina("<p>checkout</p>", url="https://www.amazon.com.br/checkout")
    nav = NavegadorInterativoFake({p.url: p}, apos_clique=[seguinte])
    nav.abrir(p.url)
    assert clicar_permitido(nav, FECHAR_PEDIDO, p) is seguinte
    assert nav.cliques == [("#sc-buy-box-ptc-button input", 0)]


def test_botao_proibido_no_lugar_do_esperado_nao_e_clicado():
    p = pagina('<input name="proceedToRetailCheckout" value="Confirmar pedido" type="submit">')
    nav = NavegadorInterativoFake({p.url: p}, apos_clique=[pagina("<p>pedido feito</p>")])
    nav.abrir(p.url)
    with pytest.raises(CliqueProibido):
        clicar_permitido(nav, FECHAR_PEDIDO, p)
    assert nav.cliques == []


def test_a_guarda_do_navegador_confere_o_elemento_da_tela():
    lida = pagina(PERMITIDOS[FECHAR_PEDIDO])
    na_tela = pagina('<input name="proceedToRetailCheckout" value="Confirmar pedido" type="submit">', url=lida.url + "?2")
    nav = NavegadorInterativoFake({na_tela.url: na_tela}, apos_clique=[pagina("<p>x</p>")])
    nav.abrir(na_tela.url)  # a tela mudou depois que `lida` foi capturada
    with pytest.raises(CliqueProibido):
        clicar_permitido(nav, FECHAR_PEDIDO, lida)
    assert nav.cliques == []


def test_sem_botao_levanta_seletor_ausente_sem_clicar():
    p = pagina("<p>passo inesperado</p>")
    nav = NavegadorInterativoFake({p.url: p})
    nav.abrir(p.url)
    with pytest.raises(SeletorAusente, match="fechar pedido"):
        clicar_permitido(nav, FECHAR_PEDIDO, p)
    assert nav.cliques == []


def test_oferta_da_lista_acha_o_botao_do_bloco_certo():
    p = pagina(
        '<div id="aod-pinned-offer"><input name="submit.addToCart" value="Adicionar ao carrinho"></div>'
        '<div id="aod-offer"><span>sem botão</span></div>'
        '<div id="aod-offer"><input name="submit.addToCart" value="Adicionar ao carrinho"></div>'
    )
    assert localizar(ADICIONAR, p, "#aod-offer", 1) == ('#aod-offer input[name="submit.addToCart"]', 0)
    assert localizar(ADICIONAR, p, "#aod-offer", 0) is None
    assert localizar(ADICIONAR, p, "#aod-offer", 5) is None
    assert localizar(ADICIONAR, p, "#aod-pinned-offer") == ('#aod-pinned-offer input[name="submit.addToCart"]', 0)


def test_remover_tira_so_do_carrinho_ativo():
    antes, depois = carrinho(["B0ALVO0001"], ["B0ALVO0001"]), carrinho([], ["B0ALVO0001"])
    nav = NavegadorInterativoFake({URL_CARRINHO: [antes, depois]}, apos_clique=[depois])
    assert remover_do_carrinho(nav, "B0ALVO0001", nav.abrir, lambda: None) == (True, 3)
    assert nav.cliques == [('[data-name="Active Items"] [data-asin="B0ALVO0001"] input[data-action="delete"]', 0)]


def test_item_so_em_salvo_para_depois_nunca_e_tocado():
    nav = NavegadorInterativoFake({URL_CARRINHO: carrinho([], ["B0ALVO0001"])})
    assert remover_do_carrinho(nav, "B0ALVO0001", nav.abrir, lambda: None) == (True, 1)
    assert nav.cliques == []


def test_remover_sem_botao_de_excluir_devolve_falso():
    sem_botao = pagina(
        '<span id="nav-cart-count">1</span><div data-name="Active Items"><div data-asin="B0ALVO0001">item</div></div>',
        url=URL_CARRINHO,
    )
    nav = NavegadorInterativoFake({URL_CARRINHO: sem_botao})
    assert remover_do_carrinho(nav, "B0ALVO0001", nav.abrir, lambda: None) == (False, 1)
    assert asin_no_carrinho_ativo(sem_botao, "B0ALVO0001")


def test_so_cliques_py_chama_clicar_do_navegador():
    raiz = Path(tcg_sniper.__file__).parent
    chamadores = sorted(
        p.relative_to(raiz).as_posix() for p in raiz.rglob("*.py") if ".clicar(" in p.read_text(encoding="utf-8")
    )
    assert chamadores == ["coletor_amazon/cliques.py"]
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t1 uv run pytest tests/coletor_amazon/test_cliques.py tests/navegador/test_chromium.py -q`
Expected: FAIL (ImportError: `cliques`; `NavegadorChromium` sem `clicar`).

- [ ] **Step 4: Protocolo**

Substitua `src/tcg_sniper/navegador/base.py` por:

```python
from collections.abc import Callable
from typing import Protocol

from tcg_sniper.navegador.modelos import Pagina

# Recebe o HTML do próprio elemento e o texto dele (texto visível, `value` e `aria-label`); levanta
# exceção para impedir o clique.
Guarda = Callable[[str, str], None]


class Navegador(Protocol):
    def vivo(self) -> bool:
        """True se a instância ainda responde (a janela não foi fechada, o processo não morreu)."""

    def abrir(self, url: str) -> Pagina:
        """Abre a URL e devolve a página renderizada. Lança ErroRede em falha de navegação,
        exceto se a tela mostrar um desafio: aí devolve a página do desafio."""


class NavegadorInterativo(Navegador, Protocol):
    def atual(self) -> Pagina:
        """A página que está na tela, sem navegar."""

    def abrir_e_esperar(self, url: str, seletor: str, timeout_ms: int = 15_000) -> Pagina:
        """Abre a URL e espera um elemento de `seletor` aparecer (conteúdo carregado depois do load,
        como o painel de ofertas). Sem o elemento no prazo, devolve a página como estiver."""

    def clicar(self, seletor: str, indice: int, guarda: Guarda) -> Pagina:
        """Clica no `indice`-ésimo elemento de `seletor`. Antes, passa o HTML e o texto do próprio
        elemento a `guarda`, que levanta exceção para impedir o clique. Devolve a página depois do
        clique. Lança ErroRede se o elemento não existe ou o clique falha. Só
        `coletor_amazon.cliques` chama este método."""
```

- [ ] **Step 5: Chromium**

Em `src/tcg_sniper/navegador/chromium.py`: importe `Guarda` (`from tcg_sniper.navegador.base import Guarda`), acrescente a constante depois dos imports e os três métodos no fim da classe:

```python
# HTML do elemento e o texto que a guarda confere: texto visível, `value` e `aria-label`.
JS_DESCREVER = (
    "e => [e.outerHTML, [e.innerText || '', e.value || '', e.getAttribute('aria-label') || ''].join(' ')]"
)
```

```python
    def atual(self) -> Pagina:
        try:
            return self._capturar(0, {})
        except PlaywrightError as erro:
            raise ErroRede(f"página atual ilegível: {erro}") from erro

    def abrir_e_esperar(self, url: str, seletor: str, timeout_ms: int = 15_000) -> Pagina:
        pagina = self.abrir(url)
        try:
            self._pagina.wait_for_selector(seletor, state="attached", timeout=timeout_ms)
        except PlaywrightError:
            return pagina  # sem o elemento no prazo: quem chamou decide (o parser acusa o layout)
        self._pagina.wait_for_timeout(self._espera_ms)
        return self._capturar(pagina.status, pagina.headers)

    def clicar(self, seletor: str, indice: int, guarda: Guarda) -> Pagina:
        try:
            elemento = self._pagina.locator(seletor).nth(indice).element_handle(timeout=self._timeout_ms)
            html, texto = elemento.evaluate(JS_DESCREVER)
        except PlaywrightError as erro:
            raise ErroRede(f"elemento {seletor} [{indice}] não encontrado: {erro}") from erro
        # A guarda vê o mesmo nó (handle) que vai ser clicado: se a página trocou o botão depois da
        # leitura do HTML, é este que conta.
        guarda(html, texto)
        try:
            elemento.click(timeout=self._timeout_ms)
            self._pagina.wait_for_load_state("load", timeout=self._timeout_ms)
            self._pagina.wait_for_timeout(self._espera_ms)
            return self._capturar(0, {})
        except PlaywrightError as erro:
            raise ErroRede(f"clique em {seletor} [{indice}]: {erro}") from erro
```

- [ ] **Step 6: URLs no parser**

Em `src/tcg_sniper/coletor_amazon/parsers.py`, depois de `url_vendedor`:

```python
URL_CARRINHO = f"{BASE_AMAZON}/gp/cart/view.html"
# Blocos do painel "Outras opções de compra": a oferta em destaque e as demais (id repetido).
SELETOR_PAINEL_OFERTAS = "#aod-pinned-offer, #aod-offer"


def url_ofertas(asin: str) -> str:
    """Fragmento com todas as ofertas do ASIN (o painel "Outras opções de compra" carrega daqui)."""
    return f"{BASE_AMAZON}/gp/product/ajax/aodAjaxMain/ref=dp_aod_ALL_mbc?asin={asin}&pc=dp&experienceId=aodAjaxMain"


def url_painel_ofertas(asin: str) -> str:
    """Página do produto com o painel de ofertas aberto (onde fica o "Adicionar ao carrinho" de cada oferta)."""
    return f"{BASE_AMAZON}/dp/{asin}?aod=1"
```

- [ ] **Step 7: `cliques.py`**

Create `src/tcg_sniper/coletor_amazon/cliques.py`:

```python
"""Os únicos cliques que o coletor faz no site da Amazon (conferência de checkout e captura de
fixtures). Cada ação tem uma lista fixa de seletores e um padrão que o elemento tem de ter; a lista
proibida (confirmar/finalizar pedido, Comprar agora, 1-Clique) é conferida antes de todo clique, no
HTML lido e de novo no elemento que o navegador vai clicar. Nenhum outro módulo chama
`NavegadorInterativo.clicar` (teste em tests/coletor_amazon/test_cliques.py).

Os seletores são conferidos nas páginas reais salvas (tests/fixtures/amazon, Task 9 do plano
2026-10-17); o primeiro de cada lista é o visto na fixture, os demais cobrem variações de layout.
"""

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

from selectolax.lexbor import LexborHTMLParser, LexborNode

from tcg_sniper.coletor_amazon.parsers import URL_CARRINHO
from tcg_sniper.navegador.base import NavegadorInterativo
from tcg_sniper.navegador.modelos import Pagina

# Trechos (sem acento, minúsculos) que tornam um elemento proibido, no HTML dele ou no texto.
PROIBIDOS = (
    "placeorder",
    "placeyourorder",
    "submitorder",
    "place your order",
    "confirmar pedido",
    "confirmar o pedido",
    "finalizar pedido",
    "finalizar compra",
    "fazer pedido",
    "fazer o pedido",
    "comprar agora",
    "buy-now",
    "buynow",
    "buy now",
    "turbo-checkout",
    "1-clique",
    "1-click",
    "oneclick",
    "one-click",
)


class CliqueProibido(Exception):
    """O elemento a clicar é (ou parece) um botão de confirmar pedido ou de compra imediata, ou não
    é o botão da ação."""


class SeletorAusente(Exception):
    """Nenhum seletor da ação achou o botão na página (layout novo ou passo inesperado)."""


@dataclass(frozen=True)
class Acao:
    nome: str
    seletores: tuple[str, ...]
    padrao: re.Pattern[str]  # o HTML ou o texto do elemento (sem acento, minúsculo) tem de casar


ADICIONAR = Acao(
    "adicionar ao carrinho",
    ('input[name="submit.addToCart"]', '[data-action="aod-atc-action"] input', '.aod-atc-column input[type="submit"]'),
    re.compile(r"submit\.addtocart|adicionar ao carrinho|add to cart"),
)
FECHAR_PEDIDO = Acao(
    "fechar pedido",
    (
        'input[name="proceedToRetailCheckout"]',
        "#sc-buy-box-ptc-button input",
        '[data-feature-id="proceed-to-checkout-action"] input',
    ),
    re.compile(r"proceedtoretailcheckout|fechar pedido|proceed to checkout"),
)
ENTREGAR = Acao(
    "entregar neste endereço",
    (
        'input[data-testid="Address_selectShipToThisAddress"]',
        "#shipToThisAddressButton input",
        'input[aria-labelledby="shipToThisAddressButton-announce"]',
    ),
    re.compile(r"entregar neste endereco|shiptothisaddress"),
)
EXCLUIR = Acao(
    "excluir do carrinho",
    (
        'input[data-action="delete"]',
        'input[name^="submit.delete"]',
        '[data-feature-id="delete"] input',
        'input[value="Excluir"]',
    ),
    re.compile(r"submit\.delete|data-action=\"delete\"|excluir"),
)
ACOES = (ADICIONAR, FECHAR_PEDIDO, ENTREGAR, EXCLUIR)

# Onde ficam os itens do carrinho ativo; "Salvo para depois" fica fora destes blocos e nunca é tocado.
ESCOPOS_CARRINHO_ATIVO = ('[data-name="Active Items"]', "#sc-active-cart", "#activeCartViewForm")
# Painel de ofertas: a oferta em destaque (posição 0) e as demais, na ordem (posição 1 = 1º bloco).
ESCOPO_OFERTA_DESTAQUE = "#aod-pinned-offer"
ESCOPO_OFERTA_LISTA = "#aod-offer"


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sem_acento.lower())


def texto_do_elemento(no: LexborNode) -> str:
    """O que a guarda lê de um elemento além do HTML: texto visível, `value` e `aria-label`."""
    partes = (no.text(separator=" ", strip=True), no.attributes.get("value"), no.attributes.get("aria-label"))
    return " ".join(p for p in partes if p)


def conferir_clique(acao: Acao, html_elemento: str, texto: str) -> None:
    """Levanta CliqueProibido se o elemento tem um trecho proibido ou não é o botão da ação."""
    alvo = _normalizar(f"{html_elemento} {texto}")
    for trecho in PROIBIDOS:
        if trecho in alvo:
            raise CliqueProibido(f"{acao.nome}: elemento proibido ({trecho!r}): {html_elemento[:200]}")
    if not acao.padrao.search(alvo):
        raise CliqueProibido(f"{acao.nome}: o elemento não é o botão esperado: {html_elemento[:200]}")


def localizar(acao: Acao, pagina: Pagina, escopo: str = "", bloco: int = 0) -> tuple[str, int] | None:
    """O primeiro seletor da ação que acha o botão dentro do `bloco`-ésimo elemento de `escopo` (sem
    escopo: o primeiro botão da página). Devolve o seletor completo e o índice do botão entre todos
    os elementos desse seletor na página (o índice que o navegador usa)."""
    arvore = LexborHTMLParser(pagina.html)
    raiz = None
    if escopo:
        blocos = arvore.css(escopo)
        if len(blocos) <= bloco:
            return None
        raiz = blocos[bloco]
    for seletor in acao.seletores:
        completo = f"{escopo} {seletor}".strip()
        todos = arvore.css(completo)
        if raiz is None:
            if todos:
                return completo, 0
            continue
        dentro = {no.mem_id for no in raiz.css(seletor)}
        for indice, no in enumerate(todos):
            if no.mem_id in dentro:
                return completo, indice
    return None


def clicar_permitido(
    nav: NavegadorInterativo, acao: Acao, pagina: Pagina, escopo: str = "", bloco: int = 0
) -> Pagina:
    """Confere o botão no HTML de `pagina` e clica nele pelo navegador, que confere de novo no próprio
    elemento antes do clique. Lança SeletorAusente ou CliqueProibido sem clicar."""
    achado = localizar(acao, pagina, escopo, bloco)
    if achado is None:
        raise SeletorAusente(f"{acao.nome}: botão não encontrado em {pagina.url}")
    seletor, indice = achado
    no = LexborHTMLParser(pagina.html).css(seletor)[indice]
    conferir_clique(acao, no.html or "", texto_do_elemento(no))
    return nav.clicar(seletor, indice, lambda html, texto: conferir_clique(acao, html, texto))


def _escopo_do_item(ativo: str, asin: str) -> str:
    return f'{ativo} [data-asin="{asin}"]'


def asin_no_carrinho_ativo(pagina: Pagina, asin: str) -> bool:
    arvore = LexborHTMLParser(pagina.html)
    return any(arvore.css_first(_escopo_do_item(ativo, asin)) is not None for ativo in ESCOPOS_CARRINHO_ATIVO)


def remover_do_carrinho(
    nav: NavegadorInterativo, asin: str, abrir: Callable[[str], Pagina], pausar: Callable[[], None]
) -> tuple[bool, int]:
    """Exclui o ASIN do carrinho ativo (nunca de "Salvo para depois"). Devolve (removido, páginas
    abertas); removido é True também quando o item já não estava no carrinho ativo."""
    carrinho = abrir(URL_CARRINHO)
    for ativo in ESCOPOS_CARRINHO_ATIVO:
        escopo = _escopo_do_item(ativo, asin)
        if localizar(EXCLUIR, carrinho, escopo) is None:
            continue
        pausar()
        clicar_permitido(nav, EXCLUIR, carrinho, escopo)
        conferido = abrir(URL_CARRINHO)  # o clique pode só esconder o item por JS: confere recarregando
        return not asin_no_carrinho_ativo(conferido, asin), 3
    return not asin_no_carrinho_ativo(carrinho, asin), 1
```

- [ ] **Step 8: Navegador falso interativo**

No topo de `tests/fakes.py` acrescente `from selectolax.lexbor import LexborHTMLParser` e `from tcg_sniper.navegador.modelos import ErroRede`; no fim:

```python
class NavegadorInterativoFake(NavegadorFake):
    """NavegadorFake que também clica, como o Chromium: acha o elemento no HTML da página atual
    (selectolax) e passa HTML e texto à guarda antes de registrar o clique. `apos_clique` diz a página
    seguinte: uma lista (cada clique consome a próxima) ou um dict {trecho do seletor: Pagina | lista}."""

    def __init__(self, paginas, apos_clique=None):
        super().__init__(paginas)
        self.apos_clique = apos_clique if apos_clique is not None else []
        self.cliques: list[tuple[str, int]] = []
        self.esperas: list[tuple[str, str]] = []
        self._atual = None

    def abrir(self, url):
        self._atual = super().abrir(url)
        return self._atual

    def abrir_e_esperar(self, url, seletor, timeout_ms=15_000):
        self.esperas.append((url, seletor))
        return self.abrir(url)

    def atual(self):
        return self._atual

    def _seguinte(self, seletor):
        if isinstance(self.apos_clique, list):
            resposta = self.apos_clique.pop(0)
        else:
            chave = next((trecho for trecho in self.apos_clique if trecho in seletor), None)
            if chave is None:
                raise AssertionError(f"clique sem página seguinte no teste: {seletor}")
            resposta = self.apos_clique[chave]
            if isinstance(resposta, list):
                resposta = resposta.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    def clicar(self, seletor, indice, guarda):
        from tcg_sniper.coletor_amazon.cliques import texto_do_elemento

        nos = LexborHTMLParser(self._atual.html).css(seletor) if self._atual is not None else []
        if len(nos) <= indice:
            raise ErroRede(f"elemento {seletor} [{indice}] não encontrado")
        no = nos[indice]
        guarda(no.html or "", texto_do_elemento(no))
        self.cliques.append((seletor, indice))
        self._atual = self._seguinte(seletor)
        return self._atual
```

(O nome do método no fake é `clicar`, mas a chamada `.clicar(` só existe em `cliques.py`: o teste `test_so_cliques_py_chama_clicar_do_navegador` varre só `src/`.)

- [ ] **Step 9: Rodar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t1 uv run pytest -q && uv run ruff check .`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add src/tcg_sniper/navegador/base.py src/tcg_sniper/navegador/chromium.py src/tcg_sniper/coletor_amazon/parsers.py src/tcg_sniper/coletor_amazon/cliques.py tests/fakes.py tests/coletor_amazon/test_cliques.py tests/navegador/test_chromium.py
git commit -m "feat: guarded clicks on Amazon (allow-list, forbidden list checked on the element before every click)"
```

---

### Task 2: Anonimização das páginas reais e teste de privacidade

**Files:**
- Create: `src/tcg_sniper/coletor_amazon/anonimizar.py`
- Create: `scripts/anonimizar_fixture.py`
- Test: `tests/coletor_amazon/test_anonimizar.py` (novo), `tests/test_fixtures_privacidade.py` (novo)

**Interfaces:**
- Produces:
  - `anonimizar.BLOCOS: dict[str, tuple[str, ...] | None]` com as chaves `ofertas`, `painel`, `carrinho`, `checkout`, `login`.
  - `anonimizar.FICTICIOS: dict[str, str]`.
  - `anonimizar.limpar(html: str, blocos: Sequence[str] | None = None) -> str` (levanta `ValueError` se `blocos` não acha nada).
  - `anonimizar.anonimizar(html: str, proibidos: Sequence[str] = ()) -> str`.
  - `anonimizar.achados(html: str, proibidos: Sequence[str] = ()) -> list[str]` (tipo e posição; nunca o valor).
  - `anonimizar.ler_proibidos(caminho: Path) -> list[str]` (`[]` sem o arquivo).
  - Script: `uv run python scripts/anonimizar_fixture.py <tipo> <origem.html> <destino.html> [--proibidos ARQ]`.

- [ ] **Step 1: Testes (falham)**

Create `tests/coletor_amazon/test_anonimizar.py`:

```python
import pytest

from tcg_sniper.coletor_amazon.anonimizar import achados, anonimizar, ler_proibidos, limpar

PAGINA = """<html><head><title>Finalizar pedido</title><script>var cpf = "123.456.789-09";</script>
<style>.x{}</style><meta name="x" content="y"></head>
<body><!-- comentário com 01310-100 -->
<div id="endereco" data-json='{"nome":"Maria Souza"}'>Entregar para Maria Souza, Rua das Flores 123, 01310-100, São Paulo</div>
<div>CPF: ***.456.789-** · Telefone (11) 98765-4321 · maria.souza@gmail.com</div>
<input type="hidden" name="anti-csrftoken-a2z" value="segredo-de-sessao">
<input type="submit" name="placeYourOrder1" value="Confirmar pedido com cartão 1234">
<span>Pagando com Visa terminado em 1234</span>
<div>Pedido 702-1234567-1234567</div>
<a href="/gp/aag/main?ie=UTF8&seller=A2SHZ&isAmazonFulfilled=1">Shazaar</a>
<a href="https://www.amazon.com.br/dp/B0DNV55QBS/ref=xyz?th=1">produto</a>
<a href="/checkout/p/p-123-456/address?pipelineType=Chewbacca">voltar</a>
<img src="x.png"><svg></svg>
</body></html>"""
PROIBIDOS = ["Maria Souza", "Rua das Flores 123"]


def test_limpar_tira_scripts_comentarios_atributos_e_tokens():
    html = limpar(PAGINA)
    for trecho in ("<script", "<style", "<img", "<svg", 'content="y"', "comentário", "data-json", "segredo-de-sessao", "pipelineType"):
        assert trecho not in html
    assert 'href="/gp/aag/main?seller=A2SHZ"' in html
    assert 'href="/dp/B0DNV55QBS"' in html
    assert 'name="placeYourOrder1"' in html  # o botão proibido fica: os testes provam que nunca é clicado
    assert "<title>Finalizar pedido</title>" in html


def test_anonimizar_troca_os_dados_pessoais_por_ficticios():
    html = anonimizar(limpar(PAGINA), PROIBIDOS)
    for real in ("Maria Souza", "Rua das Flores 123", "01310-100", "***.456.789-**", "98765-4321",
                 "maria.souza@gmail.com", "1234", "702-1234567-1234567"):
        assert real not in html
    for ficticio in ("Fulano de Tal", "01001-000", "000.000.000-00", "(11) 90000-0000", "fulano@exemplo.com",
                     "cartão 0000", "terminado em 0000", "000-0000000-0000000"):
        assert ficticio in html


def test_achados_apontam_o_que_sobrou_sem_mostrar_o_valor():
    problemas = achados(limpar(PAGINA), PROIBIDOS)
    for tipo in ("CPF", "CEP", "cartão", "e-mail", "telefone", "pedido", "texto proibido"):
        assert any(p.startswith(tipo) for p in problemas), tipo
    assert not any("1234" in p or "Maria" in p or "01310" in p for p in problemas)
    assert achados(anonimizar(limpar(PAGINA), PROIBIDOS), PROIBIDOS) == []


def test_limpar_so_os_blocos_pedidos_sem_repetir_os_aninhados():
    html = limpar('<html><body><div id="a"><div id="b">dentro</div></div><div id="c">fora</div></body></html>', ("#b", "#a"))
    assert html.count("dentro") == 1 and "fora" not in html


def test_limpar_sem_nenhum_bloco_recusa():
    with pytest.raises(ValueError, match="nenhum dos blocos"):
        limpar("<html><body><p>x</p></body></html>", ("#nada",))


def test_ler_proibidos(tmp_path):
    arquivo = tmp_path / "proibidos.txt"
    arquivo.write_text("# comentário\nMaria Souza\n\n  1234 \n", encoding="utf-8")
    assert ler_proibidos(arquivo) == ["Maria Souza", "1234"]
    assert ler_proibidos(tmp_path / "nao-existe.txt") == []
```

Create `tests/test_fixtures_privacidade.py`:

```python
"""Nenhuma fixture da Amazon pode ter dado pessoal (o repositório é público). Os padrões genéricos
valem sempre; os textos reais (nome, rua, telefone...) vêm de .fixtures-brutas/proibidos.txt, que só
existe na máquina que fez a captura."""

from pathlib import Path

import pytest

from tcg_sniper.coletor_amazon.anonimizar import achados, ler_proibidos

RAIZ = Path(__file__).parent.parent
FIXTURES = sorted((RAIZ / "tests" / "fixtures" / "amazon").glob("*.html"))
PROIBIDOS = ler_proibidos(RAIZ / ".fixtures-brutas" / "proibidos.txt")


@pytest.mark.parametrize("caminho", FIXTURES, ids=lambda p: p.name)
def test_fixture_sem_dado_pessoal(caminho):
    assert achados(caminho.read_text(encoding="utf-8"), PROIBIDOS) == []
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t2 uv run pytest tests/coletor_amazon/test_anonimizar.py tests/test_fixtures_privacidade.py -q`
Expected: FAIL (ImportError: `anonimizar`).

- [ ] **Step 3: Implementação**

Create `src/tcg_sniper/coletor_amazon/anonimizar.py`:

```python
"""Limpa e anonimiza páginas reais da Amazon antes de virarem fixture (o repositório é público).

`limpar` tira scripts, estilos, imagens, comentários e todo atributo fora de uma lista curta (sem
`data-*` com JSON, sem valor de campo oculto, links reduzidos a /dp/<ASIN> ou seller=<ID>);
`anonimizar` troca CPF, CEP, final de cartão, e-mail, telefone, número de pedido e os textos de
`proibidos` por valores fictícios; `achados` lista o que ainda parece dado pessoal (o script e o
teste de privacidade usam)."""

import re
from collections.abc import Sequence
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

TAGS_REMOVIDAS = ["script", "style", "link", "noscript", "img", "svg", "iframe", "template", "meta"]
ATRIBUTOS_MANTIDOS = frozenset(
    {
        "id", "class", "name", "type", "value", "role", "aria-label", "aria-labelledby", "href",
        "data-asin", "data-name", "data-action", "data-itemtype", "data-testid", "data-feature-id",
    }
)

# Blocos mantidos por tipo de página (None: o corpo inteiro). O painel guarda também os botões da
# página do produto ("Comprar agora" inclusive), para os testes provarem que nunca são clicados.
BLOCOS: dict[str, tuple[str, ...] | None] = {
    "ofertas": None,
    "painel": ("#aod-pinned-offer", "#aod-offer-list", "#aod-offer", "#buy-now-button", "#add-to-cart-button"),
    "carrinho": (
        "#nav-cart-count", '[data-name="Active Items"]', "#sc-active-cart", "#activeCartViewForm",
        '[data-name="Subtotals"]', "#sc-buy-box", '[data-name="Saved Items"]', "#sc-saved-cart",
    ),
    "checkout": None,
    "login": None,
}

FICTICIOS = {
    "cpf": "000.000.000-00",
    "cep": "01001-000",
    "cartao": "0000",
    "email": "fulano@exemplo.com",
    "telefone": "(11) 90000-0000",
    "pedido": "000-0000000-0000000",
    "texto": "Fulano de Tal",
}

_RE_CPF = re.compile(r"(?<![\d*])[\d*]{3}\.[\d*]{3}\.[\d*]{3}-[\d*]{2}(?![\d*])")
_RE_CEP = re.compile(r"(?<!\d)\d{5}-\d{3}(?!\d)")
_RE_CARTAO = re.compile(r"(?i)(cart[aã]o|final|terminad[oa] em|termina em|ending in)([^\d<]{0,25}?)(\d{4})(?!\d)")
_RE_EMAIL = re.compile(r"[\w.+-]+@(?!amazon\.)[\w-]+(?:\.[\w-]+)+")
_RE_TELEFONE = re.compile(r"\(?(?<!\d)\d{2}\)?\s?9\d{4}-?\d{4}(?!\d)")
_RE_PEDIDO = re.compile(r"(?<!\d)\d{3}-\d{7}-\d{7}(?!\d)")
_RE_ASIN = re.compile(r"/dp/([A-Z0-9]{10})")


def ler_proibidos(caminho: Path) -> list[str]:
    """Um texto real por linha (linhas vazias e com # são ignoradas); sem o arquivo, lista vazia."""
    if not caminho.exists():
        return []
    linhas = (linha.strip() for linha in caminho.read_text(encoding="utf-8").splitlines())
    return [linha for linha in linhas if linha and not linha.startswith("#")]


def _href_seguro(href: str) -> str:
    """Só o que os parsers usam: o vendedor (seller=<ID>) ou o produto (/dp/<ASIN>); o resto vira "#"."""
    vendedor = parse_qs(urlsplit(href).query).get("seller")
    if vendedor:
        return f"/gp/aag/main?seller={vendedor[0]}"
    achado = _RE_ASIN.search(href)
    return f"/dp/{achado.group(1)}" if achado else "#"


def _filtrar_atributos(no: LexborNode) -> None:
    for nome in list(no.attributes):
        if nome not in ATRIBUTOS_MANTIDOS:
            del no.attrs[nome]
    if (no.attributes.get("type") or "").lower() == "hidden" and "value" in no.attributes:
        del no.attrs["value"]  # campos ocultos levam tokens de sessão e ids de pedido
    href = no.attributes.get("href")
    if href is not None:
        no.attrs["href"] = _href_seguro(href)


def _sem_aninhados(nos: list[LexborNode]) -> list[LexborNode]:
    """Tira repetidos e os que estão dentro de outro bloco escolhido (senão o trecho sai duas vezes)."""
    ids = {no.mem_id for no in nos}
    vistos: set[int] = set()
    escolhidos = []
    for no in nos:
        if no.mem_id in vistos:
            continue
        vistos.add(no.mem_id)
        pai = no.parent
        while pai is not None and pai.mem_id not in ids:
            pai = pai.parent
        if pai is None:
            escolhidos.append(no)
    return escolhidos


def limpar(html: str, blocos: Sequence[str] | None = None) -> str:
    arvore = LexborHTMLParser(re.sub(r"<!--.*?-->", "", html, flags=re.S))
    titulo = arvore.css_first("title")
    texto_titulo = titulo.text(strip=True) if titulo is not None else ""
    arvore.strip_tags(TAGS_REMOVIDAS)
    if blocos is None:
        raizes = [arvore.body] if arvore.body is not None else []
    else:
        raizes = _sem_aninhados([no for seletor in blocos for no in arvore.css(seletor)])
        if not raizes:
            raise ValueError(f"nenhum dos blocos {list(blocos)} foi encontrado na página")
    partes = []
    for raiz in raizes:
        for no in raiz.traverse(include_text=False):
            _filtrar_atributos(no)
        partes.append((raiz.html or "").removeprefix("<body>").removesuffix("</body>"))
    corpo = re.sub(r"\s+", " ", "\n".join(partes)).replace("> <", ">\n<")
    return (
        '<!DOCTYPE html>\n<html><head><meta charset="utf-8">'
        f"<title>{escape(texto_titulo)}</title></head>\n"
        "<!-- Página real limpa e anonimizada (src/tcg_sniper/coletor_amazon/anonimizar.py). -->\n"
        f"<body>\n{corpo}\n</body></html>\n"
    )


def anonimizar(html: str, proibidos: Sequence[str] = ()) -> str:
    texto = html
    for valor in sorted({p.strip() for p in proibidos if p.strip()}, key=len, reverse=True):
        texto = re.sub(re.escape(valor), FICTICIOS["texto"], texto, flags=re.IGNORECASE)
    texto = _RE_CPF.sub(FICTICIOS["cpf"], texto)
    texto = _RE_PEDIDO.sub(FICTICIOS["pedido"], texto)  # antes do CEP: o número do pedido tem traços
    texto = _RE_CEP.sub(FICTICIOS["cep"], texto)
    texto = _RE_EMAIL.sub(FICTICIOS["email"], texto)
    texto = _RE_TELEFONE.sub(FICTICIOS["telefone"], texto)
    return _RE_CARTAO.sub(lambda m: f"{m.group(1)}{m.group(2)}{FICTICIOS['cartao']}", texto)


def achados(html: str, proibidos: Sequence[str] = ()) -> list[str]:
    """O que ainda parece dado pessoal: tipo e posição (nunca o valor, que iria parar no log do teste)."""
    problemas = []
    baixo = html.lower()
    for valor in sorted({p.strip() for p in proibidos if p.strip()}):
        posicao = baixo.find(valor.lower())
        if posicao >= 0:
            problemas.append(f"texto proibido na posição {posicao}")
    genericos = (
        ("CPF", _RE_CPF, FICTICIOS["cpf"]),
        ("CEP", _RE_CEP, FICTICIOS["cep"]),
        ("e-mail", _RE_EMAIL, FICTICIOS["email"]),
        ("telefone", _RE_TELEFONE, FICTICIOS["telefone"]),
        ("pedido", _RE_PEDIDO, FICTICIOS["pedido"]),
    )
    for tipo, regex, ficticio in genericos:
        problemas += [f"{tipo} na posição {m.start()}" for m in regex.finditer(html) if m.group(0) != ficticio]
    problemas += [
        f"cartão na posição {m.start()}" for m in _RE_CARTAO.finditer(html) if m.group(3) != FICTICIOS["cartao"]
    ]
    return problemas
```

Create `scripts/anonimizar_fixture.py`:

```python
"""Limpa e anonimiza uma página real da Amazon e grava como fixture.

Uso:
  uv run python scripts/anonimizar_fixture.py <tipo> <origem.html> <destino.html> [--proibidos ARQ]

<tipo>: ofertas | painel | carrinho | checkout | login (define os blocos mantidos; ver BLOCOS em
src/tcg_sniper/coletor_amazon/anonimizar.py). --proibidos (padrão .fixtures-brutas/proibidos.txt,
fora do git): um texto real por linha (nome, rua, bairro, telefone...). Não grava se, depois de
anonimizar, ainda sobrar algo com cara de dado pessoal.
"""

import argparse
import sys
from pathlib import Path

from tcg_sniper.coletor_amazon.anonimizar import BLOCOS, achados, anonimizar, ler_proibidos, limpar


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tipo", choices=sorted(BLOCOS))
    parser.add_argument("origem", type=Path)
    parser.add_argument("destino", type=Path)
    parser.add_argument("--proibidos", type=Path, default=Path(".fixtures-brutas/proibidos.txt"))
    args = parser.parse_args()
    proibidos = ler_proibidos(args.proibidos)
    if not proibidos:
        print(f"aviso: {args.proibidos} vazio ou ausente; só os padrões genéricos serão trocados")
    original = args.origem.read_text(encoding="utf-8")
    try:
        limpo = limpar(original, BLOCOS[args.tipo])
    except ValueError as erro:
        sys.exit(f"{args.origem}: {erro}")
    final = anonimizar(limpo, proibidos)
    problemas = achados(final, proibidos)
    if problemas:
        sys.exit(f"{args.origem}: ainda há dado pessoal ({'; '.join(problemas)}); nada gravado")
    args.destino.write_text(final, encoding="utf-8")
    print(f"{args.destino}: {len(original):,} -> {len(final):,} bytes")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rodar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t2 uv run pytest -q && uv run ruff check .`
Expected: PASS (as fixtures atuais da Amazon já passam no teste de privacidade).

- [ ] **Step 5: Commit**

```bash
git add src/tcg_sniper/coletor_amazon/anonimizar.py scripts/anonimizar_fixture.py tests/coletor_amazon/test_anonimizar.py tests/test_fixtures_privacidade.py
git commit -m "feat: clean and anonymize real Amazon pages for fixtures, privacy test over all Amazon fixtures"
```

---

### Task 3: Modelos, migração, repositório e configuração

**Files:**
- Modify: `src/tcg_sniper/db/models.py`
- Create: `src/tcg_sniper/db/migrations/versions/b9e4c2a7d3f5_monitor_amazon.py`
- Modify: `src/tcg_sniper/coletor_amazon/modelos.py` (`OfertaLista`)
- Modify: `src/tcg_sniper/db/repositorio_amazon.py`
- Modify: `src/tcg_sniper/coletor_amazon/config.py` (campos novos do formulário)
- Modify: `tests/fakes.py` (acrescenta `oferta_lista` no fim)
- Test: `tests/db/test_repositorio_monitor.py` (novo); `tests/db/test_migracao.py`, `tests/coletor_amazon/test_config_amazon.py` (acrescenta); `tests/admin/test_admin_config_tela.py` e `tests/admin/test_admin_amazon.py` (formulários com os campos novos)

**Interfaces:**
- Produces:
  - `models.OrigemPreco.OFERTAS`; `models.OrigemCasamento` (`MANUAL`, `SUGERIDO_IA`, `AUTOMATICO_IA`); `models.SituacaoCheckout` (`OK`, `FALHA`, `CARRINHO_OCUPADO`, `SEM_LOGIN`).
  - `AnuncioAmazon.origem_casamento: OrigemCasamento | None`.
  - `models.OfertaAmazon` (id, anuncio_id, lida_em, vendedor_id, vendedor_nome, preco, preco_de, condicao, envio, origem_envio, importada, prime, elegivel, melhor); `models.ConferenciaCheckout` (id, em, anuncio_id, vendedor_nome, preco_anunciado, itens, frete, impostos, total, situacao, motivo, item_removido).
  - `ConfigAmazon`: `monitor_janela_inicio`, `monitor_janela_fim`, `monitor_intervalo_min`, `monitor_max_paginas_hora`, `margem_candidata_pp`, `checkout_validade_h`, `descoberta_casados_dias`, `monitor_ligado`, `checkout_ligado`, `checkout_sem_login_em`.
  - `coletor_amazon.modelos.OfertaLista(posicao, vendedor_nome, seller_id, preco, preco_de, condicao, envio, origem_envio, importada, prime, pct_positivas, num_avaliacoes, cupom)`.
  - `repositorio_amazon`: `TITULO_MANUAL`; `OfertaAvaliada(oferta, vendedor_id, elegivel, melhor)`; `gravar_ofertas(s, anuncio_id, lida_em, ofertas) -> None`; `ofertas_da_ultima_leitura(s, anuncio_ids) -> dict[int, list[OfertaAmazon]]` (mais barata primeiro); `limpar_ofertas_antigas(s, agora, dias=30) -> int`; `marcar_visto(s, anuncio_id, agora) -> None`; `proximo_do_monitor(s, agora, intervalo_min, excluir=()) -> tuple[int, str] | None`; `SituacaoMonitor(confirmados, nunca_lidos, vencidos, mais_antiga, ultima)`; `situacao_monitor(s, agora, intervalo_min) -> SituacaoMonitor`; `ids_na_fila(s, agora=None, casados_dias=None) -> set[int]`; `proximo_da_fila(s, agora, casados_dias=None) -> FilaAmazon | None`; `registrar_conferencia(s, *, em, anuncio_id, vendedor_nome, preco_anunciado, itens, frete, impostos, total, situacao, motivo, item_removido) -> ConferenciaCheckout`; `conferencia_valida(s, anuncio_id, vendedor_nome, preco_anunciado, agora, validade_h) -> ConferenciaCheckout | None`; `ultima_conferencia(s, anuncio_id=None) -> ConferenciaCheckout | None`; `conferencias_com_item_no_carrinho(s) -> list[tuple[int, str]]` (id da conferência, ASIN); `marcar_item_removido(s, conferencia_id) -> None`; `CandidataCheckout(anuncio_id, asin, vendedor_nome, preco_anunciado)`; `candidatas_ao_checkout(s, agora, cfg) -> list[CandidataCheckout]` (maior desconto primeiro).
  - `registrar_preco` com origem `OFERTAS` grava vendedor/envio como a de `PRODUTO`; com origem `BUSCA` não troca o preço atual de um anúncio cuja última leitura é `OFERTAS`.
  - `coletor_amazon.config.CAMPOS` com os 7 campos novos no fim; `validar_config` valida as duas horas do monitor (início antes do fim).
  - `fakes.oferta_lista(preco="275.91", vendedor="Shazaar", seller_id="A2SHZ", envio=Envio.FBA, posicao=1, **campos) -> OfertaLista`.

- [ ] **Step 1: Testes do repositório (falham)**

Create `tests/db/test_repositorio_monitor.py`:

```python
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto, oferta_lista

from tcg_sniper.db import repositorio_amazon as repo
from tcg_sniper.db.models import Envio, OfertaAmazon, OrigemPreco, PrecoAtualAmazon, SituacaoCheckout, StatusCasamento

SP = ZoneInfo("America/Sao_Paulo")


def confirmado(s, asin, liga="1000.00", listagem_em=T0, ativo=True):
    produto = criar_produto(s, f"p-{asin}", ativo=ativo)
    criar_preco_liga(s, produto, liga, listagem_em=listagem_em)
    return criar_anuncio(s, asin, produto=produto, status=StatusCasamento.CONFIRMADO)


def ler(s, anuncio, quando, *ofertas):
    """Uma leitura do monitor: as ofertas (a primeira é a melhor, todas elegíveis) e o preço atual."""
    repo.gravar_ofertas(s, anuncio.id, quando, [repo.OfertaAvaliada(o, None, True, i == 0) for i, o in enumerate(ofertas)])
    melhor = ofertas[0] if ofertas else None
    repo.registrar_preco(
        s, anuncio.id, melhor.preco if melhor else None, OrigemPreco.OFERTAS, None,
        melhor.envio if melhor else Envio.DESCONHECIDO, quando, SP,
    )


def conferencia(s, anuncio, quando, situacao=SituacaoCheckout.OK, vendedor="Shazaar", preco="275.91", total="285.99", removido=True):
    tem_total = total is not None
    return repo.registrar_conferencia(
        s, em=quando, anuncio_id=anuncio.id, vendedor_nome=vendedor, preco_anunciado=Decimal(preco),
        itens=Decimal("237.73") if tem_total else None, frete=Decimal("0.00") if tem_total else None,
        impostos=Decimal("48.26") if tem_total else None, total=Decimal(total) if tem_total else None,
        situacao=situacao, motivo=None if situacao is SituacaoCheckout.OK else "motivo", item_removido=removido,
    )


def test_gravar_ofertas_e_ler_so_a_ultima_leitura(s):
    a = confirmado(s, "B0MON00001")
    ler(s, a, T0 - timedelta(minutes=20), oferta_lista("300.00"))
    ler(
        s, a, T0,
        oferta_lista("275.91"),
        oferta_lista("314.11", vendedor="Amazon.com.br", seller_id="amazon", envio=Envio.AMAZON, posicao=0,
                     importada=True, origem_envio="Estados Unidos", prime=True),
    )
    ultimas = repo.ofertas_da_ultima_leitura(s, [a.id])[a.id]
    assert [(o.vendedor_nome, o.preco, o.melhor) for o in ultimas] == [
        ("Shazaar", Decimal("275.91"), True), ("Amazon.com.br", Decimal("314.11"), False),
    ]
    assert ultimas[1].importada and ultimas[1].prime and ultimas[1].origem_envio == "Estados Unidos"
    assert repo.ofertas_da_ultima_leitura(s, []) == {}


def test_limpar_ofertas_com_mais_de_30_dias(s):
    a = confirmado(s, "B0MON00001")
    ler(s, a, T0 - timedelta(days=31), oferta_lista())
    ler(s, a, T0, oferta_lista())
    assert repo.limpar_ofertas_antigas(s, T0) == 1
    assert s.query(OfertaAmazon).count() == 1


def test_proximo_do_monitor_nunca_lido_primeiro_depois_o_mais_antigo(s):
    nunca = confirmado(s, "B0MON00001")
    velho = confirmado(s, "B0MON00002")
    novo = confirmado(s, "B0MON00003")
    confirmado(s, "B0MON00004", ativo=False)  # produto desativado na Liga: fora do monitor
    criar_anuncio(s, "B0MON00005", produto=criar_produto(s, "pendente"))  # pendente: fora
    repo.registrar_preco(s, nunca.id, Decimal("10.00"), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, T0, SP)
    ler(s, velho, T0 - timedelta(minutes=40), oferta_lista())
    ler(s, novo, T0 - timedelta(minutes=5), oferta_lista())
    assert repo.proximo_do_monitor(s, T0, 15) == (nunca.id, "B0MON00001")
    assert repo.proximo_do_monitor(s, T0, 15, excluir={nunca.id}) == (velho.id, "B0MON00002")
    assert repo.proximo_do_monitor(s, T0, 15, excluir={nunca.id, velho.id}) is None


def test_situacao_do_monitor(s):
    confirmado(s, "B0MON00001")
    velho = confirmado(s, "B0MON00002")
    novo = confirmado(s, "B0MON00003")
    ler(s, velho, T0 - timedelta(minutes=40), oferta_lista())
    ler(s, novo, T0 - timedelta(minutes=5), oferta_lista())
    assert repo.situacao_monitor(s, T0, 15) == repo.SituacaoMonitor(
        confirmados=3, nunca_lidos=1, vencidos=2, mais_antiga=T0 - timedelta(minutes=40), ultima=T0 - timedelta(minutes=5)
    )


def test_busca_nao_sobrescreve_o_preco_lido_nas_ofertas(s):
    a = confirmado(s, "B0MON00001")
    ler(s, a, T0, oferta_lista("700.00", vendedor="Amazon.com.br", seller_id="amazon", envio=Envio.AMAZON, posicao=0))
    gravou = repo.registrar_preco(
        s, a.id, Decimal("650.00"), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, T0 + timedelta(minutes=1), SP
    )
    atual = s.get(PrecoAtualAmazon, a.id, populate_existing=True)
    assert gravou  # vai para o histórico
    assert (atual.preco, atual.origem, atual.envio) == (Decimal("700.00"), OrigemPreco.OFERTAS, Envio.AMAZON)


def test_ofertas_gravam_vendedor_e_envio_no_preco_atual(s):
    a = confirmado(s, "B0MON00001")
    amazon = repo.vendedor_da_amazon(s)
    repo.registrar_preco(s, a.id, Decimal("700.00"), OrigemPreco.OFERTAS, amazon.id, Envio.AMAZON, T0, SP)
    assert repo.registrar_preco(s, a.id, Decimal("700.00"), OrigemPreco.OFERTAS, None, Envio.FBA, T0 + timedelta(minutes=15), SP)
    atual = s.get(PrecoAtualAmazon, a.id, populate_existing=True)
    assert (atual.vendedor_id, atual.envio, atual.origem) == (None, Envio.FBA, OrigemPreco.OFERTAS)


def test_marcar_visto(s):
    a = confirmado(s, "B0MON00001")
    repo.marcar_visto(s, a.id, T0 + timedelta(hours=3))
    s.refresh(a)
    assert a.visto_ultimo_em == T0 + timedelta(hours=3)


def test_descoberta_pula_casados_ate_a_busca_semanal(s):
    livre = criar_produto(s, "livre")
    casado = criar_produto(s, "casado")
    velho = criar_produto(s, "velho")
    nunca_buscado = criar_produto(s, "nunca")
    for produto, asin in ((casado, "B0CAS00001"), (velho, "B0CAS00002"), (nunca_buscado, "B0CAS00003")):
        criar_anuncio(s, asin, produto=produto, status=StatusCasamento.CONFIRMADO)
    repo.sincronizar_fila(s, T0 - timedelta(days=10))
    repo.reagendar(s, livre.id, T0 - timedelta(hours=2), T0 - timedelta(hours=1), False)
    repo.reagendar(s, casado.id, T0 - timedelta(days=2), T0 - timedelta(days=1), False)
    repo.reagendar(s, velho.id, T0 - timedelta(days=7), T0 - timedelta(days=6), False)
    assert repo.ids_na_fila(s, T0, 7) == {livre.id, velho.id, nunca_buscado.id}
    assert repo.ids_na_fila(s) == {livre.id, casado.id, velho.id, nunca_buscado.id}
    assert repo.proximo_da_fila(s, T0, 7).produto_id == nunca_buscado.id  # vencido desde a entrada na fila
    repo.reagendar(s, nunca_buscado.id, T0, T0 + timedelta(days=7), False)
    assert repo.proximo_da_fila(s, T0, 7).produto_id == velho.id
    repo.reagendar(s, velho.id, T0, T0 + timedelta(days=7), False)
    assert repo.proximo_da_fila(s, T0, 7).produto_id == livre.id
    assert repo.proximo_da_fila(s, T0).produto_id == casado.id  # sem o filtro, como antes


def test_conferencia_valida_pela_mesma_oferta_dentro_da_validade(s):
    a = confirmado(s, "B0MON00001")
    ok = conferencia(s, a, T0 - timedelta(hours=5))
    assert repo.conferencia_valida(s, a.id, "Shazaar", Decimal("275.91"), T0, 6).id == ok.id
    assert repo.conferencia_valida(s, a.id, "Outra loja", Decimal("275.91"), T0, 6) is None
    assert repo.conferencia_valida(s, a.id, "Shazaar", Decimal("270.00"), T0, 6) is None
    assert repo.conferencia_valida(s, a.id, "Shazaar", Decimal("275.91"), T0 + timedelta(hours=2), 6) is None
    conferencia(s, a, T0, SituacaoCheckout.FALHA, total=None)
    assert repo.conferencia_valida(s, a.id, "Shazaar", Decimal("275.91"), T0, 6).id == ok.id
    assert repo.ultima_conferencia(s, a.id).situacao is SituacaoCheckout.FALHA
    assert repo.ultima_conferencia(s).situacao is SituacaoCheckout.FALHA


def test_candidatas_ao_checkout(s):
    cfg = repo.obter_config(s)  # desconto mínimo 25%, margem 5 pontos: candidata a partir de 20%
    boa = confirmado(s, "B0CAN00001")
    no_limite = confirmado(s, "B0CAN00002")
    cara = confirmado(s, "B0CAN00003")
    inelegivel = confirmado(s, "B0CAN00004")
    ja_conferida = confirmado(s, "B0CAN00005")
    liga_velha = confirmado(s, "B0CAN00006", listagem_em=T0 - timedelta(hours=49))
    ler(s, boa, T0, oferta_lista("700.00"))
    ler(s, no_limite, T0, oferta_lista("800.00"))
    ler(s, cara, T0, oferta_lista("800.01"))
    repo.gravar_ofertas(s, inelegivel.id, T0, [repo.OfertaAvaliada(oferta_lista("500.00"), None, False, True)])
    ler(s, ja_conferida, T0, oferta_lista("700.00"))
    conferencia(s, ja_conferida, T0 - timedelta(hours=1), preco="700.00", total="720.00")
    ler(s, liga_velha, T0, oferta_lista("500.00"))
    candidatas = repo.candidatas_ao_checkout(s, T0, cfg)
    assert [c.asin for c in candidatas] == ["B0CAN00001", "B0CAN00002"]
    assert candidatas[0] == repo.CandidataCheckout(boa.id, "B0CAN00001", "Shazaar", Decimal("700.00"))


def test_item_que_ficou_no_carrinho(s):
    a = confirmado(s, "B0MON00001")
    presa = conferencia(s, a, T0, SituacaoCheckout.FALHA, total=None, removido=False)
    conferencia(s, a, T0 + timedelta(minutes=1))
    assert repo.conferencias_com_item_no_carrinho(s) == [(presa.id, "B0MON00001")]
    repo.marcar_item_removido(s, presa.id)
    assert repo.conferencias_com_item_no_carrinho(s) == []


def test_link_manual_usa_o_titulo_provisorio(s):
    produto = criar_produto(s, "p1")
    assert repo.casar_link_manual(s, produto.id, "B0MANUAL01", T0).titulo == repo.TITULO_MANUAL
```

- [ ] **Step 2: Testes da migração e da configuração (falham)**

Em `tests/db/test_migracao.py`: acrescente ao `parametrize` de `test_config_amazon_recusa_valores_fora_dos_limites` os casos `("monitor_intervalo_min", 4)`, `("monitor_max_paginas_hora", 0)`, `("margem_candidata_pp", 51)`, `("checkout_validade_h", 0)`, `("descoberta_casados_dias", 61)`; importe `datetime`/`time` conforme preciso e acrescente:

```python
def test_config_amazon_liga_monitor_e_conferencia_por_padrao(s):
    cfg = s.get(ConfigAmazon, 1)
    assert (cfg.monitor_ligado, cfg.checkout_ligado, cfg.checkout_sem_login_em) == (True, True, None)


def test_config_amazon_recusa_janela_do_monitor_invertida(s):
    with pytest.raises(IntegrityError):
        s.execute(
            update(ConfigAmazon).where(ConfigAmazon.id == 1).values(monitor_janela_inicio=time(22, 0), monitor_janela_fim=time(8, 0))
        )


def test_migracao_preenche_a_origem_do_casamento(engine):
    """Fora da transação do `sessoes`: desce para a revisão anterior, grava anúncios e avaliações, sobe
    e confere a origem preenchida. Sempre deixa o banco em head."""
    url = engine.url.render_as_string(hide_password=False)
    cfg = config_alembic(url)
    proprio = create_engine(url, poolclass=pool.NullPool)
    quando = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
    try:
        command.downgrade(cfg, "f2b6d8a4c1e7")
        with proprio.begin() as c:
            produto = c.scalar(
                text(
                    "INSERT INTO produto_liga (liga_id, nome, url, ativo, visto_primeiro_em, visto_ultimo_em) "
                    "VALUES ('mig-origem', 'P', 'u', true, now(), now()) RETURNING id"
                )
            )

            def anuncio(asin, situacao, revisado):
                return c.scalar(
                    text(
                        "INSERT INTO anuncio_amazon (asin, titulo, url, produto_id, status_casamento, revisado_em, "
                        "visto_primeiro_em, visto_ultimo_em) VALUES (:a, 't', 'u', :p, :st, :r, now(), now()) RETURNING id"
                    ),
                    {"a": asin, "p": produto, "st": situacao, "r": revisado},
                )

            def avaliacao(anuncio_id, aplicada):
                c.execute(
                    text(
                        "INSERT INTO avaliacao_ia (anuncio_id, produto_id, mesmo_produto, confianca, motivo, modelo, "
                        "assinatura, sem_imagem, avaliado_em, aplicada_em) "
                        "VALUES (:a, :p, true, 95, 'm', 'gpt-5', 'x', false, now(), :ap)"
                    ),
                    {"a": anuncio_id, "p": produto, "ap": aplicada},
                )

            automatico = anuncio("BMIG000001", "confirmado", quando)
            sugerido = anuncio("BMIG000002", "ignorado", quando)
            anuncio("BMIG000003", "confirmado", quando)
            pendente = anuncio("BMIG000004", "pendente", None)
            avaliacao(automatico, quando)
            avaliacao(sugerido, None)
            avaliacao(pendente, None)
        command.upgrade(cfg, "head")
        with proprio.connect() as c:
            origens = dict(
                c.execute(text("SELECT asin, origem_casamento FROM anuncio_amazon WHERE asin LIKE 'BMIG%'")).all()
            )
        assert origens == {
            "BMIG000001": "automatico_ia", "BMIG000002": "sugerido_ia", "BMIG000003": "manual", "BMIG000004": None,
        }
    finally:
        command.upgrade(cfg, "head")
        with proprio.begin() as c:
            c.execute(text("DELETE FROM avaliacao_ia WHERE anuncio_id IN (SELECT id FROM anuncio_amazon WHERE asin LIKE 'BMIG%')"))
            c.execute(text("DELETE FROM anuncio_amazon WHERE asin LIKE 'BMIG%'"))
            c.execute(text("DELETE FROM produto_liga WHERE liga_id = 'mig-origem'"))
        proprio.dispose()
```

(Importe `time` de `datetime` no topo: `from datetime import UTC, datetime, time`.)

Em `tests/coletor_amazon/test_config_amazon.py`, acrescente ao `parametrize` de `test_campo_invalido` os casos `("monitor_intervalo_min", "4", "entre 5 e 1440")` e `("monitor_janela_inicio", "8h", "HH:MM")`, e:

```python
def test_janela_do_monitor_invertida():
    _, erros = validar_config(formulario(monitor_janela_inicio="22:00", monitor_janela_fim="08:00"))
    assert erros == {"monitor_janela_fim": "O fim da janela do monitor precisa ser depois do início."}
```

Nos dicionários `FORMULARIO_AMAZON` (`tests/admin/test_admin_config_tela.py`) e `formulario_padrao` (`tests/admin/test_admin_amazon.py`) acrescente:

```python
        "monitor_intervalo_min": "15",
        "monitor_janela_inicio": "08:00",
        "monitor_janela_fim": "22:00",
        "monitor_max_paginas_hora": "150",
        "margem_candidata_pp": "5",
        "checkout_validade_h": "6",
        "descoberta_casados_dias": "7",
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t3 uv run pytest tests/db tests/coletor_amazon/test_config_amazon.py -q`
Expected: FAIL (ImportError: `oferta_lista`, `SituacaoCheckout`).

- [ ] **Step 4: Modelos**

Em `src/tcg_sniper/db/models.py`:

```python
class OrigemPreco(enum.StrEnum):
    BUSCA = "busca"  # cartão do resultado de busca
    PRODUTO = "produto"  # oferta principal da página do produto
    OFERTAS = "ofertas"  # melhor oferta elegível da lista de ofertas (monitor)


class OrigemCasamento(enum.StrEnum):
    MANUAL = "manual"  # o usuário decidiu sem avaliação da IA para o par, ou colou o link
    SUGERIDO_IA = "sugerido_ia"  # o usuário decidiu um par que a IA tinha avaliado
    AUTOMATICO_IA = "automatico_ia"  # o automático do casador decidiu


class SituacaoCheckout(enum.StrEnum):
    OK = "ok"
    FALHA = "falha"
    CARRINHO_OCUPADO = "carrinho_ocupado"  # havia item no carrinho ativo: nada foi clicado
    SEM_LOGIN = "sem_login"  # a Amazon pediu login: a conferência fica desligada até "Retomar"
```

Em `AnuncioAmazon`, depois de `revisado_em`:

```python
    # Quem decidiu o casamento (confirmado ou ignorado); nula enquanto pendente.
    origem_casamento: Mapped[OrigemCasamento | None] = mapped_column(_enum(OrigemCasamento, "origem_casamento"))
```

Depois de `Oportunidade`:

```python
class OfertaAmazon(Base):
    """Todas as ofertas de cada leitura do monitor (lista de ofertas do ASIN). `melhor` marca a que
    virou o preço atual do anúncio. Leituras com mais de 30 dias são apagadas pelo coletor."""

    __tablename__ = "oferta_amazon"
    __table_args__ = (Index("ix_oferta_amazon_leitura", "anuncio_id", "lida_em"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    anuncio_id: Mapped[int] = mapped_column(ForeignKey("anuncio_amazon.id"))
    lida_em: Mapped[datetime] = mapped_column(DATA)
    vendedor_id: Mapped[int | None] = mapped_column(ForeignKey("vendedor_amazon.id"))
    vendedor_nome: Mapped[str | None] = mapped_column(Text)
    preco: Mapped[Decimal] = mapped_column(DINHEIRO)
    preco_de: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    condicao: Mapped[str] = mapped_column(Text)  # "novo" | "usado" | o texto do painel
    envio: Mapped[Envio] = mapped_column(_enum(Envio, "envio_amazon"))
    origem_envio: Mapped[str | None] = mapped_column(Text)  # "Estados Unidos"
    importada: Mapped[bool] = mapped_column(Boolean)
    prime: Mapped[bool] = mapped_column(Boolean)
    elegivel: Mapped[bool] = mapped_column(Boolean)
    melhor: Mapped[bool] = mapped_column(Boolean)


class ConferenciaCheckout(Base):
    """Cada conferência de checkout de uma oferta candidata. `item_removido` False: o item pode ter
    ficado no carrinho e o coletor tenta tirar de novo na próxima volta."""

    __tablename__ = "conferencia_checkout"
    __table_args__ = (Index("ix_conferencia_checkout_anuncio", "anuncio_id", "em"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    em: Mapped[datetime] = mapped_column(DATA)
    anuncio_id: Mapped[int] = mapped_column(ForeignKey("anuncio_amazon.id"))
    vendedor_nome: Mapped[str | None] = mapped_column(Text)
    preco_anunciado: Mapped[Decimal] = mapped_column(DINHEIRO)
    itens: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    frete: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    impostos: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    total: Mapped[Decimal | None] = mapped_column(DINHEIRO)
    situacao: Mapped[SituacaoCheckout] = mapped_column(_enum(SituacaoCheckout, "situacao_checkout"))
    motivo: Mapped[str | None] = mapped_column(Text)
    item_removido: Mapped[bool] = mapped_column(Boolean)
```

Em `LIMITES_CONFIG_AMAZON` acrescente:

```python
    "monitor_intervalo_min": (5, 1440),
    "monitor_max_paginas_hora": (1, 1000),
    "margem_candidata_pp": (0, 50),
    "checkout_validade_h": (1, 72),
    "descoberta_casados_dias": (1, 60),
```

Em `PADROES_CONFIG_AMAZON` acrescente (no fim, nesta ordem):

```python
    "monitor_intervalo_min": 15,
    "monitor_janela_inicio": time(8, 0),
    "monitor_janela_fim": time(22, 0),
    "monitor_max_paginas_hora": 150,
    "margem_candidata_pp": 5,
    "checkout_validade_h": 6,
    "descoberta_casados_dias": 7,
```

Em `ConfigAmazon.__table_args__` acrescente `CheckConstraint("monitor_janela_inicio < monitor_janela_fim", name="ck_config_amazon_monitor_janela"),` e, antes de `atualizado_em`, as colunas:

```python
    monitor_janela_inicio: Mapped[time] = mapped_column(Time)
    monitor_janela_fim: Mapped[time] = mapped_column(Time)
    monitor_intervalo_min: Mapped[int] = mapped_column(Integer)
    monitor_max_paginas_hora: Mapped[int] = mapped_column(Integer)
    margem_candidata_pp: Mapped[int] = mapped_column(Integer)
    checkout_validade_h: Mapped[int] = mapped_column(Integer)
    descoberta_casados_dias: Mapped[int] = mapped_column(Integer)
    # Ligados e desligados em Serviços (fora do formulário de Configurações).
    monitor_ligado: Mapped[bool] = mapped_column(Boolean, server_default="true")
    checkout_ligado: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # Preenchida quando o checkout pediu login: a conferência não roda até "Retomar conferência".
    checkout_sem_login_em: Mapped[datetime | None] = mapped_column(DATA)
```

- [ ] **Step 5: Migração**

Create `src/tcg_sniper/db/migrations/versions/b9e4c2a7d3f5_monitor_amazon.py`:

```python
"""monitor de preço da Amazon: ofertas de cada leitura, conferência de checkout, origem do casamento
e configuração do monitor

Revision ID: b9e4c2a7d3f5
Revises: f2b6d8a4c1e7
Create Date: 2026-10-17 18:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9e4c2a7d3f5"
down_revision: Union[str, Sequence[str], None] = "f2b6d8a4c1e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DATA = sa.DateTime(timezone=True)
DINHEIRO = sa.Numeric(10, 2)
ENVIO = ("amazon", "fba", "proprio", "desconhecido")
LIMITES_NOVOS = {
    "monitor_intervalo_min": (5, 1440, 15),
    "monitor_max_paginas_hora": (1, 1000, 150),
    "margem_candidata_pp": (0, 50, 5),
    "checkout_validade_h": (1, 72, 6),
    "descoberta_casados_dias": (1, 60, 7),
}


def _enum(nome: str, *valores: str) -> sa.Enum:
    return sa.Enum(*valores, name=nome, native_enum=False, create_constraint=True, length=20)


def upgrade() -> None:
    for tabela in ("preco_amazon", "preco_atual_amazon"):
        op.drop_constraint("origem_preco", tabela, type_="check")
        op.create_check_constraint("origem_preco", tabela, "origem IN ('busca', 'produto', 'ofertas')")

    op.add_column("anuncio_amazon", sa.Column("origem_casamento", sa.String(20), nullable=True))
    op.create_check_constraint(
        "origem_casamento", "anuncio_amazon", "origem_casamento IN ('manual', 'sugerido_ia', 'automatico_ia')"
    )
    op.execute(
        """
        UPDATE anuncio_amazon a SET origem_casamento = CASE
            WHEN EXISTS (SELECT 1 FROM avaliacao_ia v WHERE v.anuncio_id = a.id AND v.produto_id = a.produto_id
                         AND v.aplicada_em = a.revisado_em) THEN 'automatico_ia'
            WHEN EXISTS (SELECT 1 FROM avaliacao_ia v WHERE v.anuncio_id = a.id AND v.produto_id = a.produto_id)
                THEN 'sugerido_ia'
            ELSE 'manual' END
        WHERE a.status_casamento IN ('confirmado', 'ignorado')
        """
    )

    op.create_table(
        "oferta_amazon",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("anuncio_id", sa.Integer(), sa.ForeignKey("anuncio_amazon.id"), nullable=False),
        sa.Column("lida_em", DATA, nullable=False),
        sa.Column("vendedor_id", sa.Integer(), sa.ForeignKey("vendedor_amazon.id"), nullable=True),
        sa.Column("vendedor_nome", sa.Text(), nullable=True),
        sa.Column("preco", DINHEIRO, nullable=False),
        sa.Column("preco_de", DINHEIRO, nullable=True),
        sa.Column("condicao", sa.Text(), nullable=False),
        sa.Column("envio", _enum("envio_amazon", *ENVIO), nullable=False),
        sa.Column("origem_envio", sa.Text(), nullable=True),
        sa.Column("importada", sa.Boolean(), nullable=False),
        sa.Column("prime", sa.Boolean(), nullable=False),
        sa.Column("elegivel", sa.Boolean(), nullable=False),
        sa.Column("melhor", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_oferta_amazon_leitura", "oferta_amazon", ["anuncio_id", "lida_em"])
    op.create_table(
        "conferencia_checkout",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("em", DATA, nullable=False),
        sa.Column("anuncio_id", sa.Integer(), sa.ForeignKey("anuncio_amazon.id"), nullable=False),
        sa.Column("vendedor_nome", sa.Text(), nullable=True),
        sa.Column("preco_anunciado", DINHEIRO, nullable=False),
        sa.Column("itens", DINHEIRO, nullable=True),
        sa.Column("frete", DINHEIRO, nullable=True),
        sa.Column("impostos", DINHEIRO, nullable=True),
        sa.Column("total", DINHEIRO, nullable=True),
        sa.Column("situacao", _enum("situacao_checkout", "ok", "falha", "carrinho_ocupado", "sem_login"), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("item_removido", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_conferencia_checkout_anuncio", "conferencia_checkout", ["anuncio_id", "em"])

    for campo, hora in (("monitor_janela_inicio", "08:00"), ("monitor_janela_fim", "22:00")):
        op.add_column("config_amazon", sa.Column(campo, sa.Time(), nullable=False, server_default=hora))
        op.alter_column("config_amazon", campo, server_default=None)
    op.create_check_constraint(
        "ck_config_amazon_monitor_janela", "config_amazon", "monitor_janela_inicio < monitor_janela_fim"
    )
    for campo, (minimo, maximo, padrao) in LIMITES_NOVOS.items():
        op.add_column("config_amazon", sa.Column(campo, sa.Integer(), nullable=False, server_default=str(padrao)))
        op.alter_column("config_amazon", campo, server_default=None)
        op.create_check_constraint(f"ck_config_amazon_{campo}", "config_amazon", f"{campo} BETWEEN {minimo} AND {maximo}")
    for campo in ("monitor_ligado", "checkout_ligado"):
        op.add_column("config_amazon", sa.Column(campo, sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("config_amazon", sa.Column("checkout_sem_login_em", DATA, nullable=True))


def downgrade() -> None:
    for campo in ("checkout_sem_login_em", "checkout_ligado", "monitor_ligado", *LIMITES_NOVOS, "monitor_janela_fim", "monitor_janela_inicio"):
        op.drop_column("config_amazon", campo)
    op.drop_index("ix_conferencia_checkout_anuncio", table_name="conferencia_checkout")
    op.drop_table("conferencia_checkout")
    op.drop_index("ix_oferta_amazon_leitura", table_name="oferta_amazon")
    op.drop_table("oferta_amazon")
    op.drop_constraint("origem_casamento", "anuncio_amazon", type_="check")
    op.drop_column("anuncio_amazon", "origem_casamento")
    op.execute("DELETE FROM preco_amazon WHERE origem = 'ofertas'")
    op.execute("UPDATE preco_atual_amazon SET origem = 'produto' WHERE origem = 'ofertas'")
    for tabela in ("preco_amazon", "preco_atual_amazon"):
        op.drop_constraint("origem_preco", tabela, type_="check")
        op.create_check_constraint("origem_preco", tabela, "origem IN ('busca', 'produto')")
```

- [ ] **Step 6: `OfertaLista`**

Em `src/tcg_sniper/coletor_amazon/modelos.py`:

```python
@dataclass(frozen=True)
class OfertaLista:
    """Uma oferta do painel "Outras opções de compra". `posicao` 0 = a oferta em destaque
    (#aod-pinned-offer); 1.. = a ordem dos blocos #aod-offer (é o que o clique usa)."""

    posicao: int
    vendedor_nome: str | None
    seller_id: str | None  # "amazon" quando vendida pela Amazon
    preco: Decimal
    preco_de: Decimal | None
    condicao: str  # "novo" | "usado" | o texto do painel
    envio: Envio
    origem_envio: str | None  # "Estados Unidos"; None quando o painel não diz
    importada: bool
    prime: bool
    pct_positivas: Decimal | None  # avaliação do vendedor mostrada no painel
    num_avaliacoes: int | None
    cupom: str | None  # desconto condicional, só informativo
```

No fim de `tests/fakes.py` (e `from tcg_sniper.coletor_amazon.modelos import OfertaLista`, `from tcg_sniper.db.models import Envio` no topo):

```python
def oferta_lista(preco="275.91", vendedor="Shazaar", seller_id="A2SHZ", envio=Envio.FBA, posicao=1, **campos) -> OfertaLista:
    valores = dict(
        posicao=posicao, vendedor_nome=vendedor, seller_id=seller_id, preco=Decimal(preco), preco_de=None,
        condicao="novo", envio=envio, origem_envio=None, importada=False, prime=False, pct_positivas=None,
        num_avaliacoes=None, cupom=None,
    )
    valores.update(campos)
    return OfertaLista(**valores)
```

- [ ] **Step 7: Repositório**

Em `src/tcg_sniper/db/repositorio_amazon.py`: importe `case`, `or_`, `and_` de `sqlalchemy`; `OfertaLista` de `coletor_amazon.modelos`; `ConferenciaCheckout`, `OfertaAmazon`, `SituacaoCheckout` de `db.models`; `from tcg_sniper.oportunidades import motor`.

Constante e `casar_link_manual`:

```python
TITULO_MANUAL = "Informado manualmente"  # título provisório do anúncio colado à mão
```

e troque `titulo="Informado manualmente"` por `titulo=TITULO_MANUAL` em `casar_link_manual`.

`registrar_preco`: troque o corpo depois do cálculo de `gravar` por:

```python
    leitura_completa = origem in (OrigemPreco.PRODUTO, OrigemPreco.OFERTAS)
    gravar = (
        ultimo is None
        or ultimo.coletado_em < inicio_do_dia
        or ultimo.preco != preco
        or (leitura_completa and (ultimo.vendedor_id, ultimo.envio) != (vendedor_id, envio))
    )
    if gravar:
        s.add(
            PrecoAmazon(
                anuncio_id=anuncio_id, coletado_em=agora, preco=preco, origem=origem,
                vendedor_id=vendedor_id, envio=envio,
            )
        )
    origem_atual = s.scalar(select(PrecoAtualAmazon.origem).where(PrecoAtualAmazon.anuncio_id == anuncio_id))
    if origem is OrigemPreco.BUSCA and origem_atual is OrigemPreco.OFERTAS:
        s.flush()  # o monitor manda no preço atual: a busca só entra no histórico
        return gravar
    atual: dict[str, object] = {"preco": preco, "origem": origem, "coletado_em": agora}
    if leitura_completa:
        atual |= {"vendedor_id": vendedor_id, "envio": envio}
    s.execute(
        pg_insert(PrecoAtualAmazon)
        .values(anuncio_id=anuncio_id, preco=preco, origem=origem, vendedor_id=vendedor_id, envio=envio, coletado_em=agora)
        .on_conflict_do_update(index_elements=[PrecoAtualAmazon.anuncio_id], set_=atual)
    )
    s.flush()
    return gravar
```

(e atualize o docstring: "vendedor/envio só mudam numa leitura de origem `produto` ou `ofertas`; a busca não troca o preço atual lido nas ofertas"). No docstring de `PrecoAtualAmazon` em `models.py`, troque "origem `produto`" por "origem `produto` ou `ofertas`".

Fila (descoberta) — substitua `ids_na_fila` e `proximo_da_fila`:

```python
def _descoberta_liberada(agora: datetime | None, casados_dias: int | None):
    """Sem casamento confirmado: sempre (no ritmo da fila). Casado: só se nunca buscado ou se a
    última busca tem `casados_dias` dias ou mais (busca semanal)."""
    if agora is None or casados_dias is None:
        return literal(True)
    casados = select(AnuncioAmazon.produto_id).where(
        AnuncioAmazon.status_casamento == StatusCasamento.CONFIRMADO, AnuncioAmazon.produto_id.is_not(None)
    )
    return or_(
        FilaAmazon.produto_id.not_in(casados),
        FilaAmazon.ultima_busca_em.is_(None),
        FilaAmazon.ultima_busca_em <= agora - timedelta(days=casados_dias),
    )


def ids_na_fila(s: Session, agora: datetime | None = None, casados_dias: int | None = None) -> set[int]:
    return set(s.scalars(select(FilaAmazon.produto_id).where(_descoberta_liberada(agora, casados_dias))))


def proximo_da_fila(s: Session, agora: datetime, casados_dias: int | None = None) -> FilaAmazon | None:
    """O vencido há mais tempo; no empate, o de maior "À partir de" na Liga. Com `casados_dias`, os
    produtos já casados só entram na busca semanal."""
    consulta = (
        select(FilaAmazon)
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == FilaAmazon.produto_id)
        .where(FilaAmazon.proxima_busca_em <= agora, _descoberta_liberada(agora, casados_dias))
        .order_by(
            FilaAmazon.proxima_busca_em,
            PrecoAtualLiga.preco_a_partir.desc().nulls_last(),
            FilaAmazon.produto_id,
        )
        .limit(1)
    )
    return s.scalar(consulta)
```

No fim do arquivo:

```python
# --- monitor de preço -----------------------------------------------------------------------


@dataclass(frozen=True)
class OfertaAvaliada:
    oferta: OfertaLista
    vendedor_id: int | None
    elegivel: bool
    melhor: bool


def gravar_ofertas(s: Session, anuncio_id: int, lida_em: datetime, ofertas: Sequence[OfertaAvaliada]) -> None:
    for avaliada in ofertas:
        o = avaliada.oferta
        s.add(
            OfertaAmazon(
                anuncio_id=anuncio_id, lida_em=lida_em, vendedor_id=avaliada.vendedor_id, vendedor_nome=o.vendedor_nome,
                preco=o.preco, preco_de=o.preco_de, condicao=o.condicao, envio=o.envio, origem_envio=o.origem_envio,
                importada=o.importada, prime=o.prime, elegivel=avaliada.elegivel, melhor=avaliada.melhor,
            )
        )
    s.flush()


def ofertas_da_ultima_leitura(s: Session, anuncio_ids: Sequence[int]) -> dict[int, list[OfertaAmazon]]:
    """As ofertas da leitura mais recente de cada anúncio, a mais barata primeiro."""
    if not anuncio_ids:
        return {}
    ultima = (
        select(OfertaAmazon.anuncio_id, func.max(OfertaAmazon.lida_em).label("lida_em"))
        .where(OfertaAmazon.anuncio_id.in_(anuncio_ids))
        .group_by(OfertaAmazon.anuncio_id)
        .subquery()
    )
    consulta = (
        select(OfertaAmazon)
        .join(ultima, and_(ultima.c.anuncio_id == OfertaAmazon.anuncio_id, ultima.c.lida_em == OfertaAmazon.lida_em))
        .order_by(OfertaAmazon.anuncio_id, OfertaAmazon.preco, OfertaAmazon.id)
    )
    resultado: dict[int, list[OfertaAmazon]] = {}
    for oferta in s.scalars(consulta):
        resultado.setdefault(oferta.anuncio_id, []).append(oferta)
    return resultado


def limpar_ofertas_antigas(s: Session, agora: datetime, dias: int = 30) -> int:
    resultado = s.execute(delete(OfertaAmazon).where(OfertaAmazon.lida_em < agora - timedelta(days=dias)))
    s.flush()
    return resultado.rowcount


def marcar_visto(s: Session, anuncio_id: int, agora: datetime) -> None:
    """A leitura do monitor conta como "visto" (fechar_oportunidades_sem_leitura usa)."""
    s.execute(update(AnuncioAmazon).where(AnuncioAmazon.id == anuncio_id).values(visto_ultimo_em=agora))
    s.flush()


def _leitura_do_monitor():
    """Quando o monitor leu o anúncio pela última vez (NULL se a última leitura não foi das ofertas)."""
    return case((PrecoAtualAmazon.origem == OrigemPreco.OFERTAS, PrecoAtualAmazon.coletado_em), else_=None)


def _confirmados_ativos(consulta):
    return (
        consulta.join(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .where(AnuncioAmazon.status_casamento == StatusCasamento.CONFIRMADO, ProdutoLiga.ativo.is_(True))
    )


def proximo_do_monitor(
    s: Session, agora: datetime, intervalo_min: int, excluir: Collection[int] = ()
) -> tuple[int, str] | None:
    """O anúncio confirmado (de produto ativo) com a leitura de ofertas mais antiga já vencida; os
    nunca lidos primeiro. `excluir`: anúncios que falharam há pouco (a varredura guarda)."""
    leitura = _leitura_do_monitor()
    consulta = _confirmados_ativos(select(AnuncioAmazon.id, AnuncioAmazon.asin)).where(
        or_(leitura.is_(None), leitura <= agora - timedelta(minutes=intervalo_min))
    )
    if excluir:
        consulta = consulta.where(AnuncioAmazon.id.not_in(list(excluir)))
    linha = s.execute(consulta.order_by(leitura.asc().nulls_first(), AnuncioAmazon.id).limit(1)).first()
    return (linha.id, linha.asin) if linha else None


@dataclass(frozen=True)
class SituacaoMonitor:
    confirmados: int
    nunca_lidos: int
    vencidos: int  # leitura mais velha que o intervalo (ou nunca lidos)
    mais_antiga: datetime | None  # leitura de ofertas mais antiga entre os já lidos
    ultima: datetime | None


def situacao_monitor(s: Session, agora: datetime, intervalo_min: int) -> SituacaoMonitor:
    leitura = _leitura_do_monitor()
    vencido = or_(leitura.is_(None), leitura <= agora - timedelta(minutes=intervalo_min))
    consulta = _confirmados_ativos(
        select(func.count(), func.count(leitura), func.count().filter(vencido), func.min(leitura), func.max(leitura))
        .select_from(AnuncioAmazon)
    )
    total, lidos, vencidos, mais_antiga, ultima = s.execute(consulta).one()
    return SituacaoMonitor(total, total - lidos, vencidos, mais_antiga, ultima)


# --- conferência de checkout ----------------------------------------------------------------


def registrar_conferencia(
    s: Session,
    *,
    em: datetime,
    anuncio_id: int,
    vendedor_nome: str | None,
    preco_anunciado: Decimal,
    itens: Decimal | None,
    frete: Decimal | None,
    impostos: Decimal | None,
    total: Decimal | None,
    situacao: SituacaoCheckout,
    motivo: str | None,
    item_removido: bool,
) -> ConferenciaCheckout:
    conferencia = ConferenciaCheckout(
        em=em, anuncio_id=anuncio_id, vendedor_nome=vendedor_nome, preco_anunciado=preco_anunciado, itens=itens,
        frete=frete, impostos=impostos, total=total, situacao=situacao, motivo=motivo, item_removido=item_removido,
    )
    s.add(conferencia)
    s.flush()
    return conferencia


def _mesma_oferta(anuncio_id: int, vendedor_nome: str | None, preco_anunciado: Decimal):
    return and_(
        ConferenciaCheckout.anuncio_id == anuncio_id,
        ConferenciaCheckout.vendedor_nome.is_not_distinct_from(vendedor_nome),
        ConferenciaCheckout.preco_anunciado == preco_anunciado,
    )


def conferencia_valida(
    s: Session, anuncio_id: int, vendedor_nome: str | None, preco_anunciado: Decimal, agora: datetime, validade_h: int
) -> ConferenciaCheckout | None:
    """A conferência ok mais recente da mesma oferta (ASIN + vendedor + preço) dentro da validade."""
    return s.scalar(
        select(ConferenciaCheckout)
        .where(
            _mesma_oferta(anuncio_id, vendedor_nome, preco_anunciado),
            ConferenciaCheckout.situacao == SituacaoCheckout.OK,
            ConferenciaCheckout.total.is_not(None),
            ConferenciaCheckout.em >= agora - timedelta(hours=validade_h),
        )
        .order_by(ConferenciaCheckout.em.desc(), ConferenciaCheckout.id.desc())
        .limit(1)
    )


def ultima_conferencia(s: Session, anuncio_id: int | None = None) -> ConferenciaCheckout | None:
    consulta = select(ConferenciaCheckout).order_by(ConferenciaCheckout.em.desc(), ConferenciaCheckout.id.desc()).limit(1)
    if anuncio_id is not None:
        consulta = consulta.where(ConferenciaCheckout.anuncio_id == anuncio_id)
    return s.scalar(consulta)


def conferencias_com_item_no_carrinho(s: Session) -> list[tuple[int, str]]:
    """(conferência, ASIN) cujo item pode ter ficado no carrinho, das mais antigas."""
    consulta = (
        select(ConferenciaCheckout.id, AnuncioAmazon.asin)
        .join(AnuncioAmazon, AnuncioAmazon.id == ConferenciaCheckout.anuncio_id)
        .where(ConferenciaCheckout.item_removido.is_(False))
        .order_by(ConferenciaCheckout.em, ConferenciaCheckout.id)
    )
    return [(conferencia_id, asin) for conferencia_id, asin in s.execute(consulta)]


def marcar_item_removido(s: Session, conferencia_id: int) -> None:
    s.execute(update(ConferenciaCheckout).where(ConferenciaCheckout.id == conferencia_id).values(item_removido=True))
    s.flush()


@dataclass(frozen=True)
class CandidataCheckout:
    anuncio_id: int
    asin: str
    vendedor_nome: str | None
    preco_anunciado: Decimal


def candidatas_ao_checkout(s: Session, agora: datetime, cfg: ConfigAmazon) -> list[CandidataCheckout]:
    """A melhor oferta elegível da última leitura de cada confirmado (produto ativo, preço da Liga em
    dia) com desconto anunciado de pelo menos `desconto_min_pct − margem_candidata_pp`, sem conferência
    ok ou falha da mesma oferta nas últimas `checkout_validade_h` horas. Maior desconto primeiro."""
    ultima = (
        select(OfertaAmazon.anuncio_id, func.max(OfertaAmazon.lida_em).label("lida_em"))
        .group_by(OfertaAmazon.anuncio_id)
        .subquery()
    )
    consulta = (
        select(AnuncioAmazon.id, AnuncioAmazon.asin, OfertaAmazon.vendedor_nome, OfertaAmazon.preco, PrecoAtualLiga.preco_a_partir)
        .join(ultima, ultima.c.anuncio_id == AnuncioAmazon.id)
        .join(
            OfertaAmazon,
            and_(
                OfertaAmazon.anuncio_id == AnuncioAmazon.id,
                OfertaAmazon.lida_em == ultima.c.lida_em,
                OfertaAmazon.melhor.is_(True),
                OfertaAmazon.elegivel.is_(True),
            ),
        )
        .join(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .join(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(
            AnuncioAmazon.status_casamento == StatusCasamento.CONFIRMADO,
            ProdutoLiga.ativo.is_(True),
            PrecoAtualLiga.listagem_em >= agora - timedelta(hours=cfg.liga_preco_max_idade_h),
        )
    )
    minimo = max(0, cfg.desconto_min_pct - cfg.margem_candidata_pp)
    candidatas: list[tuple[Decimal, CandidataCheckout]] = []
    for anuncio_id, asin, vendedor, preco, liga in s.execute(consulta):
        if not motor.atinge_desconto(preco, liga, minimo):
            continue
        conferida = s.scalar(
            select(ConferenciaCheckout.id)
            .where(
                _mesma_oferta(anuncio_id, vendedor, preco),
                ConferenciaCheckout.situacao.in_([SituacaoCheckout.OK, SituacaoCheckout.FALHA]),
                ConferenciaCheckout.em >= agora - timedelta(hours=cfg.checkout_validade_h),
            )
            .limit(1)
        )
        if conferida is None:
            candidatas.append((preco / liga, CandidataCheckout(anuncio_id, asin, vendedor, preco)))
    candidatas.sort(key=lambda par: (par[0], par[1].anuncio_id))
    return [candidata for _, candidata in candidatas]
```

(Importe `Collection` de `collections.abc`.)

- [ ] **Step 8: Formulário da Amazon**

Em `src/tcg_sniper/coletor_amazon/config.py`: acrescente no fim de `CAMPOS` (nesta ordem) `"monitor_intervalo_min", "monitor_janela_inicio", "monitor_janela_fim", "monitor_max_paginas_hora", "margem_candidata_pp", "checkout_validade_h", "descoberta_casados_dias"`; em `ROTULOS`:

```python
    "monitor_intervalo_min": "Ler cada anúncio confirmado a cada (min)",
    "monitor_janela_inicio": "Início do monitor",
    "monitor_janela_fim": "Fim do monitor",
    "monitor_max_paginas_hora": "Máximo de páginas por hora do monitor e da conferência",
    "margem_candidata_pp": "Conferir no checkout a partir de (pontos abaixo do desconto mínimo)",
    "checkout_validade_h": "Conferência de checkout vale por (h)",
    "descoberta_casados_dias": "Buscar de novo produtos já casados a cada (dias)",
```

em `EXPLICACOES`:

```python
    "monitor_intervalo_min": "De quantos em quantos minutos ler a lista de ofertas de cada anúncio confirmado.",
    "monitor_janela_inicio": "Hora (HH:MM) em que o monitor começa, com variação de até 15 minutos.",
    "monitor_janela_fim": "Hora (HH:MM) em que o monitor para, com variação de até 15 minutos.",
    "monitor_max_paginas_hora": (
        "Teto de páginas por hora somando monitor, conferência de checkout e retirada de itens do carrinho. "
        "A busca de anúncios novos tem o próprio teto."
    ),
    "margem_candidata_pp": (
        "Uma oferta com desconto anunciado de pelo menos (desconto mínimo − este valor) vai ao checkout "
        "para conferir impostos e frete."
    ),
    "checkout_validade_h": "Por quantas horas o total conferido vale para a mesma oferta (vendedor e preço).",
    "descoberta_casados_dias": "Produto que já tem anúncio confirmado só volta à busca depois deste número de dias.",
```

e em `validar_config` troque o laço das horas e acrescente a checagem da janela do monitor:

```python
    for campo in ("janela_inicio", "janela_fim", "monitor_janela_inicio", "monitor_janela_fim"):
        hora = ler_hora((campos.get(campo) or "").strip())
        if hora is None:
            erros[campo] = "Use o formato HH:MM, por exemplo 08:00."
        else:
            valores[campo] = hora
```

```python
    if (
        "monitor_janela_inicio" in valores
        and "monitor_janela_fim" in valores
        and valores["monitor_janela_inicio"] >= valores["monitor_janela_fim"]
    ):
        erros["monitor_janela_fim"] = "O fim da janela do monitor precisa ser depois do início."
```

- [ ] **Step 9: Rodar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t3 uv run pytest -q && uv run ruff check .`
Expected: PASS, inclusive `test_migracao_igual_aos_modelos` (se acusar diferença, ajuste a migração, não os modelos) e `test_migracao_amazon_preserva_os_dados_da_liga`.

- [ ] **Step 10: Commit**

```bash
git add src/tcg_sniper/db/models.py src/tcg_sniper/db/migrations/versions/b9e4c2a7d3f5_monitor_amazon.py src/tcg_sniper/coletor_amazon/modelos.py src/tcg_sniper/db/repositorio_amazon.py src/tcg_sniper/coletor_amazon/config.py tests/fakes.py tests/db/test_repositorio_monitor.py tests/db/test_migracao.py tests/coletor_amazon/test_config_amazon.py tests/admin/test_admin_config_tela.py tests/admin/test_admin_amazon.py
git commit -m "feat: tables, settings and queries for the Amazon price monitor, checkout checks and match origin"
```

---

### Task 4: Motor e mensagens (elegibilidade pública, preço conferido na mensagem)

**Files:**
- Modify: `src/tcg_sniper/oportunidades/motor.py`
- Modify: `src/tcg_sniper/oportunidades/mensagens.py`
- Test: `tests/oportunidades/test_motor.py`, `tests/oportunidades/test_mensagens.py` (acrescenta)

**Interfaces:**
- Produces:
  - `motor.vendedor_elegivel(envio: Envio, vendedor: Vendedor | None, regras: Regras) -> bool` (Amazon sempre; FBA com vendedor confiável; o resto nunca). `elegivel`/`decidir` continuam iguais.
  - `mensagens.Detalhes(total_conferido=None, impostos=None, frete=None, motivo_nao_conferido=None, importada=False, origem_envio=None, prime=False, cupom=None)`.
  - `mensagens.mensagem_oportunidade(..., detalhes: Detalhes | None = None)`: sem `detalhes`, o texto é o de hoje. Com `total_conferido`, `leitura.preco` é o total e a linha diz "R$ X conferido no checkout (impostos R$ Y, frete R$ Z)"; sem, "R$ X, preço anunciado, não conferido (<motivo>)" (motivo padrão "aguardando conferência"). Selos " · importado (EUA)" e " · Prime" dentro do parêntese do vendedor; cupom numa linha "Cupom: <texto> (condicional, não descontado)".

- [ ] **Step 1: Testes (falham)**

Em `tests/oportunidades/test_motor.py` acrescente (o arquivo já importa `Envio`, `Regras`, `Vendedor`, `Decimal`; acrescente `vendedor_elegivel` ao import de `motor`):

```python
REGRAS_ELEGIVEL = Regras(
    desconto_min_pct=25, realerta_queda_pct=5, liga_preco_max_idade_h=48,
    vendedor_min_positivas_pct=90, vendedor_min_avaliacoes=100,
)


def test_vendedor_elegivel():
    confiavel = Vendedor("Loja Boa", Decimal(98), 5000)
    poucas = Vendedor("Shazaar", Decimal(100), 66)
    assert vendedor_elegivel(Envio.AMAZON, None, REGRAS_ELEGIVEL)
    assert vendedor_elegivel(Envio.FBA, confiavel, REGRAS_ELEGIVEL)
    assert not vendedor_elegivel(Envio.FBA, poucas, REGRAS_ELEGIVEL)
    assert not vendedor_elegivel(Envio.FBA, None, REGRAS_ELEGIVEL)
    assert not vendedor_elegivel(Envio.PROPRIO, confiavel, REGRAS_ELEGIVEL)
    assert not vendedor_elegivel(Envio.DESCONHECIDO, confiavel, REGRAS_ELEGIVEL)
```

Em `tests/oportunidades/test_mensagens.py` acrescente (e `Detalhes` no import de `mensagens`):

```python
def test_mensagem_com_total_conferido_importado_prime_e_cupom():
    texto = mensagem_oportunidade(
        nome_produto="Aetherdrift Commander Deck - Eternal Might",
        leitura=Leitura(Decimal("285.99"), Envio.FBA, Vendedor("Shazaar", Decimal(100), 66)),
        ref=RefLiga(Decimal("400.00"), AGORA),
        url_amazon="https://www.amazon.com.br/dp/B0DNV55QBS",
        host="host.test",
        produto_id=7,
        detalhes=Detalhes(
            total_conferido=Decimal("285.99"), impostos=Decimal("48.26"), frete=Decimal("0.00"), importada=True,
            origem_envio="Estados Unidos", prime=True, cupom="15% off na 1ª compra com cartão Amazon",
        ),
    )
    linhas = texto.split("\n")
    assert linhas[1] == (
        "Amazon: R$ 285,99 conferido no checkout (impostos R$ 48,26, frete R$ 0,00) "
        "(vendido por Shazaar (100% de 66 avaliações), enviado pela Amazon · importado (EUA) · Prime), "
        "28% abaixo da Liga"
    )
    assert linhas[2] == "Cupom: 15% off na 1ª compra com cartão Amazon (condicional, não descontado)"
    assert linhas[3].startswith("Liga: a partir de R$ 400,00")


def test_mensagem_com_preco_anunciado_nao_conferido():
    texto = mensagem_oportunidade(
        nome_produto=NOME,
        leitura=Leitura(Decimal("275.91"), Envio.AMAZON, None),
        ref=RefLiga(Decimal("400.00"), AGORA),
        url_amazon="https://www.amazon.com.br/dp/B0TESTE123",
        host="host.test",
        produto_id=1,
        detalhes=Detalhes(motivo_nao_conferido="conferência desligada"),
    )
    assert texto.split("\n")[1] == (
        "Amazon: R$ 275,91, preço anunciado, não conferido (conferência desligada) (vendido pela Amazon), 31% abaixo da Liga"
    )


def test_mensagem_nao_conferida_sem_motivo_diz_aguardando_e_importado_sem_origem():
    texto = mensagem_oportunidade(
        nome_produto=NOME,
        leitura=Leitura(Decimal("275.91"), Envio.AMAZON, None),
        ref=RefLiga(Decimal("400.00"), AGORA),
        url_amazon="https://www.amazon.com.br/dp/B0TESTE123",
        host="host.test",
        produto_id=1,
        detalhes=Detalhes(importada=True),
    )
    assert "não conferido (aguardando conferência) (vendido pela Amazon · importado)" in texto
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t4 uv run pytest tests/oportunidades -q`
Expected: FAIL (ImportError: `vendedor_elegivel`, `Detalhes`).

- [ ] **Step 3: Motor**

Em `src/tcg_sniper/oportunidades/motor.py` troque `_vendedor_elegivel` por:

```python
def vendedor_elegivel(envio: Envio, vendedor: Vendedor | None, regras: Regras) -> bool:
    """Vendido pela Amazon sempre; lojista com envio pela Amazon (FBA) só se confiável; o resto nunca."""
    if envio is Envio.AMAZON:
        return True
    if envio is Envio.FBA:
        return vendedor_confiavel(vendedor, regras)
    return False
```

e em `elegivel` use `vendedor_elegivel(leitura.envio, leitura.vendedor, regras)` no lugar de `_vendedor_elegivel(leitura, regras)`. Atualize o docstring do módulo: "decide, para uma leitura da Amazon (melhor oferta da lista de ofertas, com o total do checkout quando conferido), ...".

- [ ] **Step 4: Mensagens**

Em `src/tcg_sniper/oportunidades/mensagens.py`:

```python
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from tcg_sniper.db.models import Envio
from tcg_sniper.formatacao import formatar_brl
from tcg_sniper.oportunidades.motor import Leitura, RefLiga, desconto_pct

PAISES_CURTOS = {"Estados Unidos": "EUA", "Estados Unidos da América": "EUA"}


@dataclass(frozen=True)
class Detalhes:
    """O que a lista de ofertas e a conferência de checkout acrescentam à mensagem."""

    total_conferido: Decimal | None = None  # total do checkout (itens + frete + impostos); None = não conferido
    impostos: Decimal | None = None
    frete: Decimal | None = None
    motivo_nao_conferido: str | None = None
    importada: bool = False
    origem_envio: str | None = None
    prime: bool = False
    cupom: str | None = None  # desconto condicional: só informação


def _preco(leitura: Leitura, detalhes: Detalhes | None) -> str:
    if detalhes is None:
        return formatar_brl(leitura.preco)
    if detalhes.total_conferido is not None:
        partes = [f"impostos {formatar_brl(detalhes.impostos)}"] if detalhes.impostos is not None else []
        if detalhes.frete is not None:
            partes.append(f"frete {formatar_brl(detalhes.frete)}")
        sufixo = f" ({', '.join(partes)})" if partes else ""
        return f"{formatar_brl(detalhes.total_conferido)} conferido no checkout{sufixo}"
    motivo = detalhes.motivo_nao_conferido or "aguardando conferência"
    return f"{formatar_brl(leitura.preco)}, preço anunciado, não conferido ({motivo})"


def _selos(detalhes: Detalhes | None) -> str:
    if detalhes is None:
        return ""
    selos = []
    if detalhes.importada:
        origem = PAISES_CURTOS.get(detalhes.origem_envio or "", detalhes.origem_envio)
        selos.append(f"importado ({origem})" if origem else "importado")
    if detalhes.prime:
        selos.append("Prime")
    return "".join(f" · {selo}" for selo in selos)
```

e em `mensagem_oportunidade` acrescente o parâmetro `detalhes: Detalhes | None = None` e troque a montagem:

```python
    linhas = [
        f"Oportunidade: {nome_produto}",
        f"{amazon}: {_preco(leitura, detalhes)} ({_quem_vende(leitura)}{_selos(detalhes)}), {desconto}% abaixo da Liga",
    ]
    if detalhes is not None and detalhes.cupom:
        linhas.append(f"Cupom: {detalhes.cupom} (condicional, não descontado)")
    linhas += [liga, url_amazon, f"Admin: http://{host}:8000/produto/{produto_id}"]
    return "\n".join(linhas)
```

- [ ] **Step 5: Rodar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t4 uv run pytest -q && uv run ruff check .`
Expected: PASS (os testes antigos de mensagem, sem `detalhes`, continuam iguais).

- [ ] **Step 6: Commit**

```bash
git add src/tcg_sniper/oportunidades/motor.py src/tcg_sniper/oportunidades/mensagens.py tests/oportunidades/test_motor.py tests/oportunidades/test_mensagens.py
git commit -m "feat: opportunity message with checked checkout total or unchecked advertised price, import and Prime badges"
```

---

### Task 5: Ferramenta de captura e comando `tcg-sniper amazon capturar`

**Files:**
- Create: `src/tcg_sniper/coletor_amazon/captura.py`
- Modify: `src/tcg_sniper/cli.py`
- Test: `tests/coletor_amazon/test_captura.py` (novo), `tests/test_cli.py` (acrescenta)

**Interfaces:**
- Consumes (Task 1): `cliques.ADICIONAR`, `FECHAR_PEDIDO`, `ENTREGAR`, `ESCOPO_OFERTA_DESTAQUE`, `ESCOPOS_CARRINHO_ATIVO`, `CliqueProibido`, `SeletorAusente`, `clicar_permitido`, `localizar`, `remover_do_carrinho`; `parsers.URL_CARRINHO`, `SELETOR_PAINEL_OFERTAS`, `url_ofertas`, `url_painel_ofertas`; `fakes.NavegadorInterativoFake`.
- Produces:
  - `captura.URL_TESTE_LOGIN: str`, `captura.ESPERA_PAINEL_MS = 15_000`.
  - `captura.Captura(destino: Path, salvas: list[Path], avisos: list[str])` com `salvar(nome: str, pagina: Pagina) -> None`.
  - `captura.carrinho_vazio(pagina: Pagina) -> bool`.
  - `captura.capturar(nav: NavegadorInterativo, asins: Sequence[str], destino: Path, *, checkout: bool, pausar: Callable[[], None]) -> Captura`. Arquivos: `carrinho_inicial`, `ofertas_<ASIN>`, `painel_<ASIN>` e, com `checkout`, `apos_adicionar`, `carrinho_um_item`, `checkout_1`, `checkout_resumo` (se houve o passo do endereço), `parou_aqui` (se algo falhou), `carrinho_vazio` (depois de tirar o item).
  - `captura.capturar_login(nav: Navegador, destino: Path) -> Path` (`login.html`).
  - CLI: `tcg-sniper amazon capturar --asin X [--asin Y ...] [--checkout] [--login]`; recusa rodar com o `coletor-amazon` de pé (lock `ID_LOCK_AMAZON`); grava em `<DIR_DADOS>/capturas/<AAAAMMDD-HHMMSS>/`.

- [ ] **Step 1: Testes (falham)**

Create `tests/coletor_amazon/test_captura.py`:

```python
from fakes import NavegadorInterativoFake, pagina_html

from tcg_sniper.coletor_amazon.captura import URL_TESTE_LOGIN, capturar, capturar_login, carrinho_vazio
from tcg_sniper.coletor_amazon.parsers import URL_CARRINHO, url_ofertas, url_painel_ofertas

ASIN = "B0DNV55QBS"
FECHAR = '<input name="proceedToRetailCheckout" value="Fechar pedido" type="submit">'


def carrinho(*ativos, com_botao=True):
    itens = "".join(
        f'<div data-asin="{a}"><input data-action="delete" value="Excluir" type="submit"></div>' for a in ativos
    )
    botao = FECHAR if ativos and com_botao else ""
    return pagina_html(
        f'<html><body><span id="nav-cart-count">{len(ativos)}</span><div data-name="Active Items">{itens}</div>{botao}</body></html>',
        url=URL_CARRINHO,
    )


PAINEL = pagina_html(
    '<html><body><input id="buy-now-button" name="submit.buy-now" value="Comprar agora" type="submit">'
    '<div id="aod-pinned-offer"><input name="submit.addToCart" value="Adicionar ao carrinho" type="submit"></div></body></html>',
    url=url_painel_ofertas(ASIN),
)
OFERTAS = pagina_html('<html><body><div id="aod-pinned-offer">R$ 314,11</div></body></html>', url=url_ofertas(ASIN))
APOS = pagina_html("<html><body>adicionado</body></html>", url="https://www.amazon.com.br/cart/smart-wagon")
ENDERECO = pagina_html(
    '<html><body><input data-testid="Address_selectShipToThisAddress" type="submit" value="Entregar neste endereço">'
    "<div>Itens: -- Total do pedido: R$ 237,73</div></body></html>",
    url="https://www.amazon.com.br/checkout/p/p-1/address",
)
RESUMO = pagina_html(
    '<html><body><input name="placeYourOrder1" type="submit" value="Confirmar pedido com cartão 0000">'
    "<div>Itens: R$ 237,73 Total do pedido: R$ 285,99</div></body></html>",
    url="https://www.amazon.com.br/checkout/p/p-1/spc",
)


def nomes(captura):
    return [p.name for p in captura.salvas]


def test_carrinho_vazio_so_com_contador_zero_e_sem_itens():
    assert carrinho_vazio(carrinho())
    assert not carrinho_vazio(carrinho("B0OUTRO001"))
    assert not carrinho_vazio(pagina_html("<html><body>sem contador</body></html>"))


def test_captura_completa_salva_tudo_clica_so_o_permitido_e_tira_o_item(tmp_path):
    nav = NavegadorInterativoFake(
        {
            URL_CARRINHO: [carrinho(), carrinho(ASIN), carrinho(ASIN), carrinho()],
            url_ofertas(ASIN): OFERTAS,
            url_painel_ofertas(ASIN): [PAINEL, PAINEL],
        },
        apos_clique=[APOS, ENDERECO, RESUMO, carrinho()],
    )
    cap = capturar(nav, [ASIN], tmp_path, checkout=True, pausar=lambda: None)
    assert cap.avisos == []
    assert nomes(cap) == [
        "carrinho_inicial.html", f"ofertas_{ASIN}.html", f"painel_{ASIN}.html", "apos_adicionar.html",
        "carrinho_um_item.html", "checkout_1.html", "checkout_resumo.html", "carrinho_vazio.html",
    ]
    assert [seletor for seletor, _ in nav.cliques] == [
        '#aod-pinned-offer input[name="submit.addToCart"]',
        'input[name="proceedToRetailCheckout"]',
        'input[data-testid="Address_selectShipToThisAddress"]',
        f'[data-name="Active Items"] [data-asin="{ASIN}"] input[data-action="delete"]',
    ]
    assert (tmp_path / "checkout_resumo.html").read_text(encoding="utf-8") == RESUMO.html


def test_carrinho_com_itens_nao_clica_em_nada(tmp_path):
    nav = NavegadorInterativoFake(
        {URL_CARRINHO: carrinho("B0OUTRO001", "B0OUTRO002"), url_ofertas(ASIN): OFERTAS, url_painel_ofertas(ASIN): PAINEL}
    )
    cap = capturar(nav, [ASIN], tmp_path, checkout=True, pausar=lambda: None)
    assert nav.cliques == []
    assert nomes(cap) == ["carrinho_inicial.html", f"ofertas_{ASIN}.html", f"painel_{ASIN}.html"]
    assert any("carrinho com itens" in aviso for aviso in cap.avisos)


def test_falha_no_meio_salva_onde_parou_e_ainda_tira_o_item(tmp_path):
    nav = NavegadorInterativoFake(
        {
            URL_CARRINHO: [carrinho(), carrinho(ASIN, com_botao=False), carrinho(ASIN), carrinho()],
            url_ofertas(ASIN): OFERTAS,
            url_painel_ofertas(ASIN): [PAINEL, PAINEL],
        },
        apos_clique=[APOS, carrinho()],
    )
    cap = capturar(nav, [ASIN], tmp_path, checkout=True, pausar=lambda: None)
    assert "parou_aqui.html" in nomes(cap) and nomes(cap)[-1] == "carrinho_vazio.html"
    assert any("fechar pedido" in aviso for aviso in cap.avisos)
    assert [seletor for seletor, _ in nav.cliques][-1].endswith('input[data-action="delete"]')


def test_sem_checkout_so_le(tmp_path):
    nav = NavegadorInterativoFake(
        {URL_CARRINHO: carrinho(), url_ofertas(ASIN): OFERTAS, url_painel_ofertas(ASIN): PAINEL}
    )
    cap = capturar(nav, [ASIN], tmp_path, checkout=False, pausar=lambda: None)
    assert nav.cliques == [] and len(cap.salvas) == 3
    assert nav.esperas == [(url_painel_ofertas(ASIN), "#aod-pinned-offer, #aod-offer")]


def test_capturar_login(tmp_path):
    nav = NavegadorInterativoFake({URL_TESTE_LOGIN: pagina_html('<html><body><form name="signIn"></form></body></html>')})
    assert capturar_login(nav, tmp_path).name == "login.html"
```

Em `tests/test_cli.py` acrescente:

```python
def test_amazon_capturar_recusa_com_o_coletor_rodando(monkeypatch):
    from contextlib import contextmanager

    from tcg_sniper.coletor_liga import agendador

    @contextmanager
    def lock_ocupado(_engine, _id):
        yield False

    monkeypatch.setattr(agendador, "lock_coleta", lock_ocupado)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x@y/z")
    with pytest.raises(SystemExit, match="docker compose stop coletor-amazon"):
        cli.main(["amazon", "capturar", "--asin", "B0DNV55QBS"])


def test_amazon_capturar_exige_asin():
    with pytest.raises(SystemExit):
        cli.main(["amazon", "capturar"])
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t5 uv run pytest tests/coletor_amazon/test_captura.py tests/test_cli.py -q`
Expected: FAIL (ImportError: `captura`; subcomando `amazon` inexistente).

- [ ] **Step 3: `captura.py`**

Create `src/tcg_sniper/coletor_amazon/captura.py`:

```python
"""Captura das páginas reais da Amazon para as fixtures do monitor e da conferência de checkout.

Roda com o coletor parado (mesmo perfil do Chromium, logado antes pelo noVNC). Salva as páginas
inteiras em <DIR_DADOS>/capturas/<data>/ (fora do git); elas só viram fixture depois de
scripts/anonimizar_fixture.py. Com `checkout`, adiciona a oferta em destaque do primeiro ASIN, vai
até o resumo do pedido (sem confirmar) e tira o item, sempre pelos cliques de `cliques.py`; com
qualquer item no carrinho ativo, não clica em nada."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from selectolax.lexbor import LexborHTMLParser

from tcg_sniper.coletor_amazon.cliques import (
    ADICIONAR,
    ENTREGAR,
    ESCOPO_OFERTA_DESTAQUE,
    ESCOPOS_CARRINHO_ATIVO,
    FECHAR_PEDIDO,
    CliqueProibido,
    SeletorAusente,
    clicar_permitido,
    localizar,
    remover_do_carrinho,
)
from tcg_sniper.coletor_amazon.parsers import SELETOR_PAINEL_OFERTAS, URL_CARRINHO, url_ofertas, url_painel_ofertas
from tcg_sniper.navegador.base import Navegador, NavegadorInterativo
from tcg_sniper.navegador.modelos import ErroRede, Pagina

# Sem sessão, o resumo do pedido manda para a página de login.
URL_TESTE_LOGIN = "https://www.amazon.com.br/gp/buy/spc/handlers/display.html?hasWorkingJavascript=1"
ESPERA_PAINEL_MS = 15_000


@dataclass
class Captura:
    destino: Path
    salvas: list[Path] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    def salvar(self, nome: str, pagina: Pagina) -> None:
        caminho = self.destino / f"{nome}.html"
        caminho.write_text(pagina.html, encoding="utf-8")
        self.salvas.append(caminho)


def carrinho_vazio(pagina: Pagina) -> bool:
    """Só com o contador do carrinho lido e igual a zero, e nenhum item nos blocos do carrinho ativo."""
    arvore = LexborHTMLParser(pagina.html)
    contador = arvore.css_first("#nav-cart-count")
    if contador is None or contador.text(strip=True) != "0":
        return False
    return not any(arvore.css_first(f"{ativo} [data-asin]") is not None for ativo in ESCOPOS_CARRINHO_ATIVO)


def capturar(
    nav: NavegadorInterativo, asins: Sequence[str], destino: Path, *, checkout: bool, pausar: Callable[[], None]
) -> Captura:
    destino.mkdir(parents=True, exist_ok=True)
    cap = Captura(destino)
    carrinho = nav.abrir(URL_CARRINHO)
    cap.salvar("carrinho_inicial", carrinho)
    for asin in asins:
        pausar()
        cap.salvar(f"ofertas_{asin}", nav.abrir(url_ofertas(asin)))
        pausar()
        cap.salvar(f"painel_{asin}", nav.abrir_e_esperar(url_painel_ofertas(asin), SELETOR_PAINEL_OFERTAS, ESPERA_PAINEL_MS))
    if not checkout:
        return cap
    if not carrinho_vazio(carrinho):
        cap.avisos.append("carrinho com itens (ou contador ilegível): checkout não capturado, nada foi clicado")
        return cap
    asin = asins[0]
    adicionou = False
    try:
        pausar()
        painel = nav.abrir_e_esperar(url_painel_ofertas(asin), SELETOR_PAINEL_OFERTAS, ESPERA_PAINEL_MS)
        pausar()
        adicionou = True  # daqui em diante pode haver item nosso no carrinho, mesmo se o clique der erro
        cap.salvar("apos_adicionar", clicar_permitido(nav, ADICIONAR, painel, ESCOPO_OFERTA_DESTAQUE))
        pausar()
        carrinho = nav.abrir(URL_CARRINHO)
        cap.salvar("carrinho_um_item", carrinho)
        pausar()
        pagina = clicar_permitido(nav, FECHAR_PEDIDO, carrinho)
        cap.salvar("checkout_1", pagina)
        if localizar(ENTREGAR, pagina) is not None:
            pausar()
            cap.salvar("checkout_resumo", clicar_permitido(nav, ENTREGAR, pagina))
    except (SeletorAusente, CliqueProibido, ErroRede) as erro:
        cap.avisos.append(f"captura do checkout parou: {erro}")
        try:
            cap.salvar("parou_aqui", nav.atual())
        except ErroRede:
            pass
    finally:
        if adicionou:
            removido, _ = remover_do_carrinho(nav, asin, nav.abrir, pausar)
            cap.salvar("carrinho_vazio", nav.atual())
            if not removido:
                cap.avisos.append(f"o item {asin} pode ter ficado no carrinho: confira pelo noVNC e exclua à mão")
    return cap


def capturar_login(nav: Navegador, destino: Path) -> Path:
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / "login.html"
    caminho.write_text(nav.abrir(URL_TESTE_LOGIN).html, encoding="utf-8")
    return caminho
```

- [ ] **Step 4: CLI**

Em `src/tcg_sniper/cli.py`, depois do subparser `ia`:

```python
    amazon = sub.add_parser("amazon", help="ferramentas da Amazon")
    amazon_sub = amazon.add_subparsers(dest="acao_amazon", required=True)
    capturar_p = amazon_sub.add_parser(
        "capturar", help="salva páginas reais para as fixtures (pare o coletor-amazon antes)"
    )
    capturar_p.add_argument("--asin", action="append", required=True, type=str.upper, help="pode repetir")
    capturar_p.add_argument(
        "--checkout", action="store_true",
        help="também põe a oferta em destaque do 1º ASIN no carrinho, vai ao resumo do pedido (sem confirmar) e tira o item",
    )
    capturar_p.add_argument("--login", action="store_true", help="também salva a página de login (perfil temporário)")
```

e no despacho, antes de `elif args.comando == "admin":`:

```python
    elif args.comando == "amazon":
        import random
        import tempfile
        import time
        from pathlib import Path

        from tcg_sniper.coletor_amazon.captura import capturar, capturar_login
        from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon
        from tcg_sniper.coletor_amazon.varredura import ID_LOCK_AMAZON
        from tcg_sniper.coletor_liga import agendador
        from tcg_sniper.db import repositorio as repo
        from tcg_sniper.navegador.chromium import NavegadorChromium

        destino = config.dir_dados / "capturas" / f"{repo.agora_utc():%Y%m%d-%H%M%S}"

        def pausar() -> None:
            time.sleep(random.uniform(3, 8))

        with agendador.lock_coleta(engine, ID_LOCK_AMAZON) as obtido:
            if not obtido:
                raise SystemExit("o coletor-amazon está rodando (mesmo perfil do Chromium): docker compose stop coletor-amazon")
            with NavegadorChromium(config.dir_dados / "perfil-amazon", eh_desafio_amazon) as nav:
                cap = capturar(nav, args.asin, destino, checkout=args.checkout, pausar=pausar)
            if args.login:
                with tempfile.TemporaryDirectory() as perfil, NavegadorChromium(Path(perfil), eh_desafio_amazon) as anonimo:
                    cap.salvas.append(capturar_login(anonimo, destino))
        for caminho in cap.salvas:
            print(caminho)
        for aviso in cap.avisos:
            print(f"AVISO: {aviso}")
```

(`agendador.lock_coleta` pelo módulo, para o teste poder trocar o lock.)

- [ ] **Step 5: Rodar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t5 uv run pytest -q && uv run ruff check .`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/tcg_sniper/coletor_amazon/captura.py src/tcg_sniper/cli.py tests/coletor_amazon/test_captura.py tests/test_cli.py
git commit -m "feat: amazon capturar command to save real offer, cart and checkout pages with the collector profile"
```

---

### Task 6: Origem do casamento e casador só para quem não tem par

**Files:**
- Modify: `src/tcg_sniper/db/repositorio_amazon.py` (`confirmar_casamento`, `ignorar_anuncio`, `desfazer_casamento`, `casar_link_manual`)
- Modify: `src/tcg_sniper/db/repositorio_ia.py` (`origem_da_decisao`, `pares_pendentes(so_descoberta=...)`)
- Modify: `src/tcg_sniper/casador/servico.py`
- Modify: `src/tcg_sniper/admin/app.py` (só `revisar_casamento`)
- Test: `tests/db/test_repositorio_amazon.py`, `tests/db/test_repositorio_ia.py`, `tests/casador/test_servico.py`, `tests/admin/test_admin_casamentos.py` (acrescenta)

**Interfaces:**
- Consumes (Task 3): `models.OrigemCasamento`, `AnuncioAmazon.origem_casamento`.
- Produces:
  - `repositorio_amazon.confirmar_casamento(s, anuncio_id, produto_id, agora, origem: OrigemCasamento = OrigemCasamento.MANUAL) -> bool`
  - `repositorio_amazon.ignorar_anuncio(s, anuncio_id, agora, origem: OrigemCasamento = OrigemCasamento.MANUAL) -> bool`
  - `repositorio_amazon.desfazer_casamento(...)` limpa a origem; `casar_link_manual(...)` grava `manual`.
  - `repositorio_ia.origem_da_decisao(s, anuncio_id: int, produto_id: int | None) -> OrigemCasamento` (`sugerido_ia` se há avaliação da IA para o par, senão `manual`).
  - `repositorio_ia.pares_pendentes(s, so_descoberta: bool = False) -> list[ParPendente]`: com `so_descoberta`, pula pendentes de produto já casado vistos antes do primeiro casamento dele.

- [ ] **Step 1: Testes (falham)**

Em `tests/db/test_repositorio_amazon.py` acrescente (importe `OrigemCasamento` de `tcg_sniper.db.models`):

```python
def test_origem_do_casamento_em_cada_decisao(s):
    produto = criar_produto(s, "p1")
    a = criar_anuncio(s, "B0ORIG0001", produto=produto)
    b = criar_anuncio(s, "B0ORIG0002", produto=produto)
    assert a.origem_casamento is None
    repo.confirmar_casamento(s, a.id, produto.id, T0)
    assert a.origem_casamento is OrigemCasamento.MANUAL
    repo.ignorar_anuncio(s, b.id, T0, OrigemCasamento.SUGERIDO_IA)
    assert b.origem_casamento is OrigemCasamento.SUGERIDO_IA
    repo.confirmar_casamento(s, b.id, produto.id, T0, OrigemCasamento.AUTOMATICO_IA)
    assert b.origem_casamento is OrigemCasamento.AUTOMATICO_IA
    repo.desfazer_casamento(s, b.id, T0)
    assert b.origem_casamento is None


def test_link_manual_tem_origem_manual(s):
    produto = criar_produto(s, "p1")
    novo = repo.casar_link_manual(s, produto.id, "B0ORIG0003", T0)
    existente = criar_anuncio(s, "B0ORIG0004", produto=produto)
    repo.ignorar_anuncio(s, existente.id, T0, OrigemCasamento.SUGERIDO_IA)
    repo.casar_link_manual(s, produto.id, "B0ORIG0004", T0)
    assert novo.origem_casamento is OrigemCasamento.MANUAL
    assert existente.origem_casamento is OrigemCasamento.MANUAL
```

Em `tests/db/test_repositorio_ia.py` acrescente (importe `OrigemCasamento`):

```python
def test_origem_da_decisao(s):
    p = criar_produto(s, "p1")
    a = criar_anuncio(s, "B1", produto=p)
    b = criar_anuncio(s, "B2", produto=p)
    repo_ia.gravar_avaliacao(
        s, anuncio_id=a.id, produto_id=p.id, mesmo_produto=True, confianca=95, motivo="m", modelo="gpt-5",
        assinatura="x", sem_imagem=False, chamada_id=None, agora=T0,
    )
    assert repo_ia.origem_da_decisao(s, a.id, p.id) is OrigemCasamento.SUGERIDO_IA
    assert repo_ia.origem_da_decisao(s, b.id, p.id) is OrigemCasamento.MANUAL
    assert repo_ia.origem_da_decisao(s, a.id, None) is OrigemCasamento.MANUAL


def test_pares_pendentes_so_descoberta_pula_os_antigos_de_produto_casado(s):
    casado = criar_produto(s, "casado")
    livre = criar_produto(s, "livre")
    criar_anuncio(s, "B0", produto=casado, status=StatusCasamento.CONFIRMADO).revisado_em = T0
    antigo = criar_anuncio(s, "B1", produto=casado, agora=T0 - timedelta(days=1))
    da_semanal = criar_anuncio(s, "B2", produto=casado, agora=T0 + timedelta(days=7))
    de_livre = criar_anuncio(s, "B3", produto=livre, agora=T0 - timedelta(days=1))
    s.flush()
    assert {p.anuncio.id for p in repo_ia.pares_pendentes(s, so_descoberta=True)} == {da_semanal.id, de_livre.id}
    assert {p.anuncio.id for p in repo_ia.pares_pendentes(s)} == {antigo.id, da_semanal.id, de_livre.id}
```

Em `tests/casador/test_servico.py` acrescente:

```python
def test_automatico_grava_a_origem_automatico_ia(sessoes, config):
    configurar(sessoes, automatico=True, confianca_confirmar=90)
    _, [a] = pares(sessoes)
    sv, _, _ = servico(sessoes, config, [veredito(True, 95)])
    sv.ciclo()
    with sessoes() as s:
        assert s.get(AnuncioAmazon, a).origem_casamento is OrigemCasamento.AUTOMATICO_IA


def test_nao_avalia_pendente_antigo_de_produto_ja_casado(sessoes, config):
    configurar(sessoes)
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Caixa Alfa")
        criar_anuncio(s, "B0CASADO", produto=p, status=StatusCasamento.CONFIRMADO).revisado_em = T0
        criar_anuncio(s, "B1ANTIGO", produto=p, agora=T0 - timedelta(days=1))
    sv, t, _ = servico(sessoes, config, [])
    assert sv.ciclo() == 0 and t.pedidos == []
```

(importe `OrigemCasamento` de `tcg_sniper.db.models`.)

Em `tests/admin/test_admin_casamentos.py` acrescente (use o fixture `cliente` do arquivo e `criar_produto`/`criar_anuncio`; importe `repositorio_ia as repo_ia` e `OrigemCasamento`):

```python
def test_decisao_no_admin_grava_sugerido_ia_ou_manual(cliente, sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Caixa Alfa")
        avaliado = criar_anuncio(s, "B0AVALIADO", produto=p)
        sem_ia = criar_anuncio(s, "B0SEMIA001", produto=p)
        repo_ia.gravar_avaliacao(
            s, anuncio_id=avaliado.id, produto_id=p.id, mesmo_produto=True, confianca=80, motivo="m",
            modelo="gpt-5", assinatura="x", sem_imagem=False, chamada_id=None, agora=T0,
        )
        ids = (p.id, avaliado.id, sem_ia.id)
    produto_id, avaliado_id, sem_ia_id = ids
    cliente.post(f"/casamentos/{avaliado_id}", data={"acao": "confirmar", "produto_id": str(produto_id)})
    cliente.post(f"/casamentos/{sem_ia_id}", data={"acao": "ignorar"})
    with sessoes() as s:
        assert s.get(AnuncioAmazon, avaliado_id).origem_casamento is OrigemCasamento.SUGERIDO_IA
        assert s.get(AnuncioAmazon, sem_ia_id).origem_casamento is OrigemCasamento.MANUAL
```

(se `AnuncioAmazon`/`T0` não estiverem importados no arquivo, importe-os de `tcg_sniper.db.models` e `fakes`.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t6 uv run pytest tests/db tests/casador tests/admin/test_admin_casamentos.py -q`
Expected: FAIL (`confirmar_casamento` sem `origem`; `origem_da_decisao` inexistente).

- [ ] **Step 3: Repositórios**

Em `src/tcg_sniper/db/repositorio_amazon.py` (importe `OrigemCasamento`):

```python
def confirmar_casamento(
    s: Session, anuncio_id: int, produto_id: int, agora: datetime, origem: OrigemCasamento = OrigemCasamento.MANUAL
) -> bool:
    """Confirma (ou troca) o produto da Liga do anúncio. Trocar fecha as oportunidades abertas."""
    anuncio = s.get(AnuncioAmazon, anuncio_id)
    if anuncio is None:
        return False
    if anuncio.produto_id != produto_id:
        fechar_oportunidades_do_anuncio(s, anuncio_id, agora)
    anuncio.produto_id = produto_id
    anuncio.status_casamento = StatusCasamento.CONFIRMADO
    anuncio.revisado_em = agora
    anuncio.origem_casamento = origem
    s.flush()
    return True


def ignorar_anuncio(
    s: Session, anuncio_id: int, agora: datetime, origem: OrigemCasamento = OrigemCasamento.MANUAL
) -> bool:
    anuncio = s.get(AnuncioAmazon, anuncio_id)
    if anuncio is None:
        return False
    fechar_oportunidades_do_anuncio(s, anuncio_id, agora)
    anuncio.status_casamento = StatusCasamento.IGNORADO
    anuncio.revisado_em = agora
    anuncio.origem_casamento = origem
    s.flush()
    return True
```

Em `desfazer_casamento`, junto de `anuncio.revisado_em = None`: `anuncio.origem_casamento = None`. Em `casar_link_manual`, no `AnuncioAmazon(...)` novo acrescente `origem_casamento=OrigemCasamento.MANUAL`, e a chamada do existente fica `confirmar_casamento(s, anuncio.id, produto_id, agora, OrigemCasamento.MANUAL)`.

Em `src/tcg_sniper/db/repositorio_ia.py` (importe `or_` de `sqlalchemy`, `aliased` de `sqlalchemy.orm`, `OrigemCasamento` de `db.models`):

```python
def origem_da_decisao(s: Session, anuncio_id: int, produto_id: int | None) -> OrigemCasamento:
    """Decisão do usuário: `sugerido_ia` se a IA avaliou este par (anúncio, produto), senão `manual`."""
    if produto_id is None:
        return OrigemCasamento.MANUAL
    avaliada = s.scalar(
        select(AvaliacaoIA.id).where(AvaliacaoIA.anuncio_id == anuncio_id, AvaliacaoIA.produto_id == produto_id).limit(1)
    )
    return OrigemCasamento.SUGERIDO_IA if avaliada is not None else OrigemCasamento.MANUAL
```

Em `pares_pendentes`, acrescente o parâmetro e o filtro (antes do `return`):

```python
def pares_pendentes(s: Session, so_descoberta: bool = False) -> list[ParPendente]:
    """Anúncios pendentes com produto sugerido, com a avaliação desse par (se houver) e os preços atuais.
    Produtos ativos primeiro; depois os vistos mais recentemente. Com `so_descoberta` (o casador), pula
    os de produto já casado, exceto os vistos pela primeira vez depois do primeiro casamento do produto
    (os anúncios novos da busca semanal)."""
    consulta = (
        select(AnuncioAmazon, ProdutoLiga, AvaliacaoIA, PrecoAtualLiga.preco_a_partir, PrecoAtualAmazon.preco)
        .join(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .outerjoin(
            AvaliacaoIA,
            and_(AvaliacaoIA.anuncio_id == AnuncioAmazon.id, AvaliacaoIA.produto_id == AnuncioAmazon.produto_id),
        )
        .outerjoin(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .outerjoin(PrecoAtualAmazon, PrecoAtualAmazon.anuncio_id == AnuncioAmazon.id)
        .where(AnuncioAmazon.status_casamento == StatusCasamento.PENDENTE)
        .order_by(ProdutoLiga.ativo.desc(), AnuncioAmazon.visto_ultimo_em.desc(), AnuncioAmazon.id)
    )
    if so_descoberta:
        casado = aliased(AnuncioAmazon)
        casado_desde = (
            select(func.min(casado.revisado_em))
            .where(casado.produto_id == AnuncioAmazon.produto_id, casado.status_casamento == StatusCasamento.CONFIRMADO)
            .scalar_subquery()
        )
        consulta = consulta.where(or_(casado_desde.is_(None), AnuncioAmazon.visto_primeiro_em > casado_desde))
    return [ParPendente(*linha) for linha in s.execute(consulta)]
```

(A consulta é a de hoje, sem mudança; o que entra é o parâmetro e o bloco `if so_descoberta`.)

- [ ] **Step 4: Casador e admin**

Em `src/tcg_sniper/casador/servico.py` (importe `OrigemCasamento`): em `ciclo`, `pendentes = repo_ia.pares_pendentes(s, so_descoberta=True)`; em `_aplicar`, `repo_amz.confirmar_casamento(s, anuncio.id, av.produto_id, agora, OrigemCasamento.AUTOMATICO_IA)` e `repo_amz.ignorar_anuncio(s, anuncio.id, agora, OrigemCasamento.AUTOMATICO_IA)`.

Em `src/tcg_sniper/admin/app.py`, `revisar_casamento` (o `repo_ia` já é importado no arquivo):

```python
            if acao == "confirmar":
                texto = formulario.get("produto_id", "").strip()
                if not (texto.isdecimal() and len(texto) <= 9):
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "produto_id inválido")
                destino_produto = s.get(ProdutoLiga, int(texto))
                if destino_produto is None or not destino_produto.ativo:
                    raise HTTPException(status.HTTP_404_NOT_FOUND)
                origem = repo_ia.origem_da_decisao(s, anuncio_id, int(texto))
                repo_amz.confirmar_casamento(s, anuncio_id, int(texto), agora, origem)
            elif acao == "ignorar":
                sugerido = s.get(AnuncioAmazon, anuncio_id).produto_id
                repo_amz.ignorar_anuncio(s, anuncio_id, agora, repo_ia.origem_da_decisao(s, anuncio_id, sugerido))
            else:
                repo_amz.desfazer_casamento(s, anuncio_id, agora)
```

- [ ] **Step 5: Rodar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t6 uv run pytest -q && uv run ruff check .`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/tcg_sniper/db/repositorio_amazon.py src/tcg_sniper/db/repositorio_ia.py src/tcg_sniper/casador/servico.py src/tcg_sniper/admin/app.py tests/db/test_repositorio_amazon.py tests/db/test_repositorio_ia.py tests/casador/test_servico.py tests/admin/test_admin_casamentos.py
git commit -m "feat: record who decided each match (manual, AI suggestion, AI automatic); casador skips products already matched"
```

---

### Task 7: Admin — ofertas da última leitura, conferência e origem do casamento

**Files:**
- Modify: `src/tcg_sniper/admin/consultas_amazon.py`
- Modify: `src/tcg_sniper/admin/templates/_componentes.html`, `casamentos_produto.html`, `produto.html`, `ofertas.html`
- Modify: `src/tcg_sniper/admin/static/admin.css` (regenerado)
- Test: `tests/admin/test_admin_monitor_ofertas.py` (novo)

**Interfaces:**
- Consumes (Task 3): `repositorio_amazon.ofertas_da_ultima_leitura`, `conferencia_valida`, `gravar_ofertas`, `OfertaAvaliada`, `registrar_conferencia`; `models.OfertaAmazon`, `ConferenciaCheckout`, `OrigemCasamento`, `OrigemPreco.OFERTAS`; `fakes.oferta_lista`.
- Produces:
  - `consultas_amazon.LinhaAnuncio` ganha `ofertas: tuple[OfertaAmazon, ...] = ()` e `conferencia: ConferenciaCheckout | None = None` (preenchidos nos confirmados de `detalhe_casamento` e em `amazon_do_produto`).
  - `consultas_amazon.LinhaOferta` ganha `origem_casamento: OrigemCasamento | None = None`, `conferencia: ConferenciaCheckout | None = None`, `importada: bool = False`, `origem_envio: str | None = None`, `prime: bool = False`.
  - `detalhe_casamento(s, produto_id, config, agora: datetime | None = None)`, `amazon_do_produto(s, produto_id, config, agora: datetime | None = None)`.
  - Leitura de origem `ofertas` conta como verificada (selo do vendedor).
  - Macros em `_componentes.html`: `selo_origem(origem)`, `preco_conferido(conferencia)`, `selos_oferta(importada, origem_envio, prime)`, `tabela_ofertas(ofertas)`. O selo "pela IA" some.

- [ ] **Step 1: Testes (falham)**

Create `tests/admin/test_admin_monitor_ofertas.py`:

```python
import base64
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto, oferta_lista
from fastapi.testclient import TestClient

from tcg_sniper.admin import consultas_amazon
from tcg_sniper.admin.app import criar_app
from tcg_sniper.admin.consultas_amazon import FiltroOfertas
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import Envio, OrigemCasamento, OrigemPreco, SituacaoCheckout, StatusCasamento

SP = ZoneInfo("America/Sao_Paulo")


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


@pytest.fixture
def cenario(sessoes):
    """Um produto com um anúncio confirmado pela IA, lido duas vezes pelo monitor, com conferência ok."""
    agora = T0
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Aetherdrift Commander")
        criar_preco_liga(s, p, "400.00", listagem_em=T0)
        a = criar_anuncio(s, "B0DNV55QBS", produto=p, status=StatusCasamento.CONFIRMADO)
        a.origem_casamento = OrigemCasamento.AUTOMATICO_IA
        antiga = oferta_lista("300.00", vendedor="Loja Antiga")
        repo_amz.gravar_ofertas(s, a.id, T0 - timedelta(minutes=30), [repo_amz.OfertaAvaliada(antiga, None, True, True)])
        shazaar = oferta_lista("275.91", importada=True, origem_envio="Estados Unidos", prime=True)
        global_ = oferta_lista("314.11", vendedor="Amazon Global", seller_id="amazon", envio=Envio.AMAZON, posicao=0)
        repo_amz.gravar_ofertas(
            s, a.id, agora,
            [repo_amz.OfertaAvaliada(shazaar, None, True, True), repo_amz.OfertaAvaliada(global_, None, True, False)],
        )
        repo_amz.registrar_preco(s, a.id, Decimal("275.91"), OrigemPreco.OFERTAS, None, Envio.FBA, agora, SP)
        repo_amz.registrar_conferencia(
            s, em=agora, anuncio_id=a.id, vendedor_nome="Shazaar", preco_anunciado=Decimal("275.91"),
            itens=Decimal("237.73"), frete=Decimal("0.00"), impostos=Decimal("48.26"), total=Decimal("285.99"),
            situacao=SituacaoCheckout.OK, motivo=None, item_removido=True,
        )
        return p.id, a.id


def test_detalhe_casamento_traz_as_ofertas_da_ultima_leitura_e_a_conferencia(sessoes, cenario):
    produto_id, anuncio_id = cenario
    with sessoes() as s:
        d = consultas_amazon.detalhe_casamento(s, produto_id, repo_amz.obter_config(s), T0)
    [linha] = d.confirmados
    assert [(o.vendedor_nome, o.melhor) for o in linha.ofertas] == [("Shazaar", True), ("Amazon Global", False)]
    assert linha.conferencia.total == Decimal("285.99")
    assert linha.verificado  # leitura de ofertas conta como verificada


def test_conferencia_vencida_ou_de_outra_oferta_nao_vale(sessoes, cenario):
    produto_id, _ = cenario
    with sessoes() as s:
        d = consultas_amazon.detalhe_casamento(s, produto_id, repo_amz.obter_config(s), T0 + timedelta(hours=7))
    assert d.confirmados[0].conferencia is None


def test_tela_do_produto_em_casamentos_mostra_tabela_origem_e_conferido(cliente, cenario, monkeypatch):
    produto_id, _ = cenario
    monkeypatch.setattr("tcg_sniper.db.repositorio.agora_utc", lambda: T0)
    texto = cliente.get(f"/casamentos/produto/{produto_id}").text
    assert "automático pela IA" in texto
    assert 'badge-outline whitespace-nowrap">pela IA<' not in texto  # o selo antigo saiu
    assert "Shazaar" in texto and "Amazon Global" in texto and "melhor" in texto
    assert "conferido no checkout: R$ 285,99 (impostos R$ 48,26)" in texto
    assert "importado (EUA)" in texto and "Prime" in texto


def test_ofertas_mostra_conferido_selos_e_origem(sessoes, cliente, cenario, monkeypatch):
    monkeypatch.setattr("tcg_sniper.db.repositorio.agora_utc", lambda: T0)
    with sessoes() as s:
        [linha] = consultas_amazon.ofertas(s, FiltroOfertas(), repo_amz.obter_config(s))
    assert linha.conferencia.total == Decimal("285.99")
    assert (linha.importada, linha.origem_envio, linha.prime) == (True, "Estados Unidos", True)
    assert linha.origem_casamento is OrigemCasamento.AUTOMATICO_IA
    texto = cliente.get("/ofertas").text
    assert "conferido no checkout: R$ 285,99 (impostos R$ 48,26)" in texto and "automático pela IA" in texto


def test_ofertas_sem_conferencia_diz_nao_conferido(sessoes, cliente):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p2", nome="Caixa Beta")
        criar_preco_liga(s, p, "1000.00", listagem_em=T0)
        a = criar_anuncio(s, "B0BETA0001", produto=p, status=StatusCasamento.CONFIRMADO)
        a.origem_casamento = OrigemCasamento.MANUAL
        o = oferta_lista("700.00", vendedor="Amazon.com.br", seller_id="amazon", envio=Envio.AMAZON, posicao=0)
        repo_amz.gravar_ofertas(s, a.id, T0, [repo_amz.OfertaAvaliada(o, None, True, True)])
        repo_amz.registrar_preco(s, a.id, Decimal("700.00"), OrigemPreco.OFERTAS, None, Envio.AMAZON, T0, SP)
    texto = cliente.get("/ofertas").text
    assert "não conferido" in texto and ">manual<" in texto


def test_pagina_do_produto_mostra_as_ofertas_lidas(cliente, cenario):
    produto_id, _ = cenario
    texto = cliente.get(f"/produto/{produto_id}").text
    assert "Shazaar" in texto and "Amazon Global" in texto and "automático pela IA" in texto
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t7 uv run pytest tests/admin/test_admin_monitor_ofertas.py -q`
Expected: FAIL (`LinhaAnuncio` sem `ofertas`; `detalhe_casamento` sem `agora`).

- [ ] **Step 3: Consultas**

Em `src/tcg_sniper/admin/consultas_amazon.py` (importe `from tcg_sniper.db import repositorio as repo`, `from tcg_sniper.db import repositorio_amazon as repo_amz`, e `ConferenciaCheckout`, `OfertaAmazon`, `OrigemCasamento` de `db.models`):

- `LinhaAnuncio`: depois de `ia`, acrescente

```python
    ofertas: tuple[OfertaAmazon, ...] = ()  # da última leitura do monitor, a mais barata primeiro
    conferencia: ConferenciaCheckout | None = None  # conferência ok válida para a melhor oferta
```

- `_selo_do_vendedor`: o retorno passa a ser `return confiavel, atual.origem in (OrigemPreco.PRODUTO, OrigemPreco.OFERTAS)`.

- Novas funções:

```python
def _conferencia_da_melhor(
    s: Session, anuncio_id: int, ofertas: Sequence[OfertaAmazon], preco: Decimal | None, validade_h: int, agora: datetime
) -> ConferenciaCheckout | None:
    melhor = next((o for o in ofertas if o.melhor), None)
    if melhor is None or preco is None:
        return None
    return repo_amz.conferencia_valida(s, anuncio_id, melhor.vendedor_nome, preco, agora, validade_h)


def _com_ofertas(s: Session, linhas: list[LinhaAnuncio], config: ConfigAmazon, agora: datetime) -> list[LinhaAnuncio]:
    por_anuncio = repo_amz.ofertas_da_ultima_leitura(s, [linha.anuncio.id for linha in linhas])
    resultado = []
    for linha in linhas:
        ofertas = tuple(por_anuncio.get(linha.anuncio.id, ()))
        preco = linha.atual.preco if linha.atual is not None and linha.atual.origem is OrigemPreco.OFERTAS else None
        conferencia = _conferencia_da_melhor(s, linha.anuncio.id, ofertas, preco, config.checkout_validade_h, agora)
        resultado.append(replace(linha, ofertas=ofertas, conferencia=conferencia))
    return resultado
```

(importe `Sequence` de `collections.abc`.)

- `detalhe_casamento(s, produto_id, config, agora=None)`: no início, `agora = agora or repo.agora_utc()`; no `return`, troque `grupos[StatusCasamento.CONFIRMADO]` por `_com_ofertas(s, grupos[StatusCasamento.CONFIRMADO], config, agora)`.

- `amazon_do_produto(s, produto_id, config, agora=None)`: `agora = agora or repo.agora_utc()` e `return _com_ofertas(s, [LinhaAnuncio(...) for ...], config, agora)` (a lista de hoje).

- `LinhaOferta`: depois de `aberta`, acrescente

```python
    origem_casamento: OrigemCasamento | None = None
    conferencia: ConferenciaCheckout | None = None
    importada: bool = False
    origem_envio: str | None = None
    prime: bool = False
```

- Em `ofertas()`, depois dos filtros `desconto_min` e `situacao` e antes do `sort`:

```python
    agora = repo.agora_utc()
    lidas = repo_amz.ofertas_da_ultima_leitura(s, [linha.anuncio.id for linha in linhas])
    completas = []
    for linha in linhas:
        ofertas_lidas = lidas.get(linha.anuncio.id, [])
        melhor = next((o for o in ofertas_lidas if o.melhor), None)
        conferencia = _conferencia_da_melhor(s, linha.anuncio.id, ofertas_lidas, linha.preco, config.checkout_validade_h, agora)
        completas.append(
            replace(
                linha,
                origem_casamento=linha.anuncio.origem_casamento,
                conferencia=conferencia,
                importada=bool(melhor and melhor.importada),
                origem_envio=melhor.origem_envio if melhor else None,
                prime=bool(melhor and melhor.prime),
            )
        )
    linhas = completas
```

- [ ] **Step 4: Templates**

Em `_componentes.html`, acrescente no fim:

```jinja
{% macro selo_origem(origem) -%}
{%- if origem -%}
{%- set rotulos = {"manual": "manual", "sugerido_ia": "sugerido pela IA", "automatico_ia": "automático pela IA"} -%}
{%- set cores = {"manual": "badge-ghost", "sugerido_ia": "badge-info badge-outline", "automatico_ia": "badge-primary badge-outline"} -%}
<span class="badge badge-sm whitespace-nowrap {{ cores[origem.value] }}">{{ rotulos[origem.value] }}</span>
{%- endif -%}
{%- endmacro %}

{% macro preco_conferido(conferencia) -%}
{%- if conferencia -%}
<div class="text-xs text-base-content/70 tabular-nums">conferido no checkout: {{ conferencia.total|brl }}{% if conferencia.impostos is not none %} (impostos {{ conferencia.impostos|brl }}){% endif %}</div>
{%- else -%}
<div class="text-xs text-base-content/60">não conferido</div>
{%- endif -%}
{%- endmacro %}

{% macro selos_oferta(importada, origem_envio, prime) -%}
{%- if importada %}<span class="badge badge-sm badge-warning badge-outline whitespace-nowrap">importado{% if origem_envio %} ({{ {"Estados Unidos": "EUA"}.get(origem_envio, origem_envio) }}){% endif %}</span>{% endif -%}
{%- if prime %} <span class="badge badge-sm badge-info badge-outline whitespace-nowrap">Prime</span>{% endif -%}
{%- endmacro %}

{% macro tabela_ofertas(ofertas) -%}
<div class="overflow-x-auto"><table class="table table-xs">
  <thead><tr><th>Vendedor</th><th class="text-right">Preço</th><th>Envio</th><th>Selos</th><th>Elegível</th></tr></thead>
  <tbody>
  {% for o in ofertas %}
    <tr>
      <td>{{ o.vendedor_nome or "—" }}{% if o.melhor %} {{ selo("ok", "melhor") }}{% endif %}{% if o.condicao != "novo" %} <span class="text-xs text-base-content/60">({{ o.condicao }})</span>{% endif %}</td>
      <td class="text-right tabular-nums whitespace-nowrap">{{ o.preco|brl }}</td>
      <td>{{ {"amazon": "Amazon", "fba": "lojista, enviado pela Amazon", "proprio": "lojista", "desconhecido": "—"}[o.envio.value] }}</td>
      <td>{{ selos_oferta(o.importada, o.origem_envio, o.prime) }}</td>
      <td>{{ "sim" if o.elegivel else "não" }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table></div>
{%- endmacro %}
```

Em `casamentos_produto.html`: no import do topo acrescente `selo_origem, tabela_ofertas, preco_conferido`. Nos confirmados, troque o bloco `{% if l.ia and l.ia.aplicada_em and l.ia.aplicada_em == l.anuncio.revisado_em %}...{% endif %}` por:

```jinja
      <div class="flex flex-wrap items-center gap-2">{{ selo_origem(l.anuncio.origem_casamento) }}{% if l.anuncio.origem_casamento and l.anuncio.origem_casamento.value == "automatico_ia" and l.ia %}<span class="text-xs text-base-content/70 break-words">{{ l.ia.motivo }}</span>{% endif %}</div>
```

e, depois da `div` do preço/vendedor/data dos confirmados:

```jinja
      {% if l.ofertas %}{{ preco_conferido(l.conferencia) }}{{ tabela_ofertas(l.ofertas) }}{% endif %}
```

Nos ignorados, troque o mesmo bloco "pela IA" pela mesma linha de `selo_origem` acima.

Em `produto.html`: no import do topo acrescente `selo_origem, tabela_ofertas, preco_conferido`; na célula do ASIN acrescente `<div>{{ selo_origem(anuncio.origem_casamento) }}</div>` depois da variação; e depois do `</tr>` de cada anúncio:

```jinja
      {% if l.ofertas %}<tr><td colspan="4">{{ preco_conferido(l.conferencia) }}{{ tabela_ofertas(l.ofertas) }}</td></tr>{% endif %}
```

Em `ofertas.html`: no import acrescente `selo_origem, preco_conferido, selos_oferta`; na tabela (desktop), na célula do produto, depois do ASIN: `<div class="flex flex-wrap gap-1">{{ selo_origem(l.origem_casamento) }}{{ selos_oferta(l.importada, l.origem_envio, l.prime) }}</div>`; na célula do preço da Amazon, depois do link: `{{ preco_conferido(l.conferencia) }}`. No cartão (mobile), depois do link do preço: `{{ preco_conferido(l.conferencia) }}`, e na linha de selos acrescente `{{ selo_origem(l.origem_casamento) }}{{ selos_oferta(l.importada, l.origem_envio, l.prime) }}`.

- [ ] **Step 5: CSS e testes**

Run: `uv run python scripts/gerar_css.py && DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t7 uv run pytest -q && uv run ruff check .`
Expected: PASS (inclusive `test_css_em_dia_com_os_templates`). Se um teste antigo de Casamentos procurar o texto "pela IA" dos confirmados, troque a expectativa por "automático pela IA".

- [ ] **Step 6: Commit**

```bash
git add src/tcg_sniper/admin/consultas_amazon.py src/tcg_sniper/admin/templates/_componentes.html src/tcg_sniper/admin/templates/casamentos_produto.html src/tcg_sniper/admin/templates/produto.html src/tcg_sniper/admin/templates/ofertas.html src/tcg_sniper/admin/static/admin.css tests/admin
git commit -m "feat: admin shows the offers of the last monitor read, the checked checkout total and the match origin"
```

---

### Task 8: Admin — Configurações, Serviços, Logs e Dashboard do monitor

**Files:**
- Modify: `src/tcg_sniper/admin/app.py` (Serviços, rotas novas, Logs)
- Modify: `src/tcg_sniper/admin/consultas.py` (históricos do monitor e do checkout)
- Modify: `src/tcg_sniper/admin/consultas_painel.py` (card e avisos da Amazon)
- Modify: `src/tcg_sniper/admin/templates/configuracoes.html`, `servicos.html`, `logs.html`
- Modify: `src/tcg_sniper/admin/static/admin.css` (regenerado)
- Test: `tests/admin/test_admin_monitor_painel.py` (novo); `tests/admin/test_admin_logs.py`, `tests/admin/test_consultas_painel.py` (ajustes)

**Interfaces:**
- Consumes (Task 3): `repositorio_amazon.situacao_monitor`, `SituacaoMonitor`, `registrar_conferencia`, `gravar_ofertas`, `OfertaAvaliada`, `registrar_preco`; `ConfigAmazon.monitor_*`, `checkout_*`; `coletor_amazon.config.aplicar_config`; `models.SituacaoCheckout`, `OfertaAmazon`, `ConferenciaCheckout`; `fakes.oferta_lista`.
- Produces:
  - Rotas `POST /amazon/monitor/ligar`, `/amazon/monitor/desligar`, `/amazon/checkout/ligar`, `/amazon/checkout/desligar`, `/amazon/checkout/retomar` (303 para `/servicos?msg=<chave>`).
  - `consultas.SITUACOES_CHECKOUT`, `consultas.LinhaConferencia(conferencia, asin, produto)`, `consultas.historico_conferencias(s, situacao, pagina, por_pagina=POR_PAGINA_HISTORICO) -> tuple[list[LinhaConferencia], int, int]`, `consultas.LinhaMonitor(lida_em, asin, produto, ofertas, melhor_preco, melhor_vendedor)`, `consultas.historico_monitor(s, pagina, por_pagina=POR_PAGINA_HISTORICO) -> tuple[list[LinhaMonitor], int, int]`.
  - `app.ABAS_LOGS = ("liga", "amazon", "monitor", "checkout", "ia")`; parâmetros `monitor_pagina`, `checkout_situacao`, `checkout_pagina`.
  - `consultas_painel`: o detalhe do card Amazon termina com "· monitor: ... · conferência: ..."; `avisos()` ganha, no fim, sem login (erro), monitor que não cabe no teto (aviso) e monitor atrasado (aviso).

- [ ] **Step 1: Testes (falham)**

Create `tests/admin/test_admin_monitor_painel.py`:

```python
import base64
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto, oferta_lista
from fastapi.testclient import TestClient

from tcg_sniper.admin import consultas
from tcg_sniper.admin import consultas_painel as painel
from tcg_sniper.admin.app import criar_app
from tcg_sniper.coletor_amazon.config import aplicar_config
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import Envio, OrigemPreco, SituacaoCheckout, StatusCasamento

AGORA = datetime(2026, 10, 16, 19, 40, tzinfo=UTC)  # 16:40 em São Paulo
SP = ZoneInfo("America/Sao_Paulo")


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def confirmado(s, asin, lido_em=None):
    produto = criar_produto(s, f"p-{asin}", nome=f"Produto {asin}")
    criar_preco_liga(s, produto, "1000.00", listagem_em=AGORA)
    anuncio = criar_anuncio(s, asin, produto=produto, status=StatusCasamento.CONFIRMADO)
    if lido_em is not None:
        o = oferta_lista("700.00", vendedor="Amazon.com.br", seller_id="amazon", envio=Envio.AMAZON, posicao=0)
        repo_amz.gravar_ofertas(s, anuncio.id, lido_em, [repo_amz.OfertaAvaliada(o, None, True, True)])
        repo_amz.registrar_preco(s, anuncio.id, o.preco, OrigemPreco.OFERTAS, None, Envio.AMAZON, lido_em, SP)
    return anuncio


def avisos_de(s, config, agora=AGORA):
    repo_msg.registrar_ciclo(s, agora)  # notificador vivo: só os avisos do monitor interessam aqui
    resumo = painel.consultas_mensagens.resumo(s, agora)
    return painel.avisos(s, agora, config, painel.saude_servicos(s, agora, config, True, resumo), resumo)


def test_configuracoes_tem_a_secao_monitor_de_preco(cliente):
    texto = cliente.get("/configuracoes").text
    assert "Monitor de preço" in texto
    assert 'name="monitor_intervalo_min" value="15"' in texto and 'name="monitor_janela_inicio" value="08:00"' in texto


@pytest.mark.parametrize(
    ("rota", "campo", "valor", "mensagem"),
    [
        ("/amazon/monitor/desligar", "monitor_ligado", False, "Monitor de preço desligado"),
        ("/amazon/monitor/ligar", "monitor_ligado", True, "Monitor de preço ligado"),
        ("/amazon/checkout/desligar", "checkout_ligado", False, "Conferência de checkout desligada"),
        ("/amazon/checkout/ligar", "checkout_ligado", True, "Conferência de checkout ligada"),
    ],
)
def test_liga_e_desliga_monitor_e_conferencia(cliente, sessoes, rota, campo, valor, mensagem):
    r = cliente.post(rota, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/servicos?msg=")
    with sessoes() as s:
        assert getattr(repo_amz.obter_config(s), campo) is valor
    assert mensagem in cliente.get(r.headers["location"]).text


def test_retomar_conferencia_limpa_o_sem_login(cliente, sessoes):
    with sessoes() as s, s.begin():
        aplicar_config(s, {"checkout_sem_login_em": T0}, T0)
    texto = cliente.get("/servicos").text
    assert "Retomar conferência" in texto and ":6081/vnc.html" in texto
    cliente.post("/amazon/checkout/retomar")
    with sessoes() as s:
        assert repo_amz.obter_config(s).checkout_sem_login_em is None
    assert "Retomar conferência" not in cliente.get("/servicos").text


def test_servicos_mostra_os_dois_interruptores(cliente):
    texto = cliente.get("/servicos").text
    assert 'action="/amazon/monitor/desligar"' in texto and 'action="/amazon/checkout/desligar"' in texto


def test_historico_das_conferencias(s):
    a = confirmado(s, "B0LOG00001")
    repo_amz.registrar_conferencia(
        s, em=T0, anuncio_id=a.id, vendedor_nome="Shazaar", preco_anunciado=Decimal("275.91"), itens=None,
        frete=None, impostos=None, total=None, situacao=SituacaoCheckout.CARRINHO_OCUPADO, motivo="2 item(ns)",
        item_removido=True,
    )
    repo_amz.registrar_conferencia(
        s, em=T0 + timedelta(minutes=5), anuncio_id=a.id, vendedor_nome="Shazaar", preco_anunciado=Decimal("275.91"),
        itens=Decimal("237.73"), frete=Decimal("0.00"), impostos=Decimal("48.26"), total=Decimal("285.99"),
        situacao=SituacaoCheckout.OK, motivo=None, item_removido=True,
    )
    linhas, pagina, paginas = consultas.historico_conferencias(s, "todas", 1)
    assert [l.conferencia.situacao for l in linhas] == [SituacaoCheckout.OK, SituacaoCheckout.CARRINHO_OCUPADO]
    assert (linhas[0].asin, linhas[0].produto, pagina, paginas) == ("B0LOG00001", "Produto B0LOG00001", 1, 1)
    assert len(consultas.historico_conferencias(s, "carrinho_ocupado", 1)[0]) == 1


def test_historico_do_monitor(s):
    a = confirmado(s, "B0LOG00001", lido_em=T0)
    repo_amz.gravar_ofertas(
        s, a.id, T0 + timedelta(minutes=15),
        [repo_amz.OfertaAvaliada(oferta_lista("690.00"), None, True, True), repo_amz.OfertaAvaliada(oferta_lista("720.00", vendedor="Outra"), None, False, False)],
    )
    linhas, _, _ = consultas.historico_monitor(s, 1)
    assert [(l.ofertas, l.melhor_preco, l.melhor_vendedor) for l in linhas] == [
        (2, Decimal("690.00"), "Shazaar"), (1, Decimal("700.00"), "Amazon.com.br"),
    ]


def test_logs_tem_as_abas_monitor_e_checkout(cliente):
    texto = cliente.get("/logs?aba=checkout").text
    assert 'aria-label="Monitor"' in texto and 'aria-label="Checkout"' in texto
    assert "Nenhuma conferência de checkout ainda." in texto
    assert cliente.get("/logs?checkout_situacao=xyz").status_code == 400


def test_card_da_amazon_mostra_monitor_e_conferencia(s, config):
    confirmado(s, "B0LOG00001", lido_em=AGORA - timedelta(minutes=5))
    detalhe = {x.nome: x for x in painel.saude_servicos(s, AGORA, config, True)}["Amazon"].detalhe
    assert detalhe.endswith("monitor: última leitura hoje 16:35 · conferência ligada")
    aplicar_config(s, {"checkout_sem_login_em": AGORA}, AGORA)
    detalhe = {x.nome: x for x in painel.saude_servicos(s, AGORA, config, True)}["Amazon"].detalhe
    assert detalhe.endswith("conferência parada: conta sem login")


def test_dashboard_avisa_conta_sem_login(s, config):
    aplicar_config(s, {"checkout_sem_login_em": AGORA - timedelta(hours=1)}, AGORA)
    [aviso] = avisos_de(s, config)
    assert aviso.tipo == "error" and "sem login" in aviso.texto and "6081" in aviso.texto and aviso.link == "/servicos"


def test_dashboard_avisa_monitor_que_nao_cabe_no_intervalo(s, config):
    for i in range(3):
        confirmado(s, f"B0LOG0000{i}", lido_em=AGORA - timedelta(minutes=1))
    aplicar_config(s, {"monitor_max_paginas_hora": 10}, AGORA)  # 3 anúncios a cada 15 min = 12 páginas/h
    [aviso] = avisos_de(s, config)
    assert aviso.tipo == "warning" and "12 páginas por hora" in aviso.texto and aviso.link == "/configuracoes"


def test_dashboard_avisa_monitor_atrasado_so_dentro_da_janela(s, config):
    confirmado(s, "B0LOG00001", lido_em=AGORA - timedelta(minutes=40))
    [aviso] = avisos_de(s, config)
    assert "atrasado" in aviso.texto and aviso.link == "/logs?aba=monitor"
    noite = datetime(2026, 10, 17, 2, 0, tzinfo=UTC)  # 23:00 em SP, monitor fora do horário
    assert avisos_de(s, config, noite) == []
    manha = datetime(2026, 10, 17, 11, 10, tzinfo=UTC)  # 08:10: a janela abriu há menos de 2 intervalos
    assert avisos_de(s, config, manha) == []
```

Em `tests/admin/test_admin_logs.py`: `ABAS = ("LigaMagic", "Amazon", "Monitor", "Checkout", "IA")` e o nome do teste `test_tres_abas_e_a_liga_abre_por_padrao` vira `test_abas_e_a_liga_abre_por_padrao`.

Em `tests/admin/test_consultas_painel.py`: nos testes `test_amazon` e `test_amazon_conta_precos_lidos_nas_ultimas_24h`, troque as comparações exatas do `detalhe` por `startswith` (o detalhe agora termina com o monitor e a conferência):

```python
    assert amazon.detalhe.startswith("0 preços lidos nas últimas 24 h · ")
```

```python
    assert saude(s, config)["Amazon"].detalhe.startswith("1 preços lidos nas últimas 24 h · ")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t8 uv run pytest tests/admin -q`
Expected: FAIL (rotas e funções novas inexistentes).

- [ ] **Step 3: Consultas dos logs**

Em `src/tcg_sniper/admin/consultas.py` (importe `dataclass`, `datetime`, `Decimal`, `case` de `sqlalchemy`, e `AnuncioAmazon`, `ConferenciaCheckout`, `OfertaAmazon`, `ProdutoLiga`, `SituacaoCheckout` de `db.models`, os que faltarem):

```python
SITUACOES_CHECKOUT = ("todas", *(situacao.value for situacao in SituacaoCheckout))


def _pagina(total: int, pagina: int, por_pagina: int) -> tuple[int, int]:
    paginas = max(1, -(-total // por_pagina))
    return min(max(pagina, 1), paginas), paginas


@dataclass(frozen=True)
class LinhaConferencia:
    conferencia: ConferenciaCheckout
    asin: str
    produto: str | None


def historico_conferencias(
    s: Session, situacao: str, pagina: int, por_pagina: int = POR_PAGINA_HISTORICO
) -> tuple[list[LinhaConferencia], int, int]:
    """Conferências de checkout, das mais recentes, com o filtro de situação da aba Checkout."""
    condicoes = [] if situacao == "todas" else [ConferenciaCheckout.situacao == SituacaoCheckout(situacao)]
    total = s.scalar(select(func.count()).select_from(ConferenciaCheckout).where(*condicoes)) or 0
    pagina, paginas = _pagina(total, pagina, por_pagina)
    consulta = (
        select(ConferenciaCheckout, AnuncioAmazon.asin, ProdutoLiga.nome)
        .join(AnuncioAmazon, AnuncioAmazon.id == ConferenciaCheckout.anuncio_id)
        .outerjoin(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .where(*condicoes)
        .order_by(ConferenciaCheckout.em.desc(), ConferenciaCheckout.id.desc())
        .offset((pagina - 1) * por_pagina)
        .limit(por_pagina)
    )
    return [LinhaConferencia(c, asin, nome) for c, asin, nome in s.execute(consulta)], pagina, paginas


@dataclass(frozen=True)
class LinhaMonitor:
    lida_em: datetime
    asin: str
    produto: str | None
    ofertas: int
    melhor_preco: Decimal | None
    melhor_vendedor: str | None


def historico_monitor(
    s: Session, pagina: int, por_pagina: int = POR_PAGINA_HISTORICO
) -> tuple[list[LinhaMonitor], int, int]:
    """Leituras do monitor (uma por anúncio e instante), das mais recentes, com nº de ofertas e a melhor.
    Leituras sem nenhuma oferta (anúncio indisponível) não aparecem."""
    leituras = (
        select(
            OfertaAmazon.anuncio_id,
            OfertaAmazon.lida_em,
            func.count().label("ofertas"),
            func.max(case((OfertaAmazon.melhor, OfertaAmazon.preco))).label("melhor_preco"),
            func.max(case((OfertaAmazon.melhor, OfertaAmazon.vendedor_nome))).label("melhor_vendedor"),
        )
        .group_by(OfertaAmazon.anuncio_id, OfertaAmazon.lida_em)
        .subquery()
    )
    total = s.scalar(select(func.count()).select_from(leituras)) or 0
    pagina, paginas = _pagina(total, pagina, por_pagina)
    consulta = (
        select(
            leituras.c.lida_em, AnuncioAmazon.asin, ProdutoLiga.nome, leituras.c.ofertas,
            leituras.c.melhor_preco, leituras.c.melhor_vendedor,
        )
        .join(AnuncioAmazon, AnuncioAmazon.id == leituras.c.anuncio_id)
        .outerjoin(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .order_by(leituras.c.lida_em.desc(), AnuncioAmazon.id)
        .offset((pagina - 1) * por_pagina)
        .limit(por_pagina)
    )
    return [LinhaMonitor(*linha) for linha in s.execute(consulta)], pagina, paginas
```

- [ ] **Step 4: Dashboard**

Em `src/tcg_sniper/admin/consultas_painel.py` (importe `import math`):

```python
def _resumo_monitor(s: Session, agora: datetime, cfg: Config) -> str:
    cfg_amazon = repo_amz.obter_config(s)
    if not cfg_amazon.monitor_ligado:
        monitor = "monitor desligado"
    else:
        situacao = repo_amz.situacao_monitor(s, agora, cfg_amazon.monitor_intervalo_min)
        if situacao.ultima is None:
            monitor = "monitor: nenhuma leitura ainda"
        else:
            monitor = f"monitor: última leitura {_quando(situacao.ultima, agora, cfg.zona)}"
            if situacao.vencidos:
                monitor += f", {situacao.vencidos} na fila"
    if not cfg_amazon.checkout_ligado:
        conferencia = "conferência desligada"
    elif cfg_amazon.checkout_sem_login_em is not None:
        conferencia = "conferência parada: conta sem login"
    else:
        conferencia = "conferência ligada"
    return f"{monitor} · {conferencia}"
```

Em `_saude_amazon`, troque a linha do `detalhe` por:

```python
    detalhe = f"{lidos} preços lidos nas últimas 24 h · {_resumo_monitor(s, agora, cfg)}"
```

Nova função e chamada no fim de `avisos()` (antes do `return lista`: `lista += _avisos_monitor(s, agora, config_efetiva)`):

```python
def _avisos_monitor(s: Session, agora: datetime, cfg: Config) -> list[Aviso]:
    """Conta Amazon sem login (a conferência parou), monitor que não cabe no teto por hora e monitor
    atrasado (leitura mais velha que dois intervalos, com a janela aberta há pelo menos dois intervalos)."""
    cfg_amazon = repo_amz.obter_config(s)
    lista = []
    if cfg_amazon.checkout_ligado and cfg_amazon.checkout_sem_login_em is not None:
        desde = _quando(cfg_amazon.checkout_sem_login_em, agora, cfg.zona)
        lista.append(
            Aviso(
                "error",
                f"A conta Amazon está sem login desde {desde}: a conferência de checkout parou (o monitor continua). "
                "Logue a conta no noVNC (porta 6081) e clique em Retomar conferência.",
                "/servicos",
                "Ir para Serviços",
            )
        )
    if not cfg_amazon.monitor_ligado:
        return lista
    intervalo = cfg_amazon.monitor_intervalo_min
    situacao = repo_amz.situacao_monitor(s, agora, intervalo)
    exigido = math.ceil(situacao.confirmados * 60 / intervalo)
    if exigido > cfg_amazon.monitor_max_paginas_hora:
        lista.append(
            Aviso(
                "warning",
                f"O monitor precisa de {exigido} páginas por hora para ler os {situacao.confirmados} anúncios "
                f"confirmados a cada {intervalo} min, acima do teto de {cfg_amazon.monitor_max_paginas_hora}: "
                "as leituras vão atrasar.",
                "/configuracoes",
                "Ajustar em Configurações",
            )
        )
    local = agora.astimezone(cfg.zona)
    abertura = local.replace(
        hour=cfg_amazon.monitor_janela_inicio.hour, minute=cfg_amazon.monitor_janela_inicio.minute, second=0, microsecond=0
    )
    dois_intervalos = timedelta(minutes=2 * intervalo)
    aberta_ha_tempo = (
        cfg_amazon.monitor_janela_inicio <= local.time() < cfg_amazon.monitor_janela_fim and local - abertura >= dois_intervalos
    )
    ativo = repo.obter_estado(s, agora, COLETOR_AMAZON).estado is EstadoColetorTipo.ATIVO
    if ativo and aberta_ha_tempo and situacao.mais_antiga is not None and agora - situacao.mais_antiga >= dois_intervalos:
        minutos = int((agora - situacao.mais_antiga).total_seconds() // 60)
        lista.append(
            Aviso(
                "warning",
                f"O monitor está atrasado: {situacao.vencidos} anúncio(s) com leitura vencida, o mais antigo lido há {minutos} min.",
                "/logs?aba=monitor",
                "Ver nos logs",
            )
        )
    return lista
```

- [ ] **Step 5: Rotas, Serviços e Logs (`app.py`)**

Em `MENSAGENS_SERVICOS` acrescente:

```python
    "monitor_ligar": "Monitor de preço ligado.",
    "monitor_desligar": "Monitor de preço desligado. A busca de anúncios novos continua.",
    "checkout_ligar": "Conferência de checkout ligada.",
    "checkout_desligar": "Conferência de checkout desligada. Os alertas usam o preço anunciado.",
    "checkout_retomar": "Conferência de checkout retomada.",
```

`ABAS_LOGS = ("liga", "amazon", "monitor", "checkout", "ia")`.

Depois de `retomar_amazon`:

```python
    def _ajustar_amazon(valores: dict[str, object], msg: str) -> RedirectResponse:
        with sessoes() as s, s.begin():
            aplicar_config(s, valores, repo.agora_utc())
        return RedirectResponse(f"/servicos?msg={msg}", status_code=status.HTTP_303_SEE_OTHER)

    @app.post("/amazon/monitor/ligar")
    def ligar_monitor():
        return _ajustar_amazon({"monitor_ligado": True}, "monitor_ligar")

    @app.post("/amazon/monitor/desligar")
    def desligar_monitor():
        return _ajustar_amazon({"monitor_ligado": False}, "monitor_desligar")

    @app.post("/amazon/checkout/ligar")
    def ligar_checkout():
        return _ajustar_amazon({"checkout_ligado": True}, "checkout_ligar")

    @app.post("/amazon/checkout/desligar")
    def desligar_checkout():
        return _ajustar_amazon({"checkout_ligado": False}, "checkout_desligar")

    @app.post("/amazon/checkout/retomar")
    def retomar_checkout():
        return _ajustar_amazon({"checkout_sem_login_em": None}, "checkout_retomar")
```

Em `servicos`, acrescente ao contexto:

```python
                    "cfg_amazon": cfg_amazon,
                    "janela_monitor": (f"{cfg_amazon.monitor_janela_inicio:%H:%M}", f"{cfg_amazon.monitor_janela_fim:%H:%M}"),
                    "monitor": repo_amz.situacao_monitor(s, repo.agora_utc(), cfg_amazon.monitor_intervalo_min),
```

Em `logs`: novos parâmetros `monitor_pagina: str = "1"`, `checkout_situacao: str = "todas"`, `checkout_pagina: str = "1"`; validação `if checkout_situacao not in consultas.SITUACOES_CHECKOUT: raise HTTPException(status.HTTP_400_BAD_REQUEST, f"situação inválida: {checkout_situacao}")`; dentro da sessão:

```python
            leituras, pagina_monitor, paginas_monitor = consultas.historico_monitor(s, numero_pagina(monitor_pagina))
            conferencias, pagina_checkout, paginas_checkout = consultas.historico_conferencias(
                s, checkout_situacao, numero_pagina(checkout_pagina)
            )
```

`parametros` ganha `"monitor_pagina": pagina_monitor, "checkout_situacao": checkout_situacao, "checkout_pagina": pagina_checkout`, e o contexto do template ganha `"leituras"`, `"pagina_monitor"`, `"paginas_monitor"`, `"conferencias"`, `"pagina_checkout"`, `"paginas_checkout"`, `"checkout_situacao"`, `"situacoes_checkout": consultas.SITUACOES_CHECKOUT`.

- [ ] **Step 6: Templates**

`configuracoes.html`: dentro do `{% for campo in secao.campos %}`, antes do `<fieldset ...>`:

```jinja
        {% if secao.id == "amazon" and campo == "monitor_intervalo_min" %}
        <div class="md:col-span-2 pt-2">
          <h3 class="text-base font-semibold">Monitor de preço</h3>
          <p class="text-sm text-base-content/70">Lê a lista de ofertas dos anúncios confirmados e confere o checkout das candidatas. Ligar e desligar fica em Serviços.</p>
        </div>
        {% endif %}
```

`servicos.html`, no card da Amazon (ramo sem desafio), antes do `<div class="card-actions">`:

```jinja
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
    {% if cfg_amazon.checkout_sem_login_em %}
    <div role="alert" class="alert alert-error alert-soft text-sm">
      <span>Conta Amazon sem login desde {{ cfg_amazon.checkout_sem_login_em|data }}. Logue em <a class="link" href="http://{{ host }}:6081/vnc.html">http://{{ host }}:6081/vnc.html</a> e retome.</span>
      <form method="post" action="/amazon/checkout/retomar"><button class="btn btn-sm btn-primary">Retomar conferência</button></form>
    </div>
    {% endif %}
```

`logs.html`: acrescente as macros `{% macro url_monitor(n) %}{{ link(aba="monitor", monitor_pagina=n) }}{% endmacro %}` e `{% macro url_checkout(n) %}{{ link(aba="checkout", checkout_pagina=n) }}{% endmacro %}`; e, entre a aba Amazon e a aba IA:

```jinja
  <input type="radio" name="logs" class="tab" aria-label="Monitor"{% if aba == "monitor" %} checked{% endif %}>
  <div class="tab-content space-y-3 pt-4">
    <div class="card bg-base-100 shadow-sm"><div class="card-body overflow-x-auto p-4">
      <table class="table table-zebra">
        <thead><tr><th>Quando</th><th>Anúncio</th><th class="text-right">Ofertas</th><th class="text-right">Melhor preço</th><th>Melhor vendedor</th></tr></thead>
        <tbody>
        {% for l in leituras %}
          <tr>
            <td class="whitespace-nowrap tabular-nums">{{ l.lida_em|data }}</td>
            <td><span class="font-mono text-xs">{{ l.asin }}</span>{% if l.produto %}<div class="text-sm">{{ l.produto }}</div>{% endif %}</td>
            <td class="text-right tabular-nums">{{ l.ofertas }}</td>
            <td class="text-right tabular-nums whitespace-nowrap">{{ l.melhor_preco|brl }}</td>
            <td>{{ l.melhor_vendedor or "—" }}</td>
          </tr>
        {% else %}
          <tr><td colspan="5">Nenhuma leitura do monitor ainda.</td></tr>
        {% endfor %}
        </tbody>
      </table>
    </div></div>
    {{ paginacao(pagina_monitor, paginas_monitor, url_monitor) }}
  </div>

  <input type="radio" name="logs" class="tab" aria-label="Checkout"{% if aba == "checkout" %} checked{% endif %}>
  <div class="tab-content space-y-3 pt-4">
    <form method="get" action="/logs" class="flex flex-wrap items-end gap-3">
      {{ ocultos("checkout", ("checkout_situacao", "checkout_pagina")) }}
      <fieldset class="fieldset"><legend class="fieldset-legend">Situação</legend>
        <select name="checkout_situacao" class="select select-sm w-auto" aria-label="Situação da conferência">
          {% for v in situacoes_checkout %}<option value="{{ v }}" {% if v == checkout_situacao %}selected{% endif %}>{{ v|replace("_", " ") }}</option>{% endfor %}
        </select>
      </fieldset>
      <button type="submit" class="btn btn-sm btn-primary mb-1">Filtrar</button>
    </form>
    <div class="card bg-base-100 shadow-sm"><div class="card-body overflow-x-auto p-4">
      <table class="table table-zebra">
        <thead><tr><th>Quando</th><th>Anúncio</th><th>Vendedor</th><th class="text-right">Anunciado</th><th class="text-right">Itens</th><th class="text-right">Frete</th><th class="text-right">Impostos</th><th class="text-right">Total</th><th>Situação</th><th>Motivo</th></tr></thead>
        <tbody>
        {% for l in conferencias %}{% set c = l.conferencia %}
          <tr>
            <td class="whitespace-nowrap tabular-nums">{{ c.em|data }}</td>
            <td><span class="font-mono text-xs">{{ l.asin }}</span>{% if l.produto %}<div class="text-sm">{{ l.produto }}</div>{% endif %}</td>
            <td>{{ c.vendedor_nome or "—" }}</td>
            <td class="text-right tabular-nums whitespace-nowrap">{{ c.preco_anunciado|brl }}</td>
            <td class="text-right tabular-nums whitespace-nowrap">{{ c.itens|brl }}</td>
            <td class="text-right tabular-nums whitespace-nowrap">{{ c.frete|brl }}</td>
            <td class="text-right tabular-nums whitespace-nowrap">{{ c.impostos|brl }}</td>
            <td class="text-right tabular-nums whitespace-nowrap">{{ c.total|brl }}</td>
            <td>{{ selo({"ok": "ok", "falha": "falha", "carrinho_ocupado": "parcial", "sem_login": "pausado"}[c.situacao.value], c.situacao.value|replace("_", " ")) }}{% if not c.item_removido %} {{ selo("pausado", "item no carrinho") }}{% endif %}</td>
            <td class="text-sm">{{ c.motivo or "" }}</td>
          </tr>
        {% else %}
          <tr><td colspan="10">Nenhuma conferência de checkout ainda.</td></tr>
        {% endfor %}
        </tbody>
      </table>
    </div></div>
    {{ paginacao(pagina_checkout, paginas_checkout, url_checkout) }}
  </div>
```

Atualize o subtítulo do cabeçalho de Logs para "Histórico das coletas, dos ciclos, do monitor, das conferências de checkout e das chamadas da IA."

- [ ] **Step 7: CSS e testes**

Run: `uv run python scripts/gerar_css.py && DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t8 uv run pytest -q && uv run ruff check .`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/tcg_sniper/admin/app.py src/tcg_sniper/admin/consultas.py src/tcg_sniper/admin/consultas_painel.py src/tcg_sniper/admin/templates/configuracoes.html src/tcg_sniper/admin/templates/servicos.html src/tcg_sniper/admin/templates/logs.html src/tcg_sniper/admin/static/admin.css tests/admin
git commit -m "feat: admin settings, on/off switches, logs and dashboard warnings for the price monitor and checkout checks"
```

---

### Task 9: Captura real em produção e fixtures (o controlador executa, não um subagente)

Esta tarefa roda no servidor de produção, com a conta Amazon do grupo. Quem executa é o controlador da sessão, que conversa com o usuário; nenhum subagente faz cliques no site real.

**Files:**
- Create: `tests/fixtures/amazon/ofertas_importada.html`, `ofertas_amazon.html`, `ofertas_fba.html`, `painel_importada.html`, `carrinho_inicial.html`, `carrinho_um_item.html`, `carrinho_vazio.html`, `checkout_endereco.html` (se o passo do endereço apareceu), `checkout_resumo.html`, `login.html`
- Create: `tests/fixtures/amazon/esperado.json`
- Modify (só se a captura mostrar seletor diferente): `src/tcg_sniper/coletor_amazon/cliques.py` (primeiro seletor de cada lista), `tests/coletor_amazon/test_cliques.py`, `src/tcg_sniper/coletor_amazon/parsers.py` (`url_ofertas`)
- Fora do git: `.fixtures-brutas/amazon/<data>/` (páginas inteiras) e `.fixtures-brutas/proibidos.txt`

**Interfaces:**
- Consumes: Task 2 (`scripts/anonimizar_fixture.py`, `tests/test_fixtures_privacidade.py`), Task 5 (`tcg-sniper amazon capturar`), Tasks 1–8 já no branch e com a imagem construída.
- Produces: as fixtures acima e `esperado.json`, no formato exato abaixo (as Tasks 10, 11 e 13 leem):

```json
{
  "ofertas_importada": {
    "asin": "B0DNV55QBS",
    "num_ofertas": 7,
    "destaque": {"vendedor": "Amazon Global", "preco": "314.11"},
    "ofertas": [
      {"vendedor": "Shazaar", "preco": "275.91", "condicao": "novo", "envio": "fba",
       "origem_envio": "Estados Unidos", "importada": true, "pct_positivas": "100", "num_avaliacoes": 66}
    ]
  },
  "painel_importada": {"asin": "B0DNV55QBS", "num_ofertas": 7, "destaque": {"vendedor": "Amazon Global", "preco": "314.11"}, "ofertas": []},
  "ofertas_amazon": {"asin": "<ASIN>", "num_ofertas": 1, "destaque": {"vendedor": "Amazon.com.br", "preco": "<preço>"}, "ofertas": []},
  "ofertas_fba": {"asin": "<ASIN>", "num_ofertas": 1, "destaque": {"vendedor": "<loja>", "preco": "<preço>"}, "ofertas": []},
  "carrinho_inicial": {"contador": 0, "asins_ativos": []},
  "carrinho_um_item": {"contador": 1, "asins_ativos": ["B0DNV55QBS"], "subtotal": "314.11"},
  "carrinho_vazio": {"contador": 0, "asins_ativos": []},
  "checkout_endereco": {"etapa": "endereco"},
  "checkout_resumo": {"etapa": "resumo", "itens": "237.73", "frete": "0.00", "impostos": "48.26", "total": "285.99"},
  "login": {"etapa": "login"}
}
```

Os números acima são os da investigação de 2026-10-17 e servem só de exemplo do formato: **os valores gravados são os lidos nas páginas capturadas** (Step 7). Campos de cada oferta em `ofertas` (todos opcionais além de `vendedor` e `preco`): `condicao`, `envio` (`amazon`/`fba`/`proprio`/`desconhecido`), `origem_envio`, `importada`, `prime`, `preco_de`, `pct_positivas`, `num_avaliacoes`. `carrinho_*` pode ter `subtotal` (string) ou não. `checkout_endereco` some do arquivo se o checkout foi direto ao resumo; nesse caso o resumo é o `checkout_1`.

- [ ] **Step 1: Escolher os anúncios**

No servidor:

```bash
docker compose exec -T postgres psql -U tcg tcg -c "select a.asin, p.envio, p.preco, v.nome from anuncio_amazon a join preco_atual_amazon p on p.anuncio_id = a.id left join vendedor_amazon v on v.id = p.vendedor_id where a.status_casamento = 'confirmado' and p.envio in ('amazon', 'fba') and p.preco is not null order by p.envio, p.coletado_em desc limit 20;"
```

Escolha um ASIN vendido pela Amazon Brasil (envio `amazon`, vendedor "Amazon.com.br") e um FBA nacional (envio `fba`). O importado é `B0DNV55QBS`.

- [ ] **Step 2: Login e carrinho vazio**

Peça ao usuário: entrar em `http://<host>:6081/vnc.html`, logar a conta Amazon do grupo no Chromium do coletor e conferir que o **carrinho ativo está vazio** (itens em "Salvo para depois" podem ficar). Espere a confirmação dele antes de seguir.

- [ ] **Step 3: Capturar**

```bash
docker compose stop coletor-amazon
docker compose run --rm --service-ports coletor-amazon tcg-sniper amazon capturar --asin B0DNV55QBS --asin <ASIN_AMAZON> --asin <ASIN_FBA> --checkout --login
docker compose start coletor-amazon
```

O comando imprime os arquivos salvos e os avisos. Com `--service-ports` o noVNC (6081) mostra a captura ao vivo. Se aparecer "AVISO: o item ... pode ter ficado no carrinho", peça ao usuário para excluir o item pelo noVNC antes de seguir.

- [ ] **Step 4: Trazer as páginas brutas**

```bash
mkdir -p .fixtures-brutas/amazon
docker compose cp coletor-amazon:/data/capturas .fixtures-brutas/amazon/
ls .fixtures-brutas/amazon/capturas/
```

(Se o trabalho de implementação estiver noutra máquina, copie `.fixtures-brutas/amazon/capturas/<data>/` para lá por scp; nunca pelo git.)

- [ ] **Step 5: Conferir os seletores na página real**

Com as páginas brutas, confira cada lista de seletores de `cliques.py` e o endpoint de ofertas:

```bash
D=.fixtures-brutas/amazon/capturas/<data>
uv run python -c "
from pathlib import Path
from tcg_sniper.coletor_amazon.cliques import ADICIONAR, ENTREGAR, EXCLUIR, FECHAR_PEDIDO, ESCOPO_OFERTA_DESTAQUE, localizar
from tcg_sniper.navegador.modelos import Pagina
def p(nome): return Pagina(url='x', status=200, html=Path('$D', nome + '.html').read_text(encoding='utf-8'), titulo='')
print('adicionar', localizar(ADICIONAR, p('painel_B0DNV55QBS'), ESCOPO_OFERTA_DESTAQUE))
print('fechar', localizar(FECHAR_PEDIDO, p('carrinho_um_item')))
print('entregar', localizar(ENTREGAR, p('checkout_1')))
print('excluir', localizar(EXCLUIR, p('carrinho_um_item'), '[data-name=\"Active Items\"] [data-asin=\"B0DNV55QBS\"]'))
"
grep -c 'id="aod-offer"\|id="aod-pinned-offer"' $D/ofertas_B0DNV55QBS.html
```

Para cada ação que imprimir `None` (ou se a captura parou com "botão não encontrado"), abra a página bruta, ache o botão e ponha o seletor certo **no início** da lista daquela ação em `cliques.py`; acrescente em `tests/coletor_amazon/test_cliques.py` um caso com o HTML do botão real (recortado, sem dado pessoal) e rode `uv run pytest tests/coletor_amazon/test_cliques.py -q`. Se o escopo do carrinho ativo não for `[data-name="Active Items"]`, ponha o escopo real no início de `ESCOPOS_CARRINHO_ATIVO`. Depois de qualquer mudança em `cliques.py`, refaça os Steps 3–5.

Se o `grep` contar 0 (o fragmento `aodAjaxMain` aberto direto não traz as ofertas), troque o corpo de `url_ofertas` em `parsers.py` por `return url_painel_ofertas(asin)` e registre no docstring: "o fragmento aberto direto vem vazio; o monitor lê a página do produto com o painel aberto". O monitor (Task 12) já abre `url_ofertas` esperando os blocos do painel (`abrir_e_esperar`), então só a URL muda.

- [ ] **Step 6: Lista de textos proibidos**

Crie `.fixtures-brutas/proibidos.txt` (fora do git) com um texto real por linha, lendo `carrinho_*`, `checkout_1`/`checkout_resumo` brutos: nome completo e nome + sobrenome do titular, rua com número, complemento, bairro, cidade-bairro se aparecer junto do endereço, telefone (como aparece), e-mail, CPF (como aparece, inclusive mascarado), final do cartão (ex.: `1234`) e CEP. Use textos de 4 caracteres ou mais (o primeiro nome curto vai junto do sobrenome).

- [ ] **Step 7: Anonimizar, gravar as fixtures e anotar os valores**

```bash
D=.fixtures-brutas/amazon/capturas/<data>
F=tests/fixtures/amazon
uv run python scripts/anonimizar_fixture.py ofertas  $D/ofertas_B0DNV55QBS.html   $F/ofertas_importada.html
uv run python scripts/anonimizar_fixture.py ofertas  $D/ofertas_<ASIN_AMAZON>.html $F/ofertas_amazon.html
uv run python scripts/anonimizar_fixture.py ofertas  $D/ofertas_<ASIN_FBA>.html    $F/ofertas_fba.html
uv run python scripts/anonimizar_fixture.py painel   $D/painel_B0DNV55QBS.html     $F/painel_importada.html
uv run python scripts/anonimizar_fixture.py carrinho $D/carrinho_inicial.html      $F/carrinho_inicial.html
uv run python scripts/anonimizar_fixture.py carrinho $D/carrinho_um_item.html      $F/carrinho_um_item.html
uv run python scripts/anonimizar_fixture.py carrinho $D/carrinho_vazio.html        $F/carrinho_vazio.html
uv run python scripts/anonimizar_fixture.py checkout $D/checkout_1.html            $F/checkout_endereco.html
uv run python scripts/anonimizar_fixture.py checkout $D/checkout_resumo.html       $F/checkout_resumo.html
uv run python scripts/anonimizar_fixture.py login    $D/login.html                 $F/login.html
```

(Se não houve passo de endereço, não há `checkout_resumo` bruto: anonimize `checkout_1.html` como `$F/checkout_resumo.html` e não crie `checkout_endereco.html`.) Se o script recusar gravar ("ainda há dado pessoal"), acrescente o texto que faltou em `proibidos.txt` e rode de novo.

Abra cada fixture gravada e leia de ponta a ponta: só pode haver títulos de produto, preços, nomes de lojas e botões. Escreva `tests/fixtures/amazon/esperado.json` no formato da seção **Interfaces**, com os valores lidos **nas páginas** (na fixture, com os olhos — não com o parser que ainda vai ser escrito): `num_ofertas` = ofertas distintas com preço (vendedor + preço + condição; a destacada conta uma vez, mesmo se também aparecer na lista), vendedor e preço da destacada, e pelo menos duas ofertas da lista do importado (a mais barata e uma vendida pela Amazon, se houver) com os campos que a página mostra; contador e ASINs do carrinho; itens, frete, impostos e total do resumo.

- [ ] **Step 8: Rodar**

Run: `uv run pytest tests/test_fixtures_privacidade.py tests/coletor_amazon/test_cliques.py -v && uv run ruff check .`
Expected: PASS em todas as fixtures (com `proibidos.txt` presente).

- [ ] **Step 9: Commit**

```bash
git add tests/fixtures/amazon/ofertas_importada.html tests/fixtures/amazon/ofertas_amazon.html tests/fixtures/amazon/ofertas_fba.html tests/fixtures/amazon/painel_importada.html tests/fixtures/amazon/carrinho_inicial.html tests/fixtures/amazon/carrinho_um_item.html tests/fixtures/amazon/carrinho_vazio.html tests/fixtures/amazon/checkout_resumo.html tests/fixtures/amazon/login.html tests/fixtures/amazon/esperado.json
git add tests/fixtures/amazon/checkout_endereco.html src/tcg_sniper/coletor_amazon/cliques.py src/tcg_sniper/coletor_amazon/parsers.py tests/coletor_amazon/test_cliques.py  # só os que existem/mudaram
git commit -m "test: anonymized real Amazon offer, cart, checkout and login fixtures with hand-read expected values"
```

---

### Task 10: Parser da lista de ofertas

**Files:**
- Modify: `src/tcg_sniper/coletor_amazon/parsers.py`
- Create: `tests/fakes_ofertas.py`
- Test: `tests/coletor_amazon/test_parsers_ofertas.py` (novo)

**Interfaces:**
- Consumes: `coletor_amazon.modelos.OfertaLista` (Task 3); `parsers.classificar_envio`, `_RE_PCT_POSITIVAS`, `_RE_NUM_AVALIACOES`, `_texto`, `SELLER_AMAZON`; fixtures e `esperado.json` (Task 9); `fakes.DIR_FIXTURES_AMAZON`, `fakes.fixture_amazon`.
- Produces:
  - `parsers.parse_ofertas(html: str) -> list[OfertaLista]`: a destacada primeiro (posição 0), depois as da lista na ordem (posição = índice do bloco `#aod-offer`, contando 1, mesmo que um bloco seja descartado); repetidas (vendedor + preço + condição) contam uma vez; sem preço legível, a oferta é descartada; painel aberto sem oferta → `[]`; página sem nenhum bloco do painel → `ErroParser`.
  - `parsers.BLOCOS_OFERTAS` (seletores lidos, para documentação e recortes futuros).
  - `tests/fakes_ofertas.py`: `bloco_oferta(preco="R$ 275,91", vendedor="Shazaar", seller_id="A2SHZ", envia="Amazon", origem=None, condicao="Novo", destaque=False, avaliacao=None, de=None, prime=False, internacional=False, cupom=None, botao=True) -> str` e `html_ofertas(*blocos, comprar_agora=False) -> str`.

- [ ] **Step 1: Confirmar os seletores na fixture**

Abra `tests/fixtures/amazon/ofertas_importada.html` e `painel_importada.html` e confira, bloco a bloco, os seletores abaixo (são os vistos na investigação de 2026-10-17). Onde a fixture mostrar outro, ponha o da fixture **no início** da tupla correspondente no Step 4 e ajuste `bloco_oferta` (Step 2) para o mesmo formato:
- blocos: `#aod-pinned-offer` (destacada) e `#aod-offer` repetido (lista); estrutura do painel: `#aod-container`, `#all-offers-display`, `#aod-offer-list`;
- preço: `.apex-pricetopay-accessibility-label`, depois `.aok-offscreen` (ignorando o texto "De: ..."), depois `.a-price .a-offscreen` (vazio na investigação);
- condição: `#aod-offer-heading`;
- vendedor: `#aod-offer-soldBy .a-col-right` (link com `seller=<ID>`, ou `span` para a Amazon), com o texto da avaliação ("... (66 avaliações) 100% positivas ...") no mesmo bloco;
- quem envia e origem: `#aod-offer-shipsFrom .a-col-right` ("Amazon Origem do envio Estados Unidos.");
- importada: texto "Compra Internacional" ou "tributos de importação" no bloco, ou origem diferente de Brasil;
- Prime: `i.a-icon-prime`, `.a-icon-prime`, `[aria-label*="Prime"]`;
- cupom: texto "NN% off ..." ou "cupom de desconto XXXX" no bloco.

- [ ] **Step 2: Blocos falsos e testes (falham)**

Create `tests/fakes_ofertas.py`:

```python
"""Painel "Outras opções de compra" da Amazon no formato visto nas fixtures reais (tests/fixtures/amazon)."""


def bloco_oferta(
    preco="R$ 275,91",
    vendedor="Shazaar",
    seller_id="A2SHZ",
    envia="Amazon",
    origem=None,
    condicao="Novo",
    destaque=False,
    avaliacao=None,
    de=None,
    prime=False,
    internacional=False,
    cupom=None,
    botao=True,
) -> str:
    """Um bloco de oferta. `seller_id=None` mostra o vendedor sem link (como a Amazon); `envia=None` omite
    o bloco "Enviado por" (como nas ofertas vendidas e enviadas pela Amazon)."""
    id_bloco = "aod-pinned-offer" if destaque else "aod-offer"
    if seller_id:
        nome = (
            f'<a class="a-size-small a-link-normal" href="/gp/aag/main?ie=UTF8&amp;seller={seller_id}'
            f'&amp;isAmazonFulfilled=1">{vendedor}</a>'
        )
    else:
        nome = f'<span class="a-size-small a-color-base">{vendedor}</span>'
    nota = f'<span class="a-size-small">{avaliacao}</span>' if avaliacao else ""
    preco_de = f'<span class="aok-offscreen">De: {de}</span>' if de else ""
    enviado = ""
    if envia:
        origem_html = f' <span class="a-size-small a-color-secondary">Origem do envio {origem}.</span>' if origem else ""
        enviado = (
            '<div id="aod-offer-shipsFrom"><div class="a-col-left"><span>Enviado por</span></div>'
            f'<div class="a-col-right"><span class="a-size-small a-color-base">{envia}</span>{origem_html}</div></div>'
        )
    extras = []
    if internacional:
        extras.append('<span class="a-color-secondary">Compra Internacional</span><span>Os tributos de importação estão incluídos</span>')
    if prime:
        extras.append('<i class="a-icon a-icon-prime" aria-label="Amazon Prime"></i>')
    if cupom:
        extras.append(f'<span class="a-color-success">{cupom}</span>')
    adicionar = (
        '<span data-action="aod-atc-action"><input name="submit.addToCart" value="Adicionar ao carrinho" '
        'type="submit" class="a-button-input"></span>'
        if botao
        else ""
    )
    return (
        f'<div id="{id_bloco}"><div id="aod-offer-price"><span class="a-price"><span class="a-offscreen"></span></span>'
        f'<span class="aok-offscreen apex-pricetopay-accessibility-label">{preco}</span>{preco_de}</div>'
        f'<div id="aod-offer-heading"><h5>{condicao}</h5></div>{"".join(extras)}'
        '<div id="aod-offer-soldBy"><div class="a-col-left"><span>Vendido por</span></div>'
        f'<div class="a-col-right">{nome}{nota}</div></div>{enviado}{adicionar}</div>'
    )


def html_ofertas(*blocos: str, comprar_agora: bool = False) -> str:
    """Painel com a oferta destacada e a lista; `comprar_agora` põe o botão "Comprar agora" da página do produto."""
    destaque = "".join(b for b in blocos if b.startswith('<div id="aod-pinned-offer"'))
    lista = "".join(b for b in blocos if b.startswith('<div id="aod-offer"'))
    comprar = '<input id="buy-now-button" name="submit.buy-now" value="Comprar agora" type="submit">' if comprar_agora else ""
    return f'<html><body>{comprar}<div id="aod-container">{destaque}<div id="aod-offer-list">{lista}</div></div></body></html>'
```

Create `tests/coletor_amazon/test_parsers_ofertas.py`:

```python
import json
from decimal import Decimal

import pytest
from fakes import DIR_FIXTURES_AMAZON, fixture_amazon
from fakes_ofertas import bloco_oferta, html_ofertas

from tcg_sniper.coletor_amazon.parsers import parse_ofertas
from tcg_sniper.db.models import Envio
from tcg_sniper.parsing import ErroParser

ESPERADO = json.loads((DIR_FIXTURES_AMAZON / "esperado.json").read_text(encoding="utf-8"))
NOMES_DOS_CAMPOS = {"vendedor": "vendedor_nome"}
AVALIACAO = "A classificação do vendedor é 5 de 5 estrelas (66 avaliações) 100% positivas nos últimos 12 meses"


def _convertido(campo, valor):
    if campo in ("preco", "preco_de", "pct_positivas"):
        return Decimal(valor)
    if campo == "envio":
        return Envio(valor)
    return valor


@pytest.mark.parametrize("nome", ["ofertas_importada", "ofertas_amazon", "ofertas_fba", "painel_importada"])
def test_ofertas_das_paginas_reais(nome):
    esperado = ESPERADO[nome]
    ofertas = parse_ofertas(fixture_amazon(nome))
    assert len(ofertas) == esperado["num_ofertas"]
    destaque = ofertas[0]
    assert destaque.posicao == 0
    assert (destaque.vendedor_nome, destaque.preco) == (esperado["destaque"]["vendedor"], Decimal(esperado["destaque"]["preco"]))
    for e in esperado["ofertas"]:
        achada = next((o for o in ofertas if o.vendedor_nome == e["vendedor"] and o.preco == Decimal(e["preco"])), None)
        assert achada is not None, e
        for campo, valor in e.items():
            assert getattr(achada, NOMES_DOS_CAMPOS.get(campo, campo)) == _convertido(campo, valor), campo
    assert all(o.preco > 0 for o in ofertas)


def test_o_importado_real_tem_oferta_dos_eua():
    assert any(o.importada and o.origem_envio == "Estados Unidos" for o in parse_ofertas(fixture_amazon("ofertas_importada")))


def test_preco_do_rotulo_de_acessibilidade_com_desconto_e_preco_de():
    [oferta] = parse_ofertas(html_ofertas(bloco_oferta("R$ 326,17 com 16 por cento de desconto", de="R$ 388,91")))
    assert (oferta.preco, oferta.preco_de) == (Decimal("326.17"), Decimal("388.91"))


def test_lojista_fba_importado_com_avaliacao_prime_e_cupom():
    [oferta] = parse_ofertas(
        html_ofertas(
            bloco_oferta(origem="Estados Unidos", avaliacao=AVALIACAO, prime=True, internacional=True,
                         cupom="15% off na 1ª compra com cartão Amazon")
        )
    )
    assert (oferta.vendedor_nome, oferta.seller_id, oferta.envio) == ("Shazaar", "A2SHZ", Envio.FBA)
    assert (oferta.origem_envio, oferta.importada, oferta.prime) == ("Estados Unidos", True, True)
    assert (oferta.pct_positivas, oferta.num_avaliacoes) == (Decimal(100), 66)
    assert oferta.cupom.startswith("15% off na 1ª compra")
    assert (oferta.condicao, oferta.posicao) == ("novo", 1)


def test_vendido_pela_amazon_sem_bloco_de_envio():
    [oferta] = parse_ofertas(html_ofertas(bloco_oferta("R$ 314,11", "Amazon.com.br", seller_id=None, envia=None, destaque=True)))
    assert (oferta.envio, oferta.seller_id, oferta.posicao, oferta.importada) == (Envio.AMAZON, "amazon", 0, False)


def test_lojista_com_envio_proprio_e_usado():
    [oferta] = parse_ofertas(html_ofertas(bloco_oferta(vendedor="Loja X", seller_id="AX", envia="Loja X", condicao="Usado - Muito bom")))
    assert (oferta.envio, oferta.condicao) == (Envio.PROPRIO, "usado")


def test_cupom_de_codigo():
    [oferta] = parse_ofertas(html_ofertas(bloco_oferta(cupom="Economize com cupom de desconto CARTAO15OFF")))
    assert oferta.cupom == "cupom de desconto CARTAO15OFF"


def test_destaque_repetido_na_lista_conta_uma_vez_e_a_posicao_segue_o_bloco():
    ofertas = parse_ofertas(
        html_ofertas(
            bloco_oferta("R$ 314,11", "Amazon.com.br", seller_id=None, envia=None, destaque=True),
            bloco_oferta("R$ 314,11", "Amazon.com.br", seller_id=None, envia=None),
            bloco_oferta("R$ 275,91"),
        )
    )
    assert [(o.vendedor_nome, o.posicao) for o in ofertas] == [("Amazon.com.br", 0), ("Shazaar", 2)]


def test_oferta_sem_preco_e_descartada_sem_mudar_a_posicao_das_outras():
    ofertas = parse_ofertas(html_ofertas(bloco_oferta(""), bloco_oferta("R$ 275,91")))
    assert [(o.vendedor_nome, o.posicao) for o in ofertas] == [("Shazaar", 2)]


def test_painel_sem_ofertas_devolve_lista_vazia():
    assert parse_ofertas(html_ofertas()) == []


def test_pagina_sem_painel_levanta_erro_parser():
    with pytest.raises(ErroParser, match="painel de ofertas"):
        parse_ofertas("<html><body><p>Página não encontrada</p></body></html>")
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t10 uv run pytest tests/coletor_amazon/test_parsers_ofertas.py -q`
Expected: FAIL (ImportError: `parse_ofertas`).

- [ ] **Step 4: Implementação**

Em `src/tcg_sniper/coletor_amazon/parsers.py`: importe `OfertaLista` de `modelos`; acrescente ao docstring do módulo uma seção "Lista de ofertas (`/gp/product/ajax/aodAjaxMain...` ou `/dp/<ASIN>?aod=1`)" descrevendo os seletores do Step 1 como ficaram; e acrescente:

```python
SELETOR_OFERTA_DESTAQUE = "#aod-pinned-offer"
SELETOR_OFERTA_LISTA = "#aod-offer"
SELETORES_ESTRUTURA_OFERTAS = ("#aod-container", "#all-offers-display", "#aod-offer-list", "#aod-pinned-offer", "#aod-offer")
SELETOR_CONDICAO = "#aod-offer-heading"
SELETOR_VENDIDO_POR_OFERTA = "#aod-offer-soldBy .a-col-right"
SELETOR_ENVIADO_POR_OFERTA = "#aod-offer-shipsFrom .a-col-right"
SELETORES_PRECO_OFERTA = (".apex-pricetopay-accessibility-label", ".aok-offscreen", ".a-price .a-offscreen")
SELETORES_PRIME = ("i.a-icon-prime", ".a-icon-prime", '[aria-label*="Prime"]')
BLOCOS_OFERTAS = (SELETOR_OFERTA_DESTAQUE, "#aod-offer-list", SELETOR_OFERTA_LISTA)
_RE_VALOR = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2})")
_RE_PRECO_DE = re.compile(r"De:\s*R\$\s*(\d{1,3}(?:\.\d{3})+,\d{2}|\d+,\d{2})")
_RE_ORIGEM = re.compile(r"Origem do envio\s*:?\s*([^.]+)", re.IGNORECASE)
_RE_CUPOM = re.compile(r"(\d{1,2}\s*% off[^.]{0,80}|cupom de desconto \S+)", re.IGNORECASE)
_MARCAS_IMPORTADA = ("compra internacional", "tributos de importação")


def _preco_da_oferta(bloco: LexborNode) -> Decimal | None:
    """O preço a pagar: o rótulo de acessibilidade ("R$ 326,17 com 16 por cento de desconto"); o
    `.a-offscreen` visível veio vazio nas páginas reais. Textos "De: R$ ..." são o preço riscado."""
    for seletor in SELETORES_PRECO_OFERTA:
        for no in bloco.css(seletor):
            texto = no.text(separator=" ", strip=True)
            if not texto or texto.lower().startswith("de:"):
                continue
            achado = _RE_VALOR.search(texto)
            if achado:
                return parse_preco_brl(achado.group(1))
    return None


def _vendedor_da_oferta(bloco: LexborNode) -> tuple[str | None, str | None, str]:
    """(nome, seller_id, texto do bloco "Vendido por" com a avaliação)."""
    alvo = bloco.css_first(SELETOR_VENDIDO_POR_OFERTA)
    if alvo is None:
        return None, None, ""
    link = alvo.css_first("a")
    nome = (link.text(separator=" ", strip=True) if link is not None else None) or _texto(alvo, "span")
    seller_id = None
    if link is not None:
        valores = parse_qs(urlsplit(link.attributes.get("href") or "").query).get("seller")
        seller_id = valores[0] if valores else None
    return nome, seller_id, alvo.text(separator=" ", strip=True)


def _envio_da_oferta(bloco: LexborNode) -> tuple[str | None, str | None]:
    """(quem envia, origem do envio) de "Amazon Origem do envio Estados Unidos."."""
    alvo = bloco.css_first(SELETOR_ENVIADO_POR_OFERTA)
    if alvo is None:
        return None, None
    texto = alvo.text(separator=" ", strip=True)
    origem = _RE_ORIGEM.search(texto)
    quem = _RE_ORIGEM.sub("", _texto(alvo, "span") or texto).strip(" .") or None
    return quem, origem.group(1).strip() if origem else None


def _condicao(bloco: LexborNode) -> str:
    texto = (_texto(bloco, SELETOR_CONDICAO) or "").lower()
    if "novo" in texto or "new" in texto:
        return "novo"
    if "usado" in texto or "used" in texto:
        return "usado"
    return texto or "desconhecida"


def parse_ofertas(html: str) -> list[OfertaLista]:
    """Todas as ofertas do painel, a destacada (posição 0) primeiro. Lista vazia: o painel abriu sem
    oferta (indisponível). Sem nenhum bloco do painel → ErroParser (layout novo ou página errada)."""
    arvore = LexborHTMLParser(html)
    if not any(arvore.css_first(seletor) is not None for seletor in SELETORES_ESTRUTURA_OFERTAS):
        raise ErroParser("painel de ofertas não encontrado")
    blocos = [(0, bloco) for bloco in arvore.css(SELETOR_OFERTA_DESTAQUE)[:1]]
    blocos += list(enumerate(arvore.css(SELETOR_OFERTA_LISTA), start=1))
    ofertas: list[OfertaLista] = []
    vistas: set[tuple[str | None, Decimal, str]] = set()
    for posicao, bloco in blocos:
        preco = _preco_da_oferta(bloco)
        if preco is None:
            log.warning("oferta %d do painel sem preço legível; descartada", posicao)
            continue
        condicao = _condicao(bloco)
        nome, seller_id, texto_vendedor = _vendedor_da_oferta(bloco)
        if (nome, preco, condicao) in vistas:
            continue  # a destacada costuma se repetir na lista
        vistas.add((nome, preco, condicao))
        quem_envia, origem = _envio_da_oferta(bloco)
        envio = classificar_envio(nome, quem_envia)
        texto = bloco.text(separator=" ", strip=True)
        baixo = texto.lower()
        pct = _RE_PCT_POSITIVAS.search(texto_vendedor)
        num = _RE_NUM_AVALIACOES.search(texto_vendedor)
        de = _RE_PRECO_DE.search(texto)
        cupom = _RE_CUPOM.search(texto)
        ofertas.append(
            OfertaLista(
                posicao=posicao,
                vendedor_nome=nome,
                seller_id=SELLER_AMAZON if envio is Envio.AMAZON else seller_id,
                preco=preco,
                preco_de=parse_preco_brl(de.group(1)) if de else None,
                condicao=condicao,
                envio=envio,
                origem_envio=origem,
                importada=any(marca in baixo for marca in _MARCAS_IMPORTADA)
                or (origem is not None and origem.lower() != "brasil"),
                prime=any(bloco.css_first(seletor) is not None for seletor in SELETORES_PRIME),
                pct_positivas=Decimal(pct.group(1)) if pct else None,
                num_avaliacoes=int(num.group(1).replace(".", "")) if num else None,
                cupom=cupom.group(1).strip() if cupom else None,
            )
        )
    return ofertas
```

- [ ] **Step 5: Rodar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t10 uv run pytest -q && uv run ruff check .`
Expected: PASS. Se um teste das páginas reais falhar, o parser está errado ou o `esperado.json` foi lido errado: abra a fixture e decida pelo que a página mostra; nunca ajuste o `esperado.json` para o que o parser devolve sem conferir na página.

- [ ] **Step 6: Commit**

```bash
git add src/tcg_sniper/coletor_amazon/parsers.py tests/fakes_ofertas.py tests/coletor_amazon/test_parsers_ofertas.py
git commit -m "feat: parse every offer of an ASIN from the Amazon offers panel (price, seller, shipping, origin, import, Prime)"
```

---

### Task 11: Parsers do carrinho, do resumo do checkout e do login

**Files:**
- Create: `src/tcg_sniper/coletor_amazon/parsers_checkout.py`
- Create: `tests/fakes_checkout.py`
- Test: `tests/coletor_amazon/test_parsers_checkout.py` (novo)

**Interfaces:**
- Consumes: `cliques.ENTREGAR`, `cliques.ESCOPOS_CARRINHO_ATIVO`, `cliques.localizar` (Task 1); `parsers.URL_CARRINHO`; fixtures e `esperado.json` (Task 9).
- Produces:
  - `parsers_checkout.Carrinho(contador: int | None, asins_ativos: tuple[str, ...], subtotal: Decimal | None)`; `parse_carrinho(html: str) -> Carrinho` (sem contador e sem bloco do carrinho → `ErroParser`).
  - `parsers_checkout.Etapa` (`ENDERECO`, `RESUMO`, `LOGIN`, `DESCONHECIDA`); `ResumoCheckout(etapa, itens, frete, impostos, total)`; `parse_resumo_checkout(pagina: Pagina) -> ResumoCheckout`; `eh_login(pagina: Pagina) -> bool`.
  - `tests/fakes_checkout.py`: `URL_ENDERECO`, `URL_RESUMO`, `URL_LOGIN`; `item_carrinho(asin) -> str`; `carrinho(*ativos, salvos=(), subtotal=None, contador=None) -> Pagina`; `checkout_endereco(total="R$ 237,73", botao=...) -> Pagina`; `checkout_resumo(itens="R$ 237,73", frete="R$ 0,00", impostos="R$ 48,26", total="R$ 285,99") -> Pagina`; `login() -> Pagina`.

- [ ] **Step 1: Confirmar na fixture**

Abra `carrinho_um_item.html`, `carrinho_inicial.html`, `checkout_endereco.html` (se existir), `checkout_resumo.html` e `login.html` e confira:
- carrinho: contador `#nav-cart-count`; itens do carrinho ativo com `data-asin` dentro de um dos `ESCOPOS_CARRINHO_ATIVO`; "Salvo para depois" fora deles; subtotal em `[data-name="Subtotals"]` ("Subtotal (1 produto): R$ 275,91"), depois `#sc-subtotal-amount-activecart`, `#sc-subtotal-amount-buybox`;
- resumo: o bloco que contém "Total do pedido" — `#subtotals-marketplace-table`, `#order-summary-container`, `[data-testid="order-summary"]`, `#spc-order-summary`, e por fim `body`; as linhas "Itens:", "Frete:", "Taxas de importação ... :" e "Total do pedido:" (com "--" antes do endereço);
- login: URL com `/ap/signin`, ou `form[name="signIn"]`, `#ap_email`, `#ap_password`, `#ap_email_login`.
Onde a fixture mostrar outro seletor ou outro texto de linha, ponha-o **no início** da tupla ou regex correspondente no Step 4 e em `tests/fakes_checkout.py`.

- [ ] **Step 2: Páginas falsas e testes (falham)**

Create `tests/fakes_checkout.py`:

```python
"""Carrinho, checkout e login da Amazon no formato visto nas fixtures reais (tests/fixtures/amazon)."""

from fakes import pagina_html

from tcg_sniper.coletor_amazon.parsers import URL_CARRINHO

URL_ENDERECO = "https://www.amazon.com.br/checkout/p/p-000-0000000-0000000/address?pipelineType=Chewbacca"
URL_RESUMO = "https://www.amazon.com.br/checkout/p/p-000-0000000-0000000/spc?pipelineType=Chewbacca"
URL_LOGIN = "https://www.amazon.com.br/ap/signin?openid.return_to=x"
BOTAO_ENTREGAR = '<input data-testid="Address_selectShipToThisAddress" type="submit" value="Entregar neste endereço">'


def item_carrinho(asin: str) -> str:
    return (
        f'<div class="sc-list-item" data-asin="{asin}"><span class="sc-product-title">Item {asin}</span>'
        f'<input data-action="delete" name="submit.delete.{asin}" value="Excluir" type="submit" aria-label="Excluir Item {asin}"></div>'
    )


def carrinho(*ativos, salvos=(), subtotal=None, contador=None):
    n = len(ativos) if contador is None else contador
    soma = f'<div data-name="Subtotals">Subtotal ({n} produto): {subtotal}</div>' if subtotal else ""
    botao = '<input name="proceedToRetailCheckout" value="Fechar pedido" type="submit">' if ativos else ""
    return pagina_html(
        f'<html><body><span id="nav-cart-count">{n}</span>'
        f'<div data-name="Active Items">{"".join(map(item_carrinho, ativos))}</div>{soma}{botao}'
        f'<div data-name="Saved Items">{"".join(map(item_carrinho, salvos))}</div></body></html>',
        url=URL_CARRINHO,
    )


def checkout_endereco(total="R$ 237,73", botao=BOTAO_ENTREGAR):
    return pagina_html(
        f'<html><body>{botao}<div id="order-summary-container">Itens: -- Frete: -- Total do pedido: {total}</div></body></html>',
        url=URL_ENDERECO,
    )


def checkout_resumo(itens="R$ 237,73", frete="R$ 0,00", impostos="R$ 48,26", total="R$ 285,99"):
    taxa = f"Taxas de importação incluindo ICMS: {impostos} " if impostos else ""
    return pagina_html(
        f'<html><body><div id="order-summary-container">Itens: {itens} Frete: {frete} {taxa}Total do pedido: {total}</div>'
        '<input name="placeYourOrder1" type="submit" value="Confirmar pedido com cartão 0000"></body></html>',
        url=URL_RESUMO,
    )


def login():
    return pagina_html('<html><body><form name="signIn"><input id="ap_email"></form></body></html>', url=URL_LOGIN)
```

Create `tests/coletor_amazon/test_parsers_checkout.py`:

```python
import json
from decimal import Decimal

import pytest
from fakes import DIR_FIXTURES_AMAZON, fixture_amazon, pagina_html
from fakes_checkout import carrinho, checkout_endereco, checkout_resumo, login

from tcg_sniper.coletor_amazon.parsers_checkout import Etapa, ResumoCheckout, eh_login, parse_carrinho, parse_resumo_checkout
from tcg_sniper.parsing import ErroParser

ESPERADO = json.loads((DIR_FIXTURES_AMAZON / "esperado.json").read_text(encoding="utf-8"))


def _dinheiro(valor):
    return None if valor is None else Decimal(valor)


@pytest.mark.parametrize("nome", ["carrinho_inicial", "carrinho_um_item", "carrinho_vazio"])
def test_carrinhos_reais(nome):
    esperado = ESPERADO[nome]
    c = parse_carrinho(fixture_amazon(nome))
    assert (c.contador, list(c.asins_ativos)) == (esperado["contador"], esperado["asins_ativos"])
    if "subtotal" in esperado:
        assert c.subtotal == _dinheiro(esperado["subtotal"])


@pytest.mark.parametrize("nome", [n for n in ("checkout_endereco", "checkout_resumo", "login") if n in ESPERADO])
def test_checkout_e_login_reais(nome):
    esperado = ESPERADO[nome]
    resumo = parse_resumo_checkout(pagina_html(fixture_amazon(nome)))
    assert resumo.etapa is Etapa(esperado["etapa"])
    for campo in ("itens", "frete", "impostos", "total"):
        if campo in esperado:
            assert getattr(resumo, campo) == _dinheiro(esperado[campo]), campo


def test_carrinho_conta_so_os_ativos():
    c = parse_carrinho(carrinho("B0ALVO0001", salvos=("B0SALVO001",), subtotal="R$ 275,91").html)
    assert (c.contador, c.asins_ativos, c.subtotal) == (1, ("B0ALVO0001",), Decimal("275.91"))


def test_carrinho_so_com_salvos_esta_vazio():
    c = parse_carrinho(carrinho(salvos=("B0SALVO001",)).html)
    assert (c.contador, c.asins_ativos, c.subtotal) == (0, (), None)


def test_contador_ilegivel_vira_none():
    c = parse_carrinho('<html><body><span id="nav-cart-count">?</span><div data-name="Active Items"></div></body></html>')
    assert c.contador is None


def test_pagina_que_nao_e_carrinho_levanta():
    with pytest.raises(ErroParser):
        parse_carrinho("<html><body>outra página</body></html>")


def test_resumo_com_impostos_de_importacao():
    assert parse_resumo_checkout(checkout_resumo()) == ResumoCheckout(
        Etapa.RESUMO, Decimal("237.73"), Decimal("0.00"), Decimal("48.26"), Decimal("285.99")
    )


def test_resumo_nacional_sem_impostos_e_frete_gratis():
    resumo = parse_resumo_checkout(checkout_resumo("R$ 1.299,90", "Grátis", None, "R$ 1.299,90"))
    assert resumo == ResumoCheckout(Etapa.RESUMO, Decimal("1299.90"), Decimal("0.00"), None, Decimal("1299.90"))


def test_etapa_do_endereco_tem_itens_vazios():
    resumo = parse_resumo_checkout(checkout_endereco())
    assert (resumo.etapa, resumo.itens, resumo.total) == (Etapa.ENDERECO, None, Decimal("237.73"))


def test_login_pela_url_ou_pelo_formulario():
    assert eh_login(login())
    assert eh_login(pagina_html("<html><body>x</body></html>", url="https://www.amazon.com.br/ap/signin?x=1"))
    assert parse_resumo_checkout(login()).etapa is Etapa.LOGIN
    assert not eh_login(checkout_resumo())


def test_passo_desconhecido():
    pagina = pagina_html("<html><body>Escolha uma forma de pagamento</body></html>", url="https://www.amazon.com.br/checkout/p/x/pay")
    assert parse_resumo_checkout(pagina).etapa is Etapa.DESCONHECIDA
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t11 uv run pytest tests/coletor_amazon/test_parsers_checkout.py -q`
Expected: FAIL (ImportError: `parsers_checkout`).

- [ ] **Step 4: Implementação**

Create `src/tcg_sniper/coletor_amazon/parsers_checkout.py`:

```python
"""Parsers puros do carrinho, do resumo do checkout e da página de login da amazon.com.br, escritos a
partir das páginas reais anonimizadas em tests/fixtures/amazon (Task 9 do plano 2026-10-17).

Carrinho (`/gp/cart/view.html`): contador `#nav-cart-count`; itens do carrinho ativo com `data-asin`
dentro de `ESCOPOS_CARRINHO_ATIVO` ("Salvo para depois" fica fora); subtotal em
`[data-name="Subtotals"]` ("Subtotal (1 produto): R$ 275,91").

Checkout (`/checkout/p/p-<id>/address` e `/spc`): resumo com as linhas "Itens:", "Frete:",
"Taxas de importação incluindo ICMS:" (só em importados) e "Total do pedido:". No passo do endereço
os itens aparecem como "--" e há o botão "Entregar neste endereço".

Login: URL `/ap/signin` ou o formulário `form[name="signIn"]`.
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from selectolax.lexbor import LexborHTMLParser

from tcg_sniper.coletor_amazon.cliques import ENTREGAR, ESCOPOS_CARRINHO_ATIVO, localizar
from tcg_sniper.navegador.modelos import Pagina
from tcg_sniper.parsing import ErroParser, parse_preco_brl

SELETOR_CONTADOR = "#nav-cart-count"
SELETORES_SUBTOTAL = ('[data-name="Subtotals"]', "#sc-subtotal-amount-activecart", "#sc-subtotal-amount-buybox")
SELETORES_RESUMO = (
    "#subtotals-marketplace-table",
    "#order-summary-container",
    '[data-testid="order-summary"]',
    "#spc-order-summary",
    "body",
)
SELETORES_LOGIN = ('form[name="signIn"]', "#ap_email", "#ap_password", "#ap_email_login")
_VALOR = r"(R\$\s*(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2}|--|Gr[aá]tis)"
_RE_LINHAS = {
    "itens": re.compile(rf"Itens\s*:?\s*{_VALOR}", re.IGNORECASE),
    "frete": re.compile(rf"Frete(?: e manuseio)?\s*:?\s*{_VALOR}", re.IGNORECASE),
    "impostos": re.compile(rf"Taxas de importa[cç][aã]o[^:]*:\s*{_VALOR}", re.IGNORECASE),
    "total": re.compile(rf"Total do pedido\s*:?\s*{_VALOR}", re.IGNORECASE),
}
_RE_SUBTOTAL = re.compile(r"R\$\s*((?:\d{1,3}(?:\.\d{3})+|\d+),\d{2})")


@dataclass(frozen=True)
class Carrinho:
    contador: int | None  # None: contador ilegível (quem chama não pode supor carrinho vazio)
    asins_ativos: tuple[str, ...]
    subtotal: Decimal | None


class Etapa(StrEnum):
    ENDERECO = "endereco"
    RESUMO = "resumo"
    LOGIN = "login"
    DESCONHECIDA = "desconhecida"


@dataclass(frozen=True)
class ResumoCheckout:
    etapa: Etapa
    itens: Decimal | None
    frete: Decimal | None
    impostos: Decimal | None
    total: Decimal | None


def parse_carrinho(html: str) -> Carrinho:
    arvore = LexborHTMLParser(html)
    contador_no = arvore.css_first(SELETOR_CONTADOR)
    escopos = [no for escopo in ESCOPOS_CARRINHO_ATIVO for no in arvore.css(escopo)]
    if contador_no is None and not escopos:
        raise ErroParser("carrinho não encontrado")
    texto_contador = contador_no.text(strip=True) if contador_no is not None else ""
    contador = int(texto_contador) if texto_contador.isdecimal() else None
    asins: list[str] = []
    for escopo in escopos:
        for item in escopo.css("[data-asin]"):
            asin = (item.attributes.get("data-asin") or "").strip()
            if asin and asin not in asins:
                asins.append(asin)
    subtotal = None
    for seletor in SELETORES_SUBTOTAL:
        no = arvore.css_first(seletor)
        achado = _RE_SUBTOTAL.search(no.text(separator=" ", strip=True)) if no is not None else None
        if achado:
            subtotal = parse_preco_brl(achado.group(1))
            break
    return Carrinho(contador, tuple(asins), subtotal)


def eh_login(pagina: Pagina) -> bool:
    if "/ap/signin" in pagina.url:
        return True
    arvore = LexborHTMLParser(pagina.html)
    return any(arvore.css_first(seletor) is not None for seletor in SELETORES_LOGIN)


def _valor(texto: str) -> Decimal | None:
    if texto == "--":
        return None
    if texto.lower().startswith("gr"):
        return Decimal("0.00")
    return parse_preco_brl(texto)


def parse_resumo_checkout(pagina: Pagina) -> ResumoCheckout:
    """Itens, frete, impostos e total do resumo do pedido. RESUMO só com itens e total lidos; ENDERECO
    quando os itens ainda são "--" e há o botão "Entregar neste endereço"."""
    if eh_login(pagina):
        return ResumoCheckout(Etapa.LOGIN, None, None, None, None)
    arvore = LexborHTMLParser(pagina.html)
    texto = ""
    for seletor in SELETORES_RESUMO:
        no = arvore.css_first(seletor)
        if no is not None and _RE_LINHAS["total"].search(no.text(separator=" ", strip=True)):
            texto = no.text(separator=" ", strip=True)
            break
    valores = {}
    for campo, regex in _RE_LINHAS.items():
        achado = regex.search(texto)
        valores[campo] = _valor(achado.group(1)) if achado else None
    if valores["itens"] is not None and valores["total"] is not None:
        etapa = Etapa.RESUMO
    elif localizar(ENTREGAR, pagina) is not None:
        etapa = Etapa.ENDERECO
    else:
        etapa = Etapa.DESCONHECIDA
    return ResumoCheckout(etapa, **valores)
```

- [ ] **Step 5: Rodar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t11 uv run pytest -q && uv run ruff check .`
Expected: PASS (com as fixtures reais). Divergência entre parser e `esperado.json`: confira na página, como na Task 10.

- [ ] **Step 6: Commit**

```bash
git add src/tcg_sniper/coletor_amazon/parsers_checkout.py tests/fakes_checkout.py tests/coletor_amazon/test_parsers_checkout.py
git commit -m "feat: parse the Amazon cart, the checkout order summary (items, shipping, import taxes, total) and the login page"
```

---

### Task 12: Monitor de preço e busca sem página de produto

**Files:**
- Create: `src/tcg_sniper/coletor_amazon/monitor.py`
- Modify: `src/tcg_sniper/coletor_amazon/busca.py` (sai a confirmação na página do produto)
- Modify: `src/tcg_sniper/db/repositorio_amazon.py` (sai `confirmados_ausentes`)
- Test: `tests/coletor_amazon/test_monitor.py` (novo); `tests/coletor_amazon/test_busca.py` (substituído); `tests/coletor_amazon/test_varredura.py` e `tests/db/test_repositorio_amazon.py` (apagam os testes do que saiu)

**Interfaces:**
- Consumes: Task 3 (`gravar_ofertas`, `OfertaAvaliada`, `registrar_preco` com `OFERTAS`, `marcar_visto`, `conferencia_valida`, `ultima_conferencia`, `ofertas_da_ultima_leitura`, `TITULO_MANUAL`, `registrar_conferencia`); Task 4 (`motor.vendedor_elegivel`, `mensagens.Detalhes`); Task 10 (`parse_ofertas`, `fakes_ofertas`); Task 1 (`NavegadorInterativoFake`, `parsers.url_ofertas`, `SELETOR_PAINEL_OFERTAS`).
- Produces:
  - `busca.abrir_pagina(ctx: ContextoBusca, url: str) -> Pagina` e `busca.ler_pagina(ctx, pagina, sufixo, parser)` (os antigos `_abrir`/`_ler`, agora públicos); `ContextoBusca.navegador: NavegadorInterativo`.
  - `busca.Conferencia(candidatos: int)` (só um campo); `processar_produto` não abre página de produto nem de vendedor.
  - `monitor.ESPERA_OFERTAS_MS = 15_000`; `monitor.abrir_ofertas(ctx, asin) -> Pagina`.
  - `monitor.ResultadoMonitor(paginas: int, ofertas: int, melhor: OfertaLista | None)`.
  - `monitor.ler_anuncio(ctx: ContextoBusca, anuncio_id: int, asin: str) -> ResultadoMonitor` (lança `DesafioAmazon`, `ErroParser` com HTML salvo como `<nome_falha>-ofertas-<ASIN>.html`, ou `ErroRede`).
  - `monitor.aplicar_conferencia(ctx: ContextoBusca, anuncio_id: int, conferencia_id: int) -> None`.

- [ ] **Step 1: Testes do monitor (falham)**

Create `tests/coletor_amazon/test_monitor.py`:

```python
import random
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fakes import (
    NavegadorInterativoFake,
    NotificadorFake,
    criar_anuncio,
    criar_preco_liga,
    criar_produto,
    html_produto_amazon,
    html_vendedor,
    pagina_html,
)
from fakes_ofertas import bloco_oferta, html_ofertas
from sqlalchemy import select

from tcg_sniper.coletor_amazon.busca import ContextoBusca, DesafioAmazon
from tcg_sniper.coletor_amazon.monitor import aplicar_conferencia, ler_anuncio
from tcg_sniper.coletor_amazon.parsers import url_ofertas, url_produto, url_vendedor
from tcg_sniper.db import repositorio_amazon as repo
from tcg_sniper.db.models import (
    AnuncioAmazon,
    Envio,
    OfertaAmazon,
    Oportunidade,
    OrigemPreco,
    PrecoAtualAmazon,
    SituacaoCheckout,
    StatusCasamento,
    VendedorAmazon,
)
from tcg_sniper.notificador.base import Destino
from tcg_sniper.parsing import ErroParser

AGORA = datetime.fromisoformat("2026-10-15T15:00:00+00:00")
ASIN = "B0DNV55QBS"
BOA = "A classificação do vendedor é 5 de 5 estrelas (5.000 avaliações) 98% positivas nos últimos 12 meses"
POUCAS = "A classificação do vendedor é 5 de 5 estrelas (66 avaliações) 100% positivas nos últimos 12 meses"
CAPTCHA = '<html><body><form action="/errors/validateCaptcha"></form></body></html>'


@pytest.fixture
def anuncio(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "aether", nome="Aetherdrift Commander")
        criar_preco_liga(s, p, "1000.00", listagem_em=AGORA - timedelta(hours=2))
        return criar_anuncio(s, ASIN, produto=p, status=StatusCasamento.CONFIRMADO)


def contexto(sessoes, config, paginas):
    with sessoes() as s:
        cfg = repo.obter_config(s)
    navegador = NavegadorInterativoFake(paginas)
    notificador = NotificadorFake()
    ctx = ContextoBusca(
        sessoes=sessoes, navegador=navegador, notificador=notificador, config=config, cfg=cfg,
        relogio=lambda: AGORA, dormir=lambda _: None, rng=random.Random(1), nome_falha="amazon-monitor",
    )
    return ctx, navegador, notificador


def painel(*blocos, asin=ASIN):
    return pagina_html(html_ofertas(*blocos), url=url_ofertas(asin))


def amazon(preco, **kw):
    return bloco_oferta(preco, "Amazon.com.br", seller_id=None, envia=None, destaque=True, **kw)


def conferencia(sessoes, anuncio_id, anunciado, total, impostos=None, vendedor="Amazon.com.br", quando=AGORA):
    with sessoes() as s, s.begin():
        return repo.registrar_conferencia(
            s, em=quando, anuncio_id=anuncio_id, vendedor_nome=vendedor, preco_anunciado=Decimal(anunciado),
            itens=Decimal(anunciado), frete=Decimal("0.00"), impostos=None if impostos is None else Decimal(impostos),
            total=Decimal(total), situacao=SituacaoCheckout.OK, motivo=None, item_removido=True,
        ).id


def test_grava_todas_as_ofertas_e_a_melhor_elegivel_vira_o_preco(sessoes, config, anuncio):
    pagina = painel(
        amazon("R$ 900,00"),
        bloco_oferta("R$ 800,00", "Loja Boa", "A1BOA", avaliacao=BOA),
        bloco_oferta("R$ 700,00", "Shazaar", "A2SHZ", origem="Estados Unidos", avaliacao=POUCAS),
        bloco_oferta("R$ 600,00", "Loja X", "AX", envia="Loja X"),
    )
    ctx, navegador, notificador = contexto(sessoes, config, {url_ofertas(ASIN): pagina})
    resultado = ler_anuncio(ctx, anuncio.id, ASIN)
    assert (resultado.paginas, resultado.ofertas, resultado.melhor.vendedor_nome) == (1, 4, "Loja Boa")
    assert navegador.esperas == [(url_ofertas(ASIN), "#aod-pinned-offer, #aod-offer")]
    with sessoes() as s:
        atual = s.get(PrecoAtualAmazon, anuncio.id)
        lidas = list(s.scalars(select(OfertaAmazon).order_by(OfertaAmazon.preco)))
        shazaar = s.scalar(select(VendedorAmazon).where(VendedorAmazon.seller_id == "A2SHZ"))
        visto = s.get(AnuncioAmazon, anuncio.id).visto_ultimo_em
    assert (atual.preco, atual.origem, atual.envio) == (Decimal("800.00"), OrigemPreco.OFERTAS, Envio.FBA)
    assert [(o.vendedor_nome, o.elegivel, o.melhor) for o in lidas] == [
        ("Loja X", False, False), ("Shazaar", False, False), ("Loja Boa", True, True), ("Amazon.com.br", True, False),
    ]
    assert (shazaar.pct_positivas, shazaar.num_avaliacoes) == (Decimal(100), 66)  # do painel, sem abrir o perfil
    assert visto == AGORA
    assert notificador.mensagens == []  # 800 é 20% abaixo de 1.000: não chega aos 25%


def test_abre_oportunidade_com_o_preco_anunciado_nao_conferido(sessoes, config, anuncio):
    ctx, _, notificador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00", prime=True))})
    ler_anuncio(ctx, anuncio.id, ASIN)
    [(destino, texto)] = notificador.mensagens
    assert destino is Destino.OPORTUNIDADES
    assert (
        "Amazon: R$ 700,00, preço anunciado, não conferido (aguardando conferência) (vendido pela Amazon · Prime), "
        "30% abaixo da Liga"
    ) in texto


def test_conferencia_valida_troca_o_preco_pelo_total(sessoes, config, anuncio):
    conferencia(sessoes, anuncio.id, "700.00", "780.00", impostos="80.00", quando=AGORA - timedelta(hours=1))
    ctx, _, notificador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))})
    ler_anuncio(ctx, anuncio.id, ASIN)
    assert notificador.mensagens == []  # com os impostos fica 22% abaixo: não é oportunidade


def test_conferencia_valida_abre_com_o_total_conferido(sessoes, config, anuncio):
    conferencia(sessoes, anuncio.id, "700.00", "740.00", impostos="40.00", quando=AGORA - timedelta(hours=1))
    ctx, _, notificador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))})
    ler_anuncio(ctx, anuncio.id, ASIN)
    [(_, texto)] = notificador.mensagens
    assert "Amazon: R$ 740,00 conferido no checkout (impostos R$ 40,00, frete R$ 0,00) (vendido pela Amazon), 26% abaixo" in texto
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)).preco_amazon == Decimal("740.00")


def test_conferencia_desligada_aparece_como_motivo(sessoes, config, anuncio):
    with sessoes() as s, s.begin():
        repo.obter_config(s).checkout_ligado = False
    ctx, _, notificador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))})
    ler_anuncio(ctx, anuncio.id, ASIN)
    assert "não conferido (conferência desligada)" in notificador.mensagens[0][1]


def test_importada_prime_e_cupom_na_mensagem(sessoes, config, anuncio):
    bloco = bloco_oferta(
        "R$ 700,00", "Loja Boa", "A1BOA", avaliacao=BOA, origem="Estados Unidos", internacional=True, prime=True,
        cupom="15% off na 1ª compra com cartão Amazon",
    )
    ctx, _, notificador = contexto(sessoes, config, {url_ofertas(ASIN): painel(bloco)})
    ler_anuncio(ctx, anuncio.id, ASIN)
    texto = notificador.mensagens[0][1]
    assert "enviado pela Amazon · importado (EUA) · Prime)" in texto
    assert "Cupom: 15% off na 1ª compra com cartão Amazon (condicional, não descontado)" in texto


def test_sem_ofertas_registra_preco_nulo_e_fecha_a_oportunidade(sessoes, config, anuncio):
    ctx, _, notificador = contexto(sessoes, config, {url_ofertas(ASIN): [painel(amazon("R$ 700,00")), painel()]})
    ler_anuncio(ctx, anuncio.id, ASIN)  # abre a oportunidade
    resultado = ler_anuncio(ctx, anuncio.id, ASIN)  # anúncio indisponível
    assert (resultado.melhor, resultado.ofertas) == (None, 0)
    with sessoes() as s:
        assert s.get(PrecoAtualAmazon, anuncio.id).preco is None
        assert s.scalar(select(Oportunidade)).fechada_em is not None
    assert len(notificador.mensagens) == 1  # só o alerta da abertura


def test_painel_ilegivel_salva_o_html_e_levanta(sessoes, config, anuncio):
    ctx, _, _ = contexto(sessoes, config, {url_ofertas(ASIN): pagina_html("<html><body>layout novo</body></html>")})
    with pytest.raises(ErroParser):
        ler_anuncio(ctx, anuncio.id, ASIN)
    assert (config.dir_dados / "falhas" / f"amazon-monitor-ofertas-{ASIN}.html").exists()


def test_captcha_levanta_desafio(sessoes, config, anuncio):
    ctx, _, _ = contexto(sessoes, config, {url_ofertas(ASIN): pagina_html(CAPTCHA)})
    with pytest.raises(DesafioAmazon) as erro:
        ler_anuncio(ctx, anuncio.id, ASIN)
    assert erro.value.url == url_ofertas(ASIN)


def test_lojista_fba_sem_avaliacao_no_painel_abre_o_perfil_uma_vez(sessoes, config, anuncio):
    pagina = painel(bloco_oferta("R$ 700,00", "Loja X", "A1"))
    paginas = {url_ofertas(ASIN): [pagina, pagina], url_vendedor("A1"): pagina_html(html_vendedor("Loja X", 97, "2.340"))}
    ctx, navegador, notificador = contexto(sessoes, config, paginas)
    assert ler_anuncio(ctx, anuncio.id, ASIN).paginas == 2
    assert "vendido por Loja X (97% de 2.340 avaliações), enviado pela Amazon" in notificador.mensagens[0][1]
    assert ler_anuncio(ctx, anuncio.id, ASIN).paginas == 1  # avaliado há menos de 7 dias
    assert navegador.visitadas.count(url_vendedor("A1")) == 1 and len(notificador.mensagens) == 1


def test_oferta_usada_nunca_e_elegivel(sessoes, config, anuncio):
    pagina = painel(
        bloco_oferta("R$ 500,00", "Amazon.com.br", seller_id=None, envia=None, condicao="Usado - Como novo", destaque=True),
        bloco_oferta("R$ 950,00", "Amazon.com.br", seller_id=None, envia=None),
    )
    ctx, _, notificador = contexto(sessoes, config, {url_ofertas(ASIN): pagina})
    assert ler_anuncio(ctx, anuncio.id, ASIN).melhor.preco == Decimal("950.00")
    assert notificador.mensagens == []


def test_sem_elegivel_a_nova_mais_barata_vira_referencia_sem_alerta(sessoes, config, anuncio):
    pagina = painel(
        bloco_oferta("R$ 600,00", "Shazaar", "A2SHZ", avaliacao=POUCAS),
        bloco_oferta("R$ 650,00", "Loja X", "AX", envia="Loja X"),
    )
    ctx, _, notificador = contexto(sessoes, config, {url_ofertas(ASIN): pagina})
    assert ler_anuncio(ctx, anuncio.id, ASIN).melhor.vendedor_nome == "Shazaar"
    with sessoes() as s:
        atual = s.get(PrecoAtualAmazon, anuncio.id)
    assert (atual.preco, atual.envio) == (Decimal("600.00"), Envio.FBA)
    assert notificador.mensagens == []


def test_anuncio_colado_a_mao_le_a_pagina_do_produto_uma_vez(sessoes, config):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "pm", nome="Produto M")
        criar_preco_liga(s, p, "1000.00", listagem_em=AGORA)
        manual = repo.casar_link_manual(s, p.id, "B0MANUAL01", AGORA - timedelta(hours=1))
    pagina = painel(amazon("R$ 990,00"), asin="B0MANUAL01")
    paginas = {
        url_ofertas("B0MANUAL01"): [pagina, pagina],
        url_produto("B0MANUAL01"): pagina_html(html_produto_amazon("Caixa Manual", "R$ 990,00", "Amazon.com.br", None)),
    }
    ctx, _, _ = contexto(sessoes, config, paginas)
    assert ler_anuncio(ctx, manual.id, "B0MANUAL01").paginas == 2
    assert ler_anuncio(ctx, manual.id, "B0MANUAL01").paginas == 1
    with sessoes() as s:
        assert s.get(AnuncioAmazon, manual.id).titulo == "Caixa Manual"


def test_conferencia_atualiza_a_aberta_sem_novo_alerta_ou_fecha(sessoes, config, anuncio):
    ctx, _, notificador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 700,00"))})
    ler_anuncio(ctx, anuncio.id, ASIN)  # abre e avisa com o preço anunciado
    aplicar_conferencia(ctx, anuncio.id, conferencia(sessoes, anuncio.id, "700.00", "720.00", impostos="20.00"))
    with sessoes() as s:
        op = s.scalar(select(Oportunidade))
    assert (op.preco_amazon, op.preco_alertado, op.fechada_em) == (Decimal("720.00"), Decimal("700.00"), None)
    aplicar_conferencia(ctx, anuncio.id, conferencia(sessoes, anuncio.id, "700.00", "800.00", impostos="100.00"))
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)).fechada_em is not None
    assert len(notificador.mensagens) == 1


def test_conferencia_que_baixa_o_preco_abre_e_avisa_conferido(sessoes, config, anuncio):
    ctx, _, notificador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 760,00"))})
    ler_anuncio(ctx, anuncio.id, ASIN)  # 24%: candidata, não oportunidade
    assert notificador.mensagens == []
    aplicar_conferencia(ctx, anuncio.id, conferencia(sessoes, anuncio.id, "760.00", "740.00"))
    [(_, texto)] = notificador.mensagens
    assert "Amazon: R$ 740,00 conferido no checkout (frete R$ 0,00) (vendido pela Amazon), 26% abaixo" in texto


def test_conferencia_de_outro_preco_e_ignorada(sessoes, config, anuncio):
    ctx, _, notificador = contexto(sessoes, config, {url_ofertas(ASIN): painel(amazon("R$ 760,00"))})
    ler_anuncio(ctx, anuncio.id, ASIN)
    aplicar_conferencia(ctx, anuncio.id, conferencia(sessoes, anuncio.id, "690.00", "600.00"))
    assert notificador.mensagens == []
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)) is None
```

- [ ] **Step 2: Busca sem página de produto: testes**

Substitua `tests/coletor_amazon/test_busca.py` inteiro por:

```python
import random
from datetime import datetime, timedelta

import pytest
from fakes import (
    NavegadorFake,
    NotificadorFake,
    cartao_busca,
    criar_anuncio,
    criar_preco_liga,
    criar_produto,
    html_busca,
    pagina_html,
)
from sqlalchemy import select

from tcg_sniper.coletor_amazon.busca import Conferencia, ContextoBusca, DesafioAmazon, processar_produto, url_busca
from tcg_sniper.db import repositorio_amazon as repo
from tcg_sniper.db.models import AnuncioAmazon, ProdutoLiga, StatusCasamento
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


def test_asin_novo_fica_pendente_e_so_a_busca_e_aberta(sessoes, config, produto):
    with sessoes() as s:
        url = url_busca(repo.obter_config(s), NOME)
    dormidas = []
    ctx, navegador, notificador = contexto(sessoes, config, {url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 100,00"))}, dormidas)
    assert processar_produto(ctx, produto) == Conferencia(0)
    assert navegador.visitadas == [url] and len(dormidas) == 1
    with sessoes() as s:
        anuncio = s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.asin == "B01"))
    assert (anuncio.status_casamento, anuncio.produto_id) == (StatusCasamento.PENDENTE, produto.id)
    assert notificador.mensagens == []


def test_confirmado_barato_conta_candidato_sem_abrir_o_produto_nem_alertar(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    ctx, navegador, notificador = contexto(sessoes, config, {url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 700,00"))})
    assert processar_produto(ctx, produto) == Conferencia(1)
    assert navegador.visitadas == [url] and notificador.mensagens == []  # o preço e o alerta são do monitor


def test_confirmado_acima_do_limite_nao_e_candidato(sessoes, config, produto):
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B01", produto=produto, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    ctx, _, _ = contexto(sessoes, config, {url: busca(url, cartao_busca("B01", "Caixa FF", "R$ 750,01"))})
    assert processar_produto(ctx, produto) == Conferencia(0)


def test_asin_casado_com_outro_produto_compara_com_o_preco_dele(sessoes, config, produto):
    with sessoes() as s, s.begin():
        outro = criar_produto(s, "outro", nome="Outro produto")
        criar_preco_liga(s, outro, "100.00", listagem_em=AGORA)
        criar_anuncio(s, "B09", produto=outro, status=StatusCasamento.CONFIRMADO)
        url = url_busca(repo.obter_config(s), NOME)
    # R$ 700 é 30% abaixo do produto buscado (R$ 1.000), mas acima do produto casado (R$ 100).
    ctx, _, _ = contexto(sessoes, config, {url: busca(url, cartao_busca("B09", "Outro", "R$ 700,00"))})
    assert processar_produto(ctx, produto) == Conferencia(0)


def test_captcha_na_busca_levanta_desafio(sessoes, config, produto):
    with sessoes() as s:
        url = url_busca(repo.obter_config(s), NOME)
    ctx, _, _ = contexto(sessoes, config, {url: pagina_html(CAPTCHA)})
    with pytest.raises(DesafioAmazon) as erro:
        processar_produto(ctx, produto)
    assert erro.value.url == url


def test_pagina_que_nao_le_salva_o_html_e_levanta(sessoes, config, produto):
    with sessoes() as s:
        url = url_busca(repo.obter_config(s), NOME)
    ctx, _, _ = contexto(sessoes, config, {url: pagina_html("<html><body>layout novo</body></html>")})
    with pytest.raises(ErroParser):
        processar_produto(ctx, produto)
    assert (config.dir_dados / "falhas" / "amazon-1-1-busca.html").exists()


def test_usar_nome_en_busca_pelo_termo_em_ingles(sessoes, config, produto):
    with sessoes() as s, s.begin():
        s.get(ProdutoLiga, produto.id).nome_en = "Booster Box - Final Fantasy"
        cfg = repo.obter_config(s)
        url_pt, url_en = url_busca(cfg, NOME), url_busca(cfg, "Booster Box - Final Fantasy")
    assert "Booster+Box+Final+Fantasy" in url_en
    with sessoes() as s:
        p = s.get(ProdutoLiga, produto.id)
        ctx, navegador, _ = contexto(sessoes, config, {url_pt: busca(url_pt), url_en: busca(url_en)})
        processar_produto(ctx, p)
        processar_produto(ctx, p, usar_nome_en=True)
        processar_produto(ctx, p, usar_nome_en=False)
    assert navegador.visitadas == [url_pt, url_en, url_pt]


def test_usar_nome_en_sem_nome_en_busca_em_portugues(sessoes, config, produto):
    with sessoes() as s:
        url_pt = url_busca(repo.obter_config(s), NOME)
    ctx, navegador, _ = contexto(sessoes, config, {url_pt: busca(url_pt)})
    processar_produto(ctx, produto, usar_nome_en=True)
    assert navegador.visitadas == [url_pt]
```

Em `tests/coletor_amazon/test_varredura.py`, apague `test_so_ausente_conferido_nao_conta_como_candidato` (e os imports que ficarem sem uso: `html_produto_amazon`, `url_produto`). Em `tests/db/test_repositorio_amazon.py`, apague `test_confirmados_ausentes_mais_antigos_primeiro_e_com_limite`.

- [ ] **Step 3: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t12 uv run pytest tests/coletor_amazon/test_monitor.py tests/coletor_amazon/test_busca.py -q`
Expected: FAIL (ImportError: `monitor`; `Conferencia` com dois campos).

- [ ] **Step 4: `busca.py`**

Substitua `src/tcg_sniper/coletor_amazon/busca.py` por:

```python
"""Uma busca na Amazon para um produto da Liga (descoberta): grava os resultados (ASIN novo fica
pendente para o casamento) e o preço de origem `busca`. Não abre página de produto nem de vendedor:
o preço dos anúncios confirmados é do monitor (monitor.py). Não conhece fila, ciclo nem janela (ver
varredura.py). `abrir_pagina` e `ler_pagina` são usadas também pelo monitor e pela conferência."""

import dataclasses
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import quote_plus

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon
from tcg_sniper.coletor_amazon.parsers import parse_busca
from tcg_sniper.coletor_amazon.termo import termo_busca
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio_amazon as repo
from tcg_sniper.db.models import ConfigAmazon, ProdutoLiga
from tcg_sniper.navegador.base import NavegadorInterativo
from tcg_sniper.navegador.modelos import Pagina
from tcg_sniper.navegador.ritmo import Dormir, com_um_retry, pausa_aleatoria, salvar_html_falha
from tcg_sniper.notificador.base import Notificador
from tcg_sniper.oportunidades import motor
from tcg_sniper.parsing import ErroParser

log = logging.getLogger(__name__)


class DesafioAmazon(Exception):
    def __init__(self, url: str):
        super().__init__(url)
        self.url = url


MAX_HTMLS_FALHA = 3  # por ciclo: sob bloqueio ou layout novo toda página falha e cada uma tem 1-2 MB


@dataclass
class CotaHtmlFalha:
    """Quantos HTMLs de falha ainda podem ser salvos; a varredura cria uma por ciclo (e uma por dia no monitor)."""

    restante: int = MAX_HTMLS_FALHA

    def consumir(self) -> bool:
        if self.restante <= 0:
            return False
        self.restante -= 1
        return True


@dataclass
class ContextoBusca:
    sessoes: sessionmaker[Session]
    navegador: NavegadorInterativo
    notificador: Notificador
    config: Config
    cfg: ConfigAmazon
    relogio: Callable[[], datetime]
    dormir: Dormir
    rng: random.Random
    nome_falha: str  # prefixo do HTML salvo em <DIR_DADOS>/falhas quando um parser falha
    cota_falhas: CotaHtmlFalha = field(default_factory=CotaHtmlFalha)


def url_busca(cfg: ConfigAmazon, nome: str) -> str:
    return cfg.url_busca.replace("{termo}", quote_plus(termo_busca(nome)))


def abrir_pagina(ctx: ContextoBusca, url: str) -> Pagina:
    """Pausa humana, abre (uma nova tentativa em erro de rede) e para no CAPTCHA."""
    pausa_aleatoria(ctx.cfg.pausa_min_s, ctx.cfg.pausa_max_s, ctx.dormir, ctx.rng)
    pagina = com_um_retry(lambda: ctx.navegador.abrir(url), url, ctx.dormir)
    if eh_desafio_amazon(pagina):
        raise DesafioAmazon(url)
    return pagina


def ler_pagina[T](ctx: ContextoBusca, pagina: Pagina, sufixo: str, parser: Callable[[str], T]) -> T:
    try:
        return parser(pagina.html)
    except ErroParser:
        if ctx.cota_falhas.consumir():
            caminho = salvar_html_falha(ctx.config.dir_dados, f"{ctx.nome_falha}-{sufixo}", pagina.html)
            log.warning("parser da Amazon falhou em %s; HTML em %s", pagina.url, caminho)
        else:
            log.warning("parser da Amazon falhou em %s; HTML não salvo (limite atingido)", pagina.url)
        raise


@dataclasses.dataclass(frozen=True)
class Conferencia:
    candidatos: int  # confirmados da busca já no desconto pelo preço atual (só para o ritmo da fila)


def processar_produto(ctx: ContextoBusca, produto: ProdutoLiga, usar_nome_en: bool = False) -> Conferencia:
    """Busca o produto e grava os resultados. Devolve quantos anúncios confirmados da busca estão no
    desconto pelo preço atual (a fila busca mais vezes o produto que teve candidato). Lança
    DesafioAmazon (CAPTCHA), ErroParser (layout) ou ErroRede (depois de uma nova tentativa).
    `usar_nome_en` busca pelo nome em inglês (se o produto tiver um)."""
    nome = produto.nome_en if usar_nome_en and produto.nome_en else produto.nome
    pagina = abrir_pagina(ctx, url_busca(ctx.cfg, nome))
    itens = ler_pagina(ctx, pagina, "busca", lambda html: parse_busca(html, ctx.cfg.resultados_por_busca))
    with ctx.sessoes() as s, s.begin():
        anuncios = repo.gravar_busca(s, itens, produto.id, ctx.relogio(), ctx.config.zona)
        candidatos = sum(
            1
            for linha in repo.confirmados_com_referencia(s, [a.id for a in anuncios])
            if motor.atinge_desconto(
                linha.atual.preco, linha.liga.preco_a_partir if linha.liga else None, ctx.cfg.desconto_min_pct
            )
        )
    return Conferencia(candidatos)
```

Em `src/tcg_sniper/db/repositorio_amazon.py`, apague `confirmados_ausentes` (e o título da seção vira `# --- link manual ---`). Rode `grep -rn "confirmados_ausentes\|MAX_CONFIRMADOS_AUSENTES\|_confirmar\b" src tests` e confirme que não sobrou referência.

- [ ] **Step 5: `monitor.py`**

Create `src/tcg_sniper/coletor_amazon/monitor.py`:

```python
"""Monitor de preço: lê a lista de ofertas de um anúncio confirmado, grava todas as ofertas da leitura,
escolhe a melhor elegível (vira o preço atual do anúncio, origem `ofertas`), roda o motor com o total
do checkout quando há conferência válida para essa oferta e avisa o grupo. Também aplica à oportunidade
uma conferência de checkout ok recém-feita. Não conhece fila nem janela (ver varredura.py)."""

import dataclasses
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from tcg_sniper.coletor_amazon.busca import ContextoBusca, DesafioAmazon, abrir_pagina, ler_pagina
from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon
from tcg_sniper.coletor_amazon.modelos import AvaliacaoVendedor, OfertaLista
from tcg_sniper.coletor_amazon.parsers import (
    SELETOR_PAINEL_OFERTAS,
    parse_ofertas,
    parse_produto_amazon,
    parse_vendedor,
    url_ofertas,
    url_produto,
    url_vendedor,
)
from tcg_sniper.db import repositorio_amazon as repo
from tcg_sniper.db.models import (
    AnuncioAmazon,
    ConferenciaCheckout,
    ConfigAmazon,
    Envio,
    OrigemPreco,
    PrecoAtualLiga,
    SituacaoCheckout,
    VendedorAmazon,
)
from tcg_sniper.navegador.modelos import Pagina
from tcg_sniper.navegador.ritmo import com_um_retry, pausa_aleatoria
from tcg_sniper.notificador.base import Destino
from tcg_sniper.oportunidades import motor
from tcg_sniper.oportunidades.mensagens import Detalhes, mensagem_oportunidade
from tcg_sniper.parsing import ErroParser

log = logging.getLogger(__name__)

ESPERA_OFERTAS_MS = 15_000


@dataclass(frozen=True)
class ResultadoMonitor:
    paginas: int  # páginas abertas: lista de ofertas, perfis de vendedor, página do produto
    ofertas: int
    melhor: OfertaLista | None  # a que virou o preço atual (None: nenhuma oferta nova)


@dataclass(frozen=True)
class _Avaliada:
    oferta: OfertaLista
    vendedor: VendedorAmazon | None
    elegivel: bool


def _info(vendedor: VendedorAmazon | None) -> motor.Vendedor | None:
    if vendedor is None:
        return None
    return motor.Vendedor(vendedor.nome, vendedor.pct_positivas, vendedor.num_avaliacoes)


def _ref(liga: PrecoAtualLiga | None) -> motor.RefLiga:
    return motor.RefLiga(
        preco_a_partir=liga.preco_a_partir if liga else None,
        listagem_em=liga.listagem_em if liga else None,
        num_lojas=liga.num_lojas if liga else None,
        preco_medio=liga.preco_medio if liga else None,
    )


def abrir_ofertas(ctx: ContextoBusca, asin: str) -> Pagina:
    """Abre a lista de ofertas esperando os blocos do painel (o fragmento já os traz; a página do produto
    com ?aod=1 os carrega depois do load). Pausa humana, uma nova tentativa em erro de rede e para no
    CAPTCHA, como `abrir_pagina`."""
    url = url_ofertas(asin)
    pausa_aleatoria(ctx.cfg.pausa_min_s, ctx.cfg.pausa_max_s, ctx.dormir, ctx.rng)
    pagina = com_um_retry(
        lambda: ctx.navegador.abrir_e_esperar(url, SELETOR_PAINEL_OFERTAS, ESPERA_OFERTAS_MS), url, ctx.dormir
    )
    if eh_desafio_amazon(pagina):
        raise DesafioAmazon(url)
    return pagina


def _vendedor(ctx: ContextoBusca, oferta: OfertaLista) -> tuple[VendedorAmazon | None, int]:
    """Vendedor da oferta e quantas páginas abriu (0 ou 1). A avaliação mostrada no painel vale como a
    do perfil; sem ela, só um lojista FBA sem avaliação recente tem o perfil aberto (como antes)."""
    with ctx.sessoes() as s, s.begin():
        if oferta.envio is Envio.AMAZON:
            return repo.vendedor_da_amazon(s), 0
        if oferta.seller_id is None:
            return None, 0
        if oferta.pct_positivas is not None and oferta.num_avaliacoes is not None:
            avaliacao = AvaliacaoVendedor(oferta.seller_id, oferta.vendedor_nome, oferta.pct_positivas, oferta.num_avaliacoes)
            return repo.gravar_vendedor(s, avaliacao, ctx.relogio()), 0
        conhecido = repo.obter_vendedor(s, oferta.seller_id)
    recente = (
        conhecido is not None
        and conhecido.avaliado_em is not None
        and ctx.relogio() - conhecido.avaliado_em < timedelta(days=ctx.cfg.vendedor_reavaliar_dias)
    )
    if oferta.envio is not Envio.FBA or recente:
        return conhecido, 0
    seller_id = oferta.seller_id
    pagina = abrir_pagina(ctx, url_vendedor(seller_id))
    avaliacao = ler_pagina(ctx, pagina, f"vendedor-{seller_id}", lambda html: parse_vendedor(html, seller_id))
    if avaliacao.nome is None:
        avaliacao = dataclasses.replace(avaliacao, nome=oferta.vendedor_nome)
    with ctx.sessoes() as s, s.begin():
        return repo.gravar_vendedor(s, avaliacao, ctx.relogio()), 1


def _indice_melhor(avaliadas: list[_Avaliada]) -> int | None:
    """A elegível mais barata (empate: a de menor posição); sem elegível, a nova mais barata (vira a
    referência do preço, sem alerta); sem oferta nova, nenhuma."""
    for aceita in (lambda a: a.elegivel, lambda a: a.oferta.condicao == "novo"):
        indices = [i for i, a in enumerate(avaliadas) if aceita(a)]
        if indices:
            return min(indices, key=lambda i: (avaliadas[i].oferta.preco, avaliadas[i].oferta.posicao))
    return None


def _ler_titulo(ctx: ContextoBusca, anuncio_id: int, asin: str) -> int:
    """Anúncio colado à mão ainda com o título provisório: lê a página do produto (título, variação, imagem)."""
    pagina = abrir_pagina(ctx, url_produto(asin))
    try:
        oferta = ler_pagina(ctx, pagina, f"produto-{asin}", lambda html: parse_produto_amazon(html, asin))
    except ErroParser:
        log.warning("página do produto %s ilegível; o título fica para a próxima leitura", asin)
        return 1
    with ctx.sessoes() as s, s.begin():
        repo.atualizar_leitura(s, anuncio_id, oferta.titulo, oferta.variacao, ctx.relogio(), oferta.imagem_url)
    return 1


def _motivo_nao_conferido(s: Session, cfg: ConfigAmazon, anuncio_id: int, agora: datetime) -> str:
    if not cfg.checkout_ligado:
        return "conferência desligada"
    if cfg.checkout_sem_login_em is not None:
        return "conta Amazon sem login"
    ultima = repo.ultima_conferencia(s, anuncio_id)
    if (
        ultima is not None
        and ultima.situacao is SituacaoCheckout.FALHA
        and agora - ultima.em < timedelta(hours=cfg.checkout_validade_h)
    ):
        return f"a conferência falhou: {ultima.motivo or 'sem motivo'}"
    return "aguardando conferência"


def _aplicar(s, acao, aberta, linha, leitura, ref, vendedor_id, agora, alertar: bool) -> None:
    """Grava a decisão do motor. `alertar` False (conferência chegando): REALERTAR só atualiza."""
    if acao is motor.Acao.ABRIR:
        repo.abrir_oportunidade(
            s, anuncio_id=linha.anuncio.id, produto_id=linha.produto.id, preco_amazon=leitura.preco,
            preco_liga=ref.preco_a_partir, desconto_pct=motor.desconto_pct(leitura.preco, ref.preco_a_partir),
            vendedor_id=vendedor_id, envio=leitura.envio, agora=agora,
        )
    elif acao in (motor.Acao.REALERTAR, motor.Acao.ATUALIZAR):
        repo.atualizar_oportunidade(
            s, aberta, preco_amazon=leitura.preco, preco_liga=ref.preco_a_partir,
            desconto_pct=motor.desconto_pct(leitura.preco, ref.preco_a_partir), vendedor_id=vendedor_id,
            envio=leitura.envio, alertou=alertar and acao is motor.Acao.REALERTAR, agora=agora,
        )
    elif acao is motor.Acao.FECHAR:
        repo.fechar_oportunidade(s, aberta, agora)


def _mensagem(ctx: ContextoBusca, linha, leitura: motor.Leitura, ref: motor.RefLiga, detalhes: Detalhes) -> str:
    return mensagem_oportunidade(
        nome_produto=linha.produto.nome, variacao=linha.anuncio.variacao, leitura=leitura, ref=ref,
        url_amazon=linha.anuncio.url, host=ctx.config.host_publico, produto_id=linha.produto.id, detalhes=detalhes,
    )


def _decidir(ctx: ContextoBusca, anuncio_id: int, melhor: _Avaliada | None) -> None:
    agora = ctx.relogio()
    mensagem = None
    with ctx.sessoes() as s, s.begin():
        linhas = repo.confirmados_com_referencia(s, [anuncio_id])
        if not linhas:  # o casamento foi desfeito no admin enquanto a página abria
            return
        linha = linhas[0]
        ref = _ref(linha.liga)
        oferta = melhor.oferta if melhor else None
        conferencia = None
        if oferta is not None:
            conferencia = repo.conferencia_valida(
                s, anuncio_id, oferta.vendedor_nome, oferta.preco, agora, ctx.cfg.checkout_validade_h
            )
        preco = conferencia.total if conferencia is not None else (oferta.preco if oferta else None)
        leitura = motor.Leitura(preco, oferta.envio if oferta else Envio.DESCONHECIDO, _info(melhor.vendedor) if melhor else None)
        aberta = repo.oportunidade_aberta(s, anuncio_id)
        acao = motor.decidir(leitura, ref, motor.Regras.de(ctx.cfg), agora, aberta.preco_alertado if aberta else None)
        vendedor_id = melhor.vendedor.id if melhor and melhor.vendedor else None
        _aplicar(s, acao, aberta, linha, leitura, ref, vendedor_id, agora, alertar=True)
        if acao in (motor.Acao.ABRIR, motor.Acao.REALERTAR):
            selos = dict(
                importada=oferta.importada, origem_envio=oferta.origem_envio, prime=oferta.prime, cupom=oferta.cupom
            )
            if conferencia is not None:
                detalhes = Detalhes(
                    total_conferido=conferencia.total, impostos=conferencia.impostos, frete=conferencia.frete, **selos
                )
            else:
                detalhes = Detalhes(motivo_nao_conferido=_motivo_nao_conferido(s, ctx.cfg, anuncio_id, agora), **selos)
            mensagem = _mensagem(ctx, linha, leitura, ref, detalhes)
    if mensagem is not None:
        ctx.notificador.enviar(Destino.OPORTUNIDADES, mensagem)


def ler_anuncio(ctx: ContextoBusca, anuncio_id: int, asin: str) -> ResultadoMonitor:
    """Lê as ofertas do anúncio e decide a oportunidade. Lança DesafioAmazon, ErroParser (painel
    ilegível; HTML salvo) ou ErroRede."""
    pagina = abrir_ofertas(ctx, asin)
    ofertas = ler_pagina(ctx, pagina, f"ofertas-{asin}", parse_ofertas)
    paginas = 1
    regras = motor.Regras.de(ctx.cfg)
    avaliadas = []
    for oferta in ofertas:
        vendedor, abertas = _vendedor(ctx, oferta)
        paginas += abertas
        elegivel = oferta.condicao == "novo" and motor.vendedor_elegivel(oferta.envio, _info(vendedor), regras)
        avaliadas.append(_Avaliada(oferta, vendedor, elegivel))
    indice = _indice_melhor(avaliadas)
    melhor = avaliadas[indice] if indice is not None else None
    agora = ctx.relogio()
    with ctx.sessoes() as s, s.begin():
        repo.gravar_ofertas(
            s, anuncio_id, agora,
            [
                repo.OfertaAvaliada(a.oferta, a.vendedor.id if a.vendedor else None, a.elegivel, i == indice)
                for i, a in enumerate(avaliadas)
            ],
        )
        repo.registrar_preco(
            s, anuncio_id, melhor.oferta.preco if melhor else None, OrigemPreco.OFERTAS,
            melhor.vendedor.id if melhor and melhor.vendedor else None,
            melhor.oferta.envio if melhor else Envio.DESCONHECIDO, agora, ctx.config.zona,
        )
        repo.marcar_visto(s, anuncio_id, agora)
        anuncio = s.get(AnuncioAmazon, anuncio_id)
        titulo_provisorio = anuncio is not None and anuncio.titulo == repo.TITULO_MANUAL
    if titulo_provisorio:
        paginas += _ler_titulo(ctx, anuncio_id, asin)
    _decidir(ctx, anuncio_id, melhor)
    return ResultadoMonitor(paginas, len(ofertas), melhor.oferta if melhor else None)


def aplicar_conferencia(ctx: ContextoBusca, anuncio_id: int, conferencia_id: int) -> None:
    """Conferência ok recém-gravada: refaz a decisão com o total do checkout. Sem oportunidade aberta,
    abre e avisa (com o total conferido) se o total ainda dá o desconto; com uma aberta, só atualiza
    (sem novo aviso) ou fecha. Se a oferta mudou desde a leitura, não faz nada (a próxima leitura decide)."""
    agora = ctx.relogio()
    mensagem = None
    with ctx.sessoes() as s, s.begin():
        conferencia = s.get(ConferenciaCheckout, conferencia_id)
        linhas = repo.confirmados_com_referencia(s, [anuncio_id])
        if conferencia is None or conferencia.total is None or not linhas:
            return
        linha = linhas[0]
        if linha.atual.preco != conferencia.preco_anunciado:
            return
        ref = _ref(linha.liga)
        vendedor = s.get(VendedorAmazon, linha.atual.vendedor_id) if linha.atual.vendedor_id else None
        leitura = motor.Leitura(conferencia.total, linha.atual.envio, _info(vendedor))
        aberta = repo.oportunidade_aberta(s, anuncio_id)
        acao = motor.decidir(leitura, ref, motor.Regras.de(ctx.cfg), agora, aberta.preco_alertado if aberta else None)
        _aplicar(s, acao, aberta, linha, leitura, ref, linha.atual.vendedor_id, agora, alertar=False)
        if acao is motor.Acao.ABRIR:
            lidas = repo.ofertas_da_ultima_leitura(s, [anuncio_id]).get(anuncio_id, [])
            melhor = next((o for o in lidas if o.melhor), None)
            detalhes = Detalhes(
                total_conferido=conferencia.total, impostos=conferencia.impostos, frete=conferencia.frete,
                importada=bool(melhor and melhor.importada), origem_envio=melhor.origem_envio if melhor else None,
                prime=bool(melhor and melhor.prime),
            )
            mensagem = _mensagem(ctx, linha, leitura, ref, detalhes)
    if mensagem is not None:
        ctx.notificador.enviar(Destino.OPORTUNIDADES, mensagem)
```

- [ ] **Step 6: Rodar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t12 uv run pytest -q && uv run ruff check .`
Expected: PASS (`test_varredura.py` continua passando: a varredura só usa `processar_produto(...).candidatos`).

- [ ] **Step 7: Commit**

```bash
git add src/tcg_sniper/coletor_amazon/monitor.py src/tcg_sniper/coletor_amazon/busca.py src/tcg_sniper/db/repositorio_amazon.py tests/coletor_amazon/test_monitor.py tests/coletor_amazon/test_busca.py tests/coletor_amazon/test_varredura.py tests/db/test_repositorio_amazon.py
git commit -m "feat: price monitor reads every offer of a confirmed listing; search no longer opens product pages"
```

---

### Task 13: Conferência de checkout

**Files:**
- Create: `src/tcg_sniper/coletor_amazon/checkout.py`
- Test: `tests/coletor_amazon/test_checkout.py` (novo)

**Interfaces:**
- Consumes: Task 1 (`cliques.*`, `NavegadorInterativoFake`), Task 10 (`parse_ofertas`, `fakes_ofertas`), Task 11 (`parse_carrinho`, `parse_resumo_checkout`, `eh_login`, `Etapa`, `fakes_checkout`), Task 12 (`busca.DesafioAmazon`), Task 3 (`SituacaoCheckout`), fixtures e `esperado.json` (Task 9).
- Produces:
  - `checkout.AlvoCheckout(asin: str, vendedor_nome: str | None, preco_anunciado: Decimal)`.
  - `checkout.ResultadoCheckout(situacao: SituacaoCheckout, motivo: str | None, itens=None, frete=None, impostos=None, total=None, item_removido: bool = True, paginas: int = 0, desafio_url: str | None = None)`.
  - `checkout.conferir(nav: NavegadorInterativo, alvo: AlvoCheckout, abrir: Callable[[str], Pagina], pausar: Callable[[], None]) -> ResultadoCheckout`. Não grava no banco. `abrir` faz a pausa, a nova tentativa e levanta `DesafioAmazon` (a varredura passa `lambda url: abrir_pagina(ctx, url)`); `pausar` vem antes de cada clique e do painel.

Passos (do spec): carrinho com qualquer item ativo → `carrinho_ocupado` sem clicar; login pedido → `sem_login`; adicionar a oferta pelo botão dela no painel (achada por vendedor + preço + condição nova); conferir que o carrinho tem só esse ASIN (e o subtotal igual ao anunciado, quando legível); "Fechar pedido"; "Entregar neste endereço" se pedir; ler o resumo; sempre tentar tirar o item (mesmo com falha no meio). Nenhum outro clique; "Confirmar pedido" e "Comprar agora" nunca.

- [ ] **Step 1: Testes (falham)**

Create `tests/coletor_amazon/test_checkout.py`:

```python
import json
from decimal import Decimal

import pytest
from fakes import DIR_FIXTURES_AMAZON, NavegadorInterativoFake, fixture_amazon, pagina_html
from fakes_checkout import BOTAO_ENTREGAR, carrinho, checkout_endereco, checkout_resumo, login
from fakes_ofertas import bloco_oferta, html_ofertas

from tcg_sniper.coletor_amazon.busca import DesafioAmazon
from tcg_sniper.coletor_amazon.checkout import AlvoCheckout, conferir
from tcg_sniper.coletor_amazon.cliques import PROIBIDOS
from tcg_sniper.coletor_amazon.parsers import URL_CARRINHO, url_painel_ofertas
from tcg_sniper.db.models import SituacaoCheckout

ASIN = "B0DNV55QBS"
ALVO = AlvoCheckout(ASIN, "Shazaar", Decimal("275.91"))
ESPERADO = json.loads((DIR_FIXTURES_AMAZON / "esperado.json").read_text(encoding="utf-8"))
EXCLUIR_ATIVO = f'[data-name="Active Items"] [data-asin="{ASIN}"] input[data-action="delete"]'


def painel(*blocos):
    return pagina_html(html_ofertas(*blocos, comprar_agora=True), url=url_painel_ofertas(ASIN))


PAINEL = painel(
    bloco_oferta("R$ 314,11", "Amazon Global", seller_id=None, envia=None, destaque=True),
    bloco_oferta("R$ 275,91", "Shazaar", "A2SHZ", origem="Estados Unidos"),
)


def conferir_com(paginas, apos_clique):
    nav = NavegadorInterativoFake(paginas, apos_clique)
    return conferir(nav, ALVO, nav.abrir, lambda: None), nav


def clicados(nav):
    return [seletor for seletor, _ in nav.cliques]


def nenhum_proibido(nav):
    return not any(trecho in seletor.lower() for seletor in clicados(nav) for trecho in ("placeyourorder", "buy-now", "submitorder"))


def test_conferencia_ok_le_o_resumo_e_tira_o_item():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [um_item, checkout_endereco(), checkout_resumo(), carrinho()],
    )
    assert (resultado.situacao, resultado.motivo) == (SituacaoCheckout.OK, None)
    assert (resultado.itens, resultado.frete, resultado.impostos, resultado.total) == (
        Decimal("237.73"), Decimal("0.00"), Decimal("48.26"), Decimal("285.99"),
    )
    assert resultado.item_removido and resultado.paginas == 9
    assert clicados(nav) == [
        '#aod-offer input[name="submit.addToCart"]',
        'input[name="proceedToRetailCheckout"]',
        'input[data-testid="Address_selectShipToThisAddress"]',
        EXCLUIR_ATIVO,
    ]
    assert nav.cliques[0] == ('#aod-offer input[name="submit.addToCart"]', 0)  # o botão da Shazaar, não o da destacada
    assert nenhum_proibido(nav)


def test_checkout_direto_no_resumo_sem_passo_do_endereco():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [um_item, checkout_resumo(), carrinho()],
    )
    assert resultado.situacao is SituacaoCheckout.OK and resultado.total == Decimal("285.99")
    assert len(nav.cliques) == 3


def test_carrinho_ocupado_nao_clica_em_nada():
    resultado, nav = conferir_com({URL_CARRINHO: carrinho("B0OUTRO001", "B0OUTRO002")}, [])
    assert (resultado.situacao, resultado.item_removido, resultado.paginas) == (SituacaoCheckout.CARRINHO_OCUPADO, True, 1)
    assert nav.cliques == [] and nav.visitadas == [URL_CARRINHO]


def test_itens_salvos_para_depois_nao_contam_e_nunca_sao_tocados():
    salvos = ("B0SALVO001", ASIN)
    um_item = carrinho(ASIN, salvos=salvos, subtotal="R$ 275,91")
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(salvos=salvos), um_item, um_item, carrinho(salvos=salvos)], url_painel_ofertas(ASIN): PAINEL},
        [um_item, checkout_resumo(), carrinho(salvos=salvos)],
    )
    assert resultado.situacao is SituacaoCheckout.OK and resultado.item_removido
    assert clicados(nav)[-1] == EXCLUIR_ATIVO
    assert not any("Saved Items" in seletor for seletor in clicados(nav))


def test_login_no_carrinho_e_sem_login_sem_clicar():
    resultado, nav = conferir_com({URL_CARRINHO: login()}, [])
    assert resultado.situacao is SituacaoCheckout.SEM_LOGIN and nav.cliques == []


def test_login_expirado_no_checkout_retira_o_item():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [um_item, login(), carrinho()],
    )
    assert (resultado.situacao, resultado.item_removido, resultado.total) == (SituacaoCheckout.SEM_LOGIN, True, None)
    assert clicados(nav)[-1] == EXCLUIR_ATIVO


def test_botao_proibido_no_lugar_de_entregar_nao_e_clicado_e_o_item_sai():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    armadilha = checkout_endereco(botao='<input data-testid="Address_selectShipToThisAddress" type="submit" value="Confirmar pedido">')
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [um_item, armadilha, carrinho()],
    )
    assert resultado.situacao is SituacaoCheckout.FALHA and "proibido" in resultado.motivo
    assert resultado.item_removido
    assert clicados(nav) == ['#aod-offer input[name="submit.addToCart"]', 'input[name="proceedToRetailCheckout"]', EXCLUIR_ATIVO]


def test_o_botao_de_confirmar_do_resumo_nunca_e_clicado():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [um_item, checkout_endereco(), checkout_resumo(), carrinho()],
    )
    assert resultado.situacao is SituacaoCheckout.OK
    assert nenhum_proibido(nav)
    for seletor in clicados(nav):
        assert not any(trecho in seletor.lower() for trecho in PROIBIDOS)


def test_falha_no_meio_ainda_tira_o_item():
    sem_botao = pagina_html(carrinho(ASIN, subtotal="R$ 275,91").html.replace('name="proceedToRetailCheckout"', 'name="outro"'), url=URL_CARRINHO)
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), sem_botao, sem_botao, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [sem_botao, carrinho()],
    )
    assert resultado.situacao is SituacaoCheckout.FALHA and "fechar pedido" in resultado.motivo
    assert resultado.item_removido and clicados(nav)[-1] == EXCLUIR_ATIVO


def test_item_que_nao_sai_fica_registrado():
    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    resultado, _ = conferir_com(
        {URL_CARRINHO: [carrinho(), um_item, um_item, um_item], url_painel_ofertas(ASIN): PAINEL},
        [um_item, checkout_resumo(), um_item],  # o clique em Excluir não tirou o item
    )
    assert resultado.situacao is SituacaoCheckout.OK and not resultado.item_removido
    assert "pode ter ficado no carrinho" in resultado.motivo


def test_oferta_que_mudou_nao_e_adicionada():
    outro_preco = painel(bloco_oferta("R$ 289,90", "Shazaar", "A2SHZ"))
    resultado, nav = conferir_com({URL_CARRINHO: carrinho(), url_painel_ofertas(ASIN): outro_preco}, [])
    assert resultado.situacao is SituacaoCheckout.FALHA and "não está mais no painel" in resultado.motivo
    assert nav.cliques == [] and resultado.item_removido


def test_subtotal_diferente_do_anunciado_falha_e_tira_o_item():
    caro = carrinho(ASIN, subtotal="R$ 314,11")  # entrou a oferta errada
    resultado, nav = conferir_com(
        {URL_CARRINHO: [carrinho(), caro, caro, carrinho()], url_painel_ofertas(ASIN): PAINEL},
        [caro, carrinho()],
    )
    assert resultado.situacao is SituacaoCheckout.FALHA and "subtotal" in resultado.motivo
    assert resultado.item_removido and clicados(nav)[-1] == EXCLUIR_ATIVO


def test_captcha_no_meio_devolve_o_desafio_sem_tentar_tirar():
    def abrir(url, contagem=[0]):
        contagem[0] += 1
        if contagem[0] == 2:
            raise DesafioAmazon(URL_CARRINHO)
        return nav.abrir(url)

    um_item = carrinho(ASIN, subtotal="R$ 275,91")
    nav = NavegadorInterativoFake({URL_CARRINHO: [carrinho(), um_item], url_painel_ofertas(ASIN): PAINEL}, [um_item])
    resultado = conferir(nav, ALVO, abrir, lambda: None)
    assert (resultado.situacao, resultado.desafio_url, resultado.item_removido) == (SituacaoCheckout.FALHA, URL_CARRINHO, False)


def test_fluxo_com_as_paginas_reais():
    destaque = ESPERADO["painel_importada"]["destaque"]
    alvo = AlvoCheckout(ESPERADO["painel_importada"]["asin"], destaque["vendedor"], Decimal(destaque["preco"]))
    real = {nome: pagina_html(fixture_amazon(nome), url=URL_CARRINHO) for nome in ("carrinho_vazio", "carrinho_um_item")}
    passos = [real["carrinho_um_item"]]
    if "checkout_endereco" in ESPERADO:
        passos.append(pagina_html(fixture_amazon("checkout_endereco")))
    passos += [pagina_html(fixture_amazon("checkout_resumo")), real["carrinho_vazio"]]
    nav = NavegadorInterativoFake(
        {
            URL_CARRINHO: [real["carrinho_vazio"], real["carrinho_um_item"], real["carrinho_um_item"], real["carrinho_vazio"]],
            url_painel_ofertas(alvo.asin): pagina_html(fixture_amazon("painel_importada"), url=url_painel_ofertas(alvo.asin)),
        },
        passos,
    )
    resultado = conferir(nav, alvo, nav.abrir, lambda: None)
    esperado = ESPERADO["checkout_resumo"]
    assert resultado.situacao is SituacaoCheckout.OK, resultado.motivo
    assert resultado.total == Decimal(esperado["total"]) and resultado.item_removido
    assert nenhum_proibido(nav)
```

(Em `test_captcha_no_meio...`, `nav` é lido pela função `abrir` só quando chamada, depois de criado.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t13 uv run pytest tests/coletor_amazon/test_checkout.py -q`
Expected: FAIL (ImportError: `checkout`).

- [ ] **Step 3: Implementação**

Create `src/tcg_sniper/coletor_amazon/checkout.py`:

```python
"""Conferência de checkout: põe uma oferta no carrinho, vai até o resumo do pedido (sem confirmar), lê
itens, frete, impostos e total, e tira o item do carrinho. Todo clique passa por
`cliques.clicar_permitido`; nada aqui confirma pedido nem usa "Comprar agora". Com qualquer item no
carrinho ativo, não clica em nada. Não grava no banco: a varredura registra a `conferencia_checkout`
e aplica o resultado à oportunidade."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from tcg_sniper.coletor_amazon.busca import DesafioAmazon
from tcg_sniper.coletor_amazon.cliques import (
    ADICIONAR,
    ENTREGAR,
    ESCOPO_OFERTA_DESTAQUE,
    ESCOPO_OFERTA_LISTA,
    FECHAR_PEDIDO,
    Acao,
    CliqueProibido,
    SeletorAusente,
    clicar_permitido,
    remover_do_carrinho,
)
from tcg_sniper.coletor_amazon.desafio import eh_desafio_amazon
from tcg_sniper.coletor_amazon.modelos import OfertaLista
from tcg_sniper.coletor_amazon.parsers import SELETOR_PAINEL_OFERTAS, URL_CARRINHO, parse_ofertas, url_painel_ofertas
from tcg_sniper.coletor_amazon.parsers_checkout import Etapa, ResumoCheckout, eh_login, parse_carrinho, parse_resumo_checkout
from tcg_sniper.db.models import SituacaoCheckout
from tcg_sniper.navegador.base import NavegadorInterativo
from tcg_sniper.navegador.modelos import ErroRede, Pagina
from tcg_sniper.parsing import ErroParser

log = logging.getLogger(__name__)

ERROS_DO_PASSO = (CliqueProibido, SeletorAusente, ErroParser, ErroRede)


@dataclass(frozen=True)
class AlvoCheckout:
    asin: str
    vendedor_nome: str | None
    preco_anunciado: Decimal


@dataclass(frozen=True)
class ResultadoCheckout:
    situacao: SituacaoCheckout
    motivo: str | None
    itens: Decimal | None = None
    frete: Decimal | None = None
    impostos: Decimal | None = None
    total: Decimal | None = None
    item_removido: bool = True  # False: o item pode ter ficado no carrinho (a varredura tenta de novo)
    paginas: int = 0
    desafio_url: str | None = None  # CAPTCHA no meio: a varredura pausa a Amazon


class _Parada(Exception):
    def __init__(self, situacao: SituacaoCheckout, motivo: str):
        super().__init__(motivo)
        self.situacao, self.motivo = situacao, motivo


def _achar(ofertas: list[OfertaLista], alvo: AlvoCheckout) -> OfertaLista | None:
    return next(
        (
            o for o in ofertas
            if o.condicao == "novo" and o.preco == alvo.preco_anunciado and o.vendedor_nome == alvo.vendedor_nome
        ),
        None,
    )


def _escopo(oferta: OfertaLista) -> tuple[str, int]:
    """Bloco do painel onde está o botão da oferta: a destacada ou o n-ésimo #aod-offer."""
    if oferta.posicao == 0:
        return ESCOPO_OFERTA_DESTAQUE, 0
    return ESCOPO_OFERTA_LISTA, oferta.posicao - 1


def conferir(
    nav: NavegadorInterativo, alvo: AlvoCheckout, abrir: Callable[[str], Pagina], pausar: Callable[[], None]
) -> ResultadoCheckout:
    paginas = 0
    adicionou = False
    resumo: ResumoCheckout | None = None
    situacao, motivo, desafio = SituacaoCheckout.OK, None, None

    def abrir_contando(url: str) -> Pagina:
        nonlocal paginas
        paginas += 1
        return abrir(url)

    def clicar(acao: Acao, pagina: Pagina, escopo: str = "", bloco: int = 0) -> Pagina:
        nonlocal paginas
        pausar()
        paginas += 1
        return clicar_permitido(nav, acao, pagina, escopo, bloco)

    try:
        carrinho = abrir_contando(URL_CARRINHO)
        if eh_login(carrinho):
            raise _Parada(SituacaoCheckout.SEM_LOGIN, "a Amazon pediu login no carrinho")
        estado = parse_carrinho(carrinho.html)
        if estado.contador is None:
            raise _Parada(SituacaoCheckout.FALHA, "contador do carrinho ilegível; nada foi clicado")
        if estado.contador or estado.asins_ativos:
            raise _Parada(SituacaoCheckout.CARRINHO_OCUPADO, f"{estado.contador} item(ns) no carrinho; nada foi clicado")
        url = url_painel_ofertas(alvo.asin)
        pausar()
        paginas += 1
        painel = nav.abrir_e_esperar(url, SELETOR_PAINEL_OFERTAS)
        if eh_desafio_amazon(painel):
            raise DesafioAmazon(url)
        oferta = _achar(parse_ofertas(painel.html), alvo)
        if oferta is None:
            raise _Parada(SituacaoCheckout.FALHA, "a oferta não está mais no painel (preço ou vendedor mudou)")
        adicionou = True  # daqui em diante pode haver item nosso no carrinho, mesmo se o clique der erro
        clicar(ADICIONAR, painel, *_escopo(oferta))
        carrinho = abrir_contando(URL_CARRINHO)
        estado = parse_carrinho(carrinho.html)
        if estado.asins_ativos != (alvo.asin,):
            raise _Parada(
                SituacaoCheckout.FALHA,
                f"carrinho inesperado depois de adicionar: {', '.join(estado.asins_ativos) or 'vazio'}",
            )
        if estado.subtotal is not None and estado.subtotal != alvo.preco_anunciado:
            raise _Parada(
                SituacaoCheckout.FALHA, f"subtotal do carrinho R$ {estado.subtotal} diferente do anunciado R$ {alvo.preco_anunciado}"
            )
        pagina = clicar(FECHAR_PEDIDO, carrinho)
        resumo = parse_resumo_checkout(pagina)
        if resumo.etapa is Etapa.ENDERECO:
            pagina = clicar(ENTREGAR, pagina)
            resumo = parse_resumo_checkout(pagina)
        if resumo.etapa is Etapa.LOGIN:
            raise _Parada(SituacaoCheckout.SEM_LOGIN, "o checkout pediu login")
        if resumo.etapa is not Etapa.RESUMO:
            raise _Parada(SituacaoCheckout.FALHA, f"passo inesperado no checkout ({pagina.url})")
    except _Parada as parada:
        situacao, motivo = parada.situacao, parada.motivo
    except DesafioAmazon as erro:
        situacao, motivo, desafio = SituacaoCheckout.FALHA, f"CAPTCHA em {erro.url}", erro.url
    except ERROS_DO_PASSO as erro:
        situacao, motivo = SituacaoCheckout.FALHA, str(erro)

    removido = not adicionou
    if adicionou and desafio is None:
        try:
            removido, abertas = remover_do_carrinho(nav, alvo.asin, abrir, pausar)
            paginas += abertas
        except DesafioAmazon as erro:
            desafio = erro.url
        except ERROS_DO_PASSO as erro:
            log.warning("não deu para tirar %s do carrinho: %s", alvo.asin, erro)
        if not removido:
            motivo = f"{motivo}; o item pode ter ficado no carrinho" if motivo else "o item pode ter ficado no carrinho"
    if situacao is not SituacaoCheckout.OK or resumo is None:
        return ResultadoCheckout(situacao, motivo, item_removido=removido, paginas=paginas, desafio_url=desafio)
    return ResultadoCheckout(
        situacao, motivo, resumo.itens, resumo.frete, resumo.impostos, resumo.total, removido, paginas, desafio
    )
```

- [ ] **Step 4: Rodar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t13 uv run pytest -q && uv run ruff check .`
Expected: PASS. Se `test_fluxo_com_as_paginas_reais` falhar num clique, o seletor da fixture não está na lista de `cliques.py`: volte à Task 9, Step 5.

- [ ] **Step 5: Commit**

```bash
git add src/tcg_sniper/coletor_amazon/checkout.py tests/coletor_amazon/test_checkout.py
git commit -m "feat: checkout check reads items, shipping, import taxes and total without ever placing an order, and always removes the item"
```

---

### Task 14: Varredura com três trabalhos, README e implantação

**Files:**
- Modify: `src/tcg_sniper/coletor_amazon/varredura.py` (substituído)
- Modify: `README.md`
- Test: `tests/coletor_amazon/test_varredura_monitor.py` (novo); `tests/coletor_amazon/test_varredura.py` continua passando

**Interfaces:**
- Consumes: tudo das Tasks 1–13: `repositorio_amazon.conferencias_com_item_no_carrinho`, `marcar_item_removido`, `candidatas_ao_checkout`, `CandidataCheckout`, `registrar_conferencia`, `ultima_conferencia`, `proximo_do_monitor`, `limpar_ofertas_antigas`, `ids_na_fila(s, agora, casados_dias)`, `proximo_da_fila(s, agora, casados_dias)`; `coletor_amazon.config.aplicar_config`; `cliques.remover_do_carrinho`, `CliqueProibido`, `SeletorAusente`; `checkout.conferir`, `AlvoCheckout`; `monitor.ler_anuncio`, `aplicar_conferencia`; `busca.abrir_pagina`, `ContextoBusca`, `CotaHtmlFalha`, `DesafioAmazon`, `processar_produto`; `fakes_ofertas`, `fakes_checkout`, `NavegadorInterativoFake`, `oferta_lista`.
- Produces:
  - `varredura.ESPERA_CARRINHO_OCUPADO = timedelta(hours=1)`, `varredura.ESPERA_RETIRADA = timedelta(minutes=15)`.
  - `varredura.mensagem_sem_login(config: Config) -> str`.
  - `VarreduraAmazon.passo()` escolhe, por prioridade: (1) tirar do carrinho um item que ficou de uma conferência; (2) conferir uma candidata; (3) ler as ofertas do confirmado mais atrasado; (4) descoberta. 1–3 só dentro da janela do monitor e enquanto as páginas da última hora (somando 1–3) estão abaixo de `monitor_max_paginas_hora`; 4 dentro da janela da busca e com o teto `max_buscas_hora`, só para produtos sem casamento ou casados com a última busca há `descoberta_casados_dias` dias.

- [ ] **Step 1: Testes (falham)**

Create `tests/coletor_amazon/test_varredura_monitor.py`:

```python
import random
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fakes import (
    NavegadorInterativoFake,
    NotificadorFake,
    criar_anuncio,
    criar_preco_liga,
    criar_produto,
    html_busca,
    oferta_lista,
    pagina_html,
)
from fakes_checkout import carrinho, checkout_resumo, login
from fakes_ofertas import bloco_oferta, html_ofertas
from sqlalchemy import select

from tcg_sniper.coletor_amazon.busca import url_busca
from tcg_sniper.coletor_amazon.config import aplicar_config
from tcg_sniper.coletor_amazon.parsers import URL_CARRINHO, url_ofertas, url_painel_ofertas
from tcg_sniper.coletor_amazon.varredura import ESPERA_OCIOSA_S, VarreduraAmazon
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    ConferenciaCheckout,
    EstadoColetorTipo,
    Envio,
    OfertaAmazon,
    Oportunidade,
    OrigemPreco,
    SituacaoCheckout,
    StatusCasamento,
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

    def __call__(self):
        fabrica = self

        class Contexto:
            def __enter__(self):
                return fabrica.navegador

            def __exit__(self, *_exc):
                pass

        return Contexto()


def varredura(engine, sessoes, config, paginas, apos_clique=None, relogio=None):
    navegador = NavegadorInterativoFake(paginas, apos_clique or [])
    notificador = NotificadorFake()
    relogio = relogio or Relogio(MEIO_DIA)
    v = VarreduraAmazon(
        engine, sessoes, FabricaFake(navegador), notificador, config,
        relogio=relogio, rng=random.Random(1), dormir=lambda _: None,
    )
    return v, navegador, notificador, relogio


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


def painel(asin, preco):
    return pagina_html(
        html_ofertas(bloco_oferta(preco, "Amazon.com.br", seller_id=None, envia=None, destaque=True), comprar_agora=True),
        url=url_painel_ofertas(asin),
    )


def conferencias(sessoes):
    with sessoes() as s:
        return list(s.scalars(select(ConferenciaCheckout).order_by(ConferenciaCheckout.id)))


def test_conferencia_antes_do_monitor_antes_da_descoberta(engine, sessoes, config):
    url_livre = livre(sessoes, "livre")
    _, candidata = confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    confirmado(sessoes, "venc", "B0VENC0001", "990.00", lido_em=MEIO_DIA - timedelta(minutes=20))
    um_item = carrinho("B0CAND0001", subtotal="R$ 700,00")
    paginas = {
        URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()],
        url_painel_ofertas("B0CAND0001"): painel("B0CAND0001", "R$ 700,00"),
        url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00"),
        url_livre: pagina_html(html_busca(), url=url_livre),
    }
    v, navegador, notificador, _ = varredura(
        engine, sessoes, config, paginas, [um_item, checkout_resumo("R$ 700,00", "R$ 0,00", None, "R$ 700,00"), carrinho()]
    )
    assert v.passo() == 0  # conferência
    assert v.passo() == 0  # monitor
    assert v.passo() == 0  # descoberta
    assert v.passo() == ESPERA_OCIOSA_S
    visitadas = navegador.visitadas
    assert visitadas.index(URL_CARRINHO) < visitadas.index(url_ofertas("B0VENC0001")) < visitadas.index(url_livre)
    [conf] = conferencias(sessoes)
    assert (conf.anuncio_id, conf.situacao, conf.total, conf.item_removido) == (candidata, SituacaoCheckout.OK, Decimal("700.00"), True)
    with sessoes() as s:
        assert s.scalar(select(Oportunidade)).preco_amazon == Decimal("700.00")
    [(destino, texto)] = notificador.mensagens
    assert destino is Destino.OPORTUNIDADES and "conferido no checkout" in texto


def test_janela_propria_do_monitor(engine, sessoes, config):
    url_livre = livre(sessoes, "livre")
    confirmado(sessoes, "venc", "B0VENC0001")  # nunca lido: vencido
    with sessoes() as s, s.begin():
        aplicar_config(s, {"janela_inicio": time(14, 0)}, MEIO_DIA)  # a busca só começa às 14h
    paginas = {url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00"), url_livre: pagina_html(html_busca(), url=url_livre)}
    v, navegador, _, _ = varredura(engine, sessoes, config, paginas)
    assert v.passo() == 0
    assert v.passo() == ESPERA_OCIOSA_S
    assert navegador.visitadas == [url_ofertas("B0VENC0001")]


def test_monitor_fora_da_janela_dele_a_descoberta_segue(engine, sessoes, config):
    url_livre = livre(sessoes, "livre")
    confirmado(sessoes, "venc", "B0VENC0001")
    with sessoes() as s, s.begin():
        aplicar_config(s, {"monitor_janela_inicio": time(14, 0)}, MEIO_DIA)
    paginas = {url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00"), url_livre: pagina_html(html_busca(), url=url_livre)}
    v, navegador, _, _ = varredura(engine, sessoes, config, paginas)
    v.passo()
    assert navegador.visitadas == [url_livre]


def test_monitor_desligado_nao_le(engine, sessoes, config):
    confirmado(sessoes, "venc", "B0VENC0001")
    with sessoes() as s, s.begin():
        aplicar_config(s, {"monitor_ligado": False}, MEIO_DIA)
    v, navegador, _, _ = varredura(engine, sessoes, config, {})
    assert v.passo() == ESPERA_OCIOSA_S and navegador.visitadas == []


def test_conferencia_desligada_nao_confere(engine, sessoes, config):
    confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    with sessoes() as s, s.begin():
        aplicar_config(s, {"checkout_ligado": False}, MEIO_DIA)
    v, navegador, _, _ = varredura(engine, sessoes, config, {})
    assert v.passo() == ESPERA_OCIOSA_S and navegador.visitadas == []


def test_monitor_e_conferencia_somam_no_mesmo_teto_e_a_descoberta_segue(engine, sessoes, config):
    url_livre = livre(sessoes, "livre")
    confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    confirmado(sessoes, "venc", "B0VENC0001", "990.00", lido_em=MEIO_DIA - timedelta(minutes=20))
    with sessoes() as s, s.begin():
        aplicar_config(s, {"monitor_max_paginas_hora": 5}, MEIO_DIA)
    um_item = carrinho("B0CAND0001", subtotal="R$ 700,00")
    paginas = {
        URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()],
        url_painel_ofertas("B0CAND0001"): painel("B0CAND0001", "R$ 700,00"),
        url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00"),
        url_livre: pagina_html(html_busca(), url=url_livre),
    }
    v, navegador, _, relogio = varredura(
        engine, sessoes, config, paginas, [um_item, checkout_resumo("R$ 700,00", "R$ 0,00", None, "R$ 700,00"), carrinho()]
    )
    v.passo()  # a conferência abre 8 páginas: estoura o teto de 5
    v.passo()  # o monitor espera; a descoberta tem o próprio teto
    assert url_livre in navegador.visitadas and url_ofertas("B0VENC0001") not in navegador.visitadas
    relogio.agora += timedelta(minutes=61)
    v.passo()
    assert navegador.visitadas[-1] == url_ofertas("B0VENC0001")


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


def test_sem_login_desliga_a_conferencia_avisa_uma_vez_e_o_monitor_continua(engine, sessoes, config):
    confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    confirmado(sessoes, "venc", "B0VENC0001", "990.00", lido_em=MEIO_DIA - timedelta(minutes=20))
    um_item = carrinho("B0CAND0001", subtotal="R$ 700,00")
    paginas = {
        URL_CARRINHO: [carrinho(), um_item, um_item, carrinho()],
        url_painel_ofertas("B0CAND0001"): painel("B0CAND0001", "R$ 700,00"),
        url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00"),
    }
    v, navegador, notificador, _ = varredura(engine, sessoes, config, paginas, [um_item, login(), carrinho()])
    v.passo()
    [conf] = conferencias(sessoes)
    assert (conf.situacao, conf.item_removido) == (SituacaoCheckout.SEM_LOGIN, True)
    with sessoes() as s:
        assert repo_amz.obter_config(s).checkout_sem_login_em == MEIO_DIA
    v.passo()
    assert navegador.visitadas[-1] == url_ofertas("B0VENC0001")  # o monitor segue
    v.passo()
    avisos = [t for d, t in notificador.mensagens if d is Destino.ADMIN]
    assert len(avisos) == 1 and "6081" in avisos[0] and "Retomar conferência" in avisos[0]
    assert len(conferencias(sessoes)) == 1


def test_item_que_ficou_no_carrinho_e_retirado_na_proxima_volta(engine, sessoes, config):
    _, anuncio_id = confirmado(sessoes, "cand", "B0CAND0001")
    with sessoes() as s, s.begin():
        presa = repo_amz.registrar_conferencia(
            s, em=MEIO_DIA - timedelta(minutes=5), anuncio_id=anuncio_id, vendedor_nome="Amazon.com.br",
            preco_anunciado=Decimal("700.00"), itens=None, frete=None, impostos=None, total=None,
            situacao=SituacaoCheckout.FALHA, motivo="x", item_removido=False,
        ).id
    um_item = carrinho("B0CAND0001")
    v, navegador, _, _ = varredura(
        engine, sessoes, config,
        {URL_CARRINHO: [um_item, carrinho()], url_ofertas("B0CAND0001"): ofertas("B0CAND0001", "R$ 990,00")},
        [carrinho()],
    )
    v.passo()
    assert navegador.cliques[-1][0].endswith('[data-asin="B0CAND0001"] input[data-action="delete"]')
    with sessoes() as s:
        assert s.get(ConferenciaCheckout, presa).item_removido is True
    v.passo()
    assert navegador.visitadas[-1] == url_ofertas("B0CAND0001")


def test_carrinho_ocupado_espera_uma_hora(engine, sessoes, config):
    confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    ocupado = carrinho("B0DOUSUARIO")
    v, navegador, _, relogio = varredura(engine, sessoes, config, {URL_CARRINHO: [ocupado, ocupado]})
    v.passo()
    assert conferencias(sessoes)[0].situacao is SituacaoCheckout.CARRINHO_OCUPADO and navegador.cliques == []
    assert v.passo() == ESPERA_OCIOSA_S and navegador.visitadas == [URL_CARRINHO]
    relogio.agora += timedelta(minutes=61)
    with sessoes() as s, s.begin():  # a leitura do monitor também venceu: deixa só a conferência pendente
        repo_amz.registrar_preco(s, conferencias(sessoes)[0].anuncio_id, Decimal("700.00"), OrigemPreco.OFERTAS, None, Envio.AMAZON, relogio.agora, SP)
    v.passo()
    assert navegador.visitadas == [URL_CARRINHO, URL_CARRINHO]


def test_monitor_que_falha_nao_trava_no_mesmo_anuncio(engine, sessoes, config):
    confirmado(sessoes, "a", "B0AAAA0001")
    confirmado(sessoes, "b", "B0BBBB0001")
    paginas = {
        url_ofertas("B0AAAA0001"): pagina_html("<html><body>layout novo</body></html>", url=url_ofertas("B0AAAA0001")),
        url_ofertas("B0BBBB0001"): ofertas("B0BBBB0001", "R$ 990,00"),
    }
    v, navegador, _, _ = varredura(engine, sessoes, config, paginas)
    v.passo()
    v.passo()
    assert navegador.visitadas == [url_ofertas("B0AAAA0001"), url_ofertas("B0BBBB0001")]
    assert v.passo() == ESPERA_OCIOSA_S


def test_captcha_no_monitor_pausa_a_amazon(engine, sessoes, config):
    confirmado(sessoes, "a", "B0AAAA0001")
    v, _, notificador, _ = varredura(engine, sessoes, config, {url_ofertas("B0AAAA0001"): pagina_html(CAPTCHA, url=url_ofertas("B0AAAA0001"))})
    assert v.passo() == ESPERA_OCIOSA_S
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.PAUSADO_DESAFIO
    assert any(d is Destino.ADMIN and "CAPTCHA" in t for d, t in notificador.mensagens)


def test_leituras_com_mais_de_30_dias_sao_apagadas(engine, sessoes, config):
    _, anuncio_id = confirmado(sessoes, "a", "B0AAAA0001", "990.00", lido_em=MEIO_DIA - timedelta(days=31))
    v, _, _, _ = varredura(engine, sessoes, config, {url_ofertas("B0AAAA0001"): ofertas("B0AAAA0001", "R$ 990,00")})
    v.passo()
    with sessoes() as s:
        assert {o.lida_em for o in s.scalars(select(OfertaAmazon))} == {MEIO_DIA}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t14 uv run pytest tests/coletor_amazon/test_varredura_monitor.py -q`
Expected: FAIL (a varredura só faz a descoberta).

- [ ] **Step 3: Implementação**

Substitua `src/tcg_sniper/coletor_amazon/varredura.py` por:

```python
"""Coletor da Amazon: um navegador, três trabalhos. Por prioridade, a cada passo: tirar do carrinho um
item que ficou de uma conferência, conferir no checkout uma candidata, ler as ofertas do anúncio
confirmado mais atrasado (monitor) e, por último, a descoberta (fila de buscas). Os três primeiros só
dentro da janela do monitor e com o teto `monitor_max_paginas_hora` (somado); a descoberta dentro da
janela da busca, com o teto `max_buscas_hora`."""

import logging
import random
import time as relogio_sistema
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.coletor_amazon import checkout, monitor
from tcg_sniper.coletor_amazon.busca import (
    ContextoBusca,
    CotaHtmlFalha,
    DesafioAmazon,
    abrir_pagina,
    processar_produto,
)
from tcg_sniper.coletor_amazon.cliques import CliqueProibido, SeletorAusente, remover_do_carrinho
from tcg_sniper.coletor_amazon.config import aplicar_config
from tcg_sniper.coletor_amazon.fila import Janela, TetoPorHora, intervalo_busca, janela_do_dia
from tcg_sniper.coletor_amazon.termo import termo_busca
from tcg_sniper.coletor_liga.agendador import lock_coleta
from tcg_sniper.config import Config
from tcg_sniper.config_banco import carregar_config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    ConfigAmazon,
    EstadoColetorTipo,
    ProdutoLiga,
    SituacaoCheckout,
    StatusColeta,
    TipoColeta,
)
from tcg_sniper.navegador.base import NavegadorInterativo
from tcg_sniper.navegador.modelos import ErroRede
from tcg_sniper.navegador.ritmo import pausa_aleatoria
from tcg_sniper.notificador.base import Destino, Notificador
from tcg_sniper.parsing import ErroParser

log = logging.getLogger(__name__)

ID_LOCK_AMAZON = 7_202_611
TIPOS_AMAZON = (TipoColeta.AMAZON,)
ESPERA_OCIOSA_S = 60
ESPERA_ERRO_S = 15 * 60
MAX_ERROS_SEGUIDOS = 3
MAX_FALHAS_SEGUIDAS = 10  # páginas seguidas com ErroParser/ErroRede (bloqueio ou layout novo)
ESPERA_CARRINHO_OCUPADO = timedelta(hours=1)  # carrinho com item do usuário: não confere por 1 h
ESPERA_RETIRADA = timedelta(minutes=15)  # item nosso que não saiu do carrinho: nova tentativa
ERROS_DE_PAGINA = (ErroParser, ErroRede, CliqueProibido, SeletorAusente)


def mensagem_captcha(config: Config, url: str) -> str:
    return (
        f"CAPTCHA na Amazon ({url}). Resolver em http://{config.host_publico}:6081/vnc.html "
        f"e depois clicar em Retomar (Amazon) em http://{config.host_publico}:8000"
    )


def mensagem_sem_login(config: Config) -> str:
    return (
        "A conta Amazon do coletor está sem login: a conferência de checkout parou (o monitor de preço continua). "
        f"Logue a conta Amazon no noVNC, porta 6081: http://{config.host_publico}:6081/vnc.html, e depois clique em "
        f"Retomar conferência em http://{config.host_publico}:8000/servicos"
    )


class VarreduraAmazon:
    def __init__(
        self,
        engine: Engine,
        sessoes: sessionmaker[Session],
        fabrica_navegador: Callable[[], AbstractContextManager[NavegadorInterativo]],
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
        self._config_env = config
        self._config = config
        self._relogio = relogio or (lambda: datetime.now(UTC))
        self._rng = rng or random.Random()
        self._dormir = dormir
        self._janelas: dict[tuple[str, date, time, time, str], Janela] = {}
        self._teto = TetoPorHora()  # buscas da descoberta
        self._teto_monitor = TetoPorHora()  # páginas do monitor, da conferência e da retirada, somadas
        self._ciclo: int | None = None
        self._pendentes: set[int] = set()
        self._ok = 0
        self._falha = 0
        self._erros_seguidos = 0
        self._falhas_seguidas = 0
        self._cota_falhas = CotaHtmlFalha()
        self._cota_falhas_monitor = CotaHtmlFalha()
        self._espera_monitor: dict[int, datetime] = {}  # anúncio que falhou -> não reler antes de
        self._retirada_em: datetime | None = None  # próxima tentativa de tirar item preso do carrinho
        self._avisados_carrinho: set[int] = set()  # conferências cujo item preso já foi avisado
        self._limpeza_em: date | None = None
        self._contexto_navegador: AbstractContextManager[NavegadorInterativo] | None = None
        self._navegador: NavegadorInterativo | None = None

    # --- navegador ---------------------------------------------------------------------------

    def _obter_navegador(self) -> NavegadorInterativo:
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

    def _contexto(self, cfg: ConfigAmazon, nome_falha: str, cota: CotaHtmlFalha) -> ContextoBusca:
        return ContextoBusca(
            sessoes=self._sessoes,
            navegador=self._obter_navegador(),
            notificador=self._notificador,
            config=self._config,
            cfg=cfg,
            relogio=self._relogio,
            dormir=self._dormir,
            rng=self._rng,
            nome_falha=nome_falha,
            cota_falhas=cota,
        )

    def _pausar(self, cfg: ConfigAmazon) -> Callable[[], None]:
        return lambda: pausa_aleatoria(cfg.pausa_min_s, cfg.pausa_max_s, self._dormir, self._rng)

    def _registrar_paginas(self, quantidade: int) -> None:
        agora = self._relogio()
        for _ in range(quantidade):
            self._teto_monitor.registrar(agora)

    # --- ciclo da descoberta -------------------------------------------------------------------

    def _iniciar_ciclo(self, agora: datetime, na_fila: set[int]) -> None:
        with self._sessoes() as s, s.begin():
            self._ciclo = repo.iniciar_coleta(s, TipoColeta.AMAZON, agora).id
        self._pendentes = set(na_fila)
        self._ok = self._falha = 0
        self._cota_falhas = CotaHtmlFalha()

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
        self._config = carregar_config(self._sessoes, self._config_env)
        with self._sessoes() as s, s.begin():
            interrompidos = repo.marcar_interrompidas(s, self._relogio(), TIPOS_AMAZON)
        if interrompidos:
            log.warning("%d ciclo(s) da Amazon interrompido(s) marcados como falha", interrompidos)
            self._notificador.enviar(
                Destino.ADMIN,
                f"{interrompidos} ciclo(s) da Amazon interrompido(s) (o coletor reiniciou) e marcado(s) como "
                "falha. A fila continua sozinha.",
            )

    def _janela(self, agora: datetime, tipo: str, inicio: time, fim: time) -> Janela:
        dia = agora.astimezone(self._config.zona).date()
        chave = (tipo, dia, inicio, fim, self._config.fuso)
        if chave not in self._janelas:
            self._janelas[chave] = janela_do_dia(dia, inicio, fim, self._config.zona, self._rng)
        return self._janelas[chave]

    def passo(self) -> float:
        """Faz no máximo um trabalho. Devolve quantos segundos dormir antes do próximo passo."""
        self._config = carregar_config(self._sessoes, self._config_env)
        agora = self._relogio()
        with self._sessoes() as s, s.begin():
            cfg = repo_amz.obter_config(s)
            estado = repo.obter_estado(s, agora, COLETOR_AMAZON).estado
        descoberta_aberta = self._janela(agora, "busca", cfg.janela_inicio, cfg.janela_fim).contem(agora)
        monitor_aberto = self._janela(agora, "monitor", cfg.monitor_janela_inicio, cfg.monitor_janela_fim).contem(agora)
        if not descoberta_aberta:
            self._encerrar_ciclo(cfg)
        if not (descoberta_aberta or monitor_aberto):
            self.fechar_navegador()
            return ESPERA_OCIOSA_S
        if estado is not EstadoColetorTipo.ATIVO:
            return ESPERA_OCIOSA_S
        self._limpar_uma_vez_por_dia(agora)
        if monitor_aberto and self._teto_monitor.liberado_em(agora, cfg.monitor_max_paginas_hora) is None:
            try:
                espera = self._passo_monitor(agora, cfg)
            except DesafioAmazon as desafio:
                self._registrar_desafio(desafio.url)
                return ESPERA_OCIOSA_S
            if espera is not None:
                return espera
        if descoberta_aberta:
            return self._passo_descoberta(agora, cfg)
        return ESPERA_OCIOSA_S

    def _limpar_uma_vez_por_dia(self, agora: datetime) -> None:
        dia = agora.astimezone(self._config.zona).date()
        if self._limpeza_em == dia:
            return
        with self._sessoes() as s, s.begin():
            apagadas = repo_amz.limpar_ofertas_antigas(s, agora)
        if apagadas:
            log.info("%d ofertas lidas há mais de 30 dias apagadas", apagadas)
        self._limpeza_em = dia
        self._cota_falhas_monitor = CotaHtmlFalha()

    # --- monitor, conferência e retirada ---------------------------------------------------------

    def _carrinho_ocupado_ha_pouco(self, s: Session, agora: datetime) -> bool:
        ultima = repo_amz.ultima_conferencia(s)
        return (
            ultima is not None
            and ultima.situacao is SituacaoCheckout.CARRINHO_OCUPADO
            and agora - ultima.em < ESPERA_CARRINHO_OCUPADO
        )

    def _passo_monitor(self, agora: datetime, cfg: ConfigAmazon) -> float | None:
        """Um trabalho do monitor, por prioridade. None: nada a fazer agora (a descoberta pode ir)."""
        self._espera_monitor = {k: v for k, v in self._espera_monitor.items() if v > agora}
        with self._sessoes() as s, s.begin():
            esquecidos = []
            if self._retirada_em is None or agora >= self._retirada_em:
                esquecidos = repo_amz.conferencias_com_item_no_carrinho(s)
            candidatas = []
            if cfg.checkout_ligado and cfg.checkout_sem_login_em is None and not self._carrinho_ocupado_ha_pouco(s, agora):
                candidatas = repo_amz.candidatas_ao_checkout(s, agora, cfg)
            proximo = None
            if cfg.monitor_ligado:
                proximo = repo_amz.proximo_do_monitor(s, agora, cfg.monitor_intervalo_min, set(self._espera_monitor))
        if esquecidos:
            return self._retirar(*esquecidos[0], cfg)
        if candidatas:
            return self._conferir(candidatas[0], cfg)
        if proximo is not None:
            return self._monitorar(*proximo, cfg)
        return None

    def _retirar(self, conferencia_id: int, asin: str, cfg: ConfigAmazon) -> float:
        ctx = self._contexto(cfg, f"amazon-carrinho-{asin}", self._cota_falhas_monitor)
        try:
            removido, paginas = remover_do_carrinho(ctx.navegador, asin, lambda url: abrir_pagina(ctx, url), self._pausar(cfg))
        except ERROS_DE_PAGINA as erro:
            log.warning("não deu para tirar %s do carrinho: %s", asin, erro)
            removido, paginas = False, 1
        self._registrar_paginas(paginas)
        if removido:
            self._retirada_em = None
            with self._sessoes() as s, s.begin():
                repo_amz.marcar_item_removido(s, conferencia_id)
            return 0
        self._retirada_em = self._relogio() + ESPERA_RETIRADA
        if conferencia_id not in self._avisados_carrinho:
            self._avisados_carrinho.add(conferencia_id)
            self._notificador.enviar(
                Destino.ADMIN,
                f"O item {asin} de uma conferência de checkout pode ter ficado no carrinho da Amazon; o coletor tenta "
                f"tirar a cada {int(ESPERA_RETIRADA.total_seconds() // 60)} min. Para tirar à mão: "
                f"http://{self._config.host_publico}:6081/vnc.html",
            )
        return 0

    def _conferir(self, candidata: repo_amz.CandidataCheckout, cfg: ConfigAmazon) -> float:
        ctx = self._contexto(cfg, f"amazon-checkout-{candidata.asin}", self._cota_falhas_monitor)
        alvo = checkout.AlvoCheckout(candidata.asin, candidata.vendedor_nome, candidata.preco_anunciado)
        resultado = checkout.conferir(ctx.navegador, alvo, lambda url: abrir_pagina(ctx, url), self._pausar(cfg))
        self._registrar_paginas(resultado.paginas)
        agora = self._relogio()
        avisar_sem_login = False
        with self._sessoes() as s, s.begin():
            conferencia_id = repo_amz.registrar_conferencia(
                s, em=agora, anuncio_id=candidata.anuncio_id, vendedor_nome=candidata.vendedor_nome,
                preco_anunciado=candidata.preco_anunciado, itens=resultado.itens, frete=resultado.frete,
                impostos=resultado.impostos, total=resultado.total, situacao=resultado.situacao,
                motivo=resultado.motivo, item_removido=resultado.item_removido,
            ).id
            if resultado.situacao is SituacaoCheckout.SEM_LOGIN and repo_amz.obter_config(s).checkout_sem_login_em is None:
                aplicar_config(s, {"checkout_sem_login_em": agora}, agora)
                avisar_sem_login = True
        log.info("conferência de checkout de %s: %s (%s)", candidata.asin, resultado.situacao.value, resultado.motivo or "ok")
        if avisar_sem_login:
            self._notificador.enviar(Destino.ADMIN, mensagem_sem_login(self._config))
        if resultado.situacao is SituacaoCheckout.OK:
            monitor.aplicar_conferencia(ctx, candidata.anuncio_id, conferencia_id)
        if resultado.desafio_url is not None:
            self._registrar_desafio(resultado.desafio_url)
            return ESPERA_OCIOSA_S
        return 0

    def _monitorar(self, anuncio_id: int, asin: str, cfg: ConfigAmazon) -> float:
        ctx = self._contexto(cfg, f"amazon-monitor-{asin}", self._cota_falhas_monitor)
        try:
            resultado = monitor.ler_anuncio(ctx, anuncio_id, asin)
        except ERROS_DE_PAGINA as erro:
            self._registrar_paginas(1)
            self._espera_monitor[anuncio_id] = self._relogio() + timedelta(minutes=cfg.monitor_intervalo_min)
            self._falhas_seguidas += 1
            log.warning("leitura das ofertas de %s falhou: %s", asin, erro)
            if self._falhas_seguidas >= MAX_FALHAS_SEGUIDAS:
                return self._pausar_por_falhas(cfg)
            return 0
        except DesafioAmazon:
            raise
        except Exception:
            # Um anúncio que quebra não pode prender o monitor nele: espera um intervalo e o erro sobe.
            self._espera_monitor[anuncio_id] = self._relogio() + timedelta(minutes=cfg.monitor_intervalo_min)
            raise
        self._registrar_paginas(resultado.paginas)
        self._falhas_seguidas = 0
        self._erros_seguidos = 0
        return 0

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
            # Português na primeira busca, depois alterna; sem nome em inglês é sempre português.
            # O inglês só vale se o termo existir e for diferente do português.
            usar_en = bool(
                item
                and produto
                and produto.nome_en
                and termo_busca(produto.nome_en) not in ("", termo_busca(produto.nome))
                and item.ultima_busca_em is not None
                and not item.ultimo_termo_en
            )
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
            teve_candidato = processar_produto(contexto, produto, usar_en).candidatos > 0
            self._ok += 1
            self._falhas_seguidas = 0
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
                        s, produto.id, depois, depois + timedelta(minutes=cfg.intervalo_busca_min), False, usar_en
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
            repo_amz.reagendar(s, produto.id, depois, proxima, teve_candidato, usar_en)
            repo_amz.fechar_oportunidades_sem_leitura(s, depois)
        self._pendentes.discard(produto.id)
        if not self._pendentes:
            self._encerrar_ciclo(cfg)
        if self._falhas_seguidas >= MAX_FALHAS_SEGUIDAS:
            return self._pausar_por_falhas(cfg)
        return 0

    def _pausar_por_falhas(self, cfg: ConfigAmazon) -> float:
        """Bloqueio sem CAPTCHA ou layout novo: toda página falha. Pausa em vez de seguir no ritmo normal."""
        self._falhas_seguidas = 0
        pasta = self._config.dir_dados / "falhas"
        try:
            with self._sessoes() as s, s.begin():
                repo.pausar(s, "falhas seguidas", self._relogio(), COLETOR_AMAZON)
        except Exception:
            log.exception("não foi possível registrar a pausa da busca na Amazon")
            self._notificador.enviar(
                Destino.ADMIN,
                f"{MAX_FALHAS_SEGUIDAS} páginas seguidas da Amazon falharam (bloqueio ou mudança de layout?); "
                f"não foi possível registrar a pausa no banco. HTMLs em {pasta}.",
            )
            return ESPERA_ERRO_S
        log.warning("%d páginas seguidas da Amazon falharam; varredura pausada", MAX_FALHAS_SEGUIDAS)
        self._encerrar_ciclo(cfg)
        self._notificador.enviar(
            Destino.ADMIN,
            f"Amazon pausada depois de {MAX_FALHAS_SEGUIDAS} páginas seguidas com falha (bloqueio ou "
            f"mudança de layout?). HTMLs em {pasta}. Veja `docker compose logs coletor-amazon` e clique em "
            f"Retomar (Amazon) em http://{self._config.host_publico}:8000",
        )
        return ESPERA_OCIOSA_S

    def tratar_erro(self, erro: Exception) -> float:
        """Erro inesperado num passo: avisa e espera; três seguidos pausam a varredura."""
        log.error("erro inesperado na varredura da Amazon", exc_info=erro)
        self.fechar_navegador()
        self._erros_seguidos += 1
        if self._erros_seguidos >= MAX_ERROS_SEGUIDOS:
            self._erros_seguidos = 0
            try:
                with self._sessoes() as s, s.begin():
                    repo.pausar(s, "erros seguidos", self._relogio(), COLETOR_AMAZON)
            except Exception:
                log.exception("não foi possível registrar a pausa da varredura da Amazon")
                self._notificador.enviar(
                    Destino.ADMIN,
                    f"Erros inesperados seguidos na varredura da Amazon (último: {erro!r}); não foi possível "
                    "registrar a pausa no banco. Nova tentativa em 15 minutos.",
                )
                return ESPERA_ERRO_S
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
                    except Exception as erro:  # noqa: BLE001 - qualquer falha inesperada vira espera/pausa
                        espera = self.tratar_erro(erro)
                    if espera > 0:
                        self._dormir(espera)
        finally:
            # SIGTERM vira SystemExit: fecha o navegador que tenha ficado aberto por um CAPTCHA.
            self.fechar_navegador()
```

A mensagem de falhas seguidas passa a falar em "páginas" (vale para monitor e busca) e mantém os trechos que `test_falhas_seguidas_pausam_a_busca` procura ("seguidas com falha", "Retomar (Amazon)").

- [ ] **Step 4: README**

Em `README.md`, depois da seção "### 9. Casamento com IA (opcional)", acrescente:

````markdown
### 10. Monitor de preço e conferência de checkout

O `coletor-amazon` tem três trabalhos num navegador só, nesta ordem de prioridade:

1. **Conferência de checkout** das candidatas (melhor oferta com desconto anunciado a até 5 pontos do mínimo): põe a oferta no carrinho, vai até o resumo do pedido, lê itens, frete, impostos de importação e total, e tira o item. **Nunca confirma pedido** e nunca usa "Comprar agora"; com qualquer item seu no carrinho ativo, não clica em nada (itens em "Salvo para depois" não contam e nunca são tocados).
2. **Monitor de preço**: lê a lista de ofertas de cada anúncio confirmado a cada 15 min (08:00–22:00) e usa a melhor oferta elegível.
3. **Descoberta**: a busca de anúncios novos, só para produtos sem anúncio confirmado (e uma vez por semana para os casados).

Tudo em Configurações → Amazon → Monitor de preço; liga e desliga em Serviços. O alerta mostra o total conferido (com impostos e frete) ou "preço anunciado, não conferido". Cupons e descontos de cartão aparecem só como informação.

A conferência precisa da conta Amazon logada no Chromium do coletor: entre em `http://<host>:6081/vnc.html` e faça login. Se a sessão cair, a conferência para (o monitor continua), o grupo admin recebe um aviso e, depois de logar de novo, clique em **Retomar conferência** em Serviços.

Para capturar páginas reais para os testes (só quando o layout da Amazon mudar):

```
docker compose stop coletor-amazon
docker compose run --rm --service-ports coletor-amazon tcg-sniper amazon capturar --asin <ASIN> --checkout --login
docker compose start coletor-amazon
```

As páginas ficam em `dados/capturas/` (fora do git) e só entram em `tests/fixtures/amazon` depois de `scripts/anonimizar_fixture.py`.
````

Na lista de serviços do compose, onde o README a tiver, a descrição do `coletor-amazon` passa a ser "monitor de preço, conferência de checkout e busca na Amazon".

- [ ] **Step 5: Rodar**

Run: `DATABASE_URL_TESTE=postgresql+psycopg://tcg:tcg@127.0.0.1:5432/tcg_test_t14 uv run pytest -q && uv run ruff check .`
Expected: PASS (inclusive `test_varredura.py` inteiro, `test_migracao_igual_aos_modelos` e `test_css_em_dia_com_os_templates`).

- [ ] **Step 6: Commit**

```bash
git add src/tcg_sniper/coletor_amazon/varredura.py tests/coletor_amazon/test_varredura_monitor.py tests/coletor_amazon/test_varredura.py README.md
git commit -m "feat: Amazon collector runs checkout checks, then the price monitor, then discovery, each with its own window and hourly cap"
```

---

## Implantação (depois do merge, com ok do usuário)

1. Backup: `docker compose exec -T postgres pg_dump -U tcg -Fc tcg > dados/backups/tcg-antes-monitor-<data>.dump`.
2. `docker compose up -d --build migrate admin coletor-amazon casador`. O `notificador` não muda (só envia o texto que os coletores gravam).
3. Conferir: `alembic_version = b9e4c2a7d3f5`; em Configurações → Amazon a seção "Monitor de preço" com os padrões (15 min, 08:00–22:00, 150 páginas/h, margem 5, validade 6 h, 7 dias); Serviços com os dois interruptores ligados; em `select origem_casamento, count(*) from anuncio_amazon group by 1` nenhum confirmado/ignorado com origem nula.
4. O usuário confere o login da conta Amazon no noVNC (porta 6081). Sem login a conferência vai para `sem_login` na primeira candidata, o grupo admin é avisado e o monitor segue.
5. Na primeira hora: Logs → Monitor com leituras chegando; Dashboard sem aviso de "monitor não cabe no intervalo" (se aparecer, aumente o intervalo ou o teto em Configurações); `docker compose logs coletor-amazon | grep conferência` para as primeiras conferências; Logs → Checkout sem `item no carrinho`.
6. Se uma conferência ficar com "item no carrinho", o coletor tenta tirar a cada 15 min e avisa uma vez; conferir pelo noVNC.
