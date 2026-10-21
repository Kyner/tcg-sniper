import io
from decimal import Decimal

import httpx
from fakes import T0, criar_anuncio, criar_produto
from PIL import Image

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
