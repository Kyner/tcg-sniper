import base64
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto
from fastapi.testclient import TestClient
from sqlalchemy import select

from tcg_sniper.admin import consultas_amazon
from tcg_sniper.admin.app import criar_app
from tcg_sniper.coletor_amazon.modelos import AvaliacaoVendedor
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    AnuncioAmazon,
    Envio,
    EstadoColetorTipo,
    OrigemPreco,
    StatusCasamento,
    StatusColeta,
    TipoColeta,
)


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


def test_pendentes_com_catalogo_grande_acha_as_alternativas_certas(s):
    for i in range(300):
        criar_produto(s, f"c{i}", nome=f"Caixa de Booster Magic Edicao Serie{i}")
    alvo = criar_produto(s, "alvo", nome="Caixa de Booster Magic Zulu Colecionador")
    criar_produto(s, "alvo2", nome="Caixa de Booster Magic Zulu Colecionador Plus")
    criar_produto(s, "alvo3", nome="Display Zulu Especial")
    anuncio_com_preco(s, "B01", alvo, "100.00", titulo="Caixa de Booster Magic Zulu Colecionador Plus Box")
    anuncio_com_preco(s, "B02", None, "100.00", titulo="Caixa de Booster Magic")  # so tokens genericos
    linhas, total = consultas_amazon.pendentes(s, desconto_min_pct=25)
    assert total == 2
    por_asin = {linha.anuncio.asin: linha for linha in linhas}
    nomes = [p.nome for p in por_asin["B01"].alternativas]
    assert nomes[0] == "Caixa de Booster Magic Zulu Colecionador Plus"
    assert alvo.nome not in nomes
    assert len(por_asin["B02"].alternativas) == 3  # fallback: compara com o catalogo todo


def test_candidatos_para_ignora_tokens_genericos_e_cai_para_todos():
    nomes = [f"caixa de booster magic edicao serie{i}" for i in range(300)]
    nomes += ["caixa de booster magic zulu colecionador", "display zulu especial"]
    indice: dict[str, set[str]] = {}
    for nome in nomes:
        for token in consultas_amazon._tokens(nome):
            indice.setdefault(token, set()).add(nome)
    candidatos = consultas_amazon.candidatos_para("caixa de booster magic zulu colecionador plus", nomes, indice)
    assert candidatos == ["caixa de booster magic zulu colecionador", "display zulu especial"]
    assert len(candidatos) < len(nomes) / 50
    assert consultas_amazon.candidatos_para("caixa de booster magic", nomes, indice) == nomes


def test_aba_revisados_mostra_contagem_de_pendentes(cliente, sessoes):
    with sessoes() as s, s.begin():
        anuncio_com_preco(s, "B01", criar_produto(s, "ff"), "700.00")
    assert "1 pendentes" in cliente.get("/casamentos?aba=revisados").text


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
    ff, sem_desconto, _, _ = preparar_ofertas(s)
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
    loja = repo_amz.gravar_vendedor(s, AvaliacaoVendedor("A1", "Loja", Decimal(85), 50), T0)
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


def test_ciclos_da_amazon_nao_empurram_as_coletas_da_liga(cliente, sessoes):
    with sessoes() as s, s.begin():
        liga = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0)
        repo.finalizar_coleta(s, liga.id, StatusColeta.OK, 1, 0, T0)
        for i in range(12):
            ciclo = repo.iniciar_coleta(s, TipoColeta.AMAZON, T0 + timedelta(hours=i))
            repo.finalizar_coleta(s, ciclo.id, StatusColeta.OK, 3, 0, T0 + timedelta(hours=i))
    texto = cliente.get("/").text
    parte_liga, parte_amazon = texto.split("Últimos ciclos (Amazon)")
    assert "Últimas coletas (LigaMagic)" in parte_liga
    assert "<td>produtos</td>" in parte_liga and "<td>amazon</td>" not in parte_liga
    assert parte_amazon.count("<td>amazon</td>") == 10
    assert "<td>produtos</td>" not in parte_amazon
