from datetime import timedelta
from decimal import Decimal

import pytest
from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto
from fakes_oportunidades import criar_atual_amazon, criar_listagem_liga

from tcg_sniper.consultas.catalogo_gestao import (
    FiltroCatalogo,
    aplicar_lote,
    contar_filtro,
    linha_produto,
    linhas_catalogo,
)
from tcg_sniper.db.models import ProdutoLiga, StatusCasamento

PENDENTE, CONFIRMADO, IGNORADO = StatusCasamento.PENDENTE, StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO


def _tipo(s, produto, tipo):
    produto.tipo = tipo
    s.flush()
    return produto


@pytest.fixture
def catalogo(sessoes):
    """Ativos em cada situação, um inativo casado e um inativo sem nada; duas categorias."""
    with sessoes() as s, s.begin():
        casado = _tipo(s, criar_produto(s, "casado", nome="Caixa Casada"), "Caixas")
        a1 = criar_anuncio(s, "B0CASADO01", casado, CONFIRMADO)
        a2 = criar_anuncio(s, "B0CASADO02", casado, CONFIRMADO)
        criar_anuncio(s, "B0CASADO03", casado, PENDENTE)
        criar_atual_amazon(s, a1, "90.00")
        criar_atual_amazon(s, a2, "80.00")
        criar_preco_liga(s, casado, "100.00", num_lojas=4)
        esperando = _tipo(s, criar_produto(s, "esperando", nome="Caixa Esperando"), "Caixas")
        criar_anuncio(s, "B0ESPERA01", esperando, PENDENTE)
        ignorado = _tipo(s, criar_produto(s, "ignorado", nome="Bundle Ignorado"), "Bundles")
        criar_anuncio(s, "B0IGNORA01", ignorado, IGNORADO)
        sem = _tipo(s, criar_produto(s, "sem", nome="Bundle Sem"), "Bundles")
        criar_preco_liga(s, sem, "50.00")
        inativo = _tipo(s, criar_produto(s, "inativo", ativo=False, nome="Caixa Inativa"), "Caixas")
        criar_anuncio(s, "B0INATIV01", inativo, CONFIRMADO)
        inativo_sem = _tipo(s, criar_produto(s, "inativo-sem", ativo=False, nome="Bundle Inativo"), "Bundles")
        return {
            "casado": casado.id, "esperando": esperando.id, "ignorado": ignorado.id, "sem": sem.id,
            "inativo": inativo.id, "inativo_sem": inativo_sem.id,
        }


def _nomes(s, **filtro):
    base = {"busca": "", "monitorado": "todos", "categoria": None, "situacao": None, "preco_liga": "todos", "pagina": 1}
    return [linha.produto.nome for linha in linhas_catalogo(s, **{**base, **filtro}).itens]


def test_filtro_monitorado_e_situacao(sessoes, catalogo):
    with sessoes() as s:
        assert _nomes(s, monitorado="sim") == ["Bundle Ignorado", "Bundle Sem", "Caixa Casada", "Caixa Esperando"]
        assert _nomes(s, monitorado="nao") == ["Bundle Inativo", "Caixa Inativa"]
        assert _nomes(s, situacao="casado") == ["Caixa Casada", "Caixa Inativa"]
        assert _nomes(s, situacao="casado", monitorado="nao") == ["Caixa Inativa"]
        assert _nomes(s, situacao="esperando_decisao") == ["Caixa Esperando"]
        assert _nomes(s, situacao="so_ignorados") == ["Bundle Ignorado"]
        assert _nomes(s, situacao="sem_candidato") == ["Bundle Sem", "Bundle Inativo"]
        assert _nomes(s, categoria="Bundles", preco_liga="com") == ["Bundle Sem"]
        assert _nomes(s, busca="caixa", monitorado="sim") == ["Caixa Casada", "Caixa Esperando"]
        pagina = linhas_catalogo(
            s, busca="casada", monitorado="todos", categoria=None, situacao=None, preco_liga="todos", pagina=1
        )
        linha = pagina.itens[0]
        assert (linha.situacao_casamento, linha.pendentes, linha.confirmados) == ("casado", 1, 2)
        assert linha.preco_liga == Decimal("100.00") and linha.lojas == 4
        assert linha.melhor_amazon == Decimal("80.00")
        sem = linha_produto(s, catalogo["sem"])
        assert sem.situacao_casamento == "sem_candidato" and sem.melhor_amazon is None
        with pytest.raises(ValueError):
            linhas_catalogo(s, busca="", monitorado="talvez", categoria=None, situacao=None, preco_liga="todos", pagina=1)
        with pytest.raises(ValueError):
            linhas_catalogo(s, busca="", monitorado="todos", categoria=None, situacao="x", preco_liga="todos", pagina=1)


def test_contar_filtro_igual_ao_total_da_lista(sessoes, catalogo):
    filtros = [
        FiltroCatalogo(),
        FiltroCatalogo(monitorado="sim"),
        FiltroCatalogo(monitorado="nao", categoria="Caixas"),
        FiltroCatalogo(situacao="casado"),
        FiltroCatalogo(situacao="sem_candidato", preco_liga="com"),
        FiltroCatalogo(busca="bundle"),
    ]
    with sessoes() as s:
        for filtro in filtros:
            pagina = linhas_catalogo(
                s, busca=filtro.busca, monitorado=filtro.monitorado, categoria=filtro.categoria,
                situacao=filtro.situacao, preco_liga=filtro.preco_liga, pagina=1, por_pagina=2,
            )
            assert contar_filtro(s, filtro) == pagina.total, filtro
        assert contar_filtro(s, FiltroCatalogo()) == 6
        segunda = linhas_catalogo(
            s, busca="", monitorado="todos", categoria=None, situacao=None, preco_liga="todos", pagina=2, por_pagina=4
        )
        assert segunda.total == 6 and len(segunda.itens) == 2 and segunda.pagina == 2 and segunda.por_pagina == 4


def _ativos(sessoes):
    with sessoes() as s:
        return {p.liga_id for p in s.query(ProdutoLiga).filter(ProdutoLiga.ativo.is_(True))}


def test_aplicar_lote_por_ids_e_por_filtro_devolve_alterados(sessoes, catalogo):
    with sessoes() as s, s.begin():
        assert aplicar_lote(s, True, [catalogo["inativo"], catalogo["casado"]], T0) == 1  # casado já estava ligado
    assert _ativos(sessoes) == {"casado", "esperando", "ignorado", "sem", "inativo"}
    with sessoes() as s, s.begin():
        assert aplicar_lote(s, False, FiltroCatalogo(categoria="Bundles"), T0) == 2
    assert _ativos(sessoes) == {"casado", "esperando", "inativo"}
    with sessoes() as s, s.begin():
        assert aplicar_lote(s, False, FiltroCatalogo(situacao="casado", monitorado="sim"), T0) == 2
        assert aplicar_lote(s, False, [], T0) == 0
    assert _ativos(sessoes) == {"esperando"}


@pytest.fixture
def esgotados(sessoes):
    """Sem "a partir de" na Liga: com média e anúncio confirmado com preço (A: 50%, C: 10%), sem média (B, sem linha
    na Liga), com anúncio confirmado sem preço (D) e só com pendente com preço (E); F tem preço na Liga."""
    with sessoes() as s, s.begin():
        def produto(chave, nome, liga=None, medio=None, sem_liga=False, ativo=True):
            p = criar_produto(s, chave, nome=nome, ativo=ativo)
            if not sem_liga:
                criar_preco_liga(s, p, liga, preco_medio=medio)
            return p

        def anuncio(asin, p, preco, status=CONFIRMADO):
            criar_atual_amazon(s, criar_anuncio(s, asin, p, status), preco)

        a = produto("a", "Zeta A", medio="200.00")
        anuncio("B0ESGOTA01", a, "100.00")
        anuncio("B0ESGOTA02", a, "150.00")
        b = produto("b", "Alfa B", sem_liga=True)
        anuncio("B0ESGOTB01", b, "80.00")
        c = produto("c", "Beta C", medio="100.00")
        anuncio("B0ESGOTC01", c, "90.00")
        d = produto("d", "Delta D", medio="100.00")
        anuncio("B0ESGOTD01", d, None)
        e = produto("e", "Eta E", medio="100.00")
        anuncio("B0ESGOTE01", e, "10.00", PENDENTE)
        f = produto("f", "Fi F", liga="100.00", medio="100.00")
        anuncio("B0ESGOTF01", f, "50.00")
        g = produto("g", "Gama G inativo", medio="300.00", ativo=False)  # esgotado, mas não monitorado: fica fora
        anuncio("B0ESGOTG01", g, "100.00")
        criar_listagem_liga(s, a, "150.00", T0 - timedelta(days=10))
        criar_listagem_liga(s, a, "140.00", T0 - timedelta(days=5))
        criar_listagem_liga(s, a, None, T0 - timedelta(days=2))
        criar_listagem_liga(s, c, None, T0 - timedelta(days=1))
        return {"a": a.id, "b": b.id, "c": c.id, "d": d.id, "e": e.id, "f": f.id, "g": g.id}


def test_filtro_esgotado_so_com_anuncio_com_preco(sessoes, esgotados):
    with sessoes() as s:
        assert set(_nomes(s, preco_liga="esgotado")) == {"Zeta A", "Alfa B", "Beta C"}  # sem o inativo G
        assert _nomes(s, preco_liga="esgotado", monitorado="nao") == []
        assert _nomes(s, preco_liga="com") == ["Fi F"]
        with pytest.raises(ValueError):
            _nomes(s, preco_liga="talvez")


def test_ordem_esgotado_por_diferenca_media_nulos_no_fim(sessoes, esgotados):
    with sessoes() as s:
        itens = linhas_catalogo(
            s, busca="", monitorado="todos", categoria=None, situacao=None, preco_liga="esgotado", pagina=1
        ).itens
        assert [i.produto.nome for i in itens] == ["Zeta A", "Beta C", "Alfa B"]
        a, c, b = itens
        assert (a.melhor_amazon, a.medio_liga, a.diferenca_media_pct) == (
            Decimal("100.00"), Decimal("200.00"), Decimal("50.00")
        )
        assert c.diferenca_media_pct == Decimal("10.00")
        assert (b.medio_liga, b.diferenca_media_pct) == (None, None)
        # sem o filtro, a ordem é a de sempre (por nome)
        assert _nomes(s)[:3] == ["Alfa B", "Beta C", "Delta D"]


def test_sem_vendedor_desde_pela_ultima_listagem_com_preco(sessoes, esgotados):
    with sessoes() as s:
        assert linha_produto(s, esgotados["a"]).sem_vendedor_desde == T0 - timedelta(days=5)
        assert linha_produto(s, esgotados["b"]).sem_vendedor_desde is None
        assert linha_produto(s, esgotados["c"]).sem_vendedor_desde is None  # só leituras sem preço


def test_contar_filtro_esgotado_igual_a_lista(sessoes, esgotados):
    filtro = FiltroCatalogo(preco_liga="esgotado")
    with sessoes() as s:
        pagina = linhas_catalogo(
            s, busca="", monitorado="todos", categoria=None, situacao=None, preco_liga="esgotado", pagina=1,
            por_pagina=2,
        )
        assert contar_filtro(s, filtro) == pagina.total == 3 and len(pagina.itens) == 2
        assert [i.produto.nome for i in pagina.itens] == ["Zeta A", "Beta C"]
        assert contar_filtro(s, FiltroCatalogo(preco_liga="esgotado", busca="beta")) == 1
        assert contar_filtro(s, FiltroCatalogo(preco_liga="esgotado", busca="gama")) == 0  # inativo fora
    with sessoes() as s, s.begin():
        assert aplicar_lote(s, True, filtro, T0) == 0  # não liga o inativo G
    assert _ativos(sessoes) == {"a", "b", "c", "d", "e", "f"}
    with sessoes() as s, s.begin():
        assert aplicar_lote(s, False, filtro, T0) == 3
    assert _ativos(sessoes) == {"d", "e", "f"}
