import base64
from datetime import timedelta
from decimal import Decimal

import pytest
from fakes import T0, criar_produto
from fastapi.testclient import TestClient

from tcg_sniper.admin.app import criar_app, formatar_brl
from tcg_sniper.coletor_liga.modelos import Resumo
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import EstadoColetorTipo, ProdutoLiga, TipoColeta


def basic(usuario, senha):
    return "Basic " + base64.b64encode(f"{usuario}:{senha}".encode()).decode()


@pytest.fixture
def cliente(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    return TestClient(criar_app(sessoes, c), headers={"Authorization": basic("admin", "segredo")})


def test_formatar_brl():
    assert formatar_brl(Decimal("1234.5")) == "R$ 1.234,50"
    assert formatar_brl(Decimal("0.99")) == "R$ 0,99"
    assert formatar_brl(None) == "—"


def test_sem_senha_401(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    assert TestClient(criar_app(sessoes, c)).get("/").status_code == 401


def test_senha_errada_401(sessoes, config):
    cfg = config.model_copy(update={"admin_senha": "segredo"})
    c = TestClient(criar_app(sessoes, cfg), headers={"Authorization": basic("admin", "errada")})
    assert c.get("/").status_code == 401


@pytest.mark.parametrize("senha", ["", "   ", "trocar-esta-senha"])
def test_criar_app_recusa_senha_vazia_ou_padrao(sessoes, config, senha):
    with pytest.raises(ValueError, match="ADMIN_SENHA"):
        criar_app(sessoes, config.model_copy(update={"admin_senha": senha}))


def test_index_mostra_estado_e_coletas(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0)
    r = cliente.get("/")
    assert r.status_code == 200
    assert "Rodar agora" in r.text
    assert "<td>produtos</td>" in r.text


def test_index_pausado_mostra_retomar(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em /x", T0)
    r = cliente.get("/")
    assert "Retomar" in r.text and "desafio em /x" in r.text and "host.test:6080" in r.text


def test_retomar(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "x", T0)
    r = cliente.post("/retomar", follow_redirects=False)
    assert r.status_code == 303
    with sessoes() as s:
        estado = repo.obter_estado(s)
        assert estado.estado is EstadoColetorTipo.ATIVO and estado.execucao_solicitada


def test_rodar_agora(cliente, sessoes):
    assert cliente.post("/rodar-agora", follow_redirects=False).status_code == 303
    with sessoes() as s:
        assert repo.obter_estado(s).execucao_solicitada


def test_busca_trata_curingas_literalmente(cliente, sessoes):
    with sessoes() as s, s.begin():
        criar_produto(s, "a", nome="Caixa 100% Foil")
        criar_produto(s, "b", nome="Caixa 1000 boosters")
        criar_produto(s, "c", nome="Bundle_Especial")
        criar_produto(s, "d", nome="Bundle Especial")
    r = cliente.get("/catalogo", params={"busca": "100%"})
    assert "Caixa 100% Foil" in r.text and "Caixa 1000 boosters" not in r.text
    r = cliente.get("/catalogo", params={"busca": "Bundle_"})
    assert "Bundle_Especial" in r.text and "Bundle Especial" not in r.text  # "_" não é curinga


def test_filtros(cliente, sessoes):
    agora = repo.agora_utc()
    with sessoes() as s, s.begin():
        criar_produto(s, "a", nome="Ativo antigo", ativo=True, agora=agora - timedelta(days=30))
        criar_produto(s, "b", nome="Inativo novo", ativo=False, agora=agora - timedelta(days=1))
    assert "Ativo antigo" in cliente.get("/catalogo?filtro=ativos").text
    assert "Inativo novo" not in cliente.get("/catalogo?filtro=ativos").text
    assert "Inativo novo" in cliente.get("/catalogo?filtro=inativos").text
    novos = cliente.get("/catalogo?filtro=novos").text
    assert "Inativo novo" in novos and "Ativo antigo" not in novos


def test_filtro_invalido_400(cliente):
    assert cliente.get("/catalogo?filtro=xyz").status_code == 400


def test_toggle_ativo(cliente, sessoes):
    with sessoes() as s, s.begin():
        produto_id = criar_produto(s, "a", ativo=False).id
    r = cliente.post(f"/produto/{produto_id}/ativo")
    assert r.status_code == 200
    assert f'id="produto-{produto_id}"' in r.text and ">Ativo</button>" in r.text
    with sessoes() as s:
        assert s.get(ProdutoLiga, produto_id).ativo is True


def test_toggle_inexistente_404(cliente):
    assert cliente.post("/produto/999999/ativo").status_code == 404


def test_detalhe_produto_mostra_preco_e_historico(cliente, sessoes):
    with sessoes() as s, s.begin():
        produto = criar_produto(s, "a", nome="Caixa Duskmourn")
        resumo = Resumo(Decimal("1234.56"), Decimal("1500.00"), Decimal("1999.90"), 7)
        c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0)
        repo.gravar_precos_produto(s, c.id, produto.id, resumo, T0)
    r = cliente.get(f"/produto/{produto.id}")
    assert r.status_code == 200
    assert "Caixa Duskmourn" in r.text
    for texto in ("Mín", "Médio", "Máx", "Lojas", "R$ 1.234,56", "R$ 1.500,00", "R$ 1.999,90", "<td>7</td>"):
        assert texto in r.text


def test_detalhe_inexistente_404(cliente):
    assert cliente.get("/produto/999999").status_code == 404


def test_catalogo_mostra_preco_min_e_lojas(cliente, sessoes):
    with sessoes() as s, s.begin():
        produto = criar_produto(s, "a", nome="Caixa Duskmourn")
        c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0)
        repo.gravar_precos_produto(s, c.id, produto.id, Resumo(Decimal("899.90"), None, None, 12), T0)
    r = cliente.get("/catalogo")
    assert "<th>Mín</th>" in r.text and "<th>Lojas</th>" in r.text
    assert "R$ 899,90" in r.text and "<td>12</td>" in r.text
