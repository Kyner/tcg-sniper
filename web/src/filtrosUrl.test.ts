import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router";
import { describe, expect, it } from "vitest";
import { useFiltrosUrl } from "./filtrosUrl";

const PADROES = { busca: "", situacao: "a", pagina: "1" };
const envolver = (inicial: string) => ({ children }: { children: ReactNode }) =>
  createElement(MemoryRouter, { initialEntries: [inicial] }, children);

function usar(inicial: string) {
  return renderHook(() => ({ f: useFiltrosUrl(PADROES), loc: useLocation() }), { wrapper: envolver(inicial) });
}

describe("useFiltrosUrl", () => {
  it("lê da URL e usa os padrões onde falta", () => {
    const { result } = usar("/x?busca=lair&pagina=3");
    expect(result.current.f[0]).toEqual({ busca: "lair", situacao: "a", pagina: "3" });
  });

  it("grava na URL e volta a pagina para 1 quando outro filtro muda", () => {
    const { result } = usar("/x?pagina=3");
    act(() => result.current.f[1]({ situacao: "b" }));
    expect(result.current.f[0]).toEqual({ busca: "", situacao: "b", pagina: "1" });
    expect(result.current.loc.search).toBe("?situacao=b");
  });

  it("mudar só a pagina mantém a página pedida", () => {
    const { result } = usar("/x?busca=a");
    act(() => result.current.f[1]({ pagina: "2" }));
    expect(result.current.f[0].pagina).toBe("2");
    expect(result.current.loc.search).toBe("?busca=a&pagina=2");
  });
});
