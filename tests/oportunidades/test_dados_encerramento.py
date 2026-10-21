from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from tcg_sniper.avisos.catalogo import CATALOGO, TipoAviso
from tcg_sniper.avisos.formato import aviso_de, formatar
from tcg_sniper.db.models import MotivoEncerramento as M
from tcg_sniper.notificador.base import Destino
from tcg_sniper.oportunidades.mensagens import dados_encerramento, tipo_do_encerramento

SP = ZoneInfo("America/Sao_Paulo")
ABERTA = datetime.fromisoformat("2026-10-18T13:15:00+00:00")  # 10:15 em São Paulo
FECHADA = ABERTA + timedelta(hours=3, minutes=20)


def texto(motivo, preco_atual=Decimal("1549.90")):
    dados = dados_encerramento(
        motivo=motivo, nome_produto="Final Fantasy - Caixa de Booster de Jogo", aberta_em=ABERTA,
        fechada_em=FECHADA, preco_alertado=Decimal("1299.90"), preco_atual=preco_atual,
        preco_liga=Decimal("1589.00"), url_amazon="https://www.amazon.com.br/dp/B0TESTE123", zona=SP,
    )
    tipo = tipo_do_encerramento(motivo)
    return tipo, formatar(aviso_de(tipo, dados, FECHADA), SP, None, estrito=True)


def test_preco_subiu_vai_para_o_grupo_de_oportunidades():
    tipo, t = texto(M.PRECO_SUBIU)
    assert tipo is TipoAviso.OPORTUNIDADE_ENCERRADA
    assert CATALOGO[tipo].grupo is Destino.OPORTUNIDADES
    assert "Oferta encerrada · preço subiu" in t
    assert "Durou 3 h 20 min (desde 18/10 10:15)" in t
    assert "R$ 1.299,90" in t and "R$ 1.549,90" in t and "R$ 1.589,00" in t


def test_oferta_sumiu_mostra_indisponivel():
    _, t = texto(M.OFERTA_SUMIU, preco_atual=None)
    assert "oferta sumiu" in t and "indisponível" in t


def test_casamento_desfeito_e_alerta_corrigido():
    tipo, t = texto(M.CASAMENTO_DESFEITO)
    assert tipo is TipoAviso.OPORTUNIDADE_CORRIGIDA
    assert "Alerta corrigido" in t
    assert "O alerta de 18/10 10:15 era de outro produto: desconsidere." in t


def test_tecnicos_vao_para_o_admin():
    for motivo in (M.SEM_LEITURA, M.LIGA_DESATUALIZADA):
        tipo, _ = texto(motivo)
        assert tipo is TipoAviso.OPORTUNIDADE_ENCERRADA_TECNICO
        assert CATALOGO[tipo].grupo is Destino.ADMIN


def test_duracao_curta():
    dados = dados_encerramento(
        motivo=M.PRECO_SUBIU, nome_produto="X", aberta_em=ABERTA, fechada_em=ABERTA + timedelta(minutes=45),
        preco_alertado=Decimal(10), preco_atual=Decimal(20), preco_liga=None, url_amazon=None, zona=SP,
    )
    assert "Durou 45 min (desde 18/10 10:15)" in dados.linhas[0]
