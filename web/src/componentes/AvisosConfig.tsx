// Avisos do WhatsApp: agrupados por área (quem manda), com busca, chave que liga/desliga no lugar e o exemplo da
// mensagem ao tocar.
import { useState } from "react";
import { chamarApi } from "../api";
import { useSessao } from "../sessao";
import type { AvisoConfig } from "../tipos";
import { TextoWhatsApp } from "./TextoWhatsApp";

interface Props {
  avisos: AvisoConfig[];
  editavel: boolean;
  aoAtualizar: (aviso: AvisoConfig) => void;
}

export function AvisosConfig({ avisos, editavel, aoAtualizar }: Props) {
  const { tratarErro } = useSessao();
  const [busca, setBusca] = useState("");
  const [exemplo, setExemplo] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const termo = busca.trim().toLowerCase();
  const filtrados = avisos.filter((a) => `${a.titulo} ${a.descricao}`.toLowerCase().includes(termo));
  const areas = [...new Set(filtrados.map((a) => a.area))];

  const alternar = async (aviso: AvisoConfig) => {
    setErro(null);
    try {
      aoAtualizar(
        await chamarApi<AvisoConfig>(`/api/gestao/avisos/${aviso.tipo}`, { metodo: "PATCH", corpo: { ligado: !aviso.ligado } }),
      );
    } catch (e) {
      setErro(tratarErro(e));
    }
  };

  return (
    <section id="avisos" className="space-y-3 scroll-mt-4">
      <h2 className="text-lg font-semibold">Avisos do WhatsApp</h2>
      <p className="text-sm text-base-content/70">Quais avisos o sistema manda. Desligar um tipo para de enviá-lo.</p>
      <input
        type="search"
        className="input input-bordered w-full"
        placeholder="Buscar aviso"
        aria-label="Buscar aviso"
        value={busca}
        onChange={(e) => setBusca(e.target.value)}
      />
      {erro && (
        <div role="alert" className="alert alert-error">
          {erro}
        </div>
      )}
      {areas.length === 0 && <p className="text-sm">Nenhum aviso encontrado.</p>}
      {areas.map((area) => (
        <div key={area} className="space-y-2">
          <h3 className="font-semibold">{area}</h3>
          <ul className="space-y-2">
            {filtrados
              .filter((a) => a.area === area)
              .map((a) => (
                <li key={a.tipo} className="rounded-box border border-base-300 bg-base-100 p-3">
                  <div className="flex items-start gap-3">
                    <input
                      type="checkbox"
                      className="toggle toggle-primary mt-1"
                      aria-label={`Ligar aviso ${a.titulo}`}
                      checked={a.ligado}
                      disabled={!editavel}
                      onChange={() => void alternar(a)}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="font-medium">{a.titulo}</p>
                      <p className="text-sm text-base-content/70">{a.descricao}</p>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
                        <code>{a.tipo}</code>
                        <span className="badge badge-ghost">{a.destino}</span>
                        {a.agrupa && <span className="badge badge-ghost">agrupa</span>}
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          aria-label={`Ver exemplo: ${a.titulo}`}
                          onClick={() => setExemplo(exemplo === a.tipo ? null : a.tipo)}
                        >
                          Ver exemplo
                        </button>
                      </div>
                      {exemplo === a.tipo && (
                        <div className="chat mt-2 rounded-box bg-base-200 p-3 text-sm">
                          <TextoWhatsApp texto={a.exemplo} />
                        </div>
                      )}
                    </div>
                  </div>
                </li>
              ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
