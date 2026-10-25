// Texto de mensagem do WhatsApp: *negrito* e _itálico_ viram <strong>/<em>; todo o resto é texto puro (nada de HTML cru).
import type { ReactNode } from "react";

// O marcador abre no começo ou depois de espaço/pontuação e fecha antes de espaço/pontuação, como no WhatsApp
// (assim "snake_case_nome" não vira itálico).
const MARCADOR = /(^|[\s([{>])([*_])(?=\S)([^*_\n]*?\S)\2(?=$|[\s.,;:!?)\]}])/g;

export function partesWhatsApp(texto: string): ReactNode[] {
  const saida: ReactNode[] = [];
  let resto = 0;
  let chave = 0;
  for (const m of texto.matchAll(MARCADOR)) {
    const inicio = m.index + m[1].length;
    if (inicio > resto) saida.push(texto.slice(resto, inicio));
    saida.push(m[2] === "*" ? <strong key={chave++}>{m[3]}</strong> : <em key={chave++}>{m[3]}</em>);
    resto = m.index + m[0].length;
  }
  if (resto < texto.length) saida.push(texto.slice(resto));
  return saida;
}

export function TextoWhatsApp({ texto }: { texto: string }) {
  return <div className="whitespace-pre-wrap break-words">{partesWhatsApp(texto)}</div>;
}
