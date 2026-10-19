import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fakes import AvisadorFake
from sqlalchemy import select

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, TipoAviso
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db import repositorio_manutencao as repo_man
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import (
    COLETOR_MANUTENCAO,
    ChamadaIA,
    ExecucaoManutencao,
    MensagemSaida,
    StatusManutencao,
    StatusMensagem,
)
from tcg_sniper.manutencao.backup import SaidaComando
from tcg_sniper.manutencao.servico import ServicoManutencao
from tcg_sniper.notificador.base import Destino

# Fuso padrão America/Sao_Paulo (UTC-3): 07:00 UTC = 04:00 local.
QUARTA_4H = datetime(2026, 10, 14, 7, 0, tzinfo=UTC)
DOMINGO_4H = datetime(2026, 10, 18, 7, 0, tzinfo=UTC)
SEGREDO = "segredo-falso-r2-0123456789"


class Relogio:
    def __init__(self, agora):
        self.agora = agora

    def __call__(self):
        return self.agora


class ExecutorFake:
    def __init__(self, dump_codigo=0, lista="; Archive\n1; SCHEMA public\n"):
        self.dump_codigo, self.lista = dump_codigo, lista
        self.dumps = 0

    def __call__(self, args, env, timeout=None):
        if args[0] == "pg_dump":
            self.dumps += 1
            with open(args[args.index("-f") + 1], "wb") as arquivo:
                arquivo.write(b"PGDMP-fake-123")
            return SaidaComando(self.dump_codigo, "", "pg_dump: error: connection to server failed")
        return SaidaComando(0, self.lista, "")


class EnviadorFake:
    def __init__(self, erro: Exception | None = None):
        self.erro = erro
        self.enviados: list[str] = []
        self.segredos = (SEGREDO, "ID-FALSO-R2")

    def enviar(self, caminho, chave):
        if self.erro is not None:
            raise self.erro
        assert caminho.exists()
        self.enviados.append(chave)


@pytest.fixture
def pasta(config):
    return config.pasta_backups


def servico(sessoes, config, agora, enviador=None, executar=None, avisador=None):
    return ServicoManutencao(
        sessoes, config, avisador or AvisadorFake(), enviador, executar or ExecutorFake(),
        relogio=Relogio(agora), dormir=lambda _: None,
    )


def execucoes(sessoes):
    with sessoes() as s:
        return list(s.scalars(select(ExecucaoManutencao).order_by(ExecucaoManutencao.id)))


def gravar_execucao(sessoes, inicio, status):
    with sessoes() as s, s.begin():
        e = repo_man.iniciar(s, inicio)
        if status is not StatusManutencao.RODANDO:
            repo_man.finalizar(
                s, e.id, inicio + timedelta(minutes=1), status, arquivo=None, tamanho_bytes=None, enviado_r2=False,
                apagados=None, erro=None,
            )


# --- agenda ------------------------------------------------------------------------------------


def test_roda_as_4h_locais_uma_vez_por_dia(sessoes, config):
    gravar_execucao(sessoes, QUARTA_4H - timedelta(days=1), StatusManutencao.OK)
    srv = servico(sessoes, config, QUARTA_4H - timedelta(minutes=1))
    srv.inicializar()
    assert srv.tick() is False  # 03:59 local, último ok há menos de 24 h
    srv._relogio.agora = QUARTA_4H
    assert srv.tick() is True
    srv._relogio.agora = QUARTA_4H + timedelta(hours=5)
    assert srv.tick() is False
    srv._relogio.agora = QUARTA_4H + timedelta(days=1)
    assert srv.tick() is True
    assert [e.status for e in execucoes(sessoes)] == [StatusManutencao.OK] + [StatusManutencao.SO_LOCAL] * 2


def test_ao_subir_com_ultimo_ok_velho_roda_ja_mesmo_antes_das_4h(sessoes, config):
    madrugada = QUARTA_4H - timedelta(hours=3)  # 01:00 local
    gravar_execucao(sessoes, madrugada - timedelta(hours=25), StatusManutencao.OK)
    srv = servico(sessoes, config, madrugada)
    srv.inicializar()
    assert srv.tick() is True
    srv._relogio.agora = QUARTA_4H  # mesmo dia local: não repete às 04:00
    assert srv.tick() is False


def test_ao_subir_sem_nenhum_backup_roda_ja(sessoes, config):
    srv = servico(sessoes, config, QUARTA_4H - timedelta(hours=3))
    srv.inicializar()
    assert srv.tick() is True


def test_recuperacao_so_no_inicio(sessoes, config):
    """Antes das 04:00 e sem ser a primeira passada, um último ok velho espera o horário."""
    madrugada = QUARTA_4H - timedelta(hours=3)
    gravar_execucao(sessoes, madrugada - timedelta(hours=23), StatusManutencao.OK)
    srv = servico(sessoes, config, madrugada)
    srv.inicializar()
    assert srv.tick() is False  # 23 h: em dia
    srv._relogio.agora = madrugada + timedelta(hours=2)  # 25 h, mas não é mais o início
    assert srv.tick() is False


def test_reinicio_nao_repete_o_dia(sessoes, config):
    primeiro = servico(sessoes, config, QUARTA_4H)
    primeiro.inicializar()
    assert primeiro.tick() is True
    segundo = servico(sessoes, config, QUARTA_4H + timedelta(hours=1))
    segundo.inicializar()
    assert segundo.tick() is False
    assert len(execucoes(sessoes)) == 1


def test_erro_conta_como_a_execucao_do_dia(sessoes, config):
    gravar_execucao(sessoes, QUARTA_4H, StatusManutencao.ERRO)
    srv = servico(sessoes, config, QUARTA_4H + timedelta(hours=1))
    srv.inicializar()
    assert srv.tick() is False


def test_execucao_interrompida_e_fechada_e_o_dia_roda_de_novo(sessoes, config):
    gravar_execucao(sessoes, QUARTA_4H, StatusManutencao.RODANDO)
    srv = servico(sessoes, config, QUARTA_4H + timedelta(minutes=10))
    srv.inicializar()
    assert srv.tick() is True
    assert [e.status for e in execucoes(sessoes)] == [StatusManutencao.INTERROMPIDA, StatusManutencao.SO_LOCAL]


def test_desligado_em_servicos_nao_roda_mas_registra_que_esta_vivo(sessoes, config):
    with sessoes() as s, s.begin():
        repo.pausar(s, "pausado no admin", QUARTA_4H, COLETOR_MANUTENCAO)
    srv = servico(sessoes, config, QUARTA_4H)
    srv.inicializar()
    assert srv.tick() is False
    with sessoes() as s:
        assert repo_man.ultimo_ciclo(s) == QUARTA_4H
    assert execucoes(sessoes) == []


def test_usa_o_fuso_de_configuracoes(sessoes, config):
    with sessoes() as s, s.begin():
        repo.obter_config_geral(s, config)
        repo.salvar_config_geral(s, {"fuso": "UTC"}, QUARTA_4H)
    gravar_execucao(sessoes, QUARTA_4H - timedelta(hours=20), StatusManutencao.OK)
    srv = servico(sessoes, config, datetime(2026, 10, 14, 3, 59, tzinfo=UTC))
    srv.inicializar()
    assert srv.tick() is False
    srv._relogio.agora = datetime(2026, 10, 14, 4, 0, tzinfo=UTC)
    assert srv.tick() is True


# --- execução ----------------------------------------------------------------------------------


def test_ok_com_r2_num_dia_de_semana(sessoes, config, pasta):
    enviador, avisador = EnviadorFake(), AvisadorFake()
    srv = servico(sessoes, config, QUARTA_4H, enviador=enviador, avisador=avisador)
    srv.executar(QUARTA_4H)
    (e,) = execucoes(sessoes)
    assert (e.status, e.arquivo, e.tamanho_bytes, e.enviado_r2, e.erro) == (
        StatusManutencao.OK, "tcg-diario-2026-10-14.dump", len(b"PGDMP-fake-123"), True, None
    )
    assert e.fim == QUARTA_4H and e.apagados == {"chamada_ia": 0, "conferencia_checkout": 0, "coleta": 0}
    assert enviador.enviados == ["diario/tcg-2026-10-14.dump"]
    assert sorted(p.name for p in pasta.iterdir()) == ["tcg-diario-2026-10-14.dump"]
    [dados] = avisador.dados(TipoAviso.BACKUP_CONCLUIDO)
    assert dados.titulo_extra == "14/10" and dados.linhas[1] == "Cópia no R2: sim"
    assert dados.linhas[2].startswith("Linhas antigas apagadas: ")
    assert avisador.tipos() == [TipoAviso.BACKUP_CONCLUIDO]
    assert (TipoAviso.BACKUP_ERRO, CHAVE_GERAL) in avisador.resolvidos


def test_domingo_grava_e_envia_tambem_o_semanal(sessoes, config, pasta):
    enviador = EnviadorFake()
    servico(sessoes, config, DOMINGO_4H, enviador=enviador).executar(DOMINGO_4H)
    assert enviador.enviados == ["diario/tcg-2026-10-18.dump", "semanal/tcg-2026-W42.dump"]
    assert sorted(p.name for p in pasta.iterdir()) == ["tcg-diario-2026-10-18.dump", "tcg-semanal-2026-W42.dump"]


def test_sem_r2_fica_so_local_sem_alerta(sessoes, config, pasta):
    avisador = AvisadorFake()
    servico(sessoes, config, QUARTA_4H, avisador=avisador).executar(QUARTA_4H)
    (e,) = execucoes(sessoes)
    assert (e.status, e.enviado_r2, e.erro) == (StatusManutencao.SO_LOCAL, False, None)
    assert avisador.tipos() == [TipoAviso.BACKUP_CONCLUIDO]
    assert avisador.dados(TipoAviso.BACKUP_CONCLUIDO)[0].linhas[1] == "Cópia no R2: não (só local)"


def test_falha_do_pg_dump_grava_erro_avisa_uma_vez_e_nao_limpa(sessoes, config, pasta):
    with sessoes() as s, s.begin():
        repo_ia.registrar_chamada(
            s, em=QUARTA_4H - timedelta(days=100), finalidade="casamento", modelo="m", tokens_entrada=1,
            tokens_saida=1, custo_usd=Decimal(0), ok=True, erro=None,
        )
    enviador, avisador = EnviadorFake(), AvisadorFake()
    srv = servico(sessoes, config, QUARTA_4H, enviador, ExecutorFake(dump_codigo=1), avisador)
    srv.executar(QUARTA_4H)
    (e,) = execucoes(sessoes)
    assert e.status is StatusManutencao.ERRO and "pg_dump falhou" in e.erro
    assert (e.arquivo, e.enviado_r2, e.apagados) == (None, False, None)
    assert enviador.enviados == [] and list(pasta.iterdir()) == []
    [(tipo, chave, dados)] = avisador.avisos
    assert (tipo, chave) == (TipoAviso.BACKUP_ERRO, CHAVE_GERAL) and dados.titulo_extra == "14/10"
    assert "pg_dump falhou" in dados.linhas[0] and dados.linhas[1] == "Nenhum backup novo foi gravado"
    assert avisador.mensagens[0][0] is Destino.ADMIN and "Traceback" not in avisador.mensagens[0][1]
    with sessoes() as s:  # sem backup novo, nada é apagado
        assert s.scalar(select(ChamadaIA.id)) is not None


def test_falha_na_validacao(sessoes, config, pasta):
    avisador = AvisadorFake()
    servico(sessoes, config, QUARTA_4H, None, ExecutorFake(lista=""), avisador).executar(QUARTA_4H)
    (e,) = execucoes(sessoes)
    assert e.status is StatusManutencao.ERRO and "validação" in e.erro
    assert list(pasta.iterdir()) == [] and avisador.tipos() == [TipoAviso.BACKUP_ERRO]


def test_falha_no_r2_mantem_o_local_avisa_e_nao_vaza_segredo(sessoes, config, pasta, caplog):
    caplog.set_level(logging.DEBUG)
    erro = RuntimeError(f"An error occurred (SignatureDoesNotMatch) for key ID-FALSO-R2 secret {SEGREDO}")
    enviador, avisador = EnviadorFake(erro), AvisadorFake()
    servico(sessoes, config, QUARTA_4H, enviador=enviador, avisador=avisador).executar(QUARTA_4H)
    (e,) = execucoes(sessoes)
    assert e.status is StatusManutencao.ERRO and not e.enviado_r2
    assert e.arquivo == "tcg-diario-2026-10-14.dump" and (pasta / e.arquivo).exists()
    assert "R2" in e.erro and "SignatureDoesNotMatch" in e.erro
    assert e.apagados is not None  # o backup local existe: a limpeza roda
    assert avisador.tipos() == [TipoAviso.BACKUP_ERRO]
    assert avisador.dados(TipoAviso.BACKUP_ERRO)[0].linhas[1] == "O backup local ficou salvo"
    for texto in (e.erro, avisador.mensagens[0][1], caplog.text):
        assert SEGREDO not in texto and "ID-FALSO-R2" not in texto


def test_rodizio_e_limpeza_na_mesma_execucao(sessoes, config, pasta):
    pasta.mkdir(parents=True)
    for dia in range(1, 10):
        (pasta / f"tcg-diario-2026-10-{dia:02d}.dump").write_bytes(b"x")
    (pasta / "tcg-antes-monitor.dump").write_bytes(b"manual")
    with sessoes() as s, s.begin():
        repo_ia.registrar_chamada(
            s, em=QUARTA_4H - timedelta(days=100), finalidade="casamento", modelo="m", tokens_entrada=1,
            tokens_saida=1, custo_usd=Decimal(0), ok=True, erro=None,
        )
    servico(sessoes, config, QUARTA_4H).executar(QUARTA_4H)
    (e,) = execucoes(sessoes)
    assert e.apagados["chamada_ia"] == 1
    nomes = sorted(p.name for p in pasta.iterdir())
    assert nomes == ["tcg-antes-monitor.dump"] + [f"tcg-diario-2026-10-{dia:02d}.dump" for dia in (4, 5, 6, 7, 8, 9, 14)]


def test_rodar_para_quando_pedem(sessoes, config):
    srv = servico(sessoes, config, QUARTA_4H)
    srv.parar()
    srv.rodar()
    assert len(execucoes(sessoes)) <= 1


def test_falha_na_copia_semanal_mantem_o_diario_envia_e_limpa(sessoes, config, pasta, monkeypatch):
    from tcg_sniper.manutencao import backup

    def disco_cheio(origem, destino):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(backup, "_copiar_atomico", disco_cheio)
    enviador, avisador = EnviadorFake(), AvisadorFake()
    servico(sessoes, config, DOMINGO_4H, enviador=enviador, avisador=avisador).executar(DOMINGO_4H)
    (e,) = execucoes(sessoes)
    assert e.status is StatusManutencao.ERRO and "cópia semanal" in e.erro
    assert e.arquivo == "tcg-diario-2026-10-18.dump" and (pasta / e.arquivo).exists()
    assert enviador.enviados == ["diario/tcg-2026-10-18.dump"] and e.enviado_r2
    assert e.apagados is not None
    [dados] = avisador.dados(TipoAviso.BACKUP_ERRO)
    assert dados.linhas[1] == "O backup local ficou salvo" and "cópia semanal" in dados.linhas[0]


def test_erro_na_recuperacao_da_madrugada_ganha_mais_uma_tentativa_as_4h(sessoes, config):
    madrugada = QUARTA_4H - timedelta(hours=3)  # 01:00 local, último ok velho: recupera já
    gravar_execucao(sessoes, madrugada - timedelta(days=2), StatusManutencao.OK)
    srv = servico(sessoes, config, madrugada, executar=ExecutorFake(dump_codigo=1))
    srv.inicializar()
    assert srv.tick() is True  # falhou
    srv._relogio.agora = QUARTA_4H - timedelta(minutes=1)
    assert srv.tick() is False
    srv._relogio.agora = QUARTA_4H
    assert srv.tick() is True  # a do horário ainda roda
    srv._relogio.agora = QUARTA_4H + timedelta(hours=1)
    assert srv.tick() is False  # e só uma vez
    assert [e.status for e in execucoes(sessoes)][1:] == [StatusManutencao.ERRO, StatusManutencao.ERRO]


def test_recuperacao_ok_na_madrugada_nao_repete_as_4h(sessoes, config):
    madrugada = QUARTA_4H - timedelta(hours=3)
    srv = servico(sessoes, config, madrugada)
    srv.inicializar()
    assert srv.tick() is True
    srv._relogio.agora = QUARTA_4H
    assert srv.tick() is False


def test_interrompida_ao_subir_avisa_o_admin_uma_vez(sessoes, config):
    gravar_execucao(sessoes, QUARTA_4H, StatusManutencao.RODANDO)
    avisador = AvisadorFake()
    servico(sessoes, config, QUARTA_4H + timedelta(minutes=10), avisador=avisador).inicializar()
    [(tipo, _, dados)] = avisador.avisos
    assert tipo is TipoAviso.BACKUP_INTERROMPIDO
    assert dados.linhas == ("1 execução(ões) interrompida(s) no meio: o serviço de manutenção reiniciou",)
    outro = AvisadorFake()
    servico(sessoes, config, QUARTA_4H + timedelta(minutes=20), avisador=outro).inicializar()
    assert outro.avisos == []


def test_tick_roda_a_vigia_mesmo_com_o_backup_desligado(sessoes, config):
    from tcg_sniper.avisos import servico as avisos
    from tcg_sniper.avisos.catalogo import TipoAviso

    relogio = Relogio(QUARTA_4H - timedelta(hours=3))
    srv = ServicoManutencao(
        sessoes, config, AvisadorFake(), None, ExecutorFake(), relogio=relogio, dormir=lambda _: None
    )
    with sessoes() as s, s.begin():
        repo.pausar(s, "pausado no admin", relogio.agora, COLETOR_MANUTENCAO)
    relogio.agora += timedelta(minutes=11)
    srv.tick()
    with sessoes() as s:
        assert "casador" in avisos.abertos(s, TipoAviso.SERVICO_SEM_SINAL)


def test_tick_expira_individual_vencida_e_apaga_o_codigo(sessoes, config):
    with sessoes() as s, s.begin():
        vencida = repo_msg.enfileirar(
            s, "individual", "*123456*", QUARTA_4H - timedelta(minutes=5), numero="+5511900000001",
            expira_em=QUARTA_4H,
        ).id
        valida = repo_msg.enfileirar(
            s, "individual", "*654321*", QUARTA_4H, numero="+5511900000001", expira_em=QUARTA_4H + timedelta(minutes=5)
        ).id
        grupo = repo_msg.enfileirar(s, "admin", "aviso", QUARTA_4H - timedelta(hours=1)).id
    servico(sessoes, config, QUARTA_4H).tick()
    with sessoes() as s:
        m, v, g = (s.get(MensagemSaida, i) for i in (vencida, valida, grupo))
        assert (m.status, m.texto) == (StatusMensagem.EXPIRADA, repo_msg.TEXTO_APAGADO)
        assert (v.status, v.texto) == (StatusMensagem.PENDENTE, "*654321*")
        assert (g.status, g.texto) == (StatusMensagem.PENDENTE, "aviso")
