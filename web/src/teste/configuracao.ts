// Preparação de todo teste (Vitest): matchers do jest-dom e limpeza entre testes.
import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

// A página Oportunidades (com o Recharts) é carregada sob demanda: a 1ª abertura num teste pode passar de 1 s.
configure({ asyncUtilTimeout: 5000 });

class ResizeObserverFalso {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// jsdom não tem ResizeObserver, que o ResponsiveContainer do Recharts usa, nem `scrollTo` (o Layout leva a
// tela nova ao topo).
beforeEach(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverFalso);
  vi.stubGlobal("scrollTo", vi.fn());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});
