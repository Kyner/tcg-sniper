from datetime import UTC, datetime

from sqlalchemy import func, select

from tcg_sniper.db import repositorio_acao_gestao as repo
from tcg_sniper.db import repositorio_acesso as repo_acesso
from tcg_sniper.db.models import AcaoGestao, Papel, TipoAcaoGestao

T = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


def _total(s) -> int:
    return s.scalar(select(func.count()).select_from(AcaoGestao))


def test_registrar_grava_na_transacao_de_quem_chama(sessoes):
    with sessoes() as s:
        s.begin()
        acao = repo.registrar(s, None, TipoAcaoGestao.CATALOGO_LOTE, {"qtd": 3}, T)
        assert acao.id is not None and acao.detalhe == {"qtd": 3} and acao.tipo == TipoAcaoGestao.CATALOGO_LOTE
        s.rollback()
        assert _total(s) == 0


def test_usuario_apagado_deixa_acao_sem_usuario(s):
    u = repo_acesso.criar_usuario(s, "Op", "+5511900000009", Papel.OPERADOR, T)
    acao = repo.registrar(s, u.id, TipoAcaoGestao.SERVICO, {"servico": "liga"}, T)
    s.flush()
    assert acao.usuario_id == u.id
    s.delete(u)
    s.flush()
    s.refresh(acao)
    assert acao.usuario_id is None
