import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { apiFalsa, EU_GRUPO, ok, renderizarEm } from "../teste/apoio";
import type { Historico } from "../tipos";

function historico(parcial: Partial<Historico> = {}): Historico {
  return {
    produto: { id: 7, nome: "Final Fantasy - Caixa", edicao: "FIN", imagem: null, url_liga: "https://liga.test/p/7" },
    anuncio: { titulo: "Caixa FF", url: "https://www.amazon.com.br/dp/B0X", imagem: null },
    periodo: "30d", escala: "hora",
    amazon: [{ t: "2026-10-18T10:00:00-03:00", preco: "1299.90", anuncio: "Caixa FF" }],
    liga: [{ t: "2026-10-18T04:00:00-03:00", preco: "1589.00" }],
    liga_medio: [],
    desconto_min_pct: 20,
    faixas: [{ id: 2, inicio: "2026-10-18T10:15:00-03:00", fim: "2026-10-18T13:15:00-03:00", aberta: false, motivo: "preco_subiu" }],
    oportunidades: [{ id: 2, produto: { id: 7, nome: "Final Fantasy - Caixa", imagem: null, ativo: true },
      aberta_em: "2026-10-18T10:15:00-03:00", fechada_em: "2026-10-18T13:35:00-03:00", aberta: false,
      duracao_min: 180, alertas: 2, preco_alertado: "1299.90", menor_preco: "1249.90", preco_liga: "1589.00",
      desconto_pct: "18.20", motivo: "preco_subiu" }],
    recorrencia_30d: 4,
    quase_la: true,
    ...parcial,
  };
}

describe("Produto", () => {
  it("cabeçalho, recorrência, links, quase lá e histórico", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO), "GET /api/produtos/7/historico?periodo=30d": ok(historico()) });
    renderizarEm("/produtos/7?oportunidade=2");
    expect(await screen.findByRole("heading", { name: "Final Fantasy - Caixa" })).toBeInTheDocument();
    expect(screen.getByText("4ª oportunidade em 30 dias")).toBeInTheDocument();
    expect(screen.getByText("quase lá")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ver na Liga" })).toHaveAttribute("href", "https://liga.test/p/7");
    expect(screen.getByRole("link", { name: "Ver na Amazon" })).toHaveAttribute("href", "https://www.amazon.com.br/dp/B0X");
    expect(screen.getByRole("figure", { name: /Curva de preço/ })).toBeInTheDocument();
    const secao = screen.getByRole("region", { name: "Oportunidades deste produto" });
    const tabela = within(secao).getByRole("table");
    expect(within(tabela).getByText("3 h")).toBeInTheDocument();
    expect(within(tabela).getByText("preço subiu")).toBeInTheDocument();
    // No celular a mesma informação vem em lista.
    expect(within(within(secao).getByRole("list")).getByText(/durou 3 h/)).toBeInTheDocument();
  });

  it("sem leituras e sem Liga: textos de vazio; troca de período", async () => {
    apiFalsa({
      "GET /api/auth/eu": ok(EU_GRUPO),
      "GET /api/produtos/7/historico?periodo=30d": ok(historico({ amazon: [], liga: [], oportunidades: [], faixas: [] })),
      "GET /api/produtos/7/historico?periodo=7d": ok(historico({ periodo: "7d" })),
    });
    renderizarEm("/produtos/7");
    expect(await screen.findByText("Ainda não há leituras suficientes para a curva")).toBeInTheDocument();
    expect(screen.getByText("sem preço da Liga no período")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "7 dias" }));
    expect(await screen.findByRole("figure", { name: /1 leituras da Amazon e 1 da Liga/ })).toBeInTheDocument();
  });

  it("produto inexistente: Não encontrada", async () => {
    apiFalsa({
      "GET /api/auth/eu": ok(EU_GRUPO),
      "GET /api/produtos/9/historico?periodo=30d": { status: 404, corpo: { erro: "nao_encontrado", mensagem: "Produto não encontrado." } },
    });
    renderizarEm("/produtos/9");
    expect(await screen.findByRole("heading", { name: /não encontrada/i })).toBeInTheDocument();
  });

  it("erro: alerta com Tentar de novo", async () => {
    apiFalsa({
      "GET /api/auth/eu": ok(EU_GRUPO),
      "GET /api/produtos/7/historico?periodo=30d": { status: 500, corpo: { erro: "interno", mensagem: "Falhou." } },
    });
    renderizarEm("/produtos/7");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tentar de novo" })).toBeInTheDocument();
  });
});
