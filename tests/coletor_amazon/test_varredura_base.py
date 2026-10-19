from datetime import timedelta

import pytest
from fakes_varredura import MEIO_DIA, criar_laco

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, TipoAviso
from tcg_sniper.coletor_amazon.varredura_base import (
    ESPERA_ERRO_S,
    ESPERA_OCIOSA_S,
    ORIGEM_BUSCA,
    ORIGEM_MONITOR,
    VarreduraBase,
    dados_captcha,
)
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import COLETOR_AMAZON, COLETOR_AMAZON_BUSCA, EstadoColetorTipo


class LacoDaBusca(VarreduraBase):
    origem = ORIGEM_BUSCA
    acao = staticmethod(lambda: 0)

    def passo(self):
        return self.acao()


class LacoDoMonitor(LacoDaBusca):
    origem = ORIGEM_MONITOR


def estado(sessoes, coletor):
    with sessoes() as s:
        return repo.obter_estado(s, coletor=coletor)


def quebrar():
    raise RuntimeError("navegador fechou")


def test_tres_erros_seguidos_pausam_so_a_propria_origem(engine, sessoes, config, monkeypatch):
    laco, _, _, avisador, _ = criar_laco(LacoDaBusca, engine, sessoes, config, {})
    monkeypatch.setattr(laco, "passo", quebrar)
    assert [laco.executar_passo() for _ in range(3)] == [ESPERA_ERRO_S, ESPERA_ERRO_S, ESPERA_OCIOSA_S]
    busca = estado(sessoes, COLETOR_AMAZON_BUSCA)
    assert (busca.estado, busca.motivo) == (EstadoColetorTipo.PAUSADO, "erros seguidos")
    assert estado(sessoes, COLETOR_AMAZON).estado is EstadoColetorTipo.ATIVO
    assert avisador.tipos() == [
        TipoAviso.AMAZON_BUSCA_ERRO,
        TipoAviso.AMAZON_BUSCA_ERRO,
        TipoAviso.AMAZON_BUSCA_PAUSADA,
    ]
    assert avisador.dados(TipoAviso.AMAZON_BUSCA_PAUSADA)[0].linhas[1] == (
        "Com a busca pausada, o monitor e a conferência seguem"
    )


def test_passo_ok_resolve_so_o_erro_da_propria_origem(engine, sessoes, config):
    laco, _, _, avisador, _ = criar_laco(LacoDoMonitor, engine, sessoes, config, {})
    assert laco.executar_passo() == 0
    assert (TipoAviso.AMAZON_ERRO, CHAVE_GERAL) in avisador.resolvidos
    assert (TipoAviso.AMAZON_BUSCA_ERRO, CHAVE_GERAL) not in avisador.resolvidos


def test_desafio_pausa_a_origem_e_avisa_com_o_efeito_e_os_extras(engine, sessoes, config):
    laco, _, _, avisador, _ = criar_laco(LacoDoMonitor, engine, sessoes, config, {})
    laco._registrar_desafio("https://www.amazon.com.br/gp/cart/view.html", ("linha extra",))
    assert estado(sessoes, COLETOR_AMAZON).estado is EstadoColetorTipo.PAUSADO_DESAFIO
    assert estado(sessoes, COLETOR_AMAZON_BUSCA).estado is EstadoColetorTipo.ATIVO
    [(tipo, chave, dados)] = avisador.avisos
    assert (tipo, chave) == (TipoAviso.AMAZON_CAPTCHA, CHAVE_GERAL)
    assert dados.linhas == (
        "Página: /gp/cart/view.html",
        "Monitor e conferência pausados até você retomar; a busca segue",
        "linha extra",
    )


def test_inicio_do_passo_resolve_a_pausa_so_da_propria_origem(engine, sessoes, config):
    laco, _, _, avisador, _ = criar_laco(LacoDaBusca, engine, sessoes, config, {})
    with sessoes() as s, s.begin():
        repo.pausar(s, "falhas seguidas", MEIO_DIA, COLETOR_AMAZON_BUSCA)
    _, situacao = laco._inicio_do_passo(MEIO_DIA)
    assert situacao is EstadoColetorTipo.PAUSADO and avisador.resolvidos == []
    with sessoes() as s, s.begin():
        repo.retomar(s, MEIO_DIA, COLETOR_AMAZON_BUSCA)
    _, situacao = laco._inicio_do_passo(MEIO_DIA)
    assert situacao is EstadoColetorTipo.ATIVO
    assert avisador.resolvidos == [(TipoAviso.AMAZON_BUSCA_PAUSADA, CHAVE_GERAL)]


def test_pausa_que_o_banco_recusa_avisa_e_espera_15_min(engine, sessoes, config, monkeypatch):
    from tcg_sniper.coletor_amazon import varredura_base as modulo

    def recusar(*_a, **_k):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(modulo.repo, "pausar", recusar)
    laco, _, _, avisador, _ = criar_laco(LacoDaBusca, engine, sessoes, config, {})
    chamadas = []
    assert laco._pausar_servico("falhas seguidas", "motivo x", ao_pausar=lambda: chamadas.append(1)) == ESPERA_ERRO_S
    assert chamadas == []  # sem pausa registrada, o gancho (fechar o ciclo) não roda
    assert avisador.dados(TipoAviso.AMAZON_BUSCA_PAUSADA)[0].linhas == (
        "Motivo: motivo x",
        "Não consegui registrar a pausa no banco: nova tentativa em 15 min",
    )


def test_janela_e_sorteada_uma_vez_por_tipo_e_dia(engine, sessoes, config):
    laco, _, _, _, _ = criar_laco(LacoDaBusca, engine, sessoes, config, {})
    with sessoes() as s:
        from tcg_sniper.db import repositorio_amazon as repo_amz

        cfg = repo_amz.obter_config(s)
    a = laco._janela(MEIO_DIA, "busca", cfg.janela_inicio, cfg.janela_fim)
    assert laco._janela(MEIO_DIA + timedelta(hours=1), "busca", cfg.janela_inicio, cfg.janela_fim) is a
    assert laco._janela(MEIO_DIA + timedelta(days=1), "busca", cfg.janela_inicio, cfg.janela_fim) is not a


def test_navegador_que_morre_e_reaberto(engine, sessoes, config):
    laco, navegador, fabrica, _, _ = criar_laco(LacoDaBusca, engine, sessoes, config, {})
    assert laco._obter_navegador() is navegador
    navegador.morto = True
    laco._obter_navegador()
    assert (fabrica.abertos, fabrica.fechados) == (2, 1)
    laco.fechar_navegador()
    assert fabrica.fechados == 2


@pytest.mark.parametrize("origem", [ORIGEM_BUSCA, ORIGEM_MONITOR])
def test_origens_nao_dividem_estado_trava_nem_avisos(origem):
    outra = ORIGEM_MONITOR if origem is ORIGEM_BUSCA else ORIGEM_BUSCA
    assert origem.coletor != outra.coletor and origem.id_lock != outra.id_lock
    assert {origem.captcha, origem.pausada, origem.erro}.isdisjoint({outra.captcha, outra.pausada, outra.erro})
    assert dados_captcha(origem, "https://www.amazon.com.br/s?k=a").linhas[1] == origem.efeito_captcha
