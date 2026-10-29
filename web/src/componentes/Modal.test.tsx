import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { Modal } from "./Modal";

function Tela() {
  const [aberto, setAberto] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setAberto(true)}>Abrir janela</button>
      <button type="button">Outro botão</button>
      {aberto && (
        <Modal tituloId="titulo-teste" aoFechar={() => setAberto(false)}>
          <div className="modal-box">
            <h3 id="titulo-teste">Janela de teste</h3>
            <button type="button" onClick={() => setAberto(false)}>Fechar janela</button>
          </div>
        </Modal>
      )}
    </>
  );
}

describe("Modal", () => {
  it("ao fechar, o foco volta para o botão que abriu", async () => {
    render(<Tela />);
    const abrir = screen.getByRole("button", { name: "Abrir janela" });
    await userEvent.click(abrir);
    await userEvent.click(screen.getByRole("button", { name: "Fechar janela" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(abrir).toHaveFocus();
  });

  it("fechar com Esc também devolve o foco", async () => {
    render(<Tela />);
    const abrir = screen.getByRole("button", { name: "Abrir janela" });
    await userEvent.click(abrir);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(abrir).toHaveFocus();
  });
});
