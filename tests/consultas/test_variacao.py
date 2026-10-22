"""Pistas de variação no nome do produto da Liga e termos de variação no título do anúncio."""

from tcg_sniper.consultas.variacao import pistas_variacao, termos_variacao


def test_pistas_sem_foil_e_sem_idioma():
    assert pistas_variacao("Secret Lair - Goblingram") == ["sem Foil no nome", "idioma não informado"]


def test_pistas_foil():
    assert pistas_variacao("Secret Lair - Goblingram Foil Edition") == ["Foil", "idioma não informado"]


def test_pistas_idioma():
    assert pistas_variacao("Booster Box - Core Set 2019 (Inglês)") == ["sem Foil no nome", "inglês"]


def test_pistas_non_foil_vence_foil_e_outros_idiomas():
    assert pistas_variacao("Secret Lair - Goblingram Non-Foil (Japanese)") == ["Non-Foil", "japonês"]
    assert pistas_variacao("Coleção X (Português)") == ["sem Foil no nome", "português"]


def test_termos_non_foil_vence_foil():
    assert termos_variacao("MTG Secret Lair: Goblingram (Non-Foil Edition)") == ["Non-Foil"]


def test_termos_quantidade_e_idioma():
    assert termos_variacao("Yu-Gi-Oh! Booster Box 24 Packs English") == ["24 Packs", "English"]


def test_termos_por_palavra_sem_diferenciar_maiusculas():
    assert termos_variacao("Secret Lair FOIL edition 36 boosters") == ["FOIL", "36 boosters"]
    assert termos_variacao("Foiled Booster Englishman") == []
    assert termos_variacao("Caixa sem variação") == []
