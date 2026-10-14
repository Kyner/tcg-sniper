import pytest

from tcg_sniper.coletor_amazon.termo import termo_busca


@pytest.mark.parametrize(
    ("nome", "termo"),
    [
        ("Caixa de Booster - Final Fantasy - Booster de Jogo", "Caixa de Booster Final Fantasy Booster de Jogo"),
        ("Kit de Pré Lançamento - Khans de Tarkir - Jeskai", "Kit de Pré Lançamento Khans de Tarkir Jeskai"),
        ("Booster Avulso - Final Fantasy - Value Booster", "Booster Avulso Final Fantasy Value Booster"),
        (
            "Kit Pré Lançamento - Dragões de Tarkir - Atarka (Battle With)",
            "Kit Pré Lançamento Dragões de Tarkir Atarka Battle With",
        ),
        ("Secret Lair: Deadpool / Marvel, Bundle", "Secret Lair Deadpool Marvel Bundle"),
        ("  Caixa –  Edição  ", "Caixa Edição"),
    ],
)
def test_termo_busca_mantem_o_nome_e_tira_so_a_pontuacao(nome, termo):
    assert termo_busca(nome) == termo
