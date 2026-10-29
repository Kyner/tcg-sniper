// Topo da revisão: voltar à lista, posição na fila, Anterior/Próximo e o menu ⋯ (rebuscar, reavaliar, termos e
// casar por link). "Pular" e "Próximo" levavam ao mesmo produto (não há "visto" a marcar): ficou só "Próximo".
import { useState } from "react";
import { Link } from "react-router";
import type { RevisaoCasamento } from "../../../tipos";

export type AcaoTopo = "rebuscar" | "reavaliar" | "termos";

export function BarraRevisao({
  navegacao, voltar, linkProduto, aoAcao, aoCasarLink,
}: {
  navegacao: RevisaoCasamento["navegacao"];
  voltar: string;
  linkProduto: (id: number) => string;
  aoAcao: (acao: AcaoTopo) => void;
  /** Devolve true quando casou (o campo é limpo). */
  aoCasarLink: (link: string) => Promise<boolean>;
}) {
  const [link, setLink] = useState("");
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Link className="btn btn-ghost btn-sm" to={voltar}>Voltar à lista</Link>
      {navegacao.posicao > 0 ? (
        <span className="badge badge-ghost">{navegacao.posicao} de {navegacao.total}</span>
      ) : (
        <span className="badge badge-ghost">Fora da lista filtrada</span>
      )}
      <div className="join">
        {navegacao.anterior !== null ? (
          <Link className="btn btn-sm join-item" to={linkProduto(navegacao.anterior)}>← Anterior</Link>
        ) : (
          <button type="button" className="btn btn-sm join-item" disabled>← Anterior</button>
        )}
        {navegacao.proximo !== null ? (
          <Link className="btn btn-primary btn-sm join-item" to={linkProduto(navegacao.proximo)}>Próximo →</Link>
        ) : (
          <button type="button" className="btn btn-sm join-item" disabled>Próximo →</button>
        )}
      </div>
      <div className="dropdown dropdown-end ml-auto">
        <div tabIndex={0} role="button" className="btn btn-ghost btn-sm" aria-label="Mais ações">⋯</div>
        <div tabIndex={0} className="dropdown-content z-10 mt-2 w-72 rounded-box bg-base-100 p-2 shadow">
          <ul className="menu w-full p-0">
            <li><button type="button" onClick={() => aoAcao("rebuscar")}>Rebuscar agora</button></li>
            <li><button type="button" onClick={() => aoAcao("reavaliar")}>Reavaliar com a IA</button></li>
            <li><button type="button" onClick={() => aoAcao("termos")}>Gerar termos de busca</button></li>
          </ul>
          <form
            className="join mt-2 w-full"
            onSubmit={(ev) => {
              ev.preventDefault();
              const valor = link.trim();
              if (!valor) return;
              void aoCasarLink(valor).then((casou) => {
                if (casou) setLink("");
              });
            }}
          >
            <input
              type="text" className="input input-sm join-item w-full" aria-label="Casar por link ou ASIN"
              placeholder="Casar por link ou ASIN" value={link} onChange={(ev) => setLink(ev.target.value)}
            />
            <button type="submit" className="btn btn-sm join-item">Casar</button>
          </form>
        </div>
      </div>
    </div>
  );
}
