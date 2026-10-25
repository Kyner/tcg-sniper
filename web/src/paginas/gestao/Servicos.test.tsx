import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFalsa, EU_ADMIN, EU_OPERADOR, ok, renderizarEm } from "../../teste/apoio";

const LIGA = {
  id: "liga", nome: "LigaMagic", estado: "rodando", agora: "coletando a página 3 de 40 do catálogo inteiro",
  detalhe: "Coleta em andamento desde 14:02, página 3 de 40.", ultimo_ok: "2026-10-25T14:02:00+00:00",
  ligado: true, transicao: null, acoes: ["desligar", "rodar_agora"], abrir: "http://localhost:6080/vnc.html",
  atividade: "servico=liga", sub: null,
};
const MONITOR = {
  ...LIGA, id: "amazon_monitor", nome: "Amazon · monitor", estado: "esperando", agora: "ok", detalhe: "Tudo certo.",
  acoes: ["desligar"], abrir: "http://localhost:6081/vnc.html", atividade: "servico=amazon_monitor",
  sub: {
    monitor_ligado: true, checkout_ligado: true, checkout_parado: true,
    carrinho: [{ conferencia_id: 9, asin: "B0X", produto: "Booster Box Teste", em: "2026-10-25T13:00:00+00:00" }],
  },
};
const BACKUP = {
  ...LIGA, id: "backup", nome: "Backup", estado: "desligado", agora: "desligado", detalhe: "Desligado.", ligado: false,
  acoes: ["ligar"], abrir: null, atividade: "servico=backup",
};
const OUTROS = ["amazon_busca", "casador", "whatsapp"].map((id) => ({
  ...LIGA, id, nome: `Serviço ${id}`, acoes: [], abrir: null, agora: `texto ${id}`,
}));
const LISTA = { servicos: [LIGA, MONITOR, BACKUP, ...OUTROS] };
const base = { "GET /api/auth/eu": ok(EU_ADMIN), "GET /api/gestao/menu": ok({ casamentos_esperando: 0 }) };
const LISTAR = "GET /api/gestao/servicos";
const PARANDO = {
  ...LIGA, estado: "desligado", ligado: false, acoes: ["ligar"],
  transicao: { tipo: "parando", desde: "2026-10-25T14:10:00+00:00" },
};

afterEach(() => vi.useRealTimers());

describe("Serviços", () => {
  it("mostra o carregamento e depois os seis serviços com selo, texto truncado e o detalhe no tooltip", async () => {
    apiFalsa({ ...base, [LISTAR]: ok(LISTA) });
    renderizarEm("/gestao/servicos");
    expect(screen.getByRole("status")).toBeInTheDocument();
    const linha = (await screen.findByText("LigaMagic")).closest("tr")!;
    expect(within(linha).getByText("rodando")).toHaveClass("badge-success");
    const texto = within(linha).getByText(LIGA.agora);
    expect(texto).toHaveClass("truncate");
    expect(texto.closest(".tooltip")).toHaveAttribute("data-tip", LIGA.detalhe);
    expect(screen.getByText("Backup").closest("tr")).toHaveTextContent("desligado");
    expect(screen.getAllByRole("checkbox", { name: /^(Ligar|Desligar) (?!monitor|conferência)/ })).toHaveLength(6);
  });

  it("erro na lista mostra o alerta e Tentar de novo recarrega", async () => {
    apiFalsa({ ...base, [LISTAR]: [{ status: 500, corpo: { erro: "falha", mensagem: "Deu ruim." } }, ok(LISTA)] });
    renderizarEm("/gestao/servicos");
    expect(await screen.findByRole("alert")).toHaveClass("alert-error");
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByText("LigaMagic")).toBeInTheDocument();
  });

  it("operador não vê chave, ações nem Abrir", async () => {
    const lista = { servicos: [{ ...LIGA, acoes: [], abrir: null }] };
    apiFalsa({ ...base, "GET /api/auth/eu": ok(EU_OPERADOR), [LISTAR]: ok(lista) });
    renderizarEm("/gestao/servicos");
    await screen.findByText("LigaMagic");
    expect(screen.queryByRole("checkbox", { name: /Ligar|Desligar/ })).toBeNull();
    expect(screen.queryByText("Abrir")).toBeNull();
    expect(screen.queryByText("Rodar agora")).toBeNull();
    expect(screen.getByRole("link", { name: "Atividade" })).toBeInTheDocument();
  });

  it("desligar mostra parando… no lugar, com um GET só da lista depois do POST", async () => {
    const chamadas = apiFalsa({
      ...base, [LISTAR]: [ok({ servicos: [LIGA] }), ok({ servicos: [PARANDO] })],
      "POST /api/gestao/servicos/liga/desligar": ok({ codigo: "desligado", mensagem: "LigaMagic desligado." }),
    });
    renderizarEm("/gestao/servicos");
    await userEvent.click(await screen.findByRole("checkbox", { name: "Desligar LigaMagic" }));
    expect(await screen.findByText("parando…")).toBeInTheDocument();
    expect(screen.getByText("LigaMagic desligado.")).toBeInTheDocument();
    const gestao = chamadas.filter((c) => c.caminho.startsWith("/api/gestao/servicos"));
    expect(gestao.map((c) => `${c.metodo} ${c.caminho}`)).toEqual([
      "GET /api/gestao/servicos", "POST /api/gestao/servicos/liga/desligar", "GET /api/gestao/servicos",
    ]);
    expect(screen.getByRole("checkbox", { name: "Ligar LigaMagic" })).not.toBeChecked();
  });

  it("erro no POST mantém a chave e mostra o alerta", async () => {
    apiFalsa({
      ...base, [LISTAR]: ok({ servicos: [LIGA] }),
      "POST /api/gestao/servicos/liga/desligar": { status: 500, corpo: { erro: "falha", mensagem: "Não deu." } },
    });
    renderizarEm("/gestao/servicos");
    await userEvent.click(await screen.findByRole("checkbox", { name: "Desligar LigaMagic" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Não deu.");
    expect(screen.getByRole("checkbox", { name: "Desligar LigaMagic" })).toBeChecked();
  });

  it("Rodar agora usa o caminho com hífen", async () => {
    const chamadas = apiFalsa({
      ...base, [LISTAR]: ok({ servicos: [LIGA] }),
      "POST /api/gestao/servicos/liga/rodar-agora": ok({ codigo: "rodar_agora", mensagem: "Coleta pedida." }),
    });
    renderizarEm("/gestao/servicos");
    await userEvent.click(await screen.findByRole("button", { name: "Rodar agora" }));
    expect(await screen.findByText("Coleta pedida.")).toBeInTheDocument();
    expect(chamadas.some((c) => c.caminho === "/api/gestao/servicos/liga/rodar-agora")).toBe(true);
  });

  it("transição parado diz parado de verdade desde HH:MM; iniciando mostra iniciando…", async () => {
    const parado = { ...LIGA, estado: "desligado", transicao: { tipo: "parado", desde: "2026-10-25T14:10:00+00:00" } };
    const iniciando = { ...BACKUP, transicao: { tipo: "iniciando", desde: null } };
    apiFalsa({ ...base, [LISTAR]: ok({ servicos: [parado, iniciando] }) });
    renderizarEm("/gestao/servicos");
    expect(await screen.findByText(/parado de verdade desde \d{2}:\d{2}/)).toBeInTheDocument();
    expect(screen.getByText("iniciando…")).toBeInTheDocument();
  });

  it("Abrir abre em outra aba com o tooltip Só abre neste PC; Atividade leva ao filtro do serviço", async () => {
    apiFalsa({ ...base, [LISTAR]: ok({ servicos: [LIGA] }) });
    renderizarEm("/gestao/servicos");
    const abrir = await screen.findByRole("link", { name: "Abrir" });
    expect(abrir).toHaveAttribute("href", "http://localhost:6080/vnc.html");
    expect(abrir).toHaveAttribute("target", "_blank");
    expect(abrir.closest(".tooltip")).toHaveAttribute("data-tip", "Só abre neste PC");
    expect(screen.getByRole("link", { name: "Atividade" })).toHaveAttribute("href", "/gestao/atividade?servico=liga");
  });

  it("sub-linha do monitor: duas chaves, Retomar do checkout e Já conferi no carrinho", async () => {
    const chamadas = apiFalsa({
      ...base, [LISTAR]: ok({ servicos: [MONITOR] }),
      "POST /api/gestao/servicos/amazon_monitor/monitor/desligar": ok({ codigo: "monitor_desligado", mensagem: "Monitor desligado." }),
      "POST /api/gestao/servicos/amazon_monitor/checkout/retomar": ok({ codigo: "checkout_retomado", mensagem: "Checkout retomado." }),
      "POST /api/gestao/servicos/carrinho/9/conferido": ok({ codigo: "carrinho_conferido", mensagem: "Anotado." }),
    });
    renderizarEm("/gestao/servicos");
    await userEvent.click(await screen.findByRole("checkbox", { name: "Desligar monitor de preço" }));
    expect(await screen.findByText("Monitor desligado.")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Desligar conferência de checkout" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retomar checkout" }));
    expect(await screen.findByText("Checkout retomado.")).toBeInTheDocument();
    expect(screen.getByText("Booster Box Teste")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Já conferi" }));
    expect(await screen.findByText("Anotado.")).toBeInTheDocument();
    expect(chamadas.filter((c) => c.metodo === "POST")).toHaveLength(3);
  });

  it("recarrega a lista a cada 60 s", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const chamadas = apiFalsa({ ...base, [LISTAR]: ok({ servicos: [LIGA] }) });
    renderizarEm("/gestao/servicos");
    await screen.findByText("LigaMagic");
    const listas = () => chamadas.filter((c) => c.caminho === "/api/gestao/servicos").length;
    const antes = listas();
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    await waitFor(() => expect(listas()).toBe(antes + 1));
  });
});
