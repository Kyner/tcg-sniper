"""Visão geral do Dashboard: saúde de cada serviço, avisos, números do projeto e atividade do dia."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tcg_sniper.coletor_liga.agendador import TIPOS_LIGA
from tcg_sniper.coletor_liga.esfriamento import situacao_desafio
from tcg_sniper.config import Config
from tcg_sniper.consultas import historico, mensagens
from tcg_sniper.consultas.catalogo import (
    SituacaoCatalogo,
    inicio_do_dia,
    produtos_avaliados_desde,
    situacao_catalogo,
)
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db import repositorio_manutencao as repo_man
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    COLETOR_AMAZON_BUSCA,
    COLETOR_CASADOR,
    COLETOR_MANUTENCAO,
    COLETOR_NOTIFICADOR,
    ChamadaIA,
    Coleta,
    ConfigAmazon,
    EstadoColetorTipo,
    FilaAmazon,
    MensagemSaida,
    Oportunidade,
    PrecoAtualAmazon,
    PrecoAtualLiga,
    ProdutoLiga,
    StatusColeta,
    StatusManutencao,
    StatusMensagem,
    TipoColeta,
)
from tcg_sniper.formatacao import formatar_bytes
from tcg_sniper.manutencao.servico import HORA_BACKUP

# Texto do selo de cada situação (as chaves são as do macro `selo` de _componentes.html).
ROTULOS = {
    "ok": "funcionando",
    "rodando": "rodando",
    "parcial": "atenção",
    "pausado": "pausado",
    "pausado_desafio": "desafio pendente",
    "inativo": "desligado",
    "falha": "parado",
}
PROBLEMAS = ("pausado", "pausado_desafio", "falha")
TEXTO_NOTIFICADOR_DESLIGADO = (
    "Envio desligado; as mensagens ficam guardadas e saem quando ligar (ofertas vencidas expiram)"
)


@dataclass(frozen=True)
class SaudeServico:
    nome: str
    situacao: str  # chave do macro `selo`
    texto: str
    detalhe: str
    link: str
    selo: str | None = None  # texto do selo quando não é o padrão da situação
    aviso: str | None = None  # texto do aviso do Dashboard quando não é "<nome> — <texto>."

    @property
    def rotulo(self) -> str:
        return self.selo or ROTULOS[self.situacao]


@dataclass(frozen=True)
class Aviso:
    tipo: str  # "error" | "warning" (macro `aviso`)
    texto: str
    link: str
    rotulo_link: str
    acao: str | None = None  # POST de um botão ao lado do link (ex.: "Já conferi")
    rotulo_acao: str | None = None
    chave: str | None = None  # marca o tipo do aviso para o Dashboard novo ("servico_pausado", "servico_problema", "monitor_atrasado")


@dataclass(frozen=True)
class Numeros:
    catalogo: SituacaoCatalogo  # casamentos e IA contados por produto ativo
    produtos_ativos: int
    produtos_total: int
    gasto_mes: Decimal
    teto_mes: Decimal
    abertas: int
    alertas_hoje: int
    alertas_semana: int
    maior_desconto: Decimal | None
    desconto_min: int


@dataclass(frozen=True)
class Atividade:
    rotulo: str
    texto: str
    situacao: str  # "ok" | "rodando" | "parcial" | "falha" | "nenhum" (cor do ponto)


def _quando(dt: datetime, agora: datetime, zona: ZoneInfo) -> str:
    """"hoje 10:32", "ontem 10:32" ou "14/10/2026 10:32", no fuso configurado."""
    local, hoje = dt.astimezone(zona), agora.astimezone(zona).date()
    if local.date() == hoje:
        return f"hoje {local:%H:%M}"
    if local.date() == hoje - timedelta(days=1):
        return f"ontem {local:%H:%M}"
    return f"{local:%d/%m/%Y %H:%M}"


def _contar(s: Session, modelo, *condicoes) -> int:
    return s.scalar(select(func.count()).select_from(modelo).where(*condicoes)) or 0


def _coleta_rodando(s: Session, tipos: Sequence[TipoColeta]) -> Coleta | None:
    return s.scalar(
        select(Coleta)
        .where(Coleta.tipo.in_(tipos), Coleta.status == StatusColeta.RODANDO)
        .order_by(Coleta.id.desc())
        .limit(1)
    )


def _saude_liga(s: Session, agora: datetime, cfg: Config) -> SaudeServico:
    estado = repo.obter_estado(s, agora)
    link_logs = "/logs?aba=liga"
    if estado.estado is EstadoColetorTipo.PAUSADO_DESAFIO:
        return SaudeServico(
            "LigaMagic", "pausado_desafio", f"Desafio pendente: {estado.motivo or ''}".strip(),
            "Resolva pelo noVNC em Serviços.", "/servicos",
        )
    if estado.estado is EstadoColetorTipo.PAUSADO:
        return SaudeServico(
            "LigaMagic", "pausado", f"Pausada: {estado.motivo or 'sem motivo'}",
            "Não coleta até ser ligada de novo em Serviços.", "/servicos",
        )
    zona = cfg.zona
    inicio_dia = inicio_do_dia(agora, zona)
    alvo = inicio_dia.replace(hour=cfg.coleta_hora.hour, minute=cfg.coleta_hora.minute)
    ja_rodou = repo.coleta_iniciada_desde(s, TipoColeta.LISTAGEM, inicio_dia)
    ativos = _contar(s, ProdutoLiga, ProdutoLiga.ativo.is_(True))
    com_preco = s.scalar(
        select(func.count())
        .select_from(ProdutoLiga)
        .join(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(ProdutoLiga.ativo.is_(True), PrecoAtualLiga.preco_a_partir.is_not(None))
    ) or 0
    horario = f"por volta das {cfg.coleta_hora:%H:%M} (± {cfg.coleta_jitter_min} min)"
    if ja_rodou:
        proxima = f"Próxima amanhã {horario}"
    elif agora >= alvo:
        proxima = f"Próxima começa em instantes (hoje às {cfg.coleta_hora:%H:%M} ± {cfg.coleta_jitter_min} min)"
    else:
        proxima = f"Próxima hoje {horario}"
    detalhe = f"{proxima} · {com_preco} de {ativos} com preço"
    rodando = _coleta_rodando(s, TIPOS_LIGA)
    if rodando is not None:
        texto = f"Coleta em andamento desde {_quando(rodando.iniciada_em, agora, zona)}"
        return SaudeServico("LigaMagic", "rodando", texto, detalhe, link_logs)
    desafio = situacao_desafio(s, agora, zona, cfg.esfriar_desafio_min)
    if desafio.parada_hoje:
        return SaudeServico(
            "LigaMagic", "parcial", "Parada até amanhã (2º desafio)", f"Próxima amanhã {horario} · {com_preco} de {ativos} com preço",
            link_logs, selo="parada até amanhã",
        )
    if desafio.esfriando_ate is not None:
        texto = f"Esfriando até {desafio.esfriando_ate.astimezone(zona):%H:%M}"
        espera = f"Volta sozinha nessa hora, com pausas em dobro até o fim do dia · {com_preco} de {ativos} com preço"
        return SaudeServico("LigaMagic", "parcial", texto, espera, link_logs, selo="esfriando")
    ultima_ok = historico.ultima_coleta_sucesso(s, TIPOS_LIGA)
    texto_ok = f"Última coleta ok {_quando(ultima_ok.iniciada_em, agora, zona)}" if ultima_ok else "Nenhuma coleta ainda"
    ultima = historico.ultima_coleta_finalizada(s, TIPOS_LIGA)
    if ultima is not None and ultima.status is StatusColeta.FALHA:
        texto = f"A última coleta ({ultima.tipo.value}, {_quando(ultima.iniciada_em, agora, zona)}) falhou"
        return SaudeServico("LigaMagic", "parcial", texto, f"{texto_ok} · {detalhe}", link_logs)
    return SaudeServico("LigaMagic", "ok", texto_ok, detalhe, link_logs)


def _resumo_monitor(s: Session, agora: datetime, cfg: Config) -> str:
    cfg_amazon = repo_amz.obter_config(s)
    if not cfg_amazon.monitor_ligado:
        monitor = "monitor desligado"
    else:
        situacao = repo_amz.situacao_monitor(s, agora, cfg_amazon)
        if situacao.ultima is None:
            monitor = "monitor: nenhuma leitura ainda"
        else:
            monitor = f"monitor: última leitura {_quando(situacao.ultima, agora, cfg.zona)}"
            monitor += f" · rápida {situacao.rapidos} · lenta {situacao.lentos} · esgotado {situacao.esgotados}"
            if situacao.nunca_lidos:
                monitor += f" · nunca lidos {situacao.nunca_lidos}"
            if situacao.vencidos:
                monitor += f", {situacao.vencidos} na fila"
    if not cfg_amazon.checkout_ligado:
        conferencia = "conferência desligada"
    elif cfg_amazon.checkout_sem_login_em is not None:
        conferencia = "conferência parada: conta sem login"
    else:
        conferencia = "conferência ligada"
    return f"{monitor} · {conferencia}"


SEGUNDOS_POR_PAGINA = 3  # estimativa do tempo de abrir a página, somado à pausa média entre leituras


def capacidade_por_hora(cfg: ConfigAmazon) -> int:
    """Quantas páginas por hora o monitor consegue ler com as pausas configuradas.

    Conta otimista: supõe uma página e uma pausa por anúncio. "Exibir mais" das ofertas, perfis de vendedor,
    páginas do checkout e do carrinho também abrem páginas e entram no teto `monitor_max_paginas_hora`, então a
    leitura real de anúncios por hora fica abaixo deste número."""
    return math.floor(3600 / ((cfg.pausa_min_s + cfg.pausa_max_s) / 2 + SEGUNDOS_POR_PAGINA))


NOME_BUSCA = "Amazon (busca)"
NOME_MONITOR = "Amazon (monitor e checkout)"


def _buscas_na_ultima_hora(s: Session, agora: datetime) -> int:
    """Produtos buscados na última hora (um produto buscado duas vezes na hora conta uma)."""
    return _contar(s, FilaAmazon, FilaAmazon.ultima_busca_em > agora - timedelta(hours=1))


def _nunca_buscados(s: Session) -> int:
    """Produtos ativos que a busca ainda não visitou (inclusive os que nem entraram na fila)."""
    return s.scalar(
        select(func.count())
        .select_from(ProdutoLiga)
        .outerjoin(FilaAmazon, FilaAmazon.produto_id == ProdutoLiga.id)
        .where(ProdutoLiga.ativo.is_(True), FilaAmazon.ultima_busca_em.is_(None))
    ) or 0


def _saude_amazon_busca(s: Session, agora: datetime, cfg: Config) -> SaudeServico:
    estado = repo.obter_estado(s, agora, COLETOR_AMAZON_BUSCA)
    zona = cfg.zona
    detalhe = (
        f"{_buscas_na_ultima_hora(s, agora)} buscas na última hora · "
        f"{_nunca_buscados(s)} produtos ativos nunca buscados"
    )
    if estado.estado is EstadoColetorTipo.PAUSADO_DESAFIO:
        return SaudeServico(
            NOME_BUSCA, "pausado_desafio", f"CAPTCHA pendente: {estado.motivo or ''}".strip(),
            "Resolva pelo noVNC da busca (porta 6082) em Serviços.", "/servicos",
        )
    if estado.estado is EstadoColetorTipo.PAUSADO:
        return SaudeServico(NOME_BUSCA, "pausado", f"Pausada: {estado.motivo or 'sem motivo'}", detalhe, "/servicos")
    ultimo_ok = historico.ultima_coleta_sucesso(s, (TipoColeta.AMAZON,))
    ciclo = historico.ciclo_atual(s)
    if ciclo is not None:
        texto = f"Ciclo desde {ciclo.iniciada_em.astimezone(zona):%H:%M}"
        if ultimo_ok is not None:
            texto += f" · último ok {ultimo_ok.iniciada_em.astimezone(zona):%H:%M}"
        return SaudeServico(NOME_BUSCA, "rodando", texto, detalhe, "/logs?aba=amazon")
    config_amazon = repo_amz.obter_config(s)
    if not (config_amazon.janela_inicio <= agora.astimezone(zona).time() < config_amazon.janela_fim):
        janela = f"{config_amazon.janela_inicio:%H:%M}–{config_amazon.janela_fim:%H:%M}"
        return SaudeServico(NOME_BUSCA, "ok", f"Parada: fora do horário ({janela})", detalhe, "/logs?aba=amazon")
    ultimo = historico.ultima_coleta_finalizada(s, (TipoColeta.AMAZON,))
    if ultimo is None:
        texto = "Nenhum ciclo ainda"
    else:
        texto = f"Último ciclo {_quando(ultimo.iniciada_em, agora, zona)} ({ultimo.status.value.replace('_', ' ')})"
    return SaudeServico(NOME_BUSCA, "ok", texto, detalhe, "/logs?aba=amazon")


def _saude_amazon_monitor(s: Session, agora: datetime, cfg: Config) -> SaudeServico:
    estado = repo.obter_estado(s, agora, COLETOR_AMAZON)
    lidos = _contar(s, PrecoAtualAmazon, PrecoAtualAmazon.coletado_em >= agora - timedelta(hours=24))
    detalhe = f"{lidos} preços lidos nas últimas 24 h · {_resumo_monitor(s, agora, cfg)}"
    if estado.estado is EstadoColetorTipo.PAUSADO_DESAFIO:
        return SaudeServico(
            NOME_MONITOR, "pausado_desafio", f"CAPTCHA pendente: {estado.motivo or ''}".strip(),
            "Resolva pelo noVNC do monitor (porta 6081) em Serviços.", "/servicos",
        )
    if estado.estado is EstadoColetorTipo.PAUSADO:
        return SaudeServico(NOME_MONITOR, "pausado", f"Pausado: {estado.motivo or 'sem motivo'}", detalhe, "/servicos")
    config_amazon = repo_amz.obter_config(s)
    if not config_amazon.monitor_ligado:
        if config_amazon.checkout_ligado:
            return SaudeServico(NOME_MONITOR, "ok", "Monitor desligado · checkout ligado", detalhe, "/servicos")
        return SaudeServico(NOME_MONITOR, "inativo", "Monitor desligado", detalhe, "/servicos")
    local = agora.astimezone(cfg.zona).time()
    if not (config_amazon.monitor_janela_inicio <= local < config_amazon.monitor_janela_fim):
        janela = f"{config_amazon.monitor_janela_inicio:%H:%M}–{config_amazon.monitor_janela_fim:%H:%M}"
        return SaudeServico(NOME_MONITOR, "ok", f"Parado: fora do horário ({janela})", detalhe, "/logs?aba=monitor")
    texto = f"Até {config_amazon.monitor_max_paginas_hora} páginas por hora no navegador logado"
    return SaudeServico(NOME_MONITOR, "ok", texto, detalhe, "/logs?aba=monitor")


def _saude_casador(s: Session, agora: datetime, cfg: Config, chave_ia: bool) -> SaudeServico:
    estado = repo.obter_estado(s, agora, COLETOR_CASADOR)
    cfg_ia = repo_ia.obter_config_ia(s, agora)
    if estado.estado is not EstadoColetorTipo.ATIVO:
        return SaudeServico(
            "Casador (IA)", "pausado", f"Pausado: {estado.motivo or 'sem motivo'}", "Retome em Serviços.", "/servicos"
        )
    if not cfg_ia.ligado:
        return SaudeServico(
            "Casador (IA)", "inativo", "IA desligada", "Liga em Configurações → IA.", "/configuracoes", "desligada"
        )
    if not chave_ia:
        return SaudeServico(
            "Casador (IA)", "pausado", "IA ligada, mas sem chave",
            "Defina OPENAI_API_KEY no .env e reinicie o casador.", "/servicos", "sem chave",
        )
    ultima = s.scalar(select(func.max(ChamadaIA.em)))
    automatico = "automático ligado" if cfg_ia.automatico else "automático desligado"
    texto = f"Última chamada {_quando(ultima, agora, cfg.zona)}" if ultima else "Nenhuma chamada ainda"
    gasto = repo_ia.gasto(s, agora, cfg.zona)
    detalhe = f"{cfg_ia.modelo} · {usd(gasto.dia_usd)} de {usd(cfg_ia.teto_dia_usd)} hoje"
    return SaudeServico("Casador (IA)", "ok", f"{texto} · {automatico}", detalhe, "/logs?aba=ia")


def usd(valor: Decimal) -> str:
    return f"US$ {valor:.2f}".replace(".", ",")


def _mensagens_hoje(s: Session, agora: datetime, zona: ZoneInfo) -> tuple[int, int]:
    inicio = inicio_do_dia(agora, zona)
    enviadas = _contar(s, MensagemSaida, MensagemSaida.enviada_em >= inicio)
    falhas = _contar(s, MensagemSaida, MensagemSaida.status == StatusMensagem.FALHA, MensagemSaida.atualizado_em >= inicio)
    return enviadas, falhas


def _saude_whatsapp(
    s: Session, agora: datetime, cfg: Config, resumo: mensagens.ResumoMensagens
) -> SaudeServico:
    situacao, ultimo = mensagens.estado_notificador(s, agora)
    enviadas, _ = _mensagens_hoje(s, agora, cfg.zona)
    detalhe = f"{enviadas} enviadas hoje · {resumo.falhas} com falha · {resumo.paradas} paradas"
    if situacao == "nunca":
        aviso = "O notificador nunca rodou — veja Serviços."
        return SaudeServico("WhatsApp", "falha", "Notificador nunca rodou", detalhe, "/servicos", aviso=aviso)
    if situacao == "parado":
        quando = _quando(ultimo, agora, cfg.zona)
        aviso = f"O notificador está parado desde {quando} — veja Serviços."
        texto = f"Notificador parado desde {quando}"
        return SaudeServico("WhatsApp", "falha", texto, detalhe, "/servicos", aviso=aviso)
    if repo.obter_estado(s, agora, COLETOR_NOTIFICADOR).estado is not EstadoColetorTipo.ATIVO:
        return SaudeServico(
            "WhatsApp", "pausado", TEXTO_NOTIFICADOR_DESLIGADO, detalhe, "/servicos"
        )
    segundos = max(0, int((agora - ultimo).total_seconds()))
    return SaudeServico("WhatsApp", "ok", f"Notificador vivo · último ciclo há {segundos} s", detalhe, "/mensagens")


def saude_servicos(
    s: Session,
    agora: datetime,
    config_efetiva: Config,
    chave_ia: bool,
    resumo: mensagens.ResumoMensagens | None = None,
) -> list[SaudeServico]:
    """Um item por serviço, na ordem LigaMagic, Amazon (busca), Amazon (monitor e checkout), Casador (IA), WhatsApp. `resumo` (das
    mensagens) é reaproveitado quando já foi lido."""
    if resumo is None:
        resumo = mensagens.resumo(s, agora)
    return [
        _saude_liga(s, agora, config_efetiva),
        _saude_amazon_busca(s, agora, config_efetiva),
        _saude_amazon_monitor(s, agora, config_efetiva),
        _saude_casador(s, agora, config_efetiva, chave_ia),
        _saude_whatsapp(s, agora, config_efetiva, resumo),
    ]


MANUTENCAO_VIVA = timedelta(minutes=5)  # o serviço registra que está vivo a cada minuto
BACKUP_ATRASADO = timedelta(hours=26)
EXECUCAO_LONGA = timedelta(hours=2)  # um backup "rodando" há mais que isso não explica o serviço calado


def processo_manutencao(s: Session, agora: datetime) -> tuple[str, datetime | None]:
    """("rodando" | "parado" | "nunca", último ciclo) do serviço de manutenção."""
    ultimo = repo_man.ultimo_ciclo(s)
    if ultimo is None:
        return "nunca", None
    return ("rodando" if agora - ultimo < MANUTENCAO_VIVA else "parado"), ultimo


def saude_backup(s: Session, agora: datetime, cfg: Config) -> SaudeServico:
    """Card "Backup" do Dashboard: serviço de manutenção vivo, ligado e com um backup ok recente."""
    zona = cfg.zona
    link = "/logs?aba=manutencao"
    ultima = repo_man.ultima(s)
    rodando = ultima is not None and ultima.status is StatusManutencao.RODANDO and agora - ultima.inicio < EXECUCAO_LONGA
    ok = repo_man.ultima_ok(s)
    if ok is not None:
        r2 = "sim" if ok.enviado_r2 else "não (só local)"
        detalhe = f"{formatar_bytes(ok.tamanho_bytes)} · cópia no R2: {r2} · todo dia às {HORA_BACKUP:%H:%M}"
    else:
        detalhe = f"Todo dia às {HORA_BACKUP:%H:%M}; ao subir, roda já se o último tiver mais de 24 h"
    processo, ultimo_ciclo = processo_manutencao(s, agora)
    if processo != "rodando" and not rodando:
        if processo == "nunca":
            aviso = "O serviço de manutenção (backup) nunca rodou — veja Serviços."
            return SaudeServico("Backup", "falha", "Serviço de manutenção nunca rodou", detalhe, "/servicos", aviso=aviso)
        quando = _quando(ultimo_ciclo, agora, zona)
        aviso = f"O serviço de manutenção (backup) está parado desde {quando} — veja Serviços."
        texto = f"Serviço de manutenção parado desde {quando}"
        return SaudeServico("Backup", "falha", texto, detalhe, "/servicos", aviso=aviso)
    estado = repo.obter_estado(s, agora, COLETOR_MANUTENCAO)
    if estado.estado is not EstadoColetorTipo.ATIVO:
        return SaudeServico(
            "Backup", "pausado", f"Backup desligado: {estado.motivo or 'sem motivo'}", detalhe, "/servicos", "desligado"
        )
    if rodando:
        return SaudeServico("Backup", "rodando", f"Backup em andamento desde {_quando(ultima.inicio, agora, zona)}", detalhe, link)
    if ok is None:
        return SaudeServico("Backup", "parcial", "Nenhum backup ainda", detalhe, link)
    texto_ok = f"Último backup {_quando(ok.inicio, agora, zona)} · {formatar_bytes(ok.tamanho_bytes)}"
    if ultima is not None and ultima.status is StatusManutencao.ERRO:
        texto = f"O último backup ({_quando(ultima.inicio, agora, zona)}) teve erro"
        return SaudeServico("Backup", "parcial", texto, f"{ultima.erro or 'erro'} · último ok: {texto_ok}", link)
    if agora - ok.inicio > BACKUP_ATRASADO:
        texto = f"Último backup ok {_quando(ok.inicio, agora, zona)}: mais de 26 h"
        return SaudeServico("Backup", "parcial", texto, detalhe, link)
    return SaudeServico("Backup", "ok", texto_ok, detalhe, link)


def _chave_servico(servico: SaudeServico) -> str:
    return "servico_pausado" if servico.situacao == "pausado" else "servico_problema"


def avisos_backup(backup: SaudeServico) -> list[Aviso]:
    """Serviço parado ou desligado vira erro; backup atrasado ou com erro vira atenção."""
    if backup.situacao in PROBLEMAS:
        return [
            Aviso(
                "error", backup.aviso or f"{backup.nome} — {backup.texto}.", "/servicos", "Ir para Serviços",
                chave=_chave_servico(backup),
            )
        ]
    if backup.situacao == "parcial":
        return [Aviso("warning", f"{backup.nome} — {backup.texto}.", "/logs?aba=manutencao", "Ver nos logs")]
    return []


def avisos(
    s: Session,
    agora: datetime,
    config_efetiva: Config,
    servicos: Sequence[SaudeServico],
    resumo: mensagens.ResumoMensagens,
) -> list[Aviso]:
    """Um aviso por problema: serviço pausado ou parado, mensagens presas ou com falha, e a última
    coleta da LigaMagic ou o último ciclo da Amazon que terminou com falha. Reaproveita a saúde dos
    serviços e o resumo das mensagens já lidos."""
    lista = [
        Aviso(
            "error", servico.aviso or f"{servico.nome} — {servico.texto}.", "/servicos", "Ir para Serviços",
            chave=_chave_servico(servico),
        )
        for servico in servicos
        if servico.situacao in PROBLEMAS
    ]
    if resumo.aviso:
        lista.append(Aviso("warning", resumo.aviso, resumo.link_aviso, "Ir para Mensagens"))
    for tipos, aba in ((TIPOS_LIGA, "liga"), ((TipoColeta.AMAZON,), "amazon")):
        ultima = historico.ultima_coleta_finalizada(s, tipos)
        if ultima is not None and ultima.status is StatusColeta.FALHA:
            quando = _quando(ultima.iniciada_em, agora, config_efetiva.zona)
            if aba == "liga":
                texto = f"A última coleta da LigaMagic ({ultima.tipo.value}, {quando}) terminou com falha."
            else:
                texto = f"O último ciclo da busca na Amazon ({quando}) terminou com falha."
            if ultima.erro:
                texto += f" {ultima.erro}"
            lista.append(Aviso("warning", texto, f"/logs?aba={aba}", "Ver nos logs"))
    lista += _avisos_monitor(s, agora, config_efetiva)
    return lista


def _avisos_monitor(s: Session, agora: datetime, cfg: Config) -> list[Aviso]:
    """Conta Amazon sem login (a conferência parou), monitor que não cabe no teto por hora e monitor
    atrasado (leitura mais velha que dois intervalos, com a janela aberta há pelo menos dois intervalos)."""
    cfg_amazon = repo_amz.obter_config(s)
    lista = [
        Aviso(
            "error",
            f"Confira o carrinho da Amazon: pode haver 1× {asin} de uma conferência automática "
            f"({_quando(conferencia.em, agora, cfg.zona)}); tire à mão pelo noVNC (porta 6081) se não for seu.",
            "/servicos",
            "Ir para Serviços",
            f"/amazon/carrinho/{conferencia.id}/conferido",
            "Já conferi",
        )
        for conferencia, asin in repo_amz.conferencias_a_conferir_a_mao(s)
    ]
    if cfg_amazon.checkout_ligado and cfg_amazon.checkout_sem_login_em is not None:
        desde = _quando(cfg_amazon.checkout_sem_login_em, agora, cfg.zona)
        lista.append(
            Aviso(
                "error",
                f"A conta Amazon está sem login desde {desde}: a conferência de checkout parou (o monitor continua). "
                "Logue a conta no noVNC (porta 6081) e clique em Retomar conferência.",
                "/servicos",
                "Ir para Serviços",
            )
        )
    if not cfg_amazon.monitor_ligado:
        return lista
    intervalo = cfg_amazon.monitor_intervalo_min
    situacao = repo_amz.situacao_monitor(s, agora, cfg_amazon)
    exigido = math.ceil(situacao.rapidos * 60 / intervalo)
    limite = min(cfg_amazon.monitor_max_paginas_hora, capacidade_por_hora(cfg_amazon))
    if exigido > limite:
        lista.append(
            Aviso(
                "warning",
                f"O monitor precisa de {exigido} páginas por hora para ler os {situacao.rapidos} anúncios da fila "
                f"rápida a cada {intervalo} min, acima do que cabe ({limite} por hora: teto "
                f"{cfg_amazon.monitor_max_paginas_hora}, pausas de {cfg_amazon.pausa_min_s}–{cfg_amazon.pausa_max_s} s): "
                "as leituras da fila rápida vão atrasar.",
                "/configuracoes",
                "Ajustar em Configurações",
            )
        )
    local = agora.astimezone(cfg.zona)
    abertura = local.replace(
        hour=cfg_amazon.monitor_janela_inicio.hour, minute=cfg_amazon.monitor_janela_inicio.minute, second=0, microsecond=0
    )
    dois_intervalos = timedelta(minutes=2 * intervalo)
    aberta_ha_tempo = (
        cfg_amazon.monitor_janela_inicio <= local.time() < cfg_amazon.monitor_janela_fim and local - abertura >= dois_intervalos
    )
    ativo = repo.obter_estado(s, agora, COLETOR_AMAZON).estado is EstadoColetorTipo.ATIVO
    if ativo and aberta_ha_tempo and situacao.mais_antiga_rapida is not None and agora - situacao.mais_antiga_rapida >= dois_intervalos:
        minutos = int((agora - situacao.mais_antiga_rapida).total_seconds() // 60)
        lista.append(
            Aviso(
                "warning",
                f"O monitor está atrasado: {situacao.vencidos} anúncio(s) com leitura vencida, o mais antigo lido há {minutos} min.",
                "/logs?aba=monitor",
                "Ver nos logs",
                chave="monitor_atrasado",
            )
        )
    return lista


def numeros(s: Session, agora: datetime, config_efetiva: Config) -> Numeros:
    """Números do Dashboard; casamentos e IA por produto ativo (`consultas.catalogo`)."""
    catalogo = situacao_catalogo(s, agora, config_efetiva.zona)
    cfg_ia = repo_ia.obter_config_ia(s, agora)
    inicio_dia = inicio_do_dia(agora, config_efetiva.zona)
    return Numeros(
        catalogo=catalogo,
        produtos_ativos=catalogo.produtos_ativos,
        produtos_total=_contar(s, ProdutoLiga),
        gasto_mes=repo_ia.gasto(s, agora, config_efetiva.zona).mes_usd,
        teto_mes=cfg_ia.teto_mes_usd,
        abertas=_contar(s, Oportunidade, Oportunidade.fechada_em.is_(None)),
        alertas_hoje=_contar(s, Oportunidade, Oportunidade.alertada_em >= inicio_dia),
        alertas_semana=_contar(s, Oportunidade, Oportunidade.alertada_em >= inicio_dia - timedelta(days=6)),
        maior_desconto=s.scalar(select(func.max(Oportunidade.desconto_pct)).where(Oportunidade.fechada_em.is_(None))),
        desconto_min=repo_amz.obter_config(s).desconto_min_pct,
    )


def _pior(situacoes: Sequence[StatusColeta]) -> str:
    if StatusColeta.FALHA in situacoes or StatusColeta.PAUSADA_DESAFIO in situacoes:
        return "falha"
    if StatusColeta.RODANDO in situacoes:
        return "rodando"
    if StatusColeta.PARCIAL in situacoes:
        return "parcial"
    return "ok" if situacoes else "nenhum"


def atividade_hoje(s: Session, agora: datetime, config_efetiva: Config) -> list[Atividade]:
    zona = config_efetiva.zona
    inicio = inicio_do_dia(agora, zona)
    ultimas = []
    for tipo in TIPOS_LIGA:
        coleta = s.scalar(
            select(Coleta).where(Coleta.tipo == tipo, Coleta.iniciada_em >= inicio).order_by(Coleta.id.desc()).limit(1)
        )
        if coleta is not None:
            ultimas.append(coleta)
    liga = " · ".join(f"{c.tipo.value} {c.iniciada_em.astimezone(zona):%H:%M}" for c in ultimas) or "nenhuma hoje"

    ciclos = list(s.scalars(select(Coleta.status).where(Coleta.tipo == TipoColeta.AMAZON, Coleta.iniciada_em >= inicio)))
    lidos = _contar(s, PrecoAtualAmazon, PrecoAtualAmazon.coletado_em >= inicio)
    situacao_amazon = "rodando" if StatusColeta.RODANDO in ciclos else ("ok" if ciclos else "nenhum")

    chamadas = _contar(s, ChamadaIA, ChamadaIA.em >= inicio)
    erros = _contar(s, ChamadaIA, ChamadaIA.em >= inicio, ChamadaIA.ok.is_(False))
    situacao_ia = "falha" if erros else ("ok" if chamadas else "nenhum")
    produtos_ia = produtos_avaliados_desde(s, inicio)
    texto_ia = f"{chamadas} · {erros} com erro · {produtos_ia} {'produto avaliado' if produtos_ia == 1 else 'produtos avaliados'}"

    enviadas, falhas = _mensagens_hoje(s, agora, zona)
    situacao_msgs = "falha" if falhas else ("ok" if enviadas else "nenhum")
    return [
        Atividade("Coleta da LigaMagic", liga, _pior([c.status for c in ultimas])),
        Atividade(
            "Buscas na Amazon",
            f"{len(ciclos)} {'ciclo' if len(ciclos) == 1 else 'ciclos'} · {lidos} preços",
            situacao_amazon,
        ),
        Atividade("Chamadas da IA", texto_ia, situacao_ia),
        Atividade("Mensagens do WhatsApp", f"{enviadas} enviadas · {falhas} falhas", situacao_msgs),
    ]
