// Histórico de um produto: curva Amazon × Liga com as oportunidades em faixas e a lista delas (recorrência).
import { useCallback, useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { chamarApi, ErroApi } from "../api";
import { Carregando } from "../componentes/Carregando";
import { CurvaPreco } from "../componentes/CurvaPreco";
import { MotivoSelo } from "../componentes/MotivoSelo";
import { SeletorPeriodo } from "../componentes/SeletorPeriodo";
import { dataHora, duracao, pct, reais } from "../formato";
import { useSessao } from "../sessao";
import type { Historico, Periodo } from "../tipos";
import { NaoEncontrada } from "./NaoEncontrada";

const PERIODOS: readonly Periodo[] = ["7d", "30d", "90d", "tudo"];

function periodoInicial(valor: string | null): Periodo {
  return PERIODOS.find((p) => p === valor) ?? "30d";
}

export function Produto() {
  const { id } = useParams();
  const [busca] = useSearchParams();
  const destaque = busca.get("oportunidade") ? Number(busca.get("oportunidade")) : null;
  const { tratarErro } = useSessao();
  const [periodo, setPeriodo] = useState<Periodo>(() => periodoInicial(busca.get("periodo")));
  const [historico, setHistorico] = useState<Historico | null>(null);
  const [naoExiste, setNaoExiste] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(async (sinal?: { cancelado: boolean }) => {
    setErro(null);
    try {
      const h = await chamarApi<Historico>(`/api/produtos/${id}/historico?periodo=${periodo}`);
      if (sinal?.cancelado) return;
      setNaoExiste(false);
      setHistorico(h);
    } catch (e) {
      if (sinal?.cancelado) return;
      if (e instanceof ErroApi && e.status === 404) setNaoExiste(true);
      else setErro(tratarErro(e));
    }
  }, [id, periodo, tratarErro]);

  useEffect(() => {
    const sinal = { cancelado: false };
    void carregar(sinal);
    return () => { sinal.cancelado = true; };
  }, [carregar]);

  if (naoExiste) return <NaoEncontrada />;
  const h = historico && String(historico.produto.id) === id ? historico : null;
  if (h === null && !erro) return <Carregando />;

  return (
    <section className="space-y-6">
      {erro && (
        <div role="alert" className="alert alert-error">
          <span>{erro}</span>
          <button type="button" className="btn btn-sm" onClick={() => void carregar()}>Tentar de novo</button>
        </div>
      )}
      {h && (
        <>
          <div className="flex flex-wrap items-start gap-4">
            {h.produto.imagem && <img src={h.produto.imagem} alt="" className="h-24 w-24 rounded object-contain" />}
            <div className="flex-1 space-y-2">
              <h1 className="text-2xl font-bold">{h.produto.nome}</h1>
              <div className="flex flex-wrap gap-2">
                {h.produto.edicao && <span className="badge badge-ghost">{h.produto.edicao}</span>}
                <span className="badge badge-primary">
                  {h.recorrencia_30d === 0
                    ? "nenhuma oportunidade em 30 dias"
                    : `${h.recorrencia_30d}ª oportunidade em 30 dias`}
                </span>
                {h.quase_la && <span className="badge badge-warning">quase lá</span>}
              </div>
              <div className="flex flex-wrap gap-2">
                <a className="btn btn-sm" href={h.produto.url_liga} target="_blank" rel="noreferrer">Ver na Liga</a>
                {h.anuncio && (
                  <a className="btn btn-primary btn-sm" href={h.anuncio.url} target="_blank" rel="noreferrer">Ver na Amazon</a>
                )}
              </div>
            </div>
            <SeletorPeriodo valor={periodo} aoMudar={setPeriodo} />
          </div>
          <CurvaPreco historico={h} destaque={destaque} />
          <section aria-labelledby="titulo-historico" className="space-y-3">
            <h2 id="titulo-historico" className="text-xl font-semibold">Oportunidades deste produto</h2>
            {h.oportunidades.length === 0 && <p className="opacity-70">Nenhuma oportunidade no período</p>}
            {h.oportunidades.length > 0 && (
              <ul className="list bg-base-100 rounded-box shadow-sm md:hidden">
                {h.oportunidades.map((o) => (
                  <li key={o.id} className={o.id === destaque ? "list-row bg-base-200" : "list-row"}>
                    <div className="list-col-grow space-y-1">
                      <div>{dataHora(o.aberta_em)} · durou {duracao(o.duracao_min)}</div>
                      <div className="text-xs opacity-70">
                        {o.alertas} alertas · {reais(o.preco_alertado)} → {reais(o.menor_preco)} · {pct(o.desconto_pct)}
                      </div>
                    </div>
                    <MotivoSelo motivo={o.motivo} aberta={o.aberta} />
                  </li>
                ))}
              </ul>
            )}
            {h.oportunidades.length > 0 && (
              <div className="hidden overflow-x-auto md:block">
                <table className="table table-sm">
                  <thead>
                    <tr><th>Abriu</th><th>Durou</th><th>Alertas</th><th>Alerta</th><th>Menor</th><th>Desconto</th><th>Motivo</th></tr>
                  </thead>
                  <tbody>
                    {h.oportunidades.map((o) => (
                      <tr key={o.id} className={o.id === destaque ? "bg-base-200" : undefined}>
                        <td>{dataHora(o.aberta_em)}</td>
                        <td>{duracao(o.duracao_min)}</td>
                        <td>{o.alertas}</td>
                        <td>{reais(o.preco_alertado)}</td>
                        <td>{reais(o.menor_preco)}</td>
                        <td>{pct(o.desconto_pct)}</td>
                        <td><MotivoSelo motivo={o.motivo} aberta={o.aberta} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </section>
  );
}
