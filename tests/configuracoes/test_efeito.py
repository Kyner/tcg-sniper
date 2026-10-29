from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto
from fakes_oportunidades import criar_atual_amazon, criar_oportunidade

from tcg_sniper.configuracoes import efeito as modulo
from tcg_sniper.configuracoes.efeito import efeito
from tcg_sniper.configuracoes.grupos import valores_atuais
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import StatusCasamento

AGORA = T0 + timedelta(hours=2)


@pytest.fixture(autouse=True)
def _tabelas(s, config):
    valores_atuais(s, config)  # cria geral e liga como na tela


def _texto(resultado) -> str:
    return "\n".join(resultado.linhas)


def test_grupos_sem_efeito_devolvem_none(s):
    for grupo in ("vendedores", "liga", "ia-modelo", "whatsapp", "sistema"):
        assert efeito(s, AGORA, grupo, {}) is None


def test_grupo_desconhecido(s):
    with pytest.raises(KeyError):
        efeito(s, AGORA, "nao-existe", {})


# --- oportunidades --------------------------------------------------------------------------


def _produto(s, nome, liga="1000.00"):
    p = criar_produto(s, nome)
    criar_preco_liga(s, p, liga, listagem_em=T0)
    return p


def test_oportunidades_faixas_e_contagem(s):
    aberta = _produto(s, "aberta")
    a = criar_anuncio(s, "B0EFE00001", aberta, StatusCasamento.CONFIRMADO)
    criar_atual_amazon(s, a, "700.00")
    criar_oportunidade(s, a, aberta, aberta_em=T0)
    perto = _produto(s, "perto")
    criar_atual_amazon(s, criar_anuncio(s, "B0EFE00002", perto, StatusCasamento.CONFIRMADO), "850.00")  # 15%

    r = efeito(s, AGORA, "oportunidades", {"amazon.desconto_min_pct": "20", "amazon.quase_oportunidade_min_pct": "10"})
    texto = _texto(r)
    assert r.nivel == "info"
    assert "alerta a partir de 20%" in texto
    assert "quase lá de 10% a 20%" in texto
    assert "1 oportunidade aberta" in texto
    assert "1 produto quase lá" in texto
    # com o piso acima dos 15% do anúncio, ele sai do "quase lá"
    r = efeito(s, AGORA, "oportunidades", {"amazon.desconto_min_pct": "20", "amazon.quase_oportunidade_min_pct": "16"})
    assert "0 produtos quase lá" in _texto(r)


def test_oportunidades_quase_la_acima_do_minimo_e_erro(s):
    r = efeito(s, AGORA, "oportunidades", {"amazon.desconto_min_pct": "20", "amazon.quase_oportunidade_min_pct": "20"})
    assert r.nivel == "erro"


# --- busca ----------------------------------------------------------------------------------


def _catalogo_sem_par(s):
    for nome in ("a", "b", "c"):
        criar_produto(s, nome)
    casado = criar_produto(s, "casado")
    criar_anuncio(s, "B0EFE00010", casado, StatusCasamento.CONFIRMADO)


def test_busca_por_dia_e_ciclo_dos_sem_par(s):
    _catalogo_sem_par(s)
    r = efeito(s, AGORA, "busca", {
        "amazon.max_buscas_hora": "1", "amazon.janela_inicio": "08:00", "amazon.janela_fim": "10:00",
    })
    texto = _texto(r)
    assert r.nivel == "info"
    assert "2 buscas por dia" in texto
    assert "cada produto sem par a cada ~1,5 dias" in texto  # 3 sem par ÷ 2 por dia


def test_busca_ciclo_curto_fica_no_intervalo(s):
    _catalogo_sem_par(s)
    r = efeito(s, AGORA, "busca", {"amazon.intervalo_busca_min": "60"})  # 90/h × 14 h = 1.260 por dia
    texto = _texto(r)
    assert "1.260 buscas por dia" in texto
    assert "a cada ~60 min" in texto


def test_busca_janela_invertida_e_erro(s):
    r = efeito(s, AGORA, "busca", {"amazon.janela_inicio": "10:00", "amazon.janela_fim": "09:00"})
    assert r.nivel == "erro"


# --- monitor --------------------------------------------------------------------------------


def _rapidos(monkeypatch, s, n):
    base = repo_amz.situacao_monitor(s, AGORA, repo_amz.obter_config(s))
    monkeypatch.setattr(modulo.repo_amz, "situacao_monitor", lambda *_a, **_k: replace(base, rapidos=n, confirmados=n))


def test_monitor_estoura_a_capacidade(s, monkeypatch):
    _rapidos(monkeypatch, s, 64)
    # pausas 8–20 s (padrão): 3600 / (14 + 3) = 211 por hora
    r = efeito(s, AGORA, "monitor", {"amazon.monitor_intervalo_min": "15", "amazon.monitor_max_paginas_hora": "300"})
    texto = _texto(r)
    assert r.nivel == "aviso"
    assert "256 páginas por hora" in texto
    assert "cabem 211 por hora" in texto
    assert "estimativa" in texto
    assert "usar 19 min" in texto  # ceil(64 × 60 / 211)


def test_monitor_estoura_o_teto(s, monkeypatch):
    _rapidos(monkeypatch, s, 64)
    r = efeito(s, AGORA, "monitor", {"amazon.monitor_intervalo_min": "15", "amazon.monitor_max_paginas_hora": "150"})
    texto = _texto(r)
    assert r.nivel == "aviso"
    assert "cabem 150 por hora" in texto
    assert "usar 26 min" in texto  # ceil(64 × 60 / 150)


def test_monitor_cabe(s, monkeypatch):
    _rapidos(monkeypatch, s, 10)
    r = efeito(s, AGORA, "monitor", {"amazon.monitor_intervalo_min": "15", "amazon.monitor_max_paginas_hora": "150"})
    assert r.nivel == "info"
    assert "40 páginas por hora" in _texto(r)
    assert "usar" not in _texto(r)


# --- checkout e bloqueio --------------------------------------------------------------------


def test_checkout_a_partir_de(s):
    r = efeito(s, AGORA, "checkout", {"amazon.margem_candidata_pp": "5", "amazon.checkout_validade_h": "6"})
    assert r.nivel == "info"
    assert "a partir de 20% de desconto" in _texto(r)  # desconto mínimo 25 − 5


def test_bloqueio_capacidade_por_navegador_e_soma(s):
    r = efeito(s, AGORA, "bloqueio", {"amazon.pausa_min_s": "8", "amazon.pausa_max_s": "20"})
    texto = _texto(r)
    assert "211 páginas por hora" in texto
    assert "422 páginas por hora" in texto
    assert "estimativa" in texto
    r = efeito(s, AGORA, "bloqueio", {"amazon.pausa_min_s": "1", "amazon.pausa_max_s": "3"})  # 3600 / 5
    assert "720 páginas por hora" in _texto(r)


# --- IA -------------------------------------------------------------------------------------


def _avaliar(s, asin, produto, mesmo, confianca):
    anuncio = criar_anuncio(s, asin, produto, StatusCasamento.PENDENTE)
    repo_ia.gravar_avaliacao(
        s, anuncio_id=anuncio.id, produto_id=produto.id, mesmo_produto=mesmo, confianca=confianca, motivo="m",
        modelo="gpt-5", assinatura="x", sem_imagem=False, chamada_id=None, agora=T0,
    )


def test_ia_decide_quantos_ficam_para_voce(s):
    p = criar_produto(s, "ia")
    _avaliar(s, "B0EFE00020", p, True, 95)
    _avaliar(s, "B0EFE00021", p, False, 95)
    _avaliar(s, "B0EFE00022", p, True, 60)
    criar_anuncio(s, "B0EFE00023", p, StatusCasamento.PENDENTE)  # sem avaliação
    base = {"ia.ligado": "sim", "ia.automatico": "sim", "ia.confianca_confirmar": "90", "ia.confianca_ignorar": "90"}

    texto = _texto(efeito(s, AGORA, "ia-decide", base))
    assert "2 de 4 anúncios pendentes ficam para você" in texto
    texto = _texto(efeito(s, AGORA, "ia-decide", {**base, "ia.confianca_confirmar": "50"}))
    assert "1 de 4 anúncios pendentes ficam para você" in texto
    texto = _texto(efeito(s, AGORA, "ia-decide", {**base, "ia.automatico": "não"}))
    assert "4 de 4 anúncios pendentes ficam para você" in texto


def _chamada(s, em, custo, ok=True, finalidade="casamento"):
    repo_ia.registrar_chamada(
        s, em=em, finalidade=finalidade, modelo="gpt-5", tokens_entrada=1, tokens_saida=1, custo_usd=Decimal(custo),
        ok=ok, erro=None if ok else "falhou",
    )


def test_ia_ritmo_sem_dado(s):
    r = efeito(s, AGORA, "ia-ritmo", {"ia.lote": "20", "ia.intervalo_min": "5"})
    texto = _texto(r)
    assert "240 avaliações por hora" in texto
    assert "sem dado ainda" in texto


def test_ia_ritmo_teto_do_dia_no_custo_medio(s):
    _chamada(s, AGORA - timedelta(days=1), "0.01")
    _chamada(s, AGORA - timedelta(days=2), "0.03")
    _chamada(s, AGORA - timedelta(days=1), "1.00", ok=False)  # erro não conta
    _chamada(s, AGORA - timedelta(days=1), "1.00", finalidade="termos")  # outra finalidade não conta
    _chamada(s, AGORA - timedelta(days=8), "1.00")  # fora dos 7 dias
    r = efeito(s, AGORA, "ia-ritmo", {"ia.lote": "20", "ia.intervalo_min": "5"})
    texto = _texto(r)
    assert "US$ 0,0200" in texto
    assert "acaba em ~25 min" in texto  # US$ 2 ÷ (240/h × US$ 0,02)
    assert r.nivel == "aviso"
    r = efeito(s, AGORA, "ia-ritmo", {"ia.lote": "1", "ia.intervalo_min": "60"})  # 24/dia × 0,02 = 0,48
    assert "não chega ao teto do dia" in _texto(r)
    assert r.nivel == "info"


def test_ia_gasto_barras_e_nivel(s):
    _chamada(s, AGORA - timedelta(hours=1), "1.50")
    r = efeito(s, AGORA, "ia-gasto", {})
    texto = _texto(r)
    assert r.nivel == "info"
    assert "US$ 1,50 de US$ 2,00 (75%)" in texto
    assert r.barras == (("Hoje", 75), ("No mês", 8), ("Chamadas hoje", 0))
    assert efeito(s, AGORA, "ia-gasto", {"ia.teto_dia_usd": "1,8"}).nivel == "aviso"  # 83%
    assert efeito(s, AGORA, "ia-gasto", {"ia.teto_dia_usd": "1"}).nivel == "erro"  # 150%


def test_valor_invalido_usa_o_salvo_e_chave_de_fora_e_ignorada(s):
    r = efeito(s, AGORA, "checkout", {"amazon.margem_candidata_pp": "abc", "amazon.monitor_ligado": "x"})
    assert "a partir de 20% de desconto" in _texto(r)  # margem salva: 5

