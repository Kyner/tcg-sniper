// 403: o papel da pessoa não permite a tela.
import { Link } from "react-router";
import { paginaInicial } from "../permissoes";
import { useSessao } from "../sessao";

export function SemAcesso() {
  const { sessao } = useSessao();
  const inicio = sessao.estado === "logado" ? paginaInicial(sessao.eu.permissoes) : "/entrar";
  return (
    <section className="hero py-16">
      <div className="hero-content text-center">
        <div className="max-w-md space-y-4">
          <h1 className="text-2xl font-bold">Sem acesso</h1>
          <p>Seu papel não permite abrir esta tela. Se precisar, peça a quem cuida dos acessos.</p>
          {inicio !== "/sem-acesso" && (
            <Link className="btn btn-primary" to={inicio}>
              Voltar ao início
            </Link>
          )}
        </div>
      </div>
    </section>
  );
}
