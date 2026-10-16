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
    assert pagina2.count('href="/casamentos/produto/') == 12  # 26 sem par (Gama + 25) → 20 + 6, cada um na tabela e no cartão
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


def test_trocar_nao_oferece_produto_inativo(cliente, sessoes, cenario):
    with sessoes() as s:
        alfa = s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.asin == "B0ALFA0001"))
        alfa.titulo = "Caixa Inativa"
        s.commit()
    texto = cliente.get(f"/casamentos/{alfa.id}/trocar", params={"busca": "Inativa"}).text
    assert f"/casamentos/produto/{cenario['e'].id}" not in texto
    with sessoes() as s:
        assert all(p.ativo for p, _ in consultas_amazon.buscar_produtos(s, "Inativa"))
        anuncio = s.get(AnuncioAmazon, alfa.id)
        assert all(p.ativo for p, _ in consultas_amazon.sugestoes_para(s, anuncio))


def test_confirmar_para_produto_inativo_404_e_nao_grava(cliente, sessoes, cenario):
    with sessoes() as s:
        alfa = s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.asin == "B0ALFA0001"))
    r = cliente.post(f"/casamentos/{alfa.id}", data={"acao": "confirmar", "produto_id": str(cenario["e"].id)})
    assert r.status_code == 404
    with sessoes() as s:
        assert s.get(AnuncioAmazon, alfa.id).status_casamento is StatusCasamento.PENDENTE
        assert s.get(AnuncioAmazon, alfa.id).produto_id == cenario["a"].id


def test_busca_com_nul_nao_quebra(cliente, cenario):
    assert cliente.get("/casamentos", params={"busca": "a\x00b"}).status_code == 200
    assert cliente.get("/ofertas", params={"busca": "a\x00b"}).status_code == 200


def test_opcao_da_variacao_aparece_nas_telas(cliente, sessoes, cenario):
    d = cenario["d"]
    with sessoes() as s, s.begin():
        s.execute(update(AnuncioAmazon).where(AnuncioAmazon.asin == "B0DELTA001").values(variacao="Collector Booster Box"))
        anuncio_id = s.scalar(select(AnuncioAmazon.id).where(AnuncioAmazon.asin == "B0DELTA001"))
    assert "— Collector Booster Box" in cliente.get(f"/casamentos/produto/{d.id}").text
    assert "— Collector Booster Box" in cliente.get(f"/casamentos/{anuncio_id}/trocar").text
    assert "Collector Booster Box" in cliente.get(f"/produto/{d.id}").text
    assert "B0DELTA001 · Collector Booster Box" in cliente.get("/ofertas").text


def test_lista_de_casamentos_tem_selos(cliente, cenario):
    texto = cliente.get("/casamentos", params={"situacao": "todos"}).text
    assert 'badge-success">oportunidade</span>' in texto
    assert ">sem par</span>" in texto


def test_pagina_do_produto_abre_na_aba_de_pendentes_ou_confirmados(cliente, cenario):
    def aba_marcada(texto, rotulo):
        inicio = texto.index(f'aria-label="{rotulo}')
        return "checked" in texto[texto.rindex("<input", 0, inicio):inicio + 80]

    com_pendente = cliente.get(f"/casamentos/produto/{cenario['a'].id}").text
    assert aba_marcada(com_pendente, "Pendentes")
    so_confirmado = cliente.get(f"/casamentos/produto/{cenario['d'].id}").text
    assert aba_marcada(so_confirmado, "Confirmados") and not aba_marcada(so_confirmado, "Pendentes")


@pytest.fixture
def com_nome_en(sessoes, cenario):
    with sessoes() as s, s.begin():
        s.get(type(cenario["c"]), cenario["c"].id).nome_en = "Gamma Box English"
    return cenario


def test_nome_em_ingles_aparece_em_casamentos_cabecalho_e_trocar(cliente, sessoes, com_nome_en):
    c = com_nome_en["c"]
    marca = 'text-sm text-base-content/60">Gamma Box English'
    assert marca in cliente.get("/casamentos", params={"situacao": "todos"}).text
    assert marca in cliente.get(f"/casamentos/produto/{c.id}").text
    with sessoes() as s:
        alfa = s.scalar(select(AnuncioAmazon).where(AnuncioAmazon.asin == "B0ALFA0001"))
    assert marca in cliente.get(f"/casamentos/{alfa.id}/trocar", params={"busca": "Gamma"}).text


def test_busca_de_casamentos_e_trocar_acha_pelo_nome_em_ingles(s, com_nome_en):
    assert nomes(s, busca="gamma box", situacao="todos") == ["Caixa Gama"]
    assert [p.nome for p, _ in consultas_amazon.buscar_produtos(s, "Gamma Box")] == ["Caixa Gama"]


def test_sugestoes_acham_pelo_nome_em_ingles(s):
    alvo = criar_produto(s, "alvo", nome="Caixa de Draft Quenya Colecionador")
    alvo.nome_en = "Zorblax Wombat Collector Draft Box"
    atual = criar_produto(s, "atual", nome="Outra Coisa Totalmente Diferente")
    for i in range(50):
        criar_produto(s, f"g{i}", nome=f"Caixa de Booster Magic Generico {i:03d}")
    anuncio = criar_anuncio(s, "B0ZORB0001", produto=atual)
    anuncio.titulo = "Zorblax Wombat Collector Draft Box"
    s.flush()
    assert consultas_amazon.sugestoes_para(s, anuncio)[0][0].id == alvo.id
