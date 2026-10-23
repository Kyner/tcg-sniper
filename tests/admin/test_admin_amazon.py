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
from tcg_sniper.admin.consultas_amazon import FiltroOfertas
from tcg_sniper.coletor_amazon.modelos import AvaliacaoVendedor
from tcg_sniper.consultas import casamentos
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    Envio,
    EstadoColetorTipo,
    MotivoEncerramento,
    Oportunidade,
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
    assert "Amazon" in texto and "Ciclo desde" in texto
    assert 'action="/amazon/pausar"' in cliente.get("/servicos").text


def test_pausar_e_retomar_a_amazon(cliente, sessoes):
    assert cliente.post("/amazon/pausar", follow_redirects=False).status_code == 303
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.PAUSADO
        assert repo.obter_estado(s).estado is EstadoColetorTipo.ATIVO  # a Liga não muda
    assert 'action="/amazon/retomar"' in cliente.get("/servicos").text
    cliente.post("/amazon/retomar")
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.ATIVO


def test_index_mostra_o_captcha_da_amazon_com_o_link_do_novnc(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em https://www.amazon.com.br/s?k=x", T0, COLETOR_AMAZON)
    texto = cliente.get("/servicos").text
    assert ":6081/vnc.html" in texto and 'action="/amazon/retomar"' in texto


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
        "monitor_intervalo_min": "15",
        "monitor_janela_inicio": "08:00",
        "monitor_janela_fim": "22:00",
        "monitor_max_paginas_hora": "150",
        "monitor_esgotado_dias": "7",
        "margem_candidata_pp": "5",
        "checkout_validade_h": "6",
        "descoberta_casados_dias": "7",
        "carencia_encerramento_min": "30",
        "quase_oportunidade_min_pct": "10",
    }
    campos.update({k: str(v) for k, v in mudancas.items()})
    return campos


def test_configuracoes_grava_valores_validos(cliente, sessoes):
    r = cliente.post("/configuracoes/amazon", data=formulario_padrao(desconto_min_pct=30), follow_redirects=False)
    assert r.status_code == 303
    with sessoes() as s:
        assert repo_amz.obter_config(s).desconto_min_pct == 30
    assert "Salvo; vale a partir da próxima coleta ou ciclo." in cliente.get(r.headers["location"]).text


def test_configuracoes_recusa_valor_invalido_e_nao_grava_nada(cliente, sessoes):
    r = cliente.post("/configuracoes/amazon", data=formulario_padrao(desconto_min_pct=0, max_buscas_hora=150))
    assert r.status_code == 400
    assert "entre 1 e 90" in r.text
    assert 'name="max_buscas_hora" value="150"' in r.text  # o formulário volta com o que foi digitado
    with sessoes() as s:
        config = repo_amz.obter_config(s)
    assert (config.desconto_min_pct, config.max_buscas_hora) == (25, 90)


SP = ZoneInfo("America/Sao_Paulo")


def anuncio_com_preco(s, asin, produto, preco, status=StatusCasamento.PENDENTE, agora=T0, titulo=None):
    anuncio = criar_anuncio(s, asin, produto=produto, status=status, agora=agora)
    if titulo:
        anuncio.titulo = titulo
    repo_amz.registrar_preco(s, anuncio.id, Decimal(preco), OrigemPreco.BUSCA, None, Envio.DESCONHECIDO, agora, SP)
    return anuncio


def test_candidatos_para_ignora_tokens_genericos_e_cai_para_todos():
    nomes = [f"caixa de booster magic edicao serie{i}" for i in range(300)]
    nomes += ["caixa de booster magic zulu colecionador", "display zulu especial"]
    indice: dict[str, set[str]] = {}
    for nome in nomes:
        for token in casamentos._tokens(nome):
            indice.setdefault(token, set()).add(nome)
    candidatos = casamentos.candidatos_para("caixa de booster magic zulu colecionador plus", nomes, indice)
    assert candidatos == ["caixa de booster magic zulu colecionador", "display zulu especial"]
    assert len(candidatos) < len(nomes) / 50
    assert casamentos.candidatos_para("caixa de booster magic", nomes, indice) == nomes


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
        desconto_pct=Decimal("31.00"), vendedor_id=amazon.id, envio=Envio.AMAZON, agora=T0, conferido=False,
    )
    return ff, sem_desconto, caro, barato


def test_ofertas_melhor_oferta_por_produto_ordenada_por_desconto(s):
    ff, sem_desconto, _, _ = preparar_ofertas(s)
    config = repo_amz.obter_config(s)
    linhas = consultas_amazon.ofertas(s, FiltroOfertas(), config)
    assert [(l.produto.id, l.anuncio.asin, l.preco, l.desconto) for l in linhas] == [
        (ff.id, "B02", Decimal("690.00"), Decimal("31.00")),
        (sem_desconto.id, "B03", Decimal("95.00"), Decimal("5.00")),
    ]
    assert linhas[0].aberta and linhas[0].confiavel and not linhas[1].aberta
    assert [l.produto.id for l in consultas_amazon.ofertas(s, FiltroOfertas(desconto_min=config.desconto_min_pct), config)] == [ff.id]
    assert [l.produto.id for l in consultas_amazon.ofertas(s, FiltroOfertas(situacao="abertas"), config)] == [ff.id]


def test_ofertas_mostra_o_risco_da_oportunidade(s):
    ff, *_ = preparar_ofertas(s)
    config = repo_amz.obter_config(s)
    op = s.scalar(select(Oportunidade).where(Oportunidade.produto_id == ff.id, Oportunidade.fechada_em.is_(None)))
    op.em_risco_desde, op.motivo_risco = T0, MotivoEncerramento.PRECO_SUBIU
    s.flush()
    [linha] = [l for l in consultas_amazon.ofertas(s, FiltroOfertas(), config) if l.produto.id == ff.id]
    assert linha.risco == (T0, "preço subiu")


@pytest.mark.parametrize("risco_no_da_linha", [True, False])
def test_ofertas_mostra_o_risco_da_oportunidade_do_proprio_anuncio(s, risco_no_da_linha):
    """Duas oportunidades abertas em anúncios diferentes do mesmo produto: o selo da linha (a oferta mais
    barata, B02) é o da oportunidade desse anúncio, não o de outro anúncio do produto."""
    ff, _, _, barato = preparar_ofertas(s)
    config = repo_amz.obter_config(s)
    caro = anuncio_com_preco(s, "B05", ff, "900.00", status=StatusCasamento.CONFIRMADO)  # id depois do da linha
    outra = repo_amz.abrir_oportunidade(
        s, anuncio_id=caro.id, produto_id=ff.id, preco_amazon=Decimal("900.00"), preco_liga=Decimal("1000.00"),
        desconto_pct=Decimal("10.00"), vendedor_id=None, envio=Envio.AMAZON, agora=T0, conferido=False,
    )
    da_linha = s.scalar(select(Oportunidade).where(Oportunidade.anuncio_id == barato.id))
    em_risco = da_linha if risco_no_da_linha else outra
    em_risco.em_risco_desde, em_risco.motivo_risco = T0, MotivoEncerramento.PRECO_SUBIU
    s.flush()
    outra.preco_amazon = Decimal("899.00")  # a do outro anúncio é a última gravada (e a última lida)
    s.flush()
    [linha] = [l for l in consultas_amazon.ofertas(s, FiltroOfertas(), config) if l.produto.id == ff.id]
    assert linha.anuncio.id == barato.id and linha.aberta
    assert linha.risco == ((T0, "preço subiu") if risco_no_da_linha else None)


def test_lojista_fba_confiavel_ou_nao(s):
    ff = criar_produto(s, "ff")
    criar_preco_liga(s, ff, "1000.00")
    anuncio = anuncio_com_preco(s, "B01", ff, "700.00", status=StatusCasamento.CONFIRMADO)
    loja = repo_amz.gravar_vendedor(s, AvaliacaoVendedor("A1", "Loja", Decimal(85), 50), T0)
    repo_amz.registrar_preco(s, anuncio.id, Decimal("700.00"), OrigemPreco.PRODUTO, loja.id, Envio.FBA, T0, SP)
    [linha] = consultas_amazon.ofertas(s, FiltroOfertas(), repo_amz.obter_config(s))
    assert (linha.envio, linha.vendedor.nome, linha.confiavel) == (Envio.FBA, "Loja", False)


def test_tela_de_ofertas(cliente, sessoes):
    with sessoes() as s, s.begin():
        preparar_ofertas(s)
    texto = cliente.get("/ofertas").text
    assert "Caixa FF" in texto and "R$ 690,00" in texto and "31,00%" in texto and "Caixa Sem Amazon" not in texto
    assert "Caixa Sem Desconto" not in cliente.get("/ofertas?desconto_min=25").text
    assert cliente.get("/ofertas?vendedor=xyz").status_code == 400


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
    texto = cliente.get("/logs").text
    parte_liga, parte_amazon = texto.split('aria-label="Amazon"')
    assert 'aria-label="LigaMagic"' in parte_liga
    assert 'data-tipo="produtos"' in parte_liga and 'data-tipo="amazon"' not in parte_liga
    assert parte_amazon.count('data-tipo="amazon"') == 12
    assert 'data-tipo="produtos"' not in parte_amazon


def test_servicos_tem_selo_de_estado(cliente):
    texto = cliente.get("/servicos").text
    assert 'badge-success">ligado</span>' in texto
