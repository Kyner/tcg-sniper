// Gestão: os seis serviços, cada um com selo de estado, a chave ligar/desligar e as ações. Cartões no celular e tabela a
// partir de md (o mesmo HTML, com classes responsivas). Toda ação atualiza a lista no lugar; a lista se recarrega a cada 60 s.
import { Fragment, useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { chamarApi } from "../../api";
import { Carregando } from "../../componentes/Carregando";
import { SeloEstado } from "../../componentes/SeloEstado";
import { dataHora, horaMinuto } from "../../formato";
import { useSessao } from "../../sessao";
import type { AcaoServico, ListaServicos, ResultadoServico, ServicoGestao } from "../../tipos";

const RECARGA_MS = 60_000;
const BASE = "/api/gestao/servicos";

function textoTransicao(s: ServicoGestao): string | null {
  const t = s.transicao;
  if (t === null) return null;
  if (t.tipo === "parando") return "parando…";
  if (t.tipo === "iniciando") return "iniciando…";
  return t.desde === null ? "parado de verdade" : `parado de verdade desde ${horaMinuto(t.desde)}`;
}

export function Servicos() {
  const { pode, tratarErro } = useSessao();
  const podeAgir = pode("pausar_servicos");
  const [dados, setDados] = useState<ListaServicos | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [mensagem, setMensagem] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [recarga, setRecarga] = useState(0);

  useEffect(() => {
    const sinal = { cancelado: false };
    setErro(null);
    chamarApi<ListaServicos>(BASE).then(
      (r) => { if (!sinal.cancelado) setDados(r); },
      (e: unknown) => { if (!sinal.cancelado) setErro(tratarErro(e)); },
    );
    return () => { sinal.cancelado = true; };
  }, [recarga, tratarErro]);

  // A cada minuto a lista se atualiza em silêncio: se falhar, a tela segue com o que já tem.
  useEffect(() => {
    let vivo = true;
    const timer = setInterval(() => {
      chamarApi<ListaServicos>(BASE).then((r) => { if (vivo) setDados(r); }, () => undefined);
    }, RECARGA_MS);
    return () => { vivo = false; clearInterval(timer); };
  }, []);

  const agir = useCallback(async (caminho: string) => {
    setOcupado(true);
    setErro(null);
    try {
      const r = await chamarApi<ResultadoServico>(`${BASE}/${caminho}`, { metodo: "POST" });
      setMensagem(r.mensagem);
      setDados(await chamarApi<ListaServicos>(BASE));
    } catch (e) {
      setMensagem(null);
      setErro(tratarErro(e));
    } finally {
      setOcupado(false);
    }
  }, [tratarErro]);

  if (dados === null && !erro) return <Carregando />;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Serviços</h1>
      {erro && (
        <div role="alert" className="alert alert-error">
          <span>{erro}</span>
          {dados === null && (
            <button type="button" className="btn btn-sm" onClick={() => setRecarga((n) => n + 1)}>Tentar de novo</button>
          )}
        </div>
      )}
      {mensagem && (
        <div role="status" className="alert alert-info">
          <span>{mensagem}</span>
        </div>
      )}
      {dados && (
        <table className="table">
          <thead className="hidden md:table-header-group">
            <tr>
              <th>Serviço</th><th>Agora</th><th>Último ok</th><th>Chave</th><th>Ações</th>
            </tr>
          </thead>
          <tbody className="block md:table-row-group">
            {dados.servicos.map((s) => (
              <Linha key={s.id} s={s} podeAgir={podeAgir} ocupado={ocupado} agir={agir} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

interface LinhaProps { s: ServicoGestao; podeAgir: boolean; ocupado: boolean; agir: (caminho: string) => void }

function Linha({ s, podeAgir, ocupado, agir }: LinhaProps) {
  const tem = (a: AcaoServico) => s.acoes.includes(a);
  const transicao = textoTransicao(s);
  const caminhoChave = `${s.id}/${s.ligado ? "desligar" : "ligar"}`;
  return (
    <Fragment>
      <tr className="mb-3 block rounded-box border border-base-300 bg-base-100 p-3 md:mb-0 md:table-row md:rounded-none md:border-0 md:bg-transparent md:p-0">
        <td className="flex items-center justify-between gap-2 border-0 p-0 md:table-cell md:p-3">
          <span className="font-medium">{s.nome}</span>
          <span className="flex items-center gap-2">
            <SeloEstado estado={s.estado} />
            {transicao && <span className="text-xs text-base-content/70">{transicao}</span>}
          </span>
        </td>
        <td className="block min-w-0 p-0 py-1 md:table-cell md:max-w-xs md:p-3">
          <div className="tooltip tooltip-bottom block w-full text-left" data-tip={s.detalhe}>
            <span className="block truncate text-sm">{s.agora}</span>
          </div>
        </td>
        <td className="block p-0 text-xs text-base-content/70 md:table-cell md:p-3 md:text-sm">
          {s.ultimo_ok ? `Último ok ${dataHora(s.ultimo_ok)}` : "Sem registro ainda"}
        </td>
        <td className="block p-0 py-1 md:table-cell md:p-3">
          {podeAgir && (
            <input
              type="checkbox"
              className="toggle toggle-success"
              aria-label={`${s.ligado ? "Desligar" : "Ligar"} ${s.nome}`}
              checked={s.ligado}
              disabled={ocupado || !(tem("ligar") || tem("desligar"))}
              onChange={() => agir(caminhoChave)}
            />
          )}
        </td>
        <td className="block p-0 pt-2 md:table-cell md:p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Link className="btn btn-sm btn-ghost" to={`/gestao/atividade?${s.atividade}`}>Atividade</Link>
            {podeAgir && s.abrir && (
              <div className="tooltip" data-tip="Só abre neste PC">
                <a className="btn btn-sm" href={s.abrir} target="_blank" rel="noreferrer">Abrir</a>
              </div>
            )}
            {podeAgir && tem("rodar_agora") && (
              <button type="button" className="btn btn-sm" disabled={ocupado} onClick={() => agir(`${s.id}/rodar-agora`)}>
                Rodar agora
              </button>
            )}
            {podeAgir && tem("retomar") && (
              <button type="button" className="btn btn-sm btn-warning" disabled={ocupado} onClick={() => agir(`${s.id}/retomar`)}>
                Retomar
              </button>
            )}
          </div>
        </td>
      </tr>
      {s.sub && <SubLinha s={s} sub={s.sub} podeAgir={podeAgir} ocupado={ocupado} agir={agir} />}
    </Fragment>
  );
}

function SubLinha({ sub, podeAgir, ocupado, agir }: LinhaProps & { sub: NonNullable<ServicoGestao["sub"]> }) {
  const base = "amazon_monitor";
  return (
    <tr className="mb-3 block rounded-box bg-base-200 p-3 md:mb-0 md:table-row md:rounded-none">
      <td colSpan={5} className="block p-0 md:table-cell md:p-3">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          {podeAgir ? (
            <>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="toggle toggle-sm toggle-success"
                  aria-label={`${sub.monitor_ligado ? "Desligar" : "Ligar"} monitor de preço`}
                  checked={sub.monitor_ligado}
                  disabled={ocupado}
                  onChange={() => agir(`${base}/monitor/${sub.monitor_ligado ? "desligar" : "ligar"}`)}
                />
                monitor de preço
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="toggle toggle-sm toggle-success"
                  aria-label={`${sub.checkout_ligado ? "Desligar" : "Ligar"} conferência de checkout`}
                  checked={sub.checkout_ligado}
                  disabled={ocupado}
                  onChange={() => agir(`${base}/checkout/${sub.checkout_ligado ? "desligar" : "ligar"}`)}
                />
                conferência de checkout
              </label>
            </>
          ) : (
            <>
              <span className="badge badge-ghost">{sub.monitor_ligado ? "monitor de preço: ligado" : "monitor de preço: desligado"}</span>
              <span className="badge badge-ghost">{sub.checkout_ligado ? "conferência de checkout: ligada" : "conferência de checkout: desligada"}</span>
            </>
          )}
          {sub.checkout_parado && (
            <>
              <span className="text-sm text-warning">Checkout parado: conta sem login.</span>
              {podeAgir && (
                <button type="button" className="btn btn-sm btn-warning" disabled={ocupado} onClick={() => agir(`${base}/checkout/retomar`)}>
                  Retomar checkout
                </button>
              )}
            </>
          )}
        </div>
        {sub.carrinho.length > 0 && (
          <div className="mt-3">
            <p className="text-sm font-medium">Carrinho a conferir</p>
            <ul className="mt-1 space-y-1">
              {sub.carrinho.map((c) => (
                <li key={c.conferencia_id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                  <span className="min-w-0">
                    <span className="block truncate">{c.produto}</span>
                    <span className="text-xs text-base-content/70">
                      {c.asin}{c.em ? ` · desde ${dataHora(c.em)}` : ""}
                    </span>
                  </span>
                  {podeAgir && (
                    <button type="button" className="btn btn-sm" disabled={ocupado} onClick={() => agir(`carrinho/${c.conferencia_id}/conferido`)}>
                      Já conferi
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </td>
    </tr>
  );
}
