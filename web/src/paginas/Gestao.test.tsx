import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiFalsa, EU_OPERADOR, ok, renderizarEm } from "../teste/apoio";

const DASH = "GET /api/gestao/dashboard";
const FUNIL = {
  liga: 1200, monitorados: 300, esperando_decisao: 96, so_ignorados: 20, sem_candidato: 40,
  casados_produtos: 144, casados_anuncios: 150, oportunidades: 3,
};
const COMPLETO = {
  precisa: [
    { texto: "96 casamentos esperando decisão", rotulo: "Revisar em sequência", destino: "/gestao/casamentos" },
    { texto: "WhatsApp desconectado", rotulo: "Ligar", destino: "/gestao/configuracoes?grupo=whatsapp" },
  ],
  saude: [
    { id: "liga", nome: "LigaMagic", estado: "rodando", resumo: "coletando" },
    { id: "backup", nome: "Backup", estado: "com_problema", resumo: "falhou" },
  ],
  oportunidades: {
    top: [
      { produto_id: 7, nome: "Booster Box Alfa", imagem: "http://x/a.jpg", desconto_pct: 31.5 },
      { produto_id: 8, nome: "Booster Box Beta", imagem: null, desconto_pct: 25 },
    ],
    abertas: 5, alertas_hoje: 2, alertas_semana: 9,
  },
  funil: FUNIL,
};
const base = { "GET /api/auth/eu": ok(EU_OPERADOR), "GET /api/gestao/menu": ok({ casamentos_esperando: 0 }) };

afterEach(() => vi.useRealTimers());

describe("Dashboard da gestão", () => {
  it("mostra os blocos na ordem: precisa de você, saúde, oportunidades, funil", async () => {
    apiFalsa({ ...base, [DASH]: ok(COMPLETO) });
    renderizarEm("/gestao");
    const titulos = (await screen.findAllByRole("heading", { level: 2 })).map((h) => h.textContent);
    expect(titulos).toEqual(["Precisa de você", "Saúde dos serviços", "Oportunidades", "Funil"]);
  });

  it("todo destino é Link interno, nenhum abre o admin antigo", async () => {
    apiFalsa({ ...base, [DASH]: ok(COMPLETO) });
    renderizarEm("/gestao");
    const rev = await screen.findByRole("link", { name: "Revisar em sequência" });
    expect(rev).toHaveAttribute("href", "/gestao/casamentos");
    const ligar = screen.getByRole("link", { name: "Ligar" });
    expect(ligar).toHaveAttribute("href", "/gestao/configuracoes?grupo=whatsapp");
    expect(ligar).not.toHaveAttribute("target");
    expect(screen.getByText("96 casamentos esperando decisão")).toBeInTheDocument();
  });

  it("saúde: selo de estado, nome e link para Serviços; no celular só o nome", async () => {
    apiFalsa({ ...base, [DASH]: ok(COMPLETO) });
    renderizarEm("/gestao");
    const liga = (await screen.findByText("LigaMagic")).closest("a")!;
    expect(liga).toHaveAttribute("href", "/gestao/servicos");
    expect(within(liga).getByText("rodando")).toBeInTheDocument();
    const selo = screen.getByText("com problema").parentElement!;
    expect(selo.className).toContain("hidden");
    expect(selo.className).toContain("sm:inline-flex");
  });

  it("oportunidades: foto, nome e desconto, com link para o produto", async () => {
    apiFalsa({ ...base, [DASH]: ok(COMPLETO) });
    renderizarEm("/gestao");
    expect(await screen.findByRole("img", { name: "Booster Box Alfa" })).toHaveAttribute("src", "http://x/a.jpg");
    expect(screen.getByRole("img", { name: "Booster Box Beta (sem foto)" })).toBeInTheDocument();
    expect(screen.getByText("31,5%")).toBeInTheDocument();
    expect(screen.getByText(/5 abertas/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Booster Box Alfa/ })).toHaveAttribute("href", "/produtos/7");
  });

  it("funil: cada degrau é link para a lista filtrada", async () => {
    apiFalsa({ ...base, [DASH]: ok(COMPLETO) });
    renderizarEm("/gestao");
    const degrau = (nome: RegExp) => screen.findByRole("link", { name: nome });
    expect(await degrau(/Esperando decisão/)).toHaveAttribute("href", "/gestao/casamentos?situacao=esperando_decisao");
    expect(await degrau(/Só ignorados/)).toHaveAttribute("href", "/gestao/casamentos?situacao=so_ignorados");
    expect(await degrau(/Sem candidato/)).toHaveAttribute("href", "/gestao/casamentos?situacao=sem_candidato");
    expect(await degrau(/Produtos casados/)).toHaveAttribute("href", "/gestao/casamentos?situacao=casado");
    expect(await degrau(/Monitorados/)).toHaveAttribute("href", "/gestao/catalogo?monitorado=sim");
    expect(await degrau(/Na Liga/)).toHaveAttribute("href", "/gestao/catalogo");
    expect(await degrau(/Oportunidades abertas/)).toHaveAttribute("href", "/");
    expect(screen.getByText("1200")).toBeInTheDocument();
  });

  it("bloco null não aparece e 'Precisa de você' some quando vazio", async () => {
    apiFalsa({ ...base, [DASH]: ok({ precisa: [], saude: null, oportunidades: null, funil: null }) });
    renderizarEm("/gestao");
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.queryAllByRole("heading", { level: 2 })).toHaveLength(0);
  });

  it("primeira carga com erro mostra alerta e Tentar de novo recarrega", async () => {
    apiFalsa({ ...base, [DASH]: [{ status: 500, corpo: { erro: "falha", mensagem: "Deu ruim." } }, ok(COMPLETO)] });
    renderizarEm("/gestao");
    expect(await screen.findByRole("alert")).toHaveTextContent("Deu ruim.");
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByText("LigaMagic")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("primeira carga com a rede fora cai em Sistema indisponível e volta ao tentar de novo", async () => {
    apiFalsa({ ...base, [DASH]: ["rede-fora", ok(COMPLETO)] });
    renderizarEm("/gestao");
    expect(await screen.findByRole("heading", { name: "Sistema indisponível" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByText("LigaMagic")).toBeInTheDocument();
  });

  it("funil sem permissão da tela de destino vira texto, sem link", async () => {
    const eu = { ...EU_OPERADOR, permissoes: EU_OPERADOR.permissoes.filter((p) => p !== "revisar_casamentos" && p !== "ver_catalogo") };
    apiFalsa({ ...base, "GET /api/auth/eu": ok(eu), [DASH]: ok(COMPLETO) });
    renderizarEm("/gestao");
    await screen.findByText("Esperando decisão");
    expect(screen.queryByRole("link", { name: /Esperando decisão/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Monitorados/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Oportunidades abertas/ })).toBeInTheDocument();
  });

  it("recarrega a cada 60 s", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const chamadas = apiFalsa({ ...base, [DASH]: ok(COMPLETO) });
    renderizarEm("/gestao");
    await screen.findByText("LigaMagic");
    const n = () => chamadas.filter((c) => c.caminho === "/api/gestao/dashboard").length;
    const antes = n();
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    await waitFor(() => expect(n()).toBe(antes + 1));
  });

  it("sem ver_area_negocio as oportunidades e o funil não levam à área de negócio", async () => {
    const eu = { ...EU_OPERADOR, permissoes: EU_OPERADOR.permissoes.filter((p) => p !== "ver_area_negocio") };
    apiFalsa({ ...base, "GET /api/auth/eu": ok(eu), [DASH]: ok(COMPLETO) });
    renderizarEm("/gestao");
    expect(await screen.findByText("Booster Box Alfa")).toBeInTheDocument();
    expect(screen.getByText("Booster Box Alfa").closest("a")).toBeNull();
    expect(screen.queryByRole("link", { name: /Oportunidades abertas/ })).toBeNull();
    expect(screen.getByText("Oportunidades abertas")).toBeInTheDocument();
  });

  it("com ver_area_negocio as oportunidades levam ao produto", async () => {
    apiFalsa({ ...base, [DASH]: ok(COMPLETO) });
    renderizarEm("/gestao");
    expect((await screen.findByText("Booster Box Alfa")).closest("a")).toHaveAttribute("href", "/produtos/7");
    expect(screen.getByRole("link", { name: /Oportunidades abertas/ })).toHaveAttribute("href", "/");
  });
});
