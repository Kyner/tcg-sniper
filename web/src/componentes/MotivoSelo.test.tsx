import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MotivoSelo } from "./MotivoSelo";

describe("MotivoSelo", () => {
  it("mostra o rótulo de produto desativado", () => {
    render(<MotivoSelo motivo="produto_desativado" />);
    expect(screen.getByText("produto desativado")).toBeInTheDocument();
  });
});
