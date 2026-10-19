// A API não respondeu (container parado, banco fora): explica e deixa tentar de novo.
export function Indisponivel({ aoTentar }: { aoTentar: () => void }) {
  return (
    <main className="hero min-h-screen bg-base-200">
      <div className="hero-content text-center">
        <div className="max-w-md space-y-4">
          <h1 className="text-2xl font-bold">Sistema indisponível</h1>
          <p>Não foi possível falar com o servidor. Confira se os containers estão de pé (docker compose ps) e tente de novo.</p>
          <button type="button" className="btn btn-primary" onClick={aoTentar}>
            Tentar de novo
          </button>
        </div>
      </div>
    </main>
  );
}
