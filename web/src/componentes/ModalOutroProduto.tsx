// "É de outro produto…": produtos da Liga parecidos com o anúncio e a busca no catálogo, cada um com foto.
import { useCallback, useEffect, useState } from "react";
import { chamarApi } from "../api";
import { reais } from "../formato";
import { useSessao } from "../sessao";
import type { AnuncioRevisao, ProdutoParecido } from "../tipos";
import { Foto } from "./Foto";
import { Modal } from "./Modal";

export function ModalOutroProduto({
  anuncio,
  produtoId,
  aoEscolher,
  aoFechar,
}: {
  anuncio: AnuncioRevisao;
  produtoId: number;
  aoEscolher: (produto: ProdutoParecido) => void;
  aoFechar: () => void;
}) {
  const { tratarErro } = useSessao();
  const [texto, setTexto] = useState("");
  const [itens, setItens] = useState<ProdutoParecido[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const buscar = useCallback(
    async (busca: string) => {
      setErro(null);
      setItens(null);
      try {
        const q = `busca=${encodeURIComponent(busca)}&de=${produtoId}`;
        setItens(await chamarApi<ProdutoParecido[]>(`/api/gestao/casamentos/anuncios/${anuncio.anuncio_id}/produtos?${q}`));
      } catch (e) {
        setErro(tratarErro(e));
        setItens([]);
      }
    },
    [anuncio.anuncio_id, produtoId, tratarErro],
  );

  useEffect(() => {
    void buscar("");
  }, [buscar]);

  return (
    <Modal tituloId="titulo-outro-produto" aoFechar={aoFechar}>
      <div className="modal-box space-y-3">
        <h3 id="titulo-outro-produto" className="text-lg font-bold">É de outro produto</h3>
        <p className="truncate text-sm opacity-70" title={anuncio.titulo}>{anuncio.titulo}</p>
        <form
          className="join w-full"
          onSubmit={(ev) => {
            ev.preventDefault();
            void buscar(texto.trim());
          }}
        >
          <input
            type="search" className="input join-item w-full" aria-label="Buscar no catálogo"
            placeholder="Buscar no catálogo" value={texto} onChange={(ev) => setTexto(ev.target.value)}
          />
          <button type="submit" className="btn join-item">Buscar</button>
        </form>
        {erro && <div role="alert" className="alert alert-error"><span>{erro}</span></div>}
        {itens === null ? (
          <span className="loading loading-spinner" aria-label="Carregando" />
        ) : itens.length === 0 ? (
          <p className="text-sm opacity-70">Nenhum produto encontrado.</p>
        ) : (
          <ul className="list rounded-box bg-base-100" aria-label="Produtos para escolher">
            {itens.map((p) => (
              <li key={p.id} className="list-row items-center">
                <Foto src={p.imagem} alt={p.nome} tamanho="p" />
                <div className="list-col-grow min-w-0">
                  <p className="truncate">{p.nome}</p>
                  <p className="text-xs opacity-70">{reais(p.preco_liga)}</p>
                </div>
                <button type="button" className="btn btn-primary btn-sm" aria-label={`Escolher ${p.nome}`} onClick={() => aoEscolher(p)}>
                  Escolher
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="modal-action">
          <button type="button" className="btn" onClick={aoFechar}>Fechar</button>
        </div>
      </div>
    </Modal>
  );
}
