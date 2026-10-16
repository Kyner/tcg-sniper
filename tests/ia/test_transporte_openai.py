import json

import httpx
import pytest
import respx

from tcg_sniper.ia.modelos import ChaveInvalida, ErroIA, Pedido
from tcg_sniper.ia.transporte_openai import TransporteOpenAI

URL = "https://api.openai.test/v1/responses"
PEDIDO = Pedido("gpt-5", "low", "inst", "txt", ("QUFB",), "veredito", {"type": "object"})


def transporte():
    return TransporteOpenAI("sk-teste-segredo", max_retries=0, base_url="https://api.openai.test/v1")


def resposta_ok(texto):
    return {
        "id": "resp_1", "object": "response", "created_at": 0, "model": "gpt-5", "status": "completed",
        "output": [{"type": "message", "id": "m1", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": texto, "annotations": []}]}],
        "usage": {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150,
                  "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 10}},
        "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
    }


@respx.mock
def test_envia_texto_imagem_e_formato():
    rota = respx.post(URL).mock(return_value=httpx.Response(200, json=resposta_ok('{"a": 1}')))
    bruta = transporte().enviar(PEDIDO)
    assert (bruta.texto, bruta.tokens_entrada, bruta.tokens_saida) == ('{"a": 1}', 120, 30)
    corpo = json.loads(rota.calls[0].request.content)
    assert corpo["model"] == "gpt-5" and corpo["reasoning"] == {"effort": "low"} and corpo["instructions"] == "inst"
    conteudo = corpo["input"][0]["content"]
    assert conteudo[0] == {"type": "input_text", "text": "txt"}
    assert conteudo[1] == {"type": "input_image", "image_url": "data:image/jpeg;base64,QUFB", "detail": "low"}
    assert corpo["text"]["format"] == {"type": "json_schema", "name": "veredito", "schema": {"type": "object"}, "strict": True}


@respx.mock
@pytest.mark.parametrize("codigo", [401, 403])
def test_chave_recusada(codigo):
    respx.post(URL).mock(return_value=httpx.Response(codigo, json={"error": {"message": "bad key sk-teste-segredo", "code": "invalid_api_key"}}))
    with pytest.raises(ChaveInvalida) as erro:
        transporte().enviar(PEDIDO)
    assert "sk-teste" not in str(erro.value)


@respx.mock
def test_sem_credito_e_chave_invalida():
    respx.post(URL).mock(return_value=httpx.Response(429, json={"error": {"message": "quota", "code": "insufficient_quota", "type": "insufficient_quota"}}))
    with pytest.raises(ChaveInvalida, match="crédito"):
        transporte().enviar(PEDIDO)


@respx.mock
@pytest.mark.parametrize("codigo", [429, 500])
def test_outros_erros(codigo):
    respx.post(URL).mock(return_value=httpx.Response(codigo, json={"error": {"message": "x sk-teste-segredo", "code": "rate_limit_exceeded"}}))
    with pytest.raises(ErroIA) as erro:
        transporte().enviar(PEDIDO)
    assert not isinstance(erro.value, ChaveInvalida) and "sk-teste" not in str(erro.value)
