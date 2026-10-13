from decimal import Decimal

from fakes import (
    NavegadorFake,
    NotificadorFake,
    cartao_listagem,
    fixture_liga,
    html_listagem,
    pagina_html,
)
from sqlalchemy import func, select

from tcg_sniper.coletor_liga.listagens import coletar_listagens
from tcg_sniper.coletor_liga.modelos import ErroRede, PaginaExpandida
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import (
    Coleta,
    EstadoColetorTipo,
    PrecoAtualLiga,
    PrecoListagem,
    ProdutoLiga,
    StatusColeta,
    TipoColeta,
)
from tcg_sniper.notificador.base import Destino

HTML_10 = fixture_liga("catalogo_pagina_1")  # 40 cartões, todos com preço
# categoria 11: um produto que também está na 10 (127987) e um novo sem estoque
HTML_11 = html_listagem(
    cartao_listagem("127987", "Caixa de Booster - 30th Anniversary Edition", "R$ 9.999,99"),
    cartao_listagem("900001", "Bundle - Teste", None, categoria="Bundles"),
)
HTML_12 = html_listagem(cartao_listagem("900002", "Kit - Teste", "R$ 1.234,56", categoria="Kits"))
HTML_QUEBRADO = "<html><body><p>layout novo</p></body></html>"
DESAFIO = pagina_html("<html></html>", titulo="Just a moment...")


def url(config, categ):
    return config.url_listagem(categ)


def expandida(html, url_pagina, cliques=0, limite=False):
    return PaginaExpandida(pagina_html(html, url=url_pagina), cliques, limite)


def paginas_ok(config):
    return {
        url(config, "10"): expandida(HTML_10, url(config, "10"), cliques=2),
        url(config, "11"): expandida(HTML_11, url(config, "11")),
        url(config, "12"): expandida(HTML_12, url(config, "12")),
    }


def coletar(sessoes, config, paginas, pausas=None):
    navegador = NavegadorFake(paginas)
    notificador = NotificadorFake()
    resultado = coletar_listagens(
        sessoes,
        navegador,
        notificador,
        config,
        dormir=(pausas if pausas is not None else []).append,
        embaralhar=lambda lista: None,
    )
    return resultado, navegador, notificador


def contar(sessoes, modelo):
    with sessoes() as s:
        return s.scalar(select(func.count()).select_from(modelo))


def test_varre_todas_as_categorias_grava_catalogo_e_preco_atual(sessoes, config):
    pausas = []
    resultado, navegador, notificador = coletar(sessoes, config, paginas_ok(config), pausas)

    assert navegador.expandidas == [(url(config, c), 5) for c in ("10", "11", "12")]
    assert resultado.status is StatusColeta.OK
    assert (resultado.produtos_ok, resultado.produtos_falha, resultado.novos) == (3, 0, 42)
    # 2 pausas antes dos cliques em "Exibir mais" da categoria 10 + 2 entre categorias
    assert len(pausas) == 4 and all(8 <= p <= 20 for p in pausas)
    assert notificador.mensagens == [
        (Destino.ADMIN, "42 produtos novos no catálogo. Ativar em http://host.test:8000/catalogo?filtro=novos")
    ]
    assert contar(sessoes, ProdutoLiga) == 42
    assert contar(sessoes, PrecoListagem) == 42
    with sessoes() as s:
        assert s.scalar(select(func.count()).select_from(ProdutoLiga).where(ProdutoLiga.ativo)) == 0
        precos = dict(
            s.execute(
                select(ProdutoLiga.liga_id, PrecoAtualLiga.preco_a_partir).join(
                    PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id
                )
            ).all()
        )
        assert precos["127987"] == Decimal("8888.85")  # primeira categoria visitada vence
        assert precos["900001"] is None  # sem estoque: None, não zero
        assert precos["900002"] == Decimal("1234.56")
        coleta = s.get(Coleta, resultado.coleta_id)
        assert coleta.tipo is TipoColeta.LISTAGEM
        assert coleta.status is StatusColeta.OK and coleta.finalizada_em is not None


def test_segunda_coleta_nao_avisa_e_acrescenta_historico(sessoes, config):
    coletar(sessoes, config, paginas_ok(config))
    resultado, _, notificador = coletar(sessoes, config, paginas_ok(config))
    assert resultado.novos == 0
    assert notificador.mensagens == []
    assert contar(sessoes, ProdutoLiga) == 42
    assert contar(sessoes, PrecoListagem) == 84
    with sessoes() as s:
        assert set(s.scalars(select(PrecoAtualLiga.listagem_coleta_id))) == {resultado.coleta_id}


def test_desafio_na_segunda_categoria_pausa_e_avisa(sessoes, config):
    paginas = paginas_ok(config)
    paginas[url(config, "11")] = PaginaExpandida(DESAFIO, 0, False)
    resultado, navegador, notificador = coletar(sessoes, config, paginas)

    assert resultado.status is StatusColeta.PAUSADA_DESAFIO
    assert (resultado.produtos_ok, resultado.novos) == (1, 40)
    assert navegador.visitadas == [url(config, "10"), url(config, "11")]
    textos = [texto for _, texto in notificador.mensagens]
    assert "http://host.test:6080/vnc.html" in textos[0]
    assert textos[1].startswith("40 produtos novos")
    with sessoes() as s:
        assert repo.obter_estado(s).estado is EstadoColetorTipo.PAUSADO_DESAFIO
        assert s.get(Coleta, resultado.coleta_id).status is StatusColeta.PAUSADA_DESAFIO


def test_coletor_pausado_nao_executa(sessoes, config):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "x", repo.agora_utc())
    resultado, navegador, _ = coletar(sessoes, config, paginas_ok(config))
    assert resultado is None
    assert navegador.visitadas == []
    assert contar(sessoes, Coleta) == 0


def test_falha_de_parser_salva_html_e_status_parcial(sessoes, config):
    paginas = paginas_ok(config)
    paginas[url(config, "11")] = expandida(HTML_QUEBRADO, url(config, "11"))
    resultado, _, notificador = coletar(sessoes, config, paginas)
    assert resultado.status is StatusColeta.PARCIAL
    assert (resultado.produtos_ok, resultado.produtos_falha) == (2, 1)
    assert [t for _, t in notificador.mensagens if "layout" in t] == []
    salvos = list((config.dir_dados / "falhas").glob("*.html"))
    assert [p.name for p in salvos] == [f"listagem-{resultado.coleta_id}-11.html"]
    assert salvos[0].read_text(encoding="utf-8") == HTML_QUEBRADO


def test_mais_da_metade_falhando_avisa_layout(sessoes, config):
    paginas = paginas_ok(config)
    paginas[url(config, "11")] = expandida(HTML_QUEBRADO, url(config, "11"))
    paginas[url(config, "12")] = expandida(HTML_QUEBRADO, url(config, "12"))
    resultado, _, notificador = coletar(sessoes, config, paginas)
    assert resultado.status is StatusColeta.FALHA
    textos = [t for _, t in notificador.mensagens]
    assert any("falhou em 2 de 3 categorias" in t and "layout" in t for t in textos)


def test_limite_de_cliques_conta_como_falha_da_categoria(sessoes, config):
    paginas = paginas_ok(config)
    paginas[url(config, "10")] = expandida(HTML_10, url(config, "10"), cliques=5, limite=True)
    resultado, _, _ = coletar(sessoes, config, paginas)
    assert (resultado.produtos_ok, resultado.produtos_falha) == (2, 1)
    assert resultado.status is StatusColeta.PARCIAL
    assert contar(sessoes, ProdutoLiga) == 3  # nada da categoria 10 foi gravado
    assert (config.dir_dados / "falhas" / f"listagem-{resultado.coleta_id}-10.html").exists()


def test_erro_de_rede_tenta_de_novo_uma_vez(sessoes, config):
    paginas = paginas_ok(config)
    paginas[url(config, "10")] = [ErroRede("timeout"), expandida(HTML_10, url(config, "10"))]
    paginas[url(config, "11")] = [ErroRede("timeout"), ErroRede("timeout")]
    pausas = []
    resultado, _, _ = coletar(sessoes, config, paginas, pausas)
    assert (resultado.produtos_ok, resultado.produtos_falha) == (2, 1)
    assert pausas.count(30) == 2


def test_erro_inesperado_fecha_coleta_como_falha(sessoes, config):
    paginas = paginas_ok(config)
    paginas[url(config, "11")] = RuntimeError("chromium morreu")
    resultado, _, notificador = coletar(sessoes, config, paginas)
    assert resultado.status is StatusColeta.FALHA
    assert any("chromium morreu" in t for _, t in notificador.mensagens)
    assert any(t.startswith("40 produtos novos") for _, t in notificador.mensagens)
    with sessoes() as s:
        coleta = s.get(Coleta, resultado.coleta_id)
        assert coleta.status is StatusColeta.FALHA and "chromium morreu" in coleta.erro
