// Guarda da regra do projeto: classes do DaisyUI/Tailwind escritas por extenso, nada montado por concatenação
// (o Tailwind só gera as classes que aparecem literais no código).
import { describe, expect, it } from "vitest";

const FONTES = import.meta.glob("./**/*.tsx", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

// className com template string (`... ${x}`) ou com soma de textos.
const MONTADA = /className=\{\s*`|className=\{[^}]*["'`]\s*\+|className=\{[^}]*\+\s*["'`]/;

function montadas(): string[] {
  const achadas: string[] = [];
  for (const [arquivo, texto] of Object.entries(FONTES)) {
    if (arquivo.endsWith(".test.tsx")) continue;
    texto.split("\n").forEach((linha, i) => {
      if (MONTADA.test(linha)) achadas.push(`${arquivo}:${i + 1}: ${linha.trim()}`);
    });
  }
  return achadas;
}

describe("classes literais", () => {
  it("o padrão pega template string e soma", () => {
    expect(MONTADA.test('<div className={`${classe} alert-vertical`}>')).toBe(true);
    expect(MONTADA.test('<div className={"btn " + tamanho}>')).toBe(true);
    expect(MONTADA.test('<div className={erro ? "input input-error" : "input"}>')).toBe(false);
  });

  it("nenhum componente monta className por concatenação", () => {
    expect(Object.keys(FONTES).length).toBeGreaterThan(20);
    expect(montadas()).toEqual([]);
  });
});
