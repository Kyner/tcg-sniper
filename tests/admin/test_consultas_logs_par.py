from datetime import timedelta
from decimal import Decimal

from fakes import T0, criar_anuncio, criar_produto, oferta_lista

from tcg_sniper.consultas import historico
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db.models import Envio, SituacaoCheckout, StatusCasamento

HORA = timedelta(hours=1)


def test_logs_do_checkout_e_do_monitor_mostram_o_produto_confirmado(s):
    pendente = criar_produto(s, "pendente-log", nome="Produto Sugerido")
    certo = criar_produto(s, "certo-log", nome="Produto Certo")
    anuncio = criar_anuncio(s, "B0LOG00001", produto=pendente)
    repo_casamento.confirmar(s, anuncio.id, certo.id, T0)
    repo_amz.registrar_conferencia(
        s, em=T0, anuncio_id=anuncio.id, vendedor_nome="Loja", preco_anunciado=Decimal("1.00"), itens=None,
        frete=None, impostos=None, total=None, situacao=SituacaoCheckout.FALHA, motivo="m", item_removido=True,
    )
    repo_amz.gravar_ofertas(s, anuncio.id, T0, [repo_amz.OfertaAvaliada(oferta_lista(), None, True, True)])
    conferencias, _, _ = historico.historico_conferencias(s, "todas", 1)
    leituras, _, _ = historico.historico_monitor(s, 1)
    assert [linha.produto for linha in conferencias] == ["Produto Certo"]
    assert [linha.produto for linha in leituras] == ["Produto Certo"]


def _registrar_linhas(s, anuncio, em):
    repo_amz.registrar_conferencia(
        s, em=em, anuncio_id=anuncio.id, vendedor_nome="Loja", preco_anunciado=Decimal("1.00"), itens=None,
        frete=None, impostos=None, total=None, situacao=SituacaoCheckout.FALHA, motivo="m", item_removido=True,
    )
    repo_amz.gravar_ofertas(s, anuncio.id, em, [repo_amz.OfertaAvaliada(oferta_lista(), None, True, True)])


def _produtos_dos_logs(s):
    conferencias, _, _ = historico.historico_conferencias(s, "todas", 1)
    leituras, _, _ = historico.historico_monitor(s, 1)
    return [linha.produto for linha in conferencias], [linha.produto for linha in leituras]


def test_logs_sem_par_confirmado_mostram_o_par_mais_recente_do_anuncio(s):
    """Desfeito ou ignorado o confirmado, a linha antiga continua com produto: o par mexido por último."""
    outro = criar_produto(s, "outro-log", nome="Produto Outro")
    certo = criar_produto(s, "certo-log2", nome="Produto Certo")
    anuncio = criar_anuncio(s, "B0LOG00002", produto=outro)
    repo_casamento.confirmar(s, anuncio.id, certo.id, T0 + HORA)
    _registrar_linhas(s, anuncio, T0 + HORA)
    repo_casamento.ignorar(s, anuncio.id, certo.id, T0 + 2 * HORA)
    assert _produtos_dos_logs(s) == (["Produto Certo"], ["Produto Certo"])


def test_logs_mostram_o_produto_da_oportunidade_aberta_na_hora_da_linha(s):
    """Trocado o casamento depois, a linha antiga fica com o produto da oportunidade de então."""
    antes = criar_produto(s, "antes-log", nome="Produto De Antes")
    depois = criar_produto(s, "depois-log", nome="Produto De Depois")
    anuncio = criar_anuncio(s, "B0LOG00003", produto=antes, status=StatusCasamento.CONFIRMADO)
    repo_amz.abrir_oportunidade(
        s, anuncio_id=anuncio.id, produto_id=antes.id, preco_amazon=Decimal(1), preco_liga=Decimal(2),
        desconto_pct=Decimal(50), vendedor_id=None, envio=Envio.AMAZON, agora=T0, conferido=False,
    )
    _registrar_linhas(s, anuncio, T0 + HORA)
    repo_casamento.trocar(s, anuncio.id, depois.id, T0 + 2 * HORA)
    assert _produtos_dos_logs(s) == (["Produto De Antes"], ["Produto De Antes"])
