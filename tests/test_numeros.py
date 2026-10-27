import pytest

from tcg_sniper.formatacao import com_nove_extra, mascarar_numero, normalizar_numero, ocultar_numero


@pytest.mark.parametrize(
    "texto",
    [
        "(11) 90000-0001",
        "11 90000-0001",
        "11900000001",
        "+55 11 90000-0001",
        "+55 (11) 90000.0001",
        "5511900000001",
        " +5511900000001 ",
    ],
)
def test_normalizar_numero_formatos(texto):
    assert normalizar_numero(texto) == "+5511900000001"


def test_normalizar_fixo_e_estrangeiro():
    assert normalizar_numero("(11) 3000-0001") == "+551130000001"
    assert normalizar_numero("+1 202 555 0100") == "+12025550100"


@pytest.mark.parametrize(
    "texto", ["", "abc", "123", "+0 11 90000-0001", "11 90000-00012345678", "１１９０００００００１", "+55 11 9000O-0001"]
)
def test_normalizar_recusa(texto):
    with pytest.raises(ValueError):
        normalizar_numero(texto)


def test_mascarar_numero():
    assert mascarar_numero("+5511900000034") == "+55 11 9****-**34"
    assert mascarar_numero("+551130000034") == "+55 11 3***-**34"
    assert mascarar_numero("+12025550134") == "+12 *******34"


def test_ocultar_numero_com_e_sem_mais():
    texto = 'HTTP 400: {"number":"5511900000034","jid":"5511900000034@s.whatsapp.net","n":"+5511900000034"}'
    oculto = ocultar_numero(texto, "+5511900000034")
    assert "900000034" not in oculto
    assert oculto.count("+55 11 9****-**34") == 3


def test_ocultar_numero_variante_sem_o_nove_extra():
    texto = '{"a":"551100000034","jid":"551100000034@s.whatsapp.net","b":"+551100000034","c":"5511900000034"}'
    oculto = ocultar_numero(texto, "+5511900000034")
    assert "00000034" not in oculto.replace("**34", "")
    assert oculto.count("+55 11 9****-**34") == 4


def test_ocultar_numero_fixo_nao_inventa_variante():
    assert ocultar_numero("x 551130000034 y", "+551130000034") == "x +55 11 3***-**34 y"


@pytest.mark.parametrize(
    "numero, esperado",
    [
        ("+551187654321", "+5511987654321"),
        ("+551167654321", "+5511967654321"),
        ("+551130000001", None),  # fixo (começa em 2-5) nunca vira celular
        ("+5511987654321", None),
        ("+12025550100", None),
    ],
)
def test_com_nove_extra(numero, esperado):
    assert com_nove_extra(numero) == esperado
