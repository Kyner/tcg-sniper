import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { apiFalsa, EU_GRUPO, ok, renderizarEm, respostasOportunidadesVazias } from "../teste/apoio";

const PRODUTO = { id: 7, nome: "Final Fantasy - Caixa", imagem: null, ativo: true };
const ANUNCIO = { titulo: "Caixa FF", url: "https://www.amazon.com.br/dp/B0X", imagem: null };
const resumo = (periodo: string, oportunidades: number) => ok({
  periodo,
  numeros: oportunidades
    ? { diferenca_bruta: "4820.00", oportunidades, desconto_medio: "27.40", duracao_media_min: 200, produtos: 9 }
    : { diferenca_bruta: "0.00", oportunidades: 0, desconto_medio: null, duracao_media_min: null, produtos: 0 },
  por_dia: [{ dia: "2026-10-20", oportunidades }],
});

describe("Oportunidades", () => {
  it("mostra números, ativa, quase lá e encerrada", async () => {
    apiFalsa({
      "GET /api/auth/eu": ok(EU_GRUPO),
      "GET /api/oportunidades/resumo?periodo=7d": resumo("7d", 12),
      "GET /api/oportunidades/ativas": ok({
        ativas: [{ id: 1, produto: PRODUTO, anuncio: ANUNCIO, preco_amazon: "1299.90", preco_liga: "1589.00",
          desconto_pct: "18.20", aberta_em: new Date().toISOString(), em_risco_desde: new Date().toISOString(),
          motivo_risco: "preco_subiu" }],
        ultima_aberta_em: null,
      }),
      "GET /api/oportunidades/quase?limite=20": ok({
        itens: [{ produto: { ...PRODUTO, id: 8, nome: "Duskmourn" }, anuncio: ANUNCIO, preco_amazon: "850.00",
          preco_liga: "1000.00", desconto_pct: "15.00", falta_reais: "50.00", falta_pp: "5.00" }],
        desconto_min_pct: 20, piso_pct: 10,
      }),
      "GET /api/oportunidades/encerradas?periodo=7d&pagina=1": ok({
        itens: [{ id: 2, produto: PRODUTO, aberta_em: "2026-10-18T10:15:00-03:00",
          fechada_em: "2026-10-18T13:35:00-03:00", aberta: false, duracao_min: 200, alertas: 2,
          preco_alertado: "1299.90", menor_preco: "1249.90", preco_liga: "1589.00", desconto_pct: "18.20",
          motivo: "preco_subiu" }],
        total: 1, pagina: 1, por_pagina: 25,
      }),
    });
    renderizarEm("/");
    expect(await screen.findByRole("heading", { name: "Oportunidades" })).toBeInTheDocument();
    expect(await screen.findByText("R$ 4.820,00")).toBeInTheDocument();
    expect(screen.getByText("antes de taxas e frete")).toBeInTheDocument();
    expect(screen.getAllByText("3 h 20 min").length).toBeGreaterThanOrEqual(1);
    const ativas = await screen.findByRole("region", { name: "Ativas agora" });
    expect(await within(ativas).findByText(/em risco desde/)).toBeInTheDocument();
    expect(within(ativas).getByRole("link", { name: "Ver na Amazon" })).toHaveAttribute("href", ANUNCIO.url);
    expect(within(ativas).getByRole("link", { name: "Histórico do produto" })).toHaveAttribute("href", "/produtos/7");
    const quase = screen.getByRole("region", { name: "Quase lá" });
    expect(await within(quase).findAllByText(/faltam R\$ 50,00 \(5%\)/)).not.toHaveLength(0);
    const encerradas = screen.getByRole("region", { name: "Encerradas no período" });
    expect(await within(await within(encerradas).findByRole("table")).findByText("preço subiu")).toBeInTheDocument();
    // O link para o histórico leva o período, para a oportunidade destacada estar na curva.
    for (const link of within(encerradas).getAllByRole("link", { name: PRODUTO.nome })) {
      expect(link).toHaveAttribute("href", "/produtos/7?oportunidade=2&periodo=7d");
    }
  });

  it("ativa de produto inativo: sem link para o histórico", async () => {
    apiFalsa({
      "GET /api/auth/eu": ok(EU_GRUPO),
      ...respostasOportunidadesVazias(),
      "GET /api/oportunidades/ativas": ok({
        ativas: [{ id: 1, produto: { ...PRODUTO, ativo: false }, anuncio: ANUNCIO, preco_amazon: "1299.90",
          preco_liga: "1589.00", desconto_pct: "18.20", aberta_em: new Date().toISOString(), em_risco_desde: null,
          motivo_risco: null }],
        ultima_aberta_em: null,
      }),
    });
    renderizarEm("/");
    const ativas = await screen.findByRole("region", { name: "Ativas agora" });
    expect(await within(ativas).findByRole("link", { name: "Ver na Amazon" })).toBeInTheDocument();
    expect(within(ativas).queryByRole("link", { name: "Histórico do produto" })).not.toBeInTheDocument();
  });

  it("primeira carga das encerradas falhou: alerta sem spinner eterno", async () => {
    apiFalsa({
      "GET /api/auth/eu": ok(EU_GRUPO),
      ...respostasOportunidadesVazias(),
      "GET /api/oportunidades/encerradas?periodo=7d&pagina=1": {
        status: 500, corpo: { erro: "interno", mensagem: "Erro interno. Tente de novo em instantes." },
      },
    });
    renderizarEm("/");
    expect(await screen.findByRole("alert")).toHaveTextContent("Erro interno");
    await screen.findByText("Nenhuma oportunidade aberta agora");
    const encerradas = screen.getByRole("region", { name: "Encerradas no período" });
    expect(within(encerradas).queryByRole("status", { name: "Carregando seção" })).not.toBeInTheDocument();
  });

  it("mostra Carregando antes da primeira resposta", async () => {
    apiFalsa({ "GET /api/auth/eu": ok(EU_GRUPO), ...respostasOportunidadesVazias() });
    renderizarEm("/");
    expect(screen.getByRole("status", { name: "Carregando" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Oportunidades" })).toBeInTheDocument();
    expect(await screen.findByText("Nenhuma oportunidade aberta agora")).toBeInTheDocument();
  });

  it("período vazio: médias com traço e textos de vazio; troca de período busca de novo", async () => {
    const chamadas = apiFalsa({
      "GET /api/auth/eu": ok(EU_GRUPO),
      ...respostasOportunidadesVazias(),
      "GET /api/oportunidades/resumo?periodo=30d": resumo("30d", 3),
      "GET /api/oportunidades/encerradas?periodo=30d&pagina=1": ok({ itens: [], total: 0, pagina: 1, por_pagina: 25 }),
    });
    renderizarEm("/");
    expect(await screen.findByText("Nenhuma oportunidade aberta agora")).toBeInTheDocument();
    expect(await screen.findByText("Nenhuma oportunidade nos últimos 7 dias")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
    await userEvent.click(screen.getByRole("button", { name: "30 dias" }));
    expect(await screen.findByText("R$ 4.820,00")).toBeInTheDocument();
    expect(chamadas.some((c) => c.caminho === "/api/oportunidades/resumo?periodo=30d")).toBe(true);
  });

  it("filtro por motivo busca de novo com o motivo e volta à página 1", async () => {
    const chamadas = apiFalsa({
      "GET /api/auth/eu": ok(EU_GRUPO),
      ...respostasOportunidadesVazias(),
      "GET /api/oportunidades/encerradas?periodo=7d&pagina=1&motivo=preco_subiu": ok({
        itens: [], total: 0, pagina: 1, por_pagina: 25,
      }),
    });
    renderizarEm("/");
    await screen.findByText("Nenhuma oportunidade aberta agora");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Motivo" }), "preco_subiu");
    await screen.findByText("Nenhuma encerrada nos últimos 7 dias");
    expect(
      chamadas.some((c) => c.caminho === "/api/oportunidades/encerradas?periodo=7d&pagina=1&motivo=preco_subiu"),
    ).toBe(true);
  });

  it("erro de rede mostra alerta com Tentar de novo", async () => {
    apiFalsa({
      "GET /api/auth/eu": ok(EU_GRUPO),
      ...respostasOportunidadesVazias(),
      "GET /api/oportunidades/resumo?periodo=7d": [
        { status: 500, corpo: { erro: "interno", mensagem: "Erro interno. Tente de novo em instantes." } },
        resumo("7d", 12),
      ],
    });
    renderizarEm("/");
    expect(await screen.findByRole("alert")).toHaveTextContent("Erro interno");
    await userEvent.click(screen.getByRole("button", { name: "Tentar de novo" }));
    expect(await screen.findByText("R$ 4.820,00")).toBeInTheDocument();
  });

  it("sem ver_oportunidades vai para Sem acesso", async () => {
    apiFalsa({ "GET /api/auth/eu": ok({ ...EU_GRUPO, permissoes: ["ver_area_negocio"] }) });
    renderizarEm("/");
    expect(await screen.findByRole("heading", { name: "Sem acesso" })).toBeInTheDocument();
  });
});
