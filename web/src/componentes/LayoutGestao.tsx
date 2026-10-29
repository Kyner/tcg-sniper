// Moldura da gestão: menu lateral (gaveta no celular) com só o que a pessoa pode, e a página ao lado.
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { chamarApi } from "../api";
import { useSessao } from "../sessao";
import type { MenuGestao } from "../tipos";

const RECARGA_MS = 60_000;

export function LayoutGestao() {
  const { pode } = useSessao();
  const [esperando, setEsperando] = useState(0);
  const veCasamentos = pode("revisar_casamentos");
  const [aberto, setAberto] = useState(false);
  const { pathname } = useLocation();

  // No celular, trocar de tela fecha a gaveta.
  useEffect(() => setAberto(false), [pathname]);

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
      <input
        id="menu-gestao"
        type="checkbox"
        className="drawer-toggle"
        checked={aberto}
        onChange={(e) => setAberto(e.target.checked)}
      />
      <div className="drawer-content">
        <button
          type="button" className="btn btn-ghost btn-sm mb-2 lg:hidden" aria-expanded={aberto} aria-controls="gaveta-gestao"
          onClick={() => setAberto((a) => !a)}
        >
          ☰ Menu da gestão
        </button>
        <Outlet />
      </div>
      <div id="gaveta-gestao" className="drawer-side z-20 lg:z-auto">
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
          {pode("ver_catalogo") && (
            <li>
              <NavLink to="/gestao/ofertas">Ofertas</NavLink>
            </li>
          )}
          {pode("ver_servicos") && (
            <li>
              <NavLink to="/gestao/servicos">Serviços</NavLink>
            </li>
          )}
          {pode("ver_logs") && (
            <li>
              <NavLink to="/gestao/atividade">Atividade</NavLink>
            </li>
          )}
          {pode("ver_configuracoes") && (
            <li>
              <NavLink to="/gestao/configuracoes">Configurações</NavLink>
            </li>
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
          {pode("ver_documentacao_api") && (
            <li>
              <a href="/api/docs">Documentação da API</a>
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}
