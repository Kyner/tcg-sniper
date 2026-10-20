from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fakes import criar_anuncio, criar_preco_liga, criar_produto
from sqlalchemy import select

from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import (
    Envio,
    MensagemSaida,
    Oportunidade,
    StatusCasamento,
    StatusMensagem,
)
from tcg_sniper.db.models import (
    MotivoEncerramento as M,
)
from tcg_sniper.oportunidades.encerramento import encerrar

AGORA = datetime.fromisoformat("2026-10-20T15:00:00+00:00")


@pytest.fixture
def oportunidade(sessoes):
    """Oportunidade aberta com alerta pendente na fila; o teste muda a situação da mensagem."""
    with sessoes() as s, s.begin():
        p = criar_produto(s, "ff", nome="Final Fantasy")
        criar_preco_liga(s, p, "1000.00", listagem_em=AGORA)
        a = criar_anuncio(s, "B0ENCERRA1", produto=p, status=StatusCasamento.CONFIRMADO)
        msg = repo_msg.enfileirar(s, "oportunidades", "alerta", AGORA - timedelta(hours=2))
        op = Oportunidade(
            anuncio_id=a.id, produto_id=p.id, preco_amazon=Decimal(700), preco_liga=Decimal(1000),
            desconto_pct=Decimal(30), envio=Envio.AMAZON, aberta_em=AGORA - timedelta(hours=2),
            alertada_em=AGORA - timedelta(hours=2), preco_alertado=Decimal(700), menor_preco=Decimal(700),
            mensagem_alerta_id=msg.id,
        )
        s.add(op)
        s.flush()
        return op.id, msg.id


def _situacao(sessoes, msg_id, status):
    with sessoes() as s, s.begin():
        s.get(MensagemSaida, msg_id).status = status


def _avisos(s):
    return list(s.scalars(select(MensagemSaida).where(MensagemSaida.texto != "alerta")))


def test_alerta_enviado_avisa_o_grupo_e_grava_o_motivo(sessoes, oportunidade):
    op_id, msg_id = oportunidade
    _situacao(sessoes, msg_id, StatusMensagem.ENVIADA)
    with sessoes() as s, s.begin():
        assert encerrar(s, op_id, M.PRECO_SUBIU, AGORA) is True
    with sessoes() as s:
        op = s.get(Oportunidade, op_id)
        assert (op.fechada_em, op.motivo_encerramento, op.encerramento_avisado_em) == (AGORA, "preco_subiu", AGORA)
        [aviso] = _avisos(s)
        assert aviso.destino == "oportunidades" and "Oferta encerrada · preço subiu" in aviso.texto


def test_alerta_pendente_e_descartado_sem_aviso(sessoes, oportunidade):
    op_id, msg_id = oportunidade
    with sessoes() as s, s.begin():
        encerrar(s, op_id, M.OFERTA_SUMIU, AGORA)
    with sessoes() as s:
        assert s.get(MensagemSaida, msg_id).status is StatusMensagem.DESCARTADA
        assert _avisos(s) == [] and s.get(Oportunidade, op_id).encerramento_avisado_em is None


@pytest.mark.parametrize("status", [StatusMensagem.EXPIRADA, StatusMensagem.DESCARTADA, StatusMensagem.FALHA])
def test_alerta_que_nao_saiu_nao_avisa(sessoes, oportunidade, status):
    op_id, msg_id = oportunidade
    _situacao(sessoes, msg_id, status)
    with sessoes() as s, s.begin():
        encerrar(s, op_id, M.PRECO_SUBIU, AGORA)
    with sessoes() as s:
        assert _avisos(s) == []


def test_sem_mensagem_nao_avisa_mas_alerta_sem_registro_avisa(sessoes, oportunidade):
    op_id, _ = oportunidade
    with sessoes() as s, s.begin():
        s.get(Oportunidade, op_id).mensagem_alerta_id = None
    with sessoes() as s, s.begin():
        encerrar(s, op_id, M.PRECO_SUBIU, AGORA)
    with sessoes() as s, s.begin():
        assert _avisos(s) == []
        op = s.get(Oportunidade, op_id)
        op.fechada_em, op.alerta_sem_registro = None, True  # reabre como oportunidade de antes da versão
    with sessoes() as s, s.begin():
        encerrar(s, op_id, M.PRECO_SUBIU, AGORA)
    with sessoes() as s:
        assert len(_avisos(s)) == 1


def test_casamento_desfeito_avisa_alerta_corrigido(sessoes, oportunidade):
    op_id, msg_id = oportunidade
    _situacao(sessoes, msg_id, StatusMensagem.ENVIADA)
    with sessoes() as s, s.begin():
        encerrar(s, op_id, M.CASAMENTO_DESFEITO, AGORA)
    with sessoes() as s:
        [aviso] = _avisos(s)
        assert aviso.destino == "oportunidades" and "Alerta corrigido" in aviso.texto


def test_tecnico_vai_para_o_admin(sessoes, oportunidade):
    op_id, msg_id = oportunidade
    _situacao(sessoes, msg_id, StatusMensagem.ENVIADA)
    with sessoes() as s, s.begin():
        encerrar(s, op_id, M.SEM_LEITURA, AGORA)
    with sessoes() as s:
        [aviso] = _avisos(s)
        assert aviso.destino == "admin"


def test_segunda_chamada_nao_fecha_nem_avisa_de_novo(sessoes, oportunidade):
    op_id, msg_id = oportunidade
    _situacao(sessoes, msg_id, StatusMensagem.ENVIADA)
    with sessoes() as s, s.begin():
        assert encerrar(s, op_id, M.PRECO_SUBIU, AGORA) is True
    with sessoes() as s, s.begin():
        assert encerrar(s, op_id, M.CASAMENTO_DESFEITO, AGORA + timedelta(minutes=1)) is False
    with sessoes() as s:
        assert len(_avisos(s)) == 1 and s.get(Oportunidade, op_id).motivo_encerramento == "preco_subiu"


def test_limpa_o_risco(sessoes, oportunidade):
    op_id, _ = oportunidade
    with sessoes() as s, s.begin():
        op = s.get(Oportunidade, op_id)
        op.em_risco_desde, op.motivo_risco = AGORA - timedelta(minutes=40), M.OFERTA_SUMIU
    with sessoes() as s, s.begin():
        encerrar(s, op_id, M.OFERTA_SUMIU, AGORA)
    with sessoes() as s:
        op = s.get(Oportunidade, op_id)
        assert (op.em_risco_desde, op.motivo_risco) == (None, None)


def test_oferta_sumiu_diz_indisponivel_mesmo_com_preco_guardado(sessoes, oportunidade):
    from tcg_sniper.db.models import OrigemPreco, PrecoAtualAmazon

    op_id, msg_id = oportunidade
    _situacao(sessoes, msg_id, StatusMensagem.ENVIADA)
    with sessoes() as s, s.begin():
        anuncio_id = s.get(Oportunidade, op_id).anuncio_id
        s.add(PrecoAtualAmazon(anuncio_id=anuncio_id, preco=Decimal("555.55"), origem=OrigemPreco.PRODUTO, envio=Envio.AMAZON, coletado_em=AGORA))
    with sessoes() as s, s.begin():
        encerrar(s, op_id, M.OFERTA_SUMIU, AGORA)
    with sessoes() as s:
        [aviso] = _avisos(s)
        assert "555" not in aviso.texto and "indisponível" in aviso.texto
