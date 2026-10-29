from decimal import Decimal

from tcg_sniper.configuracoes.ia import CAMPOS_IA, validar_ia

VALIDO = {
    "ligado": "sim", "modelo": "gpt-5-mini", "esforco": "minimal",
    "preco_entrada_milhao_usd": "0,25", "preco_saida_milhao_usd": "2", "teto_dia_usd": "1,50",
    "teto_mes_usd": "15", "max_chamadas_dia": "500", "intervalo_min": "10", "lote": "30",
    "automatico": "não", "confianca_confirmar": "95", "confianca_ignorar": "85",
}


def test_valido():
    valores, erros = validar_ia(VALIDO)
    assert erros == {}
    assert set(valores) == set(CAMPOS_IA)
    assert valores["ligado"] is True and valores["automatico"] is False
    assert valores["preco_entrada_milhao_usd"] == Decimal("0.25") and valores["teto_dia_usd"] == Decimal("1.50")
    assert valores["lote"] == 30 and valores["esforco"] == "minimal"


def test_invalidos():
    ruins = {
        "ligado": "talvez", "modelo": "gpt 5", "esforco": "max", "preco_entrada_milhao_usd": "-1",
        "preco_saida_milhao_usd": "abc", "teto_dia_usd": "1.234", "teto_mes_usd": "", "max_chamadas_dia": "1.5",
        "intervalo_min": "0", "lote": "501", "automatico": "", "confianca_confirmar": "101", "confianca_ignorar": "-5",
    }
    _, erros = validar_ia(ruins)
    assert set(erros) == set(CAMPOS_IA)


def test_modelo_vazio_e_longo():
    assert "modelo" in validar_ia({**VALIDO, "modelo": ""})[1]
    assert "modelo" in validar_ia({**VALIDO, "modelo": "x" * 101})[1]
