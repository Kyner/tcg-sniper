// Seletor de período (join de botões do DaisyUI). Classes literais: ativo = btn-primary.
import type { Periodo } from "../tipos";

const OPCOES: { valor: Periodo; rotulo: string }[] = [
  { valor: "7d", rotulo: "7 dias" },
  { valor: "30d", rotulo: "30 dias" },
  { valor: "90d", rotulo: "90 dias" },
  { valor: "tudo", rotulo: "Tudo" },
];

export function SeletorPeriodo({ valor, aoMudar }: { valor: Periodo; aoMudar: (p: Periodo) => void }) {
  return (
    <div className="join" role="group" aria-label="Período">
      {OPCOES.map((o) => (
        <button
          key={o.valor}
          type="button"
          className={o.valor === valor ? "btn btn-sm btn-primary join-item" : "btn btn-sm join-item"}
          aria-pressed={o.valor === valor}
          onClick={() => aoMudar(o.valor)}
        >
          {o.rotulo}
        </button>
      ))}
    </div>
  );
}
