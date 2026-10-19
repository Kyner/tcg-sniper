"""Busca alternativa: a IA sugere de 2 a 3 termos de busca na Amazon Brasil para um produto da Liga (uma
chamada barata, sem imagem, dentro do teto de gasto) e o filtro descarta os inválidos."""

import re
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.coletor_amazon.termo import termo_busca
from tcg_sniper.db.models import ProdutoLiga
from tcg_sniper.db.repositorio import agora_utc
from tcg_sniper.db.repositorio_termos import IDIOMAS, MAX_TERMOS, TERMO_MAX
from tcg_sniper.ia.cliente import perguntar
from tcg_sniper.ia.modelos import RespostaForaDoFormato, Transporte

FINALIDADE = "termos"
NOME_FORMATO = "termos_busca"
_LINK = re.compile(r"https?://|www\.|\.com\b|\.br\b", re.IGNORECASE)

INSTRUCOES = """Você ajuda a achar na Amazon Brasil (amazon.com.br) um produto selado de Magic: The Gathering vendido na LigaMagic.
A busca pelo nome da LigaMagic não achou nada parecido há uma semana. Sugira de 2 a 3 termos de busca curtos, do jeito que um vendedor da Amazon escreveria o título: em português ou em inglês, com a coleção e o tipo do produto (booster avulso, caixa de boosters, bundle, deck, kit, colecionador etc.).
Idioma: a edição em português é a preferida para o produto da LigaMagic, e a edição em inglês também serve enquanto o produto não tem anúncio em português confirmado (é o caso deste produto). Primeiro termos para achar a edição em português; pode incluir termos para a edição em inglês; nunca termos para a edição japonesa nem de outro idioma. Japonês e qualquer outro idioma são sempre outro produto.
Não repita o nome da LigaMagic nem o nome em inglês exatamente como foram dados. Sem links, sem aspas, até 80 caracteres cada. Informe o idioma em que cada termo está escrito: "pt" ou "en"."""

FORMATO = {
    "type": "object",
    "properties": {
        "termos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"termo": {"type": "string"}, "idioma": {"type": "string", "enum": list(IDIOMAS)}},
                "required": ["termo", "idioma"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["termos"],
    "additionalProperties": False,
}


def texto_pedido(produto: ProdutoLiga) -> str:
    return "\n".join(
        [
            "Produto da LigaMagic:",
            f"- nome: {produto.nome}",
            f"- nome em inglês: {produto.nome_en or '(não informado)'}",
            f"- edição: {produto.edicao or '(não informada)'}",
            f"- tipo: {produto.tipo or '(não informado)'}",
            f"- idioma: {produto.idioma or '(não informado)'}",
        ]
    )


def filtrar_termos(dados: dict, nome: str, nome_en: str | None) -> list[tuple[str, str]]:
    """Os termos válidos, na ordem da resposta, no máximo 3: sem vazio, até 80 caracteres, sem link, sem
    repetir o nome nem o nome em inglês (nem entre si; sem diferenciar maiúsculas e pontuação) e com idioma
    "pt" ou "en". Resposta sem a lista: RespostaForaDoFormato."""
    brutos = dados.get("termos")
    if not isinstance(brutos, list):
        raise RespostaForaDoFormato("resposta sem a lista de termos")
    vistos = {termo_busca(n).casefold() for n in (nome, nome_en) if n}
    saida: list[tuple[str, str]] = []
    for item in brutos:
        if not isinstance(item, dict):
            continue
        termo, idioma = item.get("termo"), item.get("idioma")
        if not isinstance(termo, str) or idioma not in IDIOMAS:
            continue
        termo = " ".join(termo.split())
        chave = termo_busca(termo).casefold()
        if not chave or len(termo) > TERMO_MAX or _LINK.search(termo) or chave in vistos:
            continue
        vistos.add(chave)
        saida.append((termo, idioma))
    return saida[:MAX_TERMOS]


def gerar_termos(
    sessoes: sessionmaker[Session],
    transporte: Transporte,
    produto: ProdutoLiga,
    *,
    zona: ZoneInfo,
    relogio: Callable[[], datetime] = agora_utc,
) -> list[tuple[str, str]]:
    """Uma chamada (registrada em `chamada_ia` com a finalidade "termos"). Lança SemOrcamento (sem chamar),
    ChaveInvalida, ConfiguracaoInvalida, RespostaForaDoFormato ou ErroIA, como `perguntar`."""
    resposta = perguntar(
        sessoes, transporte, finalidade=FINALIDADE, instrucoes=INSTRUCOES, texto=texto_pedido(produto), imagens=[],
        nome_formato=NOME_FORMATO, formato=FORMATO, zona=zona, relogio=relogio,
    )
    return filtrar_termos(resposta.dados, produto.nome, produto.nome_en)
