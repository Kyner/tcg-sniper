// Troca entre o tema claro (winter) e o escuro (night).
import { useState } from "react";
import { aplicarTema, temaEscuroAgora } from "../tema";

export function BotaoTema() {
  const [escuro, setEscuro] = useState(temaEscuroAgora);

  function trocar() {
    aplicarTema(escuro ? "winter" : "night");
    setEscuro(!escuro);
  }

  return (
    <button type="button" className="btn btn-ghost btn-sm" aria-label="Trocar tema" aria-pressed={escuro} onClick={trocar}>
      {escuro ? "☀" : "☾"}
    </button>
  );
}
