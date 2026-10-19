import json
from datetime import timedelta
from decimal import Decimal

import httpx
from fakes import T0, AvisadorFake, TransporteFake, criar_anuncio, criar_produto
from sqlalchemy import select

from tcg_sniper.avisos.catalogo import TipoAviso
from tcg_sniper.casador.servico import FALHAS_SEGUIDAS_MAX, TERMOS_POR_CICLO, ServicoCasador
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db import repositorio_termos as repo_termos
from tcg_sniper.db.models import ChamadaIA, FilaAmazon, ProdutoLiga, StatusCasamento
from tcg_sniper.ia.modelos import Bruta, ErroIA

DIA = timedelta(days=1)


def termos(*itens):
    return Bruta(json.dumps({"termos": [{"termo": termo, "idioma": idioma} for termo, idioma in itens]}), 300, 40)


def servico(sessoes, config, respostas, agora):
    t = TransporteFake(respostas)
    avisador = AvisadorFake()
    cfg = config.model_copy(update={"openai_api_key": "sk-teste"})
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    return ServicoCasador(sessoes, t, cfg, avisador, cliente_http=http, relogio=lambda: agora), t, avisador


def configurar(sessoes, **valores):
    with sessoes() as s, s.begin():
        repo_ia.salvar_config_ia(s, {"ligado": True, **valores}, T0)


def na_fila(sessoes, *liga_ids, entrou_em=T0):
    with sessoes() as s, s.begin():
        ids = [criar_produto(s, liga_id, nome=f"Caixa de Booster {liga_id}").id for liga_id in liga_ids]
        repo_amz.sincronizar_fila(s, entrou_em)
        return ids


def guardados(sessoes, produto_id):
    with sessoes() as s:
        return [(t.termo, t.idioma) for t in repo_termos.termos_do_produto(s, produto_id)]


def test_gera_termos_so_depois_de_7_dias_sem_candidato(sessoes, config):
    configurar(sessoes)
    [p] = na_fila(sessoes, "alfa")
    sv, t, _ = servico(sessoes, config, [], T0 + 6 * DIA)
    sv.ciclo()
    assert t.pedidos == []
    respostas = [termos(("alfa booster box", "en"), ("caixa alfa lacrada", "pt"))]
    sv, t, _ = servico(sessoes, config, respostas, T0 + 7 * DIA)
    sv.ciclo()
    [pedido] = t.pedidos
    assert pedido.imagens == ()
    assert guardados(sessoes, p) == [("alfa booster box", "en"), ("caixa alfa lacrada", "pt")]
    with sessoes() as s:
        assert [c.finalidade for c in s.scalars(select(ChamadaIA))] == ["termos"]
    sv, t, _ = servico(sessoes, config, [], T0 + 8 * DIA)
    sv.ciclo()
    assert t.pedidos == []  # uma vez por produto: já tem termos guardados


def test_termos_invalidos_sao_descartados_e_so_tenta_de_novo_em_7_dias(sessoes, config):
    configurar(sessoes)
    [p] = na_fila(sessoes, "alfa")
    invalidos = [termos(("https://amazon.com.br/x", "pt"), ("Caixa de Booster alfa", "pt"))]
    sv, t, _ = servico(sessoes, config, invalidos, T0 + 7 * DIA)
    sv.ciclo()
    assert len(t.pedidos) == 1 and guardados(sessoes, p) == []
    with sessoes() as s:
        assert s.get(FilaAmazon, p).termos_tentados_em == T0 + 7 * DIA
    sv, t, _ = servico(sessoes, config, [], T0 + 13 * DIA)
    sv.ciclo()
    assert t.pedidos == []
    sv, t, _ = servico(sessoes, config, [termos(("alfa booster box", "en"))], T0 + 14 * DIA)
    sv.ciclo()
    assert guardados(sessoes, p) == [("alfa booster box", "en")]


def test_sem_orcamento_nao_gera_e_mantem_o_pedido(sessoes, config):
    configurar(sessoes, teto_dia_usd=Decimal(0))
    [p] = na_fila(sessoes, "alfa")
    with sessoes() as s, s.begin():
        repo_termos.pedir_termos(s, p, T0)
    sv, t, avisador = servico(sessoes, config, [], T0)
    sv.ciclo()
    assert t.pedidos == [] and guardados(sessoes, p) == []
    assert TipoAviso.IA_SEM_ORCAMENTO in avisador.tipos()
    with sessoes() as s:
        fila = s.get(FilaAmazon, p)
        assert (fila.termos_pedidos_em, fila.termos_tentados_em) == (T0, None)


def test_pedido_do_admin_regenera_mesmo_com_termos_guardados(sessoes, config):
    configurar(sessoes)
    [p] = na_fila(sessoes, "alfa")
    with sessoes() as s, s.begin():
        repo_termos.guardar_termos(s, p, [("antigo alfa", "pt")], T0)
        repo_termos.pedir_termos(s, p, T0)
    sv, _, _ = servico(sessoes, config, [termos(("alfa booster box", "en"))], T0)  # fora da seca: vale o pedido
    sv.ciclo()
    assert guardados(sessoes, p) == [("alfa booster box", "en")]
    with sessoes() as s:
        assert s.get(FilaAmazon, p).termos_pedidos_em is None


def test_limite_de_produtos_por_ciclo(sessoes, config):
    assert TERMOS_POR_CICLO == 5
    configurar(sessoes)
    na_fila(sessoes, *(f"p{i}" for i in range(TERMOS_POR_CICLO + 1)))
    respostas = [termos((f"termo {i}", "pt")) for i in range(TERMOS_POR_CICLO + 1)]
    sv, t, _ = servico(sessoes, config, respostas, T0 + 7 * DIA)
    sv.ciclo()
    assert len(t.pedidos) == TERMOS_POR_CICLO


def test_produto_casado_nao_gera_termos(sessoes, config):
    configurar(sessoes)
    [p] = na_fila(sessoes, "alfa")
    with sessoes() as s, s.begin():
        criar_anuncio(s, "B0CASADO01", produto=s.get(ProdutoLiga, p), status=StatusCasamento.CONFIRMADO)
    sv, t, _ = servico(sessoes, config, [], T0 + 30 * DIA)
    sv.ciclo()
    assert t.pedidos == []


def test_falhas_seguidas_na_avaliacao_pulam_a_etapa_dos_termos(sessoes, config):
    configurar(sessoes)
    [p] = na_fila(sessoes, "alfa")
    with sessoes() as s, s.begin():
        produto = s.get(ProdutoLiga, p)
        for i in range(FALHAS_SEGUIDAS_MAX):
            criar_anuncio(s, f"B0FALHA{i:03d}", produto=produto, agora=T0 + 7 * DIA)
        repo_termos.pedir_termos(s, p, T0)
    falhas = [ErroIA("OpenAI 500")] * FALHAS_SEGUIDAS_MAX
    sv, t, _ = servico(sessoes, config, [*falhas, termos(("alfa booster box", "en"))], T0 + 7 * DIA)
    sv.ciclo()
    assert len(t.pedidos) == FALHAS_SEGUIDAS_MAX  # nenhuma chamada de termos depois da quebra
    assert guardados(sessoes, p) == []
    with sessoes() as s:
        fila = s.get(FilaAmazon, p)
        assert (fila.termos_pedidos_em, fila.termos_tentados_em) == (T0, None)  # o pedido fica para o próximo
