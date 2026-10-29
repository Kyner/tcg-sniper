// O produto da Liga na revisão e os parecidos dele. No celular o produto fica compacto acima (order-1), os anúncios
// logo depois (order-2, na página) e os parecidos por último (order-3); a partir do lg tudo fica na coluna fixa.
import { Link } from "react-router";
import { Foto } from "../../../componentes/Foto";
import { reais } from "../../../formato";
import type { ProdutoParecido, RevisaoCasamento } from "../../../tipos";

export function ProdutoDaLiga({ produto }: { produto: RevisaoCasamento["produto"] }) {
  return (
    <div className="card card-border card-sm order-1 bg-base-100 lg:order-none">
      <div className="card-body">
        <div className="flex gap-3 lg:flex-col">
          <Foto src={produto.imagem} alt={produto.nome} tamanho="a" />
          <div className="min-w-0 space-y-1">
            <h1 className="text-lg font-bold lg:text-xl">{produto.nome}</h1>
            {produto.nome_en && produto.nome_en !== produto.nome && (
              <p className="text-sm opacity-70">{produto.nome_en}</p>
            )}
            <div className="flex flex-wrap items-center gap-1 text-sm">
              {produto.categoria && <span className="badge badge-outline badge-sm">{produto.categoria}</span>}
              <span>a partir de <strong>{reais(produto.preco_liga)}</strong></span>
              {produto.lojas !== null && <span className="opacity-70">· {produto.lojas} lojas</span>}
            </div>
            <div className="flex flex-wrap gap-1">
              {produto.pistas.map((p) => <span key={p} className="badge badge-ghost badge-sm">{p}</span>)}
            </div>
            <a className="link text-sm" href={produto.url} target="_blank" rel="noreferrer">Ver na LigaMagic ↗</a>
          </div>
        </div>
      </div>
    </div>
  );
}

export function ParecidosNaLiga({
  parecidos, linkProduto,
}: {
  parecidos: ProdutoParecido[];
  linkProduto: (id: number) => string;
}) {
  if (parecidos.length === 0) return null;
  return (
    <div className="card card-border card-sm order-3 bg-base-100 lg:order-none">
      <div className="card-body space-y-1">
        <h2 className="text-sm font-semibold">Parecidos na Liga</h2>
        <ul className="list" aria-label="Parecidos na Liga">
          {parecidos.map((p) => (
            <li key={p.id} className="list-row items-center p-1">
              <Foto src={p.imagem} alt={p.nome} tamanho="p" />
              <Link className="link list-col-grow truncate text-sm" to={linkProduto(p.id)}>{p.nome}</Link>
              <span className="text-xs opacity-70">{reais(p.preco_liga)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
