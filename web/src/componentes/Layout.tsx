// Moldura das telas logadas: barra com o menu (só o que a pessoa pode), nome, papel, tema e Sair.
import type { ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router";
import { ROTULO_PAPEL } from "../permissoes";
import { useSessao } from "../sessao";
import { BotaoTema } from "./BotaoTema";

export function Layout({ children }: { children: ReactNode }) {
  const { sessao, pode, sair } = useSessao();
  const navegar = useNavigate();
  const emGestao = useLocation().pathname.startsWith("/gestao"); // a gestão tem menu lateral: precisa de mais largura
  if (sessao.estado !== "logado") return null;
  const { eu } = sessao;

  async function aoSair() {
    await sair();
    navegar("/entrar", { replace: true });
  }

  const links = (
    <>
      {pode("ver_area_negocio") && (
        <li>
          <NavLink to="/" end>
            Negócio
          </NavLink>
        </li>
      )}
      {pode("ver_area_gestao") && (
        <li>
          <NavLink to="/gestao">Gestão</NavLink>
        </li>
      )}
    </>
  );

  return (
    <div className="min-h-screen bg-base-200">
      <nav className="navbar bg-base-100 shadow-sm">
        <div className="navbar-start">
          <div className="dropdown lg:hidden">
            <div tabIndex={0} role="button" className="btn btn-ghost btn-sm" aria-label="Menu">
              ☰
            </div>
            <ul tabIndex={0} className="menu menu-sm dropdown-content z-10 mt-3 w-52 rounded-box bg-base-100 p-2 shadow">
              {links}
            </ul>
          </div>
          <Link to="/" className="btn btn-ghost text-lg">
            TCG Sniper
          </Link>
        </div>
        <div className="navbar-center hidden lg:flex">
          <ul className="menu menu-horizontal px-1">{links}</ul>
        </div>
        <div className="navbar-end gap-1">
          <span className="hidden text-sm sm:inline">{eu.nome}</span>
          <span className="badge badge-ghost badge-sm">{ROTULO_PAPEL[eu.papel]}</span>
          <BotaoTema />
          <button type="button" className="btn btn-ghost btn-sm" onClick={aoSair}>
            Sair
          </button>
        </div>
      </nav>
      <main className={emGestao ? "mx-auto max-w-7xl p-4" : "mx-auto max-w-5xl p-4"}>{children}</main>
    </div>
  );
}
