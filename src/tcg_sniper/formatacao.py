from decimal import Decimal


def formatar_brl(valor: Decimal | None) -> str:
    if valor is None:
        return "—"
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


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
