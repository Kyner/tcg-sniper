from datetime import datetime

from sqlalchemy.orm import Session

from tcg_sniper.db.models import AcaoGestao, TipoAcaoGestao


def registrar(s: Session, usuario_id: int | None, tipo: TipoAcaoGestao, detalhe: dict, agora: datetime) -> AcaoGestao:
    """Grava a ação na transação de quem chama (sem commit). `usuario_id` nulo = admin antigo."""
    acao = AcaoGestao(usuario_id=usuario_id, em=agora, tipo=tipo, detalhe=detalhe)
    s.add(acao)
    s.flush()
    return acao
