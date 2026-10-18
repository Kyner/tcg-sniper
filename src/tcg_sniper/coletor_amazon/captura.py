"""Captura das páginas reais da Amazon para as fixtures do monitor e da conferência de checkout.

Roda com o coletor parado (mesmo perfil do Chromium, logado antes pelo noVNC). Salva as páginas
inteiras em <DIR_DADOS>/capturas/<data>/ (fora do git); elas só viram fixture depois de
scripts/anonimizar_fixture.py. Com `checkout`, adiciona a oferta em destaque do primeiro ASIN, vai
até o resumo do pedido (sem confirmar) e tira o item, sempre pelos cliques de `cliques.py`; com
qualquer item no carrinho ativo, não clica em nada."""

from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from tcg_sniper.coletor_amazon.cliques import (
    ADICIONAR,
    ENTREGAR,
    ESCOPO_OFERTA_DESTAQUE,
    FECHAR_PEDIDO,
    CliqueProibido,
    SeletorAusente,
    clicar_permitido,
    localizar,
    remover_do_carrinho,
)
from tcg_sniper.coletor_amazon.parsers import SELETOR_PAINEL_OFERTAS, URL_CARRINHO, url_ofertas, url_painel_ofertas
from tcg_sniper.coletor_amazon.parsers_checkout import parse_carrinho
from tcg_sniper.navegador.base import Navegador, NavegadorInterativo
from tcg_sniper.navegador.modelos import ErroRede, Pagina
from tcg_sniper.parsing import ErroParser

# Sem sessão, o resumo do pedido manda para a página de login.
# "Seus pedidos" sem sessão manda para a tela de login (o endereço antigo do checkout dava 404).
URL_TESTE_LOGIN = "https://www.amazon.com.br/gp/css/order-history"
ESPERA_PAINEL_MS = 15_000


@dataclass
class Captura:
    destino: Path
    salvas: list[Path] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    def salvar(self, nome: str, pagina: Pagina) -> None:
        caminho = self.destino / f"{nome}.html"
        caminho.write_text(pagina.html, encoding="utf-8")
        self.salvas.append(caminho)


def carrinho_vazio(pagina: Pagina) -> bool:
    """Só com o carrinho lido por `parse_carrinho` (o bloco do carrinho ativo na página), o contador
    igual a zero e nenhum item ativo. Login, CAPTCHA ou erro no lugar do carrinho (ErroParser): False."""
    try:
        estado = parse_carrinho(pagina.html)
    except ErroParser:
        return False
    return estado.contador == 0 and not estado.asins_ativos


def capturar(
    nav: NavegadorInterativo,
    asins: Sequence[str],
    destino: Path,
    *,
    checkout: bool,
    pausar: Callable[[], None],
    cap: Captura | None = None,
) -> Captura:
    """`cap` (opcional) é preenchida aos poucos: quem chama vê o que foi salvo e os avisos mesmo
    se uma exceção inesperada escapar."""
    destino.mkdir(parents=True, exist_ok=True)
    cap = cap if cap is not None else Captura(destino)
    carrinho = nav.abrir(URL_CARRINHO)
    cap.salvar("carrinho_inicial", carrinho)
    for asin in asins:
        pausar()
        cap.salvar(f"ofertas_{asin}", nav.abrir(url_ofertas(asin)))
        pausar()
        cap.salvar(f"painel_{asin}", nav.abrir_e_esperar(url_painel_ofertas(asin), SELETOR_PAINEL_OFERTAS, ESPERA_PAINEL_MS))
    if not checkout:
        return cap
    if not carrinho_vazio(carrinho):
        cap.avisos.append("carrinho com itens (ou contador ilegível): checkout não capturado, nada foi clicado")
        return cap
    asin = asins[0]
    pausar()
    # Confere de novo logo antes de adicionar: o usuário pode ter posto algo no carrinho nesse meio tempo.
    if not carrinho_vazio(nav.abrir(URL_CARRINHO)):
        cap.avisos.append(
            f"carrinho com itens (ou contador ilegível) antes de adicionar {asin}: checkout não capturado, nada foi clicado"
        )
        return cap
    adicionou = False
    try:
        pausar()
        painel = nav.abrir_e_esperar(url_painel_ofertas(asin), SELETOR_PAINEL_OFERTAS, ESPERA_PAINEL_MS)
        pausar()
        adicionou = True  # daqui em diante pode haver item nosso no carrinho, mesmo se o clique der erro
        cap.salvar("apos_adicionar", clicar_permitido(nav, ADICIONAR, painel, ESCOPO_OFERTA_DESTAQUE))
        pausar()
        carrinho = nav.abrir(URL_CARRINHO)
        cap.salvar("carrinho_um_item", carrinho)
        pausar()
        pagina = clicar_permitido(nav, FECHAR_PEDIDO, carrinho)
        cap.salvar("checkout_1", pagina)
        if localizar(ENTREGAR, pagina) is not None:
            pausar()
            cap.salvar("checkout_resumo", clicar_permitido(nav, ENTREGAR, pagina))
    except (SeletorAusente, CliqueProibido, ErroRede) as erro:
        cap.avisos.append(f"captura do checkout parou: {erro}")
        with suppress(Exception):  # salvar onde parou é só ajuda; a retirada do item vem a seguir
            cap.salvar("parou_aqui", nav.atual())
    except BaseException as erro:
        # Não engole: registra e deixa subir depois da retirada (o finally não levanta nada).
        cap.avisos.append(f"captura do checkout falhou: {erro!r}")
        raise
    finally:
        if adicionou:
            _retirar_item(nav, asin, cap, pausar)
    return cap


def _retirar_item(nav: NavegadorInterativo, asin: str, cap: Captura, pausar: Callable[[], None]) -> None:
    """Tira o item adicionado e confere recarregando o carrinho; nunca levanta. Qualquer dúvida vira aviso."""
    aviso = f"o item {asin} pode ter ficado no carrinho: confira pelo noVNC e exclua à mão"
    print("removendo o item adicionado...", flush=True)
    try:
        removido, _ = remover_do_carrinho(nav, asin, nav.abrir, pausar)
        conferido = nav.abrir(URL_CARRINHO)
        cap.salvar("carrinho_vazio", conferido)
        if not (removido and carrinho_vazio(conferido)):
            cap.avisos.append(aviso)
    except Exception as erro:  # noqa: BLE001 - a retirada não pode esconder o erro original nem sumir calada
        cap.avisos.append(f"{aviso} (erro na retirada: {erro!r})")
        with suppress(Exception):
            cap.salvar("carrinho_vazio", nav.atual())


def capturar_login(nav: Navegador, destino: Path) -> Path:
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / "login.html"
    caminho.write_text(nav.abrir(URL_TESTE_LOGIN).html, encoding="utf-8")
    return caminho
