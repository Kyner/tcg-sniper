// Chamadas à API. Mesma origem: o Caddy (no container) ou o Vite (em desenvolvimento) repassa /api para o
// serviço api. O cookie de sessão é HttpOnly: o front nunca o lê; o navegador manda sozinho.

/** Erro no formato padrão da API: {erro, mensagem}. `message` é a mensagem em português para mostrar. */
export class ErroApi extends Error {
  readonly status: number;
  readonly erro: string;

  constructor(status: number, erro: string, mensagem: string) {
    super(mensagem);
    this.status = status;
    this.erro = erro;
  }
}

/** A API não respondeu (fora do ar, ou o proxy devolveu 502/503/504). */
export class ApiIndisponivel extends Error {
  constructor() {
    super("Sistema indisponível");
  }
}

interface Opcoes {
  metodo?: "GET" | "POST" | "PUT" | "PATCH";
  corpo?: unknown;
}

export async function chamarApi<T>(caminho: string, { metodo = "GET", corpo }: Opcoes = {}): Promise<T> {
  let resposta: Response;
  try {
    resposta = await fetch(caminho, {
      method: metodo,
      credentials: "same-origin",
      headers: corpo === undefined ? undefined : { "Content-Type": "application/json" },
      body: corpo === undefined ? undefined : JSON.stringify(corpo),
    });
  } catch {
    throw new ApiIndisponivel();
  }
  if (resposta.status === 502 || resposta.status === 503 || resposta.status === 504) {
    throw new ApiIndisponivel();
  }
  const dados: unknown = await resposta.json().catch(() => null);
  // 500 sem o JSON da API ({erro, mensagem}) não veio da API: é o proxy do Vite (dev/preview) com a API fora.
  const formatoDaApi = typeof (dados as { erro?: unknown } | null)?.erro === "string";
  if (resposta.status === 500 && !formatoDaApi) {
    throw new ApiIndisponivel();
  }
  if (!resposta.ok) {
    const { erro = "desconhecido", mensagem = "Erro inesperado. Tente de novo." } = (dados ?? {}) as {
      erro?: string;
      mensagem?: string;
    };
    throw new ErroApi(resposta.status, erro, mensagem);
  }
  return dados as T;
}
