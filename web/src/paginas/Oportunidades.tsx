// Área de negócio: números do período, ativas, quase lá, encerradas e oportunidades por dia. Só dado de mercado.
// As ativas recarregam a cada 60 s; o resto ao abrir e ao trocar o período, o motivo ou a página.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { chamarApi } from "../api";
import { Carregando } from "../componentes/Carregando";
import { MotivoSelo } from "../componentes/MotivoSelo";
import { SeletorPeriodo } from "../componentes/SeletorPeriodo";
import { useCoresTema } from "../cores";
import { dataCurta, dataHora, duracao, pct, reais, ROTULOS_MOTIVO } from "../formato";
import { useSessao } from "../sessao";
import type {
  AtivasOportunidades, EncerradasOportunidades, Motivo, Periodo, QuaseOportunidades, ResumoOportunidades,
} from "../tipos";

const TEXTO_PERIODO: Record<Periodo, string> = {
  "7d": "nos últimos 7 dias", "30d": "nos últimos 30 dias", "90d": "nos últimos 90 dias", tudo: "até agora",
};

function minutosDesde(iso: string): number {
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 60000));
}

export function Oportunidades() {
  const { tratarErro } = useSessao();
  const cores = useCoresTema();
  const [periodo, setPeriodo] = useState<Periodo>("7d");
  const [motivo, setMotivo] = useState<Motivo | "">("");
  const [pagina, setPagina] = useState(1);
  const [resumo, setResumo] = useState<ResumoOportunidades | null>(null);
  const [ativas, setAtivas] = useState<AtivasOportunidades | null>(null);
  const [quase, setQuase] = useState<QuaseOportunidades | null>(null);
  const [todasQuase, setTodasQuase] = useState(false);
  const [encerradas, setEncerradas] = useState<EncerradasOportunidades | null>(null);
  const [erroPrincipal, setErroPrincipal] = useState<string | null>(null);
  const [erroAtivas, setErroAtivas] = useState<string | null>(null);
  const erro = erroPrincipal ?? erroAtivas;

  const carregar = useCallback(async (sinal?: { cancelado: boolean }) => {
    setErroPrincipal(null);
    try {
      const filtroMotivo = motivo ? `&motivo=${motivo}` : "";
      const [r, e] = await Promise.all([
        chamarApi<ResumoOportunidades>(`/api/oportunidades/resumo?periodo=${periodo}`),
        chamarApi<EncerradasOportunidades>(
          `/api/oportunidades/encerradas?periodo=${periodo}&pagina=${pagina}${filtroMotivo}`,
        ),
      ]);
      if (sinal?.cancelado) return;
      setResumo(r);
      setEncerradas(e);
    } catch (e) {
      if (sinal?.cancelado) return;
      setErroPrincipal(tratarErro(e));
    }
  }, [periodo, motivo, pagina, tratarErro]);

  const carregarAtivas = useCallback(async (sinal?: { cancelado: boolean }) => {
    try {
      const caminhoQuase = todasQuase ? "/api/oportunidades/quase" : "/api/oportunidades/quase?limite=20";
      const [a, q] = await Promise.all([
        chamarApi<AtivasOportunidades>("/api/oportunidades/ativas"),
        chamarApi<QuaseOportunidades>(caminhoQuase),
      ]);
      if (sinal?.cancelado) return;
      setAtivas(a);
      setQuase(q);
      setErroAtivas(null);
    } catch (e) {
      if (sinal?.cancelado) return;
      setErroAtivas(tratarErro(e));
    }
  }, [todasQuase, tratarErro]);

  useEffect(() => {
    const sinal = { cancelado: false };
    void carregar(sinal);
    return () => { sinal.cancelado = true; };
  }, [carregar]);
  useEffect(() => {
    const sinal = { cancelado: false };
    void carregarAtivas(sinal);
    const id = window.setInterval(() => void carregarAtivas(sinal), 60_000);
    return () => {
      sinal.cancelado = true;
      window.clearInterval(id);
    };
  }, [carregarAtivas]);

  function trocarPeriodo(p: Periodo) {
    setPagina(1);
    setPeriodo(p);
  }

  function trocarMotivo(valor: string) {
    setPagina(1);
    setMotivo(valor as Motivo | "");
  }

  const n = resumo?.numeros;
  const paginas = encerradas ? Math.max(1, Math.ceil(encerradas.total / encerradas.por_pagina)) : 1;

  if (resumo === null && !erro) return <Carregando />;

  const girando = <span className="loading loading-spinner" role="status" aria-label="Carregando seção" />;

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">Oportunidades</h1>
        <SeletorPeriodo valor={periodo} aoMudar={trocarPeriodo} />
      </div>

      {erro && (
        <div role="alert" className="alert alert-error">
          <span>{erro}</span>
          <button type="button" className="btn btn-sm" onClick={() => { void carregar(); void carregarAtivas(); }}>
            Tentar de novo
          </button>
        </div>
      )}

      {n && (
        <div className="stats stats-vertical lg:stats-horizontal w-full shadow-sm">
          <div className="stat">
            <div className="stat-title">Diferença bruta</div>
            <div className="stat-value text-primary">{reais(n.diferenca_bruta)}</div>
            <div className="stat-desc">antes de taxas e frete</div>
          </div>
          <div className="stat">
            <div className="stat-title">Oportunidades</div>
            <div className="stat-value">{n.oportunidades}</div>
            <div className="stat-desc">{n.produtos} produtos</div>
          </div>
          <div className="stat">
            <div className="stat-title">Desconto médio</div>
            <div className="stat-value">{pct(n.desconto_medio)}</div>
          </div>
          <div className="stat">
            <div className="stat-title">Duração média</div>
            <div className="stat-value">{duracao(n.duracao_media_min)}</div>
          </div>
        </div>
      )}
      {n && n.oportunidades === 0 && <p className="opacity-70">Nenhuma oportunidade {TEXTO_PERIODO[periodo]}</p>}

      <section aria-labelledby="titulo-ativas" className="space-y-3">
        <h2 id="titulo-ativas" className="text-xl font-semibold">Ativas agora</h2>
        {ativas === null && girando}
        {ativas && ativas.ativas.length === 0 && (
          <p className="opacity-70">
            Nenhuma oportunidade aberta agora
            {ativas.ultima_aberta_em && <> · a última abriu em {dataHora(ativas.ultima_aberta_em)}</>}
          </p>
        )}
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {ativas?.ativas.map((a) => {
            const imagem = a.produto.imagem ?? a.anuncio.imagem;
            return (
              <div key={a.id} className="card bg-base-100 shadow-sm">
                {imagem && (
                  <figure className="h-40 bg-base-200">
                    <img src={imagem} alt="" className="h-full object-contain" />
                  </figure>
                )}
                <div className="card-body gap-2">
                  <h3 className="card-title text-base">{a.produto.nome}</h3>
                  <p>
                    <span className="text-lg font-bold">{reais(a.preco_amazon)}</span>
                    <span className="opacity-70"> · Liga {reais(a.preco_liga)}</span>
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <span className="badge badge-primary">{pct(a.desconto_pct)}</span>
                    <span className="badge badge-ghost">aberta há {duracao(minutosDesde(a.aberta_em))}</span>
                    {a.em_risco_desde && (
                      <span className="badge badge-warning">em risco desde {dataHora(a.em_risco_desde)}</span>
                    )}
                  </div>
                  <div className="card-actions justify-end">
                    <a className="btn btn-primary btn-sm" href={a.anuncio.url} target="_blank" rel="noreferrer">
                      Ver na Amazon
                    </a>
                    <Link className="btn btn-ghost btn-sm" to={`/produtos/${a.produto.id}`}>Histórico do produto</Link>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section aria-labelledby="titulo-quase" className="space-y-3">
        <h2 id="titulo-quase" className="text-xl font-semibold">Quase lá</h2>
        {quase === null && girando}
        {quase && quase.itens.length === 0 && (
          <p className="opacity-70">Nenhum produto entre {quase.piso_pct}% e {quase.desconto_min_pct}% de desconto agora</p>
        )}
        {quase && quase.itens.length > 0 && (
          <ul className="list bg-base-100 rounded-box shadow-sm md:hidden">
            {quase.itens.map((q) => (
              <li key={q.produto.id} className="list-row">
                <div className="list-col-grow">
                  <Link className="link" to={`/produtos/${q.produto.id}`}>{q.produto.nome}</Link>
                  <div className="text-xs opacity-70">
                    {pct(q.desconto_pct)} · faltam {reais(q.falta_reais)} ({pct(q.falta_pp)})
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
        {quase && quase.itens.length > 0 && (
          <div className="hidden overflow-x-auto md:block">
            <table className="table table-sm">
              <thead><tr><th>Produto</th><th>Desconto</th><th>Falta</th></tr></thead>
              <tbody>
                {quase.itens.map((q) => (
                  <tr key={q.produto.id}>
                    <td><Link className="link" to={`/produtos/${q.produto.id}`}>{q.produto.nome}</Link></td>
                    <td>{pct(q.desconto_pct)}</td>
                    <td>faltam {reais(q.falta_reais)} ({pct(q.falta_pp)})</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {quase && !todasQuase && quase.itens.length === 20 && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setTodasQuase(true)}>Ver todas</button>
        )}
      </section>

      <section aria-labelledby="titulo-encerradas" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="titulo-encerradas" className="text-xl font-semibold">Encerradas no período</h2>
          <select
            className="select select-sm w-auto"
            aria-label="Motivo"
            value={motivo}
            onChange={(ev) => trocarMotivo(ev.target.value)}
          >
            <option value="">Todos os motivos</option>
            {(Object.keys(ROTULOS_MOTIVO) as Motivo[]).map((m) => (
              <option key={m} value={m}>{ROTULOS_MOTIVO[m]}</option>
            ))}
          </select>
        </div>
        {encerradas === null && girando}
        {encerradas && encerradas.itens.length === 0 && <p className="opacity-70">Nenhuma encerrada {TEXTO_PERIODO[periodo]}</p>}
        {encerradas && encerradas.itens.length > 0 && (
          <ul className="list bg-base-100 rounded-box shadow-sm md:hidden">
            {encerradas.itens.map((e) => (
              <li key={e.id} className="list-row">
                <div className="list-col-grow space-y-1">
                  <div>
                    {e.produto.ativo
                      ? <Link className="link" to={`/produtos/${e.produto.id}?oportunidade=${e.id}`}>{e.produto.nome}</Link>
                      : e.produto.nome}
                  </div>
                  <div className="text-xs opacity-70">
                    {dataHora(e.aberta_em)} · durou {duracao(e.duracao_min)} · {pct(e.desconto_pct)}
                  </div>
                  <div className="text-xs opacity-70">{reais(e.preco_alertado)} → {reais(e.menor_preco)}</div>
                </div>
                <MotivoSelo motivo={e.motivo} aberta={e.aberta} />
              </li>
            ))}
          </ul>
        )}
        {encerradas && encerradas.itens.length > 0 && (
          <div className="hidden overflow-x-auto md:block">
            <table className="table table-sm">
              <thead>
                <tr><th>Produto</th><th>Abriu</th><th>Durou</th><th>Alerta → menor</th><th>Desconto</th><th>Motivo</th></tr>
              </thead>
              <tbody>
                {encerradas.itens.map((e) => (
                  <tr key={e.id}>
                    <td>
                      {e.produto.ativo
                        ? <Link className="link" to={`/produtos/${e.produto.id}?oportunidade=${e.id}`}>{e.produto.nome}</Link>
                        : e.produto.nome}
                    </td>
                    <td>{dataHora(e.aberta_em)}</td>
                    <td>{duracao(e.duracao_min)}</td>
                    <td>{reais(e.preco_alertado)} → {reais(e.menor_preco)}</td>
                    <td>{pct(e.desconto_pct)}</td>
                    <td><MotivoSelo motivo={e.motivo} aberta={e.aberta} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {paginas > 1 && (
          <div className="join">
            <button type="button" className="btn btn-sm join-item" disabled={pagina <= 1} onClick={() => setPagina(pagina - 1)}>«</button>
            <span className="btn btn-sm join-item">Página {pagina} de {paginas}</span>
            <button type="button" className="btn btn-sm join-item" disabled={pagina >= paginas} onClick={() => setPagina(pagina + 1)}>»</button>
          </div>
        )}
      </section>

      {resumo && resumo.por_dia.length > 0 && (
        <section aria-labelledby="titulo-por-dia" className="space-y-3">
          <h2 id="titulo-por-dia" className="text-xl font-semibold">Oportunidades por dia</h2>
          <div className="h-56 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={resumo.por_dia.map((d) => ({ ...d, rotulo: dataCurta(`${d.dia}T12:00:00`) }))}>
                <XAxis dataKey="rotulo" stroke={cores.texto} fontSize={12} />
                <YAxis allowDecimals={false} stroke={cores.texto} fontSize={12} width={28} />
                <Tooltip />
                <Bar dataKey="oportunidades" name="Oportunidades" fill={cores.primaria} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}
    </section>
  );
}
