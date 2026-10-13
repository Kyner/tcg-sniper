from tcg_sniper.coletor_liga.modelos import Pagina

TITULOS_DESAFIO = ("just a moment", "um momento")
# Marcadores exclusivos da página interstitial. Não usar "cf-turnstile" nem
# "/cdn-cgi/challenge-platform" sozinhos: o widget pode aparecer em formulários normais
# e o Cloudflare injeta scripts desse caminho em páginas comuns (ver teste com fixtures
# reais na Task 6).
MARCADORES_HTML = ('id="challenge-form"', "_cf_chl_opt", "cf-chl-")


def eh_desafio(pagina: Pagina) -> bool:
    titulo = pagina.titulo.strip().lower()
    if any(titulo.startswith(t) for t in TITULOS_DESAFIO):
        return True
    headers = {k.lower() for k in pagina.headers}
    if pagina.status in (403, 503) and "cf-mitigated" in headers:
        return True
    html = pagina.html.lower()
    return any(m in html for m in MARCADORES_HTML)
