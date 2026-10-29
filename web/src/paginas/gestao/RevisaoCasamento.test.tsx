import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { apiFalsa, EU_OPERADOR, ok, renderizarEm } from "../../teste/apoio";

const Q = "situacao=esperando_decisao&ordem=preco_liga&pagina=1";
const QL = "busca=lair&situacao=esperando_decisao&ordem=preco_liga&pagina=3";
const base = { "GET /api/auth/eu": ok(EU_OPERADOR), "GET /api/gestao/menu": ok({ casamentos_esperando: 2 }) };

function anuncio(id: number, titulo: string, extra: Record<string, unknown> = {}) {
  return {
    anuncio_id: id, asin: `B0${id}`, titulo, url: `https://www.amazon.com.br/dp/B0${id}`, imagem: null,
    preco: "999.00", vendedor: "Loja X", termos_variacao: [], idioma: null, ia: null, origem: null, revisado_em: null,
    oportunidade: false, casado_com: null, ...extra,
  };
}

const A1 = anuncio(101, "Lair of the Hydra Booster Box Foil", {
  termos_variacao: ["Foil"],
  ia: { mesmo_produto: true, confianca: 95, motivo: "Mesmo nome e mesma edição", idioma: "inglês" },
});
const A2 = anuncio(102, "Lair of the Hydra Booster", {
  ia: { mesmo_produto: false, confianca: 80, motivo: "Coleção diferente", idioma: null },
});
const A3 = anuncio(103, "Lair Hydra Caixa");
const CONF = anuncio(201, "Lair of the Hydra confirmado", { origem: "manual", revisado_em: "2026-10-20T12:00:00Z" });
const IGN = anuncio(301, "Outra coisa", { origem: "automatico_ia" });

const REVISAO = {
  produto: {
    id: 31, nome: "Lair of the Hydra", nome_en: "Lair of the Hydra EN", imagem: null, categoria: "Booster",
    url: "https://www.ligamagic.com.br/?view=prod/view&pcode=31", preco_liga: "1589.00", lojas: 4,
    pistas: ["sem Foil no nome", "idioma não informado"],
  },
  navegacao: { posicao: 12, total: 96, anterior: 30, proximo: 32 },
  para_decidir: [A1, A2, A3],
  confirmados: [CONF],
  ignorados: [IGN],
  parecidos: [{ id: 40, nome: "Lair of the Hydra Foil", imagem: null, preco_liga: "1700.00" }],
  termos: ["lair hydra"],
  termos_pedidos: false,
};
const REVISAO_32 = {
  ...REVISAO, produto: { ...REVISAO.produto, id: 32, nome: "Goblin Box" },
  navegacao: { posicao: 13, total: 96, anterior: 31, proximo: 33 },
};

const G = (id: number, q = Q) => `GET /api/gestao/casamentos/${id}?${q}`;
const P = (anuncioId: number) => `POST /api/gestao/casamentos/31/anuncios/${anuncioId}`;

function grupo(nome: string) {
  return screen.getByRole("list", { name: nome });
}

describe("Revisão de um produto", () => {
  it("mostra Liga fixa à esquerda e os três grupos sem abas", async () => {
    apiFalsa({ ...base, [G(31)]: ok(REVISAO) });
    const { container } = renderizarEm("/gestao/casamentos/31");
    expect(await screen.findByRole("heading", { name: "Lair of the Hydra" })).toBeInTheDocument();
    expect(screen.getByText("12 de 96")).toBeInTheDocument();
    expect(container.querySelector(".lg\\:sticky")).not.toBeNull();
    expect(screen.getByText("sem Foil no nome")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ver na LigaMagic/ })).toHaveAttribute("href", REVISAO.produto.url);
    expect(screen.getByRole("heading", { name: /Para decidir/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Confirmados/ })).toBeInTheDocument();
    expect(screen.getByText(/Ignorados/)).toBeInTheDocument();
    expect(within(grupo("Para decidir")).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
    expect(screen.queryAllByRole("tablist")).toHaveLength(0);
    // Variação destacada e parecer da IA.
    const foil = within(grupo("Para decidir")).getByText("Foil");
    expect(foil.tagName).toBe("SPAN");
    expect(foil).toHaveClass("font-semibold", "text-warning");
    expect(within(grupo("Para decidir")).getByText(/mesmo · 95%/)).toHaveClass("badge-success");
    expect(within(grupo("Para decidir")).getByText(/outro · 80%/)).toHaveClass("badge-error");
  });

  it("mantém a query da lista em Voltar, Anterior e Próximo (sem um Pular igual ao Próximo)", async () => {
    const chamadas = apiFalsa({ ...base, [G(31, QL)]: ok(REVISAO) });
    renderizarEm(`/gestao/casamentos/31?${QL}`);
    await screen.findByRole("heading", { name: "Lair of the Hydra" });
    expect(chamadas.some((c) => c.caminho === `/api/gestao/casamentos/31?${QL}`)).toBe(true);
    expect(screen.getByRole("link", { name: "Voltar à lista" })).toHaveAttribute("href", `/gestao/casamentos?${QL}`);
    expect(screen.getByRole("link", { name: /Próximo/ })).toHaveAttribute("href", `/gestao/casamentos/32?${QL}`);
    expect(screen.queryByRole("link", { name: /Pular/ })).toBeNull();
    expect(screen.getByRole("link", { name: /Anterior/ })).toHaveAttribute("href", `/gestao/casamentos/30?${QL}`);
  });

  it("C move o cartão para Confirmados sem nova busca da página", async () => {
    const chamadas = apiFalsa({
      ...base, [G(31)]: ok(REVISAO),
      [P(101)]: ok({ anuncio: { ...A1, origem: "sugerido_ia" }, grupo: "confirmados", mensagem: null }),
    });
    renderizarEm("/gestao/casamentos/31");
    await screen.findByRole("heading", { name: "Lair of the Hydra" });
    const cartao = within(grupo("Para decidir")).getAllByRole("listitem")[0];
    await userEvent.click(within(cartao).getByRole("button", { name: /é o mesmo/ }));
    await waitFor(() => expect(within(grupo("Confirmados")).getAllByRole("listitem")).toHaveLength(2));
    expect(within(grupo("Para decidir")).getAllByRole("listitem")).toHaveLength(2);
    const posts = chamadas.filter((c) => c.metodo === "POST");
    expect(posts).toHaveLength(1);
    expect(posts[0].corpo).toEqual({ acao: "confirmar" });
    expect(chamadas.filter((c) => c.caminho.startsWith("/api/gestao/casamentos/31?"))).toHaveLength(1);
  });

  it("o confirmado tem o botão definir idioma e o selo muda no lugar", async () => {
    const chamadas = apiFalsa({
      ...base, [G(31)]: ok(REVISAO),
      "PATCH /api/gestao/casamentos/anuncios/201/idioma": ok({ anuncio_id: 201, idioma: "ja" }),
    });
    renderizarEm("/gestao/casamentos/31");
    await screen.findByRole("heading", { name: "Lair of the Hydra" });
    // Só o cartão confirmado oferece o botão.
    expect(within(grupo("Para decidir")).queryByRole("button", { name: /definir idioma/ })).toBeNull();
    const cartao = within(grupo("Confirmados")).getAllByRole("listitem")[0];
    expect(within(cartao).queryByText("ja")).toBeNull();
    await userEvent.click(within(cartao).getByRole("button", { name: /definir idioma/ }));
    for (const opcao of ["português", "inglês", "japonês", "outro"]) {
      expect(within(cartao).getByRole("button", { name: opcao })).toBeInTheDocument();
    }
    await userEvent.click(within(cartao).getByRole("button", { name: "japonês" }));
    expect(await within(cartao).findByText("ja")).toHaveClass("badge");
    const patches = chamadas.filter((c) => c.metodo === "PATCH");
    expect(patches).toHaveLength(1);
    expect(patches[0].corpo).toEqual({ idioma: "ja" });
    expect(within(grupo("Confirmados")).getAllByRole("listitem")).toHaveLength(1);
  });

  it("409 ja_confirmado devolve o cartão e mostra a mensagem", async () => {
    apiFalsa({
      ...base, [G(31)]: ok(REVISAO),
      [P(101)]: { status: 409, corpo: { erro: "ja_confirmado", mensagem: "Este anúncio já está confirmado em Goblin Box." } },
    });
    renderizarEm("/gestao/casamentos/31");
    await screen.findByRole("heading", { name: "Lair of the Hydra" });
    const cartao = within(grupo("Para decidir")).getAllByRole("listitem")[0];
    await userEvent.click(within(cartao).getByRole("button", { name: /é o mesmo/ }));
    expect(await screen.findByText("Este anúncio já está confirmado em Goblin Box.")).toBeInTheDocument();
    expect(within(grupo("Para decidir")).getAllByRole("listitem")).toHaveLength(3);
    expect(within(grupo("Para decidir")).getAllByRole("listitem")[0]).toHaveTextContent("Lair of the Hydra Booster Box");
    expect(within(grupo("Confirmados")).getAllByRole("listitem")).toHaveLength(1);
  });

  it('404 do produto mostra "Produto não está mais monitorado" e o botão Próximo', async () => {
    apiFalsa({
      ...base,
      [G(31)]: { status: 404, corpo: { erro: "nao_encontrado", mensagem: "Produto não está mais monitorado." } },
      [`GET /api/gestao/casamentos?${Q}`]: ok({
        itens: [{ id: 6, nome: "Goblin Box" }], total: 1, pagina: 1, por_pagina: 20, categorias: [],
      }),
    });
    renderizarEm("/gestao/casamentos/31");
    expect(await screen.findByText("Produto não está mais monitorado.")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /Próximo/ })).toHaveAttribute("href", `/gestao/casamentos/6?${Q}`);
    expect(screen.getByRole("link", { name: "Voltar à lista" })).toHaveAttribute("href", `/gestao/casamentos?${Q}`);
  });

  it("atalhos C, I, setas e Enter", async () => {
    const chamadas = apiFalsa({
      ...base, [G(31, QL)]: ok(REVISAO), [G(32, QL)]: ok(REVISAO_32),
      [P(102)]: ok({ anuncio: A2, grupo: "confirmados", mensagem: null }),
      [P(101)]: ok({ anuncio: A1, grupo: "ignorados", mensagem: null }),
    });
    renderizarEm(`/gestao/casamentos/31?${QL}`);
    await screen.findByRole("heading", { name: "Lair of the Hydra" });
    await userEvent.keyboard("{ArrowDown}c");
    await waitFor(() => expect(chamadas.some((c) => c.caminho.endsWith("/anuncios/102"))).toBe(true));
    expect(chamadas.find((c) => c.caminho.endsWith("/anuncios/102"))?.corpo).toEqual({ acao: "confirmar" });
    await userEvent.keyboard("{ArrowUp}i");
    await waitFor(() => expect(chamadas.some((c) => c.caminho.endsWith("/anuncios/101"))).toBe(true));
    expect(chamadas.find((c) => c.caminho.endsWith("/anuncios/101"))?.corpo).toEqual({ acao: "ignorar" });
    // Atalho não vale com o foco num campo.
    await userEvent.click(screen.getByRole("textbox", { name: "Casar por link ou ASIN" }));
    await userEvent.keyboard("c");
    expect(chamadas.filter((c) => c.metodo === "POST")).toHaveLength(2);
    (document.activeElement as HTMLElement).blur();
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByRole("heading", { name: "Goblin Box" })).toBeInTheDocument();
    expect(chamadas.some((c) => c.caminho === `/api/gestao/casamentos/32?${QL}`)).toBe(true);
  });

  it.each([
    ["sucesso", ok({ anuncio: A1, grupo: "confirmados", mensagem: "Confirmado em Lair." })],
    ["409", { status: 409, corpo: { erro: "ja_confirmado", mensagem: "Este anúncio já está confirmado em Goblin Box." } }],
  ] as const)("decisão que responde (%s) depois de ir ao próximo produto não mexe nele", async (_nome, resposta) => {
    const R32 = {
      ...REVISAO_32, para_decidir: [anuncio(501, "Goblin pendente")], confirmados: [], ignorados: [],
    };
    apiFalsa({ ...base, [G(31)]: ok(REVISAO), [G(32)]: ok(R32), [P(101)]: resposta });
    // Segura a resposta do POST até o teste soltar.
    const falso = globalThis.fetch;
    let soltar: () => void = () => {};
    const portao = new Promise<void>((r) => { soltar = r; });
    vi.stubGlobal("fetch", async (entrada: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") await portao;
      return falso(entrada, init);
    });
    renderizarEm("/gestao/casamentos/31");
    await screen.findByRole("heading", { name: "Lair of the Hydra" });
    await userEvent.keyboard("c{Enter}");
    expect(await screen.findByRole("heading", { name: "Goblin Box" })).toBeInTheDocument();
    soltar();
    await new Promise((r) => setTimeout(r, 50));
    expect(within(grupo("Para decidir")).getAllByRole("listitem")).toHaveLength(1);
    expect(within(grupo("Para decidir")).getByText("Goblin pendente")).toBeInTheDocument();
    expect(within(grupo("Confirmados")).queryAllByRole("listitem")).toHaveLength(0);
    expect(within(grupo("Ignorados")).queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(/Lair of the Hydra Booster/)).toBeNull();
  });

  it("Ignorados começam fechados", async () => {
    apiFalsa({ ...base, [G(31)]: ok(REVISAO) });
    const { container } = renderizarEm("/gestao/casamentos/31");
    await screen.findByRole("heading", { name: "Lair of the Hydra" });
    const colapso = container.querySelector(".collapse");
    expect(colapso).not.toBeNull();
    const chave = colapso!.querySelector("input[type=checkbox]") as HTMLInputElement;
    expect(chave.checked).toBe(false);
  });

  it("É de outro produto abre modal com parecidos e busca; escolher chama trocar", async () => {
    const parecido = { id: 40, nome: "Lair of the Hydra Foil", imagem: null, preco_liga: "1700.00" };
    const achado = { id: 41, nome: "Hydra Deluxe", imagem: null, preco_liga: null };
    const chamadas = apiFalsa({
      ...base, [G(31)]: ok(REVISAO),
      "GET /api/gestao/casamentos/anuncios/101/produtos?busca=&de=31": ok([parecido]),
      "GET /api/gestao/casamentos/anuncios/101/produtos?busca=deluxe&de=31": ok([achado]),
      [P(101)]: ok({ anuncio: { ...A1, origem: "manual" }, grupo: "ignorados", mensagem: null }),
    });
    renderizarEm("/gestao/casamentos/31");
    await screen.findByRole("heading", { name: "Lair of the Hydra" });
    const cartao = within(grupo("Para decidir")).getAllByRole("listitem")[0];
    await userEvent.click(within(cartao).getByRole("button", { name: /é de outro produto/ }));
    const modal = await screen.findByRole("dialog", { name: /É de outro produto/ });
    expect(await within(modal).findByText("Lair of the Hydra Foil")).toBeInTheDocument();
    await userEvent.type(within(modal).getByRole("searchbox", { name: "Buscar no catálogo" }), "deluxe");
    await userEvent.click(within(modal).getByRole("button", { name: "Buscar" }));
    expect(await within(modal).findByText("Hydra Deluxe")).toBeInTheDocument();
    await userEvent.click(within(modal).getByRole("button", { name: "Escolher Hydra Deluxe" }));
    await waitFor(() => expect(chamadas.some((c) => c.metodo === "POST")).toBe(true));
    expect(chamadas.find((c) => c.metodo === "POST")?.corpo).toEqual({ acao: "trocar", para_produto_id: 41 });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(within(grupo("Para decidir")).getAllByRole("listitem")).toHaveLength(2);
  });

  it("menu ⋯ Rebuscar agora mostra a mensagem da API em alert", async () => {
    apiFalsa({
      ...base, [G(31)]: ok(REVISAO),
      "POST /api/gestao/casamentos/31/rebuscar": ok({ tipo: "success", mensagem: "Produto vai na frente da fila." }),
    });
    renderizarEm("/gestao/casamentos/31");
    await screen.findByRole("heading", { name: "Lair of the Hydra" });
    await userEvent.click(screen.getByRole("button", { name: "Mais ações" }));
    await userEvent.click(screen.getByRole("button", { name: "Rebuscar agora" }));
    const alerta = await screen.findByRole("alert");
    expect(alerta).toHaveTextContent("Produto vai na frente da fila.");
    expect(alerta).toHaveClass("alert-success");
  });

  it("Casar por link põe o anúncio em Confirmados", async () => {
    const novo = anuncio(401, "Anúncio colado", { origem: "manual" });
    const chamadas = apiFalsa({ ...base, [G(31)]: ok(REVISAO), "POST /api/gestao/casamentos/31/link": ok(novo) });
    renderizarEm("/gestao/casamentos/31");
    await screen.findByRole("heading", { name: "Lair of the Hydra" });
    await userEvent.type(screen.getByRole("textbox", { name: "Casar por link ou ASIN" }), "B0401");
    await userEvent.click(screen.getByRole("button", { name: "Casar" }));
    await waitFor(() => expect(within(grupo("Confirmados")).getAllByRole("listitem")).toHaveLength(2));
    expect(chamadas.find((c) => c.metodo === "POST")?.corpo).toEqual({ link: "B0401" });
  });

  it("Enter com o foco no menu ⋯ não avança para o próximo produto", async () => {
    const chamadas = apiFalsa({ ...base, [G(31)]: ok(REVISAO), [G(32)]: ok(REVISAO_32) });
    renderizarEm("/gestao/casamentos/31");
    await screen.findByRole("heading", { name: "Lair of the Hydra" });
    screen.getByRole("button", { name: "Mais ações" }).focus();
    await userEvent.keyboard("{Enter}");
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.getByRole("heading", { name: "Lair of the Hydra" })).toBeInTheDocument();
    expect(chamadas.some((c) => c.caminho.startsWith("/api/gestao/casamentos/32"))).toBe(false);
  });

  it("↑/↓ rolam até o cartão escolhido", async () => {
    const rolar = vi.fn();
    Element.prototype.scrollIntoView = rolar;
    apiFalsa({ ...base, [G(31)]: ok(REVISAO) });
    renderizarEm("/gestao/casamentos/31");
    await screen.findByRole("heading", { name: "Lair of the Hydra" });
    await userEvent.keyboard("{ArrowDown}");
    await waitFor(() => expect(rolar).toHaveBeenCalled());
    const alvo = rolar.mock.contexts.at(-1) as HTMLElement;
    expect(alvo).toHaveTextContent("Lair of the Hydra Booster");
    expect(alvo).not.toHaveTextContent("Foil");
  });

  it("desfazer não troca o cartão destacado", async () => {
    Element.prototype.scrollIntoView = vi.fn();
    apiFalsa({
      ...base, [G(31)]: ok(REVISAO),
      "POST /api/gestao/casamentos/31/anuncios/201": ok({ anuncio: CONF, grupo: "para_decidir", mensagem: null }),
    });
    renderizarEm("/gestao/casamentos/31");
    await screen.findByRole("heading", { name: "Lair of the Hydra" });
    await userEvent.keyboard("{ArrowDown}");
    const destacado = () => within(grupo("Para decidir")).getAllByRole("article").find((a) => a.getAttribute("aria-current") === "true");
    expect(destacado()).toHaveTextContent("Lair of the Hydra Booster");
    await userEvent.click(within(grupo("Confirmados")).getByRole("button", { name: "desfazer" }));
    await waitFor(() => expect(within(grupo("Para decidir")).getAllByRole("listitem")).toHaveLength(4));
    expect(destacado()).toHaveTextContent("Lair of the Hydra Booster");
    expect(destacado()).not.toHaveTextContent("Foil");
  });

  it("no celular a Liga fica compacta acima e os anúncios logo depois, antes dos parecidos", async () => {
    apiFalsa({ ...base, [G(31)]: ok({ ...REVISAO, produto: { ...REVISAO.produto, imagem: "https://img/x.jpg" } }) });
    renderizarEm("/gestao/casamentos/31");
    await screen.findByRole("heading", { name: "Lair of the Hydra" });
    // Foto do produto pequena no celular, grande só no lg.
    const foto = screen.getByRole("img", { name: "Lair of the Hydra" });
    expect(foto).toHaveClass("h-20", "lg:h-40");
    // Ordem no celular: produto (1), anúncios (2), parecidos (3); no lg a ordem do HTML.
    const produto = screen.getByRole("heading", { name: "Lair of the Hydra" }).closest(".card")!;
    const anuncios = grupo("Para decidir").closest("section")!.parentElement!;
    const parecidos = grupo("Parecidos na Liga").closest(".card")!;
    expect(produto).toHaveClass("order-1", "lg:order-none");
    expect(anuncios).toHaveClass("order-2", "lg:order-none");
    expect(parecidos).toHaveClass("order-3", "lg:order-none");
  });

  it("menu definir idioma fecha com Esc e com clique fora", async () => {
    apiFalsa({ ...base, [G(31)]: ok(REVISAO) });
    renderizarEm("/gestao/casamentos/31");
    await screen.findByRole("heading", { name: "Lair of the Hydra" });
    const cartao = within(grupo("Confirmados")).getAllByRole("listitem")[0];
    await userEvent.click(within(cartao).getByRole("button", { name: /definir idioma/ }));
    expect(within(cartao).getByRole("button", { name: "japonês" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(within(cartao).queryByRole("button", { name: "japonês" })).toBeNull();
    await userEvent.click(within(cartao).getByRole("button", { name: /definir idioma/ }));
    expect(within(cartao).getByRole("button", { name: "japonês" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("heading", { name: "Lair of the Hydra" }));
    expect(within(cartao).queryByRole("button", { name: "japonês" })).toBeNull();
  });

  it("desfazer sem ter usado as setas mantém o destaque no cartão que o tinha", async () => {
    Element.prototype.scrollIntoView = vi.fn();
    apiFalsa({
      ...base, [G(31)]: ok(REVISAO),
      "POST /api/gestao/casamentos/31/anuncios/201": ok({ anuncio: CONF, grupo: "para_decidir", mensagem: null }),
    });
    renderizarEm("/gestao/casamentos/31");
    await screen.findByRole("heading", { name: "Lair of the Hydra" });
    const destacado = () => within(grupo("Para decidir")).getAllByRole("article").find((a) => a.getAttribute("aria-current") === "true");
    expect(destacado()).toHaveTextContent("Foil");
    await userEvent.click(within(grupo("Confirmados")).getByRole("button", { name: "desfazer" }));
    await waitFor(() => expect(within(grupo("Para decidir")).getAllByRole("listitem")).toHaveLength(4));
    expect(destacado()).toHaveTextContent("Foil");
  });

  it("C e depois desfazer: o destaque fica no próximo pendente, não no desfeito", async () => {
    Element.prototype.scrollIntoView = vi.fn();
    apiFalsa({
      ...base, [G(31)]: ok(REVISAO),
      [P(101)]: ok({ anuncio: A1, grupo: "confirmados", mensagem: null }),
      "POST /api/gestao/casamentos/31/anuncios/201": ok({ anuncio: CONF, grupo: "para_decidir", mensagem: null }),
    });
    renderizarEm("/gestao/casamentos/31");
    await screen.findByRole("heading", { name: "Lair of the Hydra" });
    const destacado = () => within(grupo("Para decidir")).getAllByRole("article").find((a) => a.getAttribute("aria-current") === "true");
    await userEvent.keyboard("c");
    await waitFor(() => expect(within(grupo("Confirmados")).getAllByRole("listitem")).toHaveLength(2));
    expect(destacado()).toHaveTextContent("Lair of the Hydra Booster");
    const conf = within(grupo("Confirmados")).getAllByRole("listitem").find((li) => li.textContent?.includes("confirmado"))!;
    await userEvent.click(within(conf).getByRole("button", { name: "desfazer" }));
    await waitFor(() => expect(within(grupo("Para decidir")).getAllByRole("listitem")).toHaveLength(3));
    expect(destacado()).toHaveTextContent("Lair of the Hydra Booster");
    expect(destacado()).not.toHaveTextContent("confirmado");
  });
});
