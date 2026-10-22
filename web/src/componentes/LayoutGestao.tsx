// Moldura da gestão: menu lateral (gaveta no celular) com só o que a pessoa pode, e a página ao lado.
import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router";
import { chamarApi } from "../api";
import { enderecoAdminAntigo } from "../enderecos";
import { useSessao } from "../sessao";
import type { MenuGestao, Permissao } from "../tipos";

const TELAS_ANTIGAS: readonly (readonly [string, string, Permissao])[] = [
  ["Ofertas", "ofertas", "ver_servicos"],
  ["Serviços", "servicos", "ver_servicos"],
  ["Mensagens", "mensagens", "ver_mensagens"],
  ["Configurações", "configuracoes", "ver_configuracoes"],
  ["Logs", "logs", "ver_logs"],
];

const RECARGA_MS = 60_000;

export function LayoutGestao() {
  const { pode } = useSessao();
  const [esperando, setEsperando] = useState(0);
  const veCasamentos = pode("revisar_casamentos");

  useEffect(() => {
    if (!veCasamentos) return;
    let vivo = true;
    const buscar = () =>
      chamarApi<MenuGestao>("/api/gestao/menu")
        .then((m) => {
          if (vivo) setEsperando(m.casamentos_esperando);
        })
        .catch(() => undefined); // o selo é só um aviso: se falhar, o menu segue sem ele
    void buscar();
    const timer = setInterval(() => void buscar(), RECARGA_MS);
    return () => {
      vivo = false;
      clearInterval(timer);
    };
  }, [veCasamentos]);

  return (
    <div className="drawer lg:drawer-open">
      <input id="menu-gestao" type="checkbox" className="drawer-toggle" />
      <div className="drawer-content">
        <label htmlFor="menu-gestao" className="btn btn-ghost btn-sm mb-2 lg:hidden">
          ☰ Menu da gestão
        </label>
        <Outlet />
      </div>
      <div className="drawer-side z-20 lg:z-auto">
        <label htmlFor="menu-gestao" aria-label="Fechar menu" className="drawer-overlay"></label>
        <ul className="menu min-h-full w-56 bg-base-100 p-2 text-base-content">
          <li>
            <NavLink to="/gestao" end>
              Dashboard
            </NavLink>
          </li>
          {veCasamentos && (
            <li>
              <NavLink to="/gestao/casamentos">
                Casamentos
                {esperando > 0 && <span className="badge badge-primary badge-sm">{esperando}</span>}
              </NavLink>
            </li>
          )}
          {pode("ver_catalogo") && (
            <li>
              <NavLink to="/gestao/catalogo">Catálogo</NavLink>
            </li>
          )}
          {TELAS_ANTIGAS.map(
            ([nome, caminho, permissao]) =>
              pode(permissao) && (
                <li key={nome}>
                  <a href={enderecoAdminAntigo(caminho)} target="_blank" rel="noreferrer">
                    {nome}
                  </a>
                </li>
              ),
          )}
          {pode("gerir_usuarios") && (
            <li>
              <NavLink to="/gestao/usuarios">Usuários</NavLink>
            </li>
          )}
          {pode("gerir_acessos") && (
            <li>
              <NavLink to="/gestao/acessos">Acessos</NavLink>
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}
