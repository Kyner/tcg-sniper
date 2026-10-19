// Guardas das rotas. Só esconde: quem decide é sempre a API.
import type { ReactNode } from "react";
import { Navigate, Outlet } from "react-router";
import { useSessao } from "../sessao";
import type { Permissao } from "../tipos";
import { Carregando } from "./Carregando";
import { Layout } from "./Layout";

/** Exige sessão: sem login vai para /entrar; com login mostra o menu e a página. */
export function RotaProtegida() {
  const { sessao } = useSessao();
  if (sessao.estado === "carregando") return <Carregando />;
  if (sessao.estado !== "logado") return <Navigate to="/entrar" replace />;
  return (
    <Layout>
      <Outlet />
    </Layout>
  );
}

/** Mostra a página só com a permissão; sem ela, /sem-acesso. */
export function Exige({ permissao, children }: { permissao: Permissao; children: ReactNode }) {
  const { pode } = useSessao();
  return pode(permissao) ? <>{children}</> : <Navigate to="/sem-acesso" replace />;
}
