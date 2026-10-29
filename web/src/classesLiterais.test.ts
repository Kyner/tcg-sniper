// Guarda da regra do projeto: classes do DaisyUI/Tailwind escritas por extenso, nada montado por concatenação
// (o Tailwind só gera as classes que aparecem literais no código).
import { describe, expect, it } from "vitest";

const FONTES = import.meta.glob(["./**/*.tsx", "./**/*.ts"], {
  query: "?raw", import: "default", eager: true,
}) as Record<string, string>;

// className com template string em qualquer ponto antes do primeiro "}" (logo depois do "{", noutra linha ou num
// ramo de ternário) ou com soma de textos.
const CLASSNAME_MONTADA = /className=\{[^}]*`|className=\{[^}]*["'`]\s*\+|className=\{[^}]*\+\s*["'`]/;
// Template string com uma classe do DaisyUI/Tailwind e uma interpolação (ex.: `btn-${tamanho}`, `alert ${x} text-error`).
const NOMES = "btn|badge|alert|input|select|toggle|tooltip|card|menu|modal|progress|checkbox|join|drawer|dropdown|collapse|text|bg|border|list";
const TOKEN = String.raw`\b(?:${NOMES})-[a-z0-9]`;
const TEMPLATE_COM_CLASSE = new RegExp(
  [
    String.raw`\x60[^\x60]*${TOKEN}[^\x60]*\$\{`, // classe antes da interpolação
    String.raw`\x60[^\x60]*\$\{[^\x60]*${TOKEN}`, // classe depois da interpolação
    String.raw`\x60[^\x60]*\b(?:${NOMES})-\$\{`, // a própria classe interpolada
  ].join("|"),
);

/** As linhas (uma vez cada) onde começa um trecho suspeito. */
function achados(texto: string): string[] {
  const linhas = new Map<number, string>();
  const linhaDe = (pos: number) => texto.slice(0, pos).split("\n").length;
  for (const padrao of [CLASSNAME_MONTADA, TEMPLATE_COM_CLASSE]) {
    for (const m of texto.matchAll(new RegExp(padrao, "g"))) {
      const n = linhaDe(m.index);
      if (!linhas.has(n)) linhas.set(n, `${n}: ${m[0].slice(0, 80)}`);
    }
  }
  return [...linhas.values()];
}

function montadas(): string[] {
  return Object.entries(FONTES)
    .filter(([arquivo]) => !arquivo.endsWith(".test.tsx") && !arquivo.endsWith(".test.ts"))
    .flatMap(([arquivo, texto]) => achados(texto).map((a) => `${arquivo}:${a}`));
}

describe("classes literais", () => {
  it("o padrão pega template string, soma, ramo de ternário, outra linha e template com classe", () => {
    expect(achados('<div className={`${classe} alert-vertical`}>')).toHaveLength(1);
    expect(achados('<div className={"btn " + tamanho}>')).toHaveLength(1);
    expect(achados('<div className={erro ? `input ${x}` : "input"}>')).toHaveLength(1);
    expect(achados('<div\n  className={\n    `card ${x}`\n  }>')).toHaveLength(1);
    expect(achados("const c = `btn-${tamanho}`;")).toHaveLength(1);
    expect(achados("const c = `alert ${x} text-error`;")).toHaveLength(1);
    expect(achados('<div className={erro ? "input input-error" : "input"}>')).toEqual([]);
    expect(achados("const t = `${n} produtos alterados`;")).toEqual([]);
  });

  it("nenhum arquivo monta classes por concatenação", () => {
    expect(Object.keys(FONTES).length).toBeGreaterThan(20);
    expect(montadas()).toEqual([]);
  });
});
