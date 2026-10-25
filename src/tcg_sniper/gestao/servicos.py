"""Ações sobre os serviços (ligar, desligar, retomar, rodar agora, monitor e checkout da Amazon, carrinho).

Usado pelo admin antigo e pela API nova. Cada ação devolve a chave de `MENSAGENS` com o que aconteceu.
A transação é de quem chama (`with sessoes() as s, s.begin()`).
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from tcg_sniper.avisos import servico as avisos
from tcg_sniper.avisos.catalogo import Dados, TipoAviso
from tcg_sniper.coletor_amazon.config import aplicar_config
from tcg_sniper.coletor_liga.esfriamento import situacao_desafio
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    COLETOR_AMAZON_BUSCA,
    COLETOR_CASADOR,
    COLETOR_LIGA,
    COLETOR_MANUTENCAO,
    COLETOR_NOTIFICADOR,
    AnuncioAmazon,
    ConferenciaCheckout,
    EstadoColetorTipo,
)


class Servico(StrEnum):
    LIGA = "liga"
    AMAZON_BUSCA = "amazon_busca"
    AMAZON_MONITOR = "amazon_monitor"
    CASADOR = "casador"
    WHATSAPP = "whatsapp"
    BACKUP = "backup"


COLETOR: dict[Servico, str] = {
    Servico.LIGA: COLETOR_LIGA,
    Servico.AMAZON_BUSCA: COLETOR_AMAZON_BUSCA,
    Servico.AMAZON_MONITOR: COLETOR_AMAZON,
    Servico.CASADOR: COLETOR_CASADOR,
    Servico.WHATSAPP: COLETOR_NOTIFICADOR,
    Servico.BACKUP: COLETOR_MANUTENCAO,
}

NOMES: dict[Servico, str] = {
    Servico.LIGA: "LigaMagic",
    Servico.AMAZON_BUSCA: "Amazon (busca)",
    Servico.AMAZON_MONITOR: "Amazon (monitor e checkout)",
    Servico.CASADOR: "Casador (IA)",
    Servico.WHATSAPP: "WhatsApp (notificador)",
    Servico.BACKUP: "Backup (manutenção)",
}

MENSAGENS = {
    "rodar": "Execução da LigaMagic solicitada; começa em até 1 minuto.",
    "retomar": "Coleta da LigaMagic retomada.",
    "retomar_esfriando": (
        "Desafio resolvido. A coleta volta sozinha depois do esfriamento (o card mostra até quando), "
        "com pausas em dobro até o fim do dia."
    ),
    "retomar_parada": "Desafio resolvido. Foi o 2º de hoje: a coleta da LigaMagic só volta amanhã, no horário de sempre.",
    "liga_esfriando": "Execução da LigaMagic solicitada; começa quando o esfriamento terminar (o card mostra até quando).",
    "liga_parada_hoje": "A LigaMagic teve o 2º desafio hoje e fica parada até amanhã; nada foi solicitado.",
    "liga_pausar": "Coleta da LigaMagic desligada. Volta quando você ligar de novo.",
    "liga_retomar": "Coleta da LigaMagic ligada; segue o horário diário.",
    "notificador_pausar": (
        "Envio do WhatsApp desligado. As mensagens ficam guardadas e saem quando ligar (ofertas vencidas expiram)."
    ),
    "desafio_pendente": "Há um desafio pendente: resolva pelo noVNC e clique em Retomar (nada foi desligado).",
    "notificador_retomar": "Envio do WhatsApp ligado.",
    "amazon_pausar": "Monitor e checkout da Amazon pausados. A busca segue.",
    "amazon_busca_pausar": "Busca na Amazon pausada. O monitor e o checkout seguem.",
    "monitor_ligar": "Monitor de preço ligado.",
    "monitor_desligar": "Monitor de preço desligado. A busca de anúncios novos continua.",
    "checkout_ligar": "Conferência de checkout ligada.",
    "checkout_desligar": "Conferência de checkout desligada. Os alertas usam o preço anunciado.",
    "checkout_retomar": "Conferência de checkout retomada.",
    "carrinho_conferido": "Carrinho conferido: o aviso saiu.",
    "amazon_retomar": "Monitor e checkout da Amazon retomados.",
    "amazon_busca_retomar": "Busca na Amazon retomada.",
    "casador_pausar": "Casador pausado.",
    "casador_retomar": "Casador retomado; roda em até 1 minuto.",
    "casador_rodar": "Rodada do casador solicitada; começa em até 1 minuto.",
    "manutencao_pausar": "Backup e limpeza desligados. Ligue de novo para não ficar sem backup.",
    "manutencao_retomar": "Backup e limpeza ligados; se o de hoje ainda não rodou, roda em até 1 minuto.",
}

# Prefixo das chaves de mensagem de cada serviço (liga_pausar, notificador_retomar, ...).
_PREFIXO = {
    Servico.LIGA: "liga",
    Servico.AMAZON_BUSCA: "amazon_busca",
    Servico.AMAZON_MONITOR: "amazon",
    Servico.CASADOR: "casador",
    Servico.WHATSAPP: "notificador",
    Servico.BACKUP: "manutencao",
}

# Ao religar, quem segue o próprio horário não pede execução na hora; os demais pedem.
_SEM_SOLICITAR = frozenset({Servico.LIGA, Servico.WHATSAPP, Servico.BACKUP})


def _avisar_mudanca(s: Session, servico: Servico, novo: str, agora: datetime) -> None:
    dados = Dados(titulo_extra=NOMES[servico], linhas=(f"Novo estado: {novo}",))
    avisos.avisar(s, TipoAviso.SERVICO_PAUSADO_MANUAL, COLETOR[servico], dados, agora)


def ligar(s: Session, servico: Servico, agora: datetime) -> str:
    repo.retomar(s, agora, COLETOR[servico], solicitar=servico not in _SEM_SOLICITAR)
    _avisar_mudanca(s, servico, "ativo", agora)
    return f"{_PREFIXO[servico]}_retomar"


def desligar(s: Session, servico: Servico, agora: datetime) -> str:
    """Pausa manual; um desafio pendente não é sobrescrito (só sai com Retomar, depois de resolvido)."""
    coletor = COLETOR[servico]
    if servico is not Servico.CASADOR and (
        repo.obter_estado(s, agora, coletor).estado is EstadoColetorTipo.PAUSADO_DESAFIO
    ):
        return "desafio_pendente"
    repo.pausar(s, "pausado no admin", agora, coletor)
    _avisar_mudanca(s, servico, "pausado", agora)
    return f"{_PREFIXO[servico]}_pausar"


def retomar_desafio(s: Session, servico: Servico, zona: ZoneInfo, cfg_efetiva, agora: datetime) -> str:
    """Retoma depois de o desafio ser resolvido (Liga) ou do CAPTCHA (busca e monitor da Amazon), pedindo
    uma execução já. Na Liga a mensagem diz se há esfriamento ou se foi o 2º desafio do dia.

    Fora do estado de desafio faz o mesmo que a rota antiga: retoma e avisa (idempotente)."""
    if servico not in (Servico.LIGA, Servico.AMAZON_BUSCA, Servico.AMAZON_MONITOR):
        raise ValueError(f"serviço sem desafio para retomar: {servico}")
    repo.retomar(s, agora, COLETOR[servico], solicitar=True)
    _avisar_mudanca(s, servico, "ativo", agora)
    if servico is not Servico.LIGA:
        return f"{_PREFIXO[servico]}_retomar"
    desafio = situacao_desafio(s, agora, zona, cfg_efetiva.esfriar_desafio_min)
    if desafio.parada_hoje:
        return "retomar_parada"
    return "retomar_esfriando" if desafio.esfriando_ate is not None else "retomar"


def rodar_agora(s: Session, servico: Servico, zona: ZoneInfo, cfg_efetiva, agora: datetime) -> str:
    """Só Liga e Casador. A Liga respeita o esfriamento (o pedido espera) e a parada do 2º desafio
    (nada é pedido)."""
    if servico is Servico.CASADOR:
        repo.solicitar_execucao(s, agora, COLETOR_CASADOR)
        return "casador_rodar"
    if servico is not Servico.LIGA:
        raise ValueError(f"serviço sem 'rodar agora': {servico}")
    desafio = situacao_desafio(s, agora, zona, cfg_efetiva.esfriar_desafio_min)
    if desafio.parada_hoje:
        return "liga_parada_hoje"
    repo.solicitar_execucao(s, agora)
    return "liga_esfriando" if desafio.esfriando_ate is not None else "rodar"


def ajustar_amazon(
    s: Session, chave: Literal["monitor_ligado", "checkout_ligado"], ligado: bool, agora: datetime
) -> str:
    """Liga ou desliga o monitor de preço ou a conferência de checkout (sem aviso)."""
    aplicar_config(s, {chave: ligado}, agora)
    base = "monitor" if chave == "monitor_ligado" else "checkout"
    return f"{base}_{'ligar' if ligado else 'desligar'}"


def retomar_checkout(s: Session, agora: datetime) -> str:
    """Tira a marca de "sem login" e deixa o checkout voltar a conferir."""
    aplicar_config(s, {"checkout_sem_login_em": None}, agora)
    return "checkout_retomar"


def carrinho_conferido(s: Session, conferencia_id: int, agora: datetime) -> bool:
    """"Já conferi": a conferência sai do "conferir à mão" e o aviso do carrinho daquele ASIN fecha.
    False se a conferência não existe ou não estava aguardando conferência à mão (nada é marcado)."""
    conferencia = s.get(ConferenciaCheckout, conferencia_id)
    anuncio = s.get(AnuncioAmazon, conferencia.anuncio_id) if conferencia is not None else None
    resolvida = repo_amz.marcar_item_removido(s, conferencia_id)
    if resolvida and anuncio is not None:
        avisos.resolver(s, TipoAviso.AMAZON_CARRINHO, anuncio.asin, agora)
    return resolvida
