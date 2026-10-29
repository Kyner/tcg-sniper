// Categorias da Liga: um chip por ID ("categoria N": ainda não há tabela de nomes). Busca filtra os chips; o campo
// "Adicionar categoria" aceita o número e Enter.
import { useState } from "react";

interface Props {
  ids: number[];
  editavel: boolean;
  aoMudar: (ids: number[]) => void;
  rotulo: string;
}

export function CategoriasConfig({ ids, editavel, aoMudar, rotulo }: Props) {
  const [busca, setBusca] = useState("");
  const [novo, setNovo] = useState("");
  const visiveis = ids.filter((n) => `categoria ${n}`.includes(busca.trim().toLowerCase()));

  const adicionar = () => {
    const n = Number(novo.trim());
    setNovo("");
    if (Number.isInteger(n) && n > 0 && !ids.includes(n)) aoMudar([...ids, n]);
  };

  return (
    <div className="space-y-2" role="group" aria-label={rotulo}>
      <input
        type="search"
        className="input input-bordered input-sm w-full"
        placeholder="Buscar categoria"
        aria-label="Buscar categoria"
        value={busca}
        onChange={(e) => setBusca(e.target.value)}
      />
      <div className="flex flex-wrap gap-2">
        {visiveis.map((n) => (
          <span key={n} className="badge badge-lg gap-1">
            <span>categoria {n}</span>
            {editavel && (
              <button
                type="button"
                className="btn btn-ghost btn-xs btn-circle"
                aria-label={`Remover categoria ${n}`}
                onClick={() => aoMudar(ids.filter((i) => i !== n))}
              >
                ✕
              </button>
            )}
          </span>
        ))}
        {visiveis.length === 0 && <span className="text-sm text-base-content/70">Nenhuma categoria.</span>}
      </div>
      {editavel && (
        <input
          type="text"
          inputMode="numeric"
          className="input input-bordered input-sm w-full"
          placeholder="Número da categoria + Enter"
          aria-label="Adicionar categoria"
          value={novo}
          onChange={(e) => setNovo(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              adicionar();
            }
          }}
        />
      )}
    </div>
  );
}
