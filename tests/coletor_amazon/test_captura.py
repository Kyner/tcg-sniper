import pytest
from fakes import NavegadorInterativoFake, pagina_html
from fakes_checkout import SAIR_DA_CONTA

from tcg_sniper.coletor_amazon.captura import URL_TESTE_LOGIN, Captura, capturar, capturar_login, carrinho_vazio
from tcg_sniper.coletor_amazon.parsers import URL_CARRINHO, url_ofertas, url_painel_ofertas
from tcg_sniper.navegador.modelos import ErroRede

ASIN = "B0DNV55QBS"
FECHAR = '<input name="proceedToRetailCheckout" value="Fechar pedido" type="submit">'


def carrinho(*ativos, com_botao=True):
    itens = "".join(
        f'<div data-asin="{a}"><input data-action="delete" value="Excluir" type="submit"></div>' for a in ativos
    )
    botao = FECHAR if ativos and com_botao else ""
    return pagina_html(
        f'<html><body>{SAIR_DA_CONTA}<span id="nav-cart-count">{len(ativos)}</span>'
        f'<div data-name="Active Items">{itens}</div>{botao}</body></html>',
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


def test_contador_zero_sem_o_bloco_do_carrinho_ativo_nao_e_carrinho_vazio():
    # login ou CAPTCHA no lugar do carrinho também mostram o contador: não provam carrinho vazio
    assert not carrinho_vazio(pagina_html('<html><body><span id="nav-cart-count">0</span><form name="signIn"></form></body></html>'))


def test_captura_completa_salva_tudo_clica_so_o_permitido_e_tira_o_item(tmp_path, capsys):
    nav = NavegadorInterativoFake(
        {
            URL_CARRINHO: [carrinho(), carrinho(), carrinho(ASIN), carrinho(ASIN), carrinho(), carrinho()],
            url_ofertas(ASIN): OFERTAS,
            url_painel_ofertas(ASIN): [PAINEL, PAINEL],
        },
        apos_clique=[APOS, ENDERECO, RESUMO, carrinho()],
    )
    cap = capturar(nav, [ASIN], tmp_path, checkout=True, pausar=lambda: None)
    assert cap.avisos == []
    assert "removendo o item adicionado..." in capsys.readouterr().out
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
            URL_CARRINHO: [carrinho(), carrinho(), carrinho(ASIN, com_botao=False), carrinho(ASIN), carrinho(), carrinho()],
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


CAPTCHA = pagina_html(
    '<html><body><form action="/errors/validatecaptcha">Digite os caracteres que você vê</form></body></html>',
    url=URL_CARRINHO,
)
LOGIN = pagina_html(
    '<html><body><form name="signIn"><input type="email" name="email"></form></body></html>',
    url="https://www.amazon.com.br/ap/signin",
)
FICOU = "pode ter ficado no carrinho"


def ate_o_resumo(carrinhos_da_retirada, apos_excluir=None):
    """Checkout até o resumo; depois a retirada vê `carrinhos_da_retirada` (uma por abertura do
    carrinho) e o clique de excluir, se houver, leva a `apos_excluir`."""
    apos = [APOS, ENDERECO, RESUMO] + ([apos_excluir] if apos_excluir is not None else [])
    return NavegadorInterativoFake(
        {
            URL_CARRINHO: [carrinho(), carrinho(), carrinho(ASIN), *carrinhos_da_retirada],
            url_ofertas(ASIN): OFERTAS,
            url_painel_ofertas(ASIN): [PAINEL, PAINEL],
        },
        apos_clique=apos,
    )


def test_retirada_que_cai_no_captcha_avisa_que_o_item_pode_ter_ficado(tmp_path):
    nav = ate_o_resumo([CAPTCHA, CAPTCHA])
    cap = capturar(nav, [ASIN], tmp_path, checkout=True, pausar=lambda: None)
    assert any(FICOU in aviso for aviso in cap.avisos)
    assert not any("data-action" in seletor for seletor, _ in nav.cliques)  # nada a excluir no CAPTCHA


def test_retirada_que_cai_no_login_avisa_que_o_item_pode_ter_ficado(tmp_path):
    nav = ate_o_resumo([carrinho(ASIN), LOGIN, LOGIN], apos_excluir=LOGIN)
    cap = capturar(nav, [ASIN], tmp_path, checkout=True, pausar=lambda: None)
    assert any(FICOU in aviso for aviso in cap.avisos)
    assert nomes(cap)[-1] == "carrinho_vazio.html"


def test_item_que_continua_no_carrinho_depois_de_excluir_gera_aviso(tmp_path):
    nav = ate_o_resumo([carrinho(ASIN), carrinho(ASIN), carrinho(ASIN)], apos_excluir=carrinho(ASIN))
    cap = capturar(nav, [ASIN], tmp_path, checkout=True, pausar=lambda: None)
    assert any(FICOU in aviso for aviso in cap.avisos)


def test_erro_no_clique_de_excluir_vira_aviso_e_capturar_retorna(tmp_path):
    nav = ate_o_resumo([carrinho(ASIN)], apos_excluir=ErroRede("a página não respondeu"))
    cap = capturar(nav, [ASIN], tmp_path, checkout=True, pausar=lambda: None)
    aviso = next(aviso for aviso in cap.avisos if FICOU in aviso)
    assert "a página não respondeu" in aviso
    assert nomes(cap)[-1] == "carrinho_vazio.html"


def test_botao_proibido_no_lugar_de_entregar_nao_e_clicado_e_o_item_sai(tmp_path):
    proibido = pagina_html(
        '<html><body><input data-testid="Address_selectShipToThisAddress" type="submit" value="Confirmar pedido">'
        "</body></html>",
        url="https://www.amazon.com.br/checkout/p/p-1/address",
    )
    nav = NavegadorInterativoFake(
        {
            URL_CARRINHO: [carrinho(), carrinho(), carrinho(ASIN), carrinho(ASIN), carrinho(), carrinho()],
            url_ofertas(ASIN): OFERTAS,
            url_painel_ofertas(ASIN): [PAINEL, PAINEL],
        },
        apos_clique=[APOS, proibido, carrinho()],
    )
    cap = capturar(nav, [ASIN], tmp_path, checkout=True, pausar=lambda: None)
    seletores = [seletor for seletor, _ in nav.cliques]
    assert not any("Address_selectShipToThisAddress" in seletor for seletor in seletores)
    assert seletores[-1].endswith('input[data-action="delete"]')
    assert any("captura do checkout parou" in aviso for aviso in cap.avisos)
    assert not any(FICOU in aviso for aviso in cap.avisos)
    assert "parou_aqui.html" in nomes(cap) and "checkout_resumo.html" not in nomes(cap)


def test_erro_de_rede_no_meio_salva_onde_parou_e_tira_o_item(tmp_path):
    nav = NavegadorInterativoFake(
        {
            URL_CARRINHO: [carrinho(), carrinho(), carrinho(ASIN), carrinho(ASIN), carrinho(), carrinho()],
            url_ofertas(ASIN): OFERTAS,
            url_painel_ofertas(ASIN): [PAINEL, PAINEL],
        },
        apos_clique=[APOS, ErroRede("timeout no fechar pedido"), carrinho()],
    )
    cap = capturar(nav, [ASIN], tmp_path, checkout=True, pausar=lambda: None)
    assert any("timeout no fechar pedido" in aviso for aviso in cap.avisos)
    assert not any(FICOU in aviso for aviso in cap.avisos)
    assert "parou_aqui.html" in nomes(cap) and nomes(cap)[-1] == "carrinho_vazio.html"
    assert [seletor for seletor, _ in nav.cliques][-1].endswith('input[data-action="delete"]')


def test_carrinho_que_ganhou_item_antes_de_adicionar_nao_clica_em_nada(tmp_path):
    nav = NavegadorInterativoFake(
        {URL_CARRINHO: [carrinho(), carrinho("B0OUTRO001")], url_ofertas(ASIN): OFERTAS, url_painel_ofertas(ASIN): PAINEL}
    )
    cap = capturar(nav, [ASIN], tmp_path, checkout=True, pausar=lambda: None)
    assert nav.cliques == []
    assert any("antes de adicionar" in aviso for aviso in cap.avisos)


def test_erro_inesperado_sobe_registrado_e_o_item_sai_mesmo_assim(tmp_path):
    nav = NavegadorInterativoFake(
        {
            URL_CARRINHO: [carrinho(), carrinho(), carrinho(ASIN), carrinho(), carrinho()],
            url_ofertas(ASIN): OFERTAS,
            url_painel_ofertas(ASIN): [PAINEL, PAINEL],
        },
        apos_clique=[RuntimeError("quebrou"), carrinho()],
    )
    cap = Captura(tmp_path)
    with pytest.raises(RuntimeError, match="quebrou"):
        capturar(nav, [ASIN], tmp_path, checkout=True, pausar=lambda: None, cap=cap)
    assert any("quebrou" in aviso for aviso in cap.avisos)
    assert [seletor for seletor, _ in nav.cliques][-1].endswith('input[data-action="delete"]')
    assert nomes(cap)[-1] == "carrinho_vazio.html"
