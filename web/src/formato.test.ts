import { describe, expect, it } from "vitest";
import { duracao, pct, reais, ROTULOS_MOTIVO } from "./formato";

describe("formato", () => {
  it("reais em pt-BR", () => {
    expect(reais("1299.9")).toBe("R$ 1.299,90");
    expect(reais(null)).toBe("—");
  });
  it("percentual", () => {
    expect(pct("27.4")).toBe("27,4%");
    expect(pct(null)).toBe("—");
  });
  it("duração", () => {
    expect(duracao(45)).toBe("45 min");
    expect(duracao(200)).toBe("3 h 20 min");
    expect(duracao(120)).toBe("2 h");
    expect(duracao(60 * 24 * 2 + 60)).toBe("2 d 1 h");
    expect(duracao(null)).toBe("—");
  });
});

describe("rótulos de motivo", () => {
  it("produto desativado tem rótulo", () => {
    expect(ROTULOS_MOTIVO.produto_desativado).toBe("produto desativado");
  });
});
