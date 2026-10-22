// Gestão: catálogo da Liga (ativos e inativos). Busca, filtros e página ficam na URL; a chave de cada linha liga e
// desliga o monitoramento no lugar; marcar linhas (ou "todos do filtro") abre a barra de lote.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { chamarApi, ErroApi } from "../../api";
import { Carregando } from "../../componentes/Carregando";
import { Foto } from "../../componentes/Foto";
import { ModalConfirmarLote } from "../../componentes/ModalConfirmarLote";
import { useFiltrosUrl } from "../../filtrosUrl";
import { reais } from "../../formato";
import { useSessao } from "../../sessao";
import type { LinhaCatalogo, ListaCatalogo, LoteCatalogo } from "../../tipos";

export const PADROES_CATALOGO = { busca: "", monitorado: "todos", categoria: "", situacao: "", com_preco: "", pagina: "1" };
const ORDEM_CHAVES = ["busca", "monitorado", "categoria", "situacao", "com_preco", "pagina"] as const;
const ESPERA_BUSCA_MS = 350;

const MONITORADOS: Record<string, string> = { todos: "Todos", sim: "Monitorados", nao: "Não monitorados" };
const SITUACOES: Record<string, string> = {
  "": "Qualquer situação", casado: "Casado", esperando_decisao: "Esperando decisão", so_ignorados: "Só ignorados",
  sem_candidato: "Sem candidato",
};

/** Query canônica: ordem fixa e vazios fora; a mesma vai para a API, para o produto e para o "voltar". */
export function montarQueryCatalogo(filtros: Record<string, string>, comPagina: boolean): string {
  const partes: string[] = [];
  for (const k of ORDEM_CHAVES) {
    if (k === "pagina" && !comPagina) continue;
    if (filtros[k] !== "") partes.push(`${k}=${encodeURIComponent(filtros[k])}`);
  }
  return partes.join("&");
}

interface Lote { acao: "ligar" | "desligar"; alvo: number; aviso: string | null }

export function Catalogo() {
  const { pode, tratarErro } = useSessao();
  const podeEditar = pode("editar_catalogo");
  const [filtros, mudar] = useFiltrosUrl(PADROES_CATALOGO);
  const [texto, setTexto] = useState(filtros.busca);
  const [dados, setDados] = useState<ListaCatalogo | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [recarga, setRecarga] = useState(0);
  const [ocupados, setOcupados] = useState<Set<number>>(new Set());
  const [marcados, setMarcados] = useState<Set<number>>(new Set());
  const [todoFiltro, setTodoFiltro] = useState<number | null>(null);
  const [lote, setLote] = useState<Lote | null>(null);
  const [enviando, setEnviando] = useState(false);
  const query = montarQueryCatalogo(filtros, true);
  const caminho = `/api/gestao/catalogo?${query}`;

  useEffect(() => { setTexto(filtros.busca); }, [filtros.busca]);
  useEffect(() => {
    if (texto === filtros.busca) return;
    const id = window.setTimeout(() => mudar({ busca: texto.trim() }), ESPERA_BUSCA_MS);
    return () => window.clearTimeout(id);
  }, [texto, filtros.busca, mudar]);

  // Outra lista (filtro ou página): a seleção anterior não vale mais.
  useEffect(() => { setMarcados(new Set()); setTodoFiltro(null); setLote(null); }, [caminho]);

  useEffect(() => {
    const sinal = { cancelado: false };
    setErro(null);
    chamarApi<ListaCatalogo>(caminho).then(
      (r) => { if (!sinal.cancelado) setDados(r); },
      (e: unknown) => { if (!sinal.cancelado) setErro(tratarErro(e)); },
    );
    return () => { sinal.cancelado = true; };
  }, [caminho, recarga, tratarErro]);

  const filtroLote = useCallback(() => ({
    busca: filtros.busca, monitorado: filtros.monitorado, categoria: filtros.categoria || null,
    situacao: filtros.situacao || null, com_preco: filtros.com_preco === "true",
  }), [filtros]);

  async function alternar(p: LinhaCatalogo) {
    const novo = !p.monitorado;
    const pinta = (valor: boolean) =>
      setDados((d) => d && { ...d, itens: d.itens.map((i) => (i.id === p.id ? { ...i, monitorado: valor } : i)) });
    setAviso(null);
    setOcupados((o) => new Set(o).add(p.id));
    pinta(novo);
    try {
      await chamarApi(`/api/gestao/produtos/${p.id}`, { metodo: "PATCH", corpo: { ativo: novo } });
    } catch (e) {
      pinta(p.monitorado);
      setAviso(tratarErro(e) ?? "Não foi possível alterar o produto.");
    } finally {
      setOcupados((o) => { const n = new Set(o); n.delete(p.id); return n; });
    }
  }

  function marcar(id: number, valor: boolean) {
    setMarcados((m) => { const n = new Set(m); if (valor) n.add(id); else n.delete(id); return n; });
  }

  function marcarPagina(valor: boolean) {
    setMarcados(valor && dados ? new Set(dados.itens.map((i) => i.id)) : new Set());
  }

  function limparSelecao() { setMarcados(new Set()); setTodoFiltro(null); }

  function corpoLote(acao: "ligar" | "desligar", esperado: number, confirmar: boolean) {
    return todoFiltro !== null
      ? { acao, filtro: filtroLote(), esperado, confirmar }
      : { acao, ids: [...marcados], esperado, confirmar };
  }

  async function selecionarTodosDoFiltro() {
    setAviso(null);
    try {
      const r = await chamarApi<LoteCatalogo>("/api/gestao/catalogo/lote", {
        metodo: "POST", corpo: { acao: "desligar", filtro: filtroLote(), esperado: 0, confirmar: false },
      });
      setTodoFiltro(r.alvo);
    } catch (e) {
      setAviso(tratarErro(e) ?? "Não foi possível contar os produtos do filtro.");
    }
  }

  async function confirmarLote() {
    if (!lote) return;
    setEnviando(true);
    try {
      await chamarApi<LoteCatalogo>("/api/gestao/catalogo/lote", { metodo: "POST", corpo: corpoLote(lote.acao, lote.alvo, true) });
      setLote(null);
      limparSelecao();
      setRecarga((n) => n + 1);
    } catch (e) {
      if (e instanceof ErroApi && e.status === 409 && e.erro === "contagem_mudou") {
        try {
          const r = await chamarApi<LoteCatalogo>("/api/gestao/catalogo/lote", {
            metodo: "POST", corpo: corpoLote(lote.acao, 0, false),
          });
          if (todoFiltro !== null) setTodoFiltro(r.alvo);
          setLote({ acao: lote.acao, alvo: r.alvo, aviso: e.message });
        } catch (e2) {
          setLote(null);
          setAviso(tratarErro(e2) ?? "Não foi possível conferir a contagem.");
        }
      } else {
        setLote(null);
        setAviso(tratarErro(e) ?? "Não foi possível aplicar a ação.");
      }
    } finally {
      setEnviando(false);
    }
  }

  const filtrado = Object.keys(PADROES_CATALOGO).some(
    (k) => k !== "pagina" && filtros[k as keyof typeof PADROES_CATALOGO] !== PADROES_CATALOGO[k as keyof typeof PADROES_CATALOGO],
  );
  const pagina = Number(filtros.pagina) || 1;
  const paginas = dados ? Math.max(1, Math.ceil(dados.total / dados.por_pagina)) : 1;
  const linkProduto = (id: number) => `/gestao/produtos/${id}${query ? `?${query}` : ""}`;
  const nSel = todoFiltro ?? marcados.size;
  const textoSel = `${nSel} ${nSel === 1 ? "selecionado" : "selecionados"}`;
  const estaMarcado = (id: number) => todoFiltro !== null || marcados.has(id);
  const todosDaPagina = !!dados && dados.itens.length > 0 && dados.itens.every((i) => estaMarcado(i.id));

  if (dados === null && !erro) return <Carregando />;

  const chave = (p: LinhaCatalogo) => podeEditar && (
    <input
      type="checkbox" className="toggle toggle-success toggle-sm" aria-label={`Monitorar ${p.nome}`}
      checked={p.monitorado} disabled={ocupados.has(p.id)} onChange={() => void alternar(p)}
    />
  );
  const caixa = (p: LinhaCatalogo) => podeEditar && (
    <input
      type="checkbox" className="checkbox checkbox-sm" aria-label={`Selecionar ${p.nome}`}
      checked={estaMarcado(p.id)} disabled={todoFiltro !== null} onChange={(ev) => marcar(p.id, ev.target.checked)}
    />
  );
  const situacao = (p: LinhaCatalogo) => (
    <span className="badge badge-outline badge-sm">{SITUACOES[p.situacao] ?? p.situacao}</span>
  );

  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-bold">Catálogo</h1>

      <fieldset className="fieldset grid grid-cols-1 gap-3 rounded-box bg-base-100 p-3 shadow-sm sm:grid-cols-2 lg:grid-cols-5">
        <legend className="fieldset-legend">Filtros</legend>
        <input
          type="search" className="input w-full" aria-label="Buscar" placeholder="Buscar produto"
          value={texto} onChange={(ev) => setTexto(ev.target.value)}
        />
        <select className="select w-full" aria-label="Monitoramento" value={filtros.monitorado}
          onChange={(ev) => mudar({ monitorado: ev.target.value })}>
          {Object.entries(MONITORADOS).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
        </select>
        <select className="select w-full" aria-label="Categoria" value={filtros.categoria}
          onChange={(ev) => mudar({ categoria: ev.target.value })}>
          <option value="">Todas as categorias</option>
          {(dados?.categorias ?? []).map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select className="select w-full" aria-label="Situação" value={filtros.situacao}
          onChange={(ev) => mudar({ situacao: ev.target.value })}>
          {Object.entries(SITUACOES).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
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
          <button type="button" className="btn btn-sm" onClick={() => setRecarga((n) => n + 1)}>Tentar de novo</button>
        </div>
      )}
      {aviso && (
        <div role="alert" className="alert alert-error">
          <span>{aviso}</span>
          <button type="button" className="btn btn-sm" onClick={() => setAviso(null)}>Fechar</button>
        </div>
      )}

      {dados && dados.itens.length === 0 && !erro && (
        <div className="space-y-3 py-6 text-center">
          <p className="opacity-70">{filtrado ? "Nenhum produto com esses filtros" : "O catálogo está vazio"}</p>
          {filtrado && (
            <button type="button" className="btn btn-sm" onClick={() => { setTexto(""); mudar({ busca: "", monitorado: "todos", categoria: "", situacao: "", com_preco: "" }); }}>
              Limpar filtros
            </button>
          )}
        </div>
      )}

      {dados && dados.itens.length > 0 && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span className="opacity-70">{dados.total} {dados.total === 1 ? "produto" : "produtos"}</span>
            {podeEditar && (
              <label className="label cursor-pointer gap-2">
                <input type="checkbox" className="checkbox checkbox-sm" checked={todosDaPagina}
                  disabled={todoFiltro !== null} onChange={(ev) => marcarPagina(ev.target.checked)} />
                <span>Selecionar a página</span>
              </label>
            )}
          </div>
          <ul className="list rounded-box bg-base-100 shadow-sm md:hidden" aria-label="Produtos">
            {dados.itens.map((p) => (
              <li key={p.id} className="list-row">
                <Foto src={p.imagem} alt={p.nome} tamanho="p" />
                <div className="list-col-grow min-w-0 space-y-1">
                  <Link className="link block truncate" to={linkProduto(p.id)}>{p.nome}</Link>
                  <div className="text-xs opacity-70">
                    {reais(p.preco_liga)}{p.categoria ? ` · ${p.categoria}` : ""}
                  </div>
                  {situacao(p)}
                </div>
                {podeEditar && <div className="flex flex-col items-center gap-2">{chave(p)}{caixa(p)}</div>}
              </li>
            ))}
          </ul>
          <div className="hidden md:block">
            <table className="table table-sm">
              <thead>
                <tr>
                  {podeEditar && <th>Seleção</th>}
                  <th></th><th>Produto</th><th>Categoria</th><th>Preço Liga</th><th>Melhor Amazon</th><th>Situação</th>
                  {podeEditar && <th>Monitorar</th>}
                </tr>
              </thead>
              <tbody>
                {dados.itens.map((p) => (
                  <tr key={p.id}>
                    {podeEditar && <td>{caixa(p)}</td>}
                    <td><Foto src={p.imagem} alt={p.nome} tamanho="p" /></td>
                    <td className="max-w-xs">
                      <div className="tooltip max-w-full" data-tip={p.nome}>
                        <Link className="link block truncate" to={linkProduto(p.id)}>{p.nome}</Link>
                      </div>
                    </td>
                    <td>{p.categoria ?? "—"}</td>
                    <td>{reais(p.preco_liga)}</td>
                    <td>{reais(p.melhor_amazon)}</td>
                    <td>{situacao(p)}</td>
                    {podeEditar && <td>{chave(p)}</td>}
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

      {podeEditar && nSel > 0 && (
        <section aria-label="Ação em lote" className="sticky bottom-0 z-10">
          <div className="alert alert-info flex flex-wrap items-center justify-between gap-2">
            <span className="font-semibold">{textoSel}</span>
            <div className="flex flex-wrap gap-2">
              {todoFiltro === null && dados && dados.total > marcados.size && (
                <button type="button" className="btn btn-sm" onClick={() => void selecionarTodosDoFiltro()}>
                  Selecionar todos os {dados.total} do filtro
                </button>
              )}
              <button type="button" className="btn btn-sm btn-success" onClick={() => setLote({ acao: "ligar", alvo: nSel, aviso: null })}>Ligar</button>
              <button type="button" className="btn btn-sm btn-warning" onClick={() => setLote({ acao: "desligar", alvo: nSel, aviso: null })}>Desligar</button>
              <button type="button" className="btn btn-sm btn-ghost" onClick={limparSelecao}>Limpar seleção</button>
            </div>
          </div>
        </section>
      )}

      {lote && (
        <ModalConfirmarLote
          acao={lote.acao} alvo={lote.alvo} aviso={lote.aviso} ocupado={enviando}
          aoConfirmar={() => void confirmarLote()} aoFechar={() => setLote(null)}
        />
      )}
    </section>
  );
}
