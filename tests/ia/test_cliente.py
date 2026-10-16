import json
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fakes import T0, TransporteFake
from sqlalchemy import select

from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import ChamadaIA
from tcg_sniper.ia.cliente import custo, perguntar
from tcg_sniper.ia.modelos import Bruta, ChaveInvalida, ErroIA, SemOrcamento

SP = ZoneInfo("America/Sao_Paulo")
FORMATO = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}


def chamar(sessoes, transporte, **extra):
    return perguntar(
        sessoes, transporte, finalidade="casamento", instrucoes="inst", texto="txt", imagens=["AAA"],
        nome_formato="teste", formato=FORMATO, zona=SP, relogio=lambda: T0, **extra,
    )


def chamadas(sessoes):
    with sessoes() as s:
        return list(s.scalars(select(ChamadaIA).order_by(ChamadaIA.id)))


def test_custo(s):
    cfg = repo_ia.obter_config_ia(s)  # 1.25 / 10.00 por milhão
    assert custo(1000, 100, cfg) == Decimal("0.002250")


def test_sucesso_registra_e_devolve(sessoes):
    t = TransporteFake([Bruta(json.dumps({"ok": True}), 1000, 100)])
    r = chamar(sessoes, t)
    assert r.dados == {"ok": True} and r.custo_usd == Decimal("0.002250") and r.modelo == "gpt-5"
    pedido = t.pedidos[0]
    assert (pedido.modelo, pedido.esforco, pedido.imagens, pedido.formato) == ("gpt-5", "low", ("AAA",), FORMATO)
    [c] = chamadas(sessoes)
    assert c.ok and c.id == r.chamada_id and c.finalidade == "casamento" and c.tokens_entrada == 1000


def test_modelo_sobrescrito(sessoes):
    t = TransporteFake([Bruta('{"ok": true}', 10, 1)])
    assert chamar(sessoes, t, modelo="gpt-5-mini").modelo == "gpt-5-mini"
    assert t.pedidos[0].modelo == "gpt-5-mini"


def test_json_invalido_vira_erro_registrado(sessoes):
    t = TransporteFake([Bruta("não é json", 50, 5)])
    with pytest.raises(ErroIA):
        chamar(sessoes, t)
    [c] = chamadas(sessoes)
    assert not c.ok and c.tokens_entrada == 50 and c.custo_usd > 0 and "JSON" in c.erro


@pytest.mark.parametrize("erro", [ChaveInvalida("chave recusada pela OpenAI (401)"), ErroIA("OpenAI 500")])
def test_erro_do_transporte_registrado_e_relancado(sessoes, erro):
    t = TransporteFake([erro])
    with pytest.raises(type(erro)):
        chamar(sessoes, t)
    [c] = chamadas(sessoes)
    assert not c.ok and c.erro == str(erro) and c.custo_usd == 0


def test_sem_orcamento_nao_chama(sessoes):
    with sessoes() as s, s.begin():
        repo_ia.salvar_config_ia(s, {"max_chamadas_dia": 0}, T0)
    t = TransporteFake([])
    with pytest.raises(SemOrcamento):
        chamar(sessoes, t)
    assert t.pedidos == [] and chamadas(sessoes) == []


def test_erro_inesperado_do_transporte_vira_erro_ia_registrado_sem_a_mensagem(sessoes):
    t = TransporteFake([RuntimeError("falhou com sk-segredo no texto")])
    with pytest.raises(ErroIA) as erro:
        chamar(sessoes, t)
    assert "RuntimeError" in str(erro.value) and "sk-segredo" not in str(erro.value)
    assert erro.value.__cause__ is None and erro.value.__suppress_context__
    [c] = chamadas(sessoes)
    assert not c.ok and c.erro == "RuntimeError" and c.custo_usd == 0


def test_precos_sobrescritos_valem_no_custo_e_no_registro(sessoes):
    t = TransporteFake([Bruta('{"ok": true}', 1000, 100)])
    r = chamar(sessoes, t, preco_entrada=Decimal("0.25"), preco_saida=Decimal(2))
    assert r.custo_usd == Decimal("0.000450")
    [c] = chamadas(sessoes)
    assert c.custo_usd == Decimal("0.000450")


def test_so_um_preco_sobrescrito(sessoes):
    t = TransporteFake([Bruta('{"ok": true}', 1000, 100)])
    # entrada 0,25 informada; saída 10,00 de Configurações
    assert chamar(sessoes, t, preco_entrada=Decimal("0.25")).custo_usd == Decimal("0.001250")
