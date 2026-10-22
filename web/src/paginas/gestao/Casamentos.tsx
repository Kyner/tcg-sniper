// Gestão: lista de produtos da Liga para revisar casamentos. Busca, filtros, ordem e página ficam na URL.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { chamarApi } from "../../api";
import { Carregando } from "../../componentes/Carregando";
import { Foto } from "../../componentes/Foto";
import { useFiltrosUrl } from "../../filtrosUrl";
import { reais } from "../../formato";
import { useSessao } from "../../sessao";
import type { ListaCasamentos, ProdutoCasamento } from "../../tipos";

const PADROES = {
  busca: "", situacao: "esperando_decisao", categoria: "", com_preco: "", ordem: "preco_liga", pagina: "1",
};
const ORDEM_CHAVES = ["busca", "situacao", "categoria", "com_preco", "ordem", "pagina"] as const;
const ESPERA_BUSCA_MS = 350;

const SITUACOES: Record<string, string> = {
  esperando_decisao: "Esperando decisão", casado: "Casado", so_ignorados: "Só ignorados",
  sem_candidato: "Sem candidato", todos: "Todos",
};
const ORDENS: Record<string, string> = { preco_liga: "Preço da Liga", pendentes: "Mais pendentes", nome: "Nome" };

function montarQuery(filtros: Record<string, string>, comPagina: boolean): string {
  const partes: string[] = [];
  for (const k of ORDEM_CHAVES) {
    if (k === "pagina" && !comPagina) continue;
    if (filtros[k] !== "") partes.push(`${k}=${encodeURIComponent(filtros[k])}`);
  }
  return partes.join("&");
}

function Contagens({ p }: { p: ProdutoCasamento }) {
  return (
    <div className="flex flex-wrap gap-1">
      <span className="badge badge-warning badge-sm" title="Pendentes">{p.pendentes} pend.</span>
      <span className="badge badge-success badge-sm" title="Confirmados">{p.confirmados} conf.</span>
      <span className="badge badge-ghost badge-sm" title="Ignorados">{p.ignorados} ign.</span>
      {p.ia_sugere > 0 && <span className="badge badge-info badge-sm" title="A IA sugere">IA {p.ia_sugere}</span>}
    </div>
  );
}

function Situacao({ valor }: { valor: string }) {
  const texto = SITUACOES[valor] ?? valor;
  return (
    <div className="tooltip tooltip-left max-w-full" data-tip={texto}>
      <span className="badge badge-outline block max-w-full truncate">{texto}</span>
    </div>
  );
}

export function Casamentos() {
  const { tratarErro } = useSessao();
  const [filtros, mudar] = useFiltrosUrl(PADROES);
  const [texto, setTexto] = useState(filtros.busca);
  const [dados, setDados] = useState<ListaCasamentos | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const caminho = `/api/gestao/casamentos?${montarQuery(filtros, true)}`;
  const queryRevisao = montarQuery(filtros, true);

  useEffect(() => { setTexto(filtros.busca); }, [filtros.busca]);
  useEffect(() => {
    if (texto === filtros.busca) return;
    const id = window.setTimeout(() => mudar({ busca: texto.trim() }), ESPERA_BUSCA_MS);
    return () => window.clearTimeout(id);
  }, [texto, filtros.busca, mudar]);

  const carregar = useCallback(async (sinal?: { cancelado: boolean }) => {
    setErro(null);
    try {
      const r = await chamarApi<ListaCasamentos>(caminho);
      if (sinal?.cancelado) return;
      setDados(r);
    } catch (e) {
      if (sinal?.cancelado) return;
      setErro(tratarErro(e));
    }
  }, [caminho, tratarErro]);

  useEffect(() => {
    const sinal = { cancelado: false };
    void carregar(sinal);
    return () => { sinal.cancelado = true; };
  }, [carregar]);

  const filtrado = Object.keys(PADROES).some((k) => k !== "pagina" && filtros[k as keyof typeof PADROES] !== PADROES[k as keyof typeof PADROES]);
  const pagina = Number(filtros.pagina) || 1;
  const paginas = dados ? Math.max(1, Math.ceil(dados.total / dados.por_pagina)) : 1;
  const linkRevisao = (id: number) => `/gestao/casamentos/${id}${queryRevisao ? `?${queryRevisao}` : ""}`;

  if (dados === null && !erro) return <Carregando />;

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">Casamentos</h1>
        {dados && dados.itens.length > 0 && (
          <Link className="btn btn-primary btn-sm" to={linkRevisao(dados.itens[0].id)}>Revisar em sequência</Link>
        )}
      </div>

      <fieldset className="fieldset grid grid-cols-1 gap-3 rounded-box bg-base-100 p-3 shadow-sm sm:grid-cols-2 lg:grid-cols-5">
        <legend className="fieldset-legend">Filtros</legend>
        <input
          type="search" className="input w-full" aria-label="Buscar" placeholder="Buscar produto"
          value={texto} onChange={(ev) => setTexto(ev.target.value)}
        />
        <select className="select w-full" aria-label="Situação" value={filtros.situacao}
          onChange={(ev) => mudar({ situacao: ev.target.value })}>
          {Object.entries(SITUACOES).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
        </select>
        <select className="select w-full" aria-label="Categoria" value={filtros.categoria}
          onChange={(ev) => mudar({ categoria: ev.target.value })}>
          <option value="">Todas as categorias</option>
          {(dados?.categorias ?? []).map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select className="select w-full" aria-label="Ordenar por" value={filtros.ordem}
          onChange={(ev) => mudar({ ordem: ev.target.value })}>
          {Object.entries(ORDENS).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
        </select>
        <label className="label cursor-pointer justify-start gap-2">
          <input type="checkbox" className="checkbox checkbox-sm" checked={filtros.com_preco === "true"}
            onChange={(ev) => mudar({ com_preco: ev.target.checked ? "true" : "" })} />
          <span>Só com preço</span>
        </label>
      </fieldset>

      {erro && (
        <div role="alert" className="alert alert-error">
          <span>{erro}</span>
          <button type="button" className="btn btn-sm" onClick={() => void carregar()}>Tentar de novo</button>
        </div>
      )}

      {dados && dados.itens.length === 0 && !erro && (
        <div className="space-y-3 py-6 text-center">
          <p className="opacity-70">{filtrado ? "Nenhum produto com esses filtros" : "Nenhum produto para revisar"}</p>
          {filtrado && (
            <button type="button" className="btn btn-sm" onClick={() => { setTexto(""); mudar({ busca: "", situacao: PADROES.situacao, categoria: "", com_preco: "", ordem: PADROES.ordem }); }}>
              Limpar filtros
            </button>
          )}
        </div>
      )}

      {dados && dados.itens.length > 0 && (
        <>
          <ul className="list rounded-box bg-base-100 shadow-sm md:hidden" aria-label="Produtos">
            {dados.itens.map((p) => (
              <li key={p.id} className="list-row">
                <Foto src={p.imagem} alt={p.nome} tamanho="p" />
                <div className="list-col-grow min-w-0 space-y-1">
                  <Link className="link block truncate" to={linkRevisao(p.id)}>{p.nome}</Link>
                  <div className="text-xs opacity-70">{reais(p.preco_liga)}{p.categoria ? ` · ${p.categoria}` : ""}</div>
                  <Contagens p={p} />
                  <Situacao valor={p.situacao} />
                </div>
              </li>
            ))}
          </ul>
          <div className="hidden md:block">
            <table className="table table-sm">
              <thead>
                <tr><th></th><th>Produto</th><th>Categoria</th><th>Preço Liga</th><th>Anúncios</th><th>Situação</th></tr>
              </thead>
              <tbody>
                {dados.itens.map((p) => (
                  <tr key={p.id}>
                    <td><Foto src={p.imagem} alt={p.nome} tamanho="p" /></td>
                    <td className="max-w-xs">
                      <div className="tooltip max-w-full" data-tip={p.nome}>
                        <Link className="link block truncate" to={linkRevisao(p.id)}>{p.nome}</Link>
                      </div>
                    </td>
                    <td>{p.categoria ?? "—"}</td>
                    <td>{reais(p.preco_liga)}</td>
                    <td><Contagens p={p} /></td>
                    <td className="max-w-40"><Situacao valor={p.situacao} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {paginas > 1 && (
        <div className="join">
          <button type="button" className="btn btn-sm join-item" disabled={pagina <= 1}
            onClick={() => mudar({ pagina: String(pagina - 1) })}>«</button>
          <span className="btn btn-sm join-item">Página {pagina} de {paginas}</span>
          <button type="button" className="btn btn-sm join-item" disabled={pagina >= paginas}
            onClick={() => mudar({ pagina: String(pagina + 1) })}>»</button>
        </div>
      )}
    </section>
  );
}
