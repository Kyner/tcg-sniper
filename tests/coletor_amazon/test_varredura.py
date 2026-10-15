import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fakes import (
    NavegadorFake,
    NotificadorFake,
    cartao_busca,
    criar_anuncio,
    criar_preco_liga,
    criar_produto,
    html_busca,
    html_produto_amazon,
    pagina_html,
)
from sqlalchemy import select

from tcg_sniper.coletor_amazon.busca import url_busca
from tcg_sniper.coletor_amazon.config import aplicar_config
from tcg_sniper.coletor_amazon.parsers import url_produto
from tcg_sniper.coletor_amazon.varredura import (
    ESPERA_ERRO_S,
    ESPERA_OCIOSA_S,
    MAX_FALHAS_SEGUIDAS,
    VarreduraAmazon,
)
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    AnuncioAmazon,
    Coleta,
    EstadoColetorTipo,
    FilaAmazon,
    StatusCasamento,
    StatusColeta,
    TipoColeta,
)
from tcg_sniper.notificador.base import Destino

SP = ZoneInfo("America/Sao_Paulo")
MEIO_DIA = datetime(2026, 10, 15, 12, 0, tzinfo=SP)
CAPTCHA = '<html><body><form action="/errors/validateCaptcha"></form></body></html>'


class Relogio:
    def __init__(self, agora):
        self.agora = agora

    def __call__(self):
        return self.agora


class FabricaFake:
    def __init__(self, navegador):
        self.navegador = navegador
        self.abertos = 0
        self.fechados = 0

    def __call__(self):
        fabrica = self

        class Contexto:
            def __enter__(self):
                fabrica.abertos += 1
                return fabrica.navegador

            def __exit__(self, *_exc):
                fabrica.fechados += 1

        return Contexto()


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
    navegador = NavegadorFake(paginas)
    fabrica = FabricaFake(navegador)
    notificador = NotificadorFake()
    v = VarreduraAmazon(
        engine,
        sessoes,
        fabrica,
        notificador,
        config,
        relogio=relogio or Relogio(MEIO_DIA),
        rng=random.Random(1),
        dormir=lambda _: None,
    )
    return v, navegador, fabrica, notificador


def ciclos(sessoes):
    with sessoes() as s:
        return list(s.scalars(select(Coleta).where(Coleta.tipo == TipoColeta.AMAZON).order_by(Coleta.id)))


def vazia(url):
    return pagina_html(html_busca(), url=url)


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


def test_so_ausente_conferido_nao_conta_como_candidato(engine, sessoes, config):
    (a,), urls = produtos(sessoes, "a")
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B0AUSENTE1", produto=s.get(type(a), a.id), status=StatusCasamento.CONFIRMADO)
    paginas = {
        urls[a.id]: vazia(urls[a.id]),
        url_produto("B0AUSENTE1"): pagina_html(html_produto_amazon("Item", "R$ 900,00", "Loja", "Loja")),
    }
    v, navegador, _, _ = varredura(engine, sessoes, config, paginas)
    v.passo()
    assert url_produto("B0AUSENTE1") in navegador.visitadas
    with sessoes() as s:
        fila = s.get(FilaAmazon, a.id)
    assert fila.ultimo_candidato_em is None
    assert fila.proxima_busca_em == MEIO_DIA + timedelta(minutes=60)


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
        repo.pausar(s, "manual", MEIO_DIA, COLETOR_AMAZON)
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()})
    assert v.passo() == ESPERA_OCIOSA_S
    assert navegador.visitadas == []


def test_captcha_pausa_avisa_e_mantem_o_navegador(engine, sessoes, config):
    _, urls = produtos(sessoes, "a")
    [url] = urls.values()
    v, _, fabrica, notificador = varredura(engine, sessoes, config, {url: pagina_html(CAPTCHA, url=url)})
    assert v.passo() == ESPERA_OCIOSA_S
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.PAUSADO_DESAFIO
    [ciclo] = ciclos(sessoes)
    assert ciclo.status is StatusColeta.PAUSADA_DESAFIO
    [(destino, texto)] = notificador.mensagens
    assert destino is Destino.ADMIN and ":6081/vnc.html" in texto
    assert fabrica.fechados == 0


def test_retomar_continua_no_mesmo_navegador(engine, sessoes, config):
    _, urls = produtos(sessoes, "a")
    [url] = urls.values()
    v, navegador, fabrica, _ = varredura(engine, sessoes, config, {url: [pagina_html(CAPTCHA, url=url), vazia(url)]})
    v.passo()
    with sessoes() as s, s.begin():
        repo.retomar(s, MEIO_DIA, COLETOR_AMAZON)
    assert v.passo() == 0
    assert navegador.visitadas == [url, url]
    assert fabrica.abertos == 1


def test_falha_de_layout_conta_falha_e_ciclo_falho_avisa(engine, sessoes, config):
    _, urls = produtos(sessoes, "a")
    [url] = urls.values()
    v, _, _, notificador = varredura(engine, sessoes, config, {url: pagina_html("<html>novo</html>", url=url)})
    v.passo()
    [ciclo] = ciclos(sessoes)
    assert (ciclo.status, ciclo.produtos_falha) == (StatusColeta.FALHA, 1)
    assert any(d is Destino.ADMIN and "falhou" in t for d, t in notificador.mensagens)


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
    from tcg_sniper.coletor_amazon import varredura as modulo

    def quebrar(*_a, **_k):
        raise RuntimeError("banco caiu")

    monkeypatch.setattr(modulo, "processar_produto", quebrar)
    _, urls = produtos(sessoes, "a")
    relogio = Relogio(MEIO_DIA)
    v, _, fabrica, notificador = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()}, relogio)
    esperas = []
    for _ in range(3):
        try:
            v.passo()
        except RuntimeError as erro:
            esperas.append(v.tratar_erro(erro))
        relogio.agora += timedelta(hours=2)  # o produto que quebra é reagendado para daqui a 60 min
    assert esperas == [ESPERA_ERRO_S, ESPERA_ERRO_S, ESPERA_OCIOSA_S]
    with sessoes() as s:
        estado = repo.obter_estado(s, coletor=COLETOR_AMAZON)
    assert (estado.estado, estado.motivo) == (EstadoColetorTipo.PAUSADO, "erros seguidos")
    assert len([m for m in notificador.mensagens if "falhou" not in m[1]]) == 3
    assert fabrica.fechados == 3


def test_inicializar_so_marca_os_ciclos_da_amazon(engine, sessoes, config):
    with sessoes() as s, s.begin():
        liga = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, MEIO_DIA)
        amazon = repo.iniciar_coleta(s, TipoColeta.AMAZON, MEIO_DIA)
    v, _, _, notificador = varredura(engine, sessoes, config, {})
    v.inicializar()
    with sessoes() as s:
        assert s.get(Coleta, liga.id).status is StatusColeta.RODANDO
        assert s.get(Coleta, amazon.id).status is StatusColeta.FALHA
    assert len(notificador.mensagens) == 1


@pytest.mark.parametrize("hora", [7, 22])
def test_janela_nas_bordas(engine, sessoes, config, hora):
    _, urls = produtos(sessoes, "a")
    relogio = Relogio(datetime(2026, 10, 15, hora, 0, tzinfo=SP) + timedelta(minutes=-20 if hora == 7 else 20))
    v, navegador, _, _ = varredura(engine, sessoes, config, {u: vazia(u) for u in urls.values()}, relogio)
    assert v.passo() == ESPERA_OCIOSA_S
    assert navegador.visitadas == []


def test_produto_que_quebra_nao_trava_a_fila(engine, sessoes, config, monkeypatch):
    from tcg_sniper.coletor_amazon import varredura as modulo

    (a, b), urls = produtos(sessoes, "a", "b")
    real = modulo.processar_produto

    def quebra_so_a(contexto, produto):
        if produto.id == a.id:
            raise RuntimeError("bug no parser")
        return real(contexto, produto)

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
    from tcg_sniper.coletor_amazon import varredura as modulo

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
    from tcg_sniper.coletor_amazon import varredura as modulo

    def quebrar(*_a, **_k):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(modulo.repo, "pausar", quebrar)
    v, _, _, notificador = varredura(engine, sessoes, config, {})
    esperas = [v.tratar_erro(RuntimeError("x")) for _ in range(3)]
    assert esperas == [ESPERA_ERRO_S] * 3
    assert len(notificador.mensagens) == 3


def quebrada(url):
    return pagina_html("<html></html>", url=url)


def nomes(n):
    return [f"p{i:02d}" for i in range(n)]  # mesmo preço e vencimento: a fila segue a ordem de id


def test_falhas_seguidas_pausam_a_busca(engine, sessoes, config):
    _, urls = produtos(sessoes, *nomes(MAX_FALHAS_SEGUIDAS + 1))
    v, navegador, _, notificador = varredura(engine, sessoes, config, {u: quebrada(u) for u in urls.values()})
    for _ in range(MAX_FALHAS_SEGUIDAS):
        v.passo()
    with sessoes() as s:
        estado = repo.obter_estado(s, coletor=COLETOR_AMAZON)
    assert (estado.estado, estado.motivo) == (EstadoColetorTipo.PAUSADO, "falhas seguidas")
    avisos = [t for d, t in notificador.mensagens if d is Destino.ADMIN and "seguidas com falha" in t]
    assert len(avisos) == 1
    assert "Retomar (Amazon)" in avisos[0]
    [ciclo] = ciclos(sessoes)
    assert (ciclo.status, ciclo.produtos_falha) == (StatusColeta.FALHA, MAX_FALHAS_SEGUIDAS)
    assert v.passo() == ESPERA_OCIOSA_S
    assert len(navegador.visitadas) == MAX_FALHAS_SEGUIDAS


def test_busca_com_sucesso_zera_as_falhas_seguidas(engine, sessoes, config):
    criados, urls = produtos(sessoes, *nomes(2 * MAX_FALHAS_SEGUIDAS - 1))
    meio = criados[MAX_FALHAS_SEGUIDAS - 1].id
    paginas = {u: vazia(u) if pid == meio else quebrada(u) for pid, u in urls.items()}
    v, navegador, _, notificador = varredura(engine, sessoes, config, paginas)
    for _ in range(len(criados)):
        v.passo()
    assert navegador.visitadas[MAX_FALHAS_SEGUIDAS - 1] == urls[meio]
    with sessoes() as s:
        assert repo.obter_estado(s, coletor=COLETOR_AMAZON).estado is EstadoColetorTipo.ATIVO
    assert not any("seguidas com falha" in t for _, t in notificador.mensagens)


def test_no_maximo_tres_htmls_de_falha_por_ciclo(engine, sessoes, config):
    _, urls = produtos(sessoes, *nomes(5))
    v, _, _, _ = varredura(engine, sessoes, config, {u: quebrada(u) for u in urls.values()})
    for _ in range(5):
        v.passo()
    [ciclo] = ciclos(sessoes)
    assert ciclo.produtos_falha == 5
    assert len(list((config.dir_dados / "falhas").iterdir())) == 3


def test_host_salvo_na_tela_vale_na_mensagem_do_captcha(engine, sessoes, config):
    _, urls = produtos(sessoes, "a")
    [url] = urls.values()
    with sessoes() as s, s.begin():
        repo.obter_config_geral(s, config)
        repo.salvar_config_geral(s, {"host_publico": "10.9.8.7"}, MEIO_DIA)
    v, _, _, notificador = varredura(engine, sessoes, config, {url: pagina_html(CAPTCHA, url=url)})
    v.passo()
    [(_, texto)] = notificador.mensagens
    assert "http://10.9.8.7:6081/vnc.html" in texto
