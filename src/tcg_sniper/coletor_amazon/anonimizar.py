"""Limpa e anonimiza páginas reais da Amazon antes de virarem fixture (o repositório é público).

`limpar` tira scripts, estilos, imagens, comentários e todo atributo fora de uma lista curta (sem
`data-*` com JSON, sem valor de campo oculto, links reduzidos a /dp/<ASIN> ou seller=<ID>);
`anonimizar` troca CPF, CNPJ, CEP, final de cartão, e-mail, telefone (celular e fixo), número de pedido e os textos de
`proibidos` por valores fictícios (número proibido leva junto os dígitos vizinhos), troca a bandeira do
cartão e ids de pedido/item/sessão nos atributos por fictícios estáveis; no carrinho, os itens do "Salvo
para depois" viram "Produto salvo N" / B0SALVO00N; `achados` lista o que ainda parece dado pessoal (o script e o
teste de privacidade usam). Em `proibidos` liste também o primeiro nome e o sobrenome em linhas
separadas (nome completo, rua, bairro, telefone...): saudação e linha de entrega são trocadas por
padrão, mas o resto só some se estiver na lista."""

import re
from collections.abc import Sequence
from html import escape, unescape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

TAGS_REMOVIDAS = ["script", "style", "link", "noscript", "img", "svg", "iframe", "template", "meta"]
ATRIBUTOS_MANTIDOS = frozenset(
    {
        "id",
        "class",
        "name",
        "type",
        "value",
        "role",
        "aria-label",
        "aria-labelledby",
        "href",
        "data-asin",
        "data-name",
        "data-action",
        "data-itemtype",
        "data-testid",
        "data-feature-id",
    }
)

# Blocos mantidos por tipo de página (None: o corpo inteiro). O painel guarda também os botões da
# página do produto ("Comprar agora" inclusive), para os testes provarem que nunca são clicados.
BLOCOS: dict[str, tuple[str, ...] | None] = {
    "ofertas": None,
    "painel": (
        "#nav-cart-count",  # a conferência relê o contador do carrinho nesta página antes de adicionar
        "#aod-pinned-offer",
        "#aod-offer-list",
        "#aod-offer",
        "#buy-now-button",
        "#add-to-cart-button",
    ),
    "carrinho": (
        "#nav-cart-count",
        "#nav-item-signout",  # "Sair da conta": prova que a página é da conta logada (não um carrinho de visitante)
        '[data-name="Active Items"]',
        "#sc-active-cart",
        "#activeCartViewForm",
        '[data-name="Subtotals"]',
        "#sc-buy-box",
        '[data-name="Saved Items"]',
        "#sc-saved-cart",
    ),
    "checkout": None,
    "login": None,
}

# Tipos de página com dados do usuário logado (nome, endereço, cartão): sem `proibidos` o script recusa.
TIPOS_COM_DADOS_PESSOAIS = frozenset({"checkout", "carrinho", "login", "ofertas"})

FICTICIOS = {
    "cpf": "000.000.000-00",
    "cep": "01001-000",
    "cartao": "0000",
    "email": "fulano@exemplo.com",
    "telefone": "(11) 90000-0000",
    "pedido": "000-0000000-0000000",
    "texto": "Fulano de Tal",
    "cep_bruto": "01001000",
    "cpf_bruto": "00000000000",
    "cnpj": "00.000.000/0000-00",
    "cnpj_bruto": "00000000000000",
    "telefone_bruto": "1130000000",
    "numero": "0000",
    "pagando": "Pagando com cartão final 0000",
}

_RE_CPF = re.compile(r"(?<![\d*])[\d*]{3}\.[\d*]{3}\.[\d*]{3}-[\d*]{2}(?![\d*])")
_RE_CEP = re.compile(r"(?<!\d)\d{5}-\d{3}(?!\d)")
# Entre "cartão" e os 4 dígitos: tags e texto sem dígito e sem moeda ("valor final R$ 1299" é preço).
_GAP = r"(?:<[^>]*>|(?!R\$|\$|BRL)[^\d<]){0,60}?"
# Depois de "final"/"terminado em": os 4 dígitos logo em seguida (só tags, espaço e pontuação no meio).
_GAP_CURTO = r"(?:<[^>]*>|[\s:.•*-]){0,12}?"
_RES_CARTAO = (
    re.compile(r"(?i)(cart[aã]o)(" + _GAP + r")(\d{4})(?!\d|[,.]\d)"),
    re.compile(
        r"(?i)(\bfinal\b|terminad[oa] em|terminando em|termina em|ending in)(" + _GAP_CURTO + r")(\d{4})(?!\d|[,.]\d)"
    ),
    re.compile(r"(?i)([•*]{3,}|\bx{4,})((?:<[^>]*>|\s){0,10}?)(\d{4})(?!\d|,\d)"),
)
_RE_EMAIL = re.compile(r"[\w.+*•-]+@(?!amazon\.)[\w-]+(?:\.[\w-]+)+")
_RE_TELEFONE = re.compile(
    r"\+\s?55[\s-]?\(?\d{2}\)?[\s-]?\d{4,5}[\s-]?\d{4}(?!\d)"  # +55 11 98765-4321, +5511987654321
    r"|(?<![\w+])\(?\d{2}\)?[\s-]?9\d{4}[\s-]?\d{4}(?!\d)"  # (11) 98765-4321, 11 98765 4321
)
_RE_NUMERO_DE_TELEFONE = re.compile(r"(?i)(N[uú]mero de telefone\s*:?(?:\s|<[^>]*>)*)([^<\s][^<]*)")
_RE_PAGANDO = re.compile(r"(?i)Pagando com\b[^<]*")
_RE_FIXO = re.compile(r"\(\d{2}\)\s?\d{4}-\d{4}(?!\d)")
# Fixo sem parênteses: DDD, espaço ou traço e o número de 8 dígitos com traço (fixo começa em 2 a 5).
_RE_FIXO_SEM_PARENTESES = re.compile(r"(?<![\w+.,/$-])[1-9]\d[\s-][2-5]\d{3}-\d{4}(?![\d-])")
# DDD + número só com dígitos (10 ou 11), só logo depois de uma palavra de telefone.
_RE_TELEFONE_BRUTO = re.compile(
    r"(?i)(\b(?:telefone|tel|fone|celular|cel|contato|whatsapp)\b(?:<[^>]*>|[^\w<]){0,8})(\d{10,11})(?!\d)"
)
_RE_CEP_BRUTO = re.compile(r"(?i)(\bCEP(?:<[^>]*>|[^\w<]){0,5})(\d{8})(?!\d)")
_RE_CPF_BRUTO = re.compile(r"(?i)(\bCPF(?:<[^>]*>|[^\w<]){0,8})(\d{11})(?!\d)")
_RE_CNPJ = re.compile(r"(?<![\d*])[\d*]{2}\.[\d*]{3}\.[\d*]{3}/[\d*]{4}-[\d*]{2}(?![\d*])")
# CNPJ público que fica: o da própria Amazon, no rodapé de toda página.
CNPJS_PUBLICOS = frozenset({"15.436.940/0001-03"})
_RE_CNPJ_BRUTO = re.compile(r"(?i)(\bCNPJ(?:<[^>]*>|[^\w<]){0,8})(\d{14})(?!\d)")
# Número proibido curto (número da casa): só como número solto, nunca dentro de preço, ASIN ou outro número.
_RE_NUMERO_SOLTO = re.compile(r"\d{1,6}")
_ANTES_DO_NUMERO = r"(?<![0-9A-Za-zÀ-ÿ])(?<![0-9][.,])"
_DEPOIS_DO_NUMERO = r"(?![0-9A-Za-zÀ-ÿ])(?![.,][0-9])"
_RE_SAUDACAO = re.compile(r"(?i)(Ol[aá],(?:\s|<[^>]*>)*)(?!fa[cç]a|fa&|entre|sign)(?![\s<])[^<]{1,60}")
_RE_ENTREGA = re.compile(r"(?i)\b((?:Enviar|Entrega|Entregar|Enviando) para\s+)[^<,\d\-]{1,60}?(\s*(?:[<,\d\-]|\Z))")
_RE_PEDIDO = re.compile(r"(?<!\d)\d{3}-\d{7}-\d{7}(?!\d)")
_RE_ASIN = re.compile(r"/dp/([A-Z0-9]{10})")

# Ids de pedido, item e sessão dentro de atributos (id, name, for, class, aria-*, data-*).
_RE_ATRIBUTO = re.compile(r"""(\s(?:id|name|for|class|aria-[\w-]+|data-[\w-]+)\s*=\s*)("[^"]*"|'[^']*')""")
_RE_UUID = re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])")
_UUID_FICTICIO = "00000000-0000-0000-0000-"
_RE_RASTREIO = re.compile(r"(?<![\w-])p[fd]_rd_[\w-]*")
_RE_PEDIDO_ATRIBUTO = re.compile(r"(?<!\d)\d{3}-\d{7}(?:-\d{1,7})?(?!\d)")
_RE_TOKEN = re.compile(r"(?<![A-Za-z0-9+/=_])[A-Za-z0-9+/_]{16,}={0,2}(?![A-Za-z0-9+/=_])")
_RE_TOKEN_FICTICIO = re.compile(r"tok\d{4}")

# "Salvo para depois" do carrinho: mostra o que o dono da conta anda comprando.
SELETORES_SALVOS = ('[data-name="Saved Cart"]', "#sc-saved-cart", '[data-name="Saved Items"]')
SELETORES_ATIVOS = ('[data-name="Active Items"]', "#sc-active-cart", "#activeCartViewForm")
SELETOR_TITULO_SALVO = (
    ".sc-product-title, .a-truncate-full, .a-truncate-cut, .sc-removed-msg-title, h3, [class*=product-title]"
)


def ler_proibidos(caminho: Path) -> list[str]:
    """Um texto real por linha (linhas vazias e com # são ignoradas); sem o arquivo, lista vazia."""
    if not caminho.exists():
        return []
    linhas = (linha.strip() for linha in caminho.read_text(encoding="utf-8").splitlines())
    return [linha for linha in linhas if linha and not linha.startswith("#")]


def _href_seguro(href: str) -> str:
    """Só o que os parsers usam: o vendedor (seller=<ID>) ou o produto (/dp/<ASIN>); o resto vira "#"."""
    vendedor = parse_qs(urlsplit(href).query).get("seller")
    if vendedor:
        return f"/gp/aag/main?seller={vendedor[0]}"
    achado = _RE_ASIN.search(href)
    return f"/dp/{achado.group(1)}" if achado else "#"


def _filtrar_atributos(no: LexborNode) -> None:
    for nome in list(no.attributes):
        if nome not in ATRIBUTOS_MANTIDOS:
            del no.attrs[nome]
    botao = no.tag == "input" and (no.attributes.get("type") or "").lower() in ("submit", "button")
    if "value" in no.attributes and not botao:
        # só o texto de botões fica; os demais campos levam tokens, ids de cartão/endereço e dados preenchidos
        del no.attrs["value"]
    href = no.attributes.get("href")
    if href is not None:
        no.attrs["href"] = _href_seguro(href)


def _sem_aninhados(nos: list[LexborNode]) -> list[LexborNode]:
    """Tira repetidos e os que estão dentro de outro bloco escolhido (senão o trecho sai duas vezes)."""
    ids = {no.mem_id for no in nos}
    vistos: set[int] = set()
    escolhidos = []
    for no in nos:
        if no.mem_id in vistos:
            continue
        vistos.add(no.mem_id)
        pai = no.parent
        while pai is not None and pai.mem_id not in ids:
            pai = pai.parent
        if pai is None:
            escolhidos.append(no)
    return escolhidos


def limpar(html: str, blocos: Sequence[str] | None = None) -> str:
    arvore = LexborHTMLParser(re.sub(r"<!--.*?-->", "", _normalizar(html), flags=re.DOTALL))
    titulo = arvore.css_first("title")
    texto_titulo = titulo.text(strip=True) if titulo is not None else ""
    arvore.strip_tags(TAGS_REMOVIDAS)
    asins_salvos, titulos_salvos = _trocar_salvos(arvore)
    _substituir_secao_salvos(arvore)
    if blocos is None:
        raizes = [arvore.body] if arvore.body is not None else []
    else:
        raizes = _sem_aninhados([no for seletor in blocos for no in arvore.css(seletor)])
        if not raizes:
            raise ValueError(f"nenhum dos blocos {list(blocos)} foi encontrado na página")
    partes = []
    for raiz in raizes:
        for no in raiz.traverse(include_text=False):
            _filtrar_atributos(no)
        partes.append((raiz.html or "").removeprefix("<body>").removesuffix("</body>"))
    corpo = re.sub(r"\s+", " ", "\n".join(partes)).replace("> <", ">\n<")
    visivel = _sem_espacos(_desescapar(corpo))
    if any(asin in visivel.upper() for asin in asins_salvos) or any(_sem_espacos(t) in visivel for t in titulos_salvos):
        raise ValueError("item do 'Salvo para depois' continua na página depois da troca")
    return (
        '<!DOCTYPE html>\n<html><head><meta charset="utf-8">'
        f"<title>{escape(texto_titulo)}</title></head>\n"
        "<!-- Página real limpa e anonimizada (src/tcg_sniper/coletor_amazon/anonimizar.py). -->\n"
        f"<body>\n{corpo}\n</body></html>\n"
    )


def _desescapar(texto: str) -> str:
    """Desfaz entidades HTML até estabilizar (a Amazon codifica duas vezes: `&amp;eacute;`)."""
    for _ in range(5):
        novo = unescape(texto)
        if novo == texto:
            break
        texto = novo
    return texto


def _bloco_salvos_ficticio(raiz: LexborNode, quantos: int, inicio: int) -> LexborNode:
    """O mesmo elemento (tag e atributos) com `quantos` itens fictícios no lugar de todo o conteúdo."""
    atributos = "".join(f' {nome}="{escape(valor or "", quote=True)}"' for nome, valor in raiz.attributes.items())
    itens = "".join(
        f'<div class="a-row sc-list-item" data-asin="B0SALVO{n:03d}" data-itemtype="saved" role="listitem">'
        f'<span class="a-truncate-full sc-product-title">Produto salvo {n}</span>'
        '<span class="sc-product-price">R$ 10,00</span></div>'
        for n in range(inicio, inicio + quantos)
    )
    html = f'<{raiz.tag}{atributos}><h2>Salvo para depois</h2><div class="a-section sc-list-body">{itens}</div></{raiz.tag}>'
    novo = LexborHTMLParser(f"<html><body>{html}</body></html>").body
    assert novo is not None and novo.child is not None
    return novo.child


def _substituir_secao_salvos(arvore: LexborHTMLParser) -> None:
    """Todo o conteúdo do "Salvo para depois" (títulos, preços, selos, vendedor, aria-labels) vira um bloco
    sintético com o mesmo número de itens; nada real daquela seção sobra."""
    raizes = _sem_aninhados([no for seletor in SELETORES_SALVOS for no in arvore.css(seletor)])
    ativos = {_asin_do_no(no) for seletor in SELETORES_ATIVOS for no in arvore.css(f"{seletor} [data-asin]")}
    inicio = 1
    for raiz in raizes:
        asins = {a for no in raiz.css("[data-asin]") if (a := _asin_do_no(no)) and a not in ativos}
        quantos = len(asins)
        raiz.replace_with(_bloco_salvos_ficticio(raiz, quantos, inicio))
        inicio += quantos


def _sem_espacos(texto: str) -> str:
    return " ".join(texto.split()).lower()


def _asin_do_no(no: LexborNode) -> str:
    return (no.attributes.get("data-asin") or "").strip()


def _sem_reticencias(texto: str) -> str:
    return re.sub(r"(?:\.\.\.|…)$", "", " ".join(texto.split())).strip()


def _itens_salvos_arvore(arvore: LexborHTMLParser) -> list[tuple[str, list[str]]]:
    """(ASIN, títulos) de cada item do "Salvo para depois", na ordem da página, sem os do carrinho ativo."""
    raizes = _sem_aninhados([no for seletor in SELETORES_SALVOS for no in arvore.css(seletor)])
    ativos = {_asin_do_no(no) for seletor in SELETORES_ATIVOS for no in arvore.css(f"{seletor} [data-asin]")}
    itens: dict[str, list[str]] = {}
    for raiz in raizes:
        for item in raiz.css("[data-asin]"):
            asin = _asin_do_no(item)
            if not asin:
                continue
            titulos = itens.setdefault(asin, [])
            for no in item.css(SELETOR_TITULO_SALVO):
                proprio = _sem_reticencias(_desescapar(no.text(deep=False)))
                if len(proprio) >= 4 and proprio not in titulos:
                    titulos.append(proprio)
    return [(asin, titulos) for asin, titulos in itens.items() if asin not in ativos]


def itens_salvos(html: str) -> tuple[set[str], set[str]]:
    """ASINs e títulos do "Salvo para depois" de uma página de carrinho (o teste de privacidade compara)."""
    itens = _itens_salvos_arvore(LexborHTMLParser(_normalizar(html)))
    return {asin for asin, _ in itens}, {titulo for _, titulos in itens for titulo in titulos}


def _achar_titulo(trecho: str, em_ordem: list[str]) -> str:
    alvo = _sem_espacos(trecho)
    return next(t for t in em_ordem if _sem_espacos(t) == alvo)


def _trocar_salvos(arvore: LexborHTMLParser) -> tuple[set[str], set[str]]:
    """Troca título e ASIN de cada item salvo por fictícios ("Produto salvo N", B0SALVO00N) na página
    inteira (texto, aria-label, data-asin, href), mantendo quantos itens e a estrutura. Devolve os reais."""
    itens = _itens_salvos_arvore(arvore)
    if not itens or arvore.root is None:
        return set(), set()
    asins = {asin: f"B0SALVO{i:03d}" for i, (asin, _) in enumerate(itens, start=1)}
    titulos = {t: f"Produto salvo {i}" for i, (_, ts) in enumerate(itens, start=1) for t in ts}
    em_ordem = sorted(titulos, key=len, reverse=True)
    re_asin = re.compile(r"(?<![A-Z0-9])(" + "|".join(map(re.escape, asins)) + r")(?![A-Z0-9])")
    re_titulo = (
        re.compile("|".join(r"\s+".join(map(re.escape, t.split())) for t in em_ordem), re.IGNORECASE)
        if em_ordem
        else None
    )

    def trocar(texto: str) -> str:
        if re_titulo is not None:
            texto = re_titulo.sub(lambda m: titulos[_achar_titulo(m.group(), em_ordem)], texto)
        return re_asin.sub(lambda m: asins[m.group(1)], texto)

    textos = []
    for no in arvore.root.traverse(include_text=True):
        if no.tag == "-text":
            textos.append(no)
            continue
        for nome, valor in list(no.attributes.items()):
            if valor and (novo := trocar(_desescapar(valor))) != _desescapar(valor):
                no.attrs[nome] = novo
    for no in textos:
        original = _desescapar(no.text_content or "")
        novo = trocar(original)
        limpo = _sem_reticencias(original).lower()
        if novo == original and len(limpo) >= 10:  # título cortado num ponto que não foi lido
            novo = next((titulos[t] for t in em_ordem if t.lower().startswith(limpo)), original)
        if novo != original:
            no.replace_with(novo)

    return set(asins), set(titulos)


def _normalizar(html: str) -> str:
    """Hífens e traços Unicode viram "-" e espaços rígidos viram espaço comum, para os padrões casarem."""
    html = re.sub("[\u2010-\u2015\u2212]", "-", html)
    html = re.sub(r"(?i)&(?:ndash|mdash|hyphen|minus|#8208|#8209|#8210|#8211|#8212|#8213|#8722);", "-", html)
    return re.sub(r"(?i)&nbsp;|&#160;|&#xa0;|[\xa0\u2007\u202f]", " ", html)


def _padrao_texto(valor: str) -> str:
    """Casa o texto mesmo com espaços repetidos ou tags no meio das palavras (nome em <b>/<span> separados)."""
    return r"(?:\s|<[^>]*>)+".join(re.escape(palavra) for palavra in valor.split())


def _lista(proibidos: Sequence[str]) -> list[str]:
    return sorted({" ".join(p.split()) for p in proibidos if p.strip()}, key=len, reverse=True)


def _padrao_proibido(valor: str) -> str:
    """Valor que começa/termina em dígito leva junto os dígitos ligados a ele (+55, DDD, final do número):
    trocar só o meio deixaria parte do telefone na página. Número curto (até 6 dígitos, o número da casa)
    só casa solto: "742" não mexe em "R$ 1.742,90", "B0742XYZ12" nem "17420"."""
    if _RE_NUMERO_SOLTO.fullmatch(valor):
        return _ANTES_DO_NUMERO + re.escape(valor) + _DEPOIS_DO_NUMERO
    padrao = _padrao_texto(valor)
    if re.match(r"[\d(+]", valor):
        padrao = r"(?:[+(]*\d(?:[\d()]|[ -](?=[\d(]))*[ -]?)?" + padrao  # sem quantificador aninhado
    if re.search(r"\d\)?$", valor):
        padrao += r"(?:[ -]?\d)*"
    return padrao


def _trocar_identificadores(texto: str) -> str:
    """Ids de pedido, item e sessão nos atributos viram fictícios estáveis (o mesmo valor vira o mesmo
    fictício na página, então aria-labelledby continua achando o alvo). O prefixo legível fica:
    submit.delete-saved.<uuid> -> submit.delete-saved.00000000-0000-0000-0000-000000000001."""
    uuids: dict[str, str] = {}
    tokens: dict[str, str] = {}

    def uuid(m: re.Match[str]) -> str:
        valor = m.group().lower()
        if valor.startswith(_UUID_FICTICIO):
            return valor
        return uuids.setdefault(valor, f"{_UUID_FICTICIO}{len(uuids) + 1:012d}")

    def token(valor: str) -> str:
        return tokens.setdefault(valor, f"tok{len(tokens) + 1:04d}")

    def base64(m: re.Match[str]) -> str:
        valor = m.group()
        if _RE_TOKEN_FICTICIO.fullmatch(valor) or not re.search(r"[\d+/=]", valor):
            return valor
        return token(valor)

    def atributo(m: re.Match[str]) -> str:
        aspas, conteudo = m.group(2)[0], m.group(2)[1:-1]
        if "miq://" in conteudo:
            conteudo = token(conteudo)
        conteudo = _RE_RASTREIO.sub(lambda r: token(r.group()), conteudo)
        conteudo = _RE_UUID.sub(uuid, conteudo)
        conteudo = _RE_PEDIDO_ATRIBUTO.sub(lambda r: token(r.group()), conteudo)
        conteudo = _RE_TOKEN.sub(base64, conteudo)
        return f"{m.group(1)}{aspas}{conteudo}{aspas}"

    return _RE_ATRIBUTO.sub(atributo, texto)


def anonimizar(html: str, proibidos: Sequence[str] = ()) -> str:
    texto = _trocar_identificadores(_normalizar(html))
    for valor in _lista(proibidos):
        ficticio = FICTICIOS["texto"] if re.search(r"[^\W\d_]", valor) else FICTICIOS["numero"]
        texto = re.sub(_padrao_proibido(valor), ficticio, texto, flags=re.IGNORECASE)
    texto = _RE_SAUDACAO.sub(lambda m: f"{m.group(1)}{FICTICIOS['texto']}", texto)
    texto = _RE_ENTREGA.sub(lambda m: f"{m.group(1)}{FICTICIOS['texto']}{m.group(2)}", texto)
    texto = _RE_CPF.sub(FICTICIOS["cpf"], texto)
    texto = _RE_CPF_BRUTO.sub(lambda m: f"{m.group(1)}{FICTICIOS['cpf_bruto']}", texto)
    texto = _RE_CNPJ.sub(lambda m: m.group() if m.group() in CNPJS_PUBLICOS else FICTICIOS["cnpj"], texto)
    texto = _RE_CNPJ_BRUTO.sub(lambda m: f"{m.group(1)}{FICTICIOS['cnpj_bruto']}", texto)
    texto = _RE_PEDIDO.sub(FICTICIOS["pedido"], texto)  # antes do CEP: o número do pedido tem traços
    texto = _RE_CEP.sub(FICTICIOS["cep"], texto)
    texto = _RE_CEP_BRUTO.sub(lambda m: f"{m.group(1)}{FICTICIOS['cep_bruto']}", texto)
    texto = _RE_EMAIL.sub(FICTICIOS["email"], texto)
    texto = _RE_TELEFONE.sub(FICTICIOS["telefone"], texto)
    texto = _RE_FIXO.sub(FICTICIOS["telefone"], texto)
    texto = _RE_FIXO_SEM_PARENTESES.sub(FICTICIOS["telefone"], texto)
    texto = _RE_TELEFONE_BRUTO.sub(lambda m: f"{m.group(1)}{FICTICIOS['telefone_bruto']}", texto)
    texto = _RE_NUMERO_DE_TELEFONE.sub(lambda m: f"{m.group(1)}{FICTICIOS['telefone']}", texto)
    texto = _RE_PAGANDO.sub(FICTICIOS["pagando"], texto)
    for regex in _RES_CARTAO:
        texto = regex.sub(lambda m: f"{m.group(1)}{m.group(2)}{FICTICIOS['cartao']}", texto)
    return texto


def achados(html: str, proibidos: Sequence[str] = ()) -> list[str]:
    """O que ainda parece dado pessoal: tipo e posição (nunca o valor, que iria parar no log do teste)."""
    html = _normalizar(html)
    problemas = []
    baixo = " ".join(html.lower().split())
    corpo = LexborHTMLParser(html).body
    visivel = " ".join((corpo.text(separator=" ") if corpo is not None else "").lower().split())
    for valor in sorted(_lista(proibidos)):
        alvo = valor.lower()
        if _RE_NUMERO_SOLTO.fullmatch(valor):  # número da casa: só solto (o mesmo critério da troca)
            solto = re.compile(_padrao_proibido(valor))
            if (achado := solto.search(baixo) or solto.search(visivel)) is not None:
                problemas.append(f"texto proibido (número) na posição {achado.start()}")
            continue
        if (posicao := baixo.find(alvo)) >= 0:
            problemas.append(f"texto proibido na posição {posicao}")
        elif (posicao := visivel.find(alvo)) >= 0:
            problemas.append(f"texto proibido no texto visível, posição {posicao}")
    genericos = (
        ("CPF", _RE_CPF, FICTICIOS["cpf"], 0),
        ("CPF", _RE_CPF_BRUTO, FICTICIOS["cpf_bruto"], 2),
        ("CNPJ", _RE_CNPJ, FICTICIOS["cnpj"], 0),
        ("CNPJ", _RE_CNPJ_BRUTO, FICTICIOS["cnpj_bruto"], 2),
        ("CEP", _RE_CEP, FICTICIOS["cep"], 0),
        ("CEP", _RE_CEP_BRUTO, FICTICIOS["cep_bruto"], 2),
        ("e-mail", _RE_EMAIL, FICTICIOS["email"], 0),
        ("telefone", _RE_TELEFONE, FICTICIOS["telefone"], 0),
        ("telefone", _RE_FIXO, FICTICIOS["telefone"], 0),
        ("telefone", _RE_FIXO_SEM_PARENTESES, FICTICIOS["telefone"], 0),
        ("telefone", _RE_TELEFONE_BRUTO, FICTICIOS["telefone_bruto"], 2),
        ("pedido", _RE_PEDIDO, FICTICIOS["pedido"], 0),
    )
    for tipo, regex, ficticio, grupo in genericos:
        problemas += [
            f"{tipo} na posição {m.start()}"
            for m in regex.finditer(html)
            if m.group(grupo) != ficticio and m.group(grupo) not in CNPJS_PUBLICOS
        ]
    for regex in _RES_CARTAO:
        problemas += [
            f"cartão na posição {m.start()}" for m in regex.finditer(html) if m.group(3) != FICTICIOS["cartao"]
        ]
    problemas += [
        f"telefone na posição {m.start()}"
        for m in _RE_NUMERO_DE_TELEFONE.finditer(html)
        if m.group(2).strip() != FICTICIOS["telefone"]
    ]
    problemas += [
        f"cartão na posição {m.start()}"
        for m in _RE_PAGANDO.finditer(html)
        if m.group().strip() != FICTICIOS["pagando"]
    ]
    problemas += [f"identificador na posição {posicao}" for posicao in _identificadores(html)]
    return problemas


def _identificadores(html: str) -> list[int]:
    """Posições de ids de pedido/item/sessão que sobraram em atributos (miq:// e pf_rd_ em qualquer lugar)."""
    posicoes = [m.start() for m in re.finditer(r"miq://|(?<![\w-])p[fd]_rd_", html)]
    for m in _RE_ATRIBUTO.finditer(html):
        conteudo = m.group(2)[1:-1]
        restos = [u for u in _RE_UUID.findall(conteudo) if not u.lower().startswith(_UUID_FICTICIO)]
        restos += _RE_PEDIDO_ATRIBUTO.findall(conteudo)
        restos += [
            t for t in _RE_TOKEN.findall(conteudo) if re.search(r"[\d+/=]", t) and not _RE_TOKEN_FICTICIO.fullmatch(t)
        ]
        if restos:
            posicoes.append(m.start())
    return sorted(set(posicoes))
