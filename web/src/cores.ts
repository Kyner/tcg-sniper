// Cores do tema do DaisyUI lidas do CSS, refeitas quando o tema muda (data-theme no <html>).
import { useEffect, useState } from "react";

export interface CoresTema { primaria: string; secundaria: string; texto: string; aviso: string; sucesso: string }

function ler(): CoresTema {
  const css = getComputedStyle(document.documentElement);
  const v = (nome: string, padrao: string) => css.getPropertyValue(nome).trim() || padrao;
  return {
    primaria: v("--color-primary", "#570df8"),
    secundaria: v("--color-secondary", "#f000b8"),
    texto: v("--color-base-content", "#1f2937"),
    aviso: v("--color-warning", "#fbbd23"),
    sucesso: v("--color-success", "#36d399"),
  };
}

export function useCoresTema(): CoresTema {
  const [cores, setCores] = useState(ler);
  useEffect(() => {
    const observador = new MutationObserver(() => setCores(ler()));
    observador.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observador.disconnect();
  }, []);
  return cores;
}
