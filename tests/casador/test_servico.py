import json
from datetime import timedelta

import httpx
from fakes import T0, NotificadorFake, TransporteFake, criar_anuncio, criar_produto
from sqlalchemy import select

from tcg_sniper.casador.pergunta import assinatura
from tcg_sniper.casador.servico import ServicoCasador
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_amazon as repo_amz
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import (
    COLETOR_CASADOR,
    AnuncioAmazon,
    AvaliacaoIA,
    ChamadaIA,
    EstadoColetorTipo,
    ProdutoLiga,
    StatusCasamento,
)
from tcg_sniper.ia.modelos import Bruta, ChaveInvalida, ErroIA
from tcg_sniper.notificador.base import Destino


def veredito(mesmo=True, confianca=95, motivo="mesma caixa"):
    return Bruta(json.dumps({"mesmo_produto": mesmo, "confianca": confianca, "motivo": motivo}), 1000, 100)


def sem_rede():
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))


def servico(sessoes, config, respostas, **kw):
    t = TransporteFake(respostas)
    n = NotificadorFake()
    cfg = config.model_copy(update={"openai_api_key": "sk-teste"})
    agora = kw.pop("agora", T0)
    sv = ServicoCasador(sessoes, t, cfg, n, cliente_http=kw.pop("cliente_http", sem_rede()), relogio=lambda: agora, **kw)
    return sv, t, n


def configurar(sessoes, **valores):
    with sessoes() as s, s.begin():
        repo_ia.salvar_config_ia(s, {"ligado": True, **valores}, T0)


def pares(sessoes, n=1, status=StatusCasamento.PENDENTE):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Caixa Alfa")
        return p.id, [criar_anuncio(s, f"B{i}", produto=p, status=status).id for i in range(n)]


def avaliacoes(sessoes):
    with sessoes() as s:
        return list(s.scalars(select(AvaliacaoIA).order_by(AvaliacaoIA.id)))


def status_de(sessoes, anuncio_id):
    with sessoes() as s:
        return s.get(AnuncioAmazon, anuncio_id).status_casamento


def test_desligada_nao_chama(sessoes, config):
    pares(sessoes)
    sv, t, _ = servico(sessoes, config, [])
    assert sv.ciclo() == 0 and t.pedidos == []


def test_sem_chave_nao_chama(sessoes, config):
    configurar(sessoes)
    pares(sessoes)
    sv = ServicoCasador(sessoes, None, config, NotificadorFake(), cliente_http=sem_rede(), relogio=lambda: T0)
    assert sv.ciclo() == 0


def test_pausado_nao_chama(sessoes, config):
    configurar(sessoes)
    pares(sessoes)
    with sessoes() as s, s.begin():
        repo.pausar(s, "pausado no admin", T0, COLETOR_CASADOR)
    sv, t, _ = servico(sessoes, config, [])
    assert sv.ciclo() == 0 and t.pedidos == []


def test_sugere_sem_mudar_status_com_automatico_desligado(sessoes, config):
    configurar(sessoes)
    _, [a] = pares(sessoes)
    sv, t, _ = servico(sessoes, config, [veredito(True, 99)])
    assert sv.ciclo() == 1
    [av] = avaliacoes(sessoes)
    assert av.mesmo_produto and av.confianca == 99 and av.aplicada_em is None and av.sem_imagem
    assert status_de(sessoes, a) is StatusCasamento.PENDENTE
    assert t.pedidos[0].imagens == ()


def test_nao_reavalia_com_assinatura_igual_e_reavalia_quando_muda(sessoes, config):
    configurar(sessoes)
    _, [a] = pares(sessoes)
    sv, t, _ = servico(sessoes, config, [veredito(), veredito(False, 80, "outro")])
    sv.ciclo()
    assert sv.ciclo() == 0 and len(t.pedidos) == 1
    with sessoes() as s, s.begin():
        s.get(AnuncioAmazon, a).titulo = "Título novo"
    assert sv.ciclo() == 1
    [av] = avaliacoes(sessoes)
    assert av.mesmo_produto is False and av.motivo == "outro"


def test_automatico_respeita_os_limites(sessoes, config):
    configurar(sessoes, automatico=True, confianca_confirmar=90, confianca_ignorar=85)
    _, ids = pares(sessoes, 4)
    sv, _, _ = servico(sessoes, config, [veredito(True, 90), veredito(True, 89), veredito(False, 85), veredito(False, 84)])
    assert sv.ciclo() == 4
    por_anuncio = {av.anuncio_id: av for av in avaliacoes(sessoes)}
    # ordem do ciclo: mais recentes primeiro; todos têm o mesmo visto_ultimo_em, desempate por id
    esperado = dict(zip(ids, [StatusCasamento.CONFIRMADO, StatusCasamento.PENDENTE, StatusCasamento.IGNORADO, StatusCasamento.PENDENTE]))
    for anuncio_id, situacao in esperado.items():
        assert status_de(sessoes, anuncio_id) is situacao
        assert (por_anuncio[anuncio_id].aplicada_em is not None) == (situacao is not StatusCasamento.PENDENTE)


def test_decisao_humana_durante_a_chamada_vence(sessoes, config):
    configurar(sessoes, automatico=True)
    p_id, [a] = pares(sessoes)
    with sessoes() as s, s.begin():
        outro_id = criar_produto(s, "p2").id

    class TransporteQueDecide(TransporteFake):
        def enviar(self, pedido):
            with sessoes() as s, s.begin():
                repo_amz.confirmar_casamento(s, a, outro_id, T0)  # usuário troca o produto no meio
            return super().enviar(pedido)

    t = TransporteQueDecide([veredito(False, 99)])
    sv = ServicoCasador(sessoes, t, config.model_copy(update={"openai_api_key": "k"}), NotificadorFake(),
                        cliente_http=sem_rede(), relogio=lambda: T0)
    sv.ciclo()
    with sessoes() as s:
        anuncio = s.get(AnuncioAmazon, a)
        assert anuncio.status_casamento is StatusCasamento.CONFIRMADO and anuncio.produto_id == outro_id
    [av] = avaliacoes(sessoes)
    assert av.produto_id == p_id and av.aplicada_em is None


def test_desfeito_pelo_usuario_nao_e_reaplicado(sessoes, config):
    configurar(sessoes, automatico=True)
    _, [a] = pares(sessoes)
    sv, _, _ = servico(sessoes, config, [veredito(True, 99), veredito(True, 99)])
    sv.ciclo()
    assert status_de(sessoes, a) is StatusCasamento.CONFIRMADO
    with sessoes() as s, s.begin():
        repo_amz.desfazer_casamento(s, a, T0)
        s.get(AnuncioAmazon, a).titulo = "Título novo"  # força reavaliação
    assert sv.ciclo() == 1
    assert status_de(sessoes, a) is StatusCasamento.PENDENTE


def test_resposta_fora_do_formato_nao_grava_e_volta(sessoes, config):
    configurar(sessoes)
    pares(sessoes)
    ruim = Bruta(json.dumps({"mesmo_produto": True, "confianca": 150, "motivo": "x"}), 10, 1)
    sv, _, _ = servico(sessoes, config, [ruim, veredito()])
    sv.ciclo()
    assert avaliacoes(sessoes) == []
    with sessoes() as s:
        assert [c.ok for c in s.scalars(select(ChamadaIA))] == [True]  # a chamada saiu; o formato é do casador
    sv.ciclo()
    assert len(avaliacoes(sessoes)) == 1


def test_tres_erros_seguidos_encerram_o_ciclo(sessoes, config):
    configurar(sessoes)
    pares(sessoes, 5)
    sv, t, _ = servico(sessoes, config, [ErroIA("OpenAI 500")] * 3)
    assert sv.ciclo() == 0 and len(t.pedidos) == 3


def test_chave_invalida_pausa_e_avisa(sessoes, config):
    configurar(sessoes)
    pares(sessoes, 2)
    sv, t, n = servico(sessoes, config, [ChaveInvalida("chave recusada pela OpenAI (401)")])
    sv.ciclo()
    with sessoes() as s:
        estado = repo.obter_estado(s, coletor=COLETOR_CASADOR)
    assert estado.estado is EstadoColetorTipo.PAUSADO and "401" in estado.motivo
    assert len(t.pedidos) == 1 and n.mensagens[0][0] is Destino.ADMIN and "401" in n.mensagens[0][1]


def test_sem_orcamento_para_e_avisa_uma_vez_por_dia(sessoes, config):
    configurar(sessoes, max_chamadas_dia=1)
    pares(sessoes, 3)
    sv, t, n = servico(sessoes, config, [veredito()])
    assert sv.ciclo() == 1 and len(t.pedidos) == 1
    sv.ciclo()
    assert len(n.mensagens) == 1 and "chamadas" in n.mensagens[0][1]
    # dia seguinte: libera e avisa de novo só se estourar de novo
    sv2, t2, n2 = servico(sessoes, config, [veredito()], agora=T0 + timedelta(days=1))
    sv2._avisos_orcamento = sv._avisos_orcamento
    assert sv2.ciclo() == 1 and len(t2.pedidos) == 1
    assert len(n2.mensagens) == 1  # estourou de novo no dia novo: um aviso novo


def test_imagens_vao_na_pergunta(sessoes, config):
    import base64
    import io

    from PIL import Image

    saida = io.BytesIO()
    Image.new("RGB", (10, 10)).save(saida, "PNG")
    cliente = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=saida.getvalue())))
    configurar(sessoes)
    p_id, [a] = pares(sessoes)
    with sessoes() as s, s.begin():
        s.get(AnuncioAmazon, a).imagem_url = "https://img/a.jpg"
        s.get(ProdutoLiga, p_id).imagem_url = "https://img/p.jpg"
    sv, t, _ = servico(sessoes, config, [veredito()], cliente_http=cliente)
    sv.ciclo()
    assert len(t.pedidos[0].imagens) == 2 and all(base64.b64decode(i) for i in t.pedidos[0].imagens)
    assert avaliacoes(sessoes)[0].sem_imagem is False


def test_lote_limita_o_ciclo(sessoes, config):
    configurar(sessoes, lote=2)
    pares(sessoes, 5)
    sv, _, _ = servico(sessoes, config, [veredito()] * 5)
    assert sv.ciclo() == 2


def test_assinatura_gravada_e_a_do_par(sessoes, config):
    configurar(sessoes)
    p_id, [a] = pares(sessoes)
    sv, _, _ = servico(sessoes, config, [veredito()])
    sv.ciclo()
    with sessoes() as s:
        assert avaliacoes(sessoes)[0].assinatura == assinatura(s.get(AnuncioAmazon, a), s.get(ProdutoLiga, p_id))
