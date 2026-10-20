"""Fim de uma oportunidade: o único lugar que fecha (monitor, busca e casamento), grava o motivo e decide o
aviso pela situação da mensagem do alerta (spec 2026-10-20-fim-da-oportunidade):

- alerta enviado (ou oportunidade de antes desta versão, `alerta_sem_registro`): avisa o grupo do motivo;
- alerta ainda pendente na fila: descarta o alerta (perdeu a validade) e não avisa;
- alerta expirado, descartado, com falha ou sem mensagem: não avisa (ninguém viu o alerta).

Roda na transação de quem chama; o aviso roda em savepoint (`avisos.servico.avisar`): falha nele não desfaz o
encerramento."""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from tcg_sniper.avisos import servico as avisos
from tcg_sniper.db import repositorio_mensagens as repo_msg
from tcg_sniper.db.models import (
    AnuncioAmazon,
    MensagemSaida,
    MotivoEncerramento,
    Oportunidade,
    PrecoAtualAmazon,
    PrecoAtualLiga,
    ProdutoLiga,
    StatusMensagem,
)
from tcg_sniper.oportunidades.mensagens import dados_encerramento, tipo_do_encerramento

log = logging.getLogger(__name__)


def _alerta_saiu(s: Session, op: Oportunidade, agora: datetime) -> bool:
    mensagem = s.get(MensagemSaida, op.mensagem_alerta_id) if op.mensagem_alerta_id else None
    if mensagem is not None and mensagem.status is StatusMensagem.PENDENTE:
        repo_msg.descartar(s, mensagem.id, agora)
        return False
    if op.alerta_sem_registro:
        return True
    return mensagem is not None and mensagem.status is StatusMensagem.ENVIADA


def encerrar(s: Session, oportunidade_id: int, motivo: MotivoEncerramento, agora: datetime) -> bool:
    op = s.get(Oportunidade, oportunidade_id, with_for_update=True, populate_existing=True)
    if op is None or op.fechada_em is not None:
        return False
    op.fechada_em, op.motivo_encerramento = agora, motivo
    op.em_risco_desde = op.motivo_risco = None
    s.flush()
    if not _alerta_saiu(s, op, agora):
        return True
    produto = s.get(ProdutoLiga, op.produto_id)
    anuncio = s.get(AnuncioAmazon, op.anuncio_id)
    # Oferta sumida: o preço guardado é o da última leitura, não vale para o aviso ("indisponível").
    # Oferta sumida: o preço guardado é o da última leitura; o aviso sempre diz "indisponível".
    atual = None if motivo is MotivoEncerramento.OFERTA_SUMIU else s.get(PrecoAtualAmazon, op.anuncio_id)
    liga = s.get(PrecoAtualLiga, op.produto_id)
    zona, _ = avisos.zona_e_host(s)
    dados = dados_encerramento(
        motivo=motivo, nome_produto=produto.nome, aberta_em=op.aberta_em, fechada_em=agora,
        preco_alertado=op.preco_alertado, preco_atual=atual.preco if atual else None,
        preco_liga=liga.preco_a_partir if liga else None, url_amazon=anuncio.url if anuncio else None, zona=zona,
    )
    if avisos.avisar(s, tipo_do_encerramento(motivo), str(op.id), dados, agora) is not None:
        op.encerramento_avisado_em = agora
        s.flush()
    return True
