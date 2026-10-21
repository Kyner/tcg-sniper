// Selo do motivo de encerramento; sem motivo = fechada antes do registro (2026-10-20).
import { ROTULOS_MOTIVO } from "../formato";
import type { Motivo } from "../tipos";

export function MotivoSelo({ motivo, aberta = false }: { motivo: Motivo | null; aberta?: boolean }) {
  if (aberta) return <span className="badge badge-success badge-sm">aberta</span>;
  if (motivo === null) return <span className="badge badge-ghost badge-sm">antes do registro</span>;
  return <span className="badge badge-outline badge-sm">{ROTULOS_MOTIVO[motivo]}</span>;
}
