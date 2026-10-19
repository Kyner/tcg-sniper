// Rota que não existe. "Ir para o início" leva à tela inicial da pessoa (ou a Entrar, sem login).
import { Link } from "react-router";
import { paginaInicial } from "../permissoes";
import { useSessao } from "../sessao";

export function NaoEncontrada() {
  const { sessao } = useSessao();
  const inicio = sessao.estado === "logado" ? paginaInicial(sessao.eu.permissoes) : "/entrar";
  return (
    <main className="hero min-h-screen bg-base-200">
      <div className="hero-content text-center">
        <div className="max-w-md space-y-4">
          <h1 className="text-2xl font-bold">Página não encontrada</h1>
          <Link className="btn btn-primary" to={inicio}>
            Ir para o início
          </Link>
        </div>
      </div>
    </main>
  );
}
