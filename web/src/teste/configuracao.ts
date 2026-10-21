// Preparação de todo teste (Vitest): matchers do jest-dom e limpeza entre testes.
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

class ResizeObserverFalso {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// jsdom não tem ResizeObserver, que o ResponsiveContainer do Recharts usa.
beforeEach(() => {
  vi.stubGlobal("ResizeObserver", ResizeObserverFalso);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});
