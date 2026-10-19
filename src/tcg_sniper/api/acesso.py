"""Login pelo WhatsApp: pedir código (com limites), entrar (código → sessão, com limite de tentativas) e o resumo
do aparelho.
Número só aparece em log mascarado; código e token nunca (no banco, só o hash)."""

import logging
import secrets
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy.orm import Session

from tcg_sniper.api.dependencias import VALIDADE_SESSAO
from tcg_sniper.api.segredos import gerar_codigo, gerar_token, hash_segredo
from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import Dados, TipoAviso
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import Usuario
from tcg_sniper.formatacao import mascarar_numero

log = logging.getLogger(__name__)

VALIDADE_CODIGO = timedelta(minutes=5)
MAX_TENTATIVAS = 5
LIMITE_POR_NUMERO = 3
JANELA_NUMERO = timedelta(minutes=15)
LIMITE_TOTAL = 20
JANELA_TOTAL = timedelta(hours=1)
LIMITE_ENTRADAS = 10  # tentativas de entrar por número (com ou sem cadastro) a cada 15 min
JANELA_ENTRADAS = timedelta(minutes=15)
CHAVE_TOTAL = "total"  # chave do `SEGURANCA_LIMITE` do limite total por hora
LINHAS_CODIGO = ("Vale por 5 minutos.", "Não passe este código para ninguém.")
NAVEGADORES = (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari"))
SISTEMAS = (
    ("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"), ("Windows", "Windows"),
    ("Mac OS X", "macOS"), ("Linux", "Linux"),
)


class ResultadoPedido(StrEnum):
    ACEITO = "aceito"
    LIMITE_NUMERO = "limite_numero"
    LIMITE_TOTAL = "limite_total"


def resumir_aparelho(user_agent: str | None) -> str:
    """"Chrome · Windows": o bastante para a pessoa reconhecer a sessão, sem guardar o User-Agent inteiro."""
    texto = user_agent or ""
    navegador = next((nome for marca, nome in NAVEGADORES if marca in texto), "navegador desconhecido")
    sistema = next((nome for marca, nome in SISTEMAS if marca in texto), "sistema desconhecido")
    return f"{navegador} · {sistema}"


def emitir_codigo(s: Session, usuario_id: int, agora: datetime, segredo: str) -> str:
    """Novo código para o usuário (o anterior deixa de valer: só o último vale). Usado no login e no acesso de
    emergência (`tcg-sniper codigo-acesso`). No banco, só o HMAC com `segredo` (SEGREDO_API)."""
    codigo = gerar_codigo()
    repo_acesso.criar_codigo(s, usuario_id, hash_segredo(segredo, codigo), agora, VALIDADE_CODIGO)
    return codigo


def _chave_numero(numero_hash: str) -> str:
    """Chave do `SEGURANCA_LIMITE` de um número: parte do hash, nunca o número (pedidos e códigos errados agrupam)."""
    return f"numero:{numero_hash[:12]}"


def _recusar(s: Session, numero: str, numero_hash: str, resultado: ResultadoPedido, agora: datetime) -> ResultadoPedido:
    repo_acesso.registrar_pedido(s, numero_hash, resultado.value, agora)
    if resultado is ResultadoPedido.LIMITE_TOTAL:
        chave = CHAVE_TOTAL
        linhas = (f"Limite: {LIMITE_TOTAL} pedidos por hora no total", "Vários números")
    else:
        chave = _chave_numero(numero_hash)
        linhas = (f"Limite: {LIMITE_POR_NUMERO} códigos por número em 15 min", f"Número com final {numero[-2:]}")
    log.warning("pedido de código recusado (%s) para %s", resultado.value, mascarar_numero(numero))
    avisos.avisar(s, TipoAviso.SEGURANCA_LIMITE, chave, Dados(linhas=linhas), agora)
    return resultado


def pedir_codigo(s: Session, numero: str, agora: datetime, segredo: str) -> ResultadoPedido:
    """`numero` já normalizado. Dentro dos limites, registra o pedido e, se for de um usuário ativo, emite o código e
    enfileira a mensagem individual. Fora dos limites, registra, avisa o grupo admin e devolve o limite atingido.
    O chamador responde igual para número com ou sem cadastro."""
    repo_acesso.limpar_antigos(s, agora)
    numero_hash = hash_segredo(segredo, numero)
    # Sempre nesta ordem (total, depois número): sem impasse entre duas requisições.
    repo_acesso.travar_limite(s, repo_acesso.TRAVA_PEDIDOS_TOTAL)
    repo_acesso.travar_limite(s, repo_acesso.TRAVA_PEDIDOS_NUMERO, numero_hash)
    if repo_acesso.contar_pedidos(s, agora - JANELA_TOTAL) >= LIMITE_TOTAL:
        return _recusar(s, numero, numero_hash, ResultadoPedido.LIMITE_TOTAL, agora)
    if repo_acesso.contar_pedidos(s, agora - JANELA_NUMERO, numero_hash) >= LIMITE_POR_NUMERO:
        return _recusar(s, numero, numero_hash, ResultadoPedido.LIMITE_NUMERO, agora)
    repo_acesso.registrar_pedido(s, numero_hash, ResultadoPedido.ACEITO.value, agora)
    avisos.resolver(s, TipoAviso.SEGURANCA_LIMITE, CHAVE_TOTAL, agora)  # aceito: o limite total já passou
    usuario = repo_acesso.usuario_por_numero(s, numero)
    if usuario is None or not usuario.ativo:
        log.info("pedido de código para %s: sem usuário ativo, nada enviado", mascarar_numero(numero))
        return ResultadoPedido.ACEITO
    codigo = emitir_codigo(s, usuario.id, agora, segredo)
    dados = Dados(destaque=codigo, linhas=LINHAS_CODIGO)
    na_fila = avisos.avisar_individual(s, TipoAviso.CODIGO_ACESSO, usuario.numero, dados, agora, VALIDADE_CODIGO)
    situacao = "na fila do WhatsApp" if na_fila else "não enfileirado (aviso desligado ou erro)"
    log.info("código de acesso para %s: %s", mascarar_numero(numero), situacao)
    return ResultadoPedido.ACEITO


def registrar_entrada(s: Session, numero: str, agora: datetime, segredo: str) -> bool:
    """Conta uma tentativa de entrar (`numero` já normalizado), tenha ou não cadastro. False (nada gravado) se o
    número já fez `LIMITE_ENTRADAS` tentativas na janela: o chamador responde 429 sem conferir o código.
    Também apaga pedidos e códigos antigos (como `pedir_codigo`)."""
    repo_acesso.limpar_antigos(s, agora)
    numero_hash = hash_segredo(segredo, numero)
    repo_acesso.travar_limite(s, repo_acesso.TRAVA_ENTRADAS_NUMERO, numero_hash)
    if repo_acesso.contar_pedidos(s, agora - JANELA_ENTRADAS, numero_hash, repo_acesso.ENTRADA) >= LIMITE_ENTRADAS:
        log.warning("entrada recusada para %s: limite de tentativas", mascarar_numero(numero))
        return False
    repo_acesso.registrar_pedido(s, numero_hash, repo_acesso.ENTRADA, agora)
    return True


def _avisar_codigo_invalidado(s: Session, numero: str, agora: datetime, segredo: str) -> None:
    linhas = (f"Limite: {MAX_TENTATIVAS} códigos errados seguidos; o código foi invalidado", f"Número com final {numero[-2:]}")
    log.warning("código de %s invalidado: %d tentativas erradas", mascarar_numero(numero), MAX_TENTATIVAS)
    chave = _chave_numero(hash_segredo(segredo, numero))
    avisos.avisar(s, TipoAviso.SEGURANCA_LIMITE, chave, Dados(linhas=linhas), agora)


def entrar(
    s: Session, numero: str, codigo: str, aparelho: str, agora: datetime, segredo: str
) -> tuple[Usuario, str] | None:
    """Confere o último código do usuário (validade, uso, tentativas). Certo: marca usado, cria a sessão e devolve
    (usuário, token). Errado: conta a tentativa (o chamador grava antes de responder 401) e devolve None."""
    usuario = repo_acesso.usuario_por_numero(s, numero)
    if usuario is None or not usuario.ativo:
        return None
    atual = repo_acesso.ultimo_codigo(s, usuario.id)
    if atual is None or atual.usado_em is not None or atual.expira_em <= agora or atual.tentativas >= MAX_TENTATIVAS:
        log.info("entrada recusada para %s: sem código válido", mascarar_numero(numero))
        return None
    if not secrets.compare_digest(atual.hash_codigo, hash_segredo(segredo, codigo)):
        atual.tentativas += 1
        log.info("código errado para %s (tentativa %d de %d)", mascarar_numero(numero), atual.tentativas, MAX_TENTATIVAS)
        if atual.tentativas >= MAX_TENTATIVAS:
            _avisar_codigo_invalidado(s, numero, agora, segredo)
        return None
    atual.usado_em = agora
    token = gerar_token()
    repo_acesso.criar_sessao(s, usuario.id, hash_segredo(segredo, token), aparelho, agora, VALIDADE_SESSAO)
    log.info("entrada de %s (usuário %d, %s)", mascarar_numero(numero), usuario.id, aparelho)
    # Entrou: o problema de limite deste número (pedidos ou códigos errados) acabou.
    avisos.resolver(s, TipoAviso.SEGURANCA_LIMITE, _chave_numero(hash_segredo(segredo, numero)), agora)
    return usuario, token
