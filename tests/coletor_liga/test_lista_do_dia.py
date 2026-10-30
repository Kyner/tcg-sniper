from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fakes import criar_anuncio, criar_produto

from tcg_sniper.coletor_liga.lista_do_dia import ListaDoDia, inicio_do_dia, montar_lista
from tcg_sniper.coletor_liga.modelos import Resumo
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db.models import StatusCasamento, TipoColeta

SP = ZoneInfo("America/Sao_Paulo")
SEGUNDA = datetime(2026, 10, 12, 12, 0, tzinfo=SP)
QUARTA = SEGUNDA + timedelta(days=2)
ANTIGO = SEGUNDA - timedelta(days=10)
# Lido há poucos dias: no rodízio só no dia da semana dele (sem atraso).
RECENTE = QUARTA - timedelta(days=2)


def fixo(_grupo):
    """Não embaralha: a ordem fica a de antes do sorteio."""


def produto(s, nome, lido_em=None, ativo=True, visto=ANTIGO):
    """Produto com (opcionalmente) um resumo gravado em `lido_em`."""
    p = criar_produto(s, nome, ativo=ativo, agora=visto)
    if lido_em is not None:
        c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, lido_em)
        repo.gravar_precos_produto(s, c.id, p.id, Resumo(None, None, None, 1), lido_em)
    return p


def par(s, p, status, sufixo="00"):
    criar_anuncio(s, f"B{p.id:07d}{sufixo}", produto=p, status=status)


def ler(s, produto_ids, quando):
    """O job leu estes produtos (grava um resumo para cada um)."""
    c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, quando)
    for pid in produto_ids:
        repo.gravar_precos_produto(s, c.id, pid, Resumo(None, None, None, 1), quando)


def ids(lista):
    return [produto_id for produto_id, _ in lista.produtos]


def test_grupos_na_ordem_e_cada_produto_uma_vez_so(s):
    casado = produto(s, "casado", lido_em=ANTIGO)
    par(s, casado, StatusCasamento.CONFIRMADO)
    par(s, casado, StatusCasamento.PENDENTE, "01")  # também tem candidato: fica só em casados
    candidato = produto(s, "candidato", lido_em=ANTIGO)
    par(s, candidato, StatusCasamento.PENDENTE)
    novo = produto(s, "novo")
    velhos = [produto(s, f"velho{i}", lido_em=RECENTE) for i in range(7)]
    [do_dia] = [v for v in velhos if v.id % 7 == QUARTA.weekday()]

    lista = montar_lista(s, QUARTA, SP, 100, fixo)

    assert ids(lista) == [casado.id, candidato.id, novo.id, do_dia.id]
    assert (lista.casados, lista.candidatos, lista.novos, lista.rodizio) == (1, 1, 1, 1)
    assert lista.grupos() == "casados 1, candidatos 1, novos 1, rodízio 1"
    assert dict(lista.produtos)[novo.id] == novo.url


def test_rodizio_cobre_cada_produto_uma_vez_por_semana(s):
    assert SEGUNDA.weekday() == 0
    velhos = [produto(s, f"v{i}", lido_em=SEGUNDA - timedelta(days=1)) for i in range(14)]
    vistos = []
    for dia in range(7):
        agora = SEGUNDA + timedelta(days=dia)
        lista = montar_lista(s, agora, SP, 100, fixo)
        assert all(produto_id % 7 == dia for produto_id in ids(lista))
        assert (lista.rodizio, lista.atrasados) == (2, 0)
        ler(s, ids(lista), agora)
        vistos += ids(lista)
    assert sorted(vistos) == sorted(v.id for v in velhos)


def test_novos_ate_o_teto_os_mais_antigos_primeiro(s):
    novos = [produto(s, f"n{i}", visto=ANTIGO + timedelta(days=5 - i)) for i in range(5)]  # n4 é o mais antigo
    lista = montar_lista(s, QUARTA, SP, 3, fixo)
    assert ids(lista) == [novos[4].id, novos[3].id, novos[2].id]
    assert lista.novos == 3
    assert montar_lista(s, QUARTA, SP, 0, fixo).produtos == ()


def test_novo_alem_do_teto_nao_entra_no_rodizio(s):
    novos = [produto(s, f"n{i}") for i in range(7)]  # mesmo visto_primeiro_em: desempate pelo id
    lista = montar_lista(s, QUARTA, SP, 1, fixo)
    assert ids(lista) == [novos[0].id]
    assert (lista.novos, lista.rodizio) == (1, 0)


def test_lido_hoje_fica_de_fora_e_a_meia_noite_e_a_do_fuso(s):
    meia_noite = inicio_do_dia(QUARTA, SP)
    assert meia_noite == datetime(2026, 10, 14, 0, 0, tzinfo=SP)
    hoje = produto(s, "hoje", lido_em=meia_noite + timedelta(minutes=1))
    par(s, hoje, StatusCasamento.CONFIRMADO)
    ontem = produto(s, "ontem", lido_em=meia_noite - timedelta(minutes=1))  # 23:59 local = 02:59 UTC de hoje
    par(s, ontem, StatusCasamento.CONFIRMADO)
    lista = montar_lista(s, QUARTA, SP, 100, fixo)
    assert ids(lista) == [ontem.id]
    assert lista.casados == 1


def test_inativo_fica_de_fora_e_ignorado_nao_e_candidato(s):
    inativo = produto(s, "inativo", lido_em=ANTIGO, ativo=False)
    par(s, inativo, StatusCasamento.CONFIRMADO)
    so_ignorado = produto(s, "ignorado", lido_em=ANTIGO)
    par(s, so_ignorado, StatusCasamento.IGNORADO)
    lista = montar_lista(s, QUARTA, SP, 100, fixo)
    assert inativo.id not in ids(lista)
    assert (lista.casados, lista.candidatos) == (0, 0)


def test_embaralha_cada_grupo_separado(s):
    casados = [produto(s, f"c{i}", lido_em=ANTIGO) for i in range(2)]
    for c in casados:
        par(s, c, StatusCasamento.CONFIRMADO)
    novos = [produto(s, f"n{i}") for i in range(2)]
    chamadas = []

    def inverter(grupo):
        chamadas.append(len(grupo))
        grupo.reverse()

    lista = montar_lista(s, QUARTA, SP, 100, inverter)
    assert chamadas == [2, 0, 2, 0]  # casados, candidatos, novos, rodízio
    assert ids(lista) == [casados[1].id, casados[0].id, novos[1].id, novos[0].id]


def test_sem_produtos_a_lista_e_vazia(s):
    assert montar_lista(s, QUARTA, SP, 100, fixo) == ListaDoDia((), 0, 0, 0, 0)


def test_teto_de_novos_vale_para_o_dia_inteiro_e_renova_amanha(s):
    novos = [produto(s, f"n{i}") for i in range(6)]
    primeira = montar_lista(s, QUARTA, SP, 4, fixo)
    assert ids(primeira) == [n.id for n in novos[:4]]
    for pid in ids(primeira)[:3]:  # o job leu 3 e parou
        c = repo.iniciar_coleta(s, TipoColeta.PRODUTOS, QUARTA)
        repo.gravar_precos_produto(s, c.id, pid, Resumo(None, None, None, 1), QUARTA)
    segunda = montar_lista(s, QUARTA + timedelta(hours=1), SP, 4, fixo)
    assert ids(segunda) == [novos[3].id]  # 4 - 3 já lidos hoje; os 3 lidos saem da lista
    assert segunda.novos == 1
    amanha = montar_lista(s, QUARTA + timedelta(days=1), SP, 4, fixo)
    assert amanha.novos == 3  # n3..n5: o teto de amanhã está cheio de novo
    assert len(set(ids(segunda)) | set(ids(primeira)[:3])) <= 4


def test_casado_ou_candidato_lido_hoje_nao_reduz_o_teto_de_novos(s):
    casado = produto(s, "casado", lido_em=QUARTA)
    par(s, casado, StatusCasamento.CONFIRMADO)
    candidato = produto(s, "candidato", lido_em=QUARTA)
    par(s, candidato, StatusCasamento.PENDENTE)
    novos = [produto(s, f"n{i}") for i in range(3)]
    lista = montar_lista(s, QUARTA + timedelta(hours=1), SP, 2, fixo)
    assert ids(lista) == [n.id for n in novos[:2]]


def test_novo_que_falha_3_vezes_sai_dos_novos_do_dia(s):
    ruim = produto(s, "ruim")
    bom = produto(s, "bom")
    for _ in range(2):
        repo.registrar_falha_pagina(s, ruim.id)
    assert ids(montar_lista(s, QUARTA, SP, 1, fixo)) == [ruim.id]  # com 2 falhas ainda é o primeiro dos novos
    repo.registrar_falha_pagina(s, ruim.id)
    lista = montar_lista(s, QUARTA, SP, 1, fixo)
    assert ids(lista) == [bom.id] and lista.novos == 1  # o teto do dia vai para o próximo novo
    # sem resumo, segue no rodízio do dia da semana dele
    do_dia = montar_lista(s, SEGUNDA + timedelta(days=ruim.id % 7), SP, 0, fixo)
    assert ids(do_dia) == [ruim.id] and do_dia.rodizio == 1


def test_rodizio_nao_lido_no_dia_passa_para_os_proximos_dias(s):
    # Sexta cortada por um desafio: o produto da sexta não lido entra no sábado como atrasado.
    sexta = SEGUNDA + timedelta(days=4)
    velhos = [produto(s, f"v{i}") for i in range(7)]
    [da_sexta] = [v for v in velhos if v.id % 7 == sexta.weekday()]
    ler(s, [da_sexta.id], sexta - timedelta(days=7))  # a última leitura dele foi na sexta passada
    ler(s, [v.id for v in velhos if v is not da_sexta], sexta - timedelta(days=2))
    assert ids(montar_lista(s, sexta, SP, 100, fixo)) == [da_sexta.id]  # o job parou antes de ler
    sabado = montar_lista(s, sexta + timedelta(days=1), SP, 100, fixo)
    [do_sabado] = [v for v in velhos if v.id % 7 == 5]
    assert ids(sabado) == [da_sexta.id, do_sabado.id]  # atrasado antes do rodízio do dia
    assert (sabado.atrasados, sabado.rodizio) == (1, 1)
    assert sabado.grupos() == "casados 0, candidatos 0, novos 0, rodízio 1, atrasados 1"
    ler(s, [da_sexta.id], sexta + timedelta(days=1))
    assert da_sexta.id not in ids(montar_lista(s, sexta + timedelta(days=2), SP, 100, fixo))


def test_atrasados_mais_antigos_primeiro_e_lido_na_semana_nao_atrasa(s):
    fora_do_dia = [v for v in (produto(s, f"v{i}") for i in range(14)) if v.id % 7 != QUARTA.weekday()]
    antigo, menos_antigo, da_semana = fora_do_dia[:3]
    ler(s, [menos_antigo.id], QUARTA - timedelta(days=8))
    ler(s, [antigo.id], QUARTA - timedelta(days=20))
    ler(s, [da_semana.id], inicio_do_dia(QUARTA, SP) - timedelta(days=6))  # ainda dentro dos 7 dias
    lista = montar_lista(s, QUARTA, SP, 0, fixo)
    assert ids(lista) == [antigo.id, menos_antigo.id]
    assert lista.atrasados == 2


def test_atrasado_que_falha_3_vezes_fica_so_no_dia_dele(s):
    [ruim] = [v for v in (produto(s, f"v{i}", lido_em=ANTIGO) for i in range(7)) if v.id % 7 != QUARTA.weekday()][:1]
    for _ in range(3):
        repo.registrar_falha_pagina(s, ruim.id)
    assert ruim.id not in ids(montar_lista(s, QUARTA, SP, 0, fixo))


def test_atrasados_tem_teto_por_dia_que_vale_entre_execucoes(s, monkeypatch):
    from tcg_sniper.coletor_liga import lista_do_dia

    monkeypatch.setattr(lista_do_dia, "ATRASADOS_POR_DIA", 2)
    fora_do_dia = [v for v in (produto(s, f"v{i}") for i in range(21)) if v.id % 7 != QUARTA.weekday()][:4]
    for dias, v in zip((30, 20, 10, 9), fora_do_dia, strict=True):
        ler(s, [v.id], QUARTA - timedelta(days=dias))
    primeira = montar_lista(s, QUARTA, SP, 0, fixo)
    assert ids(primeira) == [fora_do_dia[0].id, fora_do_dia[1].id]  # os 2 mais antigos
    ler(s, [fora_do_dia[0].id], QUARTA)  # o job leu 1 e parou
    segunda = montar_lista(s, QUARTA + timedelta(hours=1), SP, 0, fixo)
    assert ids(segunda) == [fora_do_dia[1].id]  # o teto do dia já gastou 1
    amanha = montar_lista(s, QUARTA + timedelta(days=1), SP, 0, fixo)
    assert amanha.atrasados == 2
