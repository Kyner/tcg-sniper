from urllib.parse import urlsplit

from fakes import (
    AvisadorFake,
    NavegadorFake,
    criar_produto,
    fixture_liga,
    pagina_html,
)
from sqlalchemy import func, select

from tcg_sniper.avisos.catalogo import TipoAviso
from tcg_sniper.coletor_liga.modelos import ErroRede
from tcg_sniper.coletor_liga.parsers import parse_produto
from tcg_sniper.coletor_liga.produtos import coletar_produtos
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import (
    Coleta,
    EstadoColetorTipo,
    PrecoAtualLiga,
    ProdutoLiga,
    ResumoPreco,
    StatusColeta,
    TipoColeta,
)

HTML_OK = fixture_liga("produto_varios_vendedores")
HTML_QUEBRADO = "<html><body><p>layout novo</p></body></html>"
DESAFIO = pagina_html("<html></html>", titulo="Just a moment...")


def preparar(sessoes, *liga_ids, inativos=()):
    with sessoes() as s, s.begin():
        for i in inativos:
            criar_produto(s, i, ativo=False)
        return {i: criar_produto(s, i).url for i in liga_ids}


def coletar(sessoes, config, paginas, pausas=None):
    navegador = NavegadorFake(paginas)
    avisador = AvisadorFake()
    resultado = coletar_produtos(
        sessoes,
        navegador,
        avisador,
        config,
        dormir=(pausas if pausas is not None else []).append,
        embaralhar=lambda lista: None,
    )
    return resultado, navegador, avisador


def test_coleta_ok_grava_resumos_e_pausa_entre_produtos(sessoes, config):
    urls = preparar(sessoes, "a", "b", "c", inativos=("z",))
    pausas = []
    resultado, navegador, avisador = coletar(
        sessoes, config, {u: pagina_html(HTML_OK, url=u) for u in urls.values()}, pausas
    )

    assert navegador.visitadas == list(urls.values())  # o inativo "z" não é visitado
    assert resultado.status is StatusColeta.OK
    assert (resultado.produtos_ok, resultado.produtos_falha) == (3, 0)
    assert len(pausas) == 2 and all(8 <= p <= 20 for p in pausas)
    assert avisador.mensagens == []
    with sessoes() as s:
        assert s.scalar(select(func.count()).select_from(ResumoPreco)) == 3
        atuais = s.scalars(select(PrecoAtualLiga)).all()
        esperado = parse_produto(HTML_OK)
        assert len(atuais) == 3
        assert all(
            (a.preco_min, a.preco_medio, a.preco_max, a.num_lojas, a.resumo_coleta_id)
            == (esperado.preco_min, esperado.preco_medio, esperado.preco_max, esperado.num_lojas, resultado.coleta_id)
            for a in atuais
        )
        coleta = s.get(Coleta, resultado.coleta_id)
        assert coleta.tipo is TipoColeta.PRODUTOS
        assert coleta.status is StatusColeta.OK and coleta.finalizada_em is not None


def test_desafio_pausa_coleta_avisa_admin_e_para(sessoes, config):
    urls = preparar(sessoes, "a", "b", "c")
    paginas = {urls["a"]: pagina_html(HTML_OK), urls["b"]: DESAFIO, urls["c"]: pagina_html(HTML_OK)}
    resultado, navegador, avisador = coletar(sessoes, config, paginas)

    assert resultado.status is StatusColeta.PAUSADA_DESAFIO
    assert navegador.visitadas == [urls["a"], urls["b"]]
    [(tipo, _, dados)] = avisador.avisos
    assert tipo is TipoAviso.LIGA_DESAFIO and dados.linhas[0] == f"Página: {urlsplit(urls['b']).path}"
    assert ":6080" not in avisador.mensagens[0][1] and ":8000" not in avisador.mensagens[0][1]
    with sessoes() as s:
        assert repo.obter_estado(s).estado is EstadoColetorTipo.PAUSADO_DESAFIO
        assert s.get(Coleta, resultado.coleta_id).status is StatusColeta.PAUSADA_DESAFIO
        assert s.scalar(select(func.count()).select_from(PrecoAtualLiga)) == 1


def test_coletor_pausado_nao_executa(sessoes, config):
    urls = preparar(sessoes, "a")
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "x", repo.agora_utc())
    resultado, navegador, _ = coletar(sessoes, config, {urls["a"]: pagina_html(HTML_OK)})
    assert resultado is None
    assert navegador.visitadas == []
    with sessoes() as s:
        assert s.scalar(select(func.count()).select_from(Coleta)) == 0


def test_falha_de_parser_salva_html_e_status_parcial(sessoes, config):
    urls = preparar(sessoes, "a", "b", "c")
    paginas = {
        urls["a"]: pagina_html(HTML_OK),
        urls["b"]: pagina_html(HTML_QUEBRADO),
        urls["c"]: pagina_html(HTML_OK),
    }
    resultado, _, avisador = coletar(sessoes, config, paginas)
    assert resultado.status is StatusColeta.PARCIAL
    assert (resultado.produtos_ok, resultado.produtos_falha) == (2, 1)
    assert avisador.mensagens == []
    salvos = list((config.dir_dados / "falhas").glob("produto-*.html"))
    assert len(salvos) == 1 and salvos[0].read_text(encoding="utf-8") == HTML_QUEBRADO


def test_mais_da_metade_falhando_avisa_layout(sessoes, config):
    urls = preparar(sessoes, "a", "b", "c")
    paginas = {
        urls["a"]: pagina_html(HTML_OK),
        urls["b"]: pagina_html(HTML_QUEBRADO),
        urls["c"]: pagina_html(HTML_QUEBRADO),
    }
    resultado, _, avisador = coletar(sessoes, config, paginas)
    assert resultado.status is StatusColeta.FALHA
    [falhou] = avisador.dados(TipoAviso.LIGA_COLETA_FALHOU)
    assert falhou.linhas == ("Etapa: Coleta dos produtos ativos", "Falhas: 2 de 3 produtos")


def test_erro_de_rede_tenta_de_novo_uma_vez(sessoes, config):
    urls = preparar(sessoes, "a", "b")
    paginas = {
        urls["a"]: [ErroRede("timeout"), pagina_html(HTML_OK)],
        urls["b"]: [ErroRede("timeout"), ErroRede("timeout")],
    }
    pausas = []
    resultado, _, _ = coletar(sessoes, config, paginas, pausas)
    assert (resultado.produtos_ok, resultado.produtos_falha) == (1, 1)
    assert pausas.count(30) == 2


def test_erro_inesperado_fecha_coleta_como_falha(sessoes, config):
    urls = preparar(sessoes, "a")
    resultado, _, avisador = coletar(sessoes, config, {urls["a"]: RuntimeError("chromium morreu")})
    assert resultado.status is StatusColeta.FALHA and resultado.interrompida
    assert avisador.tipos() == [TipoAviso.LIGA_ERRO]
    with sessoes() as s:
        coleta = s.get(Coleta, resultado.coleta_id)
        assert coleta.status is StatusColeta.FALHA and "chromium morreu" in coleta.erro


def test_sem_produtos_ativos(sessoes, config):
    resultado, _, _ = coletar(sessoes, config, {})
    assert resultado.status is StatusColeta.OK
    assert (resultado.produtos_ok, resultado.produtos_falha) == (0, 0)


def test_coleta_guarda_o_nome_em_ingles_e_nao_apaga_com_pagina_sem_ele(sessoes, config):
    urls = preparar(sessoes, "a")
    [url] = urls.values()
    com_en = pagina_html(fixture_liga("produto_nome_en"), url=url)
    coletar(sessoes, config, {url: com_en})
    with sessoes() as s:
        assert s.scalar(select(ProdutoLiga.nome_en)) == (
            "Booster Box - The Lord of the Rings: Tales of Middle-Earth - Draft Booster"
        )
        assert s.scalar(select(ProdutoLiga.imagem_url)) == (
            "https://repositorio.sbrauble.com/arquivos/up/prod/20230222/1677093808_3868.jpg"
        )
    coletar(sessoes, config, {url: pagina_html(HTML_OK, url=url)})
    with sessoes() as s:
        assert s.scalar(select(ProdutoLiga.nome_en)).startswith("Booster Box")
        assert s.scalar(select(ProdutoLiga.imagem_url)).endswith("1677093808_3868.jpg")
