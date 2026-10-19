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


def ids(lista):
    return [produto_id for produto_id, _ in lista.produtos]


def test_grupos_na_ordem_e_cada_produto_uma_vez_so(s):
    casado = produto(s, "casado", lido_em=ANTIGO)
    par(s, casado, StatusCasamento.CONFIRMADO)
    par(s, casado, StatusCasamento.PENDENTE, "01")  # também tem candidato: fica só em casados
    candidato = produto(s, "candidato", lido_em=ANTIGO)
    par(s, candidato, StatusCasamento.PENDENTE)
    novo = produto(s, "novo")
    velhos = [produto(s, f"velho{i}", lido_em=ANTIGO) for i in range(7)]
    [do_dia] = [v for v in velhos if v.id % 7 == QUARTA.weekday()]

    lista = montar_lista(s, QUARTA, SP, 100, fixo)

    assert ids(lista) == [casado.id, candidato.id, novo.id, do_dia.id]
    assert (lista.casados, lista.candidatos, lista.novos, lista.rodizio) == (1, 1, 1, 1)
    assert lista.grupos() == "casados 1, candidatos 1, novos 1, rodízio 1"
    assert dict(lista.produtos)[novo.id] == novo.url


def test_rodizio_cobre_cada_produto_uma_vez_por_semana(s):
    assert SEGUNDA.weekday() == 0
    velhos = [produto(s, f"v{i}", lido_em=ANTIGO) for i in range(14)]
    vistos = []
    for dia in range(7):
        lista = montar_lista(s, SEGUNDA + timedelta(days=dia), SP, 100, fixo)
        assert all(produto_id % 7 == dia for produto_id in ids(lista))
        assert lista.rodizio == 2
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
