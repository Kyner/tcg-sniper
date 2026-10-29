"""Validação da aba IA de Configurações, com os limites do banco."""

import re
from collections.abc import Mapping
from decimal import Decimal

from tcg_sniper.db.models import ESFORCOS_IA, LIMITES_CONFIG_IA, ConfigIA

DINHEIRO_RE = re.compile(r"[0-9]{1,6}(\.[0-9]{1,2})?")
PRECO_RE = re.compile(r"[0-9]{1,6}(\.[0-9]{1,4})?")
SIM_NAO = (("sim", "Sim"), ("não", "Não"))

CAMPOS_IA = (
    "ligado",
    "modelo",
    "esforco",
    "preco_entrada_milhao_usd",
    "preco_saida_milhao_usd",
    "teto_dia_usd",
    "teto_mes_usd",
    "max_chamadas_dia",
    "intervalo_min",
    "lote",
    "automatico",
    "confianca_confirmar",
    "confianca_ignorar",
)
ROTULOS_IA = {
    "ligado": "IA ligada",
    "modelo": "Modelo da OpenAI",
    "esforco": "Esforço de raciocínio",
    "preco_entrada_milhao_usd": "Preço de entrada (US$ por milhão de tokens)",
    "preco_saida_milhao_usd": "Preço de saída (US$ por milhão de tokens)",
    "teto_dia_usd": "Teto de gasto por dia (US$)",
    "teto_mes_usd": "Teto de gasto por mês (US$)",
    "max_chamadas_dia": "Máximo de chamadas por dia",
    "intervalo_min": "Intervalo entre rodadas (min)",
    "lote": "Anúncios por rodada",
    "automatico": "Automático",
    "confianca_confirmar": "Confiança mínima para confirmar sozinho (%)",
    "confianca_ignorar": "Confiança mínima para ignorar sozinho (%)",
}
EXPLICACOES_IA = {
    "ligado": "Desligada, o casador não chama a OpenAI. Ligada, avalia os anúncios pendentes e mostra a sugestão em Casamentos.",
    "modelo": "Nome do modelo na API da OpenAI, como gpt-5 ou gpt-5-mini. Confira os preços abaixo ao trocar.",
    "esforco": "Mais esforço tende a acertar mais e custa mais tokens de saída.",
    "preco_entrada_milhao_usd": "Copie da página de preços da OpenAI para o modelo escolhido. Usado para calcular o gasto.",
    "preco_saida_milhao_usd": "Copie da página de preços da OpenAI. Inclui os tokens de raciocínio.",
    "teto_dia_usd": "Atingido, o casador para até o dia seguinte (fuso da seção Geral) e avisa no WhatsApp.",
    "teto_mes_usd": "Atingido, o casador para até o mês seguinte e avisa no WhatsApp.",
    "max_chamadas_dia": "Trava extra contra laço ou erro, independente do preço.",
    "intervalo_min": "De quanto em quanto tempo o casador procura anúncios novos ou mudados.",
    "lote": "Quantos anúncios no máximo por rodada.",
    "automatico": "Ligado, a IA confirma ou ignora sozinha quando a confiança passa dos limites abaixo. Decisões suas nunca são trocadas.",
    "confianca_confirmar": "A IA diz que é o mesmo produto com pelo menos essa confiança: confirma (com o automático ligado).",
    "confianca_ignorar": "A IA diz que é outro produto com pelo menos essa confiança: ignora (com o automático ligado).",
}
OPCOES_IA: dict[str, tuple[tuple[str, str], ...]] = {
    "ligado": SIM_NAO,
    "automatico": SIM_NAO,
    "esforco": tuple((e, e) for e in ESFORCOS_IA),
}


def texto_ia(cfg: ConfigIA, campo: str) -> str:
    """Valor salvo como aparece no formulário."""
    valor = getattr(cfg, campo)
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    if isinstance(valor, Decimal):
        return format(valor.normalize(), "f").replace(".", ",")
    return str(valor)


def validar_ia(campos: Mapping[str, str]) -> tuple[dict[str, object], dict[str, str]]:
    valores: dict[str, object] = {}
    erros: dict[str, str] = {}

    for campo in ("ligado", "automatico"):
        texto = (campos.get(campo) or "").strip()
        if texto in ("sim", "não"):
            valores[campo] = texto == "sim"
        else:
            erros[campo] = "Escolha Sim ou Não."

    modelo = (campos.get("modelo") or "").strip()
    if not modelo or len(modelo) > 100 or any(c.isspace() for c in modelo):
        erros["modelo"] = "Informe o nome do modelo, sem espaços (ex.: gpt-5)."
    else:
        valores["modelo"] = modelo

    esforco = (campos.get("esforco") or "").strip()
    if esforco in ESFORCOS_IA:
        valores["esforco"] = esforco
    else:
        erros["esforco"] = "Escolha um dos valores da lista."

    for campo, padrao, exemplo in (
        ("preco_entrada_milhao_usd", PRECO_RE, "1,25"),
        ("preco_saida_milhao_usd", PRECO_RE, "10"),
        ("teto_dia_usd", DINHEIRO_RE, "2"),
        ("teto_mes_usd", DINHEIRO_RE, "20"),
    ):
        texto = (campos.get(campo) or "").strip().replace(",", ".")
        if padrao.fullmatch(texto):
            valores[campo] = Decimal(texto)
        else:
            erros[campo] = f"Informe um valor em dólar, zero ou mais (ex.: {exemplo})."

    for campo, (minimo, maximo) in LIMITES_CONFIG_IA.items():
        texto = (campos.get(campo) or "").strip()
        if not (texto.isascii() and texto.isdecimal()) or len(texto) > 6:
            erros[campo] = f"Informe um número inteiro entre {minimo} e {maximo}."
        elif not minimo <= int(texto) <= maximo:
            erros[campo] = f"O valor deve ficar entre {minimo} e {maximo}."
        else:
            valores[campo] = int(texto)
    return valores, erros
