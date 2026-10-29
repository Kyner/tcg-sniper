import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { apiFalsa, EU_GRUPO, EU_OPERADOR, ok, renderizarEm } from "../../teste/apoio";

const OFERTA = {
  produto_id: 5, produto: "Aetherdrift Commander", imagem: "https://img.test/a.jpg", preco_liga: "400.00",
  anuncio: { asin: "B0DNV55QBS", titulo: "Anúncio", url: "https://www.amazon.com.br/dp/B0DNV55QBS", imagem: null },
  preco: "275.91", desconto_pct: "28.50", diferenca: "114.01", envio: "fba",
  vendedor: { nome: "Shazaar", envio: "fba" }, confiavel: true, verificado: true, aberta: true,
  risco: null, origem: "automatico_ia", prime: true, importada: true, origem_envio: "Estados Unidos",
  conferido: { preco: "285.99", impostos: "48.26", frete: "30.00" }, coletado_em: "2026-10-20T15:00:00+00:00",
};
const LISTA = { itens: [OFERTA], total: 1, pagina: 1, por_pagina: 50, categorias: ["Caixas", "Decks"], desconto_min_pct: 25 };
const base = { "GET /api/auth/eu": ok(EU_OPERADOR), "GET /api/gestao/menu": ok({ casamentos_esperando: 0 }) };
const LISTAR = "GET /api/gestao/ofertas?pagina=1";

async function tabela() {
  return within(await screen.findByRole("table"));
}

describe("Ofertas", () => {
  it("mostra o produto, o desconto, a diferença e a frase do conferido em uma linha", async () => {
    apiFalsa({ ...base, [LISTAR]: ok(LISTA) });
    renderizarEm("/gestao/ofertas");
    const t = await tabela();
    expect(t.getByRole("link", { name: "Aetherdrift Commander" })).toHaveAttribute("href", "/gestao/produtos/5");
    expect(t.getByRole("img", { name: "Aetherdrift Commander" })).toHaveAttribute("src", "https://img.test/a.jpg");
    expect(t.getByText("28,5%")).toBeInTheDocument();
    expect(t.getByText("R$ 114,01")).toBeInTheDocument();
    const frase = t.getByText("conferido R$ 285,99 com impostos");
    expect(frase.className).toContain("truncate");
    expect(frase.closest("[data-tip]")?.getAttribute("data-tip")).toBe(
      "Conferido no checkout: R$ 285,99 (impostos R$ 48,26 inclusos; frete R$ 30,00 à parte)",
    );
    expect(t.getByRole("link", { name: "R$ 275,91" })).toHaveAttribute("href", OFERTA.anuncio.url);
  });

  it("origem, Prime e importado ficam no tooltip, sem selos empilhados", async () => {
    apiFalsa({ ...base, [LISTAR]: ok(LISTA) });
    renderizarEm("/gestao/ofertas");
    const t = await tabela();
    expect(t.queryByText("Prime")).toBeNull();
    expect(t.queryByText("importado (EUA)")).toBeNull();
    const dica = t.getByText("FBA").closest("[data-tip]")?.getAttribute("data-tip") ?? "";
    expect(dica).toContain("Shazaar");
    expect(dica).toContain("Prime");
    expect(dica).toContain("importado (EUA)");
    expect(dica).toContain("automático pela IA");
    expect(t.getByText("oportunidade")).toBeInTheDocument();
  });

  it("diferença negativa sai com o sinal antes do símbolo e sem preço na Liga sem desconto", async () => {
    apiFalsa({
      ...base,
      [LISTAR]: ok({
        ...LISTA, total: 2,
        itens: [
          { ...OFERTA, diferenca: "-42.00", desconto_pct: "-10.5" },
          { ...OFERTA, produto_id: 6, produto: "Sem Liga", preco_liga: null, desconto_pct: null, diferenca: null, conferido: null },
        ],
      }),
    });
    renderizarEm("/gestao/ofertas");
    const t = await tabela();
    expect(t.getByText("−R$ 42,00")).toBeInTheDocument();
    expect(t.getByText("−10,5%")).toBeInTheDocument();
    expect(t.getByText("não conferido")).toBeInTheDocument();
  });

  it("em risco mostra desde quando e o motivo em uma linha com o detalhe no tooltip", async () => {
    apiFalsa({ ...base, [LISTAR]: ok({ ...LISTA, itens: [{ ...OFERTA, risco: { desde: "2026-10-20T15:00:00+00:00", motivo: "preço subiu" } }] }) });
    renderizarEm("/gestao/ofertas");
    const t = await tabela();
    const selo = t.getByText(/^em risco/);
    expect(selo.className).toContain("truncate");
    expect(selo.closest("[data-tip]")?.getAttribute("data-tip")).toContain("preço subiu");
  });

  it("filtros vão para a URL e para a API", async () => {
    const chamadas = apiFalsa({
      ...base, [LISTAR]: ok(LISTA),
      "GET /api/gestao/ofertas?vendedor=fba&pagina=1": ok(LISTA),
      "GET /api/gestao/ofertas?categoria=Decks&vendedor=fba&pagina=1": ok(LISTA),
    });
    renderizarEm("/gestao/ofertas");
    await tabela();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Vendedor" }), "fba");
    await waitFor(() => expect(chamadas.some((c) => c.caminho === "/api/gestao/ofertas?vendedor=fba&pagina=1")).toBe(true));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Categoria" }), "Decks");
    await waitFor(() => expect(chamadas.some((c) => c.caminho.includes("categoria=Decks&vendedor=fba"))).toBe(true));
  });

  it("o chip de desconto configurado aplica e desfaz o filtro", async () => {
    const chamadas = apiFalsa({ ...base, [LISTAR]: ok(LISTA), "GET /api/gestao/ofertas?desconto_min=25&pagina=1": ok(LISTA) });
    renderizarEm("/gestao/ofertas");
    await tabela();
    const chip = screen.getByRole("button", { name: "≥ desconto configurado (25%)" });
    expect(chip).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(chip);
    await waitFor(() => expect(chamadas.some((c) => c.caminho.includes("desconto_min=25"))).toBe(true));
    await waitFor(() => expect(screen.getByRole("button", { name: "≥ desconto configurado (25%)" })).toHaveAttribute("aria-pressed", "true"));
    await userEvent.click(screen.getByRole("button", { name: "≥ desconto configurado (25%)" }));
    await waitFor(() => expect(chamadas.filter((c) => c.caminho === "/api/gestao/ofertas?pagina=1").length).toBe(2));
  });

  it("lê os filtros da URL", async () => {
    const chamadas = apiFalsa({ ...base, "GET /api/gestao/ofertas?busca=deck&situacao=abertas&ordem=nome&pagina=2": ok({ ...LISTA, pagina: 2, total: 120 }) });
    renderizarEm("/gestao/ofertas?busca=deck&situacao=abertas&ordem=nome&pagina=2");
    await tabela();
    expect(chamadas.some((c) => c.caminho.startsWith("/api/gestao/ofertas?busca=deck"))).toBe(true);
    expect(screen.getByText("Página 2 de 3")).toBeInTheDocument();
  });

  it("sem resultado com filtro oferece limpar; erro oferece tentar de novo", async () => {
    apiFalsa({
      ...base,
      [LISTAR]: [{ status: 500, corpo: { erro: "falha", mensagem: "Deu ruim." } }, ok({ ...LISTA, itens: [], total: 0 })],
    });
    renderizarEm("/gestao/ofertas");
    expect(await screen.findByText("Deu ruim.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByText("Nenhuma oferta no momento")).toBeInTheDocument();
  });

  it("sem resultado com filtros mostra Limpar filtros", async () => {
    const chamadas = apiFalsa({
      ...base, "GET /api/gestao/ofertas?vendedor=fba&pagina=1": ok({ ...LISTA, itens: [], total: 0 }), [LISTAR]: ok(LISTA),
    });
    renderizarEm("/gestao/ofertas?vendedor=fba");
    expect(await screen.findByText("Nenhuma oferta com esses filtros")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Limpar filtros" }));
    await waitFor(() => expect(chamadas.some((c) => c.caminho === "/api/gestao/ofertas?pagina=1")).toBe(true));
  });

  it("página fora do limite mostra a página que a API devolveu", async () => {
    apiFalsa({ ...base, "GET /api/gestao/ofertas?pagina=999": ok({ ...LISTA, pagina: 2, total: 60 }) });
    renderizarEm("/gestao/ofertas?pagina=999");
    await tabela();
    expect(screen.getByText("Página 2 de 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "»" })).toBeDisabled();
  });

  it("sem impostos na conferência a frase não diz 'com impostos'", async () => {
    apiFalsa({ ...base, [LISTAR]: ok({ ...LISTA, itens: [{ ...OFERTA, conferido: { preco: "300.00", impostos: null, frete: null } }] }) });
    renderizarEm("/gestao/ofertas");
    const t = await tabela();
    expect(t.getByText("conferido R$ 300,00")).toBeInTheDocument();
  });

  it("erro esconde a lista antiga, mantém as categorias e oferece Limpar filtros", async () => {
    const chamadas = apiFalsa({
      ...base, [LISTAR]: ok(LISTA),
      "GET /api/gestao/ofertas?vendedor=fba&pagina=1": { status: 400, corpo: { erro: "filtro_invalido", mensagem: "Filtro inválido." } },
    });
    renderizarEm("/gestao/ofertas");
    await tabela();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Vendedor" }), "fba");
    const alerta = await screen.findByRole("alert");
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("option", { name: "Decks" })).toBeInTheDocument();
    await userEvent.click(within(alerta).getByRole("button", { name: "Limpar filtros" }));
    await waitFor(() => expect(chamadas.filter((c) => c.caminho === "/api/gestao/ofertas?pagina=1").length).toBe(2));
  });

  it("quem não tem ver_catalogo não entra", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO) });
    renderizarEm("/gestao/ofertas");
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Ofertas" })).toBeNull());
  });
});
