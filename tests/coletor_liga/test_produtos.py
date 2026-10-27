from datetime import datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fakes import (
    T0,
    AvisadorFake,
    NavegadorFake,
    criar_anuncio,
    criar_produto,
    fixture_liga,
    pagina_html,
)
from sqlalchemy import func, select

from tcg_sniper.avisos.catalogo import TipoAviso
from tcg_sniper.coletor_liga.modelos import ErroRede, Resumo
from tcg_sniper.coletor_liga.parsers import parse_produto
from tcg_sniper.coletor_liga.produtos import coletar_produtos
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import (
    Coleta,
    EstadoColetorTipo,
    PrecoAtualLiga,
    ProdutoLiga,
    ResumoPreco,
    StatusCasamento,
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


def coletar(sessoes, config, paginas, pausas=None, agora=None):
    navegador = NavegadorFake(paginas)
    avisador = AvisadorFake()
    resultado = coletar_produtos(
        sessoes,
        navegador,
        avisador,
        config,
        dormir=(pausas if pausas is not None else []).append,
        embaralhar=lambda lista: None,
        agora=agora,
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
    assert falhou.linhas == ("Etapa: Coleta dos produtos da lista do dia", "Falhas: 2 de 3 produtos")


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
    with sessoes() as s, s.begin():  # casado: entra na lista de amanhã (lido hoje fica de fora)
        criar_anuncio(s, produto=s.scalar(select(ProdutoLiga)), status=StatusCasamento.CONFIRMADO)
    amanha = repo.agora_utc() + timedelta(days=1)
    _, navegador, _ = coletar(sessoes, config, {url: pagina_html(HTML_OK, url=url)}, agora=amanha)
    assert navegador.visitadas == [url]  # a página sem o nome em inglês foi mesmo aberta
    with sessoes() as s:
        assert s.scalar(select(ProdutoLiga.nome_en)).startswith("Booster Box")
        assert s.scalar(select(ProdutoLiga.imagem_url)).endswith("1677093808_3868.jpg")


SP = ZoneInfo("America/Sao_Paulo")
QUARTA = datetime(2026, 10, 14, 12, 0, tzinfo=SP)
ANTIGO = QUARTA - timedelta(days=10)


def lido_em(s, produto, quando):
    c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, quando)
    repo.gravar_precos_produto(s, c.id, produto.id, Resumo(None, None, None, 1), quando)


def test_le_so_a_lista_do_dia_e_resume_os_grupos(sessoes, config):
    with sessoes() as s, s.begin():
        casado = criar_produto(s, "casado")
        lido_em(s, casado, ANTIGO)
        criar_anuncio(s, "B000000001", produto=casado, status=StatusCasamento.CONFIRMADO)
        candidato = criar_produto(s, "candidato")
        lido_em(s, candidato, ANTIGO)
        criar_anuncio(s, "B000000002", produto=candidato, status=StatusCasamento.PENDENTE)
        novo = criar_produto(s, "novo")
        velhos = [criar_produto(s, f"velho{i}") for i in range(7)]
        for v in velhos:
            lido_em(s, v, ANTIGO)
        [do_dia] = [v for v in velhos if v.id % 7 == QUARTA.weekday()]
        urls = [p.url for p in (casado, candidato, novo, do_dia)]
    paginas = {u: pagina_html(HTML_OK, url=u) for u in urls}
    resultado, navegador, _ = coletar(sessoes, config, paginas, agora=QUARTA)
    assert navegador.visitadas == urls  # os outros 6 velhos ficam para outros dias da semana
    assert (resultado.status, resultado.produtos_ok, resultado.produtos_falha) == (StatusColeta.OK, 4, 0)
    assert resultado.grupos == "casados 1, candidatos 1, novos 1, rodízio 1"


def test_retomar_continua_de_onde_parou_sem_reler_os_lidos_hoje(sessoes, config):
    urls = preparar(sessoes, "a", "b", "c")
    navegador = NavegadorFake(
        {urls["a"]: pagina_html(HTML_OK), urls["b"]: [DESAFIO, pagina_html(HTML_OK)], urls["c"]: pagina_html(HTML_OK)}
    )

    def rodar():
        return coletar_produtos(
            sessoes, navegador, AvisadorFake(), config, dormir=[].append, embaralhar=lambda lista: None
        )

    assert rodar().status is StatusColeta.PAUSADA_DESAFIO
    with sessoes() as s, s.begin():
        repo.retomar(s, repo.agora_utc())
    segundo = rodar()
    assert navegador.visitadas == [urls["a"], urls["b"], urls["b"], urls["c"]]  # "a" não é relido
    assert (segundo.status, segundo.produtos_ok) == (StatusColeta.OK, 2)
    assert segundo.grupos == "casados 0, candidatos 0, novos 2, rodízio 0"


def test_lista_vazia_fecha_ok_sem_abrir_pagina(sessoes, config):
    preparar(sessoes, inativos=("z",))
    resultado, navegador, avisador = coletar(sessoes, config, {})
    assert navegador.visitadas == [] and avisador.mensagens == []
    assert (resultado.status, resultado.produtos_ok, resultado.produtos_falha) == (StatusColeta.OK, 0, 0)
    assert resultado.grupos == "casados 0, candidatos 0, novos 0, rodízio 0"


def test_teto_de_novos_vem_da_configuracao(sessoes, config):
    with sessoes() as s, s.begin():
        novos = [criar_produto(s, f"n{i}", agora=T0 - timedelta(days=i)) for i in range(3)]  # n2 é o mais antigo
    paginas = {p.url: pagina_html(HTML_OK, url=p.url) for p in novos}
    c = config.model_copy(update={"produtos_novos_dia": 2})
    _, navegador, _ = coletar(sessoes, c, paginas)
    assert navegador.visitadas == [novos[2].url, novos[1].url]


def test_aviso_do_primeiro_desafio_do_dia_diz_que_volta_depois_de_esfriar(sessoes, config):
    urls = preparar(sessoes, "a")
    _, _, avisador = coletar(sessoes, config, {urls["a"]: DESAFIO})
    [dados] = avisador.dados(TipoAviso.LIGA_DESAFIO)
    assert dados.linhas[1:] == (
        "A coleta fica pausada até você retomar",
        "1º desafio de hoje: volta 30 min depois de você retomar, com pausas em dobro até o fim do dia",
    )


def test_aviso_sem_esfriar_diz_que_volta_logo(sessoes, config):
    urls = preparar(sessoes, "a")
    c = config.model_copy(update={"esfriar_desafio_min": 0})
    _, _, avisador = coletar(sessoes, c, {urls["a"]: DESAFIO})
    [dados] = avisador.dados(TipoAviso.LIGA_DESAFIO)
    assert dados.linhas[2] == "1º desafio de hoje: volta logo depois de você retomar, com pausas em dobro até o fim do dia"


def test_aviso_do_segundo_desafio_do_dia_diz_que_volta_amanha(sessoes, config):
    urls = preparar(sessoes, "a")
    with sessoes() as s, s.begin():
        antes = repo.agora_utc() - timedelta(seconds=1)
        c = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, antes)
        repo.finalizar_coleta(s, c.id, StatusColeta.PAUSADA_DESAFIO, 0, 0, antes, erro="desafio em /x")
    _, _, avisador = coletar(sessoes, config, {urls["a"]: DESAFIO})
    [dados] = avisador.dados(TipoAviso.LIGA_DESAFIO)
    assert dados.linhas[2] == "2º desafio de hoje: depois de retomar, a coleta só volta amanhã, no horário de sempre"


def falhas_da_pagina(sessoes, url):
    with sessoes() as s:
        return s.scalar(select(ProdutoLiga.falhas_pagina).where(ProdutoLiga.url == url))


def test_falha_de_rede_ou_parser_soma_e_leitura_boa_zera_as_falhas(sessoes, config):
    urls = preparar(sessoes, "a", "b")
    paginas = {urls["a"]: pagina_html(HTML_QUEBRADO), urls["b"]: [ErroRede("t"), ErroRede("t")]}
    coletar(sessoes, config, paginas)
    assert (falhas_da_pagina(sessoes, urls["a"]), falhas_da_pagina(sessoes, urls["b"])) == (1, 1)
    coletar(sessoes, config, {urls["a"]: pagina_html(HTML_OK, url=urls["a"]), urls["b"]: [ErroRede("t")] * 2})
    assert (falhas_da_pagina(sessoes, urls["a"]), falhas_da_pagina(sessoes, urls["b"])) == (0, 2)


def test_leitura_boa_zera_as_falhas(s):
    p = criar_produto(s, "x")
    repo.registrar_falha_pagina(s, p.id)
    repo.registrar_falha_pagina(s, p.id)
    c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0)
    repo.gravar_precos_produto(s, c.id, p.id, Resumo(None, None, None, 1), T0)
    s.refresh(p)
    assert p.falhas_pagina == 0
