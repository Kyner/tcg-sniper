// Rotas do site. /entrar é aberta; o resto exige sessão e, cada tela, a sua permissão.
import { BrowserRouter, Outlet, Route, Routes } from "react-router";
import { Exige, RotaProtegida } from "./componentes/RotaProtegida";
import { Acessos } from "./paginas/Acessos";
import { AreaNegocio } from "./paginas/AreaNegocio";
import { Entrar } from "./paginas/Entrar";
import { Gestao } from "./paginas/Gestao";
import { Indisponivel } from "./paginas/Indisponivel";
import { NaoEncontrada } from "./paginas/NaoEncontrada";
import { SemAcesso } from "./paginas/SemAcesso";
import { Usuarios } from "./paginas/Usuarios";
import { SessaoProvider, useSessao } from "./sessao";

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
              <AreaNegocio />
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
