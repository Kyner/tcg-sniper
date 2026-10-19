// Tema claro (winter) ou escuro (night), guardado no localStorage com a mesma chave do admin antigo.
export type Tema = "winter" | "night";

const CHAVE = "tema";

export function temaEscuroAgora(): boolean {
  const atual = document.documentElement.dataset.theme;
  if (atual) return atual === "night";
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function aplicarTema(tema: Tema): void {
  document.documentElement.dataset.theme = tema;
  try {
    localStorage.setItem(CHAVE, tema);
  } catch {
    // navegador sem localStorage: o tema vale só nesta página
  }
}
