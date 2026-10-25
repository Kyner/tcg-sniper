// Selo do estado de um serviço: o único lugar que liga o estado à classe e ao rótulo (classes por extenso).
import type { Estado } from "../tipos";

const SELOS: Record<Estado, { classe: string; rotulo: string }> = {
  rodando: { classe: "badge badge-success", rotulo: "rodando" },
  esperando: { classe: "badge badge-ghost", rotulo: "esperando" },
  atrasado: { classe: "badge badge-warning", rotulo: "atrasado" },
  com_problema: { classe: "badge badge-error", rotulo: "com problema" },
  desligado: { classe: "badge badge-neutral", rotulo: "desligado" },
};

export function SeloEstado({ estado }: { estado: Estado }) {
  const selo = SELOS[estado];
  return <span className={selo.classe}>{selo.rotulo}</span>;
}
