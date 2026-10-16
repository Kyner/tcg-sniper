from decimal import Decimal

from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.ia.orcamento import motivo_sem_orcamento


def test_orcamento(s):
    cfg = repo_ia.obter_config_ia(s)  # teto dia 2.00, mês 20.00, 1000 chamadas
    G = repo_ia.Gasto
    assert motivo_sem_orcamento(cfg, G(Decimal("1.99"), Decimal("19.99"), 999)) is None
    assert "diário" in motivo_sem_orcamento(cfg, G(Decimal("2.00"), Decimal(2), 1))
    assert "mensal" in motivo_sem_orcamento(cfg, G(Decimal(0), Decimal("20.00"), 1))
    assert "chamadas" in motivo_sem_orcamento(cfg, G(Decimal(0), Decimal(0), 1000))


def test_teto_zero_bloqueia_tudo(s):
    cfg = repo_ia.obter_config_ia(s)
    cfg.teto_dia_usd = Decimal(0)
    assert motivo_sem_orcamento(cfg, repo_ia.Gasto(Decimal(0), Decimal(0), 0)) is not None
