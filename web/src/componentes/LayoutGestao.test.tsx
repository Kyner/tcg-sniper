import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { apiFalsa, EU_ADMIN, EU_OPERADOR, ok, renderizarEm } from "../teste/apoio";

describe("LayoutGestao", () => {
  it("mostra o selo de casamentos esperando no menu", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_OPERADOR), "GET /api/gestao/menu": ok({ casamentos_esperando: 96 }) });
    renderizarEm("/gestao");
    const item = await screen.findByRole("link", { name: /Casamentos/ });
    expect(item).toHaveAttribute("href", "/gestao/casamentos");
    expect(await screen.findByText("96")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Catálogo" })).toHaveAttribute("href", "/gestao/catalogo");
    expect(screen.getAllByRole("link", { name: "Ofertas" })[0]).toHaveAttribute("href", "http://localhost:8000/ofertas");
  });

  it("operador sem revisar_casamentos não vê o item", async () => {
    const eu = { ...EU_OPERADOR, permissoes: EU_OPERADOR.permissoes.filter((p) => p !== "revisar_casamentos") };
    apiFalsa({ "GET /api/auth/eu": ok(eu), "GET /api/gestao/menu": ok({ casamentos_esperando: 0 }) });
    renderizarEm("/gestao");
    expect(await screen.findByRole("link", { name: "Catálogo" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Casamentos/ })).not.toBeInTheDocument();
  });

  it("Usuários e Acessos só para quem gere", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_ADMIN), "GET /api/gestao/menu": ok({ casamentos_esperando: 0 }) });
    renderizarEm("/gestao");
    expect(await screen.findByRole("link", { name: "Usuários" })).toHaveAttribute("href", "/gestao/usuarios");
    expect(screen.getByRole("link", { name: "Acessos" })).toHaveAttribute("href", "/gestao/acessos");
  });

  it("Ofertas segue ver_catalogo, não ver_servicos", async () => {
    const eu = { ...EU_OPERADOR, permissoes: EU_OPERADOR.permissoes.filter((p) => p !== "ver_servicos") };
    apiFalsa({ "GET /api/auth/eu": ok(eu), "GET /api/gestao/menu": ok({ casamentos_esperando: 0 }) });
    renderizarEm("/gestao");
    expect((await screen.findAllByRole("link", { name: "Ofertas" })).length).toBeGreaterThan(0);
  });

  it("a gaveta fecha ao trocar de tela", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_OPERADOR), "GET /api/gestao/menu": ok({ casamentos_esperando: 0 }), "GET /api/gestao/catalogo?monitorado=todos&pagina=1": ok({ itens: [], total: 0, pagina: 1, por_pagina: 25, categorias: [] }) });
    renderizarEm("/gestao");
    const alternar = (await screen.findByText("☰ Menu da gestão")).closest("label")!;
    await userEvent.click(alternar);
    const caixa = document.getElementById("menu-gestao") as HTMLInputElement;
    expect(caixa.checked).toBe(true);
    await userEvent.click(screen.getByRole("link", { name: "Catálogo" }));
    expect(await screen.findByRole("heading", { name: "Catálogo" })).toBeInTheDocument();
    expect(caixa.checked).toBe(false);
  });

  it("rota de casamentos sem a permissão vai para Sem acesso", async () => {
    const eu = { ...EU_OPERADOR, permissoes: EU_OPERADOR.permissoes.filter((p) => p !== "revisar_casamentos") };
    apiFalsa({ "GET /api/auth/eu": ok(eu), "GET /api/gestao/menu": ok({ casamentos_esperando: 0 }) });
    renderizarEm("/gestao/casamentos");
    expect(await screen.findByRole("heading", { name: "Sem acesso" })).toBeInTheDocument();
  });
});
