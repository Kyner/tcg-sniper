import threading
from datetime import timedelta
from decimal import Decimal

import pytest
from fakes import T0, criar_anuncio, criar_par, criar_produto
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import Casamento, Envio, OrigemCasamento, StatusCasamento

PENDENTE, CONFIRMADO, IGNORADO = StatusCasamento.PENDENTE, StatusCasamento.CONFIRMADO, StatusCasamento.IGNORADO
MANUAL, OUTRO = OrigemCasamento.MANUAL, OrigemCasamento.OUTRO_CONFIRMADO


def situacao(s, anuncio, produto):
    par = repo_casamento.obter_par(s, anuncio.id, produto.id)
    return None if par is None else (par.status, par.origem)


def abrir_op(s, anuncio, produto):
    return repo_amz.abrir_oportunidade(
        s, anuncio_id=anuncio.id, produto_id=produto.id, preco_amazon=Decimal(1), preco_liga=Decimal(2),
        desconto_pct=Decimal(50), vendedor_id=None, envio=Envio.AMAZON, agora=T0, conferido=False,
    )


def avaliacao(s, anuncio, produto):
    return repo_ia.gravar_avaliacao(
        s, anuncio_id=anuncio.id, produto_id=produto.id, mesmo_produto=True, confianca=99, motivo="m",
        modelo="gpt-5", assinatura="x", sem_imagem=False, chamada_id=None, agora=T0,
    )


def test_registrar_visto_cria_pendente_e_depois_so_atualiza_o_visto(s):
    p = criar_produto(s, "p")
    anuncio = criar_anuncio(s, "B0VISTO001")
    par, criado = repo_casamento.registrar_visto(s, anuncio.id, p.id, T0)
    assert criado and (par.status, par.origem, par.visto_primeiro_em, par.visto_ultimo_em) == (PENDENTE, None, T0, T0)
    repo_casamento.ignorar(s, anuncio.id, p.id, T0)
    depois = T0 + timedelta(days=1)
    par, criado = repo_casamento.registrar_visto(s, anuncio.id, p.id, depois)
    assert not criado and (par.status, par.visto_primeiro_em, par.visto_ultimo_em) == (IGNORADO, T0, depois)


def test_ignorado_para_a_vira_pendente_para_b(s):
    a, b = criar_produto(s, "a"), criar_produto(s, "b")
    anuncio = criar_anuncio(s, "B0IGNA0001", produto=a, status=IGNORADO, origem=MANUAL)
    par, criado = repo_casamento.registrar_visto(s, anuncio.id, b.id, T0)
    assert criado and par.status is PENDENTE
    assert situacao(s, anuncio, a) == (IGNORADO, MANUAL)


def test_anuncio_confirmado_para_q_entra_como_outro_confirmado_para_p(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    anuncio = criar_anuncio(s, "B0CONFQ001", produto=q, status=CONFIRMADO, origem=MANUAL)
    par, criado = repo_casamento.registrar_visto(s, anuncio.id, p.id, T0)
    assert criado and (par.status, par.origem, par.revisado_em) == (IGNORADO, OUTRO, T0)


def test_confirmar_ignora_os_outros_pendentes_e_fecha_oportunidades_dos_outros(s):
    p, q, r = criar_produto(s, "p"), criar_produto(s, "q"), criar_produto(s, "r")
    anuncio = criar_anuncio(s, "B0CONF0001", produto=p)
    criar_par(s, anuncio, q)
    criar_par(s, anuncio, r, status=IGNORADO, origem=MANUAL, revisado_em=T0)
    op_q = abrir_op(s, anuncio, q)
    par = repo_casamento.confirmar(s, anuncio.id, p.id, T0, OrigemCasamento.SUGERIDO_IA)
    assert (par.status, par.origem, par.revisado_em, par.reavaliar) == (CONFIRMADO, OrigemCasamento.SUGERIDO_IA, T0, False)
    assert situacao(s, anuncio, q) == (IGNORADO, OUTRO)
    assert situacao(s, anuncio, r) == (IGNORADO, MANUAL)  # decisão sua não muda
    s.refresh(op_q)
    assert op_q.fechada_em == T0


def test_confirmar_cria_o_par_que_nao_existe(s):
    p = criar_produto(s, "p")
    anuncio = criar_anuncio(s, "B0NOVO0001")
    par = repo_casamento.confirmar(s, anuncio.id, p.id, T0)
    assert (par.status, par.origem, par.visto_primeiro_em, par.visto_ultimo_em) == (CONFIRMADO, MANUAL, T0, T0)


def test_confirmar_anuncio_ja_confirmado_em_outro_produto_nao_muda_nada(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    anuncio = criar_anuncio(s, "B0JACONF01", produto=q, status=CONFIRMADO, origem=MANUAL)
    criar_par(s, anuncio, p)
    with pytest.raises(repo_casamento.JaConfirmado) as erro:
        repo_casamento.confirmar(s, anuncio.id, p.id, T0)
    assert erro.value.produto_id == q.id and str(erro.value) == "já confirmado para outro produto"
    assert situacao(s, anuncio, p) == (PENDENTE, None)
    assert situacao(s, anuncio, q) == (CONFIRMADO, MANUAL)
    assert repo_casamento.confirmar(s, anuncio.id, q.id, T0).produto_id == q.id  # o mesmo par: nada a fazer


def test_indice_unico_recusa_dois_confirmados_no_mesmo_anuncio(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    anuncio = criar_anuncio(s, "B0INDICE01", produto=p, status=CONFIRMADO)
    with pytest.raises(IntegrityError), s.begin_nested():
        criar_par(s, anuncio, q, status=CONFIRMADO)


def test_confirmacoes_concorrentes_so_uma_vale(engine):
    """Duas transações confirmam o mesmo anúncio para produtos diferentes ao mesmo tempo: uma vale, a
    outra recebe JaConfirmado. Grava de verdade (fora do `sessoes`) e apaga no fim."""
    fabrica = sessionmaker(bind=engine, expire_on_commit=False)
    with fabrica() as s, s.begin():
        p, q = criar_produto(s, "conc-p", nome="Conc P"), criar_produto(s, "conc-q", nome="Conc Q")
        anuncio_id, produtos = criar_anuncio(s, "B0CONC0001").id, (p.id, q.id)
    barreira = threading.Barrier(2)
    resultados: dict[int, str] = {}

    def confirmar(produto_id: int) -> None:
        with fabrica() as s, s.begin():
            barreira.wait(timeout=10)
            try:
                repo_casamento.confirmar(s, anuncio_id, produto_id, T0)
                resultados[produto_id] = "ok"
            except repo_casamento.JaConfirmado:
                resultados[produto_id] = "já"

    try:
        linhas = [threading.Thread(target=confirmar, args=(produto_id,)) for produto_id in produtos]
        for linha in linhas:
            linha.start()
        for linha in linhas:
            linha.join(timeout=30)
        assert sorted(resultados.values()) == ["já", "ok"]
        with fabrica() as s:
            confirmados = s.scalars(
                select(Casamento).where(Casamento.anuncio_id == anuncio_id, Casamento.status == CONFIRMADO)
            ).all()
        assert len(confirmados) == 1
    finally:
        with engine.begin() as c:
            c.execute(text("DELETE FROM casamento WHERE anuncio_id = :a"), {"a": anuncio_id})
            c.execute(text("DELETE FROM anuncio_amazon WHERE id = :a"), {"a": anuncio_id})
            c.execute(text("DELETE FROM produto_liga WHERE liga_id IN ('conc-p', 'conc-q')"))


def test_desfazer_confirmado_volta_a_pendente_reabre_outros_e_pede_reavaliacao(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    anuncio = criar_anuncio(s, "B0DESF0001", produto=p)
    criar_par(s, anuncio, q)
    av = avaliacao(s, anuncio, p)
    repo_casamento.confirmar(s, anuncio.id, p.id, T0, OrigemCasamento.AUTOMATICO_IA)
    av.aplicada_em = T0
    op = abrir_op(s, anuncio, p)
    depois = T0 + timedelta(hours=1)
    par = repo_casamento.desfazer(s, anuncio.id, p.id, depois)
    assert (par.status, par.origem, par.revisado_em, par.reavaliar) == (PENDENTE, None, None, True)
    assert situacao(s, anuncio, q) == (PENDENTE, None)
    s.refresh(av)
    s.refresh(op)
    assert av.aplicada_em is None and op.fechada_em == depois
    assert repo_casamento.desfazer(s, anuncio.id, criar_produto(s, "sem-par").id, T0) is None


def test_desfazer_par_outro_confirmado_com_o_anuncio_ainda_confirmado_e_recusado(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    anuncio = criar_anuncio(s, "B0DESF0002", produto=q, status=CONFIRMADO, origem=MANUAL)
    criar_par(s, anuncio, p, status=IGNORADO, origem=OUTRO, revisado_em=T0)
    with pytest.raises(repo_casamento.JaConfirmado):
        repo_casamento.desfazer(s, anuncio.id, p.id, T0)
    assert situacao(s, anuncio, p) == (IGNORADO, OUTRO)


def test_ignorar_o_confirmado_reabre_os_outro_confirmado(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    anuncio = criar_anuncio(s, "B0IGNC0001", produto=p)
    criar_par(s, anuncio, q)
    repo_casamento.confirmar(s, anuncio.id, p.id, T0)
    assert situacao(s, anuncio, q) == (IGNORADO, OUTRO)
    par = repo_casamento.ignorar(s, anuncio.id, p.id, T0, MANUAL)
    assert (par.status, par.origem, par.revisado_em, par.reavaliar) == (IGNORADO, MANUAL, T0, False)
    assert situacao(s, anuncio, q) == (PENDENTE, None)
    assert repo_casamento.ignorar(s, anuncio.id, criar_produto(s, "sem-par").id, T0) is None


def test_trocar_ignora_o_confirmado_anterior_como_manual_e_confirma_o_novo(s):
    p, q, r = criar_produto(s, "p"), criar_produto(s, "q"), criar_produto(s, "r")
    anuncio = criar_anuncio(s, "B0TROC0001", produto=p)
    criar_par(s, anuncio, r)
    repo_casamento.confirmar(s, anuncio.id, p.id, T0, OrigemCasamento.AUTOMATICO_IA)
    op = abrir_op(s, anuncio, p)
    depois = T0 + timedelta(hours=1)
    par = repo_casamento.trocar(s, anuncio.id, q.id, depois, OrigemCasamento.SUGERIDO_IA)
    assert (par.status, par.origem, par.revisado_em) == (CONFIRMADO, OrigemCasamento.SUGERIDO_IA, depois)
    assert situacao(s, anuncio, p) == (IGNORADO, MANUAL)
    assert situacao(s, anuncio, r) == (IGNORADO, OUTRO)
    s.refresh(op)
    assert op.fechada_em == depois


def test_casar_asin_cria_o_anuncio_ou_troca_o_confirmado(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    novo = repo_casamento.casar_asin(s, p.id, "B0ASIN0001", T0, "Provisório")
    assert (novo.titulo, novo.url, novo.visto_primeiro_em) == ("Provisório", "https://www.amazon.com.br/dp/B0ASIN0001", T0)
    assert situacao(s, novo, p) == (CONFIRMADO, MANUAL)
    depois = T0 + timedelta(hours=1)
    mesmo = repo_casamento.casar_asin(s, q.id, "B0ASIN0001", depois, "Provisório")
    assert mesmo.id == novo.id and mesmo.visto_ultimo_em == depois
    assert situacao(s, novo, p) == (IGNORADO, MANUAL)
    assert situacao(s, novo, q) == (CONFIRMADO, MANUAL)


def test_reavaliar_produto_so_mexe_nos_pares_dele_e_nao_nas_decisoes_manuais(s):
    p, q, outro = criar_produto(s, "p"), criar_produto(s, "q"), criar_produto(s, "outro")
    pend = criar_anuncio(s, "B0REAV0001", produto=p)
    pela_ia = criar_anuncio(s, "B0REAV0002", produto=p, status=IGNORADO, origem=OrigemCasamento.AUTOMATICO_IA)
    sugerido = criar_anuncio(s, "B0REAV0003", produto=p, status=IGNORADO, origem=OrigemCasamento.SUGERIDO_IA)
    manual = criar_anuncio(s, "B0REAV0004", produto=p, status=IGNORADO, origem=MANUAL)
    confirmado = criar_anuncio(s, "B0REAV0005", produto=p, status=CONFIRMADO, origem=OrigemCasamento.AUTOMATICO_IA)
    casado_em_q = criar_anuncio(s, "B0REAV0006", produto=q, status=CONFIRMADO, origem=MANUAL)
    criar_par(s, casado_em_q, p, status=IGNORADO, origem=OUTRO, revisado_em=T0)
    sobra = criar_anuncio(s, "B0REAV0007", produto=p, status=IGNORADO, origem=OUTRO)  # sem confirmado em lugar nenhum
    de_outro = criar_anuncio(s, "B0REAV0008", produto=outro, status=IGNORADO, origem=OrigemCasamento.AUTOMATICO_IA)
    av = avaliacao(s, pela_ia, p)
    av.aplicada_em = T0
    s.flush()
    assert repo_casamento.reavaliar_produto(s, p.id, T0) == 4
    for anuncio in (pend, pela_ia, sugerido, sobra):
        par = repo_casamento.obter_par(s, anuncio.id, p.id)
        assert (par.status, par.origem, par.revisado_em, par.reavaliar) == (PENDENTE, None, None, True)
    assert situacao(s, manual, p) == (IGNORADO, MANUAL)
    assert situacao(s, confirmado, p) == (CONFIRMADO, OrigemCasamento.AUTOMATICO_IA)
    assert situacao(s, casado_em_q, p) == (IGNORADO, OUTRO)
    assert situacao(s, de_outro, outro) == (IGNORADO, OrigemCasamento.AUTOMATICO_IA)
    s.refresh(av)
    assert av.aplicada_em is None


def test_marcar_reavaliado(s):
    p = criar_produto(s, "p")
    anuncio = criar_anuncio(s, "B0MARC0001", produto=p, status=IGNORADO, origem=OrigemCasamento.AUTOMATICO_IA)
    repo_casamento.reavaliar_produto(s, p.id, T0)
    repo_casamento.marcar_reavaliado(s, anuncio.id, p.id)
    assert repo_casamento.obter_par(s, anuncio.id, p.id).reavaliar is False


def test_condicao_confirmado_e_produtos_casados(s):
    p, q = criar_produto(s, "p"), criar_produto(s, "q")
    anuncio = criar_anuncio(s, "B0COND0001", produto=p, status=CONFIRMADO)
    criar_par(s, anuncio, q, status=IGNORADO, origem=OUTRO, revisado_em=T0)
    assert set(s.scalars(repo_casamento.produtos_casados())) == {p.id}
    par = s.scalar(select(Casamento).where(repo_casamento.condicao_confirmado(anuncio.id)))
    assert par.produto_id == p.id
