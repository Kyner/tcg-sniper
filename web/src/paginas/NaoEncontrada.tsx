// Rota que não existe.
import { Link } from "react-router";

export function NaoEncontrada() {
  return (
    <main className="hero min-h-screen bg-base-200">
      <div className="hero-content text-center">
        <div className="max-w-md space-y-4">
          <h1 className="text-2xl font-bold">Página não encontrada</h1>
          <Link className="btn btn-primary" to="/">
            Ir para o início
          </Link>
        </div>
      </div>
    </main>
  );
}
