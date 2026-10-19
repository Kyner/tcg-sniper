from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from fakes import AvisadorFake, cartao_busca, criar_preco_liga, criar_produto, html_busca, pagina_html
from fakes_checkout import carrinho
from fakes_varredura import CAPTCHA, MEIO_DIA, SP, Relogio, confirmado, criar_laco, livre, vazia
from sqlalchemy import select

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, TipoAviso
from tcg_sniper.coletor_amazon.busca import url_busca
from tcg_sniper.coletor_amazon.config import aplicar_config
from tcg_sniper.coletor_amazon.parsers import URL_CARRINHO, url_ofertas
from tcg_sniper.coletor_amazon.varredura_base import ESPERA_ERRO_S, ESPERA_OCIOSA_S, MAX_FALHAS_SEGUIDAS
from tcg_sniper.coletor_amazon.varredura_busca import VarreduraBusca
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_termos as repo_termos
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    COLETOR_AMAZON_BUSCA,
    AnuncioAmazon,
    Coleta,
    ConferenciaCheckout,
    EstadoColetorTipo,
    FilaAmazon,
    ProdutoLiga,
    SituacaoCheckout,
    StatusColeta,
    TipoColeta,
)
from tcg_sniper.notificador.base import Destino


def produtos(sessoes, *nomes):
    with sessoes() as s, s.begin():
        criados = []
        for nome in nomes:
            p = criar_produto(s, nome, nome=nome)
            criar_preco_liga(s, p, "1000.00", listagem_em=MEIO_DIA)
            criados.append(p)
        cfg = repo_amz.obter_config(s)
        return criados, {p.id: url_busca(cfg, p.nome) for p in criados}


def varredura(engine, sessoes, config, paginas, relogio=None):
    v, navegador, fabrica, avisador, _ = criar_laco(VarreduraBusca, engine, sessoes, config, paginas, relogio=relogio)
    return v, navegador, fabrica, avisador


def ciclos(sessoes):
    with sessoes() as s:
        return list(s.scalars(select(Coleta).where(Coleta.tipo == TipoColeta.AMAZON).order_by(Coleta.id)))


def test_passo_busca_reagenda_e_fecha_o_ciclo(engine, sessoes, config):
    (a, _b), urls = produtos(sessoes, "a", "b")
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()})
    assert v.passo() == 0
    assert v.passo() == 0
    assert sorted(navegador.visitadas) == sorted(urls.values())
    [ciclo] = ciclos(sessoes)
    assert (ciclo.status, ciclo.produtos_ok, ciclo.produtos_falha) == (StatusColeta.OK, 2, 0)
    with sessoes() as s:
        fila = s.get(FilaAmazon, a.id)
    assert fila.ultima_busca_em == MEIO_DIA
    assert fila.proxima_busca_em == MEIO_DIA + timedelta(minutes=60)
    assert v.passo() == ESPERA_OCIOSA_S  # nada vencido


def test_fora_da_janela_nao_busca_e_fecha_o_navegador(engine, sessoes, config):
    _, urls = produtos(sessoes, "a")
    noite = Relogio(datetime(2026, 10, 15, 23, 0, tzinfo=SP))
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()}, noite)
    assert v.passo() == ESPERA_OCIOSA_S
    assert navegador.visitadas == []


def test_fuso_salvo_na_tela_muda_a_janela_do_dia(engine, sessoes, config):
    _, urls = produtos(sessoes, "a", "b")
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()})
    assert v.passo() == 0  # meio-dia em São Paulo: dentro da janela; sobra um produto na fila
    with sessoes() as s, s.begin():
        repo.obter_config_geral(s, config)
        repo.salvar_config_geral(s, {"fuso": "Asia/Singapore"}, MEIO_DIA)  # lá são 23h do mesmo dia
    assert len(navegador.visitadas) == 1
    assert v.passo() == ESPERA_OCIOSA_S
    assert len(navegador.visitadas) == 1


def test_pausado_nao_busca(engine, sessoes, config):
    _, urls = produtos(sessoes, "a")
    with sessoes() as s, s.begin():
        repo.pausar(s, "manual", MEIO_DIA, COLETOR_AMAZON_BUSCA)
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()})
    assert v.passo() == ESPERA_OCIOSA_S
    assert navegador.visitadas == []


def test_captcha_pausa_so_a_busca_avisa_e_mantem_o_navegador(engine, sessoes, config):
    _, urls = produtos(sessoes, "a")
    [url] = urls.values()
    v, _, fabrica, avisador = varredura(engine, sessoes, config, {url: pagina_html(CAPTCHA, url=url)})
    assert v.passo() == ESPERA_OCIOSA_S
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON_BUSCA).estado is EstadoColetorTipo.PAUSADO_DESAFIO
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.ATIVO
    [ciclo] = ciclos(sessoes)
    assert ciclo.status is StatusColeta.PAUSADA_DESAFIO
    [(destino, texto)] = avisador.mensagens
    assert destino is Destino.ADMIN
    [(tipo, chave, dados)] = avisador.avisos
    assert (tipo, chave) == (TipoAviso.AMAZON_BUSCA_CAPTCHA, CHAVE_GERAL)
    assert dados.linhas[1] == "A busca fica pausada até você retomar; o monitor e a conferência seguem"
    assert "Amazon (busca) · CAPTCHA" in texto and "noVNC da busca (porta 6082)" in texto
    assert fabrica.fechados == 0


def test_falha_ao_gravar_a_pausa_por_captcha_nao_esquece_o_ciclo(engine, sessoes, config, monkeypatch):
    from tcg_sniper.coletor_amazon import varredura_busca as modulo

    _, urls = produtos(sessoes, "a", "b")
    url_a, url_b = urls.values()
    v, _, _, avisador = varredura(
        engine, sessoes, config, {url_a: vazia(url_a), url_b: [pagina_html(CAPTCHA, url=url_b), vazia(url_b)]}
    )
    assert v.passo() == 0  # a primeira busca abre o ciclo e sobra uma pendente
    assert v._ciclo is not None and v._pendentes
    ciclo_aberto, pendentes = v._ciclo, set(v._pendentes)

    def quebra(*_args, **_kwargs):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(modulo.repo, "pausar_por_desafio", quebra)
    with pytest.raises(RuntimeError):
        v.passo()
    assert v._ciclo == ciclo_aberto and v._pendentes == pendentes  # nada de estado esquecido sem commit
    assert [c.status for c in ciclos(sessoes)] == [StatusColeta.RODANDO]
    assert avisador.avisos == []


def test_retomar_continua_no_mesmo_navegador(engine, sessoes, config):
    _, urls = produtos(sessoes, "a")
    [url] = urls.values()
    v, navegador, fabrica, avisador = varredura(engine, sessoes, config, {url: [pagina_html(CAPTCHA, url=url), vazia(url)]})
    v.passo()
    assert (TipoAviso.AMAZON_BUSCA_CAPTCHA, CHAVE_GERAL) not in avisador.resolvidos
    with sessoes() as s, s.begin():
        repo.retomar(s, MEIO_DIA, COLETOR_AMAZON_BUSCA)
    assert v.passo() == 0
    assert navegador.visitadas == [url, url]
    assert fabrica.abertos == 1
    assert (TipoAviso.AMAZON_BUSCA_CAPTCHA, CHAVE_GERAL) in avisador.resolvidos


def test_falha_de_layout_conta_falha_e_ciclo_falho_avisa(engine, sessoes, config):
    _, urls = produtos(sessoes, "a")
    [url] = urls.values()
    v, _, _, avisador = varredura(engine, sessoes, config, {url: pagina_html("<html>novo</html>", url=url)})
    v.passo()
    [ciclo] = ciclos(sessoes)
    assert (ciclo.status, ciclo.produtos_falha) == (StatusColeta.FALHA, 1)
    assert TipoAviso.AMAZON_BUSCA_FALHOU in avisador.tipos()


def test_teto_por_hora(engine, sessoes, config):
    _, urls = produtos(sessoes, "a", "b")
    with sessoes() as s, s.begin():
        valores = {"max_buscas_hora": 1}
        aplicar_config(s, valores, MEIO_DIA)
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()})
    v.passo()
    assert v.passo() == ESPERA_OCIOSA_S
    assert len(navegador.visitadas) == 1


def test_mudanca_na_config_vale_no_passo_seguinte(engine, sessoes, config):
    (a, b), urls = produtos(sessoes, "a", "b")  # mesmo preço e mesmo vencimento: "a" (menor id) vai primeiro
    paginas = {
        urls[a.id]: pagina_html(html_busca(*(cartao_busca(f"A0000000{i}", "Item", "R$ 10,00") for i in range(3)))),
        urls[b.id]: pagina_html(html_busca(*(cartao_busca(f"B0000000{i}", "Item", "R$ 10,00") for i in range(3)))),
    }
    v, _, _, _ = varredura(engine, sessoes, config, paginas)
    v.passo()
    with sessoes() as s:
        assert len(s.scalars(select(AnuncioAmazon)).all()) == 3
    with sessoes() as s, s.begin():
        aplicar_config(s, {"resultados_por_busca": 1}, MEIO_DIA)
    v.passo()
    with sessoes() as s:
        assert len(s.scalars(select(AnuncioAmazon)).all()) == 4


def test_produto_desativado_no_meio_do_ciclo_sai_e_o_ciclo_fecha(engine, sessoes, config):
    (a, b), urls = produtos(sessoes, "a", "b")
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()})
    v.passo()
    buscado = navegador.visitadas[0]
    restante = b if buscado == urls[a.id] else a
    with sessoes() as s, s.begin():
        s.get(type(restante), restante.id).ativo = False
    assert v.passo() == ESPERA_OCIOSA_S
    assert len(navegador.visitadas) == 1
    [ciclo] = ciclos(sessoes)
    assert (ciclo.status, ciclo.produtos_ok) == (StatusColeta.OK, 1)


def test_erros_inesperados_seguidos_pausam(engine, sessoes, config, monkeypatch):
    from tcg_sniper.coletor_amazon import varredura_busca as modulo

    def quebrar(*_a, **_k):
        raise RuntimeError("banco caiu")

    monkeypatch.setattr(modulo, "processar_produto", quebrar)
    _, urls = produtos(sessoes, "a")
    relogio = Relogio(MEIO_DIA)
    v, _, fabrica, avisador = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()}, relogio)
    esperas = []
    for _ in range(3):
        try:
            v.passo()
        except RuntimeError as erro:
            esperas.append(v.tratar_erro(erro))
        relogio.agora += timedelta(hours=2)  # o produto que quebra é reagendado para daqui a 60 min
    assert esperas == [ESPERA_ERRO_S, ESPERA_ERRO_S, ESPERA_OCIOSA_S]
    with sessoes() as s:
        estado = repo.obter_estado(s, coletor=COLETOR_AMAZON_BUSCA)
    assert (estado.estado, estado.motivo) == (EstadoColetorTipo.PAUSADO, "erros seguidos")
    seguidos = [t for t in avisador.tipos() if t in (TipoAviso.AMAZON_BUSCA_ERRO, TipoAviso.AMAZON_BUSCA_PAUSADA)]
    assert seguidos == [TipoAviso.AMAZON_BUSCA_ERRO, TipoAviso.AMAZON_BUSCA_ERRO, TipoAviso.AMAZON_BUSCA_PAUSADA]
    assert fabrica.fechados == 3


def test_inicializar_so_marca_os_ciclos_da_amazon(engine, sessoes, config):
    with sessoes() as s, s.begin():
        liga = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, MEIO_DIA)
        amazon = repo.iniciar_coleta(s, TipoColeta.AMAZON, MEIO_DIA)
    v, _, _, avisador = varredura(engine, sessoes, config, {})
    v.inicializar()
    with sessoes() as s:
        assert s.get(Coleta, liga.id).status is StatusColeta.RODANDO
        assert s.get(Coleta, amazon.id).status is StatusColeta.FALHA
    assert avisador.tipos() == [TipoAviso.AMAZON_INTERROMPIDA]
    [dados] = avisador.dados(TipoAviso.AMAZON_INTERROMPIDA)
    assert dados.linhas == ("1 ciclo(s) marcado(s) como falha: o serviço de busca reiniciou",)


@pytest.mark.parametrize("hora", [7, 22])
def test_janela_nas_bordas(engine, sessoes, config, hora):
    _, urls = produtos(sessoes, "a")
    relogio = Relogio(datetime(2026, 10, 15, hora, 0, tzinfo=SP) + timedelta(minutes=-20 if hora == 7 else 20))
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()}, relogio)
    assert v.passo() == ESPERA_OCIOSA_S
    assert navegador.visitadas == []


def test_produto_que_quebra_nao_trava_a_fila(engine, sessoes, config, monkeypatch):
    from tcg_sniper.coletor_amazon import varredura_busca as modulo

    (a, b), urls = produtos(sessoes, "a", "b")
    real = modulo.processar_produto

    def quebra_so_a(contexto, produto, termo=None):
        if produto.id == a.id:
            raise RuntimeError("bug no parser")
        return real(contexto, produto, termo)

    monkeypatch.setattr(modulo, "processar_produto", quebra_so_a)
    v, navegador, _, _ = varredura(engine, sessoes, config, {urls[b.id]: vazia(urls[b.id])})
    with pytest.raises(RuntimeError) as info:
        v.passo()
    assert v.tratar_erro(info.value) == ESPERA_ERRO_S
    with sessoes() as s:
        assert s.get(FilaAmazon, a.id).proxima_busca_em > MEIO_DIA
    assert v.passo() == 0
    assert navegador.visitadas == [urls[b.id]]
    [ciclo] = ciclos(sessoes)
    assert (ciclo.produtos_ok, ciclo.produtos_falha) == (1, 1)


def test_ciclo_de_um_produto_que_quebra_nao_fecha_como_ok(engine, sessoes, config, monkeypatch):
    from tcg_sniper.coletor_amazon import varredura_busca as modulo

    def quebrar(*_a, **_k):
        raise RuntimeError("bug")

    monkeypatch.setattr(modulo, "processar_produto", quebrar)
    _, urls = produtos(sessoes, "a")
    v, _, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()})
    with pytest.raises(RuntimeError):
        v.passo()
    [ciclo] = ciclos(sessoes)
    assert ciclo.produtos_falha >= 1
    assert ciclo.status is StatusColeta.FALHA


def test_tratar_erro_nunca_levanta_se_a_pausa_falhar(engine, sessoes, config, monkeypatch):
    from tcg_sniper.coletor_amazon import varredura_busca as modulo

    def quebrar(*_a, **_k):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(modulo.repo, "pausar", quebrar)
    v, _, _, avisador = varredura(engine, sessoes, config, {})
    esperas = [v.tratar_erro(RuntimeError("x")) for _ in range(3)]
    assert esperas == [ESPERA_ERRO_S] * 3
    assert avisador.tipos() == [TipoAviso.AMAZON_BUSCA_ERRO, TipoAviso.AMAZON_BUSCA_ERRO, TipoAviso.AMAZON_BUSCA_PAUSADA]
    assert avisador.dados(TipoAviso.AMAZON_BUSCA_PAUSADA)[0].linhas[1] == (
        "Não consegui registrar a pausa no banco: nova tentativa em 15 min"
    )


def quebrada(url):
    return pagina_html("<html></html>", url=url)


def nomes(n):
    return [f"p{i:02d}" for i in range(n)]  # mesmo preço e vencimento: a fila segue a ordem de id


def test_falhas_seguidas_pausam_a_busca(engine, sessoes, config):
    _, urls = produtos(sessoes, *nomes(MAX_FALHAS_SEGUIDAS + 1))
    v, navegador, _, avisador = varredura(engine, sessoes, config, {u: quebrada(u) for u in urls.values()})
    for _ in range(MAX_FALHAS_SEGUIDAS):
        v.passo()
    with sessoes() as s:
        estado = repo.obter_estado(s, coletor=COLETOR_AMAZON_BUSCA)
    assert (estado.estado, estado.motivo) == (EstadoColetorTipo.PAUSADO, "falhas seguidas")
    [pausa] = avisador.dados(TipoAviso.AMAZON_BUSCA_PAUSADA)
    assert pausa.linhas[0] == f"Motivo: {MAX_FALHAS_SEGUIDAS} páginas seguidas com falha (bloqueio ou layout novo?)"
    assert "Admin → Serviços → Amazon (busca) → Retomar" in avisador.mensagens[-1][1]
    # o ciclo terminou pela pausa: só o aviso da pausa, sem "busca falhou" nem conclusão
    assert avisador.tipos() == [TipoAviso.AMAZON_BUSCA_PAUSADA]
    [ciclo] = ciclos(sessoes)
    assert (ciclo.status, ciclo.produtos_falha) == (StatusColeta.FALHA, MAX_FALHAS_SEGUIDAS)
    assert v.passo() == ESPERA_OCIOSA_S
    assert len(navegador.visitadas) == MAX_FALHAS_SEGUIDAS


def test_busca_com_sucesso_zera_as_falhas_seguidas(engine, sessoes, config):
    criados, urls = produtos(sessoes, *nomes(2 * MAX_FALHAS_SEGUIDAS - 1))
    meio = criados[MAX_FALHAS_SEGUIDAS - 1].id
    paginas = {u: vazia(u) if pid == meio else quebrada(u) for pid, u in urls.items()}
    v, navegador, _, avisador = varredura(engine, sessoes, config, paginas)
    for _ in range(len(criados)):
        v.passo()
    assert navegador.visitadas[MAX_FALHAS_SEGUIDAS - 1] == urls[meio]
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON_BUSCA).estado is EstadoColetorTipo.ATIVO
    assert TipoAviso.AMAZON_BUSCA_PAUSADA not in avisador.tipos()


def test_no_maximo_tres_htmls_de_falha_por_ciclo(engine, sessoes, config):
    _, urls = produtos(sessoes, *nomes(5))
    v, _, _, _ = varredura(engine, sessoes, config, {u: quebrada(u) for u in urls.values()})
    for _ in range(5):
        v.passo()
    [ciclo] = ciclos(sessoes)
    assert ciclo.produtos_falha == 5
    assert len(list((config.dir_dados / "falhas").iterdir())) == 3


def test_mensagem_do_captcha_nunca_leva_o_host_salvo(engine, sessoes, config):
    with sessoes() as s, s.begin():
        repo.obter_config_geral(s, config)
        repo.salvar_config_geral(s, {"host_publico": "10.9.8.7"}, MEIO_DIA)
    _, urls = produtos(sessoes, "a")
    [url] = urls.values()
    v, _, _, _ = varredura(engine, sessoes, config, {url: pagina_html(CAPTCHA, url=url)})
    avisador = AvisadorFake(host_publico="10.9.8.7")  # modo estrito: o host no texto faz o avisar levantar
    v._avisador = avisador
    v.passo()
    [(_, texto)] = avisador.mensagens
    assert "porta 6082" in texto and "10.9.8.7" not in texto


def test_busca_alterna_portugues_e_ingles_quando_ha_nome_en(engine, sessoes, config):
    (a,), urls = produtos(sessoes, "Caixa de Booster - Alfa")
    with sessoes() as s, s.begin():
        s.get(ProdutoLiga, a.id).nome_en = "Booster Box - Alpha"
        url_en = url_busca(repo_amz.obter_config(s), "Booster Box - Alpha")
    url_pt = urls[a.id]
    relogio = Relogio(MEIO_DIA)
    v, navegador, _, _ = varredura(
        engine, sessoes, config, {url_pt: vazia(url_pt), url_en: vazia(url_en)}, relogio=relogio
    )
    flags = []
    for _ in range(3):
        assert v.passo() == 0
        with sessoes() as s:
            flags.append(s.get(FilaAmazon, a.id).indice_termo)
        relogio.agora += timedelta(hours=3)
    assert navegador.visitadas == [url_pt, url_en, url_pt]
    assert flags == [1, 0, 1]


def test_busca_sem_nome_en_sempre_em_portugues_e_flag_continua_falso(engine, sessoes, config):
    (a,), urls = produtos(sessoes, "Caixa de Booster - Alfa")
    url = urls[a.id]
    relogio = Relogio(MEIO_DIA)
    v, navegador, _, _ = varredura(engine, sessoes, config, {url: vazia(url)}, relogio=relogio)
    for _ in range(2):
        assert v.passo() == 0
        relogio.agora += timedelta(hours=3)
    assert navegador.visitadas == [url, url]
    with sessoes() as s:
        assert s.get(FilaAmazon, a.id).indice_termo == 0


@pytest.mark.parametrize("nome_en", ["Caixa de Booster: Alfa", "  -  "])
def test_nome_en_igual_ao_portugues_ou_vazio_nao_vira_busca_em_ingles(engine, sessoes, config, nome_en):
    (a,), urls = produtos(sessoes, "Caixa de Booster - Alfa")
    with sessoes() as s, s.begin():
        s.get(ProdutoLiga, a.id).nome_en = nome_en
    url = urls[a.id]
    relogio = Relogio(MEIO_DIA)
    v, navegador, _, _ = varredura(engine, sessoes, config, {url: vazia(url)}, relogio=relogio)
    for _ in range(3):
        assert v.passo() == 0
        with sessoes() as s:
            assert s.get(FilaAmazon, a.id).indice_termo == 0
        relogio.agora += timedelta(hours=3)
    assert navegador.visitadas == [url, url, url]


def test_flag_do_termo_tambem_alterna_quando_a_busca_falha_no_parser(engine, sessoes, config):
    (a,), urls = produtos(sessoes, "Caixa de Booster - Alfa")
    with sessoes() as s, s.begin():
        s.get(ProdutoLiga, a.id).nome_en = "Booster Box - Alpha"
        url_en = url_busca(repo_amz.obter_config(s), "Booster Box - Alpha")
    url_pt = urls[a.id]
    quebrada = lambda u: pagina_html("<html>novo</html>", url=u)
    relogio = Relogio(MEIO_DIA)
    v, navegador, _, _ = varredura(
        engine, sessoes, config, {url_pt: quebrada(url_pt), url_en: quebrada(url_en)}, relogio=relogio
    )
    flags = []
    for _ in range(2):
        v.passo()
        with sessoes() as s:
            flags.append(s.get(FilaAmazon, a.id).indice_termo)
        relogio.agora += timedelta(hours=3)
    assert navegador.visitadas == [url_pt, url_en]
    assert flags == [1, 0]


def test_ciclo_ok_avisa_busca_concluida_e_resolve_a_falha(engine, sessoes, config):
    _, urls = produtos(sessoes, "a")
    [url] = urls.values()
    v, _, _, avisador = varredura(engine, sessoes, config, {url: vazia(url)})
    v.passo()
    [(tipo, chave, dados)] = avisador.avisos
    assert (tipo, chave) == (TipoAviso.AMAZON_BUSCA_CONCLUIDA, CHAVE_GERAL)
    assert dados.titulo_extra.startswith("ciclo ") and dados.linhas == ("Buscas: 1 ok · 0 falhas", "Duração: menos de 1 min")
    assert (TipoAviso.AMAZON_BUSCA_FALHOU, CHAVE_GERAL) in avisador.resolvidos


def test_ciclo_parcial_avisa_busca_parcial(engine, sessoes, config):
    with sessoes() as s, s.begin():
        aplicar_config(s, {"limite_falha_pct": 60}, MEIO_DIA)
    (a, b), urls = produtos(sessoes, "a", "b")
    relogio = Relogio(MEIO_DIA)
    v, _, _, avisador = varredura(
        engine, sessoes, config, {urls[a.id]: vazia(urls[a.id]), urls[b.id]: quebrada(urls[b.id])}, relogio
    )
    v.passo()
    relogio.agora += timedelta(minutes=30)
    v.passo()
    [(tipo, _, dados)] = avisador.avisos
    assert tipo is TipoAviso.AMAZON_BUSCA_PARCIAL
    assert dados.linhas == ("Buscas: 1 ok · 1 falha", "Duração: 30 min")
    assert (TipoAviso.AMAZON_BUSCA_FALHOU, CHAVE_GERAL) in avisador.resolvidos


def test_janela_que_fecha_no_meio_do_ciclo_nao_avisa_conclusao(engine, sessoes, config):
    _, urls = produtos(sessoes, "a", "b")
    relogio = Relogio(MEIO_DIA)
    v, navegador, _, avisador = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()}, relogio)
    assert v.passo() == 0  # um dos dois buscado; o outro fica pendente
    relogio.agora = datetime(2026, 10, 15, 23, 0, tzinfo=SP)  # fora da janela: o ciclo fecha pela metade
    assert v.passo() == ESPERA_OCIOSA_S
    [ciclo] = ciclos(sessoes)
    assert ciclo.status is not StatusColeta.RODANDO and len(navegador.visitadas) == 1
    assert avisador.avisos == []


def test_ciclo_que_termina_com_a_pausa_so_avisa_a_pausa(engine, sessoes, config):
    _, urls = produtos(sessoes, *nomes(MAX_FALHAS_SEGUIDAS))  # a última busca fecha o ciclo e pausa
    v, _, _, avisador = varredura(engine, sessoes, config, {u: quebrada(u) for u in urls.values()})
    for _ in range(MAX_FALHAS_SEGUIDAS):
        v.passo()
    [ciclo] = ciclos(sessoes)
    assert ciclo.status is StatusColeta.FALHA
    assert avisador.tipos() == [TipoAviso.AMAZON_BUSCA_PAUSADA]


def test_passo_com_a_amazon_ativa_resolve_a_pausa(engine, sessoes, config):
    v, _, _, avisador = varredura(engine, sessoes, config, {})
    with sessoes() as s, s.begin():
        repo.pausar(s, "erros seguidos", MEIO_DIA, COLETOR_AMAZON_BUSCA)
    v.passo()
    assert (TipoAviso.AMAZON_BUSCA_PAUSADA, CHAVE_GERAL) not in avisador.resolvidos
    with sessoes() as s, s.begin():
        repo.retomar(s, MEIO_DIA, COLETOR_AMAZON_BUSCA)
    v.passo()
    assert (TipoAviso.AMAZON_BUSCA_PAUSADA, CHAVE_GERAL) in avisador.resolvidos


def test_executar_passo_avisa_erro_e_o_passo_ok_seguinte_resolve(engine, sessoes, config, monkeypatch):
    v, _, _, avisador = varredura(engine, sessoes, config, {})

    def quebrar():
        raise RuntimeError("navegador fechou")

    monkeypatch.setattr(v, "passo", quebrar)
    assert v.executar_passo() == ESPERA_ERRO_S
    [(tipo, _, dados)] = avisador.avisos
    assert tipo is TipoAviso.AMAZON_BUSCA_ERRO and dados.linhas == ("Erro: RuntimeError('navegador fechou')",)
    assert (TipoAviso.AMAZON_BUSCA_ERRO, CHAVE_GERAL) not in avisador.resolvidos
    monkeypatch.setattr(v, "passo", lambda: 0)
    assert v.executar_passo() == 0
    assert (TipoAviso.AMAZON_BUSCA_ERRO, CHAVE_GERAL) in avisador.resolvidos


def _em_seca(sessoes, produto_id, termos, nome_en=None):
    """Produto 8 dias na fila sem par novo, com `termos` guardados. Devolve {termo: url}."""
    with sessoes() as s, s.begin():
        produto = s.get(ProdutoLiga, produto_id)
        produto.nome_en = nome_en
        repo_amz.sincronizar_fila(s, MEIO_DIA - timedelta(days=8))
        if termos:
            repo_termos.guardar_termos(s, produto_id, termos, MEIO_DIA - timedelta(days=1))
        cfg = repo_amz.obter_config(s)
        nomes = [produto.nome, *([nome_en] if nome_en else []), *(termo for termo, _ in termos)]
        return {nome: url_busca(cfg, nome) for nome in nomes}


DUAS_HORAS = timedelta(hours=2, minutes=1)  # sem candidato há 7 dias o intervalo dobra (120 min)


def test_em_seca_a_fila_alterna_nome_ingles_e_termos(engine, sessoes, config):
    (a,), _ = produtos(sessoes, "Caixa de Booster - Alfa")
    urls = _em_seca(sessoes, a.id, [("alfa booster box", "en"), ("caixa alfa lacrada", "pt")], "Booster Box - Alpha")
    relogio = Relogio(MEIO_DIA)
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()}, relogio=relogio)
    for _ in range(5):
        assert v.passo() == 0
        relogio.agora += DUAS_HORAS
    assert navegador.visitadas == [
        urls["Caixa de Booster - Alfa"], urls["Booster Box - Alpha"], urls["alfa booster box"],
        urls["caixa alfa lacrada"], urls["Caixa de Booster - Alfa"],
    ]


def test_em_seca_sem_termos_segue_com_o_nome_normal(engine, sessoes, config):
    (a,), _ = produtos(sessoes, "Caixa de Booster - Alfa")
    urls = _em_seca(sessoes, a.id, [], "Booster Box - Alpha")
    relogio = Relogio(MEIO_DIA)
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()}, relogio=relogio)
    for _ in range(3):
        assert v.passo() == 0
        relogio.agora += DUAS_HORAS
    pt, en = urls["Caixa de Booster - Alfa"], urls["Booster Box - Alpha"]
    assert navegador.visitadas == [pt, en, pt]


def test_candidato_novo_na_seca_volta_ao_nome_normal(engine, sessoes, config):
    (a,), _ = produtos(sessoes, "Caixa de Booster - Alfa")
    urls = _em_seca(sessoes, a.id, [("alfa booster box", "en")], "Booster Box - Alpha")
    pt, en, alternativo = urls["Caixa de Booster - Alfa"], urls["Booster Box - Alpha"], urls["alfa booster box"]
    com_anuncio = pagina_html(html_busca(cartao_busca("B0NOVO0001", "Caixa Alfa", "R$ 900,00")), url=pt)
    relogio = Relogio(MEIO_DIA)
    paginas = {pt: com_anuncio, en: vazia(en), alternativo: vazia(alternativo)}
    v, navegador, _, _ = varredura(engine, sessoes, config, paginas, relogio=relogio)
    for _ in range(3):
        assert v.passo() == 0
        relogio.agora += DUAS_HORAS
    assert navegador.visitadas == [pt, en, pt]  # o termo alternativo não entra mais
    with sessoes() as s:
        assert s.get(FilaAmazon, a.id).ultimo_par_novo_em == MEIO_DIA
        assert [t.termo for t in repo_termos.termos_do_produto(s, a.id)] == ["alfa booster box"]  # guardados


def test_indice_maior_que_a_sequencia_nao_quebra(engine, sessoes, config):
    (a,), urls = produtos(sessoes, "Caixa de Booster - Alfa")
    with sessoes() as s, s.begin():
        repo_amz.sincronizar_fila(s, MEIO_DIA)
        s.get(FilaAmazon, a.id).indice_termo = 4  # sobra de uma seca que acabou
    url = urls[a.id]
    v, navegador, _, _ = varredura(engine, sessoes, config, {url: vazia(url)})
    assert v.passo() == 0 and navegador.visitadas == [url]
    with sessoes() as s:
        assert s.get(FilaAmazon, a.id).indice_termo == 0


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


def test_busca_nunca_le_ofertas_nem_abre_o_carrinho(engine, sessoes, config):
    """Anúncio vencido no monitor, candidata ao checkout e item preso no carrinho: a busca ignora tudo."""
    _, anuncio_id = confirmado(sessoes, "cand", "B0CAND0001", "700.00")
    confirmado(sessoes, "venc", "B0VENC0001")  # nunca lido: vencido
    with sessoes() as s, s.begin():
        repo_amz.registrar_conferencia(
            s, em=MEIO_DIA - timedelta(minutes=5), anuncio_id=anuncio_id, vendedor_nome="Amazon.com.br",
            preco_anunciado=Decimal("700.00"), itens=None, frete=None, impostos=None, total=None,
            situacao=SituacaoCheckout.FALHA, motivo="em andamento", item_removido=False,
        )
    url = livre(sessoes, "livre")
    paginas = {url: vazia(url), URL_CARRINHO: carrinho(), url_ofertas("B0VENC0001"): vazia(url_ofertas("B0VENC0001"))}
    v, navegador, _, _ = varredura(engine, sessoes, config, paginas)
    assert v.passo() == 0
    assert v.passo() == ESPERA_OCIOSA_S
    assert navegador.visitadas == [url] and navegador.cliques == []
    with sessoes() as s:
        assert [c.item_removido for c in s.scalars(select(ConferenciaCheckout))] == [False]


def test_busca_segue_a_propria_janela_e_nao_a_do_monitor(engine, sessoes, config):
    url = livre(sessoes, "livre")
    with sessoes() as s, s.begin():
        aplicar_config(s, {"monitor_janela_inicio": time(14, 0)}, MEIO_DIA)  # monitor fechado ao meio-dia
    v, navegador, _, _ = varredura(engine, sessoes, config, {url: vazia(url)})
    assert v.passo() == 0 and navegador.visitadas == [url]
    url2 = livre(sessoes, "livre2")  # vencido: só a janela da busca o segura
    with sessoes() as s, s.begin():
        aplicar_config(s, {"monitor_janela_inicio": time(8, 0), "janela_inicio": time(14, 0)}, MEIO_DIA)
    v2, navegador2, _, _ = varredura(engine, sessoes, config, {url2: vazia(url2)})
    assert v2.passo() == ESPERA_OCIOSA_S and navegador2.visitadas == []


def test_busca_segue_o_proprio_teto_e_nao_o_do_monitor(engine, sessoes, config):
    _, urls = produtos(sessoes, "a", "b")
    with sessoes() as s, s.begin():
        aplicar_config(s, {"max_buscas_hora": 1, "monitor_max_paginas_hora": 1000}, MEIO_DIA)
    relogio = Relogio(MEIO_DIA)
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()}, relogio)
    assert v.passo() == 0
    assert v.passo() == ESPERA_OCIOSA_S
    relogio.agora += timedelta(minutes=61)
    assert v.passo() == 0
    assert len(navegador.visitadas) == 2
