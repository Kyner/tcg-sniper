// Guarda de rota que pede várias permissões de uma vez. Só esconde: quem decide é sempre a API.
import type { ReactNode } from "react";
import { Navigate } from "react-router";
import { useSessao } from "../sessao";
import type { Permissao } from "../tipos";

/** Mostra a página só com todas as permissões; faltando alguma, /sem-acesso. */
export function ExigeTodas({ permissoes, children }: { permissoes: Permissao[]; children: ReactNode }) {
  const { pode } = useSessao();
  return permissoes.every((p) => pode(p)) ? <>{children}</> : <Navigate to="/sem-acesso" replace />;
}
