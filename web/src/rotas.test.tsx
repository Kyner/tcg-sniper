import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { apiFalsa, DASHBOARD_VAZIO, EU_GRUPO, EU_OPERADOR, ok, renderizarEm, respostasOportunidadesVazias, SEM_SESSAO } from "./teste/apoio";

describe("proteção das rotas", () => {
  it("sem sessão, qualquer tela vai para Entrar", async () => {
    apiFalsa({ "GET /api/auth/eu": SEM_SESSAO });
    renderizarEm("/gestao");
    expect(await screen.findByRole("heading", { name: "Entrar" })).toBeInTheDocument();
  });

  it("grupo vê a área de negócio e não vê o menu Gestão", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO), ...respostasOportunidadesVazias() });
    renderizarEm("/");
    expect(await screen.findByRole("heading", { name: "Oportunidades" })).toBeInTheDocument();
    expect(screen.queryAllByRole("link", { name: "Gestão" })).toHaveLength(0);
    expect(screen.getAllByRole("link", { name: "Negócio" }).length).toBeGreaterThan(0);
  });

  it("grupo em /gestao vai para Sem acesso", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO) });
    renderizarEm("/gestao");
    expect(await screen.findByRole("heading", { name: "Sem acesso" })).toBeInTheDocument();
  });

  it("operador entra na gestão: menu com as telas novas e sem os itens que não pode", async () => {
    apiFalsa({ ...DASHBOARD_VAZIO, "GET /api/auth/eu": ok(EU_OPERADOR), "GET /api/gestao/menu": ok({ casamentos_esperando: 0 }) });
    renderizarEm("/gestao");
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Usuários/ })).not.toBeInTheDocument();
    for (const link of screen.getAllByRole("link", { name: "Serviços" })) {
      expect(link).toHaveAttribute("href", "/gestao/servicos");
    }
    expect(screen.getAllByRole("link", { name: /Casamentos/ })).toHaveLength(1);
    expect(screen.getAllByRole("link", { name: "Catálogo" })).toHaveLength(1);
  });

  it("API fora: Sistema indisponível, e Tentar de novo volta quando a API responde", async () => {
    apiFalsa({ "GET /api/auth/eu": ["rede-fora", ok(EU_GRUPO)], ...respostasOportunidadesVazias() });
    renderizarEm("/");
    expect(await screen.findByRole("heading", { name: "Sistema indisponível" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("heading", { name: "Oportunidades" })).toBeInTheDocument();
  });

  it("Sair encerra a sessão e volta para Entrar", async () => {
    const chamadas = apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO), "POST /api/auth/sair": ok({ ok: true }), ...respostasOportunidadesVazias() });
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
    apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO), ...respostasOportunidadesVazias() });
    renderizarEm("/");
    expect(screen.getByRole("status", { name: "Carregando" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Oportunidades" })).toBeInTheDocument();
  });
});
