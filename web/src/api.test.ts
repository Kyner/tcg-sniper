import { describe, expect, it, vi } from "vitest";
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

  it("HTTP 500 sem corpo (proxy do Vite sem API) vira ApiIndisponivel", async () => {
    apiFalsa({ "GET /api/x": { status: 500 } });
    await expect(chamarApi("/api/x")).rejects.toBeInstanceOf(ApiIndisponivel);
  });

  it("HTTP 500 com corpo que não é JSON vira ApiIndisponivel", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("Internal Server Error", { status: 500 })));
    await expect(chamarApi("/api/x")).rejects.toBeInstanceOf(ApiIndisponivel);
  });

  it("HTTP 500 no formato da API continua ErroApi", async () => {
    apiFalsa({ "GET /api/x": { status: 500, corpo: { erro: "erro_interno", mensagem: "Erro interno." } } });
    await expect(chamarApi("/api/x")).rejects.toMatchObject({ status: 500, erro: "erro_interno" });
  });

  it("rede fora vira ApiIndisponivel", async () => {
    apiFalsa({ "GET /api/x": "rede-fora" });
    await expect(chamarApi("/api/x")).rejects.toBeInstanceOf(ApiIndisponivel);
  });
});
