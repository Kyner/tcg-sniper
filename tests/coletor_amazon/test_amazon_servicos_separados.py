"""Os dois laços sobre o mesmo banco, cada um com o próprio navegador: um não para nem atrasa o outro."""

from datetime import time, timedelta

from fakes import pagina_html
from fakes_varredura import CAPTCHA, MEIO_DIA, confirmado, criar_laco, livre, ofertas, vazia

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, TipoAviso
from tcg_sniper.coletor_amazon.config import aplicar_config
from tcg_sniper.coletor_amazon.parsers import url_ofertas
from tcg_sniper.coletor_amazon.varredura_base import ESPERA_OCIOSA_S
from tcg_sniper.coletor_amazon.varredura_busca import VarreduraBusca
from tcg_sniper.coletor_amazon.varredura_monitor import VarreduraMonitor
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    COLETOR_AMAZON_BUSCA,
    Coleta,
    EstadoColetorTipo,
    StatusColeta,
    TipoColeta,
)


def dois_lacos(engine, sessoes, config, paginas):
    busca, nav_busca, _, av_busca, relogio = criar_laco(VarreduraBusca, engine, sessoes, config, paginas)
    monitor, nav_monitor, _, av_monitor, _ = criar_laco(
        VarreduraMonitor, engine, sessoes, config, paginas, relogio=relogio
    )
    return busca, nav_busca, av_busca, monitor, nav_monitor, av_monitor, relogio


def estado(sessoes, coletor):
    with sessoes() as s:
        return repo.obter_estado(s, coletor=coletor).estado


def test_busca_roda_com_o_monitor_sempre_atrasado(engine, sessoes, config):
    """O problema de 2026-10-19: com o monitor sempre com anúncio vencido, a busca quase não rodava."""
    asins = ("B0VENC0001", "B0VENC0002", "B0VENC0003")
    for i, asin in enumerate(asins):
        confirmado(sessoes, f"venc{i}", asin)  # nunca lidos: vencidos
    urls = [livre(sessoes, nome) for nome in ("livre1", "livre2")]
    paginas = {url_ofertas(a): ofertas(a, "R$ 990,00") for a in asins} | {u: vazia(u) for u in urls}
    busca, nav_busca, _, monitor, nav_monitor, _, relogio = dois_lacos(engine, sessoes, config, paginas)
    for _ in range(2):
        assert monitor.passo() == 0  # sempre há anúncio vencido
        assert busca.passo() == 0
        relogio.agora += timedelta(minutes=16)  # intervalo de 15 min: tudo vence de novo
    assert sorted(nav_busca.visitadas) == sorted(urls)
    assert len(nav_monitor.visitadas) == 2 and set(nav_monitor.visitadas) <= {url_ofertas(a) for a in asins}


def test_captcha_na_busca_nao_para_o_monitor(engine, sessoes, config):
    confirmado(sessoes, "venc", "B0VENC0001")
    url = livre(sessoes, "livre")
    paginas = {url: pagina_html(CAPTCHA, url=url), url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00")}
    busca, _, av_busca, monitor, nav_monitor, av_monitor, _ = dois_lacos(engine, sessoes, config, paginas)
    assert busca.passo() == ESPERA_OCIOSA_S
    assert estado(sessoes, COLETOR_AMAZON_BUSCA) is EstadoColetorTipo.PAUSADO_DESAFIO
    assert estado(sessoes, COLETOR_AMAZON) is EstadoColetorTipo.ATIVO
    assert monitor.passo() == 0 and nav_monitor.visitadas == [url_ofertas("B0VENC0001")]
    assert av_busca.tipos() == [TipoAviso.AMAZON_BUSCA_CAPTCHA]
    [(_, texto)] = av_busca.mensagens
    assert "porta 6082" in texto
    # a leitura limpa do monitor fecha só o CAPTCHA dele; o da busca continua aberto
    assert (TipoAviso.AMAZON_CAPTCHA, CHAVE_GERAL) in av_monitor.resolvidos
    assert (TipoAviso.AMAZON_BUSCA_CAPTCHA, CHAVE_GERAL) not in av_monitor.resolvidos + av_busca.resolvidos


def test_captcha_no_monitor_nao_para_a_busca(engine, sessoes, config):
    confirmado(sessoes, "venc", "B0VENC0001")
    url = livre(sessoes, "livre")
    oferta = url_ofertas("B0VENC0001")
    paginas = {url: vazia(url), oferta: pagina_html(CAPTCHA, url=oferta)}
    busca, nav_busca, av_busca, monitor, _, av_monitor, _ = dois_lacos(engine, sessoes, config, paginas)
    assert monitor.passo() == ESPERA_OCIOSA_S
    assert estado(sessoes, COLETOR_AMAZON) is EstadoColetorTipo.PAUSADO_DESAFIO
    assert estado(sessoes, COLETOR_AMAZON_BUSCA) is EstadoColetorTipo.ATIVO
    assert busca.passo() == 0 and nav_busca.visitadas == [url]
    assert av_monitor.tipos() == [TipoAviso.AMAZON_CAPTCHA]
    assert (TipoAviso.AMAZON_BUSCA_CAPTCHA, CHAVE_GERAL) in av_busca.resolvidos
    assert (TipoAviso.AMAZON_CAPTCHA, CHAVE_GERAL) not in av_busca.resolvidos


def test_busca_desligada_em_servicos_o_monitor_segue(engine, sessoes, config):
    confirmado(sessoes, "venc", "B0VENC0001")
    url = livre(sessoes, "livre")
    with sessoes() as s, s.begin():
        repo.pausar(s, "pausado no admin", MEIO_DIA, COLETOR_AMAZON_BUSCA)
    paginas = {url: vazia(url), url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00")}
    busca, nav_busca, _, monitor, nav_monitor, _, _ = dois_lacos(engine, sessoes, config, paginas)
    assert busca.passo() == ESPERA_OCIOSA_S and nav_busca.visitadas == []
    assert monitor.passo() == 0 and nav_monitor.visitadas == [url_ofertas("B0VENC0001")]


def test_tetos_independentes(engine, sessoes, config):
    for asin in ("B0VENC0001", "B0VENC0002"):
        confirmado(sessoes, asin, asin)
    urls = [livre(sessoes, nome) for nome in ("livre1", "livre2")]
    with sessoes() as s, s.begin():
        aplicar_config(s, {"max_buscas_hora": 1, "monitor_max_paginas_hora": 1}, MEIO_DIA)
    paginas = {url_ofertas(a): ofertas(a, "R$ 990,00") for a in ("B0VENC0001", "B0VENC0002")} | {
        u: vazia(u) for u in urls
    }
    busca, nav_busca, _, monitor, nav_monitor, _, relogio = dois_lacos(engine, sessoes, config, paginas)
    assert busca.passo() == 0 and monitor.passo() == 0
    assert busca.passo() == ESPERA_OCIOSA_S and monitor.passo() == ESPERA_OCIOSA_S
    assert (len(nav_busca.visitadas), len(nav_monitor.visitadas)) == (1, 1)
    relogio.agora += timedelta(minutes=61)
    assert busca.passo() == 0 and monitor.passo() == 0


def test_janelas_independentes(engine, sessoes, config):
    confirmado(sessoes, "venc", "B0VENC0001")
    url = livre(sessoes, "livre")
    with sessoes() as s, s.begin():
        aplicar_config(s, {"janela_inicio": time(14, 0)}, MEIO_DIA)  # só a busca fechada ao meio-dia
    paginas = {url: vazia(url), url_ofertas("B0VENC0001"): ofertas("B0VENC0001", "R$ 990,00")}
    busca, nav_busca, _, monitor, nav_monitor, _, _ = dois_lacos(engine, sessoes, config, paginas)
    assert busca.passo() == ESPERA_OCIOSA_S and nav_busca.visitadas == []
    assert monitor.passo() == 0 and nav_monitor.visitadas == [url_ofertas("B0VENC0001")]


def test_inicializar_do_monitor_nao_fecha_o_ciclo_da_busca(engine, sessoes, config):
    with sessoes() as s, s.begin():
        ciclo_id = repo.iniciar_coleta(s, TipoColeta.AMAZON, MEIO_DIA).id
    monitor, _, _, avisador, _ = criar_laco(VarreduraMonitor, engine, sessoes, config, {})
    monitor.inicializar()
    with sessoes() as s:
        assert s.get(Coleta, ciclo_id).status is StatusColeta.RODANDO
    assert avisador.avisos == []
