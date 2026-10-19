import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { apiFalsa, EU_GRUPO, EU_OPERADOR, ok, renderizarEm, SEM_SESSAO } from "./teste/apoio";

describe("proteção das rotas", () => {
  it("sem sessão, qualquer tela vai para Entrar", async () => {
    apiFalsa({ "GET /api/auth/eu": SEM_SESSAO });
    renderizarEm("/gestao");
    expect(await screen.findByRole("heading", { name: "Entrar" })).toBeInTheDocument();
  });

  it("grupo vê a área de negócio e não vê o menu Gestão", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO) });
    renderizarEm("/");
    expect(await screen.findByRole("heading", { name: "Área de negócio" })).toBeInTheDocument();
    expect(screen.queryAllByRole("link", { name: "Gestão" })).toHaveLength(0);
    expect(screen.getAllByRole("link", { name: "Negócio" }).length).toBeGreaterThan(0);
  });

  it("grupo em /gestao vai para Sem acesso", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO) });
    renderizarEm("/gestao");
    expect(await screen.findByRole("heading", { name: "Sem acesso" })).toBeInTheDocument();
  });

  it("operador entra na gestão, sem os cartões que não pode", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_OPERADOR) });
    renderizarEm("/gestao");
    expect(await screen.findByRole("heading", { name: "Gestão" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Usuários/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Serviços" })).toHaveAttribute("href", "http://localhost:8000/servicos");
  });

  it("API fora: Sistema indisponível, e Tentar de novo volta quando a API responde", async () => {
    apiFalsa({ "GET /api/auth/eu": ["rede-fora", ok(EU_GRUPO)] });
    renderizarEm("/");
    expect(await screen.findByRole("heading", { name: "Sistema indisponível" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("heading", { name: "Área de negócio" })).toBeInTheDocument();
  });

  it("Sair encerra a sessão e volta para Entrar", async () => {
    const chamadas = apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO), "POST /api/auth/sair": ok({ ok: true }) });
    renderizarEm("/");
    await userEvent.click(await screen.findByRole("button", { name: "Sair" }));
    expect(await screen.findByRole("heading", { name: "Entrar" })).toBeInTheDocument();
    expect(chamadas.some((c) => c.metodo === "POST" && c.caminho === "/api/auth/sair")).toBe(true);
  });

  it("rota desconhecida mostra Página não encontrada", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO) });
    renderizarEm("/nada");
    expect(await screen.findByRole("heading", { name: "Página não encontrada" })).toBeInTheDocument();
  });

  it("Página não encontrada leva ao início de quem está logado", async () => {
    apiFalsa({ "GET /api/auth/eu": ok({ ...EU_OPERADOR, permissoes: ["ver_area_gestao"] }) });
    renderizarEm("/nada");
    expect(await screen.findByRole("link", { name: "Ir para o início" })).toHaveAttribute("href", "/gestao");
  });

  it("carregando é anunciado como status", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO) });
    renderizarEm("/");
    expect(screen.getByRole("status", { name: "Carregando" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Área de negócio" })).toBeInTheDocument();
  });
});
