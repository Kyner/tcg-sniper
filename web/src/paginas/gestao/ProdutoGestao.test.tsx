import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { apiFalsa, EU_OPERADOR, ok, renderizarEm } from "../../teste/apoio";

const DADOS = {
  produto: { id: 5, nome: "Lair of the Hydra", nome_en: null, imagem: null, categoria: "Booster", url: "https://liga.test/5", pistas: [] },
  monitorado: true,
  esgotado_liga: false,
  liga: { preco: "1589.00", lojas: 4, medio: "1700.00", lido_em: "2026-10-21T10:00:00-03:00" },
  melhor_amazon: { preco: "1200.00", diferenca_pct: "24.5" },
  casamentos: { pendentes: 3, confirmados: 2, ignorados: 1 },
  anuncio: { titulo: "Caixa Hydra", url: "https://www.amazon.com.br/dp/B0H", imagem: null },
  sem_preco: false,
  anuncios_casados: 1,
  curva: null,
};
const base = { "GET /api/auth/eu": ok(EU_OPERADOR), "GET /api/gestao/menu": ok({ casamentos_esperando: 0 }) };

describe("ProdutoGestao", () => {
  it("mostra monitorar, preços, contagens e link de revisão", async () => {
    apiFalsa({ ...base, "GET /api/gestao/produtos/5": ok(DADOS) });
    renderizarEm("/gestao/produtos/5?busca=lair&monitorado=todos&pagina=2");
    expect(await screen.findByRole("heading", { name: "Lair of the Hydra" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Monitorar" })).toBeChecked();
    expect(screen.getByText("R$ 1.589,00")).toBeInTheDocument();
    expect(screen.getByText("R$ 1.200,00")).toBeInTheDocument();
    expect(screen.getByText("3 pendentes")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Revisar este produto" })).toHaveAttribute("href", "/gestao/casamentos/5");
    expect(screen.getByRole("link", { name: "Histórico do produto" })).toHaveAttribute("href", "/produtos/5");
    expect(screen.getByRole("link", { name: "Ver na Amazon" })).toHaveAttribute("href", "https://www.amazon.com.br/dp/B0H");
    expect(screen.getByRole("link", { name: "Voltar" })).toHaveAttribute(
      "href", "/gestao/catalogo?busca=lair&monitorado=todos&pagina=2",
    );
    expect(screen.getByText(/Ainda não há leituras suficientes/)).toBeInTheDocument();
    expect(screen.queryByText("Esgotado na Liga")).not.toBeInTheDocument();
  });

  it("casado sem preço: link da Amazon, aviso e ligação para os casamentos", async () => {
    apiFalsa({
      ...base,
      "GET /api/gestao/produtos/5": ok({ ...DADOS, melhor_amazon: null, sem_preco: true, anuncios_casados: 3 }),
    });
    renderizarEm("/gestao/produtos/5");
    expect(await screen.findByRole("link", { name: "Ver na Amazon" })).toHaveAttribute("href", "https://www.amazon.com.br/dp/B0H");
    expect(screen.getByText("sem preço agora")).toBeInTheDocument();
    expect(screen.queryByText("Sem anúncio confirmado com preço")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "+2 anúncios" })).toHaveAttribute("href", "/gestao/casamentos/5");
  });

  it("sem anúncio casado: texto de vazio e sem link da Amazon", async () => {
    apiFalsa({
      ...base,
      "GET /api/gestao/produtos/5": ok({ ...DADOS, melhor_amazon: null, anuncio: null, anuncios_casados: 0 }),
    });
    renderizarEm("/gestao/produtos/5");
    expect(await screen.findByText("Sem anúncio confirmado")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Ver na Amazon" })).not.toBeInTheDocument();
  });

  it("produto esgotado na Liga mostra o selo", async () => {
    apiFalsa({
      ...base,
      "GET /api/gestao/produtos/5": ok({ ...DADOS, esgotado_liga: true, liga: { ...DADOS.liga, preco: null } }),
    });
    renderizarEm("/gestao/produtos/5");
    expect(await screen.findByText("Esgotado na Liga")).toHaveClass("badge", "badge-warning");
  });

  it("a chave muda no lugar e erro devolve", async () => {
    apiFalsa({
      ...base, "GET /api/gestao/produtos/5": ok(DADOS),
      "PATCH /api/gestao/produtos/5": { status: 500, corpo: { erro: "interno", mensagem: "Falhou." } },
    });
    renderizarEm("/gestao/produtos/5");
    const chave = await screen.findByRole("checkbox", { name: "Monitorar" });
    await userEvent.click(chave);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(chave).toBeChecked();
  });

  it("sem editar_catalogo a chave some", async () => {
    apiFalsa({
      ...base, "GET /api/auth/eu": ok({ ...EU_OPERADOR, permissoes: EU_OPERADOR.permissoes.filter((p) => p !== "editar_catalogo") }),
      "GET /api/gestao/produtos/5": ok(DADOS),
    });
    renderizarEm("/gestao/produtos/5");
    await screen.findByRole("heading", { name: "Lair of the Hydra" });
    expect(screen.queryByRole("checkbox", { name: "Monitorar" })).not.toBeInTheDocument();
  });
});
