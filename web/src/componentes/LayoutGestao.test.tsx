import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { apiFalsa, DASHBOARD_VAZIO, EU_ADMIN, EU_OPERADOR, ok, renderizarEm } from "../teste/apoio";

const MENU = { "GET /api/gestao/menu": ok({ casamentos_esperando: 0 }), ...DASHBOARD_VAZIO };

describe("LayoutGestao", () => {
  it("mostra o selo de casamentos esperando no menu", async () => {
    apiFalsa({ ...DASHBOARD_VAZIO, "GET /api/auth/eu": ok(EU_OPERADOR), "GET /api/gestao/menu": ok({ casamentos_esperando: 96 }) });
    renderizarEm("/gestao");
    const item = await screen.findByRole("link", { name: /Casamentos/ });
    expect(item).toHaveAttribute("href", "/gestao/casamentos");
    expect(await screen.findByText("96")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Catálogo" })).toHaveAttribute("href", "/gestao/catalogo");
    expect(screen.getAllByRole("link", { name: "Ofertas" })[0]).toHaveAttribute("href", "/gestao/ofertas");
  });

  it("a ordem do menu e as telas novas no lugar das antigas", async () => {
    apiFalsa({ ...MENU, "GET /api/auth/eu": ok(EU_ADMIN) });
    renderizarEm("/gestao");
    await screen.findByRole("link", { name: "Usuários" });
    const menu = document.querySelector(".drawer-side ul.menu") as HTMLElement;
    const nomes = within(menu).getAllByRole("link").map((a) => a.textContent);
    expect(nomes).toEqual([
      "Dashboard", "Casamentos", "Catálogo", "Ofertas", "Serviços", "Atividade", "Configurações", "Usuários", "Acessos",
      "Documentação da API",
    ]);
    expect(within(menu).getByRole("link", { name: "Serviços" })).toHaveAttribute("href", "/gestao/servicos");
    expect(within(menu).getByRole("link", { name: "Atividade" })).toHaveAttribute("href", "/gestao/atividade");
    expect(within(menu).getByRole("link", { name: "Configurações" })).toHaveAttribute("href", "/gestao/configuracoes");
    for (const a of within(menu).getAllByRole("link")) {
      expect(a.getAttribute("href")).not.toContain(":8000");
      expect(a).not.toHaveAttribute("target", "_blank");
    }
    expect(within(menu).getByRole("link", { name: "Documentação da API" })).toHaveAttribute("href", "/api/docs");
    expect(within(menu).queryByRole("link", { name: "Mensagens" })).not.toBeInTheDocument();
    expect(within(menu).queryByRole("link", { name: "Logs" })).not.toBeInTheDocument();
  });

  it("sem ver_servicos/ver_logs/ver_documentacao_api os itens não aparecem", async () => {
    const tira = ["ver_servicos", "ver_logs", "ver_documentacao_api"];
    const eu = { ...EU_OPERADOR, permissoes: EU_OPERADOR.permissoes.filter((p) => !tira.includes(p)) };
    apiFalsa({ ...MENU, "GET /api/auth/eu": ok(eu) });
    renderizarEm("/gestao");
    await screen.findByRole("link", { name: "Catálogo" });
    expect(screen.queryByRole("link", { name: "Serviços" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Atividade" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Documentação da API" })).not.toBeInTheDocument();
  });

  it("operador sem revisar_casamentos não vê o item", async () => {
    const eu = { ...EU_OPERADOR, permissoes: EU_OPERADOR.permissoes.filter((p) => p !== "revisar_casamentos") };
    apiFalsa({ ...MENU, "GET /api/auth/eu": ok(eu) });
    renderizarEm("/gestao");
    expect(await screen.findByRole("link", { name: "Catálogo" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Casamentos/ })).not.toBeInTheDocument();
  });

  it("Usuários e Acessos só para quem gere", async () => {
    apiFalsa({ ...MENU, "GET /api/auth/eu": ok(EU_ADMIN) });
    renderizarEm("/gestao");
    expect(await screen.findByRole("link", { name: "Usuários" })).toHaveAttribute("href", "/gestao/usuarios");
    expect(screen.getByRole("link", { name: "Acessos" })).toHaveAttribute("href", "/gestao/acessos");
  });

  it("Ofertas segue ver_catalogo, não ver_servicos", async () => {
    const eu = { ...EU_OPERADOR, permissoes: EU_OPERADOR.permissoes.filter((p) => p !== "ver_servicos") };
    apiFalsa({ ...MENU, "GET /api/auth/eu": ok(eu) });
    renderizarEm("/gestao");
    expect((await screen.findAllByRole("link", { name: "Ofertas" })).length).toBeGreaterThan(0);
  });

  it("a gaveta fecha ao trocar de tela", async () => {
    apiFalsa({ ...MENU, "GET /api/auth/eu": ok(EU_OPERADOR), "GET /api/gestao/catalogo?monitorado=todos&pagina=1": ok({ itens: [], total: 0, pagina: 1, por_pagina: 25, categorias: [] }) });
    renderizarEm("/gestao");
    await userEvent.click(await screen.findByRole("button", { name: /Menu da gestão/ }));
    const caixa = document.getElementById("menu-gestao") as HTMLInputElement;
    expect(caixa.checked).toBe(true);
    await userEvent.click(screen.getByRole("link", { name: "Catálogo" }));
    expect(await screen.findByRole("heading", { name: "Catálogo" })).toBeInTheDocument();
    expect(caixa.checked).toBe(false);
  });

  it("o botão do menu no celular recebe foco e abre/fecha com Enter e Espaço", async () => {
    apiFalsa({ ...MENU, "GET /api/auth/eu": ok(EU_OPERADOR) });
    renderizarEm("/gestao");
    const botao = await screen.findByRole("button", { name: /Menu da gestão/ });
    const caixa = document.getElementById("menu-gestao") as HTMLInputElement;
    botao.focus();
    expect(botao).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(caixa.checked).toBe(true);
    await userEvent.keyboard(" ");
    expect(caixa.checked).toBe(false);
  });

  it("o botão do menu no celular diz se a gaveta está aberta e qual ela é", async () => {
    apiFalsa({ ...MENU, "GET /api/auth/eu": ok(EU_OPERADOR) });
    renderizarEm("/gestao");
    const botao = await screen.findByRole("button", { name: /Menu da gestão/ });
    expect(botao).toHaveAttribute("aria-expanded", "false");
    const alvo = botao.getAttribute("aria-controls");
    expect(alvo).toBeTruthy();
    expect(document.getElementById(alvo!)).toContainElement(screen.getByRole("link", { name: "Catálogo" }));
    await userEvent.click(botao);
    expect(botao).toHaveAttribute("aria-expanded", "true");
  });

  it("rota de casamentos sem a permissão vai para Sem acesso", async () => {
    const eu = { ...EU_OPERADOR, permissoes: EU_OPERADOR.permissoes.filter((p) => p !== "revisar_casamentos") };
    apiFalsa({ ...MENU, "GET /api/auth/eu": ok(eu) });
    renderizarEm("/gestao/casamentos");
    expect(await screen.findByRole("heading", { name: "Sem acesso" })).toBeInTheDocument();
  });
});
