import io
from decimal import Decimal

import httpx
import pytest
from fakes import T0, criar_anuncio, criar_produto
from PIL import Image, ImageFile

from tcg_sniper.db.models import AnuncioAmazon, Envio, Oportunidade, ProdutoLiga, StatusCasamento
from tcg_sniper.manutencao import imagens


def _png(lado=1200) -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", (lado, lado // 2), (200, 30, 30)).save(saida, "PNG")
    return saida.getvalue()


class EnviadorFalso:
    def __init__(self, falhar_em=()):
        self.gravados: dict[str, tuple[bytes, str, str]] = {}
        self.falhar_em = set(falhar_em)

    def enviar_bytes(self, dados: bytes, chave: str, tipo: str, cache: str) -> None:
        if any(chave.startswith(p) for p in self.falhar_em):
            raise OSError("R2 fora")
        self.gravados[chave] = (dados, tipo, cache)


def _http(respostas: dict[str, httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda req: respostas[str(req.url)]))


def _ok_png():
    return httpx.Response(200, content=_png(), headers={"Content-Type": "image/png"})


def criar_oportunidade(s, anuncio, produto, aberta_em):
    op = Oportunidade(
        anuncio_id=anuncio.id, produto_id=produto.id, preco_amazon=Decimal(700), preco_liga=Decimal(1000),
        desconto_pct=Decimal(30), envio=Envio.AMAZON, aberta_em=aberta_em, alertada_em=aberta_em,
        preco_alertado=Decimal(700), menor_preco=Decimal(700),
    )
    s.add(op)
    s.flush()
    return op


def test_para_webp_reduz_e_converte():
    webp = imagens.para_webp(_png(1200))
    imagem = Image.open(io.BytesIO(webp))
    assert imagem.format == "WEBP" and max(imagem.size) == 600


def test_chave_muda_com_a_origem():
    a = imagens.chave_para("produtos", "p1", "https://x.test/a.jpg")
    b = imagens.chave_para("produtos", "p1", "https://x.test/b.jpg")
    assert a.startswith("produtos/p1-") and a.endswith(".webp") and a != b


def test_pendentes_na_ordem_oportunidade_casado_resto(s):
    resto = criar_produto(s, "resto")
    casado = criar_produto(s, "casado")
    com_op = criar_produto(s, "comop")
    inativo = criar_produto(s, "inativo", ativo=False)
    for p in (resto, casado, com_op, inativo):
        p.imagem_url = f"https://liga.test/{p.liga_id}.jpg"
    a_casado = criar_anuncio(s, "B0IMG00001", casado, StatusCasamento.CONFIRMADO)
    a_op = criar_anuncio(s, "B0IMG00002", com_op, StatusCasamento.CONFIRMADO)
    a_pendente = criar_anuncio(s, "B0IMG00003", resto, StatusCasamento.PENDENTE)
    for a in (a_casado, a_op, a_pendente):
        a.imagem_url = f"https://amazon.test/{a.asin}.jpg"
    criar_oportunidade(s, a_op, com_op, aberta_em=T0)
    s.flush()
    alvos = [(a.tipo, a.ident) for a in imagens.pendentes(s, limite=10)]
    assert alvos[:2] == [("produtos", "comop"), ("anuncios", "B0IMG00002")]
    assert set(alvos[2:4]) == {("produtos", "casado"), ("anuncios", "B0IMG00001")}
    assert alvos[4:] == [("produtos", "resto")]  # inativo e anúncio só pendente ficam de fora
    assert len(imagens.pendentes(s, limite=2)) == 2


def test_copiar_lote_grava_e_marca_e_falha_nao_para_o_resto(sessoes):
    with sessoes() as s, s.begin():
        bom = criar_produto(s, "bom")
        bom.imagem_url = "https://liga.test/bom.jpg"
        quebrado = criar_produto(s, "quebrado")
        quebrado.imagem_url = "https://liga.test/quebrado.jpg"
        texto = criar_produto(s, "texto")
        texto.imagem_url = "https://liga.test/texto.jpg"
        ids = bom.id, quebrado.id, texto.id
    http = _http({
        "https://liga.test/bom.jpg": _ok_png(),
        "https://liga.test/quebrado.jpg": httpx.Response(404),
        "https://liga.test/texto.jpg": httpx.Response(200, text="<html>", headers={"Content-Type": "text/html"}),
    })
    enviador = EnviadorFalso()
    resultado = imagens.copiar_lote(sessoes, enviador, http, limite=10, dormir=lambda _s: None)
    assert (resultado.copiadas, resultado.falhas) == (1, 2)
    (chave, (_dados, tipo, cache)), = enviador.gravados.items()
    assert chave.startswith("produtos/bom-") and tipo == "image/webp" and "immutable" in cache
    with sessoes() as s:
        bom, quebrado, texto = (s.get(ProdutoLiga, i) for i in ids)
        assert (bom.imagem_chave, bom.imagem_origem) == (chave, "https://liga.test/bom.jpg")
        assert quebrado.imagem_chave is None and texto.imagem_chave is None


def test_origem_nova_copia_de_novo_com_outra_chave(sessoes):
    with sessoes() as s, s.begin():
        p = criar_produto(s, "troca")
        p.imagem_url, p.imagem_chave, p.imagem_origem = "https://liga.test/nova.jpg", "produtos/troca-velha.webp", \
            "https://liga.test/velha.jpg"
        pid = p.id
    enviador = EnviadorFalso()
    imagens.copiar_lote(sessoes, enviador, _http({"https://liga.test/nova.jpg": _ok_png()}), limite=10,
                        dormir=lambda _s: None)
    with sessoes() as s:
        assert s.get(ProdutoLiga, pid).imagem_origem == "https://liga.test/nova.jpg"
        assert s.get(ProdutoLiga, pid).imagem_chave != "produtos/troca-velha.webp"


def test_r2_fora_conta_falha_e_nao_marca(sessoes):
    with sessoes() as s, s.begin():
        a = criar_anuncio(s, "B0IMGR2001", criar_produto(s, "r2"), StatusCasamento.CONFIRMADO)
        a.imagem_url = "https://amazon.test/r2.jpg"
        aid = a.id
    http = _http({"https://amazon.test/r2.jpg": _ok_png(), "https://liga.test/r2.jpg": _ok_png()})
    resultado = imagens.copiar_lote(sessoes, EnviadorFalso(falhar_em=("anuncios/",)), http, limite=10,
                                    dormir=lambda _s: None)
    assert resultado.falhas == 1
    with sessoes() as s:
        assert s.get(AnuncioAmazon, aid).imagem_chave is None


def test_servico_um_lote_por_hora_e_excecao_nao_derruba(monkeypatch, sessoes, config):
    from datetime import UTC, datetime, timedelta

    from fakes import AvisadorFake

    from tcg_sniper.manutencao.servico import ServicoManutencao

    class Relogio:
        agora = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)

        def __call__(self):
            return self.agora

    chamadas = []

    def falso(*args, **kwargs):
        chamadas.append(1)
        raise RuntimeError("boom")

    monkeypatch.setattr(imagens, "copiar_lote", falso)
    relogio = Relogio()
    servico = ServicoManutencao(
        sessoes, config, AvisadorFake(), None, relogio=relogio, dormir=lambda _: None,
        enviador_imagens=EnviadorFalso(), http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
    )
    servico.tick()
    servico.tick()
    assert len(chamadas) == 1
    relogio.agora += timedelta(hours=1)
    servico.tick()
    assert len(chamadas) == 2


def _tres_produtos(sessoes):
    with sessoes() as s, s.begin():
        for nome in ("a", "b", "c"):
            criar_produto(s, nome).imagem_url = f"https://liga.test/{nome}.jpg"
    return _http({f"https://liga.test/{n}.jpg": _ok_png() for n in "abc"})


def test_prazo_estourado_para_o_lote_no_meio(sessoes):
    http = _tres_produtos(sessoes)
    tempo = iter([0, 0, 0, 1000, 1000, 1000])  # prazo conferido antes de cada item
    resultado = imagens.copiar_lote(sessoes, EnviadorFalso(), http, dormir=lambda _s: None, prazo_s=180,
                                    relogio=lambda: next(tempo))
    assert (resultado.copiadas, resultado.falhas) == (2, 0)


def test_parar_nao_processa_nada(sessoes):
    http = _tres_produtos(sessoes)
    enviador = EnviadorFalso()
    resultado = imagens.copiar_lote(sessoes, enviador, http, dormir=lambda _s: None, parar=lambda: True)
    assert resultado == imagens.Resultado(0, 0) and not enviador.gravados


def test_so_https_inclusive_no_redirecionamento(sessoes):
    http = _http({
        "http://liga.test/x.jpg": _ok_png(),
        "https://liga.test/r.jpg": httpx.Response(302, headers={"Location": "http://liga.test/x.jpg"}),
    })
    for url in ("http://liga.test/x.jpg", "https://liga.test/r.jpg"):
        with pytest.raises(imagens.ErroImagem):
            imagens.baixar(http, url)


def test_servico_pausado_nao_copia_imagens(monkeypatch, sessoes, config):
    from datetime import UTC, datetime

    from fakes import AvisadorFake

    from tcg_sniper.db import repositorio as repo
    from tcg_sniper.db.models import COLETOR_MANUTENCAO
    from tcg_sniper.manutencao.servico import ServicoManutencao

    agora = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
    with sessoes() as s, s.begin():
        repo.pausar(s, "pausado", agora, COLETOR_MANUTENCAO)
    chamadas = []
    monkeypatch.setattr(imagens, "copiar_lote", lambda *a, **k: chamadas.append(1))
    servico = ServicoManutencao(sessoes, config, AvisadorFake(), None, relogio=lambda: agora,
                                dormir=lambda _: None, enviador_imagens=EnviadorFalso())
    servico.tick()
    assert chamadas == []


def test_bucket_das_imagens_igual_ao_dos_backups_desliga_a_copia(config, caplog):
    import logging

    from fakes import AvisadorFake

    from tcg_sniper.manutencao.servico import ServicoManutencao

    igual = config.model_validate({**config.model_dump(), "r2_account_id": "conta", "r2_bucket": "balde",
                                   "r2_bucket_imagens": " balde ", "r2_access_key_id": "a",
                                   "r2_secret_access_key": "b"})
    assert not igual.imagens_configuradas
    from tcg_sniper.manutencao.r2 import criar_enviador_imagens
    assert criar_enviador_imagens(igual) is None
    servico = ServicoManutencao(None, igual, AvisadorFake(), None)
    servico.parar()
    servico.inicializar = lambda: None
    with caplog.at_level(logging.WARNING):
        servico.rodar()
    assert "igual ao bucket dos backups" in caplog.text


def test_para_webp_recusa_acima_de_40_megapixels(monkeypatch):
    saida = io.BytesIO()
    Image.new("1", (8000, 5001)).save(saida, "PNG")  # 40,008 MP, arquivo pequeno
    chamadas = []
    monkeypatch.setattr(ImageFile.ImageFile, "load", lambda self: chamadas.append(1))
    with pytest.raises(imagens.ErroImagem, match="grande demais"):
        imagens.para_webp(saida.getvalue())
    assert chamadas == []  # recusada antes de decodificar


def test_falha_fica_de_fora_por_24h_e_nao_segura_a_fila(sessoes):
    with sessoes() as s, s.begin():
        for nome in ("a", "b", "c"):
            criar_produto(s, nome).imagem_url = f"https://liga.test/{nome}.jpg"
    pedidos = []
    respostas = {"https://liga.test/a.jpg": httpx.Response(404), "https://liga.test/b.jpg": httpx.Response(404),
                 "https://liga.test/c.jpg": _ok_png()}

    def responder(req):
        pedidos.append(str(req.url).rsplit("/", 1)[1])
        return respostas[str(req.url)]

    http = httpx.Client(transport=httpx.MockTransport(responder))
    falhas: dict = {}
    agora = [1000.0]
    lote = {"limite": 2, "dormir": lambda _s: None, "relogio": lambda: agora[0], "falhas_recentes": falhas}
    assert imagens.copiar_lote(sessoes, EnviadorFalso(), http, **lote) == imagens.Resultado(0, 2)
    assert pedidos == ["a.jpg", "b.jpg"] and len(falhas) == 2
    pedidos.clear()
    agora[0] += imagens.PAUSA_FALHA_S - 1  # antes de 24 h: só o seguinte da fila
    assert imagens.copiar_lote(sessoes, EnviadorFalso(), http, **lote) == imagens.Resultado(1, 0)
    assert pedidos == ["c.jpg"]
    pedidos.clear()
    agora[0] += 1  # 24 h depois da falha: tenta de novo
    assert imagens.copiar_lote(sessoes, EnviadorFalso(), http, **lote) == imagens.Resultado(0, 2)
    assert pedidos == ["a.jpg", "b.jpg"]


def test_r2_fora_nao_tira_o_item_da_fila(sessoes):
    with sessoes() as s, s.begin():
        criar_produto(s, "r2fora").imagem_url = "https://liga.test/r2fora.jpg"
    falhas: dict = {}
    imagens.copiar_lote(sessoes, EnviadorFalso(falhar_em=("produtos/",)), _http({"https://liga.test/r2fora.jpg":
                        _ok_png()}), limite=10, dormir=lambda _s: None, falhas_recentes=falhas)
    assert falhas == {}


def test_servico_guarda_as_falhas_entre_os_lotes(monkeypatch, sessoes, config):
    from datetime import UTC, datetime, timedelta

    from fakes import AvisadorFake

    from tcg_sniper.manutencao.servico import ServicoManutencao

    class Relogio:
        agora = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)

        def __call__(self):
            return self.agora

    recebidas = []
    monkeypatch.setattr(imagens, "copiar_lote", lambda *a, **k: recebidas.append(k["falhas_recentes"]))
    relogio = Relogio()
    servico = ServicoManutencao(sessoes, config, AvisadorFake(), None, relogio=relogio, dormir=lambda _: None,
                                enviador_imagens=EnviadorFalso(), http=_http({}))
    servico.tick()
    relogio.agora += timedelta(hours=1)
    servico.tick()
    assert len(recebidas) == 2 and recebidas[0] is recebidas[1]


@pytest.mark.parametrize("campo", ["r2_imagens_access_key_id", "r2_imagens_secret_access_key"])
def test_so_uma_chave_propria_das_imagens_avisa(config, caplog, campo):
    import logging

    from fakes import AvisadorFake

    from tcg_sniper.manutencao.servico import ServicoManutencao

    metade = config.model_validate({**config.model_dump(), campo: "so-esta"})
    servico = ServicoManutencao(None, metade, AvisadorFake(), None, enviador_imagens=EnviadorFalso(), http=_http({}))
    servico.parar()
    servico.inicializar = lambda: None
    with caplog.at_level(logging.WARNING):
        servico.rodar()
    assert "Só uma das chaves R2_IMAGENS_* preenchida: usando as chaves dos backups" in caplog.text


def test_as_duas_chaves_proprias_nao_avisam(config, caplog):
    import logging

    from fakes import AvisadorFake

    from tcg_sniper.manutencao.servico import ServicoManutencao

    ambas = config.model_validate({**config.model_dump(), "r2_imagens_access_key_id": "id",
                                   "r2_imagens_secret_access_key": "segredo"})
    servico = ServicoManutencao(None, ambas, AvisadorFake(), None, enviador_imagens=EnviadorFalso(), http=_http({}))
    servico.parar()
    servico.inicializar = lambda: None
    with caplog.at_level(logging.WARNING):
        servico.rodar()
    assert "R2_IMAGENS_*" not in caplog.text
