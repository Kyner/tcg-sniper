from decimal import Decimal

from fakes import T0, criar_anuncio, criar_produto, oferta_lista

from tcg_sniper.admin import consultas
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db.models import SituacaoCheckout


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
    conferencias, _, _ = consultas.historico_conferencias(s, "todas", 1)
    leituras, _, _ = consultas.historico_monitor(s, 1)
    assert [linha.produto for linha in conferencias] == ["Produto Certo"]
    assert [linha.produto for linha in leituras] == ["Produto Certo"]
