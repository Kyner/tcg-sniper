// Rótulos dos papéis e a tela inicial de cada pessoa (pelas permissões que a API devolveu).
import type { Papel, Permissao } from "./tipos";

export const ROTULO_PAPEL: Record<Papel, string> = { grupo: "Grupo", operador: "Operador", admin: "Admin" };

export function paginaInicial(permissoes: Permissao[]): string {
  if (permissoes.includes("ver_area_negocio")) return "/";
  if (permissoes.includes("ver_area_gestao")) return "/gestao";
  return "/sem-acesso";
}
