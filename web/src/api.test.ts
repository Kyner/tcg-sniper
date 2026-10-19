import { describe, expect, it } from "vitest";
import { ApiIndisponivel, chamarApi, ErroApi } from "./api";
import { apiFalsa, ok } from "./teste/apoio";

describe("chamarApi", () => {
  it("devolve o JSON e manda o cookie da mesma origem", async () => {
    const chamadas = apiFalsa({ "POST /api/x": ok({ a: 1 }) });
    expect(await chamarApi("/api/x", { metodo: "POST", corpo: { b: 2 } })).toEqual({ a: 1 });
    expect(chamadas[0]).toMatchObject({ metodo: "POST", caminho: "/api/x", corpo: { b: 2 }, credenciais: "same-origin" });
  });

  it("erro da API vira ErroApi com o código e a mensagem", async () => {
    apiFalsa({ "GET /api/x": { status: 403, corpo: { erro: "sem_permissao", mensagem: "Seu acesso não permite isto." } } });
    const erro = await chamarApi("/api/x").catch((e: unknown) => e);
    expect(erro).toBeInstanceOf(ErroApi);
    expect(erro).toMatchObject({ status: 403, erro: "sem_permissao", message: "Seu acesso não permite isto." });
  });

  it.each([502, 503, 504])("HTTP %i (proxy sem API) vira ApiIndisponivel", async (status) => {
    apiFalsa({ "GET /api/x": { status } });
    await expect(chamarApi("/api/x")).rejects.toBeInstanceOf(ApiIndisponivel);
  });

  it("rede fora vira ApiIndisponivel", async () => {
    apiFalsa({ "GET /api/x": "rede-fora" });
    await expect(chamarApi("/api/x")).rejects.toBeInstanceOf(ApiIndisponivel);
  });
});
