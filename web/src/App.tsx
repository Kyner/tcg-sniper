// Rotas do site. /entrar é aberta; o resto exige sessão e, cada tela, a sua permissão.
import { lazy, Suspense } from "react";
import { BrowserRouter, Outlet, Route, Routes } from "react-router";
import { Carregando } from "./componentes/Carregando";
import { Exige, RotaProtegida } from "./componentes/RotaProtegida";
import { Acessos } from "./paginas/Acessos";
import { Entrar } from "./paginas/Entrar";
import { Gestao } from "./paginas/Gestao";
import { Indisponivel } from "./paginas/Indisponivel";
import { NaoEncontrada } from "./paginas/NaoEncontrada";
import { SemAcesso } from "./paginas/SemAcesso";
import { Usuarios } from "./paginas/Usuarios";
import { SessaoProvider, useSessao } from "./sessao";

// As páginas Oportunidades e Produto trazem o Recharts: vão em pedaços próprios, carregados só ao abrir a rota.
const Oportunidades = lazy(() => import("./paginas/Oportunidades").then((m) => ({ default: m.Oportunidades })));
const Produto = lazy(() => import("./paginas/Produto").then((m) => ({ default: m.Produto })));

export function Rotas() {
  const { sessao, recarregar } = useSessao();
  if (sessao.estado === "indisponivel") return <Indisponivel aoTentar={() => void recarregar()} />;
  return (
    <Routes>
      <Route path="/entrar" element={<Entrar />} />
      <Route element={<RotaProtegida />}>
        <Route
          path="/"
          element={
            <Exige permissao="ver_area_negocio">
              <Exige permissao="ver_oportunidades">
                <Suspense fallback={<Carregando />}>
                  <Oportunidades />
                </Suspense>
              </Exige>
            </Exige>
          }
        />
        <Route
          path="/produtos/:id"
          element={
            <Exige permissao="ver_area_negocio">
              <Exige permissao="ver_oportunidades">
                <Suspense fallback={<Carregando />}>
                  <Produto />
                </Suspense>
              </Exige>
            </Exige>
          }
        />
        <Route
          path="/gestao"
          element={
            <Exige permissao="ver_area_gestao">
              <Outlet />
            </Exige>
          }
        >
          <Route index element={<Gestao />} />
          <Route
            path="usuarios"
            element={
              <Exige permissao="gerir_usuarios">
                <Usuarios />
              </Exige>
            }
          />
          <Route
            path="acessos"
            element={
              <Exige permissao="gerir_acessos">
                <Acessos />
              </Exige>
            }
          />
        </Route>
        <Route path="/sem-acesso" element={<SemAcesso />} />
      </Route>
      <Route path="*" element={<NaoEncontrada />} />
    </Routes>
  );
}

export default function App() {
  return (
    <SessaoProvider>
      <BrowserRouter>
        <Rotas />
      </BrowserRouter>
    </SessaoProvider>
  );
}
