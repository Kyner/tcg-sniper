// Área de gestão: atalhos para as telas novas (só as que a pessoa pode) e links para o admin antigo.
import { Link } from "react-router";
import { enderecoAdminAntigo } from "../enderecos";
import { useSessao } from "../sessao";

const TELAS_ANTIGAS = [
  ["Dashboard", ""],
  ["Serviços", "servicos"],
  ["Casamentos", "casamentos"],
  ["Catálogo", "catalogo"],
  ["Ofertas", "ofertas"],
  ["Mensagens", "mensagens"],
  ["Configurações", "configuracoes"],
  ["Logs", "logs"],
] as const;

export function Gestao() {
  const { pode } = useSessao();
  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold">Gestão</h1>
      <div className="grid gap-4 sm:grid-cols-2">
        {pode("gerir_usuarios") && (
          <Link to="/gestao/usuarios" className="card bg-base-100 shadow-sm">
            <div className="card-body">
              <h2 className="card-title">Usuários</h2>
              <p>Quem entra no site, o papel de cada um e as sessões abertas.</p>
            </div>
          </Link>
        )}
        {pode("gerir_acessos") && (
          <Link to="/gestao/acessos" className="card bg-base-100 shadow-sm">
            <div className="card-body">
              <h2 className="card-title">Acessos</h2>
              <p>O que cada papel pode fazer (grade papel × permissão).</p>
            </div>
          </Link>
        )}
        {pode("ver_documentacao_api") && (
          <a href="/api/docs" className="card bg-base-100 shadow-sm">
            <div className="card-body">
              <h2 className="card-title">Documentação da API</h2>
              <p>As rotas da API (OpenAPI).</p>
            </div>
          </a>
        )}
      </div>
      <div className="card bg-base-100 shadow-sm">
        <div className="card-body">
          <h2 className="card-title">Ainda no admin antigo</h2>
          <p className="text-sm">Estas telas mudam para cá nas próximas fases. O admin antigo pede a senha dele.</p>
          <ul className="menu w-full">
            {TELAS_ANTIGAS.map(([nome, caminho]) => (
              <li key={nome}>
                <a href={enderecoAdminAntigo(caminho)} target="_blank" rel="noreferrer">
                  {nome}
                </a>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
