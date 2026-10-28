import json
from zoneinfo import ZoneInfo

import httpx
from fakes import T0, TransporteFake, criar_anuncio, criar_produto
from sqlalchemy import select

from tcg_sniper.casador.idioma import definir_idioma_com_ia
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import AnuncioAmazon, ChamadaIA, OrigemCasamento, StatusCasamento
from tcg_sniper.ia.modelos import Bruta, ChaveInvalida, ErroIA

SP = ZoneInfo("America/Sao_Paulo")


def resp(idioma, motivo="Caixa em japonês na foto", mesmo=True):
    return Bruta(
        json.dumps({"mesmo_produto": mesmo, "confianca": 90, "motivo": motivo, "idioma_anuncio": idioma}), 1000, 100
    )


def http():
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))


def confirmado(s, asin, titulo, produto=None):
    p = produto or criar_produto(s, f"p{asin}")
    a = criar_anuncio(s, asin, produto=p, status=StatusCasamento.CONFIRMADO, origem=OrigemCasamento.MANUAL)
    a.titulo = titulo
    s.flush()
    return a.id


def idioma_de(sessoes, anuncio_id):
    with sessoes() as s:
        return s.get(AnuncioAmazon, anuncio_id).idioma


def rodar(sessoes, transporte, aplicar):
    return definir_idioma_com_ia(sessoes, transporte, http(), SP, lambda: T0, aplicar=aplicar)


def test_aplicando_grava_o_idioma_da_ia(sessoes):
    with sessoes() as s, s.begin():
        a = confirmado(s, "B1", "Caixa sem idioma")
    t = TransporteFake([resp("en", "Texto em inglês na caixa")])
    r = rodar(sessoes, t, aplicar=True)
    assert idioma_de(sessoes, a) == "en"
    assert r.definidos == {"en": 1} and r.sem_decisao == [] and r.falhas == 0
    assert [(d.anuncio_id, d.idioma, d.motivo) for d in r.decisoes] == [(a, "en", "Texto em inglês na caixa")]
    assert "Caixa sem idioma" in t.pedidos[0].texto


def test_sem_aplicar_nao_grava_mas_chama_e_registra_a_ia(sessoes):
    with sessoes() as s, s.begin():
        a = confirmado(s, "B1", "Caixa sem idioma")
    r = rodar(sessoes, TransporteFake([resp("pt")]), aplicar=False)
    assert idioma_de(sessoes, a) is None
    assert r.definidos == {"pt": 1} and len(r.decisoes) == 1
    with sessoes() as s:
        assert [c.finalidade for c in s.scalars(select(ChamadaIA))] == ["idioma"]


def test_indefinido_fica_sem_decisao(sessoes):
    with sessoes() as s, s.begin():
        a = confirmado(s, "B1", "Caixa sem idioma")
    r = rodar(sessoes, TransporteFake([resp("indefinido")]), aplicar=True)
    assert idioma_de(sessoes, a) is None
    assert r.definidos == {} and r.sem_decisao == [(a, "Caixa sem idioma")] and r.decisoes == []


def test_japones_da_ia_vira_suspeito(sessoes):
    with sessoes() as s, s.begin():
        a = confirmado(s, "B1", "Caixa sem idioma")
    r = rodar(sessoes, TransporteFake([resp("ja")]), aplicar=True)
    assert idioma_de(sessoes, a) == "ja"
    assert r.suspeitos == [(a, "Caixa sem idioma")]


def test_nao_chama_a_ia_para_quem_o_titulo_decide(sessoes):
    with sessoes() as s, s.begin():
        titulo = confirmado(s, "B1", "Booster Box English")
        sem = confirmado(s, "B2", "Caixa sem idioma")
    t = TransporteFake([resp("pt")])
    r = rodar(sessoes, t, aplicar=True)
    assert len(t.pedidos) == 1 and "Caixa sem idioma" in t.pedidos[0].texto
    assert idioma_de(sessoes, titulo) == "en" and idioma_de(sessoes, sem) == "pt"
    assert r.definidos == {"en": 1, "pt": 1}


def test_nao_sobrescreve_idioma_ja_definido(sessoes):
    with sessoes() as s, s.begin():
        a = confirmado(s, "B1", "Caixa sem idioma")
        s.get(AnuncioAmazon, a).idioma = "ja"
    t = TransporteFake([])
    rodar(sessoes, t, aplicar=True)
    assert t.pedidos == [] and idioma_de(sessoes, a) == "ja"


def test_falha_num_anuncio_nao_para_os_outros(sessoes):
    with sessoes() as s, s.begin():
        a = confirmado(s, "B1", "Caixa um")
        b = confirmado(s, "B2", "Caixa dois")
    r = rodar(sessoes, TransporteFake([ErroIA("OpenAI 500"), resp("en")]), aplicar=True)
    assert r.falhas == 1 and r.interrompida is None
    assert idioma_de(sessoes, a) is None and idioma_de(sessoes, b) == "en"
    assert (a, "Caixa um") in r.sem_decisao


def test_sem_orcamento_interrompe(sessoes):
    with sessoes() as s, s.begin():
        confirmado(s, "B1", "Caixa um")
        confirmado(s, "B2", "Caixa dois")
        repo_ia.salvar_config_ia(s, {"max_chamadas_dia": 0}, T0)
    t = TransporteFake([])
    r = rodar(sessoes, t, aplicar=True)
    assert r.interrompida is not None and "chamadas" in r.interrompida and t.pedidos == []
    assert len(r.sem_decisao) == 2


def test_chave_invalida_interrompe_sem_seguir(sessoes):
    with sessoes() as s, s.begin():
        confirmado(s, "B1", "Caixa um")
        confirmado(s, "B2", "Caixa dois")
    t = TransporteFake([ChaveInvalida("chave da OpenAI recusada")])
    r = rodar(sessoes, t, aplicar=True)
    assert "recusada" in r.interrompida and len(t.pedidos) == 1
