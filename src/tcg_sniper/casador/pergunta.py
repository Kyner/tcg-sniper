"""A pergunta "é o mesmo produto?" para a IA: texto, formato da resposta, assinatura dos dados e leitura."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session, sessionmaker

from tcg_sniper.db.models import IDIOMAS_ANUNCIO, AnuncioAmazon, ProdutoLiga
from tcg_sniper.db.repositorio import agora_utc
from tcg_sniper.formatacao import formatar_brl
from tcg_sniper.ia.cliente import perguntar
from tcg_sniper.ia.imagens import preparar
from tcg_sniper.ia.modelos import RespostaForaDoFormato, RespostaIA, Transporte

NOME_FORMATO = "veredito_casamento"
MOTIVO_MAX = 200

INSTRUCOES = """Você compara um produto selado de Magic: The Gathering vendido na LigaMagic com um anúncio da Amazon Brasil.
Responda se o anúncio é exatamente o mesmo item lacrado do produto da LigaMagic.
É o mesmo produto só se coincidirem: o jogo, a edição/coleção, o tipo (booster avulso, caixa de boosters, bundle, deck, kit, colecionador etc.), a versão do booster (draft, set, play, collector), a quantidade e o idioma pela regra abaixo.
É outro produto: carta avulsa, acessório (sleeve, deck box, playmat), outra edição, outro tipo, outra quantidade ou lote com vários itens.
Idioma: A edição em português é a preferida para o produto da LigaMagic. Anúncio em inglês também é o mesmo produto quando o produto da LigaMagic não tem anúncio em português confirmado (nas coleções antigas a LigaMagic junta português e inglês num produto só). Se já tem anúncio em português confirmado (ou não se sabe), julgue o anúncio em inglês pelo resto, como se o inglês valesse, e diga no motivo que é a edição em inglês: quem decide é o usuário. Japonês e qualquer outro idioma são sempre outro produto.
Em idioma_anuncio informe o idioma do produto vendido, pela embalagem e pelas cartas que aparecem nas imagens, não pelo título (lojas brasileiras escrevem o título em português para produto importado): "pt", "en", "ja", "outro" ou "indefinido" (as imagens não mostram a embalagem com clareza).
Use as imagens, quando houver, para conferir embalagem, edição e tipo. Preço muito abaixo do esperado é pista de item diferente, não prova.
A confiança é um inteiro de 0 a 100 sobre a sua resposta. O motivo é uma frase curta em português (até 200 caracteres) com o que decidiu."""

FORMATO = {
    "type": "object",
    "properties": {
        "mesmo_produto": {"type": "boolean"},
        "confianca": {"type": "integer"},
        "motivo": {"type": "string"},
        "idioma_anuncio": {"type": "string", "enum": list(IDIOMAS_ANUNCIO)},
    },
    "required": ["mesmo_produto", "confianca", "motivo", "idioma_anuncio"],
    "additionalProperties": False,
}

PORTUGUES_CONFIRMADO = {True: "sim", False: "não", None: "não se sabe (há anúncio confirmado de idioma não registrado)"}


@dataclass(frozen=True)
class Veredito:
    mesmo_produto: bool
    confianca: int
    motivo: str
    idioma_anuncio: str | None = None  # None: resposta sem o campo (o formato estrito sempre o traz)


def _preco(valor: Decimal | None) -> str:
    return formatar_brl(valor) if valor is not None else "sem preço"


def texto_pergunta(
    anuncio: AnuncioAmazon,
    produto: ProdutoLiga,
    preco_liga: Decimal | None,
    preco_amazon: Decimal | None,
    portugues_confirmado: bool | None = False,
) -> str:
    linhas = [
        "Produto da LigaMagic:",
        f"- nome: {produto.nome}",
        f"- nome em inglês: {produto.nome_en or '(não informado)'}",
        f"- edição: {produto.edicao or '(não informada)'}",
        f"- tipo: {produto.tipo or '(não informado)'}",
        f"- idioma: {produto.idioma or '(não informado)'}",
        f"- menor preço na LigaMagic: {_preco(preco_liga)}",
        f"- já tem anúncio em português confirmado: {PORTUGUES_CONFIRMADO[portugues_confirmado]}",
        "",
        "Anúncio da Amazon:",
        f"- título: {anuncio.titulo}",
        f"- opção da variação: {anuncio.variacao or '(nenhuma)'}",
        f"- preço: {_preco(preco_amazon)}",
        "",
        "Imagens, quando houver: primeiro a da LigaMagic, depois a da Amazon.",
    ]
    return "\n".join(linhas)


def assinatura(anuncio: AnuncioAmazon, produto: ProdutoLiga) -> str:
    """Hash dos dados que decidem a resposta: mudou, o par é reavaliado. O "português confirmado" fica de
    fora de propósito (confirmar um anúncio não reavalia os outros pares do produto); o automático confere
    o estado atual na hora de aplicar."""
    dados = [anuncio.titulo, anuncio.variacao, anuncio.imagem_url, produto.nome, produto.nome_en,
             produto.edicao, produto.tipo, produto.idioma, produto.imagem_url]
    return hashlib.sha256(json.dumps(dados, ensure_ascii=False).encode()).hexdigest()


def ler_veredito(dados: dict) -> Veredito:
    mesmo, confianca, motivo = dados.get("mesmo_produto"), dados.get("confianca"), dados.get("motivo")
    if not isinstance(mesmo, bool):
        raise RespostaForaDoFormato("resposta sem mesmo_produto booleano")
    if not isinstance(confianca, int) or isinstance(confianca, bool) or not 0 <= confianca <= 100:
        raise RespostaForaDoFormato("confiança fora de 0 a 100")
    if not isinstance(motivo, str) or not motivo.strip():
        raise RespostaForaDoFormato("resposta sem motivo")
    idioma = dados.get("idioma_anuncio")
    if idioma is not None and idioma not in IDIOMAS_ANUNCIO:
        raise RespostaForaDoFormato("idioma do anúncio desconhecido")
    return Veredito(mesmo, confianca, motivo.strip()[:MOTIVO_MAX], idioma)


def avaliar_par(
    sessoes: sessionmaker[Session],
    transporte: Transporte,
    cliente_http: httpx.Client,
    anuncio: AnuncioAmazon,
    produto: ProdutoLiga,
    preco_liga: Decimal | None,
    preco_amazon: Decimal | None,
    *,
    finalidade: str,
    portugues_confirmado: bool | None = False,
    zona: ZoneInfo,
    modelo: str | None = None,
    preco_entrada: Decimal | None = None,
    preco_saida: Decimal | None = None,
    relogio: Callable[[], datetime] = agora_utc,
) -> tuple[Veredito, RespostaIA, bool]:
    """Prepara as imagens, pergunta e lê o veredito. Devolve também se faltou alguma imagem."""
    imagens = [preparar(cliente_http, produto.imagem_url), preparar(cliente_http, anuncio.imagem_url)]
    prontas = [i for i in imagens if i is not None]
    resposta = perguntar(
        sessoes, transporte, finalidade=finalidade, instrucoes=INSTRUCOES,
        texto=texto_pergunta(anuncio, produto, preco_liga, preco_amazon, portugues_confirmado), imagens=prontas,
        nome_formato=NOME_FORMATO, formato=FORMATO, zona=zona, modelo=modelo, preco_entrada=preco_entrada,
        preco_saida=preco_saida, relogio=relogio,
    )
    return ler_veredito(resposta.dados), resposta, len(prontas) < 2
