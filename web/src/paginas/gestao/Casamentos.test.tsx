import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { apiFalsa, EU_OPERADOR, ok, renderizarEm } from "../../teste/apoio";

const ITEM = {
  id: 5, nome: "Lair of the Hydra", nome_en: "Lair of the Hydra", imagem: null, categoria: "Booster",
  preco_liga: "1589.00", pendentes: 3, confirmados: 1, ignorados: 0, em_outro: 0, ia_sugere: 2,
  situacao: "esperando_decisao",
};
const LISTA = {
  itens: [ITEM, { ...ITEM, id: 6, nome: "Goblin Box" }], total: 2, pagina: 1, por_pagina: 20,
  categorias: ["Booster", "Caixa"],
};
const VAZIA = { itens: [], total: 0, pagina: 1, por_pagina: 20, categorias: ["Booster"] };
const BASE = "situacao=esperando_decisao&ordem=preco_liga&pagina=1";
const L = (q: string) => `GET /api/gestao/casamentos?${q}`;
const base = { "GET /api/auth/eu": ok(EU_OPERADOR), "GET /api/gestao/menu": ok({ casamentos_esperando: 2 }) };

describe("Casamentos", () => {
  it("lista os produtos com preço e link da revisão com a mesma query", async () => {
    apiFalsa({ ...base, [L(BASE)]: ok(LISTA) });
    renderizarEm("/gestao/casamentos");
    const tabela = await screen.findByRole("table");
    const link = within(tabela).getByRole("link", { name: /Lair of the Hydra/ });
    expect(link).toHaveAttribute("href", "/gestao/casamentos/5?situacao=esperando_decisao&ordem=preco_liga&pagina=1");
    expect(within(tabela).getAllByText("R$ 1.589,00").length).toBeGreaterThan(0);
  });

  it("cartão leva à revisão com a mesma query", async () => {
    apiFalsa({ ...base, [L("busca=lair&situacao=esperando_decisao&ordem=preco_liga&pagina=3")]: ok(LISTA) });
    renderizarEm("/gestao/casamentos?busca=lair&pagina=3");
    const lista = await screen.findByRole("list", { name: "Produtos" });
    expect(within(lista).getByRole("link", { name: /Lair of the Hydra/ })).toHaveAttribute(
      "href", "/gestao/casamentos/5?busca=lair&situacao=esperando_decisao&ordem=preco_liga&pagina=3",
    );
  });

  it("aplica filtro sem botão e grava na URL", async () => {
    const chamadas = apiFalsa({
      ...base, [L(BASE)]: ok(LISTA), [L("situacao=todos&ordem=preco_liga&pagina=1")]: ok(LISTA),
    });
    renderizarEm("/gestao/casamentos");
    await screen.findByRole("table");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Situação" }), "todos");
    await waitFor(() =>
      expect(chamadas.some((c) => c.caminho.endsWith("?situacao=todos&ordem=preco_liga&pagina=1"))).toBe(true),
    );
    expect(screen.getByRole("combobox", { name: "Situação" })).toHaveValue("todos");
  });

  it("busca espera o usuário parar de digitar", async () => {
    const chamadas = apiFalsa({
      ...base, [L(BASE)]: ok(LISTA),
      [L("busca=goblin&situacao=esperando_decisao&ordem=preco_liga&pagina=1")]: ok(LISTA),
    });
    renderizarEm("/gestao/casamentos");
    await screen.findByRole("table");
    await userEvent.type(screen.getByRole("searchbox", { name: "Buscar" }), "goblin");
    await waitFor(() => expect(chamadas.some((c) => c.caminho.includes("busca=goblin"))).toBe(true));
    expect(chamadas.filter((c) => c.caminho.includes("casamentos?") && c.caminho.includes("busca="))).toHaveLength(1);
  });

  it("Revisar em sequência abre o primeiro da lista filtrada", async () => {
    apiFalsa({ ...base, [L("situacao=todos&ordem=preco_liga&pagina=1")]: ok(LISTA) });
    renderizarEm("/gestao/casamentos?situacao=todos");
    await screen.findByRole("table");
    expect(screen.getByRole("link", { name: "Revisar em sequência" })).toHaveAttribute(
      "href", "/gestao/casamentos/5?situacao=todos&ordem=preco_liga&pagina=1",
    );
  });

  it("vazio com filtro mostra Limpar filtros", async () => {
    apiFalsa({
      ...base, [L("busca=zzz&situacao=esperando_decisao&ordem=preco_liga&pagina=1")]: ok(VAZIA),
      [L(BASE)]: ok(LISTA),
    });
    renderizarEm("/gestao/casamentos?busca=zzz");
    expect(await screen.findByText("Nenhum produto com esses filtros")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Limpar filtros" }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });

  it("voltar restaura busca, filtros e página", async () => {
    const chamadas = apiFalsa({
      ...base,
      [L("busca=lair&situacao=esperando_decisao&ordem=preco_liga&pagina=3")]: ok({ ...LISTA, pagina: 3, total: 50 }),
    });
    renderizarEm("/gestao/casamentos?busca=lair&pagina=3");
    await screen.findByRole("table");
    expect(screen.getByRole("searchbox", { name: "Buscar" })).toHaveValue("lair");
    expect(chamadas.some((c) => c.caminho.includes("pagina=3"))).toBe(true);
    expect(screen.getByText("Página 3 de 3")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByRole("link", { name: /Lair of the Hydra/ })).toHaveAttribute(
      "href", "/gestao/casamentos/5?busca=lair&situacao=esperando_decisao&ordem=preco_liga&pagina=3",
    );
  });

  it("erro mostra alerta com Tentar de novo", async () => {
    apiFalsa({
      ...base,
      [L(BASE)]: [{ status: 500, corpo: { erro: "interno", mensagem: "Erro interno." } }, ok(LISTA)],
    });
    renderizarEm("/gestao/casamentos");
    expect(await screen.findByRole("alert")).toHaveTextContent("Erro interno");
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });
});
