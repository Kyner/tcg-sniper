import base64

import pytest
from fakes import T0, criar_anuncio, criar_produto
from fastapi.testclient import TestClient

from tcg_sniper.admin.app import criar_app
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import Casamento, OrigemCasamento, StatusCasamento


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def avaliar(s, anuncio, produto, mesmo, confianca, motivo, aplicada=False, revisado=T0):
    av = repo_ia.gravar_avaliacao(
        s, anuncio_id=anuncio.id, produto_id=produto.id, mesmo_produto=mesmo, confianca=confianca, motivo=motivo,
        modelo="gpt-5", assinatura="x", sem_imagem=False, chamada_id=None, agora=T0,
    )
    if aplicada:
        av.aplicada_em = T0
        par = s.get(Casamento, (anuncio.id, produto.id))
        par.revisado_em = revisado  # o automático grava os dois no mesmo instante
        par.origem = OrigemCasamento.AUTOMATICO_IA if revisado == T0 else OrigemCasamento.MANUAL
        s.flush()
    return av


@pytest.fixture
def cenario(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Caixa Alfa")
        outro = criar_produto(s, "p2", nome="Caixa Beta")
        nao = criar_anuncio(s, "B1", produto=p)
        media = criar_anuncio(s, "B2", produto=p)
        sim = criar_anuncio(s, "B3", produto=p)
        criar_anuncio(s, "B4", produto=p)
        conf = criar_anuncio(s, "B5", produto=p, status=StatusCasamento.CONFIRMADO)
        par_antigo = criar_anuncio(s, "B6", produto=p)
        avaliar(s, nao, p, False, 92, "é carta avulsa")
        avaliar(s, media, p, True, 70, "edição parecida")
        avaliar(s, sim, p, True, 96, "mesma caixa de draft")
        avaliar(s, conf, p, True, 99, "idêntico", aplicada=True)
        avaliar(s, par_antigo, outro, True, 99, "avaliado contra outro produto")
        return p.id


def test_selos_motivo_e_ordem(cliente, cenario):
    html = cliente.get(f"/casamentos/produto/{cenario}").text
    assert "IA: mesmo produto 96%" in html and "IA: outro produto 92%" in html and "IA: mesmo produto 70%" in html
    assert "mesma caixa de draft" in html and "é carta avulsa" in html
    assert "badge-success" in html and "badge-error" in html and "badge-warning" in html
    # sim primeiro (por confiança), depois os demais na ordem de hoje
    assert html.index("Anúncio B3") < html.index("Anúncio B2") < html.index("Anúncio B1")
    assert "avaliado contra outro produto" not in html  # avaliação de outro par não aparece
    assert "automático pela IA" in html and "idêntico" in html  # confirmado pelo automático


def test_contagem_ia_sugere_na_lista(cliente, cenario):
    html = cliente.get("/casamentos").text
    assert "IA sugere" in html
    assert "2 pela IA" in html  # B3 (96%) e B2 (70%): pendentes com "sim"
    assert "IA sugere: 2 pela IA" not in html and "IA sugere: 2<" in html  # cartão do celular


def test_selo_pela_ia_some_quando_o_usuario_decidiu_depois(cliente, sessoes):
    from datetime import timedelta

    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Caixa Alfa")
        conf = criar_anuncio(s, "B1", produto=p, status=StatusCasamento.CONFIRMADO)
        ign = criar_anuncio(s, "B2", produto=p, status=StatusCasamento.IGNORADO)
        pela_ia = criar_anuncio(s, "B3", produto=p, status=StatusCasamento.IGNORADO)
        depois = T0 + timedelta(hours=1)
        avaliar(s, conf, p, True, 99, "motivo velho um", aplicada=True, revisado=depois)
        avaliar(s, ign, p, False, 99, "motivo velho dois", aplicada=True, revisado=depois)
        avaliar(s, pela_ia, p, False, 99, "carta avulsa", aplicada=True)
        produto_id = p.id
    html = cliente.get(f"/casamentos/produto/{produto_id}").text
    assert html.count(">automático pela IA<") == 1 and "carta avulsa" in html
    assert "motivo velho um" not in html and "motivo velho dois" not in html


def test_idioma_do_anuncio_aparece_nos_pares(cliente, sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Caixa Alfa")
        pend = criar_anuncio(s, "B1", produto=p)
        conf = criar_anuncio(s, "B2", produto=p, status=StatusCasamento.CONFIRMADO)
        ign = criar_anuncio(s, "B3", produto=p, status=StatusCasamento.IGNORADO, origem=OrigemCasamento.AUTOMATICO_IA)
        sem = criar_anuncio(s, "B4", produto=p)
        for anuncio, idioma in ((pend, "en"), (conf, "pt"), (ign, "ja"), (sem, None)):
            avaliar(s, anuncio, p, True, 90, "m").idioma_anuncio = idioma
        produto_id = p.id
    html = cliente.get(f"/casamentos/produto/{produto_id}").text
    assert '<span class="badge badge-outline badge-sm">inglês</span>' in html
    assert '<span class="badge badge-outline badge-sm">português</span>' in html
    assert '<span class="badge badge-error badge-outline badge-sm">japonês</span>' in html
    assert html.count("badge-outline badge-sm\">") == 3  # sem idioma (avaliação antiga): sem selo
