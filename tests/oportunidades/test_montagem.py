from datetime import UTC, datetime
from decimal import Decimal

from tcg_sniper.db.models import PrecoAtualLiga, VendedorAmazon
from tcg_sniper.oportunidades import montagem, motor


def test_montagem_dos_dados_do_motor():
    assert montagem.vendedor_do_motor(None) is None
    v = VendedorAmazon(seller_id="X", nome="Loja", pct_positivas=Decimal(97), num_avaliacoes=300)
    assert montagem.vendedor_do_motor(v) == motor.Vendedor("Loja", Decimal(97), 300)
    assert montagem.ref_liga(None) == motor.RefLiga(None, None, None, None)
    quando = datetime(2026, 10, 20, tzinfo=UTC)
    liga = PrecoAtualLiga(produto_id=1, preco_a_partir=Decimal(1000), listagem_em=quando, num_lojas=4,
                          preco_medio=Decimal(1100))
    assert montagem.ref_liga(liga) == motor.RefLiga(Decimal(1000), quando, 4, Decimal(1100))
