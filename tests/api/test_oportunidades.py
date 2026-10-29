from datetime import timedelta

import pytest
from fakes import criar_anuncio, criar_preco_liga, criar_produto
from fakes_oportunidades import criar_atual_amazon, criar_oportunidade

from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import MotivoEncerramento, Papel, StatusCasamento

ROTAS = ["/api/oportunidades/resumo", "/api/oportunidades/ativas", "/api/oportunidades/encerradas",
         "/api/oportunidades/quase"]


@pytest.fixture
def dados(sessoes, relogio):
    agora = relogio()
    with sessoes() as s, s.begin():
        p = criar_produto(s, "api", nome="Final Fantasy")
        criar_preco_liga(s, p, "1000.00", listagem_em=agora)
        a = criar_anuncio(s, "B0API00001", p, StatusCasamento.CONFIRMADO)
        criar_atual_amazon(s, a, "800.00")
        criar_oportunidade(s, a, p, aberta_em=agora - timedelta(hours=1), preco_alertado="800")
        criar_oportunidade(s, a, p, aberta_em=agora - timedelta(days=1), fechada_em=agora - timedelta(hours=20),
                           motivo=MotivoEncerramento.PRECO_SUBIU)
        return p.id


def test_sem_sessao_401_e_sem_permissao_403(cliente, logar, sessoes):
    for rota in ROTAS:
        assert cliente.get(rota).status_code == 401
    with sessoes() as s, s.begin():
        repo_acesso.salvar_permissao(s, Papel.GRUPO, "ver_oportunidades", False)
    logar(Papel.GRUPO)
    for rota in [*ROTAS, "/api/produtos/1/historico"]:
        r = cliente.get(rota)
        assert r.status_code == 403 and r.json()["erro"] == "sem_permissao"


def test_periodo_invalido_400(cliente, logar):
    logar(Papel.GRUPO)
    r = cliente.get("/api/oportunidades/resumo?periodo=1a")
    assert r.status_code == 400 and r.json() == {"erro": "periodo_invalido", "mensagem": "Período inválido."}


def test_formatos_e_chaves_fechadas(cliente, logar, dados):
    logar(Papel.GRUPO)
    resumo = cliente.get("/api/oportunidades/resumo?periodo=7d").json()
    assert set(resumo) == {"periodo", "numeros", "por_dia"}
    assert resumo["numeros"]["diferenca_bruta"] == "500.00"
    ativas = cliente.get("/api/oportunidades/ativas").json()
    assert set(ativas) == {"ativas", "ultima_aberta_em"}
    assert set(ativas["ativas"][0]) == {"id", "produto", "anuncio", "preco_amazon", "preco_liga", "desconto_pct",
                                        "aberta_em", "em_risco_desde", "motivo_risco"}
    assert set(ativas["ativas"][0]["produto"]) == {"id", "nome", "imagem", "ativo"}
    assert set(ativas["ativas"][0]["anuncio"]) == {"titulo", "url", "imagem"}
    enc = cliente.get("/api/oportunidades/encerradas?periodo=tudo&motivo=preco_subiu").json()
    assert enc["total"] == 1 and enc["itens"][0]["motivo"] == "preco_subiu"
    assert set(enc["itens"][0]) == {"id", "produto", "aberta_em", "fechada_em", "aberta", "duracao_min", "alertas",
                                    "preco_alertado", "menor_preco", "preco_liga", "desconto_pct", "motivo", "anuncio"}
    assert set(enc["itens"][0]["anuncio"]) == {"titulo", "url", "imagem"}
    assert enc["itens"][0]["anuncio"]["url"] == "https://www.amazon.com.br/dp/B0API00001"
    quase = cliente.get("/api/oportunidades/quase").json()
    assert set(quase) == {"itens", "desconto_min_pct", "piso_pct"}
    hist = cliente.get(f"/api/produtos/{dados}/historico?periodo=30d").json()
    assert set(hist) == {"produto", "anuncio", "periodo", "escala", "amazon", "liga", "liga_medio",
                         "desconto_min_pct", "faixas", "oportunidades", "recorrencia_30d", "quase_la",
                         "sem_preco", "anuncios_casados"}
    assert hist["anuncio"]["url"].endswith("B0API00001") and hist["sem_preco"] is False
    assert hist["anuncios_casados"] == 1
    assert hist["oportunidades"][0]["anuncio"]["url"].endswith("B0API00001")
    texto = str([resumo, ativas, enc, quase, hist]).lower()
    for proibido in ("vendedor", "casamento", "mensagem", "imposto", "frete", "seller", "sbrauble", "media-amazon"):
        assert proibido not in texto


def test_imagem_vem_do_nosso_bucket_ou_nula(sessoes, config, relogio, dados):
    from fakes_api import logar as logar_cliente
    from fastapi.testclient import TestClient

    from tcg_sniper.api.app import criar_app
    from tcg_sniper.db.models import ProdutoLiga

    with sessoes() as s, s.begin():
        s.get(ProdutoLiga, dados).imagem_chave = "produtos/api.webp"
    for base, esperado in (("https://img.exemplo.test", "https://img.exemplo.test/produtos/api.webp"), (None, None)):
        cliente = TestClient(criar_app(sessoes, config.model_copy(update={"url_publica_imagens": base}), relogio))
        logar_cliente(sessoes, cliente, Papel.GRUPO, numero="+5511900000004" if base else "+5511900000005")
        ativa = cliente.get("/api/oportunidades/ativas").json()["ativas"][0]
        assert ativa["produto"]["imagem"] == esperado
        assert ativa["anuncio"]["imagem"] is None  # anúncio sem cópia


def test_produto_inexistente_404(cliente, logar):
    logar(Papel.GRUPO)
    r = cliente.get("/api/produtos/999999/historico")
    assert r.status_code == 404 and r.json()["erro"] == "nao_encontrado"


def test_quase_la_sem_limite_usa_200(sessoes, relogio, cliente, logar):
    agora = relogio()
    with sessoes() as s, s.begin():
        for i in range(201):
            p = criar_produto(s, f"quase{i}", nome=f"Quase {i}")
            criar_preco_liga(s, p, "1000.00", listagem_em=agora)
            criar_atual_amazon(s, criar_anuncio(s, f"BQ{i:08d}", p, StatusCasamento.CONFIRMADO), "850.00")  # 15%
    logar(Papel.GRUPO)
    assert len(cliente.get("/api/oportunidades/quase").json()["itens"]) == 200
    assert len(cliente.get("/api/oportunidades/quase?limite=5").json()["itens"]) == 5
