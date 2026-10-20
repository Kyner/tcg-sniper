"""Validação do formulário de configuração da Amazon (admin), com os limites do banco."""

import re
from collections.abc import Mapping
from datetime import datetime, time

from sqlalchemy import update
from sqlalchemy.orm import Session

from tcg_sniper.db.models import LIMITES_CONFIG_AMAZON, ConfigAmazon

HORA_RE = re.compile(r"[0-9]{2}:[0-9]{2}")

CAMPOS = (
    "url_busca",
    "janela_inicio",
    "janela_fim",
    "pausa_min_s",
    "pausa_max_s",
    "resultados_por_busca",
    "intervalo_busca_min",
    "max_buscas_hora",
    "limite_falha_pct",
    "desconto_min_pct",
    "realerta_queda_pct",
    "liga_preco_max_idade_h",
    "vendedor_min_positivas_pct",
    "vendedor_min_avaliacoes",
    "vendedor_reavaliar_dias",
    "monitor_intervalo_min",
    "monitor_janela_inicio",
    "monitor_janela_fim",
    "monitor_max_paginas_hora",
    "margem_candidata_pp",
    "checkout_validade_h",
    "descoberta_casados_dias",
    "carencia_encerramento_min",
)

ROTULOS = {
    "url_busca": "URL da busca",
    "janela_inicio": "Início da busca",
    "janela_fim": "Fim da busca",
    "pausa_min_s": "Pausa mínima (s)",
    "pausa_max_s": "Pausa máxima (s)",
    "resultados_por_busca": "Resultados por busca",
    "intervalo_busca_min": "Intervalo entre buscas do mesmo produto (min)",
    "max_buscas_hora": "Máximo de buscas por hora (busca)",
    "limite_falha_pct": "Limite de falhas por ciclo (%)",
    "desconto_min_pct": "Desconto mínimo sobre a Liga (%)",
    "realerta_queda_pct": "Queda para novo aviso (%)",
    "liga_preco_max_idade_h": "Idade máxima do preço da Liga (h)",
    "vendedor_min_positivas_pct": "Lojista FBA: mínimo de positivas (%)",
    "vendedor_min_avaliacoes": "Lojista FBA: mínimo de avaliações",
    "vendedor_reavaliar_dias": "Reavaliar lojista a cada (dias)",
    "monitor_intervalo_min": "Ler cada anúncio confirmado a cada (min)",
    "monitor_janela_inicio": "Início do monitor",
    "monitor_janela_fim": "Fim do monitor",
    "monitor_max_paginas_hora": "Máximo de páginas por hora (monitor e checkout)",
    "margem_candidata_pp": "Conferir no checkout a partir de (pontos abaixo do desconto mínimo)",
    "checkout_validade_h": "Conferência de checkout vale por (h)",
    "descoberta_casados_dias": "Buscar de novo produtos já casados a cada (dias)",
    "carencia_encerramento_min": "Carência antes de encerrar uma oportunidade (min)",
}

EXPLICACOES = {
    "url_busca": "Modelo da busca na Amazon; {termo} é trocado pelo nome do produto da Liga.",
    "janela_inicio": "Hora (HH:MM) em que a busca de anúncios novos começa, com variação de até 15 minutos.",
    "janela_fim": "Hora (HH:MM) em que a busca de anúncios novos para, com variação de até 15 minutos.",
    "pausa_min_s": "Pausa mínima, em segundos, antes de cada página da Amazon (vale para os dois navegadores).",
    "pausa_max_s": "Pausa máxima, em segundos. Pausas menores aumentam a chance de CAPTCHA.",
    "resultados_por_busca": "Quantos resultados ler em cada busca (os primeiros da página).",
    "intervalo_busca_min": (
        "Minutos entre duas buscas do mesmo produto. Metade disso se ele teve oferta boa nas "
        "últimas 24 h; o dobro se não tem há 7 dias."
    ),
    "max_buscas_hora": (
        "Teto de buscas por hora do navegador da busca (sem login). A Amazon vê a soma deste teto com o do "
        "monitor, no mesmo endereço."
    ),
    "limite_falha_pct": "Percentual de buscas com falha num ciclo a partir do qual o grupo admin é avisado.",
    "desconto_min_pct": 'Desconto mínimo sobre o "À partir de" da Liga para avisar o grupo de oportunidades.',
    "realerta_queda_pct": "Queda extra de preço, em %, que gera um novo aviso da mesma oferta.",
    "liga_preco_max_idade_h": "Idade máxima, em horas, do preço da Liga usado como referência.",
    "vendedor_min_positivas_pct": "Percentual mínimo de avaliações positivas de um lojista com envio pela Amazon.",
    "vendedor_min_avaliacoes": "Número mínimo de avaliações de um lojista com envio pela Amazon.",
    "vendedor_reavaliar_dias": "De quantos em quantos dias reler o perfil de um lojista.",
    "monitor_intervalo_min": "De quantos em quantos minutos ler a lista de ofertas de cada anúncio confirmado.",
    "monitor_janela_inicio": "Hora (HH:MM) em que o monitor começa, com variação de até 15 minutos.",
    "monitor_janela_fim": "Hora (HH:MM) em que o monitor para, com variação de até 15 minutos.",
    "monitor_max_paginas_hora": (
        "Teto de páginas por hora do navegador logado, somando monitor, conferência de checkout e retirada de "
        "itens do carrinho. A Amazon vê a soma deste teto com o da busca, no mesmo endereço."
    ),
    "margem_candidata_pp": (
        "Uma oferta com desconto anunciado de pelo menos (desconto mínimo − este valor) vai ao checkout "
        "para conferir impostos e frete."
    ),
    "checkout_validade_h": "Por quantas horas o total conferido vale para a mesma oferta (vendedor e preço).",
    "descoberta_casados_dias": "Produto que já tem anúncio confirmado só volta à busca depois deste número de dias.",
    "carencia_encerramento_min": (
        "Quanto tempo uma oportunidade que deixou de ser elegível fica em risco antes de ser encerrada. "
        "0 encerra na hora."
    ),
}


def ler_hora(texto: str) -> time | None:
    if not HORA_RE.fullmatch(texto):
        return None
    try:
        return time.fromisoformat(texto)
    except ValueError:
        return None


def validar_config(campos: Mapping[str, str]) -> tuple[dict[str, object], dict[str, str]]:
    valores: dict[str, object] = {}
    erros: dict[str, str] = {}

    url = (campos.get("url_busca") or "").strip()
    if not url.startswith("https://"):
        erros["url_busca"] = "Use uma URL que comece com https://."
    elif "{termo}" not in url:
        erros["url_busca"] = "A URL precisa conter {termo}."
    else:
        valores["url_busca"] = url

    for campo in ("janela_inicio", "janela_fim", "monitor_janela_inicio", "monitor_janela_fim"):
        hora = ler_hora((campos.get(campo) or "").strip())
        if hora is None:
            erros[campo] = "Use o formato HH:MM, por exemplo 08:00."
        else:
            valores[campo] = hora

    for campo, (minimo, maximo) in LIMITES_CONFIG_AMAZON.items():
        texto = (campos.get(campo) or "").strip()
        if not (texto.isascii() and texto.isdecimal()) or len(texto) > 6:
            erros[campo] = f"Informe um número inteiro entre {minimo} e {maximo}."
            continue
        numero = int(texto)
        if not minimo <= numero <= maximo:
            erros[campo] = f"O valor deve ficar entre {minimo} e {maximo}."
            continue
        valores[campo] = numero

    if "pausa_min_s" in valores and "pausa_max_s" in valores and valores["pausa_min_s"] > valores["pausa_max_s"]:
        erros["pausa_min_s"] = "A pausa mínima não pode ser maior que a máxima."
    if "janela_inicio" in valores and "janela_fim" in valores and valores["janela_inicio"] >= valores["janela_fim"]:
        erros["janela_fim"] = "O fim da janela precisa ser depois do início."
    if (
        "monitor_janela_inicio" in valores
        and "monitor_janela_fim" in valores
        and valores["monitor_janela_inicio"] >= valores["monitor_janela_fim"]
    ):
        erros["monitor_janela_fim"] = "O fim da janela do monitor precisa ser depois do início."
    return valores, erros


def aplicar_config(s: Session, valores: Mapping[str, object], agora: datetime) -> None:
    s.execute(update(ConfigAmazon).where(ConfigAmazon.id == 1).values(**valores, atualizado_em=agora))
    s.flush()
