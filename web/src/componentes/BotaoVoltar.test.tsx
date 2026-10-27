import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";
import { BotaoVoltar } from "./BotaoVoltar";

function montar(entradas: string[], indice: number) {
  return render(
    <MemoryRouter initialEntries={entradas} initialIndex={indice}>
      <Routes>
        <Route path="/anterior" element={<p>página anterior</p>} />
        <Route path="/padrao" element={<p>página padrão</p>} />
        <Route path="/atual" element={<BotaoVoltar padrao="/padrao?x=1" />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("BotaoVoltar", () => {
  it("sem página anterior do site: link para o padrão", () => {
    montar(["/atual"], 0);
    const link = screen.getByRole("link", { name: "Voltar" });
    expect(link).toHaveAttribute("href", "/padrao?x=1");
    expect(link).toHaveClass("btn", "btn-ghost", "btn-sm");
  });

  it("com página anterior: volta no histórico", async () => {
    montar(["/anterior", "/atual"], 1);
    expect(screen.queryByRole("link", { name: "Voltar" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Voltar" }));
    expect(await screen.findByText("página anterior")).toBeInTheDocument();
  });
});
