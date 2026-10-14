from tcg_sniper.navegador.modelos import Pagina

# Marcadores exclusivos da página de verificação ("robot check") da Amazon. Conferidos contra
# páginas normais reais na Task 7 (nenhuma fixture normal pode casar).
MARCADORES_HTML = (
    'action="/errors/validatecaptcha"',
    "digite os caracteres que você vê",
    "api-services-support@amazon.com",
)


def eh_desafio_amazon(pagina: Pagina) -> bool:
    html = pagina.html.lower()
    return any(marcador in html for marcador in MARCADORES_HTML)
