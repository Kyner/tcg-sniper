import pytest

from tcg_sniper.coletor_amazon.termo import sequencia_de_termos, termo_busca


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


NOME = "Caixa de Booster - Alfa"


def test_sequencia_so_com_o_nome():
    assert sequencia_de_termos(NOME, None) == [NOME]


def test_sequencia_com_ingles_e_alternativos_sem_repetir():
    alternativos = ["alpha booster box", "caixa de booster: ALFA", "Booster Box: Alpha", "   ", "caixa alfa lacrada"]
    assert sequencia_de_termos(NOME, "Booster Box - Alpha", alternativos) == [
        NOME, "Booster Box - Alpha", "alpha booster box", "caixa alfa lacrada",
    ]


@pytest.mark.parametrize("nome_en", ["Caixa de Booster: Alfa", "CAIXA DE BOOSTER ALFA", "  -  ", "", None])
def test_ingles_igual_ao_portugues_ou_vazio_nao_entra(nome_en):
    assert sequencia_de_termos(NOME, nome_en) == [NOME]
