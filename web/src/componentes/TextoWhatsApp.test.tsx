import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TextoWhatsApp } from "./TextoWhatsApp";

describe("TextoWhatsApp", () => {
  it("renderiza *negrito* e _itálico_", () => {
    render(<TextoWhatsApp texto={"Achei *Booster Box* por _R$ 100_ hoje"} />);
    expect(screen.getByText("Booster Box").tagName).toBe("STRONG");
    expect(screen.getByText("R$ 100").tagName).toBe("EM");
  });

  it("não interpreta HTML: <b> aparece como texto", () => {
    const { container } = render(<TextoWhatsApp texto={"<b>oi</b> *x*"} />);
    expect(container.querySelector("b")).toBeNull();
    expect(container).toHaveTextContent("<b>oi</b> x");
  });

  it("marcadores soltos ficam como estão e quebras de linha são mantidas", () => {
    const { container } = render(<TextoWhatsApp texto={"a * b\nsnake_case_nome"} />);
    expect(container).toHaveTextContent("a * b");
    expect(container).toHaveTextContent("snake_case_nome");
    expect(container.querySelector("em")).toBeNull();
    expect(container.firstElementChild).toHaveClass("whitespace-pre-wrap");
  });
});
