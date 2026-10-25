import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { apiFalsa, EU_ADMIN, EU_OPERADOR, ok, renderizarEm } from "../../teste/apoio";
import { fimDoDia, inicioDoDia } from "./Atividade";

const base = { "GET /api/auth/eu": ok(EU_ADMIN), "GET /api/gestao/menu": ok({ casamentos_esperando: 0 }) };
const LISTAR = "GET /api/gestao/atividade";

function linha(extra: Record<string, unknown> = {}) {
  return {
    chave: "coleta:1", em: "2026-10-25T14:02:00+00:00", servico: "liga", o_que: "coleta_liga", situacao: "ok",
    resultado: "42 produtos coletados, nenhum com falha", produto_id: null, produto: null, asin: null,
    custo_usd: null, detalhe: { tipo: "liga", produtos_ok: 42, erro: null }, ...extra,
  };
}
const MSG = linha({
  chave: "mensagem:7", servico: "whatsapp", o_que: "mensagem", situacao: "falha", resultado: "falha · grupo do admin · Achei",
  detalhe: { mensagem_id: 7, status: "falha", destino: "admin", texto: "Achei *Booster Box* barato", tentativas: 3, ultimo_erro: "HTTP 500" },
});
const PRODUTO = linha({
  chave: "checkout:3", servico: "amazon_monitor", o_que: "checkout", produto_id: 12, produto: "Booster Box Teste", asin: "B0TESTE123",
  resultado: "Conferido R$ 100,00 sem frete e com uma observação bem comprida que passa do limite da linha",
  detalhe: { situacao: "ok", motivo: "Observação completa do checkout", vendedor: "Loja X", frete: null },
});

describe("Atividade", () => {
  it("lista as linhas com quando, serviço, o quê, produto, ASIN e resultado truncado", async () => {
    apiFalsa({ ...base, [LISTAR]: ok({ itens: [linha(), PRODUTO], proximo: null }) });
    renderizarEm("/gestao/atividade");
    const item = (await screen.findByText("Booster Box Teste")).closest("li")!;
    expect(within(item).getByRole("link", { name: "Booster Box Teste" })).toHaveAttribute("href", "/gestao/produtos/12");
    const asin = within(item).getByRole("link", { name: "B0TESTE123" });
    expect(asin).toHaveAttribute("href", "https://www.amazon.com.br/dp/B0TESTE123");
    expect(asin).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(within(item).getByText("checkout")).toBeInTheDocument();
    const res = within(item).getByText(/Conferido R\$ 100,00/);
    expect(res).toHaveClass("truncate");
    expect(res.closest(".tooltip")).toHaveAttribute("data-tip", PRODUTO.resultado);
    expect(within(item).getByText("ok")).toHaveClass("badge-success");
  });

  it("mapeia parcial e falha para as cores", async () => {
    apiFalsa({
      ...base,
      [LISTAR]: ok({ itens: [linha({ chave: "a", situacao: "parcial", resultado: "metade" }), linha({ chave: "b", situacao: "falha", resultado: "quebrou" })], proximo: null }),
    });
    renderizarEm("/gestao/atividade");
    const a = (await screen.findByText("metade")).closest("li")!;
    expect(within(a).getByText("parcial")).toHaveClass("badge-warning");
    expect(within(screen.getByText("quebrou").closest("li")!).getByText("falha")).toHaveClass("badge-error");
  });

  it("tocar na linha abre o detalhe com a observação completa", async () => {
    apiFalsa({ ...base, [LISTAR]: ok({ itens: [PRODUTO], proximo: null }) });
    renderizarEm("/gestao/atividade");
    const botao = await screen.findByRole("button", { name: /Detalhes/ });
    expect(botao).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Observação completa do checkout")).not.toBeInTheDocument();
    await userEvent.click(botao);
    expect(botao).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Observação completa do checkout")).toBeInTheDocument();
    expect(screen.getByText("Loja X")).toBeInTheDocument();
  });

  it("filtros vêm da URL, mudar um refaz a busca e explica o monitor", async () => {
    const chamadas = apiFalsa({
      ...base,
      "GET /api/gestao/atividade?servico=liga&o_que=coleta_liga&situacao=problemas": ok({ itens: [linha()], proximo: null }),
      "GET /api/gestao/atividade?servico=liga&o_que=coleta_liga": ok({ itens: [linha()], proximo: null }),
    });
    renderizarEm("/gestao/atividade?servico=liga&o_que=coleta_liga&situacao=problemas");
    await screen.findByText(/42 produtos coletados/);
    expect(screen.getByRole("combobox", { name: "Serviço" })).toHaveValue("liga");
    expect(screen.getByRole("combobox", { name: "O quê" })).toHaveValue("coleta_liga");
    expect(screen.getByRole("combobox", { name: "Situação" })).toHaveValue("problemas");
    expect(screen.getByText(/leituras do monitor só aparecem/i)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Situação" }), "");
    await waitFor(() => expect(chamadas.at(-1)!.caminho).toBe("/api/gestao/atividade?servico=liga&o_que=coleta_liga"));
  });

  it("a busca aplica sozinha, com espera", async () => {
    const chamadas = apiFalsa({
      ...base,
      [LISTAR]: ok({ itens: [linha()], proximo: null }),
      "GET /api/gestao/atividade?busca=B0X": ok({ itens: [], proximo: null }),
    });
    renderizarEm("/gestao/atividade");
    await screen.findByText(/42 produtos coletados/);
    await userEvent.type(screen.getByRole("searchbox", { name: "Buscar" }), "B0X");
    expect(chamadas.some((c) => c.caminho.includes("busca=B"))).toBe(false);
    await waitFor(() => expect(chamadas.at(-1)!.caminho).toBe("/api/gestao/atividade?busca=B0X"));
  });

  it("datas viram ISO com o fuso do navegador", async () => {
    const de = inicioDoDia("2026-10-20");
    const ate = fimDoDia("2026-10-21");
    expect(de).toMatch(/^2026-10-20T00:00:00[+-]\d\d:\d\d$/);
    expect(ate).toMatch(/^2026-10-21T23:59:59[+-]\d\d:\d\d$/);
    const chamadas = apiFalsa({
      ...base,
      [`GET /api/gestao/atividade?de=${encodeURIComponent(de)}&ate=${encodeURIComponent(ate)}`]: ok({ itens: [], proximo: null }),
    });
    renderizarEm("/gestao/atividade?de=2026-10-20&ate=2026-10-21");
    await waitFor(() => expect(chamadas.some((c) => c.caminho.includes("de=2026-10-20T00%3A00%3A00"))).toBe(true));
  });

  it("Carregar mais usa o cursor e acrescenta sem perder as linhas", async () => {
    const chamadas = apiFalsa({
      ...base,
      [LISTAR]: ok({ itens: [linha({ chave: "a", resultado: "primeira" })], proximo: "CUR1" }),
      "GET /api/gestao/atividade?cursor=CUR1": ok({ itens: [linha({ chave: "b", resultado: "segunda" })], proximo: null }),
    });
    renderizarEm("/gestao/atividade");
    await screen.findByText("primeira");
    await userEvent.click(screen.getByRole("button", { name: "Carregar mais" }));
    expect(await screen.findByText("segunda")).toBeInTheDocument();
    expect(screen.getByText("primeira")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Carregar mais" })).not.toBeInTheDocument();
    expect(chamadas.at(-1)!.caminho).toBe("/api/gestao/atividade?cursor=CUR1");
  });

  it("resposta atrasada de Carregar mais não entra na lista de outro filtro", async () => {
    apiFalsa({
      ...base,
      [LISTAR]: ok({ itens: [linha({ chave: "a", resultado: "primeira" })], proximo: "CUR1" }),
      "GET /api/gestao/atividade?cursor=CUR1": ok({ itens: [linha({ chave: "velha", resultado: "linha velha" })], proximo: "CUR_VELHO" }),
      "GET /api/gestao/atividade?servico=liga": ok({ itens: [linha({ chave: "n", resultado: "linha nova" })], proximo: "CUR_NOVO" }),
      "GET /api/gestao/atividade?servico=liga&cursor=CUR_NOVO": ok({ itens: [linha({ chave: "n2", resultado: "nova dois" })], proximo: null }),
    });
    const real = globalThis.fetch;
    let soltar: () => void = () => {};
    const segurada = new Promise<void>((r) => { soltar = r; });
    vi.stubGlobal("fetch", async (entrada: RequestInfo | URL, init?: RequestInit) => {
      if (String(entrada) === "/api/gestao/atividade?cursor=CUR1") await segurada;
      return real(entrada, init);
    });
    renderizarEm("/gestao/atividade");
    await screen.findByText("primeira");
    await userEvent.click(screen.getByRole("button", { name: "Carregar mais" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Serviço" }), "liga");
    await screen.findByText("linha nova");
    soltar();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByText("linha velha")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Carregar mais" }));
    expect(await screen.findByText("nova dois")).toBeInTheDocument();
  });

  it("mensagem mostra o negrito renderizado no detalhe", async () => {
    apiFalsa({ ...base, [LISTAR]: ok({ itens: [MSG], proximo: null }) });
    renderizarEm("/gestao/atividade");
    await userEvent.click(await screen.findByRole("button", { name: /Detalhes/ }));
    expect(screen.getByText("Booster Box").tagName).toBe("STRONG");
  });

  it("sem texto (sem ver_mensagens) mostra 'texto oculto'", async () => {
    const oculta = { ...MSG, detalhe: { ...MSG.detalhe, texto: null } };
    apiFalsa({ ...base, [LISTAR]: ok({ itens: [oculta], proximo: null }) });
    renderizarEm("/gestao/atividade");
    await userEvent.click(await screen.findByRole("button", { name: /Detalhes/ }));
    expect(screen.getByText("texto oculto")).toBeInTheDocument();
  });

  it("Reenviar atualiza o status no lugar; sem a permissão não há botões", async () => {
    const chamadas = apiFalsa({
      ...base,
      [LISTAR]: ok({ itens: [MSG], proximo: null }),
      "POST /api/gestao/mensagens/7/reenviar": ok({ status: "pendente" }),
    });
    renderizarEm("/gestao/atividade");
    await userEvent.click(await screen.findByRole("button", { name: /Detalhes/ }));
    await userEvent.click(screen.getByRole("button", { name: "Reenviar" }));
    const item = within(screen.getByRole("list", { name: "Atividade" })).getByRole("listitem");
    await waitFor(() => expect(within(item).getByText("parcial")).toHaveClass("badge-warning"));
    expect(within(item).getByText("pendente")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reenviar" })).not.toBeInTheDocument();
    expect(chamadas.filter((c) => c.metodo === "POST")).toHaveLength(1);
  });

  it("Descartar mostra o erro 409 e mantém a linha", async () => {
    apiFalsa({
      ...base,
      [LISTAR]: ok({ itens: [MSG], proximo: null }),
      "POST /api/gestao/mensagens/7/descartar": { status: 409, corpo: { erro: "acao_invalida", mensagem: "Já foi enviada." } },
    });
    renderizarEm("/gestao/atividade");
    await userEvent.click(await screen.findByRole("button", { name: /Detalhes/ }));
    await userEvent.click(screen.getByRole("button", { name: "Descartar" }));
    expect(await screen.findByText("Já foi enviada.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Descartar" })).toBeInTheDocument();
  });

  it("sem reenviar_mensagens não mostra os botões", async () => {
    apiFalsa({ ...base, "GET /api/auth/eu": ok(EU_OPERADOR), [LISTAR]: ok({ itens: [MSG], proximo: null }) });
    renderizarEm("/gestao/atividade");
    await userEvent.click(await screen.findByRole("button", { name: /Detalhes/ }));
    expect(screen.queryByRole("button", { name: "Reenviar" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Descartar" })).not.toBeInTheDocument();
  });

  it("o interruptor 'Mostrar reinícios' manda reinicios=true", async () => {
    const chamadas = apiFalsa({
      ...base,
      [LISTAR]: ok({ itens: [linha()], proximo: null }),
      "GET /api/gestao/atividade?reinicios=true": ok({ itens: [linha()], proximo: null }),
    });
    renderizarEm("/gestao/atividade");
    await screen.findByText(/42 produtos coletados/);
    await userEvent.click(screen.getByRole("checkbox", { name: "Mostrar reinícios" }));
    await waitFor(() => expect(chamadas.at(-1)!.caminho).toBe("/api/gestao/atividade?reinicios=true"));
  });

  it("vazio com filtro oferece Limpar filtros; erro oferece Tentar de novo", async () => {
    apiFalsa({
      ...base,
      "GET /api/gestao/atividade?servico=liga": [
        { status: 500, corpo: { erro: "falha", mensagem: "Deu ruim." } },
        ok({ itens: [], proximo: null }),
      ],
      [LISTAR]: ok({ itens: [linha()], proximo: null }),
    });
    renderizarEm("/gestao/atividade?servico=liga");
    expect(await screen.findByRole("alert")).toHaveClass("alert-error");
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByText("Nenhuma atividade com esses filtros")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Limpar filtros" }));
    expect(await screen.findByText(/42 produtos coletados/)).toBeInTheDocument();
  });

  it("exige ver_logs", async () => {
    const semLogs = { ...EU_OPERADOR, permissoes: EU_OPERADOR.permissoes.filter((p) => p !== "ver_logs") };
    apiFalsa({ ...base, "GET /api/auth/eu": ok(semLogs) });
    renderizarEm("/gestao/atividade");
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Atividade" })).not.toBeInTheDocument());
  });
});
