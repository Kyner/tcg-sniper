// Área de negócio (fase 1: só o esqueleto). Nunca mostra dado de gestão: um dia será a área dos assinantes.
import { enderecoAdminAntigo } from "../enderecos";

export function AreaNegocio() {
  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold">Área de negócio</h1>
      <div className="card bg-base-100 shadow-sm">
        <div className="card-body">
          <h2 className="card-title">Em construção</h2>
          <p>Aqui vão ficar as oportunidades, o funil e os resultados do grupo (próxima fase).</p>
          <div className="card-actions">
            <a className="btn btn-primary btn-sm" href={enderecoAdminAntigo()} target="_blank" rel="noreferrer">
              Abrir o admin antigo
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
