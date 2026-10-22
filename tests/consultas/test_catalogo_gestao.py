from decimal import Decimal

import pytest
from fakes import T0, criar_anuncio, criar_preco_liga, criar_produto
from fakes_oportunidades import criar_atual_amazon

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
    base = {"busca": "", "monitorado": "todos", "categoria": None, "situacao": None, "com_preco": False, "pagina": 1}
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
        assert _nomes(s, categoria="Bundles", com_preco=True) == ["Bundle Sem"]
        assert _nomes(s, busca="caixa", monitorado="sim") == ["Caixa Casada", "Caixa Esperando"]
        pagina = linhas_catalogo(
            s, busca="casada", monitorado="todos", categoria=None, situacao=None, com_preco=False, pagina=1
        )
        linha = pagina.itens[0]
        assert (linha.situacao_casamento, linha.pendentes, linha.confirmados) == ("casado", 1, 2)
        assert linha.preco_liga == Decimal("100.00") and linha.lojas == 4
        assert linha.melhor_amazon == Decimal("80.00")
        sem = linha_produto(s, catalogo["sem"])
        assert sem.situacao_casamento == "sem_candidato" and sem.melhor_amazon is None
        with pytest.raises(ValueError):
            linhas_catalogo(s, busca="", monitorado="talvez", categoria=None, situacao=None, com_preco=False, pagina=1)
        with pytest.raises(ValueError):
            linhas_catalogo(s, busca="", monitorado="todos", categoria=None, situacao="x", com_preco=False, pagina=1)


def test_contar_filtro_igual_ao_total_da_lista(sessoes, catalogo):
    filtros = [
        FiltroCatalogo(),
        FiltroCatalogo(monitorado="sim"),
        FiltroCatalogo(monitorado="nao", categoria="Caixas"),
        FiltroCatalogo(situacao="casado"),
        FiltroCatalogo(situacao="sem_candidato", com_preco=True),
        FiltroCatalogo(busca="bundle"),
    ]
    with sessoes() as s:
        for filtro in filtros:
            pagina = linhas_catalogo(
                s, busca=filtro.busca, monitorado=filtro.monitorado, categoria=filtro.categoria,
                situacao=filtro.situacao, com_preco=filtro.com_preco, pagina=1, por_pagina=2,
            )
            assert contar_filtro(s, filtro) == pagina.total, filtro
        assert contar_filtro(s, FiltroCatalogo()) == 6
        segunda = linhas_catalogo(
            s, busca="", monitorado="todos", categoria=None, situacao=None, com_preco=False, pagina=2, por_pagina=4
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
