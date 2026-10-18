import subprocess
import sys
from html import unescape
from pathlib import Path

import pytest
from selectolax.lexbor import LexborHTMLParser

from tcg_sniper.coletor_amazon.anonimizar import BLOCOS, achados, anonimizar, itens_salvos, ler_proibidos, limpar

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
    for trecho in (
        "<script",
        "<style",
        "<img",
        "<svg",
        'content="y"',
        "comentário",
        "data-json",
        "segredo-de-sessao",
        "pipelineType",
    ):
        assert trecho not in html
    assert 'href="/gp/aag/main?seller=A2SHZ"' in html
    assert 'href="/dp/B0DNV55QBS"' in html
    assert 'name="placeYourOrder1"' in html  # o botão proibido fica: os testes provam que nunca é clicado
    assert "<title>Finalizar pedido</title>" in html
    assert "123.456.789-09" not in html  # o conteúdo do script some junto com ele


def test_anonimizar_troca_os_dados_pessoais_por_ficticios():
    html = anonimizar(limpar(PAGINA), PROIBIDOS)
    for real in (
        "Maria Souza",
        "Rua das Flores 123",
        "01310-100",
        "***.456.789-**",
        "98765-4321",
        "maria.souza@gmail.com",
        "1234",
        "702-1234567-1234567",
    ):
        assert real not in html
    for ficticio in (
        "Fulano de Tal",
        "01001-000",
        "000.000.000-00",
        "(11) 90000-0000",
        "fulano@exemplo.com",
        "cartão 0000",
        "Pagando com cartão final 0000",
        "000-0000000-0000000",
    ):
        assert ficticio in html


def test_achados_apontam_o_que_sobrou_sem_mostrar_o_valor():
    problemas = achados(limpar(PAGINA), PROIBIDOS)
    for tipo in ("CPF", "CEP", "cartão", "e-mail", "telefone", "pedido", "texto proibido"):
        assert any(p.startswith(tipo) for p in problemas), tipo
    assert not any("1234" in p or "Maria" in p or "01310" in p for p in problemas)
    assert achados(anonimizar(limpar(PAGINA), PROIBIDOS), PROIBIDOS) == []


def test_limpar_so_os_blocos_pedidos_sem_repetir_os_aninhados():
    html = limpar(
        '<html><body><div id="a"><div id="b">dentro</div></div><div id="c">fora</div></body></html>', ("#b", "#a")
    )
    assert html.count("dentro") == 1 and "fora" not in html


def test_limpar_sem_nenhum_bloco_recusa():
    with pytest.raises(ValueError, match="nenhum dos blocos"):
        limpar("<html><body><p>x</p></body></html>", ("#nada",))


def test_ler_proibidos(tmp_path):
    arquivo = tmp_path / "proibidos.txt"
    arquivo.write_text("# comentário\nMaria Souza\n\n  1234 \n", encoding="utf-8")
    assert ler_proibidos(arquivo) == ["Maria Souza", "1234"]
    assert ler_proibidos(tmp_path / "nao-existe.txt") == []


RAIZ = Path(__file__).parent.parent.parent


@pytest.mark.parametrize(
    "trecho",
    [
        "Visa terminado em <span>1234</span>",
        "Visa ••••1234",
        "Visa •••• 1234",
        "Visa ****1234",
        "Visa xxxx 1234",
        "Elo terminando em 1234",
        "Cartão de crédito Amex terminando em 1234",
        "Visa final 1234",
    ],
)
def test_final_de_cartao_em_varias_formas(trecho):
    assert any(p.startswith("cartão") for p in achados(trecho))
    saida = anonimizar(trecho)
    assert "1234" not in saida and "0000" in saida
    assert achados(saida) == []


def test_valor_final_e_precos_nao_sao_cartao():
    trecho = "<span>Valor final R$ 1.299,00</span> <b>Total final R$ 1299,00</b> final: R$ 1299,50"
    assert achados(trecho) == []
    assert anonimizar(trecho) == trecho


def test_limpar_so_mantem_valor_de_botoes():
    pagina = (
        '<html><body><input type="radio" name="r" value="instrumentId=ABC123">'
        '<input type="text" name="n" value="Rua Qualquer"><input name="s" value="semtipo">'
        '<input type="submit" name="ok" value="Continuar"><input type="button" value="Voltar">'
        '<input type="hidden" name="h" value="tok"></body></html>'
    )
    html = limpar(pagina)
    for real in ("instrumentId", "Rua Qualquer", "semtipo", "tok"):
        assert real not in html
    assert 'value="Continuar"' in html and 'value="Voltar"' in html


def test_nome_com_nbsp_ou_dividido_em_elementos():
    pagina = "<p>Maria&nbsp;Souza</p><p><b>Maria</b> <i>Souza</i> mora aqui</p><p>Rua&nbsp;das&nbsp;Flores</p>"
    proibidos = ["Maria Souza", "Rua das Flores"]
    assert len(achados(pagina, proibidos)) >= 2
    saida = anonimizar(pagina, proibidos)
    assert "Souza" not in saida and "Flores" not in saida
    assert achados(saida, proibidos) == []


def test_achados_olha_o_texto_visivel_dividido_por_tags():
    problemas = achados("<p><b>Maria</b><i>Souza</i></p><p><b>Maria</b> <i>Souza</i></p>", ["Maria Souza"])
    assert any(p.startswith("texto proibido") for p in problemas)


def test_saudacao_e_linha_de_entrega_sao_trocadas_sem_proibidos():
    pagina = (
        '<a id="nav">Olá, Joana</a><span>Olá, <b>Joana</b></span><a>Olá, faça seu login</a>'
        "<span>Enviar para Joana</span><span>Entrega para Joana Prado - São Paulo 01310-100</span>"
    )
    saida = anonimizar(pagina)
    assert "Joana" not in saida and "Prado" not in saida and "01310" not in saida
    assert "Olá, Fulano de Tal" in saida and "Enviar para Fulano de Tal" in saida
    assert "Olá, faça seu login" in saida


def test_hifens_unicode_cep_bruto_fixo_e_cpf_sem_pontuacao():
    pagina = (
        "CEP 01310\u2013100 CEP: 01310100 <b>CEP</b> 01310100 (11) 3333-4444 CPF: 12345678909 "
        "000\u2212000\u2212000 702\u20131234567\u20131234567"
    )
    problemas = achados(pagina)
    for tipo in ("CEP", "telefone", "CPF", "pedido"):
        assert any(p.startswith(tipo) for p in problemas), tipo
    saida = anonimizar(pagina)
    for real in ("01310", "3333-4444", "12345678909", "702-1234567"):
        assert real not in saida
    assert achados(saida) == []


@pytest.mark.parametrize("email", ["m****a@gmail.com", "m\u2022\u2022\u2022a@gmail.com", "j.s***@hotmail.com.br"])
def test_email_mascarado_e_trocado_por_inteiro(email):
    assert any(p.startswith("e-mail") for p in achados(f"<p>{email}</p>"))
    saida = anonimizar(f"<p>{email}</p>")
    assert saida == "<p>fulano@exemplo.com</p>"


def rodar_script(tmp_path, tipo, *extra):
    origem = tmp_path / "origem.html"
    origem.write_text("<html><body><p>Entrega para Maria Souza</p></body></html>", encoding="utf-8")
    destino = tmp_path / "destino.html"
    resultado = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "anonimizar_fixture.py"), tipo, str(origem), str(destino), *extra],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    return resultado, destino


@pytest.mark.parametrize("tipo", ["checkout", "carrinho", "login", "ofertas"])
def test_script_recusa_sem_proibidos_em_paginas_de_usuario_logado(tmp_path, tipo):
    resultado, destino = rodar_script(tmp_path, tipo)
    assert resultado.returncode != 0
    assert not destino.exists()
    resultado, destino = rodar_script(tmp_path, tipo, "--proibidos", str(tmp_path / "vazio.txt"))
    assert resultado.returncode != 0 and not destino.exists()


def test_script_grava_com_proibidos(tmp_path):
    proibidos = tmp_path / "proibidos.txt"
    proibidos.write_text("Maria\nSouza\n", encoding="utf-8")
    resultado, destino = rodar_script(tmp_path, "login", "--proibidos", str(proibidos))
    assert resultado.returncode == 0, resultado.stderr
    assert "Maria" not in destino.read_text(encoding="utf-8")


# --- correções da auditoria de privacidade das fixtures reais (valores sintéticos) ---

U1 = "123e4567-e89b-12d3-a456-426614174000"
U2 = "9b2f0c1e-7a6d-4c3b-8e5f-1a2b3c4d5e6f"
HEX64 = "ab12" * 16
B64 = "bWl4OmZha2VsaW5laXRlbTEyMzQ1Ng=="


@pytest.mark.parametrize(
    "telefone",
    ["+55 11 98765-4321", "+5511987654321", "(11) 98765-4321", "11 98765 4321", "+55 (11) 98765-4321"],
)
def test_telefone_em_varias_formas(telefone):
    pagina = f"<p>Contato {telefone} amanhã</p>"
    assert any(p.startswith("telefone") for p in achados(pagina))
    saida = anonimizar(pagina)
    assert "8765" not in saida and "4321" not in saida and "+55" not in saida
    assert "Contato (11) 90000-0000 amanhã" in saida
    assert achados(saida) == []


def test_proibido_no_meio_do_numero_leva_os_digitos_vizinhos():
    saida = anonimizar("<p>Ligue +5511987654321 amanhã</p><p>Fone (11) 98765-4321.</p>", ["1198765432", "98765-4321"])
    assert "<p>Ligue 0000 amanhã</p>" in saida
    assert "<p>Fone 0000.</p>" in saida


def test_texto_depois_de_numero_de_telefone_e_trocado():
    saida = anonimizar("<p>Número de telefone: +Fulano 321 <b>x</b></p><p>Número de telefone:<span>abc</span></p>")
    assert "321" not in saida and "abc" not in saida
    assert "<p>Número de telefone: (11) 90000-0000<b>x</b></p>" in saida
    assert "<p>Número de telefone:<span>(11) 90000-0000</span></p>" in saida


def test_bandeira_do_cartao_depois_de_pagando_com():
    saida = anonimizar('<span class="break-word">Pagando com Elo Cartão do Fulano</span>')
    assert saida == '<span class="break-word">Pagando com cartão final 0000</span>'
    assert achados(saida) == []


PAGINA_IDS = f"""<html><body>
<div id="sc-saved-{U1}" class="sc-list-item"><input type="submit" name="submit.delete-saved.{U1}" value="Excluir"
 aria-labelledby="sc-list-item-removed-msg-text-delete-{U1}"><span id="sc-list-item-removed-msg-text-delete-{U1}">x</span>
<span id="add-to-list-{U2}">lista</span><input type="submit" name="submit.add-to-list-popover.{U2}" value="Lista"></div>
<div id="{B64}"><span id="{B64}-announce">ok</span><span aria-labelledby="{B64}-announce">b</span></div>
<div id="miq://document:1.0/Ordering/amazon:1.0/Unit:1.0/703-1234567-1234567:{U2}-std" name="miq://x/703-1234567">m</div>
<div id="select-destination-on-sasp-desktop-panel-id-{HEX64}">d</div>
<div class="celwidget pd_rd_w-AbCdE content-id-12345.sym.{U1} pf_rd_p-{U2} pf_rd_r-ABCDEFGHJK1234567890">c</div>
<div id="pedido-703-1234567-1234567"><span id="parcial-703-1234567">p</span></div>
<span id="redeemedpctch1729012345678901-announce">r</span>
<span aria-labelledby="redeemedpctch1729012345678901-announce">s</span>
</body></html>"""


def test_identificadores_em_atributos_viram_ficticios_estaveis():
    bruto = limpar(PAGINA_IDS)
    assert any(p.startswith("identificador") for p in achados(bruto))
    html = anonimizar(bruto)
    for real in (U1, U2, HEX64, B64, "miq://", "703-1234567", "pf_rd_", "pd_rd_", "1729012345678901", "ABCDEFGHJK"):
        assert real not in html, real
    assert 'name="submit.delete-saved.00000000-0000-0000-0000-000000000001"' in html
    assert 'id="sc-saved-00000000-0000-0000-0000-000000000001"' in html
    assert 'name="submit.add-to-list-popover.00000000-0000-0000-0000-000000000002"' in html
    assert 'id="select-destination-on-sasp-desktop-panel-id-' in html and 'class="celwidget ' in html
    arvore = LexborHTMLParser(html)
    referencias = [no.attributes["aria-labelledby"] for no in arvore.css("[aria-labelledby]")]
    assert len(referencias) == 3
    for alvo in referencias:  # o mesmo valor vira o mesmo fictício: quem aponta continua achando o alvo
        assert arvore.css_first(f'[id="{alvo}"]') is not None, alvo
    assert achados(html) == []


PAGINA_SELETORES = """<html><body>
<span id="nav-cart-count">1</span>
<div id="aod-pinned-offer"><div id="aod-offer-heading">Novo</div><div id="aod-offer-soldBy">v</div>
<div id="aod-offer-shipsFrom">e</div><input type="submit" name="submit.addToCart" value="Adicionar"></div>
<div id="aod-offer">o</div>
<div data-name="Active Items" id="sc-active-cart"><div data-asin="B0DNV55QBS" data-itemtype="active">
<input type="submit" name="submit.delete-active.123e4567-e89b-12d3-a456-426614174000" value="Excluir"></div></div>
<div id="sc-saved-cart" data-name="Saved Cart"></div>
<input type="submit" name="proceedToRetailCheckout" value="Fechar pedido">
<table id="subtotals-marketplace-table"><tr><td>t</td></tr></table>
<span id="checkout-primary-continue-button-id"><input type="submit" data-testid="bottom-continue-button"
 aria-labelledby="checkout-primary-continue-button-id-announce">
<span id="checkout-primary-continue-button-id-announce">Usar este endereço</span></span>
<form name="signIn"><input type="email" id="ap_email" name="email"><input id="ap_email_login" type="text"></form>
</body></html>"""


def test_seletores_dos_parsers_e_da_trava_sobrevivem():
    html = anonimizar(limpar(PAGINA_SELETORES), ["Maria Souza"])
    arvore = LexborHTMLParser(html)
    for seletor in (
        "#nav-cart-count",
        "#aod-pinned-offer",
        "#aod-offer",
        "#aod-offer-heading",
        "#aod-offer-soldBy",
        "#aod-offer-shipsFrom",
        'input[name="submit.addToCart"]',
        '[data-name="Active Items"] [data-asin="B0DNV55QBS"]',
        "#sc-active-cart",
        '#sc-saved-cart[data-name="Saved Cart"]',
        'input[name="proceedToRetailCheckout"]',
        "#subtotals-marketplace-table",
        '#checkout-primary-continue-button-id input[data-testid="bottom-continue-button"]',
        '[aria-labelledby="checkout-primary-continue-button-id-announce"]',
        "#checkout-primary-continue-button-id-announce",
        'input[name^="submit.delete"]',
        'form[name="signIn"]',
        "#ap_email",
        "#ap_email_login",
    ):
        assert arvore.css_first(seletor) is not None, seletor
    assert 'name="submit.delete-active.00000000-0000-0000-0000-000000000001"' in html


PAGINA_CARRINHO = """<html><body>
<span id="nav-cart-count">1</span>
<div data-name="Active Items" id="sc-active-cart"><div data-asin="B0ATIVO001" data-itemtype="active">
<span class="a-truncate-full">Produto Ativo de Teste</span><a href="/dp/B0ATIVO001/ref=x">ativo</a></div></div>
<div data-name="Saved Cart" id="sc-saved-cart">
<div data-asin="B0REAL0001" data-itemtype="saved" class="sc-list-item">
<a href="/dp/B0REAL0001/ref=x" class="a-link-normal sc-product-link sc-removed-msg-title">Caneca Azul de Porcelana Grande
<span class="aok-hidden">Abre em uma nova aba</span></a> foi excluído
<span class="a-truncate-full a-offscreen">Caneca Azul de Porcelana Grande</span>
<span class="a-truncate-cut">Caneca Azul de Porc…</span>
<input type="submit" name="submit.delete-saved.x" value="Excluir" aria-label="Excluir Caneca Azul de Porcelana Grande">
<img alt="Caneca Azul de Porcelana Grande" src="x.png"></div>
<div data-asin="B0REAL0002" data-itemtype="saved" class="sc-list-item">
<h3><span class="a-truncate sc-grid-item-product-title"><span class="a-truncate-full">Livro de Receitas da Vovó</span>
<span class="a-truncate-cut">Livro de Receitas…</span></span></h3>
<span aria-label="Mover para o carrinho Livro de Receitas da Vovó">mover</span></div>
<div data-asin="B0REAL0003" data-itemtype="saved" class="sc-list-item">
<span class="a-truncate-full">Caf&amp;eacute; Torrado Especial</span>
<span aria-label="Adicionar &amp;agrave; lista Caf&amp;eacute; Torrado Especial">lista</span>
<span aria-label="Visualizar itens semelhantes Caf&amp;amp;eacute; Torrado Especial">ver</span>
<span class="sc-product-price">R$ 57,90</span><span>ou em até 10x de R$ 5,79 sem juros</span>
<span>Taxas de importação R$ 12,34</span><span>O preço caiu R$ 3,21</span>
<span class="a-badge-text">1º mais vendido</span><span>Mais de 3 mil compras no mês passado</span>
<span>Vendido por Loja Exemplo Ltda</span></div>
</div>
<div id="sc-active-cart-extra" data-name="Active Items">
<span aria-label="Mover para o carrinho Caf&amp;eacute; Torrado Especial">x</span></div>
</body></html>"""


def test_salvos_para_depois_viram_um_bloco_sintetico():
    html = anonimizar(limpar(PAGINA_CARRINHO, BLOCOS["carrinho"]), ["Maria Souza"])
    reais = ("Caneca", "Porc", "Livro", "Receitas", "Vovó", "Torrado", "Caf", "B0REAL000")
    reais += ("57,90", "5,79", "12,34", "3,21", "mais vendido", "3 mil", "Loja Exemplo", "Abre em uma nova aba")
    desescapado = html
    for _ in range(4):
        desescapado = unescape(desescapado)
    for real in reais:
        assert real not in desescapado, real
    arvore = LexborHTMLParser(html)
    secao = arvore.css_first('#sc-saved-cart[data-name="Saved Cart"]')
    assert secao is not None and arvore.css_first('[data-name="Saved Cart"] [aria-label]') is None
    salvos = secao.css('[data-itemtype="saved"]')
    assert [no.attributes["data-asin"] for no in salvos] == ["B0SALVO001", "B0SALVO002", "B0SALVO003"]
    for n, no in enumerate(salvos, start=1):
        assert no.text(separator=" ", strip=True) == f"Produto salvo {n} R$ 10,00"
    assert "Produto Ativo de Teste" in html and 'data-asin="B0ATIVO001"' in html and 'href="/dp/B0ATIVO001"' in html
    assert "Mover para o carrinho Produto salvo 3" in html  # fora da seção: o título vira o fictício
    asins, titulos = itens_salvos(PAGINA_CARRINHO)
    assert asins == {"B0REAL0001", "B0REAL0002", "B0REAL0003"}
    assert {"Caneca Azul de Porcelana Grande", "Livro de Receitas da Vovó", "Café Torrado Especial"} <= titulos
