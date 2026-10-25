"""Limites de pedir código e de entrar sob concorrência: duas transações ao mesmo tempo não passam juntas pela
última vaga (a contagem e o registro ficam atrás de um `pg_advisory_xact_lock`)."""

import threading
import time

import pytest
from fakes_api import SEGREDO_TESTE, T0
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from tcg_sniper.api import acesso
from tcg_sniper.api.segredos import hash_segredo
from tcg_sniper.db.models import PedidoCodigo

NUMERO_A = "+5511900000071"
NUMERO_B = "+5511900000072"


def _esperar_bloqueio(engine, tarefa: threading.Thread) -> None:
    """Espera a outra transação parar no advisory lock (ou terminar, quando não há trava)."""
    limite = time.monotonic() + 5
    while tarefa.is_alive() and time.monotonic() < limite:
        with engine.connect() as c:
            if c.scalar(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted")):
                return
        time.sleep(0.01)


def _corrida(engine, primeira, segunda):
    """`primeira` roda numa transação que só confirma depois que a `segunda` (outra conexão, numa thread) começou;
    a segunda é desfeita no fim. Devolve o resultado da segunda."""
    resultado = {}
    with Session(engine) as s1:
        primeira(s1)

        def rodar():
            with Session(engine) as s2:
                resultado["valor"] = segunda(s2)
                s2.rollback()

        tarefa = threading.Thread(target=rodar)
        tarefa.start()
        _esperar_bloqueio(engine, tarefa)
        s1.commit()
        tarefa.join(10)
    return resultado["valor"]


@pytest.fixture
def limpar(engine):
    yield
    hashes = [hash_segredo(SEGREDO_TESTE, n) for n in (NUMERO_A, NUMERO_B)]
    with engine.begin() as c:
        c.execute(delete(PedidoCodigo).where(PedidoCodigo.numero_hash.in_(hashes)))


def test_dois_pedidos_ao_mesmo_tempo_nao_levam_a_ultima_vaga_do_numero(engine, limpar, monkeypatch):
    monkeypatch.setattr(acesso, "LIMITE_POR_NUMERO", 1)
    resultado = _corrida(
        engine,
        lambda s: acesso.pedir_codigo(s, NUMERO_A, T0, SEGREDO_TESTE),
        lambda s: acesso.pedir_codigo(s, NUMERO_A, T0, SEGREDO_TESTE),
    )
    assert resultado is acesso.ResultadoPedido.LIMITE_NUMERO


def test_dois_numeros_ao_mesmo_tempo_sao_aceitos(engine, limpar):
    """Sem limite total, pedidos de números diferentes não disputam vaga."""
    resultado = _corrida(
        engine,
        lambda s: acesso.pedir_codigo(s, NUMERO_A, T0, SEGREDO_TESTE),
        lambda s: acesso.pedir_codigo(s, NUMERO_B, T0, SEGREDO_TESTE),
    )
    assert resultado is acesso.ResultadoPedido.ACEITO


def test_duas_entradas_ao_mesmo_tempo_nao_levam_a_ultima_vaga(engine, limpar, monkeypatch):
    monkeypatch.setattr(acesso, "LIMITE_ENTRADAS", 1)
    resultado = _corrida(
        engine,
        lambda s: acesso.registrar_entrada(s, NUMERO_A, T0, SEGREDO_TESTE),
        lambda s: acesso.registrar_entrada(s, NUMERO_A, T0, SEGREDO_TESTE),
    )
    assert resultado is False
