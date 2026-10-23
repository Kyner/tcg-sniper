// Gestão: catálogo da Liga (ativos e inativos). Busca, filtros e página ficam na URL; a chave de cada linha liga e
// desliga o monitoramento no lugar; marcar linhas (ou "todos do filtro") abre a barra de lote.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { chamarApi, ErroApi } from "../../api";
import { Carregando } from "../../componentes/Carregando";
import { Foto } from "../../componentes/Foto";
import { ModalConfirmarLote } from "../../componentes/ModalConfirmarLote";
import { useFiltrosUrl } from "../../filtrosUrl";
import { dataComAno, pct, reais } from "../../formato";
import { useSessao } from "../../sessao";
import type { LinhaCatalogo, ListaCatalogo, LoteCatalogo } from "../../tipos";

export const PADROES_CATALOGO = {
  busca: "", monitorado: "todos", categoria: "", situacao: "", preco_liga: "todos", pagina: "1",
};
const ORDEM_CHAVES = ["busca", "monitorado", "categoria", "situacao", "preco_liga", "pagina"] as const;
const ESPERA_BUSCA_MS = 350;

const MONITORADOS: Record<string, string> = { todos: "Todos", sim: "Monitorados", nao: "Não monitorados" };
const SITUACOES: Record<string, string> = {
  "": "Qualquer situação", casado: "Casado", esperando_decisao: "Esperando decisão", so_ignorados: "Só ignorados",
  sem_candidato: "Sem candidato",
};
const PRECOS_LIGA: Record<string, string> = {
  todos: "Com ou sem preço", com: "Com preço", esgotado: "Esgotado (com anúncio casado)",
};

/** Query canônica: ordem fixa, vazios e o "preco_liga" padrão fora; a mesma vai para a API, para o produto e para o "voltar". */
export function montarQueryCatalogo(filtros: Record<string, string>, comPagina: boolean): string {
  const partes: string[] = [];
  for (const k of ORDEM_CHAVES) {
    if (k === "pagina" && !comPagina) continue;
    if (filtros[k] === "" || (k === "preco_liga" && filtros[k] === PADROES_CATALOGO.preco_liga)) continue;
    partes.push(`${k}=${encodeURIComponent(filtros[k])}`);
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
  const [carregadoDe, setCarregadoDe] = useState<string | null>(null);
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
  // Sempre o caminho da tela agora: respostas que voltam depois de uma troca de filtro são descartadas.
  const caminhoAtual = useRef(caminho);
  caminhoAtual.current = caminho;
  // A lista na tela só vale para a seleção quando foi carregada para o filtro de agora.
  const listaAtual = dados !== null && carregadoDe === caminho;

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
      (r) => { if (!sinal.cancelado) { setDados(r); setCarregadoDe(caminho); } },
      (e: unknown) => { if (!sinal.cancelado) setErro(tratarErro(e)); },
    );
    return () => { sinal.cancelado = true; };
  }, [caminho, recarga, tratarErro]);

  const filtroLote = useCallback(() => ({
    busca: filtros.busca, monitorado: filtros.monitorado, categoria: filtros.categoria || null,
    situacao: filtros.situacao || null, preco_liga: filtros.preco_liga,
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
    setMarcados(valor && dados && listaAtual ? new Set(dados.itens.map((i) => i.id)) : new Set());
  }

  function limparSelecao() { setMarcados(new Set()); setTodoFiltro(null); }

  function corpoLote(acao: "ligar" | "desligar", esperado: number, confirmar: boolean) {
    return todoFiltro !== null
      ? { acao, filtro: filtroLote(), esperado, confirmar }
      : { acao, ids: [...marcados], esperado, confirmar };
  }

  async function selecionarTodosDoFiltro() {
    const de = caminho;
    setAviso(null);
    try {
      const r = await chamarApi<LoteCatalogo>("/api/gestao/catalogo/lote", {
        metodo: "POST", corpo: { acao: "desligar", filtro: filtroLote(), esperado: 0, confirmar: false },
      });
      if (caminhoAtual.current === de) setTodoFiltro(r.alvo);
    } catch (e) {
      if (caminhoAtual.current !== de) return;
      setAviso(tratarErro(e) ?? "Não foi possível contar os produtos do filtro.");
    }
  }

  async function confirmarLote() {
    if (!lote) return;
    const de = caminho;
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
          if (caminhoAtual.current !== de) return; // a lista mudou: a seleção e o modal já foram descartados
          if (todoFiltro !== null) setTodoFiltro(r.alvo);
          setLote({ acao: lote.acao, alvo: r.alvo, aviso: e.message });
        } catch (e2) {
          if (caminhoAtual.current !== de) return;
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
  const todosDaPagina = listaAtual && !!dados && dados.itens.length > 0 && dados.itens.every((i) => estaMarcado(i.id));

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
      checked={estaMarcado(p.id)} disabled={todoFiltro !== null || !listaAtual} onChange={(ev) => marcar(p.id, ev.target.checked)}
    />
  );
  const esgotado = listaAtual && filtros.preco_liga === "esgotado";
  const diferenca = (p: LinhaCatalogo) => (
    <span className={Number(p.diferenca_media_pct) > 0 ? "badge badge-success badge-sm" : "badge badge-ghost badge-sm"}>
      {pct(p.diferenca_media_pct)}
    </span>
  );
  const semVendedor = (p: LinhaCatalogo) => (p.sem_vendedor_desde ? dataComAno(p.sem_vendedor_desde) : "sem registro de preço");
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
        <select className="select w-full" aria-label="Preço na Liga" value={filtros.preco_liga}
          onChange={(ev) => mudar({ preco_liga: ev.target.value })}>
          {Object.entries(PRECOS_LIGA).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
        </select>
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
            <button type="button" className="btn btn-sm" onClick={() => { setTexto(""); mudar({ busca: "", monitorado: "todos", categoria: "", situacao: "", preco_liga: "todos" }); }}>
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
                  disabled={todoFiltro !== null || !listaAtual} onChange={(ev) => marcarPagina(ev.target.checked)} />
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
                  {esgotado && (
                    <div className="flex flex-wrap items-center gap-1 text-xs">
                      <span>Amazon {reais(p.melhor_amazon)} · média Liga {reais(p.medio_liga)}</span>
                      {diferenca(p)}
                      <span className="opacity-70">sem vendedor desde {semVendedor(p)}</span>
                    </div>
                  )}
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
                  <th></th><th>Produto</th><th>Categoria</th><th>Preço Liga</th><th>Melhor Amazon</th>
                  {esgotado && <><th>Média Liga</th><th>Diferença</th><th>Sem vendedor desde</th></>}
                  <th>Situação</th>
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
                    {esgotado && <><td>{reais(p.medio_liga)}</td><td>{diferenca(p)}</td><td>{semVendedor(p)}</td></>}
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
                <button type="button" className="btn btn-sm" disabled={!listaAtual} onClick={() => void selecionarTodosDoFiltro()}>
                  Selecionar todos os {dados.total} do filtro
                </button>
              )}
              <button type="button" className="btn btn-sm btn-success" disabled={!listaAtual} onClick={() => setLote({ acao: "ligar", alvo: nSel, aviso: null })}>Ligar</button>
              <button type="button" className="btn btn-sm btn-warning" disabled={!listaAtual} onClick={() => setLote({ acao: "desligar", alvo: nSel, aviso: null })}>Desligar</button>
              <button type="button" className="btn btn-sm btn-ghost" onClick={limparSelecao}>Limpar seleção</button>
            </div>
          </div>
        </section>
      )}

      {lote && (
        <ModalConfirmarLote
          acao={lote.acao} alvo={lote.alvo} aviso={lote.aviso} ocupado={enviando}
          aoConfirmar={() => void confirmarLote()} aoFechar={() => { if (!enviando) setLote(null); }}
        />
      )}
    </section>
  );
}
