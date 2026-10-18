from datetime import UTC, datetime, timedelta

from tcg_sniper.db import repositorio_manutencao as repo_man
from tcg_sniper.db.models import ExecucaoManutencao, StatusManutencao

AGORA = datetime(2026, 10, 18, 7, 0, tzinfo=UTC)


def _finalizada(s, inicio, status, **campos):
    execucao = repo_man.iniciar(s, inicio)
    valores = {"arquivo": None, "tamanho_bytes": None, "enviado_r2": False, "apagados": None, "erro": None, **campos}
    repo_man.finalizar(s, execucao.id, inicio + timedelta(minutes=1), status, **valores)
    return s.get(ExecucaoManutencao, execucao.id, populate_existing=True)


def test_iniciar_e_finalizar_gravam_tudo(s):
    e = _finalizada(
        s, AGORA, StatusManutencao.OK, arquivo="tcg-diario-2026-10-18.dump", tamanho_bytes=5_000_000_000,
        enviado_r2=True, apagados={"coleta": 2}, erro=None,
    )
    assert (e.status, e.arquivo, e.tamanho_bytes, e.enviado_r2, e.apagados) == (
        StatusManutencao.OK, "tcg-diario-2026-10-18.dump", 5_000_000_000, True, {"coleta": 2}
    )
    assert e.fim == AGORA + timedelta(minutes=1)


def test_marcar_interrompidas_fecha_so_as_rodando(s):
    rodando = repo_man.iniciar(s, AGORA)
    ok = _finalizada(s, AGORA - timedelta(days=1), StatusManutencao.OK)
    assert repo_man.marcar_interrompidas(s, AGORA + timedelta(hours=1)) == 1
    s.expire_all()
    assert s.get(ExecucaoManutencao, rodando.id).status is StatusManutencao.INTERROMPIDA
    assert s.get(ExecucaoManutencao, rodando.id).erro == repo_man.MOTIVO_INTERROMPIDA
    assert s.get(ExecucaoManutencao, ok.id).status is StatusManutencao.OK


def test_execucoes_desde_conta_erro_mas_nao_interrompida(s):
    desde = AGORA - timedelta(hours=3)
    _finalizada(s, AGORA - timedelta(days=1), StatusManutencao.OK)
    assert repo_man.execucoes_desde(s, desde) == []
    _finalizada(s, AGORA, StatusManutencao.INTERROMPIDA)
    assert repo_man.execucoes_desde(s, desde) == []
    erro = _finalizada(s, AGORA, StatusManutencao.ERRO, erro="falhou")
    assert [e.id for e in repo_man.execucoes_desde(s, desde)] == [erro.id]


def test_ultima_ok_aceita_so_local_e_ignora_erro(s):
    assert repo_man.ultima_ok(s) is None
    so_local = _finalizada(s, AGORA - timedelta(days=2), StatusManutencao.SO_LOCAL)
    _finalizada(s, AGORA - timedelta(days=1), StatusManutencao.ERRO, erro="x")
    assert repo_man.ultima_ok(s).id == so_local.id
    assert repo_man.ultima(s).status is StatusManutencao.ERRO


def test_registrar_ciclo(s):
    assert repo_man.ultimo_ciclo(s) is None
    repo_man.registrar_ciclo(s, AGORA)
    assert repo_man.ultimo_ciclo(s) == AGORA
