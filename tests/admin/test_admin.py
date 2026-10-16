import base64
import re
from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from fakes import T0, criar_produto
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from tcg_sniper.admin import consultas
from tcg_sniper.admin.app import criar_app, formatar_brl
from tcg_sniper.coletor_liga.modelos import ItemListagem, Resumo
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import EstadoColetorTipo, ProdutoLiga, StatusColeta, TipoColeta


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
        c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, T0)
        repo.finalizar_coleta(s, c.id, StatusColeta.OK, 1, 0, T0)
    r = cliente.get("/")
    assert r.status_code == 200
    assert "Rodar agora" in cliente.get("/servicos").text
    assert "<td>produtos</td>" in r.text


def test_index_pausado_mostra_retomar(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "desafio em /x", T0)
    r = cliente.get("/")
    assert "desafio em /x" in r.text and 'href="/servicos"' in r.text
    servicos = cliente.get("/servicos").text
    assert "Retomar" in servicos and "host.test:6080" in servicos


def test_retomar(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.pausar_por_desafio(s, "x", T0)
    r = cliente.post("/retomar", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/servicos?msg=retomar"
    with sessoes() as s:
        estado = repo.obter_estado(s)
        assert estado.estado is EstadoColetorTipo.ATIVO and estado.execucao_solicitada


def test_rodar_agora(cliente, sessoes):
    r = cliente.post("/rodar-agora", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/servicos?msg=rodar")
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


def item_listagem(liga_id, nome, preco, tipo="Caixas de Boosters"):
    return ItemListagem(
        liga_id=liga_id,
        nome=nome,
        url=f"https://liga.test/{liga_id}",
        preco_a_partir=None if preco is None else Decimal(preco),
        tipo=tipo,
    )


def test_catalogo_mostra_preco_a_partir_e_indisponivel(cliente, sessoes):
    with sessoes() as s, s.begin():
        c = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0)
        itens = [item_listagem("1", "Caixa Aetherdrift", "525.43"), item_listagem("2", "Caixa Magic 2010", None)]
        repo.gravar_listagem(s, c.id, itens, T0)
    r = cliente.get("/catalogo")
    assert "<th>À partir de</th>" in r.text and "<th>Categoria</th>" in r.text
    assert "R$ 525,43" in r.text and "Indisponível" in r.text and "Caixas de Boosters" in r.text
    assert "None" not in r.text  # sem resumo da página do produto, "Lojas" aparece como "—"


def test_detalhe_mostra_historico_da_listagem_e_rotulo_de_venda(cliente, sessoes):
    with sessoes() as s, s.begin():
        c1 = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0)
        repo.gravar_listagem(s, c1.id, [item_listagem("1", "Caixa Aetherdrift", "525.43")], T0)
        c2 = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0 + timedelta(days=1))
        repo.gravar_listagem(s, c2.id, [item_listagem("1", "Caixa Aetherdrift", None)], T0 + timedelta(days=1))
        produto_id = s.scalar(select(ProdutoLiga.id).where(ProdutoLiga.liga_id == "1"))
    r = cliente.get(f"/produto/{produto_id}")
    assert r.status_code == 200
    assert "Histórico do preço à partir de" in r.text and "Histórico de venda" in r.text
    assert "R$ 525,43" in r.text and "Indisponível" in r.text
    assert "13/10/2026 10:00" in r.text and "14/10/2026 10:00" in r.text  # T0 = 13:00 UTC = 10:00 em SP
    assert "None" not in r.text


def test_produto_so_com_listagem_mostra_traco_e_nunca_none(cliente, sessoes):
    with sessoes() as s, s.begin():
        c = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0)
        repo.gravar_listagem(s, c.id, [item_listagem("1", "Caixa Aetherdrift", "525.43")], T0)
        produto_id = s.scalar(select(ProdutoLiga.id).where(ProdutoLiga.liga_id == "1"))
    for url in ("/catalogo", f"/produto/{produto_id}"):
        r = cliente.get(url)
        assert r.status_code == 200
        assert "None" not in r.text
        assert "R$ 525,43" in r.text
    assert "<td>—</td>" in cliente.get("/catalogo").text
    assert "<strong>Lojas:</strong> —" in cliente.get(f"/produto/{produto_id}").text
    assert cliente.post(f"/produto/{produto_id}/ativo").status_code == 200


def test_index_com_coleta_rodando_mostra_andamento_e_esconde_rodar_agora(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0)
    r = cliente.get("/")
    assert "coleta em andamento" in r.text
    assert "Rodar agora" not in cliente.get("/servicos").text


def criar_muitos(sessoes, n):
    with sessoes() as s, s.begin():
        for i in range(n):
            criar_produto(s, f"p{i:03d}", nome=f"Produto {i:03d}")


def test_catalogo_pagina_100_linhas_com_total(cliente, sessoes):
    criar_muitos(sessoes, 250)
    r = cliente.get("/catalogo")
    assert "Página 1 de 3 · 250 produto(s)" in r.text
    assert "Produto 099" in r.text and "Produto 100" not in r.text
    assert "mostrando os primeiros" not in r.text
    r = cliente.get("/catalogo?pagina=3")
    assert "Página 3 de 3 · 250 produto(s)" in r.text
    assert "Produto 200" in r.text and "Produto 249" in r.text and "Produto 199" not in r.text


def test_catalogo_pagina_invalida_vira_1(cliente, sessoes):
    criar_muitos(sessoes, 150)
    for valor in ("0", "-2", "abc", "", "9" * 5000, "9" * 30):
        r = cliente.get("/catalogo", params={"pagina": valor})
        assert r.status_code == 200 and "Página 1 de 2" in r.text


def test_catalogo_pagina_alem_do_fim_mostra_ultima(cliente, sessoes):
    criar_muitos(sessoes, 150)
    r = cliente.get("/catalogo?pagina=99")
    assert "Página 2 de 2" in r.text and "Produto 149" in r.text


def test_catalogo_links_anterior_proxima_mantem_parametros(cliente, sessoes):
    criar_muitos(sessoes, 250)
    r = cliente.get("/catalogo?pagina=2&busca=Produto&filtro=ativos&com_preco=1")
    assert "Página 1 de 1 · 0 produto(s)" in r.text  # com_preco=1 esconde tudo (sem preço)
    r = cliente.get("/catalogo?pagina=2&busca=Produto&filtro=ativos")
    assert "Página 2 de 3" in r.text
    assert 'href="/catalogo?busca=Produto&amp;filtro=ativos&amp;pagina=1"' in r.text
    assert 'href="/catalogo?busca=Produto&amp;filtro=ativos&amp;pagina=3"' in r.text
    primeira = cliente.get("/catalogo").text
    assert "Anterior</a>" not in primeira and "Próxima</a>" in primeira


def test_catalogo_vazio_mostra_pagina_1_de_1(cliente):
    r = cliente.get("/catalogo")
    assert "Página 1 de 1 · 0 produto(s)" in r.text
    assert "Nenhum produto encontrado." in r.text


def gravar_listagem_tipos(sessoes):
    with sessoes() as s, s.begin():
        c = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0)
        repo.gravar_listagem(
            s,
            c.id,
            [
                item_listagem("1", "Caixa Alfa", "10.00", tipo="Caixas de Boosters"),
                item_listagem("2", "Caixa Beta", None, tipo="Caixas de Boosters"),
                item_listagem("3", "Bundle Gama", "20.00", tipo="Bundles"),
            ],
            T0,
        )


def test_catalogo_filtra_por_categoria_e_lista_opcoes(cliente, sessoes):
    gravar_listagem_tipos(sessoes)
    with sessoes() as s, s.begin():
        criar_produto(s, "sem-tipo", nome="Sem Tipo")
    r = cliente.get("/catalogo", params={"categoria": "Bundles"})
    assert r.status_code == 200
    assert "Bundle Gama" in r.text and "Caixa Alfa" not in r.text and "Sem Tipo" not in r.text
    assert '<option value="">todas as categorias</option>' in r.text
    assert r.text.index(">Bundles</option>") < r.text.index(">Caixas de Boosters</option>")
    assert '<option value="Bundles" selected>' in r.text
    assert "1 produto(s)" in r.text


def test_catalogo_categoria_desconhecida_400(cliente, sessoes):
    gravar_listagem_tipos(sessoes)
    assert cliente.get("/catalogo", params={"categoria": "Inexistente"}).status_code == 400


def test_catalogo_categoria_vazia_e_todas(cliente, sessoes):
    gravar_listagem_tipos(sessoes)
    r = cliente.get("/catalogo?categoria=")
    assert r.status_code == 200 and "Caixa Alfa" in r.text and "Bundle Gama" in r.text


def test_catalogo_so_com_preco(cliente, sessoes):
    gravar_listagem_tipos(sessoes)
    with sessoes() as s, s.begin():
        criar_produto(s, "sem-linha", nome="Sem Linha")
    r = cliente.get("/catalogo?com_preco=1")
    assert "Caixa Alfa" in r.text and "Bundle Gama" in r.text
    assert "Caixa Beta" not in r.text and "Sem Linha" not in r.text
    assert "2 produto(s)" in r.text
    assert 'name="com_preco" value="1" checked' in r.text
    assert "Sem Linha" in cliente.get("/catalogo").text


def test_catalogo_filtros_combinam(cliente, sessoes):
    gravar_listagem_tipos(sessoes)
    r = cliente.get("/catalogo?categoria=Caixas+de+Boosters&com_preco=1&busca=caixa&filtro=inativos")
    assert "Caixa Alfa" in r.text and "Caixa Beta" not in r.text and "Bundle Gama" not in r.text
    assert "1 produto(s)" in r.text
    assert "Nenhum produto encontrado." in cliente.get("/catalogo?categoria=Bundles&busca=caixa").text


def test_catalogo_ordem_estavel_com_nomes_iguais(cliente, sessoes):
    with sessoes() as s, s.begin():
        for i in range(120):
            criar_produto(s, f"x{i:03d}", nome="Mesmo Nome")
    ids = []
    for pagina in (1, 2):
        ids += re.findall(r'id="produto-(\d+)"', cliente.get(f"/catalogo?pagina={pagina}").text)
    assert len(ids) == 120 and len(set(ids)) == 120
    assert ids == sorted(ids, key=int)  # nomes iguais: o desempate por id é crescente entre as páginas


def test_catalogo_link_proxima_codifica_categoria_e_mantem_ordem(cliente, sessoes):
    tipo = "Caixas de Boosters/Promo ção"
    with sessoes() as s, s.begin():
        c = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0)
        itens = [item_listagem(f"q{i:03d}", f"Promo {i:03d}", "10.00", tipo=tipo) for i in range(101)]
        repo.gravar_listagem(s, c.id, itens, T0)
    r = cliente.get("/catalogo", params={"categoria": tipo, "com_preco": "1"})
    assert r.status_code == 200 and "Página 1 de 2 · 101 produto(s)" in r.text
    assert (
        'href="/catalogo?categoria=Caixas+de+Boosters%2FPromo+%C3%A7%C3%A3o&amp;com_preco=1&amp;pagina=2"'
        in r.text
    )


# --- ativação/desativação em lote ---


def ids_ativos(sessoes):
    with sessoes() as s:
        return {p.nome for p in s.scalars(select(ProdutoLiga)) if p.ativo}


def criar_lote(sessoes):
    """Cenário: 120 caixas inativas (110 com preço) + um bundle inativo com preço + uma caixa já ativa."""
    with sessoes() as s, s.begin():
        c = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0)
        itens = [
            item_listagem(f"c{i:03d}", f"Caixa {i:03d}", "10.00" if i < 110 else None) for i in range(120)
        ]
        itens.append(item_listagem("b1", "Bundle Um", "5.00", tipo="Bundles"))
        itens.append(item_listagem("c-ativa", "Caixa Ativa", "7.00"))
        repo.gravar_listagem(s, c.id, itens, T0)
        s.execute(update(ProdutoLiga).where(ProdutoLiga.liga_id == "c-ativa").values(ativo=True))


def test_condicoes_catalogo_compartilhadas_com_buscar_catalogo(sessoes):
    criar_lote(sessoes)
    agora = repo.agora_utc()
    with sessoes() as s:
        _, total, _, _ = consultas.buscar_catalogo(s, "caixa", "inativos", agora, "Caixas de Boosters", True)
        condicoes = consultas.condicoes_catalogo("caixa", "inativos", "Caixas de Boosters", True, agora)
        assert total == 110 and len(condicoes) == 4


def test_lote_respeita_categoria_com_preco_busca_e_filtro_em_varias_paginas(sessoes):
    criar_lote(sessoes)
    agora = repo.agora_utc()
    with sessoes() as s, s.begin():
        n = consultas.alterar_ativo_em_lote(s, True, "caixa", "inativos", "Caixas de Boosters", True, agora)
    assert n == 110  # 110 > POR_PAGINA: inclui as páginas seguintes; exclui sem preço, bundle e já ativa
    ativos = ids_ativos(sessoes)
    assert len(ativos) == 111 and "Caixa 109" in ativos and "Caixa 110" not in ativos
    assert "Bundle Um" not in ativos


def test_lote_conta_so_linhas_que_mudaram(sessoes):
    criar_lote(sessoes)
    agora = repo.agora_utc()
    with sessoes() as s, s.begin():
        assert consultas.alterar_ativo_em_lote(s, True, "", "todos", "Caixas de Boosters", False, agora) == 120
    with sessoes() as s, s.begin():  # "Caixa Ativa" já estava ativa e as demais agora também
        assert consultas.alterar_ativo_em_lote(s, True, "", "todos", "Caixas de Boosters", False, agora) == 0
        assert consultas.alterar_ativo_em_lote(s, False, "", "ativos", "Caixas de Boosters", False, agora) == 121


def test_lote_sem_com_preco_nao_precisa_de_juncao(sessoes):
    criar_lote(sessoes)
    with sessoes() as s, s.begin():
        n = consultas.alterar_ativo_em_lote(s, True, "Bundle", "todos", None, False, repo.agora_utc())
    assert n == 1


def test_lote_nao_toca_outras_colunas_nem_produtos_fora_do_filtro(sessoes):
    criar_lote(sessoes)
    agora = repo.agora_utc()

    def foto():
        with sessoes() as s:
            return {
                p.id: (p.nome, p.url, p.tipo, p.visto_primeiro_em, p.visto_ultimo_em, p.ativo)
                for p in s.scalars(select(ProdutoLiga))
            }

    antes = foto()
    with sessoes() as s, s.begin():
        consultas.alterar_ativo_em_lote(s, True, "", "todos", "Bundles", False, agora)
    depois = foto()
    mudou = [i for i in antes if antes[i] != depois[i]]
    assert len(mudou) == 1
    assert antes[mudou[0]][:-1] == depois[mudou[0]][:-1] and depois[mudou[0]][-1] is True


def test_lote_acao_invalida_400(cliente, sessoes):
    criar_lote(sessoes)
    r = cliente.post("/catalogo/lote", data={"acao": "apagar"}, follow_redirects=False)
    assert r.status_code == 400
    assert cliente.post("/catalogo/lote", data={"acao": "ativar", "filtro": "xyz"}).status_code == 400
    assert cliente.post("/catalogo/lote", data={"acao": "ativar", "categoria": "Nada"}).status_code == 400
    assert ids_ativos(sessoes) == {"Caixa Ativa"}


def test_lote_exige_autenticacao(sessoes, config):
    c = config.model_copy(update={"admin_senha": "segredo"})
    r = TestClient(criar_app(sessoes, c)).post("/catalogo/lote", data={"acao": "ativar"}, follow_redirects=False)
    assert r.status_code == 401


def test_lote_redireciona_com_filtros_e_mensagem(cliente, sessoes):
    criar_lote(sessoes)
    r = cliente.post(
        "/catalogo/lote",
        data={"acao": "ativar", "busca": "caixa", "filtro": "inativos", "categoria": "Caixas de Boosters", "com_preco": "1"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    destino = urlsplit(r.headers["location"])
    assert destino.path == "/catalogo"
    q = parse_qs(destino.query)
    assert q == {
        "busca": ["caixa"],
        "filtro": ["inativos"],
        "categoria": ["Caixas de Boosters"],
        "com_preco": ["1"],
        "pagina": ["1"],
        "msg": ["110 produto(s) ativado(s)."],
    }
    pagina = cliente.get(r.headers["location"])
    assert "110 produto(s) ativado(s)." in pagina.text
    desativar = cliente.post("/catalogo/lote", data={"acao": "desativar"}, follow_redirects=True)
    assert "111 produto(s) desativado(s)." in desativar.text


def test_msg_do_catalogo_e_so_texto_do_servidor(cliente):
    r = cliente.get("/catalogo", params={"msg": "<script>alert(1)</script>"})
    assert "<script>alert(1)</script>" not in r.text


def test_botoes_do_lote_mostram_total_e_confirmacao(cliente, sessoes):
    criar_muitos(sessoes, 250)
    r = cliente.get("/catalogo?busca=Produto&filtro=ativos")
    assert 'action="/catalogo/lote"' in r.text
    assert "Ativar todos os 250 deste filtro" in r.text and "Desativar todos os 250 deste filtro" in r.text
    assert "confirm(" in r.text and "250" in r.text.split("confirm(")[1].split(")")[0]
    assert '<input type="hidden" name="busca" value="Produto">' in r.text
    assert '<input type="hidden" name="filtro" value="ativos">' in r.text
    assert "17 s" in r.text


def test_botoes_do_lote_escondidos_sem_resultados(cliente):
    r = cliente.get("/catalogo")
    assert "Ativar todos" not in r.text and "Desativar todos" not in r.text
    assert "/catalogo/lote" not in r.text


def test_ciclo_da_amazon_rodando_nao_conta_como_coleta_da_liga_em_andamento(cliente, sessoes):
    with sessoes() as s, s.begin():
        repo.iniciar_coleta(s, TipoColeta.AMAZON, T0)
    assert "Rodar agora" in cliente.get("/servicos").text


def test_produto_ativo_liga_para_os_casamentos_do_produto_e_inativo_nao(cliente, sessoes):
    with sessoes() as s, s.begin():
        c = repo.iniciar_coleta(s, TipoColeta.LISTAGEM, T0)
        repo.gravar_listagem(s, c.id, [item_listagem("1", "Caixa Aetherdrift", "525.43")], T0)
        produto_id = s.scalar(select(ProdutoLiga.id).where(ProdutoLiga.liga_id == "1"))
    assert f"/casamentos/produto/{produto_id}" not in cliente.get(f"/produto/{produto_id}").text  # nasce inativo
    cliente.post(f"/produto/{produto_id}/ativo")
    assert f'href="/casamentos/produto/{produto_id}"' in cliente.get(f"/produto/{produto_id}").text
    cliente.post(f"/produto/{produto_id}/ativo")
    texto = cliente.get(f"/produto/{produto_id}").text
    assert f"/casamentos/produto/{produto_id}" not in texto and "aba=revisados" not in texto
