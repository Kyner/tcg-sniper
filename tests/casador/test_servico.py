import json
from datetime import timedelta

import httpx
from fakes import T0, AvisadorFake, TransporteFake, criar_anuncio, criar_produto
from sqlalchemy import select

from tcg_sniper.avisos.catalogo import CHAVE_GERAL, TipoAviso
from tcg_sniper.casador.pergunta import assinatura
from tcg_sniper.casador.servico import ServicoCasador
from tcg_sniper.db import repositorio as repo
from tcg_sniper.db import repositorio_casamento as repo_casamento
from tcg_sniper.db import repositorio_ia as repo_ia
from tcg_sniper.db.models import (
    COLETOR_CASADOR,
    AnuncioAmazon,
    AvaliacaoIA,
    Casamento,
    ChamadaIA,
    EstadoColetorTipo,
    OrigemCasamento,
    ProdutoLiga,
    StatusCasamento,
)
from tcg_sniper.ia.modelos import Bruta, ChaveInvalida, ConfiguracaoInvalida, ErroIA
from tcg_sniper.notificador.base import Destino


class Relogio:
    def __init__(self, inicio=T0):
        self.agora = inicio

    def __call__(self):
        return self.agora

    def avancar(self, **delta):
        self.agora += timedelta(**delta)


def veredito(mesmo=True, confianca=95, motivo="mesma caixa"):
    return Bruta(json.dumps({"mesmo_produto": mesmo, "confianca": confianca, "motivo": motivo}), 1000, 100)


def sem_rede():
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))


def servico(sessoes, config, respostas, **kw):
    t = TransporteFake(respostas)
    n = AvisadorFake()
    cfg = config.model_copy(update={"openai_api_key": "sk-teste"})
    agora = kw.pop("agora", T0)
    relogio = kw.pop("relogio", lambda: agora)
    sv = ServicoCasador(sessoes, t, cfg, n, cliente_http=kw.pop("cliente_http", sem_rede()), relogio=relogio, **kw)
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


def status_de(sessoes, anuncio_id, produto_id=None):
    with sessoes() as s:
        pares_do_anuncio = list(s.scalars(select(Casamento).where(Casamento.anuncio_id == anuncio_id)))
    if produto_id is not None:
        pares_do_anuncio = [par for par in pares_do_anuncio if par.produto_id == produto_id]
    [par] = pares_do_anuncio
    return par.status


def esperas(sessoes):
    """(falhas seguidas, espera até, assinatura) de cada par que tem falha gravada."""
    with sessoes() as s:
        return [
            (c.ia_falhas, c.ia_espera_ate, c.ia_falha_assinatura)
            for c in s.scalars(select(Casamento).order_by(Casamento.anuncio_id, Casamento.produto_id))
            if c.ia_falhas or c.ia_espera_ate is not None or c.ia_falha_assinatura is not None
        ]


def test_desligada_nao_chama(sessoes, config):
    pares(sessoes)
    sv, t, _ = servico(sessoes, config, [])
    assert sv.ciclo() == 0 and t.pedidos == []


def test_sem_chave_nao_chama(sessoes, config):
    configurar(sessoes)
    pares(sessoes)
    sv = ServicoCasador(sessoes, None, config, AvisadorFake(), cliente_http=sem_rede(), relogio=lambda: T0)
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
        with sessoes() as s:
            revisado = s.scalar(select(Casamento.revisado_em).where(Casamento.anuncio_id == anuncio_id))
        assert por_anuncio[anuncio_id].aplicada_em == revisado  # mesmo instante: o selo "pela IA" depende disso


def test_decisao_humana_durante_a_chamada_vence(sessoes, config):
    configurar(sessoes, automatico=True)
    p_id, [a] = pares(sessoes)
    with sessoes() as s, s.begin():
        outro_id = criar_produto(s, "p2").id

    class TransporteQueDecide(TransporteFake):
        def enviar(self, pedido):
            with sessoes() as s, s.begin():
                repo_casamento.trocar(s, a, outro_id, T0)  # usuário troca o produto no meio
            return super().enviar(pedido)

    t = TransporteQueDecide([veredito(False, 99)])
    sv = ServicoCasador(sessoes, t, config.model_copy(update={"openai_api_key": "k"}), AvisadorFake(),
                        cliente_http=sem_rede(), relogio=lambda: T0)
    sv.ciclo()
    assert status_de(sessoes, a, outro_id) is StatusCasamento.CONFIRMADO
    assert status_de(sessoes, a, p_id) is StatusCasamento.IGNORADO
    [av] = avaliacoes(sessoes)
    assert av.produto_id == p_id and av.aplicada_em is None


def test_desfazer_faz_a_ia_reavaliar_mesmo_sem_mudar_os_dados(sessoes, config):
    configurar(sessoes, automatico=True)
    p_id, [a] = pares(sessoes)
    sv, t, _ = servico(sessoes, config, [veredito(True, 99), veredito(True, 70)])
    sv.ciclo()
    assert status_de(sessoes, a) is StatusCasamento.CONFIRMADO
    with sessoes() as s, s.begin():
        repo_casamento.desfazer(s, a, p_id, T0)  # sem mudar título, imagem nem produto
    assert sv.ciclo() == 1 and len(t.pedidos) == 2  # reavaliou com a assinatura igual
    assert status_de(sessoes, a) is StatusCasamento.PENDENTE  # 70 < 90: espera você
    with sessoes() as s:
        assert s.get(Casamento, (a, p_id)).reavaliar is False
    assert sv.ciclo() == 0 and len(t.pedidos) == 2  # não repete


def test_ligar_o_automatico_aplica_avaliacoes_ja_feitas_sem_nova_chamada(sessoes, config):
    configurar(sessoes)  # automático desligado
    _, [a, b, c] = pares(sessoes, 3)
    sv, t, _ = servico(sessoes, config, [veredito(True, 95), veredito(False, 92), veredito(True, 70)])
    assert sv.ciclo() == 3
    assert {status_de(sessoes, i) for i in (a, b, c)} == {StatusCasamento.PENDENTE}
    configurar(sessoes, automatico=True)
    assert sv.ciclo() == 0 and len(t.pedidos) == 3  # nada novo para perguntar
    por_anuncio = {av.anuncio_id: av for av in avaliacoes(sessoes)}
    assert status_de(sessoes, a) is StatusCasamento.CONFIRMADO and por_anuncio[a].aplicada_em is not None
    assert status_de(sessoes, b) is StatusCasamento.IGNORADO and por_anuncio[b].aplicada_em is not None
    assert status_de(sessoes, c) is StatusCasamento.PENDENTE and por_anuncio[c].aplicada_em is None  # abaixo do limite


def test_desfeito_volta_para_a_ia_e_o_automatico_decide_de_novo(sessoes, config):
    configurar(sessoes, automatico=True)
    p_id, [a, b] = pares(sessoes, 2)
    respostas = [veredito(True, 99), veredito(False, 99), veredito(True, 99), veredito(False, 99)]
    sv, _, _ = servico(sessoes, config, respostas)
    sv.ciclo()
    with sessoes() as s, s.begin():
        repo_casamento.desfazer(s, a, p_id, T0)
        repo_casamento.desfazer(s, b, p_id, T0)
    assert sv.ciclo() == 2
    assert status_de(sessoes, a) is StatusCasamento.CONFIRMADO and status_de(sessoes, b) is StatusCasamento.IGNORADO


def test_resposta_fora_do_formato_nao_grava_e_volta(sessoes, config):
    configurar(sessoes)
    pares(sessoes)
    ruim = Bruta(json.dumps({"mesmo_produto": True, "confianca": 150, "motivo": "x"}), 10, 1)
    relogio = Relogio()
    sv, _, _ = servico(sessoes, config, [ruim, veredito()], relogio=relogio)
    sv.ciclo()
    assert avaliacoes(sessoes) == []
    with sessoes() as s:
        assert [c.ok for c in s.scalars(select(ChamadaIA))] == [True]  # a chamada saiu; o formato é do casador
    relogio.avancar(hours=1)
    sv.ciclo()
    assert len(avaliacoes(sessoes)) == 1


def test_tres_erros_seguidos_encerram_o_ciclo(sessoes, config):
    configurar(sessoes)
    pares(sessoes, 5)
    sv, t, av = servico(sessoes, config, [ErroIA("OpenAI 500")] * 3)
    assert sv.ciclo() == 0 and len(t.pedidos) == 3
    [dados] = av.dados(TipoAviso.IA_FALHAS_SEGUIDAS)
    assert dados.linhas == ("3 chamadas seguidas falharam; a rodada parou", "Última: OpenAI 500")
    assert TipoAviso.IA_RODADA_CONCLUIDA not in av.tipos()


def test_chave_invalida_pausa_e_avisa(sessoes, config):
    configurar(sessoes)
    pares(sessoes, 2)
    sv, t, av = servico(sessoes, config, [ChaveInvalida("chave recusada pela OpenAI (401)")])
    sv.ciclo()
    with sessoes() as s:
        estado = repo.obter_estado(s, coletor=COLETOR_CASADOR)
    assert estado.estado is EstadoColetorTipo.PAUSADO and "401" in estado.motivo
    assert len(t.pedidos) == 1
    assert av.dados(TipoAviso.IA_PAUSADA)[0].linhas == ("Motivo: chave recusada pela OpenAI (401)",)
    assert av.mensagens[0][0] is Destino.ADMIN


def test_sem_orcamento_avisa_com_a_chave_do_periodo(sessoes, config):
    configurar(sessoes, max_chamadas_dia=1)
    pares(sessoes, 3)
    sv, t, av = servico(sessoes, config, [veredito()])
    assert sv.ciclo() == 1 and len(t.pedidos) == 1
    sv.ciclo()
    orcamento = [(c, d) for tipo, c, d in av.avisos if tipo is TipoAviso.IA_SEM_ORCAMENTO]
    assert [c for c, _ in orcamento] == ["dia 13/10", "dia 13/10"]  # o agrupamento é do serviço de avisos
    assert orcamento[0][1].titulo_extra == "dia 13/10" and "chamadas" in orcamento[0][1].linhas[0]
    # dia seguinte: a chamada ok fecha os períodos abertos; estourar de novo abre o dia novo
    sv2, t2, av2 = servico(sessoes, config, [veredito()], agora=T0 + timedelta(days=1))
    assert sv2.ciclo() == 1 and len(t2.pedidos) == 1
    assert (TipoAviso.IA_SEM_ORCAMENTO, "*") in av2.resolvidos
    assert [c for tipo, c, _ in av2.avisos if tipo is TipoAviso.IA_SEM_ORCAMENTO] == ["dia 14/10"]


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


def test_configuracao_invalida_pausa_e_avisa(sessoes, config):
    configurar(sessoes)
    pares(sessoes, 2)
    motivo = "modelo ou esforço inválido em Configurações → IA: model_not_found (model)"
    sv, t, av = servico(sessoes, config, [ConfiguracaoInvalida(motivo)])
    sv.ciclo()
    with sessoes() as s:
        estado = repo.obter_estado(s, coletor=COLETOR_CASADOR)
    assert estado.estado is EstadoColetorTipo.PAUSADO and "model_not_found" in estado.motivo
    assert len(t.pedidos) == 1 and "model_not_found" in av.dados(TipoAviso.IA_PAUSADA)[0].linhas[0]


def test_rodada_com_avaliacao_avisa_conclusao_com_as_contas(sessoes, config):
    configurar(sessoes, automatico=True, confianca_confirmar=90, confianca_ignorar=85)
    pares(sessoes, 3)
    sv, _, av = servico(sessoes, config, [veredito(True, 95), veredito(False, 90), veredito(True, 50)])
    assert sv.ciclo() == 3
    [dados] = av.dados(TipoAviso.IA_RODADA_CONCLUIDA)
    assert dados.linhas == (
        "Avaliados: 3 anúncios em 1 produto", "Confirmados pelo automático: 1", "Ignorados pelo automático: 1", "Esperando você: 1",
    )
    assert dados.acao == "Revise os pendentes em Admin → Casamentos."


def test_rodada_sem_ninguem_esperando_nao_tem_acao(sessoes, config):
    configurar(sessoes, automatico=True)
    pares(sessoes, 1)
    sv, _, av = servico(sessoes, config, [veredito(True, 99)])
    sv.ciclo()
    assert av.dados(TipoAviso.IA_RODADA_CONCLUIDA)[0].acao is None


def test_rodada_sem_avaliacao_nao_avisa(sessoes, config):
    configurar(sessoes)
    sv, _, av = servico(sessoes, config, [])
    assert sv.ciclo() == 0 and av.avisos == []


def test_chamada_ok_resolve_falhas_e_orcamento_e_ciclo_ativo_resolve_a_pausa(sessoes, config):
    configurar(sessoes)
    pares(sessoes, 1)
    sv, _, av = servico(sessoes, config, [veredito()])
    sv.ciclo()
    assert av.resolvidos[0] == (TipoAviso.IA_PAUSADA, CHAVE_GERAL)
    assert (TipoAviso.IA_FALHAS_SEGUIDAS, CHAVE_GERAL) in av.resolvidos
    assert (TipoAviso.IA_SEM_ORCAMENTO, "*") in av.resolvidos


def test_pausado_nao_resolve_a_pausa(sessoes, config):
    configurar(sessoes)
    pares(sessoes)
    with sessoes() as s, s.begin():
        repo.pausar(s, "pausado no admin", T0, COLETOR_CASADOR)
    sv, _, av = servico(sessoes, config, [])
    sv.ciclo()
    assert av.resolvidos == []


def test_pares_que_falham_nao_travam_a_fila(sessoes, config):
    configurar(sessoes)
    _, ids = pares(sessoes, 5)
    sv, t, _ = servico(sessoes, config, [ErroIA("OpenAI 500")] * 3 + [veredito(), veredito()])
    assert sv.ciclo() == 0 and len(t.pedidos) == 3
    assert sv.ciclo() == 2  # os 3 que falharam esperam; os de trás andam
    assert {av.anuncio_id for av in avaliacoes(sessoes)} == set(ids[3:])


def test_espera_crescente_depois_de_falhar(sessoes, config):
    configurar(sessoes)
    pares(sessoes)
    relogio = Relogio()
    sv, t, _ = servico(sessoes, config, [ErroIA("OpenAI 500")] * 4, relogio=relogio)
    sv.ciclo()
    relogio.avancar(minutes=59)
    sv.ciclo()
    assert len(t.pedidos) == 1
    relogio.avancar(minutes=1)  # 1 h
    sv.ciclo()
    assert len(t.pedidos) == 2
    relogio.avancar(hours=5, minutes=59)
    sv.ciclo()
    assert len(t.pedidos) == 2
    relogio.avancar(minutes=1)  # 6 h
    sv.ciclo()
    assert len(t.pedidos) == 3
    relogio.avancar(hours=24)  # 24 h
    sv.ciclo()
    assert len(t.pedidos) == 4
    assert esperas(sessoes)[0][0] == 4  # limite de 24 h a partir daqui


def test_espera_maxima_e_24_horas(sessoes, config):
    configurar(sessoes)
    pares(sessoes)
    relogio = Relogio()
    sv, t, _ = servico(sessoes, config, [ErroIA("OpenAI 500")] * 6, relogio=relogio)
    for horas in (0, 1, 6, 24, 24):
        relogio.avancar(hours=horas)
        sv.ciclo()
    assert len(t.pedidos) == 5
    relogio.avancar(hours=23, minutes=59)
    sv.ciclo()
    assert len(t.pedidos) == 5
    relogio.avancar(minutes=1)
    sv.ciclo()
    assert len(t.pedidos) == 6


def test_dados_mudados_tiram_o_par_da_espera(sessoes, config):
    configurar(sessoes)
    _, [a] = pares(sessoes)
    sv, t, _ = servico(sessoes, config, [ErroIA("OpenAI 500"), veredito()])
    sv.ciclo()
    sv.ciclo()
    assert len(t.pedidos) == 1
    with sessoes() as s, s.begin():
        s.get(AnuncioAmazon, a).titulo = "Título novo"
    assert sv.ciclo() == 1 and esperas(sessoes) == []


def test_sucesso_limpa_a_falha(sessoes, config):
    configurar(sessoes)
    pares(sessoes)
    relogio = Relogio()
    sv, _, _ = servico(sessoes, config, [ErroIA("OpenAI 500"), veredito()], relogio=relogio)
    sv.ciclo()
    assert len(esperas(sessoes)) == 1
    relogio.avancar(hours=1)
    assert sv.ciclo() == 1 and esperas(sessoes) == []


def test_espera_sobrevive_a_reinicio_do_casador(sessoes, config):
    configurar(sessoes)
    pares(sessoes)
    relogio = Relogio()
    sv, t, _ = servico(sessoes, config, [ErroIA("OpenAI 500")], relogio=relogio)
    sv.ciclo()
    assert len(t.pedidos) == 1
    relogio.avancar(minutes=59)
    novo, t2, _ = servico(sessoes, config, [veredito()], relogio=relogio)  # container reiniciado
    assert novo.ciclo() == 0 and t2.pedidos == []
    relogio.avancar(minutes=1)
    assert novo.ciclo() == 1 and len(t2.pedidos) == 1 and esperas(sessoes) == []


def test_falhas_continuam_contando_depois_do_reinicio(sessoes, config):
    configurar(sessoes)
    pares(sessoes)
    relogio = Relogio()
    sv, _, _ = servico(sessoes, config, [ErroIA("OpenAI 500")], relogio=relogio)
    sv.ciclo()
    relogio.avancar(hours=1)
    novo, _, _ = servico(sessoes, config, [ErroIA("OpenAI 500")], relogio=relogio)
    novo.ciclo()
    [(n, ate, _)] = esperas(sessoes)
    assert n == 2 and ate == relogio.agora + timedelta(hours=6)


def test_erros_de_formato_nao_encerram_o_ciclo(sessoes, config):
    configurar(sessoes)
    pares(sessoes, 4)
    ruim = Bruta(json.dumps({"mesmo_produto": "sim", "confianca": 90, "motivo": "x"}), 10, 1)
    sv, t, _ = servico(sessoes, config, [ruim, ruim, ruim, veredito()])
    assert sv.ciclo() == 1 and len(t.pedidos) == 4
    assert len(esperas(sessoes)) == 3


def test_excecao_inesperada_num_par_nao_derruba_o_lote(sessoes, config, monkeypatch, caplog):
    from tcg_sniper.casador import servico as modulo

    configurar(sessoes)
    pares(sessoes, 2)
    original = modulo.avaliar_par
    chamadas = []

    def avaliar_par(*args, **kw):
        chamadas.append(1)
        if len(chamadas) == 1:
            raise RuntimeError("quebrou sk-teste")
        return original(*args, **kw)

    monkeypatch.setattr(modulo, "avaliar_par", avaliar_par)
    sv, t, _ = servico(sessoes, config, [veredito()])
    assert sv.ciclo() == 1 and len(esperas(sessoes)) == 1 and len(t.pedidos) == 1
    assert "RuntimeError" in caplog.text
    assert sv.ciclo() == 0 and len(chamadas) == 2  # o par que quebrou espera


def test_erro_no_ciclo_nao_repete_no_passo_seguinte(sessoes, config):
    configurar(sessoes, intervalo_min=10)
    passos = []
    sv, _, _ = servico(sessoes, config, [], dormir=lambda _s: passos.append(1) or (len(passos) >= 3 and sv.parar()))
    tentativas = []

    def ciclo():
        tentativas.append(1)
        raise RuntimeError("falhou")

    sv.ciclo = ciclo
    sv.rodar()
    assert len(passos) == 3 and len(tentativas) == 1  # o relógio não andou 10 min: não tenta de novo


def test_automatico_grava_a_origem_automatico_ia(sessoes, config):
    configurar(sessoes, automatico=True, confianca_confirmar=90)
    _, [a] = pares(sessoes)
    sv, _, _ = servico(sessoes, config, [veredito(True, 95)])
    sv.ciclo()
    with sessoes() as s:
        assert s.scalar(select(Casamento.origem).where(Casamento.anuncio_id == a)) is OrigemCasamento.AUTOMATICO_IA


def test_nao_avalia_pendente_antigo_de_produto_ja_casado(sessoes, config):
    configurar(sessoes)
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Caixa Alfa")
        casado = criar_anuncio(s, "B0CASADO", produto=p, status=StatusCasamento.CONFIRMADO)
        s.get(Casamento, (casado.id, p.id)).revisado_em = T0
        criar_anuncio(s, "B1ANTIGO", produto=p, agora=T0 - timedelta(days=1))
    sv, t, _ = servico(sessoes, config, [])
    assert sv.ciclo() == 0 and t.pedidos == []


def test_anuncio_ignorado_em_a_e_achado_na_busca_de_b_e_avaliado_para_b(sessoes, config):
    configurar(sessoes)
    with sessoes() as s, s.begin():
        colecionador = criar_produto(s, "a", nome="Caixa Colecionador")
        jogo = criar_produto(s, "b", nome="Caixa de Jogo")
        anuncio = criar_anuncio(
            s, "B0JOGO0001", produto=colecionador, status=StatusCasamento.IGNORADO, origem=OrigemCasamento.AUTOMATICO_IA
        )
        repo_casamento.registrar_visto(s, anuncio.id, jogo.id, T0)
        esperado = (anuncio.id, jogo.id)
    sv, _, _ = servico(sessoes, config, [veredito(True, 95)])
    assert sv.ciclo() == 1
    [av] = avaliacoes(sessoes)
    assert (av.anuncio_id, av.produto_id) == esperado


def test_par_outro_confirmado_fica_fora_da_ia(sessoes, config):
    configurar(sessoes)
    with sessoes() as s, s.begin():
        p, q = criar_produto(s, "p"), criar_produto(s, "q")
        anuncio = criar_anuncio(s, "B0Q0000001", produto=q, status=StatusCasamento.CONFIRMADO)
        repo_casamento.registrar_visto(s, anuncio.id, p.id, T0)
    sv, t, _ = servico(sessoes, config, [])
    assert sv.ciclo() == 0 and t.pedidos == []


def test_automatico_nao_confirma_anuncio_que_ficou_confirmado_em_outro_produto(sessoes, config):
    configurar(sessoes, automatico=True)
    p_id, [a] = pares(sessoes)
    with sessoes() as s, s.begin():
        q_id = criar_produto(s, "q").id

    class TransporteQueConfirmaOutro(TransporteFake):
        def enviar(self, pedido):
            with sessoes() as s, s.begin():
                repo_casamento.confirmar(s, a, q_id, T0)  # você confirma para q enquanto a IA responde
                par = s.get(Casamento, (a, p_id))  # e uma busca atrasada deixou o par de p pendente (corrida)
                par.status, par.origem, par.revisado_em = StatusCasamento.PENDENTE, None, None
            return super().enviar(pedido)

    t = TransporteQueConfirmaOutro([veredito(True, 99)])
    sv = ServicoCasador(sessoes, t, config.model_copy(update={"openai_api_key": "k"}), AvisadorFake(),
                        cliente_http=sem_rede(), relogio=lambda: T0)
    sv.ciclo()
    assert status_de(sessoes, a, q_id) is StatusCasamento.CONFIRMADO
    assert status_de(sessoes, a, p_id) is StatusCasamento.PENDENTE
    [av] = avaliacoes(sessoes)
    assert av.aplicada_em is None


def test_reavaliar_produto_casado_reavalia_tambem_os_pares_antigos(sessoes, config):
    configurar(sessoes)
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Caixa Alfa")
        casado = criar_anuncio(s, "B0CASADO", produto=p, status=StatusCasamento.CONFIRMADO)
        s.get(Casamento, (casado.id, p.id)).revisado_em = T0
        criar_anuncio(s, "B1ANTIGO", produto=p, agora=T0 - timedelta(days=1))
        p_id = p.id
    sv, t, _ = servico(sessoes, config, [veredito(False, 95)])
    assert sv.ciclo() == 0  # so_descoberta: o antigo de produto casado fica de fora
    with sessoes() as s, s.begin():
        assert repo_casamento.reavaliar_produto(s, p_id, T0) == 1
    assert sv.ciclo() == 1 and len(t.pedidos) == 1


# Regra de idioma (2026-10-19, revista): português preferido; inglês casa quando o produto não tem
# português confirmado; japonês e outros idiomas nunca são confirmados pelo automático.


def veredito_idioma(idioma, mesmo=True, confianca=95, motivo="mesma caixa"):
    dados = {"mesmo_produto": mesmo, "confianca": confianca, "motivo": motivo, "idioma_anuncio": idioma}
    return Bruta(json.dumps(dados), 1000, 100)


def produto_com_confirmado(sessoes, idioma_confirmado):
    """Produto com um anúncio confirmado (avaliado com `idioma_confirmado`, ou sem avaliação se "sem") e um
    anúncio pendente. Devolve (produto, confirmado, pendente)."""
    with sessoes() as s, s.begin():
        p = criar_produto(s, "p1", nome="Caixa Alfa")
        conf = criar_anuncio(s, "BCONF", produto=p, status=StatusCasamento.CONFIRMADO, origem=OrigemCasamento.MANUAL)
        if idioma_confirmado != "sem":
            repo_ia.gravar_avaliacao(
                s, anuncio_id=conf.id, produto_id=p.id, mesmo_produto=True, confianca=99, motivo="m", modelo="x",
                assinatura=assinatura(conf, p), sem_imagem=True, chamada_id=None, agora=T0,
                idioma_anuncio=idioma_confirmado,
            )
        pend = criar_anuncio(s, "BPEND", produto=p)
        return p.id, conf.id, pend.id


def test_ingles_confirmado_quando_o_produto_nao_tem_portugues(sessoes, config):
    configurar(sessoes, automatico=True, confianca_confirmar=90, confianca_ignorar=90)
    _, [a] = pares(sessoes)
    sv, t, _ = servico(sessoes, config, [veredito_idioma("en")])
    assert sv.ciclo() == 1
    assert status_de(sessoes, a) is StatusCasamento.CONFIRMADO
    [av] = avaliacoes(sessoes)
    assert av.idioma_anuncio == "en" and av.aplicada_em is not None
    assert "- já tem anúncio em português confirmado: não" in t.pedidos[0].texto


def test_ingles_com_so_ingles_confirmado_tambem_confirma(sessoes, config):
    configurar(sessoes, automatico=True, confianca_confirmar=90, confianca_ignorar=90)
    p, _, pend = produto_com_confirmado(sessoes, "en")
    sv, _, _ = servico(sessoes, config, [veredito_idioma("en")])
    sv.ciclo()
    assert status_de(sessoes, pend, p) is StatusCasamento.CONFIRMADO


def test_ingles_fica_pendente_quando_o_produto_tem_portugues_confirmado(sessoes, config):
    configurar(sessoes, automatico=True, confianca_confirmar=90, confianca_ignorar=90)
    p, conf, pend = produto_com_confirmado(sessoes, "pt")
    sv, t, _ = servico(sessoes, config, [veredito_idioma("en", True, 99)])
    assert sv.ciclo() == 1
    assert status_de(sessoes, pend, p) is StatusCasamento.PENDENTE
    assert status_de(sessoes, conf, p) is StatusCasamento.CONFIRMADO
    av = repo_ia_avaliacao(sessoes, pend, p)
    assert av.idioma_anuncio == "en" and av.aplicada_em is None
    assert "- já tem anúncio em português confirmado: sim" in t.pedidos[0].texto


def test_ingles_fica_pendente_quando_o_confirmado_nao_tem_idioma_registrado(sessoes, config):
    configurar(sessoes, automatico=True, confianca_confirmar=90, confianca_ignorar=90)
    p, _, pend = produto_com_confirmado(sessoes, "sem")
    sv, t, _ = servico(sessoes, config, [veredito_idioma("en", True, 99)])
    sv.ciclo()
    assert status_de(sessoes, pend, p) is StatusCasamento.PENDENTE
    assert "- já tem anúncio em português confirmado: não se sabe" in t.pedidos[0].texto


def test_ingles_diferente_continua_ignorado_mesmo_com_portugues_confirmado(sessoes, config):
    configurar(sessoes, automatico=True, confianca_confirmar=90, confianca_ignorar=90)
    p, _, pend = produto_com_confirmado(sessoes, "pt")
    sv, _, _ = servico(sessoes, config, [veredito_idioma("en", False, 97, "outra coleção")])
    sv.ciclo()
    assert status_de(sessoes, pend, p) is StatusCasamento.IGNORADO


def test_portugues_confirmado_depois_nao_desfaz_o_ingles(sessoes, config):
    configurar(sessoes, automatico=True, confianca_confirmar=90, confianca_ignorar=90)
    p, conf, pend = produto_com_confirmado(sessoes, "en")
    sv, _, _ = servico(sessoes, config, [veredito_idioma("pt")])
    sv.ciclo()
    assert status_de(sessoes, pend, p) is StatusCasamento.CONFIRMADO
    assert status_de(sessoes, conf, p) is StatusCasamento.CONFIRMADO  # o inglês fica: quem desfaz é o usuário


def test_japones_e_outro_idioma_nunca_sao_confirmados(sessoes, config):
    configurar(sessoes, automatico=True, confianca_confirmar=90, confianca_ignorar=90)
    _, ids = pares(sessoes, 2)
    sv, _, _ = servico(sessoes, config, [veredito_idioma("ja", True, 99), veredito_idioma("outro", True, 99)])
    assert sv.ciclo() == 2
    for anuncio_id in ids:
        assert status_de(sessoes, anuncio_id) is StatusCasamento.PENDENTE
    assert all(av.aplicada_em is None for av in avaliacoes(sessoes))


def test_avaliacao_antiga_sem_idioma_segue_a_regra_de_antes(sessoes, config):
    """Avaliação de antes da coluna (idioma vazio) aplicada depois: confirma como antes."""
    configurar(sessoes, automatico=True, confianca_confirmar=90, confianca_ignorar=90)
    _, [a] = pares(sessoes)
    sv, _, _ = servico(sessoes, config, [veredito(True, 95)])
    sv.ciclo()
    assert status_de(sessoes, a) is StatusCasamento.CONFIRMADO
    assert avaliacoes(sessoes)[0].idioma_anuncio is None


def repo_ia_avaliacao(sessoes, anuncio_id, produto_id):
    with sessoes() as s:
        return repo_ia.avaliacoes_dos_pares(s, [(anuncio_id, produto_id)])[(anuncio_id, produto_id)]


def test_indefinido_com_portugues_confirmado_nao_confirma_sozinho(sessoes, config):
    configurar(sessoes, automatico=True, confianca_confirmar=90, confianca_ignorar=90)
    p, _, pend = produto_com_confirmado(sessoes, "pt")
    sv, _, _ = servico(sessoes, config, [veredito_idioma("indefinido", True, 99)])
    sv.ciclo()
    assert status_de(sessoes, pend, p) is StatusCasamento.PENDENTE
    assert repo_ia_avaliacao(sessoes, pend, p).aplicada_em is None


def test_indefinido_sem_portugues_confirmado_confirma(sessoes, config):
    configurar(sessoes, automatico=True, confianca_confirmar=90, confianca_ignorar=90)
    _, [a] = pares(sessoes)
    sv, _, _ = servico(sessoes, config, [veredito_idioma("indefinido", True, 99)])
    sv.ciclo()
    assert status_de(sessoes, a) is StatusCasamento.CONFIRMADO
