"""Transporte real: Responses API da OpenAI com resposta em JSON Schema (structured outputs)."""

import openai

from tcg_sniper.ia.modelos import Bruta, ChaveInvalida, ErroIA, Pedido


class TransporteOpenAI:
    def __init__(self, chave: str, timeout_s: float = 60, max_retries: int = 3, base_url: str | None = None):
        # max_retries: o SDK repete 408/409/429/5xx e falhas de conexão com espera crescente
        self._cliente = openai.OpenAI(api_key=chave, timeout=timeout_s, max_retries=max_retries, base_url=base_url)

    def enviar(self, pedido: Pedido) -> Bruta:
        conteudo = [{"type": "input_text", "text": pedido.texto}]
        conteudo += [
            {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64}", "detail": "low"}
            for b64 in pedido.imagens
        ]
        try:
            resposta = self._cliente.responses.create(
                model=pedido.modelo,
                instructions=pedido.instrucoes,
                input=[{"role": "user", "content": conteudo}],
                reasoning={"effort": pedido.esforco},
                text={"format": {"type": "json_schema", "name": pedido.nome_formato, "schema": pedido.formato, "strict": True}},
            )
        except (openai.AuthenticationError, openai.PermissionDeniedError) as erro:
            raise ChaveInvalida(f"chave recusada pela OpenAI ({erro.status_code})") from None
        except openai.RateLimitError as erro:
            if _codigo(erro) == "insufficient_quota":
                raise ChaveInvalida("conta da OpenAI sem crédito (insufficient_quota)") from None
            raise ErroIA("OpenAI 429: limite de requisições") from None
        except openai.APIStatusError as erro:
            raise ErroIA(f"OpenAI {erro.status_code}") from None
        except openai.APIConnectionError as erro:  # inclui timeout
            raise ErroIA(f"sem conexão com a OpenAI: {type(erro).__name__}") from None
        uso = resposta.usage
        return Bruta(resposta.output_text, uso.input_tokens if uso else 0, uso.output_tokens if uso else 0)


def _codigo(erro: openai.APIStatusError) -> str | None:
    corpo = erro.body if isinstance(erro.body, dict) else {}
    interno = corpo.get("error", corpo) if isinstance(corpo, dict) else {}
    return interno.get("code") if isinstance(interno, dict) else None
