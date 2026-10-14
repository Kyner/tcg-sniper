import random

import pytest

from tcg_sniper.navegador.modelos import ErroRede
from tcg_sniper.navegador.ritmo import ESPERA_RETRY_S, com_um_retry, pausa_aleatoria, salvar_html_falha


def test_pausa_aleatoria_dorme_dentro_do_intervalo():
    dormidas = []
    rng = random.Random(1)
    for _ in range(50):
        pausa_aleatoria(8, 20, dormidas.append, rng)
    assert all(8 <= d <= 20 for d in dormidas)


def test_com_um_retry_tenta_de_novo_uma_vez_depois_de_esperar():
    tentativas, dormidas = [], []

    def abrir():
        tentativas.append(1)
        if len(tentativas) == 1:
            raise ErroRede("timeout")
        return "ok"

    assert com_um_retry(abrir, "https://x.test", dormidas.append) == "ok"
    assert len(tentativas) == 2
    assert dormidas == [ESPERA_RETRY_S]


def test_com_um_retry_desiste_na_segunda_falha():
    def abrir():
        raise ErroRede("fora do ar")

    with pytest.raises(ErroRede):
        com_um_retry(abrir, "https://x.test", lambda _: None)


def test_salvar_html_falha(tmp_path):
    caminho = salvar_html_falha(tmp_path, "amazon-1-2", "<html>x</html>")
    assert caminho == tmp_path / "falhas" / "amazon-1-2.html"
    assert caminho.read_text(encoding="utf-8") == "<html>x</html>"
