import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fakes import criar_anuncio, criar_produto
from fakes_oportunidades import criar_oportunidade

from tcg_sniper.consultas import dashboard
from tcg_sniper.consultas.catalogo import contar_esperando_decisao, situacao_catalogo
from tcg_sniper.consultas.painel import Aviso
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import ChamadaIA, StatusCasamento

AGORA = datetime(2026, 10, 16, 19, 40, tzinfo=UTC)
FONTES = Path(__file__).resolve().parents[2] / "src" / "tcg_sniper" / "consultas"


@pytest.mark.parametrize(
    ("antigo", "novo"),
    [
        ("/", "/gestao"),
        ("/servicos", "/gestao/servicos"),
        ("/logs?aba=liga", "/gestao/atividade?o_que=coleta_liga"),
        ("/logs?aba=amazon", "/gestao/atividade?o_que=busca"),
        ("/logs?aba=monitor", "/gestao/atividade?o_que=leitura_monitor"),
        ("/logs?aba=checkout", "/gestao/atividade?o_que=checkout"),
        ("/logs?aba=ia", "/gestao/atividade?o_que=ia"),
        ("/logs?aba=manutencao", "/gestao/atividade?o_que=backup"),
        ("/logs", "/gestao/atividade?o_que=coleta_liga"),
        ("/logs?aba=liga&liga_status=falha", "/gestao/atividade?o_que=coleta_liga&situacao=falha"),
        ("/logs?aba=amazon&amazon_status=parcial", "/gestao/atividade?o_que=busca&situacao=parcial"),
        ("/logs?aba=liga&liga_status=todos", "/gestao/atividade?o_que=coleta_liga"),
        ("/logs?aba=liga&liga_status=pausada_desafio", "/gestao/atividade?o_que=coleta_liga"),
        ("/logs?aba=ia&situacao=com_erro", "/gestao/atividade?o_que=ia&situacao=falha"),
        ("/logs?aba=ia&finalidade=termos", "/gestao/atividade?o_que=ia"),
        ("/logs?aba=inexistente", "/gestao/atividade"),
        ("/mensagens", "/gestao/atividade?o_que=mensagem"),
        ("/mensagens?situacao=falha", "/gestao/atividade?o_que=mensagem&situacao=falha"),
        ("/mensagens?situacao=pendente", "/gestao/atividade?o_que=mensagem&situacao=pendente"),
        ("/mensagens?destino=admin", "/gestao/atividade?o_que=mensagem&destino=admin"),
        ("/mensagens?situacao=falha&destino=individual", "/gestao/atividade?o_que=mensagem&situacao=falha&destino=individual"),
        ("/mensagens?destino=todos", "/gestao/atividade?o_que=mensagem"),
        ("/mensagens?destino=outro", "/gestao/atividade?o_que=mensagem"),
        ("/casamentos", "/gestao/casamentos"),
        ("/casamentos?situacao=todos&situacao_produto=sem_candidato", "/gestao/casamentos?situacao=sem_candidato"),
        ("/casamentos?situacao=pendentes", "/gestao/casamentos?situacao=esperando_decisao"),
        ("/casamentos?situacao=sem_par&busca=ab", "/gestao/casamentos?busca=ab&situacao=sem_candidato"),
        ("/casamentos?situacao=casados&com_preco=1", "/gestao/casamentos?situacao=casado&com_preco=true"),
        ("/casamentos/produto/7", "/gestao/casamentos/7"),
        ("/configuracoes", "/gestao/configuracoes"),
        ("/configuracoes?aba=ia", "/gestao/configuracoes"),
        ("/configuracoes?secao=geral", "/gestao/configuracoes?grupo=sistema"),
        ("/configuracoes?secao=liga", "/gestao/configuracoes?grupo=liga"),
        ("/configuracoes?secao=amazon", "/gestao/configuracoes?grupo=oportunidades"),
        ("/configuracoes?secao=ia", "/gestao/configuracoes?grupo=ia-decide"),
        ("/configuracoes?secao=avisos", "/gestao/configuracoes?grupo=whatsapp"),
        ("/configuracoes?secao=inexistente", "/gestao/configuracoes"),
        ("/ofertas", "/gestao/ofertas"),
        ("/ofertas?pagina=2", "/gestao/ofertas"),
        ("/produtos/3", "/produtos/3"),
        ("/algo-desconhecido", "/gestao"),
    ],
)
def test_destino_novo_traduz_cada_link_antigo(antigo, novo):
    assert dashboard.destino_novo(antigo) == novo


def test_destino_novo_desconhecido_avisa_no_log(caplog):
    with caplog.at_level("WARNING", logger="tcg_sniper.consultas.dashboard"):
        assert dashboard.destino_novo("/algo-desconhecido") == "/gestao"
        assert dashboard.destino_novo("/servicos") == "/gestao/servicos"
    assert [r.getMessage() for r in caplog.records] == ["link do painel sem destino novo: /algo-desconhecido"]


def test_destino_novo_cobre_todo_link_que_o_painel_emite(caplog):
    """Varre o código do painel e das mensagens: todo link literal vira destino migrado (ou as Configurações)."""
    texto = (FONTES / "painel.py").read_text(encoding="utf-8") + (FONTES / "mensagens.py").read_text(encoding="utf-8")
    links = set(re.findall(r'"(/(?:servicos|logs|mensagens|casamentos|configuracoes)[^"{]*)"', texto))
    assert {"/servicos", "/logs?aba=liga", "/logs?aba=manutencao", "/mensagens?situacao=falha", "/configuracoes?secao=ia"} <= links
    # Links montados com f-string (painel.py: `f"/logs?aba={aba}"`, abas liga e amazon): valores reais.
    assert 'f"/logs?aba={aba}"' in texto
    links |= {"/logs?aba=liga", "/logs?aba=amazon"}
    with caplog.at_level("WARNING", logger="tcg_sniper.consultas.dashboard"):
        for link in links:
            destino = dashboard.destino_novo(link)
            assert destino.startswith("/gestao"), (link, destino)
            assert destino != "/gestao", (link, destino)
    assert caplog.records == []  # link sem destino novo logaria a cada carga do Dashboard


def test_avisos_do_painel_apontam_para_a_secao_certa():
    texto = (FONTES / "painel.py").read_text(encoding="utf-8")
    assert "/configuracoes?secao=amazon" in texto and "/configuracoes?secao=ia" in texto
    assert not re.search(r'"/configuracoes"', texto)


def test_permissao_do_destino():
    assert dashboard.permissao_do_destino("/gestao/servicos") == "ver_servicos"
    assert dashboard.permissao_do_destino("/gestao/atividade?o_que=mensagem") == "ver_logs"
    assert dashboard.permissao_do_destino("/gestao/atividade?o_que=busca") == "ver_logs"
    assert dashboard.permissao_do_destino("/gestao/casamentos?situacao=casado") == "revisar_casamentos"
    assert dashboard.permissao_do_destino("/gestao/configuracoes?grupo=monitor") == "ver_configuracoes"
    assert dashboard.permissao_do_destino("/gestao/ofertas") == "ver_catalogo"
    assert dashboard.permissao_do_destino("/produtos/5") == "ver_oportunidades"


def test_destino_da_area_de_negocio_pede_tambem_ver_area_negocio():
    produto = dashboard.ItemPrecisa("x", "Ver", "/produtos/5", dashboard.permissao_do_destino("/produtos/5"))
    assert dashboard.pode_abrir(produto, {"ver_oportunidades", "ver_area_negocio"})
    assert not dashboard.pode_abrir(produto, {"ver_oportunidades"})
    assert not dashboard.pode_abrir(produto, {"ver_area_negocio"})
    servicos = dashboard.ItemPrecisa("x", "Ver", "/gestao/servicos", "ver_servicos")
    assert dashboard.pode_abrir(servicos, {"ver_servicos"})
    assert not dashboard.pode_abrir(servicos, {"ver_area_negocio"})
    assert dashboard.pode_abrir(dashboard.ItemPrecisa("x", "Ver", "/gestao", None), set())


def test_ligar_vira_ver_para_quem_nao_pode_pausar():
    item = dashboard.ItemPrecisa("LigaMagic pausado.", "Ligar", "/gestao/servicos", "ver_servicos")
    assert dashboard.rotulo_para(item, {"ver_servicos", "pausar_servicos"}) == "Ligar"
    assert dashboard.rotulo_para(item, {"ver_servicos"}) == "Ver"
    outro = dashboard.ItemPrecisa("x", "Ver o efeito", "/gestao/configuracoes", "ver_configuracoes")
    assert dashboard.rotulo_para(outro, set()) == "Ver o efeito"


def test_precisa_some_quando_nao_ha_nada(s, config):
    assert dashboard.precisa(s, AGORA, config, []) == []


def test_precisa_junta_decisoes_e_avisos_com_destino_novo(s, config):
    p = criar_produto(s, "x1")
    criar_anuncio(s, "B000000X10", p)
    avisos = [
        Aviso("error", "Liga parada.", "/servicos", "Ir para Serviços"),
        Aviso("error", "Confira o carrinho.", "/servicos", "Ir para Serviços", "/amazon/carrinho/7/conferido", "Já conferi"),
    ]
    itens = dashboard.precisa(s, AGORA, config, avisos)
    assert [(i.texto, i.rotulo, i.destino) for i in itens] == [
        ("1 produto esperando decisão.", "Revisar em sequência", "/gestao/casamentos?situacao=esperando_decisao"),
        ("Liga parada.", "Ir para Serviços", "/gestao/servicos"),
        ("Confira o carrinho.", "Ir para Serviços", "/gestao/servicos"),
    ]
    assert [i.requer for i in itens] == ["revisar_casamentos", "ver_servicos", "ver_servicos"]
    assert [i.acao for i in itens] == [
        None, None, dashboard.AcaoPrecisa("Já conferi", "/api/gestao/servicos/carrinho/7/conferido"),
    ]


def _gastar(s, usd, quando):
    s.add(ChamadaIA(em=quando, finalidade="casamento", modelo="m", tokens_entrada=1, tokens_saida=1,
                    custo_usd=Decimal(usd), ok=True))
    s.flush()


def test_ia_perto_do_teto_entra(s, config):
    teto = repo_ia.obter_config_ia(s, AGORA).teto_dia_usd
    _gastar(s, str(teto * Decimal("0.79")), AGORA - timedelta(minutes=5))
    assert dashboard.ia_perto_do_teto(s, AGORA, config) == []
    _gastar(s, str(teto * Decimal("0.02")), AGORA - timedelta(minutes=4))
    [item] = dashboard.ia_perto_do_teto(s, AGORA, config)
    assert "81% do teto do dia" in item.texto
    assert item.destino == "/gestao/configuracoes?grupo=ia-gasto" and item.requer == "ver_configuracoes"


def test_funil_soma_com_o_catalogo(s, config):
    esperando = criar_produto(s, "f1")
    criar_anuncio(s, "B000000F10", esperando)
    casado = criar_produto(s, "f2")
    criar_anuncio(s, "B000000F20", casado, StatusCasamento.CONFIRMADO)
    criar_anuncio(s, "B000000F21", casado, StatusCasamento.CONFIRMADO)
    ignorado = criar_produto(s, "f3")
    criar_anuncio(s, "B000000F30", ignorado, StatusCasamento.IGNORADO)
    criar_produto(s, "f4")
    criar_produto(s, "f5", ativo=False)
    f = dashboard.funil(s, AGORA, config)
    assert (f.liga, f.monitorados) == (5, 4)
    assert (f.casados_produtos, f.esperando_decisao, f.so_ignorados, f.sem_candidato) == (1, 1, 1, 1)
    assert f.casados_produtos + f.esperando_decisao + f.so_ignorados + f.sem_candidato == f.monitorados
    assert f.casados_anuncios == 2
    assert f.oportunidades == 0
    cat = situacao_catalogo(s, AGORA, config.zona)
    assert f.monitorados == cat.produtos_ativos and f.casados_produtos == cat.casado


def test_top_3_por_maior_desconto(s):
    for i, preco in enumerate(["900", "600", "800", "500"]):
        p = criar_produto(s, f"t{i}")
        a = criar_anuncio(s, f"B000000T{i}0", p)
        criar_oportunidade(s, a, p, aberta_em=AGORA, preco_alertado=preco, preco_liga="1000")
    fechada = criar_produto(s, "tf")
    af = criar_anuncio(s, "B000000TF0", fechada)
    criar_oportunidade(s, af, fechada, aberta_em=AGORA, preco_alertado="100", fechada_em=AGORA)
    top = dashboard.top_oportunidades(s)
    assert [t.preco_amazon for t in top] == [Decimal(500), Decimal(600), Decimal(800)]


def test_contar_esperando_decisao_igual_a_situacao_do_catalogo(s, config):
    a = criar_produto(s, "c1")
    criar_anuncio(s, "B000000C10", a)
    b = criar_produto(s, "c2")
    criar_anuncio(s, "B000000C20", b)
    criar_anuncio(s, "B000000C21", b, StatusCasamento.CONFIRMADO)  # casado: não espera
    criar_produto(s, "c3", ativo=False)
    inativo = criar_produto(s, "c4", ativo=False)
    criar_anuncio(s, "B000000C40", inativo)
    assert contar_esperando_decisao(s) == situacao_catalogo(s, AGORA, config.zona).esperando_decisao == 1


def test_monitor_atrasado_abre_configuracoes_com_ver_o_efeito(s, config):
    from zoneinfo import ZoneInfo

    from fakes import criar_preco_liga, oferta_lista

    from tcg_sniper.consultas import mensagens, painel
    from tcg_sniper.db import repositorio_amazon as repo_amz
    from tcg_sniper.db.models import Envio, OrigemPreco

    produto = criar_produto(s, "ma1")
    criar_preco_liga(s, produto, "1000.00", listagem_em=AGORA)
    anuncio = criar_anuncio(s, "B0MA000001", produto=produto, status=StatusCasamento.CONFIRMADO)
    lido_em = AGORA - timedelta(minutes=40)
    o = oferta_lista("700.00", vendedor="Amazon.com.br", seller_id="amazon", envio=Envio.AMAZON, posicao=0)
    repo_amz.gravar_ofertas(s, anuncio.id, lido_em, [repo_amz.OfertaAvaliada(o, None, True, True)])
    repo_amz.registrar_preco(
        s, anuncio.id, o.preco, OrigemPreco.OFERTAS, None, Envio.AMAZON, lido_em, ZoneInfo("America/Sao_Paulo")
    )
    avisos = painel.avisos(s, AGORA, config, [], mensagens.resumo(s, AGORA))
    [item] = [i for i in dashboard.precisa(s, AGORA, config, avisos) if "atrasado" in i.texto]
    assert item.rotulo == "Ver o efeito"
    assert item.destino == "/gestao/configuracoes?grupo=monitor"
    assert item.requer == "ver_configuracoes"


def test_aviso_de_servico_leva_ligar_ou_ver_conforme_o_estado():
    from tcg_sniper.consultas.painel import SaudeServico, avisos_backup

    pausado = SaudeServico("Backup", "pausado", "Backup desligado", "", "/servicos")
    falha = SaudeServico("Backup", "falha", "parou", "", "/servicos")
    desafio = SaudeServico("Backup", "pausado_desafio", "captcha", "", "/servicos")
    rotulos = [dashboard.rotulo_de(a) for sv in (pausado, falha, desafio) for a in avisos_backup(sv)]
    assert rotulos == ["Ligar", "Ver", "Ver"]


def test_nenhum_destino_do_dashboard_aponta_para_o_admin_antigo():
    assert not hasattr(dashboard, "PREFIXO_ANTIGO")
