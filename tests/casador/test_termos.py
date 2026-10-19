import json
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, TransporteFake, criar_produto
from sqlalchemy import select

from tcg_sniper.casador import pergunta, termos
from tcg_sniper.casador.termos import FINALIDADE, filtrar_termos, gerar_termos
from tcg_sniper.db.models import ChamadaIA
from tcg_sniper.ia.modelos import Bruta, RespostaForaDoFormato

NOME, NOME_EN = "Caixa de Booster - Alfa", "Booster Box - Alpha"
VALIDO = ("caixa alfa lacrada", "pt")
REGRA_IDIOMA = "idioma diferente = outro produto: português, inglês e japonês não se casam entre si"


def dados(*itens):
    return {"termos": [{"termo": termo, "idioma": idioma} for termo, idioma in itens]}


def test_mantem_os_validos_na_ordem():
    itens = (("alfa booster box", "en"), VALIDO)
    assert filtrar_termos(dados(*itens), NOME, NOME_EN) == list(itens)


@pytest.mark.parametrize(
    "termo",
    [
        "",
        "   ",
        "x" * 81,
        "https://www.amazon.com.br/dp/B0ALFA0001",
        "www.amazon.com.br caixa alfa",
        "caixa de booster: ALFA",  # o nome em português com outra pontuação e caixa
        "booster box alpha",  # o nome em inglês
    ],
)
def test_descarta_invalidos(termo):
    assert filtrar_termos(dados((termo, "pt"), VALIDO), NOME, NOME_EN) == [VALIDO]


def test_descarta_idioma_desconhecido_repetido_e_corta_em_3():
    itens = (("alfa caja", "es"), VALIDO, ("Caixa  Alfa  Lacrada", "pt"), ("a1", "pt"), ("a2", "en"), ("a3", "pt"))
    assert filtrar_termos(dados(*itens), NOME, None) == [VALIDO, ("a1", "pt"), ("a2", "en")]


def test_espacos_internos_sao_normalizados():
    assert filtrar_termos(dados(("caixa   alfa \t lacrada", "pt")), NOME, None) == [VALIDO]


def test_item_que_nao_e_objeto_ou_sem_texto_e_ignorado():
    assert filtrar_termos({"termos": ["solto", {"idioma": "pt"}, {"termo": 3, "idioma": "pt"}]}, NOME, None) == []


@pytest.mark.parametrize("resposta", [{}, {"termos": "caixa alfa"}])
def test_resposta_sem_lista_e_fora_do_formato(resposta):
    with pytest.raises(RespostaForaDoFormato):
        filtrar_termos(resposta, NOME, None)


def test_gerar_termos_faz_uma_chamada_sem_imagem_e_registra_a_finalidade(sessoes):
    with sessoes() as s, s.begin():
        produto = criar_produto(s, "p1", nome=NOME)
        produto.nome_en = NOME_EN
        s.flush()
        s.expunge(produto)
    t = TransporteFake([Bruta(json.dumps(dados(("alfa booster box", "en"))), 300, 40)])
    gerados = gerar_termos(sessoes, t, produto, zona=ZoneInfo("America/Sao_Paulo"), relogio=lambda: T0)
    assert gerados == [("alfa booster box", "en")]
    [pedido] = t.pedidos
    assert pedido.imagens == () and NOME in pedido.texto and NOME_EN in pedido.texto
    with sessoes() as s:
        assert [c.finalidade for c in s.scalars(select(ChamadaIA))] == [FINALIDADE]


def test_regra_do_idioma_esta_nas_duas_perguntas():
    # Regra do usuário (2026-10-19): edições em idiomas diferentes são produtos diferentes.
    assert REGRA_IDIOMA in pergunta.INSTRUCOES.casefold()
    assert REGRA_IDIOMA in termos.INSTRUCOES.casefold()
    assert "mesma edição de idioma" in termos.INSTRUCOES  # os termos buscam a edição do idioma do produto
