"""Validação das seções Geral e LigaMagic da tela de Configurações, com os limites do banco."""

import functools
import re
import zoneinfo
from collections.abc import Mapping

from tcg_sniper.coletor_amazon.config import ler_hora
from tcg_sniper.db.models import LIMITES_CONFIG_LIGA

PAUSA_RE = re.compile(r"[0-9]{1,3}(\.[0-9]{1,2})?")



@functools.cache
def _fusos() -> frozenset[str]:
    """Nomes de fuso aceitos. `ZoneInfo("America")` estoura OSError no Linux e "localtime"/"Factory"
    passam sem serem fusos de verdade, então a validação é por pertencimento à lista."""
    return frozenset(zoneinfo.available_timezones() - {"localtime", "Factory", "posixrules"})


CAMPOS_GERAL = (
    "host_publico",
    "fuso",
    "evolution_instancia",
    "whatsapp_grupo_admin",
    "whatsapp_grupo_oportunidades",
    "validade_oportunidade_h",
)
ROTULOS_GERAL = {
    "host_publico": "IP ou nome deste PC na rede",
    "fuso": "Fuso horário",
    "evolution_instancia": "Instância da Evolution API",
    "whatsapp_grupo_admin": "Grupo de WhatsApp do admin",
    "whatsapp_grupo_oportunidades": "Grupo de WhatsApp de oportunidades",
    "validade_oportunidade_h": "Validade das oportunidades (h)",
}
EXPLICACOES_GERAL = {
    "host_publico": "Usado nos links do admin para o noVNC. Com o noVNC só neste PC (padrão), use 127.0.0.1; o IP da rede só serve se VNC_ESCUTA no .env abrir o noVNC para a rede de casa. As mensagens do WhatsApp nunca levam este endereço.",
    "fuso": "Usado no horário da coleta e nas datas do admin e das mensagens. Ex.: America/Sao_Paulo.",
    "evolution_instancia": "Nome da instância criada na Evolution. Vazio: as mensagens ficam pendentes em Mensagens.",
    "whatsapp_grupo_admin": "ID do grupo (120363...@g.us) que recebe desafios, falhas e resumos. Vazio: as mensagens ficam pendentes em Mensagens.",
    "whatsapp_grupo_oportunidades": "ID do grupo (120363...@g.us) que recebe as ofertas com desconto. Vazio: as mensagens ficam pendentes em Mensagens.",
    "validade_oportunidade_h": "Oportunidade que não saiu em até tantas horas, por o WhatsApp estar fora, é descartada como expirada.",
}

CAMPOS_LIGA = (
    "coleta_hora",
    "coleta_jitter_min",
    "pausa_min_s",
    "pausa_max_s",
    "limite_falha_pct",
    "categorias",
    "url_listagem",
    "max_cliques",
    "produtos_novos_dia",
    "esfriar_desafio_min",
)
ROTULOS_LIGA = {
    "coleta_hora": "Horário da coleta diária",
    "coleta_jitter_min": "Variação do horário (min)",
    "pausa_min_s": "Pausa mínima (s)",
    "pausa_max_s": "Pausa máxima (s)",
    "limite_falha_pct": "Limite de falhas por coleta (%)",
    "categorias": "Categorias",
    "url_listagem": "URL da listagem",
    "max_cliques": "Máximo de cliques em \"Exibir mais\"",
    "produtos_novos_dia": "Produtos novos por dia",
    "esfriar_desafio_min": "Esfriar após desafio (min)",
}
EXPLICACOES_LIGA = {
    "coleta_hora": "Hora (HH:MM), no fuso da seção Geral.",
    "coleta_jitter_min": "Minutos sorteados para mais ou para menos. Com 10:00 e 30, começa entre 09:30 e 10:30.",
    "pausa_min_s": "Pausa mínima, em segundos, entre páginas e antes de cada clique em \"Exibir mais\".",
    "pausa_max_s": "Pausa máxima, em segundos. Pausas menores aumentam a chance de desafio do Cloudflare.",
    "limite_falha_pct": "Percentual de falhas a partir do qual a coleta vira \"falha\" e o grupo admin é avisado.",
    "categorias": "IDs das categorias de selados, separados por vírgula. Tire daqui uma categoria que falha todo dia.",
    "url_listagem": "Modelo da URL de uma categoria; {categ} é trocado pelo ID.",
    "max_cliques": "Cada clique mostra mais 40 produtos. Atingir o limite conta como falha da categoria.",
    "produtos_novos_dia": "Produtos ativos ainda sem resumo de preço abertos por dia, os mais antigos primeiro. 0: nenhum.",
    "esfriar_desafio_min": (
        "Depois de um desafio resolvido, a coleta espera esses minutos e segue com pausas em dobro por 24 h depois do desafio."
    ),
}


def validar_geral(campos: Mapping[str, str]) -> tuple[dict[str, object], dict[str, str]]:
    valores: dict[str, object] = {}
    erros: dict[str, str] = {}

    host = (campos.get("host_publico") or "").strip()
    if not host or any(c.isspace() for c in host):
        erros["host_publico"] = "Informe o IP ou o nome deste PC, sem espaços."
    elif "/" in host or ":" in host:
        erros["host_publico"] = "Informe só o IP ou o nome deste PC, sem http:// nem porta."
    else:
        valores["host_publico"] = host

    fuso = (campos.get("fuso") or "").strip()
    if fuso in _fusos():
        valores["fuso"] = fuso
    else:
        erros["fuso"] = "Fuso desconhecido. Use o formato America/Sao_Paulo."

    valores["evolution_instancia"] = (campos.get("evolution_instancia") or "").strip() or None

    for campo in ("whatsapp_grupo_admin", "whatsapp_grupo_oportunidades"):
        grupo = (campos.get(campo) or "").strip()
        if not grupo:
            valores[campo] = None
        elif not grupo.endswith("@g.us") or len(grupo) <= len("@g.us"):
            erros[campo] = "Use o ID do grupo, terminado em @g.us (passo 5 do README)."
        else:
            valores[campo] = grupo

    texto = (campos.get("validade_oportunidade_h") or "").strip()
    if not (texto.isascii() and texto.isdecimal()) or len(texto) > 3 or not 1 <= int(texto) <= 48:
        erros["validade_oportunidade_h"] = "Informe um número inteiro de horas entre 1 e 48."
    else:
        valores["validade_oportunidade_h"] = int(texto)
    return valores, erros


def validar_liga(campos: Mapping[str, str]) -> tuple[dict[str, object], dict[str, str]]:
    valores: dict[str, object] = {}
    erros: dict[str, str] = {}

    hora = ler_hora((campos.get("coleta_hora") or "").strip())
    if hora is None:
        erros["coleta_hora"] = "Use o formato HH:MM, por exemplo 10:00."
    else:
        valores["coleta_hora"] = hora

    for campo in ("coleta_jitter_min", "limite_falha_pct", "max_cliques", "produtos_novos_dia", "esfriar_desafio_min"):
        minimo, maximo = LIMITES_CONFIG_LIGA[campo]
        texto = (campos.get(campo) or "").strip()
        if not (texto.isascii() and texto.isdecimal()) or len(texto) > 6:
            erros[campo] = f"Informe um número inteiro entre {minimo} e {maximo}."
        elif not minimo <= int(texto) <= maximo:
            erros[campo] = f"O valor deve ficar entre {minimo} e {maximo}."
        else:
            valores[campo] = int(texto)

    for campo in ("pausa_min_s", "pausa_max_s"):
        minimo, maximo = LIMITES_CONFIG_LIGA[campo]
        texto = (campos.get(campo) or "").strip().replace(",", ".")
        if not PAUSA_RE.fullmatch(texto):
            erros[campo] = f"Informe segundos entre {minimo} e {maximo} (ex.: 8 ou 8,5)."
        elif not minimo <= float(texto) <= maximo:
            erros[campo] = f"O valor deve ficar entre {minimo} e {maximo}."
        else:
            valores[campo] = float(texto)
    if "pausa_min_s" in valores and "pausa_max_s" in valores and valores["pausa_min_s"] > valores["pausa_max_s"]:
        erros["pausa_min_s"] = "A pausa mínima não pode ser maior que a máxima."

    ids = [parte.strip() for parte in (campos.get("categorias") or "").split(",") if parte.strip()]
    if not ids or not all(i.isascii() and i.isdecimal() for i in ids):
        erros["categorias"] = "Informe IDs numéricos separados por vírgula, por exemplo 10,11,12."
    else:
        valores["categorias"] = ",".join(dict.fromkeys(ids))

    url = (campos.get("url_listagem") or "").strip()
    if not url.startswith(("http://", "https://")):
        erros["url_listagem"] = "Use uma URL que comece com http:// ou https://."
    elif "{categ}" not in url:
        erros["url_listagem"] = "A URL precisa conter {categ}."
    else:
        valores["url_listagem"] = url
    return valores, erros


# Nomes das categorias da Liga por ID (vazio por ora; ID sem nome aparece como "categoria N").
NOMES_CATEGORIAS: dict[int, str] = {}
