from datetime import timedelta

import pytest
from fakes import T0, criar_anuncio, criar_produto

from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_termos as repo_termos
from tcg_sniper.db.models import FilaAmazon, StatusCasamento

DIA = timedelta(days=1)


def test_seca_conta_7_dias_desde_a_entrada_ou_o_ultimo_par_novo(s):
    p = criar_produto(s, "p")
    repo_amz.sincronizar_fila(s, T0)
    assert not repo_termos.em_seca(s, p.id, T0 + 7 * DIA - timedelta(seconds=1))
    assert repo_termos.em_seca(s, p.id, T0 + 7 * DIA)
    s.get(FilaAmazon, p.id).ultimo_par_novo_em = T0 + 3 * DIA
    s.flush()
    assert not repo_termos.em_seca(s, p.id, T0 + 7 * DIA)
    assert repo_termos.em_seca(s, p.id, T0 + 10 * DIA)


def test_produto_casado_ou_fora_da_fila_nunca_esta_em_seca(s):
    casado, fora = criar_produto(s, "casado"), criar_produto(s, "fora", ativo=False)
    repo_amz.sincronizar_fila(s, T0)
    criar_anuncio(s, "B0SECA0001", produto=casado, status=StatusCasamento.CONFIRMADO)
    assert not repo_termos.em_seca(s, casado.id, T0 + 30 * DIA)
    assert not repo_termos.em_seca(s, fora.id, T0 + 30 * DIA)


def test_guardar_termos_substitui_marca_a_tentativa_e_limpa_o_pedido(s):
    p = criar_produto(s, "p")
    repo_amz.sincronizar_fila(s, T0)
    assert repo_termos.pedir_termos(s, p.id, T0) is True
    repo_termos.guardar_termos(s, p.id, [("caixa alfa", "pt"), ("alpha box", "en")], T0)
    repo_termos.guardar_termos(s, p.id, [("alpha booster box", "en")], T0 + DIA)
    assert [(t.termo, t.idioma, t.ordem) for t in repo_termos.termos_do_produto(s, p.id)] == [("alpha booster box", "en", 1)]
    fila = s.get(FilaAmazon, p.id)
    assert (fila.termos_tentados_em, fila.termos_pedidos_em) == (T0 + DIA, None)
    with pytest.raises(ValueError):
        repo_termos.guardar_termos(s, p.id, [("a", "pt"), ("b", "pt"), ("c", "pt"), ("d", "pt")], T0)
    with pytest.raises(ValueError):
        repo_termos.guardar_termos(s, p.id, [], T0)


def test_pedir_termos_sem_linha_na_fila_devolve_falso(s):
    p = criar_produto(s, "p")
    assert repo_termos.pedir_termos(s, p.id, T0) is False


def test_produtos_para_gerar_termos(s):
    pedido = criar_produto(s, "pedido")
    seco = criar_produto(s, "seco")
    seco_com_termos = criar_produto(s, "seco-com-termos")
    tentado = criar_produto(s, "tentado")
    recente = criar_produto(s, "recente")
    repo_amz.sincronizar_fila(s, T0)
    s.get(FilaAmazon, recente.id).entrou_em = T0 + 5 * DIA
    repo_termos.guardar_termos(s, seco_com_termos.id, [("x y", "pt")], T0)
    repo_termos.guardar_termos(s, pedido.id, [("antigo", "pt")], T0)  # o pedido regenera mesmo com termos
    repo_termos.pedir_termos(s, pedido.id, T0 + 8 * DIA)
    repo_termos.marcar_tentativa(s, tentado.id, T0 + 6 * DIA)
    agora = T0 + 8 * DIA
    assert [p.id for p in repo_termos.produtos_para_gerar_termos(s, agora, 10)] == [pedido.id, seco.id]
    assert [p.id for p in repo_termos.produtos_para_gerar_termos(s, agora, 1)] == [pedido.id]
    assert tentado.id in [p.id for p in repo_termos.produtos_para_gerar_termos(s, T0 + 13 * DIA, 10)]


@pytest.mark.parametrize(
    "termos",
    [
        [("x" * 81, "pt")],
        [("   ", "pt")],
        [("", "en")],
        [("caixa", "es")],
        [("Caixa Alfa", "pt"), ("caixa alfa", "en")],
        [("caixa alfa", "pt"), (" caixa alfa ", "pt")],
    ],
)
def test_guardar_termos_recusa_invalidos_sem_gravar(s, termos):
    p = criar_produto(s, "p")
    repo_amz.sincronizar_fila(s, T0)
    repo_termos.guardar_termos(s, p.id, [("antigo", "pt")], T0)
    with pytest.raises(ValueError):
        repo_termos.guardar_termos(s, p.id, termos, T0 + DIA)
    assert [t.termo for t in repo_termos.termos_do_produto(s, p.id)] == ["antigo"]
    assert s.get(FilaAmazon, p.id).termos_tentados_em == T0


def test_guardar_termos_tira_os_espacos_das_pontas(s):
    p = criar_produto(s, "p")
    repo_amz.sincronizar_fila(s, T0)
    repo_termos.guardar_termos(s, p.id, [("  caixa alfa ", "pt"), ("x" * 80, "en")], T0)
    assert [t.termo for t in repo_termos.termos_do_produto(s, p.id)] == ["caixa alfa", "x" * 80]
