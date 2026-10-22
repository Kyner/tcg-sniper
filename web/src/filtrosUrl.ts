// Filtros de uma lista guardados na URL (voltar do navegador restaura tudo). Valores iguais ao padrão não vão para a URL.
import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";

export function useFiltrosUrl<T extends Record<string, string>>(
  padroes: T,
): [T, (mudancas: Partial<T>) => void] {
  const [params, setParams] = useSearchParams();
  const chaves = Object.keys(padroes);
  const sinal = chaves.map((k) => params.get(k) ?? "").join("\u0000");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const valores = useMemo(() => {
    const lidos = { ...padroes };
    for (const k of chaves) {
      const v = params.get(k);
      if (v !== null && v !== "") (lidos as Record<string, string>)[k] = v;
    }
    return lidos;
  }, [sinal]);

  const mudar = useCallback(
    (mudancas: Partial<T>) => {
      const proximo: Record<string, string> = { ...valores, ...(mudancas as Record<string, string>) };
      // Qualquer filtro novo recomeça da primeira página, a menos que a própria página tenha sido pedida.
      if ("pagina" in padroes && !("pagina" in mudancas)) proximo.pagina = padroes.pagina;
      const novo = new URLSearchParams();
      for (const k of chaves) if (proximo[k] !== "" && proximo[k] !== padroes[k]) novo.set(k, proximo[k]);
      setParams(novo);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [valores, setParams],
  );
  return [valores, mudar];
}
