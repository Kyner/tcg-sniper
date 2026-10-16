"""Transporte real: Responses API da OpenAI com resposta em JSON Schema (structured outputs).

As mensagens de erro levam só o status, o `code` e o `param` do corpo do erro e nomes de exceção:
nunca a mensagem da OpenAI nem o corpo (que podem ecoar a chave)."""

import openai

from tcg_sniper.ia.modelos import Bruta, ChaveInvalida, ConfiguracaoInvalida, ErroIA, Pedido

CAMPO_MAX = 60
PARAMS_DE_CONFIGURACAO = ("reasoning", "text")


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
            if _campo(erro, "code") == "insufficient_quota":
                raise ChaveInvalida("conta da OpenAI sem crédito (insufficient_quota)") from None
            raise ErroIA("OpenAI 429: limite de requisições") from None
        except openai.APIStatusError as erro:
            if _configuracao_invalida(erro):
                raise ConfiguracaoInvalida(f"modelo ou esforço inválido em Configurações → IA: {_detalhe(erro)}") from None
            raise ErroIA(f"OpenAI {erro.status_code}: {_detalhe(erro)}") from None
        except openai.APIConnectionError as erro:  # inclui timeout
            raise ErroIA(f"sem conexão com a OpenAI: {type(erro).__name__}") from None
        except openai.APIError as erro:  # resposta que o SDK não conseguiu ler, entre outros
            raise ErroIA(f"erro da OpenAI: {type(erro).__name__}") from None
        uso = resposta.usage
        return Bruta(resposta.output_text, uso.input_tokens if uso else 0, uso.output_tokens if uso else 0)


def _configuracao_invalida(erro: openai.APIStatusError) -> bool:
    if isinstance(erro, openai.NotFoundError):  # model_not_found
        return True
    if not isinstance(erro, openai.BadRequestError):
        return False
    param = _campo(erro, "param") or ""
    return param == "model" or param.startswith(PARAMS_DE_CONFIGURACAO)


def _detalhe(erro: openai.APIStatusError) -> str:
    """`code (param)` do corpo do erro; nunca a mensagem."""
    codigo, param = _campo(erro, "code"), _campo(erro, "param")
    texto = codigo or "sem código"
    return f"{texto} ({param})" if param else texto


def _campo(erro: openai.APIStatusError, nome: str) -> str | None:
    corpo = erro.body if isinstance(erro.body, dict) else {}
    interno = corpo.get("error", corpo)
    valor = interno.get(nome) if isinstance(interno, dict) else None
    return valor[:CAMPO_MAX] if isinstance(valor, str) and valor else None
