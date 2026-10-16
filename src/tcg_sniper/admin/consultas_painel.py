"""Visão geral do Dashboard: saúde de cada serviço, avisos, números do projeto e atividade do dia."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from tcg_sniper.admin import consultas, consultas_amazon, consultas_mensagens
from tcg_sniper.coletor_liga.agendador import TIPOS_LIGA
from tcg_sniper.config import Config
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import (
    COLETOR_AMAZON,
    COLETOR_CASADOR,
    COLETOR_NOTIFICADOR,
    AnuncioAmazon,
    AvaliacaoIA,
    ChamadaIA,
    Coleta,
    EstadoColetorTipo,
    MensagemSaida,
    Oportunidade,
    PrecoAtualAmazon,
    PrecoAtualLiga,
    ProdutoLiga,
    StatusCasamento,
    StatusColeta,
    StatusMensagem,
    TipoColeta,
)

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


@dataclass(frozen=True)
class SaudeServico:
    nome: str
    situacao: str  # chave do macro `selo`
    texto: str
    detalhe: str
    link: str
    selo: str | None = None  # texto do selo quando não é o padrão da situação

    @property
    def rotulo(self) -> str:
        return self.selo or ROTULOS[self.situacao]


@dataclass(frozen=True)
class Aviso:
    tipo: str  # "error" | "warning" (macro `aviso`)
    texto: str
    link: str
    rotulo_link: str


@dataclass(frozen=True)
class Numeros:
    confirmados: int
    pendentes: int
    ignorados: int
    produtos_com_par: int
    produtos_ativos: int
    produtos_total: int
    avaliados: int
    pelo_automatico: int
    esperando_voce: int
    automatico: bool
    confianca_confirmar: int
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


def _inicio_do_dia(agora: datetime, zona: ZoneInfo) -> datetime:
    return agora.astimezone(zona).replace(hour=0, minute=0, second=0, microsecond=0)


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
        select(Coleta).where(Coleta.tipo.in_(tipos), Coleta.status == StatusColeta.RODANDO).order_by(Coleta.id.desc())
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
    inicio_dia = _inicio_do_dia(agora, zona)
    alvo = inicio_dia.replace(hour=cfg.coleta_hora.hour, minute=cfg.coleta_hora.minute)
    ja_rodou = repo.coleta_iniciada_desde(s, TipoColeta.LISTAGEM, inicio_dia)
    dia = "amanhã" if ja_rodou or agora > alvo + timedelta(minutes=cfg.coleta_jitter_min) else "hoje"
    ativos = _contar(s, ProdutoLiga, ProdutoLiga.ativo.is_(True))
    com_preco = s.scalar(
        select(func.count())
        .select_from(ProdutoLiga)
        .join(PrecoAtualLiga, PrecoAtualLiga.produto_id == ProdutoLiga.id)
        .where(ProdutoLiga.ativo.is_(True), PrecoAtualLiga.preco_a_partir.is_not(None))
    ) or 0
    detalhe = (
        f"Próxima {dia} por volta das {cfg.coleta_hora:%H:%M} (± {cfg.coleta_jitter_min} min)"
        f" · {com_preco} de {ativos} com preço"
    )
    rodando = _coleta_rodando(s, TIPOS_LIGA)
    if rodando is not None:
        texto = f"Coleta em andamento desde {_quando(rodando.iniciada_em, agora, zona)}"
        return SaudeServico("LigaMagic", "rodando", texto, detalhe, link_logs)
    ultima_ok = consultas.ultima_coleta_sucesso(s, TIPOS_LIGA)
    texto_ok = f"Última coleta ok {_quando(ultima_ok.iniciada_em, agora, zona)}" if ultima_ok else "Nenhuma coleta ainda"
    ultima = consultas.ultima_coleta_finalizada(s, TIPOS_LIGA)
    if ultima is not None and ultima.status is StatusColeta.FALHA:
        texto = f"A última coleta ({ultima.tipo.value}, {_quando(ultima.iniciada_em, agora, zona)}) falhou"
        return SaudeServico("LigaMagic", "parcial", texto, f"{texto_ok} · {detalhe}", link_logs)
    return SaudeServico("LigaMagic", "ok", texto_ok, detalhe, link_logs)


def _saude_amazon(s: Session, agora: datetime, cfg: Config) -> SaudeServico:
    estado = repo.obter_estado(s, agora, COLETOR_AMAZON)
    zona = cfg.zona
    lidos = _contar(s, PrecoAtualAmazon, PrecoAtualAmazon.coletado_em >= agora - timedelta(hours=24))
    detalhe = f"{lidos} preços lidos nas últimas 24 h"
    if estado.estado is EstadoColetorTipo.PAUSADO_DESAFIO:
        return SaudeServico(
            "Amazon", "pausado_desafio", f"CAPTCHA pendente: {estado.motivo or ''}".strip(),
            "Resolva pelo noVNC em Serviços.", "/servicos",
        )
    if estado.estado is EstadoColetorTipo.PAUSADO:
        return SaudeServico("Amazon", "pausado", f"Pausada: {estado.motivo or 'sem motivo'}", detalhe, "/servicos")
    ultimo_ok = consultas.ultima_coleta_sucesso(s, (TipoColeta.AMAZON,))
    ciclo = consultas_amazon.ciclo_atual(s)
    if ciclo is not None:
        texto = f"Ciclo desde {ciclo.iniciada_em.astimezone(zona):%H:%M}"
        if ultimo_ok is not None:
            texto += f" · último ok {ultimo_ok.iniciada_em.astimezone(zona):%H:%M}"
        return SaudeServico("Amazon", "rodando", texto, detalhe, "/logs?aba=amazon")
    config_amazon = repo_amz.obter_config(s)
    if not (config_amazon.janela_inicio <= agora.astimezone(zona).time() < config_amazon.janela_fim):
        janela = f"{config_amazon.janela_inicio:%H:%M}–{config_amazon.janela_fim:%H:%M}"
        return SaudeServico("Amazon", "ok", f"Parada: fora do horário ({janela})", detalhe, "/logs?aba=amazon")
    ultimo = consultas.ultima_coleta_finalizada(s, (TipoColeta.AMAZON,))
    if ultimo is None:
        texto = "Nenhum ciclo ainda"
    else:
        texto = f"Último ciclo {_quando(ultimo.iniciada_em, agora, zona)} ({ultimo.status.value.replace('_', ' ')})"
    return SaudeServico("Amazon", "ok", texto, detalhe, "/logs?aba=amazon")


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
    detalhe = f"{cfg_ia.modelo} · {_usd(gasto.dia_usd)} de {_usd(cfg_ia.teto_dia_usd)} hoje"
    return SaudeServico("Casador (IA)", "ok", f"{texto} · {automatico}", detalhe, "/logs?aba=ia")


def _usd(valor: Decimal) -> str:
    return f"US$ {valor:.2f}".replace(".", ",")


def _mensagens_hoje(s: Session, agora: datetime, zona: ZoneInfo) -> tuple[int, int]:
    inicio = _inicio_do_dia(agora, zona)
    enviadas = _contar(s, MensagemSaida, MensagemSaida.enviada_em >= inicio)
    falhas = _contar(s, MensagemSaida, MensagemSaida.status == StatusMensagem.FALHA, MensagemSaida.atualizado_em >= inicio)
    return enviadas, falhas


def _saude_whatsapp(s: Session, agora: datetime, cfg: Config) -> SaudeServico:
    situacao, ultimo = consultas_mensagens.estado_notificador(s, agora)
    resumo = consultas_mensagens.resumo(s, agora)
    enviadas, _ = _mensagens_hoje(s, agora, cfg.zona)
    detalhe = f"{enviadas} enviadas hoje · {resumo.falhas} com falha · {resumo.paradas} paradas"
    if situacao == "nunca":
        return SaudeServico("WhatsApp", "falha", "Notificador nunca rodou", detalhe, "/servicos")
    if situacao == "parado":
        texto = f"Notificador parado desde {_quando(ultimo, agora, cfg.zona)}"
        return SaudeServico("WhatsApp", "falha", texto, detalhe, "/servicos")
    if repo.obter_estado(s, agora, COLETOR_NOTIFICADOR).estado is not EstadoColetorTipo.ATIVO:
        return SaudeServico(
            "WhatsApp", "pausado", "Envio desligado; as mensagens ficam guardadas", detalhe, "/servicos"
        )
    segundos = max(0, int((agora - ultimo).total_seconds()))
    return SaudeServico("WhatsApp", "ok", f"Notificador vivo · último ciclo há {segundos} s", detalhe, "/mensagens")


def saude_servicos(s: Session, agora: datetime, config_efetiva: Config, chave_ia: bool) -> list[SaudeServico]:
    """Um item por serviço, na ordem LigaMagic, Amazon, Casador (IA), WhatsApp."""
    return [
        _saude_liga(s, agora, config_efetiva),
        _saude_amazon(s, agora, config_efetiva),
        _saude_casador(s, agora, config_efetiva, chave_ia),
        _saude_whatsapp(s, agora, config_efetiva),
    ]


def avisos(s: Session, agora: datetime, config_efetiva: Config, chave_ia: bool) -> list[Aviso]:
    """Um aviso por problema: serviço pausado ou parado, mensagens presas ou com falha, e a última
    coleta da LigaMagic ou o último ciclo da Amazon que terminou com falha."""
    lista = []
    for servico in saude_servicos(s, agora, config_efetiva, chave_ia):
        if servico.situacao not in PROBLEMAS:
            continue
        if servico.nome == "WhatsApp" and servico.situacao == "falha":
            situacao, ultimo = consultas_mensagens.estado_notificador(s, agora)
            texto = (
                "O notificador nunca rodou — veja Serviços."
                if situacao == "nunca"
                else f"O notificador está parado desde {_quando(ultimo, agora, config_efetiva.zona)} — veja Serviços."
            )
        else:
            texto = f"{servico.nome} — {servico.texto}."
        lista.append(Aviso("error", texto, "/servicos", "Ir para Serviços"))
    resumo = consultas_mensagens.resumo(s, agora)
    if resumo.aviso:
        lista.append(Aviso("warning", resumo.aviso, resumo.link_aviso, "Ir para Mensagens"))
    for nome, tipos, aba in (("da LigaMagic", TIPOS_LIGA, "liga"), ("da Amazon", (TipoColeta.AMAZON,), "amazon")):
        ultima = consultas.ultima_coleta_finalizada(s, tipos)
        if ultima is not None and ultima.status is StatusColeta.FALHA:
            o_que = "A última coleta" if aba == "liga" else "O último ciclo"
            texto = (
                f"{o_que} {nome} ({ultima.tipo.value}, {_quando(ultima.iniciada_em, agora, config_efetiva.zona)}) "
                f"terminou com falha."
            )
            if ultima.erro:
                texto += f" {ultima.erro}"
            lista.append(Aviso("warning", texto, f"/logs?aba={aba}", "Ver nos logs"))
    return lista


def numeros(s: Session, agora: datetime, config_efetiva: Config) -> Numeros:
    por_status = dict(
        s.execute(
            select(AnuncioAmazon.status_casamento, func.count())
            .where(AnuncioAmazon.produto_id.is_not(None))
            .group_by(AnuncioAmazon.status_casamento)
        ).all()
    )
    produtos_com_par = s.scalar(
        select(func.count(func.distinct(AnuncioAmazon.produto_id)))
        .join(ProdutoLiga, ProdutoLiga.id == AnuncioAmazon.produto_id)
        .where(AnuncioAmazon.status_casamento == StatusCasamento.CONFIRMADO, ProdutoLiga.ativo.is_(True))
    ) or 0
    esperando = s.scalar(
        select(func.count())
        .select_from(AvaliacaoIA)
        .join(
            AnuncioAmazon,
            and_(AnuncioAmazon.id == AvaliacaoIA.anuncio_id, AnuncioAmazon.produto_id == AvaliacaoIA.produto_id),
        )
        .where(
            AnuncioAmazon.status_casamento == StatusCasamento.PENDENTE,
            AvaliacaoIA.mesmo_produto.is_(True),
            AvaliacaoIA.aplicada_em.is_(None),
        )
    ) or 0
    cfg_ia = repo_ia.obter_config_ia(s, agora)
    inicio_dia = _inicio_do_dia(agora, config_efetiva.zona)
    return Numeros(
        confirmados=por_status.get(StatusCasamento.CONFIRMADO, 0),
        pendentes=por_status.get(StatusCasamento.PENDENTE, 0),
        ignorados=por_status.get(StatusCasamento.IGNORADO, 0),
        produtos_com_par=produtos_com_par,
        produtos_ativos=_contar(s, ProdutoLiga, ProdutoLiga.ativo.is_(True)),
        produtos_total=_contar(s, ProdutoLiga),
        avaliados=_contar(s, AvaliacaoIA),
        pelo_automatico=_contar(s, AvaliacaoIA, AvaliacaoIA.aplicada_em.is_not(None)),
        esperando_voce=esperando,
        automatico=cfg_ia.automatico,
        confianca_confirmar=cfg_ia.confianca_confirmar,
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
    inicio = _inicio_do_dia(agora, zona)
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

    enviadas, falhas = _mensagens_hoje(s, agora, zona)
    situacao_msgs = "falha" if falhas else ("ok" if enviadas else "nenhum")
    return [
        Atividade("Coleta da LigaMagic", liga, _pior([c.status for c in ultimas])),
        Atividade("Buscas na Amazon", f"{len(ciclos)} ciclos · {lidos} preços", situacao_amazon),
        Atividade("Chamadas da IA", f"{chamadas} · {erros} com erro", situacao_ia),
        Atividade("Mensagens do WhatsApp", f"{enviadas} enviadas · {falhas} falhas", situacao_msgs),
    ]
