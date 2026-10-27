import re
from decimal import Decimal


def formatar_brl(valor: Decimal | None) -> str:
    if valor is None:
        return "—"
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def formatar_milhar(numero: int) -> str:
    """Inteiro com ponto de milhar ("1.234")."""
    return f"{numero:,}".replace(",", ".")


def formatar_bytes(tamanho: int | None) -> str:
    """Tamanho de arquivo em B, KB, MB ou GB (base 1024), com vírgula decimal."""
    if tamanho is None:
        return "—"
    if tamanho < 1024:
        return f"{tamanho} B"
    valor = float(tamanho)
    for unidade in ("KB", "MB", "GB"):
        valor /= 1024
        if valor < 1024 or unidade == "GB":
            break
    return f"{valor:.1f} {unidade}".replace(".", ",")


_NUMERO_E164 = re.compile(r"\+[1-9][0-9]{9,14}")
_SEPARADORES = re.compile(r"[\s().-]")


def normalizar_numero(texto: str) -> str:
    """Número de WhatsApp em E.164 ("+5511900000001"). Aceita espaços, parênteses, pontos e traços; sem "+",
    10 ou 11 dígitos (DDD + número) viram número do Brasil (+55). Levanta ValueError se não for um número válido."""
    bruto = texto.strip()
    com_mais = bruto.startswith("+")
    digitos = _SEPARADORES.sub("", bruto.removeprefix("+"))
    if not (digitos.isascii() and digitos.isdigit()):
        raise ValueError("número inválido")
    if not com_mais and len(digitos) in (10, 11):
        digitos = "55" + digitos
    numero = "+" + digitos
    if not _NUMERO_E164.fullmatch(numero):
        raise ValueError("número inválido")
    return numero


def com_nove_extra(numero: str) -> str | None:
    """Celular do Brasil digitado sem o 9 extra ("+551187654321", DDD + 8 dígitos começando em 6-9): a variante com o
    9 ("+5511987654321"). None para qualquer outro número; fixo (8 dígitos começando em 2-5) nunca vira celular."""
    if re.fullmatch(r"\+55[1-9][0-9][6-9][0-9]{7}", numero):
        return numero[:5] + "9" + numero[5:]
    return None


def mascarar_numero(numero: str) -> str:
    """Número para log e tela: "+5511900000034" vira "+55 11 9****-**34" (só DDD, o 1º e os 2 últimos dígitos)."""
    digitos = numero.removeprefix("+")
    if digitos.startswith("55") and len(digitos) in (12, 13):
        ddd, assinante = digitos[2:4], digitos[4:]
        return f"+55 {ddd} {assinante[0]}{'*' * (len(assinante) - 5)}-**{assinante[-2:]}"
    return f"+{digitos[:2]} {'*' * max(len(digitos) - 4, 1)}{digitos[-2:]}"


def ocultar_numero(texto: str, numero: str) -> str:
    """Troca o número (com ou sem "+") pela versão mascarada: texto de terceiros (erro da Evolution) que repete o
    número da pessoa não vai para log, banco de erros nem grupo."""
    mascarado = mascarar_numero(numero)
    digitos = numero.removeprefix("+")
    variantes = [numero, digitos]
    if digitos.startswith("55") and len(digitos) == 13 and digitos[4] == "9":
        # celular do Brasil sem o 9 extra (formato antigo, ainda aceito pelo WhatsApp)
        sem_nove = digitos[:4] + digitos[5:]
        variantes += ["+" + sem_nove, sem_nove]
    for variante in variantes:  # com "+" antes das versões sem, para não sobrar "+" solto
        texto = texto.replace(variante, mascarado)
    return texto
