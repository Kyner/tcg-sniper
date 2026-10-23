import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { apiFalsa, EU_OPERADOR, ok, renderizarEm } from "../../teste/apoio";

const ITEM = {
  id: 5, nome: "Lair of the Hydra", nome_en: null, imagem: null, categoria: "Booster", monitorado: true,
  preco_liga: "1589.00", lojas: 4, situacao: "casado", pendentes: 0, confirmados: 2, melhor_amazon: "1200.00",
  medio_liga: "1700.00", diferenca_media_pct: "29.41", sem_vendedor_desde: null,
};
const LISTA = {
  itens: [ITEM, { ...ITEM, id: 6, nome: "Goblin Box", monitorado: false }], total: 412, pagina: 1, por_pagina: 25,
  categorias: ["Booster"],
};
const base = { "GET /api/auth/eu": ok(EU_OPERADOR), "GET /api/gestao/menu": ok({ casamentos_esperando: 0 }) };
const LISTAR = "GET /api/gestao/catalogo?monitorado=todos&pagina=1";
const FILTRO = { busca: "", monitorado: "todos", categoria: null, situacao: null, preco_liga: "todos" };
const LISTAR_ESGOTADO = "GET /api/gestao/catalogo?monitorado=todos&preco_liga=esgotado&pagina=1";
const ESGOTADOS = {
  ...LISTA, total: 2,
  itens: [
    { ...ITEM, preco_liga: null, melhor_amazon: "100.00", medio_liga: "200.00", diferenca_media_pct: "50.00",
      sem_vendedor_desde: "2026-10-10T13:00:00+00:00" },
    { ...ITEM, id: 6, nome: "Goblin Box", preco_liga: null, melhor_amazon: "80.00", medio_liga: null,
      diferenca_media_pct: null, sem_vendedor_desde: null },
  ],
};

const LISTAR_SIM = "GET /api/gestao/catalogo?monitorado=sim&pagina=1";

/** Segura as chamadas que casam com o texto (a partir da n-ésima) até `soltar()`; as demais seguem direto. */
function segurar(parte: string, apartirDe = 1) {
  const original = globalThis.fetch;
  let vistas = 0;
  let soltar: () => void = () => {};
  const porta = new Promise<void>((res) => { soltar = res; });
  vi.stubGlobal("fetch", (entrada: RequestInfo | URL, init?: RequestInit) =>
    String(entrada).includes(parte) && ++vistas >= apartirDe ? porta.then(() => original(entrada, init)) : original(entrada, init));
  return () => soltar();
}

async function tabela() {
  return within(await screen.findByRole("table"));
}

describe("Catálogo", () => {
  it("chave da linha liga e desliga no lugar, sem recarregar a lista", async () => {
    const chamadas = apiFalsa({ ...base, [LISTAR]: ok(LISTA), "PATCH /api/gestao/produtos/5": ok({ ...ITEM, monitorado: false }) });
    renderizarEm("/gestao/catalogo");
    const t = await tabela();
    const chave = t.getByRole("checkbox", { name: "Monitorar Lair of the Hydra" });
    expect(chave).toBeChecked();
    await userEvent.click(chave);
    expect(chave).not.toBeChecked();
    await waitFor(() => expect(chamadas.some((c) => c.metodo === "PATCH" && (c.corpo as { ativo: boolean }).ativo === false)).toBe(true));
    expect(chamadas.filter((c) => c.caminho.includes("/catalogo?"))).toHaveLength(1);
  });

  it("erro ao trocar a chave devolve a chave e mostra alerta", async () => {
    apiFalsa({
      ...base, [LISTAR]: ok(LISTA),
      "PATCH /api/gestao/produtos/5": { status: 500, corpo: { erro: "interno", mensagem: "Falhou." } },
    });
    renderizarEm("/gestao/catalogo");
    const t = await tabela();
    const chave = t.getByRole("checkbox", { name: "Monitorar Lair of the Hydra" });
    await userEvent.click(chave);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(chave).toBeChecked();
  });

  it("marcar linhas mostra a barra de lote com N selecionados", async () => {
    apiFalsa({ ...base, [LISTAR]: ok(LISTA) });
    renderizarEm("/gestao/catalogo");
    const t = await tabela();
    await userEvent.click(t.getByRole("checkbox", { name: "Selecionar Lair of the Hydra" }));
    await userEvent.click(t.getByRole("checkbox", { name: "Selecionar Goblin Box" }));
    const barra = screen.getByRole("region", { name: "Ação em lote" });
    expect(within(barra).getByText("2 selecionados")).toBeInTheDocument();
  });

  it("Selecionar todos do filtro pede a contagem e o modal mostra Desligar 412 produtos?", async () => {
    const chamadas = apiFalsa({
      ...base, [LISTAR]: ok(LISTA),
      "POST /api/gestao/catalogo/lote": [ok({ alvo: 412, alterados: 0 }), ok({ alvo: 412, alterados: 412 })],
    });
    renderizarEm("/gestao/catalogo");
    const t = await tabela();
    await userEvent.click(t.getByRole("checkbox", { name: "Selecionar Lair of the Hydra" }));
    await userEvent.click(screen.getByRole("button", { name: /Selecionar todos os 412 do filtro/ }));
    expect(await screen.findByText("412 selecionados")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Desligar" }));
    expect(await screen.findByText("Desligar 412 produtos?")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    await waitFor(() => expect(chamadas.filter((c) => c.metodo === "POST")).toHaveLength(2));
    const posts = chamadas.filter((c) => c.metodo === "POST");
    expect(posts[0].corpo).toEqual({ acao: "desligar", filtro: FILTRO, esperado: 0, confirmar: false });
    expect(posts[1].corpo).toEqual({ acao: "desligar", filtro: FILTRO, esperado: 412, confirmar: true });
  });

  it("409 contagem_mudou mostra o número novo e pede confirmar de novo", async () => {
    apiFalsa({
      ...base, [LISTAR]: ok(LISTA),
      "POST /api/gestao/catalogo/lote": [
        ok({ alvo: 412, alterados: 0 }),
        { status: 409, corpo: { erro: "contagem_mudou", mensagem: "A lista mudou: agora são 400 produtos. Confira e confirme de novo." } },
        ok({ alvo: 400, alterados: 0 }),
        ok({ alvo: 400, alterados: 400 }),
      ],
    });
    renderizarEm("/gestao/catalogo");
    const t = await tabela();
    await userEvent.click(t.getByRole("checkbox", { name: "Selecionar Lair of the Hydra" }));
    await userEvent.click(screen.getByRole("button", { name: /Selecionar todos os 412 do filtro/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Desligar" }));
    await userEvent.click(await screen.findByRole("button", { name: "Confirmar" }));
    expect(await screen.findByText("Desligar 400 produtos?")).toBeInTheDocument();
    expect(screen.getByText(/A lista mudou: agora são 400 produtos/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirmar" }));
    await waitFor(() => expect(screen.queryByText("Desligar 400 produtos?")).not.toBeInTheDocument());
  });

  it("sem editar_catalogo não há chaves nem caixas de seleção", async () => {
    apiFalsa({
      ...base, "GET /api/auth/eu": ok({ ...EU_OPERADOR, permissoes: EU_OPERADOR.permissoes.filter((p) => p !== "editar_catalogo") }),
      [LISTAR]: ok(LISTA),
    });
    renderizarEm("/gestao/catalogo");
    const t = await tabela();
    expect(t.getAllByRole("link", { name: /Lair of the Hydra/ }).length).toBeGreaterThan(0);
    expect(screen.queryAllByRole("checkbox", { name: /Monitorar|Selecionar/ })).toHaveLength(0);
  });

  it("link do produto leva a query da lista", async () => {
    apiFalsa({ ...base, "GET /api/gestao/catalogo?busca=lair&monitorado=todos&pagina=2": ok(LISTA) });
    renderizarEm("/gestao/catalogo?busca=lair&pagina=2");
    const t = await tabela();
    expect(t.getByRole("link", { name: /Lair of the Hydra/ })).toHaveAttribute(
      "href", "/gestao/produtos/5?busca=lair&monitorado=todos&pagina=2",
    );
  });

  it("Preço na Liga: esgotado grava preco_liga na URL e mostra média, diferença e sem vendedor desde", async () => {
    const chamadas = apiFalsa({ ...base, [LISTAR]: ok(LISTA), [LISTAR_ESGOTADO]: ok(ESGOTADOS) });
    renderizarEm("/gestao/catalogo");
    await tabela();
    expect(screen.queryByRole("columnheader", { name: "Média Liga" })).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Preço na Liga" }), "esgotado");
    const t = within(await screen.findByRole("table"));
    expect(await t.findByRole("columnheader", { name: "Média Liga" })).toBeInTheDocument();
    expect(t.getByRole("columnheader", { name: "Diferença" })).toBeInTheDocument();
    expect(t.getByRole("columnheader", { name: "Sem vendedor desde" })).toBeInTheDocument();
    expect(t.getByText("R$ 200,00")).toBeInTheDocument();
    expect(t.getByText("50%")).toBeInTheDocument();
    expect(t.getByText("10/10/2026")).toBeInTheDocument();
    expect(t.getByText("sem registro de preço")).toBeInTheDocument();
    expect(chamadas.some((c) => c.caminho === "/api/gestao/catalogo?monitorado=todos&preco_liga=esgotado&pagina=1")).toBe(true);
    expect(t.getByRole("link", { name: /Lair of the Hydra/ })).toHaveAttribute(
      "href", "/gestao/produtos/5?monitorado=todos&preco_liga=esgotado&pagina=1",
    );
  });

  it("lote com o filtro esgotado manda preco_liga", async () => {
    const chamadas = apiFalsa({
      ...base, [LISTAR_ESGOTADO]: ok(ESGOTADOS), "POST /api/gestao/catalogo/lote": ok({ alvo: 2, alterados: 0 }),
    });
    renderizarEm("/gestao/catalogo?preco_liga=esgotado");
    const t = await tabela();
    await userEvent.click(t.getByRole("checkbox", { name: "Selecionar Lair of the Hydra" }));
    await userEvent.click(screen.getByRole("button", { name: /Selecionar todos os 2 do filtro/ }));
    await waitFor(() => expect(chamadas.filter((c) => c.metodo === "POST")).toHaveLength(1));
    expect(chamadas.find((c) => c.metodo === "POST")?.corpo).toEqual({
      acao: "desligar", filtro: { ...FILTRO, preco_liga: "esgotado" }, esperado: 0, confirmar: false,
    });
  });

  it("trocar o filtro com a lista nova pendente trava a seleção da lista antiga", async () => {
    apiFalsa({ ...base, [LISTAR]: ok(LISTA), [LISTAR_SIM]: ok({ ...LISTA, itens: [ITEM], total: 1 }) });
    const soltar = segurar("monitorado=sim");
    renderizarEm("/gestao/catalogo");
    const t = await tabela();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Monitoramento" }), "sim");
    expect(screen.getByRole("checkbox", { name: "Selecionar a página" })).toBeDisabled();
    expect(t.getByRole("checkbox", { name: "Selecionar Goblin Box" })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: "Selecionar a página" }));
    expect(screen.queryByRole("region", { name: "Ação em lote" })).not.toBeInTheDocument();
    soltar();
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Selecionar a página" })).toBeEnabled());
    expect(screen.queryByRole("checkbox", { name: "Selecionar Goblin Box" })).not.toBeInTheDocument();
  });

  it("contagem do filtro que chega depois de trocar o filtro é descartada", async () => {
    apiFalsa({
      ...base, [LISTAR]: ok(LISTA), [LISTAR_SIM]: ok({ ...LISTA, itens: [ITEM], total: 1 }),
      "POST /api/gestao/catalogo/lote": ok({ alvo: 412, alterados: 0 }),
    });
    const soltar = segurar("/catalogo/lote");
    renderizarEm("/gestao/catalogo");
    const t = await tabela();
    await userEvent.click(t.getByRole("checkbox", { name: "Selecionar Lair of the Hydra" }));
    await userEvent.click(screen.getByRole("button", { name: /Selecionar todos os 412 do filtro/ }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Monitoramento" }), "sim");
    soltar();
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Selecionar a página" })).toBeEnabled());
    expect(screen.queryByText("412 selecionados")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Ação em lote" })).not.toBeInTheDocument();
  });

  it("Escape durante a nova contagem do 409 não fecha o modal", async () => {
    apiFalsa({
      ...base, [LISTAR]: ok(LISTA),
      "POST /api/gestao/catalogo/lote": [
        ok({ alvo: 412, alterados: 0 }),
        { status: 409, corpo: { erro: "contagem_mudou", mensagem: "A lista mudou: agora são 400 produtos." } },
        ok({ alvo: 400, alterados: 0 }),
      ],
    });
    const soltar = segurar("/catalogo/lote", 3); // a nova contagem fica pendente
    renderizarEm("/gestao/catalogo");
    const t = await tabela();
    await userEvent.click(t.getByRole("checkbox", { name: "Selecionar Lair of the Hydra" }));
    await userEvent.click(screen.getByRole("button", { name: /Selecionar todos os 412 do filtro/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Desligar" }));
    await userEvent.click(await screen.findByRole("button", { name: "Confirmar" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.getByText("Desligar 412 produtos?")).toBeInTheDocument();
    soltar();
    expect(await screen.findByText("Desligar 400 produtos?")).toBeInTheDocument();
  });
});
