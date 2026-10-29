// Gestão: as ofertas da Amazon contra o "À partir de" da Liga, uma por produto. Filtros e página ficam na URL.
// Celular: um cartão por produto; computador: tabela enxuta. O que é detalhe (origem do casamento, Prime, importado,
// vendedor, composição do preço conferido) fica no tooltip, para a linha não empilhar selos.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { chamarApi } from "../../api";
import { Carregando } from "../../componentes/Carregando";
import { Foto } from "../../componentes/Foto";
import { useFiltrosUrl } from "../../filtrosUrl";
import { dataHora, pct2, reais, reaisComSinal } from "../../formato";
import { useSessao } from "../../sessao";
import type { ListaOfertas, OfertaGestao } from "../../tipos";

export const PADROES_OFERTAS = {
  busca: "", categoria: "", desconto_min: "", vendedor: "todos", situacao: "todas", ordem: "desconto", pagina: "1",
};
const ORDEM_CHAVES = ["busca", "categoria", "desconto_min", "vendedor", "situacao", "ordem", "pagina"] as const;
const ESPERA_MS = 350;

const VENDEDORES: Record<string, string> = {
  todos: "Todos os vendedores", amazon: "Vendido pela Amazon", fba: "Lojista FBA", elegiveis: "Só elegíveis",
};
const SITUACOES: Record<string, string> = { todas: "Todas", abertas: "Só oportunidades abertas" };
const ORDENS: Record<string, string> = {
  desconto: "Maior desconto", diferenca: "Maior diferença em R$", recentes: "Leitura mais recente", nome: "Nome",
};
const ENVIOS: Record<string, string> = { amazon: "Amazon", fba: "FBA", proprio: "Lojista", desconhecido: "—" };
const ORIGENS: Record<string, string> = {
  manual: "manual", sugerido_ia: "sugerido pela IA", automatico_ia: "automático pela IA", outro_confirmado: "outro produto",
};

/** Query canônica da API: ordem fixa, vazios e valores padrão fora (a página vai sempre). */
export function montarQueryOfertas(filtros: Record<string, string>): string {
  const partes: string[] = [];
  for (const k of ORDEM_CHAVES) {
    if (k !== "pagina" && (filtros[k] === "" || filtros[k] === PADROES_OFERTAS[k])) continue;
    partes.push(`${k}=${encodeURIComponent(filtros[k])}`);
  }
  return partes.join("&");
}

function fraseConferido(o: OfertaGestao): { curta: string; detalhe: string } | null {
  const c = o.conferido;
  if (!c) return null;
  const partes: string[] = [];
  if (c.impostos !== null) partes.push(`impostos ${reais(c.impostos)} inclusos`);
  if (c.frete !== null) partes.push(`frete ${reais(c.frete)} à parte`);
  return {
    curta: c.impostos !== null ? `conferido ${reais(c.preco)} com impostos` : `conferido ${reais(c.preco)}`,
    detalhe: `Conferido no checkout: ${reais(c.preco)}${partes.length ? ` (${partes.join("; ")})` : ""}`,
  };
}

function rotuloVendedor(o: OfertaGestao): string {
  if (!o.verificado) return "não verificado";
  return o.confiavel ? ENVIOS[o.envio] : `${ENVIOS[o.envio]} (não elegível)`;
}

function dicaVendedor(o: OfertaGestao): string {
  const partes: string[] = [];
  if (o.vendedor.nome) partes.push(`Vendedor: ${o.vendedor.nome}`);
  if (!o.verificado) partes.push("preço lido só na busca");
  if (o.origem) partes.push(`casamento ${ORIGENS[o.origem] ?? o.origem}`);
  if (o.importada) partes.push(`importado${o.origem_envio ? ` (${o.origem_envio === "Estados Unidos" ? "EUA" : o.origem_envio})` : ""}`);
  if (o.prime) partes.push("Prime");
  return partes.join(" · ") || "Sem detalhes do vendedor";
}

export function Ofertas() {
  const { tratarErro } = useSessao();
  const [filtros, mudar] = useFiltrosUrl(PADROES_OFERTAS);
  const [texto, setTexto] = useState(filtros.busca);
  const [textoDesconto, setTextoDesconto] = useState(filtros.desconto_min);
  const [dados, setDados] = useState<ListaOfertas | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [recarga, setRecarga] = useState(0);
  const caminho = `/api/gestao/ofertas?${montarQueryOfertas(filtros)}`;
  const caminhoAtual = useRef(caminho);
  caminhoAtual.current = caminho;

  useEffect(() => { setTexto(filtros.busca); }, [filtros.busca]);
  useEffect(() => { setTextoDesconto(filtros.desconto_min); }, [filtros.desconto_min]);
  useEffect(() => {
    if (texto === filtros.busca) return;
    const id = window.setTimeout(() => mudar({ busca: texto.trim() }), ESPERA_MS);
    return () => window.clearTimeout(id);
  }, [texto, filtros.busca, mudar]);
  useEffect(() => {
    if (textoDesconto === filtros.desconto_min) return;
    // Só números de 0 a 100 vão para a API; o resto espera o usuário terminar de digitar.
    if (textoDesconto !== "" && !(/^\d{1,3}$/.test(textoDesconto) && Number(textoDesconto) <= 100)) return;
    const id = window.setTimeout(() => mudar({ desconto_min: textoDesconto }), ESPERA_MS);
    return () => window.clearTimeout(id);
  }, [textoDesconto, filtros.desconto_min, mudar]);

  useEffect(() => {
    const sinal = { cancelado: false };
    setErro(null);
    chamarApi<ListaOfertas>(caminho).then(
      (r) => { if (!sinal.cancelado) setDados(r); },
      (e: unknown) => { if (!sinal.cancelado) setErro(tratarErro(e)); },
    );
    return () => { sinal.cancelado = true; };
  }, [caminho, recarga, tratarErro]);

  const filtrado = Object.keys(PADROES_OFERTAS).some(
    (k) => k !== "pagina" && filtros[k as keyof typeof PADROES_OFERTAS] !== PADROES_OFERTAS[k as keyof typeof PADROES_OFERTAS],
  );
  const pagina = dados?.pagina ?? (Number(filtros.pagina) || 1);
  const paginas = dados ? Math.max(1, Math.ceil(dados.total / dados.por_pagina)) : 1;
  const minimo = dados?.desconto_min_pct ?? null;
  const chipAtivo = minimo !== null && filtros.desconto_min === String(minimo);

  function limpar() {
    setTexto(""); setTextoDesconto("");
    mudar({ busca: "", categoria: "", desconto_min: "", vendedor: "todos", situacao: "todas", ordem: "desconto" });
  }

  if (dados === null && !erro) return <Carregando />;

  const desconto = (o: OfertaGestao) => {
    if (o.desconto_pct === null) return <span className="opacity-60">—</span>;
    const n = Number(o.desconto_pct);
    const cor =
      minimo !== null && n >= minimo ? "badge badge-sm badge-success tabular-nums"
        : n > 0 ? "badge badge-sm badge-warning tabular-nums"
          : "badge badge-sm badge-error badge-outline tabular-nums";
    return <span className={cor}>{pct2(o.desconto_pct)}</span>;
  };
  const estado = (o: OfertaGestao) => (
    <div className="flex min-w-0 items-center gap-1">
      {o.aberta && <span className="badge badge-success badge-sm shrink-0">oportunidade</span>}
      {o.risco && (
        <div className="tooltip min-w-0" data-tip={`Em risco desde ${dataHora(o.risco.desde)}: ${o.risco.motivo}`}>
          <span className="badge badge-warning badge-sm block max-w-full truncate">
            em risco desde {dataHora(o.risco.desde)} · {o.risco.motivo}
          </span>
        </div>
      )}
    </div>
  );
  const conferido = (o: OfertaGestao) => {
    const f = fraseConferido(o);
    return f ? (
      <div className="tooltip block max-w-full" data-tip={f.detalhe}>
        <span className="block truncate text-xs tabular-nums opacity-70">{f.curta}</span>
      </div>
    ) : (
      <span className="block text-xs opacity-60">não conferido</span>
    );
  };
  const precoAmazon = (o: OfertaGestao) => (
    <a className="link tabular-nums" href={o.anuncio.url} target="_blank" rel="noopener noreferrer">{reais(o.preco)}</a>
  );
  const vendedor = (o: OfertaGestao) => (
    <div className="tooltip max-w-full" data-tip={dicaVendedor(o)}>
      <span className={o.confiavel && o.verificado ? "badge badge-sm badge-success max-w-full truncate" : "badge badge-sm badge-ghost max-w-full truncate"}>
        {rotuloVendedor(o)}
      </span>
    </div>
  );
  const diferenca = (o: OfertaGestao) => (
    <span className="tabular-nums">{reaisComSinal(o.diferenca)}</span>
  );
  const nomeEAsin = (o: OfertaGestao) => (
    <div className="min-w-0">
      <div className="tooltip max-w-full" data-tip={o.produto}>
        <Link className="link block truncate" to={`/gestao/produtos/${o.produto_id}`}>{o.produto}</Link>
      </div>
      <div className="truncate font-mono text-xs opacity-60">{o.anuncio.asin}</div>
    </div>
  );

  return (
    <section className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold">Ofertas</h1>
        {dados && <p className="text-sm opacity-70">Amazon × LigaMagic · {dados.total} {dados.total === 1 ? "produto" : "produtos"}</p>}
      </div>

      <fieldset className="fieldset grid grid-cols-1 gap-3 rounded-box bg-base-100 p-3 shadow-sm sm:grid-cols-2 lg:grid-cols-4">
        <legend className="fieldset-legend">Filtros</legend>
        <input
          type="search" className="input w-full sm:col-span-2" aria-label="Buscar" placeholder="Buscar produto"
          value={texto} onChange={(ev) => setTexto(ev.target.value)}
        />
        <select className="select w-full" aria-label="Categoria" value={filtros.categoria}
          onChange={(ev) => mudar({ categoria: ev.target.value })}>
          <option value="">Todas as categorias</option>
          {(dados?.categorias ?? []).map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <input
          type="number" min={0} max={100} inputMode="numeric" className="input w-full" aria-label="Desconto mínimo (%)"
          placeholder="Desconto mínimo (%)" value={textoDesconto} onChange={(ev) => setTextoDesconto(ev.target.value)}
        />
        <select className="select w-full" aria-label="Vendedor" value={filtros.vendedor}
          onChange={(ev) => mudar({ vendedor: ev.target.value })}>
          {Object.entries(VENDEDORES).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
        </select>
        <select className="select w-full" aria-label="Situação" value={filtros.situacao}
          onChange={(ev) => mudar({ situacao: ev.target.value })}>
          {Object.entries(SITUACOES).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
        </select>
        <select className="select w-full" aria-label="Ordem" value={filtros.ordem}
          onChange={(ev) => mudar({ ordem: ev.target.value })}>
          {Object.entries(ORDENS).map(([v, r]) => <option key={v} value={v}>{r}</option>)}
        </select>
        {minimo !== null && (
          <div className="flex items-center">
            <button
              type="button" aria-pressed={chipAtivo}
              className={chipAtivo ? "btn btn-sm btn-soft btn-primary" : "btn btn-sm btn-soft"}
              onClick={() => mudar({ desconto_min: chipAtivo ? "" : String(minimo) })}
            >
              ≥ desconto configurado ({minimo}%)
            </button>
          </div>
        )}
      </fieldset>

      {erro && (
        <div role="alert" className="alert alert-error">
          <span>{erro}</span>
          <button type="button" className="btn btn-sm" onClick={() => setRecarga((n) => n + 1)}>Tentar de novo</button>
          {filtrado && <button type="button" className="btn btn-sm" onClick={limpar}>Limpar filtros</button>}
        </div>
      )}

      {dados && !erro && dados.itens.length === 0 && (
        <div className="space-y-3 py-6 text-center">
          <p className="opacity-70">{filtrado ? "Nenhuma oferta com esses filtros" : "Nenhuma oferta no momento"}</p>
          {filtrado && (
            <button type="button" className="btn btn-sm" onClick={limpar}>Limpar filtros</button>
          )}
        </div>
      )}

      {dados && !erro && dados.itens.length > 0 && (
        <>
          <ul className="list rounded-box bg-base-100 shadow-sm lg:hidden" aria-label="Ofertas">
            {dados.itens.map((o) => (
              <li key={o.produto_id} className="list-row">
                <Foto src={o.imagem} alt={o.produto} tamanho="p" />
                <div className="list-col-grow min-w-0 space-y-1">
                  {nomeEAsin(o)}
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                    <span className="tabular-nums opacity-70">Liga {reais(o.preco_liga)}</span>
                    <span>Amazon {precoAmazon(o)}</span>
                    {desconto(o)}
                    <span className="text-xs opacity-70">{o.diferenca !== null && <>dif. {diferenca(o)}</>}</span>
                  </div>
                  {conferido(o)}
                  {estado(o)}
                  <div className="flex min-w-0 items-center gap-2 text-xs">
                    {vendedor(o)}
                    <span className="opacity-60">{dataHora(o.coletado_em)}</span>
                  </div>
                </div>
              </li>
            ))}
          </ul>
          <div className="hidden lg:block">
            <table className="table table-sm w-full">
              <thead>
                <tr>
                  <th>Produto</th><th className="text-right">Liga</th><th className="text-right">Amazon</th>
                  <th className="text-right">Desconto</th><th className="text-right">Diferença</th><th>Vendedor</th>
                  <th className="hidden xl:table-cell">Lido em</th>
                </tr>
              </thead>
              <tbody>
                {dados.itens.map((o) => (
                  <tr key={o.produto_id}>
                    <td className="w-full max-w-0">
                      <div className="flex min-w-0 items-center gap-2">
                        <Foto src={o.imagem} alt={o.produto} tamanho="p" />
                        <div className="min-w-0 space-y-1">{nomeEAsin(o)}{estado(o)}</div>
                      </div>
                    </td>
                    <td className="whitespace-nowrap text-right tabular-nums">{reais(o.preco_liga)}</td>
                    <td className="max-w-48 text-right">{precoAmazon(o)}{conferido(o)}</td>
                    <td className="text-right">{desconto(o)}</td>
                    <td className="whitespace-nowrap text-right">{diferenca(o)}</td>
                    <td className="max-w-40">{vendedor(o)}</td>
                    <td className="hidden whitespace-nowrap opacity-70 xl:table-cell">{dataHora(o.coletado_em)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!erro && paginas > 1 && (
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
